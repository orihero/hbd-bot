"""What one sitting at the lyric step may spend, and what may interleave with it.

Split out of ``test_lyrics_step.py``, which had grown past the repo's 800-line cap. That
module is about the STEP — what the customer sees, pastes and navigates. This one is about
the two things that bound it: the per-draft write ceiling, and the concurrency the writing
frame invites, because the preview asks the customer to type while an ``await`` is in
flight.

Note which ceiling is which. ``MAX_LYRIC_WRITES`` here is per DRAFT and is MEANT to be reset
by a fresh start; the durable per-account daily budget above it lives in
``test_lyric_budget_gate.py``. The two are a pair and neither replaces the other.

The two locally-built ``BotDeps`` carry an EMPTY ``FakeProfiles``, and empty is the correct
half of the rule: every test here reaches ``Wizard.lyrics`` by WALKING, and ``walk_to_lyrics``
now drives the real onboarding screens and creates the row on the way past. The one test that
sets ``Wizard.submitting`` by hand does so AFTER a walk, so it is behind onboarding legitimately
rather than in front of it. With no store at all the onboarding router fails open and the walk
never reaches the writer, so ``content.calls`` would be zero and this file would read as a
regression in the vendor seam.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import ONBOARDED_KEY, UI_LANGUAGE_KEY
from hbd.bot.handlers.lyrics import MAX_LYRIC_WRITES
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import Brief, Language, LyricDraft, Result
from tests.test_bot.conftest import (
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
)
from tests.test_bot.test_lyrics_step import PASTED, current_draft, screen_texts
from tests.test_bot.test_wizard_flow import press, send, walk_to_lyrics


# ---------------------------------------------------------------------------
# spending, and racing
# ---------------------------------------------------------------------------
class StateWatchingContentWriter(RecordingContentWriter):
    """Records the FSM state the session was parked in while the vendor call was in flight.

    The concurrency bug this exists to fence is invisible to a sequential test: writing is
    an ``await``, aiogram handles updates as concurrent tasks, and the preview the user is
    reading invites them to send their own lyric as a message. If ``Wizard.lyrics`` were
    still live during the write, that paste would be accepted, confirmed to the customer,
    and then overwritten by the machine's words when the call returned.
    """

    def __init__(self, state: FSMContext) -> None:
        super().__init__()
        self._state = state
        self.states_during_write: list[str | None] = []

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.states_during_write.append(await self._state.get_state())
        return await super().write_lyrics(brief)


async def test_the_session_is_not_accepting_input_while_the_writer_is_working(
    bot: Bot, settings: Settings, storage: MemoryStorage, state: FSMContext
) -> None:
    # Arrange
    watcher = StateWatchingContentWriter(state)
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=watcher,
        profiles=FakeProfiles(),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — no wizard handler is registered on the busy state, so nothing can race
    assert watcher.states_during_write == [Wizard.submitting.state]
    assert await state.get_state() == Wizard.lyrics.state


class CancellingContentWriter(RecordingContentWriter):
    """Presses Cancel from inside the vendor call, the way a waiting customer would.

    The writing frame carries a Cancel button now, so this is a real sequence and not a
    contrived one: the user gives up during the wait, and the vendor answers afterwards.
    Driving it through a real dispatcher rather than by clearing the state directly is
    what makes it a test of the whole path — ``handle_cancel`` refuses to cancel while an
    ORDER is in flight, and a lyric write must not be mistaken for one.

    The Cancel goes through a SECOND dispatcher over the same storage, and that detail is
    the scenario rather than a convenience. ``build_dispatcher`` now holds a per-chat lock
    for the whole of every update, so within one dispatcher a Cancel cannot be processed
    while a write is in flight — it queues behind it. What can still interleave is a Cancel
    whose lock is a DIFFERENT one: ``RedisEventIsolation`` expires its lock after sixty
    seconds (``DEFAULT_REDIS_LOCK_KWARGS``) and the writer is allowed ``llm_timeout_s``, so
    a slow enough vendor call really does end up sharing the chat with the next update.
    Two dispatchers over one storage is that situation, exactly.
    """

    def __init__(self) -> None:
        super().__init__()
        self._dispatcher: Dispatcher | None = None
        self._bot: Bot | None = None

    def bind(self, dispatcher: Dispatcher, bot: Bot) -> None:
        self._dispatcher, self._bot = dispatcher, bot

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        assert self._dispatcher is not None and self._bot is not None, "bind() was not called"
        await self._dispatcher.feed_update(
            self._bot, callback_update(NavCB(action=NavAction.CANCEL).pack())
        )
        return await super().write_lyrics(brief)


async def test_cancelling_during_the_write_is_not_undone_when_the_lyric_arrives(
    bot: Bot, settings: Settings, storage: MemoryStorage, state: FSMContext
) -> None:
    """Giving up mid-write really gives up. The late result is dropped, not written back.

    Without the check the sequence reads: the customer cancels, is told the session is
    gone, and then a lyric preview appears on the screen that just said goodbye — with the
    whole cancelled draft resurrected in storage behind it.
    """
    # Arrange
    writer = CancellingContentWriter()
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=writer,
        profiles=FakeProfiles(),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    writer.bind(build_dispatcher(deps, storage=storage), bot)

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — the writer was called and answered; nothing OF THE DRAFT survived the cancel
    assert writer.calls == 1
    assert await state.get_state() is None
    # Not ``== {}`` any more, and the difference is the whole of C2-8. ``handle_cancel`` clears
    # through ``common.clear_keeping_identity``, which deliberately carries two keys across the
    # clear: which language to speak, and whether the number has already been asked for. A bare
    # clear here would have made the goodbye message and the next screen disagree about the
    # language, and would have re-asked an onboarded customer for their phone number for the
    # crime of cancelling. Spelled as an exact set so a THIRD key surviving — a draft fragment,
    # an order id — still fails, which is the erasure this test is actually about.
    assert set(await state.get_data()) == {UI_LANGUAGE_KEY, ONBOARDED_KEY}


async def test_a_message_sent_while_the_writer_is_working_cannot_overwrite_the_result(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """A paste that lands mid-write is not silently confirmed and then thrown away."""
    # Arrange — park the session where ``enter_lyrics_step`` parks it during the call
    await walk_to_lyrics(dispatcher, bot)
    written = (await current_draft(state)).lyrics
    await state.set_state(Wizard.submitting)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert — the paste was refused, not accepted and then lost
    assert (await current_draft(state)).lyrics == written


async def test_a_session_cannot_bill_the_writer_without_limit(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    """Regenerate is pre-payment vendor spend on a button anyone reaching /start can press."""
    # Arrange — the walk to the preview spends the first write
    await walk_to_lyrics(dispatcher, bot)

    # Act — press regenerate until the cap is reached, then once more
    for _ in range(MAX_LYRIC_WRITES):
        await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — the writer stopped being called, and the customer was told why
    assert content.calls == MAX_LYRIC_WRITES
    assert (await current_draft(state)).lyric_writes == MAX_LYRIC_WRITES
    assert any(
        translate("wizard.lyrics.too_many", Language.EN, limit=MAX_LYRIC_WRITES) == text
        for text in screen_texts(session)
    )
    assert (await current_draft(state)).lyrics is not None
