"""What a paid sale writes, as two functions that two different processes can both call.

``SqlPurchaseLedger`` used to own both halves of a purchase: the POLICY ("a paid single song
is one receipt and one credit, written under one key from one clock") and the TRANSACTION
that carried it. That was correct for exactly as long as there was one process writing money
rows. A redirect rail is a second one — its settlement arrives as an inbound HTTP request in
a different service — and it cannot call ``fulfil_single``, because its own correctness rests
on writing the receipt, the credit grant, the rail transaction's state flip and the intent
claim in ONE commit. A method that opens its own session can only be called from OUTSIDE a
transaction, so the only thing the gateway could have done with ``SqlPurchaseLedger`` was
copy it. **Two copies of "what a paid sale writes" is one copy that drifts, and the thing it
drifts on is money.** So the policy moves down here, where a caller supplies the transaction,
and the ledger keeps the transaction and the ``Result`` boundary that were always its job.

Written to the same rule as :mod:`hbd.db.credit_sql`, :mod:`hbd.db.plan_sql` and
:mod:`hbd.db.topup_sql` one level up: the session comes FIRST and POSITIONAL, it is NOT
owned, ``now`` is a parameter and nothing here commits. The difference in altitude is the
whole point — those modules hold one STATEMENT each, these hold one SALE each, and a sale is
the unit two rails have to agree on.

**THE REFUSALS TRAVEL WITH THE WRITES, AS THE FIRST STATEMENTS, AND THAT IS WHY THIS
EXTRACTION WAS WORTH DOING SEPARATELY.** Before it, ``_refuse_an_unpaid_purchase`` and
``_refuse_a_product_that_is_not_a_topup`` ran in the CALLER — above ``now = self._clock()``
and above ``self._sessions.begin()`` — so a mechanical reading of "move the body" starts at
the clock read and leaves both guards behind. That refactor compiles, passes every existing
test, and quietly hands the one process that writes money rows from an inbound internet
request a write primitive with no last-line defence. ``_refuse_an_unpaid_purchase``'s own
docstring says the guard "has to exist before the rail that needs it does": the rail is here
now, so the guard is here too, ahead of the first write in each function.

Raising them INSIDE the caller's transaction rather than before it is not a weakening. Both
are pure reads of a frozen :class:`hbd.checkout.Purchase`, neither writes anything before it
raises, and the caller's ``async with sessions.begin()`` rolls back on the way out — so "an
unpaid purchase leaves no row and no credit" is still achieved by an absence of writes and
not by a compensating one. The gateway gets something stronger for free: a refusal here also
unwinds the rail transaction's state flip that was made earlier in the SAME commit, which a
guard sitting in front of the transaction could not have done.

**Neither function reads the balance and neither returns one.**
:func:`hbd.db.credit_sql.read_balance` projects a due allowance and a live plan's unminted
songs, and it can only do that against the :class:`hbd.entitlements.EntitlementPolicy` the
WORKER will charge under. Keeping it in the caller means the bot reads the balance with the
policy it was built with, and the gateway — which sells credits and never spends them — holds
no policy at all and therefore cannot drift from the bot's.

**Nothing here is wrapped in :func:`hbd.db.guard.run_guarded` and nothing here returns
``Result``.** The never-throw boundary belongs at the public method of whichever ledger owns
the transaction, because that is the frame that decides whether to commit. An ``Err``
returned from inside somebody else's ``begin()`` block would be a refusal that had already
been swallowed by the time the transaction chose to commit anyway — the exact failure the
``Result`` discipline exists to prevent.

:func:`write_plan_sale` returns a ``PlanPurchaseRow``. Rule 15 governs the ``hbd.db`` PACKAGE
boundary, not this file, and a mapped row may move freely within it; the two callers want
different things out of that row — the bot turns it into a :class:`hbd.checkout.PlanState`
for a screen, a rail only needs to know a row exists under its key — so handing back the row
leaves that choice with the caller instead of inventing a second frozen view here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from hbd.checkout import Product, Purchase
from hbd.db.credits import grant
from hbd.db.enums import CreditReason, PlanKind, TopupKind
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.plan_sql import current_plan, insert_plan, plan_by_key
from hbd.db.topup_sql import insert_topup
from hbd.errors import PaymentError, StorageError
from hbd.logging import get_logger

__all__ = ["write_single_sale", "write_plan_sale", "CHECKOUT_ACTOR"]

_log = get_logger(__name__)

#: Who signs a purchase's ledger row. Not ``bot`` and not an operator: a customer's own
#: payment did this, and an operator reading ``credit_ledger.actor`` months later must be able
#: to tell a bought song from a comped one at a glance, without joining anything.
#:
#: It lives beside the ``grant`` call rather than beside the ledger that used to make it,
#: because EVERY rail that fulfils a sale must sign with the same string — an actor that said
#: ``payme`` on one rail and ``checkout`` on another would split one population of paid songs
#: into two and make "how many songs were bought?" a UNION. ``hbd.db.purchases`` re-exports it
#: so the name it has always been imported under keeps resolving.
CHECKOUT_ACTOR: str = "checkout"

#: How many credits one single-song purchase puts on the balance. Named once and passed to
#: BOTH writes, so the receipt and the grant cannot disagree about what was sold: a literal
#: ``1`` in two places is how a future three-song bundle comes to grant three and record one.
_TOPUP_CREDITS: Final[int] = 1


async def write_single_sale(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    purchase: Purchase,
    idempotency_key: str,
    now: datetime,
) -> None:
    """One paid single song becomes one receipt and one credit, once, in the caller's commit.

    Refuses first and writes second: an unpaid purchase and a purchase that is not a one-off
    product are both rejected before ``insert_topup`` is reached, so this function is safe to
    call from a process whose input is an HTTP body somebody else composed.

    Calls the MODULE-LEVEL :func:`hbd.db.credits.grant`, which accepts ``reason=`` even
    though ``EntitlementStore.grant`` does not — that protocol speaks no database enum
    (``hbd.entitlements`` argues why it must not), so the only way a purchase can be
    distinguishable from an operator's comp in the ledger is to bypass the protocol and
    call the function. The distinction is not cosmetic: ``admin_grant`` means somebody
    gave a song away and ``topup_purchase`` means somebody paid for one, and a refund
    conversation needs to know which.

    **The receipt is written FIRST, deliberately.** Both writes are in one transaction,
    so today they land together or not at all; but if a future refactor ever splits
    them, a run that recorded a sale and granted no credit is far less bad than one that
    granted a song with no record of the money — the same ordering argument
    :func:`hbd.db.credit_erasure.forget_account` makes for receipts-first, balance-last.
    The ledger GRANT carries no amount and no rail and never will, so a lost receipt is
    revenue that cannot be reconstructed from anything.

    Both rows take the SAME ``now`` and the SAME ``idempotency_key``. That is what makes
    the two populations comparable: the admin surface counts the sales that were recorded
    before amounts were, with a correlated ``NOT EXISTS`` on that shared key, and a
    windowed count of receipts and a windowed count of grants must never straddle a
    boundary differently. The key is the CALLER's, and on a redirect rail it is the same
    string the bot minted when it opened the payment — which is precisely how a settlement
    arriving twice, or a genuine settlement arriving after an operator forced one, lands on
    the same two unique indexes and writes nothing the second time.

    A replayed key writes NEITHER row, and this function reports nothing about that: each
    write is independently insert-or-ignore on its own unique index, so a replay writes
    nothing twice and the caller's own answer — an unchanged balance, or a rail's
    acknowledgement — is the correct one either way. Returning ``None`` rather than a "did I
    win?" boolean is deliberate: no caller may branch on it, because the second caller of a
    replayed key is entitled to exactly the same successful outcome as the first.
    """
    _refuse_an_unpaid_purchase(purchase, telegram_user_id=telegram_user_id)
    _refuse_a_product_that_is_not_a_topup(purchase, telegram_user_id=telegram_user_id)
    await insert_topup(
        session,
        telegram_user_id=telegram_user_id,
        product=TopupKind(purchase.product.value),
        credits_granted=_TOPUP_CREDITS,
        amount_minor=purchase.amount_minor,
        currency=purchase.currency,
        provider=purchase.provider,
        reference=purchase.reference,
        idempotency_key=idempotency_key,
        now=now,
    )
    await grant(
        session,
        telegram_user_id=telegram_user_id,
        credits=_TOPUP_CREDITS,
        idempotency_key=idempotency_key,
        actor=CHECKOUT_ACTOR,
        now=now,
        reason=CreditReason.TOPUP_PURCHASE,
    )


async def write_plan_sale(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    purchase: Purchase,
    songs: int,
    days: int,
    idempotency_key: str,
    now: datetime,
) -> PlanPurchaseRow:
    """Open a plan, or hand back the one already running. Writes no credits at all.

    Refuses first, exactly as :func:`write_single_sale` does, and for the same reason: this
    is reachable from a process that is answering the public internet.

    **One plan at a time**, decided by :func:`hbd.db.plan_sql.current_plan`, which ignores
    ``songs_used`` on purpose: a customer who spent all twelve songs on day three still
    OWNS the starter plan until day thirty, and selling them a second one would write a
    new end date over the one they already paid for while the old row kept minting
    nothing. Such a customer is offered the single-song top-up instead — which is why the
    two predicates on :class:`hbd.checkout.PlanState` are named separately.

    Returning the running plan rather than an error is deliberate. This is reached from a
    button tap, and "you already have this" is a true, complete answer that redraws the
    right screen; an ``Err`` here would make a harmless second tap look like a failed
    payment. A rail's settlement gets the same answer for a different reason: it has already
    taken the money, so the only useful thing it can be told is which plan the customer now
    holds.

    Returns the row rather than a frozen view because the two callers want different things
    from it — see the module docstring. The row belongs to the caller's session and dies with
    the caller's transaction, which is why it may not leave ``hbd.db``.
    """
    _refuse_an_unpaid_purchase(purchase, telegram_user_id=telegram_user_id)
    _refuse_a_product_that_is_not_a_plan(purchase, telegram_user_id=telegram_user_id)
    running = await current_plan(session, telegram_user_id=telegram_user_id, now=now)
    if running is not None:
        _log.info(
            "a plan is already running; the new purchase opened nothing",
            extra={
                "telegram_user_id": telegram_user_id,
                "reference": purchase.reference,
                "plan_ends_at": running.plan_ends_at.isoformat(),
            },
        )
        return running
    written = await insert_plan(
        session,
        telegram_user_id=telegram_user_id,
        plan=PlanKind.STARTER,
        songs_included=songs,
        amount_minor=purchase.amount_minor,
        currency=purchase.currency,
        provider=purchase.provider,
        reference=purchase.reference,
        idempotency_key=idempotency_key,
        plan_ends_at=now + timedelta(days=days),
        now=now,
    )
    row = await plan_by_key(session, idempotency_key)
    if row is None:
        # The insert either wrote the row or lost to one written under this exact key, so a
        # read-back that finds nothing means the row vanished inside this transaction. That
        # cannot happen today; reporting it as a storage fault rolls the whole purchase back
        # rather than inventing a PlanState the database does not hold — and on a rail it
        # rolls back the settlement that was being written alongside it, so the rail retries
        # rather than recording a sale nobody can find.
        raise StorageError(
            "the plan disappeared between being written and being read back",
            context={
                "telegram_user_id": telegram_user_id,
                "idempotency_key": idempotency_key,
                "was_written": written is not None,
            },
        )
    return row


def _refuse_an_unpaid_purchase(purchase: Purchase, *, telegram_user_id: int) -> None:
    """Nothing is written for a :class:`hbd.checkout.Purchase` that is not paid.

    The FIRST statement of both write primitives, ahead of every insert, so the refusal
    cannot leave a half-written row: nothing has been written when it raises, and the
    caller's transaction rolls back around it anyway. The ``Result`` boundary at the caller's
    public method turns it into an ``Err`` and the customer sees "that did not go through,
    and nothing was charged", which is the literal truth.

    This is not defensive programming against a stub that always reports paid. A redirect
    rail — which is what Payme actually is — returns an UNPAID :class:`hbd.checkout.Purchase`
    carrying a ``checkout_url`` as the normal first half of a payment, and completes it later
    from its own webhook. Granting on one would hand out a free song for every abandoned
    checkout, so the guard has to exist before the rail that needs it does.

    It now lives INSIDE the write rather than in front of it precisely because that rail
    exists: the process that settles a redirect payment does not go through
    ``SqlPurchaseLedger`` at all, and a guard that stayed with the ledger would have
    protected only the caller that never needed protecting.
    """
    if not purchase.is_paid:
        raise PaymentError(
            "refusing to fulfil a purchase the provider has not reported paid",
            context={
                "telegram_user_id": telegram_user_id,
                "provider": purchase.provider,
                "reference": purchase.reference,
                "product": purchase.product.value,
            },
        )


def _refuse_a_product_that_is_not_a_topup(purchase: Purchase, *, telegram_user_id: int) -> None:
    """Only a one-off product may be fulfilled as a top-up. A plan goes through the sibling.

    :class:`hbd.checkout.Product` is the catalogue and holds ``STARTER`` as well as
    ``SINGLE``; :class:`hbd.db.enums.TopupKind` deliberately mirrors only the one-off half,
    because a ``topup_purchases`` row claiming ``starter`` would assert something the rest of
    the schema forbids — a plan's receipt is ``plan_purchases``, and a plan grants no credit
    at purchase. So a misrouted plan must be refused here rather than reshaped into a top-up.

    Raised beside :func:`_refuse_an_unpaid_purchase` as the second statement of
    :func:`write_single_sale`, and as a ``PaymentError`` rather than as the bare
    ``ValueError`` ``TopupKind(...)`` would raise on an unknown value.
    :func:`hbd.db.guard.run_guarded` catches ``HbdError``, ``IntegrityError``,
    ``SQLAlchemyError`` and pydantic's ``ValidationError`` and nothing else, so a
    ``ValueError`` would escape the ``Result`` boundary every caller of this module promises
    never to breach — a refusal that became an unhandled exception in a callback handler, or
    a 500 on an endpoint whose whole protocol requires it to answer 200.
    """
    if purchase.product is not Product.SINGLE:
        raise PaymentError(
            "refusing to fulfil a purchase that is not a single-song top-up",
            context={
                "telegram_user_id": telegram_user_id,
                "provider": purchase.provider,
                "reference": purchase.reference,
                "product": purchase.product.value,
            },
        )


def _refuse_a_product_that_is_not_a_plan(purchase: Purchase, *, telegram_user_id: int) -> None:
    """The mirror image, and the one guard this extraction ADDS rather than moves.

    ``_start_plan`` never carried a product guard, and until now it did not need one: its
    single caller is the ``else`` arm of a two-member branch on
    :class:`hbd.checkout.Product`, so a ``SINGLE`` purchase could not reach it. That
    argument dies the moment a second caller exists. A rail routes on the product recorded
    on its own intent, not on a branch in a handler, and a misrouted single would be written
    as a twelve-song ``plan_purchases`` row — hard-coded ``PlanKind.STARTER``, an invented
    thirty-day end date, and a customer who paid for one song holding a plan that blocks the
    sale of a real one until it expires. That is a worse outcome than the top-up guard
    prevents, because it is silent: every column would be valid and no constraint would fire.

    Symmetry is the secondary reason and idempotency is not a defence: the two receipt tables
    key on the SAME ``idempotency_key`` string, so a single-song key spent on a plan row is a
    key the correct write can then never use. The refusal has to come before the insert, not
    after it.
    """
    if purchase.product is not Product.STARTER:
        raise PaymentError(
            "refusing to open a plan for a purchase that is not a plan product",
            context={
                "telegram_user_id": telegram_user_id,
                "provider": purchase.provider,
                "reference": purchase.reference,
                "product": purchase.product.value,
            },
        )
