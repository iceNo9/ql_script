"""
配置文件加载模块。

负责：

- 从项目根目录的 config 目录加载 YAML 配置
- 使用 utils.paths 获取配置目录
- 使用 ruamel.yaml 解析 YAML
- 使用 utils.log 记录配置加载过程
- 定义全局配置 Model
- 提供统一的 YAML 配置加载接口
- 提供统一的 YAML 配置保存接口
- 提供全局配置加载接口

不负责：

- 定义具体应用的配置 Model
- 处理应用业务逻辑
- 校验应用自身的业务配置
- 时区相关操作（已移至 utils.timezone）

目录结构：

project/
├── config/
│   ├── global.yaml
│   ├── glados.yaml
│   └── app_a.yaml
│
├── apps/
│   ├── glados/
│   │   ├── config.py
│   │   └── ...
│   └── app_a/
│       ├── config.py
│       └── ...
│
└── utils/
    ├── paths.py
    ├── log.py
    ├── config.py
    └── timezone.py
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils.log import get_logger
from utils.paths import config as config_dir
from utils.paths import logs

# ============================================================================
# 日志
# ============================================================================

logger = get_logger(name="global_config", log_dir=logs(), fmt_type="detailed")


# ============================================================================
# YAML
# ============================================================================

# 用于读取。
# safe 模式只获取配置数据，不保留 YAML 注释、格式等信息。
_yaml = YAML(typ="safe")

# 用于写入。
#
# 使用默认的 round-trip 模式，可以正确处理 CommentedMap，
# 从而支持保存 YAML 注释。
_yaml_writer = YAML()

_yaml_writer.default_flow_style = False
_yaml_writer.allow_unicode = True


# ============================================================================
# 全局配置 Model
# ============================================================================


@dataclass
class ProxyConfig:
    """全局代理配置。"""

    enabled: bool = False
    http: list[str] = field(default_factory=list)
    https: list[str] = field(default_factory=list)
    no_proxy: list[str] = field(default_factory=list)


@dataclass
class DatabaseConfig:
    """全局数据库配置。"""

    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""


@dataclass
class TimezoneConfig:
    """全局时区配置。"""

    timezone: str = "Asia/Shanghai"


@dataclass
class GlobalConfig:
    """
    全局配置。

    所有应用都可以访问的公共配置。
    """

    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    timezone: TimezoneConfig = field(default_factory=TimezoneConfig)


# ============================================================================
# 默认配置模板
# ============================================================================


def _create_default_global_config() -> CommentedMap:
    """
    创建全局默认配置模板。

    首次运行时生成：

        proxy:
          enabled: false
          http: []
          https: []
          no_proxy: []

        database:
          host: localhost
          port: 5432
          database: ""
          username: ""
          password: ""

        timezone:
          timezone: "Asia/Shanghai"

    同时在文件顶部生成完整的配置注释。

    Returns:
        CommentedMap:
            全局默认配置。
    """
    config = CommentedMap()

    # ------------------------------------------------------------------------
    # 文件顶部说明
    # ------------------------------------------------------------------------

    config.yaml_set_start_comment("""全局配置文件。

本文件由程序首次启动时自动生成。

该配置适用于所有应用，提供公共配置项。

代理配置：
- 支持 HTTP/HTTPS 代理
- 支持 no_proxy 白名单

数据库配置：
- 支持 PostgreSQL 数据库连接
- 默认使用本地 5432 端口

时区配置：
- 设置应用使用的时区
- 支持 IANA 时区数据库格式
- 数据库统一使用 UTC 时间存储

