"""``/api/broadcasts`` over the real ASGI stack — compose, authorise, and the two refusals.

This is the first surface in the panel whose actions leave the building, so the assertions
that carry the file are all about what must NOT happen.

**1. The send needs a real step-up, scoped to the campaign.** Not a mocked grant and not a
patched clock: every send test below drives ``POST /api/auth/step-up`` with the operator's
actual password, because the scope the SPA sends and the scope the handler demands are two
strings compared whole, and a mock proves that a mock matches itself. The negative cases are
driven the same way — a grant taken for *another campaign*, and one taken for ``user.block``,
must not authorise this send — since a confused-deputy step-up is exactly the failure a
subject-scoped grant exists to prevent.

**2. A test send reaches only an allowlisted id.** ``admin_broadcast_test_recipients`` ships
empty, so the route is off by default and its refusal is asserted with the allowlist empty,
with a *different* id on it, and with the right id on it — three cases, because "the check
exists" and "the check compares the right thing" are different claims. Nothing is enqueued and
no audit row is written on a refusal.

**3. No raw Telegram id is on the recipient wire, at any role.** Asserted against
``response.text`` rather than against the field list: "the model has no such field" is a
weaker claim than "the digits are not in the bytes", and it is the claim that survives
somebody adding a field to a projection later.

**4. Persist, then enqueue.** The queue is a recording
:class:`~bayram.admin.queue.NullAdminQueue`, so every route that hands work to the worker is
asserted on the job NAME, the campaign id and the frozen instant it passed — a counter could
not tell a right id from a wrong one. A refusing queue is a 503 and not a 500.

The audience is frozen at creation, so ``expectedAudienceSize`` is checked on ``POST
/api/broadcasts`` and nowhere else; the drift tests live beside the create and not beside the
send.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.queue import (
    EXPAND_JOB_NAME,
    SEND_JOB_NAME,
    TEST_SEND_JOB_NAME,
    NullAdminQueue,
)
from bayram.admin.routers.broadcasts import (
    BROADCAST_CANCEL_PATH,
    BROADCAST_PATH,
    BROADCAST_PAUSE_PATH,
    BROADCAST_RECIPIENTS_PATH,
    BROADCAST_RESUME_PATH,
    BROADCAST_REVISE_PATH,
    BROADCAST_SEND_PATH,
    BROADCAST_STATS_PATH,
    BROADCAST_SUBJECT_TYPE,
    BROADCAST_TEST_SEND_PATH,
    BROADCASTS_PATH,
)
from bayram.admin.security.permissions import StepUpAction
from bayram.contracts import (
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
)
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.db.models.broadcast import BroadcastRow
from bayram.db.models.broadcast_body import BroadcastBodyRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow
from bayram.db.models.user import UserRow
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

#: Every role in the matrix, so a widened or narrowed cell fails here rather than in review.
EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

#: The two roles §12.2 gives ``BROADCAST_WRITE``, and the two it does not.
WRITE_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.ADMIN, AdminRole.OWNER)
READ_ONLY_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.VIEWER, AdminRole.SUPPORT)

#: Distinctive enough that a substring hit in a response body is a leak and not a coincidence.
RECIPIENT_ID: Final[int] = 987_654_321
#: The operator's own account — the only id the test-send allowlist below carries.
TEST_RECIPIENT_ID: Final[int] = 111_222_333
#: On no allowlist in this file, so "the check compares the right thing" has a witness.
STRANGER_ID: Final[int] = 444_555_666

CAMPAIGN_ID: Final[UUID] = UUID("aaaaaaaa-0000-4000-8000-000000000001")
OTHER_CAMPAIGN_ID: Final[UUID] = UUID("aaaaaaaa-0000-4000-8000-000000000002")
UNKNOWN_ID: Final[UUID] = UUID("bbbbbbbb-0000-4000-8000-00000000ffff")


#: A future instant for the scheduled-send path, and it must be future against the REAL
#: clock: ``conftest.NOW`` is a fixed instant for TTLs and windows, but the handler refuses a
#: past ``scheduledFor`` against ``utc_now()``, so a literal here would start failing the day
#: it went by.
def later() -> datetime:
    """A week out, resolved when the request is built. Well clear of any test's runtime."""
    return (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)


#: The smallest legal segment document: everybody.
EVERYONE: Final[dict[str, Any]] = {"v": 1, "match": "all", "rules": []}

