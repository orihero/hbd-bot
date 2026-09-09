"""What every LLM call reports about itself, and what it refuses to report.

This is the leg where the money goes. Until these records existed, an OpenRouter bill
arrived each month against a system that had counted exactly nothing: no token totals, no
model id on a log line, and two accounts whose adapters both answered to the name
``openai-compat`` and were therefore one undifferentiated number.

Three rules are pinned here over and over because each one is a way the accounting could
quietly become fiction:

* A cost has a provenance or it does not exist. OpenRouter's own ``usage.cost`` is
  VENDOR_REPORTED; our arithmetic over its token counts is DERIVED; an unpriced
  deployment gets ``None`` and ``None``, never ``0.0``.
* A missing measurement is ``None``. A response with no ``usage`` block records no
  tokens — it does not record zero tokens, and it does not raise.
* A failure is still a call. A 429 spends no tokens but it happened, and a vendor whose
  failures vanish from the record looks healthier than it is.
"""

from __future__ import annotations

import json
from typing import Any, Final

import httpx
import pytest
from pydantic import BaseModel, Field

from hbd.config import Settings
from hbd.contracts import CostSource, LlmRequest, Ok, Vendor, VendorOperation
from hbd.errors import ErrorCode
from hbd.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from hbd.providers.llm.fake import FakeLlmProvider
from hbd.providers.llm.gemini import GeminiLlmProvider
from hbd.providers.llm.openai_compat import OpenAiCompatLlmProvider
from hbd.providers.llm.pricing import TokenPricing
from hbd.usage import UsageSink, VendorUsage
from tests.test_providers_llm.conftest import gemini_response, mock_client, openai_response


class Sample(BaseModel):
    name: str = Field(min_length=1)


class Moderation(BaseModel):
    """A shape the fake provider recognises, so its own answer path is the one measured."""

    is_allowed: bool
    reason: str = ""


REQUEST = LlmRequest(system_prompt="be brief", user_prompt="name a person")

ANSWER: Final[str] = '{"name": "Alyona"}'
MODEL_ID: Final[str] = "google/gemma-4-31b-it:free"
FALLBACK_MODEL_ID: Final[str] = "gpt-5.6-luna"
OPENROUTER_BASE_URL: Final[str] = "https://openrouter.ai/api/v1"

#: A rate card that makes the arithmetic legible: a million prompt tokens costs a dollar.
PRICED: Final[TokenPricing] = TokenPricing(
    usd_per_million_prompt=1.0, usd_per_million_completion=2.0
)


class RecordingUsageSink:
    """Collects what the adapter reported. Satisfies ``UsageSink`` structurally."""

    def __init__(self) -> None:
        self.records: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.records.append(usage)

    @property
    def only(self) -> VendorUsage:
        """The single record, asserting that exactly one call was measured."""
        assert len(self.records) == 1, f"expected one usage record, got {len(self.records)}"
        return self.records[0]


def json_responder(payload: dict[str, Any], *, status: int = 200) -> Any:
    """Serve a decoded body. Encoded by hand rather than through httpx's ``json=``.

    ``httpx`` refuses to encode a ``NaN`` and the standard library happily emits one, which
    is the case that matters here: a lax gateway CAN put a bare ``NaN`` in ``usage.cost``,
    ``json.loads`` will read it straight back as a float, and ``_reported_cost`` is what
    stops that becoming a dollar figure on a dashboard.
    """
    body = json.dumps(payload)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "application/json"})

    return handler


def text_responder(body: str, *, status: int) -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return handler


def openrouter(
    handler: Any, *, sink: UsageSink, pricing: TokenPricing | None = None
) -> OpenAiCompatLlmProvider:
    return OpenAiCompatLlmProvider(
        api_key="test-key",
        base_url=OPENROUTER_BASE_URL,
        model_id=MODEL_ID,
        client=mock_client(handler),
        vendor=Vendor.OPENROUTER,
        pricing=pricing,
        usage=sink,
    )


