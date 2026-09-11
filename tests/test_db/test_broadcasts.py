"""The campaign write side, where every test is really about one of two orderings.

**The first is the never-double-send rule.** ``claim_chunk`` moves a row to ``SENDING`` and
the caller commits that *before* the Telegram call; ``settle_recipient`` closes it after.
Everything that can go wrong in a broadcast is a violation of that order, so the tests below
attack it from the three sides it can be broken from:

* a row already in ``SENDING`` must never be claimed a second time — that is the crashed job's
  row, and re-claiming it is exactly the duplicate message the module refuses;
* two workers racing over one ledger must produce one sender per row and no more, which is
  asserted on ``attempts`` rather than on the returned tuples, because ``attempts`` counts
  winning ``UPDATE``s and cannot be made to agree by accident;
* an abandoned row ages to ``UNKNOWN`` and *not* back to ``PENDING``, so the hole in the
  counters is visible instead of being paid for with a second message.

**The second is that the audience is frozen at creation.** ``expand_chunk`` materialises it
once, resumably, through ``insert_or_ignore``; a replayed chunk is a database no-op. That is
asserted directly (the same page written twice inserts nothing the second time) because it is
the property every retry in this pipeline leans on and the only evidence for it is a number.

Rows are seeded directly rather than through a repository, for the reason every seed in this
package gives: the expectations are computed by hand from these instants, and a writer that
read its own clock would make them assert whatever it chose.

The genuinely simultaneous version of the claim race lives where it can: SQLite behind a
``StaticPool`` shares one connection, so ``asyncio.gather`` here interleaves await points
rather than connections (``test_postgres_integration.py`` says the same about the entitlement
race). What it does prove is that the conditional ``UPDATE`` — and not the ``SELECT`` that
precedes it — is what settles who owns a row, which is the part a refactor to
read-then-write would break.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bayram.contracts import (
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    is_err,
    is_ok,
)
from bayram.db.admin.page import Cursor
from bayram.db.broadcasts import (
    STALE_SENDING_ERROR_CODE,
    BroadcastActor,
    BroadcastBody,
    ExpansionChunk,
    NewBroadcast,
    SqlBroadcasts,
    age_stale_sending,
    cache_media_file_id,
    cancel,
    claim_chunk,
    create_broadcast,
    current_state,
    decode_expand_cursor,
    expand_chunk,
    mark_finished,
    mark_scheduled,
    mark_sending,
    pause,
    release_recipient,
    resume,
    revise_broadcast,
    roll_up_counters,
    settle_recipient,
)
from bayram.db.enums import AuditReasonCode
from bayram.db.models.broadcast import BroadcastRow
from bayram.db.models.broadcast_body import BroadcastBodyRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow
from bayram.db.models.user import UserRow
from bayram.errors import StorageError, ValidationError

pytestmark = pytest.mark.anyio

#: Mid-day, so a test that advances the clock cannot pass by landing on a boundary.
_NOON: Final[datetime] = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
_LATER: Final[datetime] = _NOON + timedelta(minutes=30)
#: When the seeded accounts joined. Each is a day older than the one before it, so the
#: expansion's ``(created_at DESC, id DESC)`` walk has a total order a reader can predict.
_JOINED: Final[datetime] = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

_FIRST_ACCOUNT: Final[int] = 90_001

#: The compiled document, stored verbatim on the campaign. Its shape belongs to
#: ``bayram.admin.schemas.segment``; this layer only has to keep it unchanged.
_SEGMENT: Final[dict[str, Any]] = {
    "root": {"match": "all", "rules": [{"field": "is_reachable", "op": "is_true"}]},
    "sort": {"key": "joined_at", "direction": "desc"},
}
_OPERATOR: Final[BroadcastActor] = BroadcastActor(admin_id=uuid4(), username="ops.dilnoza")
_SCHEDULER: Final[BroadcastActor] = BroadcastActor(admin_id=uuid4(), username="ops.rustam")


# ---------------------------------------------------------------------------
# Seeds — explicit values, no clocks, no policies
# ---------------------------------------------------------------------------
async def _seed_users(
    sessions: async_sessionmaker[AsyncSession],
    *,
    count: int = 3,
    first_id: int = _FIRST_ACCOUNT,
    language: Language = Language.UZ_LATN,
    is_blocked: bool = False,
    blocked_bot_at: datetime | None = None,
) -> tuple[int, ...]:
    """``count`` accounts, newest first, so the keyset walk visits ``first_id`` first."""
    async with sessions.begin() as session:
        for offset in range(count):
            session.add(
                UserRow(
                    id=uuid4(),
                    telegram_user_id=first_id + offset,
                    ui_language=language,
                    is_blocked=is_blocked,
                    last_seen_at=_NOON,
                    blocked_bot_at=blocked_bot_at,
                    created_at=_JOINED - timedelta(days=offset),
                    updated_at=_NOON,
                )
            )
    return tuple(first_id + offset for offset in range(count))


def _draft(
    *,
    bodies: tuple[BroadcastBody, ...] = (
        BroadcastBody(language=Language.UZ_LATN, text="Bugun kechqurun tizim yangilanadi."),
    ),
    audience_size: int = 3,
) -> NewBroadcast:
    return NewBroadcast(
        title="September outage notice",
        kind=BroadcastKind.SERVICE,
        segment=_SEGMENT,
        segment_hash="a" * 64,
        audience_size=audience_size,
        audience_evaluated_at=_NOON,
        bodies=bodies,
        scheduled_for=None,
        created_by=_OPERATOR,
        reason_code=AuditReasonCode.INCIDENT,
        reason_ref="INC-4417",
    )


async def _create(
    sessions: async_sessionmaker[AsyncSession], *, draft: NewBroadcast | None = None
) -> UUID:
    async with sessions.begin() as session:
        return await create_broadcast(session, draft=draft or _draft(), at=_NOON)


async def _seed_campaign(
    sessions: async_sessionmaker[AsyncSession], *, state: BroadcastState = BroadcastState.SENDING
) -> UUID:
    """A campaign in one state, written directly: the ledger tests are about recipients."""
    broadcast_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            BroadcastRow(
                id=broadcast_id,
                title="September outage notice",
                kind=BroadcastKind.SERVICE,
                state=state,
                segment=_SEGMENT,
                segment_hash="a" * 64,
                audience_size=0,
                audience_evaluated_at=_NOON,
                recipient_count=0,
                sent_count=0,
                failed_count=0,
                skipped_count=0,
                undeliverable_count=0,
                unknown_count=0,
                created_at=_NOON,
                updated_at=_NOON,
            )
        )
    return broadcast_id


async def _seed_recipients(
    sessions: async_sessionmaker[AsyncSession],
    *,
    broadcast_id: UUID,
    states: tuple[BroadcastRecipientState, ...],
    updated_at: datetime = _NOON,
) -> tuple[UUID, ...]:
    """One row per state, in order. Returns the ids so a test can settle a chosen one."""
    ids = tuple(uuid4() for _ in states)
    async with sessions.begin() as session:
        for offset, (recipient_id, state) in enumerate(zip(ids, states, strict=True)):
            session.add(
                BroadcastRecipientRow(
                    id=recipient_id,
                    broadcast_id=broadcast_id,
                    telegram_user_id=_FIRST_ACCOUNT + offset,
                    language=Language.UZ_LATN,
                    state=state,
                    attempts=0,
                    error_code=None,
                    settled_at=None,
                    created_at=_NOON + timedelta(seconds=offset),
                    updated_at=updated_at,
                )
            )
    return ids


# ---------------------------------------------------------------------------
# Reads used by the assertions
# ---------------------------------------------------------------------------
async def _campaign(sessions: async_sessionmaker[AsyncSession], broadcast_id: UUID) -> BroadcastRow:
    async with sessions() as session:
        row = await session.get(BroadcastRow, broadcast_id)
        assert row is not None
        return row


async def _bodies(
    sessions: async_sessionmaker[AsyncSession], broadcast_id: UUID
) -> list[BroadcastBodyRow]:
    async with sessions() as session:
        rows = await session.scalars(
            sa.select(BroadcastBodyRow)
            .where(BroadcastBodyRow.broadcast_id == broadcast_id)
            .order_by(BroadcastBodyRow.language)
        )
        return list(rows)


async def _recipients(
    sessions: async_sessionmaker[AsyncSession], broadcast_id: UUID
) -> list[BroadcastRecipientRow]:
    async with sessions() as session:
        rows = await session.scalars(
            sa.select(BroadcastRecipientRow)
            .where(BroadcastRecipientRow.broadcast_id == broadcast_id)
            .order_by(BroadcastRecipientRow.telegram_user_id)
        )
        return list(rows)


async def _expand_once(
    sessions: async_sessionmaker[AsyncSession],
    *,
    broadcast_id: UUID,
    cursor: Cursor | None = None,
    limit: int = 100,
    predicate: sa.ColumnElement[bool] | None = None,
    at: datetime = _NOON,
) -> ExpansionChunk:
    async with sessions.begin() as session:
        return await expand_chunk(
            session,
            broadcast_id=broadcast_id,
            predicate=predicate,
            cursor=cursor,
            at=at,
            limit=limit,
        )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
async def test_a_campaign_is_born_expanding_with_the_frozen_audience_on_the_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``DRAFT`` has no writer here: a campaign exists only once it has an audience."""
    # Act
    broadcast_id = await _create(sessions, draft=_draft(audience_size=4_112))

    # Assert
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.EXPANDING
    assert row.audience_size == 4_112, "the exact count the operator approved"
    assert row.audience_evaluated_at == _NOON
    assert row.segment == _SEGMENT, "stored verbatim, never a reference to be re-evaluated"
    assert row.recipient_count == 0, "nothing is materialised yet"
    assert row.expand_cursor is None
    assert row.started_at is None and row.finished_at is None
    assert row.created_by_admin_id == _OPERATOR.admin_id
    assert row.created_by_username == _OPERATOR.username
    assert row.reason_code is AuditReasonCode.INCIDENT
    assert row.reason_ref == "INC-4417"


