"""Test doubles for the bot layer. Nothing here touches the network.

The Bot is real — a real ``aiogram.Bot`` with a real router tree — but its *session* is
replaced, so every outgoing call is recorded instead of sent and canned replies come back
synthetically. That is deliberate: the wizard is exercised by feeding real ``Update``
objects through a real ``Dispatcher`` and pressing the callback data the real keyboards
produced, which is the only way a routing or FSM bug actually shows up in a test.

Three things the fake session has to do that a canned ``Message`` alone cannot, each closing a
failure that would otherwise be silent:

* **Hold a reply keyboard.** ``Message.reply_markup`` is typed ``InlineKeyboardMarkup | None``,
  so the persistent main menu cannot travel on the canned reply at all — it is read off the
  recorded outgoing call by :func:`last_reply_keyboard` instead.
* **Answer a method with something other than a ``Message``.** ``get_user_profile_photos`` and
  ``get_file`` return their own types, and a ``Message`` in their place has no ``total_count``
  and no ``file_path`` — which the best-effort avatar fetch swallows, so the bug arrives as a
  missing face and never as a red test. :attr:`RecordingSession.responses` is that seam.
* **Serve bytes.** ``stream_content`` used to yield ``b""`` unconditionally, so an avatar
  download "succeeded" with nothing in it. :attr:`RecordingSession.files` is that seam, and
  :func:`arm_avatar` wires all three hops together so no test arms only two.

``FakeProfiles`` is the in-memory ``UserProfileStore`` the whole suite runs on, and it starts
EMPTY on purpose — see its docstring, and the ``profiles`` fixture below.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4, uuid5

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    File,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    ReplyKeyboardMarkup,
    Update,
    User,
    UserProfilePhotos,
)

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.checkout import Plan, PlanState, Purchase, PurchaseRequest
from bayram.config import Settings
from bayram.contracts import (
    Brief,
    Language,
    LyricDraft,
    LyricSection,
    Order,
    Result,
    SpokenScript,
    VoiceDescriptor,
    err,
    ok,
)
from bayram.entitlements import CreditBalance
from bayram.errors import BayramError, PaymentError, PipelineError
from bayram.user_profiles import AVATAR_MIME, UserProfile
from tests.conftest import recipient_of

BOT_TOKEN = "42:AAF-test-token-value-not-a-real-one"
BOT_ID = 42
CHAT_ID = 1_000_777
USER_ID = 1_000_777
FIXED_MOMENT = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


class RecordingSession(BaseSession):
    """Records every outgoing call and answers with a plausible canned response."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.failures: dict[str, Exception] = {}
        #: Failures that fire ONCE and then clear themselves, by aiogram method class name.
        #:
        #: :attr:`failures` raises for every call of a method name, which cannot express the
        #: shape a redraw-then-present path actually has: the FIRST ``EditMessageText`` is
        #: refused ("message is not modified") and the SECOND must succeed, because it is
        #: drawing a genuinely different screen into the same message. Registered here, the
        #: entry is popped as it is raised, so a test can say "this one edit fails" without
        #: reaching for a counting side effect or a mid-flight mutation of :attr:`failures`.
        self.failures_once: dict[str, Exception] = {}
        #: The calls that were not refused — i.e. the ones that actually reached the chat.
        #:
        #: :attr:`calls` records a method BEFORE the injected failure is raised, which is what
        #: makes "the handler tried this" assertable. It is the wrong list for "the customer
        #: saw this": an ``EditMessageText`` Telegram answered 400 to changed nothing on the
        #: customer's screen, so a test asserting over :attr:`calls` about what is on screen
        #: reads a refused draw as a delivered one — and would, for instance, find a live
        #: price button in a markup that was never drawn.
        self.delivered: list[TelegramMethod[Any]] = []
        #: Canned answers by aiogram METHOD CLASS NAME — ``"GetUserProfilePhotos"``, ``"GetFile"``.
        #: Consulted before :meth:`_message_for`, which answers every method with a ``Message``
        #: and therefore hands ``get_user_profile_photos()`` an object with no ``total_count``
        #: and ``get_file()`` one with no ``file_path``. Both read, at the call site, as an
        #: avatar that quietly is not there: the fetcher is best-effort and swallows what it
        #: cannot use, so the ``AttributeError`` would surface as a silently absent face rather
        #: than as a failing test.
        self.responses: dict[str, Any] = {}
        #: File bytes by Telegram ``file_path``. ``Bot.download_file`` builds
        #: ``https://api.telegram.org/file/bot<token>/<file_path>`` and streams it through
        #: :meth:`stream_content`, whose default yields ``b""`` — so an avatar download
        #: "succeeds" with zero bytes and every assertion about the stored image passes on
        #: emptiness.
        self.files: dict[str, bytes] = {}
        self._next_message_id = 100

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        once = self.failures_once.pop(name, None)
        if once is not None:
            raise once
        failure = self.failures.get(name)
        if failure is not None:
            raise failure
        self.delivered.append(method)
        if name in self.responses:
            return self.responses[name]
        if name == "AnswerCallbackQuery":
            return True
        return self._message_for(method)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - the signature is aiogram's, not ours
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Serve :attr:`files` by the ``file_path`` tail of the download URL.

        ``Bot.download_file`` composes ``session.api.file_url(token, file_path)``, so the
        registered key is the bare ``file_path`` and the match is a suffix — a test registers
        what Telegram would have handed it in ``File.file_path`` and never has to know how the
        token is spliced into the URL.

        An unregistered path still yields ``b""`` rather than raising, because that is what an
        expired ``file_path`` does in production and the avatar fetch is best-effort. The
        consequence is the reason :attr:`files` exists at all: a test that wants bytes must
        register them, and a fetch of nothing must therefore store nothing — the old
        unconditional ``yield b""`` made "the avatar downloaded fine" and "the avatar is zero
        bytes long" the same green result.
        """
        for file_path, payload in self.files.items():
            if url.endswith(file_path):
                yield payload
                return
        yield b""

    def _message_for(self, method: TelegramMethod[Any]) -> Message:
        """The canned reply Telegram would send back.

        ``reply_markup`` is copied through only when it is an INLINE markup, because
        ``Message.reply_markup`` is typed ``InlineKeyboardMarkup | None`` and pydantic rejects
        a ``ReplyKeyboardMarkup`` outright — verified in-process on aiogram 3.31.0. Copying it
        blindly is what this used to do, so the first handler to attach the persistent main
        menu died inside the fake session with a validation error naming neither the router nor
        the handler that sent it.

        The reply keyboard is not lost: the outgoing method is already in :attr:`calls`, and
        :func:`reply_buttons` reads it from there, which is the honest place — a reply keyboard
        is chat-level state that outlives the message it rode in on, not a property of one
        message.
        """
        self._next_message_id += 1
        markup = getattr(method, "reply_markup", None)
        return Message(
            message_id=getattr(method, "message_id", None) or self._next_message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
            text=getattr(method, "text", None),
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        )

    # -- assertions helpers -------------------------------------------------
    def named(self, name: str) -> tuple[TelegramMethod[Any], ...]:
        return tuple(call for call in self.calls if type(call).__name__ == name)

    def last_named(self, name: str) -> Any:
        found = self.named(name)
        assert found, f"no {name} call was made; calls were {self.call_names}"
        return found[-1]

    @property
    def call_names(self) -> tuple[str, ...]:
        return tuple(type(call).__name__ for call in self.calls)

    @property
    def last_screen(self) -> Any:
        """The most recent call that put text on the screen, sent or edited."""
        screens = [
            call for call in self.calls if type(call).__name__ in {"SendMessage", "EditMessageText"}
        ]
        assert screens, f"nothing was put on screen; calls were {self.call_names}"
        return screens[-1]

    def delivered_named(self, name: str) -> tuple[TelegramMethod[Any], ...]:
        """The calls of this kind that Telegram accepted. See :attr:`delivered`."""
        return tuple(call for call in self.delivered if type(call).__name__ == name)

    def clear(self) -> None:
        self.calls.clear()
        self.delivered.clear()


class RecordingSubmitter:
    """A fake job queue. Records what it was handed; can be told to fail.

    It refuses an order id it has already accepted, the way the real one does: production
    persists before it enqueues, so a duplicate id hits the ``orders`` primary key and
    ``db.guard`` turns that into a non-retryable ``Err``. A fake that accepted duplicates
    made a double tap look harmless in a test and buy two songs in production.
    """

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.submitted: list[tuple[Order, int, int]] = []
        self.failure = failure

    @property
    def submitted_ids(self) -> tuple[str, ...]:
        return tuple(str(order.id) for order, _chat, _message in self.submitted)

    async def submit(self, order: Order, *, chat_id: int, progress_message_id: int) -> Result[str]:
        from bayram.contracts import err

        if self.failure is not None:
            return err(PipelineError("queue unavailable", cause=self.failure))
        if str(order.id) in self.submitted_ids:
            return err(PipelineError("order already exists", context={"order_id": str(order.id)}))
        self.submitted.append((order, chat_id, progress_message_id))
        return ok(f"job-{uuid4().hex[:8]}")


#: What the fake writer puts in a verse. Deliberately says nothing about the recipient, so
#: a test asserting on the name is asserting on the hook section and nothing else.
LYRIC_VERSE = "The candles are lit and the table is laid"


def canned_lyrics(brief: Brief, *, take: int) -> LyricDraft:
    """The lyric the fake writer returns on its ``take``-th call.

    ``take`` appears in the title and in the hook, which is what lets a regenerate test
    tell a genuinely new lyric from the previous one merely being re-rendered.

    Only ``recipient.display`` reaches the text. The submitted candidates — the stripped
    and hyphenated spellings sent to the voice vendor — must never appear on a screen, and
    the lyric preview is a screen, so a fake that leaked one would quietly turn that
    invariant's test green for the wrong reason.
    """
    display = recipient_of(brief).display
    return LyricDraft(
        title=f"Take {take} for {display}",
        language=brief.output_language,
        sections=(
            LyricSection(label="verse-1", lines=(LYRIC_VERSE,)),
            LyricSection(
                label="hook",
                lines=(f"{display}, take {take} is for you",),
                is_name_hook=True,
            ),
        ),
        name_display=display,
    )


class RecordingContentWriter:
    """A fake lyric writer. Records the briefs it was asked to write for.

    The wizard now calls a :class:`~bayram.pipeline.ports.ContentWriter` on the customer's
    screen, so the bot tests need one that answers instantly and predictably. Set
    ``failure`` to a typed error and every subsequent call comes back as an ``Err``, which
    is how the "the writer fell over mid-wizard" path is exercised without a vendor.
    """

    def __init__(self, *, failure: BayramError | None = None) -> None:
        self.briefs: list[Brief] = []
        self.failure = failure

    @property
    def calls(self) -> int:
        """How many times a lyric was asked for. One per preview shown."""
        return len(self.briefs)

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.briefs.append(brief)
        if self.failure is not None:
            return err(self.failure)
        return ok(canned_lyrics(brief, take=len(self.briefs)))

    async def write_scripts(
        self,
        brief: Brief,
        lyrics: LyricDraft,
        *,
        voices: tuple[VoiceDescriptor, ...],
        name_submitted: str,
        target_duration_s: float,
    ) -> Result[tuple[SpokenScript, ...]]:
        """Never reached from the bot: spoken greetings are the worker's half of the job."""
        raise AssertionError("the wizard must not ask the writer for spoken scripts")


