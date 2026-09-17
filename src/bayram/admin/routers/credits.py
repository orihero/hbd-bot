"""``/users/{telegramUserId}/credits`` — the entitlement ledger, and the one way to add to it.

**Two routers, because the read and the write are two different cells.** The ledger is an
ordinary record: it explains a balance the ``/users`` row already shows, holds no personal
data (``credit_ledger`` is deliberately absent from ``tables_with_personal_data``), and so it
sits on ``RECORDS_READ`` beside the row it explains. The grant issues value, and §12.2 has no
row for it at all — the cell this codebase rules for it, and the threat-model argument behind
that ruling, are written out beside ``Permission.CREDIT_GRANT`` in
:mod:`bayram.admin.security.permissions`.

**The grant router declares ``CREDIT_GRANT_WRITE`` and the handler enforces ``CREDIT_GRANT``.**
That is the split the reveal routes, the media routes and the block pair all take, for the
same mechanical reason each time: :func:`~bayram.admin.security.permissions.check_role` is what a
router-level guard calls, it holds no subject and therefore no grant, and it answers
``STEP_UP_REQUIRED`` to a ``W+S`` cell unconditionally — so a router guarded by
``CREDIT_GRANT`` itself would refuse an ADMIN who has just re-authenticated for exactly this
account, for ever, and it would look right.

**The write goes through ``db.credits.grant`` and nothing else.** That function opens the
account, appends the ledger row and moves ``credit_accounts.balance`` in one transaction, and
its ``INSERT … ON CONFLICT DO NOTHING`` on the idempotency key is what makes two racing
writers produce one row and one loser. A route that inserted a ledger row itself would be a
second writer of a balance whose whole design (``models/credit_account.py``) rests on there
being one.

**Order inside the handler: step up, grant, audit, read back.** The step-up first, because a
refusal must cost nothing and change nothing. The audit row inside the request's transaction,
per §9.1's first rule — this is a single database transaction, so an unaudited grant is then
impossible rather than merely unlikely. The read back last and from the database rather than
from arithmetic, so the balance in the response is one the ledger agrees with.

**A replay writes an audit row too, and that is deliberate.** ``grant`` answers ``False`` when
this idempotency key was already used, and nothing moves — but somebody still asked, under a
fresh step-up, and §12.6's rule is that the log records what operators did rather than what
succeeded in changing something. The row carries ``record_count=0`` so the two are told apart
by a query rather than by reading reasons, and the response says ``isReplay: true`` so a
client that retried a timed-out request is not left inferring it from a balance.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink
from bayram.admin.deps import (
    Admin,
    Container,
    CurrentAdmin,
    Db,
    enforce_step_up,
    require_permission,
)
from bayram.admin.errors import ProblemError
from bayram.admin.routers.users import USER_PATH, USER_SUBJECT_TYPE, no_such_user
from bayram.admin.schemas.credits import (
    CreditGrantRequest,
    CreditGrantResultView,
    CreditLedgerPage,
    to_credit_account_view,
    to_credit_entry_view,
)
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.credits import count_credit_entries, get_credit_account, list_credit_entries
from bayram.db.admin.users import UserFilters, count_users
from bayram.db.base import utc_now
from bayram.db.credits import grant
from bayram.db.enums import AuditAction
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.db.models.credit_ledger import ACTOR_LENGTH
from bayram.errors import StorageError

__all__ = [
    "USER_CREDITS_PATH",
    "USER_CREDITS_GRANT_PATH",
    "ADMIN_ACTOR_PREFIX",
    "admin_actor",
    "build_credits_router",
    "build_credit_grant_router",
]

#: Built from ``USER_PATH`` rather than spelled out, so ``/api/users/{telegram_user_id}``
#: exists once in this codebase and the namespace cannot grow a second identifier name.
USER_CREDITS_PATH: Final[str] = f"{USER_PATH}/credits"
USER_CREDITS_GRANT_PATH: Final[str] = f"{USER_CREDITS_PATH}/grant"

#: ``credit_ledger.actor`` for a movement an operator caused. The vocabulary is ``bot`` |
#: ``pipeline`` | ``sweep`` | ``admin:{username}`` (``models/credit_ledger.py``:
#: ``ACTOR_LENGTH``), so the prefix is what makes a grant distinguishable from an allowance
#: in a query that never joins the audit log.
ADMIN_ACTOR_PREFIX: Final[str] = "admin:"

#: Declared per router, exactly as ``orders.py`` and ``users.py`` declare their own. The
#: alias is one line; what matters is the ``withTotal`` spelling, which is the same on every
#: list endpoint and is what a bare ``with_total: bool`` would silently change to ``with_total``
#: on the wire — a query parameter the SPA never sends and the server never complains about.
WithTotal = Annotated[bool, Query(alias="withTotal")]


def admin_actor(username: str) -> str:
    """``admin:{username}``, truncated to fit ``credit_ledger.actor``'s 32 characters.

    Truncated at the END, so the prefix always survives: a 30-character operator name that
    dropped the ``admin:`` instead would leave a ledger row indistinguishable from one the
    pipeline wrote. The truncation is safe because this column is diagnostic attribution and
    not identity — ``admin_audit_log`` holds the authoritative "who", at 64 characters, and
    ``ACTOR_LENGTH``'s own comment says exactly this.
    """
    return f"{ADMIN_ACTOR_PREFIX}{username}"[:ACTOR_LENGTH]


def build_credits_router() -> APIRouter:
    """The ledger read. ``RECORDS_READ``, like the ``/users`` row it explains."""
    router = APIRouter(
        tags=["credits"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(USER_CREDITS_PATH)
    async def list_user_credits(
        db: Db, telegram_user_id: int, paging: Paging, with_total: WithTotal = False
    ) -> CreditLedgerPage:
        """This account's balance and one keyset page of its movements, newest first.

        The existence check is what keeps "this customer has never spent a credit" and "we
        hold nothing about this id at all" apart: without it an unknown id answers with an
        empty ledger and the first reading is the one an operator takes.

        **It asks the credit subsystem as well as ``users``, and the order matters.** The
        account row is read first and is itself proof that something is held under this id:
        ``grant_credits`` below has deliberately no 404 because ``db.credits.grant`` calls
        ``open_account``, which writes ``credit_accounts`` and **no ``users`` row** — so a
        ``users``-only probe would 404 on the ledger, the balance and the audit trail this
        API had just written for the population the grant route exists to serve. The
        ``count_users`` probe survives, one statement cheaper than it was: it runs only when
        there is no account, which is exactly the case it can still answer for (a customer
        who has spoken to the bot and never been metered). An id neither table has heard of
        is still a 404, which is the distinction this endpoint's tests pin.

        ``account`` is ``null`` for a user who has a ``users`` row and no ``credit_accounts``
        one — never a zeroed object. That is a different fact from a balance of 0 and the two
        must not render alike; :class:`~bayram.admin.schemas.credits.CreditLedgerPage` says which
        two populations land there.
        """
        account = await get_credit_account(db, telegram_user_id)
        if account is None:
            existing = await count_users(db, filters=UserFilters(telegram_user_id=telegram_user_id))
            if existing.total == 0:
                raise no_such_user()
        page = await list_credit_entries(db, telegram_user_id=telegram_user_id, request=paging)
        total = (
            await count_credit_entries(db, telegram_user_id=telegram_user_id)
            if with_total
            else None
        )
        return CreditLedgerPage(
            account=None if account is None else to_credit_account_view(account),
            items=[to_credit_entry_view(item) for item in page.items],
            meta=page_meta(page, total),
        )

    return router


def build_credit_grant_router() -> APIRouter:
    """The grant. ``CREDIT_GRANT_WRITE`` on the router; ``CREDIT_GRANT``'s step-up inside."""
    router = APIRouter(
        tags=["credits"],
        dependencies=[Depends(require_permission(Permission.CREDIT_GRANT_WRITE))],
    )

    @router.post(USER_CREDITS_GRANT_PATH)
    async def grant_credits(
        body: CreditGrantRequest, db: Db, admin: Admin, container: Container, telegram_user_id: int
    ) -> CreditGrantResultView:
        """Add credits to one account on an operator's say-so, with a mandatory reason.

        **There is no 404**, and the reason is the writer's: ``db.credits.grant`` calls
        ``open_account`` first, so an account that has never been metered is opened by this
        call — which is precisely the customer a goodwill comp is usually for. Refusing an id
        with no ``credit_accounts`` row would refuse the common case; refusing one with no
        ``users`` row would make the route an existence oracle for guessable Telegram ids, and
        would also refuse an account that ``credits.touch`` has simply not seen since the
        onboarding deploy. The credit lands on the account either way, because the ledger is
        keyed on the Telegram id and never on ``users.id``.

        The idempotency key is minted here when the caller sent no ``requestId``, so two
        presses of the button are two grants — the honest reading of two presses. A caller
        that retries a timed-out request sends the same ``requestId`` and gets
        ``isReplay: true`` with nothing moved.

        **The key carries the Telegram id, and leaving it out was a silent no-op.**
        ``credit_ledger.idempotency_key`` is globally unique, so a bare
        ``grant:admin:{requestId}`` made one ``requestId`` reused across two accounts credit
        the first and quietly issue nothing to the second: ``grant`` sees a used key, answers
        ``False``, and the response says ``grantedCredits: N`` with ``isReplay: true`` — a
        value-issuing action reporting a number nobody was ever given. Any caller keying
        ``requestId`` off something coarser than one press of one button (a ticket id, a
        resubmitted form) hits that. Scoped to the subject the step-up was taken for, the
        collision is impossible rather than unlikely, and retry-safety is unchanged for the
        case ``requestId`` exists to serve: same caller, same account, same request.

        ``now`` is read once and threaded through the step-up window, the ledger row, the
        audit row and the response, so none of them can land on the far side of a boundary
        from the others.
        """
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.CREDIT_GRANT,
            subject_id=str(telegram_user_id),
            now=now,
        )
        key = f"grant:admin:{telegram_user_id}:{body.request_id or uuid4()}"
        is_written = await grant(
            db,
            telegram_user_id=telegram_user_id,
            credits=body.credits,
            idempotency_key=key,
            actor=admin_actor(admin.username),
            now=now,
        )
        await audit_sink.record(
            db,
            container,
            _grant_entry(
                admin,
                telegram_user_id=telegram_user_id,
                body=body,
                key=key,
                is_written=is_written,
            ),
            now=now,
        )
        account = await get_credit_account(db, telegram_user_id)
        if account is None:  # pragma: no cover - ``grant`` opened it in this transaction
            # Unreachable by construction — ``grant`` calls ``open_account`` before it writes
            # anything, in this transaction — and raised rather than papered over with a
            # zeroed object, because a response that invented ``balance: 0`` here would be
            # the panel telling an operator their grant did nothing. Through ``ProblemError``
            # so it lands in the shared envelope as a 503 rather than as a bare 500.
            raise ProblemError(
                StorageError(
                    "the account this grant opened could not be read back",
                    context={"telegram_user_id": telegram_user_id},
                )
            )
        return CreditGrantResultView(
            telegram_user_id=telegram_user_id,
            telegram_user_id_masked=mask_telegram_user_id(telegram_user_id),
            granted_credits=body.credits,
            is_replay=not is_written,
            idempotency_key=key,
            account=to_credit_account_view(account),
        )

    return router


