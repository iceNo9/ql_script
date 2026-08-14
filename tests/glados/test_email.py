# tests/test_email.py
import json
import os
from datetime import datetime

from utils.email import (
    EmailClient,
    EmailProvider,
    MailDetail,
    MailSummary,
)
from utils.log import get_logger
from utils.paths import temp

logger = get_logger(
    name="test_glados_email",
    fmt_type="detailed",
    log_dir=temp(),
    console_level=10,
)

# ===============================
# 测试配置
# ===============================

EMAIL_USERNAME = os.environ["EMAIL_USERNAME"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

EMAIL_FOLDER = "INBOX"
EMAIL_DAYS = 7
MAX_DETAILS = 10


def log_mail_summary(summary: MailSummary, index: int) -> None:
    """记录邮件摘要。"""
    logger.info(
        "邮件 #%s | UID=%s | Subject=%s | Sender=%s | To=%s | Date=%s",
        index,
        summary.uid,
        summary.subject or "(无主题)",
        summary.sender or "(未知发件人)",
        ", ".join(summary.to) if summary.to else "(无)",
        summary.date,
    )


def log_mail_detail(detail: MailDetail, index: int) -> None:
    """记录邮件完整详情。"""
    logger.info("=" * 100)
    logger.info("邮件详情 #%s | UID=%s", index, detail.uid)
    logger.info("=" * 100)

    logger.info("基本信息:")
    logger.info("  UID: %s", detail.uid)
    logger.info("  主题: %s", detail.subject or "(无主题)")
    logger.info("  发件人: %s", detail.sender or "(未知发件人)")
    logger.info("  收件人: %s", ", ".join(detail.to) if detail.to else "(无)")
    logger.info("  日期: %s", detail.date)
    logger.info("  时区: %s", detail.date.tzinfo)

    logger.info("纯文本内容:")
    logger.info("-" * 80)

    if detail.text_plain:
        logger.info("%s", detail.text_plain)
        logger.info("纯文本长度: %s 字符", len(detail.text_plain))
    else:
        logger.info("(无纯文本内容)")

    logger.info("HTML 内容:")
    logger.info("-" * 80)

    if detail.text_html:
        logger.info("%s", detail.text_html)
        logger.info("HTML 长度: %s 字符", len(detail.text_html))
    else:
        logger.info("(无 HTML 内容)")


def log_statistics(
    summaries: list[MailSummary],
    details: list[MailDetail],
) -> None:
    """记录邮件统计信息。"""
    logger.info("=" * 100)
    logger.info("统计信息")
    logger.info("=" * 100)

    logger.info("邮件总数: %s", len(summaries))
    logger.info("详情获取数: %s", len(details))

    if not details:
        return

    total_plain_len = sum(len(detail.text_plain) for detail in details)
    total_html_len = sum(len(detail.text_html) for detail in details)

    avg_plain_len = total_plain_len // len(details)
    avg_html_len = total_html_len // len(details)

    max_plain = max(len(detail.text_plain) for detail in details)
    min_plain = min(len(detail.text_plain) for detail in details)

    max_html = max(len(detail.text_html) for detail in details)
    min_html = min(len(detail.text_html) for detail in details)

    logger.info("内容统计:")
    logger.info("  纯文本总长度: %,d 字符", total_plain_len)
    logger.info("  HTML 总长度: %,d 字符", total_html_len)
    logger.info("  平均纯文本长度: %,d 字符", avg_plain_len)
    logger.info("  平均 HTML 长度: %,d 字符", avg_html_len)

    logger.info("长度范围:")
    logger.info("  纯文本: %,d ~ %,d 字符", min_plain, max_plain)
    logger.info("  HTML: %,d ~ %,d 字符", min_html, max_html)

    sender_count: dict[str, int] = {}

    for detail in details:
        sender = detail.sender or "(未知发件人)"
        sender_count[sender] = sender_count.get(sender, 0) + 1

    logger.info("发件人统计:")

    for sender, count in sorted(
        sender_count.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        logger.info("  %s: %s 封", sender, count)

    total = len(details)

    has_plain = sum(bool(detail.text_plain) for detail in details)
    has_html = sum(bool(detail.text_html) for detail in details)
    has_both = sum(bool(detail.text_plain and detail.text_html) for detail in details)

    empty_plain = total - has_plain
    empty_html = total - has_html

    logger.info("内容类型:")
    logger.info(
        "  包含纯文本: %s/%s (%.1f%%)",
        has_plain,
        total,
        has_plain / total * 100,
    )
    logger.info(
        "  包含 HTML: %s/%s (%.1f%%)",
        has_html,
        total,
        has_html / total * 100,
    )
    logger.info(
        "  同时包含两者: %s/%s (%.1f%%)",
        has_both,
        total,
        has_both / total * 100,
    )

    logger.info("空内容:")
    logger.info(
        "  无纯文本: %s/%s (%.1f%%)",
        empty_plain,
        total,
        empty_plain / total * 100,
    )
    logger.info(
        "  无 HTML: %s/%s (%.1f%%)",
        empty_html,
        total,
        empty_html / total * 100,
    )


def find_special_emails(details: list[MailDetail]) -> None:
    """查找特殊邮件。"""
    logger.info("=" * 100)
    logger.info("特殊邮件检测")
    logger.info("=" * 100)

    # ===============================
    # 验证码
    # ===============================

    code_patterns = ("验证码", "code", "Code", "CODE", "验证")
    code_emails: list[MailDetail] = []

    for detail in details:
        text = detail.text_plain or ""

        if any(pattern in text for pattern in code_patterns):
            code_emails.append(detail)

    if code_emails:
        logger.info("发现 %s 封可能包含验证码的邮件", len(code_emails))

        for detail in code_emails:
            logger.info(
                "  邮件: %s | UID=%s",
                detail.subject or "(无主题)",
                detail.uid,
            )

            for line in (detail.text_plain or "").splitlines():
                if any(pattern in line for pattern in code_patterns):
                    logger.info("    %s", line.strip())

    else:
        logger.info("未发现包含验证码的邮件")

    # ===============================
    # 礼品码
    # ===============================

    gift_patterns = (
        "礼品码",
        "礼品",
        "gift",
        "GIFT",
        "兑换码",
        "激活码",
    )

    gift_emails: list[MailDetail] = []

    for detail in details:
        text = f"{detail.text_plain or ''}{detail.text_html or ''}"

        if any(pattern in text for pattern in gift_patterns):
            gift_emails.append(detail)

    if gift_emails:
        logger.info("发现 %s 封可能包含礼品码的邮件", len(gift_emails))

        for detail in gift_emails:
            logger.info(
                "  邮件: %s | UID=%s",
                detail.subject or "(无主题)",
                detail.uid,
            )

            for line in (detail.text_plain or "").splitlines():
                if any(pattern in line for pattern in gift_patterns):
                    logger.info("    %s", line.strip())

    else:
        logger.info("未发现包含礼品码的邮件")

    # ===============================
    # GLaDOS
    # ===============================

    glados_patterns = ("GLaDOS", "glados")

    glados_emails = [
        detail
        for detail in details
        if any(pattern in (detail.subject or "") for pattern in glados_patterns)
    ]

    if glados_emails:
        logger.info("发现 %s 封 GLaDOS 相关邮件", len(glados_emails))

        for detail in glados_emails:
            logger.info(
                "  %s | UID=%s",
                detail.subject or "(无主题)",
                detail.uid,
            )
    else:
        logger.info("未发现 GLaDOS 相关邮件")


def export_mail_data(details: list[MailDetail]) -> None:
    """导出邮件数据。"""
    export_data = [
        {
            "uid": detail.uid,
            "subject": detail.subject,
            "sender": detail.sender,
            "to": detail.to,
            "date": detail.date.isoformat(),
            "text_plain_length": len(detail.text_plain),
            "text_html_length": len(detail.text_html),
            "text_plain": detail.text_plain,
            "text_html": detail.text_html,
        }
        for detail in details
    ]

    filename = f"mail_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            export_data,
            file,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(
        "邮件数据已导出: %s | 共 %s 封",
        filename,
        len(export_data),
    )


def main() -> None:
    """测试邮件功能。"""
    email_client = EmailClient(
        username=EMAIL_USERNAME,
        password=EMAIL_PASSWORD,
        provider=EmailProvider.QQ,
    )

    try:
        with email_client.connection() as client:
            logger.info("=" * 100)
            logger.info("邮箱连接成功")
            logger.info("邮箱: %s", EMAIL_USERNAME)
            logger.info("服务商: %s", EmailProvider.QQ.value)
            logger.info("=" * 100)

            # ===============================
            # 获取邮件摘要
            # ===============================

            logger.info(
                "开始获取邮件摘要 | days=%s | folder=%s",
                EMAIL_DAYS,
                EMAIL_FOLDER,
            )

            summaries = email_client.list_mail_summaries(
                client,
                days=EMAIL_DAYS,
                folder=EMAIL_FOLDER,
            )

            logger.info(
                "邮件摘要获取完成 | 共 %s 封",
                len(summaries),
            )

            for index, summary in enumerate(summaries, 1):
                log_mail_summary(summary, index)

                if index % 10 == 0 and index < len(summaries):
                    input("按 Enter 继续查看下一批摘要...")

            # ===============================
            # 获取邮件详情
            # ===============================

            max_details = min(MAX_DETAILS, len(summaries))

            logger.info(
                "开始获取邮件详情 | count=%s",
                max_details,
            )

            details: list[MailDetail] = []
            failed_uids: list[int] = []

            for index, summary in enumerate(
                summaries[:max_details],
                1,
            ):
                logger.info(
                    "[%s/%s] 正在获取邮件详情 | UID=%s",
                    index,
                    max_details,
                    summary.uid,
                )

                try:
                    detail = email_client.get_mail(
                        client,
                        summary.uid,
                        folder=EMAIL_FOLDER,
                    )

                    if detail is None:
                        logger.warning(
                            "获取邮件详情失败 | UID=%s",
                            summary.uid,
                        )
                        failed_uids.append(summary.uid)
                        continue

                    details.append(detail)

                    logger.info(
                        "邮件详情获取成功 | UID=%s | Subject=%s",
                        detail.uid,
                        detail.subject or "(无主题)",
                    )

                    logger.debug(
                        "邮件内容长度 | UID=%s | text=%s | html=%s",
                        detail.uid,
                        len(detail.text_plain),
                        len(detail.text_html),
                    )

                    if index < max_details:
                        choice = (
                            input(
                                f"是否立即查看第 {index} 封邮件的完整内容？"
                                " (y/n，默认 n): "
                            )
                            .strip()
                            .lower()
                        )

                        if choice == "y":
                            log_mail_detail(detail, index)
                            input("按 Enter 继续...")

                except Exception:
                    logger.exception(
                        "获取邮件详情异常 | UID=%s",
                        summary.uid,
                    )
                    failed_uids.append(summary.uid)

            logger.info(
                "邮件详情获取完成 | 成功=%s | 失败=%s",
                len(details),
                len(failed_uids),
            )

            if failed_uids:
                logger.warning(
                    "获取失败的 UID: %s",
                    failed_uids,
                )

            # ===============================
            # 查看详细内容
            # ===============================

            if details:
                logger.info("开始查看邮件详细内容")

                for index, detail in enumerate(details, 1):
                    log_mail_detail(detail, index)

                    if index < len(details):
                        choice = (
                            input(
                                f"是否继续查看第 {index + 1} 封邮件？"
                                " (y/n，默认 y): "
                            )
                            .strip()
                            .lower()
                        )

                        if choice == "n":
                            break

                # ===============================
                # 统计
                # ===============================

                log_statistics(summaries, details)

                # ===============================
                # 特殊邮件
                # ===============================

                find_special_emails(details)

                # ===============================
                # 导出
                # ===============================

                export_choice = (
                    input("是否导出邮件数据到 JSON 文件？" " (y/n，默认 n): ")
                    .strip()
                    .lower()
                )

                if export_choice == "y":
                    export_mail_data(details)

            logger.info("=" * 100)
            logger.info("邮件测试完成")
            logger.info("=" * 100)

    except Exception:
        logger.exception("邮件测试失败")
        raise


def test_code_detect():
    from apps.glados.core.email import GiftCode, LoginCode

    """测试邮件功能。"""
    email_client = EmailClient(
        username=EMAIL_USERNAME,
        password=EMAIL_PASSWORD,
        provider=EmailProvider.QQ,
    )

    try:
        with email_client.connection() as client:
            logger.info("=" * 100)
            logger.info("邮箱连接成功")
            logger.info("邮箱: %s", EMAIL_USERNAME)
            logger.info("服务商: %s", EmailProvider.QQ.value)
            logger.info("=" * 100)

            # 测试登录验证码 uid=964 folder="INBOX"
            uid = 964
            folder = "INBOX"

            detail = email_client.get_mail(client, uid, folder=folder)
            logincode = LoginCode.from_plain("login", detail.text_plain)
            logger.info(f"登录验证码: {logincode}")

            # 测试礼品码 uid=1 folder="已兑换礼品码"
            uid = 1
            folder = "已兑换礼品码"

            detail = email_client.get_mail(client, uid, folder=folder)
            giftcode = GiftCode.from_html("gift", detail.text_html)
            logger.info(f"礼品码: {giftcode}")

    except Exception:
        logger.exception("邮件测试失败")
        raise


if __name__ == "__main__":
    test_code_detect()
    # main()