class DecliningPaymentProvider:
    """Authorises nothing. Exists to prove the gate is actually consulted."""

    name = "declining"

    async def authorize(
        self, *, order_id: Any, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[Any]:
        from bayram.contracts import PaymentAuthorization

        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference="declined",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=False,
            )
        )


#: The plan a :class:`FakePurchases` opens, in days from ``FIXED_MOMENT``. Written out rather
#: than added to the clock at call time so a test that asserts on the date the customer reads
#: is asserting against a decision and not against whatever arithmetic the fake happened to do.
FAKE_PLAN_ENDS_AT: Final[datetime] = datetime(2026, 4, 20, 9, 0, 0, tzinfo=UTC)


class RecordingCheckout:
    """A :class:`~bayram.checkout.CheckoutProvider` that records what it was asked to charge.

    Structurally the same shape as ``StubCheckoutProvider`` — it contacts nothing either —
    and it exists for the one thing the stub cannot express: ``is_paid=False``. A redirect
    rail returns an unpaid receipt every time it STARTS a payment, so that branch is not a
    hypothetical failure but the normal behaviour of the rail this seam was designed for,
    and the handler's refusal to grant against one has to be exercised before that rail
    lands rather than after.

    ``requests`` is what the idempotency-key tests read: a double tap must hand this two
    requests carrying the SAME key, because deduplication is the ledger's job and a provider
    that hid the second call would hide the property under test.

    **``checkout_url`` is what makes it a REDIRECT rail**, and it changes the shape of the
    answer rather than merely adding a field. Set it and every receipt carries a link, and —
    the property the redirect tests actually rest on — the link is IDEMPOTENT ON THE KEY, the
    way ``PaymentIntentOpener.open_intent`` is: one intent per ``idempotency_key``, one
    ``public_ref`` per intent, therefore one URL. A fake that minted a fresh link per CALL
    would make "a second press re-mints the identical key and gets the identical link" pass or
    fail on nothing at all, and a fake that returned one CONSTANT link would make it pass
    vacuously — so the suffix is derived from the key and a different key produces a visibly
    different link.

    With ``checkout_url`` unset the reference is the per-call ``rec-N`` this fake has always
    returned and no link is attached, so every existing test that builds one is byte-identical
    to what it was.
    """

    def __init__(self, *, is_paid: bool = True, checkout_url: str | None = None) -> None:
        self.name = "recording"
        #: Flip to False to make every subsequent charge an unpaid receipt.
        self.is_paid = is_paid
        #: The base of the link an unpaid receipt carries, or ``None`` for an inline rail.
        self.checkout_url = checkout_url
        #: Every request, in order, including replays of one key.
        self.requests: list[PurchaseRequest] = []
        #: Reference minted per IDEMPOTENCY KEY, not per call. See the class docstring.
        self.opened: dict[str, str] = {}

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        self.requests.append(request)
        reference = f"rec-{len(self.requests)}"
        link: str | None = None
        if self.checkout_url is not None:
            reference = self.opened.setdefault(request.idempotency_key, f"ref-{len(self.opened)}")
            link = f"{self.checkout_url}/{reference}"
        return ok(
            Purchase(
                product=request.product,
                provider=self.name,
                reference=reference,
                amount_minor=request.amount_minor,
                currency=request.currency,
                is_paid=self.is_paid,
                checkout_url=link,
            )
        )


