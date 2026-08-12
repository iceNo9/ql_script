from pathlib import Path
from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass
import random
import yagmail
from htmlmin import minify
from utils.log import get_logger

logger = get_logger(__name__)


# ==================== Notify 专用 DTO ====================

@dataclass
class SignResult:
    """签到结果（通知用）"""
    username: str           # 用户名
    success: bool           # 是否成功
    reward: int             # 签到获得积分
    continuous_days: int    # 连续签到天数
    message: str            # 消息


@dataclass
class AccountInfo:
    """账户信息（通知用）"""
    username: str           # 用户名
    credit: int             # 总积分
    continuous_days: int    # 连续签到天数


# ==================== 通知器 ====================

class Notifier:
    def __init__(
        self,
        smtp_client: yagmail.SMTP,
        email_to: List[str],
        template_path: Path,
        sign_results: Optional[List[SignResult]] = None,
        account_infos: Optional[List[AccountInfo]] = None,
    ):
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        self.smtp_client = smtp_client
        self.email_to = email_to
        self.template_path = template_path
        self.sign_results = sign_results or []
        self.account_infos = account_infos or []
        self.report_id = f"BYF{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"

    def _build_account_rows(self) -> str:
        """构建账户信息表格行"""
        if not self.account_infos:
            return '<tr><td colspan="3" style="border:1px solid #e0e0e0; padding:20px; text-align:center; color:#999;">暂无数据</td></tr>'
        
        rows = []
        for acc in self.account_infos:
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:left;">{acc.username}</td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center; color:#ffc107; font-weight:bold;">{acc.credit}</td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center; color:#4CAF50; font-weight:bold;">{acc.continuous_days} 天</td>
            </tr>
            ''')
        return ''.join(rows)

    def _build_sign_rows(self) -> str:
        """构建签到结果表格行"""
        if not self.sign_results:
            return '<tr><td colspan="5" style="border:1px solid #e0e0e0; padding:20px; text-align:center; color:#999;">暂无数据</td></tr>'
        
        rows = []
        for res in self.sign_results:
            status_icon = "✅" if res.success else "❌"
            status_color = "#28a745" if res.success else "#dc3545"
            status_text = "成功" if res.success else "失败"
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:left;">{res.username}</td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">
                    <span style="color:{status_color}; font-weight:bold;">{status_icon} {status_text}</span>
                </td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center; color:#ffc107; font-weight:bold;">+{res.reward}</td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center; color:#4CAF50; font-weight:bold;">{res.continuous_days} 天</td>
                <td style="border:1px solid #e0e0e0; padding:10px 12px; text-align:left; color:#666;">{res.message}</td>
            </tr>
            ''')
        return ''.join(rows)

    def _build_account_section(self) -> str:
        """构建完整的账户信息部分"""
        if not self.account_infos:
            return ''
        
        return f'''
        <div style="background:#ffffff; border:2px solid #667eea; border-radius:8px; margin-bottom:25px; overflow:hidden;">
            <div style="background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding:12px 20px; color:#ffffff; font-size:15px; font-weight:bold;">
                👤 账户信息 ({len(self.account_infos)}个账户)
            </div>
            <div style="overflow-x:auto;">
                <table style="width:100%; border-collapse:collapse; font-size:13px; min-width:400px;">
                    <thead>
                        <tr style="background:#f0f0f0;">
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:left;">账号</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">积分</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">连续签到</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._build_account_rows()}
                    </tbody>
                </table>
            </div>
        </div>
        '''

    def _build_sign_section(self) -> str:
        """构建完整的签到结果部分"""
        if not self.sign_results:
            return ''
        
        total = len(self.sign_results)
        successful = sum(1 for r in self.sign_results if r.success)
        total_reward = sum(r.reward for r in self.sign_results if r.success)
        success_rate = (successful / total * 100) if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #4CAF50; border-radius:8px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#4CAF50; padding:12px 20px; color:#ffffff; font-size:15px; font-weight:bold;">
                📅 签到结果 ({successful}/{total})
            </div>
            <div style="padding:10px 20px; background:#f8f9fa; border-bottom:1px solid #e0e0e0; font-size:12px;">
                成功: <strong style="color:#28a745;">{successful}次</strong> | 
                获得积分: <strong style="color:#ffc107;">+{total_reward}</strong> | 
                成功率: <strong style="color:#17a2b8;">{success_rate:.1f}%</strong>
            </div>
            <div style="overflow-x:auto;">
                <table style="width:100%; border-collapse:collapse; font-size:13px; min-width:600px;">
                    <thead>
                        <tr style="background:#e8f5e9;">
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:left;">账号</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">状态</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">获得积分</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">连续签到</th>
                            <th style="border:1px solid #e0e0e0; padding:10px 12px; text-align:center;">消息</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._build_sign_rows()}
                    </tbody>
                </table>
            </div>
        </div>
        '''

    def _build_email_body(self) -> str:
        """构建完整邮件HTML内容"""
        try:
            html_tpl = self.template_path.read_text(encoding="utf-8")
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 构建各部分
            account_section = self._build_account_section()
            sign_section = self._build_sign_section()
            
            # 替换占位符
            replacements = {
                "{{current_time}}": str(now),
                "{{report_id}}": str(self.report_id),
                "{{account_section}}": account_section,
                "{{sign_section}}": sign_section,
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

    def send(self, subject: str = "🎯 小白玩物箱 签到报告") -> bool:
        """发送运行报告邮件"""
        if not any([self.account_infos, self.sign_results]):
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
            logger.info(f"[+] 邮件发送成功，报告ID: {self.report_id}")
            self.smtp_client.close()
            return True
        except Exception as e:
            logger.error(f"[!] 邮件发送失败: {e}", exc_info=True)
            return False


# ==================== 导出 ====================

__all__ = [
    'SignResult',
    'AccountInfo',
    'Notifier',
]