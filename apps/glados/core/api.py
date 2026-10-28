# apps\glados\core\api.py

from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from utils.challenge_client import ChallengeClient, ChallengeError
from utils.log import get_logger
from utils.paths import logs
from utils.request_client import RequestClient

logger = get_logger(name="glados_api", log_dir=logs(), fmt_type="detailed")


class GladosEndpoints:
    """Glados API 端点配置"""

    BASE_URL = "https://glados.cloud"

    # 认证相关
    AUTH = "/api/authorization"  # POST 发送验证码
    LOGIN = "/api/login"  # POST 提交验证码登录
    LOGIN_PAGE = "/login"  # GET  登录页面

    # 用户相关
    CHECKIN = "/api/user/checkin"  # POST 签到
    STATUS = "/api/user/status"  # GET  获取用户状态
    CODE = "/api/user/code"  # POST 兑换礼品码
    POINTS = "/api/user/points"  # GET  获取积分信息
    CAKES = "/api/user/cakes"  # GET  获取蛋糕列表
    REDEEM = "/api/user/cake/redeem"  # POST 兑换蛋糕
    EXCHANGE = "/api/user/exchange"  # POST 积分兑换天数

    # 其他（如有需要）
    USAGE = "/api/user/usage"  # GET  获取使用情况
    PROFILE = "/api/user/profile"  # GET  获取用户资料


class GladosAPIError(Exception):
    """GLaDOS API 请求异常。"""

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
        抛出 GladosAPIError，并携带 HTTP 状态码。

    HTTP 请求异常：
        记录异常日志。
        抛出 GladosAPIError，并保留原始异常作为异常链。

    其他未预期异常：
        记录异常日志。
        原异常继续向上抛出，不进行吞掉或转换。

    注意：
        本装饰器不再返回 None。
        调用方只有两种正常情况：
        1. 获取到有效的 requests.Response。
        2. 发生异常。

        这样上层认证逻辑可以通过捕获 GladosAPIError，
        判断当前认证方式失败并尝试下一级认证。

    Args:
        func:
            实际执行 HTTP 请求的 API 方法。

    Returns:
        包装后的 API 请求方法。

    Raises:
        GladosAPIError:
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

            raise GladosAPIError(
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

            raise GladosAPIError(
                status_code=0,
                message=str(exc),
            ) from exc

        except GladosAPIError:
            # 已经转换成统一的 GLaDOS API 异常，
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


class GladosAPI:
    """纯 API 调用层，只负责发送 HTTP 请求"""

    def __init__(
        self,
        request_client: RequestClient,
        challenge_client: ChallengeClient | None = None,
    ):
        self.client = request_client
        self.challenge = challenge_client
        self.base_url = GladosEndpoints.BASE_URL
        self._token = ""

    def _url(self, endpoint: str) -> str:
        """构建完整 URL"""
        return urljoin(self.base_url, endpoint)

    def _site(self) -> str:
        """从 base_url 推导 site 字段（与 Origin 保持一致）。"""
        # https://glados.cloud → glados.cloud
        return urlparse(self.base_url).netloc

    def _ensure_json_mode(self):
        """确保是 JSON 请求模式"""
        # 如果当前不是 JSON 模式，切换
        headers = self.client.get_headers()
        if "Accept" in headers and "text/html" in headers["Accept"]:
            self.client.set_json_mode()

    def set_token(self, token: str):
        """设置认证令牌"""
        self._token = token
        if token:
            self.client.update_headers({"Authorization": token})
        else:
            # 移除 Authorization 头
            self.client.remove_headers(["Authorization"])

    def _ensure_clearance(self, page_url: str) -> None:
        """显式过挑战并把凭证注入主客户端。"""
        if self.challenge is None:
            raise GladosAPIError(
                status_code=0,
                message="未配置 ChallengeClient，无法处理 Cloudflare 挑战",
            )

    # ==================== 认证相关 API ====================

    @handle_response
    def authorization(self, email: str) -> requests.Response:
        """请求发送登录验证码（强制走镜像模式过 Cloudflare）。"""
        if self.challenge is None:
            raise GladosAPIError(
                status_code=0,
                message="未配置 ChallengeClient，无法处理 Cloudflare 挑战",
            )

        payload = {"address": email, "site": self._site()}

        logger.debug(f"请求验证码（镜像）: {email}")
        return self.challenge.mirror_request(
            method="POST",
            path=GladosEndpoints.AUTH,
            hostname=self._site(),
            json_body=payload,
            extra_headers={
                "Origin": self.base_url,
                "Referer": self._url(GladosEndpoints.LOGIN_PAGE),
            },
        )

    @handle_response
    def login(self, email: str, mailcode: str) -> requests.Response:
        """
        邮箱验证码登录

        Args:
            email: 邮箱地址
            mailcode: 验证码

        Returns:
            API 原始响应字典
        """
        url = self._url(GladosEndpoints.LOGIN)
        payload = {
            "email": email,
            "mailcode": mailcode,
            "method": "email",
            "site": self._site(),
        }

        self.client.set_referer(self._url(GladosEndpoints.LOGIN_PAGE))
        self.client.update_headers({"Origin": self.base_url})

        logger.debug(f"登录: {email}")
        response = self.client.post(url, json=payload)
        return response

    # ==================== 用户操作 API ====================

    @handle_response
    def checkin(self) -> requests.Response:
        """签到"""
        url = self._url(GladosEndpoints.CHECKIN)
        payload = {"token": "glados.cloud"}

        self._ensure_json_mode()
        response = self.client.post(url, json=payload)
        return response

    @handle_response
    def get_status(self) -> requests.Response:
        """获取用户状态"""
        url = self._url(GladosEndpoints.STATUS)

        self._ensure_json_mode()
        response = self.client.get(url)
        return response

    @handle_response
    def get_points(self) -> requests.Response:
        """获取积分信息"""
        url = self._url(GladosEndpoints.POINTS)

        self._ensure_json_mode()
        response = self.client.get(url)
        return response

    @handle_response
    def redeem_code(self, code: str) -> requests.Response:
        """兑换礼品码"""
        url = self._url(GladosEndpoints.CODE)
        payload = {"code": code.strip().upper().replace(" ", "")}

        self._ensure_json_mode()
        response = self.client.post(url, json=payload, timeout=30)
        return response

    @handle_response
    def get_cakes(self) -> requests.Response:
        """获取蛋糕列表"""
        url = self._url(GladosEndpoints.CAKES)

        self._ensure_json_mode()
        response = self.client.get(url)
        return response

    @handle_response
    def redeem_cake(self, cake_id: int) -> requests.Response:
        """兑换蛋糕"""
        url = self._url(GladosEndpoints.REDEEM)
        payload = {"cakeId": cake_id}

        self._ensure_json_mode()
        response = self.client.post(url, json=payload)
        return response

    @handle_response
    def exchange_points(self, plan_type: str) -> requests.Response:
        """积分兑换天数"""
        url = self._url(GladosEndpoints.EXCHANGE)
        payload = {"planType": plan_type}

        self._ensure_json_mode()
        response = self.client.post(url, json=payload, timeout=30)
        return response

    # ==================== Cookies 透传 ====================

    def get_cookies(self) -> dict[str, str]:
        """获取当前 cookies"""
        return self.client.get_cookies_dict()

    def set_cookies(self, cookies: dict[str, str]):
        """设置 cookies"""
        self.client.set_cookies(cookies)

    def clear_cookies(self):
        """清空 cookies"""
        self.client.clear_cookies()
