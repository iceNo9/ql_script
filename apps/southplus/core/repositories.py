# apps/southplus/core/repositories.py

"""
SouthPlus 数据访问层。

提供对 SouthPlus 各业务表的 CRUD 操作。

职责：
- 提供 SouthPlus 数据库表的 Repository。
- 负责账号 Cookie 的加解密。
- 提供 SouthPlus 数据库表初始化函数。

不负责：
- 数据库连接管理
- Session 管理
- 事务管理
- 数据库迁移
- 业务逻辑计算
"""

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.southplus.core.models import (
    Account,
    DailyCompleteLog,
    NotificationLog,
    WeeklyCompleteLog,
)
from utils.crypto import Crypto
from utils.database import Base, get_engine
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_utc

logger = get_logger(
    name="southplus_repositories",
    log_dir=logs(),
    fmt_type="detailed",
)


# ============================================================================
# 数据库初始化
# ============================================================================


def init_database() -> None:
    """
    初始化 SouthPlus 数据库表。

    如果表不存在则创建，已经存在的表不会修改。
    """
    engine = get_engine()

    logger.info("检查 SouthPlus 数据库表...")

    Base.metadata.create_all(
        bind=engine,
        tables=[
            Account.__table__,
            DailyCompleteLog.__table__,
            NotificationLog.__table__,
            WeeklyCompleteLog.__table__,
        ],
    )

    logger.info("SouthPlus 数据库表初始化完成")


# ============================================================================
# Account Repository
# ============================================================================


class AccountRepository:
    """账号 Repository - 提供纯粹的 CRUD 操作。"""

    def __init__(
        self,
        session: Session,
        crypto: Crypto,
    ) -> None:
        self.session = session
        self.crypto = crypto

    # ========================================================================
    # 加密辅助方法（私有）
    # ========================================================================

    def _encrypt(
        self,
        plaintext: str | None,
    ) -> str | None:
        """加密文本。"""
        return self.crypto.encrypt(plaintext) if plaintext is not None else None

    def _decrypt(
        self,
        ciphertext: str | None,
    ) -> str | None:
        """解密文本。"""
        if not ciphertext:
            return None

        return self.crypto.decrypt(ciphertext)

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    def create(
        self,
        username: str,
        cookies: str | None = None,
        **kwargs,
    ) -> Account:
        """
        创建账号。

        Cookie 在写入数据库之前加密。
        """
        encrypted_cookies = self._encrypt(cookies)

        account = Account(
            username=username,
            cookies=encrypted_cookies,
            **kwargs,
        )

        self.session.add(account)
        self.session.flush()

        logger.info("📝 创建账号: %s", username)

        return account

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    def delete(
        self,
        account_id: int,
    ) -> bool:
        """
        软删除账号。

        将 is_active 设置为 False。
        """
        account = self.get_by_id(account_id)

        if not account:
            return False

        account.is_active = False
        self.session.flush()

        logger.info("🗑️ 软删除账号: %s", account.username)

        return True

    def hard_delete(
        self,
        account_id: int,
    ) -> bool:
        """硬删除账号（从数据库中移除）。"""
        account = self.get_by_id(account_id)

        if not account:
            return False

        username = account.username

        self.session.delete(account)
        self.session.flush()

        logger.info("🗑️ 硬删除账号: %s", username)

        return True

    def restore(
        self,
        account_id: int,
    ) -> bool:
        """恢复软删除的账号。"""
        account = self.get_by_id(account_id)

        if not account:
            return False

        account.is_active = True
        self.session.flush()

        logger.info("♻️ 恢复账号: %s", account.username)

        return True

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    def update(
        self,
        account: Account,
    ) -> Account:
        """
        更新账号。

        调用方应先修改 ORM 对象，本方法只负责 flush。
        """
        self.session.flush()

        return account

    def update_cookies(
        self,
        account: Account,
        cookies: str | None,
    ) -> Account:
        """
        更新账号 Cookie。

        Cookie 写入数据库前自动加密。
        """
        account.cookies = self._encrypt(cookies)

        self.session.flush()

        return account

    def update_points_sp(
        self,
        account: Account,
        points_sp: int,
    ) -> Account:
        """
        更新账号当前 SP Point。
        """
        account.points_sp = points_sp

        self.session.flush()

        return account

    # ------------------------------------------------------------------------
    # Read (Query)
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        account_id: int,
    ) -> Account | None:
        """根据 ID 获取账号。"""
        return self.session.get(Account, account_id)

    def get_by_username(
        self,
        username: str,
    ) -> Account | None:
        """根据用户名获取账号。"""
        return self.session.execute(
            select(Account).where(Account.username == username)
        ).scalar_one_or_none()

    def get_all(
        self,
        active_only: bool = False,
        valid_only: bool = False,
    ) -> dict[str, Account]:
        """
        获取所有账号，返回以用户名为键的字典。

        Args:
            active_only: 仅获取活跃账号。
            valid_only: 仅获取有效账号。

        Returns:
            字典，key 为 username，value 为 Account 对象。
        """
        stmt = select(Account)

        if active_only:
            stmt = stmt.where(Account.is_active.is_(True))

        if valid_only:
            stmt = stmt.where(Account.is_valid.is_(True))

        stmt = stmt.order_by(Account.id)

        accounts = self.session.execute(stmt).scalars().all()

        return {account.username: account for account in accounts}

    def count(
        self,
        active_only: bool = False,
        valid_only: bool = False,
    ) -> int:
        """统计账号数量。"""
        stmt = select(func.count()).select_from(Account)

        if active_only:
            stmt = stmt.where(Account.is_active.is_(True))

        if valid_only:
            stmt = stmt.where(Account.is_valid.is_(True))

        return self.session.execute(stmt).scalar() or 0

    def get_cookies(
        self,
        account: Account,
    ) -> str | None:
        """
        获取账号 Cookie 明文。

        数据库中保存的是加密后的 Cookie。
        """
        return self._decrypt(account.cookies)