请根据实际需要修改配置。""")

    # ------------------------------------------------------------------------
    # 代理配置
    # ------------------------------------------------------------------------

    config["proxy"] = CommentedMap()

    config.yaml_set_comment_before_after_key(
        "proxy",
        before="代理配置。",
    )

    proxy = config["proxy"]

    proxy["enabled"] = False
    proxy.yaml_set_comment_before_after_key(
        "enabled",
        before="是否启用代理。\ntrue 表示启用，false 表示禁用。",
    )

    proxy["http"] = []
    proxy.yaml_set_comment_before_after_key(
        "http",
        before=(
            "HTTP 代理地址列表。\n\n"
            "示例：\n"
            '  - "http://127.0.0.1:7890"\n'
            '  - "http://proxy.example.com:8080"'
        ),
    )

    proxy["https"] = []
    proxy.yaml_set_comment_before_after_key(
        "https",
        before=(
            "HTTPS 代理地址列表。\n\n"
            "示例：\n"
            '  - "https://127.0.0.1:7890"\n'
            '  - "https://proxy.example.com:8080"'
        ),
    )

    proxy["no_proxy"] = []
    proxy.yaml_set_comment_before_after_key(
        "no_proxy",
        before=(
            "不使用代理的地址列表。\n\n"
            "支持域名、IP 地址、CIDR 网段。\n\n"
            "示例：\n"
            '  - "localhost"\n'
            '  - "127.0.0.1"\n'
            '  - "192.168.0.0/16"\n'
            '  - ".example.com"'
        ),
    )

    # ------------------------------------------------------------------------
    # 数据库配置
    # ------------------------------------------------------------------------

    config["database"] = CommentedMap()

    config.yaml_set_comment_before_after_key(
        "database",
        before="数据库配置。",
    )

    database = config["database"]

    database["host"] = "localhost"
    database.yaml_set_comment_before_after_key(
        "host",
        before="数据库主机地址。",
    )

    database["port"] = 5432
    database.yaml_set_comment_before_after_key(
        "port",
        before="数据库端口。\nPostgreSQL 默认端口为 5432。",
    )

    database["database"] = ""
    database.yaml_set_comment_before_after_key(
        "database",
        before="数据库名称。",
    )

    database["username"] = ""
    database.yaml_set_comment_before_after_key(
        "username",
        before="数据库用户名。",
    )

    database["password"] = ""
    database.yaml_set_comment_before_after_key(
        "password",
        before=(
            "数据库密码。\n\n"
            "建议使用环境变量或密钥管理服务，\n"
            "避免明文存储敏感信息。"
        ),
    )

    # ------------------------------------------------------------------------
    # 时区配置
    # ------------------------------------------------------------------------

    config["timezone"] = CommentedMap()

    config.yaml_set_comment_before_after_key(
        "timezone",
        before="时区配置。",
    )

    timezone = config["timezone"]

    timezone["timezone"] = "Asia/Shanghai"
    timezone.yaml_set_comment_before_after_key(
        "timezone",
        before=(
            "应用使用的时区。\n\n"
            "使用 IANA 时区数据库格式。\n\n"
            "常用时区：\n"
            '  - "Asia/Shanghai" (中国标准时间)\n'
            '  - "Asia/Tokyo" (日本标准时间)\n'
            '  - "America/New_York" (美国东部时间)\n'
            '  - "Europe/London" (英国时间)\n'
            '  - "UTC" (协调世界时)\n\n'
            "注意：数据库统一使用 UTC 时间存储。"
        ),
    )

    return config


# ============================================================================
# 配置路径
# ============================================================================


def get_config_path(name: str) -> Path:
    """
    获取指定配置文件路径。

    Args:
        name:
            配置文件名称，不需要包含 .yaml 后缀。

            例如：

                global
                glados
                app_a

    Returns:
        Path:
            配置文件完整路径。

    Examples:
        >>> get_config_path("global")
        Path("/project/config/global.yaml")
    """
    return config_dir() / f"{name}.yaml"


# ============================================================================
# 配置加载
# ============================================================================


def load_config(name: str) -> dict[str, Any]:
    """
    加载指定 YAML 配置文件。

    该函数只负责：

    - 定位配置文件
    - 读取 YAML
    - 解析 YAML
    - 确保根节点为字典

    不负责：

    - 配置 Model 转换
    - 应用配置校验
    - 业务逻辑

    Args:
        name:
            配置文件名称，不需要包含 .yaml 后缀。

    Returns:
        dict[str, Any]:
            配置数据。

            如果 YAML 文件为空，则返回空字典。

    Raises:
        FileNotFoundError:
            配置文件不存在。

        TypeError:
            YAML 根节点不是字典。

        Exception:
            YAML 解析失败或文件读取失败。
    """
    path = get_config_path(name)

    logger.debug(f"加载配置文件: {path}")

    if not path.is_file():
        logger.error(f"配置文件不存在: {path}")
        raise FileNotFoundError(f"配置文件不存在: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = _yaml.load(file)

    except Exception:
        logger.exception(f"读取配置文件失败: {path}")
        raise

    # YAML 文件为空
    if data is None:
        logger.warning(f"配置文件为空: {path}")
        return {}

    # YAML 根节点必须是字典
    if not isinstance(data, dict):
        logger.error(f"配置文件根节点必须是字典: {path}")
        raise TypeError(f"配置文件根节点必须是字典: {path}")

    logger.debug(f"配置文件加载成功: {path}")

    return dict(data)


# ============================================================================
# 配置保存
# ============================================================================


def save_config(
    name: str,
    data: dict[str, Any] | CommentedMap,
) -> None:
    """
    保存指定 YAML 配置文件。

    支持普通 dict 和 ruamel.yaml 的 CommentedMap。

    使用 CommentedMap 时，可以保留并写入 YAML 注释。

    Args:
        name:
            配置文件名称，不需要包含 .yaml 后缀。

        data:
            要保存的配置数据。

            可以使用普通 dict：

                {
                    "name": "example",
                }

            也可以使用 CommentedMap 创建带注释的 YAML：

                data = CommentedMap()
                data["name"] = "example"
                data.yaml_set_comment_before_after_key(
                    "name",
                    before="名称",
                )

    Raises:
        TypeError:
            配置数据不是字典或 CommentedMap。

        Exception:
            YAML 写入失败或文件操作失败。
    """
    if not isinstance(data, (dict, CommentedMap)):
        raise TypeError("配置数据必须是 dict 或 CommentedMap")

    path = get_config_path(name)

    logger.debug(f"保存配置文件: {path}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            _yaml_writer.dump(data, file)

    except Exception:
        logger.exception(f"保存配置文件失败: {path}")
        raise

    logger.debug(f"配置文件保存成功: {path}")


# ============================================================================
# 全局配置
# ============================================================================

# 全局配置实例（模块加载时初始化）
_global_config: GlobalConfig | None = None


def _init_global_config() -> None:
    """初始化全局配置。内部函数，模块加载时自动调用。"""
    global _global_config
    _global_config = load_global_config()
    logger.info("全局配置初始化完成")


def load_global_config() -> GlobalConfig:
    """
    加载全局配置。

    对应：

        config/global.yaml

    如果配置文件不存在：

    1. 自动创建带完整中文注释的配置模板。
    2. 保存到 config/global.yaml。
    3. 返回 GlobalConfig 默认配置。

    如果配置文件存在但为空，则同样使用默认配置。

    Returns:
        GlobalConfig:
            全局配置对象。
    """
    path = get_config_path("global")

    # 配置文件不存在，创建默认模板
    if not path.is_file():
        logger.warning(f"全局配置文件不存在，创建配置模板: {path}")

        data = _create_default_global_config()
        save_config("global", data)

        logger.info(f"全局配置模板已创建: {path}")
        return GlobalConfig()

    data = load_config("global")

    if not data:
        logger.warning(f"全局配置文件为空，使用默认配置: {path}")
        return GlobalConfig()

    return GlobalConfig(
        proxy=ProxyConfig(**data.get("proxy", {})),
        database=DatabaseConfig(**data.get("database", {})),
        timezone=TimezoneConfig(**data.get("timezone", {})),
    )


def get_global_config() -> GlobalConfig:
    """
    获取全局配置实例。

    如果配置未初始化，则自动加载。

    Returns:
        GlobalConfig: 全局配置对象。
    """
    if _global_config is None:
        _init_global_config()

    return _global_config


# ============================================================================
# 配置是否存在
# ============================================================================


def config_exists(name: str) -> bool:
    """
    检查指定配置文件是否存在。

    Args:
        name:
            配置文件名称，不需要包含 .yaml 后缀。

    Returns:
        bool:
            配置文件存在返回 True，否则返回 False。

    Examples:
        >>> config_exists("global")
        True

        >>> config_exists("glados")
        False
    """
    return get_config_path(name).is_file()


# ============================================================================
# 模块加载时自动初始化
# ============================================================================

# 自动初始化全局配置
_init_global_config()


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "DatabaseConfig",
    "GlobalConfig",
    "ProxyConfig",
    "TimezoneConfig",
    "config_exists",
    "get_config_path",
    "get_global_config",
    "load_config",
    "load_global_config",
    "save_config",
]
