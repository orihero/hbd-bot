"""Wire models for ``GET /api/admins`` — the operator roster, minus the credential.

**``password_hash`` is absent, not masked.** It is the whole credential record — the
argon2id PHC string carries its own salt and parameters (:mod:`hbd.db.models.admin_user`) —
so there is no redacted form of it that is worth anything to a panel and every form of it is
worth something to an attacker holding a response body. :class:`AdminAccountView` therefore
names the eight fields it exposes one at a time rather than projecting the row and dropping
a key: a denylist ships whatever column somebody adds to ``admin_users`` next.

**Usernames are in the clear, and that is not a masking exemption being waved through.**
§12.3 governs *customer* personal data; an operator is staff, their account is the thing
this endpoint exists to enumerate, and a roster of ``o•••`` answers no question anybody
would open it to ask. ``mask_name`` is deliberately not imported here.

**Deactivated accounts are in the list.** They still own audit rows, they can still be
reactivated, and a roster that hides them answers "who has access?" with a number smaller
than the number of credentials that exist. ``isActive`` is on the wire so the panel can grey
them rather than omit them — the same reason :func:`hbd.db.admin.accounts.list_all` returns
them.

**``mustChangePassword`` and ``passwordChangedAt`` are here because they are the two facts
that make a roster actionable**: the first names an account still holding a password
somebody else chose, and the second is the instant every session issued before it became
void (§12.1 T9). Neither is derivable from the other.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from hbd.admin.schemas.common import ApiModel
from hbd.db.enums import AdminRole
from hbd.db.models.admin_user import AdminUserRow

__all__ = [
    "AdminAccountView",
    "AdminRosterResponse",
    "to_account_view",
    "to_roster",
]


class AdminAccountView(ApiModel):
    """One ``admin_users`` row as the panel sees it. Eight fields, named individually."""

    id: UUID
    username: str
    role: AdminRole
    #: ``false`` for an account that exists and cannot sign in. Never a reason to omit it.
    is_active: bool
    must_change_password: bool
    #: ``null`` for an account that has never been signed into — which is a different fact
    #: from one whose last login is old, and the one worth chasing after a handover.
    last_login_at: datetime | None
    password_changed_at: datetime
    created_at: datetime


class AdminRosterResponse(ApiModel):
    """``GET /api/admins``. A bounded whole-table read, so there is no page meta.

    ``admin_users`` is capped by :data:`hbd.db.admin.accounts.MAX_ADMIN_ACCOUNTS`, and a
    deployment with more operator accounts than that is one nobody designed. Paging it
    would put a cursor between an operator and the question "who has access?", whose only
    useful answer is the whole list at once.
    """

    items: list[AdminAccountView]


def to_account_view(row: AdminUserRow) -> AdminAccountView:
    """Project one operator onto the wire. Every exposed field is written out by hand."""
    return AdminAccountView(
        id=row.id,
        username=row.username,
        role=row.role,
        is_active=row.is_active,
        must_change_password=row.must_change_password,
        last_login_at=row.last_login_at,
        password_changed_at=row.password_changed_at,
        created_at=row.created_at,
    )


def to_roster(rows: Iterable[AdminUserRow]) -> AdminRosterResponse:
    """The whole roster, in the order the query returned it — oldest account first."""
    return AdminRosterResponse(items=[to_account_view(row) for row in rows])
