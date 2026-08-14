import os

from dotenv import load_dotenv

from apps.glados.core.api import GladosAPI
from apps.glados.core.email import EmailTool
from apps.glados.core.parser import GladosParser
from utils.email import EmailClient, EmailProvider, MailDetail, MailSummary
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(
    name="tests.glados.test_auto_login.py",
    fmt_type="detailed",
    log_dir=temp(),
    console_level=10,
)

load_dotenv(env() / "development.env")


# ===============================
# 测试配置
# ===============================

EMAIL_USERNAME = os.environ["EMAIL_USERNAME"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_PROVIDER = os.environ["EMAIL_PROVIDER"]

EMAIL_FOLDER = "INBOX"
EMAIL_DAYS = 7
MAX_DETAILS = 10

USER = os.environ["USER"]


requestclient = RequestClient(proxies=[os.environ["PROXY"]])
emailclient = EmailClient(EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_PROVIDER)

api = GladosAPI(requestclient)
parser = GladosParser()
emailtool = EmailTool(emailclient)


auth_response = api.authorization(EMAIL_USERNAME)
auth_parser = parser.parse_authorization(auth_response)

if auth_parser.success:
    # 获取登录验证码
    login_code = emailtool.wait_login_code(
        USER,
        timeout=600,
        interval=10,
    )

    if login_code:
        # 验证码归属用户检查
        if login_code.user != USER:
            logger.error(
                "验证码归属用户不符合登录用户: expected=%s, actual=%s",
                USER,
                login_code.user,
            )
        else:
            # 调用登录 API
            login_response = api.login(
                USER,
                login_code.code,
            )

            # ===============================
            # 保存完整登录响应到日志
            # ===============================

            logger.info("========== GLaDOS 登录响应 ==========")
            logger.info("状态码: %s", login_response.status_code)
            logger.info("响应 URL: %s", login_response.url)
            logger.info("响应 Headers:\n%s", dict(login_response.headers))
            logger.info("响应 Cookies:\n%s", login_response.cookies.get_dict())
            logger.info("响应正文:\n%s", login_response.text)
            logger.info("======================================")
