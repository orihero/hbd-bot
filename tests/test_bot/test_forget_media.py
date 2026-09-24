"""``/forget`` reaches the media arm (IMAGE_VIDEO_SPEC §9.3).

The data half is pinned in ``tests/test_db/test_media_tables.py``; this is the wiring: the
handler calls :class:`bayram.bot.ports.MediaEraser` for the sender, and a failure there is
reported rather than covered by ``privacy.forgotten``.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.i18n import translate
from bayram.bot.ports import MediaEraser
from bayram.config import Settings
from bayram.contracts import Language, Result, err, ok
from bayram.db.media_erasure import SqlMediaEraser
from bayram.errors import StorageError
from tests.test_bot.conftest import (
    USER_ID,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_wizard_flow import send


class FakeMediaEraser:
    """Records who was forgotten; can be told to fail."""

    def __init__(self, *, failure: StorageError | None = None) -> None:
        self.forgotten: list[int] = []
        self._failure = failure

    async def forget_media(self, telegram_user_id: int) -> Result[int]:
        self.forgotten.append(telegram_user_id)
        if self._failure is not None:
            return err(self._failure)
        return ok(3)


def _deps(settings: Settings, eraser: FakeMediaEraser) -> BotDeps:
    return BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        media_erasure=eraser,
    )


def test_the_sql_eraser_satisfies_the_port() -> None:
    assert isinstance(FakeMediaEraser(), MediaEraser)
    assert hasattr(SqlMediaEraser, "forget_media")


async def test_forget_erases_the_senders_media(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    eraser = FakeMediaEraser()
    dispatcher = build_dispatcher(_deps(settings, eraser), storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    assert eraser.forgotten == [USER_ID]
    assert session.last_screen.text == translate("privacy.forgotten", Language.UZ_LATN)


async def test_a_media_erasure_that_fails_says_so(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    eraser = FakeMediaEraser(failure=StorageError("the database is down"))
    dispatcher = build_dispatcher(_deps(settings, eraser), storage=MemoryStorage())

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert — the confirmation would claim an erasure that did not happen.
    assert eraser.forgotten == [USER_ID]
    assert session.last_screen.text != translate("privacy.forgotten", Language.UZ_LATN)
