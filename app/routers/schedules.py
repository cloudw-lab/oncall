import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
from datetime import date, datetime
from ..database import get_db
from .. import models, schemas
from ..security import can_manage_schedule, get_current_admin, get_current_user, is_admin_user, require_schedule_access
from ..services.schedule_service import ScheduleService
from ..services.alert_service import AlertService
from ..services.notification_service import NotificationService

router = APIRouter()


def _default_schedule_source_key(schedule_id: int) -> str:
    return f"schedule-{schedule_id}-default"


def _generate_default_cti(db: Session) -> str:
    existing_values = set()
    sources = db.query(models.AlertSource).all()
    for source in sources:
        config = source.config or {}
        values = config.get("cti_values", [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    existing_values.add(value.strip().lower())

    while True:
        candidate = f"cti-{secrets.token_hex(6)}"
        if candidate.lower() not in existing_values:
            return candidate


def _ensure_schedule_default_integration(db: Session, schedule: models.Schedule) -> models.AlertSource:
    source_key = _default_schedule_source_key(schedule.id)
    source = db.query(models.AlertSource).filter(models.AlertSource.source_key == source_key).first()
    if source:
        config = source.config or {}
        cti_values = config.get("cti_values", [])
        if isinstance(cti_values, list) and any(isinstance(item, str) and item.strip() for item in cti_values):
            return source
    else:
        source = models.AlertSource(
            source_key=source_key,
            name=f"{schedule.name} 默认接入",
            description=f"auto created integration for schedule#{schedule.id}",
            schedule_id=schedule.id,
            channel="email",
            config={},
            is_active=True,
        )
        db.add(source)
        db.flush()

    config = dict(source.config or {})
    config["cti_values"] = config.get("cti_values") or [_generate_default_cti(db)]
    source.config = config
    return source


def _normalize_cti_values(raw_values) -> List[str]:
    if not isinstance(raw_values, list):
        return []
    values = []
    for item in raw_values:
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
    return values


def _build_schedule_cti_map(db: Session, schedule_ids: List[int]) -> Dict[int, List[str]]:
    if not schedule_ids:
        return {}

    source_keys = [_default_schedule_source_key(schedule_id) for schedule_id in schedule_ids]
    sources = db.query(models.AlertSource).filter(models.AlertSource.source_key.in_(source_keys)).all()
    cti_map = {schedule_id: [] for schedule_id in schedule_ids}

    for source in sources:
        if source.schedule_id in cti_map:
            config = source.config or {}
            cti_map[source.schedule_id] = _normalize_cti_values(config.get("cti_values"))
    return cti_map


def _set_schedule_view_fields(schedule: models.Schedule, cti_values: Optional[List[str]] = None):
    active_members = [member for member in schedule.members if member.is_active]
    schedule.member_count = len(active_members)
    schedule.member_ids = [member.user_id for member in active_members]
    schedule.member_names = [member.user.full_name for member in active_members if member.user]
    schedule.owner_name = schedule.owner.full_name if schedule.owner else None
    schedule.cti_values = cti_values or []


def _ensure_owner_exists(db: Session, owner_id: Optional[int]):
    if owner_id is None:
        return
    owner = db.query(models.User).filter(
        models.User.id == owner_id,
        models.User.is_active == True,
    ).first()
    if not owner:
        raise HTTPException(status_code=404, detail=f"负责人不存在: {owner_id}")


@router.post("/", response_model=schemas.ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    schedule: schemas.ScheduleCreate,
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    schedule_service = ScheduleService(db)
    if schedule.owner_id is None:
        raise HTTPException(status_code=400, detail="创建排班时必须设置负责人")
    _ensure_owner_exists(db, schedule.owner_id)

    if schedule.member_ids:
        existing_user_ids = {
            user.id for user in db.query(models.User).filter(
                models.User.id.in_(schedule.member_ids),
                models.User.is_active == True,
            ).all()
        }
        missing_ids = [uid for uid in schedule.member_ids if uid not in existing_user_ids]
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"用户不存在: {missing_ids}")
    
    # 创建排班表
    db_schedule = models.Schedule(
        name=schedule.name,
        description=schedule.description,
        rotation_type=schedule.rotation_type,
        rotation_interval=schedule.rotation_interval,
        handover_hour=schedule.handover_hour,
        repeat_count=schedule.repeat_count,
        start_date=schedule.start_date,
        # 新建排班默认无限期，忽略外部 end_date。
        end_date=None,
        timezone=schedule.timezone,
        owner_id=schedule.owner_id,
    )
    
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    
    # 添加成员
    if schedule.member_ids:
        for idx, user_id in enumerate(schedule.member_ids):
            member = models.ScheduleMember(
                schedule_id=db_schedule.id,
                user_id=user_id,
                order=idx
            )
            db.add(member)
        db.commit()

    # 初始化默认规则
    schedule_service.upsert_rule(db_schedule.id, {})
    source = _ensure_schedule_default_integration(db, db_schedule)

    db.refresh(db_schedule)
    # 新建排班后，按当前成员自动生成基础班次，保证日历里立刻有排班
    if schedule.member_ids:
        schedule_service.generate_mvp(
            schedule=db_schedule,
            # 不传 start/end_date，内部会从 schedule.start_date 开始，
            # 按 repeat_count / end_date / 默认窗口生成
            include_secondary=True,
            regenerate=True,
        )
        db.refresh(db_schedule)
    source_config = source.config or {}
    _set_schedule_view_fields(db_schedule, _normalize_cti_values(source_config.get("cti_values")))
    
    return db_schedule


@router.get("/", response_model=List[schemas.ScheduleResponse])
def list_schedules(
    active_only: bool = True,
    cti: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.Schedule)
    if active_only:
        query = query.filter(models.Schedule.is_active == True)
    if not is_admin_user(current_user):
        query = query.join(
            models.ScheduleMember,
            models.ScheduleMember.schedule_id == models.Schedule.id,
        ).filter(
            models.ScheduleMember.user_id == current_user.id,
            models.ScheduleMember.is_active == True,
        ).distinct()
    schedules = query.all()
    cti_map = _build_schedule_cti_map(db, [schedule.id for schedule in schedules])
    if cti:
        expected = cti.strip().lower()
        schedules = [
            schedule for schedule in schedules
            if any(value.lower() == expected for value in cti_map.get(schedule.id, []))
        ]
    for schedule in schedules:
        _set_schedule_view_fields(schedule, cti_map.get(schedule.id, []))
    return schedules


@router.get("/today", response_model=List[schemas.TodayScheduleItem])
def get_today_oncall(db: Session = Depends(get_db)):
    schedule_service = ScheduleService(db)
    schedules = db.query(models.Schedule).filter(models.Schedule.is_active == True).all()

    result = []
    for schedule in schedules:
        result.append({
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "date": datetime.now().date(),
            "assignments": schedule_service.get_today_assignments(schedule),
        })
    return result


@router.post("/{schedule_id}/send-today-reminder")
def send_today_schedule_reminder(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)
    result = NotificationService().send_schedule_today_brief(db=db, schedule=schedule)
    return {
        "schedule_id": schedule_id,
        "schedule_name": schedule.name,
        **result,
    }


@router.get("/{schedule_id}", response_model=schemas.ScheduleResponse)
def get_schedule(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)
    cti_map = _build_schedule_cti_map(db, [schedule.id])
    _set_schedule_view_fields(schedule, cti_map.get(schedule.id, []))
    return schedule


@router.put("/{schedule_id}", response_model=schemas.ScheduleResponse)
def update_schedule(
    schedule_id: int,
    schedule_update: schemas.ScheduleUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)
    schedule_service = ScheduleService(db)
    
    update_data = schedule_update.model_dump(exclude_unset=True)
    member_ids = update_data.pop("member_ids", None)
    if "owner_id" in update_data and update_data.get("owner_id") is None:
        raise HTTPException(status_code=400, detail="负责人不能为空")
    _ensure_owner_exists(db, update_data.get("owner_id"))

    for field, value in update_data.items():
        setattr(schedule, field, value)

    if member_ids is not None:
        existing_user_ids = {
            user.id for user in db.query(models.User).filter(
                models.User.id.in_(member_ids),
                models.User.is_active == True,
            ).all()
        }
        missing_ids = [uid for uid in member_ids if uid not in existing_user_ids]
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"用户不存在: {missing_ids}")

        db.query(models.ScheduleMember).filter(models.ScheduleMember.schedule_id == schedule.id).delete()
        for idx, user_id in enumerate(member_ids):
            db.add(models.ScheduleMember(
                schedule_id=schedule.id,
                user_id=user_id,
                order=idx,
                is_active=True,
            ))

        # 成员调整后，清理今天及未来的自动班次并按新成员重排，保证后续班次一致。
        today = date.today()
        db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule.id,
            models.Shift.is_locked == False,
            models.Shift.shift_date >= today,
        ).delete(synchronize_session=False)
        if member_ids:
            schedule_service.generate_mvp(
                schedule=schedule,
                start_date=today,
                include_secondary=True,
                regenerate=True,
            )
    
    db.commit()
    db.refresh(schedule)
    cti_map = _build_schedule_cti_map(db, [schedule.id])
    _set_schedule_view_fields(schedule, cti_map.get(schedule.id, []))
    return schedule


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)
    
    schedule.is_active = False
    db.commit()
    return {"message": "排班表已删除"}


