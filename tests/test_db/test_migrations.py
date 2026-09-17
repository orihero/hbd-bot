"""The migration chain is the schema. These tests keep that true.

Behavioural tests build their schema from ``Base.metadata.create_all``, which is fast and
lets them assert behaviour instead of DDL. The risk in that trade is a model changing
without a migration, so production and the test suite quietly diverge. That risk is closed
here, in one place:

* :func:`test_upgrade_then_downgrade_leaves_no_tables_behind` proves the chain is
  reversible — a migration that cannot be rolled back is one nobody dares deploy.
* :func:`test_the_migrated_schema_matches_the_model_metadata` proves the chain and the
  models agree, so ``create_all`` in the other tests is a faithful stand-in.
* ``_CORE_TABLES`` keeps the original six named explicitly, asserted as a subset, so the
  regression guard survives the schema growing without every new table having to edit
  this file.

Every test here is **synchronous**, deliberately. ``env.py`` drives an async engine and
calls ``asyncio.run`` itself, which raises if a loop is already running — so an ``async
def`` test would fail on the first ``command.upgrade``. Inspection then gets its own
``asyncio.run``, which keeps the whole module free of a sync database driver and therefore
free of a dependency the project does not otherwise need.

The SQLite runs are unit tests. The Postgres run is marked ``integration`` and needs
``docker compose up -d``; SoW DAT-4 requires the migration to work on the real engine, and
SQLite's permissiveness is not evidence that it does.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from bayram.config import get_settings
from bayram.db.engine import ping as db_ping
from bayram.db.models import Base

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_ALEMBIC_INI: Final[Path] = _REPO_ROOT / "migrations" / "alembic.ini"
_VERSIONS_DIR: Final[Path] = _ALEMBIC_INI.parent / "versions"

#: Alembic's own bookkeeping table, present after any upgrade and absent from our metadata.
_ALEMBIC_TABLE: Final[str] = "alembic_version"

#: Matches docker-compose.yml. Overridable so CI can point at its own instance.
_POSTGRES_URL: Final[str] = os.environ.get(
    "BAYRAM_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)

_REQUIRED_ENV: Final[tuple[str, ...]] = (
    "BAYRAM_TELEGRAM_BOT_TOKEN",
    "BAYRAM_ELEVENLABS_API_KEY",
    "BAYRAM_LLM_API_KEY",
)

#: The six tables the product cannot run without. Asserted as a SUBSET, never as the whole
#: schema: this is a regression guard against a migration that quietly stops creating one
#: of them, and it must not become a chore that every new table has to edit.
_CORE_TABLES: Final[frozenset[str]] = frozenset(
    {"users", "orders", "briefs", "assets", "name_records", "generation_attempts"}
)

#: Derived, not hardcoded. The chain and the models agreeing is what
#: :func:`test_the_migrated_schema_matches_the_model_metadata` proves; restating the table
#: list by hand only means a PR that adds a table turns this file red for everyone else
#: while proving nothing extra.
#:
#: **Being derived is also this constant's one blind spot, and the reason
#: :func:`test_the_new_table_is_registered_as_well_as_migrated` exists.** A model file that
#: is written but never imported in ``db/models/__init__.py`` is invisible to
#: ``Base.metadata``, so it drops out of BOTH sides of every comparison in this module at
#: once and the migration that creates the table passes unnoticed. That is why a new model
#: and its registration have to land in the same commit as its revision, and why the one
#: table this file names by hand is named in a test rather than added here.
_EXPECTED_TABLES: Final[frozenset[str]] = frozenset(Base.metadata.tables)

#: The table revision ``0014`` adds: the customer's language, number, name and photograph.
#: Spelled out once, because the assertion that keeps it registered has to name something.
_USER_PROFILES_TABLE: Final[str] = "user_profiles"

#: The table revision ``0016`` adds: one row per vendor call, with what it cost and how we
#: know. Named here for exactly the reason above — an unregistered model drops out of BOTH
#: sides of every derived comparison in this file at once — and the stake is specific: the
#: whole point of that table is that its quantity columns are nullable with no default, and
#: a schema the unit suite never builds is one whose nulls nothing ever exercises.
_VENDOR_USAGE_TABLE: Final[str] = "vendor_usage"
#: The composite index 0016 hand-names rather than deriving from ``NAMING_CONVENTION``, the
#: same way 0015 does. It is the one the vendor rollup reads on, and a migration that
#: created it under the templated name would leave the model declaring an index the chain
#: never builds — which is what ``test_the_migrated_indexes_match_the_model_metadata``
#: catches generically and this names concretely.
_VENDOR_USAGE_INDEX: Final[str] = "ix_vendor_usage_vendor_created_at"
#: The templated index on ``vendor_usage.cost_usd``. Named here for a reason the generic
#: comparison cannot express: the query it serves — ``has_priced_vendor_usage``, reached on
#: every ``/api/ops/pulse`` and so every five seconds from the Live screen — finds nothing
#: at all on a deployment that prices nothing, and a ``LIMIT 1`` that never hits is a full
#: scan of the largest table in the schema rather than a cheap probe.
_VENDOR_USAGE_COST_INDEX: Final[str] = "ix_vendor_usage_cost_usd"

#: The three tables revision ``0023`` adds: the redirect payment rail. Named by hand for the
#: reason stated on ``_EXPECTED_TABLES`` — an unregistered model drops out of BOTH sides of
#: every derived comparison at once — and the stake here is the sharpest in the file. These
#: tables carry the state machine that decides whether somebody who has paid gets a credit,
#: and every one of the concurrency tests that proves exactly-once fulfilment builds its
#: schema with ``create_all``. A model file written but never imported would leave that whole
#: suite passing against a database with no payment tables in it.
_PAYME_RAIL_TABLES: Final[frozenset[str]] = frozenset(
    {"payment_intents", "payme_transactions", "payme_rpc_log"}
)

#: The three tables revision ``0024`` adds: the campaign, its bodies and its frozen
#: audience. Named by hand for the reason stated on ``_EXPECTED_TABLES``, and the stake is
#: ``broadcast_recipients``: it is the row that answers "has this account already been
#: messaged?", and every test that proves the send is exactly-once builds its schema with
#: ``create_all``. An unregistered model would leave that suite green against a database
#: with no recipient table in it at all.
_BROADCAST_TABLES: Final[frozenset[str]] = frozenset(
    {"broadcasts", "broadcast_bodies", "broadcast_recipients"}
)

#: The two tables revision ``0027`` adds: the support ticket and its append-only timeline.
#: Named by hand for the reason stated on ``_EXPECTED_TABLES``, and the stake is the latch.
#: ``support_tickets.(group_chat_id, group_message_id)`` is both the once-only claim that stops
#: a replayed ARQ job posting a second card into the staff group and the key a staffer's reply
#: is matched back to a ticket by — and its uniqueness is what keeps one customer's answer from
#: reaching another. Every test that proves either property builds its schema with
#: ``create_all``, so an unregistered model would not turn this suite red; it would leave it
#: green while never once exercising the constraint.
_SUPPORT_TICKET_TABLES: Final[frozenset[str]] = frozenset(
    {"support_tickets", "support_ticket_events"}
)
_SUPPORT_TICKETS_TABLE: Final[str] = "support_tickets"
#: The card latch, asserted by name AND by shape. UNIQUE over the PAIR, because a Telegram
#: ``message_id`` is a per-chat counter: unique over the message id alone, it fails the latch
#: for a card that posted successfully as soon as the support group's chat id changes.
_SUPPORT_CARD_INDEX: Final[str] = "ix_support_tickets_group_chat_id_group_message_id"

#: The table revision ``0028`` adds: every group the bot knows it is in, and which one of them
#: receives ticket cards. Named by hand for the reason stated on ``_EXPECTED_TABLES``, and the
#: stake is that this table REPLACES a setting. ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` is removed in
#: the same change, so the row is the only authority there is on where support tickets land.
_BOT_CHATS_TABLE: Final[str] = "bot_chats"
#: The partial unique index that makes "at most one selected support group" true. Asserted by
#: name AND by shape, the way the support card latch is: a unique index correct in name and
#: wrong in uniqueness passes ``test_the_migrated_indexes_match_the_model_metadata`` cleanly,
#: because that test compares NAMES in one direction only.
_SELECTED_SUPPORT_GROUP_INDEX: Final[str] = "ix_bot_chats_selected_support_group"

#: The revision that adds the lyric the customer approves in the wizard, and the one it
#: builds on. Named here because both halves of the product depend on this column existing
#: before the wizard ships: without it the worker silently sings a lyric nobody approved.
_APPROVED_LYRICS_REVISION: Final[str] = "0003"
_REVISION_BEFORE_APPROVED_LYRICS: Final[str] = "0002"
_APPROVED_LYRICS_COLUMN: Final[str] = "approved_lyrics"


def _config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_ALEMBIC_INI.parent))
    return config


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """``get_settings`` is ``lru_cache``d, so a stale entry outlives any ``monkeypatch``.

    Without this the URL set by :func:`_prepare_env` is silently ignored and every run
    targets whatever database was cached first — the test cannot control its own target.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _prepare_env(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``env.py`` at ``url`` the same way production does — through ``bayram.config``.

    **The developer's own dotenv file is taken out of reach first**, and that is not
    tidiness. ``env.py`` prefers ``BAYRAM_DB_MIGRATION_URL`` — the OWNER role's DSN — over the
    application DSN set below, and reads it from the process environment and then from the
    dotenv file. A developer who has followed either README instruction has that variable
    pointed at their real Postgres, and without these two lines every test in this module
    silently migrated *that* database instead of the SQLite file in ``tmp_path``: the
    upgrade succeeded, the assertion failed against an empty temp file, and the two
    downgrade tests were one passing assertion away from running ``downgrade base`` on it.

    ``BAYRAM_ENV_FILE`` at a path that does not exist is the whole neutralisation — it is what
    ``bayram.config.env_file()`` returns, so it disables ``.env`` for the settings the
    migration builds as well.
    """
    monkeypatch.setenv("BAYRAM_ENV_FILE", str(_ALEMBIC_INI.parent / "no-such.env"))
    monkeypatch.delenv("BAYRAM_DB_MIGRATION_URL", raising=False)
    monkeypatch.setenv("BAYRAM_DATABASE_URL", url)
    for name in _REQUIRED_ENV:
        monkeypatch.setenv(name, "migration-test-value")
    # Settings are cached process-wide; the env above only takes effect once it is dropped.
    get_settings.cache_clear()


def _require_postgres(url: str) -> None:
    """Skip when no *project* Postgres answers at ``url``.

    A foreign Postgres on the same port authenticates as a different role, which is a
    missing dependency rather than a failing migration — so it skips, like the rest of the
    integration suite, instead of reporting a defect that is not there.
    """
    engine = create_async_engine(url)
    try:
        is_reachable = asyncio.run(db_ping(engine))
    finally:
        asyncio.run(engine.dispose())
    if not is_reachable:
        pytest.skip(f"no project Postgres at {url}; run `docker compose up -d`")


def _upgrade(url: str, monkeypatch: pytest.MonkeyPatch, *, to: str = "head") -> None:
    _prepare_env(url, monkeypatch)
    command.upgrade(_config(), to)


def _downgrade(url: str, monkeypatch: pytest.MonkeyPatch, *, to: str = "base") -> None:
    _prepare_env(url, monkeypatch)
    command.downgrade(_config(), to)


def _schema_of(url: str) -> dict[str, set[str]]:
    """Table -> column names, read back from a live database. Its own event loop."""

    def _read(connection: Connection) -> dict[str, set[str]]:
        inspector = inspect(connection)
        return {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
            if table != _ALEMBIC_TABLE
        }

    async def _run() -> dict[str, set[str]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _indexes_of(url: str) -> dict[str, set[str]]:
    """Table -> index names, read back from a live database. Its own event loop."""

    def _read(connection: Connection) -> dict[str, set[str]]:
        inspector = inspect(connection)
        return {
            table: {
                str(name)
                for name in (index.get("name") for index in inspector.get_indexes(table))
                if name is not None
            }
            for table in inspector.get_table_names()
            if table != _ALEMBIC_TABLE
        }

    async def _run() -> dict[str, set[str]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _index_columns_of(url: str, table: str) -> dict[str, tuple[tuple[str, ...], bool]]:
    """One table's indexes, read back from a live database as ``name -> (columns, unique)``.

    Separate from :func:`_indexes_of`, which reads names only. A name proves an index was
    created; it does not prove WHICH columns it spans or whether it is unique, and both of
    those are load-bearing for the support card latch — an index correct in name and wrong in
    shape is the failure that reached review.
    """

    def _read(connection: Connection) -> dict[str, tuple[tuple[str, ...], bool]]:
        return {
            str(index["name"]): (
                tuple(str(column) for column in index["column_names"]),
                bool(index.get("unique")),
            )
            for index in inspect(connection).get_indexes(table)
            if index.get("name") is not None
        }

    async def _run() -> dict[str, tuple[tuple[str, ...], bool]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _sqlite_url(tmp_path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / name}"


# ---------------------------------------------------------------------------
# Static checks — no engine at all
# ---------------------------------------------------------------------------
def test_exactly_one_migration_head_exists() -> None:
    # Arrange
    script = ScriptDirectory.from_config(_config())

    # Act
    heads = script.get_heads()

    # Assert — two heads means someone branched and nobody merged.
    assert len(heads) == 1


def test_every_migration_defines_a_real_downgrade() -> None:
    # Arrange
    versions = sorted(_VERSIONS_DIR.glob("*.py"))
    assert versions, "expected at least the initial migration to exist"

    # Act
    stubs = [
        path.name
        for path in versions
        if "def downgrade() -> None:\n    pass" in path.read_text(encoding="utf-8")
    ]

    # Assert
    assert stubs == [], f"migrations without a working downgrade: {stubs}"


def test_no_migration_imports_application_code() -> None:
    # Arrange — a migration importing bayram.* breaks when bayram.* is refactored, and it breaks
    # historically, on a revision that already ran everywhere. env.py renders our own
    # column types as plain SQLAlchemy ones precisely so this stays true.
    versions = sorted(_VERSIONS_DIR.glob("*.py"))

    # Act
    offenders = [
        path.name
        for path in versions
        if any(
            line.startswith(("import bayram", "from bayram"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]

    # Assert
    assert offenders == [], f"migrations importing application code: {offenders}"


def test_the_new_table_is_registered_as_well_as_migrated() -> None:
    """A model file that exists but is not imported is invisible to ``Base.metadata``.

    ``_EXPECTED_TABLES`` and ``test_the_migrated_schema_matches_the_model_metadata`` both
    derive from the metadata, so an unregistered model makes BOTH sides of the comparison
    agree on a table that neither knows about — the migration creates it, the models do not
    declare it, and every behavioural test that builds its schema with ``create_all`` runs
    without it. The symptom is not a red suite; it is a green one that has never once
    exercised the table holding every customer's phone number.

    Named by hand, unlike everything else in this module, precisely because a derived check
    cannot see the absence it is meant to catch.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    assert _USER_PROFILES_TABLE in registered, (
        f"{_USER_PROFILES_TABLE} is created by revision 0014 but no model declares it; "
        "import UserProfileRow in src/bayram/db/models/__init__.py"
    )


def test_the_vendor_usage_table_is_registered_as_well_as_migrated() -> None:
    """Revision 0016 creates ``vendor_usage``; a model has to declare it too.

    Same failure mode as :func:`test_the_new_table_is_registered_as_well_as_migrated` and
    worth naming separately, because this table's contract is entirely about what its
    columns do NOT default to. If ``VendorUsageRow`` is never imported in
    ``db/models/__init__.py`` the metadata does not know it, ``create_all`` never builds it,
    and every test that asserts "an unmeasured quantity comes back NULL" is asserting it
    against a table that is not there.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    assert _VENDOR_USAGE_TABLE in registered, (
        f"{_VENDOR_USAGE_TABLE} is created by revision 0016 but no model declares it; "
        "import VendorUsageRow in src/bayram/db/models/__init__.py"
    )


def test_the_payme_rail_tables_are_registered_as_well_as_migrated() -> None:
    """Revision 0023 creates three tables; three models have to declare them too.

    The companion this file's own convention demands, and the failure mode is the one
    ``_EXPECTED_TABLES`` documents: a model file that exists but is never imported in
    ``db/models/__init__.py`` is invisible to ``Base.metadata``, so it drops out of BOTH
    sides of every comparison in this module at once — the migration creates the table, the
    models do not declare it, and the comparison agrees on a table neither side knows about.

    It is worth naming these three separately from ``user_profiles`` and ``vendor_usage``
    because of what the tables do. They hold the payment state machine: the intent's
    ``awaiting`` hold, the conditional claim that grants a credit exactly once, and the
    unique index on the rail's own transaction id that makes a resent call a replay instead
    of a second charge. Every test that proves those properties builds its schema with
    ``create_all``. An unregistered model would leave that entire suite green against a
    database with no payment tables in it at all — the symptom is not a red suite, it is a
    green one that has never once exercised the code that moves money.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    missing = sorted(_PAYME_RAIL_TABLES - registered)
    assert missing == [], (
        f"{missing} are created by revision 0023 but no model declares them; import "
        "PaymentIntentRow, PaymeTransactionRow and PaymeRpcLogRow in "
        "src/bayram/db/models/__init__.py"
    )


def test_the_broadcast_tables_are_registered_as_well_as_migrated() -> None:
    """Revision 0024 creates three tables; three models have to declare them too.

    The same companion the two tests above are, and the same blind spot in
    ``_EXPECTED_TABLES``: a model file that exists but is never imported in
    ``db/models/__init__.py`` is invisible to ``Base.metadata`` and drops out of BOTH sides
    of every comparison in this module at once.

    ``broadcast_recipients`` is why these three are named rather than left to the derived
    comparison. It is the materialised audience — the table that makes "who was this sent
    to?" answerable and "has this account already been messaged?" askable — and the
    ``UNIQUE (broadcast_id, telegram_user_id)`` on it is the idempotency authority a replayed
    expansion chunk relies on. Every test that proves a campaign sends once builds its schema
    with ``create_all``, so an unregistered model would not turn this suite red; it would
    leave it green while never once exercising the constraint that stops forty thousand
    people getting the same message twice.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    missing = sorted(_BROADCAST_TABLES - registered)
    assert missing == [], (
        f"{missing} are created by revision 0024 but no model declares them; import "
        "BroadcastRow, BroadcastBodyRow and BroadcastRecipientRow in "
        "src/bayram/db/models/__init__.py"
    )


def test_the_support_ticket_tables_are_registered_as_well_as_migrated() -> None:
    """Revision 0027 creates two tables; two models have to declare them too.

    The same companion the three tests above are, and the same blind spot in
    ``_EXPECTED_TABLES``: a model file that exists but is never imported in
    ``db/models/__init__.py`` is invisible to ``Base.metadata`` and drops out of BOTH sides of
    every comparison in this module at once — the migration creates the table, the models do
    not declare it, and the comparison agrees on a table neither side knows about.

    These two are named rather than left to the derived comparison because of what the schema
    is carrying. ``support_tickets.(group_chat_id, group_message_id)`` is the once-only latch for
    the staff-group card: ARQ replays every job on every deploy, so the row and not the job is
    the record of "this was posted", and the UNIQUE over that pair is also what resolves a
    staffer's reply to exactly one ticket — per chat, because a Telegram message id is a
    per-chat counter. ``support_ticket_events`` is the append-only record of what a customer
    was actually told, and ``ON DELETE CASCADE`` on its ``ticket_id`` is what makes ``/forget``
    one statement instead of two that can disagree. Every test that proves any of that builds
    its schema with ``create_all``. An unregistered model would leave the whole support suite
    green against a database with no ticket tables in it — the symptom is not a red suite, it is
    a green one that has never once exercised the constraint stopping one customer's complaint
    being answered with another customer's reply.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    missing = sorted(_SUPPORT_TICKET_TABLES - registered)
    assert missing == [], (
        f"{missing} are created by revision 0027 but no model declares them; import "
        "SupportTicketRow and SupportTicketEventRow in src/bayram/db/models/__init__.py"
    )


def test_the_bot_chats_table_is_registered_as_well_as_migrated() -> None:
    """Revision 0028 creates ``bot_chats``; a model has to declare it too.

    The same companion the four tests above are, and the same blind spot in
    ``_EXPECTED_TABLES``: a model file that exists but is never imported in
    ``db/models/__init__.py`` is invisible to ``Base.metadata``, so it drops out of BOTH sides
    of every comparison in this module at once — the migration creates the table, the models do
    not declare it, and the comparison agrees on a table neither side knows about.

    This one is named rather than left to the derived comparison because of what it replaces.
    ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` is REMOVED in the same change: there is no setting behind
    this table, no seed and no fallback, so a row here is the only authority there is on where
    a customer's complaint gets posted. And the invariant that keeps that answer singular is a
    PARTIAL UNIQUE index — at most one row with ``is_support_group`` true — which lives in the
    model's ``__table_args__`` and is therefore built by ``create_all`` only if the model is
    registered. An unregistered model would not turn this suite red; it would leave every test
    of the picker green against a database with no ``bot_chats`` table at all, having never
    once exercised the constraint that stops two groups each receiving half the tickets.
    """
    # Arrange / Act
    registered = set(Base.metadata.tables)

    # Assert
    assert _BOT_CHATS_TABLE in registered, (
        f"{_BOT_CHATS_TABLE} is created by revision 0028 but no model declares it; "
        "import BotChatRow in src/bayram/db/models/__init__.py"
    )


def test_the_approved_lyrics_revision_is_reachable_from_head() -> None:
    # Arrange — walk_revisions starts at head, so membership proves the chain resolves.
    script = ScriptDirectory.from_config(_config())

    # Act
    revisions = {revision.revision for revision in script.walk_revisions()}

    # Assert — a revision whose down_revision is missing makes the whole chain unusable.
    assert _APPROVED_LYRICS_REVISION in revisions
    assert _REVISION_BEFORE_APPROVED_LYRICS in revisions


# ---------------------------------------------------------------------------
# SQLite — runs everywhere, no Docker
# ---------------------------------------------------------------------------
def test_upgrade_creates_every_expected_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "migrate.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert
    created = set(_schema_of(url))
    assert created == set(_EXPECTED_TABLES)
    assert created >= _CORE_TABLES, f"missing core tables: {sorted(_CORE_TABLES - created)}"


def test_the_migrated_schema_matches_the_model_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "compare.db")
    _upgrade(url, monkeypatch)

    # Act
    migrated = _schema_of(url)
    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }

    # Assert — this is what licenses every other test to build its schema with create_all.
    assert migrated == expected


