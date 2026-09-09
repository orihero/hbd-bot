"""The hourly balance poll: which accounts it asks, what it writes, and what it refuses to.

The probes are covered in ``test_vendor_balance_probes.py`` and the writer in
``tests/test_db/test_vendor_balances.py``. This file is about the job that joins them, and
the three decisions it owns:

**WHICH ACCOUNTS EXIST AT ALL.** A Gemini or self-hosted OpenAI-compatible gateway answers no
key-limit endpoint, so it yields no target and therefore NO ROW — not a row full of nulls.
That distinction gives an operator three states with three different remedies: an ABSENT row
means "this deployment does not poll that vendor"; a PRESENT row with ``fetched_at`` null
means "we tried and were never answered"; a present row with a stale ``fetched_at`` means
"here is the last figure, and it is N hours old". A test that only checked the happy path
would let the first collapse into the second.

**FAKE MODE WRITES NOTHING**, which is a deliberate break from the ``vendor_usage``
convention where a fake run DOES write rows stamped ``is_fake``. That works there because a
fake row records something that happened; a fabricated BALANCE records nothing, and stamping
it would still put a number on the tile an operator reads to decide whether to top up.

**A PROBE IS A CALL AND NEVER A COST.** Every probe writes one ``vendor_usage`` row with
``operation=HEALTH`` so a vendor that is down shows up in the error surface even when the
pipeline is idle — but ``cost_usd`` and ``cost_source`` stay NULL, so no probe can ever be
read as spend.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
import sqlalchemy as sa

from hbd.config import ENV_PREFIX, Settings
from hbd.contracts import BalanceUnit, Vendor, VendorOperation
from hbd.db.models.vendor_balance import VendorBalanceRow
from hbd.db.models.vendor_usage import VendorUsageRow
from hbd.errors import PipelineError
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import build_kit_worker_settings
from hbd.runtime.retention_job import RETENTION_CRON_MINUTE
from hbd.runtime.vendor_balance_job import (
    VENDOR_BALANCE_CRON_MINUTE,
    VENDOR_BALANCE_JOB_NAME,
    poll_vendor_balances,
)
from hbd.runtime.vendor_balance_probes import (
    ELEVENLABS_PROBE_NAME,
    OPENROUTER_PROBE_NAME,
    BalanceProbe,
    BalanceReading,
)

pytestmark = pytest.mark.anyio

_NOW: Final[datetime] = datetime(2026, 9, 8, 12, 43, tzinfo=UTC)
_GEMINI_BASE: Final[str] = "https://generativelanguage.googleapis.com/v1beta"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's own ``HBD_`` variables must not decide what this deployment polls."""
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'balances.db'}",
        elevenlabs_api_key="el-key",
        llm_api_key="or-key",
        **overrides,
    )


class _Probes:
    """A stand-in for the probe layer that records what it was asked and answers a script.

    The whole HTTP surface is exercised in ``test_vendor_balance_probes.py`` against a
    ``MockTransport``; substituting it here keeps this file about routing and persistence,
    and means a change to a vendor's field names cannot make a wiring test fail for an
    unrelated reason.
    """

    def __init__(self, *, openrouter_ok: bool = True, elevenlabs_ok: bool = True) -> None:
        self.openrouter_ok = openrouter_ok
        self.elevenlabs_ok = elevenlabs_ok
        #: ``(vendor, is_fallback, base_url, api_key)`` per call, in order.
        self.asked: list[tuple[Vendor, bool, str, str]] = []
        #: The management key each OpenRouter call was handed, in the same order. Recorded
        #: separately because it is not a property of the ACCOUNT the way the four above are:
        #: it names one account's management credential, and which row it reaches is the
        #: routing decision this file exists to pin.
        self.management_keys: list[str] = []

    async def openrouter(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str,
        is_fallback: bool,
        timeout_s: float,
        management_key: str = "",
    ) -> BalanceProbe:
        self.asked.append((Vendor.OPENROUTER, is_fallback, base_url, api_key))
        self.management_keys.append(management_key)
        return BalanceProbe(
            vendor=Vendor.OPENROUTER,
            is_fallback=is_fallback,
            provider=OPENROUTER_PROBE_NAME,
            balance_unit=BalanceUnit.USD,
            reading=BalanceReading(balance_remaining=12.40) if self.openrouter_ok else None,
            http_status=200 if self.openrouter_ok else 503,
            error_code=None if self.openrouter_ok else "UPSTREAM_5XX",
            latency_ms=31,
        )

    async def elevenlabs(
        self, client: httpx.AsyncClient, *, api_key: str, base_url: str, timeout_s: float
    ) -> BalanceProbe:
        self.asked.append((Vendor.ELEVENLABS, False, base_url, api_key))
        return BalanceProbe(
            vendor=Vendor.ELEVENLABS,
            is_fallback=False,
            provider=ELEVENLABS_PROBE_NAME,
            balance_unit=BalanceUnit.CHARACTERS,
            reading=BalanceReading(balance_remaining=380_000.0) if self.elevenlabs_ok else None,
            http_status=200 if self.elevenlabs_ok else 401,
            error_code=None if self.elevenlabs_ok else "CONFIG_INVALID",
            latency_ms=44,
        )


