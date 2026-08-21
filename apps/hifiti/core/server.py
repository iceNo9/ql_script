# modules/hifiti/core/hifiti.py

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from apps.hifiti.core.api import (
    HifitiAPI,
    HifitiAPIError,
)
from apps.hifiti.core.config import HifitiAccountConfig, HifitiConfig
from apps.hifiti.core.notify_builder import SectionBuilder
from apps.hifiti.core.notify_dto import (
    AccountInfo,
    AppConfig,
    CheckinResult,
    ReportData,
)
from apps.hifiti.core.parser import (
    HifitiCheckinResult,
    HifitiParser,
    HifitiUserDataResult,
)
from apps.hifiti.core.repositories import (
    Account,
    AccountRepository,
    CheckinLogRepository,
)
from utils.config import GlobalConfig
from utils.crypto import Crypto
from utils.database import get_session
from utils.log import get_logger
from utils.paths import logs
from utils.renderer import ReportRenderer
from utils.request_client import RequestClient
from utils.timezone import (
    now_local,
    now_utc,
    utc_to_local,
)

logger = get_logger(name="hifiti_server", log_dir=logs(), fmt_type="detailed")

T = TypeVar("T")


def authenticated(func: Callable[..., T]) -> Callable[..., T]:
    """
    Hifiti API 认证装饰器。

    按照以下优先级逐级尝试认证：

    1. 数据库 Cookie
    2. 配置文件 Cookie
    3. 数据库密码 → 配置文件密码（通过 login API）
    """

    @wraps(func)
    def wrapper(self: "HifitiClient", *args: Any, **kwargs: Any) -> T:
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Hifiti 账号")

        # 获取数据库账号
        db_account = self.account_repository.get_by_username(account.username)

        auth_methods = (
            self._get_database_cookies,
            self._get_config_cookies,
            self._login_with_password,
        )

        last_error: HifitiAPIError | None = None

        for auth_method in auth_methods:
            try:
                # 对于密码登录，传入 db_account 以便优先使用数据库密码
                if auth_method == self._login_with_password:
                    cookies = auth_method(account, db_account)
                else:
                    cookies = auth_method(account)

                if not cookies:
                    continue

                self.api.set_cookies(cookies)

                result = func(self, *args, **kwargs)

                # 保存成功的 Cookie 和密码
                self._save_cookies(account, cookies, db_account)

                return result

            except HifitiAPIError as exc:
                last_error = exc
                logger.warning(
                    "账号 %s 当前认证方式失败，尝试下一层认证",
                    account.username,
                )

        if last_error is not None:
            raise last_error

        raise HifitiAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    return wrapper


