"""The entitlement vocabulary: the refusals, the policy, and the leaf-module guarantee.

Nothing here touches a database. These are the pieces every gate and every fake will build
against, and three of them are load-bearing in a way that is easy to break silently:

* **The refusals are terminal.** ``Err.is_retryable`` drives the ARQ retry ladder in
  ``bayram.runtime.jobs``, so a retryable "you are out of credits" would re-run the whole
  pipeline on a schedule for an answer that cannot change until the calendar does.
* **They are not ``QUOTA_EXHAUSTED``.** That code belongs to ``ProviderQuotaExhaustedError``
  and renders ``error.service_unavailable`` — it would tell a customer who simply used
  their allowance that the studio is down, and would corrupt vendor-failure metrics with
  ordinary business declines.
* **``bayram.entitlements`` imports nothing but ``bayram.contracts`` and ``bayram.errors``.** Putting
  these types in ``contracts`` reproduced a real circular import; the leaf property is what
  lets ``bayram.db`` depend on this module, and it is asserted rather than assumed.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import bayram.entitlements as entitlements
from bayram.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    BalanceDrift,
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
from bayram.errors import BayramError, ConfigError, ErrorCode, ValidationError

#: The only first-party imports this module may ever have. See the module docstring.
_ALLOWED_FIRST_PARTY = {"bayram.contracts", "bayram.errors"}


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("error", "code", "key"),
    [
        (EntitlementError("x"), ErrorCode.ACCOUNT_BLOCKED, "error.blocked"),
        (
            InsufficientCreditsError("x"),
            ErrorCode.CREDITS_EXHAUSTED,
            "error.credits_exhausted",
        ),
        (
            TooManyOrdersInFlightError("x"),
            ErrorCode.TOO_MANY_IN_FLIGHT,
            "error.too_many_in_flight",
        ),
    ],
)
def test_every_entitlement_refusal_is_terminal_and_carries_its_own_locale_key(
    error: BayramError, code: ErrorCode, key: str
) -> None:
    # Arrange / Act / Assert — three distinct keys, because "you are blocked", "you are out
    # of credits" and "your last song is still rendering" are three different next actions.
    assert error.error_code is code
    assert error.user_message_key == key
    assert error.is_retryable is False
    assert error.is_terminal is True
    assert isinstance(error, EntitlementError)


def test_no_entitlement_refusal_borrows_the_provider_quota_code() -> None:
    # Arrange — QUOTA_EXHAUSTED means OUR balance with a vendor is gone and renders
    # "error.service_unavailable". A credit-less customer told the studio is down would be
    # a lie, and every vendor-failure dashboard would fill with ordinary declines.
    refusals = (
        EntitlementError("x"),
        InsufficientCreditsError("x"),
        TooManyOrdersInFlightError("x"),
    )

    # Act / Assert
    assert all(error.error_code is not ErrorCode.QUOTA_EXHAUSTED for error in refusals)
    assert len({error.user_message_key for error in refusals}) == 3


def test_a_refusal_carries_its_numbers_as_scalars_a_locale_string_can_interpolate() -> None:
    # Arrange — the gate has one chance to be useful. A refusal that says only "no" sends
    # the customer to support; these three scalars are what make the copy actionable.
    error = InsufficientCreditsError(
        "spent", context={"balance": 0, "needed": 1, "next_grant_at": "2026-04-05T00:00:00+00:00"}
    )

    # Act / Assert
    assert error.context["balance"] == 0
    assert error.context["needed"] == 1
    assert error.context["next_grant_at"].startswith("2026-04-05")


# ---------------------------------------------------------------------------
# The value objects
# ---------------------------------------------------------------------------
def test_a_credit_balance_is_frozen() -> None:
    # Arrange
    balance = CreditBalance(telegram_user_id=1, credits=3, in_flight=0, is_blocked=False)

    # Act / Assert
    with pytest.raises(PydanticValidationError):
        balance.credits = 9  # type: ignore[misc]


def test_a_credit_balance_can_report_a_negative_figure_rather_than_raising() -> None:
    # Arrange — `credits` is deliberately unbounded. The database constraint is what keeps a
    # real balance non-negative; a reader that raised on a drifted row would turn a
    # reporting problem into an outage at exactly the moment an operator needs to see it.
    balance = CreditBalance(telegram_user_id=1, credits=-2, in_flight=0, is_blocked=False)

    # Act / Assert
    assert balance.credits == -2
    with pytest.raises(PydanticValidationError):
        # An in-flight count is a COUNT(*), though, and a negative one is a bug in the query.
        CreditBalance(telegram_user_id=1, credits=0, in_flight=-1, is_blocked=False)


def test_a_balance_drift_names_both_representations_that_disagree() -> None:
    # Arrange / Act
    drift = BalanceDrift(telegram_user_id=7, balance=3, ledger_total=1)

    # Assert — an operator needs both numbers to know which one to trust.
    assert (drift.balance, drift.ledger_total) == (3, 1)
    with pytest.raises(PydanticValidationError):
        drift.balance = 0  # type: ignore[misc]


def test_the_two_outcome_enums_persist_the_values_the_ledger_keys_are_built_from() -> None:
    # Arrange / Act / Assert — these strings reach logs and, through the reason mapping,
    # the audit trail; renaming a member is a data change, not a refactor.
    assert [outcome.value for outcome in ChargeOutcome] == ["charged", "already_paid"]
    assert [outcome.value for outcome in SettlementOutcome] == [
        "delivered",
        "not_delivered",
        "failed",
    ]


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
def test_the_shipped_policy_is_three_credits_a_month_and_one_render_at_a_time() -> None:
    # Arrange / Act / Assert — the settled product decision, pinned so a later edit to the
    # defaults is a visible change rather than a silent one.
    assert DEFAULT_ENTITLEMENT_POLICY.allowance_credits == 3
    assert DEFAULT_ENTITLEMENT_POLICY.allowance_period_days == 30
    assert DEFAULT_ENTITLEMENT_POLICY.max_orders_in_flight == 1
    # The grace is the one number here that is DERIVED rather than chosen: it is every job
    # timeout arq will spend on one order plus the deferrals in between (see
    # ``derive_settlement_grace_s``). It was a flat 3600 until the sweep landed, which is
    # shorter than the 4500s of timeouts alone — a sweep on that grace would have refunded
    # orders that were still rendering. ``tests/test_runtime/test_cron.py`` pins it against
    # the real ``Settings``; this asserts the shipped value has not drifted.
    assert DEFAULT_ENTITLEMENT_POLICY.settlement_grace_s == 4_550


def test_the_policy_is_immutable() -> None:
    # Arrange
    policy = EntitlementPolicy()

    # Act / Assert — a frozen slotted dataclass: a caller cannot widen its own allowance.
    with pytest.raises(AttributeError):
        policy.allowance_credits = 99  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        # A zero period is a divisor, so this one would be a ZeroDivisionError inside a
        # transaction on a customer's first render rather than a startup failure.
        {"allowance_period_days": 0},
        {"allowance_credits": -1},
        {"max_orders_in_flight": 0},
        {"settlement_grace_s": 0},
    ],
)
def test_a_policy_that_cannot_be_enforced_is_refused_at_construction(
    overrides: dict[str, object],
) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ConfigError):
        EntitlementPolicy(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The rolling window
# ---------------------------------------------------------------------------
def test_the_period_index_only_advances_when_a_whole_window_has_passed() -> None:
    # Arrange — this index is the ``{index}`` in grant:period:{tg}:{index}, so it is the
    # entire idempotency of the mint: two processes agreeing on the instant must agree here.
    start = period_start(700, period_days=30)

    # Act / Assert
    assert period_index_for(start, period_days=30) == 700
    assert period_index_for(start + timedelta(days=29, hours=23), period_days=30) == 700
    assert period_index_for(start + timedelta(days=30), period_days=30) == 701


def test_the_window_start_is_the_instant_the_next_allowance_opens() -> None:
    # Arrange — a refusal quotes this date, so it has to be the real boundary rather than
    # "thirty days from whenever you last asked".
    now = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)

    # Act
    index = period_index_for(now, period_days=30)
    opens = period_start(index + 1, period_days=30)

    # Assert
    assert opens > now
    assert opens - period_start(index, period_days=30) == timedelta(days=30)
    assert period_index_for(opens, period_days=30) == index + 1


def test_a_naive_clock_is_rejected_rather_than_assumed_to_be_utc() -> None:
    # Arrange — guessing the zone would shift the window boundary by up to a day and mint a
    # second allowance. A ValidationError (an BayramError) is raised rather than a bare
    # ValueError so run_guarded converts it into an Err instead of letting it escape.
    naive = datetime(2026, 3, 21, 9, 0)

    # Act / Assert
    with pytest.raises(ValidationError):
        period_index_for(naive, period_days=30)


# ---------------------------------------------------------------------------
# The leaf guarantee
# ---------------------------------------------------------------------------
def test_the_entitlements_module_imports_nothing_but_contracts_and_errors() -> None:
    # Arrange — putting these types in bayram.contracts reproduced a real cycle
    # (contracts -> bayram.db.enums -> bayram/db/__init__ -> bayram.db.attempts -> contracts). This
    # module is what bayram.db imports, so a first-party import added here re-opens it. The
    # source is parsed rather than the runtime inspected, because a lazily-imported module
    # inside a function would still be a back-edge and would not show up in sys.modules.
    source = Path(entitlements.__file__).read_text(encoding="utf-8")

    # Act
    tree = ast.parse(source)
    from_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    plain_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    # Assert
    first_party = {name for name in from_imports | plain_imports if name.split(".")[0] == "bayram"}
    assert first_party == _ALLOWED_FIRST_PARTY