class FakePurchases:
    """An in-memory :class:`~bayram.checkout.PurchaseFulfiller`. Idempotent on the key, like the real one.

    The ledger it stands in for deduplicates on a unique index over ``idempotency_key``, and
    that is the property every double-tap assertion in this suite rests on — so this fake
    deduplicates too, by remembering the answer it gave for a key and returning it unchanged.
    A fake that granted twice for one key would make a double tap look harmless in a test and
    charge a customer twice in production, which is the exact shape of the defect
    ``RecordingSubmitter`` was given its own duplicate check for.

    ``grants`` and ``plans`` record EVERY key handed in, replays included. That is the
    distinction the tests need: a double tap must show two entries carrying one key, while a
    deliberate second purchase must show two entries carrying two.

    Failures are INJECTED and returned as ``Err``, never raised. Every method of the port
    returns ``Result`` and none of them raises; a fake that raised would prove the handler
    survives an exception it will never see while proving nothing about the failure it will.
    """

    def __init__(self, *, credits: int = 0, failure: BayramError | None = None) -> None:
        #: The balance this account reads back at. Moved by a fulfilled single song.
        self.credits = credits
        #: Returned by every method while set.
        self.failure = failure
        #: Every ``fulfil_single`` key, in order, replays included.
        self.grants: list[str] = []
        #: Every ``start_plan`` key, in order, replays included.
        self.plans: list[str] = []
        #: The running plan, or ``None``. One at a time, as the real store enforces.
        self.plan: PlanState | None = None
        self._settled: dict[str, int] = {}

    async def fulfil_single(
        self, *, telegram_user_id: int, purchase: Purchase, idempotency_key: str
    ) -> Result[CreditBalance]:
        self.grants.append(idempotency_key)
        if self.failure is not None:
            return err(self.failure)
        if not purchase.is_paid:
            return err(PaymentError("the purchase was not paid"))
        if idempotency_key not in self._settled:
            self.credits += 1
            self._settled[idempotency_key] = self.credits
        return ok(self._balance(telegram_user_id))

    async def start_plan(
        self,
        *,
        telegram_user_id: int,
        purchase: Purchase,
        songs: int,
        days: int,
        idempotency_key: str,
    ) -> Result[PlanState]:
        self.plans.append(idempotency_key)
        if self.failure is not None:
            return err(self.failure)
        if not purchase.is_paid:
            return err(PaymentError("the purchase was not paid"))
        if self.plan is None:
            # One plan at a time, exactly as ``SqlPurchaseLedger.start_plan`` does: a second
            # plan would overwrite an end date the customer has already paid for.
            self.plan = PlanState(
                plan=Plan.STARTER,
                songs_included=songs,
                songs_used=0,
                ends_at=FAKE_PLAN_ENDS_AT,
            )
        return ok(self.plan)

    async def plan_for(self, telegram_user_id: int) -> Result[PlanState | None]:
        if self.failure is not None:
            return err(self.failure)
        return ok(self.plan)

    # -- test-side reads, not part of the port ------------------------------

    def _balance(self, telegram_user_id: int) -> CreditBalance:
        plan = self.plan
        return CreditBalance(
            telegram_user_id=telegram_user_id,
            credits=self.credits,
            in_flight=0,
            is_blocked=False,
            plan_songs_left=0 if plan is None else plan.songs_left,
            plan_ends_at=None if plan is None else plan.ends_at,
        )


