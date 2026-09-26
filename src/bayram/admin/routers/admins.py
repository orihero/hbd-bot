"""``/api/admins`` — who can sign in to this panel, and the one route that adds somebody.

**Two routers, because the read and the write are two different cells.** The roster is
§6.8 line 949's bare owner ``W``; creating an operator is the ``W +S`` beneath it. The guard
is per-router (§12.1 T3), so they cannot share one — and a ``GET`` that also created
something would be a state change behind a safe method, which the route-enumeration test
forbids and a browser prefetch would fire.

**The read declares ``ADMIN_READ``.** Owner, write-class, **no step-up** — because §6.8 line
949 lists ``GET /admins`` as a bare ``W`` while giving each of the four account writes below
it an explicit ``W +S``. §12.2 collapsed the read and those writes into a single ``W+S`` row;
the endpoint table is the more specific statement and it won, and §12.2 has since been split
to match (lines 1883-1884). The whole argument, and the reason merging the rows back together
makes the roster unreachable by everybody, is beside them in
:mod:`bayram.admin.security.permissions`.

So the other three roles are a 403 with an audit row — and that refusal is written by the
guard, not here — while an OWNER is served without re-authenticating. ``check_access`` would
be the wrong question for the same reason it is on the audit and retention lists: with no
subject there is no scope to compare a step-up against, so ``check_access(subject_id=None)``
would log an ERROR on every request to a route that asks for no step-up at all.

**The write declares ``ADMIN_MANAGE_WRITE`` and the handler enforces ``ADMIN_MANAGE``.**
That is the split the reveal routes, the media routes, block/unblock and the credit grant
all take, for the same mechanical reason each time:
:func:`~bayram.admin.security.permissions.check_role` is what a router-level guard calls, it
holds no subject and therefore no grant, and it answers ``STEP_UP_REQUIRED`` to a ``W+S``
cell unconditionally — so a router guarded by ``ADMIN_MANAGE`` itself would refuse an OWNER
who has just re-authenticated for exactly this account, for ever, and it would look right.

**The step-up is scoped to the username, because the account does not exist yet.** Every
other subject-scoped action in the panel re-authenticates against a row that is already
there — a Telegram id, an order, a campaign — and this one cannot: the id it would name is
minted by the ``INSERT`` this request is asking for. So the scope is
``admin.manage:<username>``, which is also what lets the SPA's re-authentication prompt say
*which* operator is about to be created, and what makes an owner who edits the username
afterwards fall out of scope rather than quietly create somebody else. The charset that
costs is :data:`~bayram.admin.schemas.admins.ADMIN_USERNAME_PATTERN`, and it is argued there.

**Order inside the handler: step up, refuse, hash, insert, audit.** The step-up first,
because a refusal must cost nothing and change nothing. argon2id last of the checks, because
it is deliberately slow and a request that was going to be refused must not pay for it. The
audit row inside the request's transaction, per §9.1's first rule: this is a single database
transaction, so an unaudited account is then impossible rather than merely unlikely.

**OWNER cannot be created here, and the refusal is a sentence rather than a schema.**
``ix_admin_users_active_owner`` permits exactly one *active* OWNER (``models/admin_user.py``),
so a second one is refused by the database whatever this route thinks. Moving ownership is
``python -m bayram.admin.bootstrap --reset-owner`` on the host, which refuses while an active
OWNER remains and is therefore the only place a handover is deliberate. A narrowed enum on
the request body would turn all of that into a 422 listing three legal members, which reads
as "OWNER is misspelled"; this reads as the rule it is.

**There is no ``displayName``, and §6.8 line 950 lists one.** ``admin_users`` has no such
column in the shipped schema, and the same omission is already made and argued at
:class:`~bayram.admin.schemas.auth.MeResponse`: a field that is always the username would be
a promise the database does not keep. The body carries the reason trio instead, which §6.8's
row does not mention and §12.4 requires of every operator action — this one creates a
credential, so it is not the place to make accountability optional.

**Every refusal past the step-up writes its own audit row.** Somebody re-authenticated in
order to create an operator and did not get one, and §12.6's rule is that the log records
what operators did rather than what succeeded — the same rule that puts a row behind a
replayed credit grant. Those rows carry ``AuditOutcome.ERROR``, which
``models/admin_audit.py`` defines as an allowed action that then failed, and they name the
username they were refused for. The step-up refusal itself is audited one layer down, by
``deps.enforce_step_up``, as a ``PERMISSION_DENIED`` rather than as a create that failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError

from bayram.admin import audit_sink
from bayram.admin.container import AdminContainer
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    enforce_step_up,
    require_permission,
)
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem
from bayram.admin.schemas.admins import (
    AdminAccountView,
    AdminCreateRequest,
    AdminRosterResponse,
    to_account_view,
    to_roster,
)
from bayram.admin.security.passwords import hash_password_async
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.db.admin.accounts import (
    MAX_ADMIN_ACCOUNTS,
    count_all,
    create,
    get_by_username,
    list_all,
)
from bayram.db.admin.audit import AuditEntry
from bayram.db.base import utc_now
from bayram.db.enums import AdminRole, AuditAction
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.errors import ErrorCode

__all__ = [
    "ADMINS_PATH",
    "ADMIN_SUBJECT_TYPE",
    "build_admin_accounts_router",
    "build_admins_router",
]

ADMINS_PATH: Final[str] = f"{API_PREFIX}/admins"

#: ``admin_audit_log.subject_type`` for a row whose subject is an operator account. One of
#: :data:`bayram.db.admin.audit.SUBJECT_TYPES`' closed set, and the same value the auth routes
#: already write for a sign-in or a password change — the panel joins on these strings, so a
#: second spelling would split one account's history in two.
ADMIN_SUBJECT_TYPE: Final[str] = "admin"

#: 201, spelled once. The body is the account that now exists, so this is a ``Created``
#: rather than the ``204`` the sign-out route answers with.
_CREATED: Final[int] = 201

#: ``record_count`` for a create that produced an account, and for one that did not. The
#: column is "how much did this action move?", so an operator added is 1 and every refusal
#: is 0 — which keeps "how many operators were added this quarter" a ``SUM`` over an indexed
#: action filter rather than a join onto ``admin_users``.
_ONE_ACCOUNT: Final[int] = 1
_NO_ACCOUNT: Final[int] = 0

_OWNER_REFUSAL: Final[str] = (
    "An OWNER cannot be created from the panel: the database permits exactly one active "
    "owner. Hand ownership over with `python -m bayram.admin.bootstrap --reset-owner` on the "
    "host, which refuses while an active owner remains."
)
_TAKEN_REFUSAL: Final[str] = "that username already has an account — pick another"
_FULL_REFUSAL: Final[str] = (
    f"this panel already holds {MAX_ADMIN_ACCOUNTS} operator accounts, which is the most the "
    "roster can show. Deactivate an account nobody uses before adding another."
)


def build_admins_router() -> APIRouter:
    """The operator roster. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["admins"],
        dependencies=[Depends(require_permission(Permission.ADMIN_READ))],
    )

    @router.get(ADMINS_PATH)
    async def list_admins(db: Db) -> AdminRosterResponse:
        """Every operator account, oldest first, deactivated ones included.

        **It is a bounded whole-table read, not a page.** ``list_all`` stops at
        :data:`~bayram.db.admin.accounts.MAX_ADMIN_ACCOUNTS`, and the bound is the shape of the
        question rather than a pagination default deferred: "who has access?" has one useful
        answer and it is the whole list at once. The create route refuses at that same
        number rather than letting this read silently truncate past it.

        **The handler takes no ``Admin``.** The router dependency has already authenticated
        and authorised the request, and there is nothing on this response to mask: an
        operator is staff, and §12.3's masking is about customer personal data. Taking the
        operator in order to ignore them would imply a cell-dependent projection that does
        not exist here.

        The credential itself never leaves the process: ``AdminAccountView`` names the
        fields it exposes and ``password_hash`` is not among them.
        """
        return to_roster(await list_all(db))

    return router