DETAIL_URL: Final[str] = BROADCAST_PATH.format(broadcast_id=CAMPAIGN_ID)
RECIPIENTS_URL: Final[str] = BROADCAST_RECIPIENTS_PATH.format(broadcast_id=CAMPAIGN_ID)
SEND_URL: Final[str] = BROADCAST_SEND_PATH.format(broadcast_id=CAMPAIGN_ID)
REVISE_URL: Final[str] = BROADCAST_REVISE_PATH.format(broadcast_id=CAMPAIGN_ID)
PAUSE_URL: Final[str] = BROADCAST_PAUSE_PATH.format(broadcast_id=CAMPAIGN_ID)
RESUME_URL: Final[str] = BROADCAST_RESUME_PATH.format(broadcast_id=CAMPAIGN_ID)
CANCEL_URL: Final[str] = BROADCAST_CANCEL_PATH.format(broadcast_id=CAMPAIGN_ID)
TEST_SEND_URL: Final[str] = BROADCAST_TEST_SEND_PATH.format(broadcast_id=CAMPAIGN_ID)


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient
    queue: NullAdminQueue


@asynccontextmanager
async def open_panel(*, refusing: bool = False, **settings: Any) -> AsyncIterator[Panel]:
    """One panel, with the container's settings and its queue chosen by the caller.

    A context manager rather than a fixture per variant: three tests need a differently
    configured panel (an empty allowlist, a wider drift tolerance, no worker at all) and
    parametrising the fixture would put those three configurations in front of every test in
    the file.
    """
    queue = NullAdminQueue(refusing=refusing)
    async with (
        open_container(
            make_settings(**settings), FakeRedis(), MemoryRateLimits(), queue
        ) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http, queue=queue)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    """The default panel: the test-send allowlist carries exactly one id."""
    async with open_panel(admin_broadcast_test_recipients=(TEST_RECIPIENT_ID,)) as opened:
        yield opened


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.ADMIN) -> str:
    """Sign in as ``role``. ADMIN by default, because that is where every write cell starts —
    a file that only ever used OWNER would not notice the cell narrowing."""
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    assert (await sign_in(panel.http, username=username, password=PASSWORD)).status_code == 200
    return username


async def step_up(
    panel: Panel,
    *,
    subject: UUID = CAMPAIGN_ID,
    scope: str = StepUpAction.BROADCAST_SEND.value,
) -> httpx.Response:
    """The REAL re-authentication route, with the operator's real password."""
    return await panel.http.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": str(subject)},
        headers=csrf_headers(panel.http),
    )


