"""Test doubles for the bot layer. Nothing here touches the network.

The Bot is real — a real ``aiogram.Bot`` with a real router tree — but its *session* is
replaced, so every outgoing call is recorded instead of sent and canned replies come back
synthetically. That is deliberate: the wizard is exercised by feeding real ``Update``
objects through a real ``Dispatcher`` and pressing the callback data the real keyboards
produced, which is the only way a routing or FSM bug actually shows up in a test.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

from hbd.bot.app import build_dispatcher
from hbd.bot.deps import BotDeps
from hbd.config import Settings
from hbd.contracts import (
    Brief,
    LyricDraft,
    LyricSection,
    Order,
    Result,
    SpokenScript,
    VoiceDescriptor,
    err,
    ok,
)
from hbd.errors import HbdError, PipelineError

BOT_TOKEN = "42:AAF-test-token-value-not-a-real-one"
BOT_ID = 42
CHAT_ID = 1_000_777
USER_ID = 1_000_777
FIXED_MOMENT = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


class RecordingSession(BaseSession):
    """Records every outgoing call and answers with a plausible canned response."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.failures: dict[str, Exception] = {}
        self._next_message_id = 100

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        failure = self.failures.get(name)
        if failure is not None:
            raise failure
        if name == "AnswerCallbackQuery":
            return True
        return self._message_for(method)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - the signature is aiogram's, not ours
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    def _message_for(self, method: TelegramMethod[Any]) -> Message:
        self._next_message_id += 1
        return Message(
            message_id=getattr(method, "message_id", None) or self._next_message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="hbd"),
            text=getattr(method, "text", None),
            reply_markup=getattr(method, "reply_markup", None),
        )

    # -- assertions helpers -------------------------------------------------
    def named(self, name: str) -> tuple[TelegramMethod[Any], ...]:
        return tuple(call for call in self.calls if type(call).__name__ == name)

    def last_named(self, name: str) -> Any:
        found = self.named(name)
        assert found, f"no {name} call was made; calls were {self.call_names}"
        return found[-1]

    @property
    def call_names(self) -> tuple[str, ...]:
        return tuple(type(call).__name__ for call in self.calls)

    @property
    def last_screen(self) -> Any:
        """The most recent call that put text on the screen, sent or edited."""
        screens = [
            call
            for call in self.calls
            if type(call).__name__ in {"SendMessage", "EditMessageText"}
        ]
        assert screens, f"nothing was put on screen; calls were {self.call_names}"
        return screens[-1]

    def clear(self) -> None:
        self.calls.clear()


class RecordingSubmitter:
    """A fake job queue. Records what it was handed; can be told to fail."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.submitted: list[tuple[Order, int, int]] = []
        self.failure = failure

    async def submit(
        self, order: Order, *, chat_id: int, progress_message_id: int
    ) -> Result[str]:
        if self.failure is not None:
            from hbd.contracts import err

            return err(PipelineError("queue unavailable", cause=self.failure))
        self.submitted.append((order, chat_id, progress_message_id))
        return ok(f"job-{uuid4().hex[:8]}")


#: What the fake writer puts in a verse. Deliberately says nothing about the recipient, so
#: a test asserting on the name is asserting on the hook section and nothing else.
LYRIC_VERSE = "The candles are lit and the table is laid"


def canned_lyrics(brief: Brief, *, take: int) -> LyricDraft:
    """The lyric the fake writer returns on its ``take``-th call.

    ``take`` appears in the title and in the hook, which is what lets a regenerate test
    tell a genuinely new lyric from the previous one merely being re-rendered.

    Only ``recipient.display`` reaches the text. The submitted candidates — the stripped
    and hyphenated spellings sent to the voice vendor — must never appear on a screen, and
    the lyric preview is a screen, so a fake that leaked one would quietly turn that
    invariant's test green for the wrong reason.
    """
    display = brief.recipient.display
    return LyricDraft(
        title=f"Take {take} for {display}",
        language=brief.output_language,
        sections=(
            LyricSection(label="verse-1", lines=(LYRIC_VERSE,)),
            LyricSection(
                label="hook",
                lines=(f"{display}, take {take} is for you",),
                is_name_hook=True,
            ),
        ),
        name_display=display,
    )


class RecordingContentWriter:
    """A fake lyric writer. Records the briefs it was asked to write for.

    The wizard now calls a :class:`~hbd.pipeline.ports.ContentWriter` on the customer's
    screen, so the bot tests need one that answers instantly and predictably. Set
    ``failure`` to a typed error and every subsequent call comes back as an ``Err``, which
    is how the "the writer fell over mid-wizard" path is exercised without a vendor.
    """

    def __init__(self, *, failure: HbdError | None = None) -> None:
        self.briefs: list[Brief] = []
        self.failure = failure

    @property
    def calls(self) -> int:
        """How many times a lyric was asked for. One per preview shown."""
        return len(self.briefs)

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.briefs.append(brief)
        if self.failure is not None:
            return err(self.failure)
        return ok(canned_lyrics(brief, take=len(self.briefs)))

    async def write_scripts(
        self,
        brief: Brief,
        lyrics: LyricDraft,
        *,
        voices: tuple[VoiceDescriptor, ...],
        name_submitted: str,
        target_duration_s: float,
    ) -> Result[tuple[SpokenScript, ...]]:
        """Never reached from the bot: spoken greetings are the worker's half of the job."""
        raise AssertionError("the wizard must not ask the writer for spoken scripts")


