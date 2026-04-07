from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from .models import RotationType, ShiftType, ShiftRole, AlertEventStatus, AlertIncidentStatus


# User schemas
class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    team: str = "SRE"
    role: str = "operator"
    skills: List[str] = Field(default_factory=list)
    max_shifts_per_week: Optional[int] = None
    max_night_shifts_per_week: Optional[int] = None
    no_nights: bool = False


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    team: Optional[str] = None
    role: Optional[str] = None
    skills: Optional[List[str]] = None
    max_shifts_per_week: Optional[int] = None
    max_night_shifts_per_week: Optional[int] = None
    no_nights: Optional[bool] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    full_name: str
    phone: Optional[str] = Field(default=None, alias="phone_plain")
    masked_phone: Optional[str] = None
    team: str = "SRE"
    role: str = "operator"
    skills: List[str] = Field(default_factory=list)
    max_shifts_per_week: Optional[int] = None
    max_night_shifts_per_week: Optional[int] = None
    no_nights: bool = False
    is_active: bool
    keycloak_id: Optional[str] = None
    keycloak_groups: List[str] = Field(default_factory=list)
    keycloak_sync_at: Optional[datetime] = Field(default=None, alias="keycloak_sync_at")
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


# Schedule schemas
class ScheduleBase(BaseModel):
    name: str
    description: Optional[str] = None
    rotation_type: RotationType = RotationType.WEEKLY
    rotation_interval: int = 1
    handover_hour: int = 9
    repeat_count: int = 0
    start_date: datetime
    end_date: Optional[datetime] = None
    timezone: str = "Asia/Shanghai"
    owner_id: Optional[int] = None


class ScheduleCreate(ScheduleBase):
    owner_id: int
    member_ids: List[int] = []


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rotation_type: Optional[RotationType] = None
    rotation_interval: Optional[int] = None
    handover_hour: Optional[int] = None
    repeat_count: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    timezone: Optional[str] = None
    owner_id: Optional[int] = None
    member_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None


