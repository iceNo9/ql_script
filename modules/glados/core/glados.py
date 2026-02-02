import yagmail
from urllib.parse import urljoin
from functools import wraps
from typing import Callable, TypeVar, Any, Optional, List, cast
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
from htmlmin import minify
from pathlib import Path
from common.log import get_logger
from common.global_config import GlobalConfig, EmailConfig, IMAPConfig
from datetime import datetime
from typing import ParamSpec, Concatenate


from modules.glados.utils.request_client import RequestClient
from modules.glados.core.email import EmailCodeExtractor, GiftCode
from modules.glados.core.data import GladosAccountData as Account

from modules.glados.core.server import (
    GladosServer, 
    GladosAuthResult,
    GladosPointResult,
    GladosCheckinResult,
    GladosStatusResult,
    GladosCodeResult,
    GladosCakesResult,
    GladosRedeemResult
)

logger = get_logger(__name__)

P = ParamSpec('P')
R = TypeVar('R')

def require_login_typed(func: Callable[Concatenate['GladosClient', Account, P], R]
                       ) -> Callable[Concatenate['GladosClient', Account, P], Optional[R]]:
    """类型安全的登录检查装饰器"""
    @wraps(func)
    def wrapper(self: 'GladosClient', account: Account, *args: P.args, **kwargs: P.kwargs) -> Optional[R]:
        if not self._check_account_ok(account):
            if not self.login(account):
                logger.error(f"[!] 账户 {account.username} 登录失败，跳过操作")
                return None
        return func(self, account, *args, **kwargs)
    return wrapper


def require_email_client_typed(func: Callable[Concatenate['GladosClient', P], R]
                              ) -> Callable[Concatenate['GladosClient', P], Optional[R]]:
    """类型安全的邮箱客户端检查装饰器"""
    @wraps(func)
    def wrapper(self: 'GladosClient', *args: P.args, **kwargs: P.kwargs) -> Optional[R]:
        smtp = self._setup_smtp_client()
        if not smtp:
            logger.error("[!] SMTP 客户端不可用，取消发送邮件")
            return None
        return func(self, *args, **kwargs)
    return wrapper



class CheckinResult(BaseModel):
    id: str
    success: bool
    point: int
    message: str

class CodeResult(BaseModel):
    id : str
    success: bool
    days: int
    message: str

class RedeemResult(BaseModel):
    id : str
    success: bool
    amount: int
    message: str

class AccountInfo(BaseModel):
    id: str
    points: int
    left_days: int
    current_traffic: int
    total_traffic: int
    use_percent: float