def _install(monkeypatch: pytest.MonkeyPatch, probes: _Probes) -> _Probes:
    monkeypatch.setattr(
        "hbd.runtime.vendor_balance_job.probe_openrouter", probes.openrouter, raising=True
    )
    monkeypatch.setattr(
        "hbd.runtime.vendor_balance_job.probe_elevenlabs", probes.elevenlabs, raising=True
    )
    return probes


async def _balances(container: AppContainer) -> list[VendorBalanceRow]:
    async with container.require_session_factory()() as session:
        rows = await session.scalars(
            sa.select(VendorBalanceRow).order_by(
                VendorBalanceRow.vendor, VendorBalanceRow.is_fallback
            )
        )
        return list(rows)


async def _usage(container: AppContainer) -> list[VendorUsageRow]:
    async with container.require_session_factory()() as session:
        rows = await session.scalars(
            sa.select(VendorUsageRow).order_by(VendorUsageRow.created_at, VendorUsageRow.provider)
        )
        return list(rows)


async def _container(tmp_path: Path, **overrides: Any) -> AppContainer:
    return await build_container(
        _settings(tmp_path, **overrides), data_root=tmp_path / "var", with_providers=False
    )


# ---------------------------------------------------------------------------
# The two ways the job declines to run
# ---------------------------------------------------------------------------
async def test_a_fake_run_writes_no_row_because_a_fabricated_balance_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the deliberate break from ``vendor_usage``, which DOES write ``is_fake`` rows.
    # There is no fake account and no fake credit, so the honest rendering of an offline demo
    # is the empty one.
    probes = _install(monkeypatch, _Probes())
    container = await _container(tmp_path, use_fake_providers=True)
    try:
        # Act
        summary = await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert
        assert summary == {"skipped": "fake_providers"}
        assert await _balances(container) == []
        assert probes.asked == []
    finally:
        await container.engine.dispose()


async def test_the_poll_switched_off_is_a_different_answer_from_a_fake_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — two distinct reasons, told apart on the wire, because "this deployment
    # contacts no vendor" and "this one surface is switched off" are different decisions.
    probes = _install(monkeypatch, _Probes())
    container = await _container(tmp_path, vendor_balance_poll_enabled=False)
    try:
        # Act
        summary = await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert
        assert summary == {"skipped": "poll_disabled"}
        assert await _balances(container) == []
        assert probes.asked == []
    finally:
        await container.engine.dispose()


# ---------------------------------------------------------------------------
# Which accounts get asked
# ---------------------------------------------------------------------------
async def test_a_deployment_that_is_not_on_openrouter_polls_no_openrouter_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a Gemini host. It answers no key-limit endpoint, so asking it would produce
    # a failed probe and a row of nulls, which reads as "we cannot reach OpenRouter" on a
    # deployment that does not use OpenRouter at all.
    probes = _install(monkeypatch, _Probes())
    container = await _container(tmp_path, llm_base_url=_GEMINI_BASE)
    try:
        # Act
        summary = await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — ABSENT, not null-filled.
        assert summary["polled"] == 1
        rows = await _balances(container)
        assert [row.vendor for row in rows] == [Vendor.ELEVENLABS]
        assert [asked[0] for asked in probes.asked] == [Vendor.ELEVENLABS]
    finally:
        await container.engine.dispose()


async def test_an_unset_fallback_key_produces_no_second_openrouter_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the shipped configuration: one OpenRouter account, no fallback credential.
    probes = _install(monkeypatch, _Probes())
    container = await _container(tmp_path)
    try:
        # Act
        await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert
        rows = await _balances(container)
        assert [(row.vendor, row.is_fallback) for row in rows] == [
            (Vendor.ELEVENLABS, False),
            (Vendor.OPENROUTER, False),
        ]
        assert [asked[1] for asked in probes.asked if asked[0] is Vendor.OPENROUTER] == [False]
    finally:
        await container.engine.dispose()


