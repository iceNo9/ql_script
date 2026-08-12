# modules\southplus\core\table.py

import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from utils.database import BaseTable
from utils.log import get_logger

logger = get_logger(__name__)


# ====================
# DTO
# ====================

@dataclass
class User:
    """SouthPlus 用户数据"""

    username: str

    # ====================
    # SP币
    # ====================
    credit: int = 0
    last_credit: int = 0

    # ====================
    # 日常任务
    # ====================
    last_daily_time: str = ""
    next_daily_time: str = ""
    daily_count: int = 0

    # ====================
    # 周常任务
    # ====================
    last_weekly_time: str = ""
    next_weekly_time: str = ""
    weekly_count: int = 0

    # ====================
    # 邮件
    # ====================
    last_mail_time: str = ""

    def __post_init__(self):
        self.last_daily_time = self.last_daily_time or ""
        self.next_daily_time = self.next_daily_time or ""
        self.last_weekly_time = self.last_weekly_time or ""
        self.next_weekly_time = self.next_weekly_time or ""
        self.last_mail_time = self.last_mail_time or ""

    # ====================
    # 状态判断
    # ====================

    def can_daily(self) -> bool:
        if not self.next_daily_time:
            return True
        return datetime.now() >= datetime.fromisoformat(self.next_daily_time)

    def can_weekly(self) -> bool:
        if not self.next_weekly_time:
            return True
        return datetime.now() >= datetime.fromisoformat(self.next_weekly_time)

    # ====================
    # 更新行为
    # ====================

    def add_daily_done(self):
        self.daily_count += 1
        self.last_daily_time = datetime.now().isoformat()

    def add_weekly_done(self):
        self.weekly_count += 1
        self.last_weekly_time = datetime.now().isoformat()

    def update_mail_time(self):
        self.last_mail_time = datetime.now().isoformat()

    # ====================
    # SP币操作
    # ====================
    
    def update_credit_with_last(self, new_credit: int):
        """更新SP币，同时记录上次的值"""
        self.last_credit = self.credit
        self.credit = new_credit
    
    def get_credit_change(self) -> int:
        """获取SP币变化量（当前-上次）"""
        return self.credit - self.last_credit
    
    def has_credit_changed(self) -> bool:
        """检查SP币是否发生变化"""
        return self.credit != self.last_credit
    
    # ====================
    # DB转换
    # ====================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "credit": self.credit,
            "last_credit": self.last_credit,

            "last_daily_time": self.last_daily_time,
            "next_daily_time": self.next_daily_time,
            "daily_count": self.daily_count,

            "last_weekly_time": self.last_weekly_time,
            "next_weekly_time": self.next_weekly_time,
            "weekly_count": self.weekly_count,

            "last_mail_time": self.last_mail_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        return cls(
            username=data.get("username", ""),
            credit=data.get("credit", 0),
            last_credit=data.get("last_credit", 0),

            last_daily_time=data.get("last_daily_time", ""),
            next_daily_time=data.get("next_daily_time", ""),
            daily_count=data.get("daily_count", 0),

            last_weekly_time=data.get("last_weekly_time", ""),
            next_weekly_time=data.get("next_weekly_time", ""),
            weekly_count=data.get("weekly_count", 0),

            last_mail_time=data.get("last_mail_time", ""),
        )


# ====================
# Table
# ====================

