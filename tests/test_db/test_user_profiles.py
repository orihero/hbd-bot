"""``SqlUserProfiles`` against a real database: what it writes, and what it refuses.

This store is the only writer of the one table in the schema that holds a phone number, a
person's name and a photograph of their face, and the only thing that erases them. So the
tests here are about refusals at least as much as about writes: a number that was not stored
under a "thank you, saved" screen, a row claiming an avatar whose bytes were never written, a
``/forget`` that deletes an operator's block along with the number it was asked to erase —
each of those is a defect that a suite testing only the happy path reports as green.

Two structural facts are asserted rather than assumed, because both were decisions:

* **``ui_language`` is READ here and WRITTEN by ``record_language`` (C0-1).** The column stays
  on ``users``, which is DDL-frozen and must survive ``/forget``, so ``get`` JOINs it back in.
  A test that only round-tripped the language through this store would pass with the column
  on either table and prove nothing about which one it is on.
* **``record_language`` is authoritative and an order is not (C0-13 / C1-1).** One column,
  two writers, and only one of them is evidence about which language a human reads in.

The clock is injected and pinned, because three columns here are write-once —
``language_chosen_at``, ``onboarded_at``, ``created_at`` — and "a second call left this alone"
is not assertable against a clock that moves on its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import bayram.storage
from bayram.contracts import Language, Ok, Result, StoredObject, err, is_err, is_ok, ok
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from bayram.db.user_profiles import SqlUserProfiles
from bayram.db.users_sql import ensure_user
from bayram.errors import StorageError
from bayram.user_profiles import (
    AVATAR_MIME,
    UserProfile,
    UserProfileStore,
    avatar_key,
    normalise_phone,
)
from tests.test_db.conftest import MovableClock

#: Mid-day, so a test that advances a day cannot pass by landing on a boundary.
_NOON: Final[datetime] = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

_ALICE: Final[int] = 71_001
_BOB: Final[int] = 71_002

#: The canonical spelling :func:`bayram.user_profiles.normalise_phone` produces. The store trusts
#: what it is handed (there is exactly one definition of a valid number, and it is not here),
#: so every fixture hands it E.164 exactly as onboarding would.
_PHONE: Final[str] = "+998901234542"
_OTHER_PHONE: Final[str] = "+998901234599"

#: A profile photo's worth of bytes. Content is irrelevant; identity is not — the storage
#: assertions below are about WHICH bytes landed under which key.
_IMAGE: Final[bytes] = b"\xff\xd8\xff\xe0 a face"


class _MemoryStorage:
    """A ``Storage`` that keeps objects in a dict and can be told to refuse a ``put``.

    A real :class:`bayram.storage.LocalFileStorage` over ``tmp_path`` would work for the happy
    path and could not produce the failure that matters: a ``put`` that returns ``Err``. That
    is not an exotic case — it is a full disk, a revoked bucket credential, a network blip —
    and it is the one that decides whether the row is allowed to claim an avatar. So the
    double exists to make that arm reachable, and the happy path uses the same double so that
    both arms are the same code path with one flag flipped.

    ``delete`` records rather than removes on purpose: ``/forget``'s contract is that the key
    is handed for deletion UNCONDITIONALLY, whether or not the row claimed an avatar, and an
    assertion about what was attempted is the only way to see a key that was never handed
    over.
    """

    def __init__(self, *, put_error: StorageError | None = None) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []
        self._put_error = put_error

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]:
        if self._put_error is not None:
            return err(self._put_error)
        self.objects[key] = (data, content_type)
        return ok(
            StoredObject(key=key, size_bytes=len(data), sha256="a" * 64, content_type=content_type)
        )

    async def get(self, key: str) -> Result[bytes]:
        raise NotImplementedError

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]:
        raise NotImplementedError

    async def delete(self, key: str) -> Result[None]:
        self.deleted.append(key)
        self.objects.pop(key, None)
        return ok(None)

    async def size(self, key: str) -> Result[int]:
        raise NotImplementedError

    async def open_range(self, key: str, *, start: int, end: int) -> Result[AsyncIterator[bytes]]:
        raise NotImplementedError


def _store(
    sessions: async_sessionmaker[AsyncSession],
    *,
    storage: _MemoryStorage | None = None,
    clock: MovableClock | None = None,
) -> SqlUserProfiles:
    return SqlUserProfiles(
        sessions, storage=storage or _MemoryStorage(), clock=clock or MovableClock(_NOON)
    )


async def _unwrap(result: Result[UserProfile]) -> UserProfile:
    """One profile, unwrapped. Every call in this module that uses it expects an ``Ok``."""
    assert isinstance(result, Ok), result
    return result.value


async def _profile_of(store: SqlUserProfiles, telegram_user_id: int) -> UserProfile | None:
    fetched = await store.get(telegram_user_id)
    assert isinstance(fetched, Ok), fetched
    return fetched.value


async def _user_row(
    sessions: async_sessionmaker[AsyncSession], telegram_user_id: int
) -> UserRow | None:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(UserRow).where(UserRow.telegram_user_id == telegram_user_id)
            )
        ).scalar_one_or_none()


async def _profile_rows(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        counted = await session.scalar(sa.select(sa.func.count()).select_from(UserProfileRow))
    return int(counted or 0)


# ---------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------
def test_the_store_satisfies_the_user_profile_store_protocol(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The bot holds the protocol, never this class. ``runtime_checkable`` checks presence only.

    Which is exactly why this assertion is cheap and still worth making: a method renamed here
    and not in ``bayram.user_profiles`` would leave the bot calling a name that no longer exists,
    and ``mypy --strict`` only catches that where a call site is annotated with the protocol.
    """
    # Arrange / Act
    is_conformant = isinstance(_store(sessions), UserProfileStore)

    # Assert
    assert is_conformant


