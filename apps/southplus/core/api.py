# apps/southplus/core/api.py

from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urljoin

import requests

from utils.log import get_logger
from utils.paths import logs
from utils.request_client import RequestClient

logger = get_logger(
    name="southplus_api",
    log_dir=logs(),
    fmt_type="detailed",
)


# ============================================================================
# API 端点
# ============================================================================


class SouthPlusEndpoints:
    """SouthPlus API 端点配置。"""

    BASE_URL = "https://bbs.south-plus.org"

    # HTML 页面
    HTML_PROFILE = "/userpay.php"
    HTML_TASKS = "/plugin.php?H_name-tasks.html"
    HTML_TASKS_ACTIONS = "/plugin.php?H_name-tasks-actions-newtasks.html.html"

    # 签到 / 任务操作
    XML_SIGN = "/plugin.php"


# ============================================================================
# API 异常
# ============================================================================


class SouthPlusAPIError(Exception):
    """SouthPlus API 请求异常。"""

    def __init__(
        self,
        status_code: int,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message

        super().__init__(message or f"HTTP {status_code}")


# ============================================================================
# 响应处理
# ============================================================================


def handle_response(
    func: Callable[..., requests.Response],
) -> Callable[..., requests.Response]:
    """
    统一处理 API 请求结果。

    正常响应（HTTP 2xx）：
        返回 requests.Response。

    HTTP 非 2xx 响应：
        记录详细日志。
        抛出 SouthPlusAPIError。

    HTTP 请求异常：
        记录异常日志。
        转换为 SouthPlusAPIError，并保留原始异常。

    其他未预期异常：
        原样继续向上抛出。
    """

    @wraps(func)
    def wrapper(
        *args: Any,
        **kwargs: Any,
    ) -> requests.Response:
        try:
            response = func(*args, **kwargs)

            if response.ok:
                return response

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

            raise SouthPlusAPIError(
                status_code=response.status_code,
                message=response.reason,
            )

        except requests.RequestException as exc:
            logger.exception(
                "API 请求异常: %s",
                func.__name__,
            )

            raise SouthPlusAPIError(
                status_code=0,
                message=str(exc),
            ) from exc

        except SouthPlusAPIError:
            raise

        except Exception:
            logger.exception(
                "API 请求发生未预期异常: %s",
                func.__name__,
            )
            raise

    return wrapper


# ============================================================================
# API
# ============================================================================


class SouthPlusAPI:
    """
    SouthPlus HTTP API 调用层。

    只负责：

    - 构建 URL
    - 管理 Cookies
    - 设置 HTTP 请求头
    - 发送 HTTP 请求
    - 返回原始 Response

    不负责：

    - HTML 解析
    - XML 解析
    - 业务逻辑
    - 签到结果判断
    - 用户实体构建
    """

    def __init__(
        self,
        request_client: RequestClient,
    ) -> None:
        self.client = request_client
        self.base_url = SouthPlusEndpoints.BASE_URL

    # =========================================================================
    # 基础请求
    # =========================================================================

    def _url(self, endpoint: str) -> str:
        """构建完整 URL。"""

        return urljoin(
            self.base_url,
            endpoint,
        )

    def _html_headers(
        self,
        referer: str,
        *,
        fetch_dest: str = "document",
    ) -> dict[str, str]:
        """
        构建 SouthPlus HTML 请求头。

        保持旧 Server 中实际使用的浏览器请求头。
        """

        return {
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "image/avif,"
                "image/webp,"
                "image/apng,"
                "*/*;q=0.8,"
                "application/signed-exchange;"
                "v=b3;q=0.7"
            ),
            "Priority": "u=1, i",
            "Referer": referer,
            "Sec-Fetch-Dest": fetch_dest,
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-fetch-user": "?1",
            "Upgrade-insecure-requests": "1",
        }

    # =========================================================================
    # Cookies
    # =========================================================================

    def set_cookies(
        self,
        cookies: dict[str, str],
    ) -> None:
        """替换会话级 Cookies。"""

        self.client.set_cookies(cookies)

        logger.debug(
            "Cookies 已设置: %s",
            list(cookies.keys()),
        )

    def update_cookies(
        self,
        cookies: dict[str, str],
    ) -> None:
        """更新会话级 Cookies。"""

        self.client.update_cookies(cookies)

        logger.debug(
            "Cookies 已更新: %s",
            list(cookies.keys()),
        )

    def get_cookies(self) -> dict[str, str]:
        """获取当前会话 Cookies。"""

        return self.client.get_cookies_dict()

    def clear_cookies(self) -> None:
        """清空会话 Cookies。"""

        self.client.clear_cookies()

        logger.debug("Cookies 已清空")

    # =========================================================================
    # Profile
    # =========================================================================

    @handle_response
    def get_profile(self) -> requests.Response:
        """
        获取用户 Profile 页面。

        当前端点：

            /userpay.php

        返回原始 HTTP Response。
        HTML 解析由上层负责。
        """
        url = self._url(SouthPlusEndpoints.HTML_PROFILE)

        headers = self._html_headers(
            referer=f"{self.base_url}/u.php",
        )

        response = self.client.get(
            url,
            extra_headers=headers,
        )

        logger.debug(
            "成功获取 Profile: %s",
            url,
        )

        return response

    # =========================================================================
    # Tasks
    # =========================================================================

    @handle_response
    def get_tasks(self) -> requests.Response:
        """
        获取任务页面。

        对应：

            /plugin.php?H_name-tasks.html
        """

        url = self._url(SouthPlusEndpoints.HTML_TASKS)

        headers = self._html_headers(
            referer=f"{self.base_url}/index.php",
        )

        response = self.client.get(
            url,
            extra_headers=headers,
        )

        logger.debug(
            "成功获取任务页面: %s",
            url,
        )

        return response

    @handle_response
    def get_tasks_actions(self) -> requests.Response:
        """
        获取进行中的任务。

        对应：

            /plugin.php?H_name-tasks-actions-newtasks.html.html
        """

        url = self._url(SouthPlusEndpoints.HTML_TASKS_ACTIONS)

        headers = self._html_headers(
            referer=self._url(SouthPlusEndpoints.HTML_TASKS),
        )

        response = self.client.get(
            url,
            extra_headers=headers,
        )

        logger.debug(
            "成功获取进行中的任务: %s",
            url,
        )

        return response

    # ============================================================================
    # 申请任务
    # ============================================================================

    @handle_response
    def apply_daily(self) -> requests.Response:
        """
        申请每日任务。

        参数：

            H_name=tasks
            action=ajax
            actions=job
            cid=15
        """

        return self._task_action(
            actions="job",
            cid=15,
        )

    @handle_response
    def apply_weekly(self) -> requests.Response:
        """
        申请每周任务。

        参数：

            H_name=tasks
            action=ajax
            actions=job
            cid=14
        """

        return self._task_action(
            actions="job",
            cid=14,
        )

    # =========================================================================
    # 完成任务
    # =========================================================================

    @handle_response
    def complete_daily(self) -> requests.Response:
        """
        完成每日任务。

        参数：

            H_name=tasks
            action=ajax
            actions=job2
            cid=15
        """

        return self._task_complete(
            cid=15,
        )

    @handle_response
    def complete_weekly(self) -> requests.Response:
        """
        完成每周任务。

        参数：

            H_name=tasks
            action=ajax
            actions=job2
            cid=14
        """

        return self._task_complete(
            cid=14,
        )

    # =========================================================================
    # 内部任务请求
    # =========================================================================

    def _task_action(
        self,
        *,
        actions: str,
        cid: int,
    ) -> requests.Response:
        """
        执行任务 Action。

        这是每日 / 每周签到的公共 HTTP 请求。
        """

        url = self._url(SouthPlusEndpoints.XML_SIGN)

        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": actions,
            "cid": cid,
        }

        headers = self._html_headers(
            referer=self._url(SouthPlusEndpoints.HTML_TASKS),
            fetch_dest="iframe",
        )

        response = self.client.get(
            url,
            params=params,
            extra_headers=headers,
        )

        logger.debug(
            "任务操作成功: actions=%s, cid=%s",
            actions,
            cid,
        )

        return response

    def _task_complete(
        self,
        *,
        cid: int,
    ) -> requests.Response:
        """
        执行任务完成请求。
        """

        return self._task_action(
            actions="job2",
            cid=cid,
        )


__all__ = [
    "SouthPlusAPI",
    "SouthPlusAPIError",
    "SouthPlusEndpoints",
    "handle_response",
]
