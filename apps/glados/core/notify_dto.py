# apps\glados\core\notify_dto.py

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

    point: int = 0

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "point": self.point,
        }


@dataclass
class CodeResult(TaskResult):
    """礼品码兑换结果。"""

    days: int = 0

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "days": self.days,
        }


@dataclass
class RedeemResult(TaskResult):
    """蛋糕兑换结果。"""

    amount: int = 0

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "amount": self.amount,
        }


# ================================================================
# 账户信息
# ================================================================


@dataclass
class AccountInfo:
    """账户信息。"""

    username: str

    points: int
    left_days: int

    # 流量单位：bytes
    current_traffic: int
    total_traffic: int

    # 使用百分比：0 ~ 100
    use_percent: float

    # 签到信息
    continuous_checkin_days: int = 0  # 连续签到天数
    total_checkin_days: int = 0  # 总签到天数

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "points": self.points,
            "left_days": self.left_days,
            "current_traffic": self.current_traffic,
            "total_traffic": self.total_traffic,
            "use_percent": self.use_percent,
            "continuous_checkin_days": self.continuous_checkin_days,
            "total_checkin_days": self.total_checkin_days,
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

    codes: list[CodeResult] = field(
        default_factory=list,
    )

    redeem: list[RedeemResult] = field(
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
                self.codes,
                self.redeem,
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
                points=item["points"],
                left_days=item["left_days"],
                current_traffic=item["current_traffic"],
                total_traffic=item["total_traffic"],
                use_percent=item["use_percent"],
                continuous_checkin_days=item.get("continuous_checkin_days", 0),
                total_checkin_days=item.get("total_checkin_days", 0),
            )
            for item in data.get("accounts", [])
        ]

        checkin = [
            CheckinResult(
                username=item["username"],
                success=item["success"],
                point=item.get("point", 0),
                message=item.get("message", ""),
            )
            for item in data.get("checkin", [])
        ]

        codes = [
            CodeResult(
                username=item["username"],
                success=item["success"],
                days=item.get("days", 0),
                message=item.get("message", ""),
            )
            for item in data.get("codes", [])
        ]

        redeem = [
            RedeemResult(
                username=item["username"],
                success=item["success"],
                amount=item.get("amount", 0),
                message=item.get("message", ""),
            )
            for item in data.get("redeem", [])
        ]

        return cls(
            app=app,
            accounts=accounts,
            checkin=checkin,
            codes=codes,
            redeem=redeem,
        )
