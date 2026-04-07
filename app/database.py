from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _sqlite_table_columns(conn, table_name: str):
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


def ensure_sqlite_schema_compatibility():
    """为本地 SQLite 旧库补齐新增字段，避免模型升级后运行时报 500。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    alterations = {
        "users": [
            ("team", "ALTER TABLE users ADD COLUMN team VARCHAR DEFAULT 'SRE'"),
            ("role", "ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'operator'"),
            ("skills", "ALTER TABLE users ADD COLUMN skills TEXT DEFAULT '[]'"),
            ("max_shifts_per_week", "ALTER TABLE users ADD COLUMN max_shifts_per_week INTEGER"),
            ("max_night_shifts_per_week", "ALTER TABLE users ADD COLUMN max_night_shifts_per_week INTEGER"),
            ("no_nights", "ALTER TABLE users ADD COLUMN no_nights BOOLEAN DEFAULT 0"),
            ("keycloak_id", "ALTER TABLE users ADD COLUMN keycloak_id VARCHAR"),
            ("keycloak_sync_at", "ALTER TABLE users ADD COLUMN keycloak_sync_at DATETIME"),
            ("keycloak_groups", "ALTER TABLE users ADD COLUMN keycloak_groups TEXT DEFAULT '[]'"),
        ],
        "schedules": [
            ("timezone", "ALTER TABLE schedules ADD COLUMN timezone VARCHAR DEFAULT 'Asia/Shanghai'"),
            ("handover_hour", "ALTER TABLE schedules ADD COLUMN handover_hour INTEGER DEFAULT 9"),
            ("repeat_count", "ALTER TABLE schedules ADD COLUMN repeat_count INTEGER DEFAULT 0"),
            ("owner_id", "ALTER TABLE schedules ADD COLUMN owner_id INTEGER"),
        ],
        "shifts": [
            ("role", "ALTER TABLE shifts ADD COLUMN role VARCHAR DEFAULT 'PRIMARY'"),
            ("shift_date", "ALTER TABLE shifts ADD COLUMN shift_date DATE"),
            ("is_locked", "ALTER TABLE shifts ADD COLUMN is_locked BOOLEAN DEFAULT 0"),
        ],
    }

    with engine.begin() as conn:
        for table_name, column_sql_list in alterations.items():
            table_columns = _sqlite_table_columns(conn, table_name)
            if not table_columns:
                continue
            for column_name, alter_sql in column_sql_list:
                if column_name not in table_columns:
                    conn.execute(text(alter_sql))

        # 保证至少有一个管理员，避免旧库升级后无法进行配置操作。
        conn.execute(text("""
            UPDATE users
            SET role = 'operator'
            WHERE role IS NULL OR trim(role) = ''
        """))
        conn.execute(text("""
            UPDATE users
            SET role = 'admin'
            WHERE id = (SELECT MIN(id) FROM users)
        """))

        # 历史兼容：把通过 notes 标记 [SPECIAL] 的旧班次迁移到独立表。
        conn.execute(text("""
            INSERT INTO special_shifts (
                schedule_id, user_id, shift_type, role, shift_date, start_time, end_time, notes, is_locked
            )
            SELECT
                s.schedule_id,
                s.user_id,
                s.shift_type,
                COALESCE(s.role, 'PRIMARY'),
                COALESCE(s.shift_date, date(s.start_time)),
                s.start_time,
                s.end_time,
                NULLIF(trim(replace(COALESCE(s.notes, ''), '[SPECIAL]', '')), ''),
                1
            FROM shifts s
            WHERE COALESCE(s.notes, '') LIKE '%[SPECIAL]%'
              AND NOT EXISTS (
                SELECT 1
                FROM special_shifts ss
                WHERE ss.schedule_id = s.schedule_id
                  AND ss.shift_date = COALESCE(s.shift_date, date(s.start_time))
                  AND ss.shift_type = s.shift_type
                  AND ss.role = COALESCE(s.role, 'PRIMARY')
              )
        """))

        conn.execute(text("DELETE FROM shifts WHERE COALESCE(notes, '') LIKE '%[SPECIAL]%'"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
