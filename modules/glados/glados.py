import time
import requests
from .config import Config
from .mailbox_client import MailBoxClient
from typing import Optional, Dict
from datetime import datetime, timedelta, timezone
from common.notify import ql_notify
from common.logger import logger

class GladosClient:
    def __init__(self, cfg_path: str = "config.yaml"):
        self.cfg = Config(cfg_path)
        gl_cfg = self.cfg.glados
        self.accounts = gl_cfg.get("accounts", [])
        self.threshold = gl_cfg.get("threshold", 999999.0)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        # 邮箱客户端
        email_cfg = self.cfg.email
        self.notify_email = email_cfg.get("notify_address", "")
        self.mail_client = MailBoxClient(
            email_addr=email_cfg["address"],
            password=email_cfg["password"],
            provider=email_cfg["provider"],
            ssl=email_cfg.get("ssl", True)
        )

    # -------------------------------
    # 内部工具方法
    # -------------------------------
    def _set_session_cookies(self, cookies: Dict[str, str]):
        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    def _cookie_login_ok(self) -> bool:
        try:
            r = self.session.get(self.cfg.glados.get("status_url"), timeout=10)
            j = r.json()
            return j.get("code") == 0
        except Exception:
            return False

    def _update_account(self, idx: int, cookies: Dict[str, str], balance: float, left_days: str, token: Optional[str] = None):
        self.accounts[idx]["cookies"] = cookies
        self.accounts[idx]["balance"] = balance
        self.accounts[idx]["leftDays"] = left_days
        if token:
            self.accounts[idx]["token"] = token
        self.cfg.set("glados", "accounts", self.accounts)

    # -------------------------------
    # 登录函数（单个账号）
    # -------------------------------
    def login_account(self, account_name: str, wait_seconds: int = 10, attempts: int = 18, mailbox_within_minutes: int = 15) -> bool:
        """登录单个账号，优先使用 cookies / token / 邮箱验证码"""
        idx = next((i for i, a in enumerate(self.accounts) if a["name"] == account_name), None)
        if idx is None:
            logger.error(f"账号 {account_name} 未配置")
            return False
        acc = self.accounts[idx]

        # 1️⃣ Cookies 登录
        if acc.get("cookies"):
            self._set_session_cookies(acc["cookies"])
            if self._cookie_login_ok():
                logger.info(f"[+] {account_name} 使用 cookies 登录成功")
                # 使用 account_name 调用刷新
                self._refresh_status(account_name)
                return True

        # 2️⃣ Token 登录
        token = acc.get("token")
        if token:
            try:
                headers = {"authorization": token}
                payload = {"method": "email", "site": "glados.network", "email": acc["username"], "mailcode": "000000"}
                r = self.session.post(self.cfg.glados.get("login_api"), json=payload, headers=headers, timeout=10)
                if r.json().get("code") == 0:
                    logger.info(f"[+] {account_name} 使用 token 登录成功")
                    self._refresh_status(account_name)
                    return True
            except Exception:
                logger.warning(f"[*] {account_name} token 登录失败")

        # 3️⃣ 邮箱验证码登录
        self.mail_client.login()
        payload = {"address": acc["username"], "site": "glados.network"}
        headers = {
            "Referer": self.cfg.glados.get("login_url"),
            "Origin": self.cfg.glados.get("login_url").rsplit("/", 1)[0],
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json;charset=UTF-8",
        }
        r = self.session.post(self.cfg.glados.get("auth_url"), json=payload, headers=headers)
        if "authorization" in r.headers:
            token = r.headers["authorization"]

        # 获取邮箱验证码
        code = None
        for i in range(attempts):
            code = self.mail_client.get_verification_code(
                within_minutes=mailbox_within_minutes,
                sender_match=acc["username"],
                delete_after_find=True,
            )
            if code:
                logger.info(f"[+] {account_name} 找到验证码: {code}")
                break
            logger.info(f"[*] 等待 {wait_seconds}s 获取验证码 ({i + 1}/{attempts})")
            time.sleep(wait_seconds)
        self.mail_client.logout()

        if not code:
            logger.error(f"[x] {account_name} 未收到验证码")
            return False

        # 提交验证码登录
        headers["authorization"] = token
        payload = {"method": "email", "site": "glados.network", "email": acc["username"], "mailcode": code}
        r = self.session.post(self.cfg.glados.get("login_api"), json=payload, headers=headers)
        j = r.json()
        if j.get("code") != 0:
            logger.error(f"[x] {account_name} 登录失败: {j}")
            return False

        logger.info(f"[+] {account_name} 登录成功（邮箱验证码）")
        cookies_dict = self.session.cookies.get_dict()
        # 更新 cookies 保持原 balance/leftDays，之后签到会更新 balance，然后状态会覆盖 leftDays
        self._update_account(idx, cookies_dict, acc.get("balance", 0), acc.get("leftDays", "0"), token)
        return True

    # -------------------------------
    # 获取状态（并更新账户） - 按 account_name 调用
    # -------------------------------
    def _refresh_status(self, account_name: str):
        """
        通过 status 接口刷新指定账号的 balance 和 leftDays（并写回 config）。
        account_name: accounts 列表中配置的 name 字段（例如 no01_xxx@163.com）
        """
        # 找到索引
        idx = next((i for i, a in enumerate(self.accounts) if a.get("name") == account_name), None)
        if idx is None:
            logger.error(f"[!] _refresh_status: 未找到账号 {account_name}")
            return

        try:
            r = self.session.get(self.cfg.glados.get("status_url"))
            r.raise_for_status()
            j = r.json()
            logger.debug(f"账户状态: {j}")

            data = j.get("data", {}) or {}

            # balance
            balance_raw = data.get("balance")
            try:
                balance = float(balance_raw) if balance_raw is not None else float(self.accounts[idx].get("balance", 0))
            except Exception:
                balance = float(self.accounts[idx].get("balance", 0))

            # leftDays（强制保存为整数）
            left_days_raw = data.get("leftDays", self.accounts[idx].get("leftDays", 0))
            try:
                left_days = int(float(left_days_raw))
            except Exception:
                left_days = int(float(self.accounts[idx].get("leftDays", 0)))

            # traffic (字节数)
            traffic_raw = data.get("traffic", self.accounts[idx].get("traffic", 0))
            try:
                traffic = int(traffic_raw)
            except Exception:
                traffic = int(self.accounts[idx].get("traffic", 0))

            # 总流量假设为 5GB (5 * 1024 * 1024 * 1024 字节)
            total_traffic = 5 * 1024 * 1024 * 1024  # 5GB 转换为字节

            # 将流量数据保存到配置文件
            self.accounts[idx]['traffic'] = traffic
            self.accounts[idx]['total_traffic'] = total_traffic

            # 更新账户（保持 cookies/token）
            self._update_account(
                idx,
                self.accounts[idx].get("cookies", {}),
                balance,
                left_days,
                self.accounts[idx].get("token"),
            )

            # 更新配置文件
            self.cfg.set("glados", "accounts", self.accounts)

            # 日志
            logger.info(f"[{account_name}] balance={balance}, leftDays={left_days}, usedTraffic={traffic / (1024 * 1024 * 1024):.2f} GB, totalTraffic={total_traffic / (1024 * 1024 * 1024):.2f} GB")

        except Exception as e:
            logger.warning(f"[WARN] 获取余额/状态失败 ({account_name}): {e}")



    # -------------------------------
    # 签到（单个账号）
    # -------------------------------
    def checkin_account(self, account_name: str) -> dict:
        idx = next((i for i, a in enumerate(self.accounts) if a["name"] == account_name), None)
        if idx is None:
            raise ValueError(f"账号 {account_name} 未配置")

        acc = self.accounts[idx]
        balance = acc.get("balance", 0)
        if balance >= self.threshold:
            logger.info(f"[*] {account_name} 余额 {balance} >= 阈值 {self.threshold}，跳过签到")
            return {"code": 2, "message": "Skipped due to threshold", "balance": balance}

        r = self.session.post(self.cfg.glados.get("checkin_url"), json={"token": "glados.one"})
        j = r.json()
        logger.debug(f"签到结果: {j}")
        logger.info(f"[✓] {account_name} 签到结果: {j.get('message', '')}")

        # 如果签到接口返回 list，优先使用里面的 balance/leftDays 更新 balance
        if "list" in j and j["list"]:
            new_balance = float(j["list"][0].get("balance", balance))
            left_days = j["list"][0].get("leftDays", self.accounts[idx].get("leftDays", "0"))
            self._update_account(idx, acc.get("cookies", {}), new_balance, left_days, acc.get("token"))
            logger.info(f"[+] {account_name} 签到后余额更新为: {new_balance}, leftDays={left_days}")

        # 签到后再刷新状态（使用 account_name），以获得更准确的 leftDays / expireAt
        self._refresh_status(account_name)

        return j

    # -------------------------------
    # 批量签到并发邮件
    # -------------------------------
    def checkin_all(self):
        results = []
        for acc in self.accounts:
            name = acc["name"]
            try:
                if self.login_account(name):
                    res = self.checkin_account(name)
                    results.append((name, res))
            except Exception as e:
                logger.error(f"[x] {name} 签到失败: {e}")

        # 邮件通知
        self._send_checkin_notification()
        return results

    def _send_checkin_notification(self):
        """发送签到结果邮件（HTML 格式）"""
        if not self.notify_email:
            return

        subject = "GLaDOS 签到成功通知"

        # HTML 样式
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
            table {
                width: 100%;
                border-collapse: collapse;
                background: #ffffff;
                box-shadow: 0 2px 6px rgba(0,0,0,0.05);
                margin-top: 10px;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 10px 12px;
                text-align: center;
            }
            th {
                background-color: #4CAF50;
                color: white;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            tr:hover {
                background-color: #e8f5e9;
            }
            .expire {
                color: #f44336;
                font-weight: bold;
            }
            .footer {
                text-align: center;
                font-size: 12px;
                color: #888;
                margin-top: 20px;
            }
            .traffic-info {
                font-size: 12px;
                color: #555;
                margin-top: 10px;
            }
        </style>
        """

        # 表格内容
        table_rows = ""
        for acc in self.accounts:
            expire_html = acc.get("expireAt", "—")

            # 获取已用流量和总流量
            used_traffic = acc.get("traffic", 0)
            total_traffic = acc.get("total_traffic", 5 * 1024 * 1024 * 1024)  # 默认总流量 5GB
            used_traffic_gb = used_traffic / (1024 * 1024 * 1024)  # 转换为 GB
            total_traffic_gb = total_traffic / (1024 * 1024 * 1024)  # 转换为 GB
            remaining_traffic_gb = total_traffic_gb - used_traffic_gb  # 剩余流量
            remaining_traffic_percentage = (remaining_traffic_gb / total_traffic_gb) * 100  # 剩余流量百分比

            row = f"""
            <tr>
                <td>{acc.get('name', '')}</td>
                <td>{acc.get('balance', 0)}</td>
                <td>{acc.get('leftDays', 0)}</td>
                <td class="expire">{expire_html}</td>
                <td>{used_traffic_gb:.2f} GB / {total_traffic_gb:.2f} GB</td>
                <td>{remaining_traffic_percentage:.2f}%</td>
            </tr>
            """
            table_rows += row

        html_body = f"""
        <html>
        <head>{html_style}</head>
        <body>
            <h2>GLaDOS 签到成功通知</h2>
            <p>以下是各账户的最新签到信息：</p>
            <table>
                <tr>
                    <th>账号</th>
                    <th>余额</th>
                    <th>剩余天数</th>
                    <th>到期时间</th>
                    <th>流量使用情况 (已用 / 总流量)</th>
                    <th>剩余流量百分比</th>
                </tr>
                {table_rows}
            </table>
            <div class="footer">此邮件由系统自动发送，请勿回复。</div>
        </body>
        </html>
        """

        # 发送邮件（HTML 格式）
        succ = self.mail_client.send_email(self.notify_email, subject, html_body, html=True)
        if succ:
            logger.info(f"[+] 通知邮件已发送至: {self.notify_email}")
        else:
            logger.error(f"[-] 通知邮件发送失败: {self.notify_email}")



# -------------------------------
# CLI 入口
# -------------------------------
if __name__ == "__main__":
    client = GladosClient("config.yaml")
    client.checkin_all()
