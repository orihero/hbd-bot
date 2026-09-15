"""The three support jobs, driven end to end against a real database and a recording transport.

These are deliberately not mocked, for ``test_payme_jobs``'s reason: every property worth
asserting here is a property of a real row.

* the card sync is IDEMPOTENT because ``group_message_id`` is a latch claimed by the rowcount
  of a conditional ``UPDATE``, not because a fake remembered being called — so the replay test
  runs the job twice against the same row and counts ``SendMessage`` calls;
* the relay is idempotent because ``support_ticket_events.relayed_at`` is a real column, and
  the ONE thing that must never happen — an internal ``NOTE`` reaching a customer — is a
  property of a real timeline with both kinds of row on it;
* "answer in the language the TICKET was opened in" is only assertable against a ticket whose
  language differs from everything else in the fixture, so the ticket here is opened in Russian
  and the assertion is an equality against ``translate(..., Language.RU, ...)``;
* the verification job's whole value is that its four verdicts are DIFFERENT SENTENCES, so the
  classifier is asserted against the real ``aiogram`` exception types and the job is asserted
  against the real ``bot_chats`` row it writes them into.

**THE SUPPORT GROUP IS NO LONGER A SETTING, AND THAT CHANGED THIS FIXTURE.** It is a row in
``bot_chats`` that an operator selects in the panel (``SUPPORT_TICKETS_SPEC §3.8``), so the
:func:`container` fixture SELECTS one, exactly as a live deployment would, instead of passing a
chat id into ``Settings``. Any test that wants a different answer selects a different row —
which is also what makes "the card is edited where it was POSTED, not where the selection points
today" assertable without a second settings object.

The container is the same real, provider-free shape ``tests/test_runtime/test_payme_jobs.py``
uses: SQLite on disk, no vendor adapter anywhere near it.

**Two things about the fixture that will otherwise waste somebody's afternoon.** The worker
context here carries no ``redis``, so :func:`~bayram.runtime.support_jobs.group_pacer` degrades
to :class:`~bayram.runtime.pacer.InMemorySendBudgetStore` — which is real pacing, so a test
that puts two messages into the group inside one wall-clock second really does sleep to the
next second. That is why no test here sends more than a couple. And the group chat id is
NEGATIVE, because that is what a supergroup id looks like and a fixture using a positive one
would pass while pointing the whole feature at a private chat.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import EditMessageText, GetChat, SendMessage
from aiogram.types import AcceptedGiftTypes, Chat, ChatFullInfo, Message, User
from arq.worker import Retry

from bayram.bot.delivery import MAX_MESSAGE_CHARS
from bayram.bot.handlers.support import relay_text_for
from bayram.bot.i18n import translate
from bayram.bot.support_card import status_badge
from bayram.bot_chats import BotChatSnapshot
from bayram.config import Settings
from bayram.contracts import (
    BotChatSource,
    BotChatStatus,
    BotChatType,
    Language,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
    is_ok,
)
from bayram.db.admin.support_tickets import get_ticket
from bayram.db.admin.views import SupportTicketEventItem
from bayram.db.bot_chats import SqlBotChats, load_chat, select_support_group
from bayram.db.support_tickets import SqlSupportTickets, append_event
from bayram.errors import PipelineError
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.jobs import build_kit_worker_settings
from bayram.runtime.pacer import SEND_BUDGET_KEY, SEND_PARK_KEY
from bayram.runtime.support_jobs import (
    GROUP_PACER_POLICY,
    GROUP_SEND_BUDGET_KEY,
    SUPPORT_CARD_JOB_NAME,
    SUPPORT_CARD_MAX_TRIES,
    SUPPORT_RELAY_JOB_NAME,
    SUPPORT_RELAY_MAX_TRIES,
    SUPPORT_VERIFY_JOB_NAME,
    SUPPORT_VERIFY_MAX_TRIES,
    VERIFICATION_CONFIRMATION,
    relay_support_reply,
    sync_support_card,
    verification_failure_for,
    verify_support_group,
)
from bayram.support import EventAuthor, TicketSnapshot
from tests.test_bot.conftest import BOT_TOKEN, RecordingSession

#: Outside the 32-bit range, so a column that was accidentally ``Integer`` fails loudly rather
#: than truncating a customer's id into somebody else's account.
_CUSTOMER: Final[int] = 8_200_000_000_031

#: A supergroup id, which is what one really looks like: ``-100`` and then the chat's own
#: number. A positive id here would be a private chat — an internal triage card delivered to a
#: stranger — and ``bayram.bot_chats.chat_type_for_pasted_id`` refuses a non-negative id for
#: exactly that reason, so a fixture using a positive one would not even be selectable.
_GROUP: Final[int] = -1_002_345_678_901
#: A DIFFERENT group, used only to prove the edit goes to the chat the card was posted to
#: rather than to whichever chat is SELECTED today.
_OTHER_GROUP: Final[int] = -1_009_876_543_210
#: A chat id that is in no directory at all — what a stale enqueue names.
_UNKNOWN_GROUP: Final[int] = -1_005_555_555_555
#: A forum topic inside ``_GROUP``. Non-zero, because ``0`` is exactly the value Telegram
#: refuses on a group that is not a forum and the column is nullable to avoid ever sending it.
_TOPIC: Final[int] = 91

_PANEL: Final[str] = "https://panel.example"
_START: Final[datetime] = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)

#: The catalogue key the relay is rendered from, spelled here rather than imported.
#:
#: It is deliberately NOT imported from the worker any more: the worker used to own a
#: ``RELAY_MESSAGE_KEY`` of its own and render the template itself, which is how it came to
#: bound the RAW body instead of the finished message. It now renders through
#: ``handlers.support.relay_text_for``, so there is no constant left to import — and asserting
#: against the catalogue directly is the stronger assertion anyway, because comparing the
#: worker's output to the function the worker calls would be true of any two implementations.
_RELAY_KEY: Final[str] = "support.ticket.reply"

#: The ``message_id`` Telegram answers the relay with, pinned by the fixture so the re-point
#: can be asserted as an equality rather than as "something changed".
_RELAY_MESSAGE_ID: Final[int] = 777_001

#: The ForceReply the ticket is listening on BEFORE a staffer or an operator answers it. A
#: value the relay's id cannot collide with, so "it moved" and "it moved to the right place"
#: are two different assertions.
_FORCE_REPLY_MESSAGE_ID: Final[int] = 4_242


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "telegram_bot_token": "t",
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'support_jobs.db'}",
        "elevenlabs_api_key": "k",
        "llm_api_key": "k",
        "support_panel_base_url": _PANEL,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    """A real, provider-free container with a support group SELECTED — a live deployment.

    The selection is part of the fixture rather than of each test because it is part of the
    shipped state: a deployment with no group selected posts no cards at all, which is its own
    test below and not the baseline every other assertion should be written against.
    """
    built = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    await _select_group(built)
    yield built
    await built.aclose()


async def _select_group(
    container: AppContainer, chat_id: int = _GROUP, *, thread_id: int | None = None
) -> None:
    """Point the support inbox at a chat, the way the panel's POST does.

    Through :func:`bayram.db.bot_chats.select_support_group` and not through a hand-written
    ``INSERT``, because that function is what the panel calls and it is the only thing that
    knows the two rules a hand-written row would get wrong: the previous selection is cleared
    BEFORE the new one is set (the partial unique index refuses two), and an id the directory
    has never heard of is recorded as ``source=manual`` rather than rejected.
    """
    async with container.require_session_factory().begin() as session:
        await select_support_group(
            session, chat_id, thread_id=thread_id, selected_by_username="ops.dilnoza", now=_START
        )


async def _chat_row(container: AppContainer, chat_id: int = _GROUP) -> BotChatSnapshot:
    """One ``bot_chats`` row, read back the way the panel reads it."""
    async with container.require_session_factory()() as session:
        found = await load_chat(session, chat_id)
    assert found is not None
    return found


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    """The worker's ``Bot``: send-only, recording, and HTML.

    ``parse_mode=HTML`` is not decoration — the card and the relay template are both HTML, and
    a bot built without it renders the tags as literal text while every assertion still passes.
    """
    return Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


def _ctx(container: AppContainer, bot: Bot, **extra: Any) -> dict[str, Any]:
    """The context ARQ hands a job. No ``redis`` key: see the module docstring."""
    return {"container": container, "bot": bot, **extra}


def _sent(session: RecordingSession) -> list[SendMessage]:
    """Every message this worker put in a chat, typed. ``isinstance`` rather than a name
    comparison, so ``mypy --strict`` checks the field each assertion reaches for."""
    return [call for call in session.calls if isinstance(call, SendMessage)]


def _edits(session: RecordingSession) -> list[EditMessageText]:
    return [call for call in session.calls if isinstance(call, EditMessageText)]


def _store(container: AppContainer) -> SqlSupportTickets:
    return SqlSupportTickets(container.require_session_factory())


async def _described_ticket(
    container: AppContainer,
    *,
    language: Language = Language.RU,
    order_id: UUID | None = None,
    body: str = "Имя спели неправильно.",
) -> TicketSnapshot:
    """One ticket a customer actually typed into. The state both jobs are defined over.

    Described a minute after it was opened rather than at the same instant: the timeline is
    ordered on ``(created_at, id)`` and the id is a random uuid4, so two events sharing an
    instant come back in a stable but arbitrary order. Everything here reads better with a
    clock that moves.
    """
    store = _store(container)
    opened = await store.open_ticket(
        telegram_user_id=_CUSTOMER,
        language=language,
        source=(
            SupportTicketSource.DELIVERY_BUTTON
            if order_id is not None
            else SupportTicketSource.SUPPORT_COMMAND
        ),
        order_id=order_id,
        now=_START,
    )
    assert is_ok(opened), opened
    described = await store.describe_ticket(
        opened.value.id, body=body, now=_START + timedelta(minutes=1)
    )
    assert is_ok(described) and described.value is not None
    return described.value


async def _posted_ticket(container: AppContainer, *, message_id: int = 5150) -> TicketSnapshot:
    """A ticket whose card is already in the group — the latch claimed and settled."""
    ticket = await _described_ticket(container)
    store = _store(container)
    claimed = await store.claim_group_post(
        ticket.id, group_chat_id=_GROUP, group_message_id=message_id
    )
    assert is_ok(claimed) and claimed.value
    settled = await store.settle_group_post(ticket.id, now=_START + timedelta(minutes=2))
    assert is_ok(settled)
    reread = await store.load_ticket(ticket.id)
    assert is_ok(reread) and reread.value is not None
    return reread.value


async def _reload(container: AppContainer, ticket_id: UUID) -> TicketSnapshot:
    found = await _store(container).load_ticket(ticket_id)
    assert is_ok(found) and found.value is not None
    return found.value


async def _reply_event(
    container: AppContainer, ticket: TicketSnapshot, *, body: str = "Исправили, слушайте ещё раз."
) -> UUID:
    """An operator's reply, composed but not yet delivered — what the panel enqueues against."""
    appended = await _store(container).append_event(
        ticket.id,
        kind=SupportTicketEventKind.REPLY,
        author=EventAuthor.operator("ops.dilnoza"),
        now=_START + timedelta(minutes=5),
        body=body,
    )
    assert is_ok(appended), appended
    return appended.value