async def test_a_second_openrouter_credential_is_its_own_billing_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — both LLM adapters report the same vendor name, so without ``is_fallback`` the
    # two billing relationships would be one row overwriting itself once an hour.
    probes = _install(monkeypatch, _Probes())
    container = await _container(
        tmp_path, llm_fallback_api_key="or-fallback", llm_fallback_provider="gemini"
    )
    try:
        # Act
        summary = await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — the fallback inherits the PRIMARY host under the ``gemini`` fallback
        # provider, mirroring ``build_fallback_llm_provider``; deriving it differently here
        # would let the poller probe an account the pipeline never bills.
        assert summary["polled"] == 3
        rows = await _balances(container)
        assert [(row.vendor, row.is_fallback) for row in rows] == [
            (Vendor.ELEVENLABS, False),
            (Vendor.OPENROUTER, False),
            (Vendor.OPENROUTER, True),
        ]
        keys = {asked[3] for asked in probes.asked if asked[0] is Vendor.OPENROUTER}
        assert keys == {"or-key", "or-fallback"}
    finally:
        await container.engine.dispose()


async def test_the_management_key_reaches_the_primary_account_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — two OpenRouter accounts and one management credential. ``HBD_OPENROUTER_
    # MANAGEMENT_KEY`` names ONE account's management key, and nothing in the setting says
    # which, so the primary is the only row it can honestly be spent on.
    probes = _install(monkeypatch, _Probes())
    container = await _container(
        tmp_path,
        llm_fallback_api_key="or-fallback",
        llm_fallback_provider="gemini",
        openrouter_management_key="or-manage",
    )
    try:
        # Act
        await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — a pool read with the primary's credential and written under the
        # fallback's row would be the wrong account's money on the wrong chip.
        handed = {
            asked[1]: key
            for asked, key in zip(
                [a for a in probes.asked if a[0] is Vendor.OPENROUTER],
                probes.management_keys,
                strict=True,
            )
        }
        assert handed == {False: "or-manage", True: ""}
    finally:
        await container.engine.dispose()


async def test_elevenlabs_is_never_handed_a_credential_it_cannot_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the ElevenLabs probe takes no management key at all, and the target that
    # feeds it must not carry one either: a credential is only ever as safe as the number of
    # requests it can leave on.
    probes = _install(monkeypatch, _Probes())
    container = await _container(tmp_path, openrouter_management_key="or-manage")
    try:
        # Act
        await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — one OpenRouter call, and it is the only one that saw the key.
        assert len(probes.management_keys) == 1
        assert probes.management_keys == ["or-manage"]
    finally:
        await container.engine.dispose()


# ---------------------------------------------------------------------------
# What each probe writes
# ---------------------------------------------------------------------------
async def test_every_probe_writes_a_health_row_that_can_never_be_read_as_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — one vendor up, one down, so both arms of ``_record_health`` are exercised.
    _install(monkeypatch, _Probes(elevenlabs_ok=False))
    container = await _container(tmp_path)
    try:
        # Act
        await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — ``VendorOperation.HEALTH`` was declared for exactly this. The rows make a
        # vendor outage visible in the error surface even when the pipeline is idle, which
        # today it cannot be; and every one of them is unpriced, so the spend queries that
        # exclude HEALTH can never see a probe as money.
        rows = await _usage(container)
        assert len(rows) == 2
        assert {row.operation for row in rows} == {VendorOperation.HEALTH}
        assert all(row.cost_usd is None and row.cost_source is None for row in rows)
        # No ``usage_scope`` is entered, so the row honestly carries no order and no task.
        assert all(row.order_id is None and row.task is None for row in rows)
        assert {(row.vendor, row.is_success) for row in rows} == {
            (Vendor.OPENROUTER, True),
            (Vendor.ELEVENLABS, False),
        }
        assert {row.error_code for row in rows} == {None, "CONFIG_INVALID"}
    finally:
        await container.engine.dispose()


async def test_the_summary_counts_four_things_and_never_collapses_them_into_a_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _install(monkeypatch, _Probes(elevenlabs_ok=False))
    container = await _container(tmp_path)
    try:
        # Act
        summary = await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — ``estimated`` is expected to be SMALLER than ``succeeded`` under the
        # shipped rate card: that is the "needs balances" state and not a fault, and a single
        # "healthy probes" number would have hidden the difference. The summary is what arq
        # stores as the job result, so every value has to be JSON-safe.
        assert summary["polled"] == 2
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1
        assert summary["estimated"] == 0
        assert isinstance(summary["duration_ms"], int)
        assert all(
            isinstance(value, int | float | str | bool | type(None)) for value in summary.values()
        )
    finally:
        await container.engine.dispose()


