"""
modules\glados\core\table.py - GLaDOS 数据库操作模块
包含数据库 DTO 和表操作
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from datetime import datetime

from utils.database import BaseTable


# ==================== 数据库 DTO ====================

@dataclass
class GladosUser:
    """
    GLaDOS 用户数据 DTO
    
    对应数据库 glados 表
    """
    username: str                              # 用户名（主键）
    vip_level: int = 0                         # VIP级别
    points: int = 0                            # 积分
    remaining_days: int = 0                    # 剩余天数
    used_traffic_kb: int = 0                   # 已用流量(KB)
    cookies: Optional[Dict[str, Any]] = None   # Cookies（支持复杂结构）
    last_sign_date: str = ""                   # 最后签到日期

    cookies_valid: bool = True          # cookies 是否有效
    cookies_expire_at: int = 0          # cookies 过期时间戳（可选）
    last_check_at: int = 0              # 最后检查时间
    
    def __post_init__(self):
        """初始化默认值"""
        if self.cookies is None:
            self.cookies = {}
        if not self.last_sign_date:
            self.last_sign_date = datetime.now().strftime("%Y-%m-%d")
    
    # ==================== 便捷属性 ====================
    
    @property
    def is_active(self) -> bool:
        """是否有效用户"""
        return self.remaining_days > 0
    
    @property
    def used_traffic_mb(self) -> float:
        """已用流量(MB)"""
        return round(self.used_traffic_kb / 1024, 2)
    
    @property
    def used_traffic_gb(self) -> float:
        """已用流量(GB)"""
        return round(self.used_traffic_kb / (1024 ** 2), 2)
    
    @property
    def vip_name(self) -> str:
        """VIP等级名称"""
        return {0: "普通", 1: "VIP", 2: "SVIP", 10: "Pro"}.get(self.vip_level, f"Lv{self.vip_level}")
    
    def is_sign_today(self) -> bool:
        """今日是否已签到"""
        return self.last_sign_date == datetime.now().strftime("%Y-%m-%d")
    
    # ==================== 序列化 ====================
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于数据库写入）"""
        return {
            'username': self.username,
            'vip_level': self.vip_level,
            'points': self.points,
            'remaining_days': self.remaining_days,
            'used_traffic_kb': self.used_traffic_kb,
            'cookies': self.cookies,
            'last_sign_date': self.last_sign_date,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosUser":
        """从字典创建实例"""
        return cls(
            username=data['username'],
            vip_level=data.get('vip_level', 0),
            points=data.get('points', 0),
            remaining_days=data.get('remaining_days', 0),
            used_traffic_kb=data.get('used_traffic_kb', 0),
            cookies=data.get('cookies'),
            last_sign_date=data.get('last_sign_date', ''),
        )
    
    # ==================== 显示 ====================
    
    def to_summary(self) -> str:
        """简短摘要"""
        return f"{self.username} | {self.vip_name} | 剩余{self.remaining_days}天 | {self.points}积分"
    
    def __str__(self) -> str:
        return self.to_summary()


# ==================== 数据库表类 ====================

class GladosTable(BaseTable):
    """GLaDOS 用户数据表"""
    
    __tablename__ = "glados"
    
    __table_schema__ = """
        CREATE TABLE IF NOT EXISTS glados (
            username TEXT PRIMARY KEY,
            vip_level INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            remaining_days INTEGER DEFAULT 0,
            used_traffic_kb INTEGER DEFAULT 0,
            cookies TEXT,
            last_sign_date TEXT,
            cookies_valid INTEGER DEFAULT 1,
            cookies_expire_at INTEGER DEFAULT 0,
            last_check_at INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """
    
    __indexes__ = [
        "CREATE INDEX IF NOT EXISTS idx_glados_remaining ON glados(remaining_days)",
        "CREATE INDEX IF NOT EXISTS idx_glados_points ON glados(points)",
    ]


# 全局实例
_table = GladosTable()


# ==================== 对外接口 ====================

def save(user: GladosUser) -> bool:
    """
    保存用户（插入或更新）
    """
    with _table._get_connection() as conn:
        existing = _table.get(user.username)
        data = user.to_dict()
        
        if existing:
            # 更新
            updates = []
            params = []
            for key, value in data.items():
                if key != 'username' and value is not None:
                    updates.append(f"{key} = ?")
                    params.append(_table._serialize(value))
            
            if updates:
                params.append(user.username)
                conn.execute(f"""
                    UPDATE {_table.__tablename__} 
                    SET {', '.join(updates)}, updated_at = strftime('%s','now')
                    WHERE username = ?
                """, params)
                _table.logger.debug(f"更新用户: {user.username}")
        else:
            # 插入
            columns = list(data.keys())
            placeholders = ['?'] * len(columns)
            values = [_table._serialize(data[k]) for k in columns]
            
            conn.execute(f"""
                INSERT INTO {_table.__tablename__} 
                ({', '.join(columns)}, created_at, updated_at)
                VALUES ({', '.join(placeholders)}, strftime('%s','now'), strftime('%s','now'))
            """, values)
            _table.logger.info(f"新增用户: {user.username}")
        
        return True


def get(username: str) -> Optional[GladosUser]:
    """
    获取用户
    """
    data = _table.get(username)
    if not data:
        return None
    
    # 反序列化 cookies
    if data.get('cookies'):
        data['cookies'] = _table._deserialize(data['cookies'])
    
    return GladosUser.from_dict(data)


def get_all(order_by: str = "remaining_days DESC", limit: int = None) -> List[GladosUser]:
    """
    获取所有用户
    """
    rows = _table.get_all(order_by, limit)
    users = []
    for row in rows:
        if row.get('cookies'):
            row['cookies'] = _table._deserialize(row['cookies'])
        users.append(GladosUser.from_dict(row))
    return users


def get_active_users() -> List[GladosUser]:
    """
    获取有效用户（剩余天数 > 0）
    """
    with _table._get_connection() as conn:
        rows = conn.execute(f"""
            SELECT * FROM {_table.__tablename__} 
            WHERE remaining_days > 0 
            ORDER BY remaining_days ASC
        """).fetchall()
        
        users = []
        for row in rows:
            data = dict(row)
            if data.get('cookies'):
                data['cookies'] = _table._deserialize(data['cookies'])
            users.append(GladosUser.from_dict(data))
        return users


def get_expiring_soon(days: int = 7) -> List[GladosUser]:
    """
    获取即将过期的用户（剩余天数 <= days 且 > 0）
    """
    with _table._get_connection() as conn:
        rows = conn.execute(f"""
            SELECT * FROM {_table.__tablename__} 
            WHERE remaining_days > 0 AND remaining_days <= ?
            ORDER BY remaining_days ASC
        """, (days,)).fetchall()
        
        users = []
        for row in rows:
            data = dict(row)
            if data.get('cookies'):
                data['cookies'] = _table._deserialize(data['cookies'])
            users.append(GladosUser.from_dict(data))
        return users


def get_top_points(limit: int = 10) -> List[GladosUser]:
    """
    积分排行榜
    """
    return get_all(order_by="points DESC", limit=limit)


def delete(username: str) -> bool:
    """删除用户"""
    return _table.delete(username)


def exists(username: str) -> bool:
    """检查用户是否存在"""
    return _table.exists(username)


def count(active_only: bool = False) -> int:
    """统计用户数量"""
    if active_only:
        return _table.count("remaining_days > 0")
    return _table.count()


def update_sign(username: str, gained_points: int = 10, new_remaining_days: int = None) -> bool:
    """
    签到更新（便捷方法）
    
    Args:
        username: 用户名
        gained_points: 获得的积分
        new_remaining_days: 新的剩余天数（可选）
    """
    user = get(username)
    if not user:
        return False
    
    # 检查今日是否已签到
    if user.is_sign_today():
        return False
    
    # 更新数据
    user.points += gained_points
    user.last_sign_date = datetime.now().strftime("%Y-%m-%d")
    
    if new_remaining_days is not None:
        user.remaining_days = new_remaining_days
    
    return save(user)


def get_statistics() -> Dict[str, Any]:
    """获取统计信息"""
    with _table._get_connection() as conn:
        stats = conn.execute(f"""
            SELECT 
                COUNT(*) as total_users,
                SUM(CASE WHEN remaining_days > 0 THEN 1 ELSE 0 END) as active_users,
                SUM(CASE WHEN remaining_days <= 0 AND remaining_days != 0 THEN 1 ELSE 0 END) as expired_users,
                AVG(remaining_days) as avg_remaining_days,
                SUM(points) as total_points,
                AVG(points) as avg_points,
                SUM(used_traffic_kb) as total_traffic_kb
            FROM {_table.__tablename__}
        """).fetchone()
        
        if stats:
            result = dict(stats)
            if result.get('total_traffic_kb'):
                result['total_traffic_gb'] = round(result['total_traffic_kb'] / (1024 ** 2), 2)
            return result
        
        return {
            'total_users': 0, 'active_users': 0, 'expired_users': 0,
            'avg_remaining_days': 0, 'total_points': 0, 'avg_points': 0,
            'total_traffic_kb': 0, 'total_traffic_gb': 0
        }


# ==================== 导出接口 ====================

__all__ = [
    # DTO
    'GladosUser',
    # 基础操作
    'save', 'get', 'get_all', 'delete', 'exists', 'count',
    # 查询
    'get_active_users', 'get_expiring_soon', 'get_top_points',
    # 业务操作
    'update_sign', 'get_statistics',
]