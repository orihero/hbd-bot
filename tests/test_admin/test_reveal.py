"""``POST /api/reveal`` over the real ASGI stack — the real login, the real ``/auth/step-up``.

Four assertions carry this file and everything else exists to keep them honest.

**1. The audit row is written before the read, and the only test that proves it makes the
read fail.** ``audit_sink.record`` appends into the *request's* transaction, which
``deps.get_db_session`` rolls back on any exception — so an implementation that wrote its
row "before" the read and then errored would lose it, and a test shaped "reveal, then assert
the row exists" would pass under that implementation and under a correct one alike.
:func:`test_the_audit_row_survives_a_read_that_fails_after_it` breaks the read *after* the
audit call and requires the row to still be there. Its converse,
:func:`test_a_reveal_whose_audit_row_cannot_be_written_returns_no_plaintext`, is the other
half of §9.1: an unaudited reveal must not happen, so a refused audit write fails the
request rather than being swallowed the way the auth routes deliberately swallow theirs.

**2. The budget counts records.** A conversation-shaped reveal charges its page size, not
one, and the number it charges is the number on the audit row and the number the meter
renders. A budget that charged one unit per request would pass every other test here.

**3. The plaintext is byte-exact.** ``Oʻktam``, ``Gʻulom``, ``Дилноза`` and ``sanʼat`` go in
and come out with their codepoints unchanged — asserted as codepoints, not as strings,
because ``"Oʻktam" == "O'ktam"`` is false but ``NFKD`` makes them equal and a normalising
layer anywhere on this path would be invisible to an ``==`` on two literals that both went
through it. This is the inverse of ``test_redaction.py``'s
``test_no_plaintext_reaches_any_body_at_any_role``: reveal is the one route where the whole
string is *supposed* to cross, so it is the one route where a stray ``.normalize()`` would
destroy the datum instead of merely leaking it.

**4. A purged column is distinguishable from an empty one.** ``mask_name(None) is None`` is
load-bearing in the serializer for the same reason it is here: "no name" and "name erased on
schedule on 2026-05-14" are different facts, ``identity_purged_at`` is always displayed, and
a reveal that answered ``""`` or a mask for a purged column would destroy that distinction
on the one screen that exists to make it.

The step-up is always obtained by driving ``POST /api/auth/step-up`` rather than by building
a ``StepUpGrant`` by hand. That is the only shape that catches the two failures a hand-built
grant cannot: an action spelled as a ``Permission`` value rather than a ``StepUpAction``
(``reveal.personal_data`` builds a perfectly storable scope that the issued ``reveal:<id>``
grant never matches), and a subject id stringified differently on the two sides of a
whole-string comparison.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.routers.reveal import REVEAL_PATH
from bayram.admin.routers.users import USER_BLOCK_PATH
from bayram.admin.schemas.actions import ReasonedRequest, UserBlockRequest
from bayram.admin.schemas.reveal import (
    FIELD_SHAPES,
    FIELD_SUBJECTS,
    RevealField,
    RevealRequest,
    RevealShape,
    RevealSubjectType,
)
from bayram.admin.security.budget import (
    MAX_RECORDS_PER_REVEAL,
    RevealBudgetScope,
    reveal_budget_key,
)
from bayram.admin.services import reveal as reveal_service

# ``_FIELD_NAME_PATTERN`` is imported rather than restated: a copied regex would drift, and
# it would drift in the direction of passing here while the audit boundary refused.
from bayram.db.admin.audit import _FIELD_NAME_PATTERN as AUDIT_FIELD_NAME_PATTERN
from bayram.db.admin.audit import SUBJECT_TYPES
from bayram.db.admin.audit import append as audit_append
from bayram.db.base import utc_now
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome
from bayram.db.models.user_profile import UserProfileRow
from bayram.errors import ErrorCode
from tests.test_admin.conftest import (
    NOW,
    ORIGIN,
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
from tests.test_admin.test_orders_router import (
    seed_attempt,
    seed_brief,
    seed_order,
    seed_purged_brief,
    seed_user,
)

#: The four names the U+02BB assertion is written around, with their codepoints spelled out
#: so the fixture cannot drift into the ASCII apostrophe it exists to be distinguished from.
#:
#: * ``Oʻktam`` / ``Gʻulom`` carry U+02BB MODIFIER LETTER TURNED COMMA — correct Uzbek Latin
#:   orthography for the ``oʻ``/``gʻ`` letters, and the character ``NFKD`` folds to ``'``.
#: * ``sanʼat`` carries U+02BC MODIFIER LETTER APOSTROPHE, the *other* one; a layer that
#:   "helpfully" unified the two would pass a test that used only the first.
#: * ``Дилноза`` is Cyrillic, so a byte-slicing bug shows up as mojibake rather than as a
#:   subtly wrong apostrophe.
_NAMES: Final[tuple[tuple[str, str, tuple[int, ...]], ...]] = (
    ("oktam", "Oʻktam", (0x4F, 0x02BB, 0x6B, 0x74, 0x61, 0x6D)),
    ("gulom", "Gʻulom", (0x47, 0x02BB, 0x75, 0x6C, 0x6F, 0x6D)),
    ("dilnoza", "Дилноза", (0x414, 0x438, 0x43B, 0x43D, 0x43E, 0x437, 0x430)),
    ("sanat", "sanʼat", (0x73, 0x61, 0x6E, 0x02BC, 0x61, 0x74)),
)

#: The customer's own words about a real third party. §12.3 exposes it as a length
#: everywhere except here.
_NOTE: Final[str] = "Oʻktam akasi bilan togʻda — sanʼat haqida gapiradi."
_TRANSCRIPT: Final[str] = "Gʻulom, tugʻilgan kuningiz bilan"

#: The contact record the four ``user_profiles`` fields reveal. The number is Uzbek and the
#: names carry U+02BB, so the byte-exactness rule this file is built around covers the second
#: table as well as the first — a normalising layer added on the profile path would otherwise
#: have no test looking at it.
_PHONE: Final[str] = "+998901234542"
_USERNAME: Final[str] = "gulomjon"
_FIRST_NAME: Final[str] = "Gʻulom"
_LAST_NAME: Final[str] = "Oʻktamov"
#: Every one of them, as the substrings a leak would show up as.
_PROFILE_PLAINTEXTS: Final[tuple[str, ...]] = (_PHONE, _USERNAME, _FIRST_NAME, _LAST_NAME)

_BUDGET_LOGGER: Final[str] = "bayram.admin.security.budget"
#: ``admin_reveal_records_per_hour`` has ``ge=10``, so this is the tightest hour an operator
#: can be configured into and the cheapest one to exhaust in a test.
_TIGHT_RECORDS: Final[int] = 10

_NAME_FIELDS: Final[list[str]] = [
    RevealField.RECIPIENT_NAME_DISPLAY.value,
    RevealField.RECIPIENT_NAME_RAW.value,
]


class _Recorder(logging.Handler):
    """Collects records from one logger, whatever the root handlers have been set to.

    ``caplog`` cannot be used here: ``create_app``'s lifespan calls
    ``bayram.logging.configure_logging``, which reconfigures the root logger out from under
    pytest's capturing handler — so a WARNING emitted inside a request never reaches
    ``caplog.records`` and the assertion passes vacuously in the *other* direction. A handler
    attached to the named logger sees it either way.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def recording(name: str) -> Iterator[_Recorder]:
    """Capture one logger's WARNING-and-above records for the duration of the block."""
    recorder = _Recorder()
    logger = logging.getLogger(name)
    logger.addHandler(recorder)
    try:
        yield recorder
    finally:
        logger.removeHandler(recorder)


