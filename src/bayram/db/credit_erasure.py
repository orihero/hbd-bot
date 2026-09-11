"""``/forget`` against the credit tables: drop the balance, keep the count, lose the name.

``/privacy`` enumerates four retention clocks and promises that everything on them is
deleted on a schedule. The entitlement layer arrived with two tables that are on no clock
at all — ``credit_accounts``, which is a live balance, and ``credit_ledger``, which is an
append-only audit trail — so the notice became false the moment WU1 landed. This module is
half of making it true again; the other half is the copy in the four catalogues that now
names both.

**The two tables get opposite treatment, and the asymmetry is the whole design.**

*A balance is not an audit fact.* ``credit_accounts`` holds what someone may spend right
now. Nobody needs it after they have asked to be forgotten, and keeping it would leave a
row that says "this Telegram account exists and has two songs left" — an identity record
with no purpose. It is DELETED.

*A receipt is.* ``credit_ledger`` is what answers "why does this account have two credits?"
and "was this customer charged for a song that never arrived?" months later, including for
a dispute the customer themselves raises. Deleting it would destroy that answer for
everyone, and an audit trail that erases itself on request is not an audit trail. So the
rows STAY and the identity comes off them: ``telegram_user_id`` is nulled and everything
else — the movement, its reason, its clock — survives as an anonymous aggregate.

**``plan_purchases`` gets the receipt treatment for exactly the same reason, and the
argument is worth restating rather than inferring, because that table looks more like a
balance than the ledger does.** It carries an amount, a rail, a reference and a counter, and
the money in it was really paid: "was this customer charged 49 000 soʻm for twelve songs
they never got?" is precisely the question a deleted row cannot answer, so deleting it would
make ``/forget`` mean "refund me". ``songs_used`` is also left exactly where it is —
resetting it would make ``/forget`` mean "give me my twelve songs back", repeatable for as
long as the plan runs, which is the same exploit the kept ``idempotency_key`` closes for the
rolling allowance below.

**``topup_purchases`` is the fourth table and takes the identical treatment, for the
identical reason.** It is the receipt for a single song, and the money on it is the only
record that the sale had a price at all — the ``credit_ledger`` GRANT it was written beside
carries an entitlement and no amount. "Was this customer charged 7 000 soʻm for a song they
never got?" is the same dispute one row smaller, and it is asked months later, after the
recipient's name, the customer's note and the rendered audio are lawfully gone. So the id
comes off and the amount, the currency, the rail, its reference, the key and the clock stay
as an anonymous sale. Without this arm ``/forget`` would leave a fully identified sales
receipt behind and the ``/privacy`` notice would be false again the moment top-up revenue
landed — which is the exact failure this module exists to prevent.

**``bot_membership_events`` is the fifth table, and it is here for a reason that is NOT a
receipt's.** It holds no money and settles no dispute; it is the record of a customer
blocking or unblocking the bot, and the panel counts it to answer "how many people left us
last month". Deleting these rows on request would make that answer shrink retroactively by
the number of people who asked to be forgotten — last March's churn would stop being last
March's churn — which is precisely the defect the append-only events table exists to
prevent. An anonymous transition record, by contrast, says nothing about anybody at all. So
it takes the ledger's treatment: the id comes off, the direction, the source and the instant
stay. ``users.blocked_bot_at`` is deliberately NOT cleared alongside it — a forgotten
customer who still has the bot blocked is still unreachable, and clearing it would make the
churn gauge count them as reachable.

**``payment_intents`` is the sixth table, and it is the only one where deleting the row
would make us LIE TO A THIRD PARTY.** It is the record of a payment started on a redirect
rail and finished minutes later on an inbound request from that rail's own servers. The rail
keeps its side of that record permanently and can ask us about any transaction it ever
created, over an arbitrary period, through its statement call. A deleted intent would make
that answer "we have never heard of this payment" about money a customer really paid —
which is not merely a lost dispute, it is the answer that makes the customer's own bank
believe them less. So the row takes the receipt treatment and then some: the id comes off
and ``public_ref``, the amount, the currency, the merchant account, the rail's reference and
every clock stay, so the statement call still renders a complete account object for a person
who no longer exists in our database. ``settle_note`` stays too, because "was this money
moved by the rail or forced through by one of us?" is the first question of any
reconciliation and the answer must not depend on who has since asked to be forgotten.

**``broadcast_recipients`` is the seventh table, and it is on ``bot_membership_events``'
footing rather than a receipt's.** It holds no money either; it is the delivery ledger of a
campaign that has already gone out, one row per account per campaign, and the six counters on
the ``broadcasts`` row are a rollup of exactly these rows. Deleting them on request would make
a completed campaign's arithmetic shrink retroactively by the number of people who have since
asked to be forgotten — last March's send would stop being last March's send, which is the
same defect the churn log's treatment above exists to prevent, and it would do it to a number
an operator has already read and acted on. So the id comes off and the state, the attempt
count, the error code and the settlement instant stay, saying nothing about anybody. The
unique constraint is built to allow it: ``UNIQUE (broadcast_id, telegram_user_id)`` tolerates
any number of NULLs on both engines, so an anonymised row stops participating in uniqueness
and can never block a later expansion for a different account. ``broadcasts`` and
``broadcast_bodies`` are untouched — they hold operator copy and a segment document of
registry keys, and nothing about a customer at all.

**Why ``idempotency_key`` deliberately keeps the id it was built from.** The rolling
allowance is minted once per window on ``grant:period:{telegram_user_id}:{index}``, and the
unique index on that key is the ONLY thing that makes the mint idempotent. Rewriting the
key here would delete that memory, and because :func:`bayram.db.credits._mint_due_allowance`
reads ``credit_accounts.allowance_period_index`` — a row this function has just removed —
the very next order would mint a fresh allowance for a window already paid for. ``/forget``
would become "reset my free songs", repeatable, forever. Keeping the key is what makes
:func:`forget_account` an erasure rather than an exploit, and it is asserted by test.

The cost of that choice is stated rather than hidden: one machine-built string per grant
still contains the account id. It is a replay marker, not a record about a person — it
carries no balance, no order and no history on its own — but a reader of this module should
know it is there.

Shape follows :mod:`bayram.db.admin` and :func:`bayram.db.purge.purge_expired`: session first and
positional, exceptions propagate, and **nothing is committed here**. The caller owns the
transaction, which is what lets the seven statements below be atomic — an erasure that
deleted the balance and then failed to anonymise the ledger would be the worst of both.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.churn import anonymise_bot_membership_events
from bayram.db.credit_sql import rowcount_of
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.plan_sql import anonymise_plans
from bayram.db.topup_sql import anonymise_topups

__all__ = ["CreditErasure", "forget_account"]


@dataclass(frozen=True, slots=True)
class CreditErasure:
    """What one ``/forget`` actually removed. Seven numbers, so the log is not a guess.

    All seven being zero is a perfectly ordinary answer — most people who send ``/forget`` never
    confirmed an order, so they have no account row and no ledger history — and it is
    reported as such rather than treated as a failure. The handler's confirmation to the
    customer does not depend on it: it says the same thing either way, because "there was
    nothing of yours to delete" and "I deleted it" are the same promise kept.

    All seven come from the driver's ``rowcount`` over a bulk statement, which
    :func:`bayram.db.credit_sql.rowcount_of` documents as exact only for single-row writes.
    They are therefore DIAGNOSTIC — they go in a log line and nothing branches on them.
    """

    #: ``credit_accounts`` rows removed. Zero or one; the id is that table's primary key.
    accounts_deleted: int
    #: ``credit_ledger`` rows that lost their owner and kept everything else.
    entries_anonymised: int
    #: ``plan_purchases`` rows treated the same way. A THIRD number rather than a sum with
    #: the one above, because the two tables answer different questions in a dispute and an
    #: operator reading the log line needs to know a plan receipt survived, not merely that
    #: "some rows" did.
    plans_anonymised: int = 0
    #: ``topup_purchases`` rows treated the same way. A FOURTH number for the reason the
    #: third one is separate: a plan dispute and a single-song dispute are different
    #: conversations with different amounts, and an operator reading the log line needs to
    #: know which kind of receipt survived. Summing them would say only that "some rows" did.
    topups_anonymised: int = 0
    #: ``bot_membership_events`` rows treated the same way, and a FIFTH number for a reason
    #: unlike the other three: this table holds no money at all. It is the churn history, and
    #: DELETING it would make the daily block counts shrink retroactively by the number of
    #: people who asked to be forgotten — a historical figure that changes after the fact,
    #: which is the exact defect the events table was created to avoid. So the id comes off
    #: and the passages stay, saying nothing about anybody.
    membership_events_anonymised: int = 0
    #: ``payment_intents`` rows treated the same way, and a SIXTH number rather than a sum
    #: with the receipts above for a reason none of them share: this is the only table whose
    #: rows a THIRD PARTY can still ask us about by name. An operator reading the log line
    #: after a customer's ``/forget`` needs to know that the payment rail's own view of that
    #: person's transactions is still answerable — which is what a non-zero here says and
    #: what a sum with ``topups_anonymised`` would have hidden.
    intents_anonymised: int = 0
    #: ``broadcast_recipients`` rows treated the same way, and a SEVENTH number rather than a
    #: sum with ``membership_events_anonymised`` — the arm it shares an argument with —
    #: because the two answer different complaints. "Was this person sent that campaign?" is
    #: the first question of a marketing complaint, and an operator reading the log line needs
    #: to know the delivery ledger was reached, not merely that "some rows" were. It is also
    #: the only number here that can be in the thousands for one account: a customer who has
    #: been on the audience of every campaign we have ever run has a row for each.
    recipients_anonymised: int = 0


async def forget_account(session: AsyncSession, *, telegram_user_id: int) -> CreditErasure:
    """Erase what the credit tables hold about one Telegram account.

    Ordered receipts-first and balance-last on purpose. All seven statements run in the
    caller's transaction, so they either all land or none do; but if a future caller ever
    splits them, a run that leaves the receipts anonymous and the balance behind is far less
    bad than one that deletes the balance and leaves a fully identified history.

    Idempotent by construction: a second call matches nothing and returns seven zeroes.

    **What this does not reach.** A song already in the studio settles after the erasure,
    and the worker writes that settlement from the ``orders`` row — which keeps its own id
    on the ``/privacy`` schedule — so one ledger entry can appear afterwards carrying the
    account id again. ``privacy.forgotten`` already tells the customer that a song at the
    studio keeps the dates in ``/privacy``; sending ``/forget`` once it has arrived clears
    that entry too. Named here because a reader must not have to discover it.
    """
    plans = await anonymise_plans(session, telegram_user_id=telegram_user_id)
    topups = await anonymise_topups(session, telegram_user_id=telegram_user_id)
    events = await anonymise_bot_membership_events(session, telegram_user_id=telegram_user_id)
    # Written here rather than behind a ``payme_sql`` helper because the redirect rail's own
    # query module is not a dependency of erasure: this arm must keep working — and keep
    # being asserted by test — on a deployment where ``BAYRAM_CHECKOUT_PROVIDER=stub`` and no
    # rail code is reachable at all. Its shape is the ``credit_ledger`` statement below,
    # deliberately: the id comes off, every money column, ``public_ref``, ``settle_note`` and
    # all four clocks stay. See the module docstring on why a DELETE here would be worse
    # than useless.
    intents = await session.execute(
        sa.update(PaymentIntentRow)
        .where(PaymentIntentRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    # Spelled out here rather than behind a broadcast query module for
    # :attr:`PaymentIntentRow`'s reason above: erasure must not acquire a dependency on the
    # campaign feature's own SQL layer, and this arm has to keep working — and keep being
    # asserted by test — on a deployment that has never sent a broadcast at all. The
    # ``broadcasts`` parent and its bodies are deliberately not touched; see the module
    # docstring on why the campaign's counters must survive this whole.
    recipients = await session.execute(
        sa.update(BroadcastRecipientRow)
        .where(BroadcastRecipientRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    anonymised = await session.execute(
        sa.update(CreditLedgerRow)
        .where(CreditLedgerRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    deleted = await session.execute(
        sa.delete(CreditAccountRow).where(CreditAccountRow.telegram_user_id == telegram_user_id)
    )
    return CreditErasure(
        accounts_deleted=rowcount_of(deleted),
        entries_anonymised=rowcount_of(anonymised),
        plans_anonymised=plans,
        topups_anonymised=topups,
        membership_events_anonymised=events,
        intents_anonymised=rowcount_of(intents),
        recipients_anonymised=rowcount_of(recipients),
    )
