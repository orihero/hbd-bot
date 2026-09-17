"""The three worker jobs support needs: repaint the card, answer the customer, check the room.

**Why these are jobs at all.** A ticket lives in two places at once — a row in
``support_tickets``, which the admin panel owns and can change inside one request, and a card
in a Telegram support group, which only a process holding the bot token can touch. The panel
holds no token and must not be able to (``ADMIN_PANEL_PLAN D10 / §4.2``, enforced by
``bayram.admin.app.FORBIDDEN_ENV_VARS`` and by ``AdminSettings`` having no field to put one
in), so an operator who moves a ticket on the board has not moved it as far as the staffer
working from the card is concerned until something over here goes and redraws it. That
something is :func:`sync_support_card`. The same split is why an operator's reply cannot be
delivered by the process that composed it, which is :func:`relay_support_reply`. Both are the
argument :mod:`bayram.runtime.payme_jobs` makes for the Payme gateway and
:mod:`bayram.runtime.broadcast_job` makes for the panel, taken a third time.

**The row is the record, because every job here is replayed on every deploy.** ARQ runs with
``retry_jobs=True`` and SIGTERM cancels running tasks, so neither of these coroutines may
carry the state it acts on. Both are handed ids and re-read:

* :func:`sync_support_card` takes a ticket id and nothing else. A job carrying the status it
  was enqueued with would repaint the card with an hour-old badge the moment it ran late, and
  a replayed one would repaint it with a badge that is now two moves stale. Re-reading makes
  the job safe to replay, safe to lose and safe to run out of order — the worst outcome of a
  duplicate is an edit to the text the message already has, which Telegram refuses and this
  module swallows;
* :func:`relay_support_reply` takes the EVENT id, and ``support_ticket_events.relayed_at`` is
  the replay guard. The event row says a reply was COMPOSED; the clock says it was
  DELIVERED. Collapsing the two would make a customer who blocked the bot indistinguishable
  from one who read the answer, which is the single fact an operator picking the ticket up
  tomorrow most needs — and it is published on the timeline for exactly that reason
  (:class:`bayram.db.admin.views.SupportTicketEventItem`).

**A RELAY IS THE SAME ACT AS A STAFFER'S REPLY, THROUGH A DIFFERENT DOOR, AND IT OWES THE
CUSTOMER THE SAME THREE THINGS.** One message, to one person, out of one catalogue key: render
through :func:`bayram.bot.handlers.support.relay_text_for` so the length is bounded against the
FINISHED message, stamp ``relayed_at``, and re-point ``support_tickets.prompt_message_id`` at
the relay's own ``message_id`` so the reply it invites resolves back to the ticket instead of
into a half-finished wizard. This module shipped doing none of the three — it owned a template
key and a raw-body length of its own, and it discarded what ``send_message`` returned — while
the staff-group door next to it did all three correctly. Both fixes are therefore made by
CALLING that door's code rather than by a second copy of it, and the standing rule is written
down where it will be read next time: **a fix to one of these two doors is not finished until
the other door has been checked.** See ``SUPPORT_TICKETS_SPEC §3.5b``.

**THE SUPPORT GROUP GETS ITS OWN SEND BUDGET, AND THAT IS THE ONE THING IN THIS MODULE THAT
PROTECTS SOMETHING OTHER THAN TICKETS.** Telegram rate-limits a SINGLE chat at roughly twenty
messages a minute — far tighter than the ~30/s across DIFFERENT chats that
``BAYRAM_BROADCAST_SEND_RATE_PER_S`` is sized against — and the shared ``SendPacer`` bucket
(``bayram:send:budget``) meters the TOKEN, not the chat. So a backlog of card syncs into one
group, sent against the shared bucket, is comfortably inside the deployment's configured rate
and still earns a ``retry_after`` on the bot token; and a flood wait on the token stops
customer ORDERS, not merely tickets. The group therefore charges
:data:`GROUP_SEND_BUDGET_KEY`, a bucket of its own — see :func:`group_pacer` for what that
does and does not buy, including the honest shortfall.

**Nothing here sweeps, and that is a deliberate difference from the Payme jobs.** Arm three of
``run_payme_sweep`` exists because a settled payment nobody was told about is INVISIBLE: the
row looks healthy and nothing would ever read it again. Neither failure here is invisible. A
card that never reached the group is a ticket with ``is_posted_to_group=False`` on the board,
and a reply that never reached the customer is a ``REPLY`` row with no ``relayed_at`` on the
timeline, rendered as such. Both are already in front of the operator whose problem they are,
and a cron that retried them would be a scheduler pressing Send on somebody's behalf. What is
missing — and is named here rather than left to be discovered — is that an operator has to
notice: see the module's note in ``SUPPORT_TICKETS_SPEC`` and the report accompanying this
change.

**THE THIRD JOB IS NOT ABOUT A TICKET AT ALL, AND IT IS HERE BECAUSE OF THE SAME SPLIT.** The
support group stopped being ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` and became a row in ``bot_chats``
that an operator picks in the panel (``SUPPORT_TICKETS_SPEC §3.8``). The panel can write that
row and cannot say a word to Telegram, so "is this actually a chat the bot can post in?" is a
question only a process holding the token can answer — and it is a question that MUST be
answered, because Telegram has no "list my groups" API and the only route to a group the bot was
already sitting in is an operator typing its id. :func:`verify_support_group` is therefore the
single thing standing between a mistyped digit and a support inbox that is silently dead, which
is why its failure messages are prose an operator can act on rather than an exception's ``repr``
— see :func:`verification_failure_for`.

The store is built here from the container's session factory rather than taken off
``AppContainer``, which is :func:`bayram.runtime.payme_jobs.build_worker_payme_ledger`'s
precedent and :func:`bayram.runtime.broadcast_job._store`'s: the container carries the ports
the BOT holds, and neither of these is one — the bot never repaints a panel-side change and
never relays an operator's words.

The registration lives in :mod:`bayram.runtime.jobs` with every other job. A job that is not
in that list is a job ARQ will never dispatch, silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from arq.worker import Retry
from redis.asyncio import Redis

from bayram.bot.delivery import is_blocked_by_customer, order_reference
from bayram.bot.handlers.support import post_card, relay_text_for, support_group_target
from bayram.bot.support_card import card_keyboard, render_card
from bayram.bot_chats import BotChatDirectory, BotChatSnapshot
from bayram.config import Settings
from bayram.contracts import BotChatType, Result, SupportTicketEventKind, is_err, is_ok
from bayram.db.admin.support_tickets import get_ticket
from bayram.db.admin.views import SupportTicketDetail, SupportTicketEventItem
from bayram.db.base import utc_now
from bayram.db.guard import run_guarded
from bayram.db.support_tickets import SqlSupportTickets
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.runtime.container import AppContainer
from bayram.runtime.pacer import (
    SEND_PARK_KEY,
    InMemorySendBudgetStore,
    PacerPolicy,
    RedisSendBudgetStore,
    SendBudgetStore,
    SendPacer,
)
from bayram.support import SupportTicketStore, TicketSnapshot

__all__ = [
    "SUPPORT_CARD_JOB_NAME",
    "SUPPORT_RELAY_JOB_NAME",
    "SUPPORT_VERIFY_JOB_NAME",
    "SUPPORT_CARD_MAX_TRIES",
    "SUPPORT_RELAY_MAX_TRIES",
    "SUPPORT_VERIFY_MAX_TRIES",
    "GROUP_SEND_BUDGET_KEY",
    "GROUP_SEND_RATE_PER_S",
    "GROUP_PACER_POLICY",
    "VERIFICATION_CONFIRMATION",
    "VerificationFailure",
    "verification_failure_for",
    "build_worker_support_store",
    "group_pacer",
    "sync_support_card",
    "relay_support_reply",
    "verify_support_group",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function NAME, and for both of these the enqueue side is ANOTHER PROCESS
#: — the admin panel, through :mod:`bayram.admin.queue`, which restates these same two strings
#: rather than importing them (importing this module would put ``aiogram.Bot`` in the import
#: graph of a process that is structurally forbidden a token). Both copies are asserted against
#: their functions: here at the bottom of this module, and by
#: ``test_the_restated_support_job_names_match_the_ones_the_worker_registers`` in
#: ``tests/test_admin/test_queue.py``, which is the only place the two halves are compiled
#: together.
#:
#: **They are Python identifiers and not the ``support:card_sync`` / ``support:relay`` of the
#: spec's prose.** A colon cannot be a function ``__name__``, so a literal ``"support:relay"``
#: would be a string this worker could never answer to — the panel would report success, the
#: job id would be real, and the customer's reply would sit in Redis until it expired. The
#: colon lives in the JOB ID instead, where it is a namespace and not a dispatch key.
SUPPORT_CARD_JOB_NAME: Final[str] = "sync_support_card"
SUPPORT_RELAY_JOB_NAME: Final[str] = "relay_support_reply"

#: The verification job, enqueued by the panel the instant a support group is SELECTED.
#:
#: A third name on the same terms as the two above — a Python identifier here, the
#: ``support:verify_group`` of the spec's prose only ever in a job ID — and restated in
#: ``bayram.admin.queue`` rather than imported, because importing this module would put
#: ``aiogram.Bot`` in the import graph of the one process that is structurally denied a token
#: (``ADMIN_PANEL_PLAN D10 / §4.2``). The assert at the bottom of this module holds up this end.
SUPPORT_VERIFY_JOB_NAME: Final[str] = "verify_support_group"

#: The kit job's context keys, RE-STATED rather than imported from :mod:`bayram.runtime.jobs`.
#: Importing them would make this module depend on the one that registers it, which is a cycle;
#: :mod:`bayram.runtime.payme_jobs` and :mod:`bayram.runtime.broadcast_job` restate the same
#: strings for the same reason.
CONTAINER_CTX_KEY: Final[str] = "container"
BOT_CTX_KEY: Final[str] = "bot"
#: ARQ's own key for the pool it hands every job. Present in a real worker and ABSENT in a
#: hand-built context, which is why the only reader of it treats it as optional.
REDIS_CTX_KEY: Final[str] = "redis"

#: How many attempts a card sync gets, and the number this module reads to decide when a
#: retryable failure has become terminal. It must equal the ``max_tries`` the function is
#: REGISTERED with in :mod:`bayram.runtime.jobs`: ARQ compares ``job_try > max_tries`` at the
#: top of its own runner, so the attempt that would have been the fourth never enters the
#: function at all and a ``Retry`` raised on the last permitted attempt is discarded with
#: nobody told. ``payme_jobs._retry_or_give_up`` learned that the hard way and it is worth
#: exactly one constant per job here.
#:
#: THREE rather than the notification's five, and the difference is the cost of giving up. A
#: lost card sync is a card reading one status behind — repainted by the next panel action on
#: that ticket, of which there is usually one within minutes — while a lost relay is a customer
#: who was never answered. Three rather than one because the FIRST post of a card is repainted
#: by nothing: until the latch is claimed there is no card to edit, and the ticket sits on the
#: board with no staffer having seen it.
SUPPORT_CARD_MAX_TRIES: Final[int] = 3

#: How many attempts a relay gets. Five, matching ``PAYME_NOTIFY_MAX_TRIES``, because this job
#: has the same shape and the same stake: one message to one person who is waiting, where the
#: money — or here, the complaint — is already ours. Unlike the notification it has NO backstop
#: sweep behind it; see the module docstring for why the give-up state is visible instead.
SUPPORT_RELAY_MAX_TRIES: Final[int] = 5

#: How many attempts a group verification gets, and the number :func:`verify_support_group`
#: reads back to decide when a retryable failure has become terminal. It must equal the
#: ``max_tries`` the function is registered with in :mod:`bayram.runtime.jobs`, for the reason
#: :data:`SUPPORT_CARD_MAX_TRIES` states: ARQ compares ``job_try > max_tries`` before it
#: re-enters the function, so a ``Retry`` raised on the last permitted attempt is discarded
#: with nobody told.
#:
#: THREE, and the number matters less here than the fact that MOST failures never reach the
#: ladder at all. The four verdicts this job exists to produce — no such chat, the bot is not a
#: member, the bot cannot post, the group migrated — are all TERMINAL: a second attempt would
#: ask Telegram the same question and be told the same thing, and three attempts at "chat not
#: found" is two extra minutes before the operator learns they mistyped a digit. The ladder is
#: for Telegram being unreachable or rate-limiting, which is the one case where waiting helps.
SUPPORT_VERIFY_MAX_TRIES: Final[int] = 3

#: Seconds between attempts, multiplied by the attempt number the way ARQ counts them (from 1).
#: Sized for a Telegram hiccup rather than a vendor rate limit — a genuine ``retry_after`` is
#: obeyed to the second instead, by :func:`_retry_or_give_up`'s ``defer_s`` argument.
_BACKOFF_S: Final[float] = 5.0

#: The support group's own outbound budget, separate from ``bayram:send:budget``.
#:
#: A second key and not a second rate on the same key: the shared bucket meters the TOKEN and
#: the group's ceiling is per CHAT, so charging both from one counter would make a campaign's
#: fifty thousand messages eat the group's allowance and a backlog of cards eat the campaign's.
#: Two buckets is what lets each be sized for the limit it is actually about. They deliberately
#: share the PARK key (:data:`bayram.runtime.pacer.SEND_PARK_KEY`) — see :func:`group_pacer`.
GROUP_SEND_BUDGET_KEY: Final[str] = "bayram:send:group"

#: Messages a second this deployment will put into the support group, across every worker.
#:
#: **One, and this is three times looser than Telegram's documented group ceiling. Read this
#: before changing it.** Telegram limits a single chat to roughly 20 messages a MINUTE, which
#: is one every three seconds — a rate of ``0.33/s``. :class:`~bayram.runtime.pacer.PacerPolicy`
#: refuses anything below ``1``, and correctly: ``rate_per_s`` is a divisor on the degraded
#: path, so a fractional or zero value is a ``ZeroDivisionError`` the first time Redis blinks,
#: mid-send. One per second is therefore the tightest bucket this seam can express without
#: widening that policy, and what it buys is real: it is **thirty-six times** tighter than the
#: shared bucket's shipped twelve per second, which is the failure this whole arrangement is
#: about, and it bounds the group across every replica rather than per process.
#:
#: What it does not buy is compliance with the 20/minute figure during a sustained backlog. The
#: second half of the protection is the shared park: when Telegram does say ``retry_after``,
#: every sender in every process — campaigns, relays, cards — stops (:func:`group_pacer`). If
#: the group is observed earning flood waits anyway, the fix is a settings-backed
#: ``support_group_send_rate`` plus a policy that admits a fractional rate, in that order; do
#: NOT simply raise this number, and do not point the group at the shared bucket to "simplify".
GROUP_SEND_RATE_PER_S: Final[int] = 1

#: The whole policy the group is paced under, as one value rather than three arguments spelled
#: at the one call site that builds a pacer.
#:
#: **Its ``park_key`` is the SHARED one and its ``budget_key`` is not, which is the entire
#: design and is the reason this is a named constant.** ``retry_after`` is a statement about the
#: BOT TOKEN, never about the chat that provoked it — ``bayram.runtime.pacer``'s module
#: docstring says so, and ``bayram.bot.delivery`` records that under a 429 the second call is
#: the one most likely to make the wait longer. A group pacer with a park key of its own would
#: keep posting cards straight through a flood wait a campaign had just earned, deepening the
#: wait on the token the ORDERS depend on. Splitting the budget and sharing the park is what
#: makes the two limits independent where they are independent and joint where they are joint;
#: a reviewer "tidying" this into one fully-private or one fully-shared policy breaks one half
#: or the other, which is why the pair is written down here and asserted in the tests.
GROUP_PACER_POLICY: Final[PacerPolicy] = PacerPolicy(
    rate_per_s=GROUP_SEND_RATE_PER_S,
    budget_key=GROUP_SEND_BUDGET_KEY,
    park_key=SEND_PARK_KEY,
)

# THE RELAY IS RENDERED BY ``bayram.bot.handlers.support.relay_text_for``, AND THIS MODULE
# DELIBERATELY OWNS NO TEMPLATE KEY AND NO LENGTH OF ITS OWN.
#
# It used to own both — a ``RELAY_MESSAGE_KEY`` naming ``support.ticket.reply`` and a
# ``MAX_RELAY_BODY_CHARS`` of 3000 — and the pair were the defect, not the fix. The number
# bounded the RAW body, before the header, the ``<blockquote>``, the closing line and the HTML
# escaping that turns one ``&`` into five characters; the finished message could therefore
# still run past Telegram's 4096 and be refused with a 400, which burned the whole retry
# ladder and answered nobody. ``relay_text_for`` measures the FINISHED string instead and
# binary-searches the longest raw prefix that fits, which is correct whatever the template and
# the locale do — and it is the same function the staff-group door already relays through, so
# the two doors cannot drift into disagreeing about what fits. Re-introducing a constant here
# re-introduces the second implementation; if the bound ever needs changing it changes there.


# ---------------------------------------------------------------------------
# The context, and the things built from it
# ---------------------------------------------------------------------------
def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _require_bot(ctx: Mapping[str, Any]) -> Bot:
    bot = ctx.get(BOT_CTX_KEY)
    if not isinstance(bot, Bot):
        raise PipelineError(
            "worker context is missing a usable 'bot'",
            context={"key": BOT_CTX_KEY, "found": type(bot).__name__},
        )
    return bot


def build_worker_support_store(container: AppContainer) -> SupportTicketStore:
    """The ticket store, built here rather than taken off the container.

    ``AppContainer`` has no support field and should not grow one: it carries the ports the BOT
    holds, and ``bayram.main`` wires ``SqlSupportTickets`` into ``BotDeps`` because the bot is
    what opens tickets. Neither job here opens one. Constructing a second handle costs nothing
    at all — it is two field assignments over the session factory the container already owns,
    no I/O — which is exactly :func:`bayram.runtime.payme_jobs.build_worker_payme_ledger`'s
    argument for doing the same with the rail.

    **No quota is threaded in**, although ``SqlSupportTickets`` accepts one. The quota bounds
    how many tickets an ACCOUNT may open, it is read only by ``check_open_quota``, and neither
    of these jobs opens a ticket — so passing ``resolve_support_quota(container.settings)``
    here would be a number that is never read, quietly implying to the next reader that the
    worker meters something. The shipped default stands in for a value nothing consults.

    Returning the PROTOCOL rather than the concrete class is what makes ``mypy --strict`` check
    the structural conformance here, at the one place in the worker that depends on it, rather
    than at some later attribute access.
    """
    return SqlSupportTickets(container.require_session_factory())


def group_pacer(ctx: Mapping[str, Any]) -> SendPacer:
    """The pacer for sends into the SUPPORT GROUP. Its own budget, the shared park.

    **Its own budget** because Telegram's per-chat ceiling and its per-token ceiling are
    different limits about different things, and a single counter cannot express both: see
    :data:`GROUP_SEND_BUDGET_KEY` and :data:`GROUP_SEND_RATE_PER_S`, which carries the honest
    account of what this rate does and does not achieve.

    **The shared park**, and that half is not a detail. ``retry_after`` is a statement about the
    BOT TOKEN, not about the chat that happened to provoke it — ``bayram.runtime.pacer``'s
    module docstring says so, and ``bayram.bot.delivery`` records that under a 429 the second
    call is the one most likely to make the wait longer. A group pacer with a park key of its
    own would keep posting cards straight through a flood wait a campaign had just earned,
    deepening the wait on the token the ORDERS depend on. Pointing it at
    :data:`~bayram.runtime.pacer.SEND_PARK_KEY` means every sender in every process stops
    together and resumes together, which is the only behaviour that is correct for a limit
    measured on a credential.

    The fallback when this worker has no Redis is :func:`bayram.runtime.broadcast_job._pacer`'s,
    with its reasoning: ``use_fake_providers`` mode and the whole unit suite run with no Redis,
    and a pacer that could only exist against a server would be switched off exactly where a
    developer would notice it misbehaving. A multi-replica deployment always has
    ``ctx["redis"]``, because ARQ puts it there.
    """
    redis = ctx.get(REDIS_CTX_KEY)
    store: SendBudgetStore
    if isinstance(redis, Redis):
        store = RedisSendBudgetStore(redis)
    else:
        # Typed rather than merely null-checked, for ``_require_container``'s reason: a context
        # holding something that is not a client would otherwise degrade one ``AttributeError``
        # per message through the pacer's own broad ``except``, which is the shape of a store
        # that is down and not the shape of one that was never wired.
        _LOG.warning(
            "no redis client in the worker context; group sends are paced per process only",
            extra={"rate_per_s": GROUP_SEND_RATE_PER_S, "found": type(redis).__name__},
        )
        store = InMemorySendBudgetStore()
    return SendPacer(store, policy=GROUP_PACER_POLICY)


def _attempt(ctx: Mapping[str, Any]) -> int:
    """Which attempt this is, counting from 1 the way ARQ does."""
    attempt = ctx.get("job_try", 1)
    return attempt if isinstance(attempt, int) and attempt > 0 else 1


def _retry_or_give_up(
    ctx: Mapping[str, Any],
    *,
    max_tries: int,
    job: str,
    subject: str,
    reason: str,
    defer_s: float | None = None,
) -> None:
    """Ask ARQ for another attempt, unless this was the last one it will honour.

    Raising ``Retry`` on the final permitted attempt is the defect
    ``bayram.runtime.jobs._is_final_attempt`` and ``payme_jobs._retry_or_give_up`` both exist to
    prevent: ARQ discards that retry BEFORE re-entering the function, so nothing runs, nothing
    is logged from inside the job, and nobody is told. On the last attempt this logs at ERROR
    and returns, which leaves the row in the state that MAKES the failure visible — an unposted
    card is ``is_posted_to_group=False`` on the board, an unrelayed reply is a ``REPLY`` row
    with no ``relayed_at`` on the timeline. Neither is lost; both are waiting for somebody.

    ``defer_s`` overrides the ladder for the one case where Telegram has told us exactly how
    long to wait. Obeying a ``retry_after`` with a five-second ladder is how a flood wait gets
    extended instead of served.
    """
    attempt = _attempt(ctx)
    if attempt < max_tries:
        raise Retry(defer=defer_s if defer_s is not None else _BACKOFF_S * attempt)
    _LOG.error(
        "a support job gave up; the row is what makes the failure visible",
        extra={
            "job": job,
            "subject": subject,
            "reason": reason,
            "attempt": attempt,
            "max_tries": max_tries,
        },
    )


def _job_uuid(value: str, *, field: str, job: str) -> UUID:
    """Parse an id the panel queued. A non-UUID means the enqueue side is broken, so it raises.

    ``bayram.runtime.broadcast_job._campaign_id``'s posture exactly: this is not a runtime
    condition a retry could recover from, and swallowing it would turn a bug in the seam into a
    job that silently does nothing for the life of the deployment.
    """
    try:
        return UUID(value)
    except ValueError as exc:
        raise PipelineError(
            "a support job was queued with an id that is not a UUID",
            context={"job": job, "field": field, "value": value},
            cause=exc,
        ) from exc


# ---------------------------------------------------------------------------
# support:card_sync — repaint the group card from the row as it now stands
# ---------------------------------------------------------------------------
async def sync_support_card(ctx: Mapping[str, Any], ticket_id: str) -> None:
    """Make the group card say what the ticket row says. Enqueued by the PANEL.

    Takes the ticket id and NOTHING ELSE — no status, no assignee, no rendered text. See the
    module docstring: a job carrying the state it was enqueued with repaints the card with a
    stale badge the moment it runs late, and every job here runs late eventually because every
    job here is replayed on deploy. The row is the truth; this is a nudge to go and look at it.

    **Two arms, and which one runs is decided by the latch and not by the caller.**

    * The ticket has never been posted (``group_message_id IS NULL``). The card is POSTED, and
      through :func:`bayram.bot.handlers.support.post_card` rather than through a second copy
      of the send/claim/settle dance written here. That sequence is the one thing in this
      feature that must not exist twice: the claim is a conditional ``UPDATE`` whose rowcount
      is the lock, it cannot precede the send (Telegram issues the ``message_id`` in the
      RESPONSE), and the loser of the race deletes its own card. A second implementation that
      drifted by one line would put two live cards in the group and leave the relay listening
      on the wrong one. This arm is therefore also the retry for a group post the bot lost to a
      Telegram refusal at description time — the panel's "sync" button is the ticket's second
      chance at ever reaching staff, which is the more valuable of the two arms and the reason
      :data:`SUPPORT_CARD_MAX_TRIES` is not 1.
    * The ticket carries a card. It is EDITED IN PLACE, at :attr:`~bayram.support.
      TicketSnapshot.group_chat_id` — the chat the card was actually posted to, never whichever
      chat is SELECTED right now. That distinction got sharper rather than softer when the group
      stopped being an environment variable: repointing the support inbox used to take a
      redeploy and now takes one press in the panel, so the window in which "where cards go" and
      "where this card went" disagree is a window that opens several times a week. Editing a
      message id against the new chat names either somebody else's message or nothing at all,
      and the card staff are actually reading would silently stop being updated.

    **A card that is already correct is a success, not a failure.** Telegram refuses an edit
    that would change nothing, and the whole design of :func:`~bayram.bot.support_card.
    render_card` is that it is a total function of the snapshot — so a duplicate job, a replay
    and a second operator pressing the same button all converge on that refusal. It is
    swallowed at INFO, the way ``handlers.support._rerender_card`` swallows it.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    identifier = _job_uuid(ticket_id, field="ticket_id", job=SUPPORT_CARD_JOB_NAME)
    store = build_worker_support_store(container)

    found = await store.load_ticket(identifier)
    if is_err(found):
        _LOG.warning(
            "a support ticket could not be read for a card sync",
            extra=found.error.to_log_dict(),
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_CARD_MAX_TRIES,
            job=SUPPORT_CARD_JOB_NAME,
            subject=ticket_id,
            reason="ticket_unreadable",
        )
        return
    ticket = found.value
    if ticket is None:
        # Not retryable and not worth a page: an id that names nothing is a stale enqueue, and
        # two more attempts will find the same nothing.
        _LOG.error("no support ticket answers this id", extra={"ticket_id": ticket_id})
        return

    pacer = group_pacer(ctx)
    if not ticket.is_posted:
        await _post_first_card(ctx, bot, store, container, ticket, pacer=pacer)
        return
    await _edit_card(ctx, bot, container.settings, ticket, pacer=pacer)


