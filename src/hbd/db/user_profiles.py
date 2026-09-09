"""``user_profiles`` over SQLAlchemy: the language, the number, the name and the face.

The shape is :mod:`hbd.db.lyric_budget`'s and :mod:`hbd.db.credits`', copied deliberately
rather than reinvented, because the split is what makes both halves testable and composable:

* the **free functions** below take an ``AsyncSession`` first and positionally, take ``now``
  as a parameter instead of reading a clock, let exceptions propagate, and **never commit**.
  A caller that already owns a transaction composes them into it — which is exactly what
  :meth:`SqlUserProfiles.record_language` does when it runs
  :func:`hbd.db.users_sql.ensure_user`, :func:`upsert_language` and :func:`load_profile` as
  one atomic act. Had they owned their own sessions, an onboarding write could commit a
  ``users`` row and then fail to write the profile, leaving an account that exists, has a
  language, and will never be asked for a phone number again by a gate reading a row that is
  not there.
* :class:`SqlUserProfiles` is the never-throw facade: every public method is one
  :func:`hbd.db.guard.run_guarded` delegation owning exactly one
  ``async with self._sessions.begin()`` (two, in the one case that must sequence an object
  write between them — see :meth:`SqlUserProfiles.record_avatar`).

**Why ``now`` is a parameter and the clock is a constructor argument.** Three columns here
are write-once-or-not-at-all — ``language_chosen_at``, ``onboarded_at``, ``created_at`` — and
a test that cannot pin the instant cannot assert that a second call left them alone. The
facade reads its clock ONCE per operation and hands the same value to every statement in the
transaction, so a row never records itself as created and updated a millisecond apart.

This module is the only thing in the tree that knows a ``user_profiles`` row exists. The bot
holds :class:`hbd.user_profiles.UserProfileStore`, a protocol over ``Result``, and the admin
panel reaches the same table through :mod:`hbd.db.admin.users`' read-only projections.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, Result, Storage, is_err
from hbd.db.base import utc_now
from hbd.db.credit_sql import rowcount_of, upsert_statement
from hbd.db.guard import not_found, run_guarded
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from hbd.db.users_sql import ensure_user
from hbd.logging import get_logger
from hbd.user_profiles import AVATAR_MIME, UserProfile, avatar_key

__all__ = [
    # The facade the bot holds through ``hbd.user_profiles.UserProfileStore``.
    "SqlUserProfiles",
    # Session-first statements, composable into a transaction the caller owns.
    "ProfileErasure",
    "load_profile",
    "upsert_language",
    "upsert_contact",
    "erase_profile",
]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProfileErasure:
    """What one ``/forget`` removed, so the log is a fact and not a guess.

    Two fields rather than a bare count because the erasure has two halves that commit at
    different moments: the row goes with the transaction, the bytes go after it. When a
    customer asks months later whether their request was honoured, the answer has to be
    readable in the log of the process that honoured it, and "we deleted a profile" without
    saying whether an object key was handed on for deletion answers only half the question.

    ``profiles_deleted == 0`` is an ordinary, successful answer: most people who send
    ``/forget`` never onboarded, so there is nothing of theirs to erase, and "there was
    nothing" and "I deleted it" are the same promise kept. Nothing branches on either field;
    they are diagnostic, exactly as :class:`hbd.db.credit_erasure.CreditErasure`'s are.
    """

    #: ``user_profiles`` rows removed. Zero or one — ``telegram_user_id`` is ``UNIQUE``.
    profiles_deleted: int
    #: Object keys the caller must now delete, AFTER its transaction has committed. Non-empty
    #: whenever a row was deleted, whether or not that row claimed an avatar; see
    #: :func:`erase_profile` for why that is the safe direction and not a wasted call.
    storage_keys: tuple[str, ...]


async def load_profile(session: AsyncSession, telegram_user_id: int) -> UserProfile | None:
    """The whole profile for one Telegram account, or ``None`` when there is no row.

    **The join is INNER and that is a statement about the schema, not an optimisation.**
    ``user_profiles.user_id`` is simultaneously the primary key and a foreign key onto
    ``users.id``, so a profile row without its ``users`` row cannot exist; a LEFT join would
    invent a ``None`` branch for ``ui_language`` that no database state can reach, and every
    reader downstream would have to carry a fallback for it. :attr:`UserProfile.ui_language`
    is a plain ``Language`` precisely because this join cannot fail to find one.

    **``populate_existing=True`` is load-bearing.** Inside :meth:`SqlUserProfiles.record_language`
    and :meth:`SqlUserProfiles.record_contact` this read runs AFTER a Core upsert in the same
    transaction, and without it the ORM identity map hands back the row as it was BEFORE that
    write — so the settings screen would redraw from the value the customer just replaced, and
    the "thank you, your number is saved" screen would be rendered from a profile that still
    says ``phone_e164 is None``. :func:`hbd.db.lyric_budget._writes_today` documents the same
    trap and escapes it the other way, by selecting columns instead of the entity.

    That columns-only alternative was considered here and lost. Thirteen columns read by
    position is one column rename away from being silently wrong — the values would still
    unpack, they would just land in the wrong fields, and a phone number in the
    ``telegram_username`` slot is a defect no type checker can see. Mapping the ORM entity
    attribute by attribute costs one execution option and fails loudly instead.
    """
    row = (
        await session.execute(
            sa.select(UserProfileRow, UserRow.ui_language)
            .join(UserRow, UserRow.id == UserProfileRow.user_id)
            .where(UserProfileRow.telegram_user_id == telegram_user_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        return None
    profile, ui_language = row._tuple()
    return UserProfile(
        user_id=profile.user_id,
        telegram_user_id=profile.telegram_user_id,
        ui_language=ui_language,
        phone_e164=profile.phone_e164,
        telegram_username=profile.telegram_username,
        first_name=profile.first_name,
        last_name=profile.last_name,
        avatar_file_unique_id=profile.avatar_file_unique_id,
        avatar_mime=profile.avatar_mime,
        avatar_stored_at=profile.avatar_stored_at,
        language_chosen_at=profile.language_chosen_at,
        phone_shared_at=profile.phone_shared_at,
        onboarded_at=profile.onboarded_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def upsert_language(
    session: AsyncSession,
    *,
    user_id: UUID,
    telegram_user_id: int,
    now: datetime,
) -> None:
    """Open the profile row if it is not there, and stamp the language choice on it.

    An UPSERT rather than a SELECT-then-INSERT for the reason
    :func:`hbd.db.users_sql.ensure_user` states about the row above it: this is the FIRST
    write of an account's life, made while a live customer waits on the answer, and
    ``run_guarded`` classifies an ``IntegrityError`` as terminal and never retries it. A
    conditional insert that lost a race here would fail the one write in the system that has
    no second chance.

    **``language_chosen_at`` is write-once, via ``COALESCE`` in the ``SET`` clause.** The
    column answers "when did this account first tell us a language", so a customer changing
    the language in Settings must not move it — otherwise the evidence that the first choice
    happened is overwritten by every later one, and an account that has chosen four times
    looks new to whoever reads the admin list. A bare column reference in ``SET`` means the
    STORED row on Postgres and SQLite alike (``excluded`` is the proposed one);
    :func:`hbd.db.lyric_budget.claim_write` states the same fact and its ``CASE`` depends on
    it, so the ``COALESCE`` really does read the value that is already there rather than the
    one being inserted. After PD-3's ``/forget`` the row is gone, so the next answer
    legitimately starts the clock again — which is the intended reading of "first", because
    the erasure means we know nothing about any earlier one.

    ``telegram_username``, the names and the number are deliberately absent from both halves.
    This call knows only which language was picked; writing ``None`` over a number a customer
    shared last week would make a settings change an erasure.

    ``created_at``/``updated_at`` are set by hand because ``TimestampMixin``'s ``default`` and
    ``onupdate`` are ORM-flush and UPDATE-statement hooks respectively, and this is neither:
    it is a Core ``INSERT … ON CONFLICT``, so without the explicit values a row bumped daily
    would keep the timestamp of the day it was created.
    """
    await session.execute(
        upsert_statement(
            session,
            UserProfileRow,
            {
                "user_id": user_id,
                "telegram_user_id": telegram_user_id,
                "language_chosen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["user_id"],
            set_={
                "telegram_user_id": telegram_user_id,
                "updated_at": now,
                # The stored value wins whenever there is one — see the docstring.
                "language_chosen_at": sa.func.coalesce(UserProfileRow.language_chosen_at, now),
            },
        )
    )


async def upsert_contact(
    session: AsyncSession,
    *,
    user_id: UUID,
    telegram_user_id: int,
    phone_e164: str,
    telegram_username: str | None,
    first_name: str | None,
    last_name: str | None,
    now: datetime,
) -> None:
    """Store the shared contact card. This is the write that makes ``is_onboarded`` true.

    Same statement shape as :func:`upsert_language`, and an upsert for the same reason: a
    customer whose FSM was parked at ``Onboarding.contact`` across a database reset arrives
    here with no profile row at all, and refusing them would be a dead end no screen can
    escape.

    **The asymmetry between the two timestamps is the point of the function.**
    ``phone_shared_at`` answers "when did they last hand us THIS number", so it moves on every
    re-share — it is the freshness of the number the delivery fallback would dial, and a stale
    one is how a song reaches somebody's old SIM. ``onboarded_at`` answers "since when has
    this account been able to order", so it is written once and then ``COALESCE``d: collapse
    the two and every returning customer who updates their number appears in the admin list as
    newly onboarded, which turns the only cohort figure the panel has into noise.

    **Nothing is re-validated here, deliberately.** The caller has already checked that
    ``message.contact.user_id == message.from_user.id`` — Telegram lets anyone forward a third
    party's contact card, and a stranger's number stored as this customer's is a song
    delivered to the wrong person — and has already canonicalised the number through
    :func:`hbd.user_profiles.normalise_phone`. A second definition of "a valid number" living
    down here would drift from the first one, and the day it does the silent one wins.

    The identity fields are nullable on both halves on purpose: an account that drops its
    ``@username`` between two shares must stop claiming one, because a stored handle is a
    record of what we were told and not a claim about what is true now.
    """
    await session.execute(
        upsert_statement(
            session,
            UserProfileRow,
            {
                "user_id": user_id,
                "telegram_user_id": telegram_user_id,
                "phone_e164": phone_e164,
                "telegram_username": telegram_username,
                "first_name": first_name,
                "last_name": last_name,
                "phone_shared_at": now,
                "onboarded_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["user_id"],
            set_={
                "telegram_user_id": telegram_user_id,
                "phone_e164": phone_e164,
                "telegram_username": telegram_username,
                "first_name": first_name,
                "last_name": last_name,
                # Moves on a re-share: it is the freshness of the number we would dial.
                "phone_shared_at": now,
                # Does NOT move: "onboarded since" is asked once and answered forever.
                "onboarded_at": sa.func.coalesce(UserProfileRow.onboarded_at, now),
                "updated_at": now,
            },
        )
    )


async def erase_profile(session: AsyncSession, *, telegram_user_id: int) -> ProfileErasure:
    """Delete one account's profile row and report the object key its bytes live under. PD-3.

    **A DELETE, not a blanking.** Nulling columns leaves a row that half exists, and every
    later read has to decide what a row with no number but a ``created_at`` means; a whole-row
    delete needs no column-by-column audit to prove it was complete, has nothing to stamp, and
    leaves "erased" indistinguishable from "never onboarded" — which is exactly what PD-3
    wants an operator to see. This table is on NO clock (PD-2): the absence of the row IS the
    erasure record, and :mod:`hbd.db.models.user_profile`'s docstring carries the full
    argument, including the honesty test that keeps the absence from being a silent exemption.

    **SELECT then DELETE, rather than ``DELETE … RETURNING``.** ``RETURNING`` on a ``DELETE``
    needs SQLite 3.35+, and the unit suite has to run on whatever ``aiosqlite`` and whatever
    system SQLite the machine happens to have. Two statements inside one transaction are
    portable and atomic; a clever one is neither.

    **The object key comes back even when ``avatar_stored_at`` was NULL, and the caller
    deletes it unconditionally.** ``LocalFileStorage.delete`` treats a missing object as
    success (``storage.py:205-206``), so the cost of an unnecessary key is one no-op unlink,
    while the cost of a missing one is that bytes written by a :meth:`SqlUserProfiles.record_avatar`
    whose row update later failed outlive the erasure with nothing left pointing at them.
    ``repository._replace_assets`` makes the identical trade in the identical words
    (``repository.py:378-380``): "a key for bytes that were never written costs one no-op
    delete on the sweep; a missing key costs the bytes forever."

    **What this deliberately does NOT touch: the ``users`` row.** It survives, keeping
    ``users.ui_language``. It must survive, because ``credits.set_blocked`` UPSERTs that row so
    an operator can bar an account that never ordered — delete it here and ``/forget`` becomes
    a self-service unblock, repeatable, forever. The surviving ``ui_language`` is a preference
    and not a fact about a person, and it is invisible to onboarding, which reads the profile
    row, finds nothing, and asks both questions again on the next ``/start`` exactly as PD-3
    requires. Do not "fix" this by widening the delete.

    Session-first and never commits: the caller's transaction is what makes the read and the
    delete one act, and what lets the object deletion be sequenced strictly after the commit.
    """
    user_id = (
        await session.execute(
            sa.select(UserProfileRow.user_id).where(
                UserProfileRow.telegram_user_id == telegram_user_id
            )
        )
    ).scalar_one_or_none()
    if user_id is None:
        return ProfileErasure(profiles_deleted=0, storage_keys=())
    deleted = await session.execute(
        sa.delete(UserProfileRow).where(UserProfileRow.telegram_user_id == telegram_user_id)
    )
    return ProfileErasure(
        profiles_deleted=rowcount_of(deleted), storage_keys=(avatar_key(user_id),)
    )


class SqlUserProfiles:
    """:class:`hbd.user_profiles.UserProfileStore` over ``user_profiles`` and ``users``.

    Owns its transactions, owns its clock, owns the object store, and **never raises**: every
    public method is one :func:`hbd.db.guard.run_guarded` delegation, so a dropped connection
    reaches the handler as an ``Err`` rather than as an exception. That matters more here than
    anywhere else in the persistence layer, because onboarding runs inside aiogram's per-chat
    FSM isolation lock while a live customer waits: a leaked exception there is a handler that
    never replies, and a customer staring at a keyboard that does nothing.

    **Why the ``Storage`` handle is on THIS class and not on ``BotDeps`` (D13).** The avatar
    has two representations — bytes in the object store and three columns on the row — and the
    two must agree. Keeping the handle here puts "write the object, then the row" and "delete
    the row, then the object" in one layer, so the ordering is a property of this file rather
    than a convention two handlers have to remember. ``BotDeps`` gains one field instead of
    two, and no caller ever holds bytes it has nowhere to put. ``Storage`` is the protocol from
    :mod:`hbd.contracts`, never ``hbd.storage.LocalFileStorage``: the unit suite substitutes a
    fake, and ``tests/test_admin/test_asset_stream.py:712`` exists because the concrete class
    is exactly what layers above persistence must not learn to import.

    **Why this is not a method set on ``KitRepository`` (D12).** That protocol is held by the
    render worker and is about orders and kits. Widening it would hand the worker a write
    against a customer's phone number that it must never make, and hand ``BotDeps`` a
    ``create_order`` that the bot must never call. A separate seam keeps both halves of that
    sentence literally true instead of relying on nobody calling the wrong method.

    **There is deliberately no retention policy argument here (PD-2.)** No clock, no
    ``profile_expires_at``, no sweep, no ``RetentionPolicy`` field: the product owner chose
    "kept while the account exists", so ``/forget`` is the erasure route and there is nothing
    for a policy to parameterise. :mod:`hbd.db.models.user_profile`'s docstring carries the
    full argument and names the test that keeps the absence honest; read it there before
    adding a ``retention=`` here, because the sweep this class does not have is the first
    thing a reader assumes was forgotten.
    """

    __slots__ = ("_clock", "_sessions", "_storage")

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        storage: Storage,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._storage = storage
        self._clock = clock

    # -- UserProfileStore ---------------------------------------------------
    async def get(self, telegram_user_id: int) -> Result[UserProfile | None]:
        """The profile, or ``Ok(None)`` when this account has no row.

        ``Ok(None)`` is the NORMAL answer and never an error: there is no backfill (D11), so
        on the deploy after revision 0014 it is the answer for the entire installed base, and
        it is the answer for every account since its ``/forget``. Only an ``Err`` means the
        database could not be read, and only an ``Err`` may take a caller's fail-open path.
        """
        return await run_guarded(
            "profiles.get",
            lambda: self._get(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    async def record_language(
        self, telegram_user_id: int, *, ui_language: Language
    ) -> Result[UserProfile]:
        """Persist a deliberate language choice and answer with the stored profile."""
        return await run_guarded(
            "profiles.record_language",
            lambda: self._record_language(telegram_user_id, ui_language),
            telegram_user_id=telegram_user_id,
        )

    async def record_contact(
        self,
        telegram_user_id: int,
        *,
        phone_e164: str,
        telegram_username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> Result[UserProfile]:
        """Store the shared contact card and answer with the stored profile."""
        return await run_guarded(
            "profiles.record_contact",
            lambda: self._record_contact(
                telegram_user_id, phone_e164, telegram_username, first_name, last_name
            ),
            telegram_user_id=telegram_user_id,
        )

    async def record_avatar(
        self, telegram_user_id: int, *, image: bytes, mime: str, file_unique_id: str
    ) -> Result[None]:
        """Store the profile photo. Best effort — a refusal here never stops an onboarding."""
        return await run_guarded(
            "profiles.record_avatar",
            lambda: self._record_avatar(telegram_user_id, image, mime, file_unique_id),
            telegram_user_id=telegram_user_id,
        )

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """Honour ``/forget``: delete the row, then the avatar's bytes. PD-3."""
        return await run_guarded(
            "profiles.forget",
            lambda: self._forget(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    # -- implementations ----------------------------------------------------
    async def _get(self, telegram_user_id: int) -> UserProfile | None:
        async with self._sessions.begin() as session:
            return await load_profile(session, telegram_user_id)

    async def _record_language(self, telegram_user_id: int, ui_language: Language) -> UserProfile:
        """One transaction: the ``users`` row, the profile row, and the read-back.

        ``is_language_authoritative=True`` is the whole reason this write exists. A customer
        picking a language on the first screen or in Settings is the ONE authoritative event
        about which language they read in; ``repository._create_order`` passes ``False`` so a
        brief's output language can never stamp over it, and ``credits.touch`` writes whatever
        the draft happened to be rendering in. Without the flag this method and order creation
        would fight over one column and the customer would lose.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            user_id = await ensure_user(
                session,
                telegram_user_id=telegram_user_id,
                ui_language=ui_language,
                now=now,
                is_language_authoritative=True,
            )
            await upsert_language(
                session, user_id=user_id, telegram_user_id=telegram_user_id, now=now
            )
            return await self._read_back(session, telegram_user_id)

    async def _record_contact(
        self,
        telegram_user_id: int,
        phone_e164: str,
        telegram_username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> UserProfile:
        """One transaction, and ``ensure_user`` with NO opinion about the language.

        ``ui_language=None`` with ``is_language_authoritative=False`` is not defensive
        boilerplate: this call genuinely knows nothing about which language anybody reads in,
        and inventing one would be the clobber ``is_language_authoritative`` exists to prevent
        wearing a third hat. The ``ensure_user`` call is still made, because a customer whose
        FSM was parked at ``Onboarding.contact`` across a database reset reaches this method
        with no ``users`` row at all, and the profile row's primary key is a foreign key onto
        one.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            user_id = await ensure_user(
                session,
                telegram_user_id=telegram_user_id,
                ui_language=None,
                now=now,
                is_language_authoritative=False,
            )
            await upsert_contact(
                session,
                user_id=user_id,
                telegram_user_id=telegram_user_id,
                phone_e164=phone_e164,
                telegram_username=telegram_username,
                first_name=first_name,
                last_name=last_name,
                now=now,
            )
            return await self._read_back(session, telegram_user_id)

    async def _read_back(self, session: AsyncSession, telegram_user_id: int) -> UserProfile:
        """The row this transaction just wrote, or the module's standard not-found error.

        ``None`` is unreachable — the upsert two statements up guarantees the row, and
        :func:`load_profile`'s ``populate_existing`` guarantees we see it rather than a stale
        identity-map copy. It raises :func:`hbd.db.guard.not_found` anyway instead of casting,
        which is ``repository._load_order``'s own idiom: a ``cast`` would turn the impossible
        state into an ``AttributeError`` several frames away in a handler, while the raise
        becomes a named, terminal ``Err`` at this boundary with the account id attached.
        """
        profile = await load_profile(session, telegram_user_id)
        if profile is None:  # pragma: no cover - the upsert above guarantees the row exists
            raise not_found("user_profile", telegram_user_id=telegram_user_id)
        return profile

    async def _record_avatar(
        self, telegram_user_id: int, image: bytes, mime: str, file_unique_id: str
    ) -> None:
        """Object first, row second, and every refusal is a log line plus a shrug.

        **Three things answer "nothing happened", and none of them is an error.** No profile
        row means the customer has not answered the language question yet, so there is nothing
        to hang an avatar on and the fetcher simply ran early. An unrecognised MIME is
        discarded (D14) rather than stored: if Telegram ever serves WebP profile photos that
        surfaces as a logged refusal instead of a blob the admin panel serves under a content
        type it guessed — which is how a stored image becomes stored XSS. And a storage
        failure leaves the row untouched, because a row claiming an avatar whose bytes were
        never written is a lie the admin route acts on, 404ing at best and serving somebody
        else's stale object at worst. A caller that had to distinguish the three would grow a
        branch per case at the one step where the bot must simply move on, so each is recorded
        here and the flow above stays silent.

        **The ordering is deliberate: bytes, then row.** Bytes with no row are unreachable and
        are swept anyway by the unconditional key :func:`erase_profile` hands back; a row with
        no bytes is a broken image in the operator's list that nothing will ever repair. Two
        transactions rather than one because the ``put`` must not be attempted while holding a
        write transaction open across a network call to the object store.
        """
        async with self._sessions.begin() as session:
            user_id = await session.scalar(
                sa.select(UserProfileRow.user_id).where(
                    UserProfileRow.telegram_user_id == telegram_user_id
                )
            )
        if user_id is None:
            _log.debug(
                "avatar arrived before the profile row existed",
                extra={"telegram_user_id": telegram_user_id},
            )
            return
        if mime != AVATAR_MIME:
            _log.warning(
                "avatar discarded: unexpected content type",
                extra={
                    "telegram_user_id": telegram_user_id,
                    "mime": mime,
                    "expected_mime": AVATAR_MIME,
                },
            )
            return
        key = avatar_key(user_id)
        stored = await self._storage.put(key, image, content_type=mime)
        if is_err(stored):
            _log.warning(
                "avatar bytes were not stored; the row keeps saying there is no avatar",
                extra={"telegram_user_id": telegram_user_id, "key": key},
                exc_info=stored.error,
            )
            return
        now = self._clock()
        async with self._sessions.begin() as session:
            await session.execute(
                sa.update(UserProfileRow)
                .where(UserProfileRow.telegram_user_id == telegram_user_id)
                .values(
                    avatar_file_unique_id=file_unique_id,
                    avatar_mime=mime,
                    avatar_stored_at=now,
                    updated_at=now,
                )
            )

    async def _forget(self, telegram_user_id: int) -> None:
        """Delete the row, commit, and only THEN delete the bytes.

        The order is the whole safety argument. The object deletion runs outside the
        transaction because a rollback cannot un-delete a file: bytes removed inside a
        transaction that then fails would be gone while the row that describes them lived on,
        and the admin panel would serve a broken image for ever. This way the worst case is
        the reverse, an orphaned object at a key nothing references any more — stated here
        honestly rather than hidden, and removable by hand from the WARNING below, which
        carries the key.

        **A storage failure does not fail the request.** The row deletion has already
        committed, so the record IS gone; returning an ``Err`` would tell the customer nothing
        was erased when the sensitive half of the erasure is complete, and would invite a
        retry that can only repeat the same unlink. The INFO line is the audit answer, in the
        shape ``SqlCreditLedger._forget`` already uses (``credits.py:709-724``): when someone
        asks later whether their erasure ran, the answer has to be in the log of the process
        that ran it and not inferred from the absence of a row.
        """
        async with self._sessions.begin() as session:
            erased = await erase_profile(session, telegram_user_id=telegram_user_id)
        for key in erased.storage_keys:
            removed = await self._storage.delete(key)
            if is_err(removed):
                _log.warning(
                    "avatar object survived an erasure; delete it by hand",
                    extra={"telegram_user_id": telegram_user_id, "key": key},
                    exc_info=removed.error,
                )
        _log.info(
            "profile erased on request",
            extra={
                "telegram_user_id": telegram_user_id,
                "profiles_deleted": erased.profiles_deleted,
                "storage_keys": len(erased.storage_keys),
            },
        )
