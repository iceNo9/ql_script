# modules\hifiti\core\server.py

import requests
from urllib.parse import urljoin
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
import hashlib


from common.log import get_logger
from common.global_config import GlobalConfig, EmailConfig, IMAPConfig
from common.request_client import RequestClient

logger = get_logger(__name__)

BASE_URL = "https://www.hifiti.com"

class Endpoints:
    """端点配置"""    
    HTML_MY = "/my.htm"

    JSON_LOGIN = "/user-login.htm"
    JSON_SIGN = "/sg_sign.htm"


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
    def get_my(self):
        url = self._build_url(Endpoints.HTML_MY)
        extra_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Priority": "u=0, i",
            "Referer": BASE_URL,
            "Sec-fetch-dest": "document",
            "Sec-fetch-mode": "navigate",
            "Sec-fetch-site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }
        logger.debug(f"当前get my cookies：{self.client.get_cookies_dict()}")
        response = self.client.get(url, extra_headers=extra_headers)
    
        if response.status_code == 200:
            logger.debug(f"成功获取 {url}")
            return response.text
        else:
            logger.warning(f"获取 {url} 失败，状态码: {response.status_code}")
            return None

    # -------------------------------
    # JSON
    # -------------------------------
    def post_login(self, email, password):
        url = self._build_url(Endpoints.JSON_LOGIN)
        data = {
            "email": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
        }
        extra_headers = {
            "Accept": "text/plain, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": f"{BASE_URL}/user-login.htm",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }
        self.client.clear_cookies()
        
        try:
            response = self.client.post(url, extra_headers=extra_headers, data=data)
            
            # 获取响应后的 cookies
            updated_cookies = self.client.get_cookies_dict()
            set_cookie = response.headers.get('Set-Cookie', '')
            
            # 判断登录是否成功
            if response.status_code == 200:
                # 尝试解析响应内容
                try:
                    resp_data = response.json()
                    logger.info(f"登录响应: {resp_data}")
                except:
                    resp_data = {"text": response.text}
                
                # 检查是否有 token 或其他成功标志
                if "bbs_token" in updated_cookies or response.status_code == 200:
                    logger.info(f"✅ 登录成功: {email}")
                    return {
                        "success": True,
                        "message": "登录成功",
                        "cookies": updated_cookies,
                        "set_cookie": set_cookie,
                        "response": resp_data
                    }
                else:
                    logger.warning(f"⚠️ 登录响应异常: {response.text}")
                    return {
                        "success": False,
                        "message": "登录响应异常",
                        "cookies": updated_cookies,
                        "set_cookie": set_cookie,
                        "response": resp_data
                    }
            else:
                logger.warning(f"❌ 登录失败，状态码: {response.status_code}")
                return {
                    "success": False,
                    "message": f"登录失败，状态码: {response.status_code}",
                    "cookies": updated_cookies,
                    "set_cookie": set_cookie,
                    "response": response.text
                }
                
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return {
                "success": False,
                "message": f"登录异常: {str(e)}",
                "cookies": self.client.get_cookies_dict(),
                "set_cookie": set_cookie,
                "response": None
            }
        
    def post_sign(self):
        url = self._build_url(Endpoints.JSON_SIGN)
        
        extra_headers = {
            "Accept": "text/plain, */*; q=0.01",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": BASE_URL,  # 从首页发起的签到
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }
        
        try:
            # POST 请求，无请求体（content-length: 0）
            response = self.client.post(url, extra_headers=extra_headers, data={})
            logger.debug(response.text)           
            if response.status_code == 200:
                resp_data = response.json()
                code = resp_data.get('code')
                message = resp_data.get('message', '')
                
                # code == "0" 表示成功
                return {
                    "success": code == "0",
                    "message": message,
                }
            else:
                return {"success": False, "message": f"请求失败: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"签到异常: {e}")
            return {"success": False, "message": str(e)}