#: Namespace for the ``users.id`` this fake derives from a Telegram id.
#:
#: DERIVED rather than random so the same account gets the same UUID in every test, in every
#: run, and — crucially — across a ``forget`` that dropped the row: production keeps the
#: ``users`` row through ``/forget`` (an operator's block must survive a data-subject request),
#: so a fake that minted a fresh id on re-onboarding would let a test assert an ``avatar_key``
#: that production would never rebuild.
_FAKE_USER_ID_NAMESPACE: Final[UUID] = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

#: The language a profile row is born with when something reached :meth:`FakeProfiles.record_contact`
#: without a language choice ever being recorded. Named rather than inlined for the same reason
#: ``bayram.db.credits`` names its own: "the language a row is born with" must have exactly one
#: spelling, or the fallback drifts from the production one and the fake starts answering a
#: question the real store answers differently.
FAKE_BIRTH_LANGUAGE: Final[Language] = Language.UZ_LATN

#: The phone number ``seed`` stores, in the canonical E.164 spelling ``normalise_phone`` emits.
#: Uzbek because that is the market, and long enough that a mask which keeps a fixed ``+998``
#: head in the clear looks obviously wrong when a test prints it.
SEEDED_PHONE: Final[str] = "+998901234542"


def fake_user_id(telegram_user_id: int) -> UUID:
    """The ``users.id`` :class:`FakeProfiles` gives an account. Stable, and a test may recompute it.

    Exported rather than kept private because ``avatar_key(profile.user_id)`` is what the admin
    route rebuilds server-side, so a test that wants to assert on the stored object's key needs
    the same id the store handed the bot — and a test that reached into ``profiles.rows`` for it
    would be asserting against whatever the fake happened to do rather than against a decision.
    """
    return uuid5(_FAKE_USER_ID_NAMESPACE, str(telegram_user_id))


