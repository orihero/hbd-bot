"""The wire vocabulary: the envelope, the clocks, the codes and the two state enums.

Four properties are pinned here and every one of them is a certification scenario rather than
an implementation detail.

* **A ``jsonrpc`` member is accepted and never required.** Every documented request example
  omits it; some clients send it. A model that required it fails every published example, and
  one that rejected unknown members fails the day Payme adds one.
* **Every reply carries ``jsonrpc``, the echoed ``id``, and exactly ONE of ``result`` and
  ``error``.** "Exactly one" is asserted as an exclusive-or rather than as two membership
  checks, because a body carrying both is the shape a well-meaning helper produces when it
  adds a diagnostic ``error`` alongside a success.
* **An unset time is integer ``0`` and never ``null``.** The official PHP template emits
  ``null``; that is the known deviation. ``wire_time(None) == 0`` is asserted to be an ``int``
  and not merely falsy, because ``None``, ``0`` and ``0.0`` are all falsy and only one of them
  is right.
* **Every account-range message is a three-key map with three non-empty strings.** Payme's own
  interface renders these to a customer, so an empty ``uz`` is a blank refusal on a payment
  page we do not control and would never see in our own logs.

The state-enum totality tests are the quiet ones and they are the ones that would bite: a
member added to :class:`hbd.payme.protocol.PaymeState` without a matching entry in
``WIRE_STATE`` surfaces as a ``KeyError`` inside a settlement transaction, on the money path,
after a card has been charged.
"""

from __future__ import annotations

import ast
import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

import hbd.payme
import hbd.payme.auth
import hbd.payme.errors
import hbd.payme.link
import hbd.payme.protocol
import hbd.payme.rules
from hbd.checkout import PaymentIntentState
from hbd.errors import HbdError
from hbd.payme.errors import (
    PaymeAccountFault,
    PaymeAmountMismatch,
    PaymeFault,
    PaymeOrderDelivered,
    PaymeStateRefusal,
    PaymeTransactionNotFound,
)
from hbd.payme.protocol import (
    ACCOUNT_MESSAGES,
    DEFAULT_ACCOUNT_FIELD,
    JSONRPC_VERSION,
    MISSING_TIME,
    CancelReason,
    PaymeErrorCode,
    PaymeMethod,
    PaymeState,
    RpcRequest,
    WireState,
    from_ms,
    localised,
    render_fault,
    render_success,
    to_ms,
)
from hbd.payme.rules import (
    ACCOUNT_FAULT,
    DEFAULT_TRANSACTION_TIMEOUT_MS,
    WIRE_STATE,
    account_fault_for,
    is_expired,
    wire_state,
    wire_time,
)

#: A fixed instant with a whole-millisecond value, so nothing here rounds and nothing here
#: goes red at midnight.
_NOW: Final[datetime] = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: The three languages Payme's message map must carry. Exactly three, and not the bot's four.
_MESSAGE_KEYS: Final[frozenset[str]] = frozenset({"ru", "uz", "en"})


# ---------------------------------------------------------------------------
# The request envelope
# ---------------------------------------------------------------------------
def test_a_request_parses_with_and_without_a_jsonrpc_member() -> None:
    # Arrange — the first body is Payme's own documented shape; the second is what a
    # JSON-RPC-conformant client sends. Both must parse to the same request.
    documented: dict[str, Any] = {
        "method": "CheckPerformTransaction",
        "params": {"amount": 700_000, "account": {"order_id": "9f2c"}},
        "id": 1,
    }
    conformant: dict[str, Any] = {"jsonrpc": "2.0", **documented}

    # Act
    without = RpcRequest.model_validate(documented)
    with_member = RpcRequest.model_validate(conformant)

    # Assert
    assert without.method == with_member.method == PaymeMethod.CHECK_PERFORM_TRANSACTION
    assert without.id == with_member.id == 1
    assert without.params == with_member.params


