# apps\hifiti\core\report.py

"""
Hifiti 报告服务。

职责：
    从数据库读取账号 / 签到日志，构建 Hifiti HTML 运行报告。

不负责：
    - 数据库连接与事务（由调用方管理）
    - 认证
    - 签到业务
    - HTML Section 构建细节（委托 notify_builder）
    - HTML 模板渲染（委托 utils.renderer）
"""

from __future__ import annotations

from apps.hifiti.core.config import HifitiAccountConfig
from apps.hifiti.core.notify_builder import SectionBuilder
from apps.hifiti.core.notify_dto import (
    AccountInfo,
    AppConfig,
    CheckinResult,
    ReportData,
)
from apps.hifiti.core.repositories import (
    AccountRepository,
    CheckinLogRepository,
)
from utils.log import get_logger
from utils.paths import logs
from utils.renderer import ReportRenderer

logger = get_logger(
    name="hifiti_report",
    log_dir=logs(),
    fmt_type="detailed",
)

# ================================================================
# 应用展示配置
# ================================================================

_APP_CONFIG = AppConfig(
    name="Hifiti",
    icon="💎",
    gradient_start="#667eea",
    gradient_end="#764ba2",
)


class ReportService:
    """
    Hifiti 报告服务。

    只读服务：仅依赖两个 Repository，不持有 Session，不提交事务。
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        checkin_log_repository: CheckinLogRepository,
    ) -> None:
        self.account_repository = account_repository
        self.checkin_log_repository = checkin_log_repository

    # ============================================================
    # 公开入口
    # ============================================================

    def build_html(
        self,
        account_configs: list[HifitiAccountConfig],
    ) -> str:
        """
        构建 Hifiti HTML 运行报告。

        Args:
            account_configs: 账号配置列表（用于确定统计范围）。

        Returns:
            完整 HTML 文档字符串。
        """
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
        account_configs: list[HifitiAccountConfig],
    ) -> ReportData:
        """从数据库收集报告所需的全部结构化数据。"""

        if not account_configs:
            logger.warning("没有配置 Hifiti 账号，跳过报告统计")
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
            (account_info, checkin_result)，
            账号不存在时返回 (None, None)。
        """
        db_account = self.account_repository.get_by_username(username)

        if db_account is None:
            logger.warning("账号 %s 不存在，跳过报告统计", username)
            return None, None

        account_info = AccountInfo(
            username=db_account.username,
            gold=db_account.gold,
            continuous_checkin_days=db_account.streak_days,
            total_checkin_days=db_account.total_days,
            error_count=db_account.error_count,
            last_error_at=db_account.last_error_at,
        )

        checkin_log = self.checkin_log_repository.get_latest_by_account_id(
            db_account.id
        )

        if checkin_log is None:
            return account_info, None

        checkin_result = CheckinResult(
            username=db_account.username,
            success=checkin_log.success,
            checkin_gold=checkin_log.checkin_gold,
            checkin_rank=checkin_log.checkin_rank,
            message=checkin_log.message or "",
            created_at=checkin_log.checkin_at,
        )

        return account_info, checkin_result


__all__ = [
    "ReportService",
]
