"""``/orders`` over the real ASGI stack — the real container, the real login, the real guard.

Two assertions carry this file, and the rest of it exists to keep them honest.

**The purged order must be readable.** ``mapping.to_order`` raises ``PipelineError`` when
``recipient_name_display IS NULL`` (``db/mapping.py:137-147``), which is exactly what the
90-day identity sweep leaves behind — so a router that reached for the repository would fail
a whole page because one lawfully erased row was on it, and the 404 would land on the record
a data-subject request is about. ``test_a_page_containing_an_identity_purged_order_...`` and
its detail twin are the regression that pins the router to :mod:`hbd.db.admin.orders`.

**The plaintext name must never be in the bytes.** §12.3 is a rule about the payload, not
about what the SPA renders, so the assertion is a substring search over the whole response
body — at every one of the four roles, because §12.2 gives ``RECORDS_READ`` as **M** to all
of them and there is no unmasked variant in this slice. The fixture name is ``Gʻulom``, whose
U+02BB is the character a byte-wise mask would split; ``G•••`` is the only form allowed out.

There is no "a role without the permission is 403" test, because no such role exists: the
matrix row grants ``RECORDS_READ`` to VIEWER, SUPPORT, ADMIN and OWNER alike. The 403 this
router can actually produce is the forced-rotation gate, and that is the one asserted.

The orders router is mounted here rather than assumed: ``create_app`` wires it in a later
step of this slice, so the fixture below includes it only when the factory has not already.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin.container import AdminContainer
from hbd.admin.routers.orders import (
    ORDER_ASSETS_PATH,
    ORDER_ATTEMPTS_PATH,
    ORDER_STATE_COUNTS_PATH,
    ORDER_TIMELINE_PATH,
    ORDERS_PATH,
)
from hbd.contracts import (
    AssetKind,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    VoiceGender,
)
from hbd.db.admin.sql import MAX_SEARCH_CHARS
from hbd.db.base import utc_now
from hbd.db.credits import unenforced_key_prefix
from hbd.db.enums import AdminRole, CreditEntryKind, CreditReason, GenerationKind
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.credit_ledger import CreditLedgerRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.retention import RetentionClass
from tests.test_admin.conftest import NOW, PASSWORD, create_account, sign_in

#: The name the whole privacy assertion is written around. U+02BB MODIFIER LETTER TURNED
#: COMMA is a code point of its own and a grapheme cluster of its own, so a mask that cut at
#: a byte would emit half of it and a mask that cut at two clusters would leak ``Gʻ``.
PLAINTEXT_NAME: Final[str] = "Gʻulom"
MASKED_NAME: Final[str] = "G•••"
#: The customer's free text about a real third party. §12.3 exposes it as a length only, so
#: this string is asserted absent from every body the same way the name is.
PLAINTEXT_NOTE: Final[str] = "Loves the mountains above Chimgan."
#: A transcript is a near-verbatim copy of the sung lyric — the same rule, a different table.
PLAINTEXT_TRANSCRIPT: Final[str] = "Gʻulom, happy birthday to you"

TELEGRAM_ID: Final[int] = 99_000_111
MASKED_TELEGRAM_ID: Final[str] = "•••••111"
FAR_FUTURE: Final[datetime] = datetime(2027, 1, 1, tzinfo=UTC)
PURGED_AT: Final[datetime] = NOW - timedelta(days=1)

_ROLES: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)


# ---------------------------------------------------------------------------
# Seeding — real models, explicit values, no clocks and no policies
# ---------------------------------------------------------------------------
async def seed_user(session: AsyncSession, *, telegram_user_id: int = TELEGRAM_ID) -> UserRow:
    """Get or create.

    ``users.telegram_user_id`` is unique and most tests want one customer with several
    orders, so a fresh row per order would be a UNIQUE violation dressed up as a fixture.
    """
    existing = (
        await session.execute(
            sa.select(UserRow).where(UserRow.telegram_user_id == telegram_user_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        ui_language=Language.UZ_LATN,
        is_blocked=False,
        last_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_order(session: AsyncSession, *, user: UserRow, **kw: Any) -> OrderRow:
    created_at = kw.pop("created_at", NOW)
    row = OrderRow(
        id=kw.pop("id", uuid4()),
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        state=kw.pop("state", OrderState.DELIVERED),
        correlation_id=kw.pop("correlation_id", "corr-default"),
        is_paid=kw.pop("is_paid", True),
        delivered_at=kw.pop("delivered_at", None),
        failed_reason=kw.pop("failed_reason", None),
        created_at=created_at,
        updated_at=kw.pop("updated_at", created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_brief(session: AsyncSession, *, order: OrderRow, **kw: Any) -> BriefRow:
    """A brief. Pass ``recipient_name_display=None`` plus ``identity_purged_at`` for a purge."""
    row = BriefRow(
        id=uuid4(),
        order_id=order.id,
        occasion=kw.pop("occasion", Occasion.BIRTHDAY),
        genre=kw.pop("genre", Genre.UZBEK_POP),
        vocal_gender=VoiceGender.FEMALE,
        ui_language=Language.UZ_LATN,
        output_language=kw.pop("output_language", Language.UZ_LATN),
        note=kw.pop("note", PLAINTEXT_NOTE),
        approved_lyrics=kw.pop("approved_lyrics", None),
        note_expires_at=kw.pop("note_expires_at", FAR_FUTURE),
        note_purged_at=kw.pop("note_purged_at", None),
        recipient_name_raw=kw.pop("recipient_name_raw", PLAINTEXT_NAME),
        recipient_name_display=kw.pop("recipient_name_display", PLAINTEXT_NAME),
        recipient_lookup_key=kw.pop("recipient_lookup_key", "gulom"),
        recipient_script=Script.LATIN,
        recipient_language=Language.UZ_LATN,
        recipient_candidates=kw.pop("recipient_candidates", [{"text": "Gulom", "rank": 0}]),
        identity_expires_at=kw.pop("identity_expires_at", FAR_FUTURE),
        identity_purged_at=kw.pop("identity_purged_at", None),
        event_day=12,
        event_month=5,
        created_at=order.created_at,
        updated_at=order.created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def seed_purged_brief(session: AsyncSession, *, order: OrderRow) -> BriefRow:
    """What the 90-day sweep leaves: no identity columns, and the proof it was erased."""
    return await seed_brief(
        session,
        order=order,
        recipient_name_raw=None,
        recipient_name_display=None,
        recipient_lookup_key=None,
        recipient_candidates=None,
        identity_purged_at=PURGED_AT,
        note=None,
        note_purged_at=PURGED_AT,
    )


async def seed_asset(session: AsyncSession, *, order: OrderRow, **kw: Any) -> AssetRow:
    row = AssetRow(
        id=uuid4(),
        order_id=order.id,
        kind=kw.pop("kind", AssetKind.SONG),
        variant_index=kw.pop("variant_index", 0),
        path="/var/kits/song.mp3",
        storage_key=kw.pop("storage_key", None),
        mime="audio/mpeg",
        size_bytes=1_024,
        duration_s=90.0,
        sha256="a" * 64,
        loudness_lufs=-14.0,
        tg_file_id=kw.pop("tg_file_id", None),
        name_candidate_strategy=NameStrategy.STRIPPED,
        name_candidate_rank=0,
        retention_class=RetentionClass.PAID_AUDIO,
        expires_at=FAR_FUTURE,
        created_at=kw.pop("created_at", order.created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_attempt(
    session: AsyncSession, *, order: OrderRow, **kw: Any
) -> GenerationAttemptRow:
    row = GenerationAttemptRow(
        id=uuid4(),
        order_id=order.id,
        kind=kw.pop("kind", GenerationKind.SONG),
        sequence=kw.pop("sequence", 0),
        attempt=kw.pop("attempt", 0),
        provider=kw.pop("provider", "elevenlabs"),
        provider_remote_id=None,
        language=Language.UZ_LATN,
        is_success=kw.pop("is_success", True),
        name_candidate_strategy=kw.pop("name_candidate_strategy", None),
        name_candidate_rank=kw.pop("name_candidate_rank", None),
        is_name_verified=None,
        match_confidence=None,
        name_candidate_text=kw.pop("name_candidate_text", None),
        stt_transcript=kw.pop("stt_transcript", None),
        error_code=kw.pop("error_code", None),
        error_message=kw.pop("error_message", None),
        cost_usd=kw.pop("cost_usd", 0.0),
        latency_ms=kw.pop("latency_ms", 0),
        identity_expires_at=FAR_FUTURE,
        identity_purged_at=None,
        text_expires_at=FAR_FUTURE,
        text_purged_at=None,
        created_at=kw.pop("created_at", order.created_at),
    )
    session.add(row)
    await session.flush()
    return row


async def seed_named_order(container: AdminContainer, **kw: Any) -> UUID:
    """One delivered order with a named brief, an asset and a successful attempt."""
    async with container.session_factory.begin() as session:
        user = await seed_user(session)
        order = await seed_order(session, user=user, **kw)
        await seed_brief(session, order=order)
        await seed_asset(session, order=order)
        await seed_attempt(session, order=order, name_candidate_text=PLAINTEXT_NAME)
        return order.id


async def seed_purged_order(container: AdminContainer) -> UUID:
    """One order past the 90-day identity clock — the row ``to_order`` cannot read at all."""
    async with container.session_factory.begin() as session:
        user = await seed_user(session, telegram_user_id=TELEGRAM_ID + 1)
        order = await seed_order(
            session, user=user, created_at=NOW - timedelta(days=100), correlation_id="corr-old"
        )
        await seed_purged_brief(session, order=order)
        return order.id


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole = AdminRole.ADMIN
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


def detail_path(order_id: UUID) -> str:
    return f"{ORDERS_PATH}/{order_id}"


def sub_path(order_id: UUID, suffix: str) -> str:
    return f"{ORDERS_PATH}/{order_id}/{suffix}"


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
async def test_an_unauthenticated_caller_gets_401_not_a_page_of_orders(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_named_order(container)

    # Act
    response = await client.get(ORDERS_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("role", _ROLES)
async def test_every_role_in_the_matrix_row_may_read_the_list(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RECORDS_READ as M to all four roles.
    await seed_named_order(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(ORDERS_PATH)

    # Assert
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_an_operator_owing_a_password_change_is_refused_the_records(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the only 403 this router can produce: every role holds RECORDS_READ, so the
    # forced-rotation gate (§12.6) is what closes the panel to a credential somebody else chose.
    await seed_named_order(container)
    await create_account(container, username="rotating", must_change_password=True)
    assert (await sign_in(client, username="rotating", password=PASSWORD)).status_code == 200

    # Act
    response = await client.get(ORDERS_PATH)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "password_change_required"


# ---------------------------------------------------------------------------
# The trap this router exists to avoid
# ---------------------------------------------------------------------------
async def test_a_page_containing_an_identity_purged_order_returns_it_rather_than_failing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one named order and one the 90-day sweep has erased, on the same page.
    await seed_named_order(container)
    purged_id = await seed_purged_order(container)
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_PATH)

    # Assert — the page is whole, and the purged row carries both halves of the story.
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert len(rows) == 2
    purged = rows[str(purged_id)]
    assert purged["recipientName"] is None
    assert purged["identityPurgedAt"] is not None
    assert purged["isIdentityPurged"] is True
    # "no name" and "name erased on schedule" are different facts, so the brief is still there.
    assert purged["isBriefPresent"] is True


async def test_the_detail_of_an_identity_purged_order_is_readable(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``get_order`` cannot read this row at all; ``get_order_detail`` must.
    purged_id = await seed_purged_order(container)
    await signed_in(container, client)

    # Act
    response = await client.get(detail_path(purged_id))

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["order"]["recipientName"] is None
    assert body["order"]["identityPurgedAt"] is not None
    assert body["brief"]["recipientName"] is None
    assert body["brief"]["identityPurgedAt"] is not None
    assert body["brief"]["isIdentityPurged"] is True
    # Both clocks are on the wire, because a brief can be past one and not the other.
    assert body["brief"]["notePurgedAt"] is not None
    assert body["brief"]["noteChars"] is None


# ---------------------------------------------------------------------------
# §12.3 — what is not in the bytes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", _ROLES)
async def test_the_plaintext_recipient_name_is_absent_from_every_body_at_every_role(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — RECORDS_READ is M for all four roles and has no unmasked variant in this
    # slice, so OWNER is asserted exactly as hard as VIEWER.
    order_id = await seed_named_order(container)
    await signed_in(container, client, role=role)
    paths = [
        ORDERS_PATH,
        detail_path(order_id),
        sub_path(order_id, "attempts"),
        sub_path(order_id, "assets"),
        sub_path(order_id, "timeline"),
    ]

    # Act
    bodies = {path: (await client.get(path)).text for path in paths}

    # Assert — a substring search over the payload, because §12.3 is a rule about bytes.
    for path, body in bodies.items():
        assert PLAINTEXT_NAME not in body, path
        assert PLAINTEXT_NOTE not in body, path
    assert MASKED_NAME in bodies[ORDERS_PATH]
    assert MASKED_NAME in bodies[detail_path(order_id)]
    # The attempt's candidate orthography is a name too, and is masked by the same rule.
    assert MASKED_NAME in bodies[sub_path(order_id, "attempts")]


async def test_the_telegram_id_travels_masked_beside_the_raw_one(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the id itself is the join key an operator pastes into a ticket, so it stays;
    # the masked form is what the list renders (§12.3).
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]

    # Assert
    assert row["telegramUserId"] == TELEGRAM_ID
    assert row["telegramUserIdMasked"] == MASKED_TELEGRAM_ID


async def test_free_text_is_a_length_and_a_flag_rather_than_a_value(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order_id = await seed_named_order(container)
    async with container.session_factory.begin() as session:
        order = await session.get(OrderRow, order_id)
        assert order is not None
        await seed_attempt(
            session,
            order=order,
            sequence=1,
            kind=GenerationKind.NAME_VERIFICATION,
            stt_transcript=PLAINTEXT_TRANSCRIPT,
        )
    await signed_in(container, client)

    # Act
    body = (await client.get(detail_path(order_id))).json()

    # Assert
    assert body["brief"]["noteChars"] == len(PLAINTEXT_NOTE)
    assert body["brief"]["hasApprovedLyrics"] is False
    transcribed = [a for a in body["attempts"] if a["sttTranscriptChars"] is not None]
    assert [a["sttTranscriptChars"] for a in transcribed] == [len(PLAINTEXT_TRANSCRIPT)]
    assert PLAINTEXT_TRANSCRIPT not in (await client.get(detail_path(order_id))).text


async def test_uninstrumented_cost_and_latency_are_null_rather_than_zero(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the columns default to 0.0 and 0 and nothing writes them yet. Rendering
    # "$0.00" on the screen an operator uses to decide what to spend would be a lie.
    order_id = await seed_named_order(container)
    await signed_in(container, client)

    # Act
    attempt = (await client.get(sub_path(order_id, "attempts"))).json()["items"][0]

    # Assert
    assert attempt["costUsd"] is None
    assert attempt["latencyMs"] is None
    assert attempt["isInstrumented"] is False


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------
async def test_the_list_row_carries_the_triage_columns_an_operator_sorts_on(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order_id = await seed_named_order(
        container, state=OrderState.DELIVERED, delivered_at=NOW, correlation_id="corr-abc"
    )
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]

    # Assert
    assert row["id"] == str(order_id)
    assert row["state"] == OrderState.DELIVERED.value
    assert row["isPaid"] is True
    assert row["correlationId"] == "corr-abc"
    assert row["recipientName"] == MASKED_NAME
    assert row["occasion"] == Occasion.BIRTHDAY.value
    assert row["assetCount"] == 1
    assert row["hasAssets"] is True
    assert row["failedReason"] is None
    assert row["isFailedReasonRetryable"] is None


async def test_the_detail_assembles_the_brief_assets_attempts_plan_and_timeline(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order_id = await seed_named_order(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(detail_path(order_id))).json()

    # Assert
    assert body["order"]["id"] == str(order_id)
    assert body["brief"]["occasion"] == Occasion.BIRTHDAY.value
    assert len(body["assets"]) == 1
    assert len(body["attempts"]) == 1
    # The plan is deduced from attempts, assets and four mutable timestamps — never claimed.
    assert body["stagePlan"]["isInferred"] is True
    assert body["timeline"]["events"]
    assert "audit" in body["timeline"]["unavailableSources"]


async def test_the_timeline_route_returns_the_same_events_as_the_detail(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order_id = await seed_named_order(container)
    await signed_in(container, client)

    # Act
    standalone = (await client.get(sub_path(order_id, "timeline"))).json()
    embedded = (await client.get(detail_path(order_id))).json()["timeline"]

    # Assert
    assert standalone == embedded
    assert standalone["availableSources"] == ["order", "attempts", "assets"]


async def test_the_asset_page_reports_an_unrecorded_storage_key_rather_than_hiding_it(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — today's real shape: ``_replace_assets`` does not write ``storage_key`` yet,
    # so the sweep has no key to hand the archive and the bytes outlive the row.
    order_id = await seed_named_order(container)
    await signed_in(container, client)

    # Act
    asset = (await client.get(sub_path(order_id, "assets"))).json()["items"][0]

    # Assert
    assert asset["orderId"] == str(order_id)
    assert asset["kind"] == AssetKind.SONG.value
    assert asset["isStorageKeyRecorded"] is False
    assert asset["hasTelegramFileId"] is False
    assert "path" not in asset


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("suffix", ["", "timeline"])
async def test_an_unknown_order_id_is_a_404_in_the_error_envelope(
    container: AdminContainer, client: httpx.AsyncClient, suffix: str
) -> None:
    # Arrange
    await signed_in(container, client)
    unknown = uuid4()
    path = detail_path(unknown) if not suffix else sub_path(unknown, suffix)

    # Act
    response = await client.get(path)

    # Assert
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "NOT_FOUND"
    # The envelope carries the correlation id the log line and the header carry.
    assert body["correlationId"]
    assert str(unknown) not in body["message"]


async def test_a_malformed_order_id_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``{order_id}`` is typed ``UUID``, so no query runs on a hand-typed path.
    await signed_in(container, client)

    # Act
    response = await client.get(f"{ORDERS_PATH}/not-a-uuid")

    # Assert
    assert response.status_code == 422


@pytest.mark.parametrize("suffix", ["attempts", "assets"])
async def test_a_sub_collection_of_an_unknown_order_is_an_empty_page_not_a_404(
    container: AdminContainer, client: httpx.AsyncClient, suffix: str
) -> None:
    # Arrange — these two are ``/attempts?orderId=`` with the scope in the path, so an empty
    # page is the right answer to a filter that matched nothing. Pinned because the opposite
    # choice is the tempting one and would cost a probe query on every page load.
    await signed_in(container, client)

    # Act
    response = await client.get(sub_path(uuid4(), suffix))

    # Assert
    assert response.status_code == 200
    assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
async def test_repeated_state_values_are_or_within_the_field(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    delivered = await seed_named_order(container, state=OrderState.DELIVERED)
    failed = await seed_named_order(
        container, state=OrderState.FAILED, failed_reason="PROVIDER_ERROR"
    )
    await seed_named_order(container, state=OrderState.DRAFT)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(ORDERS_PATH, params=[("state", "delivered"), ("state", "failed")])
    ).json()

    # Assert
    assert {row["id"] for row in body["items"]} == {str(delivered), str(failed)}


async def test_an_unknown_state_is_a_422_rather_than_a_filter_that_matches_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_PATH, params={"state": "refunded"})

    # Assert
    assert response.status_code == 422


async def test_the_scalar_filters_are_anded_across_fields(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    wanted = await seed_named_order(container, is_paid=True, correlation_id="corr-wanted")
    await seed_named_order(container, is_paid=False, correlation_id="corr-wanted")
    await seed_named_order(container, is_paid=True, correlation_id="corr-other")
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            ORDERS_PATH,
            params={
                "isPaid": "true",
                "correlationId": "corr-wanted",
                "telegramUserId": TELEGRAM_ID,
            },
        )
    ).json()

    # Assert
    assert [row["id"] for row in body["items"]] == [str(wanted)]


async def test_has_assets_reads_the_same_expression_the_column_reports(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the purged order has no asset row at all.
    with_assets = await seed_named_order(container)
    without = await seed_purged_order(container)
    await signed_in(container, client)

    # Act
    yes = (await client.get(ORDERS_PATH, params={"hasAssets": "true"})).json()
    no = (await client.get(ORDERS_PATH, params={"hasAssets": "false"})).json()

    # Assert
    assert [row["id"] for row in yes["items"]] == [str(with_assets)]
    assert [row["id"] for row in no["items"]] == [str(without)]


async def test_the_window_is_half_open_on_orders_created_at(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the row stamped exactly at ``to`` must fall outside, so consecutive windows
    # tile without both claiming it.
    inside = await seed_named_order(container, created_at=NOW - timedelta(hours=1))
    await seed_named_order(container, created_at=NOW)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(
            ORDERS_PATH,
            params={
                "from": (NOW - timedelta(days=1)).isoformat(),
                "to": NOW.isoformat(),
            },
        )
    ).json()

    # Assert
    assert [row["id"] for row in body["items"]] == [str(inside)]


async def test_a_naive_from_is_refused_rather_than_guessed_at(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``UtcDateTime.process_bind_param`` raises inside the driver, where no handler
    # is waiting, so the offset is demanded at the boundary instead (§6.1).
    await signed_in(container, client)

    # Act
    response = await client.get(
        ORDERS_PATH, params={"from": "2026-03-20T09:00:00", "to": NOW.isoformat()}
    )

    # Assert
    assert response.status_code == 422
    assert "UTC offset" in response.json()["error"]["message"]


async def test_a_from_with_no_to_runs_to_the_moment_the_request_was_served(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — "since X, until now" is the range every date picker produces and it used to be
    # a 422 (AUDIT_AND_REDESIGN §2.2). ``NOW`` is a fixed instant in the past, so the upper
    # bound the server supplies is strictly later than both rows.
    old = await seed_named_order(container, created_at=NOW - timedelta(days=30))
    recent = await seed_named_order(container, created_at=NOW)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(ORDERS_PATH, params={"from": (NOW - timedelta(days=1)).isoformat()})
    ).json()

    # Assert — the older row is excluded by the bound the caller gave, not by the one the
    # server chose, which is what proves the default end is "now" and not "the epoch".
    ids = [row["id"] for row in body["items"]]
    assert ids == [str(recent)]
    assert str(old) not in ids


async def test_a_to_with_no_from_leaves_the_lower_bound_off_the_query(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the mirror case: no invented epoch, just no lower predicate at all.
    old = await seed_named_order(container, created_at=NOW - timedelta(days=30))
    await seed_named_order(container, created_at=NOW)
    await signed_in(container, client)

    # Act
    body = (
        await client.get(ORDERS_PATH, params={"to": (NOW - timedelta(days=1)).isoformat()})
    ).json()

    # Assert
    assert [row["id"] for row in body["items"]] == [str(old)]


async def test_a_from_in_the_future_is_refused_by_the_ordering_check(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an open-ended window still ends at ``now``, so "since next year" is a window
    # that ends before it starts rather than a page of nothing to misread.
    await signed_in(container, client)

    # Act
    future = utc_now() + timedelta(days=365)
    response = await client.get(ORDERS_PATH, params={"from": future.isoformat()})

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_a_window_that_ends_before_it_starts_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(
        ORDERS_PATH,
        params={"from": NOW.isoformat(), "to": (NOW - timedelta(days=1)).isoformat()},
    )

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------
async def test_a_page_hands_back_a_cursor_that_fetches_the_rest(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — newest first, so the cursor walks backwards through time.
    for hour in range(3):
        await seed_named_order(container, created_at=NOW - timedelta(hours=hour))
    await signed_in(container, client)

    # Act
    first = (await client.get(ORDERS_PATH, params={"limit": 2})).json()
    second = (
        await client.get(ORDERS_PATH, params={"limit": 2, "cursor": first["meta"]["nextCursor"]})
    ).json()

    # Assert
    assert len(first["items"]) == 2
    assert first["meta"]["nextCursor"]
    assert len(second["items"]) == 1
    # Nothing else means "the end", so a client's loop terminates on one condition.
    assert second["meta"]["nextCursor"] is None
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}


async def test_the_total_is_absent_unless_it_was_asked_for_and_travels_with_its_exactness(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — ``total`` alone would be read as a measurement when it is a ceiling.
    await seed_named_order(container)
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    without = (await client.get(ORDERS_PATH)).json()["meta"]
    with_total = (await client.get(ORDERS_PATH, params={"withTotal": "true"})).json()["meta"]

    # Assert
    assert without["total"] is None
    assert without["isTotalExact"] is None
    assert with_total["total"] == 2
    assert with_total["isTotalExact"] is True


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_a_limit_outside_the_bounds_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient, limit: int
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_PATH, params={"limit": limit})

    # Assert
    assert response.status_code == 422


async def test_a_cursor_this_endpoint_did_not_issue_is_refused(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_PATH, params={"cursor": "not-a-cursor"})

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The sub-collections
# ---------------------------------------------------------------------------
async def test_the_attempt_page_is_scoped_to_the_order_and_filtered_by_kind_and_outcome(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one order with three attempts, and a second order whose rows must not leak in.
    order_id = await seed_named_order(container)
    async with container.session_factory.begin() as session:
        order = await session.get(OrderRow, order_id)
        assert order is not None
        await seed_attempt(session, order=order, sequence=1, kind=GenerationKind.GREETING)
        await seed_attempt(
            session,
            order=order,
            sequence=2,
            kind=GenerationKind.SONG,
            is_success=False,
            error_code="PROVIDER_ERROR",
        )
    await seed_named_order(container, correlation_id="corr-other")
    await signed_in(container, client)

    # Act
    everything = (await client.get(sub_path(order_id, "attempts"))).json()
    songs = (
        await client.get(sub_path(order_id, "attempts"), params={"kind": GenerationKind.SONG.value})
    ).json()
    failures = (
        await client.get(sub_path(order_id, "attempts"), params={"isSuccess": "false"})
    ).json()

    # Assert
    assert len(everything["items"]) == 3
    assert {a["kind"] for a in songs["items"]} == {GenerationKind.SONG.value}
    assert len(failures["items"]) == 1
    assert failures["items"][0]["errorCode"] == "PROVIDER_ERROR"
    assert failures["items"][0]["orderId"] == str(order_id)


async def test_the_asset_page_is_scoped_to_the_order(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    order_id = await seed_named_order(container)
    async with container.session_factory.begin() as session:
        order = await session.get(OrderRow, order_id)
        assert order is not None
        await seed_asset(session, order=order, kind=AssetKind.GREETING, variant_index=1)
    await seed_named_order(container, correlation_id="corr-other")
    await signed_in(container, client)

    # Act
    body = (await client.get(sub_path(order_id, "assets"), params={"withTotal": "true"})).json()

    # Assert
    assert {asset["orderId"] for asset in body["items"]} == {str(order_id)}
    assert body["meta"]["total"] == 2


async def test_the_declared_paths_are_the_ones_the_router_serves(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the forced-rotation gate compares ``scope["route"].path`` against absolute
    # paths, so a router included with a prefix would open it silently.
    order_id = await seed_named_order(container)
    await signed_in(container, client)
    formatted = {
        ORDER_ATTEMPTS_PATH: sub_path(order_id, "attempts"),
        ORDER_ASSETS_PATH: sub_path(order_id, "assets"),
        ORDER_TIMELINE_PATH: sub_path(order_id, "timeline"),
    }

    # Act / Assert
    assert all(declared.startswith(ORDERS_PATH) for declared in formatted)
    for declared, concrete in formatted.items():
        assert declared.format(order_id=order_id) == concrete
        assert (await client.get(concrete)).status_code == 200


# ---------------------------------------------------------------------------
# Financials on the wire — §5.1 of the audit plan, minus the two rails it invented
# ---------------------------------------------------------------------------
async def seed_ledger_entry(session: AsyncSession, **kw: Any) -> CreditLedgerRow:
    """One ``credit_ledger`` row, by hand.

    Not through ``credits.charge``: that writer takes a policy and a clock, opens its own
    balance row and decides the generation itself, and every assertion below is about an
    exact ledger shape rather than about what the entitlement subsystem would have chosen.
    """
    row = CreditLedgerRow(
        id=uuid4(),
        telegram_user_id=kw.pop("telegram_user_id", TELEGRAM_ID),
        kind=kw.pop("kind"),
        reason=kw.pop("reason"),
        delta=kw.pop("delta"),
        order_id=kw.pop("order_id", None),
        generation=kw.pop("generation", 0),
        idempotency_key=kw.pop("idempotency_key"),
        actor=kw.pop("actor", "pipeline"),
        created_at=kw.pop("created_at", NOW),
    )
    session.add(row)
    await session.flush()
    return row


async def charge_order(container: AdminContainer, order_id: UUID, *, comped: bool = False) -> None:
    """Debit the order and settle it, exactly as the gate and the worker would.

    ``comped`` adds the dark-switch top-up ``credits._cover_the_shortfall`` writes when
    ``credits_enforced`` is off — the row that carries no ``order_id`` and is therefore
    findable only by its idempotency key.
    """
    async with container.session_factory.begin() as session:
        if comped:
            await seed_ledger_entry(
                session,
                kind=CreditEntryKind.GRANT,
                reason=CreditReason.UNENFORCED_RENDER,
                delta=1,
                idempotency_key=f"{unenforced_key_prefix(order_id)}0",
                actor="unenforced",
            )
        await seed_ledger_entry(
            session,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=-1,
            order_id=order_id,
            idempotency_key=f"debit:{order_id}:0",
        )
        await seed_ledger_entry(
            session,
            kind=CreditEntryKind.CONSUME,
            reason=CreditReason.ORDER_DELIVERED,
            delta=0,
            order_id=order_id,
            idempotency_key=f"consume:{order_id}:0",
        )


async def test_an_order_nobody_charged_reports_no_cost_and_no_rail(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``creditCost: 0`` with ``ledgerStatus: "unmetered"`` — not "free", and not "pending".

    ``credits_enforced`` ships ``False`` and a DRAFT never reaches the gate, so this is the
    ordinary case rather than the corner, and it is the case the audit plan's three-value
    ``ledgerStatus`` had no member for.
    """
    # Arrange
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]

    # Assert
    assert row["creditCost"] == 0
    assert row["ledgerStatus"] == "unmetered"
    assert row["paymentRail"] == "none"


