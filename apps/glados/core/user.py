# apps\glados\core\user.py

"""
GLaDOS 用户服务。

职责：
    - 查询积分（get_points）
    - 查询状态（get_status）+ 记录流量历史
    - 积分兑换（exchange_points）

不负责：
    - 认证（门面负责，cookie 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）
    - 签到（CheckinService 负责）
    - 按规则续费编排（门面负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Cookie。

异常传播约定：
    GladosAPIError 一律上抛，由门面处理认证降级。
    本服务不吞 GladosAPIError。
    其他异常吞掉并返回 None。
"""

from __future__ import annotations

from apps.glados.core.api import (
    GladosAPI,
    GladosAPIError,
)
from apps.glados.core.config import GladosAccountConfig
from apps.glados.core.models import Account
from apps.glados.core.parser import (
    GladosExchangeResult,
    GladosParser,
    GladosPointsResult,
    GladosStatusResult,
)
from apps.glados.core.repositories import TrafficHistoryRepository
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="glados_user",
    log_dir=logs(),
    fmt_type="detailed",
)


class UserService:
    """
    GLaDOS 用户服务。

    持有 api / parser / traffic_history_repository，
    自行发起远程调用、写流量历史；
    不写 Account 字段，不提交事务。
    """

    def __init__(
        self,
        api: GladosAPI,
        parser: GladosParser,
        traffic_history_repository: TrafficHistoryRepository,
    ) -> None:
        self.api = api
        self.parser = parser
        self.traffic_history_repository = traffic_history_repository

    # ================================================================
    # Points（积分查询）
    # ================================================================

    def get_points(
        self,
        account: GladosAccountConfig,
    ) -> GladosPointsResult | None:
        """
        查询当前账号的积分信息。

        前提：self.api 已由门面设置好 Cookie。

        异常传播：
            GladosAPIError 上抛（门面处理降级）。
            其他异常吞掉并返回 None。
        """
        logger.info(
            "获取 GLaDOS 积分信息: username=%s",
            account.username,
        )

        try:
            response = self.api.get_points()
            result = self.parser.parse_points(response)

            if not result.success:
                logger.warning(
                    "获取 GLaDOS 积分失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 GLaDOS 积分成功: username=%s, points=%.2f",
                account.username,
                result.points,
            )

            return result

        except GladosAPIError:
            logger.warning(
                "获取积分 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception:
            logger.exception(
                "获取 GLaDOS 积分异常: username=%s",
                account.username,
            )
            return None

    # ================================================================
    # Status（状态查询 + 流量历史）
    # ================================================================

    def get_status(
        self,
        account: GladosAccountConfig,
        db_account: Account,
    ) -> GladosStatusResult | None:
        """
        查询当前账号的状态信息，并记录流量历史。

        前提：self.api 已由门面设置好 Cookie。

        注意：
            本方法会写 TrafficHistory 表（流量历史）。
            Account.left_days 由门面通过 AccountService 更新。

        Args:
            account: 账号配置。
            db_account: 数据库账号对象（用于写流量历史的外键）。

        Returns:
            GladosStatusResult 或 None。
        """
        logger.info(
            "获取 GLaDOS 账号状态: username=%s",
            account.username,
        )

        try:
            response = self.api.get_status()
            result = self.parser.parse_status(response)

            if not result.success:
                logger.warning(
                    "获取 GLaDOS 账号状态失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 GLaDOS 账号状态成功: username=%s, "
                "vip=%s, left_days=%.2f, traffic=%d",
                account.username,
                result.vip,
                result.left_days,
                result.traffic_byte,
            )

            # 记录流量历史
            self.traffic_history_repository.create(
                db_account.id,
                result.traffic_byte,
                result.total_traffic_byte,
                result.total_traffic_byte - result.traffic_byte,
            )

            return result

        except GladosAPIError:
            logger.warning(
                "获取状态 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception:
            logger.exception(
                "获取 GLaDOS 账号状态异常: username=%s",
                account.username,
            )
            return None

    # ================================================================
    # Exchange（积分兑换）
    # ================================================================

    def exchange_points(
        self,
        account: GladosAccountConfig,
        plan_type: str,
    ) -> GladosExchangeResult | None:
        """
        执行积分兑换。

        前提：self.api 已由门面设置好 Cookie。

        Args:
            account: 账号配置。
            plan_type: 兑换计划类型（plan500 / plan200 / plan100）。

        Returns:
            GladosExchangeResult 或 None。
        """
        logger.info(
            "开始 GLaDOS 积分兑换: username=%s, plan_type=%s",
            account.username,
            plan_type,
        )

        try:
            response = self.api.exchange_points(plan_type)
            result = self.parser.parse_exchange(response)

            if not result.success:
                logger.warning(
                    "GLaDOS 积分兑换失败: username=%s, plan_type=%s, error=%s",
                    account.username,
                    plan_type,
                    result.error,
                )
                return None

            logger.info(
                "GLaDOS 积分兑换成功: username=%s, plan_type=%s, "
                "message=%s, points_used=%d, days_added=%d, points_remaining=%.2f",
                account.username,
                plan_type,
                result.message,
                result.points_used,
                result.days_added,
                result.points,
            )

            return result

        except GladosAPIError:
            logger.warning(
                "积分兑换 API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception:
            logger.exception(
                "GLaDOS 积分兑换异常: username=%s",
                account.username,
            )
            return None


__all__ = [
    "UserService",
]