class Table(BaseTable):
    """SouthPlus 用户表"""

    __tablename__ = "southplus"

    __table_schema__ = """
    CREATE TABLE IF NOT EXISTS southplus (
        username TEXT PRIMARY KEY,
        credit INTEGER DEFAULT 0,
        last_credit INTEGER DEFAULT 0,

        last_daily_time TEXT DEFAULT '',
        next_daily_time TEXT DEFAULT '',
        daily_count INTEGER DEFAULT 0,

        last_weekly_time TEXT DEFAULT '',
        next_weekly_time TEXT DEFAULT '',
        weekly_count INTEGER DEFAULT 0,

        last_mail_time TEXT DEFAULT '',

        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """

    __indexes__ = [
        "CREATE INDEX IF NOT EXISTS idx_southplus_credit ON southplus(credit)",
        "CREATE INDEX IF NOT EXISTS idx_southplus_last_credit ON southplus(last_credit)",
        "CREATE INDEX IF NOT EXISTS idx_southplus_next_daily ON southplus(next_daily_time)",
        "CREATE INDEX IF NOT EXISTS idx_southplus_next_weekly ON southplus(next_weekly_time)",
        "CREATE INDEX IF NOT EXISTS idx_southplus_daily_count ON southplus(daily_count)",
        "CREATE INDEX IF NOT EXISTS idx_southplus_weekly_count ON southplus(weekly_count)",
    ]

    def __init__(self):
        super().__init__()
        self.logger = get_logger("southplus.db")

    # ====================
    # CRUD
    # ====================

    def get_user(self, username: str) -> Optional[User]:
        data = self.get(username)
        return User.from_dict(data) if data else None

    def upsert_user(self, user: User) -> bool:
        return self.upsert(user.username, user.to_dict())

    def get_all_users(self) -> List[User]:
        return [User.from_dict(i) for i in self.get_all()]

    # ====================
    # SP币
    # ====================

    def update_credit(self, username: str, credit: int) -> bool:
        """更新SP币，自动记录上次的值"""
        # 先获取当前的credit值
        current_user = self.get_user(username)
        if not current_user:
            # 用户不存在，创建新用户
            user = User(username=username, credit=credit, last_credit=0)
            return self.upsert_user(user)
        
        # 更新时自动记录上次的credit
        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__}
                SET last_credit = credit,  -- 将当前credit保存到last_credit
                    credit = ?,
                    updated_at = strftime('%s','now')
                WHERE username = ?
            """, (credit, username))
            return conn.total_changes > 0

    def update_credit_with_manual_last(self, username: str, credit: int, last_credit: int) -> bool:
        """手动指定上次SP币的更新方法"""
        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__}
                SET credit = ?,
                    last_credit = ?,
                    updated_at = strftime('%s','now')
                WHERE username = ?
            """, (credit, last_credit, username))
            return conn.total_changes > 0

    def get_credit_history(self, username: str) -> Optional[Dict[str, int]]:
        """获取用户的SP币历史（当前和上次）"""
        user = self.get_user(username)
        if user:
            return {
                "current": user.credit,
                "last": user.last_credit,
                "change": user.get_credit_change()
            }
        return None
    
    # ====================
    # 日常
    # ====================

    def update_daily_done(self, username: str, next_time: str) -> bool:
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__}
                SET last_daily_time = ?,
                    next_daily_time = ?,
                    daily_count = daily_count + 1,
                    updated_at = strftime('%s','now')
                WHERE username = ?
            """, (now, next_time, username))
            return conn.total_changes > 0

    # ====================
    # 周常
    # ====================

    def update_weekly_done(self, username: str, next_time: str) -> bool:
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__}
                SET last_weekly_time = ?,
                    next_weekly_time = ?,
                    weekly_count = weekly_count + 1,
                    updated_at = strftime('%s','now')
                WHERE username = ?
            """, (now, next_time, username))
            return conn.total_changes > 0

    # ====================
    # 邮件
    # ====================

    def update_mail_time(self, username: str) -> bool:
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute(f"""
                UPDATE {self.__tablename__}
                SET last_mail_time = ?,
                    updated_at = strftime('%s','now')
                WHERE username = ?
            """, (now, username))
            return conn.total_changes > 0

    # ====================
    # 查询
    # ====================

    def get_users_need_daily(self) -> List[User]:
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__}
                WHERE next_daily_time = ''
                   OR next_daily_time <= ?
            """, (now,)).fetchall()

            return [User.from_dict(self._row_to_dict(r)) for r in rows]

    def get_users_need_weekly(self) -> List[User]:
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__}
                WHERE next_weekly_time = ''
                   OR next_weekly_time <= ?
            """, (now,)).fetchall()

            return [User.from_dict(self._row_to_dict(r)) for r in rows]
        
    def get_users_with_credit_change(self) -> List[User]:
        """获取SP币发生变化的用户"""
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM {self.__tablename__}
                WHERE credit != last_credit
            """).fetchall()
            return [User.from_dict(self._row_to_dict(r)) for r in rows]


# ====================
# 单例
# ====================

_table = None

def get_table() -> Table:
    global _table
    if _table is None:
        _table = Table()
    return _table


# ====================
# 便捷函数
# ====================

def get_user(username: str) -> Optional[User]:
    return get_table().get_user(username)


def save_user(user: User) -> bool:
    return get_table().upsert_user(user)


def update_credit(username: str, credit: int) -> bool:
    return get_table().update_credit(username, credit)

def update_credit_with_manual_last(username: str, credit: int, last_credit: int) -> bool:
    return get_table().update_credit_with_manual_last(username, credit, last_credit)

def update_daily(username: str, next_time: str) -> bool:
    return get_table().update_daily_done(username, next_time)


def update_weekly(username: str, next_time: str) -> bool:
    return get_table().update_weekly_done(username, next_time)


def update_mail(username: str) -> bool:
    return get_table().update_mail_time(username)