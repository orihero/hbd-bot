"""``GatewayGuardModerator`` against the §6.5 contract, over ``httpx.MockTransport``
(IMAGE_VIDEO_SPEC §6.2–§6.5, §10 M3.1). No network.

Pinned here: the G1 label mapping (unsafe → block, controversial → review, safe → allow, the
label missing → unavailable, an unknown category → block); G2's ``scores:{}`` → unavailable
and zero-tolerance ``sexual`` on any image; a slogan in a photo reaching G1 through G8; one
blocked image of two blocking the call; a timeout is an ``Err``; the youth signal from a
caption meeting ``sexual`` is the hard rule; the key rides in a header only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from bayram.contracts import is_err, is_ok
from bayram.db.enums import MediaScreenDecision
from bayram.moderation.contracts import (
    MEDIA_POLICY_VERSION,
    CategoryCode,
    ImageItem,
    MediaModerator,
    TextItem,
)
from bayram.moderation.gateway import (
    G1_CHAT_PATH,
    G1_TEXT_PATH,
    G2_IMAGE_PATH,
    G3_TRANSCRIBE_PATH,
    G8_DESCRIBE_PATH,
    GatewayGuardModerator,
)
from bayram.moderation.policy import G2_CUSTOM_MINOR_POLICY, G2_POLICIES
from bayram.providers.media.local_gateway import API_KEY_HEADER

BASE = "https://guards.example.test"
KEY = "guard-key"
Handler = Callable[[httpx.Request], httpx.Response]


def clean_scores(**over: float) -> dict[str, float]:
    scores = dict.fromkeys(G2_POLICIES, 0.01)
    scores.update(over)
    return scores


class Gateway:
    """A scripted guard gateway. Each route answers from a callable; every request is kept."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.g1_safety: dict[str, Any] = {}
        self.g1_categories: dict[str, list[str]] = {}
        self.g2_scores: dict[str, Any] = {}
        self.g8: dict[str, dict[str, Any]] = {}
        self.fail: dict[str, Exception | int] = {}

    def body(self, path: str) -> dict[str, Any]:
        found = [r for r in self.requests if r.url.path == path]
        assert found, f"no call to {path}"
        body: dict[str, Any] = json.loads(found[-1].content)
        return body

    def calls(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        failure = self.fail.get(path)
        if isinstance(failure, Exception):
            raise failure
        if isinstance(failure, int):
            return httpx.Response(failure, json={"detail": "nope"})
        if path == G1_TEXT_PATH:
            items = json.loads(request.content)["items"]
            results = []
            for item in items:
                entry: dict[str, Any] = {"id": item["id"]}
                safety = self.g1_safety.get(item["id"], "safe")
                if safety is not None:
                    entry["safety"] = safety
                entry["categories"] = self.g1_categories.get(item["id"], [])
                results.append(entry)
            return httpx.Response(200, json={"model": "qwen3guard", "results": results})
        if path == G2_IMAGE_PATH:
            items = json.loads(request.content)["items"]
            return httpx.Response(
                200,
                json={
                    "model": "shieldgemma-2",
                    "results": [
                        {"id": i["id"], "scores": self.g2_scores.get(i["id"], clean_scores())}
                        for i in items
                    ],
                },
            )
        if path == G8_DESCRIBE_PATH:
            items = json.loads(request.content)["items"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": i["id"], **self.g8.get(i["id"], {"ocr_text": "", "caption": ""})}
                        for i in items
                    ]
                },
            )
        return httpx.Response(404)


@pytest.fixture
def gateway() -> Gateway:
    return Gateway()


def _moderator(gateway: Gateway, **kwargs: Any) -> GatewayGuardModerator:
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    return GatewayGuardModerator(base_url=BASE, api_key=KEY, client=client, **kwargs)


def _image(tmp_path: Path, name: str, subject: Any = "upload") -> ImageItem:
    path = tmp_path / f"{name}.jpg"
    path.write_bytes(b"\xff\xd8\xff" + name.encode())
    return ImageItem(id=name, subject=subject, path=path)


async def _text(moderator: GatewayGuardModerator, content: str = "a garden") -> Any:
    result = await moderator.screen_text(
        [TextItem(id="prompt", subject="prompt", content=content)], policy=MEDIA_POLICY_VERSION
    )
    assert is_ok(result), result
    return result.value


