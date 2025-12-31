import time
import requests
import re
import yagmail
from imapclient import IMAPClient
import mailparser
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.notify import ql_notify
from common.logger import logger
from modules.glados.config.config import Config

class RequestClient:
    """封装请求客户端，优先使用代理"""
    
    def __init__(self, proxy_url: Optional[str] = None, max_retries: int = 3):
        """
        初始化请求客户端
        
        Args:
            proxy_url: 代理地址，例如 "http://127.0.0.1:7890"
            max_retries: 最大重试次数
        """
        self.proxy_url = proxy_url
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })
        
    def _get_proxies(self, use_proxy: bool = True) -> Optional[Dict[str, str]]:
        """获取代理配置"""
        if use_proxy and self.proxy_url:
            return {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }
        return None
    
    def request(
        self,
        method: str,
        url: str,
        prefer_proxy: bool = True,
        **kwargs
    ) -> requests.Response:
        """
        发送请求，优先使用代理
        
        Args:
            method: HTTP方法
            url: 请求URL
            prefer_proxy: 是否优先使用代理
            **kwargs: requests请求参数
            
        Returns:
            requests.Response对象
        """
        last_exception = None
        
        # 定义尝试顺序：如果prefer_proxy为True，先尝试代理，再尝试直连
        attempts_plan = []
        if prefer_proxy and self.proxy_url:
            attempts_plan.append((True, "代理"))  # 先尝试代理
            attempts_plan.append((False, "直连"))  # 再尝试直连
        else:
            attempts_plan.append((False, "直连"))  # 只尝试直连
        
        for use_proxy, method_name in attempts_plan:
            for attempt in range(self.max_retries):
                try:
                    logger.debug(f"[*] 尝试 {method_name} 请求 {url} (尝试 {attempt+1}/{self.max_retries})")
                    
                    proxies = self._get_proxies(use_proxy)
                    
                    # 设置超时
                    if 'timeout' not in kwargs:
                        kwargs['timeout'] = 30
                    
                    # 发送请求
                    response = self.session.request(
                        method=method,
                        url=url,
                        proxies=proxies,
                        **kwargs
                    )
                    
                    # 记录日志
                    logger.debug(f"[*] {method_name} 请求 {url} - 状态码: {response.status_code}")
                    
                    # 如果请求成功，返回响应
                    if response.status_code < 500:  # 只对服务器错误进行重试
                        logger.info(f"[+] {method_name} 请求成功: {url}")
                        return response
                    
                    # 服务器错误，记录并继续重试
                    logger.warning(f"[!] {method_name} 请求失败: {url} - 状态码: {response.status_code}")
                    
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_exception = e
                    logger.warning(f"[!] {method_name} 网络请求异常 (尝试 {attempt+1}/{self.max_retries}): {e}")
                    
                    if attempt < self.max_retries - 1:
                        time.sleep(1)  # 等待后重试
                    continue
                
                except Exception as e:
                    last_exception = e
                    logger.error(f"[!] {method_name} 请求异常: {e}")
                    break  # 其他异常直接跳出重试循环
            
            # 如果当前方法成功了，就返回
            if 'response' in locals() and response.status_code < 500:
                return response
        
        # 所有尝试都失败
        if last_exception:
            raise last_exception
        raise Exception(f"所有请求方式都失败: {url}")
    
    def get(self, url: str, prefer_proxy: bool = True, **kwargs) -> requests.Response:
        """GET请求，优先使用代理"""
        return self.request("GET", url, prefer_proxy=prefer_proxy, **kwargs)
    
    def post(self, url: str, prefer_proxy: bool = True, **kwargs) -> requests.Response:
        """POST请求，优先使用代理"""
        return self.request("POST", url, prefer_proxy=prefer_proxy, **kwargs)
    
    def set_cookies(self, cookies: Dict[str, str]):
        """设置cookies"""
        self.session.cookies.clear()
        for k, v in cookies.items():
            self.session.cookies.set(k, v)
    
    def get_cookies_dict(self) -> Dict[str, str]:
        """获取当前cookies字典"""
        return requests.utils.dict_from_cookiejar(self.session.cookies)

