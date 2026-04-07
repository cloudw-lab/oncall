import logging
from datetime import datetime
from datetime import timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..config import settings
from .notification_service import NotificationService
from .schedule_service import ScheduleService

logger = logging.getLogger("oncall.alert_service")


class AlertService:
    def __init__(self, db: Session):
        self.db = db
        self.schedule_service = ScheduleService(db)
        self.notification_service = NotificationService()

    def _get_schedule_or_404(self, schedule_id: int) -> models.Schedule:
        schedule = self.db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="排班表不存在")
        return schedule

    def _get_user_or_404(self, user_id: int) -> models.User:
        user = self.db.query(models.User).filter(
            models.User.id == user_id,
            models.User.is_active == True,
        ).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在或已禁用")
        return user

    def _get_incident_or_404(self, incident_id: int) -> models.AlertIncident:
        incident = self.db.query(models.AlertIncident).options(
            selectinload(models.AlertIncident.source),
            selectinload(models.AlertIncident.events),
            selectinload(models.AlertIncident.notifications).selectinload(models.AlertNotification.user),
            selectinload(models.AlertIncident.action_logs).selectinload(models.IncidentActionLog.actor_user),
            selectinload(models.AlertIncident.assigned_user),
            selectinload(models.AlertIncident.acknowledged_by),
            selectinload(models.AlertIncident.resolved_by),
        ).filter(models.AlertIncident.id == incident_id).first()
        if not incident:
            raise HTTPException(status_code=404, detail="Incident 不存在")
        return incident

    def _normalize_incident_status(self, status_value: Optional[str]):
        if not status_value:
            return None
        if status_value == "all":
            return None
        if isinstance(status_value, models.AlertIncidentStatus):
            return status_value
        try:
            return models.AlertIncidentStatus(status_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"不支持的 incident 状态: {status_value}") from exc

    def _normalize_event_status(self, status_value: Optional[str]):
        if not status_value:
            return models.AlertEventStatus.TRIGGERED
        if isinstance(status_value, models.AlertEventStatus):
            return status_value
        try:
            return models.AlertEventStatus(status_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"不支持的事件状态: {status_value}") from exc

    def _server_now(self) -> datetime:
        tz_name = settings.SERVER_TIMEZONE or "UTC"
        try:
            tz = ZoneInfo(tz_name)
            # Store as server-local naive datetime to keep SQLite and frontend parsing consistent.
            return datetime.now(tz).replace(tzinfo=None)
        except Exception:
            return datetime.now()

    def _build_current_oncall_summary(self, schedule_id: int, at_time: Optional[datetime] = None) -> Optional[Dict]:
        context = self.schedule_service.get_current_oncall_context(schedule_id, at_time=at_time)
        if not context:
            return None
        shift = context["shift"]
        return {
            "shift_kind": context["shift_kind"],
            "role": shift.role,
            "start_time": shift.start_time,
            "end_time": shift.end_time,
            "user": shift.user,
        }

    def _decorate_source(self, source: models.AlertSource) -> models.AlertSource:
        source.schedule_name = source.schedule.name if source.schedule else None
        source.current_oncall = self._build_current_oncall_summary(source.schedule_id)
        source.open_incident_count = self.db.query(models.AlertIncident).filter(
            models.AlertIncident.source_id == source.id,
            models.AlertIncident.status.in_([
                models.AlertIncidentStatus.OPEN,
                models.AlertIncidentStatus.ACKNOWLEDGED,
            ]),
        ).count()
        return source

    def _decorate_incident(self, incident: models.AlertIncident) -> models.AlertIncident:
        incident.source_name = incident.source.name if incident.source else None
        incident.schedule_name = incident.schedule.name if incident.schedule else None
        incident.event_count = len(incident.events or [])
        incident.notification_count = len(incident.notifications or [])
        incident.latest_event_status = incident.events[-1].event_status if incident.events else None
        return incident

    def _append_action_log(
        self,
        incident: models.AlertIncident,
        action: str,
        message: str,
        actor_user_id: Optional[int] = None,
        action_meta: Optional[Dict] = None,
    ) -> models.IncidentActionLog:
        log = models.IncidentActionLog(
            incident_id=incident.id,
            action=action,
            actor_user_id=actor_user_id,
            message=message,
            action_meta=action_meta or {},
            created_at=self._server_now(),
        )
        self.db.add(log)
        self.db.flush()
        return log

    def _build_incident_link(self, incident_id: int, schedule_id: Optional[int] = None) -> str:
        query = urlencode({
            key: value
            for key, value in {
                "feature": "alerts",
                "schedule_id": schedule_id,
                "incident_id": incident_id,
            }.items()
            if value is not None
        })
        path = f"/?{query}"
        if settings.INCIDENT_LINK_BASE_URL:
            return f"{settings.INCIDENT_LINK_BASE_URL.rstrip('/')}{path}"
        return path

    def list_sources(self, schedule_id: Optional[int] = None) -> List[models.AlertSource]:
        query = self.db.query(models.AlertSource).options(selectinload(models.AlertSource.schedule)).order_by(models.AlertSource.created_at.desc())
        if schedule_id:
            query = query.filter(models.AlertSource.schedule_id == schedule_id)
        rows = query.all()
        return [self._decorate_source(row) for row in rows]

    def upsert_source(self, payload: schemas.AlertSourceUpsert) -> models.AlertSource:
        schedule = self._get_schedule_or_404(payload.schedule_id)
        source = self.db.query(models.AlertSource).options(selectinload(models.AlertSource.schedule)).filter(
            models.AlertSource.source_key == payload.source_key
        ).first()

        if source:
            source.name = payload.name
            source.description = payload.description
            source.schedule_id = payload.schedule_id
            source.channel = payload.channel
            source.config = payload.config
            source.is_active = payload.is_active
        else:
            source = models.AlertSource(
                source_key=payload.source_key,
                name=payload.name,
                description=payload.description,
                schedule_id=payload.schedule_id,
                channel=payload.channel,
                config=payload.config,
                is_active=payload.is_active,
            )
            self.db.add(source)

        self.db.commit()
        self.db.refresh(source)
        source.schedule = schedule
        return self._decorate_source(source)

    def _resolve_source(self, payload: schemas.AlertEventIngest) -> models.AlertSource:
        resolved_schedule_id = payload.schedule_id
        if not resolved_schedule_id and payload.cti:
            resolved_schedule_id = self._resolve_schedule_id_by_cti(payload.cti)

        source = self.db.query(models.AlertSource).options(selectinload(models.AlertSource.schedule)).filter(
            models.AlertSource.source_key == payload.source_key
        ).first()

        if source:
            if resolved_schedule_id and source.schedule_id != resolved_schedule_id:
                source.schedule_id = resolved_schedule_id
            if payload.source_name:
                source.name = payload.source_name
            if not source.is_active:
                source.is_active = True
            self.db.flush()
            return source

        if not resolved_schedule_id:
            raise HTTPException(status_code=400, detail="首次接入事件时必须提供 schedule_id 或先创建 integration")

        self._get_schedule_or_404(resolved_schedule_id)
        source = models.AlertSource(
            source_key=payload.source_key,
            name=payload.source_name or payload.source_key,
            schedule_id=resolved_schedule_id,
            channel="email",
            config={},
            is_active=True,
        )
        self.db.add(source)
        self.db.flush()
        return source

    def _normalize_cti(self, cti: Optional[str]) -> Optional[str]:
        value = (cti or "").strip().lower()
        return value or None

    def _extract_cti_from_labels(self, labels: Any) -> Optional[str]:
        if isinstance(labels, dict):
            for key in ("cti", "CTI", "Cti"):
                if key in labels and labels.get(key) is not None:
                    return str(labels.get(key)).strip()
            return None

        if isinstance(labels, list):
            for item in labels:
                if isinstance(item, str) and "=" in item:
                    key, value = item.split("=", 1)
                    if key.strip().lower() == "cti":
                        return value.strip()
                elif isinstance(item, dict):
                    key = str(item.get("name") or item.get("key") or "").strip().lower()
                    if key == "cti":
                        value = item.get("value")
                        if value is not None:
                            return str(value).strip()
        return None

    def _extract_cti_from_nightingale_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        direct_candidates = [
            payload.get("cti"),
            payload.get("CTI"),
        ]
        for value in direct_candidates:
            if value is not None and str(value).strip():
                return str(value).strip()

        for key in (
            "tags",
            "labels",
            "commonLabels",
            "common_labels",
            "rule_labels",
            "rule_tags",
        ):
            extracted = self._extract_cti_from_labels(payload.get(key))
            if extracted:
                return extracted
        return None

    def _build_nightingale_title(self, payload: Dict[str, Any]) -> str:
        raw_title = str(
            payload.get("title")
            or payload.get("rule_name")
            or payload.get("ruleName")
            or payload.get("target_ident")
            or "Nightingale Alert"
        ).strip()
        if not raw_title:
            return "Nightingale Alert"

        if "{{$value}}" not in raw_title and "{{ $value }}" not in raw_title:
            return raw_title

        value_candidates = [
            payload.get("trigger_value"),
            payload.get("last_eval_value"),
            payload.get("value"),
            payload.get("eval_value"),
        ]
        value_text = None
        for candidate in value_candidates:
            if candidate is None:
                continue
            text = str(candidate).strip()
            if text:
                value_text = text
                break

        if not value_text:
            return raw_title.replace("{{$value}}", "").replace("{{ $value }}", "").strip() or raw_title
        return raw_title.replace("{{$value}}", value_text).replace("{{ $value }}", value_text).strip()

    def _normalize_n9e_severity(self, payload: Dict[str, Any]) -> tuple[str, Optional[str]]:
        raw = payload.get("severity")
        if raw is None:
            raw = payload.get("level")
        if raw is None:
            raw = payload.get("priority")
        text = str(raw or "").strip().lower()

        # Nightingale numeric level mapping: 1=critical, 2=warning.
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

    def _resolve_schedule_id_by_cti(self, cti: Optional[str]) -> Optional[int]:
        normalized = self._normalize_cti(cti)
        if not normalized:
            return None

        sources = self.db.query(models.AlertSource).filter(
            models.AlertSource.is_active == True,
        ).order_by(models.AlertSource.id.asc()).all()

        matched_schedule_ids: List[int] = []
        for source in sources:
            config = source.config or {}
            configured_cti_values = config.get("cti_values", [])
            if not isinstance(configured_cti_values, list):
                continue
            normalized_values = {
                self._normalize_cti(item)
                for item in configured_cti_values
                if isinstance(item, str) and self._normalize_cti(item)
            }
            if normalized in normalized_values:
                matched_schedule_ids.append(source.schedule_id)

        uniq_schedule_ids = sorted(set(matched_schedule_ids))
        if not uniq_schedule_ids:
            return None
        if len(uniq_schedule_ids) > 1:
            raise HTTPException(
                status_code=409,
                detail=f"cti={cti} 命中了多个排班表，请确保 cti_values 配置唯一",
            )
        return uniq_schedule_ids[0]

    def _build_nightingale_ingest_payload(self, payload: Dict[str, Any]) -> schemas.AlertEventIngest:
        cti = self._extract_cti_from_nightingale_payload(payload)
        schedule_id = self._resolve_schedule_id_by_cti(cti)
        if schedule_id is None:
            raise HTTPException(status_code=400, detail=f"未找到 cti={cti or 'unknown'} 对应的排班表配置")

        source_key = f"schedule-{schedule_id}-default"
        source_name = str(payload.get("source_name") or payload.get("rule_name") or payload.get("ruleName") or "Nightingale").strip()

        # 判断是否为恢复事件，兼容 n9e 各种字段格式：
        # 1. is_recovered=True  (n9e 主要标识字段)
        # 2. status 字符串：resolved/recover/recovered/ok
        # 3. alert_status 整型：n9e v6+ 用 2 表示 recovered
        # 4. event_status 字符串：resolved/recovered
        is_recovered_flag = payload.get("is_recovered")
        if is_recovered_flag is True or str(is_recovered_flag).lower() == "true":
            event_status = models.AlertEventStatus.RESOLVED
        else:
            # 字符串 status 字段检查
            status_raw = payload.get("status")
            event_status_raw = payload.get("event_status")
            alert_status_raw = payload.get("alert_status")

            # n9e 用整型 alert_status: 0=firing, 2=recovered
            if isinstance(alert_status_raw, int) and alert_status_raw == 2:
                event_status = models.AlertEventStatus.RESOLVED
            else:
                resolved_markers = {"resolved", "recover", "recovered", "ok", "2"}
                status_text = str(status_raw or event_status_raw or "triggered").strip().lower()
                event_status = models.AlertEventStatus.RESOLVED if status_text in resolved_markers else models.AlertEventStatus.TRIGGERED

        severity, severity_tag = self._normalize_n9e_severity(payload)
        title = self._build_nightingale_title(payload)

        summary = payload.get("summary")
        annotations = payload.get("annotations")
        if summary is None and isinstance(annotations, dict):
            summary = annotations.get("summary")
        if summary is not None:
            summary = str(summary).strip()

        occurred_at = None
        # Recovery events: just use current server time (N9E recovery payloads
        # often carry trigger_time=original or recover_time=0, both misleading).
        if event_status == models.AlertEventStatus.RESOLVED:
            occurred_at = datetime.now(ZoneInfo(settings.SERVER_TIMEZONE or "UTC")).replace(tzinfo=None)
        else:
            for key in ("trigger_time", "first_trigger_time", "timestamp", "ts"):
                value = payload.get(key)
                if value is None:
                    continue
                if isinstance(value, (int, float)):
                    ts_value = float(value)
                    if ts_value > 1_000_000_000_000:
                        ts_value = ts_value / 1000.0
                    occurred_at = datetime.fromtimestamp(ts_value)
                    break
                if isinstance(value, str):
                    text = value.strip()
                    if not text:
                        continue
                    try:
                        occurred_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
                        break
                    except ValueError:
                        continue

        # n9e 场景下要求提供 hash；同 hash 视为同一告警（含恢复事件）
        fingerprint = str(payload.get("hash") or payload.get("fingerprint") or "").strip()
        if not fingerprint:
            raise HTTPException(status_code=400, detail="n9e payload 缺少必填字段: hash")

        external_event_id = payload.get("event_id") or payload.get("id") or payload.get("alarm_id")
        if external_event_id is not None:
            external_event_id = str(external_event_id)
            # n9e recovery 与 firing 共用同一 external_event_id；
            # 加 _r 后缀让 DB UNIQUE 约束不冲突，并区分恢复事件
            if event_status == models.AlertEventStatus.RESOLVED:
                external_event_id = f"{external_event_id}_r"

        event_payload = dict(payload)
        event_payload["nightingale_origin"] = True
        if cti:
            event_payload["cti"] = cti
        if fingerprint:
            event_payload["hash"] = fingerprint
            event_payload["fingerprint"] = fingerprint
        if severity_tag:
            event_payload["n9e_severity_tag"] = severity_tag

        return schemas.AlertEventIngest(
            source_key=source_key,
            schedule_id=schedule_id,
            source_name=source_name,
            cti=cti,
            fingerprint=fingerprint,
            title=title,
            summary=summary,
            severity=severity,
            status=event_status,
            external_event_id=external_event_id,
            occurred_at=occurred_at,
            payload=event_payload,
        )

    def ingest_nightingale_event(self, payload: Dict[str, Any]) -> Dict:
        ingest_payload = self._build_nightingale_ingest_payload(payload)
        return self.ingest_event(ingest_payload)

    def _create_notification(self, incident: models.AlertIncident, event: models.AlertEvent) -> models.AlertNotification:
        target_user = incident.assigned_user
        message = self.notification_service.build_alert_message(incident, event, target_user)

        # Schedule-level integration config (stored on default source config)
        integration_source_key = f"schedule-{incident.schedule_id}-default"
        integration_source = self.db.query(models.AlertSource).filter(models.AlertSource.source_key == integration_source_key).first()
        integration_cfg = (integration_source.config or {}) if integration_source else {}

        lark_enabled = bool(integration_cfg.get("lark_enabled", False))
        lark_chat_id = integration_cfg.get("lark_chat_id")
        incident_link = self._build_incident_link(incident.id, incident.schedule_id)

        if lark_enabled and lark_chat_id:
            delivery = self.notification_service.send_lark_app_message(
                db=self.db,
                chat_id=lark_chat_id,
                title=message["subject"],
                text=incident.summary or event.summary or '',
                mention_users=[target_user] if target_user else None,
                link_url=incident_link,
            )
        elif target_user and target_user.email:
            delivery = self.notification_service.send_email(target_user.email, message["subject"], message["body"])
        else:
            delivery = {
                "channel": "console",
                "status": "skipped",
                "recipient": None,
                "error_message": "当前没有可通知的值班人",
            }

        row = models.AlertNotification(
            incident_id=incident.id,
            event_id=event.id,
            user_id=target_user.id if target_user else None,
            channel=delivery.get("channel") or "email",
            status=delivery.get("status") or "pending",
            recipient=delivery.get("recipient"),
            subject=message["subject"],
            body=message["body"],
            error_message=delivery.get("error_message"),
            created_at=self._server_now(),
            sent_at=self._server_now() if delivery.get("status") in {"sent", "simulated"} else None,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _already_escalated_to_phone(self, incident_id: int) -> bool:
        row = self.db.query(models.AlertNotification.id).filter(
            models.AlertNotification.incident_id == incident_id,
            models.AlertNotification.channel == "phone",
        ).first()
        return row is not None

    def _already_notified_all_oncall(self, incident_id: int) -> bool:
        row = self.db.query(models.AlertNotification.id).filter(
            models.AlertNotification.incident_id == incident_id,
            models.AlertNotification.channel == "lark",
            models.AlertNotification.recipient == "oncall_all",
        ).first()
        return row is not None

    def _get_integration_config(self, schedule_id: int) -> Dict:
        integration_source_key = f"schedule-{schedule_id}-default"
        integration_source = self.db.query(models.AlertSource).filter(models.AlertSource.source_key == integration_source_key).first()
        return (integration_source.config or {}) if integration_source else {}

    def _is_important_severity(self, severity_value: Optional[str]) -> bool:
        text = str(severity_value or "").strip().lower()
        return text in {"critical", "1", "p1", "sev1", "s1"}

    def _is_important_incident(self, incident: models.AlertIncident) -> bool:
        # MVP: severity=critical/1 OR latest event payload important=true
        if self._is_important_severity(incident.severity):
            return True
        if incident.events:
            payload = incident.events[-1].payload or {}
            if isinstance(payload, dict) and payload.get("important") is True:
                return True
        return False

    def notify_all_oncall_today_via_lark(self, incident_id: int, reason: str) -> Optional[models.AlertNotification]:
        incident = self._get_incident_or_404(incident_id)
        if incident.status == models.AlertIncidentStatus.RESOLVED:
            return None

        cfg = self._get_integration_config(incident.schedule_id)
        if not bool(cfg.get("lark_enabled", False)):
            return None
        chat_id = cfg.get("lark_chat_id")
        if not chat_id:
            return None
        if not bool(cfg.get("notify_all_oncall_on_ack_timeout", True)):
            return None
        if self._already_notified_all_oncall(incident_id):
            return None

        schedule = self._get_schedule_or_404(incident.schedule_id)
        day = incident.latest_event_at.date()
        assignments = self.schedule_service.get_today_assignments(schedule, target_date=day)
        users = []
        full_day = assignments.get("full_day", {}) if isinstance(assignments, dict) else {}
        for role_key in ("primary", "secondary"):
            user = full_day.get(role_key)
            if user:
                users.append(user)
        uniq = list({u.id: u for u in users}.values())
        names = ", ".join([u.full_name for u in uniq]) or "(无人)"

        title = f"[未认领升级][{incident.severity.upper()}] {incident.title}"
        incident_link = self._build_incident_link(incident.id, incident.schedule_id)
        text = (
            f"当前值班: {incident.assigned_user.full_name if incident.assigned_user else '未匹配'}\n"
            f"今日值班全员: {names}\n"
            f"fingerprint={incident.fingerprint}\n"
            f"reason={reason}\n"
            f"summary={incident.summary or ''}"
        )
        delivery = self.notification_service.send_lark_app_message(
            db=self.db,
            chat_id=chat_id,
            title=title,
            text=text,
            mention_users=uniq,
            link_url=incident_link,
        )

        latest_event = incident.events[-1] if incident.events else None
        event_id = latest_event.id if latest_event else None
        if event_id is None:
            return None

        row = models.AlertNotification(
            incident_id=incident.id,
            event_id=event_id,
            user_id=None,
            channel="lark",
            status=delivery.get("status") or "pending",
            recipient="oncall_all",
            subject=title,
            body=text,
            error_message=delivery.get("error_message"),
            created_at=self._server_now(),
            sent_at=self._server_now() if delivery.get("status") in {"sent", "simulated"} else None,
        )
        self.db.add(row)
        self._append_action_log(
            incident,
            action="escalated_lark_all",
            message="未 ACK 超时，已通知当天值班全员",
            action_meta={"reason": reason, "names": names},
        )
        self.db.commit()
        return row

    def escalate_incident_to_phone(self, incident_id: int, reason: str = "auto") -> Optional[models.AlertNotification]:
        incident = self._get_incident_or_404(incident_id)
        if incident.status == models.AlertIncidentStatus.RESOLVED:
            return None
        if self._already_escalated_to_phone(incident_id):
            return None

        cfg = self._get_integration_config(incident.schedule_id)

        # For important alerts, we allow direct phone even if escalation_enabled is off.
        if not reason.startswith("important") and not bool(cfg.get("escalation_enabled", True)):
            return None

        title = f"[手机告警升级] {incident.title}"
        text = f"incident_id={incident.id}\nseverity={incident.severity}\nstatus={incident.status.value}\nfingerprint={incident.fingerprint}\nsummary={incident.summary or ''}"
        target_phones = []
        if incident.assigned_user and incident.assigned_user.phone_plain:
            target_phones.append(incident.assigned_user.phone_plain)
        target_phones.extend(cfg.get("huawei_target_phones", []) or [])
        target_phones = list(dict.fromkeys([phone for phone in target_phones if phone]))
        delivery = self.notification_service.send_phone_alert_huawei_stub(
            api_url=cfg.get("huawei_phone_api_url"),
            title=title,
            text=text,
            target_phones=target_phones,
        )

        # Create a pseudo event link: use latest event
        latest_event = incident.events[-1] if incident.events else None
        event_id = latest_event.id if latest_event else None
        if event_id is None:
            # fallback: create an empty event record
            latest_event = models.AlertEvent(
                source_id=incident.source_id,
                incident_id=incident.id,
                schedule_id=incident.schedule_id,
                external_event_id=None,
                fingerprint=incident.fingerprint,
                event_status=models.AlertEventStatus.TRIGGERED,
                severity=incident.severity,
                title=incident.title,
                summary=incident.summary,
                payload={},
                occurred_at=self._server_now(),
            )
            self.db.add(latest_event)
            self.db.flush()
            event_id = latest_event.id

        row = models.AlertNotification(
            incident_id=incident.id,
            event_id=event_id,
            user_id=incident.assigned_user_id,
            channel=delivery.get("channel") or "phone",
            status=delivery.get("status") or "pending",
            recipient=delivery.get("recipient"),
            subject=title,
            body=text,
            error_message=delivery.get("error_message"),
            created_at=self._server_now(),
            sent_at=self._server_now() if delivery.get("status") in {"sent", "simulated"} else None,
        )
        self.db.add(row)
        self._append_action_log(
            incident,
            action="escalated_phone",
            message=f"Incident 已升级到手机告警 ({reason})",
            action_meta={"reason": reason},
        )
        self.db.commit()
        return row

    def scan_and_escalate(self) -> int:
        """扫描未处理 incident：

        - important 直接电话
        - 未 ACK 超时后 Lark 通知当天值班全员
        - 未关闭超时后手机告警（保留）
        """
        now = self._server_now()
        candidates = self.db.query(models.AlertIncident).options(
            selectinload(models.AlertIncident.events),
            selectinload(models.AlertIncident.assigned_user),
        ).filter(
            models.AlertIncident.status.in_([
                models.AlertIncidentStatus.OPEN,
                models.AlertIncidentStatus.ACKNOWLEDGED,
            ])
        ).all()

        escalated = 0
        for incident in candidates:
            cfg = self._get_integration_config(incident.schedule_id)

            # Important direct phone
            if bool(cfg.get("important_direct_phone", True)) and self._is_important_incident(incident):
                if not self._already_escalated_to_phone(incident.id):
                    row = self.escalate_incident_to_phone(incident.id, reason="important")
                    if row:
                        escalated += 1

            # Unacked escalation to all oncall today
            if bool(cfg.get("ack_escalation_enabled", True)):
                ack_after = int(cfg.get("ack_escalation_after_minutes", 15))
                ack_deadline = incident.first_event_at + timedelta(minutes=ack_after)
                if now >= ack_deadline and not incident.acknowledged_at and incident.status == models.AlertIncidentStatus.OPEN:
                    row = self.notify_all_oncall_today_via_lark(incident.id, reason=f"unacked_{ack_after}m")
                    if row:
                        escalated += 1

            # Resolve escalation to phone
            if bool(cfg.get("escalation_enabled", True)):
                after_minutes = int(cfg.get("escalation_after_minutes", 60))
                deadline = incident.first_event_at + timedelta(minutes=after_minutes)
                if now >= deadline and incident.status != models.AlertIncidentStatus.RESOLVED:
                    if not self._already_escalated_to_phone(incident.id):
                        row = self.escalate_incident_to_phone(incident.id, reason=f"timeout_{after_minutes}m")
                        if row:
                            escalated += 1
        return escalated

    def ingest_event(self, payload: schemas.AlertEventIngest) -> Dict:
        event_status = self._normalize_event_status(payload.status)
        source = self._resolve_source(payload)
        schedule = self._get_schedule_or_404(payload.schedule_id or source.schedule_id)
        occurred_at = payload.occurred_at or self._server_now()
        event_payload = dict(payload.payload or {})
        if payload.cti and not event_payload.get("cti"):
            event_payload["cti"] = payload.cti
        if payload.fingerprint and not event_payload.get("hash"):
            event_payload["hash"] = payload.fingerprint

        # 恢复事件简化 payload：只保留必要字段
        if event_status == models.AlertEventStatus.RESOLVED:
            event_payload = {
                "rule_name": event_payload.get("rule_name", payload.title),
                "is_recovered": True,
                "hash": payload.fingerprint,
                "nightingale_origin": bool((payload.payload or {}).get("nightingale_origin")),
            }
            event_status = models.AlertEventStatus.RECOVERED

        if payload.external_event_id:
            existing_event = self.db.query(models.AlertEvent).filter(
                models.AlertEvent.source_id == source.id,
                models.AlertEvent.external_event_id == payload.external_event_id,
            ).first()
            if existing_event:
                # 恢复事件允许带相同 external_event_id（n9e recovery 与 firing 共用同一 ID）
                # 只有 triggered 事件才视为重复并拒绝
                if event_status == models.AlertEventStatus.TRIGGERED:
                    raise HTTPException(status_code=409, detail="external_event_id 已存在")

        incident = self.db.query(models.AlertIncident).options(
            selectinload(models.AlertIncident.source),
            selectinload(models.AlertIncident.schedule),
            selectinload(models.AlertIncident.assigned_user),
            selectinload(models.AlertIncident.events),
            selectinload(models.AlertIncident.notifications),
        ).filter(
            models.AlertIncident.source_id == source.id,
            models.AlertIncident.fingerprint == payload.fingerprint,
            models.AlertIncident.status.in_([
                models.AlertIncidentStatus.OPEN,
                models.AlertIncidentStatus.ACKNOWLEDGED,
            ]),
        ).order_by(models.AlertIncident.latest_event_at.desc()).first()

        deduped = incident is not None and event_status == models.AlertEventStatus.TRIGGERED
        assignment = self.schedule_service.get_current_oncall_context(schedule.id, at_time=occurred_at)

        if incident is None:
            incident = models.AlertIncident(
                source_id=source.id,
                schedule_id=schedule.id,
                fingerprint=payload.fingerprint,
                status=models.AlertIncidentStatus.RESOLVED if event_status in (models.AlertEventStatus.RESOLVED, models.AlertEventStatus.RECOVERED) else models.AlertIncidentStatus.OPEN,
                severity=payload.severity,
                title=payload.title,
                summary=payload.summary,
                assigned_user_id=assignment["shift"].user_id if assignment else None,
                assigned_role=assignment["shift"].role if assignment else None,
                assigned_shift_kind=assignment["shift_kind"] if assignment else None,
                first_event_at=occurred_at,
                latest_event_at=occurred_at,
                resolved_at=occurred_at if event_status in (models.AlertEventStatus.RESOLVED, models.AlertEventStatus.RECOVERED) else None,
            )
            self.db.add(incident)
            self.db.flush()
            self._append_action_log(
                incident,
                action="created",
                message="外部事件创建了新的 Incident",
                action_meta={
                    "source_key": source.source_key,
                    "event_status": event_status.value,
                },
            )
        else:
            incident.latest_event_at = occurred_at
            incident.severity = payload.severity or incident.severity
            incident.title = payload.title or incident.title
            if payload.summary is not None:
                incident.summary = payload.summary

        event = models.AlertEvent(
            source_id=source.id,
            incident_id=incident.id,
            schedule_id=schedule.id,
            external_event_id=payload.external_event_id,
            fingerprint=payload.fingerprint,
            event_status=event_status,
            severity=payload.severity,
            title=payload.title,
            summary=payload.summary,
            payload=event_payload,
            occurred_at=occurred_at,
        )
        self.db.add(event)
        self.db.flush()

        notifications: List[models.AlertNotification] = []
        if event_status in (models.AlertEventStatus.RESOLVED, models.AlertEventStatus.RECOVERED):
            incident.status = models.AlertIncidentStatus.RESOLVED
            incident.resolved_at = occurred_at
            self._append_action_log(
                incident,
                action="auto_resolved",
                message="收到恢复事件，Incident 已自动关闭",
                action_meta={"event_id": event.id},
            )
            # Send Lark recovery notification (same as manual resolve)
            self.db.flush()
            try:
                lark_result = self._send_lark_recovery_ticket_for_incident(incident)
                self._append_action_log(
                    incident,
                    action="auto_resolved_ticket_notified",
                    message="收到恢复事件后已发送 Lark 恢复卡片",
                    action_meta={
                        "lark_status": lark_result.get("status"),
                        "message_id": lark_result.get("message_id"),
                        "error_message": lark_result.get("error_message"),
                    },
                )
            except Exception as exc:
                logger.warning("auto_resolved lark notification failed: %s", exc)
        elif deduped:
            self._append_action_log(
                incident,
                action="deduplicated",
                message="重复事件已归并到现有 Incident",
                action_meta={"event_id": event.id},
            )
        else:
            # Important alerts: direct phone escalation immediately (if enabled)
            cfg = self._get_integration_config(incident.schedule_id)
            is_nightingale = bool(event_payload.get("nightingale_origin"))
            use_ticket_only = is_nightingale and bool(cfg.get("lark_ticket_enabled", True))

            if not use_ticket_only:
                notifications.append(self._create_notification(incident, event))
                self._append_action_log(
                    incident,
                    action="notified",
                    message="已按当前值班匹配结果生成通知",
                    action_meta={
                        "event_id": event.id,
                        "assigned_user_id": incident.assigned_user_id,
                        "assigned_shift_kind": incident.assigned_shift_kind,
                    },
                )
            else:
                chat_id = cfg.get("lark_chat_id")
                if chat_id and not deduped:
                    ticket_payload = dict(event_payload)
                    ticket_payload.setdefault("rule_name", payload.title)
                    ticket_payload.setdefault("title", payload.title)
                    ticket_payload.setdefault("severity", payload.severity)
                    ticket_payload.setdefault("status", event_status.value)
                    ticket_payload.setdefault("trigger_time", occurred_at.isoformat())
                    self.notification_service.send_nightingale_alert_ticket(
                        db=self.db,
                        chat_id=chat_id,
                        alert_data=ticket_payload,
                        incident_id=incident.id,
                        link_url=self._build_incident_link(incident.id, incident.schedule_id),
                    )
                self._append_action_log(
                    incident,
                    action="ticket_notified",
                    message="Nightingale 事件使用 Ticket 通知，已跳过通用告警模板",
                    action_meta={"event_id": event.id},
                )

            if bool(cfg.get("important_direct_phone", True)):
                # Evaluate importance based on incident/event
                if self._is_important_severity(payload.severity) or event_payload.get("important") is True:
                    self.escalate_incident_to_phone(incident.id, reason="important_immediate")

        self.db.commit()
        incident = self._get_incident_or_404(incident.id)
        incident.current_oncall = self._build_current_oncall_summary(incident.schedule_id)
        incident.schedule_coverage = {
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "date": incident.latest_event_at.date(),
            "assignments": self.schedule_service.get_today_assignments(schedule, target_date=incident.latest_event_at.date()),
        }
        if incident.source:
            self._decorate_source(incident.source)
        self._decorate_incident(incident)
        return {
            "deduped": deduped,
            "incident": incident,
            "event": event,
            "notifications": incident.notifications[-len(notifications):] if notifications else [],
        }

    def list_incidents(
        self,
        schedule_id: Optional[int] = None,
        status_value: Optional[str] = None,
        user_id: Optional[int] = None,
        related_only: bool = False,
        keyword: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[models.AlertIncident]:
        query = self.db.query(models.AlertIncident).options(
            selectinload(models.AlertIncident.source),
            selectinload(models.AlertIncident.schedule),
            selectinload(models.AlertIncident.assigned_user),
            selectinload(models.AlertIncident.acknowledged_by),
            selectinload(models.AlertIncident.resolved_by),
            selectinload(models.AlertIncident.events),
            selectinload(models.AlertIncident.notifications).selectinload(models.AlertNotification.user),
        ).order_by(models.AlertIncident.id.desc())

        if schedule_id:
            query = query.filter(models.AlertIncident.schedule_id == schedule_id)
        normalized_status = self._normalize_incident_status(status_value)
        if normalized_status:
            query = query.filter(models.AlertIncident.status == normalized_status)

        if related_only and user_id:
            query = query.filter(
                or_(
                    models.AlertIncident.assigned_user_id == user_id,
                    models.AlertIncident.acknowledged_by_user_id == user_id,
                    models.AlertIncident.resolved_by_user_id == user_id,
                    models.AlertIncident.notifications.any(models.AlertNotification.user_id == user_id),
                )
            )

        keyword = (keyword or "").strip()
        if keyword:
            like_pattern = f"%{keyword}%"
            filters = [
                models.AlertIncident.title.ilike(like_pattern),
                models.AlertIncident.fingerprint.ilike(like_pattern),
                models.AlertIncident.summary.ilike(like_pattern),
                models.AlertIncident.source.has(models.AlertSource.name.ilike(like_pattern)),
                cast(models.AlertIncident.id, String).ilike(like_pattern),
            ]
            if keyword.isdigit():
                filters.append(models.AlertIncident.id == int(keyword))
            query = query.filter(or_(*filters))

        rows = query.offset(skip).limit(limit).all()
        return [self._decorate_incident(row) for row in rows]

    def get_incident_detail(self, incident_id: int) -> models.AlertIncident:
        incident = self._get_incident_or_404(incident_id)
        schedule = self._get_schedule_or_404(incident.schedule_id)
        if incident.source:
            self._decorate_source(incident.source)
        incident.current_oncall = self._build_current_oncall_summary(incident.schedule_id)
        incident.schedule_coverage = {
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "date": incident.latest_event_at.date(),
            "assignments": self.schedule_service.get_today_assignments(schedule, target_date=incident.latest_event_at.date()),
        }
        return self._decorate_incident(incident)

    def acknowledge_incident(self, incident_id: int, payload: schemas.IncidentActionRequest) -> models.AlertIncident:
        incident = self._get_incident_or_404(incident_id)
        if incident.status == models.AlertIncidentStatus.RESOLVED:
            raise HTTPException(status_code=400, detail="已关闭的 Incident 不能再认领")

        actor = self._get_user_or_404(payload.user_id) if payload.user_id else None
        incident.status = models.AlertIncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = self._server_now()
        incident.acknowledged_by_user_id = actor.id if actor else None
        self._append_action_log(
            incident,
            action="acknowledged",
            message=payload.note or "Incident 已被认领",
            actor_user_id=actor.id if actor else None,
            action_meta={"acknowledged_at": incident.acknowledged_at.isoformat()},
        )
        self.db.commit()
        return self.get_incident_detail(incident_id)

    def _build_ticket_alert_data_from_incident(
        self,
        incident: models.AlertIncident,
        *,
        force_recovered: bool = False,
    ) -> Dict[str, Any]:
        latest_event = incident.events[-1] if incident.events else None
        alert_data = dict((latest_event.payload or {}) if latest_event else {})

        alert_data.setdefault("rule_name", incident.title)
        alert_data.setdefault("title", incident.title)
        alert_data.setdefault("severity", incident.severity)
        alert_data.setdefault("summary", incident.summary)
        if latest_event:
            alert_data.setdefault("trigger_time", latest_event.occurred_at.isoformat())

        if force_recovered or incident.status == models.AlertIncidentStatus.RESOLVED:
            alert_data["is_recovered"] = True
            if incident.resolved_at:
                alert_data["trigger_time"] = incident.resolved_at.isoformat()

        return alert_data

    def _send_lark_recovery_ticket_for_incident(self, incident: models.AlertIncident) -> Dict[str, Optional[str]]:
        cfg = self._get_integration_config(incident.schedule_id)
        lark_chat_id = cfg.get("lark_chat_id")
        if not cfg.get("lark_enabled") or not lark_chat_id:
            return {
                "status": "skipped",
                "message_id": None,
                "error_message": "lark_disabled_or_missing_chat_id",
            }

        alert_data = self._build_ticket_alert_data_from_incident(incident, force_recovered=True)
        return self.notification_service.send_nightingale_alert_ticket(
            db=self.db,
            chat_id=lark_chat_id,
            alert_data=alert_data,
            incident_id=incident.id,
            link_url=self._build_incident_link(incident.id, incident.schedule_id),
        )

    def resend_lark_ticket(self, incident_id: int) -> Dict:
        """手动重新发送 Lark Ticket 告警卡片（使用最近一次事件的 payload）"""
        incident = self._get_incident_or_404(incident_id)
        alert_data = self._build_ticket_alert_data_from_incident(incident)

        cfg = self._get_integration_config(incident.schedule_id)
        lark_chat_id = cfg.get("lark_chat_id")
        if not cfg.get("lark_enabled") or not lark_chat_id:
            raise HTTPException(status_code=400, detail="当前排班未配置 Lark 通知，无法发送")

        result = self.notification_service.send_nightingale_alert_ticket(
            db=self.db,
            chat_id=lark_chat_id,
            alert_data=alert_data,
            incident_id=incident.id,
            link_url=self._build_incident_link(incident.id, incident.schedule_id),
        )
        return {
            "incident_id": incident_id,
            "lark_status": result.get("status"),
            "message_id": result.get("message_id"),
            "error_message": result.get("error_message"),
        }

    def resolve_incident(self, incident_id: int, payload: schemas.IncidentActionRequest) -> models.AlertIncident:
        incident = self._get_incident_or_404(incident_id)
        actor = self._get_user_or_404(payload.user_id) if payload.user_id else None

        if incident.status != models.AlertIncidentStatus.RESOLVED:
            incident.status = models.AlertIncidentStatus.RESOLVED
            incident.resolved_at = self._server_now()
            incident.resolved_by_user_id = actor.id if actor else None
            self._append_action_log(
                incident,
                action="resolved",
                message=payload.note or "Incident 已关闭",
                actor_user_id=actor.id if actor else None,
                action_meta={"resolved_at": incident.resolved_at.isoformat()},
            )
            self.db.commit()

            incident = self._get_incident_or_404(incident_id)
            lark_result = self._send_lark_recovery_ticket_for_incident(incident)
            self._append_action_log(
                incident,
                action="resolved_ticket_notified",
                message="Incident 关闭后已发送（或尝试发送）Lark 恢复卡片",
                actor_user_id=actor.id if actor else None,
                action_meta={
                    "lark_status": lark_result.get("status"),
                    "message_id": lark_result.get("message_id"),
                    "error_message": lark_result.get("error_message"),
                },
            )
            self.db.commit()
        return self.get_incident_detail(incident_id)

