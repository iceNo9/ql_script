from pathlib import Path
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from datetime import datetime

from common.log import get_logger

logger = get_logger(__name__)

# ----------------------
# Pydantic Schema
# ----------------------
class GladosAccountData(BaseModel):
    # 用户可见字段
    id: str
    username: str

    # 程序内部字段
    balance: float = 0.0
    leftDays: int = 0
    expireAt: Optional[datetime] = None
    traffic: int = 0
    total_traffic: int = 5368709120  # 默认 5GB
    vip_level: int = 0
    cookies: Dict[str, str] = Field(default_factory=dict)

class GladosDataConfig(BaseModel):
    accounts: List[GladosAccountData] = Field(default_factory=list)

# ----------------------
# 配置管理类
# ----------------------
class GladosDataManager:
    def __init__(self, path: str = "glados_accounts.yml"):
        self.path = Path(path)
        self.config: Optional[GladosDataConfig] = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml_data = {}

    def read(self) -> Optional[GladosDataConfig]:
        """加载 YAML 并验证"""
        if not self.path.exists():
            logger.warning(f"配置文件不存在: {self.path}")
            
            self._create_default_config()
            return self.config
        
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._yaml_data = self._yaml.load(f) or {}
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            # 如果文件损坏，创建默认配置
            self._create_default_config()
            return self.config

        try:
            # 尝试从YAML数据加载配置
            self.config = GladosDataConfig(**self._yaml_data.get("accounts", {}))
        except Exception as e:
            logger.error(f"配置文件格式错误: {e}")
            # 如果格式错误，创建默认配置
            self._create_default_config()
        
        return self.config

    def _create_default_config(self):
        """创建默认配置"""
        logger.info(f"创建默认配置")
        self.config = GladosDataConfig(accounts=[])
        self._yaml_data = {"accounts": self.config.model_dump()}

    def save(self):
        """写回 YAML，保持原有格式"""
        if self.config is None:
            raise ValueError("Config is not loaded")

        # 确保目录存在
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # 同步 Pydantic 对象到 YAML 数据
            self._yaml_data["accounts"] = self.config.model_dump()
            with open(self.path, "w", encoding="utf-8") as f:
                self._yaml.dump(self._yaml_data, f)
            logger.info(f"配置已保存到: {self.path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    # ----------------------
    # dot-access
    # ----------------------
    def __getattr__(self, item):
        if self.config is not None and hasattr(self.config, item):
            return getattr(self.config, item)
        raise AttributeError(f"{item} not found in GladosDataConfig")

    def __setattr__(self, key, value):
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)