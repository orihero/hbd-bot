"""``python -m bayram.payme.harness`` — Payme's sandbox scripts, replayed against a live gateway.

**What this is for.** Payme certifies a merchant by driving two published scripts against the
endpoint and reading the replies. A certification slot is a scheduled call with a human on the
other end, and the failure mode this module exists to prevent is discovering during that call
that our answer to step four was ``-31008`` where theirs expects ``-31050``. So the scripts are
encoded here as DATA, and the same table is driven twice: by
``tests/test_payme/test_sandbox_scenarios.py`` through the in-process ASGI app on every
``make test``, and by this script over a real socket against the real ``bayram-payme.service`` on
the VPS. One table, two transports, and the second one exists because the first cannot prove
what the first cannot reach.

**Why a script and not only a test.** The suite drives the app in-process with a recorder
standing in for the queue, an in-memory SQLite database and no worker anywhere. That is the
right shape for a test and it is deliberately blind to four things that have each broken a
deployment somewhere: the TLS terminator's rewriting of a body or a status, Postgres' answer
to the two conditional ``UPDATE``s where SQLite's file lock gave the same answer for a
different reason, an ARQ enqueue against a real Redis, and the worker actually sending a
Telegram message to a real person. Running this against a live gateway exercises all four —
the whole settlement path, up to and including a customer reading "your payment went
through" — before Payme has heard our name, because **the merchant key is only ever compared
against itself**, so an invented 36-character string is a functionally complete gateway.

**The one property Payme actually checks, and the reason this file has a repeat rule at all.**
Their sandbox states it plainly: «При повторных вызовах... ответ должен совпадать с ответом из
первого запроса». Every ``CreateTransaction``, ``PerformTransaction`` and ``CancelTransaction``
is therefore issued TWICE by :func:`run_step` and the second parsed reply is compared to the
first with ``==``. That rule is expressed once, as :data:`REPLAYED_METHODS`, rather than as a
flag on each row — a per-row flag is a rule a new row can forget, and the row most likely to
forget it is the one somebody adds in a hurry the week before certification. It is also why a
replay must return a STORED clock and never ``now()``: two replies that differ only in a
timestamp fail this comparison, and they fail it intermittently, which is the worst way to
learn about it.

**Rows this creates are real rows, and they carry ``is_sandbox=true``.** The intents are opened
through the same ``open_intent`` the bot's provider calls — not by hand-written SQL — so this
script cannot produce a row shape the product could not, and a change to the intent's schema
reaches it with no edit. The flag is what keeps a rehearsal out of every future revenue figure
by construction rather than by a ``WHERE`` clause somebody has to remember.

**What is deliberately NOT in the table.** Envelope-level faults — a missing ``method``, a
malformed body, a ``GET`` — are ``tests/test_payme/test_http.py``'s ground, asserted against
the real router where a 405 or a 422 can actually be produced. They cannot be expressed as a
``(method, params)`` row, and duplicating them here as raw bodies would put the transport rules
in two places with one of them able to drift. What IS here is the bad-auth probe, because that
one is a legitimate ``(method, params)`` row differing only in a header, and because it is the
first thing the sandbox does.

**This module imports ``bayram.payme.container``, which is the package's one sanctioned door into
``bayram.db``.** It needs a database because opening an intent is the BOT's port and there is no
bot in the room; it goes through the composition root rather than reaching for ``bayram.db``
itself so that this script wires exactly what the gateway wires, with the same pool sizing and
the same clock. See ``PAYME_INTEGRATION §7`` for the three inferred protocol facts each run of
this script is trying to close, and ``docs/deployment/08-payme.md`` for where it sits in the
certification runbook.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

import httpx

from bayram.checkout import PaymentIntentState, Product
from bayram.contracts import is_err
from bayram.errors import BayramError
from bayram.logging import configure_logging, get_logger
from bayram.payme.container import PaymeContainer, payme_container
from bayram.payme.protocol import CancelReason, PaymeErrorCode, PaymeMethod, to_ms
from bayram.payme.settings import PaymeSettings, build_payme_settings

__all__ = [
    "Auth",
    "Ref",
    "Expectation",
    "Step",
    "Scenario",
    "Credentials",
    "StepOutcome",
    "ScenarioOutcome",
    "OpenBindings",
    "REPLAYED_METHODS",
    "SCENARIOS",
    "ACCOUNT",
    "ACCOUNT_VALUE",
    "UNKNOWN_ACCOUNT",
    "MISCONFIGURED_ACCOUNT",
    "AMOUNT",
    "WRONG_AMOUNT",
    "TRANSACTION",
    "SECOND_TRANSACTION",
    "UNKNOWN_TRANSACTION",
    "NOW_MS",
    "WINDOW_FROM",
    "WINDOW_TO",
    "DUPLICATE_CODE",
    "MISSING_REFERENCE",
    "MISCONFIGURED_FIELD",
    "ACCOUNT_RANGE",
    "in_account_range",
    "WEAKENED_LOGIN",
    "PAYME_CONTENT_TYPE",
    "bind_params",
    "bindings_for",
    "check_reply",
    "run_step",
    "run_scenario",
    "run_transcript",
    "render_report",
    "plan",
    "apply",
    "check_intent",
    "Request",
    "RefusedError",
    "main",
    "EXIT_OK",
    "EXIT_FAILED",
    "EXIT_CONFIG",
]

_LOG: Final = get_logger(__name__)

EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2

#: Payme's own documented ``Content-Type``. It is sent here rather than ``application/json``
#: because it is what the rail sends, and because no framework body parser recognises it as
#: JSON — which is exactly why the gateway reads the raw body itself. A harness that sent the
#: convenient content type would rehearse a request Payme never makes.
PAYME_CONTENT_TYPE: Final[str] = "text/json; charset=UTF-8"

#: The login PayTechUz's widely-installed package accepts because it splits the decoded
#: credential on ``':'`` and compares only the trailing key. We compare the WHOLE
#: ``login:key`` pair, so this probe must be refused; it is in the transcript rather than only
#: in the unit suite because "we are not that package" is a claim worth making over a socket.
WEAKENED_LOGIN: Final[str] = "admin"

#: A 24-character reference that is not a ``public_ref`` anywhere. ``secrets.token_hex(12)``
#: would have to collide with a fixed string for this to become a false negative, which is a
#: one-in-16^24 event and not a thing to design around.
MISSING_REFERENCE: Final[str] = "00000000000000000000dead"

#: An account subfield name the cabinet is certainly not configured with. The step that uses it
#: rehearses the single most likely go-live defect: «Настройка Аккаунт» is filled in by a human
#: in a web form, and a mismatch with ``BAYRAM_PAYME_ACCOUNT_FIELD`` turns every
#: ``CheckPerformTransaction`` into a ``-31050`` that looks like our bug.
MISCONFIGURED_FIELD: Final[str] = "not_the_configured_field"

#: The codes whose envelope PAYME's own interface renders to a customer, and which therefore
#: MUST carry ``data`` (the account subfield name) and a three-key ``{ru, uz, en}`` message map.
#:
#: The rule is stated as a RANGE rather than as a flag on each row for the same reason the
#: dispatcher decides it that way: one code in this family — the duplicate-transaction code —
#: is an environment variable, so an expectation that named the envelope shape per row would be
#: wrong for exactly the row certification is most likely to change.
ACCOUNT_RANGE: Final[range] = range(-31099, -31049)


def in_account_range(code: int) -> bool:
    """Whether ``code`` is in ``-31050..-31099`` and so needs the localised envelope."""
    return code in ACCOUNT_RANGE


#: How wide a window ``GetStatement`` is asked for, either side of the run's instant.
_STATEMENT_WINDOW: Final[timedelta] = timedelta(hours=1)

#: How long an operator-supplied ``--run-id`` may be. It is a label inside an idempotency key,
#: not an identifier in its own right, and a long one makes the key harder to read in a dump.
_MAX_RUN_ID: Final[int] = 32

_NO_FIELDS: Final[Mapping[str, object]] = MappingProxyType({})


class Auth(StrEnum):
    """Which credential a step presents. Three of the four are refusals worth rehearsing."""

    VALID = "valid"
    WRONG_KEY = "wrong_key"
    WRONG_LOGIN = "wrong_login"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class Ref:
    """A late-bound value in the table: the script names it, the runner supplies it.

    A scenario cannot spell its own account reference — ``public_ref`` is minted by
    ``open_intent`` at run time and is different on every run, which is the point of it. Nor
    can it spell the duplicate-transaction code, which is an environment variable precisely
    because Payme's own materials contradict themselves about it. A ``Ref`` is how a row stays
    DATA instead of becoming a function: :func:`bind_params` walks the parameters and swaps
    each one for whatever :func:`bindings_for` produced, and a name with no binding raises
    ``KeyError`` at the moment the step runs rather than sending Payme the string ``"Ref(...)"``.
    """

    name: str


#: The account object, already wearing the CONFIGURED subfield name: ``{order_id: <ref>}``.
ACCOUNT: Final[Ref] = Ref("account")
#: Just the reference string, for the step that deliberately files it under the wrong subfield.
ACCOUNT_VALUE: Final[Ref] = Ref("account_value")
#: An account object naming a reference that exists nowhere. Expect ``-31050``.
UNKNOWN_ACCOUNT: Final[Ref] = Ref("unknown_account")
#: A real reference under a subfield name we are not configured for. Also ``-31050``.
MISCONFIGURED_ACCOUNT: Final[Ref] = Ref("misconfigured_account")
#: The intent's amount, in TIYIN. Nothing on this path multiplies by 100.
AMOUNT: Final[Ref] = Ref("amount")
#: One tiyin more than the intent was opened for. Expect ``-31001`` and never a re-price.
WRONG_AMOUNT: Final[Ref] = Ref("wrong_amount")
#: The rail-side transaction id for a scenario's main transaction.
TRANSACTION: Final[Ref] = Ref("transaction")
#: A second rail-side id, for the "this order already has an active transaction" probe.
SECOND_TRANSACTION: Final[Ref] = Ref("second_transaction")
#: A rail-side id we never created. Expect ``-31003`` from every method that takes one.
UNKNOWN_TRANSACTION: Final[Ref] = Ref("unknown_transaction")
#: The run's instant as 13-digit milliseconds, for ``CreateTransaction.params.time``.
NOW_MS: Final[Ref] = Ref("now_ms")
#: The ``GetStatement`` window, an hour either side of the run.
WINDOW_FROM: Final[Ref] = Ref("window_from")
WINDOW_TO: Final[Ref] = Ref("window_to")
#: ``BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE`` as the gateway under test is actually configured.
#: Late-bound on purpose: certification may flip this value, and an expectation hard-coding
#: ``-31008`` would then fail against a gateway that is behaving exactly as configured.
DUPLICATE_CODE: Final[Ref] = Ref("duplicate_code")


@dataclass(frozen=True, slots=True)
class Expectation:
    """What a correct reply looks like, in the smallest vocabulary that says it.

    Every field is a separate CLAIM rather than one big expected body, because the parts of a
    reply we can predict and the parts we cannot are genuinely different: ``state`` is decided
    by the protocol, ``create_time`` is decided by the clock, and ``transaction`` is a UUID
    minted a millisecond ago. Asserting a whole body would mean either inventing values the
    runner has to feed back in — a test comparing the code with itself — or asserting nothing.

    :attr:`zero` earns its place alone. Payme's own PHP template renders an unset
    ``perform_time`` as ``null``; ``payrest`` and PayTechUz both coerce it to integer ``0``,
    and the specification says the field is an integer. A reply carrying ``null`` parses, looks
    right in a terminal, and is a deviation from the documented type that only shows up as a
    rejected certification — so "this key is present, is an ``int``, and is exactly 0" is a
    claim the transcript makes explicitly rather than leaving to a reader's eye.
    """

    #: The JSON-RPC error code, or ``None`` when a ``result`` is expected. May be a :class:`Ref`
    #: because one code in this protocol is an environment variable.
    error_code: int | Ref | None = None
    #: ``result["state"]``, in Payme's own numbering: 1, 2, -1, -2.
    state: int | None = None
    #: Keys of ``result`` compared for exact equality against these values.
    result: Mapping[str, object] = _NO_FIELDS
    #: Integer keys of ``result`` that must be present and strictly positive.
    positive: tuple[str, ...] = ()
    #: Integer keys of ``result`` that must be present and exactly ``0`` — never ``null``.
    zero: tuple[str, ...] = ()
    #: Keys of ``result`` that must be present, a string, and non-empty.
    nonempty: tuple[str, ...] = ()
    #: Keys of ``result`` that must be present and ``None``. ``reason`` on a transaction that
    #: was never cancelled is the only one, and it is ``null`` rather than ``0`` on purpose:
    #: zero is a cancel reason Payme could send, so it cannot also mean "never cancelled".
    null: tuple[str, ...] = ()
    #: ``GetStatement`` only: the fewest rows the window must contain.
    min_transactions: int | None = None
    #: ``error.data`` must equal this literal. Used by the unknown-method probe, where ``data``
    #: carries the method name back so an operator can see what was asked for.
    error_data: str | None = None
    #: Whether the reply must echo the request's ``id``. False for the authorization probes
    #: alone, and the exception is the correct behaviour rather than a shortcoming: the
    #: gateway refuses a bad credential BEFORE it reads the body, so at the moment it answers
    #: there is no ``id`` to echo — and making an unauthenticated caller's body worth parsing
    #: is work they should not be able to ask us for. Every reply still carries the member,
    #: as ``null``, which is what the JSON-RPC envelope requires.
    echoes_id: bool = True


@dataclass(frozen=True, slots=True)
class Step:
    """One inbound call and the reply it must produce.

    ``method`` is a plain ``str`` and not :class:`bayram.payme.protocol.PaymeMethod`, for one row's
    sake: the unknown-method probe sends a name that is deliberately not a member, and typing
    the field as the enum would make that row unexpressible in the very table whose job is to
    rehearse it.
    """

    label: str
    method: str
    params: Mapping[str, object]
    expect: Expectation
    auth: Auth = Auth.VALID


#: The three methods Payme resends on a lost response, and the ones whose second answer their
#: sandbox compares with the first. Stated once, as a rule over the table rather than as a flag
#: per row: a flag can be forgotten by whoever adds the next ``CreateTransaction``, and the
#: property it guards — a replay returns the STORED clock, never a fresh one — is the property
#: this whole integration's idempotency argument rests on.
REPLAYED_METHODS: Final[frozenset[str]] = frozenset(
    {
        PaymeMethod.CREATE_TRANSACTION.value,
        PaymeMethod.PERFORM_TRANSACTION.value,
        PaymeMethod.CANCEL_TRANSACTION.value,
    }
)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One of Payme's published scripts, plus what it must leave behind.

    ``credits_granted`` and ``receipts_written`` are why this type exists at all rather than a
    bare tuple of steps. A reply saying ``state: 2`` is not evidence that a credit was granted
    and a reply saying ``-31007`` is not evidence that nothing was reversed; the wire and the
    money are two claims and a certification rehearsal that checked only the first would pass
    happily against a gateway that answered beautifully and wrote nothing.

    ``expected_intent_state`` is the third claim, and it is the one the harness can check over
    a socket without counting rows: after the cancellation in scenario one the intent must be
    back at ``PENDING``, because a declined card has to let the customer try another one within
    seconds rather than sentencing them to wait out a validity window they did not cause.
    """

    name: str
    narrative: str
    steps: tuple[Step, ...]
    credits_granted: int
    receipts_written: int
    expected_intent_state: PaymentIntentState


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------
_AUTHORIZATION = Scenario(
    name="authorization",
    narrative=(
        "The sandbox's first probe. A wrong key is refused, and so is the right key under the "
        "wrong login — the second is the specific weakening a popular third-party package "
        "ships, and refusing it is a claim worth making over a socket rather than only in a "
        "unit test."
    ),
    steps=(
        Step(
            label="a wrong key is -32504 at HTTP 200",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.UNAUTHORISED, echoes_id=False),
            auth=Auth.WRONG_KEY,
        ),
        Step(
            label="the right key under the login 'admin' is -32504 too",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.UNAUTHORISED, echoes_id=False),
            auth=Auth.WRONG_LOGIN,
        ),
        Step(
            label="no Authorization header at all is -32504",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.UNAUTHORISED, echoes_id=False),
            auth=Auth.MISSING,
        ),
    ),
    credits_granted=0,
    receipts_written=0,
    expected_intent_state=PaymentIntentState.PENDING,
)

