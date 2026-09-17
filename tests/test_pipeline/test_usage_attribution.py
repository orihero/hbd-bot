"""Does a vendor call know which order and which job it was made for?

No provider signature carries an order id — deliberately, and permanently. Attribution
travels in a ``ContextVar`` bound by :func:`bayram.usage.usage_scope`, which means the whole
guarantee is a property of WHERE the scopes are entered and of nothing else. Read the
adapters and you will find no evidence either way; that is what makes these tests the only
place the claim is checkable.

The fakes are wrapped rather than replaced. Each proxy records one measurement at the
moment the real call happens — inside the stage, inside the scope, exactly where a real
adapter's ``self._usage.record(...)`` sits — and the recording sink reads the context the
way ``DbUsageSink`` does, at record time rather than at construction time. So what is
asserted is what a row would actually have been stamped with.

The wizard's lyric preview is here too, driven through the real dispatcher, because it is
the one vendor call in the product with NO order to charge to: it happens before the
customer confirms anything, so its row carries a task and a null order id, and a test that
did not pin the null would let someone "fix" it with an invented id later.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.config import Settings
from bayram.contracts import Brief, LyricDraft, Order, Result, UsageTask, Vendor, VendorOperation
from bayram.usage import UsageContext, UsageSink, VendorUsage, current_usage_context
from tests.test_bot.conftest import (
    BOT_TOKEN,
    FIXED_MOMENT,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_wizard_flow import walk_to_lyrics
from tests.test_pipeline.conftest import Studio, value_of


class UsageRecorder:
    """A ``UsageSink`` that keeps the attribution bound at the moment of each call.

    The context is read HERE and not passed in, mirroring ``DbUsageSink.record`` exactly:
    a sink that captured the context when it was constructed would pass these tests while
    stamping every production row with whatever was bound at startup, which is nothing.
    """

    def __init__(self) -> None:
        self.records: list[tuple[VendorOperation, UsageContext]] = []

    async def record(self, usage: VendorUsage) -> None:
        self.records.append((usage.operation, current_usage_context()))

    @property
    def tasks(self) -> set[UsageTask | None]:
        return {context.task for _, context in self.records}

    @property
    def order_ids(self) -> set[UUID | None]:
        return {context.order_id for _, context in self.records}

    def contexts_for(self, operation: VendorOperation) -> tuple[UsageContext, ...]:
        return tuple(context for recorded, context in self.records if recorded is operation)


class _Measured:
    """One instrumented adapter, standing in front of a pipeline fake.

    Everything not named below is delegated untouched, so the fake keeps behaving exactly
    as every other pipeline test expects it to; the only difference is that one usage
    record is emitted from inside the call.
    """

    def __init__(self, inner: Any, sink: UsageSink) -> None:
        self._inner = inner
        self._sink = sink

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    async def _measure(self, operation: VendorOperation) -> None:
        await self._sink.record(
            VendorUsage(
                vendor=Vendor.FAKE,
                operation=operation,
                provider=self._inner.name,
                is_success=True,
                is_fake=True,
            )
        )


class MeasuredMusic(_Measured):
    async def compose(self, *args: Any, **kwargs: Any) -> Any:
        await self._measure(VendorOperation.MUSIC_COMPOSE)
        return await self._inner.compose(*args, **kwargs)

    async def inpaint(self, *args: Any, **kwargs: Any) -> Any:
        await self._measure(VendorOperation.MUSIC_INPAINT)
        return await self._inner.inpaint(*args, **kwargs)


class MeasuredTts(_Measured):
    async def synthesize(self, *args: Any, **kwargs: Any) -> Any:
        await self._measure(VendorOperation.SPEECH_SYNTHESIS)
        return await self._inner.synthesize(*args, **kwargs)


class MeasuredStt(_Measured):
    async def transcribe(self, *args: Any, **kwargs: Any) -> Any:
        await self._measure(VendorOperation.TRANSCRIPTION)
        return await self._inner.transcribe(*args, **kwargs)


class MeasuredLlm(_Measured):
    async def generate_json(self, *args: Any, **kwargs: Any) -> Any:
        await self._measure(VendorOperation.CHAT_COMPLETION)
        return await self._inner.generate_json(*args, **kwargs)


@pytest.fixture
def recorder() -> UsageRecorder:
    return UsageRecorder()


async def run_measured(studio: Studio, order: Order, recorder: UsageRecorder) -> None:
    """Run one order with every vendor leg instrumented."""
    pipeline = studio.pipeline(
        music=MeasuredMusic(studio.music, recorder),
        tts=MeasuredTts(studio.tts, recorder),
        stt=MeasuredStt(studio.stt, recorder),
        llm=MeasuredLlm(studio.llm, recorder),
    )
    value_of(await pipeline.run(order))


# ---------------------------------------------------------------------------
# The worker's path
# ---------------------------------------------------------------------------
async def test_every_vendor_call_in_a_run_names_the_order_that_paid_for_it(
    studio: Studio, ready_order: Order, recorder: UsageRecorder
) -> None:
    # Arrange / Act
    await run_measured(studio, ready_order, recorder)

    # Assert: one id, and it is the order's — not a null, and not a second one.
    assert recorder.records, "the instrumented run recorded no vendor call at all"
    assert recorder.order_ids == {ready_order.id}


async def test_every_vendor_calling_stage_stamps_its_own_task(
    studio: Studio, ready_order: Order, recorder: UsageRecorder
) -> None:
    """The five tasks a complete run actually spends on, and no ``None`` among them.

    A ``None`` here would mean a stage reached a vendor outside ``_staged``, which is the
    one way the mapping can be silently incomplete: the call still happens, the row still
    lands, and the panel simply cannot say what the money bought.
    """
    # Arrange / Act
    await run_measured(studio, ready_order, recorder)

    # Assert
    assert recorder.tasks == {
        UsageTask.MODERATION,
        UsageTask.LYRICS,
        UsageTask.GREETING_SCRIPTS,
        UsageTask.SONG,
        UsageTask.GREETING_SPEECH,
    }


async def test_the_name_loops_transcription_is_attributed_to_composing_the_song(
    studio: Studio, ready_order: Order, recorder: UsageRecorder
) -> None:
    """Pinning where the name loop's spend lands today, rather than leaving it to chance.

    ``VERIFYING_NAME`` is in the stage-to-task table but the loop runs inside
    ``render_song``, which runs inside COMPOSING_SONG — so its transcription is SONG. That
    is honest, and this test is what makes it a decision: the day the loop gets its own
    stage wrapper, this fails and the attribution is looked at rather than drifting.
    """
    # Arrange / Act
    await run_measured(studio, ready_order, recorder)

    # Assert
    transcriptions = recorder.contexts_for(VendorOperation.TRANSCRIPTION)
    assert transcriptions, "the name loop made no transcription call"
    assert {context.task for context in transcriptions} == {UsageTask.SONG}
    assert {context.order_id for context in transcriptions} == {ready_order.id}


async def test_the_stage_scope_never_detaches_a_call_from_its_order(
    studio: Studio, ready_order: Order, recorder: UsageRecorder
) -> None:
    """The nesting rule, asserted where it can actually break.

    ``_staged`` enters a scope naming only a task. If that inner scope cleared the outer
    ``order_id`` instead of inheriting it, every row in the product would carry a task and
    no order — which reads as unattributable preview spend and would be believed.
    """
    # Arrange / Act
    await run_measured(studio, ready_order, recorder)

    # Assert
    assert all(
        context.order_id == ready_order.id and context.task is not None
        for _, context in recorder.records
    )


async def test_the_run_leaves_no_attribution_bound_behind_it(
    studio: Studio, ready_order: Order, recorder: UsageRecorder
) -> None:
    """A worker process runs orders back to back on one event loop.

    A scope that outlived its run would stamp the NEXT order's calls — and a health probe's
    — with the previous order's id, which is worse than no attribution: it is wrong data
    that looks right.
    """
    # Arrange / Act
    await run_measured(studio, ready_order, recorder)

    # Assert
    assert current_usage_context() == UsageContext(order_id=None, task=None)


# ---------------------------------------------------------------------------
# The wizard's path — spend with no order
# ---------------------------------------------------------------------------
class ContextRecordingWriter(RecordingContentWriter):
    """The wizard's writer, plus the attribution bound when it was called."""

    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[UsageContext] = []

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.contexts.append(current_usage_context())
        return await super().write_lyrics(brief)