# ---------------------------------------------------------------------------
# Seeding, through the real models
# ---------------------------------------------------------------------------
async def seed_users(panel: Panel, *count_ids: int) -> None:
    """Accounts for a segment to select. Every clock stated; nothing defaulted."""
    async with panel.container.session_factory.begin() as db:
        for telegram_user_id in count_ids:
            db.add(
                UserRow(
                    id=uuid4(),
                    telegram_user_id=telegram_user_id,
                    ui_language=Language.RU,
                    is_blocked=False,
                    last_seen_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


async def seed_campaign(panel: Panel, **overrides: Any) -> BroadcastRow:
    """One campaign row, with every column the model does not default in Python set.

    Seeded directly rather than composed through ``POST /api/broadcasts``, because the states
    the lifecycle routes act on — ``READY``, ``SENDING``, ``PAUSED`` — are reached by the
    WORKER, and a test that had to run an expansion to reach them would be testing the worker.
    """
    values: dict[str, Any] = {
        "id": CAMPAIGN_ID,
        "title": "September outage notice",
        "kind": BroadcastKind.SERVICE,
        "state": BroadcastState.READY,
        "segment": EVERYONE,
        "segment_hash": "a" * 64,
        "audience_size": 3,
        "audience_evaluated_at": NOW,
        "expand_cursor": None,
        "scheduled_for": None,
        "started_at": None,
        "finished_at": None,
        "recipient_count": 3,
        "sent_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "undeliverable_count": 0,
        "unknown_count": 0,
        "created_by_admin_id": None,
        "created_by_username": "someone-else",
        "scheduled_by_admin_id": None,
        "scheduled_by_username": None,
        "reason_code": None,
        "reason_ref": None,
        "error_code": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    row = BroadcastRow(**values)
    async with panel.container.session_factory.begin() as db:
        db.add(row)
        db.add(
            BroadcastBodyRow(
                id=uuid4(),
                broadcast_id=values["id"],
                language=Language.RU,
                text="Salom, <b>do'stlar</b>!",
                media_storage_key=None,
                media_file_id=None,
                button_label=None,
                button_url=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await db.flush()
    return row


async def seed_recipient(panel: Panel, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "id": uuid4(),
        "broadcast_id": CAMPAIGN_ID,
        "telegram_user_id": RECIPIENT_ID,
        "language": Language.RU,
        "state": BroadcastRecipientState.SENT,
        "attempts": 1,
        "error_code": None,
        "settled_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    async with panel.container.session_factory.begin() as db:
        db.add(BroadcastRecipientRow(**values))


# ---------------------------------------------------------------------------
# Reading the database back
# ---------------------------------------------------------------------------
async def stored_campaigns(panel: Panel) -> list[BroadcastRow]:
    async with panel.container.session_factory.begin() as db:
        statement = sa.select(BroadcastRow).order_by(BroadcastRow.created_at)
        return list((await db.execute(statement)).scalars().all())


async def stored_bodies(panel: Panel, broadcast_id: UUID) -> list[BroadcastBodyRow]:
    async with panel.container.session_factory.begin() as db:
        statement = sa.select(BroadcastBodyRow).where(BroadcastBodyRow.broadcast_id == broadcast_id)
        return list((await db.execute(statement)).scalars().all())


async def audit_rows(panel: Panel, *actions: AuditAction) -> list[AdminAuditRow]:
    async with panel.container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action.in_(actions))
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------
def create_body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "September outage notice",
        "kind": BroadcastKind.SERVICE.value,
        "segment": EVERYONE,
        "bodies": [{"language": Language.RU.value, "text": "Salom, <b>do'stlar</b>!"}],
    }
    payload.update(overrides)
    return payload


async def post(panel: Panel, url: str, body: dict[str, Any]) -> httpx.Response:
    """Every mutation goes out with the headers a signed-in SPA sends. There is no other way
    to reach one of these handlers, and a test that skipped them would test the CSRF layer."""
    return await panel.http.post(url, json=body, headers=csrf_headers(panel.http))


def reason(code: AuditReasonCode = AuditReasonCode.ROUTINE_OPS, **extra: Any) -> dict[str, Any]:
    return {"reasonCode": code.value, **extra}


# ---------------------------------------------------------------------------
# Who may read, and who may write
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_in_the_matrix_row_may_read_the_campaign_list(
    panel: Panel, role: AdminRole
) -> None:
    # Arrange — BROADCAST_READ is M in all four cells: a campaign record is operator copy,
    # closed enums and counters, and holds no customer data at all.
    await seed_campaign(panel)
    await signed_in(panel, role=role)

    # Act
    response = await panel.http.get(f"{BROADCASTS_PATH}?withTotal=true")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["September outage notice"]
    assert (body["meta"]["total"], body["meta"]["isTotalExact"]) == (1, True)


@pytest.mark.parametrize("role", READ_ONLY_ROLES)
async def test_a_role_with_no_write_cell_is_forbidden_rather_than_prompted(
    panel: Panel, role: AdminRole
) -> None:
    """VIEWER and SUPPORT may read every campaign and compose none.

    403 ``FORBIDDEN`` and never ``STEP_UP_REQUIRED``: re-authenticating would not help, and
    telling somebody to try again is worse than telling them no.
    """
    # Arrange
    await signed_in(panel, role=role)

    # Act
    response = await post(panel, BROADCASTS_PATH, create_body())

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert await stored_campaigns(panel) == []


# ---------------------------------------------------------------------------
# Compose — the call that freezes the audience
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", WRITE_ROLES)
async def test_composing_a_campaign_freezes_the_audience_and_enqueues_the_expansion(
    panel: Panel, role: AdminRole
) -> None:
    # Arrange — three accounts, so the exact count is a number and not a coincidence of zero.
    await seed_users(panel, RECIPIENT_ID, TEST_RECIPIENT_ID, STRANGER_ID)
    username = await signed_in(panel, role=role)

    # Act — no step-up: composing messages nobody.
    response = await post(panel, BROADCASTS_PATH, create_body(expectedAudienceSize=3))

    # Assert — the response, the row, the body, the audit entry and the job.
    assert response.status_code == 200
    body = response.json()
    assert body["broadcast"]["state"] == BroadcastState.EXPANDING.value
    assert body["broadcast"]["progress"]["audienceSize"] == 3
    assert body["broadcast"]["progress"]["recipientCount"] == 0
    assert body["broadcast"]["progress"]["isAudienceComplete"] is False
    assert body["broadcast"]["createdByUsername"] == username
    assert body["isSegmentReadable"] is True
    assert body["bodies"][0]["renderedText"] == "Salom, <b>do'stlar</b>!"

    [campaign] = await stored_campaigns(panel)
    assert campaign.audience_size == 3
    assert campaign.audience_evaluated_at is not None
    assert campaign.state is BroadcastState.EXPANDING
    assert len(campaign.segment_hash) == 64
    assert [row.language for row in await stored_bodies(panel, campaign.id)] == [Language.RU]

    [entry] = await audit_rows(panel, AuditAction.BROADCAST_CREATE)
    assert entry.subject_type == BROADCAST_SUBJECT_TYPE
    assert entry.subject_id == str(campaign.id)
    assert entry.record_count == 3

    # Persist, then enqueue: the job is asked for by id and by the instant the audience was
    # frozen at, so every chunk compiles the segment against the same clock.
    [call] = panel.queue.calls
    assert call.job == EXPAND_JOB_NAME
    assert call.broadcast_id == campaign.id
    assert call.arguments[1] == campaign.audience_evaluated_at.isoformat()


async def test_an_audience_that_moved_since_the_preview_is_a_409_that_writes_nothing(
    panel: Panel,
) -> None:
    """The wizard rendered a count; between that render and this call the world moved.

    Refused rather than materialised, because the operator approved a number and this would
    have frozen a different one. Both numbers are in the body: "it moved" alone gives nobody a
    way to decide between re-previewing and insisting.
    """
    # Arrange — three accounts against an expectation of thirty.
    await seed_users(panel, RECIPIENT_ID, TEST_RECIPIENT_ID, STRANGER_ID)
    await signed_in(panel)

    # Act
    response = await post(panel, BROADCASTS_PATH, create_body(expectedAudienceSize=30))

    # Assert
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == AdminErrorCode.CONFLICT.value
    assert error["details"] == {"expectedAudienceSize": 30, "audienceSize": 3}
    assert await stored_campaigns(panel) == []
    assert panel.queue.calls == []


async def test_drift_inside_the_tolerance_is_composed_rather_than_refused(
    panel: Panel,
) -> None:
    """A tolerance of zero would refuse a correct request on any live database, and the first
    thing an operator would learn is to stop sending the expected size at all."""
    # Arrange — 100 expected against 98 real, inside the shipped 5%.
    async with open_panel(admin_broadcast_audience_drift_tolerance=0.5) as tolerant:
        await seed_users(tolerant, RECIPIENT_ID, TEST_RECIPIENT_ID)
        await signed_in(tolerant)

        # Act
        response = await post(tolerant, BROADCASTS_PATH, create_body(expectedAudienceSize=3))

        # Assert
        assert response.status_code == 200
        assert (await stored_campaigns(tolerant))[0].audience_size == 2


async def test_a_create_with_no_worker_is_a_503_rather_than_a_500(panel: Panel) -> None:
    """A missing worker is an unavailable dependency, and the SPA can retry a 503."""
    # Arrange
    async with open_panel(refusing=True) as unstaffed:
        await seed_users(unstaffed, RECIPIENT_ID)
        await signed_in(unstaffed)

        # Act
        response = await post(unstaffed, BROADCASTS_PATH, create_body())

        # Assert
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------
async def test_revising_a_campaign_replaces_the_whole_body_set(panel: Panel) -> None:
    """A whole replacement, not a patch: "leave the Russian body alone" and "delete it" are
    the same JSON document once the fields are optional."""
    # Arrange
    await seed_campaign(panel, state=BroadcastState.EXPANDING)
    await signed_in(panel)

    # Act
    response = await post(
        panel,
        REVISE_URL,
        {
            "title": "September outage notice, corrected",
            "bodies": [{"language": Language.UZ_LATN.value, "text": "Kechirasiz!"}],
        },
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["broadcast"]["title"] == "September outage notice, corrected"
    assert [row.language for row in await stored_bodies(panel, CAMPAIGN_ID)] == [Language.UZ_LATN]
    assert len(await audit_rows(panel, AuditAction.BROADCAST_REVISE)) == 1


async def test_a_campaign_already_sending_cannot_be_revised(panel: Panel) -> None:
    """The refusal is the conditional ``UPDATE``'s, not a check here: the send job runs in
    another process and the gap between a SELECT and an UPDATE is one message wide."""
    # Arrange
    await seed_campaign(panel, state=BroadcastState.SENDING, started_at=NOW)
    await signed_in(panel)

    # Act
    response = await post(
        panel,
        REVISE_URL,
        {"title": "too late", "bodies": [{"language": Language.RU.value, "text": "Kech"}]},
    )

    # Assert
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == AdminErrorCode.CONFLICT.value
    assert error["details"]["state"] == BroadcastState.SENDING.value
    assert (await stored_bodies(panel, CAMPAIGN_ID))[0].text.startswith("Salom")


async def test_an_unknown_campaign_is_a_404_that_does_not_echo_the_id(panel: Panel) -> None:
    # Arrange
    await signed_in(panel)

    # Act
    response = await panel.http.get(BROADCAST_PATH.format(broadcast_id=UNKNOWN_ID))

    # Assert
    assert response.status_code == 404
    assert str(UNKNOWN_ID) not in response.text


# ---------------------------------------------------------------------------
# The send — the destructive action
# ---------------------------------------------------------------------------
async def test_a_send_without_a_step_up_is_refused_and_enqueues_nothing(panel: Panel) -> None:
    # Arrange — an ADMIN who holds the role half of the cell and no grant.
    await seed_campaign(panel)
    await signed_in(panel)

    # Act
    response = await post(panel, SEND_URL, reason())

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert (await stored_campaigns(panel))[0].scheduled_by_admin_id is None
    assert panel.queue.calls == []


@pytest.mark.parametrize(
    ("subject", "scope"),
    [
        (OTHER_CAMPAIGN_ID, StepUpAction.BROADCAST_SEND.value),
        (CAMPAIGN_ID, StepUpAction.USER_BLOCK.value),
    ],
    ids=["another-campaign", "another-action"],
)
async def test_a_grant_for_something_else_does_not_authorise_this_send(
    panel: Panel, subject: UUID, scope: str
) -> None:
    """A step-up collected to bar one abuser must not also message the whole database."""
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=subject, scope=scope)).status_code == 200

    # Act
    response = await post(panel, SEND_URL, reason())

    # Assert
    assert response.status_code == 403
    assert (await stored_campaigns(panel))[0].scheduled_by_admin_id is None
    assert panel.queue.calls == []


async def test_a_scoped_send_authorises_the_campaign_audits_it_and_starts_the_worker(
    panel: Panel,
) -> None:
    # Arrange
    await seed_campaign(panel)
    username = await signed_in(panel)
    assert (await step_up(panel)).status_code == 200

    # Act
    response = await post(
        panel, SEND_URL, reason(AuditReasonCode.INCIDENT, reasonRef="OPS-14", reasonText="outage")
    )

    # Assert — the response, the row, the audit entry, and the job.
    assert response.status_code == 200
    body = response.json()["broadcast"]
    assert body["scheduledByUsername"] == username
    assert body["scheduledFor"] is None
    assert body["reasonCode"] == AuditReasonCode.INCIDENT.value

    [campaign] = await stored_campaigns(panel)
    assert campaign.scheduled_by_username == username
    assert campaign.reason_ref == "OPS-14"

    [entry] = await audit_rows(panel, AuditAction.BROADCAST_SCHEDULE)
    # ``recordCount`` is how many people this authorises a message to — the column that tells
    # a forty-recipient test from a forty-thousand-recipient send by a query.
    assert entry.record_count == campaign.audience_size
    assert entry.subject_id == str(CAMPAIGN_ID)
    assert entry.reason_text == "outage"

    [call] = panel.queue.calls
    assert (call.job, call.broadcast_id) == (SEND_JOB_NAME, CAMPAIGN_ID)


async def test_a_scheduled_send_records_the_instant_and_leaves_the_worker_alone(
    panel: Panel,
) -> None:
    """A campaign that must not start for days is the due sweep's, not a job enqueued now."""
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)
    assert (await step_up(panel)).status_code == 200
    instant = later()

    # Act
    response = await post(panel, SEND_URL, reason(scheduledFor=instant.isoformat()))

    # Assert
    assert response.status_code == 200
    assert (await stored_campaigns(panel))[0].scheduled_for == instant
    assert panel.queue.calls == []


async def test_an_instant_that_has_already_passed_is_refused(panel: Panel) -> None:
    """No schema in this package reads a clock, so "already happened" is the handler's own
    refusal, made against the same instant it would have stamped the row with."""
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)
    assert (await step_up(panel)).status_code == 200
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    # Act
    response = await post(panel, SEND_URL, reason(scheduledFor=past))

    # Assert
    assert response.status_code == 422
    assert (await stored_campaigns(panel))[0].scheduled_by_admin_id is None
    assert panel.queue.calls == []


async def test_a_campaign_whose_audience_is_still_expanding_cannot_be_sent(
    panel: Panel,
) -> None:
    """Authorising a half-written ledger is the distinction EXPANDING and READY exist to keep."""
    # Arrange
    await seed_campaign(panel, state=BroadcastState.EXPANDING, recipient_count=1)
    await signed_in(panel)
    assert (await step_up(panel)).status_code == 200

    # Act
    response = await post(panel, SEND_URL, reason())

    # Assert
    assert response.status_code == 409
    assert response.json()["error"]["details"]["state"] == BroadcastState.EXPANDING.value
    assert await audit_rows(panel, AuditAction.BROADCAST_SCHEDULE) == []
    assert panel.queue.calls == []


# ---------------------------------------------------------------------------
# Pause, resume, cancel
# ---------------------------------------------------------------------------
async def test_pausing_a_running_campaign_needs_no_step_up(panel: Panel) -> None:
    """The brake is the one action here that makes FEWER messages leave. A re-authentication
    in front of it would cost seconds at the moment somebody most needs them."""
    # Arrange
    await seed_campaign(panel, state=BroadcastState.SENDING, started_at=NOW)
    await signed_in(panel)

    # Act
    response = await post(panel, PAUSE_URL, reason(AuditReasonCode.INCIDENT))

    # Assert
    assert response.status_code == 200
    assert response.json()["broadcast"]["state"] == BroadcastState.PAUSED.value
    assert (await stored_campaigns(panel))[0].state is BroadcastState.PAUSED
    assert len(await audit_rows(panel, AuditAction.BROADCAST_PAUSE)) == 1


async def test_resuming_a_paused_campaign_re_enqueues_the_send_job(panel: Panel) -> None:
    # Arrange
    await seed_campaign(panel, state=BroadcastState.PAUSED, started_at=NOW)
    await signed_in(panel)

    # Act
    response = await post(panel, RESUME_URL, reason(AuditReasonCode.INCIDENT))

    # Assert
    assert response.status_code == 200
    assert (await stored_campaigns(panel))[0].state is BroadcastState.SENDING
    [call] = panel.queue.calls
    assert (call.job, call.broadcast_id) == (SEND_JOB_NAME, CAMPAIGN_ID)


async def test_cancelling_keeps_the_counters_of_what_already_went(panel: Panel) -> None:
    """A campaign cancelled halfway is a cancelled campaign with messages already delivered."""
    # Arrange
    await seed_campaign(panel, state=BroadcastState.SENDING, started_at=NOW, sent_count=2)
    await signed_in(panel)

    # Act
    response = await post(panel, CANCEL_URL, reason(AuditReasonCode.INCIDENT))

    # Assert
    assert response.status_code == 200
    body = response.json()["broadcast"]
    assert body["state"] == BroadcastState.CANCELLED.value
    assert body["isTerminal"] is True
    assert body["progress"]["sentCount"] == 2
    assert len(await audit_rows(panel, AuditAction.BROADCAST_CANCEL)) == 1


async def test_a_terminal_campaign_cannot_be_paused(panel: Panel) -> None:
    # Arrange
    await seed_campaign(panel, state=BroadcastState.COMPLETED, finished_at=NOW)
    await signed_in(panel)

    # Act
    response = await post(panel, PAUSE_URL, reason(AuditReasonCode.INCIDENT))

    # Assert
    assert response.status_code == 409
    assert await audit_rows(panel, AuditAction.BROADCAST_PAUSE) == []


# ---------------------------------------------------------------------------
# The test send — the allowlist
# ---------------------------------------------------------------------------
async def test_a_test_send_to_an_id_outside_the_allowlist_is_refused(panel: Panel) -> None:
    """Without the allowlist this route is "message any customer id you can type". The
    step-up proves who asked and the audit row records that they did; neither bounds who
    receives it."""
    # Arrange — a live, correctly scoped grant. The refusal below is the allowlist's alone.
    await seed_campaign(panel)
    await signed_in(panel)
    assert (await step_up(panel)).status_code == 200

    # Act
    response = await post(panel, TEST_SEND_URL, reason(telegramUserId=STRANGER_ID))

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert str(STRANGER_ID) not in response.text
    assert await audit_rows(panel, AuditAction.BROADCAST_TEST) == []
    assert panel.queue.calls == []


async def test_an_empty_allowlist_turns_the_test_send_off_entirely(panel: Panel) -> None:
    """The shipped default. A deployment that has not named its operators sends no tests."""
    # Arrange
    async with open_panel() as unlisted:
        await seed_campaign(unlisted)
        await signed_in(unlisted)
        assert (await step_up(unlisted)).status_code == 200

        # Act
        response = await post(unlisted, TEST_SEND_URL, reason(telegramUserId=TEST_RECIPIENT_ID))

        # Assert
        assert response.status_code == 403
        assert unlisted.queue.calls == []


async def test_a_test_send_to_an_allowlisted_id_enqueues_it_and_masks_the_recipient(
    panel: Panel,
) -> None:
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)
    assert (await step_up(panel)).status_code == 200

    # Act
    response = await post(panel, TEST_SEND_URL, reason(telegramUserId=TEST_RECIPIENT_ID))

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["telegramUserIdMasked"].endswith("333")
    # The caller sent the id; this API still does not read it back to them, for the reason
    # every other projection here withholds one.
    assert str(TEST_RECIPIENT_ID) not in response.text

    [entry] = await audit_rows(panel, AuditAction.BROADCAST_TEST)
    assert entry.record_count == 1
    assert entry.subject_id == str(CAMPAIGN_ID)

    [call] = panel.queue.calls
    assert (call.job, call.broadcast_id) == (TEST_SEND_JOB_NAME, CAMPAIGN_ID)
    assert call.arguments[1] == TEST_RECIPIENT_ID


