"""Chat history recorder and aiogram middleware for inbound and outbound messages.

Captures all customer interactions (text, callbacks, screen renders, audio previews)
into the database via a non-blocking queue and asynchronous batch drain.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.fsm.context import FSMContext
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendAudio,
    SendMessage,
    SendPhoto,
    SendVoice,
    TelegramMethod,
)
from aiogram.methods.base import Response, TelegramType
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin.chats import ChatLineDraft, record_chat_batch
from hbd.db.enums import ChatDirection, ChatMessageKind
from hbd.logging import get_logger

__all__ = [
    "ChatRecorder",
    "ChatLogInboundMiddleware",
    "ChatLogOutboundMiddleware",
    "DEFAULT_CHAT_QUEUE_MAXSIZE",
]

_LOG = get_logger(__name__)

DEFAULT_CHAT_QUEUE_MAXSIZE: Final[int] = 2000
_BATCH_SIZE: Final[int] = 50
_FLUSH_INTERVAL_S: Final[float] = 0.5


class ChatRecorder:
    """Bounded, non-blocking queue and background batch writer for chat messages."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        maxsize: int = DEFAULT_CHAT_QUEUE_MAXSIZE,
        batch_size: int = _BATCH_SIZE,
        flush_interval_s: float = _FLUSH_INTERVAL_S,
    ) -> None:
        self._session_factory = session_factory
        self._queue: asyncio.Queue[ChatLineDraft] = asyncio.Queue(maxsize=max(1, maxsize))
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._dropped = 0
        self._drain_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def offer(self, draft: ChatLineDraft) -> bool:
        """Offer a draft without blocking or raising. Returns False if dropped."""
        if self._session_factory is None:
            return False
        try:
            self._queue.put_nowait(draft)
        except asyncio.QueueFull:
            self._dropped += 1
            _LOG.warning(
                "chat record dropped: chat drain queue is full",
                extra={"telegram_user_id": draft.telegram_user_id, "dropped": self._dropped},
            )
            return False
        else:
            return True

    async def flush_batch(self, batch: list[ChatLineDraft]) -> None:
        if not batch or self._session_factory is None:
            return
        try:
            async with self._session_factory.begin() as session:
                await record_chat_batch(session, batch)
        except Exception as exc:
            _LOG.error(
                "failed to record chat batch to database",
                extra={"batch_size": len(batch), "error": repr(exc)},
            )

    async def _drain_loop(self) -> None:
        while self._running:
            batch: list[ChatLineDraft] = []
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval_s)
                batch.append(first)
                self._queue.task_done()
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            while len(batch) < self._batch_size:
                try:
                    item = self._queue.get_nowait()
                    batch.append(item)
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break

            if batch:
                await self.flush_batch(batch)

    async def start(self) -> None:
        if self._running or self._session_factory is None:
            return
        self._running = True
        self._drain_task = asyncio.create_task(self._drain_loop(), name="chat-drain-loop")

    async def aclose(self) -> None:
        self._running = False
        if self._drain_task is not None:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
            self._drain_task = None

        remaining: list[ChatLineDraft] = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        if remaining and self._session_factory is not None:
            await self.flush_batch(remaining)


