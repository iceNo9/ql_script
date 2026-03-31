import yagmail
import random
from urllib.parse import urljoin
from functools import wraps
from typing import Callable, TypeVar, Any, Optional, List, cast
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
from htmlmin import minify
from pathlib import Path
from common.log import get_logger
from common.global_config import GlobalConfig, EmailConfig, IMAPConfig
from datetime import datetime
from typing import ParamSpec, Concatenate


from modules.glados.utils.request_client import RequestClient
from modules.glados.core.email import EmailCodeExtractor, GiftCode
from modules.glados.core.data import GladosAccountData as Account
from modules.glados.core.notify import GladosNotifier 

from modules.glados.core.server import (
    GladosServer, 
    GladosAuthResult,
    GladosPointResult,
    GladosCheckinResult,
    GladosStatusResult,
    GladosCodeResult,
    GladosCakesResult,
    GladosRedeemResult,
    GladosExchangeRequest,
    GladosExchangeResult
)

logger = get_logger(__name__)

P = ParamSpec('P')
R = TypeVar('R')

class CheckinResult(BaseModel):
    id: str
    success: bool
    point: int
    message: str

class CodeResult(BaseModel):
    id : str
    success: bool
    days: int
    message: str

class RedeemResult(BaseModel):
    id : str
    success: bool
    amount: int
    message: str

class AccountInfo(BaseModel):
    id: str
    points: int
    left_days: int
    current_traffic: int
    total_traffic: int
    use_percent: float

def require_login_typed(func: Callable[Concatenate['GladosClient', Account, P], R]
                       ) -> Callable[Concatenate['GladosClient', Account, P], Optional[R]]:
    """类型安全的登录检查装饰器"""
    @wraps(func)
    def wrapper(self: 'GladosClient', account: Account, *args: P.args, **kwargs: P.kwargs) -> Optional[R]:
        if not self._check_account_ok(account):
            if not self.login(account):
                logger.error(f"[!] 账户 {account.username} 登录失败，跳过操作")
                return None
        return func(self, account, *args, **kwargs)
    return wrapper

