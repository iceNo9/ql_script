# modules/glados/glados_config.py

from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from common.log import get_logger

logger = get_logger(__name__)

# ----------------------
# Pydantic Schema
# ----------------------
class GladosAccount(BaseModel):
    id: str = Field(..., description="账号唯一ID")
    username: str = Field(..., description="账号用户名")

class GladosConfigModel(BaseModel):
    accounts: List[GladosAccount] = Field(
        default_factory=lambda: [
            GladosAccount(id="example", username="example"),
            GladosAccount(id="example2", username="example2"),
        ],
        description="Glados 账号列表"
    )

# ----------------------
# 配置管理类
# ----------------------
class GladosConfigManager:
    def __init__(self, path: str ):
        self.path = Path(path)
        self.config: GladosConfigModel | None = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml_data = {}

    def read(self) -> Optional[GladosConfigModel]:
        """加载 YAML 并验证"""
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._yaml_data = self._yaml.load(f) or {}
        else:
            logger.error(f"配置文件缺失{self.path},强制结束运行")
            return None

        self.config = GladosConfigModel(**self._yaml_data.get("glados", {}))
        return self.config  

    def save(self):
        """写回 YAML，保留原格式"""
        if self.config is None:
            raise ValueError("Config is not loaded")
        self._yaml_data["glados"] = self.config.model_dump()
        with open(self.path, "w", encoding="utf-8") as f:
            self._yaml.dump(self._yaml_data, f)

    # ----------------------
    # dot-access
    # ----------------------
    def __getattr__(self, item):
        if self.config is not None and hasattr(self.config, item):
            return getattr(self.config, item)
        raise AttributeError(f"{item} not found in GladosConfig")

    def __setattr__(self, key, value):
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)
