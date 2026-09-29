"""The Higgsfield adapter against IMAGE_VIDEO_SPEC §4.3 and §10 M6.1. No socket is opened.

Every call goes through an ``httpx.MockTransport``. The M6.1 acceptance list, each below:
an ambiguous POST is never repeated; a 400 about concurrency is rate-limited; 402 and 403 are
quota; ``sound:"off"`` (or ``generate_audio:false``) is always sent. Beside them: the key goes
to the API host only, the estimate comes before any upload or POST and the ceiling refuses
without either, ``nsfw`` is a content refusal, and the webhook yields an id and nothing else.
Geometry normalisation is the stage chain's (``tests/test_runtime/test_media_paid_backend.py``
and ``tests/test_media/test_mux.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest

from bayram.config import Settings
from bayram.contracts import HealthState, is_err, is_ok
from bayram.db.enums import MediaAttemptStatus, MediaBackend
from bayram.errors import (
    ErrorCode,
    ProviderAmbiguousError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
)
from bayram.media.contracts import (
    ATTEMPT_STATUS_FOR_PHASE,
    JobHandle,
    JobPhase,
    MediaGenProvider,
    is_ambiguous,
    is_pre_submit,
    max_references,
)
from bayram.providers.media.factory import build_media_provider, higgsfield_submit_ceilings
from bayram.providers.media.higgsfield import (
    AUTH_HEADER,
    HIGGSFIELD_MODELS,
    WEBHOOK_QUERY_PARAM,
    HiggsfieldProvider,
    aspect_ratio_of,
    build_payload,
    webhook_request_id,
)
from tests.test_media.conftest import image_request, jpeg_file, video_request

BASE_URL = "https://platform.example.test"
UPLOAD_URL = "https://uploads.example.test/signed/abc?sig=1"
PUBLIC_URL = "https://cdn.example.test/in/abc.jpg"
RESULT_URL = "https://cdn.example.test/out/clip.mp4"
KEY_ID = "test-key-id"
SECRET = "test-secret-not-real"
KLING_T2V = "/kling-video/v3.0/std/text-to-video"
KLING_I2V = "/kling-video/v3.0/std/image-to-video"

Handler = Callable[[httpx.Request], httpx.Response]


def _kling(**overrides: Any) -> Any:
    return video_request(**{"model_key": "kling3_0_std", **overrides})


def _soul(**overrides: Any) -> Any:
    return image_request(**{"model_key": "soul_standard", **overrides})


def _handle(remote_id: str = "req-1", kind: Any = "video") -> JobHandle:
    return JobHandle(
        provider="higgsfield", remote_id=remote_id, kind=kind, model_key="kling3_0_std"
    )


class Vendor:
    """A scripted Higgsfield: answers by path, records every request in order."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.estimate = httpx.Response(200, json={"cost_usd": 0.56})
        self.submit: httpx.Response | Exception = httpx.Response(
            200, json={"request_id": "req-1", "status": "queued"}
        )
        self.status = httpx.Response(200, json={"status": "queued", "request_id": "req-1"})
        self.result = httpx.Response(
            200, content=b"\x00\x00\x00\x18ftypmp42", headers={"content-type": "video/mp4"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path.startswith("/estimate/"):
            return self.estimate
        if path == "/files/generate-upload-url":
            return httpx.Response(200, json={"upload_url": UPLOAD_URL, "public_url": PUBLIC_URL})
        if request.url.host == "uploads.example.test":
            return httpx.Response(200)
        if path.endswith("/status"):
            return self.status
        if path.endswith("/cancel"):
            return httpx.Response(202)
        if request.url.host == "cdn.example.test":
            return self.result
        if isinstance(self.submit, Exception):
            raise self.submit
        return self.submit

    def posts_to(self, path: str) -> list[httpx.Request]:
        return [r for r in self.seen if r.method == "POST" and r.url.path == path]


def _provider(vendor: Handler, **overrides: Any) -> HiggsfieldProvider:
    values: dict[str, Any] = {
        "key_id": KEY_ID,
        "secret": SECRET,
        "base_url": BASE_URL,
        "max_submit_cost_usd": {"image": 0.10, "video": 1.00},
        "client": httpx.AsyncClient(transport=httpx.MockTransport(vendor)),
    }
    values.update(overrides)
    return HiggsfieldProvider(**values)


async def _submit(provider: HiggsfieldProvider, req: Any, **kwargs: Any) -> Any:
    values: dict[str, Any] = {"correlation_key": "media:j:0:1", "webhook_url": None, "timeout_s": 5}
    values.update(kwargs)
    return await provider.submit(req, **values)


# ---------------------------------------------------------------------------
# The payload: closed keys, silent always, sold aspects only
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model_key", [key for key, model in HIGGSFIELD_MODELS.items() if model.kind == "video"]
)
def test_every_video_model_is_asked_for_silence(model_key: str) -> None:
    built = build_payload(video_request(model_key=model_key), image_urls=())

    assert is_ok(built)
    payload = built.value
    assert payload.get("sound") == "off" or payload.get("generate_audio") is False
    assert payload["duration"] == 5  # 81 frames at 16 fps
    assert payload["aspect_ratio"] == "9:16"


def test_the_payload_is_built_from_a_closed_set_of_keys(tmp_path: Path) -> None:
    video = build_payload(_kling(refs=(jpeg_file(tmp_path),)), image_urls=(PUBLIC_URL,))
    image = build_payload(_soul(), image_urls=())

    assert is_ok(video) and is_ok(image)
    assert set(video.value) <= {"prompt", "aspect_ratio", "duration", "sound", "image_url"}
    assert set(image.value) == {"prompt", "aspect_ratio", "seed"}


def test_an_image_url_goes_only_with_a_reference_and_to_the_models_field(tmp_path: Path) -> None:
    ref = jpeg_file(tmp_path)

    with_ref = build_payload(_kling(refs=(ref,)), image_urls=(PUBLIC_URL,))
    stray = build_payload(_kling(), image_urls=(PUBLIC_URL,))

    assert is_ok(with_ref) and with_ref.value["image_url"] == PUBLIC_URL
    assert is_err(stray) and is_pre_submit(stray.error)


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"model_key": "veo3"}, "allowlist"),
        ({"model_key": "soul_standard"}, "kind"),
        ({"prompt": "  "}, "empty"),
        ({"width": 1000, "height": 700}, "aspect"),
    ],
)
def test_a_request_the_adapter_cannot_send_is_refused_pre_submit(
    overrides: dict[str, Any], why: str
) -> None:
    built = build_payload(_kling(**overrides), image_urls=())

    assert is_err(built) and is_pre_submit(built.error), why


