# apps\hifiti\core\checkin.py

"""
Hifiti 签到服务。

职责：
    - 判断今日是否已签到（DB 记录）
    - 执行签到
    - 处理"远程已签到"分支
    - 产出"签到决策结果"（CheckinOutcome）
    - 写入签到日志（CheckinLog）

不负责：
    - 认证（门面负责，cookies 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Cookie。

异常传播约定：
    HifitiAPIError 一律上抛，由门面处理认证降级。
    本服务不吞 HifitiAPIError，否则门面无法感知"需要重新认证"。
    其他异常（解析异常、代码 bug 等）吞掉并返回失败结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.hifiti.core.api import (
    HifitiAPI,
    HifitiAPIError,
)
from apps.hifiti.core.config import HifitiAccountConfig
from apps.hifiti.core.models import Account
from apps.hifiti.core.parser import (
    HifitiCheckinResult,
    HifitiParser,
)
from apps.hifiti.core.repositories import CheckinLogRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import (
    local_to_utc,
    now_local,
    now_utc,
    utc_to_local,
)

logger = get_logger(
    name="hifiti_checkin",
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
        result: 给调用方的原始 HifitiCheckinResult。
        action: 本次动作类型，取值：
            - "skipped"    : DB 记录显示今日已签到，未发起任何请求
            - "synced"     : 远程已签到，只更新 last_checkin_at
            - "checked_in" : 本次签到成功
            - "failed"     : 签到失败
        checkin_gold: 本次获得金币（写 CheckinLog；synced/failed 时为 0）。
        checkin_rank: 本次排名（写 CheckinLog；synced/failed 时为 0）。
        checkin_local: 签到时间（本地时间，非 None）。
        error_message: 失败时的错误信息。
    """

    result: HifitiCheckinResult
    action: str
    checkin_gold: int = 0
    checkin_rank: int = 0
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
    Hifiti 签到服务。

    持有 api / parser / checkin_log_repository，
    自行发起远程调用、写签到日志；
    不写 Account 字段，不提交事务。
    """

    def __init__(
        self,
        api: HifitiAPI,
        parser: HifitiParser,
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
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        执行签到决策。

        只读 db_account（判断今日是否已签到），不写。

        前提：self.api 已由门面设置好 Cookie。
        """
        logger.info("开始 Hifiti 签到: username=%s", account.username)

        # ------------------------------------------------------------
        # 1. DB 记录显示今日已签到 → 跳过
        # ------------------------------------------------------------

        if self._already_checked_in_db(db_account):
            logger.info(
                "账号 %s 今日已签到（数据库记录），跳过",
                account.username,
            )
            return CheckinOutcome(
                result=HifitiCheckinResult(success=True),
                action="skipped",
            )

        # ------------------------------------------------------------
        # 2. 发起签到
        # ------------------------------------------------------------

        logger.info("账号 %s 开始执行签到", account.username)

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
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        调用 API 执行签到，产出结果 + 写日志。

        异常传播：
            HifitiAPIError 一律上抛（门面处理降级）。
            其他异常吞掉并返回失败结果。
        """
        try:
            response = self.api.checkin()
            result = self.parser.parse_checkin(response)

            # 失败（解析层面或业务 code 非 0/-1）
            if not result.success:
                return self._build_failure_outcome(
                    db_account,
                    result.error or "签到失败",
                    result,
                )

            # 远程已签到 → 只写 CheckinLog，不更新 Account 金币
            if result.already_checked:
                logger.info(
                    "账号 %s 远程已签到，产出同步结果",
                    account.username,
                )
                return self._build_remote_sync_outcome(account, db_account, result)

            # 签到成功
            logger.info(
                "Hifiti 签到成功: username=%s, checkin_gold=%d, rank=%d",
                account.username,
                result.checkin_gold,
                result.rank,
            )

            checkin_local = now_local()
            checkin_utc = local_to_utc(checkin_local)

            self.checkin_log_repository.create(
                account_id=db_account.id,
                success=True,
                checkin_gold=result.checkin_gold,
                checkin_rank=result.rank,
                message=result.message or "签到成功",
                checkin_at=checkin_utc,
            )

            return CheckinOutcome(
                result=result,
                action="checked_in",
                checkin_gold=result.checkin_gold,
                checkin_rank=result.rank,
                checkin_local=checkin_local,
            )

        except HifitiAPIError:
            logger.warning(
                "Hifiti 签到 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception as exc:
            logger.exception(
                "Hifiti 签到异常: username=%s",
                account.username,
            )
            return self._build_failure_outcome(
                db_account,
                str(exc) or "签到异常",
                HifitiCheckinResult.failure("签到异常"),
            )

    # ================================================================
    # 内部：远程已签到 → 同步结果
    # ================================================================

    def _build_remote_sync_outcome(
        self,
        account: HifitiAccountConfig,
        db_account: Account,
        result: HifitiCheckinResult,
    ) -> CheckinOutcome:
        """远程已签到：产出同步结果 + 写日志。"""
        checkin_local = now_local()
        checkin_utc = local_to_utc(checkin_local)

        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=True,
            checkin_gold=0,
            checkin_rank=0,
            message=result.message or "远程已签到（同步状态）",
            checkin_at=checkin_utc,
        )

        return CheckinOutcome(
            result=result,
            action="synced",
            checkin_gold=0,
            checkin_rank=0,
            checkin_local=checkin_local,
        )

    # ================================================================
    # 内部：失败结果
    # ================================================================

    def _build_failure_outcome(
        self,
        db_account: Account,
        error_message: str,
        result: HifitiCheckinResult,
    ) -> CheckinOutcome:
        """产出失败结果 + 写失败日志。"""
        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=False,
            checkin_gold=0,
            checkin_rank=0,
            message=error_message,
            checkin_at=now_utc(),
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
