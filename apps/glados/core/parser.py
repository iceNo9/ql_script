# apps\glados\core\parser.py

"""
Glados API Response Parser

负责：
- 将 API Response 解析为对应的 Result 对象
- 通过 ResultStatus 表达业务语义
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
from datetime import UTC, datetime
from enum import StrEnum
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
# 结果状态
# ============================================================


class ResultStatus(StrEnum):
    """
    业务结果状态。

    OK                业务成功
    BUSINESS_REJECTED 业务正常拒绝（如今日已签到、积分不足）—— 非错误
    AUTH_EXPIRED      凭证失效（如 code=-2 没有权限）—— 需重新认证
    AUTH_REQUIRED     从未认证 / 需要登录 —— 需重新认证
    RATE_LIMITED      限流 —— 可重试
    INVALID_REQUEST   请求/参数错误 —— 不该重试
    PARSE_ERROR       响应无法被解析（JSON 非法、缺字段）—— 契约变化
    UNKNOWN           未知业务失败 —— 保守处理
    """

    OK = "ok"
    BUSINESS_REJECTED = "business_rejected"
    AUTH_EXPIRED = "auth_expired"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    INVALID_REQUEST = "invalid_request"
    PARSE_ERROR = "parse_error"
    UNKNOWN = "unknown"


def _classify(code: Any, message: Any) -> ResultStatus:
    """
    将 GLaDOS 的 code / message 映射为 ResultStatus。

    注意：
        目前规则较少，先集中在此函数内。
        code 语义增多后再抽为独立模块。
    """
    msg = str(message) if message is not None else ""

    if code == 0:
        return ResultStatus.OK

    # -2 / "没有权限" → 凭证失效，需重新认证
    if code == -2 or "没有权限" in msg:
        return ResultStatus.AUTH_EXPIRED

    # 需要登录
    if code == -1 and ("login" in msg.lower() or "登录" in msg):
        return ResultStatus.AUTH_REQUIRED

    # 限流
    if code == 429 or "too many" in msg.lower() or "频繁" in msg:
        return ResultStatus.RATE_LIMITED

    # 参数/请求错误
    if code == 400 or "invalid" in msg.lower() or "参数" in msg:
        return ResultStatus.INVALID_REQUEST

    return ResultStatus.UNKNOWN


# ============================================================
# 基础结果类
# ============================================================


@dataclass
class GladosBaseResult(ABC):
    """所有结果对象的基类"""

    status: ResultStatus
    error: str | None = None

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosBaseResult:
        """从字典解析结果"""
        raise NotImplementedError

    # ---------------- 便捷构造 ----------------

    @classmethod
    def ok(cls) -> Self:
        return cls(status=ResultStatus.OK)

    @classmethod
    def rejected(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.BUSINESS_REJECTED, error=error)

    @classmethod
    def auth_expired(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.AUTH_EXPIRED, error=error)

    @classmethod
    def auth_required(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.AUTH_REQUIRED, error=error)

    @classmethod
    def rate_limited(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.RATE_LIMITED, error=error)

    @classmethod
    def invalid_request(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.INVALID_REQUEST, error=error)

    @classmethod
    def parse_error(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.PARSE_ERROR, error=error)

    @classmethod
    def unknown(cls, error: str | None = None) -> Self:
        return cls(status=ResultStatus.UNKNOWN, error=error)

    # ---------------- 便捷属性 ----------------

    @property
    def success(self) -> bool:
        """成功 = 业务成功。只读属性，方便阅读。"""
        return self.status == ResultStatus.OK

    @property
    def is_auth_failure(self) -> bool:
        """是否为认证类失败（触发降级）。"""
        return self.status in (
            ResultStatus.AUTH_EXPIRED,
            ResultStatus.AUTH_REQUIRED,
        )

    @property
    def is_failure(self) -> bool:
        """是否为失败（非 OK 且非业务拒绝）。"""
        return self.status not in (
            ResultStatus.OK,
            ResultStatus.BUSINESS_REJECTED,
        )

    @property
    def is_rejected(self) -> bool:
        """是否为业务拒绝（非错误）。"""
        return self.status == ResultStatus.BUSINESS_REJECTED


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
            return cls.rejected("Invalid authorization response")

        return cls.ok()


@dataclass
class GladosLoginResult(GladosBaseResult):
    """登录 结果"""

    cookies: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosLoginResult:
        """满足抽象基类要求，实际不会被调用。"""
        raise NotImplementedError("Use from_response for login result")

    @classmethod
    def from_response(cls, response: requests.Response) -> GladosLoginResult:
        """从登录 Response 中解析 Cookie。"""
        cookies = response.cookies.get_dict()

        if not cookies:
            return cls.auth_required("Response missing cookies")

        return cls(
            status=ResultStatus.OK,
            cookies=cookies,
        )


@dataclass
class GladosCheckinResult(GladosBaseResult):
    """
    签到 结果

    属性说明：
        status: 结果状态
        already_checked (bool): 是否已经签到过
        points (int): 本次签到获得的积分
        streak (int): 连续签到天数
        message (str): 接口返回的消息
        total_balance (float | None): 当前总积分余额
    """

    already_checked: bool = False
    points: int = 0
    streak: int = 0
    message: str = ""
    total_balance: float | None = None

    @classmethod
    def _extract_required_fields(
        cls, data: dict[str, Any]
    ) -> tuple[int, int, int, str] | None:
        code = data.get("code")
        points = data.get("points")
        streak = data.get("streak")
        message = data.get("message")

        if code is None or points is None or streak is None or message is None:
            return None

        if code not in (0, 1):
            return None

        try:
            points_int = int(points)
        except (ValueError, TypeError):
            return None

        try:
            streak_int = int(streak)
        except (ValueError, TypeError):
            return None

        return code, points_int, streak_int, str(message)

    @classmethod
    def _extract_total_balance(cls, data: dict[str, Any]) -> float | None:
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

        balance_val = data.get("balance")
        if balance_val is not None:
            try:
                return float(balance_val)
            except (ValueError, TypeError):
                pass

        return None

    @classmethod
    def _extract_today_checkin_points(cls, data: dict[str, Any]) -> int | None:
        records = data.get("list")
        if not isinstance(records, list) or not records:
            return None

        today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("business", "") != "system:checkin":
                continue
            if record.get("detail", "") != today_str:
                continue

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
        解析签到结果。

        code=0 → 签到成功（OK）
        code=1 → 今日已签到（BUSINESS_REJECTED，非错误）
        其他 code → 交给 _classify（如 -2 → AUTH_EXPIRED）
        """
        code = data.get("code")
        message = data.get("message")

        # 非 0/1 的 code 交给统一分类（含认证失效）
        if code not in (0, 1):
            status = _classify(code, message)
            return cls(status=status, error=str(message) if message else None)

        required = cls._extract_required_fields(data)
        if required is None:
            return cls.parse_error(
                "Missing or invalid required fields (code, points, streak, message)"
            )

        code, points_int, streak_int, message = required

        total_balance = cls._extract_total_balance(data)

        already_checked = code == 1
        final_points = points_int

        if already_checked and points_int == 0:
            today_points = cls._extract_today_checkin_points(data)
            if today_points is not None:
                final_points = today_points

        status = ResultStatus.BUSINESS_REJECTED if already_checked else ResultStatus.OK

        return cls(
            status=status,
            already_checked=already_checked,
            points=final_points,
            streak=streak_int,
            message=message,
            total_balance=total_balance,
        )

    @property
    def checked_in_today(self) -> bool:
        return self.already_checked

    @property
    def earned_points(self) -> int:
        return self.points