def test_a_text_only_image_model_refuses_a_reference(tmp_path: Path) -> None:
    built = build_payload(_soul(refs=(jpeg_file(tmp_path),)), image_urls=(PUBLIC_URL,))

    assert is_err(built) and is_pre_submit(built.error)


@pytest.mark.parametrize(
    ("size", "aspect"),
    [((720, 1280), "9:16"), ((768, 1344), "9:16"), ((1024, 1024), "1:1"), ((1344, 768), "16:9")],
)
def test_every_sold_size_maps_to_its_aspect(size: tuple[int, int], aspect: str) -> None:
    assert aspect_ratio_of(*size) == aspect


# ---------------------------------------------------------------------------
# Submit: estimate first, ceiling, upload, one POST
# ---------------------------------------------------------------------------
async def test_a_submit_estimates_then_uploads_then_posts_once(tmp_path: Path) -> None:
    vendor = Vendor()
    provider = _provider(vendor)

    result = await _submit(provider, _kling(refs=(jpeg_file(tmp_path),)))

    assert is_ok(result) and result.value.remote_id == "req-1"
    order = [(r.method, r.url.host, r.url.path) for r in vendor.seen]
    assert order == [
        ("POST", "platform.example.test", f"/estimate{KLING_I2V}"),
        ("POST", "platform.example.test", "/files/generate-upload-url"),
        ("PUT", "uploads.example.test", "/signed/abc"),
        ("POST", "platform.example.test", KLING_I2V),
    ]
    # The estimate is asked without the photo; the submit carries the uploaded URL.
    assert "image_url" not in orjson.loads(vendor.seen[0].content)
    posted = orjson.loads(vendor.seen[-1].content)
    assert posted["image_url"] == PUBLIC_URL and posted["sound"] == "off"


