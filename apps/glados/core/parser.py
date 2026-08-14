"""
Glados API Response Parser

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
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from functools import wraps
from typing import Any, Self, TypeVar

import requests

from utils.log import get_logger
from utils.paths import logs

logger = get_logger(name="glados_parser", log_dir=logs(), fmt_type="detailed")


# ============================================================
# 类型变量
# ============================================================

R = TypeVar("R", bound="GladosBaseResult")


# ============================================================
# 基础结果类
# ============================================================


@dataclass
class GladosBaseResult(ABC):
    """所有结果对象的基类"""

    success: bool
    error: str | None = None  # 添加错误信息字段，便于调试

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosBaseResult:
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
class GladosAuthorizationResult(GladosBaseResult):
    """邮件认证 结果"""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosAuthorizationResult:
        code = data.get("code")

        if code != 0 and data.get("method") is None:
            return cls.failure("Invalid authorization response")

        return cls(success=True)


@dataclass
class GladosLoginResult(GladosBaseResult):
    """登录 结果"""

    cookies: dict[str, str] | None = None

    @classmethod
    def from_response(cls, response: requests.Response) -> GladosLoginResult:
        """从登录 Response 中解析 Cookie。"""

        cookies = response.cookies.get_dict()

        if not cookies:
            return cls.failure("Response missing cookies")

        return cls(
            success=True,
            cookies=cookies,
        )


@dataclass
class GladosCheckinResult(GladosBaseResult):
    """
    签到 结果

    属性说明：
        success (bool): 继承自基类，表示 API 调用是否成功（HTTP 200 + 有效 JSON）
        already_checked (bool): 是否已经签到过（True 表示今日已签到，False 表示本次签到成功）
        points (int): 本次签到获得的积分（已签到过时，返回当天签到获得的积分，从历史记录中获取）
        streak (int): 连续签到天数
        message (str): 接口返回的消息
        total_balance (float | None): 当前总积分余额（可选，部分接口返回）
    """

    already_checked: bool = False
    points: int = 0
    streak: int = 0
    message: str = ""
    total_balance: float | None = None  # 可选，部分响应中可能不包含

    @classmethod
    def _extract_required_fields(
        cls, data: dict[str, Any]
    ) -> tuple[int, int, int, str] | None:
        """
        提取并验证必要字段：code, points, streak, message。
        返回 (code, points, streak, message) 或 None（验证失败）。
        """
        code = data.get("code")
        points = data.get("points")
        streak = data.get("streak")
        message = data.get("message")

        # 检查是否存在
        if code is None or points is None or streak is None or message is None:
            return None

        # 检查 code 是否为 0 或 1
        if code not in (0, 1):
            return None

        # 转换 points
        try:
            points_int = int(points)
        except (ValueError, TypeError):
            return None

        # 转换 streak
        try:
            streak_int = int(streak)
        except (ValueError, TypeError):
            return None

        return code, points_int, streak_int, str(message)

    @classmethod
    def _extract_total_balance(cls, data: dict[str, Any]) -> float | None:
        """从响应中提取总余额（优先从 list[0].balance，其次从顶层 balance）。"""
        # 从 list 中获取最新余额
        records = data.get("list")
        if isinstance(records, list) and records:
            latest = records[0]
            if isinstance(latest, dict):
                balance_str = latest.get("balance")
                if balance_str is not None:
                    try:
                        return float(balance_str)
                    except (ValueError, TypeError):
                        pass

        # 从顶层获取
        balance_val = data.get("balance")
        if balance_val is not None:
            try:
                return float(balance_val)
            except (ValueError, TypeError):
                pass

        return None

    @classmethod
    def _extract_today_checkin_points(cls, data: dict[str, Any]) -> int | None:
        """
        从历史记录中提取今天签到获得的积分。
        从 list 中找到 business 为 "system:checkin" 且 detail 为今天日期的记录，获取其 change 值。
        如果找不到，返回 None。
        """
        records = data.get("list")
        if not isinstance(records, list) or not records:
            return None

        # 获取今天的日期字符串（格式：YYYY-MM-DD）
        from datetime import datetime

        today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        # 遍历所有记录，查找今天签到的记录
        for record in records:
            if not isinstance(record, dict):
                continue

            # 检查 business 是否为签到类型
            business = record.get("business", "")
            if business != "system:checkin":
                continue

            # 检查 detail 是否为今天日期
            detail = record.get("detail", "")
            if detail != today_str:
                continue

            # 获取 change 值
            change = record.get("change")
            if change is not None:
                try:
                    return int(float(change))
                except (ValueError, TypeError):
                    pass

        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosCheckinResult:
        """
        从字典解析签到结果。

        判定规则：
            - 存在 code 字段，且 code 为 0 或 1
            - 存在 points 字段（int 或数字字符串）
            - 存在 streak 字段（int 或数字字符串）
            - 存在 message 字段（str）

        只要满足上述条件，即认为接口调用成功（success=True）。
        code=0 表示签到成功（获得积分），code=1 表示今日已签到过。

        积分获取逻辑：
            - code=0: 直接使用 points 字段
            - code=1: 从历史记录（list）中查找今天日期的记录，获取其 change 值
        """
        # 1. 提取必要字段
        required = cls._extract_required_fields(data)
        if required is None:
            return cls.failure(
                "Missing or invalid required fields (code, points, streak, message)"
            )

        code, points_int, streak_int, message = required

        # 2. 提取总余额
        total_balance = cls._extract_total_balance(data)

        # 3. 确定最终积分值
        already_checked = code == 1
        final_points = points_int

        if already_checked and points_int == 0:
            # 已签到但 points=0，尝试从历史记录中获取今天的签到积分
            today_points = cls._extract_today_checkin_points(data)
            if today_points is not None:
                final_points = today_points

        return cls(
            success=True,
            already_checked=already_checked,
            points=final_points,
            streak=streak_int,
            message=message,
            total_balance=total_balance,
        )

    @property
    def checked_in_today(self) -> bool:
        """已签到过的别名，方便阅读"""
        return self.already_checked

    @property
    def earned_points(self) -> int:
        """本次获得的积分的别名，已签到过时返回当天签到值"""
        return self.points


# ============================================================
# Response 日志工具
# ============================================================


def _get_response_detail(response: requests.Response) -> str:
    """获取 Response 的详细信息，用于解析失败时日志输出。"""

    # 收集所有可用的响应信息
    details = []

    # 1. 基本信息
    details.append(f"URL: {response.url}")
    details.append(f"Status Code: {response.status_code}")
    details.append(f"Encoding: {response.encoding}")
    details.append(f"Elapsed: {response.elapsed.total_seconds():.3f}s")
    details.append(f"Cookies: {dict(response.cookies) if response.cookies else 'None'}")

    # 2. Headers（完整输出）
    try:
        headers = dict(response.headers)
        details.append(f"Headers ({len(headers)} items):")
        for key, value in headers.items():
            details.append(f"  {key}: {value}")
    except (AttributeError, TypeError, ValueError) as e:
        details.append(f"Headers: <无法读取 response.headers: {e}>")

    # 3. 原始响应体（完整输出，不截断）
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

    # 4. 响应头中的 Content-Type（特别标注）
    content_type = response.headers.get("Content-Type", "Not specified")
    details.append(f"Content-Type: {content_type}")

    # 5. 响应的历史记录（如果有重定向）
    if response.history:
        details.append(f"Redirect History ({len(response.history)} redirects):")
        for i, hist_resp in enumerate(response.history, 1):
            details.append(f"  #{i}: {hist_resp.status_code} - {hist_resp.url}")

    return "\n".join(details)


def _log_parse_failure(response: requests.Response, error: str | None = None) -> None:
    """记录 API Response 解析失败的详细信息。"""

    error_msg = f"错误类型: 响应结构解析失败{f': {error}' if error else ''}"
    logger.error(
        "=" * 80 + "\n"
        "Glados API 响应解析失败，响应规则可能已发生变化。\n"
        "请检查以下完整响应信息以调整解析规则：\n"
        "-" * 80 + "\n"
        "%s\n"
        "-" * 80 + "\n"
        "%s",
        _get_response_detail(response),
        error_msg,
    )


# ============================================================
# 解析装饰器
# ============================================================


def parse_result(result_class: type[GladosBaseResult]) -> Callable:
    """
    统一处理解析结果。
    显式传入结果类，避免类型提示解析问题。

    Args:
        result_class: 结果类（必须是 GladosBaseResult 的子类）

    Returns:
        装饰器函数
    """

    # 验证 result_class 是 GladosBaseResult 的子类
    if not (
        isinstance(result_class, type) and issubclass(result_class, GladosBaseResult)
    ):
        raise TypeError(
            f"result_class must be a subclass of GladosBaseResult, got {result_class}"
        )

    def decorator(
        func: Callable[..., GladosBaseResult],
    ) -> Callable[..., GladosBaseResult]:
        @wraps(func)
        def wrapper(
            self: Any,
            response: requests.Response,
            *args: Any,
            **kwargs: Any,
        ) -> GladosBaseResult:
            try:
                result = func(self, response, *args, **kwargs)
            except Exception as e:
                logger.exception(
                    "API 响应解析异常: %s",
                    func.__name__,
                )
                _log_parse_failure(response, str(e))

                return result_class.failure(
                    f"Parse exception: {e}",
                )

            if not result.success:
                _log_parse_failure(response, result.error)

            return result

        return wrapper

    return decorator


# ============================================================
# Parser
# ============================================================


class GladosParser:
    """Glados API 响应解析器"""

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

    # --------------------------------------------------------
    # Authorization
    # --------------------------------------------------------

    @parse_result(GladosAuthorizationResult)
    def parse_authorization(
        self,
        response: requests.Response,
    ) -> GladosAuthorizationResult:
        """解析用户信息。"""

        data = self._response_to_dict(response)

        if data is None:
            return GladosAuthorizationResult(
                success=False, error="Response is not valid JSON dict"
            )

        return GladosAuthorizationResult.from_dict(data)

    # --------------------------------------------------------
    # Login
    # --------------------------------------------------------

    @parse_result(GladosLoginResult)
    def parse_login(
        self,
        response: requests.Response,
    ) -> GladosLoginResult:
        """解析登录响应，提取 Cookie。"""

        return GladosLoginResult.from_response(response)

    # --------------------------------------------------------
    # Checkin（新增）
    # --------------------------------------------------------

    @parse_result(GladosCheckinResult)
    def parse_checkin(
        self,
        response: requests.Response,
    ) -> GladosCheckinResult:
        """
        解析签到响应。

        根据日志中的实际响应格式：
        - code=0: 签到成功，获得积分
        - code=1: 今日已签到，无新积分
        - 必需字段: code, points, streak, message
        - 可选字段: list (包含历史记录), balance
        """
        data = self._response_to_dict(response)

        if data is None:
            return GladosCheckinResult(
                success=False, error="Response is not valid JSON dict"
            )

        return GladosCheckinResult.from_dict(data)
