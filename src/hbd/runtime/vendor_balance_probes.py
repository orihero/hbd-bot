"""The two balance probes: pure HTTP and pure parsing, with no database anywhere in sight.

``vendor_balances`` is a cache of what a vendor last said about our account with it. This
module is the half that does the asking. It imports ``httpx``, ``hbd.contracts``,
``hbd.errors`` and the speech transport, and **deliberately not ``hbd.db``**: every branch
below is reachable from a test with a mock transport and no engine, which is the only way a
failure taxonomy this wide gets covered at all.

**THE ``SubscriptionPayload`` TRAP, NAMED SO IT IS NOT WALKED INTO.**
:class:`hbd.providers.tts.elevenlabs_api.SubscriptionPayload` already parses the very
endpoint :func:`probe_elevenlabs` calls, it sits one import away, and it looks exactly like
the right thing to reuse. It declares ``character_count: int = 0`` and ``character_limit:
int = 0``. Those defaults are CORRECT there — a partial body should read as a degraded
health verdict rather than crash one — and POISON here, because they turn a body that
omitted the field into "0 characters remaining" on the one tile an operator reads to decide
whether to top up before New Year. That is ``generation_attempts.cost_usd DEFAULT 0.0``
reinvented, except this zero reads as "stop shipping" rather than "free". So this module
parses into its own models, whose every field is optional and whose every quantity is
narrowed by hand. It DOES import ``SUBSCRIPTION_PATH`` and ``API_KEY_HEADER`` from that
module rather than re-spelling them, because that module's docstring says the endpoint
lives in one place precisely so two adapters cannot disagree about it, and a third caller
copying the literal is how they eventually do.

**EVERY PARSED FIELD IS TYPED ``Any`` AND NARROWED, WHICH IS NOT LAZINESS.** Both vendors
are actively renaming their published vocabulary — ElevenLabs is migrating from characters
toward a unified credit pool that music, TTS and STT all draw on — and a pydantic field
declared ``float | None`` turns a renamed or retyped field into a FAILED probe with a
``UPSTREAM_MALFORMED`` code somebody spends an afternoon chasing. Declared ``Any`` and
narrowed, the same change degrades to a SUCCESSFUL probe that measured nothing, which the
row records as ``fetched_at`` set with every quantity ``NULL`` and the panel renders as
"not reported". That is the honest reading, and it is why
``ck_vendor_balances_a_measured_balance_carries_its_time`` is an implication rather than a
biconditional. It is also a SILENT failure — a ``fetched_at`` that keeps advancing while
every quantity stays null looks healthy on a graph — so "polled OK, measured nothing" is
worth its own alert one day.

**OPENROUTER'S ``/api/v1/credits`` IS NOW USED, AND IT COST A FIFTH SECRET.** This module
previously refused that endpoint on the grounds that its documentation says "Management key
required", and that a management key — which can create and revoke keys and read the
account — is a credential whose compromise costs more than the spend it reports. That
refusal named its own reversal condition: *"if the prepaid figure is later judged worth a
fifth secret, that is a separate decision with its own review; it must not arrive as an
implementation detail of a dashboard tile."* **The owner has made that decision** (see
``docs/decisions/DECISIONS.md``), for a reason ``/key`` cannot serve: an uncapped inference
key reports ``limit: null``, and a panel that wants to draw REMAINING AS A FRACTION needs a
denominator that only the prepaid pool has.

The reversal is fenced rather than blanket, and every fence below is load-bearing:

* ``openrouter_management_key`` is **optional** and is NOT in
  ``REQUIRED_VENDOR_SECRET_FIELDS``. Unset, every process starts and this module behaves
  exactly as it did before — an uncapped key, no figure, ``is_unbounded=True``.
* It IS in ``VENDOR_SECRET_FIELDS``, so the admin process refuses to boot in production
  holding it. The panel that renders the number must not be able to fetch it.
* The credits call is made **only when ``/key`` reported no cap**. A capped key already has
  the denominator, and spending the dangerous credential to re-learn a number we hold is
  paying the risk twice.
* A refused or malformed credits call **degrades to the ``/key`` reading** rather than
  failing the probe. The old behaviour is the floor, so a revoked management key costs the
  ring and nothing else.

**WHAT THE OPENROUTER NUMBER MEANS, AND WHERE IT IS SILENT.** ``/key`` reports the limit on
THIS KEY, not the balance of the account. On a key with no cap set, ``limit`` and
``limit_remaining`` are both null, so :attr:`BalanceReading.balance_remaining` is ``None``
and :attr:`BalanceReading.is_unbounded` is ``True``. Those are two different unknowns and
they stay apart on purpose: ``is_unbounded=True`` with a null balance says "unknown because
uncapped", and ``is_unbounded=None`` with a null balance says "unknown because unpolled".
The first is fine and the second is a broken poller, and a tile that renders them the same
way is wrong in one of two opposite directions.

``/credits`` answers a DIFFERENT question again — the whole account's prepaid pool, shared
by every key on it — and a merged reading says so by flipping ``is_unbounded`` to ``False``:
the KEY is still uncapped, but the money behind it is finite and now measured. Which
question a row answers is therefore readable from the row: a bounded figure with an uncapped
key is the account pool, a bounded figure on a capped key is that key's own allowance.

**NEITHER PROBE RAISES, AND NEITHER INVENTS A ZERO.** Both go through
:func:`hbd.providers.tts.transport.send_request`, which already classifies a status into the
closed ``hbd.errors`` taxonomy — 401/403 to ``CONFIG_INVALID``, 402 to quota-exhausted, 5xx
to unavailable, timeouts and dropped connections to their own types. Reusing it rather than
calling ``httpx`` directly is what makes a rotated key report as a configuration error
instead of as an outage, which is a distinction ``health_from_error`` was written to
preserve and one the panel must render differently: an outage self-heals and a revoked
credential never does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict

from hbd.contracts import BalanceUnit, Err, Vendor
from hbd.errors import HbdError
from hbd.providers.tts.elevenlabs_api import API_KEY_HEADER, SUBSCRIPTION_PATH
from hbd.providers.tts.transport import http_status_of, parse_json_body, send_request

__all__ = [
    "BalanceProbe",
    "BalanceReading",
    "ELEVENLABS_PROBE_NAME",
    "OPENROUTER_CREDITS_PATH",
    "OPENROUTER_KEY_PATH",
    "OPENROUTER_LEGACY_KEY_PATH",
    "OPENROUTER_PROBE_NAME",
    "is_openrouter",
    "openrouter_probe_url",
    "probe_elevenlabs",
    "probe_openrouter",
]

#: The current documented spelling — https://openrouter.ai/docs/api-reference/limits.
OPENROUTER_KEY_PATH: Final[str] = "/key"
#: The historical spelling of the SAME endpoint. OpenRouter has published it both ways, and
#: this is the one fact about either vendor that could not be pinned to a single answer, so
#: the probe tries the current path and falls back to this one on 404 AND ONLY 404. Both
#: 404-ing is a FAILED probe carrying its error code — never a zero balance.
OPENROUTER_LEGACY_KEY_PATH: Final[str] = "/auth/key"
#: Substring that identifies an OpenRouter host. A Gemini or self-hosted OpenAI-compatible
#: gateway answers no such endpoint, and must therefore yield no probe and no row at all —
#: an ABSENT row means "this deployment does not poll that vendor", which is a different
#: operator action from a row that has never been measured.
OPENROUTER_HOST_MARKER: Final[str] = "openrouter.ai"

#: The account's prepaid pool — https://openrouter.ai/docs/api-reference/get-credits. Asked
#: with ``openrouter_management_key`` and ONLY when ``/key`` reported no cap. Unlike the two
#: key paths there is no historical spelling to fall back to: this endpoint has been
#: published one way, and inventing a ladder for it would turn a revoked management key into
#: two requests instead of one.
OPENROUTER_CREDITS_PATH: Final[str] = "/credits"

#: ``vendor_balances.provider`` — OUR short name for the probe, never the vendor's.
OPENROUTER_PROBE_NAME: Final[str] = "openrouter_key"
ELEVENLABS_PROBE_NAME: Final[str] = "elevenlabs_subscription"

#: ``HBD_LLM_BASE_URL`` ships versioned (``https://openrouter.ai/api/v1``) and OpenRouter's
#: own quickstart prints it that way, but a host-only value is just as legal. Naive
#: concatenation of one onto the other yields ``/api/v1/v1/key`` and a 404 whose HTML body
#: then defeats any attempt to read the real cause — the same trap
#: ``openai_compat._normalize_base_url`` exists for.
_VERSION_SUFFIX: Final[str] = "/v1"
_OPENROUTER_API_PREFIX: Final[str] = "/api/v1"

_STATUS_NOT_FOUND: Final[int] = 404
_MS_PER_S: Final[int] = 1000

#: Epoch seconds we are willing to read as an instant: after 1970 and before 2100. A zero,
#: a negative or a millisecond timestamp is a field we do not understand, and the honest
#: answer to a field we do not understand is ``None`` rather than a date in 1970 or 55000.
_MIN_EPOCH_S: Final[int] = 1
_MAX_EPOCH_S: Final[int] = 4_102_444_800

#: How much of a vendor's own vocabulary word we keep before the writer trims it to the
#: column. Generous, because the point here is to stop a pathological body flooding a log
#: line — the authoritative widths live on the model, and the writer applies them.
_MAX_VENDOR_TEXT: Final[int] = 200


@dataclass(frozen=True, slots=True)
class BalanceReading:
    """What one SUCCESSFUL probe measured. Every field optional, none ever defaulted to 0.

    A field is ``None`` when the vendor did not report it — which is a true statement about
    a measurement nobody has, unlike ``0``, which is a claim nobody made. The reading is a
    domain object with no column widths on it: trimming to ``vendor_balances``' string
    lengths is the writer's job, because the writer is the layer allowed to import the model
    that owns those numbers.
    """

    balance_remaining: float | None = None
    balance_total: float | None = None
    balance_used: float | None = None
    #: Three-valued on purpose — see the module docstring and the model's.
    is_unbounded: bool | None = None
    quota_resets_at: datetime | None = None
    #: A CADENCE word (``monthly``), not an instant. OpenRouter's ``limit_reset`` is a
    #: phrase, and a cadence rendered as a timestamp is a lie with a clock on it.
    quota_reset_hint: str | None = None
    plan_tier: str | None = None
    subscription_status: str | None = None


@dataclass(frozen=True, slots=True)
class BalanceProbe:
    """One attempt against one billing account, successful or not.

    ``reading is None`` IFF the attempt failed, which is what :attr:`is_success` reads. The
    failure carries whatever it can — a status when a response arrived, an error code
    always — because the row it produces must be able to say "we looked, and here is why it
    did not work", which is a different sentence from "we have never looked".
    """

    vendor: Vendor
    is_fallback: bool
    provider: str
    balance_unit: BalanceUnit
    reading: BalanceReading | None
    http_status: int | None = None
    error_code: str | None = None
    latency_ms: int | None = None

    @property
    def is_success(self) -> bool:
        return self.reading is not None


class _OpenRouterKeyData(BaseModel):
    """The ``data`` object of ``GET /api/v1/key``.

    ``label`` is DELIBERATELY ABSENT from this model. It is the operator's own free-text
    name for the API key and in practice reads like "Sardor laptop dev key" — the only field
    on either vendor's response that could carry a person's name. Not parsing it is what
    keeps ``vendor_balances``' "holds no personal data" classification true rather than
    nearly true, and it buys no tile anything.

    Every field is ``Any``: see the module docstring on why a renamed field must degrade to
    "not reported" rather than to a failed probe.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    limit: Any = None
    limit_remaining: Any = None
    limit_reset: Any = None
    usage: Any = None


