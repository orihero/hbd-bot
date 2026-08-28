"""One function per wizard screen: draft in, text + keyboard out.

Rendering is kept apart from handling on purpose. A screen is a pure function of the draft,
so Back is implemented once — "render the previous step" — instead of once per handler,
and every screen is assertable in a test without a Bot, an Update or an event loop.

``resolve_step`` is the safety net: a step the draft cannot render (a name confirmation
with no name in it, or a lyric preview with no lyric in it, because storage was cleared
under us) is downgraded to the nearest step that *can* be rendered, rather than producing a
screen with a hole in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from aiogram.types import InlineKeyboardMarkup

from hbd.bot.callbacks import LanguageSlot
from hbd.bot.draft import MAX_NOTE_CHARS, WizardDraft
from hbd.bot.i18n import (
    escape_html,
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
    lyrics_keyboard,
    name_confirm_keyboard,
    name_prompt_keyboard,
    note_keyboard,
    occasion_keyboard,
    vocal_gender_keyboard,
)
from hbd.bot.states import WizardStep
from hbd.contracts import Language

__all__ = ["Screen", "render_step", "resolve_step", "welcome_screen", "MAX_PREVIEW_LYRIC_CHARS"]

#: How much of a lyric the preview shows. Telegram refuses a message over 4096 characters,
#: and a generated lyric is bounded only by the lyric-shape constants — eight sections of
#: eight 160-character lines is ten thousand — so an unclamped preview would be rejected by
#: the API and, because ``_edit_or_send`` retries the SAME text with ``answer``, the retry
#: would fail too and the customer would get a generic error instead of their song. What is
#: elided here is display only: the draft the user approves is the whole lyric.
#:
#: The budget is spent in ESCAPED characters, because that is the string Telegram counts.
#: ``translate`` HTML-escapes every parameter, and escaping inflates: one ``&`` costs one
#: character here and the five of ``&amp;`` on the wire, one ``<`` or ``>`` costs four.
#: (It does NOT touch apostrophes — ``escape_html`` passes ``quote=False`` — so testing the
#: clamp with an apostrophe-heavy lyric finds no inflation and proves nothing.) A lyric well
#: inside the paste limit can therefore still render past 4096 if the clamp is measured on
#: the text the customer typed rather than on the text we send.
MAX_PREVIEW_LYRIC_CHARS: Final[int] = 3_000

#: Appended when the preview had to be cut, so a short screen never reads as a short lyric.
_ELLIPSIS: Final[str] = "…"


@dataclass(frozen=True, slots=True)
class Screen:
    """What to put on the user's screen. Immutable, and free of any Telegram plumbing."""

    text: str
    markup: InlineKeyboardMarkup | None = None
    #: True when the next thing we expect from the user is typed text, not a button.
    is_text_expected: bool = False


def resolve_step(step: WizardStep, draft: WizardDraft) -> WizardStep:
    """Downgrade ``step`` to one this draft can actually render.

    LYRICS is checked before CONFIRM because it is now the only route to it: a draft that
    has every answer but no approved lyric belongs on the preview screen, not on a summary
    of a song whose words have not been written yet.
    """
    if step is WizardStep.NAME_CONFIRM and draft.recipient is None:
        return WizardStep.NAME
    if step is WizardStep.LYRICS and draft.lyrics is None:
        return WizardStep.OUTPUT_LANGUAGE
    if step is WizardStep.CONFIRM and not draft.is_complete:
        if draft.recipient is None:
            return WizardStep.NAME
        if draft.missing_answers:
            return WizardStep.OUTPUT_LANGUAGE
        return WizardStep.LYRICS
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
        case WizardStep.LYRICS:
            return _lyrics_screen(draft)
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


def _elide_for_preview(body: str) -> str:
    """Cut ``body`` so its *escaped* form fits :data:`MAX_PREVIEW_LYRIC_CHARS`.

    Counted one source character at a time rather than by slicing the escaped string,
    because a slice can land inside ``&amp;`` and hand Telegram a broken entity — which is
    the same rejected message the clamp exists to avoid, arrived at from the other side.
    """
    if len(escape_html(body)) <= MAX_PREVIEW_LYRIC_CHARS:
        return body
    kept: list[str] = []
    spent = 0
    for char in body:
        spent += len(escape_html(char))
        if spent > MAX_PREVIEW_LYRIC_CHARS:
            break
        kept.append(char)
    return "".join(kept) + _ELLIPSIS


def _lyrics_screen(draft: WizardDraft) -> Screen:
    """Show the words before a single cent is spent, and invite all three answers to them.

    ``translate`` HTML-escapes every parameter exactly once, so the template is free to wrap
    ``{lyrics}`` in ``<pre>`` and nothing is escaped at this call site.
    """
    language = draft.ui_language
    lyrics = draft.lyrics
    if lyrics is None:
        return render_step(WizardStep.OUTPUT_LANGUAGE, draft)
    body = _elide_for_preview(lyrics.as_plain_text())
    return Screen(
        translate("wizard.lyrics.preview", language, title=lyrics.title, lyrics=body),
        lyrics_keyboard(language),
        is_text_expected=True,
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
