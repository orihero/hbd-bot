"""Gemini TTS, its key pool and the narration fallback (IMAGE_VIDEO_SPEC §5.1, §5.2, §10 M4.2).

Every request goes to an ``httpx.MockTransport``; no socket is opened. The acceptance line
for M4.2: a 429 on key A sends the call to key B and cools A; every key cooled sends it to
ElevenLabs; a key never appears in a log record.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from bayram.contracts import (
    CostSource,
    Err,
    HealthState,
    Language,
    NarrationRequest,
    Ok,
    Vendor,
    VendorOperation,
    VoiceGender,
)
from bayram.errors import (
    ConfigError,
    ErrorCode,
    ProviderRejectedContentError,
    ProviderUnavailableError,
)
from bayram.providers.tts.elevenlabs import DEFAULT_NARRATION_VOICES, ElevenLabsTts
from bayram.providers.tts.fakes import FakeNarrationProvider, silent_wav
from bayram.providers.tts.gemini import (
    API_KEY_HEADER,
    DEFAULT_MODEL,
    GeminiTtsPricing,
    GeminiTtsProvider,
    is_pool_exhausted,
)
from bayram.providers.tts.key_pool import (
    BASE_COOLDOWN_S,
    GeminiKeyPool,
    KeyEvent,
    KeyState,
    MemoryKeyPoolStore,
    key_ref,
)
from bayram.providers.tts.router import NarrationRouter, build_narration_router
from bayram.usage import VendorUsage

from .conftest import audio_response, build_client

KEY_A = "AIzaSy-test-key-alpha-0000000000000000"
KEY_B = "AIzaSy-test-key-bravo-1111111111111111"
KEY_C = "AIzaSy-test-key-charlie-22222222222222"
INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
VOICES = {VoiceGender.FEMALE: "Kore", VoiceGender.MALE: "Puck"}
TIMEOUT_S = 5.0
IDEMPOTENCY_KEY = "media-job-1:tts"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class CollectingSink:
    def __init__(self) -> None:
        self.records: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.records.append(usage)


class Gemini:
    """A scripted Gemini: each request is answered by the next reply for the key it carries."""

    def __init__(self, script: dict[str, list[httpx.Response]]) -> None:
        self._script = {key: list(replies) for key, replies in script.items()}
        self.requests: list[httpx.Request] = []

    @property
    def keys_used(self) -> list[str]:
        return [request.headers[API_KEY_HEADER] for request in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        replies = self._script.get(request.headers.get(API_KEY_HEADER, ""), [])
        if not replies:
            return httpx.Response(500, text="unscripted")
        return replies.pop(0) if len(replies) > 1 else replies[0]


def wav_ok(
    seconds: float = 2.0, *, usage: dict[str, int] | None = None, interaction_id: str = "int-1"
) -> httpx.Response:
    payload: dict[str, Any] = {
        "id": interaction_id,
        "status": "completed",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "audio",
                        "mime_type": "audio/wav",
                        "data": base64.b64encode(silent_wav(seconds)).decode("ascii"),
                    }
                ],
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    return httpx.Response(200, json=payload)


def status(code: int, text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(code, text=text, headers=headers or {})


def rate_limited(retry_after: str | None = None) -> httpx.Response:
    body = '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","message":"quota exceeded"}}'
    return status(429, body, {"retry-after": retry_after} if retry_after else None)


def narration(**overrides: Any) -> NarrationRequest:
    values: dict[str, Any] = {
        "text": "Happy birthday, have a wonderful day!",
        "language": Language.EN,
        "gender": VoiceGender.FEMALE,
        "style": "warm and cheerful",
    }
    values.update(overrides)
    return NarrationRequest(**values)


def build(
    gemini: Gemini,
    *,
    keys: tuple[str, ...] = (KEY_A, KEY_B),
    clock: Clock | None = None,
    sink: CollectingSink | None = None,
    store: Any = None,
    voices: dict[VoiceGender, str] | None = None,
) -> tuple[GeminiTtsProvider, GeminiKeyPool]:
    clock = clock or Clock()
    pool = GeminiKeyPool(keys, store=store or MemoryKeyPoolStore(), clock=clock)
    provider = GeminiTtsProvider(
        pool=pool,
        voices=VOICES if voices is None else voices,
        client=build_client(gemini),
        clock=clock,
        usage=sink or CollectingSink(),
    )
    return provider, pool


async def states(pool: GeminiKeyPool) -> dict[str, KeyState]:
    return {row.key_ref: row.state for row in await pool.snapshot()}


# ---------------------------------------------------------------------------
# The wire shape (the recorded fixture §5.1 asks for)
# ---------------------------------------------------------------------------
async def test_the_request_is_the_documented_interactions_call() -> None:
    gemini = Gemini({KEY_A: [wav_ok()], KEY_B: [wav_ok()]})
    provider, _ = build(gemini)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    request = gemini.requests[0]
    assert str(request.url) == INTERACTIONS_URL
    assert request.method == "POST"
    assert request.headers[API_KEY_HEADER] in (KEY_A, KEY_B)
    assert "key=" not in str(request.url)
    assert json.loads(request.content) == {
        "model": DEFAULT_MODEL,
        "input": [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": "Happy birthday, have a wonderful day!",
                        "annotations": [{"type": "speech_metadata", "style": "warm and cheerful"}],
                    }
                ],
            }
        ],
        "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
        "generation_config": {"speech_config": [{"voice": "Kore"}]},
    }


async def test_the_male_voice_is_used_for_a_male_line_and_no_style_sends_no_annotation() -> None:
    gemini = Gemini({KEY_A: [wav_ok()]})
    provider, _ = build(gemini, keys=(KEY_A,))

    await provider.narrate(
        narration(gender=VoiceGender.MALE, style=None),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    body = json.loads(gemini.requests[0].content)
    assert body["generation_config"]["speech_config"] == [{"voice": "Puck"}]
    assert "annotations" not in body["input"][0]["content"][0]


async def test_uzbek_cyrillic_is_spoken_from_latin() -> None:
    gemini = Gemini({KEY_A: [wav_ok()]})
    provider, _ = build(gemini, keys=(KEY_A,))

    await provider.narrate(
        narration(text="Туғилган кунинг билан!", language=Language.UZ_CYRL),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    text = json.loads(gemini.requests[0].content)["input"][0]["content"][0]["text"]
    assert text.startswith("Tu")
    assert not any("Ѐ" <= character <= "ӿ" for character in text)


async def test_the_wav_comes_back_measured_and_metered_from_vendor_tokens() -> None:
    sink = CollectingSink()
    gemini = Gemini(
        {KEY_A: [wav_ok(2.0, usage={"total_input_tokens": 20, "total_output_tokens": 50})]}
    )
    provider, _ = build(gemini, keys=(KEY_A,), sink=sink)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    audio = result.value
    assert audio.mime == "audio/wav"
    assert audio.duration_s == pytest.approx(2.0)
    assert audio.remote_id == "int-1"
    assert audio.cost_source is CostSource.DERIVED
    assert audio.cost_usd == pytest.approx((20 * 0.5 + 50 * 9.0) / 1_000_000)
    (row,) = sink.records
    assert (row.vendor, row.operation, row.is_success) == (
        Vendor.GEMINI_TTS,
        VendorOperation.SPEECH_SYNTHESIS,
        True,
    )
    assert (row.prompt_tokens, row.completion_tokens, row.audio_ms) == (20, 50, 2000)


async def test_without_vendor_tokens_the_cost_is_estimated_at_25_tokens_a_second() -> None:
    gemini = Gemini({KEY_A: [wav_ok(4.0)]})
    provider, _ = build(gemini, keys=(KEY_A,))

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    assert result.value.cost_source is CostSource.ESTIMATED
    assert result.value.cost_usd == pytest.approx(100 * 9.0 / 1_000_000)


def test_the_price_doubles_on_the_first_of_2027() -> None:
    pricing = GeminiTtsPricing()
    before = pricing.cost_for(input_tokens=0, output_tokens=1_000, on=date(2026, 12, 31))
    after = pricing.cost_for(input_tokens=0, output_tokens=1_000, on=date(2027, 1, 1))

    assert after == pytest.approx(before * 2)


async def test_a_raw_audio_body_is_accepted_too() -> None:
    gemini = Gemini({KEY_A: [audio_response(silent_wav(1.0), content_type="audio/wav")]})
    provider, _ = build(gemini, keys=(KEY_A,))

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    assert result.value.duration_s == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The pool (§5.2)
# ---------------------------------------------------------------------------
async def test_calls_rotate_round_robin_across_the_keys() -> None:
    gemini = Gemini({KEY_A: [wav_ok()], KEY_B: [wav_ok()], KEY_C: [wav_ok()]})
    provider, _ = build(gemini, keys=(KEY_A, KEY_B, KEY_C))

    for _ in range(3):
        await provider.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    assert sorted(gemini.keys_used) == sorted([KEY_A, KEY_B, KEY_C])


async def test_a_429_on_key_a_uses_key_b_and_cools_a() -> None:
    clock = Clock()
    sink = CollectingSink()
    gemini = Gemini({KEY_A: [rate_limited(retry_after="120")], KEY_B: [wav_ok()]})
    # The shared counter starts at 1, so key index 1 % 2 = B first: prime it so A is first.
    store = MemoryKeyPoolStore()
    await store.next_counter()
    provider, pool = build(gemini, clock=clock, sink=sink, store=store)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    assert gemini.keys_used == [KEY_A, KEY_B]
    assert (await states(pool)) == {
        key_ref(KEY_A): KeyState.COOLING,
        key_ref(KEY_B): KeyState.AVAILABLE,
    }
    (row_a,) = [row for row in await pool.snapshot() if row.key_ref == key_ref(KEY_A)]
    assert row_a.cooldown_until == clock.now + timedelta(seconds=120)
    assert row_a.rate_limited_24h == 1
    assert [row.is_success for row in sink.records] == [False, True]
    assert sink.records[0].http_status == 429

    # While A cools, every call goes to B, whatever the counter says.
    await provider.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)
    await provider.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)
    assert gemini.keys_used[2:] == [KEY_B, KEY_B]

    # And once the cooldown passes, A is back in rotation.
    clock.now += timedelta(seconds=121)
    assert (await states(pool))[key_ref(KEY_A)] is KeyState.AVAILABLE


async def test_without_retry_after_the_cooldown_backs_off_exponentially() -> None:
    clock = Clock()
    pool = GeminiKeyPool((KEY_A,), store=MemoryKeyPoolStore(), clock=clock)
    (key,) = pool.keys

    first = await pool.mark_rate_limited(key, retry_after_s=None)
    second = await pool.mark_rate_limited(key, retry_after_s=None)
    for _ in range(10):
        last = await pool.mark_rate_limited(key, retry_after_s=None)

    assert (first, second) == (BASE_COOLDOWN_S, BASE_COOLDOWN_S * 2)
    assert last == 900.0
    await pool.mark_ok(key)
    assert await pool.mark_rate_limited(key, retry_after_s=None) == BASE_COOLDOWN_S


async def test_every_key_cooled_is_a_pool_exhausted_error() -> None:
    gemini = Gemini({KEY_A: [rate_limited()], KEY_B: [rate_limited()]})
    provider, pool = build(gemini)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Err)
    assert is_pool_exhausted(result.error)
    assert set((await states(pool)).values()) == {KeyState.COOLING}
    # A second call does not even reach the vendor.
    before = len(gemini.requests)
    again = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )
    assert isinstance(again, Err) and is_pool_exhausted(again.error)
    assert len(gemini.requests) == before


@pytest.mark.parametrize(
    "reply",
    [
        status(401, '{"error":{"status":"UNAUTHENTICATED"}}'),
        status(403, '{"error":{"status":"PERMISSION_DENIED","message":"suspended"}}'),
        status(400, '{"error":{"status":"INVALID_ARGUMENT","reason":"API_KEY_INVALID"}}'),
    ],
    ids=["401", "403", "invalid-key-400"],
)
async def test_a_rejected_key_is_disabled_for_a_day_and_the_next_key_speaks(
    reply: httpx.Response, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    store = MemoryKeyPoolStore()
    await store.next_counter()
    gemini = Gemini({KEY_A: [reply], KEY_B: [wav_ok()]})
    provider, pool = build(gemini, clock=clock, store=store)

    with caplog.at_level(logging.ERROR):
        result = await provider.narrate(
            narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
        )

    assert isinstance(result, Ok)
    assert gemini.keys_used == [KEY_A, KEY_B]
    (row_a,) = [row for row in await pool.snapshot() if row.key_ref == key_ref(KEY_A)]
    assert row_a.state is KeyState.DISABLED
    assert row_a.disabled_until == clock.now + timedelta(hours=24)
    alerts = [r for r in caplog.records if getattr(r, "alert", None) == "gemini_tts_key_disabled"]
    assert [getattr(r, "key_ref", None) for r in alerts] == [key_ref(KEY_A)]
    clock.now += timedelta(hours=24, seconds=1)
    assert (await states(pool))[key_ref(KEY_A)] is KeyState.AVAILABLE


async def test_a_5xx_tries_the_next_key_once_and_then_fails() -> None:
    gemini = Gemini({KEY_A: [status(503)], KEY_B: [status(500)], KEY_C: [status(502)]})
    provider, _ = build(gemini, keys=(KEY_A, KEY_B, KEY_C))

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Err)
    assert isinstance(result.error, ProviderUnavailableError)
    assert len(gemini.requests) == 2


async def test_a_5xx_then_a_good_key_speaks() -> None:
    store = MemoryKeyPoolStore()
    await store.next_counter()
    gemini = Gemini({KEY_A: [status(502)], KEY_B: [wav_ok()]})
    provider, _ = build(gemini, store=store)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    assert gemini.keys_used == [KEY_A, KEY_B]


@pytest.mark.parametrize(
    "reply",
    [
        status(400, '{"error":{"status":"INVALID_ARGUMENT","message":"blocked: SAFETY"}}'),
        httpx.Response(
            200,
            json={
                "id": "int-9",
                "status": "failed",
                "errors": [{"code": "PROHIBITED_CONTENT", "message": "blocked"}],
            },
        ),
    ],
    ids=["400-safety", "200-failed"],
)
async def test_a_content_refusal_is_final_and_not_a_key_fault(reply: httpx.Response) -> None:
    gemini = Gemini({KEY_A: [reply], KEY_B: [reply]})
    provider, pool = build(gemini)

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Err)
    assert isinstance(result.error, ProviderRejectedContentError)
    assert len(gemini.requests) == 1
    assert set((await states(pool)).values()) == {KeyState.AVAILABLE}


async def test_an_answer_with_no_audio_is_a_malformed_response() -> None:
    gemini = Gemini({KEY_A: [httpx.Response(200, json={"id": "x", "status": "completed"})]})
    provider, _ = build(gemini, keys=(KEY_A,))

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_MALFORMED


async def test_an_unreadable_store_still_narrates() -> None:
    class BrokenStore(MemoryKeyPoolStore):
        async def next_counter(self) -> int:
            raise ConnectionError("redis down")

        async def read_state(self, ref: str) -> dict[str, str]:
            raise ConnectionError("redis down")

    gemini = Gemini({KEY_A: [wav_ok()], KEY_B: [wav_ok()]})
    provider, _ = build(gemini, store=BrokenStore())

    result = await provider.narrate(
        narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)


def test_a_key_is_named_by_its_ref_and_never_rendered() -> None:
    pool = GeminiKeyPool((KEY_A, KEY_A, " ", KEY_B), store=MemoryKeyPoolStore())

    assert pool.refs == (key_ref(KEY_A), key_ref(KEY_B))
    assert len(key_ref(KEY_A)) == 8
    assert KEY_A not in repr(pool)
    assert KEY_A not in repr(pool.keys[0])
    assert KEY_A not in str(pool.keys[0])


async def test_health_counts_successes_per_key() -> None:
    gemini = Gemini({KEY_A: [wav_ok()]})
    provider, pool = build(gemini, keys=(KEY_A,))
    await provider.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    (row,) = await pool.snapshot()
    health = await provider.health()

    assert (row.ok_24h, row.rate_limited_24h, row.last_ok_at is not None) == (1, 0, True)
    assert isinstance(health, Ok) and health.value.state is HealthState.HEALTHY
    assert KEY_A not in (health.value.detail or "")


async def test_the_memory_store_counts_only_the_window() -> None:
    store = MemoryKeyPoolStore()
    now = datetime(2026, 9, 25, tzinfo=UTC)
    await store.record_event("ref", KeyEvent.OK, now - timedelta(hours=25))
    await store.record_event("ref", KeyEvent.OK, now)

    assert await store.count_events("ref", KeyEvent.OK, now - timedelta(hours=24)) == 1


# ---------------------------------------------------------------------------
# Keys never reach a log record (§5.2; the M4.2 caplog assertion)
# ---------------------------------------------------------------------------
async def test_no_key_appears_in_any_log_record(caplog: pytest.LogCaptureFixture) -> None:
    gemini = Gemini(
        {
            KEY_A: [rate_limited(), wav_ok()],
            KEY_B: [status(401, "unauthenticated"), wav_ok()],
            KEY_C: [status(503, "down"), wav_ok()],
        }
    )
    provider, pool = build(gemini, keys=(KEY_A, KEY_B, KEY_C))
    elevenlabs = ElevenLabsTts(
        api_key="el-key",
        base_url="https://api.elevenlabs.io",
        model_id="eleven_v3",
        client=build_client(lambda _: audio_response()),
    )
    router = NarrationRouter(
        {Language.EN: provider}, fallback=elevenlabs, clock=lambda: datetime.now(UTC)
    )

    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            await router.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)
        await pool.snapshot()
        await router.health()

    assert caplog.records, "the run is expected to log (a 429, a 401, a 5xx)"
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__!r}"
        for key in (KEY_A, KEY_B, KEY_C):
            assert key not in rendered, record.getMessage()


# ---------------------------------------------------------------------------
# The narration router: ElevenLabs behind the pool
# ---------------------------------------------------------------------------
def elevenlabs_with(recorded: list[httpx.Request]) -> ElevenLabsTts:
    def reply(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return audio_response()

    return ElevenLabsTts(
        api_key="el-key",
        base_url="https://api.elevenlabs.io",
        model_id="eleven_v3",
        client=build_client(reply),
    )


async def test_every_key_cooled_falls_back_to_elevenlabs_in_the_house_voice() -> None:
    gemini = Gemini({KEY_A: [rate_limited()], KEY_B: [rate_limited()]})
    provider, _ = build(gemini)
    recorded: list[httpx.Request] = []
    built = build_narration_router([provider, elevenlabs_with(recorded)], fallback="elevenlabs_tts")
    assert isinstance(built, Ok)

    result = await built.value.narrate(
        narration(gender=VoiceGender.MALE), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    assert isinstance(result, Ok)
    (request,) = recorded
    assert request.url.path == f"/v1/text-to-speech/{DEFAULT_NARRATION_VOICES[VoiceGender.MALE]}"
    body = json.loads(request.content)
    assert body["text"] == "Happy birthday, have a wonderful day!"
    assert body["language_code"] == "en"


async def test_a_missing_house_voice_falls_back() -> None:
    gemini = Gemini({KEY_A: [wav_ok()]})
    provider, _ = build(gemini, keys=(KEY_A,), voices={})
    recorded: list[httpx.Request] = []
    router = NarrationRouter({Language.EN: provider}, fallback=elevenlabs_with(recorded))

    result = await router.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    assert isinstance(result, Ok)
    assert gemini.requests == []
    assert len(recorded) == 1


async def test_a_content_refusal_is_never_offered_to_the_fallback() -> None:
    refusal = ProviderRejectedContentError("refused", provider="gemini_tts")
    fallback = FakeNarrationProvider(name="elevenlabs_tts")
    router = NarrationRouter(
        {Language.EN: FakeNarrationProvider(name="gemini_tts", error=refusal)}, fallback=fallback
    )

    result = await router.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    assert isinstance(result, Err)
    assert result.error is refusal
    assert fallback.calls == ()


async def test_a_failing_fallback_fails_the_line() -> None:
    down = ProviderUnavailableError("down", provider="x")
    router = NarrationRouter(
        {Language.EN: FakeNarrationProvider(name="gemini_tts", error=down)},
        fallback=FakeNarrationProvider(name="elevenlabs_tts", error=down),
    )

    result = await router.narrate(narration(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    assert isinstance(result, Err)


def test_a_table_naming_an_unknown_provider_refuses() -> None:
    built = build_narration_router(
        [FakeNarrationProvider(name="elevenlabs_tts")], fallback="elevenlabs_tts"
    )

    assert isinstance(built, Err)
    assert isinstance(built.error, ConfigError)
    assert "gemini_tts" in built.error.operator_message


def test_a_narration_is_spoken_by_one_of_the_two_house_voices() -> None:
    with pytest.raises(PydanticValidationError):
        narration(gender=VoiceGender.DUET)
    with pytest.raises(PydanticValidationError):
        narration(text="")
