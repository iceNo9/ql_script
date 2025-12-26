# email_config.py
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class EmailConfig:
    """邮箱配置类"""
    imap_server: str = ""
    imap_port: int = 993
    username: str = ""
    password: str = ""
    notify_address: Optional[str] = None
    ssl: bool = True
    # 可选的附加配置
    smtp_server: str = ""
    smtp_port: int = 587
    timeout: int = 30
    search_folders: list = field(default_factory=lambda: ['INBOX'])
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "imap_server": self.imap_server,
            "imap_port": self.imap_port,
            "username": self.username,
            "password": self.password,
            "ssl": self.ssl,
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "timeout": self.timeout,
            "search_folders": self.search_folders.copy()
        }
        
        if self.notify_address is not None:
            result["notify_address"] = self.notify_address
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EmailConfig':
        """从字典创建对象"""
        # 处理旧格式的兼容性
        if "address" in data and "username" not in data:
            data["username"] = data["address"]
        
        return cls(
            imap_server=data.get("imap_server", ""),
            imap_port=data.get("imap_port", 993),
            username=data.get("username", ""),
            password=data.get("password", ""),
            notify_address=data.get("notify_address"),
            ssl=data.get("ssl", True),
            smtp_server=data.get("smtp_server", ""),
            smtp_port=data.get("smtp_port", 587),
            timeout=data.get("timeout", 30),
            search_folders=data.get("search_folders", ['INBOX'])
        )
    
    def validate(self) -> bool:
        """验证配置是否有效"""
        # 基本验证
        if not self.imap_server:
            return False
        if not self.username or "@" not in self.username:
            return False
        if not self.password:
            return False
        if self.imap_port <= 0 or self.imap_port > 65535:
            return False
            
        return True
    
    def get_imap_host_port(self) -> tuple:
        """获取IMAP服务器和端口"""
        return self.imap_server, self.imap_port
    
    def get_smtp_host_port(self) -> tuple:
        """获取SMTP服务器和端口"""
        smtp_server = self.smtp_server or self._infer_smtp_server()
        return smtp_server, self.smtp_port
    
    def _infer_smtp_server(self) -> str:
        """根据邮箱地址推断SMTP服务器"""
        if "qq.com" in self.username:
            return "smtp.qq.com"
        elif "gmail.com" in self.username:
            return "smtp.gmail.com"
        elif "163.com" in self.username:
            return "smtp.163.com"
        elif "126.com" in self.username:
            return "smtp.126.com"
        elif "outlook.com" in self.username or "hotmail.com" in self.username:
            return "smtp-mail.outlook.com"
        else:
            return ""
    
    def __str__(self) -> str:
        """友好的字符串表示"""
        return (f"EmailConfig(server={self.imap_server}:{self.imap_port}, "
                f"user={self.mask_username()}, ssl={self.ssl})")
    
    def mask_username(self) -> str:
        """隐藏用户名部分信息"""
        if not self.username:
            return ""
        
        if "@" in self.username:
            local, domain = self.username.split("@", 1)
            if len(local) > 4:
                masked = local[:2] + "***" + local[-2:]
            else:
                masked = "***"
            return f"{masked}@{domain}"
        return "***"
    
    def mask_password(self) -> str:
        """隐藏密码信息"""
        if not self.password:
            return ""
        if len(self.password) > 4:
            return self.password[:2] + "***" + self.password[-2:]
        return "***"