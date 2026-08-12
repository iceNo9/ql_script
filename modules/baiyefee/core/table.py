"""
baiyefee 模块数据库表定义
"""

import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from utils.database import BaseTable
from utils.log import get_logger

logger = get_logger(__name__)


# ==================== 数据库 DTO ====================

@dataclass
class User:
    """用户数据 DTO，对应数据库 baiyefee 表"""
    
    username: str                                    # 用户名（主键）
    credit: int = 0                                  # 积分
    continuous_sign_days: int = 0                    # 连续签到天数
    last_sign_date: str = ""                         # 最后签到日期 (YYYY-MM-DD)
    last_sign_reward: int = 0                        # 最后签到获得积分
    cookies: Optional[Dict[str, Any]] = field(default_factory=dict)   # Cookies
    cookies_expire_at: int = 0                       # cookies 过期时间戳
    
    def __post_init__(self):
        """初始化默认值"""
        if self.cookies is None:
            self.cookies = {}
        if not self.last_sign_date:
            self.last_sign_date = datetime.now().strftime("%Y-%m-%d")
    
    # ==================== 便捷属性 ====================
    
    @property
    def is_cookies_valid(self) -> bool:
        """cookies 是否有效（未过期）"""
        if not self.cookies:
            return False
        if self.cookies_expire_at <= 0:
            return False
        return int(datetime.now().timestamp()) < self.cookies_expire_at
    
    def is_sign_today(self) -> bool:
        """今日是否已签到"""
        return self.last_sign_date == datetime.now().strftime("%Y-%m-%d")
    
    # ==================== 字典转换 ====================
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于数据库存储"""
        return {
            "username": self.username,
            "credit": self.credit,
            "continuous_sign_days": self.continuous_sign_days,
            "last_sign_date": self.last_sign_date,
            "last_sign_reward": self.last_sign_reward,
            "cookies": self.cookies,
            "cookies_expire_at": self.cookies_expire_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """从字典创建 User 对象"""
        return cls(
            username=data.get("username", ""),
            credit=data.get("credit", 0),
            continuous_sign_days=data.get("continuous_sign_days", 0),
            last_sign_date=data.get("last_sign_date", ""),
            last_sign_reward=data.get("last_sign_reward", 0),
            cookies=data.get("cookies", {}),
            cookies_expire_at=data.get("cookies_expire_at", 0),
        )
    
    # ==================== 更新方法 ====================
    
    def update_credit(self, new_credit: int):
        """更新积分"""
        self.credit = new_credit
    
    def update_sign_info(self, reward: int, continuous_days: int, credit: int = None):
        """更新签到信息"""
        self.last_sign_date = datetime.now().strftime("%Y-%m-%d")
        self.last_sign_reward = reward
        self.continuous_sign_days = continuous_days
        if credit is not None:
            self.credit = credit
    
    def update_cookies(self, cookies: Dict[str, Any], expire_at: int):
        """更新 cookies"""
        self.cookies = cookies
        self.cookies_expire_at = expire_at


# ==================== 数据库表类 ====================

class Table(BaseTable):
    """用户数据表"""
    
    __tablename__ = "baiyefee"
    
    __table_schema__ = """
    CREATE TABLE IF NOT EXISTS baiyefee (
        username TEXT PRIMARY KEY,
        credit INTEGER DEFAULT 0,
        continuous_sign_days INTEGER DEFAULT 0,
        last_sign_date TEXT DEFAULT '',
        last_sign_reward INTEGER DEFAULT 0,
        cookies TEXT DEFAULT '{}',
        cookies_expire_at INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """
    
    __indexes__ = [
        "CREATE INDEX IF NOT EXISTS idx_baiyefee_last_sign_date ON baiyefee(last_sign_date)",
        "CREATE INDEX IF NOT EXISTS idx_baiyefee_credit ON baiyefee(credit)",
        "CREATE INDEX IF NOT EXISTS idx_baiyefee_cookies_expire_at ON baiyefee(cookies_expire_at)",
        "CREATE INDEX IF NOT EXISTS idx_baiyefee_continuous_sign_days ON baiyefee(continuous_sign_days)",
    ]
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger("baiyefee.db")
    
    # ==================== CRUD 操作 ====================
    
    def get_user(self, username: str) -> Optional[User]:
        """
        获取用户
        
        Args:
            username: 用户名
            
        Returns:
            User 对象或 None
        """
        data = self.get(username)
        if data:
            return User.from_dict(data)
        return None
    
    def upsert_user(self, user: User) -> bool:
        """
        插入或更新用户
        
        Args:
            user: User 对象
            
        Returns:
            是否成功
        """
        return self.upsert(user.username, user.to_dict())
    
    def update_credit(self, username: str, credit: int) -> bool:
        """
        更新用户积分
        
        Args:
            username: 用户名
            credit: 积分数量
            
        Returns:
            是否成功
        """
        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__} 
                SET credit = ?, updated_at = strftime('%s','now')
                WHERE username = ?
            """, (credit, username))
            return conn.total_changes > 0
    
    def update_sign_info(self, username: str, reward: int, continuous_days: int, credit: int = None) -> bool:
        """
        更新签到信息
        
        Args:
            username: 用户名
            reward: 获得积分
            continuous_days: 连续签到天数
            credit: 总积分（可选）
            
        Returns:
            是否成功
        """
        today = datetime.now().strftime("%Y-%Y-%m-%d")
        
        with self._get_connection() as conn:
            if credit is not None:
                conn.execute(f"""
                    UPDATE {self.__tablename__} 
                    SET last_sign_date = ?, last_sign_reward = ?, continuous_sign_days = ?, credit = ?, updated_at = strftime('%s','now')
                    WHERE username = ?
                """, (today, reward, continuous_days, credit, username))
            else:
                conn.execute(f"""
                    UPDATE {self.__tablename__} 
                    SET last_sign_date = ?, last_sign_reward = ?, continuous_sign_days = ?, updated_at = strftime('%s','now')
                    WHERE username = ?
                """, (today, reward, continuous_days, username))
            
            return conn.total_changes > 0
    
    def update_cookies(self, username: str, cookies: Dict[str, Any], expire_at: int) -> bool:
        """
        更新用户 cookies
        
        Args:
            username: 用户名
            cookies: cookies 字典
            expire_at: 过期时间戳
            
        Returns:
            是否成功
        """
        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__} 
                SET cookies = ?, cookies_expire_at = ?, updated_at = strftime('%s','now')
                WHERE username = ?
            """, (json.dumps(cookies), expire_at, username))
            return conn.total_changes > 0
    
    def get_all_users(self) -> List[User]:
        """
        获取所有用户
        
        Returns:
            User 对象列表
        """
        data_list = self.get_all()
        return [User.from_dict(data) for data in data_list]
    
    def get_active_users(self) -> List[User]:
        """
        获取 cookies 未过期的用户
        
        Returns:
            User 对象列表
        """
        now = int(datetime.now().timestamp())
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__} 
                WHERE cookies_expire_at > ?
                ORDER BY updated_at DESC
            """, (now,)).fetchall()
            return [User.from_dict(self._row_to_dict(row)) for row in rows]
    
    def get_today_signed_users(self) -> List[User]:
        """
        获取今日已签到的用户
        
        Returns:
            User 对象列表
        """
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__} 
                WHERE last_sign_date = ?
            """, (today,)).fetchall()
            return [User.from_dict(self._row_to_dict(row)) for row in rows]
    
    def get_users_need_sign(self) -> List[User]:
        """
        获取今日未签到的用户（cookies 有效且今日未签到）
        
        Returns:
            User 对象列表
        """
        now = int(datetime.now().timestamp())
        today = datetime.now().strftime("%Y-%m-%d")
        
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__} 
                WHERE cookies_expire_at > ? 
                AND last_sign_date != ?
                ORDER BY updated_at DESC
            """, (now, today)).fetchall()
            return [User.from_dict(self._row_to_dict(row)) for row in rows]
    
    def get_ranking_by_credit(self, limit: int = 10) -> List[User]:
        """
        按积分数量获取用户排行榜
        
        Args:
            limit: 返回数量
            
        Returns:
            User 对象列表
        """
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__} 
                ORDER BY credit DESC 
                LIMIT ?
            """, (limit,)).fetchall()
            return [User.from_dict(self._row_to_dict(row)) for row in rows]


# ==================== 全局实例 ====================

_user_table = None


def get_table() -> Table:
    """获取 Table 单例"""
    global _user_table
    if _user_table is None:
        _user_table = Table()
    return _user_table


# ==================== 便捷函数 ====================

def get_user(username: str) -> Optional[User]:
    """获取用户"""
    return get_table().get_user(username)


def save_user(user: User) -> bool:
    """保存用户"""
    return get_table().upsert_user(user)


def update_credit(username: str, credit: int) -> bool:
    """更新积分"""
    return get_table().update_credit(username, credit)


def update_sign_info(username: str, reward: int, continuous_days: int, credit: int = None) -> bool:
    """更新签到信息"""
    return get_table().update_sign_info(username, reward, continuous_days, credit)


def update_cookies(username: str, cookies: Dict[str, Any], expire_at: int) -> bool:
    """更新 cookies"""
    return get_table().update_cookies(username, cookies, expire_at)