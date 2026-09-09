"""Database queries and persistence for chat logging and the admin chats console.

ADMIN_PANEL_PLAN §5.7, §7.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.base import utc_now
from hbd.db.enums import ChatDirection, ChatMessageKind
from hbd.db.models.chat_message import CHAT_BODY_MAX_CHARS, ChatMessageRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy
from hbd.logging import get_logger

__all__ = [
    "ChatLineDraft",
    "ChatConversationSummary",
    "record_chat_batch",
    "list_chat_conversations",
    "get_chat_transcript",
    "truncate_chat_body",
]

_LOG: Final = get_logger(__name__)

DEFAULT_ABANDONED_DAYS: Final[int] = 14
DEFAULT_CHAT_LOG_DAYS: Final[int] = 90


def truncate_chat_body(text: str | None) -> tuple[str | None, bool]:
    """Truncate chat text to CHAT_BODY_MAX_CHARS before persisting."""
    if text is None:
        return None, False
    if len(text) <= CHAT_BODY_MAX_CHARS:
        return text, False
    return text[:CHAT_BODY_MAX_CHARS], True


@dataclass(frozen=True, slots=True)
class ChatLineDraft:
    """An uncommitted chat message draft prepared by inbound or outbound middleware."""

    telegram_user_id: int
    chat_id: int
    direction: ChatDirection
    kind: ChatMessageKind
    body: str | None = None
    user_id: UUID | None = None
    order_id: UUID | None = None
    session_id: str | None = None
    wizard_step: str | None = None
    telegram_message_id: int | None = None
    callback_data: str | None = None
    parse_mode: str | None = None
    is_truncated: bool = False
    is_from_worker: bool = False
    media_group_id: str | None = None
    error_code: str | None = None
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ChatConversationSummary:
    """One conversation thread in the admin Chats screen."""

    telegram_user_id: int
    chat_id: int
    user_id: UUID | None
    username: str | None
    first_name: str | None
    last_name: str | None
    phone_e164: str | None
    has_avatar: bool
    is_blocked: bool
    last_message_at: datetime
    last_message_text: str | None
    last_message_direction: ChatDirection
    last_message_kind: ChatMessageKind
    message_count: int
    wizard_step: str | None


async def record_chat_batch(
    session: AsyncSession,
    drafts: Sequence[ChatLineDraft],
    *,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> int:
    """Insert a batch of chat message drafts with retention clocks applied."""
    if not drafts:
        return 0

    rows: list[ChatMessageRow] = []
    for draft in drafts:
        body, was_clipped = truncate_chat_body(draft.body)
        is_truncated = draft.is_truncated or was_clipped
        created_at = draft.created_at
        text_expires_at = created_at + timedelta(days=policy.abandoned_draft_days)
        expires_at = created_at + timedelta(days=DEFAULT_CHAT_LOG_DAYS)

        row = ChatMessageRow(
            id=uuid4(),
            telegram_user_id=draft.telegram_user_id,
            chat_id=draft.chat_id,
            user_id=draft.user_id,
            order_id=draft.order_id,
            session_id=draft.session_id,
            direction=draft.direction,
            kind=draft.kind,
            wizard_step=draft.wizard_step,
            telegram_message_id=draft.telegram_message_id,
            callback_data=draft.callback_data,
            parse_mode=draft.parse_mode,
            body=body,
            is_truncated=is_truncated,
            is_from_worker=draft.is_from_worker,
            media_group_id=draft.media_group_id,
            error_code=draft.error_code,
            correlation_id=draft.correlation_id,
            text_expires_at=text_expires_at,
            body_purged_at=None,
            expires_at=expires_at,
            created_at=created_at,
        )
        rows.append(row)

    session.add_all(rows)
    await session.flush()
    return len(rows)


async def list_chat_conversations(
    session: AsyncSession,
    *,
    limit: int = 50,
    search: str | None = None,
) -> list[ChatConversationSummary]:
    """List recent conversation threads grouped by telegram_user_id.

    Joins with user_profiles and users to enrich each thread with avatar, username, and name.
    """
    # CTE to rank messages per user by created_at DESC
    rn = sa.func.row_number().over(
        partition_by=ChatMessageRow.telegram_user_id,
        order_by=(ChatMessageRow.created_at.desc(), ChatMessageRow.id.desc()),
    ).label("rn")
    total_cnt = sa.func.count(ChatMessageRow.id).over(
        partition_by=ChatMessageRow.telegram_user_id
    ).label("total_cnt")

    ranked_subq = (
        sa.select(
            ChatMessageRow.id.label("msg_id"),
            ChatMessageRow.telegram_user_id,
            ChatMessageRow.chat_id,
            ChatMessageRow.user_id.label("msg_user_id"),
            ChatMessageRow.created_at.label("last_msg_at"),
            ChatMessageRow.body.label("last_msg_body"),
            ChatMessageRow.direction.label("last_msg_direction"),
            ChatMessageRow.kind.label("last_msg_kind"),
            ChatMessageRow.callback_data.label("last_callback_data"),
            ChatMessageRow.wizard_step.label("last_wizard_step"),
            rn,
            total_cnt,
        )
        .subquery("ranked_messages")
    )

    # Filter to rn == 1 (the latest message for each user)
    latest = (
        sa.select(ranked_subq)
        .where(ranked_subq.c.rn == 1)
        .subquery("latest_per_user")
    )

    # Join with users and user_profiles
    query = (
        sa.select(
            latest.c.telegram_user_id,
            latest.c.chat_id,
            sa.func.coalesce(latest.c.msg_user_id, UserRow.id).label("user_id"),
            UserProfileRow.telegram_username.label("username"),
            UserProfileRow.first_name,
            UserProfileRow.last_name,
            UserProfileRow.phone_e164,
            sa.case(
                (UserProfileRow.avatar_stored_at.is_not(None), True),
                else_=False,
            ).label("has_avatar"),
            sa.func.coalesce(UserRow.is_blocked, False).label("is_blocked"),
            latest.c.last_msg_at,
            latest.c.last_msg_body,
            latest.c.last_msg_direction,
            latest.c.last_msg_kind,
            latest.c.last_callback_data,
            latest.c.last_wizard_step,
            latest.c.total_cnt,
        )
        .select_from(latest)
        .outerjoin(UserRow, UserRow.telegram_user_id == latest.c.telegram_user_id)
        .outerjoin(UserProfileRow, UserProfileRow.user_id == UserRow.id)
    )

    if search:
        trimmed = search.strip()
        pattern = f"%{trimmed}%"
        try:
            numeric_id = int(trimmed)
            id_clause = (latest.c.telegram_user_id == numeric_id)
        except ValueError:
            id_clause = sa.literal(False)

        query = query.where(
            sa.or_(
                id_clause,
                UserProfileRow.telegram_username.ilike(pattern),
                UserProfileRow.first_name.ilike(pattern),
                UserProfileRow.last_name.ilike(pattern),
                UserProfileRow.phone_e164.ilike(pattern),
                latest.c.last_msg_body.ilike(pattern),
            )
        )

    query = query.order_by(latest.c.last_msg_at.desc()).limit(limit)
    result = await session.execute(query)

    conversations: list[ChatConversationSummary] = []
    for row in result:
        text = row.last_msg_body
        if not text:
            if row.last_msg_kind == ChatMessageKind.CALLBACK and row.last_callback_data:
                text = f"[Action: {row.last_callback_data}]"
            elif row.last_msg_kind == ChatMessageKind.AUDIO:
                text = "[🎵 Audio Song]"
            elif row.last_msg_kind == ChatMessageKind.VOICE:
                text = "[🎤 Voice Note]"
            elif row.last_msg_kind == ChatMessageKind.SCREEN:
                text = f"[{row.last_wizard_step or 'Screen'}]"
            else:
                text = f"[{row.last_msg_kind}]"

        conversations.append(
            ChatConversationSummary(
                telegram_user_id=row.telegram_user_id,
                chat_id=row.chat_id,
                user_id=row.user_id,
                username=row.username,
                first_name=row.first_name,
                last_name=row.last_name,
                phone_e164=row.phone_e164,
                has_avatar=row.has_avatar,
                is_blocked=row.is_blocked,
                last_message_at=row.last_msg_at,
                last_message_text=text,
                last_message_direction=row.last_msg_direction,
                last_message_kind=row.last_msg_kind,
                message_count=row.total_cnt,
                wizard_step=row.last_wizard_step,
            )
        )

    return conversations


async def get_chat_transcript(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    limit: int = 200,
    before: datetime | None = None,
) -> list[ChatMessageRow]:
    """Return messages for a user in chronological order (earliest first)."""
    query = (
        sa.select(ChatMessageRow)
        .where(ChatMessageRow.telegram_user_id == telegram_user_id)
    )
    if before is not None:
        query = query.where(ChatMessageRow.created_at < before)

    # Order ASC so transcript reads top-to-bottom naturally
    query = query.order_by(ChatMessageRow.created_at.asc(), ChatMessageRow.id.asc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())
