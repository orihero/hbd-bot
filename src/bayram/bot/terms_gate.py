"""The Terms gate for the installed base: an onboarded account that owes the Terms is stopped.

IMAGE_VIDEO_SPEC §2.1, D26. A NEW account meets the Terms as an onboarding step, drawn by the
onboarding router. Everybody who finished onboarding before the gate existed — or before the
version was bumped — never passes through onboarding again, so this middleware is what reaches
them: on their next message it compares what they accepted with the pair in force and, until
they accept, answers with the Terms screen instead of letting the update through.

**OUTER, registered after** ``gate.InboundGateMiddleware`` **and before the routers** (the
spec's placement). Outer, because an inner middleware only sees updates a handler already
claimed; after the inbound gate, because a blocked or throttled account is refused there first
and must not also be shown a Terms screen; per observer, so a refused callback can be answered.
It is installed only when a gate is wired (``BotDeps.terms``) — with the version unset it does
not exist, which is the shipped default.

**What it lets through, whatever the account owes** — the allowlist the spec writes down:

* the data-subject commands ``gate.ERASURE_COMMANDS`` exempts (``/privacy``, ``/forget``,
  ``/support``), and ``/start``, ``/terms``, ``/help``, ``/cancel``. Somebody asked to accept
  a text must be able to read it, ask what it means, erase themselves instead, or start over;
* every ``trm:*`` callback — the ✅ and 📄 on the Terms screen itself — and the SETTINGS
  language picker (``lang:set:*``), so the Terms can be re-read in another language before
  accepting. Only that slot: the wizard's ``lang:ui`` and ``lang:out`` buttons advance a draft,
  and ``lang:out`` rewrites the lyric — a vendor LLM call carrying the customer's brief — which
  an account with no acceptance on record must not be able to trigger (D26);
* a REPLY that a support ticket is listening for — exactly what ``support.ListeningTicket``
  would claim (IMAGE_VIDEO_SPEC §2.1). ``/support`` opens a ticket with a command and describes
  it with an ordinary reply, and a gate that let the command through and refused the
  description would open a ticket nobody can fill in. Not every reply to the bot: a reply to
  the note prompt is wizard input, and would reach the lyric writer. That check costs a ticket
  lookup, so it runs only for an account the gate is about to refuse.

**Private chats only.** Every router it protects is private-only; the support group's router
is not, and its Claim and Resolve buttons belong to staff who may never have accepted anything
as customers. A group update is not this gate's to stop, and a Terms screen posted into the
staff room could not be accepted there anyway.

**Where it stands down, because somebody else owns the question.** A customer who has not
finished onboarding — by FSM state or by profile — is the onboarding router's: it asks
language → terms → contact in that order, and a Terms screen drawn from here before the
language question would be drawn in a language nobody chose. ``Wizard.submitting`` is
``handlers.submitting``'s, which answers every update while a song renders; the song is
delivered either way, because the worker never passes through this gate.

**Cost, and why it is ordered as it is.** The allowlist and the state checks are free. Then
:meth:`bayram.terms.TermsGate.standing` — one Redis GET for an account that has accepted, which
is every account but the few being asked right now. Only an account that has NOT accepted pays
``load_identity`` (usually one more FSM read) to learn whether onboarding owns it.

**Fails open.** Like the inbound gate, this is not wrapped by ``ErrorGuardMiddleware`` (outer
runs first), so an exception here would silence the chat. :meth:`TermsGateMiddleware._decide`
is wrapped whole, and anything it raises lets the update through, logged.

**One Terms screen per account per minute** (the ``claim_notice`` pattern,
``bayram.ratelimit``): the refusal of a message is the whole screen, and somebody typing five
messages must not be sent five screens. A refused CALLBACK is always answered — a
``terms.required`` toast every time, because an unanswered callback spins — and additionally
gets the screen when the minute's notice is still unspent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from bayram.bot.callbacks import LanguageCB, LanguageSlot, TermsCB
from bayram.bot.deps import BotDeps
from bayram.bot.gate import ERASURE_COMMANDS
from bayram.bot.handlers.common import COMMAND_PREFIX, ui_language
from bayram.bot.handlers.onboarding import load_identity
from bayram.bot.handlers.support import ListeningTicket
from bayram.bot.i18n import translate
from bayram.bot.ports import Clock, utc_now
from bayram.bot.screens import terms_screen
from bayram.bot.states import Onboarding, Wizard
from bayram.contracts import Language
from bayram.logging import get_logger
from bayram.ratelimit import (
    InboundPolicy,
    InMemoryWindowCounterStore,
    WindowCounterStore,
    claim_notice,
)
from bayram.terms import TermsGate, TermsStanding

__all__ = ["TermsGateMiddleware", "TERMS_ALLOWED_COMMANDS", "TERMS_NOTICE_WINDOW_S"]

_LOG = get_logger(__name__)

#: Commands that reach their handler whatever the account owes (IMAGE_VIDEO_SPEC §2.1): the
#: data-subject three, plus the four a person reading a Terms screen needs.
TERMS_ALLOWED_COMMANDS: Final[frozenset[str]] = ERASURE_COMMANDS | frozenset(
    {"start", "terms", "help", "cancel"}
)

#: At most one full Terms screen per account per this many seconds (§2.1: "at most once per
#: 60 s"). The toast on a refused button is not metered.
TERMS_NOTICE_WINDOW_S: Final[int] = 60

#: The ``claim_notice`` purpose. Its own key, so it never shares a budget with ``error.*``.
_NOTICE_PURPOSE: Final[str] = "terms.gate"

#: Callback prefixes that always pass: the Terms screen's own buttons and the SETTINGS
#: language picker — not the wizard's two language slots (see the module docstring).
_ALLOWED_CALLBACK_PREFIXES: Final[tuple[str, ...]] = (
    f"{TermsCB.__prefix__}:",
    f"{LanguageCB.__prefix__}:{LanguageSlot.SETTINGS.value}:",
)

#: Telegram 400s a callback answer over 200 characters.
_CALLBACK_ANSWER_MAX_CHARS: Final[int] = 200


@dataclass(frozen=True, slots=True)
class _Refusal:
    """One decided refusal: everything :meth:`TermsGateMiddleware._deliver` needs, resolved
    inside the fail-open ``try`` so that delivering it reads nothing that could raise."""

    telegram_user_id: int
    standing: TermsStanding
    gate: TermsGate
    language: Language


class TermsGateMiddleware(BaseMiddleware):
    """Stop an onboarded account that owes the Terms in force. Register ONE instance on both
    observers, so the notice budget is one per account and not one per update type."""

    def __init__(
        self,
        *,
        counters: WindowCounterStore | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._counters = counters if counters is not None else InMemoryWindowCounterStore()
        self._clock = clock
        self._policy = InboundPolicy(window_s=TERMS_NOTICE_WINDOW_S)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        refusal = await self._refusal_for(event, data)
        if refusal is None:
            return await handler(event, data)
        await self._deliver(event, refusal)
        return None

    async def _refusal_for(self, event: TelegramObject, data: dict[str, Any]) -> _Refusal | None:
        """The decision, wrapped so nothing in it can stop the handler running. See the module
        docstring: the handler call is OUTSIDE the ``try`` so a raising handler never runs twice.
        """
        try:
            return await self._decide(event, data)
        except Exception:
            _LOG.exception(
                "the terms gate failed open; the update is being handled",
                extra={"event_type": type(event).__name__},
            )
            return None

    async def _decide(self, event: TelegramObject, data: dict[str, Any]) -> _Refusal | None:
        """``None`` to let the update through; else the refusal, never for ``ACCEPTED``."""
        deps = data.get("deps")
        if not isinstance(deps, BotDeps) or deps.terms is None or not _is_private(event):
            return None
        user = getattr(event, "from_user", None)
        telegram_user_id = getattr(user, "id", None)
        if not isinstance(telegram_user_id, int) or _is_allowed(event):
            return None
        raw_state = data.get("raw_state")
        if isinstance(raw_state, str) and (
            raw_state.startswith(f"{Onboarding.__full_group_name__}:")
            or raw_state == Wizard.submitting.state
        ):
            return None
        standing = await deps.terms.standing(telegram_user_id)
        if standing is TermsStanding.ACCEPTED:
            return None
        state = data.get("state")
        if not isinstance(state, FSMContext):
            return None
        identity = await load_identity(state, deps, telegram_user_id)
        if not identity.is_onboarded:
            # The onboarding router's customer: it asks language → terms → contact.
            return None
        if isinstance(event, Message) and await ListeningTicket()(event, deps):
            # The description (or follow-up) of a ticket /support opened: see the docstring.
            return None
        _LOG.info(
            "an account that owes the terms was stopped",
            extra={"telegram_user_id": telegram_user_id, "standing": standing.value},
        )
        return _Refusal(
            telegram_user_id=telegram_user_id,
            standing=standing,
            gate=deps.terms,
            language=await ui_language(state, deps),
        )

    async def _deliver(self, event: TelegramObject, refusal: _Refusal) -> None:
        """The toast on a button, always; the screen, once a minute. Best effort."""
        language = refusal.language
        # ``claim_notice`` fails open in the speaking direction and never raises.
        is_spoken = await claim_notice(
            self._counters,
            telegram_user_id=refusal.telegram_user_id,
            purpose=_NOTICE_PURPOSE,
            now=self._clock(),
            policy=self._policy,
        )
        screen = terms_screen(
            language, refusal.gate.versions, standing=refusal.standing, url=refusal.gate.url
        )
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(
                    translate("terms.required", language)[:_CALLBACK_ANSWER_MAX_CHARS]
                )
                if is_spoken and isinstance(event.message, Message):
                    await event.message.answer(screen.text, reply_markup=screen.markup)
                return
            if isinstance(event, Message) and is_spoken:
                await event.answer(screen.text, reply_markup=screen.markup)
        except TelegramAPIError:
            _LOG.exception(
                "could not deliver the terms screen",
                extra={"event_type": type(event).__name__},
            )


def _is_private(event: TelegramObject) -> bool:
    """Whether the update comes from a private chat — ``only_in_private``'s test, restated.

    A callback whose message is gone (``None``, or inaccessible) is not known to be private
    and is let through: the routers behind it apply their own chat filters.
    """
    if isinstance(event, Message):
        return event.chat.type == ChatType.PRIVATE
    if isinstance(event, CallbackQuery):
        message = event.message
        return message is not None and message.chat.type == ChatType.PRIVATE
    return False


def _is_allowed(event: TelegramObject) -> bool:
    """The free half of the allowlist in the module docstring, checkable from the update alone.
    The support reply is the other half, in :meth:`TermsGateMiddleware._decide`."""
    if isinstance(event, CallbackQuery):
        return (event.data or "").startswith(_ALLOWED_CALLBACK_PREFIXES)
    if not isinstance(event, Message):
        return True
    text = event.text or event.caption or ""
    if not text.startswith(COMMAND_PREFIX):
        return False
    word = text.split(maxsplit=1)[0].removeprefix(COMMAND_PREFIX)
    return word.split("@", 1)[0].casefold() in TERMS_ALLOWED_COMMANDS
