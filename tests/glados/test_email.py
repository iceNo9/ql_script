# test_email.py
from utils.config import EmailConfig, GlobalConfigManager
from utils.log import get_logger

from modules.glados.core.email import EmailCodeExtractor, MailSummary, MailDetail



logger = get_logger(__name__)

def main():
    # 初始化配置
    global_config_manager = GlobalConfigManager(r"config\global.yaml")
    global_config = global_config_manager.read()
    email_config = global_config.email

    # 初始化提取器
    extractor = EmailCodeExtractor(email_config)

    logger.info("=== 测试 list_mail_summaries ===")
    try:
        summaries = extractor.list_mail_summaries(days=30)
        for s in summaries:
            logger.info(f"UID={s.uid}, Subject={s.subject}, Sender={s.sender}, To={s.to}, Date={s.date}")
    except Exception as e:
        logger.error(f"list_mail_summaries 出错: {e}")

    logger.info("=== 测试 list_mail_details ===")
    try:
        details = extractor.list_mail_details(days=7)
        for d in details[:5]:  # 只打印前5封邮件防止太多
            logger.info(f"UID={d.uid}, Subject={d.subject}, Sender={d.sender}, To={d.to}, Date={d.date}")
            logger.info(f"Text preview: {d.text_plain[:100]}...")
    except Exception as e:
        logger.error(f"list_mail_details 出错: {e}")

    logger.info("=== 测试 get_mail_detail_by_uid ===")
    summaries = extractor.list_mail_summaries(days=7)
    if summaries:
        test_uid = 365
        try:
            mail_detail = extractor.get_mail_detail_by_uid(test_uid)
            if mail_detail:
                logger.info(f"UID={test_uid} 邮件获取成功")
                logger.info(f"Subject={mail_detail.subject}, Sender={mail_detail.sender}, To={mail_detail.to}, Date={mail_detail.date}")
            else:
                logger.info(f"UID={test_uid} 邮件获取失败")
        except Exception as e:
            logger.error(f"get_mail_detail_by_uid 出错: {e}")

if __name__ == "__main__":
    main()
