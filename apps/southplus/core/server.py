# apps/southplus/core/southplus.py

"""
SouthPlus 应用编排。

职责：
- 管理 SouthPlus 当前账号。
- 管理 API / Parser / Repository。
- 管理 SouthPlus 认证流程。
- 编排日常任务、周常任务以及用户信息同步。
- 构建通知报告。

不负责：
- HTTP 请求底层实现
- API Endpoint 定义
- HTML DOM 解析规则
- 数据库连接管理
- HTML 模板渲染
- 邮件发送
"""

import json
import re
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any, TypeVar

import cookiesparser

from apps.southplus.core.api import (
    SouthPlusAPI,
    SouthPlusAPIError,
)
from apps.southplus.core.config import (
    SouthPlusAccountConfig,
    SouthPlusConfig,
)
from apps.southplus.core.models import Account
from apps.southplus.core.notify_builder import SectionBuilder
from apps.southplus.core.notify_dto import (
    AccountInfo,
    AppConfig,
    DailyTaskInfo,
    ReportData,
    WeeklyTaskInfo,
)
from apps.southplus.core.parser import (
    SouthPlusDailyCompleteResult,
    SouthPlusParser,
    SouthPlusProfileResult,
    SouthPlusWeeklyCompleteResult,
)
from apps.southplus.core.repositories import (
    AccountRepository,
    DailyCompleteLogRepository,
    NotificationLogRepository,
    WeeklyCompleteLogRepository,
)
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.log import get_logger
from utils.notify import send
from utils.paths import logs
from utils.renderer import ReportRenderer
from utils.request_client import RequestClient
from utils.timezone import now_local, now_utc, utc_to_local

logger = get_logger(
    name="southplus_client",
    log_dir=logs(),
    fmt_type="detailed",
)


T = TypeVar("T")

DAILY_INTERVAL = timedelta(hours=18)
WEEKLY_INTERVAL = timedelta(hours=158)


def _build_sec_ch_ua(user_agent: str) -> str:
    match = re.search(r"Chrome/(\d+)", user_agent)

    if not match:
        return ""

    version = match.group(1)

    return (
        f'"Chromium";v="{version}", '
        f'"Google Chrome";v="{version}", '
        '"Not(A:Brand";v="99"'
    )


# ============================================================================
# Authentication
# ============================================================================


def authenticated(
    func: Callable[..., T],
) -> Callable[..., T]:
    """
    SouthPlus API 认证装饰器。

    按照以下优先级逐级尝试认证：

    1. 数据库 Cookie
    2. 配置文件 Cookie

    后续如果 SouthPlus 增加登录 API，
    可以继续在认证链末尾增加登录方式。
    """

    @wraps(func)
    def wrapper(
        self: "SouthPlusClient",
        *args: Any,
        **kwargs: Any,
    ) -> T:
        account = self._current_account

        if account is None:
            raise RuntimeError(
                "当前没有选择 SouthPlus 账号",
            )

        # ================================================================
        # 获取数据库账号
        # ================================================================

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        # ================================================================
        # 认证方式
        #
        # 顺序不能改变：
        # 1. 数据库 Cookie
        # 2. 配置文件 Cookie
        # ================================================================

        auth_methods = (
            self._get_database_cookies,
            self._get_config_cookies,
        )

        last_error: SouthPlusAPIError | None = None

        for auth_method in auth_methods:
            try:
                cookies = auth_method(account)

                if not cookies:
                    continue

                # ========================================================
                # 设置 API Cookie
                # ========================================================

                self.api.set_cookies(cookies)

                # ========================================================
                # 使用当前 Cookie 执行业务 API
                # ========================================================

                result = func(
                    self,
                    *args,
                    **kwargs,
                )

                # ========================================================
                # 当前认证成功
                #
                # 将 Cookie 保存到数据库。
                # 数据库 Cookie 始终作为后续认证的最高优先级。
                # ========================================================

                self._save_cookies(
                    account,
                    cookies,
                    db_account,
                )

                return result

            except SouthPlusAPIError as exc:
                last_error = exc

                logger.warning(
                    "账号 %s 当前认证方式失败，尝试下一层认证",
                    account.username,
                )

        if last_error is not None:
            raise last_error

        raise SouthPlusAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    return wrapper


# ============================================================================
# SouthPlus Client
# ============================================================================


