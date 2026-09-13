# apps\baiyefee\core\auth.py

"""
Baiyefee 认证服务。

职责：
    - 按优先级尝试多种认证方式，获取可用 Token：
        1. 数据库 Token
        2. 配置文件 Token
        3. 密码登录（数据库密码优先 → 配置文件密码）
    - 认证成功后，把 Token / 密码持久化到数据库。

不负责：
    - api.set_token（由调用方负责）
    - 账号行的创建 / 存在性保证（由 AccountService 负责）
    - 事务提交与回滚（由调用方负责）
    - 签到 / 用户数据等业务逻辑
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from apps.baiyefee.core.api import (
    BaiyefeeAPI,
    BaiyefeeAPIError,
)
from apps.baiyefee.core.config import BaiyefeeAccountConfig
from apps.baiyefee.core.models import Account
from apps.baiyefee.core.parser import BaiyefeeParser
from apps.baiyefee.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="baiyefee_auth",
    log_dir=logs(),
    fmt_type="detailed",
)


class AuthSource(StrEnum):
    """认证来源。"""

    DATABASE_TOKEN = "database_token"
    CONFIG_TOKEN = "config_token"
    PASSWORD = "password"


class AuthService:
    """
    Baiyefee 认证服务。

    只依赖 API / Parser / AccountRepository，
    不持有 Session，不提交事务，不修改 api 的 token 状态。
    """

    def __init__(
        self,
        api: BaiyefeeAPI,
        parser: BaiyefeeParser,
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
        account: BaiyefeeAccountConfig,
        *,
        skip_sources: frozenset[AuthSource] = frozenset(),
    ) -> tuple[str, AuthSource]:
        """
        按优先级尝试认证，返回 (token, source)。

        认证顺序：
            1. 数据库 Token
            2. 配置文件 Token
            3. 密码登录

        Args:
            account: 账号配置。
            skip_sources: 需要跳过的认证来源（单次运行内的降级）。

        Returns:
            (token, source)。

        Raises:
            BaiyefeeAPIError:
                所有未跳过的认证方式均失败。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            raise BaiyefeeAPIError(
                status_code=0,
                message=(
                    f"数据库账号不存在: username={account.username}，"
                    "请先通过 AccountService 创建账号"
                ),
            )

        # (source, method)
        auth_methods: tuple[
            tuple[AuthSource, Callable[[BaiyefeeAccountConfig, Account], str | None]],
            ...,
        ] = (
            (AuthSource.DATABASE_TOKEN, self._from_database_token),
            (AuthSource.CONFIG_TOKEN, self._from_config_token),
            (AuthSource.PASSWORD, self._from_password),
        )

        last_error: BaiyefeeAPIError | None = None

        for source, auth_method in auth_methods:
            if source in skip_sources:
                logger.debug(
                    "账号 %s 跳过认证来源 %s",
                    account.username,
                    source,
                )
                continue

            try:
                token = auth_method(account, db_account)
            except BaiyefeeAPIError as exc:
                last_error = exc
                logger.warning(
                    "账号 %s 认证来源 %s 失败，尝试下一层",
                    account.username,
                    source,
                )
                continue

            if not token:
                logger.debug(
                    "账号 %s 认证来源 %s 未返回 Token，尝试下一层",
                    account.username,
                    source,
                )
                continue

            self._save_credentials(account, db_account, token)

            logger.info(
                "账号 %s 认证成功（来源: %s）",
                account.username,
                source,
            )
            return token, source

        if last_error is not None:
            raise last_error

        raise BaiyefeeAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    # ================================================================
    # 认证方式（每个方法签名统一：account, db_account → token | None）
    # ================================================================

    def _from_database_token(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> str | None:
        """从数据库读取 Token（Repository 负责解密）。"""
        token = self.account_repository.get_token(db_account)

        if not token:
            return None

        return token

    def _from_config_token(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> str | None:
        """从配置文件读取 Token。"""
        if not account.token or not account.token.strip():
            return None

        return account.token.strip()

    def _from_password(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> str | None:
        """
        通过用户名密码登录。

        密码优先级：
            1. 数据库密码（优先）
            2. 配置文件密码

        异常传播：
            self.api.login() 由 handle_response 装饰，
            HTTP 非正常响应 / 请求异常会抛 BaiyefeeAPIError，
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
            "开始通过用户名密码登录 Baiyefee: username=%s",
            account.username,
        )

        response = self.api.login(account.username, password)
        login_result = self.parser.parse_login(response)

        if not login_result.success or not login_result.token:
            logger.error(
                "Baiyefee 登录失败: username=%s, error=%s",
                account.username,
                login_result.error,
            )
            return None

        logger.info(
            "Baiyefee 登录成功: username=%s",
            account.username,
        )

        return login_result.token

    def _resolve_password(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
    ) -> str | None:
        """
        解析密码：数据库优先，其次配置文件。
        """
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
    # 凭据持久化
    # ================================================================

    def _save_credentials(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account,
        token: str,
    ) -> None:
        """
        保存认证成功的 Token 与密码。

        - Token 总是更新。
        - 密码仅在配置文件中有、且与数据库不一致时更新，
          以保持数据库密码为最新。

        Args:
            account: 账号配置。
            db_account: 数据库账号对象（必定存在）。
            token: 认证成功的 Token。
        """
        # 更新 Token（总是更新）
        self.account_repository.update_token(db_account, token)

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
