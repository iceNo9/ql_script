"""
utils/renderer.py

通用 HTML 报告渲染器。

职责：
    将 Section HTML 套入统一的 HTML 报告模板。

本模块不依赖任何具体业务应用。

输入：
    list[str]
        HTML Section。

输出：
    str
        完整 HTML 文档。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from utils.paths import templates

# 报告展示时区：北京时间（UTC+8）
DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ReportRenderer:
    """通用 HTML 报告渲染器。"""

    def __init__(
        self,
        *,
        app_name: str,
        app_icon: str = "🚀",
        gradient_start: str = "#667eea",
        gradient_end: str = "#764ba2",
    ) -> None:
        self.app_name = app_name
        self.app_icon = app_icon
        self.gradient_start = gradient_start
        self.gradient_end = gradient_end

    def render(
        self,
        sections: list[str],
        *,
        report_id: str | None = None,
        current_time: datetime | None = None,
    ) -> str:
        """渲染完整 HTML 报告。"""

        template = self._load_template()

        report_id = report_id or self._generate_report_id()

        # 内部统一使用 UTC 时间。
        current_time = current_time or datetime.now(UTC)

        # 转换为北京时间，仅用于报告展示。
        display_time = current_time.astimezone(DISPLAY_TIMEZONE)

        section_html = "".join(section for section in sections if section)

        if not section_html:
            section_html = self._empty_section()

        replacements = {
            "{{app_name}}": self.app_name,
            "{{app_icon}}": self.app_icon,
            "{{gradient_start}}": self.gradient_start,
            "{{gradient_end}}": self.gradient_end,
            "{{current_time}}": display_time.strftime("%Y-%m-%d %H:%M:%S"),
            "{{report_id}}": report_id,
            "{{sections}}": section_html,
        }

        for placeholder, value in replacements.items():
            template = template.replace(
                placeholder,
                value,
            )

        return template

    @staticmethod
    def _load_template() -> str:
        """加载统一报告模板。"""

        template_path = templates() / "report.html"

        if not template_path.is_file():
            raise FileNotFoundError(f"报告模板不存在: {template_path}")

        return template_path.read_text(
            encoding="utf-8",
        )

    @staticmethod
    def _generate_report_id() -> str:
        """生成报告 ID。"""

        return uuid4().hex[:12]

    @staticmethod
    def _empty_section() -> str:
        """生成空报告 Section。"""

        return """
        <div style="
            background:#fff3cd;
            border:2px solid #ffc107;
            border-radius:6px;
            padding:20px;
            text-align:center;
            color:#856404;
            margin-bottom:25px;
        ">
            <p style="
                margin:0;
                font-size:16px;
            ">
                📭 本次运行无任何操作数据
            </p>
        </div>
        """
