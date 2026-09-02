"""Persistence for the admin panel's own tables.

Split from ``hbd.db.repository`` on purpose. The kit repository owns customer data behind
a ``Result``-returning facade because a bot handler must never see an exception; these
functions instead take an ``AsyncSession`` and let it propagate, because every admin call
site already runs inside one request-scoped transaction that must roll back as a whole —
an authentication that half-succeeded is worse than one that failed loudly.

For the same reason nothing here commits. The caller owns the transaction boundary, so a
login that writes a session row and then fails to write its audit entry leaves neither.
"""

from __future__ import annotations

from hbd.db.admin import accounts, sessions

__all__ = ["accounts", "sessions"]
