"""The prompts the model actually receives.

There are two prompt systems in this repo and only one of them is ever sent. These tests
pin the live one — ``bayram.pipeline.prompts`` — because the Uzbek orthography rules lived
for a long time in a template that no production call path could reach.
"""

from __future__ import annotations

from bayram.contracts import Brief, Language, Occasion
from bayram.pipeline.prompts import OCCASION_BRIEFS, lyrics_system_prompt, lyrics_user_prompt
from bayram.providers.llm.prompt_loader import language_guide

TURNED_COMMA = "ʻ"
MODIFIER_APOSTROPHE = "ʼ"


def test_the_live_lyric_prompt_carries_the_language_guide() -> None:
    """Not a paraphrase of the guide — the guide itself, so the two cannot drift."""
    # Arrange / Act
    prompt = lyrics_system_prompt(Language.UZ_LATN)

    # Assert
    assert language_guide(Language.UZ_LATN) in prompt


def test_the_uzbek_latin_prompt_states_the_orthography_rule_in_the_right_codepoints() -> None:
    """A rule written with ASCII apostrophes teaches the model the wrong character."""
    # Arrange / Act
    prompt = lyrics_system_prompt(Language.UZ_LATN)

    # Assert
    assert TURNED_COMMA in prompt
    assert MODIFIER_APOSTROPHE in prompt


def test_every_supported_language_gets_its_own_guide() -> None:
    # Arrange / Act / Assert
    for language in Language:
        assert language_guide(language) in lyrics_system_prompt(language)


def test_the_shared_rules_survive_the_guide_being_injected() -> None:
    """The guide is added to the prompt, not swapped in for what was already there."""
    # Arrange / Act
    prompt = lyrics_system_prompt(Language.UZ_LATN)

    # Assert
    assert "is_name_hook" in prompt
    assert "ALL CAPS" in prompt


def test_the_live_lyric_prompt_asks_for_craft_not_only_prohibitions() -> None:
    """The prompt used to say only what to avoid, and got unobjectionable filler back."""
    # Arrange / Act
    prompt = lyrics_system_prompt(Language.UZ_LATN)

    # Assert
    assert "Rhyme" in prompt
    assert "repeat its words" in prompt
    assert "two concrete details" in prompt


def test_the_live_lyric_prompt_keeps_the_structural_contract_after_the_craft_merge() -> None:
    """Craft rules were added around the section contract, not over it."""
    # Arrange / Act
    prompt = lyrics_system_prompt(Language.UZ_LATN)

    # Assert
    assert "4 to 6 sections" in prompt
    assert "is_name_hook" in prompt


def test_the_shape_sentence_the_parser_depends_on_is_untouched(brief: Brief) -> None:
    """``LyricsPayload`` reads title and sections; the merge must not drift the keys."""
    # Arrange / Act
    prompt = lyrics_user_prompt(brief)

    # Assert
    assert (
        'Return JSON shaped as {"title": str, "sections": '
        '[{"label": str, "lines": [str], "is_name_hook": bool}]}.'
    ) in prompt


def test_every_occasion_has_a_phrase_the_writer_can_be_given() -> None:
    """``OCCASION_BRIEFS`` is subscripted, not ``.get``-ed, so a gap is a live KeyError.

    It fails at the lyric stage — after the order is taken and the customer is watching a
    progress bar — which is the worst place in the run to discover that somebody added an
    occasion to the enum and stopped there. The list was widened from three members to ten
    exactly once and this is the fence that keeps the eleventh honest.
    """
    # Arrange / Act
    missing = [occasion.value for occasion in Occasion if occasion not in OCCASION_BRIEFS]

    # Assert
    assert missing == []
