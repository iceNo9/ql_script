# apps\hifiti\core\auth.py

"""
Hifiti 认证服务。

职责：
    - 按优先级尝试多种认证方式，获取可用 Cookie：
        1. 数据库 Cookie
        2. 配置文件 Cookie
        3. 密码登录（数据库密码优先 → 配置文件密码）
    - 认证成功后，把 Cookie / 密码持久化到数据库。

不负责：
    - api.set_cookies（由调用方负责）
    - 账号行的创建 / 存在性保证（由 AccountService 负责）
    - 事务提交与回滚（由调用方负责）
    - 签到 / 用户数据等业务逻辑
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from enum import StrEnum

from apps.hifiti.core.api import (
    HifitiAPI,
    HifitiAPIError,
)
from apps.hifiti.core.config import HifitiAccountConfig
from apps.hifiti.core.models import Account
from apps.hifiti.core.parser import HifitiParser
from apps.hifiti.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="hifiti_auth",
    log_dir=logs(),
    fmt_type="detailed",
)


class AuthSource(StrEnum):
    """认证来源。"""

    DATABASE_COOKIES = "database_cookies"
    CONFIG_COOKIES = "config_cookies"
    PASSWORD = "password"


class AuthService:
    """
    Hifiti 认证服务。

    只依赖 API / Parser / AccountRepository，
    不持有 Session，不提交事务，不修改 api 的 cookie 状态。
    """

    def __init__(
        self,
        api: HifitiAPI,
        parser: HifitiParser,
        account_repository: AccountRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.account_repository = account_repository

    # ================================================================
    # 公开入口
    # ================================================================

    def authenticate(
        self,
        account: HifitiAccountConfig,
        *,
        skip_sources: frozenset[AuthSource] = frozenset(),
    ) -> tuple[dict[str, str], AuthSource]:
        """
        按优先级尝试认证，返回 (cookies, source)。

        认证顺序：
            1. 数据库 Cookie
            2. 配置文件 Cookie
            3. 密码登录

        Args:
            account: 账号配置。
            skip_sources: 需要跳过的认证来源（单次运行内的降级）。

        Returns:
            (cookies, source)。

        Raises:
            HifitiAPIError:
                所有未跳过的认证方式均失败。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            raise HifitiAPIError(
                status_code=0,
                message=(
                    f"数据库账号不存在: username={account.username}，"
                    "请先通过 AccountService 创建账号"
                ),
            )

        auth_methods: tuple[
            tuple[
                AuthSource,
                Callable[[HifitiAccountConfig, Account], dict[str, str] | None],
            ],
            ...,
        ] = (
            (AuthSource.DATABASE_COOKIES, self._from_database_cookies),
            (AuthSource.CONFIG_COOKIES, self._from_config_cookies),
            (AuthSource.PASSWORD, self._from_password),
        )

        last_error: HifitiAPIError | None = None

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
            except HifitiAPIError as exc:
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

        raise HifitiAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    # ================================================================
    # 认证方式
    # ================================================================

    def _from_database_cookies(
        self,
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """从数据库读取 Cookie（Repository 负责解密）。"""
        cookies_str = self.account_repository.get_cookies(db_account)

        if not cookies_str:
            return None

        return self._parse_cookies(cookies_str, account.username)

    def _from_config_cookies(
        self,
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """从配置文件读取 Cookie。"""
        if not account.cookies:
            return None

        return self._parse_cookies(account.cookies, account.username)

    def _from_password(
        self,
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """
        通过用户名密码登录。

        密码优先级：
            1. 数据库密码（优先）
            2. 配置文件密码

        异常传播：
            self.api.login() 由 handle_response 装饰，
            HTTP 非正常响应 / 请求异常会抛 HifitiAPIError，
            本方法不捕获，由 authenticate() 统一处理。
        """
        password = self._resolve_password(account, db_account)

        if not password:
            logger.warning(
                "账号 %s 未配置密码（数据库和配置文件均无），无法通过密码登录",
                account.username,
            )
            return None

        logger.info(
            "开始通过用户名密码登录 Hifiti: username=%s",
            account.username,
        )

        response = self.api.login(account.username, password)
        login_result = self.parser.parse_login(response)

        if not login_result.success or not login_result.cookies:
            logger.error(
                "Hifiti 登录失败: username=%s, error=%s",
                account.username,
                login_result.error,
            )
            return None

        logger.info(
            "Hifiti 登录成功: username=%s",
            account.username,
        )

        return login_result.cookies

    def _resolve_password(
        self,
        account: HifitiAccountConfig,
        db_account: Account,
    ) -> str | None:
        """解析密码：数据库优先，其次配置文件。"""
        # 1. 数据库密码
        password = self.account_repository.get_passwd(db_account)
        if password:
            logger.debug(
                "账号 %s 使用数据库密码登录",
                account.username,
            )
            return password

        # 2. 配置文件密码
        if account.passwd and account.passwd.strip():
            logger.debug(
                "账号 %s 使用配置文件密码登录",
                account.username,
            )
            return account.passwd.strip()

        return None

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
        account: HifitiAccountConfig,
        db_account: Account,
        cookies: dict[str, str],
    ) -> None:
        """
        保存认证成功的 Cookie 与密码。

        - Cookie 总是更新。
        - 密码仅在配置文件中有、且与数据库不一致时更新。

        Args:
            account: 账号配置。
            db_account: 数据库账号对象（必定存在）。
            cookies: 认证成功的 Cookie 字典。
        """
        # 更新 Cookie（总是更新）
        cookies_str = json.dumps(cookies)
        self.account_repository.update_cookies(db_account, cookies_str)

        # 更新密码：仅当配置文件提供密码、且与数据库不一致时
        if account.passwd:
            db_passwd = self.account_repository.get_passwd(db_account)
            if db_passwd != account.passwd:
                self.account_repository.update_passwd(db_account, account.passwd)
                logger.debug(
                    "账号 %s 密码已更新（配置文件 → 数据库）",
                    account.username,
                )


__all__ = [
    "AuthService",
    "AuthSource",
]
