# apps\glados\core\server.py

import ast
import json
from collections.abc import Callable
from typing import Any, TypeVar

from apps.glados.core.api import (
    GladosAPI,
    GladosAPIError,
)

# 导入配置 DTO
from apps.glados.core.config import GladosAccountConfig, GladosConfig
from apps.glados.core.email import EmailTool
from apps.glados.core.notify_builder import SectionBuilder
from apps.glados.core.notify_dto import (
    AccountInfo,
    AppConfig,
    CheckinResult,
    ReportData,
)
from apps.glados.core.parser import (
    GladosCheckinResult,
    GladosExchangeResult,
    GladosParser,
    GladosPointsResult,
    GladosStatusResult,
)
from apps.glados.core.repositories import (
    Account,
    AccountRepository,
    CheckinLogRepository,
    TrafficHistoryRepository,
)
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.email import EmailClient
from utils.log import get_logger
from utils.paths import logs
from utils.renderer import ReportRenderer
from utils.request_client import RequestClient
from utils.timezone import now_local, utc_to_local

logger = get_logger(name="glados_server", log_dir=logs(), fmt_type="detailed")
from functools import wraps

T = TypeVar("T")


def authenticated(func: Callable[..., T]) -> Callable[..., T]:
    """
    GLaDOS API 认证装饰器。

    按照以下优先级逐级尝试认证：

    1. 数据库 Cookie
    2. 配置文件 Cookie
    3. 邮件验证码登录
    """

    @wraps(func)
    def wrapper(self: "GladosClient", *args: Any, **kwargs: Any) -> T:
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 GLaDOS 账号")

        auth_methods = (
            self._get_database_cookie,
            self._get_config_cookie,
            self._login_with_email,
        )

        last_error: GladosAPIError | None = None

        for auth_method in auth_methods:
            try:
                cookies = auth_method(account)

                if not cookies:
                    continue

                self.api.set_cookies(cookies)

                result = func(self, *args, **kwargs)

                self._save_cookies(account, cookies)

                return result

            except GladosAPIError as exc:
                last_error = exc

                logger.warning(
                    "账号 %s 当前认证方式失败，尝试下一层认证",
                    account.username,
                )

        if last_error is not None:
            raise last_error

        raise GladosAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    return wrapper