# ---------------------------------------------------------------------------
# A running panel, and the two requests every test here makes
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Panel:
    """One running admin API, its container and the counter store behind the budget."""

    container: AdminContainer
    http: httpx.AsyncClient
    limits: MemoryRateLimits


@asynccontextmanager
async def open_panel(**overrides: Any) -> AsyncIterator[Panel]:
    """The real application over in-memory SQLite, at whatever ceilings the test needs."""
    limits = MemoryRateLimits()
    async with (
        open_container(make_settings(**overrides), FakeRedis(), limits) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http, limits=limits)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with open_panel() as running:
        yield running


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.SUPPORT) -> str:
    """Sign in as ``role``. SUPPORT by default: §12.2's reveal row starts there, and a test
    that only ever used OWNER would not notice a cell that had quietly narrowed."""
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    response = await sign_in(panel.http, username=username, password=PASSWORD)
    assert response.status_code == 200
    return username


async def step_up(panel: Panel, *, subject: UUID, scope: str = "reveal") -> httpx.Response:
    """``POST /api/auth/step-up`` the way the SPA does — the only writer of ``step_up_scope``.

    ``str(subject)`` and nothing else: the scope is compared whole and byte-exact, so this
    call is also the assertion that the handler stringifies its subject the same way.
    """
    return await panel.http.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": str(subject)},
        headers=csrf_headers(panel.http),
    )


async def post_reveal(
    panel: Panel,
    *,
    subject: UUID,
    fields: list[str],
    reason_code: str | None = AuditReasonCode.SUPPORT_INVESTIGATION.value,
    **extra: Any,
) -> httpx.Response:
    body: dict[str, Any] = {
        "subjectType": "order",
        "subjectId": str(subject),
        "fields": fields,
        **extra,
    }
    if reason_code is not None:
        body["reasonCode"] = reason_code
    return await panel.http.post(REVEAL_PATH, json=body, headers=csrf_headers(panel.http))


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
async def seed_reveal_order(
    panel: Panel,
    *,
    name: str = "Gʻulom",
    note: str | None = _NOTE,
    telegram_user_id: int = 55_000_001,
) -> UUID:
    """One order with a named brief and nothing else."""
    async with panel.container.session_factory.begin() as session:
        user = await seed_user(session, telegram_user_id=telegram_user_id)
        order = await seed_order(session, user=user, correlation_id=f"corr-{uuid4().hex[:8]}")
        await seed_brief(
            session,
            order=order,
            recipient_name_display=name,
            recipient_name_raw=name,
            note=note,
        )
        return order.id


async def seed_transcript_order(panel: Panel, *, takes: int) -> UUID:
    """One order with ``takes`` attempts, each carrying free text, all distinctly stamped.

    Distinct ``created_at`` per row because the keyset key is ``(created_at, id)``: rows
    sharing an instant would page on the id tie-break alone, which is a weaker exercise of
    the cursor than the production data gives it.
    """
    async with panel.container.session_factory.begin() as session:
        user = await seed_user(session, telegram_user_id=55_000_002)
        order = await seed_order(session, user=user, correlation_id="corr-transcript")
        await seed_brief(session, order=order)
        for index in range(takes):
            await seed_attempt(
                session,
                order=order,
                sequence=index,
                stt_transcript=f"{_TRANSCRIPT} #{index}",
                created_at=NOW - timedelta(seconds=index),
            )
        return order.id


async def seed_reveal_profile(panel: Panel, *, telegram_user_id: int = 55_000_004) -> UUID:
    """One customer with a contact record, returning the ``users.id`` a reveal is keyed on.

    The Telegram id is returned by nobody on purpose: the caller that wants it has it
    already, and a helper handing back both invites the test that posts the wrong one and
    then asserts on a 403 it cannot explain. The four values seeded here are the four
    columns ``PROFILE_COLUMNS`` names, so a reveal that returned three of them fails on the
    fourth rather than on a shape.
    """
    async with panel.container.session_factory.begin() as session:
        user = await seed_user(session, telegram_user_id=telegram_user_id)
        session.add(
            UserProfileRow(
                user_id=user.id,
                telegram_user_id=telegram_user_id,
                phone_e164=_PHONE,
                telegram_username=_USERNAME,
                first_name=_FIRST_NAME,
                last_name=_LAST_NAME,
                phone_shared_at=NOW,
                onboarded_at=NOW,
            )
        )
        return user.id


async def audit_rows(container: AdminContainer, action: AuditAction) -> list[AdminAuditRow]:
    """Every row for one action, oldest first."""
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == action)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# The field vocabulary, closed at both ends
# ---------------------------------------------------------------------------
def test_every_reveal_field_has_a_column_behind_it() -> None:
    # Arrange — the wire vocabulary and the two column tables the service reads it through
    # are separate declarations, and a field added to one and not the other is a 500 on a
    # route whose whole job is to answer carefully. Worse, a ``dict.get(field)`` default
    # would answer ``null`` instead, and ``null`` on this endpoint means "purged".

    # Act
    covered = (
        set(reveal_service.BRIEF_COLUMNS)
        | set(reveal_service.ATTEMPT_COLUMNS)
        | set(reveal_service.PROFILE_COLUMNS)
    )

    # Assert — exactly, in both directions, and each field's shape agrees with the table it
    # is in: a ``briefs`` column is one record, an attempt column is a page of them.
    assert covered == set(RevealField) == set(FIELD_SHAPES)
    assert {FIELD_SHAPES[f] for f in reveal_service.BRIEF_COLUMNS} == {RevealShape.SINGLE}
    assert {FIELD_SHAPES[f] for f in reveal_service.ATTEMPT_COLUMNS} == {RevealShape.PAGED}
    assert {FIELD_SHAPES[f] for f in reveal_service.PROFILE_COLUMNS} == {RevealShape.SINGLE}


