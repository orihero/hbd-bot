"""The step-up grace window is configuration, and "grace 0" is really zero.

Two claims are pinned here, and both were false while the window was the module constant
``STEP_UP_MAX_AGE_S = 900``.

**1. The window is ``AdminSettings.admin_step_up_grace_seconds``.** A setting that nothing
reads is worse than the constant it replaced: it looks configurable, an operator lowers it
after an incident, and the guard keeps honouring fifteen minutes. So the guards take the
window as a required argument — there is no module default left to fall back to — and the
one live caller, ``POST /api/auth/step-up``, reports an expiry derived from the same value.

**2. Purge and config commit have no grace at all (§12.1 T2).** Sixty seconds was a grace,
and the field's own docstring promises that raising the setting cannot loosen these two.
Both halves are asserted: a one-second-old grant cannot purge even at the maximum
configurable grace, and the route tells the operator so rather than quoting a window the
guard will not honour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from hbd.admin.container import AdminContainer
from hbd.admin.deps import CurrentAdmin, require_permission
from hbd.admin.errors import AdminErrorCode, AdminProblem, ProblemError
from hbd.admin.security import permissions
from hbd.admin.security.permissions import (
    STEP_UP_ACTIONS,
    STEP_UP_FRESH_MAX_AGE_S,
    AccessDecision,
    Permission,
    StepUpAction,
    StepUpGrant,
    StepUpRequirement,
    build_step_up_scope,
    check_access,
    max_age_for_action,
)
from hbd.admin.sessions import SessionSnapshot
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole

from .conftest import (
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

_NOW = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
_USER_ID = "418"
#: The model's ceiling for ``admin_step_up_grace_seconds``. Used where a test needs the
#: loosest window the operator can possibly configure, to show a tightening is not optional.
_MAX_GRACE_S = 900


def _grant(permission: Permission, *, age_s: float) -> StepUpGrant:
    return StepUpGrant(
        scope=build_step_up_scope(STEP_UP_ACTIONS[permission], _USER_ID),
        granted_at=_NOW - timedelta(seconds=age_s),
    )


def _decide(permission: Permission, *, age_s: float, grace_s: int) -> AccessDecision:
    return check_access(
        permission,
        role=AdminRole.OWNER,
        now=_NOW,
        subject_id=_USER_ID,
        step_up=_grant(permission, age_s=age_s),
        grace_s=grace_s,
    )


# ---------------------------------------------------------------------------
# 1. The window is the setting, not a constant
# ---------------------------------------------------------------------------
def test_the_module_no_longer_carries_a_hardcoded_grace_window() -> None:
    """``STEP_UP_MAX_AGE_S`` is gone, from the module and from its ``__all__``.

    Left in place it would be a second answer to "how long is a step-up good for", and the
    two would drift the first time an operator changed the setting.
    """
    assert not hasattr(permissions, "STEP_UP_MAX_AGE_S")
    assert "STEP_UP_MAX_AGE_S" not in permissions.__all__


@pytest.mark.parametrize(
    ("grace_s", "age_s", "expected"),
    [
        (60, 30, AccessDecision.ALLOWED),
        (60, 61, AccessDecision.STEP_UP_EXPIRED),
        (300, 61, AccessDecision.ALLOWED),
        (300, 301, AccessDecision.STEP_UP_EXPIRED),
        (900, 899, AccessDecision.ALLOWED),
        (900, 901, AccessDecision.STEP_UP_EXPIRED),
        (0, 1, AccessDecision.STEP_UP_EXPIRED),
    ],
)
def test_the_configured_grace_decides_when_an_ordinary_grant_lapses(
    grace_s: int, age_s: float, expected: AccessDecision
) -> None:
    """The same grant is live or expired depending only on the configured window."""
    assert _decide(Permission.USER_BLOCK, age_s=age_s, grace_s=grace_s) is expected


def test_a_zero_grace_makes_every_action_reprompt() -> None:
    """The field documents 0 as "every action in the scope re-prompts"; that is asserted."""
    assert _decide(Permission.USER_BLOCK, age_s=1, grace_s=0) is AccessDecision.STEP_UP_EXPIRED
    assert _decide(Permission.USER_BLOCK, age_s=0, grace_s=0) is AccessDecision.ALLOWED


# ---------------------------------------------------------------------------
# 2. Grace 0 for purge and config commit is real
# ---------------------------------------------------------------------------
def test_the_fresh_window_is_zero_seconds() -> None:
    assert STEP_UP_FRESH_MAX_AGE_S == 0


@pytest.mark.parametrize("permission", [Permission.USER_PURGE, Permission.CONFIG_WRITE])
def test_a_one_second_old_grant_cannot_purge_or_commit_config(permission: Permission) -> None:
    """One second is a grace. §12.1 T2 gives these two none."""
    assert _decide(permission, age_s=1, grace_s=_MAX_GRACE_S) is AccessDecision.STEP_UP_EXPIRED


@pytest.mark.parametrize("permission", [Permission.USER_PURGE, Permission.CONFIG_WRITE])
@pytest.mark.parametrize("grace_s", [0, 300, _MAX_GRACE_S])
def test_raising_the_grace_cannot_loosen_a_fresh_action(
    permission: Permission, grace_s: int
) -> None:
    """The setting's docstring promises this, so it is a test and not a comment."""
    assert max_age_for_action(STEP_UP_ACTIONS[permission], grace_s=grace_s) == 0
    assert _decide(permission, age_s=30, grace_s=grace_s) is AccessDecision.STEP_UP_EXPIRED