async def _post_first_card(
    ctx: Mapping[str, Any],
    bot: Bot,
    store: SupportTicketStore,
    container: AppContainer,
    ticket: TicketSnapshot,
    *,
    pacer: SendPacer,
) -> None:
    """The ticket has no card yet. Give it one, through the bot's own posting sequence.

    The pacer is acquired HERE rather than inside ``post_card``, because that function is
    shared with the bot process — which holds no Redis pool of its own and no pacer — and
    widening its signature to take one would put a worker concern in a customer-facing handler.
    Acquiring first and delegating second paces the send exactly as if the pacing were inside
    it, at the cost of one wasted unit of budget on the paths ``post_card`` returns early from.
    Those are cheap and rare: the ``is_posted`` case is filtered out by the caller, and the "no
    group selected" case is answered BEFORE the acquire, below, rather than inside ``post_card``
    — which is a change from when the group was a setting, because the answer is now a database
    read and paying a budget unit for a room nobody picked would be paying it on every ticket a
    deployment files before an operator gets round to choosing one.

    **The whole container is taken rather than ``Settings``, and that is the shape of the
    change.** The support group is a ``bot_chats`` row now, so this arm needs the directory port
    as well as the panel URL, and :func:`~bayram.bot.handlers.support.support_group_target` is
    the same resolution the BOT's door makes — one function, so the two doors cannot come to
    disagree about what "no group" means.

    **A flood wait raised by this send is invisible to this arm, and that is a real limitation
    stated rather than hidden.** ``post_card`` swallows ``TelegramAPIError`` by design — a
    refused card must never lose the ticket — so a ``TelegramRetryAfter`` from inside it is
    logged there and never reaches :meth:`~bayram.runtime.pacer.SendPacer.park_after_flood`.
    What still holds is the half that matters most: :meth:`~bayram.runtime.pacer.SendPacer.
    acquire` WAITS OUT a park published by anybody else, so a flood wait a campaign or an edit
    learned about still stops this arm. What is lost is this arm's ability to TEACH the others
    about one. The fix, if the group ever provokes them at this rate, is for ``post_card`` to
    return a typed outcome rather than ``None``; that is a change in the bot's lane.
    """
    target = await support_group_target(container.bot_chats)
    if target is None:
        # No group is SELECTED — or none could be read, or this deployment records no chat
        # directory at all. The ticket is still written, the customer is still answered and the
        # board is still populated, so this is an ordinary state and never a retry. It is also
        # a state an operator can leave without a redeploy, which is the whole reason the group
        # stopped being an environment variable (``SUPPORT_TICKETS_SPEC §3.8``): the panel's
        # own "sync" button re-runs this job the moment they pick a room.
        _LOG.info(
            "no support group is selected; the card sync has nothing to post",
            extra={"ticket_id": str(ticket.id), "public_ref": ticket.public_ref},
        )
        return
    await pacer.acquire()
    await post_card(bot, store, container.settings, ticket, target=target, now=utc_now())
    reread = await store.load_ticket(ticket.id)
    if is_err(reread) or reread.value is None:
        # The post may well have landed; only the confirmation read failed. Retrying would send
        # nothing a second time — ``post_card`` returns early on a ticket that now carries a
        # card — so this is logged rather than raised.
        _LOG.warning(
            "a support card was posted but the row could not be re-read",
            extra={"ticket_id": str(ticket.id)},
        )
        return
    if not reread.value.is_posted:
        _LOG.warning(
            "a support card sync did not reach the group; the ticket is unaffected",
            extra={"ticket_id": str(ticket.id), "public_ref": ticket.public_ref},
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_CARD_MAX_TRIES,
            job=SUPPORT_CARD_JOB_NAME,
            subject=str(ticket.id),
            reason="group_post_refused",
        )
        return
    _LOG.info(
        "a support card reached the group",
        extra={
            "ticket_id": str(ticket.id),
            "public_ref": ticket.public_ref,
            "group_message_id": reread.value.group_message_id,
        },
    )


