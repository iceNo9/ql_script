# apps\glados\core\config.py

"""
GLaDOS 应用配置模块。

负责：

- 定义 GLaDOS 应用配置 Model
- 定义单个 GLaDOS 账号配置 Model
- 从全局配置模块加载 config/glados.yaml
- 初始化 GLaDOS 加密密钥
- 首次运行时创建 GLaDOS 配置模板

不负责：

- GLaDOS 业务逻辑
- 邮箱登录
- Cookie 获取与刷新
- 续费业务处理
- YAML 文件解析
"""

from dataclasses import dataclass, field
from enum import StrEnum

from ruamel.yaml.comments import CommentedMap

from utils.config import config_exists, load_config, save_config
from utils.crypto import generate_key
from utils.email import EmailProvider

# ============================================================================
# 配置 Model
# ============================================================================


@dataclass
class GladosAccountConfig:
    """
    单个 GLaDOS 账号配置。

    一个账号对应一个邮箱账号。
    """

    username: str
    cookies: str

    # 邮箱配置
    email_provider: EmailProvider
    email_user: str
    email_passwd: str

    # 续费配置
    renew_enabled: bool = False
    renew_plan: str = ""
    renew_threshold: int = 2


@dataclass
class GladosConfig:
    """
    GLaDOS 应用配置。

    一个 GLaDOS 应用可以配置多个账号。
    """

    encryption_key: str
    accounts: list[GladosAccountConfig] = field(default_factory=list)


# ============================================================================
# 默认配置模板
# ============================================================================


def _enum_values(enum_cls: type[StrEnum]) -> str:
    """获取枚举的所有值，并转换为适合配置注释显示的字符串。"""
    return "、".join(member.value for member in enum_cls)


def _create_default_config() -> CommentedMap:
    """
    创建 GLaDOS 默认配置模板。

    首次运行时生成：

        encryption_key: <自动生成的密钥>
        accounts: []

    同时在文件顶部生成完整的账号配置模板注释。

    Returns:
        CommentedMap:
            GLaDOS 默认配置。
    """
    config = CommentedMap()

    # ------------------------------------------------------------------------
    # 文件顶部说明
    # ------------------------------------------------------------------------

    email_providers = _enum_values(EmailProvider)

    config.yaml_set_start_comment(
        "\n".join(
            [
                "GLaDOS 应用配置。",
                "",
                "本文件由程序首次启动时自动生成。",
                "",
                "账号配置模板：",
                "",
                "accounts:",
                '  - username: ""',
                '    cookies: ""',
                "",
                f"    # 邮箱服务商，可选值：{email_providers}",
                '    email_provider: ""',
                "",
                "    # 邮箱账号",
                '    email_user: ""',
                "",
                "    # 邮箱密码或 SMTP 授权码",
                '    email_passwd: ""',
                "",
                "    # 是否启用自动续费",
                "    renew_enabled: false",
                "",
                "    # 自动续费套餐",
                '    renew_plan: ""',
                "",
                "    # 剩余天数低于该值时触发自动续费",
                "    renew_threshold: 2",
                "",
                "请将账号模板复制到 accounts 列表中。",
            ]
        )
    )

    # ------------------------------------------------------------------------
    # 加密密钥
    # ------------------------------------------------------------------------

    config["encryption_key"] = generate_key()

    config.yaml_set_comment_before_after_key(
        "encryption_key",
        before=(
            "GLaDOS 应用加密密钥。\n"
            "\n"
            "该密钥由程序首次启动时自动生成。\n"
            "请勿修改，否则已保存的 Cookie 和 Token 将无法解密。"
        ),
    )

    # ------------------------------------------------------------------------
    # 账号列表
    # ------------------------------------------------------------------------

    config["accounts"] = []

    config.yaml_set_comment_before_after_key(
        "accounts",
        before=(
            "GLaDOS 账号列表。\n"
            "\n"
            "可以配置多个账号。\n"
            "复制上面的账号模板到 accounts: 下方即可。"
        ),
    )

    return config


# ============================================================================
# 配置加载
# ============================================================================


def load_glados_config() -> GladosConfig | None:
    """
    加载 GLaDOS 应用配置。

    对应：

        config/glados.yaml

    如果配置文件不存在：

    1. 自动生成加密密钥。
    2. 创建带完整中文注释的配置模板。
    3. 保存到 config/glados.yaml。
    4. 返回 None。

    返回 None 表示：

        GLaDOS 配置文件刚刚初始化，
        当前还没有正式加载应用配置。

    如果配置文件已经存在，则正常加载并返回 GladosConfig。

    Returns:
        GladosConfig | None:
            配置加载成功返回 GladosConfig。
            首次初始化配置文件返回 None。
    """

    # ------------------------------------------------------------------------
    # 首次运行
    # ------------------------------------------------------------------------

    if not config_exists("glados"):
        data = _create_default_config()

        save_config("glados", data)

        return None

    # ------------------------------------------------------------------------
    # 正常加载
    # ------------------------------------------------------------------------

    data = load_config("glados")

    encryption_key = data.get("encryption_key")

    # 如果旧配置没有 encryption_key，
    # 自动生成并持久化。
    if not encryption_key:
        encryption_key = generate_key()
        data["encryption_key"] = encryption_key

        save_config("glados", data)

    accounts = []

    for account in data.get("accounts", []):
        account = dict(account)

        account["email_provider"] = EmailProvider(account["email_provider"])

        accounts.append(GladosAccountConfig(**account))

    return GladosConfig(
        encryption_key=encryption_key,
        accounts=accounts,
    )


__all__ = [
    "GladosAccountConfig",
    "GladosConfig",
    "load_glados_config",
]