class OpenRouterKeyPayload(BaseModel):
    """The envelope. OpenRouter wraps the answer in ``{"data": {...}}``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    data: _OpenRouterKeyData | None = None


class _OpenRouterCreditsData(BaseModel):
    """The ``data`` object of ``GET /api/v1/credits``.

    Two fields, both ``Any`` for the reason every other parsed field here is: this endpoint
    is reached with the account's most dangerous credential, and a renamed field must
    degrade to "the pool was not reported" rather than to a failed probe somebody debugs by
    passing that credential around.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    total_credits: Any = None
    total_usage: Any = None


class OpenRouterCreditsPayload(BaseModel):
    """The envelope. Same ``{"data": {...}}`` shape as the key endpoint."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    data: _OpenRouterCreditsData | None = None


class ElevenLabsSubscriptionPayload(BaseModel):
    """``GET /v1/user/subscription``, parsed for a BALANCE rather than for a health verdict.

    Not :class:`hbd.providers.tts.elevenlabs_api.SubscriptionPayload`, and the difference is
    the whole point: that model defaults its two character counts to ``0``. See the module
    docstring.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    character_count: Any = None
    character_limit: Any = None
    status: Any = None
    tier: Any = None
    next_character_count_reset_unix: Any = None


def _quantity(value: Any) -> float | None:
    """A number we are willing to store, or ``None``.

    ``bool`` is excluded because it is an ``int`` in Python and a vendor that answered
    ``"usage": true`` has told us nothing — the same trap ``openai_compat._token_count``
    exists for. Non-finite and negative are refused for the same reason: they are not
    measurements, and a NaN in a balance column propagates through every aggregate that
    touches it.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0.0 else None


def _bounded_text(value: Any, limit: int = _MAX_VENDOR_TEXT) -> str | None:
    """A stripped, non-empty, bounded string, or ``None``.

    An empty tier is not a tier and a whitespace status is not a status; both become
    ``None`` rather than a value that would sort and group like a real one.
    """
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:limit] if trimmed else None


def _reset_instant(value: Any) -> datetime | None:
    """An aware UTC instant from an epoch-second field, or ``None`` when it is not one."""
    seconds = _quantity(value)
    if seconds is None or not (_MIN_EPOCH_S <= seconds <= _MAX_EPOCH_S):
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def is_openrouter(base_url: str) -> bool:
    """Whether this LLM host is OpenRouter, and therefore answers a key-limit endpoint.

    Case-folded and matched against the HOST rather than the whole URL, so a self-hosted
    gateway with ``openrouter.ai`` somewhere in a path is not mistaken for the real thing.
    A bare host with no scheme is accepted too, because ``HBD_LLM_BASE_URL`` is a string
    an operator types.
    """
    parts = urlsplit(base_url if "//" in base_url else f"//{base_url}")
    return OPENROUTER_HOST_MARKER in (parts.hostname or "").casefold()


def openrouter_probe_url(base_url: str, path: str) -> str:
    """Join a configured OpenRouter host to one of the two key paths, either spelling.

    ``https://openrouter.ai/api/v1`` and ``https://openrouter.ai`` both resolve to
    ``https://openrouter.ai/api/v1/key``.
    """
    trimmed = base_url.rstrip("/")
    if trimmed.endswith(_VERSION_SUFFIX):
        return f"{trimmed}{path}"
    return f"{trimmed}{_OPENROUTER_API_PREFIX}{path}"


def _failed(
    *,
    vendor: Vendor,
    is_fallback: bool,
    provider: str,
    unit: BalanceUnit,
    error: HbdError,
    latency_ms: int,
) -> BalanceProbe:
    """A probe that could not measure. Carries why, and not one quantity."""
    return BalanceProbe(
        vendor=vendor,
        is_fallback=is_fallback,
        provider=provider,
        balance_unit=unit,
        reading=None,
        http_status=http_status_of(error),
        error_code=error.error_code.value,
        latency_ms=latency_ms,
    )


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started`` — the unit ``vendor_usage.latency_ms`` stores."""
    return int((perf_counter() - started) * _MS_PER_S)


