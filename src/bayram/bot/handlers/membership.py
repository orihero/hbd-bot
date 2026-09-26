"""``my_chat_member``: who left, and which rooms the bot is standing in.

This router registers on a THIRD observer, which no other router in this tree touches. It
claims no message and no button, it answers nobody, and it writes exactly two facts: that a
customer blocked, or unblocked, the bot, and that the bot was added to — or removed from — a
group. The first had no home at all before — the Churn card on the dashboard could not be
drawn, and the only trace of a departure was a ``TelegramForbiddenError`` in a log line the
worker threw away. The second had no home either, and its absence was worse than invisible: it
was the reason the support group had to be an environment variable.

**TWO REGISTRATIONS ON ONE OBSERVER, AND THEY ARE DISJOINT BY CHAT TYPE RATHER THAN BY
STATUS.** :func:`handle_my_chat_member` takes ``ChatType.PRIVATE`` and writes churn;
:func:`handle_group_my_chat_member` takes ``group``, ``supergroup`` and ``channel`` and writes
``bot_chats``. The split is on the one axis that decides what ``event.chat.id`` MEANS — a
person or a room — which is the axis the paragraph below says is the correctness condition,
and it is the reason two registrations here are safe where two STATUS-filtered ones would not
be. Every possible value of ``chat.type`` is claimed by exactly one of the two, so neither
handler can ever see the other's updates and no update falls between them.

**THE GROUP HALF EXISTS BECAUSE TELEGRAM HAS NO "LIST MY GROUPS" API.** A bot cannot enumerate
its own chats. This update — delivered when the bot's OWN membership changes — is the only
route by which the process ever learns that a group exists, which is why it is recorded rather
than acted on: nothing here decides anything, it writes a directory row and the panel picks the
support inbox out of it (``SUPPORT_TICKETS_SPEC §3.8``). A group the bot was already sitting in
when this shipped produces no such event and can never be discovered; that gap is closed by an
operator pasting a chat id, not by anything in this file.

**The subscription was already paid for**, which is why this half cost one registration and not
a redeployment. ``Dispatcher.start_polling`` resolves ``allowed_updates`` from the registered
observers, so the churn handler below was ALREADY making Telegram send ``my_chat_member`` —
including every group add and remove, which arrived, matched no handler, and were dropped.

**Why ONE handler and not two filtered registrations.** aiogram ships
``ChatMemberUpdatedFilter``, and the obvious wiring is two registrations, one marked
``KICKED`` and one ``MEMBER``. A bare status marker checks only the NEW status, so those two
would be two filters over the same two-valued space — and any status neither of them matched
would vanish with no trace whatsoever. Telegram's member statuses are not a closed set this
code controls: ``restricted`` and ``left`` already exist and more can be added. One handler
turns the unrecognised case into a WARNING naming the status, which is the difference between
learning that the vocabulary moved and never finding out.

**``F.chat.type == ChatType.PRIVATE`` is not decoration; it is the correctness condition.**
It is the only thing that makes ``event.chat.id`` a Telegram USER id. Without it, a group
that adds and removes the bot would arrive here with a NEGATIVE chat id, and the upsert
underneath would mint a phantom ``users`` row keyed on it — polluting both the churn gauge
and every account-shaped aggregate the panel draws, with rows no customer corresponds to.
The group registration is the same condition read backwards, and
:class:`~bayram.contracts.BotChatType` makes it structural rather than conventional: that enum
has no ``private`` member, so a person cannot be spelled into ``bot_chats`` at all.

**``event.date`` and not ``deps.clock()``.** Telegram stamps the transition itself and
aiogram parses it tz-aware UTC. It is the instant the daily churn series groups on, and it is
the one thing that separates this source from the worker's delivery arm, which can only ever
report the moment a send was refused. Substituting our own clock would silently downgrade
the better of the two sources to the weaker one's accuracy. The group half takes BOTH clocks
for the same reason from two directions: ``event.date`` becomes
``bot_chats.first_seen_at``/``last_seen_at`` because it is when Telegram says the bot's
standing changed, and ``deps.clock()`` becomes ``created_at``/``updated_at`` because that is
when this process wrote the row. They can be days apart —
``delete_webhook(drop_pending_updates=True)`` throws away everything that arrived during a
deploy — and collapsing them would either invent a transition or claim a write that did not
happen when it says.

**The polling fact that keeps this handler alive, and can silently kill it.**
``Dispatcher.start_polling`` resolves ``allowed_updates`` from the registered observers when
it is left UNSET (``resolve_used_update_types()``), so registering this handler is what makes
Telegram send ``my_chat_member`` at all. Any future code that passes an explicit
``allowed_updates`` list without ``"my_chat_member"`` in it stops churn being recorded from
this source, with no error anywhere: the numbers simply stop rising.

**What this handler does NOT get, and must therefore not need.** ``InboundGateMiddleware``
and ``ErrorGuardMiddleware`` are both registered per event type on ``message`` and
``callback_query`` only (see ``bayram.bot.app.install_inbound_gate``), so this handler has
neither a throttle nor an error net. An exception escaping it reaches aiogram's own error
middleware, is logged and is lost — and here that is INVISIBLE, because the customer has just
blocked the bot and would see nothing either way. It is therefore written to be structurally
incapable of raising: its one await returns a ``Result``, which is why there is no ``try``
around it and why one is not needed. ``FSMContextMiddleware``, by contrast, IS an outer
middleware on the ``update`` observer and DOES wrap this handler, so it runs inside the
per-chat isolation lock — the one await must stay a single short transaction, or this chat's
other updates queue behind it.

The gate's absence is also deliberate rather than incidental, and the reason is on
``install_inbound_gate``: ``TouchDrain`` would stamp ``last_seen_at`` from a block, corrupting
the active-user series with people who are the opposite of active, and the gate's block check
would refuse to record the churn of exactly the barred accounts an operator most wants to see
leave.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated

from bayram.bot.deps import BotDeps
from bayram.bot_chats import MembershipSighting
from bayram.contracts import BotBlockSource, BotChatStatus, BotChatType, Result, is_ok
from bayram.logging import get_logger

__all__ = [
    "build_router",
    "handle_my_chat_member",
    "handle_group_my_chat_member",
    "GROUP_CHAT_TYPES",
]

_LOG = get_logger(__name__)

#: The chat types the group recorder claims — every value of ``chat.type`` except ``private``.
#:
#: Named rather than spelled inline because the set is an EXHAUSTIVE PARTITION with the churn
#: handler's ``PRIVATE`` filter and not a list of the interesting cases: between them the two
#: registrations claim all four of Telegram's chat types, so no ``my_chat_member`` update can
#: fall between them unnoticed. It is also exactly the member list of
#: :class:`~bayram.contracts.BotChatType`, which is what :func:`_chat_type_of` relies on.
#:
#: ``CHANNEL`` is in it even though nobody would deliberately make a channel the support inbox.
#: The bot can be promoted to administrator of one, Telegram sends this same update when it
#: happens, and dropping it would be the "the vocabulary moved and nobody found out" failure
#: this module's docstring argues against one paragraph further down — with the extra cost that
#: an operator who added the bot to a channel would find the panel silent about it.
GROUP_CHAT_TYPES: Final[frozenset[str]] = frozenset(
    {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL}
)


async def handle_my_chat_member(event: ChatMemberUpdated, deps: BotDeps) -> None:
    """Record the transition this update describes. Answers nothing and never raises.

    ``KICKED`` is Telegram's word for "the user blocked the bot" in a private chat, and
    ``MEMBER`` is the same person coming back. Every other status is logged and dropped
    rather than guessed at: ``restricted`` and ``left`` cannot occur in a private chat today,
    and inventing a meaning for one would put a number on the Churn card that no second
    source would ever corroborate.

    ``deps.bot_blocks is None`` means this deployment does not record churn — the same
    unwired-not-degraded posture ``profiles`` and ``lyric_budget`` take — and the handler
    then does nothing at all rather than failing an update nobody is waiting on.
    """
    recorder = deps.bot_blocks
    if recorder is None:
        return
    # A PRIVATE chat's id IS the account's id; the router's filter is what guarantees that.
    telegram_user_id = event.chat.id
    at = event.date
    status = event.new_chat_member.status
    if status == ChatMemberStatus.KICKED:
        result = await recorder.record_bot_blocked(
            telegram_user_id, at=at, source=BotBlockSource.MEMBERSHIP_UPDATE
        )
        _log_outcome(result, telegram_user_id=telegram_user_id, event="blocked")
        return
    if status == ChatMemberStatus.MEMBER:
        result = await recorder.record_bot_unblocked(
            telegram_user_id, at=at, source=BotBlockSource.MEMBERSHIP_UPDATE
        )
        _log_outcome(result, telegram_user_id=telegram_user_id, event="unblocked")
        return
    _LOG.warning(
        "my_chat_member carried a status this handler does not record",
        extra={"telegram_user_id": telegram_user_id, "status": str(status)},
    )


def _log_outcome(result: Result[bool], *, telegram_user_id: int, event: str) -> None:
    """Three levels, because the three outcomes mean three different things.

    A recorded transition is news (INFO). "Already in that state" is the ordinary answer
    whenever the worker's delivery arm got there first, or Telegram redelivered an update,
    and it is not worth an operator's attention (DEBUG). Only a storage failure is a
    warning, and it carries the typed error rather than a repr.
    """
    if not is_ok(result):
        _LOG.warning(
            "a bot membership transition could not be recorded",
            extra={"telegram_user_id": telegram_user_id, **result.error.to_log_dict()},
        )
        return
    if result.value:
        _LOG.info(
            "bot membership changed",
            extra={"telegram_user_id": telegram_user_id, "event": event},
        )
        return
    _LOG.debug(
        "bot membership was already in that state; nothing recorded",
        extra={"telegram_user_id": telegram_user_id, "event": event},
    )


# ---------------------------------------------------------------------------
# The other half: which rooms the bot is standing in
# ---------------------------------------------------------------------------
async def handle_group_my_chat_member(event: ChatMemberUpdated, deps: BotDeps) -> None:
    """Record that the bot's standing in a GROUP changed. Answers nothing and never raises.

    This is the only automatic route by which this system ever learns that a group exists —
    Telegram has no "list my groups" API — so the handler's job is to lose nothing. It does not
    decide whether the group is interesting, does not post anything into it, and does not so
    much as look at whether it is the selected support inbox. It writes a directory row; an
    operator picks the support group out of that directory in the panel
    (``SUPPORT_TICKETS_SPEC §3.8``).

    **It records a DEPARTURE exactly as it records an arrival**, which is why there is no
    status filter here and why ``left`` and ``kicked`` are members of
    :class:`~bayram.contracts.BotChatStatus` rather than reasons to skip the write. A group the
    bot was thrown out of is a group an operator needs to SEE in the picker — usually because it
    is the one the tickets stopped arriving in — and a recorder that only wrote the good news
    would answer "where did the support inbox go?" with silence.

    **An unrecognised status becomes ``UNKNOWN`` and a WARNING, and is never dropped.** This
    module's docstring makes that argument for the churn half; here the stake is higher, because
    the churn half can afford to ignore a status it cannot interpret and this half cannot: the
    row is the only evidence the chat exists, and a status nobody anticipated would otherwise
    take the whole chat out of the picker. ``bot_status`` is evidence and never permission
    anyway — whether the bot can actually post is ``verified_at``, written by the job that tried
    — so storing a status we do not understand costs nothing and losing the row costs the
    feature.

    **``deps.bot_chats is None`` means this deployment records no chat directory**, the same
    unwired-not-degraded posture ``profiles``, ``lyric_budget`` and ``bot_blocks`` take. The
    support group is then simply never selectable, tickets are still written and the customer is
    still answered.

    Structurally incapable of raising, for the reason this module's docstring gives: the
    ``my_chat_member`` observer carries neither ``InboundGateMiddleware`` nor
    ``ErrorGuardMiddleware``, so an exception escaping here is logged by aiogram and lost — and
    lost in silence, because nobody is waiting on this update. Its one ``await`` returns a
    ``Result``, and the two conversions above it are total functions with a named fallback.
    """
    directory = deps.bot_chats
    if directory is None:
        return
    chat_type = _chat_type_of(event)
    if chat_type is None:
        # Unreachable while the registration's filter and ``GROUP_CHAT_TYPES`` agree, and it is
        # a return rather than an assertion for exactly that reason: if they ever stop agreeing
        # — a new Telegram chat type, a filter somebody widened — the cost must be one log line
        # and not an exception in an observer that has no error guard.
        _LOG.warning(
            "a group membership update named a chat type this recorder cannot store",
            extra={"chat_id": event.chat.id, "chat_type": str(event.chat.type)},
        )
        return
    sighting = MembershipSighting(
        chat_id=event.chat.id,
        chat_type=chat_type,
        title=event.chat.title,
        username=event.chat.username,
        bot_status=_bot_status_of(event),
        # TELEGRAM's clock. See the module docstring: this is when the transition happened, and
        # it can be a long way behind the moment the row is written.
        at=event.date,
    )
    # OURS, and the second half of the same sentence: when this process wrote the row.
    recorded = await directory.record_membership(sighting, now=deps.clock())
    _log_sighting(recorded, sighting=sighting)


def _chat_type_of(event: ChatMemberUpdated) -> BotChatType | None:
    """Telegram's ``chat.type`` as the enum the table stores, or ``None`` if it is not one.

    ``None`` rather than a guess. The three members of :class:`~bayram.contracts.BotChatType`
    are spelled identically to Telegram's own strings, so this is a lookup and not a mapping —
    and the one value that is deliberately missing, ``private``, is the one this function must
    never invent an answer for: it belongs to :func:`handle_my_chat_member`, whose upsert keys
    on a USER id.
    """
    try:
        return BotChatType(event.chat.type)
    except ValueError:
        return None


def _bot_status_of(event: ChatMemberUpdated) -> BotChatStatus:
    """The bot's new standing, with ``UNKNOWN`` and a warning for a word we do not know.

    ``creator`` is the concrete case this exists for today: it is a real Telegram status, a bot
    can never hold it, and being sure of that is not the same as the code being safe if it ever
    arrives. Telegram's member statuses are not a closed set this code controls — the module
    docstring makes the argument in full for the churn half — and the difference between an
    enum that widens and a chat that disappears from the picker is this one ``except``.
    """
    status = event.new_chat_member.status
    try:
        return BotChatStatus(status)
    except ValueError:
        _LOG.warning(
            "a group membership update carried a status this recorder does not know",
            extra={"chat_id": event.chat.id, "status": str(status)},
        )
        return BotChatStatus.UNKNOWN


def _log_sighting(result: Result[bool], *, sighting: MembershipSighting) -> None:
    """Three levels, for :func:`_log_outcome`'s reasons applied to a directory row.

    A chat nobody had ever seen is news worth an INFO line — it is a new row in the picker and
    the only moment this system will ever be told about it. A repeat sighting is the ordinary
    case (a promotion, a re-add after a deploy, a redelivered update) and is DEBUG. Only a
    storage failure is a warning, and it carries the typed error rather than a repr.
    """
    if not is_ok(result):
        _LOG.warning(
            "a group membership change could not be recorded",
            extra={"chat_id": sighting.chat_id, **result.error.to_log_dict()},
        )
        return
    level = _LOG.info if result.value else _LOG.debug
    level(
        "the bot's membership of a group changed",
        extra={
            "chat_id": sighting.chat_id,
            "chat_type": sighting.chat_type.value,
            "bot_status": sighting.bot_status.value,
            "is_first_sighting": result.value,
        },
    )


def build_router() -> Router:
    """A fresh router. Built per dispatcher, never shared — aiogram routers are single-use.

    **ONE router with two registrations, not two routers**, and the choice is load-bearing in a
    place that is easy to miss: ``tests/test_bot/test_membership_handler.py`` asserts that
    exactly one router in the tree carries ``my_chat_member`` handlers, which is what makes this
    router's position in ``handlers.build_router`` provably not load-bearing. A second router on
    the same observer would have an ordering relative to the first, and an ordering is a thing
    somebody has to reason about; two registrations whose filters partition the chat types have
    no ordering to get wrong.

    The registration order below is therefore arbitrary and must stay that way. ``PRIVATE`` and
    :data:`GROUP_CHAT_TYPES` are disjoint, so aiogram's first-match rule never has a choice to
    make. If a future filter here stops being disjoint, that is the bug — not the order.
    """
    router = Router(name="membership")
    router.my_chat_member.register(handle_my_chat_member, F.chat.type == ChatType.PRIVATE)
    router.my_chat_member.register(handle_group_my_chat_member, F.chat.type.in_(GROUP_CHAT_TYPES))
    return router
