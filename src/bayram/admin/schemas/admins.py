"""Wire models for ``GET /api/admins`` — the operator roster, minus the credential.

**``password_hash`` is absent, not masked.** It is the whole credential record — the
argon2id PHC string carries its own salt and parameters (:mod:`bayram.db.models.admin_user`) —
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
them rather than omit them — the same reason :func:`bayram.db.admin.accounts.list_all` returns
them.

**``mustChangePassword`` and ``passwordChangedAt`` are here because they are the two facts
that make a roster actionable**: the first names an account still holding a password
somebody else chose, and the second is the instant every session issued before it became
void (§12.1 T9). Neither is derivable from the other.

**The create body carries a password and the response never does.**
:class:`AdminCreateRequest` is the one body in this module with a credential on it, so it
follows :mod:`bayram.admin.schemas.auth`'s rule exactly — ``repr=False``, because pydantic
renders a model into a validation error, into a debugger frame and into any log line that
interpolates it, and ``bayram.logging``'s redaction masks by key *name* only once the value
has already been turned into a string somewhere it might be kept. What comes back is an
:class:`AdminAccountView` like any other row — the account that now exists, with no echo of
what was sent to create it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field

from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.common import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS, ApiModel
from bayram.db.enums import AdminRole
from bayram.db.models.admin_user import AdminUserRow

__all__ = [
    "MIN_ADMIN_USERNAME_CHARS",
    "MAX_ADMIN_USERNAME_CHARS",
    "ADMIN_USERNAME_PATTERN",
    "AdminAccountView",
    "AdminCreateRequest",
    "AdminRosterResponse",
    "to_account_view",
    "to_roster",
]

#: Three characters, which is also what ``_SCOPE_PATTERN`` demands of a whole step-up scope.
#: A one- or two-character login is a typo far more often than it is a decision.
MIN_ADMIN_USERNAME_CHARS: Final[int] = 3
#: Half of ``admin_users.username``'s 64, and the shorter bound is deliberate: it keeps a
#: username inside ``audit._CREDENTIAL_SHAPES``' 40-character run test, which refuses any
#: ``[A-Za-z0-9_-]{40,}`` value at the audit boundary. A 44-character login would be a legal
#: account whose every audit row was rejected — a write nobody could hold anybody to.
MAX_ADMIN_USERNAME_CHARS: Final[int] = 32

#: Lowercase, digits, and the three separators — starting and ending on an alphanumeric.
#:
#: **The charset is the step-up scope's, not a style preference.** The account does not
#: exist when the operator re-authenticates, so the only identifier the step-up can be
#: scoped to is the username they typed, and it travels twice: into
#: ``admin_sessions.step_up_scope`` as ``admin.manage:<username>``
#: (``permissions._SCOPE_PATTERN``, ``[A-Za-z0-9._:-]``) and, on the refusal path, into
#: ``admin_audit_log.subject_id`` (``audit._SUBJECT_ID_PATTERN``, ``[A-Za-z0-9:._-]``). A
#: character outside both is a username that cannot be re-authenticated for. ``:`` is
#: excluded on top of that, because it is the scope separator: ``admin.manage:a:b`` parses
#: as two different subjects depending on who splits it.
#:
#: **So an email-shaped login cannot be created from the panel** — ``@`` is in neither
#: pattern. ``admin_users.username`` is 64 characters wide because the model anticipated
#: one, and the bootstrap CLI will still create it; what the panel cannot do is offer a
#: step-up for it. Handles here, addresses on the host.
#:
#: **Lowercase is required rather than casefolded.** ``normalize_username`` casefolds on the
#: way to the database, but a step-up scope is compared whole and byte-identical: an SPA that
#: re-authenticated for ``admin.manage:Dilnoza`` and then created ``dilnoza`` would earn a
#: scope mismatch nobody can debug from the 403. One spelling, refused at the edge.
ADMIN_USERNAME_PATTERN: Final[str] = r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$"


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


class AdminCreateRequest(ReasonedRequest):
    """``POST /api/admins`` — the body that adds an operator.

    Four fields and a reason. There is no ``isActive``, no ``mustChangePassword`` and no
    ``id``: a new account is active (an inactive one nobody can sign into is not a thing to
    create), it always holds a password somebody else chose, and its id is the database's.
    Accepting any of the three would be a second way to say something the server already
    knows the answer to.

    **``role`` accepts every member of the enum, including OWNER, and the handler refuses
    that one.** Narrowing the type here would make the refusal a 422 listing the legal
    members, which reads as "OWNER is misspelled" rather than as what it is —
    ``ix_admin_users_active_owner`` permits exactly one active OWNER, and moving it is
    ``bootstrap --reset-owner``'s job on the host. That sentence has to reach the operator,
    so the refusal belongs where a sentence can be written.
    """

    username: Annotated[
        str,
        Field(
            min_length=MIN_ADMIN_USERNAME_CHARS,
            max_length=MAX_ADMIN_USERNAME_CHARS,
            pattern=ADMIN_USERNAME_PATTERN,
        ),
    ]
    #: The password the new operator signs in with **once**: the account is written with
    #: ``must_change_password=True``, so the first thing they do with it is replace it. The
    #: floor is :data:`~bayram.admin.schemas.common.MIN_PASSWORD_CHARS`, the same one
    #: ``PasswordChangeRequest`` imposes on a rotation — unlike ``LoginRequest``, which has
    #: none, because an existing password predates any rule a schema could impose on it.
    password: str = Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS, repr=False)
    role: AdminRole


class AdminRosterResponse(ApiModel):
    """``GET /api/admins``. A bounded whole-table read, so there is no page meta.

    ``admin_users`` is capped by :data:`bayram.db.admin.accounts.MAX_ADMIN_ACCOUNTS`, and a
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
