"""The audited asset stream — §14 Phase 2, §12.1 T4 and T7, §12.3's audio caveat.

Four claims carry this file; everything else supports one of them.

**A range request is answered correctly, and a failing one leaks nothing.** ``bytes=0-99`` is
a 206 whose ``Content-Range`` and ``Content-Length`` describe the bytes actually sent;
``bytes=999999-`` is a 416 that says how long the object really is. A missing object is a 404
whose body contains **no filesystem path** — asserted against the storage root, the temporary
directory, the order id, the filename and the object key, because leaking the archive layout
through an error body is the classic version of this bug and every one of those five is a
piece of it.

**Confinement is not re-implemented, and it is not reached into.** The traversal cases are
asserted against ``Storage.open_range`` itself, which is the seam §12.7 opened so the admin
package would never need ``LocalFileStorage._resolve`` — and
:func:`test_the_admin_package_reaches_for_no_private_storage_member` walks the AST of every
module under ``src/hbd/admin`` to prove it never does.

**Nothing serves customer text as ``text/plain``.** §12.1 T7: a same-origin body of
customer-written free text is a stored-XSS primitive that bypasses React entirely, so the
lyric sheet is ``application/json`` and the assertion is made **globally**, over every route
the application mounts, rather than only for the one route that was written to be safe.

**One play is one audit row.** An ``<audio>`` element issues a range request every few
seconds. §12.3 audits the first per ``(actor, asset)`` per ten minutes, and this file tests
the window directly: many requests inside it write one row, one after it writes a second. The
budget follows the same window, because a budget charged per range request would spend an
operator's hour on a single song.

The audit-ordering test is the one that would pass under a wrong implementation if it were
written the obvious way. "Stream, then assert the row exists" is true whether the row was
committed before the read or written into the request's transaction afterwards. So the test
here makes the read **fail** after the audit call and asserts the row survives — which is
exactly the case §12.3's "writes the audit row before the read" exists for, and is false for
any implementation that uses ``audit_sink.record``.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

import hbd.storage as storage_module
from hbd.admin import routers as routers_package
from hbd.admin.container import ARCHIVE_DIRNAME, AdminContainer
from hbd.admin.deps import AUTH_PREFIX
from hbd.admin.errors import AdminErrorCode
from hbd.admin.routers import assets as assets_router
from hbd.admin.routers.assets import ASSET_STREAM_PATH, ASSET_TEXT_PATH, ASSETS_PATH
from hbd.admin.security.budget import RevealBudgetScope, reveal_budget_key
from hbd.admin.security.permissions import StepUpAction
from hbd.admin.services.assets import (
    ASSET_STREAM_WINDOW_S,
    FILENAME_PATTERN,
    LYRIC_TEXT_MIME,
    STREAMABLE_MIMES,
    AssetMedia,
    RangeOutcome,
    object_key,
    parse_range,
    reveal_window_key,
)
from hbd.contracts import AssetKind, Err, Language, LyricDraft, LyricSection, OrderState
from hbd.db.admin.audit import SUBJECT_TYPES
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole, AuditAction
from hbd.db.mapping import lyrics_to_payload
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.asset import AssetRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.retention import RetentionClass
from hbd.errors import ErrorCode, NotFoundError, ValidationError
from hbd.pipeline.assets import LYRIC_SHEET_MIME, render_lyric_sheet
from hbd.storage import LocalFileStorage, archive_key
from tests.test_admin.conftest import (
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    api_routes,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)
from tests.test_admin.test_routes_enumeration import EXEMPT_PATHS, MOUNTED_ROUTES

#: A fixed instant for the seed rows. The request clock is the ``clock`` fixture's, not this.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
FAR_FUTURE: Final[datetime] = NOW + timedelta(days=300)

TELEGRAM_ID: Final[int] = 99_000_777
SONG_FILENAME: Final[str] = "song.mp3"
#: Enough bytes that a 100-byte range is a genuine slice and a suffix range is not the whole
#: object, and small enough that the whole thing is one ``RANGE_CHUNK_BYTES`` read.
SONG_BYTES: Final[bytes] = bytes(range(256)) * 8

#: The name the product exists to get right. U+02BB is a modifier letter, not an apostrophe,
#: and the reveal path is the one place a whole customer string is returned — so it is
#: asserted **byte-identically**, never normalised, case-folded or re-encoded.
RECIPIENT_NAME: Final[str] = "Gʻulom"
LYRIC_LINE: Final[str] = "Gʻulomjonga tugʻilgan kuningiz muborak boʻlsin"

#: The step-up grace has to outlast the ten-minute audit window for the windowing test to be
#: about the window rather than about an expired grant. 900 is the setting's ceiling.
LONG_GRACE_S: Final[int] = 900

#: The logger whose ``event`` fields the fail-open tests read.
_SERVICE_LOGGER: Final[str] = "hbd.admin.services.assets"


# ---------------------------------------------------------------------------
# The panel: a real container whose Storage points at a temporary archive
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class Panel:
    """One application, its container, its counter store, and the archive on disk."""

    container: AdminContainer
    client: httpx.AsyncClient
    archive: Path
    limits: MemoryRateLimits


@pytest.fixture
async def panel(tmp_path: Path) -> AsyncIterator[Panel]:
    """The real stack with the archive swapped for a temporary directory.

    ``dataclasses.replace`` on the container rather than a hand-built one: the engine, the
    pool and the schema shortcut stay exactly production's, and only the volume moves. The
    protocol is what the package depends on, so nothing in ``src`` notices.
    """
    settings = make_settings(admin_step_up_grace_seconds=LONG_GRACE_S)
    redis, limits = FakeRedis(), MemoryRateLimits()
    archive = tmp_path / ARCHIVE_DIRNAME
    archive.mkdir()
    async with open_container(settings, redis, limits) as built:
        container = dataclasses.replace(built, storage=LocalFileStorage(archive))
        async with open_client(container) as http:
            yield Panel(container=container, client=http, archive=archive, limits=limits)


class Clock:
    """The router's ``now``, movable — and aware that every window here is epoch-aligned.

    ``ratelimit._window_index`` buckets by ``int(now.timestamp()) // window_s``, so a window
    resets on the clock rather than on first use. A test that simply advanced nine minutes
    would cross a ten-minute boundary whenever it happened to start late in one, and would
    then fail once an hour for reasons having nothing to do with the code. Both helpers below
    exist to make the bucket a decision rather than an accident.

    Every offset they produce stays **well inside** ``LONG_GRACE_S``, because the step-up
    grant is minted by the real ``/auth/step-up`` against the real clock: pushing this one
    past the grace would expire the grant and turn a windowing test into an authorisation
    test that passes for the wrong reason.
    """

    def __init__(self, read: Callable[[], datetime]) -> None:
        self._read = read
        self.offset = 0.0

    def now(self) -> datetime:
        return self._read() + timedelta(seconds=self.offset)

    def advance(self, seconds: float) -> None:
        self.offset += seconds

    def _remaining(self, window_s: int) -> float:
        return window_s - (self.now().timestamp() % window_s)

    def cross(self, window_s: int) -> None:
        """Step just past the next boundary. Costs at most one window."""
        self.advance(self._remaining(window_s) + 1)

    def room_for(self, window_s: int, seconds: float) -> None:
        """Guarantee ``seconds`` of headroom inside the CURRENT bucket, crossing if short."""
        if self._remaining(window_s) <= seconds:
            self.cross(window_s)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    """Move the router's ``now`` forward without moving the wall clock.

    Only :mod:`hbd.admin.routers.assets` is patched, so the session and the step-up grant are
    still written against the real clock — which is what makes "the audit window elapsed" and
    "the grant expired" two different, separately testable facts.
    """
    # The unpatched function itself, so the shifted clock is an offset from real time and
    # not a self-reference to whatever this fixture installed.
    real: Callable[[], datetime] = utc_now
    shifted = Clock(real)
    monkeypatch.setattr(assets_router, "utc_now", shifted.now)
    yield shifted


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
async def seed_order(container: AdminContainer) -> OrderRow:
    """One user and one order, because both FKs on ``assets`` are mandatory."""
    async with container.session_factory.begin() as db:
        user = UserRow(
            id=uuid4(),
            telegram_user_id=TELEGRAM_ID,
            ui_language=Language.UZ_LATN,
            is_blocked=False,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(user)
        await db.flush()
        order = OrderRow(
            id=uuid4(),
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            state=OrderState.DELIVERED,
            correlation_id="corr-stream",
            is_paid=True,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(order)
        await db.flush()
        return order


async def seed_asset(container: AdminContainer, *, order: OrderRow, **kw: Any) -> AssetRow:
    """One asset row, written through the real model so the columns are the real ones."""
    async with container.session_factory.begin() as db:
        row = AssetRow(
            id=kw.pop("id", uuid4()),
            order_id=order.id,
            kind=kw.pop("kind", AssetKind.SONG),
            variant_index=kw.pop("variant_index", 0),
            # Absolute, and from the worker's filesystem rather than the panel's — which is
            # the shape T4 is about: only ``Path(path).name`` is ever used.
            path=kw.pop("path", f"/srv/hbd/var/workspace/{order.id}/{SONG_FILENAME}"),
            storage_key=kw.pop("storage_key", None),
            mime=kw.pop("mime", "audio/mpeg"),
            # Deliberately wrong, and deliberately the default the column actually carries:
            # nothing in this repository writes ``size_bytes``, so a Content-Range built from
            # it would read ``/0``. Every length assertion below must come from the volume.
            size_bytes=kw.pop("size_bytes", 0),
            duration_s=kw.pop("duration_s", 91.5),
            sha256=kw.pop("sha256", "a" * 64),
            loudness_lufs=kw.pop("loudness_lufs", -14.0),
            persona_id=kw.pop("persona_id", "persona-1"),
            tg_file_id=kw.pop("tg_file_id", None),
            name_candidate_text=kw.pop("name_candidate_text", RECIPIENT_NAME),
            name_candidate_strategy=kw.pop("name_candidate_strategy", None),
            name_candidate_rank=kw.pop("name_candidate_rank", None),
            payload=kw.pop("payload", None),
            retention_class=kw.pop("retention_class", RetentionClass.PAID_AUDIO),
            expires_at=kw.pop("expires_at", FAR_FUTURE),
            created_at=kw.pop("created_at", NOW),
        )
        db.add(row)
        await db.flush()
        return row


def write_object(panel: Panel, *, order_id: UUID, filename: str, data: bytes) -> Path:
    """Put bytes where ``archive_key`` says the object lives. The one spelling, shared."""
    target = panel.archive / archive_key(order_id, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def lyric_draft() -> LyricDraft:
    return LyricDraft(
        title="Tugʻilgan kun",
        language=Language.UZ_LATN,
        sections=(LyricSection(label="verse", lines=(LYRIC_LINE,), is_name_hook=True),),
        name_display=RECIPIENT_NAME,
    )


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.SUPPORT) -> str:
    """Sign one operator in and hand back their username."""
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    response = await sign_in(panel.client, username=username, password=PASSWORD)
    assert response.status_code == 200, response.text
    return username


async def step_up(panel: Panel, subject_id: object) -> httpx.Response:
    """The real ``/auth/step-up`` route — the only thing that writes ``step_up_scope``.

    Driven over HTTP rather than by hand-building a ``StepUpGrant``, because a hand-built one
    would agree with whatever literal the handler happened to use. This is the call that
    proves the handler asks for the same scope the SPA obtains.
    """
    return await panel.client.post(
        f"{AUTH_PREFIX}/step-up",
        json={
            "password": PASSWORD,
            "scope": StepUpAction.REVEAL.value,
            "subjectId": str(subject_id),
        },
        headers=csrf_headers(panel.client),
    )


async def audit_rows(container: AdminContainer, action: AuditAction) -> list[AdminAuditRow]:
    """Every row for one action, oldest first."""
    async with container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.action == action)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


def stream_path(asset_id: object) -> str:
    return ASSET_STREAM_PATH.format(asset_id=asset_id)


def text_path(asset_id: object) -> str:
    return ASSET_TEXT_PATH.format(asset_id=asset_id)


async def ready_song(panel: Panel, *, clock_role: AdminRole = AdminRole.SUPPORT) -> AssetRow:
    """A signed-in operator, a stepped-up grant, an asset row and its bytes on disk."""
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    await signed_in(panel, role=clock_role)
    assert (await step_up(panel, asset.id)).status_code == 200
    return asset


# ---------------------------------------------------------------------------
# Ranges — the acceptance's first bullet
# ---------------------------------------------------------------------------
async def test_a_hundred_byte_range_is_a_206_describing_exactly_what_it_sent(
    panel: Panel,
) -> None:
    # Arrange
    asset = await ready_song(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-99"})

    # Assert — the header, the length and the body all agree, and the total is the object's
    # real length rather than ``assets.size_bytes`` (seeded as 0 on purpose).
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-99/{len(SONG_BYTES)}"
    assert response.headers["content-length"] == "100"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == SONG_BYTES[:100]


async def test_a_range_past_the_end_of_the_object_is_a_416(panel: Panel) -> None:
    # Arrange
    asset = await ready_song(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=999999-"})

    # Assert — and the 416 says how long the object actually is, which is what lets a client
    # re-ask for a range that exists (RFC 9110 §15.5.17).
    assert response.status_code == 416
    assert response.json()["error"]["code"] == AdminErrorCode.RANGE_NOT_SATISFIABLE.value
    assert response.headers["content-range"] == f"bytes */{len(SONG_BYTES)}"


async def test_an_open_ended_range_is_clamped_to_the_last_byte(panel: Panel) -> None:
    # Arrange — ``bytes=N-`` is what a browser sends when an operator seeks.
    asset = await ready_song(panel)
    start = len(SONG_BYTES) - 10

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": f"bytes={start}-"})

    # Assert
    assert response.status_code == 206
    assert response.headers["content-range"] == (
        f"bytes {start}-{len(SONG_BYTES) - 1}/{len(SONG_BYTES)}"
    )
    assert response.content == SONG_BYTES[start:]


async def test_a_request_with_no_range_header_returns_the_whole_object(panel: Panel) -> None:
    # Arrange — the first request an ``<audio>`` element makes is usually this one.
    asset = await ready_song(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-range" not in response.headers
    assert response.content == SONG_BYTES


async def test_the_stream_is_never_cacheable(panel: Panel) -> None:
    # Arrange — T10. ``IMMUTABLE_PATH_PREFIX`` is the literal ``"/assets/"`` and is matched on
    # the raw request path; ``/api/assets/...`` does not start with it, which is the only
    # reason an audio response does not inherit a one-year immutable cache.
    asset = await ready_song(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})

    # Assert
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# The missing file, and what its body may not contain
# ---------------------------------------------------------------------------
def assert_names_no_path(response: httpx.Response, *, panel: Panel, order_id: UUID) -> None:
    """No piece of the archive layout appears anywhere in this body.

    Five separate pieces, because leaking any one of them is a step towards the next: the
    storage root, its parent, the object key, the order id's place in that key, and the
    filename. ``operator_message`` is what crosses the wire for an ``HbdError`` — ``context``
    is dropped by ``errors._details_of`` — so this passes only while every message the
    storage layer produces stays a constant.
    """
    body = response.text
    for fragment in (
        str(panel.archive),
        str(panel.archive.parent),
        archive_key(order_id, SONG_FILENAME),
        f"orders/{order_id}",
        SONG_FILENAME,
    ):
        assert fragment not in body, fragment


async def test_a_missing_object_is_a_404_whose_body_names_no_filesystem_path(
    panel: Panel,
) -> None:
    # Arrange — the row is there and the bytes are not, which is what an unswept retention
    # backlog or a half-failed archive looks like in production.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert_names_no_path(response, panel=panel, order_id=order.id)


async def test_a_key_that_names_a_directory_is_a_404_that_names_no_path(panel: Panel) -> None:
    # Arrange — a directory key resolves and stats perfectly well; it is still not an object,
    # and the refusal must not describe where it looked.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    (panel.archive / archive_key(order.id, SONG_FILENAME)).mkdir(parents=True)
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})

    # Assert
    assert response.status_code == 404
    assert_names_no_path(response, panel=panel, order_id=order.id)


async def test_a_filename_the_pattern_refuses_never_reaches_the_storage_layer(
    panel: Panel,
) -> None:
    # Arrange — rule 9: a string read back out of the database is untrusted input. The
    # pipeline only ever writes song.mp3 / greeting-N.ogg / lyrics.txt, so anything else is a
    # row to refuse rather than a key to resolve.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order, path="/srv/kits/../../etc/pa%20sswd")
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 404
    assert "passwd" not in response.text


@pytest.mark.parametrize(
    "filename",
    ["song.mp3", "greeting-1.ogg", "lyrics.txt", "a", "A-b_c.9"],
)
def test_the_filenames_the_pipeline_writes_all_pass_the_pattern(filename: str) -> None:
    # Arrange / Act / Assert — a pattern that refused a real deliverable would take the whole
    # feature out, silently, one asset kind at a time.
    assert FILENAME_PATTERN.fullmatch(filename) is not None


@pytest.mark.parametrize(
    "path",
    [
        "/var/kits/a b.mp3",
        "/var/kits/a\\b.mp3",
        "/var/kits/" + "x" * 200 + ".mp3",
        "/var/kits/naïve.mp3",
        "",
    ],
)
def test_a_row_whose_filename_is_unusable_yields_no_object_key(path: str) -> None:
    # Arrange
    media = AssetMedia(
        asset_id=uuid4(), order_id=uuid4(), path=path, mime="audio/mpeg", payload=None
    )

    # Act / Assert — ``None``, never a key built anyway and left for the storage layer to
    # refuse. Confinement is the backstop, not the gate.
    assert object_key(media) is None


@pytest.mark.parametrize(
    "path", ["/var/kits/../../etc/song.mp3", "../../song.mp3", "/var/kits/./song.mp3"]
)
def test_a_traversing_path_column_contributes_only_its_basename(path: str) -> None:
    # Arrange — T4's first half, and the reason the key is REBUILT rather than read: whatever
    # ``assets.path`` says, only ``Path(path).name`` survives into the key, so a stored value
    # cannot address anything outside this order's own folder in the archive.
    order_id = uuid4()
    media = AssetMedia(
        asset_id=uuid4(), order_id=order_id, path=path, mime="audio/mpeg", payload=None
    )

    # Act / Assert
    assert object_key(media) == archive_key(order_id, SONG_FILENAME)


def test_a_usable_row_yields_the_one_shared_spelling_of_the_key() -> None:
    # Arrange — the same function ``pipeline.assets``, ``db.repository`` and ``db.purge`` use.
    # Two spellings of this string is the archive-orphan bug those three exist to close.
    order_id = uuid4()
    media = AssetMedia(
        asset_id=uuid4(),
        order_id=order_id,
        path=f"/srv/hbd/var/workspace/{order_id}/{SONG_FILENAME}",
        mime="audio/mpeg",
        payload=None,
    )

    # Act / Assert
    assert object_key(media) == archive_key(order_id, SONG_FILENAME)


# ---------------------------------------------------------------------------
# T4 — traversal, asserted at the seam rather than at the router
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "orders/../../etc/passwd",
        "/etc/passwd",
        "orders\\evil\\song.mp3",
        "orders/\x00/song.mp3",
        "",
        "   ",
        "orders//song.mp3",
        "orders/./song.mp3",
    ],
    ids=repr,
)
async def test_open_range_refuses_every_traversing_key(tmp_path: Path, key: str) -> None:
    # Arrange — the seam itself, because that is where §12.7 put confinement and where T4
    # forbids the admin package from re-implementing it.
    storage = LocalFileStorage(tmp_path)

    # Act
    ranged = await storage.open_range(key, start=0, end=9)
    sized = await storage.size(key)

    # Assert — distinguished by exception TYPE, never by message text.
    assert isinstance(ranged, Err)
    assert isinstance(ranged.error, ValidationError)
    assert ranged.error.error_code is ErrorCode.INVALID_INPUT
    assert isinstance(sized, Err)
    assert isinstance(sized.error, ValidationError)


async def test_a_valid_asset_resolves_under_the_root_and_streams(tmp_path: Path) -> None:
    # Arrange — the positive half of the same claim.
    storage = LocalFileStorage(tmp_path)
    order_id = uuid4()
    key = archive_key(order_id, SONG_FILENAME)
    target = tmp_path / key
    target.parent.mkdir(parents=True)
    target.write_bytes(SONG_BYTES)

    # Act
    sized = await storage.size(key)
    opened = await storage.open_range(key, start=0, end=99)

    # Assert
    assert not isinstance(sized, Err)
    assert sized.value == len(SONG_BYTES)
    assert not isinstance(opened, Err)
    assert b"".join([chunk async for chunk in opened.value]) == SONG_BYTES[:100]
    assert target.resolve().is_relative_to(tmp_path.resolve())


async def test_a_key_for_bytes_that_are_not_there_is_not_found_and_not_a_storage_failure(
    tmp_path: Path,
) -> None:
    # Arrange — "gone" and "broken" must map to 404 and 5xx respectively, and a caller that
    # cannot tell them apart turns a disk fault into "the customer's song expired".
    storage = LocalFileStorage(tmp_path)

    # Act
    missing = await storage.size(archive_key(uuid4(), SONG_FILENAME))

    # Assert
    assert isinstance(missing, Err)
    assert isinstance(missing.error, NotFoundError)
    assert missing.error.error_code is ErrorCode.NOT_FOUND
    assert missing.error.is_retryable is False
    # The message is a constant. Everything identifying lives in ``context``, which
    # ``admin.errors._details_of`` drops before anything reaches the wire.
    assert str(tmp_path) not in missing.error.operator_message


# ---------------------------------------------------------------------------
# §12.7 — the admin package touches no private storage member
# ---------------------------------------------------------------------------
def private_names(namespace: object) -> frozenset[str]:
    """Every single-underscore name in a module or class namespace."""
    return frozenset(
        name for name in vars(namespace) if name.startswith("_") and not name.startswith("__")
    )


#: Derived from the objects themselves rather than typed out, so a private member added to
#: ``LocalFileStorage`` tomorrow is covered by this test today.
PRIVATE_STORAGE_NAMES: Final[frozenset[str]] = private_names(storage_module) | private_names(
    LocalFileStorage
)

ADMIN_PACKAGE_ROOT: Final[Path] = Path(assets_router.__file__).resolve().parent.parent


def admin_modules() -> list[Path]:
    return sorted(path for path in ADMIN_PACKAGE_ROOT.rglob("*.py"))


def test_the_private_storage_names_this_test_guards_are_the_real_ones() -> None:
    # Arrange / Act / Assert — the scan below is worth nothing if the set is empty or if
    # ``_resolve``, the member T4 names by hand, is not in it.
    assert "_resolve" in PRIVATE_STORAGE_NAMES
    assert len(admin_modules()) > 20


def test_the_admin_package_reaches_for_no_private_storage_member() -> None:
    # Arrange — §12.7's whole reason for existing: the panel gets a public seam so it never
    # has to reach into a private method of a concrete backend, which would make the S3
    # answer unimplementable and would duplicate confinement where it can drift.
    offences: list[str] = []

    # Act
    for path in admin_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in PRIVATE_STORAGE_NAMES:
                offences.append(f"{path.name}:{node.lineno} .{node.attr}")
            if isinstance(node, ast.ImportFrom) and node.module == storage_module.__name__:
                offences.extend(
                    f"{path.name}:{node.lineno} imports {alias.name}"
                    for alias in node.names
                    if alias.name not in storage_module.__all__
                )

    # Assert
    assert offences == []


def test_everything_the_admin_package_imports_from_storage_is_public_api() -> None:
    # Arrange — the other half: a public name that is not in ``__all__`` is not a contract
    # either, and this is the list the S3 replacement would have to honour.
    imported: set[str] = set()

    # Act
    for path in admin_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == storage_module.__name__:
                imported.update(alias.name for alias in node.names)

    # Assert — a concrete class at wiring time, and the shared key spelling. Nothing else.
    assert imported <= {"LocalFileStorage", "archive_key"}
    assert imported <= set(storage_module.__all__)


def test_the_panel_reads_the_same_archive_directory_the_worker_writes() -> None:
    # Arrange — the name is restated in ``admin.container`` rather than imported, because
    # ``hbd.runtime.container`` builds the provider set at import and §4.2 keeps this process
    # free of vendor adapters. A test can afford the import; the process cannot.
    from hbd.runtime.container import ARCHIVE_DIRNAME as WORKER_ARCHIVE_DIRNAME

    # Act / Assert — a drift here streams from a directory nothing writes into, and every
    # asset in the fleet is a 404 nobody can explain.
    assert ARCHIVE_DIRNAME == WORKER_ARCHIVE_DIRNAME


# ---------------------------------------------------------------------------
# §12.1 T7 — the lyric sheet is JSON, and nothing anywhere is text/plain
# ---------------------------------------------------------------------------
async def ready_lyric_sheet(panel: Panel) -> AssetRow:
    order = await seed_order(panel.container)
    asset = await seed_asset(
        panel.container,
        order=order,
        kind=AssetKind.LYRIC_SHEET,
        path=f"/srv/hbd/var/workspace/{order.id}/lyrics.txt",
        mime=LYRIC_SHEET_MIME,
        payload=lyrics_to_payload(lyric_draft()),
    )
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200
    return asset


async def test_the_lyric_sheet_comes_back_as_json_with_nosniff(panel: Panel) -> None:
    # Arrange
    asset = await ready_lyric_sheet(panel)

    # Act
    response = await panel.client.get(text_path(asset.id))

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["assetId"] == str(asset.id)


async def test_the_revealed_lyric_is_byte_identical_to_what_the_customer_would_read(
    panel: Panel,
) -> None:
    # Arrange — the mirror of ``test_redaction``'s "no plaintext reaches any body": reveal is
    # the one path that returns the whole string, so it must return exactly the whole string.
    # U+02BB is category ``Lm`` and correct Uzbek Latin orthography; a ``.strip()``, a
    # ``.normalize()`` or a re-encode anywhere on this path corrupts the one value an
    # operator opened this screen to check.
    asset = await ready_lyric_sheet(panel)

    # Act
    response = await panel.client.get(text_path(asset.id))

    # Assert
    assert response.json()["text"] == render_lyric_sheet(lyric_draft())
    assert LYRIC_LINE in response.json()["text"]
    assert RECIPIENT_NAME in response.json()["text"]


async def test_the_lyric_sheet_is_never_streamed_as_bytes(panel: Panel) -> None:
    # Arrange — T7 by name: ``text/plain`` is no longer streamed at all. The mime is literally
    # ``"text/plain; charset=utf-8"``, so an allowlist normalised with ``split(";")[0]`` would
    # give the right answer here by luck while widening the audio set for everything else.
    asset = await ready_lyric_sheet(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 415
    assert response.json()["error"]["code"] == AdminErrorCode.UNSUPPORTED_MEDIA_TYPE.value


@pytest.mark.parametrize("mime", ["audio/wave", "audio/basic", "application/octet-stream"])
async def test_a_format_outside_the_allowlist_is_415_not_a_guess(panel: Panel, mime: str) -> None:
    # Arrange — every one of these is a legitimate ElevenLabs output for a format nobody
    # configured the panel to play. 415, not 404: the file is there and the reason is the
    # format, which is a different thing for an operator to go and fix.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order, mime=mime)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 415
    assert response.json()["error"]["details"]["mime"] == mime


def test_the_streamable_allowlist_is_exactly_the_two_audio_types_t4_names() -> None:
    # Arrange / Act / Assert — matched whole, so no ``audio/mpeg; codecs=…`` variant nobody
    # reviewed can join it by prefix.
    assert frozenset({"audio/mpeg", "audio/ogg"}) == STREAMABLE_MIMES
    assert LYRIC_TEXT_MIME not in STREAMABLE_MIMES
    assert LYRIC_TEXT_MIME == "text/plain; charset=utf-8"


async def test_no_mounted_route_answers_with_a_text_plain_body(panel: Panel) -> None:
    # Arrange — asserted GLOBALLY rather than for the one route that was written to be safe.
    # T7's reasoning is about the *class* of response: a same-origin body of customer free
    # text is a stored-XSS primitive whatever route produced it, and the next route to serve
    # one would pass every test in this file except this one.
    asset = await ready_lyric_sheet(panel)
    identifiers = {
        "order_id": uuid4(),
        "telegram_user_id": TELEGRAM_ID,
        "asset_id": asset.id,
        "attempt_id": uuid4(),
    }

    # Act / Assert
    for method, template, _ in sorted(MOUNTED_ROUTES):
        if method != "GET" or template in EXEMPT_PATHS:
            continue
        response = await panel.client.get(template.format(**identifiers))
        content_type = response.headers.get("content-type", "")
        assert not content_type.startswith("text/plain"), (template, content_type)


def test_no_mounted_route_declares_a_text_plain_response(panel: Panel) -> None:
    # Arrange — the structural half. The sweep above can only see the answers it provoked;
    # this one reads what every route says it may return, including branches no fixture hits.
    from hbd.admin.app import create_app

    application = create_app(container=panel.container)

    # Act / Assert
    for route in api_routes(application):
        declared = getattr(route.response_class, "value", route.response_class)
        media_type = getattr(declared, "media_type", None)
        assert media_type is None or not str(media_type).startswith("text/plain"), route.path


# ---------------------------------------------------------------------------
# §12.2 — the role half and the scope half, both of which must run
# ---------------------------------------------------------------------------
async def test_a_viewer_is_refused_by_role_and_never_offered_a_prompt(panel: Panel) -> None:
    # Arrange — §12.2 row 10 is ``—`` for VIEWER. FORBIDDEN and not STEP_UP_REQUIRED: the SPA
    # turns the second into a re-authentication prompt, and offering one to somebody who was
    # never eligible is a loop they cannot win.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    await signed_in(panel, role=AdminRole.VIEWER)

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value


@pytest.mark.parametrize("role", [AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER])
async def test_every_role_in_the_matrix_row_can_actually_play_after_stepping_up(
    panel: Panel, role: AdminRole
) -> None:
    # Arrange — the test that would fail if the ``A+S`` cell were declared at the router: a
    # router guard holds no subject and answers STEP_UP_REQUIRED to an operator holding a
    # live, correctly-scoped grant, for ever, and it looks exactly like the matrix working.
    asset = await ready_song(panel, clock_role=role)

    # Act
    response = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})

    # Assert
    assert response.status_code == 206, response.text
    assert response.content == SONG_BYTES[:10]


async def test_playing_without_a_step_up_is_refused_and_the_refusal_is_audited(
    panel: Panel,
) -> None:
    # Arrange — the role is fine; the subject-scoped grant is missing.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    await signed_in(panel)

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert — 403, no bytes, and §12.6's refusal row in its own committed transaction.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert await audit_rows(panel.container, AuditAction.ASSET_STREAM) == []
    assert len(await audit_rows(panel.container, AuditAction.PERMISSION_DENIED)) == 1


async def test_a_grant_for_another_asset_does_not_authorise_this_one(panel: Panel) -> None:
    # Arrange — the confused deputy the scope exists to stop. A grant is the whole string
    # ``reveal:<subject>`` and it is compared whole, never by prefix.
    order = await seed_order(panel.container)
    wanted = await seed_asset(panel.container, order=order)
    other = await seed_asset(panel.container, order=order, variant_index=1)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    await signed_in(panel)
    assert (await step_up(panel, other.id)).status_code == 200

    # Act
    response = await panel.client.get(stream_path(wanted.id))

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value


async def test_the_scope_the_handler_asks_for_is_the_one_the_spa_can_obtain(
    panel: Panel,
) -> None:
    # Arrange — trap 9, closed. ``require_step_up`` takes ``action: str``, so
    # ``require_step_up("reveal.media", …)`` type-checks, builds a storable scope and then
    # never matches a grant ``/auth/step-up`` issued for ``reveal:<id>``. That is a permanent,
    # silent 403 that only a test driving the real route catches — a hand-built ``StepUpGrant``
    # would agree with whatever literal the handler used and pass either way. This drives the
    # real route.
    asset = await ready_song(panel)

    # Act
    granted = await step_up(panel, asset.id)
    played = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-0"})

    # Assert
    assert granted.json()["scope"] == f"{StepUpAction.REVEAL.value}:{asset.id}"
    assert played.status_code == 206


# ---------------------------------------------------------------------------
# §12.3 — one audit row per (actor, asset) per ten-minute window
# ---------------------------------------------------------------------------
#: Eight range requests twenty seconds apart — the shape of one play, compressed.
_PLAY_REQUESTS: Final[int] = 8
_PLAY_GAP_S: Final[int] = 20


async def test_many_range_requests_inside_the_window_write_exactly_one_audit_row(
    panel: Panel, clock: Clock
) -> None:
    # Arrange — this is what one play looks like on the wire: a browser asks for the head,
    # then chunk after chunk. A row per request would make "1 play" unreadable in the log and
    # would spend a whole hourly budget on one song.
    asset = await ready_song(panel)
    clock.room_for(ASSET_STREAM_WINDOW_S, _PLAY_REQUESTS * _PLAY_GAP_S)

    # Act
    for index in range(_PLAY_REQUESTS):
        response = await panel.client.get(
            stream_path(asset.id), headers={"Range": f"bytes={index * 16}-{index * 16 + 15}"}
        )
        assert response.status_code == 206, response.text
        clock.advance(_PLAY_GAP_S)

    # Assert
    rows = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert len(rows) == 1


async def test_a_request_after_the_window_writes_a_second_row(panel: Panel, clock: Clock) -> None:
    # Arrange
    asset = await ready_song(panel)

    # Act — stepped just past the next boundary rather than "ten minutes later", because the
    # bucket is epoch-aligned and "later" is not the same thing as "in the next window".
    first = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})
    clock.cross(ASSET_STREAM_WINDOW_S)
    second = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})

    # Assert — two plays, two rows, and both attributable.
    assert (first.status_code, second.status_code) == (206, 206)
    rows = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert len(rows) == 2
    assert {row.subject_id for row in rows} == {str(asset.id)}


async def test_the_audit_row_carries_the_columns_an_investigation_reads(panel: Panel) -> None:
    # Arrange — trap 11: ``field_names`` is shape-validated and the failure is *swallowed*
    # with the subject and the address stripped, so only a test that reads the columns
    # notices an "audited" reveal that cannot be attributed.
    asset = await ready_song(panel)

    # Act
    assert (await panel.client.get(stream_path(asset.id))).status_code == 200

    # Assert
    (row,) = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert row.subject_type in SUBJECT_TYPES
    assert row.subject_id == str(asset.id)
    assert row.actor_username == f"{AdminRole.SUPPORT.value}-account"
    assert row.field_names == ["assets.storage_key"]
    assert row.record_count == 1
    assert row.actor_id is not None


async def test_reading_the_lyric_sheet_twice_is_audited_twice(panel: Panel) -> None:
    # Arrange — the audio window is for range requests. One request returns the whole sheet,
    # so a second read is a second disclosure and gets its own row and its own charge.
    asset = await ready_lyric_sheet(panel)

    # Act
    assert (await panel.client.get(text_path(asset.id))).status_code == 200
    assert (await panel.client.get(text_path(asset.id))).status_code == 200

    # Assert
    rows = await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)
    assert len(rows) == 2
    assert {row.field_names and tuple(row.field_names) for row in rows} == {("assets.payload",)}


# ---------------------------------------------------------------------------
# §12.3 — the audit row is COMMITTED before the read
# ---------------------------------------------------------------------------
async def test_the_audit_row_survives_a_read_that_then_fails(panel: Panel) -> None:
    # Arrange — the test that bites. "Stream, then assert the row exists" passes whether the
    # row was committed before the read or written into the request's transaction after it.
    # So the read is made to FAIL after the audit call: the row exists on disk only if it was
    # committed independently, because the request's transaction is rolled back by the
    # ``ProblemError`` this raises. That is precisely the case §12.3's sentence exists for —
    # "a reveal that then errors is still attributable".
    #
    # It matters twice over for a stream: a yield dependency's exit runs AFTER a
    # ``StreamingResponse`` body is consumed, so a row written into the request transaction
    # would not commit until the operator stopped playing.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act — the row is there, the bytes are not.
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 404
    (row,) = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert row.subject_id == str(asset.id)
    assert row.outcome.value == "ok"


# ---------------------------------------------------------------------------
# §12.3 — the budget, charged per play rather than per request
# ---------------------------------------------------------------------------
def records_key(username: str, now: datetime) -> str:
    return reveal_budget_key(RevealBudgetScope.RECORDS, username=username, now=now)


def records_charged(panel: Panel, username: str, now: datetime) -> int:
    """Units charged to this actor's record budget, whichever clock hour they landed in.

    Summed over the namespace rather than read off one key: the hourly bucket is
    epoch-aligned too, and a test that pinned one key would be asserting what time it is.
    """
    namespace = records_key(username, now).rsplit(":", 2)[0]
    return sum(count for key, count in panel.limits.counts.items() if key.startswith(namespace))


async def test_the_budget_is_charged_once_per_window_not_once_per_request(
    panel: Panel, clock: Clock
) -> None:
    # Arrange — the defect §12.3 says the review forced a correction for, in its audio form:
    # a budget charged per range request measures HTTP traffic, not exposure.
    asset = await ready_song(panel)
    username = f"{AdminRole.SUPPORT.value}-account"
    clock.room_for(ASSET_STREAM_WINDOW_S, _PLAY_REQUESTS * _PLAY_GAP_S)

    # Act
    for _ in range(5):
        assert (await panel.client.get(stream_path(asset.id))).status_code == 200
        clock.advance(_PLAY_GAP_S)

    # Assert
    assert records_charged(panel, username, clock.now()) == 1


async def test_a_spent_budget_refuses_the_play_with_a_429_and_a_retry_after(
    panel: Panel,
) -> None:
    # Arrange — the counter is pre-loaded rather than spent through the route, because
    # spending it through the route would need two hundred distinct assets and would be
    # testing the loop rather than the ceiling.
    asset = await ready_song(panel)
    username = f"{AdminRole.SUPPORT.value}-account"
    ceiling = panel.container.settings.admin_reveal_records_per_hour
    panel.limits.counts[records_key(username, utc_now())] = ceiling

    # Act
    response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 429
    assert response.json()["error"]["code"] == AdminErrorCode.REVEAL_BUDGET_EXHAUSTED.value
    assert int(response.headers["retry-after"]) > 0
    assert await audit_rows(panel.container, AuditAction.ASSET_STREAM) == []


async def test_a_refused_play_gives_its_window_back(panel: Panel) -> None:
    # Arrange — the bypass this closes: the window is claimed before the budget is charged, so
    # a 429 that left the claim standing would let the very next request inside those ten
    # minutes stream un-audited and un-charged. Nothing was disclosed, so nothing is spent.
    asset = await ready_song(panel)
    username = f"{AdminRole.SUPPORT.value}-account"
    key = records_key(username, utc_now())
    panel.limits.counts[key] = panel.container.settings.admin_reveal_records_per_hour

    # Act — refused, then the budget is restored and the same asset is asked for again.
    refused = await panel.client.get(stream_path(asset.id))
    panel.limits.counts[key] = 0
    allowed = await panel.client.get(stream_path(asset.id))

    # Assert — the retry is audited and charged, which it would not be if the refusal had
    # burned the window.
    assert refused.status_code == 429
    assert allowed.status_code == 200
    assert len(await audit_rows(panel.container, AuditAction.ASSET_STREAM)) == 1
    assert panel.limits.counts[key] == 1


# ---------------------------------------------------------------------------
# Range parsing, as a pure function
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("header", "total", "expected"),
    [
        (None, 100, (RangeOutcome.ABSENT, 0, 0)),
        ("bytes=0-99", 1000, (RangeOutcome.SATISFIABLE, 0, 99)),
        # Clamped, not refused: asking for more than there is is a satisfiable question.
        ("bytes=0-99", 50, (RangeOutcome.SATISFIABLE, 0, 49)),
        ("bytes=10-", 50, (RangeOutcome.SATISFIABLE, 10, 49)),
        ("bytes=-10", 50, (RangeOutcome.SATISFIABLE, 40, 49)),
        ("bytes=-500", 50, (RangeOutcome.SATISFIABLE, 0, 49)),
        ("bytes=49-49", 50, (RangeOutcome.SATISFIABLE, 49, 49)),
        # The only shape that is unsatisfiable: a first byte at or past the end.
        ("bytes=999999-", 50, (RangeOutcome.UNSATISFIABLE, 0, 0)),
        ("bytes=50-60", 50, (RangeOutcome.UNSATISFIABLE, 0, 0)),
        ("bytes=-0", 50, (RangeOutcome.UNSATISFIABLE, 0, 0)),
        ("bytes=0-0", 0, (RangeOutcome.UNSATISFIABLE, 0, 0)),
        ("bytes=10-5", 50, (RangeOutcome.UNSATISFIABLE, 0, 0)),
        # Ignored rather than refused (RFC 9110 §14.2): a 416 for a range this server simply
        # does not implement would break a client that was entitled to send it.
        ("bytes=0-9, 20-29", 50, (RangeOutcome.ABSENT, 0, 0)),
        ("items=0-9", 50, (RangeOutcome.ABSENT, 0, 0)),
        ("bytes=-", 50, (RangeOutcome.ABSENT, 0, 0)),
        ("nonsense", 50, (RangeOutcome.ABSENT, 0, 0)),
        # Bounded digits, so a header of ten thousand nines is a parse failure rather than a
        # bignum allocation.
        ("bytes=" + "9" * 40 + "-", 50, (RangeOutcome.ABSENT, 0, 0)),
    ],
    ids=repr,
)
def test_parse_range_resolves_every_form_against_the_real_length(
    header: str | None, total: int, expected: tuple[RangeOutcome, int, int]
) -> None:
    # Arrange / Act
    parsed = parse_range(header, total=total)

    # Assert
    assert (parsed.outcome, parsed.start, parsed.last) == expected


def test_a_satisfiable_range_reports_its_own_length_and_header() -> None:
    # Arrange / Act
    parsed = parse_range("bytes=0-99", total=1000)

    # Assert — the two numbers a 206 must agree on.
    assert parsed.length == 100
    assert parsed.content_range(total=1000) == "bytes 0-99/1000"


# ---------------------------------------------------------------------------
# The metadata routes are unchanged by any of this
# ---------------------------------------------------------------------------
async def test_the_metadata_surface_still_carries_no_lyric_and_no_name(panel: Panel) -> None:
    # Arrange — the media routes are new; the promise the list page makes is not. ``payload``
    # is the whole song in the customer's own words, and §6.7 routes free text through the
    # audited reveal alone.
    asset = await ready_lyric_sheet(panel)

    # Act
    listed = await panel.client.get(ASSETS_PATH)
    detail = await panel.client.get(f"{ASSETS_PATH}/{asset.id}")

    # Assert
    for response in (listed, detail):
        assert response.status_code == 200
        assert LYRIC_LINE not in response.text
        assert RECIPIENT_NAME not in response.text


def test_every_media_builder_the_package_exports_is_reachable() -> None:
    # Arrange / Act / Assert — the enumeration test proves the routes are mounted; this proves
    # the builder is exported, which is the half that catches "written, tested, never wired".
    assert "build_asset_media_router" in routers_package.__all__


# ---------------------------------------------------------------------------
# The failure paths that would otherwise fail open, invisibly
# ---------------------------------------------------------------------------
#: The reveal window's own key namespace, derived rather than typed so the fakes below break
#: exactly the counter under test. Breaking every counter would take the login limiter down
#: with it and the request would never reach a handler at all.
WINDOW_NAMESPACE: Final[str] = reveal_window_key(
    username="probe", asset_id=UUID(int=0), now=NOW, window_s=ASSET_STREAM_WINDOW_S
).rsplit(":", 3)[0]


class BrokenWindowStore(MemoryRateLimits):
    """A counter store whose reveal-window operations fail, so a fail-open can be seen.

    Only one method, and only for one namespace. A store that failed everything would be
    indistinguishable from a container that was never wired, and the two have opposite
    consequences.
    """

    def __init__(self, *, broken: str) -> None:
        super().__init__()
        self.broken = broken

    def _refuses(self, key: str, operation: str) -> bool:
        return self.broken == operation and key.startswith(WINDOW_NAMESPACE)

    async def increment(self, key: str, *, ttl_s: int) -> int:
        if self._refuses(key, "increment"):
            raise ConnectionError("the window counter is unavailable")
        return await super().increment(key, ttl_s=ttl_s)

    async def refund(self, key: str, *, ttl_s: int) -> None:
        if self._refuses(key, "refund"):
            raise ConnectionError("the window counter is unavailable")
        await super().refund(key, ttl_s=ttl_s)


def logged_events(caplog: pytest.LogCaptureFixture, logger: str) -> set[str]:
    """The ``event`` field of every record from one logger.

    Read off the record rather than out of ``caplog.text``: ``extra`` never reaches the
    formatted message, so a substring search over the text would pass for the wrong reason
    (the traceback happens to contain the words) or fail for the right one.
    """
    return {str(getattr(record, "event", "")) for record in caplog.records if record.name == logger}


@pytest.fixture
async def broken_window_panel(tmp_path: Path) -> AsyncIterator[Panel]:
    """The panel again, with the ten-minute window's counter unable to answer."""
    settings = make_settings(admin_step_up_grace_seconds=LONG_GRACE_S)
    limits = BrokenWindowStore(broken="increment")
    archive = tmp_path / ARCHIVE_DIRNAME
    archive.mkdir()
    async with open_container(settings, FakeRedis(), limits) as built:
        container = dataclasses.replace(built, storage=LocalFileStorage(archive))
        async with open_client(container) as http:
            yield Panel(container=container, client=http, archive=archive, limits=limits)