def _openrouter_reading(payload: OpenRouterKeyPayload) -> BalanceReading:
    """Map ``data`` onto the reading. Nothing here can produce a zero from an absence.

    ``plan_tier`` is left ``None`` even though ``is_free_tier`` exists on the body: turning a
    boolean into the string ``"free_tier"`` would put OUR word into a column documented as
    holding the vendor's own tier vocabulary, and a column with two vocabularies in it is a
    column nobody can group by.
    """
    data = payload.data
    if data is None:
        return BalanceReading()
    total = _quantity(data.limit)
    used = _quantity(data.usage)
    # The two unknowns, kept apart. A number for ``limit`` means the key IS capped; no
    # number but a reported ``usage`` means the vendor answered and named no cap; neither
    # means it said nothing at all, and that is not evidence of anything.
    is_unbounded = False if total is not None else (True if used is not None else None)
    return BalanceReading(
        balance_remaining=_quantity(data.limit_remaining),
        balance_total=total,
        balance_used=used,
        is_unbounded=is_unbounded,
        quota_reset_hint=_bounded_text(data.limit_reset),
    )


def _merged_with_credits(
    reading: BalanceReading, payload: OpenRouterCreditsPayload
) -> BalanceReading:
    """Fold the account's prepaid pool into a reading that has no denominator of its own.

    Returns the reading UNCHANGED unless the pool is fully readable — both halves present,
    numeric, and a positive total. A pool of zero is a body we do not understand rather than
    an exhausted account, the same judgement ``_elevenlabs_reading`` makes about a zero
    character limit, and the same reason neither one subtracts from an absence.

    ``is_unbounded`` flips to ``False`` because it is a statement about the FIGURE this row
    now carries: there is a finite pool and we measured it. The key's own cap is still
    absent, which is exactly the thing the caller has already established before asking.
    """
    data = payload.data
    if data is None:
        return reading
    total = _quantity(data.total_credits)
    used = _quantity(data.total_usage)
    if total is None or used is None or total <= 0.0:
        return reading
    return replace(
        reading,
        balance_remaining=max(total - used, 0.0),
        balance_total=total,
        balance_used=used,
        is_unbounded=False,
    )


