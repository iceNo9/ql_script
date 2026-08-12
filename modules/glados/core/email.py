# modules\glados\core\email.py
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any, cast, Union
from imapclient.response_types import Envelope, Address

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError
from functools import wraps
import mailparser
from email.header import decode_header
from email.utils import parsedate_to_datetime

from utils.log import get_logger
from utils.global_config import EmailConfig

logger = get_logger(__name__)

def decode_mime_subject(value: str) -> str:
    if not value:
        return ""

    parts = decode_header(value)
    decoded = []

    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(part)

    return "".join(decoded)

class MailSummary:
    """邮件摘要（列表展示用）"""

    def __init__(
        self,
        uid: int,
        subject: str,
        sender: str,
        to: List[str],
        date: datetime,
    ):
        self.uid = uid
        self.subject = subject
        self.sender = sender
        self.to = to
        self.date = date


class MailDetail:
    """邮件详细内容"""

    def __init__(
        self,
        uid: int,
        subject: str,
        sender: str,
        to: List[str],
        date: datetime,
        text_plain: str,
        text_html: str,
        raw: bytes,
    ):
        self.uid = uid
        self.subject = subject
        self.sender = sender
        self.to = to
        self.date = date
        self.text_plain = text_plain
        self.text_html = text_html
        self.raw = raw

class GiftCode:
    def __init__(self, username: str, code: str, valid_day: str):
        self.username = username
        self.code = code
        self.valid_day = valid_day

