"""Prompt templates live in files, and every placeholder must be supplied.

These also assert the orthography instructions the product depends on, so nobody can
quietly delete "never use capitals for stress" or the U+02BB rule during an edit.
"""

from __future__ import annotations

import pytest

from bayram.contracts import Language
from bayram.errors import ConfigError
from bayram.providers.llm.prompt_loader import language_guide, load_prompt, render_prompt

MODIFIER_TURNED_COMMA = "ʻ"
ALL_TEMPLATES = (
    "kit_system",
    "kit_user",
    "intake_system",
    "intake_user",
    "retry_nudge",
    "lang_uz_latn",
    "lang_uz_cyrl",
    "lang_ru",
    "lang_en",
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_shipped_template_loads_and_is_not_empty(name: str) -> None:
    assert load_prompt(name).strip()


def test_a_missing_template_raises_a_config_error_naming_it() -> None:
    with pytest.raises(ConfigError, match="no_such_prompt"):
        load_prompt("no_such_prompt")


@pytest.mark.parametrize("language", list(Language))
def test_every_language_has_its_own_guide(language: Language) -> None:
    assert language_guide(language).strip()


def test_the_four_language_guides_are_all_different() -> None:
    guides = {language_guide(language) for language in Language}

    assert len(guides) == len(Language)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def test_render_substitutes_every_placeholder() -> None:
    rendered = render_prompt("intake_user", _intake_values())

    assert "{{" not in rendered
    assert "Gʻulomjon" in rendered


def test_render_raises_a_config_error_naming_the_missing_placeholders() -> None:
    with pytest.raises(ConfigError, match="raw_note"):
        render_prompt("intake_user", {"raw_name": "A"})


def test_render_ignores_values_the_template_does_not_use() -> None:
    rendered = render_prompt("intake_user", {**_intake_values(), "unused": "ignored"})

    assert "ignored" not in rendered


# ---------------------------------------------------------------------------
# The orthography instructions the product depends on
# ---------------------------------------------------------------------------
def test_the_uzbek_latin_guide_demands_the_modifier_turned_comma() -> None:
    guide = language_guide(Language.UZ_LATN)

    assert MODIFIER_TURNED_COMMA in guide
    assert "U+02BB" in guide


def test_the_uzbek_guides_state_that_stress_falls_on_the_final_syllable() -> None:
    for language in (Language.UZ_LATN, Language.UZ_CYRL):
        assert "FINAL syllable" in language_guide(language)


def test_the_russian_guide_demands_the_yo_vowel_be_preserved() -> None:
    guide = language_guide(Language.RU)

    assert "ё" in guide
    assert "Алёна" in guide


@pytest.mark.parametrize("language", list(Language))
def test_no_guide_ever_recommends_capitals_for_stress(language: Language) -> None:
    # ALL CAPS means LOUDER to a music model, not stressed. This must never drift back in.
    guide = language_guide(language)

    assert "capital" in guide.lower()
    assert "volume" in guide.lower() or "LOUDER" in guide


def test_the_kit_system_prompt_forbids_naming_a_real_artist() -> None:
    # A vendor rejects the whole request when it sees one, burning a paid generation.
    assert "artist" in load_prompt("kit_system")


def _intake_values() -> dict[str, str]:
    return {
        "raw_name": "Gʻulomjon",
        "raw_note": "loves plov",
        "ui_language": "ru",
        "output_language": "uz_latn",
    }
