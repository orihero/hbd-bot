"""Moderation: fail-closed on a verdict, and on an outage only when the note is ours.

The last section is about the opposite failure. A gate that refuses a paying customer's
harmless note is not "safe", it is broken, and it broke silently in production — so the
wording of the reject list is pinned here, and the live model is asked the real question
under ``integration``.
"""

from __future__ import annotations

from typing import Final

import httpx
import pytest

from hbd.config import Settings, build_settings
from hbd.contracts import Err, LlmRequest, LyricDraft, LyricSection
from hbd.errors import ErrorCode, ProviderUnavailableError
from hbd.pipeline.moderation import AllowAllModerator, LlmModerator, ModerationPayload
from hbd.pipeline.prompts import moderation_system_prompt, moderation_user_prompt
from hbd.providers.llm.factory import build_llm_provider
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_lyrics
from tests.test_pipeline.conftest import FakeLlmProvider, failure_of

#: The live golden test needs the real credential, so it must be able to name it in the
#: skip message an operator reads when nothing ran.
_LLM_KEY_ENV: Final[str] = "HBD_LLM_API_KEY"

#: ``Settings`` requires a database URL and the golden test opens no connection; this keeps
#: an unconfigured host from turning a moderation question into a config error.
_UNUSED_DATABASE_URL: Final[str] = "postgresql+asyncpg://unused/unused"


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


# ---------------------------------------------------------------------------
# The alcohol false positive that cost a real order
# ---------------------------------------------------------------------------
#: The exact note from order 1251314e-2138-4d4e-a263-2874a0c08601, which failed at
#: MODERATING five seconds in and showed a paying customer 9% and a generic error.
#: Roughly: "he loves drinking beer, works at a logistics company! Married, recently had a
#: child" — an ordinary affectionate ribbing of a friend, and the product's core use case.
LIVE_BEER_NOTE = (
    "Pivo ichishni yqotiradi, logistica kompaniyasida ishlaydi! Uylangan yaqinda farzandli bo'lafi"
)


def test_the_moderation_prompt_permits_a_light_hearted_mention_of_drinking() -> None:
    """The reject list must name the behaviour, not the noun.

    "promotes alcohol or drugs" made the model treat any mention of beer as promotion, and
    that item outranked the sentence right after it that allows an affectionate note about
    a friend. Regression pin for order 1251314e-2138-4d4e-a263-2874a0c08601.
    """
    # Arrange / Act
    prompt = moderation_system_prompt()

    # Assert: the over-broad formulation is gone …
    assert "promotes alcohol" not in prompt
    # … replaced by one that only refuses celebrating the behaviour …
    assert "glorifies drug use or drunkenness" in prompt
    # … and the carve-out now says out loud what an Uzbek birthday note actually contains.
    assert "including light-hearted references to drinking, food or habits" in prompt


async def test_the_local_denylist_does_not_fire_on_the_live_beer_note(
    settings: Settings,
) -> None:
    """The cheap layer was never the problem here; this keeps it that way.

    The denylist is a tripwire for unmistakable abuse, so the note that broke the order in
    production must reach the model rather than being refused before the call.
    """
    # Arrange
    llm = FakeLlmProvider()

    # Act
    result = await LlmModerator(llm, settings).review(make_brief(note=LIVE_BEER_NOTE))

    # Assert
    assert not isinstance(result, Err)
    assert len(llm.requests) == 1


@pytest.mark.integration
async def test_the_configured_model_allows_the_live_beer_note() -> None:
    """The golden test: the real note, the real configured model, a real verdict.

    Everything above pins wording; only this pins *behaviour*, because the failure was the
    model's reading of the wording and no fake can reproduce that. Skips rather than fails
    without a key, so a keyless CI run is unaffected — ``make test`` excludes it anyway.

    It deliberately does not take the ``settings`` fixture: that fixture strips every
    ``HBD_`` variable from the environment, which is right for a unit test and fatal for
    one whose whole point is to ask the vendor the customer's model was asked. The database
    URL is overridden because nothing here touches a database and a missing one must not
    turn this into a config failure; every LLM setting still comes from the environment or
    ``.env``, so what answers here is what answers in production.
    """
    # Arrange
    live = build_settings({"database_url": _UNUSED_DATABASE_URL}, require_vendor_secrets=False)
    if not live.llm_api_key:
        pytest.skip(f"{_LLM_KEY_ENV} is not set; skipping the live moderation golden test")
    request = LlmRequest(
        system_prompt=moderation_system_prompt(),
        user_prompt=moderation_user_prompt(make_brief(note=LIVE_BEER_NOTE)),
        temperature=0.0,
        max_output_tokens=live.llm_max_output_tokens,
    )

    # Act
    async with httpx.AsyncClient() as client:
        llm = build_llm_provider(live, client=client)
        result = await llm.generate_json(request, ModerationPayload, timeout_s=live.llm_timeout_s)

    # Assert: a transport failure is a failed test, not a pass — fail-open lives in the
    # moderator, and this test is about what the model says.
    assert not isinstance(result, Err), f"moderation call failed: {result}"
    assert result.value.is_allowed is True, (
        f"{live.llm_model_id} still rejects an affectionate note about a friend: "
        f"{result.value.reason}"
    )