def build_admin_accounts_router() -> APIRouter:
    """The create. ``ADMIN_MANAGE_WRITE`` on the router; ``ADMIN_MANAGE``'s step-up inside."""
    router = APIRouter(
        tags=["admins"],
        dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE_WRITE))],
    )

    @router.post(ADMINS_PATH, status_code=_CREATED)
    async def create_admin(
        body: AdminCreateRequest, db: Db, admin: Admin, container: Container
    ) -> AdminAccountView:
        """Add one operator account: active, and holding a password it must replace at once.

        ``must_change_password=True`` is passed rather than defaulted, and it is not
        negotiable from the wire: the password on this body was chosen by the owner filling
        the form in, so the account starts life with a credential its holder never picked.
        The flag is what turns that from a shared secret into a handover — the first sign-in
        reaches nothing until it has been replaced
        (``deps._enforce_password_rotation``).

        ``now`` is read once and threaded through the step-up window, the row's three
        timestamps and the audit entry, so none of them can land on the far side of a
        boundary from the others.

        The response is the row that was written, projected from the flushed object rather
        than echoed from the request: ``id``, ``createdAt`` and ``passwordChangedAt`` are the
        database's answers, and the panel appends the result to the roster it already holds.
        """
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.ADMIN_MANAGE,
            subject_id=body.username,
            now=now,
        )
        if body.role is AdminRole.OWNER:
            raise await _refused(
                container,
                admin,
                body,
                code=ErrorCode.INVALID_INPUT,
                message=_OWNER_REFUSAL,
                now=now,
            )
        # Read before insert, and NOT the guarantee — a pre-flight ``SELECT`` is a race, and
        # ``uq_admin_users_username`` is what actually closes it (see the ``IntegrityError``
        # below). This is here for the message: the ordinary case is an owner retyping a name
        # that is on the roster in front of them, and that deserves a sentence and an audit
        # row rather than a constraint name surfacing two statements later.
        if await get_by_username(db, body.username) is not None:
            raise await _refused(
                container,
                admin,
                body,
                code=AdminErrorCode.CONFLICT,
                message=_TAKEN_REFUSAL,
                now=now,
            )
        # The cap the roster read stops at. Refusing here is what keeps that bound honest:
        # past it, ``list_all`` would return 500 accounts out of more and the panel would
        # answer "who has access?" with a number smaller than the number of credentials.
        if await count_all(db) >= MAX_ADMIN_ACCOUNTS:
            raise await _refused(
                container,
                admin,
                body,
                code=AdminErrorCode.CONFLICT,
                message=_FULL_REFUSAL,
                now=now,
            )
        password_hash = await hash_password_async(body.password, hasher=container.hasher)
        try:
            row = await create(
                db,
                username=body.username,
                password_hash=password_hash,
                role=body.role,
                must_change_password=True,
                now=now,
            )
        except IntegrityError as exc:
            # The losing side of a genuine race — two owners creating one username at the
            # same moment — and the only path here that writes no audit row. This
            # transaction is already aborted, so the row cannot go in it, and
            # ``record_refusal``'s own transaction would have to be opened while this one is
            # mid-rollback, which is the one thing that pattern is not for. Nothing was
            # written, the winner's account exists, and the winner's row is in the log.
            raise problem(AdminErrorCode.CONFLICT, _TAKEN_REFUSAL) from exc
        await audit_sink.record(
            db,
            container,
            _entry(admin, body, outcome=AuditOutcome.OK, record_count=_ONE_ACCOUNT),
            now=now,
        )
        return to_account_view(row)

    return router