async def test_a_test_send_without_a_step_up_is_refused_before_the_allowlist(
    panel: Panel,
) -> None:
    """An unauthenticated-for-this probe learns nothing about which ids are allowlisted."""
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)

    # Act
    response = await post(panel, TEST_SEND_URL, reason(telegramUserId=TEST_RECIPIENT_ID))

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert panel.queue.calls == []


# ---------------------------------------------------------------------------
# The recipient ledger — the one list that pages through people
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_no_raw_telegram_id_reaches_the_recipient_wire_at_any_role(
    panel: Panel, role: AdminRole
) -> None:
    """Asserted against the BYTES, not the field list.

    ``/users`` publishes the id beside its mask because every ``/users/**`` route keys on it;
    nothing here does — a recipient row is addressed by its own UUID — and this is the one
    list in the API that pages through a membership decision made about people. So the digits
    must not be in the response at all, at any role, and a field somebody adds to the
    projection later fails here rather than in a review.
    """
    # Arrange
    await seed_campaign(panel)
    await seed_recipient(panel)
    await signed_in(panel, role=role)

    # Act
    response = await panel.http.get(f"{RECIPIENTS_URL}?withTotal=true")

    # Assert
    assert response.status_code == 200
    assert str(RECIPIENT_ID) not in response.text
    # The quotes matter: ``telegramUserId`` is a prefix of the masked field's own name.
    assert '"telegramUserId"' not in response.text
    [item] = response.json()["items"]
    assert item["telegramUserIdMasked"].endswith("321")
    assert item["isErased"] is False


