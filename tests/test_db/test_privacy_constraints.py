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
    }

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
