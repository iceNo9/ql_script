# modules/southplus/core/app.py

import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Callable, Any, Optional, List, Dict
from functools import wraps

from utils.log import get_logger
from utils.config import GlobalConfig
from utils.request_client import RequestClient

from apps.southplus.core.server import Server
from apps.southplus.core.parser import Parser
from apps.southplus.core.config import ConfigManager

from apps.southplus.core.table import (
    get_user,
    save_user,
    User,
    update_mail,
    update_credit,
)

from apps.southplus.core.notify import (
    TaskResult,
    AccountInfo,
    Notifier
)

logger = get_logger(__name__)


DAILY_INTERVAL_SECONDS = 18 * 3600
WEEKLY_INTERVAL_SECONDS = 158 * 3600

# SP币奖励
DAILY_REWARD = 2
WEEKLY_REWARD = 7

class App:

    def __init__(
        self,
        global_config: GlobalConfig,
        config_manager: ConfigManager
    ):
        self.global_config = global_config
        self.config_manager = config_manager

        self.client = RequestClient(
            proxies=global_config.proxy,
            max_retries=2
        )

        self.server = Server(self.client)
        self.parser = Parser()

        self._task_results: List[TaskResult] = []
        self._account_infos: List[AccountInfo] = []

    # =========================================================
    # 登录（cookie）
    # =========================================================
    def _ensure_login(self, username: str) -> bool:
        cookie = self.config_manager.get_cookie_by_username(username)
        if not cookie:
            logger.error(f"[!] {username} 没有 cookie")
            return False

        cookies = {}
        for item in cookie.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v

        self.server.update_cookies(cookies)
        return True

    # =========================================================
    # 时间工具
    # =========================================================
    def _now(self) -> datetime:
        return datetime.now()

    def _iso(self) -> str:
        return self._now().isoformat()

    def _add_seconds(self, seconds: int) -> str:
        return (self._now() + timedelta(seconds=seconds)).isoformat()

    # =========================================================
    # 任务时间判断
    # =========================================================
    def _can_daily(self, user: User) -> bool:
        if not user.next_daily_time:
            return True
        return datetime.fromisoformat(user.next_daily_time) <= self._now()

    def _can_weekly(self, user: User) -> bool:
        if not user.next_weekly_time:
            return True
        return datetime.fromisoformat(user.next_weekly_time) <= self._now()

    # =========================================================
    # 日常
    # =========================================================
    def _handle_daily(self, username: str, user: User) -> Optional[str]:
        """执行日常任务，返回完成消息"""
        if not self._can_daily(user):
            return None

        if not self._ensure_login(username):
            return None

        apply_xml = self.server.get_sign_daily()
        ok, msg = self.parser.parse_sign_result(apply_xml)

        html = self.server.get_tasks_actions()

        if not self.parser.can_complete_daily(html):
            return None

        finish_xml = self.server.get_complete_daily()
        ok2, msg2 = self.parser.parse_sign_result(finish_xml)

        if not ok2:
            logger.info(f"[daily] {username} 完成失败: {msg2}")
            return None

        user.last_daily_time = self._iso()
        user.next_daily_time = self._add_seconds(DAILY_INTERVAL_SECONDS)
        user.daily_count += 1

        save_user(user)

        return f"daily success: {msg2} (+{DAILY_REWARD} SP币)"

    # =========================================================
    # 周常
    # =========================================================
    def _handle_weekly(self, username: str, user: User) -> Optional[str]:
        """执行周常任务，返回完成消息"""
        if not self._can_weekly(user):
            return None

        if not self._ensure_login(username):
            return None

        apply_xml = self.server.get_sign_weekly()
        ok, msg = self.parser.parse_sign_result(apply_xml)

        html = self.server.get_tasks_actions()

        if not self.parser.can_complete_weekly(html):
            return None

        finish_xml = self.server.get_complete_weekly()
        ok2, msg2 = self.parser.parse_sign_result(finish_xml)

        if not ok2:
            logger.info(f"[weekly] {username} 完成失败: {msg2}")
            return None
        
        user.last_weekly_time = self._iso()
        user.next_weekly_time = self._add_seconds(WEEKLY_INTERVAL_SECONDS)
        user.weekly_count += 1

        save_user(user)

        return f"weekly success: {msg2} (+{WEEKLY_REWARD} SP币)"
    
    # =========================================================
    # SP币查询
    # =========================================================
    def get_user_sp_coin(self, username: str) -> Optional[int]:
        """从网站获取用户当前的SP币（实时）"""
        if not self._ensure_login(username):
            logger.error(f"[SP查询] {username} 登录失败")
            return None
        
        html = self.server.get_profile()
        if not html:
            logger.error(f"[SP查询] {username} 获取个人资料失败")
            return None
        
        sp_coin = self.parser.get_sp_coin(html)
        logger.info(f"[SP查询] {username} 当前SP币: {sp_coin}")
        return sp_coin

    def sync_sp_coin_from_web(self, username: str = None) -> bool:
        """
        从网站同步SP币到数据库（只更新 credit，不更新 last_credit）
        """
        if username:
            sp = self.get_user_sp_coin(username)
            if sp is not None:
                user = get_user(username)
                if not user:
                    user = User(username=username)
                # ❌ 删除：不再更新 last_credit
                # user.last_credit = user.credit
                user.credit = sp
                save_user(user)
                logger.info(f"[同步] {username} SP币已更新: {sp}")
                return True
            return False
        else:
            for username in self.config_manager.get_all_usernames():
                self.sync_sp_coin_from_web(username)
            return True
        
    # =========================================================
    # 主流程
    # =========================================================
    def run(self):
        """执行主流程，收集所有用户的任务状态"""
        task_results = []

        for username in self.config_manager.get_all_usernames():
            user = get_user(username)
            if not user:
                user = User(username=username)
                save_user(user)

            logger.info(f"[+] 处理 {username}")
            
            # ❌ 删除：不再在任务执行时同步SP币
            # self.sync_sp_coin_from_web(username)
            
            # 执行任务
            daily_msg = self._handle_daily(username, user)
            weekly_msg = self._handle_weekly(username, user)
            
            # 收集消息
            messages = []
            if daily_msg:
                messages.append(daily_msg)
            if weekly_msg:
                messages.append(weekly_msg)
            
            message = "; ".join(messages) if messages else "无任务执行"
            
            # 重新获取用户最新数据
            user = get_user(username)
            
            # 创建任务结果
            task_result = TaskResult(
                username=username,
                last_daily_time=user.last_daily_time,
                next_daily_time=user.next_daily_time,
                last_weekly_time=user.last_weekly_time,
                next_weekly_time=user.next_weekly_time,
                message=message
            )
            task_results.append(task_result)

        self._task_results = task_results
        return task_results

    # =========================================================
    # 账户信息
    # =========================================================
    def collect_account_infos(self):
        """收集账户信息（用于邮件显示）"""
        infos = []

        for username in self.config_manager.get_all_usernames():
            user = get_user(username)
            if not user:
                continue

            # 计算当日变化量 = 当前SP币 - 上次SP币（上次邮件时的值）
            daily_change = user.credit - user.last_credit

            infos.append(
                AccountInfo(
                    username=username,
                    sp_coin=user.credit,
                    last_sp_coin=user.last_credit,
                    daily_count=user.daily_count,
                    weekly_count=user.weekly_count,
                )
            )
            
            logger.info(f"[账户] {username}: 当前={user.credit}, 上次={user.last_credit}, 今日变化={daily_change:+d}")

        self._account_infos = infos
        return infos

    # =========================================================
    # 邮件判断（核心修改：按“日期”去重）
    # =========================================================
    def _today(self) -> str:
        return datetime.now().date().isoformat()

    def should_send_mail(self, user: User) -> bool:
        """
        同一天只发送一次邮件
        """
        if not user.last_mail_time:
            return True

        try:
            last_day = datetime.fromisoformat(user.last_mail_time).date().isoformat()
        except Exception:
            return True

        return last_day != self._today()

    def mark_mail_sent(self, username: str):
        update_mail(username)

    # =========================================================
    # Notifier
    # =========================================================
    def get_notifier(self):
        import yagmail

        mail = self.global_config.email

        smtp = yagmail.SMTP(
            user=mail.username,
            password=mail.password,
            host=mail.smtp.host,
            port=mail.smtp.port,
            smtp_ssl=mail.smtp.secure
        )

        return Notifier(
            smtp_client=smtp,
            email_to=self.global_config.email_to,
            template_path=Path("modules/southplus/templates/report.html"),
            task_results=self._task_results,
            account_infos=self._account_infos
        )

    # =========================================================
    # 邮件发送入口（同一天只发一次）
    # =========================================================
    def send_report_if_needed(self):
        """发送邮件报告（同时更新 last_credit 和 last_mail_time）"""
        
        # 1. 先同步所有用户的当前SP币
        self.sync_sp_coin_from_web()
        
        # 2. 收集账户信息（此时会计算变化量）
        self.collect_account_infos()
        
        # 3. 检查是否需要发送
        any_user = None
        for u in self.config_manager.get_all_usernames():
            dbu = get_user(u)
            if dbu:
                any_user = dbu
                break

        if not any_user:
            return False

        if not self.should_send_mail(any_user):
            logger.info("[mail] 今日已发送，跳过")
            return False

        # 4. 发送邮件
        notifier = self.get_notifier()
        ok = notifier.send()

        # 5. 发送成功后，更新所有用户的 last_credit 和 last_mail_time
        if ok:
            for username in self.config_manager.get_all_usernames():
                user = get_user(username)
                if user:
                    # 将当前SP币保存到 last_credit
                    user.last_credit = user.credit
                    # 更新邮件发送时间
                    user.last_mail_time = self._iso()
                    save_user(user)
                    logger.info(f"[邮件] {username} last_credit 更新为 {user.last_credit}, last_mail_time 更新")
            
            logger.info("[mail] 邮件发送成功，已更新所有用户的 last_credit 和 last_mail_time")
        
        return ok