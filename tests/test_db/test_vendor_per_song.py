"""The three per-song vendor reads, and the four ways each of them can lie quietly.

``cost_per_delivered_song_by_vendor``, ``units_per_delivered_song_by_vendor`` and
``cost_provenance`` all publish figures an operator makes purchasing decisions from, and
none of their failure modes raises: each one produces a plausible dollar amount or a
plausible token count that happens to describe a different population than the caption
above it. The cases below are one per failure mode.

* **A zero where nothing was measured.** ``vendor_usage`` declares no default on any
  quantity column precisely so ``SUM`` over an unmeasured group returns ``NULL``, and these
  reads coalesce nothing. A ``0.0`` cost-per-song would say a vendor rendered a song for
  free; a ``0`` token count would say it rendered one out of no tokens at all. Both are
  asserted as ``None`` here, on a vendor that measured nothing and on a window that
  delivered nothing.
* **The unpriced calls disappearing.** Every other cost read on this surface collapses
  provenance into a ``MIN``/``MAX`` "mixed" boolean, and the rows carrying no cost at all
  drop out of ``MIN(cost_source)`` entirely — so the one number that says how much of the
  spend total is MISSING rather than small exists only in ``cost_provenance``'s ``NULL``
  bucket. That bucket is asserted present, positive, and distinguishable from a genuine
  vendor-reported ``0.0``.
* **Demo spend read as revenue-relevant cost.** ``_narrow`` drops ``is_fake`` rows unless a
  caller asks for them, and a fake run priced at ninety-nine dollars is seeded below in
  every one of the three reads to prove the filter is not merely inherited in the docstring.
* **The denominator drifting between the breakdown and the total beside it.**
  ``delivered_orders`` is a parameter, the same integer on every row, and a per-vendor
  denominator would make cost-per-song improve as instrumentation got worse.

Rows are inserted through the ORM with every clock stated, following
``test_admin_queries.py``: these tests assert figures computed by hand from the fixture,
which only means anything if the fixture's instants are exactly what the test says.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import count
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import CostSource, Language, OrderState, UsageTask, Vendor, VendorOperation
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.vendor_usage import (
    cost_per_delivered_song_by_vendor,
    cost_provenance,
    units_per_delivered_song_by_vendor,
)
from bayram.db.admin.views import CostProvenance, VendorCostPerSong, VendorUnitsPerSong
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow
from bayram.db.models.vendor_usage import VendorUsageRow
from tests.conftest import FIXED_NOW

#: The instant every window below is anchored to. Nothing is delivered ON it.
_NOW: Final[datetime] = FIXED_NOW
#: Comfortably inside the one-day window, and comfortably outside it.
_INSIDE: Final[datetime] = _NOW - timedelta(hours=2)
_OUTSIDE: Final[datetime] = _NOW - timedelta(days=9)
#: "Yesterday", the window every dashboard card on this surface is drawn for.
_WINDOW: Final[TimeWindow] = TimeWindow(start=_NOW - timedelta(days=1), end=_NOW)

#: Telegram ids are handed out by a counter because these reads do not look at the account
#: at all — an order needs one to satisfy its foreign key and nothing here asserts on it.
_ACCOUNTS: Iterator[int] = count(700_000_001)


async def _delivered_order(
    sessions: async_sessionmaker[AsyncSession],
    *,
    delivered_at: datetime | None,
    created_at: datetime | None = None,
) -> UUID:
    """One order and the account it hangs off. ``delivered_at`` is the only column read.

    ``state`` is set to match the timestamp so the fixture is not internally contradictory,
    but no read here looks at it: ``delivered_at`` IS the delivery event and these three
    functions filter on the column, never on the state beside it.
    """
    order_id = uuid4()
    opened = created_at if created_at is not None else (delivered_at or _INSIDE)
    async with sessions.begin() as session:
        telegram_user_id = next(_ACCOUNTS)
        user = UserRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            ui_language=Language.UZ_LATN,
            is_blocked=False,
            last_seen_at=opened,
            created_at=opened,
            updated_at=opened,
        )
        session.add(user)
        await session.flush()
        session.add(
            OrderRow(
                id=order_id,
                user_id=user.id,
                telegram_user_id=telegram_user_id,
                state=OrderState.DELIVERED if delivered_at else OrderState.GENERATING,
                correlation_id=f"corr-{order_id}",
                is_paid=True,
                delivered_at=delivered_at,
                created_at=opened,
                updated_at=opened,
            )
        )
    return order_id


async def _call(
    sessions: async_sessionmaker[AsyncSession],
    *,
    vendor: Vendor,
    order_id: UUID | None = None,
    operation: VendorOperation = VendorOperation.CHAT_COMPLETION,
    created_at: datetime = _INSIDE,
    **kw: Any,
) -> None:
    """One ``vendor_usage`` row. Every quantity defaults to ``NULL``, as the table does."""
    async with sessions.begin() as session:
        session.add(
            VendorUsageRow(
                id=uuid4(),
                vendor=vendor,
                operation=operation,
                provider=kw.pop("provider", "openai-compat"),
                model_id=kw.pop("model_id", None),
                is_fallback=False,
                is_fake=kw.pop("is_fake", False),
                task=kw.pop("task", UsageTask.SONG),
                order_id=order_id,
                correlation_id=None,
                is_success=True,
                http_status=200,
                total_tokens=kw.pop("total_tokens", None),
                billed_characters=kw.pop("billed_characters", None),
                audio_ms=kw.pop("audio_ms", None),
                cost_usd=kw.pop("cost_usd", None),
                cost_source=kw.pop("cost_source", None),
                created_at=created_at,
            )
        )


def _by_vendor[R: (VendorCostPerSong, VendorUnitsPerSong)](rows: tuple[R, ...]) -> dict[Vendor, R]:
    """Both shapes are ordered tuples; a test asserting one vendor's figures says which."""
    return {row.vendor: row for row in rows}


