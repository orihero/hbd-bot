"""The RBAC matrix as data, and the two guards that read it.

§12.2 of ADMIN_PANEL_PLAN is a table, so it is stored here as a table: one
:class:`Permission` per row, one :class:`Grant` per cell, and **no wildcard**. A wildcard
is how a permission added next quarter silently lands on a role nobody reviewed; an absent
cell is a denial, stated once. Because the matrix is data, the Slice 1c test can be
parameterised straight over it rather than restating it in assertions that drift.

The four roles come from ``hbd.db.enums.AdminRole``. The plan's draft called the third role
``OPERATOR``; the shipped enum calls it ``ADMIN`` and that is what this module speaks.
Ordering is documentation only — ``StrEnum`` compares as text, and nothing here derives a
permission from "greater than", because the first role that does not fit the ladder turns
every such check into a silent grant.

**Step-up is scoped to an action *and* a subject.** A session-wide "recently
re-authenticated" flag is the design this replaces: it lets a step-up collected to reveal
one order's note authorise blocking an unrelated user, which is precisely the confused
deputy the control exists to stop. So a grant is the exact string ``<action>:<subject-id>``
and it is compared whole. Single-use consumption is the session store's job, not this
module's.

**Freshness is enforced on top of that, and the window is not a constant here.** The
ordinary grace is ``AdminSettings.admin_step_up_grace_seconds``, threaded in by the caller
as ``grace_s``; there is deliberately no module-level default, because a default is what a
future caller silently inherits when an operator has lowered the setting. The two actions
§12.1 T2 marks "grace 0" — purge and config commit/rollback — take
:data:`STEP_UP_FRESH_MAX_AGE_S`, which is **zero**, and the choice is derived from the
matrix rather than restated, so raising the setting cannot loosen them and a future ``FRESH``
cell cannot quietly inherit the grace. Zero is a window rather than a wall: a grant carrying
the deciding request's own instant still passes, which is the shape those two actions must
take — re-authenticate and act under one ``now``, never across a round trip.

Nothing here raises for an authorisation failure: the guards return a
:class:`AccessDecision` and the HTTP layer maps it to the error envelope. A pure decision
is testable without a request, and it keeps the one place that decides "may they?" free of
any opinion about status codes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from hbd.db.enums import AdminRole
from hbd.logging import get_logger

__all__ = [
    "Permission",
    "StepUpAction",
    "StepUpRequirement",
    "Grant",
    "RBAC_MATRIX",
    "ROLE_PERMISSIONS",
    "STEP_UP_ACTIONS",
    "STEP_UP_FRESH_MAX_AGE_S",
    "MAX_STEP_UP_SCOPE_CHARS",
    "AccessDecision",
    "StepUpGrant",
    "PermissionGuard",
    "StepUpGuard",
    "build_step_up_scope",
    "grant_for",
    "is_permitted",
    "check_access",
    "check_role",
    "check_step_up",
    "max_age_for_action",
    "require",
    "require_step_up",
    "step_up_from_session",
]

_LOGGER: Final = get_logger(__name__)

#: The window for a "grace 0" action (§12.1 T2) — purge and config commit/rollback. Zero
#: seconds, not "a small number of seconds": only a grant carrying the deciding request's own
#: instant authorises one, so the action has to re-authenticate and act under a single
#: ``now`` rather than across a round trip. Anything larger is a grace, and the whole point
#: of these two cells is that they have none.
#:
#: There is no companion constant for the ordinary window. That one is
#: ``AdminSettings.admin_step_up_grace_seconds`` and it arrives as ``grace_s``.
STEP_UP_FRESH_MAX_AGE_S: Final[int] = 0
#: ``admin_sessions.step_up_scope`` is ``String(128)``.
MAX_STEP_UP_SCOPE_CHARS: Final[int] = 128

_SCOPE_SEPARATOR: Final[str] = ":"
#: Scopes are built from closed vocabularies and identifiers, never from free text, so the
#: shape is asserted before the value reaches the database or a log line.
_SCOPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]{3,128}$")


class Permission(StrEnum):
    """One row of §12.2. The value is what a route declares and an audit row records."""

    SESSION_SELF = "session.self"
    DASHBOARD_READ = "dashboard.read"
    RECORDS_READ = "records.read"
    CHAT_INDEX_READ = "chat.index.read"
    WIZARD_STATE_READ = "wizard_state.read"
    MODERATION_QUEUE_READ = "moderation.queue.read"
    CONFIG_READ = "config.read"
    RETENTION_READ = "retention.read"
    REVEAL_PERSONAL_DATA_READ = "reveal.personal_data.read"
    REVEAL_PERSONAL_DATA = "reveal.personal_data"
    REVEAL_MEDIA_READ = "reveal.media.read"
    REVEAL_MEDIA = "reveal.media"
    ORDER_RETRY = "order.retry"
    ORDER_FORCE_DELIVER = "order.force_deliver"
    USER_BLOCK = "user.block"
    MODERATION_REVEAL = "moderation.reveal"
    MODERATION_DECIDE = "moderation.decide"
    RETENTION_SWEEP = "retention.sweep"
    AUDIT_READ = "audit.read"
    REVEAL_VOLUME_READ = "reveal.volume.read"
    EXPORT_AGGREGATE = "export.aggregate"
    USER_PURGE = "user.purge"
    CONFIG_WRITE = "config.write"
    ORDER_EVIDENCE_EXPORT = "order.evidence_export"
    AUDIT_EXPORT = "audit.export"
    ADMIN_READ = "admin.read"
    ADMIN_MANAGE = "admin.manage"


class StepUpAction(StrEnum):
    """The left half of a step-up scope.

    Coarser than :class:`Permission` in exactly one place: every reveal — a name, a note, a
    chat body, a moderation detail, an audio stream — is the single ``reveal`` action, so
    the one audited reveal path in §12.3 has one scope shape. Everything else maps 1:1,
    because a step-up for "block this user" must not authorise "purge this user".
    """

    REVEAL = "reveal"
    ORDER_FORCE_DELIVER = "order.force_deliver"
    USER_BLOCK = "user.block"
    MODERATION_DECIDE = "moderation.decide"
    USER_PURGE = "user.purge"
    CONFIG_WRITE = "config.write"
    ORDER_EVIDENCE_EXPORT = "order.evidence_export"
    AUDIT_EXPORT = "audit.export"
    ADMIN_MANAGE = "admin.manage"


class StepUpRequirement(StrEnum):
    """How recently the operator must have re-authenticated for this cell."""

    NONE = "none"
    REQUIRED = "required"
    FRESH = "fresh"


class AccessDecision(StrEnum):
    """The guards' answer. Anything but ``ALLOWED`` is a refusal with a distinct reason.

    The reasons are distinct because the panel reacts differently to each: a missing
    step-up opens the re-authentication prompt, a scope mismatch means the operator
    switched subjects mid-flow, and a role failure must not offer a prompt at all.
    """

    ALLOWED = "allowed"
    FORBIDDEN_ROLE = "forbidden_role"
    STEP_UP_REQUIRED = "step_up_required"
    STEP_UP_SCOPE_MISMATCH = "step_up_scope_mismatch"
    STEP_UP_EXPIRED = "step_up_expired"


@dataclass(frozen=True, slots=True)
class Grant:
    """One cell of the matrix. Absence of a cell is denial; this is never "empty".

    ``is_unmasked`` is what the serializer reads: **M** and **R** are both reads, and the
    difference between them is whether personal data comes back in the clear, which is a
    response-boundary decision rather than a routing one (§12.3).
    """

    is_readable: bool = False
    is_unmasked: bool = False
    is_writable: bool = False
    is_reveal: bool = False
    step_up: StepUpRequirement = StepUpRequirement.NONE


#: The cell vocabulary of §12.2, named as the table names them.
_M: Final[Grant] = Grant(is_readable=True)
_R: Final[Grant] = Grant(is_readable=True, is_unmasked=True)
_W: Final[Grant] = Grant(is_writable=True)
_WS: Final[Grant] = Grant(is_writable=True, step_up=StepUpRequirement.REQUIRED)
_WSF: Final[Grant] = Grant(is_writable=True, step_up=StepUpRequirement.FRESH)
_AS: Final[Grant] = Grant(
    is_readable=True,
    is_unmasked=True,
    is_reveal=True,
    step_up=StepUpRequirement.REQUIRED,
)


def _row(
    *,
    viewer: Grant | None = None,
    support: Grant | None = None,
    admin: Grant | None = None,
    owner: Grant | None = None,
) -> Mapping[AdminRole, Grant]:
    """One matrix row. A role left ``None`` has no cell, which is a denial."""
    cells = {
        AdminRole.VIEWER: viewer,
        AdminRole.SUPPORT: support,
        AdminRole.ADMIN: admin,
        AdminRole.OWNER: owner,
    }
    return MappingProxyType({role: cell for role, cell in cells.items() if cell is not None})


#: §12.2, verbatim but for one ruled-on split. VIEWER · SUPPORT · ADMIN (the plan's
#: OPERATOR) · OWNER. The exception is the pair of ``ADMIN_*`` rows at the bottom, which
#: follow §6.8 line 949 rather than §12.2's collapsed row; the reason is written out there.
RBAC_MATRIX: Final[Mapping[Permission, Mapping[AdminRole, Grant]]] = MappingProxyType(
    {
        Permission.SESSION_SELF: _row(viewer=_W, support=_W, admin=_W, owner=_W),
        Permission.DASHBOARD_READ: _row(viewer=_M, support=_M, admin=_M, owner=_R),
        Permission.RECORDS_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.CHAT_INDEX_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.WIZARD_STATE_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.MODERATION_QUEUE_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.CONFIG_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        Permission.RETENTION_READ: _row(viewer=_M, support=_M, admin=_M, owner=_M),
        # ── The THIRD place this table splits a §12.2 row, for the same reason as the two ──
        # ── below it. Read the ADMIN_READ / ADMIN_MANAGE note at the bottom first. ────────
        #
        # §12.2 rows 4, 6, 7 and 9 all reduce to one endpoint — "Every ``A`` cell routes
        # through the same ``POST /reveal`` endpoint" (§12.2 line 1886) — and §6.8 line 928
        # gives that endpoint as ``S +S, audited, budgeted``. One ``A+S`` cell on the router
        # makes it unreachable by everybody, for :func:`check_role`'s reason: the router
        # guard holds no subject and therefore no grant, so it answers STEP_UP_REQUIRED to a
        # SUPPORT operator holding a live, correctly-scoped ``reveal:<order>`` grant, for
        # ever. And unlike the roster there is no §6.8 sibling row to fall back on, because
        # /reveal has exactly one.
        #
        # Guarding the router with RECORDS_READ instead — the shape ``test_budget.py``'s
        # probe route uses — is not available either: RECORDS_READ is ``M`` for all four
        # roles, and §12.2 gives VIEWER no reveal cell at all.
        #
        # So the row is split: REVEAL_PERSONAL_DATA_READ is the ROLE half — who may reach
        # ``POST /reveal`` at all, SUPPORT and above and pointedly not VIEWER — carrying no
        # step-up, so the router guard decides it and lets the request through.
        # REVEAL_PERSONAL_DATA keeps the ``A+S`` cell and is what the HANDLER enforces on
        # the subject in the body, through
        # ``deps.enforce_step_up(StepUpAction.REVEAL, subject_id=…)``. Both halves run on
        # every request; neither is decorative and neither is sufficient alone.
        #
        # ``_M`` and not ``_R``: passing this guard unmasks nothing by itself. The plaintext
        # only crosses after the step-up, the budget charge and the audit row, and that is
        # the ``_AS`` cell on the next line.
        Permission.REVEAL_PERSONAL_DATA_READ: _row(support=_M, admin=_M, owner=_M),
        Permission.REVEAL_PERSONAL_DATA: _row(support=_AS, admin=_AS, owner=_AS),
        # ── The second place this table splits a §12.2 row, for the SAME reason as the ──
        # ── ADMIN_READ / ADMIN_MANAGE pair below. See the long note there first. ────────
        #
        # §12.2 row 10 is ``Stream audio or read lyric text | — | A+S | A+S | A+S``, and
        # §6.8 lines 924-925 give both endpoints as ``S +S, audited``. Read literally as one
        # cell it makes GET /api/assets/{id}/stream unreachable by everybody: the router
        # guard is :func:`check_role`, which holds no subject and therefore no grant, so it
        # answers STEP_UP_REQUIRED to an ``A+S`` cell for ever — an operator who has just
        # completed a correctly-scoped ``reveal:<asset>`` step-up still gets 403, and it
        # looks right, because STEP_UP_REQUIRED is exactly what the matrix predicts.
        #
        # So the row is split the way §12.2 itself split the roster: REVEAL_MEDIA_READ is
        # the ROLE half — who may reach the media routes at all, which is SUPPORT and above
        # and pointedly not VIEWER — and it carries no step-up, so the router guard decides
        # it and lets the request through. REVEAL_MEDIA keeps the ``A+S`` cell and is what
        # the HANDLER enforces on the subject it has read, through
        # ``deps.enforce_step_up(StepUpAction.REVEAL, subject_id=str(asset_id))``. Both
        # halves therefore run on every request: neither is decorative and neither is
        # sufficient alone.
        #
        # ``_M`` and not ``_R``: passing this guard unmasks nothing by itself. The bytes
        # only move after the step-up, and that is the ``_AS`` cell below.
        Permission.REVEAL_MEDIA_READ: _row(support=_M, admin=_M, owner=_M),
        Permission.REVEAL_MEDIA: _row(support=_AS, admin=_AS, owner=_AS),
        Permission.ORDER_RETRY: _row(admin=_W, owner=_W),
        Permission.ORDER_FORCE_DELIVER: _row(admin=_WS, owner=_WS),
        Permission.USER_BLOCK: _row(admin=_WS, owner=_WS),
        Permission.MODERATION_REVEAL: _row(admin=_AS, owner=_AS),
        Permission.MODERATION_DECIDE: _row(admin=_WS, owner=_WS),
        Permission.RETENTION_SWEEP: _row(admin=_W, owner=_W),
        Permission.AUDIT_READ: _row(admin=_M, owner=_R),
        Permission.REVEAL_VOLUME_READ: _row(admin=_R, owner=_R),
        Permission.EXPORT_AGGREGATE: _row(admin=_W, owner=_W),
        Permission.USER_PURGE: _row(owner=_WSF),
        Permission.CONFIG_WRITE: _row(owner=_WSF),
        Permission.ORDER_EVIDENCE_EXPORT: _row(owner=_WS),
        Permission.AUDIT_EXPORT: _row(owner=_WS),
        # ── The one place this table deliberately does NOT follow §12.2. ──────────────
        # §6.8 line 949 is the endpoint-level table and it is the authority here:
        #     | GET | /admins | List | W |
        # — owner, write-class, and pointedly with NO ``+S``, while the four writes beneath
        # it (POST /admins, PATCH /admins/{id}, POST /admins/{id}/reset-password,
        # DELETE /admins/{id}/sessions) each carry ``W +S`` explicitly. §12.2 collapsed all
        # five into one row — ``| Admin account CRUD, revoke others' sessions | — | — | — |
        # W+S |`` — and that collapsed row was NOT followed, by a ruling on the
        # contradiction, because the endpoint table is the more specific statement. §12.2 now
        # carries the same split (lines 1883-1884), so the two sections agree again.
        #
        # The split is not cosmetic. :func:`check_role` is the router-level guard and it
        # takes only (permission, role): it holds no grant and reads no session, so a single
        # ``_WS`` cell answers ``STEP_UP_REQUIRED`` to an OWNER unconditionally and forever —
        # a granted, unexpired, correctly-scoped ``admin.manage`` step-up still yields 403.
        # Reading §12.2's collapsed row literally therefore made the roster unreachable by
        # every role, which is not what either section asks for.
        #
        # So: ADMIN_READ is the roster read (owner, ``W``, no step-up) and ADMIN_MANAGE stays
        # the ``W+S`` cell guarding the four account writes when they arrive in Phase 2.
        # Do not merge them back.
        Permission.ADMIN_READ: _row(owner=_W),
        Permission.ADMIN_MANAGE: _row(owner=_WS),
    }
)

#: The §12.1 T9 shape, DERIVED from the matrix rather than restated beside it — two hand-
#: maintained copies of an authorisation table disagree eventually, and the disagreement is
#: always a grant.
ROLE_PERMISSIONS: Final[Mapping[AdminRole, frozenset[Permission]]] = MappingProxyType(
    {
        role: frozenset(permission for permission, row in RBAC_MATRIX.items() if role in row)
        for role in AdminRole
    }
)

#: Which step-up action guards which permission. Every permission whose grant carries a
#: step-up requirement appears here, asserted by test — a missing entry would be a route
#: that asks for a step-up nobody can grant.
STEP_UP_ACTIONS: Final[Mapping[Permission, StepUpAction]] = MappingProxyType(
    {
        Permission.REVEAL_PERSONAL_DATA: StepUpAction.REVEAL,
        Permission.REVEAL_MEDIA: StepUpAction.REVEAL,
        Permission.MODERATION_REVEAL: StepUpAction.REVEAL,
        Permission.ORDER_FORCE_DELIVER: StepUpAction.ORDER_FORCE_DELIVER,
        Permission.USER_BLOCK: StepUpAction.USER_BLOCK,
        Permission.MODERATION_DECIDE: StepUpAction.MODERATION_DECIDE,
        Permission.USER_PURGE: StepUpAction.USER_PURGE,
        Permission.CONFIG_WRITE: StepUpAction.CONFIG_WRITE,
        Permission.ORDER_EVIDENCE_EXPORT: StepUpAction.ORDER_EVIDENCE_EXPORT,
        Permission.AUDIT_EXPORT: StepUpAction.AUDIT_EXPORT,
        Permission.ADMIN_MANAGE: StepUpAction.ADMIN_MANAGE,
    }
)

#: Action → how fresh a grant for it must be, DERIVED from the matrix. An action is
#: ``FRESH`` when any permission it guards is, so the strictest cell wins and a second
#: hand-maintained list of "the grace-0 actions" — which would eventually disagree with
#: §12.2, and always in the loosening direction — does not exist.
_ACTION_STEP_UP: Final[Mapping[StepUpAction, StepUpRequirement]] = MappingProxyType(
    {
        action: (
            StepUpRequirement.FRESH
            if any(
                grant.step_up is StepUpRequirement.FRESH
                for permission, guarding in STEP_UP_ACTIONS.items()
                if guarding is action
                for grant in RBAC_MATRIX[permission].values()
            )
            else StepUpRequirement.REQUIRED
        )
        for action in STEP_UP_ACTIONS.values()
    }
)


@dataclass(frozen=True, slots=True)
class StepUpGrant:
    """A step-up as it is stored: the exact scope it was granted for, and when."""

    scope: str
    granted_at: datetime


def step_up_from_session(scope: str | None, granted_at: datetime | None) -> StepUpGrant | None:
    """Lift ``admin_sessions.step_up_scope`` / ``step_up_at`` into a grant, or ``None``.

    Both columns are nullable and are only meaningful together: half a grant is no grant.
    """
    if scope is None or granted_at is None:
        return None
    return StepUpGrant(scope=scope, granted_at=granted_at)


def build_step_up_scope(action: str, subject_id: str) -> str:
    """``"<action>:<subject-id>"``. Raises ``ValueError`` on a shape that cannot be stored.

    Validated rather than trusted because the result is written to a ``String(128)`` column
    and read back into an authorisation comparison: a scope carrying a newline, a space or
    2 KiB of anything is a bug upstream, and silently truncating it would widen a grant.
    """
    if not action or not subject_id:
        raise ValueError("a step-up scope needs both an action and a subject to be storable")
    scope = f"{action}{_SCOPE_SEPARATOR}{subject_id}"
    if len(scope) > MAX_STEP_UP_SCOPE_CHARS or _SCOPE_PATTERN.fullmatch(scope) is None:
        raise ValueError(f"step-up scope is not a storable identifier: {scope!r}")
    return scope


def grant_for(permission: Permission, role: AdminRole) -> Grant | None:
    """The cell for this role, or ``None`` when the matrix has none — which is a denial."""
    return RBAC_MATRIX[permission].get(role)


def is_permitted(permission: Permission, role: AdminRole) -> bool:
    """Role check only. Says nothing about masking or step-up; see :func:`check_access`."""
    return grant_for(permission, role) is not None


def _max_age_s(requirement: StepUpRequirement, grace_s: int) -> int:
    return STEP_UP_FRESH_MAX_AGE_S if requirement is StepUpRequirement.FRESH else grace_s


def max_age_for_action(action: StepUpAction, *, grace_s: int) -> int:
    """How many seconds a grant for ``action`` stays valid, given the configured grace.

    The one place outside :func:`check_access` that needs the answer is the step-up route,
    which reports an ``expiresAt`` to the SPA. It asks here rather than doing the arithmetic
    itself, because an ``expiresAt`` computed from the grace for an action the guard will
    only honour for zero seconds is a promise the next request breaks.
    """
    return _max_age_s(_ACTION_STEP_UP[action], grace_s)


def check_step_up(
    step_up: StepUpGrant | None,
    *,
    required_scope: str,
    now: datetime,
    max_age_s: int,
) -> AccessDecision:
    """Is ``step_up`` a live grant for exactly ``required_scope``?

    Scope equality is exact and whole-string: a grant for ``reveal:<order>`` is not a grant
    for ``user.block:<order>``, for ``reveal:<other-order>``, or for a prefix of either.
    """
    if step_up is None:
        return AccessDecision.STEP_UP_REQUIRED
    if step_up.scope != required_scope:
        return AccessDecision.STEP_UP_SCOPE_MISMATCH
    age_s = (now - step_up.granted_at).total_seconds()
    if age_s < 0 or age_s > max_age_s:
        # A grant timestamped in the future is a clock problem or a forged row; neither is
        # a reason to authorise a purge.
        return AccessDecision.STEP_UP_EXPIRED
    return AccessDecision.ALLOWED


def check_role(permission: Permission, role: AdminRole) -> AccessDecision:
    """As much as can be decided without a subject: the cell, and whether it wants a step-up.

    This is the router-level question. A router guard holds no subject — the subject is a
    path parameter only the handler has read — and therefore no grant either, so a window
    would be inert there. Rather than hand one over to be ignored, the router asks the
    narrower question and gets ``STEP_UP_REQUIRED`` for a cell whose step-up the request has
    not presented, which is the honest answer and the one the SPA turns into a prompt.
    """
    grant = grant_for(permission, role)
    if grant is None:
        return AccessDecision.FORBIDDEN_ROLE
    if grant.step_up is StepUpRequirement.NONE:
        return AccessDecision.ALLOWED
    return AccessDecision.STEP_UP_REQUIRED


def check_access(
    permission: Permission,
    *,
    role: AdminRole,
    now: datetime,
    grace_s: int,
    subject_id: str | None = None,
    step_up: StepUpGrant | None = None,
) -> AccessDecision:
    """The whole check: role first, then step-up when the cell demands one.

    ``subject_id`` identifies what the action is being taken against — an order id, a
    Telegram user id, a config version. It is required exactly when the cell requires a
    step-up, because the scope cannot be built without it.

    ``grace_s`` is ``AdminSettings.admin_step_up_grace_seconds``. It has no default on
    purpose: a caller that forgets it is a compile-time error rather than a route quietly
    honouring fifteen minutes after an operator configured one. It is ignored for the
    ``FRESH`` cells, so raising it cannot loosen a purge or a config commit.
    """
    grant = grant_for(permission, role)
    if grant is None:
        return AccessDecision.FORBIDDEN_ROLE
    if grant.step_up is StepUpRequirement.NONE:
        return AccessDecision.ALLOWED
    action = STEP_UP_ACTIONS[permission]
    if subject_id is None:
        _LOGGER.error(
            "step-up permission checked without a subject id; denying",
            extra={"event": "admin.rbac.missing_subject", "permission": str(permission)},
        )
        return AccessDecision.STEP_UP_REQUIRED
    return check_step_up(
        step_up,
        required_scope=build_step_up_scope(action, subject_id),
        now=now,
        max_age_s=_max_age_s(grant.step_up, grace_s),
    )


@dataclass(frozen=True, slots=True)
class PermissionGuard:
    """What :func:`require` returns: a callable that decides, and names its permission.

    The ``permission`` attribute is not decoration — the Slice 1c route-enumeration test
    reads it off each route's dependencies to assert that every route carries exactly one.
    """

    permission: Permission

    def __call__(
        self,
        *,
        role: AdminRole,
        now: datetime,
        grace_s: int,
        subject_id: str | None = None,
        step_up: StepUpGrant | None = None,
    ) -> AccessDecision:
        return check_access(
            self.permission,
            role=role,
            now=now,
            grace_s=grace_s,
            subject_id=subject_id,
            step_up=step_up,
        )


@dataclass(frozen=True, slots=True)
class StepUpGuard:
    """What :func:`require_step_up` returns: one action bound to one subject."""

    action: str
    subject_id: str

    @property
    def scope(self) -> str:
        return build_step_up_scope(self.action, self.subject_id)

    def __call__(
        self,
        step_up: StepUpGrant | None,
        *,
        now: datetime,
        max_age_s: int,
    ) -> AccessDecision:
        """``max_age_s`` has no default: see :func:`max_age_for_action` for where it comes
        from. A guard for a grace-0 action handed the ordinary grace would honour it, so the
        window is never guessed here."""
        return check_step_up(step_up, required_scope=self.scope, now=now, max_age_s=max_age_s)


def require(permission: Permission) -> PermissionGuard:
    """Declare the permission a router needs. Applied at router level, never per handler."""
    return PermissionGuard(permission=permission)


def require_step_up(action: str, subject_id: str) -> StepUpGuard:
    """Demand a step-up for this action **on this subject**.

    Both halves are load-bearing. ``require_step_up("user.block", user_id)`` rejects a grant
    obtained for ``reveal:<order-id>``, and it also rejects one obtained for
    ``user.block:<a-different-user>``.
    """
    # Built eagerly so an unstorable scope fails where the route is declared, not on the
    # first request that reaches it.
    build_step_up_scope(action, subject_id)
    return StepUpGuard(action=action, subject_id=subject_id)
