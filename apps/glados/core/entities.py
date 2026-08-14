"""
GLaDOS 数据库实体定义。

定义所有与 GLaDOS 相关的数据表。
"""

from datetime import datetime
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from utils.database import Base


class Account(Base):
    """
    GLaDOS 账号表。

    存储账号基础信息、加密 Cookie 以及签到状态。
    """

    __tablename__ = "glados_accounts"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    # 加密后的 Cookie
    cookies: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 签到相关
    last_checkin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    checkin_days: Mapped[int] = mapped_column(
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
        index=True,
    )

    error_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
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
        return f"<Account(id={self.id}, email={self.email})>"


class CheckinLog(Base):
    """
    GLaDOS 签到日志表。

    记录每次签到的结果以及签到时间。
    """

    __tablename__ = "glados_checkin_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{Account.__tablename__}.id"),
        nullable=False,
        index=True,
    )

    success: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 签到时间：年月日时分秒，统一 UTC
    checkin_at: Mapped[datetime] = mapped_column(
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
            f"success={self.success}"
            f")>"
        )


class TrafficHistory(Base):
    """
    GLaDOS 流量历史表。

    记录账号的流量变化历史。
    """

    __tablename__ = "glados_traffic_history"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{Account.__tablename__}.id"),
        nullable=False,
        index=True,
    )

    used_traffic: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    total_traffic: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    remaining_traffic: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # 记录时间：统一 UTC
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<TrafficHistory(id={self.id}, account_id={self.account_id})>"


__all__ = [
    "Account",
    "CheckinLog",
    "TrafficHistory",
]
