"""Every mapped class, imported here so ``Base.metadata`` is complete.

SQLAlchemy resolves the string annotations in a relationship against the declarative
registry, which only knows a class once its module has been imported. Importing all six
in one place is what makes ``create_all`` and Alembic autogenerate see the whole schema
regardless of which module a caller reached for first.
"""

from __future__ import annotations

from hbd.db.base import Base
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.name_record import NameRecordRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow

__all__ = [
    "Base",
    "UserRow",
    "OrderRow",
    "BriefRow",
    "AssetRow",
    "NameRecordRow",
    "GenerationAttemptRow",
]
