"""The reveal budget: a ceiling on personal data pulled, counted in **records**.

A sibling of :mod:`bayram.admin.security.ratelimit`, deliberately: same fixed-window key shape,
same injected clock, same injected store protocol, same "return a decision, never raise for
a policy answer" contract. What is different is the **unit**, and the unit is the whole
design (ADMIN_PANEL_PLAN §12.3).

**Records, not requests.** A name reveal unmasks one string; a conversation reveal unmasks
every stored body for one user — up to ninety days of transcript carrying the recipient's
name, the note, the full lyric and everything the customer typed. A request-counted budget
of thirty an hour is therefore thirty complete conversations an hour, ~700 a day, all inside
policy and all logged as thirty rows: bulk export of personal data through the reveal
endpoint, defeating the export prohibition the whole panel exists to keep. So one reveal
returning fifty bodies charges **fifty** units, and a budget that charges one unit per
request is the bug this module exists to avoid.

**Two budgets, separately exhaustible.** ``admin_reveal_records_per_hour`` (default 200)
counts every record any reveal returns. ``admin_reveal_conversations_per_day`` (default 20)
counts conversation reveals only, on its own key namespace and its own window, so spending
one can never spend the other and an operator who has exhausted their day's transcripts can
still reveal a name.

**Atomicity: charge first, compare after — in ONE round trip.** ``INCRBY`` returns the
post-charge total, so the check and the charge are the same operation and two concurrent
reveals cannot both read 199/200 and both pass. This is why
:meth:`~bayram.admin.security.ratelimit.WindowCounterStore.increment_by` exists at all:
charging N records as N calls to ``increment`` is N interleavable operations, not one atomic
charge, and it is exactly the race the record unit was introduced to survive.

**A refused reveal gives its charge back, and that is where this parts company with
``ratelimit.py``.** There, a refused login attempt keeps its charge, because the attempt
itself is the thing being bounded — argon2 already ran, or was about to. Here the budget
bounds *disclosure*, and a refused reveal disclosed nothing. Leaving a 50-record charge
standing on a refusal would let one over-large request at 199/200 spend the rest of the hour
on data nobody ever saw, and would make the counter — which §12.3 wants read as "exposure"
on ``/metrics/reveals`` — measure attempts instead. The release is best-effort: if it fails
it is logged at ERROR and the charge stands, which is the conservative direction. The cost
of releasing is a microseconds-wide window in which a concurrent smaller reveal sees the
in-flight charge and is refused although it would have fitted; a transient false refusal is
the acceptable direction for a control whose other failure mode is undetected bulk export.

**Fail closed.** A store that cannot answer denies, exactly as the credential limiter does,
but with its own outcome so an outage is never reported as an exhausted budget: the caller
maps :attr:`RevealBudgetOutcome.BACKEND_UNAVAILABLE` to 503, not to 429. An unbudgeted
reveal path is an unbounded one, and §12.3 makes the budget the only thing bounding a
compromised session's reveal volume — step-up grants are not single-use, so within the grace
one grant authorises repeated reveals of the same subject and this counter is what stops
them.

**Windows are fixed and epoch-aligned**, like ``ratelimit.py``'s: the index is baked into
the key, so a bucket can never outlive itself and no sweep is needed. The consequence is
worth stating plainly — the "hour" resets on the clock hour and the "day" is a UTC day, so
200 records at 10:59 and 200 more at 11:00 is inside policy. ``retry_after_s`` is
**seconds-to-reset**, not the whole window: a daily budget reporting 86400 when the reset is
a minute away is a number an operator cannot act on. (``ratelimit.py`` reports the whole
window; its windows are fifteen minutes, so the difference did not matter there.)

Nothing here raises for a policy answer and nothing here imports the HTTP layer: the
decision is a value, and ``bayram.admin.deps.enforce_reveal_budget`` maps it to the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from bayram.admin.security.ratelimit import WindowCounterStore
from bayram.admin.security.tokens import sha256_hex
from bayram.logging import get_logger

__all__ = [
    "DEFAULT_MAX_CONVERSATIONS_PER_DAY",
    "DEFAULT_MAX_RECORDS_PER_HOUR",
    "DEFAULT_REVEAL_BUDGET",
    "MAX_RECORDS_PER_REVEAL",
    "REVEAL_CONVERSATIONS_WINDOW_S",
    "REVEAL_RECORDS_WINDOW_S",
    "RevealBudgetDecision",
    "RevealBudgetLimits",
    "RevealBudgetOutcome",
    "RevealBudgetScope",
    "charge_reveal_budget",
    "reveal_budget_key",
]

_LOGGER: Final = get_logger(__name__)

#: One hour, one UTC day. Named rather than inlined because the key carries the window index
#: derived from them, so changing one silently re-buckets every live counter.
REVEAL_RECORDS_WINDOW_S: Final[int] = 3_600
REVEAL_CONVERSATIONS_WINDOW_S: Final[int] = 86_400

#: The two §12.3 defaults, mirrored from ``AdminSettings`` rather than imported from it:
#: :mod:`bayram.admin.settings` imports this package, so importing it back is a cycle. The
#: settings model is the authority at runtime — :class:`RevealBudgetLimits` is built from it
#: at the call site — and these exist so the limits are constructible in a unit test without
#: a settings object, the way ``ratelimit.py``'s defaults are.
DEFAULT_MAX_RECORDS_PER_HOUR: Final[int] = 200
DEFAULT_MAX_CONVERSATIONS_PER_DAY: Final[int] = 20

#: §12.3: "a conversation reveal returns **at most 50 bodies**; more requires a fresh reveal
#: with a ``nextCursor``, each one charged and each one audited". Enforced here as well as at
#: the schema, because a single charge larger than this is a page that was never paged — and
#: a budget can only be honest about exposure if the number it is handed is the number of
#: records the caller is actually authorised to return.
MAX_RECORDS_PER_REVEAL: Final[int] = 50

_KEY_PREFIX: Final[str] = "bayram:admin:budget"
#: Enough digest to make a collision irrelevant, short enough to keep keys readable — the
#: same length ``ratelimit.py`` uses, for the same reason.
_KEY_DIGEST_CHARS: Final[int] = 32


class RevealBudgetScope(StrEnum):
    """Which budget answered. Part of every key, which is what keeps the two separate."""

    RECORDS = "records"
    CONVERSATIONS = "conversations"


class RevealBudgetOutcome(StrEnum):
    """Why the budget answered as it did.

    ``BACKEND_UNAVAILABLE`` is distinct from ``EXHAUSTED`` for the reason
    :class:`~bayram.admin.security.ratelimit.RateLimitOutcome` splits them: one is an operator
    at their ceiling and the other is Redis being down, and an SPA that told an operator
    "your reveal budget is spent" for an hour of a store outage would have them opening an
    incident against the wrong system.
    """

    ALLOWED = "allowed"
    EXHAUSTED = "exhausted"
    BACKEND_UNAVAILABLE = "backend_unavailable"


@dataclass(frozen=True, slots=True)
class RevealBudgetLimits:
    """The two ceilings and their windows. Frozen; built from ``AdminSettings`` per request.

    Built at the call site rather than read from settings here, because this package is
    imported *by* :mod:`bayram.admin.settings` and must not import it back — and because a
    limiter that reaches for global configuration cannot be tested at a chosen ceiling.
    """

    max_records_per_hour: int = DEFAULT_MAX_RECORDS_PER_HOUR
    max_conversations_per_day: int = DEFAULT_MAX_CONVERSATIONS_PER_DAY
    records_window_s: int = REVEAL_RECORDS_WINDOW_S
    conversations_window_s: int = REVEAL_CONVERSATIONS_WINDOW_S

    def window_s(self, scope: RevealBudgetScope) -> int:
        """The window the named budget buckets on."""
        if scope is RevealBudgetScope.RECORDS:
            return self.records_window_s
        return self.conversations_window_s


DEFAULT_REVEAL_BUDGET: Final[RevealBudgetLimits] = RevealBudgetLimits()


@dataclass(frozen=True, slots=True)
class RevealBudgetDecision:
    """The budget's answer, and enough of the arithmetic to render a 429 and a meter.

    The two ``*_remaining`` fields are ``None`` when this call did not learn the number —
    the counter was not touched (a name reveal never reads the conversation budget), or the
    store could not answer. ``None`` is not zero: a meter that renders "0 left" for "not
    asked" is the kind of wrong that stops an operator from doing legitimate work.
    """

    is_allowed: bool
    outcome: RevealBudgetOutcome
    #: The budget that refused, or ``None`` on an allowed decision.
    scope: RevealBudgetScope | None
    #: Seconds until the refusing budget's window resets. ``0`` when allowed.
    retry_after_s: int
    records_requested: int
    #: Units left standing against the hourly budget once this call settled: the request's
    #: own ``record_count`` when allowed, ``0`` when refused (the charge was released).
    records_charged: int
    conversations_charged: int
    records_remaining: int | None
    conversations_remaining: int | None


@dataclass(frozen=True, slots=True)
class _Charge:
    """One charge that has landed, and what it takes to give it back."""

    key: str
    amount: int
    ttl_s: int


def _window_index(now: datetime, window_s: int) -> int:
    return int(now.timestamp()) // window_s


def _seconds_left(now: datetime, window_s: int) -> int:
    """Seconds until this window's bucket rolls over. Always ``1..window_s``."""
    return window_s - int(now.timestamp()) % window_s