async def test_an_erased_recipient_is_listed_rather_than_filtered(panel: Panel) -> None:
    """``/forget`` nulls the column; the row is the evidence a message went to an account this
    database no longer holds, and dropping it would make the funnel stop adding up."""
    # Arrange
    await seed_campaign(panel)
    await seed_recipient(panel, telegram_user_id=None)
    await signed_in(panel)

    # Act
    response = await panel.http.get(RECIPIENTS_URL)

    # Assert
    [item] = response.json()["items"]
    assert item["isErased"] is True
    assert item["telegramUserIdMasked"] is None


async def test_the_ledger_filters_by_state_within_one_campaign(panel: Panel) -> None:
    # Arrange — "show me the failures" is the filter an operator actually reaches for.
    await seed_campaign(panel)
    await seed_recipient(panel)
    await seed_recipient(
        panel,
        telegram_user_id=STRANGER_ID,
        state=BroadcastRecipientState.FAILED,
        error_code="flood_wait",
    )
    await signed_in(panel)

    # Act
    response = await panel.http.get(
        f"{RECIPIENTS_URL}?state={BroadcastRecipientState.FAILED.value}"
    )

    # Assert
    [item] = response.json()["items"]
    assert item["state"] == BroadcastRecipientState.FAILED.value
    assert item["errorCode"] == "flood_wait"


