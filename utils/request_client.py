# common\request_client.py

import time
import requests
from typing import Optional, List, Dict, Any
from utils.log import get_logger

logger = get_logger(__name__)

class RequestClient:
    """封装请求客户端，支持代理列表与重试"""
    
    # 固定的设备指纹（方案一：最安全的做法）
    # 这些是模拟浏览器身份的核心字段，在一个会话中固定不变
    _BASE_HEADERS = {
        # 传统 UA
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        # 现代浏览器客户端提示 (必须和 UA 版本一致)
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        # 编码（标准值，基本不变）
        "Accept-Encoding": "gzip, deflate, br",
        # 语言（相对固定，可根据需要修改类变量）
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # 连接方式
        # "Connection": "keep-alive",
    }
    
    # 注意：以下头不在基类中固定，因为不同场景需要不同值：
    # - Accept: 请求 HTML 和请求 JSON 需要不同的值
    # - Referer: 每次请求的来源不同
    # - Cookie: 会话管理，session 自动处理
    # - 伪标头 (:method, :path, :authority, :scheme): 由 HTTP 库自动生成

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
        
        # 应用固定的基础头
        self.session.headers.update(self._BASE_HEADERS.copy())
        
        # 额外存储用户自定义的固定头（不会在请求间丢失）
        self._custom_headers: Dict[str, str] = {}
        
        logger.debug(f"[*] RequestClient 初始化完成，基础头: {list(self.session.headers.keys())}")

    # ==================== Header 管理方法 ====================
    
    def set_headers(self, headers: Dict[str, str], merge: bool = True):
        """
        设置会话级别的固定请求头（会持久化到整个会话）
        
        Args:
            headers: 要设置的请求头字典
            merge: True=合并到现有头，False=完全替换现有头
        """
        if merge:
            self.session.headers.update(headers)
            self._custom_headers.update(headers)
        else:
            # 完全替换：先清除所有非基础的，再设置新的
            self.session.headers.clear()
            self.session.headers.update(self._BASE_HEADERS.copy())
            self.session.headers.update(headers)
            self._custom_headers = headers.copy()
        
        logger.debug(f"[*] 会话级请求头已更新，当前: {list(self.session.headers.keys())}")
    
    def update_headers(self, headers: Dict[str, str]):
        """
        更新会话级别的请求头（等价于 set_headers(..., merge=True) 的快捷方式）
        
        Args:
            headers: 要更新的请求头字典
        """
        self.set_headers(headers, merge=True)
    
    def get_headers(self) -> Dict[str, str]:
        """获取当前会话的所有请求头"""
        return dict(self.session.headers)
    
    def remove_headers(self, keys: List[str]):
        """
        移除指定的请求头
        
        Args:
            keys: 要移除的请求头名称列表
        """
        for key in keys:
            if key in self.session.headers:
                del self.session.headers[key]
            if key in self._custom_headers:
                del self._custom_headers[key]
        logger.debug(f"[*] 已移除请求头: {keys}")
    
    def reset_headers(self):
        """
        重置请求头到初始状态（只保留基础设备指纹）
        """
        self.session.headers.clear()
        self.session.headers.update(self._BASE_HEADERS.copy())
        self._custom_headers.clear()
        logger.debug("[*] 请求头已重置为基础配置")
    
    # ==================== 单次请求级别的 Header 设置 ====================
    
    def _build_request_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        构建单次请求的完整请求头
        
        Args:
            extra_headers: 单次请求额外添加的头（优先级最高）
        
        Returns:
            完整的请求头字典
        """
        # 基础头已在 session.headers 中
        headers = dict(self.session.headers)
        
        # 单次请求的额外头覆盖
        if extra_headers:
            headers.update(extra_headers)
        
        return headers
    
    # ==================== 核心请求方法 ====================
    
    def _get_proxies(self, proxy_url: Optional[str] = None) -> Optional[Dict[str, str]]:
        """根据传入的proxy_url或初始化代理列表返回代理字典"""
        proxy = proxy_url or (self.proxies_list[0] if self.proxies_list else None)
        if proxy:
            return {"http": proxy, "https": proxy}
        return None

    def request(
        self, 
        method: str, 
        url: str, 
        proxy_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> requests.Response:
        """
        发送请求，优先使用代理
        
        Args:
            method: HTTP方法
            url: 请求URL
            proxy_url: 临时使用的代理地址
            extra_headers: 单次请求额外添加的请求头（不会持久化到会话）
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
        
        # 构建请求头（合并单次请求的额外头）
        final_headers = self._build_request_headers(extra_headers)
        
        response = None
        for proxy in proxies_to_try:
            method_name = f"代理({proxy})" if proxy else "直连"
            for attempt in range(self.max_retries):
                try:
                    proxies_dict = self._get_proxies(proxy)
                    if 'timeout' not in kwargs:
                        kwargs['timeout'] = 30

                    logger.debug(f"[*] 尝试 {method_name} 请求 {url} (尝试 {attempt+1}/{self.max_retries})")
                    logger.debug(f"[*] 请求头: {final_headers}")

                    response = self.session.request(
                        method=method,
                        url=url,
                        proxies=proxies_dict,
                        headers=final_headers,  # 使用合并后的头
                        **kwargs
                    )

                    logger.debug(f"[*] {method_name} 请求 {url} - 状态码: {response.status_code}")

                    if response.status_code < 500:
                        logger.info(f"[+] {method_name} 请求成功: {url}")
                        return response

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

        if last_exception:
            raise last_exception

        raise RuntimeError(f"所有请求方式失败: {url}")

    # ==================== GET / POST 快捷方法 ====================
    
    def get(
        self, 
        url: str, 
        proxy_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> requests.Response:
        """GET 请求"""
        return self.request("GET", url, proxy_url=proxy_url, extra_headers=extra_headers, **kwargs)

    def post(
        self, 
        url: str, 
        proxy_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> requests.Response:
        """POST 请求"""
        return self.request("POST", url, proxy_url=proxy_url, extra_headers=extra_headers, **kwargs)

    # ==================== Cookies 操作 ====================
    
    def set_cookies(self, cookies: Dict[str, str]):
        """设置会话级 Cookie"""
        self.session.cookies.clear()
        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    def get_cookies_dict(self) -> Dict[str, str]:
        """获取当前 Cookie 字典"""
        return requests.utils.dict_from_cookiejar(self.session.cookies)

    def clear_cookies(self):
        """清空 Cookie"""
        self.session.cookies.clear()
    
    # ==================== 便捷方法：特定场景的 Header 预设 ====================
    
    def set_html_mode(self):
        """
        设置为请求 HTML 页面的模式
        自动设置合适的 Accept 头
        """
        self.update_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })
        logger.info("[*] 已切换到 HTML 请求模式")
    
    def set_json_mode(self):
        """
        设置为请求 JSON API 的模式
        自动设置合适的 Accept 头
        """
        self.update_headers({
            "Accept": "application/json, text/plain, */*",
        })
        # 如果有 Upgrade-Insecure-Requests 则移除（JSON 模式不需要）
        if "Upgrade-Insecure-Requests" in self.session.headers:
            del self.session.headers["Upgrade-Insecure-Requests"]
        logger.info("[*] 已切换到 JSON API 请求模式")
    
    def set_referer(self, referer: str):
        """
        设置 Referer 头（会话级，后续所有请求都会带）
        
        Args:
            referer: 来源 URL
        """
        self.update_headers({"Referer": referer})
    
    def set_origin(self, origin: str):
        """
        设置 Origin 头（会话级）
        
        Args:
            origin: 源站 URL
        """
        self.update_headers({"Origin": origin})