"""
配置文件加载模块的单元测试

测试覆盖：

- get_config_path: 路径生成
- config_exists: 配置文件存在性检查
- load_config: YAML 配置加载
- load_global_config: 全局配置加载
- 异常处理: 文件不存在、根节点非字典、YAML 解析失败
- 空文件处理
- 默认配置
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from ruamel.yaml import YAML

from utils.config import (
    DatabaseConfig,
    GlobalConfig,
    ProxyConfig,
    config_exists,
    get_config_path,
    load_config,
    load_global_config,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config_dir(tmp_path: Path) -> Path:
    """创建临时的配置目录。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_config_file(mock_config_dir: Path) -> Path:
    """创建临时的配置文件。"""
    return mock_config_dir / "test.yaml"


@pytest.fixture
def yaml_parser() -> YAML:
    """YAML 解析器。"""
    return YAML(typ="safe")


@pytest.fixture
def sample_yaml_data() -> dict:
    """示例 YAML 数据。"""
    return {
        "proxy": {
            "enabled": True,
            "http": "http://127.0.0.1:8080",
            "https": "https://127.0.0.1:8443",
        },
        "database": {
            "host": "192.168.1.100",
            "port": 3306,
            "database": "test_db",
            "username": "admin",
            "password": "secret",
        },
    }


@pytest.fixture
def mock_paths_module(mock_config_dir: Path):
    """Mock utils.paths 模块。"""
    with patch("utils.config.config_dir", return_value=mock_config_dir):
        yield


@pytest.fixture
def mock_logger():
    """Mock logger。"""
    with patch("utils.config.logger") as mock_log:
        yield mock_log


# ============================================================================
# 测试 get_config_path
# ============================================================================


class TestGetConfigPath:
    """测试 get_config_path 函数。"""

    def test_returns_path_with_yaml_extension(self, mock_paths_module):
        """测试返回包含 .yaml 后缀的路径。"""
        path = get_config_path("test")
        assert path.name == "test.yaml"
        assert path.suffix == ".yaml"

    def test_path_in_config_directory(self, mock_paths_module, mock_config_dir):
        """测试路径在 config 目录下。"""
        path = get_config_path("test")
        assert path.parent == mock_config_dir

    def test_handles_name_without_yaml_extension(self, mock_paths_module):
        """测试处理不带 .yaml 后缀的名称。"""
        path = get_config_path("test")
        assert path.name == "test.yaml"

    def test_handles_subdirectories(self, mock_paths_module, mock_config_dir):
        """测试处理子目录路径。"""
        path = get_config_path("subdir/test")
        assert path.parent == mock_config_dir / "subdir"
        assert path.name == "test.yaml"


# ============================================================================
# 测试 config_exists
# ============================================================================


class TestConfigExists:
    """测试 config_exists 函数。"""

    def test_returns_true_when_file_exists(self, mock_paths_module, mock_config_file):
        """测试文件存在时返回 True。"""
        mock_config_file.touch()
        assert config_exists("test") is True

    def test_returns_false_when_file_not_exists(self, mock_paths_module):
        """测试文件不存在时返回 False。"""
        assert config_exists("nonexistent") is False

    def test_handles_subdirectory_path(self, mock_paths_module, mock_config_dir):
        """测试处理子目录路径。"""
        subdir = mock_config_dir / "subdir"
        subdir.mkdir()
        config_file = subdir / "test.yaml"
        config_file.touch()

        assert config_exists("subdir/test") is True
        assert config_exists("subdir/nonexistent") is False


# ============================================================================
# 测试 load_config
# ============================================================================


