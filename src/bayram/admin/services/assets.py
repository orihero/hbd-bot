"""The audited media reveal: what may be read, by whom, how much of it, and at what cost.

Two routes stand on this module — ``GET /api/assets/{id}/stream`` and
``GET /api/assets/{id}/text`` — and §12.2 puts both on the same ``A+S`` cell as every other
reveal, for a reason worth restating: **a greeting says the recipient's name aloud**, so
playing one is not "viewing metadata", it is unmasking personal data through a speaker. The
lyric sheet is the customer's own words. Neither is a file download; both are reveals that
happen to be delivered as bytes.

So the gate is the same gate ``POST /reveal`` uses, in the same order, and it is here rather
than in the router so it cannot be half-applied by the next route somebody adds:

1. **Step-up on this subject.** ``deps.enforce_step_up`` with ``StepUpAction.REVEAL`` and the
   asset id, stringified exactly as the SPA sent it to ``/auth/step-up``.
2. **Budget, charged before the read** (§12.3). One record per reveal.
3. **The audit row, committed before the read** — in its OWN transaction, which is the whole
   reason :func:`_record_reveal` exists beside ``audit_sink.record``. The request's
   transaction is not committed until the handler returns, and for a stream it is not
   committed until the client has finished *playing*: a yield dependency's exit runs after
   the ``StreamingResponse`` body is consumed. A row written into it would therefore land
   minutes late, or not at all if the read then failed — the exact case §12.3's "writes the
   audit row before the read" exists for.

**Unlike ``audit_sink``, an audit failure here fails the request.** That module swallows,
deliberately, because an unauthenticated login route must not become a 500 an attacker can
choose. This path is authenticated, every audited value is ours (a username, a role, a UUID),
and §9.1's rule is that an unaudited reveal must not happen. So the append is allowed to
raise and no bytes move. The one exception is a caller-supplied ``actor_username`` the audit
layer refuses as credential-shaped, which is retried once with a placeholder exactly as
``audit_sink`` does — the *event* stays recorded even when the identifier cannot be.

**The 10-minute window (§12.3's audio caveat).** An ``<audio>`` element issues a range
request every few seconds; auditing each one would make "1 play" unreadable in the log and
would spend an operator's whole hourly budget on one song. So the first request per
``(actor, asset)`` per ten minutes audits and charges, and the rest inside that window are
free. The claim is a counter increment, which is atomic, and it is **released** if the budget
then refuses — otherwise a 429 would burn the window and the retry behind it would stream
un-audited and un-charged, which is a bypass rather than a rough edge.

**Path traversal (§12.1 T4).** The wire accepts an asset UUID and nothing else. The object
key is rebuilt server-side through :func:`bayram.storage.archive_key` from the row's
``order_id`` and ``Path(row.path).name``, and that filename is re-validated against
:data:`FILENAME_PATTERN` on the way out of the database, because a stored string is untrusted
input on read like any other. Confinement itself is not re-implemented here: the key goes to
``Storage.open_range``, and nothing in this package touches ``LocalFileStorage._resolve`` or
any other private member of a concrete backend (§12.7,
``test_asset_stream.py::test_the_admin_package_touches_no_private_storage_member``).

**Content types are compared whole.** ``LYRIC_SHEET_MIME`` is literally
``"text/plain; charset=utf-8"``, and the obvious normalisation — ``mime.split(";")[0]``, the
idiom two lines away in ``pipeline.assets`` — happens to give the right answer for it today
while quietly widening the audio allowlist to any ``audio/mpeg; codecs=…`` variant nobody
reviewed. :data:`STREAMABLE_MIMES` is therefore an exact-match set of two strings, and the
lyric route compares the full mime against one constant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.audit_sink import UNSTORABLE_USERNAME
from bayram.admin.container import AdminContainer
from bayram.admin.deps import CurrentAdmin, enforce_reveal_budget, enforce_step_up
from bayram.admin.errors import ProblemError
from bayram.admin.security.permissions import StepUpAction
from bayram.admin.security.ratelimit import WindowCounterStore
from bayram.admin.security.tokens import sha256_hex
from bayram.contracts import LyricDraft
from bayram.db.admin.audit import AuditEntry, AuditValueRejectedError, append
from bayram.db.enums import AuditAction, AuditReasonCode
from bayram.db.mapping import lyrics_from_payload
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.db.models.asset import AssetRow
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.pipeline.assets import LYRIC_SHEET_MIME, render_lyric_sheet
from bayram.storage import archive_key

__all__ = [
    "ASSET_STREAM_WINDOW_S",
    "ASSET_SUBJECT_TYPE",
    "FILENAME_PATTERN",
    "LYRIC_TEXT_MIME",
    "MEDIA_REVEAL_REASON",
    "STREAMABLE_MIMES",
    "STREAM_FIELD_NAME",
    "TEXT_FIELD_NAME",
    "AssetMedia",
    "ByteRange",
    "RangeOutcome",
    "authorise_media_reveal",
    "lyric_text",
    "load_media",
    "object_key",
    "parse_range",
    "reveal_window_key",
]

_LOGGER: Final = get_logger(__name__)

#: §12.1 T4's allowlist, matched **whole**. ``audio/wave``, ``audio/basic`` and
#: ``application/octet-stream`` are all legitimate outputs of the ElevenLabs adapter for
#: formats nobody configured the panel to play, and each one is a 415 rather than a stream of
#: bytes the browser gets to guess at.
STREAMABLE_MIMES: Final[frozenset[str]] = frozenset({"audio/mpeg", "audio/ogg"})

#: The lyric sheet's mime, exactly as ``pipeline.assets`` writes it. Imported rather than
#: respelled: the ``; charset=utf-8`` half is what makes a prefix comparison tempting, and a
#: second literal is how the two spellings drift apart.
LYRIC_TEXT_MIME: Final[str] = LYRIC_SHEET_MIME

#: §12.1 T4, rule 9: a filename read back out of the database is untrusted input. Anchored,
#: bounded, and with no ``/``, ``\``, NUL or ``.`` segment expressible inside it.
FILENAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: §12.3's audio caveat: one audit row per ``(actor, asset)`` per ten minutes, not one per
#: range request. Fixed and epoch-aligned like every other window in this package
#: (``ratelimit._window_index``), so it resets on the clock rather than on first use.
ASSET_STREAM_WINDOW_S: Final[int] = 600

#: ``db.admin.audit.SUBJECT_TYPES`` is closed and already contains this one.
ASSET_SUBJECT_TYPE: Final[str] = "asset"

#: What ``field_names`` records. Real column names, lowercase-dotted, because
#: ``_FIELD_NAME_PATTERN`` refuses anything else and the refusal is retried with the subject
#: stripped — an "audited" reveal that cannot be attributed. There is no column for the audio
#: bytes themselves, so the stream names the column that addresses them.
STREAM_FIELD_NAME: Final[str] = "assets.storage_key"
TEXT_FIELD_NAME: Final[str] = "assets.payload"

#: Neither route carries a body, so neither can carry §12.3's ``reasonCode`` — and the SPA's
#: player URL is already frozen by shipped tests as ``/api/assets/{id}/stream`` with no query
#: string. ``SUPPORT_INVESTIGATION`` is the honest constant of the closed vocabulary: an
#: operator listening to a customer's greeting is looking into something. It is deliberately
#: not ``ROUTINE_OPS`` (which ``audit_sink.auth_entry`` uses precisely because a login is not
#: an investigation) and not ``OTHER`` (which would make "other" the commonest value in the
#: table and therefore meaningless).
MEDIA_REVEAL_REASON: Final[AuditReasonCode] = AuditReasonCode.SUPPORT_INVESTIGATION

#: Redis namespace for the audio window. Distinct from ``ratelimit._KEY_PREFIX`` and from the
#: budget's, because these three count different things and a shared prefix is how one of
#: them starts answering for another.
_WINDOW_KEY_PREFIX: Final[str] = "bayram:admin:reveal:window"
_KEY_DIGEST_CHARS: Final[int] = 32

#: Bounded so a ``Range`` header of ten thousand digits is a parse failure rather than a
#: bignum allocation. Nineteen digits covers every object any filesystem will hold.
_RANGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^bytes=(\d{0,19})-(\d{0,19})$")


# ---------------------------------------------------------------------------
# The row, and the key it names
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AssetMedia:
    """What the two media routes need from one ``assets`` row, and nothing else.

    Deliberately not :class:`bayram.db.admin.views.AssetView`: that projection drops ``path``
    and ``payload`` on purpose, because the metadata surface must never carry either. This
    one carries both and is never serialised.
    """

    asset_id: UUID
    order_id: UUID
    path: str
    mime: str
    payload: dict[str, Any] | None


async def load_media(session: AsyncSession, asset_id: UUID) -> AssetMedia | None:
    """One asset row, or ``None`` for the caller to answer 404 with."""
    row = await session.get(AssetRow, asset_id)
    if row is None:
        return None
    return AssetMedia(
        asset_id=row.id,
        order_id=row.order_id,
        path=row.path,
        mime=row.mime,
        payload=row.payload,
    )


def object_key(media: AssetMedia) -> str | None:
    """The archive key for this row, or ``None`` when the row cannot name a safe one.

    §12.1 T4, both halves. The key is **rebuilt** — ``orders/{order_id}/{filename}`` through
    the one function all three writers of that string share — rather than read from
    ``assets.storage_key``, which is a stored string that no writer has ever had to prove
    anything about and that is ``NULL`` on every row written before Phase 2 anyway.
    ``Path(path).name`` is then matched against :data:`FILENAME_PATTERN`, because a database
    read is an untrusted boundary like any other: the pipeline only ever writes ``song.mp3``,
    ``greeting-1.ogg`` and ``lyrics.txt``, and anything else is a row to refuse rather than a
    key to resolve.
    """
    filename = Path(media.path).name
    if FILENAME_PATTERN.fullmatch(filename) is None:
        _LOGGER.error(
            "an asset row names a filename this route will not resolve",
            extra={
                "event": "admin.asset.filename_refused",
                "asset_id": str(media.asset_id),
                # Length only. The value is the thing being refused; echoing it into a log
                # line is the same disclosure the refusal exists to prevent.
                "filename_chars": len(filename),
            },
        )
        return None
    return archive_key(media.order_id, filename)


def lyric_text(media: AssetMedia) -> str | None:
    """The lyric sheet as the customer would read it, or ``None`` if the row has no usable one.

    Read from ``assets.payload``, never from the filesystem: the column already holds the
    lyric, so the text route needs no object key, no byte range and no traversal surface at
    all. The sheet is re-typeset with the pipeline's own renderer, so the panel shows the
    file the renderer would produce today rather than a second, differently-formatted
    rendering of its own.

    **Today's renderer, which is not always the delivered file — the limitation is precise
    and it is a version skew, not a formatting choice.** This paragraph used to promise "the
    file that was delivered". :func:`bayram.pipeline.assets.render_lyric_sheet` now wraps the
    sheet in a ``SHEET_RULE`` watermark line top and bottom, so for every order archived
    BEFORE that shipped the bytes in object storage carry no rules while this reveal shows
    two, and an operator comparing the reveal against a customer's forwarded ``lyrics.txt``
    sees a difference the old wording said could not exist. Harmless — nothing here is
    compared byte-for-byte and the lyric itself is identical — but re-rendering means the
    panel tracks the renderer, and any future change to the sheet's shape will re-open the
    same gap for everything already archived. The alternative, reading the delivered object,
    is what the ``payload`` column exists to avoid.

    A payload that no longer validates is ``None`` — the caller answers 404. It is logged at
    ERROR because a stored shape that stopped matching its model is a data incident, but it
    is not a 500: a corrupt row on one order must not look like the panel being down.
    """
    if media.payload is None:
        return None
    try:
        draft: LyricDraft = lyrics_from_payload(media.payload, order_id=media.order_id)
    except (PipelineError, PydanticValidationError):
        _LOGGER.exception(
            "an asset row carries a lyric payload that no longer validates",
            extra={"event": "admin.asset.payload_invalid", "asset_id": str(media.asset_id)},
        )
        return None
    return render_lyric_sheet(draft)


# ---------------------------------------------------------------------------
# Byte ranges
# ---------------------------------------------------------------------------
class RangeOutcome(StrEnum):
    """What a ``Range`` header amounted to, once the object's real length was known."""

    #: No header, or one this server does not implement (multi-range, a unit other than
    #: bytes). RFC 9110 §14.2 permits ignoring a range specification, and ignoring it means
    #: answering 200 with the whole object — never 416, which would break a client that sent
    #: a range it was entitled to send.
    ABSENT = "absent"
    SATISFIABLE = "satisfiable"
    #: 416. The **only** shape that produces it is a first-byte position at or past the end
    #: of the object — which is also why an empty object cannot satisfy any range.
    UNSATISFIABLE = "unsatisfiable"


