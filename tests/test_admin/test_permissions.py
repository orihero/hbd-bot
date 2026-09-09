"""§12.2 restated once, as data, and then checked against the module's own table.

Two halves, and both are needed:

* :data:`_PLAN_MATRIX` is the plan's table typed out cell by cell, in the plan's own
  notation. Comparing it to :data:`RBAC_MATRIX` is how an accidental grant — a copy-paste
  that hands SUPPORT a write, a new permission quietly added to OWNER's row and everyone
  else's — is caught by a diff instead of by an incident. Its one departure from §12.2 is
  the ``ADMIN_READ`` / ``ADMIN_MANAGE`` pair, transcribed from §6.8 line 949 by a ruling on
  the two sections' contradiction; the row carries the reasoning.
* everything below that is parameterised **over the module's matrix**, so a permission
  added next quarter is automatically subject to the same rules about step-up scoping
  without anyone remembering to extend a test.

The step-up tests are the reason this file exists. A session-wide "recently
re-authenticated" flag would pass a naive version of every one of them; what separates the
two designs is that a grant obtained for ``reveal:<order-id>`` must be refused for
``user.block:<user-id>``, and that is asserted across every pair of actions rather than for
one illustrative case.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from hbd.admin.security.permissions import (
    MAX_STEP_UP_SCOPE_CHARS,
    RBAC_MATRIX,
    ROLE_PERMISSIONS,
    STEP_UP_ACTIONS,
    STEP_UP_FRESH_MAX_AGE_S,
    AccessDecision,
    Grant,
    Permission,
    StepUpAction,
    StepUpGrant,
    StepUpRequirement,
    build_step_up_scope,
    check_access,
    check_step_up,
    grant_for,
    is_permitted,
    require,
    require_step_up,
    step_up_from_session,
)
from hbd.db.enums import AdminRole

_NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
#: The window now arrives from ``AdminSettings.admin_step_up_grace_seconds``; these
#: tests pass it explicitly, because the guards no longer carry a default to inherit.
_GRACE_S: Final[int] = 300
_ORDER_ID: Final[str] = "3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3"
_USER_ID: Final[str] = "770000123"

#: §12.2's own notation. ``None`` is the table's em dash: no cell, therefore denied.
_M: Final[str] = "M"
_R: Final[str] = "R"
_W: Final[str] = "W"
_WS: Final[str] = "W+S"
_WSF: Final[str] = "W+S(fresh)"
_AS: Final[str] = "A+S"

#: The plan's table, in plan order: VIEWER · SUPPORT · ADMIN (the plan's OPERATOR) · OWNER.
_PLAN_MATRIX: Final[Mapping[Permission, tuple[str | None, str | None, str | None, str | None]]] = {
    Permission.SESSION_SELF: (_W, _W, _W, _W),
    Permission.DASHBOARD_READ: (_M, _M, _M, _R),
    Permission.RECORDS_READ: (_M, _M, _M, _M),
    Permission.CHAT_INDEX_READ: (_M, _M, _M, _M),
    Permission.WIZARD_STATE_READ: (_M, _M, _M, _M),
    Permission.MODERATION_QUEUE_READ: (_M, _M, _M, _M),
    Permission.CONFIG_READ: (_M, _M, _M, _M),
    Permission.RETENTION_READ: (_M, _M, _M, _M),
    # The same split, one row earlier, and for a sharper reason than the media pair below:
    # §12.2 line 1886 collapses every ``A`` cell onto ONE endpoint (``POST /reveal``), and
    # §6.8 line 928 gives that endpoint a single ``S +S`` row — so unlike the roster there is
    # no second endpoint-table line to fall back on. REVEAL_PERSONAL_DATA_READ is the role
    # half the router declares (``M``: passing it unmasks nothing by itself, since the
    # plaintext crosses only after the step-up, the budget charge and the audit row), and
    # REVEAL_PERSONAL_DATA keeps §12.2's ``A+S``, enforced by the handler on the subject in
    # the body. RECORDS_READ was not available for the role half: it is ``M`` for all four
    # roles, and §12.2 gives VIEWER no reveal cell at all.
    Permission.REVEAL_PERSONAL_DATA_READ: (None, _M, _M, _M),
    Permission.REVEAL_PERSONAL_DATA: (None, _AS, _AS, _AS),
    # NOT transcribed from §12.2 as it stands, and the deviation is the same one the
    # ADMIN_READ / ADMIN_MANAGE pair below records. §12.2 row 10 —
    # ``Stream audio or read lyric text | — | A+S | A+S | A+S`` — read literally as one cell
    # makes both endpoints unreachable by every role: the router guard is ``check_role``,
    # which holds no subject and so no grant, and answers STEP_UP_REQUIRED to an ``A+S`` cell
    # unconditionally. So the row is split. REVEAL_MEDIA_READ is the role half the router
    # declares (``M``: passing it unmasks nothing by itself), and REVEAL_MEDIA keeps §12.2's
    # ``A+S``, enforced by the handler on the subject it has read.
    Permission.REVEAL_MEDIA_READ: (None, _M, _M, _M),
    Permission.REVEAL_MEDIA: (None, _AS, _AS, _AS),
    Permission.ORDER_RETRY: (None, None, _W, _W),
    Permission.ORDER_FORCE_DELIVER: (None, None, _WS, _WS),
    Permission.USER_BLOCK: (None, None, _WS, _WS),
    # The role half of the row above, transcribed by the same ruling that split the two
    # reveal rows: a ``W+S`` cell decided by ``check_role`` is a permanent 403 for every
    # role, because a router guard holds no subject and therefore no grant to weigh. So
    # ``POST /users/{id}/block`` and ``/unblock`` declare this cell — USER_BLOCK's own two
    # roles with the ``+S`` removed — and their handlers enforce USER_BLOCK on the Telegram
    # id they have read. §12.2 has one row; the code has two, and neither is reachable
    # without the other.
    Permission.USER_BLOCK_WRITE: (None, None, _W, _W),
    # NOT in §12.2 at all. ``AuditAction.CREDIT_GRANT`` shipped with the entitlement ledger
    # and §12.2 predates ``credit_accounts``, so the cell is a ruling rather than a
    # transcription; ``permissions.py`` carries the argument for ADMIN+OWNER, for ``+S`` and
    # for it not being ``fresh``. The pair is split for the reason the pair above is.
    Permission.CREDIT_GRANT: (None, None, _WS, _WS),
    Permission.CREDIT_GRANT_WRITE: (None, None, _W, _W),
    # Also NOT in §12.2 — a ruling in the shape of the pair above, transcribed from
    # BROADCAST_SPEC §3.1. The read is ``M`` at every role because a campaign record holds
    # no customer data (a title, a segment, counters) and a VIEWER who cannot see what went
    # out cannot review it; the recipient list is masked at the response boundary for
    # everyone, so there is nothing here for an ``R`` cell to unmask. The write pair is split
    # for the reason the two above are, and ``permissions.py`` argues the ``+S`` on the send:
    # it is the one action that reaches every customer at once and the one nothing can undo.
    Permission.BROADCAST_READ: (_M, _M, _M, _M),
    Permission.BROADCAST_WRITE: (None, None, _W, _W),
    Permission.BROADCAST_SEND: (None, None, _WS, _WS),
    Permission.MODERATION_REVEAL: (None, None, _AS, _AS),
    Permission.MODERATION_DECIDE: (None, None, _WS, _WS),
    Permission.RETENTION_SWEEP: (None, None, _W, _W),
    Permission.AUDIT_READ: (None, None, _M, _R),
    Permission.REVEAL_VOLUME_READ: (None, None, _R, _R),
    Permission.EXPORT_AGGREGATE: (None, None, _W, _W),
    Permission.USER_PURGE: (None, None, None, _WSF),
    Permission.CONFIG_WRITE: (None, None, None, _WSF),
    Permission.ORDER_EVIDENCE_EXPORT: (None, None, None, _WS),
    Permission.AUDIT_EXPORT: (None, None, None, _WS),
    # The one pair of rows NOT transcribed from §12.2 as it stood. It read
    # ``| Admin account CRUD, revoke others' sessions | — | — | — | W+S |`` — one row for
    # five endpoints. §6.8 line 949 splits them: ``| GET | /admins | List | W |`` for the
    # roster read, and an explicit ``W +S`` on each of POST /admins, PATCH /admins/{id},
    # POST /admins/{id}/reset-password and DELETE /admins/{id}/sessions. The endpoint table
    # is the more specific statement and it was ruled the authority, so the read is
    # transcribed from §6.8 as a bare owner ``W`` and the writes keep §12.2's ``W+S``.
    Permission.ADMIN_READ: (None, None, None, _W),
    Permission.ADMIN_MANAGE: (None, None, None, _WS),
}

_ROLES_IN_PLAN_ORDER: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

_CELLS: Final[Mapping[str, Grant]] = {
    _M: Grant(is_readable=True),
    _R: Grant(is_readable=True, is_unmasked=True),
    _W: Grant(is_writable=True),
    _WS: Grant(is_writable=True, step_up=StepUpRequirement.REQUIRED),
    _WSF: Grant(is_writable=True, step_up=StepUpRequirement.FRESH),
    _AS: Grant(
        is_readable=True,
        is_unmasked=True,
        is_reveal=True,
        step_up=StepUpRequirement.REQUIRED,
    ),
}

_STEP_UP_PERMISSIONS: Final[tuple[Permission, ...]] = tuple(
    permission
    for permission, row in RBAC_MATRIX.items()
    for grant in row.values()
    if grant.step_up is not StepUpRequirement.NONE
)


#: Every (permission, role) the matrix has no cell for — the denials, enumerated rather
#: than skipped, so the count in the test report is the number of denials actually checked.
_DENIED_PAIRS: Final[tuple[tuple[Permission, AdminRole], ...]] = tuple(
    (permission, role)
    for permission in RBAC_MATRIX
    for role in AdminRole
    if not is_permitted(permission, role)
)


def _any_grant(permission: Permission) -> Grant:
    return next(iter(RBAC_MATRIX[permission].values()))


def _a_role_with(permission: Permission) -> AdminRole:
    return next(iter(RBAC_MATRIX[permission]))


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------
def test_the_encoded_matrix_is_the_plan_s_matrix() -> None:
    assert set(RBAC_MATRIX) == set(_PLAN_MATRIX)


@pytest.mark.parametrize("permission", list(_PLAN_MATRIX))
def test_every_cell_matches_the_plan(permission: Permission) -> None:
    expected = {
        role: _CELLS[code]
        for role, code in zip(_ROLES_IN_PLAN_ORDER, _PLAN_MATRIX[permission], strict=True)
        if code is not None
    }

    assert dict(RBAC_MATRIX[permission]) == expected


def test_the_matrix_has_no_wildcard_row() -> None:
    """A row every role can reach is fine; a row nobody reviewed reaching every role is not."""
    write_everywhere = [
        permission
        for permission, row in RBAC_MATRIX.items()
        if permission is not Permission.SESSION_SELF
        and all(grant.is_writable for grant in row.values())
        and len(row) == len(AdminRole)
    ]

    assert write_everywhere == []


def test_a_viewer_can_write_nothing_and_unmask_nothing() -> None:
    for permission in ROLE_PERMISSIONS[AdminRole.VIEWER]:
        grant = grant_for(permission, AdminRole.VIEWER)
        assert grant is not None
        assert grant.is_writable is (permission is Permission.SESSION_SELF)
        assert grant.is_unmasked is False
        assert grant.is_reveal is False


def test_role_permissions_is_derived_from_the_matrix_and_agrees_with_it() -> None:
    for role in AdminRole:
        derived = ROLE_PERMISSIONS[role]
        assert derived == frozenset(
            permission for permission in RBAC_MATRIX if is_permitted(permission, role)
        )
    assert ROLE_PERMISSIONS[AdminRole.VIEWER] < ROLE_PERMISSIONS[AdminRole.OWNER]


def test_the_matrix_speaks_the_shipped_role_names_not_the_draft_s() -> None:
    """The plan said OPERATOR; ``AdminRole`` says ADMIN, and the contract wins."""
    assert Permission.ORDER_RETRY in ROLE_PERMISSIONS[AdminRole.ADMIN]
    assert {role.value for role in AdminRole} == {"owner", "admin", "support", "viewer"}


# ---------------------------------------------------------------------------
# Role checks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("permission", "role"), _DENIED_PAIRS)
def test_a_role_without_a_cell_is_refused(permission: Permission, role: AdminRole) -> None:
    decision = check_access(permission, role=role, now=_NOW, subject_id=_ORDER_ID, grace_s=_GRACE_S)

    assert decision is AccessDecision.FORBIDDEN_ROLE


@pytest.mark.parametrize("permission", list(RBAC_MATRIX))
def test_a_cell_without_a_step_up_requirement_allows_immediately(
    permission: Permission,
) -> None:
    for role, grant in RBAC_MATRIX[permission].items():
        if grant.step_up is not StepUpRequirement.NONE:
            continue
        assert (
            check_access(permission, role=role, now=_NOW, grace_s=_GRACE_S)
            is AccessDecision.ALLOWED
        )


# ---------------------------------------------------------------------------
# Step-up: scoped to an action AND a subject
# ---------------------------------------------------------------------------
def test_every_step_up_permission_has_an_action_and_nothing_else_does() -> None:
    assert set(STEP_UP_ACTIONS) == set(_STEP_UP_PERMISSIONS)


@pytest.mark.parametrize("permission", sorted(set(_STEP_UP_PERMISSIONS)))
def test_a_step_up_permission_without_a_grant_asks_for_one(permission: Permission) -> None:
    role = _a_role_with(permission)

    decision = check_access(permission, role=role, now=_NOW, subject_id=_ORDER_ID, grace_s=_GRACE_S)

    assert decision is AccessDecision.STEP_UP_REQUIRED


@pytest.mark.parametrize("permission", sorted(set(_STEP_UP_PERMISSIONS)))
def test_a_correctly_scoped_fresh_grant_is_accepted(permission: Permission) -> None:
    role = _a_role_with(permission)
    scope = build_step_up_scope(STEP_UP_ACTIONS[permission], _ORDER_ID)

    decision = check_access(
        permission,
        role=role,
        now=_NOW,
        subject_id=_ORDER_ID,
        step_up=StepUpGrant(scope=scope, granted_at=_NOW),
        grace_s=_GRACE_S,
    )

    assert decision is AccessDecision.ALLOWED


@pytest.mark.parametrize("granted_action", list(StepUpAction))
@pytest.mark.parametrize("requested_action", list(StepUpAction))
def test_a_grant_for_one_action_never_authorises_another(
    granted_action: StepUpAction, requested_action: StepUpAction
) -> None:
    """The correction the review forced: a step-up is not a session-wide flag."""
    granted = StepUpGrant(scope=build_step_up_scope(granted_action, _ORDER_ID), granted_at=_NOW)
    guard = require_step_up(requested_action, _ORDER_ID)

    decision = guard(granted, now=_NOW, max_age_s=_GRACE_S)

    expected = (
        AccessDecision.ALLOWED
        if granted_action is requested_action
        else AccessDecision.STEP_UP_SCOPE_MISMATCH
    )
    assert decision is expected


def test_a_reveal_grant_is_refused_by_a_user_block_guard() -> None:
    """The worked example from the brief, spelled out rather than only parameterised."""
    reveal = StepUpGrant(scope=build_step_up_scope(StepUpAction.REVEAL, _ORDER_ID), granted_at=_NOW)

    assert require_step_up(StepUpAction.USER_BLOCK, _USER_ID)(
        reveal, now=_NOW, max_age_s=_GRACE_S
    ) is (AccessDecision.STEP_UP_SCOPE_MISMATCH)
    assert require_step_up(StepUpAction.REVEAL, _ORDER_ID)(
        reveal, now=_NOW, max_age_s=_GRACE_S
    ) is (AccessDecision.ALLOWED)


def test_a_grant_for_a_different_subject_of_the_same_action_is_refused() -> None:
    granted = StepUpGrant(
        scope=build_step_up_scope(StepUpAction.USER_BLOCK, _USER_ID), granted_at=_NOW
    )

    decision = check_access(
        Permission.USER_BLOCK,
        role=AdminRole.ADMIN,
        now=_NOW,
        subject_id="770000999",
        step_up=granted,
        grace_s=_GRACE_S,
    )

    assert decision is AccessDecision.STEP_UP_SCOPE_MISMATCH


def test_a_scope_prefix_is_not_a_scope() -> None:
    granted = StepUpGrant(scope=f"reveal:{_ORDER_ID}-extra", granted_at=_NOW)

    assert (
        check_step_up(granted, required_scope=f"reveal:{_ORDER_ID}", now=_NOW, max_age_s=_GRACE_S)
        is AccessDecision.STEP_UP_SCOPE_MISMATCH
    )


# ---------------------------------------------------------------------------
# Step-up: freshness
# ---------------------------------------------------------------------------
def test_a_stale_grant_expires() -> None:
    granted = StepUpGrant(
        scope=build_step_up_scope(StepUpAction.USER_BLOCK, _USER_ID),
        granted_at=_NOW - timedelta(seconds=_GRACE_S + 1),
    )

    decision = check_access(
        Permission.USER_BLOCK,
        role=AdminRole.ADMIN,
        now=_NOW,
        subject_id=_USER_ID,
        step_up=granted,
        grace_s=_GRACE_S,
    )

    assert decision is AccessDecision.STEP_UP_EXPIRED


@pytest.mark.parametrize("permission", [Permission.USER_PURGE, Permission.CONFIG_WRITE])
def test_the_grace_zero_actions_reject_a_grant_the_others_would_accept(
    permission: Permission,
) -> None:
    """Purge and config commit are the two §12.1 marks "fresh"; one second is not fresh."""
    age = timedelta(seconds=STEP_UP_FRESH_MAX_AGE_S + 1)
    granted = StepUpGrant(
        scope=build_step_up_scope(STEP_UP_ACTIONS[permission], _USER_ID),
        granted_at=_NOW - age,
    )

    assert (
        check_access(
            permission,
            role=AdminRole.OWNER,
            now=_NOW,
            subject_id=_USER_ID,
            step_up=granted,
            grace_s=_GRACE_S,
        )
        is AccessDecision.STEP_UP_EXPIRED
    )
    assert STEP_UP_FRESH_MAX_AGE_S < _GRACE_S


def test_a_grant_timestamped_in_the_future_is_not_an_authorisation() -> None:
    granted = StepUpGrant(scope=f"reveal:{_ORDER_ID}", granted_at=_NOW + timedelta(seconds=30))

    assert (
        check_step_up(granted, required_scope=f"reveal:{_ORDER_ID}", now=_NOW, max_age_s=_GRACE_S)
        is AccessDecision.STEP_UP_EXPIRED
    )


# ---------------------------------------------------------------------------
# Wiring: what the routers and the session row hand these functions
# ---------------------------------------------------------------------------
def test_a_step_up_permission_checked_without_a_subject_denies_rather_than_allows() -> None:
    decision = check_access(Permission.USER_PURGE, role=AdminRole.OWNER, now=_NOW, grace_s=_GRACE_S)

    assert decision is AccessDecision.STEP_UP_REQUIRED


def test_half_a_stored_grant_is_no_grant() -> None:
    assert step_up_from_session(None, _NOW) is None
    assert step_up_from_session("reveal:x", None) is None
    assert step_up_from_session("reveal:x", _NOW) == StepUpGrant("reveal:x", _NOW)


def test_require_names_its_permission_for_the_route_enumeration_test() -> None:
    guard = require(Permission.RECORDS_READ)

    assert guard.permission is Permission.RECORDS_READ
    assert guard(role=AdminRole.VIEWER, now=_NOW, grace_s=_GRACE_S) is AccessDecision.ALLOWED
    assert guard(role=AdminRole.OWNER, now=_NOW, grace_s=_GRACE_S) is AccessDecision.ALLOWED


def test_a_permission_guard_carries_the_step_up_check_too() -> None:
    guard = require(Permission.USER_BLOCK)
    scope = build_step_up_scope(StepUpAction.USER_BLOCK, _USER_ID)

    assert guard(role=AdminRole.SUPPORT, now=_NOW, subject_id=_USER_ID, grace_s=_GRACE_S) is (
        AccessDecision.FORBIDDEN_ROLE
    )
    assert (
        guard(
            role=AdminRole.ADMIN,
            now=_NOW,
            subject_id=_USER_ID,
            step_up=StepUpGrant(scope=scope, granted_at=_NOW),
            grace_s=_GRACE_S,
        )
        is AccessDecision.ALLOWED
    )


# ---------------------------------------------------------------------------
# Scope strings are storable identifiers, not free text
# ---------------------------------------------------------------------------
def test_a_scope_is_action_colon_subject() -> None:
    assert build_step_up_scope(StepUpAction.REVEAL, _ORDER_ID) == f"reveal:{_ORDER_ID}"


@pytest.mark.parametrize(
    "subject_id",
    ["", " ", "with space", "line\nbreak", "a" * MAX_STEP_UP_SCOPE_CHARS, "quote'"],
)
def test_an_unstorable_scope_is_refused_at_the_point_it_is_built(subject_id: str) -> None:
    """``step_up_scope`` is ``String(128)``; truncation there would widen a grant."""
    with pytest.raises(ValueError, match="storable"):
        build_step_up_scope(StepUpAction.REVEAL, subject_id)


def test_require_step_up_rejects_an_unstorable_scope_where_the_route_is_declared() -> None:
    with pytest.raises(ValueError, match="storable"):
        require_step_up(StepUpAction.REVEAL, "not a subject id")


def test_a_guard_exposes_the_scope_the_session_must_carry() -> None:
    guard = require_step_up(StepUpAction.CONFIG_WRITE, "v42")

    assert guard.scope == "config.write:v42"
    assert len(guard.scope) <= MAX_STEP_UP_SCOPE_CHARS


def test_every_grant_shape_in_the_matrix_is_one_of_the_plan_s_cells() -> None:
    for permission in RBAC_MATRIX:
        assert _any_grant(permission) in set(_CELLS.values())
