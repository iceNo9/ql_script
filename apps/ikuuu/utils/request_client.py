# modules\glados\utils\request_client.py

import time
import requests
from typing import Optional, List, Dict
from utils.log import get_logger

logger = get_logger(__name__)

class RequestClient:
    """封装请求客户端，支持代理列表与重试"""

    def __init__(self, proxies: Optional[List[str]] = None, max_retries: int = 3):
        """
        初始化请求客户端
        
        Args:
            proxies: 初始化代理列表，例如 ["http://127.0.0.1:7890", ...]
            max_retries: 最大重试次数
        """
        self.proxies_list = proxies or []
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

    def _get_proxies(self, proxy_url: Optional[str] = None) -> Optional[Dict[str, str]]:
        """根据传入的proxy_url或初始化代理列表返回代理字典"""
        proxy = proxy_url or (self.proxies_list[0] if self.proxies_list else None)
        if proxy:
            return {"http": proxy, "https": proxy}
        return None

    def request(self, method: str, url: str, proxy_url: Optional[str] = None, **kwargs) -> requests.Response:
        """
        发送请求，优先使用代理
        
        Args:
            method: HTTP方法
            url: 请求URL
            proxy_url: 临时使用的代理地址
            **kwargs: requests参数
        """
        last_exception = None
        proxies_to_try = []

        # 构建尝试顺序
        if proxy_url:
            proxies_to_try.append(proxy_url)
        elif self.proxies_list:
            proxies_to_try.extend(self.proxies_list)
        proxies_to_try.append(None)  # 最后尝试直连
        
        response = None  # 初始化
        for proxy in proxies_to_try:
            method_name = f"代理({proxy})" if proxy else "直连"
            for attempt in range(self.max_retries):
                try:
                    proxies_dict = self._get_proxies(proxy)
                    if 'timeout' not in kwargs:
                        kwargs['timeout'] = 30

                    logger.debug(f"[*] 尝试 {method_name} 请求 {url} (尝试 {attempt+1}/{self.max_retries})")

                    response = self.session.request(
                        method=method,
                        url=url,
                        proxies=proxies_dict,
                        **kwargs
                    )

                    logger.debug(f"[*] {method_name} 请求 {url} - 状态码: {response.status_code}")

                    if response.status_code < 500:
                        logger.info(f"[+] {method_name} 请求成功: {url}")
                        return response  # 这里一定不是 None

                    logger.warning(f"[!] {method_name} 请求失败: {url} - 状态码: {response.status_code}")

                except (requests.ConnectionError, requests.Timeout) as e:
                    last_exception = e
                    logger.warning(f"[!] {method_name} 网络异常 (尝试 {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(1)
                    continue
                except Exception as e:
                    last_exception = e
                    logger.error(f"[!] {method_name} 请求异常: {e}")
                    break

        # 循环结束后，如果 response 不存在或所有尝试失败，抛异常
        if response is not None and response.status_code < 500:
            return response

        # 如果有最后异常就抛
        if last_exception:
            raise last_exception

        # 所有方式都失败
        raise RuntimeError(f"所有请求方式失败: {url}")


    # GET / POST 快捷方法
    def get(self, url: str, proxy_url: Optional[str] = None, **kwargs) -> requests.Response:
        return self.request("GET", url, proxy_url=proxy_url, **kwargs)

    def post(self, url: str, proxy_url: Optional[str] = None, **kwargs) -> requests.Response:
        return self.request("POST", url, proxy_url=proxy_url, **kwargs)

    # Cookies 操作
    def set_cookies(self, cookies: Dict[str, str]):
        self.session.cookies.clear()
        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    def get_cookies_dict(self) -> Dict[str, str]:
        return requests.utils.dict_from_cookiejar(self.session.cookies)

    def clear_cookies(self):
        self.session.cookies.clear()