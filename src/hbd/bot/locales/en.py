"""English catalogue. This file is the REFERENCE key set.

``tests/test_bot/test_i18n.py`` asserts every other catalogue defines exactly these keys,
so a missing translation is a failing test, never a runtime ``KeyError``.
"""

from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors (keys owned by hbd.errors) ---------------------------------
    "error.generic": "Something went wrong on our side. Please try again in a moment.",
    "error.service_unavailable": "The service is temporarily unavailable. Please try again later.",
    "error.invalid_input": "That does not look right. Please check it and send it again.",
    "error.content_not_allowed": "We cannot make a song from that. Please try different wording.",
    "error.provider_generic": "Our studio hiccuped. Please try again in a moment.",
    "error.provider_slow": "The studio is taking longer than usual. Please try again shortly.",
    "error.provider_busy": "The studio is busy right now. Please try again in a few minutes.",
    "error.name_pronunciation_best_effort": (
        "We could not perfect the pronunciation, so we delivered our best take."
    ),
    "error.delivery_failed": "We could not send your files. Please try again.",
    "error.payment_failed": "Payment did not go through. Nothing was charged.",
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 Welcome! I make a personal celebration kit: one song, three spoken greetings "
        "and a lyric sheet — with the name pronounced properly."
    ),
    "start.choose_ui_language": "First, which language should I talk to you in?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "What are we celebrating?",
    "wizard.genre.prompt": "Pick a musical style.",
    "wizard.vocal_gender.prompt": "Who should sing it?",
    "wizard.note.prompt": (
        "Tell me something personal about them — a hobby, an inside joke, a nickname. "
        "Or press Skip."
    ),
    "wizard.note.too_long": "That is a bit long. Please keep it under {limit} characters.",
    "wizard.name.prompt": (
        "Now type the recipient's name exactly as you would write it. "
        "Please type it — do not send a voice message."
    ),
    "wizard.name.invalid": "I need a name written in letters. Please type it again.",
    "wizard.name.too_long": "That name is too long. Please keep it under {limit} characters.",
    "wizard.name.too_many_words": (
        "That looks like a sentence. Please type just the name — up to {limit} words."
    ),
    "wizard.name.confirm": "I will write and sing it as:\n\n<b>{name}</b>\n\nIs that right?",
    "wizard.name.unresolved": "I could not read that name. Please type it again.",
    "wizard.output_language.prompt": "Which language should the song and greetings be in?",
    "wizard.confirm.summary": (
        "<b>Your kit</b>\n"
        "Name: <b>{name}</b>\n"
        "Occasion: {occasion}\n"
        "Style: {genre}\n"
        "Voice: {vocal_gender}\n"
        "Language: {output_language}\n"
        "Note: {note}\n\n"
        "Shall I start?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "That session expired. Send /start to begin again.",
    "wizard.cancelled": "Cancelled. Send /start whenever you are ready.",
    "wizard.queued": "🎬 Your kit is in the studio. I will send it here when it is ready.",
    "wizard.enqueue_failed": "I could not start the studio. Please try again in a moment.",
    "wizard.payment_declined": "I could not authorise this order. Nothing was charged.",
    "wizard.name.type_only": "Please type the name as text — a voice message will not do.",
    "wizard.use_buttons": "Please use the buttons above, or send /start to begin again.",
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Back",
    "button.skip": "Skip",
    "button.cancel": "Cancel",
    "button.confirm": "✅ Yes, start",
    "button.name_ok": "✅ Correct",
    "button.retype": "✏️ Type it again",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "Birthday",
    "occasion.anniversary": "Anniversary",
    "occasion.custom": "Something else",
    "genre.pop": "Pop",
    "genre.retro_estrada": "Retro estrada",
    "genre.hip_hop": "Hip-hop",
    "genre.rock": "Rock",
    "genre.acoustic_ballad": "Acoustic ballad",
    "genre.dance_electronic": "Dance / electronic",
    "genre.uzbek_pop": "Uzbek pop",
    "genre.uzbek_folk": "Uzbek folk",
    "genre.shashmaqom": "Shashmaqom",
    "genre.jazz_lounge": "Jazz lounge",
    "vocal_gender.female": "Female voice",
    "vocal_gender.male": "Male voice",
    "vocal_gender.duet": "Duet",
    "vocal_gender.any": "Any voice",
    "language.uz_latn": "Oʻzbekcha (lotin)",
    "language.uz_cyrl": "Ўзбекча (кирилл)",
    "language.ru": "Русский",
    "language.en": "English",
    # -- progress (keys mirror hbd.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": "🎬 In the queue…",
    "progress.validating": "🔎 Checking the details…",
    "progress.moderating": "🛡 Reviewing the wording…",
    "progress.writing_lyrics": "✍️ Writing the lyrics…",
    "progress.writing_scripts": "📝 Writing the spoken greetings…",
    "progress.authorizing": "🔐 Confirming the order…",
    "progress.composing_song": "🎼 Composing the song…",
    "progress.verifying_name": "🔍 Checking the pronunciation of the name…",
    "progress.rendering_greetings": "🎙 Recording the spoken greetings…",
    "progress.post_processing": "🎚 Mastering the audio…",
    "progress.persisting": "💾 Saving your kit…",
    "progress.delivering": "📦 Packing everything up…",
    "progress.done": "✅ Ready! Sending it now.",
    "progress.failed": "❌ We could not finish this one. Nothing was charged.",
    "progress.retrying_suffix": "(attempt {attempt})",
    "progress.degraded_suffix": "(best effort)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 {title} — for {name}",
    "delivery.greeting_caption": "🎙 Greeting {index} of {total}",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.done": "🎉 That is your kit for {name}. Send /start to make another.",
}