def test_no_field_appears_in_two_column_tables() -> None:
    # Arrange — the shape no longer decides which table is read, and this is the assertion
    # that keeps the decision unambiguous. Every ``user_profiles`` column is SINGLE and so is
    # every ``briefs`` column, so ``read_records`` branches on the SUBJECT first and falls
    # through to the shape only afterwards. A field sitting in two maps would make that
    # branch answer differently depending on which arm ran — and the arms are keyed by two
    # different id spaces, a ``users.id`` and an ``orders.id``, that happen not to collide.
    # The failure would be one customer's note returned under another customer's grant, with
    # every shape assertion above still green, because the shape would be right.
    tables = (
        set(reveal_service.BRIEF_COLUMNS),
        set(reveal_service.ATTEMPT_COLUMNS),
        set(reveal_service.PROFILE_COLUMNS),
    )

    # Act
    total = sum(len(table) for table in tables)

    # Assert — pairwise disjoint, stated as a count so the failure names the size of the
    # overlap rather than only that one exists.
    assert total == len(set().union(*tables))
    for first, second in ((0, 1), (0, 2), (1, 2)):
        assert tables[first] & tables[second] == set(), (first, second)


def test_every_field_belongs_to_the_subject_whose_table_holds_it() -> None:
    # Arrange — ``FIELD_SUBJECTS`` refuses a mixed request at the boundary and the branch in
    # ``read_records`` refuses it again at the read, but neither of them checks that the two
    # halves agree. If ``user_profiles.phone_e164`` were declared an ORDER field, a perfectly
    # well-formed request would pass the validator and then be read out of ``briefs``, which
    # has no such column, as a 500 on the one route that must answer carefully.

    # Act / Assert — the declaration and the table that actually holds the column.
    for field in reveal_service.PROFILE_COLUMNS:
        assert FIELD_SUBJECTS[field] is RevealSubjectType.USER, field
    for field in (*reveal_service.BRIEF_COLUMNS, *reveal_service.ATTEMPT_COLUMNS):
        assert FIELD_SUBJECTS[field] is RevealSubjectType.ORDER, field
    assert set(FIELD_SUBJECTS) == set(RevealField)


def test_the_user_subject_type_is_a_name_the_audit_log_accepts() -> None:
    # Arrange — ``audit.SUBJECT_TYPES`` is the closed vocabulary the column accepts, and
    # ``audit_sink`` SWALLOWS a refusal and retries the row with ``subject_id=None, ip=None``.
    # A subject type outside it would therefore ship a 200 whose audit row cannot be
    # attributed to the customer it was about — invisible to every test that reads only the
    # response body, and the exact failure ``field_names`` has its own test for above.

    # Act / Assert
    assert RevealSubjectType.USER.value in SUBJECT_TYPES
    assert {subject.value for subject in RevealSubjectType} <= SUBJECT_TYPES


def test_every_reveal_field_is_a_name_the_audit_log_will_store() -> None:
    # Arrange — ``audit._FIELD_NAME_PATTERN`` refuses anything that is not a lowercase dotted
    # identifier, and ``audit_sink`` would swallow the refusal and retry the row with
    # ``subject_id=None, ip=None``. A camelCase member here would therefore ship a 200 whose
    # audit row cannot be attributed to a subject — invisible to every test that only reads
    # the response.

    # Act / Assert
    for field in RevealField:
        assert AUDIT_FIELD_NAME_PATTERN.fullmatch(field.value), field


# ---------------------------------------------------------------------------
# Who may ask at all — the split row, over HTTP
# ---------------------------------------------------------------------------
async def test_an_unauthenticated_reveal_is_401_and_returns_nothing(panel: Panel) -> None:
    # Arrange
    order_id = await seed_reveal_order(panel)

    # Act
    response = await panel.http.post(
        REVEAL_PATH,
        json={
            "subjectType": "order",
            "subjectId": str(order_id),
            "fields": [RevealField.NOTE.value],
            "reasonCode": AuditReasonCode.SUPPORT_INVESTIGATION.value,
        },
        headers={"Origin": ORIGIN},
    )

    # Assert
    assert response.status_code == 401
    assert _NOTE not in response.text


async def test_a_viewer_is_refused_for_their_role_and_not_sent_to_re_authenticate(
    panel: Panel,
) -> None:
    # Arrange — §12.2 gives VIEWER no reveal cell, so the refusal must be FORBIDDEN. A
    # STEP_UP_REQUIRED here would open a re-authentication prompt at somebody no grant could
    # ever admit, which is a loop they cannot win.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel, role=AdminRole.VIEWER)

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value


# ---------------------------------------------------------------------------
# The two refusals the acceptance names
# ---------------------------------------------------------------------------
async def test_a_reveal_without_a_reason_code_is_422(panel: Panel) -> None:
    # Arrange — §12.3: "``reasonCode`` is required and comes from the closed
    # ``AuditReasonCode`` enum". A default here would make the accountability optional.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel, subject=order_id, fields=[RevealField.NOTE.value], reason_code=None
    )

    # Assert
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == ErrorCode.INVALID_INPUT.value
    assert any("reasonCode" in field for field in body["details"]["fields"])
    assert _NOTE not in response.text


async def test_a_reveal_without_a_reason_code_is_refused_before_anything_is_charged(
    panel: Panel,
) -> None:
    # Arrange — the ordering claim from the other end: the body is validated first, so a
    # malformed request costs no budget and writes no ``REVEAL_PERSONAL`` row. A handler
    # that charged before validating would let a caller drain their own hourly ceiling with
    # requests that never reached a database.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200
    charged_before = dict(panel.limits.counts)

    # Act
    response = await post_reveal(
        panel, subject=order_id, fields=[RevealField.NOTE.value], reason_code=None
    )

    # Assert
    assert response.status_code == 422
    assert panel.limits.counts == charged_before
    assert await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL) == []


async def test_a_reveal_without_a_scoped_step_up_is_403_step_up_required(panel: Panel) -> None:
    # Arrange — signed in, holding the cell, and holding no grant. Phase 1 wrote
    # ``admin_sessions.step_up_scope`` and no route ever read it back; this is the read.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert _NOTE not in response.text


