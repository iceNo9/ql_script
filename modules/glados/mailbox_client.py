# mailbox_client.py
import imaplib
import email
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict
import datetime
from bs4 import BeautifulSoup
from .config import Config
from common.logger import logger
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

class MailBoxClient:
    """IMAP 邮箱客户端（支持 163/126/qq/gmail），配置从 config.yaml 读取。"""

    # 配置收信和发信服务器 + 端口 + SSL/TLS
    DEFAULT_SERVERS = {
        "163": {
            "imap": {"host": "imap.163.com", "port": 993, "ssl": True},
            "smtp": {"host": "smtp.163.com", "port": 465, "ssl": True},
        },
        "126": {
            "imap": {"host": "imap.126.com", "port": 993, "ssl": True},
            "smtp": {"host": "smtp.126.com", "port": 465, "ssl": True},
        },
        "qq": {
            "imap": {"host": "imap.qq.com", "port": 993, "ssl": True},
            "smtp": {"host": "smtp.qq.com", "port": 465, "ssl": True},
        },
        "gmail": {
            "imap": {"host": "imap.gmail.com", "port": 993, "ssl": True},
            "smtp": {"host": "smtp.gmail.com", "port": 465, "ssl": True},
        },
    }

    def __init__(self, email_addr: str, password: str, provider: str = "qq", ssl: bool = True):
        self.email_addr = email_addr
        self.password = password
        self.provider = provider.lower()

        # IMAP 配置
        imap_cfg = self.DEFAULT_SERVERS[self.provider]["imap"]
        self.imap_host = imap_cfg["host"]
        self.imap_port = imap_cfg["port"]
        self.imap_ssl = imap_cfg["ssl"]
        
        # SMTP 配置
        smtp_cfg = self.DEFAULT_SERVERS[self.provider]["smtp"]
        self.smtp_host = smtp_cfg["host"]
        self.smtp_port = smtp_cfg["port"]
        self.smtp_ssl = smtp_cfg["ssl"]

        self.conn: Optional[imaplib.IMAP4] = None

    # ---------------- 配置加载 ----------------
    @staticmethod
    def from_config(path: str = "config.yaml"):
        """从 config.yaml 创建客户端实例"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"config 文件未找到: {path}")
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        email_cfg = cfg.get("email", {})
        provider = email_cfg.get("provider", "qq")
        address = email_cfg.get("address")
        password = email_cfg.get("password")
        ssl = bool(email_cfg.get("ssl", True))

        if not address or not password:
            raise ValueError("config.yaml 中 email.address 与 email.password 必须配置")

        return MailBoxClient(email_addr=address, password=password, provider=provider, ssl=ssl)

    # ---------------- 登录 / 登出 ----------------
    def login(self):
        try:
            if self.imap_ssl:
                self.conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            else:
                self.conn = imaplib.IMAP4(self.imap_host, self.imap_port)

            typ, data = self.conn.login(self.email_addr, self.password)
            if typ != "OK":
                raise Exception(f"登录失败: {data}")

            # 尝试发送 ID 命令让服务器认为是常见客户端（部分服务器可能不支持）
            try:
                self.conn._simple_command('ID', '("name" "Thunderbird" "version" "102.0")')
            except Exception:
                pass

            # 强制 select INBOX，并检查返回值
            typ, data = self.conn.select("INBOX")
            if typ != "OK":
                raise Exception(f"选择邮箱失败: {data}")

            logger.info(f"[+] 登录成功并已选择 INBOX: {self.email_addr} ({self.provider})")

        except imaplib.IMAP4.error as e:
            raise Exception(f"[!] IMAP异常: {e}")


    def logout(self):
        if self.conn:
            try:
                self.conn.logout()
                logger.info("[+] 已登出邮箱")
            except Exception:
                pass
            self.conn = None

    # ---------------- 内部工具 ----------------
    def _ensure_selected(self):
        """确保当前连接处于 SELECTED 状态，否则尝试 select INBOX"""
        if not self.conn:
            raise Exception("请先调用 login()")
        state = getattr(self.conn, "state", None)
        if state != "SELECTED":
            typ, data = self.conn.select("INBOX")
            if typ != "OK":
                raise Exception(f"选择邮箱失败(ensure_selected): {data}")

    def _decode_header(self, hdr):
        if not hdr:
            return ""
        parts = decode_header(hdr)
        decoded = ""
        for part, enc in parts:
            if isinstance(part, bytes):
                try:
                    decoded += part.decode(enc or "utf-8", errors="ignore")
                except Exception:
                    decoded += part.decode("utf-8", errors="ignore")
            else:
                decoded += part
        return decoded

    def _extract_body(self, msg) -> str:
        """提取邮件正文（支持 text/plain + text/html）"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ["text/plain", "text/html"]:
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        raw = part.get_payload(decode=True)
                        if raw is None:
                            continue
                        text = raw.decode(charset, errors="ignore")
                        if ctype == "text/html":
                            text = BeautifulSoup(text, "html.parser").get_text(separator="\n")
                        if text.strip():
                            body = text
                            break
                    except Exception:
                        continue
        else:
            charset = msg.get_content_charset() or "utf-8"
            raw = msg.get_payload(decode=True) or b""
            text = raw.decode(charset, errors="ignore")
            body = BeautifulSoup(text, "html.parser").get_text(separator="\n")
        return body

    # ---------------- 核心功能 ----------------
    def list_recent_emails(self, limit: int = 5) -> List[Dict]:
        """返回最近 limit 封邮件的摘要（倒序：最近的在最前）"""
        self._ensure_selected()
        result, data = self.conn.search(None, "ALL")
        if result != "OK" or not data[0]:
            logger.info("[-] 没有邮件")
            return []

        ids = data[0].split()[-limit:]
        emails = []
        for msg_id in reversed(ids):  # 最近的先返回
            res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
            if res != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = self._decode_header(msg.get("Subject", ""))
            from_ = self._decode_header(msg.get("From", ""))
            date_str = msg.get("Date", "")
            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = None
            emails.append({
                "subject": subject,
                "from": from_,
                "date": date,
            })
        return emails

    def get_latest_email(
        self,
        from_filter: Optional[str] = None,
        subject_filter: Optional[str] = None,
        within_minutes: Optional[int] = None,
        unread_only: bool = False,
    ) -> Optional[str]:
        """获取最新邮件正文，可按发件人/主题/时间过滤"""
        self._ensure_selected()
        search_criteria = []
        search_criteria.append("UNSEEN" if unread_only else "ALL")
        if from_filter:
            search_criteria.append(f'FROM "{from_filter}"')
        criteria = " ".join(search_criteria)

        result, data = self.conn.search(None, criteria)
        if result != "OK" or not data[0]:
            # 没有匹配的邮件
            return None

        ids = data[0].split()
        for msg_id in reversed(ids):
            res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
            if res != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            # 时间过滤
            if within_minutes:
                date_str = msg.get("Date", "")
                try:
                    date = parsedate_to_datetime(date_str)
                    if date:
                        # normalize to UTC for comparison
                        now = datetime.datetime.now(datetime.timezone.utc)
                        delta = (now - date).total_seconds()
                        if delta > within_minutes * 60:
                            continue
                except Exception:
                    pass

            subject = self._decode_header(msg.get("Subject", ""))
            if subject_filter and subject_filter not in subject:
                continue

            body = self._extract_body(msg)
            if body:
                return body

        return None

    def get_verification_code(
        self,
        within_minutes: int,
        sender_match: str,
        pattern: str = r"\b\d{6}\b",
        delete_after_find: bool = False,
        trash_mailbox: str = "Trash",
    ) -> Optional[str]:
        """
        在最近 within_minutes 分钟内，定位包含 sender_match 的邮件，并从邮件正文提取验证码。
        如果 delete_after_find 为 True，会尝试把该邮件移动到 trash_mailbox（先 COPY 再标记为 Deleted 并 EXPUNGE）。
        """
        self._ensure_selected()  # 确保已选中一个 mailbox（且最好是 read-write）

        # 搜索最近的邮件（使用 ALL，然后手动时间过滤）
        result, data = self.conn.search(None, "UNSEEN")
        if result != "OK" or not data or not data[0]:
            return None

        ids = data[0].split()
        for msg_id in reversed(ids):  # 最近邮件先检查
            try:
                res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
            except Exception:
                continue
            if res != "OK" or not msg_data or not msg_data[0]:
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            # 时间过滤
            date_str = msg.get("Date", "")
            try:
                date = parsedate_to_datetime(date_str)
                if date:
                    # 统一比较到 UTC
                    now = datetime.datetime.now(datetime.timezone.utc)
                    # 如果邮件时间没有 timezone，parsedate_to_datetime 可能返回 naive，先安全处理
                    if date.tzinfo is None:
                        # 假设服务器返回本地时间 -> 这里无法可靠判断，跳过时间过滤或按你的环境处理
                        pass
                    else:
                        if (now - date).total_seconds() > within_minutes * 60:
                            break  # 更旧的邮件都不需要检查了
            except Exception:
                # 无法解析时间则继续检查内容
                pass

            # 检查 sender_match 是否出现在 From header 或 邮件正文中
            from_hdr = self._decode_header(msg.get("From", ""))
            body = self._extract_body(msg)
            if sender_match not in from_hdr and sender_match not in (body or ""):
                continue

            # 找到可能的邮件，尝试提取验证码
            match = re.search(pattern, body or "")
            if match:
                code = match.group(0)

                # 如果需要删除 / 移动邮件
                if delete_after_find:
                    try:
                        # 首选：尝试 COPY 到 trash_mailbox（有些服务器的回收箱名不是 "Trash"，你可以改）
                        copy_res, copy_data = self.conn.copy(msg_id, trash_mailbox)
                        if copy_res != "OK":
                            # 如果 COPY 失败，仍尝试直接标记删除（谨慎）
                            pass

                        # 标记为 Deleted
                        # 使用 sequence number 或 msg_id（从 search 得到）都可以，这里沿用 msg_id
                        store_res, store_data = self.conn.store(msg_id, "+FLAGS", r"(\Deleted)")
                        if store_res == "OK":
                            # 执行 expunge —— 注意：这会清理该 mailbox 中所有 \Deleted 标记的邮件
                            try:
                                self.conn.expunge()
                            except Exception:
                                # 某些 IMAP 服务器可能不支持 expunge 或行为不同，忽略异常
                                pass
                        else:
                            # 标记失败，可以记录日志或重试
                            pass
                    except Exception:
                        # 删除/移动过程中出现错误，不影响返回验证码
                        pass

                return code

        return None
    
    def send_email(
    self,
    to_addr: str,
    subject: str,
    body: str,
    attachment_path: Optional[str] = None,
    html: bool = False
) -> bool:
        """发送邮件（支持 HTML 格式）"""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.email_addr
            msg["To"] = to_addr
            msg["Subject"] = subject

            # 如果 html=True，则发送 HTML，否则发送纯文本
            mime_type = "html" if html else "plain"
            msg.attach(MIMEText(body, mime_type, "utf-8"))

            # 附件处理
            if attachment_path:
                with open(attachment_path, "rb") as f:
                    attachment = MIMEApplication(f.read(), Name=attachment_path.split("/")[-1])
                    attachment["Content-Disposition"] = f"attachment; filename={attachment_path.split('/')[-1]}"
                    msg.attach(attachment)

            # 发送邮件
            if self.smtp_ssl:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    server.login(self.email_addr, self.password)
                    server.sendmail(self.email_addr, to_addr, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    server.login(self.email_addr, self.password)
                    server.sendmail(self.email_addr, to_addr, msg.as_string())

            logger.info(f"[+] 邮件发送成功: {subject}")
            return True

        except smtplib.SMTPResponseException as e:
            if e.smtp_code == -1 and e.smtp_error == b'\x00\x00\x00':
                logger.warning(f"[!] QQ 邮箱特殊返回码 (-1, b'\\x00\\x00\\x00')，邮件可能已成功发送: {subject}")
                return True
            logger.error(f"[!] SMTP返回异常: {e.smtp_code}, {e.smtp_error}")
            return False

        except Exception as e:
            if "b'\\x00\\x00\\x00'" in str(e) or "[-1]" in str(e):
                logger.warning(f"[!] 捕获到非标准返回 (-1, b'\\x00\\x00\\x00')，邮件可能已成功发送: {subject}")
                return True
            logger.error(f"[!] 邮件发送失败: {e}")
            return False





# ---------------- 测试 / CLI 使用示例 ----------------
if __name__ == "__main__":
    cfg = Config("config.yaml")
    email_cfg = cfg.email

    client = MailBoxClient(
        email_addr=email_cfg["address"],
        password=email_cfg["password"],
        provider=email_cfg["provider"],
        ssl=email_cfg["ssl"]
    )

    client.login()

    logger.info("\n=== 最近邮件摘要 ===")
    for info in client.list_recent_emails(limit=5):
        print(f"{info['date']}: {info['from']} → {info['subject']}")

    logger.info("\n=== 尝试获取验证码 ===")

    client.logout()