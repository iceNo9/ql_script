"""
时区工具模块。

负责：
    - 提供应用时区对象
    - 提供数据库时区对象（UTC）
    - 提供时间转换函数（UTC ↔ 本地时间）
    - 提供当前时间获取函数（本地/UTC）

依赖：
    - utils.config: 获取全局配置中的时区设置
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from utils.config import get_global_config

# ============================================================================
# 时区对象
# ============================================================================

# 数据库时区（固定 UTC）
DB_TIMEZONE = UTC


def get_app_timezone() -> ZoneInfo:
    """
    获取应用时区。

    从全局配置中读取时区设置。

    Returns:
        ZoneInfo: 应用当前使用的时区。

    Examples:
        >>> from utils.timezone import get_app_timezone
        >>> tz = get_app_timezone()
        >>> tz
        ZoneInfo("Asia/Shanghai")
    """
    config = get_global_config()
    return ZoneInfo(config.timezone.timezone)


# ============================================================================
# 当前时间
# ============================================================================


def now_local() -> datetime:
    """
    获取当前本地时间。

    Returns:
        datetime: 当前本地时间（带时区信息）。

    Examples:
        >>> from utils.timezone import now_local
        >>> now_local()
        datetime.datetime(2026, 8, 20, 14, 30, ...)
    """
    return datetime.now(get_app_timezone())


def now_utc() -> datetime:
    """
    获取当前 UTC 时间。

    Returns:
        datetime: 当前 UTC 时间（带时区信息）。
    """
    return datetime.now(DB_TIMEZONE)


# ============================================================================
# 时间转换
# ============================================================================


def utc_to_local(utc_dt: datetime) -> datetime:
    """
    将 UTC 时间转换为本地时间。

    Args:
        utc_dt: UTC 时间（可带时区或不带）。

    Returns:
        datetime: 本地时间（带时区信息）。

    Examples:
        >>> from utils.timezone import utc_to_local
        >>> from datetime import datetime, timezone
        >>> utc_time = datetime(2026, 8, 20, 6, 0, 0, tzinfo=timezone.utc)
        >>> utc_to_local(utc_time)
        datetime.datetime(2026, 8, 20, 14, 0, ...)
    """
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=DB_TIMEZONE)
    return utc_dt.astimezone(get_app_timezone())


def local_to_utc(local_dt: datetime) -> datetime:
    """
    将本地时间转换为 UTC 时间。

    Args:
        local_dt: 本地时间（可带时区或不带）。

    Returns:
        datetime: UTC 时间（带时区信息）。
    """
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=get_app_timezone())
    return local_dt.astimezone(DB_TIMEZONE)


def format_local_time(utc_dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    将 UTC 时间格式化为本地时间字符串。

    Args:
        utc_dt: UTC 时间（可带时区或不带）。
        fmt: 时间格式，默认为 "%Y-%m-%d %H:%M:%S"。

    Returns:
        str: 本地时间字符串。

    Examples:
        >>> from utils.timezone import format_local_time
        >>> from datetime import datetime, timezone
        >>> utc_time = datetime(2026, 8, 20, 6, 0, 0, tzinfo=timezone.utc)
        >>> format_local_time(utc_time)
        '2026-08-20 14:00:00'
    """
    if utc_dt is None:
        return "-"
    local_dt = utc_to_local(utc_dt)
    return local_dt.strftime(fmt)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "DB_TIMEZONE",
    "format_local_time",
    "get_app_timezone",
    "local_to_utc",
    "now_local",
    "now_utc",
    "utc_to_local",
]
