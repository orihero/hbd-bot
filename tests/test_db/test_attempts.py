"""``generation_attempts``: the render ledger and the query the name ranking is tuned on."""

from __future__ import annotations

from uuid import UUID, uuid4

from hbd.contracts import (
    CostSource,
    Language,
    NameCandidate,
    NameStrategy,
    is_ok,
)
from hbd.db.attempts import GenerationAttempt, GenerationAttemptRepository, StrategyStat
from hbd.db.enums import GenerationKind
from hbd.db.repository import SqlKitRepository
from tests.test_db.conftest import new_order


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
