# hbd-bot — Production Remediation Plan
**Owner: product lead · Tree: `feat/live-vendor-integration` @ 2026-08-28 · Scope: copy + conversational UX for paid launch**

---

## 1. Executive verdict

1. **Not launch-ready.** The pipeline is good; the conversation around it is not. Five defects are user-visible and two of them (`confirm.py` double-tap, `deliver_kit` retry) duplicate vendor spend today and become duplicate *charges* the day a real rail replaces `NoopPaymentProvider`.
2. **The single worst moment is the wait.** `state.clear()` at the end of `_authorize_and_submit` means every message a user types while their song renders is answered *"That session expired. Send /start to begin again."* — the bot denies a live order and instructs the exact action that creates a second one.
3. **The product never sells itself.** The two strongest proof points it owns — you read and approve the lyrics before anything is recorded, and the sung name is transcribed back and re-recorded up to 3× at 0.85 similarity — appear nowhere in the copy at the moments of decision (welcome, confirm) and only as an unexplained progress line.
4. **The payoff is a dead end.** `delivery.done` ends on "Send /start to make another": no forward instruction, no button, no share — and forwarding the audio is the *only* distribution this product has.
5. **Top 3 conversion costs, in order:** (a) the silent/hostile generation window; (b) an unproven welcome + a "Your kit / ✅ Yes, start" commit screen; (c) a payoff message that neither distributes the gift nor re-opens the loop.

---

## 2. Findings by severity

### HIGH — block launch

| ID | Surface | Problem | Remedy | Effort |
|---|---|---|---|---|
| NAV-01 | CONFIRM tap | `handle_confirm` answers the callback then awaits `read_draft` + `authorize` before `set_state(Wizard.submitting)`; two taps = two `uuid4()` orders, two ARQ jobs, two kits | Set `Wizard.submitting` as the first await after the state filter; roll back on every failure branch; derive order id from the draft | small |
| TRUST-07 | Cancel during generation | `nav:cancel` is registered with no state filter, so an older screen's Cancel says "Cancelled." while the job runs to completion and delivers | Detect in-flight order in `handle_cancel` and refuse honestly (`wizard.cancel_too_late`); real dequeue is Phase 3 | medium |
| TRUST-08 | Delivery retry | One failed asset → `Err` → ARQ `Retry` → `_replay` re-sends everything that already landed; the replayed `PipelineOutcome` drops `gaps`, so the redelivered close silently omits the pronunciation disclosure | Record per-asset delivery state and skip what landed; persist `gaps` so `_replay` reconstructs them | medium |
| TRUST-11 | NOTE/NAME steps | Bot solicits a third party's name and personal facts; `RetentionPolicy` defines real commitments (recipient 90d, note 30d, audio 365d) stated to no one; no `/privacy`, no deletion path | Add `/privacy` rendering values from `RetentionPolicy`, a one-line notice on the note prompt, `/forget` wired to the existing purge | medium |
| SELL-03 / NAV-02 / TRUST-06 | Generation window (one root cause) | `state.clear()` on submit ⇒ every typed message answers `wizard.expired` while the kit renders; first frame is a bare "🎬 In the queue…"; `wizard.queued` exists in all four catalogues, wired to nothing | Keep `Wizard.submitting`; register a message handler on it that answers `wizard.queued`; name the recipient in the queued frame | small |

### MEDIUM — fix before or immediately after launch

| ID | Surface | Problem | Remedy | Effort |
|---|---|---|---|---|
| TRUST-03 | Failure frame | `user_message_key` is computed then thrown into a job-result dict nobody reads; `error.content_not_allowed` (the one failure a user can fix) is unreachable | Send `translate(outcome.error.user_message_key, …)` to `chat_id` from `_run_pipeline` before returning | small |
| TRUST-04 | Progress | 900 s job timeout cancels the task with no FAILED frame — the bar freezes forever; provider-level retries emit no events | Wrap the job body to emit one terminal frame on cancel (`progress.timed_out`); thread the reporter into provider retry ladders | medium |
| TRUST-12 | Progress | Bar runs backwards 64%→55%; denominator is always 11 with 2 stages skipped by default; "✅ Ready!" is emitted *before* `_send_kit` | Clamp ratio monotonic in the sink; compute denominator from scheduled stages; move DELIVERING/SUCCEEDED after `deliver_kit` returns ok | medium |
| TRUST-05 | Commands | Only `/start` and `/cancel` registered; no `set_my_commands` anywhere; `/help` typed at NOTE is stored verbatim as the note and sung | Register `/help`, `/support`, `/privacy`; call `set_my_commands` at startup; add a command guard to `handle_note` | small |
| TRUST-09 | Closing message | Gap notices appended under 🎉 with no apology and no dedup; a name-verification miss is a footnote on the product's core claim | Lead with `delivery.done_degraded` when gaps exist; dedupe gap keys | small |
| TRUST-10 | Post-delivery | No `reply_markup` anywhere in `delivery.py`; no order reference in any user-facing string | Attach `[Make another][Something's wrong]`; surface a short order ref | medium |
| SELL-01 | Payoff | No forward/share instruction, repeat CTA is a typed command | Rewrite `delivery.done`; add inline keyboard in `_send_closing` | small |
| SELL-02 | Welcome | Spec line, "kit" warehouse noun, zero proof of the two differentiators | Rewrite `start.welcome` | trivial |
| SELL-08 | Failure frame | Dead end with no CTA, and "Nothing was charged" introduces a charge on a product that never showed a price | Drop the charge clause; add a retry path | small |
| NAV-03 | Every screen | Unconfirmed Cancel on all ten screens, same weight as Back, lands in a keyboardless dead end | Confirmation once the draft holds answers; `[Start over]` button in `finish_with` | medium |
| NAV-04 | NOTE / NAME via Back | Neither screen echoes its stored value; Skip silently erases a 600-char note; NAME must be retyped character-for-character | Echo current value; add a keep/continue button; Skip preserves an existing note | small |
| NAV-05 | CONFIRM → edit | No per-field edit (7 Backs to reach genre); re-tapping the *same* output language destroys an approved or hand-pasted lyric | Short-circuit `handle_output_language` when code is unchanged and a lyric exists; add per-field edit row | medium |
| NAV-06 | Stale/expired | `handle_stale_callback` toasts and leaves the dead keyboard on screen; recovery text is ephemeral | Edit the message into expired copy with `[Start over]` | small |
| NAV-07 | All nav callbacks | `NavCB` carries only an action, no step token; `handle_retype` from a post-lyric state leaves a lyric written around the old name in the draft | Stamp the originating step into `NavCB`; clear `lyrics` on retype; strip old markup when `_edit_or_send` falls back | medium |
| NAV-08 | Lyric write wait | Buttonless screen for up to `llm_timeout_s`=45 s labelled "a few seconds"; FSM still at `output_language`, so typing gets "use the buttons above" on a screen with none | Honest copy; keep Cancel; dedicated state + handler; `[Try again]` on failure | small |
| L1 | OCCASION | `Anniversary` → `Yubiley`/`Юбилей` = round-number jubilee, not a generic anniversary; no toʻy entry at all | Relabel to `Yillik`/`Годовщина`; add `Occasion.TOY` (product call) | small |
| L8 | Payment copy | Uzbek states the no-charge guarantee two different ways across three surfaces (`pul yechilmadi` vs `toʻlov olinmadi`) | Pick one sentence per Uzbek script | trivial |
| L12 | Gap notices | `error.provider_generic`'s "Please try again in a moment" is stapled onto a *successful* delivery, undeduplicated | Separate gap keys with no retry clause; dedupe in `_send_closing` | small |

### LOW — polish

| ID | Surface | Problem | Remedy | Effort |
|---|---|---|---|---|
| SELL-04 | NAME_CONFIRM | Highest-proof slot used as a spellcheck | State the stake + one line of mechanism | trivial |
| SELL-05 | Audio caption | Metadata row on the most forwardable message | Bold title, address the recipient | trivial |
| SELL-06 | LYRICS preview | Footer duplicates the button labels; "nothing is recorded yet" unspoken | Reframe as reassurance | trivial |
| SELL-07 | CONFIRM | "Your kit" header, name demoted to a field row, "✅ Yes, start" | Recipient as headline; action-named button | trivial |
| SELL-09 | Progress | The one honest proof point written as jargon | Rewrite `verifying_name` / `post_processing` as physical acts | small |
| SELL-10 | GENRE | "Pick a musical style." above the only locally differentiated catalogue | One line naming Shashmaqom/folk | trivial |
| SELL-11 | OUTPUT_LANGUAGE / writing | Recipient known and never echoed | Pass `name=`; guard the `recipient=None` render path | small |
| SELL-12 | Exits | All three exits end in a typed command | `[Start over]` button (same fix as NAV-03/06) | small |
| NAV-09 | All screens | No step counter; every limit taught by rejection; `limit=` passed to a template with no `{limit}` | Step prefix from `WIZARD_ORDER.index`; fold limits into prompts | medium |
| NAV-10 | CONFIRM w/o lyric | `show_step` sets state from `resolve_step` but renders from `render_step`; latent state/screen divergence | Resolve once, render from the resolved value | trivial |
| NAV-11 | Post-delivery | No history/re-order; CTA points at a command with no menu entry | Covered by TRUST-05 + TRUST-10; history is scope | medium |
| NAV-12 | Nav row | `_nav_row` packs 3 buttons in one row, 38 chars on the default locale, breaking the file's own 2-column rule | Put Skip on its own row | trivial |
| L2 | Uzbek CONFIRM | `Sabab:` = "cause" on the last pre-order screen | `Munosabat:` / `Муносабат:` | trivial |
| L3 | Button widths | `Skip` 4→17 chars in uz_latn, sharing a third of a row with Cancel | Split the row; shorten worst genre labels; add a width test | small |
| L4 | GENRE labels | Two "estrada" buttons outside EN; `Jaz-launj` transliteration; hyphen split on Ретро-эстрада | Free *estrada* for retro only; `Jaz`/`Джаз`; settle the hyphen | trivial |
| L5 | RU failure copy | Bot's first person vanishes in 4 failure strings but survives every success string | Keep 1sg in failure copy | trivial |
| L6 | RU welcome | Sole question-mark parity failure across 89×3 keys, on the first sentence | `На каком языке нам с вами общаться?` | trivial |
| L7 | RU note prompt | "about them" dropped at a step *before* the name is known — reads as asking about the user | Restore `о нём или о ней` | trivial |
| L10 | UZ lyrics preview | Verb deferred behind two conditionals on the longest string in the catalogue | Restructure into three button-mirrored lines | trivial |
| TRUST-01 | Failure frame | "Nothing was charged" is hardcoded and unconditional, including after the AUTHORIZING stage | Gate the clause on `step_index < AUTHORIZING`, or drop it | small |
| TRUST-02 | CONFIRM | Commit with no price shown, then charge-shaped language on failure | Cost line rendered from `deps.amount_minor`, explicit free case | trivial |

---

## 3. Phased work plan

### Phase 1 — must-fix before launch
*Goal: no duplicate orders, no lies about state, a legal footing, and a wait that doesn't insult the user.*

**P1.1 — Kill the double-submit (NAV-01)**
`src/hbd/bot/handlers/confirm.py`
- Move `await state.set_state(Wizard.submitting)` to the first statement of `handle_confirm` after the `Wizard.confirm` filter matches, before `read_draft` and before `_is_authorized`.
- Reset to `Wizard.confirm` on every early return in `_authorize_and_submit` (incomplete brief, decline, progress failure, enqueue failure).
- Replace `uuid4()` in `_build_order` with a deterministic id derived from `(telegram_user_id, draft fingerprint)` so a leaked concurrent tap is idempotent at the submitter (`job_id_for(order.id)` then collides by design).
- Move `await callback.answer()` to after the state flip so the spinner stays up.
- Test: `tests/test_bot/test_confirm_double_tap.py` — two concurrent `handle_confirm` calls ⇒ exactly one `submitter.submit`.