async def _prompted_ticket(container: AppContainer, **kwargs: Any) -> TicketSnapshot:
    """A described ticket that is ALREADY listening on a ForceReply, like every real one.

    Every ticket in production reaches the panel in this state: the customer tapped, the bot
    sent a ``ForceReply`` and recorded its id, and the customer answered it. A fixture that
    left ``prompt_message_id`` NULL would let a job that never re-points at all look correct,
    because NULL and "the stale prompt" are equally wrong and only one of them is visible.
    """
    ticket = await _described_ticket(container, **kwargs)
    attached = await _store(container).attach_prompt(
        ticket.id, prompt_message_id=_FORCE_REPLY_MESSAGE_ID, now=_START
    )
    assert is_ok(attached) and attached.value
    return await _reload(container, ticket.id)


def _telegram_answers_the_relay_with(session: RecordingSession, message_id: int) -> None:
    """Pin the ``message_id`` Telegram hands back, which is the thing the ticket must point at.

    Pinned rather than read off the fake's own counter: the counter is an implementation
    detail of the recording session and an assertion against it would still pass if the job
    re-pointed at, say, the ticket's group card id by mistake — two numbers that happen to
    agree in a fixture and never agree in production.
    """
    session.responses["SendMessage"] = Message(
        message_id=message_id,
        date=_START,
        chat=Chat(id=_CUSTOMER, type="private"),
        from_user=User(id=42, is_bot=True, first_name="Bayram"),
    )


