"""The prompts the model actually receives.

There are two prompt systems in this repo and only one of them is ever sent. These tests
pin the live one — ``hbd.pipeline.prompts`` — because the Uzbek orthography rules lived
for a long time in a template that no production call path could reach.
"""

from __future__ import annotations

from hbd.contracts import Language
from hbd.pipeline.prompts import lyrics_system_prompt
from hbd.providers.llm.prompt_loader import language_guide

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
