"""
GLaDOS 数据访问层。

提供对 GLaDOS 各业务表的 CRUD 操作。

职责：
- 提供 GLaDOS 数据库表的 Repository。
- 负责账号 Cookie 的加解密。
- 提供 GLaDOS 数据库表初始化函数。

不负责：
- 数据库连接管理
- Session 管理
- 事务管理
- 数据库迁移
"""

from datetime import UTC, datetime, timedelta
from functools import wraps

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.glados.core.entities import Account, CheckinLog, TrafficHistory
from utils.crypto import Crypto
from utils.database import Base, get_engine
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="glados_repositories",
    log_dir=logs(),
    fmt_type="detailed",
)


# ============================================================================
# 数据库初始化
# ============================================================================


def init_database() -> None:
    """
    初始化 GLaDOS 数据库表。

    如果表不存在则创建，已经存在的表不会修改。
    """
    engine = get_engine()

    logger.info("检查 GLaDOS 数据库表...")

    Base.metadata.create_all(
        bind=engine,
        tables=[
            Account.__table__,
            CheckinLog.__table__,
            TrafficHistory.__table__,
        ],
    )

    logger.info("GLaDOS 数据库表初始化完成")


# ============================================================================
# Repository 基类
# ============================================================================


class BaseRepository:
    """Repository 基类。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def transactional(func):
        """
        装饰器：自动提交事务。

        被装饰的方法执行后自动调用 session.commit()。
        如果方法抛出异常，自动调用 session.rollback()。
        """

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                result = func(self, *args, **kwargs)
                self.session.commit()
                return result
            except Exception:
                self.session.rollback()
                raise

        return wrapper


# ============================================================================
# Account Repository
# ============================================================================


class AccountRepository(BaseRepository):
    """账号 Repository。"""

    def __init__(
        self,
        session: Session,
        crypto: Crypto,
    ) -> None:
        super().__init__(session)

        self.crypto = crypto

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    @BaseRepository.transactional
    def create(
        self,
        email: str,
        cookies: str | None = None,
        **kwargs,
    ) -> Account:
        """
        创建账号。

        Cookie 在写入数据库之前加密。
        """
        encrypted_cookie = self.crypto.encrypt(cookies) if cookies is not None else None

        account = Account(
            email=email,
            cookies=encrypted_cookie,
            **kwargs,
        )

        self.session.add(account)
        self.session.flush()

        logger.info("📝 创建账号: %s", email)

        return account

    # ------------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        account_id: int,
    ) -> Account | None:
        """根据 ID 获取账号。"""
        return self.session.get(Account, account_id)

    def get_by_email(
        self,
        email: str,
    ) -> Account | None:
        """根据邮箱获取账号。"""
        return self.session.execute(
            select(Account).where(Account.email == email)
        ).scalar_one_or_none()

    def get_active_accounts(self) -> list[Account]:
        """获取所有活跃且有效的账号。"""
        return (
            self.session.execute(
                select(Account)
                .where(Account.is_active.is_(True))
                .where(Account.is_valid.is_(True))
                .order_by(Account.id)
            )
            .scalars()
            .all()
        )

    def get_accounts_need_checkin(
        self,
        hours: int = 24,
    ) -> list[Account]:
        """
        获取需要签到的账号。

        Args:
            hours:
                超过指定小时未签到。
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        return (
            self.session.execute(
                select(Account)
                .where(Account.is_active.is_(True))
                .where(Account.is_valid.is_(True))
                .where(
                    (Account.last_checkin_at.is_(None))
                    | (Account.last_checkin_at < cutoff)
                )
                .order_by(Account.last_checkin_at.asc().nulls_first())
            )
            .scalars()
            .all()
        )

    # ------------------------------------------------------------------------
    # Cookie
    # ------------------------------------------------------------------------

    def get_cookie(
        self,
        account: Account,
    ) -> str | None:
        """
        获取账号 Cookie 明文。

        数据库中保存的是加密后的 Cookie。
        """
        if not account.cookies:
            return None

        return self.crypto.decrypt(account.cookies)

    @BaseRepository.transactional
    def update_cookie(
        self,
        account: Account,
        cookies: str | None,
    ) -> Account:
        """
        更新账号 Cookie。

        Cookie 写入数据库前自动加密。
        """
        account.cookies = self.crypto.encrypt(cookies) if cookies is not None else None

        self.session.flush()

        return account

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    @BaseRepository.transactional
    def update(
        self,
        account: Account,
    ) -> Account:
        """
        更新账号。

        调用方应先修改 ORM 对象，
        本方法只负责 flush。
        """
        self.session.flush()

        return account

    @BaseRepository.transactional
    def update_checkin_result(
        self,
        account_id: int,
        success: bool,
        message: str | None = None,
        error: str | None = None,
    ) -> Account | None:
        """更新账号签到结果。"""
        account = self.get_by_id(account_id)

        if not account:
            return None

        # 应用层统一使用 UTC
        account.last_checkin_at = datetime.now(UTC)

        if success:
            account.checkin_days += 1
            account.total_days += 1
            account.error_count = 0
            account.last_error = None

            logger.debug(
                "✅ 账号 %s 签到成功",
                account.email,
            )

        else:
            account.error_count += 1
            account.last_error = error or message

            logger.warning(
                "❌ 账号 %s 签到失败: %s",
                account.email,
                error or message,
            )

        # 连续/累计错误次数过多，标记账号无效
        if account.error_count >= 5:
            account.is_valid = False

            logger.warning(
                "⚠️ 账号 %s 错误次数过多，已标记为无效",
                account.email,
            )

        self.session.flush()

        return account

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    @BaseRepository.transactional
    def delete(
        self,
        account_id: int,
    ) -> bool:
        """
        删除账号。

        实际执行软删除。
        """
        account = self.get_by_id(account_id)

        if not account:
            return False

        account.is_active = False

        self.session.flush()

        logger.info(
            "🗑️ 软删除账号: %s",
            account.email,
        )

        return True

    @BaseRepository.transactional
    def hard_delete(
        self,
        account_id: int,
    ) -> bool:
        """硬删除账号。"""
        account = self.get_by_id(account_id)

        if not account:
            return False

        email = account.email

        self.session.delete(account)
        self.session.flush()

        logger.info(
            "🗑️ 硬删除账号: %s",
            email,
        )

        return True