def require_connection(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self._ensure_connection():
            raise RuntimeError("IMAP 未连接")
        return func(self, *args, **kwargs)
    return wrapper

class EmailCodeExtractor:
    """邮件验证码 / 礼品码 / 邮件读取"""

    def __init__(self, config: EmailConfig):
        self.config = config
        self.imap_client: Optional[IMAPClient] = None

        self._connect()

    def get_login_code(self, email_address: str, max_wait_minutes: int = 5, check_interval_seconds: int = 10) -> Optional[str]:
        """
        获取登录验证码（优化：先找到 '验证码' 或 'code' 关键词，再在其后匹配 5~7 位连续数字）
        """
        try:
            import time
            max_attempts = (max_wait_minutes * 60) // check_interval_seconds
            keywords = ["验证码", "code"]  # 支持多关键字

            for attempt in range(1, max_attempts + 1):
                logger.debug(f"[*] 第 {attempt}/{max_attempts} 次尝试获取验证码")

                # 获取最近1天的邮件
                summaries = self.list_mail_summaries(days=1)
                for summary in summaries:
                    # 判断date比现在早5分钟,则下一封
                    if summary.date < datetime.now() - timedelta(minutes=5):
                        continue

                    # 判断subject不包含"GLaDOS Authentication",则下一封
                    if "GLaDOS Authentication" not in summary.subject:
                        continue

                    # 判断收件人不包含email_address,则下一封
                    if email_address not in summary.to:
                        continue

                    # 获取邮件详细
                    detail = self.get_mail_detail_by_uid(summary.uid)
                    if detail and detail.text_plain:
                        text = detail.text_plain

                        for keyword in keywords:
                            keyword_pos = text.lower().find(keyword.lower())
                            if keyword_pos != -1:
                                # 取关键词之后的 50 个字符作为搜索范围
                                search_window = text[keyword_pos: keyword_pos + 50]
                                code_pattern = r'\b(\d{5,7})\b'
                                match = re.search(code_pattern, search_window)
                                if match:
                                    login_code = match.group(1)
                                    logger.debug(f"[+] 从 '{keyword}' 后提取到验证码: {login_code}")
                                    self.delete_email(summary.uid)
                                    logger.debug(f"[*] 删除邮件: {summary.subject}")
                                    return login_code

                # 如果这不是最后一次尝试，则等待
                if attempt < max_attempts:
                    logger.debug(f"[*] 等待 {check_interval_seconds} 秒后重试...")
                    time.sleep(check_interval_seconds)

            return None

        except Exception as e:
            logger.error(f"[!] 获取验证码过程中出错: {e}")
            return None

    def get_gift_codes(self) -> List[GiftCode]:
        """
        获取礼品码
        """
        gift_codes = []
        target_folder = "已兑换礼品码"

        try:
            # 获取最近7天的邮件摘要
            summaries = self.list_mail_summaries(days=7)
            for summary in summaries:
                gift_code = GiftCode("", "", "")                

                # 判断邮件主题是否包含"礼品码"和"GLaDOS"
                if "礼品码" not in summary.subject or "GLaDOS" not in summary.subject:
                    continue

                # 从邮件主题获取奖励天数,正则匹配类似于"30天礼品码"
                days_pattern = r'(\d+)天礼品码'
                match = re.search(days_pattern, summary.subject)
                if not match:
                    logger.warning(f"[!] 无法从邮件主题中提取奖励天数: {summary.subject}")
                    continue
                gift_code.valid_day = match.group(1)
                logger.debug(f"[+] 从邮件主题提取到奖励天数: {gift_code.valid_day}")

                # 获取奖励账户
                gift_code.username = summary.to[0]

                # 获取邮件详情
                detail = self.get_mail_detail_by_uid(summary.uid)
                if detail:
                    # 在text_plain中正则匹配类似"Q12JC-D7LCM-FE1OO-JNWZO"
                    code_pattern = r'\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b'
                    match = re.search(code_pattern, detail.text_html)
                    if match:
                        gift_code.code = match.group(1)
                        logger.debug(f"[+] 从邮件内容中提取到礼品码: {gift_code.code}")
                        self.move_email(summary.uid, target_folder)
                        logger.debug(f"[+] 将邮件移动到文件夹{target_folder}")                
                
                gift_codes.append(gift_code)

        except Exception as e:
            logger.error(f"[!] 获取礼品码过程中出错: {e}")

        return gift_codes
    
    @require_connection
    def delete_email(self, uid: int) -> bool:
        """
        删除邮件
        """
        try:
            if self.imap_client:
                self.imap_client.add_flags([uid], [b'\\Deleted'])
                self.imap_client.expunge()
                logger.debug(f"[+] 已删除邮件 UID={uid}")
                return True
            else:
                return False
        except Exception as e:
            logger.warning(f"[!] 删除邮件失败: {e}")
            return False
    
    @require_connection
    def move_email(self, msg_id: int, folder_name: str) -> bool:
        """
        移动邮件到指定文件夹
        """
        try:
            if self.imap_client:
                # 检查文件夹是否存在，不存在则创建
                folders = [f[2] for f in self.imap_client.list_folders()]
                if folder_name not in folders:
                    self.imap_client.create_folder(folder_name)
                    logger.info(f"[+] 创建邮箱文件夹: {folder_name}")
                
                # 移动邮件
                self.imap_client.move([msg_id], folder_name)
                logger.info(f"[+] 邮件ID {msg_id} 移动到 {folder_name}")
                return True
            else:
                return False
        except Exception as e:
            logger.warning(f"[!] 移动邮件失败: {e}")
            return False
        
    def _ensure_connection(self) -> bool:
        """
        确保 IMAP 连接和登录状态
        所有 IMAP 操作前必须调用
        """
        try:
            if not self.imap_client:
                return self._connect()

            self.imap_client.noop()
            return True

        except IMAPClientError:
            logger.info("IMAP 连接失效，尝试重连")
            return self._reconnect()

        except Exception as e:
            logger.exception(f"IMAP 状态异常: {e}")
            return False

    def _connect(self) -> bool:
        try:
            self.imap_client = IMAPClient(
                self.config.imap.host,
                port=self.config.imap.port,
                ssl=self.config.imap.secure,
            )
            self.imap_client.login(
                self.config.username,
                self.config.password,
            )
            if self.imap_client:
                if self.imap_client is not None:
                    self.imap_client.select_folder("INBOX", readonly=True)
            return True
        except Exception as e:
            logger.error(f"IMAP 连接失败: {e}")
            return False

    def _reconnect(self) -> bool:
        try:
            try:
                if self.imap_client:
                    self.imap_client.logout()
            except Exception:
                pass
            return self._connect()
        except Exception as e:
            logger.error(f"IMAP 重连失败: {e}")
            return False
        
    # ===============================
    # 邮件摘要
    # ===============================
    @require_connection
    def list_mail_summaries(self, days: int = 7) -> List[MailSummary]:
        summaries: List[MailSummary] = []

        try:
            if self.imap_client:
                self.imap_client.select_folder("INBOX", readonly=True)
                since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
                search_criteria = f"SINCE {since_date}"
                
                # search 方法返回 List[int]
                uids: List[int] = self.imap_client.search(search_criteria)
                
                if not uids:
                    return summaries

                uids = sorted(uids, reverse=True)
                
                # fetch_data 的类型: Dict[int, Dict[bytes, Any]]
                fetch_data: Dict[int, Dict[bytes, Any]] = self.imap_client.fetch(uids, ["ENVELOPE"])

                for uid in uids:
                    # 明确获取 envelope 数据
                    message_data: Dict[bytes, Any] = fetch_data.get(uid, {})
                    env_data: Any = message_data.get(b"ENVELOPE")
                    
                    if not env_data:
                        continue

                    # 类型断言
                    env: Envelope = cast(Envelope, env_data)

                    # subject - 处理可能的 None
                    raw_subject: Union[bytes, None] = env.subject
                    subject: str = ""
                    if raw_subject:
                        try:
                            decoded_subject: str = raw_subject.decode(errors="ignore")
                            subject = decode_mime_subject(decoded_subject)
                        except Exception as e:
                            logger.debug(f"Failed to decode subject for UID {uid}: {e}")
                            subject = ""

                    # from - 更安全地处理
                    sender: str = ""
                    if env.from_ and isinstance(env.from_, tuple) and len(env.from_) > 0:
                        frm: Address = env.from_[0]
                        if isinstance(frm, Address) and frm.mailbox and frm.host:
                            try:
                                mailbox_bytes: bytes = frm.mailbox
                                host_bytes: bytes = frm.host
                                mailbox_str: str = mailbox_bytes.decode(errors="ignore")
                                host_str: str = host_bytes.decode(errors="ignore")
                                sender = f"{mailbox_str}@{host_str}"
                            except Exception as e:
                                logger.debug(f"Failed to decode sender for UID {uid}: {e}")

                    # to
                    to_list: List[str] = []
                    if env.to and isinstance(env.to, tuple):
                        for addr in env.to:
                            if isinstance(addr, Address) and addr.mailbox and addr.host:
                                try:
                                    mailbox_str: str = addr.mailbox.decode(errors="ignore")
                                    host_str: str = addr.host.decode(errors="ignore")
                                    to_list.append(f"{mailbox_str}@{host_str}")
                                except Exception as e:
                                    logger.debug(f"Failed to decode recipient for UID {uid}: {e}")

                    # date - 处理可能的 None 或不存在的属性
                    date: datetime = datetime.now()
                    try:
                        # 检查是否有 date 属性并且不是 None
                        if hasattr(env, 'date') and env.date is not None:
                            # env.date 可能是 datetime 对象或其他格式
                            if isinstance(env.date, datetime):
                                date = env.date
                            else:
                                # 尝试转换
                                try:
                                    date = datetime.fromtimestamp(env.date)
                                except (TypeError, ValueError):
                                    pass
                    except Exception as e:
                        logger.debug(f"Failed to get date for UID {uid}: {e}")

                    summaries.append(
                        MailSummary(
                            uid=uid,
                            subject=subject,
                            sender=sender,
                            to=to_list,
                            date=date,
                        )
                    )

        except Exception as e:
            logger.error(f"获取邮件摘要失败: {e}", exc_info=True)
            return summaries
        
        return summaries

                
    # ===============================
    # 邮件详细列表
    # ===============================
    @require_connection
    def list_mail_details(self, days: int = 7) -> List[MailDetail]:
        details: List[MailDetail] = []

        try:
            if self.imap_client:
                self.imap_client.select_folder("INBOX", readonly=True)
                since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
                
                # 修复搜索参数 - 使用字符串格式
                search_criteria: str = f"SINCE {since_date}"
                uids: List[int] = self.imap_client.search(search_criteria)
                
                if not uids:
                    return details

                uids = sorted(uids, reverse=True)
                
                # fetch_data 的类型: Dict[int, Dict[bytes, Any]]
                fetch_data: Dict[int, Dict[bytes, Any]] = self.imap_client.fetch(uids, ["RFC822", "ENVELOPE"])

                for uid in uids:
                    message_data: Dict[bytes, Any] = fetch_data.get(uid, {})
                    
                    # 获取原始邮件数据和 envelope
                    raw_email: Optional[bytes] = message_data.get(b"RFC822")
                    env_data: Any = message_data.get(b"ENVELOPE")
                    
                    if not raw_email or not env_data:
                        continue

                    # 解析邮件
                    mail = mailparser.parse_from_bytes(raw_email)
                    
                    # 主题
                    subject: str = ""
                    if mail.subject:
                        if isinstance(mail.subject, list):
                            subject = "".join(mail.subject) if mail.subject else ""
                        else:
                            subject = str(mail.subject)
                    
                    # 发件人
                    sender: str = ""
                    if mail.from_ and len(mail.from_) > 0:
                        # mail.from_ 是列表，每个元素可能是元组 (name, address) 或字符串
                        from_info = mail.from_[0]
                        if isinstance(from_info, tuple) and len(from_info) >= 2:
                            # 元组格式: (name, address)
                            sender = from_info[1] or ""
                        elif isinstance(from_info, str):
                            sender = from_info
                        elif hasattr(from_info, 'email'):
                            # 可能是 MailAddress 对象
                            # 兼容性处理：如果 from_info 不是 tuple 或 str，尝试获取 email 属性，否则忽略
                            try:
                                sender = getattr(from_info, "email", "") or ""
                            except Exception:
                                sender = ""
                    
                    # 收件人列表
                    to_list: List[str] = []
                    if mail.to:
                        for recipient in mail.to:
                            if isinstance(recipient, tuple) and len(recipient) >= 2:
                                # 元组格式: (name, address)
                                email_address = recipient[1] if recipient[1] else ""
                                if email_address:
                                    to_list.append(str(email_address))
                            elif isinstance(recipient, str):
                                to_list.append(recipient)
                            elif not isinstance(recipient, tuple) and hasattr(recipient, 'email') and recipient.email:
                                # MailAddress 对象
                                to_list.append(str(recipient.email))
                    # 确保 to_list 只包含字符串
                    to_list = [str(addr) for addr in to_list if isinstance(addr, str)]
                    
                    # 日期
                    date: datetime = datetime.now()
                    if mail.date:
                        if isinstance(mail.date, datetime):
                            date = mail.date
                        else:
                            # 尝试转换字符串日期
                            try:
                                date = parsedate_to_datetime(str(mail.date))
                            except Exception:
                                logger.debug(f"Failed to parse date for UID {uid}: {mail.date}")
                    
                    # 纯文本内容
                    text_plain: str = ""
                    if mail.text_plain and isinstance(mail.text_plain, list):
                        # 合并所有纯文本部分
                        text_parts: List[str] = []
                        for part in mail.text_plain:
                            if isinstance(part, str):
                                text_parts.append(part)
                        text_plain = "".join(text_parts)
                    
                    # HTML 内容
                    text_html: str = ""
                    if mail.text_html and isinstance(mail.text_html, list):
                        # 合并所有 HTML 部分
                        html_parts: List[str] = []
                        for part in mail.text_html:
                            if isinstance(part, str):
                                html_parts.append(part)
                        text_html = "".join(html_parts)
                    
                    details.append(MailDetail(
                        uid=uid,
                        subject=subject,
                        sender=sender,
                        to=to_list,
                        date=date,
                        text_plain=text_plain,
                        text_html=text_html,
                        raw=raw_email
                    ))

        except Exception as e:
            logger.error(f"获取邮件详情失败: {e}", exc_info=True)

        return details

    # ===============================
    # 根据 UID 获取单封邮件详情
    # ===============================
    @require_connection
    def get_mail_detail_by_uid(self, uid: int) -> Optional[MailDetail]:
        try:
            if self.imap_client:
                self.imap_client.select_folder("INBOX", readonly=True)
                fetch_data = self.imap_client.fetch([uid], ["RFC822", "ENVELOPE"])
                if uid not in fetch_data:
                    return None

                raw_email = fetch_data[uid].get(b"RFC822")
                if not isinstance(raw_email, bytes):
                    logger.warning(f"邮件 UID={uid} 的原始内容不是 bytes，已用空字节替代")
                    raw_email_bytes = b""
                else:
                    raw_email_bytes = raw_email
                mail = mailparser.parse_from_bytes(raw_email_bytes)
                # Ensure subject is always a string
                subject = ""
                if mail.subject:
                    if isinstance(mail.subject, list):
                        subject = "".join(str(s) for s in mail.subject if s)
                    else:
                        subject = str(mail.subject)
                sender = mail.from_[0][1] if mail.from_ and mail.from_[0][1] else ""
                to_list = [t[1] if isinstance(t, tuple) and len(t) == 2 else t for t in (mail.to or [])]
                # Ensure all elements in to_list are strings
                to_list = [str(addr) for addr in to_list if isinstance(addr, str) or (isinstance(addr, tuple) and len(addr) == 2 and isinstance(addr[1], str))]
                date = mail.date or datetime.now()
                text_plain = "".join(mail.text_plain) if mail.text_plain else ""
                text_html = "".join(mail.text_html) if mail.text_html else ""

                return MailDetail(
                    uid=uid,
                    subject=subject,
                    sender=sender,
                    to=to_list,
                    date=date,
                    text_plain=text_plain,
                    text_html=text_html,
                    raw=raw_email_bytes
                )
            else:
                return None

        except Exception as e:
            logger.error(f"获取邮件 UID={uid} 失败: {e}", exc_info=True)
            return None