**P1.2 — Survive the generation window (SELL-03 / NAV-02 / TRUST-06)**
- `confirm.py`: delete the trailing `await state.clear()`. Leave the FSM at `Wizard.submitting`, storing `{order_id, progress_message_id}`.
- New `src/hbd/bot/handlers/submitting.py`: message handler bound to `Wizard.submitting` answering `wizard.queued` (the existing dead key — now wired). Register it in `build_router()` **before** `fallback`.
- `src/hbd/bot/progress.py::queued_text` — accept `name` and render `progress.queued` with it; caller `confirm.py::_start_progress` already has the draft.
- Clear the state from the delivery path (`runtime/jobs.py` after `_send_kit`) rather than at submit, or expire it via the existing FSM TTL.

**P1.3 — Honest cancel (TRUST-07)**
`src/hbd/bot/handlers/navigation.py::handle_cancel` — when the current state is `Wizard.submitting`, do **not** clear; answer `wizard.cancel_too_late`. Same guard in `handlers/start.py::handle_start` (warn, then restart).

**P1.4 — Stop duplicate deliveries (TRUST-08)**
`src/hbd/bot/delivery.py` + `src/hbd/pipeline/orchestrator.py::_replay`
- Persist a `delivered_assets` set on the kit row; `deliver_kit` skips what already landed.
- `_replay` must reconstruct `gaps` from storage instead of defaulting to `()`.

**P1.5 — Legal footing (TRUST-11, TRUST-05)**
- `src/hbd/bot/handlers/start.py` — register `/help`, `/privacy`, `/support`, `/forget` (start router matches first from any state).
- `src/hbd/bot/app.py` — `await bot.set_my_commands([...])` at startup so the menu is non-empty.
- `/privacy` renders values read from `src/hbd/db/retention.py::RetentionPolicy` so copy cannot drift from code.
- `questions.py::handle_note` — add `~CommandStart()` / command guard so `/help` is never stored as the note.
- Append `wizard.note.privacy_line` to the note prompt.

**P1.6 — Terminal states tell the truth (TRUST-03, TRUST-04, TRUST-01, SELL-08)**
- `src/hbd/runtime/jobs.py::_run_pipeline` — before returning the failure dict, `bot.send_message(chat_id, translate(outcome.error.user_message_key, order.brief.ui_language))`.
- Wrap the job body in `try/except asyncio.CancelledError` to emit one `progress.timed_out` frame before dying.
- `progress.failed`: drop "Nothing was charged." (the clause is unconditional and decoupled from payment state); keep the reassurance non-monetary.

**New locale keys in Phase 1** (all four catalogues + `tests/test_bot/test_i18n.py` parity):
`wizard.cancel_too_late`, `wizard.note.privacy_line`, `progress.timed_out`, `help.text`, `privacy.text`, `support.text`, `button.start_over`.
**Re-used dead key:** `wizard.queued`.

---

### Phase 2 — conversion lifts

**P2.1 — Payoff and distribution (SELL-01, TRUST-09, TRUST-10, L12)**
`src/hbd/bot/delivery.py::_send_closing`
- Rewrite `delivery.done` (forward instruction + one open loop).
- Attach `InlineKeyboardMarkup` with `button.make_another` (→ new `nav:make_another` running the `handle_start` reset) and `button.report_problem`.
- `dict.fromkeys(gaps)` dedupe; when gaps are non-empty use `delivery.done_degraded` as the lead line and render gap text from new `gap.*` keys that carry **no** retry clause.
- Include a short order reference in the closing line.

**P2.2 — Sell at the two decision points (SELL-02, SELL-04, SELL-06, SELL-07)**
- `locales/*.py`: `start.welcome`, `wizard.name.confirm`, `wizard.lyrics.preview`, `wizard.confirm.summary`, `button.confirm`, `button.name_ok`.
- `src/hbd/bot/screens.py::_confirm_screen` — recipient becomes the headline; drop the redundant `Name:` row.

**P2.3 — No destructive Back, no dead keyboards (NAV-04, NAV-05, NAV-06, NAV-03, SELL-12)**
- `screens.py` NOTE/NAME branches echo `draft.note` / `draft.recipient.display`.
- `keyboards.py::note_keyboard` — Skip preserves an existing note; add a keep/continue button when a value exists.
- `questions.py::handle_output_language` — if `code == draft.output_language and draft.lyrics is not None`, `show_step(LYRICS)` instead of regenerating.
- `handlers/common.py::finish_with` — render with a `[button.start_over]` keyboard.
- `fallback.py::handle_stale_callback` — edit the message into expired copy + `[Start over]`, keep the toast as a secondary cue.

**P2.4 — Honest progress (TRUST-12, SELL-09, NAV-08)**
- `pipeline/events.py::progress_ratio` — denominator from stages actually scheduled.
- `bot/progress.py` — clamp the rendered ratio monotonic per order.
- `orchestrator.py` — move `DELIVERING/SUCCEEDED` after `deliver_kit` returns ok; use `progress.delivering` (currently dead copy) for the send window.
- Rewrite `progress.verifying_name`, `progress.post_processing`, `wizard.lyrics.writing`.
- `handlers/lyrics.py::enter_lyrics_step` — keep Cancel on the writing screen; `[Try again]` on failure instead of a silent bounce.

**New keys in Phase 2:** `button.make_another`, `button.report_problem`, `delivery.done_degraded`, `gap.name_best_effort`, `gap.greeting_missing`, `button.keep_note`, `button.keep_name`, `button.try_again`.

---

### Phase 3 — polish and growth

- **L-series copy pass** (L1 relabel, L2, L4, L5, L6, L7, L8, L10) — pure catalogue edits, one PR, reviewed by a native speaker per locale.
- **`Occasion.TOY`** (L1, product decision): add to `src/hbd/contracts.py`; the keyboard picks it up automatically via `for value in Occasion`. `db/base.py` uses `native_enum=False`, so no migration — but 4 catalogues + i18n test.
- **Layout** (NAV-12, L3): split `_nav_row` at two per row in `keyboards.py`; add a per-locale button-width test.
- **`NavCB` step token** (NAV-07): `nav:back:genre`; stale taps get a "this screen has moved on" toast; `handle_retype` clears `draft.lyrics`; `_edit_or_send` strips old markup before falling back to `answer()`.
- **`show_step` single-resolve** (NAV-10): one line in `handlers/common.py`, plus a test asserting the rendered keyboard's callback namespace matches the FSM state.
- **Step counter + inline limits** (NAV-09): prefix from `WIZARD_ORDER.index(step)`; use the `{limit}` already passed to `wizard.note.prompt`.
- **Name echo** (SELL-11): pass `name=` into `wizard.output_language.prompt` and `wizard.lyrics.writing`, with a `recipient=None` fallback key.
- **Real cancellation** (TRUST-07 full fix): `is_cancelled` flag on the order, checked at each `_staged` boundary before spending.
- **Re-order history** (NAV-11): persist last N briefs, `/mykits`.

---

## 4. Copy rewrite sheet (EN — `src/hbd/bot/locales/en.py`)

Tone: humble, warm, specific, short, no hype. Emoji only where it marks a message type. Every string below must be mirrored into `ru.py`, `uz_latn.py`, `uz_cyrl.py` in the same key order — `tests/test_bot/test_i18n.py` enforces parity.

```python
# ── welcome ───────────────────────────────────────────────────────────
"start.welcome": (
    "🎂 I make one song, for one person, with their name sung the way it is "
    "actually said.\n\n"
    "You pick the style and the voice, and you read the words before anything "
    "is recorded. The song and the lyric sheet arrive right here."
),
"start.choose_ui_language": "First — which language should I talk to you in?",

# ── wizard prompts ────────────────────────────────────────────────────
"wizard.occasion.prompt": "What are we celebrating?",
"wizard.genre.prompt": (
    "What should it sound like?\n"
    "Shashmaqom and Uzbek folk are built on doira and dutar, not a preset."
),
"wizard.vocal_gender.prompt": "Who should sing it?",
"wizard.note.prompt": (
    "Tell me something personal about the person you are celebrating — a hobby, "
    "an inside joke, a nickname. Up to {limit} characters, or press Skip."
),
"wizard.note.privacy_line": (
    "I keep this note for 30 days and the name for 90, then delete both. "
    "/privacy for the rest."
),
"wizard.name.prompt": (
    "Now type their name, exactly as you would write it — up to {limit} characters. "
    "Please type it; a voice message will not do."
),
"wizard.name.confirm": (
    "I will sing it as:\n\n<b>{name}</b>\n\n"
    "The spelling decides the pronunciation, so it is worth a second look. "
    "After the song is recorded I listen back to this word and record it again "
    "if it came out wrong.\n\nIs that right?"
),
"wizard.output_language.prompt": "Which language should {name} hear it in?",

# ── lyrics ────────────────────────────────────────────────────────────
"wizard.lyrics.writing": (
    "✍️ Writing {name}'s words. This usually takes under a minute — "
    "I will show them to you as soon as they are ready."
),
"wizard.lyrics.preview": (
    "<b>{title}</b>\n\n"
    "<pre>{lyrics}</pre>\n\n"
    "These are the exact words that will be sung. Nothing is recorded yet — "
    "keep them, ask for a different set, or send me your own as a message."
),
"wizard.lyrics.failed": (
    "I could not write the words this time. Tap below and I will try again."
),
"wizard.lyrics.updated": "Got it — I will use your words.",

# ── confirm ───────────────────────────────────────────────────────────
"wizard.confirm.summary": (
    "<b>{name}'s song</b>\n"
    "Occasion: {occasion}\n"
    "Style: {genre}\n"
    "Voice: {vocal_gender}\n"
    "Language: {output_language}\n"
    "Note: {note}\n\n"
    "The words are set. Next I record it, then check the name by ear.\n"
    "Shall I start?"
),
"button.confirm": "🎬 Record it",
"button.name_ok": "✅ Yes, that is it",

# ── the wait ──────────────────────────────────────────────────────────
"progress.queued": "🎬 {name}'s song is in the studio. You can close Telegram — it lands here.",
"wizard.queued": (          # now wired to Wizard.submitting, was dead copy
    "🎬 Still in the studio. {name}'s song arrives here the moment it is done — "
    "no need to wait on this screen."
),
"progress.verifying_name": "🔍 Listening back to how the name was sung…",
"progress.post_processing": "🎚 Levelling the mix so it sounds right on a phone…",
"progress.delivering": "📦 Sending it over…",
"progress.done": "✅ Done — sending it now.",

# ── failures ──────────────────────────────────────────────────────────
"progress.failed": "❌ That one did not come together. You have not lost anything.",
"progress.timed_out": (     # NEW
    "❌ This one took too long, so I stopped it. Send /start to try again, "
    "or /support if it keeps happening."
),
"wizard.enqueue_failed": "I could not start the studio. Give me a minute and try again.",
"wizard.cancel_too_late": (  # NEW
    "{name}'s song is already in the studio, so I cannot stop it now — it will "
    "arrive here shortly. If something is wrong with it, send /support."
),

# ── exits ─────────────────────────────────────────────────────────────
"wizard.cancelled": "Cancelled — nothing was made, and nothing was kept.",
"wizard.expired": "That session has closed. We can pick it up from the top.",
"wizard.use_buttons": "Use the buttons above, or start over below.",
"button.start_over": "↩️ Start over",  # NEW

# ── delivery ──────────────────────────────────────────────────────────
"delivery.song_caption": "🎵 <b>{title}</b>\nWritten and sung for {name}. Sound on.",
"delivery.done": (
    "🎉 That is {name}'s song, yours to send.\n\n"
    "Forward the audio straight to them — it plays inside the chat, nothing to "
    "download.\n\n"
    "Order {order_ref} — keep it if you need to reach us.\n\n"
    "Whose turn next?"
),
"delivery.done_degraded": (  # NEW
    "Here is {name}'s song.\n\n"
    "I have to be straight with you: I could not get the name where I wanted it, "
    "and this is my best take. Sorry.\n\n"
    "Order {order_ref} — send /support and I will look at it."
),
"gap.name_best_effort": (    # NEW — no retry clause on a success screen
    "The sung name is our closest take, not a perfect one."
),
"gap.greeting_missing": (    # NEW
    "One spoken greeting did not come out right, so it is not in this kit."
),
"button.make_another": "🎁 Make one for someone else",  # NEW
"button.report_problem": "⚠️ Something's wrong",        # NEW

# ── commands ──────────────────────────────────────────────────────────
"help.text": (               # NEW
    "I make a personal celebration song, with the name sung the way it is "
    "actually said.\n\n"
    "/start — begin a new song\n"
    "/cancel — stop what we are doing\n"
    "/privacy — what I keep, and for how long\n"
    "/support — reach a person\n\n"
    "Something wrong with a song I made? Send /support and tell me what happened."
),
"privacy.text": (            # NEW — values rendered from RetentionPolicy
    "What I keep, and for how long:\n"
    "• The recipient's name — {recipient_identity_days} days\n"
    "• Your note about them — {brief_text_days} days\n"
    "• Your finished song — {paid_audio_days} days\n"
    "• Half-finished orders — {abandoned_draft_days} days\n\n"
    "Then it is deleted automatically. Send /forget to delete everything of "
    "yours right now."
),
"support.text": (            # NEW — owner to fill the channel
    "Tell me what went wrong in one message and I will read it. "
    "If you have an order reference, include it."
),
```