async def test_get_answers_none_for_somebody_who_has_never_spoken_to_us(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``Ok(None)`` is the NORMAL answer and must never be dressed up as a failure.

    There is no backfill (D11), so on the deploy after revision 0014 this is the answer for
    the entire installed base, and it is the answer for every account since its ``/forget``. A
    caller fails OPEN on ``Err`` (C1-5) — if this returned one for an unknown account, every
    first-time customer would be waved past onboarding and the bot would hold no number to
    deliver their song to.
    """
    # Arrange
    store = _store(sessions)

    # Act
    fetched = await store.get(_ALICE)

    # Assert — Ok, and empty. Not an Err, and not a raise.
    assert is_ok(fetched)
    assert fetched.value is None


# ---------------------------------------------------------------------------
# record_language — the first write of an account's life
# ---------------------------------------------------------------------------
async def test_record_language_creates_both_rows_and_makes_the_language_readable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Two rows, one transaction, and the language read back through the JOIN (C0-1).

    ``users`` and ``user_profiles`` are written together because the profile's primary key is
    a foreign key onto the account: had they been two transactions, a crash between them would
    leave an account that exists, has a language, and is never asked for a phone number again
    by a gate reading a row that is not there.

    The language is asserted through ``get`` rather than by reading ``users.ui_language``
    directly, because ``UserProfile.ui_language`` coming back from the JOIN is the contract —
    the column stays on ``users`` (DDL-frozen, must survive ``/forget``) and this store is the
    only thing that puts the two halves back together.
    """
    # Arrange
    store = _store(sessions)

    # Act
    profile = await _unwrap(await store.record_language(_ALICE, ui_language=Language.RU))

    # Assert — the returned profile and the stored one agree, and both carry the language.
    assert profile.telegram_user_id == _ALICE
    assert profile.ui_language is Language.RU
    assert profile.language_chosen_at == _NOON
    assert profile.phone_e164 is None
    assert profile.is_onboarded is False

    user = await _user_row(sessions, _ALICE)
    assert user is not None
    assert user.ui_language is Language.RU
    assert profile.user_id == user.id

    stored = await _profile_of(store, _ALICE)
    assert stored is not None
    assert stored.ui_language is Language.RU


async def test_record_language_is_idempotent_and_keeps_the_first_choice_stamp(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Changing the language in Settings must not restart "when did they first choose one".

    ``language_chosen_at`` answers a cohort question. If every later change moved it, an
    account that has changed language four times would look brand new to whoever reads the
    admin list, and the only evidence that the first choice happened would be overwritten by
    the least interesting one.
    """
    # Arrange — a first choice at noon, and a second choice a day later.
    clock = MovableClock(_NOON)
    store = _store(sessions, clock=clock)
    await store.record_language(_ALICE, ui_language=Language.RU)
    later = clock.advance(days=1)

    # Act
    profile = await _unwrap(await store.record_language(_ALICE, ui_language=Language.EN))

    # Assert — the language moved, the first-choice stamp did not, and there is still one row.
    assert profile.ui_language is Language.EN
    assert profile.language_chosen_at == _NOON
    assert profile.updated_at == later
    assert await _profile_rows(sessions) == 1


async def test_record_language_is_authoritative_and_an_order_is_not(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """C0-13 / C1-1, in both directions, on one column with two writers.

    An order is evidence that an account is ALIVE; it is not evidence about which language its
    owner READS in. ``repository._create_order`` therefore calls ``ensure_user`` with
    ``is_language_authoritative=False`` and a brief's ``ui_language`` — a field the wizard
    frequently fills from a fallback rather than from a choice — while ``record_language``
    passes ``True``.

    Collapse the two and the customer loses a column they can see: they pick Russian in
    Settings, order a song in English, and every screen answers them in English afterwards
    with nothing on it explaining why. Both directions are asserted because the defect is
    symmetrical — a flag that never grants authority is "Settings saves nothing", which is
    just as silent and takes just as long for a customer to report.
    """
    # Arrange — the customer chose Russian.
    store = _store(sessions)
    await store.record_language(_ALICE, ui_language=Language.RU)

    # Act — the order path writes the same row with a different language and no authority.
    async with sessions.begin() as session:
        await ensure_user(
            session,
            telegram_user_id=_ALICE,
            ui_language=Language.EN,
            now=_NOON + timedelta(hours=1),
            is_language_authoritative=False,
        )

    # Assert — the choice survived the order.
    after_order = await _profile_of(store, _ALICE)
    assert after_order is not None
    assert after_order.ui_language is Language.RU

    # Act — the customer changes it in Settings, which IS authoritative.
    await store.record_language(_ALICE, ui_language=Language.EN)

    # Assert — this writer, and only this writer, moves the column.
    after_settings = await _profile_of(store, _ALICE)
    assert after_settings is not None
    assert after_settings.ui_language is Language.EN


# ---------------------------------------------------------------------------
# record_contact — the write that makes is_onboarded true
# ---------------------------------------------------------------------------
async def test_record_contact_stores_the_number_and_stamps_the_two_clocks(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The number, the identity fields, and the two timestamps that answer different questions.

    ``is_onboarded`` reads the NUMBER, never ``onboarded_at``: the number is the fallback
    delivery channel, and a language alone buys the customer nothing. Asserting it here is
    what stops the gate from being satisfied by a row that holds no way to reach anybody.
    """
    # Arrange
    store = _store(sessions)
    await store.record_language(_ALICE, ui_language=Language.UZ_LATN)

    # Act
    profile = await _unwrap(
        await store.record_contact(
            _ALICE,
            phone_e164=_PHONE,
            telegram_username="gulomjon",
            first_name="Gʻulomjon",
            last_name="Toshmatov",
        )
    )

    # Assert
    assert profile.phone_e164 == _PHONE
    assert profile.telegram_username == "gulomjon"
    assert (profile.first_name, profile.last_name) == ("Gʻulomjon", "Toshmatov")
    assert profile.phone_shared_at == _NOON
    assert profile.onboarded_at == _NOON
    assert profile.is_onboarded is True


async def test_record_contact_is_idempotent_and_updates_in_place(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The upsert is on ``user_id``, so a re-share updates one row rather than opening a second.

    And the asymmetry between the two clocks is the point. ``phone_shared_at`` MOVES: it is
    the freshness of the number the delivery fallback would dial, and a stale one is how a
    song reaches somebody's old SIM. ``onboarded_at`` does NOT: collapse them and every
    returning customer who updates their number appears in the admin list as newly onboarded,
    which turns the only cohort figure the panel has into noise.

    A dropped ``@username`` is asserted too, because a stored handle is a record of what we
    were told and not a claim about what is true now — a coalescing write would keep showing
    an operator a handle the account no longer has.
    """
    # Arrange — onboarded at noon, re-shares a different number a day later, with no username.
    clock = MovableClock(_NOON)
    store = _store(sessions, clock=clock)
    await store.record_language(_ALICE, ui_language=Language.UZ_LATN)
    await store.record_contact(
        _ALICE,
        phone_e164=_PHONE,
        telegram_username="gulomjon",
        first_name="Gʻulomjon",
        last_name=None,
    )
    later = clock.advance(days=1)

    # Act
    profile = await _unwrap(
        await store.record_contact(
            _ALICE,
            phone_e164=_OTHER_PHONE,
            telegram_username=None,
            first_name="Gʻulomjon",
            last_name=None,
        )
    )

    # Assert — one row, the new number, the moved share clock, the frozen onboarding clock.
    assert await _profile_rows(sessions) == 1
    assert profile.phone_e164 == _OTHER_PHONE
    assert profile.telegram_username is None
    assert profile.phone_shared_at == later
    assert profile.onboarded_at == _NOON


async def test_record_contact_opens_a_row_for_an_account_that_never_answered_the_language(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A customer parked at ``Onboarding.contact`` across a database reset must not dead-end.

    They arrive here with no ``users`` row and no profile row at all, and the profile's primary
    key is a foreign key onto the account — so refusing them would be a dead end no screen can
    escape and no retry can clear. ``ensure_user`` is called with ``ui_language=None`` and no
    authority, because this call genuinely knows nothing about which language anybody reads
    in; inventing one here would be the clobber ``is_language_authoritative`` exists to
    prevent, wearing a third hat.
    """
    # Arrange — nothing at all has ever been written for this account.
    store = _store(sessions)

    # Act
    profile = await _unwrap(
        await store.record_contact(
            _BOB, phone_e164=_PHONE, telegram_username=None, first_name=None, last_name=None
        )
    )

    # Assert — onboarded, and the account was born with the default language rather than a
    # guess derived from a screen that was never shown.
    assert profile.is_onboarded is True
    assert profile.language_chosen_at is None
    user = await _user_row(sessions, _BOB)
    assert user is not None
    assert user.ui_language is Language.UZ_LATN


# ---------------------------------------------------------------------------
# The two pure functions the whole flow is spelled in
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Already canonical.
        ("+998901234542", "+998901234542"),
        # Telegram's ``Contact.phone_number`` routinely arrives with no ``+`` at all.
        ("998901234542", "+998901234542"),
        # Formatted by a carrier, an address book or an iOS contact card.
        ("+998 90 123 45 42", "+998901234542"),
        ("+998-90-123-45-42", "+998901234542"),
        # A non-breaking space is the worst spelling collision there is: invisible in every
        # log line and every admin screen, and matching nothing.
        (" +998 90 123 45 42 ", "+998901234542"),
        # A country code may not start with zero.
        ("+0998901234542", None),
        # Too short and too long: E.164's own bounds, eight to fifteen digits.
        ("+1234567", None),
        ("+1234567890123456", None),
        # Nothing at all, and something that is not a number.
        ("", None),
        ("   ", None),
        ("not a phone", None),
        ("++998901234542", None),
    ],
)
def test_normalise_phone_accepts_e164_and_refuses_everything_else(
    raw: str, expected: str | None
) -> None:
    """One canonical spelling, or a refusal — never a raise and never a second spelling.

    ``None`` is a REFUSAL and not an error: the handler renders ``onboarding.contact.required``
    and asks again. Two spellings of one number are two people as far as an operator's search
    is concerned, and ``user_profiles.phone_e164`` is deliberately unindexed and unfilterable,
    so a duplicate would never be caught by a constraint — normalisation is the only thing
    standing between "one customer" and "two rows nobody can reconcile".

    **The refusals are about SHAPE, and the acceptances are about NOISE, and they are
    different questions.** Punctuation, spaces and a missing ``+`` carry no information and are
    stripped, because Telegram sends numbers in whatever shape the SIM was registered in; a
    parser that refused them would refuse the majority of real contact shares and onboarding
    would dead-end for customers whose only mistake was owning an iPhone. What is refused is a
    string that cannot be a number under E.164 at any spelling.

    Every country is admitted deliberately. A Russian or Kazakh SIM is entirely plausible in
    this market, and a customer must never be told their own phone is invalid.
    """
    # Arrange / Act
    normalised = normalise_phone(raw)

    # Assert
    assert normalised == expected


def test_avatar_key_is_a_fixed_filename_per_user() -> None:
    """``users/{user_id}/avatar.jpg``, and it lives in ``bayram.user_profiles`` and NOT in ``bayram.storage``.

    **The filename is fixed** so a customer who changes their photo is a re-download that
    overwrites the same object. A key carrying ``file_unique_id`` would leave one unreachable
    blob per photo change with nothing recording that it exists — the archive-orphan shape
    ``repository._replace_assets`` documents.

    **It is reconstructible from the id alone**, which is what lets ``/forget`` delete the
    bytes with no ``avatar_storage_key`` column existing anywhere, and lets that delete run
    unconditionally.

    **And it is in the leaf, not in the storage module.**
    ``tests/test_admin/test_asset_stream.py:712`` caps everything the admin package imports
    from ``bayram.storage`` at ``{"LocalFileStorage", "archive_key"}``, and the avatar route must
    rebuild this key server-side rather than trust one off the wire. Defining it in
    ``bayram.storage`` would fail that allowlist the day the route lands, and the cheap way out
    of a failing import cap is to widen the cap — which is the whole point of it gone. So the
    absence is asserted here, where it is a decision, rather than discovered there, where it
    would look like an obstacle.
    """
    # Arrange
    user_id = UUID("11111111-2222-3333-4444-555555555555")

    # Act
    key = avatar_key(user_id)

    # Assert — the exact spelling, keyed on the UUID and not on a Telegram id.
    assert key == f"users/{user_id}/avatar.jpg"
    assert avatar_key(user_id) == key

    # Assert — the builder is the leaf's, and bayram.storage got no edit at all.
    assert avatar_key.__module__ == "bayram.user_profiles"
    assert not hasattr(bayram.storage, "avatar_key")


# ---------------------------------------------------------------------------
# record_avatar — best effort, and the Result seam that keeps it honest
# ---------------------------------------------------------------------------
async def test_record_avatar_writes_the_object_and_the_row_together(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Bytes under the derived key, and three columns describing them, or neither.

    ``avatar_mime`` is stored because ``LocalFileStorage.put`` accepts a content type and
    persists none of it: without the column the admin route would have to GUESS one for a
    blob, and a guessed content type on stored bytes is how an uploaded image becomes stored
    XSS. ``avatar_file_unique_id`` is stored so a later fetch can skip a photo that has not
    changed.
    """
    # Arrange
    storage = _MemoryStorage()
    store = _store(sessions, storage=storage)
    await store.record_language(_ALICE, ui_language=Language.UZ_LATN)
    profile = await _profile_of(store, _ALICE)
    assert profile is not None

    # Act
    recorded = await store.record_avatar(
        _ALICE, image=_IMAGE, mime=AVATAR_MIME, file_unique_id="AgADBAADq6cxG"
    )

    # Assert — the bytes are under the rebuilt key, with the content type the row records.
    assert is_ok(recorded)
    assert storage.objects[avatar_key(profile.user_id)] == (_IMAGE, AVATAR_MIME)

    stored = await _profile_of(store, _ALICE)
    assert stored is not None
    assert stored.avatar_stored_at == _NOON
    assert stored.avatar_mime == AVATAR_MIME
    assert stored.avatar_file_unique_id == "AgADBAADq6cxG"


async def test_a_storage_failure_leaves_no_row_claiming_an_avatar(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The ``Result`` seam, at the one place where ignoring it would be visible to a customer.

    An ``Err`` from the object store must leave ``avatar_stored_at`` NULL. A row that claims an
    avatar whose bytes were never written is a lie the admin panel acts on: the SPA draws an
    ``<img>`` because ``hasAvatar`` is true, the route rebuilds the key, finds nothing, and
    answers 404 — a broken image per affected customer, in a list, with nothing to explain it
    and nothing that will ever repair it.

    And the call still answers ``Ok(None)``: a profile photo is best effort, and failing an
    onboarding over one would stop a customer ordering a song because a bucket was full.
    """
    # Arrange — a store whose object writes always refuse.
    storage = _MemoryStorage(put_error=StorageError("the bucket refused"))
    store = _store(sessions, storage=storage)
    await store.record_language(_ALICE, ui_language=Language.UZ_LATN)

    # Act
    recorded = await store.record_avatar(
        _ALICE, image=_IMAGE, mime=AVATAR_MIME, file_unique_id="AgADBAADq6cxG"
    )

    # Assert — not an error to the caller, and not an avatar to the panel.
    assert is_ok(recorded)
    assert storage.objects == {}
    stored = await _profile_of(store, _ALICE)
    assert stored is not None
    assert stored.avatar_stored_at is None
    assert stored.avatar_mime is None
    assert stored.avatar_file_unique_id is None


async def test_an_unrecognised_content_type_is_discarded_rather_than_stored(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One MIME, defined once, in ``bayram.user_profiles`` — and anything else is dropped.

    If Telegram ever serves WebP profile photos, that must surface as a logged refusal rather
    than as a blob the admin panel serves under a content type it guessed. The route's
    ``AVATAR_MIMES`` allowlist is built from the same constant precisely so the two cannot
    drift: three independent literals would drift in both directions at once and the
    observable result would be "no avatars anywhere", with a fully green suite.
    """
    # Arrange
    storage = _MemoryStorage()
    store = _store(sessions, storage=storage)
    await store.record_language(_ALICE, ui_language=Language.UZ_LATN)

    # Act
    recorded = await store.record_avatar(
        _ALICE, image=_IMAGE, mime="image/webp", file_unique_id="AgADBAADq6cxG"
    )

    # Assert — nothing written anywhere, and still not an error.
    assert is_ok(recorded)
    assert storage.objects == {}
    stored = await _profile_of(store, _ALICE)
    assert stored is not None
    assert stored.avatar_stored_at is None


async def test_an_avatar_that_arrives_before_the_profile_row_is_a_shrug(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """No row to hang it on is not an error either: the fetcher simply ran early.

    Nothing must be written under a key belonging to an account we hold no profile for —
    orphaned bytes at a key nothing references are exactly what ``/forget``'s unconditional
    delete cannot reach, because there is no row left to derive the key from.
    """
    # Arrange
    storage = _MemoryStorage()
    store = _store(sessions, storage=storage)

    # Act
    recorded = await store.record_avatar(
        _BOB, image=_IMAGE, mime=AVATAR_MIME, file_unique_id="AgADBAADq6cxG"
    )

    # Assert
    assert is_ok(recorded)
    assert storage.objects == {}
    assert await _profile_rows(sessions) == 0


# ---------------------------------------------------------------------------
# forget — PD-3, and the reason this table exists at all
# ---------------------------------------------------------------------------
async def test_forget_deletes_the_row_and_the_object_and_leaves_the_users_row_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """PD-3, and the whole argument for a separate table rather than columns on ``users``.

    ``credits.set_blocked`` UPSERTs the ``users`` row so an operator can bar an account that
    never ordered. If the personal data lived on that row, ``/forget`` would either have to
    leave it behind — an erasure that erases nothing — or delete the row, which turns
    ``/forget`` into a self-service unblock that any abuser can repeat forever. Keying a
    separate table on ``users.id`` is what makes both halves of "erase everything about the
    person, keep the operator's decision" true at once, so the block is asserted here beside
    the deletion rather than in a test about blocking.

    The object key is handed for deletion AFTER the row transaction commits, because a
    rollback cannot un-delete a file: bytes removed inside a transaction that then failed
    would be gone while the row describing them lived on, and the panel would serve a broken
    image forever.
    """
    # Arrange — an onboarded customer with an avatar, whom an operator has blocked.
    storage = _MemoryStorage()
    store = _store(sessions, storage=storage)
    await store.record_language(_ALICE, ui_language=Language.RU)
    await store.record_contact(
        _ALICE,
        phone_e164=_PHONE,
        telegram_username="gulomjon",
        first_name="Gʻulomjon",
        last_name="Toshmatov",
    )
    await store.record_avatar(
        _ALICE, image=_IMAGE, mime=AVATAR_MIME, file_unique_id="AgADBAADq6cxG"
    )
    profile = await _profile_of(store, _ALICE)
    assert profile is not None
    async with sessions.begin() as session:
        await session.execute(
            sa.update(UserRow).where(UserRow.telegram_user_id == _ALICE).values(is_blocked=True)
        )

    # Act
    forgotten = await store.forget(_ALICE)

    # Assert — the row and the bytes are gone, and the store now knows nothing about them.
    assert is_ok(forgotten)
    assert await _profile_rows(sessions) == 0
    assert await _profile_of(store, _ALICE) is None
    assert storage.deleted == [avatar_key(profile.user_id)]
    assert storage.objects == {}

    # Assert — the operator's decision survived the data-subject request.
    user = await _user_row(sessions, _ALICE)
    assert user is not None
    assert user.is_blocked is True
    assert user.ui_language is Language.RU


async def test_forget_is_idempotent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A second ``/forget`` is a successful erasure, because there is nothing left to erase.

    Most people who send ``/forget`` never onboarded at all, so "there was nothing" and "I
    deleted it" are the same promise kept — and PD-3 wants the two indistinguishable anyway:
    an operator who could tell "purged" from "never onboarded" would be reading the very fact
    the erasure was supposed to remove.
    """
    # Arrange
    store = _store(sessions)
    await store.record_language(_ALICE, ui_language=Language.RU)
    await store.forget(_ALICE)

    # Act — the customer sends it again, and a stranger sends it for the first time.
    second = await store.forget(_ALICE)
    never_seen = await store.forget(_BOB)

    # Assert
    assert is_ok(second)
    assert is_ok(never_seen)


# ---------------------------------------------------------------------------
# The never-throw facade
# ---------------------------------------------------------------------------
async def test_every_method_returns_err_rather_than_raising_on_a_dead_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One assertion per method, because ``run_guarded`` is applied per method and can be missed.

    Onboarding runs inside aiogram's per-chat FSM isolation lock while a live customer waits.
    A leaked exception there is a handler that never replies and a customer staring at a
    keyboard that does nothing — no error screen, no retry, no way forward — so "the database
    broke" has to arrive as a value the handler can branch on rather than as a traceback.

    The table is dropped out from under a store that already has one, which is the closest a
    unit test gets to the real failure (a dropped connection, a failed-over primary) without
    a second engine. Every method is listed by hand: a facade whose methods each carry their
    own ``run_guarded`` call cannot be checked in aggregate, and the one that was written
    without it would be the one nobody thought to list.
    """
    # Arrange
    storage = _MemoryStorage()
    store = _store(sessions, storage=storage)
    await store.record_language(_ALICE, ui_language=Language.RU)
    async with sessions.begin() as session:
        await session.execute(sa.text("DROP TABLE user_profiles"))

    # Act
    results: dict[str, Result[Any]] = {
        "get": await store.get(_ALICE),
        "record_language": await store.record_language(_ALICE, ui_language=Language.EN),
        "record_contact": await store.record_contact(
            _ALICE, phone_e164=_PHONE, telegram_username=None, first_name=None, last_name=None
        ),
        "record_avatar": await store.record_avatar(
            _ALICE, image=_IMAGE, mime=AVATAR_MIME, file_unique_id="AgADBAADq6cxG"
        ),
        "forget": await store.forget(_ALICE),
    }

    # Assert — a typed Err from every one of them, and no exception escaped.
    for name, result in results.items():
        assert is_err(result), f"{name} did not report the failure as an Err"