def _fresh_profile(telegram_user_id: int, ui_language: Language) -> UserProfile:
    """The row an account is BORN with: a language and nothing else.

    Every optional field is spelled out rather than defaulted, because
    :class:`~bayram.user_profiles.UserProfile` has no defaults and must not grow any — a default
    would let a field added to the port slip into every fake row unnoticed, and the fake would
    then agree with a store that had never learned to write it.
    """
    return UserProfile(
        user_id=fake_user_id(telegram_user_id),
        telegram_user_id=telegram_user_id,
        ui_language=ui_language,
        phone_e164=None,
        telegram_username=None,
        first_name=None,
        last_name=None,
        avatar_file_unique_id=None,
        avatar_mime=None,
        avatar_stored_at=None,
        language_chosen_at=FIXED_MOMENT,
        phone_shared_at=None,
        onboarded_at=None,
        created_at=FIXED_MOMENT,
        updated_at=FIXED_MOMENT,
    )


class FakeProfiles:
    """An in-memory :class:`~bayram.user_profiles.UserProfileStore`. Starts EMPTY.

    Empty is the interesting state and therefore the default: a store that came pre-populated
    would make every walker skip onboarding, which is the fail-open path the suite already
    over-covers and the one that ships to nobody. :meth:`record_language` is what creates the
    row, exactly as ``SqlUserProfiles`` does, so :meth:`get` answering ``None`` before it means
    "this person has never spoken to us" and not "the store is unwired". There is no backfill
    (D11), so ``None`` is also the honest answer for the entire installed base on deploy day.

    Failures are INJECTED, never raised: the port is a ``Result`` seam and a fake that raised
    would prove the handlers survive an exception they will never see while proving nothing
    about the ``Err`` they will. ``failure`` is checked first thing in every method, including
    the reads, because C1-5's fail-open branch is decided on an ``Err`` from :meth:`get` and a
    fake that could only fail its writes could not drive it.

    Every timestamp is ``FIXED_MOMENT``. A fake with a moving clock would let a test that meant
    to assert "the row records WHEN the number was shared" pass on any two distinct instants,
    and the wizard's own clock fixture is already frozen there.
    """

    def __init__(self, *, failure: BayramError | None = None) -> None:
        self.rows: dict[int, UserProfile] = {}
        #: Returned by every method while set. Drives the C1-5 fail-open assertions.
        self.failure = failure
        #: ``(telegram_user_id, mime, file_unique_id, len(image))`` per stored avatar.
        #:
        #: Appended to for EVERY call, including the ones whose bytes are then discarded, so a
        #: test can assert what the fetcher actually sent. The row is only stamped when the
        #: call would have been stored for real — see :meth:`record_avatar`.
        self.avatars: list[tuple[int, str, str, int]] = []
        #: Every id ``forget`` was called with, in order, including ones with no row.
        self.forgotten: list[int] = []

    # -- test-side seeding, not part of the port ----------------------------
    def seed(self, telegram_user_id: int, **overrides: Any) -> UserProfile:
        """A fully ONBOARDED row, so "a returning customer" is one line in a test.

        Fully onboarded — ``phone_e164`` and ``onboarded_at`` both set — because a half-seeded
        row is the one shape no production path can produce: the contact write sets both in the
        same statement. A test that wants the language-only intermediate calls
        :meth:`record_language` instead, which is what the customer's tap does.

        ``ui_language`` defaults to :attr:`~bayram.contracts.Language.EN` and NOT to the product's
        Uzbek default, deliberately: English is the language the assertions in this suite are
        written in, and a default that matched ``settings.default_ui_language`` would let a
        screen rendered from the fallback and a screen rendered from the stored choice look
        identical — which is precisely the bug C1-5's fail-open path can introduce.

        ``**overrides`` is a plain kwargs splat onto :class:`~bayram.user_profiles.UserProfile`'s
        own field names, so a misspelled field is a ``TypeError`` at the call site rather than
        a silently ignored intention.
        """
        fields: dict[str, Any] = {
            "user_id": fake_user_id(telegram_user_id),
            "telegram_user_id": telegram_user_id,
            "ui_language": Language.EN,
            "phone_e164": SEEDED_PHONE,
            "telegram_username": "dilnoza",
            "first_name": "Dilnoza",
            "last_name": "Yoʻldosheva",
            "avatar_file_unique_id": None,
            "avatar_mime": None,
            "avatar_stored_at": None,
            "language_chosen_at": FIXED_MOMENT,
            "phone_shared_at": FIXED_MOMENT,
            "onboarded_at": FIXED_MOMENT,
            "created_at": FIXED_MOMENT,
            "updated_at": FIXED_MOMENT,
        }
        fields.update(overrides)
        profile = UserProfile(**fields)
        self.rows[telegram_user_id] = profile
        return profile

    # -- the port ----------------------------------------------------------
    async def get(self, telegram_user_id: int) -> Result[UserProfile | None]:
        if self.failure is not None:
            return err(self.failure)
        return ok(self.rows.get(telegram_user_id))

    async def record_language(
        self, telegram_user_id: int, *, ui_language: Language
    ) -> Result[UserProfile]:
        """Create or refresh the row, exactly as the real store's upsert does.

        It creates the row because it is the FIRST thing that ever happens to an account: the
        language question is the first screen a new customer sees, so a fake that required a
        row to exist could not drive onboarding at all.
        """
        if self.failure is not None:
            return err(self.failure)
        existing = self.rows.get(telegram_user_id)
        profile = (
            _fresh_profile(telegram_user_id, ui_language)
            if existing is None
            else replace(
                existing,
                ui_language=ui_language,
                language_chosen_at=FIXED_MOMENT,
                updated_at=FIXED_MOMENT,
            )
        )
        self.rows[telegram_user_id] = profile
        return ok(profile)

    async def record_contact(
        self,
        telegram_user_id: int,
        *,
        phone_e164: str,
        telegram_username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> Result[UserProfile]:
        """Store the number and the identity, and make :attr:`UserProfile.is_onboarded` true.

        Trusts what it is handed, like the real seam: the caller has already refused a
        forwarded contact card and already run ``normalise_phone``. Re-validating here would
        put a second definition of "a valid number" in the tree, and a fake that rejected what
        production stores would make a green test a lie in the more dangerous direction.

        It creates the row when there is none, stamping :data:`FAKE_BIRTH_LANGUAGE`. No
        onboarding path reaches this without a language choice first, but a test may seed only
        half of one, and a ``KeyError`` there would blame the store for the test's arrangement.
        """
        if self.failure is not None:
            return err(self.failure)
        existing = self.rows.get(telegram_user_id)
        base = existing or _fresh_profile(telegram_user_id, FAKE_BIRTH_LANGUAGE)
        profile = replace(
            base,
            phone_e164=phone_e164,
            telegram_username=telegram_username,
            first_name=first_name,
            last_name=last_name,
            phone_shared_at=FIXED_MOMENT,
            onboarded_at=base.onboarded_at or FIXED_MOMENT,
            updated_at=FIXED_MOMENT,
        )
        self.rows[telegram_user_id] = profile
        return ok(profile)

    async def record_avatar(
        self, telegram_user_id: int, *, image: bytes, mime: str, file_unique_id: str
    ) -> Result[None]:
        """Best effort, and ``Ok(None)`` for every reason it did not store anything.

        The attempt is always recorded on :attr:`avatars` and the ROW is stamped only when the
        real store would have stored the bytes — there is a profile row and the MIME is
        :data:`~bayram.user_profiles.AVATAR_MIME`. Splitting the two is what lets a test assert
        both halves of the production contract: that the fetcher sends exactly the one content
        type the tree defines, and that anything else is discarded rather than served later
        under a guessed content type.

        It never answers ``Err`` for "there was nothing to store", because a failed avatar is
        not a failed onboarding and a caller forced to distinguish these would grow a branch
        per case at the one step where the bot must simply move on.
        """
        if self.failure is not None:
            return err(self.failure)
        self.avatars.append((telegram_user_id, mime, file_unique_id, len(image)))
        existing = self.rows.get(telegram_user_id)
        if existing is None or mime != AVATAR_MIME:
            return ok(None)
        self.rows[telegram_user_id] = replace(
            existing,
            avatar_file_unique_id=file_unique_id,
            avatar_mime=mime,
            avatar_stored_at=FIXED_MOMENT,
            updated_at=FIXED_MOMENT,
        )
        return ok(None)

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """Delete the row and the recorded avatar. Idempotent, and total.

        An account with no row is a successful erasure, not a failure — ``handle_forget``'s own
        docstring relies on that, and PD-3 makes the ABSENCE of the row the erasure record, so
        there is nothing to distinguish "purged" from "never onboarded" and nothing should try.
        The avatar entries go too: bytes that outlived the row would be exactly the leak the
        unconditional object delete in the real store exists to prevent.
        """
        if self.failure is not None:
            return err(self.failure)
        self.forgotten.append(telegram_user_id)
        self.rows.pop(telegram_user_id, None)
        self.avatars = [entry for entry in self.avatars if entry[0] != telegram_user_id]
        return ok(None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    return Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def submitter() -> RecordingSubmitter:
    return RecordingSubmitter()


@pytest.fixture
def content() -> RecordingContentWriter:
    return RecordingContentWriter()


@pytest.fixture
def clock() -> Callable[[], datetime]:
    return lambda: FIXED_MOMENT


@pytest.fixture
def purchases() -> FakePurchases:
    """A purchase store with an empty account and no plan.

    Deliberately NOT wired into the shared ``deps`` fixture. ``BotDeps.purchases`` unset is
    what "this deployment does not sell" means, and every other module in this suite
    depends on it staying unset: with a store wired by default, every Confirm screen in the
    suite would render as a paywall and the byte-identical-screen property that the whole
    checkout was designed around would be asserted by nothing.
    """
    return FakePurchases()


@pytest.fixture
def profiles() -> FakeProfiles:
    """The shared profile store. EMPTY, so the wizard is reached THROUGH onboarding.

    A module that drives PAST onboarding — one that sets a ``Wizard.*`` state by hand rather
    than walking to it — overrides this fixture with a seeded one, because the onboarding
    catch-all would otherwise claim its first update. That is the rule in both directions:
    walk through onboarding ⇒ empty store; start behind it ⇒ seeded store.
    """
    return FakeProfiles()


@pytest.fixture
def deps(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    clock: Callable[[], datetime],
    profiles: FakeProfiles,
) -> BotDeps:
    """The shared dependencies. ``profiles`` is wired, and that is a decision (C1-4 / C2-1).

    With ``profiles=None`` the fail-open branch is the only path the suite exercises, so the
    onboarding gate, the language question and the contact request would ship untested while
    every test stayed green — the failure this whole package exists to prevent. The three
    walkers therefore drive the REAL onboarding screens.

    The two cases that genuinely need no store — ``profiles=None`` and an ``Err``-injecting
    store — build their own ``BotDeps`` in ``test_onboarding.py``, where the fail-open
    behaviour is the subject rather than the accident.

    ``profiles`` is passed LAST, matching the trailing-and-defaulted field on ``BotDeps``: the
    field is trailing precisely so the thirty other ``BotDeps(`` sites in this suite keep
    compiling without an edit, and a fixture that reordered it would hide a positional
    construction that no longer means what it says.
    """
    return BotDeps(
        settings=settings, submitter=submitter, content=content, clock=clock, profiles=profiles
    )


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def dispatcher(deps: BotDeps, storage: MemoryStorage) -> Dispatcher:
    return build_dispatcher(deps, storage=storage)


@pytest.fixture
def state(storage: MemoryStorage) -> FSMContext:
    key = StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    return FSMContext(storage=storage, key=key)


# ---------------------------------------------------------------------------
# Update builders
# ---------------------------------------------------------------------------
_update_id = 0


def _next_update_id() -> int:
    global _update_id
    _update_id += 1
    return _update_id


def make_message(text: str, *, message_id: int = 10) -> Message:
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        text=text,
    )


def make_non_text_message(*, message_id: int = 11) -> Message:
    """A message with no text at all — a sticker, a voice note, a photo."""
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
    )


