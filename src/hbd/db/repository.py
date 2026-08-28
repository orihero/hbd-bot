"""``SqlKitRepository`` — the ``KitRepository`` protocol over Postgres (or SQLite in tests).

Three things this class is careful about, because each of them is a bug that only appears
in production:

* **One transaction per public method.** ``session_factory.begin()`` commits on a clean
  exit and rolls back on any exception, so a half-written kit is impossible.
* **No lazy loads.** Every relationship on every model is ``lazy="raise"``; the reads here
  fetch what they need explicitly. An implicit load inside async SQLAlchemy fails with a
  greenlet error at an unrelated await, which is a miserable thing to debug.
* **Writes are idempotent.** ARQ retries jobs. ``save_kit`` replaces an order's assets
  rather than appending to them, so a retried delivery does not leave six greetings on a
  three-greeting kit.

The retention clock is stamped here and only here, on the way in, from
:class:`hbd.db.retention.RetentionPolicy`. The purge job never recomputes it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import (
    AssetKind,
    GeneratedAsset,
    Kit,
    NameVerdict,
    Order,
    OrderState,
    Result,
)
from hbd.db.attempts import name_verdicts_from_rows, verdict_row_values
from hbd.db.base import utc_now
from hbd.db.enums import GenerationKind
from hbd.db.guard import not_found, run_guarded
from hbd.db.mapping import (
    asset_name_candidate_values,
    brief_identity_values,
    lyrics_from_payload,
    lyrics_to_payload,
    payload_for,
    to_generated_asset,
    to_order,
)
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionClass, RetentionPolicy

__all__ = ["SqlKitRepository", "MAX_ORDER_HISTORY"]

#: Hard ceiling on ``list_orders_for_user`` regardless of what the caller asks for.
#: An unbounded query against a user's history is exactly the shape that takes a
#: database down the first time someone with 4,000 orders opens ``/orders``.
MAX_ORDER_HISTORY: int = 100

#: States at or beyond which the order counts as paid for retention purposes.
_PAID_STATES: frozenset[OrderState] = frozenset(
    {OrderState.AUTHORIZED, OrderState.GENERATING, OrderState.DELIVERED}
)


class SqlKitRepository:
    """Structural implementation of ``hbd.contracts.KitRepository``.

    Deliberately not a subclass: the protocol is ``@runtime_checkable`` and satisfied
    structurally, so persistence does not have to import an ABC to be substitutable.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._policy = policy
        self._clock = clock

    # -- KitRepository ------------------------------------------------------
    async def create_order(self, order: Order) -> Result[Order]:
        return await run_guarded(
            "create_order", lambda: self._create_order(order), order_id=str(order.id)
        )

    async def get_order(self, order_id: UUID) -> Result[Order]:
        return await run_guarded(
            "get_order", lambda: self._get_order(order_id), order_id=str(order_id)
        )

    async def set_order_state(
        self, order_id: UUID, state: OrderState, *, now: datetime
    ) -> Result[Order]:
        return await run_guarded(
            "set_order_state",
            lambda: self._set_order_state(order_id, state, now),
            order_id=str(order_id),
            state=str(state),
        )

    async def save_kit(self, kit: Kit) -> Result[Kit]:
        return await run_guarded(
            "save_kit", lambda: self._save_kit(kit), order_id=str(kit.order_id)
        )

    async def get_kit(self, order_id: UUID) -> Result[Kit]:
        return await run_guarded("get_kit", lambda: self._get_kit(order_id), order_id=str(order_id))

    async def list_orders_for_user(
        self, telegram_user_id: int, *, limit: int
    ) -> Result[tuple[Order, ...]]:
        return await run_guarded(
            "list_orders_for_user",
            lambda: self._list_orders_for_user(telegram_user_id, limit),
            telegram_user_id=telegram_user_id,
        )

    # -- implementations ----------------------------------------------------
    async def _create_order(self, order: Order) -> Order:
        now = self._clock()
        async with self._sessions.begin() as session:
            user_id = await _ensure_user(session, order, now=now)
            session.add(
                OrderRow(
                    id=order.id,
                    user_id=user_id,
                    telegram_user_id=order.telegram_user_id,
                    state=order.state,
                    correlation_id=order.correlation_id,
                    is_paid=order.state in _PAID_STATES,
                    created_at=order.created_at,
                    updated_at=order.updated_at,
                )
            )
            session.add(self._new_brief_row(order, now=now))
        return order

    def _new_brief_row(self, order: Order, *, now: datetime) -> BriefRow:
        brief = order.brief
        return BriefRow(
            id=uuid4(),
            order_id=order.id,
            occasion=brief.occasion,
            genre=brief.genre,
            vocal_gender=brief.vocal_gender,
            ui_language=brief.ui_language,
            output_language=brief.output_language,
            note=brief.note or None,
            # The only write path for the approved lyric. The queue payload carries an
            # order id and nothing else, so whatever is missed here the worker will
            # silently rewrite — a different song from the one the customer approved.
            approved_lyrics=(
                lyrics_to_payload(brief.approved_lyrics)
                if brief.approved_lyrics is not None
                else None
            ),
            note_expires_at=self._policy.brief_text_expires_at(now),
            created_at=now,
            updated_at=now,
            **brief_identity_values(
                brief.recipient, expires_at=self._policy.identity_expires_at(now)
            ),
        )

    async def _get_order(self, order_id: UUID) -> Order:
        async with self._sessions.begin() as session:
            order_row, brief_row = await _load_order(session, order_id)
            return to_order(order_row, brief_row)

    async def _set_order_state(self, order_id: UUID, state: OrderState, now: datetime) -> Order:
        async with self._sessions.begin() as session:
            order_row, brief_row = await _load_order(session, order_id)
            order_row.state = state
            order_row.updated_at = now
            # Latch, never clear: a refunded or failed order still bought what it bought.
            order_row.is_paid = order_row.is_paid or state in _PAID_STATES
            if state is OrderState.DELIVERED:
                order_row.delivered_at = now
            return to_order(order_row, brief_row)

    async def _save_kit(self, kit: Kit) -> Kit:
        now = self._clock()
        async with self._sessions.begin() as session:
            order_row, brief_row = await _load_order(session, kit.order_id)
            retention_class = (
                RetentionClass.PAID_AUDIO if order_row.is_paid else RetentionClass.FREE_OUTPUT
            )
            expires_at = self._policy.expires_at(now, retention_class)

            await _replace_assets(
                session, kit, expires_at=expires_at, klass=retention_class, now=now
            )
            await _replace_verdicts(
                session,
                kit.order_id,
                kit.name_verdicts,
                identity_expires_at=self._policy.identity_expires_at(now),
                text_expires_at=self._policy.brief_text_expires_at(now),
                now=now,
            )
            # Delivery is the anchor FIL-7 measures the personal-data clocks from, and
            # save_kit is the moment delivery becomes real.
            brief_row.note_expires_at = self._policy.brief_text_expires_at(now)
            brief_row.identity_expires_at = self._policy.identity_expires_at(now)
        return kit

    async def _get_kit(self, order_id: UUID) -> Kit:
        async with self._sessions.begin() as session:
            await _load_order(session, order_id)
            asset_rows = (
                (
                    await session.execute(
                        sa.select(AssetRow)
                        .where(AssetRow.order_id == order_id)
                        .order_by(AssetRow.kind, AssetRow.variant_index)
                    )
                )
                .scalars()
                .all()
            )
            verdict_rows = (
                (
                    await session.execute(
                        sa.select(GenerationAttemptRow)
                        .where(
                            GenerationAttemptRow.order_id == order_id,
                            GenerationAttemptRow.kind == GenerationKind.NAME_VERIFICATION,
                        )
                        .order_by(GenerationAttemptRow.attempt)
                    )
                )
                .scalars()
                .all()
            )
            return _build_kit(order_id, asset_rows, verdict_rows)

    async def _list_orders_for_user(self, telegram_user_id: int, limit: int) -> tuple[Order, ...]:
        capped = max(1, min(limit, MAX_ORDER_HISTORY))
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    sa.select(OrderRow, BriefRow)
                    .join(BriefRow, BriefRow.order_id == OrderRow.id)
                    .where(OrderRow.telegram_user_id == telegram_user_id)
                    .order_by(OrderRow.created_at.desc())
                    .limit(capped)
                )
            ).all()
            return tuple(to_order(order_row, brief_row) for order_row, brief_row in rows)


