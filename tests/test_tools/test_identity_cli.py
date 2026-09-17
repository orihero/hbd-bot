"""``python -m bayram.tools.identity`` — the profile writer, tested without a token.

Two properties matter about a command that edits what every customer sees before they
type anything, and neither is the argument parsing.

**It writes exactly the fields the operator named, in a fixed order.** Every assertion
below reads the aiogram METHOD CLASSES off a recording session, so a change that started
sending ``setMyName`` on a ``--description``-only run — or that reordered the four writes
and made the mid-way failure report wrong — fails here rather than on a live bot.

**A refusal happens before the first request.** ``plan`` is exercised with no bot at all,
because that is the guarantee: a mistyped flag costs an exit code, never a profile left
half-written with a 400 for an explanation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from aiogram import Bot
from aiogram.types import BotDescription, BotName, BotShortDescription, User

from bayram.tools.identity import (
    EXIT_REFUSED,
    Change,
    RefusedError,
    Show,
    apply,
    main,
    plan,
)
from tests.test_bot.conftest import BOT_TOKEN, RecordingSession

#: A JPEG's first three bytes are all this tool reads; the rest of a real photo would only
#: make the fixture large.
_JPEG: Final[bytes] = b"\xff\xd8\xff" + b"\x00" * 64


@pytest.fixture
def session() -> RecordingSession:
    recording = RecordingSession()
    recording.responses = {
        "GetMe": User(id=42, is_bot=True, first_name="BAYRAM BOT", username="bayram_uzbot"),
        "GetMyName": BotName(name="BAYRAM BOT"),
        "GetMyDescription": BotDescription(description="A song for a birthday."),
        "GetMyShortDescription": BotShortDescription(short_description="Songs, in a minute."),
        "SetMyName": True,
        "SetMyDescription": True,
        "SetMyShortDescription": True,
        "SetMyProfilePhoto": True,
    }
    return recording


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    return Bot(token=BOT_TOKEN, session=session)


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "avatar.jpg"
    path.write_bytes(_JPEG)
    return path


def test_plan_reads_the_default_locale_when_none_is_given() -> None:
    assert plan(["show"]) == Show(language_code="")


def test_plan_keeps_an_unnamed_field_none_so_it_is_never_written() -> None:
    change = plan(["set", "--description", "A song for a birthday."])
    assert change == Change(language_code="", description="A song for a birthday.")


def test_plan_accepts_an_empty_description_as_a_clear() -> None:
    """``""`` is a state BotFather can produce, so it cannot mean "unset"."""
    assert plan(["set", "--description", ""]) == Change(language_code="", description="")


def test_plan_refuses_a_set_that_would_change_nothing() -> None:
    with pytest.raises(RefusedError, match="nothing to set"):
        plan(["set"])


def test_plan_refuses_an_empty_name() -> None:
    with pytest.raises(RefusedError, match="--name"):
        plan(["set", "--name", "   "])


def test_plan_refuses_text_over_telegrams_cap_before_any_request() -> None:
    with pytest.raises(RefusedError, match="at most 120 characters, and this is 121"):
        plan(["set", "--short-description", "x" * 121])


def test_plan_refuses_a_malformed_locale() -> None:
    with pytest.raises(RefusedError, match="--language-code"):
        plan(["set", "--name", "Bayram", "--language-code", "russian!"])


def test_plan_refuses_a_photo_that_is_not_a_jpeg_and_says_how_to_convert(tmp_path: Path) -> None:
    png = tmp_path / "avatar.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(RefusedError, match="sips -s format jpeg"):
        plan(["set", "--photo", str(png)])


def test_plan_refuses_a_photo_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(RefusedError, match="no such file"):
        plan(["set", "--photo", str(tmp_path / "absent.jpg")])


def test_plan_refuses_a_localised_photo_because_a_bot_has_only_one(photo: Path) -> None:
    with pytest.raises(RefusedError, match="one picture for every"):
        plan(["set", "--photo", str(photo), "--language-code", "ru"])


async def test_show_reports_every_value_and_the_locale_it_read(bot: Bot) -> None:
    report = await apply(bot, Show(language_code="ru"))
    assert "@bayram_uzbot (42), locale: ru" in report
    assert "'A song for a birthday.'" in report
    assert "'Songs, in a minute.'" in report


async def test_show_names_the_default_locale_rather_than_printing_an_empty_one(bot: Bot) -> None:
    assert "locale: default" in await apply(bot, Show(language_code=""))


async def test_set_writes_only_the_named_fields(bot: Bot, session: RecordingSession) -> None:
    report = await apply(bot, Change(language_code="", description="A song for a birthday."))
    assert [type(call).__name__ for call in session.calls] == ["SetMyDescription"]
    assert report == "Set for the default locale: description."


async def test_set_writes_all_four_in_a_fixed_order(
    bot: Bot, session: RecordingSession, photo: Path
) -> None:
    await apply(
        bot,
        Change(
            language_code="",
            name="Bayram Studio",
            description="A song for a birthday.",
            short_description="Songs, in a minute.",
            photo=photo,
        ),
    )
    assert [type(call).__name__ for call in session.calls] == [
        "SetMyName",
        "SetMyDescription",
        "SetMyShortDescription",
        "SetMyProfilePhoto",
    ]


async def test_set_carries_the_locale_to_every_text_setter(
    bot: Bot, session: RecordingSession
) -> None:
    await apply(bot, Change(language_code="ru", name="Bayram", description="Песня"))
    assert [call.language_code for call in session.calls] == ["ru", "ru"]  # type: ignore[attr-defined]


async def test_a_failure_mid_way_reports_what_had_already_landed(
    bot: Bot, session: RecordingSession
) -> None:
    """Four setters are four requests: the report must name the half that applied."""
    session.failures = {"SetMyShortDescription": RuntimeError("Bad Request: too long")}
    with pytest.raises(RefusedError) as raised:
        await apply(
            bot,
            Change(
                language_code="",
                name="Bayram Studio",
                description="A song for a birthday.",
                short_description="x",
            ),
        )
    assert "Applied before it did: name, description." in str(raised.value)


def test_main_returns_a_refusal_code_without_touching_the_network() -> None:
    assert main(["set"]) == EXIT_REFUSED
