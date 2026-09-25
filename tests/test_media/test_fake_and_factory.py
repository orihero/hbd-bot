"""FakeMediaProvider renders real files; the factory maps a backend name to an adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

import httpx
import pytest
from PIL import Image

from bayram.config import Settings
from bayram.contracts import is_err, is_ok
from bayram.db.enums import MediaBackend
from bayram.errors import ProviderUnavailableError
from bayram.media.contracts import JobHandle, JobPhase, MediaGenProvider, is_pre_submit
from bayram.providers.media.factory import UnbuiltMediaProvider, build_media_provider
from bayram.providers.media.fake import FakeMediaProvider, fake_clip_bytes
from bayram.providers.media.local_gateway import ACCESS_CLIENT_ID_HEADER, LocalGatewayProvider
from tests.test_media.conftest import image_request, video_request


async def test_a_fake_image_is_a_real_png_at_the_requested_size(tmp_path: Path) -> None:
    # Arrange
    provider = FakeMediaProvider(polls_until_done=1)

    # Act
    handle = await provider.submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=1
    )
    assert is_ok(handle)
    first = await provider.poll(handle.value, timeout_s=1)
    second = await provider.poll(handle.value, timeout_s=1)
    fetched = await provider.fetch(
        handle.value, 0, tmp_path / "o.png", max_bytes=10**7, timeout_s=1
    )

    # Assert
    assert is_ok(first) and first.value.phase is JobPhase.RUNNING
    assert is_ok(second) and second.value.phase is JobPhase.SUCCEEDED
    assert is_ok(fetched)
    with Image.open(fetched.value.path) as image:
        assert image.size == (768, 1344)


async def test_two_seeds_give_two_different_images(tmp_path: Path) -> None:
    provider = FakeMediaProvider()
    paths = []
    for seed in (7, 8):
        handle = await provider.submit(
            image_request(seed=seed), correlation_key="k", webhook_url=None, timeout_s=1
        )
        assert is_ok(handle)
        fetched = await provider.fetch(
            handle.value, 0, tmp_path / f"{seed}.png", max_bytes=10**7, timeout_s=1
        )
        assert is_ok(fetched)
        paths.append(fetched.value.sha256)

    assert paths[0] != paths[1]


async def test_a_fake_video_is_the_vendored_clip(tmp_path: Path) -> None:
    provider = FakeMediaProvider()
    handle = await provider.submit(
        video_request(), correlation_key="k", webhook_url=None, timeout_s=1
    )
    assert is_ok(handle)

    fetched = await provider.fetch(
        handle.value, 0, tmp_path / "o.mp4", max_bytes=10**7, timeout_s=1
    )

    assert is_ok(fetched)
    assert fetched.value.mime == "video/mp4"
    assert fetched.value.path.read_bytes() == fake_clip_bytes()


@pytest.mark.skipif(which("ffprobe") is None, reason="needs ffprobe")
def test_the_vendored_clip_is_a_decodable_five_second_video(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    clip.write_bytes(fake_clip_bytes())

    probed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert abs(float(probed.stdout.strip()) - 81 / 16) < 0.1


async def test_the_fake_records_every_submit_and_hands_out_queued_errors() -> None:
    boom = ProviderUnavailableError("scripted")
    provider = FakeMediaProvider(submit_errors=[boom])

    first = await provider.submit(
        image_request(), correlation_key="a", webhook_url=None, timeout_s=1
    )
    second = await provider.submit(
        image_request(), correlation_key="b", webhook_url=None, timeout_s=1
    )

    assert is_err(first) and first.error is boom
    assert is_ok(second)
    assert [s.correlation_key for s in provider.submits] == ["b"]


async def test_the_fake_refuses_what_the_gateway_would() -> None:
    provider = FakeMediaProvider()

    refused = await provider.submit(
        image_request(model_key="zootopia"), correlation_key="k", webhook_url=None, timeout_s=1
    )
    too_many = await provider.submit(
        image_request(refs=(Path("a"), Path("b"))),
        correlation_key="k",
        webhook_url=None,
        timeout_s=1,
    )

    assert is_err(refused) and is_pre_submit(refused.error)
    assert is_err(too_many) and is_pre_submit(too_many.error)
    assert provider.submits == []


async def test_the_fake_answers_unknown_for_an_id_it_never_issued() -> None:
    handle = JobHandle(provider="fake_media", remote_id="nope", kind="image", model_key="flux2")

    result = await FakeMediaProvider().poll(handle, timeout_s=1)

    assert is_ok(result)
    assert result.value.phase is JobPhase.UNKNOWN


def test_the_factory_builds_the_fake_under_use_fake_providers(settings: Settings) -> None:
    faked = settings.model_copy(update={"use_fake_providers": True})

    provider = build_media_provider(faked, MediaBackend.LOCAL)

    assert isinstance(provider, FakeMediaProvider)


def test_the_factory_builds_the_gateway_for_local(settings: Settings) -> None:
    provider = build_media_provider(settings, MediaBackend.LOCAL)

    assert isinstance(provider, LocalGatewayProvider)
    assert isinstance(provider, MediaGenProvider)


async def test_the_factory_passes_the_access_token_to_the_gateway(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    configured = settings.model_copy(
        update={
            "genai_base_url": "https://genai.example.test",
            "genai_api_key": "k",
            "genai_access_client_id": "id.access",
            "genai_access_client_secret": "not-a-real-secret",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_media_provider(configured, MediaBackend.LOCAL, client=client)
        await provider.health()

    assert seen[0].headers[ACCESS_CLIENT_ID_HEADER] == "id.access"


@pytest.mark.parametrize("backend", [MediaBackend.HIGGSFIELD, MediaBackend.FAL])
async def test_an_unbuilt_backend_fails_every_submit_pre_submit(
    settings: Settings, backend: MediaBackend
) -> None:
    provider = build_media_provider(settings, backend)

    result = await provider.submit(
        image_request(), correlation_key="k", webhook_url=None, timeout_s=1
    )

    assert isinstance(provider, UnbuiltMediaProvider)
    assert isinstance(provider, MediaGenProvider)
    assert is_err(result)
    assert is_pre_submit(result.error)
