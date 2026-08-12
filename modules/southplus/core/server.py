# modules\southplus\core\server.py

import requests
from urllib.parse import urljoin
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
import hashlib


from utils.log import get_logger
from utils.config import GlobalConfig, EmailConfig, IMAPConfig
from utils.request_client import RequestClient

logger = get_logger(__name__)

BASE_URL = "https://bbs.south-plus.org"

class Endpoints:
    """端点配置"""
    HTML_PROFILE = "/profile.php"
    HTML_TASKS = "/plugin.php?H_name-tasks.html"
    HTML_TASKS_ACTIONS = "/plugin.php?H_name-tasks-actions-newtasks.html.html" # 进行中的任务

    XML_SIGN = "/plugin.php"

class Server:
    """服务器接口封装类"""
    
    def __init__(self, request_client: RequestClient):
        """
        初始化 服务器接口
        
        Args:
            request_client: 请求客户端实例
        """
        self.client = request_client
        self.base_url = BASE_URL
        
    # -------------------------------
    # 基础请求方法
    # -------------------------------    
    def _build_url(self, endpoint: str) -> str:
        """构建完整 URL"""
        return urljoin(self.base_url, endpoint)
    
    # -------------------------------
    # Cookies 管理
    # -------------------------------    
    def update_cookies(self, cookies: Dict[str, str]):
        """
        更新客户端的cookies
        
        Args:
            cookies: cookies字典
        """
        self.client.set_cookies(cookies)
        logger.debug(f"[*] Cookies已更新{cookies}")
    
    def get_cookies(self) -> Dict[str, str]:
        """
        获取当前cookies
        
        Returns:
            cookies字典
        """
        return self.client.get_cookies_dict()
    
    def clear_cookies(self):
        """清空cookies"""
        self.client.clear_cookies()
        logger.debug("[*] Cookies已清空")

    # -------------------------------
    # HTML
    # -------------------------------
    def get_profile(self):
        url = self._build_url(Endpoints.HTML_PROFILE)
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": f"{BASE_URL}/u.php",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }
        
        response = self.client.get(url, extra_headers=extra_headers)
    
        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text
        else:
            logger.warning(f"获取 {url} 失败，状态码: {response.status_code}")
            return None
        
    def get_tasks(self):
        url = self._build_url(Endpoints.HTML_TASKS)
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": f"{BASE_URL}/index.php",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }
        
        response = self.client.get(url, extra_headers=extra_headers)
    
        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text
        else:
            logger.warning(f"获取 {url} 失败，状态码: {response.status_code}")
            return None
    
    def get_tasks_actions(self):
        url = self._build_url(Endpoints.HTML_TASKS_ACTIONS)
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": self._build_url(Endpoints.HTML_TASKS),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }
        
        response = self.client.get(url, extra_headers=extra_headers)
    
        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text
        else:
            logger.warning(f"获取 {url} 失败，状态码: {response.status_code}")
            return None
    
    # -------------------------------
    # XML
    # -------------------------------
    def get_sign_daily(self):
        url = self._build_url(Endpoints.XML_SIGN)
        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": "job",
            "cid": 15,
        }
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": self._build_url(Endpoints.HTML_TASKS),
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }

        response = self.client.get(
            url,
            params=params,
            extra_headers=extra_headers,
        )

        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text

        logger.warning(
            f"获取 {url} 失败，状态码: {response.status_code}"
        )
        return None


    def get_sign_weekly(self):
        url = self._build_url(Endpoints.XML_SIGN)
        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": "job",
            "cid": 14,
        }
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": self._build_url(Endpoints.HTML_TASKS),
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }

        response = self.client.get(
            url,
            params=params,
            extra_headers=extra_headers,
        )

        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text

        logger.warning(
            f"获取 {url} 失败，状态码: {response.status_code}"
        )
        return None
    
    def get_complete_daily(self):
        url = self._build_url(Endpoints.XML_SIGN)
        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": "job2",
            "cid": 15,
        }
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": self._build_url(Endpoints.HTML_TASKS),
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }

        response = self.client.get(
            url,
            params=params,
            extra_headers=extra_headers,
        )

        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text

        logger.warning(
            f"获取 {url} 失败，状态码: {response.status_code}"
        )
        return None


    def get_complete_weekly(self):
        url = self._build_url(Endpoints.XML_SIGN)
        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": "job2",
            "cid": 14,
        }
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=1, i",
            "Referer": self._build_url(Endpoints.HTML_TASKS),
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }

        response = self.client.get(
            url,
            params=params,
            extra_headers=extra_headers,
        )

        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text

        logger.warning(
            f"获取 {url} 失败，状态码: {response.status_code}"
        )
        return None
    
    