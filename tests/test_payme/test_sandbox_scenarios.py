"""The certification rehearsal: Payme's own sandbox scripts, driven through the real ASGI app.

**What this file answers.** "Will we pass certification?" — asked and answered before a
certification account exists. Payme certifies a merchant by walking two published scripts
against the endpoint and reading the replies; this suite walks the same table
(:data:`hbd.payme.harness.SCENARIOS`, shared verbatim with the operator script that replays it
against the live VPS) through the real router, the real dispatcher and the real ledger, and
then counts the rows.

**The headline property, and the only one the sandbox states in so many words.** «При
повторных вызовах... ответ должен совпадать с ответом из первого запроса». Every
``CreateTransaction``, ``PerformTransaction`` and ``CancelTransaction`` in the transcript is
issued TWICE and the second parsed reply is asserted EQUAL to the first with ``==``. That is
not a nicety: a replayed ``Perform`` that returned ``now()`` instead of the stored
``perform_time`` differs from the first reply by a few milliseconds, passes every
single-request test ever written, and fails certification intermittently.

**Why the money is counted and not read off the wire.** A reply saying ``state: 2`` is not
evidence that a credit was granted, and a reply saying ``-31007`` is not evidence that nothing
was reversed. Every scenario therefore carries its own money claim
(:data:`tests.test_payme.scenarios.MONEY_OUTCOMES`) and the claim is checked against
``topup_purchases``, ``plan_purchases`` and ``credit_ledger``: one credit after scenario two,
zero after scenario one.

**And why the checker itself is under test.** A conformance runner that always returned "no
failures" would make this whole file green and worthless, which is a specific and easy way to
ship a rehearsal that rehearses nothing. :func:`hbd.payme.harness.check_reply` therefore has
its own tests below, each feeding it a reply that is wrong in one documented way — a 405, a
``null`` where an integer ``0`` is required, an account-range error missing its three-key
message — and asserting it says so.

No network, no Redis, no Postgres, no marker: in-memory SQLite, a made-up 36-character key and
a recorder standing in for the ARQ enqueue. The one test in this workstream that does touch the
network is ``test_sandbox_link_live.py``, which is marked ``integration`` and excluded from
``make test``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import httpx
import pytest

from hbd.payme.app import PAYME_PATH, create_app
from hbd.payme.container import (
    PaymeContainer,
    SqlRpcJournal,
    build_payme_container,
    notify_job_id,
)
from hbd.payme.harness import (
    EXIT_CONFIG,
    REPLAYED_METHODS,
    Auth,
    Credentials,
    Expectation,
    OpenBindings,
    RefusedError,
    Scenario,
    ScenarioOutcome,
    Step,
    StepOutcome,
    check_reply,
    main,
    plan,
    render_report,
    run_scenario,
    run_transcript,
)
from hbd.payme.protocol import PaymeErrorCode, PaymeMethod
from hbd.payme.service import PaymeService
from hbd.payme.settings import PAYME_ENV_FILE_VAR, PaymeSettings, build_payme_settings
from tests.test_payme.scenarios import (
    MONEY_OUTCOMES,
    PLACEHOLDER_CREDENTIALS,
    PLACEHOLDER_KEY,
    PLACEHOLDER_LOGIN,
    PLACEHOLDER_MERCHANT,
    PRICE_MINOR,
    TELEGRAM_USER_ID,
    TRANSCRIPT,
    MoneyOutcome,
    money_after,
    transaction_count,
)

_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"
_ACCOUNT_FIELD: Final[str] = "order_id"
#: Fixed, so a failure message names the run that produced it and the idempotency keys the
#: transcript wrote are readable in a dump: ``harness:rehearsal:scenario-two``.
_RUN_ID: Final[str] = "rehearsal"


class _RecordingNotifier:
    """Stands in for the ARQ enqueue, so the suite can assert the customer was told.

    The gateway holds no Telegram token — that is the whole reason it is a fourth process — so
    the only thing it can do about a settled payment is hand the reference to a queue. What
    this records is that hand-off, and that it happened once per settlement and not once per
    request Payme sent.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, public_ref: str) -> None:
        self.calls.append(public_ref)


