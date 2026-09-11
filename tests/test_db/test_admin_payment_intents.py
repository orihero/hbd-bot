"""``db.admin.payment_intents`` — the header, the funnel, the list and its chain columns.

Four properties are worth the file, and every test here is one of them:

* **The header is MEASURED, not declared.** The admin process cannot read
  ``CHECKOUT_PROVIDER`` or ``PAYME_ENABLED``, so provider / merchant / sandbox come off the
  newest ``payment_intents`` row. A regression that read the newest by ``updated_at``, or that
  returned the OLDEST, would render a stale cashbox with total confidence.
* **Absent is not zero.** A state with no rows is missing from the funnel rather than present
  at ``0``, because a zero bar is a claim about payments nobody attempted on a day this rail
  may not have been switched on.
* **The chain columns do not FAN OUT.** An intent accumulates a transaction per declined card,
  so a ``LEFT JOIN`` would return one payment three times and any caller summing
  ``amount_minor`` would triple the sale. The correlated-subquery shape is asserted by
  counting rows, not by reading a plan.
* **``has_grant`` false is NORMAL for a plan.** A plan mints songs as they are used and grants
  no credit at purchase, so a screen that rendered the missing grant as a fault would file
  every plan customer as a defect.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_ok
from bayram.db.admin.page import PageRequest, page_request
from bayram.db.admin.payment_intents import (
    MATCHED_ON_PUBLIC_REF,
    MATCHED_ON_TRANSACTION_ID,
    IntentFilters,
    SettleSource,
    count_intents,
    has_opened_any_intent,
    has_settled_any_intent,
    intent_by_id,
    intent_funnel,
    latest_checkout_seen,
    list_intents,
    resolve_intent_reference,
)
from bayram.db.admin.sql import TimeWindow
from bayram.db.enums import IntentProduct, PaymentIntentState, PaymeState
from tests.test_db.rail_helpers import (
    add,
    make_grant,
    make_intent,
    make_plan_receipt,
    make_topup_receipt,
    make_transaction,
    settle,
)

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


async def test_the_header_is_none_before_any_checkout_has_ever_been_opened(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``None`` and not a fabricated row: "nothing has ever been opened here" is a screen."""
    # Act
    async with sessions() as session:
        seen = await latest_checkout_seen(session)

    # Assert
    assert seen is None


