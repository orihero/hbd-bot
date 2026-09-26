"""Materialising a frozen audience, and the two things that must survive a restart.

**A resumed expansion must not write a row twice, and a resumed one must not skip anybody.**
Those are the same property from two sides and they are what every test here is about: the
cursor is persisted with the rows it belongs to, the insert goes through the unique
``(broadcast_id, telegram_user_id)``, and a page replayed after a lost commit is therefore a
database no-op rather than a branch somebody has to remember. The first test drives that
directly — it rewinds the cursor the way a crash between the write and the commit would and
asserts the row count does not move.

**The audience is the one the operator approved.** ``compile_segment`` is handed
``broadcasts.audience_evaluated_at`` and never ``utc_now()``, so "joined in the last 30 days"
means the same thirty days in the last chunk as in the first. That is asserted with a
campaign frozen five weeks ago against accounts that would fall outside the window today: if
the job ever read the wall clock, the row count would be zero.

The jobs are driven through their real entry points with the context ARQ hands them —
container, bot, queue — because half of what is under test is the wiring: which job is
enqueued next, and whether one is enqueued at all.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from aiogram import Bot

from bayram.contracts import BroadcastRecipientState, BroadcastState
from bayram.db.base import utc_now
from bayram.db.broadcasts import cancel
from bayram.db.models.broadcast import BroadcastRow
from bayram.runtime import broadcast_job
from bayram.runtime.broadcast_job import (
    EXPAND_JOB_NAME,
    SEND_JOB_NAME,
    expand_broadcast_audience,
    sweep_due_broadcasts,
)
from bayram.runtime.container import AppContainer
from tests.test_runtime.conftest import (
    FIRST_ACCOUNT,
    FROZEN_AT,
    RecordingQueue,
    broadcast_ctx,
    campaign_row,
    recipients,
    seed_accounts,
    seed_campaign,
)

pytestmark = pytest.mark.anyio

#: A rule that only means something relative to a clock, which is the point: compiled at
#: ``FROZEN_AT`` it matches the seed, compiled at ``utc_now()`` it matches nobody.
_JOINED_RECENTLY: Final[dict[str, Any]] = {
    "v": 1,
    "match": "all",
    "rules": [{"field": "joined_at", "op": "within_last_days", "value": 30}],
}

#: How many times a test will re-enter the expansion before deciding it is not converging.
_MAX_PAGES: Final[int] = 12


async def _run(
    container: AppContainer, queue: RecordingQueue, broadcast_id: UUID, *, bot: Bot | None = None
) -> dict[str, Any]:
    """One pass of the expansion, through the entry point ARQ calls."""
    ctx = broadcast_ctx(container, bot, queue)
    return await expand_broadcast_audience(ctx, str(broadcast_id), FROZEN_AT.isoformat())


async def _rewind(container: AppContainer, broadcast_id: UUID, *, cursor: str | None) -> None:
    """Put the campaign's cursor back where an earlier page left it.

    The rows and the cursor are written in ONE transaction, so production cannot land the
    first without the second — which means the only honest way to model a crash between the
    two is from the other end: a job that comes back to a cursor older than the rows it has
    already written, and must write none of them again.
    """
    async with container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == broadcast_id)
            .values(expand_cursor=cursor)
        )


async def test_a_resumed_expansion_inserts_no_duplicates(
    broadcast_container: AppContainer, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — five accounts and a page size of two, so the audience genuinely spans three
    # pages and the resume is a real one rather than a second call that finds nothing to do.
    monkeypatch.setattr(broadcast_job, "EXPAND_CHUNK_SIZE", 2)
    accounts = await seed_accounts(broadcast_container, count=5)
    campaign = await seed_campaign(broadcast_container, audience_size=len(accounts))

    # Act — two pages, then a REPLAY of the second: the job comes back with the cursor it
    # started that page from, which is what a worker killed between the write and the commit
    # hands its successor.
    first = await _run(broadcast_container, queue, campaign)
    cursor_after_first = (await campaign_row(broadcast_container, campaign)).expand_cursor
    second = await _run(broadcast_container, queue, campaign)
    await _rewind(broadcast_container, campaign, cursor=cursor_after_first)
    replayed = await _run(broadcast_container, queue, campaign)

    # Assert — the replay wrote NOTHING. That is the whole guarantee, and it is a number
    # rather than an inference: ``insert_or_ignore`` reports per row whether it landed.
    assert first["inserted"] == 2
    assert second["inserted"] == 2
    assert replayed["scanned"] == 2, "the replayed page must be walked again"
    assert replayed["inserted"] == 0
    assert len(await recipients(broadcast_container, campaign)) == 4

    # Act — carry on to the end.
    for _ in range(_MAX_PAGES):
        if (await campaign_row(broadcast_container, campaign)).state is BroadcastState.READY:
            break
        await _run(broadcast_container, queue, campaign)

    # Assert — every account exactly once, and the campaign is ready to send.
    rows = await recipients(broadcast_container, campaign)
    assert sorted(row.telegram_user_id or 0 for row in rows) == sorted(accounts)
    assert len(rows) == len(accounts)
    assert (await campaign_row(broadcast_container, campaign)).state is BroadcastState.READY


async def test_the_segment_is_compiled_against_the_frozen_instant_not_the_clock(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — accounts that joined eleven days before the audience was frozen, which is
    # WEEKS before today. "Joined in the last 30 days" is therefore true of them at
    # ``audience_evaluated_at`` and false of them now; a job that read the wall clock would
    # materialise an empty audience and report a campaign that went to nobody.
    accounts = await seed_accounts(
        broadcast_container, count=3, joined=FROZEN_AT - timedelta(days=11)
    )
    campaign = await seed_campaign(
        broadcast_container, segment=_JOINED_RECENTLY, audience_size=len(accounts)
    )

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert
    assert summary["inserted"] == len(accounts)
    assert summary["is_complete"] is True


async def test_a_blocked_account_is_materialised_as_a_skip_rather_than_dropped(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — one of three has blocked the bot.
    blocked = FIRST_ACCOUNT + 1
    accounts = await seed_accounts(broadcast_container, count=3, blocked_bot=(blocked,))
    campaign = await seed_campaign(broadcast_container, audience_size=len(accounts))

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert — three rows, not two: the funnel from audience to messages is arithmetic in the
    # table, so a skip is a row that says why rather than an absence somebody has to explain.
    rows = await recipients(broadcast_container, campaign)
    assert len(rows) == 3
    assert summary["suppressed"] == 1
    skipped = [row for row in rows if row.state is BroadcastRecipientState.SKIPPED_BLOCKED]
    assert [row.telegram_user_id for row in skipped] == [blocked]
    assert skipped[0].settled_at is not None, "a skip is settled the moment it is written"


async def test_the_last_page_queues_the_send_when_the_campaign_is_due(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — no ``scheduled_for`` at all, which is what "send it now" looks like on the row.
    await seed_accounts(broadcast_container, count=2)
    campaign = await seed_campaign(broadcast_container, audience_size=2)

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert — the send is queued by the expansion rather than waited for by the sweep,
    # which is the difference between a campaign going out now and going out within five
    # minutes.
    assert summary["is_due"] is True
    assert [job.name for job in queue.jobs] == [SEND_JOB_NAME]
    assert queue.jobs[0].arguments == (str(campaign),)


async def test_a_scheduled_campaign_is_left_for_the_sweep(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — scheduled for tomorrow. The panel deliberately enqueues nothing for a future
    # instant, so the expansion must not either: a job deferred by a day inside Redis is a
    # promise made by the least durable component in the system.
    #
    # Tomorrow is measured from the REAL clock, not from ``FROZEN_AT``: the audience instant
    # is a stored fact a test may put wherever it likes, but "is this campaign due" is asked
    # of the wall clock the worker is actually running on.
    await seed_accounts(broadcast_container, count=2)
    campaign = await seed_campaign(
        broadcast_container, audience_size=2, scheduled_for=utc_now() + timedelta(days=1)
    )

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert
    assert summary["is_complete"] is True
    assert summary["is_due"] is False
    assert queue.jobs == []
    assert (await campaign_row(broadcast_container, campaign)).state is BroadcastState.READY


async def test_a_cancelled_campaign_stops_the_expansion_and_queues_nothing(
    broadcast_container: AppContainer, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a page size of two over five accounts, so there is a second page to refuse,
    # and a cancel between the two pages.
    monkeypatch.setattr(broadcast_job, "EXPAND_CHUNK_SIZE", 2)
    await seed_accounts(broadcast_container, count=5)
    campaign = await seed_campaign(broadcast_container, audience_size=5)
    await _run(broadcast_container, queue, campaign)
    queue.jobs.clear()
    async with broadcast_container.require_session_factory().begin() as session:
        assert await cancel(session, broadcast_id=campaign, at=FROZEN_AT)

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert — no successor. The rows already written are harmless (a cancelled campaign
    # sends nothing) but a successor would keep an abandoned expansion running to the end of
    # a fifty-thousand-account audience.
    assert queue.jobs == []
    assert summary["state"] == str(BroadcastState.CANCELLED)


async def test_a_segment_that_no_longer_compiles_fails_the_campaign_before_anything_is_sent(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — a document naming a field the registry does not have, which is what a
    # campaign stored before a field was withdrawn looks like on the way back in.
    await seed_accounts(broadcast_container, count=2)
    campaign = await seed_campaign(
        broadcast_container,
        segment={
            "v": 1,
            "match": "all",
            "rules": [{"field": "phone_number", "op": "is_not_null"}],
        },
    )

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert — ``failed`` grades the RUN and is reachable only from here: a structural defect
    # found before any message left. No recipients, no successor, and an error code an
    # operator can grep.
    row = await campaign_row(broadcast_container, campaign)
    assert row.state is BroadcastState.FAILED
    assert row.error_code == "segment_undecodable"
    assert summary["error"] == "segment_undecodable"
    assert queue.jobs == []
    assert await recipients(broadcast_container, campaign) == ()


async def test_a_cursor_nobody_can_read_fails_the_campaign_rather_than_looping_forever(
    broadcast_container: AppContainer, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a corrupted resume token. It was minted by us and written by us, so it cannot
    # be caller error; it is a damaged row, and it is damaged identically on every retry.
    monkeypatch.setattr(broadcast_job, "EXPAND_CHUNK_SIZE", 2)
    await seed_accounts(broadcast_container, count=5)
    campaign = await seed_campaign(broadcast_container, audience_size=5)
    await _run(broadcast_container, queue, campaign)
    await _rewind(broadcast_container, campaign, cursor="not-a-cursor")
    queue.jobs.clear()

    # Act
    summary = await _run(broadcast_container, queue, campaign)

    # Assert — failed, and therefore no longer due: the sweep only revives campaigns that are
    # still expanding, so this is what stops one damaged row being re-queued twelve times an
    # hour for the life of the deployment.
    row = await campaign_row(broadcast_container, campaign)
    assert row.state is BroadcastState.FAILED
    assert row.error_code == "cursor_undecodable"
    assert summary["error"] == "cursor_undecodable"
    assert queue.jobs == []


async def test_a_job_queued_for_a_campaign_that_does_not_exist_is_not_an_incident(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Act — a campaign deleted between the enqueue and the run.
    summary = await _run(broadcast_container, queue, uuid4())

    # Assert — reported, never raised: raising here would hand the queue a retry ladder
    # against a row that is never coming back.
    assert summary["error"] == "unknown_campaign"
    assert queue.jobs == []


async def test_the_sweep_resumes_an_expansion_whose_worker_died(
    broadcast_container: AppContainer, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — one page written, and then nothing: the successor was never queued, which is
    # exactly what a SIGTERM between the commit and the enqueue leaves behind. ARQ's own
    # retry cannot fix that (``max_tries=1``), so the sweep is the only thing that can.
    monkeypatch.setattr(broadcast_job, "EXPAND_CHUNK_SIZE", 2)
    await seed_accounts(broadcast_container, count=5)
    campaign = await seed_campaign(broadcast_container, audience_size=5)
    await _run(broadcast_container, queue, campaign)
    queue.jobs.clear()

    # Act — an hour after the page was written, which is well past the lease the sweep calls
    # "stalled". The instant is taken from the real clock because that is what the page's own
    # ``updated_at`` was stamped with: the job reads ``utc_now()``, deliberately, and only the
    # SEGMENT is compiled against the frozen one.
    ctx = broadcast_ctx(broadcast_container, None, queue)
    summary = await sweep_due_broadcasts(ctx, now=utc_now() + timedelta(hours=1))

    # Assert — the expansion is queued again, against the instant its audience was frozen at
    # and not against the sweep's own clock.
    assert summary["expansions_enqueued"] == 1
    assert [job.name for job in queue.jobs] == [EXPAND_JOB_NAME]
    assert queue.jobs[0].arguments == (str(campaign), FROZEN_AT.isoformat())


async def test_the_sweep_leaves_a_campaign_that_is_still_moving_alone(
    broadcast_container: AppContainer, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the same half-expanded campaign, but swept while its last chunk is recent.
    # This is what keeps a five-minutely sweep from handing one healthy campaign twelve
    # parallel chains of jobs an hour.
    monkeypatch.setattr(broadcast_job, "EXPAND_CHUNK_SIZE", 2)
    await seed_accounts(broadcast_container, count=5)
    campaign = await seed_campaign(broadcast_container, audience_size=5)
    await _run(broadcast_container, queue, campaign)
    queue.jobs.clear()

    # Act — one minute after the page was written, which is inside the lease.
    ctx = broadcast_ctx(broadcast_container, None, queue)
    summary = await sweep_due_broadcasts(ctx, now=utc_now() + timedelta(minutes=1))

    # Assert
    assert summary["campaigns_scanned"] == 0
    assert queue.jobs == []


def test_the_worker_decodes_a_stored_segment_without_importing_a_web_framework() -> None:
    """The stored document is the PANEL's wire shape, so the worker decodes it with the
    panel's own models — and that import must stay a pydantic one.

    A second decoder in this process was the alternative, and it would be a second vocabulary
    to keep in step with the field registry: the day the two drifted, the campaign that went
    out would not be the one the operator previewed. Reusing ``bayram.admin.schemas.segment`` is
    therefore the cheaper mistake — but only while it costs no FastAPI, no Starlette and no
    request machinery in a process that must never serve HTTP. This runs in a subprocess
    because the assertion is about a FRESH interpreter: in this one, half the suite has
    already imported the admin app.
    """
    # Arrange / Act
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import bayram.runtime.broadcast_job; "
            "print(sorted(m for m in sys.modules if m in {'fastapi', 'starlette'}))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Assert
    assert probe.stdout.strip() == "[]", probe.stdout
