import logging
import secrets
import string
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import get_current_admin, get_current_user, hash_password, verify_password
from ..services.alert_service import AlertService

logger = logging.getLogger("oncall.webhook_auth")

router = APIRouter()
nightingale_basic = HTTPBasic(auto_error=False)


def _ingest_open_event_payload(payload: Dict[str, Any], db: Session):
    service = AlertService(db)
    # Generic open-api/events payload keeps backward compatibility.
    if "source_key" in payload and "fingerprint" in payload:
        ingest_payload = schemas.AlertEventIngest.model_validate(payload)
        return service.ingest_event(ingest_payload)
    # Otherwise treat it as Nightingale-style payload.
    return service.ingest_nightingale_event(payload)


def _get_nightingale_auth_row(db: Session) -> models.NightingaleWebhookAuthConfig:
    row: Optional[models.NightingaleWebhookAuthConfig] = (
        db.query(models.NightingaleWebhookAuthConfig)
        .order_by(models.NightingaleWebhookAuthConfig.id.asc())
        .first()
    )
    if row:
        return row
    row = models.NightingaleWebhookAuthConfig(enabled=False, username=None, password_hash=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _verify_nightingale_auth(
    request: Request,
    credentials: Optional[HTTPBasicCredentials],
    db: Session,
):
    """Verify Nightingale webhook authentication.

    Supports three methods (checked in order):
    1. Standard HTTP Basic Auth (``Authorization: Basic …``)
    2. URL query-parameter token  (``?token=<password>``)
    3. Username / password embedded in the URL (userinfo)

    Method 2 exists because some Nightingale versions do NOT attach
    ``Authorization`` when the callback "授权用户名/授权密码" fields are
    filled in – a confirmed N9E quirk.  Using ``?token=`` lets operators
    paste a single URL without touching HTTP Headers.
    """
    row = (
        db.query(models.NightingaleWebhookAuthConfig)
        .order_by(models.NightingaleWebhookAuthConfig.id.asc())
        .first()
    )

    # Only enforce auth when switch is enabled and full credentials are configured.
    if not row or not row.enabled or not row.username or not row.password_hash:
        return  # auth disabled / not configured → allow

    # ── Method 1: standard Basic Auth ──
    if credentials:
        username_ok = credentials.username == row.username
        password_ok = verify_password(credentials.password or "", row.password_hash)
        if username_ok and password_ok:
            logger.info("webhook auth OK (Basic Auth) user=%r", credentials.username)
            return
        logger.warning(
            "webhook auth FAIL (Basic Auth): username_match=%s password_match=%s",
            username_ok, password_ok,
        )

    # ── Method 2: ?token=<password> query parameter ──
    token = request.query_params.get("token")
    if token and verify_password(token, row.password_hash):
        logger.info("webhook auth OK (URL token)")
        return
    if token:
        logger.warning("webhook auth FAIL: token param present but does not match")

    # ── nothing matched ──
    logger.warning("webhook auth: no valid credentials (Basic / token)")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid nightingale webhook credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


@router.get("/api/v1/lark-app-config", response_model=schemas.LarkAppConfigResponse, tags=["接入配置"])
def get_lark_app_config(
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.LarkAppConfig).order_by(models.LarkAppConfig.id.asc()).first()
    if row:
        return row

    row = models.LarkAppConfig(enabled=False, app_id=None, app_secret=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/api/v1/lark-app-config", response_model=schemas.LarkAppConfigResponse, tags=["接入配置"])
def upsert_lark_app_config(
    payload: schemas.LarkAppConfigUpsert,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.LarkAppConfig).order_by(models.LarkAppConfig.id.asc()).first()
    if not row:
        row = models.LarkAppConfig()
        db.add(row)
        db.flush()

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return row


@router.get("/api/v1/nightingale-webhook-auth", response_model=schemas.NightingaleWebhookAuthStatusResponse, tags=["接入配置"])
def get_nightingale_webhook_auth(
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    row = _get_nightingale_auth_row(db)
    effective_enabled = bool(row.enabled and row.username and row.password_hash)
    return {
        "enabled": effective_enabled,
        "username": row.username,
        "has_password": bool(row.password_hash),
        "updated_at": row.updated_at,
    }


@router.post("/api/v1/nightingale-webhook-auth/generate", response_model=schemas.NightingaleWebhookAuthGenerateResponse, tags=["接入配置"])
def generate_nightingale_webhook_auth(
    payload: schemas.NightingaleWebhookAuthGenerateRequest,
    request: Request,
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    row = _get_nightingale_auth_row(db)
    username = (payload.username or "").strip() or f"n9e_{secrets.token_hex(3)}"
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(24))

    row.enabled = True
    row.username = username
    row.password_hash = hash_password(password)
    db.commit()
    db.refresh(row)

    # Build a ready-to-paste webhook URL with ?token= for N9E compatibility.
    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/open-api/events?token={password}"

    return {
        "enabled": bool(row.enabled),
        "username": row.username,
        "has_password": True,
        "updated_at": row.updated_at,
        "password": password,
        "webhook_url": webhook_url,
    }


@router.post("/api/v1/nightingale-webhook-auth/disable", response_model=schemas.NightingaleWebhookAuthStatusResponse, tags=["接入配置"])
def disable_nightingale_webhook_auth(
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    row = _get_nightingale_auth_row(db)
    row.enabled = False
    row.username = None
    row.password_hash = None
    db.commit()
    db.refresh(row)
    return {
        "enabled": bool(row.enabled),
        "username": row.username,
        "has_password": bool(row.password_hash),
        "updated_at": row.updated_at,
    }


@router.get("/integrations", response_model=List[schemas.AlertSourceResponse], tags=["告警接入"])
def list_integrations(
    schedule_id: Optional[int] = Query(default=None),
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AlertService(db).list_sources(schedule_id=schedule_id)


@router.post("/integrations", response_model=schemas.AlertSourceResponse, tags=["告警接入"])
def upsert_integration(
    payload: schemas.AlertSourceUpsert,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AlertService(db).upsert_source(payload)


@router.post("/open-api/events", response_model=schemas.EventIngestResponse, tags=["开放接入"])
def ingest_event(
    request: Request,
    payload: Dict[str, Any],
    credentials: Optional[HTTPBasicCredentials] = Depends(nightingale_basic),
    db: Session = Depends(get_db),
):
    # Nightingale events require auth; generic events keep unauthenticated behavior.
    if not ("source_key" in payload and "fingerprint" in payload):
        _verify_nightingale_auth(request=request, credentials=credentials, db=db)
    return _ingest_open_event_payload(payload, db)


@router.get("/incidents", response_model=List[schemas.AlertIncidentResponse], tags=["告警运营"])
def list_incidents(
    schedule_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    related_only: bool = Query(default=False),
    keyword: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AlertService(db).list_incidents(
        schedule_id=schedule_id,
        status_value=status,
        user_id=user_id or current_user.id,
        related_only=related_only,
        keyword=keyword,
        skip=skip,
        limit=limit,
    )


@router.get("/incidents/{incident_id}", response_model=schemas.AlertIncidentDetailResponse, tags=["告警运营"])
def get_incident(
    incident_id: int,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AlertService(db).get_incident_detail(incident_id)


@router.post("/incidents/{incident_id}/ack", response_model=schemas.AlertIncidentDetailResponse, tags=["告警运营"])
def acknowledge_incident(
    incident_id: int,
    payload: schemas.IncidentActionRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.user_id is None:
        payload = payload.model_copy(update={"user_id": current_user.id})
    return AlertService(db).acknowledge_incident(incident_id, payload)


@router.post("/incidents/{incident_id}/resolve", response_model=schemas.AlertIncidentDetailResponse, tags=["告警运营"])
def resolve_incident(
    incident_id: int,
    payload: schemas.IncidentActionRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.user_id is None:
        payload = payload.model_copy(update={"user_id": current_user.id})
    return AlertService(db).resolve_incident(incident_id, payload)


@router.post("/incidents/{incident_id}/resend-lark-ticket", tags=["告警运营"])
def resend_lark_ticket(
    incident_id: int,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AlertService(db).resend_lark_ticket(incident_id)


@router.post("/incidents/{incident_id}/escalate-now", response_model=schemas.AlertIncidentDetailResponse, tags=["告警运营"])
def escalate_incident_now(
    incident_id: int,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = AlertService(db)
    service.escalate_incident_to_phone(incident_id, reason="manual")
    return service.get_incident_detail(incident_id)