def test_an_unknown_member_is_ignored_rather_than_rejected() -> None:
    # Arrange — the day Payme adds a member, a strict model refuses every request in
    # production and the fault looks like an outage rather than a schema change.
    body: dict[str, Any] = {
        "method": "CheckTransaction",
        "params": {"id": "6" * 24},
        "id": 7,
        "something_they_added_later": True,
    }

    # Act
    request = RpcRequest.model_validate(body)

    # Assert
    assert request.method == "CheckTransaction"
    assert not hasattr(request, "something_they_added_later")


@pytest.mark.parametrize(
    "body",
    [
        {"params": {}, "id": 1},
        {"method": "CheckTransaction", "id": 1},
        {"method": "CheckTransaction", "params": {}},
        {"method": "CheckTransaction", "params": [], "id": 1},
        {"method": "CheckTransaction", "params": {}, "id": "not-an-integer"},
    ],
    ids=["no method", "no params", "no id", "params is a list", "id is a string"],
)
def test_a_malformed_envelope_is_a_validation_failure_and_not_a_silent_default(
    body: dict[str, Any],
) -> None:
    # Arrange — each of these is answered with -32600 by the dispatcher. What must NOT happen
    # is a model that fills in a default and lets a method run against arguments nobody sent.

    # Act / Assert
    with pytest.raises(ValueError):
        RpcRequest.model_validate(body)


def test_a_parsed_request_is_frozen() -> None:
    # Arrange — the request is read by the dispatcher, the journal and the log line. A handler
    # that could edit ``params`` in place would make those three disagree about what arrived.
    request = RpcRequest.model_validate({"method": "CheckTransaction", "params": {}, "id": 3})

    # Act / Assert — through ``setattr`` because ``mypy --strict`` already refuses the direct
    # assignment, which is half the guarantee; this asserts the other half, that the refusal
    # also holds at runtime against code the type checker never saw.
    with pytest.raises(ValueError):
        setattr(request, "id", 4)  # noqa: B010


# ---------------------------------------------------------------------------
# The reply envelope
# ---------------------------------------------------------------------------
def test_a_success_envelope_carries_the_version_the_echoed_id_and_only_a_result() -> None:
    # Arrange / Act
    body = render_success({"allow": True}, request_id=42)

    # Assert
    assert body["jsonrpc"] == JSONRPC_VERSION
    assert body["id"] == 42
    assert body["result"] == {"allow": True}
    assert ("result" in body) ^ ("error" in body)


def test_a_fault_envelope_carries_the_version_the_echoed_id_and_only_an_error() -> None:
    # Arrange / Act
    body = render_fault(PaymeErrorCode.STATE_REFUSAL, "not a legal transition", request_id=42)

    # Assert
    assert body["jsonrpc"] == JSONRPC_VERSION
    assert body["id"] == 42
    assert body["error"] == {"code": -31008, "message": "not a legal transition"}
    assert ("result" in body) ^ ("error" in body)


def test_a_fault_echoes_a_null_id_when_the_body_never_parsed() -> None:
    # Arrange — a body that is not JSON has no id to echo, and the member must still be
    # present. Dropping it would leave Payme unable to match a retry to its own request.

    # Act
    body = render_fault(PaymeErrorCode.PARSE, "could not parse the request body", request_id=None)

    # Assert
    assert "id" in body
    assert body["id"] is None


def test_data_is_omitted_entirely_rather_than_sent_as_null() -> None:
    # Arrange — ``data`` is meaningful on exactly two populations: the account subfield name in
    # the -31050..-31099 range and the unknown method name on -32601. A null everywhere else
    # reads as "there was supposed to be something here".

    # Act
    without = render_fault(PaymeErrorCode.WRONG_AMOUNT, "amount mismatch", request_id=1)["error"]
    with_data = render_fault(
        PaymeErrorCode.METHOD_NOT_FOUND, "no such method", request_id=1, data="Frobnicate"
    )["error"]
    assert isinstance(without, dict)
    assert isinstance(with_data, dict)

    # Assert
    assert "data" not in without
    assert with_data == {"code": -32601, "message": "no such method", "data": "Frobnicate"}