async def _edit_card(
    ctx: Mapping[str, Any],
    bot: Bot,
    settings: Settings,
    ticket: TicketSnapshot,
    *,
    pacer: SendPacer,
) -> None:
    """Redraw an existing card in place. The common arm, and the one that must not accumulate.

    Edited rather than re-posted: the card is a row in a working queue, and appending a new one
    per state change would turn a scannable list of open tickets into a scroll of history the
    panel already keeps — ``handlers.support._rerender_card``'s argument, made here for the
    panel-driven half of the same card.

    An edit charges the group's rate limit exactly as a send does, which is why it acquires the
    same budget.
    """
    chat_id = ticket.group_chat_id
    message_id = ticket.group_message_id
    if chat_id is None or message_id is None:  # pragma: no cover - ``is_posted`` guards this
        return
    order_ref = order_reference(ticket.order_id) if ticket.order_id is not None else None
    await pacer.acquire()
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=render_card(ticket, order_ref=order_ref),
            reply_markup=card_keyboard(ticket, panel_base_url=settings.support_panel_base_url),
        )
    except TelegramRetryAfter as exc:
        parked_s = await pacer.park_after_flood(exc)
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_CARD_MAX_TRIES,
            job=SUPPORT_CARD_JOB_NAME,
            subject=str(ticket.id),
            reason="flood_wait",
            defer_s=parked_s,
        )
        return
    except TelegramAPIError as exc:
        # INFO and not ERROR, and not a retry either: "message is not modified" is BY FAR the
        # most common answer here — two operators pressing the same button, a replayed job, a
        # status moved back to where the card already said it was — and it means the card is
        # already correct. Retrying it would spend the ladder proving that three times. A
        # genuinely broken edit (the message was deleted, the bot was removed from the group)
        # produces the same swallow, and the ticket is still on the board.
        _LOG.info(
            "the support card was not redrawn",
            extra={
                "ticket_id": str(ticket.id),
                "group_chat_id": chat_id,
                "group_message_id": message_id,
                "failure": repr(exc),
            },
        )
        return
    _LOG.info(
        "a support card was redrawn",
        extra={
            "ticket_id": str(ticket.id),
            "public_ref": ticket.public_ref,
            "status": ticket.status.value,
        },
    )