async def _event_row(
    container: AppContainer, ticket_id: UUID, event_id: UUID
) -> SupportTicketEventItem:
    """One timeline row, read the way the panel reads it — which is where ``relayed_at`` is
    published, and the only place "composed" can be told from "delivered"."""
    async with container.require_session_factory()() as db:
        detail = await get_ticket(db, ticket_id)
    assert detail is not None
    found = next((row for row in detail.events if row.id == event_id), None)
    assert found is not None
    return found


# ---------------------------------------------------------------------------
# Registration — ARQ dispatches by NAME, and the panel spells these strings twice
# ---------------------------------------------------------------------------
def test_every_job_is_registered_under_the_name_the_panel_enqueues(tmp_path: Path) -> None:
    # Arrange — a job absent from ``functions`` is a route that answers 200 with a job id no
    # process will ever run, which is the failure this assertion is the only guard against.
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )
    entries = {
        getattr(entry, "name", getattr(entry, "__name__", "")): entry for entry in worker.functions
    }

    # Assert — registered, and with the retry budget each job reads back. The two numbers
    # MUST match: ARQ compares ``job_try > max_tries`` before re-entering the function, so a
    # job that stops raising ``Retry`` at a different number than it is registered with either
    # gives up an attempt early or has its last retry discarded with nobody told.
    assert {
        SUPPORT_CARD_JOB_NAME,
        SUPPORT_RELAY_JOB_NAME,
        SUPPORT_VERIFY_JOB_NAME,
    } <= set(entries)
    assert entries[SUPPORT_CARD_JOB_NAME].max_tries == SUPPORT_CARD_MAX_TRIES
    assert entries[SUPPORT_RELAY_JOB_NAME].max_tries == SUPPORT_RELAY_MAX_TRIES
    assert entries[SUPPORT_VERIFY_JOB_NAME].max_tries == SUPPORT_VERIFY_MAX_TRIES
    assert sync_support_card.__name__ == SUPPORT_CARD_JOB_NAME
    assert relay_support_reply.__name__ == SUPPORT_RELAY_JOB_NAME
    assert verify_support_group.__name__ == SUPPORT_VERIFY_JOB_NAME


def test_the_group_gets_its_own_budget_and_shares_the_park() -> None:
    # Assert — the whole design of the group pacer in two lines. A separate BUDGET because
    # Telegram's per-chat ceiling and its per-token ceiling are different limits; the SHARED
    # park because ``retry_after`` is a statement about the token, so a group pacer that
    # parked privately would keep posting cards through a flood wait a campaign had earned
    # and deepen the wait on the credential the customer ORDERS depend on.
    assert GROUP_PACER_POLICY.budget_key == GROUP_SEND_BUDGET_KEY
    assert GROUP_PACER_POLICY.budget_key != SEND_BUDGET_KEY
    assert GROUP_PACER_POLICY.park_key == SEND_PARK_KEY