def _elevenlabs_reading(payload: ElevenLabsSubscriptionPayload) -> BalanceReading:
    """Map the subscription body onto the reading.

    ``balance_remaining`` is COMPUTED, and only when both halves are present and the limit
    is positive. A limit of zero is a body we do not understand rather than an exhausted
    account, and subtracting from an absent limit would produce exactly the fabricated zero
    this module exists to refuse.
    """
    used = _quantity(payload.character_count)
    total = _quantity(payload.character_limit)
    has_cap = total is not None and total > 0.0
    remaining = (
        max(total - used, 0.0) if has_cap and total is not None and used is not None else None
    )
    return BalanceReading(
        balance_remaining=remaining,
        balance_total=total,
        balance_used=used,
        # ``True`` is never inferred here: an ElevenLabs subscription always has a character
        # allowance, so an absent limit is a body we could not read, not an unlimited plan.
        is_unbounded=False if has_cap else None,
        quota_resets_at=_reset_instant(payload.next_character_count_reset_unix),
        plan_tier=_bounded_text(payload.tier),
        subscription_status=_bounded_text(payload.status),
    )


async def _openrouter_credits(
    client: httpx.AsyncClient,
    *,
    management_key: str,
    base_url: str,
    timeout_s: float,
    reading: BalanceReading,
) -> BalanceReading:
    """``GET {base}/api/v1/credits`` with the management key, or the reading untouched.

    **Every failure path here returns the reading it was given.** A refused, unreachable or
    unreadable credits call is not a failed probe: ``/key`` has already answered, and the
    row it produces is the one this module shipped before the management key existed. That
    is what keeps an unset, revoked or rotated credential a missing RING rather than a
    missing balance — and it is why this returns a reading rather than a ``Result``.
    """
    response = await send_request(
        client,
        provider=OPENROUTER_PROBE_NAME,
        method="GET",
        url=openrouter_probe_url(base_url, OPENROUTER_CREDITS_PATH),
        timeout_s=timeout_s,
        headers={"Authorization": f"Bearer {management_key}", "accept": "application/json"},
        context={"operation": "balance"},
    )
    if isinstance(response, Err):
        return reading
    parsed = parse_json_body(
        response.value,
        OpenRouterCreditsPayload,
        provider=OPENROUTER_PROBE_NAME,
        context={"operation": "balance"},
    )
    if isinstance(parsed, Err):
        return reading
    return _merged_with_credits(reading, parsed.value)


