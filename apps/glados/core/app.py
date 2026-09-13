# apps\glados\core\app.py

"""
GLaDOS 应用门面。

职责：
    - 装配资源（Session / API / Parser / Repository / Service / EmailTool 缓存）
    - 账号定位（username → 配置 → 数据库行）
    - 认证与 Cookie 注入
    - 事务边界
    - 单账号 / 批量执行模板
    - 编排：CheckinService / UserService 决策 → AccountService 落库
    - 按规则续费编排（exchange_points_by_rule / exchange_all_by_rules）

不负责：
    - 任何业务细节
    - 任何字段写入
    - HTTP / 解析 / 持久化

认证降级策略：
    任何 GladosAPIError 都视为"可能需要重新认证"，
    触发认证来源降级（最多 3 次）。
"""

from collections.abc import Callable
from typing import TypeVar

from apps.glados.core.account import AccountService
from apps.glados.core.api import GladosAPI, GladosAPIError
from apps.glados.core.auth import AuthService, AuthSource
from apps.glados.core.checkin import CheckinOutcome, CheckinService
from apps.glados.core.config import GladosAccountConfig, GladosConfig
from apps.glados.core.models import Account
from apps.glados.core.parser import (
    GladosCheckinResult,
    GladosExchangeResult,
    GladosParser,
    GladosPointsResult,
    GladosStatusResult,
)
from apps.glados.core.report import ReportService
from apps.glados.core.repositories import (
    AccountRepository,
    CheckinLogRepository,
    TrafficHistoryRepository,
)
from apps.glados.core.user import UserService
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.log import get_logger
from utils.paths import logs
from utils.request_client import RequestClient

logger = get_logger(
    name="glados_app",
    log_dir=logs(),
    fmt_type="detailed",
)

T = TypeVar("T")

# 认证来源数量，决定降级重试的最大次数
_MAX_AUTH_ATTEMPTS = 3

# 积分兑换计划 -> 所需积分
_PLAN_POINTS_MAP = {
    "plan500": 500,
    "plan200": 200,
    "plan100": 100,
}

# 有效的兑换计划
_VALID_PLANS = frozenset(_PLAN_POINTS_MAP.keys())


