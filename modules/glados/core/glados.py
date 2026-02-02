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

        # 操作结果
        self.checkin_results = []
        self.code_results = []
        self.redeem_results = []
        self.account_infos = []

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _check_account_ok(self, rv_account: Account) -> bool:
        """检查登录状态"""
        if rv_account.cookies:
            self.server.update_cookies(rv_account.cookies)
        else:
            self.server.clear_cookies()

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
            
            logger.info(f"[+] 账户 {rv_account.username} 验证码登录成功")
            rv_account.cookies = self.server.get_cookies()
            self.server.update_cookies(rv_account.cookies)

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

    @require_login_typed
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

                account.balance = point.points
                
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

    def get_notifier(self) -> 'GladosNotifier':
        """获取通知器实例"""
        # 初始化 SMTP 客户端
        try:
            yagmail.sender.SMTP.__del__ = lambda self: None
            mail = self._global_config.email
            smtp = mail.smtp
            smtp_client = yagmail.SMTP(
                user=mail.username,
                password=mail.password,
                host=smtp.host,
                port=smtp.port,
                smtp_ssl=smtp.secure
            )
            logger.info("[+] SMTP 客户端登录成功")
            
            # 创建通知器
            return GladosNotifier(
                smtp_client=smtp_client,
                email_to=self._global_config.email_to,
                template_path=Path("modules/glados/templates/glados_notification.html"),
                checkin_results=self.checkin_results,
                code_results=self.code_results,
                redeem_results=self.redeem_results,
                account_infos=self.account_infos
            )
        except Exception as e:
            logger.error(f"[!] 创建通知器失败: {e}", exc_info=True)
            raise