class ScheduleResponse(ScheduleBase):
    id: int
    is_active: bool
    created_at: datetime
    member_count: int = 0
    member_ids: List[int] = Field(default_factory=list)
    member_names: List[str] = Field(default_factory=list)
    owner_name: Optional[str] = None
    cti_values: List[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class ScheduleBatchDeleteRequest(BaseModel):
    schedule_ids: List[int] = Field(default_factory=list)


class ScheduleBatchDeleteResponse(BaseModel):
    deleted_count: int
    not_found_ids: List[int] = Field(default_factory=list)
    forbidden_ids: List[int] = Field(default_factory=list)


# Shift schemas
class ShiftBase(BaseModel):
    shift_type: ShiftType = ShiftType.DAY
    role: ShiftRole = ShiftRole.PRIMARY
    shift_date: Optional[date] = None
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None


class ShiftCreate(ShiftBase):
    schedule_id: int
    user_id: int


class ShiftUpdate(BaseModel):
    user_id: Optional[int] = None
    shift_type: Optional[ShiftType] = None
    role: Optional[ShiftRole] = None
    shift_date: Optional[date] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    notes: Optional[str] = None
    is_handover: Optional[bool] = None
    is_locked: Optional[bool] = None


class ShiftResponse(ShiftBase):
    id: int
    schedule_id: int
    user_id: int
    is_handover: bool
    is_locked: bool
    created_at: datetime
    user: UserResponse
    
    class Config:
        from_attributes = True


class SpecialShiftBase(BaseModel):
    shift_type: ShiftType = ShiftType.FULL_DAY
    role: ShiftRole = ShiftRole.PRIMARY
    shift_date: date
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None
    is_locked: bool = True


class SpecialShiftCreate(SpecialShiftBase):
    schedule_id: int
    user_id: int


class SpecialShiftUpdate(BaseModel):
    user_id: Optional[int] = None
    shift_type: Optional[ShiftType] = None
    role: Optional[ShiftRole] = None
    shift_date: Optional[date] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    notes: Optional[str] = None
    is_locked: Optional[bool] = None


class SpecialShiftResponse(SpecialShiftBase):
    id: int
    schedule_id: int
    user_id: int
    created_at: datetime
    user: UserResponse

    class Config:
        from_attributes = True


class SpecialShiftBulkImportItem(BaseModel):
    user_id: int
    shift_date: date
    shift_type: ShiftType = ShiftType.FULL_DAY
    role: ShiftRole = ShiftRole.PRIMARY
    notes: Optional[str] = None


class SpecialShiftBulkImportRequest(BaseModel):
    items: List[SpecialShiftBulkImportItem] = Field(default_factory=list)
    overwrite: bool = False


class SpecialShiftBulkImportFailure(BaseModel):
    index: int
    shift_date: Optional[date] = None
    shift_type: Optional[ShiftType] = None
    role: Optional[ShiftRole] = None
    user_id: Optional[int] = None
    reason: str


class SpecialShiftBulkImportResponse(BaseModel):
    created_count: int
    failed_count: int
    failures: List[SpecialShiftBulkImportFailure] = Field(default_factory=list)


# Exchange schemas
class ExchangeRequestCreate(BaseModel):
    requester_id: int
    shift_id: int
    responder_id: int
    reason: str


class ExchangeRequestUpdate(BaseModel):
    status: str  # approved or rejected


class ExchangeRequestResponse(BaseModel):
    id: int
    requester_id: int
    responder_id: int
    shift_id: int
    reason: str
    status: str
    created_at: datetime
    responded_at: Optional[datetime] = None
    requester: UserResponse
    responder: UserResponse
    shift: ShiftResponse
    
    class Config:
        from_attributes = True


# Token schemas
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class BlackoutDateRule(BaseModel):
    date: date
    disallow_nights: bool = False
    disallow_members: List[int] = Field(default_factory=list)


class ScheduleRuleBase(BaseModel):
    max_shifts_per_week: int = 7
    max_night_shifts_per_week: int = 4
    avoid_consecutive_nights: bool = True
    max_consecutive_work_days: int = 7
    fairness_threshold: int = 2
    use_volunteers_only: bool = False
    volunteer_member_ids: List[int] = Field(default_factory=list)
    holiday_dates: List[date] = Field(default_factory=list)
    blackout_dates: List[BlackoutDateRule] = Field(default_factory=list)


class ScheduleRuleUpsert(ScheduleRuleBase):
    pass


class ScheduleRuleResponse(ScheduleRuleBase):
    id: int
    schedule_id: int

    class Config:
        from_attributes = True


class ScheduleGenerateRequest(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    include_secondary: bool = True
    regenerate: bool = True


class UnassignedSlot(BaseModel):
    date: date
    shift_type: ShiftType
    role: ShiftRole
    reason: str


class ScheduleGenerateResponse(BaseModel):
    generated_count: int
    unassigned_slots: List[UnassignedSlot]


class ValidationIssueData(BaseModel):
    type: str
    member_id: Optional[int] = None
    date: Optional[date] = None
    message: str


class ScheduleValidateRequest(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ScheduleValidateResponse(BaseModel):
    is_valid: bool
    errors: List[ValidationIssueData]
    warnings: List[ValidationIssueData]


class MemberScheduleResponse(BaseModel):
    member_id: int
    shifts: List[ShiftResponse]


class TodayScheduleItem(BaseModel):
    schedule_id: int
    schedule_name: str
    date: date
    assignments: Dict[str, Dict[str, Optional[UserResponse]]]


class CurrentOncallSummary(BaseModel):
    shift_kind: Optional[str] = None
    role: Optional[ShiftRole] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    user: Optional[UserResponse] = None


class AlertSourceBase(BaseModel):
    source_key: str
    name: str
    description: Optional[str] = None
    schedule_id: int
    channel: str = "email"
    config: Dict[str, Any] = Field(default_factory=dict)


class AlertSourceUpsert(AlertSourceBase):
    is_active: bool = True


class AlertSourceResponse(AlertSourceBase):
    id: int
    is_active: bool
    created_at: datetime
    schedule_name: Optional[str] = None
    open_incident_count: int = 0
    current_oncall: Optional[CurrentOncallSummary] = None

    class Config:
        from_attributes = True


class AlertEventIngest(BaseModel):
    source_key: str
    schedule_id: Optional[int] = None
    source_name: Optional[str] = None
    cti: Optional[str] = None
    fingerprint: str
    title: str
    summary: Optional[str] = None
    severity: str = "critical"
    status: AlertEventStatus = AlertEventStatus.TRIGGERED
    external_event_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class AlertEventResponse(BaseModel):
    id: int
    source_id: int
    incident_id: int
    schedule_id: int
    external_event_id: Optional[str] = None
    fingerprint: str
    hash: Optional[str] = None
    event_status: AlertEventStatus
    severity: str
    title: str
    summary: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class AlertNotificationResponse(BaseModel):
    id: int
    incident_id: int
    event_id: int
    user_id: Optional[int] = None
    channel: str
    status: str
    recipient: Optional[str] = None
    subject: str
    body: str
    error_message: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


class IncidentActionLogResponse(BaseModel):
    id: int
    incident_id: int
    action: str
    actor_user_id: Optional[int] = None
    message: str
    action_meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    actor_user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


class AlertIncidentResponse(BaseModel):
    id: int
    source_id: int
    schedule_id: int
    fingerprint: str
    hash: Optional[str] = None
    status: AlertIncidentStatus
    severity: str
    title: str
    summary: Optional[str] = None
    assigned_user_id: Optional[int] = None
    assigned_role: Optional[ShiftRole] = None
    assigned_shift_kind: Optional[str] = None
    first_event_at: datetime
    latest_event_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by_user_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolved_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    assigned_user: Optional[UserResponse] = None
    acknowledged_by: Optional[UserResponse] = None
    resolved_by: Optional[UserResponse] = None
    source_name: Optional[str] = None
    schedule_name: Optional[str] = None
    event_count: int = 0
    notification_count: int = 0
    latest_event_status: Optional[AlertEventStatus] = None

    class Config:
        from_attributes = True


class AlertIncidentDetailResponse(AlertIncidentResponse):
    source: Optional[AlertSourceResponse] = None
    events: List[AlertEventResponse] = Field(default_factory=list)
    notifications: List[AlertNotificationResponse] = Field(default_factory=list)
    action_logs: List[IncidentActionLogResponse] = Field(default_factory=list)
    current_oncall: Optional[CurrentOncallSummary] = None
    schedule_coverage: Optional[TodayScheduleItem] = None


class IncidentActionRequest(BaseModel):
    user_id: Optional[int] = None
    note: Optional[str] = None


class LarkAppConfigBase(BaseModel):
    enabled: bool = False
    app_id: Optional[str] = None
    app_secret: Optional[str] = None


class LarkAppConfigUpsert(LarkAppConfigBase):
    pass


class LarkAppConfigResponse(LarkAppConfigBase):
    id: int

    class Config:
        from_attributes = True


class NightingaleWebhookAuthGenerateRequest(BaseModel):
    username: Optional[str] = None


class NightingaleWebhookAuthStatusResponse(BaseModel):
    enabled: bool
    username: Optional[str] = None
    has_password: bool = False
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NightingaleWebhookAuthGenerateResponse(NightingaleWebhookAuthStatusResponse):
    password: str
    webhook_url: Optional[str] = None


class ScheduleIntegrationConfig(BaseModel):
    """排班表级别的通知/升级配置（MVP：存储在 AlertSource.config 里）"""

    source_key: Optional[str] = None
    source_name: Optional[str] = None

    lark_enabled: bool = False
    lark_chat_id: Optional[str] = None
    cti_values: List[str] = Field(default_factory=list)


    escalation_enabled: bool = True
    escalation_after_minutes: int = 60  # 未关闭升级（保留）

    ack_escalation_enabled: bool = True
    ack_escalation_after_minutes: int = 15
    notify_all_oncall_on_ack_timeout: bool = True

    important_direct_phone: bool = True
    important_severity_threshold: str = "critical"  # >=? MVP: critical 直接电话
    phone_channel: str = "huawei_stub"
    huawei_phone_api_url: Optional[str] = None
    huawei_app_key: Optional[str] = None
    huawei_app_secret: Optional[str] = None
    huawei_target_phones: List[str] = Field(default_factory=list)


class ScheduleIntegrationConfigResponse(ScheduleIntegrationConfig):
    schedule_id: int
    schedule_name: Optional[str] = None


class EventIngestResponse(BaseModel):
    deduped: bool
    incident: AlertIncidentResponse
    event: AlertEventResponse
    notifications: List[AlertNotificationResponse] = Field(default_factory=list)


