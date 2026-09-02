"""The standing commands: ``/balance``, ``/help``, ``/privacy``, ``/support`` and ``/forget``.

The wizard asks for a third party's name and for private facts about them — an old joke, a
hobby, the name only one person uses. Until this module existed the bot collected all of
that and disclosed none of it: there was no ``/privacy``, no way to ask for deletion, and
``set_my_commands`` was never called, so the Telegram command menu was empty and the only
command a customer could discover was the ``/start`` they had already sent.

Three properties this module is built around:

**They work from any state.** None of these handlers carries a state filter, and
:func:`build_router` is registered FIRST in ``handlers/__init__``. A customer who wants to
know what we keep should not have to abandon a half-typed wizard to find out, and — the
sharper half — ``handle_note`` matches any text at the note step, so a ``/help`` typed
there would otherwise be stored verbatim as the note and sung.

**None of them touches the draft, except the one that is supposed to.** ``/balance``,
``/help``, ``/privacy`` and ``/support`` answer alongside the wizard and leave the FSM
exactly where it was; only ``/forget`` clears it, because clearing it is the whole point —
and even that one puts the parking place back when a song is already at the studio, so the
bot does not forget a run it has just promised will still be delivered.

**The menu and the erasure are one commit.** ``/balance`` lives in
:mod:`hbd.bot.handlers.balance` but is advertised and registered here, for the reason the
:data:`BOT_COMMANDS` comment gives; and ``/forget`` now erases the credit record as well as
the draft, because the entitlement layer put two tables behind a notice that had no words
for them.

**The retention numbers are read from the policy, never typed into the copy.** A privacy
notice that says thirty days while the purge job says sixty is worse than no notice, so
:data:`~hbd.db.retention.DEFAULT_RETENTION_POLICY` is interpolated at call time and the
catalogues carry placeholders rather than digits.

Scope of ``/forget``: see :func:`handle_forget`. It deletes the copy this process owns and
it does not pretend to more than that.
"""

from __future__ import annotations

from typing import Any, Final

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message

from hbd.bot.deps import BotDeps
from hbd.bot.handlers.balance import handle_balance
from hbd.bot.handlers.common import error_text, support_text
from hbd.bot.handlers.submitting import (
    ORDER_ID_KEY,
    PROGRESS_MESSAGE_ID_KEY,
    order_in_flight,
)
from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.bot.middleware import resolve_language
from hbd.bot.states import Wizard
from hbd.contracts import Err, Result, ok
from hbd.db.retention import DEFAULT_RETENTION_POLICY
from hbd.logging import get_logger

__all__ = ["build_router", "BOT_COMMANDS"]

_LOG = get_logger(__name__)

#: The Telegram command menu, in the order it is shown. ``/start`` and ``/cancel`` are
#: handled by :mod:`hbd.bot.handlers.start` but are advertised here, because the menu is
#: one surface and splitting it across two modules is how an entry goes missing.
#:
#: The descriptions are English only. Telegram scopes commands by the *client's* language
#: code rather than by the interface language this bot asked for, and there are no
#: ``command.*`` keys in the catalogues to render the other three from; see the module
#: report for the four keys per locale that would close the gap.
BOT_COMMANDS: Final[tuple[BotCommand, ...]] = (
    BotCommand(command="start", description="Make a song"),
    BotCommand(command="cancel", description="Stop the one being made"),
    BotCommand(command="balance", description="Songs left in your allowance"),
    BotCommand(command="help", description="What I can do"),
    BotCommand(command="privacy", description="What I keep, and for how long"),
    BotCommand(command="support", description="Tell me something went wrong"),
    BotCommand(command="forget", description="Delete what I hold about you"),
)


async def handle_help(message: Message, state: FSMContext) -> None:
    """What the bot does and every command it answers. Leaves the wizard untouched."""
    language = await resolve_language(state)
    await message.answer(translate("help.text", language))


async def handle_privacy(message: Message, state: FSMContext) -> None:
    """The retention schedule, rendered from the policy the purge job actually runs on.

    Reading the four periods here rather than writing them into the catalogues is what
    makes the notice provably true: shortening a period in
    :class:`~hbd.db.retention.RetentionPolicy` changes this message in the same commit.
    """
    language = await resolve_language(state)
    policy = DEFAULT_RETENTION_POLICY
    await message.answer(
        translate(
            "privacy.text",
            language,
            recipient_identity_days=policy.recipient_identity_days,
            brief_text_days=policy.brief_text_days,
            paid_audio_days=policy.paid_audio_days,
            abandoned_draft_days=policy.abandoned_draft_days,
        )
    )


