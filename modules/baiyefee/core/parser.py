# modules/baiyefee/core/parser.py

import re
import time
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

from common.log import get_logger

logger = get_logger(__name__)


class Parser:
    """页面解析器"""
    
    # ==================== 积分 ====================    
    def get_credit(self, user_info_result: Dict[str, Any]) -> int:
        """
        从用户信息中获取积分/信用值
        
        Args:
            user_info_result: post_user_info 返回的结果字典
            
        Returns:
            积分值，获取失败返回 0
        """
        # 检查请求是否成功
        if not user_info_result.get("success"):
            logger.warning("获取用户信息失败，无法获取积分")
            return 0
        
        # 获取数据部分
        data = user_info_result.get("data", {})
        if not data:
            logger.warning("用户信息数据为空")
            return 0
        
        # 从 user_data.credit 获取积分
        user_data = data.get("user_data", {})
        credit_str = user_data.get("credit", "0")
        
        # 尝试转换为整数
        try:
            credit = int(credit_str)
            logger.debug(f"获取到积分: {credit}")
            return credit
        except (ValueError, TypeError) as e:
            logger.error(f"积分转换失败: {credit_str}, 错误: {e}")
            return 0
    
    # ==================== 登录Cookie 解析 ====================
    def get_cookie_expires_timestamp(self, login_result: Dict[str, Any]) -> Optional[int]:
        """
        从登录结果中解析 Cookie 到期时间戳（取 bbs_token 的 Max-Age）
        """
        if not login_result:
            return None

        set_cookie = login_result.get("set_cookie", "")

        if not set_cookie:
            return None

        # 优先使用 Max-Age
        max_ages = [
            int(v)
            for v in re.findall(
                r"Max-Age=(\d+)",
                set_cookie,
                re.IGNORECASE
            )
        ]

        if max_ages:
            return int(time.time()) + min(max_ages)

        # 其次使用 Expires
        expires_matches = re.findall(
            r"Expires=([^;]+)",
            set_cookie,
            re.IGNORECASE
        )

        timestamps = []

        for expires_str in expires_matches:
            try:
                timestamps.append(
                    int(
                        parsedate_to_datetime(
                            expires_str.strip()
                        ).timestamp()
                    )
                )
            except Exception:
                pass

        if timestamps:
            return min(timestamps)

        return None