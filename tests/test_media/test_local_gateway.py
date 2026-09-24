"""The local gateway adapter against every trap in IMAGE_VIDEO_SPEC §4.2. No socket is opened."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import orjson
import pytest

from bayram.contracts import HealthState, is_err, is_ok
from bayram.db.enums import MediaAttemptStatus
from bayram.errors import (
    ErrorCode,
    ProviderAmbiguousError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)
from bayram.media.contracts import (
    ATTEMPT_STATUS_FOR_PHASE,
    JobHandle,
    JobPhase,
    MediaGenProvider,
    is_ambiguous,
    is_pre_submit,
)
from bayram.providers.media.local_gateway import (
    API_KEY_HEADER,
    CLIENT_TAG,
    LOCAL_MODEL_ALLOWLIST,
    LocalGatewayProvider,
    build_generate_payload,
)
from tests.test_media.conftest import image_request, jpeg_file, video_request

BASE_URL = "https://genai.example.test"
API_KEY = "test-gateway-key-not-real"

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler) -> LocalGatewayProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LocalGatewayProvider(base_url=BASE_URL, api_key=API_KEY, client=client)


def _recording(response: httpx.Response) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return handler, seen


def _job(job_id: str = "job-1") -> JobHandle:
    return JobHandle(provider="local_genai", remote_id=job_id, kind="image", model_key="flux2")


def _assert_key_in_header_only(request: httpx.Request) -> None:
    assert request.headers[API_KEY_HEADER] == API_KEY
    assert API_KEY not in str(request.url)
    assert "api_key" not in request.url.params


# ---------------------------------------------------------------------------
# The payload builder
# ---------------------------------------------------------------------------
def test_a_video_payload_sends_length_not_frames() -> None:
    # Act
    built = build_generate_payload(video_request(), image=None)

    # Assert
    assert is_ok(built)
    assert built.value["length"] == 81
    assert built.value["fps"] == 16
    assert "frames" not in built.value


def test_a_video_payload_defaults_to_the_81_frame_clip() -> None:
    built = build_generate_payload(video_request(length_frames=None, fps=None), image=None)

    assert is_ok(built)
    assert (built.value["length"], built.value["fps"]) == (81, 16)


@pytest.mark.parametrize("request_", [image_request(), video_request()])
def test_width_and_height_are_always_explicit(request_: object) -> None:
    built = build_generate_payload(request_, image=None)  # type: ignore[arg-type]

    assert is_ok(built)
    assert built.value["width"] > 0
    assert built.value["height"] > 0


@pytest.mark.parametrize(("width", "height"), [(0, 1344), (768, 0), (770, 1344), (4096, 1024)])
def test_geometry_that_is_not_explicit_multiples_of_16_is_refused(width: int, height: int) -> None:
    built = build_generate_payload(image_request(width=width, height=height), image=None)

    assert is_err(built)
    assert is_pre_submit(built.error)


@pytest.mark.parametrize(
    "model", ["zootopia", "storybook", "storybook_wan", "hunyuan", "", "FLUX2"]
)
def test_a_model_off_the_allowlist_is_refused_before_any_request(model: str) -> None:
    built = build_generate_payload(image_request(model_key=model), image=None)

    assert is_err(built)
    assert is_pre_submit(built.error)


def test_a_model_is_refused_for_the_kind_it_does_not_render() -> None:
    assert is_err(build_generate_payload(image_request(model_key="wan"), image=None))
    assert is_err(build_generate_payload(video_request(model_key="flux2"), image=None))


@pytest.mark.parametrize(
    ("request_", "image"),
    [
        (image_request(), None),
        (image_request(refs=(Path("a.jpg"),), denoise=0.6), "data:image/jpeg;base64,AA=="),
        (video_request(), None),
        (video_request(refs=(Path("a.jpg"),)), "data:image/jpeg;base64,AA=="),
    ],
)
def test_every_payload_is_a_closed_dict_with_an_allowlisted_model(
    request_: object, image: str | None
) -> None:
    built = build_generate_payload(request_, image=image)  # type: ignore[arg-type]

    assert is_ok(built)
    allowed = {"type", "model", "prompt", "width", "height", "steps", "seed", "client"}
    allowed |= {"image", "denoise", "length", "fps"}
    assert set(built.value) <= allowed
    assert built.value["model"] in LOCAL_MODEL_ALLOWLIST
    assert built.value["client"] == CLIENT_TAG


def test_more_than_one_reference_must_be_a_collage_first() -> None:
    built = build_generate_payload(
        image_request(refs=(Path("a.jpg"), Path("b.jpg"))), image="data:image/jpeg;base64,AA=="
    )

    assert is_err(built)
    assert is_pre_submit(built.error)


def test_denoise_without_a_reference_and_on_video_is_refused() -> None:
    assert is_err(build_generate_payload(image_request(denoise=0.6), image=None))
    assert is_err(build_generate_payload(video_request(denoise=0.6), image=None))


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------
async def test_submit_posts_the_closed_payload_with_the_key_in_a_header_only() -> None:
    # Arrange
    handler, seen = _recording(httpx.Response(200, json={"job_id": "job-1", "model": "flux2"}))
    provider = _provider(handler)

    # Act
    result = await provider.submit(
        image_request(), correlation_key="m:1:0:1", webhook_url=None, timeout_s=5.0
    )

    # Assert
    assert is_ok(result)
    assert result.value.remote_id == "job-1"
    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/generate"
    _assert_key_in_header_only(request)
    body = orjson.loads(request.content)
    assert body["model"] == "flux2"
    assert (body["width"], body["height"]) == (768, 1344)


async def test_a_reference_travels_as_a_base64_data_url(tmp_path: Path) -> None:
    # Arrange
    ref = jpeg_file(tmp_path)
    handler, seen = _recording(httpx.Response(200, json={"job_id": "job-2"}))
    provider = _provider(handler)

    # Act
    result = await provider.submit(
        image_request(refs=(ref,), denoise=0.6), correlation_key="k", webhook_url=None, timeout_s=5
    )

    # Assert
    assert is_ok(result)
    image = orjson.loads(seen[0].content)["image"]
    assert image.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image.split(",", 1)[1]) == ref.read_bytes()


async def test_a_reference_that_is_not_an_image_is_refused_before_the_post(tmp_path: Path) -> None:
    ref = tmp_path / "note.jpg"
    ref.write_bytes(b"not an image")
    handler, seen = _recording(httpx.Response(200, json={"job_id": "never"}))

    result = await _provider(handler).submit(
        image_request(refs=(ref,)), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert is_pre_submit(result.error)
    assert seen == []


async def test_a_502_with_no_job_id_is_a_non_retryable_pre_submit_error() -> None:
    # Arrange — what ComfyUI's workflow validation looks like through the gateway.
    handler, _ = _recording(
        httpx.Response(502, json={"detail": "ComfyUI rejected workflow: missing node"})
    )

    # Act
    result = await _provider(handler).submit(
        video_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    # Assert
    assert is_err(result)
    assert is_pre_submit(result.error)
    assert not is_ambiguous(result.error)
    assert not result.error.is_retryable
    assert result.error.error_code is ErrorCode.INVALID_INPUT


async def test_a_502_that_carries_a_job_id_is_ambiguous() -> None:
    handler, _ = _recording(httpx.Response(502, json={"job_id": "job-3"}))

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert is_ambiguous(result.error)


@pytest.mark.parametrize("status", [500, 504])
async def test_a_server_error_after_the_body_left_is_ambiguous(status: int) -> None:
    handler, _ = _recording(httpx.Response(status, text="upstream"))

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert isinstance(result.error, ProviderAmbiguousError)
    assert not result.error.is_retryable


async def test_a_200_with_no_job_id_is_ambiguous() -> None:
    handler, _ = _recording(httpx.Response(200, json={"status": "accepted"}))

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert is_ambiguous(result.error)


async def test_a_read_timeout_after_the_post_is_ambiguous_never_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert isinstance(result.error, ProviderAmbiguousError)
    assert not result.error.is_retryable


async def test_a_connect_failure_is_pre_submit_and_may_fall_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert isinstance(result.error, ProviderUnavailableError)
    assert is_pre_submit(result.error)


async def test_a_busy_gateway_is_rate_limited_and_pre_submit() -> None:
    handler, _ = _recording(httpx.Response(429))

    result = await _provider(handler).submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert isinstance(result.error, ProviderRateLimitedError)
    assert is_pre_submit(result.error)


async def test_a_disallowed_model_never_reaches_the_network() -> None:
    handler, seen = _recording(httpx.Response(200, json={"job_id": "never"}))

    result = await _provider(handler).submit(
        image_request(model_key="zootopia"), correlation_key="k", webhook_url=None, timeout_s=5
    )

    assert is_err(result)
    assert seen == []


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("queued", JobPhase.QUEUED),
        ("running", JobPhase.RUNNING),
        ("done", JobPhase.SUCCEEDED),
        ("error", JobPhase.FAILED),
        ("unknown", JobPhase.UNKNOWN),
    ],
)
async def test_poll_maps_the_gateway_status(status: str, phase: JobPhase) -> None:
    handler, seen = _recording(httpx.Response(200, json={"status": status}))

    result = await _provider(handler).poll(_job(), timeout_s=5)

    assert is_ok(result)
    assert result.value.phase is phase
    assert seen[0].url.path == "/jobs/job-1"
    _assert_key_in_header_only(seen[0])


async def test_an_unknown_status_is_terminal_and_makes_the_attempt_ambiguous() -> None:
    handler, _ = _recording(httpx.Response(200, json={"status": "unknown"}))

    result = await _provider(handler).poll(_job("typo"), timeout_s=5)

    assert is_ok(result)
    assert result.value.phase.is_terminal
    assert ATTEMPT_STATUS_FOR_PHASE[result.value.phase] is MediaAttemptStatus.AMBIGUOUS


async def test_a_done_job_reports_its_outputs() -> None:
    body = {"status": "done", "outputs": [{"filename": "a.png"}, {"filename": "b.png"}]}
    handler, _ = _recording(httpx.Response(200, json=body))

    result = await _provider(handler).poll(_job(), timeout_s=5)

    assert is_ok(result)
    assert result.value.output_count == 2


async def test_a_network_drop_during_a_poll_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network is unreachable", request=request)

    result = await _provider(handler).poll(_job(), timeout_s=5)

    assert is_err(result)
    assert result.error.is_retryable


async def test_a_status_we_do_not_know_is_an_error_not_a_guess() -> None:
    handler, _ = _recording(httpx.Response(200, json={"status": "paused"}))

    result = await _provider(handler).poll(_job(), timeout_s=5)

    assert is_err(result)


# ---------------------------------------------------------------------------
# fetch, cancel, health, queue
# ---------------------------------------------------------------------------
async def test_fetch_streams_the_result_to_disk_with_its_digest(tmp_path: Path) -> None:
    # Arrange
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 5_000
    handler, seen = _recording(
        httpx.Response(200, content=payload, headers={"content-type": "image/png"})
    )
    dest = tmp_path / "ws" / "out.png"

    # Act
    result = await _provider(handler).fetch(_job(), 1, dest, max_bytes=1_000_000, timeout_s=5)

    # Assert
    assert is_ok(result)
    assert dest.read_bytes() == payload
    assert result.value.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.value.mime == "image/png"
    assert seen[0].url.path == "/result/job-1"
    assert seen[0].url.params["index"] == "1"
    _assert_key_in_header_only(seen[0])
    assert not (tmp_path / "ws" / "out.png.part").exists()


async def test_fetch_refuses_a_result_over_max_bytes_and_leaves_nothing(tmp_path: Path) -> None:
    handler, _ = _recording(
        httpx.Response(200, content=b"x" * 10_000, headers={"content-type": "video/mp4"})
    )
    dest = tmp_path / "out.mp4"

    result = await _provider(handler).fetch(_job(), 0, dest, max_bytes=1_000, timeout_s=5)

    assert is_err(result)
    assert not result.error.is_retryable
    assert list(tmp_path.iterdir()) == []


async def test_fetch_refuses_an_unexpected_content_type(tmp_path: Path) -> None:
    handler, _ = _recording(
        httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    )

    result = await _provider(handler).fetch(_job(), 0, tmp_path / "o", max_bytes=100, timeout_s=5)

    assert is_err(result)


async def test_cancel_never_calls_interrupt_or_anything_else() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"cancel sent {request.method} {request.url.path}")

    result = await _provider(handler).cancel(_job())

    assert is_ok(result)
    assert result.value is False


async def test_health_reads_health_with_the_key_in_a_header() -> None:
    handler, seen = _recording(httpx.Response(200, json={"status": "ok"}))

    result = await _provider(handler).health()

    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    _assert_key_in_header_only(seen[0])


async def test_health_reports_an_unreachable_gateway_as_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    result = await _provider(handler).health()

    assert is_ok(result)
    assert result.value.state is HealthState.UNAVAILABLE


async def test_the_queue_lists_running_and_pending_ids_for_reconciliation() -> None:
    body = {
        "status": "busy",
        "running_jobs": [{"job_id": "job-1"}],
        "pending_jobs": ["job-2", {"id": "job-3"}],
    }
    handler, seen = _recording(httpx.Response(200, json=body))

    result = await _provider(handler).queued_job_ids(timeout_s=5)

    assert is_ok(result)
    assert result.value == frozenset({"job-1", "job-2", "job-3"})
    _assert_key_in_header_only(seen[0])


def test_the_adapter_satisfies_the_protocol_and_takes_one_reference() -> None:
    provider = _provider(lambda request: httpx.Response(200))

    assert isinstance(provider, MediaGenProvider)
    capabilities = provider.capabilities()
    assert capabilities.max_reference_images == 1
    assert capabilities.idempotent_submit is False
    assert capabilities.cancel == "none"
