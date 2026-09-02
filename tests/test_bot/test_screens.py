"""Screens are pure functions of the draft, so they are tested as pure functions."""

from __future__ import annotations

import re

import pytest

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.draft import MAX_NOTE_CHARS, WizardDraft
from hbd.bot.i18n import translate
from hbd.bot.keyboards import KEEP_NOTE_LABEL_KEY, SKIP_LABEL_KEY
from hbd.bot.screens import MAX_PREVIEW_LYRIC_CHARS, render_step, resolve_step, welcome_screen
from hbd.bot.states import WIZARD_ORDER, WizardStep
from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Genre,
    Language,
    LyricDraft,
    LyricSection,
    Occasion,
    VoiceGender,
)
from tests.conftest import UZBEK_NAME_CANONICAL, make_lyrics, make_name
from tests.test_bot.conftest import buttons

#: An unfilled ``str.format`` placeholder, as it reaches the customer. ``translate`` renders
#: one rather than raising when a call site forgets a parameter, so the only place this can
#: be caught is a rendered screen.
_UNFILLED_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def full_draft(**overrides: object) -> WizardDraft:
    """A draft every step can render, the approved lyric included.

    The lyric is part of "full" now: without it ``resolve_step`` downgrades both the
    preview and the summary, and the tests below that walk all of ``WIZARD_ORDER`` would be
    asserting about a screen the draft cannot actually reach.
    """
    base = WizardDraft(
        ui_language=Language.EN,
        occasion=Occasion.ANNIVERSARY,
        genre=Genre.JAZZ_LOUNGE,
        vocal_gender=VoiceGender.DUET,
        note="Adores late-night jazz",
        recipient=make_name(),
        output_language=Language.RU,
        lyrics=make_lyrics(),
    )
    return base.updated(**overrides) if overrides else base


