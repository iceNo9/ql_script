"""
paths.py - 项目路径管理模块

该模块位于 utils 目录下，用于定义项目根目录和常用路径方法。
"""

from pathlib import Path


class PathManager:
    """项目路径管理器"""

    def __init__(self):
        """初始化路径管理器，自动检测项目根目录"""
        self._root_dir = self._find_root_dir()
        print(f"项目根目录: {self._root_dir}")

    def _find_root_dir(self) -> Path:
        """
        查找项目根目录。

        从当前文件所在目录向上查找，只要目录中存在
        ``task_*.py`` 文件或 ``main.py``，就认为该目录为项目根目录。

        Returns:
            Path: 项目根目录路径
        """
        current_dir = Path(__file__).resolve().parent

        markers = [
            "task_*.py",
            "main.py",
        ]

        for parent in [current_dir] + list(current_dir.parents):
            if any(
                path.is_file() for pattern in markers for path in parent.glob(pattern)
            ):
                return parent

        return current_dir.parent

    @property
    def root(self) -> Path:
        """项目根目录"""
        return self._root_dir

    @property
    def src(self) -> Path:
        """源代码目录 (假设为 src 或项目名目录)"""
        # 尝试常见的源码目录
        possible_src = [
            self._root_dir / "src",
            self._root_dir / "app",
            self._root_dir / "apps",
            self._root_dir / "project",
        ]

        for path in possible_src:
            if path.exists() and path.is_dir():
                return path

        # 如果没有找到，返回 root/src (即使不存在)
        return self._root_dir / "src"

    @property
    def utils(self) -> Path:
        """utils 目录 (当前文件所在目录)"""
        return Path(__file__).resolve().parent

    @property
    def tests(self) -> Path:
        """测试目录"""
        return self._root_dir / "tests"

    @property
    def data(self) -> Path:
        """数据目录"""
        return self._root_dir / "data"

    @property
    def logs(self) -> Path:
        """日志目录"""
        return self._root_dir / "logs"

    @property
    def config(self) -> Path:
        """配置目录"""
        return self._root_dir / "config"

    @property
    def output(self) -> Path:
        """输出目录"""
        return self._root_dir / "output"

    @property
    def temp(self) -> Path:
        """临时目录"""
        return self._root_dir / "temp"

    @property
    def env(self) -> Path:
        """环境变量配置目录"""
        return self._root_dir / "env"

    @property
    def asset(self) -> Path:
        """资源目录。"""
        return self._root_dir / "asset"

    @property
    def templates(self) -> Path:
        """模板目录。"""
        return self.asset / "templates"

    def get_path(self, *paths: str | Path) -> Path:
        """
        获取相对于项目根目录的路径

        Args:
            *paths: 路径组件

        Returns:
            Path: 相对于项目根目录的完整路径

        Examples:
            >>> paths.get_path("data", "raw", "file.csv")
            Path("/project/data/raw/file.csv")
        """
        return self._root_dir.joinpath(*paths)

    def ensure_dir(self, path: str | Path) -> Path:
        """
        确保目录存在，如果不存在则创建

        Args:
            path: 目录路径

        Returns:
            Path: 创建后的目录路径
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self, *paths: str | Path) -> None:
        """
        确保多个目录存在

        Args:
            *paths: 要创建的目录路径列表
        """
        for path in paths:
            self.ensure_dir(path)

    def is_in_project(self, path: str | Path) -> bool:
        """
        检查给定路径是否在项目根目录内

        Args:
            path: 要检查的路径

        Returns:
            bool: 是否在项目根目录内
        """
        try:
            Path(path).resolve().relative_to(self._root_dir.resolve())
            return True
        except ValueError:
            return False

    def get_relative_path(self, path: str | Path) -> Path:
        """
        获取相对于项目根目录的路径

        Args:
            path: 绝对路径或相对路径

        Returns:
            Path: 相对于项目根目录的路径

        Raises:
            ValueError: 如果路径不在项目根目录内
        """
        abs_path = Path(path).resolve()
        try:
            return abs_path.relative_to(self._root_dir.resolve())
        except ValueError:
            raise ValueError(
                f"Path {abs_path} is not inside project root {self._root_dir}"
            )


# 创建全局单例实例
_paths = PathManager()


# 为了使用方便，直接导出常用属性
def root() -> Path:
    """获取项目根目录"""
    return _paths.root


def src() -> Path:
    """获取源码目录"""
    return _paths.src


def utils() -> Path:
    """获取 utils 目录"""
    return _paths.utils


def tests() -> Path:
    """获取测试目录"""
    return _paths.tests


def data() -> Path:
    """获取数据目录"""
    return _paths.data


def logs() -> Path:
    """获取日志目录"""
    return _paths.logs


def config() -> Path:
    """获取配置目录"""
    return _paths.config


def output() -> Path:
    """获取输出目录"""
    return _paths.output


def temp() -> Path:
    """获取临时目录"""
    return _paths.temp


def env() -> Path:
    """获取环境变量配置目录"""
    return _paths.env


def asset() -> Path:
    """获取资源目录。"""
    return _paths.asset


def templates() -> Path:
    """获取模板目录。"""
    return _paths.templates


def get_path(*paths: str | Path) -> Path:
    """获取相对于项目根目录的路径"""
    return _paths.get_path(*paths)


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在"""
    return _paths.ensure_dir(path)


def ensure_dirs(*paths: str | Path) -> None:
    """确保多个目录存在"""
    _paths.ensure_dirs(*paths)


def is_in_project(path: str | Path) -> bool:
    """检查路径是否在项目内"""
    return _paths.is_in_project(path)


def get_relative_path(path: str | Path) -> Path:
    """获取相对路径"""
    return _paths.get_relative_path(path)


# 添加 __all__ 以便于 from paths import * 导入
__all__ = [
    "PathManager",
    "asset",
    "config",
    "data",
    "ensure_dir",
    "ensure_dirs",
    "env",
    "get_path",
    "get_relative_path",
    "is_in_project",
    "logs",
    "output",
    "root",
    "src",
    "temp",
    "templates",
    "tests",
    "utils",
]
