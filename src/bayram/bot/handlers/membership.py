"""``my_chat_member``: the one update that tells us a customer left, at the instant they did.

This router registers on a THIRD observer, which no other router in this tree touches. It
claims no message and no button, it answers nobody, and it writes exactly one fact: that a
customer blocked, or unblocked, the bot. That fact had no home at all before — the Churn
card on the dashboard could not be drawn, and the only trace of a departure was a
``TelegramForbiddenError`` in a log line the worker threw away.

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

**``event.date`` and not ``deps.clock()``.** Telegram stamps the transition itself and
aiogram parses it tz-aware UTC. It is the instant the daily churn series groups on, and it is
the one thing that separates this source from the worker's delivery arm, which can only ever
report the moment a send was refused. Substituting our own clock would silently downgrade
the better of the two sources to the weaker one's accuracy.

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

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated

from bayram.bot.deps import BotDeps
from bayram.contracts import BotBlockSource, Result, is_ok
from bayram.logging import get_logger

__all__ = ["build_router", "handle_my_chat_member"]

_LOG = get_logger(__name__)


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


def build_router() -> Router:
    """A fresh router. Built per dispatcher, never shared — aiogram routers are single-use."""
    router = Router(name="membership")
    router.my_chat_member.register(handle_my_chat_member, F.chat.type == ChatType.PRIVATE)
    return router