class GladosApp:
    """GLaDOS 应用门面。"""

    def __init__(
        self,
        global_config: GlobalConfig,
        glados_config: GladosConfig,
    ) -> None:
        self.global_config = global_config
        self.glados_config = glados_config

        # 基础资源
        self.session = get_session()
        self.crypto = Crypto(glados_config.encryption_key)

        # HTTP
        proxy = global_config.proxy
        self.request_client = RequestClient(
            http_proxies=proxy.http if proxy.enabled else [],
            https_proxies=proxy.https if proxy.enabled else [],
            no_proxy=proxy.no_proxy if proxy.enabled else [],
        )

        # API / Parser
        self.api = GladosAPI(self.request_client)
        self.parser = GladosParser()

        # Repository
        self.account_repository = AccountRepository(self.session, self.crypto)
        self.checkin_log_repository = CheckinLogRepository(self.session)
        self.traffic_history_repository = TrafficHistoryRepository(self.session)

        # Service
        self.account_service = AccountService(self.account_repository)
        self.auth_service = AuthService(
            self.api,
            self.parser,
            self.account_repository,
        )
        self.checkin_service = CheckinService(
            self.api,
            self.parser,
            self.checkin_log_repository,
        )
        self.user_service = UserService(
            self.api,
            self.parser,
            self.traffic_history_repository,
        )
        self.report_service = ReportService(
            self.account_repository,
            self.checkin_log_repository,
            self.traffic_history_repository,
        )

    # ================================================================
    # 生命周期
    # ================================================================

    def close(self) -> None:
        """关闭数据库 Session。"""
        self.session.close()

    # ================================================================
    # 内部：账号定位
    # ================================================================

    def _resolve_account(
        self,
        username: str,
    ) -> GladosAccountConfig | None:
        """从配置中按用户名定位账号配置。"""
        account = next(
            (
                account
                for account in self.glados_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error("未找到 GLaDOS 账号: username=%s", username)

        return account

    # ================================================================
    # 内部：认证 + 执行（含降级）
    # ================================================================

    def _authenticate_and_run(
        self,
        account: GladosAccountConfig,
        action: Callable[[], T],
    ) -> T:
        """
        认证并执行 action，遇到 GladosAPIError 时降级重试。

        降级逻辑：
            1. authenticate 返回 (cookies, source)
            2. set_cookies，执行 action
            3. 若抛 GladosAPIError：
               把 source 加入 skip_sources，重新认证
            4. 最多尝试 _MAX_AUTH_ATTEMPTS 次

        注意：
            本方法不区分 HTTP 错误类型。
            任何 GladosAPIError 都视为"可能需要重新认证"。
        """
        skip_sources: set[AuthSource] = set()
        last_error: GladosAPIError | None = None

        for _ in range(_MAX_AUTH_ATTEMPTS):
            cookies, source = self.auth_service.authenticate(
                account,
                skip_sources=frozenset(skip_sources),
            )
            self.api.set_cookies(cookies)

            try:
                return action()

            except GladosAPIError as exc:
                logger.warning(
                    "账号 %s 认证来源 %s 执行失败，降级重试: %s",
                    account.username,
                    source,
                    exc,
                )
                skip_sources.add(source)
                last_error = exc

        raise last_error or GladosAPIError(
            status_code=0,
            message=f"账号 {account.username} 所有认证来源均失效",
        )

    # ================================================================
    # 内部：执行模板
    # ================================================================

    def _run_for_account(
        self,
        username: str,
        action: Callable[[GladosAccountConfig, Account], T],
    ) -> T | None:
        """
        单账号执行模板。

        流程：定位配置 → AccountService.ensure → 认证执行 → commit。
        """
        account = self._resolve_account(username)

        if account is None:
            return None

        try:
            db_account = self.account_service.ensure(account)

            result = self._authenticate_and_run(
                account,
                lambda: action(account, db_account),
            )

            self.session.commit()
            return result

        except Exception:
            self.session.rollback()
            raise

    def _run_for_all(
        self,
        action: Callable[[str], T | None],
    ) -> dict[str, T | None]:
        """批量执行模板。"""
        results: dict[str, T | None] = {}

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过执行")
            return results

        for account in self.glados_config.accounts:
            try:
                results[account.username] = action(account.username)
            except Exception:
                logger.exception("账号 %s 执行异常", account.username)
                results[account.username] = None

        return results

    # ================================================================
    # 签到
    # ================================================================

    def checkin(self, username: str) -> GladosCheckinResult | None:
        """
        指定账号执行签到。

        编排：
            CheckinService 决策 → AccountService 落库 → commit
        """

        def action(
            account: GladosAccountConfig,
            db_account: Account,
        ) -> GladosCheckinResult:
            outcome = self.checkin_service.checkin(account, db_account)
            self._apply_checkin_outcome(db_account, outcome)
            return outcome.result

        return self._run_for_account(username, action)

    def checkin_all(self) -> dict[str, GladosCheckinResult | None]:
        """遍历全部账号执行签到。"""
        return self._run_for_all(self.checkin)

    def _apply_checkin_outcome(
        self,
        db_account: Account,
        outcome: CheckinOutcome,
    ) -> None:
        """根据 CheckinOutcome 编排 AccountService 的落库调用。"""
        if outcome.should_update_account:
            if outcome.action == "checked_in":
                self.account_service.apply_checkin_success(
                    db_account,
                    earned_points=outcome.earned_points,
                    streak=outcome.streak,
                    checkin_local=outcome.checkin_local,
                )
            elif outcome.action == "synced":
                self.account_service.apply_remote_checkin(
                    db_account,
                    streak=outcome.streak,
                    checkin_local=outcome.checkin_local,
                )

        elif outcome.is_failure:
            self.account_service.apply_checkin_failure(
                db_account,
                outcome.error_message or "签到失败",
            )

    # ================================================================
    # 积分
    # ================================================================

    def points(self, username: str) -> GladosPointsResult | None:
        """获取指定账号的积分信息。"""

        def action(
            account: GladosAccountConfig,
            db_account: Account,
        ) -> GladosPointsResult | None:
            result = self.user_service.get_points(account)
            if result is not None:
                self.account_service.update_points(db_account, result.points)
            return result

        return self._run_for_account(username, action)

    def points_all(self) -> dict[str, GladosPointsResult | None]:
        """获取所有账号的积分信息。"""
        return self._run_for_all(self.points)

    # ================================================================
    # 状态
    # ================================================================

    def status(self, username: str) -> GladosStatusResult | None:
        """获取指定账号的状态信息。"""

        def action(
            account: GladosAccountConfig,
            db_account: Account,
        ) -> GladosStatusResult | None:
            result = self.user_service.get_status(account, db_account)
            if result is not None:
                self.account_service.update_left_days(db_account, result.left_days)
            return result

        return self._run_for_account(username, action)

    def status_all(self) -> dict[str, GladosStatusResult | None]:
        """获取所有账号的状态信息。"""
        return self._run_for_all(self.status)

    # ================================================================
    # 积分兑换
    # ================================================================

    def exchange_points(
        self,
        username: str,
        plan_type: str = "plan500",
    ) -> GladosExchangeResult | None:
        """
        指定账号执行积分兑换。

        Args:
            username: 用户名（邮箱）。
            plan_type: 兑换计划类型（plan500 / plan200 / plan100）。
        """
        if plan_type not in _VALID_PLANS:
            logger.error(
                "无效的兑换计划: %s，支持: %s",
                plan_type,
                ", ".join(sorted(_VALID_PLANS)),
            )
            return None

        def action(
            account: GladosAccountConfig,
            db_account: Account,
        ) -> GladosExchangeResult | None:
            result = self.user_service.exchange_points(account, plan_type)
            if result is not None:
                # 赋值剩余积分
                self.account_service.update_points(db_account, result.points)
                # 累加剩余天数
                self.account_service.add_left_days(db_account, result.days_added)
            return result

        return self._run_for_account(username, action)

    # ================================================================
    # 按规则续费（编排：status + points + exchange）
    # ================================================================

    def exchange_points_by_rule(
        self,
        account_config: GladosAccountConfig,
    ) -> GladosExchangeResult | None:
        """
        根据账号配置的续费规则执行积分兑换。

        Args:
            account_config: 账号配置对象。

        Returns:
            兑换结果对象，失败或无需续费返回 None。
        """
        # 1. 检查是否启用续费
        if not account_config.renew_enabled:
            logger.debug(
                "账号 %s 未启用自动续费，跳过",
                account_config.username,
            )
            return None

        # 2. 检查续费套餐是否有效
        plan_type = account_config.renew_plan
        if not plan_type or plan_type not in _VALID_PLANS:
            logger.error(
                "账号 %s 无效的续费套餐: %s，支持: %s",
                account_config.username,
                plan_type,
                ", ".join(sorted(_VALID_PLANS)),
            )
            return None

        # 3. 获取账号状态（检查剩余天数）
        status_result = self.status(account_config.username)
        if status_result is None:
            logger.error(
                "获取账号状态失败: username=%s",
                account_config.username,
            )
            return None

        left_days = status_result.left_days
        threshold = account_config.renew_threshold

        logger.info(
            "账号 %s 剩余天数: %.1f 天, 阈值: %d 天",
            account_config.username,
            left_days,
            threshold,
        )

        # 4. 检查剩余天数是否低于阈值
        if left_days >= threshold:
            logger.info(
                "账号 %s 剩余天数充足 (%.1f >= %d)，无需续费",
                account_config.username,
                left_days,
                threshold,
            )
            return None

        logger.info(
            "账号 %s 剩余天数不足 (%.1f < %d)，触发续费",
            account_config.username,
            left_days,
            threshold,
        )

        # 5. 获取积分（检查积分是否足够）
        points_result = self.points(account_config.username)
        if points_result is None:
            logger.error(
                "获取账号积分失败: username=%s",
                account_config.username,
            )
            return None

        required_points = _PLAN_POINTS_MAP.get(plan_type, 500)
        current_points = points_result.points

        logger.info(
            "账号 %s 当前积分: %.2f, 需要: %d",
            account_config.username,
            current_points,
            required_points,
        )

        if current_points < required_points:
            logger.warning(
                "账号 %s 积分不足: %.2f < %d，跳过续费",
                account_config.username,
                current_points,
                required_points,
            )
            return None

        # 6. 执行兑换
        return self.exchange_points(account_config.username, plan_type)

    def exchange_all_by_rules(self) -> dict[str, GladosExchangeResult | None]:
        """
        根据配置的续费规则执行所有账号的积分兑换。

        Returns:
            字典，key 为用户名，value 为兑换结果（失败或无需续费为 None）。
        """
        results: dict[str, GladosExchangeResult | None] = {}

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过续费检查")
            return results

        for account_config in self.glados_config.accounts:
            try:
                result = self.exchange_points_by_rule(account_config)
                results[account_config.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 续费兑换异常: ",
                    account_config.username,
                )
                results[account_config.username] = None

        self.session.commit()

        success_count = sum(1 for r in results.values() if r is not None)
        logger.info(
            "续费兑换完成，共处理 %d 个账号，成功 %d 笔交易",
            len(results),
            success_count,
        )

        return results

    # ================================================================
    # 报告
    # ================================================================

    def build_report_html(self) -> str:
        """构建 GLaDOS HTML 运行报告。"""
        return self.report_service.build_html(self.glados_config.accounts)


__all__ = [
    "GladosApp",
]
