"""
Hifiti API Response Parser

负责：
- 将 API Response 解析为对应的 Result 对象
- 统一检查 Result.success
- 当 Response 存在但解析规则不匹配时输出详细响应信息

不负责：
- 发起 HTTP 请求
- 处理 HTTP 请求异常
- 处理 HTTP 重试
- 业务逻辑
- 认证方式切换
"""

from __future__ import annotations

import json
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

logger = get_logger(name="hifiti_parser", log_dir=logs(), fmt_type="detailed")


# ============================================================
# 类型变量
# ============================================================

R = TypeVar("R", bound="HifitiBaseResult")


# ============================================================
# 基础结果类
# ============================================================


@dataclass
class HifitiBaseResult(ABC):
    """所有结果对象的基类"""

    success: bool
    error: str | None = None

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> HifitiBaseResult:
        """从字典解析结果"""
        raise NotImplementedError

    @classmethod
    def failure(cls, error: str | None = None) -> Self:
        """创建失败结果。"""
        return cls(success=False, error=error)


# ============================================================
# 具体结果类
# ============================================================


@dataclass
class HifitiLoginResult(HifitiBaseResult):
    """
    登录结果

    Hifiti 登录接口返回的是 JSON，但认证是通过 Cookie 进行的。
    登录成功后，Cookie 从 Response 的 set-cookie 头获取。
    """

    cookies: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HifitiLoginResult:
        """从字典解析登录结果。

        注意：登录的 Cookie 来自 Response 对象，不是来自 JSON body。
        此方法仅用于满足抽象基类要求，实际不会被调用。
        """
        return cls.failure("Use from_response() instead")

    @classmethod
    def from_response(cls, response: requests.Response) -> HifitiLoginResult:
        """从登录 Response 中解析 Cookie。"""

        cookies = response.cookies.get_dict()

        if not cookies:
            return cls.failure("Response missing cookies")

        return cls(
            success=True,
            cookies=cookies,
        )


@dataclass
class HifitiCheckinResult(HifitiBaseResult):
    """
    签到结果

    Hifiti 签到接口返回格式：
    {
        "code": "0",       # 0=签到成功，-1=已签到
        "message": "成功签到！今日排名5491，总奖励2金币！"
    }

    属性说明：
        already_checked (bool): 是否已经签到过（今日已签到）
        rank (int): 今日签到排名（仅签到成功时有值）
        checkin_gold (int): 本次签到获得的金币（仅签到成功时有值）
        message (str): 接口返回的消息
    """

    already_checked: bool = False
    rank: int = 0
    checkin_gold: int = 0
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HifitiCheckinResult:
        """
        从字典解析签到结果。
        """
        if not isinstance(data, dict):
            return cls.failure(f"Unexpected response type: {type(data)}")

        code = data.get("code")
        msg = data.get("message", "")

        # code 可能是字符串或整数
        code_str = str(code)

        if code_str == "-1":
            # 已签到：message 只是提示信息，不包含排名和金币
            return cls(
                success=True,
                already_checked=True,
                rank=0,
                checkin_gold=0,
                message=msg,
            )

        if code_str == "0":
            # 签到成功：从 message 中提取排名和金币
            rank, gold = cls._parse_checkin_message(msg)
            return cls(
                success=True,
                already_checked=False,
                rank=rank,
                checkin_gold=gold,
                message=msg,
            )

        # 其他 code 值视为失败
        return cls.failure(f"签到失败: {msg}")

    @classmethod
    def _parse_checkin_message(cls, message: str) -> tuple[int, int]:
        """
        从签到消息中提取排名和金币。

        消息格式示例：
        - "成功签到！今日排名5491，总奖励2金币！"

        返回: (rank, gold)
        """

        rank = 0
        gold = 0

        if not message:
            return rank, gold

        # 提取排名：排名数字
        rank_match = re.search(r"排名(\d+)", message)
        if rank_match:
            try:
                rank = int(rank_match.group(1))
            except ValueError:
                pass

        # 提取金币：数字 + 金币
        gold_match = re.search(r"(\d+)金币", message)
        if gold_match:
            try:
                gold = int(gold_match.group(1))
            except ValueError:
                pass

        return rank, gold


@dataclass
class HifitiUserDataResult(HifitiBaseResult):
    """
    用户数据结果（从 /my-credits.htm 页面解析）

    从 HTML 页面中提取用户金币数据。
    """

    gold: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HifitiUserDataResult:
        """
        从字典解析用户数据。

        注意：Hifiti 的 /my-credits.htm 返回的是 HTML，不是 JSON。
        此方法仅用于满足抽象基类要求，实际不会被调用。
        """
        return cls.failure("Use from_html() instead")

    @classmethod
    def from_html(cls, html: str) -> HifitiUserDataResult:
        """
        从 HTML 页面解析用户金币数据。

        Args:
            html: /my-credits.htm 页面的 HTML 内容

        Returns:
            HifitiUserDataResult

        解析规则：
            使用 CSS Selector 定位金币输入框：
            .input-group:has(.input-group-text:contains("金币")) .form-control
            或更精确：
            .input-group:has(.icon-diamond) .form-control
        """
        if not html:
            return cls.failure("HTML 内容为空")

        try:
            soup = BeautifulSoup(html, "html.parser")

            # 查找包含金币的 input-group
            # 方案1：通过 icon-diamond 图标查找
            gold_group = soup.select_one(".input-group:has(.icon-diamond)")
            if not gold_group:
                # 方案2：通过文本 "金币" 查找
                gold_group = soup.select_one(
                    '.input-group:has(.input-group-text:contains("金币"))'
                )

            if not gold_group:
                return cls.failure("未找到金币信息")

            # 获取 input 元素的值
            gold_input = gold_group.select_one("input.form-control")
            if not gold_input:
                return cls.failure("未找到金币输入框")

            gold_value = gold_input.get("value", "0")
            try:
                gold = int(gold_value)
            except (ValueError, TypeError):
                gold = 0

            return cls(
                success=True,
                gold=gold,
            )

        except (AttributeError, TypeError, ValueError) as e:
            # BeautifulSoup 解析或 CSS 选择器相关的异常
            return cls.failure(f"HTML 解析异常: {e}")