def with_usage(text: str, **usage: Any) -> dict[str, Any]:
    """An OpenAI-shaped body carrying the accounting block OpenRouter returns."""
    return {**openai_response(text), "usage": usage}


# ---------------------------------------------------------------------------
# Cost provenance
# ---------------------------------------------------------------------------
async def test_the_vendors_own_cost_figure_is_recorded_as_vendor_reported() -> None:
    """OpenRouter prices the call itself, and its number outranks any of ours.

    It is the only figure in the system that reconciles line-for-line against an invoice.
    """
    # Arrange
    sink = RecordingUsageSink()
    payload = with_usage(
        ANSWER, prompt_tokens=120, completion_tokens=45, total_tokens=165, cost=0.00042
    )

    # Act
    await openrouter(json_responder(payload), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert — the vendor's figure verbatim, not our rate card's answer for 165 tokens.
    assert sink.only.cost_usd == 0.00042
    assert sink.only.cost_source is CostSource.VENDOR_REPORTED


async def test_a_configured_rate_card_derives_the_cost_when_the_vendor_quotes_none() -> None:
    # Arrange — the same response, minus the one field OpenRouter adds.
    sink = RecordingUsageSink()
    payload = with_usage(ANSWER, prompt_tokens=1_000_000, completion_tokens=1_000_000)

    # Act
    await openrouter(json_responder(payload), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.cost_usd == pytest.approx(3.0)
    assert sink.only.cost_source is CostSource.DERIVED


async def test_an_unpriced_deployment_records_tokens_and_no_cost_whatsoever() -> None:
    """The shipped posture: no rate is configured, so there is no honest dollar figure.

    The tokens are still recorded, because they were genuinely measured — this is the
    difference the panel draws between "not instrumented" and "not priced".
    """
    # Arrange
    sink = RecordingUsageSink()
    payload = with_usage(ANSWER, prompt_tokens=120, completion_tokens=45, total_tokens=165)

    # Act
    await openrouter(json_responder(payload), sink=sink).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert — `is None` on both, never a zero that a SUM() would read as "free".
    assert sink.only.cost_usd is None
    assert sink.only.cost_source is None
    assert sink.only.total_tokens == 165


async def test_a_vendor_reported_zero_is_kept_because_a_free_model_really_costs_nothing() -> None:
    # Arrange — OpenRouter answers 0 for its free tier, and that IS the measurement.
    sink = RecordingUsageSink()
    payload = with_usage(ANSWER, prompt_tokens=10, completion_tokens=5, cost=0)

    # Act
    await openrouter(json_responder(payload), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.cost_usd == 0.0
    assert sink.only.cost_source is CostSource.VENDOR_REPORTED


@pytest.mark.parametrize("cost", ["free", None, True, float("nan"), float("inf"), -1.0])
async def test_a_cost_field_that_is_not_a_real_number_falls_through_to_our_own_pricing(
    cost: Any,
) -> None:
    # Arrange — a gateway that returns junk in `cost` must not poison the ledger.
    sink = RecordingUsageSink()
    payload = with_usage(ANSWER, prompt_tokens=1_000_000, completion_tokens=0, cost=cost)

    # Act
    await openrouter(json_responder(payload), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.cost_usd == pytest.approx(1.0)
    assert sink.only.cost_source is CostSource.DERIVED


# ---------------------------------------------------------------------------
# Absent measurements
# ---------------------------------------------------------------------------
async def test_a_response_with_no_usage_block_records_no_tokens_and_does_not_raise() -> None:
    """An OpenAI-compatible host that answers without accounting is normal, not broken."""
    # Arrange
    sink = RecordingUsageSink()

    # Act
    result = await openrouter(
        json_responder(openai_response(ANSWER)), sink=sink, pricing=PRICED
    ).generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert — the call succeeded and every quantity is absent rather than zero.
    assert isinstance(result, Ok)
    assert sink.only.prompt_tokens is None
    assert sink.only.completion_tokens is None
    assert sink.only.total_tokens is None
    assert sink.only.cost_usd is None


@pytest.mark.parametrize(
    "usage_block",
    [
        {"prompt_tokens": "many"},
        {"prompt_tokens": True},
        {"prompt_tokens": -4},
        {"prompt_tokens": None},
    ],
)
async def test_a_malformed_token_count_is_absent_rather_than_guessed(
    usage_block: dict[str, Any],
) -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await openrouter(
        json_responder({**openai_response(ANSWER), "usage": usage_block}), sink=sink
    ).generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    assert sink.only.prompt_tokens is None


# ---------------------------------------------------------------------------
# Failures are calls too
# ---------------------------------------------------------------------------
async def test_a_rate_limited_call_is_recorded_as_a_failure_with_its_status_and_code() -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await openrouter(text_responder("slow down", status=429), sink=sink).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.is_success is False
    assert sink.only.error_code == ErrorCode.RATE_LIMITED.value
    assert sink.only.http_status == 429
    assert sink.only.cost_usd is None


async def test_a_content_refusal_over_a_200_is_a_failure_that_still_spent_its_tokens() -> None:
    """The tokens were billed whatever the model then declined to write."""
    # Arrange
    sink = RecordingUsageSink()
    payload = {
        **openai_response("", finish_reason="content_filter"),
        "usage": {"prompt_tokens": 90, "completion_tokens": 0},
    }

    # Act
    await openrouter(json_responder(payload), sink=sink).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.is_success is False
    assert sink.only.error_code == ErrorCode.CONTENT_REJECTED.value
    assert sink.only.http_status == 200
    assert sink.only.prompt_tokens == 90


async def test_a_transport_failure_records_a_call_with_no_status_at_all() -> None:
    # Arrange — a timeout has no HTTP status, and inventing one would be a fabrication.
    sink = RecordingUsageSink()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    # Act
    await openrouter(handler, sink=sink).generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    assert sink.only.is_success is False
    assert sink.only.http_status is None
    assert sink.only.error_code == ErrorCode.UPSTREAM_TIMEOUT.value


async def test_exactly_one_record_is_written_per_call() -> None:
    # Arrange
    sink = RecordingUsageSink()
    payload = with_usage(ANSWER, prompt_tokens=10, completion_tokens=5)

    # Act
    await openrouter(json_responder(payload), sink=sink).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert — a double record would double the spend on the panel.
    assert len(sink.records) == 1


# ---------------------------------------------------------------------------
# The request OpenRouter has to be asked
# ---------------------------------------------------------------------------
async def test_openrouter_is_asked_to_include_the_accounting_block() -> None:
    """Without this field OpenRouter returns no usage at all, and the leg is unmeasured."""
    # Arrange
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=openai_response(ANSWER))

    # Act
    await openrouter(handler, sink=RecordingUsageSink()).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert captured["usage"] == {"include": True}


async def test_a_non_openrouter_host_is_never_sent_the_gateway_extension() -> None:
    """A strict OpenAI-compatible host 400s on an unknown top-level key.

    Gated on the vendor rather than on a setting: which hosts understand the field is a
    fact about the hosts, and a deployment must not have to learn to switch telemetry off
    before its gateway will answer at all.
    """
    # Arrange
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=openai_response(ANSWER))

    subject = OpenAiCompatLlmProvider(
        api_key="k",
        base_url="https://gateway.internal",
        model_id=FALLBACK_MODEL_ID,
        client=mock_client(handler),
        usage=RecordingUsageSink(),
    )

    # Act
    await subject.generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    assert "usage" not in captured


# ---------------------------------------------------------------------------
# Telling the two accounts apart
# ---------------------------------------------------------------------------
async def test_the_primary_and_the_fallback_are_distinguishable_on_the_record() -> None:
    """The adapter NAME cannot tell them apart, and that is why the flag exists.

    Both instances answer to ``openai-compat`` because that is the wire dialect they
    speak. ``is_fallback`` and ``model_id`` are what let an operator ask what the failover
    account is costing.
    """
    # Arrange
    sink = RecordingUsageSink()
    handler = json_responder(with_usage(ANSWER, prompt_tokens=10, completion_tokens=5))
    primary = openrouter(handler, sink=sink)
    fallback = OpenAiCompatLlmProvider(
        api_key="k",
        base_url=OPENROUTER_BASE_URL,
        model_id=FALLBACK_MODEL_ID,
        client=mock_client(handler),
        vendor=Vendor.OPENROUTER,
        is_fallback=True,
        usage=sink,
    )

    # Act
    await primary.generate_json(REQUEST, Sample, timeout_s=5.0)
    await fallback.generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    first, second = sink.records
    assert first.provider == second.provider == "openai-compat"
    assert (first.is_fallback, first.model_id) == (False, MODEL_ID)
    assert (second.is_fallback, second.model_id) == (True, FALLBACK_MODEL_ID)


async def test_a_chat_completion_records_the_vendor_the_operation_and_a_latency() -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await openrouter(json_responder(openai_response(ANSWER)), sink=sink).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.vendor is Vendor.OPENROUTER
    assert sink.only.operation is VendorOperation.CHAT_COMPLETION
    assert sink.only.latency_ms is not None
    assert sink.only.latency_ms >= 0
    assert sink.only.is_fake is False


# ---------------------------------------------------------------------------
# Health probes
# ---------------------------------------------------------------------------
async def test_a_health_probe_is_recorded_and_is_never_priced() -> None:
    """A quota probe is a real call with a real status, and never spend."""
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await openrouter(json_responder({"data": []}), sink=sink, pricing=PRICED).health()

    # Assert
    assert sink.only.operation is VendorOperation.HEALTH
    assert sink.only.is_success is True
    assert sink.only.cost_usd is None
    assert sink.only.cost_source is None


async def test_a_failing_health_probe_is_recorded_as_a_failure() -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await openrouter(text_responder("slow down", status=429), sink=sink).health()

    # Assert — dropping it would make a vendor that is down look healthier than it is.
    assert sink.only.operation is VendorOperation.HEALTH
    assert sink.only.is_success is False
    assert sink.only.http_status == 429


# ---------------------------------------------------------------------------
# Gemini reads a different accounting block
# ---------------------------------------------------------------------------
def gemini(
    handler: Any, *, sink: UsageSink, pricing: TokenPricing | None = None
) -> GeminiLlmProvider:
    return GeminiLlmProvider(
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-3.7-flash",
        client=mock_client(handler),
        pricing=pricing,
        usage=sink,
    )


async def test_gemini_records_its_own_usage_metadata_field_names() -> None:
    # Arrange
    sink = RecordingUsageSink()
    payload = {
        **gemini_response(ANSWER),
        "usageMetadata": {
            "promptTokenCount": 200,
            "candidatesTokenCount": 80,
            "totalTokenCount": 280,
        },
    }

    # Act
    await gemini(json_responder(payload), sink=sink).generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    assert sink.only.vendor is Vendor.GEMINI
    assert (sink.only.prompt_tokens, sink.only.completion_tokens) == (200, 80)
    assert sink.only.total_tokens == 280


async def test_gemini_has_no_vendor_reported_cost_so_a_priced_call_is_derived() -> None:
    # Arrange — Gemini quotes token counts and never a price.
    sink = RecordingUsageSink()
    payload = {
        **gemini_response(ANSWER),
        "usageMetadata": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 0},
    }

    # Act
    await gemini(json_responder(payload), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.cost_usd == pytest.approx(1.0)
    assert sink.only.cost_source is CostSource.DERIVED


async def test_gemini_without_usage_metadata_records_nothing_it_did_not_measure() -> None:
    # Arrange
    sink = RecordingUsageSink()

    # Act
    await gemini(json_responder(gemini_response(ANSWER)), sink=sink, pricing=PRICED).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    # Assert
    assert sink.only.prompt_tokens is None
    assert sink.only.cost_usd is None
    assert sink.only.cost_source is None


# ---------------------------------------------------------------------------
# The fake is recorded, not skipped
# ---------------------------------------------------------------------------
async def test_a_fake_call_is_recorded_and_visibly_excluded_from_spend() -> None:
    """A demo that wrote no rows would look exactly like a deployment nobody measured."""
    # Arrange
    sink = RecordingUsageSink()

    # Act
    result = await FakeLlmProvider(usage=sink).generate_json(REQUEST, Moderation, timeout_s=5.0)

    # Assert — no model answered and no request was sent, so both stay absent.
    assert isinstance(result, Ok)
    assert sink.only.vendor is Vendor.FAKE
    assert sink.only.is_fake is True
    assert sink.only.is_success is True
    assert sink.only.cost_usd is None
    assert sink.only.http_status is None
    assert sink.only.model_id is None


# ---------------------------------------------------------------------------
# Who the factory says is billed
# ---------------------------------------------------------------------------
def test_the_shipped_base_url_is_recognised_as_an_openrouter_bill(settings: Settings) -> None:
    """The adapter is chosen by the setting; the INVOICE is read off the host.

    ``HBD_LLM_PROVIDER=openai`` pointed at openrouter.ai is an OpenRouter bill however the
    wire format is spelled, and the host is the only fact in the configuration that knows.
    """
    # Arrange / Act
    provider = build_llm_provider(settings)

    # Assert
    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert provider._vendor is Vendor.OPENROUTER


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://openrouter.ai/api/v1", Vendor.OPENROUTER),
        ("https://OpenRouter.ai/api", Vendor.OPENROUTER),
        ("https://eu.openrouter.ai/api/v1", Vendor.OPENROUTER),
        ("openrouter.ai/api/v1", Vendor.OPENROUTER),
        ("https://api.openai.com", Vendor.OPENAI_COMPATIBLE),
        ("https://gateway.internal:8080/v1", Vendor.OPENAI_COMPATIBLE),
        ("https://notopenrouter.ai/api", Vendor.OPENAI_COMPATIBLE),
    ],
)
def test_the_billing_identity_follows_the_configured_host(
    base_url: str, expected: Vendor, settings: Settings
) -> None:
    # Arrange
    configured = settings.model_copy(update={"llm_base_url": base_url})

    # Act
    provider = build_llm_provider(configured)

    # Assert — a lookalike domain is NOT OpenRouter; suffix matching is on a dot boundary.
    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert provider._vendor is expected