# ============================================================
# Points (积分) 结果类
# ============================================================


@dataclass
class GladosPointsResult(GladosBaseResult):
    """积分查询结果"""

    points: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosPointsResult:
        code = data.get("code")
        if code is None:
            return cls.parse_error("Missing 'code' field")

        if code != 0:
            message = data.get("message", data.get("msg", f"Code: {code}"))
            status = _classify(code, message)
            return cls(status=status, error=f"API returned error code: {message}")

        points = data.get("points")
        if points is None:
            return cls.parse_error("Missing 'points' field")

        try:
            points_val = float(points)
        except (ValueError, TypeError):
            return cls.parse_error(f"Invalid points value: {points}")

        return cls(status=ResultStatus.OK, points=points_val)


# ============================================================
# Status (状态) 结果类
# ============================================================


@dataclass
class GladosStatusResult(GladosBaseResult):
    """用户状态查询结果"""

    vip: int = 10
    left_days: float = 0.0
    traffic_byte: int = 0
    total_traffic_byte: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosStatusResult:
        code = data.get("code")
        if code is None:
            return cls.parse_error("Missing 'code' field")

        if code != 0:
            message = data.get("message", data.get("msg", f"Code: {code}"))
            status = _classify(code, message)
            return cls(status=status, error=f"API returned error code: {message}")

        api_data = data.get("data")
        if not api_data or not isinstance(api_data, dict):
            return cls.parse_error("Missing or invalid 'data' field")

        vip = api_data.get("vip", 10)
        try:
            vip = int(vip)
        except (ValueError, TypeError):
            vip = 10

        left_days_str = api_data.get("leftDays", "0")
        try:
            left_days = float(left_days_str)
        except (ValueError, TypeError):
            left_days = 0.0

        traffic_byte = api_data.get("traffic", 0)
        try:
            traffic_byte = int(traffic_byte)
        except (ValueError, TypeError):
            traffic_byte = 0

        total_traffic_byte = cls._get_total_traffic_by_vip(vip)

        return cls(
            status=ResultStatus.OK,
            vip=vip,
            left_days=left_days,
            traffic_byte=traffic_byte,
            total_traffic_byte=total_traffic_byte,
        )

    @staticmethod
    def _get_total_traffic_by_vip(vip: int) -> int:
        GB = 1073741824
        vip_traffic_map = {
            10: 10 * GB,
            21: 200 * GB,
        }
        return vip_traffic_map.get(vip, 10 * GB)