def _by_source(rows: tuple[CostProvenance, ...]) -> dict[CostSource | None, CostProvenance]:
    return {row.cost_source: row for row in rows}


# ---------------------------------------------------------------------------
# Nothing measured is never nothing spent
# ---------------------------------------------------------------------------
async def test_a_window_with_no_delivered_song_returns_no_vendor_rows_at_all_rather_than_zeroes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a real, priced, token-carrying delivery, nine days before the window opens.
    # The vendor rows themselves sit INSIDE the window, so only the cohort's `delivered_at`
    # predicate can keep them out; a read that windowed `vendor_usage.created_at` instead
    # would count this spend against a week that shipped nothing.
    order_id = await _delivered_order(sessions, delivered_at=_OUTSIDE)
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        order_id=order_id,
        cost_usd=0.42,
        cost_source=CostSource.DERIVED,
        total_tokens=1_200,
    )

    # Act — the caller's "Songs delivered" card counted zero, and hands that zero down.
    async with sessions() as session:
        costs = await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=0)
        units = await units_per_delivered_song_by_vendor(
            session, window=_WINDOW, delivered_orders=0
        )

    # Assert — an EMPTY tuple, not a row per vendor at zero. "We shipped nothing this week"
    # is not "our vendors were free this week", and a table drawn from these rows must have
    # no rows to draw rather than a column of $0.00 beside every vendor we use.
    assert costs == ()
    assert units == ()


async def test_a_call_billed_after_the_window_closed_still_belongs_to_the_song_it_rendered(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a song delivered inside the window whose music leg was recorded six hours
    # after the window shut. Rendering, delivery and billing are three instants and the
    # cohort is defined by the middle one, so `_narrow` is deliberately called with
    # `window=None`: a second range predicate on `vendor_usage.created_at` would drop
    # exactly this row and quietly report the song as cheaper than it was.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    await _call(
        sessions,
        vendor=Vendor.ELEVENLABS,
        order_id=order_id,
        operation=VendorOperation.MUSIC_COMPOSE,
        created_at=_NOW + timedelta(hours=6),
        cost_usd=0.20,
        cost_source=CostSource.ESTIMATED,
        audio_ms=90_000,
    )

    # Act
    async with sessions() as session:
        costs = await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        provenance = await cost_provenance(session, window=_WINDOW)

    # Assert — the per-song read counts it, and `cost_provenance` does NOT. The two are
    # scoped differently on purpose: one asks "what did the songs we shipped cost", which is
    # a question about a cohort, and the other asks "how was this period's spend arrived at",
    # which is a question about a calendar. Neither is a bug in the other.
    assert costs[0].cost_usd == pytest.approx(0.20)
    assert costs[0].attributed_orders == 1
    assert provenance == ()


