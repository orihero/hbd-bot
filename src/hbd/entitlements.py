"""What an account is allowed to render, why it was refused, and the store that decides.

**This module is a leaf and must stay one.** It imports ``hbd.contracts`` and ``hbd.errors``
and nothing else, and it may never import ``hbd.db``. That is not tidiness: putting these
types in ``hbd.contracts`` was tried and reproduced a real circular import, because a
protocol that named ``hbd.db.enums.CreditReason`` made ``contracts`` import the ``hbd.db``
package, whose ``__init__`` imports ``hbd.db.attempts``, which imports ``hbd.contracts``.
Two consequences follow and both are deliberate:

* :class:`EntitlementStore` speaks :class:`SettlementOutcome`, not ``CreditEntryKind`` /
  ``CreditReason``. The persistence layer translates one into the other in
  ``hbd.db.credits``; the callers (the worker gate, the settlement hook, the CLI) never
  name a database enum, so the cycle cannot come back through a call site either.
* ``hbd.db`` imports *this* module, never the reverse. There is no back-edge to find.

``hbd.contracts`` is also already 857 lines, over this repo's own 800-line cap, which is
the second reason nothing below lives there.

**The allowance is rolling, not a lifetime grant** — 3 credits per 30 days, minted
idempotently on ``grant:period:{telegram_user_id}:{index}``. The period index is computed
here, from a clock the caller injects, so the mint is deterministic across the bot process,
the worker process and a test that moves time by a month. A lifetime grant would make every
customer's second song a permanent refusal, which the product's own delivery copy ("Whose
turn next?") walks them straight into; a rolling window also makes the refusal actionable,
because there is a real date on which the next credit opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hbd.contracts import Language, Result
from hbd.errors import (
    ConfigError,
    EntitlementError,
    InsufficientCreditsError,
    TooManyOrdersInFlightError,
    ValidationError,
)

__all__ = [
    # Values
    "ChargeOutcome",
    "SettlementOutcome",
    "CreditBalance",
    "BalanceDrift",
    # Policy
    "EntitlementPolicy",
    "DEFAULT_ENTITLEMENT_POLICY",
    "derive_settlement_grace_s",
    "resolve_entitlement_policy",
    "period_index_for",
    "period_start",
    # Seam
    "EntitlementStore",
    # Refusals, re-exported so one import serves a caller that both calls and catches.
    # They are DEFINED in hbd.errors because that module is the single error hierarchy and
    # imports nothing at all; re-exporting keeps that true without a second import line at
    # every gate.
    "EntitlementError",
    "InsufficientCreditsError",
    "TooManyOrdersInFlightError",
]

#: The instant every period index is measured from. Fixed forever: changing it would
#: renumber every window and re-mint an allowance for every account that ever had one.
_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)

_DEFAULT_ALLOWANCE_CREDITS: Final[int] = 3
_DEFAULT_ALLOWANCE_PERIOD_DAYS: Final[int] = 30
#: One render at a time. The cap is an abuse rail, not a product tier: it refuses stacking,
#: which is what turns one account into a queue-filling render farm.
_DEFAULT_MAX_ORDERS_IN_FLIGHT: Final[int] = 1
#: The queue ladder as ``hbd.config`` ships it: ``queue_job_timeout_s`` (config.py:314),
#: ``queue_max_tries`` (config.py:320) and ``provider_backoff_base_s`` (config.py:214).
#: Restated as literals because this module is a LEAF and may not import ``hbd.config`` —
#: and pinned against the real thing by
#: ``tests/test_runtime/test_cron.py::test_the_shipped_queue_defaults_derive_the_shipped_grace``,
#: so a change to either side is a red test rather than a sweep that refunds live jobs.
_SHIPPED_JOB_TIMEOUT_S: Final[float] = 900.0
_SHIPPED_MAX_TRIES: Final[int] = 5
_SHIPPED_BACKOFF_BASE_S: Final[float] = 5.0


def derive_settlement_grace_s(
    *, job_timeout_s: float, max_tries: int, backoff_base_s: float
) -> int:
    """The longest an order can legitimately still be alive, given the queue's own ladder.

    Defined here, and above the default it produces, because the grace is not a taste
    setting: it is the answer to "could this debit's job still come back?", and the queue is
    the only thing that knows. An attempt may burn a whole ``job_timeout_s``, arq will start
    ``max_tries`` of them, and ``jobs._defer_seconds`` parks attempt *n* for
    ``backoff_base_s * n`` before the next one — so the honest bound is every timeout plus
    every deferral in between.

    Getting it too SHORT is the expensive direction and the reason this is arithmetic rather
    than a round number: the in-flight cutoff and WU6's sweep both read it, so a grace under
    the ladder lets the sweep refund an order that is sitting in backoff and about to render
    — the customer gets their credit back AND their song. Too long only delays the tidy-up
    of a debit whose job really did die.

    Rounded up, because a fractional second of grace is a fractional second of that race.
    """
    deferrals = backoff_base_s * (max_tries - 1) * max_tries / 2
    return ceil(job_timeout_s * max_tries + deferrals)


#: How long a debit may sit unsettled before it stops counting against the in-flight cap and
#: before the sweep may close it. A *self-healing* window, not a promise: a job that dies
#: without settling must not wedge its customer out forever, and WU6's
#: ``hbd.db.credits.settle_stale_debits`` is what closes such a debit properly.
#:
#: Derived rather than chosen (4550s under the shipped defaults). A round hour here — the
#: literal this replaced — is SHORTER than the 4500s of job timeouts arq alone will spend on
#: one order, which would have made the sweep refund orders that were still being rendered.
_DEFAULT_SETTLEMENT_GRACE_S: Final[int] = derive_settlement_grace_s(
    job_timeout_s=_SHIPPED_JOB_TIMEOUT_S,
    max_tries=_SHIPPED_MAX_TRIES,
    backoff_base_s=_SHIPPED_BACKOFF_BASE_S,
)


class ChargeOutcome(StrEnum):
    """What a call to ``charge`` actually did to the ledger.

    ``ALREADY_PAID`` is the reason the gate can run twice per order (once at the Confirm
    tap, once in the worker, and again on every ARQ retry) without charging twice. It is
    decided from the order's NET position — ``SUM(delta) WHERE order_id`` — and NOT from
    the presence of a debit row, which is the distinction the whole design turns on: a
    refunded order returns to net 0 and must be chargeable again, while an order that is
    currently paid for must never be charged a second time.
    """

    CHARGED = "charged"
    ALREADY_PAID = "already_paid"


class SettlementOutcome(StrEnum):
    """How an order ended, in the only vocabulary the ledger needs to close its debit.

    Deliberately three members rather than a pass-through of ``OrderState``: the policy is
    that DELIVERED and NOT_DELIVERED settle identically (the kit exists and is
    redeliverable, so refunding it would let someone block the bot mid-render for unlimited
    free songs) while only a terminal failure gives the credit back. Keeping them distinct
    here costs nothing and preserves *why* in the audit trail, since each maps to its own
    ``CreditReason``.
    """

    #: The customer has their kit. The credit bought something; it is consumed.
    DELIVERED = "delivered"
    #: The kit exists but Telegram would not take it. Still consumed — see above.
    NOT_DELIVERED = "not_delivered"
    #: Terminal failure, moderation rejection included. Refunded: the progress copy already
    #: promises "you have not lost anything", and this is what makes that true.
    FAILED = "failed"


class CreditBalance(BaseModel):
    """One account's entitlement, as every gate and the ``/balance`` command see it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    telegram_user_id: int
    #: Spendable credits, INCLUDING an allowance that is due but not yet minted — a
    #: read-only gate must not refuse a customer the writer would have granted a moment
    #: later. Deliberately **not** bounded with ``ge=0``: the database constraint is what
    #: keeps a real balance non-negative, and a reader that raised on a drifted row would
    #: turn a reporting problem into an outage exactly when an operator needs to see it.
    credits: int
    #: Debits for OTHER orders that are neither consumed nor refunded, within the
    #: settlement grace. Derived from the ledger rather than from ``orders.state``, which
    #: is verified broken for this purpose: ``orchestrator._fail`` writes FAILED on
    #: retryable failures too, so an order sitting in ARQ backoff would be invisible.
    in_flight: int = Field(ge=0)
    is_blocked: bool


