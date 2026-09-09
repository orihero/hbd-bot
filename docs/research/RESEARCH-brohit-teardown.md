# Competitor teardown — @bro_hit_bot

## Teardown: @bro_hit_bot («Бро.Хит — Создать песню»)

### What it is

A Russian-language AI song-generation Telegram bot. The user describes an occasion and a person in chat, the bot writes lyrics free of charge, and after payment returns a finished MP3.

**Operator.** ИП Пермяков Александр Игоревич, ИНН 344713025915, ОГРН 314344304300163, Volgograd. Bank: АО «ТБанк». **Entity defect:** the mandated IT-disclosure page (`brohit.ru/disclosure`) names a *different* entity — ООО «Бро.Хит», ИНН 3444282987, ОГРН 1263400001226, registered 26 Feb 2026, same director — as rightsholder and seller of the identical 499/999/2999 price list, while the live offer text still contracts the user with the sole proprietor. Both tax IDs were read from the operator's own live pages. The consumer contract points at the older vehicle; the disclosure points at the newer one, and nobody migrated the offer.

**Surfaces named in its own offer:** `t.me/bro_hit_bot`, `brohit.ru` (web twin, shared account and balance), `max.ru/id344713025915_bot` (MAX messenger; the handle embeds the operator's tax ID), `vk.com/bro.hit.official`, and `clip.brohit.ru` (a separate AI music-video product). Channel `@brohit_ru_official` (29,931 subs), chat `@brohit_chat` (839 members).

**Scale — the number everyone quotes is misleading.** The live Telegram badge reads 45,801 monthly users. Wayback snapshots of the same `tgme_page_extra` element read 16,629 (2025-08-01) → 57,239 (2025-09-03) → 285,803 (2025-10-17) → 398,123 (2025-11-20) → 426,732 (2025-12-01) → 414,329 (2026-01-07) → 668,356 (2026-01-30) → 45,801 (2026-08-26). That is an ~89–93% collapse from peak. A control bot (`@stickers`) fell from 867,813 (2025-12-02) to 647,756 live — 25% — over the same window, so mild platform-wide deflation exists but cannot explain this. The collapse is bot-specific. The "445,000" and "800,000" figures circulating on review sites are not junk totals — they are the same monthly badge read earlier, and they land on the archived curve. The *cause* is unknown; candidates are the April 2026 web+MAX launch draining Telegram-side activity, demand decay after a viral peak, or a ranking/enforcement event. Nobody has distinguished them.

**On "largest".** Scoped precisely: among the **seven bots in the 199 ₽ price cluster surveyed** (@bro_hit_bot plus @makoo_aibot, @bitotronbot, @melogenbot, @neurobeatbot, @pesenatorbot, @maviks_music_bot), Бро.Хит is the only one whose t.me page renders a monthly-user badge at all — the other six have an empty `tgme_page_extra`, meaning they sit below Telegram's display threshold. That makes it materially the largest **of that cluster**. It is *not* the largest Russian AI-song bot overall: Songraiter (20,011), SoNata (18,781) and SpoetKa (14,853) all carry badges and all sit outside this cluster.

---

### Evidence and its limits

**Nobody drove the bot first-hand.** Not one line below was observed inside a Telegram chat with @bro_hit_bot. The corpus behind this teardown is: the operator's live public web pages and legal routes fetched by raw curl; Wayback snapshots of the t.me badge; the complete server-rendered i18n dictionaries of both the song client (`brohit.ru`) and the clip client (`clip.brohit.ru`); all 19+19 shipped JS chunks of both hosts, downloaded and grepped; unauthenticated live JSON endpoints (`/api/payment/bundles`, `/api/pricing`, `/api/feature-flags`); direct CDN probes against `music.brohit.ru`; five delivered MP3s downloaded and frame-counted; 423 scraped channel posts (2025-10-06 → 2026-08-25); and consumer review corpora.

**Critically, the web twin is not a Telegram Mini App.** No Telegram WebApp SDK appears anywhere in its bundles. Its keyboard is therefore *not* guaranteed to be the bot's keyboard, and its payment modal is *not* evidence of the bot's payment path. Everything marked "web" below is one inferential step away from the product this teardown is nominally about.

**Questions only first-hand use can settle — do not freeze requirements against guesses here:**

1. **The in-bot payment path.** Native Telegram Payments (`sendInvoice`/`answerPreCheckoutQuery`), a WebApp popup, or a link out to `brohit.ru`? The web twin's embedded YooKassa modal proves nothing about the chat.
2. **Telegram Stars.** Two review sites quote 200/400/1200 ⭐ tiers mapping 1:1 onto the ruble bundles. The web bundle contains no `XTR` currency code and no `openInvoice`/`invoice_link` call — every apparent `xtr` hit was a false positive (`extractInterceptionRoute`, `xtra.co.nz`). Only running the bot resolves it.
3. **Which Bot API method delivers the audio** — `sendAudio` vs `sendVoice` vs `sendDocument` vs a bare link. The FAQ's "download button yields an MP3" is consistent with `sendAudio` + inline buttons; one otzovik reviewer complained the file was awkward to forward, which weakly argues against plain `sendAudio`.
4. **Whether one variant or both are sent.** The backend renders exactly two; the web song product surfaces one; one otzovik reviewer reports receiving *four* variants in ~10 minutes. Unreconciled.
5. **The actual `/start` copy and every button label.** The Russian chip text below is verified for `brohit.ru` only.
6. **The real demo length** (see step 12).

---

### Complete feature surface

**Song product (bot + brohit.ru):**
- 4-input wizard: occasion (6 chips: День рождения · Признание · Свадьба · Розыгрыш · Поддержка · Корпоратив, plus free text) → genre (8 chips: Поп · Рэп/Хип-хоп · Рок · Электроника · Фолк · Инди · 80-е · Классика, plus free text) → vocal gender (Женский · Мужской · Любой) → one free-text "open question" brief.
- The option catalogue arrives inside the server-rendered payload — each question is a `{key, value, title, question, answers}` object with the answer list supplied by the server, and the Redux `steps` slice merely renders it. **This is a server-rendered build artefact, not proof of runtime configurability.** It shows the lists are not hardcoded in the client; it does not show they can be changed without a deploy. Treat "editable by ops without shipping" as unverified.
- Voice input: Telegram voice message / browser MediaRecorder → `POST /api/voice-to-text`, hard cap 20 MiB. Input only — the bot never produces speech.
- Free, unlimited LLM lyrics with a free edit loop. Licensed as free for the whole contract term by the offer itself (cl. 1.5).
- Paid generation: one credit per press of «Сгенерировать». Backend renders exactly two variants; the song product surfaces one.
- Streaming playback partway through render («Ещё создаётся… Но уже можно слушать!»).
- Result card: MP3 download, cover art, share link, 5-star rating with structured defect categories (Вокал / Музыка / Настроение / Слова не разобрать / Караоке не в такт / Другое), and an instrumental («Минусовка») generated as a separate async task.
- Share pages at `brohit.ru/song/<short_code>`; `robots.txt` disallows `/song/` for everyone but explicitly allows `TelegramBot`, `Twitterbot`, `facebookexternalhit` so link previews render.
- Account features on the web twin: email OTP / Google / Facebook / Microsoft login, profile, phone verification, «Привязать Telegram» to merge bot history and balance.

**Clip product (clip.brohit.ru, shipped June 2026, separate wallet):** Pixar-style animated video built from uploaded hero photos with automated face-quality checks; two fixed formats (≤1 min 9:16 / 3–5 min 16:9); karaoke subtitles; custom titles in 5 colours; watermark-free export; a scene editor with per-scene regeneration and a purchasable edit balance. It also carries features the song product lacks: an explicit 4-value mood picker (Трогательное / Весёлое / Торжественное / Грустное), two extra genres (`genre_sertanejo`, `genre_pagode` — Brazilian, dead code signalling a pt-BR expansion), audition-two-versions-then-pick («Одни стихи — два настроения»), free lyric regeneration with a prompt, and explicit stress handling. **Benchmarking only the song bot understates the operator's feature surface by roughly half.**

---

### End-to-end user flow

| # | Step | What happens | Evidence |
|---|---|---|---|
| 1 | `/start` | Chat bot, not a Mini App (`t.me` renders "Start Bot", not "Launch App"). `/start` is defined by the offer as the legal act of accepting the licence. | **Verified** (t.me page, offer text). Greeting copy and button labels **unknown** |
| 2 | Occasion | 6 chips + free-text escape. | **Verified for the web twin** (server-rendered i18n payload); **inferred for the bot** |
| 3 | Genre | 8 chips + free text. | **Verified (web) / inferred (bot)**. One review site quotes a different bot-side list (рэп, поп, диско 90-х, шансон, электро) — **unresolved** |
| 4 | Vocal gender | 3 options mapped to `f/m/group`. Gender only; no timbre, no named voices, no cloning. | **Verified (web) / inferred (bot)**. Whether the bot has this step at all: **unknown** |
| 5 | Free-text brief | "for whom / their age / what makes them special / jokes and phrases / what feeling". Voice accepted. | **Verified (web) / inferred (bot)** |
| 6 | Lyrics written, free | Rotating status lines; 1–3 min per user reports. | **Verified** (offer cl. 1.5 licenses text creation free; FAQ) |
| 7 | Free unlimited lyric editing | "Текст и описание можно редактировать бесплатно." | **Verified** (FAQ, offer) |
| 8 | Paywall — «Сгенерировать» | One credit per press, no partial fix: "каждая генерация засчитывается как отдельный кредит песни", "Любое изменение требует генерации новой песни." | **Verified** (FAQ) |
| 9 | Purchase | 499 ₽ / 1 song, 999 ₽ / 5, 2 999 ₽ / 30. Web checkout is an embedded YooKassa modal (`customization:{modal:true}`, server-minted `confirmation_token` from `POST /api/payment/create`) — no browser bounce. | **Verified** (live `/api/payment/bundles` + `/disclosure` + shipped JS). **In-bot payment path: unknown** |
| 10 | Generation | Suno. Delivered MP3s carry an ID3 `COMM` frame reading `made with suno; created=<ISO8601>; id=<uuid>`; ID3 artist tag is `Бро.Хит`. CDN exposes exactly `_1` and `_2` per song id (HEAD 200); `_0`/`_3` return 404. Vendor claim "up to 2 minutes"; users report 5–10 min. | **Verified** (ID3 bytes, direct CDN probes) |
| 11 | Delivery | MP3 with cover art and title, plus a share page. Measured: durations 2:36 / 2:48 / 3:02 / 3:06 / 3:19, ~185 kbps VBR, 48 kHz; downloaded files run 3.76–4.33 MB. No user-facing length control. | **Verified for the web/CDN.** Bot API method, and one-vs-both variants: **unknown** |
| 12 | Demo — **contested** | Vendor FAQ: **one** onboarding demo song for new users only ("Новые пользователи получают одну демо-песню в начале… мы не можем предоставлять аудиопревью перед каждой генерацией"). Player shows «(Демо версия)» + «Получить полную песню»; unlocking is a `buy_demo` action that spends a credit. Against this, the review network (cryptorussia, bitok.blog **and otzovik**) consistently describes a **~45-second / first-verse** fragment. | **Verified that a demo exists** (FAQ + i18n + `buy_demo`). The two readings are **unresolved**: brohit.ru never names a duration, so "45 s" has no vendor source — but otzovik is a first-hand consumer review corpus, not an SEO farm, and its account may simply describe what the *bot* does versus what the *web FAQ* says. They are reconcilable (one demo, and that demo is 45 s) but they are not the same claim |
| 13 | Instrumental | Separate async task (WebSocket `generate_instrumental`), delivered as a bare link; client detects success by `message.includes('https://')`. **The FAQ still calls this unreleased ("находится в разработке… предоставим инструментальную версию вручную"); the code ships it.** An otzovik reviewer complains «минусовку часто не делает». Cite the bundle, not the FAQ. | **Verified** (shipped JS + i18n keys `player.instrumental_generate/_download`) |
| 14 | Regenerate = pay again | No partial re-render. Wrong stress, wrong vocal gender, wrong genre are all fixed by paying for another full generation. Documented remedy is to capitalise the stressed vowel yourself («звонИт»). | **Verified** (FAQ). This is the dominant complaint in every review corpus |
| 15 | Clip upsell | 999 ₽ short (`1-video-short`) / 2 999 ₽ full (`1-video`), separate wallet, only for songs made in the service (offer cl. 2.2). | **Verified** (live `/api/pricing`, offer) |

---

### Pricing and payments

| Item | Price | Effective unit |
|---|---|---|
| 1 song credit | 499 ₽ | 499 ₽ |
| 5 song credits | 999 ₽ | 199.8 ₽ (UI rounds to «200 ₽ / песня») |
| 30 song credits | 2 999 ₽ | 99.97 ₽ (UI rounds to «100 ₽ / песня») |
| Short clip (9:16, ≤1 min) | 999 ₽ | separate wallet |
| Full clip (16:9, 3–5 min) | 2 999 ₽ | separate wallet |

Live JSON, verbatim: `{"status":"ok","bundles":[{"price":499,"songs":1},{"price":999,"songs":5},{"price":2999,"songs":30}]}` — the same three tiers restated word-for-word in the legal disclosure.

Prepaid credit packs, not a subscription; full prepayment mandated by offer cl. 4.2. Promo codes are the only discount mechanism named in the offer (cl. 4.1); a promo-code field is confirmed only on the clip product. **Note BroHit has no headline 199 ₽ tier** — it reaches that price point only through the 5-pack, which is precisely how it answers the cheaper cluster that headlines a flat 199 ₽.

**Refunds:** no refund clause exists in the offer text at all — no `возврат` section — and `https://brohit.ru/refund` returns HTTP 404 (as do `/vozvrat`, `/return`, `/policy`, `/pricing`, `/tariffs`, `/partner`, `/ref`, `/referral`). The FAQ separately promises refunds "в случае подтверждённой технической ошибки или сбоя" and otherwise bonus credits — i.e. the offer and the FAQ contradict each other. Exposure is instead pre-empted by cl. 1.3's "как есть" clause disclaiming "НЕСООТВЕТСТВИЕ РЕЗУЛЬТАТОВ ИСПОЛЬЗОВАНИЯ СЕРВИСА ОЖИДАНИЯМ ЛИЦЕНЗИАТА", plus cl. 4.2's full prepayment. No aggregator is named in any legal document. No fiscal-receipt (54-ФЗ) clause and no receipt-email field — the МАКУ cluster, by contrast, does carry a 54-ФЗ receipt commitment.

**Rights.** Offer cl. 2.3 grants the user the exclusive right to the song — a claim its own supply chain (a Suno reseller path) cannot support and its jurisdiction does not clearly grant for purely AI-generated output. Clauses 6.2–6.4, present in the June 2026 revision, take back a free, worldwide, perpetual licence for the operator to publish, broadcast and stream the user's song and clip, and push third-party claims onto the user («Лицензиат самостоятельно урегулирует претензии от третьих лиц») — under an offer whose stated acceptance is merely first visiting the resource, so there is likely no affirmative-consent moment for them.

**⚠️ UNRESOLVED — how many offers are actually live.** Two probes of the same three URLs disagree and this teardown picks neither side:

- **Probe A:** three *differently dated* offers are live simultaneously — `/terms` dated «22 января 2026 года», `/agreement` dated «07 марта 2026 года», `/oferta` dated «19 июня 2026 года»; all headed «ОФЕРТА», «г. Волгоград»; the two older ones covering only the Telegram bot, the newest covering the whole Service (site + bot + VK + MAX + clip).
- **Probe B:** `/terms` and `/agreement` serve the *same* ИП Пермяков oferta text.

Both were recorded as verified-primary. **Needs a first-hand re-check** — fetch all three routes in one pass and diff them. Until then, do not build an argument on "three materially different offers." What survives regardless: at least one live offer contracts the user with the sole proprietor while `/disclosure` names the LLC; the June text carries cl. 6.2–6.4; and there is no refund clause anywhere. If Probe A holds, add a genuine enforceability problem on top — a user who accepted via `/start` could argue the January text binds them. If Probe B holds, that argument mostly evaporates.

---

### Likely tech stack

- **Music: Suno**, proven from ID3 bytes, almost certainly via a reseller (audio is re-hosted under `music.brohit.ru`; no upstream host leaks). Which reseller and which model version are unknown; `api.kie.ai` and `api.sunoapi.org` are provably one backend and are what this whole Russian cohort uses in code. Two variants per generation is Suno's default, which also explains no stems, no cloning, no length control and ~3-minute tracks.
- **Web twin:** Next.js 15.5.10 on Selectel (212.41.1.183), driven by a WebSocket at `wss://brohit.ru:3461/ws` with the JWT as a query param. Client→server actions: `generate`, `buy_demo`, `clear`, `generate_instrumental`, `rate`, `add_history`, `transaction`. Server→client includes `{error_code:"INSUFFICIENT_FUNDS"}` and `system_notification` types `balance_updated` / `generate_instrumental`. Literal `ping`/`pong` heartbeat; reconnect backoff 300 ms → 1 s → `min(1000+(n-1)*500, 7000)` ms, infinite attempts; close code 401 triggers `signOut`. Six wizard flow states (`anketa1/2/3` → `nexttt` → `generation` → `after_generation`), not three.
- **REST:** `/api/auth/otp/*`, `/api/session`, `/api/profile`, `/api/profile/sync_tg`, `/api/telegram/bind`, `/api/chat/history`, `/api/playlist`, `/api/payment/bundles`, `/api/payment/create`, `/api/voice-to-text`.
- **Payments (web):** YooKassa embedded widget — `<script id="yookassa-widget-script">` from `yookassa.ru/checkout-widget/v1/checkout-widget.js`, then `new window.YooMoneyCheckoutWidget({confirmation_token, customization:{modal:true}, …})` with `success` / `fail` / `modal_close` handlers. Analytics names confirm the modal pattern: `YOOKASSA_POPUP_OPEN`, `YOOKASSA_POPUP_CLOSED_NO_PAY`, `YOOKASSA_SCRIPT_NOT_LOADED`. **Auth:** NextAuth + a Firebase user object. **Instrumentation:** Sentry + Yandex Metrika; privacy policy names ООО «Яндекс» as processor.
- **Cluster contrast:** the ООО «МАКУ» farm (Barnaul, ИНН 2225239313) runs a single multi-tenant Nuxt app internally named `music_wizard` on Timeweb across at least eight domains — proven by an identical content-hashed CSS bundle (`entry.B59UN0Lb.css`), a shared Vue scoped-style hash, one inline bootstrap script differing only in `configuredSingleSiteKey`, a shared `music_wizard.<siteKey>.web_api_token` localStorage namespace, and Nuxt prerender timestamps showing one sequential CI run on 2026-07-29 between 05:45:50 and 05:50:31 UTC (~33 s apart). Бро.Хит shares none of that infrastructure — different stack, different host, different legal form — and is a genuinely separate operator. Мавикс is a third (ИП Тихонов М.С., Saransk).

---

### What it does NOT do

- **No spoken output of any kind.** No TTS, no narration, no voice greeting, no poem reading. Speech exists only as input. Exhaustive greps of both clients' full i18n payloads, all 38 shipped JS chunks and 423 channel posts return no TTS/narration/speech-output key. (Nor does any other bot in the surveyed cohort.)
- **No voice cloning.** Vocal choice is gender only — no timbre, no named voices.
- **No stems, no multitrack, no WAV export.** The only alternate mix is the full instrumental.
- **No pronunciation control as a feature.** The documented remedy is a user-side workaround (capitalise the stressed vowel yourself); if it still comes out wrong, pay again.
- **No lyric-language selector.** Russian-only in practice: a 13-locale switcher (en, de, es, fr, it, pl, pt-BR, tr, ru, uk, ar, ja, ko) with a `POST /api/me/language` persister exists in client code, but every locale-prefixed route 404s on both hosts. Real code, dead routing — roadmap, not shipped.
- **No partial edit of a rendered track.** "После генерации трек нельзя изменить."
- **No audio preview before payment** beyond the one onboarding demo, stated as policy.
- **No referral programme in any primary artefact.** No referral/invite strings in either client; the offer mentions only promo codes; `/ref`, `/referral` and `/partner` all 404; free songs come from channel giveaways. The review network describes a promo-code referral granting a free song to both sides, and one site claims a bot menu item «пригласить друга» — **unsupported by any primary source**, and a bot-side menu is exactly the kind of thing this evidence base cannot see.
- **No distribution to streaming.** The only streaming activity was a one-off crowd-sourced "AI album" announced April 2026 whose release was never announced.
- **No published refund policy, no receipt-email field, no named payment provider in any legal document, no named AI provider.**
- **No retention mechanic.** No birthday reminders, no saved recipients, no lifecycle at all — which is worth holding next to the MAU curve above.
