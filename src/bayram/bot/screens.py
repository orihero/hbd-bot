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

That totality is why ``render_step`` still has an arm for :attr:`WizardStep.UI_LANGUAGE`
even though that step is in neither order any more — the interface language is asked once,
at first contact, by the onboarding screens at the bottom of this module. The arm is not
dead code and must not be deleted as such; ``states.PARKED_ONLY_STEPS`` sets out the two
things it buys (an exhaustive ``match`` mypy can check, and a state name Redis keeps handing
back for fourteen days) and is explicit that neither of them is a customer being sent there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from bayram.bot.callbacks import LanguageSlot, NavAction
from bayram.bot.draft import MAX_NOTE_CHARS, WizardDraft
from bayram.bot.i18n import (
    escape_html,
    genre_label,
    language_label,
    occasion_label,
    translate,
    vocal_gender_label,
)
from bayram.bot.keyboards import (
    checkout_keyboard,
    checkout_link_keyboard,
    confirm_keyboard,
    contact_request_keyboard,
    genre_keyboard,
    language_keyboard,
    lyrics_keyboard,
    main_menu_keyboard,
    name_confirm_keyboard,
    name_prompt_keyboard,
    note_keyboard,
    occasion_keyboard,
    own_lyrics_keyboard,
    settings_keyboard,
    vocal_gender_keyboard,
)
from bayram.bot.lyrics_entry import MAX_LYRIC_CHARS, MIN_LYRIC_CHARS
from bayram.bot.pricing import CheckoutOffer, format_amount
from bayram.bot.states import WizardStep
from bayram.contracts import MAX_RECIPIENT_NAME_CHARS, Language
from bayram.watermark import WATERMARK_HANDLE

__all__ = [
    "Screen",
    "render_step",
    "resolve_step",
    "menu_screen",
    "checkout_link_screen",
    "settings_screen",
    "settings_language_screen",
    "onboarding_language_screen",
    "onboarding_contact_screen",
    "MAX_PREVIEW_LYRIC_CHARS",
]

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
    #: Inline markup rides on the MESSAGE; a reply keyboard is chat-level state. Telegram's
    #: ``editMessageText`` accepts inline markup only, so a screen carrying a reply markup
    #: can only ever be SENT, never edited in place — and an edit that carries one is a 400
    #: at send time, from the send site, which no in-process test double will ever raise.
    #: ``handlers.common._edit_or_send`` enforces that; this comment is why it has to.
    #:
    #: ``ReplyKeyboardRemove`` is deliberately NOT a member. Nothing in this product removes
    #: a keyboard — the menu is persistent by design — and an unused union member is a shape
    #: that invites a removal nobody designed.
    markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None
    #: True when the next thing we expect from the user is typed text, not a button.
    is_text_expected: bool = False


def resolve_step(step: WizardStep, draft: WizardDraft) -> WizardStep:
    """Downgrade ``step`` to one this draft can actually render.

    LYRICS is checked before CONFIRM because it is now the only route to it: a draft that
    has every answer but no approved lyric belongs on the preview screen, not on a summary
    of a song whose words have not been written yet.

    A lyric-less LYRICS is downgraded ONLY on the writer's path. On the bring-your-own path
    an empty lyric is not a hole in the draft, it is the question the screen is asking —
    the step prompts for the customer's words — so downgrading it would bounce them back to
    a step that comes AFTER it in that order, and the pair would loop.

    Every downgrade below must land on a step that exists in this draft's order, or the FSM
    is parked in a state whose screen the path never draws and whose buttons are filtered to
    a different one. That is why the own-lyrics path resolves to LYRICS and never to NAME:
    it has no NAME.
    """
    if draft.is_own_lyrics:
        if step is WizardStep.CONFIRM and not draft.is_complete:
            # LYRICS is second in this order, so it is the earliest thing that can be
            # missing and the only one the customer can act on from a stale Confirm.
            return WizardStep.LYRICS if draft.lyrics is None else WizardStep.OUTPUT_LANGUAGE
        return step
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


