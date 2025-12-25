# mailbox_client.py
import imaplib
import email
import re
import os
import yaml
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict, Tuple, Any
import datetime
from bs4 import BeautifulSoup
from .config import Config
from common.logger import logger
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import time


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
    def _ensure_selected(self, mailbox: str = "INBOX"):
        """确保当前连接处于 SELECTED 状态，否则尝试 select 指定邮箱"""
        if not self.conn:
            raise Exception("请先调用 login()")
        
        # 检查当前邮箱状态
        current_state = getattr(self.conn, "state", None)
        if current_state != "SELECTED":
            typ, data = self.conn.select(mailbox)
            if typ != "OK":
                raise Exception(f"选择邮箱失败: {data}")
        return True

    def _decode_header(self, hdr):
        """解码邮件头，处理各种编码问题"""
        if not hdr:
            return ""
        
        # 如果已经是字符串，直接返回
        if isinstance(hdr, str):
            return hdr
        
        try:
            # 首先尝试标准的decode_header
            decoded_parts = decode_header(hdr)
            result_parts = []
            
            for content, encoding in decoded_parts:
                if isinstance(content, bytes):
                    if encoding:
                        try:
                            # 尝试使用指定的编码
                            decoded = content.decode(encoding, errors='ignore')
                        except (LookupError, UnicodeDecodeError):
                            # 如果编码不可用，尝试常见编码
                            for enc in ['utf-8', 'gbk', 'gb2312', 'iso-8859-1', 'ascii']:
                                try:
                                    decoded = content.decode(enc, errors='ignore')
                                    break
                                except UnicodeDecodeError:
                                    continue
                            else:
                                decoded = content.decode('utf-8', errors='ignore')
                    else:
                        # 没有指定编码，尝试常见编码
                        for enc in ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']:
                            try:
                                decoded = content.decode(enc, errors='ignore')
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            decoded = content.decode('utf-8', errors='ignore')
                else:
                    decoded = str(content)
                
                result_parts.append(decoded)
            
            result = ''.join(result_parts)
            
            # 如果结果为空或看起来不对，尝试直接解码
            if not result or '=?' in result:
                try:
                    # 尝试直接UTF-8解码
                    if isinstance(hdr, bytes):
                        result = hdr.decode('utf-8', errors='ignore')
                    else:
                        result = str(hdr)
                except Exception:
                    result = str(hdr)
            
            return result
        except Exception as e:
            logger.debug(f"[!] 解码头信息失败: {hdr[:100]}, 错误: {e}")
            # 返回原始字符串或空字符串
            try:
                if isinstance(hdr, bytes):
                    return hdr.decode('utf-8', errors='ignore')
                return str(hdr)
            except Exception:
                return ""

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

    def _extract_attachments(self, msg) -> List[Dict]:
        """提取邮件附件信息"""
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_disposition() == 'attachment':
                    filename = self._decode_header(part.get_filename())
                    if filename:
                        attachments.append({
                            'filename': filename,
                            'content_type': part.get_content_type(),
                            'size': len(part.get_payload(decode=True) or b'')
                        })
        return attachments

    def _parse_email_details(self, msg, msg_id: str = "") -> Dict[str, Any]:
        """解析邮件详细信息"""
        try:
            date_str = msg.get("Date", "")
            date = None
            if date_str:
                try:
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    date = None

            subject = self._decode_header(msg.get("Subject", ""))
            from_ = self._decode_header(msg.get("From", ""))
            to_ = self._decode_header(msg.get("To", ""))
            cc_ = self._decode_header(msg.get("Cc", ""))
            
            # 提取邮件头信息
            headers = {}
            for key, value in msg.items():
                if key.lower() not in ['subject', 'from', 'to', 'cc', 'date']:
                    headers[key] = self._decode_header(value)

            body = self._extract_body(msg)
            attachments = self._extract_attachments(msg)

            return {
                "id": msg_id,
                "subject": subject,
                "from": from_,
                "to": to_,
                "cc": cc_,
                "date": date,
                "body": body,
                "attachments": attachments,
                "headers": headers,
                "size": len(msg.as_bytes()) if hasattr(msg, 'as_bytes') else 0
            }
        except Exception as e:
            logger.error(f"[!] 解析邮件失败: {e}")
            return {}

    def _build_time_criteria(self, years: int = 0, months: int = 0, days: int = 0, 
                            hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
        """构建时间搜索条件"""
        if years == 0 and months == 0 and days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            return "ALL"
        
        # 计算时间范围
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = datetime.timedelta(
            days=days + years*365 + months*30,  # 近似计算
            hours=hours,
            minutes=minutes,
            seconds=seconds
        )
        since_date = (now - delta).strftime("%d-%b-%Y")
        
        return f"SINCE {since_date}"

    def _format_imap_date(self, date_input) -> Optional[str]:
        """
        格式化日期为IMAP要求的格式（dd-mmm-yyyy）
        """
        try:
            if isinstance(date_input, datetime.datetime):
                return date_input.strftime("%d-%b-%Y")
            elif isinstance(date_input, datetime.date):
                return date_input.strftime("%d-%b-%Y")
            elif isinstance(date_input, str):
                # 尝试解析字符串
                date_formats = [
                    "%Y-%m-%d",      # 2025-12-01
                    "%d-%b-%Y",      # 01-Dec-2025
                    "%d/%m/%Y",      # 01/12/2025
                    "%m/%d/%Y",      # 12/01/2025
                    "%Y%m%d",        # 20251201
                ]
                
                for fmt in date_formats:
                    try:
                        date_obj = datetime.datetime.strptime(date_input, fmt)
                        return date_obj.strftime("%d-%b-%Y")
                    except ValueError:
                        continue
                
                # 如果都不匹配，尝试直接使用
                return date_input
            return None
        except Exception as e:
            logger.warning(f"[!] 格式化日期失败: {date_input}, 错误: {e}")
            return None

    # ---------------- 核心功能：重构方法 ----------------
    
    # 1. 发送邮件（增强异常处理）
    def send_email(
        self,
        to_addr: str,
        subject: str,
        body: str,
        attachment_path: Optional[str] = None,
        html: bool = False,
        cc: Optional[str] = None,
        bcc: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        发送邮件（支持 HTML 格式、CC、BCC）
        
        Args:
            to_addr: 收件人地址
            subject: 邮件主题
            body: 邮件正文
            attachment_path: 附件路径
            html: 是否为HTML格式
            cc: 抄送地址
            bcc: 密送地址
            
        Returns:
            Dict containing success status and message
        """
        result = {
            "success": False,
            "message": "",
            "error": None,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        try:
            # 创建邮件对象
            if attachment_path or cc or bcc:
                msg = MIMEMultipart()
                msg["From"] = self.email_addr
                msg["To"] = to_addr
                msg["Subject"] = subject
                
                if cc:
                    msg["Cc"] = cc
                if bcc:
                    # BCC不会在邮件头显示
                    pass
                    
                # 添加正文
                mime_type = "html" if html else "plain"
                msg.attach(MIMEText(body, mime_type, "utf-8"))
                
                # 添加附件
                if attachment_path and os.path.exists(attachment_path):
                    with open(attachment_path, "rb") as f:
                        filename = os.path.basename(attachment_path)
                        attachment = MIMEApplication(f.read(), Name=filename)
                        attachment["Content-Disposition"] = f'attachment; filename="{filename}"'
                        msg.attach(attachment)
            else:
                # 简单邮件
                mime_type = "html" if html else "plain"
                msg = MIMEText(body, mime_type, "utf-8")
                msg["From"] = self.email_addr
                msg["To"] = to_addr
                msg["Subject"] = subject

            # 构建收件人列表
            recipients = [to_addr]
            if cc:
                recipients.append(cc)
            if bcc:
                recipients.append(bcc)

            # 发送邮件
            if self.smtp_ssl:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    server.login(self.email_addr, self.password)
                    server.sendmail(self.email_addr, recipients, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    server.login(self.email_addr, self.password)
                    server.sendmail(self.email_addr, recipients, msg.as_string())

            result["success"] = True
            result["message"] = f"邮件发送成功: {subject}"
            logger.info(f"[+] {result['message']}")

        except smtplib.SMTPResponseException as e:
            if e.smtp_code == -1 and e.smtp_error == b'\x00\x00\x00':
                result["success"] = True
                result["message"] = f"邮件可能已成功发送（QQ特殊返回码）: {subject}"
                logger.warning(f"[!] {result['message']}")
            else:
                result["error"] = f"SMTP返回异常: {e.smtp_code}, {e.smtp_error}"
                logger.error(f"[!] {result['error']}")

        except smtplib.SMTPAuthenticationError as e:
            result["error"] = f"SMTP认证失败: {e}"
            logger.error(f"[!] {result['error']}")

        except smtplib.SMTPConnectError as e:
            result["error"] = f"SMTP连接失败: {e}"
            logger.error(f"[!] {result['error']}")

        except smtplib.SMTPException as e:
            result["error"] = f"SMTP通用异常: {e}"
            logger.error(f"[!] {result['error']}")

        except FileNotFoundError as e:
            result["error"] = f"附件文件未找到: {e}"
            logger.error(f"[!] {result['error']}")

        except Exception as e:
            if "b'\\x00\\x00\\x00'" in str(e) or "[-1]" in str(e):
                result["success"] = True
                result["message"] = f"邮件可能已成功发送（捕获非标准返回）: {subject}"
                logger.warning(f"[!] {result['message']}")
            else:
                result["error"] = f"邮件发送失败: {e}"
                logger.error(f"[!] {result['error']}")

        return result

    # 2. 获取完整邮件（支持时间过滤）
    def get_emails_full(
        self,
        years: int = 0,
        months: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        mailbox: str = "INBOX",
        limit: int = 50,
        unread_only: bool = False,
        from_filter: Optional[str] = None,
        subject_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取完整邮件内容，支持精确时间过滤
        
        Args:
            years: 最近几年
            months: 最近几个月
            days: 最近几天
            hours: 最近几小时
            minutes: 最近几分钟
            seconds: 最近几秒
            mailbox: 邮箱文件夹
            limit: 最大返回数量
            unread_only: 是否只获取未读邮件
            from_filter: 发件人过滤
            subject_filter: 主题过滤
            
        Returns:
            List of email details
        """
        emails = []
        
        try:
            self._ensure_selected(mailbox)
            
            # 构建搜索条件
            criteria_parts = []
            if unread_only:
                criteria_parts.append("UNSEEN")
            else:
                criteria_parts.append("ALL")
                
            if from_filter:
                criteria_parts.append(f'FROM "{from_filter}"')
            if subject_filter:
                criteria_parts.append(f'SUBJECT "{subject_filter}"')
                
            # 添加时间条件
            time_criteria = self._build_time_criteria(years, months, days, hours, minutes, seconds)
            if time_criteria != "ALL":
                criteria_parts.append(time_criteria)
                
            criteria = " ".join(criteria_parts)
            
            # 搜索邮件
            result, data = self.conn.search(None, criteria)
            if result != "OK" or not data[0]:
                return emails

            # 获取邮件ID
            ids = data[0].split()
            fetch_ids = ids[-limit:] if limit > 0 else ids
            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            for msg_id in reversed(fetch_ids):  # 从最新开始
                try:
                    res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
                    if res != "OK" or not msg_data or not msg_data[0]:
                        continue
                        
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    # 精确时间过滤
                    date_str = msg.get("Date", "")
                    if date_str:
                        try:
                            email_date = parsedate_to_datetime(date_str)
                            if email_date:
                                # 如果邮件没有时区信息，假设为UTC
                                if email_date.tzinfo is None:
                                    email_date = email_date.replace(tzinfo=datetime.timezone.utc)
                                
                                # 计算时间差
                                time_diff = current_time - email_date
                                total_seconds = time_diff.total_seconds()
                                
                                # 检查是否在指定时间范围内
                                max_seconds = (
                                    seconds + 
                                    minutes * 60 + 
                                    hours * 3600 + 
                                    days * 86400 + 
                                    months * 2592000 +  # 近似30天
                                    years * 31536000    # 近似365天
                                )
                                
                                if max_seconds > 0 and total_seconds > max_seconds:
                                    continue
                        except Exception:
                            pass
                    
                    # 解析邮件详情
                    email_details = self._parse_email_details(msg, msg_id.decode())
                    if email_details:
                        emails.append(email_details)
                        
                except Exception as e:
                    logger.error(f"[!] 获取邮件 {msg_id} 失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[!] 获取完整邮件失败: {e}")
            
        return emails

    # 3. 获取邮件摘要（支持时间过滤）
    def get_emails_summary(
        self,
        years: int = 0,
        months: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        mailbox: str = "INBOX",
        limit: int = 20,
        unread_only: bool = False,
        include_body_preview: bool = False,
        body_preview_length: int = 200
    ) -> List[Dict[str, Any]]:
        """
        获取邮件摘要信息，支持精确时间过滤
        
        Args:
            years: 最近几年
            months: 最近几个月
            days: 最近几天
            hours: 最近几小时
            minutes: 最近几分钟
            seconds: 最近几秒
            mailbox: 邮箱文件夹
            limit: 最大返回数量
            unread_only: 是否只获取未读邮件
            include_body_preview: 是否包含正文预览
            body_preview_length: 正文预览长度
            
        Returns:
            List of email summaries
        """
        summaries = []
        
        try:
            self._ensure_selected(mailbox)
            
            # 构建搜索条件
            criteria_parts = ["UNSEEN" if unread_only else "ALL"]
            time_criteria = self._build_time_criteria(years, months, days, hours, minutes, seconds)
            if time_criteria != "ALL":
                criteria_parts.append(time_criteria)
                
            criteria = " ".join(criteria_parts)
            
            # 搜索邮件
            result, data = self.conn.search(None, criteria)
            if result != "OK" or not data[0]:
                return summaries

            # 获取邮件ID
            ids = data[0].split()
            fetch_ids = ids[-limit:] if limit > 0 else ids
            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            for msg_id in reversed(fetch_ids):
                try:
                    res, msg_data = self.conn.fetch(msg_id, "(BODY.PEEK[HEADER] RFC822.SIZE)")
                    if res != "OK" or not msg_data or not msg_data[0]:
                        continue
                        
                    # 解析邮件头
                    header_data = msg_data[0][1] if isinstance(msg_data[0][1], bytes) else b''
                    msg = email.message_from_bytes(header_data)
                    
                    # 获取大小
                    size = 0
                    for item in msg_data:
                        if isinstance(item, tuple) and len(item) > 1:
                            if b'RFC822.SIZE' in item[0]:
                                try:
                                    size_str = item[1].decode().strip()
                                    size = int(re.search(r'\d+', size_str).group())
                                except:
                                    pass
                    
                    # 精确时间过滤
                    date_str = msg.get("Date", "")
                    email_date = None
                    if date_str:
                        try:
                            email_date = parsedate_to_datetime(date_str)
                            if email_date:
                                # 检查时间范围
                                if email_date.tzinfo is None:
                                    email_date = email_date.replace(tzinfo=datetime.timezone.utc)
                                
                                time_diff = current_time - email_date
                                total_seconds = time_diff.total_seconds()
                                
                                max_seconds = (
                                    seconds + 
                                    minutes * 60 + 
                                    hours * 3600 + 
                                    days * 86400 + 
                                    months * 2592000 + 
                                    years * 31536000
                                )
                                
                                if max_seconds > 0 and total_seconds > max_seconds:
                                    continue
                        except Exception:
                            pass
                    
                    # 提取摘要信息
                    subject = self._decode_header(msg.get("Subject", ""))
                    from_ = self._decode_header(msg.get("From", ""))
                    to_ = self._decode_header(msg.get("To", ""))
                    
                    summary = {
                        "id": msg_id.decode(),
                        "subject": subject,
                        "from": from_,
                        "to": to_,
                        "date": email_date,
                        "size": size,
                        "has_attachments": False,
                        "is_unread": unread_only
                    }
                    
                    # 如果需要正文预览，获取更多内容
                    if include_body_preview:
                        try:
                            res_body, msg_body_data = self.conn.fetch(msg_id, "(BODY.PEEK[TEXT])")
                            if res_body == "OK" and msg_body_data[0]:
                                body_text = ""
                                if isinstance(msg_body_data[0][1], bytes):
                                    body_text = msg_body_data[0][1].decode('utf-8', errors='ignore')
                                summary["body_preview"] = body_text[:body_preview_length] + "..." if len(body_text) > body_preview_length else body_text
                        except Exception:
                            summary["body_preview"] = ""
                    
                    summaries.append(summary)
                    
                except Exception as e:
                    logger.error(f"[!] 获取邮件摘要 {msg_id} 失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[!] 获取邮件摘要失败: {e}")
            
        return summaries

    # 4. 查询邮件（通过摘要内容获取完整邮件）
    def query_email(
        self,
        search_criteria: Dict[str, Any],
        mailbox: str = "INBOX",
        get_full_content: bool = True,
        strict_mode: bool = True  # 新增：是否严格模式（AND关系）
    ) -> List[Dict[str, Any]]:
        """
        根据查询条件搜索邮件
        
        Args:
            search_criteria: 查询条件字典
            mailbox: 邮箱文件夹
            get_full_content: 是否获取完整内容
            strict_mode: True表示AND关系（严格模式），False表示OR关系
            
        Returns:
            List of email details
        """
        results = []
        
        try:
            self._ensure_selected(mailbox)
            
            # 构建搜索条件
            criteria_parts = []
            
            # 处理未读状态
            if search_criteria.get("is_unread"):
                criteria_parts.append("UNSEEN")
            else:
                criteria_parts.append("ALL")
                
            # 处理主题搜索
            if subject := search_criteria.get("subject"):
                try:
                    # 清理主题字符串
                    clean_subject = subject.strip()
                    # 处理特殊字符
                    clean_subject = clean_subject.replace('"', '\\"')
                    criteria_parts.append(f'SUBJECT "{clean_subject}"')
                    logger.debug(f"[D] 主题搜索条件: SUBJECT \"{clean_subject}\"")
                except Exception as e:
                    logger.warning(f"[!] 处理主题搜索条件失败: {e}")
                    
            # 处理日期
            if after_date := search_criteria.get("after_date"):
                date_str = self._format_imap_date(after_date)
                if date_str:
                    criteria_parts.append(f'SINCE {date_str}')
                    logger.debug(f"[D] 日期条件: SINCE {date_str}")
                    
            if before_date := search_criteria.get("before_date"):
                date_str = self._format_imap_date(before_date)
                if date_str:
                    criteria_parts.append(f'BEFORE {date_str}')
                    logger.debug(f"[D] 日期条件: BEFORE {date_str}")
                    
            # 处理其他条件...
            if from_addr := search_criteria.get("from"):
                # 提取邮箱地址
                email_match = re.search(r'<(.+?)>', from_addr)
                if email_match:
                    criteria_parts.append(f'FROM "{email_match.group(1)}"')
                else:
                    criteria_parts.append(f'FROM "{from_addr}"')
                    
            if to_addr := search_criteria.get("to"):
                email_match = re.search(r'<(.+?)>', to_addr)
                if email_match:
                    criteria_parts.append(f'TO "{email_match.group(1)}"')
                else:
                    criteria_parts.append(f'TO "{to_addr}"')
                    
            if has_attachment := search_criteria.get("has_attachment"):
                if has_attachment:
                    criteria_parts.append('HAS attachment')
            
            criteria = " ".join(criteria_parts)
            
            # 调试：打印完整的搜索条件
            logger.info(f"[INFO] IMAP搜索条件: {criteria}")
            
            try:
                # 搜索邮件
                result, data = self.conn.search(None, criteria)
                
                if result != "OK" or not data or not data[0]:
                    logger.info(f"[-] 未找到匹配的邮件: {criteria}")
                    return results

                ids = data[0].split()
                logger.info(f"[+] 找到 {len(ids)} 封匹配邮件")
                
            except imaplib.IMAP4.error as e:
                logger.error(f"[!] IMAP搜索失败: {e}")
                logger.error(f"[!] 搜索条件: {criteria}")
                return results
                    
            # 如果有正文关键词过滤，需要获取完整内容检查
            body_keyword = search_criteria.get("body")
            if body_keyword and not get_full_content:
                get_full_content = True
                
            for msg_id in reversed(ids):
                try:
                    msg_id_str = msg_id.decode('utf-8') if isinstance(msg_id, bytes) else str(msg_id)
                    
                    if get_full_content:
                        # 获取完整邮件
                        res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
                        if res != "OK" or not msg_data or not msg_data[0]:
                            continue
                            
                        msg = email.message_from_bytes(msg_data[0][1])
                        
                        # 在严格模式下，再次检查主题匹配
                        if strict_mode and subject:
                            email_subject = self._decode_header(msg.get("Subject", ""))
                            if subject.lower() not in email_subject.lower():
                                logger.debug(f"[D] 严格模式：跳过不匹配主题的邮件: {email_subject[:50]}...")
                                continue
                                
                        # 检查正文关键词
                        if body_keyword:
                            body = self._extract_body(msg)
                            if body_keyword.lower() not in body.lower():
                                continue
                                
                        email_details = self._parse_email_details(msg, msg_id_str)
                        if email_details:
                            results.append(email_details)
                            
                    else:
                        # 只获取摘要
                        res, msg_data = self.conn.fetch(msg_id, "(BODY.PEEK[HEADER])")
                        if res != "OK" or not msg_data or not msg_data[0]:
                            continue
                            
                        msg = email.message_from_bytes(msg_data[0][1])
                        
                        # 在严格模式下，再次检查主题匹配
                        if strict_mode and subject:
                            email_subject = self._decode_header(msg.get("Subject", ""))
                            if subject.lower() not in email_subject.lower():
                                continue
                                
                        email_details = self._parse_email_details(msg, msg_id_str)
                        if email_details:
                            results.append(email_details)
                            
                except Exception as e:
                    logger.error(f"[!] 处理邮件 {msg_id} 失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[!] 查询邮件失败: {e}")
            
        return results

    # ---------------- 额外辅助方法 ----------------
    
    def mark_as_read(self, email_ids: List[str]) -> bool:
        """标记邮件为已读"""
        try:
            self._ensure_selected()
            for email_id in email_ids:
                self.conn.store(email_id.encode(), '+FLAGS', r'(\Seen)')
            return True
        except Exception as e:
            logger.error(f"[!] 标记已读失败: {e}")
            return False
    
    def move_emails(self, email_ids: List[str], target_mailbox: str) -> bool:
        """移动邮件到指定文件夹"""
        try:
            self._ensure_selected()
            for email_id in email_ids:
                self.conn.copy(email_id.encode(), target_mailbox)
                self.conn.store(email_id.encode(), '+FLAGS', r'(\Deleted)')
            self.conn.expunge()
            return True
        except Exception as e:
            logger.error(f"[!] 移动邮件失败: {e}")
            return False
    
    def get_mailbox_info(self) -> Dict[str, Any]:
        """获取邮箱信息"""
        try:
            self._ensure_selected()
            # 获取邮箱状态
            typ, data = self.conn.status("INBOX", "(MESSAGES UNSEEN RECENT)")
            if typ == "OK":
                info = {}
                for item in data[0].decode().split():
                    if '=' in item:
                        key, value = item.split('=')
                        info[key.strip('()')] = int(value.strip('"'))
                return info
            return {}
        except Exception as e:
            logger.error(f"[!] 获取邮箱信息失败: {e}")
            return {}


# ---------------- 测试 / CLI 使用示例 ----------------
if __name__ == "__main__":
    # 测试新功能
    try:
        cfg = Config("config.yaml")
        email_cfg = cfg.email

        client = MailBoxClient(
            email_addr=email_cfg["address"],
            password=email_cfg["password"],
            provider=email_cfg["provider"],
            ssl=email_cfg["ssl"]
        )

        client.login()

        # 测试1: 发送邮件
        print("\n=== 测试发送邮件 ===")
        send_result = client.send_email(
            to_addr="3222973652@qq.com",
            subject="测试邮件",
            body="这是一封测试邮件",
            html=False
        )
        print(f"发送结果: {send_result}")

        # 测试2: 获取最近15秒的邮件
        print("\n=== 测试获取最近15秒的邮件 ===")
        recent_emails = client.get_emails_full(months=1)
        print(f"找到 {len(recent_emails)} 封邮件")

        # 测试3: 获取邮件摘要
        print("\n=== 测试获取邮件摘要 ===")
        summaries = client.get_emails_summary(
            months=1,
            limit=10,
            include_body_preview=True,
            body_preview_length=100
        )
        for summary in summaries:
            print(f"主题: {summary['subject']}")
            print(f"发件人: {summary['from']}")
            print(f"时间: {summary['date']}")
            print(f"预览: {summary.get('body_preview', '')}")
            print("-" * 50)

        # 测试4: 查询邮件
        print("\n=== 测试查询邮件 ===")
        query_results = client.query_email({
            "subject": "验证码",
            "is_unread": True,
            "after_date": (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%d-%b-%Y")
        })
        print(f"查询到 {len(query_results)} 封邮件")

    

        client.logout()

    except Exception as e:
        print(f"[!] 测试过程中出现错误: {e}")