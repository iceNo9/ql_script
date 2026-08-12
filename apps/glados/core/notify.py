# modules/glados/core/notify.py
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import random
import yagmail
from htmlmin import minify
from utils.log import get_logger

logger = get_logger(__name__)


# ==================== Notify 专用 DTO ====================

@dataclass
class CheckinResult:
    """签到结果（通知用）"""
    username: str
    success: bool
    point: int
    message: str


@dataclass
class CodeResult:
    """礼品码兑换结果（通知用）"""
    username: str
    success: bool
    days: int
    message: str


@dataclass
class RedeemResult:
    """蛋糕兑换结果（通知用）"""
    username: str
    success: bool
    amount: int
    message: str


@dataclass
class AccountInfo:
    """账户信息（通知用）"""
    username: str
    points: int
    left_days: int
    current_traffic: int
    total_traffic: int
    use_percent: float


# ==================== 通知器 ====================

class GladosNotifier:
    def __init__(
        self,
        smtp_client: yagmail.SMTP,
        email_to: List[str],
        template_path: Path,
        checkin_results: Optional[List[CheckinResult]] = None,
        code_results: Optional[List[CodeResult]] = None,
        redeem_results: Optional[List[RedeemResult]] = None,
        account_infos: Optional[List[AccountInfo]] = None,
    ):
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        self.smtp_client = smtp_client
        self.email_to = email_to
        self.template_path = template_path
        self.checkin_results = checkin_results or []
        self.code_results = code_results or []
        self.redeem_results = redeem_results or []
        self.account_infos = account_infos or []
        self.report_id = f"GLD{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"

    def _build_account_section(self) -> str:
        """构建完整的账户信息部分"""
        if not self.account_infos:
            return ""
        
        rows = []
        for acc in self.account_infos:
            used_gb = acc.current_traffic / (1024**3)
            total_gb = acc.total_traffic / (1024**3)
            remaining_gb = total_gb - used_gb
            use_percent = acc.use_percent
            remaining_pct = max(0, 100 - use_percent)
            
            # 确定使用率颜色
            if acc.use_percent < 50:
                usage_color = "#28a745"  # 绿色
            elif acc.use_percent < 80:
                usage_color = "#ffc107"  # 黄色
            elif acc.use_percent < 100:
                usage_color = "#fd7e14"  # 橙色
            else:
                usage_color = "#dc3545"  # 红色
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{acc.username}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{acc.points:,}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{acc.left_days}天</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{used_gb:.1f}GB / {total_gb:.1f}GB</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{remaining_gb:.1f}GB</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{usage_color}; font-weight:bold;">
                    {acc.use_percent:.1f}%
                </td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center;">{remaining_pct:.1f}%</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.account_infos)
        avg_days = sum(acc.left_days for acc in self.account_infos) / total
        avg_points = sum(acc.points for acc in self.account_infos) / total
        total_traffic = sum(acc.total_traffic / (1024**3) for acc in self.account_infos)
        
        return f'''
        <div style="background:#ffffff; border:2px solid #4CAF50; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#4CAF50; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #4CAF50;">
                👤 账户信息 ({total}个账户)
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                平均剩余天数: <strong>{avg_days:.1f}天</strong> | 平均积分: <strong>{avg_points:.1f}</strong> | 总流量: <strong>{total_traffic:.0f}GB</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#e8f5e9;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">积分</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">剩余天数</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">流量使用</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">剩余流量</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">使用率</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">剩余率</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
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
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.username}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{status_color}; font-weight:bold;">{status_icon}{'成功' if res.success else '失败'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#ffc107; font-weight:bold;">+{res.point}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.message or '完成签到'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#666;">{datetime.now().strftime('%H:%M')}</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.checkin_results)
        successful = sum(1 for r in self.checkin_results if r.success)
        total_points = sum(r.point for r in self.checkin_results if r.success)
        success_rate = (successful / total * 100) if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #2196F3; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#2196F3; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #2196F3;">
                📅 签到结果 ({successful}/{total})
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                成功: <strong style="color:#28a745;">{successful}次</strong> | 积分: <strong style="color:#ffc107;">+{total_points}</strong> | 成功率: <strong style="color:#17a2b8;">{success_rate:.1f}%</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#e3f2fd;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">状态</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">获得积分</th>
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

    def _build_code_section(self) -> str:
        """构建完整的礼品码兑换部分"""
        if not self.code_results:
            return ""
        
        rows = []
        for res in self.code_results:
            status_icon = "✅" if res.success else "❌"
            status_color = "#28a745" if res.success else "#dc3545"
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.username}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{status_color}; font-weight:bold;">{status_icon}{'成功' if res.success else '失败'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#20c997; font-weight:bold;">+{res.days}天</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.message or '兑换完成'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#666;">{datetime.now().strftime('%H:%M')}</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.code_results)
        successful = sum(1 for r in self.code_results if r.success)
        total_days = sum(r.days for r in self.code_results if r.success)
        success_rate = (successful / total * 100) if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #9C27B0; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#9C27B0; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #9C27B0;">
                🎁 礼品码兑换 ({successful}/{total})
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                成功: <strong style="color:#28a745;">{successful}次</strong> | 增加天数: <strong style="color:#20c997;">+{total_days}天</strong> | 成功率: <strong style="color:#17a2b8;">{success_rate:.1f}%</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#f3e5f5;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">状态</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">增加天数</th>
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

    def _build_redeem_section(self) -> str:
        """构建完整的蛋糕兑换部分"""
        if not self.redeem_results:
            return ""
        
        rows = []
        for res in self.redeem_results:
            status_icon = "✅" if res.success else "❌"
            status_color = "#28a745" if res.success else "#dc3545"
            
            rows.append(f'''
            <tr>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.username}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:{status_color}; font-weight:bold;">{status_icon}{'成功' if res.success else '失败'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#dc3545; font-weight:bold;">{res.amount}个</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:left;">{res.message or '兑换完成'}</td>
                <td style="border:1px solid #e0e0e0; padding:8px 10px; text-align:center; color:#666;">{datetime.now().strftime('%H:%M')}</td>
            </tr>
            ''')
        
        # 统计信息
        total = len(self.redeem_results)
        successful = sum(1 for r in self.redeem_results if r.success)
        total_amount = sum(r.amount for r in self.redeem_results if r.success)
        success_rate = (successful / total * 100) if total > 0 else 0
        
        return f'''
        <div style="background:#ffffff; border:2px solid #FF9800; border-radius:6px; margin-bottom:25px; overflow:hidden;">
            <div style="background:#FF9800; padding:15px 20px; color:#ffffff; font-size:16px; font-weight:bold; border-bottom:2px solid #FF9800;">
                🍰 蛋糕兑换 ({successful}/{total})
            </div>
            <div style="padding:12px 20px; background:#f9f9f9; border-bottom:1px solid #e0e0e0; font-size:13px;">
                成功: <strong style="color:#28a745;">{successful}次</strong> | 消耗蛋糕: <strong style="color:#dc3545;">{total_amount}个</strong> | 成功率: <strong style="color:#17a2b8;">{success_rate:.1f}%</strong>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#fff3e0;">
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:left; font-weight:bold;">账号</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">状态</th>
                        <th style="border:1px solid #e0e0e0; padding:10px; text-align:center; font-weight:bold;">消耗数量</th>
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
            code_section = self._build_code_section()
            redeem_section = self._build_redeem_section()
            
            # 替换占位符（确保所有值都是字符串）
            replacements = {
                "{{current_time}}": str(now),
                "{{report_id}}": str(self.report_id),
                "{{account_section}}": str(account_section),
                "{{checkin_section}}": str(checkin_section),
                "{{code_section}}": str(code_section),
                "{{redeem_section}}": str(redeem_section),
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

    def send(self, subject: str = "🎯 GLaDOS 运行报告") -> bool:
        """发送运行报告邮件"""
        if not any([self.account_infos, self.checkin_results, self.code_results, self.redeem_results]):
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
    'CheckinResult',
    'CodeResult', 
    'RedeemResult',
    'AccountInfo',
    'GladosNotifier',
]