class BalanceDrift(BaseModel):
    """One account whose stored balance disagrees with its own ledger.

    Two representations of the same fact are the price of a lock-free, portable debit
    (``UPDATE … WHERE balance >= :cost``), so drift is made *detectable* rather than
    assumed impossible. Every row this reports is a bug or a hand-written ``UPDATE``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    telegram_user_id: int
    balance: int
    ledger_total: int


@dataclass(frozen=True, slots=True)
class EntitlementPolicy:
    """The numbers the entitlement layer runs on. Immutable, injected, never ambient."""

    allowance_credits: int = _DEFAULT_ALLOWANCE_CREDITS
    allowance_period_days: int = _DEFAULT_ALLOWANCE_PERIOD_DAYS
    max_orders_in_flight: int = _DEFAULT_MAX_ORDERS_IN_FLIGHT
    settlement_grace_s: int = _DEFAULT_SETTLEMENT_GRACE_S
    #: ``Settings.credits_enforced``. **The narrowest possible reading of "dark": the only
    #: thing this switches off is refusing a customer who has run out.** Everything else —
    #: opening the account, minting the rolling allowance, the block gate, the in-flight
    #: cap, the debit row and its settlement — runs exactly as it will when the flag is on.
    #:
    #: It has to be that narrow. The in-flight cap is derived from UNSETTLED DEBIT ROWS
    #: (``credit_sql.count_in_flight``; a counter and ``orders.state`` were both tried and
    #: rejected), so a "dark" mode that skipped the charge wrote no debits, left
    #: ``in_flight`` permanently 0, and made the cap — the one control that stops a single
    #: account queueing unlimited concurrent renders — silently do nothing in the
    #: configuration that actually ships. Same for the block gate, which is the worker's
    #: only defence against an account blocked AFTER its job was queued.
    #:
    #: What a dark deployment therefore never does is refuse anyone for lack of credits:
    #: when the balance is short, ``hbd.db.credits.charge`` covers the shortfall with a
    #: ``CreditReason.UNENFORCED_RENDER`` grant and proceeds. Those rows are also the
    #: measurement — counting them says exactly how many renders enforcement would have
    #: refused, before an operator turns it on.
    is_balance_enforced: bool = True

    def __post_init__(self) -> None:
        """Refuse a policy that cannot be enforced, at construction rather than at charge.

        ``allowance_period_days`` is a divisor, so a zero here would be a
        ``ZeroDivisionError`` inside a transaction on a customer's first render — a
        ``ConfigError`` at startup is the same bug found by the operator instead.
        """
        if self.allowance_period_days < 1:
            raise ConfigError(
                "allowance_period_days must be at least 1 day",
                context={"allowance_period_days": self.allowance_period_days},
            )
        if self.allowance_credits < 0 or self.max_orders_in_flight < 1:
            raise ConfigError(
                "an allowance cannot be negative and at least one order must be permitted",
                context={
                    "allowance_credits": self.allowance_credits,
                    "max_orders_in_flight": self.max_orders_in_flight,
                },
            )
        if self.settlement_grace_s < 1:
            raise ConfigError(
                "settlement_grace_s must be positive",
                context={"settlement_grace_s": self.settlement_grace_s},
            )


DEFAULT_ENTITLEMENT_POLICY: Final[EntitlementPolicy] = EntitlementPolicy()


def resolve_entitlement_policy(settings: object | None = None) -> EntitlementPolicy:
    """Build the policy this deployment runs on, reading ``Settings`` defensively.

    ``object`` rather than ``Settings`` for the same reason
    :func:`hbd.db.retention.resolve_retention_policy` does it: this module is a leaf and
    importing ``hbd.config`` would give it an edge it has spent its whole docstring
    avoiding. ``getattr`` with a type check is the whole cost.

    The grace is the only field that moves, and it moves in one of two ways: an operator's
    ``HBD_SETTLEMENT_GRACE_S`` wins outright, and otherwise it is DERIVED from this
    deployment's queue ladder rather than left at the shipped default. That derivation is
    the point — an operator who raises ``HBD_QUEUE_JOB_TIMEOUT_S`` to an hour has quietly
    made every render able to outlive a fixed grace, and the sweep would then start
    refunding jobs that were still running. Deriving means they cannot get that wrong
    without also setting the override, which is a deliberate act.

    ``is_balance_enforced`` comes off ``Settings.credits_enforced`` and lands HERE rather
    than on the payment decorator, which is where it used to live. A gate that owned the
    flag could only express it as "call the store or do not", and not calling the store
    switched off the block gate and the in-flight cap along with the balance — see the
    field's own comment. Resolved in one place, it reaches the one predicate it is about.
    """
    if settings is None:
        return DEFAULT_ENTITLEMENT_POLICY
    is_enforced = _flag(settings, "credits_enforced")
    override = _positive_int(settings, "settlement_grace_s")
    if override is not None:
        return EntitlementPolicy(settlement_grace_s=override, is_balance_enforced=is_enforced)
    timeout = _positive_number(settings, "queue_job_timeout_s")
    backoff = _positive_number(settings, "provider_backoff_base_s")
    tries = _positive_int(settings, "queue_max_tries")
    if timeout is None or backoff is None or tries is None:
        return EntitlementPolicy(is_balance_enforced=is_enforced)
    return EntitlementPolicy(
        settlement_grace_s=derive_settlement_grace_s(
            job_timeout_s=timeout, max_tries=tries, backoff_base_s=backoff
        ),
        is_balance_enforced=is_enforced,
    )


def _flag(settings: object, name: str) -> bool:
    """``getattr`` narrowed to a real boolean.

    Absent or non-boolean reads as ENFORCED, deliberately. This resolver is defensive about
    a settings object it does not import, and the safe direction for a money control is the
    one that refuses rather than the one that lets everything through.
    """
    value = getattr(settings, name, None)
    return value if isinstance(value, bool) else True


def _positive_number(settings: object, name: str) -> float | None:
    """``getattr`` narrowed to a usable positive number, or ``None`` if it is not one."""
    value = getattr(settings, name, None)
    if isinstance(value, bool) or not isinstance(value, float | int) or value <= 0:
        return None
    return float(value)


def _positive_int(settings: object, name: str) -> int | None:
    """``getattr`` narrowed to a usable int. ``bool`` is excluded — it is an ``int`` here."""
    value = getattr(settings, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def period_index_for(now: datetime, *, period_days: int) -> int:
    """Which rolling window ``now`` falls in, counting whole windows from the epoch.

    This is the ``{index}`` in ``grant:period:{telegram_user_id}:{index}``, so it is the
    only thing that makes the mint idempotent: two processes that agree on the instant
    agree on the key, and the unique index on ``credit_ledger.idempotency_key`` turns the
    second write into a no-op. It is a pure function of an INJECTED clock for the same
    reason — ambient wall time would make "a user returning in a later period gets a fresh
    grant" untestable without sleeping for a month.

    A naive datetime is rejected rather than assumed to be UTC: guessing the zone would
    shift the window boundary by up to a day and silently mint an extra allowance.
    """
    if now.tzinfo is None:
        raise ValidationError(
            "period_index_for needs an aware datetime; a naive one has no window",
            context={"now": repr(now)},
        )
    return (now - _EPOCH).days // period_days


def period_start(index: int, *, period_days: int) -> datetime:
    """The instant window ``index`` opens — i.e. when the next allowance becomes mintable.

    Exists so a refusal can say *when*. ``InsufficientCreditsError`` carries
    ``period_start(period_index_for(now) + 1)`` as ``next_grant_at``, which is the one piece
    of context that turns "no" into something a customer can act on.
    """
    return _EPOCH + timedelta(days=index * period_days)


@runtime_checkable
class EntitlementStore(Protocol):
    """The seam between "may this account render?" and where that answer is written down.

    Every method returns a ``Result`` and none of them raises, matching every other
    protocol in this codebase: a gate must never have to wrap a call in ``try``. The
    persistence implementation is ``hbd.db.credits.SqlCreditLedger``.

    ``runtime_checkable`` here verifies member PRESENCE only — never signatures — so an
    ``isinstance`` assertion in a wiring test will happily accept a fake that has drifted.
    ``mypy --strict`` over ``tests`` is what actually catches that.
    """

    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = 1
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        """Take payment for ``order_id`` exactly once, opening the account if it is new.

        The ONLY writer of a debit. Idempotent per order by net position, so calling it
        again for an order that is currently paid for returns ``ALREADY_PAID`` and moves
        nothing, while calling it for an order that was refunded charges again at the next
        generation. Refuses with an :class:`EntitlementError` subclass — never with a
        successful "not authorised" — so the refusal carries a locale key and its numbers.
        """
        ...

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        """Close the debit for ``order_id``. ``True`` when this call wrote the settlement.

        ``False`` is a normal answer, not a failure: the order was never debited, or a
        redelivered job already settled it. A settlement must never mint a credit that was
        never spent, so an unspent order writes nothing at all.
        """
        ...

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        """Add credits an operator decided to give. Idempotent on ``idempotency_key``.

        The caller owns the key (``grant:admin:{uuid4}``) so that a CLI invocation retried
        after a timeout tops the account up once, not twice.
        """
        ...

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        """Read the account WITHOUT writing anything — the bot-side gate's only call.

        ``exclude_order_id`` leaves the order the caller is about to submit out of the
        in-flight count, so a retry of the same order is never refused by its own debit.
        """
        ...

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        """Bar or unbar an account. Upserts, because most people the bot has spoken to have
        no ``users`` row at all — ``repository._ensure_user`` only runs when an order is
        created, so a rowcount-checked ``UPDATE`` would silently fail to block exactly the
        accounts most worth blocking.
        """
        ...

    async def touch(self, telegram_user_id: int, *, ui_language: Language) -> Result[None]:
        """Record that this account is alive and which language it is reading.

        The first writer in the system that refreshes ``ui_language`` on an existing row,
        and the reason a person who never confirmed an order still has a row to block.
        """
        ...

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """Honour ``/forget`` here: drop the balance, keep the count, lose the identity.

        The ONE write the bot process is allowed to make through this seam, and it is not
        an exception to the read-only rule so much as the reason the rule has a shape:
        everything a GATE does is a read, because a gate that could write could double-
        charge. A data-subject request is not a gate. It cannot spend, refuse or refund
        anything — it removes rows — so nothing it does can be turned into a free song.

        Idempotent and total: an account that never ordered anything has nothing to erase,
        which is a successful erasure and not a failure. See
        :func:`hbd.db.credit_erasure.forget_account` for what is deleted, what is kept
        anonymous and why the two tables are treated in opposite ways.
        """
        ...
