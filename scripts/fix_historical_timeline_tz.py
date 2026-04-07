#!/usr/bin/env python3
"""Shift historical UTC-created timestamps to configured server timezone.

This script is intended for legacy rows written by SQLite `CURRENT_TIMESTAMP`
(UTC) before timeline timestamps were explicitly persisted in server-local time.

Default target columns (timeline-related):
- alert_incidents.created_at
- incident_action_logs.created_at
- alert_notifications.created_at

Use --apply to execute updates. Without --apply it runs in dry-run mode.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from app.config import settings


@dataclass
class TargetColumn:
    table: str
    column: str


TARGETS: tuple[TargetColumn, ...] = (
    TargetColumn("alert_incidents", "created_at"),
    TargetColumn("incident_action_logs", "created_at"),
    TargetColumn("alert_notifications", "created_at"),
)


def _parse_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    # SQLite commonly stores: YYYY-MM-DD HH:MM:SS[.ffffff]
    text = text.replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_storage_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _server_offset() -> timedelta:
    tz_name = settings.SERVER_TIMEZONE or "UTC"
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    return now_local.utcoffset() or timedelta(0)


def _iter_candidates(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    cutoff: datetime,
) -> Iterable[tuple[int, datetime, str]]:
    sql = f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
    rows = conn.execute(sql).fetchall()
    for row_id, raw in rows:
        if raw is None:
            continue
        parsed = _parse_datetime(str(raw))
        if not parsed:
            continue
        if parsed < cutoff:
            yield int(row_id), parsed, str(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix historical timeline timestamps from UTC to server timezone")
    parser.add_argument("--db", default="oncall.db", help="Path to sqlite db file")
    parser.add_argument(
        "--before",
        default=None,
        help="Only shift rows earlier than this local datetime (ISO-like, e.g. 2026-04-04T02:50:00)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply updates (default: dry-run)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    offset = _server_offset()
    if offset == timedelta(0):
        print("[warn] server timezone offset is 0. Nothing to shift for UTC->local migration.")

    if args.before:
        cutoff = _parse_datetime(args.before)
        if not cutoff:
            raise SystemExit("Invalid --before value")
    else:
        cutoff = datetime.now()

    print(f"db={db_path}")
    print(f"server_timezone={settings.SERVER_TIMEZONE}")
    print(f"utc_shift={offset}")
    print(f"cutoff={cutoff.isoformat(sep=' ')}")
    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'}")

    conn = sqlite3.connect(str(db_path))
    try:
        total_updates = 0
        for target in TARGETS:
            candidates = list(_iter_candidates(conn, target.table, target.column, cutoff))
            print(f"{target.table}.{target.column}: candidates={len(candidates)}")
            total_updates += len(candidates)

            if not args.apply or not candidates:
                continue

            for row_id, parsed, _raw in candidates:
                fixed = parsed + offset
                conn.execute(
                    f"UPDATE {target.table} SET {target.column} = ? WHERE id = ?",
                    (_to_storage_text(fixed), row_id),
                )

        if args.apply:
            conn.commit()
            print(f"updated_rows={total_updates}")
        else:
            print(f"would_update_rows={total_updates}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

