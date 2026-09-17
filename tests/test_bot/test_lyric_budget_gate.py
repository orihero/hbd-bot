"""The per-account daily lyric budget, driven through the real wizard.

Everything here runs against a REAL :class:`~bayram.db.lyric_budget.SqlLyricBudget` over an
in-memory SQLite database rather than a recording fake, and that is the point of the module
rather than thoroughness for its own sake. The defect this unit closes is that the only
existing cap lives on the DRAFT and ``reset_to_welcome`` throws the draft away — so the test
that proves it fixed has to show a count outliving a ``/start``, and a fake that a test
hands out and controls proves nothing about whether the number really landed somewhere a
``/start`` cannot reach. The row is checked directly.

The budget is charged at the one place the writer is called, so "refused" and "no vendor
call" are the same assertion made twice: ``RecordingContentWriter.calls`` is the money.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.draft import WizardDraft, load_draft
from bayram.bot.i18n import translate
from bayram.bot.keyboards import start_over_keyboard
from bayram.bot.states import Wizard
from bayram.config import Settings
from bayram.contracts import Language
from bayram.db.engine import create_session_factory
from bayram.db.lyric_budget import SqlLyricBudget
from bayram.db.models import Base
from bayram.lyric_budget import LyricBudgetPolicy
from tests.test_bot.conftest import (
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
)
from tests.test_bot.test_lyrics_step import screen_texts
from tests.test_bot.test_wizard_flow import press, send, walk_to_lyrics

pytestmark = pytest.mark.anyio

#: Mid-day, so advancing the clock by a day is not a boundary coincidence.
_NOON: datetime = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


class MovableClock:
    """``deps.clock`` a test can push forward. The budget's day comes from this and only this."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, *, days: int) -> None:
        self._now = self._now + timedelta(days=days)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def budget_clock() -> MovableClock:
    return MovableClock(_NOON)


@pytest.fixture
def writes_per_day() -> int:
    """Overridden per test. Small numbers so a refusal is two presses away, not twenty."""
    return 1


@pytest.fixture
def budget(sessions: async_sessionmaker[AsyncSession], writes_per_day: int) -> SqlLyricBudget:
    return SqlLyricBudget(sessions, policy=LyricBudgetPolicy(writes_per_day=writes_per_day))


@pytest.fixture
def metered_deps(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    budget_clock: MovableClock,
    budget: SqlLyricBudget,
    profiles: FakeProfiles,
) -> BotDeps:
    """The shared dependencies with the budget wired — and the profile store still wired.

    ``profiles`` is taken from the shared fixture rather than constructed here, so that this
    module's dispatcher differs from the suite's in exactly one respect: the budget. Dropping
    it would not fail as "no store": ``walk_to_lyrics`` drives the real onboarding screens, the
    onboarding router would fail open, the walker's language press would match no handler, and
    every refusal assertion below would compare English copy against a screen rendered in the
    operator's default language — a failure that reads as a locale bug in the budget copy.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=content,
        clock=budget_clock,
        lyric_budget=budget,
        profiles=profiles,
    )


@pytest.fixture
def dispatcher(metered_deps: BotDeps, storage: MemoryStorage) -> Dispatcher:
    """Shadows the shared fixture so the whole module runs with the budget wired."""
    return build_dispatcher(metered_deps, storage=storage)


async def writes_on_record(sessions: async_sessionmaker[AsyncSession]) -> int:
    """What the ``lyric_budgets`` row actually says. Read outside every handler on purpose.

    Raw SQL rather than the mapped row: Rule 15 (``bayram/db/__init__.py``) keeps every ``*Row``
    inside persistence, and a test outside ``tests/test_db`` that imported one to read a
    column would be the first exception to it.
    """
    async with sessions() as session:
        count = await session.scalar(
            sa.text("SELECT writes FROM lyric_budgets WHERE telegram_user_id = :id"),
            {"id": USER_ID},
        )
    return int(count or 0)


async def current_draft(state: FSMContext) -> WizardDraft | None:
    from bayram.contracts import Ok

    result = load_draft(await state.get_data())
    return result.value if isinstance(result, Ok) else None


def refusal_text(limit: int, resets_at: str, language: Language = Language.EN) -> str:
    return translate("wizard.lyrics.budget_spent", language, limit=limit, resets_at=resets_at)


@pytest.mark.parametrize("writes_per_day", [5])
async def test_the_daily_count_survives_a_start_over(
    dispatcher: Dispatcher,
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    """THE regression this unit exists for. ``/start`` resets the draft; it must not reset this.

    ``handlers.common.reset_to_welcome`` clears the FSM and mints a fresh ``WizardDraft``,
    which is exactly what makes ``MAX_LYRIC_WRITES`` — a field on that draft — resettable by
    anyone who can type ``/start``. The count below is read out of the database, not out of
    the session, so it can only have survived by being somewhere the reset cannot reach.
    """
    # Arrange — one full walk, which spends one write.
    await walk_to_lyrics(dispatcher, bot)
    assert await writes_on_record(sessions) == 1

    # Act — throw the session away exactly as a customer does, then walk again.
    await send(dispatcher, bot, "/start")
    await walk_to_lyrics(dispatcher, bot)

    # Assert — the per-draft counter DID reset (that is its job) and the daily one did not.
    draft = await current_draft(state)
    assert draft is not None
    assert draft.lyric_writes == 1
    assert content.calls == 2
    assert await writes_on_record(sessions) == 2


@pytest.mark.parametrize("writes_per_day", [1])
async def test_a_spent_budget_refuses_the_reroll_and_never_calls_the_writer(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
) -> None:
    # Arrange — the walk to the preview spends the single write this account gets today.
    await walk_to_lyrics(dispatcher, bot)
    assert content.calls == 1

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — the vendor was not called again, and the customer was told why and until when.
    assert content.calls == 1
    assert refusal_text(limit=1, resets_at="2026-08-31") in screen_texts(session)


@pytest.mark.parametrize("writes_per_day", [1])
async def test_a_refused_reroll_leaves_the_lyric_they_already_have_and_its_buttons(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
) -> None:
    """A refused reroll is not a dead end: the words on screen are orderable as they stand."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — back on the preview, with the approve button that still works.
    assert await state.get_state() == Wizard.lyrics.state
    draft = await current_draft(state)
    assert draft is not None and draft.lyrics is not None
    actions = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert NavCB(action=NavAction.LYRICS_OK).pack() in actions


