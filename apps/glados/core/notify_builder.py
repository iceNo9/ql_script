"""
modules/core/notify/builder.py

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

from html import escape
from typing import ClassVar

from apps.glados.core.notify_dto import (
    AccountInfo,
    CheckinResult,
    CodeResult,
    RedeemResult,
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
            used_gb = account.current_traffic / (1024**3)

            total_gb = account.total_traffic / (1024**3)

            remaining_gb = max(
                0,
                total_gb - used_gb,
            )

            remaining_pct = max(
                0,
                100 - account.use_percent,
            )

            if account.use_percent < 50:
                usage_color = cls.COLORS["success"]

            elif account.use_percent < 80:
                usage_color = cls.COLORS["warning"]

            elif account.use_percent < 100:
                usage_color = cls.COLORS["orange"]

            else:
                usage_color = cls.COLORS["danger"]

            rows.append(
                cls._row(
                    [
                        cls._cell(
                            cls._escape(account.username),
                            align="left",
                        ),
                        cls._cell(
                            f"{account.points:,}",
                        ),
                        cls._cell(
                            f"{account.left_days}天",
                        ),
                        cls._cell(
                            f"{used_gb:.1f}GB / " f"{total_gb:.1f}GB",
                        ),
                        cls._cell(
                            f"{remaining_gb:.1f}GB",
                        ),
                        cls._cell(
                            f"{account.use_percent:.1f}%",
                            color=usage_color,
                            bold=True,
                        ),
                        cls._cell(
                            f"{remaining_pct:.1f}%",
                        ),
                        # 新增：连续签到天数
                        cls._cell(
                            f"{account.continuous_checkin_days}天",
                            color=cls.COLORS["info"],
                            bold=True,
                        ),
                        # 新增：总签到天数
                        cls._cell(
                            f"{account.total_checkin_days}天",
                            color=cls.COLORS["purple"],
                            bold=True,
                        ),
                    ]
                )
            )

        total = len(accounts)

        avg_days = sum(account.left_days for account in accounts) / total

        avg_points = sum(account.points for account in accounts) / total

        total_traffic = sum(account.total_traffic / (1024**3) for account in accounts)

        # 新增：平均连续签到天数
        avg_continuous = (
            sum(account.continuous_checkin_days for account in accounts) / total
        )

        # 新增：平均总签到天数
        avg_total_checkin = (
            sum(account.total_checkin_days for account in accounts) / total
        )

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
                平均剩余:
                <strong>{avg_days:.1f}天</strong>
                |
                平均积分:
                <strong>{avg_points:.1f}</strong>
                |
                总流量:
                <strong>{total_traffic:.0f}GB</strong>
                |
                平均连续签到:
                <strong style="color:{cls.COLORS["info"]};">{avg_continuous:.1f}天</strong>
                |
                平均总签到:
                <strong style="color:{cls.COLORS["purple"]};">{avg_total_checkin:.1f}天</strong>
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
                            剩余天数
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            已用流量
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            剩余流量
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            使用率
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            剩余率
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            连续签到
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            总签到
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
                            f"+{result.point}",
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

        total_points = sum(result.point for result in results if result.success)

        success_rate = successful / total * 100

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
                <strong style="color:{cls.COLORS["success"]};">
                    {successful}次
                </strong>
                |
                积分:
                <strong style="color:{cls.COLORS["warning"]};">
                    +{total_points}
                </strong>
                |
                成功率:
                <strong style="color:{cls.COLORS["info"]};">
                    {success_rate:.1f}%
                </strong>
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
    # Code
    # ============================================================

    @classmethod
    def code_section(
        cls,
        results: list[CodeResult],
    ) -> str:
        """构建礼品码兑换 Section。"""

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
                            f"+{result.days}天",
                            color=cls.COLORS["success"],
                            bold=True,
                        ),
                        cls._cell(
                            cls._escape(result.message or "兑换完成"),
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

        total_days = sum(result.days for result in results if result.success)

        success_rate = successful / total * 100

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
                🎁 礼品码兑换 ({successful}/{total})
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                成功:
                <strong style="color:{cls.COLORS["success"]};">
                    {successful}次
                </strong>
                |
                增加天数:
                <strong style="color:{cls.COLORS["info"]};">
                    +{total_days}天
                </strong>
                |
                成功率:
                <strong style="color:{cls.COLORS["info"]};">
                    {success_rate:.1f}%
                </strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#f3e5f5;">
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:left;">
                            账号
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            状态
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            增加天数
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
    # Redeem
    # ============================================================

    @classmethod
    def redeem_section(
        cls,
        results: list[RedeemResult],
    ) -> str:
        """构建蛋糕兑换 Section。"""

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
                            f"{result.amount}个",
                            color=cls.COLORS["danger"],
                            bold=True,
                        ),
                        cls._cell(
                            cls._escape(result.message or "兑换完成"),
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

        total_amount = sum(result.amount for result in results if result.success)

        success_rate = successful / total * 100

        return f"""
        <div style="
            background:#ffffff;
            border:2px solid {cls.COLORS["orange"]};
            border-radius:6px;
            margin-bottom:25px;
            overflow:hidden;
        ">
            <div style="
                background:{cls.COLORS["orange"]};
                padding:15px 20px;
                color:#ffffff;
                font-size:16px;
                font-weight:bold;
            ">
                🍰 蛋糕兑换 ({successful}/{total})
            </div>

            <div style="
                padding:12px 20px;
                background:#f9f9f9;
                border-bottom:1px solid #e0e0e0;
                font-size:13px;
            ">
                成功:
                <strong style="color:{cls.COLORS["success"]};">
                    {successful}次
                </strong>
                |
                消耗蛋糕:
                <strong style="color:{cls.COLORS["danger"]};">
                    {total_amount}个
                </strong>
                |
                成功率:
                <strong style="color:{cls.COLORS["info"]};">
                    {success_rate:.1f}%
                </strong>
            </div>

            <table style="
                width:100%;
                border-collapse:collapse;
                font-size:13px;
            ">
                <thead>
                    <tr style="background:#fff3e0;">
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:left;">
                            账号
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            状态
                        </th>
                        <th style="border:1px solid #e0e0e0;padding:10px;text-align:center;">
                            消耗数量
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

        code = cls.code_section(
            report.codes,
        )

        if code:
            sections.append(code)

        redeem = cls.redeem_section(
            report.redeem,
        )

        if redeem:
            sections.append(redeem)

        sections.extend(section for section in report.extra_sections if section)

        return sections
