# modules\baiyefee\core\server.py

import requests
from urllib.parse import urljoin
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
import hashlib


from utils.log import get_logger
from utils.global_config import GlobalConfig, EmailConfig, IMAPConfig
from utils.request_client import RequestClient

logger = get_logger(__name__)

BASE_URL = "https://www.baiyefee.com"

class Endpoints:
    """端点配置"""    
    JSON_LOGIN = "/wp-json/jwt-auth/v1/token"
    JSON_USER_INFO = "/wp-json/b2/v1/getUserInfo"
    JSON_SIGN = "/wp-json/b2/v1/userMission"
    JSON_SIGN_INFO = "/wp-json/b2/v1/getUserMission"

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
    # JSON
    # -------------------------------
    def post_login(self, username, password):
        url = self._build_url(Endpoints.JSON_LOGIN)
        data = {
            "username": username,
            "password": password,
        }
        extra_headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": BASE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
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
                if "b2_token" in updated_cookies or response.status_code == 200:
                    logger.info(f"✅ 登录成功: {username}")
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
        
    def post_user_info(self):
        url = self._build_url(Endpoints.JSON_USER_INFO)
        token = self.get_cookies().get("b2_token", '')
        extra_headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": BASE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            response = self.client.post(url, extra_headers=extra_headers)
                        
            if response.status_code == 200:
                try:
                    resp_data = response.json()
                    logger.info(f"获取用户信息成功: {resp_data}")
                    return {
                        "success": True,
                        "message": "获取用户信息成功",
                        "data": resp_data,
                    }
                except Exception as e:
                    logger.error(f"解析用户信息响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"解析响应失败: {str(e)}",
                        "data": None,
                    }
            else:
                logger.warning(f"获取用户信息失败，状态码: {response.status_code}, 响应: {response.text}")
                return {
                    "success": False,
                    "message": f"获取用户信息失败，状态码: {response.status_code}",
                    "data": None,
                    "response": response.text,
                }
                
        except Exception as e:
            logger.error(f"获取用户信息异常: {e}")
            return {
                "success": False,
                "message": f"获取用户信息异常: {str(e)}",
                "data": None,
            }
        
    def post_sign(self):
        url = self._build_url(Endpoints.JSON_SIGN)
        token = self.get_cookies().get("b2_token", '')
        extra_headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": BASE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            response = self.client.post(url, extra_headers=extra_headers)
            
            if response.status_code == 200:
                try:
                    resp_data = response.json()
                    # 根据实际API返回结构判断签到结果
                    if resp_data and "credit" in resp_data:
                        logger.info(f"签到成功: {resp_data}")
                        return {
                            "success": True,
                            "message": resp_data.get("msg", "签到成功"),
                            "data": resp_data,
                        }
                    else:
                        logger.warning(f"签到失败: {resp_data}")
                        return {
                            "success": False,
                            "message": resp_data.get("msg", "签到失败"),
                            "data": resp_data,
                        }
                except Exception as e:
                    logger.error(f"解析签到响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"解析响应失败: {str(e)}",
                        "data": None,
                    }
            else:
                logger.warning(f"签到请求失败，状态码: {response.status_code}, 响应: {response.text}")
                return {
                    "success": False,
                    "message": f"签到请求失败，状态码: {response.status_code}",
                    "data": None,
                    "response": response.text,
                }
                
        except Exception as e:
            logger.error(f"签到异常: {e}")
            return {
                "success": False,
                "message": f"签到异常: {str(e)}",
                "data": None,
            }
        
    
    def post_sign_info(self):
        url = self._build_url(Endpoints.JSON_SIGN_INFO)
        token = self.get_cookies().get("b2_token", '')
        extra_headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "Content-type": "application/x-www-form-urlencoded",
            "Origin": BASE_URL,
            "Priority": "u=1, i",
            "Referer": f"{BASE_URL}/mission/today",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            response = self.client.post(url, extra_headers=extra_headers)

            if response.status_code == 200:
                try:
                    resp_data = response.json()

                    # 根据实际API返回结构判断结果
                    if resp_data and "mission" in resp_data:
                        logger.info(f"获取签到信息成功: {resp_data}")

                        return {
                            "success": True,
                            "message": resp_data.get("msg", "获取签到信息成功"),
                            "data": resp_data,
                        }
                    else:
                        logger.warning(f"获取签到信息失败: {resp_data}")

                        return {
                            "success": False,
                            "message": resp_data.get("msg", "获取签到信息失败"),
                            "data": resp_data,
                        }

                except Exception as e:
                    logger.error(f"解析签到信息响应失败: {e}")

                    return {
                        "success": False,
                        "message": f"解析响应失败: {str(e)}",
                        "data": None,
                    }

            else:
                logger.warning(
                    f"获取签到信息请求失败，状态码: {response.status_code}, 响应: {response.text}"
                )

                return {
                    "success": False,
                    "message": f"获取签到信息请求失败，状态码: {response.status_code}",
                    "data": None,
                    "response": response.text,
                }

        except Exception as e:
            logger.error(f"获取签到信息异常: {e}")

            return {
                "success": False,
                "message": f"获取签到信息异常: {str(e)}",
                "data": None,
            }