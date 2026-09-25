"""Higgsfield's REST platform behind ``MediaGenProvider`` (IMAGE_VIDEO_SPEC §4.3, D22, M6.1).

The Fast video tier, and an image backend the operator may switch to (D21's fallback). Unlike
the local gateway it **costs money per call**, and it has no idempotency key and no endpoint
that lists requests — so every rule below is about never paying twice and never paying more
than the SKU can carry (``RESEARCH-image-video-pipeline`` §3):

* **Auth is one header**, ``Authorization: Key <id>:<secret>``, sent to the API host and
  nowhere else. Upload URLs and result URLs are other hosts (a signed bucket, a CDN); they
  get the bytes or the GET, never the key.
* **A closed model table** (:data:`HIGGSFIELD_MODELS`): the model key is a setting, checked
  against it at boot and again here, and the payload is built from a fixed set of keys per
  model — never merged with anything a customer typed.
* **Silent, always.** Kling's ``sound`` defaults to on and Seedance's ``generate_audio`` to
  true; we mux our own voice (§5.6), so every video payload carries the model's off switch
  — a third of the clip's price otherwise buys audio the mux throws away.
* **``POST /estimate/<path>`` before every submit** (§4.3). The figure must be known and at
  or under the per-submit ceiling this adapter was built with, or nothing is posted. The
  per-REQUEST ceiling across variants and retries is the stage chain's (it sums what the
  earlier attempts were estimated at); this one is the last gate before money moves, so a
  caller that forgot the chain's check still cannot overspend one SKU's whole budget.
* **Our bytes, not our URLs.** A reference photo goes up through
  ``POST /files/generate-upload-url`` and a ``PUT`` to the signed URL it returns (an hour's
  life); the model is handed the resulting public URL. A Telegram file URL embeds the bot
  token and is never sent (§3.6). The estimate is asked WITHOUT the photo, so a request the
  ceiling refuses has uploaded nothing.
* **An ambiguous POST is never repeated** (R7). A read timeout, a dropped connection after
  the body left, a 5xx, a 2xx with no ``request_id`` — the job may exist and be billed, and
  there is no way to ask: :class:`~bayram.errors.ProviderAmbiguousError`, and the stage chain
  holds the job for an operator (§4.3). This adapter makes exactly one POST per ``submit``.
* **The status codes mean what the docs say they mean**: a 400 about concurrency is
  rate-limited (no ``Retry-After`` comes with it), 402 **and** 403 are the balance being gone
  (the docs say 403, the SDK 402), and a terminal ``nsfw`` status is
  :attr:`~bayram.media.contracts.JobPhase.REJECTED_CONTENT` — a moderation refusal, not
  charged by the vendor, never retried, refunded by the chain (O13).
* **The webhook is a doorbell.** Higgsfield signs nothing, so a webhook body is read for a
  request id and nothing else (:func:`webhook_request_id`); what happened is only ever
  learned from ``GET /requests/{id}/status`` with our key.
* **Geometry is measured, not assumed.** Kling has no ``resolution`` parameter and was
  measured returning 716×1284 for a 720×1280 ask; the stage chain's ffprobe normalise
  (``bayram.media.mux``) scales every fetched clip to the job's exact target size.

**The paths and body keys are from the vendor's documentation, not from a live account.**
Before a SKU is switched to this backend the operator runs one ``/estimate`` per configured
model (12-media-gateway §6.4) — a path or key the vendor does not recognise fails the
estimate, and a failed estimate refuses the submit, so a wrong guess costs a busy quote, never
money.

Nothing here logs a prompt, a response body, a URL with a signature in it, or the key.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

import httpx
import orjson

from bayram.contracts import HealthState, ProviderHealth, Result, err, is_err, ok
from bayram.errors import (
    BayramError,
    ErrorCode,
    ProviderAmbiguousError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    ValidationError,
)
from bayram.logging import get_logger
from bayram.media.contracts import (
    AMBIGUOUS,
    PRE_SUBMIT,
    SUBMIT_PHASE_KEY,
    CostEstimate,
    GeneratedMedia,
    JobHandle,
    JobPhase,
    JobStatus,
    MediaCapabilities,
    MediaKindName,
    MediaRequest,
)

__all__ = [
    "HiggsfieldProvider",
    "HiggsfieldModel",
    "PROVIDER_NAME",
    "DEFAULT_BASE_URL",
    "HIGGSFIELD_MODELS",
    "AUTH_HEADER",
    "WEBHOOK_QUERY_PARAM",
    "authorization_value",
    "aspect_ratio_of",
    "build_payload",
    "model_path",
    "webhook_request_id",
]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "higgsfield"
DEFAULT_BASE_URL: Final[str] = "https://platform.higgsfield.ai"

AUTH_HEADER: Final[str] = "Authorization"
#: The query parameter a submit names its webhook in (research §3).
WEBHOOK_QUERY_PARAM: Final[str] = "hf_webhook"

type AudioSwitch = Literal["sound", "generate_audio"]


@dataclass(frozen=True, slots=True)
class HiggsfieldModel:
    """One allowlisted endpoint pair. ``ref_path`` is ``None`` for a text-only model."""

    kind: MediaKindName
    text_path: str
    ref_path: str | None
    #: The body key the model reads its reference image URL from.
    ref_field: str | None
    #: The key that turns the model's own soundtrack off (§4.3). ``None`` only for images.
    audio_switch: AudioSwitch | None
    #: Clip lengths the model accepts, in seconds; a request is rounded to the nearest.
    durations_s: tuple[int, ...] = ()


#: The models bayram may ask Higgsfield for. A dict in code, not a setting: widening it is a
#: decision (D21, D22), and each entry carries its silence switch so none can be forgotten.
#: Kling 3.0 standard is the Fast tier's default (§4.3); its I2V takes one image, so several
#: photos are a collage first (§4.4) until M6.2 routes a multi-ref model natively.
HIGGSFIELD_MODELS: Final[Mapping[str, HiggsfieldModel]] = {
    "kling3_0_std": HiggsfieldModel(
        kind="video",
        text_path="kling-video/v3.0/std/text-to-video",
        ref_path="kling-video/v3.0/std/image-to-video",
        ref_field="image_url",
        audio_switch="sound",
        durations_s=(5, 10),
    ),
    "seedance_2_0": HiggsfieldModel(
        kind="video",
        text_path="bytedance/seedance/v2.0/text-to-video",
        ref_path="bytedance/seedance/v2.0/image-to-video",
        ref_field="image_url",
        audio_switch="generate_audio",
        durations_s=(5, 10),
    ),
    "soul_standard": HiggsfieldModel(
        kind="image",
        text_path="higgsfield-ai/soul/standard",
        ref_path=None,
        ref_field=None,
        audio_switch=None,
    ),
}

#: The three aspects the product sells (§1.3, O15), by width:height.
_ASPECTS: Final[Mapping[tuple[int, int], str]] = {(9, 16): "9:16", (1, 1): "1:1", (16, 9): "16:9"}

_STATUS_PHASES: Final[Mapping[str, JobPhase]] = {
    "queued": JobPhase.QUEUED,
    "pending": JobPhase.QUEUED,
    "in_progress": JobPhase.RUNNING,
    "running": JobPhase.RUNNING,
    "completed": JobPhase.SUCCEEDED,
    "failed": JobPhase.FAILED,
    "canceled": JobPhase.FAILED,
    "cancelled": JobPhase.FAILED,
    # Higgsfield's own moderation: terminal, not charged (research §3). Never retried.
    "nsfw": JobPhase.REJECTED_CONTENT,
}

_IMAGE_SIGNATURES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
_RESULT_MIMES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "video/mp4"}
)

_UPLOAD_URL_PATH: Final[str] = "/files/generate-upload-url"
_ESTIMATE_PREFIX: Final[str] = "/estimate/"
_REQUESTS_PATH: Final[str] = "/requests/"

_USD_FIELDS: Final[tuple[str, ...]] = ("cost_usd", "usd", "price_usd")
_CREDIT_FIELDS: Final[tuple[str, ...]] = ("credits", "cost_credits")

_HTTP_OK_FLOOR: Final[int] = 200
_HTTP_OK_CEILING: Final[int] = 300
_HTTP_BAD_REQUEST: Final[int] = 400
_HTTP_UNAUTHORIZED: Final[int] = 401
_HTTP_NOT_FOUND: Final[int] = 404
_HTTP_TOO_MANY: Final[int] = 429
_HTTP_SERVER_ERROR_FLOOR: Final[int] = 500
#: Insufficient credits: the docs say 403, the SDK README 402 (research §3). Both are quota.
_QUOTA_STATUSES: Final[frozenset[int]] = frozenset({402, 403})
#: A 400 whose detail says this is the concurrency limit, not a malformed body.
_CONCURRENCY_HINT: Final[re.Pattern[str]] = re.compile(
    r"concurren|too many|parallel|in progress", re.IGNORECASE
)

#: Transport failures raised before the request body can have left. Anything else may have
#: created — and billed — a job.
_NOT_SENT: Final[tuple[type[httpx.HTTPError], ...]] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.UnsupportedProtocol,
    httpx.LocalProtocolError,
)

_CHUNK_BYTES: Final[int] = 1 << 16
DEFAULT_HEALTH_TIMEOUT_S: Final[float] = 10.0
#: Outputs are kept about a week (research §3).
_OUTPUT_RETENTION_S: Final[int] = 7 * 86_400
_HEALTH_PROMPT: Final[str] = "a calm lake at dawn"


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def authorization_value(key_id: str, secret: str) -> str:
    """``Key <id>:<secret>`` — the one form Higgsfield's REST platform reads (§4.3)."""
    return f"Key {key_id.strip()}:{secret.strip()}"


