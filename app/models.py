from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Boolean, Enum, Text, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from .database import Base


class RotationType(str, PyEnum):
    """轮班类型"""
    DAILY = "daily"      # 每日轮换
    WEEKLY = "weekly"    # 每周轮换
    MONTHLY = "monthly"  # 每月轮换
    CUSTOM = "custom"    # 自定义


class ShiftType(str, PyEnum):
    """班次类型"""
    DAY = "day"            # 白班 (09:00-18:00)
    NIGHT = "night"        # 夜班 (18:00-09:00)
    MORNING = "morning"    # 早班 (9:00-18:00)
    MIDDLE = "middle"      # 中班 (18:00-2:00)
    FULL_DAY = "full_day"  # 全天


class ShiftRole(str, PyEnum):
    """值班角色"""
    PRIMARY = "primary"
    SECONDARY = "secondary"


class AlertEventStatus(str, PyEnum):
    """告警事件状态"""
    TRIGGERED = "triggered"
    RESOLVED = "resolved"
    RECOVERED = "recovered"


class AlertIncidentStatus(str, PyEnum):
    """告警状态"""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    phone = Column(String)
    team = Column(String, default="SRE")
    role = Column(String, default="operator")  # admin / operator
    skills = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    max_shifts_per_week = Column(Integer, nullable=True)
    max_night_shifts_per_week = Column(Integer, nullable=True)
    no_nights = Column(Boolean, default=False)
    keycloak_id = Column(String, unique=True, index=True, nullable=True)
    keycloak_sync_at = Column(DateTime(timezone=True), nullable=True)
    keycloak_groups = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    shifts = relationship("Shift", back_populates="user")
    schedule_memberships = relationship("ScheduleMember", back_populates="user")
    exchange_requests = relationship("ExchangeRequest", foreign_keys="ExchangeRequest.requester_id", back_populates="requester")
    exchange_responses = relationship("ExchangeRequest", foreign_keys="ExchangeRequest.responder_id", back_populates="responder")
    special_shifts = relationship("SpecialShift", back_populates="user")
    assigned_alert_incidents = relationship("AlertIncident", foreign_keys="AlertIncident.assigned_user_id", back_populates="assigned_user")
    acknowledged_alert_incidents = relationship("AlertIncident", foreign_keys="AlertIncident.acknowledged_by_user_id", back_populates="acknowledged_by")
    resolved_alert_incidents = relationship("AlertIncident", foreign_keys="AlertIncident.resolved_by_user_id", back_populates="resolved_by")
    alert_notifications = relationship("AlertNotification", back_populates="user")
    incident_action_logs = relationship("IncidentActionLog", back_populates="actor_user")
    owned_schedules = relationship("Schedule", back_populates="owner", foreign_keys="Schedule.owner_id")

    @property
    def phone_plain(self) -> str | None:
        from .utils.crypto import decrypt_phone

        return decrypt_phone(self.phone)

    @phone_plain.setter
    def phone_plain(self, value: str | None) -> None:
        from .utils.crypto import encrypt_phone

        self.phone = encrypt_phone(value)

    @property
    def masked_phone(self) -> str | None:
        from .utils.crypto import mask_phone

        return mask_phone(self.phone_plain)


class Schedule(Base):
    """排班表"""
    __tablename__ = "schedules"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    rotation_type = Column(Enum(RotationType), default=RotationType.WEEKLY)
    rotation_interval = Column(Integer, default=1)  # 轮换间隔（天/周/月）
    handover_hour = Column(Integer, default=9)  # 交班时间（小时）
    repeat_count = Column(Integer, default=0)  # 0 表示无限重复
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True))
    timezone = Column(String, default="Asia/Shanghai")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    members = relationship("ScheduleMember", back_populates="schedule", cascade="all, delete-orphan")
    shifts = relationship("Shift", back_populates="schedule", cascade="all, delete-orphan")
    special_shifts = relationship("SpecialShift", back_populates="schedule", cascade="all, delete-orphan")
    rule = relationship("ScheduleRule", back_populates="schedule", uselist=False, cascade="all, delete-orphan")
    validation_issues = relationship("ValidationIssue", back_populates="schedule", cascade="all, delete-orphan")
    alert_sources = relationship("AlertSource", back_populates="schedule", cascade="all, delete-orphan")
    alert_events = relationship("AlertEvent", back_populates="schedule", cascade="all, delete-orphan")
    alert_incidents = relationship("AlertIncident", back_populates="schedule", cascade="all, delete-orphan")
    owner = relationship("User", back_populates="owned_schedules", foreign_keys=[owner_id])


