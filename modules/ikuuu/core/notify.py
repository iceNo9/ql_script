from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import random
import yagmail
from htmlmin import minify
from common.log import get_logger

logger = get_logger(__name__)

class IkuuuNotifier:
    def __init__(
        self,
        smtp_client: yagmail.SMTP,
        email_to: List[str],
        template_path: Path,
        checkin_results: Optional[List] = None,
        account_infos: Optional[List] = None,
    ):
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        self.smtp_client = smtp_client
        self.email_to = email_to
        self.template_path = template_path
        self.checkin_results = checkin_results or []
        self.account_infos = account_infos or []
        self.report_id = f"IKU{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"

    def _format_bytes(self, bytes_value: int) -> str:
        """格式化字节数为易读的单位"""
        if bytes_value >= 1024 ** 3:  # GB
            return f"{bytes_value / (1024 ** 3):.2f} GB"
        elif bytes_value >= 1024 ** 2:  # MB
            return f"{bytes_value / (1024 ** 2):.2f} MB"
        elif bytes_value >= 1024:  # KB
            return f"{bytes_value / 1024:.2f} KB"
        else:
            return f"{bytes_value} B"

    def _calculate_usage_percent(self, used_bytes: int, total_bytes: int) -> float:
        """计算使用率百分比"""
        if total_bytes == 0:
            return 0.0
        return (used_bytes / total_bytes) * 100

    def _get_usage_color(self, usage_percent: float) -> str:
        """根据使用率返回颜色"""
        if usage_percent < 50:
            return "#28a745"  # 绿色
        elif usage_percent < 80:
            return "#ffc107"  # 黄色
        else:
            return "#dc3545"  # 红色

    def _build_account_section(self) -> str:
        """构建完整的账户信息部分"""
        if not self.account_infos:
            return ""
        
        rows = []
        for acc in self.account_infos:
            used_bytes = acc.used_bytes
            total_bytes = acc.total_bytes
            remain_bytes = acc.remain_bytes
            today_used_bytes = acc.today_used_bytes
            
            usage_percent = self._calculate_usage_percent(used_bytes, total_bytes)
            usage_color = self._get_usage_color(usage_percent)
            remain_percent = 100 - usage_percent
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{acc.id}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{self._format_bytes(total_bytes)}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{self._format_bytes(used_bytes)}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{self._format_bytes(remain_bytes)}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{self._format_bytes(today_used_bytes)}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{usage_color}; font-weight:bold;">{usage_percent:.1f}%</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{remain_percent:.1f}%</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.account_infos)
        total_total_bytes = sum(acc.total_bytes for acc in self.account_infos)
        total_used_bytes = sum(acc.used_bytes for acc in self.account_infos)
        total_remain_bytes = sum(acc.remain_bytes for acc in self.account_infos)
        total_today_used_bytes = sum(acc.today_used_bytes for acc in self.account_infos)
        avg_usage_percent = sum(self._calculate_usage_percent(acc.used_bytes, acc.total_bytes) for acc in self.account_infos) / total if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #4CAF50; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#4CAF50; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #4CAF50;">
                👤 Ikuuu 账户信息 ({total}个账户)
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                总流量: <strong>{self._format_bytes(total_total_bytes)}</strong> | 已使用: <strong>{self._format_bytes(total_used_bytes)}</strong> | 
                剩余: <strong>{self._format_bytes(total_remain_bytes)}</strong> | 今日使用: <strong>{self._format_bytes(total_today_used_bytes)}</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#e8f5e9;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">总流量</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">已使用</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">剩余流量</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">今日使用</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">使用率</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">剩余率</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
            <div style="padding:12px 20px; background:#f9f9f9; border-top:1px solid #e0e0e0; font-size:13px;">
                平均使用率: <strong style="color:{self._get_usage_color(avg_usage_percent)};">{avg_usage_percent:.1f}%</strong>
            </div>
        </div>
        '''

    def _build_checkin_section(self) -> str:
        """构建完整的签到结果部分"""
        if not self.checkin_results:
            return ""
        
        rows = []
        for res in self.checkin_results:
            status_icon = "✅" if res.success else "❌"
            status_color = "#28a745" if res.success else "#dc3545"
            change_display = f"+{self._format_bytes(res.change_bytes)}" if res.change_bytes > 0 else f"{self._format_bytes(res.change_bytes)}"
            change_color = "#28a745" if res.change_bytes > 0 else "#dc3545" if res.change_bytes < 0 else "#666"
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.id}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{status_color}; font-weight:bold;">{status_icon}{'成功' if res.success else '失败'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{change_color}; font-weight:bold;">{change_display}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.message or '完成签到'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#666;">{datetime.now().strftime('%H:%M')}</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.checkin_results)
        successful = sum(1 for r in self.checkin_results if r.success)
        total_change = sum(r.change_bytes for r in self.checkin_results if r.success)
        success_rate = (successful / total * 100) if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #2196F3; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#2196F3; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #2196F3;">
                📅 Ikuuu 签到结果 ({successful}/{total})
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                成功: <strong style="color:#28a745;">{successful}次</strong> | 总获得流量: <strong style="color:#28a745;">{self._format_bytes(total_change)}</strong> | 成功率: <strong style="color:#17a2b8;">{success_rate:.1f}%</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#e3f2fd;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">状态</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">流量变化</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">消息</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">时间</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
        '''

    def _build_email_body(self) -> str:
        """构建完整邮件HTML内容"""
        try:
            html_tpl = self.template_path.read_text(encoding="utf-8")
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 构建各部分的完整HTML
            account_section = self._build_account_section()
            checkin_section = self._build_checkin_section()
            
            # 替换占位符（确保所有值都是字符串）
            replacements = {
                "{{current_time}}": str(now),
                "{{report_id}}": str(self.report_id),
                "{{account_section}}": str(account_section),
                "{{checkin_section}}": str(checkin_section),
            }
            
            for k, v in replacements.items():
                html_tpl = html_tpl.replace(k, v)
            
            try:
                return minify(html_tpl, remove_empty_space=True, remove_comments=True)
            except Exception:
                return html_tpl
                
        except Exception as e:
            logger.error(f"[!] 构建邮件内容失败: {e}", exc_info=True)
            raise

    def send(self, subject: str = "🚀 Ikuuu 运行报告") -> bool:
        """发送运行报告邮件"""
        if not any([self.account_infos, self.checkin_results]):
            logger.warning("[!] 没有可发送的数据")
            return False
        
        try:
            html_body = self._build_email_body()
            self.smtp_client.send(
                to=self.email_to, 
                subject=subject, 
                contents=[html_body],
                headers={
                    'X-Report-ID': self.report_id,
                    'X-Priority': '1'
                }
            )
            logger.info(f"[+] Ikuuu 邮件发送成功，报告ID: {self.report_id}")
            self.smtp_client.close()
            return True
        except Exception as e:
            logger.error(f"[!] Ikuuu 邮件发送失败: {e}", exc_info=True)
            return False