async def probe_openrouter(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    is_fallback: bool,
    timeout_s: float,
    management_key: str = "",
) -> BalanceProbe:
    """``GET {base}/api/v1/key`` with the inference key the worker already holds.

    Falls back to :data:`OPENROUTER_LEGACY_KEY_PATH` on 404 AND ONLY 404 — a 500 is a vendor
    outage and retrying it against a second path would report the outage as a missing
    endpoint. A 404 from both paths is a failed probe carrying its error code, never an
    empty reading and never a zero.

    ``management_key`` is optional and defaults to the deployment that does not hold one. It
    buys a SECOND request, to :data:`OPENROUTER_CREDITS_PATH`, and only when the key
    answered with no cap of its own — see :func:`_openrouter_credits` for why that request
    can never make the probe worse than it was without it. The latency reported is the whole
    exchange, both calls, because that is what the poller spent.
    """
    started = perf_counter()
    for index, path in enumerate((OPENROUTER_KEY_PATH, OPENROUTER_LEGACY_KEY_PATH)):
        is_last = index == 1
        response = await send_request(
            client,
            provider=OPENROUTER_PROBE_NAME,
            method="GET",
            url=openrouter_probe_url(base_url, path),
            timeout_s=timeout_s,
            headers={"Authorization": f"Bearer {api_key}", "accept": "application/json"},
            context={"operation": "balance"},
        )
        if isinstance(response, Err):
            if http_status_of(response.error) == _STATUS_NOT_FOUND and not is_last:
                continue
            return _failed(
                vendor=Vendor.OPENROUTER,
                is_fallback=is_fallback,
                provider=OPENROUTER_PROBE_NAME,
                unit=BalanceUnit.USD,
                error=response.error,
                latency_ms=_elapsed_ms(started),
            )
        parsed = parse_json_body(
            response.value,
            OpenRouterKeyPayload,
            provider=OPENROUTER_PROBE_NAME,
            context={"operation": "balance"},
        )
        if isinstance(parsed, Err):
            return _failed(
                vendor=Vendor.OPENROUTER,
                is_fallback=is_fallback,
                provider=OPENROUTER_PROBE_NAME,
                unit=BalanceUnit.USD,
                error=parsed.error,
                latency_ms=_elapsed_ms(started),
            )
        reading = _openrouter_reading(parsed.value)
        # Only an uncapped key has a missing denominator, and only a missing denominator is
        # worth spending the management credential on.
        if management_key and reading.balance_total is None:
            reading = await _openrouter_credits(
                client,
                management_key=management_key,
                base_url=base_url,
                timeout_s=timeout_s,
                reading=reading,
            )
        return BalanceProbe(
            vendor=Vendor.OPENROUTER,
            is_fallback=is_fallback,
            provider=OPENROUTER_PROBE_NAME,
            balance_unit=BalanceUnit.USD,
            reading=reading,
            http_status=response.value.status_code,
            latency_ms=_elapsed_ms(started),
        )
    raise AssertionError("the OpenRouter path ladder always returns from inside the loop")