def aspect_ratio_of(width: int, height: int) -> str | None:
    """The sold aspect a target size is, or ``None`` (§1.3). ``768×1344`` is 9:16 to within
    the latent rounding, so the ratio is compared, not reduced exactly."""
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    for (w, h), label in _ASPECTS.items():
        if math.isclose(ratio, w / h, rel_tol=0.03):
            return label
    return None


def _refuse(message: str, **context: Any) -> ValidationError:
    return ValidationError(message, context={SUBMIT_PHASE_KEY: PRE_SUBMIT, **context})


def _clip_seconds(req: MediaRequest, model: HiggsfieldModel) -> int:
    """The model's accepted length nearest the request's (81 frames at 16 fps → 5 s)."""
    frames, fps = req.length_frames, req.fps
    wanted = frames / fps if frames and fps else float(model.durations_s[0])
    return min(model.durations_s, key=lambda seconds: (abs(seconds - wanted), seconds))


def model_path(req: MediaRequest) -> Result[str]:
    """The endpoint a request is posted to — the reference path when it carries a photo."""
    model = HIGGSFIELD_MODELS.get(req.model_key)
    if model is None:
        return err(_refuse("the model is not on the Higgsfield allowlist", model=req.model_key))
    if model.kind != req.kind:
        return err(
            _refuse("the model does not render this kind", model=req.model_key, kind=req.kind)
        )
    if not req.refs:
        return ok(model.text_path)
    if model.ref_path is None:
        return err(_refuse("this model takes no reference image", model=req.model_key))
    return ok(model.ref_path)


