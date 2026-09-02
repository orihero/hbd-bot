"""Every persisted enum value has to fit the column that stores it.

``enum_type()`` renders a ``VARCHAR(ENUM_LENGTH)``, not a native database enum, and the
two engines this project runs on disagree about what happens when a value is too long:
**SQLite stores it anyway** — ``VARCHAR(n)`` is advisory there, the declared length is not
enforced — while **Postgres raises** ``value too long for type character varying(32)``.
So a new enum member of 33 characters passes the entire unit suite and fails on the first
insert in production. Nothing else in the suite can catch that, because nothing else in
the suite runs on Postgres.

Two passes, deliberately:

* over the live schema, so a column declared with a custom ``length=`` is checked against
  the values it will actually receive;
* over every ``StrEnum`` declared in ``hbd.contracts`` or anywhere under ``hbd.db``, so a
  member added ahead of the table that will store it is checked before the migration lands
  rather than after.

The second pass walks ``hbd.db`` rather than naming modules, because an enum's home is
wherever its subject lives: ``RetentionClass`` sits with the retention policy in
``hbd.db.retention``, ``AuditOutcome`` with the audit row it grades. A hand-kept list of
"the modules that declare enums" is one new module out of date, and the final test in this
file — which proves the sweep covers everything the schema stores — is what that staleness
comes back as. Modules outside ``hbd.db`` are deliberately excluded: ``ErrorCode`` and
``Permission`` are never written to a ``VARCHAR(32)``, so holding them to that width would
be a bound nobody chose.
"""

from __future__ import annotations

import importlib
import pkgutil
from enum import StrEnum
from types import ModuleType

import pytest
import sqlalchemy as sa

from hbd import contracts
from hbd.db.base import ENUM_LENGTH
from hbd.db.models import Base


def _db_package_modules() -> tuple[ModuleType, ...]:
    """Every module under ``hbd.db``, imported so its ``StrEnum``s are visible."""
    package = importlib.import_module("hbd.db")
    return (
        package,
        *(
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(package.__path__, prefix="hbd.db.")
        ),
    )


#: The modules whose ``StrEnum``s may reach an ``enum_type()`` column.
_ENUM_MODULES: tuple[ModuleType, ...] = (contracts, *_db_package_modules())


def _declared_str_enums(module: ModuleType) -> tuple[type[StrEnum], ...]:
    """Every ``StrEnum`` defined *in* ``module`` — not merely imported into it."""
    return tuple(
        obj
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, StrEnum) and obj.__module__ == module.__name__
    )


def _all_declared_str_enums() -> tuple[type[StrEnum], ...]:
    return tuple(item for module in _ENUM_MODULES for item in _declared_str_enums(module))


def _enum_columns() -> tuple[tuple[str, sa.Enum], ...]:
    """``("table.column", type)`` for every enum column in the mapped schema."""
    return tuple(
        (f"{table.name}.{column.name}", column.type)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Enum)
    )


# ---------------------------------------------------------------------------
# The live schema
# ---------------------------------------------------------------------------
def test_the_schema_actually_has_enum_columns_to_check() -> None:
    # Arrange / Act — a refactor that stopped using enum_type() would otherwise make every
    # parametrised test below vacuously pass by collecting nothing.
    columns = _enum_columns()

    # Assert
    assert columns


@pytest.mark.parametrize(
    ("label", "column_type"), _enum_columns(), ids=[label for label, _ in _enum_columns()]
)
def test_every_enum_column_is_wide_enough_for_its_own_values(
    label: str, column_type: sa.Enum
) -> None:
    # Arrange
    declared_length = column_type.length
    assert declared_length is not None, f"{label} has no VARCHAR length"

    # Act
    longest = max(column_type.enums, key=len)

    # Assert — Postgres raises on the insert; SQLite would have accepted it silently.
    assert len(longest) <= declared_length, (
        f"{label} stores VARCHAR({declared_length}) but {longest!r} is {len(longest)} chars"
    )


def test_no_enum_column_uses_a_native_database_enum() -> None:
    # Arrange / Act — native enums make an ALTER a lock-taking special case and do not
    # exist on SQLite, which is why db/base.py forbids them.
    native = [label for label, column_type in _enum_columns() if column_type.native_enum]

    # Assert
    assert native == []


# ---------------------------------------------------------------------------
# Every declared enum, table or no table yet
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "enum_cls", _all_declared_str_enums(), ids=[e.__name__ for e in _all_declared_str_enums()]
)
def test_every_declared_enum_value_fits_the_default_column_width(
    enum_cls: type[StrEnum],
) -> None:
    # Act
    longest = max((member.value for member in enum_cls), key=len)

    # Assert
    assert len(longest) <= ENUM_LENGTH, (
        f"{enum_cls.__name__}.{longest!r} is {len(longest)} chars; "
        f"enum_type() renders VARCHAR({ENUM_LENGTH})"
    )


def test_the_declared_sweep_covers_everything_the_schema_pass_does_and_more() -> None:
    # Arrange — the schema pass can only see an enum once some table stores it, so an enum
    # declared ahead of its migration is checked by the sweep alone. That only holds while
    # the sweep is a superset of the schema's own coverage: an enum class living outside
    # ``_ENUM_MODULES`` would be checked by exactly one pass and missed by the other.
    swept = set(_all_declared_str_enums())

    # Act
    stored = {
        column_type.enum_class
        for _, column_type in _enum_columns()
        if column_type.enum_class is not None
    }

    # Assert
    assert stored, "no enum_type() column resolved back to its StrEnum class"
    assert stored <= swept, (
        "enum classes stored by the schema but outside the declared sweep: "
        f"{sorted(cls.__name__ for cls in stored - swept)}"
    )