# ============================================================
# Exchange (积分兑换) 结果类
# ============================================================


@dataclass
class GladosExchangeResult(GladosBaseResult):
    """积分兑换结果"""

    message: str = ""
    points_used: int = 0
    days_added: int = 0
    points: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GladosExchangeResult:
        code = data.get("code")
        if code is None:
            return cls.parse_error("Missing 'code' field")

        if code != 0:
            message = data.get("message", data.get("msg", f"Code: {code}"))
            status = _classify(code, message)
            return cls(status=status, error=f"API returned error code: {message}")

        message = data.get("message", "")
        if not message:
            return cls.parse_error("Missing 'message' field")

        points_used = data.get("pointsUsed")
        if points_used is None:
            return cls.parse_error("Missing 'pointsUsed' field")
        try:
            points_used = int(points_used)
        except (ValueError, TypeError):
            return cls.parse_error(f"Invalid pointsUsed value: {points_used}")

        days_added = data.get("daysAdded")
        if days_added is None:
            return cls.parse_error("Missing 'daysAdded' field")
        try:
            days_added = int(days_added)
        except (ValueError, TypeError):
            return cls.parse_error(f"Invalid daysAdded value: {days_added}")

        points = data.get("points")
        if points is None:
            return cls.parse_error("Missing 'points' field")
        try:
            points = float(points)
        except (ValueError, TypeError):
            return cls.parse_error(f"Invalid points value: {points}")

        return cls(
            status=ResultStatus.OK,
            message=message,
            points_used=points_used,
            days_added=days_added,
            points=points,
        )


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

    response_detail = _get_response_detail(response)

    log_message = (
        f"\n{'=' * 80}\n"
        f"GLaDOS API 响应解析失败，响应规则可能已发生变化。\n"
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


def parse_result(result_class: type[GladosBaseResult]) -> Callable:
    """统一处理解析结果。"""

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

                return result_class.parse_error(f"Parse exception: {e}")

            # 失败时输出详细响应（OK / BUSINESS_REJECTED 不记）
            if result.status not in (
                ResultStatus.OK,
                ResultStatus.BUSINESS_REJECTED,
            ):
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
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict):
            return None

        return data

    # Authorization
    @parse_result(GladosAuthorizationResult)
    def parse_authorization(
        self,
        response: requests.Response,
    ) -> GladosAuthorizationResult:
        data = self._response_to_dict(response)
        if data is None:
            return GladosAuthorizationResult.parse_error(
                "Response is not valid JSON dict"
            )
        return GladosAuthorizationResult.from_dict(data)

    # Login
    @parse_result(GladosLoginResult)
    def parse_login(
        self,
        response: requests.Response,
    ) -> GladosLoginResult:
        return GladosLoginResult.from_response(response)

    # Checkin
    @parse_result(GladosCheckinResult)
    def parse_checkin(
        self,
        response: requests.Response,
    ) -> GladosCheckinResult:
        data = self._response_to_dict(response)
        if data is None:
            return GladosCheckinResult.parse_error("Response is not valid JSON dict")
        return GladosCheckinResult.from_dict(data)

    # Points
    @parse_result(GladosPointsResult)
    def parse_points(self, response: requests.Response) -> GladosPointsResult:
        data = self._response_to_dict(response)
        if data is None:
            return GladosPointsResult.parse_error("Response is not valid JSON dict")
        return GladosPointsResult.from_dict(data)

    # Status
    @parse_result(GladosStatusResult)
    def parse_status(self, response: requests.Response) -> GladosStatusResult:
        data = self._response_to_dict(response)
        if data is None:
            return GladosStatusResult.parse_error("Response is not valid JSON dict")
        return GladosStatusResult.from_dict(data)

    # Exchange Points
    @parse_result(GladosExchangeResult)
    def parse_exchange(self, response: requests.Response) -> GladosExchangeResult:
        data = self._response_to_dict(response)
        if data is None:
            return GladosExchangeResult.parse_error("Response is not valid JSON dict")
        return GladosExchangeResult.from_dict(data)


__all__ = [
    "GladosAuthorizationResult",
    "GladosBaseResult",
    "GladosCheckinResult",
    "GladosExchangeResult",
    "GladosLoginResult",
    "GladosParser",
    "GladosPointsResult",
    "GladosStatusResult",
    "ResultStatus",
    "parse_result",
]