@pytest.fixture
def preview_writer() -> ContextRecordingWriter:
    return ContextRecordingWriter()


@pytest.fixture
def wizard(settings: Settings, preview_writer: ContextRecordingWriter) -> tuple[Dispatcher, Bot]:
    """A real dispatcher over recording transports. The wizard, as a customer drives it."""
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=preview_writer,
        clock=lambda: FIXED_MOMENT,
        profiles=FakeProfiles(),
    )
    bot = Bot(
        token=BOT_TOKEN,
        session=RecordingSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return build_dispatcher(deps, storage=MemoryStorage()), bot


async def test_the_lyric_preview_is_spend_with_a_task_and_no_order(
    wizard: tuple[Dispatcher, Bot], preview_writer: ContextRecordingWriter
) -> None:
    """The honest null. There is no order row yet, and there must not be an invented id.

    An id minted here would attach real spend either to an order that never appears — the
    customer closes the chat — or to one that does and did not pay for this call.
    ``LYRICS_PREVIEW`` rather than ``LYRICS`` is what keeps that unattributable spend
    visible as its own line instead of folded into the worker's lyric total.
    """
    # Arrange
    dispatcher, bot = wizard

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert
    assert preview_writer.contexts == [UsageContext(order_id=None, task=UsageTask.LYRICS_PREVIEW)]


async def test_the_preview_scope_does_not_survive_the_screen(
    wizard: tuple[Dispatcher, Bot],
) -> None:
    """Nothing after the write is billed as a preview — the bot serves everybody at once."""
    # Arrange
    dispatcher, bot = wizard

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert
    assert current_usage_context() == UsageContext(order_id=None, task=None)
