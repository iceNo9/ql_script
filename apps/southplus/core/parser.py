"""
SouthPlus API Response Parser

负责：
- 将 API Response 解析为对应的 Result 对象
- 统一通过 Result.from_response() 解析 Response
- HTML Response 使用 BeautifulSoup 解析
- 统一检查 Result.success
- 当 Response 解析异常时输出详细响应信息

不负责：
- 发起 HTTP 请求
- 处理 HTTP 请求异常
- HTTP 重试
- 认证方式切换
- 业务逻辑

SouthPlus 当前接口主要返回 HTML / XML AJAX 响应。
不同 Result 根据实际响应格式自行实现 from_response()。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, Self, TypeVar

import requests
from bs4 import BeautifulSoup

from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="southplus_parser",
    log_dir=logs(),
    fmt_type="detailed",
)


# ============================================================
# 类型变量
# ============================================================


R = TypeVar(
    "R",
    bound="SouthPlusBaseResult",
)


# ============================================================
# Task Response 解析工具
# ============================================================


def _parse_task_result(
    html: str,
) -> tuple[bool, str]:
    """
    解析 SouthPlus 任务操作结果。

    SouthPlus 任务相关 AJAX 接口返回类似：

        <?xml version="1.0" encoding="utf-8"?>
        <ajax><![CDATA[success    xxx]]></ajax>

    或：

        <?xml version="1.0" encoding="utf-8"?>
        <ajax><![CDATA[confirm    xxx]]></ajax>

    Returns:
        tuple[bool, str]:
            - bool:
                业务操作是否成功。
            - str:
                SouthPlus 返回的消息。

    Raises:
        ValueError:
            Response 内容无法按照预期规则解析。

    注意：
        这里的 bool 表示“业务操作结果”，
        不表示 Parser 是否解析成功。

        解析成功但业务失败，例如：

            confirm    已经申请过

        仍然属于：

            Parser success=True
            business success=False
    """

    if not html:
        raise ValueError(
            "响应内容为空",
        )

    match = re.search(
        r"<!\[CDATA\[(.*?)\]\]>",
        html,
        re.DOTALL,
    )

    if not match:
        raise ValueError(
            "未找到 CDATA 响应内容",
        )

    content = match.group(1).strip()

    if content.startswith("success"):
        return (
            True,
            content[len("success") :].strip(),
        )

    if content.startswith("confirm"):
        return (
            False,
            content[len("confirm") :].strip(),
        )

    raise ValueError(
        f"未知任务响应类型: {content}",
    )


# ============================================================
# 基础结果类
# ============================================================


@dataclass
class SouthPlusBaseResult(ABC):
    """
    所有 SouthPlus Parser Result 的基类。

    success 的含义非常明确：

        success=True
            Response 成功按照当前解析规则解析。

        success=False
            Response 结构异常，解析规则无法处理。

    注意：

        success 不代表业务操作成功。

    例如：

        confirm    任务已经申请过

    属于：

        success=True
        applied=False

    """

    success: bool
    error: str | None = None

    @classmethod
    @abstractmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从 HTTP Response 构造 Result。

        Args:
            response:
                HTTP Response。

        Returns:
            对应 Result。
        """
        raise NotImplementedError

    @classmethod
    def failure(
        cls,
        error: str | None = None,
    ) -> Self:
        """
        创建解析失败结果。

        这里的 failure 表示：

            Response 无法按照当前解析规则解析。

        不表示业务操作失败。
        """

        return cls(
            success=False,
            error=error,
        )


# ============================================================
# Profile
# ============================================================


