# tests/southplus/test_api.py

import os

import cookiesparser
from dotenv import load_dotenv

from apps.southplus.core.api import SouthPlusAPI
from utils.log import get_logger
from utils.paths import env, temp
from utils.request_client import RequestClient

logger = get_logger(
    name="tests.southplus.test_api",
    fmt_type="detailed",
    log_dir=temp(),
)

load_dotenv(env() / "development.env")


def parse_cookies(value: str) -> dict[str, str]:
    """
    使用 cookies 库解析 Cookie Header。

    Args:
        value:
            Cookie Header 字符串，例如：

            a=xxx; b=xxx

    Returns:
        Cookie 名称和值组成的字典。
    """

    value = value.strip()

    if not value:
        return {}

    cookies = cookiesparser.parse(value)

    return {name: cookie.value for name, cookie in cookies.items()}


# ============================================================================
# 环境变量
# ============================================================================

USERNAME = os.environ.get(
    "SOUTHPLUS_USERNAME",
    "",
).strip()


# Cookie 字符串：
#
# SOUTHPLUS_COOKIES="{'a': 'xxx', 'b': 'xxx'}"
#
# 使用 ast.literal_eval() 反序列化。
COOKIES_STR = os.environ.get(
    "SOUTHPLUS_COOKIES",
    "",
).strip()

COOKIES = parse_cookies(COOKIES_STR)

if COOKIES:
    logger.info(
        "🍪 已加载 Cookie: %s",
        list(COOKIES.keys()),
    )
else:
    logger.warning(
        "⚠️ 未加载 Cookie",
    )


# ============================================================================
# RequestClient
# ============================================================================

PROXY = os.environ.get(
    "PROXY",
    "",
).strip()


if PROXY:
    request_client = RequestClient(
        http_proxies=[PROXY],
        https_proxies=[PROXY],
    )

    logger.info(
        "🔌 使用代理: %s",
        PROXY,
    )
else:
    request_client = RequestClient()

    logger.info(
        "🔌 不使用代理",
    )


# ============================================================================
# API
# ============================================================================

api = SouthPlusAPI(request_client)


# 如果有 Cookie，则设置。
if COOKIES:
    api.set_cookies(COOKIES)

    logger.info(
        "🍪 已加载 Cookie: %s",
        list(COOKIES.keys()),
    )
else:
    logger.info(
        "🍪 未加载 Cookie",
    )


# ============================================================================
# 响应文件
# ============================================================================

RESPONSE_DIR = temp() / "southplus"

RESPONSE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def _save_response(
    filename: str,
    response,
) -> None:
    """
    将 API 响应正文保存到 temp/southplus/。

    Args:
        filename:
            输出文件名。

        response:
            requests.Response。
    """

    path = RESPONSE_DIR / filename

    path.write_text(
        response.text,
        encoding="utf-8",
    )

    logger.info(
        "💾 响应内容已保存: %s",
        path,
    )


# ============================================================================
# 辅助函数
# ============================================================================


def _log_response(
    name: str,
    response,
    *,
    max_length: int = 2000,
) -> None:
    """
    输出 API Response 调试信息。
    """

    logger.info("=" * 60)
    logger.info(
        "📨 测试 %s",
        name,
    )
    logger.info("=" * 60)

    logger.info(
        "📊 状态码: %s %s",
        response.status_code,
        response.reason,
    )

    logger.info("📋 全部响应头:")

    for key, value in response.headers.items():
        logger.info(
            "    %s: %s",
            key,
            value,
        )

    content_type = response.headers.get(
        "content-type",
        "",
    ).lower()

    logger.info(
        "📦 响应内容 (Content-Type: %s)",
        content_type,
    )

    text = response.text

    logger.info(
        "📄 响应内容（前 %s 字符）:\n%s",
        max_length,
        text[:max_length],
    )

    logger.info(
        "📄 响应总长度: %s 字符",
        len(text),
    )

    logger.info("=" * 60)


# ============================================================================
# Profile
# ============================================================================


def test_api_get_profile():
    """
    测试获取用户 Profile。
    """

    ret = api.get_profile()

    _log_response(
        "get_profile 接口 (/userpay.php)",
        ret,
    )

    _save_response(
        "get_profile.html",
        ret,
    )

    return ret


# ============================================================================
# Tasks
# ============================================================================


def test_api_get_tasks():
    """
    测试获取任务页面。
    """

    ret = api.get_tasks()

    _log_response(
        "get_tasks 接口",
        ret,
    )

    _save_response(
        "get_tasks.html",
        ret,
    )

    return ret


def test_api_get_tasks_actions():
    """
    测试获取进行中的任务。
    """

    ret = api.get_tasks_actions()

    _log_response(
        "get_tasks_actions 接口",
        ret,
    )

    _save_response(
        "get_tasks_actions.html",
        ret,
    )

    return ret


# ============================================================================
# 每日签到
# ============================================================================


def test_api_checkin_daily():
    """
    测试每日签到。

    H_name=tasks
    action=ajax
    actions=job
    cid=15
    """

    ret = api.checkin_daily()

    _log_response(
        "checkin_daily 接口",
        ret,
    )

    _save_response(
        "checkin_daily.html",
        ret,
    )

    return ret


# ============================================================================
# 每周签到
# ============================================================================