def menu_screen(language: Language, *, is_first_time: bool = False) -> Screen:
    """The home screen: one question and the persistent keyboard under it.

    ``is_first_time`` is the whole of the argument about how much to say here.
    ``start.welcome`` is 214-231 characters of product pitch across the four locales, and
    this screen is drawn on every ``/start``, every 🏠 Back to menu and every return from a
    finished flow — a weekly customer would read the same paragraph a dozen times, which is
    how a pitch turns into noise and then into something skipped. So the pitch is drawn
    exactly once, on the first menu after onboarding completes, and every other call site
    gets ``menu.prompt`` alone. One builder rather than two, because two definitions of one
    screen is how the same screen came to be described three different ways.

    The markup is a REPLY keyboard, which is the one thing a caller has to know about this
    screen: it can be sent and never edited into an existing message. See ``Screen.markup``.
    """
    body = translate("menu.prompt", language)
    if is_first_time:
        body = f"{translate('start.welcome', language)}\n\n{body}"
    return Screen(body, main_menu_keyboard(language))


def checkout_link_screen(language: Language, *, url: str, amount_minor: int) -> Screen:
    """A payment that has STARTED at a redirect rail. Not a receipt, and not a failure.

    Drawn by ``handlers.checkout._settle``'s pending branch, which is reached when the rail
    answers ``Ok`` with ``is_paid=False`` and a ``checkout_url``. Until that branch existed the
    same answer was read as a decline and the customer was told "that did not go through, and
    nothing was charged" at the exact moment their payment had successfully begun.

    **The amount is the one that was quoted to the rail, not one re-read from ``Settings``.**
    The caller passes the integer minor units it handed ``PurchaseRequest.amount_minor``, which
    is the same integer the link's ``a=`` parameter carries (``PAYME_INTEGRATION §1``), so the
    number on this screen and the number on the rail's page cannot disagree — a re-read here
    would put a price change made between the tap and the redirect on the wrong side of a
    customer's decision. It arrives in MINOR units and is formatted here, at the edge, which is
    ``bayram.bot.pricing``'s own rule; the currency WORD stays in the four catalogues, where it
    differs per language.

    **Two keys rather than one template**, mirroring :func:`onboarding_contact_screen` and
    :func:`_note_screen`. ``checkout.pending`` carries the price and ``checkout.pending_hint``
    carries the two facts about the LINK — how long it stays payable, and that only one payment
    may be open at a time — which are the same two facts for every product and every price.
    Fusing them would have given the sentence that must be identical in four catalogues a
    placeholder set owned by the sentence beside it, and
    ``test_catalog_files``/``test_i18n``'s placeholder-parity assertions are exactly where a
    half-landed four-file edit would then have shown up.

    There is deliberately no "press 🎬 Record it" here, unlike ``checkout.paid_single``: nothing
    has been granted, the meter has not moved, and the screen must not point at a button that
    would refuse. What happens next is told by ``runtime.payme_jobs.notify_payment_settled``,
    from the worker, whenever the money actually lands — which may be seconds or hours later
    and does not depend on the customer coming back at all.
    """
    return Screen(
        "\n\n".join(
            (
                translate("checkout.pending", language, amount=format_amount(amount_minor)),
                translate("checkout.pending_hint", language),
            )
        ),
        checkout_link_keyboard(language, url),
    )


def settings_screen(language: Language) -> Screen:
    """Settings, headlined by the answer to the only question it can be opened to change.

    ``{language}`` is filled with ``language_label(language, language)`` — the language's own
    endonym, not the current locale's word for it — because that is the string on the button
    the customer will press next, and a screen that names the setting one way and the button
    another makes the reader stop and check whether they are the same thing.

    The substitution is done here rather than through ``translate``'s ``**params`` for one
    unhappy reason, and it is worth writing down so nobody "simplifies" it back: this is the
    only template in any catalogue whose placeholder is spelled ``language``, which is also
    the name of ``translate``'s own second parameter — ``translate(key, lang,
    language=...)`` is a ``TypeError`` at the call, not a rendering bug, and it would take
    the whole settings screen down. Everything else about this line matches what
    ``translate`` would have done: the value is escaped exactly once with the same helper
    ``translate`` uses, and a catalogue that has lost the key degrades to the key itself with
    the substitution a harmless no-op, which is the same failure shape as every other screen.
    """
    return Screen(
        translate("settings.title", language).replace(
            "{language}", escape_html(language_label(language, language))
        ),
        settings_keyboard(language),
    )


