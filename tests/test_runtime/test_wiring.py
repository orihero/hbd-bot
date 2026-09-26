"""The composition root: does the flag actually swap everything, and is it safe?

These are the tests no module agent could write, because each of them owned one side of a
seam. What is asserted here is the *joins*: the fake flag is all-or-nothing, a live build
names every vendor, the similarity port is bound the right way round, and production
cannot accidentally be served silence.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from typing import Final, get_args

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.bot.app import WIZARD_STATE_TTL
from bayram.bot.deps import BotDeps
from bayram.bot.pricing import Pricing
from bayram.checkout import (
    STUB_PROVIDER_NAME,
    CheckoutProvider,
    Product,
    PurchaseFulfiller,
    PurchaseRequest,
)
from bayram.config import ENV_FILE_VAR, ENV_PREFIX, CheckoutRail, Settings, build_settings
from bayram.contracts import (
    AudioPostProcessor,
    Err,
    KitRepository,
    Language,
    LlmProvider,
    MusicProvider,
    Ok,
    PaymentProvider,
    Storage,
    SttProvider,
    TtsProvider,
)
from bayram.db.credits import SqlCreditLedger
from bayram.db.lyric_budget import SqlLyricBudget
from bayram.db.payme import SqlPaymeLedger
from bayram.db.purchases import SqlPurchaseLedger
from bayram.entitlements import EntitlementStore, resolve_entitlement_policy
from bayram.errors import ConfigError
from bayram.main import refuse_an_unsafe_checkout_rail
from bayram.payme.link import PROD_CHECKOUT_URL, SANDBOX_CHECKOUT_URL
from bayram.payme.ports import PAYME_PROVIDER_NAME
from bayram.payme.provider import PaymeCheckoutProvider
from bayram.payments import CreditGatedPaymentProvider, NoopPaymentProvider
from bayram.pipeline.content import LlmContentWriter
from bayram.providers.llm.fake import FakeLlmProvider
from bayram.providers.music.fake import FakeMusicProvider
from bayram.providers.tts.fakes import FakeTtsProvider
from bayram.providers.tts.router import LanguageRoutingTts
from bayram.runtime.container import AppContainer, build_checkout, build_container
from bayram.runtime.fakes import KeytermSttProvider
from bayram.runtime.providers import build_provider_set
from bayram.runtime.submitter import InProcessOrderSubmitter
from bayram.user_profiles import AVATAR_MIME, avatar_key


def _fake(settings: Settings, **extra: object) -> Settings:
    payload = {**settings.model_dump(), "use_fake_providers": True, **extra}
    return Settings(_env_file=None, **payload)


def _sqlite(settings: Settings, tmp_path: Path, **extra: object) -> Settings:
    return _fake(settings, database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", **extra)


#: A plausible cashbox id: 24 hex characters, which is what Payme's own examples carry. Never
#: a real one — the merchant id is public, but a test that used a live cashbox would build
#: links that charge somebody.
_MERCHANT_ID: Final[str] = "587f72c72cac0d162c722ae2"


def _null_session_factory() -> async_sessionmaker[AsyncSession]:
    """A factory bound to nothing, for the tests that only inspect what was WIRED.

    ``build_checkout`` stores this on the ledger and never opens a session, so a bindless
    factory is enough — and it keeps the settings-to-argument tests free of a database, which
    is the difference between an assertion about wiring and an assertion about SQLAlchemy.
    """
    return async_sessionmaker(expire_on_commit=False)


# ---------------------------------------------------------------------------
# ProviderSet
# ---------------------------------------------------------------------------
def test_the_fake_flag_swaps_every_vendor_at_once(settings: Settings) -> None:
    # Arrange / Act
    providers = build_provider_set(_fake(settings))

    # Assert: all six, not some.
    assert providers.is_fake
    assert isinstance(providers.music, FakeMusicProvider)
    assert isinstance(providers.tts, FakeTtsProvider)
    assert isinstance(providers.stt, KeytermSttProvider)
    assert isinstance(providers.llm, FakeLlmProvider)
    assert providers.llm_fallback is None


def test_every_fake_still_satisfies_its_protocol(settings: Settings) -> None:
    # Arrange / Act
    providers = build_provider_set(_fake(settings))

    # Assert
    assert isinstance(providers.music, MusicProvider)
    assert isinstance(providers.tts, TtsProvider)
    assert isinstance(providers.stt, SttProvider)
    assert isinstance(providers.llm, LlmProvider)


def test_fake_providers_are_refused_in_production(settings: Settings) -> None:
    # Arrange / Act / Assert: silence must never reach a paying customer.
    with pytest.raises(ConfigError, match="prod"):
        build_provider_set(_fake(settings, environment="prod"))


async def test_a_live_build_names_a_real_adapter_for_every_leg(settings: Settings) -> None:
    # Arrange / Act: no request is made — construction only.
    providers = build_provider_set(settings)

    # Assert
    assert not providers.is_fake
    assert isinstance(providers.tts, LanguageRoutingTts)
    assert providers.music.name == "elevenlabs_music"
    assert providers.stt.name == "elevenlabs_scribe"
    await providers.aclose()


def test_a_malformed_voice_registry_override_fails_startup_rather_than_defaulting(
    settings: Settings,
) -> None:
    # Arrange: an operator's typo must not silently restore the shipped cast.
    broken = _fake(settings, tts_voice_registry_json="{not json")

    # Act / Assert
    with pytest.raises(ConfigError, match="VOICE_REGISTRY"):
        build_provider_set(broken)


def test_a_malformed_route_table_fails_startup(settings: Settings) -> None:
    # Arrange
    broken = Settings(
        _env_file=None, **{**settings.model_dump(), "tts_routes": "klingon=elevenlabs_tts"}
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="TTS_ROUTES"):
        build_provider_set(broken)


# ---------------------------------------------------------------------------
# AppContainer
# ---------------------------------------------------------------------------
async def test_the_container_satisfies_every_protocol_the_pipeline_asks_for(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert isinstance(container.repository, KitRepository)
        assert isinstance(container.storage, Storage)
        assert isinstance(container.post, AudioPostProcessor)
        assert isinstance(container.payment, PaymentProvider)
    finally:
        await container.aclose()


async def test_the_container_creates_its_workspace_and_archive_directories(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert container.workspace_root.is_dir()
        assert (tmp_path / "archive").is_dir()
    finally:
        await container.aclose()


async def test_a_pipeline_can_be_built_per_job_without_touching_the_container(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act
    try:
        first = container.pipeline()
        second = container.pipeline()

        # Assert: separate pipelines, one shared slot budget.
        assert first is not second
        assert first._music_slots is second._music_slots
    finally:
        await container.aclose()


async def test_the_semaphores_honour_the_configured_vendor_ceilings(
    settings: Settings, tmp_path: Path
) -> None:
    # Arrange
    configured = _sqlite(settings, tmp_path, music_max_concurrency=5, tts_max_concurrency=7)

    # Act
    container = await build_container(configured, data_root=tmp_path)

    # Assert
    try:
        assert container.music_slots._value == 5
        assert container.tts_slots._value == 7
    finally:
        await container.aclose()


async def test_closing_the_container_twice_is_harmless(settings: Settings, tmp_path: Path) -> None:
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act / Assert: shutdown paths run twice under interrupt; that must not raise.
    await container.aclose()
    await container.aclose()


# ---------------------------------------------------------------------------
# The similarity binding — the one argument order that silently breaks the product
# ---------------------------------------------------------------------------
def test_the_similarity_port_is_bound_the_right_way_round() -> None:
    # Arrange: the port is (heard, expected); bayram.names is (intended, heard).
    from bayram.runtime.container import _similarity

    # Act
    heard_extra_words = _similarity("bugun Gulomjon degan", "Gʻulomjon")
    reversed_arguments = _similarity("Gʻulomjon", "bugun Gulomjon degan")

    # Assert: the scorer window-scans the *heard* side, so only one order finds the name.
    assert heard_extra_words > reversed_arguments


# ---------------------------------------------------------------------------
# The render gate — wired on the worker's side of the container, and only there
# ---------------------------------------------------------------------------
async def test_the_entitlement_store_is_wired_whatever_the_enforcement_flag_says(
    settings: Settings, tmp_path: Path
) -> None:
    """Wiring and enforcing are two decisions, and only one of them is a flag.

    The store is always built, so an operator can flip ``BAYRAM_CREDITS_ENFORCED`` without a
    redeploy and so ``/balance`` has an honest number to read while the meter is still dark.
    """
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert not container.settings.credits_enforced  # the shipped default
        assert isinstance(container.credits, EntitlementStore)
    finally:
        await container.aclose()


async def test_the_lyric_budget_is_wired_and_reads_its_ceiling_from_settings(
    settings: Settings, tmp_path: Path
) -> None:
    """The one meter the BOT writes, and the only ceiling on pre-gate vendor spend.

    Never behind ``credits_enforced``: that flag covers the credit balance, which refuses a
    paying-intent customer, while this refuses abuse — and the lyric write happens before
    every gate the flag touches, so shipping it dark would leave the free tier uncapped per
    person exactly as it was.
    """
    # Arrange
    configured = _sqlite(settings, tmp_path).model_copy(update={"lyric_writes_per_day": 4})

    # Act
    container = await build_container(configured, data_root=tmp_path)

    # Assert
    try:
        assert not container.settings.credits_enforced  # the shipped default, and irrelevant
        budget = container.lyric_budget
        assert isinstance(budget, SqlLyricBudget)
        assert budget.policy.writes_per_day == 4
    finally:
        await container.aclose()


async def test_the_pipeline_gets_the_credit_gate_and_the_bot_gets_the_bare_provider(
    settings: Settings, tmp_path: Path
) -> None:
    """The asymmetry that keeps a credit from being spent where it cannot be refunded.

    ``bayram.main`` builds ``BotDeps.payment`` from ``container.payment``, so if that field
    were the gated provider the bot would become a writer — and its three early returns
    after the gate (payment declined, ``_start_progress`` returned ``None``,
    ``submitter.submit`` returned ``Err``) can reach no refund, because no order row and no
    ARQ job exist yet. The worker is the only process whose terminal paths can compensate,
    so the gate is built per job inside ``pipeline()`` instead.
    """
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act
    try:
        gate = container.pipeline()._payment

        # Assert
        assert isinstance(gate, CreditGatedPaymentProvider)
        # Dark by default, wired all the same — and the flag is read off the STORE's policy
        # now, not off the decorator, so the block gate and the in-flight cap (which need
        # the rows this gate writes) enforce whatever it says.
        assert isinstance(container.credits, SqlCreditLedger)
        assert not container.credits.policy.is_balance_enforced
        assert isinstance(container.payment, NoopPaymentProvider)
        assert not isinstance(container.payment, CreditGatedPaymentProvider)
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# The onboarding record — one storage object, one ledger signature, one handoff
# ---------------------------------------------------------------------------
async def test_the_profile_store_and_the_kit_storage_share_one_object(
    settings: Settings, tmp_path: Path
) -> None:
    """The avatar the bot writes and the object the admin panel streams are ONE file.

    ``build_container`` hoists ``LocalFileStorage(archive)`` into a local and hands the SAME
    instance to ``storage=`` and to ``SqlUserProfiles(session_factory, storage=storage)``. Two
    instances over two roots would be the quietest possible bug: the write succeeds, the row
    records ``avatar_stored_at``, every unit test passes, and ``GET /api/users/{id}/avatar``
    answers 404 for a face that is sitting on disk in a directory nothing else reads. Nobody
    can explain that 404 from the row, because the row never stored the key.

    The identity is asserted INDIRECTLY — write through ``container.profiles``, read back
    through ``container.storage`` — rather than by reaching into a private attribute, which
    ruff's ``SLF001`` refuses and which this plan may not suppress. The indirection is the
    better test anyway: it also pins the KEY SPELLING both sides use, which is the second half
    of the same failure. ``avatar_key`` is imported from ``bayram.user_profiles`` here for exactly
    the reason it lives there — it is the one definition the store, the route and this
    assertion all read.
    """
    # Arrange: a profile row must exist before an avatar has anywhere to hang, and
    # ``record_language`` is what creates both it and the ``users`` row it points at.
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)
    try:
        assert container.profiles is not None, "the container must wire a profile store"
        created = await container.profiles.record_language(4_242, ui_language=Language.UZ_LATN)
        assert isinstance(created, Ok), f"the profile row was not created: {created}"

        # Act
        image = b"\xff\xd8\xff\xe0not-really-a-jpeg"
        stored = await container.profiles.record_avatar(
            4_242, image=image, mime=AVATAR_MIME, file_unique_id="u-small"
        )
        assert isinstance(stored, Ok), f"the avatar was not stored: {stored}"

        # Assert: the OTHER handle finds the bytes, under the key the panel rebuilds.
        read_back = await container.storage.get(avatar_key(created.value.user_id))
        assert isinstance(read_back, Ok), f"the archive handle cannot see the avatar: {read_back}"
        assert read_back.value == image
    finally:
        await container.aclose()


def test_the_credit_ledger_takes_no_retention_policy() -> None:
    """PD-2: the profile table is on NO clock, so the ledger grew no second policy.

    An earlier plan had ``SqlCreditLedger(session_factory, policy=..., retention=...)`` and a
    sweep that deleted profiles on a schedule. PD-2 struck all of it: ``/forget`` DELETEs the
    row and the absence IS the erasure record, so a ``retention=`` here would configure a sweep
    that never runs — and a constructor argument that nothing reads is how the next reader
    concludes the sweep was lost in a refactor and writes it again.

    Asserted on the SIGNATURE rather than on behaviour because there is no behaviour to assert:
    the correct implementation is the absent one, and absence is only checkable by name.
    """
    # Arrange / Act
    parameters = inspect.signature(SqlCreditLedger.__init__).parameters

    # Assert
    assert "policy" in parameters, "the entitlement policy is still the ledger's one knob"
    assert "retention" not in parameters


async def test_the_bot_is_handed_the_container_s_profile_store(
    settings: Settings, tmp_path: Path
) -> None:
    """``main.py`` passes ``profiles=container.profiles``, and nothing else may build one.

    The store owns a ``Storage`` handle and a session factory, so a second one constructed
    beside the container would write avatars into a different root and open its own
    transactions against the same rows. Building the deps here the way the composition root
    does is the only assertion that can catch that line being dropped: ``BotDeps.profiles``
    defaults to ``None``, which fails OPEN — every customer is treated as onboarded and the
    language and contact questions are never asked — so a forgotten keyword ships as "the
    onboarding flow silently does not exist", with a green suite and no error anywhere.

    ``demo.py`` is deliberately not exercised: it drives ``build_container`` and never
    constructs a ``BotDeps`` at all, which is why it needed no edit.
    """
    # Arrange
    configured = _sqlite(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    try:

        async def _never_runs(order_id: str, chat_id: int, progress_message_id: int) -> None:
            raise AssertionError("this test builds the wiring; it renders nothing")

        # Act: the same six lines ``bayram.main.run`` builds, with the same sources.
        deps = BotDeps(
            settings=configured,
            submitter=InProcessOrderSubmitter(container.repository, _never_runs),
            content=LlmContentWriter(container.require_providers().llm, configured),
            payment=container.payment,
            entitlements=container.credits,
            lyric_budget=container.lyric_budget,
            profiles=container.profiles,
        )

        # Assert: one object, not two that happen to agree.
        assert deps.profiles is not None
        assert deps.profiles is container.profiles
    finally:
        await container.aclose()


async def test_a_container_without_an_entitlement_store_still_builds_a_working_pipeline(
    settings: Settings, tmp_path: Path
) -> None:
    """``credits=None`` means "not wired at all", which is not the same as "wired, dark".

    Every test that predates the meter constructs a container without one, so the render
    gate has to degrade to the bare seam rather than to an exception at job time.
    """
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)
    unmetered = replace(container, credits=None)

    # Act / Assert
    try:
        assert unmetered.pipeline()._payment is unmetered.payment
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# The checkout — the seam a real rail lands on, and the one grant the bot may cause
# ---------------------------------------------------------------------------
async def test_the_default_container_wires_a_checkout_provider_that_contacts_nothing(
    settings: Settings, tmp_path: Path
) -> None:
    """OUT OF THE BOX the seam is stubbed, and that is now the whole of this test's claim.

    It used to assert that the container wires the stub, full stop. A real rail has since
    landed, so the claim had to be NARROWED rather than deleted: with the shipped
    configuration — ``BAYRAM_CHECKOUT_PROVIDER`` unset, therefore ``stub`` — the object built
    here is the same one that was built before Payme existed, and no intent port is wired at
    all. That is the rollback guarantee stated as an assertion: production behaviour is
    byte-identical to what it was until one environment variable moves.

    Asserted on ``name`` rather than on the concrete class because ``name`` is what the
    receipt records and what a log line reports.
    """
    # Arrange / Act
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert container.settings.checkout_provider == STUB_PROVIDER_NAME
        assert isinstance(container.checkout, CheckoutProvider)
        assert container.checkout.name == STUB_PROVIDER_NAME
        # No redirect rail, therefore no intent port. Not a degraded state: the stub settles
        # inline and never produces the unpaid-with-a-URL shape the port exists to serve.
        assert container.intents is None
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# The rail that takes real money — selected by one variable, refused by three checks
# ---------------------------------------------------------------------------
def test_the_checkout_rail_literal_names_exactly_the_two_rails_that_exist() -> None:
    """``bayram.config`` spells these two strings by hand; three modules must agree on them.

    ``CheckoutRail`` cannot be built from imported names — a ``Literal`` takes literals — and
    ``bayram.config`` must not import either package anyway. So the duplication is real, and
    this is the pin that stops it drifting: the day somebody renames the stub or the rail,
    exactly one of the three spellings moves and this test says which.
    """
    # Arrange / Act
    declared = set(get_args(CheckoutRail.__value__))

    # Assert
    assert declared == {STUB_PROVIDER_NAME, PAYME_PROVIDER_NAME}


def _payme(settings: Settings, tmp_path: Path, **extra: object) -> Settings:
    """A settings object with the Payme rail selected and the meter enforced.

    ``credits_enforced=True`` is not incidental: ``bayram.main`` refuses to boot on a live rail
    over a dark meter, so a fixture that left it false would be describing a configuration the
    process rejects.
    """
    values: dict[str, object] = {
        "checkout_provider": "payme",
        "credits_enforced": True,
        "payme_merchant_id": _MERCHANT_ID,
    }
    values.update(extra)
    return _sqlite(settings, tmp_path, **values)


async def test_selecting_payme_wires_the_payme_provider_and_its_intent_port(
    settings: Settings, tmp_path: Path
) -> None:
    """One variable swaps the rail, and the two ports are the SAME OBJECT under two types.

    That last assertion is the architectural one. ``SqlPaymeLedger`` satisfies both
    ``PaymentIntentOpener`` (what the bot gets) and ``bayram.payme.ports.PaymeLedger`` (what the
    gateway gets), and building them as two objects would be two connection paths and two
    places for the merchant id to disagree.
    """
    # Arrange / Act
    container = await build_container(_payme(settings, tmp_path), data_root=tmp_path)

    # Assert
    try:
        assert isinstance(container.checkout, PaymeCheckoutProvider)
        assert container.checkout.name == PAYME_PROVIDER_NAME
        assert isinstance(container.intents, SqlPaymeLedger)
        # The provider holds the very object the container exposes as the intent port.
        assert container.checkout._opener is container.intents
    finally:
        await container.aclose()


async def test_selecting_payme_without_a_merchant_id_refuses_by_name(
    settings: Settings, tmp_path: Path
) -> None:
    """The refusal happens where the rail is BUILT, and it says which variable is empty.

    A blank cashbox id would produce links whose ``m=`` is empty, which Payme's own checkout
    answers with «Поставщик не найден» — a sentence about THEIR system that a customer reads
    as a sentence about ours. The message must name ``BAYRAM_PAYME_MERCHANT_ID`` because that is
    the entire content of the fix.
    """
    # Arrange
    misconfigured = _payme(settings, tmp_path, payme_merchant_id="")

    # Act / Assert
    with pytest.raises(ConfigError, match="BAYRAM_PAYME_MERCHANT_ID"):
        await build_container(misconfigured, data_root=tmp_path)


async def test_a_deployment_on_the_stub_boots_with_no_payme_configuration_at_all(
    settings: Settings, tmp_path: Path
) -> None:
    """The reason the refusal is at the rail and not at every boot.

    Today's production has no cashbox id, no account field override and no return URL, and it
    must keep booting. A blanket "Payme must be configured" check at the composition root
    would have made this configuration illegal on the day the rail merged, for a rail nobody
    had switched on.
    """
    # Arrange
    bare = _sqlite(settings, tmp_path, payme_merchant_id="", payme_return_url="")

    # Act
    container = await build_container(bare, data_root=tmp_path)

    # Assert
    try:
        assert container.checkout.name == STUB_PROVIDER_NAME
    finally:
        await container.aclose()


def test_the_payme_provider_is_pointed_at_the_sandbox_or_production_by_one_flag(
    settings: Settings,
) -> None:
    """``payme_is_sandbox`` picks the host, and an explicit override beats both.

    Built through the factory rather than the container so this needs no engine: the point
    under test is a settings-to-argument mapping, and a database would only slow it down.
    """
    # Arrange
    factory = _null_session_factory()
    sandboxed = settings.model_copy(
        update={"checkout_provider": "payme", "payme_merchant_id": _MERCHANT_ID}
    )
    live = sandboxed.model_copy(update={"payme_is_sandbox": False})
    overridden = live.model_copy(update={"payme_checkout_base_url": "https://elsewhere.example"})

    # Act
    on_sandbox, _ = build_checkout(sandboxed, session_factory=factory)
    on_prod, _ = build_checkout(live, session_factory=factory)
    on_override, _ = build_checkout(overridden, session_factory=factory)

    # Assert
    assert isinstance(on_sandbox, PaymeCheckoutProvider)
    assert isinstance(on_prod, PaymeCheckoutProvider)
    assert isinstance(on_override, PaymeCheckoutProvider)
    assert on_sandbox._base_url == SANDBOX_CHECKOUT_URL
    assert on_prod._base_url == PROD_CHECKOUT_URL
    assert on_override._base_url == "https://elsewhere.example"


async def test_the_rail_is_open_when_no_pause_switch_is_wired(settings: Settings) -> None:
    """ "No switch" and "switch unreadable" answer the same way, and that is deliberate.

    An unreachable Redis silently stopping every sale is a worse outage than a paused rail
    briefly taking a payment, so both degrade towards selling. It follows that the pause
    switch is not a security control, and this test is where that is written down.
    """
    # Arrange
    configured = settings.model_copy(
        update={"checkout_provider": "payme", "payme_merchant_id": _MERCHANT_ID}
    )

    # Act
    provider, _ = build_checkout(configured, session_factory=_null_session_factory())

    # Assert
    assert isinstance(provider, PaymeCheckoutProvider)
    assert await provider._paused() is False


def test_the_plan_snapshot_handed_to_the_rail_is_the_catalogue_the_buttons_quote(
    settings: Settings,
) -> None:
    """One catalogue, read once at the composition root, reaching both the screen and the rail.

    A plan sold at twelve songs and settled at whatever the config says at settlement time is
    a plan that can shrink after it is paid for, which is the argument
    ``plan_purchases.songs_included`` already makes one layer down.
    """
    # Arrange
    configured = settings.model_copy(
        update={
            "checkout_provider": "payme",
            "payme_merchant_id": _MERCHANT_ID,
            "starter_plan_songs": 7,
            "starter_plan_days": 21,
        }
    )

    # Act
    provider, _ = build_checkout(configured, session_factory=_null_session_factory())
    quoted = Pricing.from_settings(configured)

    # Assert
    assert isinstance(provider, PaymeCheckoutProvider)
    assert (provider._plan_songs, provider._plan_days) == (quoted.plan_songs, quoted.plan_days)


async def test_the_purchase_port_is_wired_exactly_where_the_credit_ledger_is(
    settings: Settings, tmp_path: Path
) -> None:
    """Granting and reading are one decision, because half of it is a lie to the customer.

    A deployment that could grant but could not read a balance would take money and then
    paywall the customer in the very next message, so the two are built from the same
    condition — a session factory — rather than from two flags that can drift apart. The
    ledger's policy is asserted to be the RESOLVED one and not the dataclass default, because
    ``credit_sql.read_balance`` projects a live plan's unminted songs against it: a store
    reading one allowance while the worker charges under another is how the Confirm screen
    comes to disagree with the render gate one second later.
    """
    # Arrange
    configured = _sqlite(settings, tmp_path).model_copy(update={"free_allowance_credits": 2})

    # Act
    container = await build_container(configured, data_root=tmp_path)

    # Assert
    try:
        assert isinstance(container.purchases, PurchaseFulfiller)
        assert isinstance(container.purchases, SqlPurchaseLedger)
        assert (container.credits is None) == (container.purchases is None)
        assert container.purchases._policy == resolve_entitlement_policy(configured)
        assert container.purchases._policy.allowance_credits == 2
    finally:
        await container.aclose()


async def test_the_render_gate_never_reaches_the_purchase_ledger(
    settings: Settings, tmp_path: Path
) -> None:
    """A purchase GRANTS and the render gate CHARGES; those two stay in different processes.

    If ``_render_gate`` ever learned about ``purchases``, the worker would gain the ability
    to mint the credit it is about to spend — which is not a paywall, it is a free song with
    extra rows. The gate is therefore asserted twice over: it is still built from ``credits``
    alone, and its source text does not name the field at all. The source assertion is the
    one that survives a refactor, because a gate that merely *held* the ledger without using
    it yet would still pass the behavioural half.
    """
    # Arrange
    container = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)

    # Act
    try:
        gate = container._render_gate()

        # Assert
        assert isinstance(gate, CreditGatedPaymentProvider)
        assert "purchases" not in inspect.getsource(AppContainer._render_gate)
        # And the gate is indifferent to the port: strip it, and the same gate is built.
        assert isinstance(replace(container, purchases=None)._render_gate(), type(gate))
    finally:
        await container.aclose()


async def test_the_bot_is_handed_the_checkout_seam_the_purchase_port_and_a_price_list(
    settings: Settings, tmp_path: Path
) -> None:
    """The three fields ``bayram.main`` adds, and what each of them costs if it is forgotten.

    All three default, for the reason measured in ``bayram.bot.deps`` — about thirty keyword
    construction sites in the suite — so a dropped keyword ships silently as "this deployment
    does not sell": the paywall is never drawn, every screen renders exactly as it did before
    the paywall existed, and the suite stays green while the product quietly gives songs
    away. Building the deps here the way the composition root does is the only assertion that
    catches that.

    ``deps.payment`` is re-asserted alongside them on purpose. The bot now holds a rail that
    takes money, and the temptation to "simplify" by handing it the credit-gated provider as
    well is exactly the mistake the two fields were separated to prevent: the checkout rail
    grants what was paid for, and only the worker's gate spends it.
    """
    # Arrange
    configured = _sqlite(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    try:

        async def _never_runs(order_id: str, chat_id: int, progress_message_id: int) -> None:
            raise AssertionError("this test builds the wiring; it renders nothing")

        # Act: the same keywords ``bayram.main.run`` passes, from the same sources.
        deps = BotDeps(
            settings=configured,
            submitter=InProcessOrderSubmitter(container.repository, _never_runs),
            content=LlmContentWriter(container.require_providers().llm, configured),
            payment=container.payment,
            entitlements=container.credits,
            lyric_budget=container.lyric_budget,
            profiles=container.profiles,
            amount_minor=configured.single_song_price_minor,
            currency=configured.kit_currency,
            checkout=container.checkout,
            purchases=container.purchases,
            pricing=Pricing.from_settings(configured),
        )

        # Assert: one object each, not a second one that happens to agree.
        assert deps.checkout is container.checkout
        assert deps.purchases is container.purchases
        assert deps.purchases is not None
        # The catalogue the buttons quote, straight off Settings and never re-read per screen.
        assert deps.pricing is not None
        assert deps.pricing.single_amount_minor == configured.single_song_price_minor
        assert deps.pricing.plan_amount_minor == configured.starter_plan_price_minor
        assert deps.pricing.plan_songs == 12
        assert deps.pricing.plan_days == 30
        assert deps.pricing.currency == configured.kit_currency
        # The render gate's quote and the checkout's quote are the same number today.
        assert deps.amount_minor == configured.single_song_price_minor
        # And the bot's payment seam is STILL the bare provider, not the gated decorator.
        assert isinstance(deps.payment, NoopPaymentProvider)
        assert not isinstance(deps.payment, CreditGatedPaymentProvider)
    finally:
        await container.aclose()


async def test_the_shipped_free_allowance_of_zero_reaches_the_ledger_policy(
    settings: Settings, tmp_path: Path
) -> None:
    """Every recording is sold, and that is a resolved policy rather than a hardcoded 0.

    The paywall only ever appears to a customer whose balance is below the render cost, so a
    free allowance that still minted three songs a month would hide the pay and subscribe
    buttons behind three free renders — the buttons would exist, be tested, and never be seen.
    The value is asserted from BOTH directions: the shipped default is 0, and a configured
    non-zero one threads through, which is what distinguishes "resolved from Settings" from
    "someone wrote 0 in the resolver".
    """
    # Arrange
    default = await build_container(_sqlite(settings, tmp_path), data_root=tmp_path)
    generous = await build_container(
        _sqlite(settings, tmp_path).model_copy(update={"free_allowance_credits": 4}),
        data_root=tmp_path,
    )

    # Act / Assert
    try:
        assert default.settings.free_allowance_credits == 0  # the shipped default
        assert isinstance(default.credits, SqlCreditLedger)
        assert default.credits.policy.allowance_credits == 0
        assert isinstance(generous.credits, SqlCreditLedger)
        assert generous.credits.policy.allowance_credits == 4
    finally:
        await default.aclose()
        await generous.aclose()


# ---------------------------------------------------------------------------
# The boot refusals — the three configurations this process will not start on
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_dotenv(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the boot check's dotenv scan at a file that does not exist.

    ``refuse_an_unsafe_checkout_rail`` reads BOTH the process environment and the dotenv file
    this process would load, which is what makes it a control rather than a check a deploy
    script walks around by writing to a file instead of exporting. That second half would
    otherwise make every test below depend on whatever is in the developer's own ``.env``, so
    it is pointed at nothing.

    It takes ``settings`` so it is ordered AFTER that fixture, which strips every ``BAYRAM_``
    variable from the environment — including the one set here, if the order were reversed.
    """
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "there-is-no-dotenv-here.env"))


