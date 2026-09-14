"""The hourly job that asks each vendor how much credit is left, and caches the answer.

Nothing in this system has ever asked. ``subscription_health`` reads ElevenLabs'
``characters_remaining`` into a live in-memory verdict that is never persisted, and
OpenRouter is asked nothing at all, so "are we about to run out before New Year" is a
question the panel cannot answer. This job is the asker; :mod:`bayram.db.vendor_balances` is
the writer; ``bayram.db.admin.vendor_balances`` is the reader.

**THE ADMIN NEVER GAINS EGRESS, AND THIS MODULE IS WHERE THAT IS TRUE.** The panel runs as
a third process precisely so it holds no vendor key and no HTTP client (ADMIN_PANEL_PLAN
§4.2). The worker already holds both, so the worker polls and the admin selects from a table
whose numbers are already computed. A "refresh now" button is therefore not implementable as
an admin-side fetch, and the only acceptable shape for one is the one the panel already uses
for retries and re-deliveries: enqueue an ARQ job and let the worker do it. This job asks for
no new credential — see :mod:`bayram.runtime.vendor_balance_probes` on why OpenRouter's
``/api/v1/credits`` is deliberately not used — so ``Settings.VENDOR_SECRET_FIELDS`` is
unchanged by the whole feature, and that non-change is the boundary's receipt.

**WHICH ACCOUNTS ARE POLLED, AND WHICH ARE SILENTLY ABSENT.** :func:`_targets` yields
ElevenLabs when its key is set; OpenRouter-primary when the LLM key is set AND the LLM host
IS OpenRouter; OpenRouter-fallback likewise against the fallback pair. A Gemini or
self-hosted OpenAI-compatible endpoint yields NO target and therefore NO ROW — not a row full
of nulls. That distinction is why the admin read returns whatever rows exist rather than a
fixed vector, and it gives an operator three states with three different remedies: an ABSENT
row means "this deployment does not poll that vendor"; a PRESENT row with ``fetched_at``
null means "we have tried and never succeeded, and ``error_code`` says why"; a present row
with a stale ``fetched_at`` means "here is the last known figure, and it is N hours old".

**FAKE MODE WRITES NOTHING, and this is a DELIBERATE break from the ``vendor_usage``
convention.** There, a fake run DOES write rows stamped ``is_fake=True``, so a demo is
visibly excluded rather than invisible — and that works because a fake row records something
that happened. A fabricated BALANCE records nothing: there is no fake account and no fake
credit, and stamping it ``is_fake`` would still put a number on the tile an operator reads to
decide whether to top up. The honest rendering of an offline demo is the empty one.

**HOURLY, AT MINUTE 43.** A balance moves at the pace of spend and the alerting thresholds
are in DAYS of cover, so an hour of staleness cannot change a decision — and the row carries
``fetched_at``, so the age is never hidden. Daily was rejected: the SEV-1 condition is a
capability's last healthy provider hitting zero, and a day-old zero is a day of failed
customer orders. Minute 43 for the reason retention picked 17 and the snapshot picked 7 — a
scheduled job has no cause to queue behind everything else in the world, and two
database-writing crons in one minute is lock contention nobody planned.

**SEQUENTIAL PROBES, NOT ``asyncio.gather``.** Three requests. A gather would either swallow
one vendor's failure into the first raised exception or need ``return_exceptions=True`` plus
a hand-written result-splitting loop; sequential is the same code with none of that, three
timeouts sit well inside the job ceiling, and every failure is unambiguously attributed to
its own row.

**ONE CLIENT, OWNED BY THE RUN AND CLOSED BY IT.** The job builds its own
``httpx.AsyncClient`` rather than borrowing the ``ProviderSet``'s. An hourly three-request
job has no pool worth amortising, and those clients belong to the pipeline — holding a
reference would couple the poller's lifetime to ``with_providers=True``, which is not
guaranteed. Owning the client means a leaked connection cannot outlive the run.

**EVERY PROBE ALSO WRITES A ``vendor_usage`` ROW WITH ``operation=HEALTH``.** That member
was declared for exactly this: a quota probe is a real call with a real latency and a real
HTTP status, and dropping it would make the failure rate of a vendor that is down look better
than it is — but it is never priced, so ``cost_usd`` and ``cost_source`` stay ``NULL`` and a
probe can never be read as spend. The cache holds the latest state, the append-only table
holds the history under its own 400-day cutoff, and no second history table is needed. A side
benefit worth stating: the vendor-error surface now sees an outage even when the pipeline is
idle, which today it cannot.

**AND THE COST OF THAT, STATED RATHER THAN BURIED.** This adds roughly 72 ``HEALTH`` rows a
day, and ``bayram.db.admin.vendor_usage._narrow`` filters only window and vendor — so health
probes fold into ``successRate``, ``avgLatencyMs`` and the error breakdown an alert pages on,
and the unattributed-pre-order-spend query counts ``order_id IS NULL`` rows, which every
probe is. Both are open defects today and hourly probes make them materially worse. **This
job should not ship ahead of the ``_narrow`` fix** (an ``exclude_operations`` argument, plus
``AND task IS NOT NULL`` on the free-tier query), because the failure mode is a paging rule
moved by a quota endpoint hiccup, and that is worth knowing in a PR rather than at 3 a.m.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import httpx

from bayram.config import Settings
from bayram.contracts import BalanceUnit, Vendor, VendorOperation
from bayram.db.base import utc_now
from bayram.db.vendor_balances import PerSongRate, measure_per_song_rate, record_probe
from bayram.db.vendor_usage import DbUsageSink
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.providers.llm.openai_compat import DEFAULT_BASE_URL as OPENAI_DEFAULT_BASE_URL
from bayram.runtime.container import AppContainer
from bayram.runtime.vendor_balance_probes import (
    ELEVENLABS_PROBE_NAME,
    OPENROUTER_PROBE_NAME,
    BalanceProbe,
    is_openrouter,
    probe_elevenlabs,
    probe_openrouter,
)
from bayram.usage import VendorUsage

__all__ = [
    "VENDOR_BALANCE_CRON_MINUTE",
    "VENDOR_BALANCE_JOB_NAME",
    "BalancePollResult",
    "poll_vendor_balances",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name. Asserted against the function at import.
VENDOR_BALANCE_JOB_NAME: Final[str] = "poll_vendor_balances"

#: Minute past every hour. See the module docstring on why not ``:00``, and why not the
#: minutes the other two crons in this worker already occupy.
VENDOR_BALANCE_CRON_MINUTE: Final[int] = 43

#: The kit job's context key, re-stated rather than imported — importing it from ``jobs``
#: would make this module depend on the one that depends on it.
CONTAINER_CTX_KEY: Final[str] = "container"

#: What the job returns instead of a summary when it did not run at all. Two distinct
#: reasons, told apart on the wire, because "this deployment contacts no vendor" and "this
#: one surface is switched off" are different operator decisions.
_SKIPPED_FAKE: Final[str] = "fake_providers"
_SKIPPED_DISABLED: Final[str] = "poll_disabled"


@dataclass(frozen=True, slots=True)
class _Target:
    """One billing account this deployment is able to ask about.

    Built from ``Settings`` alone, before any request leaves the box — which is why
    ``provider`` and ``balance_unit`` are NOT NULL on the row while every quantity is
    nullable: the shape of an account is configuration, and only its balance is a
    measurement.
    """

    vendor: Vendor
    is_fallback: bool
    provider: str
    balance_unit: BalanceUnit
    api_key: str
    base_url: str
    #: The OpenRouter management key, when this deployment holds one. Empty everywhere else,
    #: including on the ElevenLabs target, which has no such endpoint and must never be
    #: handed a credential it cannot use. See ``Settings.openrouter_management_key``.
    management_key: str = ""


@dataclass(frozen=True, slots=True)
class BalancePollResult:
    """How one hour's poll went. Four counts, none of them collapsed into a rate.

    ``polled`` minus ``succeeded`` minus ``failed`` is always zero; ``estimated`` counts the
    rows that also got a songs-remaining figure, and it is expected to be SMALLER than
    ``succeeded`` under the shipped rate card — that is the "needs balances" state, not a
    fault, and a single "healthy probes" number would have hidden the difference.
    """

    polled: int = 0
    succeeded: int = 0
    failed: int = 0
    estimated: int = 0


def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _fallback_base_url(settings: Settings) -> str:
    """The host the fallback LLM adapter would actually call.

    Mirrors ``bayram.providers.llm.factory.build_fallback_llm_provider`` exactly: an unset
    ``llm_fallback_base_url`` means "the usual home of that adapter", which is the PRIMARY
    host for Gemini and OpenAI's own for the compatible adapter. Deriving it differently here
    would let the poller probe an account the pipeline never bills, or skip one it does.
    """
    if settings.llm_fallback_base_url:
        return settings.llm_fallback_base_url
    return (
        settings.llm_base_url
        if settings.llm_fallback_provider == "gemini"
        else (OPENAI_DEFAULT_BASE_URL)
    )


def _targets(settings: Settings) -> tuple[_Target, ...]:
    """Which accounts this deployment can ask about. An unaskable one yields NO target.

    Never a placeholder and never a row of nulls: an absent row is the honest record of a
    deployment that does not poll that vendor, and it is a different screen from a row that
    has been asked and never answered.
    """
    targets: list[_Target] = []
    if settings.elevenlabs_api_key:
        targets.append(
            _Target(
                vendor=Vendor.ELEVENLABS,
                is_fallback=False,
                provider=ELEVENLABS_PROBE_NAME,
                # One row covers music, TTS and STT — that is how the invoice arrives.
                balance_unit=BalanceUnit.CHARACTERS,
                api_key=settings.elevenlabs_api_key,
                base_url=settings.elevenlabs_base_url,
            )
        )
    if settings.llm_api_key and is_openrouter(settings.llm_base_url):
        targets.append(
            _Target(
                vendor=Vendor.OPENROUTER,
                is_fallback=False,
                provider=OPENROUTER_PROBE_NAME,
                balance_unit=BalanceUnit.USD,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                # The PRIMARY account only, and that is a correctness decision rather than a
                # cautious one. ``BAYRAM_OPENROUTER_MANAGEMENT_KEY`` names one account's
                # management credential; the fallback key below may be a SECOND OpenRouter
                # account entirely — that is the whole reason ``is_fallback`` exists — and a
                # pool read with the primary's credential and written under the fallback's
                # row is not a conservative estimate, it is the wrong account's money on the
                # wrong chip. An operator whose management key belongs to the fallback
                # account gets no ring on either row, which is the honest outcome for a
                # setting that cannot say which account it is for.
                management_key=settings.openrouter_management_key,
            )
        )
    fallback_host = _fallback_base_url(settings)
    if settings.llm_fallback_api_key and is_openrouter(fallback_host):
        targets.append(
            _Target(
                vendor=Vendor.OPENROUTER,
                # The second OpenRouter account. Both LLM adapters answer to one name, so
                # without this flag the two billing relationships are one row.
                is_fallback=True,
                provider=OPENROUTER_PROBE_NAME,
                balance_unit=BalanceUnit.USD,
                api_key=settings.llm_fallback_api_key,
                base_url=fallback_host,
            )
        )
    return tuple(targets)


async def _probe(client: httpx.AsyncClient, target: _Target, *, timeout_s: float) -> BalanceProbe:
    """Ask one account. Never raises: the probes return their failures as data."""
    if target.vendor is Vendor.ELEVENLABS:
        return await probe_elevenlabs(
            client, api_key=target.api_key, base_url=target.base_url, timeout_s=timeout_s
        )
    return await probe_openrouter(
        client,
        api_key=target.api_key,
        base_url=target.base_url,
        is_fallback=target.is_fallback,
        timeout_s=timeout_s,
        management_key=target.management_key,
    )


async def _record_health(sink: DbUsageSink, probe: BalanceProbe) -> None:
    """One append-only ``vendor_usage`` row per probe, priced at nothing.

    ``cost_usd`` and ``cost_source`` are left unset — not zero — so a probe can never be
    read as spend, and no ``usage_scope`` is entered, so the row honestly carries no order
    and no task. ``DbUsageSink.record`` cannot raise, which is what makes this safe to await
    on the failure path as well as the success one.
    """
    await sink.record(
        VendorUsage(
            vendor=probe.vendor,
            operation=VendorOperation.HEALTH,
            provider=probe.provider,
            is_success=probe.is_success,
            is_fallback=probe.is_fallback,
            http_status=probe.http_status,
            error_code=probe.error_code,
            latency_ms=probe.latency_ms,
        )
    )


async def _divisor(
    container: AppContainer, probe: BalanceProbe, *, now: datetime
) -> PerSongRate | None:
    """The measured per-song rate for this account, or ``None``. Never raises.

    A failure to measure the divisor must not lose the BALANCE, which is the number the tile
    is actually for. So it is caught here and the probe is written with all three estimate
    columns null — the same state the shipped rate card produces anyway.

    ``used_units`` and ``quota_resets_at`` come off THIS probe's reading rather than off the
    row it is about to replace, and that is the only ordering under which the credit-burn
    basis is a measurement: the stored row still holds the previous poll's numbers, so
    dividing by a denominator taken now would pair a burn figure with songs delivered after
    it was read. A failed probe carries no reading and passes neither, which lands on
    :func:`~bayram.db.vendor_balances.measure_per_song_rate`'s "nothing was measured" path —
    correctly, since a poll that did not answer measured nothing.
    """
    reading = probe.reading
    try:
        async with container.require_session_factory()() as session:
            return await measure_per_song_rate(
                session,
                vendor=probe.vendor,
                is_fallback=probe.is_fallback,
                window_days=container.settings.vendor_balance_estimate_window_days,
                now=now,
                used_units=None if reading is None else reading.balance_used,
                quota_resets_at=None if reading is None else reading.quota_resets_at,
            )
    except Exception as exc:
        _LOG.warning(
            "the songs-remaining divisor could not be measured; the balance still stands",
            extra={"vendor": probe.vendor.value, "failure": repr(exc)},
        )
        return None


async def poll_vendor_balances(
    ctx: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Ask every askable account once, record each answer, and report what happened.

    ``now`` is injectable so a test can put the trailing estimate window somewhere it can
    seed rather than waiting thirty days for one.

    Returns a JSON-safe summary. Raises only ``PipelineError`` when the worker was wired up
    wrong — every other failure is data on a row.
    """
    container = _require_container(ctx)
    settings = container.settings
    at = now or utc_now()

    if settings.use_fake_providers:
        # See the module docstring: a fabricated balance is a record of nothing, so unlike
        # ``vendor_usage`` this job writes no row at all under fakes.
        return {"skipped": _SKIPPED_FAKE}
    if not settings.vendor_balance_poll_enabled:
        return {"skipped": _SKIPPED_DISABLED}

    targets = _targets(settings)
    started = time.monotonic()
    tally = BalancePollResult()
    sink = DbUsageSink(container.require_session_factory())

    async with httpx.AsyncClient() as client:
        for target in targets:
            probe = await _probe(client, target, timeout_s=settings.vendor_balance_timeout_s)
            await _record_health(sink, probe)
            divisor = await _divisor(container, probe, now=at) if probe.is_success else None
            await record_probe(
                container.require_session_factory(), probe=probe, divisor=divisor, at=at
            )
            tally = BalancePollResult(
                polled=tally.polled + 1,
                succeeded=tally.succeeded + (1 if probe.is_success else 0),
                failed=tally.failed + (0 if probe.is_success else 1),
                estimated=tally.estimated + (1 if divisor is not None else 0),
            )

    summary: dict[str, Any] = {
        "polled": tally.polled,
        "succeeded": tally.succeeded,
        "failed": tally.failed,
        "estimated": tally.estimated,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    _LOG.info("vendor balance poll finished", extra=summary)
    return summary


assert poll_vendor_balances.__name__ == VENDOR_BALANCE_JOB_NAME, (
    "the registered name and the job function have drifted apart; ARQ would never dispatch"
)
