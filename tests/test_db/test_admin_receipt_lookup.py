"""The dossier's three joined reads: the receipt in whichever table it landed in, and the grant.

Three functions on three modules, tested together because the property they share is what
matters: they are all keyed on ``payment_intents.idempotency_key``, copied VERBATIM into
``topup_purchases`` / ``plan_purchases`` and ``credit_ledger`` inside the one commit that flips
the intent to ``paid``. That single string is the entire join between money and fulfilment, and
a test that minted its own key per table would build a database in which the correct query
returns nothing.

Two answers here look like failures and are not:

* **A plan sale returns an EMPTY ledger tuple.** A plan mints songs as they are used and grants
  no credit at purchase. A caller that read ``()`` as a broken chain would file every plan
  customer as a fulfilment defect — which is why the dossier renders that step as NOT
  APPLICABLE and never as missing.
* **A settled payment can have no receipt in either table.** That is what an erased buyer looks
  like: ``_settle`` claims the intent and writes no sale when ``telegram_user_id IS NULL``,
  because the money moved and there is nobody left to grant a credit to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.admin.credits import ledger_for_key
from bayram.db.admin.plan_purchases import PLAN_RECEIPT_SOURCE
from bayram.db.admin.plan_purchases import receipt_for_key as plan_receipt_for_key
from bayram.db.admin.topup_purchases import TOPUP_RECEIPT_SOURCE
from bayram.db.admin.topup_purchases import receipt_for_key as topup_receipt_for_key
from bayram.db.enums import IntentProduct
from tests.test_db.rail_helpers import (
    add,
    make_grant,
    make_intent,
    make_plan_receipt,
    make_topup_receipt,
    settle,
)

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


async def test_a_single_song_key_returns_a_topup_receipt_and_one_grant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The whole single-song chain, read the way the dossier reads it."""
    # Arrange
    intent = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, intent)
    receipt_row = make_topup_receipt(intent, at=_NOW)
    await add(sessions, receipt_row, make_grant(intent, at=_NOW))

    # Act
    async with sessions() as session:
        receipt = await topup_receipt_for_key(session, idempotency_key=intent.idempotency_key)
        ledger = await ledger_for_key(session, idempotency_key=intent.idempotency_key)

    # Assert
    assert receipt is not None
    assert receipt.source == TOPUP_RECEIPT_SOURCE
    assert receipt.amount_minor == intent.amount_minor
    assert receipt.currency == intent.currency
    # The rail's own id: what an operator searches the Payme cabinet for.
    assert receipt.reference == receipt_row.reference
    assert receipt.credits_granted == 1
    # The plan-only fields are None here by construction, not by accident.
    assert (receipt.songs_included, receipt.songs_used, receipt.plan_ends_at) == (
        None,
        None,
        None,
    )
    assert [(row.kind, row.delta, row.reason) for row in ledger] == [("grant", 1, "topup_purchase")]
    assert ledger[0].actor == "checkout"


async def test_a_plan_key_returns_a_plan_receipt_and_an_empty_ledger(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The regression this file exists for.** A plan grants nothing at purchase.

    ``songs_used`` on the receipt row is the ONE place the chain continues past the purchase;
    for a single song it stops at the grant, because ``credit_accounts.balance`` is a fungible
    scalar with no lot structure.
    """
    # Arrange
    intent = settle(make_intent(now=_NOW, product=IntentProduct.STARTER), at=_NOW)
    await add(sessions, intent)
    await add(sessions, make_plan_receipt(intent, at=_NOW))

    # Act
    async with sessions() as session:
        receipt = await plan_receipt_for_key(session, idempotency_key=intent.idempotency_key)
        ledger = await ledger_for_key(session, idempotency_key=intent.idempotency_key)

    # Assert
    assert receipt is not None
    assert receipt.source == PLAN_RECEIPT_SOURCE
    assert receipt.songs_included == 12
    assert receipt.songs_used == 0
    assert receipt.plan_ends_at is not None
    assert receipt.credits_granted is None
    assert ledger == ()


async def test_a_key_with_nothing_under_it_answers_none_and_an_empty_tuple(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The erased-buyer settlement: money moved, no sale written, and none of it is an error."""
    # Arrange
    intent = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    await add(sessions, intent)

    # Act
    async with sessions() as session:
        topup = await topup_receipt_for_key(session, idempotency_key=intent.idempotency_key)
        plan = await plan_receipt_for_key(session, idempotency_key=intent.idempotency_key)
        ledger = await ledger_for_key(session, idempotency_key=intent.idempotency_key)

    # Assert
    assert topup is None
    assert plan is None
    assert ledger == ()


async def test_one_payments_receipt_is_never_another_payments(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The lookup is an equality on a UNIQUE key, so two settlements cannot cross-contaminate."""
    # Arrange
    first = settle(make_intent(now=_NOW), at=_NOW)
    second = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, first, second)
    await add(sessions, make_topup_receipt(first, at=_NOW))

    # Act
    async with sessions() as session:
        found = await topup_receipt_for_key(session, idempotency_key=first.idempotency_key)
        missing = await topup_receipt_for_key(session, idempotency_key=second.idempotency_key)

    # Assert
    assert found is not None
    assert missing is None
