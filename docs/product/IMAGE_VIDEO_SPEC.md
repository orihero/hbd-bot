# IMAGE_VIDEO_SPEC — generated images and videos (✨ Create)

**Migration head when this was written:** `0028` on `main`; `0029` (`add_acquisition_source`) is
already taken on `feat/capture-start-payload` and lands with M0.4, so this spec's revisions are
`0030`–`0032`. Cite this document by section —
`IMAGE_VIDEO_SPEC §4.2` — never by path, so the citation survives the file moving.

**Status, 2026-09-24 — plan only. Nothing here is built.** It specifies `DECISIONS.md` **D20–D26**
and is the build plan for them. The research it rests on is
`docs/research/RESEARCH-image-video-pipeline.md` (frozen, same date).

**The owner's answers of 2026-09-24 are binding** (§0.2). The request they answer is quoted
verbatim in §0.4. Where the research recommended something
else — a licensed image backend, one Gemini project instead of a key pool, a face policy — the
owner's choice is what this spec implements, and the residual risk is written into §11 and into the
D-entry that records the choice. Do not relitigate them in review; raise a §12 question instead.

---

## 0. Ground truth this specification is built on

### 0.1 What exists today

| Fact | Consequence |
| --- | --- |
| The bot sells one product, a song kit; menu is a 2×2 reply keyboard `[🎵 \| 🎫] / [⚙️ \| ❓]` (`bot/keyboards.py:188-214, 790-818`, dispatched in `bot/handlers/menu.py:77-122`); `menu.py:14-18` records that six buttons truncate on a 360dp phone | Keep four buttons; 🎵 becomes **✨ Create** opening a picker (§2.2). |
| The reply keyboard is re-sent only by `/start`, onboarding end, a language change, 🏠, fallback-with-no-state and checkout (`start.py:112`, `onboarding.py:426`, `menu.py:167,221`, `fallback.py:108`, `checkout.py:460`) | Existing chats never see a new label unless we re-push it (§2.2, `MENU_VERSION`). |
| **No photo, document, album or voice-note intake exists** (only `chatlog.py:192` logs "[Photo]"); a 10-photo album at a text step draws 10 replies (`fallback.py:97-110`) | Album handling is net-new (§2.3.2). |
| One `Wizard` StatesGroup, 1:1 with `WizardStep`; `states.py:97-107` explains why a non-step flow needs its own group; `NavAction.BACK` expires any non-Wizard state (`navigation.py:100-111`) | New `ImageOrder`/`VideoOrder` groups and a new `MediaCB(prefix="med")` callback (§2). |
| Per-chat `RedisEventIsolation` lock (`bot/app.py:86-97`) serialises a chat's updates | No slow call in a handler: screening, script-writing and generation run in the worker. |
| The song flow parks the chat in `Wizard.submitting`; the menu router stands down in that state (`~StateFilter(Wizard.submitting)`, `menu.py:241-242`); the worker's `_release_session` only wipes FSM data when `ORDER_ID_KEY` still matches (`runtime/jobs.py:476-487`) | A media draft would **not** be wiped (`start_image`/`start_video` drop `ORDER_ID_KEY`); what blocks media during a render is the stand-down filter and the lost progress park. v1: media cannot start while a song renders (§2.2, Q5). |
| Inbound gate: 30 updates / 60 s per account, in-process (`src/bayram/ratelimit.py:60-72`, `config.py:644-667`) | Two 10-photo albums approach the ceiling: album follow-ons count as one update (§2.3.2). |
| Four processes (bot, one ARQ worker, admin, Payme); host has 2 vCPU, 1.9 GiB RAM, ~831 MiB free, 38 GB disk (`docs/deployment/00-host-inventory.md` row 1, row 9) | No fifth process; no guard model on the host; stream bytes to disk, never hold a video in RAM (§3.6). |
| Worker: `max_jobs=15`, `job_timeout=900 s` (`config.py:755-756`, `runtime/jobs.py:769-1000`); in-process semaphores only | Short idempotent stage jobs; a Redis GPU mutex (§3.4). |
| `orders` feeds song metrics (28 `OrderRow` refs in `db/admin/metrics.py`), `assets.order_id` is NOT NULL FK, `generation_attempts` feeds name-strategy tuning | Separate `media_*` tables (§3.2). |
| `LocalFileStorage.put(key, bytes)` holds the object in memory (`storage.py:149`); `signed_url` is `file://` | Add a streaming `put_file`; send the gateway base64, never a URL (§3.6). |
| `RetentionClass.EPHEMERAL` is declared and written by nothing; `var/workspace` is never swept (`db/retention.py:58,70`, `db/purge.py:789-829`) | Write `sweep_workspace` before video lands (M0). |
| Every `*_expires_at` column must be read by a `rows_past_expiry_statements` predicate (`db/purge.py:696`, `tests/test_db/test_audit_retention.py:386-392`); personal-data tables are enumerated (`tests/test_db/test_privacy_constraints.py:172-179, 422`) | Each new table is registered and purged (§3.2.4). |
| `checkout_provider` defaults to `"stub"` (`config.py:857`), `credits_enforced=False` (`:572`); the stub marks every charge paid (`checkout.py:320-370`) | Launched unchanged, media would be free. Boot refusal + beta allowlist (§7.4). |
| The credit is one fungible song-denominated scalar (`db/plan_sql.py:15`, `models/credit_account.py:69`); `topup_purchases` has `CHECK credits_granted > 0` | Media has its own receipt and its own kind-scoped refund ledger (§7). |
| Six places branch SINGLE-else-PLAN and would misfile a new SKU; one raises **inside the Payme money commit** (`db/payme.py:1058`) | Exhaustive fail-closed `match` at every site (§7.3). |
| D17: settlement starts the render via `payment_intents.resume_order_id` + a one-shot `resumed_at` claim (`runtime/render_resume.py`, `db/payme_sql.py:771-795`); a burned claim is recoverable for songs only because the customer holds a credit and a 🎬 button | Media carries `resume_media_job_id` on the intent, but its start latch is the **job row's own conditional state move**, re-driven by `media_sweep` (§7.2); `resumed_at` is audit only. |
| `VENDOR_SECRET_FIELDS` is asserted by set equality against every secret-shaped `Settings` field (`config.py:133-139`, `tests/test_admin/test_settings_and_boot.py:88-91`) | Every new credential is added there (§9.5). |
| Vendor/usage enums are VARCHAR(32), no CHECK (`contracts.py:283-356`) | New `Vendor`/`VendorOperation`/`UsageTask` members need no DDL. |
| Migrations are not in the wheel (`00-host-inventory.md` row 45) | Each revision is copied to the host and run as the owner role (§10). |
| Local gateway: flux2 t2i/img2img 31–43 s; Wan t2v/i2v ~17.5 min per 5.06 s silent 720p clip; one job at a time; traps in `RESEARCH-image-video-pipeline` §1.3 | §4.2 is written against those traps. |
| Gateway security: plain HTTP, residential IP, one static key also accepted as `?api_key=`, keeps every input | Hardening is an M2 prerequisite (§9.1). |

### 0.2 Owner decisions, 2026-09-24 (binding)

| # | Decision | Recorded in | Implemented in |
| --- | --- | --- | --- |
| O1 | Local flux2 (FLUX.2-dev) for **paid** images; licence risk accepted; Higgsfield/fal stay behind the flag | D21 | §4.2, §11 R1 |
| O2 | Video has two tiers — **Standard** (local Wan) and **Fast** (Higgsfield); only Standard is enabled now; prices TBD as config | D22 | §1.3, §7.1 |
| O3 | Voice is optional: none / AI voice on user text / AI voice on LLM text (editable) / own Telegram voice note muxed as-is; no cloning | D23 | §2.4, §5 |
| O4 | Real people and faces: **Terms only** — a Terms + Privacy gate before *any* use of the bot, plus normal safety checks; **no face-specific logic** | D20, D26 | §2.1, §6, §11 R3 |
| O5 | 5 000 UZS buys **one request yielding 2 images** | D25 | §7.1 |
| O6 | Several photos on a 1-ref backend are **composited into one collage**; passed natively when a multi-ref backend is enabled | D21 | §4.4 |
| O7 | Keep 4 buttons; 🎵 → **✨ Create** → Song / Image / Video; old label aliased; keyboard re-pushed | D20 | §2.2 |
| O8 | Gemini TTS **key pool** (5–6 keys, possibly several projects); ToS risk accepted; free-tier keys are acceptable for all jobs, training on narration text accepted (owner, 2026-09-24, answering Q17); per-key 429 cooldown, health, ElevenLabs fallback | D23 | §5.2, §11 R2, Q17 |
| O9 | **Free beta on the stub rail first**, owner/admins only (allowlist), until Payme production; boot refuses media on stub without beta flag + allowlist. "Payme production" = `checkout_provider=payme`, `credits_enforced`, **and not `payme_is_sandbox`** | D25 | §2.5, §7.4 |
| O10 | Guard models on the 5090 (Qwen3Guard-Gen-4B text, ShieldGemma 2 images, whisper for voice notes); screen before payment and output before delivery; **fail closed** | D24 | §6 |
| O11 | Paid customer jobs pre-empt marketing renders; during an operator "GPU reserved" window the local tier refuses orders before payment | D22 | §3.4, §4.5 |
| O12 | Beta access: owner/admins only | D25 | §2.5 |
| O13 | Re-rolls are paid again; refund credit only on generation failure or our output block | D25 | §7.5 |
| O14 | Audio capped to the clip length (5 s now): AI text ≤ ~12 words; voice notes over the limit rejected before payment. 12 words is the ceiling; per-language budgets below it (§5.3) keep the text speakable in 5 s | D23 | §2.4, §5.3 |
| O15 | Aspect: user picks 9:16 / 1:1 / 16:9, default 9:16 | D20 | §1.3 |
| O16 | Uploads (photos, voice notes) deleted **immediately after delivery**, and on failure/abandon; outputs unspecified (spec defaults 30 d, open); gateway needs a sweeper. Exception confirmed by the owner 2026-09-24 (Q16): a CSAM-class block keeps the offending bytes encrypted for ≤72 h pending the escalation owner's reporting decision (§6.7) | D20, D24 | §3.2.4, §6.7, §9.2, Q2, Q16 |
| O17 | Claude drafts uz/ru/en Terms + Privacy marked DRAFT; owner/counsel approves; acceptance stored with a version so a change re-prompts | D26 | §2.1, Appendix A |
| O18 | Backend selectable by flag: `local \| higgsfield \| fal \| fake`; Higgsfield/fal later behind the same protocol | D21, D22 | §4 |

### 0.3 What is broken today and must be fixed first (M0)

| Defect | Where | Why it blocks media |
| --- | --- | --- |
| **Zero-greeting `_replay` double-bill.** Shipped `greetings_per_kit=0` (`config.py:~465`, `.env.example:243`); `_build_kit` raises `not_found` with no greeting rows (`db/repository.py:461`), so `_replay` (`pipeline/orchestrator.py:723`) returns `None` and a redelivered job re-runs the pipeline and **pays the vendor again**. No test builds a zero-greeting kit (`tests/test_db/conftest.py:125` defaults to 3). | songs, today | Same replay pattern on a Higgsfield video is a ~$0.56–2.55 double spend. |
| **Song moderator fails open.** `ModerationPayload.is_allowed: bool = True` with `extra='ignore'` (`pipeline/moderation.py:64-70`) parses `{"allowed": false}` as allowed; transport errors allow (`:1-31`); user text pasted unescaped (`pipeline/prompts.py:246-258`). | songs, today | The media verdict schema must not inherit it (§6.3); fixed separately (§6.8). |
| Workspace never swept | `db/retention.py:58,70` | Video intermediates are 10–100× song bytes. |
| Row-existence onboarding bug: `onboarding.py:239` returns `True` for "language chosen" whenever a `user_profiles` row exists; the fix is only on `feat/capture-start-payload`, together with migration `0029_add_acquisition_source` | onboarding | The terms gate (§2.1) must not open a profile row early, or users skip the language screen. |
| Stale price in docs: PAYME_INTEGRATION §8.6.2 and `main.py:128` say 7 000 UZS; live is 15 000 (`config.py:503`) | docs | Media copy interpolates prices; never hard-codes them. |

### 0.4 The owner's original request, 2026-09-24 (verbatim)

Kept word for word, typos included, so later readers can see what was asked before the question
rounds turned it into §0.2. Where §0.2 differs from this text, **§0.2 wins**: it records the
owner's later answers. Where the request's assumptions turned out wrong, the correction is in
the right-hand column below.

> we need to implement video creation pipeline also here! What I got in mind is this: I have local video gen API setup! Here is the documentation: /Users/ai/Downloads/Telegram\ Desktop/README.md /Users/ai/Desktop/work/tasks/ai-video-production/openapi.json
> We will be using that for now later I will spin up a backup server or add higgsfield api! WE need to have feature flag there to generate it from local model or higgsfield or any other;
> For voice we will be using gemini tts (3.8 version); I will give you several api keys since they have rate limit (5-6 api keys should be enaugh)
>
> How the process goes:
> 1. User goes to bot and presses video or image (we will add those two; currently we have create song button)
> 2. Image: we will get from them image or prompt for image generation; we will ask for payment - 5000UZS for each image; we will forward their image/prompt to generation AI and give them the results after successfull payment; Prompt is required here; even if they send image we need to get prompt anyways; They can send multiple images
> 3. VIdeo: We will ask them for prompt or reference image; Image is optional but prompt is required; Several images are allowed; When they send prompt we will trigger 2 things: audio generation with gemini tts; video generation with my local modals or higgsfield;
>
>
> Redflags: Our API has local llm also! I was thinking about giving those prompts to qwen3.8 flash-next or laya for identifying the prompt injection, misuse, nudity, terrorism, copyright etc enfrigments; What is your take on this?
> Please do a research if need, ask any number of questions to understand the feature better and write a plan! All in ultracode

| The request assumed | What the research found / what was decided |
| --- | --- |
| The local video API is ready to build on | Its README says video is broken, but that README is stale: Wan works, at ~17.5 min per 5 s clip, one job at a time (§0.1; D22) |
| 5–6 Gemini keys add rate-limit headroom | Limits are per project, not per key; pool kept as an accepted ToS risk (O8, D23) |
| 5 000 UZS "for each image" | One request yields 2 images for 5 000 UZS (O5) |
| TTS and video start "when they send prompt" | Nothing billable runs before payment; screening comes first, then TTS and render run in parallel after settlement (§2, §7) |
| Moderation by "qwen3.8 flash-next or laya" | Neither model exists; dedicated guard models on the 5090 instead (O10, D24, §6) |
| A separate Image and Video button | One ✨ Create button with a Song / Image / Video picker (O7) |

---

## 1. Scope and non-goals

### 1.1 Products

| Product | What the customer gets | Backend now | Status at launch |
| --- | --- | --- | --- |
| **Song** | Unchanged. Reached through ✨ Create → 🎵. | as today | live |
| **Image** | One request → **2 images**, from a prompt (required) and 0..N photos. | `local` (flux2) | beta (allowlist) → paid (M5) |
| **Video — Standard** | One 5 s clip, prompt + optional photos, optional voice. Slow (queue + ~17.5 min render). | `local` (Wan 2.2) | beta → paid |
| **Video — Fast** | Same, rendered on Higgsfield (Kling 3.0 std by default). | `higgsfield` | **flagged off** (M6) |

### 1.2 Non-goals (v1)

- **No voice cloning or voice design** from a customer's voice; own voice notes are muxed as-is.
- **No face-specific logic** (owner, O4): no face detector, no "is this you / consent" tap, no
  face-conditioned policy. Real-person risk is carried by the Terms gate (§2.1) and the general
  guards (§6). Residual risk: §11 R3.