@dataclass(frozen=True, slots=True)
class ByteRange:
    """A resolved, inclusive ``[start, last]`` slice — HTTP's convention, not Python's."""

    outcome: RangeOutcome
    start: int = 0
    last: int = 0

    @property
    def length(self) -> int:
        """How many bytes the response body will carry."""
        return self.last - self.start + 1

    def content_range(self, *, total: int) -> str:
        """The ``Content-Range`` header for a 206."""
        return f"bytes {self.start}-{self.last}/{total}"


_ABSENT: Final[ByteRange] = ByteRange(outcome=RangeOutcome.ABSENT)
_UNSATISFIABLE: Final[ByteRange] = ByteRange(outcome=RangeOutcome.UNSATISFIABLE)


def parse_range(header: str | None, *, total: int) -> ByteRange:
    """Resolve one ``Range`` header against the object's real length.

    ``total`` comes from ``Storage.size`` and never from ``assets.size_bytes``: that column
    defaults to ``0``, no writer in this repository has ever set it, and a ``Content-Range``
    built from it would read ``bytes 0-99/0`` while making every open-ended ``bytes=N-``
    unsatisfiable.

    The three forms RFC 9110 defines for a single range are all here, and ``end`` past the
    tail is **clamped** rather than refused — a client asking for more than there is has
    asked a satisfiable question.
    """
    if header is None:
        return _ABSENT
    match = _RANGE_PATTERN.match(header.strip())
    if match is None:
        return _ABSENT
    first_text, last_text = match.group(1), match.group(2)
    if not first_text and not last_text:
        # "bytes=-" names neither end. Malformed, so ignored rather than refused.
        return _ABSENT
    if not first_text:
        return _suffix_range(int(last_text), total=total)
    start = int(first_text)
    if start >= total:
        # Includes ``total == 0``: an empty object satisfies no range at all.
        return _UNSATISFIABLE
    last = total - 1 if not last_text else min(int(last_text), total - 1)
    if last < start:
        return _UNSATISFIABLE
    return ByteRange(outcome=RangeOutcome.SATISFIABLE, start=start, last=last)