class GladosClient:
    def __init__(
        self,
        global_config: GlobalConfig,
        glados_config: GladosConfig,
    ):
        """
        初始化 GLaDOS 客户端。

        Args:
            global_config: 全局配置
            glados_config: GLaDOS 配置
        """
        self.global_config = global_config
        self.glados_config = glados_config

        # ================================================================
        # 当前账号
        # ================================================================

        # 当前正在处理的 GLaDOS 配置账号。
        #
        # 切换账号时更新该属性。
        self._current_account: GladosAccountConfig | None = None

        # ================================================================
        # 基础资源
        # ================================================================

        # 数据库 Session
        self.session = get_session()

        # 加密工具
        self.crypto = Crypto(glados_config.encryption_key)

        # ================================================================
        # HTTP
        # ================================================================

        proxy = global_config.proxy

        self.request_client = RequestClient(
            http_proxies=proxy.http if proxy.enabled else [],
            https_proxies=proxy.https if proxy.enabled else [],
            no_proxy=proxy.no_proxy if proxy.enabled else [],
        )

        # ================================================================
        # GLaDOS API / Parser
        # ================================================================

        self.api = GladosAPI(self.request_client)
        self.parser = GladosParser()

        # ================================================================
        # Email
        # ================================================================

        # 邮箱用户名 -> EmailTool
        self.email_tools: dict[str, EmailTool] = {}

        # ================================================================
        # Repository
        # ================================================================

        self.account_repository = AccountRepository(
            self.session,
            self.crypto,
        )

        self.checkin_log_repository = CheckinLogRepository(
            self.session,
        )

        self.traffic_history_repository = TrafficHistoryRepository(
            self.session,
        )

    # ====================================================================
    # 数据库
    # ====================================================================

    def close(self):
        # 退出释放数据库 Session
        self.session.close()

    def _get_or_create_db_account(
        self,
        account: GladosAccountConfig,
    ) -> Account:
        """
        获取数据库账号，不存在则创建。
        """

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 GLaDOS 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(
            username=account.username,
        )

    # ====================================================================
    # Email
    # ====================================================================

    def get_email_tool(
        self,
        account: GladosAccountConfig,
    ) -> EmailTool:
        """获取指定账号对应的 EmailTool。"""
        username = account.email_user

        if username not in self.email_tools:
            email_client = EmailClient(
                username=account.email_user,
                password=account.email_passwd,
                provider=account.email_provider,
            )

            self.email_tools[username] = EmailTool(email_client)

        return self.email_tools[username]

    # ====================================================================
    # Authentication
    # ====================================================================

    def _get_database_cookie(
        self,
        account: GladosAccountConfig,
    ) -> dict[str, str] | None:
        """
        获取数据库中的 Cookie。

        数据库中的 Cookie 为加密存储，
        Repository 负责解密。
        """
        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            return None

        cookies_str = self.account_repository.get_cookie(
            db_account,
        )

        if not cookies_str:
            return None

        # 使用 ast.literal_eval 安全解析
        return ast.literal_eval(cookies_str)

    def _get_config_cookie(
        self,
        account: GladosAccountConfig,
    ) -> dict[str, str] | None:
        """获取配置文件中的 Cookie。"""
        if not account.cookies or not account.cookies.strip():
            return None
        return ast.literal_eval(account.cookies) or None

    def _login_with_email(
        self,
        account: GladosAccountConfig,
    ) -> dict[str, str] | None:
        """
        通过邮箱验证码登录 GLaDOS。

        登录成功：
            返回新的 Cookie。

        登录失败：
            返回 None。
        """

        email_tool = self.get_email_tool(account)

        logger.info(
            "开始通过邮箱验证码登录 GLaDOS: username=%s",
            account.username,
        )

        # ================================================================
        # 请求登录验证码
        # ================================================================

        auth_response = self.api.authorization(
            account.username,
        )

        auth_result = self.parser.parse_authorization(
            auth_response,
        )

        if not auth_result.success:
            logger.error(
                "请求 GLaDOS 登录验证码失败: username=%s, error=%s",
                account.username,
                auth_result.error,
            )
            return None

        # ================================================================
        # 等待登录验证码
        # ================================================================

        logger.info(
            "等待 GLaDOS 登录验证码: username=%s",
            account.username,
        )

        login_code = email_tool.wait_login_code(
            account.username,
            timeout=600,
            interval=10,
        )

        if login_code is None:
            logger.error(
                "获取 GLaDOS 登录验证码失败: username=%s",
                account.username,
            )
            return None

        # ================================================================
        # 验证验证码归属用户
        # ================================================================

        if login_code.user != account.username:
            logger.error(
                "验证码归属用户不符合登录用户: expected=%s, actual=%s",
                account.username,
                login_code.user,
            )
            return None

        # ================================================================
        # 登录
        # ================================================================

        login_response = self.api.login(
            account.username,
            login_code.code,
        )

        login_result = self.parser.parse_login(
            login_response,
        )

        if not login_result.success:
            logger.error(
                "GLaDOS 邮箱登录失败: username=%s, error=%s",
                account.username,
                login_result.error,
            )
            return None

        cookies = login_result.cookies

        if not cookies:
            logger.error(
                "GLaDOS 登录成功，但未获取到 Cookie: username=%s",
                account.username,
            )
            return None

        logger.info(
            "GLaDOS 邮箱登录成功: username=%s",
            account.username,
        )

        return cookies

    # ====================================================================
    # Cookie
    # ====================================================================

    def _save_cookies(
        self,
        account: GladosAccountConfig,
        cookies: dict[str, str],
    ) -> None:
        """
        保存当前验证成功的 Cookie。

        数据库中不存在账号：
            创建账号。

        数据库中已存在账号：
            更新 Cookie。

        Cookie 的加密由 AccountRepository 负责。
        """

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        # 将字典转为 JSON 字符串
        cookies_str = json.dumps(cookies)

        if db_account is None:
            self.account_repository.create(
                email=account.username,
                cookies=cookies_str,
            )
            return

        self.account_repository.update_cookie(
            db_account,
            cookies_str,
        )

    # ====================================================================
    # Checkin
    # ====================================================================

    @authenticated
    def _checkin(self) -> GladosCheckinResult:
        """
        执行当前 GLaDOS 账号签到。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        签到结果同时同步到数据库。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 GLaDOS 账号")

        logger.info(
            "开始 GLaDOS 签到: username=%s",
            account.username,
        )

        # ================================================================
        # 获取数据库账号
        # ================================================================

        db_account = self.account_repository.get_by_username(account.username)

        # 获取当前本地时间
        current_local = now_local()

        # 检查是否已签到（防止重复签到）
        if db_account.last_checkin_at is not None:
            # 数据库存储的是UTC时间，直接转换
            last_checkin_utc = db_account.last_checkin_at
            last_checkin_local = utc_to_local(last_checkin_utc)

            if last_checkin_local.date() == current_local.date():
                logger.info("账号今日已签到（本地时间 Asia/Shanghai），返回已签到结果")
                # 返回已签到结果，而不是直接 return
                return GladosCheckinResult(
                    success=True,
                )
            else:
                logger.info("账号今日未签到（本地时间 Asia/Shanghai），继续执行")
        else:
            logger.info("账号从未签到过，首次签到")

        # ================================================================
        # 执行签到
        # ================================================================

        response = self.api.checkin()
        result = self.parser.parse_checkin(response)

        # ================================================================
        # 处理签到结果
        # ================================================================

        if result.success:
            if result.already_checked:
                # 情况1：接口返回已签到（可能用户在web端手动签到了）
                logger.info(
                    "GLaDOS 今日已签到（同步数据）: username=%s, points=%d, streak=%d",
                    account.username,
                    result.points,
                    result.streak,
                )
                # 同步数据：更新签到时间，但不增加积分
                # 注意：result.points 是用户当前总积分，不是本次增加的量
            else:
                # 情况2：签到成功，本次获得了新积分
                logger.info(
                    "GLaDOS 签到成功: username=%s, points=%d, streak=%d",
                    account.username,
                    result.points,
                    result.streak,
                )
                # 增加积分（只有真正签到成功才增加）
                db_account.points += result.points
        else:
            # 情况3：签到失败
            logger.warning(
                "GLaDOS 签到失败: username=%s, error=%s",
                account.username,
                result.error,
            )

        # ================================================================
        # 数据库更新（统一处理）
        # ================================================================

        # 更新签到结果（记录本次签到尝试）
        self.account_repository.update_checkin_result(
            account_id=db_account.id,
            success=result.success,
            message=result.message,
            error=result.error,
        )

        # 只有签到成功时更新积分（已在上面处理）
        # 注意：如果 already_checked=True，result.points 是当前总积分，不应累加
        if result.success and not result.already_checked:
            # 积分已在上面累加，这里保存
            self.account_repository.update(db_account)

        # 创建签到日志（记录每次签到尝试）
        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=result.success,
            message=result.message if result.success else result.error,
            points=(
                result.points if result.success and not result.already_checked else 0
            ),
        )

        self.session.commit()
        return result

    def checkin(
        self,
        username: str,
    ) -> GladosCheckinResult:
        """指定账号执行 GLaDOS 签到。"""

        account = next(
            (
                account
                for account in self.glados_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 GLaDOS 账号: username=%s",
                username,
            )
            return GladosCheckinResult.failure(
                f"未找到账号: {username}",
            )

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            result = self._checkin()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def checkin_all(self) -> dict[str, GladosCheckinResult | None]:
        """
        遍历全部 GLaDOS 账号执行签到。

        Returns:
            字典，key 为用户名，value 为签到结果（失败为 None）。
        """
        results: dict[str, GladosCheckinResult | None] = {}

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过签到")
            return results

        for account in self.glados_config.accounts:
            self._current_account = account

            try:
                self._get_or_create_db_account(account)
                result = self._checkin()
                results[account.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 签到异常: ",
                    account.username,
                )
                results[account.username] = None
            finally:
                self._current_account = None

        self.session.commit()
        return results

    # ====================================================================
    # Points (积分)
    # ====================================================================

    @authenticated
    def _points(self) -> GladosPointsResult | None:
        """
        获取当前 GLaDOS 账号的积分信息。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。

        Returns:
            当前积分值，失败返回 None。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 GLaDOS 账号")

        logger.info(
            "获取 GLaDOS 积分信息: username=%s",
            account.username,
        )

        response = self.api.get_points()
        result = self.parser.parse_points(response)

        if not result.success:
            logger.warning(
                "获取 GLaDOS 积分失败: username=%s, error=%s",
                account.username,
                result.error,
            )
            return None

        logger.debug(
            "获取 GLaDOS 积分成功: username=%s, points=%.2f",
            account.username,
            result.points,
        )

        # 更新数据库
        db_account = self.account_repository.get_by_username(account.username)
        if db_account is not None:
            db_account.points = result.points
            self.account_repository.update(db_account)

        return result

    def points(self, username: str) -> GladosPointsResult | None:
        """
        获取指定账号的积分信息。

        Args:
            username: 用户名（邮箱）

        Returns:
            当前积分值，失败返回 None。
        """
        account = next(
            (
                account
                for account in self.glados_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 GLaDOS 账号: username=%s",
                username,
            )
            return None

        self._current_account = account

        try:
            result = self._points()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def points_all(self) -> dict[str, GladosPointsResult | None]:
        """
        获取所有账号的积分信息。

        Returns:
            字典，key 为用户名，value 为积分结果（失败为 None）。
        """
        results: dict[str, GladosPointsResult | None] = {}

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过获取积分")
            return results

        for account in self.glados_config.accounts:
            try:
                result = self.points(account.username)
                results[account.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 获取积分异常: ",
                    account.username,
                )
                results[account.username] = None

        self.session.commit()
        return results

    # ====================================================================
    # Status (状态)
    # ====================================================================

    @authenticated
    def _status(self) -> GladosStatusResult | None:
        """
        获取当前 GLaDOS 账号的状态信息。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。

        Returns:
            包含状态信息的字典，失败返回 None。
            字段包括: vip, left_days, traffic, cake_count, etc.
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 GLaDOS 账号")

        logger.info(
            "获取 GLaDOS 账号状态: username=%s",
            account.username,
        )

        response = self.api.get_status()
        result = self.parser.parse_status(response)

        if not result.success:
            logger.warning(
                "获取 GLaDOS 账号状态失败: username=%s, error=%s",
                account.username,
                result.error,
            )
            return None

        logger.debug(
            "获取 GLaDOS 账号状态成功: username=%s, vip=%s, left_days=%.2f, traffic=%d",
            account.username,
            result.vip,
            result.left_days,
            result.traffic_byte,
        )

        # 更新数据库
        db_account = self.account_repository.get_by_username(account.username)
        if db_account is not None:
            db_account.left_days = result.left_days
            self.account_repository.update(db_account)

            self.traffic_history_repository.create(
                db_account.id,
                result.traffic_byte,
                result.total_traffic_byte,
                result.total_traffic_byte - result.traffic_byte,
            )

        return result

    def status(
        self,
        username: str,
    ) -> GladosStatusResult | None:
        """
        获取指定账号的状态信息。
        Args:
            username: 用户名（邮箱）
        Returns:
            包含状态信息的字典，失败返回 None。
        """
        account = next(
            (
                account
                for account in self.glados_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 GLaDOS 账号: username=%s",
                username,
            )
            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            result = self._status()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def status_all(self) -> dict[str, GladosStatusResult | None]:
        """
        获取所有账号的状态信息。

        Returns:
            字典，key 为用户名，value 为状态结果（失败为 None）。
        """
        results: dict[str, GladosStatusResult | None] = {}

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过获取状态")
            return results

        for account in self.glados_config.accounts:
            try:
                result = self.status(account.username)
                results[account.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 获取状态异常: ",
                    account.username,
                )
                results[account.username] = None

        self.session.commit()
        return results

    # ====================================================================
    # Exchange Points (积分兑换)
    # ====================================================================

    @authenticated
    def _exchange_points(self, plan_type: str) -> GladosExchangeResult | None:
        """
        执行当前 GLaDOS 账号的积分兑换。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。

        Args:
            plan_type: 兑换计划类型，支持 "plan500", "plan200", "plan100"

        Returns:
            GladosExchangeResult 对象，失败返回 None。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 GLaDOS 账号")

        logger.info(
            "开始 GLaDOS 积分兑换: username=%s, plan_type=%s",
            account.username,
            plan_type,
        )

        # 1. 调用 API 执行兑换
        response = self.api.exchange_points(plan_type)
        result = self.parser.parse_exchange(response)

        if not result.success:
            logger.warning(
                "GLaDOS 积分兑换失败: username=%s, plan_type=%s, error=%s",
                account.username,
                plan_type,
                result.error,
            )
            return None

        logger.info(
            "GLaDOS 积分兑换成功: username=%s, plan_type=%s, message=%s, points_used=%d, days_added=%d, points_remaining=%.2f",
            account.username,
            plan_type,
            result.message,
            result.points_used,
            result.days_added,
            result.points,
        )

        # 2. 更新数据库
        db_account = self.account_repository.get_by_username(account.username)
        if db_account is not None:
            # 更新积分（剩余积分）
            db_account.points = result.points
            db_account.left_days += result.days_added
            self.account_repository.update(db_account)

        return result

    def exchange_points(
        self, username: str, plan_type: str = "plan500"
    ) -> GladosExchangeResult | None:
        """
        指定账号执行积分兑换。

        Args:
            username: 用户名（邮箱）
            plan_type: 兑换计划类型
                - "plan500": 500积分兑换30天
                - "plan200": 200积分兑换7天
                - "plan100": 100积分兑换3天

        Returns:
            GladosExchangeResult 对象，失败返回 None。
        """
        # 1. 验证 plan_type
        valid_plans = {"plan500", "plan200", "plan100"}
        if plan_type not in valid_plans:
            logger.error(
                "无效的兑换计划: %s，支持: %s",
                plan_type,
                ", ".join(valid_plans),
            )
            return None

        # 2. 查找账号
        account = next(
            (
                account
                for account in self.glados_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error(
                "未找到 GLaDOS 账号: username=%s",
                username,
            )
            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            return self._exchange_points(plan_type)
        finally:
            self._current_account = None

    def exchange_points_by_rule(
        self,
        account_config: GladosAccountConfig,
    ) -> GladosExchangeResult | None:
        """
        根据账号配置的续费规则执行积分兑换。

        Args:
            account_config: 账号配置对象

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
        valid_plans = {"plan500", "plan200", "plan100"}
        if not plan_type or plan_type not in valid_plans:
            logger.error(
                "账号 %s 无效的续费套餐: %s，支持: %s",
                account_config.username,
                plan_type,
                ", ".join(valid_plans),
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

        # 不同计划所需的积分
        plan_points_map = {
            "plan500": 500,
            "plan200": 200,
            "plan100": 100,
        }

        required_points = plan_points_map.get(plan_type, 500)
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

        检查每个账号的 renew_enabled 配置，
        如果启用且剩余天数低于 renew_threshold，
        则使用 renew_plan 进行兑换。

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

    def build_report_html(self) -> str:
        """构建 GLaDOS HTML 运行报告。"""

        # ============================================================
        # 1. 应用报告配置
        # ============================================================

        app = AppConfig(
            name="GLaDOS",
            icon="🤖",
            gradient_start="#667eea",
            gradient_end="#764ba2",
        )

        accounts: list[AccountInfo] = []
        checkin: list[CheckinResult] = []

        account_configs = self.glados_config.accounts

        if not account_configs:
            logger.warning("没有配置 GLaDOS 账号，跳过报告统计")
        else:
            # ========================================================
            # 2. 获取账号报告数据
            #
            # 一个账号只查询一次，后续同时构建：
            #   AccountInfo
            #   CheckinResult
            # ========================================================

            for account_config in account_configs:
                username = account_config.username

                try:
                    account = self.account_repository.get_by_username(username)

                    if account is None:
                        logger.warning(
                            "账号 %s 不存在，跳过报告统计",
                            username,
                        )
                        continue

                    # ------------------------------------------------
                    # 账户流量信息
                    # ------------------------------------------------

                    traffic = self.traffic_history_repository.get_latest_by_account_id(
                        account.id
                    )

                    if traffic is not None:
                        total_traffic = traffic.total_traffic_bytes
                        used_traffic = traffic.used_traffic_bytes

                        if total_traffic > 0:
                            use_percent = used_traffic / total_traffic * 100
                        else:
                            use_percent = 0.0

                        accounts.append(
                            AccountInfo(
                                username=account.username,
                                points=account.points,
                                left_days=account.left_days,
                                current_traffic=used_traffic,
                                total_traffic=total_traffic,
                                use_percent=use_percent,
                                continuous_checkin_days=account.streak_days,
                                total_checkin_days=account.total_days,
                            )
                        )

                    # ------------------------------------------------
                    # 最近一次签到
                    # ------------------------------------------------

                    checkin_log = self.checkin_log_repository.get_latest_by_account_id(
                        account.id
                    )

                    if checkin_log is not None:
                        checkin.append(
                            CheckinResult(
                                username=account.username,
                                success=checkin_log.success,
                                point=checkin_log.points,
                                created_at=checkin_log.checkin_at,
                            )
                        )

                except Exception:
                    logger.exception(
                        "账号 %s 统计报告信息异常",
                        username,
                    )

        # ============================================================
        # 3. 创建报告 DTO
        # ============================================================

        report_data = ReportData(
            app=app,
            accounts=accounts,
            checkin=checkin,
        )

        # ============================================================
        # 4. 构建 Section
        # ============================================================

        sections = SectionBuilder.build(report_data)

        # ============================================================
        # 5. 使用通用 Renderer 生成完整 HTML
        # ============================================================

        renderer = ReportRenderer(
            app_name=app.name,
            app_icon=app.icon,
            gradient_start=app.gradient_start,
            gradient_end=app.gradient_end,
        )

        return renderer.render(sections)