async def test_a_step_up_taken_for_one_order_does_not_reveal_another(panel: Panel) -> None:
    # Arrange — the confused deputy the subject half of the scope exists to stop.
    first = await seed_reveal_order(panel)
    second = await seed_reveal_order(panel, telegram_user_id=55_000_009)
    await signed_in(panel)
    assert (await step_up(panel, subject=first)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=second, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_a_step_up_taken_for_a_different_action_does_not_reveal(panel: Panel) -> None:
    # Arrange — a grant collected to block a user is not a grant to read their note. This is
    # also the test that would fail if the handler passed a ``Permission`` value where a
    # ``StepUpAction`` belongs: ``reveal.personal_data:<id>`` is a perfectly storable scope
    # that the issued ``reveal:<id>`` grant never matches.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    granted = await step_up(panel, subject=order_id, scope="user.block")

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert granted.status_code == 200
    assert granted.json()["scope"] == f"user.block:{order_id}"
    assert response.status_code == 403


async def test_a_grant_older_than_the_grace_no_longer_reveals(panel: Panel) -> None:
    # Arrange — the window ``/auth/step-up`` promised is the window the handler honours.
    # Aged by rewriting the stored ``step_up_at`` rather than by sleeping, because the
    # handler reads its own ``utc_now()`` and the grace is five minutes.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    granted = await step_up(panel, subject=order_id)
    assert granted.status_code == 200
    grace_s = panel.container.settings.admin_step_up_grace_seconds
    async with panel.container.session_factory.begin() as db:
        await db.execute(
            sa.text(
                "UPDATE admin_sessions SET step_up_at = "
                "datetime(step_up_at, :shift) WHERE step_up_scope IS NOT NULL"
            ),
            {"shift": f"-{grace_s + 60} seconds"},
        )
    # The Redis mirror caches the session row, so it has to go with the column it caches.
    panel.container.redis.values.clear()  # type: ignore[attr-defined]

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


# ---------------------------------------------------------------------------
# The reveal itself
# ---------------------------------------------------------------------------
async def test_a_scoped_step_up_and_a_reason_code_return_the_named_fields_only(
    panel: Panel,
) -> None:
    # Arrange — §12.3: "Returns plaintext for the named fields only, not the whole object."
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act — the note, and pointedly not the name.
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["recordCount"] == 1
    assert body["revealedFields"] == [RevealField.NOTE.value]
    assert [record["fields"] for record in body["records"]] == [{RevealField.NOTE.value: _NOTE}]
    # The name was never asked for, so it is not in the payload at all — not masked, absent.
    assert "Gʻulom" not in response.text
    assert RevealField.RECIPIENT_NAME_DISPLAY.value not in response.text


async def test_the_audit_row_carries_the_field_names_the_reason_and_the_charge(
    panel: Panel,
) -> None:
    # Arrange — §12.4: ``field_names`` records *that* ``briefs.note`` was revealed, never
    # what it said, and ``record_count`` is what ``/audit`` and the dashboard measure.
    order_id = await seed_reveal_order(panel)
    username = await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.NOTE.value, RevealField.RECIPIENT_NAME_DISPLAY.value],
        reason_code=AuditReasonCode.CUSTOMER_REQUEST.value,
        reasonRef="HD-4417",
        reasonText="caller asked which name we sang",
    )

    # Assert
    assert response.status_code == 200
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_username == username
    assert row.subject_type == "order"
    assert row.subject_id == str(order_id)
    assert row.field_names == [
        RevealField.NOTE.value,
        RevealField.RECIPIENT_NAME_DISPLAY.value,
    ]
    assert row.record_count == 1
    assert row.reason_code is AuditReasonCode.CUSTOMER_REQUEST
    assert row.reason_ref == "HD-4417"
    assert row.reason_text == "caller asked which name we sang"
    assert row.outcome is AuditOutcome.OK
    # §12.4: never a personal-data value. The note was revealed; the row must not carry it.
    assert _NOTE not in repr(tuple(row.__dict__.values()))


async def test_a_reason_text_carrying_control_characters_is_cleaned_not_refused(
    panel: Panel,
) -> None:
    # Arrange — §12.3 caps ``reasonText`` at 500 chars with control chars stripped. It is
    # operator text, so cleaning it is required; the revealed value is customer text and is
    # never touched.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.NOTE.value],
        reasonText="ticket\r\n\x07 4417",
    )

    # Assert
    assert response.status_code == 200
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert rows[0].reason_text == "ticket 4417"


async def test_a_revealed_purged_column_is_null_and_says_which_clock_erased_it(
    panel: Panel,
) -> None:
    # Arrange — the 90-day sweep's leavings. ``null`` for the column and a stamp beside it:
    # "no name" and "name erased on schedule" are different facts, and this is the one screen
    # that exists to tell them apart.
    async with panel.container.session_factory.begin() as session:
        user = await seed_user(session, telegram_user_id=55_000_003)
        order = await seed_order(session, user=user, correlation_id="corr-purged")
        await seed_purged_brief(session, order=order)
        order_id = order.id
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=order_id, fields=_NAME_FIELDS)

    # Assert
    assert response.status_code == 200
    record = response.json()["records"][0]
    assert record["fields"] == dict.fromkeys(_NAME_FIELDS)
    assert record["identityPurgedAt"] is not None
    assert record["textPurgedAt"] is not None


async def test_a_reveal_of_an_order_that_does_not_exist_is_404_and_still_audited(
    panel: Panel,
) -> None:
    # Arrange — a 404 *after* the audit row is the ordering working: the operator asked, and
    # the log says so whether or not there was anything to answer with.
    missing = uuid4()
    await signed_in(panel)
    assert (await step_up(panel, subject=missing)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=missing, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 404
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.outcome for row in rows] == [AuditOutcome.OK, AuditOutcome.ERROR]
    assert rows[0].record_count == 1
    # The OUTCOME row carries no count: nothing was disclosed, and the dashboard sums that
    # column.
    assert rows[1].record_count is None
    assert rows[1].error_code == ErrorCode.NOT_FOUND.value


# ---------------------------------------------------------------------------
# The user subject — one endpoint, a second table, and the id space that must not slip
# ---------------------------------------------------------------------------
async def test_a_user_reveal_returns_the_four_contact_columns(panel: Panel) -> None:
    # Arrange — the phone, the handle and the two names are masked on every wire the panel
    # serves, at every role including OWNER, so this endpoint is the only way an operator
    # reaches them and the only place they are asserted to be reachable at all. A masking
    # bug that emptied the columns would otherwise look exactly like correct redaction.
    user_id = await seed_reveal_profile(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=user_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=user_id,
        fields=[field.value for field in reveal_service.PROFILE_COLUMNS],
        subjectType=RevealSubjectType.USER.value,
    )

    # Assert — byte-exact, for the reason the U+02BB section below states at length: this is
    # the one route where the whole string is supposed to cross, so a stray ``.normalize()``
    # here destroys the datum rather than merely leaking it.
    assert response.status_code == 200
    body = response.json()
    assert body["recordCount"] == 1
    assert body["records"][0]["fields"] == {
        RevealField.USER_PHONE_E164.value: _PHONE,
        RevealField.USER_TELEGRAM_USERNAME.value: _USERNAME,
        RevealField.USER_FIRST_NAME.value: _FIRST_NAME,
        RevealField.USER_LAST_NAME.value: _LAST_NAME,
    }
    assert body["records"][0]["recordId"] == str(user_id)


