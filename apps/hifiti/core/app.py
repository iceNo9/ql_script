# modules/hifiti/core/app.py

import time
from functools import wraps
from typing import Callable, Any, Optional, List, Dict
from pathlib import Path

from utils.log import get_logger
from utils.config import GlobalConfig

from utils.request_client import RequestClient
from apps.hifiti.core.table import User, get_user, save_user, update_sign_info
from apps.hifiti.core.notify import (
    SignResult,
    AccountInfo,
    Notifier
)

from apps.hifiti.core.server import Server
from apps.hifiti.core.parser import Parser

logger = get_logger(__name__)

# ==================== 缓存时间常量（秒） ====================
COOKIE_RENEW_THRESHOLD_SECONDS = 3600  # 1小时，低于此时间戳需要重新登录


# ==================== 登录检查装饰器 ====================

def require_login(func: Callable) -> Callable:
    """登录检查装饰器，自动检查并刷新登录态"""
    @wraps(func)
    def wrapper(self: 'App', username: str, *args, **kwargs):
        if not self._ensure_login(username):
            logger.error(f"[!] 账户 {username} 登录失效且无法重新登录，跳过操作")
            return None
        return func(self, username, *args, **kwargs)
    return wrapper


# ==================== HiFiTi 客户端 ====================

class App:
    def __init__(
        self, 
        global_config: GlobalConfig,
        accounts: List[Dict[str, str]],  # [{"username": "xxx", "password": "xxx"}, ...]
    ):
        """
        初始化 HiFiTi 客户端
        
        Args:
            global_config: 全局配置
            accounts: 账号列表 [{"username": "xxx", "password": "xxx"}, ...]
        """
        self.global_config = global_config
        
        # 账号列表
        self.accounts = accounts
        self.usernames = [acc["username"] for acc in accounts]
        
        # 密码映射表
        self._password_map = {acc["username"]: acc["password"] for acc in accounts}

        self.client = RequestClient(proxies=global_config.proxy, max_retries=2)
        self.server = Server(self.client)
        self.parser = Parser()

        # 操作结果（用于通知）
        self._sign_results: List[SignResult] = []
        self._account_infos: List[AccountInfo] = []

    # -------------------------------
    # 登录状态检查
    # -------------------------------
    
    def _switch_to_user_cookies(self, username: str) -> None:
        """切换到指定用户的 cookies"""
        db_user = get_user(username)
        if db_user and db_user.cookies:
            self.server.update_cookies(db_user.cookies)
            logger.debug(f"[切换] 账户 {username} 已切换到该用户的 cookies")
        else:
            logger.debug(f"[切换] 账户 {username} 无缓存 cookies")
    
    def _is_cookies_valid(self, username: str) -> bool:
        """检查 cookies 是否有效（未过期）"""
        db_user = get_user(username)
        if not db_user:
            return False
        
        if not db_user.cookies:
            return False
        
        if db_user.cookies_expire_at <= 0:
            return False
        
        current_time = int(time.time())
        return current_time < db_user.cookies_expire_at
    
    def _should_renew_cookies(self, username: str) -> bool:
        """检查是否需要更新 cookies（剩余时间不足阈值）"""
        db_user = get_user(username)
        if not db_user:
            return True
        
        if db_user.cookies_expire_at <= 0:
            return True
        
        current_time = int(time.time())
        remaining = db_user.cookies_expire_at - current_time
        return remaining < COOKIE_RENEW_THRESHOLD_SECONDS
    
    def _ensure_login(self, username: str) -> bool:
        """
        确保指定用户已登录（检查并切换 cookies，必要时重新登录）
        
        Returns:
            True: 登录有效
            False: 登录失败
        """
        # 检查是否需要重新登录（过期或即将过期）
        if self._should_renew_cookies(username):
            logger.info(f"[*] 账户 {username} cookies 即将过期或已过期，准备重新登录")
            return self._login(username)
        
        # 检查 cookies 是否有效
        if self._is_cookies_valid(username):
            # 切换到该用户的 cookies
            self._switch_to_user_cookies(username)
            return True
        
        # cookies 无效，重新登录
        logger.info(f"[*] 账户 {username} cookies 无效，准备登录")
        return self._login(username)
    
    def _login(self, username: str) -> bool:
        """登录账号"""
        password = self._password_map.get(username)
        if not password:
            logger.error(f"[!] 账户 {username} 未配置密码")
            return False
        
        logger.info(f"[*] 开始登录账户 {username}")
        
        result = self.server.post_login(username, password)
        
        if result.get("success"):
            logger.info(f"[+] 账户 {username} 登录成功")
            cookies = result.get("cookies", {})
            
            # 解析 cookie 到期时间戳
            expires_timestamp = self.parser.get_cookie_expires_timestamp(result)
            
            # 保存到数据库
            db_user = get_user(username)
            if db_user is None:
                db_user = User(username=username)
            
            db_user.cookies = cookies
            db_user.cookies_expire_at = expires_timestamp if expires_timestamp else 0
            save_user(db_user)
            
            # 更新到当前 session
            self.server.update_cookies(cookies)
            
            return True
        else:
            logger.error(f"[!] 账户 {username} 登录失败: {result.get('message')}")
            return False
    
    # -------------------------------
    # 签到
    # -------------------------------
    
    def _is_sign_today(self, username: str) -> bool:
        """检查今日是否已签到"""
        db_user = get_user(username)
        if not db_user:
            return False
        today = time.strftime("%Y-%m-%d")
        return db_user.last_sign_date == today
    
    @require_login
    def _do_sign(self, username: str) -> Optional[Dict[str, Any]]:
        """执行签到（需要登录）"""
        
        # 检查今日是否已签到
        if self._is_sign_today(username):
            logger.info(f"[*] 账户 {username} 今日已签到，跳过")
            return {"success": True, "message": "今日已签到", "skip": True}
        
        result = self.server.post_sign()
        
        if not result:
            logger.error(f"[!] 账户 {username} 签到失败, 服务异常")
            return None
        
        logger.info(f"[*] 账户 {username} 签到响应: {result}")
        
        if result.get("success"):
            message = result.get("message", "")
            reward = self.parser.get_sign_reward({"success": True, "message": message})
            rank = self.parser.get_sign_rank({"success": True, "message": message})
            
            logger.info(f"[+] 账户 {username} 签到成功，获得 {reward} 金币，排名 {rank}")
            
            # 获取当前最新金币并更新数据库
            html = self.server.get_my()
            if html:
                coins = self.parser.get_coin_balance(html)
                if coins is not None:
                    update_sign_info(username, reward, rank, coins)
                    logger.debug(f"[数据库] 账户 {username} 签到信息已更新，当前金币: {coins}")
                else:
                    update_sign_info(username, reward, rank)
                    logger.debug(f"[数据库] 账户 {username} 签到信息已更新，金币解析失败")
            else:
                update_sign_info(username, reward, rank)
                logger.debug(f"[数据库] 账户 {username} 签到信息已更新，未获取到页面")
            
            return result
        else:
            logger.error(f"[!] 账户 {username} 签到失败: {result.get('message')}")
            return None
    
    def sign(self) -> List[SignResult]:
        """执行所有账户签到"""
        logger.info("[*] 开始执行 HiFiTi 账户签到")
        results = []

        for username in self.usernames:
            logger.info(f"[*] 账户 {username} 开始签到")
            ret = self._do_sign(username)
            
            # 从数据库读取最新数据用于通知
            db_user = get_user(username)
            coins = db_user.coins if db_user else 0
            
            if ret and ret.get("success"):
                # 如果是跳过的签到（今日已签到）
                if ret.get("skip"):
                    result = SignResult(
                        username=username,
                        success=True,
                        reward=0,
                        rank=0,
                        coins=coins,
                        message="今日已签到",
                    )
                else:
                    message = ret.get("message", "")
                    reward = self.parser.get_sign_reward(ret)
                    rank = self.parser.get_sign_rank(ret)
                    
                    result = SignResult(
                        username=username,
                        success=True,
                        reward=reward,
                        rank=rank,
                        coins=coins,
                        message=message,
                    )
                results.append(result)
            else:
                result = SignResult(
                    username=username,
                    success=False,
                    reward=0,
                    rank=0,
                    coins=coins,
                    message=ret.get("message", "签到失败") if ret else "服务异常",
                )
                results.append(result)

        logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
        self._sign_results = results
        return results
    
    # -------------------------------
    # 用户信息获取
    # -------------------------------
    @require_login
    def _get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """
        获取单个用户的金币（需要确保已登录并切换 cookies）
        
        Returns:
            {
                "username": "xxx",
                "coins": 83,
            }
        """
        # 确保该用户已登录并切换 cookies
        if not self._ensure_login(username):
            logger.error(f"[!] 账户 {username} 无法登录，获取信息失败")
            return None
        
        html = self.server.get_my()
        if not html:
            logger.error(f"[!] 账户 {username} 获取页面失败")
            return None
        
        # 解析金币
        coins = self.parser.get_coin_balance(html)
        
        if coins is None:
            logger.error(f"[!] 账户 {username} 解析金币失败")
            return None
        
        result = {
            "username": username,
            "coins": coins,
        }
        
        # 更新数据库中的金币
        db_user = get_user(username)
        if db_user is None:
            db_user = User(username=username)
        
        db_user.coins = result["coins"]
        save_user(db_user)
        
        logger.info(f"[*] 账户 {username} 当前金币: {coins}")
        
        return result

    def get_user_info(self, username: str = None) -> List[Dict[str, Any]]:
        """
        获取用户金币信息
        
        Args:
            username: 指定用户名，不传则获取所有用户
        
        Returns:
            用户信息列表 [{"username": "xxx", "coins": 83}, ...]
        """
        if username:
            # 获取单个用户
            if username not in self.usernames:
                logger.error(f"[!] 未找到账号: {username}")
                return []
            
            result = self._get_user_info(username)
            return [result] if result else []
        else:
            # 获取所有用户
            results = []
            for user in self.usernames:
                logger.info(f"[*] 获取账户 {user} 金币")
                result = self._get_user_info(user)
                if result:
                    results.append(result)
                else:
                    # 从数据库读取缓存
                    db_user = get_user(user)
                    if db_user:
                        results.append({
                            "username": user,
                            "coins": db_user.coins,
                        })
                        logger.debug(f"[缓存] 账户 {user} 使用缓存数据: 金币 {db_user.coins}")
            return results

    # -------------------------------
    # 账户信息收集
    # -------------------------------    
    def collect_account_infos(self) -> List[AccountInfo]:
        """收集所有账户的信息（从数据库读取）"""
        logger.info("[*] 开始收集账户信息（从数据库）")
        account_infos = []

        for username in self.usernames:
            db_user = get_user(username)
            if db_user:
                account_info = AccountInfo(
                    username=username,
                    coins=db_user.coins,
                )
                account_infos.append(account_info)
                logger.debug(f"[数据库] 账户 {username} 金币: {db_user.coins}")
            else:
                # 数据库中没有记录，尝试获取一次
                logger.info(f"[*] 账户 {username} 数据库中无记录，尝试获取")
                result = self._get_user_info(username)
                if result:
                    account_info = AccountInfo(
                        username=username,
                        coins=result["coins"],
                    )
                    account_infos.append(account_info)
                else:
                    logger.error(f"[!] 账户 {username} 无法获取信息")

        self._account_infos = account_infos
        logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
        return account_infos
    
    # -------------------------------
    # 通知
    # -------------------------------
    
    def get_notifier(self) -> Notifier:
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
            
            return Notifier(
                smtp_client=smtp_client,
                email_to=self.global_config.email_to,
                template_path=Path("modules/hifiti/templates/report.html"),
                sign_results=self._sign_results,
                account_infos=self._account_infos
            )
        except Exception as e:
            logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
            raise
    
    # -------------------------------
    # 获取内部结果（用于通知）
    # -------------------------------
    
    @property
    def sign_results(self) -> List[SignResult]:
        return self._sign_results
    
    @property
    def account_infos(self) -> List[AccountInfo]:
        return self._account_infos
    
    # -------------------------------
    # 单账户操作便捷方法
    # -------------------------------
    
    def sign_by_username(self, username: str) -> Optional[SignResult]:
        """为指定用户签到"""
        if username not in self.usernames:
            logger.error(f"[!] 未找到账号: {username}")
            return None
        
        ret = self._do_sign(username)
        
        # 从数据库读取最新数据
        db_user = get_user(username)
        coins = db_user.coins if db_user else 0
        
        if ret and ret.get("success"):
            if ret.get("skip"):
                return SignResult(
                    username=username,
                    success=True,
                    reward=0,
                    rank=0,
                    coins=coins,
                    message="今日已签到",
                )
            else:
                reward = self.parser.get_sign_reward(ret)
                rank = self.parser.get_sign_rank(ret)
                return SignResult(
                    username=username,
                    success=True,
                    reward=reward,
                    rank=rank,
                    coins=coins,
                    message=ret.get("message", ""),
                )
        else:
            return SignResult(
                username=username,
                success=False,
                reward=0,
                rank=0,
                coins=coins,
                message=ret.get("message", "签到失败") if ret else "服务异常",
            )
    
    def get_coin_balance(self, username: str) -> Optional[int]:
        """获取指定用户的金币余额（从数据库读取）"""
        if username not in self.usernames:
            logger.error(f"[!] 未找到账号: {username}")
            return None
        
        db_user = get_user(username)
        if db_user:
            return db_user.coins
        
        # 数据库中无记录，尝试获取
        result = self._get_user_info(username)
        return result["coins"] if result else None


# ==================== 导出 ====================

__all__ = [
    'App',
]