class ScheduleRule(Base):
    """排班规则配置（每个排班表一份）"""
    __tablename__ = "schedule_rules"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, unique=True)
    max_shifts_per_week = Column(Integer, default=7)
    max_night_shifts_per_week = Column(Integer, default=4)
    avoid_consecutive_nights = Column(Boolean, default=True)
    max_consecutive_work_days = Column(Integer, default=7)
    fairness_threshold = Column(Integer, default=2)
    use_volunteers_only = Column(Boolean, default=False)
    volunteer_member_ids = Column(JSON, default=list)
    holiday_dates = Column(JSON, default=list)  # 格式 YYYY-MM-DD
    blackout_dates = Column(JSON, default=list)  # [{date, disallow_nights, disallow_members}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    schedule = relationship("Schedule", back_populates="rule")


class ScheduleMember(Base):
    """排班成员关联表"""
    __tablename__ = "schedule_members"
    
    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order = Column(Integer, default=0)  # 轮班顺序
    is_active = Column(Boolean, default=True)
    
    # 关系
    schedule = relationship("Schedule", back_populates="members")
    user = relationship("User", back_populates="schedule_memberships")


class Shift(Base):
    """班次表"""
    __tablename__ = "shifts"
    
    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift_type = Column(Enum(ShiftType), default=ShiftType.FULL_DAY)
    role = Column(Enum(ShiftRole), default=ShiftRole.PRIMARY)
    shift_date = Column(Date, nullable=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_handover = Column(Boolean, default=False)  # 是否已交接
    is_locked = Column(Boolean, default=False)  # 手工锁定，不参与重排
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    schedule = relationship("Schedule", back_populates="shifts")
    user = relationship("User", back_populates="shifts")


class SpecialShift(Base):
    """独立的特殊排班表"""
    __tablename__ = "special_shifts"
    __table_args__ = (
        UniqueConstraint("schedule_id", "shift_date", "shift_type", "role", name="uq_special_shift_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift_type = Column(Enum(ShiftType), default=ShiftType.DAY)
    role = Column(Enum(ShiftRole), default=ShiftRole.PRIMARY)
    shift_date = Column(Date, nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text)
    is_locked = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    schedule = relationship("Schedule", back_populates="special_shifts")
    user = relationship("User", back_populates="special_shifts")


class ExchangeRequest(Base):
    """换班申请表"""
    __tablename__ = "exchange_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    responder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    reason = Column(Text)
    status = Column(String, default="pending")  # pending, approved, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    responded_at = Column(DateTime(timezone=True))
    
    # 关系
    requester = relationship("User", foreign_keys=[requester_id], back_populates="exchange_requests")
    responder = relationship("User", foreign_keys=[responder_id], back_populates="exchange_responses")
    shift = relationship("Shift")


class ValidationIssue(Base):
    """排班校验结果（错误/告警）"""
    __tablename__ = "validation_issues"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    issue_level = Column(String, nullable=False)  # error / warning
    issue_type = Column(String, nullable=False)
    member_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    issue_date = Column(Date, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    schedule = relationship("Schedule", back_populates="validation_issues")
    member = relationship("User")


class LarkAppConfig(Base):
    """全局共享的 Lark 应用配置。"""
    __tablename__ = "lark_app_configs"

    id = Column(Integer, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    app_id = Column(String, nullable=True)
    app_secret = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NightingaleWebhookAuthConfig(Base):
    """Nightingale 回调 Basic Auth 配置（全局单例）。"""
    __tablename__ = "nightingale_webhook_auth_configs"

    id = Column(Integer, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    username = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AlertSource(Base):
    """告警接入源配置"""
    __tablename__ = "alert_sources"

    id = Column(Integer, primary_key=True, index=True)
    source_key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    channel = Column(String, default="email")
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    schedule = relationship("Schedule", back_populates="alert_sources")
    events = relationship("AlertEvent", back_populates="source", cascade="all, delete-orphan")
    incidents = relationship("AlertIncident", back_populates="source", cascade="all, delete-orphan")


class AlertIncident(Base):
    """归并后的告警"""
    __tablename__ = "alert_incidents"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("alert_sources.id"), nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    fingerprint = Column(String, nullable=False, index=True)
    status = Column(Enum(AlertIncidentStatus), default=AlertIncidentStatus.OPEN, index=True)
    severity = Column(String, default="critical")
    title = Column(String, nullable=False)
    summary = Column(Text)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_role = Column(Enum(ShiftRole), nullable=True)
    assigned_shift_kind = Column(String, nullable=True)  # normal / special
    first_event_at = Column(DateTime(timezone=True), nullable=False)
    latest_event_at = Column(DateTime(timezone=True), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    source = relationship("AlertSource", back_populates="incidents")
    schedule = relationship("Schedule", back_populates="alert_incidents")
    assigned_user = relationship("User", foreign_keys=[assigned_user_id], back_populates="assigned_alert_incidents")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id], back_populates="acknowledged_alert_incidents")
    resolved_by = relationship("User", foreign_keys=[resolved_by_user_id], back_populates="resolved_alert_incidents")
    events = relationship("AlertEvent", back_populates="incident", cascade="all, delete-orphan", order_by="AlertEvent.occurred_at")
    notifications = relationship("AlertNotification", back_populates="incident", cascade="all, delete-orphan", order_by="AlertNotification.created_at")
    action_logs = relationship("IncidentActionLog", back_populates="incident", cascade="all, delete-orphan", order_by="IncidentActionLog.created_at")

    @property
    def hash(self) -> str:
        return self.fingerprint


class AlertEvent(Base):
    """外部事件原始入库"""
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id", name="uq_alert_source_external_event"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("alert_sources.id"), nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("alert_incidents.id"), nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    external_event_id = Column(String, nullable=True)
    fingerprint = Column(String, nullable=False, index=True)
    event_status = Column(Enum(AlertEventStatus), default=AlertEventStatus.TRIGGERED)
    severity = Column(String, default="critical")
    title = Column(String, nullable=False)
    summary = Column(Text)
    payload = Column(JSON, default=dict)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("AlertSource", back_populates="events")
    incident = relationship("AlertIncident", back_populates="events")
    schedule = relationship("Schedule", back_populates="alert_events")
    notifications = relationship("AlertNotification", back_populates="event", cascade="all, delete-orphan")

    @property
    def hash(self) -> str:
        return self.fingerprint


class AlertNotification(Base):
    """告警通知记录"""
    __tablename__ = "alert_notifications"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("alert_incidents.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("alert_events.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    channel = Column(String, default="email")
    status = Column(String, default="pending")
    recipient = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("AlertIncident", back_populates="notifications")
    event = relationship("AlertEvent", back_populates="notifications")
    user = relationship("User", back_populates="alert_notifications")


class IncidentActionLog(Base):
    """告警操作日志 / 时间线"""
    __tablename__ = "incident_action_logs"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("alert_incidents.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    message = Column(Text, nullable=False)
    action_meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("AlertIncident", back_populates="action_logs")
    actor_user = relationship("User", back_populates="incident_action_logs")

