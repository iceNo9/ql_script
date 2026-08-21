# apps/hifiti/core/repositories.py

"""
Hifiti 数据访问层。

提供对 Hifiti 各业务表的 CRUD 操作。

职责：
- 提供 Hifiti 数据库表的 Repository。
- 负责账号密码和 Cookie 的加解密。
- 提供 Hifiti 数据库表初始化函数。

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

from apps.hifiti.core.models import Account, CheckinLog
from utils.crypto import Crypto
from utils.database import Base, get_engine
from utils.log import get_logger
from utils.paths import logs
from utils.timezone import now_utc

logger = get_logger(
    name="hifiti_repositories",
    log_dir=logs(),
    fmt_type="detailed",
)


# ============================================================================
# 数据库初始化
# ============================================================================


def init_database() -> None:
    """
    初始化 Hifiti 数据库表。

    如果表不存在则创建，已经存在的表不会修改。
    """
    engine = get_engine()

    logger.info("检查 Hifiti 数据库表...")

    Base.metadata.create_all(
        bind=engine,
        tables=[
            Account.__table__,
            CheckinLog.__table__,
        ],
    )

    logger.info("Hifiti 数据库表初始化完成")


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

    def _encrypt(self, plaintext: str | None) -> str | None:
        """加密文本。"""
        return self.crypto.encrypt(plaintext) if plaintext is not None else None

    def _decrypt(self, ciphertext: str | None) -> str | None:
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
        passwd: str | None = None,
        cookies: str | None = None,
        **kwargs,
    ) -> Account:
        """
        创建账号。

        密码和 Cookie 在写入数据库之前加密。
        """
        encrypted_passwd = self.crypto.encrypt(passwd) if passwd is not None else None
        encrypted_cookies = (
            self.crypto.encrypt(cookies) if cookies is not None else None
        )

        account = Account(
            username=username,
            passwd=encrypted_passwd,
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

    def update_passwd(
        self,
        account: Account,
        passwd: str | None,
    ) -> Account:
        """
        更新账号密码。

        密码写入数据库前自动加密。
        """
        account.passwd = self._encrypt(passwd)
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

    def update_gold(
        self,
        account: Account,
        gold: int,
    ) -> Account:
        """
        更新账号金币。
        """
        account.gold = gold
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
            active_only: 仅获取活跃账号 (is_active=True)
            valid_only: 仅获取有效账号 (is_valid=True)

        Returns:
            字典，key 为 username，value 为 Account 对象
        """
        stmt = select(Account)

        if active_only:
            stmt = stmt.where(Account.is_active.is_(True))

        if valid_only:
            stmt = stmt.where(Account.is_valid.is_(True))

        stmt = stmt.order_by(Account.id)

        accounts = self.session.execute(stmt).scalars().all()

        # 转换为字典，username 作为 key
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

    def get_passwd(self, account: Account) -> str | None:
        """
        获取账号密码明文。

        数据库中保存的是加密后的密码。
        """
        return self._decrypt(account.passwd)

    def get_cookies(self, account: Account) -> str | None:
        """
        获取账号 Cookie 明文。

        数据库中保存的是加密后的 Cookie。
        """
        return self._decrypt(account.cookies)


# ============================================================================
# CheckinLog Repository
# ============================================================================


class CheckinLogRepository:
    """签到日志 Repository - 提供纯粹的 CRUD 操作。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    def create(
        self,
        account_id: int,
        success: bool,
        checkin_gold: int = 0,
        checkin_rank: int = 0,
        message: str | None = None,
        checkin_at: datetime | None = None,
    ) -> CheckinLog:
        """创建签到日志。"""
        log = CheckinLog(
            account_id=account_id,
            success=success,
            checkin_gold=checkin_gold,
            checkin_rank=checkin_rank,
            message=message,
            checkin_at=checkin_at or now_utc(),
        )

        self.session.add(log)
        self.session.flush()

        logger.debug(
            "📝 记录签到日志: account_id=%s, success=%s, gold=%s, rank=%s",
            account_id,
            success,
            checkin_gold,
            checkin_rank,
        )

        return log

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    def delete_by_id(
        self,
        log_id: int,
    ) -> bool:
        """根据 ID 删除签到日志。"""
        log = self.get_by_id(log_id)

        if not log:
            return False

        self.session.delete(log)
        self.session.flush()

        logger.debug("🗑️ 删除签到日志: id=%s", log_id)
        return True

    def delete_by_account_id(
        self,
        account_id: int,
    ) -> int:
        """删除账号的所有签到日志，返回删除数量。"""
        result = (
            self.session.execute(
                select(CheckinLog).where(CheckinLog.account_id == account_id)
            )
            .scalars()
            .all()
        )

        count = len(result)
        for log in result:
            self.session.delete(log)

        self.session.flush()

        logger.debug("🗑️ 删除账号 %s 的 %d 条签到日志", account_id, count)
        return count

    # ------------------------------------------------------------------------
    # Read (Query)
    # ------------------------------------------------------------------------

    def get_by_id(
        self,
        log_id: int,
    ) -> CheckinLog | None:
        """根据 ID 获取签到日志。"""
        return self.session.get(CheckinLog, log_id)

    def get_by_account_id(
        self,
        account_id: int,
        limit: int = 100,
        offset: int = 0,
        success_only: bool = False,
    ) -> list[CheckinLog]:
        """
        获取账号的签到日志。

        Args:
            account_id: 账号 ID
            limit: 返回数量限制
            offset: 偏移量（用于分页）
            success_only: 仅返回成功的日志
        """
        stmt = select(CheckinLog).where(CheckinLog.account_id == account_id)

        if success_only:
            stmt = stmt.where(CheckinLog.success.is_(True))

        stmt = stmt.order_by(desc(CheckinLog.checkin_at)).offset(offset).limit(limit)

        return self.session.execute(stmt).scalars().all()

    def get_latest_by_account_id(
        self,
        account_id: int,
    ) -> CheckinLog | None:
        """获取账号最新的签到日志。"""
        return self.session.execute(
            select(CheckinLog)
            .where(CheckinLog.account_id == account_id)
            .order_by(desc(CheckinLog.checkin_at))
            .limit(1)
        ).scalar_one_or_none()


__all__ = [
    "AccountRepository",
    "CheckinLogRepository",
    "init_database",
]
