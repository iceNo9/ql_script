# modules/baiyefee/core/baiyefee.py

from collections.abc import Callable
from datetime import datetime
from functools import wraps  # 添加这行
from typing import Any, TypeVar

from apps.baiyefee.core.api import (
    BaiyefeeAPI,
    BaiyefeeAPIError,
)
from apps.baiyefee.core.config import BaiyefeeAccountConfig, BaiyefeeConfig
from apps.baiyefee.core.notify_builder import SectionBuilder
from apps.baiyefee.core.notify_dto import (
    AccountInfo,
    AppConfig,
    CheckinResult,
    ReportData,
)
from apps.baiyefee.core.parser import (
    BaiyefeeCheckinResult,
    BaiyefeeParser,
    BaiyefeeSignInfoResult,
    BaiyefeeUserDataResult,
)
from apps.baiyefee.core.repositories import (
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
    local_to_utc,
    now_local,
    now_utc,
    parse_local_datetime,
    utc_to_local,
)

logger = get_logger(name="baiyefee_server", log_dir=logs(), fmt_type="detailed")

T = TypeVar("T")


def authenticated(func: Callable[..., T]) -> Callable[..., T]:
    """
    Baiyefee API 认证装饰器。

    按照以下优先级逐级尝试认证：

    1. 数据库 Token
    2. 配置文件 Token
    3. 数据库密码（优先）→ 配置文件密码
    """

    @wraps(func)
    def wrapper(self: "BaiyefeeClient", *args: Any, **kwargs: Any) -> T:
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Baiyefee 账号")

        # 获取数据库账号（用于获取数据库中的密码）
        db_account = self.account_repository.get_by_username(account.username)

        auth_methods = (
            self._get_database_token,
            self._get_config_token,
            self._login_with_password,
        )

        last_error: BaiyefeeAPIError | None = None

        for auth_method in auth_methods:
            try:
                # 对于密码登录，传入 db_account 以便优先使用数据库密码
                if auth_method == self._login_with_password:
                    token = auth_method(account, db_account)
                else:
                    token = auth_method(account)

                if not token:
                    continue

                self.api.set_token(token)

                result = func(self, *args, **kwargs)

                # 保存成功的 Token 和密码
                self._save_token(account, token, db_account)

                return result

            except BaiyefeeAPIError as exc:
                last_error = exc
                logger.warning(
                    "账号 %s 当前认证方式失败，尝试下一层认证",
                    account.username,
                )

        if last_error is not None:
            raise last_error

        raise BaiyefeeAPIError(
            status_code=0,
            message="所有认证方式均不可用",
        )

    return wrapper


