"""argon2id hashing, with the two properties a login route cannot supply for itself.

**It never runs on the event loop.** A 64 MiB, ~50 ms hash executed inline stalls every
other request in the process, which is both a latency bug and a denial-of-service lever on
the one unauthenticated route. So the async wrappers here are the public API and they run
the CPU-bound call in ``asyncio.to_thread``; the synchronous functions exist for the
bootstrap CLI, which has no event loop. A caller cannot forget, because forgetting means
calling something that is not ``await``-able and mypy says so (ADMIN_PANEL_PLAN §12.1 T1).

**An unknown username costs the same as a wrong password.** :func:`verify_password`
accepts ``password_hash=None`` and verifies against a dummy hash built with the *caller's*
parameters, so response time carries no signal about whether the account exists. Skipping
the work for an unknown user is the classic enumeration oracle, and it is measurable over
a handful of requests.

Parameters are arguments, never imported settings: this module stays pure so a test can
run it at one-round cost while production runs the ``HBD_ADMIN_ARGON2_*`` values. The
caller builds one :class:`~argon2.PasswordHasher` at startup with :func:`build_hasher` and
passes it in — constructing one per request is wasted work, not extra safety.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from hbd.logging import get_logger

__all__ = [
    "DEFAULT_TIME_COST",
    "DEFAULT_MEMORY_KIB",
    "DEFAULT_PARALLELISM",
    "MAX_PASSWORD_BYTES",
    "PasswordVerification",
    "build_hasher",
    "hash_password",
    "verify_password",
    "hash_password_async",
    "verify_password_async",
]

_LOGGER: Final = get_logger(__name__)

#: OWASP's argon2id baseline, and the defaults of the ``HBD_ADMIN_ARGON2_*`` settings.
DEFAULT_TIME_COST: Final[int] = 3
DEFAULT_MEMORY_KIB: Final[int] = 65_536
DEFAULT_PARALLELISM: Final[int] = 4

#: A hard cap on what we are willing to spend argon2 on. argon2id's cost is dominated by
#: its memory parameter, but the pre-hash of a multi-megabyte password is still work done
#: on behalf of an unauthenticated caller, and no operator password is this long.
MAX_PASSWORD_BYTES: Final[int] = 1_024

#: Verified against when the username does not exist. Never a valid credential: the
#: password below is a constant, so a login can only match it if someone deliberately
#: stores a hash of it, and no code path here does.
_DUMMY_PASSWORD: Final[str] = "hbd-admin-nonexistent-account-placeholder"


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    """Outcome of one verification.

    ``needs_rehash`` is reported alongside validity rather than left to the caller to ask
    for, because the only moment the plaintext is in memory is the moment it can be
    re-hashed at the new cost — a parameter bump that is never acted on is a parameter
    bump that never happened.
    """

    is_valid: bool
    needs_rehash: bool


_INVALID: Final[PasswordVerification] = PasswordVerification(is_valid=False, needs_rehash=False)


def build_hasher(
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_kib: int = DEFAULT_MEMORY_KIB,
    parallelism: int = DEFAULT_PARALLELISM,
) -> PasswordHasher:
    """Build the process-wide hasher. ``memory_kib`` is argon2's ``memory_cost``, in KiB."""
    return PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_kib,
        parallelism=parallelism,
    )


@lru_cache(maxsize=8)
def _dummy_hash(time_cost: int, memory_cost: int, parallelism: int) -> str:
    """A hash of a constant, at the given cost, computed once per parameter set.

    Cached rather than module-level because the parameters are configuration: a dummy
    built at import with the defaults would take a different amount of time than a real
    verify under an operator's tuned settings, which is the oracle this exists to close.
    """
    return build_hasher(time_cost=time_cost, memory_kib=memory_cost, parallelism=parallelism).hash(
        _DUMMY_PASSWORD
    )


def _is_oversized(password: str) -> bool:
    return len(password.encode("utf-8")) > MAX_PASSWORD_BYTES


def hash_password(password: str, *, hasher: PasswordHasher) -> str:
    """Hash a new password. Blocking — prefer :func:`hash_password_async` in a server.

    Raises ``ValueError`` for a password past :data:`MAX_PASSWORD_BYTES`. That is a caller
    bug (the request schema bounds the field first), not a runtime condition, so it is not
    a ``Result``.
    """
    if _is_oversized(password):
        raise ValueError(f"password exceeds {MAX_PASSWORD_BYTES} bytes and will not be hashed")
    return hasher.hash(password)


def verify_password(
    password: str,
    password_hash: str | None,
    *,
    hasher: PasswordHasher,
) -> PasswordVerification:
    """Check ``password`` against ``password_hash``. Blocking — see the async wrapper.

    ``password_hash=None`` means "no such account". It is verified against the dummy hash
    anyway, so an unknown username and a wrong password cost the same and answer the same.
    Never raises: a corrupt stored hash is a failed verification plus a WARNING, because a
    500 here would tell an attacker which row is broken.
    """
    if _is_oversized(password):
        return _INVALID
    is_dummy = not password_hash
    stored = (
        _dummy_hash(hasher.time_cost, hasher.memory_cost, hasher.parallelism)
        if is_dummy or password_hash is None
        else password_hash
    )
    try:
        hasher.verify(stored, password)
    except VerifyMismatchError:
        return _INVALID
    except (InvalidHashError, VerificationError):
        # Reached when the stored value is not a parsable argon2 hash. Logged without the
        # hash, the password or any prefix of either (§12.4, "never logged").
        _LOGGER.warning(
            "stored admin password hash could not be parsed; treating login as failed",
            extra={"event": "admin.password.hash_unusable"},
        )
        return _INVALID
    if is_dummy or password_hash is None:
        # The dummy matched, which can only happen if someone passes the placeholder
        # itself. There is no account, so there is no login — and an empty stored hash is
        # a broken row, not a credential.
        return _INVALID
    return PasswordVerification(
        is_valid=True,
        needs_rehash=hasher.check_needs_rehash(password_hash),
    )


async def hash_password_async(password: str, *, hasher: PasswordHasher) -> str:
    """:func:`hash_password`, off the event loop. This is the API a request handler uses."""
    return await asyncio.to_thread(hash_password, password, hasher=hasher)


async def verify_password_async(
    password: str,
    password_hash: str | None,
    *,
    hasher: PasswordHasher,
) -> PasswordVerification:
    """:func:`verify_password`, off the event loop. This is the API a login route uses."""
    return await asyncio.to_thread(verify_password, password, password_hash, hasher=hasher)