# ---------------------------------------------------------------------------
# Several references, natively (§4.4, O6, M6.2)
# ---------------------------------------------------------------------------
SEEDANCE_R2V = "/bytedance/seedance/v2.0/reference-to-video"


def _r2v(**overrides: Any) -> Any:
    return video_request(**{"model_key": "seedance_2_0_r2v", **overrides})


def _refs(directory: Path, count: int) -> tuple[Path, ...]:
    return tuple(jpeg_file(directory, f"ref-{index}.jpg") for index in range(count))


def test_capabilities_report_the_configured_models_reference_limits() -> None:
    kling = _provider(Vendor()).capabilities()
    r2v = _provider(Vendor(), health_model="seedance_2_0_r2v").capabilities()

    # Kling I2V takes one photo (collage first); Soul none; Seedance R2V several.
    assert (max_references(kling, "video"), max_references(kling, "image")) == (1, 0)
    assert max_references(r2v, "video") == HIGGSFIELD_MODELS["seedance_2_0_r2v"].max_refs > 1
    assert r2v.max_reference_images == max_references(r2v, "video")


def test_a_multi_ref_model_gets_every_url_as_a_list(tmp_path: Path) -> None:
    urls = tuple(f"https://cdn.example.test/in/{index}.jpg" for index in range(3))

    built = build_payload(_r2v(refs=_refs(tmp_path, 3)), image_urls=urls)

    assert is_ok(built)
    assert built.value["image_urls"] == list(urls)
    assert built.value["generate_audio"] is False
    assert "image_url" not in built.value


def test_a_one_ref_model_refuses_several_references_pre_submit(tmp_path: Path) -> None:
    refs = _refs(tmp_path, 2)

    built = build_payload(_kling(refs=refs), image_urls=(PUBLIC_URL, PUBLIC_URL))

    assert is_err(built) and is_pre_submit(built.error)


def test_urls_that_do_not_match_the_references_are_refused(tmp_path: Path) -> None:
    built = build_payload(_r2v(refs=_refs(tmp_path, 3)), image_urls=(PUBLIC_URL,))

    assert is_err(built) and is_pre_submit(built.error)


async def test_a_multi_ref_submit_uploads_each_photo_then_posts_once(tmp_path: Path) -> None:
    vendor = Vendor()
    provider = _provider(vendor, health_model="seedance_2_0_r2v")

    result = await _submit(provider, _r2v(refs=_refs(tmp_path, 3)))

    assert is_ok(result)
    assert len(vendor.posts_to("/files/generate-upload-url")) == 3
    assert len([r for r in vendor.seen if r.method == "PUT"]) == 3
    assert len(vendor.posts_to(SEEDANCE_R2V)) == 1
    assert "image_urls" not in orjson.loads(vendor.posts_to(f"/estimate{SEEDANCE_R2V}")[0].content)
    posted = orjson.loads(vendor.posts_to(SEEDANCE_R2V)[0].content)
    assert posted["image_urls"] == [PUBLIC_URL] * 3 and posted["generate_audio"] is False


async def test_the_key_goes_to_the_api_host_and_nowhere_else(tmp_path: Path) -> None:
    vendor = Vendor()
    provider = _provider(vendor)

    await _submit(provider, _kling(refs=(jpeg_file(tmp_path),)))
    await provider.fetch(_handle(), 0, tmp_path / "out.mp4", max_bytes=1 << 20, timeout_s=5)
    vendor.status = httpx.Response(200, json={"status": "completed", "video": {"url": RESULT_URL}})
    await provider.fetch(_handle(), 0, tmp_path / "out.mp4", max_bytes=1 << 20, timeout_s=5)

    for request in vendor.seen:
        if request.url.host == "platform.example.test":
            assert request.headers[AUTH_HEADER] == f"Key {KEY_ID}:{SECRET}"
        else:
            assert AUTH_HEADER not in request.headers, request.url.host
        assert SECRET not in str(request.url)
    assert {r.url.host for r in vendor.seen} >= {"uploads.example.test", "cdn.example.test"}