def test_a_rendered_envelope_does_not_alias_the_account_message_constant() -> None:
    # Arrange — ``ACCOUNT_MESSAGES`` hands out read-only mappings, and a rendered body must be
    # an ordinary self-contained value the JSON serialiser can take. A body that aliased the
    # constant would make one request's reply mutable through another's.
    message = ACCOUNT_MESSAGES[PaymeErrorCode.ACCOUNT_UNKNOWN]

    # Act
    body = render_fault(
        PaymeErrorCode.ACCOUNT_UNKNOWN, message, request_id=1, data=DEFAULT_ACCOUNT_FIELD
    )
    rendered = body["error"]
    assert isinstance(rendered, dict)

    # Assert
    assert rendered["message"] == dict(message)
    assert rendered["message"] is not message
    assert isinstance(rendered["message"], dict)


# ---------------------------------------------------------------------------
# The millisecond clock
# ---------------------------------------------------------------------------
def test_a_moment_becomes_thirteen_digits_of_milliseconds() -> None:
    # Arrange / Act
    value = to_ms(_NOW)

    # Assert — milliseconds, not seconds. A seconds-based implementation would be exactly
    # 1000x smaller and would put every transaction in 1970 on Payme's side.
    assert value == 1_788_955_200_000
    assert len(str(value)) == 13


def test_the_clock_round_trips_and_comes_back_timezone_aware() -> None:
    # Arrange — ``from_ms``'s output goes straight into ``payme_transactions.payme_time``, and
    # ``hbd.db.base.UtcDateTime`` raises on a naive bind by design.

    # Act
    restored = from_ms(to_ms(_NOW))

    # Assert
    assert restored == _NOW
    assert restored.tzinfo is not None
    assert restored.utcoffset() == timedelta(0)


def test_a_naive_moment_is_read_as_utc_rather_than_as_local_time() -> None:
    # Arrange — every clock this system owns is aware, so a naive value can only have come
    # from a call site that reached for ``datetime.utcnow()``, for which this is the correct
    # answer. Raising instead would put an uncaught exception on the perform path.

    # Act / Assert
    assert to_ms(_NOW.replace(tzinfo=None)) == to_ms(_NOW)


def test_an_unset_time_serialises_as_the_integer_zero_and_never_as_none() -> None:
    # Arrange — the official PHP template emits null here; that is the known deviation, not the
    # specification. ``None``, ``0`` and ``0.0`` are all falsy and only one of them is right,
    # so the TYPE is asserted alongside the value.

    # Act
    unset = wire_time(None)

    # Assert
    assert unset == MISSING_TIME == 0
    assert isinstance(unset, int)
    assert unset is not None
    assert wire_time(_NOW) == to_ms(_NOW)


# ---------------------------------------------------------------------------
# The twelve-hour window
# ---------------------------------------------------------------------------
def test_the_window_is_measured_from_paymes_own_creation_instant() -> None:
    # Arrange — the specification says "from the moment the transaction was created in Payme
    # Business", which is ``params.time``. Measuring from our own ``created_at`` would close
    # the window early on exactly the transactions that had trouble reaching us.
    payme_time = _NOW
    inside = _NOW + timedelta(hours=11, minutes=59)
    outside = _NOW + timedelta(hours=12, minutes=1)

    # Act / Assert
    timeout = DEFAULT_TRANSACTION_TIMEOUT_MS
    assert is_expired(payme_time=payme_time, now=inside, timeout_ms=timeout) is False
    assert is_expired(payme_time=payme_time, now=outside, timeout_ms=timeout) is True


