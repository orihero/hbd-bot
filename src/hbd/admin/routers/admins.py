"""``GET /api/admins`` — who can sign in to this panel, including who currently cannot.

**It is a read and it writes nothing.** Creating an operator, resetting a password,
demoting, deactivating: every one of those is a write, every one is an OWNER cell that
demands a step-up and an audit row, and none of them is in this slice. A ``GET`` that also
created something would be a state change behind a safe method, which the route-enumeration
test forbids and a browser prefetch would fire.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``.
The permission is :data:`~hbd.admin.security.permissions.Permission.ADMIN_READ` — owner,
write-class, **no step-up** — because §6.8 line 949 lists ``GET /admins`` as a bare ``W``
while giving each of the four account writes below it an explicit ``W +S``. §12.2 collapsed
the read and those writes into a single ``W+S`` row; the endpoint table is the more specific
statement and it won, and §12.2 has since been split to match (lines 1883-1884). The whole
argument, and the reason merging the two back together makes the roster unreachable by
everybody, is at the two rows in :mod:`hbd.admin.security.permissions`.

So the other three roles are a 403 with an audit row — and that refusal is written by the
guard, not here — while an OWNER is served without re-authenticating. ``check_access`` would
be the wrong question for the same reason it is on the audit and retention lists: with no
subject there is no scope to compare a step-up against, so ``check_access(subject_id=None)``
would log an ERROR on every request to a route that asks for no step-up at all. The step-up
``ADMIN_MANAGE`` carries belongs to the Phase 2 writes, on the account they are about to
change.

**The handler takes no ``Admin``.** The router dependency has already authenticated and
authorised the request, and there is nothing on this response to mask: an operator is staff,
and §12.3's masking is about customer personal data. Taking the operator in order to ignore
them would imply a cell-dependent projection that does not exist here.

**It is a bounded whole-table read, not a page.** ``list_all`` stops at
:data:`~hbd.db.admin.accounts.MAX_ADMIN_ACCOUNTS`, and the bound is the shape of the
question rather than a pagination default deferred: "who has access?" has one useful answer
and it is the whole list at once. A deployment with more operator accounts than the cap has
a problem the panel cannot fix, and a cursor in front of the roster would hide it rather
than surface it.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.schemas.admins import AdminRosterResponse, to_roster
from hbd.admin.security.permissions import Permission
from hbd.db.admin.accounts import list_all

__all__ = ["ADMINS_PATH", "build_admins_router"]

ADMINS_PATH: Final[str] = f"{API_PREFIX}/admins"


def build_admins_router() -> APIRouter:
    """The operator roster. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["admins"],
        dependencies=[Depends(require_permission(Permission.ADMIN_READ))],
    )

    @router.get(ADMINS_PATH)
    async def list_admins(db: Db) -> AdminRosterResponse:
        """Every operator account, oldest first, deactivated ones included.

        The credential itself never leaves the process: ``AdminAccountView`` names the
        fields it exposes and ``password_hash`` is not among them.
        """
        return to_roster(await list_all(db))

    return router