@pytest.mark.parametrize("step", list(WIZARD_ORDER))
def test_every_step_renders_non_empty_text(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert screen.text.strip()


@pytest.mark.parametrize("step", [s for s in WIZARD_ORDER if s is not WizardStep.UI_LANGUAGE])
def test_every_step_after_the_first_draws_a_back_button(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert NavCB(action=NavAction.BACK).pack() in {d for _, d in buttons(screen.markup)}


def test_the_first_step_has_no_back_button() -> None:
    # Arrange / Act
    screen = welcome_screen(Language.EN)

    # Assert
    assert NavCB(action=NavAction.BACK).pack() not in {d for _, d in buttons(screen.markup)}


@pytest.mark.parametrize("step", list(WIZARD_ORDER))
def test_every_step_can_be_cancelled(step: WizardStep) -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(step, draft)

    # Assert
    assert NavCB(action=NavAction.CANCEL).pack() in {d for _, d in buttons(screen.markup)}


def test_only_the_note_step_offers_skip() -> None:
    # Arrange
    draft = full_draft()
    skip = NavCB(action=NavAction.SKIP).pack()

    # Act
    with_skip = {
        step
        for step in WIZARD_ORDER
        if skip in {d for _, d in buttons(render_step(step, draft).markup)}
    }

    # Assert
    assert with_skip == {WizardStep.NOTE}


def test_text_is_expected_on_the_note_name_and_lyrics_steps() -> None:
    """The lyric preview accepts a pasted lyric, so it is a typing step like the other two."""
    # Arrange
    draft = full_draft()

    # Act
    typing_steps = {step for step in WIZARD_ORDER if render_step(step, draft).is_text_expected}

    # Assert
    assert typing_steps == {WizardStep.NOTE, WizardStep.NAME, WizardStep.LYRICS}


@pytest.mark.parametrize("step", list(WIZARD_ORDER))
@pytest.mark.parametrize("language", list(Language))
def test_no_screen_ships_an_unfilled_placeholder(step: WizardStep, language: Language) -> None:
    """``translate`` renders ``{name}`` literally rather than raising when a caller forgets.

    That is the right behaviour — a customer must never see a stack trace because a
    translator dropped a placeholder — and it is also why a forgotten parameter is
    invisible until somebody reads the screen. Several templates gained parameters at once
    (the recipient's name, the two character limits), and this is the one assertion that
    covers all of them, in all four locales, for good.
    """
    # Arrange
    draft = full_draft(ui_language=language)

    # Act
    screen = render_step(step, draft)

    # Assert
    assert not _UNFILLED_PLACEHOLDER.search(screen.text), screen.text


@pytest.mark.parametrize("step", [WizardStep.NOTE, WizardStep.NAME, WizardStep.OUTPUT_LANGUAGE])
def test_a_draft_with_no_name_yet_still_renders(step: WizardStep) -> None:
    """``render_step`` is total. Three screens now reach for the recipient; none may raise."""
    # Arrange — the state after Retype, and after storage lost the name under us
    draft = full_draft(recipient=None, lyrics=None)

    # Act
    screen = render_step(step, draft)

    # Assert
    assert screen.text.strip()
    assert not _UNFILLED_PLACEHOLDER.search(screen.text), screen.text


# ---------------------------------------------------------------------------
# the recipient, once we know who they are
# ---------------------------------------------------------------------------
def test_the_output_language_question_names_the_recipient() -> None:
    """From the name step onwards the bot knows who this is for and used to never say it."""
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.OUTPUT_LANGUAGE, draft)

    # Assert
    assert UZBEK_NAME_CANONICAL in screen.text


def test_the_output_language_question_falls_back_to_a_key_without_a_name() -> None:
    """An empty ``{name}`` would render "Which language should 's song be in?"."""
    # Arrange
    draft = full_draft(recipient=None, lyrics=None)

    # Act
    screen = render_step(WizardStep.OUTPUT_LANGUAGE, draft)

    # Assert
    assert screen.text == translate("wizard.output_language.prompt_noname", Language.EN)


def test_the_summary_headlines_the_recipient_rather_than_listing_them() -> None:
    """The commit screen led with the bot's word for the product and buried the person.

    Asserted as "named once", because the fix was not only adding the headline — the
    ``Name:`` row went with it, and leaving both in reads as a duplicate.
    """
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.CONFIRM, draft)

    # Assert
    assert screen.text.count(UZBEK_NAME_CANONICAL) == 1
    assert screen.text.index(UZBEK_NAME_CANONICAL) < screen.text.index("\n")


# ---------------------------------------------------------------------------
# Back must not be destructive
# ---------------------------------------------------------------------------
def test_the_note_step_shows_the_note_already_written() -> None:
    """Reached through Back, this screen used to re-ask a question the draft could answer."""
    # Arrange
    draft = full_draft(note="Adores late-night jazz")

    # Act
    screen = render_step(WizardStep.NOTE, draft)

    # Assert
    assert "Adores late-night jazz" in screen.text


def test_the_note_step_offers_to_keep_an_existing_note_instead_of_skipping_it() -> None:
    """Skip wrote an empty string over six hundred characters nobody could retype."""
    # Arrange
    with_note = full_draft(note="Adores late-night jazz")
    without = full_draft(note="")
    skip = NavCB(action=NavAction.SKIP).pack()

    # Act
    kept = {data: text for text, data in buttons(render_step(WizardStep.NOTE, with_note).markup)}
    fresh = {data: text for text, data in buttons(render_step(WizardStep.NOTE, without).markup)}

    # Assert — same button, different promise
    assert kept[skip] == translate(KEEP_NOTE_LABEL_KEY, Language.EN)
    assert fresh[skip] == translate(SKIP_LABEL_KEY, Language.EN)


def test_the_note_step_escapes_the_note_it_echoes() -> None:
    """The echo is the one value on these screens that no template escapes for us."""
    # Arrange
    draft = full_draft(note="<script>alert(1)</script>")

    # Act
    screen = render_step(WizardStep.NOTE, draft)

    # Assert
    assert "<script>" not in screen.text
    assert "&lt;script&gt;" in screen.text


def test_the_note_step_says_how_long_the_note_is_kept() -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NOTE, draft)

    # Assert
    assert translate("wizard.note.privacy_line", Language.EN) in screen.text


