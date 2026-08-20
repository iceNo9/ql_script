# apps\glados\core\email.py

import re
import time
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
        logger.debug(f"尝试从纯文本解析用户 {user} 的登录验证码")

        # 匹配 Verification Code: 后面的数字
        pattern = r"Verification Code:\s*(\d+)"
        match = re.search(pattern, plain)

        if not match:
            logger.error(
                f"用户 {user} 的邮件内容中未找到验证码，内容预览: {plain[:200]}..."
            )
            raise ValueError(f"未在邮件内容中找到验证码: {plain[:200]}...")

        code = match.group(1)
        logger.info(f"成功解析用户 {user} 的登录验证码: {code}")

        return cls(
            code=code,
            user=user,
        )


@dataclass
class GiftCode:
    """礼品码"""

    code: str
    user: str

    @classmethod
    def from_html(
        cls,
        user: str,
        html: str,
    ) -> "GiftCode":
        """从邮件 HTML 中解析礼品码。"""
        logger.debug(f"尝试从 HTML 解析用户 {user} 的礼品码")

        pattern = re.compile(
            r"(?:兑换码|礼品码|激活码)\s*[:：]?\s*" r"([A-Z0-9]{5}(?:-[A-Z0-9]{5}){3})",
            re.IGNORECASE,
        )

        match = pattern.search(html)

        if not match:
            logger.error(f"用户 {user} 的 HTML 内容中未找到礼品码")
            raise ValueError("未找到礼品码")

        code = match.group(1)
        logger.info(f"成功解析用户 {user} 的礼品码: {code}")

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
        logger.info("邮件工具初始化完成")

    def get_login_code(self, user: str) -> LoginCode | None:
        """获取登录验证码。

        从最近1天的邮件中查找主题包含 'GLaDOS Authentication Code' 且收件人匹配的邮件，
        解析验证码后删除该邮件。

        Args:
            user: 用户名（邮箱地址）

        Returns:
            LoginCode 对象，如果未找到则返回 None
        """
        logger.info(f"开始获取用户 {user} 的登录验证码")

        try:
            with self.email_client.connection() as client:
                logger.debug(f"获取用户 {user} 最近1天的邮件摘要")

                # 获取最近1天的邮件摘要
                summaries = self.email_client.list_mail_summaries(
                    client=client,
                    days=1,
                )

                if not summaries:
                    logger.warning(f"用户 {user} 最近1天没有邮件")
                    return None

                logger.debug(f"共 {len(summaries)} 封邮件，查找登录验证码邮件")

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
                    logger.debug(
                        f"找到匹配的验证码邮件 uid={target_uid}，主题: {summary.subject}"
                    )
                    break

                if target_uid is None:
                    logger.warning(
                        f"用户 {user} 未找到登录验证码邮件（主题: {self._login_code_subject}）"
                    )
                    return None

                # 获取邮件详细内容
                logger.debug(f"获取邮件完整内容 uid={target_uid}")
                mail_detail = self.email_client.get_mail(
                    client=client,
                    uid=target_uid,
                )

                if mail_detail is None:
                    logger.error(f"获取邮件内容失败 uid={target_uid}")
                    return None

                # 解析验证码
                try:
                    login_code = LoginCode.from_plain(user, mail_detail.text_plain)
                except ValueError as e:
                    logger.error(f"解析验证码失败 uid={target_uid}: {e}")
                    return None

                # 删除邮件
                try:
                    logger.debug(f"删除验证码邮件 uid={target_uid}")
                    self.email_client.delete_mail(
                        client=client,
                        uid=target_uid,
                    )
                    logger.debug(f"成功删除验证码邮件 uid={target_uid}")
                except Exception:
                    # 删除失败不影响返回结果
                    logger.exception(f"删除邮件失败 uid={target_uid}")

                logger.info(f"成功获取用户 {user} 的登录验证码: {login_code.code}")
                return login_code

        except Exception:
            logger.exception(f"获取用户 {user} 登录验证码时发生异常")
            return None

    def get_gift_code(self, user: str, days: int = 30) -> GiftCode | None:
        """获取礼品码。

        查找主题包含 'GLaDOS' 和 '礼品码' 且收件人匹配的邮件，
        解析礼品码后移动到 '已兑换礼品码' 文件夹。

        Args:
            user: 用户名（邮箱地址）
            days: 查询天数，默认30天

        Returns:
            GiftCode 对象，如果未找到则返回 None
        """
        logger.info(f"开始获取用户 {user} 的礼品码，查询范围: {days}天")

        try:
            with self.email_client.connection() as client:
                logger.debug(f"获取用户 {user} 最近 {days} 天的邮件摘要")

                # 获取最近30天的邮件摘要（给一些缓冲时间）
                summaries = self.email_client.list_mail_summaries(
                    client=client,
                    days=days,
                )

                if not summaries:
                    logger.warning(f"用户 {user} 最近 {days} 天没有邮件")
                    return None

                logger.debug(f"共 {len(summaries)} 封邮件，查找礼品码邮件")

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
                    logger.debug(
                        f"找到匹配的礼品码邮件 uid={target_uid}，主题: {summary.subject}"
                    )
                    break

                if target_uid is None:
                    logger.warning(
                        f"用户 {user} 未找到礼品码邮件（匹配模式: {self._gift_code_subject_pattern.pattern}）"
                    )
                    return None

                # 获取邮件详细内容
                logger.debug(f"获取邮件完整内容 uid={target_uid}")
                mail_detail = self.email_client.get_mail(
                    client=client,
                    uid=target_uid,
                )

                if mail_detail is None:
                    logger.error(f"获取邮件内容失败 uid={target_uid}")
                    return None

                # 解析礼品码
                try:
                    gift_code = GiftCode.from_html(user, mail_detail.text_html)
                except ValueError as e:
                    logger.error(f"解析礼品码失败 uid={target_uid}: {e}")
                    return None

                # 移动到已兑换文件夹
                try:
                    logger.debug(
                        f"移动礼品码邮件 uid={target_uid} 到 '已兑换礼品码' 文件夹"
                    )
                    self.email_client.move_mail(
                        client=client,
                        uid=target_uid,
                        target_folder="已兑换礼品码",
                    )
                    logger.debug(
                        f"成功移动礼品码邮件 uid={target_uid} 到 '已兑换礼品码' 文件夹"
                    )
                except Exception:
                    # 移动失败不影响返回结果
                    logger.exception(f"移动邮件失败 uid={target_uid}")

                logger.info(f"成功获取用户 {user} 的礼品码: {gift_code.code}")
                return gift_code

        except Exception:
            logger.exception(f"获取用户 {user} 礼品码时发生异常")
            return None

    def list_gift_codes(self, days: int = 30) -> list[GiftCode]:
        """获取所有礼品码列表。

        查找主题包含 'GLaDOS' 和 '礼品码' 的邮件，
        解析所有礼品码后移动到 '已兑换礼品码' 文件夹。

        Args:
            days: 查询天数，默认30天

        Returns:
            GiftCode 列表，没有则为空列表
        """
        logger.info(f"开始批量获取礼品码，查询范围: {days}天")
        gift_codes: list[GiftCode] = []

        try:
            with self.email_client.connection() as client:
                logger.debug(f"获取最近 {days} 天的邮件摘要")

                # 获取最近30天的邮件摘要
                summaries = self.email_client.list_mail_summaries(
                    client=client,
                    days=days,
                )

                if not summaries:
                    logger.warning(f"最近 {days} 天没有邮件")
                    return []

                logger.debug(f"共 {len(summaries)} 封邮件，查找礼品码邮件")

                # 查找所有匹配的邮件
                matched_uids: list[int] = []
                for summary in summaries:
                    # 使用正则检查主题是否同时包含 GLaDOS 和 礼品码
                    if self._gift_code_subject_pattern.search(summary.subject):
                        matched_uids.append(summary.uid)
                        logger.debug(
                            f"找到匹配的礼品码邮件 uid={summary.uid}，主题: {summary.subject}"
                        )

                if not matched_uids:
                    logger.info(f"最近 {days} 天未发现礼品码邮件")
                    return []

                logger.info(f"发现 {len(matched_uids)} 封礼品码邮件，开始处理")

                # 处理每封匹配的邮件
                for idx, uid in enumerate(matched_uids, 1):
                    logger.debug(f"处理礼品码邮件 {idx}/{len(matched_uids)}，uid={uid}")

                    # 获取邮件详细内容
                    mail_detail = self.email_client.get_mail(
                        client=client,
                        uid=uid,
                    )

                    if mail_detail is None:
                        logger.error(f"获取邮件内容失败 uid={uid}，跳过")
                        continue

                    # 解析礼品码
                    try:
                        gift_code = GiftCode.from_html(
                            user=mail_detail.to[0] if mail_detail.to else "unknown",
                            html=mail_detail.text_html,
                        )
                        gift_codes.append(gift_code)
                        logger.debug(
                            f"成功解析礼品码 {idx}/{len(matched_uids)}: {gift_code.code}"
                        )
                    except ValueError as e:
                        logger.warning(f"解析礼品码失败 uid={uid}: {e}，跳过")
                        continue

                    # 移动到已兑换文件夹
                    try:
                        logger.debug(
                            f"移动礼品码邮件 uid={uid} 到 '已兑换礼品码' 文件夹"
                        )
                        self.email_client.move_mail(
                            client=client,
                            uid=uid,
                            target_folder="已兑换礼品码",
                        )
                        logger.debug(f"成功移动礼品码邮件 uid={uid}")
                    except Exception:
                        # 移动失败不影响继续处理
                        logger.exception(f"移动邮件失败 uid={uid}")

                logger.info(f"成功获取 {len(gift_codes)} 个礼品码")
                return gift_codes

        except Exception:
            logger.exception("批量获取礼品码时发生异常")
            return []

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
        logger.info(
            f"开始等待用户 {user} 的登录验证码，超时: {timeout}秒，间隔: {interval}秒"
        )

        deadline = time.monotonic() + timeout
        attempt_count = 0

        while time.monotonic() < deadline:
            attempt_count += 1
            logger.debug(f"第 {attempt_count} 次尝试获取用户 {user} 的登录验证码")

            result = self.get_login_code(user)

            if result is not None:
                elapsed = time.monotonic() - (deadline - timeout)
                logger.info(
                    f"第 {attempt_count} 次尝试成功获取登录验证码 {result.code}，耗时 {elapsed:.1f}秒"
                )
                return result

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            wait_time = min(interval, remaining)
            logger.debug(
                f"第 {attempt_count} 次尝试未获取到验证码，等待 {wait_time:.1f}秒后重试"
            )
            time.sleep(wait_time)

        logger.warning(
            f"等待用户 {user} 登录验证码超时，共尝试 {attempt_count} 次，耗时 {timeout}秒"
        )
        return None