async def test_the_detail_reports_the_ledger_s_count_beside_the_row_s_rollup(
    panel: Panel,
) -> None:
    """Seeded to DISAGREE on purpose: the rows are truth and the rollup is what the worker
    last wrote, and a send being watched live is exactly when the two differ."""
    # Arrange — the campaign claims three recipients; one row exists.
    await seed_campaign(panel, recipient_count=3, sent_count=3)
    await seed_recipient(panel)
    await signed_in(panel)

    # Act
    response = await panel.http.get(DETAIL_URL)

    # Assert
    body = response.json()
    assert body["broadcast"]["progress"]["recipientCount"] == 3
    assert body["countedProgress"]["recipientCount"] == 1
    assert body["countedProgress"]["sentCount"] == 1


# ---------------------------------------------------------------------------
# The strip — an aggregate over the same filter set, on the same cell
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE)
async def test_every_role_that_may_read_the_list_may_read_the_strip(
    panel: Panel, role: AdminRole
) -> None:
    """Same cell as the list, and strictly less on the wire than the list carries.

    BROADCAST_READ is ``M`` at all four roles, and the guard is the router's — there is no
    handler-level check to get wrong. The bytes are asserted as well as the status because an
    aggregate surface in this panel carries counts, closed enum members and UTC instants and
    nothing else (§12.3): the campaign TITLE is on the list beside it and must not be here,
    and neither must any recipient's id.
    """
    # Arrange
    await seed_campaign(panel, state=BroadcastState.COMPLETED, started_at=NOW, sent_count=3)
    await seed_recipient(panel)
    await signed_in(panel, role=role)

    # Act
    response = await panel.http.get(BROADCAST_STATS_PATH)

    # Assert
    assert response.status_code == 200
    assert "September outage notice" not in response.text
    assert str(RECIPIENT_ID) not in response.text
    body = response.json()
    assert body["total"] == 1
    assert body["lastSendAt"] is not None


