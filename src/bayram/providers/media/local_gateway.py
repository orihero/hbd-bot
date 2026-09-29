"""The owner's local generation gateway behind ``MediaGenProvider`` (IMAGE_VIDEO_SPEC §4.2).

The gateway is a FastAPI front over ComfyUI on one RTX 5090: ``POST /generate`` returns a
``job_id``, ``GET /jobs/{id}`` reports ``queued|running|done|error``, ``GET /result/{id}``
streams the file. Every rule below answers a trap recorded in
``RESEARCH-image-video-pipeline`` §1.3, and each is asserted by a test on the built request:

* **Header auth only.** The gateway also accepts ``?api_key=``; a key in a URL lands in
  every proxy and access log on the way, so no URL this adapter builds carries it.
* **Model allowlist in code.** :data:`LOCAL_MODEL_ALLOWLIST` is ``flux2`` and ``wan``. The
  gateway serves more (``zootopia``, ``storybook``, ``storybook_wan``, ``hunyuan``) and its
  schema is ``additionalProperties: true``, so the refusal has to happen here, before any
  request — a ``model`` the settings smuggled in is refused, not forwarded.
* **A closed payload.** :func:`build_generate_payload` writes a fixed set of keys and merges
  nothing, because a misspelt or extra key is silently accepted by the gateway.
* **``length``, not ``frames``.** The README documents ``frames``; the gateway honours
  ``length`` (live echoes show ``length:81`` used and ``frames:null``).
* **Explicit ``width``/``height``.** Omitted, they resolve to 1024×1024 whatever the input.
* **Base64 inputs.** One ``image`` string as a ``data:`` URL — never a Telegram file URL,
  which embeds the bot token (§3.6). Several photos are a collage first (§4.4).
* **``{status:"unknown"}`` is terminal** → :attr:`JobPhase.UNKNOWN` → attempt ``ambiguous``.
* **A 502 with no ``job_id`` is a validation failure**: non-retryable and PRE-submit, so the
  stage may fall back to another backend. A 5xx or a lost response after the body left is
  AMBIGUOUS: the job may be queued, and there is no idempotency key to make a repeat safe.
* **Never ``/interrupt``.** It kills whatever is running on the GPU, whoever owns it.
  :meth:`LocalGatewayProvider.cancel` answers ``Ok(False)`` and sends nothing.

Nothing here logs a prompt, a response body or base64 (§9.3): a validation ``detail`` can
quote the prompt back, so only its length is kept.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx
import orjson

from bayram.contracts import HealthState, ProviderHealth, Result, err, is_err, ok
from bayram.errors import (
    BayramError,
    ErrorCode,
    ProviderAmbiguousError,
    ProviderError,
    ProviderInvalidResponseError,
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
    QueuedJob,
)

__all__ = [
    "LocalGatewayProvider",
    "PROVIDER_NAME",
    "LOCAL_MODEL_ALLOWLIST",
    "MODEL_KINDS",
    "API_KEY_HEADER",
    "ACCESS_CLIENT_ID_HEADER",
    "ACCESS_CLIENT_SECRET_HEADER",
    "CLIENT_TAG",
    "DEFAULT_VIDEO_LENGTH_FRAMES",
    "DEFAULT_VIDEO_FPS",
    "GENERATE_PAYLOAD_KEYS",
    "access_headers",
    "base_url_refusal",
    "build_generate_payload",
    "encode_reference",
]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "local_genai"

#: The only models bayram may ask the gateway for (IMAGE_VIDEO_SPEC §4.2). A frozenset in
#: code, not a setting: widening it is a decision (D21, D22), not a deploy.
LOCAL_MODEL_ALLOWLIST: Final[frozenset[str]] = frozenset({"flux2", "wan"})

#: Which kind each allowlisted model renders. A ``wan`` image request is refused rather than
#: sent, because the gateway derives the mode from ``type`` + ``model`` and would try.
MODEL_KINDS: Final[Mapping[str, MediaKindName]] = {"flux2": "image", "wan": "video"}

#: The header the gateway reads. ``Authorization: Bearer`` also works; one spelling is used.
API_KEY_HEADER: Final[str] = "X-API-Key"
#: Cloudflare Access service-token headers for the tunnel in front of the gateway (§9.1 item 2).
#: Access reads them at the edge; the gateway never sees them.
ACCESS_CLIENT_ID_HEADER: Final[str] = "CF-Access-Client-Id"
ACCESS_CLIENT_SECRET_HEADER: Final[str] = "CF-Access-Client-Secret"

#: Stamped on every job so the owner's marketing scripts can see a customer job in
#: ``GET /queue`` and yield (§3.4, until gateway change G5 adds a real ``priority``).
CLIENT_TAG: Final[str] = "bayram"

#: Wan 2.2 at 16 fps: 81 frames is the 5.06 s clip the product sells (§1.3).
DEFAULT_VIDEO_LENGTH_FRAMES: Final[int] = 81
DEFAULT_VIDEO_FPS: Final[int] = 16

#: Every key :func:`build_generate_payload` can write. The operator's contract smoke
#: (``python -m bayram.tools.media doctor --contract``) diffs it against the live
#: ``/openapi.json``: the gateway accepts undeclared keys only while its schema says
#: ``additionalProperties: true``, and ``length`` and ``client`` are undeclared today (§4.2).
GENERATE_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {"type", "model", "prompt", "width", "height", "steps", "seed", "client", "image"}
    | {"denoise", "length", "fps"}
)

#: The gateway works in latent blocks; every size we configure is a multiple of 16 (§1.3).
_DIMENSION_STEP: Final[int] = 16
_MAX_DIMENSION: Final[int] = 2_048

_GENERATE_PATH: Final[str] = "/generate"
_JOBS_PATH: Final[str] = "/jobs/"
_RESULT_PATH: Final[str] = "/result/"
_QUEUE_PATH: Final[str] = "/queue"
_HEALTH_PATH: Final[str] = "/health"

DEFAULT_HEALTH_TIMEOUT_S: Final[float] = 10.0

_STATUS_PHASES: Final[Mapping[str, JobPhase]] = {
    "queued": JobPhase.QUEUED,
    "pending": JobPhase.QUEUED,
    "running": JobPhase.RUNNING,
    "done": JobPhase.SUCCEEDED,
    "error": JobPhase.FAILED,
    "unknown": JobPhase.UNKNOWN,
}

#: Leading bytes of the two formats an input may be. Our inputs are EXIF-stripped JPEGs
#: (§3.6) or a JPEG collage (§4.4); PNG is accepted because Pillow may hand one back.
_IMAGE_SIGNATURES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

_RESULT_MIMES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "video/mp4"}
)

_HTTP_OK: Final[int] = 200
_HTTP_BAD_GATEWAY: Final[int] = 502
_HTTP_CLIENT_ERROR_FLOOR: Final[int] = 400
_HTTP_SERVER_ERROR_FLOOR: Final[int] = 500
_AUTH_STATUSES: Final[frozenset[int]] = frozenset({401, 403})
#: The gateway is busy or the tunnel is shedding load: nothing was queued.
_BUSY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})

#: Transport failures raised before the request body can have reached the gateway. Anything
#: else — a read timeout, a reset mid-response — may have queued a job.
_NOT_SENT: Final[tuple[type[httpx.HTTPError], ...]] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.UnsupportedProtocol,
    httpx.LocalProtocolError,
)

_CHUNK_BYTES: Final[int] = 1 << 16


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def encode_reference(path: Path) -> Result[str]:
    """The reference photo as a ``data:`` URL, or a refusal. Reads the screened copy only.

    The format is read from the bytes, not the filename, because a mislabelled file would
    otherwise be declared as something it is not and the gateway's decoder would say so in a
    truncated 502 that tells nobody which input was wrong.
    """
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
    for signature, mime in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return ok(f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}")
    return err(
        ValidationError(
            "the reference image is neither JPEG nor PNG",
            context={"file": path.name, "size_bytes": len(data)},
        )
    )


def _refuse(message: str, **context: Any) -> Result[dict[str, Any]]:
    return err(ValidationError(message, context={SUBMIT_PHASE_KEY: PRE_SUBMIT, **context}))


def access_headers(client_id: str, client_secret: str) -> dict[str, str]:
    """The Cloudflare Access service-token headers, or none when the token is unset.

    Half a token sends nothing: boot refuses that configuration (``bayram.media.boot``), and a
    lone id would only earn a 403 at the edge that reads like a refused gateway key.
    """
    if not (client_id.strip() and client_secret.strip()):
        return {}
    return {
        ACCESS_CLIENT_ID_HEADER: client_id.strip(),
        ACCESS_CLIENT_SECRET_HEADER: client_secret.strip(),
    }


#: Hosts where plain HTTP never leaves the machine: a development gateway.
_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})


def base_url_refusal(base_url: str, *, allow_plain_http: bool = False) -> str | None:
    """Why the gateway must not be called at ``base_url``, or ``None`` (§9.1 items 2–3).

    Plain HTTP would carry the key and the customers' base64 photos unencrypted across the
    internet; the tunnel is HTTPS. Loopback is the one exception. A ``?api_key=`` in the base
    URL would ride every call and land in the tunnel's logs — the key is a header, only.
    ``allow_plain_http`` is ``media_dev_unscreened`` (dev only): it waives the scheme, never
    the ``?api_key=`` rule.
    """
    parts = urlsplit(base_url.strip())
    is_loopback_http = parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS
    if not (parts.scheme == "https" or is_loopback_http or allow_plain_http):
        return "is not an https:// URL; the gateway is reached through the tunnel, not plain HTTP"
    if "api_key" in parse_qs(parts.query):
        return "carries ?api_key=; the key is sent as a header only"
    return None


def _is_valid_dimension(value: int) -> bool:
    return 0 < value <= _MAX_DIMENSION and value % _DIMENSION_STEP == 0


def build_generate_payload(req: MediaRequest, *, image: str | None) -> Result[dict[str, Any]]:
    """The ``POST /generate`` body, built from a closed set of keys. Pure; no IO.

    ``image`` is the already-encoded ``data:`` URL (:func:`encode_reference`) or ``None``.
    Every refusal is a ``ValidationError`` classified PRE-submit: nothing was sent.
    """
    if req.model_key not in LOCAL_MODEL_ALLOWLIST:
        return _refuse("the model is not on the local allowlist", model=req.model_key)
    if MODEL_KINDS[req.model_key] != req.kind:
        return _refuse("the model does not render this kind", model=req.model_key, kind=req.kind)
    if not req.prompt.strip():
        return _refuse("the prompt is empty")
    if not (_is_valid_dimension(req.width) and _is_valid_dimension(req.height)):
        return _refuse(
            "width and height must be explicit multiples of 16",
            width=req.width,
            height=req.height,
        )
    if len(req.refs) > 1:
        return _refuse(
            "the local gateway takes one reference image; composite first",
            refs=len(req.refs),
        )
    if (image is None) != (not req.refs):
        return _refuse("the encoded image does not match the request's references")
    if req.steps <= 0:
        return _refuse("steps must be positive", steps=req.steps)

    payload: dict[str, Any] = {
        "type": req.kind,
        "model": req.model_key,
        "prompt": req.prompt,
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "seed": req.seed,
        "client": CLIENT_TAG,
    }
    if image is not None:
        payload["image"] = image

    if req.kind == "image":
        if req.length_frames is not None or req.fps is not None:
            return _refuse("an image request carries no length or fps")
        if req.denoise is not None:
            if image is None:
                return _refuse("denoise needs a reference image")
            if not 0.0 < req.denoise <= 1.0:
                return _refuse("denoise must be in (0, 1]", denoise=req.denoise)
            payload["denoise"] = req.denoise
        return ok(payload)

    if req.denoise is not None:
        return _refuse("a video request carries no denoise")
    length = DEFAULT_VIDEO_LENGTH_FRAMES if req.length_frames is None else req.length_frames
    fps = DEFAULT_VIDEO_FPS if req.fps is None else req.fps
    if length <= 0 or fps <= 0:
        return _refuse("length and fps must be positive", length=length, fps=fps)
    # ``length`` — the key the gateway honours. ``frames`` is documented and ignored.
    payload["length"] = length
    payload["fps"] = fps
    return ok(payload)


def _classified(error: ProviderError, phase: str) -> BayramError:
    return error.with_context(**{SUBMIT_PHASE_KEY: phase})


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        parsed = orjson.loads(response.content)
    except orjson.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _job_id_of(body: Mapping[str, Any] | None) -> str | None:
    if body is None:
        return None
    job_id = body.get("job_id")
    return job_id if isinstance(job_id, str) and job_id.strip() else None


class LocalGatewayProvider:
    """``MediaGenProvider`` over the owner's gateway. One outstanding job is the caller's
    business (the Redis GPU lock, §3.4); this adapter only ever makes single calls."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        access_client_id: str = "",
        access_client_secret: str = "",
        client: httpx.AsyncClient | None = None,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._access_headers = access_headers(access_client_id, access_client_secret)
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
            max_reference_images=1,
            native_audio=False,
            durations_s=(DEFAULT_VIDEO_LENGTH_FRAMES / DEFAULT_VIDEO_FPS,),
            aspects=frozenset({"9:16", "1:1", "16:9"}),
            cancel="none",
            estimate="table",
            webhook=False,
            idempotent_submit=False,
            provider_moderation=False,
            # The gateway keeps every input and output until the owner's sweeper runs (§9.2).
            output_retention_s=None,
        )

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
        """Zero cash: the GPU and its power are the owner's and are not costed (research §6)."""
        return ok(CostEstimate(usd=0.0, basis="table"))

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        """POST one job. ``webhook_url`` is ignored: the gateway has none (§4.2)."""
        image: str | None = None
        if req.refs:
            encoded = encode_reference(req.refs[0])
            if is_err(encoded):
                return err(encoded.error.with_context(**{SUBMIT_PHASE_KEY: PRE_SUBMIT}))
            image = encoded.value
        built = build_generate_payload(req, image=image)
        if is_err(built):
            return built
        payload = built.value
        context = {"model": req.model_key, "kind": req.kind, "correlation_key": correlation_key}
        try:
            response = await self._client.post(
                f"{self._base_url}{_GENERATE_PATH}",
                headers=self._headers(),
                content=orjson.dumps(payload),
                timeout=httpx.Timeout(timeout_s),
            )
        except _NOT_SENT as exc:
            return err(
                _classified(
                    ProviderUnavailableError(
                        "the gateway could not be reached; nothing was submitted",
                        provider=self.name,
                        context={**context, "exception_type": type(exc).__name__},
                        cause=exc,
                    ),
                    PRE_SUBMIT,
                )
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderAmbiguousError(
                    "the submit may have reached the gateway and no job id came back",
                    provider=self.name,
                    context={
                        **context,
                        SUBMIT_PHASE_KEY: AMBIGUOUS,
                        "exception_type": type(exc).__name__,
                    },
                    cause=exc,
                )
            )
        return self._handle_submit_response(response, req=req, context=context)

    def _handle_submit_response(
        self, response: httpx.Response, *, req: MediaRequest, context: dict[str, Any]
    ) -> Result[JobHandle]:
        status = response.status_code
        body = _json_object(response)
        job_id = _job_id_of(body)
        context = {**context, "http_status": status, "body_bytes": len(response.content)}
        if status == _HTTP_OK and job_id is not None:
            _LOG.info("media job submitted", extra={**context, "remote_id": job_id})
            return ok(
                JobHandle(
                    provider=self.name, remote_id=job_id, kind=req.kind, model_key=req.model_key
                )
            )
        if status == _HTTP_BAD_GATEWAY and job_id is None:
            # ComfyUI rejected the workflow at submit: nothing was queued (research §1.3).
            return err(
                _classified(
                    ProviderError(
                        "the gateway rejected the job at validation (502, no job id)",
                        provider=self.name,
                        code=ErrorCode.INVALID_INPUT,
                        is_retryable=False,
                        context=context,
                    ),
                    PRE_SUBMIT,
                )
            )
        if status in _AUTH_STATUSES:
            return err(
                _classified(
                    ProviderUnavailableError(
                        "the gateway refused our credentials",
                        provider=self.name,
                        is_retryable=False,
                        context=context,
                    ),
                    PRE_SUBMIT,
                )
            )
        if status in _BUSY_STATUSES:
            return err(
                _classified(
                    ProviderRateLimitedError(
                        "the gateway is busy", provider=self.name, context=context
                    ),
                    PRE_SUBMIT,
                )
            )
        if _HTTP_CLIENT_ERROR_FLOOR <= status < _HTTP_SERVER_ERROR_FLOOR:
            return err(
                _classified(
                    ProviderError(
                        "the gateway refused the request",
                        provider=self.name,
                        code=ErrorCode.INVALID_INPUT,
                        is_retryable=False,
                        context=context,
                    ),
                    PRE_SUBMIT,
                )
            )
        # A 2xx with no id, a 5xx behind the tunnel, a 502 that did carry an id: the body
        # reached the gateway and we cannot say whether a job is queued.
        return err(
            ProviderAmbiguousError(
                "the gateway's answer to a submit does not say whether a job exists",
                provider=self.name,
                context={**context, SUBMIT_PHASE_KEY: AMBIGUOUS},
            )
        )

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        """One status read. Transport errors and 5xx are retryable (the box drops off the
        network mid-render, research §1.3); the caller's deadline bounds the retries."""
        context = {"remote_id": handle.remote_id}
        try:
            response = await self._client.get(
                f"{self._base_url}{_JOBS_PATH}{handle.remote_id}",
                headers=self._headers(),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the job status could not be read",
                    provider=self.name,
                    context={**context, "exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if response.status_code != _HTTP_OK:
            return err(self._read_failure(response, context=context, operation="poll"))
        body = _json_object(response)
        raw = body.get("status") if body is not None else None
        phase = _STATUS_PHASES.get(raw.strip().lower()) if isinstance(raw, str) else None
        if phase is None:
            return err(
                ProviderInvalidResponseError(
                    "the gateway reported a status we do not know",
                    provider=self.name,
                    context={**context, "status": str(raw)[:32]},
                )
            )
        outputs = body.get("outputs") if body is not None else None
        count = len(outputs) if isinstance(outputs, list) else 0
        if phase is JobPhase.SUCCEEDED:
            count = max(count, 1)
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
        """Stream one result to ``dest`` (atomically), refusing past ``max_bytes`` (§3.6)."""
        if index < 0:
            return err(ValidationError("result index must be non-negative"))
        context: dict[str, Any] = {"remote_id": handle.remote_id, "index": index}
        partial = dest.with_name(f"{dest.name}.part")
        digest = hashlib.sha256()
        written = 0
        try:
            async with self._client.stream(
                "GET",
                f"{self._base_url}{_RESULT_PATH}{handle.remote_id}",
                params={"index": index},
                headers=self._headers(),
                timeout=httpx.Timeout(timeout_s),
            ) as response:
                if response.status_code != _HTTP_OK:
                    await response.aread()
                    return err(self._read_failure(response, context=context, operation="fetch"))
                mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if mime not in _RESULT_MIMES:
                    return err(
                        ProviderInvalidResponseError(
                            "the gateway returned a result of an unexpected type",
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
                    "the gateway returned an empty result", provider=self.name, context=context
                )
            )
        partial.replace(dest)
        return ok(
            GeneratedMedia(path=dest, mime=mime, size_bytes=written, sha256=digest.hexdigest())
        )

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        """Not cancellable. ``/interrupt`` is GLOBAL — it would kill whatever the GPU is
        rendering, somebody else's job included — so it is never called (§4.2)."""
        return ok(False)

    async def health(self) -> Result[ProviderHealth]:
        """``GET /health``. Never optimistic, never raises; a refused key is an ``Err``."""
        try:
            response = await self._client.get(
                f"{self._base_url}{_HEALTH_PATH}",
                headers=self._headers(),
                timeout=httpx.Timeout(self._health_timeout_s),
            )
        except httpx.HTTPError as exc:
            return ok(self._health(HealthState.UNAVAILABLE, detail=type(exc).__name__))
        if response.status_code in _AUTH_STATUSES:
            return err(
                ProviderUnavailableError(
                    "the gateway refused our credentials",
                    provider=self.name,
                    is_retryable=False,
                    context={"http_status": response.status_code},
                )
            )
        if response.status_code != _HTTP_OK:
            return ok(self._health(HealthState.UNAVAILABLE, detail=f"http {response.status_code}"))
        return ok(self._health(HealthState.HEALTHY))

    # -- beyond the protocol: reconciliation and backlog (§3.4, §4.2) ----------
    async def queued_job_ids(self, *, timeout_s: float) -> Result[frozenset[str]]:
        """Every job id the gateway reports running or pending, for reconciling an
        ``ambiguous`` attempt: absent → one automatic resubmit is allowed (§4.2)."""
        listed = await self.queued_jobs(timeout_s=timeout_s)
        if is_err(listed):
            return listed
        return ok(frozenset(entry.job_id for entry in listed.value))

    async def queued_jobs(self, *, timeout_s: float) -> Result[tuple[QueuedJob, ...]]:
        """``GET /queue`` as :class:`QueuedJob` entries: running first, then pending.
        :class:`~bayram.media.contracts.GatewayQueueReader`."""
        try:
            response = await self._client.get(
                f"{self._base_url}{_QUEUE_PATH}",
                headers=self._headers(),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.HTTPError as exc:
            return err(
                ProviderUnavailableError(
                    "the gateway queue could not be read",
                    provider=self.name,
                    context={"exception_type": type(exc).__name__},
                    cause=exc,
                )
            )
        if response.status_code != _HTTP_OK:
            return err(self._read_failure(response, context={}, operation="queue"))
        body = _json_object(response)
        if body is None:
            return err(
                ProviderInvalidResponseError(
                    "the gateway queue is not a JSON object", provider=self.name
                )
            )
        jobs: dict[str, QueuedJob] = {}
        for key in ("running_jobs", "pending_jobs"):
            entries = body.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                model = _text_field(entry, "model")
                client = _text_field(entry, "client")
                for job_id in _ids_in_queue_entry(entry):
                    jobs.setdefault(job_id, QueuedJob(job_id=job_id, model=model, client=client))
        return ok(tuple(jobs.values()))

    # -- internals ----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """The key rides in a header and only there (§4.2, §9.1 item 3)."""
        return {
            **self._access_headers,
            API_KEY_HEADER: self._api_key,
            "content-type": "application/json",
            "accept": "application/json",
        }

    def _read_failure(
        self, response: httpx.Response, *, context: Mapping[str, Any], operation: str
    ) -> ProviderError:
        status = response.status_code
        detail = {**context, "http_status": status, "operation": operation}
        if status in _AUTH_STATUSES:
            return ProviderUnavailableError(
                "the gateway refused our credentials",
                provider=self.name,
                is_retryable=False,
                context=detail,
            )
        if status >= _HTTP_SERVER_ERROR_FLOOR or status in _BUSY_STATUSES:
            return ProviderUnavailableError(
                "the gateway answered with a server error", provider=self.name, context=detail
            )
        return ProviderInvalidResponseError(
            "the gateway refused the read", provider=self.name, is_retryable=False, context=detail
        )

    def _health(self, state: HealthState, *, detail: str | None = None) -> ProviderHealth:
        return ProviderHealth(name=self.name, state=state, as_of=self._clock(), detail=detail)


def _text_field(entry: object, key: str) -> str | None:
    """A string field of a dict queue entry, when the gateway reports one."""
    if isinstance(entry, dict) and isinstance(value := entry.get(key), str) and value:
        return value[:64]
    return None


def _ids_in_queue_entry(entry: object) -> set[str]:
    """The gateway's queue entries are not documented; accept a bare id or a dict holding one."""
    if isinstance(entry, str):
        return {entry}
    if isinstance(entry, dict):
        return {
            value
            for key in ("job_id", "id", "prompt_id")
            if isinstance(value := entry.get(key), str)
        }
    if isinstance(entry, list):
        return {item for item in entry if isinstance(item, str)}
    return set()
