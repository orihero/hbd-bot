"""The moderation seam M2.4 ships (IMAGE_VIDEO_SPEC §6.2, §6.3): no default, closed codes, fail
closed. The guard client itself is M3.1; what is pinned here is what it will be held to."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bayram.config import Settings
from bayram.contracts import is_err, is_ok
from bayram.db.enums import MediaScreenDecision
from bayram.moderation.contracts import (
    MEDIA_POLICY_VERSION,
    MediaModerator,
    MediaVerdict,
    TextItem,
    strictest,
)
from bayram.moderation.factory import (
    UnbuiltGuardModerator,
    build_media_moderator,
    guard_credentials,
)
from bayram.moderation.fake import FakeModerator

_VALID: dict[str, Any] = {
    "decision": "allow",
    "categories": [],
    "scores": {},
    "subject": "prompt",
    "model_id": "m",
    "policy_version": MEDIA_POLICY_VERSION,
}


def test_a_verdict_without_a_decision_does_not_parse() -> None:
    values = dict(_VALID)
    del values["decision"]
    with pytest.raises(ValidationError):
        MediaVerdict.model_validate(values)


def test_a_verdict_with_an_extra_key_does_not_parse() -> None:
    # The song moderator's fail-open (§0.3): ``{"allowed": false}`` beside a defaulted field.
    with pytest.raises(ValidationError):
        MediaVerdict.model_validate({**_VALID, "allowed": False})


def test_an_unknown_category_does_not_parse() -> None:
    with pytest.raises(ValidationError):
        MediaVerdict.model_validate({**_VALID, "categories": ["spicy"]})


@pytest.mark.parametrize(
    ("decisions", "expected"),
    [
        ((), MediaScreenDecision.ALLOW),
        (
            (MediaScreenDecision.ALLOW, MediaScreenDecision.UNAVAILABLE),
            MediaScreenDecision.UNAVAILABLE,
        ),
        ((MediaScreenDecision.UNAVAILABLE, MediaScreenDecision.REVIEW), MediaScreenDecision.REVIEW),
        ((MediaScreenDecision.REVIEW, MediaScreenDecision.BLOCK), MediaScreenDecision.BLOCK),
    ],
)
def test_the_strictest_decision_wins(
    decisions: tuple[MediaScreenDecision, ...], expected: MediaScreenDecision
) -> None:
    assert strictest(decisions) is expected


async def test_the_gateway_moderator_fails_closed_until_it_is_built(tmp_path: Path) -> None:
    moderator = UnbuiltGuardModerator()
    assert isinstance(moderator, MediaModerator)
    item = TextItem(id="prompt", subject="prompt", content="hello")

    assert is_err(await moderator.screen_text([item], policy=MEDIA_POLICY_VERSION))
    assert is_err(await moderator.screen_images([], policy=MEDIA_POLICY_VERSION))
    assert is_err(await moderator.transcribe(tmp_path / "x.ogg", language_hint="uz"))


def test_the_factory_builds_the_fake_only_when_asked_or_under_fakes(settings: Settings) -> None:
    assert isinstance(build_media_moderator(settings), UnbuiltGuardModerator)
    assert isinstance(
        build_media_moderator(settings.model_copy(update={"media_moderator": "fake"})),
        FakeModerator,
    )
    assert isinstance(
        build_media_moderator(settings.model_copy(update={"use_fake_providers": True})),
        FakeModerator,
    )


@pytest.mark.parametrize(
    ("guard_url", "is_gateways"),
    [
        ("", True),
        ("https://gpu.example.test/", True),
        ("https://GPU.example.test/v1", True),
        ("https://guards.example.test", False),
        ("https://gpu.example.test:8443", False),
        ("not a url", False),
    ],
)
def test_the_gateways_credentials_go_only_to_the_gateways_host(
    settings: Settings, guard_url: str, is_gateways: bool
) -> None:
    # M3.R: a hosted guard endpoint (D24 fallback) never receives the 5090's key or its
    # Cloudflare Access token; it gets its own media_moderator_* credentials.
    configured = settings.model_copy(
        update={
            "genai_base_url": "https://gpu.example.test",
            "genai_api_key": "gateway-key",
            "genai_access_client_id": "gateway-id",
            "genai_access_client_secret": "gateway-secret",
            "media_moderator_base_url": guard_url,
            "media_moderator_api_key": "guard-key",
        }
    )

    credentials = guard_credentials(configured)

    if is_gateways:
        assert credentials.api_key == "gateway-key"
        assert credentials.access_client_secret == "gateway-secret"
    else:
        assert credentials.api_key == "guard-key"
        assert credentials.access_client_id == ""
        assert credentials.access_client_secret == ""


async def test_the_fake_reports_the_strictest_subject_and_its_codes() -> None:
    from bayram.moderation.contracts import CategoryCode

    fake = FakeModerator(
        decisions={"narration": MediaScreenDecision.REVIEW, "prompt": MediaScreenDecision.BLOCK},
        categories={"prompt": (CategoryCode.HATE,)},
    )
    verdict = await fake.screen_text(
        [
            TextItem(id="n", subject="narration", content="a"),
            TextItem(id="p", subject="prompt", content="b"),
        ],
        policy=MEDIA_POLICY_VERSION,
    )
    assert is_ok(verdict)
    assert verdict.value.decision is MediaScreenDecision.BLOCK
    assert verdict.value.categories == (CategoryCode.HATE,)
    assert verdict.value.subject == "prompt"
