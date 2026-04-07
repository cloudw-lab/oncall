"""Keycloak provisioning helpers."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import not_
from sqlalchemy.orm import Session

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakAuthenticationError

from .. import models
from ..config import settings
from ..security import hash_password

logger = logging.getLogger(__name__)


class KeycloakSyncService:
    """Synchronize users and their groups from Keycloak into the local database."""

    def __init__(self, db: Session, admin_client: Optional[KeycloakAdmin] = None):
        self.db = db
        self.settings = settings
        self._admin = admin_client
        if not self.settings.KEYCLOAK_ENABLED and admin_client is None:
            raise RuntimeError("Keycloak 集成已关闭，无法执行同步")

    @property
    def admin(self) -> KeycloakAdmin:
        if self._admin is None:
            self._admin = self._build_admin_client()
        return self._admin

    def _build_admin_client(self) -> KeycloakAdmin:
        required = [
            self.settings.KEYCLOAK_SERVER_URL,
            self.settings.KEYCLOAK_REALM,
            self.settings.KEYCLOAK_ADMIN_USERNAME,
            self.settings.KEYCLOAK_ADMIN_PASSWORD,
        ]
        if not all(required):
            raise RuntimeError("Keycloak 配置不完整，缺少 server/realm/admin 账号信息")

        server_url = self.settings.KEYCLOAK_SERVER_URL.rstrip("/") + "/"
        try:
            return KeycloakAdmin(
                server_url=server_url,
                username=self.settings.KEYCLOAK_ADMIN_USERNAME,
                password=self.settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=self.settings.KEYCLOAK_REALM,
                verify=self.settings.KEYCLOAK_VERIFY_SSL,
                client_id=self.settings.KEYCLOAK_CLIENT_ID,
                client_secret_key=self.settings.KEYCLOAK_CLIENT_SECRET,
            )
        except KeycloakAuthenticationError as exc:  # pragma: no cover - requires real Keycloak
            raise RuntimeError("无法连接 Keycloak，请检查凭证") from exc

    def sync_users(self) -> Dict[str, Any]:
        """Pull users/groups from Keycloak and upsert locally."""
        stats = {"processed": 0, "created": 0, "updated": 0, "deactivated": 0}
        admin = self.admin
        now = datetime.now(timezone.utc)

        keycloak_users = admin.get_users({})
        seen_ids: set[str] = set()

        for kc_user in keycloak_users:
            stats["processed"] += 1
            kc_id = kc_user.get("id")
            if kc_id:
                seen_ids.add(kc_id)
            created = self._upsert_user(kc_user, now)
            if created:
                stats["created"] += 1
            else:
                stats["updated"] += 1

        if self.settings.KEYCLOAK_DISABLE_MISSING:
            query = self.db.query(models.User).filter(models.User.keycloak_id.isnot(None))
            if seen_ids:
                query = query.filter(not_(models.User.keycloak_id.in_(seen_ids)))
            missing = query.all()
            for user in missing:
                if user.is_active:
                    user.is_active = False
                    stats["deactivated"] += 1
                    logger.info("Keycloak user %s missing upstream -> disabled", user.username)

        self.db.commit()
        return stats

    def _upsert_user(self, kc_user: Dict[str, Any], synced_at: datetime) -> bool:
        kc_id = kc_user.get("id")
        username = kc_user.get("username") or kc_id
        email = self._resolve_email(kc_user, username)
        full_name = self._resolve_full_name(kc_user)
        enabled = kc_user.get("enabled", True)
        attributes = kc_user.get("attributes") or {}
        phone_attr = self._first_attr(attributes.get("phoneNumber") or attributes.get("phone"))
        team_attr = self._first_attr(attributes.get("team"))

        user = None
        if kc_id:
            user = self.db.query(models.User).filter(models.User.keycloak_id == kc_id).first()
        if not user and email:
            user = self.db.query(models.User).filter(models.User.email == email).first()
        if not user:
            user = self.db.query(models.User).filter(models.User.username == username).first()

        created = False
        if not user:
            user = models.User(
                username=username,
                email=email,
                full_name=full_name,
                team=team_attr or "SRE",
                role="operator",
                hashed_password=hash_password(secrets.token_urlsafe(32)),
            )
            created = True
            self.db.add(user)

        user.email = email
        user.full_name = full_name
        user.team = team_attr or user.team or "SRE"
        user.is_active = enabled
        user.keycloak_id = kc_id or user.keycloak_id
        user.keycloak_sync_at = synced_at
        user.keycloak_groups = self._fetch_group_names(kc_id)

        if phone_attr:
            user.phone_plain = phone_attr
        if self._should_be_admin(user.keycloak_groups):
            user.role = "admin"
        elif user.role not in {"admin", "operator"}:
            user.role = "operator"

        return created

    def _fetch_group_names(self, kc_id: Optional[str]) -> List[str]:
        if not kc_id:
            return []
        try:
            groups = self.admin.get_user_groups(kc_id)
        except Exception as exc:  # pragma: no cover - network error
            logger.warning("Failed to fetch groups for %s: %s", kc_id, exc)
            return []
        return [group.get("name") for group in groups if group.get("name")]

    @staticmethod
    def _resolve_email(kc_user: Dict[str, Any], fallback_username: str) -> str:
        email = kc_user.get("email") or kc_user.get("username")
        if email:
            return email
        return f"{fallback_username or kc_user.get('id')}@{settings.KEYCLOAK_REALM or 'keycloak'}.local"

    @staticmethod
    def _resolve_full_name(kc_user: Dict[str, Any]) -> str:
        first = kc_user.get("firstName") or ""
        last = kc_user.get("lastName") or ""
        name = (first + " " + last).strip()
        return name or kc_user.get("username") or kc_user.get("email") or "Keycloak 用户"

    @staticmethod
    def _first_attr(value: Any) -> Optional[str]:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return (value[0] if value else None)
        return value

    @staticmethod
    def _should_be_admin(groups: List[str]) -> bool:
        lowered = {g.lower() for g in groups}
        return any(name in lowered for name in {"admin", "oncall-admins", "oncall_admins"})
