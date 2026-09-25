"""The boot refusals for media (IMAGE_VIDEO_SPEC §4.5, §7.4). Configuration alone; no IO.

Called by ``bayram.main.refuse_an_unsafe_checkout_rail`` (the bot) and by the worker's
startup, before anything is built, for the reason every refusal there exists: each of these
fails silently and on the money path, and nothing else in the process would notice.

1. **Production never runs a fake media setting** — backend or moderator, offered or not.
2. **Media on a free rail needs the beta** (O9): a SKU offered on the stub or the Payme
   sandbox without ``media_beta_enabled`` and a non-empty allowlist would hand every user a
   free render. On a live-paid rail the beta flag has no effect and is warned about.
3. **Nothing is screened by the fake moderator, nothing is rendered by the fake backend**,
   whatever the environment, unless the whole process is on fakes (the test suite, the demo).
4. **Each offered SKU is sellable**: a price, a backend that is built, the gateway's address
   and key for ``local`` — the address on HTTPS (loopback excepted) with no ``?api_key=`` in
   it (§9.1) — and a margin (§4.3).
5. **The gateway models are on the allowlist** (§4.2), always — so ``zootopia`` cannot be
   configured even for a SKU that is off today and switched on tomorrow.
6. **The Cloudflare Access service token is both halves or neither** (§9.1 item 2): one
   without the other sends a header Access rejects, and every submit would fail as a
   refused credential with nothing saying which variable is missing.
7. **The guards are reachable and the legal hold can be sealed** (§6.2, §6.7): with a SKU
   offered on the ``gateway`` moderator, the guard address (``media_moderator_base_url``, or
   the gateway's) is set, on HTTPS, with the key — else every request would be ``busy``
   forever — and ``media_legal_hold_recipient`` is a valid X25519 key, else a CSAM-class
   block would leave the held bytes readable on this host.
"""

from __future__ import annotations

from typing import Final

from bayram.config import Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import ConfigError
from bayram.logging import get_logger
from bayram.media.margin import check_margin
from bayram.media.offering import (
    SKU_BACKEND_FIELDS,
    SKU_OFFERED_FIELDS,
    SKU_PRICE_FIELDS,
    env_backend,
    is_live_paid,
    offered_skus,
    sku_price_minor,
)
from bayram.moderation.factory import is_gateway_host, moderator_base_url
from bayram.moderation.legal_hold import parse_public_key
from bayram.providers.media.local_gateway import (
    LOCAL_MODEL_ALLOWLIST,
    MODEL_KINDS,
    base_url_refusal,
)

__all__ = ["refuse_unsafe_media_config", "BUILT_BACKENDS"]

_LOG = get_logger(__name__)

#: Backends with a working adapter. Higgsfield and fal arrive in M6 (§4.3); an offered SKU
#: pointed at one before then would quote a product nothing can render.
BUILT_BACKENDS: Final[frozenset[MediaBackend]] = frozenset({MediaBackend.LOCAL, MediaBackend.FAKE})


def _var(field: str) -> str:
    return f"BAYRAM_{field.upper()}"


def _refuse(message: str, **context: object) -> ConfigError:
    return ConfigError(message, context=dict(context))


def refuse_unsafe_media_config(settings: Settings) -> None:
    """Raise ``ConfigError`` naming the variable when media is unsafe to run; else return."""
    _refuse_models_off_the_allowlist(settings)
    _refuse_half_an_access_token(settings)
    _refuse_fakes_in_production(settings)
    offered = offered_skus(settings)
    if not offered:
        return
    _refuse_a_free_rail_without_the_beta(settings)
    if settings.media_moderator == "fake" and not settings.use_fake_providers:
        raise _refuse(
            "a media SKU is offered and BAYRAM_MEDIA_MODERATOR is 'fake': nothing would be "
            "screened (D24 fails closed). Set it to 'gateway', or switch the SKUs off.",
            media_moderator=settings.media_moderator,
        )
    for sku in offered:
        _refuse_an_unsellable_sku(settings, sku)
    if not settings.use_fake_providers:
        _refuse_unreachable_guards(settings)