# ---------------------------------------------------------------------------
# support:relay — put an operator's reply in the customer's chat
# ---------------------------------------------------------------------------
async def relay_support_reply(ctx: Mapping[str, Any], ticket_id: str, event_id: str) -> None:
    """Deliver one operator reply to the customer's private chat. Enqueued by the PANEL.

    Both ids travel and both are used. ``event_id`` is the AUTHORITY — it names the
    ``support_ticket_events`` row holding the exact words to send and the row stamped
    ``relayed_at`` when they land, and the panel's deterministic job id is built from it so a
    double-clicked Send cannot put the same paragraph in somebody's phone twice. ``ticket_id``
    is what the row is read THROUGH, and it carries the two things the event cannot: who to
    send to, and in which language.

    **The customer is answered in the language the TICKET was opened in**, never in whatever
    the account is set to today. An account that switched language in between would otherwise
    receive the one message where being understood is the entire point in a language it no
    longer reads. ``support_tickets.language`` exists for this sentence.

    **A MISSING EVENT ROW IS "NOT YET", NOT "NEVER" — and reading it as "never" destroyed
    replies.** The panel writes the ``reply`` row and enqueues this job; until that request's
    transaction commits, no other session can see the row. ARQ polls every ``poll_delay``, so
    this job really does sometimes open its session inside that window, and for a while the
    code here answered "no timeline row answers this event id" by logging and RETURNING — the
    job completed successfully, the reply was never sent, and the timeline showed it composed
    with ``relayed_at`` null, which an operator reads as "Telegram refused" and therefore does
    not resend. So an absent row now goes through :func:`_retry_or_give_up` like every other
    recoverable failure, and only the FINAL attempt calls it gone. The panel closed the same
    hole from its end by committing before it enqueues (``bayram.admin.routers.support.
    _committed``); this half is still needed, because a replay after a deploy, a lagging
    replica or a slow commit can put the read ahead of the write again and a retry ladder is
    the only thing that survives that.

    **The missing TICKET is not treated the same way, and the asymmetry is deliberate.** The
    ticket row was written by the bot, in another process, long before the operator opened the
    screen — this request only appends to it — so an absent ticket is never "not yet". It is a
    stale enqueue against a row ``/forget`` has deleted, and five attempts would find the same
    nothing.

    **Four silences, each of them correct.**

    * No such ticket. See above: dropped, not retried.
    * The event is not a ``REPLY``. **This is the guard that matters most in this module.**
      ``support_ticket_events`` holds ``NOTE`` rows, which are an operator's INTERNAL words
      about a customer, and they carry a body in exactly the same column. Relaying one would
      send a customer the private assessment somebody wrote about them, which is the single
      worst outcome this feature can produce — so the kind is checked here, at the last
      possible moment before the send, rather than trusted from the enqueue side.
    * ``relayed_at`` is already set. A redelivered job, or a replay after a deploy. Saying it
      twice is the one failure a customer notices.
    * The body is empty. There is nothing to say, and a message consisting of a header and an
      empty quote is worse than no message at all.

    **Send first, stamp second, and the order is deliberate.** Stamping first would make a
    failed send permanent — ``relayed_at`` set on a paragraph nobody received, and the timeline
    reading "we answered them" forever. Sending first risks a duplicate if the stamp then
    fails, and a duplicate reply is a nuisance where a missing one is a customer who thinks
    they were ignored.

    **AND THEN THE TICKET IS RE-POINTED AT THE MESSAGE THE CUSTOMER IS NOW LOOKING AT, WHICH
    THIS DOOR SHIPPED WITHOUT AND WHICH IS THE WHOLE REASON ``_send`` RETURNS AN ID.** The
    relay ends by inviting a reply — ``support.ticket.reply``'s own closing sentence — and
    ``support_tickets.prompt_message_id`` is *the message this ticket is currently listening
    on*, not "the ForceReply we sent once". Until :meth:`~bayram.support.SupportTicketStore.
    listen_on` moves it, the ticket goes on listening to a prompt from weeks ago, the
    customer's answer matches no ticket, falls straight past the support router and is claimed
    by whichever wizard step they were parked in — at ``Wizard.name`` their sentence becomes
    the RECIPIENT'S NAME and the pipeline SINGS IT. That defect was found and fixed on the
    staff-group door (``bayram.bot.handlers.support._relay_to_customer``) and left standing
    here, where the operator's own reply comes out of the panel: same failure, different door.
    An operator's Send must therefore do exactly the three things a staffer's reply does —
    render through :func:`~bayram.bot.handlers.support.relay_text_for`, stamp, re-point — and
    the three are asserted of this function rather than of the door it copies.

    **The stamp goes first and the re-point second, and the two failures are independent.** The
    stamp is the replay guard: every job here is replayed on deploy, and a deploy landing
    between the send and these two writes would relay the same paragraph a second time, which
    is the one failure a customer notices immediately. The re-point's own window is bounded by
    a person reading a message and typing an answer, so it is the one that can afford to be
    second. Neither failure is retried — the customer HAS been told, and every retry path in
    this function ends in another send — and neither is allowed to skip the other: see the
    ``mark_relayed`` block, which no longer returns.

    **Nothing here moves the ticket or repaints the card.** The panel made the move in its own
    audited transaction before it enqueued this, and it enqueues its own card sync. A job that
    also moved the status would be a second writer of a state machine, racing the first.
    ``listen_on`` is not an exception to that rule and is worth saying so: it writes no status,
    no event and no clock a board reads — it is a routing pointer, and the customer's own next
    message is what moves the ticket, through the bot's follow-up branch and
    :func:`bayram.support.reopen_target`.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    ticket_uuid = _job_uuid(ticket_id, field="ticket_id", job=SUPPORT_RELAY_JOB_NAME)
    event_uuid = _job_uuid(event_id, field="event_id", job=SUPPORT_RELAY_JOB_NAME)

    read = await _read_detail(container, ticket_uuid)
    if is_err(read):
        _LOG.warning(
            "a support ticket could not be read for a relay", extra=read.error.to_log_dict()
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_RELAY_MAX_TRIES,
            job=SUPPORT_RELAY_JOB_NAME,
            subject=event_id,
            reason="ticket_unreadable",
        )
        return
    detail = read.value
    if detail is None:
        _LOG.error(
            "no support ticket answers this id; the reply cannot be relayed",
            extra={"ticket_id": ticket_id, "event_id": event_id},
        )
        return
    row = _timeline_row(detail, event_uuid)
    if row is None:
        # NOT terminal. The panel writes this row and enqueues this job, and a job that
        # overtakes that commit sees a timeline without it. Retrying is what turns a lost
        # race into a half-second delay; returning here is what turned it into a customer
        # who was never answered. WARNING on every attempt, so the window is measurable in
        # the logs rather than inferred.
        _LOG.warning(
            "no timeline row answers this event id yet; the reply may not be committed",
            extra={
                "ticket_id": ticket_id,
                "event_id": event_id,
                "attempt": _attempt(ctx),
                "max_tries": SUPPORT_RELAY_MAX_TRIES,
            },
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_RELAY_MAX_TRIES,
            job=SUPPORT_RELAY_JOB_NAME,
            subject=event_id,
            reason="event_not_visible_yet",
        )
        # Only the final attempt falls through. A row still absent after the whole ladder is
        # genuinely gone — an erased customer, a purged ticket — and is logged as that rather
        # than as the race above, so the two are never confused when somebody reads the log
        # after the fact. There is nothing left to deliver and nothing to make visible: the
        # timeline this would have been rendered on no longer exists.
        _LOG.error(
            "no timeline row answers this event id on the last attempt; the row is gone",
            extra={"ticket_id": ticket_id, "event_id": event_id},
        )
        return
    if not _is_sendable(row, ticket_id=ticket_id, event_id=event_id):
        return

    text = relay_text_for(detail.ticket, row.body or "")
    relayed_message_id = await _send(ctx, bot, detail, text=text, event_id=event_id)
    if relayed_message_id is None:
        return

    store = build_worker_support_store(container)
    # One instant for both writes below. They are two statements about the same event — it was
    # delivered, and this is now the message the ticket listens on — and a second ``utc_now()``
    # would date them a few milliseconds apart for no reason anybody could reconstruct.
    now = utc_now()
    stamped = await store.mark_relayed(event_uuid, now=now)
    if is_err(stamped):
        # The customer HAS been told. Retrying would tell them again, so this failure is
        # recorded and dropped: the worst outcome is one duplicate if an operator presses Send
        # a second time on a row that still reads "composed", and the alternative — raising —
        # guarantees a duplicate right now.
        #
        # It does NOT return, and that is the one line of this block worth reading twice. The
        # re-point below protects against a different failure entirely — a follow-up that
        # resolves to no ticket and is sung as a recipient's name — and there is no reason a
        # missed bookkeeping stamp should also cost the customer their way back to us. Two
        # independent guarded statements, two independent failures, neither retried.
        _LOG.error("a relayed reply was sent but not stamped", extra=stamped.error.to_log_dict())
    await _listen_on_the_relay(store, detail, relayed_message_id, event_id=event_id, now=now)
    _LOG.info(
        "an operator's reply reached the customer",
        extra={
            "ticket_id": ticket_id,
            "event_id": event_id,
            "public_ref": detail.ticket.public_ref,
            "language": detail.ticket.language.value,
            "is_first_stamp": is_ok(stamped) and stamped.value,
            "listening_on": relayed_message_id,
        },
    )


async def _read_detail(
    container: AppContainer, ticket_id: UUID
) -> Result[SupportTicketDetail | None]:
    """The ticket and its whole timeline, in one transaction, as data rather than an exception.

    :func:`bayram.db.admin.support_tickets.get_ticket` is the PANEL's read, reused here rather
    than a narrower one written for this job, and the reuse is deliberate on two counts. It
    already returns exactly the four things this job needs and cannot get anywhere else —
    the ticket's language, its ``public_ref``, the event's ``body`` and the event's
    ``relayed_at`` — and it is the read the operator was looking at when they pressed Send, so
    the worker and the panel cannot come to disagree about what the reply says. ``bayram.db.
    admin`` is a read layer, not a web one; :mod:`bayram.runtime.broadcast_job` already reaches
    into it for ``db.admin.audit`` and ``db.admin.segment``, and the forbidden direction is the
    other one (the panel may not import ``bayram.runtime``, which would drag a ``Bot`` into a
    process denied a token).

    The cost is that a relay reads the whole timeline to find one row. That is tens of rows at
    the very worst — :class:`~bayram.db.admin.views.SupportTicketDetail` argues why the
    timeline is unpaged at all — against one message this job is about to spend a network round
    trip on. If it ever stops being cheap, the right fix is a ``load_event`` on
    :class:`~bayram.support.SupportTicketStore`, not a hand-written ``SELECT`` in this module:
    no job module in this package writes SQL, and this one should not be the first.
    """

    async def read() -> SupportTicketDetail | None:
        async with container.require_session_factory()() as session:
            return await get_ticket(session, ticket_id)

    return await run_guarded("support_relay_read_ticket", read, ticket_id=str(ticket_id))


def _timeline_row(detail: SupportTicketDetail, event_id: UUID) -> SupportTicketEventItem | None:
    """The row the panel named, or ``None`` when the timeline does not carry it **yet**.

    Split out of the old ``_sendable_reply`` on purpose, and the split is the point rather than
    tidiness. That function answered four different questions with one ``None``, and the caller
    could not tell "this must never be sent" (a ``NOTE``, an empty body) from "this cannot be
    sent YET" (the panel's transaction has not committed) — so all four took the terminal path
    and a reply lost to the commit race was discarded as though relaying it had been refused.
    Absence is a TIMING answer and belongs to the caller, which is the only place that holds
    ``ctx`` and can ask ARQ for another attempt. Everything below is a DECISION about a row
    that really is there, and none of those changes on a retry.
    """
    return next((row for row in detail.events if row.id == event_id), None)


def _is_sendable(event: SupportTicketEventItem, *, ticket_id: str, event_id: str) -> bool:
    """Whether a row that IS on the timeline may be put in the customer's chat.

    Three refusals, none of them retryable: a second attempt would read the same row and reach
    the same answer, so each returns ``False`` and the job stops. A boolean rather than the row
    itself because the caller already holds it — :func:`_timeline_row` found it — and a
    function that both finds and judges is what let a lost race look like a refusal.
    """
    if event.kind is not SupportTicketEventKind.REPLY:
        # See the job's docstring. A ``NOTE`` is an operator's internal words and carries a
        # body in the same column; relaying one would be the worst outcome available here.
        _LOG.error(
            "refusing to relay a timeline row that is not a reply",
            extra={"ticket_id": ticket_id, "event_id": event_id, "kind": event.kind.value},
        )
        return False
    if event.relayed_at is not None:
        _LOG.info(
            "this reply had already reached the customer; sending nothing",
            extra={"ticket_id": ticket_id, "event_id": event_id},
        )
        return False
    if not (event.body or "").strip():
        _LOG.error(
            "a reply with no words cannot be relayed",
            extra={"ticket_id": ticket_id, "event_id": event_id},
        )
        return False
    return True


async def _listen_on_the_relay(
    store: SupportTicketStore,
    detail: SupportTicketDetail,
    message_id: int,
    *,
    event_id: str,
    now: datetime,
) -> None:
    """Point the ticket at the message the customer is now looking at. Logged, never retried.

    The mirror of ``bayram.bot.handlers.support._listen_on_the_relay``, and a second small
    function rather than an import of that private one: the two differ in the type they are
    handed (a ``SupportTicketDetail`` read through the panel's query here, a
    :class:`~bayram.support.TicketSnapshot` there) and in who is told when it fails — the
    staffer gets nothing because they are standing in the group, while here there is nobody to
    tell at all. What must NOT be duplicated is the statement itself, and it is not:
    :meth:`~bayram.support.SupportTicketStore.listen_on` is one unconditional ``UPDATE`` in
    ``bayram.db.support_tickets`` and both doors call it.

    **Unconditional on purpose.** ``attach_prompt`` refuses to move a ``prompt_message_id``
    that is already set, so that a replayed open cannot orphan a ForceReply the customer can
    still see; this is the opposite case — a NEWER message has taken over the conversation, and
    the only message that can resolve is the one on their screen. Using ``attach_prompt`` here
    would be a no-op on every ticket that has ever been prompted, which is all of them.

    **A failure is logged and dropped.** The reply has already reached the customer, so there
    is nothing to retry that would not send it twice; what is lost is the routing for their
    NEXT message, and the log line says so in those words rather than as a bare error, because
    the consequence is a customer sentence landing in a wizard and not a missing row.
    """
    listening = await store.listen_on(detail.ticket.id, prompt_message_id=message_id, now=now)
    if is_err(listening):
        _LOG.error(
            "the ticket could not be pointed at its relay; a follow-up will not resolve",
            extra={
                **listening.error.to_log_dict(),
                "event_id": event_id,
                "public_ref": detail.ticket.public_ref,
                "message_id": message_id,
            },
        )
        return
    if not listening.value:
        # ``False`` is "no such ticket", which here means the row went away between the read
        # at the top of this job and now — ``/forget`` is the only thing that deletes one.
        _LOG.warning(
            "the ticket was gone before it could be pointed at its relay",
            extra={"event_id": event_id, "public_ref": detail.ticket.public_ref},
        )


async def _send(
    ctx: Mapping[str, Any],
    bot: Bot,
    detail: SupportTicketDetail,
    *,
    text: str,
    event_id: str,
) -> int | None:
    """Put the reply in the customer's chat. The relay's own ``message_id``, or ``None``.

    **It returns the id rather than a ``bool``, and that is not a style change.** The caller
    has to do two things with a delivered relay and a boolean can only answer the first: stamp
    ``relayed_at``, and re-point ``support_tickets.prompt_message_id`` at THIS message so the
    "reply here if there is more to say" the relay ends with resolves back to this ticket
    instead of into a half-finished wizard. For as long as this function discarded Telegram's
    response — ``await bot.send_message(...)`` with nothing on the left of it — the second was
    not merely unwritten, it was unwritable, and the panel door relayed answers that a customer
    could not reply to. ``bayram.bot.handlers.support._RelayOutcome`` carries the same id on
    the other door, for the same sentence.

    ``None`` is every refusal, and it is deliberately not distinguished further here: the
    caller does nothing with a failure except stop, because a relay the customer never saw must
    neither be stamped as delivered nor be listened on. Which refusal it was, and whether
    another attempt was asked for, is decided and logged inside each ``except`` below.

    **A ``Forbidden`` is NOT stamped as delivered, and that is the deliberate divergence from
    :func:`bayram.runtime.payme_jobs._send`.** There, an unreachable chat is stamped, because
    leaving ``notified_at`` NULL would put a permanently undeliverable row into the sweep's
    backlog query and re-enqueue that job every five minutes for the life of the deployment.
    Nothing sweeps unrelayed replies — see the module docstring — so there is no backlog to
    close, and leaving the clock NULL is simply TRUE: the customer never received it. The
    panel renders that row as composed-and-not-delivered, which is precisely the state an
    operator needs to see before they write a second paragraph into the void.

    It is not retried either. A block does not clear in twenty seconds, and five attempts
    against a customer who has blocked the bot is five log lines and no message.

    ``is_blocked_by_customer`` tells a block apart from a deleted account in the log line,
    rather than leaving somebody to read an exception's ``str`` — :mod:`bayram.bot.delivery`
    owns that classification and both the delivery path and the payment notification use it.
    """
    chat_id = detail.ticket.telegram_user_id
    try:
        sent = await bot.send_message(chat_id=chat_id, text=text)
    except TelegramForbiddenError as exc:
        _LOG.warning(
            "an operator's reply could not be delivered; the chat is unreachable",
            extra={
                "event_id": event_id,
                "public_ref": detail.ticket.public_ref,
                "is_blocked_by_customer": is_blocked_by_customer(exc),
                "failure": repr(exc),
            },
        )
        return None
    except TelegramRetryAfter as exc:
        # Obeyed to the second rather than through the ladder. This send does NOT charge the
        # group's budget — it goes to a private chat and belongs to the token's shared one —
        # but a ``retry_after`` still binds the token, so deferring by what Telegram named is
        # the difference between serving the wait and extending it.
        _LOG.warning(
            "telegram asked us to back off before an operator's reply could be delivered",
            extra={"event_id": event_id, "retry_after": exc.retry_after},
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_RELAY_MAX_TRIES,
            job=SUPPORT_RELAY_JOB_NAME,
            subject=event_id,
            reason="flood_wait",
            defer_s=float(exc.retry_after) + 1.0,
        )
        return None
    except TelegramAPIError as exc:
        _LOG.warning(
            "an operator's reply did not send",
            extra={"event_id": event_id, "chat_id": chat_id, "failure": repr(exc)},
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_RELAY_MAX_TRIES,
            job=SUPPORT_RELAY_JOB_NAME,
            subject=event_id,
            reason="telegram_error",
        )
        return None
    return sent.message_id


# ---------------------------------------------------------------------------
# support:verify_group — prove the bot can actually post where the operator pointed it
# ---------------------------------------------------------------------------
#: What the bot posts into a chat it has just been pointed at. English, staff copy, never a
#: catalogue key — ``bayram.bot.support_card`` argues that in full: ``translate`` falls back
#: across four locales and the catalogues are held in exact key parity, so one staff-facing
#: string in a customer catalogue obliges four translations of an internal message for ever.
#:
#: **The send IS the verification, which is why there is a message here at all rather than a
#: silent capability probe.** ``getChat`` answers "does this chat exist", and Telegram has no
#: call that answers "may this bot write here" — ``getChatMember`` returns a status, and a
#: status is evidence rather than permission (an administrator can lose ``can_post_messages``
#: with no transition sent, and a ``manual`` row has never had a transition at all). The only
#: honest proof is a message that actually landed, so the proof is a message and the message may
#: as well tell the room what happened.
#:
#: Worded about the CHECK rather than about the state, deliberately. This job is handed a chat
#: id and verifies that chat; it does not require it to still be the selected one, because an
#: operator who selects, changes their mind and re-selects within a few seconds should not get a
#: verification that lies about which room is live. "Cards will arrive here while this chat is
#: the selected support group" is true in every one of those orderings.
VERIFICATION_CONFIRMATION: Final[str] = (
    "✅ Support inbox check — I can post in this chat. Ticket cards will arrive here while "
    "this chat is the selected support group."
)


@dataclass(frozen=True, slots=True)
class VerificationFailure:
    """Why a verification did not succeed, in the two registers its two readers need.

    :attr:`message` is PROSE FOR AN OPERATOR and is the entire point of this feature. It goes
    into ``bot_chats.verification_error``, which is rendered in a list row beside the chat, and
    the person reading it has to know what to DO — add the bot, give it permission, fix the id,
    select the new supergroup. ``BotChatDirectory.record_verification_failed`` states the same
    rule from the storage side and refuses a blank message outright.

    :attr:`reason` is the machine half: a short slug for the log line and for
    :func:`_retry_or_give_up`, so an operator grepping the logs and an operator reading the
    panel are looking at the same classification under two spellings. It is never shown to
    anybody and never stored.

    :attr:`is_retryable` splits the two kinds of failure this job can have, and getting it wrong
    in either direction is a real cost. A terminal verdict retried is two extra minutes of
    "checking…" before somebody learns they mistyped a digit. A transient failure recorded as a
    verdict — Telegram down for ten seconds — is a red row an operator will go and investigate a
    group about, which is nothing to do with the group.
    """

    message: str
    reason: str
    is_retryable: bool
    #: What Telegram asked us to wait, when it asked. ``None`` means the ordinary ladder.
    defer_s: float | None = None


#: Telegram's own words for "the bot is in this chat but may not write in it".
#:
#: Matched case-folded and as SUBSTRINGS, the way ``bayram.bot.delivery``'s
#: :data:`_BLOCKED_BY_USER_MESSAGE` is, because the description is prefixed with ``Bad Request:``
#: and because Telegram has never promised these strings are stable. A phrase that stops
#: matching does not break the job — it falls through to the generic branch, which reports
#: Telegram's own description verbatim — so the cost of drift here is a less specific message
#: and never a wrong one. That is why this is a tuple of phrases rather than a total mapping
#: somebody would have to keep exhaustive.
_CANNOT_POST_PHRASES: Final[tuple[str, ...]] = (
    "not enough rights",
    "have no rights",
    "chat_write_forbidden",
    "chat_send_plain_forbidden",
    "need administrator rights",
    "chat_admin_required",
)

#: Telegram's words for "there is no such chat", which arrives as a 400 rather than a 404.
_NO_SUCH_CHAT_PHRASES: Final[tuple[str, ...]] = ("chat not found", "peer_id_invalid")

#: Telegram's words for "that topic is gone", which is OUR fault rather than the group's: the
#: topic id is a column an operator chose, and it can be deleted out from under the selection.
_NO_SUCH_TOPIC_PHRASES: Final[tuple[str, ...]] = (
    "message thread not found",
    "topic_deleted",
    "topic_closed",
)


def verification_failure_for(
    exc: TelegramAPIError, *, chat_id: int, thread_id: int | None
) -> VerificationFailure:
    """Turn one Telegram refusal into something an operator can act on. Pure, and tested alone.

    **A GENERIC FAILURE STRING DEFEATS THE WHOLE FEATURE, which is why this function exists
    instead of ``repr(exc)``.** A pasted chat id has no membership record behind it — Telegram
    has no "list my groups" API, so pasting is the only route to a group the bot was already in
    — and this job is therefore the only thing standing between an operator and a support inbox
    that is silently dead. "Verification failed" tells them to look at everything; "the bot is
    not a member of this chat — add it and try again" tells them to do one thing.

    Four verdicts are required by the design and all four are here; the fifth and sixth are ones
    this implementation found it could distinguish for free and that an operator would otherwise
    have spent an afternoon on.

    **The migration case is the one that is invisible without this.** When Telegram upgrades a
    basic group to a supergroup the chat ID CHANGES, and the old id keeps answering — so a
    selected group that migrates is a dead inbox that looks exactly like a healthy one. The
    schema's answer is deliberately passive (the new chat arrives as its own row, the old row
    stays selected and stays dead, because ``support_tickets.group_chat_id`` already holds the
    old id and rewriting it would make historical tickets claim their cards were posted
    somewhere they were not). That decision is only RECOVERABLE because this message names the
    new id, which is the single piece of information the operator cannot get any other way.

    **Everything that is not a statement about the chat is retryable, and nothing else is.** A
    flood wait, a network error and a 5xx are facts about Telegram or about us; the rest are
    facts about the room and the id, and asking again produces the same answer more slowly. The
    unrecognised tail is deliberately TERMINAL and carries Telegram's own description: an
    unclassified 400 is still a refusal of this specific chat, and a ladder would delay a
    message that is already as informative as we can make it.
    """
    if isinstance(exc, TelegramMigrateToChat):
        return VerificationFailure(
            message=(
                f"This group was upgraded to a supergroup and its chat id changed to "
                f"{exc.migrate_to_chat_id}. Select that chat instead — this one is dead."
            ),
            reason="migrated",
            is_retryable=False,
        )
    if isinstance(exc, TelegramRetryAfter):
        return VerificationFailure(
            message=(
                "Telegram asked the bot to slow down before the check could finish. "
                "Nothing is wrong with this chat — try again in a minute."
            ),
            reason="flood_wait",
            is_retryable=True,
            # The same margin ``_send`` adds, and for the same reason: obeying a ``retry_after``
            # to the second is the difference between serving a flood wait and extending it.
            defer_s=float(exc.retry_after) + 1.0,
        )
    if isinstance(exc, TelegramForbiddenError):
        return VerificationFailure(
            message=(
                "The bot is not in this chat, or was removed from it. Add @the bot to the "
                "group and select it again."
            ),
            reason="not_a_member",
            is_retryable=False,
        )
    if isinstance(exc, TelegramNetworkError | TelegramServerError):
        return VerificationFailure(
            message=(
                "Telegram could not be reached while checking this chat. Nothing is known "
                "about it yet — try the check again."
            ),
            reason="telegram_unreachable",
            is_retryable=True,
        )
    description = str(exc).casefold()
    if isinstance(exc, TelegramNotFound) or _mentions(description, _NO_SUCH_CHAT_PHRASES):
        return VerificationFailure(
            message=(
                f"Telegram knows no chat with the id {chat_id}. Check the number — a group id "
                f"is negative, and a supergroup's begins with -100."
            ),
            reason="chat_not_found",
            is_retryable=False,
        )
    if thread_id is not None and _mentions(description, _NO_SUCH_TOPIC_PHRASES):
        return VerificationFailure(
            message=(
                f"The topic {thread_id} no longer exists in this group. Select the group again "
                f"and pick a topic that is still there, or select it with no topic at all."
            ),
            reason="topic_missing",
            is_retryable=False,
        )
    if _mentions(description, _CANNOT_POST_PHRASES):
        return VerificationFailure(
            message=(
                "The bot is in this chat but is not allowed to post. Give it permission to "
                "send messages — an administrator can do it in the group's settings."
            ),
            reason="cannot_post",
            is_retryable=False,
        )
    return VerificationFailure(
        # Telegram's own description rather than ours. It is not one of the four named
        # verdicts, but it is still a specific sentence about this specific chat, and handing
        # it over unedited beats inventing a category for a refusal nobody has seen yet.
        message=f"Telegram refused the check: {exc!s}",
        reason="telegram_refused",
        is_retryable=False,
    )


def _mentions(description: str, phrases: tuple[str, ...]) -> bool:
    """Whether a case-folded Telegram description contains any of these phrases."""
    return any(phrase in description for phrase in phrases)


@dataclass(frozen=True, slots=True)
class _Proof:
    """What ``getChat`` told us on the way to a successful post. Every field may be ``None``.

    Carried rather than written at the point it was read, because a title learned from a chat
    the bot then turned out to be unable to POST in is not something this job should record: the
    row would gain a friendly name and keep a stale green badge, which is the exact combination
    the panel reads as "fine". The write happens once, after the send landed.
    """

    title: str | None
    username: str | None
    #: Telegram's own word for the chat's type, which OVERWRITES the one inferred from the id's
    #: shape when a bare number was pasted. See
    #: :func:`~bayram.bot_chats.chat_type_for_pasted_id`: the inference cannot tell a supergroup
    #: from a channel, and it is only allowed to guess because this call corrects it.
    chat_type: BotChatType | None


async def verify_support_group(ctx: Mapping[str, Any], chat_id: str) -> None:
    """Prove the bot can post in the chat an operator just picked, and write down what happened.

    Enqueued by the PANEL, after the selection has COMMITTED. That ordering is not a nicety: the
    same race was a critical defect in the support feature this morning, where the panel
    enqueued while the row was still uncommitted and the worker, finding nothing, treated it as
    terminal. ``bayram.admin.routers.support`` shows the committed-then-enqueued pattern.

    **This job is what makes a pasted chat id safe, and it carries more weight here than it
    would in a design with a ``/register`` command.** Telegram has no "list my groups" API, so a
    group the bot was already sitting in when this feature shipped can never be discovered
    automatically; an operator typing its id into the panel is the only route that exists for
    it, and a typed id has no membership record behind it at all. Nothing else in this system
    ever finds out whether that number names a real room the bot can write into.

    **The order is ``getChat``, then a real message, and both halves are load-bearing.**
    ``getChat`` answers "does this chat exist and what is it called", which is what distinguishes
    a mistyped digit from a permission problem and is where the migration verdict comes from. It
    answers NOTHING about whether we may write, and there is no Telegram call that does —
    ``getChatMember`` returns a status, and a status is evidence rather than permission. So the
    proof is a message that actually landed, sent into the selected TOPIC as well as the
    selected chat, because a group the bot can post in and a topic it cannot are different
    answers to the operator's question.

    **``verified_at`` is written only after the send succeeded**, never after ``getChat``
    returned. A row that claimed verification on the strength of a chat existing would put a
    green badge on exactly the configuration this job was built to catch.

    **The chat does not have to still be selected.** This job is handed an id and checks that
    id; an operator who selects, reconsiders and re-selects within a few seconds gets two honest
    verdicts about two chats rather than one job refusing to answer about the room it was sent
    to. Verification is a fact about a chat, and ``bot_chats`` stores it per chat for that
    reason.

    **A chat that is no longer in the directory is terminal and creates nothing.** Both verdict
    writers return ``False`` for a row that is gone, and re-creating it would resurrect a chat
    an operator deleted on purpose — with whatever partial information this job happened to hold.

    Replayed on every deploy like every job here (``retry_jobs=True`` plus SIGTERM), and safe to
    replay: it re-reads the row, and the worst a duplicate can do is post a second confirmation
    into a room that has just been told the same thing.
    """
    container = _require_container(ctx)
    bot = _require_bot(ctx)
    directory = container.bot_chats
    if directory is None:
        # Not retryable and not the queue's problem: a worker built without a chat directory
        # cannot be given one by waiting. It is an ERROR rather than an INFO because something
        # enqueued this, which means a panel IS wired against a worker that is not.
        _LOG.error(
            "this worker records no chat directory; a group verification cannot be answered",
            extra={"chat_id": chat_id, "job": SUPPORT_VERIFY_JOB_NAME},
        )
        return
    identifier = _job_chat_id(chat_id)

    loaded = await directory.load_chat(identifier)
    if is_err(loaded):
        _LOG.warning(
            "a bot chat could not be read for verification", extra=loaded.error.to_log_dict()
        )
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_VERIFY_MAX_TRIES,
            job=SUPPORT_VERIFY_JOB_NAME,
            subject=str(identifier),
            reason="chat_unreadable",
        )
        return
    chat = loaded.value
    if chat is None:
        # A stale enqueue against a row that has since gone. Not retryable — two more attempts
        # find the same nothing — and not repairable, for the reason ``record_verified`` gives.
        _LOG.error(
            "no bot chat answers this id; there is nothing to verify",
            extra={"chat_id": identifier, "job": SUPPORT_VERIFY_JOB_NAME},
        )
        return

    outcome = await _prove_the_bot_can_post(bot, chat, pacer=group_pacer(ctx))
    if isinstance(outcome, VerificationFailure):
        await _record_verdict_failure(ctx, directory, chat, outcome)
        return
    await _record_verdict_proof(directory, chat, outcome)


def _job_chat_id(value: object) -> int:
    """Read the chat id the panel queued. A value that is not one means the seam is broken.

    :func:`_job_uuid`'s posture for a different shape: this is not a runtime condition a retry
    could recover from, so it raises rather than being swallowed into a job that silently does
    nothing for the life of the deployment.

    **The payload really is a string**, which is why the job's own annotation says so: every
    argument ``bayram.admin.queue`` sends is text (``str(broadcast_id)``, ``public_ref``,
    ``str(ticket_id)``) and one job that took an ``int`` would be one worker signature whose
    shape has to be remembered separately. An ``int`` is accepted anyway because ARQ pickles its
    payloads and would deliver one intact — a caller on the other side of a process boundary
    that sent the honest type should get a working check rather than a refusal.

    ``bool`` is rejected explicitly because it is an ``int`` subclass, and ``True`` would
    otherwise be read as chat id 1 — a positive id, which is a PRIVATE chat and the one thing
    this whole table is shaped to make unrepresentable.
    """
    if isinstance(value, bool):
        raise PipelineError(
            "a group verification was queued with a boolean rather than a chat id",
            context={"job": SUPPORT_VERIFY_JOB_NAME, "value": repr(value)},
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise PipelineError(
                "a group verification was queued with an id that is not a number",
                context={"job": SUPPORT_VERIFY_JOB_NAME, "value": value},
                cause=exc,
            ) from exc
    raise PipelineError(
        "a group verification was queued with an id of the wrong type",
        context={"job": SUPPORT_VERIFY_JOB_NAME, "found": type(value).__name__},
    )


async def _prove_the_bot_can_post(
    bot: Bot, chat: BotChatSnapshot, *, pacer: SendPacer
) -> _Proof | VerificationFailure:
    """``getChat``, then a real message. The proof, or the reason there is none.

    Two calls and one return type, because the caller has exactly one decision to make and both
    calls can produce either answer. Splitting them into two functions would put the "did the
    first one succeed" branch in the caller, where it would sit next to the retry decision and
    invite somebody to retry a ``getChat`` that failed for a reason a retry cannot fix.

    **Only the message charges the group's send budget.** ``getChat`` is not a message and does
    not count against Telegram's per-chat ceiling, so paying a unit for it would meter a limit
    it is not subject to — and on the failing paths, which are the common ones for a freshly
    pasted id, it would spend the group's whole allowance on chats the bot cannot write to.

    **A flood wait parks the SHARED park key on the way past**, which is the half that protects
    something other than this job: ``retry_after`` binds the BOT TOKEN, not the chat, so every
    sender in every process — campaigns, relays, cards — has to stop together. See
    :func:`group_pacer`. The classifier's ``defer_s`` is derived from the same ``retry_after``
    and is used for THIS job's own deferral; the park is what tells everybody else.
    """
    try:
        fetched = await bot.get_chat(chat.chat_id)
    except TelegramRetryAfter as exc:
        await pacer.park_after_flood(exc)
        return verification_failure_for(exc, chat_id=chat.chat_id, thread_id=chat.thread_id)
    except TelegramAPIError as exc:
        return verification_failure_for(exc, chat_id=chat.chat_id, thread_id=chat.thread_id)

    await pacer.acquire()
    try:
        await bot.send_message(
            chat_id=chat.chat_id,
            text=VERIFICATION_CONFIRMATION,
            # ``None`` — which aiogram omits entirely — is the ordinary case, and a ``0`` here
            # would be refused by any group that is not a forum. The column is nullable for
            # exactly that reason; see ``handlers.support._send_card``, which sends the real
            # cards through the identical shape.
            message_thread_id=chat.thread_id,
        )
    except TelegramRetryAfter as exc:
        await pacer.park_after_flood(exc)
        return verification_failure_for(exc, chat_id=chat.chat_id, thread_id=chat.thread_id)
    except TelegramAPIError as exc:
        return verification_failure_for(exc, chat_id=chat.chat_id, thread_id=chat.thread_id)
    return _Proof(
        title=fetched.title, username=fetched.username, chat_type=_chat_type_of(fetched.type)
    )


def _chat_type_of(chat_type: str) -> BotChatType | None:
    """Telegram's ``chat.type`` as the enum the table stores, or ``None`` for one we cannot.

    ``None`` leaves the stored value alone, which is the right answer for the only value that
    can reach here and fail: ``private``. :class:`~bayram.contracts.BotChatType` has no such
    member on purpose, and a bot CAN be handed a positive id by an operator who pasted their own
    account number — in which case the selection was already refused at the panel, but a job is
    not the place to discover that a refusal leaked.
    """
    try:
        return BotChatType(chat_type)
    except ValueError:
        return None


async def _record_verdict_proof(
    directory: BotChatDirectory, chat: BotChatSnapshot, proof: _Proof
) -> None:
    """Write ``verified_at``, and with it whatever ``getChat`` told us about the room.

    OUR clock and not Telegram's: this is a fact about when we tried, not about anything
    Telegram stamped — the opposite of ``first_seen_at``/``last_seen_at``, which the membership
    recorder takes from the update. The writer leaves ``last_seen_at`` alone for that reason,
    so a chat the bot was thrown out of last week does not start looking recently seen because a
    job looked at it this morning.

    ``title``, ``username`` and ``chat_type`` travel because this is usually the first and only
    moment a pasted row learns any of them. A ``None`` leaves the stored value standing.
    """
    written = await directory.record_verified(
        chat.chat_id,
        at=utc_now(),
        title=proof.title,
        username=proof.username,
        chat_type=proof.chat_type,
    )
    if is_err(written):
        # The message landed and the operator can see it in the room; only the badge is
        # missing. Not retried, because a retry would post a second confirmation to prove
        # something the first one already proved.
        _LOG.error(
            "a support group was verified but the proof was not stored",
            extra={"chat_id": chat.chat_id, **written.error.to_log_dict()},
        )
        return
    if not written.value:
        _LOG.warning(
            "the chat was gone before its verification could be stored",
            extra={"chat_id": chat.chat_id},
        )
        return
    _LOG.info(
        "a support group was verified",
        extra={
            "chat_id": chat.chat_id,
            "thread_id": chat.thread_id,
            "source": chat.source.value,
            "is_support_group": chat.is_support_group,
        },
    )


async def _record_verdict_failure(
    ctx: Mapping[str, Any],
    directory: BotChatDirectory,
    chat: BotChatSnapshot,
    failure: VerificationFailure,
) -> None:
    """Ask for another attempt if one could help, and otherwise write the reason down.

    **A retryable failure is recorded on the FINAL attempt rather than dropped**, and that is
    the decision worth arguing. ``record_verification_failed`` clears ``verified_at``, so
    recording "Telegram could not be reached" throws away a green badge that may have been
    earned yesterday and was not disproved today. That is the honest answer anyway: the badge
    means "the bot has been proved able to post here since this row last changed", and a check
    that could not complete has not proved it. The alternative — leaving yesterday's badge up
    after a check nobody could run — is the panel showing an operator a proof it no longer
    holds, which is the one lie this feature cannot afford.

    ``_retry_or_give_up`` raises on every attempt but the last, so reaching the write below IS
    the final attempt. A terminal verdict skips the ladder entirely and is written at once: two
    more attempts at "chat not found" are two more minutes before somebody learns they mistyped
    a digit.
    """
    _LOG.warning(
        "a support group could not be verified",
        extra={
            "chat_id": chat.chat_id,
            "thread_id": chat.thread_id,
            "reason": failure.reason,
            "is_retryable": failure.is_retryable,
            "attempt": _attempt(ctx),
        },
    )
    if failure.is_retryable:
        _retry_or_give_up(
            ctx,
            max_tries=SUPPORT_VERIFY_MAX_TRIES,
            job=SUPPORT_VERIFY_JOB_NAME,
            subject=str(chat.chat_id),
            reason=failure.reason,
            defer_s=failure.defer_s,
        )
    written = await directory.record_verification_failed(
        chat.chat_id, message=failure.message, at=utc_now()
    )
    if is_err(written):
        _LOG.error(
            "a support group verification failed and the reason could not be stored",
            extra={"chat_id": chat.chat_id, **written.error.to_log_dict()},
        )
        return
    if not written.value:
        _LOG.warning(
            "the chat was gone before its verification failure could be stored",
            extra={"chat_id": chat.chat_id},
        )


assert sync_support_card.__name__ == SUPPORT_CARD_JOB_NAME, (
    "the panel's enqueue name and the job function have drifted apart; ARQ would never "
    "dispatch, and every group card would freeze at the status it was posted with"
)
assert relay_support_reply.__name__ == SUPPORT_RELAY_JOB_NAME, (
    "the panel's enqueue name and the job function have drifted apart; ARQ would never "
    "dispatch, and an operator's reply would sit in Redis until it expired"
)
assert verify_support_group.__name__ == SUPPORT_VERIFY_JOB_NAME, (
    "the panel's enqueue name and the job function have drifted apart; ARQ would never "
    "dispatch, and every support group would sit on 'checking…' for ever — which is the one "
    "state this feature exists to get an operator out of"
)
