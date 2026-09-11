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
:mod:`bayram.bot.handlers.balance` but is advertised and registered here, for the reason the
:data:`BOT_COMMANDS` comment gives; and ``/forget`` erases the customer's profile and their
credit record as well as the draft, because onboarding and the entitlement layer each put a
table behind a notice that had no words for it.

**The retention numbers are read from the policy, never typed into the copy.** A privacy
notice that says thirty days while the purge job says sixty is worse than no notice, so
:data:`~bayram.db.retention.DEFAULT_RETENTION_POLICY` is interpolated at call time and the
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

from bayram.bot.deps import BotDeps
from bayram.bot.handlers.balance import handle_balance
from bayram.bot.handlers.common import error_text, privacy_text, support_text
from bayram.bot.handlers.submitting import (
    ORDER_ID_KEY,
    PROGRESS_MESSAGE_ID_KEY,
    order_in_flight,
)
from bayram.bot.i18n import translate
from bayram.bot.keyboards import start_over_keyboard
from bayram.bot.middleware import resolve_language
from bayram.bot.states import Wizard
from bayram.contracts import Err, Language, Result, ok
from bayram.db.retention import DEFAULT_RETENTION_POLICY
from bayram.logging import get_logger

__all__ = ["build_router", "BOT_COMMANDS", "COMMAND_ORDER", "commands_for"]

_LOG = get_logger(__name__)

#: The Telegram command menu, in the order it is shown. ``/start`` and ``/cancel`` are
#: handled by :mod:`bayram.bot.handlers.start` but are advertised here, because the menu is
#: one surface and splitting it across two modules is how an entry goes missing.
#:
#: Telegram scopes commands by the *client's* language code rather than by the interface
#: language this bot asked for, so the descriptions live in the catalogues as ``command.*``
#: and :func:`commands_for` renders one list per locale. ``BOT_COMMANDS`` stays the English
#: cut, because English is the reference catalogue and the menu's order is pinned here.
#:
#: **There is deliberately no ``/settings`` entry**, and the decision is recorded here rather
#: than left to be re-litigated: ⚙️ Sozlamalar is a button on the persistent reply keyboard,
#: pinned under the text box on every screen, which is a more discoverable route than a
#: command anybody would have to open this list to find. The list is already seven long — the
#: point at which a menu stops being read — and a command whose only job is to render an
#: inline screen would duplicate a button the customer is looking at while they scroll past
#: it. Language, privacy and support all live behind that button, and ``/privacy`` and
#: ``/support`` keep their entries because they are the two a person reaches for in a hurry.
COMMAND_ORDER: Final[tuple[str, ...]] = (
    "start",
    "cancel",
    "balance",
    "help",
    "privacy",
    "support",
    "forget",
)


def commands_for(language: Language) -> list[BotCommand]:
    """The menu in one language, in :data:`COMMAND_ORDER`.

    Clients do not re-sort, so the order here is the order the customer scrolls. Every entry
    is rendered from the catalogue, which means a missing translation is caught by
    ``tests/test_bot/test_i18n.py`` at build time rather than by Telegram rejecting an empty
    description at startup.
    """
    return [
        BotCommand(command=name, description=translate(f"command.{name}", language))
        for name in COMMAND_ORDER
    ]


BOT_COMMANDS: Final[tuple[BotCommand, ...]] = tuple(commands_for(Language.EN))


async def handle_help(message: Message, state: FSMContext) -> None:
    """What the bot does and every command it answers. Leaves the wizard untouched."""
    language = await resolve_language(state)
    await message.answer(translate("help.text", language))


