# apps\hifiti\core\config.py

"""
Hifiti 应用配置模块。

负责：

- 定义 Hifiti 应用配置 Model
- 定义单个 Hifiti 账号配置 Model
- 从全局配置模块加载 config/hifiti.yaml
- 初始化 Hifiti 加密密钥
- 首次运行时创建 Hifiti 配置模板

不负责：

- Hifiti 业务逻辑
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
class HifitiAccountConfig:
    """
    单个 Hifiti 账号配置。

    一个账号对应一个用户名。
    """

    username: str
    passwd: str
    cookies: str = ""  # 改为 str，存储 cookie 字符串


@dataclass
class HifitiConfig:
    """
    Hifiti 应用配置。

    一个 Hifiti 应用可以配置多个账号。
    """

    encryption_key: str
    accounts: list[HifitiAccountConfig] = field(default_factory=list)


# ============================================================================
# 默认配置模板
# ============================================================================


def _create_default_config() -> CommentedMap:
    """
    创建 Hifiti 默认配置模板。

    首次运行时生成：

        encryption_key: <自动生成的密钥>
        accounts: []

    同时在文件顶部生成完整的账号配置模板注释。

    Returns:
        CommentedMap:
            Hifiti 默认配置。
    """
    config = CommentedMap()

    # ------------------------------------------------------------------------
    # 文件顶部说明
    # ------------------------------------------------------------------------

    config.yaml_set_start_comment("""
    Hifiti 应用配置。

    本文件由程序首次启动时自动生成。

    账号配置模板：

    accounts:
      - username: ""
        passwd: ""
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
            "Hifiti 应用加密密钥。\n"
            "\n"
            "该密钥由程序首次启动时自动生成。\n"
            "请勿修改，否则已保存的 Cookies 将无法解密。"
        ),
    )

    # ------------------------------------------------------------------------
    # 账号列表
    # ------------------------------------------------------------------------

    config["accounts"] = []

    config.yaml_set_comment_before_after_key(
        "accounts",
        before=(
            "Hifiti 账号列表。\n"
            "\n"
            "可以配置多个账号。\n"
            "复制上面的账号模板到 accounts: 下方即可。\n"
            "\n"
            "cookies 字段在登录成功后自动保存，格式为：\n"
            "  bbs_sid=xxx; server_name_session=xxx; bbs_token=xxx\n"
            "\n"
            "如需手动导入，可从浏览器开发者工具复制。"
        ),
    )

    return config


# ============================================================================
# 配置加载
# ============================================================================


def load_hifiti_config() -> HifitiConfig | None:
    """
    加载 Hifiti 应用配置。

    对应：

        config/hifiti.yaml

    如果配置文件不存在：

    1. 自动生成加密密钥。
    2. 创建带完整中文注释的配置模板。
    3. 保存到 config/hifiti.yaml。
    4. 返回 None。

    返回 None 表示：

        Hifiti 配置文件刚刚初始化，
        当前还没有正式加载应用配置。

    如果配置文件已经存在，则正常加载并返回 HifitiConfig。

    Returns:
        HifitiConfig | None:
            配置加载成功返回 HifitiConfig。
            首次初始化配置文件返回 None。
    """

    # ------------------------------------------------------------------------
    # 首次运行
    # ------------------------------------------------------------------------

    if not config_exists("hifiti"):
        data = _create_default_config()

        save_config("hifiti", data)

        return None

    # ------------------------------------------------------------------------
    # 正常加载
    # ------------------------------------------------------------------------

    data = load_config("hifiti")

    encryption_key = data.get("encryption_key")

    # 如果旧配置没有 encryption_key，
    # 自动生成并持久化。
    if not encryption_key:
        encryption_key = generate_key()
        data["encryption_key"] = encryption_key

        save_config("hifiti", data)

    accounts = []

    for account in data.get("accounts", []):
        account = dict(account)
        # 确保 cookies 字段存在，兼容旧配置
        if "cookies" not in account:
            account["cookies"] = ""
        accounts.append(HifitiAccountConfig(**account))

    return HifitiConfig(
        encryption_key=encryption_key,
        accounts=accounts,
    )


__all__ = [
    "HifitiAccountConfig",
    "HifitiConfig",
    "load_hifiti_config",
]