async def test_the_strip_does_not_resolve_to_the_campaign_by_id_route(panel: Panel) -> None:
    """``/broadcasts/stats`` is a literal segment where ``{broadcast_id}`` also matches.

    Registration order is what keeps them apart: FastAPI matches in declaration order, so a
    ``BROADCAST_STATS_PATH`` registered after ``BROADCAST_PATH`` would be swallowed by the
    parameterised route and answered with a 422 about a malformed UUID — an operator's strip
    replaced by a validation error about a path they never typed. Asserted on the SHAPE of
    the response as well as its status, because a 200 from the wrong route is the failure
    this route order exists to prevent.
    """
    # Arrange
    await seed_campaign(panel)
    await signed_in(panel)

    # Act
    response = await panel.http.get(BROADCAST_STATS_PATH)

    # Assert — the strip, and not the detail view the by-id route returns.
    assert response.status_code == 200
    body = response.json()
    assert "counts" in body
    assert "broadcast" not in body
    assert "bodies" not in body


async def test_an_empty_deployment_is_zeroes_and_a_null_last_send_rather_than_an_error(
    panel: Panel,
) -> None:
    """No campaigns at all is a state, not a 404 — and the last send is ABSENT, never an epoch.

    The counts zero-fill over the closed ``BroadcastState`` vocabulary, so the strip has the
    same tiles on a fresh deployment as on a busy one. ``lastSendAt`` is the one figure here
    that can be unmeasured, and it crosses as ``null``: a substituted instant would render as
    a send nobody made, and ``audienceTotal == 0`` is what tells the panel to draw a dash for
    the reach rather than "0%" — a rate with no denominator is not a number.
    """
    # Arrange — a signed-in operator and an entirely empty database.
    await signed_in(panel)

    # Act
    response = await panel.http.get(BROADCAST_STATS_PATH)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert [item["state"] for item in body["counts"]] == [state.value for state in BroadcastState]
    assert {item["count"] for item in body["counts"]} == {0}
    assert (body["total"], body["reachedRecipients"], body["audienceTotal"]) == (0, 0, 0)
    assert body["lastSendAt"] is None