async def handle_privacy(message: Message, state: FSMContext) -> None:
    """The retention schedule, rendered from the policy the purge job actually runs on.

    Reading the four periods here rather than writing them into the catalogues is what
    makes the notice provably true: shortening a period in
    :class:`~bayram.db.retention.RetentionPolicy` changes this message in the same commit.

    **The body itself has moved to** :func:`~bayram.bot.handlers.common.privacy_text`, because
    this is no longer the only surface that offers it: 🔒 on the ⚙️ Settings screen renders
    the same notice from a ``CallbackQuery`` handler, which could not call this one and
    would otherwise have grown a second copy of the four kwargs — drifting from this one the
    first time a period changed. A privacy notice that says two different things depending
    on which button you pressed is worse than no privacy notice, which is the same rule
    ``common.support_text`` was extracted under.

    Four kwargs and no fifth: ``privacy.text``'s placeholder set is unchanged by this
    release. Its PROSE now names the phone number, the username, the name and the photo and
    says they are kept for as long as the account exists and erased by ``/forget``, which is
    a fact with no clock on it — so there is nothing here to interpolate, and a kwarg with
    no matching placeholder would be silently dropped by ``i18n._SafeParams``.
    """
    language = await resolve_language(state)
    await message.answer(privacy_text(language, DEFAULT_RETENTION_POLICY))


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
    """Delete the personal data this process holds: the profile, the draft, the credit record.

    That draft is not a scratch buffer. It carries the recipient's display name, the
    free-text note about them and — since the preview step — the whole approved lyric, and
    for the many sessions that are abandoned before CONFIRM it is the *only* copy that ever
    existed. Clearing it is a real erasure of a real third party's data.

    **And the profile, which is the customer's own data rather than a third party's.** The
    ``user_profiles`` row holds their phone number, their ``@username``, the name Telegram
    gave for them and their profile photograph — the most sensitive things this product
    stores about anybody, and the only ones that identify the person sending the command
    rather than the person the song is for. :func:`_forget_profile` DELETES that row and the
    stored avatar object; it does not null a set of columns, because a half-erased row is
    still a row that says somebody was here, and the whole promise of this command is that
    afterwards there is nothing to distinguish an erased customer from one who has never
    used the bot.

    **Both erasures are attempted, always, and the profile one goes first.** Ordering is not
    stylistic: the number and the face outrank the balance, so if only one write survives an
    outage it should be that one. Neither is conditional on the other — making the credit
    erasure depend on the profile write succeeding would turn one permanently broken store
    into a permanent refusal to honour the rest of a data-subject request, which is exactly
    the failure this command exists to make impossible. Both calls are idempotent, so
    attempting both and reporting the FIRST failure costs nothing and loses nothing; sending
    ``/forget`` again finishes whichever half did not land.

    **And the credit record, which is on no schedule at all.** The entitlement layer added
    two tables that ``/privacy`` could not truthfully describe: ``credit_accounts`` is a
    live balance and ``credit_ledger`` is append-only, so neither is reached by any of the
    four retention clocks the notice enumerates. ``EntitlementStore.forget`` is the one
    write this side of the seam makes — see :meth:`bayram.entitlements.EntitlementStore.forget`
    for why a data-subject request is not the kind of write the read-only rule exists to
    prevent — and it deletes the balance while anonymising the ledger. The count survives
    without a name on it, because a receipt that erases itself on request cannot answer the
    billing question it exists for; :mod:`bayram.db.credit_erasure` argues the asymmetry.

    A store that FAILS is reported rather than papered over. The draft is gone either way —
    that part is local and irreversible — but ``privacy.forgotten`` claims the profile and
    the credit record went with it, and saying so after a failed write would be exactly the
    kind of false promise this command exists to keep. The customer is told something went
    wrong and ``/forget`` is idempotent, so sending it again finishes the job.

    **The clear is BARE, and that is the change this release makes here.** Every other
    ``state.clear()`` in the bot has become ``common.clear_keeping_identity``, which
    preserves the two FSM keys that are not session state — which language to speak, and
    whether we have already asked for a phone number. This one deliberately does not use it.
    ``/forget`` returns the account to true first-contact state: the row is DELETED, both
    caches die with the draft, and the very next ``/start`` re-runs BOTH questions — the
    language and the number — because after this command there is genuinely no record that
    either was ever answered, and a bot that remembered the answers would be contradicting
    its own confirmation. That confirmation says so out loud: ``privacy.forgotten`` now
    tells the customer the number, the username, the name and the photo are gone and that
    both questions come again next time.

    It is still not the whole story, and this docstring is the honest statement of that: an
    order that reached the queue has rows in Postgres, and ``bayram.db.purge`` exposes only a
    time-based sweep — there is no per-user erasure of the ORDER, and no repository handle
    on :class:`~bayram.bot.deps.BotDeps` to call one with. Those rows go on the schedule
    ``/privacy`` states. The PROFILE half of that gap is now closed — ``deps.profiles`` is
    the handle, and :func:`_forget_profile` is the call — but the order half is untouched by
    it. Wiring that one is a further ``BotDeps`` field and a ``purge_user`` in
    :mod:`bayram.db.purge` that is PLANNED and does not exist (``docs/product/ADMIN_PANEL_PLAN.md``
    §9.3); until both exist this command must not be described as deleting more than it
    deletes.

    **A song already at the studio keeps its parking place.** The draft goes either way —
    that is what was asked for — but the FSM is put straight back into ``Wizard.submitting``
    with the order id when one is in flight, because ``privacy.forgotten`` tells the customer
    in the very next sentence that the queued song survives on the ``/privacy`` schedule.
    A clear with no re-park contradicted that within two taps: with the park gone,
    ``order_in_flight`` went blind, and the next Cancel answered "Cancelled — nothing was
    made, and nothing was kept" about a song that then arrived. The name is gone with the
    draft, so what the bot can still say is ``wizard.still_in_studio``.

    That re-park is now load-bearing in a second way. The onboarding router's catch-all
    claims any update from a customer with no profile row — which, one statement earlier, is
    every customer who has just used this command — and it would happily set
    ``Onboarding.language`` over the park and put the wizard's parked order beyond
    ``order_in_flight``'s reach, re-opening the exact defect above. It cannot, because both
    new routers stand down for ``Wizard.submitting`` at the router level. The stand-down and
    this re-park are one mechanism seen from two files.

    The language is resolved before the clear, or the confirmation would come back in the
    fallback language for every user who had chosen anything else.
    """
    language = await resolve_language(state)
    order_id = await order_in_flight(state)
    progress_message_id = (await state.get_data()).get(PROGRESS_MESSAGE_ID_KEY)
    await state.clear()  # BARE, and the only one left in the tree. See the docstring.
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
    telegram_user_id = user.id if user else None
    forgotten = await _forget_profile(deps, telegram_user_id)
    erased = await _forget_credits(deps, telegram_user_id)
    failure = forgotten if isinstance(forgotten, Err) else erased
    if isinstance(failure, Err):
        await message.answer(error_text(failure.error, language), reply_markup=keyboard)
        return
    await message.answer(translate("privacy.forgotten", language), reply_markup=keyboard)


