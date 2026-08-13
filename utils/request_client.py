# common/request_client.py

import time
from urllib.parse import urlparse

import requests
from requests.utils import should_bypass_proxies

from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="request_client",
    log_dir=logs(),
    fmt_type="detailed",
)


class RequestClient:
    """封装 HTTP 请求客户端，支持代理、NO_PROXY 与重试。"""

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

    def __init__(
        self,
        http_proxies: list[str] | None = None,
        https_proxies: list[str] | None = None,
        no_proxy: list[str] | None = None,
        max_retries: int = 3,
    ):
        """
        初始化请求客户端。

        Args:
            http_proxies:
                HTTP 请求使用的代理列表。

            https_proxies:
                HTTPS 请求使用的代理列表。

            no_proxy:
                不使用代理的地址列表。

            max_retries:
                每个代理的最大重试次数。
        """
        self.http_proxies = http_proxies or []
        self.https_proxies = https_proxies or []
        self.no_proxy = no_proxy or []
        self.max_retries = max_retries

        self.session = requests.Session()

        # 应用固定的基础请求头
        self.session.headers.update(self._BASE_HEADERS.copy())

        # 用户自定义的会话级请求头
        self._custom_headers: dict[str, str] = {}

        logger.debug(
            "RequestClient 初始化完成，基础头: %s",
            list(self.session.headers.keys()),
        )

    # ========================================================================
    # Proxy
    # ========================================================================

    def _should_bypass_proxy(self, url: str) -> bool:
        """判断当前 URL 是否应该绕过代理。"""

        if not self.no_proxy:
            return False

        no_proxy = ",".join(self.no_proxy)

        try:
            return should_bypass_proxies(
                url,
                no_proxy=no_proxy,
            )
        except ValueError:
            logger.warning(
                "NO_PROXY 配置无效，URL: %s，NO_PROXY: %s",
                url,
                no_proxy,
            )
            return False

    def _get_proxy_list(
        self,
        url: str,
        proxy_url: str | None = None,
    ) -> list[str | None]:
        """
        获取当前请求的代理尝试列表。

        尝试顺序：

        1. 指定的临时代理
        2. 当前协议对应的代理列表
        3. 直连

        如果 URL 命中 NO_PROXY，则直接直连。

        Args:
            url:
                请求 URL。

            proxy_url:
                临时指定的代理。

        Returns:
            代理列表。
            None 表示直连。
        """

        # 临时代理拥有最高优先级。
        if proxy_url:
            return [proxy_url, None]

        # NO_PROXY 命中，直接连接。
        if self._should_bypass_proxy(url):
            return [None]

        scheme = urlparse(url).scheme.lower()

        if scheme == "https":
            proxies = self.https_proxies
        elif scheme == "http":
            proxies = self.http_proxies
        else:
            logger.warning(
                "不支持的 URL 协议: %s，使用直连: %s",
                scheme,
                url,
            )
            return [None]

        # 代理全部失败后最终尝试直连。
        return [*proxies, None]

    @staticmethod
    def _build_proxy_dict(proxy: str | None) -> dict[str, str] | None:
        """
        将单个代理地址转换为 requests proxies 格式。

        Args:
            proxy:
                代理地址。

        Returns:
            requests proxies 字典。
        """

        if not proxy:
            return None

        return {
            "http": proxy,
            "https": proxy,
        }

    # ========================================================================
    # Header 管理
    # ========================================================================

    def set_headers(
        self,
        headers: dict[str, str],
        merge: bool = True,
    ) -> None:
        """
        设置会话级别的固定请求头。

        Args:
            headers:
                要设置的请求头。

            merge:
                True:
                    合并到现有请求头。

                False:
                    清除当前自定义请求头后重新设置。
        """

        if merge:
            self.session.headers.update(headers)
            self._custom_headers.update(headers)

        else:
            self.session.headers.clear()
            self.session.headers.update(self._BASE_HEADERS.copy())
            self.session.headers.update(headers)
            self._custom_headers = headers.copy()

        logger.debug(
            "会话级请求头已更新，当前: %s",
            list(self.session.headers.keys()),
        )

    def update_headers(
        self,
        headers: dict[str, str],
    ) -> None:
        """
        更新会话级别的请求头。

        等价于：

            set_headers(headers, merge=True)
        """
        self.set_headers(headers, merge=True)

    def get_headers(self) -> dict[str, str]:
        """获取当前会话的所有请求头。"""
        return dict(self.session.headers)

    def remove_headers(self, keys: list[str]) -> None:
        """移除指定的请求头。"""

        for key in keys:
            if key in self.session.headers:
                del self.session.headers[key]

            if key in self._custom_headers:
                del self._custom_headers[key]

        logger.debug(
            "已移除请求头: %s",
            keys,
        )

    def reset_headers(self) -> None:
        """重置请求头到初始状态，只保留基础设备指纹。"""

        self.session.headers.clear()
        self.session.headers.update(self._BASE_HEADERS.copy())
        self._custom_headers.clear()

        logger.debug("请求头已重置为基础配置")

    # ========================================================================
    # 单次请求 Header
    # ========================================================================

    def _build_request_headers(
        self,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        构建单次请求的完整请求头。

        Args:
            extra_headers:
                单次请求额外的请求头。
                优先级高于会话级请求头。

        Returns:
            完整请求头。
        """

        headers = dict(self.session.headers)

        if extra_headers:
            headers.update(extra_headers)

        return headers

    # ========================================================================
    # 核心请求
    # ========================================================================

    def request(
        self,
        method: str,
        url: str,
        proxy_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        **kwargs,
    ) -> requests.Response:
        """
        发送 HTTP 请求。

        代理尝试顺序：

        1. proxy_url 指定的临时代理
        2. 当前协议配置的代理列表
        3. 直连

        如果 URL 命中 NO_PROXY，则跳过所有代理直接连接。

        Args:
            method:
                HTTP 方法。

            url:
                请求 URL。

            proxy_url:
                临时使用的代理地址。

            extra_headers:
                单次请求额外的请求头，不会持久化。

            **kwargs:
                requests.Session.request 参数。

        Returns:
            requests.Response

        Raises:
            requests.RequestException:
                所有请求最终失败，并且存在 requests 异常。

            RuntimeError:
                所有请求失败，但没有捕获到 requests 异常。
        """

        last_exception: requests.RequestException | None = None

        proxies_to_try = self._get_proxy_list(
            url,
            proxy_url=proxy_url,
        )

        final_headers = self._build_request_headers(
            extra_headers,
        )

        # 不修改调用者传入的 kwargs。
        request_kwargs = kwargs.copy()

        request_kwargs.setdefault("timeout", 30)

        response: requests.Response | None = None

        for proxy in proxies_to_try:
            method_name = f"代理({proxy})" if proxy else "直连"

            proxies_dict = self._build_proxy_dict(proxy)

            for attempt in range(1, self.max_retries + 1):
                try:
                    logger.debug(
                        "尝试 %s 请求 %s " "(尝试 %d/%d)",
                        method_name,
                        url,
                        attempt,
                        self.max_retries,
                    )

                    logger.debug(
                        "请求头: %s",
                        final_headers,
                    )

                    response = self.session.request(
                        method=method,
                        url=url,
                        proxies=proxies_dict,
                        headers=final_headers,
                        **request_kwargs,
                    )

                    logger.debug(
                        "%s 请求 %s - 状态码: %s",
                        method_name,
                        url,
                        response.status_code,
                    )

                    # 2xx / 3xx / 4xx 都认为请求本身成功。
                    # 只有 5xx 才进入重试。
                    if response.status_code < 500:
                        logger.info(
                            "%s 请求成功: %s",
                            method_name,
                            url,
                        )
                        return response

                    logger.warning(
                        "%s 请求失败: %s - 状态码: %s",
                        method_name,
                        url,
                        response.status_code,
                    )

                except (
                    requests.ConnectionError,
                    requests.Timeout,
                ) as exc:
                    last_exception = exc

                    logger.warning(
                        "%s 网络异常 " "(尝试 %d/%d): %s",
                        method_name,
                        attempt,
                        self.max_retries,
                        exc,
                    )

                    if attempt < self.max_retries:
                        time.sleep(1)

                except requests.RequestException as exc:
                    last_exception = exc

                    logger.error(
                        "%s 请求异常: %s",
                        method_name,
                        exc,
                    )

                    # 其他 RequestException 不再对当前代理重试，
                    # 直接切换下一个代理。
                    break

        # 理论上只有 5xx 响应才会走到这里。
        if response is not None:
            if response.status_code < 500:
                return response

            logger.error(
                "所有请求方式均返回服务器错误: %s - 状态码: %s",
                url,
                response.status_code,
            )

        if last_exception:
            raise last_exception

        raise RuntimeError(f"所有请求方式失败: {url}")

    # ========================================================================
    # GET / POST
    # ========================================================================

    def get(
        self,
        url: str,
        proxy_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        **kwargs,
    ) -> requests.Response:
        """发送 GET 请求。"""

        return self.request(
            "GET",
            url,
            proxy_url=proxy_url,
            extra_headers=extra_headers,
            **kwargs,
        )

    def post(
        self,
        url: str,
        proxy_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        **kwargs,
    ) -> requests.Response:
        """发送 POST 请求。"""

        return self.request(
            "POST",
            url,
            proxy_url=proxy_url,
            extra_headers=extra_headers,
            **kwargs,
        )

    # ========================================================================
    # Cookies
    # ========================================================================

    def set_cookies(
        self,
        cookies: dict[str, str],
    ) -> None:
        """设置会话级 Cookie。"""

        self.session.cookies.clear()

        for key, value in cookies.items():
            self.session.cookies.set(key, value)

    def get_cookies_dict(self) -> dict[str, str]:
        """获取当前 Cookie 字典。"""

        return requests.utils.dict_from_cookiejar(self.session.cookies)

    def clear_cookies(self) -> None:
        """清空 Cookie。"""

        self.session.cookies.clear()

    # ========================================================================
    # Header 预设
    # ========================================================================

    def set_html_mode(self) -> None:
        """设置为 HTML 请求模式。"""

        self.update_headers(
            {
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,image/avif,"
                    "image/webp,image/apng,*/*;q=0.8"
                ),
                "Upgrade-Insecure-Requests": "1",
            }
        )

        logger.info("已切换到 HTML 请求模式")

    def set_json_mode(self) -> None:
        """设置为 JSON API 请求模式。"""

        self.update_headers(
            {
                "Accept": "application/json, text/plain, */*",
            }
        )

        if "Upgrade-Insecure-Requests" in self.session.headers:
            del self.session.headers["Upgrade-Insecure-Requests"]

        logger.info("已切换到 JSON API 请求模式")

    def set_referer(
        self,
        referer: str,
    ) -> None:
        """设置会话级 Referer。"""

        self.update_headers(
            {
                "Referer": referer,
            }
        )

    def set_origin(
        self,
        origin: str,
    ) -> None:
        """设置会话级 Origin。"""

        self.update_headers(
            {
                "Origin": origin,
            }
        )