# ============================================================================
# DailyCompleteLog Repository
# ============================================================================


class DailyCompleteLogRepository:
    """日常任务完成日志 Repository - 提供纯粹的 CRUD 操作。"""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    def create(
        self,
        account_id: int,
        success: bool,
        delta_points_sp: int = 0,
        message: str | None = None,
        complete_at: datetime | None = None,
    ) -> DailyCompleteLog:
        """创建日常任务完成日志。"""
        log = DailyCompleteLog(
            account_id=account_id,
            success=success,
            delta_points_sp=delta_points_sp,
            message=message,
            complete_at=complete_at or now_utc(),
        )

        self.session.add(log)
        self.session.flush()

        logger.debug(
            "📝 记录日常完成日志: " "account_id=%s, success=%s, delta_points_sp=%s",
            account_id,
            success,
            delta_points_sp,
        )

        return log

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    def delete_by_id(
        self,
        log_id: int,
    ) -> bool:
        """根据 ID 删除日常完成日志。"""
        log = self.get_by_id(log_id)

        if not log:
            return False

        self.session.delete(log)
        self.session.flush()

        logger.debug("🗑️ 删除日常完成日志: id=%s", log_id)

        return True

    def delete_by_account_id(
        self,
        account_id: int,
    ) -> int:
        """删除账号的所有日常完成日志，返回删除数量。"""
        logs = (
            self.session.execute(
                select(DailyCompleteLog).where(
                    DailyCompleteLog.account_id == account_id
                )
            )
            .scalars()
            .all()
        )

        count = len(logs)

        for log in logs:
            self.session.delete(log)

        self.session.flush()

        logger.debug(
            "🗑️ 删除账号 %s 的 %d 条日常完成日志",
            account_id,
            count,
        )

        return count

    # ------------------------------------------------------------------------
    # Read (Query)
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        log_id: int,
    ) -> DailyCompleteLog | None:
        """根据 ID 获取日常完成日志。"""
        return self.session.get(
            DailyCompleteLog,
            log_id,
        )

    def get_by_account_id(
        self,
        account_id: int,
        limit: int = 100,
        offset: int = 0,
        success_only: bool = False,
    ) -> list[DailyCompleteLog]:
        """
        获取账号的日常完成日志。

        Args:
            account_id: 账号 ID
            limit: 返回数量限制
            offset: 偏移量
            success_only: 仅返回成功日志。
        """
        stmt = select(DailyCompleteLog).where(DailyCompleteLog.account_id == account_id)

        if success_only:
            stmt = stmt.where(DailyCompleteLog.success.is_(True))

        stmt = (
            stmt.order_by(desc(DailyCompleteLog.complete_at))
            .offset(offset)
            .limit(limit)
        )

        return self.session.execute(stmt).scalars().all()

    def get_latest_by_account_id(
        self,
        account_id: int,
    ) -> DailyCompleteLog | None:
        """获取账号最新的日常完成日志。"""
        return self.session.execute(
            select(DailyCompleteLog)
            .where(DailyCompleteLog.account_id == account_id)
            .order_by(desc(DailyCompleteLog.complete_at))
            .limit(1)
        ).scalar_one_or_none()


# ============================================================================
# WeeklyCompleteLog Repository
# ============================================================================