# ---------------------------------------------------------------------------
# sync_support_card
# ---------------------------------------------------------------------------
async def test_a_card_sync_posts_the_card_when_the_ticket_has_never_been_posted(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — a described ticket whose group post never happened: Telegram refused it at
    # description time, or the group was configured afterwards. The panel's sync button is
    # this ticket's second chance at ever being seen by a staffer.
    ticket = await _described_ticket(container)
    assert not ticket.is_posted

    # Act
    await sync_support_card(_ctx(container, bot), str(ticket.id))

    # Assert — one card, in the configured group, and the latch now holds the message id
    # Telegram answered with. Both halves matter: without the id there is nothing for a staff
    # reply to resolve through.
    sent = _sent(session)
    assert len(sent) == 1
    assert sent[0].chat_id == _GROUP
    assert ticket.public_ref in (sent[0].text or "")
    after = await _reload(container, ticket.id)
    assert after.is_posted
    assert after.group_chat_id == _GROUP
    assert after.group_posted_at is not None


async def test_a_replayed_card_sync_never_posts_a_second_card(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — ARQ runs ``retry_jobs=True`` and SIGTERM cancels running tasks, so this job
    # WILL run twice. The guarantee is not "it is enqueued once"; it is that the latch has
    # already been claimed by the time the second run reads the row.
    ticket = await _described_ticket(container)

    # Act
    await sync_support_card(_ctx(container, bot), str(ticket.id))
    first = await _reload(container, ticket.id)
    await sync_support_card(_ctx(container, bot), str(ticket.id))

    # Assert — exactly one card was ever sent; the replay took the edit arm instead, and the
    # recorded message id did not move.
    assert len(_sent(session)) == 1
    assert len(_edits(session)) == 1
    assert (await _reload(container, ticket.id)).group_message_id == first.group_message_id


async def test_a_card_sync_redraws_the_existing_card_with_the_current_status(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the panel moved the ticket in its own transaction and enqueued this job. The
    # card is what staff work from, so until it is repainted the move has not happened as far
    # as the group is concerned.
    ticket = await _posted_ticket(container)
    moved = await _store(container).move_status(
        ticket.id,
        expected=SupportTicketStatus.NEW,
        to_status=SupportTicketStatus.IN_PROGRESS,
        author=EventAuthor.operator("ops.dilnoza"),
        now=_START + timedelta(minutes=3),
    )
    assert is_ok(moved) and moved.value is not None

    # Act
    await sync_support_card(_ctx(container, bot), str(ticket.id))

    # Assert — edited, never re-posted: a new message per state change turns a scannable
    # queue into a scroll of history the panel already keeps.
    assert not _sent(session)
    edit = _edits(session)[-1]
    assert edit.chat_id == _GROUP
    assert edit.message_id == ticket.group_message_id
    assert status_badge(SupportTicketStatus.IN_PROGRESS) in (edit.text or "")


async def test_the_card_is_edited_where_it_was_posted_not_where_the_selection_points_today(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — an operator who repointed the support inbox after this card was posted, which
    # is now a thing they can do in the panel between two updates rather than a redeploy. A
    # message id belongs to ONE chat: editing it against the new group names either somebody
    # else's message or nothing at all, and the card staff are actually reading would silently
    # stop being updated. The latch records the chat for this reason, so the job reads the
    # ticket and never the selection.
    ticket = await _posted_ticket(container)
    assert ticket.group_chat_id == _GROUP
    await _select_group(container, _OTHER_GROUP)

    # Act
    await sync_support_card(_ctx(container, bot), str(ticket.id))

    # Assert — the recorded chat wins.
    edit = _edits(session)[-1]
    assert edit.chat_id == _GROUP


async def test_an_edit_telegram_refuses_is_swallowed_rather_than_retried(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — "message is not modified" is BY FAR the most common answer here: two
    # operators pressing the same button, a replayed job, a status moved back to where the
    # card already said it was. It means the card is already correct.
    ticket = await _posted_ticket(container)
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=_GROUP, message_id=1, text="x"),
        message="Bad Request: message is not modified",
    )

    # Act / Assert — no ``Retry``, no exception. Spending the ladder proving the card is
    # correct three times would be the alternative.
    await sync_support_card(_ctx(container, bot, job_try=1), str(ticket.id))
    assert len(_edits(session)) == 1


async def test_a_refused_first_post_leaves_the_latch_unset_and_asks_for_another_attempt(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the group post is the one arm nothing else repaints: until the latch is
    # claimed there is no card to edit, the ticket sits on the board with no staffer having
    # seen it, and a relay has nothing to listen on. So a refusal here IS worth the ladder,
    # which is why ``SUPPORT_CARD_MAX_TRIES`` is three rather than one.
    ticket = await _described_ticket(container)
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=_GROUP, text="x"),
        message="Bad Request: chat not found",
    )

    # Act / Assert — another attempt is asked for...
    with pytest.raises(Retry):
        await sync_support_card(_ctx(container, bot, job_try=1), str(ticket.id))

    # ...and the last permitted one gives up quietly rather than raising a ``Retry`` ARQ
    # would discard with nobody told. Either way the latch is UNSET, which is what keeps the
    # ticket retryable — a row marked posted whose card never arrived is invisible to
    # everybody.
    await sync_support_card(_ctx(container, bot, job_try=SUPPORT_CARD_MAX_TRIES), str(ticket.id))
    assert not (await _reload(container, ticket.id)).is_posted


async def test_a_card_sync_with_no_group_selected_posts_nothing(
    tmp_path: Path, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — nobody has picked a support group yet, which is the state EVERY deployment
    # starts in now that the group left the environment (``SUPPORT_TICKETS_SPEC §3.8``): there
    # is no seed, no pin and no fallback setting to inherit one from. It switches off ONLY the
    # group leg — the ticket is still written, the customer is still answered and the board is
    # still populated — so it is an ordinary state rather than a failure and must never be
    # retried. This container is built WITHOUT the fixture's selection for exactly that reason.
    built = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    try:
        ticket = await _described_ticket(built)

        # Act
        await sync_support_card(_ctx(built, bot), str(ticket.id))

        # Assert
        assert not session.calls
        assert not (await _reload(built, ticket.id)).is_posted
    finally:
        await built.aclose()


async def test_a_card_sync_for_an_unknown_ticket_says_so_and_sends_nothing(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act — a stale enqueue against a row ``/forget`` has since deleted. Two more
    # attempts would find the same nothing, so this must not raise ``Retry``.
    await sync_support_card(_ctx(container, bot, job_try=1), str(uuid4()))

    # Assert
    assert not session.calls


# ---------------------------------------------------------------------------
# relay_support_reply
# ---------------------------------------------------------------------------
async def test_a_relayed_reply_reaches_the_customer_in_the_tickets_own_language(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the ticket was opened in Russian. Answering in the account's language TODAY
    # would send the one message where being understood is the entire point in a language the
    # customer may no longer read, which is why ``support_tickets.language`` exists at all.
    ticket = await _described_ticket(container, language=Language.RU)
    event_id = await _reply_event(container, ticket)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — the customer's private chat, the ticket's language, the ticket's reference,
    # and the clock that tells "composed" from "delivered" on the timeline.
    sent = _sent(session)[-1]
    assert sent.chat_id == _CUSTOMER
    assert sent.text == translate(
        _RELAY_KEY,
        Language.RU,
        ref=ticket.public_ref,
        body="Исправили, слушайте ещё раз.",
    )
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is not None


async def test_a_reply_that_already_landed_is_never_sent_twice(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — every job in this system is replayed on every deploy, and saying it twice is
    # the one failure a customer notices. ``relayed_at`` is the guard, and it is a real column
    # rather than something a fake remembered.
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket)
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert
    assert len(_sent(session)) == 1


async def test_an_internal_note_is_never_relayed_to_the_customer(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — THE assertion of this module. ``support_ticket_events`` holds ``NOTE`` rows,
    # which are an operator's INTERNAL words about a customer, in exactly the same ``body``
    # column a reply uses. Relaying one would send somebody the private assessment written
    # about them, so the kind is checked at the last moment before the send rather than
    # trusted from the enqueue side.
    ticket = await _described_ticket(container)
    note = await _store(container).append_event(
        ticket.id,
        kind=SupportTicketEventKind.NOTE,
        author=EventAuthor.operator("ops.dilnoza"),
        now=_START + timedelta(minutes=4),
        body="Постоянно жалуется, третий тикет за неделю.",
    )
    assert is_ok(note), note

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(note.value))

    # Assert — nothing left the process, and the note was not stamped as though it had.
    assert not session.calls
    assert (await _event_row(container, ticket.id, note.value)).relayed_at is None


async def test_an_event_id_no_timeline_row_answers_yet_asks_for_another_attempt(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — THE regression. An absent event row used to be read as terminal: the job
    # logged "no timeline row answers this event id", returned, and ARQ recorded a success.
    # But the panel writes that row and enqueues this job in the same request, and the row is
    # not visible to another session until that request COMMITS — so the job that wins the
    # window sees a timeline without it and would have thrown the operator's answer away
    # while the panel showed it composed. "Not there" is a timing answer, not a verdict.
    ticket = await _described_ticket(container)

    # Act / Assert — another attempt is asked for, and nothing was sent in the meantime.
    with pytest.raises(Retry):
        await relay_support_reply(_ctx(container, bot, job_try=1), str(ticket.id), str(uuid4()))
    assert not session.calls


async def test_an_event_id_still_unanswered_on_the_last_attempt_gives_up_quietly(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act — the other half, and it has to be asserted separately: a job that only
    # ever retried would pass the test above and then have its final ``Retry`` DISCARDED by
    # ARQ with no log line and nobody told. A row still missing after the whole ladder is
    # genuinely gone — an erased customer — rather than merely uncommitted.
    ticket = await _described_ticket(container)
    await relay_support_reply(
        _ctx(container, bot, job_try=SUPPORT_RELAY_MAX_TRIES), str(ticket.id), str(uuid4())
    )

    # Assert
    assert not session.calls


async def test_a_reply_still_uncommitted_when_the_job_runs_is_delivered_on_the_next_attempt(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the window itself rather than a stand-in for it. The reply is WRITTEN and
    # flushed in one session and deliberately not committed, which is exactly the state the
    # panel's request is in between ``append_event`` and ``get_db_session``'s commit; the job
    # then runs in a session of its own, as ARQ's worker really does, and cannot see the row.
    # Every other test in this file commits first, which is why the suite went green over a
    # defect that threw an operator's answer away a few percent of the time.
    ticket = await _described_ticket(container)

    async with container.require_session_factory()() as writer:
        event_id = await append_event(
            writer,
            ticket.id,
            kind=SupportTicketEventKind.REPLY,
            author=EventAuthor.operator("ops.dilnoza"),
            now=_START + timedelta(minutes=5),
            body="Исправили, слушайте ещё раз.",
        )

        # Act — the worker wins the race. Another attempt, and nothing sent.
        with pytest.raises(Retry):
            await relay_support_reply(
                _ctx(container, bot, job_try=1), str(ticket.id), str(event_id)
            )
        assert not session.calls

        # ...and now the panel's transaction commits.
        await writer.commit()

    await relay_support_reply(_ctx(container, bot, job_try=2), str(ticket.id), str(event_id))

    # Assert — the customer IS answered, once, and the row says so. That is the whole point:
    # the old code completed successfully here and the reply simply ceased to exist.
    sent = _sent(session)
    assert len(sent) == 1
    assert sent[0].chat_id == _CUSTOMER
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is not None


async def test_a_blocked_customer_leaves_the_reply_unstamped(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the deliberate divergence from ``payme_jobs._send``, which stamps an
    # unreachable chat as notified because an unstamped row there becomes an unbounded sweep
    # backlog. NOTHING sweeps unrelayed replies, so leaving the clock NULL costs nothing and
    # is simply true: the customer never received it. The panel renders that row as
    # composed-and-not-delivered, which is exactly what an operator needs to see before they
    # write a second paragraph into the void.
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket)
    session.failures["SendMessage"] = TelegramForbiddenError(
        method=SendMessage(chat_id=_CUSTOMER, text="x"),
        message="Forbidden: bot was blocked by the user",
    )

    # Act — and no ``Retry``: a block does not clear in twenty seconds.
    await relay_support_reply(_ctx(container, bot, job_try=1), str(ticket.id), str(event_id))

    # Assert
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is None


async def test_a_transient_telegram_failure_retries_and_then_stops_raising(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — ARQ discards a ``Retry`` raised on the FINAL permitted attempt with no log
    # line and nobody told, so the job has to read its own ``max_tries`` and take the
    # give-up path itself. Both sides are asserted, because a job that only ever retried and
    # a job that never retried both pass a test that checks one.
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket)
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=_CUSTOMER, text="x"),
        message="Bad Request: chat not found",
    )

    # Act / Assert — an early attempt asks for another.
    with pytest.raises(Retry):
        await relay_support_reply(_ctx(container, bot, job_try=1), str(ticket.id), str(event_id))

    # ...and the last one does not, leaving the row in the state that makes it visible.
    await relay_support_reply(
        _ctx(container, bot, job_try=SUPPORT_RELAY_MAX_TRIES), str(ticket.id), str(event_id)
    )
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is None


async def test_a_long_operator_reply_is_bounded_by_the_finished_message_not_the_raw_body(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the ``body`` column is 4096, which is also Telegram's own single-message
    # ceiling, and the template then wraps the body in a header, a ``<blockquote>`` and a
    # closing line. So a reply at the column's full length CANNOT be sent whole, and the only
    # question is how the cut is taken. This door used to take it against a fixed raw bound of
    # 3000 characters chosen to leave room for a template nobody measured; it now renders and
    # trims until the RESULT fits, which is the same thing the staff-group door does.
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket, body="я" * MAX_MESSAGE_CHARS)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — inside the ceiling, and inside it by the template's real overhead rather than
    # by a thousand-character guess: a fixed raw bound threw away nearly a page of an
    # operator's answer that Telegram would have carried.
    text = _sent(session)[-1].text or ""
    assert len(text) <= MAX_MESSAGE_CHARS
    assert text.count("я") > 3_500
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is not None


async def test_an_escape_heavy_operator_reply_still_fits_one_telegram_message(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — THE regression for this door, and it is the case a raw bound cannot express.
    # ``translate`` HTML-escapes every parameter, so one ``&`` an operator types is FIVE
    # characters on the wire. Three thousand raw characters of it render as more than fifteen
    # thousand, Telegram answers 400, the five attempts are burned against a message that can
    # never fit, and the customer is never answered while the timeline says a reply was
    # composed — with ``relayed_at`` NULL, which reads as "they blocked us".
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket, body="&" * 4_000)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — it fits, it is really escaped, and no entity was split in half by the cut: a
    # trailing ``&am`` is a malformed entity and earns the same 400 the length would have.
    text = _sent(session)[-1].text or ""
    assert len(text) <= MAX_MESSAGE_CHARS
    assert "&amp;" in text
    assert text.count("&") == text.count("&amp;")
    assert (await _event_row(container, ticket.id, event_id)).relayed_at is not None


async def test_the_panel_relays_exactly_what_the_group_door_would_have_sent(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the two doors answer the same customer from the same template, and for a while
    # they disagreed: the group door measured the finished message and the panel door measured
    # the raw body. One shared renderer is what makes them agree by construction rather than
    # by two constants that were equal on the day they were written.
    # The body is long AND escape-heavy on purpose: a short one renders identically under both
    # bounds, so it would prove nothing at all. This one is over the ceiling once escaped,
    # which is precisely where the two doors used to part company.
    ticket = await _described_ticket(container)
    body = "Исправили — теперь Dilnora, а не Dilnoza. <b>&</b> " * 100
    event_id = await _reply_event(container, ticket, body=body)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — byte for byte, including where the cut falls and how the operator's ``<`` and
    # ``&`` are escaped. Not a tautology despite calling the same function: the assertion is
    # that this door renders through THAT function and not through a template of its own.
    assert (_sent(session)[-1].text or "") == relay_text_for(ticket, body)


async def test_a_panel_reply_re_points_the_ticket_at_the_message_it_just_sent(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — THE critical regression, and it is the same one that was fixed on the
    # staff-group door and left standing on this one. ``support_tickets.prompt_message_id`` is
    # "the message this ticket is currently listening on", and the relay ends by inviting a
    # reply. If the job does not move it, the ticket goes on listening to a ForceReply from
    # weeks ago: the customer's answer resolves to NO ticket, falls past the support router
    # and is claimed by whichever wizard step they are parked in — at ``Wizard.name`` their
    # sentence becomes the recipient's name and the pipeline sings it.
    ticket = await _prompted_ticket(container)
    assert ticket.prompt_message_id == _FORCE_REPLY_MESSAGE_ID
    _telegram_answers_the_relay_with(session, _RELAY_MESSAGE_ID)
    event_id = await _reply_event(container, ticket)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — the column moved to the relay's own id...
    store = _store(container)
    assert (await _reload(container, ticket.id)).prompt_message_id == _RELAY_MESSAGE_ID

    # ...and a follow-up really resolves through it. This is the lookup ``ListeningTicket``
    # runs on every private reply, so asserting the column alone would prove half of it.
    resolved = await store.ticket_listening_on(_CUSTOMER, prompt_message_id=_RELAY_MESSAGE_ID)
    assert is_ok(resolved) and resolved.value is not None
    assert resolved.value.id == ticket.id

    # ...while the ForceReply the customer has long since scrolled past no longer does, which
    # is what makes ``listen_on`` unconditional rather than a second ``attach_prompt``.
    stale = await store.ticket_listening_on(_CUSTOMER, prompt_message_id=_FORCE_REPLY_MESSAGE_ID)
    assert is_ok(stale) and stale.value is None


async def test_a_relay_the_customer_never_saw_leaves_the_ticket_listening_where_it_was(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the other half of the re-point, and it is not symmetrical bookkeeping. A
    # refused relay is a message that is not on the customer's screen, so pointing the ticket
    # at its id would make the ticket listen for a reply to something that does not exist,
    # and would simultaneously deafen it to the prompt that DOES.
    ticket = await _prompted_ticket(container)
    event_id = await _reply_event(container, ticket)
    session.failures["SendMessage"] = TelegramForbiddenError(
        method=SendMessage(chat_id=_CUSTOMER, text="x"),
        message="Forbidden: bot was blocked by the user",
    )

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert
    assert (await _reload(container, ticket.id)).prompt_message_id == _FORCE_REPLY_MESSAGE_ID


async def test_a_replayed_relay_neither_sends_again_nor_moves_what_the_ticket_listens_on(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — every job here is replayed on every deploy. The second run must stop at
    # ``relayed_at``, which means the re-point must sit BEHIND that guard rather than beside
    # it: a job that re-pointed before checking would walk the ticket forward onto a message
    # id it had not sent this time round.
    ticket = await _prompted_ticket(container)
    _telegram_answers_the_relay_with(session, _RELAY_MESSAGE_ID)
    event_id = await _reply_event(container, ticket)
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert
    assert len(_sent(session)) == 1
    assert (await _reload(container, ticket.id)).prompt_message_id == _RELAY_MESSAGE_ID


async def test_the_relay_writes_no_second_event_and_moves_no_status(
    container: AppContainer, bot: Bot
) -> None:
    # Arrange — the panel made the move in its own audited transaction and enqueues its own
    # card sync. A relay that also moved the status would be a second writer of a state
    # machine, racing the first, and its move would carry no audit row.
    ticket = await _described_ticket(container)
    event_id = await _reply_event(container, ticket)
    before = await _reload(container, ticket.id)

    # Act
    await relay_support_reply(_ctx(container, bot), str(ticket.id), str(event_id))

    # Assert — the status is untouched and the only authorship on the timeline is the
    # operator's own; the job appended nothing of its own.
    after = await _reload(container, ticket.id)
    assert after.status is before.status
    async with container.require_session_factory()() as db:
        detail = await get_ticket(db, ticket.id)
    assert detail is not None
    kinds = [row.kind for row in detail.events]
    assert kinds.count(SupportTicketEventKind.REPLY) == 1
    assert SupportAuthorKind.SYSTEM not in {
        row.author_kind for row in detail.events if row.kind is SupportTicketEventKind.REPLY
    }


# ---------------------------------------------------------------------------
# verify_support_group — the only thing between a typed chat id and a dead inbox
# ---------------------------------------------------------------------------
def _chat_full_info(
    *, chat_type: str = "supergroup", title: str | None = "Bayram support", username: str | None
) -> ChatFullInfo:
    """What ``getChat`` answers with, built once because most of its fields are noise.

    ``accent_color_id``, ``max_reaction_count`` and ``accepted_gift_types`` are required by
    Telegram's own schema and say nothing about anything this job cares about; spelling them at
    every call site would bury the three fields that ARE the subject — the type, the title and
    the ``@handle`` the verification writes back onto the row.
    """
    return ChatFullInfo(
        id=_GROUP,
        type=chat_type,
        title=title,
        username=username,
        accent_color_id=0,
        max_reaction_count=11,
        accepted_gift_types=AcceptedGiftTypes(
            unlimited_gifts=False,
            limited_gifts=False,
            unique_gifts=False,
            premium_subscription=False,
            gifts_from_channels=False,
        ),
    )


def _telegram_knows_the_chat(session: RecordingSession, **kwargs: Any) -> None:
    session.responses["GetChat"] = _chat_full_info(username="bayram_support", **kwargs)


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=GetChat(chat_id=_GROUP), message=message)


async def test_a_verified_group_gets_a_confirmation_and_a_stored_proof(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the ordinary case: an operator selected a group the bot really is in.
    _telegram_knows_the_chat(session)

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert — the proof is a MESSAGE THAT LANDED and not a ``getChat`` that returned. There is
    # no Telegram call that answers "may this bot write here": ``getChatMember`` returns a
    # status, and a status is evidence rather than permission, so the only honest proof is a
    # send.
    assert [type(call).__name__ for call in session.calls] == ["GetChat", "SendMessage"]
    sent = _sent(session)[0]
    assert sent.chat_id == _GROUP
    assert sent.text == VERIFICATION_CONFIRMATION
    row = await _chat_row(container)
    assert row.verified_at is not None
    assert row.is_verified
    assert row.verification_error is None


async def test_a_verification_writes_back_what_getchat_taught_it_about_a_pasted_row(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """A pasted id arrives as a bare number, and this is the only moment it gets a name.

    ``chat_type`` is the half worth asserting hardest. It is INFERRED from the ``-100`` prefix
    when an operator pastes an id, and that inference cannot tell a supergroup from a channel —
    it is only allowed to guess because this job overwrites the column with Telegram's own
    word. Without the write-back the guess is not a guess that gets corrected; it is one the
    panel repeats for the life of the row.
    """
    # Arrange — a manual row, born with no title, no handle and a guessed type.
    pasted = await _chat_row(container)
    assert pasted.source is BotChatSource.MANUAL
    assert pasted.bot_status is BotChatStatus.UNKNOWN
    assert pasted.chat_type is BotChatType.SUPERGROUP
    assert pasted.title is None
    _telegram_knows_the_chat(session, chat_type="channel", title="Bayram announcements")

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    row = await _chat_row(container)
    assert row.chat_type is BotChatType.CHANNEL
    assert row.title == "Bayram announcements"
    assert row.username == "bayram_support"


async def test_the_confirmation_goes_into_the_selected_topic_and_not_just_the_group(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — a group the bot can post in and a TOPIC it cannot are different answers to the
    # operator's question, so the check has to be made where the cards will actually go.
    await _select_group(container, thread_id=_TOPIC)
    _telegram_knows_the_chat(session)

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    assert _sent(session)[0].message_thread_id == _TOPIC


async def test_a_migrated_group_names_the_new_id_so_an_operator_can_act_on_it(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """The verdict that is invisible without this job, and the reason it must name a number.

    Telegram changes the chat id when a basic group is upgraded, and the old id keeps
    answering — so a selected group that migrated is a dead inbox that looks exactly like a
    healthy one. The schema's answer is deliberately passive (the new chat arrives as its own
    row; the old row stays selected and stays dead, because ``support_tickets.group_chat_id``
    already holds the old id and rewriting it would make historical tickets claim their cards
    were posted somewhere they were not). That decision is only RECOVERABLE because this message
    carries the new id, which the operator can get nowhere else.
    """
    # Arrange
    session.failures["GetChat"] = TelegramMigrateToChat(
        method=GetChat(chat_id=_GROUP),
        message="Bad Request: group chat was upgraded to a supergroup chat",
        migrate_to_chat_id=_OTHER_GROUP,
    )

    # Act — no ``Retry``: a migration does not un-happen, so the ladder would only delay the
    # one message that tells somebody what to do.
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    row = await _chat_row(container)
    assert row.verification_error is not None
    assert str(_OTHER_GROUP) in row.verification_error
    assert row.verified_at is None
    # Nothing was posted: there is nowhere to post it.
    assert not _sent(session)


async def test_a_chat_the_bot_is_not_in_is_told_apart_from_one_that_does_not_exist(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — two different afternoons for the operator: one is "add the bot", the other is
    # "you typed the number wrong". A generic string sends them to look at both.
    session.failures["GetChat"] = TelegramForbiddenError(
        method=GetChat(chat_id=_GROUP), message="Forbidden: bot is not a member of the group chat"
    )

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))
    not_a_member = (await _chat_row(container)).verification_error

    # Arrange / Act — the same chat, refused for the other reason.
    session.failures["GetChat"] = _bad_request("Bad Request: chat not found")
    await verify_support_group(_ctx(container, bot), str(_GROUP))
    not_found = (await _chat_row(container)).verification_error

    # Assert
    assert not_a_member is not None and "not in this chat" in not_a_member
    assert not_found is not None and str(_GROUP) in not_found
    assert not_a_member != not_found


async def test_a_group_the_bot_cannot_post_in_is_caught_by_the_send_and_not_by_getchat(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """The case that proves why a send is the verification and ``getChat`` is only the preamble.

    A bot can be a perfectly ordinary member of a group whose permissions forbid it from
    posting. ``getChat`` succeeds there and tells us the title; a job that stopped at ``getChat``
    would write ``verified_at`` on a chat nothing can ever be posted into, which is the exact
    configuration this feature exists to catch.
    """
    # Arrange
    _telegram_knows_the_chat(session)
    session.failures["SendMessage"] = _bad_request(
        "Bad Request: not enough rights to send text messages to the chat"
    )

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert — it got as far as trying, and the verdict is about permission rather than about
    # the chat existing.
    assert [type(call).__name__ for call in session.calls] == ["GetChat", "SendMessage"]
    row = await _chat_row(container)
    assert row.verified_at is None
    assert row.verification_error is not None
    assert "not allowed to post" in row.verification_error


async def test_a_missing_topic_is_reported_as_the_topic_rather_than_as_the_group(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the topic id is a column an OPERATOR chose and a thing somebody else can delete
    # out from under it, so "this group is broken" would send them to fix the wrong thing.
    await _select_group(container, thread_id=_TOPIC)
    _telegram_knows_the_chat(session)
    session.failures["SendMessage"] = _bad_request("Bad Request: message thread not found")

    # Act
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    row = await _chat_row(container)
    assert row.verification_error is not None
    assert str(_TOPIC) in row.verification_error


async def test_a_failed_check_drops_a_proof_that_was_earned_earlier(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """A green badge beside a red reason is the one lie this feature cannot afford.

    The badge is what an operator reads to decide the inbox is fine. What the strictness costs
    is the instant of the last good check, which is recoverable from ``updated_at`` and from the
    audit trail and which nobody has ever needed.
    """
    # Arrange — verified this morning...
    _telegram_knows_the_chat(session)
    await verify_support_group(_ctx(container, bot), str(_GROUP))
    assert (await _chat_row(container)).is_verified

    # Act — ...and thrown out of the group this afternoon.
    session.failures["GetChat"] = TelegramForbiddenError(
        method=GetChat(chat_id=_GROUP), message="Forbidden: bot was kicked from the supergroup chat"
    )
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    row = await _chat_row(container)
    assert row.verified_at is None
    assert row.verification_error is not None


async def test_a_flood_wait_asks_for_another_attempt_and_records_only_on_the_last(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """The one failure kind where waiting helps, and the one that must still end in a verdict.

    Recording on the FINAL attempt rather than dropping it is deliberate: leaving yesterday's
    badge standing after a check nobody could run shows an operator a proof we no longer hold.
    """
    # Arrange
    _telegram_knows_the_chat(session)
    session.failures["SendMessage"] = TelegramRetryAfter(
        method=SendMessage(chat_id=_GROUP, text="x"), message="Too Many Requests", retry_after=7
    )

    # Act / Assert — another attempt is asked for...
    with pytest.raises(Retry):
        await verify_support_group(_ctx(container, bot, job_try=1), str(_GROUP))
    assert (await _chat_row(container)).verification_error is None

    # ...and the last permitted one gives up quietly rather than raising a ``Retry`` ARQ would
    # discard with nobody told, leaving a verdict an operator can see.
    await verify_support_group(_ctx(container, bot, job_try=SUPPORT_VERIFY_MAX_TRIES), str(_GROUP))
    row = await _chat_row(container)
    assert row.verification_error is not None
    assert row.verified_at is None


async def test_a_chat_that_is_no_longer_in_the_directory_writes_nothing_and_creates_nothing(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — a stale enqueue against a row somebody deleted. Re-creating it would resurrect
    # a chat an operator removed on purpose, with whatever partial information this job holds.
    directory = SqlBotChats(container.require_session_factory())

    # Act
    await verify_support_group(_ctx(container, bot), str(_UNKNOWN_GROUP))

    # Assert — nothing was said to Telegram and no row appeared.
    assert not session.calls
    found = await directory.load_chat(_UNKNOWN_GROUP)
    assert is_ok(found) and found.value is None


async def test_the_verdict_is_about_the_chat_it_was_handed_not_the_one_selected_now(
    container: AppContainer, bot: Bot, session: RecordingSession
) -> None:
    """An operator who selects, reconsiders and re-selects gets two honest verdicts.

    Verification is a fact about a CHAT and ``bot_chats`` stores it per chat, so a job that
    refused to answer about a room that had stopped being selected in the second between the
    enqueue and the run would leave that room's row permanently unchecked.
    """
    # Arrange
    _telegram_knows_the_chat(session)
    await _select_group(container, _OTHER_GROUP)

    # Act — the job is still about ``_GROUP``.
    await verify_support_group(_ctx(container, bot), str(_GROUP))

    # Assert
    checked = await _chat_row(container, _GROUP)
    assert checked.is_verified
    assert not checked.is_support_group
    assert not (await _chat_row(container, _OTHER_GROUP)).is_verified


@pytest.mark.parametrize(
    ("failure", "is_retryable"),
    [
        (
            TelegramMigrateToChat(
                method=GetChat(chat_id=_GROUP), message="upgraded", migrate_to_chat_id=_OTHER_GROUP
            ),
            False,
        ),
        (TelegramForbiddenError(method=GetChat(chat_id=_GROUP), message="Forbidden"), False),
        (TelegramBadRequest(method=GetChat(chat_id=_GROUP), message="chat not found"), False),
        (
            TelegramBadRequest(method=GetChat(chat_id=_GROUP), message="CHAT_WRITE_FORBIDDEN"),
            False,
        ),
        (TelegramBadRequest(method=GetChat(chat_id=_GROUP), message="something new"), False),
        (
            TelegramRetryAfter(
                method=GetChat(chat_id=_GROUP), message="Too Many Requests", retry_after=3
            ),
            True,
        ),
        (TelegramServerError(method=GetChat(chat_id=_GROUP), message="Bad Gateway"), True),
        (TelegramNetworkError(method=GetChat(chat_id=_GROUP), message="timed out"), True),
    ],
    ids=[
        "migrated",
        "not_a_member",
        "chat_not_found",
        "cannot_post",
        "unrecognised",
        "flood_wait",
        "server_error",
        "network_error",
    ],
)
def test_only_failures_about_telegram_are_retryable(
    failure: TelegramBadRequest, is_retryable: bool
) -> None:
    """Facts about the ROOM are terminal; facts about Telegram or about us are not.

    The unrecognised tail is the interesting row: it is TERMINAL and carries Telegram's own
    description. An unclassified 400 is still a refusal of this specific chat, and a ladder
    would only delay a message that is already as informative as we can make it.
    """
    # Act
    verdict = verification_failure_for(failure, chat_id=_GROUP, thread_id=None)

    # Assert — and every verdict says SOMETHING, because a blank one is refused by the writer
    # and would render as a red row with nothing to act on.
    assert verdict.is_retryable is is_retryable
    assert verdict.message.strip()
    assert verdict.reason


def test_a_verdict_never_leaks_an_exception_repr_into_the_operators_column() -> None:
    # Arrange — a vendor traceback in a list row is the shape of a failure nobody reads. The
    # four named verdicts are prose; only the unrecognised tail quotes Telegram, and it quotes
    # Telegram's own description rather than the exception object.
    named = verification_failure_for(
        TelegramForbiddenError(method=GetChat(chat_id=_GROUP), message="Forbidden: kicked"),
        chat_id=_GROUP,
        thread_id=None,
    )

    # Assert
    assert "TelegramForbiddenError" not in named.message
    assert "Forbidden" not in named.message


async def test_a_queued_id_that_is_not_a_chat_id_raises_rather_than_doing_nothing(
    container: AppContainer, bot: Bot
) -> None:
    # Arrange / Act / Assert — a broken enqueue seam is not a runtime condition a retry could
    # recover from, and swallowing it would turn one bug into a job that silently does nothing
    # for the life of the deployment. ``True`` is the pointed case and is why the guard is not
    # a bare ``isinstance(value, int)``: ``bool`` IS an ``int`` subclass, and read as a chat id
    # it would be ``1`` — a POSITIVE id, which is a private chat and the one thing ``bot_chats``
    # is shaped to make unrepresentable. It is also the only line here that has to defeat the
    # type checker to be written, which is the shape of a payload only a broken seam can send.
    with pytest.raises(PipelineError):
        await verify_support_group(_ctx(container, bot), True)  # type: ignore[arg-type]
    with pytest.raises(PipelineError):
        await verify_support_group(_ctx(container, bot), "not a number")
