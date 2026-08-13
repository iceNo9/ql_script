from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Optional

import mailparser
from imapclient import IMAPClient
from imapclient.response_types import Address, Envelope

from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="email",
    log_dir=logs(),
    fmt_type="detailed",
)


class EmailProvider(StrEnum):
    """邮箱服务商。"""

    QQ = "qq"


@dataclass(frozen=True)
class IMAPConfig:
    """IMAP 服务配置。"""

    host: str
    port: int
    ssl: bool


IMAP_CONFIGS: dict[EmailProvider, IMAPConfig] = {
    EmailProvider.QQ: IMAPConfig(
        host="imap.qq.com",
        port=993,
        ssl=True,
    ),
}


@dataclass
class MailSummary:
    """邮件摘要。"""

    uid: int
    subject: str
    sender: str
    to: list[str]
    date: datetime

    @classmethod
    def from_envelope(
        cls,
        uid: int,
        envelope: Envelope,
    ) -> "MailSummary":
        """从 IMAP Envelope 解析邮件摘要。"""
        subject = cls._decode_subject(envelope.subject)
        sender = cls._extract_sender(envelope.from_)
        recipients = cls._extract_recipients(envelope.to)
        date = cls._parse_date(envelope.date)

        return cls(
            uid=uid,
            subject=subject,
            sender=sender,
            to=recipients,
            date=date,
        )

    @staticmethod
    def _decode_subject(subject_bytes: Optional[bytes]) -> str:
        """解码邮件主题。"""
        if not subject_bytes:
            return ""

        decoded_parts = decode_header(subject_bytes.decode(errors="ignore"))
        result = []

        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="ignore"))
            else:
                result.append(part)

        return "".join(result)

    @staticmethod
    def _extract_sender(from_field: Optional[list[Address]]) -> str:
        """提取发件人地址。"""
        if not from_field:
            return ""

        address = from_field[0]
        if isinstance(address, Address) and address.mailbox and address.host:
            mailbox = address.mailbox.decode(errors="ignore")
            host = address.host.decode(errors="ignore")
            return f"{mailbox}@{host}"

        return ""

    @staticmethod
    def _extract_recipients(to_field: Optional[list[Address]]) -> list[str]:
        """提取收件人地址列表。"""
        if not to_field:
            return []

        recipients = []
        for address in to_field:
            if isinstance(address, Address) and address.mailbox and address.host:
                mailbox = address.mailbox.decode(errors="ignore")
                host = address.host.decode(errors="ignore")
                recipients.append(f"{mailbox}@{host}")

        return recipients

    @staticmethod
    def _parse_date(date_value) -> datetime:
        """解析日期。"""
        if not date_value:
            return datetime.now(tz=UTC)

        if isinstance(date_value, datetime):
            return date_value

        try:
            return datetime.fromtimestamp(date_value, tz=UTC)
        except (TypeError, ValueError):
            return datetime.now(tz=UTC)


@dataclass
class MailDetail:
    """邮件详细内容。"""

    uid: int
    subject: str
    sender: str
    to: list[str]
    date: datetime
    text_plain: str
    text_html: str

    @classmethod
    def from_bytes(
        cls,
        uid: int,
        raw: bytes,
    ) -> "MailDetail":
        """从原始 RFC822 邮件解析详细内容。"""
        mail = mailparser.parse_from_bytes(raw)

        subject = cls._parse_field(mail.subject)
        sender = cls._extract_sender_from_mail(mail.from_)
        recipients = cls._extract_recipients_from_mail(mail.to)
        date = cls._parse_date_from_mail(mail.date)
        text_plain = cls._parse_field(mail.text_plain)
        text_html = cls._parse_field(mail.text_html)

        return cls(
            uid=uid,
            subject=subject,
            sender=sender,
            to=recipients,
            date=date,
            text_plain=text_plain,
            text_html=text_html,
        )

    @staticmethod
    def _parse_field(field) -> str:
        """解析通用字段。"""
        if not field:
            return ""

        if isinstance(field, list):
            return "".join(str(part) for part in field if part)

        return str(field)

    @staticmethod
    def _extract_sender_from_mail(from_field) -> str:
        """从 mailparser 对象提取发件人。"""
        if not from_field:
            return ""

        sender_info = from_field[0]

        if isinstance(sender_info, tuple) and len(sender_info) >= 2:
            return sender_info[1] or ""

        if isinstance(sender_info, str):
            return sender_info

        if hasattr(sender_info, "email"):
            return getattr(sender_info, "email", "") or ""

        return ""

    @staticmethod
    def _extract_recipients_from_mail(to_field) -> list[str]:
        """从 mailparser 对象提取收件人列表。"""
        if not to_field:
            return []

        recipients = []
        for recipient in to_field:
            address = None

            if isinstance(recipient, tuple) and len(recipient) >= 2:
                address = recipient[1]
            elif isinstance(recipient, str):
                address = recipient
            elif hasattr(recipient, "email"):
                address = getattr(recipient, "email", "")

            if address:
                recipients.append(str(address))

        return recipients

    @staticmethod
    def _parse_date_from_mail(date_field) -> datetime:
        """从 mailparser 对象解析日期。"""
        if not date_field:
            return datetime.now(tz=UTC)

        if isinstance(date_field, datetime):
            return date_field

        try:
            return parsedate_to_datetime(str(date_field))
        except (TypeError, ValueError):
            return datetime.now(tz=UTC)


