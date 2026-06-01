# modules/hifiti/core/table.py

"""
hifiti 模块数据库表定义
"""

import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from common.database import BaseTable
from common.log import get_logger

logger = get_logger(__name__)


# ==================== 数据库 DTO ====================

@dataclass
class User:
    """用户数据 DTO，对应数据库 hifiti 表"""
    
    username: str                                    # 用户名（主键）
    coins: int = 0                                   # 金币
    last_sign_date: str = ""                         # 最后签到日期 (YYYY-MM-DD)
    last_sign_reward: int = 0                        # 最后签到获得金币
    last_sign_rank: int = 0                          # 最后签到排名
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
            "coins": self.coins,
            "last_sign_date": self.last_sign_date,
            "last_sign_reward": self.last_sign_reward,
            "last_sign_rank": self.last_sign_rank,
            "cookies": self.cookies,
            "cookies_expire_at": self.cookies_expire_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """从字典创建 User 对象"""
        return cls(
            username=data.get("username", ""),
            coins=data.get("coins", 0),
            last_sign_date=data.get("last_sign_date", ""),
            last_sign_reward=data.get("last_sign_reward", 0),
            last_sign_rank=data.get("last_sign_rank", 0),
            cookies=data.get("cookies", {}),
            cookies_expire_at=data.get("cookies_expire_at", 0),
        )
    
    # ==================== 更新方法 ====================
    
    def update_coins(self, new_coins: int):
        """更新金币"""
        self.coins = new_coins
    
    def update_sign_info(self, reward: int, rank: int, coins: int = None):
        """更新签到信息"""
        self.last_sign_date = datetime.now().strftime("%Y-%m-%d")
        self.last_sign_reward = reward
        self.last_sign_rank = rank
        if coins is not None:
            self.coins = coins
    
    def update_cookies(self, cookies: Dict[str, Any], expire_at: int):
        """更新 cookies"""
        self.cookies = cookies
        self.cookies_expire_at = expire_at


# ==================== 数据库表类 ====================

class Table(BaseTable):
    """用户数据表"""
    
    __tablename__ = "hifiti"
    
    __table_schema__ = """
    CREATE TABLE IF NOT EXISTS hifiti (
        username TEXT PRIMARY KEY,
        coins INTEGER DEFAULT 0,
        last_sign_date TEXT DEFAULT '',
        last_sign_reward INTEGER DEFAULT 0,
        last_sign_rank INTEGER DEFAULT 0,
        cookies TEXT DEFAULT '{}',
        cookies_expire_at INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """
    
    __indexes__ = [
        "CREATE INDEX IF NOT EXISTS idx_hifiti_last_sign_date ON hifiti(last_sign_date)",
        "CREATE INDEX IF NOT EXISTS idx_hifiti_coins ON hifiti(coins)",
        "CREATE INDEX IF NOT EXISTS idx_hifiti_cookies_expire_at ON hifiti(cookies_expire_at)",
    ]
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger("hifiti.db")
    
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
    
    def update_coins(self, username: str, coins: int) -> bool:
        """
        更新用户金币
        
        Args:
            username: 用户名
            coins: 金币数量
            
        Returns:
            是否成功
        """
        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__} 
                SET coins = ?, updated_at = strftime('%s','now')
                WHERE username = ?
            """, (coins, username))
            return conn.total_changes > 0
    
    def update_sign_info(self, username: str, reward: int, rank: int, coins: int = None) -> bool:
        """
        更新签到信息
        
        Args:
            username: 用户名
            reward: 获得金币
            rank: 排名
            coins: 总金币（可选）
            
        Returns:
            是否成功
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        with self._get_connection() as conn:
            if coins is not None:
                conn.execute(f"""
                    UPDATE {self.__tablename__} 
                    SET last_sign_date = ?, last_sign_reward = ?, last_sign_rank = ?, coins = ?, updated_at = strftime('%s','now')
                    WHERE username = ?
                """, (today, reward, rank, coins, username))
            else:
                conn.execute(f"""
                    UPDATE {self.__tablename__} 
                    SET last_sign_date = ?, last_sign_reward = ?, last_sign_rank = ?, updated_at = strftime('%s','now')
                    WHERE username = ?
                """, (today, reward, rank, username))
            
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
    
    def get_ranking_by_coins(self, limit: int = 10) -> List[User]:
        """
        按金币数量获取用户排行榜
        
        Args:
            limit: 返回数量
            
        Returns:
            User 对象列表
        """
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__} 
                ORDER BY coins DESC 
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


def update_coins(username: str, coins: int) -> bool:
    """更新金币"""
    return get_table().update_coins(username, coins)


def update_sign_info(username: str, reward: int, rank: int, coins: int = None) -> bool:
    """更新签到信息"""
    return get_table().update_sign_info(username, reward, rank, coins)


def update_cookies(username: str, cookies: Dict[str, Any], expire_at: int) -> bool:
    """更新 cookies"""
    return get_table().update_cookies(username, cookies, expire_at)

