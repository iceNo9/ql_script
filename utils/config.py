"""
配置文件加载模块

负责：

- 从项目根目录的 config 目录加载 YAML 配置
- 使用 utils.paths 获取配置目录
- 使用 ruamel.yaml 解析 YAML
- 使用 utils.log 记录配置加载过程
- 定义全局配置 Model
- 提供统一的 YAML 配置加载接口
- 提供全局配置加载接口

不负责：

- 定义具体应用的配置 Model
- 处理应用业务逻辑
- 校验应用自身的业务配置

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
    └── config.py
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

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

_yaml = YAML(typ="safe")


# ============================================================================
# 全局配置 Model
# ============================================================================


@dataclass
class ProxyConfig:
    """全局代理配置。"""

    enabled: bool = False
    http: str | None = None
    https: str | None = None


@dataclass
class DatabaseConfig:
    """全局数据库配置。"""

    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""


@dataclass
class GlobalConfig:
    """
    全局配置。

    所有应用都可以访问的公共配置。
    """

    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


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

    logger.debug("加载配置文件: %s", path)

    if not path.is_file():
        logger.error("配置文件不存在: %s", path)
        raise FileNotFoundError(f"配置文件不存在: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = _yaml.load(file)

    except Exception:
        logger.exception("读取配置文件失败: %s", path)
        raise

    # YAML 文件为空
    if data is None:
        logger.warning("配置文件为空: %s", path)
        return {}

    # YAML 根节点必须是字典
    if not isinstance(data, dict):
        logger.error(
            "配置文件根节点必须是字典: %s",
            path,
        )
        raise TypeError(f"配置文件根节点必须是字典: {path}")

    logger.debug("配置文件加载成功: %s", path)

    return dict(data)


# ============================================================================
# 全局配置
# ============================================================================


def load_global_config() -> GlobalConfig:
    """
    加载全局配置。

    对应：

        config/global.yaml

    如果配置文件不存在，则使用 GlobalConfig 默认配置。

    如果配置文件存在但为空，则同样使用默认配置。

    Returns:
        GlobalConfig:
            全局配置对象。
    """
    path = get_config_path("global")

    if not path.is_file():
        logger.warning(
            "全局配置文件不存在，使用默认配置: %s",
            path,
        )
        return GlobalConfig()

    data = load_config("global")

    if not data:
        logger.warning(
            "全局配置文件为空，使用默认配置: %s",
            path,
        )
        return GlobalConfig()

    return GlobalConfig(
        proxy=ProxyConfig(**data.get("proxy", {})),
        database=DatabaseConfig(**data.get("database", {})),
    )


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
# 导出
# ============================================================================

__all__ = [
    "DatabaseConfig",
    "GlobalConfig",
    "ProxyConfig",
    "config_exists",
    "get_config_path",
    "load_config",
    "load_global_config",
]