async def test_an_estimate_above_the_ceiling_uploads_and_posts_nothing(tmp_path: Path) -> None:
    vendor = Vendor()
    vendor.estimate = httpx.Response(200, json={"cost_usd": 1.20})
    provider = _provider(vendor)

    result = await _submit(provider, _kling(refs=(jpeg_file(tmp_path),)))

    assert is_err(result) and is_pre_submit(result.error)
    assert [r.url.path for r in vendor.seen] == [f"/estimate{KLING_I2V}"]


async def test_an_estimate_in_credits_is_converted_or_refused() -> None:
    vendor = Vendor()
    vendor.estimate = httpx.Response(200, json={"credits": 12})

    converted = await _provider(vendor, usd_per_credit=0.0625).estimate_cost(_kling())
    unknown = await _submit(_provider(vendor), _kling())

    assert is_ok(converted) and converted.value.usd == pytest.approx(0.75)
    assert converted.value.basis == "exact"
    # No rate: the cost is unknown, never zero — and nothing is posted.
    assert is_err(unknown) and is_pre_submit(unknown.error)
    assert vendor.posts_to(KLING_T2V) == []


async def test_a_failed_estimate_refuses_the_submit() -> None:
    vendor = Vendor()
    vendor.estimate = httpx.Response(503)

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result) and is_pre_submit(result.error)
    assert vendor.posts_to(KLING_T2V) == []


async def test_a_kind_with_no_ceiling_is_refused() -> None:
    vendor = Vendor()

    result = await _submit(_provider(vendor, max_submit_cost_usd={"video": 1.0}), _soul())

    assert is_err(result) and is_pre_submit(result.error)
    assert vendor.seen == []


async def test_the_webhook_rides_the_submit_as_hf_webhook() -> None:
    vendor = Vendor()

    await _submit(_provider(vendor), _kling(), webhook_url="https://hooks.example.test/hf")
    plain_http = await _submit(_provider(vendor), _kling(), webhook_url="http://hooks.example.test")

    (posted,) = vendor.posts_to(KLING_T2V)
    assert posted.url.params[WEBHOOK_QUERY_PARAM] == "https://hooks.example.test/hf"
    assert is_err(plain_http) and is_pre_submit(plain_http.error)


# ---------------------------------------------------------------------------
# §10 M6.1: an ambiguous POST is never repeated
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "answer",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.RemoteProtocolError("connection dropped mid-response"),
        httpx.Response(500),
        httpx.Response(502, json={"detail": "bad gateway"}),
        httpx.Response(200, json={"status": "queued"}),  # no request_id
        httpx.Response(200, content=b"not json"),
    ],
)
async def test_an_ambiguous_submit_is_posted_once_and_never_repeated(
    answer: httpx.Response | Exception,
) -> None:
    vendor = Vendor()
    vendor.submit = answer

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result)
    assert isinstance(result.error, ProviderAmbiguousError) and is_ambiguous(result.error)
    assert not is_pre_submit(result.error)
    assert result.error.is_retryable is False
    assert len(vendor.posts_to(KLING_T2V)) == 1


async def test_a_submit_that_never_left_is_pre_submit() -> None:
    vendor = Vendor()
    vendor.submit = httpx.ConnectError("refused")

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result) and is_pre_submit(result.error) and not is_ambiguous(result.error)


# ---------------------------------------------------------------------------
# §10 M6.1: status codes
# ---------------------------------------------------------------------------
async def test_a_400_about_concurrency_is_rate_limited_pre_submit() -> None:
    vendor = Vendor()
    vendor.submit = httpx.Response(
        400, json={"detail": "Concurrent request limit reached for your plan"}
    )

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result)
    assert isinstance(result.error, ProviderRateLimitedError)
    assert result.error.error_code is ErrorCode.RATE_LIMITED and is_pre_submit(result.error)