def settings_language_screen(language: Language) -> Screen:
    """The language picker inside Settings. No Back, no Cancel — one way out, upwards.

    Cancel would reach ``navigation.handle_cancel``, which is stateless by design: it would
    clear the FSM and answer "Cancelled — nothing was made, and nothing was kept" to somebody
    who came here to change a language, and if they were mid-wizard it would take the draft
    with it. Back has nowhere to go — this screen has no wizard order behind it, and
    ``previous_step`` would answer ``None``. ``TO_SETTINGS`` is the exit, and unlike Cancel
    it says where it goes.

    ``LanguageSlot.SETTINGS`` in the payload is what tells the handler this is not the
    wizard's OUTPUT picker. It cannot be inferred from the FSM state, because this screen
    deliberately sets none.
    """
    return Screen(
        translate("settings.language.prompt", language),
        language_keyboard(
            LanguageSlot.SETTINGS,
            language,
            is_back_enabled=False,
            is_cancel_enabled=False,
            tail_action=NavAction.TO_SETTINGS,
        ),
    )


def onboarding_language_screen(language: Language) -> Screen:
    """The first screen a new customer ever sees. Four buttons and nothing else.

    No Back — there is nothing before it. No Cancel — there is no wizard run to abandon, and
    the button would have told a brand-new customer that something they had not started had
    been cancelled, which is the first impression this product can least afford.

    ``language`` is the language the sentence above the buttons is written in, and it is a
    guess — the configured default — until they answer. The guess is survivable because the
    buttons themselves are always drawn in each language's own name rather than translated
    into the guess: somebody who reads none of the sentence can still find their language.
    """
    return Screen(
        translate("onboarding.language.prompt", language),
        language_keyboard(
            LanguageSlot.UI, language, is_back_enabled=False, is_cancel_enabled=False
        ),
    )


def onboarding_contact_screen(language: Language) -> Screen:
    """The contact request: the prompt, then the retention promise, then the one button.

    Two paragraphs joined here rather than one template, mirroring :func:`_note_screen` —
    the promise about what happens to the number is a separate sentence in a separate voice
    (``<i>``), and it is on this screen rather than buried in ``/privacy`` because this is
    the moment the answer matters to the person deciding.

    ``is_text_expected`` is FALSE, and that is not an oversight. What is expected next is a
    ``Contact``, not text: a typed number is unattributable, and the number exists precisely
    so a song can be delivered when Telegram cannot. A typed answer is refused with
    ``onboarding.contact.required``, not stored — which is also why the keyboard is a reply
    keyboard with ``request_contact=True`` rather than a prompt to type.
    """
    return Screen(
        "\n\n".join(
            (
                translate("onboarding.contact.prompt", language),
                translate("onboarding.contact.privacy_line", language),
            )
        ),
        contact_request_keyboard(language),
    )


def _parked_language_screen(language: Language) -> Screen:
    """The total-match arm for :attr:`WizardStep.UI_LANGUAGE`. Almost certainly unreachable.

    This step left both orders when the interface language moved to onboarding. The enum
    member survives so ``render_step``'s ``match`` stays TOTAL and ``step_for_state``
    resolves a state name Redis keeps handing back for ``WIZARD_STATE_TTL`` — see
    ``states.PARKED_ONLY_STEPS`` — and NOT because a customer is expected here. A draft
    parked in ``Wizard:ui_language`` predates ``user_profiles``, so its owner has no profile
    row and the onboarding catch-all claims their next tap long before ``questions`` can;
    they are re-asked their language by :func:`onboarding_language_screen`, and the parked
    draft — a session id and a default, since UI_LANGUAGE was the first step and nothing
    after it had been answered — is dropped when onboarding ends. Do not "fix" that by
    moving this screen anywhere.

    It renders the same catalogue key the onboarding screen does, because two sentences for
    one question is how a catalogue starts disagreeing with itself. It keeps Cancel because
    a draft behind a screen is a wizard run by this module's own rule — that is the rule
    applied consistently, not evidence that anyone will press the button.
    """
    return Screen(
        translate("onboarding.language.prompt", language),
        language_keyboard(LanguageSlot.UI, language, is_back_enabled=False),
    )


