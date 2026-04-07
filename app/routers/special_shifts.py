from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..models import ShiftType
from ..security import get_current_user, is_admin_user, require_schedule_access

router = APIRouter()


def _get_schedule_or_404(db: Session, schedule_id: int) -> models.Schedule:
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="排班表不存在")
    return schedule


def _assert_member_can_be_assigned(db: Session, schedule_id: int, user_id: int):
    user = db.query(models.User).filter(models.User.id == user_id, models.User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"用户不存在或已禁用: {user_id}")

    member = db.query(models.ScheduleMember).filter(
        models.ScheduleMember.schedule_id == schedule_id,
        models.ScheduleMember.user_id == user_id,
        models.ScheduleMember.is_active == True,
    ).first()
    if not member:
        raise HTTPException(status_code=400, detail=f"用户不在排班成员中: {user_id}")


def _build_shift_window(schedule: models.Schedule, shift_date: date, shift_type: ShiftType) -> Tuple[datetime, datetime]:
    handover_hour = schedule.handover_hour if schedule.handover_hour is not None else 9
    day_start = datetime.combine(shift_date, time(hour=handover_hour, minute=0))
    day_end = day_start + timedelta(days=1)

    if shift_type == ShiftType.NIGHT:
        return day_start + timedelta(hours=9), day_start + timedelta(days=1)
    return day_start, day_end


@router.get("/", response_model=List[schemas.SpecialShiftResponse])
def list_special_shifts(
    schedule_id: Optional[int] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.SpecialShift)
    if schedule_id:
        require_schedule_access(db, current_user, schedule_id)
        query = query.filter(models.SpecialShift.schedule_id == schedule_id)
    elif not is_admin_user(current_user):
        query = query.join(
            models.ScheduleMember,
            models.ScheduleMember.schedule_id == models.SpecialShift.schedule_id,
        ).filter(
            models.ScheduleMember.user_id == current_user.id,
            models.ScheduleMember.is_active == True,
        )
    if start_date:
        query = query.filter(models.SpecialShift.shift_date >= start_date)
    if end_date:
        query = query.filter(models.SpecialShift.shift_date <= end_date)
    return query.order_by(models.SpecialShift.shift_date, models.SpecialShift.shift_type, models.SpecialShift.role).all()


@router.post("/", response_model=schemas.SpecialShiftResponse, status_code=status.HTTP_201_CREATED)
def create_special_shift(
    payload: schemas.SpecialShiftCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_schedule_or_404(db, payload.schedule_id)
    require_schedule_access(db, current_user, payload.schedule_id)
    _assert_member_can_be_assigned(db, payload.schedule_id, payload.user_id)

    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")

    exists = db.query(models.SpecialShift.id).filter(
        models.SpecialShift.schedule_id == payload.schedule_id,
        models.SpecialShift.shift_date == payload.shift_date,
        models.SpecialShift.shift_type == payload.shift_type,
        models.SpecialShift.role == payload.role,
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="该槽位已存在特殊排班")

    row = models.SpecialShift(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{special_shift_id}", response_model=schemas.SpecialShiftResponse)
def update_special_shift(
    special_shift_id: int,
    payload: schemas.SpecialShiftUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.SpecialShift).filter(models.SpecialShift.id == special_shift_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="特殊排班不存在")
    require_schedule_access(db, current_user, row.schedule_id)

    update_data = payload.model_dump(exclude_unset=True)

    new_user_id = update_data.get("user_id", row.user_id)
    _assert_member_can_be_assigned(db, row.schedule_id, new_user_id)

    new_shift_date = update_data.get("shift_date", row.shift_date)
    new_shift_type = update_data.get("shift_type", row.shift_type)
    new_role = update_data.get("role", row.role)

    conflict = db.query(models.SpecialShift.id).filter(
        models.SpecialShift.schedule_id == row.schedule_id,
        models.SpecialShift.shift_date == new_shift_date,
        models.SpecialShift.shift_type == new_shift_type,
        models.SpecialShift.role == new_role,
        models.SpecialShift.id != row.id,
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="该槽位已存在其他特殊排班")

    for field, value in update_data.items():
        setattr(row, field, value)

    if row.start_time >= row.end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")

    db.commit()
    db.refresh(row)
    return row


@router.delete("/{special_shift_id}")
def delete_special_shift(
    special_shift_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.SpecialShift).filter(models.SpecialShift.id == special_shift_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="特殊排班不存在")
    require_schedule_access(db, current_user, row.schedule_id)

    db.delete(row)
    db.commit()
    return {"message": "特殊排班已删除"}


@router.post("/schedules/{schedule_id}/bulk", response_model=schemas.SpecialShiftBulkImportResponse)
def bulk_import_special_shifts(
    schedule_id: int,
    payload: schemas.SpecialShiftBulkImportRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = _get_schedule_or_404(db, schedule_id)
    require_schedule_access(db, current_user, schedule_id)

    failures: List[schemas.SpecialShiftBulkImportFailure] = []
    created_count = 0
    seen_slots = set()

    for index, item in enumerate(payload.items):
        slot_key = (item.shift_date, item.shift_type, item.role)
        if slot_key in seen_slots:
            failures.append(schemas.SpecialShiftBulkImportFailure(
                index=index,
                shift_date=item.shift_date,
                shift_type=item.shift_type,
                role=item.role,
                user_id=item.user_id,
                reason="导入数据内存在重复槽位",
            ))
            continue
        seen_slots.add(slot_key)

        try:
            _assert_member_can_be_assigned(db, schedule_id, item.user_id)


            start_time, end_time = _build_shift_window(schedule, item.shift_date, item.shift_type)

            existing = db.query(models.SpecialShift).filter(
                models.SpecialShift.schedule_id == schedule_id,
                models.SpecialShift.shift_date == item.shift_date,
                models.SpecialShift.shift_type == item.shift_type,
                models.SpecialShift.role == item.role,
            ).first()

            if existing and not payload.overwrite:
                raise HTTPException(status_code=409, detail="该槽位已存在特殊排班")

            if existing and payload.overwrite:
                existing.user_id = item.user_id
                existing.start_time = start_time
                existing.end_time = end_time
                existing.notes = item.notes
                existing.is_locked = True
            else:
                db.add(models.SpecialShift(
                    schedule_id=schedule_id,
                    user_id=item.user_id,
                    shift_type=item.shift_type,
                    role=item.role,
                    shift_date=item.shift_date,
                    start_time=start_time,
                    end_time=end_time,
                    notes=item.notes,
                    is_locked=True,
                ))
            created_count += 1
        except HTTPException as exc:
            failures.append(schemas.SpecialShiftBulkImportFailure(
                index=index,
                shift_date=item.shift_date,
                shift_type=item.shift_type,
                role=item.role,
                user_id=item.user_id,
                reason=str(exc.detail),
            ))

    db.commit()
    return {
        "created_count": created_count,
        "failed_count": len(failures),
        "failures": failures,
    }

