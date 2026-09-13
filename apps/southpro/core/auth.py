# apps/southpro/core/auth.py

"""
SouthPro 认证服务。

职责：
    - 按优先级尝试多种认证方式，获取可用 Cookie：
        1. 数据库 Cookie
        2. 配置文件 Cookie
    - 认证成功后，把 Cookie 持久化到数据库。

不负责：
    - api.set_cookies（由调用方负责）
    - 账号行的创建 / 存在性保证（由 AccountService 负责）
    - 事务提交与回滚（由调用方负责）
    - 任务 / Profile 等业务逻辑

说明：
    SouthPro 当前没有登录 API，认证链只有 2 级。
    后续如果增加登录方式，在 auth_methods 末尾追加即可。

Cookie 存储格式约定：
    - 数据库：JSON 字符串（由 _save_credentials 写入）
    - 配置文件：HTTP Cookie 字符串（用户手填，形如 "k1=v1; k2=v2"）
    - 读取时，两者用不同方式解析，DB 用 json.loads，config 用 cookiesparser.parse
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum

import cookiesparser

from apps.southpro.core.api import SouthProAPIError
from apps.southpro.core.config import SouthProAccountConfig
from apps.southpro.core.models import Account
from apps.southpro.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="southpro_auth",
    log_dir=logs(),
    fmt_type="detailed",
)


class AuthSource(StrEnum):
    """认证来源。"""

    DATABASE_COOKIES = "database_cookies"
    CONFIG_COOKIES = "config_cookies"


class AuthService:
    """
    SouthPro 认证服务。

    只依赖 AccountRepository，
    不持有 Session，不提交事务，不修改 api 的 cookie 状态。
    """

    def __init__(
        self,
        account_repository: AccountRepository,
    ) -> None:
        self.account_repository = account_repository

    # ================================================================
    # 公开入口
    # ================================================================

    def authenticate(
        self,
        account: SouthProAccountConfig,
        *,
        skip_sources: frozenset[AuthSource] = frozenset(),
    ) -> tuple[dict[str, str], AuthSource]:
        """
        按优先级尝试认证，返回 (cookies, source)。

        认证顺序：
            1. 数据库 Cookie
            2. 配置文件 Cookie

        Args:
            account: 账号配置。
            skip_sources: 需要跳过的认证来源（单次运行内的降级）。

        Returns:
            (cookies, source)。

        Raises:
            SouthProAPIError:
                所有未跳过的认证方式均失败。
        """
        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            raise SouthProAPIError(
                status_code=0,
                message=(
                    f"数据库账号不存在: username={account.username}，"
                    "请先通过 AccountService 创建账号"
                ),
            )

        auth_methods: tuple[
            tuple[
                AuthSource,
                Callable[[SouthProAccountConfig, Account], dict[str, str] | None],
            ],
            ...,
        ] = (
            (AuthSource.DATABASE_COOKIES, self._from_database_cookies),
            (AuthSource.CONFIG_COOKIES, self._from_config_cookies),
        )

        last_error: SouthProAPIError | None = None

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
            except SouthProAPIError as exc:
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

        raise SouthProAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    # ================================================================
    # 认证方式
    # ================================================================

    def _from_database_cookies(
        self,
        account: SouthProAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """
        从数据库读取 Cookie（Repository 负责解密）。

        数据库存的是 JSON 字符串，用 json.loads 解析。
        """
        cookies_str = self.account_repository.get_cookies(db_account)

        if not cookies_str:
            logger.debug(
                "账号 %s DB Cookie 为空",
                account.username,
            )
            return None

        logger.debug(
            "账号 %s DB Cookie 已读取: len=%d",
            account.username,
            len(cookies_str),
        )

        return self._parse_json_cookies(cookies_str, account.username)

    def _from_config_cookies(
        self,
        account: SouthProAccountConfig,
        db_account: Account,
    ) -> dict[str, str] | None:
        """
        从配置文件读取 Cookie。

        配置文件存的是 HTTP Cookie 字符串（"k1=v1; k2=v2"），
        用 cookiesparser 解析。
        """
        if not account.cookies:
            return None

        return self._parse_http_cookies(account.cookies, account.username)

    # ================================================================
    # Cookie 解析
    # ================================================================

    @staticmethod
    def _parse_json_cookies(
        cookies_str: str,
        username: str,
    ) -> dict[str, str] | None:
        """
        解析数据库中的 JSON Cookie。

        失败返回 None。
        """
        try:
            cookies = json.loads(cookies_str)
        except (ValueError, TypeError) as e:
            logger.warning(
                "账号 %s DB Cookie JSON 解析失败: %s",
                username,
                e,
            )
            return None

        if not isinstance(cookies, dict):
            logger.warning(
                "账号 %s DB Cookie 不是字典类型",
                username,
            )
            return None

        return {str(k): str(v) for k, v in cookies.items()}

    @staticmethod
    def _parse_http_cookies(
        cookies_str: str,
        username: str,
    ) -> dict[str, str] | None:
        """
        解析配置文件中的 HTTP Cookie 字符串。

        失败返回 None。
        """
        try:
            cookies = cookiesparser.parse(cookies_str)
        except (ValueError, TypeError) as e:
            logger.warning(
                "账号 %s Config Cookie 解析失败: %s",
                username,
                e,
            )
            return None

        if not isinstance(cookies, dict):
            logger.warning(
                "账号 %s Config Cookie 解析结果不是字典类型",
                username,
            )
            return None

        return {str(k): str(v) for k, v in cookies.items()}

    # ================================================================
    # 凭据持久化
    # ================================================================

    def _save_credentials(
        self,
        account: SouthProAccountConfig,
        db_account: Account,
        cookies: dict[str, str],
    ) -> None:
        """
        保存认证成功的 Cookie 到数据库。

        存储格式为 JSON 字符串，与 _from_database_cookies 对应。
        """
        cookies_str = json.dumps(cookies)
        self.account_repository.update_cookies(db_account, cookies_str)

        logger.debug(
            "账号 %s DB Cookie 已更新: len=%d",
            account.username,
            len(cookies_str),
        )


__all__ = [
    "AuthService",
    "AuthSource",
]