def test_api_checkin_weekly():
    """
    测试每周签到。

    H_name=tasks
    action=ajax
    actions=job
    cid=14
    """

    ret = api.checkin_weekly()

    _log_response(
        "checkin_weekly 接口",
        ret,
    )

    _save_response(
        "checkin_weekly.html",
        ret,
    )

    return ret


# ============================================================================
# 每日任务完成
# ============================================================================


def test_api_complete_daily():
    """
    测试完成每日任务。

    H_name=tasks
    action=ajax
    actions=job2
    cid=15
    """

    ret = api.complete_daily()

    _log_response(
        "complete_daily 接口",
        ret,
    )

    _save_response(
        "complete_daily.html",
        ret,
    )

    return ret


# ============================================================================
# 每周任务完成
# ============================================================================


def test_api_complete_weekly():
    """
    测试完成每周任务。

    H_name=tasks
    action=ajax
    actions=job2
    cid=14
    """

    ret = api.complete_weekly()

    _log_response(
        "complete_weekly 接口",
        ret,
    )

    _save_response(
        "complete_weekly.html",
        ret,
    )

    return ret


# ============================================================================
# 测试入口
# ============================================================================


def run_all_tests():
    """
    运行所有 SouthPlus API 测试。
    """

    logger.info(
        "🚀 开始运行 SouthPlus API 测试",
    )

    logger.info("=" * 60)

    # ------------------------------------------------------------------------
    # 基础信息
    # ------------------------------------------------------------------------

    if USERNAME:
        logger.info(
            "👤 当前测试账号: %s",
            USERNAME,
        )
    else:
        logger.warning(
            "⚠️ 未配置 SOUTHPLUS_USERNAME",
        )

    if COOKIES:
        logger.info(
            "🍪 当前 Cookie 数量: %s",
            len(COOKIES),
        )
    else:
        logger.warning(
            "⚠️ 未配置 SOUTHPLUS_COOKIES，" "后续需要登录状态的请求可能失败",
        )

    # ------------------------------------------------------------------------
    # 1. Profile
    # ------------------------------------------------------------------------

    logger.info(
        "\n[1/7] 测试 Profile 接口...",
    )

    profile_result = test_api_get_profile()

    if profile_result.ok:
        logger.info(
            "✅ Profile 获取成功",
        )
    else:
        logger.warning(
            "❌ Profile 获取失败",
        )

    # ------------------------------------------------------------------------
    # 2. Tasks
    # ------------------------------------------------------------------------

    logger.info(
        "\n[2/7] 测试任务页面接口...",
    )

    tasks_result = test_api_get_tasks()

    if tasks_result.ok:
        logger.info(
            "✅ Tasks 获取成功",
        )
    else:
        logger.warning(
            "❌ Tasks 获取失败",
        )

    # ------------------------------------------------------------------------
    # 3. Tasks Actions
    # ------------------------------------------------------------------------

    logger.info(
        "\n[3/7] 测试进行中任务接口...",
    )

    tasks_actions_result = test_api_get_tasks_actions()

    if tasks_actions_result.ok:
        logger.info(
            "✅ Tasks Actions 获取成功",
        )
    else:
        logger.warning(
            "❌ Tasks Actions 获取失败",
        )

    # ------------------------------------------------------------------------
    # 4. 每日签到
    # ------------------------------------------------------------------------

    logger.info(
        "\n[4/7] 测试每日签到接口...",
    )

    daily_result = test_api_checkin_daily()

    if daily_result.ok:
        logger.info(
            "✅ 每日签到请求成功",
        )
    else:
        logger.warning(
            "❌ 每日签到请求失败",
        )

    # ------------------------------------------------------------------------
    # 5. 每周签到
    # ------------------------------------------------------------------------

    logger.info(
        "\n[5/7] 测试每周签到接口...",
    )

    weekly_result = test_api_checkin_weekly()

    if weekly_result.ok:
        logger.info(
            "✅ 每周签到请求成功",
        )
    else:
        logger.warning(
            "❌ 每周签到请求失败",
        )

    # ------------------------------------------------------------------------
    # 6. 完成每日任务
    # ------------------------------------------------------------------------

    logger.info(
        "\n[6/7] 测试完成每日任务接口...",
    )

    complete_daily_result = test_api_complete_daily()

    if complete_daily_result.ok:
        logger.info(
            "✅ 完成每日任务请求成功",
        )
    else:
        logger.warning(
            "❌ 完成每日任务请求失败",
        )

    # ------------------------------------------------------------------------
    # 7. 完成每周任务
    # ------------------------------------------------------------------------

    logger.info(
        "\n[7/7] 测试完成每周任务接口...",
    )

    complete_weekly_result = test_api_complete_weekly()

    if complete_weekly_result.ok:
        logger.info(
            "✅ 完成每周任务请求成功",
        )
    else:
        logger.warning(
            "❌ 完成每周任务请求失败",
        )

    # ------------------------------------------------------------------------
    # 当前 Cookie
    # ------------------------------------------------------------------------

    current_cookies = api.get_cookies()

    if current_cookies:
        logger.info(
            "🍪 当前 Cookies: %s",
            current_cookies,
        )

    logger.info(
        "\n" + "=" * 60,
    )

    logger.info(
        "✅ 所有 SouthPlus API 测试完成",
    )


# ============================================================================
# Main
# ============================================================================


if __name__ == "__main__":
    run_all_tests()
