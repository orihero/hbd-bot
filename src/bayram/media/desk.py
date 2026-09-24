"""The bot's one door to the media tables (IMAGE_VIDEO_SPEC §2.3.1, §2.5, §2.6, §7.2).

Every row move the compose screens and the post-freeze buttons make goes through
:class:`MediaDesk`, so the bot never holds a session and every answer is a ``Result`` — a
database blip is a sentence to the customer, never a spinner. :class:`SqlMediaDesk` is the one
implementation; the bot tests drive it over SQLite.

Three rules, each from the spec:

* **One open request per (account, kind)** (§2.3.1, §7.6). Freezing first looks for a row of
  the kind that is awaiting payment or paid; if there is one NOTHING is frozen and the caller
  shows ``media.open_request``. Otherwise every earlier ``drafting``/``screening``/``quoted``
  row of the kind is cancelled and the new row inserted, in one transaction. The partial
  unique index is the backstop for a race.
* **Commit, then enqueue** (:mod:`bayram.media.service`): the stage a queue entry starts reads
  the row, so the row is written first; a lost enqueue is ``media_sweep``'s to re-drive.
* **Every post-freeze press re-reads the row** (§2 "Callbacks"): owner and state are checked
  here, and a press that no longer fits is :attr:`CancelOutcome.STALE` and friends — the
  caller answers ``media.stale``. Entitlement is re-checked at press time (§2.5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.config import Settings
from bayram.contracts import Language, Result
from bayram.db.base import utc_now
from bayram.db.enums import (
    MEDIA_IN_FLIGHT_STATES,
    MediaAspect,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaSku,
)
from bayram.db.guard import run_guarded
from bayram.db.media import (
    add_input,
    cancel_prepay_jobs,
    create_job,
    list_inputs,
    load_job,
    spend_credit,
    transition,
)
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.users_sql import ensure_user
from bayram.logging import get_logger
from bayram.media.offering import media_offered
from bayram.media.service import (
    BetaStart,
    MediaQueue,
    enqueue_screen,
    enqueue_start,
    start_free_beta,
)
from bayram.media.stages import MEDIA_CLEANUP_JOB, cleanup_job_id, sku_deadline

__all__ = [
    "CANCELLABLE_STATES",
    "BLOCKING_STATES",
    "JobView",
    "InputRef",
    "FreezeRequest",
    "Frozen",
    "Reopened",
    "CancelOutcome",
    "CreditStart",
    "MediaDesk",
    "SqlMediaDesk",
]

_LOG = get_logger(__name__)

#: What a new draft, ✖️ and ``/cancel`` may cancel: nothing was paid and no pay link is out
#: (§2.3.1, §2.6). ``awaiting_payment`` is deliberately absent — see :data:`BLOCKING_STATES`.
CANCELLABLE_STATES: Final[frozenset[MediaJobState]] = frozenset(
    {MediaJobState.DRAFTING, MediaJobState.SCREENING, MediaJobState.QUOTED}
)

#: A row in one of these stops a new request of its kind being frozen (§2.3.1): a pay link is
#: out, or it is paid for and being made.
BLOCKING_STATES: Final[frozenset[MediaJobState]] = (
    frozenset({MediaJobState.AWAITING_PAYMENT}) | MEDIA_IN_FLIGHT_STATES
)


@dataclass(frozen=True, slots=True)
class JobView:
    """What the bot may know about a row. Read-only; never handed back to be written."""

    id: UUID
    telegram_user_id: int
    kind: MediaKind
    sku: MediaSku
    state: MediaJobState
    chat_id: int
    tray_message_id: int | None
    prompt: str | None
    aspect: MediaAspect
    language: Language
    paid_via: MediaPaidVia | None

    @classmethod
    def of(cls, row: MediaJobRow) -> JobView:
        return cls(
            id=row.id,
            telegram_user_id=row.telegram_user_id,
            kind=row.kind,
            sku=row.sku,
            state=row.state,
            chat_id=row.chat_id,
            tray_message_id=row.tray_message_id,
            prompt=row.prompt,
            aspect=row.aspect,
            language=row.language,
            paid_via=row.paid_via,
        )


@dataclass(frozen=True, slots=True)
class InputRef:
    """An upload by its Telegram ids. The worker downloads the bytes (§3.3)."""

    file_id: str
    file_unique_id: str | None


@dataclass(frozen=True, slots=True)
class FreezeRequest:
    """A composed draft, ready to become a ``screening`` row (§2.3.1)."""

    telegram_user_id: int
    chat_id: int
    tray_message_id: int | None
    kind: MediaKind
    sku: MediaSku
    aspect: MediaAspect
    language: Language
    prompt: str
    refs: tuple[InputRef, ...]
    outputs_requested: int
    price_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class Frozen:
    """``job_id`` is set when a row was frozen; ``open_request`` when one blocked it."""

    job_id: UUID | None
    open_request: JobView | None = None
    #: Earlier pre-pay rows of the kind this freeze cancelled.
    cancelled: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class Reopened:
    """✏️ Edit: the row the customer is editing, and its photos to put back on the tray."""

    job: JobView
    refs: tuple[InputRef, ...]


class CancelOutcome(StrEnum):
    CANCELLED = "cancelled"
    #: Not this account's, or not in a state a cancel applies to — ``media.stale``.
    STALE = "stale"
    #: A pay link is out or it is paid — ``media.cancel_too_late`` (§2.6).
    TOO_LATE = "too_late"


class CreditStart(StrEnum):
    STARTED = "started"
    STALE = "stale"
    NO_CREDIT = "no_credit"
    NOT_ENTITLED = "not_entitled"


class MediaDesk(Protocol):
    """Everything the bot does to a media row. Never raises; every answer is a ``Result``."""

    async def load(self, job_id: UUID) -> Result[JobView | None]: ...

    async def open_request(
        self, telegram_user_id: int, kind: MediaKind
    ) -> Result[JobView | None]: ...

    async def freeze(self, request: FreezeRequest) -> Result[Frozen]: ...

    async def cancel(self, job_id: UUID, *, telegram_user_id: int) -> Result[CancelOutcome]: ...

    async def cancel_open(self, telegram_user_id: int) -> Result[CancelOutcome | None]: ...

    async def reopen(self, job_id: UUID, *, telegram_user_id: int) -> Result[Reopened | None]: ...

    async def start_beta(
        self, job_id: UUID, *, telegram_user_id: int, is_paused: bool
    ) -> Result[BetaStart]: ...

    async def spend_credit(
        self, job_id: UUID, *, telegram_user_id: int, is_paused: bool
    ) -> Result[CreditStart]: ...

    async def retry_screen(self, job_id: UUID, *, telegram_user_id: int) -> Result[bool]: ...


async def _blocking_row(
    session: AsyncSession, telegram_user_id: int, kind: MediaKind | None
) -> MediaJobRow | None:
    conditions = [
        MediaJobRow.telegram_user_id == telegram_user_id,
        MediaJobRow.state.in_(tuple(BLOCKING_STATES)),
    ]
    if kind is not None:
        conditions.append(MediaJobRow.kind == kind)
    return (
        await session.scalars(
            sa.select(MediaJobRow).where(*conditions).order_by(MediaJobRow.created_at.desc())
        )
    ).first()


def _photo_refs(rows: list[MediaInputRow]) -> tuple[InputRef, ...]:
    return tuple(
        InputRef(file_id=row.tg_file_id, file_unique_id=row.tg_file_unique_id)
        for row in rows
        if row.role is MediaInputRole.PHOTO and row.tg_file_id
    )


class SqlMediaDesk:
    """:class:`MediaDesk` over the media tables and the ARQ pool."""

    __slots__ = ("_clock", "_queue", "_sessions", "_settings")

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        queue: MediaQueue,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = sessions
        self._queue = queue
        self._settings = settings
        self._clock = clock

    async def _cleanup(self, job_ids: tuple[UUID, ...] | list[UUID]) -> None:
        for job_id in job_ids:
            try:
                await self._queue.enqueue_job(
                    MEDIA_CLEANUP_JOB, str(job_id), _job_id=cleanup_job_id(job_id)
                )
            except Exception as exc:
                # The purge's own clock deletes the uploads of a terminal row (§3.2.4).
                _LOG.warning(
                    "a media cleanup could not be enqueued",
                    extra={"media_job_id": str(job_id), "failure": repr(exc)},
                )

    # -- reads ---------------------------------------------------------------------------
    async def load(self, job_id: UUID) -> Result[JobView | None]:
        async def run() -> JobView | None:
            async with self._sessions() as session:
                row = await load_job(session, job_id)
            return None if row is None else JobView.of(row)

        return await run_guarded("media.load", run, media_job_id=str(job_id))

    async def open_request(self, telegram_user_id: int, kind: MediaKind) -> Result[JobView | None]:
        async def run() -> JobView | None:
            async with self._sessions() as session:
                row = await _blocking_row(session, telegram_user_id, kind)
            return None if row is None else JobView.of(row)

        return await run_guarded("media.open_request", run, telegram_user_id=telegram_user_id)

    # -- freezing --------------------------------------------------------------------------
    async def freeze(self, request: FreezeRequest) -> Result[Frozen]:
        return await run_guarded(
            "media.freeze", lambda: self._freeze(request), telegram_user_id=request.telegram_user_id
        )

    async def _freeze(self, request: FreezeRequest) -> Frozen:
        now = self._clock()
        async with self._sessions.begin() as session:
            blocking = await _blocking_row(session, request.telegram_user_id, request.kind)
            if blocking is not None:
                return Frozen(job_id=None, open_request=JobView.of(blocking))
            cancelled = await cancel_prepay_jobs(
                session,
                telegram_user_id=request.telegram_user_id,
                now=now,
                kind=request.kind,
                states=CANCELLABLE_STATES,
            )
            user_id = await ensure_user(
                session,
                telegram_user_id=request.telegram_user_id,
                ui_language=request.language,
                now=now,
                is_language_authoritative=False,
            )
            job_id = await create_job(
                session,
                user_id=user_id,
                telegram_user_id=request.telegram_user_id,
                kind=request.kind,
                sku=request.sku,
                state=MediaJobState.SCREENING,
                chat_id=request.chat_id,
                outputs_requested=request.outputs_requested,
                aspect=request.aspect,
                language=request.language,
                prompt=request.prompt,
                price_minor=request.price_minor,
                currency=request.currency,
                now=now,
                quote_ttl=timedelta(seconds=self._settings.media_quote_ttl_s),
                tray_message_id=request.tray_message_id,
            )
            for ordinal, ref in enumerate(request.refs):
                await add_input(
                    session,
                    job_id=job_id,
                    ordinal=ordinal,
                    role=MediaInputRole.PHOTO,
                    now=now,
                    tg_file_id=ref.file_id,
                    tg_file_unique_id=ref.file_unique_id,
                )
        await self._cleanup(cancelled)
        await enqueue_screen(self._queue, job_id)
        return Frozen(job_id=job_id, cancelled=tuple(cancelled))

    # -- cancelling ------------------------------------------------------------------------
    async def cancel(self, job_id: UUID, *, telegram_user_id: int) -> Result[CancelOutcome]:
        async def run() -> CancelOutcome:
            now = self._clock()
            async with self._sessions.begin() as session:
                row = await load_job(session, job_id)
                if row is None or row.telegram_user_id != telegram_user_id:
                    return CancelOutcome.STALE
                if row.state in BLOCKING_STATES:
                    # §2.6: from awaiting_payment only while no Payme transaction exists — the
                    # intent check arrives with the pay path (M5.1); until then a pay link that
                    # is out is treated as money in flight, the safe reading.
                    return CancelOutcome.TOO_LATE
                moved = await transition(
                    session,
                    job_id,
                    expected=CANCELLABLE_STATES,
                    to=MediaJobState.CANCELLED,
                    now=now,
                )
            if not moved:
                return CancelOutcome.STALE
            await self._cleanup([job_id])
            return CancelOutcome.CANCELLED

        return await run_guarded("media.cancel", run, media_job_id=str(job_id))

    async def cancel_open(self, telegram_user_id: int) -> Result[CancelOutcome | None]:
        """``/cancel`` (§2.6): cancel what is pre-pay; say too late for what is not."""

        async def run() -> CancelOutcome | None:
            now = self._clock()
            async with self._sessions.begin() as session:
                cancelled = await cancel_prepay_jobs(
                    session, telegram_user_id=telegram_user_id, now=now, states=CANCELLABLE_STATES
                )
                blocking = await _blocking_row(session, telegram_user_id, None)
            if cancelled:
                await self._cleanup(cancelled)
                return CancelOutcome.CANCELLED
            return CancelOutcome.TOO_LATE if blocking is not None else None

        return await run_guarded("media.cancel_open", run, telegram_user_id=telegram_user_id)

    async def reopen(self, job_id: UUID, *, telegram_user_id: int) -> Result[Reopened | None]:
        """✏️ Edit (§2.3.1): a quote is cancelled in the same transaction that reads it back;
        a refusal is already terminal and is only read. ``None`` for anything else."""

        async def run() -> Reopened | None:
            now = self._clock()
            async with self._sessions.begin() as session:
                row = await load_job(session, job_id)
                if row is None or row.telegram_user_id != telegram_user_id:
                    return None
                view = JobView.of(row)
                refs = _photo_refs(await list_inputs(session, job_id))
                if row.state is MediaJobState.QUOTED:
                    moved = await transition(
                        session,
                        job_id,
                        expected=(MediaJobState.QUOTED,),
                        to=MediaJobState.CANCELLED,
                        now=now,
                    )
                    if not moved:
                        return None
                elif row.state is not MediaJobState.REJECTED:
                    return None
            if view.state is MediaJobState.QUOTED:
                await self._cleanup([job_id])
            return Reopened(job=view, refs=refs)

        return await run_guarded("media.reopen", run, media_job_id=str(job_id))

    # -- starting --------------------------------------------------------------------------
    async def start_beta(
        self, job_id: UUID, *, telegram_user_id: int, is_paused: bool
    ) -> Result[BetaStart]:
        return await run_guarded(
            "media.start_beta",
            lambda: start_free_beta(
                self._sessions,
                self._queue,
                self._settings,
                job_id=job_id,
                telegram_user_id=telegram_user_id,
                is_paused=is_paused,
                now=self._clock(),
            ),
            media_job_id=str(job_id),
        )

    async def spend_credit(
        self, job_id: UUID, *, telegram_user_id: int, is_paused: bool
    ) -> Result[CreditStart]:
        """🎟 (§7.2): the four writes of ``db.media.spend_credit`` after the §2.5 re-check."""

        async def run() -> CreditStart:
            now = self._clock()
            async with self._sessions.begin() as session:
                row = await load_job(session, job_id)
                if (
                    row is None
                    or row.telegram_user_id != telegram_user_id
                    or row.state is not MediaJobState.QUOTED
                ):
                    return CreditStart.STALE
                if not media_offered(
                    self._settings, row.sku, telegram_user_id, is_paused=is_paused
                ):
                    return CreditStart.NOT_ENTITLED
                paid = await spend_credit(
                    session, job_id, now=now, deadline=sku_deadline(self._settings, row.sku)
                )
            if not paid:
                return CreditStart.NO_CREDIT
            await enqueue_start(self._queue, job_id)
            return CreditStart.STARTED

        return await run_guarded("media.spend_credit", run, media_job_id=str(job_id))

    async def retry_screen(self, job_id: UUID, *, telegram_user_id: int) -> Result[bool]:
        """🔁 on a busy tray (§2.3.3): the SAME frozen row, screened again under a new ARQ id."""

        async def run() -> bool:
            async with self._sessions() as session:
                row = await load_job(session, job_id)
            if (
                row is None
                or row.telegram_user_id != telegram_user_id
                or row.state is not MediaJobState.SCREENING
            ):
                return False
            # Whole seconds since the epoch: new on every press, and far above the sweep's
            # minute ticks, so the two can never hand out the same id (§3.3 "ARQ job ids").
            await enqueue_screen(self._queue, job_id, n=int(self._clock().timestamp()))
            return True

        return await run_guarded("media.retry_screen", run, media_job_id=str(job_id))