class ChatLogInboundMiddleware(BaseMiddleware):
    """Inbound middleware logging customer messages and callbacks to the recorder."""

    def __init__(self, recorder: ChatRecorder | None) -> None:
        self._recorder = recorder

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._recorder is not None:
            with contextlib.suppress(Exception):
                await self._record_inbound(event, data)
        return await handler(event, data)

    async def _record_inbound(self, event: TelegramObject, data: dict[str, Any]) -> None:
        if self._recorder is None:
            return

        wizard_step: str | None = None
        state: FSMContext | None = data.get("state")
        if state is not None:
            with contextlib.suppress(Exception):
                wizard_step = await state.get_state()

        if isinstance(event, Message):
            user = event.from_user
            if user is None:
                return

            kind = ChatMessageKind.TEXT
            body = event.text or ""
            if event.audio is not None:
                kind = ChatMessageKind.AUDIO
                body = event.caption or "[Audio]"
            elif event.voice is not None:
                kind = ChatMessageKind.VOICE
                body = event.caption or "[Voice]"
            elif event.photo is not None:
                kind = ChatMessageKind.SCREEN
                body = event.caption or "[Photo]"

            draft = ChatLineDraft(
                telegram_user_id=user.id,
                chat_id=event.chat.id,
                direction=ChatDirection.INBOUND,
                kind=kind,
                body=body,
                telegram_message_id=event.message_id,
                wizard_step=wizard_step,
            )
            self._recorder.offer(draft)

        elif isinstance(event, CallbackQuery):
            user = event.from_user
            chat_id = event.message.chat.id if event.message else user.id
            draft = ChatLineDraft(
                telegram_user_id=user.id,
                chat_id=chat_id,
                direction=ChatDirection.INBOUND,
                kind=ChatMessageKind.CALLBACK,
                body=event.data or "",
                callback_data=event.data,
                telegram_message_id=event.message.message_id if event.message else None,
                wizard_step=wizard_step,
            )
            self._recorder.offer(draft)


def _extract_buttons(reply_markup: Any) -> list[list[dict[str, str]]] | None:
    if reply_markup is None:
        return None
    keyboard = getattr(reply_markup, "inline_keyboard", None)
    if not keyboard:
        return None
    rows: list[list[dict[str, str]]] = []
    for row in keyboard:
        btn_row: list[dict[str, str]] = []
        for btn in row:
            btn_info: dict[str, str] = {"text": getattr(btn, "text", "")}
            if getattr(btn, "callback_data", None):
                btn_info["callback_data"] = str(btn.callback_data)
            if getattr(btn, "url", None):
                btn_info["url"] = str(btn.url)
            btn_row.append(btn_info)
        if btn_row:
            rows.append(btn_row)
    return rows or None


class ChatLogOutboundMiddleware(BaseRequestMiddleware):
    """aiogram session middleware capturing bot outbound messages (text, audio, buttons)."""

    def __init__(self, recorder: ChatRecorder | None) -> None:
        self._recorder = recorder

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        result = await make_request(bot, method)
        if self._recorder is not None:
            with contextlib.suppress(Exception):
                self._record_outbound(method, result)
        return result

    def _record_outbound(self, method: TelegramMethod[Any], result: Any) -> None:
        if self._recorder is None:
            return

        chat_id_val = getattr(method, "chat_id", None)
        if chat_id_val is None:
            return

        try:
            chat_id = int(chat_id_val)
        except (ValueError, TypeError):
            return

        telegram_user_id = chat_id if chat_id > 0 else 0
        if telegram_user_id == 0:
            return

        body = ""
        kind = ChatMessageKind.TEXT
        buttons = _extract_buttons(getattr(method, "reply_markup", None))

        if isinstance(method, SendMessage):
            body = method.text or ""
            kind = ChatMessageKind.SCREEN if buttons else ChatMessageKind.TEXT
        elif isinstance(method, EditMessageText):
            body = method.text or ""
            kind = ChatMessageKind.SCREEN
        elif isinstance(method, SendAudio):
            body = method.caption or "[Audio]"
            kind = ChatMessageKind.AUDIO
        elif isinstance(method, SendVoice):
            body = method.caption or "[Voice]"
            kind = ChatMessageKind.VOICE
        elif isinstance(method, SendPhoto):
            body = method.caption or "[Photo]"
            kind = ChatMessageKind.SCREEN
        elif isinstance(method, AnswerCallbackQuery):
            if not method.text:
                return
            body = method.text
            kind = ChatMessageKind.TOAST
        else:
            return

        msg_id: int | None = None
        if isinstance(result, Message):
            msg_id = result.message_id
        elif isinstance(result, Response) and isinstance(result.result, Message):
            msg_id = result.result.message_id

        draft = ChatLineDraft(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            direction=ChatDirection.OUTBOUND,
            kind=kind,
            body=body,
            telegram_message_id=msg_id,
        )
        self._recorder.offer(draft)