class WeeklyCompleteLogRepository:
    """周常任务完成日志 Repository - 提供纯粹的 CRUD 操作。"""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    def create(
        self,
        account_id: int,
        success: bool,
        delta_points_sp: int = 0,
        message: str | None = None,
        complete_at: datetime | None = None,
    ) -> WeeklyCompleteLog:
        """创建周常任务完成日志。"""
        log = WeeklyCompleteLog(
            account_id=account_id,
            success=success,
            delta_points_sp=delta_points_sp,
            message=message,
            complete_at=complete_at or now_utc(),
        )

        self.session.add(log)
        self.session.flush()

        logger.debug(
            "📝 记录周常完成日志: " "account_id=%s, success=%s, delta_points_sp=%s",
            account_id,
            success,
            delta_points_sp,
        )

        return log

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    def delete_by_id(
        self,
        log_id: int,
    ) -> bool:
        """根据 ID 删除周常完成日志。"""
        log = self.get_by_id(log_id)

        if not log:
            return False

        self.session.delete(log)
        self.session.flush()

        logger.debug("🗑️ 删除周常完成日志: id=%s", log_id)

        return True

    def delete_by_account_id(
        self,
        account_id: int,
    ) -> int:
        """删除账号的所有周常完成日志，返回删除数量。"""
        logs = (
            self.session.execute(
                select(WeeklyCompleteLog).where(
                    WeeklyCompleteLog.account_id == account_id
                )
            )
            .scalars()
            .all()
        )

        count = len(logs)

        for log in logs:
            self.session.delete(log)

        self.session.flush()

        logger.debug(
            "🗑️ 删除账号 %s 的 %d 条周常完成日志",
            account_id,
            count,
        )

        return count

    # ------------------------------------------------------------------------
    # Read (Query)
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        log_id: int,
    ) -> WeeklyCompleteLog | None:
        """根据 ID 获取周常完成日志。"""
        return self.session.get(
            WeeklyCompleteLog,
            log_id,
        )

    def get_by_account_id(
        self,
        account_id: int,
        limit: int = 100,
        offset: int = 0,
        success_only: bool = False,
    ) -> list[WeeklyCompleteLog]:
        """
        获取账号的周常完成日志。

        Args:
            account_id: 账号 ID
            limit: 返回数量限制
            offset: 偏移量
            success_only: 仅返回成功日志。
        """
        stmt = select(WeeklyCompleteLog).where(
            WeeklyCompleteLog.account_id == account_id
        )

        if success_only:
            stmt = stmt.where(WeeklyCompleteLog.success.is_(True))

        stmt = (
            stmt.order_by(desc(WeeklyCompleteLog.complete_at))
            .offset(offset)
            .limit(limit)
        )

        return self.session.execute(stmt).scalars().all()

    def get_latest_by_account_id(
        self,
        account_id: int,
    ) -> WeeklyCompleteLog | None:
        """获取账号最新的周常完成日志。"""
        return self.session.execute(
            select(WeeklyCompleteLog)
            .where(WeeklyCompleteLog.account_id == account_id)
            .order_by(desc(WeeklyCompleteLog.complete_at))
            .limit(1)
        ).scalar_one_or_none()


class NotificationLogRepository:
    """
    通知日志 Repository - 提供纯粹的 CRUD 操作。

    仅负责通知发送日志的数据访问，
    不负责通知频率判断等业务逻辑。
    """

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    def create(
        self,
        success: bool,
        message: str | None = None,
        sent_at: datetime | None = None,
    ) -> NotificationLog:
        """
        创建通知发送日志。
        """

        log = NotificationLog(
            success=success,
            message=message,
            sent_at=sent_at or now_utc(),
        )

        self.session.add(log)
        self.session.flush()

        logger.debug(
            "📝 记录通知发送日志: " "success=%s, message=%s, sent_at=%s",
            success,
            message,
            log.sent_at,
        )

        return log

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    def delete_by_id(
        self,
        log_id: int,
    ) -> bool:
        """根据 ID 删除通知发送日志。"""

        log = self.get_by_id(log_id)

        if not log:
            return False

        self.session.delete(log)
        self.session.flush()

        logger.debug(
            "🗑️ 删除通知发送日志: id=%s",
            log_id,
        )

        return True

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    def update(
        self,
        log: NotificationLog,
    ) -> NotificationLog:
        """
        更新通知发送日志。

        调用方应先修改 ORM 对象，
        本方法只负责 flush。
        """

        self.session.flush()

        return log

    # ------------------------------------------------------------------------
    # Read (Query)
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        log_id: int,
    ) -> NotificationLog | None:
        """根据 ID 获取通知发送日志。"""

        return self.session.get(
            NotificationLog,
            log_id,
        )

    def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NotificationLog]:
        """
        获取通知发送日志。

        Args:
            limit: 返回数量限制。
            offset: 偏移量。
        """

        stmt = (
            select(NotificationLog)
            .order_by(desc(NotificationLog.sent_at))
            .offset(offset)
            .limit(limit)
        )

        return self.session.execute(stmt).scalars().all()

    def get_latest(self) -> NotificationLog | None:
        """获取最新的通知发送日志。"""

        return self.session.execute(
            select(NotificationLog).order_by(desc(NotificationLog.sent_at)).limit(1)
        ).scalar_one_or_none()

    def count(self) -> int:
        """统计通知发送日志数量。"""

        stmt = select(func.count()).select_from(NotificationLog)

        return self.session.execute(stmt).scalar() or 0


__all__ = [
    "AccountRepository",
    "DailyCompleteLogRepository",
    "NotificationLogRepository",
    "WeeklyCompleteLogRepository",
    "init_database",
]
