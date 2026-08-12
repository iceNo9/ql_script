# modules/glados/core/glados.py
import time
from functools import wraps
from typing import Callable, TypeVar, Any, Optional, List, Dict
from pathlib import Path

from utils.log import get_logger
from utils.config import GlobalConfig

from apps.glados.utils.request_client import RequestClient
from apps.glados.core.email import EmailCodeExtractor
from apps.glados.core.table import GladosUser, get, save, update_sign
from apps.glados.core.notify import (
    CheckinResult,
    CodeResult,
    RedeemResult,
    AccountInfo,
    GladosNotifier
)

from apps.glados.core.server import (
    GladosServer,
    GladosPointResult,
    GladosCheckinResult,
    GladosStatusResult,
    GladosCodeResult,
    GladosCakesResult,
    GladosRedeemResult,
    GladosExchangeResult
)

# 导入配置 DTO
from apps.glados.core.config import GladosConfigModel, GladosRenewalConfig

logger = get_logger(__name__)

# ==================== 缓存时间常量（秒） ====================
CACHE_COOKIES_VALID_HOURS = 24
CACHE_COOKIES_VALID_SECONDS = CACHE_COOKIES_VALID_HOURS * 3600
CACHE_STATUS_TTL_SECONDS = 300
CACHE_POINT_TTL_SECONDS = 300

# ==================== 兑换计划映射 ====================
EXCHANGE_POINTS_MAP = {
    "plan100": 100,
    "plan200": 200,
    "plan500": 500,
}


# ==================== 登录检查装饰器 ====================

def require_login(func: Callable) -> Callable:
    """登录检查装饰器，使用数据库缓存标记"""
    @wraps(func)
    def wrapper(self: 'GladosClient', username: str, *args, **kwargs):
        if not self._check_login(username):
            if not self.login(username):
                logger.error(f"[!] 账户 {username} 登录失败，跳过操作")
                return None
        return func(self, username, *args, **kwargs)
    return wrapper


# ==================== GLaDOS 客户端 ====================