def test_the_primary_and_fallback_rate_cards_do_not_leak_into_each_other(
    settings: Settings,
) -> None:
    """Two accounts, two rate cards. Sharing one would misprice whichever model is cheaper."""
    # Arrange
    configured = settings.model_copy(
        update={
            "llm_usd_per_million_prompt_tokens": 1.0,
            "llm_usd_per_million_completion_tokens": 2.0,
            "llm_fallback_api_key": "fallback-key",
            "llm_fallback_usd_per_million_prompt_tokens": 30.0,
            "llm_fallback_usd_per_million_completion_tokens": 60.0,
        }
    )

    # Act
    primary = build_llm_provider(configured)
    fallback = build_fallback_llm_provider(configured)

    # Assert
    assert isinstance(primary, OpenAiCompatLlmProvider)
    assert isinstance(fallback, OpenAiCompatLlmProvider)
    assert primary._pricing == TokenPricing(
        usd_per_million_prompt=1.0, usd_per_million_completion=2.0
    )
    assert fallback._pricing == TokenPricing(
        usd_per_million_prompt=30.0, usd_per_million_completion=60.0
    )
    assert primary._is_fallback is False
    assert fallback._is_fallback is True


def test_an_unconfigured_deployment_builds_an_unpriced_rate_card(settings: Settings) -> None:
    # Arrange / Act — nothing ships set, so out of the box every LLM row is cost NULL and
    # the panel says "not priced" rather than "$0.00".
    provider = build_llm_provider(settings)

    # Assert
    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert provider._pricing.is_priced is False
