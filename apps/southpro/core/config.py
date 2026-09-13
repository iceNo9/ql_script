# apps/southpro/core/config.py

"""
SouthPro 应用配置模块。

负责：

- 定义 SouthPro 应用配置 Model
- 定义单个 SouthPro 账号配置 Model
- 从全局配置模块加载 config/southpro.yaml
- 初始化 SouthPro 加密密钥
- 首次运行时创建 SouthPro 配置模板

不负责：

- SouthPro 业务逻辑
- 账号登录
- Cookie 获取与刷新
"""

from dataclasses import dataclass, field

from ruamel.yaml.comments import CommentedMap

from utils.config import config_exists, load_config, save_config
from utils.crypto import generate_key

# ============================================================================
# 配置 Model
# ============================================================================


@dataclass
class SouthProAccountConfig:
    """
    单个 SouthPro 账号配置。

    一个账号对应一个用户名。
    """

    username: str
    cookies: str = ""


@dataclass
class SouthProConfig:
    """
    SouthPro 应用配置。

    一个 SouthPro 应用可以配置多个账号。
    """

    encryption_key: str
    user_agent: str
    accounts: list[SouthProAccountConfig] = field(default_factory=list)


# ============================================================================
# 默认配置模板
# ============================================================================


def _create_default_config() -> CommentedMap:
    """
    创建 SouthPro 默认配置模板。

    首次运行时生成：

        encryption_key: <自动生成的密钥>
        user_agent: <默认 User-Agent>
        accounts: []

    同时在文件顶部生成完整的账号配置模板注释。

    Returns:
        CommentedMap:
            SouthPro 默认配置。
    """

    config = CommentedMap()

    # ------------------------------------------------------------------------
    # 文件顶部说明
    # ------------------------------------------------------------------------

    config.yaml_set_start_comment("""
        SouthPro 应用配置。

        本文件由程序首次启动时自动生成。

        账号配置模板：

        accounts:
          - username: ""
            cookies: ""   # 登录成功后自动保存，无需手动填写

        请将账号模板复制到 accounts 列表中。
        """.strip())

    # ------------------------------------------------------------------------
    # 加密密钥
    # ------------------------------------------------------------------------

    config["encryption_key"] = generate_key()

    config.yaml_set_comment_before_after_key(
        "encryption_key",
        before=(
            "SouthPro 应用加密密钥。\n"
            "\n"
            "该密钥由程序首次启动时自动生成。\n"
            "请勿修改，否则已保存的 Cookies 将无法解密。"
        ),
    )

    # ------------------------------------------------------------------------
    # User-Agent
    # ------------------------------------------------------------------------

    config["user_agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )

    config.yaml_set_comment_before_after_key(
        "user_agent",
        before=(
            "South Plus 请求使用的 User-Agent。\n"
            "\n"
            "该值应与获取 Cookies 时使用的浏览器 User-Agent 保持一致。\n"
            "如果手动导入浏览器 Cookies，请填写获取 Cookies 时浏览器的 User-Agent。\n"
            "修改浏览器版本后，如果现有 Cookies 无法使用，请同步更新此字段。"
        ),
    )

    # ------------------------------------------------------------------------
    # 账号列表
    # ------------------------------------------------------------------------

    config["accounts"] = []

    config.yaml_set_comment_before_after_key(
        "accounts",
        before=(
            "SouthPro 账号列表。\n"
            "\n"
            "可以配置多个账号。\n"
            "复制上面的账号模板到 accounts: 下方即可。\n"
            "\n"
            "cookies 字段在登录成功后自动保存，格式为：\n"
            "  key1=value1; key2=value2; key3=value3\n"
            "\n"
            "如需手动导入，可从浏览器开发者工具复制 Cookie。"
        ),
    )

    return config


# ============================================================================
# 配置加载
# ============================================================================


def load_southpro_config() -> SouthProConfig | None:
    """
    加载 SouthPro 应用配置。

    对应：

        config/southpro.yaml

    如果配置文件不存在：

    1. 自动生成加密密钥。
    2. 创建带完整中文注释的配置模板。
    3. 保存到 config/southpro.yaml。
    4. 返回 None。

    返回 None 表示：

        SouthPro 配置文件刚刚初始化，
        当前还没有正式加载应用配置。

    如果配置文件已经存在，则正常加载并返回 SouthProConfig。

    Returns:
        SouthProConfig | None:
            配置加载成功返回 SouthProConfig。
            首次初始化配置文件返回 None。
    """

    # ------------------------------------------------------------------------
    # 首次运行
    # ------------------------------------------------------------------------

    if not config_exists("southpro"):
        data = _create_default_config()

        save_config("southpro", data)

        return None

    # ------------------------------------------------------------------------
    # 正常加载
    # ------------------------------------------------------------------------

    data = load_config("southpro")

    encryption_key = data.get("encryption_key")

    # 如果旧配置没有 encryption_key，
    # 自动生成并持久化。
    if not encryption_key:
        encryption_key = generate_key()
        data["encryption_key"] = encryption_key

        save_config("southpro", data)

    # ------------------------------------------------------------------------
    # User-Agent
    # ------------------------------------------------------------------------

    user_agent = data.get("user_agent")

    # 兼容旧配置：
    # 如果旧配置没有 user_agent，则使用默认 Chrome User-Agent，
    # 并持久化到配置文件。
    if not user_agent:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        )

        data["user_agent"] = user_agent

        save_config("southpro", data)

    # ------------------------------------------------------------------------
    # 加载账号
    # ------------------------------------------------------------------------

    accounts = []

    for account in data.get("accounts", []):
        account = dict(account)

        # 确保 cookies 字段存在，兼容旧配置。
        if "cookies" not in account:
            account["cookies"] = ""

        accounts.append(SouthProAccountConfig(**account))

    return SouthProConfig(
        encryption_key=encryption_key,
        user_agent=user_agent,
        accounts=accounts,
    )


__all__ = [
    "SouthProAccountConfig",
    "SouthProConfig",
    "load_southpro_config",
]