@dataclass
class SouthPlusProfileResult(SouthPlusBaseResult):
    """
    SouthPlus 用户 Profile 页面解析结果。

    对应 API：

        SouthPlusAPI.get_profile()

    当前解析：

        SP币
    """

    points_sp: int = 0

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从 Profile HTTP Response 解析用户积分信息。
        """

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        points_sp = 0

        for td in soup.find_all("td"):
            text = td.get_text(
                " ",
                strip=True,
            )

            if text.startswith("SP币"):
                value = td.find("span")

                if value is None:
                    break

                try:
                    points_sp = int(
                        value.get_text(
                            strip=True,
                        )
                    )
                except ValueError:
                    pass

                break

        return cls(
            success=True,
            points_sp=points_sp,
        )


# ============================================================
# Tasks Actions
# ============================================================


@dataclass
class SouthPlusTasksActionsResult(SouthPlusBaseResult):
    """
    SouthPlus 进行中任务页面解析结果。

    对应 API：

        SouthPlusAPI.get_tasks_actions()

    用于判断当前是否可以领取：

    - 日常奖励：任务 15
    - 周常奖励：任务 14
    """

    can_complete_daily: bool = False
    can_complete_weekly: bool = False

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从任务 Actions HTML 判断是否可以领取奖励。

        判断规则：

            startjob('15') -> 可以领取日常奖励
            startjob('14') -> 可以领取周常奖励

        HTML 中单双引号均支持，大小写不敏感。
        """

        html = response.text

        if not html:
            raise ValueError(
                "响应内容为空",
            )

        can_complete_daily = bool(
            re.search(
                r"startjob\s*\(\s*['\"]15['\"]\s*\)",
                html,
                re.IGNORECASE,
            )
        )

        can_complete_weekly = bool(
            re.search(
                r"startjob\s*\(\s*['\"]14['\"]\s*\)",
                html,
                re.IGNORECASE,
            )
        )

        return cls(
            success=True,
            can_complete_daily=can_complete_daily,
            can_complete_weekly=can_complete_weekly,
        )


# ============================================================
# Daily Apply
# ============================================================


@dataclass
class SouthPlusDailyApplyResult(SouthPlusBaseResult):
    """
    SouthPlus 每日任务申请结果。

    对应 API：

        SouthPlusAPI.apply_daily()

    success：
        Response 是否成功按照解析规则解析。

    applied：
        每日任务是否真正申请成功。
    """

    applied: bool = False

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从每日任务申请 AJAX Response 解析结果。
        """

        applied, message = _parse_task_result(
            response.text,
        )

        return cls(
            success=True,
            error=None if applied else message,
            applied=applied,
        )


# ============================================================
# Weekly Apply
# ============================================================


@dataclass
class SouthPlusWeeklyApplyResult(SouthPlusBaseResult):
    """
    SouthPlus 每周任务申请结果。

    对应 API：

        SouthPlusAPI.apply_weekly()

    success：
        Response 是否成功按照解析规则解析。

    applied：
        每周任务是否真正申请成功。
    """

    applied: bool = False

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从每周任务申请 AJAX Response 解析结果。
        """

        applied, message = _parse_task_result(
            response.text,
        )

        return cls(
            success=True,
            error=None if applied else message,
            applied=applied,
        )


# ============================================================
# Daily Task Complete
# ============================================================