def build_payload(req: MediaRequest, *, image_url: str | None) -> Result[dict[str, Any]]:
    """The submit body from a closed set of keys. Pure; no IO. Every refusal is PRE-submit.

    ``image_url`` is the public URL of the uploaded reference, or ``None`` — for a text
    request, and for the estimate of a reference request (the photo is not uploaded until
    the cost is known).
    """
    path = model_path(req)
    if is_err(path):
        return path
    model = HIGGSFIELD_MODELS[req.model_key]
    if not req.prompt.strip():
        return err(_refuse("the prompt is empty"))
    if len(req.refs) > 1:
        return err(
            _refuse("this model takes one reference image; composite first", refs=len(req.refs))
        )
    if image_url is not None and not req.refs:
        return err(_refuse("an image URL was given for a request with no reference"))
    aspect = aspect_ratio_of(req.width, req.height)
    if aspect is None:
        return err(
            _refuse("the target size is not a sold aspect", width=req.width, height=req.height)
        )
    payload: dict[str, Any] = {"prompt": req.prompt, "aspect_ratio": aspect}
    if image_url is not None and model.ref_field is not None:
        payload[model.ref_field] = image_url
    if req.kind == "image":
        payload["seed"] = req.seed
        return ok(payload)
    payload["duration"] = _clip_seconds(req, model)
    # §4.3: silent, always — whatever the model's default. The mux adds our voice (§5.6).
    if model.audio_switch == "sound":
        payload["sound"] = "off"
    else:
        payload["generate_audio"] = False
    return ok(payload)