# -------------------------------
# 独立通知类
# -------------------------------
class GladosNotifier:
    def __init__(
        self,
        smtp_client: yagmail.SMTP,
        email_to: List[str],
        template_path: Optional[Path] = None,
        checkin_results: Optional[List['CheckinResult']] = None,
        code_results: Optional[List['CodeResult']] = None,
        redeem_results: Optional[List['RedeemResult']] = None,
        account_infos: Optional[List['AccountInfo']] = None,
    ):
        self.smtp_client = smtp_client
        self.email_to = email_to
        self.template_path = template_path
        self.checkin_results = checkin_results or []
        self.code_results = code_results or []
        self.redeem_results = redeem_results or []
        self.account_infos = account_infos or []

    # ----------------------------
    # 构建各个区域 HTML
    # ----------------------------
    def _build_account_section(self) -> str:
        if not self.account_infos:
            return '<div class="section"><h3>账户信息</h3><p>暂无账户信息</p></div>'
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
                <td>{used_gb:.2f} GB</td>
                <td>{total_gb:.2f} GB</td>
                <td>{remaining_gb:.2f} GB</td>
                <td>{remaining_pct:.1f}%</td>
            </tr>
            """)
        return f"""
        <div class="section">
            <h3>账户信息</h3>
            <table>
                <thead>
                    <tr>
                        <th>账号</th><th>积分余额</th><th>剩余天数</th>
                        <th>已用流量</th><th>总流量</th><th>剩余流量</th><th>剩余百分比</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """

    def _build_checkin_section(self) -> str:
        if not self.checkin_results:
            return ""
        rows = []
        for res in self.checkin_results:
            status_class = "success" if res.success else "failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{res.point}</td>
                <td>{res.message}</td>
            </tr>
            """)
        return f"""
        <div class="section">
            <h3>签到结果</h3>
            <table>
                <thead>
                    <tr><th>账号</th><th>状态</th><th>积分</th><th>说明</th></tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """

    def _build_code_section(self) -> str:
        if not self.code_results:
            return ""
        rows = []
        for res in self.code_results:
            status_class = "success" if res.success else "failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{res.days}</td>
                <td>{res.message}</td>
            </tr>
            """)
        return f"""
        <div class="section">
            <h3>礼品码兑换结果</h3>
            <table>
                <thead>
                    <tr><th>账号</th><th>状态</th><th>天数</th><th>说明</th></tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """

    def _build_redeem_section(self) -> str:
        if not self.redeem_results:
            return ""
        rows = []
        for res in self.redeem_results:
            status_class = "success" if res.success else "failed"
            status_text = "✓ 成功" if res.success else "✗ 失败"
            rows.append(f"""
            <tr>
                <td>{res.id}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{res.amount}</td>
                <td>{res.message}</td>
            </tr>
            """)
        return f"""
        <div class="section">
            <h3>蛋糕兑换结果</h3>
            <table>
                <thead>
                    <tr><th>账号</th><th>状态</th><th>点数</th><th>说明</th></tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """

    # ----------------------------
    # 构建完整邮件
    # ----------------------------
    def _build_email_body(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 如果有模板文件，则读取并替换占位符
        if self.template_path and self.template_path.exists():
            try:
                html_tpl = self.template_path.read_text(encoding="utf-8")
                replacements = {
                    "{{current_time}}": now,
                    "{{account_section}}": self._build_account_section(),
                    "{{checkin_section}}": self._build_checkin_section(),
                    "{{code_section}}": self._build_code_section(),
                    "{{redeem_section}}": self._build_redeem_section()
                }
                for k, v in replacements.items():
                    html_tpl = html_tpl.replace(k, v)
                return minify(html_tpl, remove_empty_space=True, remove_comments=True)
            except Exception as e:
                logger.error(f"[!] 读取模板失败，将使用内置 HTML：{e}", exc_info=True)

        # 内置备用 HTML
        # 内置备用 HTML（美化版）
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>GLaDOS 运行结果通知</title>
            <style>
                body {{
                    font-family: 'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
                    background:#f6f8fa;
                    padding:20px;
                    color:#333;
                }}
                h2 {{
                    text-align:center;
                    color:#222;
                    margin-bottom:10px;
                }}
                .section {{
                    background:#fff;
                    border-radius:8px;
                    padding:15px 20px;
                    margin-bottom:30px;
                    box-shadow: 0 3px 10px rgba(0,0,0,0.08);
                }}
                .section h3 {{
                    background:#4CAF50;
                    color:#fff;
                    padding:8px 12px;
                    border-radius:5px;
                    margin-top:0;
                }}
                table {{
                    width:100%;
                    border-collapse: collapse;
                    margin-top:10px;
                    table-layout:auto;
                }}
                th, td {{
                    border:1px solid #ddd;
                    padding:10px 12px;
                    text-align:center;
                    word-break:break-word;
                }}
                th {{
                    background:#4CAF50;
                    color:#fff;
                }}
                tr:nth-child(even) {{ background:#f9f9f9; }}
                .success {{ color:#4CAF50; font-weight:bold; }}
                .failed {{ color:#F44336; font-weight:bold; }}
                p.time {{
                    text-align:center;
                    color:#555;
                    margin-bottom:15px;
                }}
                p.footer {{
                    text-align:center;
                    font-size:12px;
                    color:#888;
                    margin-top:20px;
                }}
            </style>
        </head>
        <body>
            <h2>GLaDOS 运行结果通知</h2>
            <p class="time">报告时间：{now}</p>
            {self._build_account_section()}
            {self._build_checkin_section()}
            {self._build_code_section()}
            {self._build_redeem_section()}
            <p class="footer">此邮件由系统自动发送，请勿回复。</p>
        </body>
        </html>
        """
        return minify(html, remove_empty_space=True, remove_comments=True)

    # ----------------------------
    # 发送邮件
    # ----------------------------
    def send(self, subject: str = "GLaDOS 运行结果通知") -> bool:
        if not any([self.account_infos, self.checkin_results, self.code_results, self.redeem_results]):
            logger.warning("[!] 没有可发送的数据")
            return False
        try:
            html_body = self._build_email_body()
            self.smtp_client.send(to=self.email_to, subject=subject, contents=[html_body])
            logger.info("[+] GLaDOS 操作结果通知邮件发送成功")
            self.smtp_client.close()
            return True
        except Exception as e:
            logger.error(f"[!] 邮件发送失败: {e}", exc_info=True)
            return False