class GladosClient:
    def __init__(self, rv_cfg: Config):
        self.cfg = rv_cfg
        
        gl_cfg = self.cfg.glados
        
        # 初始化请求客户端，优先使用代理
        self.client = RequestClient(proxy_url=gl_cfg.proxy_url, max_retries=2)
        
        self.imap_client = None
        self.smtp_client = None

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _set_session_cookies(self, cookies: Dict[str, str]):
        """设置cookies"""
        self.client.set_cookies(cookies)

    def _cookie_login_ok(self) -> bool:
        """检查cookies登录状态"""
        try:
            status_url = self.cfg.glados.status_url
            r = self.client.get(status_url, prefer_proxy=True)
            j = r.json()
            return j.get("code") == 0
        except Exception as e:
            logger.error(f"[!] 检查登录状态失败: {e}")
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
        更新指定索引的账户信息
        """
        if idx < 0 or idx >= len(self.cfg.accounts):
            raise IndexError(f"账户索引 {idx} 超出范围")
        
        account = self.cfg.accounts[idx]
        
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
            mail_cfg = self.cfg.email
            client = IMAPClient(mail_cfg.imap_server, port=mail_cfg.imap_port, ssl=True)
            client.login(mail_cfg.username, mail_cfg.password)
            client.select_folder('INBOX', readonly=True)
            logger.info("[+] 邮件imap客户端登录成功")
            return client
        except Exception as e:
            logger.error(f"[!] 邮件imap客户端登录失败: {e}")
            return None
    
    def _setup_smtp_client(self) -> Optional[yagmail.SMTP]:
        """初始化并登录 SMTP 客户端"""
        if self.smtp_client:
            return self.smtp_client

        try:
            email_cfg = self.cfg.email
            self.smtp_client = yagmail.SMTP(
                user=email_cfg.username,
                password=email_cfg.password,
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
        搜索验证码邮件
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

            # 按 UID 倒序
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
        获取GLaDOS验证码
        """
        logger.info(f"[*] 开始为 {email_address} 获取验证码，最多等待 {max_wait_minutes} 分钟")
        
        # 设置邮件客户端
        client = self._setup_imap_client()
        
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
            """登录单个账号，优先使用代理"""
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
                    self._refresh_status(account_name)
                    return True

            # 2️⃣ 邮箱验证码登录
            logger.info(f"[*] {account_name} 开始邮箱验证码登录流程")
            
            # 请求发送验证码，优先使用代理
            payload = {"address": username, "site": "glados.network"}
            headers = {
                "Referer": glados_cfg.login_url,
                "Origin": glados_cfg.login_url.rsplit("/", 1)[0],
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json;charset=UTF-8",
            }
            
            try:
                r = self.client.post(
                    glados_cfg.auth_url, 
                    json=payload, 
                    headers=headers,
                    prefer_proxy=True
                )
                if "authorization" in r.headers:
                    token = r.headers["authorization"]
                    logger.info(f"[+] 验证码请求发送成功，获取到token")
                else:
                    logger.warning(f"[!] 未从响应头中获取到token")
                    token = None
            except Exception as e:
                logger.error(f"[!] 请求发送验证码失败: {e}")
                return False

            # 获取验证码
            code = self._get_glados_verification_code(
                email_address=username,
                max_wait_minutes=mailbox_within_minutes
            )
            
            if not code:
                logger.error(f"[x] {account_name} 未收到验证码，请检查邮箱")
                return False

            # 提交验证码登录，优先使用代理
            try:
                if token:
                    headers["authorization"] = token
                
                payload = {
                    "method": "email", 
                    "site": "glados.network", 
                    "email": username, 
                    "mailcode": code
                }
                
                r = self.client.post(
                    glados_cfg.login_api, 
                    json=payload, 
                    headers=headers,
                    prefer_proxy=True
                )
                j = r.json()
                
                if j.get("code") != 0:
                    logger.error(f"[x] {account_name} 登录失败: {j}")
                    return False

                logger.info(f"[+] {account_name} 登录成功（邮箱验证码）")
                
                # 获取并保存cookies
                cookies_dict = self.client.get_cookies_dict()
                
                # 更新账户信息
                self._update_account(
                    idx=idx,
                    cookies=cookies_dict,
                    username=username
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
    
    # 方法1：提取邮件中的礼品码
    def _extract_gift_codes_from_email(self, email_body: str, email_id: str, target_email: str, subject: str) -> List[Dict]:
        """
        从邮件正文中提取礼品码及天数信息
        """
        codes_found = []
        try:
            # 礼品码匹配，大小写不敏感
            code_pattern = r'\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b'
            matches = re.findall(code_pattern, email_body.upper())
            if not matches:
                logger.debug(f"[D] 邮件 {email_id} 未找到大写礼品码，尝试小写匹配")
                code_pattern = r'\b([a-z0-9]{5}-[a-z0-9]{5}-[a-z0-9]{5}-[a-z0-9]{5})\b'
                matches = re.findall(code_pattern, email_body.lower())
                matches = [m.upper() for m in matches]

            for code in matches:
                days = 0
                found_text = ""

                # 先从主题提取
                day_patterns = [r'(\d+)\s*天', r'(\d+)\s*Days?', r'(\d+)\s*days?']
                for pattern in day_patterns:
                    match = re.search(pattern, subject, re.IGNORECASE)
                    if match:
                        days = int(match.group(1))
                        found_text = match.group(0)
                        logger.debug(f"[D] 邮件 {email_id} 主题匹配到天数: {found_text} -> {days}")
                        break

                # 如果主题没提取到，从正文提取
                if days == 0:
                    for pattern in day_patterns:
                        match = re.search(pattern, email_body, re.IGNORECASE)
                        if match:
                            days = int(match.group(1))
                            found_text = match.group(0)
                            logger.debug(f"[D] 邮件 {email_id} 正文匹配到天数: {found_text} -> {days}")
                            break

                codes_found.append({
                    "email_id": email_id,
                    "gift_code": code,
                    "target_email": target_email,
                    "days": days,
                    "subject": subject,
                    "body_preview": email_body[:150] + "..." if len(email_body) > 150 else email_body
                })
                logger.info(f"[+] 提取到礼品码 {code} ({days}天) 邮件ID: {email_id}")

        except Exception as e:
            logger.error(f"[!] 提取礼品码失败 (邮件ID: {email_id}): {e}")

        return codes_found

    # 方法2：查询邮箱获取礼品码
    def _get_gift_code_emails(self, target_email: str, days_back: int = 7) -> List[Dict]:
        """
        扫描指定邮箱的礼品码邮件
        """
        logger.info(f"[*] 扫描邮箱 {target_email} 的礼品码邮件，过去 {days_back} 天")
        found_codes = []

        client = self._setup_imap_client()
        if client is None:
            logger.error("[x] IMAP客户端不可用")
            return []

        try:
            client.select_folder("INBOX")
            since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            logger.debug(f"[*] 搜索日期: {since_date}")

            # 仅搜索主题含 'GLaDOS' 的邮件
            criteria = ['SINCE', since_date, 'SUBJECT', 'GLaDOS']
            msg_ids = client.search(criteria)
            logger.info(f"[+] 命中 GLaDOS 主题邮件数量: {len(msg_ids)}")

            for msg_id in msg_ids:
                try:
                    msg_data = client.fetch([msg_id], ['RFC822'])
                    raw_email = msg_data[msg_id][b'RFC822']
                    mail = mailparser.parse_from_bytes(raw_email)

                    subject = mail.subject or ""
                    logger.debug(f"[D] 邮件ID {msg_id} 主题: {subject}")

                    # 获取邮件内容
                    text_plain = "\n".join(mail.text_plain) if mail.text_plain else ""
                    text_html = "\n".join(mail.text_html) if mail.text_html else ""

                    # 中文过滤，避免无关邮件
                    if '礼品码' not in subject and '礼品码' not in text_plain and '礼品码' not in text_html:
                        logger.debug(f"[D] 邮件ID {msg_id} 跳过（无礼品码关键词）")
                        continue

                    logger.debug(
                        f"[✓] 命中邮件 ID={msg_id}\n"
                        f"[SUBJECT]\n{subject}\n\n"
                        f"[TEXT_PLAIN]\n{text_plain[:500]}\n\n"
                        f"[TEXT_HTML]\n{text_html[:1000]}\n"
                        f"{'=' * 100}"
                    )

                    # 提取正文
                    extract_body = text_html if text_html.strip() else text_plain

                    # 获取邮件原始收件人
                    original_recipients = []
                    if mail.to:
                        if isinstance(mail.to, list):
                            original_recipients = mail.to
                        else:
                            original_recipients = [addr.strip() for addr in mail.to.split(",")]

                    # 假设邮件只有一个主要收件人，取第一个
                    email_target = original_recipients[0] if original_recipients else target_email

                    codes = self._extract_gift_codes_from_email(
                        extract_body,
                        str(msg_id),
                        email_target,
                        subject
                    )
                    found_codes.extend(codes)

                except Exception as e:
                    logger.warning(f"[!] 邮件解析失败 (ID: {msg_id}): {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[x] 邮件搜索失败: {e}", exc_info=True)

        logger.info(f"[✓] 邮件扫描完成，共提取 {len(found_codes)} 个礼品码")
        return found_codes
    
    # 方法3：兑换礼品码
    def redeem_gift_code(self, account_name: str, gift_code: str) -> Dict:
        """兑换礼品码，优先使用代理"""
        accounts = self.cfg.accounts
        glados_cfg = self.cfg.glados
        result = {
            "success": False,
            "code": -1,
            "message": "",
            "gift_code": gift_code,
            "account": account_name,
            "timestamp": datetime.now().isoformat(),
            "details": None
        }

        idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
        if idx is None:
            result["message"] = f"账户 {account_name} 未配置"
            logger.error(result["message"])
            return result
        
        acc = accounts[idx]

        if not self._cookie_login_ok():
            result["message"] = "账户需要登录后才能兑换礼品码"
            logger.warning(f"[!] {account_name} 需要登录")
            return result

        # 清理格式
        clean_code = gift_code.strip().upper().replace(" ", "")
        if not re.match(r'^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$', clean_code):
            result["message"] = f"礼品码格式不正确: {gift_code}"
            logger.error(result["message"])
            return result

        api_url = glados_cfg.redeem_url
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "user-agent": "Mozilla/5.0",
        }

        try:
            logger.info(f"[*] 兑换礼品码 {clean_code} - 账户 {account_name}")
            resp = self.client.post(
                api_url, 
                json={"code": clean_code}, 
                headers=headers, 
                timeout=30,
                prefer_proxy=True
            )
            data = resp.json()
            result["details"] = data
            result["code"] = data.get("code", -1)

            if data.get("code") == 0:
                result["success"] = True
                result["message"] = data.get("message", "兑换成功")
                logger.info(f"[✓] 兑换成功: {clean_code}")
                try:
                    self._refresh_status(account_name)
                except Exception:
                    pass
            elif data.get("code") == -2:
                result["success"] = False
                result["message"] = "礼品码已兑换"
                logger.warning(f"[!] 礼品码已兑换: {clean_code}")
            else:
                result["success"] = False
                result["message"] = data.get("message", f"兑换失败, code={data.get('code')}")
                logger.error(f"[x] 兑换失败: {clean_code} - {result['message']}")

        except Exception as e:
            result["message"] = f"网络请求失败: {e}"
            logger.error(f"[x] 兑换异常: {e}")

        return result

    # 方法4：扫描邮件并批量兑换礼品码
    def redeem_gift_codes(self, days_back: int = 7) -> List[Dict]:
        """
        扫描邮箱中的礼品码邮件并自动兑换
        """
        target_email = self.cfg.email.username
        accounts = self.cfg.accounts
        results = []

        logger.info(f"[*] 扫描邮箱 {target_email} 最近 {days_back} 天内的礼品码邮件")

        # 1. 获取礼品码邮件
        try:
            gift_codes = self._get_gift_code_emails(target_email, days_back=days_back)
        except Exception as e:
            logger.error(f"[x] 扫描邮件失败: {e}")
            return []

        if not gift_codes:
            logger.info(f"[i] 未找到礼品码邮件")
            return []

        logger.info(f"[+] 找到 {len(gift_codes)} 封可能包含礼品码的邮件")

        # 2. 遍历礼品码，根据收件人邮箱匹配账户并兑换
        imap_client = self._setup_imap_client()
        if imap_client is None:
            logger.error("[x] IMAP客户端不可用，无法移动邮件")
        
        # 创建目标文件夹（邮箱内）
        target_folder = "已兑换礼品码"
        try:
            if imap_client and target_folder not in imap_client.list_folders():
                imap_client.create_folder(target_folder)
                logger.info(f"[+] 创建邮箱文件夹: {target_folder}")
        except Exception as e:
            logger.warning(f"[!] 创建邮箱文件夹失败: {e}")

        for code_info in gift_codes:
            recipient_email = code_info["target_email"]
            if isinstance(recipient_email, tuple):
                recipient_email = recipient_email[1]  # 取邮箱部分
            gift_code = code_info["gift_code"]
            email_id = code_info.get("email_id")
            days = code_info.get("days", 0)
            subject = code_info.get("subject", "")

            # 匹配账户
            account = next((a for a in accounts if a.username.lower() == recipient_email.lower()), None)
            if not account:
                logger.warning(f"[!] 礼品码 {gift_code} 收件人 {recipient_email} 未找到对应账户，跳过")
                results.append({
                    "account": None,
                    "gift_code": gift_code,
                    "days": days,
                    "status": "未匹配账户",
                    "message": "收件人邮箱未找到对应账户"
                })
                continue

            account_name = account.name
            logger.info(f"[*] 尝试为账户 {account_name} 兑换礼品码 {gift_code} ({days}天)")

            try:
                if self.login_account(account_name):
                    redeem_result = self.redeem_gift_code(account_name, gift_code)
                    redeem_result["days"] = days

                    status = "成功" if redeem_result["success"] else redeem_result.get("message", "失败")

                    # 移动邮件到 '已兑换礼品码'
                    if imap_client and (redeem_result["success"] or redeem_result.get("message") == "礼品码已兑换"):
                        try:
                            imap_client.move([int(email_id)], target_folder)
                            logger.info(f"[+] 邮件ID {email_id} 移动到 {target_folder}")
                        except Exception as e:
                            logger.warning(f"[!] 邮件ID {email_id} 移动失败: {e}")

                    results.append({
                        "account": account_name,
                        "gift_code": gift_code,
                        "days": days,
                        "status": status,
                        "message": redeem_result.get("message"),
                        "email_id": email_id
                    })
            except Exception as e:
                logger.error(f"[x] 兑换礼品码 {gift_code} 失败: {e}")
                results.append({
                    "account": account_name,
                    "gift_code": gift_code,
                    "days": days,
                    "status": "兑换失败",
                    "message": str(e),
                    "email_id": email_id
                })

        logger.info(f"[✓] 批量兑换完成，共处理 {len(results)} 个礼品码")

        # 输出汇总信息
        summary = {}
        for res in results:
            acct = res.get("account", "未匹配账户")
            if acct not in summary:
                summary[acct] = []
            summary[acct].append({"gift_code": res["gift_code"], "days": res["days"], "status": res["status"]})

        logger.info("[i] 兑换汇总:")
        for acct, codes in summary.items():
            logger.info(f"  账户: {acct}")
            for c in codes:
                logger.info(f"    礼品码: {c['gift_code']}, 天数: {c['days']}, 状态: {c['status']}")

        if results:
            self._send_gift_code_notification(results)

        return results
       
    def _send_gift_code_notification(self, results: list) -> bool:
        """发送批量兑换礼品码结果邮件"""
        from htmlmin import minify
        from pathlib import Path

        email_cfg = self.cfg.email
        if not email_cfg.notify_address:
            logger.info("[i] 未配置通知邮箱，跳过发送")
            return False

        # 检查是否有兑换动作
        has_action = any(res.get("status") != "未匹配账户" for res in results)
        if not has_action:
            logger.info("[i] 无兑换动作，邮件不发送")
            return False

        # 构建表格行
        table_rows = ""
        for idx, res in enumerate(results):
            bg_color = "#f9f9f9" if idx % 2 else "#ffffff"
            status_color = "#4CAF50" if res.get("status") == "成功" else "#f44336"

            table_rows += (
                f"<tr style='background-color:{bg_color};'>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res.get('account','未匹配账户')}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res.get('gift_code')}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res.get('days',0)}</td>"
                f"<td style='border:1px solid #ccc; padding:8px; color:{status_color}; font-weight:bold;'>{res.get('status')}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res.get('message','')}</td>"
                f"<td style='border:1px solid #ccc; padding:8px;'>{res.get('email_id','')}</td>"
                f"</tr>"
            )

        # 渲染 HTML 模板
        try:
            template_path = Path("modules/glados/templates/glados_redeem.html")
            html_tpl = template_path.read_text(encoding="utf-8")
            html_body = html_tpl.replace("{{ table_rows }}", table_rows)

            html_body = minify(html_body, remove_empty_space=True, remove_comments=True)

        except Exception as e:
            logger.error(f"[!] 渲染礼品码邮件 HTML 失败: {e}", exc_info=True)
            return False

        # 发送邮件
        client = self._setup_smtp_client()
        if not client:
            logger.error("[!] SMTP 客户端不可用，发送失败")
            return False

        try:
            client.send(
                to=email_cfg.notify_address,
                subject="GLaDOS 礼品码兑换通知",
                contents=html_body
            )
            logger.info(f"[+] 礼品码兑换通知邮件已发送至 {email_cfg.notify_address}")
            client.close()
            return True

        except Exception as e:
            logger.error(f"[!] 礼品码兑换通知邮件发送失败: {e}", exc_info=True)
            return False

    # -------------------------------
    # 获取状态
    # -------------------------------
    def _refresh_status(self, account_name: str):
        """
        通过 status 接口刷新指定账号的状态
        """
        accounts = self.cfg.accounts
        idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
        if idx is None:
            logger.error(f"[!] _refresh_status: 未找到账号 {account_name}")
            return

        try:
            r = self.client.get(self.cfg.glados.status_url, prefer_proxy=True)
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

            # leftDays
            left_days_raw = data.get("leftDays", accounts[idx].leftDays)
            try:
                left_days = int(float(left_days_raw))
            except Exception:
                left_days = int(0)

            # traffic
            traffic_raw = data.get("traffic", accounts[idx].traffic)
            try:
                traffic = int(traffic_raw)
            except Exception:
                traffic = int(0)

            # 总流量假设为 5GB
            total_traffic = 5 * 1024 * 1024 * 1024

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
        """单个账户签到，优先使用代理"""
        accounts = self.cfg.accounts
        glados_cfg = self.cfg.glados

        idx = next((i for i, a in enumerate(accounts) if a.name == account_name), None)
        if idx is None:
            return {"success": False, "message": f"账号 {account_name} 未配置"}

        acc = accounts[idx]
        balance_before = acc.balance

        try:
            r = self.client.post(
                glados_cfg.checkin_url, 
                json={"token": "glados.one"},
                prefer_proxy=True
            )
            j = r.json()
            logger.debug(f"签到结果: {j}")

            # 接口返回 list，则更新 balance / leftDays
            if "list" in j and j["list"]:
                new_balance = float(j["list"][0].get("balance", balance_before))
                left_days = j["list"][0].get("leftDays", acc.leftDays)
                self._update_account(idx, balance=new_balance, left_days=left_days)
                logger.info(f"[+] {account_name} 签到后余额更新为: {new_balance}, leftDays={left_days}")

            # 刷新状态获取最新信息
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

    # -------------------------------
    # 批量签到
    # -------------------------------
    def checkin_all(self):
        """批量签到并发送 HTML 邮件通知"""
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
        """发送 GLaDOS 签到结果邮件"""
        from htmlmin import minify
        from pathlib import Path

        email_cfg = self.cfg.email
        accounts = self.cfg.accounts

        if not email_cfg.notify_address:
            logger.info("[i] 未配置通知邮箱，跳过发送")
            return False

        subject = "GLaDOS 签到成功通知"

        # 渲染并压缩 HTML 模板
        try:
            template_path = Path("modules/glados/templates/glados_checkin.html")
            html_tpl = template_path.read_text(encoding="utf-8")
            html_body = html_tpl.replace("{{ table_rows }}", table_rows)

            html_body = minify(html_body, remove_empty_space=True, remove_comments=True)

        except Exception as e:
            logger.error(f"[!] 渲染邮件 HTML 失败: {e}", exc_info=True)
            return False

        # 发送邮件
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