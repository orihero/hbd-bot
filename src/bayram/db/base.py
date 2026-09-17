"""Declarative base, portable column types and shared mixins.

Two portability rules hold for every model in this package, because unit tests run on
SQLite while production runs on Postgres and a schema that only works on one of them is
a schema nobody can test:

* **No native database enums.** Every enum column is ``VARCHAR(32)`` with the Python
  enum enforced in the mapper. Altering a native Postgres enum inside a migration is a
  lock-taking special case for no benefit here.
* **No naive datetimes, ever.** SQLite discards the timezone offset it is handed, so a
  round trip would silently turn an aware UTC value into a naive one and every retention
  comparison downstream would be wrong by whatever the reader's assumption was.
  :class:`UtcDateTime` rejects naive input on the way in and re-attaches UTC on the way
  out, so the boundary is enforced rather than hoped for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy import MetaData, types
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "Base",
    "NAMING_CONVENTION",
    "UtcDateTime",
    "enum_type",
    "utc_now",
    "TimestampMixin",
    "ENUM_LENGTH",
    "SHA256_LENGTH",
]

#: Deterministic constraint names. Without these, Alembic autogenerate emits unnamed
#: constraints that SQLite's batch-mode ALTER cannot later drop by name.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Every persisted enum value fits comfortably. The longest across ``bayram.contracts`` and
#: ``bayram.db.enums`` is 17 characters (``GenerationKind.NAME_VERIFICATION``) — not a value
#: in ``bayram.contracts``, as this note used to imply. The margin is kept rather than trimmed
#: because widening a Postgres ``VARCHAR`` later is a migration and the space is free;
#: ``tests/test_db/test_enum_lengths.py`` fails the build if a new member outgrows it,
#: since SQLite would accept the over-length value and only Postgres would reject it.
ENUM_LENGTH: Final[int] = 32
SHA256_LENGTH: Final[int] = 64


def utc_now() -> datetime:
    """Current instant, always aware. Call sites pass ``now`` explicitly where testable."""
    return datetime.now(UTC)


class UtcDateTime(types.TypeDecorator[datetime]):
    """``timestamptz`` that survives SQLite.

    Naive input is a bug at the call site, not something to paper over, so it raises
    rather than guessing which zone the caller meant.
    """

    impl = types.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                f"naive datetime rejected by UtcDateTime; pass an aware value (got {value!r})"
            )
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_type[E: StrEnum](enum_cls: type[E], *, length: int = ENUM_LENGTH) -> sa.Enum:
    """A ``VARCHAR`` column that stores the enum's *value*, not its member name.

    ``values_callable`` is the difference between persisting ``"uz_latn"`` (stable, the
    thing every other layer speaks) and ``"UZ_LATN"`` (an implementation detail of the
    Python class that a rename would silently break).
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    """Declarative base for every table in this package."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        identifier: Any = getattr(self, "id", None)
        return f"{type(self).__name__}(id={identifier!r})"


class TimestampMixin:
    """``created_at`` / ``updated_at`` in UTC, defaulted by the database clock."""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