async def test_a_window_counter_that_cannot_answer_audits_rather_than_skipping(
    broken_window_panel: Panel, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — the direction matters and only one of the two is safe. "Unknown" must mean
    # "treat this as a first play", so the reveal is audited and charged; answering "not the
    # first" would hand out an unaudited, unbudgeted stream every time Redis blinked, and the
    # suite would stay green because nothing raised.
    asset = await ready_song(broken_window_panel)

    # Act
    with caplog.at_level(logging.ERROR, logger=_SERVICE_LOGGER):
        response = await broken_window_panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 200
    assert len(await audit_rows(broken_window_panel.container, AuditAction.ASSET_STREAM)) == 1
    assert "admin.asset.window_store_unavailable" in logged_events(caplog, _SERVICE_LOGGER)


@pytest.fixture
async def broken_refund_panel(tmp_path: Path) -> AsyncIterator[Panel]:
    settings = make_settings(admin_step_up_grace_seconds=LONG_GRACE_S)
    limits = BrokenWindowStore(broken="refund")
    archive = tmp_path / ARCHIVE_DIRNAME
    archive.mkdir()
    async with open_container(settings, FakeRedis(), limits) as built:
        container = dataclasses.replace(built, storage=LocalFileStorage(archive))
        async with open_client(container) as http:
            yield Panel(container=container, client=http, archive=archive, limits=limits)


async def test_a_window_claim_that_cannot_be_released_still_refuses_cleanly(
    broken_refund_panel: Panel, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — the release is best-effort by construction: the claim carries its own window
    # in the key and expires with it, so a failed refund costs at most one un-audited replay
    # inside ten minutes. What it must never do is turn a 429 into a 500.
    asset = await ready_song(broken_refund_panel)
    username = f"{AdminRole.SUPPORT.value}-account"
    ceiling = broken_refund_panel.container.settings.admin_reveal_records_per_hour
    broken_refund_panel.limits.counts[records_key(username, utc_now())] = ceiling

    # Act
    with caplog.at_level(logging.ERROR, logger=_SERVICE_LOGGER):
        response = await broken_refund_panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 429
    assert "admin.asset.window_release_failed" in logged_events(caplog, _SERVICE_LOGGER)


async def test_a_lyric_row_with_no_payload_is_a_404_after_the_reveal_is_audited(
    panel: Panel,
) -> None:
    # Arrange — a lyric sheet written before ``payload`` was populated, or one whose text has
    # been purged. 404, not 500 — and the reveal is still on the record, because the audit
    # row is committed before anything is read.
    order = await seed_order(panel.container)
    asset = await seed_asset(
        panel.container,
        order=order,
        kind=AssetKind.LYRIC_SHEET,
        path=f"/srv/hbd/var/workspace/{order.id}/lyrics.txt",
        mime=LYRIC_SHEET_MIME,
        payload=None,
    )
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    response = await panel.client.get(text_path(asset.id))

    # Assert
    assert response.status_code == 404
    assert len(await audit_rows(panel.container, AuditAction.REVEAL_PERSONAL)) == 1


async def test_a_lyric_payload_that_no_longer_validates_is_a_404_not_a_500(
    panel: Panel, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — a stored shape that stopped matching its model is a data incident on one row,
    # and it must not look like the panel being down.
    order = await seed_order(panel.container)
    asset = await seed_asset(
        panel.container,
        order=order,
        kind=AssetKind.LYRIC_SHEET,
        path=f"/srv/hbd/var/workspace/{order.id}/lyrics.txt",
        mime=LYRIC_SHEET_MIME,
        payload={"title": "only half a draft"},
    )
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    with caplog.at_level(logging.ERROR, logger=_SERVICE_LOGGER):
        response = await panel.client.get(text_path(asset.id))

    # Assert
    assert response.status_code == 404
    assert "admin.asset.payload_invalid" in logged_events(caplog, _SERVICE_LOGGER)


async def test_an_operator_username_the_audit_layer_refuses_still_leaves_a_row(
    panel: Panel, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — ``_CREDENTIAL_SHAPES`` refuses any run of 40+ ``[A-Za-z0-9_-]`` characters, so
    # a long machine-generated operator username trips the audit boundary. §9.1's rule is that
    # an unaudited reveal must not happen, and ``audit_sink``'s rule is that the *event* stays
    # recorded even when the identifier cannot be. Both hold: the row is written with a
    # placeholder rather than the reveal proceeding unrecorded.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=SONG_BYTES)
    username = "svc-" + "a" * 44
    await create_account(panel.container, username=username, role=AdminRole.SUPPORT)
    assert (await sign_in(panel.client, username=username, password=PASSWORD)).status_code == 200
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    with caplog.at_level(logging.ERROR, logger=_SERVICE_LOGGER):
        response = await panel.client.get(stream_path(asset.id))

    # Assert
    assert response.status_code == 200
    (row,) = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert row.actor_username != username
    assert "admin.audit.value_refused" in logged_events(caplog, _SERVICE_LOGGER)


async def test_a_zero_byte_object_is_an_empty_200_and_an_unsatisfiable_range(
    panel: Panel,
) -> None:
    # Arrange — a truncated archive write leaves a file with nothing in it, and the two
    # answers have to stay separate: with no ``Range`` there is nothing to refuse, so it is a
    # 200 with an empty body; with one, every range of an empty object is unsatisfiable, so
    # it is a 416. Neither goes through ``open_range``'s iterator, which owns a file handle
    # and would have nothing to yield.
    order = await seed_order(panel.container)
    asset = await seed_asset(panel.container, order=order)
    write_object(panel, order_id=order.id, filename=SONG_FILENAME, data=b"")
    await signed_in(panel)
    assert (await step_up(panel, asset.id)).status_code == 200

    # Act
    whole = await panel.client.get(stream_path(asset.id))
    ranged = await panel.client.get(stream_path(asset.id), headers={"Range": "bytes=0-9"})

    # Assert
    assert whole.status_code == 200
    assert whole.content == b""
    assert whole.headers["content-length"] == "0"
    assert ranged.status_code == 416
    assert ranged.headers["content-range"] == "bytes */0"