async def _forget_profile(deps: BotDeps, telegram_user_id: int | None) -> Result[None]:
    """Erase who the customer is: the ``user_profiles`` row and the avatar's bytes.

    What goes is the phone number, the ``@username``, the first and last names Telegram gave
    for them, and the stored profile photograph. The row is DELETED rather than blanked, and
    the object is unlinked, because this table is on none of the four retention clocks
    ``/privacy`` enumerates — the absence of the row IS the erasure record, and a row of
    nulls would be a lasting statement that somebody was here. The ``users`` row survives on
    purpose: an operator's block must outlast a data-subject request, or the request becomes
    a way to lift one.

    An unwired store and an unknown sender both succeed, exactly as :func:`_forget_credits`
    does. Neither is a failure the customer could act on: a deployment with no profile store
    has never written a row to erase, and an update with no ``from_user`` names nobody. The
    two helpers are deliberately the same shape, because the caller reports the first ``Err``
    of the pair and a difference between them would show up there as an inconsistency in what
    "it worked" means.
    """
    store = deps.profiles
    if store is None or telegram_user_id is None:
        return ok(None)
    forgotten = await store.forget(telegram_user_id)
    if isinstance(forgotten, Err):
        _LOG.error("the profile could not be erased", extra=forgotten.error.to_log_dict())
    return forgotten


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