async def test_a_vendor_nobody_could_price_reports_no_cost_at_all_rather_than_a_free_song(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one delivered song rendered by two vendors: one whose calls carry a figure,
    # one whose calls carry none because no rate is configured for that leg. This is the
    # out-of-the-box state of a fresh deployment, not an edge case.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    await _call(
        sessions,
        vendor=Vendor.ELEVENLABS,
        order_id=order_id,
        operation=VendorOperation.MUSIC_COMPOSE,
        cost_usd=0.30,
        cost_source=CostSource.ESTIMATED,
    )
    await _call(sessions, vendor=Vendor.OPENROUTER, order_id=order_id)

    # Act
    async with sessions() as session:
        rows = _by_vendor(
            await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        )

    # Assert — the unpriced vendor is PRESENT (its calls happened and its coverage is real)
    # and its money columns are None. A 0.0 here would be the module's worst available lie:
    # it would put a vendor that rendered a song for free onto a cost table.
    unpriced = rows[Vendor.OPENROUTER]
    assert unpriced.cost_usd is None
    assert unpriced.cost_per_song_usd is None
    assert unpriced.attributed_orders == 1
    assert rows[Vendor.ELEVENLABS].cost_usd == pytest.approx(0.30)
    assert rows[Vendor.ELEVENLABS].cost_per_song_usd == pytest.approx(0.30)


async def test_a_vendor_that_measured_tokens_and_no_characters_reports_characters_as_none(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the three unit families as they actually arrive: an LLM leg records tokens
    # and nothing else, a speech leg characters, a music leg milliseconds. No vendor
    # measures all three and no vendor measures none of the three.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    await _call(sessions, vendor=Vendor.OPENROUTER, order_id=order_id, total_tokens=1_200)
    await _call(
        sessions,
        vendor=Vendor.ELEVENLABS,
        order_id=order_id,
        operation=VendorOperation.SPEECH_SYNTHESIS,
        billed_characters=840,
    )

    # Act
    async with sessions() as session:
        rows = _by_vendor(
            await units_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        )

    # Assert — each family is None for the vendor that measured none of it, and the derived
    # per-song quotient is None with it. Tokens, characters and milliseconds do not share an
    # axis, so a 0 in the empty column would not be a small number on the same chart; it
    # would be a claim that this vendor was billed for nothing in a unit it never uses.
    llm = rows[Vendor.OPENROUTER]
    assert llm.total_tokens == 1_200
    assert llm.billed_characters is None
    assert llm.audio_ms is None
    assert llm.characters_per_song is None
    assert llm.tokens_per_song == pytest.approx(1_200.0)
    speech = rows[Vendor.ELEVENLABS]
    assert speech.billed_characters == 840
    assert speech.total_tokens is None
    assert speech.tokens_per_song is None


# ---------------------------------------------------------------------------
# The denominator is the cohort's, on every row, in both breakdowns
# ---------------------------------------------------------------------------
async def test_every_row_divides_by_the_whole_cohort_and_never_by_its_own_vendors_subset(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two delivered songs; the music vendor rendered both, the LLM only one. A
    # per-vendor denominator would divide the LLM's spend by ONE and report a cost per song
    # that IMPROVES the less of the cohort we instrumented.
    first = await _delivered_order(sessions, delivered_at=_INSIDE)
    second = await _delivered_order(sessions, delivered_at=_INSIDE - timedelta(hours=1))
    for order_id in (first, second):
        await _call(
            sessions,
            vendor=Vendor.ELEVENLABS,
            order_id=order_id,
            operation=VendorOperation.MUSIC_COMPOSE,
            cost_usd=0.10,
            cost_source=CostSource.ESTIMATED,
            audio_ms=90_000,
        )
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        order_id=first,
        cost_usd=0.04,
        cost_source=CostSource.VENDOR_REPORTED,
        total_tokens=1_000,
    )

    # Act — the caller counted the cohort once and hands the same integer to both reads.
    async with sessions() as session:
        costs = _by_vendor(
            await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=2)
        )
        units = _by_vendor(
            await units_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=2)
        )

    # Assert — the same denominator on every row of both reads, and the coverage published
    # beside it on the cost rows so a reader can see that the LLM figure covers half the
    # cohort. `attributed_orders` is the number that says so; it is NOT the denominator.
    assert {row.delivered_orders for row in costs.values()} == {2}
    assert {row.delivered_orders for row in units.values()} == {2}
    assert costs[Vendor.OPENROUTER].attributed_orders == 1
    assert costs[Vendor.OPENROUTER].cost_per_song_usd == pytest.approx(0.02)
    assert costs[Vendor.ELEVENLABS].attributed_orders == 2
    assert units[Vendor.OPENROUTER].tokens_per_song == pytest.approx(500.0)


