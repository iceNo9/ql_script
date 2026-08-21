import json
import os

from dotenv import load_dotenv

from apps.baiyefee.core.api import BaiyefeeAPI
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(name="tests.baiyefee.test_api", fmt_type="detailed", log_dir=temp())
load_dotenv(env() / "development.env")

USERNAME = os.environ.get("BAIYEFEE_USERNAME", "")
PASSWD = os.environ.get("BAIYEFEE_PASSWD", "")

# Token 直接字符串
TOKEN = os.environ.get("BAIYEFEE_TOKEN", "").strip()

PROXY = os.environ.get("PROXY", "").strip()
if PROXY:
    # 有代理
    request_client = RequestClient(
        http_proxies=[PROXY],
        https_proxies=[PROXY],
    )
    logger.info(f"🔌 使用代理: {PROXY}")
else:
    # 无代理
    request_client = RequestClient()
    logger.info("🔌 不使用代理")

api = BaiyefeeAPI(request_client)
# 如果有 Token 则设置
if TOKEN:
    api.set_token(TOKEN)
    logger.info(f"🔑 已加载 Token: {TOKEN[:50]}...")
else:
    logger.info("🔑 未加载 Token")


def test_api_login():
    """测试 login 接口"""
    if not USERNAME or not PASSWD:
        logger.warning("⚠️ 未配置用户名或密码，跳过 login 测试")
        return None

    ret = api.login(USERNAME, PASSWD)

    logger.info("=" * 60)
    logger.info("📨 测试 login 接口")
    logger.info("=" * 60)

    # 打印 HTTP 状态码
    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    # 打印全部响应头
    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    # 打印响应内容
    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    # 判断是否是 JSON
    if "application/json" in content_type:
        try:
            data = ret.json()

            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")

            # 如果登录成功，提取 token 并设置
            if ret.ok and "token" in data:
                token = data["token"]
                api.set_token(token)
                logger.info(f"🔑 获取到 Token: {token[:50]}...")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        # 非 JSON，打印原始内容
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    logger.info("=" * 60)
    return ret


def test_api_checkin():
    """测试 checkin 接口"""
    ret = api.checkin()

    logger.info("=" * 60)
    logger.info("📨 测试 checkin 接口")
    logger.info("=" * 60)

    # 打印 HTTP 状态码
    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    # 打印全部响应头
    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    # 打印响应内容
    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    # 判断是否是 JSON
    if "application/json" in content_type:
        try:
            data = ret.json()

            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        # 非 JSON，打印原始内容
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    logger.info("=" * 60)
    return ret


def test_api_get_user_data():
    """测试 get_user_data 接口"""
    ret = api.get_user_data()

    logger.info("=" * 60)
    logger.info("📨 测试 get_user_data 接口")
    logger.info("=" * 60)

    # 打印 HTTP 状态码
    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    # 打印全部响应头
    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    # 打印响应内容
    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    # 判断是否是 JSON
    if "application/json" in content_type:
        try:
            data = ret.json()

            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        # 非 JSON，打印原始内容
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    logger.info("=" * 60)
    return ret


def test_api_get_sign_info():
    """测试 get_sign_info 接口"""
    ret = api.get_sign_info()

    logger.info("=" * 60)
    logger.info("📨 测试 get_sign_info 接口")
    logger.info("=" * 60)

    # 打印 HTTP 状态码
    logger.info(f"📊 状态码: {ret.status_code} {ret.reason}")

    # 打印全部响应头
    logger.info("📋 全部响应头:")
    for key, value in ret.headers.items():
        logger.info(f"    {key}: {value}")

    # 打印响应内容
    content_type = ret.headers.get("content-type", "").lower()
    logger.info(f"📦 响应内容 (Content-Type: {content_type})")

    # 判断是否是 JSON
    if "application/json" in content_type:
        try:
            data = ret.json()

            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logger.info(f"✅ JSON 数据:\n{formatted}")
        except ValueError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
            logger.info(f"原始内容: {ret.text[:500]}")
    else:
        # 非 JSON，打印原始内容
        text = ret.text
        logger.info(f"📄 原始内容:\n{text}")

    logger.info("=" * 60)
    return ret


def run_all_tests():
    """运行所有 API 测试"""
    logger.info("🚀 开始运行 Baiyefee API 测试")
    logger.info("=" * 60)

    # 1. 测试登录
    logger.info("\n[1/4] 测试登录接口...")
    login_result = test_api_login()

    # 如果登录成功且有 token，后续测试使用 token 认证
    if login_result and login_result.ok:
        try:
            data = login_result.json()
            if "token" in data:
                api.set_token(data["token"])
                logger.info("✅ 已设置 Token 认证")
        except Exception:
            logger.exception("获取token异常 ")

    # 2. 测试获取签到信息
    logger.info("\n[2/4] 测试获取签到信息接口...")
    test_api_get_sign_info()

    # 3. 测试签到
    logger.info("\n[3/4] 测试签到接口...")
    test_api_checkin()

    # 4. 测试获取用户数据
    logger.info("\n[4/4] 测试获取用户数据接口...")
    test_api_get_user_data()

    logger.info("\n" + "=" * 60)
    logger.info("✅ 所有 Baiyefee API 测试完成")


if __name__ == "__main__":
    run_all_tests()
