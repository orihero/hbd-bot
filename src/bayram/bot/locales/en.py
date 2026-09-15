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
    # -- errors (keys owned by bayram.errors) ---------------------------------
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
    # Sent by the inbound throttle in ``bayram.bot.gate``, at most once per window. Says what
    # to do (wait, then send again) rather than naming a number: the window is configurable
    # and an ``error.*`` key may carry no placeholder, so a hardcoded "60 seconds" here
    # would become a lie the day an operator changes ``BAYRAM_INBOUND_WINDOW_S``.
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
    #
    # None of these may promise that songs are free or that there is nothing to buy any
    # more. ``Settings.free_allowance_credits`` defaults to 0, so the shipped configuration
    # sells every recording, and a customer who read "it refills on its own — nothing to
    # buy" here and then met a price button one screen later would have been misled by this
    # file rather than by the code. The rolling allowance is now something a deployment may
    # switch on, not the shape of the product.
    "credits.balance": (
        "🎵 Songs left: <b>{credits}</b>\n\n"
        "Your allowance is {allowance} every {period_days} days. You can also buy songs "
        "one at a time, or take the starter plan."
    ),
    "credits.balance_none": (
        "🎵 Nothing is being counted against this account right now, so there is no "
        "number worth showing."
    ),
    # The ``/balance`` answer for the deployment that sells every song: there is no
    # allowance to describe, so the number is only worth showing beside what refills it,
    # which is now a purchase and not the calendar.
    "credits.balance_metered": (
        "🎵 Songs left: <b>{credits}</b>\n\n"
        "Each song costs one. Buy one at a time, or take the starter plan."
    ),
    # Shown whenever the meter is wired, flag or no flag: the one-song-at-a-time cap is
    # enforced from the day it merged, so a customer whose song is still in the studio would
    # otherwise read a balance that says yes and then meet a Confirm button that says no.
    "credits.balance_in_flight": (
        "🎬 One of your songs is being made right now. The next one can be ordered as soon "
        "as it lands here."
    ),
    "credits.confirm_note": "<i>This one uses one of your songs. You have {credits}.</i>",
    # -- checkout (the paywall) --------------------------------------------
    # The Confirm screen wears a second face when the account cannot afford a render. The
    # copy has one job: separate the two halves of the product, because the customer has
    # already been given something. The words were written for free and are theirs to keep;
    # only the recording is sold. Every message here therefore names the words first and
    # the price second, and none of them says "you cannot" — the screen is an offer.
    #
    # ``{single_amount}`` and ``{plan_amount}`` arrive already grouped by
    # ``bayram.bot.pricing.format_amount`` ("7 000", "49 000") and carry NO currency word,
    # because the word differs per language and belongs in these templates. The numbers
    # come from ``Settings``, so a price change is a deployment change and never a
    # four-catalogue edit that half-lands.
    "checkout.paywall": (
        "🔒 <b>The words are yours. The recording is what costs.</b>\n\n"
        "💳 One song — <b>{single_amount} UZS</b>\n"
        "🌟 Starter — <b>{plan_amount} UZS</b>: {plan_songs} songs, {plan_days} days\n\n"
        "Nothing is recorded until you choose."
    ),
    # Same screen, but a plan is already running and has no song left on it. Selling a
    # second plan on top would take money for nothing, so only the single song is offered
    # and the plan's own dead end is stated rather than left for the customer to infer.
    # The plan is not part of the catalogue at all (``Settings.is_starter_plan_offered``
    # ships False since 2026-09-14). One product, one price, and NOT a word about a plan:
    # ``paywall_topup`` says "your plan has no songs left on it", which is a sentence about a
    # plan this customer never had, and reusing it here would invent a purchase.
    "checkout.paywall_single": (
        "🔒 <b>The words are yours. The recording is what costs.</b>\n\n"
        "💳 One song — <b>{single_amount} UZS</b>\n\n"
        "Nothing is recorded until you choose."
    ),
    "checkout.paywall_topup": (
        "🔒 <b>The words are yours. The recording is what costs.</b>\n\n"
        "Your plan has no songs left on it, and it brings no more until it ends.\n\n"
        "💳 One more song — <b>{single_amount} UZS</b>"
    ),
    # After a purchase settles. It says the number and then points at the button, because
    # paying does NOT queue the render: the customer presses Record it themselves on the
    # redrawn screen, and a "paid" message that stopped there would read as a dead end.
    "checkout.paid_single": "✅ Paid. You have {credits} song(s) ready — press 🎬 Record it.",
    # ``{ends_on}`` is a plain ``YYYY-MM-DD`` calendar date, like ``credits.next_opens``
    # and for the same reason: the plan is anchored to the day it was bought, so "for 30
    # days" would stop being true the moment the customer reads it again.
    "checkout.paid_plan": "✅ Paid. {songs} songs are yours until {ends_on}.",
    # The same two sentences said COLD, by the worker, when a redirect rail settles a payment
    # minutes or hours after the customer put their phone down
    # (``runtime.payme_jobs.notify_payment_settled``). They are deliberately NOT the two above:
    # that copy points at 🎬 Record it, which is a button on a screen the customer is looking
    # at, and this message arrives when they are looking at something else entirely — so it has
    # to re-open the door itself rather than gesture at one. It names no button LABEL either,
    # because the keyboard under it belongs to the job that sends it and a label named here
    # would be a promise this file cannot keep.
    "checkout.paid_late_single": (
        "✅ <b>Your payment landed.</b>\n\n"
        "You have {credits} song(s) ready — use the buttons below to make one."
    ),
    "checkout.paid_late_plan": (
        "✅ <b>Your payment landed.</b>\n\n"
        "{songs} songs are yours until {ends_on} — use the buttons below to make one."
    ),
    # The THIRD cold sentence, and the one that is not a receipt: the payment landed AND the
    # song is already being made, because the customer had a finished draft waiting when they
    # paid (``runtime.render_resume``). It replaces the two above whenever a render is being
    # started, so it must not promise a button — the progress frame arrives a second later
    # and the message carries no keyboard at all.
    #
    # **No ``{credits}`` placeholder, deliberately.** Telling somebody they have one song
    # ready and spending it in the same breath is exactly the support ticket the comment above
    # warns about; the number would be true for a fraction of a second and wrong by the time
    # they read it.
    "checkout.paid_late_resuming": (
        "✅ <b>Your payment landed.</b>\n\nI'm starting your song now."
    ),
    # The one line the Confirm screen and ``/balance`` add while a plan is running. Italic
    # and short: it is a footnote to a number that is already on the screen.
    "checkout.plan_note": "<i>{songs} songs left on your plan, until {ends_on}.</i>",
    # A payment that has STARTED at a redirect rail, which is a SUCCESS. Until this key
    # existed the bot said ``checkout.failed`` — "nothing was charged" — at the exact moment a
    # customer's payment had begun, because an unpaid receipt was the only shape the handler
    # knew and it read it as a decline.
    #
    # ``{amount}`` arrives grouped from ``bayram.bot.pricing.format_amount`` and carries no
    # currency word, exactly like the paywall above, and it is the number that was quoted to
    # the RAIL rather than one re-read from ``Settings`` — see ``screens.checkout_link_screen``.
    # It promises nothing about the recording: nothing has been granted yet, and the sentence
    # that says a song is ready is ``checkout.paid_late_single``, sent from somewhere else.
    "checkout.pending": (
        "🔗 <b>Almost there.</b>\n\n"
        "Tap the button below to pay <b>{amount} UZS</b>. Nothing is recorded until the "
        "payment lands, and I will tell you here the moment it does."
    ),
    # The two facts about the LINK rather than about the purchase, which is why this is a
    # second key and why it carries NO placeholder: it reads identically for every product and
    # every price, so it must not inherit a placeholder set from the sentence beside it.
    #
    # The twelve hours is the ONE number in this block that is not interpolated from
    # configuration. It is Payme's own transaction window and the shipped default of both
    # ``BAYRAM_PAYME_TRANSACTION_TIMEOUT_MS`` and ``BAYRAM_PAYME_INTENT_TTL_S``; moving either off
    # its default for anything but a certification rehearsal means moving this sentence in all
    # four catalogues with it.
    "checkout.pending_hint": (
        "<i>The link stays good for 12 hours, and only one payment can be open at a time. "
        "You can close the page and come back — nothing is lost.</i>"
    ),
    # Two refusals that are deliberately NOT ``error.``-keyed. That prefix is owned by
    # ``bayram.errors`` and every key under it is reachable from the worker's
    # ``_tell_the_customer_why``, which would put "nothing was charged" into the vocabulary
    # a failed RENDER can answer with — and a render failing after a successful purchase is
    # exactly the case where that sentence is false.
    "checkout.failed": "That did not go through, and nothing was charged. Try again in a moment.",
    "checkout.unavailable": "I cannot take a payment right now. Please try again in a moment.",
    # ``CheckoutPausedError.default_user_message_key``, and the third refusal that is not an
    # ``error.`` one for the same reason as its two neighbours. It is distinct from
    # ``checkout.unavailable`` — that one is a deployment with no rail wired at all, this one is
    # an operator who has deliberately closed a live rail for a few minutes — so it promises
    # the customer a shorter wait and asks them to come back rather than telling them to try
    # something else.
    "checkout.paused": (
        "Payments are paused for a few minutes while we sort something out. Nothing was "
        "charged — please try again shortly."
    ),
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 <b>I make one song, for one person, with their name sung the way it is "
        "actually said.</b>\n\n"
        "You pick the style and the voice, and you read the words before anything is "
        "recorded. The song and the lyric sheet arrive right here."
    ),
    # -- onboarding (the two screens that come before everything else) ------
    # Read by somebody who has not yet decided whether this bot is worth a phone number, so
    # each string says what is wanted, what it buys them, and how to take it back, in that
    # order. ``onboarding.contact.required`` is deliberately NOT keyed under ``error.``:
    # that prefix is owned by ``bayram.errors``, is rendered with no parameters by
    # ``runtime.jobs._tell_the_customer_why``, and ``test_i18n.py`` forbids a placeholder
    # under it — a refusal living there could never carry the one thing that makes this one
    # actionable, which is the instruction to press the button underneath it.
    "onboarding.language.prompt": (
        "🌐 Hello. First — which language should I speak to you in?\n\n"
        "You can change this later in ⚙️ Settings."
    ),
    "onboarding.contact.prompt": (
        "📱 Now leave me your phone number — press the button below.\n\n"
        "I ask once. If your song cannot reach you here, we send it to that number."
    ),
    "onboarding.contact.privacy_line": (
        "<i>I keep the number only to deliver your song, and /forget erases it.</i>"
    ),
    "onboarding.contact.saved": "✅ Thank you, your number is saved. Now we can make a song.",
    "onboarding.contact.required": (
        "📱 Before we make a song I need your number — I ask once. Please press the button below."
    ),
    # Telegram hands over a ``Contact`` for anyone in the sender's address book, so a
    # forwarded card is a well-formed number belonging to somebody who never agreed to
    # anything. The handler compares ``contact.user_id`` with the sender's and says this.
    "onboarding.contact.foreign": (
        "⚠️ That is someone else's number. Please send your own, with the button below."
    ),
    # -- menu (the persistent reply keyboard) -------------------------------
    # These four labels are matched against inbound message TEXT. A reply keyboard is
    # chat-level state that outlives a language change, so somebody who switched to Russian
    # this morning still has yesterday's Uzbek buttons pinned under their composer — which
    # is why ``keyboards.MENU_LABELS`` is computed over all four catalogues rather than over
    # the one the customer is currently speaking. ``menu.prompt`` is a MESSAGE BODY and is
    # deliberately excluded from ``keyboards.MENU_BUTTON_KEYS``: a note at the note step
    # that happens to read "What shall we do?" must not be routed into a dispatcher that has
    # no button to dispatch to.
    "menu.prompt": "What shall we do?",
    "menu.generate": "🎵 Make a song",
    "menu.balance": "🎫 My balance",
    "menu.settings": "⚙️ Settings",
    "menu.help": "❓ Help",
    # -- settings ------------------------------------------------------------
    # ``{language}`` is the only placeholder this whole change adds, and it is interpolated
    # with a ``language.*`` label — the endonym in its own script — never with the language
    # CODE: "Current language: ru" tells somebody who cannot read the code nothing, and the
    # picker two taps below draws that same label, so the screen and the choice agree.
    "settings.title": "⚙️ <b>Settings</b>\n\nCurrent language: {language}",
    "settings.language.prompt": "🌐 Which language should I speak to you in?",
    "settings.language.saved": "✅ Language saved.",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "What are we celebrating?",
    "wizard.genre.prompt": "What should it sound like?",
    "wizard.vocal_gender.prompt": "Whose voice should sing it?",
    "wizard.note.prompt": (
        "Now for the part that matters most!\n"
        "We have the genre and the occasion — let us make the song truly personal 🎯\n\n"
        "💬 Write anything that could inspire it:\n"
        "— What are they like? Any quirks worth singing about?\n"
        "— Any funny stories or favourite catchphrases?\n"
        "— What should this track say: love, mischief, gratitude?\n\n"
        "Write as freely as you like, up to {limit} characters. I ask for the name separately "
        "on the next step — and this one can be skipped."
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
    # The two purchase buttons. The price is interpolated from ``Settings`` rather than
    # baked into four catalogues, because a baked number is one that silently disagrees
    # with ``BAYRAM_SINGLE_SONG_PRICE_MINOR`` the day somebody changes it — and disagrees only
    # in the three languages the person changing it does not read. The emoji still LEADS,
    # so ``test_every_button_label_leads_with_an_emoji`` holds with a digit in the label.
    #
    # Each gets its own keyboard row: rendered with {amount} at "49 000" these run to the
    # low twenties, and ``MAX_ROW_LABEL_CHARS`` is 30 for a whole row.
    "button.pay": "💳 {amount} UZS — 1 song",
    "button.subscribe": "🌟 {amount} UZS — {songs} songs",
    # The label on the product's first ``url=`` button — the one that hands the customer to
    # the payment rail's own page. 🔗 rather than 💳, which is ``button.pay`` one screen
    # earlier and would collide with it under
    # ``test_no_two_buttons_on_one_screen_lead_with_the_same_emoji`` the day the two ever share
    # a screen. It carries no price: the price is in the message above it
    # (``checkout.pending``), and a button that both leaves Telegram and quotes a number is one
    # a customer reads twice.
    "button.pay_now": "🔗 Pay now",
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
    # The settings submenu and the two ways out of a dead end. ``button.share_contact`` is
    # the label on a ``request_contact`` reply button rather than on a callback, because
    # that button is the only thing Telegram offers that proves the number belongs to the
    # sender — which is also why ``onboarding.contact.foreign`` above has to exist.
    "button.set_language": "🌐 Change language",
    "button.show_privacy": "🔒 My data",
    "button.show_support": "✉️ Contact us",
    "button.to_menu": "🏠 Back to menu",
    "button.to_settings": "⬅️ Back to settings",
    "button.share_contact": "📱 Share my number",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "🎂 Birthday",
    "occasion.love": "❤️ Confession",
    "occasion.support": "💪 Encouragement",
    "occasion.prank": "😂 Prank",
    "occasion.holiday": "🎉 Holiday",
    "occasion.wedding": "💒 Wedding",
    "occasion.anniversary": "💍 Anniversary",
    "occasion.kids": "👶 For kids",
    "occasion.no_occasion": "🎶 No occasion",
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
    # A language button is labelled in its own language, so these four are byte-identical
    # in every catalogue and stay that way. The flags are deliberate and so is the repeated
    # 🇺🇿: the product owner chose an emoji on every button with no exceptions and accepted
    # that both Uzbek options carry the same one, because the endonym in its own script is
    # what tells them apart. That acceptance is what forces ``keyboards.LANGUAGE_COLUMNS``
    # to 1 — with the flags on, a two-column row measures 39 characters against a 30 budget,
    # and a truncated endonym would take away the only thing distinguishing the two.
    "language.uz_latn": "🇺🇿 Oʻzbekcha (lotin)",
    "language.uz_cyrl": "🇺🇿 Ўзбекча (кирилл)",
    "language.ru": "🇷🇺 Русский",
    "language.en": "🇬🇧 English",
    # -- progress (keys mirror bayram.pipeline.events.STAGE_MESSAGE_KEYS) ------
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
    # -- watermark ---------------------------------------------------------
    # The two lines that mark everything this bot RENDERS. They are composed onto the audio
    # caption, the greeting captions, the lyric-sheet parts and the lyrics preview in code
    # rather than being folded into those six templates, for two reasons. Adding a
    # ``{handle}`` placeholder to six live keys moves their placeholder SET, which
    # ``test_catalogue_uses_the_same_placeholders_as_the_reference`` compares in both
    # directions across four files at once. And ``delivery._split_for_telegram`` has to stay
    # a pure function of the lyric text, because the part number it produces is a dedup key
    # in the redelivery ledger.
    #
    # ``{handle}`` is ``bayram.watermark.WATERMARK_HANDLE``, one constant that the cover art,
    # the ID3 tags and these captions all read, so the four carriers cannot come to disagree
    # about which bot made the song.
    #
    # NEITHER key ever reaches a ``LyricDraft``. A watermark inside the lyric would be sent
    # to the music vendor and SUNG.
    "watermark.song": "🎧 This song has been generated by {handle}",
    "watermark.invite": "✨ Generate yours at {handle}",
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
    # The Telegram command menu, one key per entry. These are the ONLY strings Telegram
    # renders from the client's own language rather than the interface language this bot
    # asked for, which is why they live here and are published per language_code by
    # ``bayram.bot.app.publish_commands`` instead of being an English-only tuple.
    "command.start": "Start a song for someone",
    "command.cancel": "Stop and start over",
    "command.balance": "Songs you still have",
    "command.help": "How this works",
    "command.privacy": "What is kept, what isn't",
    "command.support": "Write to a person",
    "command.forget": "Erase everything about you",
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
    # The first line of the list has no number beside it on purpose. What the customer told
    # me about THEMSELVES has no clock: ``/forget`` deletes the row, and the absence of the
    # row is the erasure record, so naming a retention period here would promise a sweep
    # that does not exist and that nothing in the code would ever run.
    #
    # The payment line is here because ``plan_purchases`` exists. It holds a telegram_user_id
    # beside an amount, a currency, a provider, a reference and a plan end date — a payment
    # record about a named person — and when checkout shipped this notice still listed only
    # the phone/name/photo, the brief, the assets, the draft, the songs-made record and the
    # daily write count. The erasure was never the gap: ``anonymise_plans`` is called from
    # ``forget_account`` and reported as ``plans_anonymised``. The DISCLOSURE was, and a
    # retention notice that omits a table this bot writes about its customers is the kind of
    # omission that is only ever found from the outside. It carries no placeholder on
    # purpose: ``tests/test_bot/test_i18n.py`` asserts placeholder-set equality across all
    # four catalogues in both directions, and this row has no sweep date to name anyway.
    "privacy.text": (
        "🔒 <b>What I keep, and for how long</b>\n\n"
        "📱 Your phone number, @username, name and profile photo: while your account exists\n"
        "🎙️ The name you gave me: {recipient_identity_days} days\n"
        "✍️ The note you wrote: {brief_text_days} days\n"
        "🎵 The finished song and lyric sheet: {paid_audio_days} days\n"
        "🎬 A song you started but never finished: {abandoned_draft_days} days\n"
        "🧾 The record of songs made and allowance used: no end date\n"
        "💳 What you paid, what it bought and when the plan runs out: no end date\n"
        "✍️ A count of how many times the words were written today: until you write again\n\n"
        "Everything with a date on it is deleted on a schedule, not by hand. The songs-made "
        "record and what you paid are the two exceptions, on purpose — between them they are "
        "what can still answer a question about your songs, or about money that left your "
        "account, months later — so /forget takes your account number off both and leaves "
        "the counts and the amounts behind, rather than erasing a receipt. The daily writing "
        "count keeps your account number too — it is what stops one person rewriting all "
        "day — and it is "
        "replaced the next time you write. What you told me about yourself — the number, "
        "the username, the name, the photo — has no date on it: I keep it while you have "
        "an account here, and /forget erases all of it at once.\n\n"
        "Send /forget and the song you are working on now goes immediately, along with "
        "your number, your name and your photo; anything already sent to the studio keeps "
        "the dates above. I will ask for your language and your number again next time.\n\n"
        "Send /start whenever you want to make a song."
    ),
    # The closing line says /start rather than pointing at a button, because after /forget
    # the account is back at true first contact: the next update — whichever button sent it
    # — is claimed by onboarding and re-asks for the language and the number. "Start over
    # below" would be promising a shortcut that this deletion has just taken away.
    "privacy.forgotten": (
        "✅ Deleted. The song you were working on — the name, the note, the words — is gone "
        "from my side, and there is nothing left to undo.\n\n"
        "Your phone number, your username, your name and your photo are gone too: I no "
        "longer know anything about you, and next time I will ask which language to speak "
        "and for your number again before we can make a song.\n\n"
        "Your songs-made record is no longer linked to you either: the count stays, your "
        "account number does not. That also gives up the songs left in this allowance "
        "window — the next ones open when the window turns over.\n\n"
        "A song already sent to the studio is deleted on the schedule /privacy sets out.\n\n"
        "Whenever you want another one, send /start."
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
    # -- support tickets (the ⚠️ button and /support, which are ONE flow) -------
    # Eight keys, and they are the WHOLE customer-facing surface of the ticket system: the
    # prompt and its re-prompt, the two answers a description can get, the refusal, the
    # failure, the reply that comes back from a person and the answer to a follow-up.
    # Everything a STAFFER reads — the triage card, its buttons,
    # its status badges — is an English literal in ``bayram.bot.support_card`` and is
    # deliberately not here: ``translate`` falls back across all four locales and the
    # catalogues are held in exact key parity, so one staff-facing string in this file would
    # oblige four translations of an internal message, for ever.
    #
    # ``{ref}`` is the ticket's public reference — eight characters of its own id, the same
    # shape as the order reference in the closing message (``bayram.support.public_ref_for``).
    # It is rendered inside ``<code>`` in every one of these, because its whole job is to be
    # read back to us: ``<code>`` is what makes a phone tap copy it rather than select a
    # word of the sentence around it.
    "support.ticket.prompt": (
        "✍️ Tell me what went wrong — reply to this message and describe it in your own "
        "words.\n\n"
        "Write as much as you need to: a person reads every one of these."
    ),
    "support.ticket.filed": (
        "✅ Got it. Your ticket is <code>{ref}</code>, and a person will look at it.\n\n"
        "Keep that number — quote it if you write again about the same thing. The answer "
        "comes back here, in this chat."
    ),
    "support.ticket.already_filed": (
        "📬 I already have that one — ticket <code>{ref}</code>. There is no need to send it "
        "again, and the answer comes back here."
    ),
    # The re-prompt, NOT a refusal. A customer who taps ⚠️ again while still holding a ticket
    # they have not described gets the ticket they already have — the specification's own rule
    # (§1.4) — because a refusal there once locked a blocked account out of support entirely:
    # it could open tickets it was never allowed to describe, and ran out of allowance.
    "support.ticket.still_open": (
        "✍️ You already have ticket <code>{ref}</code> open and I am still waiting to hear "
        "what went wrong.\n\n"
        "Reply to this message and describe it in your own words."
    ),
    # The DAILY ceiling, and the only real refusal here. It names the limit rather than the
    # count, because a refusal that says "you have three" invites a fourth attempt.
    "support.ticket.too_many": (
        "⏳ That is as many tickets as I can open for one account in a day.\n\n"
        "Wait for an answer to the ones you have already sent, then tell me about the next "
        "thing tomorrow."
    ),
    "support.ticket.unavailable": (
        "⚠️ I could not open a ticket just now. Please try again in a moment — and if it "
        "keeps failing, send /support and describe it here in this chat."
    ),
    "support.ticket.reply": (
        "✉️ <b>Support</b> · ticket <code>{ref}</code>\n\n"
        "<blockquote>{body}</blockquote>\n\n"
        "Reply here if there is more to say."
    ),
    # The answer to that invitation, and the reason it is no longer a lie. A follow-up joins
    # the ticket the customer already has; it never mints a second reference, because one
    # conversation split across two work items is two people each holding half the story.
    "support.ticket.follow_up": (
        "📨 Added to ticket <code>{ref}</code>. The people working on it can see it, and the "
        "answer comes back here."
    ),
}