class SouthPlusClient:
    """SouthPlus 应用客户端。"""

    def __init__(
        self,
        global_config: GlobalConfig,
        southplus_config: SouthPlusConfig,
    ) -> None:
        """
        初始化 SouthPlus 客户端。

        Args:
            global_config:
                全局配置。

            southplus_config:
                SouthPlus 应用配置。
        """

        self.global_config = global_config
        self.southplus_config = southplus_config

        # ================================================================
        # 当前账号
        # ================================================================

        self._current_account: SouthPlusAccountConfig | None = None

        # ================================================================
        # 基础资源
        # ================================================================

        self.session = get_session()

        self.crypto = Crypto(
            southplus_config.encryption_key,
        )

        # ================================================================
        # HTTP
        # ================================================================

        proxy = global_config.proxy
        user_agent = southplus_config.user_agent

        self.request_client = RequestClient(
            http_proxies=(proxy.http if proxy.enabled else []),
            https_proxies=(proxy.https if proxy.enabled else []),
            no_proxy=(proxy.no_proxy if proxy.enabled else []),
        )

        if user_agent:
            sec_ch_ua = _build_sec_ch_ua(user_agent)
            self.request_client.update_headers(
                {
                    "User-Agent": user_agent,
                    "sec-ch-ua": sec_ch_ua,
                }
            )

        # ================================================================
        # SouthPlus API / Parser
        # ================================================================

        self.api = SouthPlusAPI(
            self.request_client,
        )

        self.parser = SouthPlusParser()

        # ================================================================
        # Repository
        # ================================================================

        self.account_repository = AccountRepository(
            self.session,
            self.crypto,
        )

        self.daily_complete_log_repository = DailyCompleteLogRepository(
            self.session,
        )

        self.weekly_complete_log_repository = WeeklyCompleteLogRepository(
            self.session,
        )

        self.notification_log_repository = NotificationLogRepository(
            self.session,
        )

    # ========================================================================
    # Database
    # ========================================================================

    def close(self) -> None:
        """关闭数据库 Session。"""
        self.session.close()

    def _get_or_create_db_account(
        self,
        account: SouthPlusAccountConfig,
    ) -> Account:
        """获取数据库账号，不存在则创建。"""

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 SouthPlus 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(
            username=account.username,
        )

    # ========================================================================
    # Cookie
    # ========================================================================

    @staticmethod
    def _parse_cookies(
        cookies_str: str | None,
    ) -> dict[str, str] | None:
        """
        使用 cookiesparser 解析 Cookie 字符串。

        Args:
            cookies_str:
                HTTP Cookie 字符串。

        Returns:
            Cookie 字典。
        """

        if not cookies_str:
            return None

        try:
            cookies = cookiesparser.parse(
                cookies_str,
            )

            if not isinstance(cookies, dict):
                logger.warning(
                    "Cookie 解析结果不是字典类型",
                )
                return None

            return {str(key): str(value) for key, value in cookies.items()}

        except Exception:
            logger.exception(
                "Cookie 解析失败:",
            )
            return None

    # ========================================================================
    # Authentication
    # ========================================================================

    def _get_database_cookies(
        self,
        account: SouthPlusAccountConfig,
    ) -> dict[str, str] | None:
        """
        获取数据库 Cookie。

        优先级最高。

        数据库中的 Cookie：
            加密存储
            ↓
            Repository 解密
            ↓
            cookiesparser 解析
            ↓
            Cookie dict
        """

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            return None

        cookies_str = self.account_repository.get_cookies(
            db_account,
        )

        if not cookies_str:
            return None

        cookies = self._parse_cookies(
            cookies_str,
        )

        if cookies:
            logger.debug(
                "账号 %s 使用数据库 Cookie",
                account.username,
            )

        return cookies

    def _get_config_cookies(
        self,
        account: SouthPlusAccountConfig,
    ) -> dict[str, str] | None:
        """
        获取配置文件 Cookie。

        优先级低于数据库 Cookie。
        """

        if not account.cookies:
            return None

        cookies = self._parse_cookies(
            account.cookies,
        )

        if cookies:
            logger.debug(
                "账号 %s 使用配置文件 Cookie",
                account.username,
            )

        return cookies

    # ========================================================================
    # Cookie 保存
    # ========================================================================

    def _save_cookies(
        self,
        account: SouthPlusAccountConfig,
        cookies: dict[str, str],
        db_account: Account | None = None,
    ) -> None:
        """
        保存验证成功的 Cookie。

        Args:
            account:
                SouthPlus 账号配置。

            cookies:
                验证成功的 Cookie 字典。

            db_account:
                数据库账号对象（可选，避免重复查询）。
        """

        cookies_str = json.dumps(cookies)

        if db_account is None:
            db_account = self.account_repository.get_by_username(
                account.username,
            )

        if db_account is None:
            self.account_repository.create(
                username=account.username,
                cookies=cookies_str,
            )

            logger.debug(
                "账号 %s 创建数据库记录并保存 Cookie",
                account.username,
            )

            return

        # 更新 Cookie（总是更新）
        self.account_repository.update_cookies(
            db_account,
            cookies_str,
        )

        logger.debug(
            "账号 %s Cookie 已更新到数据库",
            account.username,
        )

    # ============================================================================
    # Daily Task
    # ============================================================================

    @authenticated
    def _complete_daily(
        self,
    ) -> SouthPlusDailyCompleteResult:
        """
        执行当前账号日常任务。

        日常任务执行间隔：

            18 小时

        执行流程：

            1. 检查上次完成时间
            2. 未达到 18 小时则跳过
            3. 申请日常任务
            4. 检查申请结果
            5. 完成日常任务
            6. 检查完成结果
            7. 更新账号统计
            8. 记录完成日志
            9. 提交事务

        Result.success 的含义：

            success=False
                Response 解析失败。

            success=True
                Response 解析正常。

        业务状态：

            apply_result.applied
                是否申请成功。

            complete_result.completed
                是否完成成功。
        """

        account = self._current_account

        if account is None:
            raise RuntimeError(
                "当前没有选择 SouthPlus 账号",
            )

        logger.info(
            "开始完成 SouthPlus 日常任务: username=%s",
            account.username,
        )

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            logger.error(
                "数据库账号不存在: username=%s",
                account.username,
            )

            return SouthPlusDailyCompleteResult.failure(
                "数据库账号不存在",
            )

        try:
            # ====================================================================
            # 检查执行间隔
            # ====================================================================

            now = now_local()
            last_complete_at = db_account.last_daily_complete_at

            if last_complete_at is not None:
                last_complete_at = utc_to_local(
                    last_complete_at,
                )

                elapsed = now - last_complete_at

                if elapsed < DAILY_INTERVAL:
                    logger.info(
                        "账号 %s 日常任务未达到执行间隔，跳过: "
                        "last_complete_at=%s, elapsed=%s, interval=%s",
                        account.username,
                        last_complete_at,
                        elapsed,
                        DAILY_INTERVAL,
                    )

                    return SouthPlusDailyCompleteResult(
                        success=True,
                        completed=False,
                        delta_points_sp=0,
                    )

            # ====================================================================
            # 申请日常任务
            # ====================================================================

            response = self.api.apply_daily()

            apply_result = self.parser.parse_apply_daily(
                response,
            )

            # --------------------------------------------------------------------
            # Response 解析失败
            # --------------------------------------------------------------------

            if not apply_result.success:
                error = apply_result.error or "日常任务申请响应解析失败"

                self._handle_daily_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return SouthPlusDailyCompleteResult.failure(
                    error,
                )

            # --------------------------------------------------------------------
            # 申请业务失败
            # --------------------------------------------------------------------

            if not apply_result.applied:
                error = apply_result.error or "日常任务申请失败"

                logger.warning(
                    "账号 %s 日常任务申请失败: %s",
                    account.username,
                    error,
                )

                return SouthPlusDailyCompleteResult(
                    success=True,
                    completed=False,
                    delta_points_sp=0,
                    error=error,
                )

            # ====================================================================
            # 完成日常任务
            # ====================================================================

            response = self.api.complete_daily()

            complete_result = self.parser.parse_complete_daily(
                response,
            )

            # --------------------------------------------------------------------
            # Response 解析失败
            # --------------------------------------------------------------------

            if not complete_result.success:
                error = complete_result.error or "日常任务完成响应解析失败"

                self._handle_daily_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return SouthPlusDailyCompleteResult.failure(
                    error,
                )

            # --------------------------------------------------------------------
            # 完成业务失败
            # --------------------------------------------------------------------

            if not complete_result.completed:
                error = complete_result.error or "日常任务完成失败"

                logger.warning(
                    "账号 %s 日常任务完成失败: %s",
                    account.username,
                    error,
                )

                self._handle_daily_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return complete_result

            # ====================================================================
            # 日常完成成功
            # ====================================================================

            complete_at = now_utc()

            db_account.points_sp += complete_result.delta_points_sp

            db_account.daily_complete_count += 1

            db_account.last_daily_complete_at = complete_at

            # 成功后恢复账号有效状态
            db_account.is_valid = True
            db_account.error_count = 0
            db_account.last_error_at = None

            self.account_repository.update(
                db_account,
            )

            self.daily_complete_log_repository.create(
                account_id=db_account.id,
                success=True,
                delta_points_sp=complete_result.delta_points_sp,
                message="日常任务完成成功",
                complete_at=complete_at,
            )

            self.session.commit()

            logger.info(
                "SouthPlus 日常任务完成: "
                "username=%s, delta_points_sp=%d, points_sp=%d",
                account.username,
                complete_result.delta_points_sp,
                db_account.points_sp,
            )

            return complete_result

        except Exception as exc:
            logger.exception(
                "SouthPlus 日常任务异常: username=%s",
                account.username,
            )

            self._handle_daily_failure(
                db_account,
                str(exc) or "日常任务异常",
            )

            self.session.commit()

            return SouthPlusDailyCompleteResult.failure(
                "日常任务异常",
            )

    def _handle_daily_failure(
        self,
        db_account: Account,
        error_message: str,
    ) -> None:
        """处理日常任务失败。"""

        db_account.error_count += 1
        db_account.last_error_at = now_utc()

        if db_account.error_count >= 5:
            db_account.is_valid = False

            logger.warning(
                "账号 %s 日常任务失败次数过多 (%d 次)，" "已标记为无效",
                db_account.username,
                db_account.error_count,
            )

        self.account_repository.update(
            db_account,
        )

        self.daily_complete_log_repository.create(
            account_id=db_account.id,
            success=False,
            delta_points_sp=0,
            message=error_message,
            complete_at=now_utc(),
        )

        logger.warning(
            "❌ 日常任务失败: " "username=%s, error=%s, error_count=%d",
            db_account.username,
            error_message,
            db_account.error_count,
        )

    def complete_daily(
        self,
        username: str,
    ) -> SouthPlusDailyCompleteResult:
        """指定账号执行日常任务。"""

        account = next(
            (
                account
                for account in self.southplus_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 SouthPlus 账号: username=%s",
                username,
            )

            return SouthPlusDailyCompleteResult.failure(
                f"未找到账号: {username}",
            )

        self._current_account = account

        try:
            self._get_or_create_db_account(
                account,
            )

            return self._complete_daily()

        finally:
            self._current_account = None

    def complete_daily_all(
        self,
    ) -> dict[str, SouthPlusDailyCompleteResult | None]:
        """遍历全部账号执行日常任务。"""

        results: dict[
            str,
            SouthPlusDailyCompleteResult | None,
        ] = {}

        if not self.southplus_config.accounts:
            logger.warning(
                "没有配置 SouthPlus 账号，跳过日常任务",
            )

            return results

        for account in self.southplus_config.accounts:
            self._current_account = account

            try:
                self._get_or_create_db_account(
                    account,
                )

                results[account.username] = self._complete_daily()

            except Exception:
                logger.exception(
                    "账号 %s 日常任务异常",
                    account.username,
                )

                results[account.username] = None

            finally:
                self._current_account = None

        self.session.commit()

        return results

    # ============================================================================
    # Weekly Task
    # ============================================================================

    @authenticated
    def _complete_weekly(
        self,
    ) -> SouthPlusWeeklyCompleteResult:
        """
        执行当前账号周常任务。

        周常任务执行间隔：

            158 小时

        执行流程：

            1. 检查上次完成时间
            2. 未达到 158 小时则跳过
            3. 申请周常任务
            4. 检查申请结果
            5. 完成周常任务
            6. 检查完成结果
            7. 更新账号统计
            8. 记录完成日志
            9. 提交事务

        Result.success 的含义：

            success=False
                Response 解析失败。

            success=True
                Response 解析正常。

        业务状态：

            apply_result.applied
                是否申请成功。

            complete_result.completed
                是否完成成功。
        """

        account = self._current_account

        if account is None:
            raise RuntimeError(
                "当前没有选择 SouthPlus 账号",
            )

        logger.info(
            "开始完成 SouthPlus 周常任务: username=%s",
            account.username,
        )

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            logger.error(
                "数据库账号不存在: username=%s",
                account.username,
            )

            return SouthPlusWeeklyCompleteResult.failure(
                "数据库账号不存在",
            )

        try:
            # ====================================================================
            # 检查执行间隔
            # ====================================================================

            now = now_local()
            last_complete_at = db_account.last_weekly_complete_at

            if last_complete_at is not None:
                last_complete_at = utc_to_local(
                    last_complete_at,
                )

                elapsed = now - last_complete_at

                if elapsed < WEEKLY_INTERVAL:
                    logger.info(
                        "账号 %s 周常任务未达到执行间隔，跳过: "
                        "last_complete_at=%s, elapsed=%s, interval=%s",
                        account.username,
                        last_complete_at,
                        elapsed,
                        WEEKLY_INTERVAL,
                    )

                    return SouthPlusWeeklyCompleteResult(
                        success=True,
                        completed=False,
                        delta_points_sp=0,
                    )

            # ====================================================================
            # 申请周常任务
            # ====================================================================

            response = self.api.apply_weekly()

            apply_result = self.parser.parse_apply_weekly(
                response,
            )

            # --------------------------------------------------------------------
            # Response 解析失败
            # --------------------------------------------------------------------

            if not apply_result.success:
                error = apply_result.error or "周常任务申请响应解析失败"

                self._handle_weekly_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return SouthPlusWeeklyCompleteResult.failure(
                    error,
                )

            # --------------------------------------------------------------------
            # 申请业务失败
            # --------------------------------------------------------------------

            if not apply_result.applied:
                error = apply_result.error or "周常任务申请失败"

                logger.warning(
                    "账号 %s 周常任务申请失败: %s",
                    account.username,
                    error,
                )

                return SouthPlusWeeklyCompleteResult(
                    success=True,
                    completed=False,
                    delta_points_sp=0,
                    error=error,
                )

            # ====================================================================
            # 完成周常任务
            # ====================================================================

            response = self.api.complete_weekly()

            complete_result = self.parser.parse_complete_weekly(
                response,
            )

            # --------------------------------------------------------------------
            # Response 解析失败
            # --------------------------------------------------------------------

            if not complete_result.success:
                error = complete_result.error or "周常任务完成响应解析失败"

                self._handle_weekly_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return SouthPlusWeeklyCompleteResult.failure(
                    error,
                )

            # --------------------------------------------------------------------
            # 完成业务失败
            # --------------------------------------------------------------------

            if not complete_result.completed:
                error = complete_result.error or "周常任务完成失败"

                logger.warning(
                    "账号 %s 周常任务完成失败: %s",
                    account.username,
                    error,
                )

                self._handle_weekly_failure(
                    db_account,
                    error,
                )

                self.session.commit()

                return complete_result

            # ====================================================================
            # 周常完成成功
            # ====================================================================

            complete_at = now_utc()

            db_account.points_sp += complete_result.delta_points_sp

            db_account.weekly_complete_count += 1

            db_account.last_weekly_complete_at = complete_at

            # 成功后恢复账号有效状态
            db_account.is_valid = True
            db_account.error_count = 0
            db_account.last_error_at = None

            self.account_repository.update(
                db_account,
            )

            self.weekly_complete_log_repository.create(
                account_id=db_account.id,
                success=True,
                delta_points_sp=complete_result.delta_points_sp,
                message="周常任务完成成功",
                complete_at=complete_at,
            )

            self.session.commit()

            logger.info(
                "SouthPlus 周常任务完成: "
                "username=%s, delta_points_sp=%d, points_sp=%d",
                account.username,
                complete_result.delta_points_sp,
                db_account.points_sp,
            )

            return complete_result

        except Exception as exc:
            logger.exception(
                "SouthPlus 周常任务异常: username=%s",
                account.username,
            )

            self._handle_weekly_failure(
                db_account,
                str(exc) or "周常任务异常",
            )

            self.session.commit()

            return SouthPlusWeeklyCompleteResult.failure(
                "周常任务异常",
            )

    def _handle_weekly_failure(
        self,
        db_account: Account,
        error_message: str,
    ) -> None:
        """处理周常任务失败。"""

        db_account.error_count += 1
        db_account.last_error_at = now_utc()

        if db_account.error_count >= 5:
            db_account.is_valid = False

            logger.warning(
                "账号 %s 周常任务失败次数过多 (%d 次)，" "已标记为无效",
                db_account.username,
                db_account.error_count,
            )

        self.account_repository.update(
            db_account,
        )

        self.weekly_complete_log_repository.create(
            account_id=db_account.id,
            success=False,
            delta_points_sp=0,
            message=error_message,
            complete_at=now_utc(),
        )

        logger.warning(
            "❌ 周常任务失败: " "username=%s, error=%s, error_count=%d",
            db_account.username,
            error_message,
            db_account.error_count,
        )

    def complete_weekly(
        self,
        username: str,
    ) -> SouthPlusWeeklyCompleteResult:
        """指定账号执行周常任务。"""

        account = next(
            (
                account
                for account in self.southplus_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 SouthPlus 账号: username=%s",
                username,
            )

            return SouthPlusWeeklyCompleteResult.failure(
                f"未找到账号: {username}",
            )

        self._current_account = account

        try:
            self._get_or_create_db_account(
                account,
            )

            return self._complete_weekly()

        finally:
            self._current_account = None

    def complete_weekly_all(
        self,
    ) -> dict[str, SouthPlusWeeklyCompleteResult | None]:
        """遍历全部账号执行周常任务。"""

        results: dict[
            str,
            SouthPlusWeeklyCompleteResult | None,
        ] = {}

        if not self.southplus_config.accounts:
            logger.warning(
                "没有配置 SouthPlus 账号，跳过周常任务",
            )

            return results

        for account in self.southplus_config.accounts:
            self._current_account = account

            try:
                self._get_or_create_db_account(
                    account,
                )

                results[account.username] = self._complete_weekly()

            except Exception:
                logger.exception(
                    "账号 %s 周常任务异常",
                    account.username,
                )

                results[account.username] = None

            finally:
                self._current_account = None

        self.session.commit()

        return results

    # ========================================================================
    # Profile
    # ========================================================================

    @authenticated
    def _get_profile(
        self,
    ) -> SouthPlusProfileResult | None:
        """获取当前账号 Profile。"""

        account = self._current_account

        if account is None:
            raise RuntimeError(
                "当前没有选择 SouthPlus 账号",
            )

        logger.info(
            "获取 SouthPlus Profile: username=%s",
            account.username,
        )

        try:
            response = self.api.get_profile()

            result = self.parser.parse_profile(
                response,
            )

            if not result.success:
                logger.warning(
                    "获取 SouthPlus Profile 失败: " "username=%s, error=%s",
                    account.username,
                    result.error,
                )

                return None

            # ============================================================
            # 同步当前 SP
            # ============================================================

            db_account = self.account_repository.get_by_username(
                account.username,
            )

            if db_account is not None:
                db_account.points_sp = result.points_sp

                self.account_repository.update(
                    db_account,
                )

                self.session.commit()

            return result

        except Exception:
            logger.exception(
                "获取 SouthPlus Profile 异常: username=%s",
                account.username,
            )

            return None

    def get_profile(
        self,
        username: str,
    ) -> SouthPlusProfileResult | None:
        """获取指定账号 Profile。"""

        account = next(
            (
                account
                for account in self.southplus_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 SouthPlus 账号: username=%s",
                username,
            )

            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(
                account,
            )

            return self._get_profile()

        finally:
            self._current_account = None

    def get_profile_all(
        self,
    ) -> dict[str, SouthPlusProfileResult | None]:
        """获取所有账号 Profile。"""

        results: dict[
            str,
            SouthPlusProfileResult | None,
        ] = {}

        if not self.southplus_config.accounts:
            logger.warning(
                "没有配置 SouthPlus 账号，" "跳过获取 Profile",
            )

            return results

        for account in self.southplus_config.accounts:
            try:
                results[account.username] = self.get_profile(
                    account.username,
                )

            except Exception:
                logger.exception(
                    "账号 %s 获取 Profile 异常",
                    account.username,
                )

                results[account.username] = None

        self.session.commit()

        return results

    # ========================================================================
    # Report
    # ========================================================================

    def build_report_html(self) -> str:
        """构建 SouthPlus HTML 运行报告。"""

        app = AppConfig(
            name="SouthPlus",
            icon="💎",
            gradient_start="#667eea",
            gradient_end="#764ba2",
        )

        accounts: list[AccountInfo] = []
        daily: list[DailyTaskInfo] = []
        weekly: list[WeeklyTaskInfo] = []

        account_configs = self.southplus_config.accounts

        if not account_configs:
            logger.warning(
                "没有配置 SouthPlus 账号，" "跳过报告统计",
            )

        else:
            for account_config in account_configs:
                username = account_config.username

                try:
                    db_account = self.account_repository.get_by_username(username)

                    if db_account is None:
                        logger.warning(
                            "账号 %s 不存在，" "跳过报告统计",
                            username,
                        )

                        continue

                    # ====================================================
                    # Account
                    # ====================================================

                    accounts.append(
                        AccountInfo(
                            username=db_account.username,
                            points_sp=db_account.points_sp,
                            error_count=db_account.error_count,
                            last_error_at=db_account.last_error_at,
                        )
                    )

                    # ====================================================
                    # Daily
                    # ====================================================

                    daily.append(
                        DailyTaskInfo(
                            username=db_account.username,
                            complete_count=(db_account.daily_complete_count),
                            last_complete_at=(db_account.last_daily_complete_at),
                            # TODO:
                            # 根据 SouthPlus 日常周期计算。
                            next_complete_at=None,
                        )
                    )

                    # ====================================================
                    # Weekly
                    # ====================================================

                    weekly.append(
                        WeeklyTaskInfo(
                            username=db_account.username,
                            complete_count=(db_account.weekly_complete_count),
                            last_complete_at=(db_account.last_weekly_complete_at),
                            # TODO:
                            # 根据 SouthPlus 周常周期计算。
                            next_complete_at=None,
                        )
                    )

                except Exception:
                    logger.exception(
                        "账号 %s 统计报告信息异常",
                        username,
                    )

        # ================================================================
        # Report DTO
        # ================================================================

        report_data = ReportData(
            app=app,
            accounts=accounts,
            daily=daily,
            weekly=weekly,
        )

        # ================================================================
        # Section
        # ================================================================

        sections = SectionBuilder.build(
            report_data,
        )

        # ================================================================
        # Renderer
        # ================================================================

        renderer = ReportRenderer(
            app_name=app.name,
            app_icon=app.icon,
            gradient_start=app.gradient_start,
            gradient_end=app.gradient_end,
        )

        return renderer.render(
            sections,
        )

    # ============================================================================
    # Notification
    # ============================================================================

    def send_report(
        self,
        html: str | None = None,
    ) -> bool:
        """
        发送 SouthPlus 运行报告。

        每天最多成功发送一次完整运行报告。

        通知发送本身属于 Client 的业务编排，
        NotificationLogRepository 只负责数据库 CRUD。

        发送失败会记录日志，但不会阻止当天后续再次发送。
        """

        now = now_local()

        latest_log = self.notification_log_repository.get_latest()

        # ========================================================================
        # 检查今天是否已经成功发送
        #
        # 失败记录不会阻止当天再次发送。
        # ========================================================================

        if latest_log is not None:
            latest_sent_at = utc_to_local(
                latest_log.sent_at,
            )

            if latest_log.success and latest_sent_at.date() == now.date():
                logger.info(
                    "SouthPlus 今日通知已经发送，跳过: sent_at=%s",
                    latest_sent_at,
                )

                return False

        # ========================================================================
        # 构建报告
        # ========================================================================

        if html is None:
            html = self.build_report_html()

        # ========================================================================
        # 发送通知
        # ========================================================================

        try:
            send(
                title="SouthPlus 任务执行报告",
                content=html,
                SMTP_HTML="true",
            )

        except Exception as exc:
            logger.exception(
                "SouthPlus 运行报告发送失败",
            )

            self.notification_log_repository.create(
                success=False,
                message=str(exc) or "通知发送失败",
                sent_at=now_utc(),
            )

            self.session.commit()

            return False

        # ========================================================================
        # 记录通知日志
        # ========================================================================

        self.notification_log_repository.create(
            success=True,
            message="SouthPlus 运行报告发送成功",
            sent_at=now_utc(),
        )

        self.session.commit()

        logger.info(
            "SouthPlus 运行报告发送完成",
        )

        return True


__all__ = [
    "SouthPlusClient",
    "authenticated",
]
