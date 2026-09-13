# apps\baiyefee\core\account.py

"""
Baiyefee 账号服务。

职责：
    - 确保数据库中存在账号行。
    - 所有对 Account 实体字段的写入（积分 / 签到数据 / 状态标记）。

不负责：
    - 认证（AuthService）
    - 签到业务决策与日志（CheckinService）
    - 事务提交（门面负责）
    - 报告构建（ReportService）
"""

from __future__ import annotations

from datetime import datetime

from apps.baiyefee.core.config import BaiyefeeAccountConfig
from apps.baiyefee.core.models import Account
from apps.baiyefee.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import local_to_utc, now_utc, utc_to_local

logger = get_logger(
    name="baiyefee_account",
    log_dir=logs(),
    fmt_type="detailed",
)

# 连续失败多少次后标记账号无效
INVALID_ERROR_THRESHOLD = 5


class AccountService:
    """
    Baiyefee 账号服务。

    所有对 Account 实体字段的写入都在这里，
    其他 Service 不直接修改 Account 字段。
    """

    def __init__(self, account_repository: AccountRepository) -> None:
        self.account_repository = account_repository

    # ================================================================
    # 存在性
    # ================================================================

    def ensure(self, account: BaiyefeeAccountConfig) -> Account:
        """
        获取数据库账号，不存在则创建。

        仅 flush，不 commit。事务由门面控制。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 Baiyefee 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(username=account.username)

    # ================================================================
    # 积分同步（用户数据）
    # ================================================================

    def update_points(
        self,
        db_account: Account,
        points: int,
    ) -> None:
        """同步账号积分（用户数据查询用）。"""
        db_account.points = points
        self.account_repository.update(db_account)

        logger.debug(
            "账号积分更新: username=%s, points=%d",
            db_account.username,
            points,
        )

    # ================================================================
    # 签到成功
    # ================================================================

    def apply_checkin_success(
        self,
        db_account: Account,
        *,
        total_points: int,
        checkin_local: datetime,
    ) -> None:
        """
        应用"签到成功"结果。

        写入：
            - 积分（total_points > 0 时）
            - 连续签到天数
            - 累计签到天数
            - 最后签到时间
            - 重置错误状态（is_valid / error_count / last_error_at）

        Args:
            db_account: 数据库账号对象。
            total_points: 当前总积分（<=0 时不更新）。
            checkin_local: 签到时间（本地时间，调用方保证非 None）。
        """
        checkin_utc = local_to_utc(checkin_local)

        # 积分
        if total_points > 0:
            db_account.points = total_points

        # 连续签到天数
        db_account.streak_days = self._next_streak_days(
            db_account,
            checkin_local,
        )

        db_account.total_days += 1
        db_account.last_checkin_at = checkin_utc

        # 重置错误状态
        db_account.is_valid = True
        db_account.error_count = 0
        db_account.last_error_at = None

        self.account_repository.update(db_account)

        logger.info(
            "账号签到数据写入: username=%s, "
            "连续签到=%d, 累计签到=%d, 总积分=%d",
            db_account.username,
            db_account.streak_days,
            db_account.total_days,
            db_account.points,
        )

    # ================================================================
    # 远程已签到同步
    # ================================================================

    def apply_remote_checkin(
        self,
        db_account: Account,
        *,
        total_points: int,
        checkin_local: datetime,
    ) -> None:
        """
        应用"远程已签到"同步结果。

        与 apply_checkin_success 的差异：
            不重置错误状态（本次未真正发起签到，只是补录远程状态）。

        Args:
            db_account: 数据库账号对象。
            total_points: 当前总积分（<=0 时不更新）。
            checkin_local: 远程记录的签到时间（本地时间，非 None）。
        """
        checkin_utc = local_to_utc(checkin_local)

        if total_points > 0:
            db_account.points = total_points

        db_account.streak_days = self._next_streak_days(
            db_account,
            checkin_local,
        )

        db_account.total_days += 1
        db_account.last_checkin_at = checkin_utc

        self.account_repository.update(db_account)

        logger.info(
            "账号远程签到同步写入: username=%s, "
            "连续签到=%d, 累计签到=%d, 总积分=%d",
            db_account.username,
            db_account.streak_days,
            db_account.total_days,
            db_account.points,
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

        Args:
            db_account: 数据库账号对象。
            error_message: 错误信息（仅用于日志）。

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
    # 内部：连续签到天数计算
    # ================================================================

    @staticmethod
    def _next_streak_days(
        db_account: Account,
        checkin_local: datetime,
    ) -> int:
        """
        计算新的连续签到天数。

        规则：
            - 首次签到：1
            - 与上次签到日期相差 <= 1 天：原值 + 1
            - 否则：重置为 1
        """
        if db_account.last_checkin_at is None:
            return 1

        last_checkin_local = utc_to_local(db_account.last_checkin_at)
        day_diff = (checkin_local.date() - last_checkin_local.date()).days

        if day_diff <= 1:
            return db_account.streak_days + 1

        return 1


__all__ = [
    "INVALID_ERROR_THRESHOLD",
    "AccountService",
]