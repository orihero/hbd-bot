"""One function per wizard screen: draft in, text + keyboard out.

Rendering is kept apart from handling on purpose. A screen is a pure function of the draft,
so Back is implemented once — "render the previous step" — instead of once per handler,
and every screen is assertable in a test without a Bot, an Update or an event loop.

``resolve_step`` is the safety net: a step the draft cannot render (a name confirmation
with no name in it, or a lyric preview with no lyric in it, because storage was cleared
under us) is downgraded to the nearest step that *can* be rendered, rather than producing a
screen with a hole in it.

Two rules the screens themselves hold, both of them learnt the hard way:

* **A step never hides an answer the draft already has.** Back through the wizard used to
  be quietly destructive — the note screen re-asked a question the draft could already
  answer and its Skip wrote an empty string over six hundred characters, and the name had
  to be retyped character for character. Every screen that owns a typed value now echoes
  it, so Back is a way to look at an answer rather than a way to lose it.
* **From the name step onwards the recipient is named.** The bot learns who the song is
  for and then never says it again, which reads as a form rather than as a person doing
  the work. Where a template takes ``{name}`` and the draft might not have one,
  ``render_step`` reaches for a sibling ``…_noname`` key rather than interpolating an
  empty string: this function is total over :class:`WizardStep` and must never raise.
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
from hbd.contracts import MAX_RECIPIENT_NAME_CHARS, Language

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


def render_step(step: WizardStep, draft: WizardDraft, *, credits_note: str | None = None) -> Screen:
    """Render any wizard step. Total over :class:`WizardStep`; never raises.

    ``credits_note`` is used by the Confirm screen alone and defaults to ``None``, which is
    what keeps every other call site — and the Confirm screen itself in a deployment with no
    meter — byte-identical to what it rendered before the entitlement layer existed. It
    arrives as finished text rather than as a balance because a screen is a pure function of
    the draft: reading the meter is I/O, it belongs to ``handlers.balance.show_confirm``, and
    a screen that could await would stop being assertable without an event loop.
    """
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
            return _note_screen(draft)
        case WizardStep.NAME:
            return _name_screen(draft)
        case WizardStep.NAME_CONFIRM:
            return _name_confirm_screen(draft)
        case WizardStep.OUTPUT_LANGUAGE:
            return _output_language_screen(draft)
        case WizardStep.LYRICS:
            return _lyrics_screen(draft)
        case WizardStep.CONFIRM:
            return _confirm_screen(draft, credits_note)


def _quoted(value: str) -> str:
    """Put a value the customer typed into the container this bot reserves for their words.

    Escaped here, unlike everywhere else on this screen, because nothing interpolates it:
    ``translate`` escapes its parameters and this string never passes through a template.
    It has no template because there is no sentence to wrap around it that would be worth
    translating four times — the ``<blockquote>`` already says "this is yours, not mine",
    which is exactly what an echoed answer needs to say and all it needs to say.
    """
    return f"<blockquote>{escape_html(value)}</blockquote>"


def _note_screen(draft: WizardDraft) -> Screen:
    """Ask for the note, show the note already given, and say what happens to it.

    The echo is what makes Back safe here. Without it the screen re-asks a question the
    draft can already answer, and the only visible way onwards is a Skip that used to
    erase what was written. The keyboard is told there is a note so it can offer to KEEP
    it instead — see ``note_keyboard``.

    The retention line is one sentence and it sits under the prompt rather than in
    ``/privacy``, because this is the screen where the customer is being asked to type
    something about a real person and it is the only moment the answer matters to them.
    """
    language = draft.ui_language
    note = draft.note.strip()
    parts = [translate("wizard.note.prompt", language, limit=MAX_NOTE_CHARS)]
    if note:
        parts.append(_quoted(note))
    parts.append(translate("wizard.note.privacy_line", language))
    return Screen(
        "\n\n".join(parts),
        note_keyboard(language, is_note_present=bool(note)),
        is_text_expected=True,
    )


def _name_screen(draft: WizardDraft) -> Screen:
    """Ask for the name, echoing the one already resolved when there is one.

    Only reachable with a name in hand via Back from the confirmation — Retype clears the
    recipient before it sends the user here — and that is precisely the case worth fixing:
    somebody who stepped back to check the spelling should be able to READ it rather than
    reproduce it from memory, since the spelling is what decides the pronunciation.

    The display form is the only spelling that ever reaches a screen; the vendor-facing
    candidates beside it in :class:`RecipientName` are never shown, here or anywhere.
    """
    language = draft.ui_language
    recipient = draft.recipient
    prompt = translate("wizard.name.prompt", language, limit=MAX_RECIPIENT_NAME_CHARS)
    text = prompt if recipient is None else f"{prompt}\n\n{_quoted(recipient.display)}"
    return Screen(text, name_prompt_keyboard(language), is_text_expected=True)


def _output_language_screen(draft: WizardDraft) -> Screen:
    """The last question, asked about somebody by name.

    ``render_step`` is total and must never raise, and a draft can reach this step with no
    recipient — ``resolve_step`` does not downgrade it, because the language can honestly
    be answered without a name. So the missing-name case gets its own key rather than an
    empty ``{name}``, which would render as "Which language should 's song be in?".
    """
    language = draft.ui_language
    recipient = draft.recipient
    text = (
        translate("wizard.output_language.prompt_noname", language)
        if recipient is None
        else translate("wizard.output_language.prompt", language, name=recipient.display)
    )
    return Screen(
        text,
        language_keyboard(LanguageSlot.OUTPUT, language, is_back_enabled=True),
    )


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

    This is the screen that answers the objection the rest of the flow cannot: the customer
    is not buying a promise, they are reading the exact words and nothing has been recorded
    yet. The template puts the lyric in a ``<blockquote expandable>`` and says so in the
    line underneath — the quote makes the words visibly theirs and keeps the bot's voice
    outside them, and expandable is what lets a long lyric be read in place rather than
    pushing the three answers off the screen.

    ``translate`` HTML-escapes every parameter exactly once, so the template owns the
    markup around ``{lyrics}`` and nothing is escaped at this call site.
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


def _confirm_screen(draft: WizardDraft, credits_note: str | None = None) -> Screen:
    """The commit screen, headlined by the person it is for.

    It used to open with the bot's word for the product and demote the recipient to one row
    of a five-row table, so the last thing read before the only irreversible press said
    nothing about who any of it was for. ``wizard.confirm.summary`` now leads with
    ``{name}`` and the row is gone with it — the same value cannot be both the headline and
    a line item without reading as a duplicate — which is why every parameter below is
    load-bearing and none of them may be dropped.
    """
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
    # Appended rather than woven into ``wizard.confirm.summary``: the note is true only when
    # the meter is wired AND enforcing (see ``handlers.balance``), and a placeholder inside
    # the summary would have to be rendered as an empty line in every other deployment —
    # which is how a screen grows a blank paragraph nobody can explain.
    if credits_note is not None:
        text = f"{text}\n\n{credits_note}"
    return Screen(text, confirm_keyboard(language))
