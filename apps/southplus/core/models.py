# apps/southplus/core/models.py

"""
SouthPlus 数据库实体定义。

定义所有与 SouthPlus 相关的数据表。
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
    SouthPlus 账号表。

    存储账号基础信息、Cookie、SP Point 以及任务完成状态。
    """

    __tablename__ = "southplus_accounts"

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

    # 加密后的 Cookie
    cookies: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # SP Point
    points_sp: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # 日常任务
    last_daily_complete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    daily_complete_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # 周常任务
    last_weekly_complete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    weekly_complete_count: Mapped[int] = mapped_column(
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


class DailyCompleteLog(Base):
    """
    SouthPlus 日常任务完成日志表。

    记录每次日常任务完成的结果、完成时间以及获得的 SP Point 变化量。
    """

    __tablename__ = "southplus_daily_complete_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("southplus_accounts.id"),
        nullable=False,
        index=True,
    )

    success: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    # 本次完成任务产生的 SP Point 变化量
    delta_points_sp: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 任务实际完成时间
    complete_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # 日志创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<DailyCompleteLog("
            f"id={self.id}, "
            f"account_id={self.account_id}, "
            f"success={self.success}, "
            f"points_sp_change={self.delta_points_sp}"
            f")>"
        )


class WeeklyCompleteLog(Base):
    """
    SouthPlus 周常任务完成日志表。

    记录每次周常任务完成的结果、完成时间以及获得的 SP Point 变化量。
    """

    __tablename__ = "southplus_weekly_complete_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("southplus_accounts.id"),
        nullable=False,
        index=True,
    )

    success: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    # 本次完成任务产生的 SP Point 变化量
    delta_points_sp: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 任务实际完成时间
    complete_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # 日志创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<WeeklyCompleteLog("
            f"id={self.id}, "
            f"account_id={self.account_id}, "
            f"success={self.success}, "
            f"points_sp_change={self.delta_points_sp}"
            f")>"
        )


class NotificationLog(Base):
    """
    SouthPlus 通知发送日志表。

    记录 SouthPlus 整体通知的发送结果。
    每天最多尝试发送一次通知。
    """

    __tablename__ = "southplus_notification_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    # 是否发送成功
    success: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    # 通知发送结果说明
    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 通知发送时间
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationLog("
            f"id={self.id}, "
            f"success={self.success}, "
            f"message={self.message!r}, "
            f"sent_at={self.sent_at}"
            f")>"
        )


__all__ = [
    "Account",
    "DailyCompleteLog",
    "NotificationLog",
    "WeeklyCompleteLog",
]
