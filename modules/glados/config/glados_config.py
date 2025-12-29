# glados_config.py
from dataclasses import dataclass

@dataclass
class GladosConfig:
    """Glados API配置类"""
    auth_url: str = "https://glados.rocks/api/authorization"
    checkin_url: str = "https://glados.rocks/api/user/checkin"
    login_api: str = "https://glados.rocks/api/login"
    login_url: str = "https://glados.rocks/login"
    status_url: str = "https://glados.rocks/api/user/status"
    redeem_url: str = "https://glados.rocks/api/user/code"
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "auth_url": self.auth_url,
            "checkin_url": self.checkin_url,
            "login_api": self.login_api,
            "login_url": self.login_url,
            "status_url": self.status_url,
            "redeem_url": self.redeem_url,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'GladosConfig':
        """从字典创建对象"""
        return cls(
            auth_url=data.get("auth_url", "https://glados.rocks/api/authorization"),
            checkin_url=data.get("checkin_url", "https://glados.rocks/api/user/checkin"),
            login_api=data.get("login_api", "https://glados.rocks/api/login"),
            login_url=data.get("login_url", "https://glados.rocks/login"),
            status_url=data.get("status_url", "https://glados.rocks/api/user/status"),
            redeem_url=data.get("redeem_url", "https://glados.rocks/api/user/code"),
        )