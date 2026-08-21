# apps\hifiti\core\api.py

import hashlib
from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urljoin

import requests

from utils.log import get_logger
from utils.paths import logs
from utils.request_client import RequestClient

logger = get_logger(name="hifiti_api", log_dir=logs(), fmt_type="detailed")


class HifitiEndpoints:
    """Hifiti API 端点配置"""

    BASE_URL = "https://www.hifiti.com"

    HTML_MY_CREDITS = "/my-credits.htm"

    JSON_LOGIN = "/user-login.htm"
    JSON_SIGN = "/sg_sign.htm"


class HifitiAPIError(Exception):
    """Hifiti API 请求异常。"""

    def __init__(
        self,
        status_code: int,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message

        super().__init__(message or f"HTTP {status_code}")


def handle_response(
    func: Callable[..., requests.Response],
) -> Callable[..., requests.Response]:
    """
    统一处理 API 请求结果。

    正常响应（HTTP 2xx）：
        返回 requests.Response。

    HTTP 非 2xx 响应：
        记录详细日志。
        抛出 HifitiAPIError，并携带 HTTP 状态码。

    HTTP 请求异常：
        记录异常日志。
        抛出 HifitiAPIError，并保留原始异常作为异常链。

    其他未预期异常：
        记录异常日志。
        原异常继续向上抛出，不进行吞掉或转换。

    注意：
        本装饰器不再返回 None。
        调用方只有两种正常情况：
        1. 获取到有效的 requests.Response。
        2. 发生异常。

        这样上层认证逻辑可以通过捕获 HifitiAPIError，
        判断当前认证方式失败并尝试下一级认证。

    Args:
        func:
            实际执行 HTTP 请求的 API 方法。

    Returns:
        包装后的 API 请求方法。

    Raises:
        HifitiAPIError:
            HTTP 非 2xx 响应或 HTTP 请求异常。
        Exception:
            其他未预期异常原样向上抛出。
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> requests.Response:
        try:
            response = func(*args, **kwargs)

            # HTTP 2xx：请求成功
            if response.ok:
                return response

            # HTTP 非 2xx：记录完整响应信息
            logger.error(
                "API 请求失败: %s\n"
                "状态码: %s\n"
                "原因: %s\n"
                "响应头: %s\n"
                "响应内容: %s",
                func.__name__,
                response.status_code,
                response.reason,
                dict(response.headers),
                response.text,
            )

            raise HifitiAPIError(
                status_code=response.status_code,
                message=response.reason,
            )

        except requests.RequestException as exc:
            # HTTP 请求本身发生异常，例如：
            # - 连接失败
            # - 连接超时
            # - DNS 解析失败
            # - SSL 错误
            logger.exception(
                "API 请求异常: %s",
                func.__name__,
            )

            raise HifitiAPIError(
                status_code=0,
                message=str(exc),
            ) from exc

        except HifitiAPIError:
            # 已经转换成统一的 Hifiti API 异常，
            # 直接继续向上抛出，避免重复处理。
            raise

        except Exception:
            # 其他未预期异常不进行转换，
            # 保留原始异常类型和 traceback，方便定位代码问题。
            logger.exception(
                "API 请求发生未预期异常: %s",
                func.__name__,
            )
            raise

    return wrapper


class HifitiAPI:
    """纯 API 调用层，只负责发送 HTTP 请求"""

    def __init__(self, request_client: RequestClient):
        self.client = request_client
        self.base_url = HifitiEndpoints.BASE_URL

    def _url(self, endpoint: str) -> str:
        """构建完整 URL"""
        return urljoin(self.base_url, endpoint)

    def _ensure_json_mode(self):
        """确保是 JSON 请求模式"""
        headers = self.client.get_headers()
        if "Accept" in headers and "text/html" in headers["Accept"]:
            self.client.set_json_mode()

    def _ensure_html_mode(self):
        """确保是 HTML 请求模式"""
        headers = self.client.get_headers()
        if "Accept" in headers and "application/json" in headers["Accept"]:
            self.client.set_html_mode()

    # ==================== Cookie 管理 ====================

    def set_cookies(self, cookies: dict[str, str]):
        """设置 cookies"""
        self.client.set_cookies(cookies)

    def get_cookies(self) -> dict[str, str]:
        """获取当前 cookies"""
        return self.client.get_cookies_dict()

    def clear_cookies(self):
        """清空 cookies"""
        self.client.clear_cookies()

    # ==================== 认证相关 API ====================

    @handle_response
    def login(self, username: str, passwd: str) -> requests.Response:
        """
        用户名密码登录
        """
        url = self._url(HifitiEndpoints.JSON_LOGIN)
        # 使用字典作为表单数据
        payload = {
            "email": username,
            "password": hashlib.md5(passwd.encode('utf-8')).hexdigest(),
        }

        # 1. 设置完整的请求头
        self.client.update_headers(
            {
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/user-login.htm",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/plain, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
        )

        logger.debug(f"登录: {username}")
        # 2. 使用 data= 发送表单数据，而不是 json=
        response = self.client.post(url, data=payload)

        # 3. 直接从 response.cookies 获取 Cookie
        if response.ok:
            cookies = response.cookies.get_dict()
            if cookies:
                self.set_cookies(cookies)
                logger.debug(f"登录成功，已保存 cookies: {list(cookies.keys())}")

        return response

    # ==================== 用户操作 API ====================

    @handle_response
    def checkin(self) -> requests.Response:
        """
        签到

        注意：使用 Cookie 认证，需要先登录或设置 cookies
        """
        url = self._url(HifitiEndpoints.JSON_SIGN)

        self.client.update_headers(
            {
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/plain, */*; q=0.01",
            }
        )

        response = self.client.post(url)
        return response

    @handle_response
    def get_user_data(self) -> requests.Response:
        """
        获取用户数据（积分/信用）

        从 /my-credits.htm 页面获取用户数据
        """
        url = self._url(HifitiEndpoints.HTML_MY_CREDITS)

        self.client.update_headers(
            {
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/my.htm",
            }
        )
        self._ensure_html_mode()

        response = self.client.get(url)
        return response


__all__ = [
    "HifitiAPI",
    "HifitiAPIError",
    "HifitiEndpoints",
    "handle_response",
]
