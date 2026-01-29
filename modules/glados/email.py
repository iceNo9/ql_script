# modules/glados/email_extractor.py
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError
from functools import wraps
import mailparser
from email.header import decode_header
from email.utils import parsedate_to_datetime

from common.log import get_logger
from common.global_config import EmailConfig

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
        获取登录验证码
        """
        try:
            max_attempts = (max_wait_minutes * 60) // check_interval_seconds
            attempts = 0
            login_code = None

            while attempts < max_attempts:
                attempts += 1
                logger.debug(f"[*] 第 {attempts}/{max_attempts} 次尝试获取验证码")

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
                    if detail:
                        # 在text_plain中正则匹配连续6个数字
                        code_pattern = r'\b(\d{6})\b'
                        match = re.search(code_pattern, detail.text_plain)
                        if match:
                            login_code = match.group(1)
                            logger.debug(f"[+] 从纯文本提取到验证码: {login_code}")
                            break

            return login_code

        except Exception as e:
            logger.error(f"[!] 获取验证码过程中出错: {e}")
            return None

    def get_gift_codes(self) -> List[GiftCode]:
        """
        获取礼品码
        """
        gift_codes = []

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
                    match = re.search(code_pattern, detail.text_plain)
                    if match:
                        gift_code.code = match.group(1)
                        logger.debug(f"[+] 从邮件内容中提取到礼品码: {gift_code.code}")

                
                
                gift_codes.append(gift_code)

        except Exception as e:
            logger.error(f"[!] 获取礼品码过程中出错: {e}")

        return gift_codes
    
    def delete_email(self, uid: int) -> bool:
        """
        删除邮件
        """
        try:
            self.imap_client.add_flags([uid], [b'\\Deleted'])
            self.imap_client.expunge()
            logger.debug(f"[+] 已删除邮件 UID={uid}")
            return True
        except Exception as e:
            logger.warning(f"[!] 删除邮件失败: {e}")
            return False
    
    def move_email(self, msg_id: int, folder_name: str) -> bool:
        """
        移动邮件到指定文件夹
        """
        try:
            # 检查文件夹是否存在，不存在则创建
            folders = [f[2] for f in self.imap_client.list_folders()]
            if folder_name not in folders:
                self.imap_client.create_folder(folder_name)
                logger.info(f"[+] 创建邮箱文件夹: {folder_name}")
            
            # 移动邮件
            self.imap_client.move([msg_id], folder_name)
            logger.info(f"[+] 邮件ID {msg_id} 移动到 {folder_name}")
            return True
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
            self.imap_client.select_folder("INBOX", readonly=True)
            since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            uids = self.imap_client.search(["SINCE", since_date])
            if not uids:
                return summaries

            uids = sorted(uids, reverse=True)
            fetch_data = self.imap_client.fetch(uids, ["ENVELOPE"])

            for uid in uids:
                env = fetch_data.get(uid, {}).get(b"ENVELOPE")
                if not env:
                    continue

                # subject
                raw_subject = env.subject.decode(errors="ignore") if env.subject else ""
                subject = decode_mime_subject(raw_subject)

                # from
                sender = ""
                if env.from_:
                    frm = env.from_[0]
                    if frm.mailbox and frm.host:
                        sender = f"{frm.mailbox.decode()}@{frm.host.decode()}"

                # to
                to_list: List[str] = []
                if env.to:
                    for addr in env.to:
                        if addr.mailbox and addr.host:
                            to_list.append(
                                f"{addr.mailbox.decode()}@{addr.host.decode()}"
                            )

                date = env.date or datetime.now()

                summaries.append(
                    MailSummary(
                        uid=uid,
                        subject=subject,
                        sender=sender,
                        to=to_list,
                        date=date,
                    )
                )

            return summaries

        except Exception as e:
            logger.error(f"获取邮件摘要失败: {e}", exc_info=True)
            return summaries

                
    # ===============================
    # 邮件详细列表
    # ===============================
    @require_connection
    def list_mail_details(self, days: int = 7) -> List[MailDetail]:
        details: List[MailDetail] = []

        try:
            self.imap_client.select_folder("INBOX", readonly=True)
            since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            uids = self.imap_client.search(["SINCE", since_date])
            if not uids:
                return details

            uids = sorted(uids, reverse=True)
            fetch_data = self.imap_client.fetch(uids, ["RFC822", "ENVELOPE"])

            for uid in uids:
                raw_email = fetch_data[uid].get(b"RFC822")
                env = fetch_data[uid].get(b"ENVELOPE")
                if not raw_email or not env:
                    continue

                mail = mailparser.parse_from_bytes(raw_email)
                subject = mail.subject or ""
                sender = ""
                if mail.from_:
                    sender = mail.from_[0][1] if mail.from_[0][1] else ""
                to_list = [t[1] if isinstance(t, tuple) and len(t) == 2 else t for t in (mail.to or [])]
                date = mail.date or datetime.now()
                text_plain = "".join(mail.text_plain) if mail.text_plain else ""
                text_html = "".join(mail.text_html) if mail.text_html else ""

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

            return details

        except Exception as e:
            logger.error(f"获取邮件详情失败: {e}", exc_info=True)
            return details

    # ===============================
    # 根据 UID 获取单封邮件详情
    # ===============================
    @require_connection
    def get_mail_detail_by_uid(self, uid: int) -> Optional[MailDetail]:
        try:
            self.imap_client.select_folder("INBOX", readonly=True)
            fetch_data = self.imap_client.fetch([uid], ["RFC822", "ENVELOPE"])
            if uid not in fetch_data:
                return None

            raw_email = fetch_data[uid].get(b"RFC822")
            mail = mailparser.parse_from_bytes(raw_email)
            subject = mail.subject or ""
            sender = mail.from_[0][1] if mail.from_ and mail.from_[0][1] else ""
            to_list = [t[1] if isinstance(t, tuple) and len(t) == 2 else t for t in (mail.to or [])]
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
                raw=raw_email
            )

        except Exception as e:
            logger.error(f"获取邮件 UID={uid} 失败: {e}", exc_info=True)
            return None

