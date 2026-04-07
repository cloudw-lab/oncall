import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 基础配置
    PROJECT_NAME: str = "Oncall 排班平台"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./oncall.db"
    
    # 安全配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天
    
    # 通知配置
    EMAIL_ENABLED: bool = False
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    INCIDENT_LINK_BASE_URL: Optional[str] = None
    LOG_DIR: str = "logs"
    SERVER_TIMEZONE: str = "Asia/Shanghai"
    
    # 调度器配置
    SCHEDULER_ENABLED: bool = True
    ONCALL_PHONE_KEY: Optional[str] = None

    # Keycloak 集成配置
    KEYCLOAK_ENABLED: bool = False
    KEYCLOAK_SERVER_URL: Optional[str] = None
    KEYCLOAK_REALM: Optional[str] = None
    KEYCLOAK_ADMIN_USERNAME: Optional[str] = None
    KEYCLOAK_ADMIN_PASSWORD: Optional[str] = None
    KEYCLOAK_CLIENT_ID: str = "admin-cli"
    KEYCLOAK_CLIENT_SECRET: Optional[str] = None
    KEYCLOAK_VERIFY_SSL: bool = True
    KEYCLOAK_SYNC_INTERVAL_MINUTES: int = 0
    KEYCLOAK_DISABLE_MISSING: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
