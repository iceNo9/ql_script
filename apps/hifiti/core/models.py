# apps/hifiti/core/models.py

"""
Hifiti 数据库实体定义。

定义所有与 Hifiti 相关的数据表。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from utils.database import Base


class Account(Base):
    """
    Hifiti 账号表。

    存储账号基础信息、加密密码、加密 Cookie 以及签到状态。
    """

    __tablename__ = "hifiti_accounts"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    username: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    # 加密后的 passwd
    passwd: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 加密后的 Cookie
    cookies: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 金币（Hifiti 积分称为金币）
    gold: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # 签到相关
    last_checkin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    streak_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # 状态
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )

    is_valid: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )

    error_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, username={self.username})>"


class CheckinLog(Base):
    """
    Hifiti 签到日志表。

    记录每次签到的结果、签到时间、排名以及获得的金币。
    """

    __tablename__ = "hifiti_checkin_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hifiti_accounts.id"),
        nullable=False,
        index=True,
    )

    success: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    # 签到获得的金币
    checkin_gold: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # 签到排名
    checkin_rank: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 签到时间：年月日时分秒，统一 UTC（实际签到发生的时间）
    checkin_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # 日志创建时间：年月日时分秒，统一 UTC（记录写入数据库的时间）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<CheckinLog("
            f"id={self.id}, "
            f"account_id={self.account_id}, "
            f"success={self.success}, "
            f"checkin_gold={self.checkin_gold}, "
            f"checkin_rank={self.checkin_rank}"
            f")>"
        )


__all__ = [
    "Account",
    "CheckinLog",
]
