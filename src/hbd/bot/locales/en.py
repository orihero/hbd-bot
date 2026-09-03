"""English catalogue. This file is the REFERENCE key set.

``tests/test_bot/test_i18n.py`` asserts every other catalogue defines exactly these keys,
so a missing translation is a failing test, never a runtime ``KeyError``.

Two things every translator has to preserve. Placeholders: the same test asserts the
placeholder SET of each translated template equals the one here, because a template that
invents ``{limit}`` renders the brace literally to a customer and one that drops ``{name}``
silently loses the only personal word in the message. Markup: every message is sent with
``parse_mode=HTML`` and ``translate`` HTML-escapes each interpolated value, so tags belong
around a placeholder (``<b>{name}</b>``) and never inside the value. Only the tags Telegram
documents are safe — ``b i u s code pre blockquote tg-spoiler a`` — anything else is a 400
at send time, from the send site, long after the typo was made.
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
    "error.delivery_failed": (
        "❌ The song was made, but I could not get it to you here. Send /support and we "
        "will put it in your hands."
    ),
    "error.payment_failed": "The order could not be confirmed. Please try again in a moment.",
    # The three entitlement refusals. Each is rendered with NO parameters by the worker
    # (``runtime.jobs._tell_the_customer_why`` calls ``translate(key, language)`` bare), so
    # none of them may carry a placeholder — the date the out-of-credits customer needs is
    # a separate line, ``credits.next_opens``, which only the bot's read-only gate sends.
    "error.blocked": (
        "This account cannot order songs at the moment. That is a decision a person "
        "made and a person can lift — send /support and tell me about it."
    ),
    "error.credits_exhausted": "You have used every song in your allowance for now.",
    "error.too_many_in_flight": (
        "Your last song is still being made. I will send it here the moment it is ready — "
        "then you can order the next one."
    ),
    # Sent by the inbound throttle in ``hbd.bot.gate``, at most once per window. Says what
    # to do (wait, then send again) rather than naming a number: the window is configurable
    # and an ``error.*`` key may carry no placeholder, so a hardcoded "60 seconds" here
    # would become a lie the day an operator changes ``HBD_INBOUND_WINDOW_S``.
    "error.too_fast": ("That is a lot at once — give me a moment to catch up, then send it again."),
    # -- credits (the rolling allowance) -----------------------------------
    # ``{next_grant_at}`` is a plain calendar date, ``YYYY-MM-DD``, written by
    # ``handlers.confirm``. A date rather than a duration because the allowance window is
    # anchored to the epoch and not to this customer's last song, so "in 30 days" would be
    # a lie for everyone who did not spend their last credit on the day the window opened.
    "credits.next_opens": "Your next song unlocks on {next_grant_at}.",
    # ``/balance`` and the Confirm-screen note. Both are shown only when the meter is wired
    # AND ``Settings.credits_enforced`` is on, because that flag is the difference between a
    # count that can refuse someone and one that cannot: with it off the ledger still runs,
    # but an account that has run out is covered by a grant and renders anyway, so "0 of
    # your 3 songs left" would be a number the product does not honour.
    # ``credits.balance_none`` is the honest answer in every other configuration.
    "credits.balance": (
        "🎵 Songs left: <b>{credits}</b>\n\n"
        "The allowance is {allowance} every {period_days} days and it refills on its "
        "own — nothing to buy, nothing to renew."
    ),
    "credits.balance_none": (
        "🎵 Songs are free while I am getting started. No limit is being applied to you "
        "yet, so there is no number worth showing."
    ),
    # Shown whenever the meter is wired, flag or no flag: the one-song-at-a-time cap is
    # enforced from the day it merged, so a customer whose song is still in the studio would
    # otherwise read a balance that says yes and then meet a Confirm button that says no.
    "credits.balance_in_flight": (
        "🎬 One of your songs is being made right now. The next one can be ordered as soon "
        "as it lands here."
    ),
    "credits.confirm_note": "<i>This one uses a song from your allowance. You have {credits}.</i>",
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 <b>I make one song, for one person, with their name sung the way it is "
        "actually said.</b>\n\n"
        "You pick the style and the voice, and you read the words before anything is "
        "recorded. The song and the lyric sheet arrive right here."
    ),
    "start.choose_ui_language": "First — which language should I talk to you in?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "What are we celebrating?",
    "wizard.genre.prompt": "What should it sound like?",
    "wizard.vocal_gender.prompt": "Whose voice should sing it?",
    "wizard.note.prompt": (
        "Tell me one thing about them — a hobby, an old joke, the name only you use. "
        "I write it into the words.\n\n"
        "A sentence or two is plenty, up to {limit} characters. You can also go on without one."
    ),
    "wizard.note.privacy_line": (
        "<i>I keep the note only long enough to write and deliver the song.</i>"
    ),
    "wizard.note.too_long": "That is a bit long. Please keep it under {limit} characters.",
    "wizard.name.prompt": (
        "Now their name, spelled the way you would write it — the spelling is what decides "
        "how it is sung.\n\n"
        "Type it as text, up to {limit} characters. A voice message will not do."
    ),
    "wizard.name.invalid": "I need a name written in letters. Please type it again.",
    "wizard.name.too_long": "That name is too long. Please keep it under {limit} characters.",
    "wizard.name.too_many_words": (
        "That looks like a sentence. Please type just the name — up to {limit} words."
    ),
    "wizard.name.confirm": (
        "I will sing it as:\n"
        "<blockquote><b>{name}</b></blockquote>\n"
        "The spelling decides the pronunciation, so it is worth a second look. After the "
        "song is recorded I listen back to this word and record it again if it came out "
        "wrong.\n\n"
        "Is that right?"
    ),
    "wizard.name.unresolved": "I could not read that name. Please type it again.",
    "wizard.output_language.prompt": "Which language should {name}'s song be in?",
    "wizard.output_language.prompt_noname": "Which language should the song be in?",
    "wizard.lyrics.writing": "✍️ Writing the words for {name}… it takes up to a minute.",
    "wizard.lyrics.preview": (
        "<b>{title}</b>\n"
        "<blockquote expandable>{lyrics}</blockquote>\n"
        "These are the exact words that will be sung. Nothing is recorded yet — keep them, "
        "ask for a different set, or send me your own as a message."
    ),
    "wizard.lyrics.failed": (
        "❌ The words did not come out this time. Nothing is lost — I can write another set, "
        "or you can send me your own as a message."
    ),
    "wizard.lyrics.too_short": (
        "That is a little short for a song. Please send at least {limit} characters."
    ),
    "wizard.lyrics.too_long": (
        "That is too long for a song. Please keep the lyrics under {limit} characters."
    ),
    "wizard.lyrics.type_only": "Please send the lyrics as text — a voice message will not do.",
    "wizard.lyrics.updated": "Got it — I will sing your words exactly as you wrote them.",
    # -- the bring-your-own path -------------------------------------------
    # Reached from the occasion list, so it is the first thing said about lyrics at all and
    # has to state the bounds up front: the two rejections below are the only other place
    # the customer would learn them, and being told a limit after breaking it is a worse way
    # to find out. Both numbers come from ``lyrics_entry``, never retyped.
    "wizard.lyrics.own_prompt": (
        "✍️ Send me the words you want sung.\n\n"
        "Type them as a message — leave a blank line between verses and I keep that shape. "
        "Anything from {minimum} to {limit} characters.\n\n"
        "They are sung exactly as you write them, so put the name in yourself if you want one."
    ),
    # The preview's twin, for words the customer wrote. It must NOT invite them to "send
    # your own", which is what ``wizard.lyrics.preview`` does — they just did.
    "wizard.lyrics.own_preview": (
        "<b>{title}</b>\n"
        "<blockquote expandable>{lyrics}</blockquote>\n"
        "Your words, exactly as they will be sung. Nothing is recorded yet — keep them, or "
        "send a different set as a message."
    ),
    "wizard.lyrics.too_many": (
        "I have already written {limit} sets of lyrics for this song. "
        "Keep the ones above, or send me your own as a message."
    ),
    # The per-account DAILY ceiling, above the per-draft one. Sent only by the bot's own
    # lyric gate, never by the worker, so it may carry placeholders — and it needs two:
    # the LIMIT (never the count, which keeps rising because a refused write still
    # counts) and the date it lifts, which is what makes the refusal actionable.
    "wizard.lyrics.budget_spent": (
        "I have written the words as many times as one day allows on this account "
        "({limit}) — that is a limit on rewriting, not on songs. "
        "The next one can be written on {resets_at}."
    ),
    "wizard.confirm.summary": (
        "<b>{name}'s song</b>\n"
        "{occasion}\n"
        "{genre}\n"
        "{vocal_gender}\n"
        "🌐 {output_language}\n"
        "✍️ {note}\n\n"
        "The words are set. Next I record it, then check the name by ear.\n\n"
        "Shall I start?"
    ),
    "wizard.confirm.no_note": "—",
    # The own-lyrics summary. Headlined by the SONG, because this path never asked who it
    # is for. Five rows where the named one has six: the note step does not exist here, and
    # rendering "—" for a question nobody was asked would read as an answer.
    "wizard.confirm.summary_noname": (
        "<b>{title}</b>\n"
        "{occasion}\n"
        "{genre}\n"
        "{vocal_gender}\n"
        "🌐 {output_language}\n\n"
        "Your words are set. Next I record them.\n\n"
        "Shall I start?"
    ),
    "wizard.lyrics.untitled": "Your song",
    "wizard.expired": "That session has closed. We can pick it up from the top.",
    "wizard.cancelled": "Cancelled — nothing was made, and nothing was kept.",
    "wizard.cancel_too_late": (
        "{name}'s song is already in the studio, so I cannot stop it now — it will arrive "
        "here shortly. If something is wrong with it, send /support."
    ),
    "wizard.queued": (
        "🎬 Still in the studio. {name}'s song arrives here the moment it is done — "
        "no need to wait on this screen."
    ),
    "wizard.still_in_studio": (
        "🎬 A song of yours is still in the studio and cannot be stopped now — it arrives "
        "here the moment it is done."
    ),
    "wizard.enqueue_failed": (
        "❌ I could not hand this to the studio. Nothing was made and nothing is lost — "
        "we can take it from the top."
    ),
    "wizard.payment_declined": (
        "I could not confirm this order. Nothing was made — we can take it from the top."
    ),
    "wizard.name.type_only": "Please type the name as text — a voice message will not do.",
    "wizard.use_buttons": "Please use the buttons above to answer this one.",
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Back",
    "button.skip": "⏭️ Skip",
    "button.cancel": "✖️ Cancel",
    "button.confirm": "🎬 Record it",
    "button.name_ok": "✅ Yes, that is it",
    "button.retype": "✏️ Type it again",
    "button.lyrics_ok": "✅ Use these lyrics",
    "button.regenerate": "🔄 Write different lyrics",
    "button.own_lyrics": "✍️ My own lyrics",
    "button.start_over": "↩️ Start over",
    "button.make_another": "🎂 Make another",
    "button.report_problem": "⚠️ Something is wrong",
    "button.keep_note": "✅ Keep this note",
    "button.try_again": "🔄 Try again",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "🎂 Birthday",
    "occasion.anniversary": "💍 Anniversary",
    "occasion.custom": "✨ Something else",
    "genre.pop": "🎤 Pop",
    "genre.retro_estrada": "📻 Retro estrada",
    "genre.hip_hop": "🎧 Hip-hop",
    "genre.rock": "🤘 Rock",
    "genre.acoustic_ballad": "🎸 Acoustic ballad",
    "genre.dance_electronic": "🕺 Dance / electronic",
    "genre.uzbek_pop": "🌟 Uzbek pop",
    "genre.uzbek_folk": "🪕 Uzbek folk",
    "genre.shashmaqom": "🎻 Shashmaqom",
    "genre.jazz_lounge": "🎷 Jazz lounge",
    "vocal_gender.female": "👩 Female voice",
    "vocal_gender.male": "👨 Male voice",
    "vocal_gender.duet": "👫 Duet",
    "vocal_gender.any": "🎲 Any voice",
    "language.uz_latn": "Oʻzbekcha (lotin)",
    "language.uz_cyrl": "Ўзбекча (кирилл)",
    "language.ru": "Русский",
    "language.en": "English",
    # -- progress (keys mirror hbd.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": "🎬 {name}'s song is in the studio. You can close Telegram — it lands here.",
    "progress.queued_noname": (
        "🎬 Your song is in the studio. You can close Telegram — it lands here."
    ),
    "progress.validating": "🔎 Checking the details…",
    "progress.moderating": "🛡️ Reviewing the wording…",
    "progress.writing_lyrics": "✍️ Writing the lyrics…",
    "progress.writing_scripts": "📝 Writing the spoken greetings…",
    "progress.authorizing": "🔐 Confirming the order…",
    "progress.composing_song": "🎼 Composing the song…",
    "progress.verifying_name": "🔍 Listening back to how the name was sung…",
    "progress.rendering_greetings": "🎙️ Recording the spoken greetings…",
    "progress.post_processing": "🎚️ Levelling the mix so it sounds right on a phone…",
    "progress.persisting": "💾 Saving the song…",
    "progress.delivering": "📦 Sending it over…",
    "progress.done": "✅ Done — sending it now.",
    "progress.failed": "❌ That one did not come together. You have not lost anything.",
    "progress.timed_out": (
        "❌ This one took too long, so I stopped it. Start over below, or send /support if "
        "it keeps happening."
    ),
    "progress.retrying_suffix": "(attempt {attempt})",
    "progress.degraded_suffix": "(best effort)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 <b>{title}</b>\nWritten and sung for {name}. Sound on.",
    "delivery.greeting_caption": "🎙️ Greeting {index} of {total}",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.lyric_sheet_part": "📄 <b>{title}</b> — {part}/{total}\n\n{body}",
    "delivery.done": (
        "🎉 That is {name}'s song, yours to send.\n\n"
        "Forward the audio straight to them — it plays inside the chat, nothing to "
        "download.\n\n"
        "Order <code>{order_ref}</code> — keep it if you need to reach us.\n\n"
        "Whose turn next?"
    ),
    "delivery.done_degraded": (
        "⚠️ {name}'s song is here, but the run did not go cleanly — what is missing is "
        "written below. I am sorry about that.\n\n"
        "Order <code>{order_ref}</code>. Send /support with it and we will look at this run."
    ),
    "delivery.song_caption_noname": "🎵 <b>{title}</b>\nYour words, sung. Sound on.",
    "delivery.done_noname": (
        "🎉 That is your song, yours to send.\n\n"
        "Forward the audio straight to them — it plays inside the chat, nothing to "
        "download.\n\n"
        "Order <code>{order_ref}</code> — keep it if you need to reach us.\n\n"
        "Another one?"
    ),
    "delivery.done_degraded_noname": (
        "⚠️ Your song is here, but the run did not go cleanly — what is missing is "
        "written below. I am sorry about that.\n\n"
        "Order <code>{order_ref}</code>. Send /support with it and we will look at this run."
    ),
    # -- gaps (appended to the closing message; never a retry instruction) --
    "gap.name_best_effort": (
        "About the name: what you hear is my closest take on how it is said, not a perfect one."
    ),
    "gap.greeting_missing": "One of the spoken greetings did not come out, so it is not in here.",
    # -- commands ----------------------------------------------------------
    "help.text": (
        "🎂 I write and record one song for one person, with their name sung properly.\n\n"
        "🎬 /start — make a song\n"
        "❌ /cancel — stop the one being made\n"
        "📄 /help — this list\n"
        "🎵 /balance — songs left in your allowance\n"
        "🔒 /privacy — what I keep, and for how long\n"
        "✉️ /support — tell me something went wrong\n"
        "🗑️ /forget — delete the song I am holding for you\n\n"
        "Something wrong with a song you received? Send /support with the order number "
        "from its closing message."
    ),
    "privacy.text": (
        "🔒 <b>What I keep, and for how long</b>\n\n"
        "🎙️ The name you gave me: {recipient_identity_days} days\n"
        "✍️ The note you wrote: {brief_text_days} days\n"
        "🎵 The finished song and lyric sheet: {paid_audio_days} days\n"
        "🎬 A song you started but never finished: {abandoned_draft_days} days\n"
        "🧾 The record of songs made and allowance used: no end date\n"
        "✍️ A count of how many times the words were written today: until you write again\n\n"
        "Everything with a date on it is deleted on a schedule, not by hand. The record is "
        "the one exception, on purpose — it is what can still answer a question about your "
        "songs months later — so /forget takes your account number off it and leaves the "
        "count behind, rather than erasing a receipt. The daily writing count keeps your "
        "account number too — it is what stops one person rewriting all day — and it is "
        "replaced the next time you write.\n\n"
        "Send /forget and the song you are working on now goes immediately; anything "
        "already sent to the studio keeps the dates above.\n\n"
        "Send /start whenever you want to make a song."
    ),
    "privacy.forgotten": (
        "✅ Deleted. The song you were working on — the name, the note, the words — is gone "
        "from my side, and there is nothing left to undo.\n\n"
        "Your songs-made record is no longer linked to you either: the count stays, your "
        "account number does not. That also gives up the songs left in this allowance "
        "window — the next ones open when the window turns over.\n\n"
        "A song already sent to the studio is deleted on the schedule /privacy sets out.\n\n"
        "Whenever you want another one, start over below."
    ),
    "support.no_contact": (
        "✉️ Tell me here what went wrong — just reply in this chat.\n\n"
        "Include the order number from the closing message under your song, so I can find "
        "the exact run."
    ),
    "support.text": (
        "✉️ Write to {contact}.\n\n"
        "Include the order number from the closing message under your song — with it we "
        "can find the exact run and see what went wrong."
    ),
}
