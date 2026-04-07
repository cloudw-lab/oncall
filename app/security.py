from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .database import get_db

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if (hashed_password or "").startswith("$2"):
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except Exception:
            return False
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": subject,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def authenticate_user(db: Session, username_or_email: str, password: str) -> Optional[models.User]:
    user = db.query(models.User).filter(
        (models.User.username == username_or_email) |
        (models.User.email == username_or_email)
    ).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _decode_token(token: str) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise credentials_exception from exc

    subject = payload.get("sub")
    if not subject:
        raise credentials_exception
    return str(subject)


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    if not credentials or not credentials.credentials:
        return None

    subject = _decode_token(credentials.credentials)
    user = db.query(models.User).filter(models.User.username == subject).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="当前用户不存在或已禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(current_user: Optional[models.User] = Depends(get_current_user_optional)) -> models.User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if not is_admin_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


def is_admin_user(user: Optional[models.User]) -> bool:
    return ((user.role if user else None) or "operator").lower() == "admin"


def can_manage_schedule(db: Session, user: models.User, schedule_id: int) -> bool:
    if is_admin_user(user):
        return True
    return db.query(models.ScheduleMember.id).filter(
        models.ScheduleMember.schedule_id == schedule_id,
        models.ScheduleMember.user_id == user.id,
        models.ScheduleMember.is_active == True,
    ).first() is not None


def require_schedule_access(db: Session, user: models.User, schedule_id: int) -> models.Schedule:
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="排班表不存在")
    if not can_manage_schedule(db, user, schedule_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能管理自己相关的排班表",
        )
    return schedule