def test_at_the_exact_boundary_the_window_is_still_open() -> None:
    # Arrange — the two readings differ by one millisecond and they differ in DIRECTION. An
    # inclusive boundary refuses a payment we are entitled to take at the instant Payme's own
    # reference implementations would still perform it. Payme's templates compare with a
    # strict ``>``; so do we.
    timeout = DEFAULT_TRANSACTION_TIMEOUT_MS
    exactly = _NOW + timedelta(milliseconds=timeout)
    one_past = exactly + timedelta(milliseconds=1)

    # Act / Assert
    assert is_expired(payme_time=_NOW, now=exactly, timeout_ms=timeout) is False
    assert is_expired(payme_time=_NOW, now=one_past, timeout_ms=timeout) is True


def test_the_timeout_can_be_driven_in_seconds_so_the_expiry_branch_is_testable() -> None:
    # Arrange — the reason the window is a setting and not a constant: a twelve-hour literal
    # makes the cancel-then-refuse branch untestable in any run a human will watch, and an
    # untested branch on the money path is how "cancel first, refuse second" silently becomes
    # "refuse only".

    # Act / Assert
    assert is_expired(payme_time=_NOW, now=_NOW + timedelta(seconds=3), timeout_ms=2_000) is True
    assert is_expired(payme_time=_NOW, now=_NOW + timedelta(seconds=1), timeout_ms=2_000) is False


def test_a_clock_that_has_gone_backwards_never_expires_a_transaction() -> None:
    # Arrange — NTP steps, a restored snapshot, a container with a bad clock. A negative
    # elapsed time must read as "not expired": cancelling a live transaction because our own
    # clock jumped is money refused for a reason the customer had no part in.

    # Act / Assert
    assert (
        is_expired(
            payme_time=_NOW,
            now=_NOW - timedelta(hours=24),
            timeout_ms=DEFAULT_TRANSACTION_TIMEOUT_MS,
        )
        is False
    )


# ---------------------------------------------------------------------------
# The two state enums, and the crossing between them
# ---------------------------------------------------------------------------
def test_every_readable_state_maps_onto_exactly_one_wire_integer() -> None:
    # Arrange — a member added to one enum and forgotten in the other surfaces as a KeyError
    # inside a settlement, on the money path, after a card has been charged.

    # Act
    mapped = {state: wire_state(state) for state in PaymeState}

    # Assert
    assert set(WIRE_STATE) == set(PaymeState)
    assert sorted(mapped.values()) == sorted(int(member) for member in WireState)
    assert len(set(mapped.values())) == len(PaymeState)


def test_the_wire_integers_are_the_four_the_protocol_defines() -> None:
    # Arrange / Act / Assert — 1 created, 2 performed, -1 cancelled from created, -2 cancelled
    # after perform. The sign carries the cancellation; the magnitude carries whether money had
    # already moved, which is why -2 exists at all.
    assert wire_state(PaymeState.CREATED) == 1
    assert wire_state(PaymeState.PERFORMED) == 2
    assert wire_state(PaymeState.CANCELLED) == -1
    assert wire_state(PaymeState.CANCELLED_AFTER_PERFORM) == -2


def test_the_cancel_reasons_are_paymes_own_numbers() -> None:
    # Arrange / Act / Assert — echoed back numerically and persisted as a bare Integer, because
    # a VARCHAR mirror would be a translation table whose only failure mode is emitting a value
    # Payme does not recognise. Reason 4 is the one WE originate, on the expiry branch.
    assert int(CancelReason.TIMEOUT) == 4
    assert {int(member) for member in CancelReason} == {1, 2, 3, 4, 5, 10}


# ---------------------------------------------------------------------------
# The account range
# ---------------------------------------------------------------------------
def test_every_account_message_has_exactly_three_non_empty_languages() -> None:
    # Arrange — these are rendered by PAYME's interface to a customer in a browser we do not
    # control. An empty ``uz`` is a blank refusal on a payment page we would never see.

    # Act / Assert
    for code, message in ACCOUNT_MESSAGES.items():
        assert set(message) == _MESSAGE_KEYS, code
        assert all(text.strip() for text in message.values()), code