class EmailClient:
    """通用 IMAP 邮箱客户端。

    只负责邮箱通信和邮件数据解析，
    不包含具体业务逻辑。
    """

    def __init__(
        self,
        username: str,
        password: str,
        provider: EmailProvider,
    ):
        self.username = username
        self.password = password
        self.provider = provider

    @contextmanager
    def connection(
        self,
    ) -> Generator[IMAPClient, None, None]:
        """创建 IMAP 连接并管理生命周期。"""
        imap_config = IMAP_CONFIGS.get(self.provider)

        if imap_config is None:
            raise ValueError(f"不支持的邮箱服务商: {self.provider}")

        client = IMAPClient(
            imap_config.host,
            port=imap_config.port,
            ssl=imap_config.ssl,
        )

        try:
            client.login(self.username, self.password)
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                logger.debug("关闭 IMAP 连接失败", exc_info=True)

    def _select_folder(
        self,
        client: IMAPClient,
        folder: str = "INBOX",
        readonly: bool = True,
    ) -> None:
        """选择文件夹。"""
        client.select_folder(folder, readonly=readonly)

    def list_mail_summaries(
        self,
        client: IMAPClient,
        days: int = 7,
        folder: str = "INBOX",
    ) -> list[MailSummary]:
        """获取邮件摘要。

        Args:
            client: IMAP 客户端
            days: 查询最近多少天的邮件
            folder: 邮箱文件夹名称，默认为 INBOX
        """
        self._select_folder(client, folder, readonly=True)

        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")

        uids = client.search(["SINCE", since])

        if not uids:
            return []

        uids.sort(reverse=True)

        data = client.fetch(uids, ["ENVELOPE"])

        summaries: list[MailSummary] = []

        for uid in uids:
            envelope = data.get(uid, {}).get(b"ENVELOPE")

            if not isinstance(envelope, Envelope):
                continue

            summaries.append(MailSummary.from_envelope(uid, envelope))

        return summaries

    def get_mail(
        self,
        client: IMAPClient,
        uid: int,
        folder: str = "INBOX",
    ) -> MailDetail | None:
        """获取并解析邮件详细内容。

        Args:
            client: IMAP 客户端
            uid: 邮件 UID
            folder: 邮箱文件夹名称，默认为 INBOX
        """
        self._select_folder(client, folder, readonly=True)

        data = client.fetch([uid], ["RFC822"])

        raw = data.get(uid, {}).get(b"RFC822")

        if not isinstance(raw, bytes):
            return None

        return MailDetail.from_bytes(uid, raw)

    def delete_mail(
        self,
        client: IMAPClient,
        uid: int,
        folder: str = "INBOX",
    ) -> None:
        """删除邮件。

        Args:
            client: IMAP 客户端
            uid: 邮件 UID
            folder: 源邮箱文件夹名称，默认为 INBOX
        """
        self._select_folder(client, folder, readonly=False)

        client.add_flags([uid], [b"\\Deleted"])
        client.expunge()

    def move_mail(
        self,
        client: IMAPClient,
        uid: int,
        target_folder: str,
        source_folder: str = "INBOX",
    ) -> None:
        """移动邮件。

        Args:
            client: IMAP 客户端
            uid: 邮件 UID
            target_folder: 目标文件夹名称
            source_folder: 源文件夹名称，默认为 INBOX
        """
        self._select_folder(client, source_folder, readonly=False)

        # 检查并创建目标文件夹
        folders = {item[2] for item in client.list_folders()}
        if target_folder not in folders:
            client.create_folder(target_folder)

        client.move([uid], target_folder)