async def test_any_other_400_is_a_refusal_not_a_rate_limit() -> None:
    vendor = Vendor()
    vendor.submit = httpx.Response(400, json={"detail": "prompt is too long"})

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result) and not isinstance(result.error, ProviderRateLimitedError)
    assert result.error.error_code is ErrorCode.INVALID_INPUT and is_pre_submit(result.error)


@pytest.mark.parametrize("status", [402, 403])
async def test_402_and_403_are_the_balance_being_gone(status: int) -> None:
    vendor = Vendor()
    vendor.submit = httpx.Response(status, json={"detail": "Not enough credits"})

    result = await _submit(_provider(vendor), _kling())

    assert is_err(result)
    assert isinstance(result.error, ProviderQuotaExhaustedError)
    assert result.error.error_code is ErrorCode.QUOTA_EXHAUSTED
    assert result.error.is_retryable is False and is_pre_submit(result.error)


async def test_quota_on_the_estimate_is_quota_too() -> None:
    vendor = Vendor()
    vendor.estimate = httpx.Response(403)

    estimated = await _provider(vendor).estimate_cost(_kling())

    assert is_err(estimated) and isinstance(estimated.error, ProviderQuotaExhaustedError)


# ---------------------------------------------------------------------------
# Poll: our vocabulary, nsfw is a content refusal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("queued", JobPhase.QUEUED),
        ("in_progress", JobPhase.RUNNING),
        ("failed", JobPhase.FAILED),
        ("canceled", JobPhase.FAILED),
        ("nsfw", JobPhase.REJECTED_CONTENT),
    ],
)
async def test_every_vendor_status_maps_to_our_phase(status: str, phase: JobPhase) -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(200, json={"status": status, "request_id": "req-1"})

    polled = await _provider(vendor).poll(_handle(), timeout_s=5)

    assert is_ok(polled) and polled.value.phase is phase
    (read,) = vendor.seen
    assert read.method == "GET" and read.url.path == "/requests/req-1/status"


async def test_nsfw_is_a_rejected_attempt_that_is_never_retried() -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(200, json={"status": "nsfw"})

    polled = await _provider(vendor).poll(_handle(), timeout_s=5)

    assert is_ok(polled)
    assert ATTEMPT_STATUS_FOR_PHASE[polled.value.phase] is MediaAttemptStatus.REJECTED


async def test_a_completed_request_counts_its_outputs() -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(
        200, json={"status": "completed", "images": [{"url": RESULT_URL}, {"url": RESULT_URL}]}
    )

    polled = await _provider(vendor).poll(_handle(kind="image"), timeout_s=5)

    assert is_ok(polled)
    assert polled.value.phase is JobPhase.SUCCEEDED and polled.value.output_count == 2


async def test_a_request_id_the_vendor_does_not_know_is_unknown() -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(404)

    polled = await _provider(vendor).poll(_handle(), timeout_s=5)

    assert is_ok(polled) and polled.value.phase is JobPhase.UNKNOWN


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"status": "melting"}),
        httpx.Response(200, json={"status": "completed"}),  # completed with nothing to fetch
        httpx.Response(503),
    ],
)
async def test_a_status_we_cannot_read_is_an_err_the_poll_chain_retries(
    answer: httpx.Response,
) -> None:
    vendor = Vendor()
    vendor.status = answer

    polled = await _provider(vendor).poll(_handle(), timeout_s=5)

    assert is_err(polled) and polled.error.is_retryable


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
async def test_fetch_reads_the_url_from_the_status_and_streams_it(tmp_path: Path) -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(200, json={"status": "completed", "video": {"url": RESULT_URL}})
    dest = tmp_path / "raw.mp4"

    fetched = await _provider(vendor).fetch(_handle(), 0, dest, max_bytes=1 << 20, timeout_s=5)

    assert is_ok(fetched)
    assert fetched.value.mime == "video/mp4" and dest.read_bytes().startswith(b"\x00\x00\x00\x18")
    assert [r.url.host for r in vendor.seen] == ["platform.example.test", "cdn.example.test"]