def test_the_account_range_is_exactly_the_five_codes_that_carry_data() -> None:
    # Arrange — the -31050..-31099 range is the only family that must carry ``data`` and a
    # message map, so "which codes are in it" and "which codes have messages" must be the same
    # question. -31054 is deliberately unallocated: the duplicate-transaction case goes through
    # the settable ``HBD_PAYME_DUPLICATE_TRANSACTION_CODE`` because Payme's own materials
    # contradict each other about it.
    account_range = {code for code in PaymeErrorCode if -31_099 <= code <= -31_050}

    # Act / Assert
    assert set(ACCOUNT_MESSAGES) == account_range
    assert len(account_range) == 5
    assert -31_054 not in {int(code) for code in PaymeErrorCode}


def test_a_terminal_intent_state_maps_to_its_account_code_and_a_live_one_maps_to_nothing() -> None:
    # Arrange / Act / Assert — ``pending`` is the healthy case and ``awaiting`` is a state
    # refusal through the settable duplicate code, which is a different range entirely. The
    # ``None`` is what makes mypy force every caller to say what it does with the healthy path.
    assert account_fault_for(PaymentIntentState.PAID) == PaymeErrorCode.ACCOUNT_ALREADY_PAID
    assert account_fault_for(PaymentIntentState.CANCELLED) == PaymeErrorCode.ACCOUNT_CANCELLED
    assert account_fault_for(PaymentIntentState.EXPIRED) == PaymeErrorCode.ACCOUNT_EXPIRED
    assert account_fault_for(PaymentIntentState.PENDING) is None
    assert account_fault_for(PaymentIntentState.AWAITING) is None
    assert set(ACCOUNT_FAULT) | {PaymentIntentState.PENDING, PaymentIntentState.AWAITING} == set(
        PaymentIntentState
    )


def test_the_method_names_are_the_exact_wire_spellings() -> None:
    # Arrange / Act / Assert — the casing is Payme's and it is significant; a comparison
    # against an inbound ``method`` needs no translation table. ChangePassword is present in
    # order to be REFUSED, so that we are not a -32601 surprise.
    assert PaymeMethod.CREATE_TRANSACTION.value == "CreateTransaction"
    assert PaymeMethod.CHANGE_PASSWORD.value == "ChangePassword"
    assert len(set(PaymeMethod)) == 7


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------
def test_every_fault_is_an_hbderror_so_run_guarded_already_catches_it() -> None:
    # Arrange — ``run_guarded`` catches NotFoundError, HbdError, IntegrityError, SQLAlchemyError
    # and pydantic's ValidationError. A fresh exception base would fall through all five and be
    # rendered as -32400 "internal error" instead of the refusal certification is asserting.
    faults = [
        PaymeAmountMismatch("amount mismatch"),
        PaymeTransactionNotFound("unknown transaction"),
        PaymeOrderDelivered("already delivered"),
        PaymeStateRefusal("illegal transition"),
        PaymeAccountFault("no such order"),
    ]

    # Act / Assert
    for fault in faults:
        assert isinstance(fault, HbdError)
        assert isinstance(fault, PaymeFault)
        assert fault.is_retryable is False


def test_each_fault_carries_the_code_the_protocol_assigns_it() -> None:
    # Arrange / Act / Assert
    assert PaymeAmountMismatch("x").rpc_code == -31001
    assert PaymeTransactionNotFound("x").rpc_code == -31003
    assert PaymeOrderDelivered("x").rpc_code == -31007
    assert PaymeStateRefusal("x").rpc_code == -31008


def test_the_state_refusal_code_is_settable_for_the_one_case_paymes_docs_contradict() -> None:
    # Arrange — "this order already has another active transaction": the sandbox text demands
    # -31008, PaycomUZ's template returns -31050 and three packages pick -31054 or -31099.

    # Act
    default = PaymeStateRefusal("illegal transition")
    duplicate = PaymeStateRefusal("another active transaction", rpc_code=-31_099)

    # Assert
    assert default.rpc_code == PaymeErrorCode.STATE_REFUSAL
    assert duplicate.rpc_code == -31_099


