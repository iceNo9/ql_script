"""
Baiyefee API Response Parser

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
from functools import wraps
from typing import Any, Self, TypeVar

import requests

from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_local, parse_local_date

logger = get_logger(name="baiyefee_parser", log_dir=logs(), fmt_type="detailed")


# ============================================================
# 类型变量
# ============================================================

R = TypeVar("R", bound="BaiyefeeBaseResult")


# ============================================================
# 基础结果类
# ============================================================


@dataclass
class BaiyefeeBaseResult(ABC):
    """所有结果对象的基类"""

    success: bool
    error: str | None = None

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaiyefeeBaseResult:
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
class BaiyefeeLoginResult(BaiyefeeBaseResult):
    """登录结果"""

    token: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaiyefeeLoginResult:
        """
        从字典解析登录结果。

        Baiyefee 登录响应格式：
        {
            "id": "20475",
            "name": "TLgFys",
            "token": "eyJ0eXAi...",
            "exp": 1788431739,
            "credit": "9",
            "task": "33",
            ...
        }
        """
        token = data.get("token")
        if not token:
            return cls.failure("Missing 'token' field in login response")

        return cls(
            success=True,
            token=token,
        )


@dataclass
class BaiyefeeCheckinResult(BaiyefeeBaseResult):
    """
    签到结果

    属性说明：
        already_checked (bool): 是否已经签到过（今日已签到）
        checkin_points (int): 本次签到获得的积分
        points (int): 签到后总积分
        message (str): 接口返回的消息
        date (str): 签到时间
    """

    already_checked: bool = False
    checkin_points: int = 0
    points: int = 0
    message: str = ""
    local_date: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaiyefeeCheckinResult:
        """
        从字典解析签到结果。

        Baiyefee 签到接口返回格式：

        1. 重复签到（今日已签到）：返回纯数字字符串
           响应体直接是字符串，如 "6"

        2. 正常签到：返回对象
           {
               "date": "2026-08-20 19:39:27",
               "credit": 5,
               "mission": {
                   "date": "2026-08-20 19:39:27",
                   "credit": "5",
                   "always": "1",
                   "tk": {"days": 0, "credit": 0, "bs": "3"},
                   "my_credit": "5",
                   "current_user": 20486
               }
           }
        """
        # 情况1：响应是字符串（重复签到，已签到）
        if isinstance(data, str):
            try:
                checkin_points = int(data)
            except (ValueError, TypeError):
                return cls.failure(f"Invalid points string: {data}")

            return cls(
                success=True,
                already_checked=True,
                checkin_points=checkin_points,
                points=0,
                message=f"今日已签到，获得 {checkin_points} 积分",
                date="",
            )

        # 情况2：响应是字典（正常签到）
        if not isinstance(data, dict):
            return cls.failure(f"Unexpected response type: {type(data)}")

        # 提取 date
        date = data.get("date", "")

        # 提取 checkin_points（本次签到获得积分）：从 credit 字段获取
        checkin_points = 0
        credit = data.get("credit")
        if credit is not None:
            try:
                checkin_points = int(credit)
            except (ValueError, TypeError):
                pass

        # 提取 points（签到后总积分）：从 mission.my_credit 获取
        points = 0
        mission = data.get("mission")
        if mission and isinstance(mission, dict):
            my_credit = mission.get("my_credit")
            if my_credit is not None:
                try:
                    points = int(my_credit)
                except (ValueError, TypeError):
                    pass

        return cls(
            success=True,
            already_checked=False,
            checkin_points=checkin_points,
            points=points,
            message=f"签到成功，获得 {checkin_points} 积分",
            local_date=date,
        )


@dataclass
class BaiyefeeUserDataResult(BaiyefeeBaseResult):
    """
    用户数据结果（getUserGoldData）

    响应格式：
    {
        "credit": "5",
        "money": 0
    }
    """

    points: int = 0
    money: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaiyefeeUserDataResult:
        """从字典解析用户数据。"""
        points = 0
        credit_val = data.get("credit")
        if credit_val is not None:
            try:
                points = int(credit_val)
            except (ValueError, TypeError):
                pass

        money = 0.0
        money_val = data.get("money")
        if money_val is not None:
            try:
                money = float(money_val)
            except (ValueError, TypeError):
                pass

        return cls(
            success=True,
            points=points,
            money=money,
        )


@dataclass
class BaiyefeeSignInfoResult(BaiyefeeBaseResult):
    """
    签到信息结果（getUserMission）

    响应格式：
    {
        "mission": {
            "date": "2026-08-20 00:46:00",  # 已签到时有日期，未签到时为空
            "credit": "6",                   # 今日签到可获得积分
            "always": "30",                 # 0=未签到，非0=已签到
            "tk": {"days": 0, "credit": 0, "bs": "3"},
            "my_credit": "418",             # 当前总积分
            "current_user": 13877
        }
    }

    属性说明：
        checkin_points (int): 今日签到可获得积分（mission.credit）
        points (int): 当前总积分（mission.my_credit）
        can_checkin (bool): 是否可以签到（mission.date 不是今天）
        date (str): 上次签到日期（已签到时为日期字符串，未签到时为空）
    """

    checkin_points: int = 0
    points: int = 0
    can_checkin: bool = False
    local_date: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaiyefeeSignInfoResult:
        """从字典解析签到信息。"""
        mission = data.get("mission")
        if not mission or not isinstance(mission, dict):
            return cls.failure("Missing or invalid 'mission' field")

        # 提取 checkin_points（今日签到可获得积分）
        checkin_points = 0
        credit = mission.get("credit")
        if credit is not None:
            try:
                checkin_points = int(credit)
            except (ValueError, TypeError):
                pass

        # 提取 points（当前总积分）
        points = 0
        my_credit = mission.get("my_credit")
        if my_credit is not None:
            try:
                points = int(my_credit)
            except (ValueError, TypeError):
                pass

        # 提取 date
        date = mission.get("date", "")

        # 判断是否可以签到：date 为空 或 date 不是今天
        can_checkin = True
        if date:
            try:
                # 解析日期字符串，只取日期部分（YYYY-MM-DD）
                mission_dt = parse_local_date(date[:10])
                if mission_dt:
                    can_checkin = mission_dt.date() != now_local().date()
                else:
                    can_checkin = True  # 解析失败，默认可以签到
            except (ValueError, TypeError):
                # 解析失败，默认可以签到
                can_checkin = True

        return cls(
            success=True,
            checkin_points=checkin_points,
            points=points,
            can_checkin=can_checkin,
            local_date=date,
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

    # 构建响应详情
    response_detail = _get_response_detail(response)

    # 使用 f-string 构建完整消息，避免 logger 的格式化处理
    log_message = (
        f"\n{'=' * 80}\n"
        f"Baiyefee API 响应解析失败，响应规则可能已发生变化。\n"
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


def parse_result(result_class: type[BaiyefeeBaseResult]) -> Callable:
    """
    统一处理解析结果。
    显式传入结果类，避免类型提示解析问题。
    """
    if not (
        isinstance(result_class, type) and issubclass(result_class, BaiyefeeBaseResult)
    ):
        raise TypeError(
            f"result_class must be a subclass of BaiyefeeBaseResult, got {result_class}"
        )

    def decorator(
        func: Callable[..., BaiyefeeBaseResult],
    ) -> Callable[..., BaiyefeeBaseResult]:
        @wraps(func)
        def wrapper(
            self: Any,
            response: requests.Response,
            *args: Any,
            **kwargs: Any,
        ) -> BaiyefeeBaseResult:
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


class BaiyefeeParser:
    """Baiyefee API 响应解析器"""

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
    @parse_result(BaiyefeeLoginResult)
    def parse_login(
        self,
        response: requests.Response,
    ) -> BaiyefeeLoginResult:
        """解析登录响应，提取 Token。"""
        data = self._response_to_dict(response)
        if data is None:
            return BaiyefeeLoginResult(
                success=False, error="Response is not valid JSON dict"
            )
        return BaiyefeeLoginResult.from_dict(data)

    # Checkin
    @parse_result(BaiyefeeCheckinResult)
    def parse_checkin(
        self,
        response: requests.Response,
    ) -> BaiyefeeCheckinResult:
        """解析签到响应。"""
        data = self._response_to_dict(response)
        if data is None:
            return BaiyefeeCheckinResult(
                success=False, error="Response is not valid JSON dict"
            )
        return BaiyefeeCheckinResult.from_dict(data)

    # User Data
    @parse_result(BaiyefeeUserDataResult)
    def parse_user_data(
        self,
        response: requests.Response,
    ) -> BaiyefeeUserDataResult:
        """解析用户数据响应。"""
        data = self._response_to_dict(response)
        if data is None:
            return BaiyefeeUserDataResult(
                success=False, error="Response is not valid JSON dict"
            )
        return BaiyefeeUserDataResult.from_dict(data)

    # Sign Info
    @parse_result(BaiyefeeSignInfoResult)
    def parse_sign_info(
        self,
        response: requests.Response,
    ) -> BaiyefeeSignInfoResult:
        """解析签到信息响应。"""
        data = self._response_to_dict(response)
        if data is None:
            return BaiyefeeSignInfoResult(
                success=False, error="Response is not valid JSON dict"
            )
        return BaiyefeeSignInfoResult.from_dict(data)


# ============================================================
# 导出
# ============================================================

__all__ = [
    "BaiyefeeBaseResult",
    "BaiyefeeCheckinResult",
    "BaiyefeeLoginResult",
    "BaiyefeeParser",
    "BaiyefeeSignInfoResult",
    "BaiyefeeUserDataResult",
    "parse_result",
]