async def test_a_vendor_called_twice_for_one_song_covers_one_order_and_not_two(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two LLM calls against a single delivered song, which is the ordinary shape:
    # a moderation pass and a lyric write are two rows for one order. `attributed_orders` is
    # COVERAGE, so counting calls there would report more covered orders than the cohort
    # contains and make the gap this column exists to expose read as zero.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    for cost in (0.03, 0.05):
        await _call(
            sessions,
            vendor=Vendor.OPENROUTER,
            order_id=order_id,
            cost_usd=cost,
            cost_source=CostSource.VENDOR_REPORTED,
            total_tokens=500,
        )

    # Act
    async with sessions() as session:
        costs = await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        units = await units_per_delivered_song_by_vendor(
            session, window=_WINDOW, delivered_orders=1
        )

    # Assert — one covered order, both costs summed, both token counts summed. The money and
    # the units add up over calls; the coverage counts orders and does not.
    assert costs[0].attributed_orders == 1
    assert costs[0].cost_usd == pytest.approx(0.08)
    assert units[0].total_tokens == 1_000


async def test_a_call_belonging_to_no_order_is_absent_from_the_per_song_reads_and_present_in_spend(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the wizard's lyric preview runs BEFORE any order row exists, so its spend
    # carries `order_id IS NULL` by design. It cannot be divided by a song because it
    # belongs to none, and it is exactly the spend an operator most wants to see — so it
    # must be missing from the per-song breakdowns and counted in the provenance total.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    await _call(
        sessions,
        vendor=Vendor.ELEVENLABS,
        order_id=order_id,
        operation=VendorOperation.MUSIC_COMPOSE,
        cost_usd=0.10,
        cost_source=CostSource.ESTIMATED,
    )
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        order_id=None,
        task=UsageTask.LYRICS_PREVIEW,
        cost_usd=0.02,
        cost_source=CostSource.VENDOR_REPORTED,
        total_tokens=300,
    )

    # Act
    async with sessions() as session:
        costs = await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        units = await units_per_delivered_song_by_vendor(
            session, window=_WINDOW, delivered_orders=1
        )
        provenance = _by_source(await cost_provenance(session, window=_WINDOW))

    # Assert — the join to `orders` drops the orphan from both per-song shapes, and nothing
    # about that omission is visible on those rows; the provenance read, which joins nothing,
    # is where the unattributed dollar is still counted.
    assert [row.vendor for row in costs] == [Vendor.ELEVENLABS]
    assert [row.vendor for row in units] == [Vendor.ELEVENLABS]
    assert provenance[CostSource.VENDOR_REPORTED].cost_usd == pytest.approx(0.02)
    assert provenance[CostSource.ESTIMATED].cost_usd == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# A demo run is recorded, and excluded from every figure that is about money
