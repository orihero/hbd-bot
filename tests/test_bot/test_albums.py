"""One album, one count and one answer (IMAGE_VIDEO_SPEC §2.2, §2.3.2)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import Chat, Message, TelegramObject, User

from bayram.bot.albums import ALBUM_WINDOW, AlbumMemory
from bayram.bot.gate import InboundGateMiddleware
from bayram.ratelimit import InboundPolicy
from tests.test_bot.conftest import FIXED_MOMENT, USER_ID


def _item(message_id: int, group: str | None) -> Message:
    return Message(
        message_id=message_id,
        date=FIXED_MOMENT,
        chat=Chat(id=USER_ID, type="private"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        media_group_id=group,
        caption=None,
    )


def test_a_lone_message_is_always_first() -> None:
    memory = AlbumMemory()
    assert memory.first(USER_ID, None, purpose="reply", now=FIXED_MOMENT)
    assert memory.first(USER_ID, None, purpose="reply", now=FIXED_MOMENT)


def test_only_the_first_item_of_an_album_is_first_per_purpose() -> None:
    memory = AlbumMemory()
    assert memory.first(USER_ID, "g", purpose="reply", now=FIXED_MOMENT)
    assert not memory.first(USER_ID, "g", purpose="reply", now=FIXED_MOMENT)
    # Another purpose — the gate counting it — is its own question.
    assert memory.first(USER_ID, "g", purpose="gate", now=FIXED_MOMENT)
    # Another account's album with the same id is another album.
    assert memory.first(USER_ID + 1, "g", purpose="reply", now=FIXED_MOMENT)


def test_an_album_is_forgotten_after_the_window() -> None:
    memory = AlbumMemory()
    assert memory.first(USER_ID, "g", purpose="reply", now=FIXED_MOMENT)
    later = FIXED_MOMENT + ALBUM_WINDOW + timedelta(seconds=1)
    assert memory.first(USER_ID, "g", purpose="reply", now=later)


async def test_the_gate_counts_an_album_as_one_update(bot: Bot) -> None:
    """Two per minute, then a ten-photo album: all ten reach the handlers."""
    gate = InboundGateMiddleware(policy=InboundPolicy(max_updates=2), clock=lambda: FIXED_MOMENT)
    handled: list[int] = []

    async def handler(event: TelegramObject, data: dict[str, Any]) -> None:
        assert isinstance(event, Message)
        handled.append(event.message_id)

    await gate(handler, _item(1, None).as_(bot), {})
    for message_id in range(10, 20):
        await gate(handler, _item(message_id, "album").as_(bot), {})
    # The album was the second update; a third plain one is over the ceiling.
    await gate(handler, _item(99, None).as_(bot), {})

    assert handled == [1, *range(10, 20)]
