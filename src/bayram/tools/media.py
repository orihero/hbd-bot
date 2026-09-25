"""``python -m bayram.tools.media`` — the operator's media switches (IMAGE_VIDEO_SPEC §4.5).

The writer of the three Redis keys in :mod:`bayram.media.overrides`, and only through that
module's functions, so there is one spelling of each key and one truthiness rule for it::

    status                                  every SKU's env + effective backend, pause, GPU window
    pause  <sku>        / resume <sku>      the per-SKU kill switch (paid jobs continue)
    backend <sku> <local|higgsfield|fal|fake|env>   route NEW submits; ``env`` clears it
    reserve --minutes N / release           the GPU reserved window (O11)
    doctor [--contract] [--release]         is the local gateway fit for customers (§9.1)
    unsuspend <telegram_id>                 lift a media suspension and forget the strikes (§6.4)

``<sku>`` is ``image``, ``video_standard`` or ``video_fast``. The switches live in Redis, a
cache in this deployment: a restart without persistence clears them, so re-run ``status``
after any Redis restart (the ``bayram.payme.pause`` caveat, inherited).

``doctor`` touches no Redis and writes nothing: it asks the gateway (``bayram.tools.media_doctor``,
12-media-gateway §2.4). ``--contract`` also diffs the live ``/openapi.json`` — the spec's
``make gateway-contract``. ``--release`` is how ``bayram-release``'s verify step runs it
(§9.1 item 4): red fails the release only while an offered SKU routes to the gateway.

``unsuspend`` is the only way a CSAM-class suspension ends (§6.4): it never expires on its
own. Lift one only after the escalation owner's review of the held job (§6.7).

Exit codes: ``0`` done, ``1`` refused (bad input; nothing written), ``2`` configuration or
Redis failure (nothing written), ``3`` ``doctor`` found a failing check.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from redis.asyncio import Redis

from bayram.config import Settings, build_settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import BayramError
from bayram.logging import configure_logging
from bayram.media.offering import effective_backend, env_backend
from bayram.media.overrides import (
    MediaSwitchStore,
    read_overrides,
    set_backend_override,
    set_gpu_reserved_until,
    set_paused,
)
from bayram.moderation.strikes import RedisStrikeStore
from bayram.tools.media_doctor import run_doctor, uses_the_gateway

__all__ = ["main", "plan", "apply", "Request", "RefusedError"]

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2
EXIT_UNHEALTHY: Final[int] = 3

#: A reserved window longer than a day is a switch somebody forgot; refuse it.
_MAX_RESERVE_MINUTES: Final[int] = 24 * 60
_ENV: Final[str] = "env"


class RefusedError(Exception):
    """The operator's input was wrong. Nothing was written."""


@dataclass(frozen=True, slots=True)
class Request:
    verb: str
    sku: MediaSku | None = None
    backend: MediaBackend | None = None
    minutes: int | None = None
    contract: bool = False
    release: bool = False
    telegram_user_id: int | None = None


def _sku(raw: str) -> MediaSku:
    try:
        return MediaSku(raw.strip().lower())
    except ValueError:
        choices = ", ".join(sku.value for sku in MediaSku)
        raise RefusedError(f"unknown SKU {raw!r}; one of: {choices}") from None


def _backend(raw: str) -> MediaBackend | None:
    value = raw.strip().lower()
    if value == _ENV:
        return None
    try:
        return MediaBackend(value)
    except ValueError:
        choices = ", ".join([*(b.value for b in MediaBackend), _ENV])
        raise RefusedError(f"unknown backend {raw!r}; one of: {choices}") from None


def _minutes(raw: str) -> int:
    if not raw.strip().isdigit():
        raise RefusedError(f"--minutes must be a whole number, not {raw!r}")
    value = int(raw)
    if not 1 <= value <= _MAX_RESERVE_MINUTES:
        raise RefusedError(f"--minutes must be 1..{_MAX_RESERVE_MINUTES}")
    return value