async def test_a_user_reveal_takes_the_users_uuid_and_not_the_telegram_id(panel: Panel) -> None:
    # Arrange — the id space is the whole reason ``user_profiles`` is keyed on ``users.id``:
    # ``RevealRequest.subjectId`` is a UUID and the step-up scope is ``reveal:<str(uuid)>``,
    # compared whole and byte-exact. A Telegram integer on one side of that comparison is a
    # STEP_UP_SCOPE_MISMATCH nobody can debug from the 403, so the boundary refuses it as a
    # 422 about the field instead — before any grant is consulted and before anything is
    # charged.
    telegram_user_id = 55_000_014
    user_id = await seed_reveal_profile(panel, telegram_user_id=telegram_user_id)
    await signed_in(panel)
    assert (await step_up(panel, subject=user_id)).status_code == 200
    fields = [RevealField.USER_PHONE_E164.value]

    # Act — the same request twice, differing only in which id names the subject.
    with_telegram_id = await panel.http.post(
        REVEAL_PATH,
        json={
            "subjectType": RevealSubjectType.USER.value,
            "subjectId": telegram_user_id,
            "fields": fields,
            "reasonCode": AuditReasonCode.SUPPORT_INVESTIGATION.value,
        },
        headers=csrf_headers(panel.http),
    )
    with_user_id = await post_reveal(
        panel,
        subject=user_id,
        fields=fields,
        subjectType=RevealSubjectType.USER.value,
    )

    # Assert
    assert with_telegram_id.status_code == 422
    assert _PHONE not in with_telegram_id.text
    assert with_user_id.status_code == 200
    assert with_user_id.json()["records"][0]["fields"] == {
        RevealField.USER_PHONE_E164.value: _PHONE
    }


async def test_a_user_subject_that_has_no_profile_row_is_a_404_and_not_an_empty_record(
    panel: Panel,
) -> None:
    # Arrange — ``/forget`` DELETEs the row (PD-3) and there is no purge stamp on this table,
    # so an erased customer must be a 404. The alternative — a record whose four fields are
    # ``null`` — would collide with the one meaning ``null`` already carries here: "the
    # customer never gave us that datum". An operator cannot be left unable to tell "we
    # erased this on request" from "they never shared a surname".
    missing = uuid4()
    await signed_in(panel)
    assert (await step_up(panel, subject=missing)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=missing,
        fields=[RevealField.USER_PHONE_E164.value],
        subjectType=RevealSubjectType.USER.value,
    )

    # Assert — and audited, like every other reveal that found nothing.
    assert response.status_code == 404
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.outcome for row in rows] == [AuditOutcome.OK, AuditOutcome.ERROR]
    assert rows[0].subject_type == RevealSubjectType.USER.value


async def test_mixing_a_user_field_with_an_order_field_is_the_fourth_refusal(
    panel: Panel,
) -> None:
    # Arrange — the refusal ``RevealRequest._one_shape`` gained for exactly this change. Both
    # fields are SINGLE, so the shape check that catches every other mixed request passes,
    # and without the subject check the request would reach ``read_records`` carrying a
    # ``users.id`` for a read out of ``briefs``. Two id spaces that happen not to collide is
    # all that would stand between that and one customer's note under another's grant.
    user_id = await seed_reveal_profile(panel, telegram_user_id=55_000_015)
    await signed_in(panel)
    assert (await step_up(panel, subject=user_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=user_id,
        fields=[RevealField.USER_PHONE_E164.value, RevealField.NOTE.value],
        subjectType=RevealSubjectType.USER.value,
    )

    # Assert — a 422 at the boundary, never a 500 and never a partial read, and nothing
    # charged or audited because the refusal happens before either.
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT.value
    assert response.json()["error"]["details"]["fields"] == ["body"]
    for plaintext in _PROFILE_PLAINTEXTS:
        assert plaintext not in response.text
    assert await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL) == []

    # Assert — the envelope deliberately reports the failing LOCATION and not the validator's
    # sentence (a reveal's error body is one nobody has masked), so the message that names
    # the offending field is asserted against the model itself. Without this half, a
    # validator that refused every user reveal for the wrong reason would pass above.
    with pytest.raises(ValidationError, match=RevealField.NOTE.value):
        RevealRequest(
            subject_type=RevealSubjectType.USER,
            subject_id=user_id,
            fields=(RevealField.USER_PHONE_E164, RevealField.NOTE),
            reason_code=AuditReasonCode.SUPPORT_INVESTIGATION,
        )


async def test_a_user_reveal_writes_an_audit_row_with_subject_type_user(panel: Panel) -> None:
    # Arrange — §12.4: the row records *that* ``user_profiles.phone_e164`` was revealed and
    # never what it said. The subject type is what makes an audit search for "everything ever
    # read about this customer" possible at all; with ``order`` on the row, a reveal keyed on
    # a ``users.id`` would file itself under an order id that does not exist.
    #
    # The subject ID is asserted as the TELEGRAM id and not the ``users.id`` the request
    # carried: see ``test_a_reveal_and_a_block_of_one_customer_share_a_subject_id`` below for
    # the whole of that argument.
    user_id = await seed_reveal_profile(panel, telegram_user_id=55_000_016)
    username = await signed_in(panel)
    assert (await step_up(panel, subject=user_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=user_id,
        fields=[RevealField.USER_PHONE_E164.value, RevealField.USER_FIRST_NAME.value],
        subjectType=RevealSubjectType.USER.value,
        reason_code=AuditReasonCode.CUSTOMER_REQUEST.value,
    )

    # Assert
    assert response.status_code == 200
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert len(rows) == 1
    assert rows[0].subject_type == RevealSubjectType.USER.value
    assert rows[0].subject_id == "55000016"
    assert rows[0].actor_username == username
    assert rows[0].field_names == [
        RevealField.USER_PHONE_E164.value,
        RevealField.USER_FIRST_NAME.value,
    ]
    assert rows[0].record_count == 1
    assert rows[0].reason_code is AuditReasonCode.CUSTOMER_REQUEST
    # §12.4: never a personal-data value. The number was revealed; the row must not carry it.
    for plaintext in _PROFILE_PLAINTEXTS:
        assert plaintext not in repr(tuple(rows[0].__dict__.values()))


async def test_a_reveal_and_a_block_of_one_customer_share_a_subject_id(panel: Panel) -> None:
    """``subject_type="user"`` must mean one id space, or ``/audit`` answers half a question.

    ``users.py::_block_entry`` and ``credits.py::_grant_entry`` file under the Telegram id —
    the only identifier either route holds. A reveal arrives with the ``users.id`` its
    step-up scope is compared byte-exact against. Filed as-is, the two spellings split one
    customer's trail in two, and neither
    ``GET /api/audit?subjectType=user&subjectId=<telegram id>`` nor the query with the UUID
    carries any signal that the other half exists — so a DSAR or an abuse investigation gets
    half the answer and reads it as the whole one. The step-up keeps the UUID; only the
    audit row is translated.
    """
    # Arrange — one customer, one operator who may both reveal and block.
    telegram_user_id = 55_000_017
    user_id = await seed_reveal_profile(panel, telegram_user_id=telegram_user_id)
    await signed_in(panel, role=AdminRole.ADMIN)

    # Act — a reveal scoped to the UUID, then a block scoped to the Telegram id.
    assert (await step_up(panel, subject=user_id)).status_code == 200
    revealed = await post_reveal(
        panel,
        subject=user_id,
        fields=[RevealField.USER_PHONE_E164.value],
        subjectType=RevealSubjectType.USER.value,
    )
    blocked = await panel.http.post(
        "/api/auth/step-up",
        json={
            "password": PASSWORD,
            "scope": "user.block",
            "subjectId": str(telegram_user_id),
        },
        headers=csrf_headers(panel.http),
    )
    assert blocked.status_code == 200
    action = await panel.http.post(
        USER_BLOCK_PATH.format(telegram_user_id=telegram_user_id),
        json={"reasonCode": AuditReasonCode.ABUSE_REPORT.value},
        headers=csrf_headers(panel.http),
    )

    # Assert
    assert revealed.status_code == 200
    assert action.status_code == 200
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL) + await audit_rows(
        panel.container, AuditAction.USER_BLOCK
    )
    assert len(rows) == 2
    assert {row.subject_type for row in rows} == {RevealSubjectType.USER.value}
    assert {row.subject_id for row in rows} == {str(telegram_user_id)}