def test_the_note_step_states_its_character_limit() -> None:
    """``screens.py`` always passed ``{limit}``; the template used to discard it silently."""
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NOTE, draft)

    # Assert
    assert str(MAX_NOTE_CHARS) in screen.text


def test_the_name_step_shows_the_name_already_resolved() -> None:
    """Back from the confirmation used to mean retyping the spelling from memory."""
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NAME, draft)

    # Assert
    assert UZBEK_NAME_CANONICAL in screen.text


def test_the_name_step_never_echoes_a_submitted_candidate() -> None:
    """The vendor-facing spellings are not a screen's business, on this screen either."""
    # Arrange
    draft = full_draft()
    submitted = [
        candidate.text
        for candidate in draft.recipient.candidates  # type: ignore[union-attr]
        if candidate.text != UZBEK_NAME_CANONICAL
    ]

    # Act
    screen = render_step(WizardStep.NAME, draft)

    # Assert
    assert submitted, "the fixture must offer a candidate that differs from the display form"
    for spelling in submitted:
        assert spelling not in screen.text


def test_the_name_step_states_its_character_limit() -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NAME, draft)

    # Assert
    assert str(MAX_RECIPIENT_NAME_CHARS) in screen.text


def test_name_confirmation_shows_the_display_spelling() -> None:
    # Arrange
    draft = full_draft()

    # Act
    screen = render_step(WizardStep.NAME_CONFIRM, draft)

    # Assert
    assert UZBEK_NAME_CANONICAL in screen.text


def test_name_confirmation_never_shows_a_submitted_candidate() -> None:
    # Arrange
    draft = full_draft()
    submitted = [
        candidate.text
        for candidate in draft.recipient.candidates  # type: ignore[union-attr]
        if candidate.text != UZBEK_NAME_CANONICAL
    ]

    # Act
    screen = render_step(WizardStep.NAME_CONFIRM, draft)

    # Assert
    for spelling in submitted:
        assert spelling not in screen.text


def test_summary_renders_an_empty_note_as_a_dash() -> None:
    # Arrange
    draft = full_draft(note="")

    # Act
    screen = render_step(WizardStep.CONFIRM, draft)

    # Assert
    assert "—" in screen.text


def test_summary_escapes_a_hostile_note() -> None:
    # Arrange
    draft = full_draft(note="<script>alert(1)</script>")

    # Act
    screen = render_step(WizardStep.CONFIRM, draft)

    # Assert
    assert "<script>" not in screen.text
    assert "&lt;script&gt;" in screen.text


def test_resolve_step_downgrades_a_confirmation_with_no_name() -> None:
    # Arrange
    draft = full_draft(recipient=None)

    # Act / Assert
    assert resolve_step(WizardStep.NAME_CONFIRM, draft) is WizardStep.NAME
    assert resolve_step(WizardStep.CONFIRM, draft) is WizardStep.NAME


def test_resolve_step_downgrades_a_summary_with_no_output_language() -> None:
    # Arrange
    draft = full_draft(output_language=None)

    # Act / Assert
    assert resolve_step(WizardStep.CONFIRM, draft) is WizardStep.OUTPUT_LANGUAGE


def test_resolve_step_leaves_a_renderable_step_alone() -> None:
    # Arrange
    draft = full_draft()

    # Act / Assert
    for step in WIZARD_ORDER:
        assert resolve_step(step, draft) is step


def test_resolve_step_downgrades_a_preview_with_no_lyric() -> None:
    """Storage lost the lyric under us: ask the language again, which writes a new one."""
    # Arrange
    draft = full_draft(lyrics=None)

    # Act / Assert
    assert resolve_step(WizardStep.LYRICS, draft) is WizardStep.OUTPUT_LANGUAGE


def test_resolve_step_downgrades_a_summary_whose_lyric_was_never_approved() -> None:
    """Every answer given but no lyric: the preview is the only route to the summary."""
    # Arrange
    draft = full_draft(lyrics=None)

    # Act / Assert
    assert resolve_step(WizardStep.CONFIRM, draft) is WizardStep.LYRICS


