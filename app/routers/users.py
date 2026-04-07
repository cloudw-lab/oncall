from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
from ..database import get_db
from .. import models, schemas
from ..security import get_current_admin, get_current_user, get_current_user_optional, hash_password

router = APIRouter()


def _normalize_role(role_value: str | None) -> str:
    role = (role_value or "operator").strip().lower()
    if role not in {"admin", "operator"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role 仅支持 admin/operator")
    return role


@router.post("/", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas.UserCreate,
    current_user: models.User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    has_any_user = db.query(models.User.id).first() is not None
    if has_any_user and (not current_user or (current_user.role or "operator") != "admin"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请以管理员身份登录后再创建用户")

    # 检查用户是否存在
    db_user = db.query(models.User).filter(
        (models.User.username == user.username) | 
        (models.User.email == user.email)
    ).first()
    
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名或邮箱已被注册"
        )
    
    # 创建用户
    is_bootstrap = not has_any_user
    assigned_role = "admin" if is_bootstrap else _normalize_role(user.role)
    new_user = models.User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        team=user.team,
        role=assigned_role,
        skills=user.skills,
        max_shifts_per_week=user.max_shifts_per_week,
        max_night_shifts_per_week=user.max_night_shifts_per_week,
        no_nights=user.no_nights,
        hashed_password=hash_password(user.password)
    )
    new_user.phone_plain = user.phone
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@router.get("/", response_model=List[schemas.UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    users = db.query(models.User).filter(models.User.is_active == True).offset(skip).limit(limit).all()
    return users


@router.get("/{user_id}", response_model=schemas.UserResponse)
def get_user(
    user_id: int,
    _: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    user_update: schemas.UserUpdate,
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    update_data = user_update.model_dump(exclude_unset=True)
    phone_marker = object()
    new_phone = update_data.pop("phone", phone_marker)
    if "role" in update_data:
        update_data["role"] = _normalize_role(update_data.get("role"))

    # 邮箱唯一约束前置校验，避免数据库异常直接抛 500。
    new_email = update_data.get("email")
    if new_email and new_email != user.email:
        duplicate_user = db.query(models.User).filter(
            models.User.email == new_email,
            models.User.id != user_id,
        ).first()
        if duplicate_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被注册"
            )

    for field, value in update_data.items():
        setattr(user, field, value)

    if new_phone is not phone_marker:
        user.phone_plain = new_phone

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名或邮箱已被注册"
        )

    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    _: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.is_active = False
    db.commit()
    return {"message": "用户已删除"}