class GladosClient:
    def __init__(
        self, 
        global_config: GlobalConfig,
        glados_config: GladosConfigModel,
    ):
        """
        初始化 GLaDOS 客户端
        
        Args:
            global_config: 全局配置
            glados_config: GLaDOS 配置（包含账号列表和续费规则）
        """
        self.global_config = global_config
        self.glados_config = glados_config
        
        # 从配置中提取用户名列表
        self.usernames = [acc.username for acc in glados_config.accounts]

        self.client = RequestClient(proxies=global_config.proxy, max_retries=2)
        self.server = GladosServer(self.client)
        self.email_extractor = EmailCodeExtractor(global_config.email)

        # 操作结果（用于通知）
        self._checkin_results: List[CheckinResult] = []
        self._code_results: List[CodeResult] = []
        self._redeem_results: List[RedeemResult] = []
        self._account_infos: List[AccountInfo] = []

    # -------------------------------
    # 数据库缓存操作
    # -------------------------------
    
    def _update_db_user_from_status(self, username: str, status_result: GladosStatusResult, cookies: Dict = None):
        """从状态结果更新数据库用户信息"""
        db_user = get(username)
        if db_user is None:
            db_user = GladosUser(username=username)
        
        db_user.vip_level = status_result.vip
        db_user.remaining_days = int(status_result.left_days)
        db_user.used_traffic_kb = status_result.traffic
        db_user.last_check_at = int(time.time())
        
        if cookies:
            db_user.cookies = cookies
        
        save(db_user)
        return db_user
    
    def _mark_cookies_invalid(self, username: str):
        """标记 cookies 无效"""
        db_user = get(username)
        if db_user:
            db_user.cookies_valid = False
            db_user.cookies_expire_at = 0
            db_user.last_check_at = int(time.time())
            save(db_user)
            logger.debug(f"[缓存] 账户 {username} cookies 已标记为无效")
    
    def _mark_cookies_valid(self, username: str, cookies: Dict):
        """标记 cookies 有效"""
        db_user = get(username)
        if db_user is None:
            db_user = GladosUser(username=username)
        
        db_user.cookies = cookies
        db_user.cookies_valid = True
        db_user.cookies_expire_at = int(time.time() + CACHE_COOKIES_VALID_SECONDS)
        db_user.last_check_at = int(time.time())
        save(db_user)
        logger.debug(f"[缓存] 账户 {username} cookies 已标记为有效，有效期 {CACHE_COOKIES_VALID_HOURS} 小时")
    
    # -------------------------------
    # 登录相关
    # -------------------------------
    
    def _check_login(self, username: str) -> bool:
        """检查登录状态（优先使用数据库缓存标记）"""
        current_time = int(time.time())
        
        # 1. 从数据库获取缓存状态
        db_user = get(username)
        
        # 2. 检查缓存标记是否有效
        if db_user and db_user.cookies_valid:
            if db_user.cookies_expire_at > current_time:
                logger.debug(f"[缓存] 账户 {username} cookies 标记有效，直接使用")
                if db_user.cookies:
                    self.server.update_cookies(db_user.cookies)
                return True
            else:
                logger.debug(f"[缓存] 账户 {username} cookies 标记已过期")
        
        # 3. 缓存无效，请求 API 验证
        logger.debug(f"[API] 验证账户 {username} cookies 有效性")
        
        if db_user and db_user.cookies:
            self.server.update_cookies(db_user.cookies)
        else:
            self.server.clear_cookies()
        
        result = self.server.request_status()
        
        if not result:
            logger.error(f"[!] 账户 {username} 登录状态服务异常")
            return False
        
        if result.success:
            logger.debug(f"[+] 账户 {username} 登录状态正常")
            self._update_db_user_from_status(username, result, db_user.cookies if db_user else None)
            if db_user and db_user.cookies:
                self._mark_cookies_valid(username, db_user.cookies)
            return True
        else:
            logger.debug(f"[!] 账户 {username} 登录状态检查失败")
            self._mark_cookies_invalid(username)
            return False
    
    def login(self, username: str) -> bool:
        """登录账号（邮箱验证码方式）"""
        logger.info(f"[*] 开始登录账户 {username}")

        if self._check_login(username):
            logger.info(f"[+] 账户 {username} 已有有效登录")
            return True
        
        logger.info(f"[*] 账户 {username} 请求发送验证码")
        result = self.server.request_authorization(username)
        if not result or not result.success:
            logger.error(f"[!] 账户 {username} 请求发送验证码失败")
            return False

        code = self.email_extractor.get_login_code(
            email_address=username,
            max_wait_minutes=5,
            check_interval_seconds=10
        )
        if not code:
            logger.error(f"[!] 账户 {username} 获取验证码失败")
            return False
        
        success = self.server.request_login(username, code)
        if not success:
            logger.error(f"[!] 账户 {username} 验证码登录失败")
            return False
        
        logger.info(f"[+] 账户 {username} 验证码登录成功")
        cookies = self.server.get_cookies()
        
        status_result = self.server.request_status()
        if status_result and status_result.success:
            self._update_db_user_from_status(username, status_result, cookies)
            self._mark_cookies_valid(username, cookies)
        else:
            self._mark_cookies_valid(username, cookies)
        
        return True
    
    # -------------------------------
    # 签到
    # -------------------------------
    
    @require_login
    def _checkin(self, username: str) -> Optional[GladosCheckinResult]:
        result = self.server.request_checkin()
        if not result:
            logger.error(f"[!] 账户 {username} 签到失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {username} 签到成功，获得 {result.points} 积分")
            update_sign(username, gained_points=result.points)
        else:
            logger.error(f"[!] 账户 {username} 签到失败: {result.message}")
            if "login" in result.message.lower() or "auth" in result.message.lower():
                self._mark_cookies_invalid(username)

        return result
    
    def checkin(self) -> List[CheckinResult]:
        """执行所有账户签到"""
        logger.info("[*] 开始执行 GLaDOS 账户签到")
        results = []

        for username in self.usernames:
            logger.info(f"[*] 账户 {username} 开始签到")
            ret = self._checkin(username)
            if ret:
                result = CheckinResult(
                    username=username,
                    success=ret.success,
                    point=ret.points,
                    message=ret.message,
                )
                results.append(result)

        logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
        self._checkin_results = results
        return results
    
    # -------------------------------
    # 积分信息
    # -------------------------------
    
    @require_login
    def _point(self, username: str, force_refresh: bool = False) -> Optional[GladosPointResult]:
        if not force_refresh:
            db_user = get(username)
            if db_user and db_user.last_check_at:
                if time.time() - db_user.last_check_at < CACHE_POINT_TTL_SECONDS:
                    logger.debug(f"[缓存] 使用数据库缓存的积分数据: {username}")
                    return None
        
        result = self.server.request_point()
        if not result:
            logger.error(f"[!] 账户 {username} 获取积分失败, 服务异常")
            return None

        if result.success:
            logger.debug(f"[+] 账户 {username} 获取积分成功: {result.points}")
            db_user = get(username)
            if db_user:
                db_user.points = int(result.points)
                save(db_user)
        else:
            logger.error(f"[!] 账户 {username} 获取积分失败")
        
        return result
    
    # -------------------------------
    # 礼品码兑换
    # -------------------------------
    
    @require_login
    def _code(self, username: str, code: str) -> Optional[GladosCodeResult]:
        result = self.server.request_code(code)
        if not result:
            logger.error(f"[!] 账户 {username} 兑换礼品码失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {username} 兑换礼品码成功")
        else:
            logger.error(f"[!] 账户 {username} 兑换礼品码失败: {result.message}")

        return result
    
    def code(self) -> List[CodeResult]:
        """
        兑换礼品码（从邮箱提取）
        """
        logger.info("[*] 开始执行 GLaDOS 账户兑换礼品码")
        results = []

        # 从邮箱获取有效的礼品码
        gift_codes = self.email_extractor.get_gift_codes()
        if not gift_codes:
            logger.info("[i] 未找到有效的礼品码，跳过兑换")
            return results

        for gift in gift_codes:
            gift_username = gift.get("username")
            gift_code = gift.get("code")
            valid_day = gift.get("valid_day", 0)
            
            if gift_username not in self.usernames:
                logger.info(f"[!] 礼品码归属 {gift_username} 不在账户列表中，跳过")
                continue
            
            logger.info(f"[*] 账户 {gift_username} 开始兑换礼品码")
            ret = self._code(gift_username, gift_code)
            if ret:
                result = CodeResult(
                    username=gift_username,
                    success=ret.success,
                    days=int(valid_day) if ret.success else 0,
                    message=ret.message
                )
                results.append(result)

        logger.info(f"[✓] 礼品码兑换完成，共处理 {len(results)} 个结果")
        self._code_results = results
        return results
    
    # -------------------------------
    # 状态信息
    # -------------------------------
    
    @require_login
    def _status(self, username: str, force_refresh: bool = False) -> Optional[GladosStatusResult]:
        if not force_refresh:
            db_user = get(username)
            if db_user and db_user.last_check_at:
                if time.time() - db_user.last_check_at < CACHE_STATUS_TTL_SECONDS:
                    logger.debug(f"[缓存] 使用数据库缓存的状态数据: {username}")
                    if db_user.cookies:
                        self.server.update_cookies(db_user.cookies)
                    return None
        
        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {username} 获取状态失败, 服务异常")
            return None

        if result.success:
            logger.debug(f"[+] 账户 {username} 获取状态成功")
            self._update_db_user_from_status(username, result)
        else:
            logger.error(f"[!] 账户 {username} 获取状态失败")
            self._mark_cookies_invalid(username)

        return result
    
    # -------------------------------
    # 蛋糕兑换
    # -------------------------------
    
    @require_login
    def _cake(self, username: str) -> Optional[GladosCakesResult]:
        result = self.server.request_cakes()
        if not result:
            logger.error(f"[!] 账户 {username} 获取蛋糕列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {username} 获取蛋糕列表成功，共 {len(result.available)} 个可用蛋糕")
        else:
            logger.error(f"[!] 账户 {username} 获取蛋糕列表失败")

        return result
    
    @require_login
    def _redeem_cake(self, username: str, cake_id: int) -> Optional[GladosRedeemResult]:
        result = self.server.request_redeem(cake_id)
        if not result:
            logger.error(f"[!] 账户 {username} 兑换蛋糕失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {username} 兑换蛋糕成功")
        else:
            logger.error(f"[!] 账户 {username} 兑换蛋糕失败: {result.message}")

        return result
    
    def cake(self) -> List[RedeemResult]:
        """执行所有账户的蛋糕兑换"""
        logger.info("[*] 开始执行 GLaDOS 蛋糕兑换")
        results = []

        for username in self.usernames:
            status_result = self._status(username)
            if not status_result:
                continue

            if status_result.cake_count == 0:
                logger.info(f"[i] 账户 {username} 没有可用蛋糕")
                continue

            cake_result = self._cake(username)
            if cake_result and cake_result.success:
                for cake in cake_result.available:
                    ret = self._redeem_cake(username, cake.id)
                    if ret:
                        result = RedeemResult(
                            username=username,
                            success=ret.success,
                            amount=cake.amount,
                            message=ret.message
                        )
                        results.append(result)
                        logger.info(f"[+] 账户 {username} 兑换蛋糕 {cake.id}，获得 {cake.amount} 天")

        logger.info(f"[✓] 蛋糕兑换完成，共处理 {len(results)} 个结果")
        self._redeem_results = results
        return results
    
    # -------------------------------
    # 积分兑换（基于配置的续费规则）
    # -------------------------------
    
    @require_login
    def _exchange(self, username: str, plan_type: str) -> Optional[GladosExchangeResult]:
        result = self.server.request_exchange(plan_type)
        if not result:
            logger.error(f"[!] 账户 {username} 积分兑换失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {username} 积分兑换成功: 使用 {result.points_used} 积分获得 {result.days_added} 天")
            logger.info(f"[+] 账户 {username} 剩余积分: {result.points_remaining}")
            
            db_user = get(username)
            if db_user:
                db_user.points = int(result.points_remaining)
                db_user.remaining_days += result.days_added
                save(db_user)
        else:
            logger.error(f"[!] 账户 {username} 积分兑换失败: {result.message}")

        return result
    
    def exchange(self) -> List[GladosExchangeResult]:
        """根据配置的续费规则执行积分兑换"""
        logger.info("[*] 开始根据续费配置执行积分兑换")
        
        renewal_rules = self.glados_config.renewals
        if not renewal_rules:
            logger.info("[i] 未配置续费规则，跳过兑换")
            return []
        
        results = []
        
        for rule in renewal_rules:
            username = rule.username
            plan_type = rule.plan_type
            days_threshold = rule.days_threshold
            
            if username not in self.usernames:
                logger.warning(f"[!] 续费规则中的账户 {username} 不在账户列表中，跳过")
                continue
            
            if plan_type not in EXCHANGE_POINTS_MAP:
                logger.error(f"[!] 无效的续费计划: {plan_type}，支持: {list(EXCHANGE_POINTS_MAP.keys())}")
                continue
            
            logger.info(f"[*] 处理续费规则: 账户 {username}, 计划 {plan_type}, 阈值 {days_threshold} 天")
            
            status = self._status(username)
            if not status or not status.success:
                logger.error(f"[!] 账户 {username} 状态获取失败，跳过续费检查")
                continue
            
            left_days = status.left_days
            logger.info(f"[*] 账户 {username} 剩余天数: {left_days:.1f} 天, 阈值: {days_threshold} 天")
            
            if left_days >= days_threshold:
                logger.info(f"[i] 账户 {username} 剩余天数充足，无需续费")
                continue
            
            logger.info(f"[!] 账户 {username} 剩余天数 {left_days:.1f} < {days_threshold}，触发续费")
            
            required_points = EXCHANGE_POINTS_MAP[plan_type]
            
            point_result = self._point(username)
            if not point_result or not point_result.success:
                logger.error(f"[!] 账户 {username} 积分获取失败，跳过续费")
                continue
            
            current_points = point_result.points
            logger.info(f"[*] 账户 {username} 当前积分: {current_points}, 需要: {required_points}")
            
            if current_points < required_points:
                logger.warning(f"[!] 账户 {username} 积分不足: {current_points} < {required_points}，跳过续费")
                continue
            
            result = self._exchange(username, plan_type)
            if result and result.success:
                results.append(result)
        
        logger.info(f"[✓] 续费兑换完成，成功 {len(results)} 笔交易")
        return results
    
    def exchange_by_id(self, username: str, plan_type: str = "plan500") -> Optional[GladosExchangeResult]:
        """
        根据用户名进行积分兑换
        
        Args:
            username: 用户名（邮箱）
            plan_type: 兑换计划类型，支持 "plan500", "plan200", "plan100"
        """
        logger.info(f"[*] 兑换请求: 账号 {username}, 计划 {plan_type}")

        if plan_type not in EXCHANGE_POINTS_MAP:
            logger.error(f"[!] 无效的兑换计划: {plan_type}, 支持: {list(EXCHANGE_POINTS_MAP.keys())}")
            return None

        if username not in self.usernames:
            logger.error(f"[!] 未找到账号: {username}")
            return None

        # 确保登录状态
        if not self._check_login(username):
            if not self.login(username):
                logger.error(f"[!] 账号 {username} 登录失败，取消兑换")
                return None

        result = self._exchange(username, plan_type)
        if result and result.success:
            logger.info(f"[✓] 兑换成功: 账号 {username} 获得 {result.days_added} 天")
        else:
            error_msg = result.message if result else "服务异常"
            logger.error(f"[✗] 兑换失败: 账号 {username}, 原因: {error_msg}")

        return result
    
    # -------------------------------
    # 账户信息收集
    # -------------------------------
    
    def collect_account_infos(self) -> List[AccountInfo]:
        """收集所有账户的信息"""
        logger.info("[*] 开始收集账户信息")
        account_infos = []

        for username in self.usernames:
            logger.info(f"[*] 获取账户 {username} 信息")
            
            status = self._status(username)
            point = self._point(username)
            db_user = get(username)
            
            if status and status.success and point and point.success:
                total_traffic = self.server.get_total_traffic(status.vip)
                use_percent = (status.traffic / total_traffic * 100) if total_traffic > 0 else 0.0
                
                account_info = AccountInfo(
                    username=username,
                    points=int(point.points),
                    left_days=int(status.left_days),
                    current_traffic=status.traffic,
                    total_traffic=total_traffic,
                    use_percent=round(use_percent, 2)
                )
                account_infos.append(account_info)
                logger.info(f"[+] 账户 {username} 信息获取成功")
            elif db_user:
                total_traffic = self.server.get_total_traffic(db_user.vip_level)
                use_percent = (db_user.used_traffic_kb / total_traffic * 100) if total_traffic > 0 else 0.0
                
                account_info = AccountInfo(
                    username=username,
                    points=db_user.points,
                    left_days=db_user.remaining_days,
                    current_traffic=db_user.used_traffic_kb,
                    total_traffic=total_traffic,
                    use_percent=round(use_percent, 2)
                )
                account_infos.append(account_info)
                logger.info(f"[缓存] 账户 {username} 使用缓存数据")
            else:
                logger.error(f"[!] 账户 {username} 信息获取失败")

        self._account_infos = account_infos
        logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
        return account_infos
    
    # -------------------------------
    # 通知
    # -------------------------------
    
    def get_notifier(self) -> GladosNotifier:
        """获取通知器实例"""
        import yagmail
        
        try:
            yagmail.sender.SMTP.__del__ = lambda self: None
            mail = self.global_config.email
            smtp = mail.smtp
            smtp_client = yagmail.SMTP(
                user=mail.username,
                password=mail.password,
                host=smtp.host,
                port=smtp.port,
                smtp_ssl=smtp.secure
            )
            logger.info("[+] SMTP 客户端登录成功")
            
            return GladosNotifier(
                smtp_client=smtp_client,
                email_to=self.global_config.email_to,
                template_path=Path("modules/glados/templates/glados_notification.html"),
                checkin_results=self._checkin_results,
                code_results=self._code_results,
                redeem_results=self._redeem_results,
                account_infos=self._account_infos
            )
        except Exception as e:
            logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
            raise
    
    # -------------------------------
    # 获取内部结果（用于通知）
    # -------------------------------
    
    @property
    def checkin_results(self) -> List[CheckinResult]:
        return self._checkin_results
    
    @property
    def code_results(self) -> List[CodeResult]:
        return self._code_results
    
    @property
    def redeem_results(self) -> List[RedeemResult]:
        return self._redeem_results
    
    @property
    def account_infos(self) -> List[AccountInfo]:
        return self._account_infos


# ==================== 导出 ====================

__all__ = [
    'GladosClient',
]