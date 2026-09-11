"""The FSM reader, tested against aiogram's own writer rather than against a string.

The bug this module exists to prevent is silent and permanent: a key that does not match
the one the bot writes returns ``None`` forever, and ``None`` is also the honest answer for
"this person has no wizard session". No exception, no log, no alert — the panel simply says
nobody is ever mid-flow. So the load-bearing test here does not assert on ``fsm:42:42:data``
at all. It hands a real :class:`~aiogram.fsm.storage.redis.RedisStorage` the same fake Redis
and asks it to write, then reads it back through :func:`read_wizard_state`: the two agree
because they derive the key from the same builder, and they will still agree the day aiogram
changes its separator.

The writer is deliberately given a ``bot_id`` the reader does not have. ``DefaultKeyBuilder``
is configured ``with_bot_id=False``, and if that ever stops being true this test fails
loudly instead of the panel going quiet.

Everything else here is the untrusted-payload boundary: JSON from another process, under
another build's schema. Each malformed shape must be "no draft" plus a WARNING naming the
key — never an exception, because the screen that would 500 is the one an operator opens
when a session is *already* stuck.
"""

from __future__ import annotations

import json
from typing import Any, Final, cast

import pytest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError
from bayram.admin.wizard_state import FSM_KEY_BUILDER, read_wizard_state, storage_key_for
from bayram.bot.draft import DRAFT_KEY, WizardDraft
from bayram.contracts import Language, NameCandidate, NameStrategy, Occasion, RecipientName, Script
from tests.test_admin.conftest import FakeRedis

TELEGRAM_USER_ID: Final[int] = 987_654_321
#: The writer's bot id. Different from the reader's constant on purpose — see the module doc.
WRITER_BOT_ID: Final[int] = 555_000_111
STATE: Final[str] = "Wizard:note"

#: Distinctive enough that a substring assertion cannot pass by accident.
NOTE: Final[str] = "Zumrad opa jiyanlariga atab aytadi"
RECIPIENT_DISPLAY: Final[str] = "Gʻulomjon"


def make_draft(**overrides: Any) -> WizardDraft:
    """A draft carrying real plaintext, built through the model the bot writes."""
    values: dict[str, Any] = {
        "session_id": "sess-1234",
        "ui_language": Language.UZ_LATN,
        "occasion": Occasion.BIRTHDAY,
        "note": NOTE,
        "recipient": RecipientName(
            raw=RECIPIENT_DISPLAY,
            display=RECIPIENT_DISPLAY,
            lookup_key="gulomjon",
            script=Script.LATIN,
            language=Language.UZ_LATN,
            candidates=(
                NameCandidate(text=RECIPIENT_DISPLAY, strategy=NameStrategy.CANONICAL, rank=0),
            ),
        ),
        "lyric_writes": 2,
    }
    values.update(overrides)
    return WizardDraft(**values)


def writer(fake_redis: FakeRedis) -> RedisStorage:
    """aiogram's own storage, over the fake. The reader never sees this object."""
    return RedisStorage(redis=cast("Redis[str]", fake_redis))


def writer_key() -> StorageKey:
    return StorageKey(bot_id=WRITER_BOT_ID, chat_id=TELEGRAM_USER_ID, user_id=TELEGRAM_USER_ID)


def seed_raw(fake_redis: FakeRedis, *, data: str) -> str:
    """Put a raw string at the data key aiogram would use, and return that key."""
    key = FSM_KEY_BUILDER.build(storage_key_for(TELEGRAM_USER_ID), "data")
    fake_redis.values[key] = data
    return key


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------
async def test_the_reader_finds_exactly_what_aiograms_own_storage_wrote(
    fake_redis: FakeRedis,
) -> None:
    # Arrange — the real writer, with a bot id the reader does not have.
    storage = writer(fake_redis)
    await storage.set_state(writer_key(), STATE)
    await storage.set_data(writer_key(), make_draft().to_state_data())

    # Act
    snapshot = await read_wizard_state(
        cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
    )

    # Assert — the draft came back unwrapped one level, as the projection expects.
    assert snapshot.state == STATE
    assert snapshot.draft is not None
    assert snapshot.draft["note"] == NOTE
    assert snapshot.draft["session_id"] == "sess-1234"


async def test_a_private_chat_keys_on_the_telegram_id_for_both_chat_and_user(
    fake_redis: FakeRedis,
) -> None:
    # Arrange / Act — the wizard runs only in a private chat, where the two are the same.
    key = storage_key_for(TELEGRAM_USER_ID)

    # Assert
    assert key.chat_id == TELEGRAM_USER_ID
    assert key.user_id == TELEGRAM_USER_ID