- No lip-sync, no multi-speaker narration, no music bed.
- **No promise of legible text in images** (rejected #15: no model renders U+02BB). Copy never
  offers "write a name on it"; the watermark rule (`src/bayram/watermark.py:1-10`) carries over —
  `@bayram_uzbot` never goes into a generation prompt.
- No Hunyuan; `zootopia`, `storybook`, `storybook_wan` are unreachable from bayram (§4.2).
- No automatic cash refunds (Payme `CancelTransaction` after Perform is −31007 by design,
  `payme/errors.py:140-152`); no one-tap Pay (blocked on `CheckoutProvider.prepare_link`).
- No templates/occasion presets in v1 (Q9).

### 1.3 Product parameters

| Parameter | Image | Video Standard | Video Fast |
| --- | --- | --- | --- |
| Outputs per request | 2 (variant 0, 1; seeds `s`, `s+1`) | 1 | 1 |
| Prompt | required, 3–800 chars | required, 3–800 chars | same |
| Photos | 0..`media_max_reference_images` (default 4) | 0..4 | 0..4 |
| Photos on a 1-ref backend | collage (§4.4) → img2img, denoise 0.6 | collage → i2v start frame | native refs |
| Aspect (default 9:16) | 9:16 → 768×1344; 1:1 → 1024×1024; 16:9 → 1344×768 | 9:16 → 720×1280; 1:1 → 960×960; 16:9 → 1280×720 | model presets |
| Length | — | `length: 81`, 16 fps (5.06 s) | 5 s |
| Voice | — | none / AI (user text) / AI (LLM text) / own note, ≤5 s | same |
| Typical wait | queue + ~2×40 s | queue + ~17.5 min | ~1–3 min (to measure) |

Resolutions are config (`media_image_sizes`, `media_video_sizes`), all multiples of 16, and are
always sent explicitly (the gateway ignores input size, `RESEARCH-image-video-pipeline` §1.3).

---

## 2. User flows

All new customer copy lives in `src/bayram/bot/locales/{en,ru,uz_latn,uz_cyrl}.py` (never
`src/bayram/i18n/locales/*.json`, which no customer sees). uz Latin uses U+02BB (oʻ, gʻ) and
U+02BC (ʼ) only (`tests/test_i18n.py:185`); `uz_cyrl` is transliterated from `uz_latn` at authoring
time and must exist for key parity (`tests/test_i18n.py:52`). Every button leads with a distinct
emoji + VS16 — but `test_locale_contract` only checks keys under `BUTTON_LABEL_PREFIXES`
(`button.`, `menu.`, `occasion.`, `genre.`, `vocal_gender.`, `language.`,
`tests/test_bot/test_locale_contract.py:329-336`). So: **every new button label is keyed
`button.media.*`, `button.terms.*` or `button.create.*`** (message bodies stay `media.*`, `terms.*`,
`create.*`; the short names in the tables below are the part after the prefix); ⏹ U+23F9, 🖥 U+1F5A5
and 🗣 U+1F5E3 are added to `TEXT_DEFAULT_EMOJI`; every new screen is added to `_labels_by_screen`
so the one-screen distinct-emoji test covers it; and no new message body goes under `menu.` (it
would be read as a button — `NOT_A_BUTTON` is pinned to `{"menu.prompt"}`). Prices are
interpolated, never written into a catalogue (`bot/pricing.py:14-19`). Key constants are named
`*_KEY`.

**Callbacks.** Pre-freeze screens (compose, aspect, voice pick) use `MediaCB(prefix="med", action,
arg)` with a state filter. **Every post-freeze callback** — 💳 / 🎟 / 🎁 / ✏️ / ✖️ on the quote, ✖️ on
the pay link, 🔁 `retry_later`, 🔁 `again`, ✨ `create.more`, 🔁 `use_credit` — carries the
`media_jobs.id` (22-char base64url, still ≤64 bytes), is **registered without a state filter**
(the FSM may be cleared or days old), and checks `job.telegram_user_id == callback.from_user.id`
and the job's current state before acting: a row-driven, idempotent dispatch like `navigation`'s
stateless callbacks. A press that no longer fits the row's state answers `media.stale` as a toast.
Terms callbacks use their own `TermsCB(prefix="trm")` (§2.1).

### 2.1 Terms of Use + Privacy gate — every user, before first use

**Where.** A third `Onboarding` state, `Onboarding.terms`, between `language` and `contact`
(`states.py:94-122`) for new users; for everyone already onboarded, a `TermsGateMiddleware`
(outer, after the inbound gate `bot/gate.py`, before routers) that compares the user's accepted
version with `settings.terms_version`.

```
            /start ─► Onboarding.language ─► Onboarding.terms ─► Onboarding.contact ─► menu
                                                 │  ▲
                              ❌ decline ─────────┘  │ (screen repeats on any input)
existing user, accepted_version < terms_version ──┘   (accept → back to what they were doing: menu_screen)
```

- **Handlers live in the onboarding router, not the media router.** The onboarding router is
  registered third (`bot/handlers/__init__.py:218-244`) and ends with the `NotOnboarded()`
  catch-all (`onboarding.py:539-540`), which would otherwise swallow a not-yet-onboarded user's
  ✅ tap and re-send the language/contact screen. So `Onboarding.terms` message/callback handlers
  and the gate's accept callback are registered **inside `onboarding.build_router()`, above the
  `NotOnboarded` registrations**, with a dedicated `TermsCB(prefix="trm")` so terms does not
  depend on the media router being present. The file is `bot/handlers/terms.py`, imported by
  `onboarding.build_router()`.
- **Resume knows three steps.** `Identity` gains a third field (`terms_ok` — accepted the current
  versions); `handle_start` (`start.py:~96-107`), `_resume_onboarding` (`onboarding.py:461-478`)
  and `NotOnboarded` branch in the order **language → terms → contact**, so `/start` or a Redis FSM
  expiry while in `Onboarding.terms` brings the terms screen back, never contact. The accept
  handler finishes by resuming whatever came next: the next onboarding step if not onboarded,
  otherwise it re-sends `menu_screen`.
- Screen `terms.gate` (summary ≤ 900 chars + `/terms`, `/privacy` commands + optional
  `settings.terms_url`), buttons **✅ `button.terms.accept`** and **📄 `button.terms.read_full`**.
  Declining is just not accepting: `terms.required` repeats; nothing else is served.
- **Allowlist while not accepted** mirrors `bot/gate.py` `ERASURE_COMMANDS` (`privacy`, `forget`,
  `support`, `gate.py:114`) plus `/start`, `/terms`, `/help`, `/cancel`, the language picker and
  `trm:*` callbacks, **and** the replies a support ticket needs: a message that `ListeningTicket`
  would claim (`support.py:567-612`) passes, reusing the inbound gate's `_is_answer_to_the_bot`
  carve-out (`gate.py:606+`) — otherwise `/support` opens a ticket the user cannot describe.
  Everything else is answered with `terms.gate` at most once per 60 s (claim-notice pattern,
  `src/bayram/ratelimit.py`); a **blocked callback is always `callback.answer()`-ed** with a
  `terms.required` toast (the 60 s de-dup applies only to the full message), so no button spins.
  **Worker deliveries are unaffected** — the gate is inbound only, so a song in flight when the
  version bumps is still delivered.
- Version bump (`BAYRAM_TERMS_VERSION`, e.g. `2026-10-01`) re-prompts everyone with
  `terms.updated` (same buttons).
- **Storage:** append-only `terms_acceptances` (§3.2.1), keyed by `telegram_user_id`, written in
  one statement on accept; the check is cached in Redis `terms:ok:{tg}` = version (TTL 1 d).
  **It must not create a `user_profiles` row** (row-existence bug, §0.3). **`/forget` deletes
  `terms:ok:{tg}`** in the same arm that anonymises acceptances (§9.3), so a forgotten user sees
  the terms screen on the next message.
- **`/privacy` already exists** (`commands.py:119-141, 383`, `menu.handle_show_privacy`), rendered
  from the single `common.privacy_text(language, DEFAULT_RETENTION_POLICY)`. M1.2 does not add a
  second privacy handler or a second notice: the versioned Privacy Notice (Appendix A.2)
  **replaces `privacy.text` behind the same `privacy_text()` helper**, and `RetentionPolicy` gains
  `media_input` and `media_output_days` fields so the media retention numbers are interpolated,
  never typed. Only **`/terms`** is new: added to `commands.build_router()` and to the
  `set_my_commands` list with a `command.terms` description in all four locales.
- **Stale copy updated in the same PR (M1.2, finished in M2.5):** `help.text` ("I write and record
  one song…", "🎬 /start — make a song"), `privacy.forgotten` and the `/forget` confirmation ("delete
  the song I am holding"), the `command.*` BotCommand descriptions, and the `privacy.text`
  retention lines. A test asserts `privacy.text` mentions media retention exactly once when any
  media SKU is offered.
- The terms screen replaces LR-54's "notice at first use" requirement for the whole bot (D26); the
  song flow's S3 recipient-data notice stays.

| Key | en | ru | uz_latn |
| --- | --- | --- | --- |
| `terms.gate` | Before we start: please read and accept our Terms of Use and Privacy Notice. In short: you must be 18+ (or use the bot with a parent's permission for songs only), you are responsible for what you upload, only upload photos and voices you have the right to use, and we delete your uploads after delivery. | Прежде чем начать, прочитайте и примите Условия использования и Уведомление о конфиденциальности. Коротко: … | Boshlashdan oldin Foydalanish shartlari va Maxfiylik bildirishnomasini oʻqib, qabul qiling. Qisqacha: … |
| `button.terms.accept` | ✅ I accept | ✅ Принимаю | ✅ Qabul qilaman |
| `button.terms.read_full` | 📄 Read in full | 📄 Читать полностью | 📄 Toʻliq oʻqish |
| `terms.required` | To use the bot, please accept the Terms. | Чтобы пользоваться ботом, примите Условия. | Botdan foydalanish uchun shartlarni qabul qiling. |
| `terms.updated` | Our Terms have changed ({version}). Please review and accept to continue. | Условия обновлены ({version}). … | Shartlar yangilandi ({version}). Davom etish uchun qabul qiling. |

(The age clause is Q7; the draft text is Appendix A. Full ru/uz text is translated from the
approved en draft, not from this table.)

### 2.2 ✨ Create picker and menu rollout

- The key stays `MENU_GENERATE_LABEL_KEY = "menu.generate"` (`keyboards.py:188`); its **value**
  changes to **✨ Create / ✨ Создать / ✨ Yaratish / ✨ Яратиш** (en / ru / uz_latn / uz_cyrl). Because
  `MENU_LABELS` and `_KEY_BY_LABEL` are both computed from `MENU_BUTTON_KEYS` through `translate()`
  (`keyboards.py:212-214`), the old 🎵 strings would vanish the moment the value changes, and adding
  a key to `MENU_BUTTON_KEYS` would draw a fifth button. So: a separate
  `MENU_LEGACY_LABEL_KEYS = {"menu.generate_legacy": "menu.generate"}`, holding the old 🎵 labels in
  all four catalogues, merged into `_KEY_BY_LABEL`/`MENU_LABELS` for dispatch
  (`bot/handlers/menu.py:77-79`) but **not drawn**. Row budget ≤34 chars (`keyboards.py:180`) holds.
- ✨ opens an inline picker `create.pick`: **🎵 Song** / **🖼 Image** / **🎬 Video**. Image/Video
  buttons render only if offered to *this* user (§2.5); if neither is, ✨ goes straight to the song
  flow (today's behaviour, no extra tap).
- 🎵 in the picker calls `common.reset_to_welcome` unchanged. 🖼/🎬 call `start_image`/`start_video`
  (`clear_keeping_identity` + fresh `session_id`, then set `ImageOrder.compose` /
  `VideoOrder.compose`).
- **During a song render** (`Wizard.submitting`) the menu router keeps standing down
  (`~StateFilter(Wizard.submitting)`, `menu.py:241-242`) → `wizard.queued`. The reason is the
  stand-down itself and the song's progress park, which leaving `submitting` would lose — **not**
  data loss: `_release_session` (`runtime/jobs.py:476-487`) only wipes a session whose
  `ORDER_ID_KEY` still matches, and `start_image`/`start_video` drop that key. Q5 is therefore a UX
  decision.
- **Re-push:** the menu version is stored **per user outside FSM data** — a no-TTL Redis key
  `menu:v:{tg}` — because FSM data is not durable: `_release_session` does `set_data({})` after
  every song, FSM data expires after 14 days, and `/forget` does a bare `state.clear()`
  (`clear_keeping_identity` keeps only `UI_LANGUAGE_KEY` and `ONBOARDED_KEY`, `common.py:236`). On
  the next private message from a user whose stored version < `keyboards.MENU_VERSION`, one
  post-handler hook sends a **separate** `menu_screen` message carrying the reply keyboard and
  `notice.menu_updated` ("✨ New: images and videos — tap ✨ Create") and stores the new version (an
  inline screen cannot carry a reply keyboard). Only users to whom media is offered see the "new"
  line; others get the relabel silently. `/forget` deletes `menu:v:{tg}`. No broadcast needed; a
  broadcast (`BROADCAST_SPEC`) remains optional for launch day.
- **Albums outside media compose.** `fallback.handle_stray_message` (`fallback.py:97-110`) and
  Wizard steps get a `media_group_id` dedupe using the same 60 s seen-set as the gate (§2.3.2):
  one reply per album, not one per photo.

### 2.3 Image

#### 2.3.1 State diagram

```
ImageOrder.compose ──[✅ Done, prompt present]──► ImageOrder.aspect ──[aspect]──► (row frozen: media_jobs.state=screening)
      ▲  │ text → prompt; photo/doc → tray                                           │ enqueue media_screen
      │  └─[🗑 Clear photos] / [✖️ Cancel → menu, draft dropped]                       ▼
      │                                                    ImageOrder.quote  ◄── worker edits tray: quote | refusal | busy
      └──[✏️ Edit: row → cancelled + inputs purged; compose reopened from the draft]── │
                                                             ├─[💳 Pay] → CheckoutProvider.charge → Payme link message
                                                             │            (state=awaiting_payment; FSM cleared to menu;
                                                             │             link message keeps ✖️ Cancel request)
                                                             ├─[🎟 Use refund credit] → state=paid
                                                             ├─[🎁 Beta: generate free] (allowlist, rail not live-paid) → state=paid
                                                             └─[✖️ Cancel] → state=cancelled, inputs purged
settlement ─► media_start ─► generate ×2 ─► output screen ─► deliver 2 photos ─► purge inputs
```

The FSM holds `MediaDraft` under a new `MEDIA_DRAFT_KEY` (update the key inventory docstring,
`bot/draft.py:10-31`): `{kind, session_id, prompt, refs:[{file_id, file_unique_id, mime, w, h,
size}], last_media_group_id, tray_message_id, aspect, tier, voice}` — **never bytes** (Redis keeps
FSM 14 days). On aspect pick the draft is frozen into a `media_jobs` row (state `screening`, with
`chat_id` and `tray_message_id` copied onto the row so the worker can edit it) and `media_inputs`
rows carrying only Telegram ids; the worker downloads bytes (§3.3).

**Freezing and the one-open-request rule.** Freezing runs, in one transaction: (1) a conditional
`UPDATE media_jobs SET state='cancelled' WHERE telegram_user_id=? AND kind=? AND state IN
('drafting','screening','quoted')` for any earlier pre-payment row of the same kind (its inputs are
purged by `media_cleanup`), then (2) the insert. If a row of that kind is in `awaiting_payment` or
any post-payment state, **nothing is frozen**: the tray becomes `media.open_request` ("You already
have an image request open — 💳 Pay / ✖️ Cancel it" for `awaiting_payment`; "Your image is being
made, about {eta}" for a paid one). The same applies to the paths that leave an open row behind
while clearing the FSM: `/start`, ✨ → 🖼 again, and 💳 Pay.

**✏️ Edit** (from the quote or from `media.refused`) sets the old row to `cancelled` (inputs
purged) in the same transaction that reopens compose from the stored draft. Every ✅ Done creates a
**new** row in `screening`; a row's prompt, refs and narration are never updated in place after
freezing. `media_start` refuses to run unless `screen_decision='allow'`, `screen_policy_version`
is current, and `content_sha256` (hash of prompt + narration + every input `sha256`, recorded by
`media_screen`) still equals a fresh hash of the row.

#### 2.3.2 Compose and album handling

- Accept `F.text` (prompt), `F.photo` (largest `PhotoSize`), `F.document` with `image/jpeg|png|webp`
  (≤20 MB, the Bot API getFile ceiling); anything else → `media.compose.unsupported`.
- Dedupe on `file_unique_id`; cap at `media_max_reference_images`; over the cap → one
  `media.tray.cap_reached` per `media_group_id`.
- **One tray message per compose**, edited in place — never a reply per photo. **Every accepted
  item that changes the count edits the tray** (at most `media_max_reference_images` edits per
  compose), so a 4-photo album ends showing "Photos: 4/4". No `sleep` and no debounce task in the
  handler (per-chat lock).
- Photos or albums sent **after ✅ Done** (in `aspect`, `quote`, `VideoOrder.voice*`) get one reply
  per `media_group_id`: `media.compose.closed` ("Photos can be added before ✅ Done — tap ✏️ Edit").
- A caption on any item sets/replaces the prompt.
- Gate: follow-on items of a `media_group_id` already seen in the window count as zero updates in
  `bot/gate.py` (key: `(account, media_group_id)` seen-set, 60 s TTL).
- `chatlog.py:180-203`: add a document branch; collapse an album to one line.
- Done without a prompt → callback alert `media.need_prompt`.

#### 2.3.3 Screens and copy (image)

| Key | en (ru / uz_latn drafted at build; uz uses U+02BB) | Buttons |
| --- | --- | --- |
| `create.pick` | What shall we make? | 🎵 `create.song` · 🖼 `create.image` · 🎬 `create.video` |
| `media.image.compose` | Describe the picture you want. You can also attach up to {max} photos (optional). | — (tray below) |
| `media.tray` | Prompt: {prompt_state} · Photos: {n}/{max} | ✅ `media.done` · 🗑 `media.clear_photos` · ✖️ `media.cancel` |
| `media.tray.cap_reached` | Only the first {max} photos are used. | — |
| `media.need_prompt` | Please type a description first. | alert |
| `media.aspect` | Choose a shape. | 📱 `media.aspect.portrait` (9:16, default) · ⏹ `media.aspect.square` · 🖥 `media.aspect.landscape` |
| `media.screening` | Checking your request… | — |
| `media.image.quote` | 2 images · {aspect} · {price} · ready in about {eta}. | 💳 `media.pay` **only when the rail is live-paid** (§2.5) · ✏️ `media.edit` · ✖️ `media.cancel` (+ 🎟 `media.use_credit` if SKU balance > 0; + 🎁 `media.beta_free` only when the rail is **not** live-paid and the user is allowlisted) |
| `media.busy` | Our studio is fully booked right now. Please try again later — you have not been charged. | 🔁 `media.retry_later` — re-runs the capability check (§7.2 step 1) on the **same** frozen row; clear → quote; still blocked → same screen |
| `media.open_request` | You already have an {kind} request open. | 💳 (re-sends the pay link) · ✖️ `media.cancel` — or, for a paid job, "being made, about {eta}" with no buttons |
| `media.stale` | This button is no longer active. | toast |
| `media.refused` | We can't make this one. Please change your description or photos. | ✏️ `media.edit` · ✖️ |
| `media.refused.suspended` | Creating images and videos is paused for your account. Contact /support if you think this is a mistake. | — |
| `media.pay_link` | Tap to pay {price}. We start as soon as the payment arrives. | 💳 URL button · ✖️ `media.cancel` (§7.2) |
| `media.progress.queued` | Paid ✅ You're #{pos} in line, about {eta}. | — (`paid_via='payme'`) |
| `media.progress.queued_free` | Accepted ✅ You're #{pos} in line, about {eta}. | — (`beta` / `credit`) |
| `media.progress.rendering` | Creating… about {minutes} min left. | — |
| `media.image.delivered` (caption) | Made with AI by @bayram_uzbot. | 🔁 `media.again` · ✨ `create.more` |
| `media.failed.refunded` | Sorry — this one failed. We've added 1 {kind} credit to your balance; use it any time. | 🔁 `media.use_credit` — opens a fresh compose for that SKU with the credit pre-selected at the quote |
| `media.failed.beta` | Sorry — this one failed. It was a free beta request; you can try again for free. | 🔁 `media.again` |

`🔁 media.again` pre-fills the prompt and aspect in a new compose; **photos are not reused**
(uploads are deleted after delivery, O16) — the compose text says so. A re-roll is a new paid
request (O13).

### 2.4 Video

#### 2.4.1 State diagram

```
VideoOrder.compose ─✅─► (row frozen: state=drafting; media_prescreen: L0 + L1 on the prompt, L2 on photos)
                          │ refused → media.refused (✏️ / ✖️)
                          ▼
                     VideoOrder.aspect ─► VideoOrder.tier* ─► VideoOrder.voice
                                                              ├─🔇 none ──────────────────────────────────────────────┐
                                                              ├─🗣 AI, my text ─► VideoOrder.voice_gender ─► VideoOrder.voice_text ─┤
                                                              ├─🤖 AI writes ─► VideoOrder.voice_gender ─► (media_script job) ─┐    │
                                                              │        VideoOrder.script_review ◄─────────────────────────────┘    │
                                                              │          [✅ use | ✏️ edit → voice_text (gender kept) | 🔄 ≤2] ─────┤
                                                              └─🎙 my voice ─► VideoOrder.voice_note (≤5 s, else reject) ─────────┤
                                                                                                                               ▼
                                (row → screening after the LAST voice step; media_screen: full L0–L2 incl. final narration_text)
                                                               ─► VideoOrder.quote ─► pay ─► [TTS ∥ render] ─► mux ─► output screen ─► deliver
```

`*` `VideoOrder.tier` is shown only when ≥2 tiers are offered to this user; with only Standard
enabled (now) it is skipped and the quote names the tier.

- **Freeze at ✅ Done** into a pre-quote state `drafting` (covered by the partial unique index and
  by the same purge as `screening`), so the script writer and every later stage reference a
  `job_id` and **only ever see a prompt that has passed L0/L1** — the prompt never travels in ARQ
  job arguments. `media_prescreen` screens the prompt and uploads; the voice steps then write
  `voice_mode`, `voice_gender` and `narration_text` onto the row (pre-screen state only, guarded by
  `WHERE state='drafting'`).
- **`media_screen` always runs after the last voice step** and screens the final
  `narration_text` at L1 whether or not it already passed L3 — a script the user edited after L3,
  or typed text, is screened as spoken. Test: an edited script containing a denylisted term is
  refused at L1.
- **GPU-reserved check** (§4.5) runs at ✅ Done (reserved → `media.busy`, no row created) and again
  when the quote is computed (reserved → the row goes to `cancelled`, tray → `media.busy`).
  *As built (M4.R):* `media_screen` cancels a video row in that case, with no 🔁, and hands its
  inputs to `media_cleanup`; an image keeps the §2.3.3 busy tray with 🔁.
- **Back map** (⬅️ `media.back`): aspect → compose; tier → aspect; voice → tier, or aspect when the
  tier screen is skipped; voice_text / voice_note / voice_gender → voice; script_review → voice.
  Going back to compose from aspect sets the `drafting` row to `cancelled` (a later ✅ Done freezes a
  new one). **Every video screen carries ✖️ `media.cancel`** as well as ⬅️.
- **Wrong input per state:** text in `voice_note` → `media.voice_note.wrong_type`; a voice note in
  `voice_text` → `media.voice.enter_text` re-prompt; anything in `voice`, `voice_gender`,
  `script_review` → `media.use_buttons`.

#### 2.4.2 Voice screens

| Key | en | Buttons |
| --- | --- | --- |
| `media.video.compose` | Describe the video (what happens, the style). You can attach up to {max} photos — they're combined into the opening frame. | tray as §2.3.3 |
| `media.video.tier` | Standard: ready in about {eta_std}, {price_std}. Fast: about {eta_fast}, {price_fast}. | 🐢 `media.tier.standard` · ⚡ `media.tier.fast` |
| `media.voice.pick` | Add a voice? The clip is {seconds} seconds, so about {words} words fit. | 🔇 `media.voice.none` · 🗣 `media.voice.ai_mine` · 🤖 `media.voice.ai_llm` · 🎙 `media.voice.own` |
| `media.voice.enter_text` | Type what the voice should say (up to {words} words). | ⬅️ `media.back` · ✖️ |
| `media.voice.too_long` | That's too long to say in {seconds} seconds — please keep it to about {words} words. | — |
| `media.voice.gender` | Which voice? | 👩 `media.voice.female` · 👨 `media.voice.male` |
| `media.voice.script_wait` | Writing a line for you… | — |
| `media.voice.script_review` | Suggested line: «{script}» | ✅ `media.voice.use` · ✏️ `media.voice.edit` · 🔄 `media.voice.another` (≤2) |
| `media.voice.send_note` | Record a voice message of up to {seconds} seconds. | ⬅️ · ✖️ |
| `media.voice_note.too_long` | That voice message is {dur} s — please record up to {seconds} s. ({dur} to one decimal) | 🎙 `media.voice.record_again` → `VideoOrder.voice_note` |
| `media.voice_note.wrong_type` | Please send a voice message (hold the 🎤 button). | — |
| `media.video.quote` | Video · {seconds} s · {aspect} · {tier} · voice: {voice_mode} · {price} · ready in about {eta}. | as image quote |
| `media.video.delivered` (caption) | Made with AI by @bayram_uzbot. | 🔁 · ✨ |

- Length budget (O14): whitespace tokens after NFC + apostrophe normalisation (D10 layer), capped
  by **per-language** `narration_max_words_{lang}` and `narration_max_chars_{lang}` — starting
  points uz ≤8 words / ~60 chars, ru ≤10 / ~70, en ≤12 / ~80, all under the owner's ~12-word
  ceiling, calibrated in the M4.4 listening test so text accepted before payment can actually be
  spoken in 5 s. The `{words}` in `media.voice.pick`, `enter_text` and `too_long` is the
  per-language value. The same budget applies to LLM-written scripts (§5.5).
- Voice note: only `F.voice` (OGG/Opus). The handler rejects `message.voice.duration >
  narration_max_seconds` **before any row exists** (O14) — but Telegram reports whole seconds, so a
  5.9 s note passes here; the authoritative check is ffprobe in `media_screen` (§5.4), which
  refuses **before payment** above `narration_max_seconds + 0.25 s`. Stored as a `file_id` in the
  draft.
- "AI writes" runs `media_script(job_id, n)` in the worker (§5.5) against the `drafting` row's
  pre-screened prompt: the handler enqueues and returns; the job edits the message. ≤2
  regenerations per draft (`media_script_max_regens`); each counts against the screening budget
  (§6.4 L0).

*As built (M4.1):* ✅ Done freezes the `drafting` row (a placeholder 9:16 aspect, Standard SKU and
price) and enqueues `media_prescreen`, which records `screen_decision='allow'` on the draft and draws
the shape screen on the tray — or refuses it (`rejected`, struck as at the screen), or answers
`media.busy` with 🔁 (the decision `unavailable`, so the sweep leaves it to the customer; a prescreen
whose enqueue was lost has no decision and the sweep re-drives it). Every later choice stays in the FSM
draft until the last voice step, which writes aspect, tier, SKU, price, `voice_mode`, `voice_gender`,
`narration_text` and the voice note's Telegram ids onto the row **in the statement that moves it
`drafting → screening`** (`MediaDesk.finalize_video`), and only for a draft the prescreen allowed; that
statement clears the prescreen's verdict, so `media_screen` judges the whole request again. After a
typed line or a voice note the "checking" message is a new one under it and becomes the row's tray.
🤖 "AI writes" is built on the bot side (enqueue `media_script(job_id, n)`, `script_review` with ✅ / ✏️
/ 🔄 ≤ `media_script_max_regens`, the keyboard the writer will draw) but **not drawn** until M4.3
registers the writer (`BUILT_VOICE_MODES`). The tier screen shows each tier that is offered, priced and
not paused; with Fast flagged off it is skipped. A voice note ffprobe measures above the clip + 0.25 s
sends the row **back to `drafting`** (a pre-pay move; its prescreen verdict restored, the note's row and
object deleted) with 🎙 record again, rather than refusing the whole request — the customer re-records
without retyping the prompt. Budgets and the clip length are `BAYRAM_NARRATION_*`; the worker re-checks
the budget as a backstop (`screen_caps`).

### 2.5 Who sees what (beta and flags)

`media_offered(kind, tier, user)` =
`is_<sku>_offered` **and** not `media:paused:<sku>` **and** (rail is live-paid **or**
(`media_beta_enabled` **and** `user.telegram_id ∈ media_beta_allowlist`)).

**Live-paid** = `checkout_provider == "payme"` **and** `credits_enforced` **and not
`payme_is_sandbox`** (`config.py:898`, default `True`). Sandbox money is not money, so the Payme
sandbox counts as *not* live-paid: media stays allowlist-only there (O9: "until Payme
production"). Admin telegram ids are listed explicitly in `BAYRAM_MEDIA_BETA_ALLOWLIST` (no
implicit "all admins" — the bot does not know panel roles). Non-allowlisted users during beta see
the relabelled ✨ button and go straight to songs.

- **Beta ends at live-paid.** 🎁 is offered only while the rail is not live-paid; 💳 only when it
  is. Boot warns (and the admin health card shows red) when `MEDIA_BETA_ENABLED` is true on a
  live-paid rail — the flag then has no effect.
- **Server-side re-check.** The 🎁, 🎟 and 💳 handlers and `media_start` re-evaluate
  `media_offered(...)`, the allowlist and the rail **at press / run time**; a rendered button is
  never proof of entitlement.
- **Beta failures mint nothing.** A failed `paid_via='beta'` job is offered a free re-run
  (`media.failed.beta`) but writes **no** ledger credit, so no beta failure becomes a durable
  credit spendable after launch.

### 2.6 Abandonment and cancellation

- FSM compose abandoned → nothing in the DB (image: no row until aspect pick; video: a `drafting`
  row, abandoned by `media_sweep` after `media_quote_ttl_s` like any pre-pay row).
- Rows in `drafting`/`screening`/`quoted` older than `media_quote_ttl_s` (24 h) → `media_sweep`
  sets `abandoned`; `media_cleanup` deletes inputs (objects + rows) and nulls text.
- Rows in `awaiting_payment` are abandoned **only when their Payme intent has reached EXPIRED**
  (`payme_intent_ttl_s`, 12 h from opening, `config.py:910`) plus a 10-minute grace — never on a
  separate clock that could disagree with the intent.
- ✖️ before payment → `cancelled`, same purge. From `awaiting_payment` (✖️ on the pay-link message,
  or `/cancel`): allowed while the intent has **no Payme transaction yet** — the intent is marked
  cancelled so `CheckPerformTransaction`/`CreateTransaction` refuse it; once Payme has created a
  transaction (money in flight) the tap answers `media.cancel_too_late` ("Your payment is being
  processed…"). **No cancel after payment** (the gateway has no per-job cancel, §4.2).
- **Late settlement** (money arrived for a row that is no longer `awaiting_payment`): the Perform
  arm never changes that row (§7.2 step 3); the receipt is written and a `late_settlement` credit is
  granted outside the money commit, and the user is told. There is **no revival** — abandoning a
  row has already purged its inputs.
- `/cancel` with an open media job: pre-payment → cancels it (`media.cancelled`); paid → answers
  `media.cancel_too_late` instead of `wizard.cancelled` (`order_in_flight` reads only
  `ORDER_ID_KEY`, which media never sets).

---

## 3. Architecture

### 3.1 Placement

| Layer | New modules (under `src/bayram/`) |
| --- | --- |
| Bot | `bot/handlers/media/{__init__,compose,image,video,voice}.py`; `bot/handlers/terms.py` (**registered inside `onboarding.build_router()`, above `NotOnboarded`**, §2.1); `bot/middlewares/terms_gate.py`; `bot/media_draft.py`; states in `bot/states.py`; `MediaCB`, `TermsCB` in `bot/callbacks.py`; media routers registered after `support`/`navigation`, before `submitting`/`fallback` (`bot/handlers/__init__.py:218-244`), wrapped in `only_in_private`; post-freeze media callbacks carry no state filter (§2) |
| Domain | `media/contracts.py` (`MediaRequest`, `MediaCapabilities`, `JobHandle`, `JobStatus`, `MediaVerdict`), `media/service.py` (freeze draft, quote, state transitions), `media/composite.py` (§4.4), `media/mux.py` (§5.6), `media/sizes.py` |
| Providers | `providers/media/{factory,local_gateway,higgsfield,fal,fake}.py`; `providers/tts/gemini.py` + `providers/tts/key_pool.py`; `providers/stt/gateway_whisper.py` |
| Moderation | `moderation/{contracts,guard_gateway,denylist,layers,strikes}.py` |
| Runtime | `runtime/media_jobs.py` (stage jobs), `runtime/gpu_lock.py`, `runtime/media_sweep.py`, `runtime/workspace_sweep.py`; registered in `build_kit_worker_settings` (`runtime/jobs.py:769-1000`) |
| DB | `db/models/media_*.py`, `db/models/terms_acceptance.py`, `db/media.py` (repository), purge arms in `db/purge.py`, `/forget` arm beside `credit_erasure.py` |
| Admin | `admin/routers/media_jobs.py`, `admin/routers/media_flags.py`, `db/admin/media_jobs.py`, `admin-dashboard/src/features/media/` |

The existing worker process hosts everything; no fifth systemd unit.

### 3.2 Data model

Three revisions: **`0030` terms** (ships with M1), **`0031` media** (M2) and **`0032`
moderation_reviews** (M3). **`0029` is already taken** by `add_acquisition_source` on
`feat/capture-start-payload` (`down_revision="0028"`), which lands with M0.4; `0030` therefore
has `down_revision="0029"`. *As built:* a fourth, **`0033` media hold records** (M3.R), adds
`media_outputs.deleted_at` and `media_jobs.legal_hold_decision`/`legal_hold_decided_at`/
`csam_cleared_at` (§6.4, §6.7). All run as the owner role and are copied to the host by hand (§0.1).
Every migration PR's acceptance includes **`alembic heads` returns exactly one head**.

#### 3.2.1 `0030` — `terms_acceptances`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `telegram_user_id` | bigint **NULL**, idx | set on accept; nulled by `/forget` anonymisation (the UNIQUE below tolerates NULLs) |
| `terms_version` | varchar(32) NOT NULL | |
| `privacy_version` | varchar(32) NOT NULL | |
| `language` | varchar(8) NOT NULL | language the text was shown in |
| `accepted_at` | timestamptz NOT NULL | |
| `source` | varchar(16) | `onboarding` \| `gate` |
| UNIQUE | (`telegram_user_id`, `terms_version`, `privacy_version`) | idempotent accept |

Retention: third route (anonymised on `/forget`, bounded by a 400-day-after-account-deletion
cutoff), like `topup_purchases` (`BROADCAST_SPEC §6.2` pattern). Reason: proof of acceptance is
the lawful-basis record.

#### 3.2.2 `0031` — media tables

**`media_jobs`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | also the D17-style resume marker and the ARQ job-id seed |
| `user_id` | uuid FK users ON DELETE CASCADE | |
| `telegram_user_id` | bigint idx | |
| `kind` | varchar(16) | `image` \| `video` |
| `tier` | varchar(16) NULL | `standard` \| `fast` (video) |
| `sku` | varchar(32) | `image` \| `video_standard` \| `video_fast` |
| `state` | varchar(24) | §3.3 (`drafting` is video-only, §2.4.1) |
| `chat_id` | bigint | where the worker edits and delivers |
| `tray_message_id`, `status_message_id` | integer NULL | the tray the worker turns into quote/refusal/busy; the progress message (§3.3 Progress) |
| `content_sha256` | char(64) NULL | hash of prompt + narration + every input `sha256`, written by `media_screen`; `media_start` re-checks it (§2.3.1) |
| `submit_seq`, `oscreen_seq` | smallint NOT NULL DEFAULT 0 | monotonic suffixes for deliberate ARQ re-enqueues (§3.3) |
| `outputs_requested` | smallint CHECK 1..4 | 2 for image, 1 for video |
| `aspect` | varchar(8) | `9:16` \| `1:1` \| `16:9` |
| `params` | jsonb | width, height, length, fps, steps, denoise, seed — **no text** |
| `backend` | varchar(16) NULL | stamped by `media_start`'s latch, as the first submits are enqueued, so every variant renders on one backend: `local` \| `higgsfield` \| `fal` \| `fake` |
| `model_id` | varchar(64) NULL | stamped with `backend` |
| `language` | varchar(8) | |
| `prompt` | varchar(800) NULL | nulled by purge / `/forget` |
| `voice_mode` | varchar(16) | `none` \| `ai_user` \| `ai_llm` \| `own` |
| `voice_gender` | varchar(8) NULL | |
| `narration_text` | varchar(160) NULL | nulled with `prompt` |
| `voice_transcript` | varchar(400) NULL | whisper text of an own note; nulled with `prompt` |
| `text_expires_at` | timestamptz NOT NULL | set at insert to `created_at + quote TTL + 30 d`; moved to terminal + 30 d by the same UPDATE that sets any terminal state |
| `text_purged_at` | timestamptz NULL | |
| `screen_decision` | varchar(8) NULL | `allow` \| `review` \| `block` \| `unavailable` |
| `screen_categories` | jsonb NULL | closed codes only |
| `screen_policy_version` | varchar(32) NULL | |
| `output_decision` | varchar(8) NULL | |
| `output_categories` | jsonb NULL | |
| `price_minor` | integer CHECK ≥ 0 | snapshotted at quote |
| `currency` | char(3) | `UZS` |
| `payment_intent_id` | uuid NULL | no FK (0006/0015/0020/0023 precedent) |
| `paid_via` | varchar(16) NULL | `payme` \| `credit` \| `beta` — **no `stub`** (a media SKU is never charged on the stub rail, §7.2) |
| `render_ready_at`, `audio_ready_at` | timestamptz NULL | fan-in for mux (§3.3) |
| `error_code` | varchar(48) NULL | closed taxonomy |
| `failed_reason` | varchar(256) NULL | `_SAFE_CONTEXT_KEYS` allowlist only (orchestrator.py) |
| `refund_state` | varchar(16) NULL | `due` \| `granted` |
| `forget_requested_at` | timestamptz NULL | §9.3 |
| `created_at`, `updated_at`, `quoted_at`, `paid_at`, `started_at`, `delivered_at` | timestamptz | |

Indexes: `(state, created_at, id)`, `(telegram_user_id, created_at, id)`, `(sku, created_at, id)`,
`(text_expires_at)`. **Partial unique** `(telegram_user_id, kind) WHERE state IN
('drafting','screening','quoted','awaiting_payment','paid','queued','generating','post','held','delivering')`
— one open request per user per kind (§7.6). No code path ever moves a terminal row back into
that set (§7.2 step 3), so the index can never fire inside the Payme money commit; freezing cancels
earlier pre-pay rows first (§2.3.1).

**State guards.** Every state transition after `paid` is a conditional
`UPDATE … WHERE id=:id AND state IN (<expected>)`; rowcount 0 means another path (deadline sweep,
`/forget`, output block) got there first, and the caller becomes a no-op — it releases the GPU lock
and discards any output it holds, and never delivers or refunds.

**`media_inputs`** — `id`, `job_id` FK CASCADE, `ordinal` smallint, `role` varchar(16)
(`photo` \| `voice_note` \| `collage`), `tg_file_id` varchar(256), `tg_file_unique_id` varchar(64),
`storage_key` varchar(512) NULL (null until downloaded), `mime`, `size_bytes`, `sha256` char(64),
`width`, `height`, `duration_ms`, `retention_class` varchar(32) (`media_input` \| `legal_hold`),
`legal_hold_expires_at` NULL, `expires_at` NOT NULL, `deleted_at` NULL. UNIQUE (`job_id`, `role`, `ordinal`); idx `expires_at`.
`expires_at` starts at `created_at + 24 h` (pre-pay backstop) and is **reset on payment** to
`paid_at + the SKU's deadline + the 24 h review SLA`, in the same transaction that moves the job to
`paid`, so a customer who pays late in the quote window keeps their inputs until the job is done.

**`media_outputs`** — `id`, `job_id` FK CASCADE, `role` (`image` \| `video_raw` \| `narration` \|
`video`), `variant` smallint, `storage_key` NOT NULL, `mime`, `size_bytes`, `sha256`,
`width`, `height`, `duration_ms`, `tg_file_id` varchar(256) NULL, `retention_class` varchar(32)
(`media_output` \| `legal_hold`), `legal_hold_expires_at` NULL, `expires_at` NOT NULL, `created_at`. UNIQUE (`job_id`, `role`, `variant`); idx `expires_at`.
`video_raw` and `narration` are intermediates with a 24 h `expires_at`.

**`media_attempts`** (no personal data) — `id`, `job_id` FK SET NULL, `stage` (`screen`,
`script`, `image`, `video`, `tts`, `stt`, `mux`, `output_screen`), `variant`, `provider`,
`model_id`, `remote_id` varchar(128) NULL, `attempt` int, `status` (`submitting` \| `submitted` \|
`succeeded` \| `failed` \| `rejected` \| `ambiguous`), UNIQUE (`job_id`, `stage`, `variant`, `attempt`), `error_code`, `queue_ms`, `run_ms`, `gpu_seconds` NULL,
`cost_usd` numeric NULL, `cost_source` varchar(16), `created_at`, `finished_at`. Cutoff 400 d.

**`media_purchases`** (append-only receipt, like `topup_purchases`) — `id`,
`telegram_user_id` NULL-able (anonymised), `job_id`, `sku`, `amount_minor` CHECK ≥ 0, `currency`,
`provider` (`payme` \| `beta` \| `credit` — **no `stub`**), `reference` (Payme transaction id / ledger
id), `idempotency_key` UNIQUE, `created_at`.

**`media_credit_ledger`** (append-only audit trail of the kind-scoped refund balance) — `id`,
`telegram_user_id`, `sku`, `delta` smallint (±1), `reason` (`generation_failed` \| `output_blocked` \|
`deadline` \| `late_settlement` \| `spent` \| `admin_correction`), `job_id` NULL, `actor`
varchar(64) NULL, `created_at`. **A job refunds at most once, whatever the reason:** partial
unique `(job_id) WHERE delta > 0 AND reason <> 'admin_correction'`, plus partial unique `(job_id)
WHERE reason = 'spent'`. Every refund path first claims `media_jobs.refund_state` NULL → `due` with
a conditional UPDATE, then inserts the ledger row and sets `granted`, so a deadline failure followed
by a late generation failure, or a variant failure followed by an output block, grants one credit.

**`media_credit_balances`** — `(telegram_user_id, sku)` PK, `balance integer NOT NULL CHECK
(balance >= 0)`, `updated_at`. The spendable balance, materialised because `SELECT … FOR UPDATE` is
a verified silent no-op in the SQLite unit suite (`db/credit_sql.py:17`, `db/payme_sql.py:28`,
`models/credit_account.py:15`) and a lock on a `credit_accounts` row that may not exist (deleted
on `/forget`, `credit_erasure.py:307`; absent for a media-only user) locks nothing. **Spend** =
one transaction: `UPDATE media_jobs SET state='paid', paid_via='credit' WHERE id=:id AND
state='quoted'` (rowcount 1) + `UPDATE media_credit_balances SET balance = balance - 1 WHERE
telegram_user_id=? AND sku=? AND balance >= 1` (rowcount 1, the `credit_sql.debit_balance`
pattern) + ledger `−1 spent` + receipt; either rowcount 0 → rollback. **Refund** = upsert `+1` in
the same transaction as the ledger row. The ledger stays the audit trail; a reconciliation test
asserts `balance = SUM(delta)`.

**Alterations:** `payment_intents ADD resume_media_job_id uuid NULL`; `vendor_usage ADD
media_job_id uuid NULL` + idx. `IntentProduct`/`TopupKind` members are VARCHAR — no DDL.

#### 3.2.3 Enumerations (Python only)

`Vendor += local_genai, higgsfield, fal, gemini_tts, gateway_guard`;
`VendorOperation += image_generate, video_generate, safety_classify, speech_synthesis (exists),
transcription (exists)`; `UsageTask += media_screen, media_script, media_image, media_video,
media_tts, media_output_screen`; `AssetKind` unchanged (media does not use `assets`).

#### 3.2.4 Retention, purge, privacy registration

| Object | Clock | Purge predicate (`rows_past_expiry_statements`, `db/purge.py:696`) |
| --- | --- | --- |
| `media_inputs` (photos, voice notes, collage) | **Deleted by `media_cleanup` immediately after delivery**, and on failure/reject/abandon/cancel (O16). `expires_at` backstop: `created_at + 24 h` pre-pay, reset on payment (§3.2.2). | `expires_at < now() AND deleted_at IS NULL AND retention_class <> 'legal_hold'` → delete object + row |
| `media_outputs` `image`/`video` | `retention_media_output_days` (default **30**, Q2) | `expires_at < now() AND retention_class <> 'legal_hold'` → delete object + row (tg_file_id with it) |
| `legal_hold` inputs/outputs (§6.7) | ≤72 h from the block, then deleted or handed over by the escalation owner | a separate `legal_hold_expires_at < now()` arm that deletes and writes an audit row |
| `media_outputs` intermediates | 24 h | same predicate |
| `media_jobs` text (`prompt`, `narration_text`, `voice_transcript`) | `text_expires_at` (insert: `created_at` + quote TTL + 30 d; terminal: terminal + 30 d) | null the three columns, set `text_purged_at` |
| `media_jobs` unpaid terminal rows (`abandoned`, `cancelled`, `rejected`) | 30 d cutoff | delete row (CASCADE) |
| `media_attempts`, `media_purchases`, `media_credit_ledger`, `terms_acceptances` | 400 d cutoff / anonymise on `/forget` | third route |
| `media_credit_balances` | deleted on `/forget` (the ledger keeps the anonymised history) | — |

Registration: `media_jobs`, `media_inputs`, `media_outputs`, `media_credit_balances` → `tables_with_personal_data`
(`tests/test_db/test_privacy_constraints.py:172`); `media_purchases`, `media_credit_ledger`,
`terms_acceptances` → the anonymise-and-cutoff route. Every new model registers on
`Base.metadata` (`test_migrations::test_the_new_table_is_registered_as_well_as_migrated`).
`RetentionClass += MEDIA_INPUT, MEDIA_OUTPUT, LEGAL_HOLD` in `db/retention.py`. Tests: a
`legal_hold` input and output survive `media_cleanup` and both purge predicates; a `rejected` job's
inputs are gone after `media_cleanup`.

### 3.3 Job state machine and stage chain

```
drafting* ─► screening ─► quoted ─► awaiting_payment ─► paid ─► queued ─► generating ─► post ─► delivering ─► delivered
    │            │           │              │                                 │           │
    └► cancelled └► rejected └► cancelled   └► abandoned / cancelled          └───────────┴──► failed ─► (refund_state=due→granted)
       / abandoned                                                                  └► held (output review) ─► delivering | failed
(* video only)
```

**ARQ job ids.** ARQ silently drops an enqueue whose `_job_id` still has a job key or a kept
result (`arq/connections.py:158`; results are kept `queue_result_ttl_s` = 3 600 s,
`config.py:757`). A deterministic id therefore de-duplicates a *duplicate* enqueue, but a
**deliberate re-enqueue must use a new id**: every self-re-enqueue carries a monotonic suffix
persisted on the row (`submit_seq`, `oscreen_seq`) or derived from a tick, and `media_sweep`
always enqueues the **next** suffix, never the last id. Raising `Retry` is not a substitute:
`max_tries` is 5 (`config.py:762`) and a job can wait hours for the GPU. Test (M2.4): a job that
re-enqueues itself actually runs again.

| ARQ job | Trigger | Does | Idempotency |
| --- | --- | --- | --- |
| `media_prescreen(job_id)` | video ✅ Done (bot enqueues) | download photos, L0/L1 on the prompt, L2 (+G8) on photos; edit tray → aspect screen or refusal; row stays `drafting` | `media:{id}:prescreen` |
| `media_screen(job_id)` | image: aspect pick; video: last voice step | download inputs (worker, `bot.get_file` + `download_file`, size checked before and after read, `avatar.py:149-200` pattern) to workspace → storage (`MEDIA_INPUT`), recording `sha256`; **decode every image with Pillow and reject multi-frame images** (animated WebP/APNG/GIF-as-document → `media.compose.unsupported`); collage if needed; L0–L3 (§6) on the **final** prompt, captions, narration and transcript; write `content_sha256`; compute quote & ETA; edit tray → quote \| refusal \| busy | `media:{id}:screen` (a 🔁 on a busy tray, or the sweep, re-screens the same row as `media:{id}:screen:{n}`); conditional `UPDATE … WHERE state='screening'` |
| `media_script(job_id, n)` | "AI writes" | reads the `drafting` row's pre-screened prompt; gateway LLM (§5.5), L3 screen, edit message | `media:{id}:script:{n}` |
| `media_start(job_id)` | settlement (§7.2), credit spend, beta free, `media_sweep` | re-checks `media_offered`, `content_sha256`, `screen_decision='allow'` and policy version; **latch = `UPDATE media_jobs SET state='queued' WHERE id=:id AND state='paid'`** (rowcount 0 → no-op); enqueue `media_submit` per variant (`attempt` fixed as a job argument) and, for AI voice, `media_tts` / for own voice, `media_voice_prepare`. `payment_intents.resumed_at` is stamped for audit only, never read as a gate | `media:{id}:start:{n}` (n from `media_sweep`) + the latch |
| `media_submit(job_id, v, attempt)` | start / retry policy / lock freed | take GPU slot (§3.4) if local; **on entry, if an attempt row for (job, v, attempt) exists in `submitting` with no `remote_id`, never POST: mark it `ambiguous` and reconcile** (local: `GET /queue`; Higgsfield: admin hold). Otherwise insert `media_attempts(status='submitting')` **before** the POST; POST; store `remote_id`, `submitted`; extend the lock; enqueue poll. Not at the queue head → re-enqueue itself with `submit_seq+1`, `_defer_by=15 s` | `media:{id}:submit:{v}:{attempt}:w{submit_seq}` |
| `media_poll(job_id, v)` | self, `_defer_by` 5 s (image) / 15 s (video) | poll status; running → re-enqueue (renews the lock, refreshes progress); succeeded → `media_fetch`; failed/rejected → retry policy; `unknown` → `ambiguous` (§4.2). Only the retry policy, after a **terminal** `failed`/`rejected` attempt, creates attempt N+1 | `media:{id}:poll:{v}:{attempt}:{tick}` |
| `media_fetch(job_id, v)` | poll success | **always releases the GPU lock** (CAS on attempt id); if the job is already terminal → discard the result, stop. Else stream result to workspace with `max_bytes`, ffprobe, `put_file` to storage, `media_outputs` row; image: conditional fan-in (below); video: set `render_ready_at`, try fan-in | `media:{id}:fetch:{v}:{attempt}` (the attempt is in the id: a fetch that failed hands the variant to attempt N+1, whose fetch must not be dropped as a duplicate) |
| `media_tts(job_id)` / `media_voice_prepare(job_id)` | start (parallel to render) | §5; reads only the stored, screened input (never re-downloads by `file_id`); store `narration` output; set `audio_ready_at`; try fan-in | `media:{id}:tts` |
| image fan-in | each variant reaching a terminal state (succeeded **or** failed after retries) | conditional UPDATE counting terminal variants; the one that brings the count to `outputs_requested` and finds ≥1 success moves `generating → post` and enqueues `media_output_screen`; 0 successes → `failed` + refund | the conditional UPDATE |
| video fan-in | whichever of render/audio finishes second | `UPDATE … SET state='post' WHERE render_ready_at IS NOT NULL AND (voice_mode='none' OR audio_ready_at IS NOT NULL) AND state='generating'`; rowcount 1 → enqueue `media_mux` | the conditional UPDATE |
| `media_mux(job_id)` | fan-in | ffmpeg (§5.6) → `video` output; no-op unless `state='post'` | `media:{id}:mux` |
| `media_output_screen(job_id)` | outputs ready | L4 (§6); allow → deliver; review → `held`; block → `failed` + refund; unavailable → re-enqueue with `oscreen_seq+1` every 2 min for ≤30 min, then `held` | `media:{id}:oscreen:{oscreen_seq}` |
| `media_deliver(job_id)` | allow / human release | conditional `post`/`held` → `delivering`; `sendMediaGroup` (2 photos, JPEG q92) / `sendVideo` (≤50 MB, `supports_streaming`, w/h/duration from ffprobe; else `sendDocument`); store `tg_file_id`; state `delivered`; enqueue cleanup | `media:{id}:deliver`; `delivered_at IS NULL` claim + state guard before send |
| `media_cleanup(job_id)` | delivered / failed / **rejected** / cancelled / abandoned | delete input objects + rows, intermediates, workspace dir; request gateway-side delete (G6, §9.2) — **skipping every `legal_hold` row** | idempotent deletes |
| `media_sweep` (cron, 5 min) | — | (a) abandon stale pre-pay rows (§2.6; `awaiting_payment` only after intent EXPIRED + grace); (b) **`paid` rows older than 2 min → enqueue `media_start` with the next suffix**; (c) `queued`/`generating` rows with no live attempt → enqueue `media_submit` with the next `submit_seq`; (d) fail jobs past deadline (§3.5) via the state-guarded path; (e) GPU queue hygiene (§3.4) | — |
| `workspace_sweep` (cron, hourly) | — | delete `var/workspace/media/*` and legacy `var/workspace/{order_id}` dirs > 24 h whose job/order is terminal | — |

**Screened bytes only.** Generation, collage, TTS input and mux read **only the storage copy
written by `media_screen`**, verified against `media_inputs.sha256` before use; nothing
re-downloads by Telegram `file_id` or re-encodes an input between screening and use.

**Late results.** A job failed by the deadline sweep, a TTS failure or `/forget` may still have a
render running (no per-job cancel). Its later poll/fetch releases the lock and discards the output;
it never delivers or fans in, and never grants a second credit (§3.2.2). Test: the deadline fires,
then the late success delivers nothing and exactly one credit exists.

Retries: `call_with_retry`/`RetryPolicy` (`pipeline/retry.py`) for transport; generation failure
retried `media_max_attempts` (2) per variant on the same backend; **fallback to another backend
only on a pre-submit error** (unavailable, quota, rate-limited, 502-without-job_id); never after an
ambiguous submit. Media jobs **do not park the chat** and never touch `ORDER_ID_KEY`.

**Progress** is DB-driven, not `ProgressReporter`: that reporter and `TelegramProgressSink`
(`pipeline/events.py:45-130`, `bot/progress.py`) are in-process, event-driven objects with "no
timer", and the media pipeline is a chain of separate ARQ jobs. `media_start` sends one status
message and stores `status_message_id`; `media_submit` (while waiting for the lock) and `media_poll`
re-render the frame from the row, editing only when queue rank or the rounded-minute ETA changes
and at most every 60 s. The render frame shows "about {minutes} min left" from `started_at` + the
moving-average `run_ms`. The queued wording is chosen by `paid_via` (`media.progress.queued` vs
`queued_free`). Delivery is a new message so it notifies.

### 3.4 GPU slot (local backend)

- One outstanding `/generate` on the gateway from bayram: Redis `media:gpu:lock` =
  `SET NX PX 120000` holding the `media_attempts.id`. The short TTL covers the window between
  acquire and POST; **only after the POST returns a `remote_id`** is it extended to the render
  timeout, and each `media_poll` renews it. **Renew and release are a Lua compare-and-set on the
  attempt id**, so a late poll or fetch from an old attempt can neither extend nor delete another
  attempt's lock.
- Fair order: Redis ZSET `media:gpu:queue`, member **`{job_id}:{variant}`** (so an image's two
  variants both queue), scored by `paid_at` then variant. Only the head may take the lock; others
  re-enqueue `media_submit` with the next `submit_seq` and `_defer_by=15 s`. The member is
  **removed in the same code path that sets any terminal state** (attempt or job). `media_sweep`
  drops members whose job is terminal and releases a lock held by a `submitting` attempt older than
  5 minutes (marking it `ambiguous` for reconciliation). Queue position and ETA for the customer =
  rank × moving-average run time per model (from `media_attempts.run_ms`) + the gateway's own
  `GET /queue` depth (non-bayram jobs).
- **Customer jobs pre-empt marketing (O11)** means *queue priority*, not killing a running render:
  `/interrupt` is global (§4.2). Requires the gateway change G5 (§6.5): a `priority` field so a
  bayram job jumps ahead of queued non-bayram jobs. Until G5 exists, the owner's marketing scripts
  must yield (check `GET /queue` for `client=bayram` before submitting) — documented in the M2
  runbook.
- Image variants 0 and 1 are two sequential gateway jobs; video is one.

### 3.5 Deadlines and settlement grace

| Deadline | Default | On expiry |
| --- | --- | --- |
| `media_image_deadline_s` (paid → delivered) | 45 min | fail + refund credit |
| `media_video_standard_deadline_s` | 4 h | fail + refund credit |
| `media_video_fast_deadline_s` | 30 min | fail + refund credit (Higgsfield: only after status confirms terminal or 2 h ambiguity) |
| render timeout (counted from gateway `running` only) | image 5 min, video 40 min | attempt failed → retry |
| quote TTL (`drafting`/`screening`/`quoted`) | 24 h | abandoned |
| `awaiting_payment` | the Payme intent's own expiry (`payme_intent_ttl_s`, 12 h) + 10 min | abandoned |

Deadlines run from `paid_at`. Media is **not** gated by `BAYRAM_AUTO_RENDER_ON_PAYMENT` (the
song-render rollback flag): a paid media job has no manual ▶️ start, so tying it to that flag would
turn every sale into a deadline credit. To stop media, use the per-SKU pause (§4.5), which stops
new quotes and lets paid jobs finish.

Media jobs are not on the song credit-debit path, so the stale-debit sweep (grace 4 550 s) never
sees them; `media_sweep` is their only reaper. The ETA shown at quote must fit inside the deadline,
else the quote screen shows `media.busy` instead (NFR-20: never take money for what we cannot
deliver).

### 3.6 Storage and bytes

- `Storage.put_file(key, src: Path)` — streaming copy + atomic rename, same key confinement as
  `put` (`storage.py:122-149`). Fetches stream (`httpx` `aiter_bytes`) to
  `var/workspace/media/{job_id}/` with a hard `max_bytes` (image 20 MB, video 200 MB).
- Key function beside `archive_key`: `media_key(job_id, role, filename) →
  media/{job_id}/{in|out}/{filename}`; filenames match `^[A-Za-z0-9._-]{1,128}$`
  (`db/purge.py:833`). Same archive root, so the admin's read-only mount sees it unchanged.
- Bytes go to the gateway as base64 in the JSON body. **Never a Telegram file URL** (it embeds the
  bot token).
- EXIF stripped and orientation applied on every input before it leaves the host.

---

## 4. Provider abstraction

### 4.1 Protocol

In `media/contracts.py` beside `MusicProvider` (`contracts.py:~1170`). Async; returns `Result`;
never raises across the boundary (`errors.py:232-310` taxonomy).

```python
class MediaGenProvider(Protocol):
    name: str
    def capabilities(self) -> MediaCapabilities: ...
    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]: ...
    async def submit(self, req: MediaRequest, *, correlation_key: str,
                     webhook_url: str | None, timeout_s: float) -> Result[JobHandle]: ...
    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        ...  # QUEUED | RUNNING | SUCCEEDED | FAILED | REJECTED_CONTENT | UNKNOWN
    async def fetch(self, handle: JobHandle, index: int, dest: Path, *,
                    max_bytes: int, timeout_s: float) -> Result[GeneratedMedia]: ...
    async def cancel(self, handle: JobHandle) -> Result[bool]: ...   # Ok(False) = not cancellable
    async def health(self) -> Result[ProviderHealth]: ...            # contracts.py:1078

@dataclass(frozen=True)
class MediaCapabilities:
    kinds: frozenset[Literal["image", "video"]]
    max_reference_images: int              # local: 1
    native_audio: bool                     # we always request silent
    durations_s: tuple[float, ...]
    aspects: frozenset[str]
    cancel: Literal["none", "queued_only", "any"]
    estimate: Literal["exact", "table", "none"]
    webhook: bool
    idempotent_submit: bool                # local: False, higgsfield: False
    provider_moderation: bool              # local: False
    output_retention_s: int | None

@dataclass(frozen=True)
class MediaRequest:
    kind: Literal["image", "video"]
    model_key: str                         # from the allowlist, never user input
    prompt: str                            # screened
    refs: tuple[Path, ...]                 # already composited when caps require
    width: int; height: int
    length_frames: int | None; fps: int | None
    steps: int; seed: int; denoise: float | None
```

Errors map to the closed taxonomy: `ProviderUnavailableError` (pre-submit, fall-back-able),
`ProviderQuotaExhaustedError` (Higgsfield 402/403), `ProviderRateLimitedError` (Higgsfield 400
concurrency, gateway busy), `ContentRejectedError` (→ MODERATION terminal class,
`contracts.py:345`), `ProviderAmbiguousError` (timeout after POST; never retried automatically).

### 4.2 `LocalGatewayProvider`

- **Base URL** `genai_base_url` (HTTPS through the tunnel, §9.1); auth **header only** with
  `genai_api_key` — the provider must never put the key in a query string, asserted by a test on
  the built request.
- **Model allowlist** in code: `LOCAL_MODEL_ALLOWLIST = frozenset({"flux2", "wan"})`; config
  `genai_image_model="flux2"`, `genai_video_model="wan"` must be members (boot validation).
  `zootopia`, `storybook`, `storybook_wan`, `hunyuan` and anything else are refused before any
  request. A test asserts the payload's `model` ∈ allowlist for every code path.
- **Payload is built from a closed dict**, never merged with user data (`additionalProperties:true`
  would forward anything): `{model, prompt, width, height, steps, seed, image?, denoise?}` for
  images; `{model, prompt, width, height, steps, seed, image?, length: 81, fps: 16}` for video —
  **`length`, not `frames`**. `width`/`height` always explicit.
- **Inputs** as `data:image/jpeg;base64,…`; one image only; multi-photo → collage first (§4.4).
- **Deadlines:** queue wait and render time tracked separately; render timeout counts only while
  status is `running`; transient poll errors ("Network is unreachable", 5xx) retried with backoff
  up to the job deadline.
- **`{status:"unknown"}` is terminal** → attempt `ambiguous`. Local reconciliation: check
  `GET /queue` for the remote id; absent → one automatic resubmit is allowed (local cost is GPU
  time only), logged; a second `unknown` fails the job with refund.
- **502 with no `job_id`** = validation failure, non-retryable, pre-submit.
- **Never call `/interrupt`** (global). `cancel()` returns `Ok(False)`.
- Every request carries a `client: "bayram"` tag and `priority: "customer"` once G5 exists.
- A contract smoke test (`make gateway-contract`, network, **not** in `pytest` `testpaths`) diffs
  the live `/openapi.json` against the fields we send.

### 4.3 `HiggsfieldProvider` and `FalProvider` (stubs now, M6)

| | Higgsfield | fal |
| --- | --- | --- |
| Auth | `Authorization: Key <id>:<secret>` (`higgsfield_api_key_id`, `higgsfield_api_secret`) | `Authorization: Key <fal_api_key>` |
| Submit | `POST /<model-path>` (Kling 3.0 std I2V default for Fast) | `queue.fal.run/<model>` |
| Inputs | upload via `/files/generate-upload-url` (1 h) — our bytes, not our URLs | fal storage upload |
| Status | poll `/requests/{id}/status`; webhook only as a trigger to re-poll (unsigned) | `status_url` |
| Audio | **always `sound:"off"` / `generate_audio:false`** — we mux our own | same |
| Cancel | queued only | `cancel_url` |
| Estimate | `POST /estimate/<path>` before quote; **per-SKU hard ceilings** covering every variant and every retry of one request: `image_max_cost_usd` (both images × attempts) and `video_fast_max_cost_usd` | static table, same ceilings |
| Ambiguous POST | **never auto-repeat**; attempt `ambiguous` → job `held` for admin reconcile, refund credit if unresolved in 2 h | same |
| Refs | per model (§ research 3); caps drive routing | per model |

**Margin check.** At boot and at every quote, the selected backend's estimated **per-request** cost
(outputs × expected attempts, from `/estimate` or the static table) converted at the admin FX rate
must be ≤ `media_max_cost_share` (default 0.5) of the SKU's `*_price_minor` net of the ~2% Payme
fee; otherwise boot refuses to offer that SKU on that backend, and a quote shows `media.busy`. The
per-request figures are `RESEARCH-image-video-pipeline` §6: at 5 000 UZS, Nano Banana Pro and
Higgsfield's documented image price are not viable.

Both implement the protocol behind `providers/media/factory.py`; `FakeMediaProvider` (deterministic
PNG/MP4 fixtures) is the default in tests (`use_fake_providers`, `config.py:217`).

### 4.4 Collage (1-ref backends)

`media/composite.py` (Pillow): inputs EXIF-transposed and stripped → canvas at the job's target
size → layout by count: 1 = fit; 2 = side-by-side (16:9, 1:1) or stacked (9:16); 3 = one large +
two small; 4 = 2×2; 2 px neutral gutters, letterboxed on a blurred copy of the first photo. Output
JPEG q90 as a `collage` input (also screened, L2). When
`capabilities().max_reference_images ≥ len(refs)` the originals go natively and no collage is made.
The compose copy tells video users photos are combined into the opening frame (residual quality
risk: Q10).

*As built (M6.2):* the limit is per kind (`MediaCapabilities.reference_limits`, read through
`max_references`): Higgsfield reports its configured models' limits — Kling 3.0 I2V 1, Soul 0,
Seedance 2.0 R2V (`seedance_2_0_r2v`) 9 — so with a multi-ref video model the photos go natively
as a list of uploaded URLs and no collage is made. `media_screen` builds and screens the collage
whenever **any** backend on the SKU's route (primary, then fallback, §4.5) needs one, and
`media_submit` sends the originals to a backend that takes that many and the collage otherwise.

### 4.5 Feature flags, overrides, kill switches

| Setting (env, `BAYRAM_` prefix) | Type / default |
| --- | --- |
| `IS_IMAGE_OFFERED`, `IS_VIDEO_STANDARD_OFFERED`, `IS_VIDEO_FAST_OFFERED` | bool, `false` |
| `IMAGE_BACKEND` | `Literal["local","higgsfield","fal","fake"]`, `local` |
| `VIDEO_STANDARD_BACKEND` | same Literal, `local` |
| `VIDEO_FAST_BACKEND` | same Literal, `higgsfield` |
| `MEDIA_BETA_ENABLED`, `MEDIA_BETA_ALLOWLIST` | bool `false`; CSV of Telegram ids |

Redis operator overrides (one writer each — admin panel or `bayram.tools.media` CLI — one reader,
the `payme.pause` / `admin/rail_switch.py` pattern):

| Key | Effect |
| --- | --- |
| `media:backend:<sku>` | overrides the env backend for new submits (must be in the Literal; unknown → ignored + alert) |
| `media:paused:<sku>` | kill switch: SKU hidden from the picker; open quotes answer `media.busy`; paid jobs continue |
| `media:gpu:reserved_until` | ISO timestamp; while in the future, every SKU whose effective backend is `local` refuses at Done/quote with `media.busy` (O11); paid jobs already queued continue |

*As built (M6.2):* an optional `IMAGE_FALLBACK_BACKEND`, `VIDEO_STANDARD_FALLBACK_BACKEND`,
`VIDEO_FAST_FALLBACK_BACKEND` (same Literal, empty = none) is the backend a job moves to under
§3.3's rule — a pre-submit `ProviderUnavailableError`, `ProviderQuotaExhaustedError`,
`ProviderRateLimitedError` or gateway 502-without-job_id, never an ambiguous submit, never our own
refusal of the request (a reference the model cannot take, the cost ceiling) — and only while
**nothing of the job was ever posted** (no attempt with a remote id, in flight, ambiguous or
finished), so one job renders on one backend and every poll asks the backend holding its id. The
move re-stamps `backend` + `model_id` under the row lock the attempt insert also takes; the
variant's next attempt (N+1) goes to the fallback, and the job leaves or joins the GPU queue with
it. A fallback for an offered SKU is held to every boot check its backend is, margin included, at
that SKU's price; a `fake` fallback is refused in production like a `fake` backend.

The effective backend is stamped on `media_jobs.backend` + `model_id` at submit, so the admin panel
reads the row and never mirrors the flag. **Boot refusals** (in `refuse_an_unsafe_checkout_rail`,
§7.4, whatever the environment unless `use_fake_providers` is true, i.e. tests): any media SKU
offered with `media_moderator == "fake"`; any offered SKU whose effective backend is `fake`. In
addition `settings.is_production` (`config.py:990`, which checks `environment == "prod"` — the
value is spelled `prod`, never `production`) refuses `fake` for any media setting outright. Boot
tests cover both.

---

## 5. Voice

### 5.1 `GeminiTtsProvider` (`gemini-3.8-flash-tts`)

- Implements the existing TTS provider contract on `providers/tts/transport.py`, added as route
  `gemini_tts` in `LanguageRoutingTts` (`providers/tts/router.py:55,71`, `BAYRAM_TTS_ROUTES`) —
  songs keep their routes; narration uses a separate route table `BAYRAM_NARRATION_ROUTES`
  in the existing `parse_routes` format (`providers/tts/router.py:71`, `Language` values):
  default `uz_latn=gemini_tts,uz_cyrl=gemini_tts,ru=gemini_tts,en=gemini_tts`, fallback
  `elevenlabs_tts`.
- New request type `NarrationRequest {text, language, gender, style}` (not `SpeechRequest`, which
  requires `persona_id`/`name_submitted`, `contracts.py:1045-1058`).
- Call: `POST https://generativelanguage.googleapis.com/v1beta/interactions`, header
  `x-goog-api-key: <pool key>`, body with `model: gemini-3.8-flash-tts`, the text as the sole user
  input, `generation_config.speech_config` naming the house voice, and the delivery style in
  `speech_metadata.style` — **never in the text** (it would be spoken). Exact field shape pinned by
  a recorded-fixture test and re-checked against the docs page at M4 build time.
- Response: unary WAV 24 kHz mono 16-bit. Content refusal (SAFETY / PROHIBITED_CONTENT) →
  `ContentRejectedError` → job fails, refund credit, never retried.
- House voices: `gemini_tts_voice_female`, `gemini_tts_voice_male` (two of the 30 prebuilt voices,
  chosen by the owner in the M4 listening test). uz text in Cyrillic is transliterated to Latin
  before synthesis. **Uzbek is listed, not proven**: M4 acceptance includes a 20-line listening
  test; if it fails, `uz` routes to ElevenLabs.
- Metering: `vendor_usage` with `Vendor.gemini_tts`, audio tokens (25/s) and the date-effective
  price (doubles 2027-01-01).

### 5.2 Key pool (owner decision O8)

`providers/tts/key_pool.py`:

- Keys from `gemini_tts_api_keys` (CSV secret, `NoDecode` + `_split_csv`), identified everywhere by
  `key_ref = sha256(key)[:8]` — the key itself is never logged, stored or shown.
- Selection: round-robin via Redis `INCR tts:gemini:rr` mod N, skipping keys in cooldown.
- Per-key state in Redis hash `tts:gemini:key:{key_ref}`: `cooldown_until`, `consecutive_429`,
  `consecutive_5xx`, `last_ok_at`, `disabled_reason`.
- 429 / RESOURCE_EXHAUSTED → cooldown = `Retry-After` or 30 s × 2^n (cap 15 min), try next key.
  401/403 (invalid, suspended, billing) → disabled 24 h + admin alert (key_ref only). 5xx/timeout →
  try next key once. Content refusal is not a key fault.
- All keys cooling/disabled, or `gemini_tts_enabled=false` → **ElevenLabs** (existing provider,
  house voice ids per gender). ElevenLabs failing → job fails with refund credit (O13: paid for
  voice, voice failed). Q11 asks whether to deliver silent + credit instead.
- **No paid-tier gate.** Pool keys may be free-tier and are used for every job, beta and paying
  customers alike; the owner accepted that Google may train on narration text (answer to Q17,
  2026-09-24; D23). The Privacy notice (Appendix A) discloses it.
- Health: admin card lists key_ref, state, last OK, 24 h success/429 counts.

*As built (M4.2):* narration is its own protocol, `NarrationProvider.narrate(NarrationRequest)`,
not a route inside the song `LanguageRoutingTts`: `TtsProvider.synthesize` takes a
`SpeechRequest`, which needs a persona and a name. `NarrationRouter` (in `providers/tts/router.py`
beside the song router, same `parse_routes` table format) sends each language to its provider
and hands **any** failure except a content refusal to the fallback. A content refusal is never
passed to the fallback. `ElevenLabsTts.narrate` is the fallback, with two house voice ids by
gender. The wire shape was checked against the speech-generation docs page on 2026-09-25:
`input[0].content[0]` is the text part, and the style is a `speech_metadata` *annotation* on it.
`response_format` asks for `audio/wav` at 24 kHz, `speech_config` is a list naming the voice,
and the audio arrives base64 in `steps[].content[].data`. Google answers a bad key with
**400 `API_KEY_INVALID`**, not 401, so that response also disables the key. A 400 or 200 that
carries `SAFETY`/`PROHIBITED_CONTENT` is the refusal. `gemini_tts_api_keys` is a plain CSV string
(`Settings.gemini_tts_key_list` splits it), so every secret field keeps `""` as its unset
value. The secret-shape test now also matches `_keys`. When Redis is unreadable, the pool
rotates with an in-process counter and treats every key as usable, which costs at most one
extra 429. An unset house voice (Q14) sends that gender to ElevenLabs.
`runtime.providers.build_narration_provider` assembles all of it. M4.3 consumes it.

### 5.3 Length cap

`narration_max_seconds = 5` (clip length) and the per-language word/char budget (§2.4.2, ceiling
12 words), enforced at input **before payment**, so text we accept is text we can speak. After
synthesis: ffprobe duration `d`; `d ≤ 5.0` → pad with silence to clip length; `5.0 < d ≤ 5.75` →
`atempo` ≤ 1.15; else re-synthesise once with style "brisk"; still over → **trim at the clip
length with a 250 ms fade-out** and deliver (never fail a paid job for an over-long line). Every
trim is counted per language so the M4.4 budgets can be tightened (Q11 note).

### 5.4 Own voice notes

- Handler rejects `duration > narration_max_seconds` pre-row (§2.4) — whole seconds only.
- `media_screen` downloads the OGG and re-checks duration with ffprobe (Telegram's value is
  client-reported and integral): **above `narration_max_seconds + 0.25 s` → refused before
  payment**, tray → `media.voice_note.too_long` with a 🎙 record-again button. Only a note inside
  that 0.25 s tolerance is trimmed (with a fade) at render time.
- It then sends the note to the gateway whisper endpoint (G3, §6.5) → `voice_transcript` for L1.
  Whisper hallucinates on Uzbek (rejected #13), so the transcript is trusted only when it looks
  like real transcription. **Refuse (as `review`, i.e. blocked before payment)** when any of:
  - the transcript is empty, or `no_speech_prob` is high while `silencedetect` finds speech;
  - mean segment `avg_logprob` < −1.0, or any segment `compression_ratio` > 2.4;
  - the detected `language` ∉ {uz, ru, en};
  - fewer than ~1 word per 1.5 s of voiced audio (by `silencedetect`) — music, moaning or other
    non-speech that whisper fills with filler text.
  M4.1 tests cover each case. Residual (§11 R11): tone and non-verbal sound are unscreened.
- *As built (M4.1):* whisper is called with **no** language (a forced language is echoed back and
  would make the language rule vacuous); `no_speech_prob` counts as high at ≥ 0.6 (whisper's own
  threshold) when silencedetect (−35 dB, 0.3 s) finds ≥ 0.5 s of speech; the word-rate rule is
  words < ⌊voiced s / 1.5⌋. An untrusted transcript refuses the request as `review` with
  `error_code='voice_untrusted'` and no strike; so does one longer than `voice_transcript`'s 400
  characters, which is never truncated, since its unscreened tail would still be delivered
  (M4.R). A trusted one is stored in `voice_transcript` and screened by G1 as `transcript`. The note is stored as sent (OGG/Opus, `audio/ogg`) with its
  ffprobe `duration_ms`.
- At render time `media_voice_prepare` reads the screened storage copy (sha256-verified): ffmpeg
  decode → `loudnorm` I=−16 LUFS → mono 48 kHz → pad (or trim within tolerance) to clip length →
  AAC. The note is muxed as-is otherwise: **no cloning, no voice conversion**.

### 5.5 LLM script writer

- Gateway `/v1/chat/completions`, model `genai_script_model` (default `qwen3.8:27b-q4_K_M`, in a
  separate LLM allowlist; `:cloud` models refused). Strict JSON schema `{ "script": string }`
  (`providers/llm/json_schema.py:73`), UI language, within the per-language word/char budget
(§2.4.2), uz Latin with U+02BB, no names of
  real people, no brands.
- The user's prompt is passed as a JSON-escaped field, never interpolated into instructions.
- Output → D10 normalisation → word/char caps → **L3 re-screen**.
- Gateway unavailable or busy > 20 s → fallback to the D5 LLM stack (`llm_provider`, Gemini 3.7
  Flash on the paid tier) through the existing client.

*As built (M4.3):* `media_script(job_id, n)` acts only on a `drafting` video whose prescreen
allowed it, and reads the prompt from the row. The user message is one `json.dumps` object
`{video_description, language, max_words, max_chars}`; the system prompt names
`video_description` as material, never instructions. The gateway client (`media/script_writer.py`)
sends `genai_script_model` with the key in `X-API-Key` plus the Access pair and a strict
`{script}` schema; a `:cloud` model is refused by `Settings` and again by the client. Any gateway
error, or no answer within `BAYRAM_GENAI_SCRIPT_TIMEOUT_S` (20 s), asks the D5 `llm_provider` and
then its documented fallback, each once; a line that fails D10 + the budget also moves on to the
next provider. Each line counts once against the screening budget (`{job}:script:{n}`), and a
job writes exactly one line. An L3 `block`/`review` line is never shown; like an unavailable
guard, no writer at all, or a strike store that cannot be read, it leaves no line and draws
`media.voice.script_failed` with ✏️ (and 🔄 while any are left), no ✅ and never `media.busy`.
The next line is the customer's own 🔄, so a refused line costs a regeneration and a screening
(§6.4 L3). *(M4.R: M4.3 wrote a second line inside the job, which spent neither.)* An L3 block
is not a strike: the words are ours. Nor is a TTS refusal of an unedited 🤖 line
(`voice_mode='ai_llm'`); words typed after ✏️ go to screening as `ai_user` and are the
customer's. ⬅️ out of the 🤖 branch sets the draft back to `voice_mode='none'`, so a line still
being written neither lands on the row nor redraws the tray. With the writer registered, 🤖 is
drawn (`BUILT_VOICE_MODES` is all four modes).

### 5.6 Mux

`media/mux.py`, subprocess via `asyncio.create_subprocess_exec` (ffmpeg is already a host
dependency, `runtime/startup.py verify_host`):

```
ffmpeg -i video_raw.mp4 -i narration.wav -map 0:v:0 -map 1:a:0 \
       -c:v copy -c:a aac -b:a 128k -af apad -t <video_duration> -movflags +faststart video.mp4
```

Silent videos (`voice_mode=none`) skip the mux and are re-wrapped with `-movflags +faststart`.
ffprobe verifies geometry and duration before output screening.

*As built (M4.3), `media/mux.py` behind a `VideoTools` seam:*

- **Fetch.** ffprobe must find a video stream with a geometry and a positive duration. H.264
  `yuv420p` is re-wrapped `+faststart` with no audio track; anything else is re-encoded (libx264,
  CRF 20). The result is the `video_raw` output (24 h), with `width`/`height`/`duration_ms`, and
  sets `render_ready_at`. Each fetch run stores under its own object key, and a run whose row
  loses deletes its object, so a racing re-drive never replaces the bytes the winning row hashes.
- **Voice, beside the render.** `media_tts` speaks `narration_text` in the chosen house voice. A
  take longer than clip × 1.15 is asked for once more with style `brisk`, and the shorter take is
  kept (§5.3). The take is stored with the MIME the vendor answered with and a matching suffix
  (the §5.2 ElevenLabs fallback is `audio/mpeg`, `.mp3`). A vendor content refusal fails the job
  (`narration_refused`) with a refund and two strikes (§6.4 L5), except for an unedited 🤖 line
  (§5.5). Any other failure is retried three times and then fails the job
  (`narration_failed`) with a refund. `media_voice_prepare` reads the screened note (streamed from
  storage, sha256-checked) and writes loudnorm I=−16 mono 48 kHz WAV. Both store a 24 h
  `narration` output, set `audio_ready_at` and try the fan-in.
- **Mux.** The voice is padded (`apad`), or sped up with `atempo` ≤ 1.15 (AI voice only), or
  trimmed with a 250 ms fade. It is cut at the render's own ffprobe duration. Every `atempo` or
  trim is logged with its language (Q11). The result must match the render's geometry and be
  within 0.15 s of its length; otherwise, or when ffmpeg fails three times, the job fails
  (`mux_failed`) with a refund.
- **L4 and delivery.** L4 screens the first frame, one frame a second, and the last frame (≤ 8)
  as `output_frame`. Delivery is `sendVideo` with `supports_streaming` and the row's
  width/height/duration; above 50 MB it is `sendDocument`. The cloud Bot API caps a bot's upload
  at 50 MB for both methods, so the document fallback only helps on a local Bot API server. A
  5 s 720p clip is a few MB. An upload Telegram refuses as too large is final, not retried.
- **Sweep.** It re-drives a stalled video's render and a voice that never arrived (after
  `STALE_HEARTBEAT`). A voice run holds a lease (`media:{job}:voice:lease`, one stage timeout)
  from when it starts, and the sweep leaves a leased voice alone, so a slow narration does not
  get a second paid run beside it. A voice still queued behind a backlog has no lease yet and
  can still be re-driven. It also re-drives the mux of a `post` video that has no clip yet.

---

## 6. Moderation

### 6.1 My take on the local-LLM idea

Screening every request on your own GPU is the right instinct: no per-call cost, no data leaving
the box, and you control the policy. Asking a general chat model like qwen3.8 "is this allowed,
yes or no" is the weakest way to do it — it can be talked round by text inside the prompt it is
judging, it gives no score to set a threshold on, a quantised model answers differently on
different runs, and it refuses on words rather than meaning (we already lost a paid song over a
beer mention). Purpose-trained guards fix most of that, which is why the plan uses exactly the
ones you agreed to install: Qwen3Guard-Gen-4B for text, ShieldGemma 2 for images, whisper to turn
voice notes into text. Two things the prompt-only idea would have missed, and this plan covers:
the uploaded **photos** and the **generated output** carry more risk than the words, so both are
screened; and if a guard is down we stop selling rather than guess. The residual gap you should
know about: none of these models can tell reliably whether a real, identifiable person — or a
child — is in a photo, and by your decision there is no face logic, so that risk is carried by the
Terms, by a zero-tolerance nudity rule on every image, and by the sexual/violence classifiers
(§6.4, §11 R3). Text *inside* a photo (a slogan, a slur, a flag's caption) is read by an OCR/caption
step (G8) and screened like any other text.

### 6.2 `Moderator` protocol

```python
class MediaModerator(Protocol):
    async def screen_text(self, items: Sequence[TextItem], *, policy: PolicyVersion) -> Result[MediaVerdict]: ...
    async def screen_images(self, items: Sequence[ImageItem], *, policy: PolicyVersion) -> Result[MediaVerdict]: ...
    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[Transcript]: ...
```

Implementations: `GatewayGuardModerator` (G1–G3, G8), `FakeModerator` (tests), selectable by
`media_moderator: Literal["gateway","fake"]`, with `media_moderator_base_url` (defaults to
`genai_base_url`) so the guards can be pointed at a hosted endpoint serving the same contract (D24
fallback) without a new implementation. `fake` with any media SKU offered refuses to boot unless
`use_fake_providers` is true (§4.5).

### 6.3 Verdict schema

```python
class MediaVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["allow", "review", "block", "unavailable"]   # no default
    categories: tuple[CategoryCode, ...]                           # closed StrEnum; unknown → parse error → block
    scores: Mapping[CategoryCode, float]
    subject: Literal["prompt", "narration", "transcript", "script", "upload", "collage",
                     "upload_text", "output_image", "output_frame", "output_text"]
    model_id: str
    policy_version: str
```

The decision is computed **in our code** (`moderation/policy.py`, versioned); the guard's own
output is an input, not the answer. How depends on the guard:

- **Text (G1, Qwen3Guard-Gen-4B) is a generative classifier** — it emits
  `Safety: Safe|Controversial|Unsafe` and `Categories: …`, not per-category scores. Mapping:
  `Unsafe` → `block`; `Controversial` → `review` (a block before payment); `Safe` → `allow`; each
  Qwen3Guard category maps to a `CategoryCode` by a closed table (unknown → parse error → block).
  Scores are optional: used only if G1 returns label-token logprobs.
- **Images (G2, ShieldGemma 2)** return per-policy probabilities; the decision is per-category
  thresholds.
- **Invariant:** for a subject that needs a guard, a result with the `safety` label missing, or
  with neither `categories` nor `scores` where the guard type requires them (empty `scores` for
  G2), is **`unavailable` — fail closed, never `allow`**. M3.1 tests: a G1 response with `safety`
  present and `scores:{}` is decided from the label, not allowed by default; `safety` missing →
  `unavailable`; a G2 response with `scores:{}` → `unavailable`.

Parse failure, timeout, HTTP error → `unavailable`. Only closed codes are stored (`screen_categories`),
never guard prose. `CategoryCode`: `sexual`, `sexual_minors`, `violence`, `self_harm`,
`hate`, `extremism`, `politics_officials`, `religion`, `illegal_drugs`, `weapons`, `jailbreak`,
`pii`, `copyright_character`, `other_unsafe`.

### 6.4 Layers

| Layer | When | What | On hit |
| --- | --- | --- | --- |
| **L0** | handler + `media_screen`, pre-pay | length/word caps; NFKC + homoglyph + invisible-char normalisation; denylist extended from `pipeline/moderation.py:53-58` with uz-Latn/uz-Cyrl/ru terms, officials and public figures, brands/characters (incl. Disney names); per-user screening budget `media_screen_daily_budget` (10/day; a probing oracle otherwise); strike check | block (no guard call) |
| **L1** | `media_screen`, pre-pay | Qwen3Guard-Gen-4B (G1) on prompt, captions, narration text, voice transcript — each a separate item | per §6.3 |
| **L2** | `media_screen`, pre-pay | ShieldGemma 2 (G2) on every upload and on the collage (policies incl. the custom minor policy below); **G8** OCR + short VLM caption of every upload, fed to G1 as `upload_text` items | per §6.3 |
| **L3** | `media_script`, pre-pay | L1 on LLM-written script | block → regenerate (counts against regens) |
| **L4** | `media_output_screen`, pre-delivery | G2 + G8 (→ G1 `output_text`) on both output images; video: first, last and 1 fps frames (ffmpeg `fps=1`, ≤8 frames); narration text was screened at L1/L3 | allow → deliver; review → `held` + queue; block → fail + refund credit. **A block on either image variant fails the whole request**: nothing is delivered, one refund credit, 2 strikes (Q3's "deliver one + credit" covers generation failures only, never our own output block) |
| **L5** | async | provider refusals (Higgsfield `nsfw`, Gemini SAFETY) → `ContentRejectedError` | fail + refund credit + strike |
| **L6** | human | review queue (§6.6) | release / confirm block / appeal |

Pre-pay `review` is treated as `block` for the customer (`media.refused`, non-specific per SEC-3)
and logged; no human wait before payment. Pre-pay `unavailable` → `media.busy` (**fail closed**,
O10). Post-pay `unavailable` → retry every 2 min for 30 min, then `held`.

**Where the youth signal comes from.** None of the guards has a minor category: Qwen3Guard's
classes are Violent, Non-violent Illegal Acts, Sexual Content, PII, Suicide & Self-Harm, Unethical
Acts, Politically Sensitive, Copyright, Jailbreak; ShieldGemma 2's stock policies are sexually
explicit, dangerous and violence. So `youth_signal` is produced **in our code** from:

1. an **L0 youth-term lexicon** in uz-Latn, uz-Cyrl, ru and en (e.g. bola, qizcha, oʻgʻil bola,
   oʻquvchi, maktab, ребёнок, девочка, школьница, подросток, child, kid, teen, schoolgirl, loli…),
   applied after normalisation to the prompt, captions, transcript, script and every G8 OCR/caption
   text;
2. a **ShieldGemma 2 custom policy** "sexualised depiction of a minor", added to G2's `policies`
   and mapped to `sexual_minors` — **uncalibrated**, logged, treated as a signal not a detector;
3. the **G8 VLM caption** (qwen3-vl) screened by G1 and matched against the lexicon.

**Zero-tolerance nudity.** Because age cannot be judged from an image, `sexual` on **any** image —
upload, collage, output image or frame — is a block at a low fixed threshold
(`media_sexual_image_block_p`, default 0.2, recalibrated in M3.3), regardless of any youth signal.

**Hard rule:** `sexual_minors` above its (low) threshold, or `sexual` (any subject) together with a
`youth_signal`, → block, no retry, strike ×3, CSAM escalation (§6.7).

**Strikes** (`moderation/strikes.py`, Redis + `media_jobs` history): a pre-pay block = 1 strike;
L4/L5 block = 2; 3 strikes in 7 days → `media:suspended:{tg}` for 7 days
(`media.refused.suspended`); a CSAM-class block → suspended until an admin clears it.

*As built (M3.1):* a pre-pay `review` refuses but does not strike (nothing was judged unsafe);
strikes are keyed by job + layer, so a redelivered stage adds none. The suspension check and
the screening budget run first in `media_screen`, before any download; the budget counts a
**job** once (a 🔁 on a busy tray is not a second screening), and a refusal for either is not a
strike. A CSAM-class suspension is lifted only by `python -m bayram.tools.media unsuspend <tg>`.
The hard rule is applied in `media_screen` and `media_output_screen` over the union of every
guard's codes with the youth signal of the request's own words, so "schoolgirl" in the prompt
and `sexual` on a photo meet even though no single guard saw both. G2's non-sexual thresholds
(`moderation/policy.py`: `dangerous` and `violence` review 0.35 / block 0.6; the custom minor
policy blocks at 0.1) are placeholders until M3.3's calibration.

*As built (M3.R):* a length/word-cap failure is refused (`screen_caps`) and **not** struck —
the bot's tray enforces the same 3–800 characters and ≤160 words, so it is only a backstop. The
bot also reads the suspension at ✅ and at the shape pick, so a suspended account freezes no row;
the denylist stays the worker's, where a hit spends the screening budget and strikes (answering
it in the bot, free and unmetered, would be an oracle). Denylist stems that open ordinary words
are written as closed forms (`trump`/`трамп(а|у|ом|е)` not *trumpet*/*трамплин*; `qatl` not
*qatlama*; `marvel's`/`marvel studios`, not *marvelous*). A CSAM-class suspension is written
before the strikes and before sealing, and is also **durable**: a `csam_blocked` job with
`csam_cleared_at` NULL refuses the account at the screen gate even after Redis lost the key;
`tools.media unsuspend` clears both. G1 receives the request's `lang_hint` (`uz`/`ru`/`en`),
G3 keeps the worst segment's `compression_ratio` for M4's §5.4 check, and an output screen with
no outputs is `unavailable`, never `allow`. A hosted guard endpoint gets its own
`BAYRAM_MEDIA_MODERATOR_*` credentials; the gateway's key and Access token go only to the
gateway's host.

### 6.5 Gateway-side work the owner does on the 5090

| # | Endpoint / change | Contract |
| --- | --- | --- |
| **G1** | `POST /v1/moderate/text` → Qwen3Guard-Gen-4B | req `{items:[{id, content}], lang_hint}`; resp `{model, results:[{id, safety:"safe"\|"controversial"\|"unsafe", categories:[…], logprobs?:{…}}], latency_ms}` — `safety` required, `logprobs` optional (§6.3 mapping). Interim acceptable: the model exposed as `qwen3guard-gen-4b` on `/v1/chat/completions`, parsed strictly by us (`Safety: …` / `Categories: …`). |
| **G2** | `POST /v1/moderate/image` → ShieldGemma 2 (4B) | req `{items:[{id, data_b64}], policies:["sexually_explicit","dangerous","violence", {"custom":"sexualised depiction of a minor"}]}`; resp `{model, results:[{id, scores:{policy: p_yes}}]}`. Images processed in memory, **never written to disk**. |
| **G3** | `POST /v1/audio/transcriptions` (whisper large-v3; exists — confirm contract) | multipart OGG; resp must include `text`, `language`, per-segment `no_speech_prob`/`avg_logprob`. |
| **G4** | `GET /v1/moderate/health` | resident models, VRAM held, p95 latency. |
| **G5** | `priority` + `client` fields on `/generate` and in `GET /queue` | a `priority:"customer"` job is placed ahead of queued non-customer jobs; a running job is never interrupted. |
| **G6** | `DELETE /result/{id}` and `DELETE /inputs/{hash}` (or a scheduled sweeper, §9.2) | removes a job's inputs and outputs. |
| **G7** | No request-body logging on G1–G3, G8; guard routes bypass the ComfyUI generation queue | guards must answer in ≤10 s p95 while Wan renders. |
| **G8** | `POST /v1/moderate/describe` → PaddleOCR(-VL) text + a ≤30-word qwen3-vl caption (both already on the box) | req `{items:[{id, data_b64}]}`; resp `{results:[{id, ocr_text, caption}]}`; in memory only. Both strings go to G1 as `upload_text` / `output_text` and through the L0 lexicon — this is what catches extremist slogans, slurs, insults to officials and captioned flags/symbols that ShieldGemma's three policies cannot see. |

VRAM: both guards resident (~8 GB each in bf16, less quantised) compete with Wan. The owner
measures G7's latency during a Wan render in M3; if it misses, guards pin to reserved VRAM or Wan
runs with offloading (Q4).

### 6.6 Review queue

Built from the unmigrated ADMIN_PANEL_PLAN §5.9 design (permissions and audit actions already
exist, `admin/permissions.py:106,125-126`, `db/enums.py:390-391`): table
`moderation_reviews(id, job_id, subject, categories, created_at, decided_at, decision, actor,
reason_code)`, shipped in `0032` with M3. Sources: L4 `review` holds, customer appeals from
`media.refused` via `/support`, and a 2% sampled audit of allowed outputs. SLA 24 h; an unreviewed
hold at 24 h → fail + refund credit. Optional: post a masked card to a `bot_chats` moderation group.

*As built (M3.2):* `0032` adds `source`, `due_at` (created + 24 h), `actor_id` and `applied_at` to
the columns above; a NULL `decision` is pending and a partial unique index allows one pending
review per job. The worker opens the review in the same transaction as the move to `held` —
source `output_review` for an L4 `review`, `guard_unavailable` for the 30-minute give-up. The
panel (`/api/media/reviews`, `/api/media-jobs/{id}/hold`, all on `media.moderate`) only
**records** a decision — `released` or `blocked` — and asks the worker to apply it
(`media_review_apply`): a release marks the output allowed and delivers it; a block fails the job
with one SKU-scoped credit attributed `admin:{name}` on the ledger (none for beta) and two strikes.
The refund's step-up is `moderation.decide` scoped to the review id, with the INTENT audit row
(`moderation.refund`) in the decision's transaction and the OUTCOME row
(`moderation.refund.outcome`) after the enqueue; a release is `moderation.approve`, a hold
`moderation.hold`, all against `subject_type="media_job"`. An operator may hold only a `post` job
whose output screen allowed it. `media_sweep` decides a pending review `expired` at `due_at`
(→ fail + one credit, no strike), re-drives a decision nobody applied after 2 minutes, and delivers
a released job whose delivery enqueue was lost. Not built yet: the appeal and 2% sample sources,
the moderation-group card, and output reveal for reviewers (M5's `media_outputs` reveal subject) —
until then a reviewer decides from the category codes. A paid-backend `ambiguous_submit` hold
(§4.3) opens no review; it is M6's reconcile path.

*As built (M3.R):* releasing a `guard_unavailable` hold does **not** mark the output allowed —
no guard and no human saw it — it moves the job back to `post` and runs the output screen again;
only a guard's `allow` delivers, and a guard still down holds it again under a fresh review.
Until M6, `media_sweep` fails a `held` job that no pending or unapplied review covers (an
`ambiguous_submit` hold, or one from before `0032`) two hours after its last move, with one
credit (§4.3's 2 h rule), so it cannot occupy the one-open-request index for ever.

### 6.7 CSAM and escalation

Named escalation owner: the owner (SCOPE §6.9) until someone else is named (Q8). **Q8 is a blocker
for leaving beta** (D25 trigger), not only for M3.

On a CSAM-class block (hard rule, §6.4):

- The offending input/output rows get `retention_class='legal_hold'` **in the same transaction as
  the block verdict**, so `media_cleanup`, the G6 gateway delete and both purge predicates skip them
  (§3.2.4). M3.1 test: a `sexual_minors` block leaves both objects and rows in place after cleanup
  and purge.
- **Never revealable in the admin panel.** The admin sees job id, category codes, sha256 and time
  only; no reveal subject exists for held bytes and no step-up unlocks them.
- Bytes are **encrypted at rest with a key held only by the named escalation owner** and are
  accessed out of band. *As built (M3.1):* each held object is sealed in place to the owner's
  X25519 public key (`BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT`; ephemeral ECDH + HKDF-SHA256 +
  AES-256-GCM, `moderation/legal_hold.py`) right after the hold commits, and again by
  `media_cleanup` if the stage died in between. The host holds the public key only; the owner
  generates the pair and opens an object with `python -m bayram.tools.legal_hold`. The rows keep
  the `sha256` of the original bytes. Boot refuses an offered SKU without a valid key.
- **Deadline:** the escalation owner records a reporting decision within **72 h**
  (`legal_hold_expires_at`); at expiry the bytes are deleted (hash + metadata kept) unless the
  decision was to hand them to the authorities, which is logged. *As built (M3.R, `0033`):*
  the decision is `python -m bayram.tools.media legal-hold <job_id> --handover|--delete`
  (`media_jobs.legal_hold_decision`, logged at WARNING); `handover` makes the purge skip the
  job's held objects, `delete` brings their clock forward. At expiry the purge deletes the
  **object** and keeps the row (`deleted_at` set, `sha256`, size, times), logging the hash; the
  job row stays with it.
- The owner confirmed this exception to O16 on 2026-09-24 (Q16). Counsel may still advise
  delete-only (hash + metadata); that is the R12 switch. Risk: §11 R12.

Everything else follows O16.

### 6.8 Separate fix: the song moderator (M0)

1. `ModerationPayload`: remove the `is_allowed=True` default, `extra='forbid'`, unknown → block.
2. User text passed in a JSON-escaped field, not inside quoted instructions
   (`pipeline/prompts.py:246-258`).
3. Transport error → retry ×2 → mark the order for review and refund on the existing path instead
   of allowing (fail closed for songs too; songs are post-payment, so "closed" means refund, not
   silence).
4. Tests: a `{"allowed": false}` reply without `is_allowed` blocks; a transport error never allows.

---

## 7. Payments

### 7.1 SKUs and prices

| SKU | `Product` / `IntentProduct` | Setting | Default |
| --- | --- | --- | --- |
| Image (2 outputs) | `IMAGE` | `image_price_minor` | **500_000** (5 000 UZS) |
| Video Standard | `VIDEO_STANDARD` | `video_standard_price_minor` | **2_500_000** (25 000 UZS, owner 2026-09-24) |
| Video Fast | `VIDEO_FAST` | `video_fast_price_minor` | `None` |

Standard is **25 000 UZS** (owner, 2026-09-24): cash cost ~0 but ~17.5 GPU-min and a long wait, priced
above the 15 000 song. Fast stays unset until M6; it should sit above Standard — **35 000–45 000 UZS**
recommended (Kling 3.0 std ≈ 10 800 UZS at 1.5 attempts; confirm with `/estimate`). Prices are integer tiyin,
hand-set per currency (LR-7, LR-9); no FX.

### 7.2 Flow

1. `media_screen` passes and capability block clears (backend healthy, not paused, GPU not
   reserved for local, ETA ≤ deadline, margin check §4.3) → state `quoted`, price snapshotted.
2. 💳 (offered only on a live-paid rail, §2.5) → the handler calls **`CheckoutProvider.charge`**
   with a `PurchaseRequest` carrying a new `resume_media_job_id` (passed through by
   `PaymeCheckoutProvider.charge` exactly as it passes `resume_order_id` today), product = the
   media SKU, amount = `price_minor`, idempotency key `f"{sku}:{tg}:{job.id}"`. Going through
   `charge` keeps the operator pause switch (`payme/provider.py` → `_is_rail_paused`) and the link
   builder (`build_checkout_link`) that a direct `open_intent` call would skip. The pay handler
   **refuses a media SKU outright when `checkout_provider == "stub"`** — `StubCheckoutProvider.charge`
   returns `is_paid=True` with no money moved (`checkout.py:320-370`), and on the stub rail
   `build_checkout` returns no opener at all (`runtime/container.py`). Row → `awaiting_payment`; the
   pay-link message carries ✖️ Cancel (§2.6).
3. **Payme checks.** `CheckPerformTransaction` and `CreateTransaction` refuse with an account error
   (−31050..−31099) when the linked media job is no longer `awaiting_payment` or its intent was
   cancelled. `PerformTransaction` → `db/payme.py _write_sale` `match` arm for media SKUs, in the
   **same commit**: insert `media_purchases`, then a conditional
   `UPDATE media_jobs SET state='paid', paid_via='payme', paid_at=now() WHERE id=:id AND
   state='awaiting_payment'` and reset the inputs' `expires_at` (§3.2.2). **It never touches a
   terminal row.** Rowcount 0 (a race past step 3's checks) → the receipt still commits; the
   settlement job grants a `late_settlement` credit outside the money commit.
4. **Settlement job** (`payme_jobs.notify_payment_settled`): **branch on `resume_media_job_id`
   before `plan_resume`** — for a media intent `resume_order_id` is None, and `plan_resume` would
   otherwise answer `no_marker` and show the song 🎬 keyboard for any parked song draft. The media
   branch enqueues `media_start` and announces with media copy. `media_start`'s latch is the job
   row (`state='paid' → 'queued'`), **not** the one-shot `resumed_at` claim, so a burned claim, a
   failed enqueue, a blocked send or a redelivery that returns early at `notified_at IS NOT NULL`
   cannot strand a paid job: `media_sweep` re-enqueues `media_start` for any row still `paid` after
   2 minutes. Not gated by `BAYRAM_AUTO_RENDER_ON_PAYMENT` (§3.5).
5. Nothing billable (GPU, Higgsfield, TTS) runs before step 3 (FR-62, LR-30). Pre-pay screening
   and script writing use guard/LLM compute only and are budgeted (§6.4 L0).

🎟 **credit spend**: one transaction, as specified under `media_credit_balances` (§3.2.2) —
conditional job move `quoted → paid` + conditional balance debit + ledger `−1 spent` +
`media_purchases(provider='credit', amount 0)` → `media_start`. 🎁 **beta**: the same conditional
job move with `paid_via='beta'` + `media_purchases(provider='beta', amount 0)`, allowed only after
the server-side re-check of §2.5.

Tests (M2.2 / M5.1): a media 💳 press on the stub rail writes no receipt and does not start the
job; Perform on a `cancelled` job commits the receipt, leaves the row `cancelled` and yields
exactly one `late_settlement` credit; the claim is burned and the enqueue fails, and the sweep
still starts the job exactly once; a settled media intent never shows the song keyboard.

### 7.3 Fail-closed match sites (M5, before any real sale)

| Site | Today | Change |
| --- | --- | --- |
| `db/payme.py:1058` `_write_sale` | SINGLE else plan; raises `StorageError` **inside PerformTransaction** | exhaustive `match`; media arm writes `media_purchases`; unknown → `assert_never` at type level + tested |
| `payme_jobs.py:359` `_announcement` and `notify_payment_settled` | announces as a plan; `plan_resume` runs first | branch on `resume_media_job_id` **before** `plan_resume`; media arm → `media_start`, media copy |
| `bot/handlers/checkout.py:529` (amount), `:619`, `:905` (idempotency prefix) | binary | per-SKU `match` |
| `payme/provider.py:201` (`charge`) | binary; passes `resume_order_id` | `match`; also passes `resume_media_job_id` |
| `CheckPerformTransaction` / `CreateTransaction` | no media notion | media arm refuses (−31050..−31099) unless the job is `awaiting_payment` |
| `admin/schemas/billing.py:1030, 1280`; `admin/routers/billing.py:871` | binary | `match`; media rows labelled by SKU |
| `checkout.py:89-101` `Product`; `db/enums.py:201-262` `IntentProduct`/`TopupKind` | 2 members | add 3; a test asserts every member has an arm in each site |

*As built (M5.1):* `Product` and `IntentProduct` gained `image`, `video_standard`, `video_fast`;
**`TopupKind` did not** — it names `topup_purchases` rows and a media sale is never one. Every site
above is an exhaustive `match` with `assert_never`; the song checkout refuses a media SKU before a key
is minted. 💳 is `media.payment.SqlMediaCharge` (charge → `quoted`/`awaiting_payment` →
`awaiting_payment` with `payment_intent_id`); ✖️ on the pay link or `/cancel` moves the intent
`pending → cancelled` (the same row the rail's hold takes, so one of the two wins) and then the job,
and answers `media.cancel_too_late` once a transaction holds it. Check/Create answer `-31052` for a
job no longer awaiting payment and `-31050` for an intent naming no job. The settlement counts media
receipts on the receipts side of the three-way invariant. The gateway reads no `Settings`, so the
Perform arm resets the uploads' clock with the shipped deadlines (`DEFAULT_SKU_DEADLINES`). The §8
reveal is `GET /api/media-outputs/{id}/stream` on the existing `reveal.media.read` + `reveal.media`
pair (no separate `media.reveal` permission yet), subject type `media_output`, image/png, image/jpeg
and video/mp4 in their own allowlist so the song route stays audio-only.

### 7.4 Boot refusal

Extend `refuse_an_unsafe_checkout_rail` (`main.py:117`) and the worker's startup equivalent:

```
if any(is_<sku>_offered):
    live_paid = (settings.checkout_provider == "payme" and settings.credits_enforced
                 and not settings.payme_is_sandbox)
    beta_ok   = settings.media_beta_enabled and len(settings.media_beta_allowlist) > 0
    if not (live_paid or beta_ok): refuse to boot ("media offered on a free rail")
    if not live_paid: media is offered to the allowlist only (§2.5)
    if live_paid and settings.media_beta_enabled: warn ("beta flag has no effect on a live-paid rail")
    if settings.media_moderator == "fake" and not settings.use_fake_providers: refuse to boot
for each offered sku: price is not None or refuse to boot; margin check (§4.3) or refuse
```

On the stub rail (and the Payme sandbox) a non-beta user can never reach a quote, and no user sees
💳; a beta job is recorded as `provider='beta'` — `stub` is not a valid value — so finance can
exclude it. Boot tests: payme + sandbox + media offered with no beta allowlist refuses; fake
moderator with media offered refuses. *As built (M5.3):* every offered SKU with an empty price refuses in
both the bot and the worker, and media offered on a **live-paid** rail with the Terms + Privacy
gate off (no `BAYRAM_TERMS_VERSION` pair) refuses too — once anyone can order, the acceptance is the
whole real-person mitigation (O4, §11 R3); the beta may still run before M1.3. The owner's go-live
checklist is runbook `12-media-gateway §8`; `.env.example` lists the go-live flag set. Default `DEFAULT_ENTITLEMENT_POLICY`
is never used in media code (`resolve_entitlement_policy(settings)` only).

### 7.5 Refunds (O13)

| Event | Refund |
| --- | --- |
| Generation failed after retries / deadline exceeded / ambiguous Higgsfield unresolved 2 h | +1 credit, same SKU |
| L4 output block / review hold expired / provider content refusal after payment | +1 credit, same SKU |
| Image: 1 of 2 variants **failed to generate** after retries | deliver the good one **and** +1 image credit (Q3) |
| Image: either variant blocked by our L4 output screen | deliver nothing; +1 image credit (one refund, not two) |
| Voice synthesis failed (all providers) | +1 credit, same SKU (Q11) |
| Customer dislikes output / wants a re-roll | none — pay again |
| Late settlement on a cancelled/abandoned job | +1 credit (`late_settlement`) |
| Any failure of a `paid_via='beta'` job | **no credit** — free re-run offered (§2.5) |

At most one refund per job, whatever the combination of events (§3.2.2). The refund arm is
`paid_via <> 'beta'`.

Credits never convert to song credits or cash. Cash refunds on request are manual (Payme cabinet +
`bayram.tools.media` ledger correction with `reason='admin_correction'`, `docs/deployment/08-payme.md` §7).

### 7.6 Caps

One open request per user per kind (partial unique index, §3.2.2); `media_daily_cap_image` = 10,
`media_daily_cap_video` = 3 paid requests per user per day (Redis counter). The song
`max_orders_in_flight=1` (`entitlements.py:80`) is not applied to media.

*As built (M5.2):* the daily caps are counted from `media_jobs.paid_at` (any rail: Payme, 🎟, 🎁)
since UTC midnight, per **kind** (both video tiers share one cap), **not a Redis counter**: the
Payme settlement that makes a job paid runs in a process with no Redis, and a counter a restart
clears is not a cap. `media_screen` refuses at the cap before a byte is downloaded or a guard asked
(`error_code='daily_cap'`, `media.daily_cap`, no strike); 💳, 🎟 and 🎁 re-check it at press time.

### 7.7 Finance

Media revenue is read from `media_purchases` (`provider='payme'`) by SKU — no new
`BAYRAM_ADMIN_*` price mirror (D19's drift problem). Beta and credit rows show as zero-amount
volume.

*As built (M5.2):* `RevenueSource` gains `media`; `/dashboard/finance` (revenue and run-rate) and
`/dashboard/series` concatenate `media_purchases` grouped by `(sku, currency, provider)` beside the
plan and top-up receipts. Operator corrections are `python -m bayram.tools.media credit <tg> <sku>
--grant|--revoke --actor NAME` (`admin_correction`, runbook 12 §6).

---

## 8. Admin panel

| Surface | Contents | Permission |
| --- | --- | --- |
| `GET /api/media-jobs` (list) | kind, SKU, state, backend, model, screen/output decision codes, price, paid_via, timings, queue position — **no prompt** (masked, `RECORDS_READ = M`) | `media.read` |
| `GET /api/media-jobs/{id}` | state timeline, attempts (provider, remote id, queue/run ms, GPU s, cost), vendor_usage rows, payment ref, outputs metadata | `media.read` |
| Reveal | prompt / narration / transcript via `POST /reveal` (new subject); outputs via `REVEAL_MEDIA` step-up with `STREAMABLE_MIMES += image/png, image/jpeg, video/mp4` (`admin/services/assets.py:110-114`). MIME types alone are not enough: `load_media` reads `AssetRow` (`assets.py:179-181`) and `reveal_window_key` is keyed on `asset_id`, while media never uses `assets` — so M5 adds a **`media_outputs` loader and a reveal subject keyed on the media output id**, reusing `parse_range` and the window counter. Test: a 200 MB mp4 streams with Range requests without being held in memory (host has ~831 MiB free). **Uploads are not revealable** (deleted after delivery), and **legal-hold items are never revealable** (§6.7) | `media.reveal` |
| Moderation queue | §6.6: held outputs, appeals, samples; release / confirm block / refund. **Refund mints a credit, so it is in D14's step-up class**: step-up + a reason code + INTENT/OUTCOME audit rows, like `CREDIT_GRANT` | `media.moderate` (+ step-up for refund) |
| Flags | effective backend per SKU (env + override), pause switches, GPU reserved window, beta allowlist (read-only from env) | `media.flags.write` + step-up for writes; audit INTENT/OUTCOME rows |
| Health | gateway `/health` + G4, GPU lock holder and queue, Gemini key pool (key_ref only), Higgsfield balance when available | `media.read` |
| Dashboard | separate media series: jobs by SKU/state, p50/p95 queue and render time, moderation reject rate by layer, refund rate, revenue from `media_purchases`, GPU-seconds/day | `metrics.read` |

Frontend in `admin-dashboard/src/features/media/` (D15), vitest beside each screen, uz/ru/en keys.

---

## 9. Security and operations

### 9.1 Gateway hardening (prerequisite for M2 go-beta with real photos)

1. **Rotate `GENAI_API_KEY`**; the old one is in plain text in two READMEs, `FIXING-VIDEO.md` and
   `scripts/client.py:9`.
2. **Cloudflare Tunnel + Access** in front of `:5174` (matching the production host's ingress);
   service token for bayram; close the raw public port.
3. **Header auth only** on the gateway; reject `?api_key=`; CORS off.
4. **Reachability test from the production host**: `bayram.tools.media doctor` hits `/health`,
   G4 and an authenticated `GET /v1/models` through the tunnel and asserts the allowlisted models
   exist and `zootopia` is not selectable by our client. Run at install and in `bayram-release`'s
   verify step.
5. Windows box: autologon/service so the gateway starts without an interactive login (or accept and
   monitor — Q12).

### 9.2 Gateway sweeper

A scheduled task on the box deletes `api_in_*` inputs and outputs older than
`gateway_retention_minutes` (60) and immediately on G6 calls; bayram calls G6 from
`media_cleanup`. Until G6 exists, the sweeper is the only control and its interval is the
exposure window.

### 9.3 Retention and `/forget`

- Uploads: deleted right after delivery, and on failure/abandon/cancel (§3.2.4).
- Outputs: 30 days default (**open, Q2**); `tg_file_id` dropped with them.
- `/forget` (`commands.py handle_forget`): delete all `media_inputs`/`media_outputs` objects and
  rows (except `legal_hold`, §6.7), null text columns, delete `media_credit_balances`, anonymise
  `media_purchases`, `media_credit_ledger`, `terms_acceptances`; delete the Redis keys
  `terms:ok:{tg}` and `menu:v:{tg}`; a job in flight gets `forget_requested_at` → it is not delivered and is
  purged at its next stage boundary; pre-pay jobs are cancelled.
- Logs: never log prompts, transcripts or base64 at INFO; the HTTP client redacts
  `x-goog-api-key`, `Authorization` and any `data:` URI.

### 9.4 Runbook

`docs/deployment/12-media-gateway.md` (written in M2, indexed in `docs/deployment/README.md`):
tunnel, key rotation, sweeper, GPU reserved window procedure, marketing-yield rule until G5,
Gemini key pool rotation, how to pause a SKU.

### 9.5 Environment variables (`.env.example`, bot + worker only)

```
# --- media: offering and rail (IMAGE_VIDEO_SPEC §4.5, §7.4)
BAYRAM_IS_IMAGE_OFFERED=false
BAYRAM_IS_VIDEO_STANDARD_OFFERED=false
BAYRAM_IS_VIDEO_FAST_OFFERED=false
BAYRAM_MEDIA_BETA_ENABLED=false
BAYRAM_MEDIA_BETA_ALLOWLIST=            # comma-separated Telegram ids
BAYRAM_IMAGE_BACKEND=local              # local|higgsfield|fal|fake
BAYRAM_VIDEO_STANDARD_BACKEND=local
BAYRAM_VIDEO_FAST_BACKEND=higgsfield
BAYRAM_IMAGE_PRICE_MINOR=500000
BAYRAM_VIDEO_STANDARD_PRICE_MINOR=2500000   # §7.1 (owner, 2026-09-24); empty = not sellable
BAYRAM_VIDEO_FAST_PRICE_MINOR=
BAYRAM_MEDIA_MAX_REFERENCE_IMAGES=4
BAYRAM_MEDIA_DAILY_CAP_IMAGE=10
BAYRAM_MEDIA_DAILY_CAP_VIDEO=3
BAYRAM_MEDIA_SCREEN_DAILY_BUDGET=10
BAYRAM_MEDIA_QUOTE_TTL_S=86400
BAYRAM_RETENTION_MEDIA_OUTPUT_DAYS=30
# --- local gateway
BAYRAM_GENAI_BASE_URL=
BAYRAM_GENAI_API_KEY=                   # secret
BAYRAM_GENAI_IMAGE_MODEL=flux2
BAYRAM_GENAI_VIDEO_MODEL=wan
BAYRAM_GENAI_SCRIPT_MODEL=qwen3.8:27b-q4_K_M
BAYRAM_MEDIA_MODERATOR=gateway          # gateway|fake (fake refuses to boot with media offered)
BAYRAM_MEDIA_MODERATOR_BASE_URL=        # defaults to GENAI_BASE_URL; a hosted guard endpoint (D24 fallback)
BAYRAM_MEDIA_MODERATOR_API_KEY=         # secret; that endpoint's own key — the gateway's never leaves its host
BAYRAM_MEDIA_MODERATOR_ACCESS_CLIENT_ID=     # optional Access pair for that endpoint, both or neither
BAYRAM_MEDIA_MODERATOR_ACCESS_CLIENT_SECRET= # secret
BAYRAM_MEDIA_GUARD_TEXT_ROUTE=moderate  # moderate (G1 endpoint) | chat (interim Qwen3Guard on /v1/chat/completions)
BAYRAM_MEDIA_GUARD_TIMEOUT_S=15
BAYRAM_MEDIA_SEXUAL_IMAGE_BLOCK_P=0.2
BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT=     # escalation owner's X25519 public key, base64 (§6.7); required with media offered
BAYRAM_MEDIA_MAX_COST_SHARE=0.5
BAYRAM_MEDIA_UZS_PER_USD=                # margin check only; needed once a SKU is on a backend that costs money
# --- voice
BAYRAM_GEMINI_TTS_API_KEYS=             # secret, comma-separated pool
BAYRAM_GEMINI_TTS_MODEL=gemini-3.8-flash-tts
BAYRAM_GEMINI_TTS_VOICE_FEMALE=
BAYRAM_GEMINI_TTS_VOICE_MALE=
BAYRAM_NARRATION_ROUTES=uz_latn=gemini_tts,uz_cyrl=gemini_tts,ru=gemini_tts,en=gemini_tts
BAYRAM_NARRATION_FALLBACK=elevenlabs_tts
BAYRAM_NARRATION_MAX_SECONDS=5
BAYRAM_NARRATION_MAX_WORDS_UZ=8         # per-language budgets under the ~12-word ceiling (§2.4.2)
BAYRAM_NARRATION_MAX_WORDS_RU=10
BAYRAM_NARRATION_MAX_WORDS_EN=12
BAYRAM_NARRATION_MAX_CHARS_UZ=60
BAYRAM_NARRATION_MAX_CHARS_RU=70
BAYRAM_NARRATION_MAX_CHARS_EN=80
# --- later backends (M6)
BAYRAM_HIGGSFIELD_API_KEY_ID=
BAYRAM_HIGGSFIELD_API_SECRET=           # secret
BAYRAM_IMAGE_MAX_COST_USD=0.20         # per request: both images, all attempts
BAYRAM_VIDEO_FAST_MAX_COST_USD=1.00     # per request, all attempts
BAYRAM_FAL_API_KEY=                     # secret
# --- terms (M1)
BAYRAM_TERMS_VERSION=
BAYRAM_PRIVACY_VERSION=
BAYRAM_TERMS_URL=
```

`VENDOR_SECRET_FIELDS += ("genai_api_key", "gemini_tts_api_keys", "higgsfield_api_secret",
"fal_api_key")` (`config.py:133`); none of them in `REQUIRED_VENDOR_SECRET_FIELDS` (media is
optional). `higgsfield_api_key_id` is not secret-shaped. The admin process refuses all four in
production (D13/D14).

---

## 10. Delivery milestones

Each item is one PR unless noted. Product tests live in `tests/`, use `FakeMediaProvider`,
`FakeModerator`, `FakeTts` and MemoryStorage — **no network in unit tests**. Gateway/Gemini
contract checks are separate make targets.

### M0 — prerequisites (no media code)

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M0.1 | Zero-greeting `_replay` fix: `_build_kit` returns a kit with an empty greeting tuple | new `tests/test_db` case builds a `greetings_per_kit=0` kit; a redelivered job replays without a vendor call (fake counts = 1) |
| M0.2 | Song moderator fail-open fix (§6.8) | the two tests in §6.8 |
| M0.3 | `workspace_sweep` cron + `Storage.put_file` | sweep deletes terminal dirs > 24 h, keeps live ones; `put_file` streams (memory bounded, tested with a 50 MB temp file) |
| M0.4 | Row-existence onboarding fix **and its migration `0029_add_acquisition_source`**, merged from `feat/capture-start-payload` | existing test on that branch passes here; `alembic heads` returns one head (`0029`). **Landed** by merging `feat/capture-start-payload` into `feat/media-products` (merge commit `7bec7ea`), not as its own PR |
| M0.5 | SCOPE_OF_WORK amendment blocks: "Amended by D20 (2026-09-24)" at §3.2, §2.2, FR-7, FR-96, LR-47, LR-51, LR-59; "Amended by D26" at LR-54 | doc-only; grep shows each carries its block |
| M0.6 | Stale price (§0.3): `main.py`'s boot-refusal docstring and PAYME_INTEGRATION §1.4, §8.2, §8.6.2 stop stating 7 000 UZS and name `single_song_price_minor` instead. **Landed** with the M0 review fixes (M0.R) | doc/comment-only; nothing in `src/` or PAYME_INTEGRATION states 7 000 UZS as the live price (worked examples of a unit bug may still use it) |

### M1 — Terms gate (all users)

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M1.1 | `0030 terms_acceptances` (`down_revision="0029"`), model, purge/anonymise, privacy-set registration | migration round-trip; one alembic head; `test_privacy_constraints`, `test_audit_retention` pass |
| M1.2 | `Onboarding.terms` + `TermsCB` inside the onboarding router, `Identity.terms_ok`, `TermsGateMiddleware`, **new `/terms`** + `command.terms`, the existing `/privacy` extended to render the versioned notice through `privacy_text()`, copy in 4 locales incl. `help.text`/`privacy.forgotten`/`command.*` | new user: language → terms → contact; FSM expired while in `Onboarding.terms` + `/start` → terms screen again, not contact; ✅ from a not-onboarded user reaches the accept handler (not `NotOnboarded`); existing user blocked until accept; `/support` then a reply describes a ticket; blocked callback is answered; version bump re-prompts; after `/forget` the next message shows terms; worker delivery unaffected; accept creates no `user_profiles` row; i18n parity |
| M1.3 | Approved Terms/Privacy text (Appendix A after counsel) | owner sign-off recorded in the PR |

### M2 — data + provider + local image behind beta

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M2.1 | `0031` media tables (incl. `media_credit_balances`), enums, repository, purge predicates, `/forget` arm | each `*_expires_at` read by a predicate; `legal_hold` rows survive purge; `/forget` removes objects; one alembic head |
| M2.2 | `MediaGenProvider`, `LocalGatewayProvider`, fake, factory, flags + Redis overrides, boot refusal, margin check | payload builder: `length` not `frames`, explicit w/h, model ∈ allowlist, no query-string key; `unknown` → ambiguous; 502-no-id → pre-submit error; boot refuses stub without beta+allowlist, payme sandbox without allowlist, fake moderator with media offered; a media 💳 press on the stub rail writes no receipt and starts nothing |
| M2.3 | Collage | 1–4 inputs × 3 aspects produce target size; EXIF stripped |
| M2.4 | Stage jobs, GPU lock, sweeps, delivery (image), DB-driven progress | full fake run: screening → beta free → 2 photos delivered → inputs deleted; duplicate enqueue of every stage is a no-op **and a deliberate self-re-enqueue runs again**; worker killed between attempt insert and POST, re-run → fake provider counts one submit; lock renew/release is CAS (old attempt cannot free a new lock); terminal job leaves the GPU queue; lock released on failure; deadline then late success → nothing delivered, one credit |
| M2.5 | Bot: ✨ picker, `menu:v:{tg}` re-push, legacy label keys, `ImageOrder`, album tray, stateless post-freeze callbacks, quote/beta screens, `/cancel` + open-request rules | album of 10 → one tray showing the final count, deduped, capped; album to the stray-message fallback → one reply; old 🎵 label still routes; non-allowlisted user sees no Image; re-push fires once, not after every song; edit after quote → new row screened before any quote; a second Done with a pre-pay row open cancels the old one; with a paid row open → `media.open_request`; 🎁 re-checks the allowlist at press time; 💳 hidden on stub, 🎁 hidden on live-paid; locale contract covers `button.media.*` |
| M2.6 | Gateway hardening done (§9.1), `doctor`, runbook `12-media-gateway.md` | `doctor` green from the production host |
| — | **Beta gate:** image enabled for the allowlist only after M3.1 lands (no unscreened beta) | |

### M3 — moderation

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M3.1 | `MediaVerdict`, `GatewayGuardModerator` (G1–G3, G8 clients), G1 label mapping, youth lexicon, L0–L4, strikes, fail-closed, legal hold | unknown category → block; timeout → `unavailable` → `media.busy`; G1 `safety` missing → `unavailable`; G2 `scores:{}` → `unavailable`; pre-pay review → refused; `sexual` on any image → block; lexicon youth term + `sexual` → hard rule; slogan in an uploaded photo reaches G1 via G8; single-variant L4 block → nothing delivered, one credit; `sexual_minors` block leaves objects + rows after cleanup and purge; strikes suspend |
| M3.2 | `0032 moderation_reviews`, admin queue (refund behind step-up) | hold → release → deliver; hold 24 h → refund; refund without step-up refused |
| M3.3 | Owner installs G1–G4, G7, G8 on the 5090 | latency during a Wan render measured and recorded in the runbook; a labelled 100-item uz/ru/en **text** set run through G1, and a labelled **image** eval set (adult nudity, violence, extremist symbols; **no CSAM**) run through G2/G8 to calibrate thresholds, results filed in `docs/research/` |

### M4 — video Standard + voice (beta)

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M4.1 | `VideoOrder` flow (`drafting` row, prescreen, back map, ✖️ everywhere), voice screens, own-voice intake | 6 s voice note rejected pre-row; 5.6 s note (Telegram says 5) refused by ffprobe before payment; text over the per-language budget rejected; edited script with a denylisted term refused at L1; whisper low `avg_logprob` / wrong language / low word rate → refused; tier screen skipped with one tier |
| M4.2 | `GeminiTtsProvider`, key pool, ElevenLabs fallback, `NarrationRequest` | 429 on key A → key B used, A cooled; all cooled → ElevenLabs; key never in logs (caplog assertion) |
| M4.3 | Script writer, whisper transcription, mux, parallel fan-in, video delivery | fan-in fires once regardless of order; mux output duration = video duration; >50 MB → document |
| M4.4 | Listening test (20 uz lines, 10 ru, 10 en) and house-voice choice | owner sign-off; uz fails → `NARRATION_ROUTES` uz → elevenlabs |

### M5 — payments live (after Payme production, PAYME_INTEGRATION §8.6)

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M5.1 | SKUs, `media_purchases`, all §7.3 match sites, `resume_media_job_id` through `charge`, Check/Create refusals, settle path, media reveal loader | Perform for each SKU commits receipt + conditional state move in one transaction; Perform on a cancelled job → receipt + one `late_settlement` credit, row untouched; unknown SKU fails closed; double settle starts once; burned claim + failed enqueue → sweep starts the job exactly once; settled media intent never shows the song keyboard; beta failure grants no credit |
| M5.2 | Credit balances + ledger, refunds, caps, finance series | two concurrent 🎟 taps with balance 1 → one spend; deadline + late failure → one credit; credit is SKU-scoped; song balance untouched |
| M5.3 | Owner sets video Standard price; flags on for everyone | boot refuses an offered SKU with no price |

### M6 — Higgsfield Fast tier

| PR | Work | Acceptance / tests |
| --- | --- | --- |
| M6.1 | `HiggsfieldProvider` (upload, estimate, submit, poll, fetch, webhook trigger, ceiling) | ambiguous POST never repeated; 400 concurrency → rate-limited; 402/403 → quota; `sound:"off"` always sent; geometry normalised |
| M6.2 | Tier screen, Fast price, multi-ref native path | with Fast enabled the tier screen shows both; >1 ref goes native, no collage |
| M6.3 | Counsel view on sending photos abroad (R6) recorded before enabling | — (owner only: a precondition in runbook 12-media-gateway §6.5 and a boot warning; no code gate) |

---

## 11. Risk register

| # | Risk | Owner | Accepted? | Mitigation | Trigger → action |
| --- | --- | --- | --- | --- | --- |
| R1 | **FLUX.2-dev licence** prohibits revenue use; paid local images breach it (rejected #19) | Owner | **Yes, 2026-09-24 (D21)** | Flag ready to move `IMAGE_BACKEND` to higgsfield/fal in one override; LR-36 row records the breach knowingly | BFL contact/notice, a licence offer within budget, monthly image revenue > the BFL licence cost, or counsel advice → switch backend or buy licence within 7 days |
| R2 | **Gemini key pool** across projects breaches Google APIs ToS §d; suspension takes down every product on those projects; free-tier keys train on narration text (accepted, Q17) | Owner | **Yes (D23)** | Dedicated projects for TTS only (no LLM on them); ElevenLabs fallback; key_ref health | Any key suspended/403 → disable pool member, alert. **Collapse to one billed project with ≤2 rotation keys** on: any key suspended or 403-disabled twice in 30 days, any Google notice about circumvention, or the D5 LLM project sharing a key (same trigger as D23) |
| R3 | **Real people / faces / minors with terms only**: deepfakes, NCII, sexualised edits of real people or children; no face logic | Owner | **Yes (D20)** | Terms gate + L1/L2/L4 sexual/violence/minor categories + hard CSAM rule + strikes + review queue | First confirmed real-person abuse case or complaint → build the face-conditioned fallback written in `RESEARCH-image-video-pipeline` §5 ("Face-conditioned fallback") within one release |
| R4 | **Capacity**: 17.5 min/video on a shared GPU; hours-long waits; deadline refunds | Owner | partly | ETA at quote, refuse when ETA > deadline, GPU reserved window, G5 priority, daily caps | p95 paid→delivered > 2 h for a week → enable Fast tier or cloud Wan (fal) for overflow |
| R5 | **Gateway on a residential IP / Windows desktop**: outages, IP changes, login-dependent start | Owner | partly | Tunnel, `doctor`, fail-closed quotes, pause switch | 3 outages > 1 h in 30 d → move Standard to fal Wan 2.5 |
| R6 | **Legal (Uzbekistan)**: extremism/religion/officials content; PD law amendment 1125 on biometric data abroad (Higgsfield/Google); AI Order 3787 human review | Owner + counsel | open | Denylist for officials/religion; review queue; counsel before M6 | Counsel advises against → keep photos local-only; Fast tier text-only |
| R7 | **Duplicate spend** (no idempotency on gateway/Higgsfield; ARQ re-runs a `_job_id` after a crash or `job_timeout`) | Engineering | no | attempt-before-POST; a `submitting` row with no `remote_id` is never re-POSTed but marked ambiguous and reconciled (§3.3); attempt number fixed at enqueue; per-SKU cost ceilings (§4.3). (M0.1 fixes the separate song-greeting replay.) | any `media_attempts` pair with same job/variant both succeeded → incident |
| R8 | **Free-screening oracle** (probe the guard for free) | Engineering | no | screening budget, strikes | budget hits > 5% of users/day → lower budget |
| R9 | **Gemini/Higgsfield 18+ terms** vs LR-59 children use case | Owner | open (Q7) | Terms age clause | Google/Higgsfield notice → media 18+ attestation |
| R10 | Output retention undecided (30 d default) | Owner | open (Q2) | `/forget` covers it | counsel/owner answer |
| R11 | Guard model gaps: Qwen3Guard on Uzbek untested; **no guard has a minor detector** (youth signal is a lexicon + an uncalibrated ShieldGemma custom policy + a VLM caption); text in images depends on OCR/caption quality (G8); **own voice notes: tone and non-verbal sound are unscreened**, only the transcript is | Engineering | no | M3.3 labelled text + image sets; thresholds per category; zero-tolerance nudity on every image; whisper confidence checks (§5.4) | recall < 90% on the set for sexual/violence → add NudeNet tripwire or a second guard |
| R12 | **Holding CSAM-class material** under legal hold (§6.7) is itself a legal exposure, (owner-confirmed exception to O16) | Owner + counsel | **Yes (Q16, 2026-09-24)** | encrypted, escalation-owner key only, never panel-revealable, 72 h deadline | counsel advises delete-only → switch to hash + metadata only |

---

## 12. Open questions

| # | Question | Default until answered |
| --- | --- | --- |
| **Q1** | ~~Video prices~~ — **answered 2026-09-24:** Standard 25 000 UZS. Fast price still open (set at M6) | Fast unset = not sellable; recommended 35–45k UZS (§7.1) |
| **Q2** | Output retention | 30 days, erased by `/forget` |
| **Q3** | Image: one of two variants fails **to generate** — deliver 1 + full credit? | Yes. Does **not** apply to our own L4 block of a variant: that fails the whole request with one credit (§6.4), so prompts cannot be steered toward "one image + a free credit" |
| **Q4** | Can the guards hold reserved VRAM during Wan, and when are G1–G7 installed (ETA)? | M3 blocks beta until installed |
| **Q5** | Allow image/video while a song renders? Blocked by the `Wizard.submitting` stand-down filter and the song's progress park (not by data loss, §2.2) — a UX decision | No in v1 |
| **Q6** | Counsel review of Terms/Privacy (Appendix A) and of photos going abroad (R6) | Terms go live only after sign-off; Fast tier off |
| **Q7** | Age clause: 18+ for the whole bot, 18+ for media only, or parental consent for songs? | Draft says 18+ for media; songs by a minor only with a parent's permission |
| **Q8** | Named CSAM/terrorism escalation owner and reporting route | The owner; legal hold as §6.7. **Blocks leaving beta** (D25) |
| **Q9** | Celebration presets/templates on top of the free prompt (value-add vs Higgsfield's pass-through clause) | Not in v1 |
| **Q10** | Video with several photos: collage as the opening frame looks like a collage. Acceptable, or use the first photo only for video? | Collage (O6) |
| **Q11** | Voice synthesis fails after payment: fail + credit, or deliver silent + credit? | Fail + credit |
| **Q12** | Gateway start-without-login (autologon/service) acceptable on the Windows box? | Monitor only |
| **Q13** | Beta allowlist ids (owner + which admins) | Owner only |
| **Q14** | House voices (female/male) for Gemini TTS | Chosen in M4.4 |
| **Q15** | Does the marketing pipeline accept "yield to bayram" before G5 exists? | Yes, by runbook |
| **Q16** | ~~CSAM-class material: hold or delete?~~ — **answered 2026-09-24:** encrypted ≤72 h legal hold (§6.7); counsel may still switch to delete-only (R12) | — |
| **Q17** | ~~Free-tier keys for paying customers?~~ — **answered 2026-09-24:** yes, use Google for everyone; training accepted (D23) | — |

---

## Appendix A — DRAFT Terms of Use and Privacy Notice (outline)

> **DRAFT — not legal advice.** Written by Claude on 2026-09-24 as a starting outline for the owner
> and local counsel. Headings and key clauses only; English master, to be translated into Uzbek
> (Latin, U+02BB) and Russian after approval. Versioned: `terms_version` / `privacy_version`
> (§2.1). Nothing here is in force until the owner signs it off (M1.3).

### A.1 Terms of Use

1. **Who we are.** Operator's legal name, registration, address, contact (`/support`).
2. **The service.** AI-generated songs, images and videos inside Telegram; outputs are produced by
   automated systems and may be inaccurate or unexpected.
3. **Eligibility.** Media features (images, videos, voice) are for users **18+** (Q7); songs may be
   ordered by a minor only with a parent's or guardian's permission. By accepting you confirm this.
4. **Your content.** You keep what you own. You grant us a limited licence to process your prompts,
   photos and voice messages **only** to provide the service. You confirm you have the right to
   upload them and, for any identifiable person in them, that person's permission.
5. **Prohibited use** (non-exhaustive): sexual content involving anyone under 18 (reported where
   required); sexual or nude images of real people; content that harasses, defames or impersonates
   a real person, including public officials; extremist, terrorist or hateful content; content that
   insults religion or state symbols in breach of local law; illegal goods; infringing others'
   copyrights, trademarks or characters; attempts to bypass our safety checks.
6. **Safety checks.** Every request and output is checked automatically; we may refuse, pause or
   withhold output without giving the specific reason; repeated violations suspend access; you can
   appeal through `/support`.
7. **AI-generated output.** Outputs are labelled AI-generated; purely AI-generated output may carry
   no copyright protection (SEC-11); we do not guarantee likeness, text rendering or suitability.
   Your permitted use of outputs; no use to deceive (e.g. presenting a generated image as real
   evidence).
8. **Payment.** Prices shown before payment in soʻm; payment via Payme; one request = what the
   quote states (e.g. 2 images). A paid request that fails or that our output check blocks is
   refunded as a credit for the same product; dissatisfaction with a result is not a failure; cash
   refunds on request per the Payme process. Free beta access may be withdrawn at any time.
9. **Third-party providers.** Named categories (GPU partner, speech provider, payment provider,
   optional cloud generation providers) and that their terms may apply.
10. **Availability.** No uptime guarantee; waits shown are estimates; we may pause features.
11. **Liability.** Limits to the amount paid for the affected request, to the extent law allows.
12. **Changes.** New versions are shown in the bot and must be accepted to continue.
13. **Law and disputes.** Governing law of the Republic of Uzbekistan; venue; consumer rights
    unaffected.

### A.2 Privacy Notice

1. **Controller** and contact; how to reach us (`/support`, `/forget`).
2. **What we collect:** Telegram id, name and language; phone number (onboarding); songs:
   recipient details you type; media: prompts, uploaded photos, voice messages and their
   transcripts, generated outputs; payment records (no card data — Payme handles it); technical
   logs; terms acceptance record.
3. **Why:** to provide what you ordered; safety screening; payment and accounting; support;
   preventing abuse (strikes); legal obligations.
4. **Legal basis:** your consent (acceptance of these documents) and performance of the service —
   counsel to confirm under the Law on Personal Data.
5. **Processors and transfers:** our GPU server (location to be stated); speech synthesis
   (Google, ElevenLabs); optional cloud generation (Higgsfield, fal) — **data may leave
   Uzbekistan**; biometric-data rules (amendment No. 1125) to be confirmed by counsel.
6. **Retention:** uploaded photos and voice messages are deleted **immediately after delivery** (or
   when a request fails, is cancelled or abandoned, within 24 hours at most); generated outputs and
   your prompts kept **30 days** (open, Q2); payment and acceptance records kept as required by law;
   material connected to suspected child sexual abuse may be preserved for up to 72 hours pending a
   decision to report it (Q16).
   Text you ask the bot to speak aloud is sent to Google (Gemini) to make the voice; Google may use
   it to improve its services. Do not put private information in narration text.
7. **Your rights:** access, correction, deletion (`/forget` deletes your uploads, outputs and
   prompts; payment records are anonymised), withdrawal of consent (stops future use).
8. **Children:** media features are not for under-18s; songs about children are allowed per the
   song flow's notice.
9. **Security:** encrypted transport, access controls, deletion schedules.
10. **Changes** to this notice are versioned and re-accepted in the bot.