async def test_a_user_reveal_with_no_users_row_audits_under_the_id_it_was_given(
    panel: Panel,
) -> None:
    """The fallback: an audit row that lost its subject is worse than one under the UUID.

    Reachable only if a ``user_profiles`` row outlived its ``users`` row, which the schema
    does not allow — but the translation must not answer ``None`` for a subject column that
    then gets dropped by ``audit_sink``'s retry. The reveal itself 404s a moment later
    either way.
    """
    # Arrange
    request = RevealRequest(
        subject_type=RevealSubjectType.USER,
        subject_id=uuid4(),
        fields=(RevealField.USER_PHONE_E164,),
        reason_code=AuditReasonCode.SUPPORT_INVESTIGATION,
    )
    plan = reveal_service.plan_reveal(request)

    # Act
    async with panel.container.session_factory.begin() as db:
        resolved = await reveal_service.audit_subject_id(db, plan)

    # Assert
    assert resolved == str(request.subject_id)


# ---------------------------------------------------------------------------
# One reason trio, one scrubber
# ---------------------------------------------------------------------------
def test_the_reveal_body_inherits_the_reason_trio_rather_than_restating_it() -> None:
    # Arrange — ``ReasonedRequest`` exists so an action added next quarter inherits the
    # mandatory reasonCode, the validated reasonRef and the scrubbed reasonText. While this
    # model restated all three, that claim was false and nothing compared the two: one
    # column, one 90-day sweep, cleaned differently depending on which endpoint wrote it.

    # Act / Assert
    assert issubclass(RevealRequest, ReasonedRequest)
    assert "reason_text" not in RevealRequest.__annotations__
    assert "reason_code" not in RevealRequest.__annotations__
    assert "reason_ref" not in RevealRequest.__annotations__


@pytest.mark.parametrize("control", ["\x00", "\n", "\r", "\t", "\x7f"])
def test_one_control_character_set_scrubs_both_bodies(control: str) -> None:
    # Arrange — the two models must agree character for character, because
    # ``admin_audit_log.reason_text`` is one column. Asserted as equality between the two
    # results rather than against a literal, so widening ``CONTROL_CHARACTERS`` keeps them
    # in step instead of quietly splitting them.
    text = f"ticket{control}42"

    # Act
    revealed = RevealRequest(
        subject_type=RevealSubjectType.USER,
        subject_id=uuid4(),
        fields=(RevealField.USER_PHONE_E164,),
        reason_code=AuditReasonCode.SUPPORT_INVESTIGATION,
        reason_text=text,
    )
    blocked = UserBlockRequest(reason_code=AuditReasonCode.SUPPORT_INVESTIGATION, reason_text=text)

    # Assert
    assert revealed.reason_text == blocked.reason_text == "ticket42"


# ---------------------------------------------------------------------------
# U+02BB — the product
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("slug", "name", "codepoints"), _NAMES, ids=[row[0] for row in _NAMES])
async def test_a_revealed_name_survives_byte_for_byte(
    slug: str, name: str, codepoints: tuple[int, ...]
) -> None:
    # Arrange — codepoints rather than a string comparison: ``"Oʻktam" == "O'ktam"`` is
    # false, but both literals normalise to the same thing, so an ``==`` between two values
    # that both went through a normalising layer would pass while the datum was destroyed.
    async with open_panel() as panel:
        order_id = await seed_reveal_order(panel, name=name, telegram_user_id=55_100_000)
        await signed_in(panel)
        assert (await step_up(panel, subject=order_id)).status_code == 200

        # Act
        response = await post_reveal(panel, subject=order_id, fields=_NAME_FIELDS)

    # Assert
    assert response.status_code == 200, slug
    fields = response.json()["records"][0]["fields"]
    for field in _NAME_FIELDS:
        revealed = fields[field]
        assert tuple(ord(char) for char in revealed) == codepoints, (slug, field)
        assert revealed == name, (slug, field)
    # And on the wire, not only after ``json()``: the response body carries the name's own
    # UTF-8 bytes rather than an escape sequence or a decomposed form.
    assert name.encode("utf-8") in response.content, slug


async def test_the_masked_form_of_the_name_is_nowhere_in_a_reveal(panel: Panel) -> None:
    # Arrange — the inverse of every other assertion about this name in the suite. Reveal is
    # where the whole string is supposed to cross, so a ``G•••`` here would mean the reveal
    # route had been wired through the masking serializer and returned nothing useful.
    order_id = await seed_reveal_order(panel, name="Gʻulom")
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=order_id, fields=_NAME_FIELDS)

    # Assert
    assert response.status_code == 200
    assert "•" not in response.text


# ---------------------------------------------------------------------------
# §12.3's ordering: the audit row is written BEFORE the read
# ---------------------------------------------------------------------------
async def test_the_audit_row_survives_a_read_that_fails_after_it(
    panel: Panel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — the only shape that can tell the two implementations apart. A row appended
    # into the request's transaction is rolled back by this exception; a row committed in its
    # own transaction is not. Both implementations pass "reveal, then assert the row exists".
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    async def explode(*_: object, **__: object) -> object:
        raise RuntimeError("the read failed after the audit row was written")

    monkeypatch.setattr(reveal_service, "read_records", explode)

    # Act
    with caplog.at_level(logging.ERROR):
        response = await panel.http.post(
            REVEAL_PATH,
            json={
                "subjectType": "order",
                "subjectId": str(order_id),
                "fields": [RevealField.NOTE.value],
                "reasonCode": AuditReasonCode.INCIDENT.value,
            },
            headers=csrf_headers(panel.http),
        )

    # Assert — the reveal failed, nothing was disclosed, and the operator is still on record.
    assert response.status_code == 500
    assert _NOTE not in response.text
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.outcome for row in rows] == [AuditOutcome.OK, AuditOutcome.ERROR]
    assert rows[0].record_count == 1
    assert rows[0].subject_id == str(order_id)
    assert rows[1].error_code == AdminErrorCode.INTERNAL_ERROR.value


