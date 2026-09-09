"""Delivering a campaign, where every test is about a message that must NOT be sent twice.

The send job's whole design is one ordering — claim, commit, send, settle — and the tests
below attack it from the sides it can be broken from:

* **a job that died between the claim and the call.** Its row stays ``sending``, nothing
  re-claims it, and the customer behind it gets nothing rather than a second copy. That the
  hole is then visible as ``unknown`` rather than rounded away is asserted too;
* **a customer who blocked the bot.** Terminal on the row, recorded as churn through the same
  recorder the delivery arm feeds, and never attempted again;
* **the pacer.** It is consulted before every single message, and a chunk that starts inside
  another replica's flood wait defers instead of claiming — a chunk that slept through its
  own job timeout would be cancelled with rows claimed, which is the first bullet again;
* **a pause.** Read every :data:`PAUSE_CHECK_EVERY` messages, and the rows already claimed
  are handed BACK rather than abandoned, because a released row is one nothing sent to.

Everything runs against a real container — a real SQLite database, the real object store and
the real churn recorder — and a recording Telegram session. A stub for any of them would
assert that the test's own fake was called.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from hbd.contracts import BroadcastRecipientState, BroadcastState, Language, is_ok
from hbd.db.base import utc_now
from hbd.db.broadcasts import BroadcastBody, SqlBroadcasts, pause
from hbd.db.enums import AdminRole, AuditAction
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.admin_user import AdminUserRow
from hbd.db.models.broadcast import BroadcastRow
from hbd.db.models.user import UserRow
from hbd.runtime import broadcast_job
from hbd.runtime.broadcast_job import (
    SEND_JOB_NAME,
    send_broadcast_chunk,
    send_broadcast_test,
    sweep_due_broadcasts,
)
from hbd.runtime.container import AppContainer
from hbd.runtime.pacer import SendPacer
from tests.test_runtime.conftest import (
    FIRST_ACCOUNT,
    BroadcastSession,
    RecordingQueue,
    broadcast_ctx,
    campaign_row,
    materialise,
    recipients,
    seed_accounts,
    seed_campaign,
)

pytestmark = pytest.mark.anyio

#: A 32-character key, which is the minimum the panel's own field accepts. The value is
#: irrelevant to every assertion here — what matters is whether the worker HAS one.
_CHAIN_KEY: Final[str] = "k" * 32
_CHAIN_KEY_VAR: Final[str] = "HBD_ADMIN_AUDIT_HMAC_KEY"


def _blocked_by_customer(chat_id: int) -> TelegramForbiddenError:
    """Telegram's refusal for an account that blocked the bot, worded as Telegram words it.

    The wording is what ``hbd.bot.delivery.is_blocked_by_customer`` classifies on, and this
    test writes it out rather than importing the constant: the predicate's own test pins the
    string, and a second test that shared the constant would agree with the code by
    construction even if both were wrong about what Telegram says.
    """
    return TelegramForbiddenError(
        method=SendMessage(chat_id=chat_id, text="x"),
        message="Forbidden: bot was blocked by the user",
    )


async def _run(
    container: AppContainer, bot: Bot, queue: RecordingQueue, broadcast_id: UUID
) -> dict[str, Any]:
    """One chunk, through the entry point ARQ calls."""
    return await send_broadcast_chunk(broadcast_ctx(container, bot, queue), str(broadcast_id))


async def _ready_campaign(
    container: AppContainer,
    *,
    accounts: int = 3,
    bodies: tuple[BroadcastBody, ...] | None = None,
) -> tuple[UUID, tuple[int, ...]]:
    """Seeded accounts, a campaign, and its audience already materialised.

    How the rows got there is ``test_broadcast_expand``'s subject; the send job is defined
    over a campaign that is ``ready``, so that is where these tests start.
    """
    seeded = await seed_accounts(container, count=accounts)
    campaign = await seed_campaign(container, audience_size=accounts, bodies=bodies)
    await materialise(container, campaign)
    return campaign, seeded


async def _seed_admin(container: AppContainer, *, role: AdminRole = AdminRole.ADMIN) -> UUID:
    """The operator a campaign is attributed to, so the outcome row can name a real one."""
    admin_id = uuid4()
    async with container.require_session_factory().begin() as session:
        session.add(
            AdminUserRow(
                id=admin_id,
                username="ops.dilnoza",
                password_hash="$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA",
                role=role,
                is_active=True,
                must_change_password=False,
                password_changed_at=utc_now(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    return admin_id


async def _attribute(container: AppContainer, campaign: UUID, admin_id: UUID) -> None:
    """Point the campaign at a real operator row, the way ``POST /api/broadcasts`` does."""
    async with container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == campaign)
            .values(created_by_admin_id=admin_id, created_by_username="ops.dilnoza")
        )


async def _audit_rows(container: AppContainer) -> list[AdminAuditRow]:
    async with container.require_session_factory()() as session:
        rows = await session.scalars(sa.select(AdminAuditRow).order_by(AdminAuditRow.seq))
        return list(rows)


async def _account(container: AppContainer, telegram_user_id: int) -> UserRow:
    async with container.require_session_factory()() as session:
        row = await session.scalar(
            sa.select(UserRow).where(UserRow.telegram_user_id == telegram_user_id)
        )
        assert row is not None
        return row


# ---------------------------------------------------------------------------
# The never-double-send rule
# ---------------------------------------------------------------------------
async def test_a_crash_between_the_claim_and_the_send_leaves_the_recipient_un_retried(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — one row claimed and never settled, which is EXACTLY what a worker killed
    # between the commit and the Telegram call leaves behind. It is produced through the real
    # claim rather than by writing the state by hand, so the row carries the attempts count
    # and the lease clock a real claim would.
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=3)
    store = SqlBroadcasts(broadcast_container.require_session_factory())
    abandoned = await store.claim(campaign, at=utc_now(), limit=1)
    assert is_ok(abandoned) and len(abandoned.value) == 1
    stranded = abandoned.value[0]

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)
    await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — the abandoned account was never messaged, by either pass. Two passes and not
    # one because the failure this guards against is a REPLAY: the row is only safe if
    # nothing claims it a second time, ever.
    assert stranded.telegram_user_id not in broadcast_session.chats()
    assert sorted(broadcast_session.chats()) == sorted(
        account for account in accounts if account != stranded.telegram_user_id
    )
    rows = {row.id: row for row in await recipients(broadcast_container, campaign)}
    assert rows[stranded.id].state is BroadcastRecipientState.SENDING
    assert rows[stranded.id].attempts == 1, "claimed once, and never claimed again"
    assert summary["sent"] == 2


async def test_the_abandoned_row_becomes_unknown_and_the_campaign_can_then_finish(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — the same crash, with the two messages that could be sent already sent.
    campaign, _ = await _ready_campaign(broadcast_container, accounts=3)
    store = SqlBroadcasts(broadcast_container.require_session_factory())
    abandoned = await store.claim(campaign, at=utc_now(), limit=1)
    assert is_ok(abandoned)
    await _run(broadcast_container, broadcast_bot, queue, campaign)
    queue.jobs.clear()

    # Act — the sweep, after the lease. It is the only thing that can retire that row, and
    # therefore the only thing that lets ``outstanding`` reach zero.
    lease_s = broadcast_container.settings.broadcast_sending_lease_s
    later = utc_now() + timedelta(seconds=lease_s + 60)
    await sweep_due_broadcasts(broadcast_ctx(broadcast_container, None, queue), now=later)
    await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — the hole is VISIBLE. ``unknown`` is its own counter, deliberately not folded
    # into ``failed``: we do not know whether that message arrived, and a counter that said
    # "failed" would be asserting something nobody can support.
    row = await campaign_row(broadcast_container, campaign)
    assert row.state is BroadcastState.COMPLETED
    assert (row.sent_count, row.unknown_count, row.failed_count) == (2, 1, 0)
    assert len(broadcast_session.chats()) == 2, "the unknown row was never sent to"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
async def test_a_blocked_user_is_settled_terminally_recorded_as_churn_and_never_retried(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — the middle account blocked the bot after the audience was frozen, which is
    # the case expansion-time suppression cannot catch and only the send can.
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=3)
    blocked = accounts[1]
    broadcast_session.refusals[blocked] = _blocked_by_customer(blocked)

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)
    attempts_first_pass = broadcast_session.chats()
    await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — terminal on the row, and the other two are unaffected: one refusal in a chunk
    # must never cost the rest of it.
    rows = {row.telegram_user_id: row for row in await recipients(broadcast_container, campaign)}
    assert rows[blocked].state is BroadcastRecipientState.SKIPPED_BLOCKED
    assert rows[blocked].error_code == "blocked_by_customer"
    assert rows[blocked].settled_at is not None
    assert summary["sent"] == 2
    assert summary["skipped"] == 1

    # Assert — recorded as churn through the container's own recorder. This is the largest
    # block detector the system has, and ``run_polling(drop_pending_updates=True)`` throws
    # away every ``my_chat_member`` that arrives during a deploy — so a refusal that recorded
    # nothing would lose the block entirely.
    assert (await _account(broadcast_container, blocked)).blocked_bot_at is not None

    # Assert — and it is never attempted again.
    assert broadcast_session.chats() == attempts_first_pass


async def test_an_account_that_ran_forget_is_undeliverable_without_a_telegram_call(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — ``/forget`` between the expansion and the send nulls the recipient's id. The
    # row is claimed rather than skipped, so that the campaign can still reach zero
    # outstanding; what it must not do is spend a Telegram call on a nobody.
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=2)
    async with broadcast_container.require_session_factory().begin() as session:
        await session.execute(
            sa.text(
                "UPDATE broadcast_recipients SET telegram_user_id = NULL "
                "WHERE telegram_user_id = :id"
            ),
            {"id": accounts[0]},
        )

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert
    assert summary["undeliverable"] == 1
    assert broadcast_session.chats() == (accounts[1],)
    states = {row.state for row in await recipients(broadcast_container, campaign)}
    assert states == {BroadcastRecipientState.UNDELIVERABLE, BroadcastRecipientState.SENT}


async def test_a_recipient_whose_language_the_campaign_never_composed_is_failed(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — a Russian-only campaign against Uzbek-speaking accounts. The compose-time
    # validator refuses this, so reaching it is a defence rather than a routine path — and a
    # defence that sent the wrong language would be worse than one that sends nothing.
    campaign, _ = await _ready_campaign(
        broadcast_container,
        accounts=2,
        bodies=(BroadcastBody(language=Language.RU, text="Сегодня вечером обновление."),),
    )

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — no message left, and the reason is a symbolic code an operator can grep.
    assert broadcast_session.chats() == ()
    assert summary["failed"] == 2
    codes = {row.error_code for row in await recipients(broadcast_container, campaign)}
    assert codes == {"no_body_for_language"}


# ---------------------------------------------------------------------------
# The pacer
# ---------------------------------------------------------------------------
class _CountingPacer(SendPacer):
    """A real pacer that remembers being asked. Subclassed rather than faked, so the job is
    still driving the production budget logic and only the counters are ours."""

    acquired: int = 0
    parked_answer: float = 0.0

    async def acquire(self) -> None:
        type(self).acquired += 1
        await super().acquire()

    async def parked_for_s(self) -> float:
        return type(self).parked_answer or await super().parked_for_s()


@pytest.fixture
def counting_pacer(monkeypatch: pytest.MonkeyPatch) -> type[_CountingPacer]:
    """Swap the pacer CLASS, not the job's use of it: the job still builds one the way it
    builds one in production, over whatever store its context implies."""
    _CountingPacer.acquired = 0
    _CountingPacer.parked_answer = 0.0
    monkeypatch.setattr(broadcast_job, "SendPacer", _CountingPacer)
    return _CountingPacer


async def test_every_message_is_paced(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
    counting_pacer: type[_CountingPacer],
) -> None:
    # Arrange — three accounts, nothing unusual about any of them.
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=3)

    # Act
    await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — one acquisition per message, no more and no fewer. Telegram's ceiling is per
    # BOT TOKEN, so a campaign that outran the budget would take the orders down with it.
    assert counting_pacer.acquired == len(accounts)
    assert len(broadcast_session.chats()) == len(accounts)


async def test_a_chunk_that_starts_inside_a_flood_wait_defers_before_claiming_anything(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
    counting_pacer: type[_CountingPacer],
) -> None:
    # Arrange — another replica has already been told to back off for half a minute. A park
    # is a statement about the TOKEN, so this replica is parked too.
    campaign, _ = await _ready_campaign(broadcast_container, accounts=3)
    counting_pacer.parked_answer = 30.0

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — nothing claimed and nothing sent. Waiting it out inside ``acquire`` would burn
    # the chunk's job timeout and end in a cancellation with rows claimed — which is the
    # crash this suite's first test is about.
    assert broadcast_session.chats() == ()
    assert summary["claimed"] == 0
    assert summary["parked_s"] == 30.0
    assert [row.state for row in await recipients(broadcast_container, campaign)] == [
        BroadcastRecipientState.PENDING
    ] * 3
    # And the successor waits exactly as long as Telegram asked for.
    assert [(job.name, job.defer_s) for job in queue.jobs] == [(SEND_JOB_NAME, 30.0)]


async def test_a_flood_wait_mid_chunk_leaves_the_rest_pending_and_defers_the_successor(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — the second account's send is answered with ``retry_after``. That message
    # never left the process, which is the ONE condition under which a claimed row may go
    # back to ``pending``.
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=4)
    broadcast_session.refusals[accounts[1]] = TelegramRetryAfter(
        method=SendMessage(chat_id=accounts[1], text="x"),
        message="Too Many Requests: retry after 12",
        retry_after=12,
    )

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — the refused account is PENDING and nothing is FAILED. A flood wait says
    # nothing about any of these accounts, and marking them failed would strike customers off
    # a campaign because Telegram was busy. Which accounts had already gone before the wait
    # arrived is not asserted: the claim drains a chunk in the order the ledger holds it, and
    # a test that pinned that order would be pinning the seed rather than the behaviour.
    rows = {row.telegram_user_id: row for row in await recipients(broadcast_container, campaign)}
    states = [row.state for row in rows.values()]
    assert rows[accounts[1]].state is BroadcastRecipientState.PENDING
    assert BroadcastRecipientState.FAILED not in states
    assert states.count(BroadcastRecipientState.SENT) == summary["sent"]
    assert states.count(BroadcastRecipientState.PENDING) == summary["released"]
    assert summary["sent"] + summary["released"] == len(accounts)
    for row in rows.values():
        if row.state is BroadcastRecipientState.PENDING:
            assert row.attempts == 1, "a claim is counted even when it is handed back"

    # Assert — every sender is parked, and the successor waits at least as long as Telegram
    # asked for. The chunk ENDS here rather than retrying inside the loop: under a 429 the
    # second call is the one most likely to deepen the wait.
    assert summary["parked_s"] >= 12.0
    assert [job.name for job in queue.jobs] == [SEND_JOB_NAME]
    assert queue.jobs[0].defer_s >= 12.0


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------
async def test_a_pause_is_observed_mid_chunk_and_the_rest_of_the_claim_is_handed_back(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — six accounts, a state re-read every two messages, and an operator who presses
    # Pause while the first message is still in flight. Two rather than twenty-five so the
    # test is about the mechanism instead of about the number.
    monkeypatch.setattr(broadcast_job, "PAUSE_CHECK_EVERY", 2)
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=6)
    sessions = broadcast_container.require_session_factory()
    pressed = False

    async def press_pause() -> None:
        nonlocal pressed
        if pressed:
            return
        pressed = True
        async with sessions.begin() as session:
            assert await pause(session, broadcast_id=campaign, at=utc_now())

    broadcast_session.after_call = press_pause

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — the stop was felt within the chunk, not at the end of it: two messages went
    # out (the one in flight, and the one before the next check) and the other four are back
    # in the queue rather than abandoned mid-claim.
    assert len(broadcast_session.chats()) == 2
    assert summary["released"] == 4
    states = [row.state for row in await recipients(broadcast_container, campaign)]
    assert states.count(BroadcastRecipientState.SENT) == 2
    assert states.count(BroadcastRecipientState.PENDING) == 4

    # Assert — and a paused campaign is not queued for another chunk. Resuming is the
    # operator's decision; a job that re-queued itself would overrule it.
    assert queue.jobs == []
    assert (await campaign_row(broadcast_container, campaign)).state is BroadcastState.PAUSED


async def test_a_paused_campaign_claims_nothing_at_all(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — one message per chunk, so the campaign is still ``sending`` when the operator
    # presses Pause: a campaign that finished in its first chunk has nothing left to refuse.
    monkeypatch.setattr(broadcast_job, "SEND_CHUNK_SIZE", 1)
    campaign, _ = await _ready_campaign(broadcast_container, accounts=3)
    await _run(broadcast_container, broadcast_bot, queue, campaign)  # ready -> sending
    async with broadcast_container.require_session_factory().begin() as session:
        assert await pause(session, broadcast_id=campaign, at=utc_now())
    broadcast_session.clear()

    # Act — a successor that arrives after the pause, which is the ordinary case: the chunk
    # was already queued when the operator pressed the button.
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert
    assert broadcast_session.calls == []
    assert summary["state"] == str(BroadcastState.PAUSED)


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------
async def test_a_finished_campaign_writes_the_outcome_audit_row(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — a real operator row, because the outcome row names WHO the campaign was sent
    # on behalf of and reads their role live: the action being recorded is this completion,
    # so today's role is the role at the time of the action.
    monkeypatch.setenv(_CHAIN_KEY_VAR, _CHAIN_KEY)
    admin_id = await _seed_admin(broadcast_container, role=AdminRole.ADMIN)
    campaign, accounts = await _ready_campaign(broadcast_container, accounts=2)
    await _attribute(broadcast_container, campaign, admin_id)

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — two audit rows would be wrong and none would be worse: ``broadcast.schedule``
    # (the panel's, recording an authorisation) is not written here, and ``broadcast.sent``
    # is, because what LANDED is knowable only now and only in this process.
    assert summary["is_finished"] is True
    rows = await _audit_rows(broadcast_container)
    assert [row.action for row in rows] == [AuditAction.BROADCAST_SENT]
    outcome = rows[0]
    assert outcome.subject_type == "broadcast"
    assert outcome.subject_id == str(campaign)
    assert outcome.record_count == len(accounts)
    assert outcome.actor_id == admin_id
    assert outcome.actor_username == "ops.dilnoza"
    assert outcome.actor_role is AdminRole.ADMIN
    assert outcome.chain_hmac, "the row is chained, or it is not evidence"


async def test_a_replayed_final_chunk_does_not_write_a_second_outcome_row(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — every job here is replayed on every deploy, so "finished" has to be a state
    # the second run finds already taken rather than a thing it does again.
    monkeypatch.setenv(_CHAIN_KEY_VAR, _CHAIN_KEY)
    campaign, _ = await _ready_campaign(broadcast_container, accounts=2)
    await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert
    assert summary["is_finished"] is False
    assert len(await _audit_rows(broadcast_container)) == 1
    assert (await campaign_row(broadcast_container, campaign)).state is BroadcastState.COMPLETED


async def test_a_worker_with_no_chain_key_still_finishes_the_campaign(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    # Arrange — no key in the environment and no dotenv to read one from. That is a supported
    # deployment: the chain key belongs to the panel, and a worker without it loses the
    # accountability COPY of the outcome, never the campaign itself.
    monkeypatch.delenv(_CHAIN_KEY_VAR, raising=False)
    monkeypatch.setenv("HBD_ENV_FILE", str(tmp_path / "absent.env"))
    campaign, _ = await _ready_campaign(broadcast_container, accounts=2)

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — the campaign row is the operational record and it is complete and correct.
    row = await campaign_row(broadcast_container, campaign)
    assert summary["is_finished"] is True
    assert row.state is BroadcastState.COMPLETED
    assert row.sent_count == 2
    assert row.finished_at is not None
    assert await _audit_rows(broadcast_container) == []


# ---------------------------------------------------------------------------
# The sweep's other arm, and the test send
# ---------------------------------------------------------------------------
async def test_the_sweep_starts_a_campaign_whose_scheduled_instant_has_arrived(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange — scheduled for an hour ago, and nobody has told the worker. Nothing else in
    # the system will: the panel enqueues no job for a future instant.
    campaign, _ = await _ready_campaign(broadcast_container, accounts=2)
    async with broadcast_container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == campaign)
            .values(scheduled_for=utc_now() - timedelta(hours=1))
        )

    # Act
    summary = await sweep_due_broadcasts(broadcast_ctx(broadcast_container, None, queue))

    # Assert
    assert summary["sends_enqueued"] == 1
    assert [(job.name, job.arguments) for job in queue.jobs] == [(SEND_JOB_NAME, (str(campaign),))]


async def test_a_send_chunk_that_arrives_before_the_scheduled_instant_sends_nothing(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — a campaign scheduled for tomorrow, and a chunk job for it anyway. Nothing in
    # the system produces that today; the guard exists because the failure it prevents — a
    # campaign going out a day before the operator said it would — is one no correction undoes.
    campaign, _ = await _ready_campaign(broadcast_container, accounts=2)
    async with broadcast_container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == campaign)
            .values(scheduled_for=utc_now() + timedelta(days=1))
        )

    # Act
    summary = await _run(broadcast_container, broadcast_bot, queue, campaign)

    # Assert — not started, nothing claimed, nothing sent.
    assert broadcast_session.calls == []
    assert summary["state"] == str(BroadcastState.READY)
    row = await campaign_row(broadcast_container, campaign)
    assert row.state is BroadcastState.READY
    assert row.started_at is None


async def test_the_sweep_leaves_a_campaign_scheduled_for_later_alone(
    broadcast_container: AppContainer, queue: RecordingQueue
) -> None:
    # Arrange
    campaign, _ = await _ready_campaign(broadcast_container, accounts=2)
    async with broadcast_container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(BroadcastRow)
            .where(BroadcastRow.id == campaign)
            .values(scheduled_for=utc_now() + timedelta(hours=1))
        )

    # Act
    summary = await sweep_due_broadcasts(broadcast_ctx(broadcast_container, None, queue))

    # Assert
    assert summary["campaigns_scanned"] == 0
    assert queue.jobs == []


async def test_the_test_send_puts_every_composed_body_in_front_of_one_operator(
    broadcast_container: AppContainer,
    broadcast_bot: Bot,
    broadcast_session: BroadcastSession,
    queue: RecordingQueue,
) -> None:
    # Arrange — two languages, one operator. Every body, because the point is to proof-read
    # the campaign rather than to simulate one delivery.
    campaign = await seed_campaign(
        broadcast_container,
        bodies=(
            BroadcastBody(language=Language.UZ_LATN, text="Bugun kechqurun yangilanish."),
            BroadcastBody(language=Language.RU, text="Сегодня вечером обновление."),
        ),
    )
    operator = FIRST_ACCOUNT + 900

    # Act
    summary = await send_broadcast_test(
        broadcast_ctx(broadcast_container, broadcast_bot, queue), str(campaign), operator
    )

    # Assert — and NOT one recipient row: a test send is not part of the campaign's ledger,
    # and counting it would put the operator inside ``sent_count``.
    assert summary["sent"] == 2
    assert broadcast_session.chats() == (operator, operator)
    assert await recipients(broadcast_container, campaign) == ()
    assert (await campaign_row(broadcast_container, campaign)).sent_count == 0