class BaiyefeeClient:
    def __init__(
        self,
        global_config: GlobalConfig,
        baiyefee_config: BaiyefeeConfig,
    ):
        """
        初始化 Baiyefee 客户端。

        Args:
            global_config: 全局配置
            baiyefee_config: Baiyefee 配置
        """
        self.global_config = global_config
        self.baiyefee_config = baiyefee_config

        # ================================================================
        # 当前账号
        # ================================================================

        self._current_account: BaiyefeeAccountConfig | None = None

        # ================================================================
        # 基础资源
        # ================================================================

        self.session = get_session()
        self.crypto = Crypto(baiyefee_config.encryption_key)

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
        # Baiyefee API / Parser
        # ================================================================

        self.api = BaiyefeeAPI(self.request_client)
        self.parser = BaiyefeeParser()

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
        account: BaiyefeeAccountConfig,
    ) -> Account:
        """获取数据库账号，不存在则创建。"""

        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 Baiyefee 账号，创建账号: username=%s",
            account.username,
        )

        return self.account_repository.create(
            username=account.username,
        )

    # ====================================================================
    # Authentication
    # ====================================================================

    def _get_database_token(
        self,
        account: BaiyefeeAccountConfig,
    ) -> str | None:
        """
        获取数据库中的 Token。

        数据库中的 Token 为加密存储，
        Repository 负责解密。
        """
        db_account = self.account_repository.get_by_username(
            account.username,
        )

        if db_account is None:
            return None

        # 获取加密的 Token
        token = self.account_repository.get_token(db_account)

        if not token:
            return None

        return token

    def _get_config_token(
        self,
        account: BaiyefeeAccountConfig,
    ) -> str | None:
        """获取配置文件中的 Token。"""
        if not account.token or not account.token.strip():
            return None
        return account.token.strip()

    def _login_with_password(
        self,
        account: BaiyefeeAccountConfig,
        db_account: Account | None = None,
    ) -> str | None:
        """
        通过用户名密码登录 Baiyefee。

        密码优先级：
        1. 数据库中的密码（优先）
        2. 配置文件中的密码

        Args:
            account: 账号配置
            db_account: 数据库账号对象（可选）

        Returns:
            登录成功返回 Token，失败返回 None。
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
            "开始通过用户名密码登录 Baiyefee: username=%s",
            account.username,
        )

        try:
            login_response = self.api.login(account.username, password)
            login_result = self.parser.parse_login(login_response)

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

        except Exception:
            logger.exception(
                "Baiyefee 登录异常: username=%s",
                account.username,
            )
            return None

    # ====================================================================
    # Token
    # ====================================================================

    def _save_token(
        self,
        account: BaiyefeeAccountConfig,
        token: str,
        db_account: Account | None = None,
    ) -> None:
        """
        保存当前验证成功的 Token 和密码。

        Args:
            account: 账号配置
            token: 验证成功的 Token
            db_account: 数据库账号对象（可选，避免重复查询）
        """
        if db_account is None:
            db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            # 创建账号时，优先使用配置文件密码
            # 如果配置文件没有密码，但登录成功说明密码在数据库或配置中
            # 此时密码可能来自数据库，但新创建账号时数据库还没有密码
            # 所以使用配置文件的密码（如果有）
            self.account_repository.create(
                username=account.username,
                passwd=account.passwd if account.passwd else None,
                token=token,
            )
            return

        # 更新 Token（总是更新）
        self.account_repository.update_token(db_account, token)

        # 更新密码：只有当配置文件中的密码与数据库中的密码不同时才更新
        # 这样可以保持数据库密码是最新的
        if account.passwd:
            db_passwd = self.account_repository.get_passwd(db_account)
            if db_passwd != account.passwd:
                self.account_repository.update_passwd(db_account, account.passwd)
                logger.debug(
                    "账号 %s 密码已更新（配置文件 → 数据库）",
                    account.username,
                )

    # ====================================================================
    # Sign Info (签到信息)
    # ====================================================================

    @authenticated
    def _get_sign_info(self) -> BaiyefeeSignInfoResult | None:
        """
        获取当前 Baiyefee 账号的签到信息。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Baiyefee 账号")

        logger.info(
            "获取 Baiyefee 签到信息: username=%s",
            account.username,
        )

        try:
            response = self.api.get_sign_info()
            result = self.parser.parse_sign_info(response)

            if not result.success:
                logger.warning(
                    "获取 Baiyefee 签到信息失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 Baiyefee 签到信息成功: username=%s, can_checkin=%s, checkin_points=%d, points=%d",
                account.username,
                result.can_checkin,
                result.checkin_points,
                result.points,
            )

            return result

        except Exception:
            logger.exception(
                "获取 Baiyefee 签到信息异常: username=%s",
                account.username,
            )
            return None

    def get_sign_info(self, username: str) -> BaiyefeeSignInfoResult | None:
        """
        获取指定账号的签到信息。

        Args:
            username: 用户名
        """
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
            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            result = self._get_sign_info()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def get_sign_info_all(self) -> dict[str, BaiyefeeSignInfoResult | None]:
        """
        获取所有账号的签到信息。
        """
        results: dict[str, BaiyefeeSignInfoResult | None] = {}

        if not self.baiyefee_config.accounts:
            logger.warning("没有配置 Baiyefee 账号，跳过获取签到信息")
            return results

        for account in self.baiyefee_config.accounts:
            try:
                result = self.get_sign_info(account.username)
                results[account.username] = result
            except Exception:
                logger.exception(
                    "账号 %s 获取签到信息异常: ",
                    account.username,
                )
                results[account.username] = None

        self.session.commit()
        return results

    # ====================================================================
    # Checkin (签到)
    # ====================================================================

    @authenticated
    def _checkin(self) -> BaiyefeeCheckinResult:
        """
        执行当前 Baiyefee 账号签到。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        签到结果同时同步到数据库。

        业务逻辑（由 Server 层负责）：
            1. 检查数据库签到记录（last_checkin_at）
            2. 如果数据库记录显示今日已签到，直接返回
            3. 否则调用 _get_sign_info 查询远程状态
            4. 如果远程显示已签到，同步数据到数据库（更新积分、签到记录）
            5. 如果远程显示未签到，调用 API 执行签到
            6. 调用 Repository 更新签到结果（含连续签到计算）
            7. 创建签到日志
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Baiyefee 账号")

        logger.info("开始 Baiyefee 签到: username=%s", account.username)

        # ================================================================
        # 获取数据库账号
        # ================================================================

        db_account = self.account_repository.get_by_username(account.username)

        if db_account is None:
            logger.error("数据库账号不存在: username=%s", account.username)
            return BaiyefeeCheckinResult.failure("数据库账号不存在")

        # ================================================================
        # 检查今日是否已签到
        # ================================================================

        today_local = now_local()

        if db_account.last_checkin_at is not None:
            last_checkin_local = utc_to_local(db_account.last_checkin_at)
            if last_checkin_local.date() == today_local.date():
                logger.info("账号今日已签到，返回已签到结果")
                return BaiyefeeCheckinResult(success=True)

        # ================================================================
        # 查询远程签到状态
        # ================================================================

        sign_info = self._get_sign_info()

        # 如果远程已签到，同步数据
        if sign_info is not None and not sign_info.can_checkin:
            logger.info("账号 %s 远程已签到，同步数据到数据库", account.username)

            # 同步数据
            self._update_account_checkin_data(
                db_account=db_account,
                checkin_points=sign_info.checkin_points,
                total_points=sign_info.points,
                checkin_local=parse_local_datetime(sign_info.local_date),
                message="远程已签到（同步数据）",
            )

            self.session.commit()
            return BaiyefeeCheckinResult(success=True)

        # ================================================================
        # 执行签到
        # ================================================================

        logger.info("账号 %s 远程可签到，开始执行签到", account.username)

        try:
            response = self.api.checkin()
            result = self.parser.parse_checkin(response)

            if not result.success:
                # 签到失败处理
                self._handle_checkin_failure(db_account, result.error or "签到失败")
                self.session.commit()
                return result

            # 签到成功，更新数据
            logger.info(
                "Baiyefee 签到成功: username=%s, checkin_points=%d, points=%d",
                account.username,
                result.checkin_points,
                result.points,
            )

            self._update_account_checkin_data(
                db_account=db_account,
                checkin_points=result.checkin_points,
                total_points=result.points,
                checkin_local=parse_local_datetime(result.local_date),
                message="签到成功",
            )

            self.session.commit()
            return result

        except Exception as e:
            logger.exception("Baiyefee 签到异常: username=%s", account.username)
            self._handle_checkin_failure(db_account, str(e) or "签到异常")
            self.session.commit()
            return BaiyefeeCheckinResult.failure("签到异常")

    def _update_account_checkin_data(
        self,
        db_account: Account,
        checkin_points: int,
        total_points: int,
        checkin_local: datetime,
        message: str,
    ) -> None:
        """
        更新账号签到数据（私有辅助方法）

        Args:
            db_account: 数据库账号对象
            checkin_points: 本次签到获得的积分
            total_points: 当前总积分
            checkin_local: 签到时间（本地时间）
            message: 签到日志消息
        """
        checkin_utc = local_to_utc(checkin_local)

        # ================================================================
        # 更新积分
        # ================================================================

        if total_points > 0:
            db_account.points = total_points

        # ================================================================
        # 计算连续签到天数
        # ================================================================

        # 获取上次签到时间（注意：update 前保存旧值）
        last_checkin_utc = db_account.last_checkin_at

        if last_checkin_utc is not None:
            last_checkin_local = utc_to_local(last_checkin_utc)
            day_diff = (checkin_local.date() - last_checkin_local.date()).days

            if day_diff <= 1:
                # 昨天或今天签到过，连续签到 +1
                db_account.streak_days += 1
            else:
                # 前天或更早，连续签到中断，重置为 1
                db_account.streak_days = 1
        else:
            # 首次签到
            db_account.streak_days = 1

        db_account.total_days += 1
        db_account.last_checkin_at = checkin_utc

        # 签到成功，重置错误状态
        db_account.is_valid = True
        db_account.error_count = 0
        db_account.last_error_at = None

        logger.info(
            "签到数据更新: 连续签到 %d 天，总签到 %d 天，总积分 %d",
            db_account.streak_days,
            db_account.total_days,
            db_account.points,
        )

        # 保存到数据库
        self.account_repository.update(db_account)

        # ================================================================
        # 创建签到日志
        # ================================================================

        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=True,
            checkin_points=checkin_points,
            message=message,
            checkin_at=checkin_utc,
        )

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
            checkin_points=0,
            message=error_message,
            checkin_at=db_account.last,
        )

        logger.warning(
            "❌ 签到失败: username=%s, error=%s, error_count=%d",
            db_account.username,
            error_message,
            db_account.error_count,
        )

    def checkin(self, username: str) -> BaiyefeeCheckinResult:
        """指定账号执行 Baiyefee 签到。"""

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
            return BaiyefeeCheckinResult.failure(f"未找到账号: {username}")

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            result = self._checkin()
            self.session.commit()
            return result
        finally:
            self._current_account = None

    def checkin_all(self) -> dict[str, BaiyefeeCheckinResult | None]:
        """
        遍历全部 Baiyefee 账号执行签到。

        Returns:
            字典，key 为用户名，value 为签到结果（失败为 None）。
        """
        results: dict[str, BaiyefeeCheckinResult | None] = {}

        if not self.baiyefee_config.accounts:
            logger.warning("没有配置 Baiyefee 账号，跳过签到")
            return results

        for account in self.baiyefee_config.accounts:
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
    def _get_user_data(self) -> BaiyefeeUserDataResult | None:
        """
        获取当前 Baiyefee 账号的用户数据。

        当前账号由 `_current_account` 提供。
        认证由 `authenticated` 装饰器负责。
        """
        account = self._current_account

        if account is None:
            raise RuntimeError("当前没有选择 Baiyefee 账号")

        logger.info(
            "获取 Baiyefee 用户数据: username=%s",
            account.username,
        )

        try:
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

            # 更新数据库积分
            db_account = self.account_repository.get_by_username(account.username)
            if db_account is not None:
                db_account.points = result.points
                self.account_repository.update(db_account)
                self.session.commit()

            return result

        except Exception:
            logger.exception(
                "获取 Baiyefee 用户数据异常: username=%s",
                account.username,
            )
            return None

    def get_user_data(self, username: str) -> BaiyefeeUserDataResult | None:
        """获取指定账号的用户数据。"""
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
            return None

        self._current_account = account

        try:
            self._get_or_create_db_account(account)
            return self._get_user_data()
        finally:
            self._current_account = None

    def get_user_data_all(self) -> dict[str, BaiyefeeUserDataResult | None]:
        """
        获取所有账号的用户数据。
        """
        results: dict[str, BaiyefeeUserDataResult | None] = {}

        if not self.baiyefee_config.accounts:
            logger.warning("没有配置 Baiyefee 账号，跳过获取用户数据")
            return results

        for account in self.baiyefee_config.accounts:
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
        """构建 Baiyefee HTML 运行报告。"""

        app = AppConfig(
            name="Baiyefee",
            icon="📦",
            gradient_start="#667eea",
            gradient_end="#764ba2",
        )

        accounts: list[AccountInfo] = []
        checkin: list[CheckinResult] = []

        account_configs = self.baiyefee_config.accounts

        if not account_configs:
            logger.warning("没有配置 Baiyefee 账号，跳过报告统计")
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
                            points=db_account.points,
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
                                checkin_points=checkin_log.checkin_points,
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
