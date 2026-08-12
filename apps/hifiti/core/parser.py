# modules/hifiti/core/parser.py

import re
import time
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from utils.log import get_logger

logger = get_logger(__name__)


class Parser:
    """页面解析器"""
    
    # ==================== 金币 ====================    
    def get_coin_balance(self, html: str) -> Optional[int]:
        """
        获取金币余额
        
        Args:
            html: HTML 字符串
            
        Returns:
            金币数量，未找到返回 None
        """
        if not html:            return None
        
        # 方法1：正则匹配（最快）
        patterns = [
            r'金币：</span><em[^>]*>(\d+)</em>',
            r'金币：.*?>(\d+)</em>',
            r'<em[^>]*style="[^"]*color: #f57e42[^"]*"[^>]*>(\d+)</em>',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return int(match.group(1))
        
        # 方法2：BeautifulSoup 解析
        soup = BeautifulSoup(html, 'html.parser')
        for em in soup.find_all('em'):
            parent_text = em.find_parent() or em
            if '金币' in parent_text.get_text():
                text = em.get_text(strip=True)
                if text.isdigit():
                    return int(text)
        
        return None
    
    # ==================== 签到响应解析 ====================    
    def get_sign_reward(self, sign_result: Dict[str, Any]) -> int:
        """
        从签到结果中解析获得的金币数量
        
        Args:
            sign_result: post_sign 返回的字典
                {"success": True, "message": "成功签到！今日排名4821，总奖励2金币！"}
        
        Returns:
            获得的金币数量，未找到返回 0
        """
        if not sign_result or not sign_result.get("success", False):
            return 0
        
        message = sign_result.get('message', '')
        
        if not message:
            return 0
        
        patterns = [
            r'总奖励(\d+)金币',
            r'奖励(\d+)金币',
            r'获得(\d+)金币',
            r'得到(\d+)金币',
            r'\+(\d+)金币',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1))
        
        return 0
    
    def get_sign_rank(self, sign_result: Dict[str, Any]) -> int:
        """
        从签到结果中解析今日排名
        
        Args:
            sign_result: post_sign 返回的字典
                {"success": True, "message": "成功签到！今日排名4821，总奖励2金币！"}
        
        Returns:
            今日排名，未找到返回 0
        """
        if not sign_result or not sign_result.get("success", False):
            return 0
        
        message = sign_result.get('message', '')
        
        if not message:
            return 0
        
        patterns = [
            r'今日排名(\d+)',
            r'排名(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1))
        
        return 0
    
    # ==================== 登录Cookie 解析 ====================
    def get_cookie_expires_timestamp(self, login_result: Dict[str, Any]) -> Optional[int]:
        """
        从登录结果中解析 Cookie 到期时间戳（取 bbs_token 的 Max-Age）
        """
        if not login_result:
            return None
        
        set_cookie = login_result.get('set_cookie', '')
        
        if not set_cookie:
            return None
        
        # 查找 bbs_token 的 Max-Age
        match = re.search(r'bbs_token=.*?Max-Age=(\d+)', set_cookie, re.IGNORECASE)
        if match:
            max_age = int(match.group(1))
            return int(time.time()) + max_age
        
        # 备选：查找任意 Max-Age
        match = re.search(r'Max-Age=(\d+)', set_cookie)
        if match:
            max_age = int(match.group(1))
            return int(time.time()) + max_age
        
        return None