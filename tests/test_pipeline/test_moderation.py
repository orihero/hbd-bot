"""Moderation: fail-closed on a verdict, and on an outage only when the note is ours."""

from __future__ import annotations

from hbd.config import Settings
from hbd.contracts import Err, LyricDraft, LyricSection
from hbd.errors import ErrorCode, ProviderUnavailableError
from hbd.pipeline.moderation import AllowAllModerator, LlmModerator, ModerationPayload
from hbd.pipeline.prompts import moderation_user_prompt
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_lyrics
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


async def test_refuses_a_customer_written_lyric_when_the_moderation_call_fails(
    settings: Settings,
) -> None:
    """Failing open is a trade about a short note. It is not a trade about the product.

    A pasted lyric is up to three thousand characters that go to the music vendor unaltered
    and come back as the thing the customer receives. An outage must not be the route by
    which those words skip the gate, so this case fails closed — retryably, because what
    failed is the transport and not the brief.
    """
    # Arrange
    llm = FakeLlmProvider()
    llm.fail_next("ModerationPayload", ProviderUnavailableError("down", provider="fake"))
    brief = make_brief(note="a kind note", approved_lyrics=_lyric_saying("Bir umr baxtli boʻl"))

    # Act
    result = await LlmModerator(llm, settings).review(brief)

    # Assert
    error = failure_of(result)
    assert error.error_code is ErrorCode.CONTENT_REJECTED
    assert error.is_retryable is True


async def test_allow_all_moderator_never_refuses() -> None:
    # Arrange / Act
    result = await AllowAllModerator().review(make_brief(note="anything at all"))

    # Assert
    assert not isinstance(result, Err)


# ---------------------------------------------------------------------------
# The lyric the customer approved is free text too
# ---------------------------------------------------------------------------
def _lyric_saying(line: str) -> LyricDraft:
    """A well-formed lyric whose chorus says exactly what a test needs it to say."""
    return make_lyrics(
        sections=(
            LyricSection(label="verse-1", lines=("Bugun sahna gullaydi",)),
            LyricSection(label="hook", lines=(UZBEK_NAME_CANONICAL,), is_name_hook=True),
            LyricSection(label="chorus", lines=(line,)),
        )
    )


async def test_rejects_a_denylisted_word_that_appears_only_in_the_approved_lyric(
    settings: Settings,
) -> None:
    """A pasted lyric ships to a music vendor as the product, so it faces the same gate."""
    # Arrange
    llm = FakeLlmProvider()
    brief = make_brief(
        note="Loves plov and long walks.",
        approved_lyrics=_lyric_saying("tonight we bomb the dance floor"),
    )

    # Act
    result = await LlmModerator(llm, settings).review(brief)

    # Assert
    error = failure_of(result)
    assert error.error_code is ErrorCode.CONTENT_REJECTED
    assert error.context["pattern_hit"].casefold() == "bomb"
    assert llm.requests == []


async def test_says_which_field_the_denylist_landed_in_so_a_false_positive_is_triageable(
    settings: Settings,
) -> None:
    """A whole song is now scanned by bare-word regexes; an operator must not have to guess."""
    # Arrange
    clean_note = "Loves plov and long walks."
    brief = make_brief(
        note=clean_note, approved_lyrics=_lyric_saying("tonight we bomb the dance floor")
    )

    # Act
    result = await LlmModerator(FakeLlmProvider(), settings).review(brief)

    # Assert
    error = failure_of(result)
    assert error.context["hit_in"] == "lyrics"
    # The note stays in the context either way: it is what triage reads first.
    assert error.context["note"] == clean_note


async def test_still_blames_the_note_when_that_is_where_the_word_was(
    settings: Settings,
) -> None:
    # Arrange
    brief = make_brief(note="I will kill him on his birthday", approved_lyrics=make_lyrics())

    # Act
    result = await LlmModerator(FakeLlmProvider(), settings).review(brief)

    # Assert
    assert failure_of(result).context["hit_in"] == "note"


async def test_allows_a_brief_whose_approved_lyric_is_as_harmless_as_its_note(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()
    brief = make_brief(note="a kind note", approved_lyrics=make_lyrics())

    # Act
    result = await LlmModerator(llm, settings).review(brief)

    # Assert: allowed, and the model was actually consulted rather than short-circuited
    assert not isinstance(result, Err)
    assert len(llm.requests) == 1


# ---------------------------------------------------------------------------
# What the reviewer is shown
# ---------------------------------------------------------------------------
#: The whole prompt for a brief with no approved lyric, spelled out rather than derived.
#: Its job is to fail loudly if the preview step ever changes the common path by a byte.
_PROMPT_WITHOUT_LYRICS = (
    f'Recipient name: "{UZBEK_NAME_CANONICAL}"\n'
    "Occasion: birthday\n"
    'Sender note: "Loves mountains and his grandmother\'s plov."'
)


def test_the_moderation_prompt_is_unchanged_for_a_brief_that_has_no_approved_lyric() -> None:
    # Arrange / Act
    prompt = moderation_user_prompt(make_brief())

    # Assert
    assert prompt == _PROMPT_WITHOUT_LYRICS
    assert "Song lyrics" not in prompt


def test_the_moderation_prompt_shows_the_lyric_when_the_customer_approved_one() -> None:
    # Arrange
    lyric = make_lyrics()

    # Act
    prompt = moderation_user_prompt(make_brief(approved_lyrics=lyric))

    # Assert: the old material first, byte for byte, then the lyric appended whole
    assert prompt == f'{_PROMPT_WITHOUT_LYRICS}\nSong lyrics: "{lyric.as_plain_text()}"'
    assert UZBEK_NAME_CANONICAL in prompt
