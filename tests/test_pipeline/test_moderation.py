"""Moderation: fail-closed on a verdict, fail-open on an outage."""

from __future__ import annotations

from hbd.config import Settings
from hbd.contracts import Err
from hbd.errors import ErrorCode, ProviderUnavailableError
from hbd.pipeline.moderation import AllowAllModerator, LlmModerator, ModerationPayload
from tests.conftest import make_brief
from tests.test_pipeline.conftest import FakeLlmProvider, failure_of


async def test_allows_an_ordinary_birthday_note(settings: Settings) -> None:
    # Arrange
    moderator = LlmModerator(FakeLlmProvider(), settings)

    # Act
    result = await moderator.review(make_brief(note="Loves plov and long walks."))

    # Assert
    assert not isinstance(result, Err)


async def test_rejects_a_note_caught_by_the_local_denylist_without_calling_the_model(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()
    moderator = LlmModerator(llm, settings)

    # Act
    result = await moderator.review(make_brief(note="I will kill him on his birthday"))

    # Assert
    assert failure_of(result).error_code is ErrorCode.CONTENT_REJECTED
    assert llm.requests == []


async def test_rejects_a_note_the_model_refuses(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "ModerationPayload", ModerationPayload(is_allowed=False, reason="political content")
    )

    # Act
    result = await LlmModerator(llm, settings).review(make_brief(note="vote for us"))

    # Assert
    error = failure_of(result)
    assert error.error_code is ErrorCode.CONTENT_REJECTED
    assert error.context["reason"] == "political content"


async def test_allows_the_brief_when_the_moderation_call_itself_fails(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.fail_next("ModerationPayload", ProviderUnavailableError("down", provider="fake"))

    # Act
    result = await LlmModerator(llm, settings).review(make_brief(note="a kind note"))

    # Assert
    assert not isinstance(result, Err)


async def test_allow_all_moderator_never_refuses() -> None:
    # Arrange / Act
    result = await AllowAllModerator().review(make_brief(note="anything at all"))

    # Assert
    assert not isinstance(result, Err)
