from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..security import get_current_admin
from ..services.keycloak_service import KeycloakSyncService

router = APIRouter(prefix=f"{settings.API_V1_STR}/integrations/keycloak", tags=["Keycloak"])


def _ensure_enabled():
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未开启 Keycloak 集成")


@router.post("/sync", dependencies=[Depends(get_current_admin)])
def trigger_sync(db: Session = Depends(get_db)):
    _ensure_enabled()
    service = KeycloakSyncService(db)
    return service.sync_users()


@router.get("/status", dependencies=[Depends(get_current_admin)])
def get_status():
    return {
        "enabled": settings.KEYCLOAK_ENABLED,
        "server_url": settings.KEYCLOAK_SERVER_URL,
        "realm": settings.KEYCLOAK_REALM,
        "sync_interval_minutes": settings.KEYCLOAK_SYNC_INTERVAL_MINUTES,
        "disable_missing": settings.KEYCLOAK_DISABLE_MISSING,
    }

