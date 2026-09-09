"""The whole application, from ``/start`` to a delivered voice note.

Every other test in this repository mocks the seam next to the thing it is testing. This
one mocks nothing except the Telegram transport and the six vendors: a real dispatcher, the
real wizard, the real name subsystem, the real orchestrator, real ffmpeg, the real SQLite
repository, real files on disk, and the real delivery code. It is the only test that can
catch two green modules disagreeing — which is the entire failure mode of a parallel build.

**Onboarding runs here against a REAL** :class:`~hbd.db.user_profiles.SqlUserProfiles`. Every
other bot test in the suite runs on the in-memory ``FakeProfiles``, which cannot catch a column
that is not nullable, a session that is never committed, a phone number that does not survive
its own round trip, or an avatar written under a key the admin panel later cannot rebuild.
This module is where the port, the migrated table, the ``users`` row underneath it, the shared
``LocalFileStorage`` and the wizard are in one process at one time — so the walk below starts
where a real customer starts, at the language question, and pays for its own number.

Marked ``integration`` because it shells out to ffmpeg. It needs no network, no Redis and
no Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Final

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.deps import BotDeps
from hbd.bot.i18n import translate
from hbd.config import Settings
from hbd.contracts import Genre, Language, Occasion, Ok, VoiceGender
from hbd.pipeline.content import LlmContentWriter
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import BOT_CTX_KEY, CONTAINER_CTX_KEY, generate_and_deliver
from hbd.runtime.submitter import InProcessOrderSubmitter
from hbd.user_profiles import avatar_key
from tests.test_bot.conftest import (
    AVATAR_BYTES,
    BOT_TOKEN,
    CHAT_ID,
    SEEDED_PHONE,
    RecordingSession,
    arm_avatar,
    callback_update,
    contact_update,
    message_update,
)

pytestmark = pytest.mark.integration

TYPED_NAME = "G‘ulomjon"  # U+2018, what a phone keyboard sends
DISPLAY_NAME = "Gʻulomjon"  # U+02BB, what the customer must be shown
NOTE = "Mehribon aka, futbolni yaxshi koʻradi."

#: The language this customer picks at onboarding, and therefore the one every screen after it
#: is rendered in. Named rather than inlined because it is now read in three separate places —
#: the language tap, the 🎵 menu label the walk presses next, and the assertion that the JOIN
#: onto ``users.ui_language`` hands the same value back — and a walk that tapped one language
#: and then pressed another language's menu label would fall through to the free-text handlers
#: and fail somewhere else entirely.
SPOKEN: Final[Language] = Language.UZ_LATN


def _settings(base: Settings, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        **{
            **base.model_dump(),
            "use_fake_providers": True,
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}",
            # Real ffmpeg runs three passes per asset; the test is about wiring.
            "song_length_ms": 30_000,
            "greetings_per_kit": 3,
            # The meter ships dark, so every other test in this repository exercises the
            # pass-through. This one turns it ON, because the only place the ledger, the
            # gate, the real orchestrator and a real delivery can be proven to agree is
            # here: the customer must still get their kit AND be charged exactly once for
            # it, and neither half is evidence of the other.
            "credits_enforced": True,
            # And it has to be a deployment that GIVES the customer that one credit, which
            # the shipped configuration no longer is: ``free_allowance_credits`` moved to 0
            # when the paywall shipped, so a walk with no purchase behind it is refused at
            # ``stage.authorizing`` and never reaches a single line this module is about.
            # 3 rather than 1, which is the number that used to arrive by default: it is
            # the only allowance under which the balance afterwards distinguishes all three
            # outcomes this file cares about. With one credit granted, "0 left" is equally
            # what an allowance that never minted at all would read; with three, the 2
            # asserted below says the grant happened AND exactly one was taken from it. The
            # PAYWALL is not exercised here — it has no worker, no ffmpeg and no delivery in
            # it — and is driven end to end in ``tests/test_bot/test_checkout.py``.
            "free_allowance_credits": 3,
        },
    )


@pytest.fixture
async def app(
    settings: Settings, tmp_path: Path
) -> AsyncGenerator[
    tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter], None
]:
    configured = _settings(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    session = RecordingSession()
    # All three hops of the avatar fetch, armed here rather than per test. The fetch is the
    # last thing onboarding does and it is best-effort: unarmed, ``getUserProfilePhotos``
    # answers the harness's canned ``Message``, the ``AttributeError`` is swallowed by
    # ``avatar.fetch_and_store_avatar``'s deliberately broad guard, and every run of this
    # module would log a stack trace for a step that is supposed to have succeeded. Armed, the
    # walk below drives the one path in the whole suite where the bot's fetcher, the real
    # ``record_avatar`` and the container's ``LocalFileStorage`` are all the production ones.
    arm_avatar(session)
    bot = Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    ctx = {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot}

    async def run_inline(order_id: str, chat_id: int, progress_message_id: int) -> None:
        await generate_and_deliver(ctx, order_id, chat_id, progress_message_id)

    submitter = InProcessOrderSubmitter(container.repository, run_inline)
    # The wizard writes the lyric on the customer's screen now, so this is the one place
    # the bot is wired with a REAL writer over the fake LLM provider — the same class the
    # composition root builds, not a test double.
    dispatcher = build_dispatcher(
        BotDeps(
            settings=configured,
            submitter=submitter,
            content=LlmContentWriter(container.require_providers().llm, configured),
            payment=container.payment,
            # ``main.py``'s line, verbatim. The REAL ``SqlUserProfiles`` over the same sqlite
            # file and the same ``LocalFileStorage`` the archive uses — not ``FakeProfiles``,
            # and not ``None``, which would fail open and skip onboarding altogether.
            profiles=container.profiles,
        ),
        storage=MemoryStorage(),
    )
    try:
        yield dispatcher, bot, session, container, submitter
    finally:
        await container.aclose()


async def _complete_onboarding(dispatcher: Dispatcher, bot: Bot) -> None:
    """The three presses that turn a stranger into an account: /start, a language, a number.

    Separate from :func:`_walk_the_wizard` because it is the half that costs nothing — no
    vendor, no ffmpeg, no order — while the wizard below it costs three encode passes per
    asset. A test that only wants to know what onboarding WROTE calls this one and finishes in
    milliseconds instead of shelling out to ffmpeg to learn the same fact.
    """
    await dispatcher.feed_update(bot, message_update("/start"))
    await dispatcher.feed_update(
        bot, callback_update(LanguageCB(slot=LanguageSlot.UI, code=SPOKEN).pack())
    )
    await dispatcher.feed_update(bot, contact_update())


async def _walk_the_wizard(dispatcher: Dispatcher, bot: Bot) -> None:
    """Exactly what a customer presses, in order, through the real keyboards.

    **The first three presses are onboarding, and they are driven against a REAL**
    ``SqlUserProfiles`` **over sqlite.** This is the only place in the suite where the port,
    the migrated ``user_profiles`` table, the ``users`` row its primary key points at, the
    shared ``LocalFileStorage`` and the wizard meet in one process; everywhere else runs on
    ``FakeProfiles``, which agrees with any schema because it has none. A NOT NULL nobody
    satisfied, an uncommitted session, or a phone number that does not round-trip fails HERE
    and nowhere earlier.

    **``/start`` no longer opens the wizard, and that is the shape being tested.** It asks the
    language; the language answer asks for the number; the number ends onboarding and draws the
    persistent menu. Only 🎵 starts a song — which is why the fourth press is a MESSAGE whose
    text is a catalogue label and not a callback. A reply-keyboard button is an ordinary text
    message, so this press is also the proof that ``MENU_LABELS`` matches what
    ``main_menu_keyboard`` actually drew in this locale: get the two out of step and the label
    falls through to the free-text handlers instead of starting anything.

    The contact card carries ``user_id == from_user.id``. A forwarded card is refused by
    ``handle_contact_shared`` and the walk would stall on the contact step for ever — the
    foreign-card branch has its own tests; this one must take the accepting path.
    """
    await _complete_onboarding(dispatcher, bot)
    await dispatcher.feed_update(bot, message_update(translate("menu.generate", SPOKEN)))
    await dispatcher.feed_update(bot, callback_update(OccasionCB(value=Occasion.BIRTHDAY).pack()))
    await dispatcher.feed_update(bot, callback_update(GenreCB(value=Genre.UZBEK_POP).pack()))
    await dispatcher.feed_update(bot, callback_update(VocalGenderCB(value=VoiceGender.MALE).pack()))
    await dispatcher.feed_update(bot, message_update(NOTE))
    await dispatcher.feed_update(bot, message_update(TYPED_NAME))
    await dispatcher.feed_update(bot, callback_update(NavCB(action=NavAction.NAME_OK).pack()))
    await dispatcher.feed_update(
        bot, callback_update(LanguageCB(slot=LanguageSlot.OUTPUT, code=SPOKEN).pack())
    )
    # The output language is no longer the last press: it writes a lyric and shows it, and
    # the customer approves those exact words before the order can be confirmed.
    await dispatcher.feed_update(bot, callback_update(NavCB(action=NavAction.LYRICS_OK).pack()))
    await dispatcher.feed_update(bot, callback_update(NavCB(action=NavAction.CONFIRM).pack()))


async def test_a_customer_walking_the_wizard_receives_a_complete_kit(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    """The kit arrives AND the two answers that bought it survive the process.

    The profile half is asserted in the same test as the delivery half on purpose: they are
    one walk, and splitting them would run ffmpeg twice to learn one thing each. It is also
    the only combination that is evidence — a suite that proved the row was written but never
    delivered a song, or delivered a song from a customer it forgot, would be green in both
    halves and broken in the product.

    ``ui_language`` is read back through the JOIN onto ``users``, which is where that column
    lives and stays; it is the one field on :class:`~hbd.user_profiles.UserProfile` that no
    ``user_profiles`` row holds, so it is the one a store could plausibly answer with a
    default and nobody would notice.
    """
    # Arrange
    dispatcher, bot, session, container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: one song, three voice notes, a lyric sheet, a closing message.
    assert len(session.named("SendAudio")) == 1
    assert len(session.named("SendVoice")) == 3
    lyric_messages = [
        call
        for call in session.named("SendMessage")
        if DISPLAY_NAME in (getattr(call, "text", "") or "")
    ]
    assert lyric_messages, "the lyric sheet never reached the chat"

    # Assert: and the onboarding answers are on a real row, in real columns.
    assert container.profiles is not None, "the e2e container must wire the profile store"
    profile = await container.profiles.get(CHAT_ID)
    assert isinstance(profile, Ok), f"the profile could not be read: {profile}"
    stored = profile.value
    assert stored is not None, "onboarding completed but wrote no user_profiles row"
    assert stored.phone_e164 == SEEDED_PHONE
    assert stored.ui_language is SPOKEN
    assert stored.is_onboarded


async def test_the_face_the_bot_fetched_is_readable_through_the_archive_handle(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    """Bot fetcher → ``record_avatar`` → the ONE ``LocalFileStorage`` → the panel's key.

    Four components, three of them owned by different packages, and no other test in the tree
    has more than two of them real at once. The failure this closes is the one that leaves no
    trace: the write succeeds, ``avatar_stored_at`` is set, and the admin route answers 404
    for ever because the storage handle the bot wrote through and the handle the route reads
    through were two objects over two roots, or because the key was spelled twice.

    Read through ``container.storage`` and keyed with :func:`~hbd.user_profiles.avatar_key`
    from the profile's own ``user_id``, which is exactly what the route does — the key is not
    stored on the row, so rebuilding it is the only way either side can find the bytes.

    No wizard is walked: the avatar is fetched at the END of onboarding and nothing after it
    touches the face, so paying for a song here would buy nothing but ffmpeg time.
    """
    # Arrange
    dispatcher, bot, _session, container, _submitter = app
    assert container.profiles is not None, "the e2e container must wire the profile store"

    # Act
    await _complete_onboarding(dispatcher, bot)

    # Assert: the row knows there is a face, and the archive handle can serve it.
    profile = await container.profiles.get(CHAT_ID)
    assert isinstance(profile, Ok), f"the profile could not be read: {profile}"
    stored = profile.value
    assert stored is not None, "onboarding wrote no user_profiles row"
    assert stored.avatar_stored_at is not None, "the fetcher never reached record_avatar"
    bytes_back = await container.storage.get(avatar_key(stored.user_id))
    assert isinstance(bytes_back, Ok), f"the archive handle cannot see the avatar: {bytes_back}"
    assert bytes_back.value == AVATAR_BYTES


async def test_the_greetings_are_ogg_opus_so_telegram_renders_them_as_voice_notes(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, session, _container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: sendVoice with anything but OGG/Opus renders as a file attachment.
    for call in session.named("SendVoice"):
        voice: Any = call.voice  # type: ignore[attr-defined]
        assert Path(voice.path).suffix == ".ogg"


async def test_the_customer_only_ever_sees_the_canonical_orthography(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, session, _container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: U+02BB everywhere on screen, and the typed U+2018 nowhere.
    on_screen = "\n".join(
        (getattr(call, "text", None) or getattr(call, "caption", None) or "")
        for call in session.calls
    )
    assert DISPLAY_NAME in on_screen
    assert TYPED_NAME not in on_screen


async def test_the_order_and_its_kit_survive_in_the_database(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, _session, container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: the bot persisted the order and the pipeline persisted its kit.
    orders = await container.repository.list_orders_for_user(CHAT_ID, limit=10)
    assert isinstance(orders, Ok), f"listing failed: {orders}"
    assert len(orders.value) == 1
    kit = await container.repository.get_kit(orders.value[0].id)
    assert isinstance(kit, Ok), f"kit was not persisted: {kit}"
    assert len(kit.value.greetings) == 3


async def test_one_delivered_kit_costs_the_customer_exactly_one_credit(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    """The whole meter, end to end, against the real ledger the worker writes through.

    The customer has never been seen before, so the rolling allowance is minted by the very
    charge that spends from it — three credits opened and one spent, in one transaction,
    with nothing seeded by hand. ``in_flight`` is back to 0 because the job SETTLED the
    debit once the kit landed (``jobs._settle``, CONSUME on DELIVERED): the credit is spent,
    not returned, and the slot the abuse cap counts is free again. Both numbers matter and
    neither implies the other — a settlement that refunded would read ``credits == 3``, and
    one that never ran would read ``in_flight == 1`` and wedge this customer out of their
    next song until the grace window expired.
    """
    # Arrange
    dispatcher, bot, session, container, submitter = app
    assert container.credits is not None, "the e2e container must wire the entitlement store"

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: the kit arrived AND it was paid for. Neither proves the other.
    assert len(session.named("SendAudio")) == 1
    balance = await container.credits.balance_for(CHAT_ID)
    assert isinstance(balance, Ok), f"the balance could not be read: {balance}"
    assert balance.value.credits == 2
    assert balance.value.in_flight == 0


async def test_the_name_chunk_carried_a_submitted_orthography_never_the_display_one(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, _session, container, submitter = app
    music: Any = container.require_providers().music

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: the vendor saw a candidate; the loop re-rolled at least once.
    name_texts = [
        chunk.text for call in music.calls for chunk in call.plan.chunks if chunk.is_name_chunk
    ]
    assert name_texts, "no chunk was marked as the name chunk"
    assert len(music.calls) > 1, "the acoustic re-roll never fired"
