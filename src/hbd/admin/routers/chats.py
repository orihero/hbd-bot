"""``/api/chats`` — list customer conversation threads and view full transcript history.

ADMIN_PANEL_PLAN §5.7, §6.7, §7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.schemas.chats import (
    ChatConversationItem,
    ChatConversationsResponse,
    ChatMessageView,
    ChatTranscriptResponse,
)
from hbd.admin.security.permissions import Permission
from hbd.db.admin.chats import get_chat_transcript, list_chat_conversations

__all__ = [
    "CHATS_PATH",
    "CHAT_MESSAGES_PATH_TEMPLATE",
    "build_chats_router",
]

CHATS_PATH: Final[str] = f"{API_PREFIX}/chats"
CHAT_MESSAGES_PATH_TEMPLATE: Final[str] = f"{API_PREFIX}/chats/{{telegram_user_id}}/messages"


def build_chats_router() -> APIRouter:
    """The chats console router. Guarded by Permission.CHAT_INDEX_READ."""
    router = APIRouter(
        tags=["chats"],
        dependencies=[Depends(require_permission(Permission.CHAT_INDEX_READ))],
    )

    @router.get(CHATS_PATH, response_model=ChatConversationsResponse)
    async def list_conversations(
        session: Db,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        q: Annotated[str | None, Query(max_length=128)] = None,
    ) -> ChatConversationsResponse:
        conversations = await list_chat_conversations(session, limit=limit, search=q)
        items = [
            ChatConversationItem(
                telegram_user_id=c.telegram_user_id,
                chat_id=c.chat_id,
                user_id=c.user_id,
                username=c.username,
                first_name=c.first_name,
                last_name=c.last_name,
                phone_e164=c.phone_e164,
                has_avatar=c.has_avatar,
                is_blocked=c.is_blocked,
                last_message_at=c.last_message_at,
                last_message_text=c.last_message_text,
                last_message_direction=c.last_message_direction,
                last_message_kind=c.last_message_kind,
                message_count=c.message_count,
                wizard_step=c.wizard_step,
            )
            for c in conversations
        ]
        return ChatConversationsResponse(items=items, total=len(items))

    @router.get(CHAT_MESSAGES_PATH_TEMPLATE, response_model=ChatTranscriptResponse)
    async def get_messages(
        telegram_user_id: int,
        session: Db,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        before: Annotated[datetime | None, Query()] = None,
    ) -> ChatTranscriptResponse:
        messages = await get_chat_transcript(
            session,
            telegram_user_id=telegram_user_id,
            limit=limit,
            before=before,
        )
        views = [
            ChatMessageView(
                id=m.id,
                telegram_user_id=m.telegram_user_id,
                chat_id=m.chat_id,
                order_id=m.order_id,
                session_id=m.session_id,
                direction=m.direction,
                kind=m.kind,
                wizard_step=m.wizard_step,
                telegram_message_id=m.telegram_message_id,
                callback_data=m.callback_data,
                parse_mode=m.parse_mode,
                body=m.body,
                is_truncated=m.is_truncated,
                is_from_worker=m.is_from_worker,
                media_group_id=m.media_group_id,
                error_code=m.error_code,
                correlation_id=m.correlation_id,
                created_at=m.created_at,
            )
            for m in messages
        ]
        return ChatTranscriptResponse(
            telegram_user_id=telegram_user_id,
            messages=views,
            total=len(views),
        )

    return router