_UNCONFIRMED_THEN_CANCELLED = Scenario(
    name="scenario-one",
    narrative=(
        "Payme's first published script: create a transaction, leave it unconfirmed, cancel "
        "it. Nothing may be written that costs money, and the intent must come back to "
        "PENDING so the customer can pay with another card immediately."
    ),
    steps=(
        Step(
            label="CheckPerformTransaction allows a fresh order",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(result={"allow": True}),
        ),
        Step(
            label="CreateTransaction returns state 1 and a create_time",
            method=PaymeMethod.CREATE_TRANSACTION.value,
            params={"id": TRANSACTION, "time": NOW_MS, "amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(state=1, positive=("create_time",), nonempty=("transaction",)),
        ),
        Step(
            label="CheckTransaction reports state 1 with both unset clocks at integer 0",
            method=PaymeMethod.CHECK_TRANSACTION.value,
            params={"id": TRANSACTION},
            expect=Expectation(
                state=1,
                positive=("create_time",),
                zero=("perform_time", "cancel_time"),
                nonempty=("transaction",),
                null=("reason",),
            ),
        ),
        Step(
            label="CancelTransaction moves it to -1 and stamps a cancel_time",
            method=PaymeMethod.CANCEL_TRANSACTION.value,
            params={"id": TRANSACTION, "reason": int(CancelReason.RECEIVER_MISSING)},
            expect=Expectation(state=-1, positive=("cancel_time",), nonempty=("transaction",)),
        ),
        Step(
            label="CheckTransaction now reports -1, the cancel reason, and no perform_time",
            method=PaymeMethod.CHECK_TRANSACTION.value,
            params={"id": TRANSACTION},
            expect=Expectation(
                state=-1,
                positive=("create_time", "cancel_time"),
                zero=("perform_time",),
                result={"reason": int(CancelReason.RECEIVER_MISSING)},
            ),
        ),
        Step(
            label="the released intent may be paid again — a declined card is not a dead order",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(result={"allow": True}),
        ),
    ),
    credits_granted=0,
    receipts_written=0,
    expected_intent_state=PaymentIntentState.PENDING,
)

_CREATE_PERFORM_CANCEL = Scenario(
    name="scenario-two",
    narrative=(
        "Payme's second published script: create, perform, then cancel. The cancellation is "
        "the ONE step where our answer is deliberately not the sandbox's: a performed "
        "transaction is -31007 unconditionally, which is PaycomUZ's own template's default "
        "(Order::allowCancel() returns false) and is argued in PAYME_INTEGRATION §6. The "
        "steps after it exist to prove the refusal reversed nothing."
    ),
    steps=(
        Step(
            label="CheckPerformTransaction allows the order",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(result={"allow": True}),
        ),
        Step(
            label="CreateTransaction returns state 1",
            method=PaymeMethod.CREATE_TRANSACTION.value,
            params={"id": TRANSACTION, "time": NOW_MS, "amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(state=1, positive=("create_time",), nonempty=("transaction",)),
        ),
        Step(
            label="PerformTransaction returns state 2 and a perform_time",
            method=PaymeMethod.PERFORM_TRANSACTION.value,
            params={"id": TRANSACTION},
            expect=Expectation(state=2, positive=("perform_time",), nonempty=("transaction",)),
        ),
        Step(
            label="CheckTransaction reports state 2 with cancel_time still integer 0",
            method=PaymeMethod.CHECK_TRANSACTION.value,
            params={"id": TRANSACTION},
            expect=Expectation(
                state=2,
                positive=("create_time", "perform_time"),
                zero=("cancel_time",),
                null=("reason",),
            ),
        ),
        Step(
            label="CancelTransaction on a delivered order is -31007 and reverses nothing",
            method=PaymeMethod.CANCEL_TRANSACTION.value,
            params={"id": TRANSACTION, "reason": int(CancelReason.REFUND)},
            expect=Expectation(error_code=PaymeErrorCode.ORDER_DELIVERED),
        ),
        Step(
            label="the transaction is still state 2 after the refused cancellation",
            method=PaymeMethod.CHECK_TRANSACTION.value,
            params={"id": TRANSACTION},
            expect=Expectation(state=2, positive=("perform_time",), zero=("cancel_time",)),
        ),
        Step(
            label="GetStatement lists it, with THEIR id under 'id' and OURS under 'transaction'",
            method=PaymeMethod.GET_STATEMENT.value,
            params={"from": WINDOW_FROM, "to": WINDOW_TO},
            expect=Expectation(min_transactions=1),
        ),
    ),
    credits_granted=1,
    receipts_written=1,
    expected_intent_state=PaymentIntentState.PAID,
)

_REFUSALS = Scenario(
    name="refusals",
    narrative=(
        "The refusals the sandbox probes around the two scripts, and the three go-live defects "
        "worth rehearsing: a wrong amount, a cabinet configured with a different account "
        "subfield name, and a second transaction against an order that already has a live one. "
        "The last step cancels the transaction this scenario opened, so a rehearsal leaves "
        "nothing live behind it."
    ),
    steps=(
        Step(
            label="a wrong amount is -31001, a plain message and no data",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": WRONG_AMOUNT, "account": ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.WRONG_AMOUNT),
        ),
        Step(
            label="an unknown order reference is -31050 with the subfield name in data",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": UNKNOWN_ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.ACCOUNT_UNKNOWN),
        ),
        Step(
            label="a real reference under the wrong subfield name is -31050 too",
            method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
            params={"amount": AMOUNT, "account": MISCONFIGURED_ACCOUNT},
            expect=Expectation(error_code=PaymeErrorCode.ACCOUNT_UNKNOWN),
        ),
        Step(
            label="performing a transaction we never created is -31003, never a creation",
            method=PaymeMethod.PERFORM_TRANSACTION.value,
            params={"id": UNKNOWN_TRANSACTION},
            expect=Expectation(error_code=PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ),
        Step(
            label="checking a transaction we never created is -31003",
            method=PaymeMethod.CHECK_TRANSACTION.value,
            params={"id": UNKNOWN_TRANSACTION},
            expect=Expectation(error_code=PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ),
        Step(
            label="cancelling a transaction we never created is -31003",
            method=PaymeMethod.CANCEL_TRANSACTION.value,
            params={"id": UNKNOWN_TRANSACTION, "reason": int(CancelReason.RECEIVER_MISSING)},
            expect=Expectation(error_code=PaymeErrorCode.TRANSACTION_NOT_FOUND),
        ),
        Step(
            label="CreateTransaction takes the mutex on the order",
            method=PaymeMethod.CREATE_TRANSACTION.value,
            params={"id": TRANSACTION, "time": NOW_MS, "amount": AMOUNT, "account": ACCOUNT},
            expect=Expectation(state=1, positive=("create_time",), nonempty=("transaction",)),
        ),
        Step(
            label="a SECOND transaction for the held order is refused before a card is charged",
            method=PaymeMethod.CREATE_TRANSACTION.value,
            params={
                "id": SECOND_TRANSACTION,
                "time": NOW_MS,
                "amount": AMOUNT,
                "account": ACCOUNT,
            },
            expect=Expectation(error_code=DUPLICATE_CODE),
        ),
        Step(
            label="an unknown method is -32601 with the name echoed in data",
            method="ThereIsNoSuchMethod",
            params={},
            expect=Expectation(
                error_code=PaymeErrorCode.METHOD_NOT_FOUND, error_data="ThereIsNoSuchMethod"
            ),
        ),
        Step(
            label="ChangePassword is dispatched and refused, not a -32601 surprise",
            method=PaymeMethod.CHANGE_PASSWORD.value,
            params={"password": "rotation-is-a-redeploy"},
            expect=Expectation(error_code=PaymeErrorCode.INTERNAL),
        ),
        Step(
            label="the scenario tidies up after itself and releases the order",
            method=PaymeMethod.CANCEL_TRANSACTION.value,
            params={"id": TRANSACTION, "reason": int(CancelReason.RECEIVER_MISSING)},
            expect=Expectation(state=-1, positive=("cancel_time",)),
        ),
    ),
    credits_granted=0,
    receipts_written=0,
    expected_intent_state=PaymentIntentState.PENDING,
)

#: The whole transcript, in the order a certification call walks it. The authorization probe is
#: first because that is where the sandbox starts and because a wrong login is the one inferred
#: fact a single real call can close: the ``-32504`` log line prints the RECEIVED login.
SCENARIOS: Final[tuple[Scenario, ...]] = (
    _AUTHORIZATION,
    _UNCONFIRMED_THEN_CANCELLED,
    _CREATE_PERFORM_CANCEL,
    _REFUSALS,
)


# ---------------------------------------------------------------------------
# Binding the table to one run
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Credentials:
    """The Basic-auth pair, and the three ways of getting it wrong on purpose."""

    login: str
    key: str

    def header(self, auth: Auth) -> str | None:
        """The ``Authorization`` value for one step, or ``None`` when the step sends none.

        The wrong key is the right key with its LAST CHARACTER changed, not a shorter or
        obviously different string. Length-preserving is the stricter probe: it fails an
        implementation that compares lengths, or that compares a prefix, and it is the shape a
        mistyped key in ``/etc/bayram/payme.env`` actually has.
        """
        if auth is Auth.MISSING:
            return None
        login = WEAKENED_LOGIN if auth is Auth.WRONG_LOGIN else self.login
        key = self.key
        if auth is Auth.WRONG_KEY:
            key = key[:-1] + ("0" if key[-1:] != "0" else "1")
        return "Basic " + base64.b64encode(f"{login}:{key}".encode()).decode("ascii")


def bindings_for(
    *,
    account_field: str,
    public_ref: str,
    amount_minor: int,
    duplicate_code: int,
    now: datetime,
) -> dict[str, object]:
    """Everything a :class:`Ref` in the table can name, for one scenario's run.

    Called once per scenario, not once per transcript: each scenario gets its own intent and
    its own rail-side ids, so a scenario that leaves a transaction in state 1 cannot make the
    next one's ``CreateTransaction`` collide with it. The two transaction ids are minted with
    ``secrets.token_hex(12)``, which is 24 lowercase hex characters — the exact shape of the
    Mongo ObjectId the rail actually sends, so a column typed too narrowly or an implementation
    tempted to parse the id as a number fails here rather than in the cabinet.
    """
    moment = to_ms(now)
    return {
        ACCOUNT.name: {account_field: public_ref},
        ACCOUNT_VALUE.name: public_ref,
        UNKNOWN_ACCOUNT.name: {account_field: MISSING_REFERENCE},
        MISCONFIGURED_ACCOUNT.name: {MISCONFIGURED_FIELD: public_ref},
        AMOUNT.name: amount_minor,
        WRONG_AMOUNT.name: amount_minor + 1,
        TRANSACTION.name: secrets.token_hex(12),
        SECOND_TRANSACTION.name: secrets.token_hex(12),
        UNKNOWN_TRANSACTION.name: secrets.token_hex(12),
        NOW_MS.name: moment,
        WINDOW_FROM.name: to_ms(now - _STATEMENT_WINDOW),
        WINDOW_TO.name: to_ms(now + _STATEMENT_WINDOW),
        DUPLICATE_CODE.name: duplicate_code,
    }


def _bind(value: object, bindings: Mapping[str, object]) -> object:
    """One value with its refs resolved, recursively. A missing name is a ``KeyError``."""
    if isinstance(value, Ref):
        return bindings[value.name]
    if isinstance(value, Mapping):
        return {key: _bind(item, bindings) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_bind(item, bindings) for item in value]
    return value


def bind_params(params: Mapping[str, object], bindings: Mapping[str, object]) -> dict[str, Any]:
    """A step's parameters, ready to send."""
    return {key: _bind(value, bindings) for key, value in params.items()}


def _bind_code(code: int | Ref | None, bindings: Mapping[str, object]) -> int | None:
    if isinstance(code, Ref):
        resolved = bindings[code.name]
        return int(resolved) if isinstance(resolved, int) else None
    return code


# ---------------------------------------------------------------------------
# Checking one reply
# ---------------------------------------------------------------------------
def check_reply(
    step: Step,
    body: Mapping[str, Any],
    *,
    status_code: int,
    request_id: int,
    account_field: str,
    bindings: Mapping[str, object],
) -> tuple[str, ...]:
    """Every way this reply fails the step, as sentences. Empty means it passed.

    A list of failures rather than a first failure, and sentences rather than a boolean,
    because the consumer on certification day is a person reading a terminal at the same time
    as somebody from Payme is reading their own screen. "state was 1, expected 2" ends that
    conversation; ``AssertionError`` does not.
    """
    failures: list[str] = []
    if status_code != 200:
        # The rule with no exceptions. Payme reads any other status as transport error -32400
        # and retries it, and a 500 costs the id echo as well.
        failures.append(f"HTTP {status_code}; every reply must be 200, without exception")
    if body.get("jsonrpc") != "2.0":
        failures.append(f"jsonrpc was {body.get('jsonrpc')!r}, expected '2.0'")
    if "id" not in body:
        failures.append("no id member; the envelope carries one on every reply, even as null")
    elif step.expect.echoes_id and body["id"] != request_id:
        failures.append(f"id was {body['id']!r}, expected {request_id!r}")
    elif not step.expect.echoes_id and body["id"] is not None:
        failures.append(f"id was {body['id']!r}; a reply refused before the body is read has none")
    if ("result" in body) == ("error" in body):
        failures.append("a reply carries exactly one of result and error")
        return tuple(failures)

    expected_code = _bind_code(step.expect.error_code, bindings)
    if expected_code is not None:
        failures.extend(_check_error(body, expected_code, step.expect, account_field=account_field))
    else:
        failures.extend(_check_result(body, step.expect))
    return tuple(failures)


def _check_error(
    body: Mapping[str, Any],
    expected_code: int,
    expect: Expectation,
    *,
    account_field: str,
) -> list[str]:
    """The error half, including the envelope shape the ``-31050..-31099`` range demands."""
    failures: list[str] = []
    error = body.get("error")
    if not isinstance(error, Mapping):
        return [f"expected error {expected_code}, got result {body.get('result')!r}"]
    if error.get("code") != expected_code:
        failures.append(f"error code was {error.get('code')!r}, expected {expected_code}")
    if in_account_range(expected_code):
        if error.get("data") != account_field:
            failures.append(
                f"error.data was {error.get('data')!r}, expected the account subfield "
                f"{account_field!r} — this is the string a human typed into «Настройка Аккаунт»"
            )
        message = error.get("message")
        if not isinstance(message, Mapping) or set(message) != {"ru", "uz", "en"}:
            failures.append("an account-range error needs a {ru, uz, en} message map")
        elif not all(isinstance(text, str) and text for text in message.values()):
            failures.append("every one of the three localised messages must be non-empty")
    elif expect.error_data is not None:
        if error.get("data") != expect.error_data:
            failures.append(f"error.data was {error.get('data')!r}, expected {expect.error_data!r}")
    else:
        if "data" in error:
            failures.append("this code carries no data; only -31050..-31099 does")
        if not isinstance(error.get("message"), str):
            failures.append("outside the account range the message is a plain string")
    return failures


def _check_result(body: Mapping[str, Any], expect: Expectation) -> list[str]:
    """The result half: the state, the clocks, and the two ids."""
    failures: list[str] = []
    result = body.get("result")
    if not isinstance(result, Mapping):
        error = body.get("error")
        return [f"expected a result, got error {error!r}"]
    if expect.state is not None and result.get("state") != expect.state:
        failures.append(f"state was {result.get('state')!r}, expected {expect.state}")
    for key, value in expect.result.items():
        if result.get(key) != value:
            failures.append(f"{key} was {result.get(key)!r}, expected {value!r}")
    for key in expect.positive:
        value = result.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            failures.append(f"{key} was {value!r}, expected a positive 13-digit millisecond int")
    for key in expect.zero:
        value = result.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            failures.append(f"{key} was {value!r}; an unset time is integer 0 and never null")
    for key in expect.nonempty:
        value = result.get(key)
        if not isinstance(value, str) or not value:
            failures.append(f"{key} was {value!r}, expected a non-empty string")
    for key in expect.null:
        if key not in result:
            failures.append(f"{key} is missing; it must be present and null")
        elif result[key] is not None:
            failures.append(f"{key} was {result[key]!r}, expected null")
    if expect.min_transactions is not None:
        rows = result.get("transactions")
        if not isinstance(rows, list):
            failures.append("GetStatement returns the plural key 'transactions' as a list")
        elif len(rows) < expect.min_transactions:
            failures.append(
                f"the window held {len(rows)} transactions, expected at least "
                f"{expect.min_transactions}"
            )
    return failures


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What one step did: the first reply, the replayed one, and every failure found."""

    step: Step
    first: Mapping[str, Any]
    #: The second reply, for the three methods Payme resends. ``None`` for every other method.
    second: Mapping[str, Any] | None
    failures: tuple[str, ...]

    @property
    def replayed(self) -> bool:
        return self.second is not None

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """One scenario's steps, plus whatever the ledger said afterwards."""

    scenario: Scenario
    steps: tuple[StepOutcome, ...]
    #: Failures found by reading the database rather than the wire — the money outcomes. Filled
    #: in by whoever has a ledger handle; empty when nobody checked, which is itself visible in
    #: the report because the row prints "wire only".
    ledger_failures: tuple[str, ...] = ()
    ledger_checked: bool = False

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps) and not self.ledger_failures


async def run_step(
    client: httpx.AsyncClient,
    *,
    url: str,
    step: Step,
    bindings: Mapping[str, object],
    credentials: Credentials,
    account_field: str,
    request_id: int = 1,
) -> StepOutcome:
    """Issue one step — twice, if the rail would resend it — and check both replies.

    The replay sends the IDENTICAL body under the IDENTICAL id, because that is what a lost
    response looks like from the rail's side: it is not a new request, it is the same one
    again. Comparing the parsed bodies with ``==`` rather than the raw bytes is deliberate —
    key order in a JSON object carries no meaning and pinning it would fail on a library
    upgrade that has nothing to do with us.
    """
    params = bind_params(step.params, bindings)
    payload = {"method": step.method, "params": params, "id": request_id}
    first_status, first = await _post(client, url, payload, credentials, step.auth)
    failures = list(
        check_reply(
            step,
            first,
            status_code=first_status,
            request_id=request_id,
            account_field=account_field,
            bindings=bindings,
        )
    )
    second: Mapping[str, Any] | None = None
    if step.method in REPLAYED_METHODS:
        second_status, second = await _post(client, url, payload, credentials, step.auth)
        failures.extend(
            check_reply(
                step,
                second,
                status_code=second_status,
                request_id=request_id,
                account_field=account_field,
                bindings=bindings,
            )
        )
        if second != first:
            failures.append(
                "the replayed reply differs from the first — Payme's sandbox compares them, "
                f"and a stored clock is what makes them equal: {first!r} then {second!r}"
            )
    return StepOutcome(step=step, first=first, second=second, failures=tuple(failures))


async def _post(
    client: httpx.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    credentials: Credentials,
    auth: Auth,
) -> tuple[int, dict[str, Any]]:
    """One POST. A body that is not JSON is reported as a failure, never raised."""
    headers = {"Content-Type": PAYME_CONTENT_TYPE}
    header = credentials.header(auth)
    if header is not None:
        headers["Authorization"] = header
    response = await client.post(url, json=payload, headers=headers)
    try:
        parsed = response.json()
    except ValueError:
        return response.status_code, {"__unparseable__": response.text[:200]}
    if not isinstance(parsed, dict):
        return response.status_code, {"__not_an_object__": repr(parsed)[:200]}
    return response.status_code, parsed


async def run_scenario(
    client: httpx.AsyncClient,
    *,
    url: str,
    scenario: Scenario,
    bindings: Mapping[str, object],
    credentials: Credentials,
    account_field: str,
) -> ScenarioOutcome:
    """Every step of one scenario, in order. Steps are never skipped after a failure.

    A failing step does not abort the scenario, because the reason a certification run is worth
    doing is to collect ALL the disagreements in one pass. Stopping at the first would turn one
    afternoon into as many afternoons as there are defects.
    """
    outcomes = [
        await run_step(
            client,
            url=url,
            step=step,
            bindings=bindings,
            credentials=credentials,
            account_field=account_field,
            request_id=index + 1,
        )
        for index, step in enumerate(scenario.steps)
    ]
    return ScenarioOutcome(scenario=scenario, steps=tuple(outcomes))


async def run_transcript(
    client: httpx.AsyncClient,
    *,
    url: str,
    scenarios: Sequence[Scenario],
    open_bindings: OpenBindings,
    credentials: Credentials,
    account_field: str,
) -> list[ScenarioOutcome]:
    """The whole table, each scenario against its own freshly opened intent."""
    outcomes: list[ScenarioOutcome] = []
    for scenario in scenarios:
        bindings = await open_bindings(scenario)
        outcomes.append(
            await run_scenario(
                client,
                url=url,
                scenario=scenario,
                bindings=bindings,
                credentials=credentials,
                account_field=account_field,
            )
        )
    return outcomes


class OpenBindings:
    """Opens one intent per scenario and returns its bindings. Held as a class, not a closure.

    A named type rather than a ``Callable`` alias because both callers — the suite and this
    script — need to keep the ``public_ref`` they minted in order to check the intent
    afterwards, and a closure that quietly accumulated state in a list is harder to read than
    an object that says it does.
    """

    __slots__ = ("_amount_minor", "_container", "_run_id", "_telegram_user_id", "refs")

    def __init__(
        self,
        container: PaymeContainer,
        *,
        amount_minor: int,
        telegram_user_id: int,
        run_id: str,
    ) -> None:
        self._container = container
        self._amount_minor = amount_minor
        self._telegram_user_id = telegram_user_id
        self._run_id = run_id
        #: scenario name -> the ``public_ref`` opened for it.
        self.refs: dict[str, str] = {}

    async def __call__(self, scenario: Scenario) -> Mapping[str, object]:
        settings = self._container.settings
        opened = await self._container.ledger.open_intent(
            telegram_user_id=self._telegram_user_id,
            product=Product.SINGLE,
            amount_minor=self._amount_minor,
            currency="UZS",
            # Deliberately not the bot's ``topup:{id}:{scope}:{seq}`` shape. A rehearsal row
            # must be identifiable as one forever, from the key alone, by an operator who has
            # only the journal in front of them.
            idempotency_key=f"harness:{self._run_id}:{scenario.name}",
            language="uz_latn",
            merchant_id=settings.payme_merchant_id,
            # Always true, whatever the process is configured with. Every row this script
            # writes is excluded from every future revenue figure by construction rather than
            # by a WHERE clause somebody has to remember to write.
            is_sandbox=True,
        )
        if is_err(opened):
            raise opened.error
        self.refs[scenario.name] = opened.value.public_ref
        return bindings_for(
            account_field=settings.payme_account_field,
            public_ref=opened.value.public_ref,
            amount_minor=self._amount_minor,
            duplicate_code=settings.payme_duplicate_transaction_code,
            now=self._container.clock(),
        )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
_PASS: Final[str] = "PASS"
_FAIL: Final[str] = "FAIL"


def render_report(outcomes: Sequence[ScenarioOutcome]) -> str:
    """The pass/fail table, as text. Pure, so it is testable without a gateway.

    Every step is printed, passing ones included. A report that listed only failures would be
    empty on a good run, and an empty terminal is indistinguishable from a script that never
    ran — which is not the thing to be uncertain about while somebody from Payme waits.
    """
    lines: list[str] = []
    for outcome in outcomes:
        scenario = outcome.scenario
        lines.append("")
        lines.append(f"== {scenario.name} — {_PASS if outcome.passed else _FAIL}")
        lines.append(f"   {scenario.narrative}")
        for step in outcome.steps:
            mark = _PASS if step.passed else _FAIL
            replay = " (replayed)" if step.replayed else ""
            lines.append(f"   [{mark}] {step.step.label}{replay}")
            lines.extend(f"          - {failure}" for failure in step.failures)
        if outcome.ledger_checked:
            mark = _PASS if not outcome.ledger_failures else _FAIL
            lines.append(f"   [{mark}] the money outcomes, counted in the database")
            lines.extend(f"          - {failure}" for failure in outcome.ledger_failures)
        else:
            lines.append("   [ -- ] the money outcomes were not checked (wire only)")
    passed = sum(1 for outcome in outcomes if outcome.passed)
    lines.append("")
    lines.append(f"{passed}/{len(outcomes)} scenarios passed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The entry point
#
# Split into ``plan`` (decide, from the command line alone) and ``apply`` (do it, against a
# live gateway), following ``bayram.tools.credits`` — the repository's other operator CLI and the
# precedent this one is deliberately shaped after. The split is what lets every refusal below
# be proved without a database, without a socket and without a process, which matters more here
# than usual: the run this script exists for happens once, on a scheduled call, and a typo that
# only surfaces after the container has been built is a typo discovered in front of an audience.
# ---------------------------------------------------------------------------
class RefusedError(Exception):
    """An operator-facing refusal. Its message is printed; nothing else is.

    An exception rather than a ``Result``, for the reason ``bayram.tools.credits.RefusedError``
    gives: :func:`main` is the boundary and there is no caller to hand a value back to. What it
    owes the operator is one sentence and an exit code, never a traceback carrying a DSN.
    """


@dataclass(frozen=True, slots=True)
class Request:
    """What one command line asks for, fully validated. Nothing here can still be wrong."""

    endpoint: str
    credentials: Credentials
    telegram_user_id: int
    amount_minor: int
    timeout_s: float
    #: Names this run inside every idempotency key it writes: ``harness:<run_id>:<scenario>``.
    #: A LABEL, so that "which rows did the 14:00 rehearsal write?" is answerable from the
    #: journal alone — not a way to replay. Reusing an id from a run that SETTLED will fail
    #: scenario two, because ``open_intent`` insert-or-ignores on the key and hands back the
    #: same order, which is by then ``paid`` and correctly refuses a second payment with
    #: ``-31051``. That refusal is the rail working; it is simply not what a rehearsal wants
    #: to see, so a fresh id is the default.
    run_id: str


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m bayram.payme.harness",
        description=(
            "Replay Payme's published sandbox scripts against a running bayram-payme gateway. "
            "Opens real intents (is_sandbox=true) through the ledger, drives the endpoint over "
            "HTTP, and prints a pass/fail table. Needs no Payme credential: the merchant key "
            "is only ever compared against itself."
        ),
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="the gateway's URL, e.g. http://127.0.0.1:8091/payme",
    )
    parser.add_argument(
        "--login",
        default="",
        help="Basic-auth login (default: BAYRAM_PAYME_BASIC_LOGIN, itself defaulting to Paycom)",
    )
    parser.add_argument(
        "--key",
        default="",
        help=(
            "the merchant key the gateway is running with (default: BAYRAM_PAYME_MERCHANT_KEY). "
            "Passing it here puts it in your shell history; prefer the dotenv."
        ),
    )
    parser.add_argument(
        "--telegram-user-id",
        required=True,
        help=(
            "whose account the rehearsal's credit lands on, and who receives the worker's "
            "'your payment went through' message. Use your own."
        ),
    )
    parser.add_argument(
        "--amount",
        default="700000",
        help="the price in TIYIN (default 700000 — 7 000 so'm; nothing here multiplies by 100)",
    )
    parser.add_argument(
        "--timeout", default="15", help="per-request timeout in seconds (default 15)"
    )
    parser.add_argument(
        "--run-id",
        default="",
        help=(
            "labels this run inside every idempotency key it writes, as "
            "harness:<run-id>:<scenario> (default: a fresh random one). Reuse an id only to "
            "re-run a rehearsal that did NOT settle: a paid order is terminal and correctly "
            "refuses a second payment."
        ),
    )
    return parser.parse_args(argv)


def _positive_int(raw: str, name: str) -> int:
    """``argparse``'s ``type=int`` accepts ``-1`` and ``0x10``, and both are worth refusing.

    The Telegram id is the only argument that identifies a person, and the amount is the only
    one that is money. Coercing either would turn a typo into a traceback at best and into a
    credit on somebody else's account at worst.
    """
    if not raw.isdigit() or int(raw) <= 0:
        raise RefusedError(f"{name} must be a positive integer, got {raw!r}")
    return int(raw)


def _run_id(raw: str) -> str:
    """A fresh id, or the operator's own — refused unless it is safely spellable in a key.

    It lands in ``payment_intents.idempotency_key``, which is what every replay in this system
    deduplicates on. A ``;`` or a ``:`` in it would not corrupt anything, but it would make the
    key unreadable at exactly the moment somebody is reading keys, so the alphabet is narrowed
    to something a person can retype from a terminal.
    """
    if not raw:
        return secrets.token_hex(4)
    if not raw.isalnum() or len(raw) > _MAX_RUN_ID:
        raise RefusedError(
            f"--run-id must be at most {_MAX_RUN_ID} letters and digits, got {raw!r}"
        )
    return raw


def plan(argv: Sequence[str], *, settings: PaymeSettings) -> Request:
    """What this command line asks for, validated — or a :class:`RefusedError`.

    ``settings`` is a parameter rather than a module-level read because two of the five fields
    default to it: the login and the key belong to the gateway being rehearsed against, and an
    operator who has them in ``/etc/bayram/payme.env`` should not have to retype a secret onto a
    command line where a shell history will keep it.
    """
    args = _parse(argv)
    credentials = Credentials(
        login=str(args.login) or settings.payme_basic_login,
        key=str(args.key) or settings.merchant_key,
    )
    if not credentials.key:
        raise RefusedError(
            "no merchant key: set BAYRAM_PAYME_MERCHANT_KEY in the gateway's dotenv or pass --key. "
            "Any 36-character string works before certification — it is only ever compared "
            "with itself."
        )
    return Request(
        endpoint=str(args.endpoint),
        credentials=credentials,
        telegram_user_id=_positive_int(str(args.telegram_user_id), "--telegram-user-id"),
        amount_minor=_positive_int(str(args.amount), "--amount"),
        timeout_s=float(_positive_int(str(args.timeout), "--timeout")),
        run_id=_run_id(str(args.run_id)),
    )


async def apply(request: Request, *, settings: PaymeSettings) -> list[ScenarioOutcome]:
    """Open an intent per scenario, drive the whole transcript, then read the intents back.

    The container is this script's own — built by ``bayram.payme.container.payme_container``, the
    same composition root the gateway boots from — so the intents it opens are opened by the
    same ``open_intent`` the bot's provider calls, against the same database the endpoint under
    test is writing to. Two processes, one schema; that is what makes the run real.
    """
    run_id = request.run_id
    _LOG.info(
        "payme certification rehearsal starting",
        extra={
            "event": "payme.harness.start",
            "run_id": run_id,
            "endpoint": request.endpoint,
            "scenarios": len(SCENARIOS),
            # The LENGTH, never the value. A key of the wrong length is the one credential
            # defect visible without printing a secret, and it is the likeliest one.
            "key_length": len(request.credentials.key),
        },
    )
    async with payme_container(settings) as container:
        opener = OpenBindings(
            container,
            amount_minor=request.amount_minor,
            telegram_user_id=request.telegram_user_id,
            run_id=run_id,
        )
        async with httpx.AsyncClient(timeout=request.timeout_s) as client:
            outcomes = await run_transcript(
                client,
                url=request.endpoint,
                scenarios=SCENARIOS,
                open_bindings=opener,
                credentials=request.credentials,
                account_field=settings.payme_account_field,
            )
        checked = [
            replace(
                outcome,
                ledger_failures=await check_intent(container, outcome, opener.refs),
                ledger_checked=True,
            )
            for outcome in outcomes
        ]
    _LOG.info(
        "payme certification rehearsal finished",
        extra={
            "event": "payme.harness.done",
            "run_id": run_id,
            "passed": sum(1 for outcome in checked if outcome.passed),
            "scenarios": len(checked),
        },
    )
    return checked


async def check_intent(
    container: PaymeContainer, outcome: ScenarioOutcome, refs: Mapping[str, str]
) -> tuple[str, ...]:
    """Read the intent back and compare its state with what the scenario claimed.

    The strongest money check this script can make over a socket. Counting receipts and credit
    ledger rows is the suite's job — it owns its database and can diff whole tables — but "the
    intent this scenario paid for is in state ``paid``" is checkable through the same port the
    notification job uses, and it is the assertion that catches a gateway that answered
    ``state: 2`` beautifully and claimed nothing.
    """
    public_ref = refs.get(outcome.scenario.name)
    if public_ref is None:
        return ("no intent was opened for this scenario",)
    found = await container.ledger.intent(public_ref=public_ref)
    if is_err(found):
        return (f"the intent could not be read back: {found.error!r}",)
    intent = found.value
    if intent is None:
        return (f"the intent {public_ref} is gone",)
    if intent.state is not outcome.scenario.expected_intent_state:
        return (
            f"the intent is {intent.state.value!r}, expected "
            f"{outcome.scenario.expected_intent_state.value!r}",
        )
    return ()


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises.

    Three codes, and the distinction is the one an operator on a certification call needs:
    ``0`` the transcript passed, ``1`` the gateway answered and some answer was wrong,
    ``2`` we never got as far as asking — a bad argument, a broken dotenv, or an endpoint that
    is not there. Only the middle one is a finding about the merchant API.
    """
    configure_logging(level="INFO", is_json=False)
    try:
        settings = build_payme_settings()
        request = plan(sys.argv[1:] if argv is None else argv, settings=settings)
    except RefusedError as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except BayramError as exc:
        print(f"harness: {exc.operator_message}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        outcomes = asyncio.run(apply(request, settings=settings))
    except httpx.HTTPError as exc:
        print(f"harness: {request.endpoint} could not be reached: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except BayramError as exc:
        print(f"harness: {exc.operator_message}", file=sys.stderr)
        return EXIT_CONFIG
    print(render_report(outcomes))
    print(
        f"\nrun id {request.run_id} — every order it opened carries the idempotency key "
        f"harness:{request.run_id}:<scenario>, which is how these rows are found again in the "
        f"journal. Use a FRESH id for the next rehearsal: a settled order is terminal."
    )
    return EXIT_OK if all(outcome.passed for outcome in outcomes) else EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
