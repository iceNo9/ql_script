# apps\glados\core\auth.py

"""
GLaDOS 认证服务。

职责：
    - 按优先级尝试多种认证方式，获取可用 Cookie：
        1. 数据库 Cookie
        2. 配置文件 Cookie
        3. 邮箱验证码登录
    - 认证成功后，把 Cookie 持久化到数据库。
    - 维护 EmailTool 缓存（每个 email_user 一个实例）。

不负责：
    - api.set_cookies（由调用方负责）
    - 账号行的创建 / 存在性保证（由 AccountService 负责）
    - 事务提交与回滚（由调用方负责）
    - 签到 / 积分 / 状态等业务逻辑
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from enum import StrEnum

from apps.glados.core.api import (
    GladosAPI,
    GladosAPIError,
)
from apps.glados.core.config import GladosAccountConfig
from apps.glados.core.email import EmailTool
from apps.glados.core.models import Account
from apps.glados.core.parser import GladosParser
from apps.glados.core.repositories import AccountRepository
from utils.email import EmailClient
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="glados_auth",
    log_dir=logs(),
    fmt_type="detailed",
)


class AuthSource(StrEnum):
    """认证来源。"""

    DATABASE_COOKIES = "database_cookies"
    CONFIG_COOKIES = "config_cookies"
    EMAIL = "email"


class AuthService:
    """
    GLaDOS 认证服务。

    只依赖 API / Parser / AccountRepository，
    不持有 Session，不提交事务，不修改 api 的 cookie 状态。

    EmailTool 缓存在本服务内（每个 email_user 一个实例）。
    """

    def __init__(
        self,
        api: GladosAPI,
        parser: GladosParser,
        account_repository: AccountRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.account_repository = account_repository

        # email_user -> EmailTool
        self._email_tools: dict[str, EmailTool] = {}

    # ================================================================
    # 公开入口
    # ================================================================

    def authenticate(
        self,
        account: GladosAccountConfig,
        *,
        skip_sources: frozenset[AuthSource] = frozenset(),
    ) -> tuple[dict[str, str], AuthSource]:
        """
        按优先级尝试认证，返回 (cookies, source)。

        认证顺序：
            1. 数据库 Cookie
            2. 配置文件 Cookie
            3. 邮箱验证码登录

        Args:
            account: 账号配置。
            skip_sources: 需要跳过的认证来源（单次运行内的降级）。

        Returns:
            (cookies, source)。

        Raises:
            GladosAPIError:
                所有未跳过的认证方式均失败。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            raise GladosAPIError(
                status_code=0,
                message=(
                    f"数据库账号不存在: username={account.username}，"
                    "请先通过 AccountService 创建账号"
                ),
            )

        auth_methods: tuple[
            tuple[
                AuthSource,
                Callable[[GladosAccountConfig, Account], dict[str, str] | None],
            ],
            ...,
        ] = (
            (AuthSource.DATABASE_COOKIES, self._from_database_cookies),
            (AuthSource.CONFIG_COOKIES, self._from_config_cookies),
            (AuthSource.EMAIL, self._from_email),
        )

        last_error: GladosAPIError | None = None

        for source, auth_method in auth_methods:
            if source in skip_sources:
                logger.debug(
                    "账号 %s 跳过认证来源 %s",
                    account.username,
                    source,
                )
                continue

            try:
                cookies = auth_method(account, db_account)
            except GladosAPIError as exc:
                last_error = exc
                logger.warning(
                    "账号 %s 认证来源 %s 失败，尝试下一层",
                    account.username,
                    source,
                )
                continue

            if not cookies:
                logger.debug(
                    "账号 %s 认证来源 %s 未返回 Cookie，尝试下一层",
                    account.username,
                    source,
                )
                continue

            self._save_credentials(account, db_account, cookies)

            logger.info(
                "账号 %s 认证成功（来源: %s）",
                account.username,
                source,
            )
            return cookies, source

        if last_error is not None:
            raise last_error

        raise GladosAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    # ================================================================
    # EmailTool 缓存
    # ================================================================

    def _get_email_tool(self, account: GladosAccountConfig) -> EmailTool:
        """获取指定账号对应的 EmailTool（带缓存）。"""
        username = account.email_user

        if username not in self._email_tools:
            email_client = EmailClient(
                username=account.email_user,
                password=account.email_passwd,
                provider=account.email_provider,
            )
            self._email_tools[username] = EmailTool(email_client)

        return self._email_tools[username]

    # ================================================================
    # 认证方式
    # ================================================================

    def _from_database_cookies(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """从数据库读取 Cookie（Repository 负责解密）。"""
        cookies_str = self.account_repository.get_cookie(db_account)

        if not cookies_str:
            return None

        return self._parse_cookies(cookies_str, account.username)

    def _from_config_cookies(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """从配置文件读取 Cookie。"""
        if not account.cookies or not account.cookies.strip():
            return None

        return self._parse_cookies(account.cookies, account.username)

    def _from_email(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """
        通过邮箱验证码登录。

        异常传播：
            self.api.authorization() / self.api.login() 由 handle_response 装饰，
            HTTP 非正常响应 / 请求异常会抛 GladosAPIError，
            本方法不捕获，由 authenticate() 统一处理。
        """
        email_tool = self._get_email_tool(account)

        logger.info(
            "开始通过邮箱验证码登录 GLaDOS: username=%s",
            account.username,
        )

        # 1. 请求登录验证码
        auth_response = self.api.authorization(account.username)
        auth_result = self.parser.parse_authorization(auth_response)

        if not auth_result.success:
            logger.error(
                "请求 GLaDOS 登录验证码失败: username=%s, error=%s",
                account.username,
                auth_result.error,
            )
            return None

        # 2. 等待登录验证码
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

        # 3. 验证验证码归属用户
        if login_code.user != account.username:
            logger.error(
                "验证码归属用户不符合登录用户: expected=%s, actual=%s",
                account.username,
                login_code.user,
            )
            return None

        # 4. 登录
        login_response = self.api.login(
            account.username,
            login_code.code,
        )
        login_result = self.parser.parse_login(login_response)

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

    # ================================================================
    # Cookie 解析
    # ================================================================

    @staticmethod
    def _parse_cookies(
        cookies_str: str,
        username: str,
    ) -> dict[str, str] | None:
        """
        解析 Cookie 字符串为字典。

        使用 ast.literal_eval 安全反序列化。
        解析失败返回 None。
        """
        try:
            cookies = ast.literal_eval(cookies_str)
        except (ValueError, SyntaxError, TypeError) as e:
            logger.warning(
                "账号 %s Cookie 反序列化失败: %s",
                username,
                e,
            )
            return None

        if not isinstance(cookies, dict):
            logger.warning(
                "账号 %s Cookie 格式错误: 不是字典类型",
                username,
            )
            return None

        return {str(k): str(v) for k, v in cookies.items()}

    # ================================================================
    # 凭据持久化
    # ================================================================

    def _save_credentials(
        self,
        account: GladosAccountConfig,
        db_account: Account,
        cookies: dict[str, str],
    ) -> None:
        """保存认证成功的 Cookie。"""
        cookies_str = json.dumps(cookies)
        self.account_repository.update_cookie(db_account, cookies_str)


__all__ = [
    "AuthService",
    "AuthSource",
]