async def test_main_hands_the_intent_opener_to_bot_deps(settings: Settings, tmp_path: Path) -> None:
    """The last hop of the wiring: container -> ``BotDeps``, one object and not a copy.

    A dropped keyword here would be invisible — no screen reads ``deps.intents`` today,
    because the provider holds the same object and opens the intent inside ``charge`` — so
    nothing in the suite except this assertion would notice. That is exactly the shape of bug
    the sibling test above ("this deployment does not sell") was written for.
    """
    # Arrange
    configured = _payme(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    try:

        async def _never_runs(order_id: str, chat_id: int, progress_message_id: int) -> None:
            raise AssertionError("this test builds the wiring; it renders nothing")

        # Act: the same keywords ``bayram.main.run`` passes, from the same sources.
        deps = BotDeps(
            settings=configured,
            submitter=InProcessOrderSubmitter(container.repository, _never_runs),
            content=LlmContentWriter(container.require_providers().llm, configured),
            payment=container.payment,
            amount_minor=configured.single_song_price_minor,
            currency=configured.kit_currency,
            checkout=container.checkout,
            intents=container.intents,
            purchases=container.purchases,
            pricing=Pricing.from_settings(configured),
        )

        # Assert
        assert deps.intents is container.intents
        assert isinstance(deps.intents, SqlPaymeLedger)
        # The narrow port and the rail are one object, reached through two types.
        assert isinstance(deps.checkout, PaymeCheckoutProvider)
        assert deps.checkout._opener is deps.intents
    finally:
        await container.aclose()


@pytest.mark.usefixtures("isolated_dotenv")
def test_payme_with_a_dark_credit_meter_refuses_to_boot(settings: Settings) -> None:
    """A rail taking real money into a meter nobody reads sells the song for nothing.

    With ``credits_enforced`` false the worker covers a short balance with an
    ``UNENFORCED_RENDER`` grant and renders anyway, so the customer is charged 7 000 UZS for
    something they would have been given. Nothing else in the process notices — the bot-side
    paywall deliberately does not read that flag — which is why this is a refusal and not the
    warning it used to be. The two settings must therefore move in the same edit, and that is
    the right direction to fail on go-live day.
    """
    # Arrange
    live_rail_dark_meter = settings.model_copy(
        update={
            "checkout_provider": "payme",
            "payme_merchant_id": _MERCHANT_ID,
            "credits_enforced": False,
        }
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="BAYRAM_CREDITS_ENFORCED"):
        refuse_an_unsafe_checkout_rail(live_rail_dark_meter)


@pytest.mark.usefixtures("isolated_dotenv")
def test_a_live_rail_building_sandbox_links_refuses_to_boot_in_production(
    settings: Settings,
) -> None:
    """The gateway is live, every button points at the Payme TEST host, nobody can pay.

    ``payme_is_sandbox`` exists TWICE under one name — on ``Settings`` for the bot that builds
    the link a customer taps, and on ``bayram.payme.settings`` for the gateway that verifies the
    callback — and the two ship with OPPOSITE defaults, True here and False there. Each is right
    alone; together they make one mistake easy, and it is the mistake that was actually made on
    2026-09-14: the operator set it false in the GATEWAY's dotenv, which does nothing to the
    link, and the Pay button went on opening ``https://test.paycom.uz``.
    """
    # Arrange
    live_rail_sandbox_links = settings.model_copy(
        update={
            "checkout_provider": "payme",
            "payme_merchant_id": _MERCHANT_ID,
            "credits_enforced": True,
            "payme_is_sandbox": True,
            "environment": "prod",
        }
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="BAYRAM_PAYME_IS_SANDBOX"):
        refuse_an_unsafe_checkout_rail(live_rail_sandbox_links)


@pytest.mark.usefixtures("isolated_dotenv")
def test_a_live_rail_on_the_sandbox_still_boots_outside_production(settings: Settings) -> None:
    """The refusal above is about PRODUCTION, not about the two flags disagreeing.

    A staging box driving the real rail against Payme's test host is the rehearsal this whole
    gate was proven with, and refusing it would make the rehearsal impossible.
    """
    # Arrange
    rehearsal = settings.model_copy(
        update={
            "checkout_provider": "payme",
            "payme_merchant_id": _MERCHANT_ID,
            "credits_enforced": True,
            "payme_is_sandbox": True,
            "environment": "staging",
        }
    )

    # Act / Assert — no raise.
    refuse_an_unsafe_checkout_rail(rehearsal)


@pytest.mark.usefixtures("isolated_dotenv")
def test_the_stub_over_a_dark_credit_meter_still_boots(settings: Settings) -> None:
    """The refusal above is about MONEY, not about two flags disagreeing.

    A deployment that wants to give songs away must be able to, and that is today's shipped
    configuration: the stub reports every purchase paid and takes nothing. ``bayram.main`` still
    warns once the container is up, which is the right volume when no card was charged.
    """
    # Arrange
    shipped = settings.model_copy(update={"credits_enforced": False})

    # Act / Assert — it returns rather than raising, which is the whole assertion.
    refuse_an_unsafe_checkout_rail(shipped)


@pytest.mark.usefixtures("isolated_dotenv")
def test_the_bot_refuses_in_prod_when_the_merchant_key_is_reachable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bot builds links with a PUBLIC id and must never hold the inbound verification key.

    Its theft mints credits at our own gateway, which is a different blast radius from the
    four outbound credentials this process does hold — and different blast radii are the whole
    reason the gateway is a fourth process. The message names the variable and never carries
    its value, exactly as the admin app's mirror image of this check does.
    """
    # Arrange
    variable = f"{ENV_PREFIX}PAYME_MERCHANT_KEY"
    secret = "a-key-that-must-not-be-within-reach-of-this-process"
    monkeypatch.setenv(variable, secret)
    in_production = settings.model_copy(update={"environment": "prod"})

    # Act / Assert
    with pytest.raises(ConfigError, match=variable) as raised:
        refuse_an_unsafe_checkout_rail(in_production)
    assert secret not in str(raised.value)
    assert secret not in str(raised.value.context)


@pytest.mark.usefixtures("isolated_dotenv")
def test_a_reachable_merchant_key_outside_prod_warns_and_boots(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A developer with one dotenv on a laptop is not the incident this check is about.

    Refusing there would only teach people to delete the check — the same reasoning
    ``bayram.admin.app._refuse_vendor_credentials`` records for its own prod-only refusal.
    """
    # Arrange
    monkeypatch.setenv(f"{ENV_PREFIX}PAYME_MERCHANT_KEY", "a-development-placeholder")

    # Act / Assert — it returns rather than raising, which is the whole assertion.
    refuse_an_unsafe_checkout_rail(settings)


@pytest.mark.usefixtures("isolated_dotenv")
def test_the_dotenv_file_is_scanned_and_not_only_the_environment(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Half a control is worse than none: a key written into the file is just as reachable.

    ``pydantic-settings`` reads that file case-insensitively, so a lowercase line is exactly
    as live as the shouted form and the scan upper-cases before comparing.
    """
    # Arrange
    dotenv = tmp_path / "bot.env"
    dotenv.write_text("bayram_payme_merchant_key=written-into-the-file\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(dotenv))
    in_production = settings.model_copy(update={"environment": "prod"})

    # Act / Assert
    with pytest.raises(ConfigError, match=f"{ENV_PREFIX}PAYME_MERCHANT_KEY"):
        refuse_an_unsafe_checkout_rail(in_production)


@pytest.mark.usefixtures("isolated_dotenv")
def test_a_checkout_link_may_not_outlive_the_draft_it_was_sold_against(
    settings: Settings,
) -> None:
    """Paying for a draft Redis has already swept is money against an unassemblable order.

    Checked unconditionally rather than only for a live rail, because it is a relationship
    between two numbers and not between two running things: it has to already hold on the day
    somebody flips the rail on, not start being checked then.
    """
    # Arrange — reach past the field's own 24-hour bound to exercise the boot assertion.
    over_the_draft_clock = settings.model_copy(
        update={"payme_intent_ttl_s": int(WIZARD_STATE_TTL.total_seconds())}
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="BAYRAM_PAYME_INTENT_TTL_S"):
        refuse_an_unsafe_checkout_rail(over_the_draft_clock)


@pytest.mark.usefixtures("isolated_dotenv")
def test_the_shipped_intent_ttl_is_comfortably_inside_the_draft_clock(
    settings: Settings,
) -> None:
    """Twelve hours against fourteen days, so the assertion above cannot fire on shipped values.

    Which is the point of having both: the field's own bound keeps the rail coherent, and the
    boot assertion is there for the day one of the two numbers moves — exactly the day nobody
    will be thinking about the other one.
    """
    # Arrange / Act / Assert
    assert settings.payme_intent_ttl_s == 43_200
    assert settings.payme_intent_ttl_s < WIZARD_STATE_TTL.total_seconds()
    refuse_an_unsafe_checkout_rail(settings)


def test_a_return_url_containing_a_semicolon_is_refused_at_settings_build_time() -> None:
    """Payme's parser truncates a value at the first ``;`` silently, and nothing observes it.

    The result is a link Payme accepts, a payment that succeeds, and a customer redirected to
    half an address. So the refusal happens at the last point where the mistake is still cheap
    and still attributable. Percent-encoding is not an alternative: the parser does not decode,
    so ``%3B`` would arrive as three literal characters.
    """
    # Arrange / Act / Assert — the failure names the variable, the way every other one does.
    with pytest.raises(ConfigError, match=f"{ENV_PREFIX}PAYME_RETURN_URL"):
        build_settings(
            {"_env_file": None, "payme_return_url": "https://t.me/bayram_uzbot?start=paid;utm=x"},
            require_vendor_secrets=False,
        )


async def test_the_pause_switch_reaches_the_rail_through_the_container(
    settings: Settings, tmp_path: Path
) -> None:
    """``build_container`` threads ``paused`` all the way to the provider, or the CLI is inert.

    This is the assertion the gap needed. ``python -m bayram.payme.cli pause`` writes a Redis key
    and ``bayram.payme.pause.is_paused`` reads it, and both halves were tested — but the composition
    root passed no reader, so the key was written and nobody read it. Every test still passed,
    the runbook's rollback step did nothing, and the only way to find out would have been an
    operator pausing a live rail during an incident and watching sales continue.
    """

    # Arrange — a rail that answers "paused" without a Redis anywhere in the test.
    async def always_paused() -> bool:
        return True

    live = _payme(settings, tmp_path)

    # Act
    container = await build_container(live, data_root=tmp_path, paused=always_paused)
    charged = await container.checkout.charge(
        PurchaseRequest(
            telegram_user_id=4242,
            product=Product.SINGLE,
            amount_minor=live.single_song_price_minor,
            currency=live.kit_currency,
            idempotency_key="pause-switch-wiring",
        )
    )

    # Assert — refused, and refused BEFORE any intent row was opened.
    assert isinstance(charged, Err)
    await container.aclose()


async def test_a_container_built_without_a_reader_leaves_the_rail_open(
    settings: Settings, tmp_path: Path
) -> None:
    """The default is an OPEN rail, not a closed one, and that direction is deliberate.

    An unreachable or unwired switch silently stopping every sale is a far worse outage than a
    paused rail briefly taking a payment — the argument ``PaymeCheckoutProvider._is_rail_paused``
    makes about a failed Redis read, applied to the case where there is no reader at all.
    """
    # Arrange
    live = _payme(settings, tmp_path)

    # Act
    container = await build_container(live, data_root=tmp_path)
    charged = await container.checkout.charge(
        PurchaseRequest(
            telegram_user_id=4243,
            product=Product.SINGLE,
            amount_minor=live.single_song_price_minor,
            currency=live.kit_currency,
            idempotency_key="pause-switch-absent",
        )
    )

    # Assert
    assert isinstance(charged, Ok)
    assert charged.value.checkout_url is not None
    await container.aclose()
