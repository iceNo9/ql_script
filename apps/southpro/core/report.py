# apps/southpro/core/report.py

"""
SouthPro 报告服务。

职责：
    从数据库读取账号信息，构建 SouthPro HTML 运行报告。

不负责：
    - 数据库连接与事务（由调用方管理）
    - 认证
    - 任务业务
    - next_complete_at 计算（由 DailyTaskService / WeeklyTaskService 负责）
    - HTML Section 构建细节（委托 notify_builder）
    - HTML 模板渲染（委托 utils.renderer）

设计说明：
    DailyTaskInfo / WeeklyTaskInfo 由门面调用任务 Service 计算后传入，
    本服务不感知 DAILY_INTERVAL / WEEKLY_INTERVAL。
"""

from __future__ import annotations

from apps.southpro.core.config import SouthProAccountConfig
from apps.southpro.core.notify_builder import SectionBuilder
from apps.southpro.core.notify_dto import (
    AccountInfo,
    AppConfig,
    DailyTaskInfo,
    ReportData,
    WeeklyTaskInfo,
)
from apps.southpro.core.repositories import AccountRepository
from utils.log import get_logger
from utils.paths import logs
from utils.renderer import ReportRenderer

logger = get_logger(
    name="southpro_report",
    log_dir=logs(),
    fmt_type="detailed",
)

# ================================================================
# 应用展示配置
# ================================================================

_APP_CONFIG = AppConfig(
    name="SouthPro",
    icon="💎",
    gradient_start="#667eea",
    gradient_end="#764ba2",
)


class ReportService:
    """
    SouthPro 报告服务。

    只读服务：仅依赖 AccountRepository，不持有 Session，不提交事务。
    """

    def __init__(
        self,
        account_repository: AccountRepository,
    ) -> None:
        self.account_repository = account_repository

    # ============================================================
    # 公开入口
    # ============================================================

    def build_html(
        self,
        account_configs: list[SouthProAccountConfig],
        *,
        daily_infos: list[DailyTaskInfo],
        weekly_infos: list[WeeklyTaskInfo],
    ) -> str:
        """
        构建 SouthPro HTML 运行报告。

        Args:
            account_configs: 账号配置列表（用于确定统计范围）。
            daily_infos: 门面调 DailyTaskService.build_report_infos() 算好。
            weekly_infos: 门面调 WeeklyTaskService.build_report_infos() 算好。

        Returns:
            完整 HTML 文档字符串。
        """
        report_data = self._collect(
            account_configs,
            daily_infos=daily_infos,
            weekly_infos=weekly_infos,
        )

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
        account_configs: list[SouthProAccountConfig],
        *,
        daily_infos: list[DailyTaskInfo],
        weekly_infos: list[WeeklyTaskInfo],
    ) -> ReportData:
        """从数据库收集报告所需的全部结构化数据。"""

        if not account_configs:
            logger.warning("没有配置 SouthPro 账号，跳过报告统计")
            return ReportData(
                app=_APP_CONFIG,
                daily=daily_infos,
                weekly=weekly_infos,
            )

        accounts: list[AccountInfo] = []

        for account_config in account_configs:
            username = account_config.username

            try:
                account_info = self._collect_one(username)
            except Exception:
                logger.exception(
                    "账号 %s 统计报告信息异常",
                    username,
                )
                continue

            if account_info is not None:
                accounts.append(account_info)

        return ReportData(
            app=_APP_CONFIG,
            accounts=accounts,
            daily=daily_infos,
            weekly=weekly_infos,
        )

    def _collect_one(
        self,
        username: str,
    ) -> AccountInfo | None:
        """
        收集单个账号的账户信息。

        Returns:
            AccountInfo，账号不存在时返回 None。
        """
        db_account = self.account_repository.get_by_username(username)

        if db_account is None:
            logger.warning("账号 %s 不存在，跳过报告统计", username)
            return None

        return AccountInfo(
            username=db_account.username,
            points_sp=db_account.points_sp,
            error_count=db_account.error_count,
            last_error_at=db_account.last_error_at,
        )


__all__ = [
    "ReportService",
]