def test_the_migrated_indexes_match_the_model_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index declared in a migration and not on a model is an index ``create_all`` — and
    therefore the whole unit suite and the admin container's schema shortcut — does not
    build. That divergence is how three unused read indexes reached review: every test ran
    against query plans production would never have."""
    # Arrange
    url = _sqlite_url(tmp_path, "indexes.db")
    _upgrade(url, monkeypatch)

    # Act
    migrated = _indexes_of(url)
    expected = {
        name: {index.name for index in table.indexes if index.name is not None}
        | {f"ix_{name}_{column.name}" for column in table.columns if column.index}
        for name, table in Base.metadata.tables.items()
    }

    # Assert — declared-but-uncreated is the failure that matters; SQLite also reports
    # implicit unique-constraint indexes the metadata does not name, so those are excluded
    # by comparing in one direction.
    missing = {
        table: sorted(names - migrated.get(table, set()))
        for table, names in expected.items()
        if names - migrated.get(table, set())
    }
    assert missing == {}, f"declared on the model but not created by the chain: {missing}"


def test_the_hand_named_vendor_rollup_index_is_actually_created_by_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The composite index the vendor rollup reads on, asserted by name.

    ``test_the_migrated_indexes_match_the_model_metadata`` above would catch this too, but
    only as one entry in a diff of every table in the schema. Naming it here says which
    index and why: a rollup that filters ``created_at`` and groups by ``vendor`` over a
    table written once per vendor call is the one read in the panel that a missing index
    turns into a full scan.
    """
    # Arrange
    url = _sqlite_url(tmp_path, "vendor-index.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert
    assert _VENDOR_USAGE_INDEX in _indexes_of(url)[_VENDOR_USAGE_TABLE]


def test_the_capability_probe_on_cost_usd_is_indexed_by_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index that pays for itself on the deployment where it never matches.

    ``has_priced_vendor_usage`` asks ``WHERE cost_usd IS NOT NULL LIMIT 1``, and
    ``read_capabilities`` runs it on every ``/api/ops/pulse`` — a five-second poll from the
    Live screen. Where a priced row exists the ``LIMIT 1`` stops at the first one and this
    index is invisible; where none does there is nothing to stop at, and without the index
    that is a full scan of the fastest-growing table in the schema, twelve times a minute,
    for as long as nobody configures a rate.
    """
    # Arrange
    url = _sqlite_url(tmp_path, "vendor-cost-index.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert
    assert _VENDOR_USAGE_COST_INDEX in _indexes_of(url)[_VENDOR_USAGE_TABLE]


def test_the_support_card_latch_is_unique_per_chat_and_not_per_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chain builds ``UNIQUE (group_chat_id, group_message_id)`` and nothing narrower.

    REGRESSION, and asserted against the CHAIN rather than the metadata because that is where
    the defect lived: revision 0027 shipped ``ix_support_tickets_group_message_id`` UNIQUE over
    the column alone. A Telegram ``message_id`` is a per-chat counter, so that index asserts
    something Telegram never promised — and the row it costs is not a rejected duplicate, it is
    a ticket whose card posted fine and then could not be latched.

    The scenario, traced end to end: the support group moves (a new group, or Telegram
    auto-upgrading a basic group to a supergroup, which CHANGES the chat id) and an operator
    repoints ``BAYRAM_SUPPORT_GROUP_CHAT_ID``. Old rows still hold message ids 2, 5, 9… from the
    old chat. ``_send_card`` succeeds, Telegram returns ``message_id=5`` in the NEW chat,
    ``claim_group_post``'s UPDATE trips the global unique index, the commit raises
    ``IntegrityError``, ``run_guarded`` converts it to an ``Err`` — and the ticket is left
    permanently un-latched beside an orphan card nothing can edit or relay from.

    ``test_the_migrated_indexes_match_the_model_metadata`` cannot catch this: it compares index
    NAMES in one direction only, so a name that matches while spanning the wrong columns, or
    carrying the wrong uniqueness, passes it cleanly.
    """
    # Arrange
    url = _sqlite_url(tmp_path, "support-card-index.db")

    # Act
    _upgrade(url, monkeypatch)
    indexes = _index_columns_of(url, _SUPPORT_TICKETS_TABLE)

    # Assert — the pair, in order, unique.
    assert indexes.get(_SUPPORT_CARD_INDEX) == (("group_chat_id", "group_message_id"), True)
    # And nothing in the chain enforces uniqueness on the message id by itself, whatever it is
    # called. Checked by SHAPE rather than by name so a renamed revival is caught too.
    global_uniques = sorted(
        name
        for name, (columns, unique) in indexes.items()
        if unique and columns == ("group_message_id",)
    )
    assert global_uniques == [], (
        f"{global_uniques} makes a per-chat Telegram message id globally unique; the latch "
        "must be UNIQUE (group_chat_id, group_message_id)"
    )


def test_the_support_group_selection_index_is_unique_and_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chain builds ``UNIQUE (is_support_group) WHERE is_support_group``, both halves.

    Asserted against the CHAIN rather than the metadata, and in three parts, because each part
    fails differently and only one of them is visible to any other test in this file.

    ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES in one
    direction only, so an index correct in name and wrong in everything else passes it
    cleanly. The UNIQUE half is the invariant itself: without it two operators pressing Select
    at the same moment can each clear the row they read and set their own, and two groups then
    receive half the tickets each with nothing to say which is right. The PARTIAL half is the
    one a "simplification" reaches for, and dropping it is far worse than it looks — a plain
    ``UNIQUE (is_support_group)`` allows one ``true`` row and one ``false`` row, so the table
    would silently refuse the third chat the bot is ever added to.

    The ``WHERE`` clause is read out of ``sqlite_master`` because the shape helper above cannot
    see it: SQLAlchemy reports an index's columns and its uniqueness, and a partial index and a
    total one are identical in both. Revision ``0010``'s active-OWNER index is the precedent
    for the predicate being a bare column name — SQLite evaluates an integer column as a
    boolean and Postgres takes a boolean column directly, so one string renders on both
    engines, which ``test_migration_applies_and_reverses_against_postgres`` is what proves.
    """
    # Arrange
    url = _sqlite_url(tmp_path, "support-group-index.db")

    # Act
    _upgrade(url, monkeypatch)
    indexes = _index_columns_of(url, _BOT_CHATS_TABLE)

    def _read_sql(connection: Connection) -> str | None:
        return connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"),
            {"name": _SELECTED_SUPPORT_GROUP_INDEX},
        ).scalar_one_or_none()

    async def _run() -> str | None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read_sql)
        finally:
            await engine.dispose()

    created_sql = asyncio.run(_run())

    # Assert — one column, unique, and partial.
    assert indexes.get(_SELECTED_SUPPORT_GROUP_INDEX) == (("is_support_group",), True)
    assert created_sql is not None, f"{_SELECTED_SUPPORT_GROUP_INDEX} was not created at all"
    assert "WHERE" in created_sql.upper(), (
        f"{_SELECTED_SUPPORT_GROUP_INDEX} is not partial: {created_sql!r}. A total "
        "UNIQUE (is_support_group) permits one selected row AND one unselected row, so the "
        "table would refuse the third group the bot is added to."
    )


def test_upgrade_then_downgrade_leaves_no_tables_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "reverse.db")
    _upgrade(url, monkeypatch)

    # Act
    _downgrade(url, monkeypatch)

    # Assert
    assert _schema_of(url) == {}


def test_upgrade_is_idempotent_when_already_at_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "twice.db")
    _upgrade(url, monkeypatch)

    # Act — a redeploy re-runs `alembic upgrade head`; it must be a no-op.
    _upgrade(url, monkeypatch)

    # Assert
    created = set(_schema_of(url))
    assert created == set(_EXPECTED_TABLES)
    assert created >= _CORE_TABLES


def test_the_approved_lyrics_column_is_added_and_dropped_by_its_own_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — stop one revision short of the column.
    url = _sqlite_url(tmp_path, "lyrics.db")
    _upgrade(url, monkeypatch, to=_REVISION_BEFORE_APPROVED_LYRICS)
    before = _schema_of(url)["briefs"]

    # Act
    _upgrade(url, monkeypatch, to=_APPROVED_LYRICS_REVISION)
    after = _schema_of(url)["briefs"]
    _downgrade(url, monkeypatch, to=_REVISION_BEFORE_APPROVED_LYRICS)
    reverted = _schema_of(url)["briefs"]

    # Assert — the column is exactly what the revision adds, and batch_alter_table rebuilds
    # the SQLite table on the way back down without losing any of its other columns.
    assert _APPROVED_LYRICS_COLUMN not in before
    assert after == before | {_APPROVED_LYRICS_COLUMN}
    assert reverted == before


def test_the_migration_records_its_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "stamp.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert — without the version table, the next upgrade would re-run everything.
    def _read(connection: Connection) -> list[str]:
        return inspect(connection).get_table_names()

    async def _run() -> list[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    assert _ALEMBIC_TABLE in asyncio.run(_run())


# ---------------------------------------------------------------------------
# Postgres — the engine production actually runs on (SoW DAT-4)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_migration_applies_and_reverses_against_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — requires `docker compose up -d`.
    _require_postgres(_POSTGRES_URL)
    _downgrade(_POSTGRES_URL, monkeypatch)

    # Act
    _upgrade(_POSTGRES_URL, monkeypatch)
    applied = _schema_of(_POSTGRES_URL)
    _downgrade(_POSTGRES_URL, monkeypatch)
    reversed_schema = _schema_of(_POSTGRES_URL)

    # Assert
    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    assert applied == expected
    assert reversed_schema == {}