@pytest.fixture(autouse=True)
def _no_local_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The boot credential scan reads a file that does not exist, on every machine."""
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(tmp_path / "absent.env"))


def _settings(*, duplicate_code: int | None = None) -> PaymeSettings:
    overrides: dict[str, object] = {
        "_env_file": None,
        "database_url": _MEMORY_URL,
        "payme_enabled": True,
        "payme_merchant_id": PLACEHOLDER_MERCHANT,
        "payme_merchant_key": PLACEHOLDER_KEY,
        "payme_basic_login": PLACEHOLDER_LOGIN,
        "payme_account_field": _ACCOUNT_FIELD,
    }
    if duplicate_code is not None:
        overrides["payme_duplicate_transaction_code"] = duplicate_code
    return build_payme_settings(overrides)


async def _build(settings: PaymeSettings, notifier: _RecordingNotifier) -> PaymeContainer:
    """The production object graph with one edge swapped: the queue becomes a recorder.

    Everything else is real — the engine, ``SqlPaymeLedger``, the journal, the dispatcher — so
    what this suite drives is the gateway, not a rehearsal of it.
    """
    built = await build_payme_container(settings)
    return replace(
        built,
        service=PaymeService(
            built.ledger,
            clock=built.clock,
            journal=SqlRpcJournal(built.session_factory),
            notify=notifier,
            account_field=settings.payme_account_field,
            duplicate_code=settings.payme_duplicate_transaction_code,
        ),
    )


@pytest.fixture
def notifier() -> _RecordingNotifier:
    return _RecordingNotifier()


@pytest.fixture
async def container(notifier: _RecordingNotifier) -> AsyncIterator[PaymeContainer]:
    built = await _build(_settings(), notifier)
    yield built
    await built.aclose()


@pytest.fixture
async def client(container: PaymeContainer) -> AsyncIterator[httpx.AsyncClient]:
    """A client over the real application with its lifespan entered.

    The lifespan runs in the setup phase and not in a test body: ``configure_logging`` strips
    every root handler, and running it during the call phase would take pytest's own capture
    handler with it.
    """
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as opened:
            yield opened


def _opener(container: PaymeContainer) -> OpenBindings:
    return OpenBindings(
        container,
        amount_minor=PRICE_MINOR,
        telegram_user_id=TELEGRAM_USER_ID,
        run_id=_RUN_ID,
    )


def _explain(outcomes: list[ScenarioOutcome]) -> str:
    """The pass/fail table as the assertion's message. The same text certification day sees."""
    return render_report(outcomes)


