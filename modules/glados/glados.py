import time
import requests
import re
import yagmail
from imapclient import IMAPClient
import mailparser
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.notify import ql_notify
from common.logger import logger
from modules.glados.config.config import Config




class GladosClient:
    def __init__(self, rv_cfg: Config):
        self.cfg = rv_cfg
        
        
        gl_cfg = self.cfg.glados
        # self.accounts = gl_cfg.get("accounts", [])
        # self.threshold = gl_cfg.get("threshold", 999999.0)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        self.imap_client = None
        self.smtp_client = None
        
        # # 邮箱客户端
        # email_cfg = self.cfg.email
        # self.notify_email = email_cfg.get("notify_address", "")
        # self.mail_client = MailBoxClient(
        #     email_addr=email_cfg["address"],
        #     password=email_cfg["password"],
        #     provider=email_cfg["provider"],
        #     ssl=email_cfg.get("ssl", True)
        # )

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _set_session_cookies(self, cookies: Dict[str, str]):
        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    def _cookie_login_ok(self) -> bool:
        try:
            status_url = self.cfg.glados.status_url
            r = self.session.get(status_url, timeout=10)
            j = r.json()
            return j.get("code") == 0
        except Exception:
            return False

    def _update_account(self, idx: int, 
                        cookies: Optional[Dict[str, str]] = None,
                        balance: Optional[float] = None,
                        left_days: Optional[int] = None,
                        expire_at: Optional[str] = None,
                        traffic: Optional[int] = None,
                        total_traffic: Optional[int] = None,
                        username: Optional[str] = None,
                        name: Optional[str] = None) -> None:
        """
        更新指定索引的账户信息，只更新传入的非空参数
        
        Args:
            idx: 账户索引
            cookies: 可选，新的cookies字典
            balance: 可选，新的余额
            left_days: 可选，新的剩余天数
            expire_at: 可选，新的过期时间
            traffic: 可选，新的已用流量
            total_traffic: 可选，新的总流量
            username: 可选，新的用户名
            name: 可选，新的账户名称
        """
        if idx < 0 or idx >= len(self.cfg.accounts):
            raise IndexError(f"账户索引 {idx} 超出范围")
        
        account = self.cfg.accounts[idx]
        
        # 只更新传入的非空参数
        if cookies is not None:
            account.cookies = cookies
        
        if balance is not None:
            account.balance = balance
        
        if left_days is not None:
            account.leftDays = left_days
        
        if expire_at is not None:
            account.expireAt = expire_at
        
        if traffic is not None:
            account.traffic = traffic
        
        if total_traffic is not None:
            account.total_traffic = total_traffic
        
        if username is not None:
            account.username = username
        
        if name is not None:
            account.name = name
        
        self.cfg.save()

    # -------------------------------
    # 邮件验证码相关方法
    # -------------------------------
    def _setup_imap_client(self) -> Optional[IMAPClient]:
        """设置并登录邮件客户端"""
        if self.imap_client is not None:
            return self.imap_client

        try:
            # 从配置中获取邮件设置
            mail_cfg = self.cfg.email  # 假设配置中有mail部分
            
            client = IMAPClient(mail_cfg.imap_server, port=mail_cfg.imap_port, ssl=True)
            client.login(mail_cfg.username, mail_cfg.password)
            client.select_folder('INBOX', readonly=True)
            
            logger.info("[+] 邮件imap客户端登录成功")
            return client
        except Exception as e:
            logger.error(f"[!] 邮件imap客户端登录失败: {e}")
            return None
    
    def _setup_smtp_client(self) -> Optional[yagmail.SMTP]:
        """初始化并登录 SMTP 客户端（yagmail）"""
        if self.smtp_client:
            return self.smtp_client

        try:
            email_cfg = self.cfg.email

            self.smtp_client = yagmail.SMTP(
                user=email_cfg.username,
                password=email_cfg.password,   # 注意：这里是 SMTP 授权码
                host=email_cfg.smtp_server,
                port=email_cfg.smtp_port,
                smtp_ssl=True
            )

            logger.info("[+] SMTP 客户端登录成功")
            return self.smtp_client

        except Exception as e:
            logger.error(f"[!] SMTP 客户端登录失败: {e}", exc_info=True)
            self.smtp_client = None
            return None
        
    def _search_verification_email(
        self,
        client: IMAPClient,
        email_address: str,
        search_minutes: int = 5
    ) -> Tuple[Optional[bytes], Optional[int]]:
        """
        搜索验证码邮件（调试增强版）
        """
        try:
            import datetime

            logger.debug("[*] ===== 开始搜索验证码邮件 =====")
            logger.debug(f"[*] 目标邮箱: {email_address}")
            logger.debug(f"[*] 搜索时间范围: 最近 {search_minutes} 分钟")

            # 计算搜索时间
            now = datetime.datetime.now()
            since_time = now - datetime.timedelta(minutes=search_minutes)
            since_date = since_time.strftime("%d-%b-%Y")

            logger.debug(f"[*] 当前时间: {now}")
            logger.debug(f"[*] SINCE 日期(IMAP): {since_date}")

            # 搜索条件
            search_criteria = [
                'SUBJECT', 'GLaDOS Authentication',
                'SINCE', since_date
            ]
            logger.debug(f"[*] IMAP 搜索条件: {search_criteria}")

            # 执行搜索
            messages = client.search(search_criteria)
            logger.debug(f"[*] IMAP search 返回 UID 列表: {messages}")

            if not messages:
                logger.warning(f"[!] 未搜索到任何符合条件的邮件")
                return None, None

            # 按 UID 倒序（通常最新的 UID 最大）
            messages = sorted(messages, reverse=True)
            logger.debug(f"[*] 排序后的 UID 列表(倒序): {messages}")

            for idx, uid in enumerate(messages, start=1):
                logger.debug(f"[*] 正在处理第 {idx}/{len(messages)} 封邮件, UID={uid}")

                msg_data = client.fetch([uid], ['RFC822', 'ENVELOPE'])
                logger.debug(f"[*] fetch 返回 keys: {list(msg_data.keys())}")

                if uid not in msg_data:
                    logger.warning(f"[!] UID {uid} 不在 fetch 结果中，跳过")
                    continue

                raw_message = msg_data[uid].get(b'RFC822')
                envelope = msg_data[uid].get(b'ENVELOPE')

                if not raw_message:
                    logger.warning(f"[!] UID {uid} 没有 RFC822 数据，跳过")
                    continue

                logger.debug(f"[*] UID {uid} 邮件大小: {len(raw_message)} bytes")

                # 解析邮件
                mail = mailparser.parse_from_bytes(raw_message)

                logger.debug(
                    f"[*] UID {uid} 邮件信息: "
                    f"from={mail.from_}, "
                    f"to={mail.to}, "
                    f"subject={mail.subject}, "
                    f"date={mail.date}"
                )

                # 收件人匹配检查
                if not mail.to:
                    logger.warning(f"[!] UID {uid} mail.to 为空")
                    continue

                if any(
                    addr.lower() == email_address.lower()
                    for _, addr in mail.to or []
                ):
                    logger.info(f"[+] ✅ 找到 {email_address} 的验证码邮件 (UID={uid})")
                    return raw_message, uid
                else:
                    logger.debug(
                        f"[-] UID {uid} 收件人不匹配，期望={email_address}"
                    )

            logger.warning("[!] 搜索完成，但未找到匹配收件人的验证码邮件")
            return None, None

        except Exception as e:
            logger.error(
                f"[!] 搜索验证码邮件失败: {e}",
                exc_info=True
            )
            return None, None

    
    def _extract_verification_code(self, raw_message: bytes) -> Optional[str]:
        """
        从邮件中提取验证码
        
        Args:
            raw_message: 邮件原始数据
            
        Returns:
            验证码字符串或None
        """
        try:
            # 解析邮件
            mail = mailparser.parse_from_bytes(raw_message)
            
            # 方法1: 从纯文本内容提取
            if mail.text_plain:
                text_content = ''.join(mail.text_plain)
                # 查找6位数字验证码
                code_pattern = r'\b(\d{6})\b'
                match = re.search(code_pattern, text_content)
                if match:
                    logger.debug(f"[+] 从纯文本提取到验证码: {match.group(1)}")
                    return match.group(1)
            
            # 方法2: 从HTML内容提取
            if mail.text_html:
                html_content = ''.join(mail.text_html)
                # 查找常见的验证码模式
                patterns = [
                    r'code[:\s]*(\d{6})',
                    r'verification[:\s]*(\d{6})',
                    r'>(\d{6})<',
                    r'\b(\d{6})\b'
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE)
                    if match:
                        logger.debug(f"[+] 从HTML提取到验证码: {match.group(1)}")
                        return match.group(1)
            
            # 方法3: 从邮件正文中查找
            if mail.body:
                body_text = mail.body
                code_pattern = r'\b(\d{6})\b'
                match = re.search(code_pattern, body_text)
                if match:
                    logger.debug(f"[+] 从邮件正文提取到验证码: {match.group(1)}")
                    return match.group(1)
            
            logger.warning("[!] 未能从邮件中提取验证码")
            return None
            
        except Exception as e:
            logger.error(f"[!] 提取验证码失败: {e}")
            return None
    
    def _get_glados_verification_code(self, email_address: str, 
                                      max_wait_minutes: int = 5,
                                      check_interval: int = 10) -> Optional[str]:
        """
        获取GLaDOS验证码（主入口方法）
        
        Args:
            email_address: 邮箱地址
            max_wait_minutes: 最大等待时间（分钟）
            check_interval: 检查间隔（秒）
            
        Returns:
            验证码字符串或None
        """
        logger.info(f"[*] 开始为 {email_address} 获取验证码，最多等待 {max_wait_minutes} 分钟")
        
        # 设置邮件客户端
        client = self._setup_imap_client()
        if not client:
            return None
        
        try:
            max_attempts = (max_wait_minutes * 60) // check_interval
            attempts = 0
            
            while attempts < max_attempts:
                attempts += 1
                logger.debug(f"[*] 第 {attempts}/{max_attempts} 次尝试获取验证码")
                
                # 搜索验证码邮件
                raw_message, uid = self._search_verification_email(
                    client, email_address, search_minutes=max_wait_minutes
                )
                
                if raw_message:
                    # 提取验证码
                    code = self._extract_verification_code(raw_message)
                    if code:
                        logger.info(f"[+] 成功获取验证码: {code}")
                        
                        try:
                            client.add_flags([uid], [b'\\Deleted'])
                            client.expunge()
                            logger.debug(f"[+] 已删除验证码邮件 UID={uid}")
                        except Exception as e:
                            logger.warning(f"[!] 删除邮件失败: {e}")
                        
                        return code
                
                # 如果没找到，等待后重试
                if attempts < max_attempts:
                    logger.debug(f"[*] 等待 {check_interval}s 后重试...")
                    time.sleep(check_interval)
            
            logger.warning(f"[!] 在 {max_wait_minutes} 分钟内未收到验证码")
            return None
            
        except Exception as e:
            logger.error(f"[!] 获取验证码过程中出错: {e}")
            return None
            
        finally:
            # 确保关闭邮件客户端连接
            try:
                client.logout()
                logger.debug("[*] 邮件客户端已关闭")
            except:
                pass

    # -------------------------------
    # 登录函数
    # -------------------------------
    def login_account(self, account_name: str, mailbox_within_minutes: int = 5) -> bool:
            """登录单个账号，优先使用 cookies / 邮箱验证码"""
            accounts = self.cfg.accounts
            glados_cfg = self.cfg.glados
            idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
            
            if idx is None:
                logger.error(f"账号 {account_name} 未配置")
                return False
            
            acc = accounts[idx]
            username = acc.username

            # 1️⃣ Cookies 登录
            logger.info(f"[*] {account_name} 尝试使用 cookies 登录")
            if acc.cookies:
                self._set_session_cookies(acc.cookies)
                if self._cookie_login_ok():
                    logger.info(f"[+] {account_name} 使用 cookies 登录成功")
                    # 使用 account_name 调用刷新
                    self._refresh_status(account_name)
                    return True

            # 2️⃣ 邮箱验证码登录
            logger.info(f"[*] {account_name} 开始邮箱验证码登录流程")
            
            # 请求发送验证码
            payload = {"address": username, "site": "glados.network"}
            headers = {
                "Referer": glados_cfg.login_url,
                "Origin": glados_cfg.login_url.rsplit("/", 1)[0],
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json;charset=UTF-8",
            }
            
            try:
                r = self.session.post(glados_cfg.auth_url, json=payload, headers=headers)
                if "authorization" in r.headers:
                    token = r.headers["authorization"]
                    logger.info(f"[+] 验证码请求发送成功，获取到token")
                else:
                    logger.warning(f"[!] 未从响应头中获取到token")
                    token = None
            except Exception as e:
                logger.error(f"[!] 请求发送验证码失败: {e}")
                return False

            # 使用新的专用方法获取验证码
            code = self._get_glados_verification_code(
                email_address=username,
                max_wait_minutes=mailbox_within_minutes
            )
            
            if not code:
                logger.error(f"[x] {account_name} 未收到验证码，请检查邮箱")
                return False

            # 提交验证码登录
            try:
                if token:
                    headers["authorization"] = token
                
                payload = {
                    "method": "email", 
                    "site": "glados.network", 
                    "email": username, 
                    "mailcode": code
                }
                
                r = self.session.post(glados_cfg.login_api, json=payload, headers=headers)
                j = r.json()
                
                if j.get("code") != 0:
                    logger.error(f"[x] {account_name} 登录失败: {j}")
                    return False

                logger.info(f"[+] {account_name} 登录成功（邮箱验证码）")
                
                # 获取并保存cookies
                cookies_dict = self.session.cookies.get_dict()
                
                # 更新账户信息（使用修改后的_update_account方法）
                self._update_account(
                    idx=idx,
                    cookies=cookies_dict,
                    username=username  # 可以传递更多需要更新的字段
                )
                
                # 刷新状态
                self._refresh_status(account_name)
                return True
                
            except Exception as e:
                logger.error(f"[x] {account_name} 提交验证码失败: {e}")
                return False

    # -------------------------------
    # 礼品码核心方法
    # -------------------------------
    
    def _get_gift_codes_from_email(
        self, 
        target_email: str, 
        days_back: int = 3
    ) -> List[Dict[str, any]]:
        """
        从邮箱中获取GLaDOS礼品码（内部方法）
        
        Args:
            target_email: 目标邮箱地址
            days_back: 扫描过去几天的邮件
            
        Returns:
            List of found gift codes
        """
        found_codes = []
        
        logger.info(f"[*] 开始扫描邮箱 {target_email} 的礼品码邮件，时间范围: {days_back}天内")
        
        # 搜索条件：主题包含"礼品码"和"GLaDOS"
        search_conditions = [
            {"subject": "礼品码", "body": "GLaDOS"},
            {"subject": "Gift Code", "body": "GLaDOS"},
            {"subject": "GLaDOS", "body": "礼品码"},
            {"subject": "GLaDOS", "body": "Gift Code"},
            {"subject": "gift code", "body": "glados"},
        ]
        
        all_emails = []
        
        for condition in search_conditions:
            try:
                emails = self.mail_client.query_email({
                    **condition,
                    "after_date": (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                })
                if emails:
                    all_emails.extend(emails)
            except Exception as e:
                logger.debug(f"[D] 搜索条件 {condition} 失败: {e}")
                continue
        
        # 去重（基于邮件ID）
        unique_emails = {}
        for email_data in all_emails:
            email_id = email_data.get("id")
            if email_id and email_id not in unique_emails:
                unique_emails[email_id] = email_data
        
        emails = list(unique_emails.values())
        logger.info(f"[+] 找到 {len(emails)} 封可能的礼品码邮件")
        
        # 解析每封邮件
        for email_data in emails:
            try:
                email_id = email_data.get("id", "")
                subject = email_data.get("subject", "")
                from_addr = email_data.get("from", "")
                email_date = email_data.get("date")
                body = email_data.get("body", "")
                
                # 检查是否发送给目标账户（可选检查）
                # 有些邮件可能发送到管理邮箱，这里可以放宽检查
                
                # 查找礼品码（格式：XXXXX-XXXXX-XXXXX-XXXXX）
                code_pattern = r'\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b'
                code_matches = re.findall(code_pattern, body.upper())
                
                # 如果没有找到，尝试小写
                if not code_matches:
                    code_pattern = r'\b([a-z0-9]{5}-[a-z0-9]{5}-[a-z0-9]{5}-[a-z0-9]{5})\b'
                    code_matches = re.findall(code_pattern, body.lower())
                    code_matches = [code.upper() for code in code_matches]
                
                if code_matches:
                    gift_code = code_matches[0]  # 取第一个匹配的代码
                    
                    # 提取赠送天数
                    days_gifted = 0
                    
                    # 从主题提取
                    days_patterns = [
                        r'(\d+)\s*天',          # 中文：50天
                        r'(\d+)\s*days',        # 英文：50 days
                        r'(\d+)\s*Days',        # 英文：50 Days
                    ]
                    
                    for pattern in days_patterns:
                        match = re.search(pattern, subject, re.IGNORECASE)
                        if match:
                            days_gifted = int(match.group(1))
                            break
                    
                    # 如果主题中没有，从正文中查找
                    if days_gifted == 0:
                        for pattern in days_patterns:
                            match = re.search(pattern, body, re.IGNORECASE)
                            if match:
                                days_gifted = int(match.group(1))
                                break
                    
                    code_info = {
                        "email_id": email_id,
                        "subject": subject,
                        "from": from_addr,
                        "date": email_date,
                        "gift_code": gift_code,
                        "days": days_gifted,
                        "target_email": target_email,
                        "body_preview": body[:150] + "..." if len(body) > 150 else body,
                    }
                    
                    found_codes.append(code_info)
                    logger.info(f"[+] 找到礼品码: {gift_code} ({days_gifted}天), 主题: {subject[:50]}...")
            
            except Exception as e:
                logger.warning(f"[!] 解析邮件失败 (ID: {email_data.get('id', 'unknown')}): {e}")
                continue
        
        return found_codes

    def get_gift_codes(
        self, 
        account_name: Optional[str] = None,
        target_email: Optional[str] = None,
        days_back: int = 3,
        delete_after_find: bool = False
    ) -> List[Dict[str, any]]:
        """
        获取指定账户的GLaDOS礼品码
        
        Args:
            account_name: 账户名称（优先使用）
            target_email: 目标邮箱地址（如果未提供account_name则使用）
            days_back: 扫描过去几天的邮件
            delete_after_find: 找到后是否删除邮件
            
        Returns:
            List of found gift codes
            
        返回格式：
        [
            {
                "email_id": str,           # 邮件ID
                "subject": str,            # 邮件主题
                "from": str,               # 发件人
                "date": datetime,          # 邮件日期
                "gift_code": str,          # 礼品码（如：014F1-ZKDOG-F0N0Q-F2FF2）
                "days": int,               # 赠送天数（如50）
                "target_email": str,       # 目标邮箱
                "body_preview": str,       # 正文预览
            },
            ...
        ]
        """
        # 确定目标邮箱
        if account_name:
            # 根据账户名查找邮箱
            idx = next((i for i, a in enumerate(self.accounts) if a["name"] == account_name), None)
            if idx is None:
                logger.error(f"[x] 账户 {account_name} 未配置")
                return []
            target_email = self.accounts[idx]["username"]
        elif not target_email:
            logger.error("[x] 必须提供 account_name 或 target_email")
            return []
        
        logger.info(f"[*] 开始获取礼品码，目标邮箱: {target_email}")
        
        # 登录邮箱
        try:
            self.mail_client.login()
        except Exception as e:
            logger.error(f"[x] 邮箱登录失败: {e}")
            return []
        
        found_codes = []
        try:
            # 调用内部方法获取礼品码
            found_codes = self._get_gift_codes_from_email(target_email, days_back)
            
            # 如果需要删除邮件
            if delete_after_find and found_codes:
                email_ids_to_delete = [code["email_id"] for code in found_codes if code["email_id"]]
                if email_ids_to_delete:
                    delete_result = self.mail_client.delete_emails(
                        email_ids=email_ids_to_delete,
                        permanent=False  # 软删除到垃圾箱
                    )
                    if delete_result.get("success"):
                        logger.info(f"[+] 已软删除 {delete_result.get('deleted_count', 0)} 封礼品码邮件")
                    else:
                        logger.warning(f"[!] 删除邮件失败: {delete_result.get('message')}")
        
        except Exception as e:
            logger.error(f"[x] 获取礼品码失败: {e}")
        finally:
            self.mail_client.logout()
        
        logger.info(f"[✓] 获取完成，共找到 {len(found_codes)} 个礼品码")
        return found_codes

    def redeem_gift_code(
        self, 
        account_name: str, 
        gift_code: str
    ) -> Dict[str, any]:
        """
        兑换单个GLaDOS礼品码
        
        Args:
            account_name: 账户名称
            gift_code: 礼品码（如：014F1-ZKDOG-F0N0Q-F2FF2）
            
        Returns:
            兑换结果
            
        返回格式：
        {
            "success": bool,           # 是否成功
            "code": int,              # API返回码：0=成功，-2=已兑换
            "message": str,           # 返回消息
            "gift_code": str,         # 兑换的礼品码
            "account": str,           # 账户名称
            "timestamp": str,         # 兑换时间
            "details": any,           # 原始返回数据
        }
        """
        result = {
            "success": False,
            "code": -1,
            "message": "",
            "gift_code": gift_code,
            "account": account_name,
            "timestamp": datetime.now().isoformat(),
            "details": None
        }
        
        # 1. 找到对应账户
        idx = next((i for i, a in enumerate(self.accounts) if a["name"] == account_name), None)
        if idx is None:
            result["message"] = f"账户 {account_name} 未配置"
            logger.error(result["message"])
            return result
        
        acc = self.accounts[idx]
        
        # 2. 确保已登录
        if not self._cookie_login_ok():
            # 需要先登录（这里使用简化登录，实际可能需要完整的登录流程）
            logger.warning(f"[!] 账户 {account_name} 需要重新登录，礼品码兑换可能需要完整登录流程")
            result["message"] = "账户需要登录后才能兑换礼品码"
            return result
        
        # 3. 清理礼品码格式
        clean_code = gift_code.strip().upper().replace(" ", "")
        
        # 验证格式：XXXXX-XXXXX-XXXXX-XXXXX
        if not re.match(r'^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$', clean_code):
            result["message"] = f"礼品码格式不正确: {gift_code}"
            logger.error(result["message"])
            return result
        
        # 4. 准备请求
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "zh-CN,zh;q=0.9",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://glados.rocks",
            "referer": "https://glados.rocks/console/checkin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        }
        
        # 添加authorization（如果有token）
        if acc.get("token"):
            headers["authorization"] = acc["token"]
        
        # 5. 发送兑换请求
        api_url = "https://glados.rocks/api/user/code"
        payload = {"code": clean_code}
        
        try:
            logger.info(f"[*] 正在为账户 {account_name} 兑换礼品码: {clean_code}")
            
            response = self.session.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            # 解析响应
            response_data = response.json()
            result["details"] = response_data
            result["code"] = response_data.get("code", -1)
            
            # 处理返回码
            if response_data.get("code") == 0:
                result["success"] = True
                result["message"] = response_data.get("message", "兑换成功")
                logger.info(f"[✓] 礼品码兑换成功: {clean_code} - {result['message']}")
                
                # 可选：刷新账户状态
                try:
                    self._refresh_status(account_name)
                except Exception:
                    pass  # 刷新失败不影响兑换结果
                
            elif response_data.get("code") == -2:
                result["success"] = False
                result["message"] = response_data.get("message", "该礼品码已兑换过")
                logger.warning(f"[!] 礼品码已兑换过: {clean_code}")
                
            else:
                result["success"] = False
                error_msg = response_data.get("message", f"兑换失败，错误码: {response_data.get('code')}")
                result["message"] = error_msg
                logger.error(f"[x] 礼品码兑换失败: {clean_code} - {error_msg}")
                
        except requests.exceptions.RequestException as e:
            result["message"] = f"网络请求失败: {str(e)}"
            logger.error(f"[x] 兑换请求失败: {e}")
        except ValueError as e:
            result["message"] = f"响应解析失败: {str(e)}"
            logger.error(f"[x] 响应解析失败: {e}")
        except Exception as e:
            result["message"] = f"兑换过程发生错误: {str(e)}"
            logger.error(f"[x] 兑换过程异常: {e}")
        
        return result

    def redeem_all_gift_codes(
        self, 
        account_name: str, 
        days_back: int = 3,
        delete_after_redeem: bool = True,
        max_retries: int = 3
    ) -> Dict[str, any]:
        """
        兑换指定账户的所有礼品码（自动扫描并兑换）
        
        Args:
            account_name: 账户名称
            days_back: 扫描过去几天的邮件
            delete_after_redeem: 兑换成功后是否删除邮件
            max_retries: 最大重试次数
            
        Returns:
            兑换汇总结果
            
        返回格式：
        {
            "account": str,                   # 账户名称
            "total_found": int,               # 总共找到的礼品码数量
            "successful": int,                # 成功兑换的数量
            "failed": int,                    # 兑换失败的数量
            "already_redeemed": int,          # 已兑换过的数量
            "total_days": int,                # 总共获得的天数
            "results": List[Dict],            # 每个礼品码的兑换结果
            "timestamp": str,                 # 操作时间
        }
        """
        result = {
            "account": account_name,
            "total_found": 0,
            "successful": 0,
            "failed": 0,
            "already_redeemed": 0,
            "total_days": 0,
            "results": [],
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"[*] 开始为账户 {account_name} 兑换所有礼品码")
        
        # 1. 首先确保账户登录
        # 这里需要完整的登录流程，因为兑换礼品码需要有效的session
        try:
            # 查找账户配置
            idx = next((i for i, a in enumerate(self.accounts) if a["name"] == account_name), None)
            if idx is None:
                logger.error(f"[x] 账户 {account_name} 未配置")
                return result
            
            acc = self.accounts[idx]
            
            # 尝试使用cookies/token登录
            if not self._cookie_login_ok():
                logger.warning(f"[!] 账户 {account_name} 需要重新登录")
                # 这里可以调用登录方法，但为简化我们继续尝试
                
        except Exception as e:
            logger.error(f"[x] 账户准备失败: {e}")
            return result
        
        # 2. 获取礼品码列表
        found_codes = self.get_gift_codes(
            account_name=account_name,
            days_back=days_back,
            delete_after_find=False  # 先不删除，等兑换成功后再处理
        )
        
        result["total_found"] = len(found_codes)
        
        if not found_codes:
            logger.info(f"[*] 未找到可兑换的礼品码")
            return result
        
        logger.info(f"[+] 找到 {len(found_codes)} 个礼品码，开始兑换...")
        
        # 3. 按时间排序（最新的优先）
        found_codes.sort(key=lambda x: x.get("date", datetime.min), reverse=True)
        
        # 4. 逐个兑换
        success_emails = []  # 成功兑换的邮件ID
        
        for code_info in found_codes:
            gift_code = code_info["gift_code"]
            days = code_info.get("days", 0)
            
            logger.info(f"[*] 尝试兑换礼品码: {gift_code} ({days}天)")
            
            # 兑换礼品码（带重试）
            redeem_success = False
            redeem_result = None
            
            for attempt in range(max_retries):
                try:
                    redeem_result = self.redeem_gift_code(account_name, gift_code)
                    
                    # 记录结果
                    combined_result = {
                        **code_info,
                        "redeem_attempt": attempt + 1,
                        "redeem_result": redeem_result
                    }
                    result["results"].append(combined_result)
                    
                    # 处理结果
                    if redeem_result.get("success"):
                        redeem_success = True
                        result["successful"] += 1
                        result["total_days"] += days
                        success_emails.append(code_info.get("email_id"))
                        logger.info(f"[✓] 兑换成功: {gift_code}")
                        break
                        
                    elif redeem_result.get("code") == -2:
                        # 已兑换过
                        result["already_redeemed"] += 1
                        logger.warning(f"[!] 礼品码已兑换过: {gift_code}")
                        break
                        
                    else:
                        # 其他错误
                        logger.warning(f"[!] 兑换失败 ({attempt + 1}/{max_retries}): {gift_code} - {redeem_result.get('message')}")
                        
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # 递增等待时间
                            logger.info(f"[*] 等待 {wait_time}s 后重试...")
                            time.sleep(wait_time)
                        else:
                            result["failed"] += 1
                            
                except Exception as e:
                    logger.error(f"[x] 兑换过程异常: {gift_code} - {e}")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                    else:
                        result["failed"] += 1
            
            # 避免请求过于频繁
            time.sleep(1)
        
        # 5. 删除成功兑换的邮件
        if delete_after_redeem and success_emails:
            try:
                self.mail_client.login()
                delete_result = self.mail_client.delete_emails(
                    email_ids=success_emails,
                    permanent=False
                )
                if delete_result.get("success"):
                    logger.info(f"[+] 已删除 {delete_result.get('deleted_count', 0)} 封已兑换的礼品码邮件")
                self.mail_client.logout()
            except Exception as e:
                logger.warning(f"[!] 删除邮件失败: {e}")
        
        # 6. 发送通知（如果有兑换成功的）
        if result["successful"] > 0:
            self._send_gift_code_notification(result)
        
        # 7. 汇总日志
        logger.info(f"[✓] 兑换完成: 成功 {result['successful']}个, 失败 {result['failed']}个, 已兑换 {result['already_redeemed']}个, 共获得 {result['total_days']}天")
        
        return result

    def _send_gift_code_notification(self, redemption_result: Dict[str, any]) -> None:
        """发送礼品码兑换通知"""
        if not self.notify_email:
            return
        
        account_name = redemption_result.get("account", "")
        successful = redemption_result.get("successful", 0)
        total_days = redemption_result.get("total_days", 0)
        
        subject = f"GLaDOS 礼品码兑换成功通知 - {account_name}"
        
        html_style = """
        <style>
            body {
                font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                background-color: #f6f8fa;
                margin: 0;
                padding: 20px;
            }
            h2 {
                color: #333;
                text-align: center;
            }
            .summary {
                background-color: #E8F5E9;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .footer {
                text-align: center;
                font-size: 12px;
                color: #888;
                margin-top: 20px;
            }
        </style>
        """
        
        # 构建成功兑换的礼品码列表
        success_list = ""
        for item in redemption_result.get("results", []):
            redeem_result = item.get("redeem_result", {})
            if redeem_result.get("success"):
                success_list += f"<li>{item.get('gift_code', '')} - {item.get('days', 0)}天</li>"
        
        html_body = f"""
        <html>
        <head>{html_style}</head>
        <body>
            <h2>GLaDOS 礼品码兑换成功通知</h2>
            <div class="summary">
                <p><strong>账户:</strong> {account_name}</p>
                <p><strong>成功兑换:</strong> {successful} 个礼品码</p>
                <p><strong>共获得:</strong> {total_days} 天会员</p>
            </div>
            {f'<p><strong>成功兑换的礼品码:</strong></p><ul>{success_list}</ul>' if success_list else ''}
            <div class="footer">此邮件由系统自动发送，请勿回复。</div>
        </body>
        </html>
        """
        
        # 发送邮件
        send_result = self.mail_client.send_email(
            self.notify_email, 
            subject, 
            html_body, 
            html=True
        )
        
        if send_result.get("success"):
            logger.info(f"[+] 礼品码兑换通知已发送至: {self.notify_email}")
        else:
            logger.error(f"[-] 通知邮件发送失败: {self.notify_email}")

    


    # -------------------------------
    # 获取状态（并更新账户） - 按 account_name 调用
    # -------------------------------
    def _refresh_status(self, account_name: str):
        """
        通过 status 接口刷新指定账号的 balance 和 leftDays（并写回 config）。
        account_name: accounts 列表中配置的 name 字段（例如 no01_xxx@163.com）
        """
        # 找到索引
        accounts = self.cfg.accounts
        idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
        if idx is None:
            logger.error(f"[!] _refresh_status: 未找到账号 {account_name}")
            return

        try:
            status_url = self.cfg.glados.status_url
            r = self.session.get(self.cfg.glados.status_url)
            r.raise_for_status()
            j = r.json()
            logger.debug(f"账户状态: {j}")

            data = j.get("data", {}) or {}

            # balance
            balance_raw = data.get("balance")
            try:
                balance = float(balance_raw) if balance_raw is not None else float(accounts[idx].balance)
            except Exception:
                balance = float(0)

            # leftDays（强制保存为整数）
            left_days_raw = data.get("leftDays", accounts[idx].leftDays)
            try:
                left_days = int(float(left_days_raw))
            except Exception:
                left_days = int(0)

            # traffic (字节数)
            traffic_raw = data.get("traffic", accounts[idx].traffic)
            try:
                traffic = int(traffic_raw)
            except Exception:
                traffic = int(0)

            # 总流量假设为 5GB (5 * 1024 * 1024 * 1024 字节)
            total_traffic = 5 * 1024 * 1024 * 1024  # 5GB 转换为字节

            # 更新账户
            self._update_account(idx,
                                 balance=balance,
                                 left_days = left_days,
                                 traffic=traffic,
                                 total_traffic=total_traffic)

            # 更新配置文件
            self.cfg.save()

            # 日志
            logger.info(f"[{account_name}] balance={balance}, leftDays={left_days}, usedTraffic={traffic / (1024 * 1024 * 1024):.2f} GB, totalTraffic={total_traffic / (1024 * 1024 * 1024):.2f} GB")

        except Exception as e:
            logger.warning(f"[WARN] 获取余额/状态失败 ({account_name}): {e}")

    # -------------------------------
    # 签到（单个账号）
    # -------------------------------
    def checkin_account(self, account_name: str) -> dict:
        """单个账户签到，并返回签到结果"""
        accounts = self.cfg.accounts
        glados_cfg = self.cfg.glados

        idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
        if idx is None:
            return {"success": False, "message": f"账号 {account_name} 未配置"}

        acc = accounts[idx]
        balance_before = acc.balance

        try:
            r = self.session.post(glados_cfg.checkin_url, json={"token": "glados.one"})
            j = r.json()
            logger.debug(f"签到结果: {j}")

            # 接口返回 list，则更新 balance / leftDays
            if "list" in j and j["list"]:
                new_balance = float(j["list"][0].get("balance", balance_before))
                left_days = j["list"][0].get("leftDays", acc.leftDays)
                self._update_account(idx, balance=new_balance, left_days=left_days)
                logger.info(f"[+] {account_name} 签到后余额更新为: {new_balance}, leftDays={left_days}")

            # 刷新状态获取最新 expireAt / leftDays
            self._refresh_status(account_name)

            return {
                "success": True,
                "message": j.get("message", "签到成功"),
                "balance": acc.balance,
                "leftDays": acc.leftDays,
                "expireAt": acc.expireAt,
                "traffic": acc.traffic,
                "total_traffic": acc.total_traffic
            }

        except Exception as e:
            logger.error(f"[x] {account_name} 签到失败: {e}")
            return {"success": False, "message": str(e)}


    def checkin_all(self):
        """批量签到并发送 HTML 邮件通知本次签到结果"""
        results = []
        accounts = self.cfg.accounts

        for acc in accounts:
            if self.login_account(acc.name):
                res = self.checkin_account(acc.name)
                results.append({"name": acc.name, **res})

        # 构建 HTML 邮件内容
        table_rows = ""
        for idx, res in enumerate(results):
            bg_color = "#f9f9f9" if idx % 2 else "#ffffff"
            status_color = "#4CAF50" if res.get("success") else "#f44336"
            message = res.get("message", "")
            balance = res.get("balance", "—")
            left_days = res.get("leftDays", "—")
            expire_at = res.get("expireAt", "—")
            used_traffic = res.get("traffic", 0)
            total_traffic = res.get("total_traffic", 5*1024**3)
            used_gb = used_traffic / (1024**3)
            total_gb = total_traffic / (1024**3)
            remaining_pct = ((total_gb - used_gb) / total_gb) * 100

            table_rows += (
                f"<tr style='background-color:{bg_color};'>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res['name']}</td>"
                f"<td style='border:1px solid #ccc; padding:8px; color:{status_color}; font-weight:bold;'>{message}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{balance}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{left_days}</td>"
                f"<td style='border:1px solid #ccc; padding:8px; color:#f44336; font-weight:bold;'>{expire_at}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{used_gb:.2f} GB / {total_gb:.2f} GB</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{remaining_pct:.2f}%</td>"
                f"</tr>"
            )

        # 发送邮件
        self._send_checkin_notification(table_rows)
        return results

    def _send_checkin_notification(self, table_rows: str) -> bool:
        """发送 GLaDOS 签到结果邮件（HTML 格式）"""
        from htmlmin import minify
        from pathlib import Path

        email_cfg = self.cfg.email
        accounts = self.cfg.accounts

        if not email_cfg.notify_address:
            logger.info("[i] 未配置通知邮箱，跳过发送")
            return False

        subject = "GLaDOS 签到成功通知"

        # =========================
        # 渲染并压缩 HTML 模板
        # =========================
        try:
            template_path = Path("modules/glados/templates/glados_checkin.html")
            html_tpl = template_path.read_text(encoding="utf-8")
            html_body = html_tpl.replace("{{ table_rows }}", table_rows)

            # 使用 htmlmin 压缩 HTML（去掉多余空格和换行）
            html_body = minify(html_body, remove_empty_space=True, remove_comments=True)

        except Exception as e:
            logger.error(f"[!] 渲染邮件 HTML 失败: {e}", exc_info=True)
            return False

        # =========================
        # 发送邮件
        # =========================
        client = self._setup_smtp_client()
        if not client:
            logger.error("[!] SMTP 客户端不可用，发送失败")
            return False

        try:
            client.send(
                to=email_cfg.notify_address,
                subject=subject,
                contents=html_body
            )
            logger.info(f"[+] 邮件已成功发送至 {email_cfg.notify_address}")
            client.close()
            client = None
            return True

        except Exception as e:
            logger.error(f"[!] 发送邮件失败: {e}", exc_info=True)
            return False

# -------------------------------
# CLI 入口
# -------------------------------
if __name__ == "__main__":
    client = GladosClient("config.yaml")
    client.checkin_all()