async def test_a_failed_probe_still_lands_on_a_row_with_its_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — every account unreachable on the very first poll this deployment ever ran.
    _install(monkeypatch, _Probes(openrouter_ok=False, elevenlabs_ok=False))
    container = await _container(tmp_path)
    try:
        # Act
        await poll_vendor_balances({"container": container}, now=_NOW)

        # Assert — the "tried and never succeeded" state, on a row, with a reason. Not an
        # absent row (which would say this deployment does not poll them) and not a zero.
        rows = await _balances(container)
        assert len(rows) == 2
        assert all(row.fetched_at is None for row in rows)
        assert all(row.balance_remaining is None for row in rows)
        assert all(row.is_last_poll_ok is False for row in rows)
        assert all(row.consecutive_failures == 1 for row in rows)
        assert all(row.checked_at == _NOW for row in rows)
        assert {row.error_code for row in rows} == {"UPSTREAM_5XX", "CONFIG_INVALID"}
    finally:
        await container.engine.dispose()


async def test_one_vendor_failing_does_not_stop_the_next_one_being_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the first probe raises outright, which the sequential loop must survive.
    # ``asyncio.gather`` would have swallowed the second vendor's answer into the first
    # raised exception; sequential probing is why every failure is attributed to its own row.
    probes = _Probes()

    async def _explode(*args: Any, **kwargs: Any) -> BalanceProbe:
        raise RuntimeError("the probe layer fell over")

    monkeypatch.setattr("hbd.runtime.vendor_balance_job.probe_elevenlabs", _explode)
    monkeypatch.setattr("hbd.runtime.vendor_balance_job.probe_openrouter", probes.openrouter)
    container = await _container(tmp_path)
    try:
        # Act / Assert — the exception is NOT caught by the job today, so this documents the
        # actual contract: a probe that RAISES aborts the run, while a probe that FAILS is
        # data. The probes are written never to raise, which is what makes that safe.
        with pytest.raises(RuntimeError):
            await poll_vendor_balances({"container": container}, now=_NOW)
    finally:
        await container.engine.dispose()


async def test_a_context_with_no_container_is_a_wiring_bug_and_does_raise() -> None:
    # The only exception the job raises on purpose. A missing container is as true of the
    # next hour as of this one, so it must not be swallowed into a summary nobody reads.
    with pytest.raises(PipelineError):
        await poll_vendor_balances({}, now=_NOW)


# ---------------------------------------------------------------------------
# The cron entry
# ---------------------------------------------------------------------------
def test_the_poll_has_an_hourly_cron_on_a_minute_of_its_own(tmp_path: Path) -> None:
    # Arrange
    async def _dependencies() -> dict[str, Any]:
        return {}

    settings = _settings(tmp_path)

    # Act
    worker = build_kit_worker_settings(settings=settings, build_dependencies=_dependencies)

    # Assert — ``timeout`` is ``vendor_balance_job_timeout_s`` and DELIBERATELY NOT
    # ``queue_job_timeout_s``: 900 seconds is sized for a music render, and a cron holding a
    # worker slot for fifteen minutes over a hung probe would starve the job a paying
    # customer is waiting on, hourly, for ever. ``max_tries=1`` because the next hour IS the
    # retry, and a retry ladder against a rate-limited vendor endpoint is how a soft 429
    # becomes a hard block.
    entry = next(job for job in worker.cron_jobs if job.name == VENDOR_BALANCE_JOB_NAME)
    assert entry.coroutine is poll_vendor_balances
    assert entry.minute == VENDOR_BALANCE_CRON_MINUTE
    assert entry.hour is None
    assert entry.timeout_s == settings.vendor_balance_job_timeout_s
    assert entry.timeout_s != settings.queue_job_timeout_s
    assert entry.max_tries == 1
    assert entry.unique is True
    # ``run_at_startup=True`` would fire once PER REPLICA — arq's unique key derives from the
    # cron window and a startup invocation is in none — so a three-replica rolling deploy
    # would make three authenticated probes at once.
    assert entry.run_at_startup is False
    assert poll_vendor_balances in worker.functions


def test_no_two_crons_in_this_worker_contend_for_the_same_minute(tmp_path: Path) -> None:
    # Two database-writing crons in one minute is lock contention nobody planned, and it is
    # the kind of thing that is invisible until an operator is reading a slow query log.
    assert VENDOR_BALANCE_CRON_MINUTE == 43
    assert VENDOR_BALANCE_CRON_MINUTE != RETENTION_CRON_MINUTE

    async def _dependencies() -> dict[str, Any]:
        return {}

    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )
    minutes = [job.minute for job in worker.cron_jobs]
    assert len(minutes) == len(set(minutes)), minutes


def test_the_registered_name_and_the_function_have_not_drifted_apart() -> None:
    # arq dispatches by function NAME, so this is the assertion that stops a rename becoming
    # a job that never runs and raises nothing while not running.
    assert poll_vendor_balances.__name__ == VENDOR_BALANCE_JOB_NAME