# ---------------------------------------------------------------------------
# G1
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Unsafe", MediaScreenDecision.BLOCK),
        ("controversial", MediaScreenDecision.REVIEW),
        ("safe", MediaScreenDecision.ALLOW),
    ],
)
async def test_g1_labels_map_to_our_decisions(
    gateway: Gateway, label: str, expected: MediaScreenDecision
) -> None:
    gateway.g1_safety["prompt"] = label
    gateway.g1_categories["prompt"] = [] if label == "safe" else ["Violent"]

    verdict = await _text(_moderator(gateway))

    assert verdict.decision is expected
    assert verdict.categories == (() if label == "safe" else (CategoryCode.VIOLENCE,))
    assert isinstance(_moderator(gateway), MediaModerator)


async def test_g1_with_the_label_and_no_scores_is_decided_from_the_label(gateway: Gateway) -> None:
    # §6.3: ``safety`` present, ``scores``/logprobs absent — the label decides; nothing defaults.
    gateway.g1_safety["prompt"] = "unsafe"
    gateway.g1_categories["prompt"] = ["Jailbreak"]

    verdict = await _text(_moderator(gateway))

    assert verdict.decision is MediaScreenDecision.BLOCK
    assert verdict.categories == (CategoryCode.JAILBREAK,)


async def test_g1_without_a_safety_label_is_unavailable(gateway: Gateway) -> None:
    gateway.g1_safety["prompt"] = None

    verdict = await _text(_moderator(gateway))

    assert verdict.decision is MediaScreenDecision.UNAVAILABLE


async def test_an_unknown_g1_label_is_unavailable_not_allowed(gateway: Gateway) -> None:
    gateway.g1_safety["prompt"] = "probably fine"

    assert (await _text(_moderator(gateway))).decision is MediaScreenDecision.UNAVAILABLE


async def test_an_unknown_category_blocks(gateway: Gateway) -> None:
    gateway.g1_safety["prompt"] = "controversial"
    gateway.g1_categories["prompt"] = ["Something New"]

    verdict = await _text(_moderator(gateway))

    assert verdict.decision is MediaScreenDecision.BLOCK
    assert verdict.categories == (CategoryCode.OTHER_UNSAFE,)