def render_step(
    step: WizardStep,
    draft: WizardDraft,
    *,
    credits_note: str | None = None,
    offer: CheckoutOffer | None = None,
) -> Screen:
    """Render any wizard step. Total over :class:`WizardStep`; never raises.

    ``credits_note`` is used by the Confirm screen alone and defaults to ``None``, which is
    what keeps every other call site — and the Confirm screen itself in a deployment with no
    meter — byte-identical to what it rendered before the entitlement layer existed. It
    arrives as finished text rather than as a balance because a screen is a pure function of
    the draft: reading the meter is I/O, it belongs to ``handlers.balance.show_confirm``, and
    a screen that could await would stop being assertable without an event loop.

    ``offer`` is the same argument one layer on. It is what makes the Confirm screen wear a
    CHECKOUT face when the account cannot afford a render, and it is a value object rather
    than a new :class:`WizardStep` for the reasons
    :class:`~bayram.bot.pricing.CheckoutOffer` sets out — a new step would move
    ``previous_step(CONFIRM)``, both step orders, ``_STATE_BY_STEP``, this ``match`` and
    ``walk_to_confirm``, for a screen that is the same screen. ``None`` — which is what a
    deployment wiring no ``purchases`` and no ``pricing`` produces — renders exactly what
    this function rendered before the checkout shipped.
    """
    language = draft.ui_language
    match step:
        case WizardStep.UI_LANGUAGE:
            return _parked_language_screen(language)
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
            return _confirm_screen(draft, credits_note, offer=offer)


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


def _own_lyrics_prompt_screen(draft: WizardDraft) -> Screen:
    """Ask the customer for their words. The bring-your-own path's only extra screen.

    Reached with no lyric in the draft, which on this path is the normal state rather than a
    broken one — see :func:`resolve_step`. Nothing has been spent to get here and nothing is
    spent leaving: the writer is an offer on the keyboard, not something already paid for.

    Both bounds are stated, because the step's two rejections are the only other place the
    customer would learn them and being told a limit after breaking it is a worse way to
    find out. They are ``lyrics_entry``'s own constants rather than numbers retyped here,
    so the screen and the validator cannot come to disagree.

    It names nobody, and that is not an omission. This is the SECOND screen of the
    own-lyrics path — the wizard has not asked who the song is for and never will — so there
    is no name to put here and the sentence is written for that.
    """
    language = draft.ui_language
    text = translate(
        "wizard.lyrics.own_prompt",
        language,
        minimum=MIN_LYRIC_CHARS,
        limit=MAX_LYRIC_CHARS,
    )
    return Screen(text, own_lyrics_keyboard(language), is_text_expected=True)


def _lyrics_screen(draft: WizardDraft) -> Screen:
    """Show the words before a single cent is spent, and invite all three answers to them.

    This is the screen that answers the objection the rest of the flow cannot: the customer
    is not buying a promise, they are reading the exact words and nothing has been recorded
    yet. The template puts the lyric in a ``<blockquote expandable>`` and says so in the
    line underneath — the quote makes the words visibly theirs and keeps the bot's voice
    outside them, and expandable is what lets a long lyric be read in place rather than
    pushing the three answers off the screen.

    On the bring-your-own path it wears two other faces. With no lyric yet it is the prompt
    that asks for one; with the customer's own words in it, it says they are the customer's
    and offers the writer instead of "a different set" — the preview's copy invites the user
    to send their own words, which is a strange thing to say to somebody reading exactly
    that. Same screen, same buttons, same handler, three honest wordings.

    ``translate`` HTML-escapes every parameter exactly once, so the template owns the
    markup around ``{lyrics}`` and nothing is escaped at this call site.

    **The watermark line is composed here, in code, and never woven into the template.**
    Two reasons, and the second is the load-bearing one:

    * ``wizard.lyrics.preview`` and ``wizard.lyrics.own_preview`` would each gain a
      ``{handle}`` placeholder in four catalogues, under a test that asserts placeholder-set
      equality in both directions — a four-file edit that half-lands is a red suite — and
      composition costs nothing;
    * the mark must sit OUTSIDE the ``<blockquote expandable>``. What is inside that quote
      is the lyric, and the lyric is what gets handed to the music vendor and sung. A
      watermark that drifted inside it would be sung to a real person on their birthday.
      ``bayram.watermark`` is a hard leaf that never touches a ``LyricDraft`` for exactly this
      reason; this call site is the boundary where that stops being an import rule and
      starts being a screen.

    The line is about thirty-five characters against Telegram's 4096 ceiling and a
    3000-character clamp on the lyric itself, so :data:`MAX_PREVIEW_LYRIC_CHARS` is
    unchanged and the preview cannot be pushed over the limit by it.
    """
    language = draft.ui_language
    lyrics = draft.lyrics
    is_own = draft.is_own_lyrics
    if lyrics is None:
        if is_own:
            return _own_lyrics_prompt_screen(draft)
        return render_step(WizardStep.OUTPUT_LANGUAGE, draft)
    body = _elide_for_preview(lyrics.as_plain_text())
    text = translate(
        "wizard.lyrics.own_preview" if is_own else "wizard.lyrics.preview",
        language,
        title=lyrics.title,
        lyrics=body,
    )
    invite = translate("watermark.invite", language, handle=WATERMARK_HANDLE)
    return Screen(
        f"{text}\n\n{invite}",
        lyrics_keyboard(language, is_own_lyrics=is_own),
        is_text_expected=True,
    )