# ============================================================================
# CheckinLog Repository
# ============================================================================


class CheckinLogRepository(BaseRepository):
    """签到日志 Repository。"""

    @BaseRepository.transactional
    def create(
        self,
        account_id: int,
        success: bool,
        message: str | None = None,
    ) -> CheckinLog:
        """创建签到日志。"""
        log = CheckinLog(
            account_id=account_id,
            success=success,
            message=message,
        )

        self.session.add(log)
        self.session.flush()

        logger.debug(
            "📝 记录签到日志: account_id=%s, success=%s",
            account_id,
            success,
        )

        return log

    def get_by_account_id(
        self,
        account_id: int,
        limit: int = 100,
    ) -> list[CheckinLog]:
        """获取账号的签到日志。"""
        return (
            self.session.execute(
                select(CheckinLog)
                .where(CheckinLog.account_id == account_id)
                .order_by(desc(CheckinLog.checkin_at))
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_today_logs(self) -> list[CheckinLog]:
        """获取今日签到日志。"""
        now = datetime.now(UTC)

        today = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        tomorrow = today + timedelta(days=1)

        return (
            self.session.execute(
                select(CheckinLog)
                .where(
                    CheckinLog.checkin_at >= today,
                    CheckinLog.checkin_at < tomorrow,
                )
                .order_by(desc(CheckinLog.checkin_at))
            )
            .scalars()
            .all()
        )

    def get_success_count_today(
        self,
        account_id: int,
    ) -> int:
        """获取账号今日签到成功次数。"""
        now = datetime.now(UTC)

        today = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        tomorrow = today + timedelta(days=1)

        return (
            self.session.execute(
                select(func.count())
                .select_from(CheckinLog)
                .where(
                    CheckinLog.account_id == account_id,
                    CheckinLog.checkin_at >= today,
                    CheckinLog.checkin_at < tomorrow,
                    CheckinLog.success.is_(True),
                )
            ).scalar()
            or 0
        )

    def get_stats_by_account(
        self,
        account_id: int,
    ) -> dict[str, int | float]:
        """获取账号签到统计。"""
        total = (
            self.session.execute(
                select(func.count())
                .select_from(CheckinLog)
                .where(CheckinLog.account_id == account_id)
            ).scalar()
            or 0
        )

        success = (
            self.session.execute(
                select(func.count())
                .select_from(CheckinLog)
                .where(
                    CheckinLog.account_id == account_id,
                    CheckinLog.success.is_(True),
                )
            ).scalar()
            or 0
        )

        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate": success / total if total else 0,
        }


# ============================================================================
# TrafficHistory Repository
# ============================================================================


class TrafficHistoryRepository(BaseRepository):
    """流量历史 Repository。"""

    @BaseRepository.transactional
    def create(
        self,
        account_id: int,
        used_traffic: float,
        total_traffic: float,
        remaining_traffic: float,
    ) -> TrafficHistory:
        """创建流量历史记录。"""
        record = TrafficHistory(
            account_id=account_id,
            used_traffic=used_traffic,
            total_traffic=total_traffic,
            remaining_traffic=remaining_traffic,
        )

        self.session.add(record)
        self.session.flush()

        logger.debug(
            "📝 记录流量: account_id=%s, used=%sGB",
            account_id,
            used_traffic,
        )

        return record

    def get_by_account_id(
        self,
        account_id: int,
        limit: int = 30,
    ) -> list[TrafficHistory]:
        """获取账号的流量历史。"""
        return (
            self.session.execute(
                select(TrafficHistory)
                .where(TrafficHistory.account_id == account_id)
                .order_by(desc(TrafficHistory.recorded_at))
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_latest_by_account_id(
        self,
        account_id: int,
    ) -> TrafficHistory | None:
        """获取账号最新的流量记录。"""
        return self.session.execute(
            select(TrafficHistory)
            .where(TrafficHistory.account_id == account_id)
            .order_by(desc(TrafficHistory.recorded_at))
            .limit(1)
        ).scalar_one_or_none()

    def get_traffic_trend(
        self,
        account_id: int,
        days: int = 7,
    ) -> list[dict[str, str | float]]:
        """获取账号流量趋势。"""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        records = (
            self.session.execute(
                select(TrafficHistory)
                .where(
                    TrafficHistory.account_id == account_id,
                    TrafficHistory.recorded_at >= cutoff,
                )
                .order_by(TrafficHistory.recorded_at)
            )
            .scalars()
            .all()
        )

        return [
            {
                "date": record.recorded_at.strftime("%Y-%m-%d"),
                "used": record.used_traffic,
                "total": record.total_traffic,
                "remaining": record.remaining_traffic,
            }
            for record in records
        ]


__all__ = [
    "AccountRepository",
    "CheckinLogRepository",
    "TrafficHistoryRepository",
    "init_database",
]
