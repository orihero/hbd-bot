"""One user's live wizard session, read out of Redis by a process that holds no bot token.

**Why this is not ``RedisStorage``.** aiogram's storage is constructed by
``bayram.bot.app.build_storage`` and lives next to ``build_bot``, which takes
``settings.telegram_bot_token``. The admin process has no token by design (D10, enforced by
``app._refuse_vendor_credentials``) and ``AdminSettings`` has no field to hold one, so this
module imports from ``aiogram.fsm.storage.base`` only — the key builder and the key — and
issues the two ``GET``s itself. Nothing here can construct a ``Bot``.

**The key is derived, never formatted.** The bot calls ``RedisStorage.from_url`` without a
``key_builder``, so the storage builds its own ``DefaultKeyBuilder()`` with every default in
place; :data:`FSM_KEY_BUILDER` is the same object built the same way, and the key comes out
of ``build()`` rather than out of an f-string here. That distinction is the whole point of
this module: a hand-written ``f"fsm:{uid}:{uid}:data"`` keeps returning ``None`` forever on
the day aiogram changes its separator or its part order, and a ``None`` from the wrong key
is indistinguishable from "this person has no wizard session" — the one answer this screen
exists to give. Deriving it means such a change breaks the key builder's own tests upstream
and, here, moves both reads together.

``StorageKey`` wants a ``bot_id`` the default builder never reads (``with_bot_id`` is
false), so :func:`storage_key_for` passes a constant rather than inventing a plausible one.
For a private chat — the only kind the wizard runs in — ``chat_id == user_id``.

**The payload is untrusted.** It is JSON written by another process, under another build's
schema, and it may be an older shape or hand-edited. So it is parsed behind a boundary that
never raises: a malformed value is a WARNING naming the key and "no draft", because a 500 on
this screen would take out the one view an operator opens when a session is already stuck.
Redis *itself* being unreachable is a different fact and gets a different answer — a 503
naming the dependency, not an empty snapshot that reads as "no session".

aiogram stores the whole draft under the single FSM-data key ``draft``
(:data:`bayram.bot.draft.DRAFT_KEY`), so the value at the data key is ``{"draft": {...}}``.
That one level is unwrapped here; the inner dict goes to
:func:`~bayram.admin.schemas.users.to_wizard_state_view`, which reads it through an allowlist
and never returns a character of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from aiogram.fsm.storage.base import DefaultKeyBuilder, StorageKey
from redis.asyncio import Redis
from redis.exceptions import RedisError

from bayram.admin.errors import AdminErrorCode, ProblemError, problem
from bayram.bot.draft import DRAFT_KEY
from bayram.logging import get_logger

__all__ = [
    "FSM_KEY_BUILDER",
    "WizardSnapshot",
    "storage_key_for",
    "read_wizard_state",
]

_LOGGER: Final = get_logger(__name__)

#: Exactly what ``RedisStorage.__init__`` builds when it is handed no ``key_builder`` — and
#: ``bayram.bot.app.build_storage`` hands it none. Constructed with no arguments on purpose:
#: restating ``prefix="fsm", separator=":"`` here would pin today's defaults into the admin
#: process and go on agreeing with a bot whose storage had moved on.
FSM_KEY_BUILDER: Final[DefaultKeyBuilder] = DefaultKeyBuilder()

#: ``DefaultKeyBuilder`` is configured ``with_bot_id=False``, so this value is never read
#: and never reaches a key. It is zero rather than a token-derived id because deriving one
#: would need the token this process must not hold.
_UNUSED_BOT_ID: Final[int] = 0

#: The two record parts ``KeyBuilder.build`` accepts. Typed as the literals its signature
#: declares rather than as ``str``, so a typo here is a type error and not a key that reads
#: an address nothing ever writes.
_STATE_PART: Final[Literal["state"]] = "state"
_DATA_PART: Final[Literal["data"]] = "data"


@dataclass(frozen=True, slots=True)
class WizardSnapshot:
    """What Redis holds for one user right now. Both halves are independently absent.

    A ``state`` with no ``draft`` is a real and common shape — the first wizard screen, or a
    draft whose TTL expired a moment before the state's. It is not an error and it is not
    "no session".
    """

    state: str | None
    draft: dict[str, Any] | None


def storage_key_for(telegram_user_id: int) -> StorageKey:
    """The key aiogram would build for this person's private chat with the bot."""
    return StorageKey(bot_id=_UNUSED_BOT_ID, chat_id=telegram_user_id, user_id=telegram_user_id)


