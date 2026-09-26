"""The certification transcript, as the suite sees it: one table, plus a way to count money.

**Where the table actually lives, and why it is not here.** Payme's two published sandbox
scripts are encoded as data in :mod:`bayram.payme.harness` — in ``src``, not in ``tests`` — and
this module is the test-facing half of that one table rather than a second copy of it. The
direction is forced and it is worth stating so nobody reverses it later: ``bayram.payme.harness``
is a SHIPPED script (``python -m bayram.payme.harness``) that an operator runs on the VPS on
certification day, and ``src`` importing ``tests`` would make that command an ``ImportError``
on any host where the wheel was installed without the test suite. The dependency therefore
points the only way it can, and the property the plan actually asks for — that the suite and
the harness drive THE SAME table, so a scenario cannot pass in CI and fail in the cabinet — is
what this arrangement buys.

**What this module adds that the shipped table cannot.** Three things, all of them things only
a process that owns its own database can do:

* the placeholder credential set — a made-up 36-character key, which is a fully functional
  gateway because the key is only ever compared against itself;
* :func:`money_after`, which COUNTS the receipt and credit-ledger rows a scenario left behind.
  A reply saying ``state: 2`` is not evidence that a credit was granted and a reply saying
  ``-31007`` is not evidence that nothing was reversed. The harness can read an intent's state
  back over its ledger handle and does; only the suite can diff whole tables;
* :data:`MONEY_OUTCOMES`, the same claim stated as data so the parametrised test reads as a
  table and not as a chain of ``if scenario.name ==``.

Nothing here mutates the shipped table. If a scenario is wrong, it is wrong in
``bayram.payme.harness`` and it is wrong in the cabinet too, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import sqlalchemy as sa

from bayram.checkout import PaymentIntentState
from bayram.db.enums import CreditEntryKind
from bayram.db.models import CreditLedgerRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.payme.container import PaymeContainer
from bayram.payme.harness import REPLAYED_METHODS, SCENARIOS, Credentials, Scenario

__all__ = [
    "TRANSCRIPT",
    "REPLAYED_METHODS",
    "MONEY_OUTCOMES",
    "MoneyOutcome",
    "PLACEHOLDER_KEY",
    "PLACEHOLDER_LOGIN",
    "PLACEHOLDER_MERCHANT",
    "PLACEHOLDER_CREDENTIALS",
    "PRICE_MINOR",
    "TELEGRAM_USER_ID",
    "money_after",
    "intent_state",
    "transaction_count",
]

#: Payme's two published scripts, the authorization probe that opens every certification call,
#: and the refusals the sandbox probes around them. Imported, never restated.
TRANSCRIPT: Final[tuple[Scenario, ...]] = SCENARIOS

#: 36 characters, invented, and completely sufficient. The merchant key is compared against
#: itself under ``hmac.compare_digest`` and reaches no third party, so a placeholder exercises
#: every line of the gateway that a real ``TEST_KEY`` would. This is why the whole rail is
#: certifiable today, before Payme has handed over a credential.
PLACEHOLDER_KEY: Final[str] = "d4f1a9c07b2e46d8ab53c1e90f7a2b6c5d3e"

#: What both official templates hard-code and what the archived 2017 spec says. It is a SETTING
#: (``BAYRAM_PAYME_BASIC_LOGIN``) because the current documentation hedges and tells a merchant to
#: ask a technical specialist; the first real ``-32504`` log line closes the question.
PLACEHOLDER_LOGIN: Final[str] = "Paycom"

#: The merchant id from Payme's own worked example of the link format. Public by nature — it is
#: rendered in a browser address bar on every checkout — so using theirs is not a leak, and it
#: keeps this suite's fixtures and ``test_link.py``'s golden vector spelling one id.
PLACEHOLDER_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"

PLACEHOLDER_CREDENTIALS: Final[Credentials] = Credentials(
    login=PLACEHOLDER_LOGIN, key=PLACEHOLDER_KEY
)

#: 7 000 so'm in TIYIN. Already the number Payme is sent — nothing on this path multiplies by
#: 100, and ``test_link.py`` has a test named after the hundred-fold bug this prevents.
PRICE_MINOR: Final[int] = 700_000

#: Well outside 2**31. An accidental ``Integer`` column on this path would not fail loudly, it
#: would truncate the id of whoever is paying.
TELEGRAM_USER_ID: Final[int] = 8_912_345_678_901


@dataclass(frozen=True, slots=True)
class MoneyOutcome:
    """What a scenario must have written when it finishes. Counted, never inferred.

    A named triple rather than a bare tuple because the three numbers are not interchangeable,
    and a failure message reading ``receipts=1, grants=0`` costs a reader nothing while
    ``(1, 0, 'paid') != (1, 1, 'paid')`` costs them ten seconds at the exact moment a payment
    did not settle.
    """

    receipts: int
    grants: int
    intent_state: PaymentIntentState


#: The money claim per scenario, keyed by name. Derived from the shipped table's own
#: ``credits_granted``/``receipts_written``/``expected_intent_state`` rather than restated, so
#: a scenario whose script changes cannot leave a stale money expectation behind it — the two
#: halves of one claim move together or they do not move.
MONEY_OUTCOMES: Final[dict[str, MoneyOutcome]] = {
    scenario.name: MoneyOutcome(
        receipts=scenario.receipts_written,
        grants=scenario.credits_granted,
        intent_state=scenario.expected_intent_state,
    )
    for scenario in TRANSCRIPT
}


async def money_after(container: PaymeContainer, *, public_ref: str) -> MoneyOutcome:
    """Count what is actually in the database, through the container's own session factory.

    Receipts are counted across BOTH sale tables. The transcript only buys singles today, so
    ``plan_purchases`` is always zero — and it is counted anyway, because the day somebody adds
    a ``STARTER`` scenario the assertion that must not silently pass is "no receipt was
    written". A count that looked only at ``topup_purchases`` would report a plan sale as zero
    receipts and call it a pass.

    Grants are counted as ``credit_ledger`` rows of kind ``GRANT`` rather than as a balance,
    because a balance is a scalar that two grants and one debit can also produce. The ledger
    row is the audit fact; the balance is a cache of it.
    """
    async with container.session_factory() as session:
        topups = await session.scalar(sa.select(sa.func.count()).select_from(TopupPurchaseRow))
        plans = await session.scalar(sa.select(sa.func.count()).select_from(PlanPurchaseRow))
        grants = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CreditLedgerRow)
            .where(CreditLedgerRow.kind == CreditEntryKind.GRANT)
        )
        state = await session.scalar(
            sa.select(PaymentIntentRow.state).where(PaymentIntentRow.public_ref == public_ref)
        )
    assert state is not None, f"no payment_intents row for {public_ref}"
    return MoneyOutcome(
        receipts=int(topups or 0) + int(plans or 0),
        grants=int(grants or 0),
        # ``bayram.db.enums.PaymentIntentState`` and ``bayram.checkout.PaymentIntentState`` are two
        # enums mirroring each other value-for-value, on purpose: no application type may reach
        # a mapped column. The crossing is spelled out here rather than hidden behind an
        # ``isinstance``, because it is exactly the seam a reviewer should be able to see.
        intent_state=PaymentIntentState(state.value),
    )


async def intent_state(container: PaymeContainer, *, public_ref: str) -> PaymentIntentState:
    """One intent's state, read straight from the row rather than through the ledger port."""
    async with container.session_factory() as session:
        found = await session.scalar(
            sa.select(PaymentIntentRow.state).where(PaymentIntentRow.public_ref == public_ref)
        )
    assert found is not None, f"no payment_intents row for {public_ref}"
    return PaymentIntentState(found.value)


async def transaction_count(container: PaymeContainer) -> int:
    """How many ``payme_transactions`` rows exist. The replay guarantee, counted.

    A replayed ``CreateTransaction`` must return the stored row and write nothing; the reply
    alone cannot distinguish that from a second row that happens to look the same, and the
    unique index on ``payme_transaction_id`` is what makes the difference. This is how the
    difference is asserted.
    """
    async with container.session_factory() as session:
        total = await session.scalar(sa.select(sa.func.count()).select_from(PaymeTransactionRow))
    return int(total or 0)