**Unchanged on purpose:** `wizard.confirm.no_note`, `delivery.lyric_sheet`, `delivery.greeting_caption`, all `button.back/skip/cancel`, all enum labels except the L1/L4 relabels, all `error.*` (their surfaces are being re-plumbed, not re-voiced).

**Signature changes callers must make when these land:**
`progress.queued` and `wizard.queued` now take `name=` (`bot/progress.py::queued_text`, `confirm.py::_start_progress`); `wizard.output_language.prompt` and `wizard.lyrics.writing` take `name=` (`screens.py`, `handlers/lyrics.py:70`) and need a `recipient=None` fallback key; `delivery.done` / `delivery.done_degraded` take `order_ref=` (`delivery.py::_send_closing`); `wizard.name.prompt` and `wizard.note.prompt` now actually consume `{limit}` (the argument is already being passed and discarded).

---

## 5. Open questions — owner decision required

1. **Pricing display.** The product is free today (`kit_price_amount_minor = 0`, `NoopPaymentProvider`) and says so nowhere, while "Nothing was charged" appears three times. Three options: (a) say "Free" positively on the confirm screen and delete the charge language everywhere; (b) show a rendered cost line from `deps.amount_minor` with an explicit free case, correct for both builds; (c) stay silent. **(b) is the only one that does not need rewriting the day a rail is wired.** Blocks TRUST-01/TRUST-02 and the final `progress.failed` wording.

2. **Product name.** There is none. Every string says "kit", "your kit", "the studio" — three competing metaphors and one warehouse noun. A single name would replace "kit" in `start.welcome`, `wizard.confirm.summary`, `delivery.done`, and `/help`. Decide before the copy pass, not after.

3. **`Occasion.TOY`.** Adding it makes the largest Uzbek celebration category a first-class button instead of "Boshqa sabab" ("another reason"). Cheap technically (enum + 4 catalogues, no migration), but it changes the lyric prompt surface — does the songwriter prompt need toʻy-specific guidance in `pipeline/prompts.py`, or does CUSTOM's free-text path already cover it?

4. **Share mechanics.** Forwarding the audio is the only distribution that exists (`signed_url` returns `file://`; there are no links). Is a forward instruction in `delivery.done` sufficient, or should the closing message carry a shareable text card the buyer can send with the audio? Also: is a referral loop in scope, or is repeat-purchase the only growth channel for v1?

5. **Free re-roll on a degraded name.** `delivery.done_degraded` currently apologises with nothing to offer. The pipeline supports name re-rolls, but with inpainting disabled a re-roll regenerates the whole track (~$0.30). Do we offer a free re-make on a pronunciation miss, or apologise and route to `/support`?

6. **`/support` destination.** The copy assumes a human reads it. Where does it go — a Telegram operator account, an email, a queue? Without an answer, `/support` is another dead end and should not ship in the P1.5 command set.

---

## Appendix — all 46 verified findings
Each was raised by a lens agent and then independently re-checked against the current tree; unverified claims were dropped (48 raised, 46 survived).

### HIGH
#### NAV-01 — Confirm has no double-tap guard: two taps queue two orders and two kits
- **Surface:** CONFIRM screen — "✅ Yes, start"
- **Anchor:** `src/hbd/bot/handlers/confirm.py:38`
- **Lens:** ux · **Effort:** small