async def read_wizard_state(redis: Redis[str], *, telegram_user_id: int) -> WizardSnapshot:
    """Two reads, no writes, and no exception for anything the payload can be.

    The state and the data are separate keys with separate TTLs, so they are read
    separately and neither is inferred from the other.
    """
    key = storage_key_for(telegram_user_id)
    state_key = FSM_KEY_BUILDER.build(key, _STATE_PART)
    data_key = FSM_KEY_BUILDER.build(key, _DATA_PART)
    state = await _get(redis, state_key)
    data = await _get(redis, data_key)
    return WizardSnapshot(state=_text(state), draft=_draft(data, key=data_key))


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
async def _get(redis: Redis[str], key: str) -> object:
    """One ``GET``, with an unreachable store reported as a 503 rather than an empty answer.

    ``OSError`` is caught beside ``RedisError`` because a socket failure can reach a caller
    unwrapped, and because the two mean the same thing to an operator: the wizard store is
    not answering, come back. Answering ``None`` instead would render as "no wizard session"
    for every user in the panel for as long as Redis is down.
    """
    try:
        return await redis.get(key)
    except (RedisError, OSError) as exc:
        _LOGGER.warning(
            "the wizard store did not answer",
            extra={"event": "admin.wizard_state.unavailable", "key": key},
            exc_info=exc,
        )
        raise _unavailable() from exc


def _unavailable() -> ProblemError:
    return problem(
        AdminErrorCode.SERVICE_UNAVAILABLE,
        "the wizard store is not answering; the live session cannot be read right now",
    )


def _text(value: object) -> str | None:
    """A stored string, whatever the client's ``decode_responses`` setting is.

    The container builds its client with ``decode_responses=True`` and this returns ``str``
    already; the ``bytes`` branch is what aiogram's own ``get_state`` does, and it costs
    three lines to not depend on a constructor argument two modules away.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None


def _draft(value: object, *, key: str) -> dict[str, Any] | None:
    """The inner draft dict, or ``None`` for anything this build cannot read.

    Three failures collapse into that one answer — unparseable JSON, a top-level value that
    is not an object, and a ``draft`` entry that is not one either — because they mean the
    same thing to the panel and none of them is worth a distinct screen. Each is logged with
    the key and **never with the payload**: the payload is the recipient's name, the note
    and the whole lyric, and a log line is not a reveal surface.
    """
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        # ValueError covers json.JSONDecodeError; a truncated write is the shape that gets
        # here, and it must not become a 500 on the screen that explains a stuck session.
        _LOGGER.warning(
            "wizard FSM data is not parseable JSON; reporting no draft",
            extra={"event": "admin.wizard_state.unparseable", "key": key, "detail": str(exc)},
        )
        return None
    if not isinstance(parsed, dict):
        _LOGGER.warning(
            "wizard FSM data is not an object; reporting no draft",
            extra={
                "event": "admin.wizard_state.not_an_object",
                "key": key,
                "actual_type": type(parsed).__name__,
            },
        )
        return None
    draft: object = parsed.get(DRAFT_KEY)
    if draft is None:
        # Not a warning: FSM data with no draft key is what every handler that stashes
        # something else beside the draft would leave behind, and an empty wizard leaves it.
        return None
    if not isinstance(draft, dict):
        _LOGGER.warning(
            "wizard draft is not an object; reporting no draft",
            extra={
                "event": "admin.wizard_state.draft_not_an_object",
                "key": key,
                "actual_type": type(draft).__name__,
            },
        )
        return None
    return draft
