# apps\baiyefee\core\app.py

"""
Baiyefee 应用门面。

职责：
    - 装配资源（Session / API / Parser / Repository / Service）
    - 账号定位（username → 配置 → 数据库行）
    - 认证与 Token 注入
    - 事务边界
    - 单账号 / 批量执行模板
    - 编排：CheckinService 决策 → AccountService 落库

不负责：
    - 任何业务细节
    - 任何字段写入
    - HTTP / 解析 / 持久化

认证降级策略：
    任何 BaiyefeeAPIError 都视为"可能需要重新认证"，
    触发认证来源降级（最多 3 次）。
    不再区分 HTTP 内部错误码。
"""

from collections.abc import Callable
from typing import TypeVar

from apps.baiyefee.core.account import AccountService
from apps.baiyefee.core.api import BaiyefeeAPI, BaiyefeeAPIError
from apps.baiyefee.core.auth import AuthService, AuthSource
from apps.baiyefee.core.checkin import CheckinOutcome, CheckinService
from apps.baiyefee.core.config import BaiyefeeAccountConfig, BaiyefeeConfig
from apps.baiyefee.core.models import Account
from apps.baiyefee.core.parser import (
    BaiyefeeCheckinResult,
    BaiyefeeParser,
    BaiyefeeSignInfoResult,
    BaiyefeeUserDataResult,
)
from apps.baiyefee.core.report import ReportService
from apps.baiyefee.core.repositories import (
    AccountRepository,
    CheckinLogRepository,
)
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.log import get_logger
from utils.paths import logs
from utils.request_client import RequestClient

logger = get_logger(
    name="baiyefee_app",
    log_dir=logs(),
    fmt_type="detailed",
)

T = TypeVar("T")

# 认证来源数量，决定降级重试的最大次数
_MAX_AUTH_ATTEMPTS = 3