def _actor_digest(username: str) -> str:
    """Hashed and case-folded into the key, exactly as ``ratelimit.py`` hashes usernames.

    Redis keys end up in ``KEYS`` dumps and support tickets, and an operator's username is
    personal-ish; case-folding first keeps ``Alice`` and ``alice`` in one bucket, or the
    ceiling is bypassed by varying the case of a name the lookup treats as one account.
    """
    return sha256_hex(username.casefold())[:_KEY_DIGEST_CHARS]


def reveal_budget_key(
    scope: RevealBudgetScope,
    *,
    username: str,
    now: datetime,
    limits: RevealBudgetLimits = DEFAULT_REVEAL_BUDGET,
) -> str:
    """The Redis key one actor's budget uses in the window containing ``now``.

    Public because ``/metrics/reveals`` and any future budget meter need to read the same
    counter the charge wrote, and a second spelling of a key is a second budget.
    """
    window = _window_index(now, limits.window_s(scope))
    return f"{_KEY_PREFIX}:{scope.value}:{window}:{_actor_digest(username)}"


async def _add(store: WindowCounterStore, key: str, amount: int, *, ttl_s: int) -> int | None:
    """Charge (or release) ``amount`` units atomically. ``None`` means the store failed."""
    try:
        return await store.increment_by(key, amount, ttl_s=ttl_s)
    except Exception:
        # Deliberately broad, for ``ratelimit._bump``'s reason: the store is a protocol and
        # raises whatever its client raises, and any failure of the budget is a failure to
        # budget.
        _LOGGER.exception(
            "reveal budget store is unavailable; failing closed",
            extra={"event": "admin.reveal.budget_store_unavailable"},
        )
        return None


