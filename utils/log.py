"""
日志模块 - 提供统一的日志记录功能

功能：
    - 支持控制台输出和文件输出
    - 按日期分目录存储
    - 按模块分文件记录
    - 可配置日志级别和格式
    - 单例模式，相同名称的 logger 只创建一次

目录结构：
    logs/
    ├── 2024-01-01/
    │   ├── app.log
    │   ├── database.log
    │   ├── manifest_parser.log
    │   └── plugin_loader.log
    └── 2024-01-02/
        ├── app.log
        └── ...

Example:
    >>> from utils.log import get_logger
    >>>
    >>> logger = get_logger("my_module")
    >>> logger.info("这是一条日志")
"""

import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import ClassVar


class Logger:
    """
    日志管理器类

    支持多种日志输出方式和灵活的配置。
    日志文件按日期分目录，按模块名分文件。

    Attributes:
        FORMATS: 预定义的日志格式
        _instances: 单例缓存

    Usage:
        >>> logger = Logger("my_module")
        >>> logger.info("模块启动")
        >>> logger.error("发生错误")
    """

    # 预定义的日志格式
    FORMATS: ClassVar[dict[str, str]] = {
        "default": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "detailed": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        "simple": "%(levelname)s - %(message)s",
        "minimal": "%(message)s",
    }

    _instances: ClassVar[dict[str, "Logger"]] = {}

    def __new__(cls, name: str = "default", **kwargs):
        """单例模式，相同名称的 logger 只创建一次"""
        if name not in cls._instances:
            cls._instances[name] = super().__new__(cls)
        return cls._instances[name]

    def __init__(
        self,
        name: str = "default",
        log_dir: str = "logs",
        log_level: int = logging.DEBUG,
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        fmt_type: str = "default",
        use_file: bool = True,
        use_console: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ):
        """
        初始化日志记录器

        Args:
            name: 日志记录器名称（对应模块名）
            log_dir: 日志根目录
            log_level: 全局日志级别
            console_level: 控制台输出级别
            file_level: 文件输出级别
            fmt_type: 日志格式类型
            use_file: 是否启用文件日志
            use_console: 是否启用控制台日志
            max_bytes: 单个日志文件最大字节数
            backup_count: 保留的日志文件备份数量
        """
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.name = name
        self.log_dir = log_dir
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)

        # 清除已有的处理器
        self.logger.handlers.clear()

        # 获取日志格式
        self.formatter = logging.Formatter(
            self.FORMATS.get(fmt_type, self.FORMATS["default"]),
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 添加控制台处理器
        if use_console:
            self._add_console_handler(console_level)

        # 添加文件处理器
        if use_file:
            self._add_file_handler(file_level, max_bytes, backup_count)

        self._initialized = True

    def _get_log_path(self) -> str:
        """
        生成日志文件路径

        格式: {log_dir}/{日期}/{模块名}.log

        Returns:
            str: 日志文件完整路径
        """
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        date_dir = os.path.join(self.log_dir, today)
        return os.path.join(date_dir, f"{self.name}.log")

    def _add_console_handler(self, level: int) -> None:
        """添加控制台日志处理器"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(self.formatter)
        self.logger.addHandler(console_handler)

    def _add_file_handler(self, level: int, max_bytes: int, backup_count: int) -> None:
        """添加文件日志处理器"""
        log_path = self._get_log_path()
        log_dir = os.path.dirname(log_path)

        # 创建日志目录
        os.makedirs(log_dir, exist_ok=True)

        # 按大小轮转
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(self.formatter)
        self.logger.addHandler(file_handler)

    def debug(self, message: str, *args, **kwargs) -> None:
        """记录 DEBUG 级别日志"""
        self.logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs) -> None:
        """记录 INFO 级别日志"""
        self.logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs) -> None:
        """记录 WARNING 级别日志"""
        self.logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs) -> None:
        """记录 ERROR 级别日志"""
        self.logger.error(message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs) -> None:
        """记录 CRITICAL 级别日志"""
        self.logger.critical(message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs) -> None:
        """记录异常日志，自动包含堆栈信息"""
        self.logger.exception(message, *args, **kwargs)

    def set_level(self, level: int) -> None:
        """动态设置日志级别"""
        self.logger.setLevel(level)

    def close(self) -> None:
        """关闭所有处理器"""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)


# ============================================================================
# 默认日志记录器
# ============================================================================

default_logger = Logger("app")


# ============================================================================
# 快捷函数
# ============================================================================


def debug(msg: str, *args, **kwargs) -> None:
    """全局 DEBUG 日志"""
    default_logger.debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs) -> None:
    """全局 INFO 日志"""
    default_logger.info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs) -> None:
    """全局 WARNING 日志"""
    default_logger.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs) -> None:
    """全局 ERROR 日志"""
    default_logger.error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs) -> None:
    """全局 CRITICAL 日志"""
    default_logger.critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs) -> None:
    """全局异常日志"""
    default_logger.exception(msg, *args, **kwargs)


def get_logger(name: str = "app", **kwargs) -> Logger:
    """
    获取指定名称的日志记录器

    Args:
        name: 日志记录器名称（模块名）
        **kwargs: 传递给 Logger 的其他参数

    Returns:
        Logger 实例

    Example:
        >>> logger = get_logger("database", log_dir="logs", fmt_type="detailed")
        >>> logger.info("数据库模块已启动")
    """
    return Logger(name, **kwargs)
