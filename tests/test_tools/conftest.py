"""Fixtures for the operator CLIs.

The database fixtures are RE-EXPORTED from ``tests.test_db.conftest`` rather than rebuilt.
A second in-memory engine defined here would drift from the one the rest of the suite runs
on — and the whole point of these tests is that the CLI writes through the same store the
product does, against the same schema.
"""

from __future__ import annotations

from tests.test_db.conftest import clock, engine, sessions

__all__ = ["engine", "sessions", "clock"]