def _paywall_screen(language: Language, offer: CheckoutOffer) -> Screen:
    """The Confirm screen's other face: the words are free, the recording is what costs.

    It REPLACES the summary rather than sitting under it, and that is the decision worth
    stating. A price appended to a five-row table of answers reads as a surcharge on a thing
    the customer thought they already had; a screen of its own reads as what it is — one
    half of the product delivered, the other half offered. The lyric is still one Back press
    away, unedited and un-taken.

    THREE bodies, and the third exists because "no plan button" has two different causes that
    must not share a sentence.

    * ``is_plan_offered`` — both products. The plan is sold and this customer has none.
    * a plan is RUNNING (``plan_ends_on`` is set, spent or not) — ``checkout.paywall_topup``.
      ``checkout.paywall`` would advertise a product the fulfiller refuses to sell twice (see
      ``PurchaseFulfiller.start_plan``), so the top-up wording offers the single song alone and
      says the plan brings nothing more until it ends. The screen and the store therefore agree
      about what can be bought, instead of the screen finding out from an error.
    * the plan is NOT SOLD AT ALL (``Settings.is_starter_plan_offered``, False since
      2026-09-14) — ``checkout.paywall_single``. Falling through to the top-up wording here
      would tell a customer who has never bought a plan that *their* plan has no songs left on
      it, which invents a purchase; and the two-product body would quote a price with no button
      under it. One product, one price, no sentence about plans.

    ``plan_ends_on`` is what separates the last two, and it is the honest discriminator: it is
    a property of the CUSTOMER, while ``is_plan_sold`` is a property of the DEPLOYMENT.

    Nothing is read here and nothing is formatted here: every number arrives finished on
    ``offer.pricing``. See :class:`~bayram.bot.pricing.CheckoutOffer`.
    """
    pricing = offer.pricing
    if offer.is_plan_offered:
        text = translate(
            "checkout.paywall",
            language,
            single_amount=pricing.single_amount,
            plan_amount=pricing.plan_amount,
            plan_songs=pricing.plan_songs,
            plan_days=pricing.plan_days,
        )
    elif offer.plan_ends_on is not None:
        text = translate("checkout.paywall_topup", language, single_amount=pricing.single_amount)
    else:
        text = translate("checkout.paywall_single", language, single_amount=pricing.single_amount)
    return Screen(text, checkout_keyboard(language, offer))


def _confirm_notes(
    language: Language, credits_note: str | None, offer: CheckoutOffer | None
) -> tuple[str, ...]:
    """The lines appended under the Confirm summary, in the order they are read.

    Two of them at most, and both are conditional on something being TRUE rather than on a
    layout: the credits note only when the meter is wired and enforcing, the plan note only
    while a plan is actually running. A screen that always drew both would have to render an
    empty paragraph for every deployment that has neither, which is how a screen grows a
    blank line nobody can explain.

    The plan note is keyed on ``plan_ends_on`` and not on ``plan_songs_left``, because a
    SPENT plan is still a fact the customer needs on this screen: it is why the plan button
    is not being offered, and it is the date after which one will be.
    """
    notes = [] if credits_note is None else [credits_note]
    if offer is not None and offer.plan_ends_on is not None:
        notes.append(
            translate(
                "checkout.plan_note",
                language,
                songs=offer.plan_songs_left,
                ends_on=offer.plan_ends_on,
            )
        )
    return tuple(notes)