def _suffix_range(suffix: int, *, total: int) -> ByteRange:
    """``bytes=-N`` — the last ``N`` bytes, clamped to the whole object."""
    if suffix == 0 or total == 0:
        return _UNSATISFIABLE
    return ByteRange(outcome=RangeOutcome.SATISFIABLE, start=max(0, total - suffix), last=total - 1)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def reveal_window_key(*, username: str, asset_id: UUID, now: datetime, window_s: int) -> str:
    """The Redis key §12.3 keys the audio window on: one actor, one asset, one window.

    The username is hashed and case-folded exactly as ``ratelimit._username_digest`` does it,
    for the same two reasons: Redis keys end up in ``KEYS`` dumps and support tickets, and
    ``Alice`` and ``alice`` are one account and must share one bucket.
    """
    window = int(now.timestamp()) // window_s
    digest = sha256_hex(username.casefold())[:_KEY_DIGEST_CHARS]
    return f"{_WINDOW_KEY_PREFIX}:{window}:{digest}:{asset_id}"


async def authorise_media_reveal(
    admin: CurrentAdmin,
    container: AdminContainer,
    *,
    action: AuditAction,
    asset_id: UUID,
    field_name: str,
    now: datetime,
    window_s: int,
) -> None:
    """Step up, charge, audit — in that order — or raise before a single byte is read.

    ``window_s`` of ``0`` means "every request is its own reveal", which is what the lyric
    route wants: one request returns the whole sheet, so there is nothing to deduplicate and
    a second read is a second disclosure. A positive value is §12.3's audio window.

    Raises :class:`ProblemError` — 403 without a scoped grant, 429 with the budget spent, 503
    with the counter store down — and returns ``None`` when the reveal may proceed.
    """
    await enforce_step_up(
        admin,
        container,
        action=StepUpAction.REVEAL,
        # ``str(uuid)`` — lowercase, unbraced — which is byte-for-byte what the SPA sends to
        # ``/auth/step-up`` as ``subjectId``. The scope comparison is whole-string.
        subject_id=str(asset_id),
        now=now,
    )
    claimed: str | None = None
    if window_s > 0:
        key = reveal_window_key(
            username=admin.username, asset_id=asset_id, now=now, window_s=window_s
        )
        if not await _claim_window(container.rate_limits, key, window_s=window_s):
            # Already audited and charged inside this window. §12.3's audio caveat.
            return
        claimed = key
    try:
        decision = await enforce_reveal_budget(admin, container, record_count=1, now=now)
    except ProblemError:
        # Release the window: a refused request disclosed nothing, and leaving the claim
        # standing would let the retry behind this 429 stream un-audited and un-charged.
        if claimed is not None:
            await _release_window(container.rate_limits, claimed, window_s=window_s)
        raise
    await _record_reveal(
        container,
        admin,
        action=action,
        asset_id=asset_id,
        field_name=field_name,
        record_count=decision.records_charged,
        now=now,
    )