async def handle_support(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Where to report a song that came out wrong.

    The copy is rendered by ``common.support_text``, which the Report-a-problem button on
    the closing message also uses: the command and the button must not describe two
    different routes to the same inbox. It is also where the unconfigured case is handled —
    the copy changes, the destination is never faked.
    """
    language = await resolve_language(state)
    await message.answer(support_text(language, deps.settings.support_contact))


async def handle_forget(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Delete the personal data this process holds: the wizard draft and the credit record.

    That draft is not a scratch buffer. It carries the recipient's display name, the
    free-text note about them and — since the preview step — the whole approved lyric, and
    for the many sessions that are abandoned before CONFIRM it is the *only* copy that ever
    existed. Clearing it is a real erasure of a real third party's data.

    **And the credit record, which is on no schedule at all.** The entitlement layer added
    two tables that ``/privacy`` could not truthfully describe: ``credit_accounts`` is a
    live balance and ``credit_ledger`` is append-only, so neither is reached by any of the
    four retention clocks the notice enumerates. ``EntitlementStore.forget`` is the one
    write this side of the seam makes — see :meth:`hbd.entitlements.EntitlementStore.forget`
    for why a data-subject request is not the kind of write the read-only rule exists to
    prevent — and it deletes the balance while anonymising the ledger. The count survives
    without a name on it, because a receipt that erases itself on request cannot answer the
    billing question it exists for; :mod:`hbd.db.credit_erasure` argues the asymmetry.

    A store that FAILS is reported rather than papered over. The draft is gone either way —
    that part is local and irreversible — but ``privacy.forgotten`` now claims the credit
    record was unlinked too, and saying so after a failed write would be exactly the kind of
    false promise this command exists to keep. The customer is told something went wrong and
    ``/forget`` is idempotent, so sending it again finishes the job.

    It is still not the whole story, and this docstring is the honest statement of that: an
    order that reached the queue has rows in Postgres, and ``hbd.db.purge`` exposes only a
    time-based sweep — there is no per-user erasure of the ORDER, and no repository handle
    on :class:`~hbd.bot.deps.BotDeps` to call one with. Those rows go on the schedule
    ``/privacy`` states. Wiring that one is a ``BotDeps`` field and a ``purge_user`` in
    :mod:`hbd.db.purge`; until both exist this command must not be described as deleting
    more than it deletes.

    **A song already at the studio keeps its parking place.** The draft goes either way —
    that is what was asked for — but the FSM is put straight back into ``Wizard.submitting``
    with the order id when one is in flight, because ``privacy.forgotten`` tells the customer
    in the very next sentence that the queued song survives on the ``/privacy`` schedule.
    A bare ``state.clear()`` contradicted that within two taps: with the park gone,
    ``order_in_flight`` went blind, and the next Cancel answered "Cancelled — nothing was
    made, and nothing was kept" about a song that then arrived. The name is gone with the
    draft, so what the bot can still say is ``wizard.still_in_studio``.

    The language is resolved before the clear, or the confirmation would come back in the
    fallback language for every user who had chosen anything else.
    """
    language = await resolve_language(state)
    order_id = await order_in_flight(state)
    progress_message_id = (await state.get_data()).get(PROGRESS_MESSAGE_ID_KEY)
    await state.clear()
    if order_id is not None:
        parked: dict[str, Any] = {ORDER_ID_KEY: order_id}
        if isinstance(progress_message_id, int):
            parked[PROGRESS_MESSAGE_ID_KEY] = progress_message_id
        await state.set_state(Wizard.submitting)
        await state.update_data(parked)
    user = message.from_user
    _LOG.info(
        "wizard draft erased on request",
        extra={
            "user_id": user.id if user else None,
            "is_order_in_flight": order_id is not None,
        },
    )
    keyboard = start_over_keyboard(language)
    erased = await _forget_credits(deps, user.id if user else None)
    if isinstance(erased, Err):
        await message.answer(error_text(erased.error, language), reply_markup=keyboard)
        return
    await message.answer(translate("privacy.forgotten", language), reply_markup=keyboard)


async def _forget_credits(deps: BotDeps, telegram_user_id: int | None) -> Result[None]:
    """Erase the credit record, or say plainly that there was nothing to erase it in.

    An unwired meter and an unknown sender both succeed: neither is a failure the customer
    could act on, and neither leaves a row behind — a deployment with no entitlement store
    has never written one, and an update with no ``from_user`` names nobody to erase.
    """
    store = deps.entitlements
    if store is None or telegram_user_id is None:
        return ok(None)
    erased = await store.forget(telegram_user_id)
    if isinstance(erased, Err):
        _LOG.error("the credit record could not be erased", extra=erased.error.to_log_dict())
    return erased


def build_router() -> Router:
    """A fresh router. Registered FIRST, so a command is never mistaken for an answer.

    No handler here filters on state: these five have to work mid-wizard, and the note step
    accepts any text, so a command that fell through to it would be sung.

    ``/balance`` is registered here rather than in its own router for the same reason it is
    advertised here: the standing commands are one surface, and a menu entry whose handler
    lives in a router nobody remembered to include is exactly how an advertised command
    replies with silence — a failure ``test_commands.py`` now pins from both ends.
    """
    router = Router(name="commands")
    router.message.register(handle_balance, Command("balance"))
    router.message.register(handle_help, Command("help"))
    router.message.register(handle_privacy, Command("privacy"))
    router.message.register(handle_support, Command("support"))
    router.message.register(handle_forget, Command("forget"))
    return router