@dataclass
class SouthPlusDailyCompleteResult(SouthPlusBaseResult):
    """
    SouthPlus 每日任务完成结果。

    对应 API：

        SouthPlusAPI.complete_daily()

    success：
        Response 是否成功按照解析规则解析。

    completed：
        每日任务是否真正完成。

    日常任务完成奖励：

        2 SP
    """

    completed: bool = False
    delta_points_sp: int = 0

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从每日任务完成 AJAX Response 解析结果。
        """

        completed, message = _parse_task_result(
            response.text,
        )

        return cls(
            success=True,
            error=None if completed else message,
            completed=completed,
            delta_points_sp=2 if completed else 0,
        )


# ============================================================
# Weekly Task Complete
# ============================================================


@dataclass
class SouthPlusWeeklyCompleteResult(SouthPlusBaseResult):
    """
    SouthPlus 每周任务完成结果。

    对应 API：

        SouthPlusAPI.complete_weekly()

    success：
        Response 是否成功按照解析规则解析。

    completed：
        每周任务是否真正完成。

    周常任务完成奖励：

        7 SP
    """

    completed: bool = False
    delta_points_sp: int = 0

    @classmethod
    def from_response(
        cls,
        response: requests.Response,
    ) -> Self:
        """
        从每周任务完成 AJAX Response 解析结果。
        """

        completed, message = _parse_task_result(
            response.text,
        )

        return cls(
            success=True,
            error=None if completed else message,
            completed=completed,
            delta_points_sp=7 if completed else 0,
        )


# ============================================================
# Response 日志工具
# ============================================================


def _get_response_detail(
    response: requests.Response,
) -> str:
    """
    获取 Response 的详细信息。

    用于真正发生解析异常时输出完整响应。
    """

    details: list[str] = []

    details.append(
        f"URL: {response.url}",
    )

    details.append(
        f"Status Code: {response.status_code}",
    )

    details.append(
        f"Encoding: {response.encoding}",
    )

    details.append(
        f"Elapsed: {response.elapsed.total_seconds():.3f}s",
    )

    # ------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------

    try:
        details.append(
            "Cookies: " f"{dict(response.cookies) if response.cookies else 'None'}"
        )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        details.append(
            f"Cookies: <无法读取 response.cookies: {exc}>",
        )

    # ------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------

    try:
        headers = dict(
            response.headers,
        )

        details.append(
            f"Headers ({len(headers)} items):",
        )

        for key, value in headers.items():
            details.append(
                f"  {key}: {value}",
            )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        details.append(
            f"Headers: <无法读取 response.headers: {exc}>",
        )

    # ------------------------------------------------------------
    # Body
    # ------------------------------------------------------------

    try:
        body = response.text

        details.append(
            f"Response Body (length: {len(body)} chars):",
        )

        details.append(body)

    except UnicodeDecodeError:
        try:
            body = response.content

            details.append(
                "Response Body " f"(raw bytes, length: {len(body)}):",
            )

            hex_preview = body[:500].hex()

            details.append(hex_preview)

            details.append(
                "... [原始内容为二进制数据，" "已显示前500字节的十六进制]",
            )

        except (
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            details.append(
                f"<无法读取 response.content: {exc}>",
            )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        details.append(
            f"<无法读取 response.text: {exc}>",
        )

    # ------------------------------------------------------------
    # Content-Type
    # ------------------------------------------------------------

    try:
        content_type = response.headers.get(
            "Content-Type",
            "Not specified",
        )

        details.append(
            f"Content-Type: {content_type}",
        )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        details.append(
            f"Content-Type: <无法读取: {exc}>",
        )

    # ------------------------------------------------------------
    # Redirect History
    # ------------------------------------------------------------

    try:
        if response.history:
            details.append(
                "Redirect History " f"({len(response.history)} redirects):",
            )

            for index, history_response in enumerate(
                response.history,
                1,
            ):
                details.append(
                    f"  #{index}: "
                    f"{history_response.status_code} - "
                    f"{history_response.url}"
                )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        details.append(
            f"Redirect History: <无法读取: {exc}>",
        )

    return "\n".join(details)


def _log_parse_failure(
    response: requests.Response,
    error: str | None = None,
) -> None:
    """
    记录 API Response 真正的解析异常。

    注意：

        只有 Result.from_response()
        抛出异常时才应该调用此方法。

    Result.success == False
    表示解析失败。
    """

    error_msg = "错误类型: 响应结构解析失败" f"{f': {error}' if error else ''}"

    response_detail = _get_response_detail(
        response,
    )

    log_message = (
        f"\n{'=' * 80}\n"
        f"SouthPlus API 响应解析失败，"
        f"响应规则可能已发生变化。\n"
        f"请检查以下完整响应信息以调整解析规则：\n"
        f"{'-' * 80}\n"
        f"{response_detail}\n"
        f"{'-' * 80}\n"
        f"{error_msg}\n"
        f"{'=' * 80}"
    )

    logger.error(log_message)


# ============================================================
# 解析装饰器
# ============================================================


def parse_result(
    result_class: type[R],
) -> Callable:
    """
    统一处理 SouthPlus Response 解析。

    Args:
        result_class:
            Result 类型。

    Returns:
        Parser 装饰器。

    行为：

        Result.from_response()
            ↓
        成功解析
            ↓
        返回 success=True 的 Result

        Result.from_response()
            ↓
        抛出异常
            ↓
        记录完整 Response
            ↓
        返回 success=False 的 Result

    注意：

        success 只表示“解析是否成功”。

        不表示具体业务操作是否成功。
    """

    if not (
        isinstance(result_class, type)
        and issubclass(
            result_class,
            SouthPlusBaseResult,
        )
    ):
        raise TypeError(
            "result_class must be a subclass of "
            "SouthPlusBaseResult, "
            f"got {result_class}"
        )

    def decorator(
        func: Callable[..., R],
    ) -> Callable[..., R]:

        @wraps(func)
        def wrapper(
            self: Any,
            response: requests.Response,
            *args: Any,
            **kwargs: Any,
        ) -> R:

            try:
                result = func(
                    self,
                    response,
                    *args,
                    **kwargs,
                )

            except Exception as exc:
                logger.exception(
                    "API 响应解析异常: %s",
                    func.__name__,
                )

                _log_parse_failure(
                    response,
                    str(exc),
                )

                return result_class.failure(
                    f"Parse exception: {exc}",
                )

            return result

        return wrapper

    return decorator


# ============================================================
# Parser
# ============================================================


class SouthPlusParser:
    """
    SouthPlus API Response 解析器。

    Parser 本身不负责具体字段解析。

    具体解析逻辑由 Result.from_response()
    实现。

    Parser 负责：

    - 提供统一 parse_xxx() API
    - 调用对应 Result.from_response()
    - 统一捕获解析异常
    - 统一记录 Response 详情
    """

    # ------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusProfileResult,
    )
    def parse_profile(
        self,
        response: requests.Response,
    ) -> SouthPlusProfileResult:
        """解析 Profile 页面。"""

        return SouthPlusProfileResult.from_response(
            response,
        )

    # ------------------------------------------------------------
    # Tasks Actions
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusTasksActionsResult,
    )
    def parse_tasks_actions(
        self,
        response: requests.Response,
    ) -> SouthPlusTasksActionsResult:
        """解析进行中的任务页面。"""

        return SouthPlusTasksActionsResult.from_response(
            response,
        )

    # ------------------------------------------------------------
    # Daily Apply
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusDailyApplyResult,
    )
    def parse_apply_daily(
        self,
        response: requests.Response,
    ) -> SouthPlusDailyApplyResult:
        """解析每日任务申请响应。"""

        return SouthPlusDailyApplyResult.from_response(
            response,
        )

    # ------------------------------------------------------------
    # Weekly Apply
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusWeeklyApplyResult,
    )
    def parse_apply_weekly(
        self,
        response: requests.Response,
    ) -> SouthPlusWeeklyApplyResult:
        """解析每周任务申请响应。"""

        return SouthPlusWeeklyApplyResult.from_response(
            response,
        )

    # ------------------------------------------------------------
    # Daily Complete
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusDailyCompleteResult,
    )
    def parse_complete_daily(
        self,
        response: requests.Response,
    ) -> SouthPlusDailyCompleteResult:
        """解析每日任务完成响应。"""

        return SouthPlusDailyCompleteResult.from_response(
            response,
        )

    # ------------------------------------------------------------
    # Weekly Complete
    # ------------------------------------------------------------

    @parse_result(
        SouthPlusWeeklyCompleteResult,
    )
    def parse_complete_weekly(
        self,
        response: requests.Response,
    ) -> SouthPlusWeeklyCompleteResult:
        """解析每周任务完成响应。"""

        return SouthPlusWeeklyCompleteResult.from_response(
            response,
        )


# ============================================================
# 导出
# ============================================================


__all__ = [
    "SouthPlusBaseResult",
    "SouthPlusDailyApplyResult",
    "SouthPlusDailyCompleteResult",
    "SouthPlusParser",
    "SouthPlusProfileResult",
    "SouthPlusTasksActionsResult",
    "SouthPlusWeeklyApplyResult",
    "SouthPlusWeeklyCompleteResult",
    "parse_result",
]