async def test_the_strip_answers_for_the_query_string_the_list_was_given(panel: Panel) -> None:
    """Filtering to one state makes every other tile ``0``, which is the honest answer.

    The strip takes the list's filter dependency verbatim, so the two can never describe two
    populations. A server that dropped a filter to produce a fuller-looking strip would be
    describing a set the operator is not looking at.
    """
    # Arrange — one finished campaign that reached forty people, one draft that reached none.
    await seed_campaign(
        panel,
        state=BroadcastState.COMPLETED,
        started_at=NOW,
        audience_size=40,
        recipient_count=40,
        sent_count=38,
        failed_count=2,
    )
    await seed_campaign(
        panel,
        id=OTHER_CAMPAIGN_ID,
        title="Unsent draft",
        state=BroadcastState.DRAFT,
        audience_size=7,
        recipient_count=0,
    )
    await signed_in(panel)

    # Act
    everything = await panel.http.get(BROADCAST_STATS_PATH)
    drafts = await panel.http.get(f"{BROADCAST_STATS_PATH}?state={BroadcastState.DRAFT.value}")

    # Assert — unfiltered, both campaigns and both audiences.
    whole = everything.json()
    assert whole["total"] == 2
    assert (whole["reachedRecipients"], whole["audienceTotal"]) == (40, 47)

    # Narrowed to drafts: one campaign, nothing reached, and NO send — the draft has never
    # started, so the instant is absent rather than inherited from the campaign beside it.
    narrowed = drafts.json()
    assert narrowed["total"] == 1
    assert (narrowed["reachedRecipients"], narrowed["audienceTotal"]) == (0, 7)
    assert narrowed["lastSendAt"] is None
    counted = {item["state"]: item["count"] for item in narrowed["counts"]}
    assert counted[BroadcastState.DRAFT.value] == 1
    assert counted[BroadcastState.COMPLETED.value] == 0