async def test_a_settled_order_reports_what_it_cost_on_the_list_and_on_the_detail(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """One answer from two code paths. A detail screen that skipped a query would disagree."""
    # Arrange
    order_id = await seed_named_order(container)
    await charge_order(container, order_id)
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]
    detail = (await client.get(detail_path(order_id))).json()["order"]

    # Assert
    assert row == detail
    assert (row["creditCost"], row["ledgerStatus"], row["paymentRail"]) == (
        1,
        "settled",
        "credits",
    )


async def test_a_refunded_order_reports_zero_because_zero_is_what_makes_it_chargeable_again(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The one number a "sum of the debits" would get wrong on the screen an operator acts on.

    A refund returns the order to net 0, and net 0 is precisely what lets the gate charge it
    again at ``generation + 1``. Reporting the debit that was handed back as a cost would have
    an operator refunding a credit the customer already has.
    """
    # Arrange
    order_id = await seed_named_order(container, state=OrderState.FAILED)
    async with container.session_factory.begin() as session:
        await seed_ledger_entry(
            session,
            kind=CreditEntryKind.DEBIT,
            reason=CreditReason.ORDER_RENDER,
            delta=-1,
            order_id=order_id,
            idempotency_key=f"debit:{order_id}:0",
        )
        await seed_ledger_entry(
            session,
            kind=CreditEntryKind.REFUND,
            reason=CreditReason.ORDER_FAILED,
            delta=1,
            order_id=order_id,
            idempotency_key=f"refund:{order_id}:0",
        )
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]

    # Assert
    assert row["creditCost"] == 0
    assert row["ledgerStatus"] == "refunded"
    # Still ``credits``: money moved for this order, it simply moved back.
    assert row["paymentRail"] == "credits"


async def test_a_comped_render_is_labelled_unenforced_rather_than_paid(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The rail the ledger's ``order_id`` column cannot see, and the deployment's default.

    Both orders below are ``settled`` with a cost of 1. Only the rail says that one customer's
    balance paid and the other was topped up to the exact cost by a configuration flag.
    """
    # Arrange
    comped_id = await seed_named_order(container, correlation_id="corr-comped")
    paid_id = await seed_named_order(container, correlation_id="corr-paid")
    await charge_order(container, comped_id, comped=True)
    await charge_order(container, paid_id)
    await signed_in(container, client)

    # Act
    rows = {row["id"]: row for row in (await client.get(ORDERS_PATH)).json()["items"]}

    # Assert
    assert rows[str(comped_id)]["ledgerStatus"] == rows[str(paid_id)]["ledgerStatus"] == "settled"
    assert rows[str(comped_id)]["paymentRail"] == "unenforced"
    assert rows[str(paid_id)]["paymentRail"] == "credits"


async def test_the_retry_count_reports_attempt_rows_and_says_nothing_about_renders(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``retryCount`` counts rows in ``generation_attempts`` — today, verification verdicts.

    ``seed_named_order`` writes exactly one attempt row, so the field reads ``1`` for a single
    clean run rather than ``0``: it is not "retries beyond the first". No vendor-render attempt
    writer exists in ``src/`` at all, which is why the wire docstring forbids the SPA from
    labelling this "render retries".
    """
    # Arrange
    order_id = await seed_named_order(container)
    async with container.session_factory.begin() as session:
        order = await session.get(OrderRow, order_id)
        assert order is not None
        await seed_attempt(
            session, order=order, kind=GenerationKind.NAME_VERIFICATION, attempt=1, is_success=False
        )
    await signed_in(container, client)

    # Act
    row = (await client.get(ORDERS_PATH)).json()["items"][0]

    # Assert
    assert row["retryCount"] == 2


# ---------------------------------------------------------------------------
# ``/orders/state-counts`` — the distribution bar, over the dataset rather than the page
# ---------------------------------------------------------------------------
async def test_the_state_counts_describe_the_dataset_and_not_the_page(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The bug the route exists for: a bar summarising the fifty rows the browser happens to hold."""
    # Arrange — three orders, two states, and a page that can only show one of them.
    await seed_named_order(container, correlation_id="corr-1")
    await seed_named_order(container, correlation_id="corr-2")
    await seed_named_order(container, correlation_id="corr-3", state=OrderState.FAILED)
    await signed_in(container, client)

    # Act
    page = (await client.get(ORDERS_PATH, params={"limit": 1})).json()
    body = (await client.get(ORDER_STATE_COUNTS_PATH)).json()

    # Assert
    assert len(page["items"]) == 1
    counts = {entry["state"]: entry["count"] for entry in body["counts"]}
    assert counts[OrderState.DELIVERED.value] == 2
    assert counts[OrderState.FAILED.value] == 1
    assert body["total"] == 3


async def test_the_state_counts_are_zero_filled_over_every_state(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """Every segment, always, in enum order — a bar that does not re-lay-out as data arrives."""
    # Arrange
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(ORDER_STATE_COUNTS_PATH)).json()

    # Assert
    assert [entry["state"] for entry in body["counts"]] == [state.value for state in OrderState]
    assert body["total"] == 1


async def test_the_state_counts_take_the_same_filters_as_the_list(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """It answers for exactly the rows the list would return for the same query string.

    Asserted against the list's own ``?withTotal=true`` rather than against a hand-counted
    number, because the property that matters is that the two agree: a bar computed from a
    population the table is not showing is the failure this route was added to fix.
    """
    # Arrange
    await seed_named_order(container, correlation_id="corr-kept")
    await seed_named_order(container, correlation_id="corr-dropped", state=OrderState.FAILED)
    await signed_in(container, client)
    narrowed = {"state": OrderState.DELIVERED.value}

    # Act
    listed = (await client.get(ORDERS_PATH, params={**narrowed, "withTotal": "true"})).json()
    body = (await client.get(ORDER_STATE_COUNTS_PATH, params=narrowed)).json()

    # Assert
    counts = {entry["state"]: entry["count"] for entry in body["counts"]}
    assert body["total"] == listed["meta"]["total"] == 1
    assert counts[OrderState.DELIVERED.value] == 1
    # The state filter narrows this endpoint too, which is what "same filter set" means.
    assert counts[OrderState.FAILED.value] == 0


async def test_the_state_counts_route_needs_a_session_like_every_other_record_read(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await seed_named_order(container)

    # Act
    response = await client.get(ORDER_STATE_COUNTS_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# ``?q=`` — the identifiers an operator has, and the name they must not get this way
# ---------------------------------------------------------------------------
async def test_the_search_matches_the_correlation_id_the_telegram_id_and_a_whole_order_id(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    wanted = await seed_named_order(container, correlation_id="req-9f201abc")
    await seed_named_order(container, correlation_id="req-000zzz")
    await signed_in(container, client)

    # Act
    async def ids(query: str) -> list[str]:
        body = (await client.get(ORDERS_PATH, params={"q": query})).json()
        return [row["id"] for row in body["items"]]

    # Assert — a fragment of the correlation id, the caller's own Telegram id, a whole
    # order id. All three are printed unmasked in this very response, so matching a
    # substring of them discloses nothing the caller was not already handed.
    assert await ids("9f201") == [str(wanted)]
    assert await ids(str(wanted)) == [str(wanted)]
    assert len(await ids(str(TELEGRAM_ID)[-6:])) == 2
    # A search box that has not been typed into must not empty the table.
    assert len(await ids("   ")) == 2


async def test_the_search_does_not_reach_the_recipient_name(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """A reveal bypass if it regresses: the plaintext costs a step-up, an audit row and a budget."""
    # Arrange
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    body = (await client.get(ORDERS_PATH, params={"q": PLAINTEXT_NAME})).json()

    # Assert
    assert body["items"] == []


async def test_an_over_long_search_is_a_422_naming_the_parameter(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """The cap is declared on the route, not left to the query layer's silent truncation.

    ``search_clause`` truncates as a backstop, and a truncated substring pattern *widens*:
    an operator who pasted a wall of text would get extra rows with nothing on the page to
    explain them. The boundary refuses instead, and names ``q`` while doing it.
    """
    # Arrange
    await seed_named_order(container)
    await signed_in(container, client)

    # Act
    response = await client.get(ORDERS_PATH, params={"q": "x" * (MAX_SEARCH_CHARS + 1)})

    # Assert
    assert response.status_code == 422
    assert "q" in str(response.json()["error"]["details"])
