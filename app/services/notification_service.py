from datetime import date, datetime
from textwrap import dedent
from typing import Dict, List, Optional, Set, Any
import json
import logging
from pathlib import Path
import httpx
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..config import settings
from .. import models
from .schedule_service import ScheduleService


class NotificationService:
    """通知服务"""
    LARK_API_BASE = "https://open.feishu.cn/open-apis"
    _lark_logger_initialized = False
    
    def __init__(self):
        self.smtp_enabled = settings.EMAIL_ENABLED and settings.SMTP_HOST
        self._ensure_lark_logger()

    def _ensure_lark_logger(self) -> None:
        """确保飞书发送日志只初始化一次。"""
        logger = logging.getLogger("notification.lark")
        if not NotificationService._lark_logger_initialized:
            log_dir = Path(settings.LOG_DIR or "logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_dir / "lark.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            logger.propagate = False
            NotificationService._lark_logger_initialized = True
        self.lark_logger = logger

    def _log_lark(self, event: str, **fields) -> None:
        if not hasattr(self, "lark_logger"):
            return
        safe_fields = {}
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, (int, float, bool)):
                safe_fields[key] = value
            else:
                safe_fields[key] = str(value)
        try:
            payload = json.dumps(safe_fields, ensure_ascii=False)
        except Exception:
            payload = str(safe_fields)
        self.lark_logger.info("%s %s", event, payload)
    
    def send_email(self, to_email: str, subject: str, body: str) -> Dict[str, Optional[str]]:
        """发送邮件通知"""
        if not self.smtp_enabled:
            print(f"[邮件通知] {to_email}: {subject}")
            return {
                "channel": "console",
                "status": "simulated",
                "recipient": to_email,
                "error_message": None,
            }
        
        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        try:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"邮件已发送至：{to_email}")
            return {
                "channel": "email",
                "status": "sent",
                "recipient": to_email,
                "error_message": None,
            }
        except Exception as e:
            print(f"邮件发送失败：{e}")
            return {
                "channel": "email",
                "status": "failed",
                "recipient": to_email,
                "error_message": str(e),
            }


    def _get_enabled_lark_app_config(self, db: Session) -> Optional[models.LarkAppConfig]:
        cfg = db.query(models.LarkAppConfig).order_by(models.LarkAppConfig.id.asc()).first()
        if not cfg or not cfg.enabled or not cfg.app_id or not cfg.app_secret:
            return None
        return cfg

    def _extract_lark_error(self, resp: httpx.Response) -> str:
        try:
            payload = resp.json()
        except Exception:
            return f"http {resp.status_code}: {resp.text[:200]}"

        code = payload.get("code")
        msg = payload.get("msg") or payload.get("message") or resp.text[:200]
        return f"http {resp.status_code}: code={code}, msg={msg}"

    def _normalize_nightingale_status_text(self, alert_data: Dict[str, Any]) -> str:
        is_recovered_flag = alert_data.get("is_recovered")
        if is_recovered_flag is True or str(is_recovered_flag).strip().lower() == "true":
            return "resolved"

        alert_status_raw = alert_data.get("alert_status")
        if isinstance(alert_status_raw, int) and alert_status_raw == 2:
            return "resolved"
        if str(alert_status_raw).strip().lower() == "2":
            return "resolved"

        resolved_markers = {"resolved", "recover", "recovered", "ok", "2"}
        status_raw = alert_data.get("status")
        event_status_raw = alert_data.get("event_status")
        status_text = str(status_raw or event_status_raw or "triggered").strip().lower()
        if status_text in resolved_markers:
            return "resolved"
        return "triggered"

    def _normalize_n9e_severity(self, alert_data: Dict[str, Any]) -> tuple[str, Optional[str]]:
        raw = alert_data.get("severity")
        if raw is None:
            raw = alert_data.get("level")
        if raw is None:
            raw = alert_data.get("priority")
        text = str(raw or "").strip().lower()

        if text in {"1", "p1", "sev1", "s1"}:
            return "critical", "L1"
        if text in {"2", "p2", "sev2", "s2"}:
            return "warning", "L2"
        if text in {"3", "p3", "sev3", "s3"}:
            return "info", "L3"
        if text in {"4", "p4", "sev4", "s4"}:
            return "debug", "L4"

        if text in {"critical", "warning", "info", "debug"}:
            return text, None
        return "critical", None

    def _get_lark_tenant_access_token(self, app_id: str, app_secret: str) -> str:
        # 验证凭证
        if not app_id or not app_secret:
            raise RuntimeError("Missing app_id or app_secret. Please configure Lark app credentials in /api/v1/lark-app-config")
        
        # 记录凭证信息（不记录秘密本身）
        self._log_lark(
            "token_request",
            app_id_len=len(app_id),
            app_secret_len=len(app_secret),
            endpoint="tenant_access_token/internal",
        )
        
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{self.LARK_API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
        
        if resp.status_code // 100 != 2:
            error_msg = self._extract_lark_error(resp)
            self._log_lark("token_failed", http_status=resp.status_code, error=error_msg)
            raise RuntimeError(error_msg)

        data = resp.json() or {}
        if data.get("code") not in (None, 0):
            error_msg = f"code={data.get('code')}, msg={data.get('msg')}"
            self._log_lark("token_failed", error=error_msg)
            raise RuntimeError(f"Lark API error: {error_msg}. Please verify app_id and app_secret are correct.")
        token = data.get("tenant_access_token") or (data.get("data") or {}).get("tenant_access_token")
        if not token:
            self._log_lark("token_failed", error="missing_tenant_access_token")
            raise RuntimeError("missing tenant_access_token in response")
        
        self._log_lark("token_success", token_len=len(token))
        return token

    def _lookup_lark_open_ids_by_email(self, tenant_access_token: str, emails: List[str]) -> Dict[str, str]:
        normalized = [email.strip().lower() for email in emails if email]
        if not normalized:
            return {}

        headers = {"Authorization": f"Bearer {tenant_access_token}"}
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{self.LARK_API_BASE}/contact/v3/users/batch_get_id?user_id_type=open_id",
                json={"emails": normalized},
                headers=headers,
            )
        if resp.status_code // 100 != 2:
            raise RuntimeError(self._extract_lark_error(resp))

        payload = resp.json() or {}
        if payload.get("code") not in (None, 0):
            raise RuntimeError(f"code={payload.get('code')}, msg={payload.get('msg')}")

        rows = (payload.get("data") or {}).get("user_list") or (payload.get("data") or {}).get("items") or []
        result: Dict[str, str] = {}
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            open_id = row.get("open_id") or row.get("user_id") or row.get("open_id_value")
            if email and open_id:
                result[email] = open_id
        return result

    def _list_lark_chat_member_open_ids(self, tenant_access_token: str, chat_id: str) -> Set[str]:
        if not chat_id:
            return set()

        headers = {"Authorization": f"Bearer {tenant_access_token}"}
        page_token = None
        open_ids: Set[str] = set()

        with httpx.Client(timeout=5.0) as client:
            while True:
                params = {"page_size": 100, "user_id_type": "open_id"}
                if page_token:
                    params["page_token"] = page_token
                resp = client.get(
                    f"{self.LARK_API_BASE}/im/v1/chats/{chat_id}/members",
                    params=params,
                    headers=headers,
                )
                if resp.status_code // 100 != 2:
                    raise RuntimeError(self._extract_lark_error(resp))

                payload = resp.json() or {}
                if payload.get("code") not in (None, 0):
                    raise RuntimeError(f"code={payload.get('code')}, msg={payload.get('msg')}")

                data = payload.get("data") or {}
                items = data.get("items") or data.get("member_list") or []
                for item in items:
                    open_id = item.get("member_id") or item.get("open_id") or item.get("user_id")
                    if open_id:
                        open_ids.add(str(open_id))

                if not data.get("has_more"):
                    break
                page_token = data.get("page_token")
                if not page_token:
                    break

        return open_ids

    def _resolve_lark_mentions(
        self,
        tenant_access_token: str,
        chat_id: str,
        mention_users: Optional[List[models.User]] = None,
    ) -> Dict[str, Any]:
        mention_users = [user for user in (mention_users or []) if user]
        mention_error = None
        open_ids_by_email: Dict[str, str] = {}
        member_open_ids: Set[str] = set()
        bot_not_in_chat = False

        try:
            open_ids_by_email = self._lookup_lark_open_ids_by_email(
                tenant_access_token,
                [user.email for user in mention_users if getattr(user, "email", None)],
            )
        except Exception as e:
            mention_error = f"lookup open_id failed: {e}"

        try:
            member_open_ids = self._list_lark_chat_member_open_ids(tenant_access_token, chat_id)
        except Exception as e:
            extra_error = f"lookup chat members failed: {e}"
            mention_error = f"{mention_error}; {extra_error}" if mention_error else extra_error
            if "code=232011" in str(e):
                bot_not_in_chat = True

        mention_tokens: List[str] = []
        card_mention_tokens: List[str] = []
        unresolved: List[str] = []
        plain_names: List[str] = []
        fallback_names: List[str] = []

        for user in mention_users:
            email = (user.email or "").strip().lower()
            display_name = user.full_name or user.username or email or "值班同学"
            fallback_names.append(display_name)
            open_id = open_ids_by_email.get(email)
            if open_id and open_id in member_open_ids:
                mention_tokens.append(f'<at user_id="{open_id}">{display_name}</at>')
                card_mention_tokens.append(f'<at id="{open_id}"></at>')
            elif email:
                unresolved.append(email)
                plain_names.append(display_name)
            else:
                plain_names.append(display_name)

        display_parts: List[str] = []
        if card_mention_tokens:
            display_parts.append(" ".join(card_mention_tokens))
        if plain_names:
            display_parts.append("、".join(plain_names))
        card_display = " / ".join(display_parts) if display_parts else None

        plain_display = "、".join(fallback_names) if fallback_names else None

        mention_line = None
        text_parts: List[str] = []
        if mention_tokens:
            text_parts.append(" ".join(mention_tokens))
        if plain_names:
            text_parts.append("、".join(plain_names))
        if text_parts:
            mention_line = "值班人: " + " / ".join(text_parts)
        elif plain_display:
            mention_line = "值班人: " + plain_display

        plain_mention_line = f"值班人: {plain_display}" if plain_display else None

        return {
            "mention_users": mention_users,
            "mention_error": mention_error,
            "bot_not_in_chat": bot_not_in_chat,
            "mention_tokens": mention_tokens,
            "card_mention_tokens": card_mention_tokens,
            "unresolved": unresolved,
            "plain_names": plain_names,
            "plain_display": plain_display,
            "card_display": card_display,
            "mention_line": mention_line,
            "plain_mention_line": plain_mention_line,
        }

    def send_lark_app_message(
        self,
        db: Session,
        chat_id: str,
        title: str,
        text: str,
        mention_users: Optional[List[models.User]] = None,
        link_url: Optional[str] = None,
        link_label: str = "查看详情",
    ) -> Dict[str, Optional[str]]:
        """通过统一 Lark 应用发送群消息，并尽量根据邮箱 @ 用户。"""
        if not chat_id:
            self._log_lark("skip", reason="missing_chat_id", title=title)
            return {
                "channel": "lark",
                "status": "skipped",
                "recipient": None,
                "error_message": "missing chat_id",
            }

        cfg = self._get_enabled_lark_app_config(db)
        if not cfg:
            self._log_lark("skip", chat_id=chat_id, reason="missing_enabled_config")
            return {
                "channel": "lark",
                "status": "skipped",
                "recipient": f"chat_id:{chat_id}",
                "error_message": "missing enabled lark app config",
            }

        try:
            tenant_access_token = self._get_lark_tenant_access_token(cfg.app_id, cfg.app_secret)
        except Exception as e:
            self._log_lark("error", chat_id=chat_id, stage="tenant_access_token", error=str(e))
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": f"tenant_access_token error: {e}",
            }

        mention_meta = self._resolve_lark_mentions(tenant_access_token, chat_id, mention_users)
        mention_users = mention_meta["mention_users"]
        mention_error = mention_meta["mention_error"]
        mention_tokens = mention_meta["mention_tokens"]
        card_mention_tokens = mention_meta["card_mention_tokens"]
        unresolved = mention_meta["unresolved"]
        plain_names = mention_meta["plain_names"]
        mention_line = mention_meta["mention_line"]
        plain_mention_line = mention_meta["plain_mention_line"]

        if mention_error and "lookup open_id failed" in mention_error:
            self._log_lark("warning", chat_id=chat_id, stage="lookup_open_id", error=mention_error)
        if mention_error and "lookup chat members failed" in mention_error:
            self._log_lark("warning", chat_id=chat_id, stage="lookup_chat_members", error=mention_error)

        if mention_meta["bot_not_in_chat"]:
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": "bot_not_in_chat: 请先把 Lark 应用机器人拉入该群后重试",
            }

        def build_text_payload(include_link: bool = False, with_mentions: bool = True) -> Dict[str, str]:
            lines = [title]
            selected_mention_line = mention_line if with_mentions else plain_mention_line
            if selected_mention_line:
                lines.append(selected_mention_line)
            if text:
                lines.append(text)
            if include_link and link_url:
                lines.append(f"{link_label}: {link_url}")
            if unresolved:
                lines.append("未匹配飞书账号: " + ", ".join(unresolved))
            return {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": "\n".join(lines)}, ensure_ascii=False),
            }

        def send_payload(payload: Dict[str, str]) -> Dict[str, Optional[str]]:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.LARK_API_BASE}/im/v1/messages?receive_id_type=chat_id",
                    json=payload,
                    headers=headers,
                )

            if resp.status_code // 100 != 2:
                error_code = None
                try:
                    error_code = (resp.json() or {}).get("code")
                except Exception:
                    error_code = None
                return {
                    "ok": False,
                    "error": self._extract_lark_error(resp),
                    "message_id": None,
                    "error_code": error_code,
                }

            data = resp.json() or {}
            if data.get("code") not in (None, 0):
                return {
                    "ok": False,
                    "error": f"code={data.get('code')}, msg={data.get('msg')}",
                    "message_id": None,
                    "error_code": data.get("code"),
                }

            return {
                "ok": True,
                "error": None,
                "message_id": (data.get("data") or {}).get("message_id"),
                "error_code": None,
            }

        if link_url:
            card_lines: List[str] = []
            if card_mention_tokens:
                card_lines.append("值班人: " + " ".join(card_mention_tokens))
            elif mention_users:
                card_lines.append("值班人: " + "、".join([user.full_name or user.email or f"用户#{user.id}" for user in mention_users]))
            if text:
                card_lines.extend([line for line in text.split("\n") if line.strip()])
            if unresolved:
                card_lines.append("未匹配飞书账号: " + ", ".join(unresolved))

            payload = {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps({
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "template": "red",
                        "title": {"tag": "plain_text", "content": title},
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": "\n".join(card_lines) or title,
                        },
                        {
                            "tag": "action",
                            "actions": [
                                {
                                    "tag": "button",
                                    "type": "primary",
                                    "text": {"tag": "plain_text", "content": link_label},
                                    "url": link_url,
                                }
                            ],
                        },
                    ],
                }, ensure_ascii=False),
            }
        else:
            payload = build_text_payload(include_link=False)
        headers = {"Authorization": f"Bearer {tenant_access_token}"}

        self._log_lark(
            "sending",
            chat_id=chat_id,
            title=title,
            mention_count=len(mention_users),
            mention_in_chat_count=len(mention_tokens),
            mention_plain_text_count=len(plain_names),
            unresolved_count=len(unresolved),
            link=bool(link_url),
        )

        try:
            result = send_payload(payload)
            if not result["ok"] and link_url:
                fallback = send_payload(build_text_payload(include_link=True))
                if (not fallback["ok"]) and fallback.get("error_code") == 230002 and mention_users:
                    fallback = send_payload(build_text_payload(include_link=True, with_mentions=False))
                if fallback["ok"]:
                    warnings = [f"interactive_failed: {result['error']}"]
                    if mention_error:
                        warnings.append(mention_error)
                    if fallback.get("error_code") == 230002:
                        warnings.append("mention_downgraded_to_plain_text")
                    self._log_lark(
                        "fallback_sent",
                        chat_id=chat_id,
                        original_error=result["error"],
                        mention_issue=mention_error,
                        message_id=fallback.get("message_id"),
                    )
                    return {
                        "channel": "lark",
                        "status": "sent",
                        "recipient": f"chat_id:{chat_id}",
                        "error_message": "; ".join(warnings),
                        "message_id": fallback.get("message_id"),
                    }
                return {
                    "channel": "lark",
                    "status": "failed",
                    "recipient": f"chat_id:{chat_id}",
                    "error_message": f"interactive_failed: {result['error']}; text_fallback_failed: {fallback['error']}",
                }

            if (not result["ok"]) and result.get("error_code") == 230002 and mention_users:
                retry_without_mentions = send_payload(build_text_payload(include_link=bool(link_url), with_mentions=False))
                if retry_without_mentions["ok"]:
                    self._log_lark(
                        "mention_downgraded",
                        chat_id=chat_id,
                        original_error=result["error"],
                        message_id=retry_without_mentions.get("message_id"),
                    )
                    return {
                        "channel": "lark",
                        "status": "sent",
                        "recipient": f"chat_id:{chat_id}",
                        "error_message": "mention_downgraded_to_plain_text",
                        "message_id": retry_without_mentions.get("message_id"),
                    }

            if not result["ok"]:
                self._log_lark("error", chat_id=chat_id, stage="send_payload", error=result["error"])
                return {
                    "channel": "lark",
                    "status": "failed",
                    "recipient": f"chat_id:{chat_id}",
                    "error_message": result["error"],
                }

            self._log_lark(
                "sent",
                chat_id=chat_id,
                message_id=result.get("message_id"),
                mention_issue=mention_error,
            )
            return {
                "channel": "lark",
                "status": "sent",
                "recipient": f"chat_id:{chat_id}",
                "error_message": mention_error,
                "message_id": result.get("message_id"),
            }
        except Exception as e:
            self._log_lark("error", chat_id=chat_id, stage="httpx", error=str(e))
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": str(e),
            }

    def send_phone_alert_huawei_stub(
        self,
        api_url: Optional[str],
        title: str,
        text: str,
        target_phones: Optional[list] = None,
    ) -> Dict[str, Optional[str]]:
        """手机告警占位：参考华为手机告警接口做适配层。

        MVP 阶段不强绑定具体接口，只落库/打印，方便后续替换为真实 Huawei API。
        """
        print(
            "[手机告警][HUAWEI_STUB]",
            json.dumps({"api_url": api_url, "title": title, "text": text, "targets": target_phones or []}, ensure_ascii=False),
        )
        return {
            "channel": "phone",
            "status": "simulated",
            "recipient": ",".join(target_phones or []) or "huawei_stub",
            "error_message": None,
        }

    def build_alert_message(self, incident: models.AlertIncident, event: models.AlertEvent, target_user: Optional[models.User]) -> Dict[str, str]:
        recipient_name = target_user.full_name if target_user else "值班同学"
        source_name = incident.source.name if incident.source else f"source#{incident.source_id}"
        subject = f"[告警通知][{incident.severity.upper()}] {incident.title}"
        body = dedent(f"""
            <h2>告警通知</h2>
            <p>您好，{recipient_name}：</p>
            <p>检测到新的告警事件，已归并为 Incident #{incident.id}。</p>
            <ul>
                <li><strong>告警源:</strong> {source_name}</li>
                <li><strong>标题:</strong> {incident.title}</li>
                <li><strong>级别:</strong> {incident.severity}</li>
                <li><strong>状态:</strong> {incident.status.value}</li>
                <li><strong>Fingerprint:</strong> {incident.fingerprint}</li>
                <li><strong>事件时间:</strong> {event.occurred_at.strftime('%Y-%m-%d %H:%M:%S')}</li>
            </ul>
            <p>{incident.summary or event.summary or '暂无摘要'}</p>
            <p>请尽快登录系统认领或关闭。</p>
        """).strip()
        return {"subject": subject, "body": body}
    
    def send_daily_reminder(self):
        """每天 9 点按排班发送当日值班信息到对应 Lark 群。"""
        db = SessionLocal()

        try:
            today = datetime.now().date()
            schedules = db.query(models.Schedule).filter(models.Schedule.is_active == True).all()

            for schedule in schedules:
                self.send_schedule_today_brief(db=db, schedule=schedule, target_date=today)
        finally:
            db.close()

    def send_schedule_today_brief(
        self,
        db: Session,
        schedule: models.Schedule,
        target_date: Optional[date] = None,
    ) -> Dict[str, Optional[str]]:
        schedule_service = ScheduleService(db)
        day = target_date or datetime.now().date()

        sources = db.query(models.AlertSource).filter(
            models.AlertSource.schedule_id == schedule.id,
            models.AlertSource.is_active == True,
        ).order_by(models.AlertSource.id.asc()).all()

        config = {}
        for source in sources:
            source_config = source.config or {}
            chat_id_value = (source_config.get("lark_chat_id") or "").strip()
            if source_config.get("lark_enabled") and chat_id_value:
                config = source_config
                break

        chat_id = (config.get("lark_chat_id") or "").strip()
        if not (config.get("lark_enabled") and chat_id):
            return {
                "status": "skipped",
                "error_message": "当前排班未配置可用的 Lark 群通知",
                "message_id": None,
            }

        assignments = schedule_service.get_today_assignments(schedule, target_date=day)
        full_day = assignments.get("full_day") or {}
        primary_user = full_day.get("primary")
        secondary_user = full_day.get("secondary")
        owner_user = schedule.owner

        mention_targets: List[models.User] = []
        for user in [owner_user, primary_user, secondary_user]:
            if user and all(existing.id != user.id for existing in mention_targets):
                mention_targets.append(user)

        mention_by_user_id: Dict[int, str] = {}
        try:
            cfg = self._get_enabled_lark_app_config(db)
            if cfg:
                token = self._get_lark_tenant_access_token(cfg.app_id, cfg.app_secret)
                open_ids_by_email = self._lookup_lark_open_ids_by_email(
                    token,
                    [user.email for user in mention_targets if getattr(user, "email", None)],
                )
                member_open_ids = self._list_lark_chat_member_open_ids(token, chat_id)

                for user in mention_targets:
                    display_name = user.full_name or user.username or user.email or f"用户#{user.id}"
                    email = (user.email or "").strip().lower()
                    open_id = open_ids_by_email.get(email)
                    if open_id and open_id in member_open_ids:
                        mention_by_user_id[user.id] = f'<at user_id="{open_id}">{display_name}</at>'
                    else:
                        mention_by_user_id[user.id] = f"@{display_name}"
        except Exception:
            # 解析 @ 失败时回退纯文本，避免阻塞日报发送
            mention_by_user_id = {}

        def mention_name(user: Optional[models.User]) -> str:
            if not user:
                return "@未设置"
            return mention_by_user_id.get(user.id, f"@{user.full_name or user.username or user.email or f'用户#{user.id}'}")

        duty_line = f"[主]{mention_name(primary_user)}"
        if secondary_user:
            duty_line += f"[备]{mention_name(secondary_user)}"

        text = "\n".join([
            f"[{schedule.name}]值班负责人{mention_name(owner_user)}",
            duty_line,
        ])

        result = self.send_lark_app_message(
            db=db,
            chat_id=chat_id,
            title="今天值班",
            text=text,
            mention_users=None,
        )
        return {
            "status": result.get("status"),
            "error_message": result.get("error_message"),
            "message_id": result.get("message_id"),
        }
    
    def send_handover_reminder(self, shift: models.Shift, db: Session):
        """发送交接班提醒"""
        # 获取下一个班次
        next_shift = db.query(models.Shift).filter(
            models.Shift.schedule_id == shift.schedule_id,
            models.Shift.start_time > shift.end_time
        ).order_by(models.Shift.start_time).first()
        
        if next_shift:
            current_user = db.query(models.User).filter(models.User.id == shift.user_id).first()
            next_user = db.query(models.User).filter(models.User.id == next_shift.user_id).first()
            
            if current_user and next_user:
                subject = "交接班提醒"
                body = f"""
                <h2>交接班提醒</h2>
                <p>{current_user.full_name}，您的班次即将结束。</p>
                <p>下一班值班人员：{next_user.full_name}</p>
                <p>请及时完成工作交接。</p>
                """
                self.send_email(current_user.email, subject, body)
    
    def notify_exchange_request(self, exchange_request: models.ExchangeRequest, db: Session):
        """通知换班申请"""
        responder = db.query(models.User).filter(models.User.id == exchange_request.responder_id).first()
        requester = db.query(models.User).filter(models.User.id == exchange_request.requester_id).first()
        
        if responder and requester:
            subject = "新的换班申请"
            body = f"""
            <h2>换班申请</h2>
            <p>{requester.full_name} 向您发起换班申请。</p>
            <p><strong>换班原因:</strong> {exchange_request.reason}</p>
            <p>请登录系统查看详情并处理。</p>
            """
            self.send_email(responder.email, subject, body)

    def send_nightingale_alert_ticket(
        self,
        db: Session,
        chat_id: str,
        alert_data: Dict[str, Any],
        incident_id: Optional[int] = None,
        link_url: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """
        发送 Nightingale 告警作为 Ticket 式 Lark 卡片
        
        从 n9e 事件中提取关键信息：
        - prom_ql: Prometheus 查询语句
        - severity: 告警级别
        - cluster: Prometheus 集群标识
        - rulename/cti: 规则名称
        - 时间相关参数: trigger_time, first_trigger_time 等
        
        Args:
            db: Database session
            chat_id: Lark 群组 ID
            alert_data: 来自 n9e 的 POST 数据
            incident_id: 系统内部 Incident ID（展示为 I{id}）
        """
        if not chat_id:
            self._log_lark("skip", reason="missing_chat_id")
            return {
                "channel": "lark",
                "status": "skipped",
                "recipient": None,
                "error_message": "missing chat_id",
            }

        cfg = self._get_enabled_lark_app_config(db)
        if not cfg:
            self._log_lark("skip", chat_id=chat_id, reason="missing_enabled_config")
            return {
                "channel": "lark",
                "status": "skipped",
                "recipient": f"chat_id:{chat_id}",
                "error_message": "missing enabled lark app config",
            }

        try:
            tenant_access_token = self._get_lark_tenant_access_token(cfg.app_id, cfg.app_secret)
        except Exception as e:
            self._log_lark("error", chat_id=chat_id, stage="tenant_access_token", error=str(e))
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": f"tenant_access_token error: {e}",
            }

        # 提取关键信息
        # ID 优先使用系统内部 incident_id（格式 I{id}，与截图一致），否则降级用 n9e 事件 ID
        if incident_id is not None:
            alert_id = f"I{incident_id}"
        else:
            alert_id = str(alert_data.get("id") or alert_data.get("alert_id") or alert_data.get("event_id") or "")
        rulename = str(alert_data.get("rule_name") or alert_data.get("ruleName") or "Unknown Rule").strip()
        cti = str(alert_data.get("cti") or alert_data.get("CTI") or "").strip()
        severity, severity_tag = self._normalize_n9e_severity(alert_data)
        severity_tag = str(alert_data.get("n9e_severity_tag") or "").strip() or severity_tag
        status_text = self._normalize_nightingale_status_text(alert_data)
        is_resolved = status_text == "resolved"
        
        # 获取集群信息
        cluster = "unknown"
        if isinstance(alert_data.get("cluster"), dict):
            cluster = alert_data.get("cluster", {}).get("name") or alert_data.get("cluster", {}).get("value") or "unknown"
        elif isinstance(alert_data.get("cluster"), str):
            cluster = alert_data.get("cluster")
        
        # 提取 Prometheus 查询信息
        prom_ql = ""
        if isinstance(alert_data.get("prom_ql"), list):
            prom_ql = alert_data.get("prom_ql", [None])[0] or ""
        else:
            prom_ql = str(alert_data.get("prom_ql") or alert_data.get("ql") or "").strip()
        
        # 提取时间信息
        trigger_time = None
        for key in ("trigger_time", "first_trigger_time", "timestamp", "ts"):
            value = alert_data.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                ts_value = float(value)
                if ts_value > 1_000_000_000_000:
                    ts_value = ts_value / 1000.0
                trigger_time = datetime.fromtimestamp(ts_value)
                break
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    continue
                try:
                    trigger_time = datetime.fromisoformat(text.replace("Z", "+00:00"))
                    break
                except ValueError:
                    continue
        
        if trigger_time is None:
            trigger_time = datetime.now()
        
        incident = None
        assigned_user = None
        if db is not None and incident_id is not None:
            incident = db.query(models.AlertIncident).filter(models.AlertIncident.id == incident_id).first()
            if incident:
                assigned_user = incident.assigned_user

        mention_meta = self._resolve_lark_mentions(
            tenant_access_token,
            chat_id,
            [assigned_user] if assigned_user else [],
        )
        mention_error = mention_meta["mention_error"]
        if mention_error and "lookup open_id failed" in mention_error:
            self._log_lark("warning", chat_id=chat_id, stage="ticket_lookup_open_id", error=mention_error)
        if mention_error and "lookup chat members failed" in mention_error:
            self._log_lark("warning", chat_id=chat_id, stage="ticket_lookup_chat_members", error=mention_error)
        if mention_meta["bot_not_in_chat"]:
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": "bot_not_in_chat: 请先把 Lark 应用机器人拉入该群后重试",
            }

        oncall_display = mention_meta["card_display"] or mention_meta["plain_display"] or "未匹配"

        # 获取目标信息
        target_ident = str(alert_data.get("target_ident") or alert_data.get("target") or "").strip()
        title = str(alert_data.get("title") or rulename or "Alert").strip()
        summary = str(alert_data.get("summary") or alert_data.get("annotations", {}).get("summary") or "").strip()
        
        # 确定卡片色彩
        color_map = {
            "critical": "red",
            "warning": "orange",
            "info": "blue",
            "debug": "grey",
        }
        header_template = "green" if is_resolved else color_map.get(severity, "red")

        # 构建 Lark 卡片内容
        if is_resolved:
            resolved_message = f"报障单#{alert_id}已解决，告警已恢复正常。" if alert_id else "报障单已解决，告警已恢复正常。"
            resolved_lines = [resolved_message]
            if assigned_user:
                resolved_lines.append(f"值班人：{oncall_display}")
            if rulename:
                resolved_lines.append(f"规则：{rulename}")
            resolved_lines.append(f"恢复时间：{trigger_time.strftime('%Y-%m-%d %H:%M:%S')}")

            title = "Ticket-报障单"
            card_elements = [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n".join(resolved_lines),
                    },
                }
            ]
        else:
            card_fields = []

            # ID 字段
            card_fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**ID:**\n{alert_id or '-'}",
                }
            })

            # 名称字段
            card_fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**名称:**\n{rulename or title}",
                }
            })

            # CTI 字段
            if cti:
                card_fields.append({
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**CTI:**\n{cti}",
                    }
                })

            # 级别字段
            card_fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**级别:**\n{severity.upper()}{f' ({severity_tag})' if severity_tag else ''}",
                }
            })

            # 集群字段
            card_fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**数据来源:**\n{cluster}",
                }
            })

            # 状态字段
            card_fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**状态:**\n{status_text}",
                }
            })

            # 值班人字段
            card_fields.append({
                "is_short": False,
                "text": {
                    "tag": "lark_md",
                    "content": f"**值班人:**\n{oncall_display}",
                }
            })

            # 时间字段
            card_fields.append({
                "is_short": False,
                "text": {
                    "tag": "lark_md",
                    "content": f"**触发时间:**\n{trigger_time.strftime('%Y-%m-%d %H:%M:%S')}",
                }
            })

            # 目标字段
            if target_ident:
                card_fields.append({
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**目标:**\n{target_ident}",
                    }
                })

            # Prom QL 字段
            if prom_ql:
                card_fields.append({
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**PromQL:**\n{prom_ql}",
                    }
                })

            # 摘要字段
            if summary:
                card_fields.append({
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**摘要:**\n{summary}",
                    }
                })

            card_elements = [
                {
                    "tag": "div",
                    "fields": card_fields,
                }
            ]

            title = "Ticket-报障单"

            if mention_meta["unresolved"]:
                card_elements.append({
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "未匹配飞书账号: " + ", ".join(mention_meta["unresolved"]),
                        }
                    ],
                })
        
        # 构建卡片 payload
        def build_ticket_payload(with_plain_oncall: bool = False) -> Dict[str, str]:
            ticket_elements = card_elements
            if with_plain_oncall and not is_resolved and assigned_user:
                plain_oncall = mention_meta["plain_display"] or oncall_display
                replaced_fields = []
                for field in card_fields:
                    content = (((field.get("text") or {}).get("content")) if isinstance(field, dict) else None)
                    if content == f"**值班人:**\n{oncall_display}":
                        replaced_fields.append({
                            "is_short": False,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**值班人:**\n{plain_oncall}",
                            }
                        })
                    else:
                        replaced_fields.append(field)
                ticket_elements = [{"tag": "div", "fields": replaced_fields}] + card_elements[1:]

            if link_url:
                ticket_elements = ticket_elements + [
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "type": "primary",
                                "text": {"tag": "plain_text", "content": "查看详情"},
                                "url": link_url,
                            }
                        ],
                    }
                ]

            return {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps({
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "template": header_template,
                        "title": {"tag": "plain_text", "content": title},
                    },
                    "elements": ticket_elements,
                }, ensure_ascii=False),
            }

        payload = build_ticket_payload()
        
        headers = {"Authorization": f"Bearer {tenant_access_token}"}
        
        self._log_lark(
            "sending_ticket",
            chat_id=chat_id,
            alert_id=alert_id,
            rulename=rulename,
            severity=severity,
        )
        
        def send_payload(message_payload: Dict[str, str]) -> Dict[str, Optional[str]]:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.LARK_API_BASE}/im/v1/messages?receive_id_type=chat_id",
                    json=message_payload,
                    headers=headers,
                )

            if resp.status_code // 100 != 2:
                error_msg = self._extract_lark_error(resp)
                return {
                    "ok": False,
                    "error_message": error_msg,
                    "message_id": None,
                    "error_code": None,
                }

            data = resp.json() or {}
            if data.get("code") not in (None, 0):
                error_msg = f"code={data.get('code')}, msg={data.get('msg')}"
                return {
                    "ok": False,
                    "error_message": error_msg,
                    "message_id": None,
                    "error_code": data.get("code"),
                }

            return {
                "ok": True,
                "error_message": None,
                "message_id": (data.get("data") or {}).get("message_id"),
                "error_code": None,
            }

        try:
            result = send_payload(payload)
            if (not result["ok"]) and result.get("error_code") == 230002 and assigned_user:
                result = send_payload(build_ticket_payload(with_plain_oncall=True))

            if not result["ok"]:
                self._log_lark("error", chat_id=chat_id, stage="send_ticket", error=result["error_message"])
                return {
                    "channel": "lark",
                    "status": "failed",
                    "recipient": f"chat_id:{chat_id}",
                    "error_message": result["error_message"],
                }

            message_id = result.get("message_id")
            self._log_lark("sent_ticket", chat_id=chat_id, message_id=message_id, mention_issue=mention_error)
            return {
                "channel": "lark",
                "status": "sent",
                "recipient": f"chat_id:{chat_id}",
                "error_message": mention_error,
                "message_id": message_id,
            }
        except Exception as e:
            self._log_lark("error", chat_id=chat_id, stage="httpx", error=str(e))
            return {
                "channel": "lark",
                "status": "failed",
                "recipient": f"chat_id:{chat_id}",
                "error_message": str(e),
            }

