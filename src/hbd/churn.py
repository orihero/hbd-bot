"""The seam between "a customer blocked us" and where that is recorded.

A customer blocking the bot was recorded nowhere at all. ``bot/delivery.py`` caught
``TelegramForbiddenError`` only to skip a retry, no handler was registered on aiogram's
``my_chat_member`` observer, and ``users`` had no column for it — so "how many customers
left us last month" had no answer, and the dashboard's Churn card could not be drawn
honestly. This module is the port that closes that; ``hbd.db.churn.SqlBotBlocks`` is the
implementation and ``hbd.bot.handlers.membership`` plus ``hbd.runtime.jobs`` are the two
callers.

**Why this is not a method on ``EntitlementStore``.** That seam answers "may this account
render?", every gate in the bot holds it, and ``hbd.bot.deps.BotDeps.entitlements`` is
documented as read-only-for-gates precisely because a gate that could DEBIT could
double-charge. :mod:`hbd.lyric_budget` makes the identical argument for the identical
reason — a separate store because the bot writes this one and may never write a credit —
and it applies here verbatim. A port carrying only the two methods below cannot express a
debit, a refusal or a grant: it can say only that a customer's membership of their own
chat changed.

**Why this module is a LEAF.** It imports ``hbd.contracts`` and nothing else — never
``hbd.db``, never ``hbd.config``. A protocol that named ``hbd.db.enums`` would drag the
whole ``hbd.db`` package into every importer, which is the import cycle
``hbd.entitlements``' docstring already records; and both callers are outside ``hbd.db``
(one is an aiogram handler, the other the ARQ worker's delivery arm).

**Where the vocabulary lives, and why it is not here.** ``BotMembershipEvent`` and
``BotBlockSource`` are declared in :mod:`hbd.contracts` beside ``Vendor`` and ``CostSource``
rather than in this file. Two things force that. They are STORED — ``bot_membership_events``
maps both through ``enum_type`` — and ``tests/test_db/test_enum_lengths.py`` sweeps only
``hbd.contracts`` and the modules under ``hbd.db`` for enums whose members must fit their
column, so an enum declared here would be silently exempt from the check that keeps a
member from being too long for its ``VARCHAR(32)``. And ``hbd.db.enums``' own rule ("nothing
outside the database, the admin panel and the tuning query needs them") is broken by
``BotBlockSource``, which the bot handler and the worker both name. Callers therefore
import the two enums from ``hbd.contracts`` and the protocol from here; this module
deliberately does not re-export them, because one vocabulary reachable by two paths is how
a reader ends up unsure which is canonical.

**Why two named methods rather than one ``is_blocked: bool`` parameter.** A boolean
argument at a call site reads as a flag on one fact, and these are two different facts about
a customer — one of which the dashboard counts as churn and the other as a win-back.
``record_bot_blocked(...)`` and ``record_bot_unblocked(...)`` cannot be confused at a call
site; ``record(..., True)`` can.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from hbd.contracts import BotBlockSource, Result

__all__ = ["BotBlockRecorder"]


@runtime_checkable
class BotBlockRecorder(Protocol):
    """Records that a customer blocked, or unblocked, the bot. Never raises.

    Both methods return ``Result[bool]``, and the boolean is the interesting half: ``True``
    means THIS call recorded a state change, ``False`` means the account was already in that
    state and nothing was written. It is the same "did I win?" primitive
    ``hbd.db.credit_sql.insert_or_ignore`` documents, and it is what lets the two callers
    below race each other safely — a block learned from Telegram's own update and a block
    learned from a refused send are the same fact, and exactly one of them records it.

    **``at`` is a required parameter and not a clock this store owns.** The membership
    handler passes Telegram's own ``ChatMemberUpdated.date``, which is the instant the
    transition actually happened and the instant the daily churn series must group on; the
    worker's delivery arm passes its own clock, because a refused send tells us only that
    the block had already happened by then. A store that stamped ``now()`` itself would
    quietly convert the first of those into the second.

    Neither method ever raises, like every other protocol in this codebase, so the
    ``my_chat_member`` handler needs no ``try`` — which matters more here than anywhere
    else, because that observer carries neither ``ErrorGuardMiddleware`` nor the inbound
    gate and an escaping exception would be logged by aiogram and silently lost.

    ``runtime_checkable`` verifies member PRESENCE only, never signatures; ``mypy --strict``
    over ``tests`` is what actually catches a fake that has drifted.
    """

    async def record_bot_blocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        """Record that this account now has the bot blocked. ``True`` if that was new."""
        ...

    async def record_bot_unblocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        """Record that this account no longer has the bot blocked. ``True`` if that was new.

        ``False`` for an account we have never seen blocked, which includes every
        first-contact ``my_chat_member`` Telegram sends when somebody presses Start for the
        first time. That is the whole reason the answer is a transition and not an event
        count: an "unblocked" row minted for a brand-new customer would put win-backs on the
        dashboard that never happened.
        """
        ...