def webhook_request_id(body: bytes) -> str | None:
    """The request id a webhook names, and NOTHING else from it (§4.3).

    The webhook is unsigned: anyone who learns the URL can post "completed" with a URL of
    their choosing. So its status and outputs are never read — the caller re-polls
    ``/requests/{id}/status`` with our key, and that answer is the only one believed.
    """
    try:
        parsed = orjson.loads(body)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("request_id")
    if isinstance(value, str) and 0 < len(value.strip()) <= 128:
        return value.strip()
    return None


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        parsed = orjson.loads(response.content)
    except orjson.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _text(body: Mapping[str, Any] | None, key: str) -> str | None:
    if body is None:
        return None
    value = body.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(body: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = body.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and math.isfinite(value) and value >= 0:
            return float(value)
    return None


def _output_urls(body: Mapping[str, Any]) -> list[str]:
    """``images[].url`` for an image, ``video.url`` for a video (research §3)."""
    urls: list[str] = []
    images = body.get("images")
    if isinstance(images, list):
        urls.extend(
            url
            for entry in images
            if isinstance(entry, dict) and isinstance(url := entry.get("url"), str) and url
        )
    video = body.get("video")
    if isinstance(video, dict) and isinstance(url := video.get("url"), str) and url:
        urls.append(url)
    return urls


def _is_https(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def _detail_text(body: Mapping[str, Any] | None) -> str:
    """The vendor's error words, for matching only — never logged (they can quote a prompt)."""
    if body is None:
        return ""
    detail = body.get("detail", body.get("error", body.get("message", "")))
    return str(detail)[:500]


class HiggsfieldProvider:
    """``MediaGenProvider`` over Higgsfield's REST platform. Nothing here raises."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        key_id: str,
        secret: str,
        max_submit_cost_usd: Mapping[MediaKindName, float],
        base_url: str = DEFAULT_BASE_URL,
        usd_per_credit: float | None = None,
        health_model: str = "kling3_0_std",
        client: httpx.AsyncClient | None = None,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._key_id = key_id.strip()
        self._secret = secret.strip()
        self._max_submit_cost_usd = dict(max_submit_cost_usd)
        self._base_url = base_url.rstrip("/")
        self._usd_per_credit = usd_per_credit
        self._health_model = health_model
        self._health_timeout_s = health_timeout_s
        self._clock = clock
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        """Close the HTTP client, but only the one we created."""
        if self._owns_client:
            await self._client.aclose()

    # -- MediaGenProvider ---------------------------------------------------
    def capabilities(self) -> MediaCapabilities:
        return MediaCapabilities(
            kinds=frozenset({"image", "video"}),
            # Kling 3.0 I2V takes one image (research §3); M6.2 routes multi-ref natively.
            max_reference_images=1,
            native_audio=True,
            durations_s=(5.0,),
            aspects=frozenset(_ASPECTS.values()),
            cancel="queued_only",
            estimate="exact",
            webhook=True,
            idempotent_submit=False,
            provider_moderation=True,
            output_retention_s=_OUTPUT_RETENTION_S,
        )

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
        """``POST /estimate/<path>`` with the request's body, minus the photo. Free.

        Anything short of a clear, non-negative figure is an ``Err``: an unknown cost is
        never read as zero (§4.3 "what cannot be proved is refused").
        """
        path = model_path(req)
        if is_err(path):
            return path
        built = build_payload(req, image_url=None)
        if is_err(built):
            return built
        context: dict[str, Any] = {"model": req.model_key, "operation": "estimate"}
        if not self._has_credentials():
            return err(self._no_credentials())
        try:
            response = await self._client.post(
                f"{self._base_url}{_ESTIMATE_PREFIX}{path.value}",
                headers=self._headers(),
                content=orjson.dumps(built.value),
                timeout=httpx.Timeout(self._health_timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the cost estimate could not be read",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if not _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEILING:
            return err(self._call_failure(response, context=context))
        body = _json_object(response)
        if body is None:
            return err(
                ProviderInvalidResponseError(
                    "the cost estimate is not a JSON object", provider=self.name, context=context
                )
            )
        usd = _number(body, _USD_FIELDS)
        if usd is not None:
            return ok(CostEstimate(usd=usd, basis="exact"))
        credits = _number(body, _CREDIT_FIELDS)
        if credits is not None and self._usd_per_credit is not None:
            return ok(CostEstimate(usd=credits * self._usd_per_credit, basis="exact"))
        return err(
            ProviderInvalidResponseError(
                "the cost estimate carries no figure we can convert to USD"
                + (" (BAYRAM_HIGGSFIELD_USD_PER_CREDIT is unset)" if credits is not None else ""),
                provider=self.name,
                is_retryable=False,
                context={**context, "fields": sorted(body)[:8]},
            )
        )

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        """Estimate, check the ceiling, upload the photo, POST once (§4.3).

        Everything before the POST is PRE-submit: nothing was created at the vendor, so the
        stage may fall back. The POST itself is never repeated here, whatever it answers.
        """
        path = model_path(req)
        if is_err(path):
            return path
        if webhook_url is not None and not _is_https(webhook_url):
            return err(_refuse("the webhook URL is not https"))
        context: dict[str, Any] = {
            "model": req.model_key,
            "kind": req.kind,
            "correlation_key": correlation_key,
        }
        ceiling = self._max_submit_cost_usd.get(req.kind)
        if ceiling is None:
            return err(_refuse("no cost ceiling is configured for this kind", kind=req.kind))
        estimated = await self.estimate_cost(req)
        if is_err(estimated):
            return err(_pre_submit(estimated.error))
        usd = estimated.value.usd
        if usd is None or usd > ceiling:
            # The ceiling covers every variant and retry of one request (§4.3); a single submit
            # above it can never fit, so nothing is uploaded and nothing is posted.
            return err(
                _pre_submit(
                    ProviderError(
                        "the estimated cost is above the per-submit ceiling",
                        provider=self.name,
                        code=ErrorCode.INVALID_INPUT,
                        is_retryable=False,
                        context={**context, "estimate_usd": usd, "ceiling_usd": ceiling},
                    )
                )
            )
        image_url: str | None = None
        if req.refs:
            uploaded = await self._upload(req.refs[0], timeout_s=timeout_s)
            if is_err(uploaded):
                return err(_pre_submit(uploaded.error))
            image_url = uploaded.value
        built = build_payload(req, image_url=image_url)
        if is_err(built):
            return built
        params = {WEBHOOK_QUERY_PARAM: webhook_url} if webhook_url is not None else None
        try:
            response = await self._client.post(
                f"{self._base_url}/{path.value}",
                params=params,
                headers=self._headers(),
                content=orjson.dumps(built.value),
                timeout=httpx.Timeout(timeout_s),
            )
        except _NOT_SENT as exc:
            return err(
                _pre_submit(
                    ProviderUnavailableError(
                        "Higgsfield could not be reached; nothing was submitted",
                        provider=self.name,
                        context={**context, "exception_type": type(exc).__name__},
                        cause=exc,
                    )
                )
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderAmbiguousError(
                    "the submit may have reached Higgsfield and no request id came back",
                    provider=self.name,
                    context={
                        **context,
                        SUBMIT_PHASE_KEY: AMBIGUOUS,
                        "exception_type": type(exc).__name__,
                    },
                    cause=exc,
                )
            )
        return self._handle_submit_response(response, req=req, context=context, usd=usd)

    def _handle_submit_response(
        self,
        response: httpx.Response,
        *,
        req: MediaRequest,
        context: dict[str, Any],
        usd: float,
    ) -> Result[JobHandle]:
        status = response.status_code
        body = _json_object(response)
        request_id = _text(body, "request_id")
        context = {**context, "http_status": status, "body_bytes": len(response.content)}
        if _HTTP_OK_FLOOR <= status < _HTTP_OK_CEILING and request_id is not None:
            _LOG.info(
                "media job submitted",
                extra={**context, "remote_id": request_id, "estimate_usd": usd},
            )
            return ok(
                JobHandle(
                    provider=self.name, remote_id=request_id, kind=req.kind, model_key=req.model_key
                )
            )
        if _HTTP_BAD_REQUEST <= status < _HTTP_SERVER_ERROR_FLOOR:
            # A 4xx is the vendor refusing before it queued anything.
            return err(_pre_submit(self._call_failure(response, context=context, body=body)))
        # A 2xx with no id, a 5xx: the body arrived and we cannot say whether a job — and a
        # bill — exists. Never re-posted (R7); the chain holds the job for an operator.
        return err(
            ProviderAmbiguousError(
                "Higgsfield's answer to a submit does not say whether a job exists",
                provider=self.name,
                context={**context, SUBMIT_PHASE_KEY: AMBIGUOUS},
            )
        )

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        """``GET /requests/{id}/status``. The only source of truth, webhook or not."""
        read = await self._status(handle, timeout_s=timeout_s)
        if is_err(read):
            return read
        body = read.value
        if body is None:
            # §4.1: an id the vendor does not know is terminal → attempt ``ambiguous``.
            return ok(JobStatus(phase=JobPhase.UNKNOWN, detail="request id not found"))
        raw = body.get("status")
        phase = _STATUS_PHASES.get(raw.strip().lower()) if isinstance(raw, str) else None
        if phase is None:
            return err(
                ProviderInvalidResponseError(
                    "Higgsfield reported a status we do not know",
                    provider=self.name,
                    context={"remote_id": handle.remote_id, "status": str(raw)[:32]},
                )
            )
        if phase is JobPhase.REJECTED_CONTENT:
            return ok(JobStatus(phase=phase, detail="provider moderation (nsfw)"))
        count = len(_output_urls(body)) if phase is JobPhase.SUCCEEDED else 0
        if phase is JobPhase.SUCCEEDED and count == 0:
            return err(
                ProviderInvalidResponseError(
                    "Higgsfield reported completed with no output",
                    provider=self.name,
                    context={"remote_id": handle.remote_id},
                )
            )
        return ok(JobStatus(phase=phase, output_count=count))

    async def fetch(
        self,
        handle: JobHandle,
        index: int,
        dest: Path,
        *,
        max_bytes: int,
        timeout_s: float,
    ) -> Result[GeneratedMedia]:
        """Re-read the status for the output URL, then stream it to ``dest`` (§3.6).

        The URL is read fresh every time rather than carried from the poll: a fetch re-driven
        after a restart has nothing else, and the status is the one answer signed by our key.
        The download goes WITHOUT our key — the result lives on another host.
        """
        if index < 0:
            return err(ValidationError("result index must be non-negative"))
        context: dict[str, Any] = {"remote_id": handle.remote_id, "index": index}
        read = await self._status(handle, timeout_s=timeout_s)
        if is_err(read):
            return read
        body = read.value
        urls = _output_urls(body) if body is not None else []
        status = _text(body, "status")
        if status is None or status.lower() != "completed" or index >= len(urls):
            return err(
                ProviderInvalidResponseError(
                    "Higgsfield has no such result",
                    provider=self.name,
                    is_retryable=False,
                    context={**context, "outputs": len(urls)},
                )
            )
        url = urls[index]
        if not _is_https(url):
            return err(
                ProviderInvalidResponseError(
                    "Higgsfield returned a result URL that is not https",
                    provider=self.name,
                    is_retryable=False,
                    context=context,
                )
            )
        return await self._download(
            url, dest, max_bytes=max_bytes, timeout_s=timeout_s, context=context
        )

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        """``POST /requests/{id}/cancel``: queued requests only. ``Ok(False)`` once running."""
        context = {"remote_id": handle.remote_id, "operation": "cancel"}
        try:
            response = await self._client.post(
                f"{self._base_url}{_REQUESTS_PATH}{handle.remote_id}/cancel",
                headers=self._headers(),
                timeout=httpx.Timeout(self._health_timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the cancel could not be sent",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEILING:
            return ok(True)
        if response.status_code == _HTTP_BAD_REQUEST:
            return ok(False)
        return err(self._call_failure(response, context=context))

    async def health(self) -> Result[ProviderHealth]:
        """A free ``/estimate`` for the Fast tier's model: it proves the host answers and the
        key is accepted without starting (or paying for) anything. A refused key is ``Err``."""
        if not self._has_credentials():
            return ok(self._health(HealthState.UNAVAILABLE, detail="no credentials"))
        model = HIGGSFIELD_MODELS.get(self._health_model)
        if model is None:
            return ok(self._health(HealthState.UNAVAILABLE, detail="model not allowlisted"))
        probe = MediaRequest(
            kind=model.kind,
            model_key=self._health_model,
            prompt=_HEALTH_PROMPT,
            refs=(),
            width=720,
            height=1280,
            length_frames=81,
            fps=16,
            steps=1,
            seed=0,
            denoise=None,
        )
        estimated = await self.estimate_cost(probe)
        if is_err(estimated):
            error = estimated.error
            refused = error.context.get("http_status") == _HTTP_UNAUTHORIZED
            if refused or isinstance(error, ProviderQuotaExhaustedError):
                return err(error)
            return ok(self._health(HealthState.UNAVAILABLE, detail=error.error_code.value))
        return ok(self._health(HealthState.HEALTHY))

    # -- internals ----------------------------------------------------------
    def _has_credentials(self) -> bool:
        return bool(self._key_id and self._secret)

    def _no_credentials(self) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            "the Higgsfield key id or secret is unset",
            provider=self.name,
            is_retryable=False,
            context={SUBMIT_PHASE_KEY: PRE_SUBMIT},
        )

    def _headers(self) -> dict[str, str]:
        """For the API host only. Upload and result hosts get no ``Authorization``."""
        return {
            AUTH_HEADER: authorization_value(self._key_id, self._secret),
            "content-type": "application/json",
            "accept": "application/json",
        }

    async def _status(
        self, handle: JobHandle, *, timeout_s: float
    ) -> Result[dict[str, Any] | None]:
        """The status body, ``Ok(None)`` for a 404 (an id the vendor does not know)."""
        context = {"remote_id": handle.remote_id, "operation": "status"}
        try:
            response = await self._client.get(
                f"{self._base_url}{_REQUESTS_PATH}{handle.remote_id}/status",
                headers=self._headers(),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the request status could not be read",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if response.status_code == _HTTP_NOT_FOUND:
            return ok(None)
        if not _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEILING:
            failure = self._call_failure(response, context=context)
            # A read that bounced off a busy vendor is retried by the poll chain; a 4xx that
            # is not about load will not get better.
            return err(failure)
        body = _json_object(response)
        if body is None:
            return err(
                ProviderInvalidResponseError(
                    "the request status is not a JSON object", provider=self.name, context=context
                )
            )
        return ok(body)

    async def _upload(self, path: Path, *, timeout_s: float) -> Result[str]:
        """Our screened bytes up to a signed URL; the public URL back (§4.3, §3.6)."""
        try:
            data = path.read_bytes()
        except OSError as exc:
            return err(
                ValidationError(
                    "the reference image could not be read",
                    context={"file": path.name, "detail": repr(exc)},
                    cause=exc,
                )
            )
        mime = next((m for sig, m in _IMAGE_SIGNATURES if data.startswith(sig)), None)
        if mime is None:
            return err(
                ValidationError(
                    "the reference image is neither JPEG nor PNG",
                    context={"file": path.name, "size_bytes": len(data)},
                )
            )
        context: dict[str, Any] = {"operation": "upload", "size_bytes": len(data)}
        try:
            response = await self._client.post(
                f"{self._base_url}{_UPLOAD_URL_PATH}",
                headers=self._headers(),
                content=orjson.dumps({"content_type": mime}),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "an upload URL could not be obtained",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if not _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEILING:
            return err(self._call_failure(response, context=context))
        body = _json_object(response)
        upload_url = _text(body, "upload_url")
        public_url = _text(body, "public_url")
        if (
            upload_url is None
            or public_url is None
            or not (_is_https(upload_url) and _is_https(public_url))
        ):
            return err(
                ProviderInvalidResponseError(
                    "the upload URL answer is missing an https upload_url or public_url",
                    provider=self.name,
                    context=context,
                )
            )
        try:
            put = await self._client.put(
                upload_url,
                headers={"content-type": mime},
                content=data,
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the reference image could not be uploaded",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if not _HTTP_OK_FLOOR <= put.status_code < _HTTP_OK_CEILING:
            return err(
                ProviderUnavailableError(
                    "the signed upload refused the reference image",
                    provider=self.name,
                    context={**context, "http_status": put.status_code},
                )
            )
        return ok(public_url)

    async def _download(
        self,
        url: str,
        dest: Path,
        *,
        max_bytes: int,
        timeout_s: float,
        context: dict[str, Any],
    ) -> Result[GeneratedMedia]:
        partial = dest.with_name(f"{dest.name}.part")
        digest = hashlib.sha256()
        written = 0
        try:
            async with self._client.stream(
                "GET", url, timeout=httpx.Timeout(timeout_s)
            ) as response:
                if not _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEILING:
                    await response.aread()
                    return err(
                        ProviderUnavailableError(
                            "the result could not be downloaded",
                            provider=self.name,
                            context={**context, "http_status": response.status_code},
                        )
                    )
                mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if mime not in _RESULT_MIMES:
                    return err(
                        ProviderInvalidResponseError(
                            "Higgsfield returned a result of an unexpected type",
                            provider=self.name,
                            is_retryable=False,
                            context={**context, "mime": mime[:64]},
                        )
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                with partial.open("wb") as sink:
                    async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                        written += len(chunk)
                        if written > max_bytes:
                            sink.close()
                            partial.unlink(missing_ok=True)
                            return err(
                                ProviderInvalidResponseError(
                                    "the result exceeds the size limit",
                                    provider=self.name,
                                    is_retryable=False,
                                    context={**context, "max_bytes": max_bytes},
                                )
                            )
                        digest.update(chunk)
                        sink.write(chunk)
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            return err(
                ProviderUnavailableError(
                    "the result could not be downloaded",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        except OSError as exc:
            partial.unlink(missing_ok=True)
            return err(
                ProviderError(
                    "the result could not be written to the workspace",
                    provider=self.name,
                    code=ErrorCode.STORAGE_FAILED,
                    is_retryable=True,
                    context={**context, "detail": repr(exc)},
                    cause=exc,
                )
            )
        if written == 0:
            partial.unlink(missing_ok=True)
            return err(
                ProviderInvalidResponseError(
                    "Higgsfield returned an empty result", provider=self.name, context=context
                )
            )
        partial.replace(dest)
        return ok(
            GeneratedMedia(path=dest, mime=mime, size_bytes=written, sha256=digest.hexdigest())
        )

    def _call_failure(
        self,
        response: httpx.Response,
        *,
        context: Mapping[str, Any],
        body: Mapping[str, Any] | None = None,
    ) -> ProviderError:
        """A non-2xx answer in our taxonomy (§4.1). The body is matched, never kept."""
        status = response.status_code
        detail = {**context, "http_status": status}
        if status in _QUOTA_STATUSES:
            return ProviderQuotaExhaustedError(
                "the Higgsfield balance is exhausted", provider=self.name, context=detail
            )
        if status == _HTTP_UNAUTHORIZED:
            return ProviderUnavailableError(
                "Higgsfield refused our credentials",
                provider=self.name,
                is_retryable=False,
                context=detail,
            )
        if status == _HTTP_TOO_MANY:
            return ProviderRateLimitedError(
                "Higgsfield is rate-limiting us", provider=self.name, context=detail
            )
        if status == _HTTP_BAD_REQUEST:
            words = _detail_text(body if body is not None else _json_object(response))
            if _CONCURRENCY_HINT.search(words):
                # The concurrency limit: nothing was queued, and no Retry-After comes (§4.1).
                return ProviderRateLimitedError(
                    "Higgsfield's concurrency limit is reached", provider=self.name, context=detail
                )
        if status >= _HTTP_SERVER_ERROR_FLOOR:
            return ProviderUnavailableError(
                "Higgsfield answered with a server error", provider=self.name, context=detail
            )
        return ProviderError(
            "Higgsfield refused the request",
            provider=self.name,
            code=ErrorCode.INVALID_INPUT,
            is_retryable=False,
            context=detail,
        )

    def _health(self, state: HealthState, *, detail: str | None = None) -> ProviderHealth:
        return ProviderHealth(name=self.name, state=state, as_of=self._clock(), detail=detail)


def _pre_submit(error: BayramError) -> BayramError:
    """Everything that fails before the POST: no job exists, falling back is safe (§3.3)."""
    return error.with_context(**{SUBMIT_PHASE_KEY: PRE_SUBMIT})