@router.post("/batch-delete", response_model=schemas.ScheduleBatchDeleteResponse)
def batch_delete_schedules(
    payload: schemas.ScheduleBatchDeleteRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule_ids = sorted({sid for sid in payload.schedule_ids if sid is not None})
    if not schedule_ids:
        raise HTTPException(status_code=400, detail="请至少提供一个排班表 ID")

    schedules = db.query(models.Schedule).filter(models.Schedule.id.in_(schedule_ids)).all()
    found_ids = {schedule.id for schedule in schedules}
    not_found_ids = [sid for sid in schedule_ids if sid not in found_ids]
    forbidden_ids = []

    deleted_count = 0
    for schedule in schedules:
        if not can_manage_schedule(db, current_user, schedule.id):
            forbidden_ids.append(schedule.id)
            continue
        if schedule.is_active:
            schedule.is_active = False
            deleted_count += 1

    db.commit()
    return {
        "deleted_count": deleted_count,
        "not_found_ids": not_found_ids,
        "forbidden_ids": forbidden_ids,
    }


@router.post("/{schedule_id}/generate", response_model=schemas.ScheduleGenerateResponse)
def regenerate_shifts(
    schedule_id: int,
    payload: Optional[schemas.ScheduleGenerateRequest] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """根据规则重新生成排班"""
    schedule = require_schedule_access(db, current_user, schedule_id)

    schedule_service = ScheduleService(db)
    payload = payload or schemas.ScheduleGenerateRequest()
    result = schedule_service.generate_mvp(
        schedule=schedule,
        start_date=payload.start_date,
        end_date=payload.end_date,
        include_secondary=payload.include_secondary,
        regenerate=payload.regenerate,
    )

    return result


@router.get("/{schedule_id}/rules", response_model=schemas.ScheduleRuleResponse)
def get_schedule_rules(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_schedule_access(db, current_user, schedule_id)

    schedule_service = ScheduleService(db)
    return schedule_service.upsert_rule(schedule_id, {})


@router.post("/{schedule_id}/rules", response_model=schemas.ScheduleRuleResponse)
def upsert_schedule_rules(
    schedule_id: int,
    rule: schemas.ScheduleRuleUpsert,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_schedule_access(db, current_user, schedule_id)

    schedule_service = ScheduleService(db)
    payload = rule.model_dump()
    payload["holiday_dates"] = [str(item) for item in payload.get("holiday_dates", [])]
    payload["blackout_dates"] = [
        {
            "date": str(item["date"]),
            "disallow_nights": item.get("disallow_nights", False),
            "disallow_members": item.get("disallow_members", []),
        }
        for item in payload.get("blackout_dates", [])
    ]
    db_rule = schedule_service.upsert_rule(schedule_id, payload)
    return db_rule


@router.post("/{schedule_id}/validate", response_model=schemas.ScheduleValidateResponse)
def validate_schedule(
    schedule_id: int,
    payload: schemas.ScheduleValidateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    schedule = require_schedule_access(db, current_user, schedule_id)

    schedule_service = ScheduleService(db)
    return schedule_service.validate_mvp(schedule, start_date=payload.start_date, end_date=payload.end_date)


@router.get("/{schedule_id}/member/{user_id}", response_model=schemas.MemberScheduleResponse)
def get_member_schedule(
    schedule_id: int,
    user_id: int,
    start_date: date = None,
    end_date: date = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_schedule_access(db, current_user, schedule_id)

    schedule_service = ScheduleService(db)
    shifts = schedule_service.get_member_shifts(schedule_id, user_id, start_date, end_date)
    return {"member_id": user_id, "shifts": shifts}


@router.get("/{schedule_id}/calendar")
def get_schedule_calendar(
    schedule_id: int,
    start_date: datetime,
    end_date: datetime,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取指定时间范围的排班日历"""
    schedule = require_schedule_access(db, current_user, schedule_id)

    # 只展示与查询窗口有时间交集的班次，同时不展示排班开始日期之前的记录
    query = db.query(models.Shift).filter(
        models.Shift.schedule_id == schedule_id,
        # 与 [start_date, end_date] 有交集：结束时间晚于窗口开始，开始时间早于窗口结束
        models.Shift.end_time >= start_date,
        models.Shift.start_time <= end_date,
    )

    # 进一步约束：不展示排班开始日期之前的班次
    if schedule.start_date:
        query = query.filter(models.Shift.start_time >= schedule.start_date)

    shifts = query.order_by(models.Shift.start_time).all()
    return shifts


@router.get("/{schedule_id}/current", response_model=schemas.CurrentOncallSummary)
def get_current_oncall(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前值班人员"""
    require_schedule_access(db, current_user, schedule_id)
    schedule_service = ScheduleService(db)
    current_context = schedule_service.get_current_oncall_context(schedule_id)
    
    if not current_context:
        raise HTTPException(status_code=404, detail="当前无值班人员")
    
    current_shift = current_context["shift"]
    return {
        "shift_kind": current_context["shift_kind"],
        "role": current_shift.role,
        "start_time": current_shift.start_time,
        "end_time": current_shift.end_time,
        "user": current_shift.user,
    }


@router.get("/{schedule_id}/integrations", response_model=schemas.ScheduleIntegrationConfigResponse)
def get_schedule_integrations(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)

    source_key = _default_schedule_source_key(schedule_id)
    source = db.query(models.AlertSource).filter(models.AlertSource.source_key == source_key).first()
    if not source:
        source = _ensure_schedule_default_integration(db, schedule)
        db.commit()
        db.refresh(source)
    config = (source.config or {}) if source else {}
    lark_enabled = bool(config.get("lark_enabled", False) or config.get("lark_chat_id"))
    return {
        "schedule_id": schedule_id,
        "schedule_name": schedule.name,
        "source_key": source_key,
        "source_name": source.name if source else f"{schedule.name} 默认接入",
        "lark_enabled": lark_enabled,
        "lark_chat_id": config.get("lark_chat_id"),
        "cti_values": config.get("cti_values", []) or [],
        "escalation_enabled": bool(config.get("escalation_enabled", True)),
        "escalation_after_minutes": int(config.get("escalation_after_minutes", 60)),
        "ack_escalation_enabled": bool(config.get("ack_escalation_enabled", True)),
        "ack_escalation_after_minutes": int(config.get("ack_escalation_after_minutes", 15)),
        "notify_all_oncall_on_ack_timeout": bool(config.get("notify_all_oncall_on_ack_timeout", True)),
        "important_direct_phone": bool(config.get("important_direct_phone", True)),
        "important_severity_threshold": config.get("important_severity_threshold", "critical"),
        "phone_channel": config.get("phone_channel", "huawei_stub"),
        "huawei_phone_api_url": config.get("huawei_phone_api_url"),
        "huawei_app_key": config.get("huawei_app_key"),
        "huawei_app_secret": config.get("huawei_app_secret"),
        "huawei_target_phones": config.get("huawei_target_phones", []) or [],
    }


@router.post("/{schedule_id}/integrations", response_model=schemas.ScheduleIntegrationConfigResponse)
def upsert_schedule_integrations(
    schedule_id: int,
    payload: schemas.ScheduleIntegrationConfig,
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="排班表不存在")

    source_key = payload.source_key or _default_schedule_source_key(schedule_id)
    source_name = payload.source_name or f"{schedule.name} 默认接入"
    upsert_payload = schemas.AlertSourceUpsert(
        source_key=source_key,
        name=source_name,
        description=f"schedule integration for schedule#{schedule_id}",
        schedule_id=schedule_id,
        channel="lark" if payload.lark_enabled else "email",
        config={
            "lark_enabled": payload.lark_enabled,
            "lark_chat_id": payload.lark_chat_id,
            "cti_values": [item.strip() for item in (payload.cti_values or []) if isinstance(item, str) and item.strip()],
            "escalation_enabled": payload.escalation_enabled,
            "escalation_after_minutes": payload.escalation_after_minutes,
            "ack_escalation_enabled": payload.ack_escalation_enabled,
            "ack_escalation_after_minutes": payload.ack_escalation_after_minutes,
            "notify_all_oncall_on_ack_timeout": payload.notify_all_oncall_on_ack_timeout,
            "important_direct_phone": payload.important_direct_phone,
            "important_severity_threshold": payload.important_severity_threshold,
            "phone_channel": payload.phone_channel,
            "huawei_phone_api_url": payload.huawei_phone_api_url,
            "huawei_app_key": payload.huawei_app_key,
            "huawei_app_secret": payload.huawei_app_secret,
            "huawei_target_phones": payload.huawei_target_phones,
        },
        is_active=True,
    )
    AlertService(db).upsert_source(upsert_payload)
    return get_schedule_integrations(schedule_id=schedule_id, current_user=_, db=db)


@router.post("/{schedule_id}/integrations/generate-cti", response_model=schemas.ScheduleIntegrationConfigResponse)
def generate_schedule_cti(
    schedule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = require_schedule_access(db, current_user, schedule_id)
    if not can_manage_schedule(db, current_user, schedule_id):
        raise HTTPException(status_code=403, detail="只能管理自己相关的排班表")

    _ensure_schedule_default_integration(db, schedule)
    db.commit()
    return get_schedule_integrations(schedule_id=schedule_id, current_user=current_user, db=db)


