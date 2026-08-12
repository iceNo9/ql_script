from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from utils.log import get_logger

logger = get_logger(__name__)

# ----------------------
# 配置宏定义
# ----------------------
CONFIG_ROOT_KEY = "baiyefee"           # YAML 根节点名称


# ----------------------
# Pydantic Schema
# ----------------------
class Account(BaseModel):
    """账号配置"""
    username: str = Field(..., description="账号用户名（主键）")
    password: str = Field(..., description="账号密码")


class ConfigModel(BaseModel):
    """配置模型"""
    accounts: List[Account] = Field(
        default_factory=list,
        description="账号列表"
    )


# ----------------------
# 配置管理类
# ----------------------
class ConfigManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.config: ConfigModel | None = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml_data = {}

    def read(self) -> Optional[ConfigModel]:
        """加载 YAML 并验证"""
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._yaml_data = self._yaml.load(f) or {}
        else:
            logger.error(f"配置文件缺失 {self.path}，强制结束运行")
            return None

        self.config = ConfigModel(**self._yaml_data.get(CONFIG_ROOT_KEY, {}))
        return self.config

    def save(self):
        """写回 YAML，保留原格式"""
        if self.config is None:
            raise ValueError("Config is not loaded")
        self._yaml_data[CONFIG_ROOT_KEY] = self.config.model_dump()
        with open(self.path, "w", encoding="utf-8") as f:
            self._yaml.dump(self._yaml_data, f)

    def get_account_by_username(self, username: str) -> Optional[Account]:
        """根据用户名获取账号配置"""
        if self.config is None:
            return None
        for account in self.config.accounts:
            if account.username == username:
                return account
        return None

    def get_all_usernames(self) -> List[str]:
        """获取所有用户名"""
        if self.config is None:
            return []
        return [account.username for account in self.config.accounts]

    def get_accounts_count(self) -> int:
        """获取账号数量"""
        if self.config is None:
            return 0
        return len(self.config.accounts)

    # ----------------------
    # dot-access
    # ----------------------
    def __getattr__(self, item):
        if self.config is not None and hasattr(self.config, item):
            return getattr(self.config, item)
        raise AttributeError(f"{item} not found in Config")

    def __setattr__(self, key, value):
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)