def test_an_account_fault_carries_the_subfield_name_that_becomes_error_data() -> None:
    # Arrange — ``data`` is the account subfield a human typed into the cabinet's «Настройка
    # Аккаунт» form. Payme's interface uses it to highlight which input the customer got wrong,
    # so the wrong name renders a correct refusal against the wrong box.

    # Act
    fault = PaymeAccountFault(
        "issued for another cashbox",
        rpc_code=PaymeErrorCode.ACCOUNT_WRONG_MERCHANT,
        account_field="hbd_ref",
    )

    # Assert
    assert fault.rpc_code == -31055
    assert fault.account_field == "hbd_ref"
    assert PaymeAccountFault("x").account_field == DEFAULT_ACCOUNT_FIELD


def test_adding_context_to_a_fault_preserves_its_code_and_its_subfield_name() -> None:
    # Arrange — ``HbdError.with_context`` rebuilds via ``type(self)(...)`` with the five base
    # keyword arguments only, so without the override in ``PaymeFault`` a -31055 would silently
    # become a -31050 on its way into a log line, and the wrong number is then the one Payme is
    # told about.
    fault = PaymeAccountFault(
        "issued for another cashbox",
        rpc_code=PaymeErrorCode.ACCOUNT_WRONG_MERCHANT,
        account_field="hbd_ref",
    )

    # Act
    enriched = fault.with_context(public_ref="9f2c4d6a8b0e1f3c5d7a9b0c")

    # Assert
    assert isinstance(enriched, PaymeAccountFault)
    assert enriched.rpc_code == -31055
    assert enriched.account_field == "hbd_ref"
    assert enriched.context["public_ref"] == "9f2c4d6a8b0e1f3c5d7a9b0c"


def test_no_fault_invents_a_locale_key_of_its_own() -> None:
    # Arrange — these sentences are for Payme's screen, in Payme's three languages, on a page
    # we do not control. A customer of ours never sees one, so a new ``error.*`` key would be a
    # string added to four bot catalogues for a screen that does not exist.

    # Act
    keys = {
        type(fault).__name__: fault.user_message_key
        for fault in (
            PaymeAmountMismatch("x"),
            PaymeTransactionNotFound("x"),
            PaymeOrderDelivered("x"),
            PaymeStateRefusal("x"),
            PaymeAccountFault("x"),
        )
    }

    # Assert — every one of them inherits the generic key that already exists in all four
    # catalogues. ``None`` was the alternative and it is not available: ``HbdError`` declares
    # the attribute as ``str``.
    assert set(keys.values()) == {"error.generic"}


def test_localised_builds_the_three_keys_in_the_documented_order() -> None:
    # Arrange / Act
    message = localised(ru="Заказ не найден", uz="Buyurtma topilmadi", en="Order not found")

    # Assert — the order Payme's own examples print, and exactly three keys. The bot's fourth
    # language has no slot here and must not acquire one by helpfulness.
    assert list(message) == ["ru", "uz", "en"]
    assert set(message) == _MESSAGE_KEYS


# ---------------------------------------------------------------------------
# The layering claim the package docstring makes
# ---------------------------------------------------------------------------
def _first_party_imports(module: ModuleType) -> set[str]:
    """Every ``hbd.*`` module ``module`` imports, including under ``if TYPE_CHECKING``.

    Parsed from the source rather than read off ``sys.modules``, for the reason
    ``tests/test_checkout/test_layering.py`` gives at length: a runtime check is green on a
    test run that happens not to have imported the forbidden module yet, so its verdict
    depends on collection order. Parsing also catches an import written inside
    ``if TYPE_CHECKING:`` — invisible at runtime, and exactly where somebody reaching for a
    row class would put it.
    """
    source = Path(str(module.__file__)).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return {name for name in imported if name.split(".")[0] == "hbd"}


