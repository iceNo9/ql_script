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
from .config.config import Config
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
        """
        初始化邮箱客户端
        
        Args:
            email_addr: 邮箱地址
            password: 邮箱密码或授权码
            provider: 服务商，可选 "163"/"126"/"qq"/"gmail"
            ssl: 是否使用SSL/TLS加密
        """
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
        logger.debug(f"[MailBoxClient] 初始化完成 - 邮箱: {email_addr}, 服务商: {provider}")

    # ---------------- 配置加载 ----------------
    @staticmethod
    def from_config(path: str = "config.yaml"):
        """从 config.yaml 创建客户端实例"""
        logger.info(f"[from_config] 开始加载配置文件: {path}")
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

        logger.info(f"[from_config] 配置加载成功 - 邮箱: {address}, 服务商: {provider}")
        return MailBoxClient(email_addr=address, password=password, provider=provider, ssl=ssl)

    # ---------------- 登录 / 登出 ----------------
    def login(self):
        """
        登录邮箱服务器
        
        Raises:
            Exception: 登录失败时抛出异常
        """
        logger.info(f"[login] 开始登录邮箱: {self.email_addr}")
        try:
            if self.imap_ssl:
                self.conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
                logger.debug(f"[login] 使用SSL连接到 {self.imap_host}:{self.imap_port}")
            else:
                self.conn = imaplib.IMAP4(self.imap_host, self.imap_port)
                logger.debug(f"[login] 使用非SSL连接到 {self.imap_host}:{self.imap_port}")

            typ, data = self.conn.login(self.email_addr, self.password)
            if typ != "OK":
                raise Exception(f"登录失败: {data}")
            logger.debug(f"[login] 登录认证成功")

            # 尝试发送 ID 命令让服务器认为是常见客户端（部分服务器可能不支持）
            try:
                self.conn._simple_command('ID', '("name" "Thunderbird" "version" "102.0")')
                logger.debug("[login] 已发送客户端标识")
            except Exception as e:
                logger.debug(f"[login] 发送客户端标识失败: {e}")

            # 强制 select INBOX，并检查返回值
            typ, data = self.conn.select("INBOX")
            if typ != "OK":
                raise Exception(f"选择邮箱失败: {data}")
            logger.debug(f"[login] 已选择INBOX邮箱")

            logger.info(f"[login] 登录成功: {self.email_addr} ({self.provider})")

        except imaplib.IMAP4.error as e:
            logger.error(f"[login] IMAP异常: {e}")
            raise Exception(f"[!] IMAP异常: {e}")

    def logout(self):
        """登出邮箱服务器"""
        logger.info("[logout] 开始登出邮箱")
        if self.conn:
            try:
                self.conn.logout()
                logger.info("[logout] 已成功登出邮箱")
            except Exception as e:
                logger.error(f"[logout] 登出时发生错误: {e}")
            finally:
                self.conn = None
                logger.debug("[logout] 连接已置空")

    # ---------------- 内部工具 ----------------
    def _ensure_selected(self, mailbox: str = "INBOX"):
        """
        确保当前连接处于 SELECTED 状态，否则尝试 select 指定邮箱
        
        Args:
            mailbox: 邮箱文件夹名称，默认为"INBOX"
            
        Returns:
            bool: 操作是否成功
            
        Raises:
            Exception: 选择邮箱失败时抛出异常
        """
        logger.debug(f"[_ensure_selected] 检查邮箱状态，目标邮箱: {mailbox}")
        
        if not self.conn:
            logger.error("[_ensure_selected] 连接未建立，请先调用login()")
            raise Exception("请先调用 login()")
        
        # 检查当前邮箱状态
        current_state = getattr(self.conn, "state", None)
        logger.debug(f"[_ensure_selected] 当前连接状态: {current_state}")
        
        if current_state != "SELECTED":
            logger.info(f"[_ensure_selected] 状态未SELECTED，正在选择邮箱: {mailbox}")
            typ, data = self.conn.select(mailbox)
            if typ != "OK":
                error_msg = f"选择邮箱失败: {data}"
                logger.error(f"[_ensure_selected] {error_msg}")
                raise Exception(error_msg)
            logger.debug(f"[_ensure_selected] 邮箱选择成功: {mailbox}")
        else:
            logger.debug("[_ensure_selected] 连接已在SELECTED状态，无需重新选择")
            
        return True

    def _decode_header(self, hdr):
        """
        解码邮件头，处理各种编码问题
        
        Args:
            hdr: 邮件头内容（可能是bytes或str）
            
        Returns:
            str: 解码后的字符串
        """
        logger.debug(f"[_decode_header] 开始解码邮件头，类型: {type(hdr)}")
        
        if not hdr:
            logger.debug("[_decode_header] 邮件头为空")
            return ""
        
        # 如果已经是字符串，直接返回
        if isinstance(hdr, str):
            logger.debug("[_decode_header] 邮件头已经是字符串，直接返回")
            return hdr
        
        try:
            # 首先尝试标准的decode_header
            decoded_parts = decode_header(hdr)
            logger.debug(f"[_decode_header] decode_header解析出 {len(decoded_parts)} 个部分")
            
            result_parts = []
            
            for i, (content, encoding) in enumerate(decoded_parts):
                logger.debug(f"[_decode_header] 处理第{i+1}部分，编码: {encoding}")
                
                if isinstance(content, bytes):
                    if encoding:
                        try:
                            # 尝试使用指定的编码
                            decoded = content.decode(encoding, errors='ignore')
                            logger.debug(f"[_decode_header] 使用指定编码 {encoding} 解码成功")
                        except (LookupError, UnicodeDecodeError) as e:
                            logger.debug(f"[_decode_header] 指定编码 {encoding} 解码失败: {e}，尝试常见编码")
                            # 如果编码不可用，尝试常见编码
                            for enc in ['utf-8', 'gbk', 'gb2312', 'iso-8859-1', 'ascii']:
                                try:
                                    decoded = content.decode(enc, errors='ignore')
                                    logger.debug(f"[_decode_header] 使用编码 {enc} 解码成功")
                                    break
                                except UnicodeDecodeError:
                                    continue
                            else:
                                decoded = content.decode('utf-8', errors='ignore')
                                logger.debug("[_decode_header] 所有编码尝试失败，使用utf-8解码")
                    else:
                        logger.debug("[_decode_header] 未指定编码，尝试常见编码")
                        # 没有指定编码，尝试常见编码
                        for enc in ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']:
                            try:
                                decoded = content.decode(enc, errors='ignore')
                                logger.debug(f"[_decode_header] 使用编码 {enc} 解码成功")
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            decoded = content.decode('utf-8', errors='ignore')
                            logger.debug("[_decode_header] 所有编码尝试失败，使用utf-8解码")
                else:
                    decoded = str(content)
                    logger.debug(f"[_decode_header] 内容非bytes类型，直接转换为字符串")
                
                result_parts.append(decoded)
                logger.debug(f"[_decode_header] 第{i+1}部分解码结果: {decoded[:50]}...")
            
            result = ''.join(result_parts)
            logger.debug(f"[_decode_header] 合并后结果长度: {len(result)}")
            
            # 如果结果为空或看起来不对，尝试直接解码
            if not result or '=?' in result:
                logger.debug("[_decode_header] 结果可能有问题，尝试直接解码")
                try:
                    # 尝试直接UTF-8解码
                    if isinstance(hdr, bytes):
                        result = hdr.decode('utf-8', errors='ignore')
                        logger.debug("[_decode_header] 直接UTF-8解码成功")
                    else:
                        result = str(hdr)
                except Exception as e:
                    logger.debug(f"[_decode_header] 直接解码失败: {e}")
                    result = str(hdr)
            
            logger.debug(f"[_decode_header] 最终解码结果: {result[:100]}...")
            return result
            
        except Exception as e:
            logger.error(f"[_decode_header] 解码头信息失败，原始内容: {str(hdr)[:100]}..., 错误: {e}")
            # 返回原始字符串或空字符串
            try:
                if isinstance(hdr, bytes):
                    return hdr.decode('utf-8', errors='ignore')
                return str(hdr)
            except Exception:
                return ""

    def _extract_body(self, msg) -> str:
        """
        提取邮件正文（支持 text/plain + text/html）
        
        Args:
            msg: email.message.Message对象
            
        Returns:
            str: 邮件正文文本
        """
        logger.debug("[_extract_body] 开始提取邮件正文")
        body = ""
        
        if msg.is_multipart():
            logger.debug("[_extract_body] 邮件为multipart格式")
            for i, part in enumerate(msg.walk()):
                ctype = part.get_content_type()
                logger.debug(f"[_extract_body] 第{i+1}部分，类型: {ctype}")
                
                if ctype in ["text/plain", "text/html"]:
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        logger.debug(f"[_extract_body] 第{i+1}部分，字符集: {charset}")
                        
                        raw = part.get_payload(decode=True)
                        if raw is None:
                            logger.debug(f"[_extract_body] 第{i+1}部分，payload为空")
                            continue
                            
                        text = raw.decode(charset, errors="ignore")
                        logger.debug(f"[_extract_body] 第{i+1}部分，解码成功，长度: {len(text)}")
                        
                        if ctype == "text/html":
                            logger.debug("[_extract_body] 第{i+1}部分为HTML，转换为纯文本")
                            text = BeautifulSoup(text, "html.parser").get_text(separator="\n")
                            
                        if text.strip():
                            body = text
                            logger.debug("[_extract_body] 使用第{i+1}部分作为正文，长度: {len(body)}")
                            break
                    except Exception as e:
                        logger.error(f"[_extract_body] 提取第{i+1}部分正文失败: {e}")
                        continue
        else:
            logger.debug("[_extract_body] 邮件为单部分格式")
            charset = msg.get_content_charset() or "utf-8"
            logger.debug(f"[_extract_body] 字符集: {charset}")
            
            raw = msg.get_payload(decode=True) or b""
            text = raw.decode(charset, errors="ignore")
            logger.debug(f"[_extract_body] 解码成功，长度: {len(text)}")
            
            body = BeautifulSoup(text, "html.parser").get_text(separator="\n")
            logger.debug(f"[_extract_body] 处理后正文长度: {len(body)}")
        
        logger.debug(f"[_extract_body] 正文提取完成，长度: {len(body)}")
        return body

    def _extract_attachments(self, msg) -> List[Dict]:
        """
        提取邮件附件信息
        
        Args:
            msg: email.message.Message对象
            
        Returns:
            List[Dict]: 附件信息列表
        """
        logger.debug("[_extract_attachments] 开始提取附件信息")
        attachments = []
        
        if msg.is_multipart():
            logger.debug("[_extract_attachments] 邮件为multipart格式")
            for i, part in enumerate(msg.walk()):
                if part.get_content_disposition() == 'attachment':
                    filename = self._decode_header(part.get_filename())
                    if filename:
                        attachment_info = {
                            'filename': filename,
                            'content_type': part.get_content_type(),
                            'size': len(part.get_payload(decode=True) or b'')
                        }
                        attachments.append(attachment_info)
                        logger.debug(f"[_extract_attachments] 找到附件 {i+1}: {filename}, 大小: {attachment_info['size']} bytes")
        else:
            logger.debug("[_extract_attachments] 邮件为单部分格式，无附件")
        
        logger.debug(f"[_extract_attachments] 找到 {len(attachments)} 个附件")
        return attachments

    def _parse_email_details(self, msg, msg_id: str = "") -> Dict[str, Any]:
        """
        解析邮件详细信息
        
        Args:
            msg: email.message.Message对象
            msg_id: 邮件ID
            
        Returns:
            Dict[str, Any]: 邮件详细信息
        """
        logger.info(f"[_parse_email_details] 开始解析邮件ID: {msg_id}")
        
        try:
            date_str = msg.get("Date", "")
            date = None
            if date_str:
                try:
                    date = parsedate_to_datetime(date_str)
                    logger.debug(f"[_parse_email_details] 日期解析成功: {date}")
                except Exception as e:
                    logger.warning(f"[_parse_email_details] 日期解析失败: {e}，原始日期: {date_str}")
                    date = None

            subject = self._decode_header(msg.get("Subject", ""))
            from_ = self._decode_header(msg.get("From", ""))
            to_ = self._decode_header(msg.get("To", ""))
            cc_ = self._decode_header(msg.get("Cc", ""))
            
            logger.debug(f"[_parse_email_details] 基础信息 - 主题: {subject[:50]}..., 发件人: {from_}, 收件人: {to_}")
            
            # 提取邮件头信息
            headers = {}
            for key, value in msg.items():
                if key.lower() not in ['subject', 'from', 'to', 'cc', 'date']:
                    headers[key] = self._decode_header(value)
            
            logger.debug(f"[_parse_email_details] 提取了 {len(headers)} 个邮件头")

            body = self._extract_body(msg)
            attachments = self._extract_attachments(msg)
            
            if attachments:
                logger.debug(f"[_parse_email_details] 邮件包含 {len(attachments)} 个附件")

            result = {
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
            
            logger.info(f"[_parse_email_details] 邮件解析成功 - ID: {msg_id}, 主题: {subject[:30]}")
            return result
            
        except Exception as e:
            logger.error(f"[_parse_email_details] 解析邮件失败: {e}")
            return {}

    def _build_time_criteria(self, years: int = 0, months: int = 0, days: int = 0, 
                            hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
        """
        构建时间搜索条件
        
        Args:
            years: 最近几年
            months: 最近几个月
            days: 最近几天
            hours: 最近几小时
            minutes: 最近几分钟
            seconds: 最近几秒
            
        Returns:
            str: IMAP搜索条件字符串
        """
        logger.debug(f"[_build_time_criteria] 构建时间条件 - 年: {years}, 月: {months}, 日: {days}, 时: {hours}, 分: {minutes}, 秒: {seconds}")
        
        if years == 0 and months == 0 and days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            logger.debug("[_build_time_criteria] 所有时间参数为0，返回'ALL'")
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
        
        criteria = f"SINCE {since_date}"
        logger.debug(f"[_build_time_criteria] 时间条件: {criteria}")
        return criteria

    def _format_imap_date(self, date_input) -> Optional[str]:
        """
        格式化日期为IMAP要求的格式（dd-mmm-yyyy）
        
        Args:
            date_input: 日期输入，可以是datetime、date或字符串
            
        Returns:
            Optional[str]: 格式化后的日期字符串，解析失败返回None
        """
        logger.debug(f"[_format_imap_date] 格式化日期输入: {date_input}, 类型: {type(date_input)}")
        
        try:
            if isinstance(date_input, datetime.datetime):
                result = date_input.strftime("%d-%b-%Y")
                logger.debug(f"[_format_imap_date] datetime类型格式化结果: {result}")
                return result
            elif isinstance(date_input, datetime.date):
                result = date_input.strftime("%d-%b-%Y")
                logger.debug(f"[_format_imap_date] date类型格式化结果: {result}")
                return result
            elif isinstance(date_input, str):
                logger.debug(f"[_format_imap_date] 字符串类型，尝试解析: {date_input}")
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
                        result = date_obj.strftime("%d-%b-%Y")
                        logger.debug(f"[_format_imap_date] 使用格式 {fmt} 解析成功，结果: {result}")
                        return result
                    except ValueError:
                        continue
                
                # 如果都不匹配，尝试直接使用
                logger.debug(f"[_format_imap_date] 所有格式解析失败，直接使用原始字符串: {date_input}")
                return date_input
            else:
                logger.warning(f"[_format_imap_date] 不支持的类型: {type(date_input)}")
                return None
        except Exception as e:
            logger.error(f"[_format_imap_date] 格式化日期失败: {date_input}, 错误: {e}")
            return None

    # ---------------- 核心功能 ----------------
    
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
            attachment_path: 附件路径，可选
            html: 是否为HTML格式，默认为False
            cc: 抄送地址，可选
            bcc: 密送地址，可选
            
        Returns:
            Dict: 包含发送结果的字典，包含success、message、error、timestamp等字段
        """
        logger.info(f"[send_email] 开始发送邮件 - 收件人: {to_addr}, 主题: {subject}")
        logger.debug(f"[send_email] 参数 - html: {html}, cc: {cc}, bcc: {bcc}, 附件: {attachment_path}")
        
        result = {
            "success": False,
            "message": "",
            "error": None,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        try:
            # 创建邮件对象
            if attachment_path or cc or bcc:
                logger.debug("[send_email] 创建MIMEMultipart邮件对象")
                msg = MIMEMultipart()
                msg["From"] = self.email_addr
                msg["To"] = to_addr
                msg["Subject"] = subject
                
                if cc:
                    msg["Cc"] = cc
                    logger.debug(f"[send_email] 设置抄送: {cc}")
                    
                if bcc:
                    # BCC不会在邮件头显示
                    logger.debug(f"[send_email] 设置密送: {bcc}")
                    
                # 添加正文
                mime_type = "html" if html else "plain"
                logger.debug(f"[send_email] 添加正文，类型: {mime_type}")
                msg.attach(MIMEText(body, mime_type, "utf-8"))
                
                # 添加附件
                if attachment_path and os.path.exists(attachment_path):
                    logger.info(f"[send_email] 添加附件: {attachment_path}")
                    with open(attachment_path, "rb") as f:
                        filename = os.path.basename(attachment_path)
                        attachment = MIMEApplication(f.read(), Name=filename)
                        attachment["Content-Disposition"] = f'attachment; filename="{filename}"'
                        msg.attach(attachment)
                elif attachment_path:
                    logger.warning(f"[send_email] 附件文件不存在: {attachment_path}")
            else:
                # 简单邮件
                logger.debug("[send_email] 创建简单邮件对象")
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
            
            logger.debug(f"[send_email] 收件人列表: {recipients}")

            # 发送邮件
            logger.info(f"[send_email] 开始发送到SMTP服务器: {self.smtp_host}:{self.smtp_port}")
            
            if self.smtp_ssl:
                logger.debug("[send_email] 使用SMTP_SSL连接")
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    logger.debug("[send_email] 开始登录SMTP服务器")
                    server.login(self.email_addr, self.password)
                    logger.debug("[send_email] SMTP登录成功，开始发送邮件")
                    server.sendmail(self.email_addr, recipients, msg.as_string())
            else:
                logger.debug("[send_email] 使用SMTP+TLS连接")
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    logger.debug("[send_email] TLS已启动，开始登录SMTP服务器")
                    server.login(self.email_addr, self.password)
                    logger.debug("[send_email] SMTP登录成功，开始发送邮件")
                    server.sendmail(self.email_addr, recipients, msg.as_string())

            result["success"] = True
            result["message"] = f"邮件发送成功: {subject}"
            logger.info(f"[send_email] {result['message']}")

        except smtplib.SMTPResponseException as e:
            if e.smtp_code == -1 and e.smtp_error == b'\x00\x00\x00':
                result["success"] = True
                result["message"] = f"邮件可能已成功发送（QQ特殊返回码）: {subject}"
                logger.warning(f"[send_email] {result['message']}")
            else:
                result["error"] = f"SMTP返回异常: {e.smtp_code}, {e.smtp_error}"
                logger.error(f"[send_email] {result['error']}")

        except smtplib.SMTPAuthenticationError as e:
            result["error"] = f"SMTP认证失败: {e}"
            logger.error(f"[send_email] {result['error']}")

        except smtplib.SMTPConnectError as e:
            result["error"] = f"SMTP连接失败: {e}"
            logger.error(f"[send_email] {result['error']}")

        except smtplib.SMTPException as e:
            result["error"] = f"SMTP通用异常: {e}"
            logger.error(f"[send_email] {result['error']}")

        except FileNotFoundError as e:
            result["error"] = f"附件文件未找到: {e}"
            logger.error(f"[send_email] {result['error']}")

        except Exception as e:
            if "b'\\x00\\x00\\x00'" in str(e) or "[-1]" in str(e):
                result["success"] = True
                result["message"] = f"邮件可能已成功发送（捕获非标准返回）: {subject}"
                logger.warning(f"[send_email] {result['message']}")
            else:
                result["error"] = f"邮件发送失败: {e}"
                logger.error(f"[send_email] {result['error']}")

        logger.debug(f"[send_email] 发送结果: {result}")
        return result

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
            years: 最近几年，默认为0
            months: 最近几个月，默认为0
            days: 最近几天，默认为0
            hours: 最近几小时，默认为0
            minutes: 最近几分钟，默认为0
            seconds: 最近几秒，默认为0
            mailbox: 邮箱文件夹，默认为"INBOX"
            limit: 最大返回数量，默认为50
            unread_only: 是否只获取未读邮件，默认为False
            from_filter: 发件人过滤，可选
            subject_filter: 主题过滤，可选
            
        Returns:
            List[Dict[str, Any]]: 邮件详情列表
        """
        logger.info(f"[get_emails_full] 开始获取完整邮件 - 邮箱: {mailbox}, 限制: {limit}, 未读: {unread_only}")
        logger.debug(f"[get_emails_full] 时间参数 - 年: {years}, 月: {months}, 日: {days}, 时: {hours}, 分: {minutes}, 秒: {seconds}")
        logger.debug(f"[get_emails_full] 过滤条件 - 发件人: {from_filter}, 主题: {subject_filter}")
        
        emails = []
        
        try:
            logger.debug(f"[get_emails_full] 确保邮箱已选中: {mailbox}")
            self._ensure_selected(mailbox)
            
            # 构建搜索条件
            criteria_parts = []
            if unread_only:
                criteria_parts.append("UNSEEN")
                logger.debug("[get_emails_full] 添加条件: UNSEEN")
            else:
                criteria_parts.append("ALL")
                logger.debug("[get_emails_full] 添加条件: ALL")
                
            if from_filter:
                criteria_parts.append(f'FROM "{from_filter}"')
                logger.debug(f"[get_emails_full] 添加条件: FROM '{from_filter}'")
            if subject_filter:
                criteria_parts.append(f'SUBJECT "{subject_filter}"')
                logger.debug(f"[get_emails_full] 添加条件: SUBJECT '{subject_filter}'")
                
            # 添加时间条件
            time_criteria = self._build_time_criteria(years, months, days, hours, minutes, seconds)
            if time_criteria != "ALL":
                criteria_parts.append(time_criteria)
                logger.debug(f"[get_emails_full] 添加时间条件: {time_criteria}")
                
            criteria = " ".join(criteria_parts)
            logger.info(f"[get_emails_full] 最终搜索条件: {criteria}")
            
            # 搜索邮件
            logger.debug("[get_emails_full] 执行IMAP搜索")
            result, data = self.conn.search(None, criteria)
            if result != "OK" or not data[0]:
                logger.warning(f"[get_emails_full] 搜索返回异常或为空，结果: {result}, 数据: {data}")
                return emails

            # 获取邮件ID
            ids = data[0].split()
            logger.info(f"[get_emails_full] 找到 {len(ids)} 封邮件")
            
            fetch_ids = ids[-limit:] if limit > 0 else ids
            logger.debug(f"[get_emails_full] 准备获取 {len(fetch_ids)} 封邮件")
            
            current_time = datetime.datetime.now(datetime.timezone.utc)
            logger.debug(f"[get_emails_full] 当前时间: {current_time}")
            
            for i, msg_id in enumerate(reversed(fetch_ids), 1):  # 从最新开始
                msg_id_str = msg_id.decode('utf-8', errors='ignore')
                logger.debug(f"[get_emails_full] 处理第{i}/{len(fetch_ids)}封邮件，ID: {msg_id_str}")
                
                try:
                    res, msg_data = self.conn.fetch(msg_id, "(RFC822)")
                    if res != "OK" or not msg_data or not msg_data[0]:
                        logger.warning(f"[get_emails_full] 获取邮件 {msg_id_str} 失败，结果: {res}")
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
                                    logger.debug(f"[get_emails_full] 邮件 {msg_id_str} 时间超出范围，跳过")
                                    continue
                                    
                                logger.debug(f"[get_emails_full] 邮件 {msg_id_str} 时间在范围内，继续处理")
                        except Exception as e:
                            logger.warning(f"[get_emails_full] 解析邮件 {msg_id_str} 日期失败: {e}")
                            # 日期解析失败，继续处理这封邮件
                            pass
                    
                    # 解析邮件详情
                    email_details = self._parse_email_details(msg, msg_id_str)
                    if email_details:
                        emails.append(email_details)
                        logger.debug(f"[get_emails_full] 邮件 {msg_id_str} 解析成功，已添加到结果列表")
                        
                except Exception as e:
                    logger.error(f"[get_emails_full] 获取邮件 {msg_id_str} 失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[get_emails_full] 获取完整邮件失败: {e}")
            
        logger.info(f"[get_emails_full] 获取完成，共找到 {len(emails)} 封邮件")
        return emails

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
            years: 最近几年，默认为0
            months: 最近几个月，默认为0
            days: 最近几天，默认为0
            hours: 最近几小时，默认为0
            minutes: 最近几分钟，默认为0
            seconds: 最近几秒，默认为0
            mailbox: 邮箱文件夹，默认为"INBOX"
            limit: 最大返回数量，默认为20
            unread_only: 是否只获取未读邮件，默认为False
            include_body_preview: 是否包含正文预览，默认为False
            body_preview_length: 正文预览长度，默认为200
            
        Returns:
            List[Dict[str, Any]]: 邮件摘要列表
        """
        logger.info(f"[get_emails_summary] 开始获取邮件摘要 - 邮箱: {mailbox}, 限制: {limit}, 未读: {unread_only}")
        logger.debug(f"[get_emails_summary] 参数 - 预览: {include_body_preview}, 预览长度: {body_preview_length}")
        
        summaries = []
        
        try:
            logger.debug(f"[get_emails_summary] 确保邮箱已选中: {mailbox}")
            self._ensure_selected(mailbox)
            
            # 构建搜索条件
            criteria_parts = ["UNSEEN" if unread_only else "ALL"]
            logger.debug(f"[get_emails_summary] 添加条件: {criteria_parts[0]}")
            
            time_criteria = self._build_time_criteria(years, months, days, hours, minutes, seconds)
            if time_criteria != "ALL":
                criteria_parts.append(time_criteria)
                logger.debug(f"[get_emails_summary] 添加时间条件: {time_criteria}")
                
            criteria = " ".join(criteria_parts)
            logger.info(f"[get_emails_summary] 最终搜索条件: {criteria}")
            
            # 搜索邮件
            logger.debug("[get_emails_summary] 执行IMAP搜索")
            result, data = self.conn.search(None, criteria)
            if result != "OK" or not data[0]:
                logger.warning(f"[get_emails_summary] 搜索返回异常或为空，结果: {result}, 数据: {data}")
                return summaries

            # 获取邮件ID
            ids = data[0].split()
            logger.info(f"[get_emails_summary] 找到 {len(ids)} 封邮件")
            
            fetch_ids = ids[-limit:] if limit > 0 else ids
            logger.debug(f"[get_emails_summary] 准备获取 {len(fetch_ids)} 封邮件摘要")
            
            current_time = datetime.datetime.now(datetime.timezone.utc)
            logger.debug(f"[get_emails_summary] 当前时间: {current_time}")
            
            for i, msg_id in enumerate(reversed(fetch_ids), 1):
                msg_id_str = msg_id.decode('utf-8', errors='ignore')
                logger.debug(f"[get_emails_summary] 处理第{i}/{len(fetch_ids)}封邮件，ID: {msg_id_str}")
                
                try:
                    res, msg_data = self.conn.fetch(msg_id, "(BODY.PEEK[HEADER] RFC822.SIZE)")
                    if res != "OK" or not msg_data or not msg_data[0]:
                        logger.warning(f"[get_emails_summary] 获取邮件 {msg_id_str} 摘要失败，结果: {res}")
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
                                    size_match = re.search(r'\d+', size_str)
                                    if size_match:
                                        size = int(size_match.group())
                                        logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 大小: {size} bytes")
                                except Exception as e:
                                    logger.debug(f"[get_emails_summary] 解析邮件 {msg_id_str} 大小失败: {e}")
                    
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
                                    logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 时间超出范围，跳过")
                                    continue
                                    
                                logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 时间在范围内，继续处理")
                        except Exception as e:
                            logger.warning(f"[get_emails_summary] 解析邮件 {msg_id_str} 日期失败: {e}")
                            # 日期解析失败，继续处理这封邮件
                            pass
                    
                    # 提取摘要信息
                    subject = self._decode_header(msg.get("Subject", ""))
                    from_ = self._decode_header(msg.get("From", ""))
                    to_ = self._decode_header(msg.get("To", ""))
                    
                    summary = {
                        "id": msg_id_str,
                        "subject": subject,
                        "from": from_,
                        "to": to_,
                        "date": email_date,
                        "size": size,
                        "has_attachments": False,  # 摘要模式不检查附件
                        "is_unread": unread_only
                    }
                    
                    logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 摘要 - 主题: {subject[:50]}..., 发件人: {from_}")
                    
                    # 如果需要正文预览，获取更多内容
                    if include_body_preview:
                        logger.debug(f"[get_emails_summary] 获取邮件 {msg_id_str} 正文预览")
                        try:
                            res_body, msg_body_data = self.conn.fetch(msg_id, "(BODY.PEEK[TEXT])")
                            if res_body == "OK" and msg_body_data[0]:
                                body_text = ""
                                if isinstance(msg_body_data[0][1], bytes):
                                    body_text = msg_body_data[0][1].decode('utf-8', errors='ignore')
                                
                                preview_text = body_text[:body_preview_length] + "..." if len(body_text) > body_preview_length else body_text
                                summary["body_preview"] = preview_text
                                logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 预览获取成功，长度: {len(preview_text)}")
                            else:
                                summary["body_preview"] = ""
                                logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 预览获取失败")
                        except Exception as e:
                            summary["body_preview"] = ""
                            logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 预览获取异常: {e}")
                    
                    summaries.append(summary)
                    logger.debug(f"[get_emails_summary] 邮件 {msg_id_str} 摘要已添加到结果列表")
                    
                except Exception as e:
                    logger.error(f"[get_emails_summary] 获取邮件摘要 {msg_id_str} 失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[get_emails_summary] 获取邮件摘要失败: {e}")
            
        logger.info(f"[get_emails_summary] 获取完成，共找到 {len(summaries)} 封邮件摘要")
        return summaries

    def query_email(
        self,
        search_criteria: Dict[str, Any],
        mailbox: str = "INBOX",
        get_full_content: bool = True,
        strict_mode: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        查询邮件（服务器粗筛选 + 本地精筛选）

        设计目标：
        1. 服务器端（IMAP SEARCH）只做"稳定、ASCII 安全"的粗筛选
           - UNSEEN / ALL
           - SINCE / BEFORE
           - FROM / TO
        2. 本地 Python 负责：
           - Subject 中文匹配
           - Body 内容匹配
           - AND / OR（strict_mode）
        3. 根据是否需要 body，智能选择 FETCH HEADER 或 FULL，避免性能浪费

        Args:
            search_criteria: 查询条件字典，包含以下可选字段：
                {
                    "subject": str | None,      # 本地匹配（支持中文）
                    "body": str | None,         # 本地匹配（需要全文）
                    "from": str | None,         # 服务器筛选
                    "to": str | None,           # 服务器筛选
                    "is_unread": bool | None,   # 是否只查未读
                    "after_date": datetime | date | str | None,  # 开始日期
                    "before_date": datetime | date | str | None, # 结束日期
                }
            mailbox: 邮箱名，默认为 "INBOX"
            get_full_content: 是否返回完整邮件内容，默认为 True
            strict_mode: 匹配模式，默认为 True
                True -> 所有本地条件必须命中（AND）
                False -> 任意条件命中即可（OR）

        Returns:
            List[Dict[str, Any]]: 匹配的邮件列表，每一项为一封解析后的邮件
        """

        results: List[Dict[str, Any]] = []

        logger.info(
            "[query_email] 开始查询邮件 - 邮箱: %s, 严格模式: %s, 获取完整内容: %s",
            mailbox, strict_mode, get_full_content
        )
        logger.debug("[query_email] 查询条件: %s", search_criteria)

        try:
            # -------------------------------------------------
            # 0️⃣ 确保邮箱已选中
            # -------------------------------------------------
            logger.debug("[query_email] 步骤0: 确保邮箱已选中")
            self._ensure_selected(mailbox)
            logger.debug("[query_email] 邮箱已选中，准备构建搜索条件")

            # -------------------------------------------------
            # 1️⃣ 构造服务器端"粗筛选"条件
            # -------------------------------------------------
            logger.info("[query_email] 步骤1: 构建服务器端筛选条件")
            criteria_parts = []

            # 是否未读
            is_unread = search_criteria.get("is_unread")
            if is_unread:
                criteria_parts.append("UNSEEN")
                logger.debug("[query_email] 添加条件: UNSEEN (只查询未读邮件)")
            else:
                criteria_parts.append("ALL")
                logger.debug("[query_email] 添加条件: ALL (查询所有邮件)")

            # 起始日期
            after_date = search_criteria.get("after_date")
            if after_date:
                date_str = self._format_imap_date(after_date)
                if date_str:
                    criteria_parts.append(f"SINCE {date_str}")
                    logger.debug("[query_email] 添加条件: SINCE %s (开始日期)", date_str)
                else:
                    logger.warning("[query_email] after_date 格式化失败: %s", after_date)

            # 结束日期
            before_date = search_criteria.get("before_date")
            if before_date:
                date_str = self._format_imap_date(before_date)
                if date_str:
                    criteria_parts.append(f"BEFORE {date_str}")
                    logger.debug("[query_email] 添加条件: BEFORE %s (结束日期)", date_str)
                else:
                    logger.warning("[query_email] before_date 格式化失败: %s", before_date)

            # FROM / TO（ASCII 安全）
            from_addr = search_criteria.get("from")
            if from_addr:
                criteria_parts.append(f'FROM "{from_addr}"')
                logger.debug("[query_email] 添加条件: FROM '%s' (发件人)", from_addr)

            to_addr = search_criteria.get("to")
            if to_addr:
                criteria_parts.append(f'TO "{to_addr}"')
                logger.debug("[query_email] 添加条件: TO '%s' (收件人)", to_addr)

            criteria = " ".join(criteria_parts) if criteria_parts else "ALL"
            logger.info("[query_email] 服务器端筛选条件: %s", criteria)

            # -------------------------------------------------
            # 2️⃣ 执行服务器搜索
            # -------------------------------------------------
            logger.info("[query_email] 步骤2: 执行服务器搜索")
            res, data = self.conn.search(None, criteria)
            if res != "OK":
                logger.warning("[query_email] 服务器搜索失败: %s", res)
                return results

            if not data or not data[0]:
                logger.info("[query_email] 服务器搜索命中 0 封邮件")
                return results

            ids = data[0].split()
            logger.info("[query_email] 服务器搜索命中 %d 封邮件", len(ids))

            # -------------------------------------------------
            # 3️⃣ 本地精筛参数
            # -------------------------------------------------
            logger.info("[query_email] 步骤3: 设置本地精筛参数")
            subject_kw: Optional[str] = search_criteria.get("subject")
            body_kw: Optional[str] = search_criteria.get("body")

            # 确定是否需要获取正文
            need_body = bool(body_kw) or get_full_content
            fetch_items = "(RFC822)" if need_body else "(BODY.PEEK[HEADER])"
            
            logger.debug(
                "[query_email] 本地筛选参数 - 主题关键词: %s, 正文关键词: %s, 获取内容: %s",
                subject_kw, body_kw, fetch_items
            )
            logger.debug("[query_email] 需要正文: %s (原因: 正文关键词=%s, 获取完整内容=%s)", 
                        need_body, bool(body_kw), get_full_content)

            # -------------------------------------------------
            # 4️⃣ 遍历邮件，进行本地精筛选
            # -------------------------------------------------
            logger.info("[query_email] 步骤4: 开始本地精筛选，处理 %d 封邮件", len(ids))
            
            # 反转ID列表，从最新邮件开始处理
            reversed_ids = list(reversed(ids))
            
            for index, msg_id in enumerate(reversed_ids, start=1):
                msg_id_str = msg_id.decode(errors="ignore")
                logger.debug("[query_email] 处理第 %d/%d 封邮件，ID: %s", 
                           index, len(reversed_ids), msg_id_str)

                try:
                    # 获取邮件数据
                    logger.debug("[query_email] 邮件 %s: 开始获取邮件数据", msg_id_str)
                    res, msg_data = self.conn.fetch(msg_id, fetch_items)
                    if res != "OK" or not msg_data:
                        logger.warning("[query_email] 邮件 %s: 获取邮件数据失败，结果: %s", msg_id_str, res)
                        continue

                    msg = email.message_from_bytes(msg_data[0][1])
                    logger.debug("[query_email] 邮件 %s: 邮件解析成功", msg_id_str)

                    match_flags = []
                    match_details = []

                    # ---------- Subject 匹配 ----------
                    if subject_kw:
                        subject = self._decode_header(msg.get("Subject", ""))
                        hit = subject_kw.lower() in subject.lower()
                        match_flags.append(hit)
                        match_details.append(f"主题匹配: {hit}")
                        logger.debug(
                            "[query_email] 邮件 %s: 主题='%s', 关键词='%s', 匹配=%s",
                            msg_id_str, subject[:50], subject_kw, hit
                        )

                    # ---------- Body 匹配 ----------
                    if body_kw:
                        body = self._extract_body(msg)
                        hit = body_kw.lower() in body.lower()
                        match_flags.append(hit)
                        match_details.append(f"正文匹配: {hit}")
                        logger.debug(
                            "[query_email] 邮件 %s: 正文长度=%d, 关键词='%s', 匹配=%s",
                            msg_id_str, len(body), body_kw, hit
                        )

                    # ---------- 应用匹配模式 ----------
                    should_include = False
                    if match_flags:
                        if strict_mode:
                            # AND 模式：所有条件都必须满足
                            should_include = all(match_flags)
                            logger.debug("[query_email] 邮件 %s: 严格模式，所有匹配=%s, 结果=%s", 
                                       msg_id_str, match_flags, should_include)
                        else:
                            # OR 模式：任意条件满足即可
                            should_include = any(match_flags)
                            logger.debug("[query_email] 邮件 %s: 宽松模式，任意匹配=%s, 结果=%s", 
                                       msg_id_str, match_flags, should_include)
                    else:
                        # 没有本地筛选条件，直接包含
                        should_include = True
                        logger.debug("[query_email] 邮件 %s: 无本地筛选条件，直接包含", msg_id_str)

                    # ---------- 处理匹配的邮件 ----------
                    if should_include:
                        if get_full_content and not need_body:
                            # 如果之前只获取了header，现在需要获取完整内容
                            logger.debug("[query_email] 邮件 %s: 需要完整内容，重新获取", msg_id_str)
                            res_full, msg_data_full = self.conn.fetch(msg_id, "(RFC822)")
                            if res_full == "OK" and msg_data_full[0]:
                                msg = email.message_from_bytes(msg_data_full[0][1])
                        
                        email_details = self._parse_email_details(msg, msg_id_str)
                        if email_details:
                            # 添加匹配信息
                            email_details["match_info"] = {
                                "strict_mode": strict_mode,
                                "matched_conditions": match_details,
                                "all_matched": all(match_flags) if match_flags else True,
                                "any_matched": any(match_flags) if match_flags else True
                            }
                            results.append(email_details)
                            logger.info("[query_email] 邮件 %s: 匹配成功，已添加到结果列表", msg_id_str)
                        else:
                            logger.warning("[query_email] 邮件 %s: 解析失败，跳过", msg_id_str)
                    else:
                        logger.debug("[query_email] 邮件 %s: 未匹配，跳过", msg_id_str)

                except Exception as e:
                    logger.error(
                        "[query_email] 邮件 %s: 处理异常: %s",
                        msg_id_str, e, exc_info=True
                    )
                    continue

        except Exception as e:
            logger.error("[query_email] 查询过程发生致命错误: %s", e, exc_info=True)

        logger.info(
            "[query_email] 查询完成，共匹配 %d 封邮件",
            len(results)
        )
        return results

    # ---------------- 删除邮件方法 ----------------    
    def delete_emails(
        self,
        email_ids: List[str],
        permanent: bool = False,
        mailbox: str = "INBOX"
    ) -> Dict[str, Any]:
        """
        删除指定邮件（支持软删除和永久删除）
        
        Args:
            email_ids: 邮件ID列表
            permanent: True为永久删除（直接删除），False为移动到垃圾箱/已删除邮件，默认为False
            mailbox: 当前邮箱文件夹，默认为"INBOX"
            
        Returns:
            Dict[str, Any]: 删除结果，包含success、message、deleted_count、failed_ids等字段
        """
        logger.info(f"[delete_emails] 开始删除邮件 - 邮箱: {mailbox}, 永久删除: {permanent}, 邮件数量: {len(email_ids)}")
        
        result = {
            "success": False,
            "message": "",
            "deleted_count": 0,
            "failed_ids": [],
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        try:
            self._ensure_selected(mailbox)
            logger.debug("[delete_emails] 邮箱已选中，开始处理邮件ID")
            
            # 转换邮件ID为字节格式
            byte_ids = []
            for email_id in email_ids:
                try:
                    if isinstance(email_id, str):
                        byte_id = email_id.encode('utf-8')
                    elif isinstance(email_id, bytes):
                        byte_id = email_id
                    else:
                        byte_id = str(email_id).encode('utf-8')
                    
                    byte_ids.append(byte_id)
                    logger.debug("[delete_emails] 转换邮件ID: %s -> %s", email_id, byte_id)
                except Exception as e:
                    logger.warning("[delete_emails] 转换邮件ID失败: %s, 错误: %s", email_id, e)
                    result["failed_ids"].append(str(email_id))
            
            if not byte_ids:
                result["message"] = "没有有效的邮件ID"
                logger.warning("[delete_emails] " + result["message"])
                return result
            
            if permanent:
                # 永久删除
                logger.info("[delete_emails] 执行永久删除")
                try:
                    # 标记为删除
                    for email_id in byte_ids:
                        try:
                            email_id_str = email_id.decode('utf-8', errors='ignore')
                            logger.debug("[delete_emails] 标记邮件 %s 为删除", email_id_str)
                            typ, data = self.conn.store(email_id, '+FLAGS', r'(\Deleted)')
                            if typ == "OK":
                                result["deleted_count"] += 1
                                logger.debug("[delete_emails] 邮件 %s 标记成功", email_id_str)
                            else:
                                result["failed_ids"].append(email_id_str)
                                logger.warning("[delete_emails] 邮件 %s 标记失败: %s", email_id_str, data)
                        except Exception as e:
                            email_id_str = email_id.decode('utf-8', errors='ignore')
                            logger.error("[delete_emails] 标记邮件 %s 为删除失败: %s", email_id_str, e)
                            result["failed_ids"].append(email_id_str)
                    
                    # 执行删除
                    logger.debug("[delete_emails] 执行删除操作")
                    try:
                        typ, data = self.conn.expunge()
                        if typ == "OK":
                            result["success"] = True
                            result["message"] = f"已永久删除 {result['deleted_count']} 封邮件"
                            logger.info("[delete_emails] " + result['message'])
                        else:
                            result["message"] = f"删除执行失败: {data}"
                            logger.error("[delete_emails] " + result['message'])
                    except Exception as e:
                        logger.error("[delete_emails] 执行删除失败: %s", e)
                        result["message"] = f"执行删除失败: {e}"
                        
                except Exception as e:
                    logger.error("[delete_emails] 永久删除邮件失败: %s", e)
                    result["message"] = f"永久删除失败: {e}"
                    
            else:
                # 软删除：移动到垃圾箱/已删除邮件
                logger.info("[delete_emails] 执行软删除（移动到垃圾箱）")
                try:
                    # 检查目标文件夹是否存在
                    trash_folders = ["Trash", "Deleted", "垃圾邮件", "已删除邮件", "Deleted Items"]
                    target_mailbox = None
                    
                    # 列出所有邮箱文件夹
                    logger.debug("[delete_emails] 查找垃圾箱文件夹")
                    typ, data = self.conn.list()
                    if typ == "OK":
                        existing_folders = []
                        for folder_info in data:
                            folder_str = folder_info.decode('utf-8', errors='ignore')
                            # 提取文件夹名称
                            match = re.search(r'\"([^\"]+)\"', folder_str)
                            if match:
                                folder_name = match.group(1)
                                existing_folders.append(folder_name)
                        
                        logger.debug("[delete_emails] 现有文件夹: %s", existing_folders)
                        
                        # 查找合适的垃圾箱文件夹
                        for trash_name in trash_folders:
                            if trash_name in existing_folders:
                                target_mailbox = trash_name
                                logger.info("[delete_emails] 找到垃圾箱文件夹: %s", target_mailbox)
                                break
                    
                    if target_mailbox:
                        # 复制到目标文件夹
                        logger.debug("[delete_emails] 开始移动邮件到 %s", target_mailbox)
                        for email_id in byte_ids:
                            email_id_str = email_id.decode('utf-8', errors='ignore')
                            try:
                                logger.debug("[delete_emails] 复制邮件 %s 到 %s", email_id_str, target_mailbox)
                                typ, data = self.conn.copy(email_id, target_mailbox)
                                if typ == "OK":
                                    # 标记为删除（从原文件夹移除）
                                    logger.debug("[delete_emails] 标记邮件 %s 为删除", email_id_str)
                                    typ2, data2 = self.conn.store(email_id, '+FLAGS', r'(\Deleted)')
                                    if typ2 == "OK":
                                        result["deleted_count"] += 1
                                        logger.debug("[delete_emails] 邮件 %s 处理成功", email_id_str)
                                    else:
                                        result["failed_ids"].append(email_id_str)
                                        logger.warning("[delete_emails] 邮件 %s 标记删除失败: %s", email_id_str, data2)
                                else:
                                    result["failed_ids"].append(email_id_str)
                                    logger.warning("[delete_emails] 邮件 %s 复制失败: %s", email_id_str, data)
                            except Exception as e:
                                logger.error("[delete_emails] 移动邮件 %s 失败: %s", email_id_str, e)
                                result["failed_ids"].append(email_id_str)
                        
                        # 执行删除（从原文件夹移除）
                        logger.debug("[delete_emails] 执行删除操作")
                        typ, data = self.conn.expunge()
                        if typ == "OK":
                            result["success"] = True
                            result["message"] = f"已移动 {result['deleted_count']} 封邮件到 {target_mailbox}"
                            logger.info("[delete_emails] " + result['message'])
                        else:
                            result["message"] = f"移动邮件执行失败: {data}"
                            logger.error("[delete_emails] " + result['message'])
                    else:
                        # 如果没有找到垃圾箱，使用永久删除
                        logger.warning("[delete_emails] 未找到垃圾箱文件夹，使用永久删除")
                        return self.delete_emails(email_ids, permanent=True, mailbox=mailbox)
                        
                except Exception as e:
                    logger.error("[delete_emails] 移动邮件到垃圾箱失败: %s", e)
                    result["message"] = f"移动邮件失败: {e}"
            
        except Exception as e:
            logger.error("[delete_emails] 删除邮件过程中发生错误: %s", e)
            result["message"] = f"删除邮件失败: {e}"
        
        logger.debug("[delete_emails] 删除结果: %s", result)
        return result

    def delete_emails_by_criteria(
        self,
        criteria: Dict[str, Any],
        permanent: bool = False,
        mailbox: str = "INBOX",
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        根据条件删除邮件（先查询后删除）
        
        Args:
            criteria: 查询条件（与query_email兼容）
            permanent: True为永久删除，False为移动到垃圾箱，默认为False
            mailbox: 当前邮箱文件夹，默认为"INBOX"
            limit: 最大删除数量，默认为100
            
        Returns:
            Dict[str, Any]: 删除结果，包含success、message、total_found、deleted_count等字段
        """
        logger.info(f"[delete_emails_by_criteria] 开始根据条件删除邮件 - 邮箱: {mailbox}, 永久删除: {permanent}, 限制: {limit}")
        logger.debug("[delete_emails_by_criteria] 查询条件: %s", criteria)
        
        result = {
            "success": False,
            "message": "",
            "total_found": 0,
            "deleted_count": 0,
            "failed_count": 0,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        try:
            # 先查询符合条件的邮件
            logger.debug("[delete_emails_by_criteria] 先查询符合条件的邮件")
            matching_emails = self.query_email(
                search_criteria=criteria,
                mailbox=mailbox,
                get_full_content=False
            )
            
            result["total_found"] = len(matching_emails)
            logger.info("[delete_emails_by_criteria] 找到 %d 封符合条件的邮件", result["total_found"])
            
            if not matching_emails:
                result["message"] = "未找到符合条件的邮件"
                result["success"] = True
                logger.info("[delete_emails_by_criteria] " + result["message"])
                return result
            
            # 提取邮件ID
            email_ids = [email["id"] for email in matching_emails[:limit]]
            logger.debug("[delete_emails_by_criteria] 提取前 %d 封邮件的ID", len(email_ids))
            
            # 调用删除方法
            logger.debug("[delete_emails_by_criteria] 调用delete_emails方法")
            delete_result = self.delete_emails(
                email_ids=email_ids,
                permanent=permanent,
                mailbox=mailbox
            )
            
            # 合并结果
            result.update({
                "success": delete_result["success"],
                "message": delete_result["message"],
                "deleted_count": delete_result["deleted_count"],
                "failed_count": len(delete_result["failed_ids"])
            })
            
            logger.info("[delete_emails_by_criteria] 删除完成，成功: %d, 失败: %d", 
                       result["deleted_count"], result["failed_count"])
            
        except Exception as e:
            logger.error("[delete_emails_by_criteria] 根据条件删除邮件失败: %s", e)
            result["message"] = f"根据条件删除失败: {e}"
        
        return result

    # ---------------- 额外辅助方法 ----------------
    
    def mark_as_read(self, email_ids: List[str]) -> bool:
        """
        标记邮件为已读
        
        Args:
            email_ids: 邮件ID列表
            
        Returns:
            bool: 操作是否成功
        """
        logger.info(f"[mark_as_read] 开始标记邮件为已读，数量: {len(email_ids)}")
        
        try:
            self._ensure_selected()
            logger.debug("[mark_as_read] 邮箱已选中，开始标记")
            
            for email_id in email_ids:
                try:
                    email_id_bytes = email_id.encode() if isinstance(email_id, str) else email_id
                    logger.debug("[mark_as_read] 标记邮件 %s 为已读", email_id)
                    self.conn.store(email_id_bytes, '+FLAGS', r'(\Seen)')
                except Exception as e:
                    logger.error("[mark_as_read] 标记邮件 %s 为已读失败: %s", email_id, e)
                    # 继续处理其他邮件
            
            logger.info("[mark_as_read] 标记完成")
            return True
            
        except Exception as e:
            logger.error("[mark_as_read] 标记已读失败: %s", e)
            return False
    
    def move_emails(self, email_ids: List[str], target_mailbox: str) -> bool:
        """
        移动邮件到指定文件夹
        
        Args:
            email_ids: 邮件ID列表
            target_mailbox: 目标邮箱文件夹
            
        Returns:
            bool: 操作是否成功
        """
        logger.info(f"[move_emails] 开始移动邮件到 {target_mailbox}，数量: {len(email_ids)}")
        
        try:
            self._ensure_selected()
            logger.debug("[move_emails] 邮箱已选中，开始移动")
            
            for email_id in email_ids:
                try:
                    email_id_bytes = email_id.encode() if isinstance(email_id, str) else email_id
                    logger.debug("[move_emails] 移动邮件 %s 到 %s", email_id, target_mailbox)
                    
                    # 复制到目标文件夹
                    self.conn.copy(email_id_bytes, target_mailbox)
                    
                    # 标记为删除（从原文件夹移除）
                    self.conn.store(email_id_bytes, '+FLAGS', r'(\Deleted)')
                    
                except Exception as e:
                    logger.error("[move_emails] 移动邮件 %s 失败: %s", email_id, e)
                    # 继续处理其他邮件
            
            # 执行删除操作
            logger.debug("[move_emails] 执行删除操作（从原文件夹移除）")
            self.conn.expunge()
            
            logger.info("[move_emails] 移动完成")
            return True
            
        except Exception as e:
            logger.error("[move_emails] 移动邮件失败: %s", e)
            return False
    
    def get_mailbox_info(self) -> Dict[str, Any]:
        """
        获取邮箱信息
        
        Returns:
            Dict[str, Any]: 邮箱信息，包含邮件总数、未读数等
        """
        logger.info("[get_mailbox_info] 开始获取邮箱信息")
        
        try:
            self._ensure_selected()
            logger.debug("[get_mailbox_info] 邮箱已选中，获取状态")
            
            # 获取邮箱状态
            typ, data = self.conn.status("INBOX", "(MESSAGES UNSEEN RECENT)")
            if typ == "OK":
                info = {}
                status_str = data[0].decode()
                logger.debug("[get_mailbox_info] 状态字符串: %s", status_str)
                
                for item in status_str.split():
                    if '=' in item:
                        key, value = item.split('=')
                        clean_key = key.strip('()')
                        clean_value = value.strip('"')
                        info[clean_key] = int(clean_value)
                        logger.debug("[get_mailbox_info] %s: %s", clean_key, clean_value)
                
                logger.info("[get_mailbox_info] 获取成功，邮件总数: %d, 未读: %d", 
                          info.get('MESSAGES', 0), info.get('UNSEEN', 0))
                return info
            else:
                logger.warning("[get_mailbox_info] 获取状态失败: %s", data)
                return {}
                
        except Exception as e:
            logger.error("[get_mailbox_info] 获取邮箱信息失败: %s", e)
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
            "subject": "礼品码",
            "after_date": datetime.datetime(2025, 12, 1),
        },
        get_full_content=False,
        strict_mode=True)
        
        print(f"查询到 {len(query_results)} 封邮件")
        print("详情：")
        for email in query_results:
            print(f"主题: {email['subject']}")
            print(f"ID: {email['id']}")
            print(f"发件人: {email['from']}")
            print(f"收件人: {email['to']}")
            print(f"时间: {email['date']}")
            print("-" * 50)

        client.logout()

    except Exception as e:
        print(f"[!] 测试过程中出现错误: {e}")