async def test_fetch_refuses_past_the_size_limit_and_leaves_nothing(tmp_path: Path) -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(200, json={"status": "completed", "video": {"url": RESULT_URL}})
    dest = tmp_path / "raw.mp4"

    fetched = await _provider(vendor).fetch(_handle(), 0, dest, max_bytes=4, timeout_s=5)

    assert is_err(fetched)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed", "video": {"url": "http://cdn.example.test/out/clip.mp4"}},
        {"status": "in_progress"},
        {"status": "completed", "images": [{"url": RESULT_URL}]},  # index 1 of one
    ],
)
async def test_fetch_refuses_what_it_should_not_download(
    tmp_path: Path, body: dict[str, Any]
) -> None:
    vendor = Vendor()
    vendor.status = httpx.Response(200, json=body)
    index = 1 if "images" in body else 0

    fetched = await _provider(vendor).fetch(
        _handle(), index, tmp_path / "raw", max_bytes=1 << 20, timeout_s=5
    )

    assert is_err(fetched)
    assert all(r.url.host == "platform.example.test" for r in vendor.seen)


# ---------------------------------------------------------------------------
# The webhook is a doorbell; cancel; health; the protocol; the factory
# ---------------------------------------------------------------------------
def test_a_webhook_yields_its_request_id_and_nothing_else() -> None:
    forged = orjson.dumps(
        {"request_id": "req-9", "status": "completed", "video": {"url": "https://evil.test/x.mp4"}}
    )

    assert webhook_request_id(forged) == "req-9"
    assert webhook_request_id(b"not json") is None
    assert webhook_request_id(b"[1, 2]") is None
    assert webhook_request_id(orjson.dumps({"request_id": "x" * 200})) is None


async def test_cancel_works_while_queued_and_says_no_once_running() -> None:
    vendor = Vendor()
    queued = await _provider(vendor).cancel(_handle())
    running = await _provider(lambda request: httpx.Response(400)).cancel(_handle())

    assert is_ok(queued) and queued.value is True
    assert is_ok(running) and running.value is False


async def test_health_is_a_free_estimate_and_a_refused_key_is_an_err() -> None:
    vendor = Vendor()
    healthy = await _provider(vendor).health()
    vendor.estimate = httpx.Response(401)
    refused = await _provider(vendor).health()
    no_keys = await _provider(vendor, secret="").health()

    assert is_ok(healthy) and healthy.value.state is HealthState.HEALTHY
    assert all(r.url.path.startswith("/estimate/") for r in vendor.seen)
    assert is_err(refused)
    assert is_ok(no_keys) and no_keys.value.state is HealthState.UNAVAILABLE


def test_the_adapter_satisfies_the_protocol_and_is_honest_about_itself() -> None:
    provider = _provider(Vendor())
    caps = provider.capabilities()

    assert isinstance(provider, MediaGenProvider)
    assert caps.idempotent_submit is False and caps.provider_moderation is True
    assert caps.cancel == "queued_only" and caps.estimate == "exact"


def test_the_factory_builds_it_with_the_per_submit_share_of_each_ceiling(
    settings: Settings,
) -> None:
    live = settings.model_copy(
        update={
            "use_fake_providers": False,
            "image_max_cost_usd": 0.20,
            "video_fast_max_cost_usd": 1.00,
        }
    )

    provider = build_media_provider(live, MediaBackend.HIGGSFIELD)

    assert isinstance(provider, HiggsfieldProvider)
    # Two images share the image ceiling; one clip has the video ceiling to itself.
    assert higgsfield_submit_ceilings(live) == {"image": 0.10, "video": 1.00}


async def test_the_secret_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    vendor = Vendor()
    caplog.set_level(logging.DEBUG)

    await _submit(_provider(vendor), _kling())
    vendor.submit = httpx.Response(500)
    await _submit(_provider(vendor), _kling())

    assert SECRET not in caplog.text