async def test_the_header_reports_the_newest_intents_configuration(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The NEWEST row wins. An older cashbox rendered as current is the whole failure mode."""
    # Arrange — an older sandbox link, then a newer production one against a second cashbox.
    old = make_intent(now=_NOW, created_at=_NOW - timedelta(days=2))
    new = make_intent(
        now=_NOW,
        created_at=_NOW,
        merchant_id="99f72c72cac0d162c722ae9",
        is_sandbox=False,
        provider="payme",
    )
    await add(sessions, old, new)

    # Act
    async with sessions() as session:
        seen = await latest_checkout_seen(session)

    # Assert
    assert seen is not None
    assert seen.merchant_id == "99f72c72cac0d162c722ae9"
    assert seen.is_sandbox is False
    assert seen.seen_at == _NOW


async def test_the_two_row_probes_are_false_on_an_empty_table_and_ignore_the_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Window-blind by construction: they take no window at all, which is the assertion."""
    # Arrange
    async with sessions() as session:
        assert await has_opened_any_intent(session) is False
        assert await has_settled_any_intent(session) is False

    # Act — one intent, opened long before any window a caller would name, and never paid.
    await add(sessions, make_intent(now=_NOW, created_at=_NOW - timedelta(days=400)))

    # Assert
    async with sessions() as session:
        assert await has_opened_any_intent(session) is True
        assert await has_settled_any_intent(session) is False


async def test_a_settled_intent_flips_the_settlement_probe(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The flag that keeps an all-zero settlement card from reading as balanced."""
    # Arrange
    intent = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, intent)

    # Act / Assert
    async with sessions() as session:
        assert await has_settled_any_intent(session) is True


async def test_the_funnel_omits_states_with_no_rows_and_splits_the_expired(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Absent, never zero — and the abandoned/lapsed split needs no column to compute."""
    # Arrange — two expired intents: one that reached the payment form, one that never did.
    reached = make_intent(now=_NOW, state=PaymentIntentState.EXPIRED, created_at=_NOW)
    never = make_intent(now=_NOW, state=PaymentIntentState.EXPIRED, created_at=_NOW)
    pending = make_intent(now=_NOW, created_at=_NOW)
    await add(sessions, reached, never, pending)
    await add(
        sessions,
        make_transaction(intent_id=reached.id, payme_time=_NOW, state=PaymeState.CANCELLED),
    )

    # Act
    async with sessions() as session:
        funnel = await intent_funnel(session)

    # Assert — three states exist in the enum that have no rows, and none of them appears.
    assert {row.state for row in funnel.states} == {"expired", "pending"}
    assert funnel.expired_after_transaction == 1
    assert funnel.expired_with_no_transaction == 1


async def test_the_funnel_windows_on_created_at(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """When the payment was STARTED, not when it settled. See ``IntentFilters.window``."""
    # Arrange
    await add(
        sessions,
        make_intent(now=_NOW, created_at=_NOW - timedelta(days=10)),
        make_intent(now=_NOW, created_at=_NOW),
    )

    # Act
    async with sessions() as session:
        funnel = await intent_funnel(
            session,
            window=TimeWindow(start=_NOW - timedelta(days=1), end=_NOW + timedelta(days=1)),
        )

    # Assert
    assert funnel.states == tuple(funnel.states)
    assert sum(row.count for row in funnel.states) == 1


async def test_a_single_song_sale_reports_a_receipt_and_a_grant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The whole chain answered from correlated subqueries on the shared key."""
    # Arrange
    intent = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, intent)
    await add(sessions, make_topup_receipt(intent, at=_NOW), make_grant(intent, at=_NOW))

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())

    # Assert
    (item,) = page.items
    assert item.has_receipt is True
    assert item.has_grant is True


async def test_a_plan_sale_reports_a_receipt_and_no_grant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The regression this test exists for.** A plan grants nothing at purchase.

    A reader that treated ``has_grant is False`` as a broken chain would file every plan
    customer in the system as a fulfilment defect.
    """
    # Arrange
    intent = settle(make_intent(now=_NOW, product=IntentProduct.STARTER), at=_NOW)
    await add(sessions, intent)
    await add(sessions, make_plan_receipt(intent, at=_NOW))

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())

    # Assert
    (item,) = page.items
    assert item.has_receipt is True
    assert item.has_grant is False


async def test_an_intent_with_no_receipt_reports_neither(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Nothing under the key is ``False``/``False``, not an error and not a null."""
    # Arrange
    await add(sessions, make_intent(now=_NOW))

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())

    # Assert
    (item,) = page.items
    assert (item.has_receipt, item.has_grant) == (False, False)


async def test_three_transactions_do_not_fan_the_intent_into_three_rows(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The 1:N trap.** A ``LEFT JOIN`` here returns one payment three times.

    Asserted by counting rows and by reading ``amount_minor`` back unmultiplied, because that
    is what a caller summing the page would have got wrong.
    """
    # Arrange — a declined card, a second declined card, then a successful charge.
    intent = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, intent)
    await add(
        sessions,
        make_transaction(
            intent_id=intent.id,
            payme_time=_NOW - timedelta(minutes=4),
            state=PaymeState.CANCELLED,
        ),
        make_transaction(
            intent_id=intent.id,
            payme_time=_NOW - timedelta(minutes=2),
            state=PaymeState.CANCELLED,
        ),
        make_transaction(intent_id=intent.id, payme_time=_NOW, state=PaymeState.PERFORMED),
    )

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())

    # Assert
    assert len(page.items) == 1
    (item,) = page.items
    assert item.amount_minor == intent.amount_minor
    assert item.transaction_count == 3
    assert item.latest_transaction_state == PaymeState.PERFORMED.value
    assert item.latest_perform_time == _NOW


async def test_an_intent_the_rail_never_opened_reports_a_null_latest_state(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ "Payme has never opened a transaction against this" is itself the support answer."""
    # Arrange
    await add(sessions, make_intent(now=_NOW))

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())

    # Assert
    (item,) = page.items
    assert item.transaction_count == 0
    assert item.latest_transaction_state is None
    assert item.latest_perform_time is None


async def test_an_erased_buyer_lists_with_the_money_intact_and_a_null_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**Money survives erasure; the buyer does not.** The row renders, it does not crash.

    ``/forget`` nulls ``payment_intents.telegram_user_id`` and touches no money column, so the
    read must hand back the amount and a ``None`` buyer — a STATE the response layer renders as
    "buyer erased", never a blank and never an error.
    """
    # Arrange
    intent = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    await add(sessions, intent)

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())
        detail = await intent_by_id(session, intent_id=intent.id)

    # Assert
    (item,) = page.items
    assert item.telegram_user_id is None
    assert item.amount_minor == intent.amount_minor
    assert item.currency == "UZS"
    assert detail is not None
    assert detail.telegram_user_id is None
    assert detail.amount_minor == intent.amount_minor


async def test_no_view_model_carries_the_idempotency_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """It embeds the customer's Telegram id. It is a server-side join key and nothing else.

    Asserted over the FIELD NAMES and over the rendered values, so neither a re-added field nor
    a value smuggled into another one passes.
    """
    # Arrange
    intent = make_intent(now=_NOW)
    await add(sessions, intent)

    # Act
    async with sessions() as session:
        page = await list_intents(session, filters=IntentFilters(), request=PageRequest())
        detail = await intent_by_id(session, intent_id=intent.id)

    # Assert
    (item,) = page.items
    assert detail is not None
    for view in (item, detail):
        assert not any("idempotency" in field.name for field in fields(view))
        # And not smuggled into another field, which a name check alone would miss.
        assert intent.idempotency_key not in str(view)
        assert "topup:" not in str(view)


async def test_the_state_and_product_filters_or_within_a_field(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """And an EMPTY tuple means no filter, never "match none"."""
    # Arrange
    await add(
        sessions,
        make_intent(now=_NOW, state=PaymentIntentState.PENDING),
        settle(make_intent(now=_NOW), at=_NOW),
        make_intent(now=_NOW, product=IntentProduct.STARTER),
    )

    # Act / Assert — no filter is every row.
    async with sessions() as session:
        everything = await list_intents(
            session, filters=IntentFilters(states=(), products=()), request=PageRequest()
        )
        assert len(everything.items) == 3

        narrowed = await list_intents(
            session,
            filters=IntentFilters(states=(PaymentIntentState.PAID,)),
            request=PageRequest(),
        )
        assert [item.state for item in narrowed.items] == ["paid"]

        plans = await list_intents(
            session,
            filters=IntentFilters(products=(IntentProduct.STARTER,)),
            request=PageRequest(),
        )
        assert [item.product for item in plans.items] == ["starter"]


async def test_settled_by_separates_the_rail_from_a_human(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ "Did the rail move this money, or did one of us?" — the first reconciliation question."""
    # Arrange
    by_rail = settle(make_intent(now=_NOW), at=_NOW)
    by_hand = settle(make_intent(now=_NOW), at=_NOW, note="operator:INC-1")
    await add(sessions, by_rail, by_hand)

    # Act / Assert
    async with sessions() as session:
        rail = await list_intents(
            session,
            filters=IntentFilters(settled_by=SettleSource.RAIL),
            request=PageRequest(),
        )
        human = await list_intents(
            session,
            filters=IntentFilters(settled_by=SettleSource.OPERATOR),
            request=PageRequest(),
        )
    assert [item.intent_id for item in rail.items] == [by_rail.id]
    assert [item.intent_id for item in human.items] == [by_hand.id]


async def test_the_sandbox_filter_is_three_valued(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``None`` means both. A certification week must be hideable AND isolatable."""
    # Arrange
    rehearsal = make_intent(now=_NOW, is_sandbox=True)
    real = make_intent(now=_NOW, is_sandbox=False)
    await add(sessions, rehearsal, real)

    # Act / Assert
    async with sessions() as session:
        assert (
            len(
                (
                    await list_intents(
                        session, filters=IntentFilters(is_sandbox=None), request=PageRequest()
                    )
                ).items
            )
            == 2
        )
        only_real = await list_intents(
            session, filters=IntentFilters(is_sandbox=False), request=PageRequest()
        )
        assert [item.intent_id for item in only_real.items] == [real.id]


async def test_keyset_paging_returns_every_row_exactly_once_across_a_tie(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Five intents sharing ONE ``created_at``. The ``id`` tie-break is the whole test.

    Rows written in one settlement transaction share an instant, so a cursor on ``created_at``
    alone would either repeat a row or make one unreachable.
    """
    # Arrange
    intents = [make_intent(now=_NOW, created_at=_NOW) for _ in range(5)]
    await add(sessions, *intents)

    # Act — walk the whole list two rows at a time.
    seen: list[str] = []
    cursor: str | None = None
    async with sessions() as session:
        for _ in range(5):
            request = page_request(limit=2, cursor=cursor)
            assert is_ok(request)
            page = await list_intents(session, filters=IntentFilters(), request=request.value)
            seen.extend(item.public_ref for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

    # Assert
    assert sorted(seen) == sorted(intent.public_ref for intent in intents)
    assert len(seen) == len(set(seen))


async def test_count_intents_is_exact_below_the_cap_and_honours_the_filters(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``bounded_total``, which ``page_meta`` requires. Saturation is ``page.py``'s own test."""
    # Arrange
    await add(
        sessions,
        make_intent(now=_NOW),
        settle(make_intent(now=_NOW), at=_NOW),
    )

    # Act
    async with sessions() as session:
        total = await count_intents(session, filters=IntentFilters())
        paid = await count_intents(
            session, filters=IntentFilters(states=(PaymentIntentState.PAID,))
        )

    # Assert
    assert (total.total, total.is_exact) == (2, True)
    assert (paid.total, paid.is_exact) == (1, True)


async def test_count_intents_saturates_at_the_cap(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the cap the pair reads "at least this many", which is what ``isTotalExact`` says."""
    # Arrange — the cap is lowered rather than ten thousand rows being written.
    monkeypatch.setattr("bayram.db.admin.page.TOTAL_COUNT_CAP", 2)
    await add(sessions, *[make_intent(now=_NOW) for _ in range(4)])

    # Act
    async with sessions() as session:
        total = await count_intents(session, filters=IntentFilters())

    # Assert
    assert (total.total, total.is_exact) == (2, False)


async def test_intent_by_id_answers_none_rather_than_raising(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The router owns the 404's wording; this layer does not know what missing should mean."""
    # Act
    async with sessions() as session:
        found = await intent_by_id(session, intent_id=uuid4())

    # Assert
    assert found is None


async def test_a_reference_resolves_by_public_ref_and_by_transaction_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Both identifiers reach the intent, and each says WHICH one answered."""
    # Arrange
    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    transaction = make_transaction(intent_id=intent.id, payme_time=_NOW)
    await add(sessions, transaction)

    # Act
    async with sessions() as session:
        by_ref = await resolve_intent_reference(session, public_ref=intent.public_ref)
        by_txn = await resolve_intent_reference(
            session, payme_transaction_id=transaction.payme_transaction_id
        )
        missing = await resolve_intent_reference(session, public_ref="0" * 24)

    # Assert
    assert by_ref is not None
    assert (by_ref.intent_id, by_ref.matched_on) == (intent.id, MATCHED_ON_PUBLIC_REF)
    assert by_txn is not None
    assert (by_txn.intent_id, by_txn.matched_on) == (intent.id, MATCHED_ON_TRANSACTION_ID)
    assert missing is None


async def test_resolving_with_both_or_neither_reference_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The backstop the router's 422 duplicates, for callers that did not arrive over HTTP."""
    # Act / Assert
    async with sessions() as session:
        with pytest.raises(ValueError, match="exactly one reference"):
            await resolve_intent_reference(session)
        with pytest.raises(ValueError, match="exactly one reference"):
            await resolve_intent_reference(
                session, public_ref="a" * 24, payme_transaction_id="b" * 24
            )