# ---------------------------------------------------------------------------
# The transcript, one scenario at a time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario", TRANSCRIPT, ids=lambda scenario: scenario.name)
async def test_a_published_sandbox_scenario_passes_against_the_real_gateway(
    scenario: Scenario, client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """One scenario, one fresh gateway, both the wire and the money asserted.

    A fresh in-memory database per parametrisation is what makes the money claim readable:
    "one credit after scenario two, zero after scenario one" is a count of the whole table
    rather than a delta somebody has to compute.
    """
    # Arrange
    opener = _opener(container)
    bindings = await opener(scenario)

    # Act
    outcome = await run_scenario(
        client,
        url=PAYME_PATH,
        scenario=scenario,
        bindings=bindings,
        credentials=PLACEHOLDER_CREDENTIALS,
        account_field=_ACCOUNT_FIELD,
    )

    # Assert
    assert outcome.passed, _explain([outcome])
    assert (
        await money_after(container, public_ref=opener.refs[scenario.name])
        == MONEY_OUTCOMES[scenario.name]
    )


async def test_the_whole_transcript_passes_in_one_sitting_and_settles_exactly_one_song(
    client: httpx.AsyncClient, container: PaymeContainer, notifier: _RecordingNotifier
) -> None:
    """The rehearsal proper: every scenario in order against one gateway, as certification runs.

    Running them in one database is a different claim from running them apart. Four intents,
    seven rail-side transactions and one settlement share a schema here, so a scenario that
    accidentally cancelled another's transaction, or a ``GetStatement`` that leaked rows across
    an order, fails here and passes the parametrised test above.
    """
    # Arrange
    opener = _opener(container)

    # Act
    outcomes = await run_transcript(
        client,
        url=PAYME_PATH,
        scenarios=TRANSCRIPT,
        open_bindings=opener,
        credentials=PLACEHOLDER_CREDENTIALS,
        account_field=_ACCOUNT_FIELD,
    )

    # Assert
    assert all(outcome.passed for outcome in outcomes), _explain(outcomes)
    paid = MONEY_OUTCOMES["scenario-two"]
    counted = await money_after(container, public_ref=opener.refs["scenario-two"])
    assert counted == paid
    assert counted.receipts == 1
    assert counted.grants == 1
    # The customer is told by the WORKER — this process holds no Telegram token. The REPLAYED
    # perform enqueues a second time, which is correct and costs nothing: the job id is
    # deterministic in ``public_ref`` (``hbd.payme.container.notify_job_id``), so ARQ refuses
    # the duplicate and one settlement produces one message however many times Payme retries.
    assert set(notifier.calls) == {opener.refs["scenario-two"]}
    assert len({notify_job_id(call) for call in notifier.calls}) == 1


async def test_the_replayed_calls_wrote_no_second_transaction_row(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """A replayed CreateTransaction returns the stored row and writes nothing.

    The reply alone cannot tell that apart from a second row that happens to look identical —
    the unique index on ``payme_transaction_id`` is what makes the difference, and this counts
    it. The transcript creates exactly three transactions that reach the database: one in
    scenario one, one in scenario two, and one in the refusals scenario. The refusals'
    deliberately-duplicate second ``CreateTransaction`` is refused before it becomes a row,
    which is the mutex point doing its job.
    """
    # Arrange
    opener = _opener(container)

    # Act
    await run_transcript(
        client,
        url=PAYME_PATH,
        scenarios=TRANSCRIPT,
        open_bindings=opener,
        credentials=PLACEHOLDER_CREDENTIALS,
        account_field=_ACCOUNT_FIELD,
    )

    # Assert
    assert await transaction_count(container) == 3


# ---------------------------------------------------------------------------
# The property the sandbox actually states
# ---------------------------------------------------------------------------
async def test_every_create_perform_and_cancel_is_issued_twice_and_answered_identically(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """**The headline requirement.** The second response must EQUAL the first.

    Asserted here per step, explicitly, rather than left inside the runner: the runner already
    reports a mismatch as a failure, but this is the property the certification slot turns on
    and it is worth a test that names it and can be grepped for. It is also what forces every
    replayed method to answer from a STORED clock — ``create_time``, ``perform_time`` and
    ``cancel_time`` are all persisted precisely so a second call has something to return that
    is not ``now()``.
    """
    # Arrange
    opener = _opener(container)

    # Act
    outcomes = await run_transcript(
        client,
        url=PAYME_PATH,
        scenarios=TRANSCRIPT,
        open_bindings=opener,
        credentials=PLACEHOLDER_CREDENTIALS,
        account_field=_ACCOUNT_FIELD,
    )

    # Assert
    replayed = [
        step
        for outcome in outcomes
        for step in outcome.steps
        if step.step.method in REPLAYED_METHODS
    ]
    assert replayed, "the transcript must contain mutating calls, or it rehearses nothing"
    for step in replayed:
        assert step.replayed, f"{step.step.label} was never issued a second time"
        assert step.second == step.first, step.step.label


def test_the_repeat_rule_covers_exactly_the_three_methods_payme_resends() -> None:
    """The rule is a property of the METHOD, not a flag somebody remembers to set on a row.

    ``CheckPerformTransaction``, ``CheckTransaction`` and ``GetStatement`` are absent on
    purpose: they write nothing, so their repeat carries no guarantee worth asserting and
    doubling them would only double the transcript's runtime.
    """
    # Assert
    assert {
        PaymeMethod.CREATE_TRANSACTION.value,
        PaymeMethod.PERFORM_TRANSACTION.value,
        PaymeMethod.CANCEL_TRANSACTION.value,
    } == REPLAYED_METHODS


def test_the_transcript_opens_with_the_bad_auth_probe() -> None:
    """Certification starts where an attacker would, and so does this table."""
    # Assert
    first = TRANSCRIPT[0]
    assert first.name == "authorization"
    assert {step.auth for step in first.steps} == {
        Auth.WRONG_KEY,
        Auth.WRONG_LOGIN,
        Auth.MISSING,
    }
    assert all(step.expect.error_code == PaymeErrorCode.UNAUTHORISED for step in first.steps)


async def test_the_right_key_under_the_login_admin_is_still_refused(
    client: httpx.AsyncClient, container: PaymeContainer
) -> None:
    """The PayTechUz weakening, pinned over a socket rather than only against a function.

    That package splits the decoded credential on ``':'`` and compares only the trailing key,
    which accepts any username at all. We compare the WHOLE ``login:key`` pair, and this asserts
    it through the router where an over-helpful middleware could still have undone it.
    """
    # Arrange
    opener = _opener(container)
    scenario = TRANSCRIPT[0]
    bindings = await opener(scenario)

    # Act
    outcome = await run_scenario(
        client,
        url=PAYME_PATH,
        scenario=scenario,
        bindings=bindings,
        credentials=PLACEHOLDER_CREDENTIALS,
        account_field=_ACCOUNT_FIELD,
    )

    # Assert
    wrong_login = next(step for step in outcome.steps if step.step.auth is Auth.WRONG_LOGIN)
    assert wrong_login.passed, _explain([outcome])
    assert wrong_login.first["error"]["code"] == PaymeErrorCode.UNAUTHORISED


# ---------------------------------------------------------------------------
# The one code Payme's own materials disagree about
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("duplicate_code", [-31008, -31050], ids=["sandbox-text", "php-template"])
async def test_the_refusals_scenario_follows_the_configured_duplicate_code(
    duplicate_code: int, notifier: _RecordingNotifier
) -> None:
    """ "This order already has another active transaction" is a contradiction in their docs.

    The sandbox scenario text demands ``-31008``, PaycomUZ's own PHP template returns
    ``-31050``, and three third-party packages pick something else again. The code is therefore
    an environment variable, and the TRANSCRIPT'S EXPECTATION is late-bound to it — a table
    that hard-coded ``-31008`` would fail against a gateway behaving exactly as an operator
    configured it, which is the worst possible thing for a rehearsal to do on certification day.
    The envelope moves with the code too: everything in ``-31050..-31099`` is rendered to the
    customer by Payme's own interface and needs ``data`` plus a three-key message map.
    """
    # Arrange
    built = await _build(_settings(duplicate_code=duplicate_code), notifier)
    scenario = next(item for item in TRANSCRIPT if item.name == "refusals")
    try:
        application = create_app(container=built)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://g") as opened:
                bindings = await _opener(built)(scenario)

                # Act
                outcome = await run_scenario(
                    opened,
                    url=PAYME_PATH,
                    scenario=scenario,
                    bindings=bindings,
                    credentials=PLACEHOLDER_CREDENTIALS,
                    account_field=_ACCOUNT_FIELD,
                )
    finally:
        await built.aclose()

    # Assert
    assert outcome.passed, _explain([outcome])
    duplicate = next(step for step in outcome.steps if "SECOND transaction" in step.step.label)
    assert duplicate.first["error"]["code"] == duplicate_code


# ---------------------------------------------------------------------------
# The checker is under test too — a runner that always passes proves nothing
# ---------------------------------------------------------------------------
def _reply(**result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def _check(step: Step, body: dict[str, Any], *, status_code: int = 200) -> tuple[str, ...]:
    return check_reply(
        step,
        body,
        status_code=status_code,
        request_id=1,
        account_field=_ACCOUNT_FIELD,
        bindings={},
    )


_A_CHECK = Step(
    label="a state-1 transaction",
    method=PaymeMethod.CHECK_TRANSACTION.value,
    params={},
    expect=Expectation(state=1, positive=("create_time",), zero=("perform_time",)),
)


def test_the_checker_refuses_any_status_that_is_not_200() -> None:
    """Payme reads a 405 or a 500 as transport error -32400 and retries it."""
    # Act
    failures = _check(_A_CHECK, _reply(state=1, create_time=1, perform_time=0), status_code=405)

    # Assert
    assert any("405" in failure for failure in failures)


def test_the_checker_refuses_a_null_where_an_integer_zero_is_required() -> None:
    """The known deviation, and the reason ``zero`` exists as its own claim.

    Payme's own PHP template renders an unset ``perform_time`` as ``null``. It parses, it looks
    right in a terminal, and it is not what the specification says the field is.
    """
    # Act
    failures = _check(_A_CHECK, _reply(state=1, create_time=1, perform_time=None))

    # Assert
    assert any("integer 0 and never null" in failure for failure in failures)


def test_the_checker_refuses_a_wrong_state() -> None:
    # Act
    failures = _check(_A_CHECK, _reply(state=2, create_time=1, perform_time=0))

    # Assert
    assert any("state was 2" in failure for failure in failures)


def test_the_checker_accepts_the_reply_it_should() -> None:
    """The companion to the three above: the checker must not simply refuse everything."""
    # Act
    failures = _check(_A_CHECK, _reply(state=1, create_time=1_757_000_000_000, perform_time=0))

    # Assert
    assert failures == ()


def test_the_checker_demands_the_three_key_message_map_on_an_account_range_error() -> None:
    """Those strings are rendered by PAYME's interface to a customer, not by ours."""
    # Arrange
    step = Step(
        label="an unknown order",
        method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
        params={},
        expect=Expectation(error_code=PaymeErrorCode.ACCOUNT_UNKNOWN),
    )
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -31050, "message": "order not found", "data": _ACCOUNT_FIELD},
    }

    # Act
    failures = _check(step, body)

    # Assert
    assert any("{ru, uz, en}" in failure for failure in failures)


def test_the_checker_demands_the_account_subfield_name_in_data() -> None:
    """The single most likely go-live defect is a cabinet configured with a different name."""
    # Arrange
    step = Step(
        label="an unknown order",
        method=PaymeMethod.CHECK_PERFORM_TRANSACTION.value,
        params={},
        expect=Expectation(error_code=PaymeErrorCode.ACCOUNT_UNKNOWN),
    )
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -31050,
            "message": {"ru": "нет", "uz": "yoʻq", "en": "no"},
            "data": "phone",
        },
    }

    # Act
    failures = _check(step, body)

    # Assert
    assert any("Настройка Аккаунт" in failure for failure in failures)


