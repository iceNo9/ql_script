# modules/baiyefee/core/app.py

import time
from functools import wraps
from typing import Callable, Any, Optional, List, Dict
from pathlib import Path

from common.log import get_logger
from common.global_config import GlobalConfig

from common.request_client import RequestClient
from modules.baiyefee.core.table import User, get_user, save_user
from modules.baiyefee.core.notify import (
    SignResult,
    AccountInfo,
    Notifier
)

from modules.baiyefee.core.server import Server
from modules.baiyefee.core.parser import Parser

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


# ==================== 小白玩物箱 客户端 ====================

class App:
    def __init__(
        self, 
        global_config: GlobalConfig,
        accounts: List[Dict[str, str]],  # [{"username": "xxx", "password": "xxx"}, ...]
    ):
        """
        初始化 小白玩物箱 客户端
        
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
    # 签到信息获取与签到
    # -------------------------------
    
    @require_login
    def _get_and_update_sign_info(self, username: str) -> Optional[Dict[str, Any]]:
        """
        获取签到信息并更新数据库（需要登录）
        
        sign_info 响应结构（实际返回）:
        {
            'mission': {
                'date': '2026-06-01 11:03:38',
                'credit': '6',
                'always': '1',
                'tk': {'days': 0, 'credit': 0, 'bs': '3'},
                'my_credit': '6',
                'current_user': 13877
            }
        }
        """
        result = self.server.post_sign_info()
        
        if not result:
            logger.error(f"[!] 账户 {username} 获取签到信息失败")
            return None
        
        if not result.get("success"):
            logger.error(f"[!] 账户 {username} 获取签到信息失败: {result.get('message')}")
            return None
        
        data = result.get("data", {})
        
        # 修复：数据在 mission 里面
        mission = data.get("mission", {})
        if not mission:
            logger.error(f"[!] 账户 {username} 签到信息解析失败: 没有 mission 字段")
            return None
        
        # 从 mission 中获取字段
        sign_date = mission.get("date", "")
        credit = int(mission.get("credit", 0))  # 签到获得的积分
        always = int(mission.get("always", 0))  # 连续签到天数
        my_credit = int(mission.get("my_credit", 0))  # 总积分
        
        # 判断今日是否已签到（通过日期判断）
        today = time.strftime("%Y-%m-%d")
        sign_date_only = sign_date.split(" ")[0] if " " in sign_date else sign_date
        is_signed_today = (sign_date_only == today)
        
        logger.info(f"[*] 账户 {username} 签到信息: "
                f"日期={sign_date}, 已签到={is_signed_today}, "
                f"签到积分={credit}, 连续签到={always}, 总积分={my_credit}")
        
        # 更新数据库
        db_user = get_user(username)
        if db_user is None:
            db_user = User(username=username)
        
        # 更新签到信息
        db_user.last_sign_date = sign_date_only
        db_user.last_sign_reward = credit
        db_user.continuous_sign_days = always
        db_user.credit = my_credit
        save_user(db_user)
        
        return {
            "success": True,
            "is_signed_today": is_signed_today,
            "sign_date": sign_date,
            "credit": credit,
            "always": always,
            "my_credit": my_credit,
            "data": data
        }
    
    @require_login
    def _do_sign(self, username: str) -> Optional[Dict[str, Any]]:
        """
        执行签到（需要登录）
        先获取签到信息，如果今天已签到则跳过，否则执行签到
        """
        # 先获取签到信息
        sign_info = self._get_and_update_sign_info(username)
        
        if not sign_info:
            logger.error(f"[!] 账户 {username} 无法获取签到信息")
            return None
        
        # 如果今天已签到，直接返回（不再调用 sign 接口）
        if sign_info.get("is_signed_today"):
            # 从 sign_info 中获取当天的签到积分
            reward = sign_info.get("credit", 0)  # 当天签到获得的积分
            continuous_days = sign_info.get("always", 0)
            my_credit = sign_info.get("my_credit", 0)
            
            logger.info(f"[*] 账户 {username} 今日已签到，获得 {reward} 积分，连续签到 {continuous_days} 天，总积分 {my_credit}")
            return {
                "success": True,
                "message": "今日已签到",
                "skip": True,
                "reward": reward,  # 显示当天签到获得的积分
                "continuous_days": continuous_days,
                "credit": my_credit
            }
        
        # 执行签到
        logger.info(f"[*] 账户 {username} 开始签到")
        result = self.server.post_sign()
        
        if not result:
            logger.error(f"[!] 账户 {username} 签到失败, 服务异常")
            return None
        
        logger.info(f"[*] 账户 {username} 签到响应: {result}")
        
        if result.get("success"):
            data = result.get("data", {})
            
            # 修复：数据在 mission 里面
            mission = data.get("mission", {})
            
            reward = int(mission.get("credit", 0))
            sign_date = mission.get("date", "")
            continuous_days = int(mission.get("always", 0))
            my_credit = int(mission.get("my_credit", 0))
            
            logger.info(f"[+] 账户 {username} 签到成功，获得 {reward} 积分，"
                    f"连续签到 {continuous_days} 天，总积分 {my_credit}")
            
            # 更新数据库
            db_user = get_user(username)
            if db_user is None:
                db_user = User(username=username)
            
            if sign_date:
                date_only = sign_date.split(" ")[0] if " " in sign_date else sign_date
                db_user.last_sign_date = date_only
            db_user.last_sign_reward = reward
            db_user.continuous_sign_days = continuous_days
            db_user.credit = my_credit
            save_user(db_user)
            
            return {
                "success": True,
                "reward": reward,
                "continuous_days": continuous_days,
                "credit": my_credit,
                "message": result.get("message", "签到成功")
            }
        else:
            # 如果是重复签到（已签到）
            if result.get("already_signed"):
                logger.info(f"[*] 账户 {username} {result.get('message')}")
                # 重新获取一次签到信息更新数据库
                sign_info = self._get_and_update_sign_info(username)
                if sign_info:
                    reward = sign_info.get("credit", 0)  # 从 sign_info 获取签到积分
                    return {
                        "success": True,
                        "skip": True,
                        "reward": reward,  # 显示当天签到获得的积分
                        "continuous_days": sign_info.get("always", 0),
                        "credit": sign_info.get("my_credit", 0),
                        "message": result.get("message")
                    }
            
            logger.error(f"[!] 账户 {username} 签到失败: {result.get('message')}")
            return None

    def sign(self) -> List[SignResult]:
        """执行所有账户签到"""
        logger.info("[*] 开始执行 小白玩物箱 账户签到")
        results = []

        for username in self.usernames:
            logger.info(f"[*] 账户 {username} 开始处理")
            ret = self._do_sign(username)
            
            # 从数据库读取最新数据用于通知
            db_user = get_user(username)
            credit = db_user.credit if db_user else 0
            continuous_days = db_user.continuous_sign_days if db_user else 0
            
            if ret and ret.get("success"):
                if ret.get("skip"):
                    # 今日已签到，使用 ret 中的 reward（从 sign_info 获取）
                    result = SignResult(
                        username=username,
                        success=True,
                        reward=ret.get("reward", 0),  # 使用从 sign_info 获取的积分
                        continuous_days=ret.get("continuous_days", continuous_days),
                        message="今日已签到",
                    )
                else:
                    # 新签到
                    result = SignResult(
                        username=username,
                        success=True,
                        reward=ret.get("reward", 0),
                        continuous_days=ret.get("continuous_days", continuous_days),
                        message=ret.get("message", "签到成功"),
                    )
                results.append(result)
            else:
                result = SignResult(
                    username=username,
                    success=False,
                    reward=0,
                    continuous_days=continuous_days,
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
        获取单个用户的积分信息（从签到信息中获取）
        
        Returns:
            {
                "username": "xxx",
                "credit": 100,
                "continuous_days": 5,
            }
        """
        # 获取签到信息（会自动更新数据库）
        sign_info = self._get_and_update_sign_info(username)
        
        if not sign_info:
            logger.error(f"[!] 账户 {username} 获取信息失败")
            return None
        
        result = {
            "username": username,
            "credit": sign_info.get("my_credit", 0),
            "continuous_days": sign_info.get("always", 0),
        }
        
        logger.info(f"[*] 账户 {username} 当前积分: {result['credit']}, 连续签到: {result['continuous_days']}天")
        
        return result

    def get_user_info(self, username: str = None) -> List[Dict[str, Any]]:
        """
        获取用户积分信息
        
        Args:
            username: 指定用户名，不传则获取所有用户
        
        Returns:
            用户信息列表 [{"username": "xxx", "credit": 100, "continuous_days": 5}, ...]
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
                logger.info(f"[*] 获取账户 {user} 积分")
                result = self._get_user_info(user)
                if result:
                    results.append(result)
                else:
                    # 从数据库读取缓存
                    db_user = get_user(user)
                    if db_user:
                        results.append({
                            "username": user,
                            "credit": db_user.credit,
                            "continuous_days": db_user.continuous_sign_days,
                        })
                        logger.debug(f"[缓存] 账户 {user} 使用缓存数据: 积分 {db_user.credit}")
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
                    credit=db_user.credit,
                    continuous_days=db_user.continuous_sign_days,
                )
                account_infos.append(account_info)
                logger.debug(f"[数据库] 账户 {username} 积分: {db_user.credit}, 连续签到: {db_user.continuous_sign_days}天")
            else:
                # 数据库中没有记录，尝试获取一次
                logger.info(f"[*] 账户 {username} 数据库中无记录，尝试获取")
                result = self._get_user_info(username)
                if result:
                    account_info = AccountInfo(
                        username=username,
                        credit=result["credit"],
                        continuous_days=result["continuous_days"],
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
                template_path=Path("modules/baiyefee/templates/report.html"),
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
        credit = db_user.credit if db_user else 0
        continuous_days = db_user.continuous_sign_days if db_user else 0
        
        if ret and ret.get("success"):
            if ret.get("skip"):
                return SignResult(
                    username=username,
                    success=True,
                    reward=0,
                    continuous_days=continuous_days,
                    message="今日已签到",
                )
            else:
                return SignResult(
                    username=username,
                    success=True,
                    reward=ret.get("reward", 0),
                    continuous_days=continuous_days,
                    message=ret.get("message", ""),
                )
        else:
            return SignResult(
                username=username,
                success=False,
                reward=0,
                continuous_days=continuous_days,
                message=ret.get("message", "签到失败") if ret else "服务异常",
            )
    
    def get_credit_balance(self, username: str) -> Optional[int]:
        """获取指定用户的积分余额"""
        if username not in self.usernames:
            logger.error(f"[!] 未找到账号: {username}")
            return None
        
        # 优先从服务器获取最新数据
        result = self._get_user_info(username)
        if result:
            return result["credit"]
        
        # 失败则从数据库读取
        db_user = get_user(username)
        return db_user.credit if db_user else None
    
    def get_continuous_days(self, username: str) -> Optional[int]:
        """获取指定用户的连续签到天数"""
        if username not in self.usernames:
            logger.error(f"[!] 未找到账号: {username}")
            return None
        
        # 优先从服务器获取最新数据
        result = self._get_user_info(username)
        if result:
            return result["continuous_days"]
        
        # 失败则从数据库读取
        db_user = get_user(username)
        return db_user.continuous_sign_days if db_user else 0


# ==================== 导出 ====================

__all__ = [
    'App',
]