def _refuse_unreachable_guards(settings: Settings) -> None:
    base_url = moderator_base_url(settings)
    if not is_gateway_host(settings):
        # A hosted guard endpoint (the D24 fallback) never gets the gateway's key, so it
        # needs its own — and its own Access pair is whole or absent (§6.2).
        if not settings.media_moderator_api_key.strip():
            raise _refuse(
                "a media SKU is offered and BAYRAM_MEDIA_MODERATOR_BASE_URL is on another "
                "host than the gateway, but BAYRAM_MEDIA_MODERATOR_API_KEY is unset: the "
                "gateway's own key is never sent there (IMAGE_VIDEO_SPEC §6.2).",
            )
        has_id = bool(settings.media_moderator_access_client_id.strip())
        if has_id != bool(settings.media_moderator_access_client_secret.strip()):
            raise _refuse(
                "BAYRAM_MEDIA_MODERATOR_ACCESS_CLIENT_ID and _SECRET are both set or both "
                "unset (IMAGE_VIDEO_SPEC §9.1).",
            )
    elif not base_url or not settings.genai_api_key.strip():
        raise _refuse(
            "a media SKU is offered but the guards have no address or key: set "
            "BAYRAM_MEDIA_MODERATOR_BASE_URL (or BAYRAM_GENAI_BASE_URL) and "
            "BAYRAM_GENAI_API_KEY (IMAGE_VIDEO_SPEC §6.2).",
        )
    refusal = base_url_refusal(base_url)
    if refusal is not None:
        raise _refuse(
            f"a media SKU is offered but the guard address {refusal} (IMAGE_VIDEO_SPEC §9.1).",
        )
    if parse_public_key(settings.media_legal_hold_recipient) is None:
        raise _refuse(
            "a media SKU is offered but BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT is not a base64 "
            "X25519 public key: a CSAM-class block could not be sealed to the escalation "
            "owner (IMAGE_VIDEO_SPEC §6.7). Generate one with "
            "`python -m bayram.tools.legal_hold keygen` on the owner's machine.",
        )


def _refuse_models_off_the_allowlist(settings: Settings) -> None:
    for field, kind in (("genai_image_model", "image"), ("genai_video_model", "video")):
        model = str(getattr(settings, field))
        if model not in LOCAL_MODEL_ALLOWLIST or MODEL_KINDS[model] != kind:
            raise _refuse(
                f"{_var(field)} is '{model}', which is not an allowlisted {kind} model "
                f"({', '.join(sorted(LOCAL_MODEL_ALLOWLIST))}). The gateway serves other "
                "models; bayram must never ask for them (IMAGE_VIDEO_SPEC §4.2).",
                field=field,
                model=model,
            )


def _refuse_half_an_access_token(settings: Settings) -> None:
    has_id = bool(settings.genai_access_client_id.strip())
    has_secret = bool(settings.genai_access_client_secret.strip())
    if has_id != has_secret:
        missing = "genai_access_client_secret" if has_id else "genai_access_client_id"
        raise _refuse(
            f"{_var(missing)} is unset while its other half is set; the Cloudflare Access "
            "service token is both variables or neither (IMAGE_VIDEO_SPEC §9.1).",
            missing=_var(missing),
        )


def _refuse_fakes_in_production(settings: Settings) -> None:
    if not settings.is_production:
        return
    fakes = [
        _var(field)
        for field in SKU_BACKEND_FIELDS.values()
        if str(getattr(settings, field)) == MediaBackend.FAKE.value
    ]
    if settings.media_moderator == "fake":
        fakes.append(_var("media_moderator"))
    if fakes:
        raise _refuse(
            f"production never runs a fake media setting: {', '.join(fakes)}",
            variables=fakes,
        )


