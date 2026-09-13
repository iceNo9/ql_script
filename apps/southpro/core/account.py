# apps/southpro/core/account.py

"""
SouthPro 账号服务。

职责：
    - 确保数据库中存在账号行。
    - 所有对 Account 实体字段的写入（SP / 任务状态 / 状态标记）。

不负责：
    - 认证（AuthService）
    - 任务业务决策与日志（DailyTaskService / WeeklyTaskService）
    - 事务提交（门面负责）
    - 报告构建（ReportService）
"""

from __future__ import annotations

from datetime import datetime

from apps.southpro.core.config import SouthProAccountConfig
from apps.southpro.core.models import Account
from apps.southpro.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_utc

logger = get_logger(
    name="southpro_account",
    log_dir=logs(),
    fmt_type="detailed",
)

# 连续失败多少次后标记账号无效
INVALID_ERROR_THRESHOLD = 5


class AccountService:
    """
    SouthPro 账号服务。

    所有对 Account 实体字段的写入都在这里，
    其他 Service 不直接修改 Account 字段。
    """

    def __init__(self, account_repository: AccountRepository) -> None:
        self.account_repository = account_repository

    # ================================================================
    # 存在性
    # ================================================================

    def ensure(self, account: SouthProAccountConfig) -> Account:
        """
        获取数据库账号，不存在则创建。

        仅 flush，不 commit。事务由门面控制。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 SouthPro 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(username=account.username)

    # ================================================================
    # SP 同步（Profile 查询）
    # ================================================================

    def update_points_sp(
        self,
        db_account: Account,
        points_sp: int,
    ) -> None:
        """同步账号 SP（赋值）。"""
        db_account.points_sp = points_sp
        self.account_repository.update(db_account)

        logger.debug(
            "账号 SP 更新: username=%s, points_sp=%d",
            db_account.username,
            points_sp,
        )

    # ================================================================
    # 日常任务成功
    # ================================================================

    def apply_daily_success(
        self,
        db_account: Account,
        *,
        delta_points_sp: int,
        complete_at: datetime,
    ) -> None:
        """
        应用"日常任务成功"结果。

        写入：
            - points_sp += delta_points_sp（累加）
            - daily_complete_count += 1
            - last_daily_complete_at = complete_at
            - 重置错误状态（is_valid / error_count / last_error_at）

        Args:
            db_account: 数据库账号对象。
            delta_points_sp: 本次获得的 SP（累加）。
            complete_at: 完成时间（UTC）。
        """
        db_account.points_sp += delta_points_sp
        db_account.daily_complete_count += 1
        db_account.last_daily_complete_at = complete_at

        # 重置错误状态
        db_account.is_valid = True
        db_account.error_count = 0
        db_account.last_error_at = None

        self.account_repository.update(db_account)

        logger.info(
            "账号日常任务成功写入: username=%s, " "SP +%d = %d, 累计完成=%d",
            db_account.username,
            delta_points_sp,
            db_account.points_sp,
            db_account.daily_complete_count,
        )

    # ================================================================
    # 周常任务成功
    # ================================================================

    def apply_weekly_success(
        self,
        db_account: Account,
        *,
        delta_points_sp: int,
        complete_at: datetime,
    ) -> None:
        """
        应用"周常任务成功"结果。

        写入：
            - points_sp += delta_points_sp（累加）
            - weekly_complete_count += 1
            - last_weekly_complete_at = complete_at
            - 重置错误状态（is_valid / error_count / last_error_at）
        """
        db_account.points_sp += delta_points_sp
        db_account.weekly_complete_count += 1
        db_account.last_weekly_complete_at = complete_at

        # 重置错误状态
        db_account.is_valid = True
        db_account.error_count = 0
        db_account.last_error_at = None

        self.account_repository.update(db_account)

        logger.info(
            "账号周常任务成功写入: username=%s, " "SP +%d = %d, 累计完成=%d",
            db_account.username,
            delta_points_sp,
            db_account.points_sp,
            db_account.weekly_complete_count,
        )

    # ================================================================
    # 任务失败（日常 / 周常共用）
    # ================================================================

    def apply_task_failure(
        self,
        db_account: Account,
        error_message: str,
    ) -> bool:
        """
        应用"任务失败"结果（日常 / 周常共用）。

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
            "账号任务失败写入: username=%s, error=%s, "
            "error_count=%d, marked_invalid=%s",
            db_account.username,
            error_message,
            db_account.error_count,
            marked_invalid,
        )

        return marked_invalid


__all__ = [
    "INVALID_ERROR_THRESHOLD",
    "AccountService",
]