async def _release(store: WindowCounterStore, charges: list[_Charge]) -> None:
    """Undo charges a refusal made. Best effort: a lost release is logged, never raised.

    Its own ``except`` rather than :func:`_add`'s, because the two failures mean opposite
    things: a charge that cannot be written must deny, and a release that cannot be written
    must not — the request is already being refused, and the only consequence is that this
    operator's counter stays high until the window rolls.
    """
    for charge in charges:
        try:
            await store.increment_by(charge.key, -charge.amount, ttl_s=charge.ttl_s)
        except Exception:
            # Broad for ``_add``'s reason: the store is a protocol and raises whatever its
            # client raises.
            _LOGGER.exception(
                "could not release a refused reveal charge; it stands until the window rolls",
                extra={
                    "event": "admin.reveal.budget_release_failed",
                    "reveal_budget_key": charge.key,
                    "units": charge.amount,
                },
            )


def _log_exhausted(
    scope: RevealBudgetScope, username: str, *, requested: int, ceiling: int, window_s: int
) -> None:
    """§12.3: "429 ``REVEAL_BUDGET_EXHAUSTED`` with a WARNING log naming the actor."

    Naming the actor is the point. "The limit is a detection control as much as a limit:
    bulk reveal is what a compromised session looks like" — a WARNING that said only that
    *some* budget tripped would detect nothing anybody could act on. A username is operator
    data, never customer data, so it is safe to log; the subject and the fields are not, and
    are not here.
    """
    _LOGGER.warning(
        "admin reveal budget exhausted",
        extra={
            "event": "admin.reveal.budget_exhausted",
            "admin_username": username,
            "reveal_budget_scope": scope.value,
            "units_requested": requested,
            "budget_ceiling": ceiling,
            "window_s": window_s,
        },
    )


def _validate(record_count: int, conversation_count: int) -> None:
    """Refuse a charge that is not a charge. Raises ``ValueError``; the caller maps it.

    ``record_count`` under one is the failure mode §12.3's correction was about arriving by
    the back door: a reveal charged zero units is a reveal the budget did not see, and the
    suite stays green while the control does nothing. A reveal that found nothing still cost
    a step-up and still has to be paid for, so the caller charges what it is *authorised* to
    return, before the read, and audits the same number.
    """
    if record_count < 1:
        raise ValueError("a reveal charges at least one record; a zero charge is not a reveal")
    if record_count > MAX_RECORDS_PER_REVEAL:
        raise ValueError(
            f"a single reveal may charge at most {MAX_RECORDS_PER_REVEAL} records; "
            f"more than that is a page that was never paged"
        )
    if conversation_count < 0:
        raise ValueError("a conversation charge cannot be negative")


