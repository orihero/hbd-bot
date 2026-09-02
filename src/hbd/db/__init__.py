"""Persistence for HBD Bot: mapped rows, repositories, and the retention purge.

The public surface is deliberately small. Everything outside this package talks to a
repository or to ``purge_expired``; nothing outside it should import a ``*Row`` class,
because a mapped row is an implementation detail with a session attached and the frozen
contract models are not.

The one thing to know before reading further: **the retention schedule is a legal
obligation** (SoW FIL-7, LR-52), it is expressed once in
:class:`hbd.db.retention.RetentionPolicy`, and every write stamps its own ``expires_at``
from it so the purge job is a single indexed predicate per table. And **no recipient birth
year exists in any column here** (FR-102, DAT-5, LR-69) — ``tests/test_db`` asserts that by
pattern across the whole metadata and every migration, so it cannot come back by accident.
"""

from __future__ import annotations

from hbd.db.attempts import (
    GenerationAttempt,
    GenerationAttemptRepository,
    StrategyStat,
)
from hbd.db.base import Base, utc_now
from hbd.db.credit_sql import verify_balances
from hbd.db.credits import SqlCreditLedger
from hbd.db.engine import create_engine, create_session_factory, ping
from hbd.db.enums import GenerationKind, NameSource
from hbd.db.guard import NotFoundError
from hbd.db.lyric_budget import SqlLyricBudget
from hbd.db.models import (
    AssetRow,
    BriefRow,
    GenerationAttemptRow,
    NameRecordRow,
    OrderRow,
    UserRow,
)
from hbd.db.models.credit_ledger import ACTOR_LENGTH
from hbd.db.names import NameRecordDraft, NameRecordRepository
from hbd.db.purge import PurgeReport, purge_expired
from hbd.db.repository import SqlKitRepository
from hbd.db.retention import (
    DEFAULT_RETENTION_POLICY,
    RetentionClass,
    RetentionPolicy,
    resolve_retention_policy,
)

__all__ = [
    # Schema
    "Base",
    "UserRow",
    "OrderRow",
    "BriefRow",
    "AssetRow",
    "NameRecordRow",
    "GenerationAttemptRow",
    "GenerationKind",
    "NameSource",
    # Engine
    "create_engine",
    "create_session_factory",
    "ping",
    "utc_now",
    # Repositories
    "SqlKitRepository",
    "GenerationAttemptRepository",
    "GenerationAttempt",
    "StrategyStat",
    "NameRecordRepository",
    "NameRecordDraft",
    "NotFoundError",
    # Entitlements. The ledger's *rows* are deliberately absent, like every other ``*Row``:
    # ``SqlCreditLedger`` returns the frozen ``hbd.entitlements`` view models instead, so a
    # gate never holds a mapped object with a closed session attached. ``verify_balances``
    # is exported because an operator tool and the tests both need to prove that
    # ``credit_accounts.balance`` still equals ``SUM(credit_ledger.delta)``.
    "SqlCreditLedger",
    "verify_balances",
    # The daily lyric-write ceiling. A SEPARATE seam from ``SqlCreditLedger`` on
    # purpose: the bot writes this counter and may never write a credit, and one store
    # carrying both would be the place that rule quietly stopped being true.
    "SqlLyricBudget",
    # The width of ``credit_ledger.actor``. A constant, not a row: the operator CLI has to
    # refuse a name that would be silently truncated, and it must not learn that number by
    # copying it.
    "ACTOR_LENGTH",
    # Retention
    "RetentionPolicy",
    "RetentionClass",
    "DEFAULT_RETENTION_POLICY",
    "resolve_retention_policy",
    "PurgeReport",
    "purge_expired",
]
