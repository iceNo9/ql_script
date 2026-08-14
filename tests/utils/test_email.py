from utils.email import EmailClient, EmailProvider

USERNAME = "你的QQ邮箱"
PASSWORD = "你的QQ邮箱授权码"


def main() -> None:
    email_client = EmailClient(
        username=USERNAME,
        password=PASSWORD,
        provider=EmailProvider.QQ,
    )

    with email_client.connection() as client:
        print("连接邮箱成功")

        summaries = email_client.list_mail_summaries(
            client, days=7, folder="已兑换礼品码"
        )

        print(f"最近 7 天邮件数量: {len(summaries)}")

        print("\n========== 邮件摘要 ==========")

        for summary in summaries:
            print(f"UID:    {summary.uid}")
            print(f"主题:   {summary.subject}")
            print(f"发件人: {summary.sender}")
            print(f"收件人: {summary.to}")
            print(f"日期:   {summary.date}")
            print("-" * 60)

        print("\n========== 前 3 封邮件详情 ==========")

        for summary in summaries[:3]:
            print(f"\nUID: {summary.uid}")
            print(f"主题: {summary.subject}")

            detail = email_client.get_mail(
                client,
                summary.uid,
            )

            if detail is None:
                print("获取邮件详情失败")
                continue

            print(f"发件人: {detail.sender}")
            print(f"收件人: {detail.to}")
            print(f"日期:   {detail.date}")

            print("\n--- text/plain ---")
            print(detail.text_plain)

            print("\n--- text/html ---")
            print(detail.text_html)

            print("=" * 60)


if __name__ == "__main__":
    main()