async def _refused(
    container: AdminContainer,
    admin: CurrentAdmin,
    body: AdminCreateRequest,
    *,
    code: AdminErrorCode | ErrorCode,
    message: str,
    now: datetime,
) -> ProblemError:
    """Audit a refusal in its own committed transaction, then hand back what to raise.

    Returns the exception rather than raising it, so the call site reads ``raise await
    _refused(...)`` and the control flow is where a reader looks for it. The row goes in a
    transaction of its own for ``audit_sink``'s reason: the request's is about to roll back,
    and a refusal recorded in it would roll back with the refusal.
    """
    await audit_sink.record_refusal(
        container,
        _entry(admin, body, outcome=AuditOutcome.ERROR, error_code=str(code)),
        now=now,
    )
    return ProblemError(AdminProblem(code=code, message=message))


def _entry(
    admin: CurrentAdmin,
    body: AdminCreateRequest,
    *,
    outcome: AuditOutcome,
    error_code: str | None = None,
    record_count: int = _NO_ACCOUNT,
) -> AuditEntry:
    """One ``ADMIN_CREATE`` row, whether or not an account came out of it.

    ``subject_id`` is the **username**, and it is the same value on every path. On a refusal
    there is no id to name; on a success there is one, but naming it would leave the
    successful create the only row in this action's history a reader cannot line up with the
    attempts that preceded it. :data:`~bayram.admin.schemas.admins.ADMIN_USERNAME_PATTERN` is a
    subset of ``audit._SUBJECT_ID_PATTERN`` precisely so this column can hold it.

    ``field_names`` names the columns the insert sets and never their values (§12.4) —
    ``password_hash`` among them, because "a credential was written" is the fact and nothing
    in the *name* could ever be replayed. ``is_active`` and ``must_change_password`` are left
    out: they are the same on every create, so they carry no information.
    """
    return AuditEntry(
        action=AuditAction.ADMIN_CREATE,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=ADMIN_SUBJECT_TYPE,
        subject_id=body.username,
        field_names=("admin_users.username", "admin_users.role", "admin_users.password_hash"),
        record_count=record_count,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=outcome,
        error_code=error_code,
        ip=admin.client_ip,
    )
