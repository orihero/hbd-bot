"""No recipient birth year exists anywhere. Enforced, not documented.

SoW FR-102, DAT-5 and LR-69 all say the same thing: the reminder record holds day and
month, and **no schema column, API field, export or log may contain a recipient birth
year**. Day and month is not a date of birth; the year is the component that would turn it
into one, and the product needs nothing the year would buy.

DAT-5 asks specifically for "a CI check that fails any migration adding one". These tests
are that check. They scan two independent surfaces, because either one alone can be
bypassed:

* the **live metadata**, which catches a column added to a model;
* the **migration files on disk**, which catches a column added by hand-written DDL that
  never made it into a model.

A future migration that reintroduces a birth year fails the build here, with a message
naming the offending column, rather than passing review because nobody remembered the rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from hbd.db.models import Base, BriefRow

#: Column-name shapes that would constitute, or trivially reconstruct, a date of birth.
#: A stored age is on the list because an age plus a timestamp is a birth year with one
#: subtraction — the SoW's own reasoning for why the year, and not the day and month, is
#: the component that makes the record sensitive.
#: ``birthday`` is deliberately absent: day-and-month is the permitted record (FR-71).
_BIRTH_YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:^|_)(?:"
    r"birth_?years?|years?_?of_?birth|birth_?yr|"
    r"date_?of_?birth|birth_?date|birthdate|dob|"
    r"ages?_?years?|age"
    r")(?:$|_)",
    re.IGNORECASE,
)

#: ``sa.Column('name', ...)`` — the NAME only. Matching a whole migration line would trip
#: over the string ``'birthday'`` inside the ``occasion`` enum, which is a value, not a
#: column, and flagging it would train people to ignore this check.
_MIGRATION_COLUMN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"sa\.Column\(\s*['\"]([A-Za-z0-9_]+)['\"]"
)

#: Columns that legitimately match and are NOT personal data. Empty, and it should stay so.
_ALLOWED: Final[frozenset[str]] = frozenset()

_MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _all_columns() -> tuple[tuple[str, str], ...]:
    return tuple(
        (table_name, column.name)
        for table_name, table in Base.metadata.tables.items()
        for column in table.columns
    )


def test_no_table_has_a_recipient_birth_year_column() -> None:
    # Arrange
    columns = _all_columns()

    # Act
    offenders = [
        f"{table}.{column}"
        for table, column in columns
        if _BIRTH_YEAR_PATTERN.search(column) and column not in _ALLOWED
    ]

    # Assert
    assert offenders == [], (
        "SoW FR-102 / DAT-5 / LR-69: no recipient birth year may exist in any column. "
        f"Offending columns: {offenders}"
    )


def test_the_briefs_table_has_no_column_named_for_a_year() -> None:
    # Arrange
    brief_columns = {column.name for column in BriefRow.__table__.columns}

    # Act / Assert — named explicitly because this is the table that would grow one.
    assert "event_year" not in brief_columns
    assert "birth_year" not in brief_columns
    assert "recipient_birth_year" not in brief_columns


def test_the_briefs_table_stores_day_and_month_and_nothing_more() -> None:
    # Arrange
    brief_columns = {column.name for column in BriefRow.__table__.columns}

    # Act
    date_columns = {name for name in brief_columns if name.startswith("event_")}

    # Assert — day and month is the whole of the occasion date.
    assert date_columns == {"event_day", "event_month"}


@pytest.mark.parametrize(
    "column_name",
    ["event_day", "event_month"],
)
def test_the_occasion_date_columns_are_nullable(column_name: str) -> None:
    # Arrange
    column = BriefRow.__table__.columns[column_name]

    # Act / Assert — the date is optional; a birthday song does not require one.
    assert column.nullable is True


def test_no_migration_on_disk_introduces_a_birth_year_column() -> None:
    # Arrange
    migration_files = sorted(_MIGRATIONS_DIR.glob("*.py"))
    assert migration_files, "expected at least the initial migration to exist"

    # Act
    offenders: list[str] = []
    for path in migration_files:
        for column_name in _MIGRATION_COLUMN_PATTERN.findall(path.read_text(encoding="utf-8")):
            if _BIRTH_YEAR_PATTERN.search(column_name) and column_name not in _ALLOWED:
                offenders.append(f"{path.name}: {column_name}")

    # Assert
    assert offenders == [], (
        "SoW DAT-5: a migration must never add a recipient birth-year column. "
        f"Offending lines: {offenders}"
    )


def test_the_initial_migration_creates_the_day_and_month_columns() -> None:
    # Arrange
    sources = "\n".join(path.read_text(encoding="utf-8") for path in _MIGRATIONS_DIR.glob("*.py"))

    # Act — reuse the column extractor so a reformat (quote style, line wrapping) cannot
    # turn the positive half of this check into a false pass.
    created = set(_MIGRATION_COLUMN_PATTERN.findall(sources))

    # Assert — the columns we DO want are actually created.
    assert {"event_day", "event_month"} <= created


def test_every_table_holding_personal_data_carries_an_expiry_column() -> None:
    """A column check, and ONLY a column check — see the note below.

    This guard was the one that should have caught ``admin_audit_log``'s two decorative
    clocks and it could not: it asserts a clock column EXISTS, never that anything reads it.
    ``admin_audit_log`` passed cleanly while ``reason_text`` was retained forever, and
    ``admin_sessions`` was not in the set at all. It is kept because a missing column is
    still worth catching early and cheaply, but the real guard is
    ``tests/test_db/test_audit_retention.py::test_every_retention_clock_in_the_schema_is_read_by_a_sweep``,
    which derives the answer from ``rows_past_expiry_statements``' own predicates.

    **A personal-data table now has two lawful answers, and exactly two.** It is either on a
    clock (below) or erased on request (the second set), and it may never be in neither. The
    second set exists because ``user_profiles`` genuinely has no ``*_expires_at`` and adding
    it above would make this test fail for a table that is behaving correctly — at which
    point the cheap way out is to say nothing about it at all, which is precisely the silent
    exemption this file's own comment calls out. Naming it is what keeps the omission a
    decision instead of an oversight.
    """
    # Arrange — the purge is a single indexed predicate per table only if this holds.
    # ``admin_audit_log`` is here for one column: ``reason_text``, the operator's optional
    # free text, which really does read "Dilnoza asked us to delete her mother's song". It
    # carries two clocks — ``reason_expires_at`` at 90 days for that text and ``expires_at``
    # at 730 days for the row — and this set is hardcoded, so a new table is silently exempt
    # until it is named here (ADMIN_PANEL_PLAN §5.4).
    tables_with_personal_data = {
        "briefs",
        "assets",
        "generation_attempts",
        "name_records",
        "admin_audit_log",
        "chat_messages",
    }
    # ``vendor_usage`` (revision 0016) is deliberately in NEITHER set. It holds no personal
    # data to be clocked or erased: every column is a closed enum, an integer, a machine id
    # (an adapter name, a vendor model id, a correlation id) or a bounded error code from the
    # ``hbd.errors`` taxonomy — no name, no note, no lyric, no transcript, no telegram id, no
    # free text of any kind — so there is nothing on that table that is text ABOUT a person.
    # Written down because the comment above says a table not named here is silently exempt,
    # and this one's exemption has to stay a decision. Its growth is still bounded, by a
    # 400-day CUTOFF on ``created_at`` in ``hbd.db.purge``; a cutoff is not a clock, which is
    # why no column on it ends in ``expires_at`` and why ``test_audit_retention.py`` passes
    # over it by construction, exactly as it does over ``user_profiles``.
    #
    # ``vendor_balances`` (revision 0019) is deliberately in NEITHER set, on ``vendor_usage``'s
    # argument and slightly stronger. Every column is a closed enum, a number, a boolean, an
    # instant, a machine id (the probe's own name), a bounded string from the VENDOR's own
    # vocabulary (plan tier, subscription status, reset hint) or a bounded error code from the
    # ``hbd.errors`` taxonomy — and the row is about OUR account with a vendor, not about a
    # customer at all. ONE FIELD WAS AVAILABLE AND IS DELIBERATELY NOT STORED, which is what
    # keeps that claim true rather than nearly true: OpenRouter's ``data.label`` is the
    # operator's own free-text name for the API key and reads in practice like "Sardor laptop
    # dev key". It is the only field on either vendor's response that could carry a person's
    # name and it buys no tile anything. The table is on NO retention cutoff either, and that
    # is not an oversight: its primary key is a five-member enum crossed with a boolean, so it
    # is bounded BY CONSTRUCTION at ten rows and is UPDATEd in place; the history a cache
    # discards is written to ``vendor_usage`` with ``operation=HEALTH``, which the 400-day
    # cutoff already covers.
    #
    # ``user_activity_snapshots`` (revision 0018) is deliberately in NEITHER set, and this is
    # the strongest of the three claims. Every column is a calendar date, a UTC instant or an
    # integer count over the ENTIRE user population: nothing is keyed to an account, nothing
    # can be attributed to a person, and no row narrows to fewer than everybody — so there is
    # no personal data to put on a clock and nothing for ``/forget`` to erase. It holds for a
    # structural reason worth stating: the day grain was chosen OVER a (day, user) grain
    # PRECISELY so this would be true. A (day, user) table would have been a per-person
    # movement log — personal data, needing a clock, a sweep and an erasure route, and building
    # the per-customer surveillance record the panel already refuses by withholding
    # ``users.last_seen_at`` from every ``/users`` view. Consequently no column there is named
    # ``*_expires_at`` and it is on no cutoff at all: one row per day is 365 a year, and the
    # long history IS the metric.
    #
    # ``bot_membership_events`` (revision 0017) is deliberately in NEITHER set, and it may NOT
    # borrow ``vendor_usage``'s argument above: unlike ``vendor_usage`` it carries a
    # ``telegram_user_id`` and is therefore about an identified person. Its route is
    # ``credit_ledger``'s and ``plan_purchases``' — both of which are in neither set for the
    # same reason — namely erasure by ANONYMISATION on request, in
    # ``hbd.db.credit_erasure.forget_account``, which nulls ``telegram_user_id`` and keeps the
    # row so the aggregate survives. (The column is nullable for exactly and only that
    # purpose; the arm that nulls it lands with the churn write path.) It is NOT in
    # ``tables_erased_on_request`` because that set's stated semantics are "the absence of a
    # row IS the erasure record; ``/forget`` DELETEs it outright", which is ``user_profiles``'
    # treatment and the opposite of this one. It is NOT in ``tables_with_personal_data``
    # because that set demands a ``*_expires_at`` clock, and adding that suffix here would
    # oblige a sweep BY NAME in ``tests/test_db/test_audit_retention.py`` and claim a legal
    # schedule this table does not have — its bound is a 400-day CUTOFF on ``at``
    # (``hbd.db.purge.BOT_MEMBERSHIP_RETENTION_DAYS``), which is defence in depth beside the
    # erasure arm and never a substitute for it.
    #
    # ``topup_purchases`` (revision 0020) — AND ``plan_purchases`` (revision 0015), which has
    # been silently exempt ever since and is named here so it stops being — are deliberately in
    # NEITHER set, by the same third route. Not personal data: every column is a Telegram id,
    # an integer, a three-letter ISO currency, a closed enum, a machine-built idempotency key,
    # a rail's own reference or a clock — no name, no note, no lyric, no free text of any kind,
    # so nothing there is text ABOUT a person, which is precisely the argument
    # ``credit_ledger`` and ``credit_accounts`` already make for holding a ``telegram_user_id``
    # without being classified as personal data. Not erased-on-request either, because they are
    # erased by ANONYMISATION: the id comes off and the amount, the rail, the reference, the key
    # and the clock stay. A deleted receipt would make ``/forget`` mean "refund me" and would
    # destroy the answer to a billing dispute for everyone, which is why neither is on any
    # retention clock and why neither carries a ``*_expires_at``.
    #
    # ``payment_intents``, ``payme_transactions`` and ``payme_rpc_log`` (revision 0023) are all
    # three deliberately in NEITHER set, by that same third route, and their arguments get
    # progressively stronger.
    #
    # ``payment_intents`` is the receipt tables' argument almost word for word: every column is
    # a Telegram id, an integer, a three-letter ISO currency, a closed enum, a machine-built
    # idempotency key, an opaque hex token minted by ``secrets.token_hex``, a merchant account
    # id, a boolean or a clock — no name, no note, no lyric, no free text of any kind, so
    # nothing on it is text ABOUT a person. Its erasure route is ANONYMISATION in
    # ``hbd.db.credit_erasure.forget_account``, which nulls ``telegram_user_id`` and keeps
    # everything else. It is NOT in ``tables_erased_on_request`` because that set's stated
    # semantics are "the absence of a row IS the erasure record", and here the absence of a row
    # would be a LIE TOLD TO A THIRD PARTY: the payment rail keeps its own copy of the
    # transaction permanently and can ask us about it through a statement call over an
    # arbitrary period, so a deleted intent makes us answer "we have never heard of this
    # payment" about money a customer really paid. It is NOT in ``tables_with_personal_data``
    # because that set demands an ``*_expires_at`` clock, and the one clock this table has —
    # ``valid_until``, how long the payment page stays payable — is a BUSINESS clock, named
    # without that suffix on purpose, exactly as ``plan_purchases.plan_ends_at`` is. Its growth
    # is bounded by a 400-day CUTOFF on ``created_at`` restricted to TERMINAL UNPAID rows
    # (``hbd.db.purge.PAYMENT_INTENT_RETENTION_DAYS``) — a ``paid`` intent is never swept —
    # which is defence in depth beside the erasure arm and never a substitute for it.
    #
    # ``payme_transactions`` makes a stronger claim than any receipt table above: IT HOLDS NO
    # TELEGRAM ID AT ALL. Every column is a UUID, the rail's own 24-character machine id, an
    # integer amount, a closed enum, the rail's numeric cancel reason or a clock. A person is
    # reachable from it only by joining through ``payment_intents`` — which is precisely the
    # join ``/forget`` breaks — so there is nothing on the row to null and no erasure arm to
    # write. It is on NO cutoff either, on ``topup_purchases``' argument at its strongest: it is
    # an audit fact about MONEY, it is the only record of what the rail says it charged, and
    # the rail may ask about any transaction it has ever created.
    #
    # ``payme_rpc_log`` is the strongest of the three, and the absence is designed rather than
    # incidental. It is the journal of inbound calls from the rail's servers, and it
    # deliberately carries NO ``telegram_user_id``, NO request body and NO header: every column
    # is a method name, an opaque reference, a machine id, an integer or ``peer_ip`` — the
    # address of PAYME's own server, published by them, never a customer's phone. Storing the
    # bodies would have been convenient and is refused for exactly this reason: it would drag
    # the one table an operator reads DURING an incident into the set above, onto a retention
    # clock, deleting itself on a schedule. Its growth is bounded by a 90-day CUTOFF on ``at``
    # (``hbd.db.purge.PAYME_RPC_LOG_RETENTION_DAYS``), which is ``vendor_usage``'s shape and
    # ``vendor_usage``'s argument.
    #
    # ``broadcasts``, ``broadcast_bodies`` and ``broadcast_recipients`` (revision 0024) are all
    # three deliberately in NEITHER set, and only the third one needs an argument.
    #
    # ``broadcasts`` holds a UUID, an operator's username, closed enums, integer counts, clocks,
    # a hex digest and the frozen segment document — and that document is a list of registry
    # KEYS and their bounded values (``plan_status in [lapsed]``), never a name, a number or
    # free text about anybody. It narrows to a population and never to a person. The free-text
    # half of the schedule reason is deliberately NOT copied onto it: that prose stays on
    # ``admin_audit_log``, which owns the 90-day clock and the sweep that clears it.
    # ``broadcast_bodies`` holds operator-authored copy addressed to a whole language group, and
    # the product rule that no ``{placeholder}`` interpolation exists at any layer is what keeps
    # that true — it is text FROM us, never text ABOUT a person.
    #
    # ``broadcast_recipients`` DOES carry a ``telegram_user_id`` and is therefore about an
    # identified person, so it may not borrow either argument above. Its route is
    # ``bot_membership_events``', ``credit_ledger``'s and ``plan_purchases``': erasure by
    # ANONYMISATION, nulling the id in place and keeping the row, which the unique constraint
    # is built to tolerate — both engines permit any number of NULLs, so an anonymised row stops
    # participating in uniqueness and keeps its count. It is NOT in ``tables_erased_on_request``
    # because that set's semantics are "the absence of a row IS the erasure record", and
    # deleting these rows would silently rewrite the delivery record of a campaign that has
    # already gone out. It is NOT in ``tables_with_personal_data`` because that set demands a
    # ``*_expires_at`` clock, which would oblige a sweep BY NAME in ``test_audit_retention.py``
    # and claim a legal schedule this table does not have; its growth — the fastest in this
    # schema, one row per account per campaign — is bounded instead by a 400-day CUTOFF on
    # ``created_at`` (``hbd.db.purge.BROADCAST_RECIPIENT_RETENTION_DAYS``), counted by
    # ``purge_runs.broadcast_recipients_deleted``, which is defence in depth beside the
    # erasure arm and never a substitute for it.
    #
    # THE ROUTE IS THEREFORE THE THIRD ONE, STATED ONCE SO A LATER READER DOES NOT HAVE TO
    # RECONSTRUCT IT: identity leaves by ``hbd.db.credit_erasure.forget_account``'s
    # anonymising ``UPDATE``, growth leaves by ``hbd.db.purge._purge_broadcast_recipients``'
    # cutoff, and nothing about this table is on a clock. Moving it into either set above
    # would break one of those two: naming it personal data demands an ``*_expires_at`` the
    # sweep would then have to read as a legal schedule, and naming it erased-on-request
    # asserts that ``/forget`` DELETEs the row — which would rewrite the delivery record of a
    # campaign that has already gone out.
    #: Tables whose personal data is erased ON REQUEST rather than on a clock. The absence of
    #: a row IS the erasure record: ``/forget`` DELETEs it outright (PD-3, a full reset to
    #: first-contact state), so there is nothing for a sweep to find and no ``*_expires_at``
    #: to read. Naming the table here rather than adding it above is the difference between a
    #: documented erasure route and a silent exemption — and ``test_audit_retention.py``'s
    #: ``_clocks_in_the_schema`` keys off ``*_expires_at``, so it ignores this table by
    #: construction and needs no edit.
    tables_erased_on_request = {"user_profiles"}

    # Act
    missing = [
        name
        for name in tables_with_personal_data
        if not any(
            column.name.endswith("expires_at") for column in Base.metadata.tables[name].columns
        )
    ]

    # Assert
    assert missing == [], f"tables with personal data but no retention clock: {missing}"

    # Assert — the two sets are exclusive, and the second really has no clock. A table that
    # drifted into both would be claiming two contradictory erasure routes.
    assert tables_with_personal_data & tables_erased_on_request == set()
    for name in tables_erased_on_request:
        # A set that names a table nobody registered is how this check goes vacuously green:
        # ``Base.metadata.tables[name]`` below would raise, but only after the model file has
        # been written — and an unregistered model is exactly the failure
        # ``test_migrations.py::test_the_new_table_is_registered_as_well_as_migrated`` exists
        # for, so the membership is asserted here too rather than left to a KeyError.
        assert name in Base.metadata.tables, f"{name} is named here but registered nowhere"
        table = Base.metadata.tables[name]
        assert not any(column.name.endswith("expires_at") for column in table.columns), name


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "birth_year",
        "birthyear",
        "recipient_birth_year",
        "year_of_birth",
        "date_of_birth",
        "birth_date",
        "dob",
        "recipient_age",
        "age_years",
    ],
)
def test_the_guard_actually_flags_a_birth_year_column_name(forbidden_name: str) -> None:
    # Arrange / Act
    is_flagged = _BIRTH_YEAR_PATTERN.search(forbidden_name) is not None

    # Assert — a check that cannot fail is not a check. This proves it can.
    assert is_flagged, f"{forbidden_name!r} must be rejected by the birth-year guard"


@pytest.mark.parametrize(
    "permitted_name",
    ["event_day", "event_month", "created_at", "language", "occasion", "note"],
)
def test_the_guard_does_not_flag_a_legitimate_column_name(permitted_name: str) -> None:
    # Arrange / Act
    is_flagged = _BIRTH_YEAR_PATTERN.search(permitted_name) is not None

    # Assert — a check with false positives gets disabled, which is worse than no check.
    assert not is_flagged