@pytest.mark.parametrize(
    "module",
    [
        hbd.payme,
        hbd.payme.protocol,
        hbd.payme.errors,
        hbd.payme.auth,
        hbd.payme.link,
        hbd.payme.rules,
    ],
    ids=lambda module: str(module.__name__),
)
def test_the_wire_layer_imports_only_the_leaves_its_package_docstring_names(
    module: ModuleType,
) -> None:
    # Arrange — the package docstring's central claim: this package may see ``hbd.contracts``,
    # ``hbd.checkout``, ``hbd.errors`` and ``hbd.logging``, and may NEVER see ``hbd.db`` or
    # ``hbd.admin``. Persistence implements these ports from the other direction; a reach the
    # other way is an import cycle that fails at composition-root boot, on a deployment, with a
    # traceback naming neither module. ``hbd.admin`` is barred for a different and stronger
    # reason: it is a different process holding a different secret, and the import graph is
    # what keeps that separation from being merely an intention.
    permitted = {
        "hbd.contracts",
        "hbd.checkout",
        "hbd.errors",
        "hbd.logging",
        "hbd.payme",
        "hbd.payme.protocol",
        "hbd.payme.errors",
        "hbd.payme.auth",
        "hbd.payme.link",
        "hbd.payme.rules",
    }

    # Act
    imported = _first_party_imports(module)

    # Assert — a closed set rather than a blocklist, so a NEW first-party dependency has to be
    # argued for here, in the test about layering, instead of arriving as a line at the top of
    # a module nobody re-reads.
    assert imported <= permitted, sorted(imported - permitted)
    assert not {name for name in imported if name.startswith(("hbd.db", "hbd.admin"))}


#: The three modules the package docstring names as DOORS: a composition root, a readiness
#: probe and an operator tool. Everything else in ``hbd.payme`` must name ``hbd.db`` nowhere in
#: its own source, and this is the list that has to be edited — with an argument — before a
#: fourth one can exist.
_PERSISTENCE_DOORS: Final[frozenset[str]] = frozenset(
    {"hbd.payme.container", "hbd.payme.app", "hbd.payme.cli"}
)


def test_only_the_three_named_doors_reach_persistence() -> None:
    """The package docstring's central bar, checked over EVERY module rather than six of them.

    ``test_the_wire_layer_imports_only_the_leaves_its_package_docstring_names`` above asserts a
    CLOSED permitted set, which can only be written for the modules with a small, stable
    dependency list — the wire layer. It therefore says nothing about ``service``, ``settings``,
    ``ports``, ``provider``, ``pause`` or ``harness``, and those are the ones a later change is
    likely to reach into ``hbd.db`` from: ``provider`` wants a row, ``harness`` wants a count.

    So this test asserts the weaker claim over the WHOLE package: nothing but the three doors
    names ``hbd.db``, and nothing at all names ``hbd.admin``. ``harness`` is deliberately on the
    strict side of the line — it reaches persistence only through ``container``, which is what
    keeps "how many doors are there?" answerable by reading this frozenset.

    Discovered from the filesystem rather than listed, so a module added tomorrow is covered by
    this test on the day it lands rather than on the day somebody remembers to add it here.
    """
    # Arrange — every module in the shipped package, by import path.
    package_dir = Path(str(hbd.payme.__file__)).parent
    modules = sorted(
        f"hbd.payme.{path.stem}" for path in package_dir.glob("*.py") if path.stem != "__init__"
    )
    assert len(modules) >= 10, modules  # the inventory in the package docstring

    # Act / Assert
    for name in modules:
        imported = _first_party_imports(importlib.import_module(name))
        reaches_db = {item for item in imported if item.startswith("hbd.db")}
        if name in _PERSISTENCE_DOORS:
            assert reaches_db, f"{name} is listed as a door but reaches no persistence"
        else:
            assert not reaches_db, f"{name} reaches {sorted(reaches_db)}"
        assert not {item for item in imported if item.startswith("hbd.admin")}, name

    # Assert — and the doors are the ones the docstring names, not whatever happens to be true.
    assert set(modules) >= _PERSISTENCE_DOORS