def test_the_checker_refuses_an_unechoed_id() -> None:
    """A lost id echo is how a retry stops matching the request it is retrying."""
    # Act
    failures = _check(_A_CHECK, {"jsonrpc": "2.0", "id": 99, "result": {"state": 1}})

    # Assert
    assert any("id was 99" in failure for failure in failures)


def test_the_checker_refuses_a_reply_carrying_both_a_result_and_an_error() -> None:
    # Act
    failures = _check(_A_CHECK, {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -1}})

    # Assert
    assert any("exactly one of result and error" in failure for failure in failures)


def test_the_report_prints_every_step_and_names_the_failures() -> None:
    """A report listing only failures is empty on a good run, which reads as "never ran"."""
    # Arrange
    scenario = TRANSCRIPT[1]
    outcome = ScenarioOutcome(
        scenario=scenario,
        steps=(
            StepOutcome(step=scenario.steps[0], first={}, second=None, failures=()),
            StepOutcome(step=scenario.steps[1], first={}, second={}, failures=("state was 1",)),
        ),
        ledger_failures=("the intent is 'pending', expected 'paid'",),
        ledger_checked=True,
    )

    # Act
    report = render_report([outcome])

    # Assert
    assert scenario.steps[0].label in report
    assert "state was 1" in report
    assert "the intent is 'pending', expected 'paid'" in report
    assert "(replayed)" in report
    assert "0/1 scenarios passed" in report