async def _claim_window(store: WindowCounterStore, key: str, *, window_s: int) -> bool:
    """Is this the first reveal of this asset by this actor in this window?

    A store that cannot answer says **yes**, which is the safe direction: the reveal is then
    audited and charged, and the charge is what refuses it if the same store is what the
    budget needs. Saying "no" would hand out an unaudited stream every time Redis blinked.
    """
    try:
        count = await store.increment(key, ttl_s=window_s)
    except Exception:
        # Broad on purpose, exactly as ``ratelimit._bump`` is: the store is a protocol and
        # its implementations raise whatever their client raises.
        _LOGGER.exception(
            "the reveal window counter is unavailable; auditing this request as a first play",
            extra={"event": "admin.asset.window_store_unavailable"},
        )
        return True
    return count == 1


async def _release_window(store: WindowCounterStore, key: str, *, window_s: int) -> None:
    """Give a claim back after a refusal. Only ever undoes an increment this call made."""
    try:
        await store.refund(key, ttl_s=window_s)
    except Exception:
        _LOGGER.exception(
            "a reveal window claim could not be released; it will expire with its window",
            extra={"event": "admin.asset.window_release_failed"},
        )


async def _record_reveal(
    container: AdminContainer,
    admin: CurrentAdmin,
    *,
    action: AuditAction,
    asset_id: UUID,
    field_name: str,
    record_count: int,
    now: datetime,
) -> None:
    """Commit the audit row in its own transaction, before the caller reads anything.

    Not ``audit_sink.record``: that appends into the request's transaction, which for a
    streamed response is not committed until the client stops playing. Not
    ``audit_sink.record_refusal`` either, despite the identical transaction shape — that name
    means "this request is about to be refused", and a success recorded through it would read
    as a denial to anyone following the call.
    """
    entry = AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=ASSET_SUBJECT_TYPE,
        subject_id=str(asset_id),
        field_names=(field_name,),
        record_count=record_count,
        reason_code=MEDIA_REVEAL_REASON,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
    key = container.settings.admin_audit_hmac_key.get_secret_value()
    async with container.session_factory.begin() as db:
        try:
            await append(db, entry, key=key, now=now)
        except AuditValueRejectedError:
            # ERROR, not a warning: a credential-shaped operator username reaching the audit
            # boundary is an incident. The retry is ``audit_sink``'s, for its reason — the
            # event stays recorded even when the identifier cannot be. Everything else this
            # can raise propagates and the reveal fails, because §9.1's rule is that an
            # unaudited reveal must not happen.
            _LOGGER.exception(
                "an audited value was refused; the reveal is recorded without it",
                extra={"event": "admin.audit.value_refused", "action": str(action)},
            )
            await append(
                db,
                replace(entry, actor_username=UNSTORABLE_USERNAME, subject_id=None, ip=None),
                key=key,
                now=now,
            )