class GladosClient:
    def __init__(self, rv_proxies: List[str], rv_accounts: List[Account], rv_global_config: GlobalConfig):

        self.accounts = rv_accounts
        self._global_config = rv_global_config 

        self.client = RequestClient(proxies=rv_proxies, max_retries=2)
        self.server = GladosServer(self.client)
        self.email_extractor = EmailCodeExtractor(self._global_config.email)

        # 邮件客户端
        self.smtp_client = None

        # 操作结果
        self.checkin_results = []
        self.code_results = []
        self.redeem_results = []
        self.account_results = []

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _setup_smtp_client(self) -> Optional[yagmail.SMTP]:
        """初始化并登录 SMTP 客户端"""
        if self.smtp_client:
            return self.smtp_client

        try:
            mail = self._global_config.email
            smtp = mail.smtp
            self.smtp_client = yagmail.SMTP(
                user=mail.username,
                password=mail.password,
                host=smtp.host,
                port=smtp.port,
                smtp_ssl=smtp.secure
            )
            logger.info("[+] SMTP 客户端登录成功")
            return self.smtp_client
        except Exception as e:
            logger.error(f"[!] SMTP 客户端登录失败: {e}", exc_info=True)
            self.smtp_client = None
            return None

    def _check_account_ok(self, rv_account: Account) -> bool:
        """检查登录状态"""
        if rv_account.cookies:
            self.server.update_cookies(rv_account.cookies)

        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {rv_account.username} 登录状态服务异常")
            return False

        if not result.success:
            logger.debug(f"[!] 账户 {rv_account.username} 登录状态检查失败")
            return False

        logger.debug(f"[+] 账户 {rv_account.username} 登录状态正常")
        return True
        
    def login(self, rv_account: Account) -> bool:
        """登录账号"""
        logger.debug(f"[+] 使用账户 {rv_account.username} 登录")

        # 检查cookies登录状态是否有效
        if self._check_account_ok(rv_account):
            logger.info(f"[+] 账户 {rv_account.username} cookies 登录成功")
        else:
            # 执行邮箱验证码登录
            logger.info(f"[*] 账户 {rv_account.username} cookies 登录失效，尝试邮箱验证码登录")
            result = self.server.request_authorization(rv_account.username)
            if not result or not result.success:
                logger.error(f"[!] 账户 {rv_account.username} 请求发送验证码失败")
                return False

            # 捕获验证码
            code = self.email_extractor.get_login_code(email_address=rv_account.username, max_wait_minutes=5, check_interval_seconds=10)
            if not code:
                logger.error(f"[!] 账户 {rv_account.username} 获取验证码失败")
                return False
            
            # 提交验证码登录
            success = self.server.request_login(rv_account.username, code)
            if not success:
                logger.error(f"[!] 账户 {rv_account.username} 验证码登录失败")
                return False
            
            if self._check_account_ok(rv_account):                
                logger.info(f"[+] 账户 {rv_account.username} 验证码登录成功")
                rv_account.cookies = self.server.get_cookies()
                self.server.update_cookies(rv_account.cookies)
                return True
            else:
                logger.error(f"[!] 账户 {rv_account.username} 验证码登录失败")
                return False

        return True
    
    @require_login_typed
    def _checkin(self, account: Account) -> Optional[GladosCheckinResult]:
        result = self.server.request_checkin()
        if not result:
            logger.error(f"[!] 账户 {account.id} 签到失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 签到成功")
        else:
            logger.error(f"[!] 账户 {account.id} 签到失败: {result.message}")

        return result

    def checkin(self) -> List[CheckinResult]:
        logger.info("[*] 开始执行 GLaDOS 账户签到")
        results = []

        for account in self.accounts:
            logger.info(f"[*] 账户 {account.id} 开始签到")
            ret = self._checkin(account)
            if ret:
                result = CheckinResult(
                    id=account.id,
                    success=ret.success,
                    point=ret.point,
                    message=ret.message,
                )            
                results.append(result)

        logger.info(f"[✓] 签到完成，共处理 {len(results)} 个结果")
        self.checkin_results = results
        return results
    
    @require_login_typed
    def _code(self, account: Account, code: str) -> Optional[GladosCodeResult]:
        result = self.server.request_code(code)
        if not result:
            logger.error(f"[!] 账户 {account.id} 兑换礼品码失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 兑换礼品码成功")
        else:
            logger.error(f"[!] 账户 {account.id} 兑换礼品码失败: {result.message}")

        return result
    
    def code(self) -> List[CodeResult]:
        logger.info("[*] 开始执行 GLaDOS 账户兑换礼品码")
        results = []

        # 获取有效的礼品码
        gift_codes = self.email_extractor.get_gift_codes()
        if not gift_codes:
            logger.info("[i] 未找到有效的礼品码，跳过兑换")
            return results

        # 兑换礼品码
        for gift_code in gift_codes:
            for account in self.accounts:
                if gift_code.username == account.username:
                    logger.info(f"[*] 账户 {account.id} 开始兑换礼品码")
                    ret = self._code(account, gift_code.code)
                    if ret:
                        result = CodeResult(
                            id=account.id,
                            success=ret.success,
                            days=int(gift_code.valid_day),
                            message=ret.message
                        )
                        results.append(result)
                    break
                else:
                    logger.info(f"[!] 账户 {account.id} 与礼品码不匹配，跳过兑换")
                    continue

        logger.info(f"[✓] 礼品码兑换完成，共处理 {len(results)} 个结果")
        self.code_results = results
        return results

    @require_email_client_typed
    def _redeem(self, account: Account, cake_id: int) -> Optional[GladosRedeemResult]:
        result = self.server.request_redeem(cake_id)
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取蛋糕列表成功")
        else:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败: {result.message}")

        return result
    
    @require_login_typed
    def _status(self, account: Account) -> Optional[GladosStatusResult]:
        result = self.server.request_status()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取状态失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取状态成功")
            account.leftDays = int(result.left_days)
            account.vip_level = int(result.vip)
            account.traffic = result.traffic
            account.total_traffic = self.server.get_total_traffic(account.vip_level)
        else:
            logger.error(f"[!] 账户 {account.id} 获取状态失败")

        return result
    
    @require_login_typed
    def _cake(self, account: Account) -> Optional[GladosCakesResult]:
        result = self.server.request_cakes()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取蛋糕列表成功")
        else:
            logger.error(f"[!] 账户 {account.id} 获取蛋糕列表失败")

        return result
    
    @require_login_typed
    def _point(self, account: Account) -> Optional[GladosPointResult]:
        result = self.server.request_point()
        if not result:
            logger.error(f"[!] 账户 {account.id} 获取积分列表失败, 服务异常")
            return None

        if result.success:
            logger.info(f"[+] 账户 {account.id} 获取积分列表成功")
        else:            
            logger.error(f"[!] 账户 {account.id} 获取积分列表失败")
        
        return result
            
    def cake(self) -> List[RedeemResult]:
        logger.info("[*] 开始执行 GLaDOS 蛋糕兑换")
        results = []

        # 获取账号信息,获取有效cake
        for account in self.accounts:

            status_result = self._status(account)
            if not status_result:
                continue

            if not status_result.success or not status_result.cake_count:
                continue

            # 获取蛋糕列表
            cake_result = self._cake(account)
            if cake_result and cake_result.success:
                for cake in cake_result.available:
                    ret = self._redeem(account, cake.id)
                    if ret:
                        result = RedeemResult(
                            id = account.id,
                            success = ret.success,
                            amount = cake.amount,
                            message = ret.message
                        )

                        results.append(result)

        logger.info(f"[✓] 蛋糕兑换完成，共处理 {len(results)} 个结果")
        self.redeem_results = results
        return results

    def collect_account_infos(self) -> List[AccountInfo]:
            """收集所有账户的信息"""
            logger.info("[*] 开始收集账户信息")
            account_infos = []
            
            for account in self.accounts:
                logger.info(f"[*] 获取账户 {account.id} 信息")
                status = self._status(account)
                point = self._point(account)
                
                if status and status.success and point and point.success:
                    # 转换为AccountInfo格式
                    account_info = AccountInfo(
                        id=account.id,
                        points=int(point.points),
                        left_days=account.leftDays,
                        current_traffic=account.traffic,
                        total_traffic=account.total_traffic,
                        use_percent = (
                            account.traffic / account.total_traffic
                            if account.total_traffic > 0 else 0.0
                        )
                    )
                    account_infos.append(account_info)
                    logger.info(f"[+] 账户 {account.id} 信息获取成功")
                else:
                    logger.error(f"[!] 账户 {account.id} 信息获取失败")
            
            self.account_infos = account_infos
            logger.info(f"[✓] 账户信息收集完成，共 {len(account_infos)} 个账户")
            return account_infos
        
    def _build_account_section(self) -> str:
        """构建账户信息板块HTML"""
        if not self.account_infos:
            return '<div class="section"><div class="section-title">账户信息</div><div class="no-data">暂无账户信息</div></div>'
        
        # 构建数据行
        rows = []
        for acc in self.account_infos:
            used_gb = acc.current_traffic / (1024**3)
            total_gb = acc.total_traffic / (1024**3)
            remaining_gb = total_gb - used_gb
            remaining_pct = 100 - acc.use_percent
            
            rows.append(f"""
            <tr>
                <td>{acc.id}</td>
                <td>{acc.points}</td>
                <td>{acc.left_days}</td>
                <td>{acc.expire_at or '—'}</td>
                <td>{used_gb:.2f} GB</td>
                <td>{total_gb:.2f} GB</td>
                <td>{remaining_gb:.2f} GB ({remaining_pct:.1f}%)</td>
            </tr>
            """)
        
        rows_html = ''.join(rows)
        
        # 统计信息
        total_accounts = len(self.account_infos)
        avg_points = sum(acc.points for acc in self.account_infos) / total_accounts if total_accounts > 0 else 0
        avg_days = sum(acc.left_days for acc in self.account_infos) / total_accounts if total_accounts > 0 else 0
        
        summary_html = f"""
        <div class="summary">
            <div class="summary-item">
                <div class="summary-value">{total_accounts}</div>
                <div class="summary-label">总账户数</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{avg_points:.0f}</div>
                <div class="summary-label">平均积分</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{avg_days:.1f}</div>
                <div class="summary-label">平均剩余天数</div>
            </div>
        </div>
        """
        
        return f"""
        <div class="section">
            <div class="section-title">账户信息</div>
            {summary_html}
            <table>
                <thead>
                    <tr>
                        <th>账号</th>
                        <th>积分余额</th>
                        <th>剩余天数</th>
                        <th>到期时间</th>
                        <th>已用流量</th>
                        <th>总流量</th>
                        <th>剩余流量</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    
    def _build_checkin_section(self) -> str:
        """构建签到结果板块HTML"""
        if not self.checkin_results:
            return ""
        
        rows = []
        success_count = 0
        total_points = 0
        
        for res in self.checkin_results:
            status_class = "status-success" if res.success else "status-failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            
            if res.success:
                success_count += 1
                total_points += res.point
            
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td><span class="{status_class}">{status_text}</span></td>
                <td>{res.point}</td>
                <td>{res.message}</td>
            </tr>
            """)
        
        rows_html = ''.join(rows)
        success_rate = (success_count / len(self.checkin_results) * 100) if self.checkin_results else 0
        
        summary_html = f"""
        <div class="summary">
            <div class="summary-item">
                <div class="summary-value">{len(self.checkin_results)}</div>
                <div class="summary-label">签到账户数</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_count}</div>
                <div class="summary-label">成功数量</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_rate:.1f}%</div>
                <div class="summary-label">成功率</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{total_points}</div>
                <div class="summary-label">总获得积分</div>
            </div>
        </div>
        """
        
        return f"""
        <div class="section">
            <div class="section-title checkin">签到结果</div>
            {summary_html}
            <table>
                <thead>
                    <tr>
                        <th>账号</th>
                        <th>签到状态</th>
                        <th>获得积分</th>
                        <th>详细信息</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    
    def _build_code_section(self) -> str:
        """构建礼品码结果板块HTML"""
        if not self.code_results:
            return ""
        
        rows = []
        success_count = 0
        total_days = 0
        
        for res in self.code_results:
            status_class = "status-success" if res.success else "status-failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            
            if res.success:
                success_count += 1
                total_days += res.days
            
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td><span class="{status_class}">{status_text}</span></td>
                <td>{res.days}</td>
                <td>{res.message}</td>
            </tr>
            """)
        
        rows_html = ''.join(rows)
        success_rate = (success_count / len(self.code_results) * 100) if self.code_results else 0
        
        summary_html = f"""
        <div class="summary">
            <div class="summary-item">
                <div class="summary-value">{len(self.code_results)}</div>
                <div class="summary-label">兑换账户数</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_count}</div>
                <div class="summary-label">成功数量</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_rate:.1f}%</div>
                <div class="summary-label">成功率</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{total_days}</div>
                <div class="summary-label">总获得天数</div>
            </div>
        </div>
        """
        
        return f"""
        <div class="section">
            <div class="section-title code">礼品码兑换结果</div>
            {summary_html}
            <table>
                <thead>
                    <tr>
                        <th>账号</th>
                        <th>兑换状态</th>
                        <th>获得天数</th>
                        <th>详细信息</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    
    def _build_redeem_section(self) -> str:
        """构建蛋糕兑换结果板块HTML"""
        if not self.redeem_results:
            return ""
        
        rows = []
        success_count = 0
        total_amount = 0
        
        for res in self.redeem_results:
            status_class = "status-success" if res.success else "status-failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            
            if res.success:
                success_count += 1
                total_amount += res.amount
            
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td><span class="{status_class}">{status_text}</span></td>
                <td>{res.amount}</td>
                <td>{res.message}</td>
            </tr>
            """)
        
        rows_html = ''.join(rows)
        success_rate = (success_count / len(self.redeem_results) * 100) if self.redeem_results else 0
        
        summary_html = f"""
        <div class="summary">
            <div class="summary-item">
                <div class="summary-value">{len(self.redeem_results)}</div>
                <div class="summary-label">兑换账户数</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_count}</div>
                <div class="summary-label">成功数量</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{success_rate:.1f}%</div>
                <div class="summary-label">成功率</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{total_amount}</div>
                <div class="summary-label">总获得点数</div>
            </div>
        </div>
        """
        
        return f"""
        <div class="section">
            <div class="section-title redeem">蛋糕兑换结果</div>
            {summary_html}
            <table>
                <thead>
                    <tr>
                        <th>账号</th>
                        <th>兑换状态</th>
                        <th>蛋糕点数</th>
                        <th>详细信息</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    
    def _build_email(self) -> str:
        """构建完整的邮件HTML内容"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建各个板块
        account_section = self._build_account_section()
        checkin_section = self._build_checkin_section()
        code_section = self._build_code_section()
        redeem_section = self._build_redeem_section()
        
        # 加载模板
        try:
            template_path = Path("modules/glados/templates/glados_notification.html")
            html_tpl = template_path.read_text(encoding="utf-8")
            
            # 替换占位符
            replacements = {
                "{{ current_time }}": current_time,
                "{{ account_section }}": account_section,
                "{{ checkin_section }}": checkin_section,
                "{{ code_section }}": code_section,
                "{{ redeem_section }}": redeem_section
            }
            
            html_body = html_tpl
            for placeholder, content in replacements.items():
                html_body = html_body.replace(placeholder, content)
            
            return minify(html_body, remove_empty_space=True, remove_comments=True)
            
        except Exception as e:
            logger.error(f"[!] 加载邮件模板失败: {e}", exc_info=True)
            return self._build_fallback_email(current_time)
    
    def _build_fallback_email(self, current_time: str) -> str:
        """模板加载失败时构建备用邮件"""
        sections = [
            self._build_account_section(),
            self._build_checkin_section(),
            self._build_code_section(),
            self._build_redeem_section()
        ]
        
        # 过滤空的部分
        sections = [section for section in sections if section]
        
        if not sections:
            return ""
        
        # 构建简单的HTML
        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>GLaDOS 操作结果通知</title></head>
