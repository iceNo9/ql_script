# apps/southpro/core/daily.py

"""
SouthPro 日常任务服务。

职责：
    - 判断日常任务是否达到执行间隔
    - 执行日常任务（申请 + 完成）
    - 产出"日常任务决策结果"（DailyTaskOutcome）
    - 写入日常任务完成日志（DailyCompleteLog）

不负责：
    - 认证（门面负责，cookie 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）
    - 周常任务（WeeklyTaskService 负责）
    - 报告构建（ReportService 负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Cookie。

异常传播约定：
    SouthProAPIError 一律上抛，由门面处理认证降级。
    其他异常吞掉并返回失败结果。

Result.success 语义：
    仅表示"响应解析成功"，不代表业务操作成功。
    业务成功另用 applied / completed。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.southpro.core.api import (
    SouthProAPI,
    SouthProAPIError,
)
from apps.southpro.core.config import SouthProAccountConfig
from apps.southpro.core.models import Account
from apps.southpro.core.notify_dto import DailyTaskInfo
from apps.southpro.core.parser import (
    SouthProDailyCompleteResult,
    SouthProParser,
)
from apps.southpro.core.repositories import DailyCompleteLogRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_local, now_utc, utc_to_local

logger = get_logger(
    name="southpro_daily",
    log_dir=logs(),
    fmt_type="detailed",
)

# 日常任务执行间隔：18 小时
DAILY_INTERVAL = timedelta(hours=18)


# ================================================================
# 决策结果 DTO
# ================================================================


@dataclass
class DailyTaskOutcome:
    """
    日常任务决策结果。

    携带"发生了什么"和"应该写什么"，
    供门面交给 AccountService 落库。

    字段说明：
        result: 给调用方的原始 SouthProDailyCompleteResult。
        action: 本次动作类型，取值：
            - "skipped"     : 未达到执行间隔，跳过
            - "apply_failed": 申请业务失败（不累加 error）
            - "checked_in"  : 完成成功（写 SP + 计数 + 时间）
            - "failed"      : 解析失败 / 完成失败 / 异常
        delta_points_sp: 本次获得 SP。
        complete_at: 完成时间（UTC）。
        error_message: 失败时的错误信息。
    """

    result: SouthProDailyCompleteResult
    action: str
    delta_points_sp: int = 0
    complete_at: datetime | None = None
    error_message: str | None = None

    @property
    def should_update_account(self) -> bool:
        """是否需要 AccountService 写 Account 表（成功）。"""
        return self.action == "checked_in"

    @property
    def is_failure(self) -> bool:
        """是否需要 AccountService 累加错误。"""
        return self.action == "failed"


# ================================================================
# DailyTaskService
# ================================================================


class DailyTaskService:
    """
    SouthPro 日常任务服务。

    持有 api / parser / daily_complete_log_repository，
    自行发起远程调用、写日常日志；
    不写 Account 字段，不提交事务。
    """

    DAILY_INTERVAL = DAILY_INTERVAL

    def __init__(
        self,
        api: SouthProAPI,
        parser: SouthProParser,
        daily_complete_log_repository: DailyCompleteLogRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.daily_complete_log_repository = daily_complete_log_repository

    # ================================================================
    # 间隔判断
    # ================================================================

    def is_due(self, db_account: Account) -> bool:
        """判断当前账号是否达到日常任务执行间隔。"""
        if db_account.last_daily_complete_at is None:
            return True

        last_local = utc_to_local(db_account.last_daily_complete_at)
        elapsed = now_local() - last_local
        return elapsed >= self.DAILY_INTERVAL

    def next_complete_at(self, db_account: Account) -> datetime | None:
        """计算下次可完成时间（本地时间）。"""
        if db_account.last_daily_complete_at is None:
            return None

        last_local = utc_to_local(db_account.last_daily_complete_at)
        return last_local + self.DAILY_INTERVAL

    # ================================================================
    # 报告信息构造
    # ================================================================

    def build_report_infos(
        self,
        account_configs: list[SouthProAccountConfig],
        *,
        account_repository,
    ) -> list[DailyTaskInfo]:
        """
        构造 DailyTaskInfo 列表（供 ReportService 使用）。

        只读：找不到账号的跳过。

        Args:
            account_configs: 账号配置列表。
            account_repository: 门面注入的 AccountRepository。

        Returns:
            DailyTaskInfo 列表。
        """
        infos: list[DailyTaskInfo] = []

        for config in account_configs:
            db_account = account_repository.get_by_username(config.username)

            if db_account is None:
                continue

            last_local = (
                utc_to_local(db_account.last_daily_complete_at)
                if db_account.last_daily_complete_at is not None
                else None
            )

            next_local = (
                last_local + self.DAILY_INTERVAL if last_local is not None else None
            )

            infos.append(
                DailyTaskInfo(
                    username=db_account.username,
                    complete_count=db_account.daily_complete_count,
                    last_complete_at=last_local,
                    next_complete_at=next_local,
                )
            )

        return infos

    # ================================================================
    # 执行日常任务
    # ================================================================

    def complete(
        self,
        account: SouthProAccountConfig,
        db_account: Account,
    ) -> DailyTaskOutcome:
        """
        执行日常任务决策。

        只读 db_account（判断间隔），不写。

        前提：self.api 已由门面设置好 Cookie。
        """
        logger.info(
            "开始 SouthPro 日常任务: username=%s",
            account.username,
        )

        # ------------------------------------------------------------
        # 1. 未达到执行间隔 → 跳过
        # ------------------------------------------------------------

        if not self.is_due(db_account):
            logger.info(
                "账号 %s 日常任务未达到执行间隔，跳过",
                account.username,
            )
            return DailyTaskOutcome(
                result=SouthProDailyCompleteResult(
                    success=True,
                    completed=False,
                    delta_points_sp=0,
                ),
                action="skipped",
            )

        # ------------------------------------------------------------
        # 2. 申请 + 完成
        # ------------------------------------------------------------

        return self._do_complete(account, db_account)

    # ================================================================
    # 内部：申请 + 完成
    # ================================================================

    def _do_complete(
        self,
        account: SouthProAccountConfig,
        db_account: Account,
    ) -> DailyTaskOutcome:
        """
        调用 API 执行日常任务（申请 + 完成），产出结果 + 写日志。

        异常传播：
            SouthProAPIError 一律上抛（门面处理降级）。
            其他异常吞掉并返回失败结果。
        """
        try:
            # --------------------------------------------------------
            # 申请日常任务
            # --------------------------------------------------------

            response = self.api.apply_daily()
            apply_result = self.parser.parse_apply_daily(response)

            # 响应解析失败
            if not apply_result.success:
                error = apply_result.error or "日常任务申请响应解析失败"
                return self._build_failure_outcome(
                    db_account,
                    error,
                    SouthProDailyCompleteResult.failure(error),
                )

            # 申请业务失败（不累加 error）
            if not apply_result.applied:
                error = apply_result.error or "日常任务申请失败"
                logger.warning(
                    "账号 %s 日常任务申请失败: %s",
                    account.username,
                    error,
                )
                return DailyTaskOutcome(
                    result=SouthProDailyCompleteResult(
                        success=True,
                        completed=False,
                        delta_points_sp=0,
                        error=error,
                    ),
                    action="apply_failed",
                    error_message=error,
                )

            # --------------------------------------------------------
            # 完成日常任务
            # --------------------------------------------------------

            response = self.api.complete_daily()
            complete_result = self.parser.parse_complete_daily(response)

            # 响应解析失败
            if not complete_result.success:
                error = complete_result.error or "日常任务完成响应解析失败"
                return self._build_failure_outcome(
                    db_account,
                    error,
                    SouthProDailyCompleteResult.failure(error),
                )

            # 完成业务失败
            if not complete_result.completed:
                error = complete_result.error or "日常任务完成失败"
                return self._build_failure_outcome(
                    db_account,
                    error,
                    complete_result,
                )

            # --------------------------------------------------------
            # 完成成功
            # --------------------------------------------------------

            complete_at = now_utc()

            logger.info(
                "SouthPro 日常任务完成: username=%s, delta_points_sp=%d",
                account.username,
                complete_result.delta_points_sp,
            )

            self.daily_complete_log_repository.create(
                account_id=db_account.id,
                success=True,
                delta_points_sp=complete_result.delta_points_sp,
                message="日常任务完成成功",
                complete_at=complete_at,
            )

            return DailyTaskOutcome(
                result=complete_result,
                action="checked_in",
                delta_points_sp=complete_result.delta_points_sp,
                complete_at=complete_at,
            )

        except SouthProAPIError:
            logger.warning(
                "日常任务 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception as exc:
            logger.exception(
                "SouthPro 日常任务异常: username=%s",
                account.username,
            )
            return self._build_failure_outcome(
                db_account,
                str(exc) or "日常任务异常",
                SouthProDailyCompleteResult.failure("日常任务异常"),
            )

    # ================================================================
    # 内部：失败结果
    # ================================================================

    def _build_failure_outcome(
        self,
        db_account: Account,
        error_message: str,
        result: SouthProDailyCompleteResult,
    ) -> DailyTaskOutcome:
        """产出失败结果 + 写失败日志。"""
        self.daily_complete_log_repository.create(
            account_id=db_account.id,
            success=False,
            delta_points_sp=0,
            message=error_message,
            complete_at=now_utc(),
        )

        return DailyTaskOutcome(
            result=result,
            action="failed",
            error_message=error_message,
        )


__all__ = [
    "DAILY_INTERVAL",
    "DailyTaskOutcome",
    "DailyTaskService",
]
