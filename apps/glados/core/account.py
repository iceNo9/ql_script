# apps\glados\core\account.py

"""
GLaDOS 账号服务。

职责：
    - 确保数据库中存在账号行。
    - 所有对 Account 实体字段的写入（积分 / 天数 / 有效期 / 状态标记）。

不负责：
    - 认证（AuthService）
    - 签到 / 积分 / 状态业务决策与日志（CheckinService / UserService）
    - 事务提交（门面负责）
    - 报告构建（ReportService）
"""

from __future__ import annotations

from datetime import datetime

from apps.glados.core.config import GladosAccountConfig
from apps.glados.core.models import Account
from apps.glados.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import local_to_utc, now_utc

logger = get_logger(
    name="glados_account",
    log_dir=logs(),
    fmt_type="detailed",
)

# 连续失败多少次后标记账号无效
INVALID_ERROR_THRESHOLD = 5


class AccountService:
    """
    GLaDOS 账号服务。

    所有对 Account 实体字段的写入都在这里，
    其他 Service 不直接修改 Account 字段。
    """

    def __init__(self, account_repository: AccountRepository) -> None:
        self.account_repository = account_repository

    # ================================================================
    # 存在性
    # ================================================================

    def ensure(self, account: GladosAccountConfig) -> Account:
        """
        获取数据库账号，不存在则创建。

        仅 flush，不 commit。事务由门面控制。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 GLaDOS 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(username=account.username)

    # ================================================================
    # 签到成功（already_checked=False）
    # ================================================================

    def apply_checkin_success(
        self,
        db_account: Account,
        *,
        earned_points: int,
        streak: int,
        checkin_local: datetime,
    ) -> None:
        """
        应用"签到成功"结果。

        写入：
            - points += earned_points（累加）
            - streak_days = streak（接口返回，直接赋值）
            - total_days += 1
            - last_checkin_at = checkin_local
            - 重置错误状态（is_valid / error_count / last_error_at）

        Args:
            db_account: 数据库账号对象。
            earned_points: 本次签到获得积分（累加到现有积分）。
            streak: 接口返回的连续签到天数。
            checkin_local: 签到时间（本地时间）。
        """
        checkin_utc = local_to_utc(checkin_local)

        db_account.points += earned_points
        db_account.streak_days = streak
        db_account.total_days += 1
        db_account.last_checkin_at = checkin_utc

        # 重置错误状态
        db_account.is_valid = True
        db_account.error_count = 0
        db_account.last_error_at = None

        self.account_repository.update(db_account)

        logger.info(
            "账号签到成功写入: username=%s, " "积分 +%d = %d, 连续签到=%d, 累计签到=%d",
            db_account.username,
            earned_points,
            db_account.points,
            db_account.streak_days,
            db_account.total_days,
        )

    # ================================================================
    # 远程已签到同步（already_checked=True）
    # ================================================================

    def apply_remote_checkin(
        self,
        db_account: Account,
        *,
        streak: int,
        checkin_local: datetime,
    ) -> None:
        """
        应用"远程已签到"同步结果。

        写入：
            - points 不变
            - streak_days = streak（接口返回，直接赋值）
            - total_days 不变
            - last_checkin_at = checkin_local（保证下次短路）
            - 不重置错误状态

        Args:
            db_account: 数据库账号对象。
            streak: 接口返回的连续签到天数。
            checkin_local: 签到时间（本地时间）。
        """
        checkin_utc = local_to_utc(checkin_local)

        db_account.streak_days = streak
        db_account.last_checkin_at = checkin_utc

        self.account_repository.update(db_account)

        logger.info(
            "账号远程签到同步写入: username=%s, " "连续签到=%d, last_checkin_at=%s",
            db_account.username,
            db_account.streak_days,
            checkin_utc,
        )

    # ================================================================
    # 签到失败
    # ================================================================

    def apply_checkin_failure(
        self,
        db_account: Account,
        error_message: str,
    ) -> bool:
        """
        应用"签到失败"结果。

        写入：
            - error_count += 1
            - last_error_at = now_utc()
            - 若 error_count >= INVALID_ERROR_THRESHOLD，标记 is_valid=False

        Returns:
            是否因本次失败被标记为无效。
        """
        db_account.error_count += 1
        db_account.last_error_at = now_utc()

        marked_invalid = False

        if db_account.error_count >= INVALID_ERROR_THRESHOLD:
            db_account.is_valid = False
            marked_invalid = True

        self.account_repository.update(db_account)

        logger.warning(
            "账号失败状态写入: username=%s, error=%s, "
            "error_count=%d, marked_invalid=%s",
            db_account.username,
            error_message,
            db_account.error_count,
            marked_invalid,
        )

        return marked_invalid

    # ================================================================
    # 积分同步（积分查询）
    # ================================================================

    def update_points(
        self,
        db_account: Account,
        points: float,
    ) -> None:
        """同步账号积分（积分查询用，赋值）。"""
        db_account.points = points
        self.account_repository.update(db_account)

        logger.debug(
            "账号积分更新: username=%s, points=%.2f",
            db_account.username,
            points,
        )

    # ================================================================
    # 有效期同步（状态查询）
    # ================================================================

    def update_left_days(
        self,
        db_account: Account,
        left_days: float,
    ) -> None:
        """同步账号剩余天数（状态查询用，赋值）。"""
        db_account.left_days = left_days
        self.account_repository.update(db_account)

        logger.debug(
            "账号剩余天数更新: username=%s, left_days=%.2f",
            db_account.username,
            left_days,
        )

    # ================================================================
    # 有效期累加（积分兑换）
    # ================================================================

    def add_left_days(
        self,
        db_account: Account,
        days: int,
    ) -> None:
        """累加账号剩余天数（积分兑换用）。"""
        db_account.left_days += days
        self.account_repository.update(db_account)

        logger.info(
            "账号剩余天数累加: username=%s, +%d = %d",
            db_account.username,
            days,
            db_account.left_days,
        )

__all__ = [
    "INVALID_ERROR_THRESHOLD",
    "AccountService",
]
