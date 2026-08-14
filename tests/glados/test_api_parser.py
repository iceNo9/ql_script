import ast
import json
import os

from dotenv import load_dotenv

from apps.glados.core.api import GladosAPI
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(
    name="tests.glados.test_api_parser", fmt_type="detailed", log_dir=temp()
)
load_dotenv(env() / "development.env")

COOKIE = ast.literal_eval(os.environ["COOKIE"])

requestclient = RequestClient(proxies=[os.environ["PROXY"]])
api = GladosAPI(requestclient)
api.set_cookies(COOKIE)

email = os.environ["USER"]


def test_api_authorization():
    """测试 authorization 接口"""
    ret = api.authorization(email)

    logger.info("=" * 60)
    logger.info("📨 测试 authorization 接口")
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

    from apps.glados.core.parser import GladosParser

    parser = GladosParser()
    result = parser.parse_checkin(ret)

    logger.info("=" * 60)
    logger.info("📊 签到结果解析:")
    logger.info("=" * 60)
    logger.info(f"   ✅ 解析成功: {result.success}")
    logger.info(f"   📅 今日已签到: {result.already_checked}")
    logger.info(f"   ⭐ 获得积分: {result.points}")
    logger.info(f"   🔥 连续签到: {result.streak} 天")
    logger.info(f"   💬 消息: {result.message}")
    if result.total_balance is not None:
        logger.info(f"   💰 当前总积分: {result.total_balance}")
    if result.error:
        logger.error(f"   ❌ 错误信息: {result.error}")
    logger.info("=" * 60)


if __name__ == "__main__":
    test_api_checkin()