def test_the_money_claims_are_derived_from_the_shipped_table_and_not_restated() -> None:
    """One claim, two halves. A scenario's script and its money outcome move together.

    If these were written out separately, the failure mode is a scenario whose steps were
    edited to perform a transaction while its money expectation still said zero credits — and
    that is a green test over a rail that grants nothing.
    """
    # Assert
    assert set(MONEY_OUTCOMES) == {scenario.name for scenario in TRANSCRIPT}
    assert MONEY_OUTCOMES["scenario-two"] == MoneyOutcome(
        receipts=1, grants=1, intent_state=TRANSCRIPT[2].expected_intent_state
    )
    assert sum(outcome.grants for outcome in MONEY_OUTCOMES.values()) == 1


def test_the_placeholder_key_is_thirty_six_characters() -> None:
    """The documented length, used everywhere, and never asserted at boot.

    ``PaymeSettings`` deliberately does NOT enforce 36 — the ``TEST_KEY``'s real length is
    unverified and a wrong assertion would be a boot failure on go-live day — so the length
    lives here, in the fixture that stands in for a credential nobody has yet.
    """
    # Assert
    assert len(PLACEHOLDER_KEY) == 36


def test_the_credentials_helper_produces_a_wrong_key_of_the_same_length() -> None:
    """Length-preserving is the stricter probe, and the shape a mistyped dotenv actually has."""
    # Arrange
    credentials = Credentials(login="Paycom", key=PLACEHOLDER_KEY)

    # Act
    good = credentials.header(Auth.VALID)
    bad = credentials.header(Auth.WRONG_KEY)

    # Assert
    assert good is not None and bad is not None
    assert len(good) == len(bad)
    assert good != bad
    assert credentials.header(Auth.MISSING) is None