async def test_the_state_and_the_data_are_read_as_two_independent_keys(
    fake_redis: FakeRedis,
) -> None:
    # Arrange — the shape of the very first wizard screen, and of a draft whose TTL went
    # a moment before the state's. Neither is an error and neither implies the other.
    storage = writer(fake_redis)
    await storage.set_state(writer_key(), STATE)

    # Act
    snapshot = await read_wizard_state(
        cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
    )

    # Assert
    assert snapshot.state == STATE
    assert snapshot.draft is None


async def test_nobody_mid_flow_is_two_nones_rather_than_a_failure(
    fake_redis: FakeRedis,
) -> None:
    # Arrange — the normal state of everyone who is not in the wizard right now.

    # Act
    snapshot = await read_wizard_state(
        cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
    )

    # Assert
    assert snapshot.state is None
    assert snapshot.draft is None


async def test_a_client_without_decode_responses_still_reads(fake_redis: FakeRedis) -> None:
    # Arrange — bytes are what a client built without ``decode_responses`` hands back, and
    # aiogram's own ``get_state`` decodes them for the same reason.
    state_key = FSM_KEY_BUILDER.build(storage_key_for(TELEGRAM_USER_ID), "state")
    fake_redis.values[state_key] = cast("str", STATE.encode("utf-8"))
    seed_raw(fake_redis, data=cast("str", json.dumps(make_draft().to_state_data()).encode()))

    # Act
    snapshot = await read_wizard_state(
        cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
    )

    # Assert
    assert snapshot.state == STATE
    assert snapshot.draft is not None


# ---------------------------------------------------------------------------
# The untrusted payload
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("payload", "event"),
    [
        ('{"draft": {"note": "x"', "admin.wizard_state.unparseable"),
        ("[1, 2, 3]", "admin.wizard_state.not_an_object"),
        ('{"draft": "a string"}', "admin.wizard_state.draft_not_an_object"),
    ],
    ids=["truncated-json", "not-an-object", "draft-not-an-object"],
)
async def test_a_payload_this_build_cannot_read_is_no_draft_and_a_warning(
    fake_redis: FakeRedis,
    caplog: pytest.LogCaptureFixture,
    payload: str,
    event: str,
) -> None:
    # Arrange — an older build's shape, a hand edit, or a truncated write.
    key = seed_raw(fake_redis, data=payload)

    # Act
    with caplog.at_level("WARNING"):
        snapshot = await read_wizard_state(
            cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
        )

    # Assert — never an exception, and the log names the key so it can be inspected.
    assert snapshot.draft is None
    warnings = [record for record in caplog.records if getattr(record, "event", None) == event]
    assert len(warnings) == 1
    assert getattr(warnings[0], "key", None) == key


async def test_a_malformed_payload_is_never_echoed_into_the_log(
    fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — the payload IS the note and the name. A log line is not a reveal surface.
    seed_raw(fake_redis, data=f'{{"draft": {{"note": "{NOTE}"')

    # Act
    with caplog.at_level("WARNING"):
        await read_wizard_state(cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID)

    # Assert
    assert NOTE not in caplog.text


async def test_fsm_data_holding_something_other_than_a_draft_is_quietly_no_draft(
    fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — well-formed FSM data that simply has no ``draft`` key. Not a defect: any
    # handler stashing its own value beside the draft leaves exactly this.
    seed_raw(fake_redis, data=json.dumps({"something_else": 1}))

    # Act
    with caplog.at_level("WARNING"):
        snapshot = await read_wizard_state(
            cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID
        )

    # Assert
    assert snapshot.draft is None
    assert caplog.records == []


def test_the_draft_key_this_module_unwraps_is_the_one_the_bot_writes() -> None:
    # Arrange / Act — the drift guard. Renaming ``DRAFT_KEY`` in the bot without this
    # reader following would make every live session read as empty.

    # Assert
    assert DRAFT_KEY in make_draft().to_state_data()


# ---------------------------------------------------------------------------
# The store itself being gone
# ---------------------------------------------------------------------------
async def test_an_unreachable_store_is_a_503_and_not_an_empty_session(
    fake_redis: FakeRedis,
) -> None:
    # Arrange — answering "no session" here would say the same thing about every user in
    # the panel for as long as Redis is down.
    fake_redis.is_down = True

    # Act
    with pytest.raises(ProblemError) as raised:
        await read_wizard_state(cast("Redis[str]", fake_redis), telegram_user_id=TELEGRAM_USER_ID)

    # Assert
    failure = raised.value.failure
    assert isinstance(failure, AdminProblem)
    assert failure.code is AdminErrorCode.SERVICE_UNAVAILABLE