async def test_a_reveal_whose_audit_row_cannot_be_written_returns_no_plaintext(
    panel: Panel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — §9.1's other half. ``audit_sink`` deliberately swallows an audit failure so a
    # login cannot be taken down by a caller-chosen username; a reveal must do the opposite,
    # because a swallowed failure there is plaintext on the wire with nothing in the log.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    async def refuse(*_: object, **__: object) -> object:
        raise RuntimeError("the audit table is unreachable")

    monkeypatch.setattr(reveal_service, "append", refuse)

    # Act
    with caplog.at_level(logging.ERROR):
        response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

    # Assert
    assert response.status_code == 500
    assert _NOTE not in response.text


async def test_a_failing_outcome_row_does_not_replace_the_operator_s_real_error(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the two audit writes are deliberately asymmetric. The row before the read is
    # allowed to fail the request, because an unaudited reveal must not happen; the OUTCOME
    # row after it is not, because the request is already failing and a second exception here
    # would bury the answer the operator needs under an audit error they cannot act on. The
    # INTENT row is already committed either way, so the reveal stays attributable.
    missing = uuid4()
    await signed_in(panel)
    assert (await step_up(panel, subject=missing)).status_code == 200
    calls = {"n": 0}

    async def fail_the_second(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("the audit table went away between the two writes")
        return await audit_append(*args, **kwargs)

    monkeypatch.setattr(reveal_service, "append", fail_the_second)

    # Act — a 404, whose OUTCOME row cannot be written.
    response = await post_reveal(panel, subject=missing, fields=[RevealField.NOTE.value])

    # Assert — still the 404, and the row that matters survived.
    assert response.status_code == 404
    assert calls["n"] == 2
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.outcome for row in rows] == [AuditOutcome.OK]


async def test_an_unstorable_reason_reference_refuses_the_reveal_as_a_422(
    panel: Panel,
) -> None:
    # Arrange — ``audit._CREDENTIAL_SHAPES`` refuses any 40-character alphanumeric run, and
    # ``_REASON_REF_PATTERN`` allows 64 characters, so the two guards disagree about what a
    # long ticket slug is. The disagreement is the plan's; what matters is that it surfaces
    # as a refusal naming the field rather than as a reveal with no row behind it.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.NOTE.value],
        reasonRef="A" * 48,
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT.value
    assert _NOTE not in response.text
    assert await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL) == []


# ---------------------------------------------------------------------------
# The paged, conversation-shaped reveal
# ---------------------------------------------------------------------------
async def test_a_conversation_reveal_returns_at_most_fifty_bodies_and_charges_fifty(
    panel: Panel,
) -> None:
    # Arrange — sixty takes, so the cap is what stops the page rather than the data running
    # out. §12.3: "A conversation reveal returns at most 50 bodies; more requires a fresh
    # reveal with a ``nextCursor``, each one charged and each one audited."
    order_id = await seed_transcript_order(panel, takes=60)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.STT_TRANSCRIPT.value])

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) == MAX_RECORDS_PER_REVEAL
    assert body["recordCount"] == MAX_RECORDS_PER_REVEAL
    assert body["budget"]["recordsCharged"] == MAX_RECORDS_PER_REVEAL
    assert body["budget"]["conversationsCharged"] == 1
    assert body["nextCursor"] is not None
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.record_count for row in rows] == [MAX_RECORDS_PER_REVEAL]
    # The bodies really are the customer's words, byte for byte.
    assert body["records"][0]["fields"][RevealField.STT_TRANSCRIPT.value] == f"{_TRANSCRIPT} #0"


async def test_a_reveal_larger_than_the_page_cap_is_refused(panel: Panel) -> None:
    # Arrange — the cap is enforced at the schema as well as in ``charge_reveal_budget``,
    # because a single charge larger than fifty is a page that was never paged.
    order_id = await seed_transcript_order(panel, takes=3)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.STT_TRANSCRIPT.value],
        limit=MAX_RECORDS_PER_REVEAL + 1,
    )

    # Assert
    assert response.status_code == 422


async def test_the_next_cursor_costs_a_second_charge_and_a_second_audit_row(
    panel: Panel,
) -> None:
    # Arrange — "each one charged and each one audited". A cursor is a position, not a
    # licence: an implementation that carried the first page's charge forward, or that
    # audited only the first request, would let one grant and one charge walk the whole
    # transcript.
    order_id = await seed_transcript_order(panel, takes=7)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200
    first = await post_reveal(
        panel, subject=order_id, fields=[RevealField.STT_TRANSCRIPT.value], limit=3
    )
    assert first.status_code == 200
    cursor = first.json()["nextCursor"]
    assert cursor is not None

    # Act
    second = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.STT_TRANSCRIPT.value],
        limit=3,
        cursor=cursor,
    )

    # Assert
    assert second.status_code == 200
    firsts = {record["recordId"] for record in first.json()["records"]}
    seconds = {record["recordId"] for record in second.json()["records"]}
    assert len(firsts) == len(seconds) == 3
    assert firsts.isdisjoint(seconds)
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert [row.record_count for row in rows] == [3, 3]
    assert second.json()["budget"]["conversationsCharged"] == 1


async def test_a_next_cursor_is_no_use_without_a_step_up_of_its_own(panel: Panel) -> None:
    # Arrange — the sharper half of "requires a fresh reveal". The cursor carries a position
    # and nothing else, so a session that never stepped up cannot spend it.
    order_id = await seed_transcript_order(panel, takes=7)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200
    first = await post_reveal(
        panel, subject=order_id, fields=[RevealField.STT_TRANSCRIPT.value], limit=3
    )
    cursor = first.json()["nextCursor"]

    # Act — a second operator, holding the cell and no grant, with the first one's cursor.
    panel.http.cookies.clear()
    await signed_in(panel, role=AdminRole.ADMIN)
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.STT_TRANSCRIPT.value],
        limit=3,
        cursor=cursor,
    )

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_a_cursor_this_api_did_not_mint_is_a_422(panel: Panel) -> None:
    # Arrange — a cursor is attacker-supplied text off a JSON body; the decoder is a
    # never-throw boundary and this is where its ``Err`` becomes an envelope.
    order_id = await seed_transcript_order(panel, takes=3)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.STT_TRANSCRIPT.value],
        cursor="not-a-cursor",
    )

    # Assert
    assert response.status_code == 422


async def test_two_record_shapes_in_one_reveal_are_refused(panel: Panel) -> None:
    # Arrange — one ``record_count`` cannot honestly describe a brief's single row and a
    # page of takes at the same time, and a budget is only a measure of exposure if the
    # number it is handed is the number the caller may return.
    order_id = await seed_transcript_order(panel, takes=3)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel,
        subject=order_id,
        fields=[RevealField.NOTE.value, RevealField.STT_TRANSCRIPT.value],
    )

    # Assert
    assert response.status_code == 422