# ============================================================
# Response 日志工具
# ============================================================


def _get_response_detail(response: requests.Response) -> str:
    """获取 Response 的详细信息，用于解析失败时日志输出。"""
    details = []

    details.append(f"URL: {response.url}")
    details.append(f"Status Code: {response.status_code}")
    details.append(f"Encoding: {response.encoding}")
    details.append(f"Elapsed: {response.elapsed.total_seconds():.3f}s")
    details.append(f"Cookies: {dict(response.cookies) if response.cookies else 'None'}")

    try:
        headers = dict(response.headers)
        details.append(f"Headers ({len(headers)} items):")
        for key, value in headers.items():
            details.append(f"  {key}: {value}")
    except (AttributeError, TypeError, ValueError) as e:
        details.append(f"Headers: <无法读取 response.headers: {e}>")

    try:
        body = response.text
        details.append(f"Response Body (length: {len(body)} chars):")
        details.append(body)
    except UnicodeDecodeError:
        try:
            body = response.content
            details.append(f"Response Body (raw bytes, length: {len(body)}):")
            hex_preview = body[:500].hex()
            details.append(hex_preview)
            details.append("... [原始内容为二进制数据，已显示前500字节的十六进制]")
        except (AttributeError, TypeError, ValueError) as e2:
            details.append(f"<无法读取 response.content: {e2}>")
    except (AttributeError, TypeError, ValueError) as e:
        details.append(f"<无法读取 response.text: {e}>")

    content_type = response.headers.get("Content-Type", "Not specified")
    details.append(f"Content-Type: {content_type}")

    if response.history:
        details.append(f"Redirect History ({len(response.history)} redirects):")
        for i, hist_resp in enumerate(response.history, 1):
            details.append(f"  #{i}: {hist_resp.status_code} - {hist_resp.url}")

    return "\n".join(details)


def _log_parse_failure(response: requests.Response, error: str | None = None) -> None:
    """记录 API Response 解析失败的详细信息。"""

    error_msg = f"错误类型: 响应结构解析失败{f': {error}' if error else ''}"

    # 构建响应详情
    response_detail = _get_response_detail(response)

    # 使用 f-string 构建完整消息，避免 logger 的格式化处理
    log_message = (
        f"\n{'=' * 80}\n"
        f"Hifiti API 响应解析失败，响应规则可能已发生变化。\n"
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


def parse_result(result_class: type[HifitiBaseResult]) -> Callable:
    """
    统一处理解析结果。
    显式传入结果类，避免类型提示解析问题。
    """
    if not (
        isinstance(result_class, type) and issubclass(result_class, HifitiBaseResult)
    ):
        raise TypeError(
            f"result_class must be a subclass of HifitiBaseResult, got {result_class}"
        )

    def decorator(
        func: Callable[..., HifitiBaseResult],
    ) -> Callable[..., HifitiBaseResult]:
        @wraps(func)
        def wrapper(
            self: Any,
            response: requests.Response,
            *args: Any,
            **kwargs: Any,
        ) -> HifitiBaseResult:
            try:
                result = func(self, response, *args, **kwargs)
            except Exception as e:
                logger.exception(
                    "API 响应解析异常: %s",
                    func.__name__,
                )
                _log_parse_failure(response, str(e))
                return result_class.failure(f"Parse exception: {e}")

            if not result.success:
                _log_parse_failure(response, result.error)

            return result

        return wrapper

    return decorator


# ============================================================
# Parser
# ============================================================


class HifitiParser:
    """Hifiti API 响应解析器"""

    @staticmethod
    def _response_to_dict(
        response: requests.Response,
    ) -> dict[str, Any] | None:
        """将 Response JSON 转换为字典。"""
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict):
            return None

        return data

    # Login
    @parse_result(HifitiLoginResult)
    def parse_login(
        self,
        response: requests.Response,
    ) -> HifitiLoginResult:
        """解析登录响应，从 Response 中提取 Cookie。"""
        return HifitiLoginResult.from_response(response)

    # Checkin
    @parse_result(HifitiCheckinResult)
    def parse_checkin(
        self,
        response: requests.Response,
    ) -> HifitiCheckinResult:
        """解析签到响应。"""
        data = self._response_to_dict(response)
        if data is None:
            return HifitiCheckinResult(
                success=False, error="Response is not valid JSON dict"
            )
        return HifitiCheckinResult.from_dict(data)

    # User Data (HTML)
    def parse_user_data(
        self,
        response: requests.Response,
    ) -> HifitiUserDataResult:
        """
        从 HTML 响应解析用户数据。

        注意：此方法不使用 @parse_result 装饰器，
        因为返回的是 HTML 而不是 JSON，解析逻辑不同。
        """
        try:
            html = response.text
        except Exception as e:
            logger.exception("读取 HTML 响应失败")
            return HifitiUserDataResult.failure(f"读取响应失败: {e}")

        if not html:
            return HifitiUserDataResult.failure("响应内容为空")

        return HifitiUserDataResult.from_html(html)


# ============================================================
# 导出
# ============================================================

__all__ = [
    "HifitiBaseResult",
    "HifitiCheckinResult",
    "HifitiLoginResult",
    "HifitiParser",
    "HifitiUserDataResult",
    "parse_result",
]