async def test_a_missing_result_for_an_item_is_unavailable(gateway: Gateway) -> None:
    def drop_narration(request: httpx.Request) -> httpx.Response:
        body = json.loads(gateway(request).content)
        body["results"] = [r for r in body["results"] if r["id"] != "narration"]
        return httpx.Response(200, json=body)

    moderator = GatewayGuardModerator(
        base_url=BASE,
        api_key=KEY,
        client=httpx.AsyncClient(transport=httpx.MockTransport(drop_narration)),
    )
    result = await moderator.screen_text(
        [
            TextItem(id="prompt", subject="prompt", content="a garden"),
            TextItem(id="narration", subject="narration", content="happy birthday"),
        ],
        policy=MEDIA_POLICY_VERSION,
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.UNAVAILABLE


async def test_a_timeout_is_an_err(gateway: Gateway) -> None:
    gateway.fail[G1_TEXT_PATH] = httpx.ReadTimeout("slow")

    result = await _moderator(gateway).screen_text(
        [TextItem(id="prompt", subject="prompt", content="a garden")], policy=MEDIA_POLICY_VERSION
    )

    assert is_err(result)
    assert result.error.context["reason"] == "timeout"


async def test_an_http_error_is_an_err(gateway: Gateway) -> None:
    gateway.fail[G1_TEXT_PATH] = 503

    result = await _moderator(gateway).screen_text(
        [TextItem(id="prompt", subject="prompt", content="a garden")], policy=MEDIA_POLICY_VERSION
    )

    assert is_err(result)


async def test_a_denylist_term_blocks_without_calling_g1(gateway: Gateway) -> None:
    verdict = await _text(_moderator(gateway), "a nаked woman")  # Cyrillic а

    assert verdict.decision is MediaScreenDecision.BLOCK
    assert verdict.categories == (CategoryCode.SEXUAL,)
    assert gateway.calls(G1_TEXT_PATH) == 0


async def test_a_youth_term_with_a_sexual_category_is_the_hard_rule(gateway: Gateway) -> None:
    gateway.g1_safety["prompt"] = "controversial"
    gateway.g1_categories["prompt"] = ["Sexual Content or Sexual Acts"]

    verdict = await _text(_moderator(gateway), "a schoolgirl in a revealing pose")

    assert verdict.decision is MediaScreenDecision.BLOCK
    assert set(verdict.categories) == {CategoryCode.SEXUAL, CategoryCode.SEXUAL_MINORS}


async def test_the_key_is_a_header_and_never_in_the_url(gateway: Gateway) -> None:
    await _text(_moderator(gateway, access_client_id="id", access_client_secret="sec"))

    request = gateway.requests[-1]
    assert request.headers[API_KEY_HEADER] == KEY
    assert request.headers["CF-Access-Client-Id"] == "id"
    assert KEY not in str(request.url)


async def test_the_interim_chat_route_is_parsed_strictly(gateway: Gateway) -> None:
    answers = iter(["Safety: Unsafe\nCategories: Violent", "I think it is fine"])

    def chat(request: httpx.Request) -> httpx.Response:
        gateway.requests.append(request)
        assert request.url.path == G1_CHAT_PATH
        return httpx.Response(200, json={"choices": [{"message": {"content": next(answers)}}]})

    moderator = GatewayGuardModerator(
        base_url=BASE,
        api_key=KEY,
        text_route="chat",
        client=httpx.AsyncClient(transport=httpx.MockTransport(chat)),
    )
    first = await moderator.screen_text(
        [TextItem(id="p", subject="prompt", content="a duel")], policy=MEDIA_POLICY_VERSION
    )
    second = await moderator.screen_text(
        [TextItem(id="p", subject="prompt", content="a duel")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(first) and first.value.decision is MediaScreenDecision.BLOCK
    assert is_ok(second) and second.value.decision is MediaScreenDecision.UNAVAILABLE


# ---------------------------------------------------------------------------
# G2 + G8
# ---------------------------------------------------------------------------
async def test_g2_with_empty_scores_is_unavailable(gateway: Gateway, tmp_path: Path) -> None:
    gateway.g2_scores["upload-0"] = {}

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.UNAVAILABLE


async def test_g2_missing_a_policy_is_unavailable(gateway: Gateway, tmp_path: Path) -> None:
    scores = clean_scores()
    del scores["violence"]
    gateway.g2_scores["upload-0"] = scores

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.UNAVAILABLE


async def test_sexual_on_any_image_blocks_at_the_low_threshold(
    gateway: Gateway, tmp_path: Path
) -> None:
    gateway.g2_scores["upload-0"] = clean_scores(sexually_explicit=0.21)

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result)
    assert result.value.decision is MediaScreenDecision.BLOCK
    assert result.value.categories == (CategoryCode.SEXUAL,)
    body = gateway.body(G2_IMAGE_PATH)
    assert body["policies"][-1] == {"custom": G2_CUSTOM_MINOR_POLICY}


async def test_one_blocked_output_of_two_blocks_the_call(gateway: Gateway, tmp_path: Path) -> None:
    gateway.g2_scores["output-1"] = clean_scores(violence=0.9)

    result = await _moderator(gateway).screen_images(
        [
            _image(tmp_path, "output-0", "output_image"),
            _image(tmp_path, "output-1", "output_image"),
        ],
        policy=MEDIA_POLICY_VERSION,
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.BLOCK
    assert result.value.categories == (CategoryCode.VIOLENCE,)


async def test_a_slogan_in_a_photo_reaches_g1_through_g8(gateway: Gateway, tmp_path: Path) -> None:
    gateway.g8["upload-0"] = {"ocr_text": "DEATH TO THE HERETICS", "caption": "a man with a sign"}
    gateway.g1_safety["upload-0:ocr"] = "unsafe"
    gateway.g1_categories["upload-0:ocr"] = ["Violent"]

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.BLOCK
    sent = gateway.body(G1_TEXT_PATH)["items"]
    assert {"id": "upload-0:ocr", "content": "DEATH TO THE HERETICS"} in sent
    assert {"id": "upload-0:caption", "content": "a man with a sign"} in sent
    assert result.value.subject == "upload_text"


async def test_an_output_caption_is_screened_as_output_text(
    gateway: Gateway, tmp_path: Path
) -> None:
    gateway.g8["output-0"] = {"ocr_text": "", "caption": "a cake on a table"}

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "output-0", "output_image")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.ALLOW
    assert gateway.body(G1_TEXT_PATH)["items"] == [
        {"id": "output-0:caption", "content": "a cake on a table"}
    ]


async def test_a_caption_youth_term_with_sexual_scores_is_the_hard_rule(
    gateway: Gateway, tmp_path: Path
) -> None:
    gateway.g8["upload-0"] = {"ocr_text": "", "caption": "a young girl on a bed"}
    gateway.g2_scores["upload-0"] = clean_scores(sexually_explicit=0.5)

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.BLOCK
    assert CategoryCode.SEXUAL_MINORS in result.value.categories


async def test_the_custom_minor_policy_over_its_threshold_is_the_hard_rule(
    gateway: Gateway, tmp_path: Path
) -> None:
    gateway.g2_scores["upload-0"] = {**clean_scores(), "custom": 0.15}

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and CategoryCode.SEXUAL_MINORS in result.value.categories
    assert result.value.decision is MediaScreenDecision.BLOCK


async def test_g8_failing_does_not_hide_a_g2_block(gateway: Gateway, tmp_path: Path) -> None:
    gateway.g2_scores["upload-0"] = clean_scores(violence=0.95)
    gateway.fail[G8_DESCRIBE_PATH] = httpx.ReadTimeout("slow")

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.BLOCK


async def test_g8_failing_alone_is_unavailable(gateway: Gateway, tmp_path: Path) -> None:
    gateway.fail[G8_DESCRIBE_PATH] = 502

    result = await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION
    )

    assert is_ok(result) and result.value.decision is MediaScreenDecision.UNAVAILABLE


# ---------------------------------------------------------------------------
# G3
# ---------------------------------------------------------------------------
async def test_g3_reads_text_language_and_the_quality_numbers(tmp_path: Path) -> None:
    def whisper(request: httpx.Request) -> httpx.Response:
        assert request.url.path == G3_TRANSCRIBE_PATH
        assert b"multipart/form-data" in request.headers["content-type"].encode()
        return httpx.Response(
            200,
            json={
                "text": " Tug'ilgan kuning bilan ",
                "language": "UZ",
                "segments": [
                    {"avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.3},
                    {"avg_logprob": -0.4, "no_speech_prob": 0.05, "compression_ratio": 2.7},
                ],
            },
        )

    note = tmp_path / "note.ogg"
    note.write_bytes(b"OggS")
    moderator = GatewayGuardModerator(
        base_url=BASE, api_key=KEY, client=httpx.AsyncClient(transport=httpx.MockTransport(whisper))
    )

    result = await moderator.transcribe(note, language_hint="uz")

    assert is_ok(result)
    assert result.value.text == "Tug'ilgan kuning bilan" and result.value.language == "uz"
    assert result.value.avg_logprob == pytest.approx(-0.3)
    assert result.value.no_speech_prob == pytest.approx(0.05)
    # §5.4 refuses on ANY segment above 2.4, so the worst one is kept.
    assert result.value.max_compression_ratio == pytest.approx(2.7)


async def test_g3_without_a_language_is_an_err(tmp_path: Path) -> None:
    note = tmp_path / "note.ogg"
    note.write_bytes(b"OggS")
    moderator = GatewayGuardModerator(
        base_url=BASE,
        api_key=KEY,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "hi"}))
        ),
    )

    assert is_err(await moderator.transcribe(note, language_hint="en"))


