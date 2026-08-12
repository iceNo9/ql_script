# common/global_config.py
import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
from ruamel.yaml import YAML

# ==================== 数据库路径配置 ====================

# 项目根目录（假设 common 目录在项目根目录下）
PROJECT_ROOT = Path(__file__).parent.parent

# 数据库路径（可通过环境变量覆盖）
DB_PATH = os.environ.get("SIGN_DB_PATH", str(PROJECT_ROOT / "data" / "data.db"))

# 确保数据目录存在
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


# ==================== 配置 Schema ====================

class IMAPConfig(BaseModel):
    """IMAP 邮件服务器配置"""
    host: str = Field(default="imap.qq.com", description="IMAP 服务器地址")
    port: int = Field(default=993, description="IMAP 服务器端口")
    secure: bool = Field(default=True, description="是否使用 SSL/TLS")


class SMTPConfig(BaseModel):
    """SMTP 邮件服务器配置"""
    host: str = Field(default="smtp.qq.com", description="SMTP 服务器地址")
    port: int = Field(default=465, description="SMTP 服务器端口")
    secure: bool = Field(default=True, description="是否使用 SSL/TLS")


class EmailConfig(BaseModel):
    """邮箱配置"""
    username: str = Field(default="", description="邮箱账号")
    password: str = Field(default="", description="邮箱密码/授权码")
    imap: IMAPConfig = Field(default_factory=IMAPConfig, description="IMAP 配置")
    smtp: SMTPConfig = Field(default_factory=SMTPConfig, description="SMTP 配置")


class GlobalConfig(BaseModel):
    """全局配置"""
    email: EmailConfig = Field(..., description="邮箱配置")
    email_to: List[EmailStr] = Field(default_factory=list, description="邮件接收地址列表")
    proxy: List[str] = Field(default_factory=list, description="代理列表")


# ==================== 配置管理类 ====================

class GlobalConfigManager:
    """全局配置管理器"""
    
    def __init__(self, path: str):
        """
        初始化配置管理器
        
        Args:
            path: 配置文件路径
        """
        self.path = Path(path)
        self.config: Optional[GlobalConfig] = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True  # 保留引号、注释
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml_data = {}

    def read(self) -> GlobalConfig:
        """
        加载 YAML 并验证
        
        Returns:
            GlobalConfig: 全局配置对象
            
        Raises:
            FileNotFoundError: 配置文件不存在
        """
        if not self.path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.path}")
        
        with open(self.path, "r", encoding="utf-8") as f:
            self._yaml_data = self._yaml.load(f) or {}
        
        self.config = GlobalConfig(**self._yaml_data.get("global", {}))
        return self.config

    def save(self):
        """
        写回 YAML，保持原有注释和结构
        
        Raises:
            ValueError: 配置未加载
        """
        if self.config is None:
            raise ValueError("配置未加载，请先调用 read() 方法")
        
        # 将 Pydantic 对象同步到原始 YAML 对象
        self._yaml_data['global'] = self.config.model_dump()
        
        with open(self.path, "w", encoding="utf-8") as f:
            self._yaml.dump(self._yaml_data, f)

    def reload(self) -> GlobalConfig:
        """
        重新加载配置
        
        Returns:
            GlobalConfig: 重新加载后的全局配置对象
        """
        return self.read()

    # ----------------------
    # 属性访问代理
    # ----------------------
    
    def __getattr__(self, item):
        """代理访问 config 对象的属性"""
        if self.config is not None and hasattr(self.config, item):
            return getattr(self.config, item)
        raise AttributeError(f"'{type(self).__name__}' 对象没有属性 '{item}'")

    def __setattr__(self, key, value):
        """设置属性，保留管理类自身的属性"""
        if key in {"path", "config", "_yaml", "_yaml_data"}:
            super().__setattr__(key, value)
        elif self.config is not None and hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            super().__setattr__(key, value)


# ==================== 导出 ====================

__all__ = [
    # 数据库配置
    'PROJECT_ROOT',
    'DB_PATH',
    # 配置 Schema
    'IMAPConfig',
    'SMTPConfig',
    'EmailConfig',
    'GlobalConfig',
    # 配置管理器
    'GlobalConfigManager',
]