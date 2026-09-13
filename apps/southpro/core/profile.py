# apps/southpro/core/profile.py

"""
SouthPro Profile 服务。

职责：
    - 查询远程 Profile（SP 币）
    - 产出 SouthProProfileResult

不负责：
    - 认证（门面负责，cookie 由门面提前设好）
    - Account 字段写入（AccountService 负责）
    - 事务提交（门面负责）
    - 报告构建（ReportService 负责）

前提：
    调用方（门面）必须已在 self.api 上设置好有效 Cookie。

异常传播约定：
    SouthProAPIError 一律上抛，由门面处理认证降级。
    其他异常吞掉并返回 None。
"""

from __future__ import annotations

from apps.southpro.core.api import (
    SouthProAPI,
    SouthProAPIError,
)
from apps.southpro.core.config import SouthProAccountConfig
from apps.southpro.core.parser import (
    SouthProParser,
    SouthProProfileResult,
)
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="southpro_profile",
    log_dir=logs(),
    fmt_type="detailed",
)


class ProfileService:
    """
    SouthPro Profile 服务。

    持有 api / parser，自行发起远程调用；
    不写 Account 字段，不提交事务。
    """

    def __init__(
        self,
        api: SouthProAPI,
        parser: SouthProParser,
    ) -> None:
        self.api = api
        self.parser = parser

    # ================================================================
    # 查询 Profile
    # ================================================================

    def get_profile(
        self,
        account: SouthProAccountConfig,
    ) -> SouthProProfileResult | None:
        """
        查询当前账号的 Profile。

        前提：self.api 已由门面设置好 Cookie。

        异常传播：
            SouthProAPIError 上抛（门面处理降级）。
            其他异常吞掉并返回 None。
        """
        logger.info(
            "获取 SouthPro Profile: username=%s",
            account.username,
        )

        try:
            response = self.api.get_profile()
            result = self.parser.parse_profile(response)

            if not result.success:
                logger.warning(
                    "获取 SouthPro Profile 失败: username=%s, error=%s",
                    account.username,
                    result.error,
                )
                return None

            logger.debug(
                "获取 SouthPro Profile 成功: username=%s, points_sp=%d",
                account.username,
                result.points_sp,
            )

            return result

        except SouthProAPIError:
            logger.warning(
                "获取 Profile API 异常，上抛给门面处理降级: username=%s",
                account.username,
            )
            raise

        except Exception:
            logger.exception(
                "获取 SouthPro Profile 异常: username=%s",
                account.username,
            )
            return None


__all__ = [
    "ProfileService",
]
