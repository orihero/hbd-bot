"""The stale-debit sweep's host, and the grace it runs on.

Two things are asserted here that no unit test of the sweep itself can reach.

**That it is actually hosted.** ``settle_stale_debits`` composes into ``purge_expired``,
which the hourly ``cron`` in :mod:`hbd.runtime.jobs` fires — so the proof that a debit gets
closed in production is a proof that runs the real cron entry point against a real container
and looks at the balance afterwards, not one that calls the sweep directly. Before this, the
in-flight cutoff and ``jobs._settle`` both pointed at a sweep with no caller.

**That the grace is derived rather than chosen.** A fixed hour — the literal this work
replaced — is SHORTER than the 4500 seconds of job timeouts arq alone will spend on one
order under the shipped defaults, which would have let the sweep refund orders that were
still rendering. The derivation is in ``hbd.entitlements`` (a leaf module that may not import
``hbd.config``), so the numbers it restates are pinned against the real ``Settings`` here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from hbd.config import ENV_PREFIX, Settings
from hbd.contracts import OrderState, is_ok
from hbd.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    derive_settlement_grace_s,
    resolve_entitlement_policy,
)
from hbd.runtime.broadcast_job import (
    EXPAND_JOB_NAME,
    SEND_JOB_NAME,
    TEST_SEND_JOB_NAME,
    sweep_due_broadcasts,
)
from hbd.runtime.container import build_container
from hbd.runtime.jobs import build_kit_worker_settings
from hbd.runtime.retention_job import run_retention_sweep
from tests.test_db.conftest import new_order

_USER: Final[int] = 6_100_000_000_001
_DATABASE_URL: Final[str] = "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's own ``HBD_`` variables must not decide what the shipped default is."""
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cron.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
        **overrides,
    )


# ---------------------------------------------------------------------------
# The host
# ---------------------------------------------------------------------------
async def test_the_worker_cron_is_what_finally_closes_a_debit_nobody_settled(
    tmp_path: Path,
) -> None:
    # Arrange — a real container, a real order that died terminally, and a real debit left
    # open because its job never came back to settle it. Everything from here is the code
    # the cron runs, unmocked.
    #
    # The allowance is set explicitly rather than inherited, because the SHIPPED value is now
    # 0 — every recording is sold — and this test is not about the allowance. With 0 the
    # account cannot afford the charge at all, the dark meter covers it with an
    # ``unenforced_render`` grant, and the numbers below would be measuring that cover rather
    # than the sweep. Three credits is the arrangement this test has always run on; it is
    # named here instead of assumed.
    container = await build_container(
        _settings(tmp_path, free_allowance_credits=3),
        data_root=tmp_path / "var",
        with_providers=False,
    )
    try:
        credits = container.credits
        assert credits is not None
        order = new_order(state=OrderState.FAILED, telegram_user_id=_USER)
        created = await container.repository.create_order(order)
        assert is_ok(created), created
        charged = await credits.charge(telegram_user_id=_USER, order_id=order.id, actor="pipeline")
        assert is_ok(charged), charged
        spent = await credits.balance_for(_USER)
        assert is_ok(spent) and spent.value.credits == 2

        # Act — the cron's own entry point, with the context arq hands it. The clock is
        # moved past the settlement grace first: the sweep now needs the ORDERS ROW to have
        # been quiet that long too, because a FAILED row means "the last attempt failed",
        # not "the job is gone" (``orchestrator._fail`` writes it on retryable failures).
        ctx: dict[str, Any] = {"container": container}
        long_after = datetime.now(UTC) + timedelta(
            seconds=DEFAULT_ENTITLEMENT_POLICY.settlement_grace_s + 60
        )
        summary = await run_retention_sweep(ctx, now=long_after)

        # Assert — the credit is back and the run says so. ``rows_affected`` is what the
        # retention job logs and the panel renders, so a run that only settled debits must
        # not read as a run that did nothing.
        restored = await credits.balance_for(_USER)
        assert is_ok(restored), restored
        assert restored.value.credits == 3
        assert summary["rows_affected"] == 1
        assert summary["error"] is None
    finally:
        await container.engine.dispose()


def test_the_sweep_has_a_cron_to_run_on_at_all(tmp_path: Path) -> None:
    # Arrange — ``purge_expired`` hosts the sweep, and this entry is what fires
    # ``purge_expired``. Without it the whole chain is dead code, which is precisely what it
    # was: ``cron_jobs`` did not exist and nothing called the purge.
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert — deliberately a membership check, not an equality one: this asserts the sweep
    # has a host, and says nothing about what else the worker schedules alongside it.
    assert run_retention_sweep in [job.coroutine for job in worker.cron_jobs]