def _unavailable(
    scope: RevealBudgetScope, *, record_count: int, now: datetime, limits: RevealBudgetLimits
) -> RevealBudgetDecision:
    return RevealBudgetDecision(
        is_allowed=False,
        outcome=RevealBudgetOutcome.BACKEND_UNAVAILABLE,
        scope=scope,
        retry_after_s=_seconds_left(now, limits.window_s(scope)),
        records_requested=record_count,
        records_charged=0,
        conversations_charged=0,
        records_remaining=None,
        conversations_remaining=None,
    )


async def charge_reveal_budget(
    store: WindowCounterStore,
    *,
    username: str,
    record_count: int,
    conversation_count: int = 0,
    now: datetime,
    limits: RevealBudgetLimits = DEFAULT_REVEAL_BUDGET,
) -> RevealBudgetDecision:
    """Charge one reveal against both budgets and say whether it may proceed.

    Call this **before** the read, with the number of records the reveal is authorised to
    return — its page size, never the number it turned out to find. Charging afterwards
    means an unbudgeted read already happened, and charging the found count lets an empty
    result be free.

    ``conversation_count`` is ``0`` for a name, note, lyric, media or moderation reveal and
    ``1`` for one page of a conversation, which is what makes the daily transcript ceiling
    exhaustible independently of the hourly record one. The conversation budget is charged
    **first**: it is the cheaper counter and the coarser refusal, and charging the records
    budget for a reveal the daily ceiling was going to refuse would spend an operator's hour
    on a request that returned nothing.

    Raises ``ValueError`` for a charge that is not a charge — under one record, over
    :data:`MAX_RECORDS_PER_REVEAL`, or a negative conversation count. The caller validates
    its body first so this is a 422 rather than a 500; the check is here as well because a
    silently-zero charge is the exact defect §12.3 corrected.
    """
    _validate(record_count, conversation_count)
    taken: list[_Charge] = []
    conversations_remaining: int | None = None

    if conversation_count > 0:
        scope = RevealBudgetScope.CONVERSATIONS
        window_s = limits.conversations_window_s
        key = reveal_budget_key(scope, username=username, now=now, limits=limits)
        total = await _add(store, key, conversation_count, ttl_s=window_s)
        if total is None:
            return _unavailable(scope, record_count=record_count, now=now, limits=limits)
        taken.append(_Charge(key, conversation_count, window_s))
        ceiling = limits.max_conversations_per_day
        if total > ceiling:
            await _release(store, taken)
            _log_exhausted(
                scope,
                username,
                requested=conversation_count,
                ceiling=ceiling,
                window_s=window_s,
            )
            return RevealBudgetDecision(
                is_allowed=False,
                outcome=RevealBudgetOutcome.EXHAUSTED,
                scope=scope,
                retry_after_s=_seconds_left(now, window_s),
                records_requested=record_count,
                records_charged=0,
                conversations_charged=0,
                records_remaining=None,
                conversations_remaining=max(0, ceiling - (total - conversation_count)),
            )
        conversations_remaining = ceiling - total

    scope = RevealBudgetScope.RECORDS
    window_s = limits.records_window_s
    key = reveal_budget_key(scope, username=username, now=now, limits=limits)
    total = await _add(store, key, record_count, ttl_s=window_s)
    if total is None:
        await _release(store, taken)
        return _unavailable(scope, record_count=record_count, now=now, limits=limits)
    taken.append(_Charge(key, record_count, window_s))
    ceiling = limits.max_records_per_hour
    if total > ceiling:
        # Both budgets are given back: the conversation page this request would have been
        # is not being served either.
        await _release(store, taken)
        _log_exhausted(scope, username, requested=record_count, ceiling=ceiling, window_s=window_s)
        return RevealBudgetDecision(
            is_allowed=False,
            outcome=RevealBudgetOutcome.EXHAUSTED,
            scope=scope,
            retry_after_s=_seconds_left(now, window_s),
            records_requested=record_count,
            records_charged=0,
            conversations_charged=0,
            records_remaining=max(0, ceiling - (total - record_count)),
            conversations_remaining=(
                None
                if conversations_remaining is None
                else conversations_remaining + conversation_count
            ),
        )

    return RevealBudgetDecision(
        is_allowed=True,
        outcome=RevealBudgetOutcome.ALLOWED,
        scope=None,
        retry_after_s=0,
        records_requested=record_count,
        records_charged=record_count,
        conversations_charged=conversation_count,
        records_remaining=ceiling - total,
        conversations_remaining=conversations_remaining,
    )
