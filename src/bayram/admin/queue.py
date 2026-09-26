"""The one path from the panel to the worker, and it is a Redis write and nothing else.

**Why this module exists at all.** Until it did, the admin process had no way to ask the
worker for anything: every job in this system is enqueued by the bot or by a cron, and
``grep -rn "enqueue_job" src/bayram/admin/`` returned nothing. A broadcast is the first admin
action whose work cannot be done inside the request — materialising forty thousand recipient
rows and then sending forty thousand messages is an hour of wall clock — so the seam had to
be built (``BROADCAST_SPEC §3.6``).

**It is a seam and not a shortcut.** The admin process is forbidden a bot token (D10, held
open by :data:`bayram.admin.app.FORBIDDEN_ENV_VARS` and by ``AdminSettings`` having no field to
put one in), so the panel cannot send a message and must not be able to. What it can do is
name a job and hand over an id. Enqueueing needs no credential, no HTTP client and no
``Bot``; the worker owns all three. Nothing in this module imports ``aiogram``, and that is
the property that keeps the split honest rather than merely conventional.

**Its own Redis handle, deliberately.** The queue's :class:`~arq.ArqRedis` is built over a
*separate* connection pool from ``AdminContainer.redis``. The panel's client is
``decode_responses=True`` because it stores sessions and CSRF tokens as text; arq's payloads
are pickled bytes, and decoding them as UTF-8 corrupts them at the first non-trivial read. A
shared pool would work for exactly as long as every payload happened to be ASCII.

**Nothing here connects at construction.** ``arq.create_pool`` pings on the way up, which
would make ``/healthz`` and the bootstrap CLI depend on a Redis that may not be running yet —
the very thing ``bayram.admin.container`` documents it will not do. So the pool is lazy and the
first command is the first connection, exactly as ``bayram.payme.container`` builds its handle,
and an unreachable Redis surfaces as a 503 on the one route that enqueues rather than as a
process that will not boot.

**A failed enqueue is not a failed campaign.** The write and its audit row commit with the
request transaction; the enqueue is the last statement in the handler. The worker's due sweep
(``BROADCAST_SPEC §4.1``) re-enqueues any campaign that is due and has no live job, so this
seam is an optimisation on the latency of the first chunk — never the only path — and a
``None`` from ARQ (the job id is already queued) is the idempotency guarantee working rather
than a failure, the same reading :class:`bayram.runtime.submitter.ArqOrderSubmitter` gives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from arq import ArqRedis
from redis.exceptions import RedisError

from bayram.contracts import Result, err, is_err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger

__all__ = [
    "EXPAND_JOB_NAME",
    "SEND_JOB_NAME",
    "TEST_SEND_JOB_NAME",
    "PAYMENT_NOTIFY_JOB_NAME",
    "SUPPORT_CARD_JOB_NAME",
    "SUPPORT_RELAY_JOB_NAME",
    "VERIFY_GROUP_JOB_NAME",
    "AdminQueue",
    "ArqAdminQueue",
    "NullAdminQueue",
    "RecordedEnqueue",
    "job_id_for_expand",
    "job_id_for_send",
    "job_id_for_test_send",
    "job_id_for_payment_notification",
    "job_id_for_support_card",
    "job_id_for_support_relay",
    "job_id_for_support_group_verification",
]

_LOGGER: Final = get_logger(__name__)

#: ARQ dispatches by function name, so these three strings and the worker's coroutines must
#: agree exactly. They are stated here rather than imported from ``bayram.runtime.broadcast_job``
#: for the reason ``ARCHIVE_DIRNAME`` is stated twice: importing that module would pull the
#: whole runtime container — provider set, ffmpeg post-processor, ``Bot`` — into a process
#: whose entire point is that it holds none of them. The worker restates them beside its own
#: ``assert fn.__name__ == JOB_NAME``, which is what keeps the two copies from drifting.
EXPAND_JOB_NAME: Final[str] = "expand_broadcast_audience"
SEND_JOB_NAME: Final[str] = "send_broadcast_chunk"
TEST_SEND_JOB_NAME: Final[str] = "send_broadcast_test"

#: The fourth, and restated for a HARDER version of the same reason. ``bayram.runtime.payme_jobs``
#: — where the worker's ``notify_payment_settled`` lives, beside ``PAYME_NOTIFY_JOB_NAME`` and
#: ``payme_notify_job_id`` — imports ``aiogram.Bot`` at module level, because sending the
#: message is its whole job. Importing it here to reuse those two symbols would put the
#: Telegram client in the admin process's import graph, which is the exact thing D10 forbids
#: and which ``test_the_seam_can_reach_nothing_that_sends_a_message`` fails on by reading this
#: file's ``import`` statements. So the string is spelled twice, on opposite sides of a process
#: boundary, and ``test_the_restated_job_names_match_the_ones_the_worker_registers`` is what
#: keeps the two copies equal — ARQ dispatches by name, so a rename that compiled on both sides
#: would leave customers unannounced with the money already banked.
PAYMENT_NOTIFY_JOB_NAME: Final[str] = "notify_payment_settled"

#: The fifth and sixth, restated for the fourth and fifth time, and for the hardest version of
#: the reason again: ``bayram.runtime.support_jobs`` holds an ``aiogram.Bot`` because editing a
#: message in the support group and sending one to a customer's private chat are the whole of
#: what those two coroutines do. An import of it here would put the Telegram client in the
#: admin process's import graph — D10 — and
#: ``test_the_seam_can_reach_nothing_that_sends_a_message`` fails on it by reading this file's
#: ``import`` statements.
#:
#: **They are Python identifiers and not the ``support:card_sync`` / ``support:relay`` of the
#: spec's prose.** ARQ dispatches by the registered function's ``__name__``, and every worker
#: module in this repo closes with ``assert fn.__name__ == JOB_NAME`` for exactly that reason
#: (``broadcast_job``, ``payme_jobs``, ``activity_job``). A colon cannot be a function name, so
#: a literal ``"support:relay"`` would be a string the worker could never answer to: the panel
#: would report success, the job id would be real, and the customer's reply would sit in Redis
#: until it expired. The colon lives in the JOB ID instead, where it is a namespace and not a
#: dispatch key — see :func:`job_id_for_support_relay`.
SUPPORT_CARD_JOB_NAME: Final[str] = "sync_support_card"
SUPPORT_RELAY_JOB_NAME: Final[str] = "relay_support_reply"

#: The seventh, restated for the sixth time, and it is the one where the restatement earns its
#: keep most obviously: this job's whole purpose is to talk to Telegram — ``getChat``, then a
#: message into the room — so the module that holds it holds an ``aiogram.Bot`` by construction,
#: and importing it here to borrow one string would put the Telegram client in the import graph
#: of a process D10 forbids a bot token to. ``test_the_seam_can_reach_nothing_that_sends_a_message``
#: reads this file's ``import`` statements and fails on exactly that.
#:
#: **A Python identifier, not the ``support:verify_group`` of ``SUPPORT_TICKETS_SPEC §3.8``'s
#: prose**, for the reason stated above :data:`SUPPORT_CARD_JOB_NAME`: ARQ dispatches by the
#: registered coroutine's ``__name__`` and a colon cannot be a function name. A literal
#: ``"support:verify_group"`` would be accepted by Redis, reported to the panel as a real job
#: id, and answered by nobody — and this is the job whose silence is worst, because an
#: unverified selection looks identical to a verified one until a customer's complaint fails to
#: arrive. The colon lives in the job id; see :func:`job_id_for_support_group_verification`.
VERIFY_GROUP_JOB_NAME: Final[str] = "verify_support_group"

#: Every job id this seam mints starts here, so one ``SCAN`` shows an operator every broadcast
#: job in flight without knowing which of the three it is looking for.
_JOB_ID_PREFIX: Final[str] = "broadcast"

#: The same idea one domain along: ``SCAN support:*`` is every ticket job in flight. A second
#: prefix rather than one shared namespace because the two families are operated by different
#: people under different pressure — a stuck campaign is an incident and a stuck card sync is
#: a card that reads one status behind — and an operator hunting one must not have to page
#: through the other.
_SUPPORT_JOB_ID_PREFIX: Final[str] = "support"


def job_id_for_expand(broadcast_id: UUID) -> str:
    """Deterministic: one expansion per campaign, ever.

    ``job_id_for_*`` rather than ``*_job_id``, following ``bayram.pipeline.worker.job_id_for``.
    The prefix order is not cosmetic: ``test_send_job_id`` is a module-level callable whose
    name starts with ``test_``, so pytest collects it out of the test module that imports it
    and reports it as an error with a missing fixture.

    ARQ refuses to queue an id it already holds, so a double-clicked Create costs nothing and
    two replicas racing the same request cannot both start materialising the audience.
    """
    return f"{_JOB_ID_PREFIX}:expand:{broadcast_id}"


def job_id_for_send(broadcast_id: UUID) -> str:
    """Deterministic: at most one chunk job per campaign in flight (``BROADCAST_SPEC §4.4``).

    That is what stops two workers claiming overlapping windows of the same recipient table.
    A refused duplicate is reported as success by :class:`ArqAdminQueue` — the campaign is
    already being sent, which is what the caller asked for — and a campaign whose chunk job
    has since finished is picked up by the due sweep, so the exclusivity costs no progress.
    """
    return f"{_JOB_ID_PREFIX}:send:{broadcast_id}"


def job_id_for_test_send(broadcast_id: UUID) -> str:
    """Unique per call, and that is the one place determinism would be wrong.

    An operator asks for a second test send *because* they changed the body. Under a
    deterministic id ARQ would refuse the repeat for as long as the first job's result lives
    (``keep_result``, an hour by default) and the panel would silently do nothing — so the id
    carries a fresh suffix. Minting it here rather than letting ARQ generate one keeps the id
    knowable before the call, which is what lets the failure path name the job it lost.
    """
    return f"{_JOB_ID_PREFIX}:test:{broadcast_id}:{uuid4().hex}"


def job_id_for_payment_notification(public_ref: str) -> str:
    """Deterministic, and the determinism is doing two jobs rather than one.

    Byte-for-byte ``bayram.runtime.payme_jobs.payme_notify_job_id``, restated for the reason
    :data:`PAYMENT_NOTIFY_JOB_NAME` is. The two callers are now THREE processes — the Payme
    gateway's post-commit enqueue, the worker's own five-minute backstop sweep, and this panel
    — and ARQ refuses an id it already holds, so all three collapse onto ONE job rather than
    three messages to one customer. A second spelling would not break a build; it would quietly
    disable that collapse, and the symptom would be a customer told three times.

    Keyed on ``public_ref`` and never on the intent's ``idempotency_key``: that key is shaped
    ``topup:{telegram_user_id}:{scope}:{seq}``, so keying on it would write a customer's
    Telegram id into a Redis key name and into the worker's log lines — which is precisely what
    ``public_ref`` was minted to avoid.
    """
    return f"{PAYMENT_NOTIFY_JOB_NAME}:{public_ref}"


def job_id_for_support_card(ticket_id: UUID) -> str:
    """Unique per call, and determinism here would be a card that lies.

    This is :func:`job_id_for_test_send`'s case rather than :func:`job_id_for_send`'s, and the
    difference is worth stating because the ticket id is right there and a deterministic id
    looks tidier. ``keep_result`` is 3600 seconds and ARQ refuses an id whose result is still
    in Redis — so an operator who claims a ticket and resolves it twenty minutes later would
    get ONE card sync, and the group card would sit at ``🆕 New`` for the rest of the hour
    while the board said ``resolved``. The card is the copy staff actually work from, so a
    stale one is worse than a duplicate edit: editing a message to the text it already has is
    a no-op Telegram absorbs, and there is nothing else for a second sync to get wrong.

    The id is still MINTED here rather than left to ARQ, so the failure path can name the job
    it lost — the reason :func:`job_id_for_test_send` gives.
    """
    return f"{_SUPPORT_JOB_ID_PREFIX}:card:{ticket_id}:{uuid4().hex}"


def job_id_for_support_relay(event_id: UUID) -> str:
    """Deterministic, and keyed on the EVENT rather than on the ticket. Both halves matter.

    Deterministic because one composed reply must reach the customer exactly once: a
    double-clicked Send, or a retried request, collapses onto the job already queued instead
    of putting the same paragraph in somebody's phone twice. That is
    :func:`job_id_for_payment_notification`'s reading of ARQ's duplicate refusal, in the one
    other place where the thing being deduplicated is a message to a person.

    Keyed on ``support_ticket_events.id`` and never on ``support_tickets.id``, because a
    ticket is a conversation and gets many replies — a ticket-keyed id would refuse the second
    answer to the same customer for as long as the first job's result lived, which is the
    exact hour an operator is most likely to send a correction. The event row is written in
    the request's own transaction before the enqueue, so its id exists and is stable; the
    worker stamps ``relayed_at`` on that same row when the message actually lands, which is
    what makes "composed but never delivered" visible on the timeline instead of assumed away.

    An event id is a UUID this system minted and carries no customer identifier, so this key
    puts nothing into a Redis key name or a worker log line —
    :func:`job_id_for_payment_notification`'s constraint, honoured the same way.
    """
    return f"{_SUPPORT_JOB_ID_PREFIX}:relay:{event_id}"


def job_id_for_support_group_verification(chat_id: int) -> str:
    """Unique per call, and a deterministic id here would make the feature unusable.

    :func:`job_id_for_support_card`'s case rather than :func:`job_id_for_support_relay`'s, and
    the reasoning is sharper: ``keep_result`` is 3600 seconds and ARQ refuses an id whose result
    is still in Redis, so a chat-keyed id would refuse every re-check of the SAME chat for an
    hour. That hour is exactly the loop this feature exists to support — an operator selects a
    group, is told the bot cannot post there, adds the bot or grants it permission, and presses
    Select again. Under a deterministic id the second press would be accepted, enqueue nothing,
    and leave the row showing the failure the operator has just fixed until the result expired.

    Nothing is lost by allowing duplicates. The job is idempotent by construction: it asks
    Telegram what is true now and overwrites ``verified_at`` or ``verification_error`` with the
    answer, so two runs a second apart write the same row twice. That is the same reading
    :func:`job_id_for_support_card` gives its own duplicates — a repeated no-op beats a stale
    truth.

    The id is still minted here rather than left to ARQ so a failed enqueue can name the job it
    lost, and a chat id is a negative integer Telegram issued about a ROOM: unlike a customer's
    Telegram id it identifies no person, so putting it in a Redis key name and a worker log line
    breaks no rule :func:`job_id_for_payment_notification` set.
    """
    return f"{_SUPPORT_JOB_ID_PREFIX}:verify:{chat_id}:{uuid4().hex}"


class AdminQueue(Protocol):
    """The seven things the panel may ask the worker to do, and no eighth.

    A protocol rather than a concrete client so a test never needs a Redis, and so the
    surface stays a list somebody has to extend on purpose. Every method returns a
    ``Result`` carrying the job id: an enqueue is I/O over a network and the repo's rule is
    that such a failure crosses a boundary as an ``Err`` and not as an exception —
    :func:`bayram.admin.errors.unwrap` turns it into the standard envelope at the handler.

    There is no ``enqueue_cancel`` or ``enqueue_pause``. Pausing is a column, read by the
    chunk job every twenty-five messages (``BROADCAST_SPEC §4.4``); enqueueing a job to stop
    a job would put the two in a race whose loser sends messages after the operator was told
    it had stopped.

    **The fourth method widened a surface that was closed at three, so here is the argument.**
    The sentence above used to read "three things … and no fourth", and that was not
    decoration: a protocol somebody has to edit on purpose is the mechanism that keeps the
    panel from growing a general "run this job" hole. :meth:`enqueue_payment_notification`
    earns the edit because the population it serves is already ON the board —
    ``paidNeverAnnounced`` is a first-class count on the rail screen (``BILLING_RAIL_BOARD
    §4``) — and a finding whose remedy lives in a different tool over SSH is a finding that
    stays unactioned. Putting the remedy next to the finding is how a backlog stops being
    permanent.

    The rejected alternative was enqueuing ARQ from the handler directly, which would have
    needed no protocol change at all. It breaks the seam that lets every test in
    ``tests/test_admin`` run with no Redis and no worker — ``NullAdminQueue`` records the call
    that was not made, and a router test asserts on its ARGUMENTS — and it would put a second
    ARQ client in a process that already documents why it holds exactly one.

    **The fifth and sixth widen it again, and the paragraph above is the standard they had to
    meet.** :meth:`enqueue_support_card_sync` and :meth:`enqueue_support_reply` are the whole
    of what a panel-side ticket action can ask for, and both exist because the admin process
    is structurally forbidden from talking to Telegram (``ADMIN_PANEL_PLAN D10 / §4.2``) while
    a ticket lives in two places at once: a row this process owns, and a card in a support
    group only the worker can edit. An operator who moves a ticket on the board and leaves the
    group card reading ``🆕 New`` has not moved it as far as the staffer working from the card
    is concerned, and there is no third process that could reconcile them.

    **There is deliberately no ``enqueue_support_note``.** A note is an internal line on an
    append-only timeline: nothing leaves the building, the card's rendered state does not
    change, and a job to tell the worker about it would be a Redis write, a deploy-replayed
    coroutine and an edit to a Telegram message whose text is identical. The rule this follows
    is :meth:`enqueue_send`'s sibling — "there is no ``enqueue_cancel``" — and it is the same
    rule: the seam carries work the worker must do, never news it might like.

    **The seventh widens it once more, and it meets the standard the fourth set more squarely
    than any of them.** :meth:`enqueue_support_group_verification` exists because
    ``POST /support/groups/select`` accepts a chat id **an operator typed** — Telegram has no
    "list my groups" API, so a group the bot was already in when the feature shipped can never
    be discovered and a pasted number is the only route to it (``SUPPORT_TICKETS_SPEC §3.8``).
    A pasted id is an unverified CLAIM: a typo, a room the bot was thrown out of, a channel it
    cannot write in, or a group that has since migrated to a new id. The panel cannot check any
    of that, because checking means asking Telegram and this process is structurally forbidden
    to (``ADMIN_PANEL_PLAN D10 / §4.2``). So the remedy has to live where the finding does, for
    the reason ``enqueue_payment_notification`` was admitted: a screen that reports a selection
    it has no way to validate, with the validation living in a different tool over SSH, is a
    screen that lies by omission for as long as nobody runs the other tool.

    **There is deliberately no ``enqueue_support_group_unverification`` beside it**, and the
    clear route enqueues nothing at all. Clearing asks the worker for no work: nothing has to be
    posted, checked or edited, the rows it would examine are the ones this request has already
    written, and a job that told the worker "there is now no support group" would be news rather
    than work — :meth:`enqueue_send`'s "there is no ``enqueue_cancel``" rule, a third time.
    """

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        """Materialise the campaign's recipient rows, as of ``now``.

        ``now`` is the instant the audience is frozen at, passed as an argument rather than
        read by the worker, because expansion is a resumable multi-chunk job and every chunk
        must compile the segment against the *same* instant — a rule like "joined in the last
        thirty days" that re-reads the clock per chunk selects a different population each
        time, and the audience would not be frozen at all.
        """
        ...

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        """Start (or resume) delivery to the rows that are already there.

        Takes no instant: the send re-checks eligibility against fresh ``users`` state by
        design, so the worker's clock is the right one and a stale one would be a lie.
        """
        ...

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        """Send the composed body to exactly one account — the operator's own.

        The recipient is an argument and not a lookup, so the job cannot be talked into
        addressing anyone but the account the handler resolved.
        """
        ...

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """Re-announce ONE settled payment, named by the reference that crosses to the rail.

        **``Result[str | None]`` where its three siblings return ``Result[str]``, and the
        ``None`` is the point.** ARQ answers ``None`` when the deterministic job id is already
        queued, and for the broadcast trio that is read as success — the campaign is already
        being sent, which is what the caller asked for. Here the same fact is the ANSWER: the
        operator pressed "re-send the confirmation" and needs to know whether they queued a
        message or landed on one that was already in flight, which the response reports as
        ``isReplay``. Collapsing it to the job id, as :meth:`enqueue_send` does, would leave
        the panel unable to say which happened without asking ARQ a second question — and that
        second question races the worker, which may have finished the job between the two.

        ``public_ref`` and never the intent's ``idempotency_key`` or Telegram id: see
        :func:`job_id_for_payment_notification`. This method therefore cannot carry a customer
        identifier into Redis even if a caller had one to hand.
        """
        ...

    async def enqueue_support_card_sync(self, ticket_id: UUID) -> Result[str]:
        """Re-render ONE ticket's card in the support group from the row as it now stands.

        Takes the ticket and nothing else — no status, no assignee, no rendered text. The
        worker re-reads the row, which is what makes this job safe to replay and safe to lose:
        ARQ runs ``retry_jobs=True`` and SIGTERM cancels running jobs, so every job in this
        system is replayed on every deploy, and a job carrying the state it was enqueued WITH
        would repaint the card with an hour-old status the moment it ran late. The row is the
        truth; this is a nudge to go and look at it.

        It is therefore also fire-and-forget in the strong sense: a ticket whose card sync was
        lost is a ticket whose card is stale, never one whose move did not happen. The move and
        its audit row are already committed by the time this is called.
        """
        ...

    async def enqueue_support_reply(self, ticket_id: UUID, *, event_id: UUID) -> Result[str]:
        """Deliver an operator's reply to the customer's private chat.

        Both ids travel. ``event_id`` is the authority — it names the
        ``support_ticket_events`` row holding the exact text to send and the row the worker
        stamps ``relayed_at`` on, and it is what the deterministic job id is built from, so a
        double-clicked Send cannot put the same paragraph in somebody's phone twice.
        ``ticket_id`` rides along because the worker needs the ticket to know WHO and in WHICH
        LANGUAGE: ``support_tickets.language`` is the locale the ticket was opened in, and
        answering in the account's language today would send the one message where being
        understood is the entire point in a language the customer may no longer read.

        Passing the two ids rather than the text is the same decision
        :meth:`enqueue_support_card_sync` makes, for the same replay reason — and one more:
        the reply is a customer's words' answer, and a payload carrying it would put the
        conversation into Redis, where nothing sweeps it.
        """
        ...

    async def enqueue_support_group_verification(self, chat_id: int) -> Result[str]:
        """Find out whether the bot can really post in the chat just selected, and record it.

        Takes the chat and nothing else. The worker re-reads the row for the ``thread_id`` to
        post into and the ``source`` that says whether it is checking Telegram's word or an
        operator's paste — :meth:`enqueue_support_card_sync`'s "the row is the truth; this is a
        nudge to go and look at it", which is what makes the job safe to replay after a deploy.

        **It is enqueued after the selection is COMMITTED, never before**, and this job feels
        the race more sharply than the two above it: it opens its own session, reads the chat by
        id, and a job that overtook the request's commit would find no such row — then either
        create nothing and report success against a selection nobody can see, or write a
        verification verdict about a chat that does not exist yet. ``routers/support_groups.py``
        commits and then enqueues for exactly this.

        **Selecting enqueues; clearing does not.** There is nothing to verify about a chat
        nobody is posting to, and a verdict recorded against a chat an operator has just
        unselected is a red badge on a row that no longer claims anything.
        """
        ...

    async def aclose(self) -> None:
        """Release whatever the implementation holds. Called once, by the container."""
        ...


class ArqAdminQueue:
    """:class:`AdminQueue` over ARQ. Production, and the only implementation that does I/O.

    Owns the :class:`~arq.ArqRedis` it is handed: the container builds the pool, gives it to
    this object and closes it through :meth:`aclose`, so the panel never holds a second Redis
    handle it could accidentally issue a session command on.
    """

    __slots__ = ("_redis",)

    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        return await self._enqueue(
            EXPAND_JOB_NAME,
            str(broadcast_id),
            now.isoformat(),
            job_id=job_id_for_expand(broadcast_id),
        )

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        return await self._enqueue(
            SEND_JOB_NAME, str(broadcast_id), job_id=job_id_for_send(broadcast_id)
        )

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        return await self._enqueue(
            TEST_SEND_JOB_NAME,
            str(broadcast_id),
            telegram_user_id,
            job_id=job_id_for_test_send(broadcast_id),
        )

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """The one caller of :meth:`_dispatch` that keeps the duplicate as a duplicate."""
        return await self._dispatch(
            PAYMENT_NOTIFY_JOB_NAME,
            public_ref,
            job_id=job_id_for_payment_notification(public_ref),
        )

    async def enqueue_support_card_sync(self, ticket_id: UUID) -> Result[str]:
        return await self._enqueue(
            SUPPORT_CARD_JOB_NAME,
            str(ticket_id),
            job_id=job_id_for_support_card(ticket_id),
        )

    async def enqueue_support_reply(self, ticket_id: UUID, *, event_id: UUID) -> Result[str]:
        """A duplicate is read as success here, unlike :meth:`enqueue_payment_notification`.

        Both deduplicate a message to one person on a deterministic id, so the divergence is
        stated rather than left to look like an oversight. The payment route reports the
        duplicate as ``isReplay`` because the operator pressed "re-send the confirmation" and
        the interesting answer is which of the two happened. Here the operator pressed Send on
        a reply they just composed, and "that reply is already on its way" is what they asked
        for — surfacing it as a distinct outcome would put a question in front of somebody who
        has none.
        """
        return await self._enqueue(
            SUPPORT_RELAY_JOB_NAME,
            str(ticket_id),
            str(event_id),
            job_id=job_id_for_support_relay(event_id),
        )

    async def enqueue_support_group_verification(self, chat_id: int) -> Result[str]:
        """The chat id travels as a STRING, like every other argument this seam sends.

        ARQ pickles its payloads, so an ``int`` would survive the round trip intact — and it is
        sent as text anyway, because every job in this file takes its subject as a string
        (``str(broadcast_id)``, ``public_ref``, ``str(ticket_id)``) and one job that did not
        would be one worker signature that has to remember which. A chat id is a 64-bit integer
        the worker parses back; ``_job_uuid``'s sibling on that side is where a malformed one is
        refused, and a job whose subject cannot be parsed is terminal rather than retried.
        """
        return await self._enqueue(
            VERIFY_GROUP_JOB_NAME,
            str(chat_id),
            job_id=job_id_for_support_group_verification(chat_id),
        )

    async def aclose(self) -> None:
        # ``aclose`` since redis-py 5.0.1; ``close`` is deprecated. The pinned ``types-redis``
        # 4.6 stubs predate the rename and shadow redis-py's own inline types, so the call is
        # correct at runtime and invisible to mypy — the same suppression
        # ``bayram.admin.container`` carries, for the same stub.
        await self._redis.aclose()  # type: ignore[attr-defined]

    async def _dispatch(self, job: str, *arguments: object, job_id: str) -> Result[str | None]:
        """One enqueue, one failure taxonomy, and the duplicate reported AS a duplicate.

        Never raises. ``RedisError`` is caught beside ``OSError`` — and ``ArqOrderSubmitter``,
        which catches the pair ``(TimeoutError, OSError)``, is the precedent this widens rather
        than contradicts. ``TimeoutError`` has subclassed ``OSError`` since 3.10, but redis-py's
        own exceptions do not: a ``ConnectionError`` or a ``ResponseError`` raised inside the
        client would otherwise leave this method as an exception, and the panel would answer a
        Redis blip with a 500 instead of the 503 that tells an operator to look at Redis.

        ``ok(None)`` means ARQ already held this id. Split out of :meth:`_enqueue` rather than
        given a boolean flag, because the two readings are two different sentences to an
        operator and the type is what stops one being mistaken for the other: the broadcast
        trio reads a duplicate as success and says so in :meth:`_enqueue`, while
        :meth:`enqueue_payment_notification` reports it as ``isReplay``.
        """
        try:
            handle = await self._redis.enqueue_job(job, *arguments, _job_id=job_id)
        except (OSError, RedisError) as exc:
            return err(
                StorageError(
                    "could not reach Redis to enqueue the job",
                    context={"job": job, "job_id": job_id},
                    cause=exc,
                )
            )
        return ok(None if handle is None else str(handle.job_id))

    async def _enqueue(self, job: str, *arguments: object, job_id: str) -> Result[str]:
        """:meth:`_dispatch` for the three campaign jobs, where a duplicate IS success."""
        outcome = await self._dispatch(job, *arguments, job_id=job_id)
        if is_err(outcome):
            return err(outcome.error)
        if outcome.value is None:
            # ARQ returns None when the id is already queued. That is the idempotency
            # guarantee doing its job, not a failure: the work is already under way.
            _LOGGER.info(
                "broadcast job was already queued; ignoring the duplicate",
                extra={"event": "admin.queue.duplicate", "job": job, "job_id": job_id},
            )
            return ok(job_id)
        return ok(outcome.value)


@dataclass(frozen=True, slots=True)
class RecordedEnqueue:
    """One call :class:`NullAdminQueue` did not make, kept so a test can assert on it.

    **Four nullable subject fields rather than one ``subject: str``.** The seven jobs are about
    four different kinds of thing — three campaigns, one payment, two tickets and one chat — and
    a single stringly subject would let a test that meant to assert on a campaign id pass on a
    public reference, a ticket id or a chat id that happened to be equal. Exactly one of the
    four is set on any row, and which one says which job family the call belongs to without
    parsing :attr:`job`. A new field is the right shape for a NEW family and a wrong one for a
    variant of an existing family; see :attr:`ticket_id`, which serves two jobs, and
    :attr:`chat_id`, which was added under that rule rather than around it.
    """

    job: str
    job_id: str
    arguments: tuple[object, ...]
    #: The campaign, for the three broadcast jobs; ``None`` for a payment notification.
    broadcast_id: UUID | None = None
    #: The intent's rail-facing reference, for a payment notification; ``None`` otherwise.
    #: Never an idempotency key and never a Telegram id — see
    #: :func:`job_id_for_payment_notification`.
    public_ref: str | None = None
    #: The ticket, for the card sync and the reply. ONE field for both jobs rather than one
    #: each, because both are about the same subject and :attr:`job` already distinguishes
    #: them; the reply's event id is not lifted out beside it for the same reason — it is in
    #: :attr:`arguments`, where a test that cares reads it, and hoisting every argument of
    #: every job onto this dataclass is how a recorder becomes a second copy of the payload.
    ticket_id: UUID | None = None
    #: The Telegram chat, for a support-group verification. An ``int`` and never a ``str``,
    #: unlike the value that goes on the wire: a test asserting ``call.chat_id == -1001`` is
    #: asserting about the chat the handler resolved, and comparing the stringified form would
    #: pass on ``"-1001"`` from a caller that had built the argument by hand. The 64-bit width
    #: is the reason this is worth saying — a chat id truncated to 32 bits is a different chat
    #: and an equal-looking prefix.
    chat_id: int | None = None


class NullAdminQueue:
    """:class:`AdminQueue` that records the call and enqueues nothing. Two uses, one class.

    **In tests** it is the default injection: a router test asserts that creating a campaign
    asked for an expansion, with the campaign's id and the request's instant, without a Redis
    and without a worker to answer. Recording rather than counting is what makes that an
    assertion about the *arguments* — a seam that enqueued the wrong id would pass a counter.

    **In a deployment with no worker** it is constructed ``refusing=True``, and then every
    call is recorded and answered with an ``Err``. Accepting a campaign nothing will ever
    send is the worse failure by a distance: the operator is told it went out, and the only
    evidence otherwise is a counter that never moves.

    The refusal carries a :class:`~bayram.errors.StorageError` and not the ``ConfigError``
    ``BROADCAST_SPEC §3.6`` names, because the spec asked for "a legible 503" and
    :data:`bayram.admin.errors.STATUS_BY_ERROR_CODE` maps ``CONFIG_INVALID`` to **422**. A
    missing worker is an unavailable dependency, not a malformed request, so the code that
    renders the status the spec asked for is the one that is used.
    """

    __slots__ = ("_refusing", "calls")

    def __init__(self, *, refusing: bool = False) -> None:
        self.calls: list[RecordedEnqueue] = []
        self._refusing = refusing

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        return self._record(
            EXPAND_JOB_NAME,
            broadcast_id,
            job_id_for_expand(broadcast_id),
            (str(broadcast_id), now.isoformat()),
        )

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        return self._record(
            SEND_JOB_NAME, broadcast_id, job_id_for_send(broadcast_id), (str(broadcast_id),)
        )

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        return self._record(
            TEST_SEND_JOB_NAME,
            broadcast_id,
            job_id_for_test_send(broadcast_id),
            (str(broadcast_id), telegram_user_id),
        )

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """Records the call and answers ``ok(job_id)`` — i.e. **never a replay**.

        A fake that returned ``ok(None)`` on the second call would be modelling ARQ's job
        registry, which this class deliberately does not have: ``NullAdminQueue`` keeps a list
        of calls, not a queue, and a duplicate-detection rule invented here would be asserted
        by tests and true of nothing. A router test that needs the replay branch overrides this
        method (see ``tests/test_admin/test_billing_router.py``), which keeps the branch's own
        behaviour asserted without this class growing a second, fictional idempotency store.
        """
        entry = RecordedEnqueue(
            job=PAYMENT_NOTIFY_JOB_NAME,
            job_id=job_id_for_payment_notification(public_ref),
            arguments=(public_ref,),
            public_ref=public_ref,
        )
        self.calls.append(entry)
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the announcement cannot be queued",
                    context={"job": entry.job, "public_ref": public_ref},
                )
            )
        return ok(entry.job_id)

    async def enqueue_support_card_sync(self, ticket_id: UUID) -> Result[str]:
        return self._record_ticket(
            SUPPORT_CARD_JOB_NAME,
            ticket_id,
            job_id_for_support_card(ticket_id),
            (str(ticket_id),),
        )

    async def enqueue_support_reply(self, ticket_id: UUID, *, event_id: UUID) -> Result[str]:
        return self._record_ticket(
            SUPPORT_RELAY_JOB_NAME,
            ticket_id,
            job_id_for_support_relay(event_id),
            (str(ticket_id), str(event_id)),
        )

    async def enqueue_support_group_verification(self, chat_id: int) -> Result[str]:
        return self._record_chat(
            VERIFY_GROUP_JOB_NAME,
            chat_id,
            job_id_for_support_group_verification(chat_id),
            (str(chat_id),),
        )

    async def aclose(self) -> None:
        """Nothing is held, so nothing is released. Present because the protocol has it."""

    def _record_chat(
        self, job: str, chat_id: int, job_id: str, arguments: tuple[object, ...]
    ) -> Result[str]:
        """:meth:`_record_ticket` one family along, filing the subject under :attr:`chat_id`.

        A third method rather than a ``subject_field`` parameter, for the reason the second one
        gives: the whole argument for typed subject fields is that a test asserting on a
        campaign cannot accidentally pass on a chat, and threading the field name through as a
        string hands that distinction back to whoever typed it.

        **What a refusing deployment leaves here is the worst of the three and is worth stating
        plainly.** A refused card sync leaves a card one status behind; a refused relay leaves a
        visible ``relayedAt`` null. A refused verification leaves a SELECTION THAT NOTHING HAS
        CHECKED — ``verified_at`` null and ``verification_error`` null, which is indistinguishable
        from "the job is still queued". The operator is told, because the handler ``unwrap``s
        this into a 503 over a committed selection; the panel's job is to render "never checked"
        as its own state rather than as an absence, and that is argued on
        :class:`~bayram.db.admin.views.BotChatListItem`. The selection itself is not lost: it and
        its audit row are committed before this is called.
        """
        self.calls.append(
            RecordedEnqueue(job=job, chat_id=chat_id, job_id=job_id, arguments=arguments)
        )
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the chat cannot be verified",
                    context={"job": job, "chat_id": chat_id},
                )
            )
        return ok(job_id)

    def _record_ticket(
        self, job: str, ticket_id: UUID, job_id: str, arguments: tuple[object, ...]
    ) -> Result[str]:
        """:meth:`_record` for the two ticket jobs, filing the subject under the right field.

        A second method rather than a ``subject_field`` parameter on :meth:`_record`: the
        whole argument for three typed subject fields on :class:`RecordedEnqueue` is that a
        test asserting on a campaign cannot accidentally pass on a ticket, and threading the
        field name through as a string would hand that distinction back to whoever typed it.

        **A refusing deployment refuses these two exactly as it refuses the others, and the
        consequence differs.** A refused expansion is a campaign that will not go out; a
        refused card sync is a card that reads one status behind a board that is already
        correct, and a refused relay is a reply the customer never receives with the timeline
        showing ``relayed_at`` empty — which is precisely the "composed but never delivered"
        state ``SupportTicketEventItem`` publishes that clock to make visible. Neither loses
        the operator's work: the row and its audit entry are committed before this is called.
        """
        self.calls.append(
            RecordedEnqueue(job=job, ticket_id=ticket_id, job_id=job_id, arguments=arguments)
        )
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the ticket job cannot be queued",
                    context={"job": job, "ticket_id": str(ticket_id)},
                )
            )
        return ok(job_id)

    def _record(
        self, job: str, broadcast_id: UUID, job_id: str, arguments: tuple[object, ...]
    ) -> Result[str]:
        """Record first, refuse second. The three campaign jobs only.

        What the panel *tried* to enqueue is the interesting half of a deployment that
        cannot enqueue anything.
        """
        self.calls.append(
            RecordedEnqueue(job=job, broadcast_id=broadcast_id, job_id=job_id, arguments=arguments)
        )
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the broadcast cannot be queued",
                    context={"job": job, "broadcast_id": str(broadcast_id)},
                )
            )
        return ok(job_id)
