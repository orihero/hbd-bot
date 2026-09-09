"""Wire schemas for the Chats console.

ADMIN_PANEL_PLAN §5.7, §6.7.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from hbd.admin.schemas.common import ApiModel
from hbd.db.enums import ChatDirection, ChatMessageKind

__all__ = [
    "ChatConversationItem",
    "ChatConversationsResponse",
    "ChatMessageView",
    "ChatTranscriptResponse",
]


class ChatConversationItem(ApiModel):
    """Summary of one customer conversation thread."""

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


class ChatConversationsResponse(ApiModel):
    """GET /api/chats response envelope."""

    items: list[ChatConversationItem]
    total: int


class ChatMessageView(ApiModel):
    """One message within a customer chat transcript."""

    id: UUID
    telegram_user_id: int
    chat_id: int
    order_id: UUID | None
    session_id: str | None
    direction: ChatDirection
    kind: ChatMessageKind
    wizard_step: str | None
    telegram_message_id: int | None
    callback_data: str | None
    parse_mode: str | None
    body: str | None
    is_truncated: bool
    is_from_worker: bool
    media_group_id: str | None
    error_code: str | None
    correlation_id: str | None
    created_at: datetime


class ChatTranscriptResponse(ApiModel):
    """GET /api/chats/{telegram_user_id}/messages response envelope."""

    telegram_user_id: int
    messages: list[ChatMessageView]
    total: int
