"""
SouthPlus 通知报告 DTO。

职责：
    定义通知模块需要的结构化数据。

不负责：
    - HTML 构建
    - HTML 模板渲染
    - 邮件发送
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ================================================================
# 账户信息
# ================================================================


@dataclass
class AccountInfo:
    """SouthPlus 账户信息。"""

    username: str

    # 当前总 SP Point
    points_sp: int = 0

    # 错误次数
    error_count: int = 0

    # 上次错误时间
    last_error_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "points_sp": self.points_sp,
            "error_count": self.error_count,
            "last_error_at": (
                self.last_error_at.isoformat() if self.last_error_at else None
            ),
        }


# ================================================================
# 日常任务
# ================================================================


@dataclass
class DailyTaskInfo:
    """SouthPlus 日常任务信息。"""

    username: str

    # 日常任务累计完成次数
    complete_count: int = 0

    # 上次日常任务完成时间
    last_complete_at: datetime | None = None

    # 下次允许完成时间
    next_complete_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "complete_count": self.complete_count,
            "last_complete_at": (
                self.last_complete_at.isoformat() if self.last_complete_at else None
            ),
            "next_complete_at": (
                self.next_complete_at.isoformat() if self.next_complete_at else None
            ),
        }


# ================================================================
# 周常任务
# ================================================================


@dataclass
class WeeklyTaskInfo:
    """SouthPlus 周常任务信息。"""

    username: str

    # 周常任务累计完成次数
    complete_count: int = 0

    # 上次周常任务完成时间
    last_complete_at: datetime | None = None

    # 下次允许完成时间
    next_complete_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "complete_count": self.complete_count,
            "last_complete_at": (
                self.last_complete_at.isoformat() if self.last_complete_at else None
            ),
            "next_complete_at": (
                self.next_complete_at.isoformat() if self.next_complete_at else None
            ),
        }


# ================================================================
# 应用报告配置
# ================================================================


@dataclass
class AppConfig:
    """应用报告显示配置。"""

    name: str
    icon: str = "🚀"

    gradient_start: str = "#667eea"
    gradient_end: str = "#764ba2"


# ================================================================
# 报告 DTO
# ================================================================


@dataclass
class ReportData:
    """完整报告的数据。

    注意：
        这里保存的是结构化数据。

    不负责：
        - 构建 HTML
        - 加载模板
        - 发送邮件
    """

    app: AppConfig

    accounts: list[AccountInfo] = field(
        default_factory=list,
    )

    daily: list[DailyTaskInfo] = field(
        default_factory=list,
    )

    weekly: list[WeeklyTaskInfo] = field(
        default_factory=list,
    )

    # 允许应用追加自定义 HTML Section。
    extra_sections: list[str] = field(
        default_factory=list,
    )

    @property
    def has_data(self) -> bool:
        """判断报告是否存在数据。"""

        return any(
            (
                self.accounts,
                self.daily,
                self.weekly,
                self.extra_sections,
            )
        )


__all__ = [
    "AccountInfo",
    "AppConfig",
    "DailyTaskInfo",
    "ReportData",
    "WeeklyTaskInfo",
]