@pytest.mark.parametrize("writes_per_day", [1])
async def test_a_refused_first_write_ends_on_a_button_rather_than_a_dead_screen(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    budget: SqlLyricBudget,
    state: FSMContext,
) -> None:
    """With no lyric written yet the wizard cannot go forward today, so it says so and stops.

    Re-showing the step would land on the output-language picker (``resolve_step`` downgrades
    a lyric-less LYRICS), whose buttons lead straight back into this refusal — the dead end
    dressed as a working screen. The session is cleared and Start over is the one button
    offered, exactly as ``handlers.confirm._refuse`` does for the refusal only the calendar
    lifts.
    """
    # Arrange — the day is already spent before this customer's first write.
    await budget.claim_lyric_write(USER_ID, now=_NOON)

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert
    assert content.calls == 0
    assert await state.get_state() is None
    screen = session.last_screen
    assert screen.text == refusal_text(limit=1, resets_at="2026-08-31")
    expected = {data for _, data in buttons(start_over_keyboard(Language.EN))}
    assert {data for _, data in buttons(screen.reply_markup)} == expected


@pytest.mark.parametrize("writes_per_day", [1])
async def test_the_budget_opens_again_the_next_day(
    dispatcher: Dispatcher,
    bot: Bot,
    content: RecordingContentWriter,
    budget_clock: MovableClock,
) -> None:
    # Arrange — spent, and a reroll already refused.
    await walk_to_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())
    assert content.calls == 1

    # Act — the same account, one day on.
    budget_clock.advance(days=1)
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — the refusal really was for the day and not forever.
    assert content.calls == 2


@pytest.mark.parametrize("writes_per_day", [1])
async def test_a_counter_that_cannot_be_read_lets_the_customer_through(
    dispatcher: Dispatcher,
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
    content: RecordingContentWriter,
) -> None:
    """Fails OPEN, like every other customer-facing gate here. A blip must not stop the wizard."""
    # Arrange — the table is gone under the store.
    async with sessions.begin() as session:
        await session.execute(sa.text("DROP TABLE lyric_budgets"))

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — the write happened; MAX_LYRIC_WRITES and the inbound throttle still bound it.
    assert content.calls == 1


async def test_a_bot_with_no_budget_wired_writes_exactly_as_it_did_before(
    deps: BotDeps,
    bot: Bot,
    storage: MemoryStorage,
    content: RecordingContentWriter,
) -> None:
    """The shared ``deps`` fixture has no ``lyric_budget``; the whole existing suite runs so."""
    # Arrange
    unmetered = build_dispatcher(deps, storage=storage)

    # Act
    await walk_to_lyrics(unmetered, bot)

    # Assert
    assert content.calls == 1
    assert deps.lyric_budget is None


@pytest.mark.parametrize("language", list(Language))
def test_every_locale_renders_the_refusal_with_both_of_its_facts(language: Language) -> None:
    """Key-set parity is asserted in ``test_i18n``; this asserts the two placeholders LAND.

    A catalogue that carried the key but dropped ``{resets_at}`` would pass parity and still
    ship a refusal with no way out of it, which is the one thing this copy must never be.
    """
    # Arrange / Act
    text = translate("wizard.lyrics.budget_spent", language, limit=20, resets_at="2026-08-31")

    # Assert
    assert "20" in text
    assert "2026-08-31" in text
    assert "{" not in text
