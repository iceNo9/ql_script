# apps/southpro/core/app.py

"""
SouthPro 应用门面。

职责：
    - 装配资源（Session / API / Parser / Repository / Service）
    - 账号定位（username → 配置 → 数据库行）
    - 认证与 Cookie 注入
    - 事务边界
    - 单账号 / 批量执行模板
    - 编排：任务 Service 决策 → AccountService 落库
    - send_report 业务编排（检查今日是否已发送 + 发送 + 记录日志）

不负责：
    - 任何业务细节
    - 任何字段写入
    - HTTP / 解析 / 持久化

认证降级策略：
    任何 SouthProAPIError 都视为"可能需要重新认证"，
    触发认证来源降级（最多 2 次，SouthPro 只有 2 级认证）。
"""

import re
from collections.abc import Callable
from typing import TypeVar

from apps.southpro.core.account import AccountService
from apps.southpro.core.api import SouthProAPI, SouthProAPIError
from apps.southpro.core.auth import AuthService, AuthSource
from apps.southpro.core.config import (
    SouthProAccountConfig,
    SouthProConfig,
)
from apps.southpro.core.daily import DailyTaskOutcome, DailyTaskService
from apps.southpro.core.models import Account
from apps.southpro.core.notify_dto import DailyTaskInfo, WeeklyTaskInfo
from apps.southpro.core.parser import (
    SouthProDailyCompleteResult,
    SouthProParser,
    SouthProProfileResult,
    SouthProWeeklyCompleteResult,
)
from apps.southpro.core.profile import ProfileService
from apps.southpro.core.report import ReportService
from apps.southpro.core.repositories import (
    AccountRepository,
    DailyCompleteLogRepository,
    NotificationLogRepository,
    WeeklyCompleteLogRepository,
)
from apps.southpro.core.weekly import WeeklyTaskOutcome, WeeklyTaskService
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.log import get_logger
from utils.notify import send
from utils.paths import logs
from utils.request_client import RequestClient
from utils.timezone import now_local, now_utc, utc_to_local

logger = get_logger(
    name="southpro_app",
    log_dir=logs(),
    fmt_type="detailed",
)

T = TypeVar("T")

# SouthPro 认证链只有 2 级
_MAX_AUTH_ATTEMPTS = 2


def _build_sec_ch_ua(user_agent: str) -> str:
    """根据 User-Agent 构造 sec-ch-ua 请求头。"""
    match = re.search(r"Chrome/(\d+)", user_agent)

    if not match:
        return ""

    version = match.group(1)

    return (
        f'"Chromium";v="{version}", '
        f'"Google Chrome";v="{version}", '
        '"Not(A:Brand";v="99"'
    )


