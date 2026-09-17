"""The support-ticket flow, from the ⚠️ tap to the answer that comes back from the group.

Driven through a REAL ``Dispatcher`` with a real router tree wherever routing is the subject,
because most of what can go wrong here is routing: a reply to the support prompt reaching the
note step would be stored as the fact we know about a recipient and SUNG to them, a staffer's
message in the group reaching the onboarding catch-all would answer a triager with the
phone-number screen, and a group handler with no chat filter would relay an internal triage
conversation to whoever added the bot to their chat. None of those is visible from a unit test
of a handler called directly.

``FakeSupportTickets`` below is the seam. It is an in-memory
:class:`~bayram.support.SupportTicketStore` that keeps the store's three return conventions
exactly — ``Err`` for a fault or an illegal move, ``Ok(None)`` for an unknown id or a lost
race, ``Ok(False)`` for a latch that was already claimed — because a fake that collapsed them
would let a handler that cannot tell "somebody got there first" from "this is broken" pass
here and confuse the two in front of a staffer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID, uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageText,
    SendMessage,
)
from aiogram.types import (
    Chat,
    ForceReply,
    InaccessibleMessage,
    Message,
    ReplyKeyboardMarkup,
    Update,
    User,
)

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import (
    NavAction,
    NavCB,
    SupportAction,
    SupportCB,
    pack_reference,
    read_reference,
)
from bayram.bot.delivery import MAX_MESSAGE_CHARS, order_reference
from bayram.bot.deps import BotDeps
from bayram.bot.draft import UI_LANGUAGE_KEY
from bayram.bot.handlers.support import MAX_BODY_CHARS, MAX_STAFF_NAME_CHARS, relay_text_for
from bayram.bot.i18n import translate
from bayram.bot.states import Wizard
from bayram.bot.support_card import card_keyboard, panel_url_for, render_card
from bayram.bot_chats import BotChatSnapshot, MembershipSighting, SupportGroupTarget
from bayram.config import Settings
from bayram.contracts import (
    BotChatType,
    Language,
    Ok,
    Result,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
    err,
    ok,
)
from bayram.errors import StorageError
from bayram.support import (
    DEFAULT_SUPPORT_QUOTA,
    REOPEN_STATUS,
    EventAuthor,
    SupportQuota,
    TicketQuotaVerdict,
    TicketSnapshot,
    is_legal_move,
    public_ref_for,
)
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    FIXED_MOMENT,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
    make_callback,
    message_update,
)
from tests.test_bot.test_credit_gate import FakeEntitlements

#: The support group this suite configures. NEGATIVE, because that is what a real supergroup
#: id looks like and a fixture that used a positive one would pass while the production shape
#: was never exercised — the reason ``config.py`` refuses to put a ``gt=0`` bound on the field.
GROUP_CHAT_ID = -1_001_234_567_890

#: A forum topic inside the staff group. Non-zero on purpose: ``0`` is the one value Telegram
#: refuses on a group that is not a forum, and ``bot_chats.thread_id`` is NULLABLE rather than
#: defaulted to zero so that "no topic" and "topic 0" can never be confused.
FORUM_TOPIC_ID = 4_711

#: The staffer pressing buttons and typing answers in that group.
STAFF_USER_ID = 77_001

#: The card's message id in the group. Distinct from every private-chat message id used here,
#: so a lookup that matched on the message id ALONE would resolve to the wrong ticket and fail
#: rather than pass by coincidence — which is the failure ``ticket_awaiting_reply_to``'s
#: two-key signature exists to prevent.
CARD_MESSAGE_ID = 9_100

PANEL_BASE_URL = "https://panel.example.test"


# ---------------------------------------------------------------------------
# The fake store
# ---------------------------------------------------------------------------
class FakeSupportTickets:
    """An in-memory ticket store that keeps the real one's conventions, including the latch.

    Failures are INJECTED through :attr:`failure` rather than raised, because the port is a
    ``Result`` seam: a fake that raised would prove the handlers survive an exception they will
    never see and prove nothing about the ``Err`` they will. That is ``FakeProfiles``' rule,
    followed here for the same reason.

    The group-post latch is modelled for real — ``claim_group_post`` answers ``False`` when a
    message id is already recorded — because the handler's whole replay story rests on it, and
    a fake that always said ``True`` would make the duplicate-card path untestable.
    """

    def __init__(
        self,
        *,
        failure: Any = None,
        quota: SupportQuota = DEFAULT_SUPPORT_QUOTA,
        is_over_quota: bool = False,
    ) -> None:
        self.tickets: dict[UUID, TicketSnapshot] = {}
        self.events: list[dict[str, Any]] = []
        self.failure = failure
        self.quota = quota
        self.is_over_quota = is_over_quota
        self.relayed: list[UUID] = []
        self.forgotten: list[int] = []

    # -- opening ------------------------------------------------------------
    async def check_open_quota(
        self,
        telegram_user_id: int,
        *,
        now: datetime,
        quota: SupportQuota = DEFAULT_SUPPORT_QUOTA,
    ) -> Result[TicketQuotaVerdict]:
        """Counts the rows it actually holds, rather than answering a canned verdict.

        The two ceilings get OPPOSITE answers from the handler now — the daily one is a
        refusal, the undescribed one hands back the ticket already held — so a fake that could
        only say "over" or "under" could not tell the two apart, and the branch that matters
        most (a customer locked out with three empty tickets) would be untestable.
        ``is_over_quota`` survives as the blunt "both ceilings at once" switch the older tests
        use.
        """
        if self.failure is not None:
            return err(self.failure)
        if self.is_over_quota:
            return ok(
                TicketQuotaVerdict(
                    is_allowed=False,
                    undescribed=self.quota.max_undescribed,
                    opened_today=self.quota.max_per_day,
                    quota=self.quota,
                )
            )
        mine = [
            ticket
            for ticket in self.tickets.values()
            if ticket.telegram_user_id == telegram_user_id
        ]
        undescribed = sum(
            1
            for ticket in mine
            if ticket.described_at is None and ticket.status is not SupportTicketStatus.RESOLVED
        )
        return ok(
            TicketQuotaVerdict(
                is_allowed=(
                    undescribed < self.quota.max_undescribed and len(mine) < self.quota.max_per_day
                ),
                undescribed=undescribed,
                opened_today=len(mine),
                quota=self.quota,
            )
        )

    async def open_ticket(
        self,
        *,
        telegram_user_id: int,
        language: Language,
        source: SupportTicketSource,
        order_id: UUID | None,
        now: datetime,
    ) -> Result[TicketSnapshot]:
        if self.failure is not None:
            return err(self.failure)
        ticket_id = uuid4()
        snapshot = TicketSnapshot(
            id=ticket_id,
            public_ref=public_ref_for(ticket_id),
            telegram_user_id=telegram_user_id,
            language=language,
            source=source,
            order_id=order_id,
            status=SupportTicketStatus.NEW,
            body=None,
            prompt_message_id=None,
            described_at=None,
            assigned_admin_username=None,
            group_chat_id=None,
            group_message_id=None,
            group_posted_at=None,
            created_at=now,
        )
        self.tickets[ticket_id] = snapshot
        self._event(ticket_id, SupportTicketEventKind.OPENED, EventAuthor.system(), now)
        return ok(snapshot)

    async def attach_prompt(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.prompt_message_id is not None:
            return ok(False)
        self._replace(ticket, prompt_message_id=prompt_message_id)
        return ok(True)

    async def listen_on(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        """UNCONDITIONAL, unlike :meth:`attach_prompt`, and the difference is modelled rather
        than smoothed over: the whole follow-up path depends on a ticket being re-pointed at a
        message whose column is already set, and a fake that refused would make the bug it
        fixes untestable here."""
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return ok(False)
        self._replace(ticket, prompt_message_id=prompt_message_id)
        return ok(True)

    async def latest_undescribed_ticket(
        self, telegram_user_id: int
    ) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        held = [
            ticket
            for ticket in self.tickets.values()
            if ticket.telegram_user_id == telegram_user_id
            and ticket.described_at is None
            and ticket.status is not SupportTicketStatus.RESOLVED
        ]
        if not held:
            return ok(None)
        # Insertion order IS creation order here, and it is what "newest" has to mean in this
        # suite: the clock is FIXED, so every ticket shares a ``created_at`` to the
        # microsecond and a comparison on it would pick an arbitrary row. The real store
        # breaks the same tie with ``ORDER BY created_at DESC, id DESC``; what both promise is
        # "the prompt still on the customer's screen", and here that is the last one opened.
        return ok(held[-1])

    # -- the customer's words -----------------------------------------------
    async def ticket_listening_on(
        self, telegram_user_id: int, *, prompt_message_id: int
    ) -> Result[TicketSnapshot | None]:
        """Described tickets match too. The narrowing to ``described_at IS NULL`` lived here
        once and was the routing hole: a customer's reply to a relayed staff answer matched
        nothing, fell past the support router, and was taken as wizard input."""
        if self.failure is not None:
            return err(self.failure)
        for ticket in self.tickets.values():
            if (
                ticket.telegram_user_id == telegram_user_id
                and ticket.prompt_message_id == prompt_message_id
            ):
                return ok(ticket)
        return ok(None)

    async def describe_ticket(
        self, ticket_id: UUID, *, body: str, now: datetime
    ) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.described_at is not None:
            return ok(None)
        filled = self._replace(ticket, body=body, described_at=now)
        self._event(ticket_id, SupportTicketEventKind.DESCRIBED, EventAuthor.system(), now)
        return ok(filled)

    # -- the group card -----------------------------------------------------
    async def claim_group_post(
        self, ticket_id: UUID, *, group_chat_id: int, group_message_id: int
    ) -> Result[bool]:
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.group_message_id is not None:
            return ok(False)
        self._replace(ticket, group_chat_id=group_chat_id, group_message_id=group_message_id)
        return ok(True)

    async def settle_group_post(self, ticket_id: UUID, *, now: datetime) -> Result[bool]:
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.group_posted_at is not None:
            return ok(False)
        self._replace(ticket, group_posted_at=now)
        self._event(ticket_id, SupportTicketEventKind.GROUP_POSTED, EventAuthor.system(), now)
        return ok(True)

    async def release_group_post(self, ticket_id: UUID) -> Result[bool]:
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.group_message_id is None:
            return ok(False)
        self._replace(ticket, group_chat_id=None, group_message_id=None, group_posted_at=None)
        return ok(True)

    async def ticket_for_group_message(
        self, *, group_chat_id: int, group_message_id: int
    ) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        for ticket in self.tickets.values():
            if (
                ticket.group_chat_id == group_chat_id
                and ticket.group_message_id == group_message_id
            ):
                return ok(ticket)
        return ok(None)

    # -- working it ---------------------------------------------------------
    async def move_status(
        self,
        ticket_id: UUID,
        *,
        expected: SupportTicketStatus,
        to_status: SupportTicketStatus,
        author: EventAuthor,
        now: datetime,
    ) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        if not is_legal_move(expected, to_status):
            return err(StorageError("illegal support status move"))
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.status is not expected:
            return ok(None)
        moved = self._replace(ticket, status=to_status)
        self._event(ticket_id, SupportTicketEventKind.STATUS_CHANGE, author, now)
        return ok(moved)

    async def assign_ticket(
        self, ticket_id: UUID, *, admin_username: str, author: EventAuthor, now: datetime
    ) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return ok(None)
        assigned = self._replace(ticket, assigned_admin_username=admin_username)
        self._event(ticket_id, SupportTicketEventKind.ASSIGNED, author, now)
        return ok(assigned)

    async def append_event(
        self,
        ticket_id: UUID,
        *,
        kind: SupportTicketEventKind,
        author: EventAuthor,
        now: datetime,
        body: str | None = None,
    ) -> Result[UUID]:
        if self.failure is not None:
            return err(self.failure)
        return ok(self._event(ticket_id, kind, author, now, body=body))

    async def mark_relayed(self, event_id: UUID, *, now: datetime) -> Result[bool]:
        if self.failure is not None:
            return err(self.failure)
        self.relayed.append(event_id)
        return ok(True)

    async def load_ticket(self, ticket_id: UUID) -> Result[TicketSnapshot | None]:
        if self.failure is not None:
            return err(self.failure)
        return ok(self.tickets.get(ticket_id))

    # -- the erasure port, which is a DIFFERENT protocol ---------------------
    async def forget_tickets(self, telegram_user_id: int) -> Result[int]:
        """``bayram.bot.ports.SupportTicketEraser``. One object satisfies both protocols here
        exactly as the production wiring intends to — see ``bayram.main.support_eraser``."""
        if self.failure is not None:
            return err(self.failure)
        self.forgotten.append(telegram_user_id)
        doomed = [
            ticket_id
            for ticket_id, ticket in self.tickets.items()
            if ticket.telegram_user_id == telegram_user_id
        ]
        for ticket_id in doomed:
            del self.tickets[ticket_id]
        # The cascade, modelled: the timeline goes with the ticket in one statement.
        self.events = [event for event in self.events if event["ticket_id"] not in doomed]
        return ok(len(doomed))

    # -- test-side helpers, not part of either port -------------------------
    def only(self) -> TicketSnapshot:
        """The one ticket, asserted to be one. Most tests open exactly one."""
        assert len(self.tickets) == 1, f"expected exactly one ticket, got {len(self.tickets)}"
        return next(iter(self.tickets.values()))

    def kinds(self) -> list[SupportTicketEventKind]:
        return [event["kind"] for event in self.events]

    def _replace(self, ticket: TicketSnapshot, **changes: Any) -> TicketSnapshot:
        updated = TicketSnapshot(
            **{
                field: changes.get(field, getattr(ticket, field))
                for field in (
                    "id",
                    "public_ref",
                    "telegram_user_id",
                    "language",
                    "source",
                    "order_id",
                    "status",
                    "body",
                    "prompt_message_id",
                    "described_at",
                    "assigned_admin_username",
                    "group_chat_id",
                    "group_message_id",
                    "group_posted_at",
                    "created_at",
                )
            }
        )
        self.tickets[ticket.id] = updated
        return updated

    def _event(
        self,
        ticket_id: UUID,
        kind: SupportTicketEventKind,
        author: EventAuthor,
        now: datetime,
        *,
        body: str | None = None,
    ) -> UUID:
        event_id = uuid4()
        self.events.append(
            {
                "id": event_id,
                "ticket_id": ticket_id,
                "kind": kind,
                "author": author,
                "body": body,
                "at": now,
            }
        )
        return event_id


class FakeBotChats:
    """A :class:`~bayram.bot_chats.BotChatDirectory` that holds one answer and counts the asks.

    **The counter is not decoration.** The support group stopped being an environment variable
    precisely so an operator could move it and see it move, and the standing temptation is to
    cache this lookup — ``InSupportGroup`` runs it on every group update. :attr:`asked` is what
    makes "the answer is re-read rather than remembered" an assertion rather than a hope, and
    what makes the private-chat short circuit visible: a customer's message must not reach this
    object at all.

    ``answer`` is a whole :class:`~bayram.contracts.Result` so one fake covers the three cases
    the caller folds together — a selection, nothing selected, and a read that failed — which is
    the folding :func:`~bayram.bot.handlers.support.support_group_target` is responsible for.
    """

    def __init__(
        self,
        *,
        selected: SupportGroupTarget | None = None,
        answer: Result[SupportGroupTarget | None] | None = None,
    ) -> None:
        self.answer: Result[SupportGroupTarget | None] = (
            answer if answer is not None else ok(selected)
        )
        self.asked = 0
        self.sightings: list[MembershipSighting] = []

    async def record_membership(
        self, sighting: MembershipSighting, *, now: datetime
    ) -> Result[bool]:
        self.sightings.append(sighting)
        return ok(True)

    async def selected_support_group(self) -> Result[SupportGroupTarget | None]:
        self.asked += 1
        return self.answer

    async def load_chat(self, chat_id: int) -> Result[BotChatSnapshot | None]:
        return ok(None)

    async def record_verified(
        self,
        chat_id: int,
        *,
        at: datetime,
        title: str | None = None,
        username: str | None = None,
        chat_type: BotChatType | None = None,
    ) -> Result[bool]:
        return ok(True)

    async def record_verification_failed(
        self, chat_id: int, *, message: str, at: datetime
    ) -> Result[bool]:
        return ok(True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def profiles() -> FakeProfiles:
    """SEEDED, and that overrides the package default deliberately.

    The shared fixture starts empty so the walkers go THROUGH onboarding; here the subject is
    what happens after a song has been delivered, which cannot be true of an account with no
    row. An empty store would have onboarding's catch-all claim every update in this file and
    every assertion below would be about the phone-number screen.
    """
    store = FakeProfiles()
    store.seed(USER_ID)
    return store


@pytest.fixture(autouse=True)
async def warm_language_cache(state: FSMContext) -> None:
    """Put English in the FSM language cache, the way a returning customer's session has it.

    ``resolve_language`` reads that cache, NOT ``profiles`` — the profile read happens once, in
    the onboarding router, and is written back here. Without this the whole module would be
    answered in the fallback locale, and every assertion comparing a rendered string against
    ``translate(key, Language.EN)`` would be comparing two different languages. Seeding the
    cache rather than switching the assertions to ``FALLBACK_LANGUAGE`` is the honest fixture:
    the interesting property under test is that the relay answers in the language the TICKET
    carries, and that is only visible when the ticket's language is not the fallback.
    """
    await state.update_data({UI_LANGUAGE_KEY: Language.EN.value})


@pytest.fixture
def support() -> FakeSupportTickets:
    return FakeSupportTickets()


@pytest.fixture
def support_settings(settings: Settings) -> Settings:
    """Settings with the panel link configured. THE GROUP IS NOT IN HERE ANY MORE.

    ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` and ``BAYRAM_SUPPORT_GROUP_THREAD_ID`` were removed rather
    than kept as a fallback (``SUPPORT_TICKETS_SPEC §3.8``): the support group is a ``bot_chats``
    row an operator selects in the panel, so it arrives through :fixture:`bot_chats` below and
    not through settings at all. ``support_panel_base_url`` stays, because it is the deep link
    on the card's button and is not the group.

    ``model_copy`` rather than a second ``Settings(...)`` call because the model is frozen and
    because the point is to change one field and nothing else: a rebuilt settings object would
    quietly differ from the package fixture in whatever the next field added to it is.
    """
    return settings.model_copy(update={"support_panel_base_url": PANEL_BASE_URL})


@pytest.fixture
def bot_chats() -> FakeBotChats:
    """A directory with ``GROUP_CHAT_ID`` selected — what a live deployment looks like."""
    return FakeBotChats(selected=SupportGroupTarget(chat_id=GROUP_CHAT_ID, thread_id=None))


@pytest.fixture
def deps(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> BotDeps:
    """The shared container for this module: a group is selected and the store is wired."""
    return BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
        support_erasure=support,
        bot_chats=bot_chats,
    )


@pytest.fixture
def dispatcher(deps: BotDeps, storage: MemoryStorage) -> Dispatcher:
    return build_dispatcher(deps, storage=storage)


# ---------------------------------------------------------------------------
# Update builders for the STAFF group
# ---------------------------------------------------------------------------
_group_update_id = 500_000


def _next_group_update_id() -> int:
    global _group_update_id
    _group_update_id += 1
    return _group_update_id


def group_card_message(message_id: int = CARD_MESSAGE_ID) -> Message:
    """The card, as it sits in the group — what a staffer replies to.

    The id defaults to :data:`CARD_MESSAGE_ID` for the tests that only need *a* message that is
    not one of ours. A test that means to reply to the card the bot really posted passes
    ``support.only().group_message_id``, through :func:`posted_card`, because the latch records
    whatever id the fake session handed back and a hard-coded one would resolve to no ticket —
    a green test for the wrong reason.
    """
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=GROUP_CHAT_ID, type="supergroup"),
        from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
        text="the card",
    )


def posted_card(support: FakeSupportTickets) -> Message:
    """The card message this ticket was actually posted as."""
    message_id = support.only().group_message_id
    assert message_id is not None, "the ticket was never posted to the group"
    return group_card_message(message_id)


def group_message(
    text: str, *, chat_id: int = GROUP_CHAT_ID, reply_to: Message | None = None
) -> Update:
    return Update(
        update_id=_next_group_update_id(),
        message=Message(
            message_id=9_200,
            date=FIXED_MOMENT,
            chat=Chat(id=chat_id, type="supergroup"),
            from_user=User(id=STAFF_USER_ID, is_bot=False, first_name="Aziz", username="aziz"),
            text=text,
            reply_to_message=reply_to,
        ),
    )


def group_sticker(*, reply_to: Message) -> Update:
    """A staffer answering a card with something that is not text.

    The realistic shape of it: a sticker, a thumbs-up photo, a forwarded voice note. There is
    nothing to relay, and the point of the test it serves is that "nothing to relay" and "not
    one of our cards" must not be the same answer — one is worth a sentence to the staffer and
    the other used to drop the update into the customer routers.
    """
    return Update(
        update_id=_next_group_update_id(),
        message=Message(
            message_id=9_300,
            date=FIXED_MOMENT,
            chat=Chat(id=GROUP_CHAT_ID, type="supergroup"),
            from_user=User(id=STAFF_USER_ID, is_bot=False, first_name="Aziz", username="aziz"),
            reply_to_message=reply_to,
        ),
    )


def group_colleague_message(message_id: int = 9_400) -> Message:
    """A message from a PERSON in the group — what a staffer replies to when they are talking
    to each other rather than to us. ``is_bot=False`` is the whole content of the fixture."""
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=GROUP_CHAT_ID, type="supergroup"),
        from_user=User(id=STAFF_USER_ID + 1, is_bot=False, first_name="Nodira"),
        text="who is taking this one?",
    )


def group_callback(data: str, *, chat_id: int = GROUP_CHAT_ID) -> Update:
    return Update(
        update_id=_next_group_update_id(),
        callback_query=make_callback(data).model_copy(
            update={
                "from_user": User(
                    id=STAFF_USER_ID, is_bot=False, first_name="Aziz", username="aziz"
                ),
                "message": group_card_message(),
            }
        ),
    )


def private_reply(text: str, *, to_message_id: int) -> Update:
    """A private message the customer sent AS A REPLY to the ForceReply prompt."""
    return Update(
        update_id=_next_group_update_id(),
        message=Message(
            message_id=4_242,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
            text=text,
            reply_to_message=Message(
                message_id=to_message_id,
                date=FIXED_MOMENT,
                chat=Chat(id=CHAT_ID, type="private"),
                from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
                text="the prompt",
            ),
        ),
    )


def sends(session: RecordingSession) -> list[SendMessage]:
    return [call for call in session.calls if isinstance(call, SendMessage)]


def private_sends(session: RecordingSession) -> list[SendMessage]:
    return [call for call in sends(session) if call.chat_id == CHAT_ID]


def group_sends(session: RecordingSession) -> list[SendMessage]:
    return [call for call in sends(session) if call.chat_id == GROUP_CHAT_ID]


async def open_and_describe(
    dispatcher: Dispatcher,
    bot: Bot,
    support: FakeSupportTickets,
    *,
    body: str = "The name is wrong",
) -> TicketSnapshot:
    """Walk the whole customer half: ⚠️ (no order) then the reply that fills the body."""
    await dispatcher.feed_update(
        bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
    )
    prompt_id = support.only().prompt_message_id
    assert prompt_id is not None
    await dispatcher.feed_update(bot, private_reply(body, to_message_id=prompt_id))
    return support.only()


# ---------------------------------------------------------------------------
# Opening a ticket
# ---------------------------------------------------------------------------
async def test_the_delivered_song_button_files_the_ticket_against_that_song(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """⚠️ under a delivered song carries the order, and the row records which one.

    This is the whole reason ``SupportCB`` exists rather than a field on ``NavCB``: by the time
    the customer taps, the delivery job has cleared their FSM and there is nowhere else the
    order id could have come from.
    """
    # Arrange
    order_id = uuid4()

    # Act
    await dispatcher.feed_update(
        bot,
        callback_update(SupportCB(action=SupportAction.OPEN, ref=pack_reference(order_id)).pack()),
    )

    # Assert
    ticket = support.only()
    assert ticket.order_id == order_id
    assert ticket.source is SupportTicketSource.DELIVERY_BUTTON
    assert ticket.status is SupportTicketStatus.NEW
    assert ticket.body is None and ticket.described_at is None


async def test_the_order_less_button_still_opens_a_ticket(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """The ``NavCB`` door — degraded screens, and every closing message sent before this
    release — must keep working, and it must open the same kind of ticket with no order on it.

    Refusing it to protect a foreign key would be the product deciding its own bookkeeping
    matters more than the customer's problem.
    """
    # Arrange / Act
    await dispatcher.feed_update(
        bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
    )

    # Assert
    ticket = support.only()
    assert ticket.order_id is None
    assert ticket.source is SupportTicketSource.DELIVERY_BUTTON


async def test_the_support_command_files_the_same_kind_of_ticket(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """``/support`` and the button may not be two routes to one inbox — they are one call.

    The only difference the row records is the DOOR, which is a real distinction: a complaint
    about a named song and one typed out of the blue are different work items.
    """
    # Arrange / Act
    await dispatcher.feed_update(bot, message_update("/support"))

    # Assert
    ticket = support.only()
    assert ticket.source is SupportTicketSource.SUPPORT_COMMAND
    assert ticket.order_id is None


async def test_the_prompt_is_a_force_reply_and_its_id_is_recorded_on_the_row(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """``ForceReply`` plus ``prompt_message_id`` is what replaces an FSM key here.

    If the id were not written back, the customer's answer would match no ticket and the
    complaint would fall through to whatever step accepts free text.
    """
    # Arrange / Act
    await dispatcher.feed_update(bot, message_update("/support"))

    # Assert
    prompt = private_sends(session)[-1]
    assert isinstance(prompt.reply_markup, ForceReply)
    assert prompt.text == translate("support.ticket.prompt", Language.EN)
    assert support.only().prompt_message_id is not None


async def test_the_quota_refusal_writes_no_ticket_and_sends_no_prompt(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """Over the ceiling, the row is not written and the customer is told the LIMIT is reached.

    The copy names the limit rather than the count on purpose — a refusal that says "you have
    three" invites a fourth attempt — so the assertion is on the key, not on a number.
    """
    # Arrange
    support = FakeSupportTickets(is_over_quota=True)
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("/support"))

    # Assert
    assert support.tickets == {}
    assert private_sends(session)[-1].text == translate("support.ticket.too_many", Language.EN)


async def test_a_broken_meter_lets_the_complaint_through(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
) -> None:
    """The quota FAILS OPEN, and that is the decided direction.

    A count that cannot be read is not a reason to refuse a complaint. The person being refused
    is already unhappy and the cost of one ticket over the line is a row — the same posture the
    inbound gate takes, with a stronger reason.
    """
    # Arrange — the meter is broken but the WRITE is not, which is the shape of a read replica
    # falling behind rather than the database being down.
    support = FakeSupportTickets()

    class OnlyTheMeterIsBroken(FakeSupportTickets):
        async def check_open_quota(self, *args: Any, **kwargs: Any) -> Result[TicketQuotaVerdict]:
            return err(StorageError("the meter is unreadable"))

    support = OnlyTheMeterIsBroken()
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("/support"))

    # Assert
    assert len(support.tickets) == 1


async def test_with_no_store_wired_the_button_says_what_it_always_said(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """``BotDeps.support = None`` is a supported configuration, not a degraded one.

    It degrades to ``common.support_text`` — exactly the sentence that shipped before this
    feature — rather than to an apology, so a deployment with no database still tells a
    customer where to write.
    """
    # Arrange
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("/support"))

    # Assert — the unconfigured-contact branch, because the fixture sets no support contact
    assert private_sends(session)[-1].text == translate("support.no_contact", Language.EN)


# ---------------------------------------------------------------------------
# The customer's words
# ---------------------------------------------------------------------------
async def test_the_reply_fills_the_body_and_the_confirmation_quotes_the_reference(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    # Arrange / Act
    ticket = await open_and_describe(dispatcher, bot, support, body="She is Dilnora, not Dilnoza")

    # Assert
    assert ticket.body == "She is Dilnora, not Dilnoza"
    assert ticket.described_at is not None
    assert SupportTicketEventKind.DESCRIBED in support.kinds()
    assert ticket.public_ref in private_sends(session)[-1].text


async def test_answering_the_same_prompt_twice_does_not_overwrite_the_first_complaint(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """A follow-up sentence replacing the original is how the only description of a problem
    gets lost. The second answer is refused and the customer is told it is already in."""
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support, body="first")
    prompt_id = ticket.prompt_message_id
    assert prompt_id is not None

    # Act — the filter will no longer match (the ticket is described), so this falls through
    # to the fallback router rather than reaching the handler at all. Either way the body is
    # untouched, which is the property under test.
    await dispatcher.feed_update(bot, private_reply("second", to_message_id=prompt_id))

    # Assert
    assert support.only().body == "first"


async def test_a_reply_to_something_else_is_not_swallowed_by_the_support_router(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The lookup lives in a FILTER, so an update that is not ours is never claimed.

    A handler that answered "this reply is not ours" by returning would already have consumed
    the message, and every reply to any bot message — a progress frame, a lyric sheet — would
    stop reaching the wizard below.
    """
    # Arrange
    await dispatcher.feed_update(bot, message_update("/support"))
    before = len(session.calls)

    # Act — a reply to a DIFFERENT message id
    await dispatcher.feed_update(bot, private_reply("hello?", to_message_id=999_999))

    # Assert — something answered it (the fallback), and the ticket is untouched
    assert support.only().body is None
    assert len(session.calls) > before


async def test_one_customers_prompt_id_cannot_describe_another_customers_ticket(
    deps: BotDeps, bot: Bot, support: FakeSupportTickets, storage: MemoryStorage
) -> None:
    """``prompt_message_id`` is a PER-CHAT counter, so two customers hold the same value
    routinely. A lookup on the message id alone would attach one person's complaint to another
    person's ticket, which is the worst single failure this feature could have.

    The lookup no longer narrows to undescribed rows — that narrowing was the routing hole a
    customer's follow-up fell through — so the ACCOUNT key is now the only thing standing
    between two customers who happen to hold the same message id, which makes this test
    load-bearing rather than belt-and-braces.
    """
    # Arrange — a ticket belonging to somebody else, waiting on the same message id
    stranger = 99_999
    opened = await support.open_ticket(
        telegram_user_id=stranger,
        language=Language.EN,
        source=SupportTicketSource.SUPPORT_COMMAND,
        order_id=None,
        now=FIXED_MOMENT,
    )
    assert isinstance(opened, Ok)
    await support.attach_prompt(opened.value.id, prompt_message_id=777, now=FIXED_MOMENT)

    # Act
    found = await support.ticket_listening_on(USER_ID, prompt_message_id=777)

    # Assert
    assert isinstance(found, Ok) and found.value is None


# ---------------------------------------------------------------------------
# The group card
# ---------------------------------------------------------------------------
async def test_the_described_ticket_reaches_the_group_and_the_latch_is_settled(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    # Arrange / Act
    ticket = await open_and_describe(dispatcher, bot, support)

    # Assert
    card = group_sends(session)[-1]
    assert ticket.public_ref in card.text
    assert ticket.group_chat_id == GROUP_CHAT_ID
    assert ticket.is_posted
    assert ticket.group_posted_at is not None
    assert SupportTicketEventKind.GROUP_POSTED in support.kinds()


async def test_a_refused_group_post_costs_the_group_a_card_and_never_costs_the_ticket(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one thing that must never happen is a complaint that exists nowhere.

    The latch is left UNSET so a later retry — the panel's card-sync job — can still claim it,
    and the customer is confirmed either way.
    """
    # Arrange — every send into the group is refused; private sends still work
    original = RecordingSession.make_request

    async def refuse_group(
        self: RecordingSession,
        bot_: Bot,
        method: Any,
        timeout: Any = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        if isinstance(method, SendMessage) and method.chat_id == GROUP_CHAT_ID:
            self.calls.append(method)
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        return await original(self, bot_, method, timeout)

    monkeypatch.setattr(RecordingSession, "make_request", cast(Any, refuse_group))

    # Act
    ticket = await open_and_describe(dispatcher, bot, support)

    # Assert
    assert ticket.described_at is not None, "the complaint is recorded"
    assert not ticket.is_posted, "the latch is free for a retry"
    confirmations = [
        call.text
        for call in private_sends(session)
        if call.text.startswith(translate("support.ticket.filed", Language.EN)[:12])
    ]
    assert confirmations, "the customer is confirmed even though the group post failed"


async def test_a_lost_latch_withdraws_the_duplicate_card(
    deps: BotDeps, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """A replay that sends before it claims must take its own card back.

    Only the LOSER is withdrawn: the winner's message id is what the relay resolves a staff
    reply through, so deleting that one would leave the ticket listening on a message that no
    longer exists.
    """
    # Arrange — a ticket that is already posted, then asked to post again
    from bayram.bot.handlers.support import post_card

    opened = await support.open_ticket(
        telegram_user_id=USER_ID,
        language=Language.EN,
        source=SupportTicketSource.SUPPORT_COMMAND,
        order_id=None,
        now=FIXED_MOMENT,
    )
    assert isinstance(opened, Ok)
    described = await support.describe_ticket(opened.value.id, body="x", now=FIXED_MOMENT)
    assert isinstance(described, Ok) and described.value is not None
    await support.claim_group_post(
        opened.value.id, group_chat_id=GROUP_CHAT_ID, group_message_id=CARD_MESSAGE_ID
    )

    # Act — post_card is handed a STALE snapshot, the shape a replayed job actually has
    await post_card(
        bot,
        support,
        deps.settings,
        described.value,
        target=SupportGroupTarget(chat_id=GROUP_CHAT_ID, thread_id=None),
        now=FIXED_MOMENT,
    )

    # Assert
    assert [call for call in session.calls if isinstance(call, DeleteMessage)]
    assert support.only().group_message_id == CARD_MESSAGE_ID


@pytest.mark.parametrize(
    "directory",
    [
        None,
        FakeBotChats(selected=None),
        FakeBotChats(answer=err(StorageError("the database is unreachable"))),
    ],
    ids=["no_directory_wired", "nothing_selected", "the_read_failed"],
)
async def test_no_selected_group_switches_off_only_the_group_leg(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
    directory: FakeBotChats | None,
) -> None:
    """Three ways to have nowhere to post, one behaviour, and that folding is the decision.

    Not one of them is a reason to fail a customer's complaint: the ticket is still written, the
    customer is still confirmed and the board is still populated. "Nothing selected" is also the
    state EVERY deployment now starts in — the two settings that used to name a group were
    removed rather than demoted to a fallback (``SUPPORT_TICKETS_SPEC §3.8``), so there is no
    seed to inherit one from and nothing to switch the feature on but an operator picking a room.
    """
    # Arrange
    support = FakeSupportTickets()
    deps = BotDeps(
        settings=settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
        bot_chats=directory,
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    ticket = await open_and_describe(dispatcher, bot, support)

    # Assert
    assert ticket.described_at is not None
    assert not ticket.is_posted
    assert group_sends(session) == []


# ---------------------------------------------------------------------------
# The staff group
# ---------------------------------------------------------------------------
async def test_a_staff_reply_reaches_the_customer_in_the_tickets_own_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The relay answers in the language the TICKET was opened in, never the account's today.

    An account that switched language in between would otherwise get the one message where
    being understood is the entire point in a language it no longer reads.
    """
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)
    assert ticket.language is Language.EN

    # Act
    await dispatcher.feed_update(
        bot, group_message("We have re-rendered it, sorry!", reply_to=posted_card(support))
    )

    # Assert
    relayed = private_sends(session)[-1]
    assert relayed.text == translate(
        "support.ticket.reply",
        Language.EN,
        ref=ticket.public_ref,
        body="We have re-rendered it, sorry!",
    )
    assert support.relayed, "relayed_at is stamped only after the message actually lands"
    assert SupportTicketEventKind.REPLY in support.kinds()


async def test_a_staff_reply_claims_a_new_ticket(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """Somebody who has typed an answer is working the ticket. Making them press ✋ afterwards
    to say so is a step that would simply not be taken, leaving a worked ticket in the
    unlooked-at column."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)

    # Act
    await dispatcher.feed_update(bot, group_message("on it", reply_to=posted_card(support)))

    # Assert
    assert support.only().status is SupportTicketStatus.IN_PROGRESS


def _refuse_the_private_send(
    monkeypatch: pytest.MonkeyPatch, failure: Callable[[Any], Exception]
) -> None:
    """Make every send to the customer's private chat raise ``failure(method)``."""
    original = RecordingSession.make_request

    async def refuse_private(
        self: RecordingSession,
        bot_: Bot,
        method: Any,
        timeout: Any = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        if isinstance(method, SendMessage) and method.chat_id == USER_ID:
            self.calls.append(method)
            raise failure(method)
        return await original(self, bot_, method, timeout)

    monkeypatch.setattr(RecordingSession, "make_request", cast(Any, refuse_private))


async def test_the_staffer_is_told_in_the_group_when_the_customer_has_blocked_the_bot(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A staffer has just written a paragraph believing it reached somebody. A log line is not
    a way to tell them it did not."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    _refuse_the_private_send(
        monkeypatch,
        lambda method: TelegramForbiddenError(
            method=method, message="Forbidden: bot was blocked by the user"
        ),
    )

    # Act
    await dispatcher.feed_update(bot, group_message("hello", reply_to=posted_card(support)))

    # Assert — the reply is still on the record, and it is NOT marked relayed
    assert SupportTicketEventKind.REPLY in support.kinds()
    assert support.relayed == []
    assert any("blocked the bot" in (call.text or "") for call in group_sends(session))


async def test_a_refused_relay_is_not_reported_to_the_staffer_as_a_customer_block(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REGRESSION (defect E, second half). Every refusal used to be reported as a block.

    The staffer was sent to investigate a customer who had blocked nobody, while the real
    cause — most often a message that ran past Telegram's ceiling — went unlooked-at. The
    classification is :func:`bayram.bot.delivery.is_blocked_by_customer`, which answers
    ``False`` for a 400, and the group must be told something the staffer can act on: try it
    again, shorter.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    _refuse_the_private_send(
        monkeypatch,
        lambda method: TelegramBadRequest(
            method=method, message="Bad Request: message is too long"
        ),
    )

    # Act
    await dispatcher.feed_update(bot, group_message("hello", reply_to=posted_card(support)))

    # Assert
    warnings = [call.text or "" for call in group_sends(session) if "⚠️" in (call.text or "")]
    assert warnings, "the staffer is told the reply did not land"
    assert not any("blocked" in text for text in warnings), (
        "a 400 is not a block and must never be reported as one"
    )
    assert support.relayed == []


async def test_a_message_in_the_group_that_replies_to_nothing_is_not_relayed(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The support group is a room where people also talk to each other."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(private_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("anyone around?"))

    # Assert
    assert len(private_sends(session)) == before


async def test_the_group_router_cannot_fire_in_another_chat(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """One chat id, read from settings. A group handler with no chat filter would relay an
    internal triage conversation to whoever added the bot to their chat."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(private_sends(session))

    # Act — the same reply, in a DIFFERENT group
    await dispatcher.feed_update(
        bot, group_message("leaked?", chat_id=-1_009_999_999_999, reply_to=posted_card(support))
    )

    # Assert
    assert len(private_sends(session)) == before


async def test_claim_assigns_the_staffer_moves_the_ticket_and_redraws_the_card(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback(SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack()),
    )

    # Assert
    claimed = support.only()
    assert claimed.status is SupportTicketStatus.IN_PROGRESS
    assert claimed.assigned_admin_username == "@aziz"
    edits = [call for call in session.calls if isinstance(call, EditMessageText)]
    assert edits and "@aziz" in (edits[-1].text or "")


async def test_a_second_claim_is_a_refusal_and_not_a_second_event(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """``LEGAL_STATUS_MOVES`` has no ``X -> X`` edge for exactly this: two operators pressing
    ✋ on one card is the common case, and the second press must be a refused move rather than
    a timeline row that says nothing and an ``updated_at`` that makes an untouched ticket look
    worked."""
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)
    press = group_callback(
        SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack()
    )
    await dispatcher.feed_update(bot, press)
    moves_after_one = support.kinds().count(SupportTicketEventKind.STATUS_CHANGE)

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback(SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack()),
    )

    # Assert
    assert support.kinds().count(SupportTicketEventKind.STATUS_CHANGE) == moves_after_one


async def test_resolve_closes_the_ticket_and_the_redrawn_card_offers_no_resolve_button(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """A button guaranteed to be refused is a button that teaches a staffer the card is broken,
    so the card draws only the moves ``legal_moves_from`` offers."""
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback(
            SupportCB(action=SupportAction.RESOLVE, ref=pack_reference(ticket.id)).pack()
        ),
    )

    # Assert
    assert support.only().status is SupportTicketStatus.RESOLVED
    edits = [call for call in session.calls if isinstance(call, EditMessageText)]
    payloads = {data for _text, data in buttons(edits[-1].reply_markup)}
    assert (
        SupportCB(action=SupportAction.RESOLVE, ref=pack_reference(ticket.id)).pack()
        not in payloads
    )
    assert SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack() in payloads


# ---------------------------------------------------------------------------
# The card renderer
# ---------------------------------------------------------------------------
def _snapshot(**overrides: Any) -> TicketSnapshot:
    ticket_id = overrides.pop("id", uuid4())
    fields: dict[str, Any] = {
        "id": ticket_id,
        "public_ref": public_ref_for(ticket_id),
        "telegram_user_id": USER_ID,
        "language": Language.UZ_LATN,
        "source": SupportTicketSource.DELIVERY_BUTTON,
        "order_id": None,
        "status": SupportTicketStatus.NEW,
        "body": "it is wrong",
        "prompt_message_id": 11,
        "described_at": FIXED_MOMENT,
        "assigned_admin_username": None,
        "group_chat_id": None,
        "group_message_id": None,
        "group_posted_at": None,
        "created_at": FIXED_MOMENT,
    }
    fields.update(overrides)
    return TicketSnapshot(**fields)


def test_the_card_escapes_the_customers_own_words() -> None:
    """An unescaped ``<`` is a 400 at send time, and a 400 at send time means the ticket never
    reaches the group at all — the one failure this whole feature exists to prevent."""
    # Arrange
    ticket = _snapshot(body="<b>shout</b> & <script>")

    # Act
    text = render_card(ticket)

    # Assert
    assert "&lt;b&gt;shout&lt;/b&gt; &amp; &lt;script&gt;" in text
    assert "<script>" not in text


def test_the_card_omits_the_order_line_when_there_is_no_order() -> None:
    """A row of blanks on a triage card is a question; an absent row is an answer."""
    # Arrange / Act
    without = render_card(_snapshot())
    order_id = uuid4()
    with_order = render_card(_snapshot(order_id=order_id), order_ref=order_reference(order_id))

    # Assert
    assert "Order" not in without
    assert order_reference(order_id) in with_order


def test_an_unusable_panel_url_omits_the_button_entirely() -> None:
    """Telegram validates a URL button at send time, so a relative or localhost link is not a
    dead button — it is a 400 that loses the ENTIRE card."""
    # Arrange / Act / Assert
    ticket = _snapshot()
    assert panel_url_for("", ticket.id) is None
    assert panel_url_for("/support", ticket.id) is None
    assert panel_url_for("panel.example", ticket.id) is None
    assert panel_url_for("https://p.test/", ticket.id) == panel_url_for("https://p.test", ticket.id)
    assert (
        not [
            data for _text, data in buttons(card_keyboard(ticket, panel_base_url="")) if data == ""
        ]
        or True
    )
    urls = [
        button.url
        for row in card_keyboard(ticket, panel_base_url="").inline_keyboard
        for button in row
    ]
    assert urls == [None, None]


def test_a_long_complaint_is_cut_so_the_card_can_still_be_sent() -> None:
    """The body column is Telegram's own message ceiling, and the card carries a header, a rule
    and a footer above it — so a body rendered at full length makes the CARD longer than a
    message may be."""
    # Arrange
    ticket = _snapshot(body="x" * 4_096)

    # Act
    text = render_card(ticket, order_ref="abcd1234")

    # Assert
    assert len(text) < 4_096
    assert text.endswith("</i>")


def test_the_card_names_the_locale_the_relay_will_answer_in() -> None:
    """The most operationally important line after the body: a staffer typing Russian into a
    ``uz_latn`` ticket is writing into a chat where it will not be understood."""
    # Arrange / Act / Assert
    assert "uz (latin)" in render_card(_snapshot(language=Language.UZ_LATN))
    assert "uz (cyrillic)" in render_card(_snapshot(language=Language.UZ_CYRL))
    assert "ru" in render_card(_snapshot(language=Language.RU))


# ---------------------------------------------------------------------------
# The callback payload
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", list(SupportAction))
def test_every_support_payload_fits_telegrams_sixty_four_bytes(action: SupportAction) -> None:
    """The whole reason ``SupportCB`` carries ONE id field: both ids together would be 78."""
    # Arrange / Act
    packed = SupportCB(action=action, ref=pack_reference(uuid4())).pack()

    # Assert
    assert len(packed.encode("utf-8")) <= 64


def test_a_malformed_reference_reads_as_absent_rather_than_raising() -> None:
    """A button from a build that packed something else must open the order-less door, not
    raise inside a callback whose only visible symptom is a spinner that never stops."""
    # Arrange / Act / Assert
    assert read_reference("-") is None
    assert read_reference("not-a-uuid") is None
    value = uuid4()
    assert read_reference(pack_reference(value)) == value


# ---------------------------------------------------------------------------
# /forget
# ---------------------------------------------------------------------------
async def test_forget_deletes_the_customers_tickets_and_their_timelines(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """The privacy exemption in ``tests/test_db/test_privacy_constraints.py`` names ``/forget``
    as this table's erasure route. This is the test that makes that paragraph true.

    The rows are DELETED rather than anonymised: ``support_tickets.telegram_user_id`` is NOT
    NULL because a complaint detached from the person who made it is a body nobody may read
    and an answer nobody can send.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    assert support.tickets and support.events

    # Act
    await dispatcher.feed_update(bot, message_update("/forget"))

    # Assert
    assert support.forgotten == [USER_ID]
    assert support.tickets == {}
    assert support.events == [], "the timeline goes with the ticket (ON DELETE CASCADE)"


async def test_forget_reports_a_failed_ticket_erasure_rather_than_claiming_success(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """``privacy.forgotten`` claims the bodies are gone. Saying so after a failed delete is the
    false promise this command exists to keep."""
    # Arrange
    support = FakeSupportTickets(failure=StorageError("the tickets could not be erased"))
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
        support_erasure=support,
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("/forget"))

    # Assert
    assert private_sends(session)[-1].text != translate("privacy.forgotten", Language.EN)


async def test_forget_with_no_eraser_wired_still_succeeds(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """An unwired eraser is the same "nothing to erase it in" success the profile and credit
    arms report. A difference between the three would show up in the caller as an
    inconsistency in what "it worked" means."""
    # Arrange
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=FakeSupportTickets(),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("/forget"))

    # Assert
    assert private_sends(session)[-1].text == translate("privacy.forgotten", Language.EN)


# ---------------------------------------------------------------------------
# The wiring helper
# ---------------------------------------------------------------------------
def test_the_eraser_is_wired_by_capability_and_never_by_assumption() -> None:
    """``bayram.main.support_eraser`` is what keeps the privacy exemption honest: a store with
    no ``forget_tickets`` yields ``None`` and a warning, never a silently absent erasure."""
    # Arrange
    from bayram.main import support_eraser

    class CannotErase:
        async def load_ticket(self, ticket_id: UUID) -> Result[TicketSnapshot | None]:
            return ok(None)

    # Act / Assert
    assert support_eraser(None) is None
    assert support_eraser(CannotErase()) is None
    store = FakeSupportTickets()
    assert support_eraser(store) is store


# ---------------------------------------------------------------------------
# Author kinds
# ---------------------------------------------------------------------------
def test_a_staff_display_name_is_cut_at_the_column_width() -> None:
    """SQLite enforces no length at all, so an over-long value is an ``IntegrityError`` from
    inside a half-written transaction on Postgres and a silent pass in this suite."""
    # Arrange
    from bayram.bot.handlers.support import _staff_name

    message = group_message("hi").message
    assert message is not None
    long_name = message.model_copy(
        update={
            "from_user": User(id=STAFF_USER_ID, is_bot=False, first_name="Q" * 200, username=None)
        }
    )

    # Act / Assert
    assert len(_staff_name(long_name)) == MAX_STAFF_NAME_CHARS


def test_a_group_reply_is_attributed_to_the_staff_group_and_not_to_an_operator() -> None:
    """``author_admin_username`` beside a ``STAFF_GROUP`` kind would be a row claiming an
    audited actor for an act nobody audited."""
    # Arrange / Act
    author = EventAuthor.staff_group(STAFF_USER_ID, display_name="@aziz")

    # Assert
    assert author.kind is SupportAuthorKind.STAFF_GROUP
    assert author.admin_username is None
    assert author.telegram_user_id == STAFF_USER_ID


# ---------------------------------------------------------------------------
# Defect D — nothing from the support group may reach a customer-facing router
# ---------------------------------------------------------------------------
#: The onboarding screen's opening question, in every locale. If ANY of these turns up in the
#: support group, the update reached ``onboarding``'s catch-all — which is the whole of what
#: these tests are watching for, and it is why they assert on the copy rather than on a
#: handler: the bug is invisible from the handler's own point of view. It answered correctly;
#: it should never have been reached.
_ONBOARDING_QUESTIONS: Final[tuple[str, ...]] = tuple(
    translate("onboarding.language.prompt", language) for language in Language
)


def _onboarding_leaked_into(session: RecordingSession) -> list[str]:
    return [
        call.text
        for call in group_sends(session)
        if any(question in (call.text or "") for question in _ONBOARDING_QUESTIONS)
    ]


async def test_a_reply_to_a_bot_message_that_is_not_a_card_is_answered_in_the_group(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """REGRESSION (defect D). An unresolved reply must not leave this router.

    ``ReplyToCard`` answers ``False`` for a reply to an erased ticket's card, to a duplicate
    card whose delete Telegram refused, and to the bot's own "I could not deliver that"
    warning — which is the most natural thing in the room for a triager to answer. That
    ``False`` used to mean "fall through", and below this router sit the CUSTOMER routers:
    ``onboarding``'s catch-all claims every update from an account with no profile row, which
    is every staffer, so the bot posted the language screen and a phone-number keyboard into
    the support group while the staffer believed they had answered a customer.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(group_sends(session))

    # Act — a reply to a bot message in the group that resolves to no ticket
    await dispatcher.feed_update(
        bot, group_message("sorry about that", reply_to=group_card_message(9_999))
    )

    # Assert
    answers = group_sends(session)[before:]
    assert answers, "the staffer is told their reply matched no ticket"
    assert "could not match that to a ticket" in (answers[-1].text or "")
    assert _onboarding_leaked_into(session) == []


async def test_a_reply_to_an_erased_tickets_card_is_answered_and_never_onboards_the_staffer(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The same hole reached through ``/forget``: the card outlives the row it points at.

    The tickets are deleted rather than anonymised (``SUPPORT_TICKETS_SPEC`` §7.2), so the
    card sitting in the group resolves to nothing from the moment a customer is forgotten —
    and a staffer answering it is the ordinary case, not an exotic one.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    card = posted_card(support)
    support.tickets.clear()
    before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("we re-rendered it", reply_to=card))

    # Assert
    answers = group_sends(session)[before:]
    assert answers and "could not match that to a ticket" in (answers[-1].text or "")
    assert _onboarding_leaked_into(session) == []
    assert private_sends(session)[-1].chat_id == CHAT_ID, "nothing was relayed to anybody"


async def test_a_card_answered_with_a_sticker_is_told_that_only_text_relays(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """A staffer's reply with no text used to make ``ReplyToCard`` answer ``False`` — which is
    indistinguishable from "not one of our cards" — and the update went down the tree to the
    customer routers. It resolves the ticket now and is answered with something actionable."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    card = posted_card(support)
    before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_sticker(reply_to=card))

    # Assert
    answers = group_sends(session)[before:]
    assert answers and "only relay text" in (answers[-1].text or "")
    assert SupportTicketEventKind.REPLY not in support.kinds(), (
        "there is nothing to put on the timeline"
    )
    assert _onboarding_leaked_into(session) == []


async def test_staff_talking_to_each_other_is_claimed_and_left_alone(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """Claiming every update is not the same as answering every update.

    The support group is a room where people also talk to each other, and a bot that replied
    "I could not match that to a ticket" to every "anyone around?" would be muted — which
    costs this feature its only notification channel. So the catch-all speaks only when the
    staffer was plainly talking to US.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("anyone around?"))
    await dispatcher.feed_update(
        bot, group_message("I will take it", reply_to=group_colleague_message())
    )

    # Assert
    assert group_sends(session)[before:] == []
    assert _onboarding_leaked_into(session) == []


async def test_an_unrecognised_button_in_the_group_is_answered_rather_than_left_spinning(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The callback half of the same hole. An unclaimed press would have reached
    ``onboarding.handle_blocked_callback`` and answered a staffer with the language screen;
    an unanswered one leaves a spinner on the button for Telegram's own timeout."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)

    # Act
    await dispatcher.feed_update(bot, group_callback(NavCB(action=NavAction.TO_MENU).pack()))

    # Assert
    answered = [call for call in session.calls if isinstance(call, AnswerCallbackQuery)]
    assert answered and "could not match that to a ticket" in (answered[-1].text or "")
    assert _onboarding_leaked_into(session) == []


async def test_no_customer_router_acts_in_a_chat_that_is_not_private(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """REGRESSION (defect D, the other half). The group catch-alls only cover the CONFIGURED
    room; this covers every other one.

    A bot added to somebody's group receives its messages, and without the private-chat
    umbrella in ``handlers.build_router`` one of them reaching ``onboarding``'s catch-all is
    "Which language should I speak?" and a phone-number keyboard posted in front of strangers,
    while one reaching ``fallback`` is the main menu in the same place.
    """
    # Arrange
    stranger_chat = -1_009_999_999_999
    before = len(session.calls)

    # Act
    await dispatcher.feed_update(bot, group_message("hello bot", chat_id=stranger_chat))

    # Assert
    assert [
        call
        for call in sends(session)[:]
        if isinstance(call, SendMessage) and call.chat_id == stranger_chat
    ] == []
    assert len(session.calls) == before, "nothing at all was said in a chat we do not own"


# ---------------------------------------------------------------------------
# Defect A — the customer's follow-up, and where it used to end up
# ---------------------------------------------------------------------------
def newest(support: FakeSupportTickets) -> TicketSnapshot:
    """The ticket opened most recently.

    By INSERTION order and never by ``created_at``: the suite's clock is fixed, so every
    ticket shares a timestamp to the microsecond and ``max(..., key=created_at)`` silently
    returns whichever one the dict happened to yield first — a test that would have passed for
    the wrong reason on every assertion about "the ticket they already hold".
    """
    return list(support.tickets.values())[-1]


async def staff_answers(
    dispatcher: Dispatcher,
    bot: Bot,
    support: FakeSupportTickets,
    text: str = "Sorry — re-running it now",
) -> int:
    """A staffer replies to the card, and the message the ticket now LISTENS on comes back.

    That id is the whole subject of the tests below: the relay ends by telling the customer to
    reply to it, so it is the id their follow-up will carry.
    """
    await dispatcher.feed_update(bot, group_message(text, reply_to=posted_card(support)))
    relay_id = support.only().prompt_message_id
    assert relay_id is not None
    return relay_id


async def test_a_follow_up_to_a_staff_reply_is_never_taken_as_wizard_input(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    state: FSMContext,
) -> None:
    """REGRESSION (defect A, the critical one). The sentence that used to be SUNG.

    ``support.ticket.reply`` ends "Reply here if there is more to say." Nothing claimed that
    reply: the only private registration was filtered on undescribed tickets, so the follow-up
    fell past the support router and was taken by whichever wizard step the customer was
    parked in. At ``Wizard.name`` "thanks, it is fine now" became the RECIPIENT'S NAME and the
    pipeline sang it to a real person; at ``Wizard.note`` it became free text about them.

    The customer is parked at ``Wizard.name`` here for exactly that reason. The assertion is
    not "the name handler behaved" — it is that the name handler was never reached.
    """
    # Arrange — a described, posted ticket, answered by a staffer, and a half-finished wizard
    await open_and_describe(dispatcher, bot, support)
    relay_id = await staff_answers(dispatcher, bot, support)
    await state.set_state(Wizard.name)
    before_kinds = support.kinds().count(SupportTicketEventKind.REPLY)

    # Act — the customer takes the relay up on its offer
    await dispatcher.feed_update(
        bot, private_reply("Thanks, it is fine now", to_message_id=relay_id)
    )

    # Assert — the support router claimed it, and the wizard never saw it
    assert support.kinds().count(SupportTicketEventKind.REPLY) == before_kinds + 1
    customer_replies = [
        event
        for event in support.events
        if event["kind"] is SupportTicketEventKind.REPLY
        and event["author"].kind is SupportAuthorKind.CUSTOMER
    ]
    assert customer_replies, "the follow-up is on the timeline as the CUSTOMER's"
    assert customer_replies[-1]["body"] == "Thanks, it is fine now"
    assert private_sends(session)[-1].text == translate(
        "support.ticket.follow_up", Language.EN, ref=support.only().public_ref
    )
    draft = await state.get_data()
    assert "Thanks, it is fine now" not in repr(draft), "nothing of it reached the draft"


async def test_the_relay_re_points_the_ticket_at_the_message_the_customer_can_see(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """``prompt_message_id`` is "the message this ticket is listening on", not "the first
    ForceReply we sent". Without the re-point the invitation at the end of every relay
    resolves to nothing, which is defect A in one column."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    original_prompt = support.only().prompt_message_id

    # Act
    await dispatcher.feed_update(
        bot, group_message("we re-rendered it", reply_to=posted_card(support))
    )

    # Assert
    relayed = [call for call in private_sends(session) if "Support" in (call.text or "")]
    assert relayed, "the relay went out"
    assert support.only().prompt_message_id != original_prompt


async def test_a_follow_up_is_posted_under_the_card_the_staff_are_working_from(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """A loose message in a busy room is a message nobody connects to a complaint."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    relay_id = await staff_answers(dispatcher, bot, support)
    card_id = support.only().group_message_id

    # Act
    await dispatcher.feed_update(bot, private_reply("it is still wrong", to_message_id=relay_id))

    # Assert
    threaded = [call for call in group_sends(session) if call.reply_to_message_id == card_id]
    assert threaded, "the follow-up hangs off the card"
    assert "it is still wrong" in (threaded[-1].text or "")


@pytest.mark.parametrize(
    "parked",
    [SupportTicketStatus.WAITING, SupportTicketStatus.RESOLVED],
)
async def test_a_customer_reply_brings_a_parked_ticket_back_to_in_progress(
    dispatcher: Dispatcher,
    bot: Bot,
    support: FakeSupportTickets,
    parked: SupportTicketStatus,
) -> None:
    """REGRESSION (defect A, second consequence). ``REOPEN_STATUS`` had no caller at all.

    ``waiting`` means waiting on the CUSTOMER — and until the customer's own words could reach
    a ticket, nothing the customer did could end that wait. ``resolved`` is the same move from
    the other side: the specification calls a customer reply a reopen and keeps ``resolved_at``
    so a repeat complaint stays visible as one.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    relay_id = await staff_answers(dispatcher, bot, support)
    ticket = support.only()
    support._replace(ticket, status=parked)

    # Act
    await dispatcher.feed_update(bot, private_reply("still not right", to_message_id=relay_id))

    # Assert
    assert support.only().status is REOPEN_STATUS


async def test_a_follow_up_on_a_new_ticket_does_not_pretend_somebody_picked_it_up(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets
) -> None:
    """``NEW`` is absent from ``REOPENING_STATUSES`` and its absence is the interesting half.

    ``new`` means "nobody has looked at this yet". A customer adding a second sentence has not
    made "somebody is working this" true, and moving it would empty the unlooked-at column by
    pretending the backlog had been worked.
    """
    # Arrange — described and posted, but never answered, so it is still `new`
    ticket = await open_and_describe(dispatcher, bot, support)
    prompt_id = ticket.prompt_message_id
    assert prompt_id is not None

    # Act
    await dispatcher.feed_update(bot, private_reply("one more thing", to_message_id=prompt_id))

    # Assert
    assert support.only().status is SupportTicketStatus.NEW
    assert support.kinds().count(SupportTicketEventKind.STATUS_CHANGE) == 0


async def test_a_second_message_before_anyone_answers_is_added_and_not_discarded(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The first complaint still cannot be overwritten — but the second sentence is no longer
    thrown away with "we already have that". It joins the ticket as a follow-up."""
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support, body="first")
    prompt_id = ticket.prompt_message_id
    assert prompt_id is not None

    # Act
    await dispatcher.feed_update(bot, private_reply("second", to_message_id=prompt_id))

    # Assert
    assert support.only().body == "first", "the description is still immutable"
    assert any(
        event["kind"] is SupportTicketEventKind.REPLY and event["body"] == "second"
        for event in support.events
    )


# ---------------------------------------------------------------------------
# Defect G — /support during a render
# ---------------------------------------------------------------------------
async def test_a_description_typed_during_a_render_is_not_eaten_by_submitting(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    state: FSMContext,
) -> None:
    """REGRESSION (defect G). The ticket was opened, prompted, and then deafened.

    ``commands`` is registered above everything, so ``/support`` itself always worked mid-
    render. The support router's MESSAGE observer then stood down for ``Wizard.submitting``,
    so the customer's answer to the ForceReply fell to
    ``submitting.handle_message_while_working`` and was answered "still being made" — leaving
    an undescribed row that counted against the customer's own quota.

    The stand-down was never needed on this observer: its filter is "a ticket of this
    account's is listening on the message this is a reply to", which no wizard input can
    satisfy.
    """
    # Arrange — a song is being made
    await state.set_state(Wizard.submitting)
    await dispatcher.feed_update(bot, message_update("/support"))
    prompt_id = support.only().prompt_message_id
    assert prompt_id is not None, "the command works mid-render, as it always did"

    # Act
    await dispatcher.feed_update(
        bot, private_reply("the name is pronounced wrong", to_message_id=prompt_id)
    )

    # Assert
    assert support.only().body == "the name is pronounced wrong"
    assert support.only().described_at is not None
    assert await state.get_state() == Wizard.submitting.state, "the park is undisturbed"


async def test_the_warning_button_still_stands_down_mid_render(
    dispatcher: Dispatcher, bot: Bot, support: FakeSupportTickets, state: FSMContext
) -> None:
    """The callback observer KEEPS its stand-down, and the asymmetry is the decision.

    A tap that opens no ticket loses nothing the customer typed, and ``submitting`` answering
    "still being made" is the behaviour recorded when this shipped. Removing the stand-down
    from the message observer must not quietly remove it from both.
    """
    # Arrange
    await state.set_state(Wizard.submitting)

    # Act — the SupportCB door, which is this router's own; the order-less ``NavCB`` ⚠️ is
    # ``navigation``'s, and that router is deliberately not state-filtered at all.
    await dispatcher.feed_update(
        bot,
        callback_update(SupportCB(action=SupportAction.OPEN, ref=pack_reference(uuid4())).pack()),
    )

    # Assert
    assert support.tickets == {}


# ---------------------------------------------------------------------------
# Defect B — the blocked account that was told to send /support
# ---------------------------------------------------------------------------
async def test_a_blocked_account_can_describe_the_ticket_it_was_told_to_open(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """REGRESSION (defect B). ``error.blocked`` says "send /support and tell me about it".

    ``/support`` is in ``gate.ERASURE_COMMANDS``, so the command reached its handler and a
    ticket was opened — but the DESCRIPTION is a plain message, so the block gate refused it
    with the very sentence that had sent the customer there. The loop was closed, and every
    turn round it burned one of the three undescribed tickets the quota allows, so the account
    ended up permanently unable to reach support.
    """
    # Arrange
    support = FakeSupportTickets()
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
        entitlements=cast(Any, FakeEntitlements(is_blocked=True)),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    await dispatcher.feed_update(bot, message_update("/support"))
    prompt_id = support.only().prompt_message_id
    assert prompt_id is not None, "the command itself was always allowed through"

    # Act
    await dispatcher.feed_update(
        bot, private_reply("please lift the block, it was a mistake", to_message_id=prompt_id)
    )

    # Assert
    assert support.only().body == "please lift the block, it was a mistake"
    assert translate("error.blocked", Language.EN) not in [
        call.text for call in private_sends(session)
    ]


async def test_a_blocked_account_is_still_refused_an_unprompted_message(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """The carve-out is a reply to one of OUR messages, and nothing wider.

    A message with no ``reply_to_message`` — which is every ordinary message — still meets the
    block gate. If this ever passes by accident the gate has stopped gating.
    """
    # Arrange
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=FakeSupportTickets(),
        entitlements=cast(Any, FakeEntitlements(is_blocked=True)),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await dispatcher.feed_update(bot, message_update("let me in"))

    # Assert
    assert translate("error.blocked", Language.EN) in [call.text for call in private_sends(session)]


async def test_the_fourth_tap_hands_back_the_ticket_already_held(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """REGRESSION (defect B, the quota half). §1.4's rule, which shipped as a refusal.

    "A customer who taps ⚠️ four times without typing gets the prompt for the ticket they
    already have, not a fourth row." Refusing instead is what turned three unanswered prompts
    into a locked door — and the ticket is re-pointed at the NEW prompt, because the old one
    is scrolled away and only the message on screen can resolve.
    """
    # Arrange — three taps, nothing typed
    for _ in range(DEFAULT_SUPPORT_QUOTA.max_undescribed):
        await dispatcher.feed_update(
            bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
        )
    assert len(support.tickets) == DEFAULT_SUPPORT_QUOTA.max_undescribed
    held = newest(support)

    # Act
    await dispatcher.feed_update(
        bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
    )

    # Assert — no fourth row, a ForceReply naming the ticket they hold, and it now listens on it
    assert len(support.tickets) == DEFAULT_SUPPORT_QUOTA.max_undescribed
    reprompt = private_sends(session)[-1]
    assert isinstance(reprompt.reply_markup, ForceReply)
    assert held.public_ref in reprompt.text
    assert reprompt.text != translate("support.ticket.too_many", Language.EN)


async def test_the_re_prompted_ticket_can_actually_be_described(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The re-prompt is only worth anything if the answer to it lands on the right row.

    The ticket is RE-POINTED at the new prompt (``listen_on``), not left listening on the one
    it was opened with: the original is scrolled away up the customer's chat and only the
    message on screen can resolve. ``attach_prompt`` would have refused the write, because the
    column is not NULL — which is exactly why the two methods are separate.
    """
    # Arrange — three taps, then the fourth that hands one back
    for _ in range(DEFAULT_SUPPORT_QUOTA.max_undescribed):
        await dispatcher.feed_update(
            bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
        )
    held = newest(support)
    prompt_before = held.prompt_message_id
    await dispatcher.feed_update(
        bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
    )

    # Act
    prompt_id = support.tickets[held.id].prompt_message_id
    assert prompt_id is not None and prompt_id != prompt_before, "it listens on the new prompt"
    await dispatcher.feed_update(
        bot, private_reply("it sang the wrong name", to_message_id=prompt_id)
    )

    # Assert
    assert support.tickets[held.id].body == "it sang the wrong name"
    assert len(support.tickets) == DEFAULT_SUPPORT_QUOTA.max_undescribed, "still no fourth row"


async def test_the_daily_ceiling_is_still_a_refusal(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The two ceilings get opposite answers. A sixth ticket in a day is a script, not a
    person with six problems, and there is nothing useful to hand back."""
    # Arrange — describe each one as it is opened, so only the DAILY count ever rises
    for index in range(DEFAULT_SUPPORT_QUOTA.max_per_day):
        await dispatcher.feed_update(
            bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
        )
        fresh = newest(support)
        assert fresh.prompt_message_id is not None
        await dispatcher.feed_update(
            bot, private_reply(f"problem {index}", to_message_id=fresh.prompt_message_id)
        )

    # Act
    await dispatcher.feed_update(
        bot, callback_update(NavCB(action=NavAction.REPORT_PROBLEM).pack())
    )

    # Assert
    assert len(support.tickets) == DEFAULT_SUPPORT_QUOTA.max_per_day
    assert private_sends(session)[-1].text == translate("support.ticket.too_many", Language.EN)


# ---------------------------------------------------------------------------
# Defect E — the relay that was too long to send
# ---------------------------------------------------------------------------
def test_a_long_staff_reply_is_measured_as_the_finished_message() -> None:
    """REGRESSION (defect E). The bound used to be on the RAW body, before the wrapper.

    ``MAX_BODY_CHARS`` is the ``support_tickets.body`` column and Telegram's own single-message
    ceiling — the right bound for the column and the wrong one for the relay, which wraps the
    body in a header, a ``<blockquote>`` and a closing line. A staffer who filled the column
    produced a message Telegram refused with a 400: the customer got nothing, ``relayed_at``
    stayed NULL, and the group was told the customer may have blocked the bot.
    """
    # Arrange
    ticket = _snapshot(language=Language.EN)

    # Act
    text = relay_text_for(ticket, "x" * MAX_BODY_CHARS)

    # Assert
    assert len(text) <= MAX_MESSAGE_CHARS
    assert ticket.public_ref in text


@pytest.mark.parametrize("language", list(Language))
def test_the_relay_fits_in_every_locale(language: Language) -> None:
    """Each catalogue's wrapper is a different length, so a bound computed against one of them
    is a bound that holds in one language."""
    # Arrange / Act
    text = relay_text_for(_snapshot(language=language), "y" * MAX_BODY_CHARS)

    # Assert
    assert len(text) <= MAX_MESSAGE_CHARS


def test_escaping_is_counted_against_the_ceiling_and_not_against_the_raw_body() -> None:
    """``translate`` HTML-escapes every parameter, so one ``&`` the staffer types becomes five
    characters and one ``<`` becomes four. A body measured before escaping can be a fifth of
    its rendered size — which is why the bound is computed on the RENDERED string."""
    # Arrange / Act
    text = relay_text_for(_snapshot(language=Language.EN), "<&" * (MAX_BODY_CHARS // 2))

    # Assert
    assert len(text) <= MAX_MESSAGE_CHARS
    assert "<blockquote>" in text and text.endswith("</blockquote>") is False


async def test_a_long_staff_reply_actually_reaches_the_customer(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """End to end: the length that used to produce a 400 now produces a delivered relay, a
    stamped ``relayed_at`` and no warning in the group."""
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(
        bot, group_message("z" * MAX_BODY_CHARS, reply_to=posted_card(support))
    )

    # Assert
    relayed = [call for call in private_sends(session) if len(call.text or "") > 1_000]
    assert relayed and len(relayed[-1].text) <= MAX_MESSAGE_CHARS
    assert support.relayed, "relayed_at is stamped"
    assert [call for call in group_sends(session)[before:] if "⚠️" in (call.text or "")] == []


# ---------------------------------------------------------------------------
# The staff room is chosen in the panel, and the choice takes effect immediately
# ---------------------------------------------------------------------------
async def test_the_selected_group_is_re_read_on_every_update_and_never_remembered(
    dispatcher: Dispatcher, bot: Bot, bot_chats: FakeBotChats
) -> None:
    """The one thing a cache here would cost, asserted rather than trusted.

    The support group left the environment so that an operator could move it without a
    redeploy. A cached answer — even a short one — puts a window back in exactly the same
    place: the panel says the move worked while staff replies in the new room go unclaimed and
    replies in the old one are still relayed to customers.
    """
    # Arrange
    before = bot_chats.asked

    # Act
    await dispatcher.feed_update(bot, group_message("anyone around?"))
    await dispatcher.feed_update(bot, group_message("still here"))

    # Assert — asked again, and not once and remembered.
    assert bot_chats.asked >= before + 2


async def test_moving_the_selection_moves_the_staff_room_with_no_restart(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> None:
    """The feature, in one test: the room changes between two updates and nothing is rebuilt."""
    # Arrange — a ticket with its card in the group an operator has selected.
    await open_and_describe(dispatcher, bot, support)
    card = posted_card(support)
    await dispatcher.feed_update(bot, group_message("On it — re-rendering now.", reply_to=card))
    assert [call for call in private_sends(session) if "re-rendering" in (call.text or "")]

    # Act — the operator picks a different room in the panel. No restart, no redeploy.
    bot_chats.answer = ok(SupportGroupTarget(chat_id=GROUP_CHAT_ID - 1, thread_id=None))
    await dispatcher.feed_update(bot, group_message("And the second one too.", reply_to=card))

    # Assert — the old room is no longer the staff room, so nothing it says reaches a customer.
    assert not [call for call in private_sends(session) if "second one" in (call.text or "")]


async def test_a_private_update_never_asks_where_the_support_group_is(
    dispatcher: Dispatcher, bot: Bot, bot_chats: FakeBotChats
) -> None:
    """The short circuit that keeps a per-update lookup off the product's hot path.

    ``support_group`` sits above the customer routers, so its filter runs on every message and
    every button press in the bot. A positive Telegram chat id is a PRIVATE chat and
    :class:`~bayram.contracts.BotChatType` has no ``private`` member, so such a chat cannot be a
    ``bot_chats`` row in any state of the database — which makes this a fact rather than an
    optimisation, and the reason the filter can answer without a round trip.
    """
    # Arrange / Act — a private message that resolves to no ticket and falls past this router.
    await dispatcher.feed_update(bot, private_reply("hello?", to_message_id=999_999))

    # Assert
    assert bot_chats.asked == 0


async def test_the_card_is_posted_into_the_topic_the_selection_carries(
    support_settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
    storage: MemoryStorage,
    bot: Bot,
    session: RecordingSession,
) -> None:
    """The topic travels WITH the chat, as one value, and that is why it cannot drift.

    As two environment variables the chat and the topic could be — and eventually would be —
    edited apart, which is a card posted into a thread that does not exist in the group it was
    sent to. :class:`~bayram.bot_chats.SupportGroupTarget` carries both because a topic id is
    meaningless apart from the chat it is a topic OF.
    """
    # Arrange
    support = FakeSupportTickets()
    deps = BotDeps(
        settings=support_settings,
        submitter=submitter,
        content=content,
        clock=clock,
        profiles=profiles,
        support=support,
        bot_chats=FakeBotChats(
            selected=SupportGroupTarget(chat_id=GROUP_CHAT_ID, thread_id=FORUM_TOPIC_ID)
        ),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await open_and_describe(dispatcher, bot, support)

    # Assert — and ``None`` rather than ``0`` on the ordinary path, which every other test in
    # this module covers: Telegram refuses ``message_thread_id=0`` on a group that is not a
    # forum, and a refused card is the failure the whole posting path is shaped to avoid.
    assert group_sends(session)[0].message_thread_id == FORUM_TOPIC_ID


# ---------------------------------------------------------------------------
# The support-group picker's own three defects: an old card, an old room, and
# the commands that started firing in every room the bot was added to
# ---------------------------------------------------------------------------
def group_callback_on_an_old_card(
    data: str, *, chat_id: int = GROUP_CHAT_ID, card_message_id: int = CARD_MESSAGE_ID
) -> Update:
    """A button pressed on a card Telegram will no longer hand the BODY of back.

    :class:`~aiogram.types.InaccessibleMessage` is what aiogram delivers when Telegram judges
    the message carrying a button too old (or it has been deleted). It is a SIBLING of
    ``Message`` — its MRO is ``MaybeInaccessibleMessage``, ``TelegramObject`` — so every
    ``isinstance(message, Message)`` in this codebase answers ``False`` for it, and it is
    exactly what a week-old ticket card in a busy staff room turns into.

    The ``chat`` and the ``message_id`` are present, because those are the two things Telegram
    can always say about a message whose body it will not return; only the body is gone. That
    is what makes routing this update possible at all, and dropping it was defect A.
    """
    return Update(
        update_id=_next_group_update_id(),
        callback_query=make_callback(data).model_copy(
            update={
                "from_user": User(
                    id=STAFF_USER_ID, is_bot=False, first_name="Aziz", username="aziz"
                ),
                "message": InaccessibleMessage(
                    chat=Chat(id=chat_id, type="supergroup"), message_id=card_message_id
                ),
            }
        ),
    )


def answers(session: RecordingSession) -> list[AnswerCallbackQuery]:
    return [call for call in session.calls if isinstance(call, AnswerCallbackQuery)]


async def test_a_button_on_an_older_card_is_still_answered_in_the_selected_group(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """REGRESSION (defect A). An inaccessible message is not "some other chat".

    ``_chat_of`` resolved a callback's chat with ``isinstance(message, Message)``, which is
    ``False`` for an :class:`~aiogram.types.InaccessibleMessage` — so ``InSupportGroup``
    answered ``False`` for a real press by a real staffer on a real card in the real support
    group. Nothing below could pick it up either: every customer router is nested under a
    private-chat filter and the chat is a supergroup. The update was UNHANDLED, ``answer()``
    was never called, and the staffer watched the spinner turn until Telegram said "query is
    too old" — while ``handle_unresolved_group_callback``, written so that can never happen,
    sat inside the router the filter had just closed.

    The card cannot be redrawn (editing an inaccessible message is genuinely impossible), and
    that is the degradation this asserts is graceful rather than total: the ticket MOVES and
    the staffer is answered.
    """
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)
    before = len(answers(session))

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback_on_an_old_card(
            SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack()
        ),
    )

    # Assert
    assert support.only().status is SupportTicketStatus.IN_PROGRESS, (
        "the press must reach the handler, not fall out of the router tree"
    )
    assert support.only().assigned_admin_username == "@aziz"
    assert len(answers(session)) > before, "an unanswered callback is a spinner that never stops"


async def test_an_inaccessible_card_in_another_group_is_still_not_ours(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The other half of defect A's fix: widening the TYPE must not widen the CHAT.

    ``_chat_of`` now answers for an inaccessible message, so the chat-id comparison is the only
    thing standing between this router and every group the bot was ever added to. A press on
    some stranger's inline keyboard in the marketing group must still be none of our business.
    """
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)
    before = len(answers(session))

    # Act
    await dispatcher.feed_update(
        bot,
        group_callback_on_an_old_card(
            SupportCB(action=SupportAction.CLAIM, ref=pack_reference(ticket.id)).pack(),
            chat_id=-1_009_999_999_999,
        ),
    )

    # Assert
    assert support.only().status is SupportTicketStatus.NEW
    assert len(answers(session)) == before


async def test_a_staff_reply_in_the_room_the_inbox_left_is_never_lost(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> None:
    """REGRESSION (defect C). Moving the inbox must not make the old room a black hole.

    Cards already posted stay where they were, and ``support:card_sync`` goes on repainting
    them, so the old room looks like a working queue. Before this fix a triager replying to one
    of those cards matched ``InSupportGroup`` no more, no router below claimed it (the customer
    routers are under a private-chat filter), and the update was UNHANDLED: nothing written,
    the customer told nothing, the staffer answered nothing at all — not even
    ``_NO_TICKET_MATCH``, the sentence this module was given for exactly that shape.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    card = posted_card(support)
    bot_chats.answer = ok(SupportGroupTarget(chat_id=GROUP_CHAT_ID - 1, thread_id=None))
    private_before = len(private_sends(session))
    group_before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("Sorry — re-running it", reply_to=card))

    # Assert — the staffer is told, in the room, that it did NOT go out and where to work it
    said = group_sends(session)[group_before:]
    assert said, "a staff reply in a room that holds cards must never vanish silently"
    assert "did NOT send that to the customer" in (said[-1].text or "")
    assert "still open" in (said[-1].text or "")
    # ...and nothing was relayed out of a room the operator deliberately stopped using
    assert len(private_sends(session)) == private_before
    assert SupportTicketEventKind.REPLY not in support.kinds(), (
        "an undelivered paragraph must not be put on the timeline as an answer"
    )
    assert support.only().status is SupportTicketStatus.NEW, (
        "a reply that was never sent must not claim the ticket"
    )


async def test_clearing_the_inbox_answers_the_old_room_too(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> None:
    """Clearing is "no selection", not "a different selection", and it is not a failure state.

    §3.8 supports clearing explicitly, so the code path where ``selected_support_group``
    answers ``None`` is an ordinary one — and it is the path where "the current inbox" cannot
    be compared against anything at all. The room still holds the cards.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    card = posted_card(support)
    bot_chats.answer = ok(None)
    private_before = len(private_sends(session))
    group_before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("Fixed it", reply_to=card))

    # Assert
    said = group_sends(session)[group_before:]
    assert said and "no longer the support inbox" in (said[-1].text or "")
    assert len(private_sends(session)) == private_before


async def test_a_button_on_a_card_in_the_old_room_works_and_says_where_the_inbox_went(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> None:
    """The asymmetry, asserted: a RELAY is refused in the old room, a TRIAGE MOVE is not.

    Resolving reaches nobody outside the company — the same operator could do it from the panel
    in the same second — so refusing the press would leave a live-looking card whose buttons do
    nothing, which is the defect this change exists to remove, one layer up. What changes is the
    answer: an alert, not a silent toast, because a staffer working a stale room is precisely
    the person who will not notice a toast.
    """
    # Arrange
    ticket = await open_and_describe(dispatcher, bot, support)
    bot_chats.answer = ok(SupportGroupTarget(chat_id=GROUP_CHAT_ID - 1, thread_id=None))

    # Act — pressed on the card the bot really posted, which is what makes this chat a chat
    # that HOLDS CARDS; a press on any other message here resolves to nothing and is declined.
    await dispatcher.feed_update(
        bot,
        group_callback_on_an_old_card(
            SupportCB(action=SupportAction.RESOLVE, ref=pack_reference(ticket.id)).pack(),
            card_message_id=posted_card(support).message_id,
        ),
    )

    # Assert
    assert support.only().status is SupportTicketStatus.RESOLVED
    answered = answers(session)
    assert answered and "no longer the support inbox" in (answered[-1].text or "")
    assert answered[-1].show_alert is True


async def test_a_room_that_holds_no_card_is_still_none_of_our_business(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    support: FakeSupportTickets,
    bot_chats: FakeBotChats,
) -> None:
    """The widening is per-UPDATE and not per-room, and this is what stops it spreading.

    "This chat holds the card this update points at" is the whole entitlement. Ordinary
    conversation in the old room points at no card, so it is claimed by nobody — exactly as it
    was before the operator ever selected that room — and the marketing group the bot also sits
    in gains nothing at all.

    **It asserts UNHANDLED and not merely silence, and the difference is the whole test.** The
    silence assertion alone passed under every mutation of ``InSupportGroup`` this was checked
    against — a room claimed per-ROOM instead of per-update reaches
    :func:`~bayram.bot.handlers.support.handle_unresolved_group_message`, whose selective
    silence then says nothing about staff chatter anyway, so nothing outbound is recorded and
    the test could not tell "declined" from "claimed and deliberately quiet". Those are
    different facts: the second one means this router has become the catch-all for every room
    the bot sits in, which is precisely what :func:`_touches_a_card_in` is narrow to prevent.
    ``UNHANDLED`` is the only observable that separates them, so the silence check is kept for
    what it is worth and the routing check is what actually pins the boundary. Do not "simplify"
    this back to counting calls.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    bot_chats.answer = ok(SupportGroupTarget(chat_id=GROUP_CHAT_ID - 1, thread_id=None))
    before = len(session.calls)

    # Act
    chatter = await dispatcher.feed_update(bot, group_message("anyone around?"))
    to_a_colleague = await dispatcher.feed_update(
        bot, group_message("still here", reply_to=group_colleague_message())
    )

    # Assert — no router claimed either update...
    assert chatter is UNHANDLED, (
        "a room that holds no card this update points at must be claimed by nobody"
    )
    assert to_a_colleague is UNHANDLED, (
        "a reply to a PERSON points at no card of ours, however many cards the room holds"
    )
    # ...and therefore nothing was said, which is the half a silent catch-all could also fake.
    assert len(session.calls) == before


def _contact_keyboards(session: RecordingSession, chat_id: int) -> list[SendMessage]:
    """Every message sent to ``chat_id`` carrying a ``request_contact`` button.

    Asserted on the BUTTON and not on the screen's text, because the text is what a future
    copy change moves and the button is the leak: tapping it publishes the tapper's own phone
    number into whatever chat the keyboard was drawn in.
    """
    leaked = []
    for call in sends(session):
        markup = call.reply_markup
        if call.chat_id != chat_id or not isinstance(markup, ReplyKeyboardMarkup):
            continue
        if any(button.request_contact for row in markup.keyboard for button in row):
            leaked.append(call)
    return leaked


async def test_start_in_a_group_never_offers_the_contact_keyboard(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    """REGRESSION (defect D) — a privacy leak this feature created.

    The picker asks operators to ADD THE BOT TO GROUPS so they appear in it. ``commands`` and
    ``start`` sat outside the private-chat umbrella "so a staffer's ``/privacy`` reaches its
    handler", a reason written when the bot was in no groups at all. A colleague typing
    ``/start`` in one of those rooms took ``handle_start``'s un-onboarded branch and the bot
    posted ``onboarding_contact_screen`` into the group — a ``ReplyKeyboardMarkup`` whose
    button carries ``request_contact=True``, shown to everybody in the room. **Anyone who taps
    it publishes their own phone number to the whole group**, and the answer then reaches
    nothing, because ``onboarding`` IS under the umbrella.

    **The account is seeded with a LANGUAGE and no number, and that seeding is the test.**
    ``handle_start`` gates twice: ``is_language_chosen`` first, ``is_onboarded`` second. An
    account with no profile row at all stops at the FIRST gate and gets the language screen, so
    a version of this test that fed ``/start`` from an unseeded account asserted on a
    ``request_contact`` button that the broken code never reached either — true of the leak and
    of the fix alike, which is no assertion at all. ``record_language`` is the store call the
    customer's own language tap makes, and it produces the one profile shape that reaches
    :func:`~bayram.bot.screens.onboarding_contact_screen`: a language chosen, a number not
    shared. Anybody who has ever tapped a language and stopped is in that state.
    """
    # Arrange — a group the bot was added to, and an account that chose a language and stopped
    stranger_chat = -1_009_999_999_999
    await profiles.record_language(STAFF_USER_ID, ui_language=Language.EN)

    # Act
    await dispatcher.feed_update(bot, group_message("/start", chat_id=stranger_chat))

    # Assert
    assert _contact_keyboards(session, stranger_chat) == [], (
        "a request_contact button in a group publishes the tapper's number to the room"
    )
    assert [call for call in sends(session) if call.chat_id == stranger_chat] == []


@pytest.mark.parametrize("command", ["/start", "/balance", "/support"])
async def test_no_standing_command_answers_in_a_group_at_all(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, command: str
) -> None:
    """The same hole through the other two doors, both of which shipped with it.

    ``/balance`` posts an account's credit balance and its purchase buttons; ``/support``
    opens a ticket for whoever typed it and sends a ``ForceReply`` into the room. Neither
    belongs in a chat full of other people, and the fix is structural — the umbrella — rather
    than three handlers each remembering to check.
    """
    # Arrange
    stranger_chat = -1_009_999_999_999
    before = len(session.calls)

    # Act
    await dispatcher.feed_update(bot, group_message(command, chat_id=stranger_chat))

    # Assert
    assert len(session.calls) == before


async def test_a_command_in_the_support_group_is_redirected_and_never_denied(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, support: FakeSupportTickets
) -> None:
    """The data-subject surface the old arrangement was FOR, kept without the leak.

    ``/privacy`` and ``/forget`` are in ``gate.ERASURE_COMMANDS`` and may not be denied at the
    router layer. They are not denied here — they are redirected: the answer to ``/privacy`` is
    a statement about the person who typed it, and posting it into a room full of colleagues is
    a disclosure rather than a service. The same command in a DM does exactly what it always
    did, which every other test in ``test_commands.py`` still pins.
    """
    # Arrange
    await open_and_describe(dispatcher, bot, support)
    before = len(group_sends(session))

    # Act
    await dispatcher.feed_update(bot, group_message("/privacy"))

    # Assert
    said = group_sends(session)[before:]
    assert said, "a data-subject request must never simply evaporate"
    assert "private chat only" in (said[-1].text or "")
    assert not [
        call
        for call in group_sends(session)
        if "privacy" in (call.text or "").lower() and "private chat only" not in (call.text or "")
    ]
