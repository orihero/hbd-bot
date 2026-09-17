"""``generation_attempts``: the render ledger and the query the name ranking is tuned on."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from bayram.contracts import (
    CostSource,
    Language,
    NameCandidate,
    NameStrategy,
    is_ok,
)
from bayram.db.admin.sql import TimeWindow
from bayram.db.attempts import GenerationAttempt, GenerationAttemptRepository, StrategyStat
from bayram.db.enums import GenerationKind
from bayram.db.models.generation_attempt import TRANSCRIPT_LENGTH
from bayram.db.repository import SqlKitRepository
from tests.test_db.conftest import MovableClock, new_order


def _attempt(
    *,
    strategy: NameStrategy,
    is_verified: bool,
    rank: int = 0,
    kind: GenerationKind = GenerationKind.SONG,
    order_id: UUID | None = None,
) -> GenerationAttempt:
    return GenerationAttempt(
        kind=kind,
        order_id=order_id,
        provider="elevenlabs",
        language=Language.UZ_LATN,
        is_success=True,
        candidate=NameCandidate(text="Gulomjon", strategy=strategy, rank=rank),
        is_name_verified=is_verified,
        match_confidence=0.9 if is_verified else 0.2,
        stt_transcript="Gulomjon" if is_verified else "Gulamjan",
        cost_usd=0.30,
        cost_source=CostSource.DERIVED,
        latency_ms=4_200,
    )


async def test_record_persists_an_attempt_and_returns_its_id(
    attempts: GenerationAttemptRepository,
) -> None:
    # Arrange
    attempt = _attempt(strategy=NameStrategy.STRIPPED, is_verified=True)

    # Act
    result = await attempts.record(attempt)

    # Assert
    assert is_ok(result)
    assert result.value is not None


async def test_an_attempt_round_trips_with_its_candidate_intact(
    attempts: GenerationAttemptRepository, repository: SqlKitRepository
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    await attempts.record(
        _attempt(strategy=NameStrategy.CANONICAL, is_verified=True, rank=1, order_id=order.id)
    )

    # Act
    result = await attempts.list_for_order(order.id)

    # Assert
    assert is_ok(result)
    stored = result.value[0]
    assert stored.candidate is not None
    assert stored.candidate.strategy is NameStrategy.CANONICAL
    assert stored.candidate.rank == 1
    assert stored.cost_source is CostSource.DERIVED


async def test_an_attempt_can_be_recorded_before_an_order_exists(
    attempts: GenerationAttemptRepository,
) -> None:
    # Arrange — a name preview happens during intake, before any order row.
    preview = _attempt(
        strategy=NameStrategy.PHONETIC, is_verified=False, kind=GenerationKind.NAME_PREVIEW
    )

    # Act
    result = await attempts.record(preview)

    # Assert
    assert is_ok(result)


async def test_list_for_order_returns_empty_for_an_order_with_no_attempts(
    attempts: GenerationAttemptRepository,
) -> None:
    # Act
    result = await attempts.list_for_order(uuid4())

    # Assert
    assert is_ok(result)
    assert result.value == ()


async def test_strategy_stats_ranks_the_better_orthography_first(
    attempts: GenerationAttemptRepository,
) -> None:
    # Arrange — this is the bake-off, run continuously against real traffic.
    for _ in range(4):
        await attempts.record(_attempt(strategy=NameStrategy.STRIPPED, is_verified=True))
    await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=True))
    for _ in range(3):
        await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=False))

    # Act
    result = await attempts.strategy_stats()

    # Assert
    assert is_ok(result)
    ranked = result.value
    assert ranked[0].strategy is NameStrategy.STRIPPED
    assert ranked[0].verification_rate == 1.0
    assert ranked[1].strategy is NameStrategy.ASCII
    assert ranked[1].verification_rate == 0.25


async def test_strategy_stats_ignores_renders_that_were_never_verified(
    attempts: GenerationAttemptRepository,
) -> None:
    # Arrange — verification can be disabled by config; those rows say nothing.
    await attempts.record(
        GenerationAttempt(
            kind=GenerationKind.SONG,
            provider="elevenlabs",
            is_success=True,
            candidate=NameCandidate(text="Gulomjon", strategy=NameStrategy.STRIPPED, rank=0),
            is_name_verified=None,
        )
    )

    # Act
    result = await attempts.strategy_stats()

    # Assert
    assert is_ok(result)
    assert result.value == ()


async def test_strategy_stats_is_empty_before_anything_is_recorded(
    attempts: GenerationAttemptRepository,
) -> None:
    # Act
    result = await attempts.strategy_stats()

    # Assert
    assert is_ok(result)
    assert result.value == ()


async def test_strategy_stats_can_be_narrowed_to_a_window_so_the_ranking_is_current(
    attempts: GenerationAttemptRepository, clock: MovableClock
) -> None:
    """The bake-off answers "what should ``BAYRAM_NAME_CANDIDATE_ORDER`` be **now**".

    ASCII won a month ago and has been losing since. Over the whole record it still leads,
    which is a finding about a pipeline that no longer exists; over this month it does not.
    """
    # Arrange — last month.
    for _ in range(2):
        await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=True))
    # Arrange — this month.
    start = clock.advance(days=30)
    await attempts.record(_attempt(strategy=NameStrategy.STRIPPED, is_verified=True))
    await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=False))

    # Act
    windowed = await attempts.strategy_stats(
        window=TimeWindow(start=start, end=start + timedelta(days=1))
    )
    all_time = await attempts.strategy_stats()

    # Assert
    assert is_ok(windowed)
    assert [(stat.strategy, stat.attempts, stat.verified) for stat in windowed.value] == [
        (NameStrategy.STRIPPED, 1, 1),
        (NameStrategy.ASCII, 1, 0),
    ]
    assert is_ok(all_time)
    # 2 of 3 all-time, which outranks STRIPPED's 1 of 1 on neither rate nor recency — the
    # point being that the two answers differ, and only one of them is about today.
    assert [(stat.strategy, stat.attempts, stat.verified) for stat in all_time.value] == [
        (NameStrategy.STRIPPED, 1, 1),
        (NameStrategy.ASCII, 3, 2),
    ]


async def test_the_window_is_half_open_so_two_consecutive_windows_never_double_count(
    attempts: GenerationAttemptRepository, clock: MovableClock
) -> None:
    """``[start, end)`` — the row landing exactly on a boundary belongs to one window only."""
    # Arrange — one verdict at the boundary instant, one a second later.
    boundary = clock.now
    await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=True))
    later = clock.advance(seconds=1)
    await attempts.record(_attempt(strategy=NameStrategy.ASCII, is_verified=True))

    # Act
    before = await attempts.strategy_stats(
        window=TimeWindow(start=boundary - timedelta(seconds=1), end=boundary)
    )
    at_and_after = await attempts.strategy_stats(
        window=TimeWindow(start=boundary, end=later + timedelta(seconds=1))
    )

    # Assert — the boundary row is in the second window, not in both and not in neither.
    assert is_ok(before)
    assert before.value == ()
    assert is_ok(at_and_after)
    assert at_and_after.value[0].attempts == 2


def test_verification_rate_is_zero_when_no_attempts_were_made() -> None:
    # Arrange
    stat = StrategyStat(strategy=NameStrategy.PHONETIC, attempts=0, verified=0)

    # Act / Assert — a division, not a crash.
    assert stat.verification_rate == 0.0


def test_a_generation_attempt_is_immutable() -> None:
    # Arrange
    attempt = _attempt(strategy=NameStrategy.STRIPPED, is_verified=True)

    # Act / Assert
    try:
        attempt.attempt = 5  # type: ignore[misc]
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("GenerationAttempt must be frozen")


async def test_a_song_length_transcript_is_truncated_rather_than_failing_the_order(
    attempts: GenerationAttemptRepository, repository: SqlKitRepository
) -> None:
    """A diagnostic column must never destroy a kit the customer already paid for.

    ``stt_transcript`` was sized for "a transcript of a name chunk, not of a song" — an
    assumption that held only while inpainting could isolate the name chunk. Inpainting is
    enterprise-gated, so verification transcribes the whole track and the real transcript
    ran to ~700 characters. A live order died at the persisting stage with
    ``value too long for type character varying(200)`` AFTER the song and all three
    greetings had been generated and paid for.

    The unit suite runs on SQLite, which does not enforce ``varchar`` length, so the
    truncation is asserted directly rather than left to the database to police.
    """
    # Arrange — longer than any column bound we would pick.
    order = new_order()
    await repository.create_order(order)
    transcript = "Bugun quyosh charaqlab turar bogʻlarda. " * 200

    # Act
    result = await attempts.record(
        _attempt(strategy=NameStrategy.STRIPPED, is_verified=True, order_id=order.id).model_copy(
            update={"stt_transcript": transcript}
        )
    )

    # Assert
    assert is_ok(result)
    stored = await attempts.list_for_order(order.id)
    assert is_ok(stored)
    kept = stored.value[0].stt_transcript
    assert kept is not None
    assert len(kept) <= TRANSCRIPT_LENGTH
    assert transcript.startswith(kept)