# ---------------------------------------------------------------------------
# The operator command line — decided without a gateway, a socket or a database
# ---------------------------------------------------------------------------
_ENDPOINT: Final[str] = "http://127.0.0.1:8091/payme"


def _argv(*extra: str) -> list[str]:
    return ["--endpoint", _ENDPOINT, "--telegram-user-id", str(TELEGRAM_USER_ID), *extra]


def test_the_command_line_takes_its_credential_from_the_gateways_own_dotenv() -> None:
    """An operator must not have to retype a secret onto a line a shell history keeps."""
    # Act
    request = plan(_argv(), settings=_settings())

    # Assert
    assert request.credentials == Credentials(login=PLACEHOLDER_LOGIN, key=PLACEHOLDER_KEY)
    assert request.endpoint == _ENDPOINT
    assert request.amount_minor == PRICE_MINOR
    assert request.run_id


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--telegram-user-id", "-1"),
        ("--telegram-user-id", "0x10"),
        ("--telegram-user-id", "0"),
        ("--amount", "not-a-number"),
        ("--amount", "-700000"),
    ],
)
def test_a_malformed_number_is_refused_by_name_rather_than_coerced(flag: str, value: str) -> None:
    """``argparse``'s ``type=int`` accepts ``-1`` and ``0x10``; both are worth refusing.

    The Telegram id is the only argument that identifies a person and the amount is the only
    one that is money. A coerced typo grants a credit on somebody else's account.
    """
    # Arrange
    argv = ["--endpoint", _ENDPOINT, "--telegram-user-id", str(TELEGRAM_USER_ID), flag, value]

    # Act / Assert
    with pytest.raises(RefusedError, match=flag):
        plan(argv, settings=_settings())


def test_a_run_id_that_could_not_be_read_back_out_of_a_key_is_refused() -> None:
    """It lands inside ``payment_intents.idempotency_key``, which people read out of dumps."""
    # Act / Assert
    with pytest.raises(RefusedError, match="--run-id"):
        plan(_argv("--run-id", "one;two"), settings=_settings())


def test_a_run_id_is_taken_verbatim_so_a_rehearsals_rows_can_be_found_again() -> None:
    """The id is a LABEL inside every idempotency key: ``harness:<run-id>:<scenario>``.

    "Which rows did the 14:00 rehearsal write?" has to be answerable from the journal alone,
    and on a live host it is the only thing separating a rehearsal's orders from a customer's.
    It is deliberately not a way to replay: ``open_intent`` insert-or-ignores on the key, so
    reusing an id from a run that settled hands back an order that is already ``paid`` and
    correctly refuses a second payment with ``-31051``.
    """
    # Act
    first = plan(_argv("--run-id", "cert2026"), settings=_settings())
    second = plan(_argv("--run-id", "cert2026"), settings=_settings())

    # Assert
    assert first.run_id == second.run_id == "cert2026"
    assert first == second


def test_a_gateway_with_no_key_configured_is_refused_before_anything_is_opened() -> None:
    """Naming the variable, in the register ``hbd.config._describe_failure`` uses."""
    # Arrange — a settings object with the rail off, which is what ships by default.
    settings = build_payme_settings({"_env_file": None, "database_url": _MEMORY_URL})

    # Act / Assert
    with pytest.raises(RefusedError, match="HBD_PAYME_MERCHANT_KEY"):
        plan(_argv(), settings=settings)


def test_a_broken_dotenv_exits_two_rather_than_tracebacking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit ``2`` means "we never got as far as asking", which is not a finding about Payme.

    The three codes are the distinction an operator needs mid-certification: ``0`` passed,
    ``1`` the gateway answered and an answer was wrong, ``2`` we never asked. Only ``1`` is a
    finding about the merchant API, and conflating them costs a slot.
    """
    # Arrange — no HBD_DATABASE_URL anywhere, so building settings fails at the boundary.
    monkeypatch.delenv("HBD_DATABASE_URL", raising=False)

    # Act
    code = main(_argv())

    # Assert
    assert code == EXIT_CONFIG