<body style="font-family: sans-serif; padding: 20px;">
    <h2>GLaDOS 操作结果通知</h2>
    <p>报告时间：{current_time}</p>
    {''.join(sections)}
    <p style="font-size: 12px; color: #888; margin-top: 20px;">
        此邮件由系统自动发送，请勿回复。
    </p>
</body>
</html>"""
        
        return minify(html_content, remove_empty_space=True, remove_comments=True)
    
    @require_email_client_typed
    def send_result_notification(self) -> bool:
        """发送结果通知邮件"""
        logger.info("[*] 开始发送 GLaDOS 操作结果通知")
        
        email_to = self._global_config.email_to
        
        # 检查是否有数据
        has_data = any([
            self.account_infos,
            self.checkin_results,
            self.code_results,
            self.redeem_results
        ])
        
        if not has_data:
            logger.warning("[!] 没有可发送的结果数据")
            return False
        
        # 构建邮件内容
        html_body = self._build_email()
        if not html_body:
            logger.error("[!] 构建邮件内容失败")
            return False
        
        # 生成主题
        subject = "GLaDOS 运行结果报告"
        
        # 发送邮件
        try:
            if self.smtp_client:
                self.smtp_client.send(
                    to=email_to,
                    subject=subject,
                    contents=[html_body],
                )
                logger.info("[*] 发送 GLaDOS 操作结果通知成功")
            else:
                logger.error("[!] SMTP 客户端未初始化")

            return True

        except Exception as e:
            logger.error(f"[!] 发送邮件失败: {e}", exc_info=True)
            return False

        finally:
            # ⭐ 关键：主动关闭，避免 __del__
            try:
                if self.smtp_client:
                    self.smtp_client.close()
                    self.smtp_client = None
                    logger.debug("[*] SMTP 客户端已关闭")
            except Exception:
                pass
