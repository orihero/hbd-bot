"""The entitlement operations: mint, charge, grant, block, touch, forget — and the facade.

Two shapes live here on purpose, and the split is the same one ``hbd.db.admin`` makes:

* **Module-level functions take an ``AsyncSession`` first, take ``now`` as a parameter, let
  exceptions propagate and never commit.** They are the composable half: WU6's stale-debit
  sweep has to run inside ``purge_expired``'s existing transaction, and a function that
  opened its own would either nest a transaction or commit half a purge.
* **:class:`SqlCreditLedger` is the never-throw facade** in the ``SqlKitRepository`` idiom —
  one ``run_guarded`` delegation per method, each owning exactly one
  ``async with self._sessions.begin()``. A refusal raised inside that block rolls the whole
  transaction back, which is precisely how "an insufficient balance leaves NO ledger row and
  NO balance movement" is achieved without a single compensating write.

The statements themselves live in :mod:`hbd.db.credit_sql`, the two-statement erasure
``/forget`` runs in :mod:`hbd.db.credit_erasure` (its asymmetry — delete the balance, keep
the count anonymous — is argued there), and everything that CLOSES a debit — ``settle``,
``refund``, ``consume`` and the hourly sweep — is in :mod:`hbd.db.credit_settlement`, split
off on that seam to keep both files under the repo's line cap and re-exported here so a
caller still sees one module. What follows is the policy for deciding whether to charge.

**Why ``charge`` looks the way it does.** Every step was chosen against a failure mode that
was reproduced rather than imagined:

1. *Open the account with a dialect-dispatched ``INSERT … ON CONFLICT DO NOTHING``, never
   ``session.begin_nested()``.* A SAVEPOINT taken as the FIRST statement of a transaction —
   exactly the shape of a first charge — does not roll back on ``aiosqlite`` while it does
   on Postgres.
2. *Decide replay from the order's NET position (``SUM(delta) WHERE order_id``), not from
   the presence of a debit row.* Net < 0 means "currently paid for" — the bot/worker pair
   and every ARQ retry converge on one charge. Net == 0 means unpaid, INCLUDING an order
   that was charged and then refunded, which must be chargeable again at the next
   generation. Keying replay on "was this order ever debited" renders every
   refunded-then-reauthorised order for free; that is the single sharpest defect this module
   exists to avoid, and ``tests/test_db/test_credits.py`` pins it.
3. *Move the balance with a conditional ``UPDATE`` and a rowcount check* — see
   ``credit_sql.debit_balance``. The balance is deliberately NOT pre-checked with a
   ``SELECT``: a read-then-write is the very race the predicate removes.
4. *Derive the in-flight count from unsettled ledger debits, not from ``orders.state``.*
   ``orchestrator._fail`` writes ``FAILED`` on retryable failures too, so an order sitting in
   ARQ backoff is invisible to a state predicate and a user can stack a second render.

``credit_accounts.balance`` is a second representation of ``SUM(credit_ledger.delta)``. Both
writes always happen in one transaction, and ``verify_balances`` exists because that makes
drift *detectable* rather than impossible — an operator's hand-written ``UPDATE`` can still
desynchronise them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, Result
from hbd.db.base import utc_now
from hbd.db.credit_erasure import forget_account
from hbd.db.credit_settlement import (
    SWEEP_ACTOR,
    consume,
    refund,
    settle,
    settle_stale_debits,
)
from hbd.db.credit_sql import (
    account_state,
    add_credits,
    debit_balance,
    generation_for,
    net_position,
    open_account,
    period_grant_key,
    read_balance,
    upsert_statement,
    write_entry,
)
from hbd.db.enums import CreditEntryKind, CreditReason
from hbd.db.guard import run_guarded
from hbd.db.models.user import UserRow
from hbd.db.plan_sql import claim_plan_song, live_plan
from hbd.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    ChargeOutcome,
    CreditBalance,
    EntitlementError,
    EntitlementPolicy,
    InsufficientCreditsError,
    SettlementOutcome,
    TooManyOrdersInFlightError,
    period_index_for,
    period_start,
)
from hbd.errors import StorageError, ValidationError
from hbd.logging import get_logger

#: ``settle``, ``refund``, ``consume`` and the sweep live in :mod:`hbd.db.credit_settlement`
#: and are re-exported here, because "the entitlement operations" is one seam to a caller
#: even though the file had to be two to stay under the line cap.
__all__ = [
    "SqlCreditLedger",
    "charge",
    "settle",
    "settle_stale_debits",
    "refund",
    "consume",
    "grant",
    "set_blocked",
    "touch",
    "DEFAULT_COST",
    "SWEEP_ACTOR",
    "UNENFORCED_ACTOR",
    "UNENFORCED_KEY_PREFIX",
    "unenforced_key_prefix",
]

_log = get_logger(__name__)

#: One render costs one credit. A parameter rather than a literal because the operator CLI
#: and a future paid tier will price differently. It must be at least 1: a DEBIT row is
#: pinned by ``ck_credit_ledger_delta_matches_kind`` to ``delta < 0``, so ``cost=0`` writes
#: ``delta = 0`` and fails that CHECK inside the customer's transaction. :func:`charge`
#: refuses it at the boundary instead, the way :func:`grant` already refuses a non-positive
#: grant — a comped render is a grant, not a zero-priced charge.
DEFAULT_COST: Final[int] = 1

#: Who signs the shortfall grant a dark deployment writes so that nobody is refused for
#: having run out. Not an operator and not the pipeline: a configuration flag did this, and
#: the audit trail should say so in one word.
UNENFORCED_ACTOR: Final[str] = "unenforced"

#: The first segment of that grant's idempotency key, which is the ONLY thing tying it to the
#: render it paid for. :func:`_cover_the_shortfall` withholds the ``order_id`` COLUMN on
#: purpose — ``net_position`` sums that column, and a grant hanging off the order would net it
#: to zero and make every dark render look unpaid — so the key is where the link had to go.
#: Named rather than spelled inline because the admin read layer matches on it
#: (``db/admin/orders.py``: ``_unenforced_orders``), and a key shape that changed silently would
#: turn every comped order back into an ordinary one on an operator's screen with no test
#: anywhere going red.
UNENFORCED_KEY_PREFIX: Final[str] = "unenforced"


def unenforced_key_prefix(order_id: UUID) -> str:
    """The ``unenforced:{order}:`` prefix every generation of one order's top-up shares.

    A function rather than a second f-string in the reader, so the writer below and the
    admin query that has to recognise its rows are built from one expression. The trailing
    colon is part of the prefix: without it ``unenforced:{a}`` would also prefix-match an
    order id that merely starts with ``a``, and UUID v4s share no prefixes only by luck.
    """
    return f"{UNENFORCED_KEY_PREFIX}:{order_id}:"


#: The language a ``users`` row is born with when the update that created it told us
#: nothing. It MUST equal ``UserRow.ui_language``'s column default (``models/user.py:37-39``),
#: which is ``nullable=False`` — an INSERT that omitted the column, or sent ``None`` into it,
#: would violate the constraint, ``run_guarded`` would return ``Err``, and NO ``users`` row
#: would ever be created for a pre-onboarding account: the block gate would silently stop
#: covering exactly the population ``tests/test_bot/test_gate_middleware.py:138-158`` exists
#: to cover. One spelling for both writers in this module — :func:`set_blocked` supplies it on
#: the insert and withholds it from the update, and :func:`touch` does the same whenever the
#: update it is serving said nothing about a language.
_DEFAULT_UI_LANGUAGE: Final[Language] = Language.UZ_LATN


async def _mint_due_allowance(
    session: AsyncSession, *, telegram_user_id: int, now: datetime, policy: EntitlementPolicy
) -> bool:
    """Mint this window's allowance unless it has already been minted. ``True`` when minted.

    Idempotent on ``grant:period:{telegram_user_id}:{index}``: the unique index on
    ``credit_ledger.idempotency_key`` is the sole authority, so two racing charges produce
    one grant and one loser even though both read the same account state a moment earlier.
    The account's ``allowance_period_index`` is advanced in the SAME statement that moves
    the balance, so the two can never disagree about which window was paid for.

    The window comparison is ``<``, not ``!=``: a clock that jumped backwards must not mint
    a second allowance for a window this account has already been paid for.

    An allowance of zero — how an operator closes the free tier without touching code —
    writes nothing at all rather than a zero-delta GRANT. The delta constraint on
    ``credit_ledger`` reserves ``delta == 0`` for CONSUME alone, and an empty grant is not a
    movement anyone should have to read past in an audit trail.
    """
    if policy.allowance_credits < 1:
        return False
    _, minted_index = await account_state(session, telegram_user_id)
    index = period_index_for(now, period_days=policy.allowance_period_days)
    if minted_index is not None and minted_index >= index:
        return False
    is_first_ever = minted_index is None
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=(CreditReason.SIGNUP_ALLOWANCE if is_first_ever else CreditReason.PERIOD_ALLOWANCE),
        delta=policy.allowance_credits,
        idempotency_key=period_grant_key(telegram_user_id, index),
        actor="allowance",
        now=now,
    ):
        return False
    await add_credits(
        session,
        telegram_user_id=telegram_user_id,
        credits=policy.allowance_credits,
        lifetime=policy.allowance_credits,
        now=now,
        period_index=index,
    )
    return True


async def _mint_plan_song(
    session: AsyncSession, *, telegram_user_id: int, now: datetime, actor: str
) -> bool:
    """Take ONE song out of a live plan and turn it into a credit. ``True`` when minted.

    Modelled line for line on :func:`_mint_due_allowance`, because it is the same idea
    applied to a different meter: a source of songs the customer has NOT yet been given as
    credits mints exactly one, inside the charge's own transaction, guarded so that two
    racing charges cannot both take it.

    The guard is different in shape and the difference is the point. The allowance is keyed
    on a deterministic window index, so the unique index on ``credit_ledger.idempotency_key``
    is the whole concurrency story. A plan has no window: it has a counter, so
    :func:`hbd.db.plan_sql.claim_plan_song` does an optimistic
    ``UPDATE … WHERE songs_used = :seen`` and the LOSER simply mints nothing. Losing that
    race is an ordinary outcome, not an error — the loser's charge falls through to whatever
    balance the account already had, exactly as it would have without a plan.

    The grant's key, ``grant:plan:{plan_id}:{songs_used}``, is built from the counter value
    this call CLAIMED, so it names one specific song of one specific plan. A replay of the
    same claim writes one grant; a thirteenth song has no claim to name and so has no key.

    **Nothing here expires and nothing is ever clawed back.** When ``plan_ends_at`` passes,
    :func:`hbd.db.plan_sql.live_plan` stops returning the row and the remaining songs are
    simply never minted — no sweep, no compensating DEBIT, and no need to tell plan money
    apart from a paid top-up on a balance that has no lots. That is the whole reason the
    minting is lazy; :mod:`hbd.db.plan_sql` argues it at length.
    """
    plan = await live_plan(session, telegram_user_id=telegram_user_id, now=now)
    if plan is None:
        return False
    # Snapshot the counter BEFORE the claim, and build the key from the snapshot. The claim
    # is an ORM-enabled Core UPDATE, so SQLAlchemy synchronises the identity map and
    # ``plan.songs_used`` reads back as the NEW value the moment it succeeds — a key built
    # from the attribute afterwards would name the song after the one this call took, and the
    # very first grant of every plan would be keyed ``:1``.
    claimed = plan.songs_used
    if not await claim_plan_song(session, plan_id=plan.id, songs_used=claimed):
        return False
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.PLAN_SONG,
        delta=1,
        idempotency_key=f"grant:plan:{plan.id}:{claimed}",
        actor=actor,
        now=now,
    ):
        return False
    await add_credits(session, telegram_user_id=telegram_user_id, credits=1, lifetime=1, now=now)
    return True


async def charge(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    actor: str,
    now: datetime,
    cost: int = DEFAULT_COST,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
) -> tuple[ChargeOutcome, CreditBalance]:
    """Pay for ``order_id`` exactly once. See the module docstring for why each step exists.

    Raises an :class:`EntitlementError` subclass on refusal, which the caller's transaction
    boundary turns into a full rollback — so a refused charge leaves no account row it just
    opened, no allowance it just minted and no debit it just wrote.

    ``state`` is read once, with this order left out of its own in-flight count, and reused
    by both refusals. Its BALANCE never decides affordability — that is the conditional
    UPDATE's job — it only explains the refusal to the customer.

    **Every step below runs whether or not ``policy.is_balance_enforced`` is set.** The flag
    reaches exactly one branch: the shortfall at the very end. That is the narrowest reading
    of "the balance check ships dark", and it is the only one that works, because the
    in-flight cap counts unsettled DEBIT rows — a dark mode that skipped this function
    wrote none, so the cap and the block gate silently did nothing in the configuration that
    ships. See ``EntitlementPolicy.is_balance_enforced``.

    **The plan pays first.** :func:`_mint_plan_song` runs whenever a live plan has a song
    left, REGARDLESS of what the balance already holds, because a plan song is the only kind
    that can be lost to the calendar and a bought top-up never expires. Spending the
    non-expiring credit first would be spending the customer's money while their plan quietly
    ran out. The consequence, stated so nobody has to derive it: a REFUND after a failed
    render returns a normal, non-expiring credit and deliberately does NOT decrement
    ``songs_used``, so a customer whose song failed keeps the value on a clock that cannot
    run out.

    ``state`` is read BEFORE the mint, so a refusal built from it — ``_insufficient_credits``
    — may report a balance one lower than the row now holds. Cosmetic only: the number in a
    refusal is explanatory context, and ``debit_balance`` reads the real row.
    """
    if cost < 1:
        raise ValidationError(
            "a render must cost at least one credit",
            context={"telegram_user_id": telegram_user_id, "cost": cost},
        )
    await open_account(session, telegram_user_id=telegram_user_id, now=now)
    await _mint_due_allowance(session, telegram_user_id=telegram_user_id, now=now, policy=policy)
    state = await read_balance(
        session,
        telegram_user_id=telegram_user_id,
        now=now,
        policy=policy,
        exclude_order_id=order_id,
    )
    _refuse_a_blocked_account(state, order_id=order_id)
    if await net_position(session, order_id) < 0:
        return ChargeOutcome.ALREADY_PAID, await _snapshot(session, state, now=now, policy=policy)
    _refuse_a_stacked_account(state, policy=policy)
    # AFTER the ALREADY_PAID short-circuit above, and after the in-flight refusal: a retry of
    # an order that is already paid for returns before it gets here, so no replay of a
    # delivered render can ever consume a second song out of the plan. Before the debit,
    # because the credit it mints is what that debit is about to spend.
    await _mint_plan_song(session, telegram_user_id=telegram_user_id, now=now, actor=actor)
    generation = await generation_for(session, order_id)
    if not await _write_debit(
        session,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
        generation=generation,
        cost=cost,
        actor=actor,
        now=now,
    ):
        # Another writer took this exact debit while we were deciding. It owns the balance
        # move; charging again here is the double-charge the unique index exists to stop.
        return ChargeOutcome.ALREADY_PAID, await _snapshot(session, state, now=now, policy=policy)
    if not await debit_balance(session, telegram_user_id=telegram_user_id, cost=cost, now=now):
        if policy.is_balance_enforced:
            raise _insufficient_credits(state, cost=cost, now=now, policy=policy)
        await _cover_the_shortfall(
            session,
            telegram_user_id=telegram_user_id,
            order_id=order_id,
            generation=generation,
            cost=cost,
            now=now,
        )
    return ChargeOutcome.CHARGED, await _snapshot(session, state, now=now, policy=policy)


async def _snapshot(
    session: AsyncSession, state: CreditBalance, *, now: datetime, policy: EntitlementPolicy
) -> CreditBalance:
    """Re-read the account after a charge decision, counting every order including this one.

    A fresh read rather than arithmetic on ``state``: the returned balance is what a customer
    is shown, and deriving it would make the display right only for as long as nobody adds a
    second write to the transaction.
    """
    return await read_balance(
        session, telegram_user_id=state.telegram_user_id, now=now, policy=policy
    )


def _refuse_a_blocked_account(state: CreditBalance, *, order_id: UUID) -> None:
    """A barred account may not render, however many credits it is holding."""
    if state.is_blocked:
        raise EntitlementError(
            "blocked account attempted a render",
            context={"telegram_user_id": state.telegram_user_id, "order_id": str(order_id)},
        )


def _refuse_a_stacked_account(state: CreditBalance, *, policy: EntitlementPolicy) -> None:
    """One render at a time. The cap refuses abuse, not customers, so it is never flagged off.

    ``charge`` calls this AFTER its replay probe on purpose: an order that is already paid
    for must stay replayable even when the account is at its cap, or the worker would fail a
    render the customer has already been charged for.
    """
    if state.in_flight >= policy.max_orders_in_flight:
        raise TooManyOrdersInFlightError(
            "account already has an unsettled render",
            context={
                "telegram_user_id": state.telegram_user_id,
                "in_flight": state.in_flight,
                "limit": policy.max_orders_in_flight,
            },
        )


def _insufficient_credits(
    state: CreditBalance, *, cost: int, now: datetime, policy: EntitlementPolicy
) -> InsufficientCreditsError:
    """The refusal, with the three scalars the locale string needs to be worth reading.

    ``next_grant_at`` is what makes the copy actionable: the allowance is rolling, so there
    is a real date on which this customer can render again. ``balance`` is the snapshot taken
    before the failed UPDATE, which under a lost race is one credit stale — the number is
    explanatory context, never the decision.
    """
    index = period_index_for(now, period_days=policy.allowance_period_days)
    return InsufficientCreditsError(
        "account cannot afford this render",
        context={
            "telegram_user_id": state.telegram_user_id,
            "balance": state.credits,
            "needed": cost,
            "next_grant_at": period_start(
                index + 1, period_days=policy.allowance_period_days
            ).isoformat(),
        },
    )


async def _cover_the_shortfall(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    generation: int,
    cost: int,
    now: datetime,
) -> None:
    """Grant exactly what this render costs, so a dark deployment refuses nobody.

    Reached only when ``policy.is_balance_enforced`` is False and the account could not
    afford the debit that has just been written. Two things are true and both matter:

    * the balance ends where it started (a grant of ``cost`` followed by a debit of
      ``cost``), so ``credit_accounts.balance == SUM(credit_ledger.delta)`` — the invariant
      ``verify_balances`` exists to police — survives a dark render exactly as it survives
      an enforced one. Writing the debit and *skipping* the balance move would have broken
      it silently on every over-allowance render;
    * ``lifetime_granted`` is NOT moved. It answers "has this account been comped?", and a
      deployment-wide flag being off is not a comp.

    The grant is KEYED on the render's ``(order, generation)`` so that a replay writes one
    row, but it deliberately carries no ``order_id`` COLUMN. That column is what
    ``net_position`` sums, and an order whose grant and debit both hung off it would net to
    zero — which reads as "never paid for" everywhere it matters: ``charge`` would debit the
    same order a second time on its next attempt, and ``settle`` would find nothing to close
    and leave the in-flight slot held until the grace expired. The top-up belongs to the
    ACCOUNT, not to the render, and the ledger has to say so.

    It is also the only row that names the flag — an operator counting ``unenforced_render``
    sees precisely how many renders enforcement would have refused.

    A second failed debit is impossible (this transaction is the only writer that has
    touched the row, and the grant it just made covers the cost exactly), so it is reported
    as a storage fault rather than swallowed into a free render nobody can see.
    """
    _log.warning(
        "the balance check is dark: covering a render this account could not afford",
        extra={
            "telegram_user_id": telegram_user_id,
            "order_id": str(order_id),
            "cost": cost,
        },
    )
    await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.UNENFORCED_RENDER,
        delta=cost,
        idempotency_key=f"{unenforced_key_prefix(order_id)}{generation}",
        actor=UNENFORCED_ACTOR,
        now=now,
    )
    await add_credits(session, telegram_user_id=telegram_user_id, credits=cost, lifetime=0, now=now)
    if not await debit_balance(session, telegram_user_id=telegram_user_id, cost=cost, now=now):
        raise StorageError(
            "the covered balance still could not pay for the render",
            context={"telegram_user_id": telegram_user_id, "order_id": str(order_id)},
        )


async def _write_debit(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    generation: int,
    cost: int,
    actor: str,
    now: datetime,
) -> bool:
    """Append the debit entry. ``False`` means a concurrent writer got there first."""
    return await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-cost,
        idempotency_key=f"debit:{order_id}:{generation}",
        actor=actor,
        now=now,
        order_id=order_id,
        generation=generation,
    )


async def grant(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    credits: int,
    idempotency_key: str,
    actor: str,
    now: datetime,
    reason: CreditReason = CreditReason.ADMIN_GRANT,
) -> bool:
    """Add credits on an operator's say-so. ``True`` when this call wrote the grant.

    The key belongs to the caller so a CLI run retried after a timeout tops the account up
    once. A non-positive grant is rejected at the boundary rather than left to
    ``ck_credit_ledger_delta_matches_kind``, so the operator gets a message about their
    input instead of a constraint name.
    """
    if credits < 1:
        raise ValidationError(
            "a grant must add at least one credit",
            context={"telegram_user_id": telegram_user_id, "credits": credits},
        )
    await open_account(session, telegram_user_id=telegram_user_id, now=now)
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=reason,
        delta=credits,
        idempotency_key=idempotency_key,
        actor=actor,
        now=now,
    ):
        return False
    await add_credits(
        session, telegram_user_id=telegram_user_id, credits=credits, lifetime=credits, now=now
    )
    return True


async def set_blocked(
    session: AsyncSession, *, telegram_user_id: int, is_blocked: bool, now: datetime
) -> None:
    """Bar or unbar an account, creating its ``users`` row if there is none.

    An UPSERT rather than an ``UPDATE`` with a rowcount check. The reason has narrowed but
    not gone away. There are now THREE writers of a ``users`` row —
    ``users_sql.ensure_user`` from ``repository._create_order``, the same function from
    ``SqlUserProfiles.record_language`` at first contact, and :func:`touch` on every inbound
    update — so a person who has spoken to the bot since the onboarding deploy does have a
    row. An account that has not spoken since then still does not, and that is exactly the
    account an operator reaches for this function to bar: a rowcount-checked ``UPDATE``
    would silently fail on precisely the population it exists to serve.

    ``ui_language`` is supplied for the insert only, from :data:`_DEFAULT_UI_LANGUAGE`;
    blocking someone must never change the language they read.
    """
    await session.execute(
        upsert_statement(
            session,
            UserRow,
            {
                "id": uuid4(),
                "telegram_user_id": telegram_user_id,
                "ui_language": _DEFAULT_UI_LANGUAGE,
                "is_blocked": is_blocked,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["telegram_user_id"],
            set_={"is_blocked": is_blocked, "updated_at": now},
        )
    )


async def touch(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    ui_language: Language | None,
    now: datetime,
) -> None:
    """Record that this account is alive and, when the update told us, which language it reads.

    ``ui_language`` is ``Language | None`` because ``gate._decide`` used to pass
    ``resolve_language(state)``, which answers with the FALLBACK language whenever there is
    no draft — so within sixty seconds of any ``state.clear()`` the drain stamped ``UZ_LATN``
    over the customer's real choice, and the settings screen appeared to forget itself for no
    reason a reader of either file could see. ``None`` now means "this update said nothing
    about the language", and the column is then left exactly as it was.

    **The key is omitted from BOTH halves of the UPSERT, not just from ``set_``.**
    ``UserRow.ui_language`` is ``nullable=False`` (``models/user.py:37-39``), so conditioning
    only the ``ON CONFLICT`` clause would send ``None`` into the INSERT; the constraint fires,
    ``run_guarded`` turns it into an ``Err``, and no ``users`` row is ever created for an
    account that has not onboarded yet — which silently disables the block gate for precisely
    the people an operator most wants to block. On the insert the column therefore takes
    :data:`_DEFAULT_UI_LANGUAGE`, exactly as :func:`set_blocked` above supplies it for the
    insert and withholds it from the update.

    ``is_blocked`` is deliberately absent from the update clause: a touch arrives on every
    inbound update, and one that reset the flag would unblock an abuser the moment they
    sent their next message.
    """
    set_: dict[str, Any] = {"last_seen_at": now, "updated_at": now}
    if ui_language is not None:
        set_["ui_language"] = ui_language
    await session.execute(
        upsert_statement(
            session,
            UserRow,
            {
                "id": uuid4(),
                "telegram_user_id": telegram_user_id,
                "ui_language": (ui_language if ui_language is not None else _DEFAULT_UI_LANGUAGE),
                "is_blocked": False,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["telegram_user_id"],
            set_=set_,
        )
    )


class SqlCreditLedger:
    """``EntitlementStore`` over Postgres (or SQLite in tests). Never raises, never leaks a row.

    Structural implementation, not a subclass: the protocol is ``@runtime_checkable`` and
    satisfied structurally, so persistence does not import an ABC to be substitutable.

    One transaction per public method, opened here and nowhere else. Every refusal raised
    by the functions above therefore rolls its whole transaction back before ``run_guarded``
    converts it into an ``Err``, which is what makes "no ledger row, no balance movement"
    true without a single compensating write.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._policy = policy
        self._clock = clock

    @property
    def policy(self) -> EntitlementPolicy:
        """The numbers this store enforces. Read-only: a policy is injected, never edited."""
        return self._policy

    # -- EntitlementStore ---------------------------------------------------
    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = DEFAULT_COST
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        return await run_guarded(
            "credits.charge",
            lambda: self._charge(telegram_user_id, order_id, actor, cost),
            telegram_user_id=telegram_user_id,
            order_id=str(order_id),
        )

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        return await run_guarded(
            "credits.settle",
            lambda: self._settle(telegram_user_id, order_id, outcome, actor),
            telegram_user_id=telegram_user_id,
            order_id=str(order_id),
            outcome=str(outcome),
        )

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        return await run_guarded(
            "credits.grant",
            lambda: self._grant(telegram_user_id, credits, idempotency_key, actor),
            telegram_user_id=telegram_user_id,
            credits=credits,
        )

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        return await run_guarded(
            "credits.balance_for",
            lambda: self._balance_for(telegram_user_id, exclude_order_id),
            telegram_user_id=telegram_user_id,
        )

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        return await run_guarded(
            "credits.set_blocked",
            lambda: self._set_blocked(telegram_user_id, is_blocked),
            telegram_user_id=telegram_user_id,
            is_blocked=is_blocked,
        )

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        return await run_guarded(
            "credits.touch",
            lambda: self._touch(telegram_user_id, ui_language),
            telegram_user_id=telegram_user_id,
        )

    async def forget(self, telegram_user_id: int) -> Result[None]:
        return await run_guarded(
            "credits.forget",
            lambda: self._forget(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    # -- implementations ----------------------------------------------------
    async def _charge(
        self, telegram_user_id: int, order_id: UUID, actor: str, cost: int
    ) -> tuple[ChargeOutcome, CreditBalance]:
        async with self._sessions.begin() as session:
            return await charge(
                session,
                telegram_user_id=telegram_user_id,
                order_id=order_id,
                actor=actor,
                now=self._clock(),
                cost=cost,
                policy=self._policy,
            )

    async def _settle(
        self, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> bool:
        async with self._sessions.begin() as session:
            return await settle(
                session,
                telegram_user_id=telegram_user_id,
                order_id=order_id,
                outcome=outcome,
                actor=actor,
                now=self._clock(),
            )

    async def _grant(
        self, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> CreditBalance:
        now = self._clock()
        async with self._sessions.begin() as session:
            await grant(
                session,
                telegram_user_id=telegram_user_id,
                credits=credits,
                idempotency_key=idempotency_key,
                actor=actor,
                now=now,
            )
            return await read_balance(
                session, telegram_user_id=telegram_user_id, now=now, policy=self._policy
            )

    async def _balance_for(
        self, telegram_user_id: int, exclude_order_id: UUID | None
    ) -> CreditBalance:
        async with self._sessions.begin() as session:
            return await read_balance(
                session,
                telegram_user_id=telegram_user_id,
                now=self._clock(),
                policy=self._policy,
                exclude_order_id=exclude_order_id,
            )

    async def _set_blocked(self, telegram_user_id: int, is_blocked: bool) -> None:
        async with self._sessions.begin() as session:
            await set_blocked(
                session,
                telegram_user_id=telegram_user_id,
                is_blocked=is_blocked,
                now=self._clock(),
            )

    async def _touch(self, telegram_user_id: int, ui_language: Language | None) -> None:
        async with self._sessions.begin() as session:
            await touch(
                session,
                telegram_user_id=telegram_user_id,
                ui_language=ui_language,
                now=self._clock(),
            )

    async def _forget(self, telegram_user_id: int) -> None:
        """One transaction, so the ledger cannot end up anonymous with the balance intact.

        Logged at INFO with EVERY count because this is a data-subject request: when
        someone asks later whether their erasure ran, the answer has to be in the log of
        the process that ran it and not inferred from the absence of a row. A counter that
        :class:`hbd.db.credit_erasure.CreditErasure` reports and this line drops would make
        the record of the request quietly incomplete, so a new receipt table adds a field
        here as well as there.
        """
        async with self._sessions.begin() as session:
            erased = await forget_account(session, telegram_user_id=telegram_user_id)
        _log.info(
            "credit record erased on request",
            extra={
                "telegram_user_id": telegram_user_id,
                "accounts_deleted": erased.accounts_deleted,
                "entries_anonymised": erased.entries_anonymised,
                "plans_anonymised": erased.plans_anonymised,
                "topups_anonymised": erased.topups_anonymised,
                # The three below were reported by ``CreditErasure`` and dropped here, which
                # is precisely the incompleteness the docstring above forbids: an erasure
                # that anonymised nine hundred delivery rows logged four zeroes and said
                # nothing about them.
                "membership_events_anonymised": erased.membership_events_anonymised,
                "intents_anonymised": erased.intents_anonymised,
                "recipients_anonymised": erased.recipients_anonymised,
            },
        )