# ---------------------------------------------------------------------------
# M3.R
# ---------------------------------------------------------------------------
async def test_g1_carries_the_requests_language_as_lang_hint(gateway: Gateway) -> None:
    # §6.5 G1: req {items, lang_hint} — Uzbek is where guard quality is the D24 risk.
    result = await _moderator(gateway).screen_text(
        [TextItem(id="prompt", subject="prompt", content="bogʻda tort")],
        policy=MEDIA_POLICY_VERSION,
        lang_hint="uz",
    )

    assert is_ok(result)
    assert gateway.body(G1_TEXT_PATH)["lang_hint"] == "uz"


async def test_g8_strings_reach_g1_with_the_same_lang_hint(
    gateway: Gateway, tmp_path: Path
) -> None:
    gateway.g8["upload-0"] = {"ocr_text": "tabriklaymiz", "caption": "a cake"}

    await _moderator(gateway).screen_images(
        [_image(tmp_path, "upload-0")], policy=MEDIA_POLICY_VERSION, lang_hint="ru"
    )

    assert gateway.body(G1_TEXT_PATH)["lang_hint"] == "ru"


async def test_no_images_is_unavailable_never_allow(gateway: Gateway) -> None:
    # An output screen handed nothing must not deliver on it (§6.3 fail closed).
    result = await _moderator(gateway).screen_images([], policy=MEDIA_POLICY_VERSION)

    assert is_ok(result)
    assert result.value.decision is MediaScreenDecision.UNAVAILABLE
    assert gateway.requests == []
