# account.py
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class Account:
    """账户类"""
    name: str = ""
    username: str = ""
    balance: float = 0.0
    leftDays: int = 0
    expireAt: str = ""
    traffic: int = 0
    total_traffic: int = 0
    cookies: Dict[str, Any] = field(default_factory=dict)
    vip_level: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """将Account对象转换为字典格式"""
        return {
            "name": self.name,
            "username": self.username,
            "balance": self.balance,
            "leftDays": self.leftDays,
            "expireAt": self.expireAt,
            "traffic": self.traffic,
            "total_traffic": self.total_traffic,
            "cookies": self.cookies.copy(),
            "vip_level": self.vip_level
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Account':
        """从字典创建Account对象"""
        return cls(
            name=data.get("name", ""),
            username=data.get("username", ""),
            balance=data.get("balance", 0.0),
            leftDays=data.get("leftDays", 0),
            expireAt=data.get("expireAt", ""),
            traffic=data.get("traffic", 0),
            total_traffic=data.get("total_traffic", 0),
            cookies=data.get("cookies", {}),
            vip_level=data.get("vip_level", 0)
        )
    
    def is_expired(self) -> bool:
        """检查账户是否已过期"""
        if not self.expireAt:
            return False
        
        try:
            expire_date = datetime.strptime(self.expireAt, '%Y-%m-%d %H:%M:%S')
            return datetime.now() > expire_date
        except ValueError:
            # 尝试其他格式
            try:
                expire_date = datetime.strptime(self.expireAt, '%Y-%m-%d')
                return datetime.now() > expire_date
            except ValueError:
                return False
    
    def get_traffic_usage_percent(self) -> float:
        """获取流量使用百分比"""
        if self.total_traffic == 0:
            return 0.0
        return (self.traffic / self.total_traffic) * 100
    
    def get_formatted_traffic(self) -> str:
        """获取格式化的流量信息"""
        def format_bytes(size: int) -> str:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0:
                    return f"{size:.2f} {unit}"
                size /= 1024.0
            return f"{size:.2f} PB"
        
        used = format_bytes(self.traffic)
        total = format_bytes(self.total_traffic)
        return f"{used} / {total} ({self.get_traffic_usage_percent():.2f}%)"