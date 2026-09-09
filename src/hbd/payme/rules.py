"""The pure predicates the settlement transaction calls. No session, no clock, no I/O.

The correctness centre of this integration is a database transaction, and a transaction is
the one place a decision cannot be unit-tested cheaply. So every decision that does NOT need
a lock is lifted out of it and lands here, where "is this transaction past its window?" is
answerable with two datetimes and an integer, in a test with no fixtures and no engine.

What deliberately did NOT come out with them: the two conditional ``UPDATE``s whose rowcount
IS the lock. Those cannot be predicates, because their answer depends on what another
connection did between the read and the write — that is the whole reason they are written as
``UPDATE ... WHERE state = :expected`` rather than as a read followed by a decision followed
by a write. A "pure decisions" layer that tried to own them would be a layer that decides
things it cannot enforce, which is the shape of every double-charge in this problem domain.

Four functions, and each is a wire fact with a consequence:

* :func:`is_expired` measures from **Payme's own creation instant**, not ours.
* :func:`wire_state` is the single crossing point between the readable state and the integer.
* :func:`wire_time` is where "unset means 0, never null" is enforced.
* :func:`account_fault_for` maps a terminal intent state to the account code that reports it.

``now`` is a parameter everywhere. Nothing in this module reads a clock, which is what lets
the twelve-hour window be driven in seconds during certification and asserted at its exact
boundary in a test.

See ``PAYME_INTEGRATION §2`` for the two state machines and ``§5`` for the replay guarantees
these predicates serve.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Final

from hbd.checkout import PaymentIntentState
from hbd.payme.protocol import MISSING_TIME, PaymeErrorCode, PaymeState, WireState, to_ms

__all__ = [
    "DEFAULT_TRANSACTION_TIMEOUT_MS",
    "WIRE_STATE",
    "ACCOUNT_FAULT",
    "is_expired",
    "wire_state",
    "wire_time",
    "account_fault_for",
]

#: Twelve hours in milliseconds: the DEFAULT of ``HBD_PAYME_TRANSACTION_TIMEOUT_MS``, and
#: deliberately not a constant anyone may import as though it were the rule.
#:
#: The specification says a transaction must be completed within twelve hours «с момента
#: создания транзакции в Payme Business» — from the instant PAYME created it, which is
#: ``params.time``, not the instant we heard about it. Those differ by the network, by a retry
#: and, on a bad day, by however long our own process was unavailable, and measuring from our
#: own ``created_at`` would close the window early on exactly the transactions that had trouble
#: reaching us.
#:
#: It is a setting rather than a literal so that the expiry branch can be driven in SECONDS
#: during certification. A twelve-hour constant makes that branch untestable in any run a human
#: will watch, and an untested branch on the money path is how "cancel first, refuse second"
#: silently becomes "refuse only".
DEFAULT_TRANSACTION_TIMEOUT_MS: Final[int] = 43_200_000

#: The readable state to the integer Payme speaks. Total by construction and asserted total by
#: ``tests/test_payme/test_protocol.py`` — a member added to one enum and forgotten in the
#: other would otherwise surface as a ``KeyError`` inside a settlement, on the money path, at
#: the moment a customer's card had already been charged.
WIRE_STATE: Final[Mapping[PaymeState, WireState]] = MappingProxyType(
    {
        PaymeState.CREATED: WireState.CREATED,
        PaymeState.PERFORMED: WireState.PERFORMED,
        PaymeState.CANCELLED: WireState.CANCELLED,
        PaymeState.CANCELLED_AFTER_PERFORM: WireState.CANCELLED_AFTER_PERFORM,
    }
)

#: The three TERMINAL intent states and the account-range code each is reported as.
#:
#: ``PENDING`` and ``AWAITING`` are absent on purpose and their absence is the meaning: an
#: intent in either of them is not faulty, it is payable (``pending``) or already held by a
#: live transaction (``awaiting``, which is a state refusal through the settable duplicate
#: code, not an account fault). See :func:`account_fault_for` for why that is expressed as a
#: ``None`` return rather than as a precondition.
ACCOUNT_FAULT: Final[Mapping[PaymentIntentState, PaymeErrorCode]] = MappingProxyType(
    {
        PaymentIntentState.PAID: PaymeErrorCode.ACCOUNT_ALREADY_PAID,
        PaymentIntentState.CANCELLED: PaymeErrorCode.ACCOUNT_CANCELLED,
        PaymentIntentState.EXPIRED: PaymeErrorCode.ACCOUNT_EXPIRED,
    }
)


def is_expired(*, payme_time: datetime, now: datetime, timeout_ms: int) -> bool:
    """Has ``payme_time`` fallen more than ``timeout_ms`` behind ``now``?

    **Measured from Payme's own creation instant**, which is why the parameter is named
    ``payme_time`` and not ``created_at``: see :data:`DEFAULT_TRANSACTION_TIMEOUT_MS`.

    **The boundary is exclusive: at exactly ``timeout_ms`` the window is still OPEN.** The two
    readings differ by one millisecond and they differ in DIRECTION, which is the part that
    matters. An inclusive boundary refuses a payment we are entitled to take, at the instant
    Payme's own reference implementations — which compare with a strict ``>`` — would still
    perform it; an exclusive one accepts a payment one millisecond after we could have refused
    it, and then we keep the money and the customer gets their song. Only one of those is a
    dispute. The boundary has a test of its own for that reason.

    Both instants go through :func:`hbd.payme.protocol.to_ms` rather than being subtracted as
    datetimes, so the comparison happens in the same integer millisecond space the wire uses
    and a sub-millisecond difference cannot make this function and the ``perform_time`` we
    report disagree about which side of the window a transaction fell on.
    """
    return to_ms(now) - to_ms(payme_time) > timeout_ms


def wire_state(state: PaymeState) -> int:
    """Our readable state as the integer Payme expects. The single crossing point.

    Returns ``int`` rather than :class:`WireState` because it is on its way into a JSON body
    and an ``IntEnum`` serialises as its value anyway — narrowing the return type here would
    only tempt a caller into comparing the enum against a number it read back off the wire.
    """
    return int(WIRE_STATE[state])


def wire_time(moment: datetime | None) -> int:
    """A clock as the wire carries it: 13-digit milliseconds, or **integer 0 when unset**.

    ``0`` and never ``null``, and this function exists so that rule is enforced once rather
    than remembered six times. The official PHP template emits ``null`` for an unset
    ``perform_time``; that is the known deviation rather than the specification, payrest and
    PayTechUz both coerce to 0, and the sandbox's own assertions compare against 0. A ``null``
    where a client expects an integer is the kind of defect that passes every local test and
    fails one certification scenario in a way nobody can reproduce.

    ``None`` is the honest in-memory representation of "this has not happened" — a column that
    stored 0 could not tell a transaction performed at the epoch from one never performed — so
    the coercion belongs at the wire and nowhere earlier.
    """
    return MISSING_TIME if moment is None else to_ms(moment)


def account_fault_for(intent_state: PaymentIntentState) -> PaymeErrorCode | None:
    """The account-range code for a TERMINAL intent state, or ``None`` if it is not terminal.

    ``paid`` -> ``-31051``, ``cancelled`` -> ``-31052``, ``expired`` -> ``-31053``.

    **``None`` for ``pending`` and ``awaiting``, rather than a precondition the caller must
    remember.** A total function returning ``PaymeErrorCode`` would have to invent an answer
    for two states that have none — ``pending`` is the healthy case and ``awaiting`` is a state
    refusal emitted through the settable duplicate code, which is a different range entirely —
    and the only ways to do that are to raise (an exception on the money path for a defect a
    type checker could have caught) or to return ``-31050`` (which would tell Payme the order
    does not exist while it is being paid for). Returning an optional makes ``mypy --strict``
    force every caller to say what it does with the healthy case, which is exactly the branch
    ``quote()`` must not fall through.
    """
    return ACCOUNT_FAULT.get(intent_state)