@pytest.mark.parametrize("permission", [Permission.USER_PURGE, Permission.CONFIG_WRITE])
def test_a_step_up_issued_by_the_request_itself_still_authorises_a_fresh_action(
    permission: Permission,
) -> None:
    """Zero is a window, not a wall: a grant carrying this request's own instant passes.

    This is what keeps grace 0 implementable — the fresh path is a step-up granted and
    consumed under one ``now``, which is why it is not simply unsatisfiable.
    """
    assert _decide(permission, age_s=0, grace_s=0) is AccessDecision.ALLOWED


def test_every_action_that_guards_a_fresh_permission_has_a_zero_window() -> None:
    """Derived from the matrix, so a future FRESH cell cannot quietly inherit the grace."""
    fresh = {
        STEP_UP_ACTIONS[permission]
        for permission, row in permissions.RBAC_MATRIX.items()
        if any(grant.step_up is StepUpRequirement.FRESH for grant in row.values())
    }
    assert fresh == {StepUpAction.USER_PURGE, StepUpAction.CONFIG_WRITE}
    for action in fresh:
        assert max_age_for_action(action, grace_s=_MAX_GRACE_S) == 0


# ---------------------------------------------------------------------------
# 3. The router guard asks the question it can actually answer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("permission", list(permissions.RBAC_MATRIX))
@pytest.mark.parametrize("role", list(AdminRole))
def test_check_role_answers_the_matrix_without_a_window(
    permission: Permission, role: AdminRole
) -> None:
    """No subject, no grant, therefore no window — and the answer still comes from §12.2."""
    grant = permissions.grant_for(permission, role)
    if grant is None:
        expected = AccessDecision.FORBIDDEN_ROLE
    elif grant.step_up is StepUpRequirement.NONE:
        expected = AccessDecision.ALLOWED
    else:
        expected = AccessDecision.STEP_UP_REQUIRED

    assert permissions.check_role(permission, role) is expected


async def test_the_router_guard_asks_for_a_step_up_rather_than_calling_it_forbidden(
    container: AdminContainer,
) -> None:
    """An OWNER holds ``user.purge``; what they are missing is the step-up, not the role.

    The distinction is what the SPA branches on: ``STEP_UP_REQUIRED`` opens the
    re-authentication prompt, ``FORBIDDEN`` must not offer one.
    """
    guard = require_permission(Permission.USER_PURGE)
    owner = CurrentAdmin(
        admin_user_id=uuid4(),
        username="owner",
        role=AdminRole.OWNER,
        must_change_password=False,
        last_login_at=None,
        session=_live_session(),
        token_sha256="0" * 64,
        client_ip=None,
    )

    with pytest.raises(ProblemError) as caught:
        await guard(owner, container)

    failure = caught.value.failure
    assert isinstance(failure, AdminProblem)
    assert failure.code is AdminErrorCode.STEP_UP_REQUIRED


def _live_session() -> SessionSnapshot:
    """A session live by both clocks and carrying no step-up. The guard reads neither."""
    now = utc_now()
    return SessionSnapshot(
        session_id=uuid4(),
        admin_user_id=uuid4(),
        csrf_token="csrf",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=1),
        step_up_scope=None,
        step_up_at=None,
    )


# ---------------------------------------------------------------------------
# 4. The one live caller reports the window it will actually honour
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("grace_s", [0, 60, 900])
async def test_the_step_up_route_reports_the_configured_grace(grace_s: int) -> None:
    """``expiresAt - grantedAt`` is the setting, not fifteen hardcoded minutes."""
    settings = make_settings(admin_step_up_grace_seconds=grace_s)
    async with open_container(settings, FakeRedis(), MemoryRateLimits()) as container:
        await create_account(container)
        async with open_client(container) as client:
            await sign_in(client)
            response = await client.post(
                "/api/auth/step-up",
                json={"password": PASSWORD, "scope": "user.block", "subjectId": _USER_ID},
                headers=csrf_headers(client),
            )

    assert response.status_code == 200
    body = response.json()
    granted = datetime.fromisoformat(body["grantedAt"])
    expires = datetime.fromisoformat(body["expiresAt"])
    assert (expires - granted).total_seconds() == grace_s


async def test_the_step_up_route_promises_no_grace_for_a_purge() -> None:
    """A purge step-up that claimed five minutes would be a lie the guard then refuses."""
    settings = make_settings(admin_step_up_grace_seconds=_MAX_GRACE_S)
    async with open_container(settings, FakeRedis(), MemoryRateLimits()) as container:
        await create_account(container)
        async with open_client(container) as client:
            await sign_in(client)
            response = await client.post(
                "/api/auth/step-up",
                json={"password": PASSWORD, "scope": "user.purge", "subjectId": _USER_ID},
                headers=csrf_headers(client),
            )

    assert response.status_code == 200
    body = response.json()
    assert body["expiresAt"] == body["grantedAt"]