def _grant_entry(
    admin: CurrentAdmin,
    *,
    telegram_user_id: int,
    body: CreditGrantRequest,
    key: str,
    is_written: bool,
) -> AuditEntry:
    """One ``CREDIT_GRANT`` row, whether or not the credits moved.

    ``record_count`` carries **how many credits were actually issued** — the request's number
    on a real grant, and ``0`` on a replay. The column is documented as "how many records were
    exposed", which is a reveal's reading of the same question ("how much did this action
    move?"), and using it here means "which operator comped how much this month" is a
    ``SUM`` over an indexed action filter rather than a join onto the ledger. The alternative
    was putting the number in ``reason_text``, which is free text on a 90-day sweep and would
    make the amount the one part of a value-issuing action that expires.

    ``field_names`` names the columns that moved, never their values, and ``subject_id`` is the
    Telegram id — inside ``audit._SUBJECT_ID_PATTERN``'s closed shape because it is digits.
    """
    return AuditEntry(
        action=AuditAction.CREDIT_GRANT,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=USER_SUBJECT_TYPE,
        subject_id=str(telegram_user_id),
        field_names=("credit_accounts.balance", "credit_accounts.lifetime_granted"),
        record_count=body.credits if is_written else 0,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        # ``OK`` on a replay too, and no new member for it. ``AuditOutcome`` has exactly
        # three values on purpose (``models/admin_audit.py:96-112``): ``DENIED`` is the
        # permission matrix refusing somebody and ``ERROR`` is an allowed action that then
        # failed. A replay is neither — the operator was allowed, nothing failed, and the
        # account holds the credits they asked for. ``record_count=0`` is what says the
        # balance did not move, which keeps "how much was comped this month" a ``SUM`` that
        # cannot double-count a retry.
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
