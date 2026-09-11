"""``vendor_balances``: the column-selective failure upsert, and the measured divisor.

**The central property of this whole workstream is asserted in
:func:`test_a_failed_poll_keeps_the_last_known_balance_and_ages_it`.** The tile an operator
reads to decide whether to top up before New Year is most needed at the moment the vendor is
unreachable — and the obvious one-statement upsert, passing ``None`` for everything it did
not measure, blanks the balance on the first 500. So the writer has TWO statements, the
failure one names a strict subset of columns, and the set-difference between them IS the
design. A refactor that generated one from the other by filtering a dict would pass every
other test in this file and fail that one.

The rest follows from the same principle in different places:

* three states, three screens — an ABSENT row means this deployment does not poll that
  vendor, a row with ``fetched_at`` NULL means we asked and were never answered, and a row
  with a stale ``fetched_at`` means here is the last figure and it is N hours old;
* ``consecutive_failures`` is a COUNT, so zero on it is a measurement and the null-never-zero
  rule does not apply — but it increments as a column expression, so two workers racing one
  window cannot lose a count to a read-modify-write;
* the songs-remaining divisor is MEASURED and never configured. With the shipped rate card
  every OpenRouter ``cost_usd`` is NULL, so the divisor is ``None``, all three estimate
  columns stay NULL together, and the tile reads "needs balances" rather than inventing a
  number out of a rate that was never a per-song rate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    BalanceEstimateBasis,
    BalanceUnit,
    CostSource,
    Language,
    OrderState,
    Vendor,
    VendorOperation,
)
from bayram.db.admin.balances import has_polled_vendor_balances, vendor_balances
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow
from bayram.db.models.vendor_balance import VendorBalanceRow
from bayram.db.models.vendor_usage import VendorUsageRow
from bayram.db.vendor_balances import measure_per_song_rate, record_probe
from bayram.runtime.vendor_balance_probes import (
    OPENROUTER_PROBE_NAME,
    BalanceProbe,
    BalanceReading,
)

pytestmark = pytest.mark.anyio

_T0: Final[datetime] = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
_T1: Final[datetime] = _T0 + timedelta(hours=1)
_T2: Final[datetime] = _T0 + timedelta(hours=2)
_T3: Final[datetime] = _T0 + timedelta(hours=3)

_WINDOW_DAYS: Final[int] = 30


def _ok(
    *,
    vendor: Vendor = Vendor.OPENROUTER,
    is_fallback: bool = False,
    unit: BalanceUnit = BalanceUnit.USD,
    **reading: Any,
) -> BalanceProbe:
    """A probe that measured something."""
    return BalanceProbe(
        vendor=vendor,
        is_fallback=is_fallback,
        provider=OPENROUTER_PROBE_NAME,
        balance_unit=unit,
        reading=BalanceReading(**reading),
        http_status=200,
    )


def _failed(
    *,
    vendor: Vendor = Vendor.OPENROUTER,
    is_fallback: bool = False,
    http_status: int | None = 500,
    error_code: str = "UPSTREAM_5XX",
) -> BalanceProbe:
    """A probe that could not measure. Carries why, and not one quantity."""
    return BalanceProbe(
        vendor=vendor,
        is_fallback=is_fallback,
        provider=OPENROUTER_PROBE_NAME,
        balance_unit=BalanceUnit.USD,
        reading=None,
        http_status=http_status,
        error_code=error_code,
    )


async def _rows(sessions: async_sessionmaker[AsyncSession]) -> list[VendorBalanceRow]:
    async with sessions() as session:
        rows = await session.scalars(
            sa.select(VendorBalanceRow).order_by(
                VendorBalanceRow.vendor, VendorBalanceRow.is_fallback
            )
        )
        return list(rows)


async def _only(sessions: async_sessionmaker[AsyncSession]) -> VendorBalanceRow:
    rows = await _rows(sessions)
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------------------
# THE CENTRAL TEST
# ---------------------------------------------------------------------------
async def test_a_failed_poll_keeps_the_last_known_balance_and_ages_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one good measurement at T0.
    await record_probe(
        sessions,
        probe=_ok(balance_remaining=12.40, balance_total=50.0, balance_used=37.60),
        divisor=None,
        at=_T0,
    )

    # Act — the vendor goes down an hour later.
    await record_probe(sessions, probe=_failed(), divisor=None, at=_T1)

    # Assert — the number an operator most needs is exactly the number that survives. Both
    # clocks are on the row and they have now diverged: ``fetched_at`` still says when the
    # figure was ANSWERED, ``checked_at`` says when we last ASKED, and the difference is the
    # staleness the panel renders. A single "as of" would show a one-hour-old figure as
    # fresh; nulling the balance would make an outage indistinguishable from a deployment
    # that has never polled at all.
    row = await _only(sessions)
    assert row.balance_remaining == pytest.approx(12.40)
    assert row.balance_total == pytest.approx(50.0)
    assert row.balance_used == pytest.approx(37.60)
    assert row.fetched_at == _T0
    assert row.checked_at == _T1
    assert row.is_last_poll_ok is False
    assert row.error_code == "UPSTREAM_5XX"
    assert row.http_status == 500
    assert row.consecutive_failures == 1


async def test_a_second_failure_counts_up_while_the_balance_still_stands(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await record_probe(sessions, probe=_ok(balance_remaining=12.40), divisor=None, at=_T0)
    await record_probe(sessions, probe=_failed(), divisor=None, at=_T1)

    # Act
    await record_probe(sessions, probe=_failed(http_status=None, error_code="UPSTREAM_TIMEOUT"), divisor=None, at=_T2)

    # Assert — the count is what tells an operator how long "the last known figure" has been
    # the only figure. It increments as a column expression rather than a read-modify-write,
    # so two workers racing one window cannot lose a count.
    row = await _only(sessions)
    assert row.consecutive_failures == 2
    assert row.balance_remaining == pytest.approx(12.40)
    assert row.fetched_at == _T0
    assert row.checked_at == _T2
    assert row.http_status is None
    assert row.error_code == "UPSTREAM_TIMEOUT"


async def test_a_recovery_clears_the_failure_state_and_moves_the_measurement_clock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a measurement, then two failures.
    await record_probe(sessions, probe=_ok(balance_remaining=12.40), divisor=None, at=_T0)
    await record_probe(sessions, probe=_failed(), divisor=None, at=_T1)
    await record_probe(sessions, probe=_failed(), divisor=None, at=_T2)

    # Act — the vendor comes back with a smaller balance.
    await record_probe(sessions, probe=_ok(balance_remaining=9.10), divisor=None, at=_T3)

    # Assert — the counter resets, the error is cleared, and both clocks converge again.
    row = await _only(sessions)
    assert row.consecutive_failures == 0
    assert row.error_code is None
    assert row.is_last_poll_ok is True
    assert row.balance_remaining == pytest.approx(9.10)
    assert row.fetched_at == _T3
    assert row.checked_at == _T3


async def test_a_first_ever_probe_that_fails_is_a_row_full_of_nothing_and_says_why(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — the "tried and never succeeded" state, which is a different screen from an
    # absent row (this deployment does not poll that vendor) and from a stale one.
    await record_probe(
        sessions, probe=_failed(http_status=401, error_code="CONFIG_INVALID"), divisor=None, at=_T0
    )

    # Assert — every quantity NULL and ``fetched_at`` NULL, which satisfies
    # ``ck_vendor_balances_a_measured_balance_carries_its_time`` trivially. Not a zero
    # anywhere: a zero balance and an unmeasured one lead to opposite operator actions.
    row = await _only(sessions)
    assert row.fetched_at is None
    assert row.balance_remaining is None
    assert row.balance_total is None
    assert row.balance_used is None
    assert row.songs_remaining is None
    assert row.checked_at == _T0
    assert row.is_last_poll_ok is False
    assert row.error_code == "CONFIG_INVALID"
    assert row.consecutive_failures == 1


async def test_a_success_that_measured_nothing_records_the_time_it_measured_nothing_at(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — a 200 whose fields the vendor has renamed. The probe degrades to a
    # SUCCESS carrying an empty reading rather than to a failure, so the row must be able to
    # hold "we were answered, and the answer contained no quantity".
    await record_probe(sessions, probe=_ok(), divisor=None, at=_T0)

    # Assert — this is the legal edge the CHECK must NOT reject, and the reason it is an
    # implication (a measured balance carries a time) rather than a biconditional.
    row = await _only(sessions)
    assert row.fetched_at == _T0
    assert row.balance_remaining is None
    assert row.is_last_poll_ok is True


# ---------------------------------------------------------------------------
# One row per billing account
# ---------------------------------------------------------------------------
async def test_two_polls_of_one_account_leave_one_row_and_the_fallback_is_its_own(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — the primary OpenRouter account twice, and the SECOND one once. Both
    # LLM adapters report the same vendor name, so without ``is_fallback`` in the primary key
    # the two billing relationships would be one row overwriting itself.
    await record_probe(sessions, probe=_ok(balance_remaining=1.0), divisor=None, at=_T0)
    await record_probe(sessions, probe=_ok(balance_remaining=2.0), divisor=None, at=_T1)
    await record_probe(
        sessions, probe=_ok(is_fallback=True, balance_remaining=8.0), divisor=None, at=_T1
    )
    await record_probe(
        sessions,
        probe=_ok(vendor=Vendor.ELEVENLABS, unit=BalanceUnit.CHARACTERS, balance_remaining=380_000.0),
        divisor=None,
        at=_T1,
    )

    # Assert
    rows = await _rows(sessions)
    assert [(row.vendor, row.is_fallback) for row in rows] == [
        (Vendor.ELEVENLABS, False),
        (Vendor.OPENROUTER, False),
        (Vendor.OPENROUTER, True),
    ]
    primary = next(row for row in rows if row.vendor is Vendor.OPENROUTER and not row.is_fallback)
    assert primary.balance_remaining == pytest.approx(2.0)


async def test_the_reader_orders_the_strip_and_reports_whether_anything_was_ever_polled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the capability probe first, on an empty table.
    async with sessions() as session:
        assert await has_polled_vendor_balances(session) is False
        assert await vendor_balances(session) == ()

    await record_probe(
        sessions, probe=_ok(is_fallback=True, balance_remaining=8.0), divisor=None, at=_T0
    )
    await record_probe(sessions, probe=_failed(), divisor=None, at=_T0)

    # Act
    async with sessions() as session:
        states = await vendor_balances(session)
        polled = await has_polled_vendor_balances(session)

    # Assert — a fixed strip on the screen must not reorder between polls, and a row that
    # was never measured serialises its balance as absent rather than as zero.
    assert polled is True
    assert [(state.vendor, state.is_fallback) for state in states] == [
        (Vendor.OPENROUTER, False),
        (Vendor.OPENROUTER, True),
    ]
    assert states[0].balance_remaining is None
    assert states[0].is_last_poll_ok is False
    assert states[1].balance_remaining == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# The constraints
# ---------------------------------------------------------------------------
async def _insert(sessions: async_sessionmaker[AsyncSession], **values: Any) -> None:
    base: dict[str, Any] = {
        "vendor": Vendor.OPENROUTER,
        "is_fallback": False,
        "provider": OPENROUTER_PROBE_NAME,
        "balance_unit": BalanceUnit.USD,
        "checked_at": _T0,
        "is_last_poll_ok": True,
        "consecutive_failures": 0,
        "created_at": _T0,
        "updated_at": _T0,
    }
    async with sessions.begin() as session:
        await session.execute(sa.insert(VendorBalanceRow).values({**base, **values}))


@pytest.mark.parametrize(
    "values",
    [
        pytest.param(
            {"songs_remaining": 40, "per_song_rate": 0.3},
            id="an estimate with no basis is unreadable",
        ),
        pytest.param(
            {"per_song_rate": 0.3, "estimate_basis": BalanceEstimateBasis.TRAILING_SPEND_USD},
            id="a divisor with no answer",
        ),
        pytest.param(
            {"songs_remaining": 40, "estimate_basis": BalanceEstimateBasis.TRAILING_SPEND_USD},
            id="an answer nobody can reproduce",
        ),
        pytest.param(
            {"balance_remaining": 12.40},
            id="a measured balance with no time is a figure of unknown age",
        ),
        pytest.param({"consecutive_failures": -1}, id="a count below zero"),
    ],
)
async def test_the_database_refuses_a_shape_no_writer_should_produce(
    sessions: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    # Enforced by the database rather than by three call sites remembering. Nobody can tell a
    # figure derived from measured USD spend from one derived from TTS characters that
    # exclude the music leg, so the three estimate columns move together or none of them do.
    with pytest.raises(IntegrityError):
        await _insert(sessions, **values)


async def test_a_time_with_no_quantities_is_legal_because_a_vendor_may_answer_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # The edge the implication must not reject — see
    # ``test_a_success_that_measured_nothing_records_the_time_it_measured_nothing_at``.
    await _insert(sessions, fetched_at=_T0)

    assert (await _only(sessions)).fetched_at == _T0


# ---------------------------------------------------------------------------
# The measured divisor
# ---------------------------------------------------------------------------
async def _seed_delivered_order(
    session: AsyncSession, *, created_at: datetime, who: int = 95_001
) -> OrderRow:
    user = UserRow(
        id=uuid4(),
        telegram_user_id=who,
        ui_language=Language.UZ_LATN,
        is_blocked=False,
        last_seen_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    await session.flush()
    order = OrderRow(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=who,
        state=OrderState.DELIVERED,
        correlation_id="corr",
        is_paid=True,
        delivered_at=created_at + timedelta(minutes=4),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(order)
    await session.flush()
    return order


def _usage_row(**values: Any) -> VendorUsageRow:
    base: dict[str, Any] = {
        "id": uuid4(),
        "vendor": Vendor.OPENROUTER,
        "operation": VendorOperation.CHAT_COMPLETION,
        "provider": "openai-compat",
        "is_fallback": False,
        "is_fake": False,
        "is_success": True,
        "created_at": _T0,
    }
    return VendorUsageRow(**{**base, **values})


async def test_the_divisor_is_measured_spend_over_the_orders_it_was_spent_on(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two delivered orders inside the window, three priced LLM calls between them.
    async with sessions.begin() as session:
        first = await _seed_delivered_order(session, created_at=_T0 - timedelta(days=2))
        second = await _seed_delivered_order(
            session, created_at=_T0 - timedelta(days=3), who=95_002
        )
        for order_id, cost in ((first.id, 0.40), (first.id, 0.20), (second.id, 0.60)):
            session.add(
                _usage_row(order_id=order_id, cost_usd=cost, cost_source=CostSource.VENDOR_REPORTED)
            )

    # Act
    async with sessions() as session:
        measured = await measure_per_song_rate(
            session,
            vendor=Vendor.OPENROUTER,
            is_fallback=False,
            window_days=_WINDOW_DAYS,
            now=_T0,
        )

    # Assert — SUM(cost) / COUNT(DISTINCT order_id), and the basis travels with it. A divisor
    # whose provenance is unknown cannot be trusted differently from one whose provenance is
    # known, which is the whole argument for the enum.
    assert measured is not None
    rate, basis = measured
    assert rate == pytest.approx(1.20 / 2)
    assert basis is BalanceEstimateBasis.TRAILING_SPEND_USD


async def test_the_shipped_rate_card_produces_no_divisor_and_therefore_no_estimate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a delivered order with LLM calls that were never priced. This is not an edge
    # case: all four ``BAYRAM_LLM_*_USD_PER_MILLION_*`` ship at 0.0, so every OpenRouter
    # ``cost_usd`` in production today is NULL.
    async with sessions.begin() as session:
        order = await _seed_delivered_order(session, created_at=_T0 - timedelta(days=1))
        session.add(_usage_row(order_id=order.id))

    # Act
    async with sessions() as session:
        measured = await measure_per_song_rate(
            session, vendor=Vendor.OPENROUTER, is_fallback=False, window_days=_WINDOW_DAYS, now=_T0
        )

    # Assert — ``None``, never 0.0. A zero rate would be a division by nothing one line later
    # and an infinite songs-remaining figure on the tile.
    assert measured is None


async def test_a_window_with_no_delivered_order_is_a_division_by_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — spend, but the order it belongs to was delivered long before the window.
    async with sessions.begin() as session:
        order = await _seed_delivered_order(session, created_at=_T0 - timedelta(days=90))
        session.add(
            _usage_row(order_id=order.id, cost_usd=0.5, cost_source=CostSource.VENDOR_REPORTED)
        )

    # Act
    async with sessions() as session:
        measured = await measure_per_song_rate(
            session, vendor=Vendor.OPENROUTER, is_fallback=False, window_days=_WINDOW_DAYS, now=_T0
        )

    # Assert
    assert measured is None


async def test_a_fake_run_never_moves_the_divisor_an_operator_tops_up_on(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one real priced call and one fake one, both on delivered orders in window.
    async with sessions.begin() as session:
        real = await _seed_delivered_order(session, created_at=_T0 - timedelta(days=1))
        fake = await _seed_delivered_order(
            session, created_at=_T0 - timedelta(days=1), who=95_003
        )
        session.add(
            _usage_row(order_id=real.id, cost_usd=1.0, cost_source=CostSource.VENDOR_REPORTED)
        )
        session.add(
            _usage_row(
                order_id=fake.id,
                cost_usd=99.0,
                cost_source=CostSource.VENDOR_REPORTED,
                is_fake=True,
            )
        )

    # Act
    async with sessions() as session:
        measured = await measure_per_song_rate(
            session, vendor=Vendor.OPENROUTER, is_fallback=False, window_days=_WINDOW_DAYS, now=_T0
        )

    # Assert — one real call over one real order. A demo must not decide whether somebody
    # buys credit.
    assert measured is not None
    assert measured[0] == pytest.approx(1.0)


async def test_the_elevenlabs_divisor_counts_characters_and_names_that_in_its_basis(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a TTS leg that billed characters, and a MUSIC leg on the same order that
    # drew on the same credit pool while recording ``audio_ms`` instead. The second is
    # invisible to this divisor, which is precisely why the basis says "tts" out loud.
    async with sessions.begin() as session:
        order = await _seed_delivered_order(session, created_at=_T0 - timedelta(days=1))
        session.add(
            _usage_row(
                vendor=Vendor.ELEVENLABS,
                operation=VendorOperation.SPEECH_SYNTHESIS,
                provider="elevenlabs_tts",
                order_id=order.id,
                billed_characters=1_200,
            )
        )
        session.add(
            _usage_row(
                vendor=Vendor.ELEVENLABS,
                operation=VendorOperation.MUSIC_COMPOSE,
                provider="elevenlabs_music",
                order_id=order.id,
                audio_ms=90_000,
            )
        )

    # Act
    async with sessions() as session:
        measured = await measure_per_song_rate(
            session, vendor=Vendor.ELEVENLABS, is_fallback=False, window_days=_WINDOW_DAYS, now=_T0
        )

    # Assert — the divisor UNDERCOUNTS, so the songs-remaining figure built on it is an UPPER
    # BOUND: it promises more songs than the account can pay for, which is the one direction
    # of error this metric must never make silently. The enum member is how the schema
    # carries that warning to a reader.
    assert measured is not None
    divisor, basis = measured
    assert divisor == pytest.approx(1_200.0)
    assert basis is BalanceEstimateBasis.TRAILING_TTS_CHARACTERS


async def test_a_vendor_with_no_measured_quantity_gets_no_divisor_at_all(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # There is nothing to divide, and inventing one would be worse than an empty tile.
    async with sessions() as session:
        assert (
            await measure_per_song_rate(
                session,
                vendor=Vendor.FAKE,
                is_fallback=False,
                window_days=_WINDOW_DAYS,
                now=_T0,
            )
            is None
        )


async def test_the_songs_remaining_figure_floors_and_never_rounds_up(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a balance that would round UP to four songs and can only pay for three.
    divisor = (0.30, BalanceEstimateBasis.TRAILING_SPEND_USD)

    # Act
    await record_probe(
        sessions, probe=_ok(balance_remaining=1.19), divisor=divisor, at=_T0
    )

    # Assert — a rounded-up "1 song remaining" on a balance that cannot pay for one is
    # exactly the failure this tile exists to prevent. All three estimate columns are
    # written together, which is what the CHECK constraint requires.
    row = await _only(sessions)
    assert row.songs_remaining == 3
    assert row.per_song_rate == pytest.approx(0.30)
    assert row.estimate_basis is BalanceEstimateBasis.TRAILING_SPEND_USD


async def test_a_divisor_with_no_balance_to_divide_writes_no_estimate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — an uncapped key: we know what a song costs and not what is left.
    await record_probe(
        sessions,
        probe=_ok(is_unbounded=True),
        divisor=(0.30, BalanceEstimateBasis.TRAILING_SPEND_USD),
        at=_T0,
    )

    # Assert — all three estimate columns stay NULL together rather than two of them being
    # written and the CHECK rejecting the row, which would lose the balance as well.
    row = await _only(sessions)
    assert row.is_unbounded is True
    assert (row.songs_remaining, row.per_song_rate, row.estimate_basis) == (None, None, None)


async def test_a_failed_probe_ignores_a_divisor_because_an_estimate_belongs_to_a_balance(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a good measurement with an estimate on it.
    divisor = (0.30, BalanceEstimateBasis.TRAILING_SPEND_USD)
    await record_probe(sessions, probe=_ok(balance_remaining=3.0), divisor=divisor, at=_T0)
    assert (await _only(sessions)).songs_remaining == 10

    # Act — the vendor goes down. The divisor is still measurable; the balance is not.
    await record_probe(sessions, probe=_failed(), divisor=divisor, at=_T1)

    # Assert — the estimate survives untouched along with the balance it describes, because
    # the failure upsert names neither. Recomputing it against a stale balance would age the
    # figure without aging the number beside it.
    row = await _only(sessions)
    assert row.songs_remaining == 10
    assert row.balance_remaining == pytest.approx(3.0)
    assert row.fetched_at == _T0
    assert row.consecutive_failures == 1
