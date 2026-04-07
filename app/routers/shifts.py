from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from ..database import get_db
from .. import models, schemas
from ..security import get_current_user, is_admin_user, require_schedule_access

router = APIRouter()


@router.post("/", response_model=schemas.ShiftResponse, status_code=status.HTTP_201_CREATED)
def create_shift(
    shift: schemas.ShiftCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_schedule_access(db, current_user, shift.schedule_id)
    # 验证时间范围
    if shift.start_time >= shift.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="开始时间必须早于结束时间"
        )
    
    db_shift = models.Shift(
        schedule_id=shift.schedule_id,
        user_id=shift.user_id,
        shift_type=shift.shift_type,
        role=shift.role,
        shift_date=shift.shift_date or shift.start_time.date(),
        start_time=shift.start_time,
        end_time=shift.end_time,
        notes=shift.notes
    )
    
    db.add(db_shift)
    db.commit()
    db.refresh(db_shift)
    
    return db_shift


@router.get("/", response_model=List[schemas.ShiftResponse])
def list_shifts(
    schedule_id: int = None,
    user_id: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(models.Shift)
    
    if schedule_id:
        require_schedule_access(db, current_user, schedule_id)
        query = query.filter(models.Shift.schedule_id == schedule_id)
    elif not is_admin_user(current_user):
        query = query.join(
            models.ScheduleMember,
            models.ScheduleMember.schedule_id == models.Shift.schedule_id,
        ).filter(
            models.ScheduleMember.user_id == current_user.id,
            models.ScheduleMember.is_active == True,
        )
    if user_id:
        query = query.filter(models.Shift.user_id == user_id)
    if start_date:
        query = query.filter(models.Shift.end_time >= start_date)
    if end_date:
        query = query.filter(models.Shift.start_time <= end_date)
    
    return query.order_by(models.Shift.start_time).all()


@router.get("/{shift_id}", response_model=schemas.ShiftResponse)
def get_shift(
    shift_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="班次不存在")
    require_schedule_access(db, current_user, shift.schedule_id)
    return shift


@router.put("/{shift_id}", response_model=schemas.ShiftResponse)
def update_shift(
    shift_id: int,
    shift_update: schemas.ShiftUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="班次不存在")
    require_schedule_access(db, current_user, shift.schedule_id)
    
    update_data = shift_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(shift, field, value)
    
    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/{shift_id}")
def delete_shift(
    shift_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="班次不存在")
    require_schedule_access(db, current_user, shift.schedule_id)
    
    db.delete(shift)
    db.commit()
    
    return {"message": "班次已删除"}


@router.post("/{shift_id}/handover")
def handover_shift(
    shift_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """交接班"""
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="班次不存在")
    require_schedule_access(db, current_user, shift.schedule_id)
    
    shift.is_handover = True
    db.commit()
    
    return {"message": "交接班完成"}
