"""
database.py - 数据库操作基类
提供统一的CRUD操作，各业务模块继承此类
"""
import sqlite3
import json
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
from abc import ABC

from common.global_config import DB_PATH
from common.log import get_logger


class BaseTable(ABC):
    """数据库表基类，所有业务表继承此类"""
    
    # 子类必须定义的属性
    __tablename__: str = None          # 表名
    __table_schema__: str = None       # 建表SQL
    __indexes__: List[str] = []        # 索引SQL列表
    
    def __init__(self):
        """初始化"""
        if not self.__tablename__:
            raise ValueError(f"{self.__class__.__name__} 必须定义 __tablename__")
        if not self.__table_schema__:
            raise ValueError(f"{self.__class__.__name__} 必须定义 __table_schema__")
        
        self.logger = get_logger(f"{self.__tablename__}.db")
        self._init_table()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接（自动管理事务）"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            conn.close()
    
    def _init_table(self):
        """初始化表结构（幂等操作）"""
        with self._get_connection() as conn:
            # 创建表
            conn.execute(self.__table_schema__)
            
            # 创建索引
            for index_sql in self.__indexes__:
                try:
                    conn.execute(index_sql)
                except sqlite3.OperationalError as e:
                    # 索引可能已存在，忽略错误
                    self.logger.debug(f"创建索引时忽略: {e}")
            
            self.logger.info(f"表 {self.__tablename__} 初始化完成")
    
    # ==================== 核心查询接口 ====================
    
    def get(self, username: str) -> Optional[Dict]:
        """
        根据用户名获取单条记录
        返回: dict 或 None
        """
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.__tablename__} WHERE username = ?",
                (username,)
            ).fetchone()
            if row:
                return self._row_to_dict(row)
            return None
    
    def get_all(self, order_by: str = None, limit: int = None) -> List[Dict]:
        """
        获取所有记录
        order_by: 排序字段，如 "remaining_days DESC"
        limit: 限制条数
        """
        with self._get_connection() as conn:
            sql = f"SELECT * FROM {self.__tablename__}"
            params = []
            
            if order_by:
                sql += f" ORDER BY {order_by}"
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    # ==================== 数据操作接口 ====================
    
    def upsert(self, username: str, data: Dict) -> bool:
        """
        插入或更新记录（子类可重写）
        
        Args:
            username: 用户名（主键）
            data: 要更新的数据字典
            
        Returns:
            bool: 操作是否成功
        """
        with self._get_connection() as conn:
            existing = self.get(username)
            
            if existing:
                # 更新：只更新传入的非空字段
                updates = []
                params = []
                
                for key, value in data.items():
                    if key != 'username' and value is not None:
                        updates.append(f"{key} = ?")
                        params.append(self._serialize(value))
                
                if updates:
                    params.append(username)
                    conn.execute(f"""
                        UPDATE {self.__tablename__} 
                        SET {', '.join(updates)}, updated_at = strftime('%s','now')
                        WHERE username = ?
                    """, params)
                    self.logger.debug(f"更新用户: {username}")
            else:
                # 插入
                columns = ['username'] + list(data.keys())
                placeholders = ['?'] * len(columns)
                values = [username] + [self._serialize(data.get(k)) for k in data.keys()]
                
                conn.execute(f"""
                    INSERT INTO {self.__tablename__} 
                    ({', '.join(columns)}, created_at, updated_at)
                    VALUES ({', '.join(placeholders)}, strftime('%s','now'), strftime('%s','now'))
                """, values)
                self.logger.info(f"新增用户: {username}")
            
            return True
    
    def delete(self, username: str) -> bool:
        """删除用户"""
        with self._get_connection() as conn:
            result = conn.execute(
                f"DELETE FROM {self.__tablename__} WHERE username = ?",
                (username,)
            )
            if result.rowcount > 0:
                self.logger.info(f"删除用户: {username}")
                return True
            return False
    
    def exists(self, username: str) -> bool:
        """检查用户是否存在"""
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.__tablename__} WHERE username = ? LIMIT 1",
                (username,)
            ).fetchone()
            return row is not None
    
    def count(self, where_clause: str = None, params: tuple = ()) -> int:
        """统计记录数"""
        with self._get_connection() as conn:
            sql = f"SELECT COUNT(*) as cnt FROM {self.__tablename__}"
            if where_clause:
                sql += f" WHERE {where_clause}"
            
            row = conn.execute(sql, params).fetchone()
            return row['cnt'] if row else 0
    
    # ==================== 辅助方法 ====================
    
    def _serialize(self, value: Any) -> Any:
        """序列化复杂类型（如dict、list）为JSON字符串"""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value
    
    def _deserialize(self, value: Any) -> Any:
        """反序列化JSON字符串"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """将数据库行转换为字典，自动反序列化JSON字段"""
        result = dict(row)
        for key, value in result.items():
            result[key] = self._deserialize(value)
        return result


# ==================== 导出 ====================

__all__ = [
    'BaseTable',
]