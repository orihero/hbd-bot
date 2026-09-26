"""Unit tests for chat recorder and aiogram logging middlewares."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.methods import SendMessage
from aiogram.methods.base import Response
from aiogram.types import CallbackQuery, Chat, Message, User

from bayram.bot.chatlog import (
    ChatLogInboundMiddleware,
    ChatLogOutboundMiddleware,
    ChatRecorder,
)
from bayram.db.admin.chats import ChatLineDraft
from bayram.db.enums import ChatDirection, ChatMessageKind


@pytest.fixture
def mock_session_factory() -> MagicMock:
    factory = MagicMock()
    session = AsyncMock()
    # async context manager
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = None
    factory.begin.return_value = cm
    return factory


async def test_recorder_offer_and_dropped(mock_session_factory: MagicMock) -> None:
    recorder = ChatRecorder(mock_session_factory, maxsize=2)
    draft1 = ChatLineDraft(
        telegram_user_id=1,
        chat_id=1,
        direction=ChatDirection.INBOUND,
        kind=ChatMessageKind.TEXT,
        body="hi 1",
    )
    draft2 = ChatLineDraft(
        telegram_user_id=1,
        chat_id=1,
        direction=ChatDirection.INBOUND,
        kind=ChatMessageKind.TEXT,
        body="hi 2",
    )
    draft3 = ChatLineDraft(
        telegram_user_id=1,
        chat_id=1,
        direction=ChatDirection.INBOUND,
        kind=ChatMessageKind.TEXT,
        body="hi 3",
    )

    assert recorder.offer(draft1) is True
    assert recorder.offer(draft2) is True
    # Queue is full, should drop and increment dropped count
    assert recorder.offer(draft3) is False
    assert recorder.dropped == 1
    assert recorder.pending == 2


async def test_recorder_drain_and_aclose(mock_session_factory: MagicMock) -> None:
    recorder = ChatRecorder(mock_session_factory, maxsize=10, batch_size=2, flush_interval_s=0.05)
    await recorder.start()

    draft1 = ChatLineDraft(
        telegram_user_id=1,
        chat_id=1,
        direction=ChatDirection.INBOUND,
        kind=ChatMessageKind.TEXT,
        body="hi 1",
    )
    recorder.offer(draft1)
    await asyncio.sleep(0.1)

    await recorder.aclose()
    # begin was called on session_factory
    assert mock_session_factory.begin.called


async def test_inbound_middleware_records_message(mock_session_factory: MagicMock) -> None:
    recorder = ChatRecorder(mock_session_factory)
    middleware = ChatLogInboundMiddleware(recorder)

    user = User(id=42, is_bot=False, first_name="Test")
    chat = Chat(id=42, type="private")
    msg = Message(message_id=101, date=datetime.now(UTC), chat=chat, from_user=user, text="Hello bot")

    handler = AsyncMock(return_value="handled")
    result = await middleware(handler, msg, {})

    assert result == "handled"
    assert recorder.pending == 1
    draft = recorder._queue.get_nowait()
    assert draft.telegram_user_id == 42
    assert draft.chat_id == 42
    assert draft.body == "Hello bot"
    assert draft.direction == ChatDirection.INBOUND
    assert draft.kind == ChatMessageKind.TEXT


async def test_inbound_middleware_records_callback(mock_session_factory: MagicMock) -> None:
    recorder = ChatRecorder(mock_session_factory)
    middleware = ChatLogInboundMiddleware(recorder)

    user = User(id=42, is_bot=False, first_name="Test")
    chat = Chat(id=42, type="private")
    msg = Message(message_id=101, date=datetime.now(UTC), chat=chat, from_user=user, text="prompt")
    cb = CallbackQuery(id="cb1", from_user=user, chat_instance="ci1", message=msg, data="btn:select")

    handler = AsyncMock(return_value="ok")
    result = await middleware(handler, cb, {})

    assert result == "ok"
    assert recorder.pending == 1
    draft = recorder._queue.get_nowait()
    assert draft.telegram_user_id == 42
    assert draft.callback_data == "btn:select"
    assert draft.direction == ChatDirection.INBOUND
    assert draft.kind == ChatMessageKind.CALLBACK


async def test_outbound_middleware_records_send_message(mock_session_factory: MagicMock) -> None:
    recorder = ChatRecorder(mock_session_factory)
    middleware = ChatLogOutboundMiddleware(recorder)

    method = SendMessage(chat_id=42, text="Bot response")
    bot = MagicMock()
    user = User(id=99, is_bot=True, first_name="Bot")
    chat = Chat(id=42, type="private")
    msg_obj = Message(message_id=202, date=datetime.now(UTC), chat=chat, from_user=user, text="Bot response")
    mock_res: Any = Response[Message](ok=True, result=msg_obj)
    make_request = AsyncMock(return_value=mock_res)

    res = await middleware(make_request, bot, method)
    assert res == mock_res

    assert recorder.pending == 1
    draft = recorder._queue.get_nowait()
    assert draft.telegram_user_id == 42
    assert draft.chat_id == 42
    assert draft.body == "Bot response"
    assert draft.direction == ChatDirection.OUTBOUND
    assert draft.kind == ChatMessageKind.TEXT
