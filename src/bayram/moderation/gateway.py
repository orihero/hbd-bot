"""``GatewayGuardModerator``: the guard models on the owner's 5090 (IMAGE_VIDEO_SPEC §6.2, §6.5).

Four HTTP calls, each the §6.5 contract the owner installs (M3.3):

* **G1** ``POST /v1/moderate/text`` — Qwen3Guard-Gen-4B. ``{items:[{id, content}], lang_hint}``
  → ``{model, results:[{id, safety, categories, logprobs?}]}``. The interim route, when
  ``media_guard_text_route="chat"``, is the same model on ``/v1/chat/completions``, one item
  per call, its ``Safety: … / Categories: …`` text parsed strictly
  (``policy.parse_qwen3guard_text``).
* **G2** ``POST /v1/moderate/image`` — ShieldGemma 2 with the three stock policies and the
  custom minor policy. ``{items:[{id, data_b64}], policies:[…]}`` → ``{model, results:[{id,
  scores:{policy: p}}]}``.
* **G3** ``POST /v1/audio/transcriptions`` — whisper large-v3, multipart OGG (M4 reads it).
* **G8** ``POST /v1/moderate/describe`` — OCR text + a short VLM caption per image. Both strings
  go through the L0 lists and then to G1 as ``upload_text`` / ``output_text``: this is what sees
  a slogan, a slur or a captioned flag that ShieldGemma's policies cannot (§6.1).

**What this class decides and what it does not.** It turns the guards' output into a
:class:`MediaVerdict` through :mod:`bayram.moderation.policy` — the label mapping, the
thresholds, the hard rule — and it runs the L0 lexicon over every text it screens (a denylist
hit is a block with no G1 call). The per-user budget, strikes and the legal hold are the stage
chain's (``runtime.media_jobs``), because they need the job row and Redis.

**Fail closed, and never lose a refusal.** A G1 call that fails is ``Err`` (the stage reads it
as ``unavailable``). Inside :meth:`screen_images` a G2 or G8 call that fails is an
``unavailable`` PART, combined with the others — so a G2 block is not turned into a retryable
``busy`` because G8 timed out. A result missing for an item, a missing ``safety`` label or
``scores:{}`` is ``unavailable`` for that item (§6.3).

Nothing here logs a prompt, a caption, an OCR string or base64 (§9.3, G7): only ids, counts,
status codes and the closed category codes.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import httpx
import orjson

from bayram.contracts import Result, err, is_err, ok
from bayram.db.enums import MediaScreenDecision
from bayram.errors import ModerationUnavailableError
from bayram.logging import get_logger
from bayram.moderation.contracts import (
    ImageItem,
    MediaVerdict,
    TextItem,
    VerdictSubject,
    VoiceTranscript,
    unavailable_verdict,
)
from bayram.moderation.lexicon import denylist_hits, has_youth_signal
from bayram.moderation.policy import (
    G2_CUSTOM_MINOR_POLICY,
    G2_POLICIES,
    G1Reading,
    block_verdict,
    combine,
    decide_g1,
    decide_g2,
    parse_g1_label,
    parse_qwen3guard_text,
)
from bayram.providers.media.local_gateway import API_KEY_HEADER, access_headers

__all__ = [
    "GatewayGuardModerator",
    "GUARD_MODERATOR_NAME",
    "G1_TEXT_PATH",
    "G1_CHAT_PATH",
    "G2_IMAGE_PATH",
    "G3_TRANSCRIBE_PATH",
    "G8_DESCRIBE_PATH",
    "G1_CHAT_MODEL",
    "G3_MODEL",
    "g2_policies_payload",
    "text_subject_for",
]

_LOG = get_logger(__name__)

GUARD_MODERATOR_NAME: Final[str] = "gateway_guard"
G1_TEXT_PATH: Final[str] = "/v1/moderate/text"
G1_CHAT_PATH: Final[str] = "/v1/chat/completions"
G2_IMAGE_PATH: Final[str] = "/v1/moderate/image"
G3_TRANSCRIBE_PATH: Final[str] = "/v1/audio/transcriptions"
G8_DESCRIBE_PATH: Final[str] = "/v1/moderate/describe"
#: The model name the interim chat route serves Qwen3Guard under (§6.5).
G1_CHAT_MODEL: Final[str] = "qwen3guard-gen-4b"
G3_MODEL: Final[str] = "whisper-large-v3"
_HTTP_OK: Final[int] = 200
#: The subject G8's strings are screened under, by the subject of the image they came from.
_TEXT_SUBJECT: Final[Mapping[str, VerdictSubject]] = {
    "upload": "upload_text",
    "collage": "upload_text",
    "output_image": "output_text",
    "output_frame": "output_text",
}


def text_subject_for(image_subject: VerdictSubject) -> VerdictSubject:
    """``upload``/``collage`` → ``upload_text``; an output → ``output_text``."""
    return _TEXT_SUBJECT.get(image_subject, "upload_text")


def g2_policies_payload() -> list[object]:
    """The ``policies`` list of every G2 call: the stock names, then the custom minor one."""
    stock: list[object] = [name for name in G2_POLICIES if name != G2_CUSTOM_MINOR_POLICY]
    return [*stock, {"custom": G2_CUSTOM_MINOR_POLICY}]


def _unavailable(guard: str, reason: str, **context: Any) -> ModerationUnavailableError:
    return ModerationUnavailableError(
        f"the {guard} guard did not answer: {reason}",
        context={"guard": guard, "reason": reason, **context},
    )


class GatewayGuardModerator:
    """:class:`~bayram.moderation.contracts.MediaModerator` over the §6.5 endpoints."""

    name: str = GUARD_MODERATOR_NAME

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        access_client_id: str = "",
        access_client_secret: str = "",
        text_route: str = "moderate",
        timeout_s: float = 15.0,
        sexual_block_p: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._access = access_headers(access_client_id, access_client_secret)
        self._text_route = text_route
        self._timeout_s = timeout_s
        self._sexual_block_p = sexual_block_p
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- MediaModerator -----------------------------------------------------
    async def screen_text(
        self, items: Sequence[TextItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]:
        """L0 then G1 over ``items``; the hard rule over the whole call (§6.4).

        ``lang_hint`` is the request's language (``uz``/``ru``/``en``), sent as G1's
        ``lang_hint`` (§6.5) — Uzbek is where the guard's quality is the D24 risk."""
        if not items:
            return ok(self._allow("prompt", policy))
        youth = has_youth_signal([item.content for item in items])
        l0 = self._denylist_parts(items, policy)
        if l0:
            return ok(self._combine(l0, items[0].subject, policy, youth=youth))
        readings = await self._g1(items, lang_hint=lang_hint)
        if is_err(readings):
            return readings
        parts = [self._g1_part(item, readings.value.get(item.id), policy) for item in items]
        return ok(self._combine(parts, items[0].subject, policy, youth=youth))

    async def screen_images(
        self, items: Sequence[ImageItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]:
        """G2 on every image and G8 on every image, G8's strings through L0 and G1 (§6.4 L2/L4).

        One verdict for the call: **a block on any image blocks the request** (L4 fails the
        whole request when either variant is blocked). **No images is ``unavailable``**, never
        ``allow``: nothing was looked at, and an output screen handed an empty list must not
        deliver on it (§6.3 fail closed).
        """
        if not items:
            return ok(unavailable_verdict("upload", model_id=self.name, policy=policy))
        encoded: list[tuple[ImageItem, str]] = []
        for item in items:
            data = await asyncio.to_thread(_read, item.path)
            if data is None:
                return err(_unavailable("g2", "an image to screen could not be read"))
            encoded.append((item, base64.b64encode(data).decode("ascii")))
        payload_items = [{"id": item.id, "data_b64": b64} for item, b64 in encoded]
        g2, g8 = await asyncio.gather(
            self._post(
                "g2", G2_IMAGE_PATH, {"items": payload_items, "policies": g2_policies_payload()}
            ),
            self._post("g8", G8_DESCRIBE_PATH, {"items": payload_items}),
        )
        parts: list[MediaVerdict] = []
        parts.extend(self._g2_parts(items, g2, policy))
        texts, described = self._g8_texts(items, g8)
        parts.extend(
            unavailable_verdict(item.subject, model_id=self.name, policy=policy)
            for item in items
            if item.id not in described
        )
        youth = has_youth_signal([text.content for text in texts])
        if texts:
            screened = await self.screen_text(texts, policy=policy, lang_hint=lang_hint)
            parts.append(
                screened.value
                if not is_err(screened)
                else unavailable_verdict(texts[0].subject, model_id=self.name, policy=policy)
            )
        return ok(self._combine(parts, items[0].subject, policy, youth=youth))

    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[VoiceTranscript]:
        """G3: whisper on an own voice note. ``text`` and ``language`` are required (§6.5)."""
        data = await asyncio.to_thread(_read, audio)
        if data is None:
            return err(_unavailable("g3", "the voice note could not be read"))
        try:
            response = await self._client.post(
                f"{self._base_url}{G3_TRANSCRIBE_PATH}",
                headers=self._headers(json_body=False),
                files={"file": (audio.name, data, "audio/ogg")},
                data={
                    "model": G3_MODEL,
                    "language": language_hint,
                    "response_format": "verbose_json",
                },
                timeout=httpx.Timeout(self._timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(_unavailable("g3", "transport", exception_type=type(exc).__name__))
        body = _json(response)
        if response.status_code != _HTTP_OK or body is None:
            return err(_unavailable("g3", "bad response", http_status=response.status_code))
        text, language = body.get("text"), body.get("language")
        if not isinstance(text, str) or not isinstance(language, str) or not language.strip():
            return err(_unavailable("g3", "text or language missing"))
        logprobs: list[float] = []
        no_speech: list[float] = []
        compression: list[float] = []
        segments = body.get("segments")
        for segment in segments if isinstance(segments, list) else []:
            if not isinstance(segment, Mapping):
                continue
            for field, readings in (
                ("avg_logprob", logprobs),
                ("no_speech_prob", no_speech),
                ("compression_ratio", compression),
            ):
                value = segment.get(field)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    readings.append(float(value))
        return ok(
            VoiceTranscript(
                text=text.strip(),
                language=language.strip().lower(),
                avg_logprob=sum(logprobs) / len(logprobs) if logprobs else None,
                no_speech_prob=max(no_speech) if no_speech else None,
                max_compression_ratio=max(compression) if compression else None,
            )
        )

    # -- G1 ---------------------------------------------------------------------
    async def _g1(
        self, items: Sequence[TextItem], *, lang_hint: str | None
    ) -> Result[dict[str, G1Reading]]:
        if self._text_route == "chat":
            return await self._g1_chat(items)
        payload: dict[str, object] = {
            "items": [{"id": item.id, "content": item.content} for item in items]
        }
        if lang_hint:
            payload["lang_hint"] = lang_hint
        body = await self._post("g1", G1_TEXT_PATH, payload)
        if is_err(body):
            return body
        readings: dict[str, G1Reading] = {}
        for result in _results(body.value):
            item_id = result.get("id")
            if not isinstance(item_id, str):
                continue
            raw = result.get("categories")
            names = tuple(str(name) for name in raw) if isinstance(raw, list) else ()
            readings[item_id] = G1Reading(
                safety=parse_g1_label(result.get("safety")), categories=names
            )
        return ok(readings)

    async def _g1_chat(self, items: Sequence[TextItem]) -> Result[dict[str, G1Reading]]:
        readings: dict[str, G1Reading] = {}
        for item in items:
            body = await self._post(
                "g1",
                G1_CHAT_PATH,
                {
                    "model": G1_CHAT_MODEL,
                    "messages": [{"role": "user", "content": item.content}],
                    "temperature": 0,
                    "max_tokens": 64,
                    "stream": False,
                },
            )
            if is_err(body):
                return body
            content = _chat_content(body.value)
            readings[item.id] = (
                parse_qwen3guard_text(content)
                if content is not None
                else G1Reading(safety=None, categories=())
            )
        return ok(readings)

    def _g1_part(self, item: TextItem, reading: G1Reading | None, policy: str) -> MediaVerdict:
        if reading is None:
            return unavailable_verdict(item.subject, model_id=self.name, policy=policy)
        decision, codes = decide_g1(reading)
        return MediaVerdict(
            decision=decision,
            categories=codes,
            scores={},
            subject=item.subject,
            model_id=self.name,
            policy_version=policy,
        )

    # -- G2 / G8 ----------------------------------------------------------------
    def _g2_parts(
        self, items: Sequence[ImageItem], body: Result[dict[str, Any]], policy: str
    ) -> list[MediaVerdict]:
        if is_err(body):
            return [unavailable_verdict(items[0].subject, model_id=self.name, policy=policy)]
        by_id = {
            result["id"]: result.get("scores")
            for result in _results(body.value)
            if isinstance(result.get("id"), str)
        }
        parts: list[MediaVerdict] = []
        for item in items:
            decision, codes, scores = decide_g2(
                by_id.get(item.id), sexual_block_p=self._sexual_block_p
            )
            parts.append(
                MediaVerdict(
                    decision=decision,
                    categories=codes,
                    scores=scores,
                    subject=item.subject,
                    model_id=self.name,
                    policy_version=policy,
                )
            )
        return parts

    def _g8_texts(
        self, items: Sequence[ImageItem], body: Result[dict[str, Any]]
    ) -> tuple[list[TextItem], set[str]]:
        """G8's strings as text items, and the ids G8 actually described."""
        if is_err(body):
            return [], set()
        by_id = {
            result["id"]: result
            for result in _results(body.value)
            if isinstance(result.get("id"), str)
        }
        texts: list[TextItem] = []
        described: set[str] = set()
        for item in items:
            result = by_id.get(item.id)
            if result is None:
                continue
            ocr, caption = result.get("ocr_text"), result.get("caption")
            if not isinstance(ocr, str) or not isinstance(caption, str):
                continue
            described.add(item.id)
            subject = text_subject_for(item.subject)
            for suffix, content in (("ocr", ocr), ("caption", caption)):
                if content.strip():
                    texts.append(
                        TextItem(id=f"{item.id}:{suffix}", subject=subject, content=content)
                    )
        return texts, described

    # -- helpers ----------------------------------------------------------------
    def _denylist_parts(self, items: Sequence[TextItem], policy: str) -> list[MediaVerdict]:
        parts: list[MediaVerdict] = []
        for item in items:
            hits = denylist_hits(item.content)
            if hits:
                _LOG.info(
                    "an L0 denylist term refused a media text",
                    extra={"subject": item.subject, "categories": [h.category.value for h in hits]},
                )
                parts.append(
                    block_verdict(
                        item.subject,
                        [hit.category for hit in hits],
                        model_id="l0_lexicon",
                        policy=policy,
                    )
                )
        return parts

    def _combine(
        self,
        parts: Sequence[MediaVerdict],
        subject: VerdictSubject,
        policy: str,
        *,
        youth: bool,
    ) -> MediaVerdict:
        verdict = combine(
            parts, fallback_subject=subject, model_id=self.name, policy=policy, youth_signal=youth
        )
        if verdict.decision is not MediaScreenDecision.ALLOW:
            _LOG.info(
                "a media guard did not allow",
                extra={
                    "decision": verdict.decision.value,
                    "subject": verdict.subject,
                    "categories": [code.value for code in verdict.categories],
                },
            )
        return verdict

    def _allow(self, subject: VerdictSubject, policy: str) -> MediaVerdict:
        return MediaVerdict(
            decision=MediaScreenDecision.ALLOW,
            categories=(),
            scores={},
            subject=subject,
            model_id=self.name,
            policy_version=policy,
        )

    async def _post(self, guard: str, path: str, payload: object) -> Result[dict[str, Any]]:
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                headers=self._headers(json_body=True),
                content=orjson.dumps(payload),
                timeout=httpx.Timeout(self._timeout_s),
            )
        except httpx.TimeoutException as exc:
            _LOG.warning("a media guard timed out", extra={"guard": guard})
            return err(_unavailable(guard, "timeout", exception_type=type(exc).__name__))
        except httpx.HTTPError as exc:
            _LOG.warning("a media guard could not be reached", extra={"guard": guard})
            return err(_unavailable(guard, "transport", exception_type=type(exc).__name__))
        if response.status_code != _HTTP_OK:
            _LOG.warning(
                "a media guard answered an error",
                extra={"guard": guard, "http_status": response.status_code},
            )
            return err(_unavailable(guard, "http error", http_status=response.status_code))
        body = _json(response)
        if body is None:
            return err(_unavailable(guard, "not a JSON object"))
        return ok(body)

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        """The key rides in a header and only there (§9.1), as for the generation calls."""
        headers = {**self._access, API_KEY_HEADER: self._api_key, "accept": "application/json"}
        if json_body:
            headers["content-type"] = "application/json"
        return headers


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = orjson.loads(response.content)
    except orjson.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def _results(body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = body.get("results")
    if not isinstance(results, list):
        return []
    return [entry for entry in results if isinstance(entry, Mapping)]


def _chat_content(body: Mapping[str, Any]) -> str | None:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return None
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None
