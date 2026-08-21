# tests\hifiti\test_api.py

import ast
import json
import os

from dotenv import load_dotenv

from apps.hifiti.core.api import HifitiAPI
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(name="tests.hifiti.test_api", fmt_type="detailed", log_dir=temp())
load_dotenv(env() / "development.env")

USERNAME = os.environ.get("HIFITI_USERNAME", "")
PASSWD = os.environ.get("HIFITI_PASSWD", "")

# Cookie 字典（从环境变量读取并反序列化）
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
# 如果有 Cookie 则设置
if COOKIES:
    api.set_cookies(COOKIES)
    logger.info(f"🍪 已加载 Cookie: {list(COOKIES.keys())}")
else:
    logger.info("🍪 未加载 Cookie")


def test_api_login():
    """测试 login 接口"""
    if not USERNAME or not PASSWD:
        logger.warning("⚠️ 未配置用户名或密码，跳过 login 测试")
        return None

    ret = api.login(USERNAME, PASSWD)

    logger.info("=" * 60)
    logger.info("📨 测试 login 接口")
    logger.info("=" * 60)

    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    if "application/json" in content_type:
        try:
            data = ret.json()
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    # 打印登录后保存的 cookies
    cookies = api.get_cookies()
    if cookies:
        logger.info(f"🍪 当前 Cookies: {cookies}")

    logger.info("=" * 60)
    return ret


def test_api_checkin():
    """测试 checkin 接口"""
    ret = api.checkin()

    logger.info("=" * 60)
    logger.info("📨 测试 checkin 接口")
    logger.info("=" * 60)

    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    if "application/json" in content_type:
        try:
            data = ret.json()
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    logger.info("=" * 60)
    return ret


def test_api_get_user_data():
    """测试 get_user_data 接口"""
    ret = api.get_user_data()

    logger.info("=" * 60)
    logger.info("📨 测试 get_user_data 接口 (/my-credits.htm)")
    logger.info("=" * 60)

    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    if "text/html" in content_type:
        text = ret.text
        logger.info(f"📄 HTML 内容（前 2000 字符）:\n{text[:2000]}...")
        logger.info(f"📄 HTML 总长度: {len(text)} 字符")
    else:
        text = ret.text
        logger.info(f"📄 原始内容（前 500 字符）:\n{text[:500]}...")

    logger.info("=" * 60)
    return ret


def run_all_tests():
    """运行所有 API 测试"""
    logger.info("🚀 开始运行 Hifiti API 测试")
    logger.info("=" * 60)

    # 1. 测试登录（如果有用户名密码）
    if USERNAME and PASSWD:
        logger.info("\n[1/3] 测试登录接口...")
        login_result = test_api_login()
        if login_result and login_result.ok:
            logger.info("✅ 登录成功，cookies 已自动保存")
            cookies = api.get_cookies()
            if cookies:
                logger.info(f"🍪 当前 Cookies: {cookies}")
    else:
        logger.info("\n[1/3] 跳过登录测试（未配置用户名密码）")
        if not COOKIES:
            logger.warning("⚠️ 未配置用户名密码或 Cookie，后续测试可能失败")

    # 2. 测试获取用户数据
    logger.info("\n[2/3] 测试获取用户数据接口...")
    test_api_get_user_data()

    # 3. 测试签到
    logger.info("\n[3/3] 测试签到接口...")
    test_api_checkin()

    logger.info("\n" + "=" * 60)
    logger.info("✅ 所有 Hifiti API 测试完成")


if __name__ == "__main__":
    run_all_tests()