def _refuse_a_free_rail_without_the_beta(settings: Settings) -> None:
    live_paid = is_live_paid(settings)
    beta_ok = settings.media_beta_enabled and len(settings.media_beta_allowlist) > 0
    if not (live_paid or beta_ok):
        raise _refuse(
            "a media SKU is offered on a free rail (the stub, or the Payme sandbox) with no "
            "beta: every user would get renders for nothing. Set BAYRAM_MEDIA_BETA_ENABLED=true "
            "and BAYRAM_MEDIA_BETA_ALLOWLIST, or switch the SKUs off until Payme production "
            "(IMAGE_VIDEO_SPEC §7.4).",
            checkout_provider=settings.checkout_provider,
            credits_enforced=settings.credits_enforced,
            payme_is_sandbox=settings.payme_is_sandbox,
            media_beta_enabled=settings.media_beta_enabled,
            allowlist_size=len(settings.media_beta_allowlist),
        )
    if live_paid and settings.media_beta_enabled:
        _LOG.warning(
            "BAYRAM_MEDIA_BETA_ENABLED has no effect on a live-paid rail; beta ended at launch",
            extra={"allowlist_size": len(settings.media_beta_allowlist)},
        )
    elif not live_paid:
        _LOG.info(
            "media is offered to the beta allowlist only",
            extra={"allowlist_size": len(settings.media_beta_allowlist)},
        )


def _refuse_an_unsellable_sku(settings: Settings, sku: MediaSku) -> None:
    offered_var = _var(SKU_OFFERED_FIELDS[sku])
    if sku_price_minor(settings, sku) is None:
        raise _refuse(
            f"{offered_var} is true but {_var(SKU_PRICE_FIELDS[sku])} is unset: an offered "
            "SKU needs a price (IMAGE_VIDEO_SPEC §7.4).",
            sku=sku.value,
        )
    backend = env_backend(settings, sku)
    backend_var = _var(SKU_BACKEND_FIELDS[sku])
    if backend is MediaBackend.FAKE and not settings.use_fake_providers:
        raise _refuse(
            f"{offered_var} is true and {backend_var} is 'fake': customers would be sold "
            "placeholder renders (IMAGE_VIDEO_SPEC §4.5).",
            sku=sku.value,
        )
    if settings.use_fake_providers:
        # Every backend is the fake here (``offering.effective_backend``); nothing to check.
        return
    if backend not in BUILT_BACKENDS:
        raise _refuse(
            f"{backend_var} is '{backend.value}', which has no adapter yet (IMAGE_VIDEO_SPEC "
            "§4.3, M6). Offer the SKU on 'local', or switch it off.",
            sku=sku.value,
            backend=backend.value,
        )
    if backend is MediaBackend.LOCAL and not (
        settings.genai_base_url.strip() and settings.genai_api_key.strip()
    ):
        raise _refuse(
            f"{offered_var} is true on the local gateway but BAYRAM_GENAI_BASE_URL or "
            "BAYRAM_GENAI_API_KEY is unset.",
            sku=sku.value,
        )
    refusal = base_url_refusal(settings.genai_base_url) if backend is MediaBackend.LOCAL else None
    if refusal is not None:
        # §9.1 items 2–3: the doctor's ``base url`` / ``key in url`` rows, made a boot refusal,
        # because nothing else stops the key and customers' photos going out unencrypted.
        raise _refuse(
            f"{offered_var} is true on the local gateway but BAYRAM_GENAI_BASE_URL {refusal} "
            "(IMAGE_VIDEO_SPEC §9.1).",
            sku=sku.value,
        )
    verdict = check_margin(settings, sku, backend)
    if not verdict.is_ok:
        raise _refuse(
            f"{offered_var} is true but the margin check fails: {verdict.reason} "
            "(IMAGE_VIDEO_SPEC §4.3).",
            sku=sku.value,
            backend=backend.value,
        )
