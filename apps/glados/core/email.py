# modules/glados/core/email.py

import re
from dataclasses import dataclass

from utils.email import EmailClient
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(name="glados_email", log_dir=logs(), fmt_type="detailed")


@dataclass
class LoginCode:
    """登录验证码"""

    code: str
    user: str

    @classmethod
    def from_plain(
        cls,
        user: str,
        plain: str,
    ) -> "LoginCode":
        """从邮件详细的plain解析登录验证码。"""
        # 匹配 Verification Code: 后面的数字
        pattern = r"Verification Code:\s*(\d+)"
        match = re.search(pattern, plain)

        if not match:
            raise ValueError(f"未在邮件内容中找到验证码: {plain[:200]}...")

        code = match.group(1)

        return cls(
            code=code,
            user=user,
        )


@dataclass
class GiftCode:
    """礼品码。"""

    code: str
    user: str

    @classmethod
    def from_html(
        cls,
        user: str,
        html: str,
    ) -> "GiftCode":
        """从邮件 HTML 中解析礼品码。"""
        pattern = re.compile(
            r"(?:兑换码|礼品码|激活码)\s*[:：]?\s*" r"([A-Z0-9]{5}(?:-[A-Z0-9]{5}){3})",
            re.IGNORECASE,
        )

        match = pattern.search(html)

        if not match:
            raise ValueError("未找到礼品码")

        return cls(
            code=match.group(1),
            user=user,
        )


class EmailTool:
    """邮件工具类，封装验证码和礼品码的获取逻辑。"""

    def __init__(self, email_client: EmailClient):
        self.email_client = email_client
        # 登录验证码主题（固定）
        self._login_code_subject = "GLaDOS Authentication Code"
        # 礼品码主题关键词正则
        self._gift_code_subject_pattern = re.compile(
            r"GLaDOS.*礼品码|礼品码.*GLaDOS",
            re.IGNORECASE,
        )

    def get_login_code(self, user: str) -> LoginCode | None:
        """获取登录验证码。

        从最近1天的邮件中查找主题包含 'GLaDOS Authentication Code' 且收件人匹配的邮件，
        解析验证码后删除该邮件。

        Args:
            user: 用户名（邮箱地址）

        Returns:
            LoginCode 对象，如果未找到则返回 None
        """
        with self.email_client.connection() as client:
            # 获取最近1天的邮件摘要
            summaries = self.email_client.list_mail_summaries(
                client=client,
                days=1,
            )

            if not summaries:
                return None

            # 查找匹配的邮件
            target_uid: int | None = None
            for summary in summaries:
                # 检查主题是否包含验证码标识
                if self._login_code_subject not in summary.subject:
                    continue

                # 检查收件人是否匹配
                if user not in summary.to:
                    continue

                target_uid = summary.uid
                break

            if target_uid is None:
                return None

            # 获取邮件详细内容
            mail_detail = self.email_client.get_mail(
                client=client,
                uid=target_uid,
            )

            if mail_detail is None:
                return None

            # 解析验证码
            try:
                login_code = LoginCode.from_plain(user, mail_detail.text_plain)
            except ValueError:
                return None
            # 删除邮件
            try:
                self.email_client.delete_mail(
                    client=client,
                    uid=target_uid,
                )
            except Exception:
                # 删除失败不影响返回结果
                logger.exception(f"Failed to delete mail with uid {target_uid}")

            return login_code

    def get_gift_code(self, user: str, days: int = 30) -> GiftCode | None:
        """获取礼品码。

        查找主题包含 'GLaDOS' 和 '礼品码' 且收件人匹配的邮件，
        解析礼品码后移动到 '已兑换礼品码' 文件夹。

        Args:
            user: 用户名（邮箱地址）

        Returns:
            GiftCode 对象，如果未找到则返回 None
        """
        with self.email_client.connection() as client:
            # 获取最近7天的邮件摘要（给一些缓冲时间）
            summaries = self.email_client.list_mail_summaries(
                client=client,
                days=days,
            )

            if not summaries:
                return None

            # 查找匹配的邮件
            target_uid: int | None = None
            for summary in summaries:
                # 使用正则检查主题是否同时包含 GLaDOS 和 礼品码
                if not self._gift_code_subject_pattern.search(summary.subject):
                    continue

                # 检查收件人是否匹配
                if user not in summary.to:
                    continue

                target_uid = summary.uid
                break

            if target_uid is None:
                return None

            # 获取邮件详细内容
            mail_detail = self.email_client.get_mail(
                client=client,
                uid=target_uid,
            )

            if mail_detail is None:
                return None

            # 解析礼品码
            try:
                gift_code = GiftCode.from_html(user, mail_detail.text_html)
            except ValueError:
                return None
            # 移动到已兑换文件夹
            try:
                self.email_client.move_mail(
                    client=client,
                    uid=target_uid,
                    target_folder="已兑换礼品码",
                )
            except Exception:
                # 移动失败不影响返回结果
                logger.exception(f"Failed to move mail with uid {target_uid}")

            return gift_code

    def list_gift_codes(self, days: int = 30) -> list[GiftCode]:
        """获取所有礼品码列表。

        查找主题包含 'GLaDOS' 和 '礼品码' 的邮件，
        解析所有礼品码后移动到 '已兑换礼品码' 文件夹。

        Returns:
            GiftCode 列表，没有则为空列表
        """
        gift_codes: list[GiftCode] = []

        with self.email_client.connection() as client:
            # 获取最近30天的邮件摘要
            summaries = self.email_client.list_mail_summaries(
                client=client,
                days=days,
            )

            if not summaries:
                return []

            # 查找所有匹配的邮件
            matched_uids: list[int] = []
            for summary in summaries:
                # 使用正则检查主题是否同时包含 GLaDOS 和 礼品码
                if self._gift_code_subject_pattern.search(summary.subject):
                    matched_uids.append(summary.uid)

            if not matched_uids:
                return []

            # 处理每封匹配的邮件
            for uid in matched_uids:
                # 获取邮件详细内容
                mail_detail = self.email_client.get_mail(
                    client=client,
                    uid=uid,
                )

                if mail_detail is None:
                    continue

                # 解析礼品码
                try:
                    gift_code = GiftCode.from_html(
                        user=mail_detail.to[0] if mail_detail.to else "unknown",
                        html=mail_detail.text_html,
                    )
                    gift_codes.append(gift_code)
                except ValueError:
                    continue
                # 移动到已兑换文件夹
                try:
                    self.email_client.move_mail(
                        client=client,
                        uid=uid,
                        target_folder="已兑换礼品码",
                    )
                except Exception:
                    # 移动失败不影响继续处理
                    logger.exception(f"Failed to move mail with uid {uid}")

        return gift_codes

    def wait_login_code(
        self,
        user: str,
        timeout: int = 60,
        interval: int = 3,
    ) -> LoginCode | None:
        """在指定时间内轮询获取登录验证码。

        Args:
            user: 用户名（邮箱地址）
            timeout: 最大等待时间，单位秒，默认 60 秒
            interval: 轮询间隔，单位秒，默认 3 秒

        Returns:
            获取到的 LoginCode，超时则返回 None。
        """
        import time

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            result = self.get_login_code(user)

            if result is not None:
                return result

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            time.sleep(min(interval, remaining))

        return None
