"""Every mapped class, imported here so ``Base.metadata`` is complete.

SQLAlchemy resolves the string annotations in a relationship against the declarative
registry, which only knows a class once its module has been imported. Importing them all
in one place is what makes ``create_all`` and Alembic autogenerate see the whole schema
regardless of which module a caller reached for first — a model missing from this list is
a table the migration test cannot see and the SQLite suite silently does without.
"""

from __future__ import annotations

from hbd.db.base import Base
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.admin_user import AdminUserRow
from hbd.db.models.asset import AssetRow
from hbd.db.models.audit_anchor import AuditChainAnchorRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.credit_account import CreditAccountRow
from hbd.db.models.credit_ledger import CreditLedgerRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.lyric_budget import LyricBudgetRow
from hbd.db.models.name_record import NameRecordRow
from hbd.db.models.order import OrderRow
from hbd.db.models.purge_run import PurgeRunRow
from hbd.db.models.user import UserRow

__all__ = [
    "Base",
    "UserRow",
    "OrderRow",
    "BriefRow",
    "AssetRow",
    "NameRecordRow",
    "GenerationAttemptRow",
    "AdminUserRow",
    "AdminSessionRow",
    "AdminAuditRow",
    "AuditChainAnchorRow",
    "CreditAccountRow",
    "CreditLedgerRow",
    "LyricBudgetRow",
    "PurgeRunRow",
]
