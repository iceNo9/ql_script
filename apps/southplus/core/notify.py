# modules\southplus\core\notify.py

from pathlib import Path
from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass
import random
import yagmail
from htmlmin import minify

from utils.log import get_logger

logger = get_logger(__name__)


# ====================
# DTO（任务结果）
# ====================

@dataclass
class TaskResult:
    """任务结果"""
    username: str

    last_daily_time: str = ""
    next_daily_time: str = ""

    last_weekly_time: str = ""
    next_weekly_time: str = ""

    message: str = ""


# ====================
# DTO（账户信息）
# ====================

@dataclass
class AccountInfo:
    """账户信息"""

    username: str
    sp_coin: int = 0
    last_sp_coin: int = 0

    daily_count: int = 0
    weekly_count: int = 0


# ====================
# Notifier
# ====================

class Notifier:
    def __init__(
        self,
        smtp_client: yagmail.SMTP,
        email_to: List[str],
        template_path: Path,
        task_results: Optional[List[TaskResult]] = None,
        account_infos: Optional[List[AccountInfo]] = None,
    ):
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

        self.smtp_client = smtp_client
        self.email_to = email_to
        self.template_path = template_path

        self.task_results = task_results or []
        self.account_infos = account_infos or []

        self.report_id = f"SP{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000,9999)}"

    # ====================
    # 账户表
    # ====================

    def _build_account_rows(self) -> str:
        if not self.account_infos:
            return '<tr><td colspan="6" style="text-align:center;color:#999;">暂无数据</td></tr>'

        rows = []
        for acc in self.account_infos:

            change = acc.sp_coin - acc.last_sp_coin
            change_icon = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            change_color = "#4caf50" if change > 0 else "#f44336" if change < 0 else "#999"
            change_text = f"{change_icon} {change:+d}" if change != 0 else f"{change_icon} 0"

            rows.append(f"""
            <tr>
                <td style="border:1px solid #e0e0e0;padding:10px;">{acc.username}</td>
                <td style="border:1px solid #e0e0e0;padding:10px;text-align:center;color:#ff9800;font-weight:bold;">{acc.sp_coin}</td>
                <td style="border:1px solid #e0e0e0;padding:10px;text-align:center;color:#2196f3;">{acc.last_sp_coin}</td>
                <td style="border:1px solid #e0e0e0;padding:10px;text-align:center;color:{change_color};font-weight:bold;">{change_text}</td>
                <td style="border:1px solid #e0e0e0;padding:10px;text-align:center;">{acc.daily_count}</td>
                <td style="border:1px solid #e0e0e0;padding:10px;text-align:center;">{acc.weekly_count}</td>
            </td>
            """)
        return "".join(rows)

    # ====================
    # 任务表
    # ====================

    def _build_task_rows(self) -> str:
        if not self.task_results:
            return '<tr><td colspan="5" style="text-align:center;color:#999;">暂无数据</td></tr>'

        rows = []
        for t in self.task_results:
            rows.append(f"""
            <tr>
                <td style="border:1px solid #e0e0e0;padding:10px;">{t.username}</td>

                <td style="border:1px solid #e0e0e0;padding:10px;font-size:12px;">
                    {t.last_daily_time}
                </td>

                <td style="border:1px solid #e0e0e0;padding:10px;font-size:12px;">
                    {t.next_daily_time}
                </td>

                <td style="border:1px solid #e0e0e0;padding:10px;font-size:12px;">
                    {t.last_weekly_time}
                </td>

                <td style="border:1px solid #e0e0e0;padding:10px;font-size:12px;">
                    {t.next_weekly_time}
                </td>
            </tr>
            """)
        return "".join(rows)

    # ====================
    # section
    # ====================

    def _build_account_section(self) -> str:
        if not self.account_infos:
            return ""

        return f"""
        <div style="background:#fff;border:2px solid #667eea;border-radius:8px;margin-bottom:20px;">
            <div style="background:#667eea;color:#fff;padding:10px 15px;font-weight:bold;">
                👤 账户信息
            </div>

            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:#f5f5f5;">
                        <th>账号</th>
                        <th>SP币</th>
                        <th>上次SP币</th>
                        <th>变化</th>
                        <th>日常次数</th>
                        <th>周常次数</th>
                    </tr>
                </thead>
                <tbody>
                    {self._build_account_rows()}
                </tbody>
            </table>
        </div>
        """

    def _build_task_section(self) -> str:
        if not self.task_results:
            return ""

        return f"""
        <div style="background:#fff;border:2px solid #4caf50;border-radius:8px;margin-bottom:20px;">
            <div style="background:#4caf50;color:#fff;padding:10px 15px;font-weight:bold;">
                📅 任务状态
            </div>

            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:#e8f5e9;">
                        <th>账号</th>
                        <th>上次日常</th>
                        <th>下次日常</th>
                        <th>上次周常</th>
                        <th>下次周常</th>
                    </tr>
                </thead>
                <tbody>
                    {self._build_task_rows()}
                </tbody>
            </table>
        </div>
        """

    # ====================
    # HTML
    # ====================

    def _build_email_body(self) -> str:
        html_tpl = self.template_path.read_text(encoding="utf-8")

        html_tpl = html_tpl.replace("{{current_time}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        html_tpl = html_tpl.replace("{{report_id}}", self.report_id)
        html_tpl = html_tpl.replace("{{account_section}}", self._build_account_section())
        html_tpl = html_tpl.replace("{{task_section}}", self._build_task_section())

        try:
            return minify(html_tpl, remove_empty_space=True, remove_comments=True)
        except Exception:
            return html_tpl

    # ====================
    # send
    # ====================

    def send(self, subject: str = "南+ 自动任务报告") -> bool:
        try:
            html = self._build_email_body()

            self.smtp_client.send(
                to=self.email_to,
                subject=subject,
                contents=[html],
                headers={
                    "X-Report-ID": self.report_id
                }
            )

            self.smtp_client.close()
            logger.info(f"邮件发送成功 {self.report_id}")
            return True

        except Exception as e:
            logger.error(f"邮件发送失败: {e}", exc_info=True)
            return False


__all__ = [
    "TaskResult",
    "AccountInfo",
    "Notifier",
]