class DecliningPaymentProvider:
    """Authorises nothing. Exists to prove the gate is actually consulted."""

    name = "declining"

    async def authorize(self, *, order_id: Any, amount_minor: int, currency: str) -> Result[Any]:
        from hbd.contracts import PaymentAuthorization

        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference="declined",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=False,
            )
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    return Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def submitter() -> RecordingSubmitter:
    return RecordingSubmitter()


@pytest.fixture
def content() -> RecordingContentWriter:
    return RecordingContentWriter()


@pytest.fixture
def clock() -> Callable[[], datetime]:
    return lambda: FIXED_MOMENT


@pytest.fixture
def deps(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
) -> BotDeps:
    return BotDeps(settings=settings, submitter=submitter, content=content, clock=clock)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def dispatcher(deps: BotDeps, storage: MemoryStorage) -> Dispatcher:
    return build_dispatcher(deps, storage=storage)


@pytest.fixture
def state(storage: MemoryStorage) -> FSMContext:
    key = StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    return FSMContext(storage=storage, key=key)


# ---------------------------------------------------------------------------
# Update builders
# ---------------------------------------------------------------------------
_update_id = 0


def _next_update_id() -> int:
    global _update_id
    _update_id += 1
    return _update_id


def make_message(text: str, *, message_id: int = 10) -> Message:
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        text=text,
    )


def make_non_text_message(*, message_id: int = 11) -> Message:
    """A message with no text at all — a sticker, a voice note, a photo."""
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
    )


def make_callback(data: str, *, message_id: int = 20) -> CallbackQuery:
    return CallbackQuery(
        id=f"cb-{message_id}-{data}",
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        chat_instance="chat-instance",
        data=data,
        message=Message(
            message_id=message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="hbd"),
            text="previous screen",
        ),
    )


def message_update(text: str) -> Update:
    return Update(update_id=_next_update_id(), message=make_message(text))


def callback_update(data: str) -> Update:
    return Update(update_id=_next_update_id(), callback_query=make_callback(data))


# ---------------------------------------------------------------------------
# Keyboard readers — a test presses the button the user would press
# ---------------------------------------------------------------------------
def buttons(markup: InlineKeyboardMarkup | None) -> tuple[tuple[str, str], ...]:
    """Every ``(text, callback_data)`` pair in a markup, flattened."""
    if markup is None:
        return ()
    return tuple(
        (button.text, button.callback_data or "")
        for row in markup.inline_keyboard
        for button in row
    )


def data_with_prefix(markup: InlineKeyboardMarkup | None, prefix: str) -> str:
    """The callback data of the first button whose payload starts with ``prefix``."""
    for _, data in buttons(markup):
        if data.startswith(prefix):
            return data
    raise AssertionError(f"no button with prefix {prefix!r} in {buttons(markup)}")