# ---------------------------------------------------------------------------
# Session-level helpers. Free functions: they need a session, not a repository.
# ---------------------------------------------------------------------------
async def _ensure_user(session: AsyncSession, order: Order, *, now: datetime) -> UUID:
    """Find or create the user row. Returns its id.

    A user is created by whichever order arrives first; there is no separate sign-up.
    """
    existing = (
        await session.execute(
            sa.select(UserRow).where(UserRow.telegram_user_id == order.telegram_user_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.last_seen_at = now
        return existing.id
    user = UserRow(
        id=uuid4(),
        telegram_user_id=order.telegram_user_id,
        ui_language=order.brief.ui_language,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _load_order(session: AsyncSession, order_id: UUID) -> tuple[OrderRow, BriefRow]:
    """Load an order with its brief, or raise the standard not-found error."""
    row = (
        await session.execute(
            sa.select(OrderRow, BriefRow)
            .join(BriefRow, BriefRow.order_id == OrderRow.id)
            .where(OrderRow.id == order_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("order", order_id=str(order_id))
    order_row, brief_row = row
    return order_row, brief_row


async def _replace_assets(
    session: AsyncSession,
    kit: Kit,
    *,
    expires_at: datetime,
    klass: RetentionClass,
    now: datetime,
) -> None:
    """Delete this order's assets and write the kit's, so a retry cannot duplicate them."""
    await session.execute(sa.delete(AssetRow).where(AssetRow.order_id == kit.order_id))
    for asset, variant_index in _numbered(kit):
        session.add(
            AssetRow(
                id=uuid4(),
                order_id=kit.order_id,
                kind=asset.kind,
                variant_index=variant_index,
                path=str(asset.path),
                mime=asset.mime,
                duration_s=asset.duration_s,
                sha256=asset.sha256,
                loudness_lufs=asset.loudness_lufs,
                persona_id=asset.persona_id,
                payload=payload_for(asset, kit.lyrics),
                retention_class=klass,
                expires_at=expires_at,
                created_at=now,
                **asset_name_candidate_values(asset.name_candidate),
            )
        )


def _numbered(kit: Kit) -> Iterable[tuple[GeneratedAsset, int]]:
    """Assign ``variant_index`` per kind, so ``(order, kind, variant)`` stays unique."""
    counters: dict[AssetKind, int] = {}
    for asset in kit.all_assets:
        index = counters.get(asset.kind, 0)
        counters[asset.kind] = index + 1
        yield asset, index


async def _replace_verdicts(
    session: AsyncSession,
    order_id: UUID,
    verdicts: tuple[NameVerdict, ...],
    *,
    identity_expires_at: datetime,
    text_expires_at: datetime,
    now: datetime,
) -> None:
    """Rewrite this order's acoustic verdicts.

    Verdicts are stored as ``generation_attempts`` rows rather than as a JSON blob on the
    kit, because that table is what the name subsystem is tuned from. A verdict that only
    existed inside a kit would be invisible to the query that reorders
    ``HBD_NAME_CANDIDATE_ORDER``.

    Two clocks are stamped, not one. ``stt_transcript`` is a transcript of the whole song,
    so it holds the lyric — free text the customer may have written — and it goes on the
    30-day free-text clock. The name columns stay on the 90-day identity clock, because the
    candidate ladder is tuned from them.
    """
    await session.execute(
        sa.delete(GenerationAttemptRow).where(
            GenerationAttemptRow.order_id == order_id,
            GenerationAttemptRow.kind == GenerationKind.NAME_VERIFICATION,
        )
    )
    for verdict in verdicts:
        session.add(
            GenerationAttemptRow(
                id=uuid4(),
                order_id=order_id,
                created_at=now,
                identity_expires_at=identity_expires_at,
                text_expires_at=text_expires_at,
                **verdict_row_values(verdict),
            )
        )


def _build_kit(
    order_id: UUID,
    asset_rows: Sequence[AssetRow],
    verdict_rows: Sequence[GenerationAttemptRow],
) -> Kit:
    """Reassemble a kit, failing loudly if a required deliverable is missing."""
    by_kind: dict[AssetKind, list[AssetRow]] = {}
    for row in asset_rows:
        by_kind.setdefault(row.kind, []).append(row)

    song_rows = by_kind.get(AssetKind.SONG, [])
    sheet_rows = by_kind.get(AssetKind.LYRIC_SHEET, [])
    greeting_rows = by_kind.get(AssetKind.GREETING, [])
    if not song_rows or not sheet_rows or not greeting_rows:
        raise not_found(
            "kit",
            order_id=str(order_id),
            has_song=bool(song_rows),
            has_lyric_sheet=bool(sheet_rows),
            greeting_count=len(greeting_rows),
        )

    cover_rows = by_kind.get(AssetKind.COVER, [])
    return Kit(
        order_id=order_id,
        song=to_generated_asset(song_rows[0]),
        greetings=tuple(to_generated_asset(row) for row in greeting_rows),
        lyric_sheet=to_generated_asset(sheet_rows[0]),
        lyrics=lyrics_from_payload(sheet_rows[0].payload, order_id=order_id),
        cover=to_generated_asset(cover_rows[0]) if cover_rows else None,
        name_verdicts=name_verdicts_from_rows(verdict_rows),
    )
