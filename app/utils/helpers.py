from datetime import datetime, timedelta


def get_week_start(date: datetime) -> datetime:
    """获取给定日期所在周的周一"""
    return date - timedelta(days=date.weekday())


def get_month_start(date: datetime) -> datetime:
    """获取给定日期所在月的第一天"""
    return date.replace(day=1)


def get_next_day(date: datetime, days: int = 1) -> datetime:
    """获取给定日期的后 N 天"""
    return date + timedelta(days=days)


def format_datetime(dt: datetime) -> str:
    """格式化日期时间"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def is_weekend(date: datetime) -> bool:
    """判断是否为周末"""
    return date.weekday() >= 5