class BaiyefeeApp:
    """Baiyefee 应用门面。"""

    def __init__(
        self,
        global_config: GlobalConfig,
        baiyefee_config: BaiyefeeConfig,
    ) -> None:
        self.global_config = global_config
        self.baiyefee_config = baiyefee_config

        # 基础资源
        self.session = get_session()
        self.crypto = Crypto(baiyefee_config.encryption_key)

        # HTTP
        proxy = global_config.proxy
        self.request_client = RequestClient(
            http_proxies=proxy.http if proxy.enabled else [],
            https_proxies=proxy.https if proxy.enabled else [],
            no_proxy=proxy.no_proxy if proxy.enabled else [],
        )

        # API / Parser
        self.api = BaiyefeeAPI(self.request_client)
        self.parser = BaiyefeeParser()

        # Repository
        self.account_repository = AccountRepository(self.session, self.crypto)
        self.checkin_log_repository = CheckinLogRepository(self.session)

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
        self.report_service = ReportService(
            self.account_repository,
            self.checkin_log_repository,
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
    ) -> BaiyefeeAccountConfig | None:
        """从配置中按用户名定位账号配置。"""
        account = next(
            (
                account
                for account in self.baiyefee_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error("未找到 Baiyefee 账号: username=%s", username)

        return account

    # ================================================================
    # 内部：认证 + 执行（含降级）
    # ================================================================

    def _authenticate_and_run(
        self,
        account: BaiyefeeAccountConfig,
        action: Callable[[], T],
    ) -> T:
        """
        认证并执行 action，遇到 BaiyefeeAPIError 时降级重试。

        降级逻辑：
            1. authenticate 返回 (token, source)
            2. set_token，执行 action
            3. 若抛 BaiyefeeAPIError：
               把 source 加入 skip_sources，重新认证
            4. 最多尝试 _MAX_AUTH_ATTEMPTS 次（覆盖三层认证来源）

        注意：
            本方法不区分 HTTP 错误类型。
            任何 BaiyefeeAPIError 都视为"可能需要重新认证"。
            若错误实际与认证无关（如频率限制），
            三次降级后仍失败，异常向上抛出。

        Args:
            account: 账号配置。
            action: 使用已认证 api 执行的业务动作。

        Returns:
            action 的返回值。

        Raises:
            BaiyefeeAPIError: 所有认证来源均失效。
            其他异常原样向上抛。
        """
        skip_sources: set[AuthSource] = set()
        last_error: BaiyefeeAPIError | None = None

        for _ in range(_MAX_AUTH_ATTEMPTS):
            token, source = self.auth_service.authenticate(
                account,
                skip_sources=frozenset(skip_sources),
            )
            self.api.set_token(token)

            try:
                return action()

            except BaiyefeeAPIError as exc:
                logger.warning(
                    "账号 %s 认证来源 %s 执行失败，降级重试: %s",
                    account.username,
                    source,
                    exc,
                )
                skip_sources.add(source)
                last_error = exc

        raise last_error or BaiyefeeAPIError(
            status_code=0,
            message=f"账号 {account.username} 所有认证来源均失效",
        )

    # ================================================================
    # 内部：执行模板
    # ================================================================

    def _run_for_account(
        self,
        username: str,
        action: Callable[[BaiyefeeAccountConfig, Account], T],
    ) -> T | None:
        """
        单账号执行模板。

        流程：定位配置 → AccountService.ensure → 认证执行 → commit。

        账号配置不存在时返回 None。
        执行异常原样上抛，由 _run_for_all 统一处理。
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

        if not self.baiyefee_config.accounts:
            logger.warning("没有配置 Baiyefee 账号，跳过执行")
            return results

        for account in self.baiyefee_config.accounts:
            try:
                results[account.username] = action(account.username)
            except Exception:
                logger.exception("账号 %s 执行异常", account.username)
                results[account.username] = None

        return results

    # ================================================================
    # 签到信息
    # ================================================================

    def get_sign_info(
        self,
        username: str,
    ) -> BaiyefeeSignInfoResult | None:
        """获取指定账号的签到信息。"""
        return self._run_for_account(
            username,
            lambda account, _db: self.checkin_service.get_sign_info(account),
        )

    def get_sign_info_all(
        self,
    ) -> dict[str, BaiyefeeSignInfoResult | None]:
        """获取所有账号的签到信息。"""
        return self._run_for_all(self.get_sign_info)

    # ================================================================
    # 签到
    # ================================================================

    def checkin(self, username: str) -> BaiyefeeCheckinResult | None:
        """
        指定账号执行签到。

        编排：
            CheckinService 决策 → AccountService 落库 → commit

        账号配置不存在或执行异常时返回 None。
        """

        def action(
            account: BaiyefeeAccountConfig,
            db_account: Account,
        ) -> BaiyefeeCheckinResult:
            outcome = self.checkin_service.checkin(account, db_account)
            self._apply_outcome(db_account, outcome)
            return outcome.result

        return self._run_for_account(username, action)

    def checkin_all(self) -> dict[str, BaiyefeeCheckinResult | None]:
        """遍历全部账号执行签到。"""
        return self._run_for_all(self.checkin)

    def _apply_outcome(
        self,
        db_account: Account,
        outcome: CheckinOutcome,
    ) -> None:
        """根据 CheckinOutcome 编排 AccountService 的落库调用。"""
        if outcome.should_update_account:
            if outcome.action == "checked_in":
                self.account_service.apply_checkin_success(
                    db_account,
                    total_points=outcome.total_points,
                    checkin_local=outcome.checkin_local,
                )
            elif outcome.action == "synced":
                self.account_service.apply_remote_checkin(
                    db_account,
                    total_points=outcome.total_points,
                    checkin_local=outcome.checkin_local,
                )

        elif outcome.is_failure:
            self.account_service.apply_checkin_failure(
                db_account,
                outcome.error_message or "签到失败",
            )

    # ================================================================
    # 用户数据
    # ================================================================

    def get_user_data(
        self,
        username: str,
    ) -> BaiyefeeUserDataResult | None:
        """获取指定账号的用户数据。"""

        def action(
            account: BaiyefeeAccountConfig,
            db_account: Account,
        ) -> BaiyefeeUserDataResult | None:
            result = self._fetch_user_data(account)
            if result is not None:
                self.account_service.update_points(db_account, result.points)
            return result

        return self._run_for_account(username, action)

    def get_user_data_all(
        self,
    ) -> dict[str, BaiyefeeUserDataResult | None]:
        """获取所有账号的用户数据。"""
        return self._run_for_all(self.get_user_data)

    def _fetch_user_data(
        self,
        account: BaiyefeeAccountConfig,
    ) -> BaiyefeeUserDataResult | None:
        """
        查询远程用户数据并解析。

        不写库。写库由调用方通过 AccountService 完成。

        注意：
            本方法不吞 BaiyefeeAPIError。
            若 token 失效，异常向上抛给 _authenticate_and_run 处理降级。
            仅"解析失败"（result.success=False）返回 None。
        """
        logger.info("获取 Baiyefee 用户数据: username=%s", account.username)

        response = self.api.get_user_data()
        result = self.parser.parse_user_data(response)

        if not result.success:
            logger.warning(
                "获取 Baiyefee 用户数据失败: username=%s, error=%s",
                account.username,
                result.error,
            )
            return None

        logger.debug(
            "获取 Baiyefee 用户数据成功: username=%s, points=%d, money=%.2f",
            account.username,
            result.points,
            result.money,
        )

        return result

    # ================================================================
    # 报告
    # ================================================================

    def build_report_html(self) -> str:
        """构建 Baiyefee HTML 运行报告。"""
        return self.report_service.build_html(self.baiyefee_config.accounts)
