"""``admin_users`` persistence — the account half of admin authentication.

Every assertion here protects a control that authentication rests on rather than a CRUD
convenience: that two casings of one login cannot become two accounts, that changing a
password moves the instant every session is checked against, and that the OWNER count the
bootstrap CLI guards on does not include operators who can no longer sign in.

Time is injected everywhere. A test that called the system clock could not assert that
``password_changed_at`` moved, only that it exists.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin import accounts
from hbd.db.enums import AdminRole
from hbd.db.models import AdminUserRow
from tests.test_db.conftest import MovableClock

_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$fake-digest-for-tests"
_OTHER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$b3RoZXJzYWx0$other-digest"


async def _create(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    username: str,
    role: AdminRole = AdminRole.OWNER,
    is_active: bool = True,
    must_change_password: bool = True,
) -> AdminUserRow:
    """Insert one operator. ``is_active`` is applied as an update, never by mutating the row."""
    async with sessions.begin() as session:
        row = await accounts.create(
            session,
            username=username,
            password_hash=_HASH,
            role=role,
            must_change_password=must_change_password,
            now=clock.now,
        )
        if not is_active:
            await session.execute(
                sa.update(AdminUserRow).where(AdminUserRow.id == row.id).values(is_active=False)
            )
        return row


# ---------------------------------------------------------------------------
# Create and fetch
# ---------------------------------------------------------------------------
async def test_a_created_account_is_found_by_its_username(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    created = await _create(sessions, clock, username="owner", role=AdminRole.OWNER)

    # Act
    async with sessions() as session:
        found = await accounts.get_by_username(session, "owner")

    # Assert
    assert found is not None
    assert found.id == created.id
    assert found.role is AdminRole.OWNER
    assert found.password_hash == _HASH
    assert found.is_active is True
    assert found.must_change_password is True
    assert found.password_changed_at == clock.now
    assert found.last_login_at is None


async def test_a_username_is_stored_and_looked_up_casefolded(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an operator typing their own name with a capital must reach their account.
    await _create(sessions, clock, username="  Ops.Lead  ")

    # Act
    async with sessions() as session:
        found = await accounts.get_by_username(session, "OPS.LEAD")

    # Assert
    assert found is not None
    assert found.username == "ops.lead"


async def test_an_unknown_username_is_none_rather_than_an_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    async with sessions() as session:
        found = await accounts.get_by_username(session, "nobody")

    # Assert — the login path needs a value it can spend the same time on as a real hit.
    assert found is None


async def test_an_account_is_found_by_id(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    created = await _create(sessions, clock, username="support", role=AdminRole.SUPPORT)

    # Act
    async with sessions() as session:
        found = await accounts.get_by_id(session, created.id)

    # Assert
    assert found is not None
    assert found.username == "support"


async def test_an_unknown_id_is_none(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    created = await _create(sessions, clock, username="viewer", role=AdminRole.VIEWER)
    async with sessions.begin() as session:
        await session.execute(sa.delete(AdminUserRow).where(AdminUserRow.id == created.id))

    # Act
    async with sessions() as session:
        found = await accounts.get_by_id(session, created.id)

    # Assert
    assert found is None


async def test_two_accounts_cannot_share_a_username(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the casing differs, which is exactly the collision the index must catch.
    await _create(sessions, clock, username="owner")

    # Act / Assert — the constraint is the guarantee; a pre-flight SELECT would be a race.
    with pytest.raises(IntegrityError):
        await _create(sessions, clock, username="Owner", role=AdminRole.ADMIN)


# ---------------------------------------------------------------------------
# Password and login bookkeeping
# ---------------------------------------------------------------------------
async def test_setting_a_password_moves_the_clock_sessions_are_checked_against(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    created = await _create(sessions, clock, username="owner", must_change_password=True)
    later = clock.advance(seconds=90)

    # Act
    async with sessions.begin() as session:
        await accounts.set_password(
            session, admin_user_id=created.id, password_hash=_OTHER_HASH, now=later
        )

    # Assert — the new hash, the new instant and the cleared flag land together, so no
    # window exists in which the old password's sessions outlive the old password.
    async with sessions() as session:
        found = await accounts.get_by_id(session, created.id)
    assert found is not None
    assert found.password_hash == _OTHER_HASH
    assert found.password_changed_at == later
    assert found.must_change_password is False
    assert found.updated_at == later


async def test_touching_a_login_records_the_instant_and_nothing_else(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    created_at = clock.now
    created = await _create(sessions, clock, username="owner")
    later = clock.advance(seconds=5)

    # Act
    async with sessions.begin() as session:
        await accounts.touch_login(session, admin_user_id=created.id, now=later)

    # Assert — a sign-in is advisory bookkeeping: it must not touch the credential or the
    # instant that decides which sessions are still valid.
    async with sessions() as session:
        found = await accounts.get_by_id(session, created.id)
    assert found is not None
    assert found.last_login_at == later
    assert found.password_changed_at == created_at
    assert found.password_hash == _HASH


# ---------------------------------------------------------------------------
# Counting — the bootstrap and last-owner guards read these
# ---------------------------------------------------------------------------
async def test_counting_active_owners_ignores_deactivated_and_other_roles(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one active OWNER is the most the database permits
    # (``ix_admin_users_active_owner``), so the other three rows are exactly the ones the
    # count has to skip: a deactivated ex-owner and two other roles.
    #
    # The ex-owner is created **first**, and that order is load-bearing rather than
    # stylistic: ``_create`` inserts an active row and demotes it with a second statement,
    # which is how an owner is really deactivated, so building it while ``owner-one`` was
    # already active would make the *insert* the second active OWNER and the partial unique
    # index would refuse it. That refusal is the constraint working, not a test artefact.
    await _create(sessions, clock, username="owner-gone", role=AdminRole.OWNER, is_active=False)
    await _create(sessions, clock, username="owner-one", role=AdminRole.OWNER)
    await _create(sessions, clock, username="admin", role=AdminRole.ADMIN)
    await _create(sessions, clock, username="viewer", role=AdminRole.VIEWER)

    # Act
    async with sessions() as session:
        owners = await accounts.count_active_owners(session)
        everyone = await accounts.count_all(session)

    # Assert — a deactivated OWNER cannot sign in, so counting them would let the last
    # usable owner be demoted.
    assert owners == 1
    assert everyone == 4


async def test_counting_an_empty_table_is_zero_not_none(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — zero is how bootstrap recognises a database nobody has set up yet.
    async with sessions() as session:
        owners = await accounts.count_active_owners(session)
        everyone = await accounts.count_all(session)

    # Assert
    assert owners == 0
    assert everyone == 0