def test_the_broadcast_due_sweep_has_a_cron_to_run_on_at_all(tmp_path: Path) -> None:
    # Arrange — the same assertion as above, for the job that has the most to lose from not
    # being scheduled. The broadcast sweep is the ONLY thing that starts a campaign an
    # operator scheduled for a future instant (the panel deliberately enqueues nothing for
    # one) and the only thing that revives a chunk job a deploy cancelled mid-send. Without
    # this entry both of those fail silently: a scheduled campaign simply never goes out, and
    # a half-sent one sits at ``sending`` with rows claimed forever.
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert — hosted, and registered in ``functions`` as well: arq dispatches a cron by
    # NAME, so a schedule whose function is absent from that list has nothing behind it.
    assert sweep_due_broadcasts in [job.coroutine for job in worker.cron_jobs]
    assert sweep_due_broadcasts in worker.functions
    # The three jobs the PANEL enqueues are registered too. Nothing else in this repository
    # calls them, so a missing entry here would be a route that answers 200 with a job id
    # that no process will ever run.
    registered = {getattr(fn, "name", getattr(fn, "__name__", "")) for fn in worker.functions}
    assert {EXPAND_JOB_NAME, SEND_JOB_NAME, TEST_SEND_JOB_NAME} <= registered


# ---------------------------------------------------------------------------
# The grace
# ---------------------------------------------------------------------------
def test_the_shipped_queue_defaults_derive_the_shipped_grace() -> None:
    # Arrange — the drift guard between ``hbd.config`` and the queue numbers
    # ``hbd.entitlements`` has to restate because it is a leaf and may not import config.
    # ``database_url`` is the model's own required field and has nothing to do with the
    # grace: everything the derivation reads is defaulted, so this construction is the
    # assertion that the new setting did not make the shipped configuration invalid.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL)

    # Act
    resolved = resolve_entitlement_policy(settings)

    # Assert — every number matches the shipped default except TWO, and both exceptions are
    # the point rather than an inconvenience. ``is_balance_enforced`` mirrors
    # ``credits_enforced``, which ships False; ``allowance_credits`` mirrors
    # ``free_allowance_credits``, which ships 0 because the free half of the product is the
    # lyric and every recording is sold. The default policy — used wherever no settings
    # object is in hand: the data layer's own tests, the sweep's fallback, the admin panel —
    # keeps enforcing and keeps its 3. Both are threaded from ``settings`` rather than
    # hardcoded, so this stays a drift guard between config and policy and does not turn into
    # a restatement of two literals.
    assert settings.settlement_grace_s is None
    assert not resolved.is_balance_enforced
    assert not settings.credits_enforced
    assert resolved == replace(
        DEFAULT_ENTITLEMENT_POLICY,
        is_balance_enforced=settings.credits_enforced,
        allowance_credits=settings.free_allowance_credits,
    )
    assert resolved.settlement_grace_s == derive_settlement_grace_s(
        job_timeout_s=settings.queue_job_timeout_s,
        max_tries=settings.queue_max_tries,
        backoff_base_s=settings.provider_backoff_base_s,
    )
    # The property that makes it correct rather than merely derived: a debit cannot be swept
    # while arq could still be spending job timeouts on it.
    assert resolved.settlement_grace_s > settings.queue_job_timeout_s * settings.queue_max_tries


def test_a_longer_queue_ladder_lengthens_the_grace_with_it() -> None:
    # Arrange — the failure this prevents: an operator quadruples the job timeout, every
    # render can now outlive a fixed grace, and the sweep starts refunding jobs that are
    # still running. They should not have to know this setting exists.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL, queue_job_timeout_s=3_600.0)

    # Act
    resolved = resolve_entitlement_policy(settings)

    # Assert
    assert resolved.settlement_grace_s == 18_050
    assert resolved.settlement_grace_s > DEFAULT_ENTITLEMENT_POLICY.settlement_grace_s


def test_an_operator_who_states_a_grace_gets_exactly_that_one() -> None:
    # Arrange — the override is the escape hatch, and it wins outright: someone who has
    # decided their queue behaves differently must not have the derivation argue with them.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL, settlement_grace_s=90)

    # Act
    resolved = resolve_entitlement_policy(settings)

    # Assert
    assert resolved.settlement_grace_s == 90


def test_an_unreadable_settings_object_falls_back_to_the_shipped_policy() -> None:
    # Arrange — ``resolve_entitlement_policy`` takes ``object`` so that the entitlements
    # module stays a leaf, which means it must survive being handed something that is not
    # ``Settings`` at all rather than crashing a worker at startup.
    class _NotSettings:
        queue_job_timeout_s = "nine hundred"

    # Act / Assert
    assert resolve_entitlement_policy(_NotSettings()) == DEFAULT_ENTITLEMENT_POLICY
    assert resolve_entitlement_policy(None) == DEFAULT_ENTITLEMENT_POLICY
