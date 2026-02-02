# common\global_config.py
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, EmailStr
from ruamel.yaml import YAML

# ----------------------
# 配置 Schema
# ----------------------
class IMAPConfig(BaseModel):
    host: str = "imap.qq.com"
    port: int = 993
    secure: bool = True

class SMTPConfig(BaseModel):
    host: str = "smtp.qq.com"
    port: int = 465
    secure: bool = True

class EmailConfig(BaseModel):
    username: str = ""
    password: str = ""
    imap: IMAPConfig = Field(default_factory=lambda: IMAPConfig())
    smtp: SMTPConfig = Field(default_factory=lambda: SMTPConfig())

class GlobalConfig(BaseModel):
    email: EmailConfig
    email_to: list[EmailStr] = []
    proxy: list[str] = []

# ----------------------
# 配置管理类
# ----------------------
class GlobalConfigManager:
    def __init__(self, path: str ):
        self.path = Path(path)
        self.config: Optional[GlobalConfig] = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True  # 保留引号、注释
        self._yaml.indent(mapping=2, sequence=4, offset=2)

    def read(self) -> GlobalConfig:
        """加载 YAML 并验证"""
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found")
        with open(self.path, "r", encoding="utf-8") as f:
            raw = self._yaml.load(f) or {}
        self.config = GlobalConfig(**raw.get("global", {}))
        self._yaml_data = raw  # 保留原始 YAML 对象
        return self.config

    def save(self):
        """写回 YAML，保持原有注释和结构"""
        if self.config is None:
            raise ValueError("Config is not loaded")

        # 将 Pydantic 对象同步到原始 YAML 对象
        self._yaml_data['global'] = self.config.model_dump()

        with open(self.path, "w", encoding="utf-8") as f:
            self._yaml.dump(self._yaml_data, f)

    # ----------------------
    # dot-access 代理
    # ----------------------
    def __getattr__(self, item):
        if self.config is not None and hasattr(self.config, item):
            return getattr(self.config, item)
        raise AttributeError(f"{item} not found in config")

    def __setattr__(self, key, value):
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)
