from common.logger import logger
import datetime

from modules.glados.glados_back import GladosClient
from modules.glados.mailbox import MailBoxClient
from modules.glados.config import Config

def main():
    client = GladosClient("config.yaml")
    client.checkin_all()

def mail_test():
    # ---------------- 测试 / CLI 使用示例 ----------------
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

if __name__ == "__main__":
    mail_test()