def _telegram_id(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise RefusedError(f"'{raw}' is not a Telegram user id") from exc
    if value <= 0:
        raise RefusedError("a Telegram user id is positive")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bayram.tools.media", description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("status", help="show every SKU's backend, pause and the GPU window")
    for verb in ("pause", "resume"):
        sub.add_parser(verb, help=f"{verb} one SKU").add_argument("sku")
    backend = sub.add_parser("backend", help="route new submits for a SKU; 'env' clears")
    backend.add_argument("sku")
    backend.add_argument("backend")
    reserve = sub.add_parser("reserve", help="reserve the GPU: local SKUs refuse new orders")
    reserve.add_argument("--minutes", required=True)
    sub.add_parser("release", help="close the GPU reserved window")
    doctor = sub.add_parser("doctor", help="check the local gateway from this host (§9.1)")
    doctor.add_argument("--contract", action="store_true", help="also diff /openapi.json")
    doctor.add_argument(
        "--release",
        action="store_true",
        help="bayram-release's verify step: red fails only while a SKU uses the gateway",
    )
    sub.add_parser("unsuspend", help="lift a media suspension (§6.4)").add_argument("telegram_id")
    return parser


def plan(argv: Sequence[str]) -> Request:
    """Parse and validate. Raises :class:`RefusedError`; never touches Redis."""
    try:
        args = _parser().parse_args(list(argv))
    except SystemExit as exc:
        raise RefusedError("invalid arguments; see --help") from exc
    verb = str(args.verb)
    if verb in ("pause", "resume"):
        return Request(verb=verb, sku=_sku(args.sku))
    if verb == "backend":
        return Request(verb=verb, sku=_sku(args.sku), backend=_backend(args.backend))
    if verb == "reserve":
        return Request(verb=verb, minutes=_minutes(args.minutes))
    if verb == "doctor":
        return Request(verb=verb, contract=bool(args.contract), release=bool(args.release))
    if verb == "unsuspend":
        return Request(verb=verb, telegram_user_id=_telegram_id(args.telegram_id))
    return Request(verb=verb)


async def apply(
    store: MediaSwitchStore, settings: Settings, request: Request, *, now: datetime
) -> str:
    """Do the one write (or the read), and say what is now true."""
    if request.verb in ("pause", "resume"):
        assert request.sku is not None
        await set_paused(store, request.sku, paused=request.verb == "pause")
        return f"{request.sku.value}: {'paused' if request.verb == 'pause' else 'resumed'}"
    if request.verb == "backend":
        assert request.sku is not None
        if request.backend is MediaBackend.FAKE and not settings.use_fake_providers:
            # The worker ignores this override anyway (``offering.effective_backend``); saying
            # so here keeps an operator from believing traffic moved (§4.5).
            raise RefusedError(
                "'fake' renders placeholders and is refused outside a fake deployment; "
                "nothing was written"
            )
        await set_backend_override(store, request.sku, request.backend)
        target = request.backend.value if request.backend is not None else "the env backend"
        return f"{request.sku.value}: new submits go to {target}"
    if request.verb == "reserve":
        assert request.minutes is not None
        until = now + timedelta(minutes=request.minutes)
        await set_gpu_reserved_until(store, until)
        return f"GPU reserved until {until.isoformat()}; local SKUs refuse new orders"
    if request.verb == "release":
        await set_gpu_reserved_until(store, None)
        return "GPU reserved window closed"
    return await _status(store, settings, now=now)


async def _status(store: MediaSwitchStore, settings: Settings, *, now: datetime) -> str:
    lines: list[str] = []
    reserved_until: datetime | None = None
    for sku in MediaSku:
        overrides = await read_overrides(store, sku)
        reserved_until = overrides.gpu_reserved_until
        effective = effective_backend(settings, sku, overrides.backend)
        lines.append(
            f"{sku.value}: env={env_backend(settings, sku).value} "
            f"override={overrides.backend.value if overrides.backend else '-'} "
            f"effective={effective.value} paused={'yes' if overrides.is_paused else 'no'}"
        )
    if reserved_until is not None and reserved_until > now:
        lines.append(f"GPU reserved until {reserved_until.isoformat()}")
    else:
        lines.append("GPU not reserved")
    return "\n".join(lines)


async def _run(request: Request) -> str:
    # No vendor key is needed to flip a switch.
    settings = build_settings(require_vendor_secrets=False)
    redis: Redis[bytes] = Redis.from_url(settings.redis_url)
    try:
        if request.verb == "unsuspend":
            assert request.telegram_user_id is not None
            lifted = await RedisStrikeStore(redis).clear(request.telegram_user_id)
            state = "lifted" if lifted else "no suspension or strikes were recorded"
            return f"{request.telegram_user_id}: {state}"
        return await apply(redis, settings, request, now=datetime.now(tz=UTC))
    finally:
        await redis.aclose()  # type: ignore[attr-defined]


def _doctor(request: Request) -> int:
    # The bot's settings exactly as it boots with them, minus the song vendors' keys, which a
    # gateway check has no use for.
    settings = build_settings(require_vendor_secrets=False)
    report = asyncio.run(run_doctor(settings, contract=request.contract))
    print(report.render())
    if report.is_green:
        return EXIT_OK
    if request.release and not uses_the_gateway(settings):
        # §9.1 item 4 runs this in every release's verify step. With no offered SKU on the
        # gateway nobody can be sold a render it cannot make, so a red gateway is a warning
        # there — the release still lands, and the operator reads why.
        print("doctor: WARNING — red, but no offered SKU routes to the local gateway")
        return EXIT_OK
    return EXIT_UNHEALTHY


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises."""
    configure_logging()
    try:
        request = plan(sys.argv[1:] if argv is None else argv)
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    try:
        if request.verb == "doctor":
            return _doctor(request)
        print(asyncio.run(_run(request)))
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    except BayramError as exc:
        print(exc.operator_message)
        return EXIT_CONFIG
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
