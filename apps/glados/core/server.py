# modules/glados/core/glados.py
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
from apps.glados.core.parser import GladosParser, GladosCheckinResult
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
from utils.request_client import RequestClient

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
                    account.email_user,
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

        db_account = self.account_repository.get_by_email(
            account.email_user,
        )

        if db_account is not None:
            return db_account

        logger.info(
            "数据库中不存在 GLaDOS 账号，创建账号: username=%s",
            account.email_user,
        )

        return self.account_repository.create(
            email=account.email_user,
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
        db_account = self.account_repository.get_by_email(
            account.email_user,
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
            account.email_user,
        )

        # ================================================================
        # 请求登录验证码
        # ================================================================

        auth_response = self.api.authorization(
            account.email_user,
        )

        auth_result = self.parser.parse_authorization(
            auth_response,
        )

        if not auth_result.success:
            logger.error(
                "请求 GLaDOS 登录验证码失败: username=%s, error=%s",
                account.email_user,
                auth_result.error,
            )
            return None

        # ================================================================
        # 等待登录验证码
        # ================================================================

        logger.info(
            "等待 GLaDOS 登录验证码: username=%s",
            account.email_user,
        )

        login_code = email_tool.wait_login_code(
            account.email_user,
            timeout=600,
            interval=10,
        )

        if login_code is None:
            logger.error(
                "获取 GLaDOS 登录验证码失败: username=%s",
                account.email_user,
            )
            return None

        # ================================================================
        # 验证验证码归属用户
        # ================================================================

        if login_code.user != account.email_user:
            logger.error(
                "验证码归属用户不符合登录用户: expected=%s, actual=%s",
                account.email_user,
                login_code.user,
            )
            return None

        # ================================================================
        # 登录
        # ================================================================

        login_response = self.api.login(
            account.email_user,
            login_code.code,
        )

        login_result = self.parser.parse_login(
            login_response,
        )

        if not login_result.success:
            logger.error(
                "GLaDOS 邮箱登录失败: username=%s, error=%s",
                account.email_user,
                login_result.error,
            )
            return None

        cookies = login_result.cookies

        if not cookies:
            logger.error(
                "GLaDOS 登录成功，但未获取到 Cookie: username=%s",
                account.email_user,
            )
            return None

        logger.info(
            "GLaDOS 邮箱登录成功: username=%s",
            account.email_user,
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

        db_account = self.account_repository.get_by_email(
            account.email_user,
        )

        # 将字典转为 JSON 字符串
        cookies_str = json.dumps(cookies)

        if db_account is None:
            self.account_repository.create(
                email=account.email_user,
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
            account.email_user,
        )

        # ================================================================
        # 获取数据库账号
        # ================================================================

        db_account = self.account_repository.get_by_email(account.email_user)

        # ================================================================
        # 检查是否已签到（防止重复签到）
        # ================================================================

        today_success_count = self.checkin_log_repository.get_success_count_today(
            db_account.id
        )

        if today_success_count > 0:
            logger.info(
                "GLaDOS 今日已签到: username=%s, success_count=%d",
                account.email_user,
                today_success_count,
            )

            # 获取最新的签到结果用于返回
            recent_logs = self.checkin_log_repository.get_by_account_id(
                db_account.id,
                limit=1,
            )

            if recent_logs:
                last_log = recent_logs[0]
                return GladosCheckinResult(
                    success=True,
                    already_checked=True,
                    message=last_log.message or "今日已签到",
                    points=0,  # 无法从日志中获取 points
                    streak=0,  # 无法从日志中获取 streak
                    error=None,
                )

            # 如果日志不存在（理论上不可能），返回一个默认结果
            return GladosCheckinResult(
                success=True,
                already_checked=True,
                message="今日已签到",
                points=0,
                streak=0,
                error=None,
            )

        # ================================================================
        # 执行签到
        # ================================================================

        response = self.api.checkin()

        result = self.parser.parse_checkin(response)

        # ================================================================
        # 日志
        # ================================================================

        if result.success:
            if result.already_checked:
                logger.info(
                    "GLaDOS 今日已签到: username=%s, points=%d, streak=%d",
                    account.email_user,
                    result.points,
                    result.streak,
                )
            else:
                logger.info(
                    "GLaDOS 签到成功: username=%s, points=%d, streak=%d",
                    account.email_user,
                    result.points,
                    result.streak,
                )
        else:
            logger.warning(
                "GLaDOS 签到失败: username=%s, error=%s",
                account.email_user,
                result.error,
            )

        # ================================================================
        # 数据库更新
        # ================================================================

        self.account_repository.update_checkin_result(
            account_id=db_account.id,
            success=result.success,
            message=result.message,
            error=result.error,
        )

        self.checkin_log_repository.create(
            account_id=db_account.id,
            success=result.success,
            message=result.message if result.success else result.error,
        )

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
                if account.email_user == username
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
            return self._checkin()
        finally:
            self._current_account = None

    def checkin_all(self) -> list[GladosCheckinResult]:
        """遍历全部 GLaDOS 账号执行签到。"""

        results: list[GladosCheckinResult] = []

        if not self.glados_config.accounts:
            logger.warning("没有配置 GLaDOS 账号，跳过签到")
            return results

        for account in self.glados_config.accounts:
            self._current_account = account

            try:
                self._get_or_create_db_account(account)
                results.append(self._checkin())
            finally:
                self._current_account = None

        return results

        # email_tool = EmailTool()
        # api = GladosAPI()

        # # 从配置中提取用户名列表
        # self.usernames = [acc.username for acc in glados_config.accounts]

        # self.client = RequestClient(proxies=global_config.proxy, max_retries=2)
        # self.server = GladosServer(self.client)
        # self.email_extractor = EmailCodeExtractor(global_config.email)

        # # 操作结果（用于通知）
        # self._checkin_results: List[GladosCheckinResult] = []
        # self._code_results: List[CodeResult] = []
        # self._redeem_results: List[RedeemResult] = []
        # self._account_infos: List[AccountInfo] = []


#     # -------------------------------
#     # 数据库缓存操作
#     # -------------------------------

#     def _update_db_user_from_status(
#         self, username: str, status_result: GladosStatusResult, cookies: Dict = None
#     ):
#         """从状态结果更新数据库用户信息"""
#         db_user = get(username)
#         if db_user is None:
#             db_user = GladosUser(username=username)

#         db_user.vip_level = status_result.vip
#         db_user.remaining_days = int(status_result.left_days)
#         db_user.used_traffic_kb = status_result.traffic
#         db_user.last_check_at = int(time.time())

#         if cookies:
#             db_user.cookies = cookies

#         save(db_user)
#         return db_user

#     def _mark_cookies_invalid(self, username: str):
#         """标记 cookies 无效"""
#         db_user = get(username)
#         if db_user:
#             db_user.cookies_valid = False
#             db_user.cookies_expire_at = 0
#             db_user.last_check_at = int(time.time())
#             save(db_user)
#             logger.debug(f"[缓存] 账户 {username} cookies 已标记为无效")

#     def _mark_cookies_valid(self, username: str, cookies: Dict):
#         """标记 cookies 有效"""
#         db_user = get(username)
#         if db_user is None:
#             db_user = GladosUser(username=username)

#         db_user.cookies = cookies
#         db_user.cookies_valid = True
#         db_user.cookies_expire_at = int(time.time() + CACHE_COOKIES_VALID_SECONDS)
#         db_user.last_check_at = int(time.time())
#         save(db_user)
#         logger.debug(
#             f"[缓存] 账户 {username} cookies 已标记为有效，有效期 {CACHE_COOKIES_VALID_HOURS} 小时"
#         )

#     # -------------------------------
#     # 登录相关
#     # -------------------------------

#     def _check_login(self, username: str) -> bool:
#         """检查登录状态（优先使用数据库缓存标记）"""
#         current_time = int(time.time())

#         # 1. 从数据库获取缓存状态
#         db_user = get(username)

#         # 2. 检查缓存标记是否有效
#         if db_user and db_user.cookies_valid:
#             if db_user.cookies_expire_at > current_time:
#                 logger.debug(f"[缓存] 账户 {username} cookies 标记有效，直接使用")
#                 if db_user.cookies:
#                     self.server.update_cookies(db_user.cookies)
#                 return True
#             else:
#                 logger.debug(f"[缓存] 账户 {username} cookies 标记已过期")

#         # 3. 缓存无效，请求 API 验证
#         logger.debug(f"[API] 验证账户 {username} cookies 有效性")

#         if db_user and db_user.cookies:
#             self.server.update_cookies(db_user.cookies)
#         else:
#             self.server.clear_cookies()

#         result = self.server.request_status()

#         if not result:
#             logger.error(f"[!] 账户 {username} 登录状态服务异常")
#             return False

#         if result.success:
#             logger.debug(f"[+] 账户 {username} 登录状态正常")
#             self._update_db_user_from_status(
#                 username, result, db_user.cookies if db_user else None
#             )
#             if db_user and db_user.cookies:
#                 self._mark_cookies_valid(username, db_user.cookies)
#             return True
#         else:
#             logger.debug(f"[!] 账户 {username} 登录状态检查失败")
#             self._mark_cookies_invalid(username)
#             return False

#     def login(self, username: str) -> bool:
#         """登录账号（邮箱验证码方式）"""
#         logger.info(f"[*] 开始登录账户 {username}")

#         if self._check_login(username):
#             logger.info(f"[+] 账户 {username} 已有有效登录")
#             return True

#         logger.info(f"[*] 账户 {username} 请求发送验证码")
#         result = self.server.request_authorization(username)
#         if not result or not result.success:
#             logger.error(f"[!] 账户 {username} 请求发送验证码失败")
#             return False

#         code = self.email_extractor.get_login_code(
#             email_address=username, max_wait_minutes=5, check_interval_seconds=10
#         )
#         if not code:
#             logger.error(f"[!] 账户 {username} 获取验证码失败")
#             return False

#         success = self.server.request_login(username, code)
#         if not success:
#             logger.error(f"[!] 账户 {username} 验证码登录失败")
#             return False

#         logger.info(f"[+] 账户 {username} 验证码登录成功")
#         cookies = self.server.get_cookies()

#         status_result = self.server.request_status()
#         if status_result and status_result.success:
#             self._update_db_user_from_status(username, status_result, cookies)
#             self._mark_cookies_valid(username, cookies)
#         else:
#             self._mark_cookies_valid(username, cookies)

#         return True

#     # -------------------------------
#     # 签到
#     # -------------------------------

#     @require_login
#     def _checkin(self, username: str) -> Optional[GladosGladosCheckinResult]:
#         result = self.server.request_checkin()
#         if not result:
#             logger.error(f"[!] 账户 {username} 签到失败, 服务异常")
#             return None

#         if result.success:
#             logger.info(f"[+] 账户 {username} 签到成功，获得 {result.points} 积分")
#             update_sign(username, gained_points=result.points)
#         else:
#             logger.error(f"[!] 账户 {username} 签到失败: {result.message}")
#             if "login" in result.message.lower() or "auth" in result.message.lower():
#                 self._mark_cookies_invalid(username)

#         return result

#     def checkin(self) -> List[GladosCheckinResult]:
#         """执行所有账户签到"""
#         logger.info("[*] 开始执行 GLaDOS 账户签到")
#         results = []

#         for username in self.usernames:
#             logger.info(f"[*] 账户 {username} 开始签到")
#             ret = self._checkin(username)
#             if ret:
#                 result = GladosCheckinResult(
#                     username=username,
#                     success=ret.success,
#                     point=ret.points,
#                     message=ret.message,
#                 )
#                 results.append(result)

#         logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
#         self._checkin_results = results
#         return results

#     # -------------------------------
#     # 积分信息
#     # -------------------------------

#     @require_login
#     def _point(
#         self, username: str, force_refresh: bool = False
#     ) -> Optional[GladosPointResult]:
#         if not force_refresh:
#             db_user = get(username)
#             if db_user and db_user.last_check_at:
#                 if time.time() - db_user.last_check_at < CACHE_POINT_TTL_SECONDS:
#                     logger.debug(f"[缓存] 使用数据库缓存的积分数据: {username}")
#                     return None

#         result = self.server.request_point()
#         if not result:
#             logger.error(f"[!] 账户 {username} 获取积分失败, 服务异常")
#             return None

#         if result.success:
#             logger.debug(f"[+] 账户 {username} 获取积分成功: {result.points}")
#             db_user = get(username)
#             if db_user:
#                 db_user.points = int(result.points)
#                 save(db_user)
#         else:
#             logger.error(f"[!] 账户 {username} 获取积分失败")

#         return result

#     # -------------------------------
#     # 礼品码兑换
#     # -------------------------------

#     @require_login
#     def _code(self, username: str, code: str) -> Optional[GladosCodeResult]:
#         result = self.server.request_code(code)
#         if not result:
#             logger.error(f"[!] 账户 {username} 兑换礼品码失败, 服务异常")
#             return None

#         if result.success:
#             logger.info(f"[+] 账户 {username} 兑换礼品码成功")
#         else:
#             logger.error(f"[!] 账户 {username} 兑换礼品码失败: {result.message}")

#         return result

#     def code(self) -> List[CodeResult]:
#         """
#         兑换礼品码（从邮箱提取）
#         """
#         logger.info("[*] 开始执行 GLaDOS 账户兑换礼品码")
#         results = []

#         # 从邮箱获取有效的礼品码
#         gift_codes = self.email_extractor.get_gift_codes()
#         if not gift_codes:
#             logger.info("[i] 未找到有效的礼品码，跳过兑换")
#             return results

#         for gift in gift_codes:
#             gift_username = gift.get("username")
#             gift_code = gift.get("code")
#             valid_day = gift.get("valid_day", 0)

#             if gift_username not in self.usernames:
#                 logger.info(f"[!] 礼品码归属 {gift_username} 不在账户列表中，跳过")
#                 continue

#             logger.info(f"[*] 账户 {gift_username} 开始兑换礼品码")
#             ret = self._code(gift_username, gift_code)
#             if ret:
#                 result = CodeResult(
#                     username=gift_username,
#                     success=ret.success,
#                     days=int(valid_day) if ret.success else 0,
#                     message=ret.message,
#                 )
#                 results.append(result)

#         logger.info(f"[✓] 礼品码兑换完成，共处理 {len(results)} 个结果")
#         self._code_results = results
#         return results

#     # -------------------------------
#     # 状态信息
#     # -------------------------------

#     @require_login
#     def _status(
#         self, username: str, force_refresh: bool = False
#     ) -> Optional[GladosStatusResult]:
#         if not force_refresh:
#             db_user = get(username)
#             if db_user and db_user.last_check_at:
#                 if time.time() - db_user.last_check_at < CACHE_STATUS_TTL_SECONDS:
#                     logger.debug(f"[缓存] 使用数据库缓存的状态数据: {username}")
#                     if db_user.cookies:
#                         self.server.update_cookies(db_user.cookies)
#                     return None

#         result = self.server.request_status()
#         if not result:
#             logger.error(f"[!] 账户 {username} 获取状态失败, 服务异常")
#             return None

#         if result.success:
#             logger.debug(f"[+] 账户 {username} 获取状态成功")
#             self._update_db_user_from_status(username, result)
#         else:
#             logger.error(f"[!] 账户 {username} 获取状态失败")
#             self._mark_cookies_invalid(username)

#         return result

#     # -------------------------------
#     # 蛋糕兑换
#     # -------------------------------

#     @require_login
#     def _cake(self, username: str) -> Optional[GladosCakesResult]:
#         result = self.server.request_cakes()
#         if not result:
#             logger.error(f"[!] 账户 {username} 获取蛋糕列表失败, 服务异常")
#             return None

#         if result.success:
#             logger.info(
#                 f"[+] 账户 {username} 获取蛋糕列表成功，共 {len(result.available)} 个可用蛋糕"
#             )
#         else:
#             logger.error(f"[!] 账户 {username} 获取蛋糕列表失败")

#         return result

#     @require_login
#     def _redeem_cake(self, username: str, cake_id: int) -> Optional[GladosRedeemResult]:
#         result = self.server.request_redeem(cake_id)
#         if not result:
#             logger.error(f"[!] 账户 {username} 兑换蛋糕失败, 服务异常")
#             return None

#         if result.success:
#             logger.info(f"[+] 账户 {username} 兑换蛋糕成功")
#         else:
#             logger.error(f"[!] 账户 {username} 兑换蛋糕失败: {result.message}")

#         return result

#     def cake(self) -> List[RedeemResult]:
#         """执行所有账户的蛋糕兑换"""
#         logger.info("[*] 开始执行 GLaDOS 蛋糕兑换")
#         results = []

#         for username in self.usernames:
#             status_result = self._status(username)
#             if not status_result:
#                 continue

#             if status_result.cake_count == 0:
#                 logger.info(f"[i] 账户 {username} 没有可用蛋糕")
#                 continue

#             cake_result = self._cake(username)
#             if cake_result and cake_result.success:
#                 for cake in cake_result.available:
#                     ret = self._redeem_cake(username, cake.id)
#                     if ret:
#                         result = RedeemResult(
#                             username=username,
#                             success=ret.success,
#                             amount=cake.amount,
#                             message=ret.message,
#                         )
#                         results.append(result)
#                         logger.info(
#                             f"[+] 账户 {username} 兑换蛋糕 {cake.id}，获得 {cake.amount} 天"
#                         )

#         logger.info(f"[✓] 蛋糕兑换完成，共处理 {len(results)} 个结果")
#         self._redeem_results = results
#         return results

#     # -------------------------------
#     # 积分兑换（基于配置的续费规则）
#     # -------------------------------

#     @require_login
#     def _exchange(
#         self, username: str, plan_type: str
#     ) -> Optional[GladosExchangeResult]:
#         result = self.server.request_exchange(plan_type)
#         if not result:
#             logger.error(f"[!] 账户 {username} 积分兑换失败, 服务异常")
#             return None

#         if result.success:
#             logger.info(
#                 f"[+] 账户 {username} 积分兑换成功: 使用 {result.points_used} 积分获得 {result.days_added} 天"
#             )
#             logger.info(f"[+] 账户 {username} 剩余积分: {result.points_remaining}")

#             db_user = get(username)
#             if db_user:
#                 db_user.points = int(result.points_remaining)
#                 db_user.remaining_days += result.days_added
#                 save(db_user)
#         else:
#             logger.error(f"[!] 账户 {username} 积分兑换失败: {result.message}")

#         return result

#     def exchange(self) -> List[GladosExchangeResult]:
#         """根据配置的续费规则执行积分兑换"""
#         logger.info("[*] 开始根据续费配置执行积分兑换")

#         renewal_rules = self.glados_config.renewals
#         if not renewal_rules:
#             logger.info("[i] 未配置续费规则，跳过兑换")
#             return []

#         results = []

#         for rule in renewal_rules:
#             username = rule.username
#             plan_type = rule.plan_type
#             days_threshold = rule.days_threshold

#             if username not in self.usernames:
#                 logger.warning(f"[!] 续费规则中的账户 {username} 不在账户列表中，跳过")
#                 continue

#             if plan_type not in EXCHANGE_POINTS_MAP:
#                 logger.error(
#                     f"[!] 无效的续费计划: {plan_type}，支持: {list(EXCHANGE_POINTS_MAP.keys())}"
#                 )
#                 continue

#             logger.info(
#                 f"[*] 处理续费规则: 账户 {username}, 计划 {plan_type}, 阈值 {days_threshold} 天"
#             )

#             status = self._status(username)
#             if not status or not status.success:
#                 logger.error(f"[!] 账户 {username} 状态获取失败，跳过续费检查")
#                 continue

#             left_days = status.left_days
#             logger.info(
#                 f"[*] 账户 {username} 剩余天数: {left_days:.1f} 天, 阈值: {days_threshold} 天"
#             )

#             if left_days >= days_threshold:
#                 logger.info(f"[i] 账户 {username} 剩余天数充足，无需续费")
#                 continue

#             logger.info(
#                 f"[!] 账户 {username} 剩余天数 {left_days:.1f} < {days_threshold}，触发续费"
#             )

#             required_points = EXCHANGE_POINTS_MAP[plan_type]

#             point_result = self._point(username)
#             if not point_result or not point_result.success:
#                 logger.error(f"[!] 账户 {username} 积分获取失败，跳过续费")
#                 continue

#             current_points = point_result.points
#             logger.info(
#                 f"[*] 账户 {username} 当前积分: {current_points}, 需要: {required_points}"
#             )

#             if current_points < required_points:
#                 logger.warning(
#                     f"[!] 账户 {username} 积分不足: {current_points} < {required_points}，跳过续费"
#                 )
#                 continue

#             result = self._exchange(username, plan_type)
#             if result and result.success:
#                 results.append(result)

#         logger.info(f"[✓] 续费兑换完成，成功 {len(results)} 笔交易")
#         return results

#     def exchange_by_id(
#         self, username: str, plan_type: str = "plan500"
#     ) -> Optional[GladosExchangeResult]:
#         """
#         根据用户名进行积分兑换

#         Args:
#             username: 用户名（邮箱）
#             plan_type: 兑换计划类型，支持 "plan500", "plan200", "plan100"
#         """
#         logger.info(f"[*] 兑换请求: 账号 {username}, 计划 {plan_type}")

#         if plan_type not in EXCHANGE_POINTS_MAP:
#             logger.error(
#                 f"[!] 无效的兑换计划: {plan_type}, 支持: {list(EXCHANGE_POINTS_MAP.keys())}"
#             )
#             return None

#         if username not in self.usernames:
#             logger.error(f"[!] 未找到账号: {username}")
#             return None

#         # 确保登录状态
#         if not self._check_login(username):
#             if not self.login(username):
#                 logger.error(f"[!] 账号 {username} 登录失败，取消兑换")
#                 return None

#         result = self._exchange(username, plan_type)
#         if result and result.success:
#             logger.info(f"[✓] 兑换成功: 账号 {username} 获得 {result.days_added} 天")
#         else:
#             error_msg = result.message if result else "服务异常"
#             logger.error(f"[✗] 兑换失败: 账号 {username}, 原因: {error_msg}")

#         return result

#     # -------------------------------
#     # 账户信息收集
#     # -------------------------------

#     def collect_account_infos(self) -> List[AccountInfo]:
#         """收集所有账户的信息"""
#         logger.info("[*] 开始收集账户信息")
#         account_infos = []

#         for username in self.usernames:
#             logger.info(f"[*] 获取账户 {username} 信息")

#             status = self._status(username)
#             point = self._point(username)
#             db_user = get(username)

#             if status and status.success and point and point.success:
#                 total_traffic = self.server.get_total_traffic(status.vip)
#                 use_percent = (
#                     (status.traffic / total_traffic * 100) if total_traffic > 0 else 0.0
#                 )

#                 account_info = AccountInfo(
#                     username=username,
#                     points=int(point.points),
#                     left_days=int(status.left_days),
#                     current_traffic=status.traffic,
#                     total_traffic=total_traffic,
#                     use_percent=round(use_percent, 2),
#                 )
#                 account_infos.append(account_info)
#                 logger.info(f"[+] 账户 {username} 信息获取成功")
#             elif db_user:
#                 total_traffic = self.server.get_total_traffic(db_user.vip_level)
#                 use_percent = (
#                     (db_user.used_traffic_kb / total_traffic * 100)
#                     if total_traffic > 0
#                     else 0.0
#                 )

#                 account_info = AccountInfo(
#                     username=username,
#                     points=db_user.points,
#                     left_days=db_user.remaining_days,
#                     current_traffic=db_user.used_traffic_kb,
#                     total_traffic=total_traffic,
#                     use_percent=round(use_percent, 2),
#                 )
#                 account_infos.append(account_info)
#                 logger.info(f"[缓存] 账户 {username} 使用缓存数据")
#             else:
#                 logger.error(f"[!] 账户 {username} 信息获取失败")

#         self._account_infos = account_infos
#         logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
#         return account_infos

#     # -------------------------------
#     # 通知
#     # -------------------------------

#     def get_notifier(self) -> GladosNotifier:
#         """获取通知器实例"""
#         import yagmail

#         try:
#             yagmail.sender.SMTP.__del__ = lambda self: None
#             mail = self.global_config.email
#             smtp = mail.smtp
#             smtp_client = yagmail.SMTP(
#                 user=mail.username,
#                 password=mail.password,
#                 host=smtp.host,
#                 port=smtp.port,
#                 smtp_ssl=smtp.secure,
#             )
#             logger.info("[+] SMTP 客户端登录成功")

#             return GladosNotifier(
#                 smtp_client=smtp_client,
#                 email_to=self.global_config.email_to,
#                 template_path=Path("modules/glados/templates/glados_notification.html"),
#                 checkin_results=self._checkin_results,
#                 code_results=self._code_results,
#                 redeem_results=self._redeem_results,
#                 account_infos=self._account_infos,
#             )
#         except Exception as e:
#             logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
#             raise

#     # -------------------------------
#     # 获取内部结果（用于通知）
#     # -------------------------------

#     @property
#     def checkin_results(self) -> List[GladosCheckinResult]:
#         return self._checkin_results

#     @property
#     def code_results(self) -> List[CodeResult]:
#         return self._code_results

#     @property
#     def redeem_results(self) -> List[RedeemResult]:
#         return self._redeem_results

#     @property
#     def account_infos(self) -> List[AccountInfo]:
#         return self._account_infos


# # ==================== 导出 ====================

# __all__ = [
#     "GladosClient",
# ]