def test_the_preview_falls_back_to_the_language_question_with_no_lyric_to_show() -> None:
    """Rendered directly, not through ``resolve_step``: the fallback is its own contract.

    Every other test reaches the preview through ``resolve_step``, which downgrades first,
    so the screen's own guard is never asked to do anything. It still has to work — an
    empty preview would be a screen with a hole in it — and the fallback is what
    ``show_step``'s fixpoint relies on agreeing with.
    """
    # Arrange
    draft = full_draft(lyrics=None)

    # Act
    screen = render_step(WizardStep.LYRICS, draft)

    # Assert
    assert screen == render_step(WizardStep.OUTPUT_LANGUAGE, draft)


def test_the_lyric_preview_shows_the_title_and_the_words() -> None:
    # Arrange
    draft = full_draft()
    lyrics = make_lyrics()

    # Act
    screen = render_step(WizardStep.LYRICS, draft)

    # Assert
    assert lyrics.title in screen.text
    for section in lyrics.sections:
        for line in section.lines:
            assert line in screen.text


def test_the_lyric_preview_escapes_a_hostile_pasted_lyric() -> None:
    """A pasted lyric is user text going into a ``parse_mode=HTML`` message."""
    # Arrange
    hostile = make_lyrics(
        sections=(
            LyricSection(
                label="verse-1",
                lines=("<script>alert(1)</script>", UZBEK_NAME_CANONICAL),
                is_name_hook=True,
            ),
        )
    )
    draft = full_draft(lyrics=hostile)

    # Act
    screen = render_step(WizardStep.LYRICS, draft)

    # Assert
    assert "<script>" not in screen.text
    assert "&lt;script&gt;" in screen.text


def test_a_very_long_lyric_is_elided_so_telegram_will_accept_the_preview() -> None:
    """Telegram refuses a message over 4096 characters and the retry would refuse it too."""
    # Arrange — a lyric far past the ceiling, built the way the shape module allows
    long_line = "x" * 160
    draft = full_draft(
        lyrics=LyricDraft(
            title="Long one",
            language=Language.RU,
            sections=tuple(
                LyricSection(
                    label=f"section-{index + 1}",
                    lines=(long_line,) * 8,
                    is_name_hook=index == 0,
                )
                for index in range(8)
            ),
            name_display=UZBEK_NAME_CANONICAL,
        )
    )

    # Act
    screen = render_step(WizardStep.LYRICS, draft)

    # Assert
    assert len(screen.text) < 4_096
    assert len(draft.lyrics.as_plain_text()) > MAX_PREVIEW_LYRIC_CHARS  # type: ignore[union-attr]


def test_an_ampersand_heavy_lyric_is_elided_on_its_escaped_length_not_its_typed_length() -> None:
    """The clamp has to count what Telegram counts, or it lets the message through anyway.

    ``translate`` escapes every parameter, so ``&`` costs five characters on the wire and one
    on the keyboard. A lyric of 1 218 typed characters — comfortably inside both the paste
    limit and the preview clamp — renders as 6 144 and the API refuses it.
    """
    # Arrange
    ampersands = "&" * 160
    draft = full_draft(
        lyrics=LyricDraft(
            title="&&&",
            language=Language.EN,
            sections=tuple(
                LyricSection(
                    label=f"section-{index + 1}", lines=(ampersands,) * 2, is_name_hook=index == 0
                )
                for index in range(4)
            ),
            name_display=UZBEK_NAME_CANONICAL,
        )
    )
    typed = draft.lyrics.as_plain_text()  # type: ignore[union-attr]
    assert len(typed) < MAX_PREVIEW_LYRIC_CHARS, "the typed length must not trip the old clamp"

    # Act
    screen = render_step(WizardStep.LYRICS, draft)

    # Assert
    assert len(screen.text) < 4_096
    assert "&amp;" in screen.text, "entities must survive whole; a slice inside one is invalid"
    assert "&am;" not in screen.text and "&a;" not in screen.text
