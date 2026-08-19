"""
数据库模块

负责：

- 创建 SQLAlchemy Engine
- 管理 PostgreSQL 数据库连接池
- 提供数据库 Session
- 提供统一的事务管理
- 提供 SQLAlchemy Declarative Base
- 提供数据库连接测试
- 提供数据库资源关闭

不负责：

- 定义具体业务数据表
- 定义应用 Model
- 定义 Repository
- 实现具体业务 CRUD

数据库配置来源：

    config/global.yaml

例如：

    database:
      host: localhost
      port: 5432
      database: qinglong
      username: postgres
      password: password
"""

from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from utils.config import DatabaseConfig, load_global_config
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(name="database", log_dir=logs(), fmt_type="detailed")


# ============================================================================
# SQLAlchemy Base
# ============================================================================


class Base(DeclarativeBase):
    """
    所有应用数据库 Model 的基类。

    应用自己的 Model 应该继承这个 Base。

    例如：

        class User(Base):
            ...
    """


# ============================================================================
# Database
# ============================================================================


class Database:
    """
    数据库管理器。

    负责管理 SQLAlchemy Engine 和 Session 工厂。

    注意：

    Database 本身不需要作为单例使用。

    SQLAlchemy Engine 本身包含连接池，因此整个应用通常只需要
    一个 Engine。

    Session 则应该按使用范围创建，不能在线程之间共享。
    """

    def __init__(
        self,
        config: DatabaseConfig | None = None,
    ) -> None:
        """
        初始化数据库管理器。

        Args:
            config:
                PostgreSQL 配置。
                如果不传，则从全局配置加载。
        """
        self.config = config or load_global_config().database

        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        self._lock = Lock()

    # ------------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------------

    @property
    def engine(self) -> Engine:
        """
        获取 SQLAlchemy Engine。

        Engine 在第一次使用时创建，并在后续重复使用。
        """
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    self._engine = self._create_engine()

        return self._engine

    def _create_engine(self) -> Engine:
        """创建 SQLAlchemy Engine。"""

        url = URL.create(
            drivername="postgresql+psycopg",
            username=self.config.username,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
        )

        logger.debug(
            "创建 PostgreSQL Engine: %s:%s/%s",
            self.config.host,
            self.config.port,
            self.config.database,
        )

        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={
                "options": "-c timezone=UTC",
            },
        )

    # ------------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------------

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """
        获取 Session 工厂。

        Session 工厂本身可以长期复用，
        但每次调用 factory() 都会创建新的 Session。
        """
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autoflush=False,
                expire_on_commit=False,
            )

        return self._session_factory

    def get_session(self) -> Session:
        """
        创建一个新的数据库 Session。

        调用方负责关闭 Session。

        推荐：

            with database.get_session() as session:
                ...
        """
        return self.session_factory()

    # ------------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------------

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        获取带事务管理的 Session。

        正常执行：

            commit()

        出现异常：

            rollback()

        最后：

            close()

        Example:

            with database.session() as session:
                user = User(...)
                session.add(user)
        """
        session = self.get_session()

        try:
            yield session
            session.commit()

        except Exception:
            session.rollback()
            raise

        finally:
            session.close()

    # ------------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------------

    def test_connection(self) -> bool:
        """
        测试 PostgreSQL 数据库连接。

        Returns:
            bool:
                连接成功返回 True，否则返回 False。
        """
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))

            logger.debug("PostgreSQL 数据库连接成功")
            return True

        except Exception:
            logger.exception("PostgreSQL 数据库连接失败")
            return False

    # ------------------------------------------------------------------------
    # Dispose
    # ------------------------------------------------------------------------

    def close(self) -> None:
        """
        关闭数据库连接池。
        """
        if self._engine is not None:
            logger.debug("关闭 PostgreSQL 数据库连接池")

            self._engine.dispose()

            self._engine = None
            self._session_factory = None


# ============================================================================
# 全局 Database
# ============================================================================

_database = Database()


# ============================================================================
# 快捷函数
# ============================================================================


def get_engine() -> Engine:
    """
    获取全局 SQLAlchemy Engine。
    """
    return _database.engine


def get_session() -> Session:
    """
    创建一个新的数据库 Session。

    调用方负责关闭 Session。
    """
    return _database.get_session()


@contextmanager
def session() -> Generator[Session, None, None]:
    """
    获取带事务管理的数据库 Session。

    Example:

        with session() as db:
            ...
    """
    with _database.session() as db:
        yield db


def test_connection() -> bool:
    """
    测试数据库连接。
    """
    return _database.test_connection()


def close() -> None:
    """
    关闭数据库连接池。
    """
    _database.close()


__all__ = [
    "Base",
    "Database",
    "close",
    "get_engine",
    "get_session",
    "session",
    "test_connection",
]