async def test_the_bodies_land_with_no_file_id_even_when_an_image_was_uploaded(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``media_file_id`` is the worker's. A create path that could set it could quote an id
    nobody minted — the admin process has no bot token and cannot have made one."""
    # Arrange
    draft = _draft(
        bodies=(
            BroadcastBody(
                language=Language.UZ_LATN,
                text="Yangi yil aksiyasi.",
                media_storage_key="broadcasts/2026-09/banner.jpg",
                button_label="Batafsil",
                button_url="https://example.uz/aksiya",
            ),
            BroadcastBody(language=Language.RU, text="Новогодняя акция."),
        )
    )

    # Act
    broadcast_id = await _create(sessions, draft=draft)

    # Assert
    uz, ru = sorted(await _bodies(sessions, broadcast_id), key=lambda body: body.language.value)
    assert {uz.language, ru.language} == {Language.UZ_LATN, Language.RU}
    with_media = uz if uz.language is Language.UZ_LATN else ru
    assert with_media.media_storage_key == "broadcasts/2026-09/banner.jpg"
    assert with_media.media_file_id is None
    assert with_media.button_label == "Batafsil"
    assert with_media.button_url == "https://example.uz/aksiya"


async def test_a_revision_replaces_the_whole_body_set_and_leaves_the_audience_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A revision changes what is said, never who hears it — and a dropped language goes.

    The bodies are deleted and re-inserted rather than upserted per language precisely so
    this holds: an upsert would leave last week's Russian text attached to a campaign whose
    author removed it.
    """
    # Arrange
    await _seed_users(sessions, count=2)
    broadcast_id = await _create(
        sessions,
        draft=_draft(
            bodies=(
                BroadcastBody(language=Language.UZ_LATN, text="Eski matn."),
                BroadcastBody(language=Language.RU, text="Старый текст."),
            )
        ),
    )
    await _expand_once(sessions, broadcast_id=broadcast_id)
    before = await _campaign(sessions, broadcast_id)
    materialised = before.recipient_count

    # Act
    async with sessions.begin() as session:
        accepted = await revise_broadcast(
            session,
            broadcast_id=broadcast_id,
            title="September outage notice (corrected)",
            bodies=(BroadcastBody(language=Language.UZ_LATN, text="Yangi matn."),),
            at=_LATER,
        )

    # Assert
    assert accepted is True
    row = await _campaign(sessions, broadcast_id)
    assert row.title == "September outage notice (corrected)"
    assert row.segment == _SEGMENT
    assert row.recipient_count == materialised == 2, "the frozen audience is untouched"
    bodies = await _bodies(sessions, broadcast_id)
    assert [body.language for body in bodies] == [Language.UZ_LATN]
    assert bodies[0].text == "Yangi matn."
    assert len(await _recipients(sessions, broadcast_id)) == 2


async def test_a_campaign_that_has_started_sending_refuses_a_revision(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A revision after the first message would be two different texts under one title and
    one audit row.

    Guarded in the ``UPDATE`` and not by a read-then-write, for the reason every guard in
    this module is: the send job runs in another process, and the window between a ``SELECT``
    and an ``UPDATE`` is exactly long enough for the first message to go out under the old
    text.
    """
    # Arrange — an empty audience reaches READY in one pass, which is all this needs.
    broadcast_id = await _create(sessions)
    await _expand_once(sessions, broadcast_id=broadcast_id)
    async with sessions.begin() as session:
        assert await mark_sending(session, broadcast_id=broadcast_id, at=_NOON) is True

    # Act
    async with sessions.begin() as session:
        accepted = await revise_broadcast(
            session,
            broadcast_id=broadcast_id,
            title="too late",
            bodies=(BroadcastBody(language=Language.UZ_LATN, text="Yangi matn."),),
            at=_LATER,
        )

    # Assert
    assert accepted is False
    row = await _campaign(sessions, broadcast_id)
    assert row.title == "September outage notice", "nothing was written"
    assert [body.text for body in await _bodies(sessions, broadcast_id)] == [
        "Bugun kechqurun tizim yangilanadi."
    ]


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------
async def test_only_a_ready_campaign_can_be_scheduled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Authorising a campaign whose ledger is half-written would schedule a send against an
    audience that does not exist yet — the distinction ``EXPANDING`` and ``READY`` keep."""
    # Arrange
    await _seed_users(sessions, count=2)
    broadcast_id = await _create(sessions)

    # Act — while the audience is still being materialised.
    async with sessions.begin() as session:
        too_early = await mark_scheduled(
            session,
            broadcast_id=broadcast_id,
            scheduled_for=_LATER,
            scheduled_by=_SCHEDULER,
            at=_NOON,
        )

    # Assert
    assert too_early is False
    row = await _campaign(sessions, broadcast_id)
    assert row.scheduled_for is None and row.scheduled_by_username is None

    # Act — once the ledger is whole.
    await _expand_once(sessions, broadcast_id=broadcast_id)
    async with sessions.begin() as session:
        authorised = await mark_scheduled(
            session,
            broadcast_id=broadcast_id,
            scheduled_for=_LATER,
            scheduled_by=_SCHEDULER,
            at=_NOON,
            reason_code=AuditReasonCode.ROUTINE_OPS,
            reason_ref="OPS-19",
        )

    # Assert
    assert authorised is True
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.READY
    assert row.scheduled_for == _LATER
    assert row.scheduled_by_admin_id == _SCHEDULER.admin_id
    assert row.scheduled_by_username == _SCHEDULER.username
    assert row.reason_code is AuditReasonCode.ROUTINE_OPS
    assert row.reason_ref == "OPS-19"


async def test_the_start_is_stamped_once_and_a_replayed_job_does_not_move_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    broadcast_id = await _seed_campaign(sessions, state=BroadcastState.READY)

    # Act
    async with sessions.begin() as session:
        first = await mark_sending(session, broadcast_id=broadcast_id, at=_NOON)
    async with sessions.begin() as session:
        replay = await mark_sending(session, broadcast_id=broadcast_id, at=_LATER)

    # Assert — ``False`` is a replay finding the campaign already started, not a failure.
    assert (first, replay) == (True, False)
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.SENDING
    assert row.started_at == _NOON, "started_at records the first message, not the last restart"


async def test_pause_and_resume_move_only_between_sending_and_paused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    broadcast_id = await _seed_campaign(sessions, state=BroadcastState.READY)
    async with sessions.begin() as session:
        await mark_sending(session, broadcast_id=broadcast_id, at=_NOON)

    # Act
    async with sessions.begin() as session:
        paused = await pause(session, broadcast_id=broadcast_id, at=_LATER)
    async with sessions.begin() as session:
        paused_again = await pause(session, broadcast_id=broadcast_id, at=_LATER)
    async with sessions.begin() as session:
        resumed = await resume(session, broadcast_id=broadcast_id, at=_LATER)

    # Assert
    assert (paused, paused_again, resumed) == (True, False, True)
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.SENDING
    assert row.started_at == _NOON, "a campaign starts once; a resumed one has no new start"


async def test_a_campaign_can_be_cancelled_mid_expansion_and_the_chunk_learns_to_stop(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``accepted=False`` is how the expansion job hears about a cancel: the rows it wrote
    stay as evidence of what was about to happen, and no successor is enqueued."""
    # Arrange
    await _seed_users(sessions, count=4)
    broadcast_id = await _create(sessions)
    first = await _expand_once(sessions, broadcast_id=broadcast_id, limit=2)
    assert first.accepted is True and first.next_cursor is not None

    # Act
    async with sessions.begin() as session:
        stopped = await cancel(session, broadcast_id=broadcast_id, at=_LATER)
    resumed = await _expand_once(
        sessions, broadcast_id=broadcast_id, cursor=first.next_cursor, limit=2, at=_LATER
    )

    # Assert
    assert stopped is True
    assert resumed.accepted is False, "the campaign stopped wanting this chunk"
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.CANCELLED
    assert row.finished_at == _LATER
    assert row.recipient_count == 2, "the counter stops where the cancel found it"


async def test_a_finished_campaign_cannot_be_finished_a_second_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """What a replayed final chunk looks like, and it is not an error."""
    # Arrange
    broadcast_id = await _seed_campaign(sessions)

    # Act
    async with sessions.begin() as session:
        finished = await mark_finished(
            session, broadcast_id=broadcast_id, state=BroadcastState.COMPLETED, at=_NOON
        )
    async with sessions.begin() as session:
        replay = await mark_finished(
            session,
            broadcast_id=broadcast_id,
            state=BroadcastState.FAILED,
            at=_LATER,
            error_code="whatever",
        )

    # Assert
    assert (finished, replay) == (True, False)
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.COMPLETED
    assert row.finished_at == _NOON
    assert row.error_code is None


async def test_finishing_into_a_state_that_is_not_terminal_is_a_caller_bug(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """It raises where everything else here returns a boolean: every state at a call site in
    this module is a literal, so a wrong one is a typo and not bad input."""
    # Arrange
    broadcast_id = await _seed_campaign(sessions)

    # Act / Assert
    async with sessions.begin() as session:
        with pytest.raises(ValueError, match="terminal broadcast state"):
            await mark_finished(
                session, broadcast_id=broadcast_id, state=BroadcastState.PAUSED, at=_NOON
            )


# ---------------------------------------------------------------------------
# Expansion — the frozen audience, materialised
# ---------------------------------------------------------------------------
async def test_expansion_walks_the_account_keyset_and_flips_to_ready_on_the_last_page(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — five accounts, pages of two.
    accounts = await _seed_users(sessions, count=5)
    broadcast_id = await _create(sessions, draft=_draft(audience_size=len(accounts)))

    # Act
    chunks = []
    cursor: Cursor | None = None
    while True:
        chunk = await _expand_once(
            sessions, broadcast_id=broadcast_id, cursor=cursor, limit=2, at=_NOON
        )
        chunks.append(chunk)
        cursor = chunk.next_cursor
        if cursor is None:
            break

    # Assert — three passes, and the cursor survives the round trip through the column.
    assert [chunk.inserted for chunk in chunks] == [2, 2, 1]
    assert all(chunk.accepted for chunk in chunks)
    assert chunks[-1].is_complete is True
    row = await _campaign(sessions, broadcast_id)
    assert row.state is BroadcastState.READY
    assert row.expand_cursor is None, "a finished walk leaves no cursor behind"
    assert row.recipient_count == 5
    assert row.audience_size == 5
    materialised = await _recipients(sessions, broadcast_id)
    assert [row.telegram_user_id for row in materialised] == list(accounts)
    assert {row.state for row in materialised} == {BroadcastRecipientState.PENDING}
    assert {row.attempts for row in materialised} == {0}
    assert {row.settled_at for row in materialised} == {None}


async def test_the_persisted_cursor_is_the_one_a_resumed_job_reads_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The cursor is written by us and read back by us, so a token that will not parse is a
    corrupted row rather than a caller's mistake — which is why it raises."""
    # Arrange
    await _seed_users(sessions, count=3)
    broadcast_id = await _create(sessions)

    # Act
    chunk = await _expand_once(sessions, broadcast_id=broadcast_id, limit=2)
    row = await _campaign(sessions, broadcast_id)

    # Assert
    assert row.expand_cursor is not None
    assert decode_expand_cursor(row.expand_cursor) == chunk.next_cursor
    assert decode_expand_cursor(None) is None
    with pytest.raises(ValidationError):
        decode_expand_cursor("not-a-cursor-this-project-minted")


async def test_a_replayed_expansion_chunk_inserts_nothing_new(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """THE IDEMPOTENCY GUARANTEE the whole retry story rests on.

    ARQ replays a job on every deploy, so the same page will be written twice. It goes
    through ``insert_or_ignore`` against ``uq_broadcast_recipients_broadcast_id_telegram_
    user_id``: the second pass is a database no-op, not a branch somebody has to get right.

    The replay is deliberately of a MID-expansion page, so ``inserted == 0`` is the unique
    constraint doing its work rather than the campaign having left ``EXPANDING``.
    """
    # Arrange
    await _seed_users(sessions, count=5)
    broadcast_id = await _create(sessions)
    first = await _expand_once(sessions, broadcast_id=broadcast_id, limit=2)
    assert first.inserted == 2
    before = await _recipients(sessions, broadcast_id)

    # Act — the identical page, written again, exactly as a retried job would.
    replay = await _expand_once(sessions, broadcast_id=broadcast_id, limit=2, at=_LATER)

    # Assert
    assert replay.scanned == 2, "the same page was genuinely re-walked"
    assert replay.inserted == 0, "and none of it was written a second time"
    assert replay.accepted is True, "the campaign is still expanding; the successor stands"
    after = await _recipients(sessions, broadcast_id)
    assert [row.id for row in after] == [row.id for row in before], "the original rows kept"
    assert [row.created_at for row in after] == [row.created_at for row in before]
    row = await _campaign(sessions, broadcast_id)
    assert row.recipient_count == 2, "the running count did not double either"


async def test_a_blocked_account_is_materialised_as_a_settled_skip_rather_than_dropped(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ "Audience minus skips equals messages" has to be arithmetic a reader can do on the
    table, not a filter somebody remembers to apply. Both blocks are suppression signals and
    they are opposite facts: ``is_blocked`` is the operator's bar, ``blocked_bot_at`` is the
    customer's own — and there is no consent predicate anywhere, by scope.
    """
    # Arrange
    reachable = await _seed_users(sessions, count=1, first_id=90_101)
    barred = await _seed_users(sessions, count=1, first_id=90_102, is_blocked=True)
    left = await _seed_users(sessions, count=1, first_id=90_103, blocked_bot_at=_JOINED)
    broadcast_id = await _create(sessions)

    # Act
    chunk = await _expand_once(sessions, broadcast_id=broadcast_id)

    # Assert
    assert chunk.scanned == 3
    assert chunk.inserted == 3, "every scanned account gets a row, messageable or not"
    assert chunk.suppressed == 2
    by_account = {row.telegram_user_id: row for row in await _recipients(sessions, broadcast_id)}
    assert by_account[reachable[0]].state is BroadcastRecipientState.PENDING
    assert by_account[reachable[0]].settled_at is None
    for suppressed in (barred[0], left[0]):
        assert by_account[suppressed].state is BroadcastRecipientState.SKIPPED_BLOCKED
        assert by_account[suppressed].settled_at == _NOON, "a skip is settled when written"
    row = await _campaign(sessions, broadcast_id)
    assert row.recipient_count == 3


async def test_the_expansion_narrows_to_the_compiled_predicate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The predicate is ``compile_segment``'s output for the STORED document, compiled
    against ``audience_evaluated_at`` — the audience the operator approved."""
    # Arrange
    wanted = await _seed_users(sessions, count=2, first_id=90_201, language=Language.RU)
    await _seed_users(sessions, count=2, first_id=90_301, language=Language.EN)
    broadcast_id = await _create(sessions)

    # Act
    chunk = await _expand_once(
        sessions, broadcast_id=broadcast_id, predicate=UserRow.ui_language == Language.RU
    )

    # Assert
    assert chunk.inserted == 2
    materialised = await _recipients(sessions, broadcast_id)
    assert [row.telegram_user_id for row in materialised] == list(wanted)
    assert {row.language for row in materialised} == {Language.RU}, "snapshotted at expansion"


# ---------------------------------------------------------------------------
# The claim — the never-double-send rule
# ---------------------------------------------------------------------------
async def test_a_claim_marks_the_row_as_being_sent_before_anything_leaves(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The claim is a write, not a read, and ``attempts`` counts it."""
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    await _seed_recipients(
        sessions,
        broadcast_id=broadcast_id,
        states=(BroadcastRecipientState.PENDING, BroadcastRecipientState.PENDING),
    )

    # Act
    async with sessions.begin() as session:
        claimed = await claim_chunk(session, broadcast_id=broadcast_id, at=_LATER, limit=10)

    # Assert
    assert len(claimed) == 2
    assert {row.attempts for row in claimed} == {1}
    assert {row.language for row in claimed} == {Language.UZ_LATN}
    rows = await _recipients(sessions, broadcast_id)
    assert {row.state for row in rows} == {BroadcastRecipientState.SENDING}
    assert {row.settled_at for row in rows} == {None}, "claimed is not settled"


async def test_a_row_left_in_sending_by_a_dead_job_is_never_claimed_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """THE RULE ITSELF, stated as the only test that could catch its removal.

    A job killed between the claim and the Telegram call leaves its row in ``SENDING``. We do
    not know whether that message arrived, and the decision — taken once and deliberately —
    is that "we cannot say whether 3 of 40 000 were delivered" beats "3 people received it
    twice". So nothing here returns the row to the queue: a second claim finds nothing.
    """
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    await _seed_recipients(
        sessions, broadcast_id=broadcast_id, states=(BroadcastRecipientState.PENDING,)
    )
    async with sessions.begin() as session:
        await claim_chunk(session, broadcast_id=broadcast_id, at=_NOON, limit=10)

    # Act — the replayed job, asking for work on the same campaign.
    async with sessions.begin() as session:
        again = await claim_chunk(session, broadcast_id=broadcast_id, at=_LATER, limit=10)

    # Assert
    assert again == ()
    (row,) = await _recipients(sessions, broadcast_id)
    assert row.state is BroadcastRecipientState.SENDING
    assert row.attempts == 1, "one claim, therefore at most one message"


async def test_two_concurrent_claims_cannot_both_win_the_same_recipient(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """WHY THE CLAIM IS A CONDITIONAL UPDATE AND NOT A READ-THEN-WRITE.

    Two workers reading the same pending ledger see the same candidates; what settles
    ownership is the ``UPDATE … WHERE id = :id AND state = 'pending'`` whose ``rowcount`` of 1
    *is* the claim. The strongest evidence is ``attempts``: it is incremented by the winning
    statement only, so ``attempts == 1`` on every row means every row was won exactly once —
    an assertion that cannot be satisfied by accident the way comparing two result tuples
    could.

    A single ``UPDATE … WHERE id IN (…)`` would fail this by construction: its rowcount says
    how many rows were won and not which, and sending to a row this caller did not win is the
    double-send the module refuses.
    """
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    await _seed_recipients(
        sessions,
        broadcast_id=broadcast_id,
        states=(BroadcastRecipientState.PENDING,) * 4,
    )

    async def worker() -> tuple[UUID, ...]:
        async with sessions.begin() as session:
            claimed = await claim_chunk(session, broadcast_id=broadcast_id, at=_NOON, limit=4)
            return tuple(row.id for row in claimed)

    # Act — both ask for the whole ledger at once.
    first, second = await asyncio.gather(worker(), worker())

    # Assert
    assert set(first) & set(second) == set(), "no recipient belongs to two senders"
    assert len(set(first) | set(second)) == 4, "and none of them was dropped"
    rows = await _recipients(sessions, broadcast_id)
    assert {row.state for row in rows} == {BroadcastRecipientState.SENDING}
    assert {row.attempts for row in rows} == {1}, "exactly one winning UPDATE per row"


async def test_settling_is_the_claimant_s_alone_and_a_replay_cannot_rewrite_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    (pending_id,) = await _seed_recipients(
        sessions, broadcast_id=broadcast_id, states=(BroadcastRecipientState.PENDING,)
    )

    # Act — settling a row nobody claimed.
    async with sessions.begin() as session:
        unclaimed = await settle_recipient(
            session, recipient_id=pending_id, state=BroadcastRecipientState.SENT, at=_NOON
        )
    async with sessions.begin() as session:
        await claim_chunk(session, broadcast_id=broadcast_id, at=_NOON, limit=1)
    async with sessions.begin() as session:
        settled = await settle_recipient(
            session, recipient_id=pending_id, state=BroadcastRecipientState.SENT, at=_LATER
        )
    async with sessions.begin() as session:
        replay = await settle_recipient(
            session,
            recipient_id=pending_id,
            state=BroadcastRecipientState.FAILED,
            at=_LATER,
            error_code="telegram_forbidden",
        )

    # Assert
    assert (unclaimed, settled, replay) == (False, True, False)
    (row,) = await _recipients(sessions, broadcast_id)
    assert row.state is BroadcastRecipientState.SENT
    assert row.settled_at == _LATER, "one clock, stamped for every terminal state"
    assert row.error_code is None


async def test_settling_into_a_state_that_is_not_terminal_is_a_caller_bug(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    (recipient_id,) = await _seed_recipients(
        sessions, broadcast_id=broadcast_id, states=(BroadcastRecipientState.SENDING,)
    )

    # Act / Assert
    async with sessions.begin() as session:
        with pytest.raises(ValueError, match="terminal recipient state"):
            await settle_recipient(
                session,
                recipient_id=recipient_id,
                state=BroadcastRecipientState.PENDING,
                at=_NOON,
            )


async def test_releasing_a_claim_returns_the_row_but_remembers_the_attempt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The one route from ``SENDING`` back to ``PENDING``, for the caller that KNOWS the
    request never left the process. ``attempts`` counts claims and is not decremented, so a
    row that keeps being claimed and released is a row an operator can see."""
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    (recipient_id,) = await _seed_recipients(
        sessions, broadcast_id=broadcast_id, states=(BroadcastRecipientState.PENDING,)
    )
    async with sessions.begin() as session:
        await claim_chunk(session, broadcast_id=broadcast_id, at=_NOON, limit=1)

    # Act
    async with sessions.begin() as session:
        released = await release_recipient(session, recipient_id=recipient_id, at=_LATER)
    async with sessions.begin() as session:
        reclaimed = await claim_chunk(session, broadcast_id=broadcast_id, at=_LATER, limit=1)
    async with sessions.begin() as session:
        again = await release_recipient(session, recipient_id=recipient_id, at=_LATER)

    # Assert
    assert released is True
    assert [row.attempts for row in reclaimed] == [2]
    assert again is True
    (row,) = await _recipients(sessions, broadcast_id)
    assert row.state is BroadcastRecipientState.PENDING
    assert row.attempts == 2


async def test_a_row_abandoned_in_sending_ages_to_unknown_and_never_back_to_pending(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Where the never-double-send rule is paid for.

    ``UNKNOWN`` counts as neither sent nor failed and the panel renders it as its own number,
    so the hole is visible rather than rounded away. Returning the row to ``PENDING`` instead
    would message some customers twice, every deploy, forever.
    """
    # Arrange — one claim that died half an hour ago, one that is still in flight.
    broadcast_id = await _seed_campaign(sessions)
    stale_id, fresh_id = await _seed_recipients(
        sessions,
        broadcast_id=broadcast_id,
        states=(BroadcastRecipientState.SENDING, BroadcastRecipientState.SENDING),
    )
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BroadcastRecipientRow)
            .where(BroadcastRecipientRow.id == fresh_id)
            .values(updated_at=_LATER)
        )

    # Act — the lease ran from the claim, so the boundary is an instant the caller computes.
    async with sessions.begin() as session:
        retired = await age_stale_sending(
            session, broadcast_id=broadcast_id, older_than=_NOON + timedelta(minutes=5), at=_LATER
        )

    # Assert
    assert retired == 1
    by_id = {row.id: row for row in await _recipients(sessions, broadcast_id)}
    assert by_id[stale_id].state is BroadcastRecipientState.UNKNOWN
    assert by_id[stale_id].settled_at == _LATER
    assert by_id[stale_id].error_code == STALE_SENDING_ERROR_CODE
    assert by_id[fresh_id].state is BroadcastRecipientState.SENDING, "the live claim is not touched"
    assert BroadcastRecipientState.PENDING not in {row.state for row in by_id.values()}


# ---------------------------------------------------------------------------
# Counters and the body cache
# ---------------------------------------------------------------------------
async def test_the_rollup_recounts_the_ledger_rather_than_trusting_the_counters(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The rows are truth and the counters are a cache. Every state is seeded exactly once
    and the total is compared against the enum's own length, so adding a member without
    teaching the rollup about it fails here rather than losing possibly-delivered messages
    into a number nobody reconciles.
    """
    # Arrange — every state once, over a campaign whose stored counters are deliberately wrong.
    every_state = tuple(BroadcastRecipientState)
    broadcast_id = await _seed_campaign(sessions)
    await _seed_recipients(sessions, broadcast_id=broadcast_id, states=every_state)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == broadcast_id)
            .values(recipient_count=999, sent_count=999, unknown_count=0, updated_at=_NOON)
        )

    # Act
    async with sessions.begin() as session:
        tally = await roll_up_counters(session, broadcast_id=broadcast_id, at=_LATER)

    # Assert
    assert tally.total == len(every_state)
    assert (tally.pending, tally.sending) == (1, 1)
    assert tally.outstanding == 2, "a row still in SENDING is not settled and must hold the end"
    assert (tally.sent, tally.failed, tally.skipped) == (1, 1, 1)
    assert (tally.undeliverable, tally.unknown) == (1, 1)
    row = await _campaign(sessions, broadcast_id)
    assert row.recipient_count == len(every_state), "the stale 999 is replaced, not added to"
    assert (row.sent_count, row.failed_count, row.skipped_count) == (1, 1, 1)
    assert (row.undeliverable_count, row.unknown_count) == (1, 1)


async def test_the_media_file_id_is_cached_once_and_the_second_worker_keeps_the_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Guarded on ``media_storage_key IS NOT NULL AND media_file_id IS NULL``, mirroring
    ``ck_broadcast_bodies_media_pair`` — so two workers that both uploaded do not fight over
    which upload the rest of the campaign quotes."""
    # Arrange
    broadcast_id = await _create(
        sessions,
        draft=_draft(
            bodies=(
                BroadcastBody(
                    language=Language.UZ_LATN,
                    text="Rasm bilan.",
                    media_storage_key="broadcasts/2026-09/banner.jpg",
                ),
                BroadcastBody(language=Language.RU, text="Без картинки."),
            )
        ),
    )

    # Act
    async with sessions.begin() as session:
        stored = await cache_media_file_id(
            session,
            broadcast_id=broadcast_id,
            language=Language.UZ_LATN,
            file_id="AgACAgIAAxkBAAI",
            at=_LATER,
        )
    async with sessions.begin() as session:
        second_worker = await cache_media_file_id(
            session,
            broadcast_id=broadcast_id,
            language=Language.UZ_LATN,
            file_id="AgACAgIAAxkBAAI-other",
            at=_LATER,
        )
    async with sessions.begin() as session:
        without_media = await cache_media_file_id(
            session,
            broadcast_id=broadcast_id,
            language=Language.RU,
            file_id="AgACAgIAAxkBAAI",
            at=_LATER,
        )

    # Assert
    assert (stored, second_worker, without_media) == (True, False, False)
    by_language = {body.language: body for body in await _bodies(sessions, broadcast_id)}
    assert by_language[Language.UZ_LATN].media_file_id == "AgACAgIAAxkBAAI"
    assert by_language[Language.UZ_LATN].updated_at == _LATER, "the caller's clock, not ours"
    assert by_language[Language.RU].media_file_id is None


# ---------------------------------------------------------------------------
# The facade — the worker's never-throw boundary
# ---------------------------------------------------------------------------
async def test_the_facade_commits_the_claim_before_the_caller_can_touch_telegram(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One transaction per method is the contract the send pipeline depends on, not an
    implementation detail: the commit is what makes the claim visible to every other replica,
    and batching it with the send would reopen the window the state machine exists to close.
    """
    # Arrange
    broadcast_id = await _seed_campaign(sessions)
    await _seed_recipients(
        sessions, broadcast_id=broadcast_id, states=(BroadcastRecipientState.PENDING,) * 2
    )
    store = SqlBroadcasts(sessions)

    # Act
    claimed = await store.claim(broadcast_id, at=_NOON, limit=2)

    # Assert — a session that knows nothing of the facade's transaction already sees it.
    assert is_ok(claimed)
    assert len(claimed.value) == 2
    rows = await _recipients(sessions, broadcast_id)
    assert {row.state for row in rows} == {BroadcastRecipientState.SENDING}

    # Act — and the settlement is its own transaction, so a crash on the next message cannot
    # roll back the outcome of this one.
    settled = await store.settle(claimed.value[0].id, state=BroadcastRecipientState.SENT, at=_LATER)

    # Assert
    assert is_ok(settled) and settled.value is True
    by_id = {row.id: row for row in await _recipients(sessions, broadcast_id)}
    assert by_id[claimed.value[0].id].state is BroadcastRecipientState.SENT
    assert by_id[claimed.value[1].id].state is BroadcastRecipientState.SENDING


async def test_the_facade_walks_a_campaign_from_ready_to_completed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _seed_users(sessions, count=2)
    broadcast_id = await _create(sessions, draft=_draft(audience_size=2))
    store = SqlBroadcasts(sessions)

    # Act
    expanded = await store.expand(broadcast_id, predicate=None, cursor=None, at=_NOON, limit=10)
    started = await store.start(broadcast_id, at=_NOON)
    claimed = await store.claim(broadcast_id, at=_NOON, limit=10)
    assert is_ok(claimed)
    for recipient in claimed.value:
        assert is_ok(
            await store.settle(recipient.id, state=BroadcastRecipientState.SENT, at=_LATER)
        )
    rolled = await store.roll_up(broadcast_id, at=_LATER)
    finished = await store.finish(broadcast_id, state=BroadcastState.COMPLETED, at=_LATER)

    # Assert
    assert is_ok(expanded) and expanded.value.is_complete is True
    assert is_ok(started) and started.value is True
    assert is_ok(rolled) and rolled.value.outstanding == 0 and rolled.value.sent == 2
    assert is_ok(finished) and finished.value is True
    async with sessions() as session:
        assert await current_state(session, broadcast_id=broadcast_id) is BroadcastState.COMPLETED
    row = await _campaign(sessions, broadcast_id)
    assert row.sent_count == 2
    assert row.finished_at == _LATER


async def test_the_facade_returns_a_typed_error_instead_of_raising_at_the_worker(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """No job body carries a ``try``: a database that has gone away is an ``Err``, and the
    job decides whether that is worth a retry."""
    # Arrange — the schema goes with the connection this pool was holding.
    store = SqlBroadcasts(sessions)
    await engine.dispose()

    # Act
    result = await store.state_of(uuid4())

    # Assert
    assert is_err(result)
    assert isinstance(result.error, StorageError)
