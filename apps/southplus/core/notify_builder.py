"""
SouthPlus 通知报告 Section 构建器。

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

from apps.southplus.core.notify_dto import (
    AccountInfo,
    DailyTaskInfo,
    ReportData,
    WeeklyTaskInfo,
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
        "sp": "#9C27B0",
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
    def _format_datetime(
        dt: datetime | None,
    ) -> str:
        """格式化日期时间。"""

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
            error_color = cls.COLORS["red"] if account.error_count > 0 else "#666"

            error_display = f"{account.error_count}次"

            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(account.username),
                            align="left",
                        ),
                        cls._cell(
                            f"{account.points_sp:,}",
                            color=cls.COLORS["sp"],
                            bold=True,
                        ),
                        cls._cell(
                            error_display,
                            color=error_color,
                            bold=account.error_count > 0,
                        ),
                        cls._cell(
                            cls._format_datetime(
                                account.last_error_at,
                            ),
                            color="#666",
                        ),
                    ]
                )
            )

        total = len(accounts)

        total_points_sp = sum(account.points_sp for account in accounts)

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
                SP Point 总计:
                <strong style="
                    color:{cls.COLORS["sp"]};
                ">
                    {total_points_sp:,}
                </strong>

                |

                总错误次数:
                <strong style="
                    color:{cls.COLORS["red"]};
                ">
                    {total_errors}次
                </strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#e8f5e9;">
                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:left;
                        ">
                            账号
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            SP Point
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            错误次数
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
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
    # Daily
    # ============================================================

    @classmethod
    def daily_section(
        cls,
        tasks: list[DailyTaskInfo],
    ) -> str:
        """构建日常任务 Section。"""

        if not tasks:
            return ""

        rows: list[str] = []

        for task in tasks:
            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(task.username),
                            align="left",
                        ),
                        cls._cell(
                            f"{task.complete_count}次",
                            color=cls.COLORS["info"],
                            bold=True,
                        ),
                        cls._cell(
                            cls._format_datetime(
                                task.last_complete_at,
                            ),
                            color="#666",
                        ),
                        cls._cell(
                            cls._format_datetime(
                                task.next_complete_at,
                            ),
                            color=cls.COLORS["primary"],
                            bold=True,
                        ),
                    ]
                )
            )

        total = len(tasks)

        total_complete_count = sum(task.complete_count for task in tasks)

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
                📅 日常任务 ({total}个账户)
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                累计完成:
                <strong style="
                    color:{cls.COLORS["info"]};
                ">
                    {total_complete_count}次
                </strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#e3f2fd;">
                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:left;
                        ">
                            账号
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            完成次数
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            上次完成时间
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            下次完成时间
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
    # Weekly
    # ============================================================

    @classmethod
    def weekly_section(
        cls,
        tasks: list[WeeklyTaskInfo],
    ) -> str:
        """构建周常任务 Section。"""

        if not tasks:
            return ""

        rows: list[str] = []

        for task in tasks:
            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(task.username),
                            align="left",
                        ),
                        cls._cell(
                            f"{task.complete_count}次",
                            color=cls.COLORS["purple"],
                            bold=True,
                        ),
                        cls._cell(
                            cls._format_datetime(
                                task.last_complete_at,
                            ),
                            color="#666",
                        ),
                        cls._cell(
                            cls._format_datetime(
                                task.next_complete_at,
                            ),
                            color=cls.COLORS["purple"],
                            bold=True,
                        ),
                    ]
                )
            )

        total = len(tasks)

        total_complete_count = sum(task.complete_count for task in tasks)

        return f"""
        <div style="
            background:#ffffff;
            border:2px solid {cls.COLORS["purple"]};
            border-radius:6px;
            margin-bottom:25px;
            overflow:hidden;
        ">
            <div style="
                background:{cls.COLORS["purple"]};
                padding:15px 20px;
                color:#ffffff;
                font-size:16px;
                font-weight:bold;
            ">
                📆 周常任务 ({total}个账户)
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                累计完成:
                <strong style="
                    color:{cls.COLORS["purple"]};
                ">
                    {total_complete_count}次
                </strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#f3e5f5;">
                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:left;
                        ">
                            账号
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            完成次数
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            上次完成时间
                        </th>

                        <th style="
                            border:1px solid #e0e0e0;
                            padding:10px;
                            text-align:center;
                        ">
                            下次完成时间
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

        daily = cls.daily_section(
            report.daily,
        )

        if daily:
            sections.append(daily)

        weekly = cls.weekly_section(
            report.weekly,
        )

        if weekly:
            sections.append(weekly)

        sections.extend(section for section in report.extra_sections if section)

        return sections


__all__ = [
    "SectionBuilder",
]
