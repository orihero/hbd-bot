"""``/users/{telegramUserId}/credits`` and its grant, over the real ASGI stack.

The credit subsystem had been fully built in persistence for a whole phase with **zero** reach
into the admin package, so this file is the first thing that proves the two are wired together
at all. Four assertions carry it:

**1. The write goes through ``db.credits.grant`` and moves both representations.**
``credit_accounts.balance`` is a deliberate duplicate of ``SUM(credit_ledger.delta)``
(``models/credit_account.py``), and the whole design rests on one writer holding them in one
transaction. So the grant is asserted against the ledger row *and* the balance, not against
the response body — a handler that returned an optimistic number would pass a body-only test.

**2. The idempotency key is the caller's when they supply one, and it is scoped to the
account.** ``grant:admin:{telegramUserId}:{uuid4}`` is the shape ``credit_ledger`` reserves,
the unique index on it is what makes a duplicate impossible rather than unlikely, and a
retried request must top the account up once. The replay is asserted the only way it can be —
balance unchanged, one ledger row, two audit rows, ``isReplay: true``. The subject is in the
key because that index is unique GLOBALLY: without it one ``requestId`` reused across two
customers credited the first and silently no-opped the second, which is its own test.

**3. The step-up is scoped to the account being credited.** Granting is the one action in the
panel that issues value, so a grant taken for one customer must not credit another, and one
taken for ``user.block`` must not credit anybody. Both are driven through the real
``POST /api/auth/step-up``.

**4. The ledger's absence cases stay distinguishable.** An id NEITHER table has heard of is a
404; a ``users`` row with no ``credit_accounts`` row is a 200 whose ``account`` is ``null``,
never a zeroed object — because "never metered, still owed a full allowance" and "spent
everything" are opposite facts about a refused customer; and a ``credit_accounts`` row with
no ``users`` row — which is precisely what the grant route opens — is a 200 too, because the
alternative was 404ing on data this API had just written.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from hbd.admin.container import AdminContainer
from hbd.admin.errors import AdminErrorCode
from hbd.admin.routers.credits import USER_CREDITS_GRANT_PATH, USER_CREDITS_PATH, admin_actor
from hbd.admin.schemas.credits import MAX_GRANT_CREDITS
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode, CreditEntryKind, CreditReason
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.credit_account import CreditAccountRow
from hbd.db.models.credit_ledger import ACTOR_LENGTH, CreditLedgerRow
from tests.test_admin.conftest import (
    NOW,
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
from tests.test_admin.test_users_router import seed_user

TELEGRAM_USER_ID: Final[int] = 987_654_321
#: An id no seeded row uses, for the 404 path and for the "no ``users`` row" grant.
UNSEEN_USER_ID: Final[int] = 555_000_222
#: A second seeded account, for the assertion that one ``requestId`` credits both.
OTHER_USER_ID: Final[int] = 123_456_789

CREDITS_URL: Final[str] = USER_CREDITS_PATH.format(telegram_user_id=TELEGRAM_USER_ID)
GRANT_URL: Final[str] = USER_CREDITS_GRANT_PATH.format(telegram_user_id=TELEGRAM_USER_ID)


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with (
        open_container(make_settings(), FakeRedis(), MemoryRateLimits()) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http)


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.ADMIN, username: str = "") -> str:
    """Sign in as ``role``. ADMIN by default: the grant cell starts there, so a file that only
    ever used OWNER would not notice the cell narrowing."""
    name = username or f"{role.value}-account"
    await create_account(panel.container, username=name, role=role)
    assert (await sign_in(panel.http, username=name, password=PASSWORD)).status_code == 200
    return name


async def step_up(panel: Panel, *, subject: int, scope: str = "credit.grant") -> httpx.Response:
    return await panel.http.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": str(subject)},
        headers=csrf_headers(panel.http),
    )


async def post_grant(panel: Panel, url: str = GRANT_URL, **body: Any) -> httpx.Response:
    payload: dict[str, Any] = {
        "credits": 2,
        "reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value,
        **body,
    }
    return await panel.http.post(url, json=payload, headers=csrf_headers(panel.http))


async def ledger_rows(container: AdminContainer) -> list[CreditLedgerRow]:
    async with container.session_factory.begin() as db:
        statement = sa.select(CreditLedgerRow).order_by(CreditLedgerRow.created_at)
        return list((await db.execute(statement)).scalars().all())


async def stored_balance(container: AdminContainer, telegram_user_id: int) -> int | None:
    async with container.session_factory.begin() as db:
        balance: int | None = await db.scalar(
            sa.select(CreditAccountRow.balance).where(
                CreditAccountRow.telegram_user_id == telegram_user_id
            )
        )
        return balance


async def grant_audit_rows(container: AdminContainer) -> list[AdminAuditRow]:
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == AuditAction.CREDIT_GRANT)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


async def seed_account(panel: Panel, *, balance: int = 1, lifetime: int = 4) -> None:
    async with panel.container.session_factory.begin() as db:
        db.add(
            CreditAccountRow(
                telegram_user_id=TELEGRAM_USER_ID,
                balance=balance,
                lifetime_granted=lifetime,
                allowance_period_index=3,
                created_at=NOW,
                updated_at=NOW,
            )
        )


async def seed_entry(panel: Panel, **kw: Any) -> None:
    async with panel.container.session_factory.begin() as db:
        db.add(
            CreditLedgerRow(
                id=uuid4(),
                telegram_user_id=kw.pop("telegram_user_id", TELEGRAM_USER_ID),
                kind=kw.pop("kind", CreditEntryKind.DEBIT),
                reason=kw.pop("reason", CreditReason.ORDER_RENDER),
                delta=kw.pop("delta", -1),
                order_id=kw.pop("order_id", UUID(int=7)),
                generation=kw.pop("generation", 0),
                idempotency_key=kw.pop("idempotency_key", f"debit:{uuid4()}:0"),
                actor=kw.pop("actor", "pipeline"),
                created_at=kw.pop("created_at", NOW),
            )
        )


# ---------------------------------------------------------------------------
# The ledger read
# ---------------------------------------------------------------------------
async def test_the_ledger_reports_the_account_and_its_movements(panel: Panel) -> None:
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await seed_account(panel)
    await seed_entry(panel, idempotency_key="debit:one:0")
    await signed_in(panel, role=AdminRole.VIEWER)

    # Act
    response = await panel.http.get(f"{CREDITS_URL}?withTotal=true")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["balance"] == 1
    assert body["account"]["lifetimeGranted"] == 4
    assert body["account"]["allowancePeriod"] == 3
    assert body["account"]["telegramUserIdMasked"].endswith("321")
    assert [entry["idempotencyKey"] for entry in body["items"]] == ["debit:one:0"]
    assert body["items"][0]["delta"] == -1
    assert body["items"][0]["actor"] == "pipeline"
    assert (body["meta"]["total"], body["meta"]["isTotalExact"]) == (1, True)


async def test_a_user_with_no_credit_account_reports_null_rather_than_a_zeroed_account(
    panel: Panel,
) -> None:
    """``null`` and ``{"balance": 0}`` are opposite claims about a refused customer.

    The account row is opened by the first charge or grant, so "no row" means never metered —
    and that customer is still owed a whole rolling allowance. A zeroed object would tell an
    operator they have spent everything.
    """
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)

    # Act
    response = await panel.http.get(CREDITS_URL)

    # Assert
    assert response.status_code == 200
    assert response.json()["account"] is None
    assert response.json()["items"] == []


async def test_an_id_this_database_has_never_seen_is_a_404_that_does_not_echo_it(
    panel: Panel,
) -> None:
    """Distinct from the empty ledger above: "never spent a credit" is not "never met".

    The body must not repeat the id — §12.3 keeps an unmasked Telegram id out of any payload
    the operator did not explicitly ask for, and an error body is a payload.
    """
    # Arrange
    await signed_in(panel)
    url = USER_CREDITS_PATH.format(telegram_user_id=UNSEEN_USER_ID)

    # Act
    response = await panel.http.get(url)

    # Assert
    assert response.status_code == 404
    assert str(UNSEEN_USER_ID) not in response.text


# ---------------------------------------------------------------------------
# The grant — the two halves of the split row
# ---------------------------------------------------------------------------
async def test_a_role_with_no_grant_cell_is_forbidden_rather_than_prompted(
    panel: Panel,
) -> None:
    # Arrange — SUPPORT may read the ledger and may not issue value.
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel, role=AdminRole.SUPPORT)

    # Act
    response = await post_grant(panel)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert await ledger_rows(panel.container) == []


async def test_an_eligible_role_without_a_grant_is_asked_to_re_authenticate(
    panel: Panel,
) -> None:
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)

    # Act
    response = await post_grant(panel)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert await ledger_rows(panel.container) == []


@pytest.mark.parametrize(
    ("subject", "scope"),
    [(UNSEEN_USER_ID, "credit.grant"), (TELEGRAM_USER_ID, "user.block")],
    ids=["another-subject", "another-action"],
)
async def test_a_grant_for_something_else_does_not_credit_this_account(
    panel: Panel, subject: int, scope: str
) -> None:
    """A step-up collected to bar an abuser must not also mint them spendable credit."""
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)
    assert (await step_up(panel, subject=subject, scope=scope)).status_code == 200

    # Act
    response = await post_grant(panel)

    # Assert
    assert response.status_code == 403
    assert await ledger_rows(panel.container) == []


# ---------------------------------------------------------------------------
# The grant itself
# ---------------------------------------------------------------------------
async def test_a_scoped_grant_moves_the_balance_the_ledger_and_the_audit_log(
    panel: Panel,
) -> None:
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await seed_account(panel, balance=1, lifetime=4)
    username = await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await post_grant(panel, credits=2, reasonRef="TICKET-7")

    # Assert — the response, the two representations, and the row that says who did it.
    assert response.status_code == 200
    body = response.json()
    assert body["isReplay"] is False
    assert body["grantedCredits"] == 2
    assert body["idempotencyKey"].startswith("grant:admin:")
    assert body["account"]["balance"] == 3
    assert body["account"]["lifetimeGranted"] == 6

    assert await stored_balance(panel.container, TELEGRAM_USER_ID) == 3
    rows = await ledger_rows(panel.container)
    assert len(rows) == 1
    assert (rows[0].kind, rows[0].reason, rows[0].delta) == (
        CreditEntryKind.GRANT,
        CreditReason.ADMIN_GRANT,
        2,
    )
    assert rows[0].actor == f"admin:{username}"
    assert rows[0].idempotency_key == body["idempotencyKey"]

    audited = await grant_audit_rows(panel.container)
    assert len(audited) == 1
    assert audited[0].subject_type == "user"
    assert audited[0].subject_id == str(TELEGRAM_USER_ID)
    assert audited[0].record_count == 2
    assert audited[0].reason_ref == "TICKET-7"
    assert audited[0].field_names == [
        "credit_accounts.balance",
        "credit_accounts.lifetime_granted",
    ]


async def test_the_same_request_id_tops_the_account_up_once(panel: Panel) -> None:
    """The unique index on ``idempotency_key`` is the concurrency primitive; this is its API.

    A retry after a timeout must not double-credit, and the caller must be able to tell "it
    worked the first time" from "it worked just now" without inferring it from a balance —
    which is what ``isReplay`` is for. The audit row is still written, because somebody asked
    under a fresh step-up and §12.6 records what operators did.
    """
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200
    request_id = str(uuid4())

    # Act
    first = await post_grant(panel, credits=2, requestId=request_id)
    second = await post_grant(panel, credits=2, requestId=request_id)

    # Assert
    assert first.json()["isReplay"] is False
    assert second.json()["isReplay"] is True
    assert first.json()["idempotencyKey"] == second.json()["idempotencyKey"]
    assert await stored_balance(panel.container, TELEGRAM_USER_ID) == 2
    assert len(await ledger_rows(panel.container)) == 1

    audited = await grant_audit_rows(panel.container)
    assert [row.record_count for row in audited] == [2, 0]


async def test_two_presses_without_a_request_id_are_two_grants(panel: Panel) -> None:
    """The honest reading of two presses, and why ``requestId`` is opt-in rather than default."""
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    first = await post_grant(panel, credits=1)
    second = await post_grant(panel, credits=1)

    # Assert
    assert first.json()["idempotencyKey"] != second.json()["idempotencyKey"]
    assert await stored_balance(panel.container, TELEGRAM_USER_ID) == 2
    assert len(await ledger_rows(panel.container)) == 2


async def test_granting_to_an_account_nobody_has_met_opens_it(panel: Panel) -> None:
    """No 404: ``grant`` calls ``open_account`` first, and the ledger keys on the Telegram id.

    A goodwill comp is usually for somebody who has never been metered — the ``credit_accounts``
    row is opened by the first movement — so refusing an id with no account would refuse the
    common case, and refusing one with no ``users`` row would make this an existence oracle.
    """
    # Arrange — nothing seeded at all.
    await signed_in(panel)
    assert (await step_up(panel, subject=UNSEEN_USER_ID)).status_code == 200
    url = USER_CREDITS_GRANT_PATH.format(telegram_user_id=UNSEEN_USER_ID)

    # Act
    response = await post_grant(panel, url, credits=3)

    # Assert
    assert response.status_code == 200
    assert response.json()["account"]["balance"] == 3
    assert await stored_balance(panel.container, UNSEEN_USER_ID) == 3


async def test_an_account_this_route_just_opened_can_be_read_back(panel: Panel) -> None:
    """The grant's own population must not 404 on the screen that displays what it wrote.

    ``grant`` calls ``open_account``, which writes ``credit_accounts`` and **no ``users``
    row** — so an existence check that asked ``users`` alone answered 404 for the ledger,
    the balance and the audit trail this API had just written, for exactly the customer the
    grant route documents as its intended case. The account row is itself proof that
    something is held under this id; ``/users/{id}`` still 404s, because that endpoint reads
    a table this account genuinely has no row in.
    """
    # Arrange — nothing seeded: no ``users`` row, no account.
    await signed_in(panel)
    assert (await step_up(panel, subject=UNSEEN_USER_ID)).status_code == 200
    granted = await post_grant(
        panel, USER_CREDITS_GRANT_PATH.format(telegram_user_id=UNSEEN_USER_ID), credits=3
    )
    assert granted.status_code == 200

    # Act
    response = await panel.http.get(USER_CREDITS_PATH.format(telegram_user_id=UNSEEN_USER_ID))

    # Assert
    assert response.status_code == 200
    assert response.json()["account"]["balance"] == 3
    assert [item["delta"] for item in response.json()["items"]] == [3]


async def test_one_request_id_credits_two_accounts_rather_than_skipping_the_second(
    panel: Panel,
) -> None:
    """``idempotency_key`` is unique GLOBALLY, so the key has to carry the account.

    Without the Telegram id in it, a ``requestId`` reused across two customers — a ticket
    id, a resubmitted form — credited the first and issued nothing to the second, while the
    response still said ``grantedCredits: 2`` and the audit row recorded an ``OK`` grant of
    ``record_count=0``. The only signal was an ``isReplay`` the operator has no reason to
    read as "wrong customer".
    """
    # Arrange — two accounts, two correctly scoped step-ups, one caller-supplied requestId.
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await seed_user(panel.container, telegram_user_id=OTHER_USER_ID, created_at=NOW)
    await signed_in(panel)
    request_id = str(uuid4())

    # Act
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200
    first = await post_grant(panel, credits=2, requestId=request_id)
    assert (await step_up(panel, subject=OTHER_USER_ID)).status_code == 200
    second = await post_grant(
        panel,
        USER_CREDITS_GRANT_PATH.format(telegram_user_id=OTHER_USER_ID),
        credits=2,
        requestId=request_id,
    )

    # Assert — both moved, and the two keys differ by the subject rather than by luck.
    assert first.json()["isReplay"] is False
    assert second.json()["isReplay"] is False
    assert first.json()["idempotencyKey"] != second.json()["idempotencyKey"]
    assert str(TELEGRAM_USER_ID) in first.json()["idempotencyKey"]
    assert await stored_balance(panel.container, TELEGRAM_USER_ID) == 2
    assert await stored_balance(panel.container, OTHER_USER_ID) == 2
    assert len(await ledger_rows(panel.container)) == 2
    assert [row.record_count for row in await grant_audit_rows(panel.container)] == [2, 2]


async def test_the_ledger_actor_keeps_its_prefix_when_the_username_is_long(
    panel: Panel,
) -> None:
    """``credit_ledger.actor`` is 32 characters and the prefix must survive the truncation.

    A long operator name that dropped ``admin:`` instead would leave a grant row
    indistinguishable from one the pipeline wrote — which is exactly the query an operator runs
    to answer "was this account comped?".
    """
    # Arrange
    long_name = "operator-with-a-very-long-name"
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel, username=long_name)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await post_grant(panel, credits=1)

    # Assert
    assert response.status_code == 200
    rows = await ledger_rows(panel.container)
    assert rows[0].actor == admin_actor(long_name)
    assert rows[0].actor is not None
    assert len(rows[0].actor) == ACTOR_LENGTH
    assert rows[0].actor.startswith("admin:")


@pytest.mark.parametrize(
    "body",
    [
        {"credits": 0},
        {"credits": -1},
        {"credits": MAX_GRANT_CREDITS + 1},
        {"reasonCode": None},
    ],
    ids=["zero", "negative", "over-the-cap", "no-reason"],
)
async def test_a_body_the_endpoint_cannot_honour_is_refused_before_anything_moves(
    panel: Panel, body: dict[str, Any]
) -> None:
    """The cap is a blast radius, not a validation nicety: a credit is real vendor spend.

    ``reasonCode`` has no default for §5.4's reason — a default would make the accountability
    optional and the modal value meaningless.
    """
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200
    payload: dict[str, Any] = {
        "credits": 1,
        "reasonCode": AuditReasonCode.CUSTOMER_REQUEST.value,
        **body,
    }
    if payload["reasonCode"] is None:
        del payload["reasonCode"]

    # Act
    response = await panel.http.post(GRANT_URL, json=payload, headers=csrf_headers(panel.http))

    # Assert
    assert response.status_code == 422
    assert await ledger_rows(panel.container) == []


async def test_a_telegram_id_in_the_body_is_refused_rather_than_believed(panel: Panel) -> None:
    """``extra="forbid"`` doing the job it exists for.

    A second copy of the subject in the body is a second answer to "who is being credited",
    and the shape that credits one account under another account's re-authentication.
    """
    # Arrange
    await seed_user(panel.container, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW)
    await signed_in(panel)
    assert (await step_up(panel, subject=TELEGRAM_USER_ID)).status_code == 200

    # Act
    response = await post_grant(panel, telegramUserId=UNSEEN_USER_ID)

    # Assert
    assert response.status_code == 422
    assert await ledger_rows(panel.container) == []
