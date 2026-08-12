from pathlib import Path
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from datetime import datetime

from utils.log import get_logger

logger = get_logger(__name__)

# ----------------------
# Pydantic Schema
# ----------------------
class IkuuuAccountData(BaseModel):
    # 用户可见字段
    id: str
    username: str
    password: str

    # 程序内部字段
    total_bytes: int = Field(default=50 * 1024**3)  # 默认50GB (50 * 1024^3 bytes)
    used_bytes: int = Field(default=0)               # 默认已使用0
    today_used_bytes: int = Field(default=0)         # 默认今日使用0
    remain_bytes: int = Field(default=50 * 1024**3)   # 默认剩余50GB

    cookies: Dict[str, str] = Field(default_factory=dict)

class IkuuuDataConfig(BaseModel):
    accounts: List[IkuuuAccountData] = Field(default_factory=list)

# ----------------------
# 配置管理类
# ----------------------
class IkuuuDataManager:
    def __init__(self, path: str = "glados_accounts.yml"):
        self.path = Path(path)
        self.config: Optional[IkuuuDataConfig] = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml_data = {}

    def read(self) -> Optional[IkuuuDataConfig]:
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
            self.config = IkuuuDataConfig(**self._yaml_data.get("accounts", {}))
        except Exception as e:
            logger.error(f"配置文件格式错误: {e}")
            # 如果格式错误，创建默认配置
            self._create_default_config()
        
        return self.config

    def _create_default_config(self):
        """创建默认配置"""
        logger.info(f"创建默认配置")
        self.config = IkuuuDataConfig(accounts=[])
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
        raise AttributeError(f"{item} not found in IkuuuDataConfig")

    def __setattr__(self, key, value):
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)