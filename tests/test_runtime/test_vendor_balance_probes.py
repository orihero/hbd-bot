"""The two balance probes: the parsers, and the failure taxonomy. No database, no socket.

The whole point of the probe layer is that a vendor who renames a field, answers with HTML,
or is simply down must produce **an honest absence and never a zero**. A zero here is not a
cosmetic bug: it is the number an operator reads to decide whether to top up before New
Year, and ``0 characters remaining`` reads as "stop shipping" exactly as
``generation_attempts.cost_usd DEFAULT 0.0`` reads as "free".

So this file is organised around what the probes REFUSE to produce.

* No arithmetic on an absence. ElevenLabs' ``character_count`` without a ``character_limit``
  yields three ``None``s, not a computed remainder; ``character_limit: 0`` yields ``None``,
  not ``0``.
* No number from a non-number. ``"usage": true`` is a bool, which is an ``int`` in Python,
  and it yields ``None`` — the same trap ``openai_compat._token_count`` exists for.
* No conflation of two different unknowns. An uncapped OpenRouter key is
  ``is_unbounded=True`` with a null balance; an unread body is ``is_unbounded=None`` with a
  null balance. A tile that renders those the same way is wrong in one of two opposite
  directions.
* No reading of ``data.label``. It is the one field on either vendor's response that could
  carry a person's name, and the "``vendor_balances`` holds no personal data" classification
  is only true because nothing parses it. That is asserted here rather than trusted.
* No successful-looking probe out of a failure. Six failure shapes are driven through a
  ``MockTransport`` and every one of them produces ``reading=None`` with an error code from
  the closed ``hbd.errors`` taxonomy.
* No spending of the management credential beyond the one thing it was accepted for. The
  account's prepaid pool is read from ``/api/v1/credits`` — a fifth secret the module
  docstring once refused, now held under the fences asserted below: the call is made only
  when the key reported no cap, it carries the MANAGEMENT key and never the inference one,
  and every way it can fail leaves the ``/key`` reading exactly as it was.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import httpx
import pytest

from hbd.contracts import BalanceUnit, Vendor
from hbd.errors import ErrorCode
from hbd.runtime.vendor_balance_probes import (
    ELEVENLABS_PROBE_NAME,
    OPENROUTER_CREDITS_PATH,
    OPENROUTER_KEY_PATH,
    OPENROUTER_LEGACY_KEY_PATH,
    OPENROUTER_PROBE_NAME,
    BalanceProbe,
    ElevenLabsSubscriptionPayload,
    OpenRouterKeyPayload,
    _elevenlabs_reading,
    _openrouter_reading,
    is_openrouter,
    openrouter_probe_url,
    probe_elevenlabs,
    probe_openrouter,
)

pytestmark = pytest.mark.anyio

type Handler = Callable[[httpx.Request], httpx.Response]

_OPENROUTER_BASE: Final[str] = "https://openrouter.ai/api/v1"
_ELEVENLABS_BASE: Final[str] = "https://api.elevenlabs.io"
_TIMEOUT_S: Final[float] = 5.0
#: Two DIFFERENT strings on purpose. The management key can create and revoke API keys, so
#: "which credential went to which endpoint" is a thing these tests assert rather than assume.
_INFERENCE_KEY: Final[str] = "inference-key"
_MANAGEMENT_KEY: Final[str] = "management-key"
_KEY_PATH: Final[str] = f"/api/v1{OPENROUTER_KEY_PATH}"
_CREDITS_PATH: Final[str] = f"/api/v1{OPENROUTER_CREDITS_PATH}"


def _client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _always(response: httpx.Response) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        return response

    return handler


def _openrouter(**data: Any) -> Any:
    """The ``{"data": {...}}`` envelope OpenRouter wraps its answer in."""
    return _openrouter_reading(OpenRouterKeyPayload.model_validate({"data": data}))


def _elevenlabs(**body: Any) -> Any:
    return _elevenlabs_reading(ElevenLabsSubscriptionPayload.model_validate(body))


async def _probe_openrouter(
    handler: Handler, *, base_url: str = _OPENROUTER_BASE, management_key: str = ""
) -> BalanceProbe:
    async with _client(handler) as client:
        return await probe_openrouter(
            client,
            api_key=_INFERENCE_KEY,
            base_url=base_url,
            is_fallback=False,
            timeout_s=_TIMEOUT_S,
            management_key=management_key,
        )


async def _probe_elevenlabs(handler: Handler) -> BalanceProbe:
    async with _client(handler) as client:
        return await probe_elevenlabs(
            client, api_key="k", base_url=_ELEVENLABS_BASE, timeout_s=_TIMEOUT_S
        )


# ---------------------------------------------------------------------------
# The OpenRouter parser
# ---------------------------------------------------------------------------
def test_a_full_openrouter_body_maps_onto_the_three_quantities() -> None:
    # Arrange / Act — a capped key, which is the shape the tile is actually for.
    reading = _openrouter(limit=50.0, limit_remaining=12.4, usage=37.6, limit_reset="monthly")

    # Assert
    assert reading.balance_remaining == pytest.approx(12.4)
    assert reading.balance_total == pytest.approx(50.0)
    assert reading.balance_used == pytest.approx(37.6)
    assert reading.is_unbounded is False


def test_an_uncapped_key_is_unbounded_and_still_has_no_balance() -> None:
    # Arrange / Act — ``limit: null`` on a key with no cap set.
    reading = _openrouter(limit=None, limit_remaining=None, usage=3.5)

    # Assert — the two unknowns stay apart. ``is_unbounded=True`` says "unknown because
    # uncapped"; a ``None`` there would say "unknown because unpolled", and those are a
    # healthy deployment and a broken poller.
    assert reading.is_unbounded is True
    assert reading.balance_remaining is None
    assert reading.balance_total is None
    assert reading.balance_used == pytest.approx(3.5)


def test_a_body_that_reported_nothing_at_all_is_not_evidence_of_being_uncapped() -> None:
    # Arrange / Act — every field absent, e.g. after a vendor rename.
    reading = _openrouter()

    # Assert — three-valued on purpose. Neither a limit nor a usage figure means the vendor
    # said nothing, and "said nothing" is not "said unlimited".
    assert reading.is_unbounded is None
    assert reading.balance_remaining is None
    assert reading.balance_total is None
    assert reading.balance_used is None


def test_a_reset_cadence_is_a_hint_and_never_an_instant() -> None:
    # ``limit_reset`` is a PHRASE (``monthly``), not a timestamp. A cadence rendered as a
    # clock is a lie with a date on it, so it lands in the hint column and nowhere else.
    reading = _openrouter(limit=10.0, limit_reset="monthly")

    assert reading.quota_reset_hint == "monthly"
    assert reading.quota_resets_at is None


def test_the_key_label_is_never_parsed_and_reaches_no_field() -> None:
    # THE PRIVACY CLAIM, asserted rather than documented. ``data.label`` is the operator's
    # own free-text name for the API key and in practice reads like a person's name; it is
    # the only field on either vendor's response that could. ``vendor_balances``' "holds no
    # personal data" classification is true only because nothing reads it.
    reading = _openrouter(label="Sardor laptop dev key", limit=10.0, limit_remaining=4.0)

    assert "Sardor laptop dev key" not in repr(reading)
    assert not hasattr(reading, "label")
    assert all(
        value != "Sardor laptop dev key"
        for value in (
            reading.quota_reset_hint,
            reading.plan_tier,
            reading.subscription_status,
        )
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="a bool is an int in python and measures nothing"),
        pytest.param(False, id="and so is false"),
        pytest.param(-1.0, id="a negative is not a measurement"),
        pytest.param(float("nan"), id="a nan propagates through every aggregate"),
        pytest.param(float("inf"), id="and so does an infinity"),
        pytest.param("12.40", id="a string is a field we do not understand"),
        pytest.param(None, id="an absence"),
    ],
)
def test_a_value_that_is_not_a_measurement_reads_as_none_and_never_as_a_number(
    value: Any,
) -> None:
    # The narrowing that makes a renamed or retyped vendor field degrade to "not reported"
    # rather than to a fabricated quantity or a failed probe.
    reading = _openrouter(usage=value)

    assert reading.balance_used is None


# ---------------------------------------------------------------------------
# The ElevenLabs parser
# ---------------------------------------------------------------------------
def test_the_elevenlabs_remainder_is_computed_from_both_halves() -> None:
    # Arrange / Act
    reading = _elevenlabs(character_limit=500_000, character_count=120_000)

    # Assert
    assert reading.balance_remaining == pytest.approx(380_000.0)
    assert reading.balance_total == pytest.approx(500_000.0)
    assert reading.balance_used == pytest.approx(120_000.0)
    assert reading.is_unbounded is False


def test_a_character_count_with_no_limit_yields_no_remainder_at_all() -> None:
    # THE ``SubscriptionPayload`` TRAP. That model — one import away, and parsing this very
    # endpoint — defaults both counts to 0, which is correct for a health verdict and poison
    # here: it turns an absent limit into "0 characters remaining" on the top-up tile.
    reading = _elevenlabs(character_count=120_000)

    assert reading.balance_remaining is None
    assert reading.balance_total is None
    assert reading.balance_used == pytest.approx(120_000.0)
    # Never inferred True: an ElevenLabs subscription always has a character allowance, so
    # an absent limit is a body we could not read and not an unlimited plan.
    assert reading.is_unbounded is None


def test_a_zero_character_limit_is_a_body_we_do_not_understand_and_not_an_empty_account() -> None:
    # Subtracting from a zero limit would produce exactly the fabricated zero this module
    # exists to refuse, and an exhausted account is reported by a limit with a count equal
    # to it — not by a limit of nothing.
    reading = _elevenlabs(character_limit=0, character_count=120_000)

    assert reading.balance_remaining is None
    assert reading.balance_total == pytest.approx(0.0)
    assert reading.is_unbounded is None


def test_an_overspent_account_reports_zero_remaining_rather_than_a_negative() -> None:
    # A real measurement that happens to be zero, which is a different thing from an absence
    # and must survive as a number. A negative balance is not a quantity anybody can act on.
    reading = _elevenlabs(character_limit=100.0, character_count=140.0)

    assert reading.balance_remaining == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(1_800_000_000, datetime(2027, 1, 15, 8, 0, tzinfo=UTC), id="an epoch second"),
        pytest.param(0, None, id="a zero is not an instant"),
        pytest.param(-5, None, id="nor is a negative"),
        pytest.param(1_800_000_000_000, None, id="milliseconds are a field we misread"),
    ],
)
def test_the_reset_instant_is_read_only_when_it_is_plausibly_one(
    value: int, expected: datetime | None
) -> None:
    # A date in 1970, or one in the year 55000, is worse than no date: it renders.
    reading = _elevenlabs(
        character_limit=10, character_count=1, next_character_count_reset_unix=value
    )

    if expected is None:
        assert reading.quota_resets_at is None
    else:
        assert reading.quota_resets_at is not None
        assert reading.quota_resets_at.tzinfo is not None
        assert reading.quota_resets_at.astimezone(UTC) == expected


def test_the_vendors_own_vocabulary_passes_through_and_a_blank_one_does_not() -> None:
    # An empty tier is not a tier and a whitespace status is not a status: both become
    # ``None`` rather than a value that would sort and group like a real one.
    named = _elevenlabs(tier="creator", status="active")
    blank = _elevenlabs(tier="   ", status="")

    assert (named.plan_tier, named.subscription_status) == ("creator", "active")
    assert (blank.plan_tier, blank.subscription_status) == (None, None)


# ---------------------------------------------------------------------------
# The URL join, and the path ladder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "base_url",
    ["https://openrouter.ai/api/v1", "https://openrouter.ai", "https://openrouter.ai/api/v1/"],
)
def test_both_spellings_of_the_base_url_resolve_to_one_endpoint(base_url: str) -> None:
    # ``HBD_LLM_BASE_URL`` ships versioned and a host-only value is just as legal. Naive
    # concatenation gives ``/api/v1/v1/key`` and a 404 whose HTML body then defeats any
    # attempt to read the real cause.
    assert openrouter_probe_url(base_url, OPENROUTER_KEY_PATH) == (
        "https://openrouter.ai/api/v1/key"
    )


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://openrouter.ai/api/v1", True),
        ("openrouter.ai", True),
        ("https://OpenRouter.AI/api/v1", True),
        ("https://generativelanguage.googleapis.com/v1beta", False),
        # The host, not the whole URL: a self-hosted gateway with the marker in a PATH
        # answers no key endpoint and must not be probed as though it did.
        ("https://gateway.internal/openrouter.ai/v1", False),
    ],
)
def test_only_a_real_openrouter_host_is_recognised(base_url: str, expected: bool) -> None:
    assert is_openrouter(base_url) is expected


async def test_a_404_on_the_current_path_falls_back_to_the_historical_spelling() -> None:
    # Arrange — OpenRouter has published this endpoint both ways, and that is the one fact
    # about either vendor that could not be pinned to a single answer.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        # An exact comparison, not ``endswith``: ``/api/v1/auth/key`` also ends in
        # ``/key``, and a handler that matched both would 404 the fallback too and prove
        # nothing about the ladder.
        if request.url.path == f"/api/v1{OPENROUTER_KEY_PATH}":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"data": {"limit": 10.0, "limit_remaining": 4.0}})

    # Act
    probe = await _probe_openrouter(handler)

    # Assert
    assert probe.is_success is True
    assert probe.reading is not None
    assert probe.reading.balance_remaining == pytest.approx(4.0)
    assert seen == ["/api/v1/key", f"/api/v1{OPENROUTER_LEGACY_KEY_PATH}"]


async def test_a_404_from_both_paths_is_a_failed_probe_and_never_an_empty_reading() -> None:
    # Act
    probe = await _probe_openrouter(_always(httpx.Response(404, json={"error": "gone"})))

    # Assert — no reading at all. An empty ``BalanceReading`` here would be indistinguishable
    # from a 200 that reported nothing, and only one of those means the endpoint moved.
    assert probe.is_success is False
    assert probe.reading is None
    assert probe.http_status == 404
    assert probe.error_code


async def test_a_500_does_not_trigger_the_legacy_retry() -> None:
    # Arrange — only a 404 means "wrong path". Retrying an outage against a second path
    # would report the outage as a missing endpoint, and the two have different remedies.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(500, text="upstream is unwell")

    # Act
    probe = await _probe_openrouter(handler)

    # Assert
    assert seen == ["/api/v1/key"]
    assert probe.is_success is False
    assert probe.error_code == ErrorCode.UPSTREAM_5XX.value


# ---------------------------------------------------------------------------
# The account pool, and the credential it costs
# ---------------------------------------------------------------------------
def _uncapped_key() -> httpx.Response:
    """What ``/key`` answers for a key with no spend cap: a usage figure and no denominator."""
    return httpx.Response(200, json={"data": {"limit": None, "usage": 3.5}})


def _ladder(**by_path: httpx.Response) -> tuple[Handler, list[httpx.Request]]:
    """A handler that answers per PATH, and the requests it saw, in order."""
    seen: list[httpx.Request] = []
    routes = {_KEY_PATH: by_path.get("key"), _CREDITS_PATH: by_path.get("credits")}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response = routes.get(request.url.path)
        if response is None:
            return httpx.Response(404, json={"error": "not routed by this test"})
        return response

    return handler, seen


async def test_an_uncapped_key_gets_its_denominator_from_the_account_pool() -> None:
    # Arrange — the case the whole credential was accepted for: ``/key`` reports no cap, so
    # there is a usage figure and nothing to take a percentage of.
    handler, seen = _ladder(
        key=_uncapped_key(),
        credits=httpx.Response(200, json={"data": {"total_credits": 40.0, "total_usage": 12.5}}),
    )

    # Act
    probe = await _probe_openrouter(handler, management_key=_MANAGEMENT_KEY)

    # Assert — the pool, and the subtraction done from two numbers that were both reported.
    assert probe.reading is not None
    assert probe.reading.balance_total == pytest.approx(40.0)
    assert probe.reading.balance_used == pytest.approx(12.5)
    assert probe.reading.balance_remaining == pytest.approx(27.5)
    # The KEY is still uncapped; what changed is that the money behind it is now measured.
    assert probe.reading.is_unbounded is False
    assert [r.url.path for r in seen] == [_KEY_PATH, _CREDITS_PATH]


async def test_the_credits_call_carries_the_management_key_and_never_the_inference_one() -> None:
    # Arrange — the fence that matters most. An inference key sent to a management endpoint
    # is a credential in a log it does not belong in; the reverse is the whole blast radius.
    handler, seen = _ladder(
        key=_uncapped_key(),
        credits=httpx.Response(200, json={"data": {"total_credits": 8.0, "total_usage": 1.0}}),
    )

    # Act
    await _probe_openrouter(handler, management_key=_MANAGEMENT_KEY)

    # Assert
    auth = {r.url.path: r.headers["authorization"] for r in seen}
    assert auth[_KEY_PATH] == f"Bearer {_INFERENCE_KEY}"
    assert auth[_CREDITS_PATH] == f"Bearer {_MANAGEMENT_KEY}"


async def test_a_deployment_holding_no_management_key_asks_nothing_new() -> None:
    # Arrange — the old behaviour is the floor. An unset credential must leave the probe
    # byte-identical to what it was before the endpoint was ever called.
    handler, seen = _ladder(key=_uncapped_key())

    # Act
    probe = await _probe_openrouter(handler)

    # Assert
    assert [r.url.path for r in seen] == [_KEY_PATH]
    assert probe.reading is not None
    assert probe.reading.is_unbounded is True
    assert probe.reading.balance_remaining is None


async def test_a_capped_key_never_spends_the_management_credential() -> None:
    # Arrange — a capped key already carries its own denominator. Asking the account pool to
    # re-learn a number we hold pays the credential's risk for nothing.
    handler, seen = _ladder(
        key=httpx.Response(
            200, json={"data": {"limit": 10.0, "limit_remaining": 4.0, "usage": 6.0}}
        ),
        credits=httpx.Response(200, json={"data": {"total_credits": 99.0, "total_usage": 1.0}}),
    )

    # Act
    probe = await _probe_openrouter(handler, management_key=_MANAGEMENT_KEY)

    # Assert — the key's own allowance, and one request.
    assert [r.url.path for r in seen] == [_KEY_PATH]
    assert probe.reading is not None
    assert probe.reading.balance_total == pytest.approx(10.0)
    assert probe.reading.balance_remaining == pytest.approx(4.0)


@pytest.mark.parametrize(
    "credits_response",
    [
        pytest.param(httpx.Response(401, json={"error": "management key required"}), id="revoked"),
        pytest.param(httpx.Response(500, text="upstream is unwell"), id="vendor outage"),
        pytest.param(httpx.Response(200, text="<html>maintenance</html>"), id="unreadable body"),
        pytest.param(httpx.Response(200, json={"data": None}), id="an empty envelope"),
        pytest.param(
            httpx.Response(200, json={"data": {"credits": 40.0, "usage": 12.5}}),
            id="the fields renamed under us",
        ),
        pytest.param(
            httpx.Response(200, json={"data": {"total_credits": 0.0, "total_usage": 0.0}}),
            # A pool of zero is a body we do not understand, not an emptied account — the
            # same judgement ``_elevenlabs_reading`` makes about ``character_limit: 0``.
            id="a zero pool",
        ),
        pytest.param(
            httpx.Response(200, json={"data": {"total_credits": True, "total_usage": 12.5}}),
            # ``bool`` is an ``int`` in Python. The narrowing that catches it is asserted on
            # the key parser too; here it must also not corrupt an otherwise fine reading.
            id="a value that is not a measurement",
        ),
    ],
)
async def test_a_credits_call_that_fails_leaves_the_key_reading_exactly_as_it_was(
    credits_response: httpx.Response,
) -> None:
    # Arrange — every way the second call can go wrong. None of them may cost the first one.
    handler, _ = _ladder(key=_uncapped_key(), credits=credits_response)

    # Act
    probe = await _probe_openrouter(handler, management_key=_MANAGEMENT_KEY)

    # Assert — a SUCCESSFUL probe reporting the uncapped key, which is what this module
    # shipped before the management key existed. A missing ring, never a missing balance.
    assert probe.is_success is True
    assert probe.reading is not None
    assert probe.reading.is_unbounded is True
    assert probe.reading.balance_total is None
    assert probe.reading.balance_remaining is None
    # The status is the KEY call's. The credits call is not a probe and does not get to
    # relabel one that already answered.
    assert probe.http_status == 200
    assert probe.error_code is None


async def test_an_overspent_pool_reports_zero_remaining_rather_than_a_negative() -> None:
    # Arrange — OpenRouter permits a small overdraft, and a negative balance on a chip reads
    # as a bug rather than as a debt.
    handler, _ = _ladder(
        key=_uncapped_key(),
        credits=httpx.Response(200, json={"data": {"total_credits": 5.0, "total_usage": 6.25}}),
    )

    # Act
    probe = await _probe_openrouter(handler, management_key=_MANAGEMENT_KEY)

    # Assert — clamped at the floor, with both halves still reported as measured.
    assert probe.reading is not None
    assert probe.reading.balance_remaining == pytest.approx(0.0)
    assert probe.reading.balance_used == pytest.approx(6.25)


# ---------------------------------------------------------------------------
# The failure taxonomy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("response", "status", "code"),
    [
        pytest.param(
            httpx.Response(200, text="<html>maintenance</html>"),
            # ``None``, and it is worth stating: ``parse_json_body`` does not put
            # ``http_status`` in the error context the way ``classify_http_failure`` does,
            # so a 200 nobody could read records its status as NULL on the row. Harmless
            # today (``error_code`` carries the diagnosis) but it does mean the row cannot
            # distinguish "we got a 200 we could not parse" from "no response arrived".
            None,
            ErrorCode.UPSTREAM_MALFORMED,
            id="a 200 carrying a non-json body",
        ),
        pytest.param(
            httpx.Response(401, json={"error": "no"}),
            401,
            ErrorCode.CONFIG_INVALID,
            id="a rotated credential, which never self-heals",
        ),
        pytest.param(
            httpx.Response(402, json={"error": "no"}),
            402,
            ErrorCode.QUOTA_EXHAUSTED,
            id="our own balance with the vendor is gone",
        ),
        pytest.param(
            httpx.Response(429, text="slow down"),
            429,
            ErrorCode.RATE_LIMITED,
            id="a transient rate limit",
        ),
        pytest.param(
            httpx.Response(500, text="boom"),
            500,
            ErrorCode.UPSTREAM_5XX,
            id="an outage, which does",
        ),
    ],
)
async def test_every_http_failure_shape_produces_a_probe_that_measured_nothing(
    response: httpx.Response, status: int | None, code: ErrorCode
) -> None:
    # Act
    probe = await _probe_openrouter(_always(response))

    # Assert — NOT ONE of these produces a reading with zeros in it. The distinctions
    # between the codes are what let the panel render a revoked key differently from an
    # outage, which ``health_from_error`` was written to preserve.
    assert probe.reading is None
    assert probe.is_success is False
    assert probe.http_status == status
    assert probe.error_code == code.value
    assert probe.vendor is Vendor.OPENROUTER
    assert probe.balance_unit is BalanceUnit.USD
    assert probe.provider == OPENROUTER_PROBE_NAME


async def test_a_connect_timeout_carries_no_status_and_still_names_its_cause() -> None:
    # Arrange — no response ever arrives, so there is no status to carry. ``None`` there is
    # the honest answer and the row records it.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    # Act
    probe = await _probe_openrouter(handler)

    # Assert
    assert probe.reading is None
    assert probe.http_status is None
    assert probe.error_code == ErrorCode.UPSTREAM_TIMEOUT.value


async def test_an_elevenlabs_failure_is_shaped_the_same_way_with_its_own_unit() -> None:
    # Act
    probe = await _probe_elevenlabs(_always(httpx.Response(401, json={"detail": "bad key"})))

    # Assert — one row covers music, TTS and STT, because ``Vendor.ELEVENLABS`` is the
    # granularity the invoice arrives at and the three adapters draw on one credit pool.
    assert probe.reading is None
    assert probe.vendor is Vendor.ELEVENLABS
    assert probe.is_fallback is False
    assert probe.balance_unit is BalanceUnit.CHARACTERS
    assert probe.provider == ELEVENLABS_PROBE_NAME
    assert probe.error_code == ErrorCode.CONFIG_INVALID.value


async def test_a_successful_elevenlabs_probe_asks_the_path_the_adapter_owns() -> None:
    # Arrange — the path and the auth header are imported from the adapter module rather
    # than re-spelled, so two callers cannot disagree about where the endpoint is.
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("xi-api-key")))
        return httpx.Response(
            200, json={"character_limit": 100_000, "character_count": 25_000, "tier": "creator"}
        )

    # Act
    probe = await _probe_elevenlabs(handler)

    # Assert
    assert seen == [("/v1/user/subscription", "k")]
    assert probe.is_success is True
    assert probe.reading is not None
    assert probe.reading.balance_remaining == pytest.approx(75_000.0)
    assert probe.latency_ms is not None and probe.latency_ms >= 0


async def test_a_probe_that_answered_with_nothing_readable_is_still_a_success() -> None:
    # Arrange / Act — a 200 whose every field has been renamed. This is the degradation the
    # ``Any``-typed models buy: the alternative is a FAILED probe carrying
    # ``UPSTREAM_MALFORMED`` that somebody spends an afternoon chasing.
    probe = await _probe_openrouter(_always(httpx.Response(200, json={"data": {}})))

    # Assert — a success with no quantities on it. The writer then records ``fetched_at``
    # set with every quantity NULL, which is the state the panel renders as "not reported",
    # and is exactly why the schema's balance-carries-its-time CHECK is an implication and
    # not a biconditional.
    assert probe.is_success is True
    assert probe.reading is not None
    assert probe.reading.balance_remaining is None
    assert probe.reading.balance_total is None
    assert probe.reading.is_unbounded is None
    assert probe.error_code is None
