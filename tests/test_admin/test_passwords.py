"""What the login route depends on argon2 for, asserted without a login route.

Three properties carry the weight, and none of them is "argon2 works":

* an unknown username and a wrong password produce the **same** answer and the **same**
  work, so the response is not an account-enumeration oracle;
* the hash runs in a worker thread, so 64 MiB of memory-hard work never stalls the event
  loop every other operator's request is waiting on;
* a parameter bump is reported to the caller while the plaintext is still in hand, because
  that is the only moment it can be acted on.

Every hasher here is built at one-round, 8 KiB cost. The parameters are arguments precisely
so the suite does not spend 50 ms per assertion proving a constant.
"""

from __future__ import annotations

import logging
import threading
from typing import Final

import pytest
from argon2 import PasswordHasher

from hbd.admin.security import passwords
from hbd.admin.security.passwords import (
    MAX_PASSWORD_BYTES,
    PasswordVerification,
    build_hasher,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)

_PASSWORD: Final[str] = "correct horse battery staple ʻ"
_WRONG: Final[str] = "correct horse battery stapl"
_PLACEHOLDER: Final[str] = "hbd-admin-nonexistent-account-placeholder"


@pytest.fixture
def hasher() -> PasswordHasher:
    """One-round, 8 KiB: the cheapest parameters argon2 accepts."""
    return build_hasher(time_cost=1, memory_kib=8, parallelism=1)


def test_a_hashed_password_verifies_and_needs_no_rehash(hasher: PasswordHasher) -> None:
    # Arrange
    stored = hash_password(_PASSWORD, hasher=hasher)

    # Act
    outcome = verify_password(_PASSWORD, stored, hasher=hasher)

    # Assert
    assert outcome == PasswordVerification(is_valid=True, needs_rehash=False)
    assert _PASSWORD not in stored


def test_the_stored_hash_fits_the_password_hash_column() -> None:
    """``admin_users.password_hash`` is ``String(255)``, at the production parameters."""
    production = build_hasher()

    assert len(hash_password("x", hasher=production)) <= 255


def test_a_wrong_password_is_rejected(hasher: PasswordHasher) -> None:
    stored = hash_password(_PASSWORD, hasher=hasher)

    assert verify_password(_WRONG, stored, hasher=hasher).is_valid is False


def test_an_unknown_username_answers_exactly_as_a_wrong_password_does(
    hasher: PasswordHasher,
) -> None:
    """The enumeration oracle: ``None`` must not be a cheaper or a different failure."""
    stored = hash_password(_PASSWORD, hasher=hasher)

    unknown = verify_password(_PASSWORD, None, hasher=hasher)
    wrong = verify_password(_WRONG, stored, hasher=hasher)

    assert unknown == wrong == PasswordVerification(is_valid=False, needs_rehash=False)


def test_the_dummy_hash_is_never_itself_a_credential(hasher: PasswordHasher) -> None:
    """Handing the placeholder to the no-account path must still not authenticate."""
    assert verify_password(_PLACEHOLDER, None, hasher=hasher).is_valid is False


def test_an_empty_stored_hash_is_a_broken_row_not_a_credential(hasher: PasswordHasher) -> None:
    assert verify_password(_PLACEHOLDER, "", hasher=hasher).is_valid is False
    assert verify_password(_PASSWORD, "", hasher=hasher).is_valid is False


def test_a_weaker_stored_hash_reports_needs_rehash() -> None:
    weak = build_hasher(time_cost=1, memory_kib=8, parallelism=1)
    strong = build_hasher(time_cost=2, memory_kib=16, parallelism=1)
    stored = hash_password(_PASSWORD, hasher=weak)

    outcome = verify_password(_PASSWORD, stored, hasher=strong)

    assert outcome.is_valid is True
    assert outcome.needs_rehash is True


def test_a_corrupt_stored_hash_fails_the_login_and_is_logged(
    hasher: PasswordHasher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 500 here would tell an attacker which row is broken; a WARNING tells us instead."""
    with caplog.at_level(logging.WARNING, logger="hbd.admin.security.passwords"):
        outcome = verify_password(_PASSWORD, "not-an-argon2-hash", hasher=hasher)

    assert outcome.is_valid is False
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert _PASSWORD not in caplog.text


def test_an_oversized_password_is_never_hashed(hasher: PasswordHasher) -> None:
    oversized = "a" * (MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValueError, match="exceeds"):
        hash_password(oversized, hasher=hasher)
    assert verify_password(oversized, None, hasher=hasher).is_valid is False


def test_multibyte_length_is_measured_in_bytes_not_characters(hasher: PasswordHasher) -> None:
    # U+02BB is two bytes in UTF-8, so this is under the character cap and over the byte one.
    oversized = "ʻ" * MAX_PASSWORD_BYTES

    with pytest.raises(ValueError, match="exceeds"):
        hash_password(oversized, hasher=hasher)


async def test_hashing_and_verifying_run_off_the_event_loop(
    hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``asyncio.to_thread``, asserted by thread identity rather than by reading the source.

    The synchronous functions are replaced with recorders: what is under test is that the
    async wrappers hand the CPU-bound call to another thread, not that argon2 hashes.
    """
    caller_thread = threading.get_ident()
    seen: list[int] = []

    def _recording_hash(password: str, *, hasher: PasswordHasher) -> str:
        seen.append(threading.get_ident())
        return "hashed"

    def _recording_verify(
        password: str, password_hash: str | None, *, hasher: PasswordHasher
    ) -> PasswordVerification:
        seen.append(threading.get_ident())
        return PasswordVerification(is_valid=True, needs_rehash=False)

    monkeypatch.setattr(passwords, "hash_password", _recording_hash)
    monkeypatch.setattr(passwords, "verify_password", _recording_verify)

    assert await hash_password_async(_PASSWORD, hasher=hasher) == "hashed"
    assert (await verify_password_async(_PASSWORD, "hashed", hasher=hasher)).is_valid is True

    assert len(seen) == 2
    assert all(thread_id != caller_thread for thread_id in seen)
