"""The two processes and the offline demo, exercised without polling Telegram.

``run_polling`` is the one call that genuinely needs a network, so it is the one thing
stubbed here. Everything before it — settings, host checks, the container, the submitter
choice, the FSM store, the dependency container, and the shutdown path — is real, because
a composition root that is only tested by starting it is not tested at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import bayram.main as main_module
from bayram.config import Settings
from bayram.errors import ConfigError
from bayram.runtime.container import build_container
from bayram.runtime.jobs import (
    ACTIVITY_SNAPSHOT_JOB_NAME,
    BOT_CTX_KEY,
    CONTAINER_CTX_KEY,
    DUE_JOB_NAME,
    EXPAND_JOB_NAME,
    KIT_JOB_NAME,
    PAYME_NOTIFY_JOB_NAME,
    PAYME_SWEEP_JOB_NAME,
    RETENTION_JOB_NAME,
    SEND_JOB_NAME,
    TEST_SEND_JOB_NAME,
    VENDOR_BALANCE_JOB_NAME,
    build_kit_worker_settings,
    generate_and_deliver,
)
from bayram.runtime.startup import verify_host
from bayram.runtime.submitter import InProcessOrderSubmitter


def _registered_name(entry: Any) -> str:
    """The name ARQ will dispatch this entry under, whether it is bare or wrapped.

    A bare coroutine is looked up by ``__qualname__``; one wrapped in ``arq.worker.func`` —
    which is how a job states a retry budget of its own — carries an explicit ``name``. Both
    end up as the key in the worker's function table, so this reads whichever is present.
    """
    return str(getattr(entry, "name", getattr(entry, "__name__", "")))


def _offline(base: Settings, tmp_path: Path, **extra: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            **base.model_dump(),
            "use_fake_providers": True,
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'entry.db'}",
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------
def test_a_missing_ffmpeg_stops_the_process_before_it_accepts_an_order(
    settings: Settings,
) -> None:
    # Arrange: a host without libopus must fail one boot, not every order.
    broken = settings.model_copy(update={"ffmpeg_binary": "ffmpeg-that-does-not-exist"})

    # Act / Assert
    with pytest.raises(ConfigError):
        verify_host(broken)


@pytest.mark.integration
def test_verify_host_passes_on_a_host_with_ffmpeg(settings: Settings) -> None:
    # Act / Assert: it returns nothing; a failure stops the process, so no news is good.
    verify_host(settings)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def test_the_offline_shape_keeps_the_wizard_in_memory(settings: Settings, tmp_path: Path) -> None:
    # Arrange / Act
    storage = main_module._fsm_storage(_offline(settings, tmp_path))

    # Assert: no Redis is contacted for a demo run.
    assert isinstance(storage, MemoryStorage)


async def test_the_offline_shape_runs_the_job_in_process(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    configured = _offline(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    bot = Bot(token="42:AAF-test-token-value-not-a-real-one")

    # Act
    try:
        submitter, closeable = await main_module.build_submitter(
            configured, container, bot, MemoryStorage()
        )

        # Assert
        assert isinstance(submitter, InProcessOrderSubmitter)
        assert closeable is None
    finally:
        await bot.session.close()
        await container.aclose()


async def test_run_builds_a_dispatcher_and_releases_everything_afterwards(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: stub out the one call that needs a network.
    seen: list[Dispatcher] = []

    async def fake_polling(bot: Bot, dispatcher: Dispatcher) -> None:
        seen.append(dispatcher)

    monkeypatch.setattr(main_module, "run_polling", fake_polling)

    # Act
    await main_module.run(_offline(settings, tmp_path), data_root=tmp_path)

    # Assert: a real dispatcher with the real router tree was handed to polling.
    assert len(seen) == 1
    assert seen[0].sub_routers


async def test_shutdown_reports_a_stubborn_resource_rather_than_masking_the_rest(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    container = await build_container(_offline(settings, tmp_path), data_root=tmp_path)
    bot = Bot(token="42:AAF-test-token-value-not-a-real-one")

    class Stubborn:
        async def aclose(self) -> None:
            raise OSError("the pool refuses to close")

    # Act / Assert: one failing close must not prevent the other two.
    await main_module._shutdown(container, bot, Stubborn())


def test_an_invalid_environment_exits_with_a_code_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: strip every BAYRAM_ variable so required settings are genuinely missing.
    import os

    from bayram.config import ENV_PREFIX

    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(str(Path(__file__).parent))  # away from any .env

    # Act
    code = main_module.main()

    # Assert
    assert code == 2


# ---------------------------------------------------------------------------
# worker settings
# ---------------------------------------------------------------------------
async def test_the_worker_registers_the_job_the_submitter_enqueues(settings: Settings) -> None:
    # Arrange: ARQ dispatches by name; a mismatch means jobs sit in Redis forever.
    async def dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker_settings = build_kit_worker_settings(settings=settings, build_dependencies=dependencies)

    # Assert — every job, named exactly. The retention sweep joined the kit job when the
    # hourly cron landed, and the dashboard instrumentation added two more: the hourly vendor
    # balance poll and the nightly activity snapshot. Leaving this as an exact list is what
    # keeps a job from being registered without somebody deciding it should be — and the
    # Payme rail is that decision being taken: the settled-payment notification and the
    # five-minutely sweep are the FIRST entries here whose enqueue side is not this
    # repository's bot or admin process at all, but the payment gateway, which holds the
    # cashbox key and no Telegram token. A name that drifted would leave a paying customer
    # silently untold with the money already banked, which is why this list is read by NAME.
    #
    # ``_registered_name`` rather than ``__name__``: the notification is wrapped in arq's
    # ``func()`` so it can carry its own retry budget instead of the queue-wide one, and a
    # wrapped entry is an ``arq.worker.Function`` — which carries ``name`` and not
    # ``__name__``. That is the same string arq dispatches on, so reading it is if anything
    # closer to the property this test is about.
    #
    # The four broadcast entries are the same decision taken a second time, for the second
    # process that queues work into this worker: the ADMIN PANEL. It is denied a Telegram
    # token by design, so composing a campaign and sending it are necessarily two processes
    # — and ``bayram.admin.queue`` names these jobs as STRINGS it restates rather than imports.
    # A rename that compiled on both sides of that gap would silently stop every campaign,
    # which is exactly what reading this list by name prevents.
    assert [_registered_name(fn) for fn in worker_settings.functions] == [
        KIT_JOB_NAME,
        RETENTION_JOB_NAME,
        VENDOR_BALANCE_JOB_NAME,
        ACTIVITY_SNAPSHOT_JOB_NAME,
        PAYME_NOTIFY_JOB_NAME,
        PAYME_SWEEP_JOB_NAME,
        EXPAND_JOB_NAME,
        SEND_JOB_NAME,
        TEST_SEND_JOB_NAME,
        DUE_JOB_NAME,
    ]
    assert worker_settings.max_jobs == settings.worker_concurrency
    assert worker_settings.job_timeout == settings.queue_job_timeout_s


async def test_worker_startup_populates_the_context_the_job_reads(settings: Settings) -> None:
    # Arrange
    async def dependencies() -> dict[str, Any]:
        return {CONTAINER_CTX_KEY: "container", BOT_CTX_KEY: "bot"}

    worker_settings = build_kit_worker_settings(settings=settings, build_dependencies=dependencies)
    ctx: dict[str, Any] = {}

    # Act
    await worker_settings.on_startup(ctx)

    # Assert
    assert set(ctx) == {CONTAINER_CTX_KEY, BOT_CTX_KEY}


async def test_worker_shutdown_is_optional_and_is_called_when_supplied(
    settings: Settings,
) -> None:
    # Arrange
    closed: list[str] = []

    async def dependencies() -> dict[str, Any]:
        return {}

    async def teardown(ctx: Mapping[str, Any]) -> None:
        closed.append("done")

    worker_settings = build_kit_worker_settings(
        settings=settings, build_dependencies=dependencies, shutdown=teardown
    )

    # Act
    await worker_settings.on_shutdown({})

    # Assert
    assert closed == ["done"]


def test_the_job_function_name_matches_the_name_the_submitter_uses() -> None:
    assert generate_and_deliver.__name__ == KIT_JOB_NAME


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_the_offline_demo_produces_a_complete_kit(tmp_path: Path) -> None:
    # Arrange / Act: the command the README tells an operator to run.
    from bayram.demo import run_demo

    code = await run_demo(data_root=tmp_path)

    # Assert
    assert code == 0
    assert list(tmp_path.rglob("*.mp3")), "no song was produced"
    assert list(tmp_path.rglob("lyrics.txt")), "no lyric sheet was produced"
    # greetings_per_kit defaults to 0: a song-only kit buys no speech, so no OGG/Opus
    # voice notes exist. Raise the setting and this becomes a non-empty list again.
    assert not list(tmp_path.rglob("*.ogg")), "speech was rendered despite greetings being off"