def make_contact_message(
    *,
    phone_number: str = SEEDED_PHONE,
    contact_user_id: int | None = USER_ID,
    first_name: str = "Dilnoza",
    last_name: str | None = "Yoʻldosheva",
    message_id: int = 12,
) -> Message:
    """A ``Message`` carrying a ``Contact``, the way the share-contact button sends one.

    There is no Telegram round trip to fake here and none is faked: ``Contact`` is a field on
    the INBOUND message, so the builder constructs it directly.

    ``contact_user_id`` is the whole point of the builder. Telegram sets ``Contact.user_id``
    only when the contact IS a Telegram account, and it is the only field that tells the
    customer's own number from one they picked out of their address book — a forwarded contact
    arrives with the same phone shape, the same button and a different (or absent) ``user_id``.
    Pass ``None`` or another id to drive ``onboarding.contact.foreign``; storing a stranger's
    number as this customer's is a song delivered to the wrong person.
    """
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        contact=Contact(
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            user_id=contact_user_id,
        ),
    )


def make_callback(data: str, *, message_id: int = 20) -> CallbackQuery:
    return CallbackQuery(
        id=f"cb-{message_id}-{data}",
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        chat_instance="chat-instance",
        data=data,
        message=Message(
            message_id=message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
            text="previous screen",
        ),
    )