**Problem.** `handle_confirm` calls `callback.answer()` first (removing Telegram's spinner, so the button looks idle again), then does two awaits — `read_draft` and `deps.payment.authorize` — before `state.set_state(Wizard.submitting)` at confirm.py:67. aiogram processes updates concurrently with no FSM lock, so two taps arriving inside that window both pass the `Wizard.confirm` state filter, both build a fresh `uuid4()` order (confirm.py:96-106) and both call `deps.submitter.submit`. The second `_start_progress` edit fails with "message is not modified", falls through to `_post_progress` (confirm.py:144-154), and the user gets two progress messages and two complete kits. Today payment is a no-op, so this ships as duplicate vendor spend (~$0.30/song) and a confusing double delivery; the moment a real rail is wired in it is a double charge on the single most trust-sensitive tap in the product.

**Remedy.** Set `Wizard.submitting` (or take an FSM/Redis lock keyed on the user) as the very first await in `handle_confirm`, before the payment call, and roll it back to `Wizard.confirm` on every failure branch. Additionally derive the order id deterministically from the draft rather than `uuid4()` so a duplicate submit is idempotent, and keep the callback spinner alive by answering only after the state flip.

#### SELL-03 — During generation the bot tells the user their session expired
- **Surface:** Wait window between "Yes, start" and delivery — queued frame + any typed message
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/handlers/confirm.py:93 (state.clear) → /Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/handlers/fallback.py:34-40; first frame at /Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/progress.py:55-57`
- **Lens:** marketing · **Effort:** small

**Problem.** Two failures stack in the highest-anticipation minutes of the product. (1) `state.clear()` fires at submit, so anything the user types while their song is being made falls to `handle_stray_message` with `state is None` and answers "That session expired. Send /start to begin again." — the bot denies the order exists while it is running it. A user who obeys that instruction restarts the wizard and gets a second charge-free duplicate order. (2) The first progress frame is "🎬 In the queue…" — a queue position, not a promise, with no name and no permission to leave. There is no anticipation copy anywhere in a wait that can legitimately run minutes (music_timeout_s 420, 4 attempts).

**Remedy.** Keep the FSM at `Wizard.submitting` instead of clearing at confirm.py:93, and register one message handler on that state that answers the new `wizard.generating` string instead of falling through to `wizard.expired`. Give `queued_text` (progress.py:55-57) the recipient name — the draft is still in scope at confirm.py:130-141 — and repurpose the currently dead `wizard.queued` key (en.py:81) rather than adding another. Nothing else in the bar needs the name.

**Proposed EN copy.**

```
progress.queued: "🎬 {name}'s song is in the studio. I will send it here — you can close Telegram."

wizard.generating (new key): "🎬 Still in the studio. {name}'s song lands here the moment it is done — no need to wait on this screen."
```

#### TRUST-07 — Cancel during generation says "Cancelled" while the job keeps running and still delivers the kit
- **Surface:** During generation
- **Anchor:** `src/hbd/bot/handlers/navigation.py:25-27 (handle_cancel, registered with no state filter)`
- **Lens:** trust · **Effort:** medium

**Problem.** _start_progress strips reply_markup (confirm.py:136) so the live message has no buttons, but nav:cancel is registered globally with no state filter, so Cancel pressed on any older, scrolled-up screen still matches. It runs finish_with("wizard.cancelled") — "Cancelled. Send /start whenever you are ready." — and the queued job is untouched: it continues, completes, and delivers the song and lyric sheet into the chat minutes after the bot said it stopped. /start behaves the same way. There is no real cancel path at all: no dequeue, no abort flag, no cancellation check in the orchestrator. Telling a user an operation is cancelled and then performing it anyway is the version of this bug that generates refund requests under a real payment rail.

**Remedy.** Either implement real cancellation (persist an is_cancelled flag on the order and check it at each _staged boundary before spending money), or — cheaper and honest today — make handle_cancel detect an in-flight order and refuse, telling the user the kit is already being made.

**Proposed EN copy.**

```
wizard.cancel_too_late: "Your kit is already in the studio, so I cannot stop it now — I will send it here shortly. If you do not want it, just ignore it, and send /support if something is wrong with it."
```

#### TRUST-08 — One failed asset re-sends the entire kit as duplicates, and the redelivered copy silently loses the pronunciation apology
- **Surface:** Delivery
- **Anchor:** `src/hbd/errors.py:349 (DeliveryError.default_is_retryable = True)`
- **Lens:** trust · **Effort:** medium

**Problem.** deliver_kit sends song → greetings → lyric sheet → closing, collecting failures, and returns Err if ANY one failed (delivery.py:64-74) — after the others have already been sent successfully. _send_kit then raises arq Retry (jobs.py:137-138). On the retry, _replay short-circuits the pipeline and returns the stored kit, and deliver_kit re-sends everything that already worked. Up to ARQ's max_tries the user receives duplicate songs, duplicate lyric sheets and duplicate "🎉 That is your kit" messages while the one broken asset keeps failing. Worse: _replay constructs PipelineOutcome with gaps defaulting to () (orchestrator.py:480), so the redelivered closing message drops "We could not perfect the pronunciation, so we delivered our best take." The last message the user keeps is the one that quietly omits the disclosure the first attempt made.

**Remedy.** Record per-asset delivery state (a delivered_assets set on the kit row) and have deliver_kit skip what already landed, so a retry sends only the missing piece. Persist gaps with the kit so _replay reconstructs them rather than defaulting to empty.

#### TRUST-11 — The bot solicits a third party's personal details and never says what it stores, for how long, or how to delete it — while a real retention policy exists in code
- **Surface:** NOTE step, NAME step, and the absent /privacy command
- **Anchor:** `src/hbd/db/retention.py:56-67`
- **Lens:** trust · **Effort:** medium

**Problem.** wizard.note.prompt actively asks the user for personal facts about someone who is not present and has not consented — "a hobby, an inside joke, a nickname" — up to 600 characters, and the NAME step captures a real person's name and script. RetentionPolicy defines concrete, deliberate commitments (recipient identity 90 days, brief free text 30 days, paid audio 365, ephemeral 7, abandoned drafts 14) with a __post_init__ guard whose own comment calls a retention period "a legal commitment". None of it is ever stated to the user. There is no /privacy command, no consent line, no deletion path, and no mention of storage in any of the 89 keys in any of the four catalogues. The gap between the care taken in the retention code and the total silence in the copy is the finding.

**Remedy.** Add a /privacy command rendering the actual policy values from RetentionPolicy (so copy cannot drift from code), and add a one-line data notice under wizard.note.prompt. Add a /forget command wired to the existing purge path.

**Proposed EN copy.**

```
wizard.note.privacy_line (append to note prompt): "I keep this note for 30 days and the name for 90, then delete both. /privacy for details."  |  privacy.text: "What I keep, and for how long:\n• The recipient's name — 90 days\n• Your note about them — 30 days\n• Your finished song — 12 months\n• Half-finished orders — 14 days\n\nThen it is deleted automatically. Send /forget to delete everything of yours right now."
```


### MEDIUM
#### L1 — Uzbek has no route to a toʻy — and "Anniversary" is mistranslated as a milestone jubilee in three of four locales
- **Surface:** OCCASION step + confirm summary; Occasion enum
- **Anchor:** `src/hbd/bot/locales/uz_latn.py:111 (also uz_cyrl.py:114, ru.py:105, en.py:97); enum at src/hbd/contracts.py:141-144`
- **Lens:** i18n · **Effort:** small

**Problem.** `occasion.anniversary` is rendered `Yubiley` / `Юбилей` / `Юбилей`. In both Uzbek and Uzbek-Russian usage *yubiley* means specifically a round-number personal milestone (50, 60, 70) — it is not a generic anniversary. A user celebrating a 3rd wedding anniversary reads a label that says "not for me"; the correct generic terms are `Yillik` / `Годовщина`. Worse, the occasion list has only three members and the single largest Uzbek celebration category — **toʻy** (nikoh toʻyi, sunnat toʻyi, beshik toʻyi) — has no entry at all. The only escape is `occasion.custom`, which in Uzbek reads "Boshqa sabab" = "another reason". So the biggest gifting occasion in the target market can only be reached through a button that calls it a *reason*. This is the localisation finding with the largest revenue surface: an entire demand category is invisible in the picker.

**Remedy.** Add a `TOY` member to `Occasion` (src/hbd/contracts.py:141-144) — it appears in the keyboard automatically (keyboards.py:144-149 iterates the enum). Relabel `anniversary` away from *yubiley*: uz `Yillik` / `Йиллик`, ru `Годовщина`. New `toy` labels: uz `Toʻy` / `Тўй`, ru `Свадьба / той`, en `Wedding or toʻy`. Keep *Yubiley* only if you add it as its own fourth occasion — it is a real and distinct Uzbek event, just not this one.

**Proposed EN copy.**

```
"occasion.anniversary": "Anniversary",
"occasion.toy": "Wedding or toʻy",
```

#### L12 — The one line with a sense of humour is flattened to an equipment-fault report in all three locales — and its "try again" CTA gets appended to successful deliveries
- **Surface:** Provider error; also the gap notice appended after delivery.done
- **Anchor:** `src/hbd/bot/locales/en.py:17; ru.py:21; uz_latn.py:20; uz_cyrl.py:23; append site at src/hbd/bot/delivery.py:167`
- **Lens:** i18n · **Effort:** small

**Problem.** EN's "Our studio hiccuped." is the single playful string in 89 keys and one of the few that keeps the possessive "our". All three locales flatten it to an impersonal technical noun phrase and drop the ownership: `В студии сбой.` ("a malfunction in the studio" — a status line, not a voice), `Studiyada nosozlik boʻldi.` / `Студияда носозлик бўлди.` This is specific to that string: `error.generic` keeps the ownership everywhere (`с нашей стороны`, `Bizning tomonda`, `Бизнинг томонда`). Compounding structurally: `deliver_kit` appends each `PipelineGap.user_message_key` after `delivery.done`, undeduplicated, so a *successful* kit can end "🎉 That is your kit for Gulomjon. Send /start to make another.\n\nOur studio hiccuped. Please try again in a moment." — a retry instruction stapled to a success screen, repeated once per failed asset.

**Remedy.** Restore the voice and the possessive without translating "hiccup" literally (no locale has an idiom for it): RU `Наша студия немного сбилась. Попробуйте ещё раз через минуту.`; uz_latn `Studiyamiz biroz chalkashdi. Bir ozdan soʻng qayta urinib koʻring.`; uz_cyrl `Студиямиз бироз чалкашди. Бир оздан сўнг қайта уриниб кўринг.` Then split the copy by surface: gap notices appended to a success message need their own keys with no "try again" clause — a success screen must never issue a retry CTA — and delivery.py:167 should dedupe identical gap messages.

**Proposed EN copy.**

```
"error.provider_generic": "Our studio hiccuped. Please try again in a moment.",
"gap.greeting_missing": "One spoken greeting did not come out right, so it is not in this kit.",
```

#### L8 — "Nothing was charged" appears three times in a product that never charges, and Uzbek says it two different ways
- **Surface:** Payment failure, payment decline, terminal failure frame
- **Anchor:** `src/hbd/bot/locales/uz_latn.py:29 vs :94 and :145 (uz_cyrl.py:32 vs :97 and :148); en.py:24, :83, :131`
- **Lens:** i18n · **Effort:** trivial

**Problem.** Two compounding problems on the most trust-sensitive sentence in the product. (a) The word *payment* appears in the entire 89-key catalogue only as a denial. There is no price, invoice, currency, or positive free claim anywhere (`NoopPaymentProvider` always authorises at amount 0 — src/hbd/payments.py, config.py:209-212). A user who was never asked for money reads `Toʻlov amalga oshmadi. Hech qanday pul yechilmadi.` and reasonably concludes a charge exists and their card failed. The reassurance manufactures the anxiety it answers. (b) Each Uzbek catalogue phrases the guarantee two different ways: `Hech qanday pul yechilmadi` ("no money was withdrawn", :29) versus `Hech qanday toʻlov olinmadi` ("no payment was taken", :94 and :145). RU is consistent across all three (`Деньги не списаны.`). Inconsistency on a money guarantee reads as boilerplate rather than a promise — on the default locale.

**Remedy.** Pick one Uzbek sentence and use it in all three places: `Hech qanday toʻlov olinmadi.` / `Ҳеч қандай тўлов олинмади.` Then, since this build never charges, stop leading with a charge denial in the two failure frames the user actually reaches — `progress.failed` and `wizard.enqueue_failed` — and add the retry CTA that is currently missing entirely on every failure path (the ❌ frame today ends with no button and no instruction; src/hbd/bot/progress.py:61-62).

**Proposed EN copy.**

```
"progress.failed": "❌ We could not finish this one — and nothing was charged. Send /start to try again.",
```

#### NAV-02 — Generation is uncancellable, unstoppable, and tells the user their session expired
- **Surface:** During generation (post-submit, no FSM state)
- **Anchor:** `src/hbd/bot/handlers/confirm.py:93`
- **Lens:** ux · **Effort:** small

**Problem.** `await state.clear()` at confirm.py:93 ends the session the instant the job is queued, and `_start_progress` (confirm.py:130-141) edits the message with `reply_markup=None`, so every button vanishes at the same moment. From then until delivery — a window bounded only by `queue_job_timeout_s = 900.0` — the user has no cancel, no status query, and no way to reach a human. Worse, anything they type falls to `handle_stray_message` (fallback.py:34) with `state is None`, which answers "That session expired. Send /start to begin again." while their kit is actively rendering. The one user who does the natural thing (asks "is it working?") is told their order is gone, and if they follow the instruction and press /start they get a fresh wizard with no acknowledgement that a kit is still coming.

**Remedy.** Keep a lightweight post-submit state (order id + progress message id) instead of clearing, register a message handler for it that answers with the current stage, and attach a single `[Cancel this order]` inline button to the progress message wired to a job-cancel path. At minimum, stop `handle_stray_message` from claiming expiry when a recent order exists for that user — answer with the in-flight copy instead.

**Proposed EN copy.**

```
Your kit is still in the studio — I will send it here the moment it is ready.
```

#### NAV-03 — Cancel is one unconfirmed tap on every screen and lands in a keyboardless dead end
- **Surface:** Every wizard screen — nav row
- **Anchor:** `src/hbd/bot/keyboards.py:84`
- **Lens:** ux · **Effort:** medium

**Problem.** `_nav_row` puts Cancel on all ten screens, same size and same row as Back, with no emoji to mark it as destructive (`button.cancel` = "Cancel"). `handle_cancel` (navigation.py:25) goes straight to `finish_with` → `state.clear()` with no confirmation step, so one mis-tap on the confirm screen — where the row reads `[⬅️ Back][Cancel]` directly under `[✅ Yes, start]` — destroys nine screens of answers, a typed name, a typed note and an approved lyric, irrecoverably. `finish_with` (common.py:101) then *edits the wizard message in place* into a bare sentence with `markup=None`, so the screen and all its context are replaced by one line and there is no button to restart. Recovery requires typing `/start` by hand, and there is no `set_my_commands` call anywhere in `src/`, so `/start` does not appear in Telegram's command menu either.

**Remedy.** Three changes: (1) require a confirmation on Cancel once the draft holds any answer — re-render the current screen with `[Yes, discard][No, keep going]`; (2) attach a `[🔄 Start over]` inline button to the cancelled/expired screen in `finish_with` so the exit is one tap, not a typed command; (3) call `bot.set_my_commands` at startup so /start and /cancel are discoverable. Consider giving Cancel its own row, separated from Back.

**Proposed EN copy.**

```
Discard this kit? Your answers, the name and the lyrics will be lost.
```

#### NAV-04 — Going Back into a typed step traps the user: no forward button, no current value shown, and Skip erases the note
- **Surface:** NOTE and NAME steps reached via Back
- **Anchor:** `src/hbd/bot/keyboards.py:162`
- **Lens:** ux · **Effort:** small

**Problem.** `note_keyboard` offers Back/Skip/Cancel and `name_prompt_keyboard` offers Back/Cancel — neither has a "keep what I already wrote" affordance, and `render_step` (screens.py:117-128) renders the bare prompt without echoing the value already in the draft. So a user who steps Back from NAME to NOTE to re-read their note sees the original blank-state prompt with no note in it, and has exactly two exits: retype the whole 600-character note from memory, or press Skip — which `handle_note_skipped` (questions.py:86) resolves to `note=""`, silently deleting it. The NAME step is worse: the only forward transition is `handle_name_typed` on `F.text`, so once you Back into NAME you must retype the recipient's name character-for-character even if it was correct, and every intermediate Back that crosses NAME_CONFIRM forces this. Back is advertised as free ("every answer already given still in the draft", navigation.py:3-5) but is in practice destructive at two of the ten steps.

**Remedy.** Echo the stored value in both screens and add a forward nav button when a value exists: at NOTE show `[✅ Keep this note][✏️ Replace it][Skip]`, at NAME show `[✅ Keep {name}]` alongside the prompt. Reserve Skip's clearing behaviour for a note that is currently empty, and label it distinctly ("Remove the note") when one exists.

**Proposed EN copy.**

```
Your note right now:

{note}

Type a new one to replace it, or keep it as it is.
```

#### NAV-05 — No single-field edit from Confirm, and backing up past the language step silently destroys the approved lyric
- **Surface:** CONFIRM summary → any earlier answer
- **Anchor:** `src/hbd/bot/screens.py:177`
- **Lens:** ux · **Effort:** medium

**Problem.** `_confirm_screen` renders six labelled facts (name, occasion, style, voice, language, note) and offers exactly one navigation affordance: `[⬅️ Back]`, one step at a time. Fixing a mis-tapped genre from the summary is six presses of Back (CONFIRM→LYRICS→OUTPUT_LANGUAGE→NAME_CONFIRM→NAME→NOTE→VOCAL_GENDER→GENRE), and because of NAV-04 that path forces a full retype of the name and a rewrite-or-erase of the note on the way. The trip is also silently destructive: the only forward transition out of OUTPUT_LANGUAGE is `handle_output_language` (questions.py:111), which calls `enter_lyrics_step` unconditionally — so re-tapping the *same, unchanged* language throws away the lyric the user just approved (or, worse, the lyric they pasted themselves at lyrics.py:106-130) and replaces it with a fresh vendor generation, with no warning and no undo. A user who backs up only to double-check their language choice loses their own words.

**Remedy.** Give the confirm summary a per-field edit row (`[✏️ Style][✏️ Voice][✏️ Language][✏️ Note]`) whose callbacks carry a return-to-CONFIRM token, so one tap edits one field and returns. Separately, short-circuit `handle_output_language` when the tapped code equals `draft.output_language` and a lyric already exists — go straight back to the LYRICS preview instead of regenerating — and confirm before discarding a lyric the user pasted.

**Proposed EN copy.**

```
Changing the song language means writing new lyrics. Keep the ones you approved, or write new ones?
```

#### NAV-06 — Expired and stale sessions dead-end in a disappearing toast while the dead buttons stay on screen
- **Surface:** Any screen after the draft is gone / stale callback
- **Anchor:** `src/hbd/bot/handlers/fallback.py:24`
- **Lens:** ux · **Effort:** small

**Problem.** `handle_stale_callback` answers the callback with `translate("wizard.expired", …)` as a **toast** and touches nothing else. The wizard message keeps its full keyboard, so the screen still looks alive: the user taps a genre, a small alert flashes for a few seconds and vanishes, the screen is unchanged, and tapping again reproduces exactly the same nothing. The recovery instruction ("Send /start to begin again") lives entirely inside that ephemeral toast, on a Telegram surface that is easy to miss on a phone and impossible to scroll back to — and /start is not in the command menu (no `set_my_commands` in `src/`). This is the terminal experience after any storage loss, and `build_dispatcher` (app.py:44) defaults to `MemoryStorage`, so every process restart in a non-Redis deployment puts every mid-wizard user here at once.

**Remedy.** Replace the screen instead of toasting it: have `handle_stale_callback` edit the message into the expired copy with a `[🔄 Start over]` inline button (and answer the callback with a short toast only as a secondary cue). Apply the same treatment to `wizard.use_buttons` when the message is a stray reply to a live step.

**Proposed EN copy.**

```
This session has ended. Tap Start over and I will set your kit up again — it takes about a minute.
```

#### NAV-07 — Old keyboards stay live and act on wherever the session is now, not on the screen they came from
- **Surface:** Every screen — all nav callbacks
- **Anchor:** `src/hbd/bot/handlers/navigation.py:56`
- **Lens:** ux · **Effort:** medium

**Problem.** `nav:back`, `nav:cancel` and `nav:retype` are registered with **no state filter**, and `NavCB` (callbacks.py:51-69) carries only an action — no step, no message id, no draft version. So any older wizard message still in the chat is a fully live control surface: Cancel on a scrolled-up screen destroys the current session, Back jumps from wherever the FSM actually is, and Retype (navigation.py:46) wipes the recipient from a draft that has since reached CONFIRM. Multiple live keyboards are not hypothetical — `_edit_or_send` (common.py:89) falls back to `message.answer()` whenever `edit_text` raises `TelegramBadRequest` (a message older than 48h, a message deleted by the user), which posts a *new* screen while leaving the old one, buttons intact, above it. `handle_retype` from CONFIRM also leaves the now-stale `lyrics` (built around the old name) sitting in the draft.

**Remedy.** Stamp the originating step into `NavCB` (`nav:back:genre`) and have each nav handler no-op with a "this screen has moved on" toast when the token does not match the current state. When `_edit_or_send` has to fall back to sending a new message, strip the old message's markup first (`edit_reply_markup(reply_markup=None)`), so only one keyboard is ever live.

**Proposed EN copy.**

```
That screen has moved on — use the buttons on the latest message.
```

#### NAV-08 — The lyric-writing wait is a buttonless modal of unknown length, mislabelled "a few seconds"
- **Surface:** OUTPUT_LANGUAGE → LYRICS transition
- **Anchor:** `src/hbd/bot/handlers/lyrics.py:70`
- **Lens:** ux · **Effort:** small

**Problem.** `enter_lyrics_step` presents `Screen(translate("wizard.lyrics.writing", …))` with **no markup**, which strips Back and Cancel for the whole duration of a live vendor call, then awaits `deps.content.write_lyrics` with no timeout of its own on this path. The copy promises "this takes a few seconds" against an `llm_timeout_s = 45.0` with `provider_max_attempts` retries behind it — a worst case of minutes on a frozen, uncancellable screen. The FSM is still at `Wizard:output_language` throughout (state is only moved by the `show_step` *after* the call returns), so anything the user types during the wait hits no registered handler and falls to `handle_stray_message` → "Please use the buttons above" — pointing at a screen that has no buttons at all. On failure the recovery is undiscoverable: `say(wizard.lyrics.failed)` plus a silent bounce back to the language picker, where the only way to retry is to re-tap a language button the user has already pressed.

**Remedy.** Keep a Cancel button on the writing screen, move the FSM into a dedicated `Wizard.writing_lyrics` state with a message handler that answers "still writing", and drop the "a few seconds" promise or make it honest. On failure, re-render with an explicit `[🔄 Try again]` button rather than bouncing to the language picker and hoping the user re-taps.

**Proposed EN copy.**

```
✍️ Writing the lyrics — this usually takes under a minute. I will show them to you as soon as they are ready.
```

#### SELL-01 — The payoff message is a shrug: no share instruction, no repeat CTA, no button
- **Surface:** Delivery closing message (last thing the user ever reads)
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:138 (delivery.done); sent at /Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/delivery.py:158-172`
- **Lens:** marketing · **Effort:** small

**Problem.** The entire product ends on "🎉 That is your kit for {name}. Send /start to make another." It never tells the user what to DO with the song — forward it to the person — which is the only distribution this product has (there are no links, no downloads, everything lives in Telegram). And the one re-engagement line is a typed command, not a button: `_send_closing` attaches no `reply_markup` at all. The emotional peak of the product is spent on an admin sentence, and the gift never leaves the buyer's chat.

**Remedy.** Rewrite `delivery.done` to name the recipient, instruct the forward explicitly, and open the loop for the next person. Add an inline keyboard to the closing message in `_send_closing` (delivery.py:158-172) with one button — `button.make_another` → a `nav:` callback that runs the same reset as `handle_start` (start.py:22-30) — so "make another" is one tap, not a typed command. Keep it to one button; two would read as a menu.

**Proposed EN copy.**

```
🎉 That is {name}'s song, yours to send.

Forward the audio straight to them — it plays inside the chat, nothing to download.

Whose turn next?

[🎁 Make one for someone else]
```

#### SELL-02 — The welcome asserts the value and proves none of it
- **Surface:** /start screen (start.welcome + language picker)
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:26-29 (start.welcome)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** "I make a personal celebration kit: one song and a lyric sheet — with the name pronounced properly" is a spec line. "Kit" is warehouse language; nobody wants a kit. The differentiator — the name — is stated as a bare claim with zero mechanism behind it, when the system actually transcribes the sung name back, compares it at 0.85 similarity, and re-records up to 3 times (config.py:161-179). The other unsold reassurance is that the user reads the words BEFORE anything is recorded (the new lyrics step) — the single biggest objection-killer in the flow, invisible at the moment of decision.

**Remedy.** Rewrite `start.welcome` to: one line of what it is (one song, one person), one line of proof (you approve the words first; the sung name is checked by ear), one line of what arrives and where. No 'kit'. Keep the 🎂 as the only emoji so the language picker below stays the visual focus.

**Proposed EN copy.**

```
🎂 I make one song, for one person, with their name sung the way it is actually said.

You pick the style and the voice, and you read the words before anything is recorded.
The song and the lyric sheet arrive here, in this chat.
```

#### SELL-08 — A failure ends in a dead end and plants a charge the user never knew about
- **Surface:** Terminal failure frame during generation
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:131 (progress.failed)`
- **Lens:** marketing · **Effort:** small

**Problem.** "❌ We could not finish this one. Nothing was charged." has two problems. It is a full stop — no button, no retry, no path back (delivery/progress messages carry no markup), so a failed user is simply lost. And "Nothing was charged" is the first and only time money is mentioned to a user who has walked the whole flow without seeing a price: the sentence introduces the idea of a charge at the exact moment trust is lowest. The reassurance belongs on the two payment paths where an authorisation was actually attempted (error.payment_failed en.py:24, wizard.payment_declined en.py:83), not here.

**Remedy.** Drop the charge clause from `progress.failed`, keep the loss reassurance non-monetary, and give the user one way forward. Attach a single retry button to the progress message on FAILED (progress.py:60-65 currently edits text only) — or, minimally, ship the copy below so the CTA exists in text. Do not add a positive 'it is free' claim anywhere; the product must not state a price, a tier, or a trial.

**Proposed EN copy.**

```
❌ That one did not come together. You have not lost anything — I can try again from your answers.

[🔄 Try again]
```

#### TRUST-03 — Every generation failure looks identical; the specific, actionable reason is computed and then thrown away
- **Surface:** Terminal failure frame
- **Anchor:** `src/hbd/runtime/jobs.py:107-112`
- **Lens:** trust · **Effort:** small

**Problem.** When the pipeline fails terminally, _run_pipeline builds a dict containing outcome.error.user_message_key and returns it to ARQ. Nothing sends it. The user's only signal is progress.failed — one sentence, identical for every cause. This means error.content_not_allowed ("We cannot make a song from that. Please try different wording.") is unreachable on the generation path even though it is the ONE failure the user can actually fix themselves: they wrote a note the moderator rejected, and the bot refuses to tell them. Same for error.provider_busy ("try again in a few minutes") and error.provider_slow — all defined, all translated into four languages, all dead. The user is left with a red ❌, no diagnosis, and no next action.

**Remedy.** In generate_and_deliver, before returning the failure dict, send translate(outcome.error.user_message_key, order.brief.ui_language) as a follow-up message to chat_id — the bot handle and chat_id are already in scope at jobs.py:107. Attach a single inline button that re-submits the same order id.

#### TRUST-04 — A 900-second job timeout leaves the progress bar frozen forever with no terminal message, and no stage ever shows an ETA
- **Surface:** Progress message during generation
- **Anchor:** `src/hbd/config.py:226 (queue_job_timeout_s = 900.0)`
- **Lens:** trust · **Effort:** medium

**Problem.** ARQ cancels the task at the job timeout. Cancellation emits no FAILED event, so TelegramProgressSink never renders a terminal frame; the message stays on whatever partial bar it last drew, forever. Compounding it: render_progress (progress.py:76-80) emits only bar + percent + stage name — no ETA, no elapsed time, no "step 4 of 11". Configured worst cases the user gets no signal about are music_timeout_s = 420.0 with provider_max_attempts = 4 and 5s backoff. Provider-level retries inside song rendering, greeting rendering and persistence use _provider_policy below the progress layer and emit no events at all, so "🎼 Composing the song… 45%" can sit unchanged for well over ten minutes with nothing indicating whether the bot is working, retrying, or dead. Silence during a multi-minute paid operation is the single largest abandonment driver in this flow.

**Remedy.** Three fixes: (1) wrap the job body so a CancelledError/timeout emits one final FAILED frame before the task dies; (2) put an expectation in the first frame — a typical-duration line the user can plan around; (3) thread the reporter into the provider retry ladders so a long stage at least ticks "(attempt 2)" rather than freezing.

**Proposed EN copy.**

```
progress.queued: "🎬 In the queue… most kits are ready in 2–5 minutes. I will send it here — you can close Telegram."  |  progress.timed_out: "❌ This one took too long and I stopped it. Nothing was charged. Send /start to try again, or /support if it keeps happening."
```

#### TRUST-05 — There is no /help, /support, /privacy or /terms — and typing /help is silently stored as the personal note that goes into the song
- **Surface:** Command surface (global)
- **Anchor:** `src/hbd/bot/handlers/start.py:40-41`
- **Lens:** trust · **Effort:** small

**Problem.** Only CommandStart() and Command("cancel") are registered, and there is no set_my_commands / BotCommand call anywhere in src/ — so Telegram's command menu is empty and the user has no discoverable affordance beyond the buttons. Any other command falls to whichever text handler owns the current state: at the NOTE step handle_note has no command filter, so "/help" is stripped and written into draft.note verbatim and later fed to the songwriting LLM; at NAME it is rejected as "I need a name written in letters"; at LYRICS it is rejected as too short. A user in trouble types /help and gets either a nonsensical validation error or has their plea for help set to music. For a bot that handles payments and a third party's personal data, having no support path and no terms/privacy command at all is both a trust failure and a compliance exposure.

**Remedy.** Register /help, /support, /privacy and /terms in the start router (which is matched first from any state), and call set_my_commands at startup so all six appear in the Telegram menu. Add a command guard to handle_note so an unrecognised command is never stored as note text.

**Proposed EN copy.**

```
help.text: "I make a personal celebration song with the recipient's name pronounced correctly.\n\n/start — begin a new kit\n/cancel — stop what we are doing\n/support — reach a human\n/privacy — what I store and for how long\n\nSomething wrong with a song I made? Send /support and tell me what happened — I read every one."
```

#### TRUST-06 — Anything the user types while their kit is generating is answered "That session expired" — and the correct copy for this exact moment exists, unused, in all four catalogues
- **Surface:** During generation
- **Anchor:** `src/hbd/bot/handlers/confirm.py:93 (state.clear()) → src/hbd/bot/handlers/fallback.py:38`
- **Lens:** trust · **Effort:** small

**Problem.** On successful submit the FSM is cleared. Every subsequent message therefore reaches handle_stray_message with state is None, which selects wizard.expired: "That session expired. Send /start to begin again." The kit is at that moment actively being generated. A user who types "how long will this take?" is told their session died and instructed to start over — which, if they obey, produces a second order and leaves them watching a progress bar they believe is dead. Meanwhile wizard.queued ("🎬 Your kit is in the studio. I will send it here when it is ready.") is defined in all four catalogues (en.py:81) and referenced by zero lines of code. The right sentence was written, translated, and never wired up.

**Remedy.** Keep the FSM in Wizard.submitting rather than clearing it (or record an in_flight flag), and register a message handler for that state that replies with wizard.queued instead of falling through to the expired branch. This also makes the strings below reachable.

**Proposed EN copy.**

```
wizard.queued (wire it to the submitting state): "🎬 Your kit is in the studio — I will send it right here when it is ready, usually within a few minutes. No need to wait on this screen."
```

#### TRUST-09 — Degraded delivery is announced as a bare line under a celebration emoji, with no apology, no retry offer, and no de-duplication
- **Surface:** Closing message
- **Anchor:** `src/hbd/bot/delivery.py:167`
- **Lens:** trust · **Effort:** small

**Problem.** _send_closing emits "🎉 That is your kit for {name}. Send /start to make another." and then appends translate(gap.user_message_key) for each gap. When the name-verification loop exhausts every candidate orthography, the appended line is "We could not perfect the pronunciation, so we delivered our best take." — a failure on the product's single stated differentiator ("with the name pronounced properly", en.py:26) delivered as a footnote under a party emoji, with no apology, no offer to try again, and no button. The gaps sequence is not de-duplicated, so three greetings failing on the same provider append "Our studio hiccuped. Please try again in a moment." three identical times — and that string tells the user to retry with no mechanism to retry. This is degraded goods handed over as if nothing happened.

**Remedy.** When gaps is non-empty, lead with the apology instead of the celebration, de-duplicate gap keys before rendering, and attach an inline keyboard with a real re-roll action for the name-pronunciation gap specifically (the pipeline already supports re-rolls).

**Proposed EN copy.**

```
delivery.done_degraded: "Here is your kit for {name}.\n\nI have to be straight with you: I could not get the pronunciation of the name where I wanted it, and this is my best take. Sorry. Tap below and I will make it again free, or send /support."  |  button.remake: "🔁 Try the name again"
```

#### TRUST-10 — No way to report a bad result: no button, no order id, nothing the user could quote to support
- **Surface:** Post-delivery
- **Anchor:** `src/hbd/bot/delivery.py:158-172 (_send_closing)`
- **Lens:** trust · **Effort:** medium

**Problem.** Nothing in delivery.py attaches reply_markup to any message. The entire post-delivery surface is one plain-text sentence: "Send /start to make another." There is no rating, no thumbs, no "something wrong with this?", no share, and — critically — no order identifier in any user-facing string, even though the job summary carries order_id (jobs.py:177). A user who receives a song mispronouncing their grandmother's name has no channel to say so and nothing to reference if they find one. For a product whose whole claim is pronunciation accuracy, having zero feedback capture means the one defect that matters is invisible to the operator and unfixable for the customer.

**Remedy.** Attach an inline keyboard to the closing message with "🔁 Make another" and "⚠️ Something's wrong", the latter routing to a short report handler that captures the order id. Include a short order reference in delivery.done so support conversations have an anchor.

**Proposed EN copy.**

```
delivery.done: "🎉 That is your kit for {name}.\n\nOrder {order_ref} — keep this if you need to reach us."  |  button.make_another: "🎂 Make another"  |  button.report_problem: "⚠️ Something's wrong"
```

#### TRUST-12 — The progress bar is not honest: it runs backwards 64% → 55%, counts skipped stages in its denominator, and announces "Ready!" before a single byte is sent
- **Surface:** Progress message
- **Anchor:** `src/hbd/pipeline/events.py:111-114 (progress_ratio)`
- **Lens:** trust · **Effort:** medium

**Problem.** Three separate accuracy defects in the one element the user stares at for minutes. (1) progress_ratio divides by len(STAGE_ORDER) = 11 unconditionally, but with the shipped default greetings_per_kit = 0 two stages (WRITING_SCRIPTS, RENDERING_GREETINGS) never run — the bar can never be honest about how much is left. (2) VERIFYING_NAME (index 6) is emitted from inside the COMPOSING_SONG (index 5) stage wrapper, so its SUCCEEDED at 64% is followed by COMPOSING_SONG's SUCCEEDED at 55%: the user watches the bar go backwards, which reads as a crash. (3) DELIVERING/SUCCEEDED renders "✅ Ready! Sending it now." at orchestrator.py:306, which runs BEFORE _send_kit — so a total send failure leaves "✅ Ready!" permanently on screen with nothing ever arriving. Separately, progress.delivering ("📦 Packing everything up…") is unreachable copy, since DELIVERING is only ever emitted as SUCCEEDED and _headline maps that to progress.done.

**Remedy.** Compute the denominator from the stages actually scheduled for this order; emit VERIFYING_NAME as a sub-status of COMPOSING_SONG rather than as a later stage index, or clamp the rendered ratio to be monotonic in the sink; and move the DELIVERING/SUCCEEDED emission to after deliver_kit returns ok, using progress.delivering for the send window.


### LOW
#### L10 — The Uzbek lyrics-preview instruction buries its verb behind two conditionals, on the longest string in the catalogue
- **Surface:** LYRICS preview screen
- **Anchor:** `src/hbd/bot/locales/uz_latn.py:58-63 (uz_cyrl.py:61-66)`
- **Lens:** i18n · **Effort:** trivial

**Problem.** EN and RU both lead with the action ("Press ✅ to keep these lyrics…" / `Нажмите ✅, чтобы оставить этот текст…`). Both Uzbek locales invert it: `Shu matn qolsin desangiz ✅ ni, boshqasini koʻrmoqchi boʻlsangiz 🔄 ni bosing yoki oʻz matningizni xabar qilib yuboring.` — grammatically correct, but the reader holds two if-clauses across 60+ characters before reaching `bosing`. At 155 characters it is the longest string in the catalogue, and it sits directly beneath a `<pre>` block of up to 3 000 characters of lyrics (screens.py:157-174). This is the highest-agency decision point in the whole flow — approve, regenerate, or paste your own — and on the default locale it is the least scannable sentence in the product.

**Remedy.** Break the run-on into three short lines that mirror the three buttons, in every locale. uz_latn: `✅ — shu matn qolsin.\n🔄 — boshqasini yozaman.\nYoki oʻz matningizni shu yerga yuboring.` uz_cyrl the same in Cyrillic. RU: `✅ — оставить этот текст.\n🔄 — написать другой.\nИли просто пришлите свой текст сообщением.` Keep the emoji identical to the button labels so the mapping is visual, not read.

**Proposed EN copy.**

```
"wizard.lyrics.preview": "<b>{title}</b>\n\n<pre>{lyrics}</pre>\n\n✅ keep these lyrics\n🔄 write a different set\nOr just send me your own lyrics as a message.",
```

#### L2 — The Uzbek confirm screen calls a celebration a "cause" — Sabab is paperwork register on the last screen before ordering
- **Surface:** CONFIRM summary label; OCCASION custom label
- **Anchor:** `src/hbd/bot/locales/uz_latn.py:80 and :112 (uz_cyrl.py:83 and :115)`
- **Lens:** i18n · **Effort:** trivial

**Problem.** `wizard.confirm.summary` labels the occasion row `Sabab:` / `Сабаб:`. *Sabab* means cause or reason — the word on a hospital form or an absence note. On the default UI locale the final pre-order screen literally reads "Sabab: Tugʻilgan kun" ("Cause: Birthday"). Uzbek names the occasion of a celebration *munosabat* (formal) or *bayram*; it is never *sabab*. The same word repeats in `occasion.custom` = "Boshqa sabab" ("another reason"), so the escape hatch reads like a dropdown on a government portal. Russian gets this right (`Повод:`), which makes the default locale the only one that sounds bureaucratic — at the exact moment the user is deciding to commit to an emotional gift.

**Remedy.** uz_latn: `Sabab:` → `Munosabat:`, `Boshqa sabab` → `Boshqa bayram`. uz_cyrl: `Сабаб:` → `Муносабат:`, `Бошқа сабаб` → `Бошқа байрам`. Leave RU `Повод:` / `Другой повод` alone. Tone target for both Uzbek scripts on this screen: celebratory-neutral, the register of a wedding invitation card, never of a form field.

**Proposed EN copy.**

```
"occasion.custom": "Another celebration",
```

#### L3 — Skip and Cancel truncate to ellipsis on the default locale — the nav row is 38 characters across three buttons in one row
- **Surface:** Every screen's nav row; NOTE step in particular; GENRE grid
- **Anchor:** `src/hbd/bot/keyboards.py:84-97 (_nav_row builds one row); labels at uz_latn.py:101-103, ru.py:111-112`
- **Lens:** i18n · **Effort:** small

**Problem.** `_nav_row` puts Back / Skip / Cancel in a single `builder.row(...)`. Measured on the default locale (uz_latn): `⬅️ Orqaga` (9) + `Oʻtkazib yuborish` (17) + `Bekor qilish` (12) = 38 characters across three buttons in one row. Telegram fits roughly 10–12 characters per button in a 3-wide row on a 360 dp phone, so both Skip and Cancel ellipsize — and Skip is the *only* way past the optional note step, so the affordance that unblocks the flow is the one that gets cut. The genre grid is worse: 2-column, RU row 3 is `Акустическая баллада` (20) + `Танцевальная / электронная` (26) = 46 characters; uz_latn row 4 is `Oʻzbek estradasi` (16) + `Oʻzbek xalq qoʻshigʻi` (21) = 37. The comment at keyboards.py:55-57 asserts two columns solves this ("Uzbek labels are long"); the measurement says it does not, because the labels themselves run 2–4× the English source (`Skip` 4 → 17).

**Remedy.** Two changes. (1) Structural: move SKIP out of the nav row onto its own full-width row in `note_keyboard`, leaving nav at Back/Cancel (2-wide) — this is the fix that does not require butchering the language. (2) Copy: shorten the worst offenders — ru `genre.dance_electronic` → `Танцевальная`, `genre.acoustic_ballad` → `Баллада`; uz `genre.uzbek_folk` → `Xalq qoʻshigʻi` / `Халқ қўшиғи`. Then add a test asserting no inline label exceeds ~16 chars in a 2-wide row and ~12 in a 3-wide row, per locale, so this cannot regress.

**Proposed EN copy.**

```
"genre.dance_electronic": "Dance",
"genre.acoustic_ballad": "Ballad",
```

#### L4 — The genre picker shows two adjacent "estrada" buttons and one meaningless transliteration to a local user
- **Surface:** GENRE step (10 buttons, 2 columns)
- **Anchor:** `src/hbd/bot/locales/ru.py:108 and :113; uz_latn.py:114 and :119; uz_cyrl.py:117 and :122; jazz at uz_latn.py:122`
- **Lens:** i18n · **Effort:** trivial

**Problem.** EN keeps a clean contrast: "Retro estrada" vs "Uzbek pop". All three localised catalogues render *both* with *estrada* — `Ретро-эстрада` / `Узбекская эстрада`, `Retro estrada` / `Oʻzbek estradasi`, `Ретро эстрада` / `Ўзбек эстрадаси` — so the grid asks the user to distinguish two options that share their head noun and sit one row apart. EN already proves the vocabulary exists to keep them apart. Separately, `genre.jazz_lounge` = `Jaz-launj` / `Жаз-лаунж` is a phonetic transliteration of an English marketing phrase; it names nothing an Uzbek listener recognises and scans as a typo. `Raqs / elektron` is two adjectives joined by a slash, not a genre name anyone would say aloud. Also a punctuation split on the same word across three files: `Ретро-эстрада` (ru, hyphen), `Ретро эстрада` (uz_cyrl, space), `Retro estrada` (uz_latn, space).

**Remedy.** Free *estrada* to mean only the retro register it means regionally: `genre.uzbek_pop` → uz `Oʻzbek pop` / `Ўзбек поп`, ru `Узбекский поп`. Drop the lounge qualifier: `genre.jazz_lounge` → `Jaz` / `Джаз` / `Джаз`. Name the dance genre as a noun: uz `Raqs musiqasi` / `Рақс мусиқаси`, ru `Танцевальная`. Settle the hyphen — use `Ретро-эстрада` in both Cyrillic catalogues to match ru.py:108.

**Proposed EN copy.**

```
"genre.jazz_lounge": "Jazz",
```

#### L5 — The Russian bot's first person disappears in exactly the five strings where it fails
- **Surface:** Name error, lyrics failure, enqueue failure, payment decline, first screen
- **Anchor:** `src/hbd/bot/locales/ru.py:34, :53, :62, :87, :88`
- **Lens:** i18n · **Effort:** trivial

**Problem.** EN and both Uzbek locales say "I could not…" (`oʻqiy olmadim`, `yoza olmadim`, `tushira olmadim`, `tasdiqlay olmadim`). Russian replaces the agent with impersonal constructions in five keys: `Не удалось разобрать это имя`, `Не получилось написать текст песни`, `Не удалось запустить студию`, `Не удалось подтвердить заказ`, `язык общения со мной`. This is not a blanket RU style choice — RU keeps first person everywhere things go *well*: `Я собираю` (:30), `Мне нужно имя буквами` (:47), `Я напишу и спою его так` (:52), `возьму ваш текст` (:72), `Я пришлю его сюда` (:86), `Отправляю` (:138). Net effect: the Russian bot has a warm personality that vanishes precisely when it has just let the user down, which is where personality does the most work. Impersonal Russian in a failure reads as institutional deflection — "it did not succeed" rather than "I could not".

**Remedy.** RU tone target: keep вы throughout (already uniform, verified — zero ты leakage), but keep the bot in first person singular in failure copy and let it own the failure, the way it owns the successes. Concretely: :53 → `Не смог разобрать это имя. Напишите его ещё раз, пожалуйста.`; :62 → `Не смог написать текст. Дайте мне ещё минуту и попробуем снова.`; :87 → `Не смог запустить студию. Попробуйте ещё раз через минуту.`; :88 → `Не смог подтвердить заказ. Деньги не списаны.` EN needs no change — it is the model here.

#### L6 — Russian turns the first question after the welcome into a command — the only question-mark parity failure in 356 strings
- **Surface:** Welcome / UI_LANGUAGE screen
- **Anchor:** `src/hbd/bot/locales/ru.py:34`
- **Lens:** i18n · **Effort:** trivial

**Problem.** `Сначала выберите язык общения со мной.` — a declarative imperative where EN and both Uzbek locales ask a question in first person (`which language should I talk to you in?`, `men siz bilan qaysi tilda gaplashay?`). `welcome_screen` (src/hbd/bot/screens.py:88-94) concatenates `start.welcome` and this key into one message, so the very first thing a Russian user reads is: warm first-person sell (`Привет! Я собираю персональный поздравительный набор…`) immediately followed by a form instruction. Tone whiplash inside a single message, on the only screen that has to earn the next tap. Verified as the sole question-mark divergence across all 89 keys × 3 target locales.

**Remedy.** ru.py:34 → `На каком языке нам с вами общаться?` — restores the question, keeps вы, and keeps the inclusive "we" that the rest of the Russian catalogue uses well (`Что празднуем?`, `Начинаем?`). Do not translate EN's "First," literally; `Сначала` reads procedural in Russian where EN's "First," reads conversational.

#### L7 — The Russian note prompt drops "about them" — it reads as asking the user to disclose something about themselves
- **Surface:** NOTE step (step 4 of 10)
- **Anchor:** `src/hbd/bot/locales/ru.py:39-41`
- **Lens:** i18n · **Effort:** trivial

**Problem.** EN anchors the request on the recipient: "Tell me something personal **about them**". Uzbek keeps the referent and fronts it (`Ular haqida shaxsiy biror narsani ayting`). RU is `Расскажите что-нибудь личное: увлечение, шутку, прозвище.` — no *про него/неё* anywhere. Because the note step comes **before** the name step in WIZARD_ORDER (src/hbd/bot/states.py:57-68), the Russian user has not yet mentioned any other person at this point in the conversation, so the only available referent is themselves. In a gifting flow that is both confusing and mildly invasive, and it degrades the note quality that feeds the lyric prompt. RU also swaps EN's em-dash for a colon, flattening three warm examples into a list. Note the EN source has a milder version of the same problem: "them" is a dangling referent at a step where nobody has been named.

**Remedy.** ru.py:39-41 → `Расскажите что-нибудь личное о нём или о ней — увлечение, шутку, прозвище. Или нажмите «Пропустить».` Restore the em-dash so the examples read as a warm aside. Uzbek is already correct; keep the fronted `Ular haqida`. Also fix the EN referent (below). Separately: `screens.py:119` passes `limit=MAX_NOTE_CHARS` to a template that contains no `{limit}` in any of the four catalogues — either use it or drop the argument.

**Proposed EN copy.**

```
"wizard.note.prompt": "Tell me something personal about the person you're celebrating — a hobby, an inside joke, a nickname. Or press Skip.",
```

#### NAV-09 — Ten screens with no progress indicator, and every input limit is revealed only by rejecting the user
- **Surface:** All wizard screens
- **Anchor:** `src/hbd/bot/screens.py:101`
- **Lens:** ux · **Effort:** medium

**Problem.** `render_step` emits a prompt and a keyboard and nothing else — no "Step 4 of 10", no breadcrumb, no sense of how much is left. `WIZARD_ORDER` (states.py:57) already indexes every step, so the position is available for free and simply is not used. The user commits to a ten-screen flow with a live vendor call in the middle without ever being told how long it is, which is exactly the shape that produces mid-funnel abandonment. Compounding it, every constraint is taught by failure: `wizard.note.prompt` never states the 600-character cap (screens.py:119 passes `limit=MAX_NOTE_CHARS` to a template that contains no `{limit}` in any of the four catalogues, so the argument is silently discarded), and `wizard.name.prompt` states neither the 40-character nor the 4-word limit — the user only learns them from `wizard.name.too_long` / `wizard.name.too_many_words` after being knocked back.

**Remedy.** Prefix every screen with a step counter derived from `WIZARD_ORDER.index(step)` (skipping it on the welcome screen), and fold the real limits into the prompts. Either use the `{limit}` parameter already being passed to `wizard.note.prompt` or stop passing it.

**Proposed EN copy.**

```
Step 5 of 10 · Tell me something personal about them — a hobby, an inside joke, a nickname. Up to {limit} characters, or press Skip.
```

#### NAV-10 — A reachable state/screen mismatch makes every button on the visible screen answer "expired"
- **Surface:** CONFIRM requested on a draft with no lyric
- **Anchor:** `src/hbd/bot/screens.py:67`
- **Lens:** ux · **Effort:** trivial

**Problem.** `show_step` (common.py:54) sets the FSM state from `resolve_step` but renders from `render_step`, and the two disagree in one case. For a draft with all five required answers but `lyrics is None`, `resolve_step(CONFIRM, draft)` returns `LYRICS` (screens.py:83) so the FSM is set to `Wizard:lyrics`; `_lyrics_screen` then sees `lyrics is None` and returns `render_step(OUTPUT_LANGUAGE, …)` (screens.py:165-166). The user is now looking at the output-language picker while the FSM sits at `Wizard:lyrics`. Every language button emits `lang:out:*`, which is registered only against `Wizard.output_language` (questions.py:144-148), so it matches nothing and drops to the fallback toast — a screen where four of the six buttons do nothing but flash "That session expired". Only Back escapes, and nothing on screen suggests it. Reachable from confirm.py:48/64/71/82 and from `handle_lyrics_ok` (lyrics.py:86) if storage drops the lyric between preview and tap.

**Remedy.** Make `show_step` render the step it actually set, not the step it was asked for — resolve once, then set state and render from the same resolved value, and remove the second-guessing downgrade inside `_lyrics_screen` / `_name_confirm_screen` / `_confirm_screen` so screen and state cannot diverge. A test asserting `state_for(shown)` matches the keyboard's own callback namespace would lock this closed.

#### NAV-11 — No history and no re-order: a second kit means retyping everything, prompted by unclickable plain text
- **Surface:** Post-delivery closing message
- **Anchor:** `src/hbd/bot/delivery.py:166`
- **Lens:** ux · **Effort:** medium

**Problem.** The closing message is `delivery.done` — "🎉 That is your kit for {name}. Send /start to make another." — sent as plain text with no `reply_markup` anywhere in `delivery.py`. The single re-engagement moment in the whole product asks the user to type a command that is not in Telegram's command menu (no `set_my_commands` in `src/`), and `state.clear()` has already discarded the draft, so "another" means all ten screens again from scratch: re-picking occasion, genre, voice and language, retyping the name and the note. There is no order history, no `/orders`, no "same recipient, different song", no re-send of a kit whose audio the user lost, and no order id in any user-facing string to quote to support. Only `/start` and `/cancel` are registered (start.py:40-41) — the two highest-intent follow-on actions in a gifting product have no surface at all.

**Remedy.** Attach an inline keyboard to the closing message: `[🎁 Another for {name}]` (re-seeds the draft with the same recipient and jumps to the occasion step) and `[✨ New kit]`. Persist the last N completed briefs per user and add a `/mykits` command that lists them with a re-order button. Register both in `set_my_commands`.

**Proposed EN copy.**

```
🎉 That is your kit for {name}. Want another? Tap below — I will remember the answers you already gave me.
```

#### NAV-12 — The nav row breaks the module's own two-column rule, three-wide with the longest labels in the default locale
- **Surface:** NOTE step nav row (default uz_latn UI)
- **Anchor:** `src/hbd/bot/keyboards.py:84`
- **Lens:** ux · **Effort:** trivial

**Problem.** `keyboards.py:55-60` sets every content grid to a maximum of two columns with an explicit rationale — "Telegram truncates a row that is too wide on a narrow phone, and Uzbek labels are long". `_nav_row` is then written outside that rule and packs three buttons into one row on the NOTE screen. In the default UI language (`uz_latn`, config.py:218) those three are `⬅️ Orqaga` + `Oʻtkazib yuborish` (17 chars, the widest relative expansion in the catalogue) + `Bekor qilish` (12 chars) — roughly 40 characters of label competing for one row width on the exact locale most users land in. Telegram truncates, so the two labels the user most needs to distinguish (Skip, which advances, and Cancel, which destroys everything) become clipped near-identical stubs sitting side by side, and each is under the ~44pt minimum comfortable tap target once thirds of the width are shared.

**Remedy.** Cap `_nav_row` at two buttons per row like every other builder: put Back and Skip on one row and Cancel alone beneath, or give Cancel its own row on every screen (which also mitigates NAV-03's mis-tap risk). Verify the rendered widths against `uz_latn` rather than `en`.

#### SELL-04 — The name confirmation is the product's proof moment and it says nothing
- **Surface:** NAME_CONFIRM screen
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:49 (wizard.name.confirm)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** "I will write and sing it as: <b>{name}</b> Is that right?" is the highest-wow-per-word slot in the whole flow and it is used as a spellcheck. The bot has just silently repaired the user's apostrophe to U+02BB and is about to run a transcribe-compare-re-record loop on that exact word — none of which is said. The user reads a form field where they could be reading the reason to trust the product. This is also the moment that earns the "pronounced properly" claim made in the welcome; unearned there, unpaid here.

**Remedy.** State the stake (spelling drives pronunciation) and the mechanism (I listen back and redo it) in two short lines around the bolded name. Do not explain transliteration strategies — one sentence of mechanism is proof, two is a manual. Pair it with a warmer `button.name_ok` (en.py:91): "✅ Correct" → "✅ Yes, that is it" (still short enough for the Uzbek expansion the two-column cap at keyboards.py:55-60 exists for).

**Proposed EN copy.**

```
I will sing it as:

<b>{name}</b>

The spelling decides the pronunciation, so it is worth a second look. Once the song is recorded I listen back to this word and do it again if it comes out wrong.

Is that right?
```

#### SELL-05 — The song arrives under a filing label
- **Surface:** Audio caption — the first thing the user sees when the product lands
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:135 (delivery.song_caption)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** "🎵 {title} — for {name}" is a metadata row. This caption sits on the single most emotional message the product ever sends, and it is the message most likely to be forwarded to the recipient — so it is also the only copy the RECIPIENT will ever read. It currently says nothing to them, gives no reason to press play with sound on (Telegram autoplays muted in many contexts), and wastes the title.

**Remedy.** Bold the title (HTML parse mode is the bot-wide default, app.py:33), address the recipient in the second line so the caption survives a forward, and give one plain playback instruction. Two lines, no third.

**Proposed EN copy.**

```
🎵 <b>{title}</b>
Written and sung for {name}. Sound on.
```

#### SELL-06 — The lyric reveal is framed as a control panel, not as the reveal
- **Surface:** LYRICS preview screen
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:53-58 (wizard.lyrics.preview)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** The footer is pure affordance listing — "Press ✅ …, 🔄 …, or simply send me your own". The user has just been handed the words of a song written for someone they love, and the copy reads like a toolbar. It never says what they are looking at (the exact words that will be sung), and never banks the reassurance that makes the ✅ easy: nothing has been recorded yet, so changing your mind here costs nothing. That reassurance is the whole reason this step was moved before the order (handlers/lyrics.py:1-19) and it is unspoken.

**Remedy.** Replace the affordance list with one line of framing plus one line of low-stakes reassurance. The three buttons already label themselves (`✅ Use these lyrics`, `🔄 Write different lyrics`), so the footer only needs to name the paste option.

**Proposed EN copy.**

```
<b>{title}</b>

<pre>{lyrics}</pre>

These are the exact words that will be sung. Nothing is recorded yet — keep them, ask for a different set, or send me your own as a message.
```

#### SELL-07 — The commit screen is a receipt with a generic header and a generic button
- **Surface:** CONFIRM screen
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:68-77 (wizard.confirm.summary), en.py:90 (button.confirm)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** The last screen before commitment is headed "<b>Your kit</b>" — the generic product noun again, at the exact point where the recipient's name should be doing the emotional work; the name is demoted to a field label ("Name: X"). The close, "Shall I start?", starts nothing the user can picture, and "✅ Yes, start" is a form-submit label. There is no last-second anticipation, and no statement of what pressing it triggers.

**Remedy.** Make the recipient the headline of the summary and drop the redundant Name row. Close by naming what happens next in concrete craft terms (record, then check the name by ear) so the commit reads as a moment rather than a submit. Rename the button to the action.

**Proposed EN copy.**

```
wizard.confirm.summary:
"<b>{name}'s song</b>
Occasion: {occasion}
Style: {genre}
Voice: {vocal_gender}
Language: {output_language}
Note: {note}

The words are set. Next I record it and check the name by ear. Shall I start?"

button.confirm: "🎬 Record it"
```

#### SELL-09 — There is no proof anywhere, and the one honest proof the system owns is buried in a progress line
- **Surface:** Progress bar — name verification stage; cross-cutting
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:125 (progress.verifying_name)`
- **Lens:** marketing · **Effort:** small

**Problem.** The audit asks for social proof or scarcity. Neither exists in this system — there are no user counts, no ratings, no queue depth, no capacity limit exposed to users, and inventing any of them would be a fabricated claim. The honest substitute is craft proof, and the product has a remarkable one it describes in laundry-list language: "🔍 Checking the pronunciation of the name…" is the bot literally transcribing the sung name and re-recording it if the match falls under 0.85. Said plainly, that one frame is more persuasive than any testimonial — and it is the only stage line that names the differentiator.

**Remedy.** Rewrite the stage line to describe the physical act rather than the abstract check, so the wait itself becomes the proof. Same treatment for the mastering line, which is real work (two-pass EBU R128) described as jargon. Explicitly do NOT add counts, ratings, "X songs made today", or urgency copy — none of it is backed by the system.

**Proposed EN copy.**

```
progress.verifying_name: "🔍 Listening back to how the name was sung…"
progress.post_processing: "🎚 Levelling the mix so it sounds right on a phone…"
```

#### SELL-10 — The most differentiated thing on offer is sold with three words
- **Surface:** GENRE step
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:33 (wizard.genre.prompt)`
- **Lens:** marketing · **Effort:** trivial

**Problem.** "Pick a musical style." sits above the only genuinely local catalogue in the product — Shashmaqom, Uzbek folk, retro estrada, conditioned with real doira and dutar instrument tags (plan_builder.py:55-66). To a user in the target market that list is the reason to choose this bot over a generic song generator, and the prompt gives them no reason to look past Pop, which is the first button.

**Remedy.** Turn the prompt into a question and add one line that points at the local styles by name. One line only — the screen already carries ten buttons.

**Proposed EN copy.**

```
What should it sound like?
Shashmaqom and Uzbek folk are recorded with doira and dutar, not a preset.
```

#### SELL-11 — The steps never say the recipient's name back, even after they know it
- **Surface:** OUTPUT_LANGUAGE step (and the lyrics 'writing' frame)
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:51 (wizard.output_language.prompt), en.py:52 (wizard.lyrics.writing)`
- **Lens:** marketing · **Effort:** small

**Problem.** By step 7 the bot knows exactly who this is for, and every remaining screen still speaks in the abstract: "Which language should the song be in?", "✍️ Writing the lyrics…". The flow reads as a form being filled rather than a song being made for a person. These are the two cheapest personalisation echoes in the product — the recipient is already in scope at both call sites (screens.py:131-135 and lyrics.py:70) — and they sit either side of the wizard's only vendor wait, which is where a form feels longest.

**Remedy.** Pass `name=draft.recipient.display` into both templates. Guard the language prompt: `resolve_step` can only route here with a recipient present, but keep the current generic string as a second key for the no-recipient case rather than rendering a literal `{name}`. Do not echo the name on the earlier steps — it is not known yet, and back-filling it would be worse than not doing it.

**Proposed EN copy.**

```
wizard.output_language.prompt: "Which language should {name} hear it in?"
wizard.lyrics.writing: "✍️ Writing {name}'s song… a few seconds."
```

#### SELL-12 — Cancel and expiry drop the user with a typed command as the only way back
- **Surface:** Cancelled / expired / stray-input screens
- **Anchor:** `/Users/fyuk/Desktop/projects/hbd-bot/src/hbd/bot/locales/en.py:79-80, 85 (wizard.expired, wizard.cancelled, wizard.use_buttons)`
- **Lens:** marketing · **Effort:** small

**Problem.** All three exits end with "Send /start". `finish_with` (handlers/common.py:101) replaces the screen with a keyboard-less message, so a user who taps Cancel — often by accident, since Cancel is on every single screen including the welcome — has to know and type a command to come back. "Cancelled." also leaves ambiguity about whether something was made or kept, on a bot that has just collected a name and a personal note.

**Remedy.** Add a single `[Start over]` button to the screen `finish_with` renders, and say plainly that nothing was kept. Keep `/start` in the text as the fallback for stale messages, where a button cannot be trusted.

**Proposed EN copy.**

```
wizard.cancelled: "Cancelled — nothing was made and nothing was kept."
wizard.expired: "That session has closed. We can pick it up from the top."
button.start_over (new key): "↩️ Start over"
```

#### TRUST-01 — "Nothing was charged" is asserted on every failure, including failures after the payment gate, and no code can ever make it true
- **Surface:** Terminal failure frame + payment copy
- **Anchor:** `src/hbd/bot/locales/en.py:133 (progress.failed); src/hbd/pipeline/orchestrator.py:245-249 (AUTHORIZING stage); src/hbd/payments.py:41`
- **Lens:** trust · **Effort:** small

**Problem.** progress.failed appends "Nothing was charged." to EVERY terminal pipeline failure, unconditionally (progress.py:61-62 maps any FAILED status to this one string). But AUTHORIZING is stage index 4 of 11: composing_song, verifying_name, rendering_greetings, post_processing, persisting and delivering all fail AFTER authorization has succeeded. There is no capture, void, reversal or refund anywhere in the codebase — the PaymentProvider seam exposes only authorize() (payments.py:41), and NoopPaymentProvider records nothing. So the single most trust-sensitive sentence in the product is a hardcoded string with no relationship to payment state. It is accidentally true today only because the amount is 0; the day a real rail is wired in (which confirm.py's docstring says is the explicit design intent) it becomes a false financial statement shipped to every user whose song failed to render after auth. That is the exact class of claim that produces chargebacks and regulatory complaints.

**Remedy.** Make the reassurance conditional on the failing stage: the ProgressEvent already carries stage and step_index, so render the no-charge clause only when event.step_index < STAGE_ORDER.index(AUTHORIZING). Split progress.failed into progress.failed_before_charge and progress.failed_after_charge, and add void/refund to the PaymentProvider protocol so the after-charge copy has something true to promise. Until a rail exists, the after-auth string should promise a human follow-up, not a financial fact.

**Proposed EN copy.**

```
progress.failed_before_charge: "❌ We could not finish this one. Nothing was charged."  |  progress.failed_after_charge: "❌ Something broke while making your song. We are reversing the payment — if you do not see it back within 3 days, send /support."
```

#### TRUST-02 — The user commits with "✅ Yes, start" having never been shown a price, while three copy strings imply money is at stake
- **Surface:** Confirm screen
- **Anchor:** `src/hbd/bot/locales/en.py:70-79 (wizard.confirm.summary)`
- **Lens:** trust · **Effort:** trivial

**Problem.** wizard.confirm.summary lists Name / Occasion / Style / Voice / Language / Note and then asks "Shall I start?". No amount, no currency, no "free", no terms link appears anywhere in any of the four catalogues — verified: no locale key contains a price. Yet the user has already been primed to expect a charge by nothing at all before this point, and will be told "Nothing was charged" / "Payment did not go through" the instant anything fails. This is the worst pairing available: zero price disclosure before commitment, plus charge-shaped language after. A user who sees "Payment did not go through" for a product they believed was free will assume the bot tried to bill a card they never gave it. Conversely, the product IS free today and never says so — the strongest possible conversion lever at the commit moment is unused.

**Remedy.** Add a cost line to wizard.confirm.summary rendered from deps.amount_minor / deps.currency, with an explicit free case when amount_minor == 0. One key, one f-string in screens._confirm_screen, and it is correct for both the current build and the paid one.

**Proposed EN copy.**

```
wizard.confirm.summary — insert before "Shall I start?":  "Cost: {price}\n\n"   with  wizard.confirm.price_free: "Free — this one is on us."  and  wizard.confirm.price_amount: "{amount} {currency}, charged only if your song is delivered."
```

