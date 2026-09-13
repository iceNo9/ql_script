# apps\glados\core\report.py

"""
GLaDOS 报告服务。

职责：
    从数据库读取账号 / 签到日志 / 流量历史，构建 GLaDOS HTML 运行报告。

不负责：
    - 数据库连接与事务（由调用方管理）
    - 认证
    - 签到 / 积分 / 状态业务
    - HTML Section 构建细节（委托 notify_builder）
    - HTML 模板渲染（委托 utils.renderer）
"""

from __future__ import annotations

from apps.glados.core.config import GladosAccountConfig
from apps.glados.core.notify_builder import SectionBuilder
from apps.glados.core.notify_dto import (
    AccountInfo,
    AppConfig,
    CheckinResult,
    ReportData,
)
from apps.glados.core.repositories import (
    AccountRepository,
    CheckinLogRepository,
    TrafficHistoryRepository,
)
from utils.log import get_logger
from utils.paths import logs
from utils.renderer import ReportRenderer

logger = get_logger(
    name="glados_report",
    log_dir=logs(),
    fmt_type="detailed",
)

# ================================================================
# 应用展示配置
# ================================================================

_APP_CONFIG = AppConfig(
    name="GLaDOS",
    icon="🤖",
    gradient_start="#667eea",
    gradient_end="#764ba2",
)


class ReportService:
    """
    GLaDOS 报告服务。

    只读服务：仅依赖三个 Repository，不持有 Session，不提交事务。
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        checkin_log_repository: CheckinLogRepository,
        traffic_history_repository: TrafficHistoryRepository,
    ) -> None:
        self.account_repository = account_repository
        self.checkin_log_repository = checkin_log_repository
        self.traffic_history_repository = traffic_history_repository

    # ============================================================
    # 公开入口
    # ============================================================

    def build_html(
        self,
        account_configs: list[GladosAccountConfig],
    ) -> str:
        """构建 GLaDOS HTML 运行报告。"""
        report_data = self._collect(account_configs)

        sections = SectionBuilder.build(report_data)

        renderer = ReportRenderer(
            app_name=_APP_CONFIG.name,
            app_icon=_APP_CONFIG.icon,
            gradient_start=_APP_CONFIG.gradient_start,
            gradient_end=_APP_CONFIG.gradient_end,
        )

        return renderer.render(sections)

    # ============================================================
    # 数据收集
    # ============================================================

    def _collect(
        self,
        account_configs: list[GladosAccountConfig],
    ) -> ReportData:
        """从数据库收集报告所需的全部结构化数据。"""

        if not account_configs:
            logger.warning("没有配置 GLaDOS 账号，跳过报告统计")
            return ReportData(app=_APP_CONFIG)

        accounts: list[AccountInfo] = []
        checkin: list[CheckinResult] = []

        for account_config in account_configs:
            username = account_config.username

            try:
                account_info, checkin_result = self._collect_one(username)
            except Exception:
                logger.exception(
                    "账号 %s 统计报告信息异常",
                    username,
                )
                continue

            if account_info is not None:
                accounts.append(account_info)

            if checkin_result is not None:
                checkin.append(checkin_result)

        return ReportData(
            app=_APP_CONFIG,
            accounts=accounts,
            checkin=checkin,
        )

    def _collect_one(
        self,
        username: str,
    ) -> tuple[AccountInfo | None, CheckinResult | None]:
        """
        收集单个账号的报告数据。

        Returns:
            (account_info, checkin_result)。
            账号不存在或无流量记录时 account_info 为 None。
        """
        account = self.account_repository.get_by_username(username)

        if account is None:
            logger.warning("账号 %s 不存在，跳过报告统计", username)
            return None, None

        # ------------------------------------------------------------
        # 账户信息（依赖流量记录）
        # ------------------------------------------------------------

        account_info: AccountInfo | None = None

        traffic = self.traffic_history_repository.get_latest_by_account_id(account.id)

        if traffic is not None:
            total_traffic = traffic.total_traffic_bytes
            used_traffic = traffic.used_traffic_bytes

            if total_traffic > 0:
                use_percent = used_traffic / total_traffic * 100
            else:
                use_percent = 0.0

            account_info = AccountInfo(
                username=account.username,
                points=account.points,
                left_days=account.left_days,
                current_traffic=used_traffic,
                total_traffic=total_traffic,
                use_percent=use_percent,
                continuous_checkin_days=account.streak_days,
                total_checkin_days=account.total_days,
            )

        # ------------------------------------------------------------
        # 最近一次签到
        # ------------------------------------------------------------

        checkin_result: CheckinResult | None = None

        checkin_log = self.checkin_log_repository.get_latest_by_account_id(account.id)

        if checkin_log is not None:
            checkin_result = CheckinResult(
                username=account.username,
                success=checkin_log.success,
                points=checkin_log.points,  # DTO 字段是单数 point
                message=checkin_log.message or "",
                created_at=checkin_log.checkin_at,
            )

        return account_info, checkin_result


__all__ = [
    "ReportService",
]