class HifitiClient:
    def __init__(
        self,
        global_config: GlobalConfig,
        hifiti_config: HifitiConfig,
    ):
        """
        初始化 Hifiti 客户端。

        Args:
            global_config: 全局配置
            hifiti_config: Hifiti 配置
        """
        self.global_config = global_config
        self.hifiti_config = hifiti_config

        # ================================================================
        # 当前账号
        # ================================================================

        self._current_account: HifitiAccountConfig | None = None

        # ================================================================
        # 基础资源
        # ================================================================

        self.session = get_session()
        self.crypto = Crypto(hifiti_config.encryption_key)

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
        # Hifiti API / Parser
        # ================================================================

        self.api = HifitiAPI(self.request_client)
        self.parser = HifitiParser()

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

    # ====================================================================
    # 数据库
    # ====================================================================

    def close(self):
        self.session.close()

    def _get_or_create_db_account(
        self,
        account: HifitiAccountConfig,
    ) -> Account:
        """获取数据库账号，不存在则创建。"""

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 Hifiti 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(
            username=account.username,
        )

    # ====================================================================
    # Cookie 解析辅助方法
    # ====================================================================

    def _parse_cookies(self, cookies_str: str | None) -> dict[str, str] | None:
        """
        解析 Cookie 字符串为字典。

        使用 ast.literal_eval 进行安全反序列化。
        """
        import ast

        if not cookies_str:
            return None

        try:
            cookies = ast.literal_eval(cookies_str)
            if not isinstance(cookies, dict):
                logger.warning("Cookie 格式错误: 不是字典类型")
                return None
            # 确保所有 key 和 value 都是字符串
            return {str(k): str(v) for k, v in cookies.items()}
        except (ValueError, SyntaxError, TypeError) as e:
            logger.warning("Cookie 反序列化失败: %s", e)
            return None

    # ====================================================================
    # Authentication
    # ====================================================================

    def _get_database_cookies(
        self,
        account: HifitiAccountConfig,
    ) -> dict[str, str] | None:
        """
        获取数据库中的 Cookie（优先级最高）。

        数据库中的 Cookie 为加密存储的 JSON 字符串，
        Repository 负责解密。
        """
        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            return None

        # 获取加密的 Cookie（存储为 JSON 字符串）
        cookies_str = self.account_repository.get_cookies(db_account)

        if not cookies_str:
            return None

        cookies = self._parse_cookies(cookies_str)
        if cookies:
            logger.debug("账号 %s 使用数据库 Cookie", account.username)

        return cookies

    def _get_config_cookies(
        self,
        account: HifitiAccountConfig,
    ) -> dict[str, str] | None:
        """
        获取配置文件中的 Cookie（优先级次之）。

        配置文件中的 Cookie 存储为字符串，需要反序列化。
        """
        if not account.cookies:
            return None

        cookies = self._parse_cookies(account.cookies)
        if cookies:
            logger.debug("账号 %s 使用配置文件 Cookie", account.username)

        return cookies

    def _login_with_password(
        self,
        account: HifitiAccountConfig,
        db_account: Account | None = None,
    ) -> dict[str, str] | None:
        """
        通过用户名密码登录 Hifiti（优先级最低）。

        密码优先级：
        1. 数据库中的密码（优先）
        2. 配置文件中的密码

        Args:
            account: 账号配置
            db_account: 数据库账号对象（可选）

        Returns:
            登录成功返回 Cookie 字典，失败返回 None。
        """
        password = None

        # 1. 优先使用数据库中的密码
        if db_account is not None:
            password = self.account_repository.get_passwd(db_account)
            if password:
                logger.debug(
                    "账号 %s 使用数据库密码登录",
                    account.username,
                )

        # 2. 如果数据库中没有密码，使用配置文件中的密码
        if not password and account.passwd and account.passwd.strip():
            password = account.passwd.strip()
            logger.debug(
                "账号 %s 使用配置文件密码登录",
                account.username,
            )

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

        try:
            login_response = self.api.login(account.username, password)

            # 使用 Parser 解析登录结果
            login_result = self.parser.parse_login(login_response)

            if not login_result.success:
                logger.error(
                    "Hifiti 登录失败: username=%s, error=%s",
                    account.username,
                    login_result.error,
                )
                return None

            # 从解析结果中获取 Cookie
            cookies = login_result.cookies

            if not cookies:
                logger.error(
                    "Hifiti 登录失败: username=%s, 未获取到 Cookie",
                    account.username,
                )
                return None

            logger.info(
                "Hifiti 登录成功: username=%s",
                account.username,
            )

            return cookies

        except Exception:
            logger.exception(
                "Hifiti 登录异常: username=%s",
                account.username,
            )
            return None

    # ====================================================================
    # Cookie 保存
    # ====================================================================

    def _save_cookies(
        self,
        account: HifitiAccountConfig,
        cookies: dict[str, str],
        db_account: Account | None = None,
    ) -> None:
        """
        保存当前验证成功的 Cookie 和密码。

        Args:
            account: 账号配置
            cookies: 验证成功的 Cookie 字典
            db_account: 数据库账号对象（可选，避免重复查询）
        """
        import json

        cookies_str = json.dumps(cookies)

        if db_account is None:
            db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            # 创建账号时，优先使用配置文件密码
            self.account_repository.create(
                username=account.username,
                passwd=account.passwd if account.passwd else None,
                cookies=cookies_str,
            )
            return

        # 更新 Cookie（总是更新）
        self.account_repository.update_cookies(db_account, cookies_str)

        # 更新密码：只有当配置文件中的密码与数据库中的密码不同时才更新
        if account.passwd:
            db_passwd = self.account_repository.get_passwd(db_account)
            if db_passwd != account.passwd:
                self.account_repository.update_passwd(db_account, account.passwd)
                logger.debug(
                    "账号 %s 密码已更新（配置文件 → 数据库）",
                    account.username,
                )

    # ====================================================================
    # Checkin (签到)
    # ====================================================================

    @authenticated
    def _checkin(self) -> HifitiCheckinResult:
        """
        执行当前 Hifiti 账号签到。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        签到结果同时同步到数据库。

        业务逻辑：
            1. 检查数据库签到记录（last_checkin_at）
            2. 如果数据库记录显示今日已签到，直接返回
            3. 否则调用 API 执行签到
            4. 调用 Parser 解析签到结果
            5. 处理三种情况：
               a. 签到成功：更新金币（数据库金币 + 获得金币），更新连续签到
               b. 远程已签到：只更新 last_checkin_at，不更新金币
               c. 签到失败：记录错误
            6. 创建签到日志
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Hifiti 账号")

        logger.info("开始 Hifiti 签到: username=%s", account.username)

        # ================================================================
        # 获取数据库账号
        # ================================================================

        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            logger.error("数据库账号不存在: username=%s", account.username)
            return HifitiCheckinResult.failure("数据库账号不存在")

        # ================================================================
        # 检查今日是否已签到（数据库记录）
        # ================================================================

        today_local = now_local()

        if db_account.last_checkin_at is not None:
            last_checkin_local = utc_to_local(db_account.last_checkin_at)
            if last_checkin_local.date() == today_local.date():
                logger.info("账号今日已签到（数据库记录），返回已签到结果")
                return HifitiCheckinResult(success=True)

        # ================================================================
        # 执行签到
        # ================================================================

        logger.info("账号 %s 开始执行签到", account.username)

        try:
            response = self.api.checkin()
            result = self.parser.parse_checkin(response)

            if not result.success:
                # 签到失败处理
                self._handle_checkin_failure(db_account, result.error or "签到失败")
                self.session.commit()
                return result

            # ================================================================
            # 情况1: 远程已签到
            # ================================================================
            if result.already_checked:
                logger.info(
                    "账号 %s 远程已签到，同步签到状态到数据库",
                    account.username,
                )
                # 只更新签到时间，不更新金币
                db_account.last_checkin_at = now_utc()
                # 重置错误状态
                db_account.is_valid = True
                db_account.error_count = 0
                db_account.last_error_at = None
                self.account_repository.update(db_account)

                # 创建签到日志（标记为已签到）
                self.checkin_log_repository.create(
                    account_id=db_account.id,
                    success=True,
                    checkin_gold=0,
                    checkin_rank=0,
                    message="远程已签到（同步状态）",
                    checkin_at=now_utc(),
                )

                self.session.commit()
                return result

            # ================================================================
            # 情况2: 签到成功
            # ================================================================
            logger.info(
                "Hifiti 签到成功: username=%s, checkin_gold=%d, rank=%d",
                account.username,
                result.checkin_gold,
                result.rank,
            )

            # 在数据库金币基础上加上本次获得的金币
            db_account.gold += result.checkin_gold

            # 计算连续签到天数
            last_checkin_utc = db_account.last_checkin_at
            checkin_utc = now_utc()
            checkin_local = utc_to_local(checkin_utc)

            if last_checkin_utc is not None:
                last_checkin_local = utc_to_local(last_checkin_utc)
                day_diff = (checkin_local.date() - last_checkin_local.date()).days

                if day_diff <= 1:
                    db_account.streak_days += 1
                else:
                    db_account.streak_days = 1
            else:
                db_account.streak_days = 1

            db_account.total_days += 1
            db_account.last_checkin_at = checkin_utc

            # 签到成功，重置错误状态
            db_account.is_valid = True
            db_account.error_count = 0
            db_account.last_error_at = None

            logger.info(
                "签到数据更新: 金币 +%d = %d, 连续签到 %d 天，总签到 %d 天",
                result.checkin_gold,
                db_account.gold,
                db_account.streak_days,
                db_account.total_days,
            )

            # 保存到数据库
            self.account_repository.update(db_account)

            # 创建签到日志
            self.checkin_log_repository.create(
                account_id=db_account.id,
                success=True,
                checkin_gold=result.checkin_gold,
                checkin_rank=result.rank,
                message=result.message or "签到成功",
                checkin_at=checkin_utc,
            )

            self.session.commit()
            return result

        except Exception as e:
            logger.exception("Hifiti 签到异常: username=%s", account.username)
            self._handle_checkin_failure(db_account, str(e) or "签到异常")
            self.session.commit()
            return HifitiCheckinResult.failure("签到异常")

    def _handle_checkin_failure(
        self,
        db_account: Account,
        error_message: str,
    ) -> None:
        """
        处理签到失败（私有辅助方法）

        Args:
            db_account: 数据库账号对象
            error_message: 错误信息
        """

        # 更新错误状态
        db_account.error_count += 1
        db_account.last_error_at = now_utc()

        # 如果错误次数过多，标记为无效
        if db_account.error_count >= 5:
            db_account.is_valid = False
            logger.warning(
                "账号 %s 签到失败次数过多 (%d 次)，已标记为无效",
                db_account.username,
                db_account.error_count,
            )

        self.account_repository.update(db_account)

        # 创建失败日志
        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=False,
            checkin_gold=0,
            checkin_rank=0,
            message=error_message,
            checkin_at=now_utc(),
        )

        logger.warning(
            "❌ 签到失败: username=%s, error=%s, error_count=%d",
            db_account.username,
            error_message,
            db_account.error_count,
        )

    def checkin(self, username: str) -> HifitiCheckinResult:
        """指定账号执行 Hifiti 签到。"""

        account = next(
            (
                account
                for account in self.hifiti_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error("未找到 Hifiti 账号: username=%s", username)
            return HifitiCheckinResult.failure(f"未找到账号: {username}")

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            result = self._checkin()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def checkin_all(self) -> dict[str, HifitiCheckinResult | None]:
        """
        遍历全部 Hifiti 账号执行签到。

        Returns:
            字典，key 为用户名，value 为签到结果（失败为 None）。
        """
        results: dict[str, HifitiCheckinResult | None] = {}

        if not self.hifiti_config.accounts:
            logger.warning("没有配置 Hifiti 账号，跳过签到")
            return results

        for account in self.hifiti_config.accounts:
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
    # User Data (用户数据)
    # ====================================================================

    @authenticated
    def _get_user_data(self) -> HifitiUserDataResult | None:
        """
        获取当前 Hifiti 账号的用户数据。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Hifiti 账号")

        logger.info(
            "获取 Hifiti 用户数据: username=%s",
            account.username,
        )

        try:
            response = self.api.get_user_data()
            result = self.parser.parse_user_data(response)

            if not result.success:
                logger.warning(
                    "获取 Hifiti 用户数据失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 Hifiti 用户数据成功: username=%s, gold=%d",
                account.username,
                result.gold,
            )

            # 更新数据库金币
            db_account = self.account_repository.get_by_username(account.username)
            if db_account is not None:
                db_account.gold = result.gold
                self.account_repository.update(db_account)
                self.session.commit()

            return result

        except Exception:
            logger.exception(
                "获取 Hifiti 用户数据异常: username=%s",
                account.username,
            )
            return None

    def get_user_data(self, username: str) -> HifitiUserDataResult | None:
        """获取指定账号的用户数据。"""
        account = next(
            (
                account
                for account in self.hifiti_config.accounts
                if account.username == username
            ),
            None,
        )

        if account is None:
            logger.error("未找到 Hifiti 账号: username=%s", username)
            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            return self._get_user_data()
        finally:
            self._current_account = None

    def get_user_data_all(self) -> dict[str, HifitiUserDataResult | None]:
        """
        获取所有账号的用户数据。
        """
        results: dict[str, HifitiUserDataResult | None] = {}

        if not self.hifiti_config.accounts:
            logger.warning("没有配置 Hifiti 账号，跳过获取用户数据")
            return results

        for account in self.hifiti_config.accounts:
            try:
                result = self.get_user_data(account.username)
                results[account.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 获取用户数据异常: ",
                    account.username,
                )
                results[account.username] = None

        self.session.commit()
        return results

    # ====================================================================
    # 报告
    # ====================================================================

    def build_report_html(self) -> str:
        """构建 Hifiti HTML 运行报告。"""

        app = AppConfig(
            name="Hifiti",
            icon="💎",
            gradient_start="#667eea",
            gradient_end="#764ba2",
        )

        accounts: list[AccountInfo] = []
        checkin: list[CheckinResult] = []

        account_configs = self.hifiti_config.accounts

        if not account_configs:
            logger.warning("没有配置 Hifiti 账号，跳过报告统计")
        else:
            for account_config in account_configs:
                username = account_config.username

                try:
                    db_account = self.account_repository.get_by_username(username)

                    if db_account is None:
                        logger.warning("账号 %s 不存在，跳过报告统计", username)
                        continue

                    accounts.append(
                        AccountInfo(
                            username=db_account.username,
                            gold=db_account.gold,
                            continuous_checkin_days=db_account.streak_days,
                            total_checkin_days=db_account.total_days,
                            error_count=db_account.error_count,
                            last_error_at=db_account.last_error_at,
                        )
                    )

                    # 最近一次签到
                    checkin_log = self.checkin_log_repository.get_latest_by_account_id(
                        db_account.id
                    )

                    if checkin_log is not None:
                        checkin.append(
                            CheckinResult(
                                username=db_account.username,
                                success=checkin_log.success,
                                checkin_gold=checkin_log.checkin_gold,
                                checkin_rank=checkin_log.checkin_rank,
                                message=checkin_log.message or "",
                                created_at=checkin_log.checkin_at,
                            )
                        )

                except Exception:
                    logger.exception(
                        "账号 %s 统计报告信息异常",
                        username,
                    )

        report_data = ReportData(
            app=app,
            accounts=accounts,
            checkin=checkin,
        )

        sections = SectionBuilder.build(report_data)

        renderer = ReportRenderer(
            app_name=app.name,
            app_icon=app.icon,
            gradient_start=app.gradient_start,
            gradient_end=app.gradient_end,
        )

        return renderer.render(sections)


__all__ = [
    "HifitiClient",
    "authenticated",
]
