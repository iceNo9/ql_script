# tests/hifiti/test_parser.py

"""
Hifiti Parser 快速验证
使用实际 API 接口数据测试解析器
"""

import ast
import json
import os

from dotenv import load_dotenv

from apps.hifiti.core.api import HifitiAPI
from apps.hifiti.core.parser import HifitiParser
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(
    name="tests.hifiti.test_parser", fmt_type="detailed", log_dir=temp()
)
load_dotenv(env() / "development.env")

USERNAME = os.environ.get("HIFITI_USERNAME", "")
PASSWD = os.environ.get("HIFITI_PASSWD", "")

COOKIES_STR = os.environ.get("HIFITI_COOKIES", "").strip()
COOKIES = {}
if COOKIES_STR:
    try:
        COOKIES = ast.literal_eval(COOKIES_STR)
        if not isinstance(COOKIES, dict):
            COOKIES = {}
    except (SyntaxError, ValueError):
        logger.warning(f"⚠️ Cookie 字符串解析失败: {COOKIES_STR}")

PROXY = os.environ.get("PROXY", "").strip()
if PROXY:
    request_client = RequestClient(
        http_proxies=[PROXY],
        https_proxies=[PROXY],
    )
    logger.info(f"🔌 使用代理: {PROXY}")
else:
    request_client = RequestClient()
    logger.info("🔌 不使用代理")

api = HifitiAPI(request_client)
parser = HifitiParser()

if COOKIES:
    api.set_cookies(COOKIES)
    logger.info(f"🍪 已加载 Cookie: {list(COOKIES.keys())}")
else:
    logger.info("🍪 未加载 Cookie")


def print_response_detail(response, title: str):
    """打印响应详情"""
    logger.info("=" * 80)
    logger.info(f"📨 {title}")
    logger.info("=" * 80)
    logger.info(f"📊 状态码: {response.status_code} {response.reason}")
    logger.info(f"📋 Content-Type: {response.headers.get('content-type', '未知')}")

    content_type = response.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        try:
            data = response.json()
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"📦 JSON 响应:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {response.text[:500]}")
    elif "text/html" in content_type:
        logger.info(f"📄 HTML 响应 (前 500 字符):\n{response.text[:500]}...")
    else:
        logger.info(f"📄 原始内容 (前 500 字符):\n{response.text[:500]}...")


def verify_login():
    """验证登录 API + Parser"""
    logger.info("\n🔐 验证登录流程")

    if not USERNAME or not PASSWD:
        logger.warning("⚠️ 未配置用户名密码，跳过登录验证")
        return None

    # 1. API 请求
    response = api.login(USERNAME, PASSWD)
    print_response_detail(response, "登录 API 响应")

    # 2. Parser 解析
    result = parser.parse_login(response)

    logger.info("-" * 80)
    logger.info("📋 Parser 解析结果:")
    logger.info(f"  success: {result.success}")
    logger.info(f"  error: {result.error}")
    if result.success and result.cookies:
        logger.info(f"  cookies: {list(result.cookies.keys())}")
    logger.info("=" * 80)

    return result


def verify_checkin():
    """验证签到 API + Parser"""
    logger.info("\n📝 验证签到流程")

    # 1. API 请求
    response = api.checkin()
    print_response_detail(response, "签到 API 响应")

    # 2. Parser 解析
    result = parser.parse_checkin(response)

    logger.info("-" * 80)
    logger.info("📋 Parser 解析结果:")
    logger.info(f"  success: {result.success}")
    logger.info(f"  error: {result.error}")
    if result.success:
        logger.info(f"  already_checked: {result.already_checked}")
        logger.info(f"  rank: {result.rank}")
        logger.info(f"  checkin_gold: {result.checkin_gold}")
        logger.info(f"  message: {result.message}")
    logger.info("=" * 80)

    return result


def verify_user_data():
    """验证用户数据 API + Parser"""
    logger.info("\n👤 验证用户数据流程")

    # 1. API 请求
    response = api.get_user_data()
    print_response_detail(response, "用户数据 API 响应")

    # 2. Parser 解析
    result = parser.parse_user_data(response)

    logger.info("-" * 80)
    logger.info("📋 Parser 解析结果:")
    logger.info(f"  success: {result.success}")
    logger.info(f"  error: {result.error}")
    if result.success:
        logger.info(f"  gold: {result.gold}")
    logger.info("=" * 80)

    return result


def main():
    """主流程：依次验证各个接口"""
    logger.info("🚀 开始 Hifiti Parser 快速验证")
    logger.info("=" * 80)

    # 检查认证状态
    has_auth = bool(USERNAME and PASSWD) or bool(COOKIES)
    if not has_auth:
        logger.error("❌ 未配置认证信息 (USERNAME/PASSWD 或 COOKIES)")
        logger.info("请在 development.env 中配置:")
        logger.info("  HIFITI_USERNAME=your_email")
        logger.info("  HIFITI_PASSWD=your_password")
        logger.info("  或")
        logger.info("  HIFITI_COOKIES={'key': 'value'}")
        return

    # 1. 登录（如果有用户名密码）
    if USERNAME and PASSWD:
        login_result = verify_login()
        if login_result and login_result.success:
            logger.info("✅ 登录成功，Cookies 已自动保存")
    else:
        logger.info("⏭️ 跳过登录验证（使用 Cookie 认证）")

    # 2. 用户数据
    user_result = verify_user_data()

    # 3. 签到
    checkin_result = verify_checkin()

    # 总结
    logger.info("\n" + "=" * 80)
    logger.info("📊 验证总结")
    logger.info("=" * 80)

    if USERNAME and PASSWD:
        logger.info(
            f"  登录: {'✅' if login_result and login_result.success else '❌'}"
        )
    else:
        logger.info("  登录: ⏭️ 跳过")

    logger.info(f"  用户数据: {'✅' if user_result and user_result.success else '❌'}")
    if user_result and user_result.success:
        logger.info(f"    金币: {user_result.gold}")

    logger.info(
        f"  签到: {'✅' if checkin_result and checkin_result.success else '❌'}"
    )
    if checkin_result and checkin_result.success:
        if checkin_result.already_checked:
            logger.info("    状态: 今日已签到")
        else:
            logger.info(f"    获得: {checkin_result.checkin_gold} 金币")
            logger.info(f"    排名: {checkin_result.rank}")

    logger.info("=" * 80)


if __name__ == "__main__":
    main()
