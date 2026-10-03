"""Tests for Teachers' Day promo feature (Occasion.TEACHERS_DAY).

Covers:
- Draft attributes and required answers (no recipient name required).
- 30% discount on single songs via `pricing.for_draft(draft)`.
- Flow transitions from menu through genre, vocal gender, note (sender), output language, lyrics, confirm.
- Confirmation screen rendering sender instead of recipient name.
- Back navigation adhering to TEACHERS_DAY_ORDER.
- Prompt generation tailored to Teacher's Day with sender attribution.
"""

from __future__ import annotations

from aiogram import Dispatcher
from aiogram.client.bot import Bot
from aiogram.fsm.context import FSMContext

from bayram.bot.callbacks import (
    GenreCB,
    NavAction,
    NavCB,
    VocalGenderCB,
)
from bayram.bot.deps import BotDeps
from bayram.bot.draft import WizardDraft
from bayram.bot.handlers.common import read_draft
from bayram.bot.pricing import Pricing
from bayram.bot.screens import render_step
from bayram.bot.states import (
    TEACHERS_DAY_ORDER,
    Wizard,
    WizardStep,
    next_step,
    previous_step,
)
from bayram.contracts import (
    Genre,
    Language,
    LyricDraft,
    LyricSection,
    Occasion,
    VoiceGender,
    is_ok,
)
from bayram.pipeline.prompts import OCCASION_BRIEFS, lyrics_user_prompt
from tests.test_bot.conftest import RecordingSession, last_reply_keyboard, reply_buttons
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send


def test_teachers_day_brief_and_prompt() -> None:
    draft = WizardDraft(
        session_id="td-sess-1",
        ui_language=Language.UZ_LATN,
        occasion=Occasion.TEACHERS_DAY,
        genre=Genre.POP,
        vocal_gender=VoiceGender.FEMALE,
        output_language=Language.UZ_LATN,
        note="56-maktab 9-a sinf o'quvchilaridan",
    )
    brief_res = draft.to_brief()
    assert is_ok(brief_res)
    brief = brief_res.value
    assert brief.occasion is Occasion.TEACHERS_DAY
    assert brief.recipient is None
    assert brief.note == "56-maktab 9-a sinf o'quvchilaridan"

    prompt = lyrics_user_prompt(brief)
    assert "O'qituvchi va murabbiylar kuni" in prompt
    assert "56-maktab 9-a sinf o'quvchilaridan" in prompt
    assert OCCASION_BRIEFS[Occasion.TEACHERS_DAY] in prompt


def test_teachers_day_draft_order_and_answers() -> None:
    draft = WizardDraft(
        session_id="td-sess-2",
        ui_language=Language.UZ_LATN,
        occasion=Occasion.TEACHERS_DAY,
    )
    assert draft.is_teachers_day is True
    assert WizardStep.NAME not in draft.required_answers
    assert WizardStep.NAME_CONFIRM not in draft.required_answers

    assert TEACHERS_DAY_ORDER == (
        WizardStep.OCCASION,
        WizardStep.GENRE,
        WizardStep.VOCAL_GENDER,
        WizardStep.NOTE,
        WizardStep.OUTPUT_LANGUAGE,
        WizardStep.LYRICS,
        WizardStep.CONFIRM,
    )
    assert next_step(WizardStep.NOTE, is_teachers_day=True) is WizardStep.OUTPUT_LANGUAGE
    assert previous_step(WizardStep.OUTPUT_LANGUAGE, is_teachers_day=True) is WizardStep.NOTE


def test_teachers_day_pricing_discount() -> None:
    pricing = Pricing(
        single_amount_minor=100_000,
        plan_amount_minor=200_000,
        plan_songs=3,
        plan_days=30,
        is_plan_sold=True,
        currency="UZS",
    )

    normal_draft = WizardDraft(
        session_id="norm-1",
        occasion=Occasion.BIRTHDAY,
    )
    assert pricing.for_draft(normal_draft).single_amount_minor == 100_000

    td_draft = WizardDraft(
        session_id="td-1",
        occasion=Occasion.TEACHERS_DAY,
    )
    td_pricing = pricing.for_draft(td_draft)
    # 30% discount on 100,000 = 70,000
    assert td_pricing.single_amount_minor == 70_000
    assert td_pricing.plan_amount_minor == 200_000


async def test_teachers_day_menu_button_triggers_flow(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    deps: BotDeps,
) -> None:
    # Set teachers_day enabled
    object.__setattr__(deps, "teachers_day_reader", lambda: _async_true())

    # Complete onboarding to get to menu in Uzbek
    await complete_onboarding(dispatcher, bot, language=Language.UZ_LATN)
    buttons = [label for row in reply_buttons(last_reply_keyboard(session)) for label in row]
    assert any("Ustozlar kuni" in b for b in buttons)

    # Click the Teachers' Day menu button
    td_btn = next(b for b in buttons if "Ustozlar kuni" in b)
    await send(dispatcher, bot, td_btn)

    # Should land directly on GENRE step
    assert await state.get_state() == Wizard.genre.state
    draft = await read_draft(state)
    assert draft is not None
    assert draft.occasion is Occasion.TEACHERS_DAY

    # Pick Genre -> Vocal Gender
    await press(dispatcher, bot, GenreCB(value=Genre.POP).pack())
    assert await state.get_state() == Wizard.vocal_gender.state

    # Pick Vocal Gender -> Note
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())
    assert await state.get_state() == Wizard.note.state
    assert "Qoʻshiq kimning nomidan boʻlsin?" in session.last_screen.text

    # Type Sender note -> Should move straight to OUTPUT_LANGUAGE (skipping NAME!)
    await send(dispatcher, bot, "2013-yil bitiruvchilaridan")
    assert await state.get_state() == Wizard.output_language.state
    draft = await read_draft(state)
    assert draft is not None
    assert draft.note == "2013-yil bitiruvchilaridan"
    assert draft.recipient is None

    # Test Back button from OUTPUT_LANGUAGE goes back to NOTE
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    assert await state.get_state() == Wizard.note.state

    # Back from NOTE goes to VOCAL_GENDER
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    assert await state.get_state() == Wizard.vocal_gender.state

    # Move forward again to OUTPUT_LANGUAGE
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())
    assert await state.get_state() == Wizard.note.state
    # Click Skip note -> moves to OUTPUT_LANGUAGE
    await press(dispatcher, bot, NavCB(action=NavAction.SKIP).pack())
    assert await state.get_state() == Wizard.output_language.state


async def test_teachers_day_confirm_screen_summary() -> None:
    draft = WizardDraft(
        session_id="td-sess-3",
        ui_language=Language.UZ_LATN,
        occasion=Occasion.TEACHERS_DAY,
        genre=Genre.POP,
        vocal_gender=VoiceGender.FEMALE,
        output_language=Language.UZ_LATN,
        note="56-maktab 9-a sinf",
        lyrics=LyricDraft(
            title="Aziz ustozim",
            language=Language.UZ_LATN,
            sections=(LyricSection(label="verse", lines=("Aziz ustozim",)),),
        ),
    )
    screen = render_step(WizardStep.CONFIRM, draft)
    assert "Kimdan: 56-maktab 9-a sinf" in screen.text
    # Should not have generic name prompt
    assert "Ism:" not in screen.text


async def _async_true() -> bool:
    return True