class GladosClient:
    def __init__(self, rv_proxies: List[str], rv_accounts: List[Account], rv_global_config: GlobalConfig):

        self.accounts = rv_accounts
        self._global_config = rv_global_config 

        self.client = RequestClient(proxies=rv_proxies, max_retries=2)
        self.server = GladosServer(self.client)
        self.email_extractor = EmailCodeExtractor(self._global_config.email)

        # 操作结果
        self.checkin_results = []
        self.code_results = []
        self.redeem_results = []
        self.account_infos = []

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _check_account_ok(self, rv_account: Account) -> bool:
        """检查登录状态"""
        if rv_account.cookies:
            self.server.update_cookies(rv_account.cookies)
        else:
            self.server.clear_cookies()

        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {rv_account.username} 登录状态服务异常")
            return False

        if not result.success:
            logger.debug(f"[!] 账户 {rv_account.username} 登录状态检查失败")
            return False

        logger.debug(f"[+] 账户 {rv_account.username} 登录状态正常")
        return True
        
    def login(self, rv_account: Account) -> bool:
        """登录账号"""
        logger.debug(f"[+] 使用账户 {rv_account.username} 登录")

        # 检查cookies登录状态是否有效
        if self._check_account_ok(rv_account):
            logger.info(f"[+] 账户 {rv_account.username} cookies 登录成功")
        else:
            # 执行邮箱验证码登录
            logger.info(f"[*] 账户 {rv_account.username} cookies 登录失效，尝试邮箱验证码登录")
            result = self.server.request_authorization(rv_account.username)
            if not result or not result.success:
                logger.error(f"[!] 账户 {rv_account.username} 请求发送验证码失败")
                return False

            # 捕获验证码
            code = self.email_extractor.get_login_code(email_address=rv_account.username, max_wait_minutes=5, check_interval_seconds=10)
            if not code:
                logger.error(f"[!] 账户 {rv_account.username} 获取验证码失败")
                return False
            
            # 提交验证码登录
            success = self.server.request_login(rv_account.username, code)
            if not success:
                logger.error(f"[!] 账户 {rv_account.username} 验证码登录失败")
                return False
            
            logger.info(f"[+] 账户 {rv_account.username} 验证码登录成功")
            rv_account.cookies = self.server.get_cookies()
            self.server.update_cookies(rv_account.cookies)

        return True
    
    @require_login_typed
    def _checkin(self, account: Account) -> Optional[GladosCheckinResult]:
        result = self.server.request_checkin()
        if not result:
            logger.error(f"[!] 账户 {account.id} 签到失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 签到成功")
        else:
            logger.error(f"[!] 账户 {account.id} 签到失败: {result.message}")

        return result

    def checkin(self) -> List[CheckinResult]:
        logger.info("[*] 开始执行 GLaDOS 账户签到")
        results = []

        for account in self.accounts:
            logger.info(f"[*] 账户 {account.id} 开始签到")
            ret = self._checkin(account)
            if ret:
                result = CheckinResult(
                    id=account.id,
                    success=ret.success,
                    point=ret.points,
                    message=ret.message,
                )            
                results.append(result)

        logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
        self.checkin_results = results
        return results
    
    @require_login_typed
    def _code(self, account: Account, code: str) -> Optional[GladosCodeResult]:
        result = self.server.request_code(code)
        if not result:
            logger.error(f"[!] 账户 {account.id} 兑换礼品码失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 兑换礼品码成功")
        else:
            logger.error(f"[!] 账户 {account.id} 兑换礼品码失败: {result.message}")

        return result
    
    def code(self) -> List[CodeResult]:
        logger.info("[*] 开始执行 GLaDOS 账户兑换礼品码")
        results = []

        # 获取有效的礼品码
        gift_codes = self.email_extractor.get_gift_codes()
        if not gift_codes:
            logger.info("[i] 未找到有效的礼品码，跳过兑换")
            return results

        # 兑换礼品码
        for gift_code in gift_codes:
            for account in self.accounts:
                if gift_code.username == account.username:
                    logger.info(f"[*] 账户 {account.id} 开始兑换礼品码")
                    ret = self._code(account, gift_code.code)
                    if ret:
                        result = CodeResult(
                            id=account.id,
                            success=ret.success,
                            days=int(gift_code.valid_day) if ret.success else 0,
                            message=ret.message
                        )
                        results.append(result)
                    break
                else:
                    logger.info(f"[!] 账户 {account.id} 与礼品码不匹配，跳过兑换")
                    continue

        logger.info(f"[✓] 礼品码兑换完成，共处理 {len(results)} 个结果")
        self.code_results = results
        return results

    @require_login_typed
    def _redeem(self, account: Account, cake_id: int) -> Optional[GladosRedeemResult]:
        result = self.server.request_redeem(cake_id)
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取蛋糕列表成功")
        else:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败: {result.message}")

        return result
    
    @require_login_typed
    def _status(self, account: Account) -> Optional[GladosStatusResult]:
        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取状态失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取状态成功")
            account.leftDays = int(result.left_days)
            account.vip_level = int(result.vip)
            account.traffic = result.traffic
            account.total_traffic = self.server.get_total_traffic(account.vip_level)
        else:
            logger.error(f"[!] 账户 {account.id} 获取状态失败")

        return result
    
    @require_login_typed
    def _cake(self, account: Account) -> Optional[GladosCakesResult]:
        result = self.server.request_cakes()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取蛋糕列表成功")
        else:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败")

        return result
    
    @require_login_typed
    def _point(self, account: Account) -> Optional[GladosPointResult]:
        result = self.server.request_point()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取积分列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取积分列表成功")
        else:            
            logger.error(f"[!] 账户 {account.id} 获取积分列表失败")
        
        return result
    
    @require_login_typed
    def _exchange(self, account: Account, plan_type: str = "plan500") -> Optional[GladosExchangeResult]:
        """
        执行积分兑换
        
        Args:
            account: 账户对象
            plan_type: 兑换计划类型，默认为 "plan500" (500积分兑换100天)
            
        Returns:
            Optional[GladosExchangeResult]: 兑换结果，失败返回 None
        """
        result = self.server.request_exchange(plan_type)
        if not result:
            logger.error(f"[!] 账户 {account.id} 积分兑换失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 积分兑换成功: 使用 {result.points_used} 积分获得 {result.days_added} 天")
            logger.info(f"[+] 账户 {account.id} 剩余积分: {result.points_remaining}")
            
            # 更新账户信息
            account.balance = result.points_remaining
            account.leftDays += result.days_added  # 增加剩余天数
        else:
            logger.error(f"[!] 账户 {account.id} 积分兑换失败: {result.message}")

        return result
            
    def cake(self) -> List[RedeemResult]:
        logger.info("[*] 开始执行 GLaDOS 蛋糕兑换")
        results = []

        # 获取账号信息,获取有效cake
        for account in self.accounts:

            status_result = self._status(account)
            if not status_result:
                continue

            if not status_result.success or not status_result.cake_count:
                continue

            # 获取蛋糕列表
            cake_result = self._cake(account)
            if cake_result and cake_result.success:
                for cake in cake_result.available:
                    ret = self._redeem(account, cake.id)
                    if ret:
                        result = RedeemResult(
                            id = account.id,
                            success = ret.success,
                            amount = cake.amount,
                            message = ret.message
                        )

                        results.append(result)

        logger.info(f"[✓] 蛋糕兑换完成，共处理 {len(results)} 个结果")
        self.redeem_results = results
        return results
    
    def exchange(self, plan_type: str = "plan500") -> Optional[GladosExchangeResult]:
        """
        智能积分兑换：当所有账户剩余天数都为0时，选择积分最多的账户进行兑换
        
        Args:
            plan_type: 兑换计划类型，默认为 "plan500" (500积分兑换100天)
            
        Returns:
            Optional[GladosExchangeResult]: 兑换结果，失败或无账户可兑换返回 None
            
        Logic:
            1. 检查所有账户的剩余天数
            2. 如果所有账户剩余天数都 <= 0，则继续
            3. 选择积分最多的账户
            4. 检查该账户积分是否足够兑换
            5. 执行兑换
        """
        logger.info("[*] 开始智能积分兑换检查")
        
        # 根据 plan_type 获取所需积分
        points_map = {
            "plan500": 500,
            "plan200": 200,
            "plan100": 100,
        }
        required_points = points_map.get(plan_type, 500)
        
        # 收集所有账户的状态信息
        accounts_status = []
        for account in self.accounts:
            status = self._status(account)
            point = self._point(account)
            
            if status and status.success and point and point.success:
                accounts_status.append({
                    'account': account,
                    'left_days': status.left_days,
                    'points': point.points
                })
                logger.debug(f"[*] 账户 {account.id}: 剩余天数 {status.left_days:.1f} 天, 积分 {point.points}")
            else:
                logger.warning(f"[!] 账户 {account.id} 状态获取失败，跳过")
        
        if not accounts_status:
            logger.error("[!] 没有可用的账户信息")
            return None
        
        # 检查是否所有账户剩余天数都为0
        all_days_zero = all(status['left_days'] <= 0 for status in accounts_status)
        
        if not all_days_zero:
            logger.info("[i] 存在账户还有剩余天数，跳过积分兑换")
            # 打印剩余天数不为0的账户信息
            active_accounts = [s for s in accounts_status if s['left_days'] > 0]
            for status in active_accounts:
                logger.info(f"[i] 账户 {status['account'].id} 还有 {status['left_days']:.1f} 天剩余")
            return None
        
        logger.info("[!] 所有账户剩余天数均为0，准备进行积分兑换")
        
        # 选择积分最多的账户
        max_points_account = max(accounts_status, key=lambda x: x['points'])
        target_account = max_points_account['account']
        max_points = max_points_account['points']
        
        logger.info(f"[*] 选择账户 {target_account.id} 进行兑换，当前积分: {max_points}")
        
        # 检查积分是否足够兑换
        if max_points < required_points:
            logger.error(f"[!] 账户 {target_account.id} 积分不足: 需要 {required_points} 积分，当前只有 {max_points} 积分")
            return None
        
        # 执行兑换
        logger.info(f"[*] 开始兑换: 账户 {target_account.id} 使用 {plan_type} 计划")
        result = self._exchange(target_account, plan_type)
        
        if result and result.success:
            logger.info(f"[✓] 智能兑换成功: 账户 {target_account.id} 获得 {result.days_added} 天，消耗 {result.points_used} 积分")
        else:
            logger.error(f"[✗] 智能兑换失败: {result.message if result else '未知错误'}")
        
        return result


    def collect_account_infos(self) -> List[AccountInfo]:
        """收集所有账户的信息"""
        logger.info("[*] 开始收集账户信息")
        account_infos = []
        
        for account in self.accounts:
            logger.info(f"[*] 获取账户 {account.id} 信息")
            status = self._status(account)
            point = self._point(account)            
            
            if status and status.success and point and point.success:

                account.balance = point.points

                # 转换为AccountInfo格式
                account_info = AccountInfo(
                    id=account.id,
                    points=int(point.points),
                    left_days=account.leftDays,
                    current_traffic=account.traffic,
                    total_traffic=account.total_traffic,
                    use_percent = (
                        account.traffic / account.total_traffic
                        if account.total_traffic > 0 else 0.0
                    )
                )
                account_infos.append(account_info)
                logger.info(f"[+] 账户 {account.id} 信息获取成功")
            else:
                logger.error(f"[!] 账户 {account.id} 信息获取失败")
        
        self.account_infos = account_infos
        logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
        return account_infos

    def get_notifier(self) -> 'GladosNotifier':
        """获取通知器实例"""
        # 初始化 SMTP 客户端
        try:
            yagmail.sender.SMTP.__del__ = lambda self: None
            mail = self._global_config.email
            smtp = mail.smtp
            smtp_client = yagmail.SMTP(
                user=mail.username,
                password=mail.password,
                host=smtp.host,
                port=smtp.port,
                smtp_ssl=smtp.secure
            )
            logger.info("[+] SMTP 客户端登录成功")
            
            # 创建通知器
            return GladosNotifier(
                smtp_client=smtp_client,
                email_to=self._global_config.email_to,
                template_path=Path("modules/glados/templates/glados_notification.html"),
                checkin_results=self.checkin_results,
                code_results=self.code_results,
                redeem_results=self.redeem_results,
                account_infos=self.account_infos
            )
        except Exception as e:
            logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
            raise