def _confirm_screen(
    draft: WizardDraft, credits_note: str | None = None, *, offer: CheckoutOffer | None = None
) -> Screen:
    """The commit screen, headlined by the person it is for.

    It used to open with the bot's word for the product and demote the recipient to one row
    of a five-row table, so the last thing read before the only irreversible press said
    nothing about who any of it was for. ``wizard.confirm.summary`` now leads with
    ``{name}`` and the row is gone with it — the same value cannot be both the headline and
    a line item without reading as a duplicate — which is why every parameter below is
    load-bearing and none of them may be dropped.

    With ``offer`` unset or not paywalled this renders BYTE-IDENTICALLY to what it rendered
    before the checkout shipped, on both the named and the own-lyrics paths. Be precise about
    who that is for, because this paragraph used to claim ``BotDeps.purchases`` and
    ``BotDeps.pricing`` are ``None`` "in every deployment", and both halves of that were
    wrong. ``bayram.main`` is the single ``BotDeps`` construction site and it passes
    ``purchases=container.purchases`` and ``pricing=Pricing.from_settings(settings)``, while
    ``runtime.container`` builds ``SqlPurchaseLedger`` unconditionally — so the paywall is
    LIVE in every shipped configuration, and with ``free_allowance_credits`` at 0 every
    existing customer meets it on their next song. That is the product, not a regression.
    What ``offer=None`` actually buys is every ``BotDeps`` built OUTSIDE ``bayram.main`` — the
    whole bot suite — plus the three runtime ways to reach it, which are enumerated once on
    ``handlers.balance.build_offer``; that sibling docstring states the rule correctly and is
    the one to trust if this ever drifts again. "This deployment does not sell" still has to
    be expressible as a screen that does not mention selling, and here it is.

    That byte-identity is a property of THIS screen only. ``_lyrics_screen`` above appends
    the watermark invite with no gate on ``purchases`` or ``pricing`` at all, so the lyric
    preview changed for everyone the day the watermark shipped — deliberately, since the
    invite is the distribution model and not a checkout artefact.

    A paywalled offer replaces the summary entirely — see :func:`_paywall_screen` — and the
    replacement carries no 🎬 Record it button, which is what makes "no render is queued
    unpaid" a property of the keyboard rather than of a check somebody could reorder.
    """
    language = draft.ui_language
    recipient = draft.recipient
    occasion, genre = draft.occasion, draft.genre
    vocal_gender, output_language = draft.vocal_gender, draft.output_language
    lyrics = draft.lyrics
    if (
        occasion is None
        or genre is None
        or vocal_gender is None
        or output_language is None
        or (recipient is None and not draft.is_own_lyrics)
    ):
        # The downgrade wins over the offer. A draft this screen cannot render is not a
        # screen a price belongs on, and the step it resolves to is never CONFIRM.
        return render_step(resolve_step(WizardStep.CONFIRM, draft), draft)
    if offer is not None and offer.is_paywalled:
        return _paywall_screen(language, offer)
    notes = _confirm_notes(language, credits_note, offer)
    if recipient is None:
        # The own-lyrics summary. It is headlined by the SONG rather than by a person,
        # because there is no person: the wizard never asked. The note row is gone with the
        # note step, so this template carries five values where the other carries six —
        # rendering "—" for a question that was never put would read as an answer.
        text = translate(
            "wizard.confirm.summary_noname",
            language,
            title=translate("wizard.lyrics.untitled", language) if lyrics is None else lyrics.title,
            occasion=occasion_label(occasion, language),
            genre=genre_label(genre, language),
            vocal_gender=vocal_gender_label(vocal_gender, language),
            output_language=language_label(output_language, language),
        )
        return Screen("\n\n".join((text, *notes)), confirm_keyboard(language))
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
    # Appended rather than woven into ``wizard.confirm.summary``: the notes are true only in
    # some deployments (see :func:`_confirm_notes`), and a placeholder inside the summary
    # would have to be rendered as an empty line in every other one — which is how a screen
    # grows a blank paragraph nobody can explain.
    return Screen("\n\n".join((text, *notes)), confirm_keyboard(language))
