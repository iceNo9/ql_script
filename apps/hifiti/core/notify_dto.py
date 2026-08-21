# apps/hifiti/core/notify_dto.py

"""
通知报告 DTO。

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
# 通用任务结果 DTO
# ================================================================


@dataclass
class TaskResult:
    """单个任务结果。"""

    username: str
    success: bool
    message: str = ""
    created_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "success": self.success,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class CheckinResult(TaskResult):
    """签到结果。"""

    checkin_gold: int = 0  # 本次签到获得金币
    checkin_rank: int = 0  # 本次签到排名

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "checkin_gold": self.checkin_gold,
            "checkin_rank": self.checkin_rank,
        }


# ================================================================
# 账户信息
# ================================================================


@dataclass
class AccountInfo:
    """账户信息。"""

    username: str
    gold: int = 0  # 当前总金币
    continuous_checkin_days: int = 0  # 连续签到天数
    total_checkin_days: int = 0  # 累计签到天数
    error_count: int = 0  # 错误次数
    last_error_at: datetime | None = None  # 上次错误时间

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "gold": self.gold,
            "continuous_checkin_days": self.continuous_checkin_days,
            "total_checkin_days": self.total_checkin_days,
            "error_count": self.error_count,
            "last_error_at": (
                self.last_error_at.isoformat() if self.last_error_at else None
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

    checkin: list[CheckinResult] = field(
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
                self.checkin,
                self.extra_sections,
            )
        )

    @classmethod
    def from_dict(
        cls,
        app: AppConfig,
        data: dict,
    ) -> ReportData:
        """从旧版 dict 数据创建 ReportData。"""

        accounts = [
            AccountInfo(
                username=item["username"],
                gold=item.get("gold", 0),
                continuous_checkin_days=item.get("continuous_checkin_days", 0),
                total_checkin_days=item.get("total_checkin_days", 0),
                error_count=item.get("error_count", 0),
                last_error_at=item.get("last_error_at"),
            )
            for item in data.get("accounts", [])
        ]

        checkin = [
            CheckinResult(
                username=item["username"],
                success=item["success"],
                checkin_gold=item.get("checkin_gold", 0),
                checkin_rank=item.get("checkin_rank", 0),
                message=item.get("message", ""),
                created_at=item.get("created_at"),
            )
            for item in data.get("checkin", [])
        ]

        return cls(
            app=app,
            accounts=accounts,
            checkin=checkin,
        )


__all__ = [
    "AccountInfo",
    "AppConfig",
    "CheckinResult",
    "ReportData",
    "TaskResult",
]