class TestLoadConfig:
    """测试 load_config 函数。"""

    def test_loads_yaml_file_successfully(
        self,
        mock_paths_module,
        mock_config_file,
        yaml_parser,
        sample_yaml_data,
        mock_logger,
    ):
        """测试成功加载 YAML 文件。"""
        # 写入 YAML 数据
        with mock_config_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(sample_yaml_data, f)

        result = load_config("test")

        assert result == sample_yaml_data
        mock_logger.debug.assert_any_call("加载配置文件: %s", mock_config_file)
        mock_logger.debug.assert_any_call("配置文件加载成功: %s", mock_config_file)

    def test_returns_empty_dict_for_empty_file(
        self,
        mock_paths_module,
        mock_config_file,
        mock_logger,
    ):
        """测试空文件返回空字典。"""
        mock_config_file.touch()

        result = load_config("test")

        assert result == {}
        mock_logger.warning.assert_called_with(
            "配置文件为空: %s",
            mock_config_file,
        )

    def test_raises_file_not_found_when_file_missing(
        self,
        mock_paths_module,
        mock_logger,
    ):
        """测试文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_config("nonexistent")

        assert "配置文件不存在" in str(exc_info.value)
        mock_logger.error.assert_called()

    def test_raises_type_error_when_root_is_not_dict(
        self,
        mock_paths_module,
        mock_config_file,
        yaml_parser,
        mock_logger,
    ):
        """测试根节点不是字典时抛出 TypeError。"""
        # 写入列表数据
        with mock_config_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(["item1", "item2"], f)

        with pytest.raises(TypeError) as exc_info:
            load_config("test")

        assert "根节点必须是字典" in str(exc_info.value)
        mock_logger.error.assert_called()

    def test_raises_exception_on_invalid_yaml(
        self,
        mock_paths_module,
        mock_config_file,
        mock_logger,
    ):
        """测试无效 YAML 时抛出异常。"""
        with mock_config_file.open("w", encoding="utf-8") as f:
            f.write("invalid: yaml: [unclosed")

        with pytest.raises(Exception):
            load_config("test")

        mock_logger.exception.assert_called()

    def test_handles_none_yaml_data_as_empty_dict(
        self,
        mock_paths_module,
        mock_config_file,
        yaml_parser,
        mock_logger,
    ):
        """测试 YAML 数据为 None 时返回空字典。"""
        # 写入空的 YAML（使用 --- 表示空文档）
        with mock_config_file.open("w", encoding="utf-8") as f:
            f.write("---\n")

        result = load_config("test")

        assert result == {}
        mock_logger.warning.assert_called_with(
            "配置文件为空: %s",
            mock_config_file,
        )

    def test_preserves_data_types(
        self,
        mock_paths_module,
        mock_config_file,
        yaml_parser,
    ):
        """测试保留数据类型。"""
        data = {
            "string": "hello",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"key": "value"},
        }

        with mock_config_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data, f)

        result = load_config("test")

        assert result["string"] == "hello"
        assert result["integer"] == 42
        assert result["float"] == 3.14
        assert result["boolean"] is True
        assert result["null"] is None
        assert result["list"] == [1, 2, 3]
        assert result["nested"] == {"key": "value"}


# ============================================================================
# 测试 load_global_config
# ============================================================================


class TestLoadGlobalConfig:
    """测试 load_global_config 函数。"""

    def test_loads_global_config_successfully(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
        sample_yaml_data,
        mock_logger,
    ):
        """测试成功加载全局配置。"""
        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(sample_yaml_data, f)

        result = load_global_config()

        assert isinstance(result, GlobalConfig)
        assert isinstance(result.proxy, ProxyConfig)
        assert isinstance(result.database, DatabaseConfig)

        assert result.proxy.enabled is True
        assert result.proxy.http == "http://127.0.0.1:8080"
        assert result.proxy.https == "https://127.0.0.1:8443"

        assert result.database.host == "192.168.1.100"
        assert result.database.port == 3306
        assert result.database.database == "test_db"
        assert result.database.username == "admin"
        assert result.database.password == "secret"

    def test_returns_default_config_when_file_not_exists(
        self,
        mock_paths_module,
        mock_logger,
    ):
        """测试文件不存在时返回默认配置。"""
        result = load_global_config()

        assert isinstance(result, GlobalConfig)
        assert isinstance(result.proxy, ProxyConfig)
        assert isinstance(result.database, DatabaseConfig)

        assert result.proxy.enabled is False
        assert result.proxy.http is None
        assert result.proxy.https is None

        assert result.database.host == "localhost"
        assert result.database.port == 5432
        assert result.database.database == ""
        assert result.database.username == ""
        assert result.database.password == ""

        mock_logger.warning.assert_called()

    def test_returns_default_config_when_file_empty(
        self,
        mock_paths_module,
        mock_config_dir,
        mock_logger,
    ):
        """测试文件为空时返回默认配置。"""
        global_file = mock_config_dir / "global.yaml"
        global_file.touch()

        result = load_global_config()

        assert isinstance(result, GlobalConfig)
        assert result.proxy.enabled is False
        assert result.database.host == "localhost"

        mock_logger.warning.assert_called()

    def test_handles_missing_proxy_config(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
        mock_logger,
    ):
        """测试缺少 proxy 配置时使用默认值。"""
        data = {
            "database": {
                "host": "192.168.1.100",
                "port": 3306,
            }
        }

        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data, f)

        result = load_global_config()

        assert result.proxy.enabled is False
        assert result.proxy.http is None
        assert result.database.host == "192.168.1.100"
        assert result.database.port == 3306

    def test_handles_missing_database_config(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
        mock_logger,
    ):
        """测试缺少 database 配置时使用默认值。"""
        data = {
            "proxy": {
                "enabled": True,
                "http": "http://127.0.0.1:8080",
            }
        }

        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data, f)

        result = load_global_config()

        assert result.proxy.enabled is True
        assert result.proxy.http == "http://127.0.0.1:8080"
        assert result.database.host == "localhost"
        assert result.database.port == 5432

    def test_handles_partial_config(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
        mock_logger,
    ):
        """测试部分配置覆盖。"""
        data = {
            "proxy": {
                "enabled": True,
            },
            "database": {
                "host": "192.168.1.100",
            },
        }

        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data, f)

        result = load_global_config()

        assert result.proxy.enabled is True
        assert result.proxy.http is None  # 使用默认值
        assert result.database.host == "192.168.1.100"
        assert result.database.port == 5432  # 使用默认值

    def test_propagates_exception_from_load_config(
        self,
        mock_paths_module,
        mock_config_dir,
        mock_logger,
    ):
        """测试从 load_config 传播异常。"""
        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            f.write("invalid: yaml: [")

        with pytest.raises(Exception):
            load_global_config()

        mock_logger.exception.assert_called()


# ============================================================================
# 测试集成场景
# ============================================================================


class TestIntegrationScenarios:
    """测试集成场景。"""

    def test_config_reload_after_change(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
    ):
        """测试配置更改后重新加载。"""
        data1 = {"proxy": {"enabled": False}}
        data2 = {"proxy": {"enabled": True}}

        config_file = mock_config_dir / "test.yaml"

        # 第一次加载
        with config_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data1, f)

        result1 = load_config("test")
        assert result1["proxy"]["enabled"] is False

        # 重新加载
        with config_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data2, f)

        result2 = load_config("test")
        assert result2["proxy"]["enabled"] is True

    def test_multiple_configs_load_independently(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
    ):
        """测试多个配置文件独立加载。"""
        data1 = {"key": "value1"}
        data2 = {"key": "value2"}

        file1 = mock_config_dir / "config1.yaml"
        file2 = mock_config_dir / "config2.yaml"

        with file1.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data1, f)
        with file2.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data2, f)

        result1 = load_config("config1")
        result2 = load_config("config2")

        assert result1["key"] == "value1"
        assert result2["key"] == "value2"

    def test_global_config_uses_defaults_when_proxy_missing(
        self,
        mock_paths_module,
        mock_config_dir,
        yaml_parser,
    ):
        """测试全局配置在 proxy 缺失时使用默认值。"""
        data = {
            "database": {
                "host": "testhost",
            }
        }

        global_file = mock_config_dir / "global.yaml"
        with global_file.open("w", encoding="utf-8") as f:
            yaml_parser.dump(data, f)

        result = load_global_config()

        # Proxy 使用默认值
        assert result.proxy.enabled is False
        assert result.proxy.http is None
        assert result.proxy.https is None

        # Database 使用配置值
        assert result.database.host == "testhost"
        assert result.database.port == 5432  # 默认值
        assert result.database.database == ""  # 默认值


# ============================================================================
# 测试数据类
# ============================================================================


class TestDataClasses:
    """测试数据类。"""

    def test_proxy_config_defaults(self):
        """测试 ProxyConfig 默认值。"""
        config = ProxyConfig()
        assert config.enabled is False
        assert config.http is None
        assert config.https is None

    def test_proxy_config_custom_values(self):
        """测试 ProxyConfig 自定义值。"""
        config = ProxyConfig(
            enabled=True,
            http="http://proxy:8080",
            https="https://proxy:8443",
        )
        assert config.enabled is True
        assert config.http == "http://proxy:8080"
        assert config.https == "https://proxy:8443"

    def test_database_config_defaults(self):
        """测试 DatabaseConfig 默认值。"""
        config = DatabaseConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == ""
        assert config.username == ""
        assert config.password == ""

    def test_database_config_custom_values(self):
        """测试 DatabaseConfig 自定义值。"""
        config = DatabaseConfig(
            host="192.168.1.100",
            port=3306,
            database="testdb",
            username="admin",
            password="secret",
        )
        assert config.host == "192.168.1.100"
        assert config.port == 3306
        assert config.database == "testdb"
        assert config.username == "admin"
        assert config.password == "secret"

    def test_global_config_defaults(self):
        """测试 GlobalConfig 默认值。"""
        config = GlobalConfig()
        assert isinstance(config.proxy, ProxyConfig)
        assert isinstance(config.database, DatabaseConfig)
        assert config.proxy.enabled is False
        assert config.database.host == "localhost"

    def test_global_config_custom_values(self):
        """测试 GlobalConfig 自定义值。"""
        proxy = ProxyConfig(enabled=True, http="http://proxy:8080")
        database = DatabaseConfig(host="dbhost", port=3306)

        config = GlobalConfig(proxy=proxy, database=database)
        assert config.proxy.enabled is True
        assert config.proxy.http == "http://proxy:8080"
        assert config.database.host == "dbhost"
        assert config.database.port == 3306
