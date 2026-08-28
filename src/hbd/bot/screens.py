"""One function per wizard screen: draft in, text + keyboard out.

Rendering is kept apart from handling on purpose. A screen is a pure function of the draft,
so Back is implemented once — "render the previous step" — instead of once per handler,
and every screen is assertable in a test without a Bot, an Update or an event loop.

``resolve_step`` is the safety net: a step the draft cannot render (a name confirmation
with no name in it, because storage was cleared under us) is downgraded to the nearest step
that *can* be rendered, rather than producing a screen with a hole in it.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardMarkup

from hbd.bot.callbacks import LanguageSlot
from hbd.bot.draft import MAX_NOTE_CHARS, WizardDraft
from hbd.bot.i18n import (
    genre_label,
    language_label,
    occasion_label,
    translate,
    vocal_gender_label,
)
from hbd.bot.keyboards import (
    confirm_keyboard,
    genre_keyboard,
    language_keyboard,
    name_confirm_keyboard,
    name_prompt_keyboard,
    note_keyboard,
    occasion_keyboard,
    vocal_gender_keyboard,
)
from hbd.bot.states import WizardStep
from hbd.contracts import Language

__all__ = ["Screen", "render_step", "resolve_step", "welcome_screen"]


@dataclass(frozen=True, slots=True)
class Screen:
    """What to put on the user's screen. Immutable, and free of any Telegram plumbing."""

    text: str
    markup: InlineKeyboardMarkup | None = None
    #: True when the next thing we expect from the user is typed text, not a button.
    is_text_expected: bool = False


def resolve_step(step: WizardStep, draft: WizardDraft) -> WizardStep:
    """Downgrade ``step`` to one this draft can actually render."""
    if step is WizardStep.NAME_CONFIRM and draft.recipient is None:
        return WizardStep.NAME
    if step is WizardStep.CONFIRM and not draft.is_complete:
        return WizardStep.NAME if draft.recipient is None else WizardStep.OUTPUT_LANGUAGE
    return step


def welcome_screen(language: Language) -> Screen:
    """The /start screen: greeting plus the interface-language picker, in one message."""
    text = "\n\n".join(
        (
            translate("start.welcome", language),
            translate("start.choose_ui_language", language),
        )
    )
    return Screen(
        text=text,
        markup=language_keyboard(LanguageSlot.UI, language, is_back_enabled=False),
    )


def render_step(step: WizardStep, draft: WizardDraft) -> Screen:
    """Render any wizard step. Total over :class:`WizardStep`; never raises."""
    language = draft.ui_language
    match step:
        case WizardStep.UI_LANGUAGE:
            return welcome_screen(language)
        case WizardStep.OCCASION:
            return Screen(
                translate("wizard.occasion.prompt", language), occasion_keyboard(language)
            )
        case WizardStep.GENRE:
            return Screen(translate("wizard.genre.prompt", language), genre_keyboard(language))
        case WizardStep.VOCAL_GENDER:
            return Screen(
                translate("wizard.vocal_gender.prompt", language), vocal_gender_keyboard(language)
            )
        case WizardStep.NOTE:
            return Screen(
                translate("wizard.note.prompt", language, limit=MAX_NOTE_CHARS),
                note_keyboard(language),
                is_text_expected=True,
            )
        case WizardStep.NAME:
            return Screen(
                translate("wizard.name.prompt", language),
                name_prompt_keyboard(language),
                is_text_expected=True,
            )
        case WizardStep.NAME_CONFIRM:
            return _name_confirm_screen(draft)
        case WizardStep.OUTPUT_LANGUAGE:
            return Screen(
                translate("wizard.output_language.prompt", language),
                language_keyboard(LanguageSlot.OUTPUT, language, is_back_enabled=True),
            )
        case WizardStep.CONFIRM:
            return _confirm_screen(draft)


def _name_confirm_screen(draft: WizardDraft) -> Screen:
    """Echo the canonical DISPLAY spelling — the ``ʻ`` intact — for confirmation.

    What goes to the vendor is a different string entirely and is never shown here.
    """
    language = draft.ui_language
    recipient = draft.recipient
    if recipient is None:
        return render_step(WizardStep.NAME, draft)
    return Screen(
        translate("wizard.name.confirm", language, name=recipient.display),
        name_confirm_keyboard(language),
    )


def _confirm_screen(draft: WizardDraft) -> Screen:
    language = draft.ui_language
    recipient = draft.recipient
    occasion, genre = draft.occasion, draft.genre
    vocal_gender, output_language = draft.vocal_gender, draft.output_language
    if (
        recipient is None
        or occasion is None
        or genre is None
        or vocal_gender is None
        or output_language is None
    ):
        return render_step(resolve_step(WizardStep.CONFIRM, draft), draft)
    text = translate(
        "wizard.confirm.summary",
        language,
        name=recipient.display,
        occasion=occasion_label(occasion, language),
        genre=genre_label(genre, language),
        vocal_gender=vocal_gender_label(vocal_gender, language),
        output_language=language_label(output_language, language),
        note=draft.note.strip() or translate("wizard.confirm.no_note", language),
    )
    return Screen(text, confirm_keyboard(language))
