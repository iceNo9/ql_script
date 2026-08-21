# apps\baiyefee\core\config.py

"""
Baiyefee 应用配置模块。

负责：

- 定义 Baiyefee 应用配置 Model
- 定义单个 Baiyefee 账号配置 Model
- 从全局配置模块加载 config/baiyefee.yaml
- 初始化 Baiyefee 加密密钥
- 首次运行时创建 Baiyefee 配置模板

不负责：

- Baiyefee 业务逻辑
- 账号登录
- Token 获取与刷新
"""

from dataclasses import dataclass, field

from ruamel.yaml.comments import CommentedMap

from utils.config import config_exists, load_config, save_config
from utils.crypto import generate_key

# ============================================================================
# 配置 Model
# ============================================================================


@dataclass
class BaiyefeeAccountConfig:
    """
    单个 Baiyefee 账号配置。

    一个账号对应一个用户名。
    """

    username: str
    passwd: str
    token: str  # 改为 token


@dataclass
class BaiyefeeConfig:
    """
    Baiyefee 应用配置。

    一个 Baiyefee 应用可以配置多个账号。
    """

    encryption_key: str
    accounts: list[BaiyefeeAccountConfig] = field(default_factory=list)


# ============================================================================
# 默认配置模板
# ============================================================================


def _create_default_config() -> CommentedMap:
    """
    创建 Baiyefee 默认配置模板。

    首次运行时生成：

        encryption_key: <自动生成的密钥>
        accounts: []

    同时在文件顶部生成完整的账号配置模板注释。

    Returns:
        CommentedMap:
            Baiyefee 默认配置。
    """
    config = CommentedMap()

    # ------------------------------------------------------------------------
    # 文件顶部说明
    # ------------------------------------------------------------------------

    config.yaml_set_start_comment("""
    Baiyefee 应用配置。

    本文件由程序首次启动时自动生成。

    账号配置模板：

    accounts:
      - username: ""
        passwd: ""
        token: ""

    请将账号模板复制到 accounts 列表中。
    """.strip())

    # ------------------------------------------------------------------------
    # 加密密钥
    # ------------------------------------------------------------------------

    config["encryption_key"] = generate_key()

    config.yaml_set_comment_before_after_key(
        "encryption_key",
        before=(
            "Baiyefee 应用加密密钥。\n"
            "\n"
            "该密钥由程序首次启动时自动生成。\n"
            "请勿修改，否则已保存的 Token 将无法解密。"
        ),
    )

    # ------------------------------------------------------------------------
    # 账号列表
    # ------------------------------------------------------------------------

    config["accounts"] = []

    config.yaml_set_comment_before_after_key(
        "accounts",
        before=(
            "Baiyefee 账号列表。\n"
            "\n"
            "可以配置多个账号。\n"
            "复制上面的账号模板到 accounts: 下方即可。"
        ),
    )

    return config


# ============================================================================
# 配置加载
# ============================================================================


def load_baiyefee_config() -> BaiyefeeConfig | None:
    """
    加载 Baiyefee 应用配置。

    对应：

        config/baiyefee.yaml

    如果配置文件不存在：

    1. 自动生成加密密钥。
    2. 创建带完整中文注释的配置模板。
    3. 保存到 config/baiyefee.yaml。
    4. 返回 None。

    返回 None 表示：

        Baiyefee 配置文件刚刚初始化，
        当前还没有正式加载应用配置。

    如果配置文件已经存在，则正常加载并返回 BaiyefeeConfig。

    Returns:
        BaiyefeeConfig | None:
            配置加载成功返回 BaiyefeeConfig。
            首次初始化配置文件返回 None。
    """

    # ------------------------------------------------------------------------
    # 首次运行
    # ------------------------------------------------------------------------

    if not config_exists("baiyefee"):
        data = _create_default_config()

        save_config("baiyefee", data)

        return None

    # ------------------------------------------------------------------------
    # 正常加载
    # ------------------------------------------------------------------------

    data = load_config("baiyefee")

    encryption_key = data.get("encryption_key")

    # 如果旧配置没有 encryption_key，
    # 自动生成并持久化。
    if not encryption_key:
        encryption_key = generate_key()
        data["encryption_key"] = encryption_key

        save_config("baiyefee", data)

    accounts = []

    for account in data.get("accounts", []):
        account = dict(account)
        accounts.append(BaiyefeeAccountConfig(**account))

    return BaiyefeeConfig(
        encryption_key=encryption_key,
        accounts=accounts,
    )


__all__ = [
    "BaiyefeeAccountConfig",
    "BaiyefeeConfig",
    "load_baiyefee_config",
]
