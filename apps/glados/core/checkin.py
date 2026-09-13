# apps\glados\core\checkin.py

"""
GLaDOS 签到服务。

职责：
    - 判断今日是否已签到（DB 记录）
    - 执行签到
    - 处理"远程已签到"分支
    - 产出"签到决策结果"（CheckinOutcome）
    - 写入签到日志（CheckinLog）

不负责：
    - 认证（门面负责，cookie 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Cookie。

异常传播约定：
    GladosAPIError 一律上抛，由门面处理认证降级。
    本服务不吞 GladosAPIError。
    其他异常（解析异常、代码 bug 等）吞掉并返回失败结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.glados.core.api import (
    GladosAPI,
    GladosAPIError,
)
from apps.glados.core.config import GladosAccountConfig
from apps.glados.core.models import Account
from apps.glados.core.parser import (
    GladosCheckinResult,
    GladosParser,
)
from apps.glados.core.repositories import CheckinLogRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_local, utc_to_local

logger = get_logger(
    name="glados_checkin",
    log_dir=logs(),
    fmt_type="detailed",
)


# ================================================================
# 决策结果 DTO
# ================================================================


@dataclass
class CheckinOutcome:
    """
    签到决策结果。

    携带"发生了什么"和"应该写什么"，
    供门面交给 AccountService 落库。

    字段说明：
        result: 给调用方的原始 GladosCheckinResult。
        action: 本次动作类型，取值：
            - "skipped"    : DB 记录显示今日已签到，未发起任何请求
            - "synced"     : 远程已签到，补录 last_checkin_at
            - "checked_in" : 本次签到成功
            - "failed"     : 签到失败
        earned_points: 本次签到获得积分（写 CheckinLog）。
        points: 接口返回的总积分（仅参考，不用于写入）。
        streak: 接口返回的连续签到天数。
        checkin_local: 签到时间（本地时间）。
        error_message: 失败时的错误信息。
    """

    result: GladosCheckinResult
    action: str
    earned_points: int = 0
    points: int = 0
    streak: int = 0
    checkin_local: datetime | None = None
    error_message: str | None = None

    @property
    def should_update_account(self) -> bool:
        """是否需要 AccountService 写 Account 表。"""
        return self.action in ("synced", "checked_in")

    @property
    def is_failure(self) -> bool:
        """是否失败。"""
        return self.action == "failed"


# ================================================================
# CheckinService
# ================================================================


class CheckinService:
    """
    GLaDOS 签到服务。

    持有 api / parser / checkin_log_repository，
    自行发起远程调用、写签到日志；
    不写 Account 字段，不提交事务。
    """

    def __init__(
        self,
        api: GladosAPI,
        parser: GladosParser,
        checkin_log_repository: CheckinLogRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.checkin_log_repository = checkin_log_repository

    # ================================================================
    # Checkin
    # ================================================================

    def checkin(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        执行签到决策。

        只读 db_account（判断今日是否已签到），不写。

        前提：self.api 已由门面设置好 Cookie。
        """
        logger.info("开始 GLaDOS 签到: username=%s", account.username)

        # ------------------------------------------------------------
        # 1. DB 记录显示今日已签到 → 跳过
        # ------------------------------------------------------------

        if self._already_checked_in_db(db_account):
            logger.info(
                "账号 %s 今日已签到（数据库记录），跳过",
                account.username,
            )
            return CheckinOutcome(
                result=GladosCheckinResult(success=True),
                action="skipped",
            )

        # ------------------------------------------------------------
        # 2. 发起签到
        # ------------------------------------------------------------

        return self._do_checkin(account, db_account)

    # ================================================================
    # 内部：DB 状态判断
    # ================================================================

    @staticmethod
    def _already_checked_in_db(db_account: Account) -> bool:
        """判断数据库中是否显示今日已签到。"""
        if db_account.last_checkin_at is None:
            return False

        today_local = now_local()
        last_checkin_local = utc_to_local(db_account.last_checkin_at)
        return last_checkin_local.date() == today_local.date()

    # ================================================================
    # 内部：发起签到
    # ================================================================

    def _do_checkin(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        调用 API 执行签到，产出结果 + 写日志。

        异常传播：
            GladosAPIError 一律上抛（门面处理降级）。
            其他异常吞掉并返回失败结果。
        """
        try:
            response = self.api.checkin()
            result = self.parser.parse_checkin(response)

            # 失败（解析层面或业务 code 异常）
            if not result.success:
                return self._build_failure_outcome(
                    db_account,
                    result.error or "签到失败",
                    result,
                )

            checkin_local = now_local()

            # 远程已签到 → synced
            if result.already_checked:
                logger.info(
                    "GLaDOS 今日已签到（同步数据）: username=%s, "
                    "points=%d, streak=%d",
                    account.username,
                    result.points,
                    result.streak,
                )

                # CheckinLog.points 写 0（保持原行为：already_checked 不记积分）
                self.checkin_log_repository.create(
                    account_id=db_account.id,
                    success=True,
                    points=0,
                    message=result.message or "远程已签到（同步状态）",
                )

                return CheckinOutcome(
                    result=result,
                    action="synced",
                    earned_points=0,
                    points=result.points,
                    streak=result.streak,
                    checkin_local=checkin_local,
                )

            # 正常签到成功 → checked_in
            logger.info(
                "GLaDOS 签到成功: username=%s, points=%d, streak=%d",
                account.username,
                result.points,
                result.streak,
            )

            self.checkin_log_repository.create(
                account_id=db_account.id,
                success=True,
                points=result.points,
                message=result.message or "签到成功",
            )

            return CheckinOutcome(
                result=result,
                action="checked_in",
                earned_points=result.points,
                points=result.points,
                streak=result.streak,
                checkin_local=checkin_local,
            )

        except GladosAPIError:
            logger.warning(
                "GLaDOS 签到 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception as exc:
            logger.exception(
                "GLaDOS 签到异常: username=%s",
                account.username,
            )
            return self._build_failure_outcome(
                db_account,
                str(exc) or "签到异常",
                GladosCheckinResult.failure("签到异常"),
            )

    # ================================================================
    # 内部：失败结果
    # ================================================================

    def _build_failure_outcome(
        self,
        db_account: Account,
        error_message: str,
        result: GladosCheckinResult,
    ) -> CheckinOutcome:
        """产出失败结果 + 写失败日志。"""
        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=False,
            points=0,
            message=error_message,
        )

        return CheckinOutcome(
            result=result,
            action="failed",
            error_message=error_message,
        )


__all__ = [
    "CheckinOutcome",
    "CheckinService",
]
