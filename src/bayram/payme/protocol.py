"""The Payme Merchant API wire vocabulary: names, codes, states, clocks and the envelope.

Everything in this module is a fact about Payme's protocol rather than a decision of ours,
and every one of those facts is spelled out ONCE, here, so that a certification finding is a
one-line edit in a file with no I/O in it. Nothing here reads a clock, opens a socket, holds
a credential or touches a session; the whole module is importable, callable and assertable
from a unit test with no fixtures at all. That is not an accident of scope — it is what makes
the protocol certifiable today, months before a merchant id exists.

**Five wire facts are load-bearing and each one has cost somebody a failed certification.**

1. **Every reply is HTTP 200, without exception.** That rule lives in the ASGI layer, but the
   reason it can be honoured lives here: :func:`render_fault` renders an error as a BODY, so
   a parse failure, a bad credential and an unhandled exception are all ordinary return
   values rather than status codes. Payme reads any non-200 as transport error ``-32300`` and
   retries; a 500 also costs us the ``id`` echo, so the retry cannot be matched to the request
   that provoked it.
2. **A ``jsonrpc`` member must be ACCEPTED and must never be REQUIRED.** Every documented
   request example omits it. :class:`RpcRequest` therefore declares three fields and
   ``extra="ignore"`` — a member we neither require nor reject. Our own responses always emit
   it, because a client that sends it will expect it back.
3. **Every timestamp on the wire is a 13-digit integer of MILLISECONDS since the Unix epoch,
   UTC.** Not seconds, not a string, not ISO-8601. :func:`to_ms` and :func:`from_ms` are the
   only two places that conversion happens.
4. **An unset time serialises as integer ``0`` and never as ``null``.** The official PHP
   template emits ``null`` and that is the known deviation, not the specification: payrest and
   PayTechUz both coerce to 0, and the sandbox's own scenario assertions compare against 0.
   :data:`MISSING_TIME` is that zero, named, so a reader of ``perform_time: 0`` can find out
   why in one jump.
5. **Errors in the ``-31050..-31099`` range MUST carry ``data`` set to the account subfield
   NAME and a ``message`` that is a map with exactly the three keys ``ru``, ``uz``, ``en``.**
   Those strings are rendered by PAYME's user interface, on a page we do not control, to a
   customer who never sees ours. They are therefore built here by :func:`localised` and
   deliberately NOT taken from ``bayram.bot.i18n``: that catalogue has FOUR languages because
   Uzbek is carried in two scripts, Payme's map has three and would silently drop one, and a
   locale key added for Payme's screen would then be scanned, parity-checked and translated by
   a test suite that exists to protect OUR screens.

**Two enums for the transaction state, and both are needed.** :class:`WireState` is the
integer Payme sends and expects — ``1``, ``2``, ``-1``, ``-2`` — and :class:`PaymeState` is
the string this application reasons in. They are separate for the same reason
``bayram.db.enums.PlanKind`` and ``bayram.checkout.Plan`` are separate: a column and a wire format
are two different audiences, an integer in a database row is unreadable in a psql session
during an incident, and a renamed member on one side must not silently become a different
number on the other. :func:`bayram.payme.rules.wire_state` is the single crossing point.

``PaymeState`` is also mirrored, value for value, by ``bayram.db.enums.PaymeState``, which is
what a mapped column stores — persistence does not put an application type in a column, and
this package may not import persistence, so the mirror is the only shape available. The two
are held together by ``tests/test_db/test_enum_lengths.py`` and by mypy, not by hope.

See ``PAYME_INTEGRATION §2`` for the two state machines as tables and ``§4`` for the account
code allocation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

__all__ = [
    "PaymeMethod",
    "PaymeErrorCode",
    "WireState",
    "PaymeState",
    "CancelReason",
    "MISSING_TIME",
    "DEFAULT_ACCOUNT_FIELD",
    "DEFAULT_AUTH_LOGIN",
    "JSONRPC_VERSION",
    "TRANSACTION_ID_LENGTH",
    "to_ms",
    "from_ms",
    "RpcRequest",
    "render_success",
    "render_fault",
    "localised",
    "ACCOUNT_MESSAGES",
]

#: The value of the ``jsonrpc`` member WE always emit. See wire fact 2 in the module
#: docstring: we emit it unconditionally and require it never.
JSONRPC_VERSION: Final[str] = "2.0"

#: An unset ``perform_time`` or ``cancel_time``. **Integer zero, never ``null``.**
MISSING_TIME: Final[int] = 0

#: The account subfield name Payme is configured with in the cabinet's «Настройка Аккаунт»
#: form, and the value that must appear in ``error.data`` for every ``-31050..-31099`` code.
#: A DEFAULT, not a constant: it is a string a human types into a web form on Payme's side,
#: so it is a setting (``BAYRAM_PAYME_ACCOUNT_FIELD``) whose default lives here beside the codes
#: that have to carry it. A mismatch between the two is the single most likely go-live defect,
#: which is why the dispatcher logs the field names actually RECEIVED alongside this one.
DEFAULT_ACCOUNT_FIELD: Final[str] = "order_id"

#: The Basic-auth login half. Both official merchant templates hard-code the literal string
#: ``Paycom``; the current documentation hedges on whether it is guaranteed, which is why the
#: gateway takes it as a setting and why the failure log line records the login it was
#: actually SENT. This is the default that setting starts from.
DEFAULT_AUTH_LOGIN: Final[str] = "Paycom"

#: Payme's transaction id is a Mongo ObjectId rendered as 24 hex characters. It is stored and
#: compared as a STRING and never parsed as a number — it is not one, and the leading zeros a
#: numeric parse would eat are significant.
TRANSACTION_ID_LENGTH: Final[int] = 24


class PaymeMethod(StrEnum):
    """The seven JSON-RPC methods, spelled exactly as they arrive on the wire.

    Values ARE the wire names, so a comparison against an inbound ``params["method"]`` needs
    no translation table. The casing is Payme's and is significant.

    ``CHANGE_PASSWORD`` is present deliberately, and it is the one member that is dispatched
    in order to be REFUSED. It is absent from the current documentation and survives only in
    the archived 2017 specification, so we cannot be certain it is dead — but implementing it
    would require the one internet-facing process in this system to rewrite its own credential
    on request, and key rotation on this deployment is a file edit and a restart. Answering it
    with an explicit ``-32400`` and a sentence saying so is a better outcome than a ``-32601``
    that reads as "this merchant does not implement the protocol".
    """

    CHECK_PERFORM_TRANSACTION = "CheckPerformTransaction"
    CREATE_TRANSACTION = "CreateTransaction"
    PERFORM_TRANSACTION = "PerformTransaction"
    CANCEL_TRANSACTION = "CancelTransaction"
    CHECK_TRANSACTION = "CheckTransaction"
    GET_STATEMENT = "GetStatement"
    CHANGE_PASSWORD = "ChangePassword"


class PaymeErrorCode(IntEnum):
    """Every JSON-RPC code this merchant can emit, and the three ranges they fall in.

    * ``-327xx`` / ``-326xx`` are JSON-RPC's own transport and envelope codes.
    * ``-325xx`` is Payme's authorisation range.
    * ``-31xxx`` is the merchant range: business refusals about an order or a transaction.
    * ``-31050..-31099`` is the ACCOUNT sub-range, and it is the only one whose members must
      carry ``data`` (the account subfield name) and a three-language ``message`` map.

    **``-31054`` is deliberately unallocated.** Payme's own materials contradict each other on
    what "this order already has another active transaction" should answer: the sandbox
    scenario text demands ``-31008``, PaycomUZ's own PHP template returns ``-31050``, and three
    widely-installed third-party packages pick ``-31054`` or ``-31099``. Rather than guess and
    bake the guess into an enum member that reads as settled fact, the duplicate case is
    emitted through the ``BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE`` setting, defaulting to
    ``STATE_REFUSAL``, so certification can flip it without a release. Allocating ``-31054``
    here would invite exactly the hard-coding that setting exists to prevent.

    ``ORDER_DELIVERED`` (``-31007``) is the answer to a CancelTransaction on a PERFORMED
    transaction, and it is unconditional in this implementation. No post-perform reversal is
    built: ``credit_accounts.balance`` is a single fungible scalar with no lot structure, so a
    debit compensating purchase A cannot know it is not burning a credit the customer paid for
    in purchase B. PaycomUZ's own template ships the same answer by default. See
    ``PAYME_INTEGRATION §6`` and the manual-refund runbook.
    """

    # -- JSON-RPC transport and envelope ------------------------------------
    TRANSPORT = -32300
    PARSE = -32700
    ENVELOPE = -32600
    METHOD_NOT_FOUND = -32601
    INTERNAL = -32400

    # -- authorisation ------------------------------------------------------
    UNAUTHORISED = -32504

    # -- merchant: the transaction ------------------------------------------
    WRONG_AMOUNT = -31001
    TRANSACTION_NOT_FOUND = -31003
    ORDER_DELIVERED = -31007
    STATE_REFUSAL = -31008

    # -- merchant: the account (these five, and only these, carry ``data``) --
    ACCOUNT_UNKNOWN = -31050
    ACCOUNT_ALREADY_PAID = -31051
    ACCOUNT_CANCELLED = -31052
    ACCOUNT_EXPIRED = -31053
    ACCOUNT_WRONG_MERCHANT = -31055


class WireState(IntEnum):
    """The transaction state as an INTEGER, which is the only form Payme speaks.

    Four values, and exactly three legal transitions: ``1 -> 2``, ``1 -> -1``, ``2 -> -2``.
    Everything else is ``-31008``. The negative pair is not "cancelled, twice" — the sign
    carries the cancellation and the magnitude carries whether money had already moved, which
    is why ``-2`` exists at all and why a merchant that never reverses a performed transaction
    still has to be able to REPORT one.
    """

    CREATED = 1
    PERFORMED = 2
    CANCELLED = -1
    CANCELLED_AFTER_PERFORM = -2


class PaymeState(StrEnum):
    """The transaction state as this application reasons about it, and as a column stores it.

    The readable mirror of :class:`WireState`. Mirrored value-for-value by
    ``bayram.db.enums.PaymeState``, which is what the mapped column actually uses — this package
    may never import persistence and persistence never puts an application type in a column,
    so two enums that agree is the only available shape, and it is the same one
    ``bayram.checkout.Plan`` and ``bayram.db.enums.PlanKind`` already take.

    Longest value is ``cancelled_after_perform`` at 23 characters, inside the 32-character
    ``ENUM_LENGTH`` that ``bayram.db.base.enum_type`` allocates. That is asserted on the
    persistence side, where the column is, rather than here.
    """

    CREATED = "created"
    PERFORMED = "performed"
    CANCELLED = "cancelled"
    CANCELLED_AFTER_PERFORM = "cancelled_after_perform"


class CancelReason(IntEnum):
    """Payme's own vocabulary for WHY a transaction was cancelled, echoed back numerically.

    These arrive from Payme on a CancelTransaction and are returned by CheckTransaction, so
    the numbers are theirs, not ours. They are persisted as a bare ``Integer`` column rather
    than as a mapped enum for exactly that reason: a VARCHAR mirror would be a translation
    table whose only possible failure mode is emitting a value Payme does not recognise, on a
    field they will send us members of that this enum does not list yet.

    :data:`TIMEOUT` is the one WE originate: it is the reason stamped when the twelve-hour
    window lapses and the transaction is cancelled before the refusal is returned.
    """

    RECEIVER_MISSING = 1
    DEBIT_ERROR = 2
    EXECUTION_ERROR = 3
    TIMEOUT = 4
    REFUND = 5
    UNKNOWN = 10


# ---------------------------------------------------------------------------
# The millisecond clock
# ---------------------------------------------------------------------------
_MS_PER_SECOND: Final[int] = 1000


def to_ms(moment: datetime) -> int:
    """``moment`` as a 13-digit integer of milliseconds since the Unix epoch, UTC.

    **A NAIVE datetime is interpreted as UTC rather than refused.** Every clock this system
    owns is ``bayram.db.base.utc_now()``, which is aware, and ``UtcDateTime`` raises on a naive
    bind, so a naive value can only arrive here from a call site that reached for
    ``datetime.utcnow()`` — for which "interpret as UTC" is the CORRECT answer. Raising would
    be the alternative, and it would put an uncaught exception on the perform path (nothing in
    ``run_guarded``'s except ladder catches a ``ValueError``) to punish a defect that produces
    the right number anyway.

    Truncates rather than rounds, so a value that round-trips through :func:`from_ms` is never
    later than the instant it came from — a transaction can be reported as created a fraction
    of a millisecond early, never late, and the twelve-hour window therefore never closes
    early on a customer.
    """
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return int(aware.timestamp() * _MS_PER_SECOND)


def from_ms(value: int) -> datetime:
    """A 13-digit millisecond epoch as a **timezone-aware UTC** datetime.

    Aware is not a nicety: ``params.time`` arrives from Payme and goes straight into
    ``payme_transactions.payme_time``, and ``bayram.db.base.UtcDateTime`` raises on a naive bind
    by design — "naive input is a bug at the call site, not something to paper over". This
    function is the boundary where the wire's integer becomes a value that column will accept.
    """
    return datetime.fromtimestamp(value / _MS_PER_SECOND, tz=UTC)


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------
class RpcRequest(BaseModel):
    """One inbound JSON-RPC request, parsed. Three fields, and one deliberate omission.

    **``extra="ignore"`` is the whole point of this class.** Payme's documented request
    examples do not carry a ``jsonrpc`` member; some clients and their own sandbox do. A model
    that REQUIRED it would fail every documented example, and a model that REJECTED unknown
    members would fail the moment Payme adds one. Ignoring extras accepts both populations and
    is the only reading of the specification under which every published example parses.

    ``id`` is an Integer on this protocol, not the JSON-RPC 2.0 union of string/number/null.
    It is echoed verbatim in every reply, including the error replies, because a merchant that
    loses the id turns Payme's retry into an unmatched call.

    ``params`` is left as an untyped mapping on purpose: the six methods take six different
    shapes, three of them nested, and validating them here would put six models in the
    envelope's file and make "the envelope parsed" and "the method's arguments were sensible"
    the same failure with the same code. They are different codes — ``-32600`` and ``-31050``
    respectively — so they stay different steps.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    method: str
    params: dict[str, Any]
    id: int


def render_success(result: Mapping[str, object], *, request_id: int | None) -> dict[str, object]:
    """The success envelope: ``jsonrpc``, the echoed ``id``, and ``result``. Never ``error``.

    ``request_id`` is ``int | None`` rather than ``int`` because the id is echoed even on the
    paths where we never successfully read one — a body that did not parse has no id, and the
    reply carries ``null``. The success path always has one, but sharing the signature with
    :func:`render_fault` is what keeps the two renderers structurally identical and therefore
    impossible to drift into emitting different envelope shapes.
    """
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": dict(result)}


def render_fault(
    code: int,
    message: str | Mapping[str, str],
    *,
    request_id: int | None,
    data: str | None = None,
) -> dict[str, object]:
    """The error envelope: ``jsonrpc``, the echoed ``id``, and ``error``. Never ``result``.

    ``message`` is a union because the protocol genuinely uses two shapes and the choice is
    not ours: the ``-31050..-31099`` account range MUST carry a three-key ``{ru, uz, en}`` map,
    which Payme's own interface renders to the customer, while ``-31001``, ``-31008`` and the
    JSON-RPC codes carry a plain string nobody but an operator ever reads. Collapsing them
    into one shape would mean either inventing translations for codes that have no customer
    behind them, or sending a bare string where the certification suite asserts a map.

    ``data`` is omitted from the payload entirely when ``None``, rather than sent as ``null``.
    It is meaningful on exactly two populations — the account subfield name in the
    ``-31050..-31099`` range, and the unknown method name on ``-32601`` — and a ``null`` on
    every other code would read as "there was supposed to be something here".
    """
    error: dict[str, object] = {"code": int(code), "message": _message_payload(message)}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def _message_payload(message: str | Mapping[str, str]) -> str | dict[str, str]:
    """Copy a mapping message so the caller cannot mutate a rendered envelope after the fact.

    :data:`ACCOUNT_MESSAGES` hands out read-only mappings; this turns one back into a plain
    ``dict`` for the JSON serialiser, which is what makes the returned envelope an ordinary,
    self-contained value rather than a view onto a module-level constant.
    """
    return message if isinstance(message, str) else dict(message)


def localised(ru: str, uz: str, en: str) -> dict[str, str]:
    """The mandatory three-key message map, in the order Payme's own examples print it.

    Positional rather than keyword because the argument NAMES are the language codes and
    spelling them twice at every call site would be noise; the order is fixed and asserted.

    Three keys, and exactly three. ``bayram.bot.i18n`` carries four languages because Uzbek is
    offered in both scripts and a customer who reads Cyrillic Uzbek is not a Russian speaker —
    but Payme's map has no slot for that distinction, so the two catalogues cannot be the same
    catalogue and this one is built by hand, here, next to the codes that carry it.
    """
    return {"ru": ru, "uz": uz, "en": en}


#: The five account-range messages, rendered by PAYME's interface and not by ours.
#:
#: Every string here is read by a customer who is looking at Payme's payment page, in a browser
#: we do not control, at a moment when they have just been refused. They therefore say what
#: happened to the ORDER in ordinary language and never mention a code, a merchant, an intent
#: or a state name — a customer told "state refusal" learns nothing and contacts Payme's
#: support rather than ours.
#:
#: The Uzbek is Latin script with U+02BB where the orthography calls for it, matching the rest
#: of this product; Payme's ``uz`` slot has no script variant, and Latin is what their own
#: interface uses. The Russian keeps ё, for the same reason the bot's catalogue does.
ACCOUNT_MESSAGES: Final[Mapping[PaymeErrorCode, Mapping[str, str]]] = MappingProxyType(
    {
        PaymeErrorCode.ACCOUNT_UNKNOWN: MappingProxyType(
            localised(
                ru="Заказ не найден",
                uz="Buyurtma topilmadi",
                en="Order not found",
            )
        ),
        PaymeErrorCode.ACCOUNT_ALREADY_PAID: MappingProxyType(
            localised(
                ru="Заказ уже оплачен",
                uz="Buyurtma allaqachon toʻlangan",
                en="This order has already been paid",
            )
        ),
        PaymeErrorCode.ACCOUNT_CANCELLED: MappingProxyType(
            localised(
                ru="Заказ отменён",
                uz="Buyurtma bekor qilingan",
                en="This order was cancelled",
            )
        ),
        PaymeErrorCode.ACCOUNT_EXPIRED: MappingProxyType(
            localised(
                ru="Срок действия заказа истёк",
                uz="Buyurtma muddati tugagan",
                en="This order has expired",
            )
        ),
        PaymeErrorCode.ACCOUNT_WRONG_MERCHANT: MappingProxyType(
            localised(
                ru="Заказ оформлен для другой кассы",
                uz="Buyurtma boshqa kassa uchun rasmiylashtirilgan",
                en="This order was issued for a different cashbox",
            )
        ),
    }
)
