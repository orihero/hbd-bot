"""``chat_messages`` — inbound and outbound chat logging for every user interaction.

ADMIN_PANEL_PLAN §5.7, §7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import ChatDirection, ChatMessageKind

__all__ = [
    "ChatMessageRow",
    "CHAT_BODY_MAX_CHARS",
    "WIZARD_STEP_LENGTH",
    "CALLBACK_DATA_LENGTH",
    "PARSE_MODE_LENGTH",
    "MEDIA_GROUP_ID_LENGTH",
    "ERROR_CODE_LENGTH",
    "CORRELATION_ID_LENGTH",
    "SESSION_ID_LENGTH",
]

CHAT_BODY_MAX_CHARS: Final[int] = 4_000
WIZARD_STEP_LENGTH: Final[int] = 32
CALLBACK_DATA_LENGTH: Final[int] = 64
PARSE_MODE_LENGTH: Final[int] = 16
MEDIA_GROUP_ID_LENGTH: Final[int] = 32
ERROR_CODE_LENGTH: Final[int] = 48
CORRELATION_ID_LENGTH: Final[int] = 128
SESSION_ID_LENGTH: Final[int] = 32


class ChatMessageRow(Base):
    """One line of dialogue between a Telegram customer and the bot (or worker)."""

    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(
        sa.String(SESSION_ID_LENGTH), nullable=True, index=True
    )
    direction: Mapped[ChatDirection] = mapped_column(enum_type(ChatDirection), nullable=False)
    kind: Mapped[ChatMessageKind] = mapped_column(enum_type(ChatMessageKind), nullable=False)
    wizard_step: Mapped[str | None] = mapped_column(sa.String(WIZARD_STEP_LENGTH), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    callback_data: Mapped[str | None] = mapped_column(
        sa.String(CALLBACK_DATA_LENGTH), nullable=True
    )
    parse_mode: Mapped[str | None] = mapped_column(sa.String(PARSE_MODE_LENGTH), nullable=True)
    body: Mapped[str | None] = mapped_column(sa.String(CHAT_BODY_MAX_CHARS), nullable=True)
    is_truncated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    is_from_worker: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    media_group_id: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_GROUP_ID_LENGTH), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(
        sa.String(CORRELATION_ID_LENGTH), nullable=True, index=True
    )
    text_expires_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, index=True
    )
    body_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )

    __table_args__ = (
        sa.Index("ix_chat_messages_user_timeline", "telegram_user_id", "created_at"),
        sa.Index("ix_chat_messages_text_sweep", "text_expires_at"),
        sa.Index("ix_chat_messages_expiry_sweep", "expires_at"),
    )
