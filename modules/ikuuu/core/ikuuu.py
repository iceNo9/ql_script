import yagmail
from urllib.parse import urljoin
from functools import wraps
from typing import Callable, TypeVar, Any, Optional, List, cast
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
from htmlmin import minify
from pathlib import Path
from utils.log import get_logger
from utils.config import GlobalConfig, EmailConfig, IMAPConfig
from datetime import datetime
from typing import ParamSpec, Concatenate


from modules.ikuuu.utils.request_client import RequestClient
from modules.ikuuu.core.data import IkuuuAccountData as Account
from modules.ikuuu.core.notify import IkuuuNotifier 

from modules.ikuuu.core.server import (
    IkuuuServer, 
    IkuuuCheckinResult,
    IkuuuStatusResult,
)

logger = get_logger(__name__)

P = ParamSpec('P')
R = TypeVar('R')

class CheckinResult(BaseModel):
    id: str
    success: bool
    change_bytes: int
    message: str

class AccountInfo(BaseModel):
    id: str
    total_bytes: int
    used_bytes: int
    today_used_bytes: int
    remain_bytes: int

def require_login_typed(func: Callable[Concatenate['IkuuuClient', Account, P], R]
                       ) -> Callable[Concatenate['IkuuuClient', Account, P], Optional[R]]:
    """类型安全的登录检查装饰器"""
    @wraps(func)
    def wrapper(self: 'IkuuuClient', account: Account, *args: P.args, **kwargs: P.kwargs) -> Optional[R]:
        if not self._check_account_ok(account):
            if not self.login(account):
                logger.error(f"[!] 账户 {account.username} 登录失败，跳过操作")
                return None
        return func(self, account, *args, **kwargs)
    return wrapper

class IkuuuClient:
    def __init__(self, rv_proxies: List[str], rv_accounts: List[Account], rv_global_config: GlobalConfig):

        self.accounts = rv_accounts
        self._global_config = rv_global_config 

        self.client = RequestClient(proxies=rv_proxies, max_retries=2)
        self.server = IkuuuServer(self.client)

        # 操作结果
        self.checkin_results = []
        self.account_infos = []

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _check_account_ok(self, rv_account: Account) -> bool:
        """检查登录状态"""
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
            # 执行邮箱密码登录
            logger.info(f"[*] 账户 {rv_account.username} cookies 登录失效，尝试账号密码登录")
            success = self.server.request_login(rv_account.username, rv_account.password)
            if not success:
                logger.error(f"[!] 账户 {rv_account.username} 账号密码登录失败")
                return False
            
            logger.info(f"[+] 账户 {rv_account.username} 账号密码登录成功")
            rv_account.cookies = self.server.get_cookies()
            self.server.update_cookies(rv_account.cookies)

        return True
    
    @require_login_typed
    def _checkin(self, account: Account) -> Optional[IkuuuCheckinResult]:
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
                    change_bytes=ret.change_bytes,
                    message=ret.message,
                )            
                results.append(result)

        logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
        self.checkin_results = results
        return results
        
    @require_login_typed
    def _status(self, account: Account) -> Optional[IkuuuStatusResult]:
        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取状态失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取状态成功")
            account.total_bytes = result.total_bytes
            account.used_bytes = result.used_bytes
            account.today_used_bytes = result.today_used_bytes
            account.remain_bytes = result.remain_bytes
        else:
            logger.error(f"[!] 账户 {account.id} 获取状态失败")

        return result
    
    def collect_account_infos(self) -> List[AccountInfo]:
        """收集所有账户的信息"""
        logger.info("[*] 开始收集账户信息")
        account_infos = []
        
        for account in self.accounts:
            logger.info(f"[*] 获取账户 {account.id} 信息")
            status = self._status(account)
            
            if status and status.success:

                # 转换为AccountInfo格式
                account_info = AccountInfo(
                    id=account.id,
                    total_bytes=account.total_bytes,
                    used_bytes=account.used_bytes,
                    today_used_bytes=account.today_used_bytes,
                    remain_bytes=account.remain_bytes,
                    )
                
                account_infos.append(account_info)
                logger.info(f"[+] 账户 {account.id} 信息获取成功")
            else:
                logger.error(f"[!] 账户 {account.id} 信息获取失败")
        
        self.account_infos = account_infos
        logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
        return account_infos

    def get_notifier(self) -> 'IkuuuNotifier':
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
            return IkuuuNotifier(
                smtp_client=smtp_client,
                email_to=self._global_config.email_to,
                template_path=Path("modules/ikuuu/templates/notification.html"),
                checkin_results=self.checkin_results,
                account_infos=self.account_infos
            )
        except Exception as e:
            logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
            raise


