# apps\baiyefee\core\checkin.py

"""
Baiyefee 签到服务。

职责：
    - 查询远程签到状态
    - 判断今日是否已签到
    - 决定是否发起签到
    - 产出"签到决策结果"（CheckinOutcome）
    - 写入签到日志（CheckinLog）

不负责：
    - 认证（门面负责，token 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Token。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.baiyefee.core.api import (
    BaiyefeeAPI,
    BaiyefeeAPIError,
)
from apps.baiyefee.core.config import BaiyefeeAccountConfig
from apps.baiyefee.core.models import Account
from apps.baiyefee.core.parser import (
    BaiyefeeCheckinResult,
    BaiyefeeParser,
    BaiyefeeSignInfoResult,
)
from apps.baiyefee.core.repositories import CheckinLogRepository
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import (
    local_to_utc,
    now_local,
    now_utc,
    parse_local_datetime,
    utc_to_local,
)

logger = get_logger(
    name="baiyefee_checkin",
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
        result: 给调用方的原始 BaiyefeeCheckinResult。
        action: 本次动作类型，取值：
            - "skipped"        : DB 记录显示今日已签到，未发起任何请求
            - "synced"         : 远程已签到，补录数据
            - "checked_in"     : 本次签到成功
            - "already"        : 服务端返回"今日已签到"
            - "failed"         : 签到失败
        checkin_points: 本次获得积分（仅日志用）。
        total_points: 签到后的总积分（<=0 表示不更新）。
        checkin_local: 签到时间（本地时间，非 None）。
        error_message: 失败时的错误信息。
    """

    result: BaiyefeeCheckinResult
    action: str
    checkin_points: int = 0
    total_points: int = 0
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
    Baiyefee 签到服务。

    持有 api / parser / checkin_log_repository，
    自行发起远程调用、写签到日志；
    不写 Account 字段，不提交事务。
    """

    def __init__(
        self,
        api: BaiyefeeAPI,
        parser: BaiyefeeParser,
        checkin_log_repository: CheckinLogRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.checkin_log_repository = checkin_log_repository

    # ================================================================
    # Sign Info
    # ================================================================

    def get_sign_info(
        self,
        account: BaiyefeeAccountConfig,
    ) -> BaiyefeeSignInfoResult | None:
        """
        查询当前账号的远程签到信息。

        前提：self.api 已由门面设置好 Token。

        异常传播：
            BaiyefeeAPIError 一律上抛，由门面处理认证降级。
            其他异常吞掉并返回 None。
        """
        logger.info(
            "获取 Baiyefee 签到信息: username=%s",
            account.username,
        )

        try:
            response = self.api.get_sign_info()
            result = self.parser.parse_sign_info(response)

            if not result.success:
                logger.warning(
                    "获取 Baiyefee 签到信息失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 Baiyefee 签到信息成功: username=%s, "
                "can_checkin=%s, checkin_points=%d, points=%d",
                account.username,
                result.can_checkin,
                result.checkin_points,
                result.points,
            )

            return result

        except BaiyefeeAPIError:
            # ★ 认证相关异常上抛，由门面降级。
            logger.warning(
                "获取签到信息 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception:
            logger.exception(
                "获取 Baiyefee 签到信息异常: username=%s",
                account.username,
            )
            return None

    # ================================================================
    # Checkin
    # ================================================================

    def checkin(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        执行签到决策。

        只读 db_account（判断今日是否已签到），不写。

        前提：self.api 已由门面设置好 Token。
        """
        logger.info("开始 Baiyefee 签到: username=%s", account.username)

        # ------------------------------------------------------------
        # 1. DB 记录显示今日已签到 → 跳过
        # ------------------------------------------------------------

        if self._already_checked_in_db(db_account):
            logger.info(
                "账号 %s 今日已签到（数据库记录），跳过",
                account.username,
            )
            return CheckinOutcome(
                result=BaiyefeeCheckinResult(success=True),
                action="skipped",
            )

        # ------------------------------------------------------------
        # 2. 查询远程签到状态
        # ------------------------------------------------------------

        sign_info = self.get_sign_info(account)

        # ------------------------------------------------------------
        # 3. 远程已签到 → 产出同步结果
        # ------------------------------------------------------------

        if sign_info is not None and not sign_info.can_checkin:
            logger.info(
                "账号 %s 远程已签到，产出同步结果",
                account.username,
            )
            return self._build_remote_sync_outcome(account, db_account, sign_info)

        # ------------------------------------------------------------
        # 4. 发起签到
        # ------------------------------------------------------------

        logger.info(
            "账号 %s 远程可签到，开始执行签到",
            account.username,
        )

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
    # 内部：远程已签到 → 同步结果
    # ================================================================

    def _build_remote_sync_outcome(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
        sign_info: BaiyefeeSignInfoResult,
    ) -> CheckinOutcome:
        """远程已签到：产出同步结果 + 写日志。"""
        checkin_local = self._resolve_checkin_local(
            sign_info.local_date,
            account.username,
        )
        checkin_utc = local_to_utc(checkin_local)

        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=True,
            checkin_points=sign_info.checkin_points,
            message="远程已签到（同步数据）",
            checkin_at=checkin_utc,
        )

        return CheckinOutcome(
            result=BaiyefeeCheckinResult(success=True),
            action="synced",
            checkin_points=sign_info.checkin_points,
            total_points=sign_info.points,
            checkin_local=checkin_local,
        )

    # ================================================================
    # 内部：发起签到
    # ================================================================

    def _do_checkin(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> CheckinOutcome:
        """
        调用 API 执行签到，产出结果 + 写日志。

        异常传播：
            BaiyefeeAPIError 一律上抛，由门面处理认证降级。
            不在此处吞掉，否则门面无法感知"需要重新认证"。

            其他异常（非 BaiyefeeAPIError）仍然吞掉并记为失败。
        """
        try:
            response = self.api.checkin()
            result = self.parser.parse_checkin(response)

            # 失败（解析层面）
            if not result.success:
                return self._build_failure_outcome(
                    db_account,
                    result.error or "签到失败",
                    result,
                )

            # 服务端返回"今日已签到"
            if result.already_checked:
                logger.info(
                    "账号 %s 服务端确认今日已签到，不重复累加天数",
                    account.username,
                )
                return CheckinOutcome(
                    result=result,
                    action="already",
                )

            # 正常签到成功
            logger.info(
                "Baiyefee 签到成功: username=%s, " "checkin_points=%d, points=%d",
                account.username,
                result.checkin_points,
                result.points,
            )

            checkin_local = self._resolve_checkin_local(
                result.local_date,
                account.username,
            )
            checkin_utc = local_to_utc(checkin_local)

            self.checkin_log_repository.create(
                account_id=db_account.id,
                success=True,
                checkin_points=result.checkin_points,
                message="签到成功",
                checkin_at=checkin_utc,
            )

            return CheckinOutcome(
                result=result,
                action="checked_in",
                checkin_points=result.checkin_points,
                total_points=result.points,
                checkin_local=checkin_local,
            )

        except BaiyefeeAPIError:
            # ★ 认证相关异常一律上抛，由门面降级重认证。
            #   不在此处记失败、不累加 error_count。
            logger.warning(
                "Baiyefee 签到 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception as exc:
            # 非 API 异常（解析异常、代码 bug 等）仍记为失败。
            logger.exception(
                "Baiyefee 签到异常: username=%s",
                account.username,
            )
            return self._build_failure_outcome(
                db_account,
                str(exc) or "签到异常",
                BaiyefeeCheckinResult.failure("签到异常"),
            )

    # ================================================================
    # 内部：失败结果
    # ================================================================

    def _build_failure_outcome(
        self,
        db_account: Account,
        error_message: str,
        result: BaiyefeeCheckinResult,
    ) -> CheckinOutcome:
        """产出失败结果 + 写失败日志。"""
        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=False,
            checkin_points=0,
            message=error_message,
            checkin_at=now_utc(),
        )

        return CheckinOutcome(
            result=result,
            action="failed",
            error_message=error_message,
        )

    # ================================================================
    # 内部：时间兜底
    # ================================================================

    @staticmethod
    def _resolve_checkin_local(
        local_date: str,
        username: str,
    ) -> datetime:
        """
        解析签到时间，为空或格式错误时用当前本地时间兜底。

        保证返回非 None，AccountService 可假定输入合法。
        """
        checkin_local = parse_local_datetime(local_date)

        if checkin_local is None:
            logger.warning(
                "签到时间缺失，使用当前本地时间兜底: username=%s, raw=%r",
                username,
                local_date,
            )
            checkin_local = now_local()

        return checkin_local


__all__ = [
    "CheckinOutcome",
    "CheckinService",
]