async def probe_elevenlabs(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    timeout_s: float,
) -> BalanceProbe:
    """``GET {base}/v1/user/subscription`` — one row covers music, TTS and STT.

    That is not a simplification: ``Vendor.ELEVENLABS`` is the granularity an invoice
    arrives at, and the three adapters draw on one credit pool. The path and the auth header
    are imported from the adapter module that already owns them.
    """
    started = perf_counter()
    response = await send_request(
        client,
        provider=ELEVENLABS_PROBE_NAME,
        method="GET",
        url=f"{base_url.rstrip('/')}{SUBSCRIPTION_PATH}",
        timeout_s=timeout_s,
        headers={API_KEY_HEADER: api_key, "accept": "application/json"},
        context={"operation": "balance"},
    )
    if isinstance(response, Err):
        return _failed(
            vendor=Vendor.ELEVENLABS,
            is_fallback=False,
            provider=ELEVENLABS_PROBE_NAME,
            unit=BalanceUnit.CHARACTERS,
            error=response.error,
            latency_ms=_elapsed_ms(started),
        )
    parsed = parse_json_body(
        response.value,
        ElevenLabsSubscriptionPayload,
        provider=ELEVENLABS_PROBE_NAME,
        context={"operation": "balance"},
    )
    if isinstance(parsed, Err):
        return _failed(
            vendor=Vendor.ELEVENLABS,
            is_fallback=False,
            provider=ELEVENLABS_PROBE_NAME,
            unit=BalanceUnit.CHARACTERS,
            error=parsed.error,
            latency_ms=_elapsed_ms(started),
        )
    return BalanceProbe(
        vendor=Vendor.ELEVENLABS,
        is_fallback=False,
        provider=ELEVENLABS_PROBE_NAME,
        balance_unit=BalanceUnit.CHARACTERS,
        reading=_elevenlabs_reading(parsed.value),
        http_status=response.value.status_code,
        latency_ms=_elapsed_ms(started),
    )