def message_update(text: str) -> Update:
    return Update(update_id=_next_update_id(), message=make_message(text))


def callback_update(data: str) -> Update:
    return Update(update_id=_next_update_id(), callback_query=make_callback(data))


def contact_update(**kwargs: Any) -> Update:
    return Update(update_id=_next_update_id(), message=make_contact_message(**kwargs))


# ---------------------------------------------------------------------------
# The avatar fetch — three hops, written down once
# ---------------------------------------------------------------------------
#: The ``file_path`` Telegram hands back for the photo this harness serves. The bytes are keyed
#: on it in :attr:`RecordingSession.files`, because that is the key ``Bot.download_file``
#: splices into the URL it then streams.
AVATAR_FILE_PATH: Final[str] = "photos/file_0.jpg"

#: A JPEG's first bytes and then some filler. Not a valid image, and it does not need to be —
#: nothing in this tree decodes it — but it starts with the real ``\xff\xd8\xff`` SOI marker so
#: that a future sniffer would agree with :data:`~bayram.user_profiles.AVATAR_MIME` rather than
#: quietly disagree with it.
AVATAR_BYTES: Final[bytes] = b"\xff\xd8\xff\xe0jpeg-ish"


def profile_photos(*, total_count: int = 1) -> UserProfilePhotos:
    """One photo, as an ASCENDING size ladder.

    ``UserProfilePhotos.photos`` is ``list[list[PhotoSize]]``: the outer list is one entry per
    PHOTO and the inner list is that photo's size ladder. A fake that flattened it would let
    ``photos[0]`` — the ladder, not a size — read as a ``PhotoSize`` and hide the exact indexing
    bug this exists to catch (C0-15). The ladder is ascending because the fetcher takes the
    SMALLEST size, so a test that asserts on ``file_unique_id`` is asserting that it took the
    cheap one and not merely the first.

    ``total_count=0`` is the "this customer has no profile photo, or hides it from us" case, and
    the ladder is still returned — Telegram is not obliged to keep the two consistent, and a
    fetcher that trusted the list length instead of ``total_count`` must fail here.
    """
    ladder = [
        PhotoSize(
            file_id="small", file_unique_id="u-small", width=320, height=320, file_size=9_000
        ),
        PhotoSize(file_id="big", file_unique_id="u-big", width=640, height=640, file_size=40_000),
    ]
    return UserProfilePhotos(total_count=total_count, photos=[ladder])