async def test_the_same_field_asked_for_twice_is_refused(panel: Panel) -> None:
    # Arrange — one read, one ``record_count``, and one ``field_names`` entry per column. A
    # repeated field would be audited twice for a single read, which makes the audit log's
    # own arithmetic wrong in the direction that overstates exposure.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel, subject=order_id, fields=[RevealField.NOTE.value, RevealField.NOTE.value]
    )

    # Assert
    assert response.status_code == 422


async def test_an_explicitly_null_reason_text_is_accepted_and_stored_as_null(
    panel: Panel,
) -> None:
    # Arrange — ``reasonText`` is optional, and the SPA sends ``null`` for "the operator
    # typed nothing" rather than omitting the key. That must not be a 422, and it must not
    # become an empty string either: ``reason_text`` carries the audit log's 90-day reason
    # clock, and a row with ``""`` would have an expiry set for text that does not exist.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(
        panel, subject=order_id, fields=[RevealField.NOTE.value], reasonText=None
    )

    # Assert
    assert response.status_code == 200
    row = (await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL))[0]
    assert row.reason_text is None
    assert row.reason_expires_at is None


async def test_limit_and_cursor_are_refused_on_a_single_record_reveal(panel: Panel) -> None:
    # Arrange — a page control on something with no pages teaches a caller to expect one.
    order_id = await seed_reveal_order(panel)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200

    # Act
    response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value], limit=5)

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The budget — §12.3's two ceilings, separately exhaustible
# ---------------------------------------------------------------------------
async def test_exceeding_the_hourly_record_budget_is_429_and_warns_naming_the_actor() -> None:
    # Arrange — §12.3: "Exceeding either returns 429 ``REVEAL_BUDGET_EXHAUSTED`` with a
    # WARNING log naming the actor. The limit is a detection control as much as a limit."
    # One grant covers every reveal here: grants are not single-use, which is exactly why
    # the budget is what bounds a compromised session's volume.
    async with open_panel(admin_reveal_records_per_hour=_TIGHT_RECORDS) as panel:
        order_id = await seed_reveal_order(panel)
        username = await signed_in(panel)
        assert (await step_up(panel, subject=order_id)).status_code == 200
        for _ in range(_TIGHT_RECORDS):
            spent = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])
            assert spent.status_code == 200

        # Act
        with recording(_BUDGET_LOGGER) as warnings:
            response = await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])

        # Assert
        assert response.status_code == 429
        body = response.json()["error"]
        assert body["code"] == AdminErrorCode.REVEAL_BUDGET_EXHAUSTED.value
        assert body["details"]["budget"] == "records"
        assert int(response.headers["Retry-After"]) > 0
        assert _NOTE not in response.text
        # The eleventh reveal read nothing, so it wrote no row either.
        rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
        assert len(rows) == _TIGHT_RECORDS
        # And its charge was given back: the budget bounds disclosure, and a refused reveal
        # disclosed nothing. Leaving it standing would make the counter measure attempts.
        # The store is shared with the credential limiter, so only the records budget's own
        # keys are read — named through ``reveal_budget_key`` rather than spelled again,
        # because a second spelling of a key is a second budget. The window index is trimmed
        # off so the assertion cannot fail on the clock hour turning mid-test.
        namespace = reveal_budget_key(
            RevealBudgetScope.RECORDS, username=username, now=utc_now()
        ).rsplit(":", 2)[0]
        charged = [value for key, value in panel.limits.counts.items() if key.startswith(namespace)]
        assert charged == [_TIGHT_RECORDS]

    named = [
        record
        for record in warnings.records
        if getattr(record, "admin_username", None) == username
        and getattr(record, "event", None) == "admin.reveal.budget_exhausted"
    ]
    assert len(named) == 1
    assert named[0].levelno == logging.WARNING


async def test_exceeding_the_daily_conversation_budget_is_429_separately() -> None:
    # Arrange — the second ceiling, and "separately" is the assertion: the hourly record
    # budget is nowhere near spent (two records against ten), so the only thing that can
    # refuse this is the daily transcript ceiling.
    async with open_panel(
        admin_reveal_records_per_hour=_TIGHT_RECORDS, admin_reveal_conversations_per_day=1
    ) as panel:
        order_id = await seed_transcript_order(panel, takes=6)
        username = await signed_in(panel)
        assert (await step_up(panel, subject=order_id)).status_code == 200
        first = await post_reveal(
            panel, subject=order_id, fields=[RevealField.STT_TRANSCRIPT.value], limit=1
        )
        assert first.status_code == 200

        # Act
        with recording(_BUDGET_LOGGER) as warnings:
            response = await post_reveal(
                panel, subject=order_id, fields=[RevealField.STT_TRANSCRIPT.value], limit=1
            )

        # Assert
        assert response.status_code == 429
        body = response.json()["error"]
        assert body["code"] == AdminErrorCode.REVEAL_BUDGET_EXHAUSTED.value
        assert body["details"]["budget"] == "conversations"
        # A name reveal still works: spending the day's transcripts must not spend the hour.
        name_reveal = await post_reveal(
            panel, subject=order_id, fields=[RevealField.RECIPIENT_NAME_DISPLAY.value]
        )
        assert name_reveal.status_code == 200

    named = [
        record
        for record in warnings.records
        if getattr(record, "admin_username", None) == username
        and getattr(record, "reveal_budget_scope", None) == "conversations"
    ]
    assert len(named) == 1
    assert named[0].levelno == logging.WARNING


async def test_a_reveal_that_found_nothing_still_costs_what_it_was_authorised_to_return(
    panel: Panel,
) -> None:
    # Arrange — the charge is the page size, before the read, and an empty result is not
    # free: a budget a caller could probe with by aiming at ids that do not exist would
    # measure nothing. Read through the meter rather than the store's keys, because the meter
    # is what an operator sees before confirming a reveal (§11.4's ``RevealBudgetMeter``).
    #
    # A step-up is taken per subject: grants are not single-use, but there is only one slot
    # per session, so asking about a second subject replaces the first grant.
    order_id = await seed_transcript_order(panel, takes=60)
    await signed_in(panel)
    assert (await step_up(panel, subject=order_id)).status_code == 200
    before = (await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])).json()[
        "budget"
    ]["recordsRemaining"]

    # Act — a page of fifty that the 404 never returns.
    missing = uuid4()
    assert (await step_up(panel, subject=missing)).status_code == 200
    refused = await post_reveal(panel, subject=missing, fields=[RevealField.STT_TRANSCRIPT.value])
    assert (await step_up(panel, subject=order_id)).status_code == 200
    after = (await post_reveal(panel, subject=order_id, fields=[RevealField.NOTE.value])).json()[
        "budget"
    ]["recordsRemaining"]

    # Assert — the 404 read nothing back, but it *was* authorised to, so its charge stands.
    # What the budget measures is what an operator was permitted to see.
    assert refused.status_code == 404
    assert after == before - 1 - MAX_RECORDS_PER_REVEAL
