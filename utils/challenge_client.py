# common/challenge_client.py

from dataclasses import dataclass, field
from typing import Any

import requests

from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="challenge_client",
    log_dir=logs(),
    fmt_type="detailed",
)


class ChallengeError(Exception):
    """Cloudflare 挑战解决失败。"""

    def __init__(self, message: str, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass
class BrowserFingerprint:
    """浏览器指纹凭证，用于注入 RequestClient。"""

    user_agent: str
    cookies: dict[str, str] = field(default_factory=dict)
    sec_ch_ua: str | None = None
    sec_ch_ua_mobile: str | None = None
    sec_ch_ua_platform: str | None = None


class ChallengeClient:
    """Cloudflare 挑战专用通道。

    提供四种与 bypass 服务交互的方式：
    - /cookies: 获取 clearance 凭证（供注入 RequestClient）
    - /html:   获取渲染后的完整 HTML
    - /fetch:  下载任意资源的原始字节
    - 镜像模式: 透明转发任意 HTTP 请求
    """

    def __init__(
        self,
        base_url: str = "http://10.0.0.40:8000",
        auth_token: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.auth_token:
            headers["x-auth-token"] = self.auth_token
        return headers

    # ==================== 方式一：/cookies ====================

    def get_clearance(self, url: str) -> BrowserFingerprint:
        """获取指定 URL 的 cf_clearance 与配套指纹。"""
        endpoint = f"{self.base_url}/cookies"
        logger.info("请求 Cloudflare 凭证: %s", url)

        try:
            resp = self._session.get(
                endpoint,
                params={"url": url},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("挑战服务请求异常: %s", url)
            raise ChallengeError(f"挑战服务请求异常: {exc}") from exc

        if not resp.ok:
            logger.error(
                "挑战服务返回错误: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise ChallengeError(
                f"挑战服务返回 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise ChallengeError("挑战服务响应不是合法 JSON") from exc

        cookies = data.get("cookies") or {}
        user_agent = data.get("user_agent") or ""

        if not cookies or not user_agent:
            raise ChallengeError("挑战服务响应缺少 cookies 或 user_agent")

        logger.info("获取凭证成功: cookies=%s", list(cookies.keys()))

        return BrowserFingerprint(
            user_agent=user_agent,
            cookies=cookies,
            sec_ch_ua=data.get("sec_ch_ua"),
            sec_ch_ua_mobile=data.get("sec_ch_ua_mobile"),
            sec_ch_ua_platform=data.get("sec_ch_ua_platform"),
        )

    # ==================== 方式二：/html ====================

    def get_html(
        self,
        url: str,
        bypass_cache: bool = False,
    ) -> tuple[str, dict[str, str]]:
        """获取绕过 Cloudflare 后的完整渲染 HTML。

        Returns:
            (html_content, response_headers)

        Raises:
            ChallengeError: 请求失败或响应异常。
        """
        endpoint = f"{self.base_url}/html"
        params: dict[str, Any] = {"url": url}
        if bypass_cache:
            params["bypassCookieCache"] = "true"

        logger.info("请求渲染 HTML: %s (bypass_cache=%s)", url, bypass_cache)

        try:
            resp = self._session.get(
                endpoint,
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("HTML 请求异常: %s", url)
            raise ChallengeError(f"HTML 请求异常: {exc}") from exc

        if not resp.ok:
            logger.error(
                "HTML 请求失败: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise ChallengeError(
                f"HTML 请求返回 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        logger.info(
            "HTML 获取成功: len=%s final_url=%s",
            len(resp.text),
            resp.headers.get("x-cf-bypasser-final-url", ""),
        )
        return resp.text, dict(resp.headers)

    # ==================== 方式三：/fetch ====================

    def fetch(
        self,
        url: str,
        bypass_cache: bool = False,
    ) -> tuple[bytes, dict[str, str], int]:
        """通过浏览器下载任意资源的原始字节。

        Returns:
            (content_bytes, response_headers, upstream_status_code)

        Raises:
            ChallengeError: 请求失败。
        """
        endpoint = f"{self.base_url}/fetch"
        params: dict[str, Any] = {"url": url}
        if bypass_cache:
            params["bypassCookieCache"] = "true"

        logger.info("请求资源 fetch: %s", url)

        try:
            resp = self._session.get(
                endpoint,
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("fetch 请求异常: %s", url)
            raise ChallengeError(f"fetch 请求异常: {exc}") from exc

        if not resp.ok:
            logger.error(
                "fetch 请求失败: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise ChallengeError(
                f"fetch 请求返回 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        logger.info(
            "fetch 成功: bytes=%s content_type=%s",
            len(resp.content),
            resp.headers.get("Content-Type", ""),
        )
        return resp.content, dict(resp.headers), resp.status_code

    # ==================== 方式四：镜像模式 ====================

    def mirror_request(
        self,
        method: str,
        path: str,
        hostname: str,
        json_body: dict[str, Any] | None = None,
        data: bytes | str | None = None,
        extra_headers: dict[str, str] | None = None,
        proxy: str | None = None,
        bypass_cache: bool = False,
    ) -> requests.Response:
        """通过镜像模式透明转发任意 HTTP 请求。

        将请求打到 bypass 服务，由服务内部过挑战后重放给目标站。

        Args:
            method: HTTP 方法（GET/POST/PUT/DELETE 等）。
            path: 目标站路径，例如 "/api/user/status"。
            hostname: 目标域名，例如 "glados.cloud"（裸域名，不带协议）。
            json_body: JSON body（与 data 二选一）。
            data: 原始 body。
            extra_headers: 额外的请求头（如 Authorization）。
            proxy: 可选代理。
            bypass_cache: 是否强制刷新 cookie。

        Returns:
            目标站原始响应的 requests.Response。

        Raises:
            ChallengeError: 请求异常或服务返回错误。
        """
        url = f"{self.base_url}{path}"
        headers = self._headers()
        headers["x-hostname"] = hostname

        if proxy:
            headers["x-proxy"] = proxy
        if bypass_cache:
            headers["x-bypass-cache"] = "true"
        if extra_headers:
            headers.update(extra_headers)

        logger.info(
            "镜像请求: %s %s -> %s (hostname=%s)",
            method,
            path,
            self.base_url,
            hostname,
        )

        try:
            resp = self._session.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                data=data,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("镜像请求异常: %s %s", method, path)
            raise ChallengeError(f"镜像请求异常: {exc}") from exc

        if resp.status_code >= 500:
            logger.error(
                "镜像请求服务端错误: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise ChallengeError(
                f"镜像请求返回 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        logger.info(
            "镜像请求完成: %s %s -> status=%s",
            method,
            path,
            resp.status_code,
        )
        return resp