def arm_avatar(session: RecordingSession, *, image: bytes = AVATAR_BYTES) -> None:
    """Wire the three hops an avatar fetch makes: the photo list, the file, the bytes.

    All three or none. Arming two of them is the shape that produced a silent zero-byte avatar
    before this harness existed — ``get_file`` answered a canned ``Message`` with no
    ``file_path``, or ``stream_content`` yielded ``b""`` — and every assertion about the stored
    image then passed on emptiness.
    """
    session.responses["GetUserProfilePhotos"] = profile_photos()
    session.responses["GetFile"] = File(
        file_id="small",
        file_unique_id="u-small",
        file_size=len(image),
        file_path=AVATAR_FILE_PATH,
    )
    session.files[AVATAR_FILE_PATH] = image


# ---------------------------------------------------------------------------
# Keyboard readers — a test presses the button the user would press
# ---------------------------------------------------------------------------
def buttons(
    markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
) -> tuple[tuple[str, str], ...]:
    """Every ``(text, callback_data)`` pair in an INLINE markup, flattened.

    A ``ReplyKeyboardMarkup`` is refused by name rather than read as empty. Returning ``()``
    would turn every ``assert data in buttons(...)`` into a failure that blames the handler and
    every ``assert data not in buttons(...)`` into a pass that tests nothing — which is exactly
    the rot ``test_locale_contract.py`` was written to catch. Use :func:`reply_buttons`.

    The PARAMETER is annotated with the whole union even though the body accepts only half of
    it, and that is deliberate (CONTRACTS §5). ``Screen.markup`` widens to
    ``InlineKeyboardMarkup | ReplyKeyboardMarkup | None`` and the live call sites in
    ``test_screens.py`` pass ``screen.markup`` straight in. A narrow annotation would make
    ``mypy --strict`` over ``tests`` fail at every one of them and invite a ``cast`` at each;
    widening the annotation and keeping the assertion moves the refusal from six suppressions
    to one loud runtime message that names the right helper.
    """
    if markup is None:
        return ()
    assert isinstance(markup, InlineKeyboardMarkup), (
        f"{type(markup).__name__} is not an inline markup; read it with reply_buttons()"
    )
    return tuple(
        (button.text, button.callback_data or "")
        for row in markup.inline_keyboard
        for button in row
    )


def data_with_prefix(markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None, prefix: str) -> str:
    """The callback data of the first button whose payload starts with ``prefix``."""
    for _, data in buttons(markup):
        if data.startswith(prefix):
            return data
    raise AssertionError(f"no button with prefix {prefix!r} in {buttons(markup)}")


def reply_buttons(markup: ReplyKeyboardMarkup | None) -> tuple[tuple[str, ...], ...]:
    """The reply keyboard's labels, ROW BY ROW.

    Rows are preserved rather than flattened because the menu's layout is a contract —
    ``main_menu_keyboard`` promises Generate | Balance above Settings | Help — and a flattened
    reader could not tell a two-by-two grid from a column of four, which is the difference
    between a keyboard that fits a phone and one that does not.
    """
    if markup is None:
        return ()
    return tuple(tuple(button.text for button in row) for row in markup.keyboard)


def requests_contact(markup: ReplyKeyboardMarkup | None) -> bool:
    """Whether any button on this reply keyboard asks Telegram for the sender's number.

    ``request_contact=True`` is the only thing that makes the share-contact button share a
    contact. A button with the right label and the flag missing looks correct in every
    screenshot and in every label assertion, and sends its own text instead — leaving the
    customer tapping it for ever on the one step that gates the whole product.
    """
    if markup is None:
        return False
    return any(button.request_contact is True for row in markup.keyboard for button in row)


def last_reply_keyboard(session: RecordingSession) -> ReplyKeyboardMarkup | None:
    """The most recent REPLY markup the bot attached to anything, or ``None``.

    Read from ``session.calls`` and NOT from ``session.last_screen.reply_markup``, because the
    canned ``Message`` deliberately carries inline markups only — see
    :meth:`RecordingSession._message_for`, where pydantic refuses the other kind outright.
    Reading the outgoing method is also the truthful place: a reply keyboard is chat-level
    state that persists until it is replaced, so "the last one sent" is the one on the
    customer's screen.
    """
    for call in reversed(session.calls):
        markup = getattr(call, "reply_markup", None)
        if isinstance(markup, ReplyKeyboardMarkup):
            return markup
    return None