# ---------------------------------------------------------------------------
async def test_a_fake_provider_run_is_excluded_from_all_three_per_song_reads(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a fake run against the same delivered order, priced absurdly high and with
    # a million tokens on it, so any read that let it through fails loudly rather than by a
    # rounding error. `is_fake` rows are written on purpose (no rows at all cannot be told
    # from an uninstrumented deployment) and every spend read must drop them.
    order_id = await _delivered_order(sessions, delivered_at=_INSIDE)
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        order_id=order_id,
        cost_usd=0.50,
        cost_source=CostSource.VENDOR_REPORTED,
        total_tokens=2_000,
    )
    await _call(
        sessions,
        vendor=Vendor.FAKE,
        order_id=order_id,
        provider="fake_llm",
        is_fake=True,
        cost_usd=99.0,
        cost_source=CostSource.VENDOR_REPORTED,
        total_tokens=1_000_000,
    )

    # Act
    async with sessions() as session:
        costs = await cost_per_delivered_song_by_vendor(session, window=_WINDOW, delivered_orders=1)
        units = await units_per_delivered_song_by_vendor(
            session, window=_WINDOW, delivered_orders=1
        )
        provenance = await cost_provenance(session, window=_WINDOW)

    # Assert — the fake vendor has no row in either breakdown, and its dollars are absent
    # from the provenance total as well. The provenance read is the one that would be missed:
    # it does not join `orders` at all, so it filters the demo run through `_narrow` alone.
    assert [row.vendor for row in costs] == [Vendor.OPENROUTER]
    assert [row.vendor for row in units] == [Vendor.OPENROUTER]
    assert costs[0].cost_usd == pytest.approx(0.50)
    assert units[0].total_tokens == 2_000
    reported = _by_source(provenance)[CostSource.VENDOR_REPORTED]
    assert reported.calls == 1
    assert reported.cost_usd == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# The unpriced bucket is the point of the provenance read, not a leftover in it
# ---------------------------------------------------------------------------
async def test_the_unpriced_calls_are_their_own_bucket_and_sort_last_rather_than_vanishing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one call of each kind, so the three buckets tie on `calls` and the ordering
    # is decided entirely by the explicit IS NULL key. A vendor-reported 0.0 sits beside an
    # unpriced call deliberately: OpenRouter reports a genuine zero on a free model, and
    # "the vendor said this was free" must never render like "nobody could say".
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        cost_usd=0.0,
        cost_source=CostSource.VENDOR_REPORTED,
    )
    await _call(
        sessions,
        vendor=Vendor.ELEVENLABS,
        operation=VendorOperation.MUSIC_COMPOSE,
        cost_usd=0.25,
        cost_source=CostSource.DERIVED,
    )
    await _call(sessions, vendor=Vendor.ELEVENLABS, operation=VendorOperation.TRANSCRIPTION)

    # Act
    async with sessions() as session:
        rows = await cost_provenance(session, window=_WINDOW)

    # Assert — three buckets, the ``None`` one LAST on both dialects (the module's NULLS
    # rule), carrying a positive call count and no cost. That row is the only number on this
    # surface that says how much of the spend total is MISSING rather than small: every
    # other read collapses provenance to a MIN/MAX boolean, and an unpriced row drops out of
    # MIN(cost_source) entirely.
    assert [row.cost_source for row in rows] == [
        CostSource.DERIVED,
        CostSource.VENDOR_REPORTED,
        None,
    ]
    unpriced = rows[-1]
    assert unpriced.calls == 1
    assert unpriced.cost_usd is None
    # The genuine zero survives as a zero. Merging these two rows would delete the
    # difference between a free model and an unconfigured rate.
    free = _by_source(rows)[CostSource.VENDOR_REPORTED]
    assert free.cost_usd == pytest.approx(0.0)
    assert free.cost_usd is not None


async def test_the_quota_probe_is_kept_out_of_the_provenance_default_and_available_on_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one real priced call and three balance-poller probes. The poller writes
    # roughly seventy-two of these a day, all unpriced on purpose, so left in they would
    # dominate the NULL bucket within a week and report an instrumented deployment's spend
    # as uninstrumented.
    await _call(
        sessions,
        vendor=Vendor.OPENROUTER,
        cost_usd=0.25,
        cost_source=CostSource.DERIVED,
    )
    for _ in range(3):
        await _call(
            sessions,
            vendor=Vendor.ELEVENLABS,
            operation=VendorOperation.HEALTH,
            provider="elevenlabs_music",
            task=None,
        )

    # Act
    async with sessions() as session:
        spendable = await cost_provenance(session, window=_WINDOW)
        everything = await cost_provenance(session, window=_WINDOW, exclude_operations=())

    # Assert — the default answers "how was our SPEND arrived at" and the probes are not
    # spend; a caller auditing the whole table passes `()` and sees them as the unpriced
    # bucket they are.
    assert [row.cost_source for row in spendable] == [CostSource.DERIVED]
    audited = _by_source(everything)
    assert audited[None].calls == 3
    assert audited[None].cost_usd is None
    assert audited[CostSource.DERIVED].calls == 1
