# modules/southplus/core/parser.py

import re
import time
from typing import Optional, Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

from common.log import get_logger

logger = get_logger(__name__)


class Parser:
    """页面解析器"""
    
    # ==================== SP币 ====================    
    def get_sp_coin(seelf, html: str) -> int:
        """
        获取 SouthPlus 用户 SP币

        示例:
            SP币: 207 G

        Returns:
            int: SP币数量
        """
        if not html:
            return 0

        # 先用正则，速度最快
        match = re.search(r"SP币:\s*(\d+)\s*G", html)
        if match:
            return int(match.group(1))

        # 正则失败再尝试 BeautifulSoup
        try:
            soup = BeautifulSoup(html, "html.parser")

            text = soup.get_text(" ", strip=True)

            match = re.search(r"SP币:\s*(\d+)\s*G", text)
            if match:
                return int(match.group(1))

        except Exception as e:
            logger.warning(f"解析SP币失败: {e}")

        return 0
    
    def parse_sign_result(self, xml: str) -> Tuple[bool, str]:
        """
        解析任务申请结果

        Returns:
            (是否成功, 提示信息)

        示例:
            (True, "已经申请[日常]完成,请赶紧去完成任务吧!")
            (False, "拒离上次申请[日常]还没超过18小时")
        """

        if not xml:
            return False, "返回为空"

        match = re.search(
            r"<!\[CDATA\[(.*?)\]\]>",
            xml,
            re.S,
        )

        if not match:
            return False, "解析失败"

        content = match.group(1).strip()

        if content.startswith("success"):
            return True, content[len("success"):].strip()

        if content.startswith("confirm"):
            return False, content[len("confirm"):].strip()

        return False, content
    
    def can_complete_weekly(self, html: str) -> bool:
        """
        是否可领取周常奖励(任务14)
        """
        if not html:
            return False

        return bool(
            re.search(
                r"startjob\s*\(\s*['\"]14['\"]\s*\)",
                html,
                re.I,
            )
        )

    def can_complete_daily(self, html: str) -> bool:
        """
        是否可领取日常奖励(任务15)
        """
        if not html:
            return False

        return bool(
            re.search(
                r"startjob\s*\(\s*['\"]15['\"]\s*\)",
                html,
                re.I,
            )
        )