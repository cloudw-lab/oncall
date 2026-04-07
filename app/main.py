from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .config import settings
from .database import engine, Base, ensure_sqlite_schema_compatibility
from .routers import auth, users, schedules, shifts, exchanges, special_shifts, alerts, keycloak
from apscheduler.schedulers.background import BackgroundScheduler
from .services.notification_service import NotificationService
from .database import SessionLocal
from .services.alert_service import AlertService
from .services.keycloak_service import KeycloakSyncService

# 创建数据库表
Base.metadata.create_all(bind=engine)
ensure_sqlite_schema_compatibility()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需要修改
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化调度器
scheduler = BackgroundScheduler()
notification_service = NotificationService()


def start_scheduler():
    """启动定时任务"""
    if settings.SCHEDULER_ENABLED:
        # 每天检查即将开始的 oncall
        scheduler.add_job(
            notification_service.send_daily_reminder,
            'cron',
            hour=9,
            minute=0,
            id='daily_schedule_lark_reminder',
            replace_existing=True,
        )

        def escalation_job():
            db = SessionLocal()
            try:
                count = AlertService(db).scan_and_escalate()
                if count:
                    print(f"[escalation] escalated {count} incidents")
            finally:
                db.close()

        scheduler.add_job(
            escalation_job,
            'interval',
            minutes=1,
            id='incident_escalation_scan',
            replace_existing=True,
        )

        if settings.KEYCLOAK_ENABLED and settings.KEYCLOAK_SYNC_INTERVAL_MINUTES > 0:
            def keycloak_job():
                db = SessionLocal()
                try:
                    KeycloakSyncService(db).sync_users()
                except Exception as exc:  # pragma: no cover - scheduler logging
                    print(f"[keycloak-sync] failed: {exc}")
                finally:
                    db.close()

            scheduler.add_job(
                keycloak_job,
                'interval',
                minutes=settings.KEYCLOAK_SYNC_INTERVAL_MINUTES,
                id='keycloak_user_sync',
                replace_existing=True,
            )
        scheduler.start()


@app.on_event("startup")
async def startup_event():
    start_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()


# 注册路由
app.include_router(auth.router)
app.include_router(users.router, prefix=f"{settings.API_V1_STR}/users", tags=["用户管理"])
app.include_router(schedules.router, prefix=f"{settings.API_V1_STR}/schedules", tags=["排班管理"])
app.include_router(shifts.router, prefix=f"{settings.API_V1_STR}/shifts", tags=["班次管理"])
app.include_router(exchanges.router, prefix=f"{settings.API_V1_STR}/exchanges", tags=["换班管理"])
app.include_router(special_shifts.router, prefix=f"{settings.API_V1_STR}/special-shifts", tags=["特殊排班"])
app.include_router(alerts.router)
app.include_router(keycloak.router)

# 挂载静态文件目录
from pathlib import Path

# 获取项目根目录 - 使用更可靠的方法
try:
    # 尝试从当前文件向上查找
    current_file = Path(__file__).resolve()
    # main.py -> app -> project_root
    project_root = current_file.parent.parent
    static_path = project_root / 'static'
    
    # 如果路径不存在，尝试当前工作目录
    if not static_path.exists():
        import sys
        project_root = Path.cwd()
        static_path = project_root / 'static'
    
    if static_path.exists():
        print(f"✓ 静态文件目录：{static_path}")
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    else:
        print(f"✗ 静态文件目录不存在：{static_path}")
except Exception as e:
    print(f"✗ 挂载静态文件失败：{e}")


@app.get("/")
async def root():
    # 返回前端页面
    from pathlib import Path
    
    try:
        # 尝试从当前文件向上查找
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent
        index_path = project_root / 'static' / 'index.html'
        
        # 如果路径不存在，尝试当前工作目录
        if not index_path.exists():
            project_root = Path.cwd()
            index_path = project_root / 'static' / 'index.html'
        
        if index_path.exists():
            print(f"✓ 返回前端页面：{index_path}")
            return FileResponse(str(index_path))
        else:
            print(f"✗ 前端页面不存在：{index_path}")
    except Exception as e:
        print(f"✗ 加载前端页面失败：{e}")
    
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


def _format_utc_offset(value: datetime) -> str:
    offset = value.utcoffset()
    if not offset:
        return "+00:00"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


@app.get("/api/v1/server-time-meta")
async def server_time_meta():
    tz_name = settings.SERVER_TIMEZONE or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
        tz_name = "UTC"

    now = datetime.now(tz)
    return {
        "timezone": tz_name,
        "utc_offset": _format_utc_offset(now),
        "server_time": now.isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
