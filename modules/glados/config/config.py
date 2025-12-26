# config.py
import os
import shutil
from pathlib import Path
from typing import Any, List, Dict, Optional, Type, TypeVar
import ruamel.yaml

from modules.glados.config.email_config import EmailConfig
from modules.glados.config.glados_config import GladosConfig
from modules.glados.config.account import Account

T = TypeVar('T')

class Config:
    """配置管理类，使用领域对象"""
    
    def __init__(self, config_path: str, default_config_path: str):
        """
        初始化配置
        
        Args:
            config_path: 用户配置文件路径
            default_config_path: 默认配置文件路径
        """
        self.config_path = Path(config_path)
        self.default_config_path = Path(default_config_path)
        self.yaml = ruamel.yaml.YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        
        # 领域对象
        self._email_config: Optional[EmailConfig] = None
        self._glados_config: Optional[GladosConfig] = None
        self._accounts: List[Account] = []
        
        # 确保配置文件存在
        self._ensure_config_exists()
        
        # 加载配置
        self._load_config()
    
    def _ensure_config_exists(self) -> None:
        """确保配置文件存在，如果不存在则从默认配置复制"""
        if not self.config_path.exists():
            if not self.default_config_path.exists():
                # 如果默认配置也不存在，创建基本的默认配置
                self._create_default_config()
            else:
                # 复制默认配置文件
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.default_config_path, self.config_path)
                print(f"已从默认配置创建配置文件: {self.config_path}")
    
    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        default_config = {
            "email": {
                "imap_server": "imap.example.com",
                "imap_port": 993,
                "username": "test@example.com",
                "password": "",
                "ssl": True
            },
            "glados": {
                "auth_url": "https://glados.rocks/api/authorization",
                "checkin_url": "https://glados.rocks/api/user/checkin",
                "login_api": "https://glados.rocks/api/login",
                "login_url": "https://glados.rocks/login",
                "status_url": "https://glados.rocks/api/user/status",
                "threshold": 200.0
            },
            "accounts": []
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.yaml.dump(default_config, f)
        print(f"已创建默认配置文件: {self.config_path}")
    
    def _load_config(self) -> None:
        """加载YAML配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            raw_config = self.yaml.load(f)
        
        # 加载各个领域对象
        if raw_config:
            self._email_config = EmailConfig.from_dict(
                raw_config.get('email', {})
            )
            self._glados_config = GladosConfig.from_dict(
                raw_config.get('glados', {})
            )
            
            # 加载账户列表
            accounts_data = raw_config.get('accounts', [])
            self._accounts = [
                Account.from_dict(acc) for acc in accounts_data
            ]
    
    def save(self) -> None:
        """保存配置到文件"""
        config_dict = {
            "email": self._email_config.to_dict() if self._email_config else {},
            "glados": self._glados_config.to_dict() if self._glados_config else {},
            "accounts": [acc.to_dict() for acc in self._accounts]
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.yaml.dump(config_dict, f)
    
    def reload(self) -> None:
        """重新加载配置文件"""
        self._load_config()
    
    # Email配置访问器
    @property
    def email(self) -> EmailConfig:
        """获取邮箱配置"""
        if self._email_config is None:
            self._email_config = EmailConfig()
        return self._email_config
    
    @email.setter
    def email(self, value: EmailConfig) -> None:
        """设置邮箱配置"""
        if not isinstance(value, EmailConfig):
            raise TypeError("email must be an EmailConfig instance")
        self._email_config = value
    
    # Glados配置访问器
    @property
    def glados(self) -> GladosConfig:
        """获取Glados配置"""
        if self._glados_config is None:
            self._glados_config = GladosConfig()
        return self._glados_config
    
    @glados.setter
    def glados(self, value: GladosConfig) -> None:
        """设置Glados配置"""
        if not isinstance(value, GladosConfig):
            raise TypeError("glados must be a GladosConfig instance")
        self._glados_config = value
    
    # Accounts配置访问器
    @property
    def accounts(self) -> List[Account]:
        """获取账户列表"""
        return self._accounts
    
    @accounts.setter
    def accounts(self, value: List[Account]) -> None:
        """设置账户列表"""
        if not all(isinstance(acc, Account) for acc in value):
            raise TypeError("All items in accounts must be Account instances")
        self._accounts = value
    
    # 账户管理方法
    def get_account(self, name: str) -> Optional[Account]:
        """根据名称获取账户"""
        for account in self._accounts:
            if account.name == name:
                return account
        return None
    
    def add_account(self, account: Account) -> None:
        """添加账户"""
        if not isinstance(account, Account):
            raise TypeError("account must be an Account instance")
        
        # 检查是否已存在同名账户
        if any(acc.name == account.name for acc in self._accounts):
            raise ValueError(f"Account with name '{account.name}' already exists")
        
        self._accounts.append(account)
    
    def remove_account(self, name: str) -> bool:
        """根据名称删除账户"""
        for i, account in enumerate(self._accounts):
            if account.name == name:
                self._accounts.pop(i)
                return True
        return False
    
    def update_account(self, account: Account) -> bool:
        """更新账户信息"""
        for i, existing_account in enumerate(self._accounts):
            if existing_account.name == account.name:
                self._accounts[i] = account
                return True
        return False
    
    # 验证方法
    def validate(self) -> Dict[str, List[str]]:
        """验证配置有效性"""
        errors = {}
        
        # 验证邮箱配置
        if self._email_config and not self._email_config.validate():
            errors.setdefault('email', []).append("Invalid email configuration")
        
        # 验证账户
        account_errors = []
        for i, account in enumerate(self._accounts):
            if not account.name:
                account_errors.append(f"Account at index {i} has no name")
            if not account.username:
                account_errors.append(f"Account {account.name} has no username")
        
        if account_errors:
            errors['accounts'] = account_errors
        
        return errors
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (f"Config(path={self.config_path}, "
                f"accounts={len(self._accounts)}, "
                f"email_valid={self.email.validate() if self._email_config else False})")