class SouthProApp:
    """SouthPro 应用门面。"""

    def __init__(
        self,
        global_config: GlobalConfig,
        southpro_config: SouthProConfig,
    ) -> None:
        self.global_config = global_config
        self.southpro_config = southpro_config

        # 基础资源
        self.session = get_session()
        self.crypto = Crypto(southpro_config.encryption_key)

        # HTTP
        proxy = global_config.proxy
        user_agent = southpro_config.user_agent

        self.request_client = RequestClient(
            http_proxies=proxy.http if proxy.enabled else [],
            https_proxies=proxy.https if proxy.enabled else [],
            no_proxy=proxy.no_proxy if proxy.enabled else [],
        )

        if user_agent:
            sec_ch_ua = _build_sec_ch_ua(user_agent)
            self.request_client.update_headers(
                {
                    "User-Agent": user_agent,
                    "sec-ch-ua": sec_ch_ua,
                }
            )

        # API / Parser
        self.api = SouthProAPI(self.request_client)
        self.parser = SouthProParser()

        # Repository
        self.account_repository = AccountRepository(self.session, self.crypto)
        self.daily_complete_log_repository = DailyCompleteLogRepository(self.session)
        self.weekly_complete_log_repository = WeeklyCompleteLogRepository(self.session)
        self.notification_log_repository = NotificationLogRepository(self.session)

        # Service
        self.account_service = AccountService(self.account_repository)
        self.auth_service = AuthService(self.account_repository)
        self.daily_task_service = DailyTaskService(
            self.api,
            self.parser,
            self.daily_complete_log_repository,
        )
        self.weekly_task_service = WeeklyTaskService(
            self.api,
            self.parser,
            self.weekly_complete_log_repository,
        )
        self.profile_service = ProfileService(
            self.api,
            self.parser,
        )
        self.report_service = ReportService(self.account_repository)

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
    ) -> SouthProAccountConfig | None:
        """从配置中按用户名定位账号配置。"""
        account = next(
            (
                account
                for account in self.southpro_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error("未找到 SouthPro 账号: username=%s", username)

        return account

    # ================================================================
    # 内部：认证 + 执行（含降级）
    # ================================================================

    def _authenticate_and_run(
        self,
        account: SouthProAccountConfig,
        action: Callable[[], T],
    ) -> T:
        """
        认证并执行 action，遇到 SouthProAPIError 时降级重试。

        SouthPro 认证链只有 2 级，最多尝试 2 次。
        """
        skip_sources: set[AuthSource] = set()
        last_error: SouthProAPIError | None = None

        for _ in range(_MAX_AUTH_ATTEMPTS):
            cookies, source = self.auth_service.authenticate(
                account,
                skip_sources=frozenset(skip_sources),
            )
            self.api.set_cookies(cookies)

            try:
                return action()

            except SouthProAPIError as exc:
                logger.warning(
                    "账号 %s 认证来源 %s 执行失败，降级重试: %s",
                    account.username,
                    source,
                    exc,
                )
                skip_sources.add(source)
                last_error = exc

        raise last_error or SouthProAPIError(
            status_code=0,
            message=f"账号 {account.username} 所有认证来源均失效",
        )

    # ================================================================
    # 内部：执行模板
    # ================================================================

    def _run_for_account(
        self,
        username: str,
        action: Callable[[SouthProAccountConfig, Account], T],
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

        if not self.southpro_config.accounts:
            logger.warning("没有配置 SouthPro 账号，跳过执行")
            return results

        for account in self.southpro_config.accounts:
            try:
                results[account.username] = action(account.username)
            except Exception:
                logger.exception("账号 %s 执行异常", account.username)
                results[account.username] = None

        return results

    # ================================================================
    # 日常任务
    # ================================================================

    def complete_daily(
        self,
        username: str,
    ) -> SouthProDailyCompleteResult | None:
        """
        指定账号执行日常任务。

        编排：
            DailyTaskService 决策 → AccountService 落库 → commit
        """

        def action(
            account: SouthProAccountConfig,
            db_account: Account,
        ) -> SouthProDailyCompleteResult:
            outcome = self.daily_task_service.complete(account, db_account)
            self._apply_daily_outcome(db_account, outcome)
            return outcome.result

        return self._run_for_account(username, action)

    def complete_daily_all(
        self,
    ) -> dict[str, SouthProDailyCompleteResult | None]:
        """遍历全部账号执行日常任务。"""
        return self._run_for_all(self.complete_daily)

    def _apply_daily_outcome(
        self,
        db_account: Account,
        outcome: DailyTaskOutcome,
    ) -> None:
        """根据 DailyTaskOutcome 编排 AccountService 的落库调用。"""
        if outcome.should_update_account:
            self.account_service.apply_daily_success(
                db_account,
                delta_points_sp=outcome.delta_points_sp,
                complete_at=outcome.complete_at,
            )
        elif outcome.is_failure:
            self.account_service.apply_task_failure(
                db_account,
                outcome.error_message or "日常任务失败",
            )

    # ================================================================
    # 周常任务
    # ================================================================

    def complete_weekly(
        self,
        username: str,
    ) -> SouthProWeeklyCompleteResult | None:
        """
        指定账号执行周常任务。

        编排：
            WeeklyTaskService 决策 → AccountService 落库 → commit
        """

        def action(
            account: SouthProAccountConfig,
            db_account: Account,
        ) -> SouthProWeeklyCompleteResult:
            outcome = self.weekly_task_service.complete(account, db_account)
            self._apply_weekly_outcome(db_account, outcome)
            return outcome.result

        return self._run_for_account(username, action)

    def complete_weekly_all(
        self,
    ) -> dict[str, SouthProWeeklyCompleteResult | None]:
        """遍历全部账号执行周常任务。"""
        return self._run_for_all(self.complete_weekly)

    def _apply_weekly_outcome(
        self,
        db_account: Account,
        outcome: WeeklyTaskOutcome,
    ) -> None:
        """根据 WeeklyTaskOutcome 编排 AccountService 的落库调用。"""
        if outcome.should_update_account:
            self.account_service.apply_weekly_success(
                db_account,
                delta_points_sp=outcome.delta_points_sp,
                complete_at=outcome.complete_at,
            )
        elif outcome.is_failure:
            self.account_service.apply_task_failure(
                db_account,
                outcome.error_message or "周常任务失败",
            )

    # ================================================================
    # Profile
    # ================================================================

    def get_profile(
        self,
        username: str,
    ) -> SouthProProfileResult | None:
        """获取指定账号 Profile。"""

        def action(
            account: SouthProAccountConfig,
            db_account: Account,
        ) -> SouthProProfileResult | None:
            result = self.profile_service.get_profile(account)
            if result is not None:
                self.account_service.update_points_sp(db_account, result.points_sp)
            return result

        return self._run_for_account(username, action)

    def get_profile_all(
        self,
    ) -> dict[str, SouthProProfileResult | None]:
        """获取所有账号 Profile。"""
        return self._run_for_all(self.get_profile)

    # ================================================================
    # 报告
    # ================================================================

    def build_report_html(self) -> str:
        """
        构建 SouthPro HTML 运行报告。

        编排：
            任务 Service 算 next_complete_at → ReportService 组装 + 渲染
        """
        account_configs = self.southpro_config.accounts

        # 1. 任务 Service 构造 DailyTaskInfo / WeeklyTaskInfo
        daily_infos: list[DailyTaskInfo] = self.daily_task_service.build_report_infos(
            account_configs,
            account_repository=self.account_repository,
        )
        weekly_infos: list[WeeklyTaskInfo] = (
            self.weekly_task_service.build_report_infos(
                account_configs,
                account_repository=self.account_repository,
            )
        )

        # 2. ReportService 组装 + 渲染
        return self.report_service.build_html(
            account_configs,
            daily_infos=daily_infos,
            weekly_infos=weekly_infos,
        )

    # ================================================================
    # 通知
    # ================================================================

    def send_report(
        self,
        html: str | None = None,
        *,
        title: str = "【成功】SouthPro 任务执行报告",
    ) -> bool:
        """
        发送 SouthPro 运行报告。

        每天最多成功发送一次完整运行报告。

        发送失败会记录日志，但不会阻止当天后续再次发送。

        Args:
            html: 已构建的 HTML。为 None 时内部构建。
            title: 邮件标题（由 main.py 传入带状态的标题）。

        Returns:
            是否发送成功。
        """
        now = now_local()
        latest_log = self.notification_log_repository.get_latest()

        # 检查今日是否已成功发送
        if latest_log is not None:
            latest_sent_at = utc_to_local(latest_log.sent_at)

            if latest_log.success and latest_sent_at.date() == now.date():
                logger.info(
                    "SouthPro 今日通知已经发送，跳过: sent_at=%s",
                    latest_sent_at,
                )
                return False

        # 构建报告
        if html is None:
            html = self.build_report_html()

        # 发送
        try:
            send(
                title=title,
                content=html,
                SMTP_HTML="true",
            )
        except Exception as exc:
            logger.exception("SouthPro 运行报告发送失败")

            self.notification_log_repository.create(
                success=False,
                message=str(exc) or "通知发送失败",
                sent_at=now_utc(),
            )
            self.session.commit()
            return False

        # 记录通知日志
        self.notification_log_repository.create(
            success=True,
            message="SouthPro 运行报告发送成功",
            sent_at=now_utc(),
        )
        self.session.commit()

        logger.info("SouthPro 运行报告发送完成")
        return True


__all__ = [
    "SouthProApp",
]
