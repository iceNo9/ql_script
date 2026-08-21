# apps\baiyefee\core\notify_builder.py

"""
通知报告 Section 构建器。

职责：
    将 ReportData 中的结构化数据转换成 HTML Section。

输出：
    HTML Fragment。

注意：
    本模块不负责：
    - 完整 HTML 文档
    - HTML 模板
    - 邮件发送
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import ClassVar

from apps.baiyefee.core.notify_dto import (
    AccountInfo,
    CheckinResult,
    ReportData,
)
from utils.timezone import format_local_time


class SectionBuilder:
    """报告 Section 构建器。"""

    COLORS: ClassVar[dict[str, str]] = {
        "success": "#28a745",
        "danger": "#dc3545",
        "warning": "#ffc107",
        "info": "#17a2b8",
        "primary": "#2196F3",
        "purple": "#9C27B0",
        "orange": "#FF9800",
        "green": "#4CAF50",
        "teal": "#009688",
        "red": "#dc3545",
    }

    # ============================================================
    # 基础 HTML
    # ============================================================

    @staticmethod
    def _escape(value: object) -> str:
        """安全转换为 HTML 文本。"""
        return escape(
            str(value),
            quote=True,
        )

    @classmethod
    def _status_badge(
        cls,
        success: bool,
    ) -> str:
        """生成状态徽章。"""

        icon = "✅" if success else "❌"
        color = cls.COLORS["success"] if success else cls.COLORS["danger"]
        text = "成功" if success else "失败"

        return (
            f'<span style="'
            f"color:{color};"
            f"font-weight:bold;"
            f'">'
            f"{icon} {text}"
            f"</span>"
        )

    @staticmethod
    def _cell(
        content: str,
        *,
        align: str = "center",
        color: str | None = None,
        bold: bool = False,
    ) -> str:
        """生成表格单元格。"""

        style = "border:1px solid #e0e0e0;" "padding:8px 10px;" f"text-align:{align};"

        if color:
            style += f"color:{color};"

        if bold:
            style += "font-weight:bold;"

        return f'<td style="{style}">' f"{content}" f"</td>"

    @staticmethod
    def _row(
        cells: list[str],
    ) -> str:
        """生成表格行。"""

        return "<tr>" + "".join(cells) + "</tr>"

    @staticmethod
    def _time(result) -> str:
        """获取结果时间。"""

        if result.created_at is None:
            return "-"

        return format_local_time(result.created_at)

    @staticmethod
    def _format_datetime(dt: datetime | None) -> str:
        """格式化日期时间（年月日时分秒）。"""

        if dt is None:
            return "-"

        return format_local_time(dt)

    # ============================================================
    # Account
    # ============================================================

    @classmethod
    def account_section(
        cls,
        accounts: list[AccountInfo],
    ) -> str:
        """构建账户信息 Section。"""

        if not accounts:
            return ""

        rows: list[str] = []

        for account in accounts:
            # 错误次数显示为红色（如果有错误）
            error_color = cls.COLORS["red"] if account.error_count > 0 else "#666"
            error_display = (
                f"{account.error_count}次" if account.error_count > 0 else "0次"
            )

            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(account.username),
                            align="left",
                        ),
                        cls._cell(
                            f"{account.points:,}",
                            color=cls.COLORS["warning"],
                            bold=True,
                        ),
                        cls._cell(
                            f"{account.continuous_checkin_days}天",
                            color=cls.COLORS["info"],
                            bold=True,
                        ),
                        cls._cell(
                            f"{account.total_checkin_days}天",
                            color=cls.COLORS["purple"],
                            bold=True,
                        ),
                        cls._cell(
                            error_display,
                            color=error_color,
                            bold=account.error_count > 0,
                        ),
                        cls._cell(
                            cls._format_datetime(account.last_error_at),
                            color="#666",
                        ),
                    ]
                )
            )

        total = len(accounts)
        avg_points = (
            sum(account.points for account in accounts) / total if total > 0 else 0
        )
        avg_continuous = (
            sum(account.continuous_checkin_days for account in accounts) / total
            if total > 0
            else 0
        )
        avg_total_checkin = (
            sum(account.total_checkin_days for account in accounts) / total
            if total > 0
            else 0
        )
        total_errors = sum(account.error_count for account in accounts)

        return f"""
        <div style="
            background:#ffffff;
            border:2px solid {cls.COLORS["green"]};
            border-radius:6px;
            margin-bottom:25px;
            overflow:hidden;
        ">
            <div style="
                background:{cls.COLORS["green"]};
                padding:15px 20px;
                color:#ffffff;
                font-size:16px;
                font-weight:bold;
            ">
                👤 账户信息 ({total}个账户)
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                平均积分:
                <strong style="color:{cls.COLORS["warning"]};">{avg_points:.1f}</strong>
                |
                平均连续签到:
                <strong style="color:{cls.COLORS["info"]};">{avg_continuous:.1f}天</strong>
                |
                平均累计签到:
                <strong style="color:{cls.COLORS["purple"]};">{avg_total_checkin:.1f}天</strong>
                |
                总错误次数:
                <strong style="color:{cls.COLORS["red"]};">{total_errors}次</strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#e8f5e9;">
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:left;">
                            账号
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            积分
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            连续签到
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            累计签到
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            错误次数
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            上次错误时间
                        </th>
                    </tr>
                </thead>

                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        </div>
        """

    # ============================================================
    # Checkin
    # ============================================================

    @classmethod
    def checkin_section(
        cls,
        results: list[CheckinResult],
    ) -> str:
        """构建签到结果 Section。"""

        if not results:
            return ""

        rows: list[str] = []

        for result in results:
            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(result.username),
                            align="left",
                        ),
                        cls._cell(
                            cls._status_badge(result.success),
                        ),
                        cls._cell(
                            f"+{result.checkin_points}",
                            color=cls.COLORS["warning"],
                            bold=True,
                        ),
                        cls._cell(
                            cls._escape(result.message or "完成签到"),
                            align="left",
                        ),
                        cls._cell(
                            cls._time(result),
                            color="#666",
                        ),
                    ]
                )
            )

        total = len(results)
        successful = sum(1 for result in results if result.success)
        total_points = sum(
            result.checkin_points for result in results if result.success
        )
        success_rate = successful / total * 100 if total > 0 else 0

        return f"""
        <div style="
            background:#ffffff;
            border:2px solid {cls.COLORS["primary"]};
            border-radius:6px;
            margin-bottom:25px;
            overflow:hidden;
        ">
            <div style="
                background:{cls.COLORS["primary"]};
                padding:15px 20px;
                color:#ffffff;
                font-size:16px;
                font-weight:bold;
            ">
                📅 签到结果 ({successful}/{total})
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                成功:
                <strong style="color:{cls.COLORS["success"]};">{successful}次</strong>
                |
                获得积分:
                <strong style="color:{cls.COLORS["warning"]};">+{total_points}</strong>
                |
                成功率:
                <strong style="color:{cls.COLORS["info"]};">{success_rate:.1f}%</strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#e3f2fd;">
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:left;">
                            账号
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            状态
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            获得积分
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            消息
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            时间
                        </th>
                    </tr>
                </thead>

                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        </div>
        """

    # ============================================================
    # Report
    # ============================================================

    @classmethod
    def build(
        cls,
        report: ReportData,
    ) -> list[str]:
        """将 ReportData 构建为 Section HTML。

        Returns:
            Section HTML 列表。

        注意：
            这里只返回 Fragment，
            不负责完整 HTML 文档。
        """

        sections: list[str] = []

        account = cls.account_section(
            report.accounts,
        )

        if account:
            sections.append(account)

        checkin = cls.checkin_section(
            report.checkin,
        )

        if checkin:
            sections.append(checkin)

        sections.extend(section for section in report.extra_sections if section)

        return sections
