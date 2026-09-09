# Scope of Work — HBD Bot

**AI celebration kit for Telegram: one brief → one song + three spoken greetings, with the recipient's name pronounced correctly.**

Version 1.0 · Working document · All jurisdictional statements are drafting input for counsel, not legal advice.

---

## 1. Project summary and objective

### 1.1 What we are building

A Telegram bot. The user enters the full name of a friend or relative, answers four short structured questions, and receives a **celebration kit**: one AI-generated song in the chosen genre and language, three AI-generated spoken congratulatory voice messages in three different character voices, and a lyric sheet — all produced from a single brief, all naming the recipient, all pronouncing that name correctly.

### 1.2 Objective

Own the gap that the entire researched market leaves open. Three findings from the competitive research define the product:

1. **Nobody pairs a song with speech.** Across seven Russian AI-song bots, ten open-source implementations of the same stack, and the one celebrity-greeting product in the adjacent niche, **no product anywhere produces an AI song and an AI spoken greeting from one brief**. Speech appears in every song bot as *input* only (voice-message transcription). Two separate markets exist; the bridge does not.
2. **Nobody solves name pronunciation.** The category leader's documented remedy is a user-side workaround — add stress marks or capitals yourself — and if it still comes out wrong, pay for another full generation. Wrong stress is the second-loudest complaint in its review corpus. For Uzbek names, run through RU/EN-weighted models, the failure rate is far higher.
3. **No Uzbek-language product exists in the niche at all.** The category leader ships a 13-locale switcher in client code with every locale route returning 404. Uzbekistan is an unoccupied, Telegram-native market.

Two secondary objectives follow from the observed economics:

4. **Do not import the category's dominant failure.** Every operator surveyed charges a full new generation to fix one mispronounced word. That single mechanic — not the price — generates their entire complaint corpus. At ~$0.28 direct COGS against a ~$5.90 sale, free re-renders are affordable and are the cheapest differentiation available.
5. **Build a retention loop.** No competitor has one. The category leader's Telegram monthly-user badge went 16,629 (Aug 2025) → 668,356 (Jan 2026) → 45,801 (Aug 2026), an ~89% collapse against 25% for a control bot over the same window. A one-shot occasion purchase with no return trigger is structurally short-lived. Birthdays recur; the product should too.

### 1.3 Markets and languages

**v1: Uzbekistan first**, plus international users served in Russian and English. Interface and output languages: **Uzbek (Latin default, Cyrillic toggle, both scripts complete at launch), Russian, English**, with interface and output language chosen independently. **The Russian Federation is geo-gated out of v1** — see §7.4 and D-3.

### 1.4 What decides whether this works

Three numbers, and none of them is the music. On the per-request billing assumption the music is roughly $0.05 of a $0.28 COGS on a $5.90 sale; if P0-V finds per-asset or per-second billing it is roughly $0.10 of $0.33. **Either way the music is the smallest of the three levers** — which is the point, and which is why this assumption changes the feature and the marketing claim but not the viability.

| Lever | Range | Effect |
|---|---|---|
| Payment rail | ~1.5% (Payme/Click) vs ~32% (Telegram Stars on mobile) | −$0.09 vs −$1.89 per order |
| Free-tier waste | $0.72 (competitor pattern) vs ~$0.12 (our design) | 2.5× COGS vs 0.4× COGS |
| Data-residency posture | Determines whether the Russian Federation — the home market of every bot in the researched cluster — is addressable at all | Binary |

Spend the engineering attention accordingly.

---

## 2. Reference implementation: @bro_hit_bot

`@bro_hit_bot` is **the largest of the seven bots in the 199–500 ₽ Russian price cluster this research covered, and the only one of those seven for which Telegram renders a monthly-user badge at all** — 45,801 monthly users as of 26 Aug 2026. It is **not** the largest AI-song bot on Telegram: the prior research records **Songraiter at 20,011, SoNata at 18,781 and SpoetKa at 14,853** monthly users, all badged, none inside the price cluster, and none surveyed here in depth. The superlative is scoped to the cluster deliberately; read wider it is unsupported. Within that cluster it is also the best-documented. It is a Suno wrapper (proven from `made with suno; created=…; id=<uuid>` ID3 frames on delivered files) with a four-input chat wizard, free editable lyrics, a hard per-generation paywall, and a separately-walleted animated-clip upsell. A full teardown accompanies this document.

**A provenance rule that governs every claim below: nobody ran `/start`.** Everything attributed to the bot was read from its web twin `brohit.ru` (whose server-rendered payload ships the complete i18n dictionary), from public offers, from unauthenticated JSON endpoints, and from ID3 tags on delivered MP3s. The web twin renders "Start Bot", not "Launch App", and contains no Telegram WebApp SDK — so it is not a Mini App and its keyboard and its payment modal are not evidence of the bot's. Two facts must be observed in-bot before FR-54–FR-56 and FR-63/FR-70 are frozen: **which Bot API method delivers the file, and where the bot takes payment.**

### 2.1 What we take

| Behaviour | Why |
|---|---|
| **Free, unlimited, editable lyrics before the audio paywall** | Every operator in the category converged on this independently. It builds sunk-cost commitment before any money is asked for, and it is licensed as free for the whole contract term in the leader's own offer. |
| **Paywall position: after the user has seen text, before any audio** | Validated by seven operators independently. |
| **Option lists as data, not as code** | Their wizard's question objects (`{key, value, title, question, answers}`) arrive with the page rather than being hardcoded in the client, which is a sound shape and we adopt it. **What the evidence does and does not support:** it was read from a Next.js app's server-rendered RSC i18n payload (`common.steps.questions.*.answers`) — that is a **build artefact**, and it establishes that the *client* does not hardcode the lists. It does **not** establish that the operator can change a chip without a deploy; a Next.js redeploy is a release. **So this is our requirement on its own merits, not a copied capability.** FR-11 and FR-28 require field sets and genre lists to be **DB-backed runtime configuration**, and their acceptance tests say exactly that — a config change alters the keyboard **with no deploy and no restart**, which is a stronger property than anything observed in the competitor and must be built rather than inherited. |
| **Voice-message input, transcribed server-side** | First-class and shipped across the cluster (20 MiB cap). Cheap, and it removes typing friction from the longest field. |
| **Occasion picker with birthday first**, 8+ genres, vocal-gender selection | Proven shape. We add regional genres and a mood picker. |
| **Mood picker** | They ship four moods — but only inside the clip product. Their song wizard has none. We adopt it into the song flow, which is where their own users needed it. |
| **Share pages with a `robots.txt` allow-list** for `TelegramBot`/`Twitterbot`/`facebookexternalhit` only | Exactly their configuration and exactly the right one: previews render, search engines do not index strangers' personal gifts. |
| **Structured post-delivery defect categories** | They ship these; we add "name pronounced wrong" as a first-class category because it is our differentiator's own health metric. |
| **Prepaid credit denomination in the ledger** | Every operator uses it. We denominate internally but sell one SKU at launch (§7.1). |
| **Debit before the provider call, refund on failure** | Universal in every mature reference implementation, with the code comment explaining why: otherwise a user walks the wizard again during the 1–3 minute wait and takes a free generation. |

### 2.2 What we deliberately do differently

| They do | We do | Why |
|---|---|---|
| Sung output only. No speech anywhere. | **Song + three spoken greetings from one brief.** | The gap. This is the product. |
| Name pronunciation is the user's problem; capitalise the stressed vowel yourself. | **A pronunciation dictionary, LLM respelling fallback, a free ~3-second name preview before payment, and free re-renders after.** Displayed lyrics keep the original spelling; only the engine payload is respelled. | The mechanism that makes pronunciation control invisible. Their approach both looks broken in the lyric sheet and rarely works. |
| Russian-only in practice (13 dead locales in client code). | **Uzbek, Russian, English, with output language chosen independently of interface language.** | No Uzbek product exists in the niche. |
| One free demo *song* for new users. | **Static pre-rendered samples + free lyric drafts + a ~3-second name preview. Never a free song render.** | At 10% conversion their pattern costs ~$0.72 per paid order — 2.5× the COGS of the thing being sold. |
| One lyric draft. | **Two materially different drafts**, free. | Turns the buy decision into a choice between goods rather than a leap of faith. Negligible marginal cost. |
| A Suno-backed pipeline renders two clips per request and bills per request; their song product surfaces one and charges again for the other. **This is verified for that pipeline only.** | **Every asset a paid generation produces is delivered; the buyer designates one as the gift** (FR-30). | Charging twice for one generation is the mechanic we are refusing. **The "zero marginal provider cost" claim is deliberately not made here:** it is a billing property of Suno via a reseller — a provider LR-37 forbids us from using — and nothing is established about ElevenLabs Music or Google Lyria. P0-V measures asset count and billing unit for our actual providers before Phase 1; FR-30a/FR-30b select the product on the finding. |
| Regenerating to fix one word costs a full new credit. | **One free re-render per kit for any reason, plus free name-pronunciation re-renders of voice greetings.** | The single loudest complaint in every competitor review corpus. Costs ~$0.28; a support hour costs more. |
| No refund clause appears in any offer examined; `/refund` 404s; the FAQ contradicts the offer. | **A published, plain-language refund policy with automatic execution for the common cases, stating exactly what a refund does and does not take back.** | Their inconsistency is both a reputational liability and an enforceability problem. |
| **Contested — reported as an unresolved conflict in the evidence, not as a fact.** Two independent primary probes of `brohit.ru` disagree. The money probe reports **three materially different offer versions live simultaneously** — `/terms` dated 22 Jan 2026, `/agreement` dated 07 Mar 2026, `/oferta` dated 19 Jun 2026, the two older covering only the bot and the newest the whole service. The identity probe reports that **`/terms` and `/agreement` serve the same ИП Пермяков oferta text**. Both are marked verified-primary; both cannot be right; the conflict is unresolved and is **not** relied on. | **Exactly one live offer version at one canonical URL**, with a version id, an effective date, versioned acceptance records, and superseded versions archived at stable URLs. | Our requirement stands on its own: a user who accepted version *n* must be governed by version *n*, and that is only demonstrable if exactly one version is ever live and every acceptance is recorded against a version id. What is separately and non-contestedly established about the incumbent is recorded in the rows above and below, and either of those would carry this requirement on its own. |
| Offer claims the user holds exclusive copyright; separate clauses take back a free perpetual worldwide publishing licence, under an offer accepted by merely visiting the site. | **We assign whatever rights we hold and grant a broad commercial licence, disclose plainly that AI output may not attract copyright, and take no publishing licence back without separate affirmative opt-in.** | Their claim is one their supply chain cannot support. Ours must be one ours can. |
| Suno via a reseller. | **ElevenLabs Music primary / Google Lyria fallback. No reseller in any paid path.** | Reseller access breaks the commercial-rights chain, so we could not honestly tell a paying customer what they may do with the file, and it carries an upstream termination risk that would take the product offline without notice. |
| Consumer contract names ИП Пермяков (ИНН 344713025915); the mandated disclosure page names ООО «Бро.Хит» (ИНН 3444282987) as seller of the identical price list. | **Offer entity = acquiring entity = receipt entity.** | Stated as a requirement because the most successful bot in the cluster gets it wrong. |
| No retention mechanic at all. | **Opt-in birthday reminders with a one-tap prefilled repeat order, scheduled in the recipient's owner's local time.** | Their MAU collapsed ~89% in seven months. |
| Photo upload for the clip product. | **No third-party photo or voice upload anywhere in v1.** Cover art is produced server-side from a licensed template set. | Compounds the non-consenting-recipient exposure and opens the cloning attack surface. |
| Celebrity-persona greetings (the adjacent VIP Pozdravik product, 1190–2590 ₽). | **Original character personas only, each licensed or commissioned, with a named same-language substitute. Absolute prohibition on public-figure impersonation.** | Banned by every major TTS provider's terms — a violation is simultaneously a legal exposure, a personality-rights exposure and a supply-cutoff risk. |

### 2.3 What we explicitly do not copy from the cluster

The five-bot ООО «МАКУ» brand farm (one Nuxt codebase, eight domains, one CI run, deliberately individuated branding and separate IPs within one hosting provider) and the undisclosed affiliate placement that promotes it — a vc.ru "best bots" listicle whose links 302 through a redirector to `?start=ref_…` with no advertising disclosure, and which misprices one of its own subjects. We adopt referral `start` parameters (FR-60); we do not adopt undisclosed placement.

---

## 3. Scope

### 3.1 In scope for v1

- Telegram chat bot (not a Mini App, not a web app), aiogram 3.x.
- Three languages: Uzbek (Latin + Cyrillic, both complete at launch), Russian, English. Interface language and output language selected independently.
- One occasion end-to-end — **birthday** — with a complete structured field set; anniversary and free-text custom occasion as `SHOULD`.
- One kit = 1 song generation, delivering every asset that generation produces (FR-30), + 3 spoken greetings + verified name pronunciation + lyric sheet.
- Name-pronunciation subsystem: dictionary, normalisation, LLM respelling fallback, pre-payment preview, post-delivery free re-render, admin review queue and learning loop. The seed dictionary is a delivered, provenance-tracked and licensed data work package, not an assumption.
- Free tier: static samples, one free lyric-draft round + two free refinements, one short name preview. **Never a free song render.**
- Payments: Payme + Click (Uzbekistan) and Telegram Stars, behind one abstraction. Single-kit SKU at launch; ledger denominated in kit credits, with credits treated as a liability until consumed.
- Delivery: `sendAudio` for songs with full metadata and server-rendered cover art, `sendVoice` for greetings, forwardable share pack, opt-in public share page.
- Opt-in birthday reminders with one-tap prefilled repeat orders, fired in the user's stored timezone under a rate-governed fan-out.
- Order history, re-download, published refund policy, one-tap problem reports, structured quality feedback, and a support desk with a system of record and an entry point reachable without a working Telegram session.
- Moderation pipeline, data-protection plumbing, operator console (including provider balance and quota, dispute and chargeback handling, settlement and deferred-revenue reporting), observability, on-call rota and incident runbook.

### 3.2 Out of scope for v1 (deliberate exclusions, not oversights)

**Not building:** animated or AI video clips of any kind; karaoke video, burned-in subtitles, lyric videos; stems, multitrack or WAV export; instrumental/backing-track generation; distribution to streaming platforms; a web application or Telegram Mini App; accounts, login or cross-device sync; a song editor or any partial re-render (the free re-render is the answer; a real editor is not achievable on these providers); user-uploaded audio or photos beyond a voice brief; third-party image models in the request path; native mobile apps; a public API.

**Not supporting:** any language beyond the three (each additional language is ~4 engineer-days plus a permanent native-reviewer commitment); cloning any voice other than the buyer's own with recorded consent — public-figure and third-party cloning is out of scope permanently, not just for v1; users in jurisdictions whose data-residency requirements our infrastructure does not satisfy; enterprise SSO, SLAs or on-premise deployment.

**Not doing:** manual fulfilment beyond the Phase 0 concierge test's 30-order cap; custom orders taken over DM; any subscription or recurring billing; paid affiliate networks (user-to-user referral is in scope); a second messaging platform (MAX, VK, WhatsApp); storing a recipient's birth year, in any table, export or log.

### 3.3 Deferred to a named later phase

Multi-kit packs (Phase 2), five additional occasions (Phase 2), Russian market with RU-resident storage and YuKassa (Phase 2R, gated on D-3), B2B bulk orders and branded templates (Phase 3), sender-voice cloning (Phase 3, gated on D-10 and a separate compliance programme). The dispute and chargeback console may ship in Phase 2 behind a manual runbook; its ledger treatment may not — that is Phase 1, because the ledger shape must be right from the first transaction.

---

## 4. Functional requirements

**Conventions.** `MUST` = no launch without it. `SHOULD` = v1.1, build the seam now. `LATER` = out of v1, recorded so it is not designed out. Every requirement carries an observable pass condition; a requirement with no falsifiable test is not a requirement.

### 4.1 Onboarding and language (FR-1 – FR-8, FR-94)

**FR-1 (MUST)** On `/start` from a user with no stored language, the first and only message is a language chooser (Русский / Oʻzbekcha / English). *Test:* a fresh `telegram_id` receives exactly three language buttons and no other interactive control.

**FR-2 (MUST)** Language persists against `telegram_id`; `/lang` reopens the chooser without destroying an in-progress order. *Test:* switch language mid-wizard; the wizard resumes at the same step with all field values intact.

**FR-3 (MUST)** Uzbek renders Latin by default with a Cyrillic toggle, and both scripts ship at launch. *Test:* `Tugʻilgan kun` → `Туғилган кун`; all buttons and error strings switch together.

**FR-4 (MUST)** Output language for lyrics and speech is captured separately from interface language, defaulting to it, overridable in one tap. *Test:* interface RU + output UZ produces Uzbek lyrics and Uzbek speech with Russian bot strings.

**FR-5 (MUST)** After language selection the bot offers a **static pre-rendered sample pack** — one ~25 s song excerpt and one ~20 s spoken greeting per language — never a live free generation. *Test:* playing samples any number of times triggers zero provider calls and creates no order.

**FR-6 (MUST)** Before the first field capturing a third party, the bot displays a recipient-data notice and the user acknowledges it. *Test:* a first-time user cannot reach the name field without a timestamped acknowledgement.

**FR-7 (MUST)** No third-party voice or photo upload path exists. *Test:* a photo, audio file or voice note outside the STT brief field returns a polite refusal and stores nothing.

**FR-8 (SHOULD)** Free-text fields accept a Telegram voice message, transcribed server-side, capped at 20 MB / 300 s. *Test:* a 45 s voice note populates the facts field with editable text; a 25 MB file is rejected with a specific error.

**FR-94 (MUST)** Uzbek script parity is complete and enforced: every user-visible string, button, error message and legal surface exists in both `uz-Latn` and `uz-Cyrl`, and user input is accepted in either script and normalised to a single pronunciation key. *Test:* a CI check asserts every locale key exists in both `uz-Latn` and `uz-Cyrl` and fails the build on any gap; a scripted full-wizard run in `uz-Cyrl` encounters zero Latin strings; `Гулнора` and `Gulnora` resolve to the same `name_pronunciations` row (FR-47). *Rationale:* Uzbekistan is the only launch market, both-script moderation is already mandatory, the Latin↔Cyrillic transliteration table and its round-trip tests are already built for the pronunciation pipeline, and the offer and privacy policy are already required in Uzbek. The residual work is translation and native QA of the string catalogue, not engineering. A Cyrillic-reading buyer meeting a half-translated interface in our only market is a launch defect, not a backlog item.

### 4.2 Occasion and field sets (FR-9 – FR-19)

**FR-9 (MUST)** Occasion picker with birthday first and visually dominant. *Test:* birthday is the first button in the first row in all three languages.

**FR-10 (MUST/SHOULD/LATER)** `MUST`: birthday with a complete field set. `SHOULD`: anniversary and a free-text custom occasion. `LATER`: wedding, new year, Navruz, 8 March, new baby, professional holidays, corporate. *Test:* birthday reaches delivery end-to-end; LATER occasions are absent from the keyboard, not present-but-broken.

**FR-11 (MUST)** Field sets are declarative configuration — field key, type, required flag, enum values, validation, per-language label — not code. *Test:* add a four-field occasion by config change and reload; it appears and completes an order with no deploy.

**FR-12 (MUST)** Birthday field set, in order: (1) `name_as_sung`, required, ≤40 chars, labelled "enter the name exactly as it should be sung", with one positive and one negative example; (2) `relationship`, required enum; (3) `age`, optional 1–120 with an explicit "don't mention age"; (4) `address_form`, required (FR-14); (5) `facts`, 2–3 entries, minimum 2, ≤200 chars each, entered one at a time; (6) `mood`, required enum. *Test:* the order cannot advance to draft generation missing name, relationship, address form, mood, or with fewer than two facts. Age omitted is accepted.

**FR-13 (MUST)** After `name_as_sung`, the bot echoes it in isolation for confirmation. *Test:* every name entry produces an echo containing that exact string before the next field.

**FR-14 (MUST)** `address_form` captures grammatical gender and the T–V distinction: RU `{ты·муж, ты·жен, вы·муж, вы·жен, нейтрально}`; UZ `{sen·erkak, sen·ayol, siz·erkak, siz·ayol, neytral}`; EN `{he, she, they, name-only}`. The captured value governs every generated text. *Rationale:* an LLM guessing wrong turns a gift to a grandmother or a boss into an insult. No competitor captures this.

The user-visible promise is *"a вы order never ships a ты form"*. It is delivered by three mechanisms, of which the detector is only the second, and none of which is asked to be perfect.

**(a) Generation-side control.** The address form is an explicit constraint in the lyric and greeting prompts, and the model is required to emit, as a structured field alongside the text, the address form it believes it used. *Test:* 100% of lyric and greeting generations carry the self-reported field (contract test on the schema); a mismatch between requested and self-reported triggers exactly one re-roll.

**(b) A closed-vocabulary detector with a measured error rate.** Not a general morphological analyser — a bounded lexicon plus a bounded suffix set:
  - **RU:** the ты-pronoun paradigm in all cases (ты, тебя, тебе, тобой, о тебе), the твой/твоя/твоё/твои possessive paradigm in all cases, the 2nd-person-singular verb endings (-ешь, -ёшь, -ишь) and the singular imperative, each with a curated exception list (e.g. -шь nouns such as `мышь`, `ночь`; fixed phrases).
  - **UZ, both scripts:** sen / senga / seni / sening / senda / sendan, the -san/-sen personal endings, the -ing possessive, and their Cyrillic forms, normalised through the FR-47 apostrophe and script rules first.
  - *Test, with the bar stated as a measurement:* on a **held-out evaluation set of 200 lines per language** — 100 containing a вы/siz violation, 100 clean — hand-labelled by the native reviewer and never used to tune the rules, the detector achieves **recall ≥ 0.98 on violations and precision ≥ 0.90**, and the measured figures are recorded in the release notes. The recall bar is the binding one; false positives cost only a re-roll.

**(c) A fallback that cannot violate.** A flagged line triggers one re-roll. A second flag routes the order to the **name-only** address form, which has no T–V distinction in any of the three languages, and the user is told the text was rendered without direct address. *Test:* a fixture whose generations are forced to violate twice delivers a name-only text and never delivers a ты/sen form on a вы/siz order; asserted end-to-end. The detector is re-validated per occasion when new occasions ship, because occasion changes the register of the surrounding text.

**FR-15 (MUST)** Age appears at most once in the lyric, or never if suppressed. *Test:* automated check — the integer and its written form appear ≤1 time; 0 times with suppression on.

**FR-16 (MUST)** Mood enum: warm/touching, funny, celebratory, ironic, wistful. Applied to song and greetings. *Test:* the selected value is present in both the music and TTS payloads.

**FR-17 (MUST)** A summary screen before draft generation with per-field back-edit that returns to the summary, not to the start. *Test:* edit `mood` only; all other values unchanged.

**FR-18 (MUST)** Free-text fields are scanned for recognised artist/band names; matches are stripped or flagged before any provider call. *Test:* a brief containing a well-known band name produces a sanitised provider request containing no such token. *Rationale:* a real, observed provider rejection (`Tags contained artist name`) that otherwise burns a paid generation.

**FR-19 (SHOULD)** A first-time birthday brief completes in ≤90 s of user time; a repeat order for a saved recipient (FR-73) in ≤30 s. *Test:* timed usability run, n≥5 per language, median within budget.

### 4.3 Lyric drafts — free, before the paywall (FR-20 – FR-27)

**FR-20 (MUST)** On brief submission, generate and display **two complete** lyrics — full verse/chorus structure, not excerpts — free, with no card on file. *Test:* an account with zero balance receives 2 full drafts; provider billing shows LLM cost only, zero music cost.

**FR-21 (MUST)** Drafts differ in chorus hook and structural approach. *Test:* pairwise token overlap of chorus lines <40%; failures trigger one silent re-roll before display.

**FR-22 (MUST)** Every draft contains `name_as_sung` at least twice including once in the chorus, and passes the FR-14 address checks. *Test:* pre-display assertion; a failing draft is not shown.

**FR-23 (MUST)** Each draft uses at least two of the supplied facts.

*Pre-launch acceptance — this is the gate, and it is executable before a single customer exists:*
1. **Judge validation first.** The native reviewer hand-labels a 100-draft calibration sample per language for "how many supplied facts are referenced". The LLM judge is admissible only if it agrees with the human label on **≥90% of items with Cohen's κ ≥ 0.7** per language. Below that the rubric is revised and the calibration re-run. An unvalidated judge produces no admissible number.
2. **Frozen evaluation set.** A fixed set of **100 briefs** spanning the three languages, the relationship enum, and both the 2-fact and 3-fact cases, committed to the repo and versioned.
3. **Bar:** **≥95% of drafts reference ≥2 supplied facts**, measured by the validated judge over the frozen set. Stated with its interval, per this document's own rule: at 95/100 the Wilson 95% interval is **[88.8%, 97.9%]**. It is a **point-estimate bar with a reported interval**, deliberately, because a *lower-bound* rule at 95% would require **n ≈ 173** evaluated drafts per language — stated here so nobody later mistakes the point estimate for a guarantee.
4. **Regression:** the frozen set runs on every prompt-template change and every lyric-model change, and a drop below the bar blocks the rollout.

*Post-launch monitoring (SHOULD — a monitor with an alert threshold, explicitly not a launch gate):* sampled human review of `min(50, 10% of the week's orders)` with a **floor of 10** — where a week yields fewer than 10 orders the sample rolls forward until 10 accumulate, so the metric is defined at any volume. Alert (SEV-3) when the rate over the trailing 30 reviewed orders falls below 90%. Owner: the founder, or the native reviewer for the Uzbek stream.

**FR-24 (SHOULD)** Drafts are screened against a per-language banned-phrase list, and line syllable counts are checked against a **per-language, per-section syllable band** — not against tempo.

- The band is a **hand-set editorial parameter** in the per-language lyric guide, signed off by the native reviewer, e.g. RU verse 7–11 and chorus 5–9 syllables per line. It is a configuration value, not a derived quantity.
- **Its evidentiary basis:** the Phase 0 sung clips are additionally labelled by the reviewer for "words crammed or rushed", and each band is set to the syllable range that carried no crammed labels. If Phase 0 produces too few sung clips per section type to support this, the launch band is the reviewer's editorial judgement and is marked as such in the lyric guide.
- *Test:* (1) a seeded banned phrase never reaches the user — pre-display assertion on fixtures; (2) syllable counting is a pure unit-tested function per language, agreeing with a **200-line reviewer-labelled set per language on ≥95% of lines exactly**; (3) a line outside its band by >30% triggers exactly one re-roll of that draft, asserted on fixtures; (4) the band in force and the measured per-line distribution are written to the order so the rule can be audited after the fact.
- **Recorded explicitly:** *we do not control, request or observe the music model's tempo.* The syllable band is a consistency and scansion control, not a tempo-matching mechanism, and it is not evidence that any particular line will be sung comfortably.

**FR-25 (MUST)** Free unlimited inline editing of the chosen draft before payment. Editing is client-side: the user's text is stored verbatim and no model call is made. *Test:* ten successive edits produce zero charges and zero provider calls.

**FR-26 (MUST)** "Write different ones" re-runs the draft set, capped at **2 free rounds** per order (admin-configurable, FR-89), on a cheaper model tier than the paid path. Beyond the cap the user is offered to edit or proceed. *Test:* the third regeneration is refused with an explanatory message; the cap is changeable in admin without deploy. *Resolution note:* the functional draft proposed 3 uncapped-cost rounds and the commercial draft's free-tier budget did not close at that number; 1 round + 2 refinements on a cheap model is the reconciled figure (§7.3).

**FR-27 (MUST)** Drafts, edits and the brief persist server-side. *Test:* kill the session mid-flow; 24 h later `/start` offers "continue your unfinished gift" with all state intact.

### 4.4 Song generation (FR-28 – FR-37)

**FR-28 (MUST)** At least eight genres, server-driven (FR-11), with a free-text escape. Regional genres for the UZ market are added at launch. *Test:* the keyboard renders from config; a config change changes it without deploy.

**FR-29 (MUST)** Vocal gender: female / male / duet / any, with the vocal descriptor placed first in the style string. *Test:* selection present in the payload, descriptor in first position.

**FR-30 (MUST)** A paid generation delivers **every asset that generation produced, at no additional charge to the buyer**. The order model treats a generation as producing a list of one or more variants: schema, storage, delivery order, share pack and order history handle *n ≥ 1* with no code change, and the count comes from the routed adapter's `variants_per_call` capability metadata — it is **read, never assumed**.

*Test:* a single paid order yields exactly `variants_per_call` assets for the routed provider; each asset has a distinct `provider_remote_id` and a distinct `sha256`; all appear in `/orders`; designating one as the gift does not delete the others; and for `n = 1` the delivery sequence, share pack and history render correctly with no empty slot. Duration inequality is **not** a pass condition — `sha256` inequality is the correct distinctness test.

*Test (the cost assumption, made to fail loudly instead of silently):* for any provider where `variants_per_call > 1`, the order's `cogs_usd` for an *n*-asset delivery is within 5% of the recorded single-asset reference cost for that provider. This is the executable form of "zero marginal cost", and it breaks the build rather than the margin if the assumption is wrong.

*Standing note.* `variants_per_call` and the billing unit are **unknown** for ElevenLabs Music and Google Lyria. The two-variants-per-request, bill-per-request behaviour is a verified property of a **Suno**-backed pipeline only, and Suno resellers are forbidden in any paid path by LR-37. Nothing about Suno's billing transfers to a provider we do not use. The Phase 0 provider billing-shape measurement (**P0-V**, delivered by M0.5) establishes, for every configured music provider, the number of distinct assets one accepted request returns, the billing unit read from the vendor's own usage surface, and whether a request returning *k* assets is charged differently from one returning a single asset.

**FR-30a (MUST, conditional)** Applies iff P0-V finds, for the selected primary, `variants_per_call ≥ 2` **and** a charge that does not increase with the additional asset: both assets are delivered, the buyer designates one as the gift (FR-58), both persist in order history, and "both versions, one price" is a marketing claim. *Test:* a single paid order yields two assets, both in `/orders`, designating one does not delete the other, and the order's `cogs_usd` matches the single-asset reference cost within 5%.

**FR-30b (MUST, conditional)** Applies iff P0-V finds one asset per request, or billing that scales with assets: one asset is delivered per paid generation. A second variant is **not** a v1 feature, the kit definition and paywall copy describe a single song, and the COGS model moves to the per-asset line. *Test:* a single paid order yields one asset and the delivery sequence, share pack and history render with no empty slot.

Neither branch is written into the product before the Phase 0 memo names which applies. The `variants` list, the capability metadata and both delivery paths are built in Phase 1 regardless; only the copy and the marketing claim are branch-dependent.

**FR-31 (MUST)** Music generation goes through an internal interface with ElevenLabs Music primary and Google Lyria fallback. **No Suno reseller API in any paid path.** *Test:* the capability switch (FR-87) redirects new jobs to the fallback within 60 s with no deploy and no user-visible error.

**FR-32 (MUST)** Charge/consume before the provider call; reverse automatically and fully on failure, timeout or content rejection, with a reason-naming notification. *Test:* force a provider 5xx; entitlement restored within 60 s. Re-running the wizard during a pending generation cannot yield a second free generation.

**FR-33 (MUST)** Job timeout 300 s. Only a true terminal success state is treated as done. *Test:* a job stuck in an intermediate state for 300 s is failed and refunded; no delivery is attempted with an empty asset URL. *Rationale:* the documented trap in this API family — intermediate statuses expose partial payloads and audio URLs exist only in the final state.

**FR-34 (MUST)** One status message, edited through at least three phases, deleted immediately before assets are sent. *Test:* exactly one status message exists at any time; it is gone when audio arrives.

**FR-35 (MUST)** Jobs run through a queue with a configurable global concurrency cap (default 15), below the provider ceiling; users waiting >60 s see a queue position. *Test:* submit 40 jobs; zero rate-limit rejections; the 40th user sees a position.

**FR-36 (MUST)** Each paid kit carries **one free re-render for any reason**, not consuming the next entitlement, plus **free re-renders of spoken greetings for name pronunciation** (up to 2 per greeting, FR-52) which do not consume it. A song re-render for pronunciation consumes the one free re-render. *Test:* entitlement before == after a greeting pronunciation re-render; the song re-render decrements the counter and the counter is visible to the user. *Resolution note:* the functional draft offered 2 pronunciation + 1 vocal-gender song re-renders and the commercial draft offered one per kit. Reconciled on cost: a greeting re-render is ~$0.01, a song re-render is ~$0.20, so greetings are free and songs draw on the single entitlement.

**FR-37 (LATER)** Named character vocal personas beyond gender. Any future personas must be licensed or wholly synthetic.

### 4.5 Spoken greetings (FR-38 – FR-45)

**FR-38 (MUST)** At least three named, non-celebrity spoken personas per output language, each with a free pre-rendered sample and a designated same-language substitute. *Test:* every persona has a playable zero-cost sample in all three languages, and every persona-language pair names its substitute.

**FR-39 (MUST)** Greeting scripts derive from the same brief as the lyrics — same name spelling, relationship, address form, facts, mood. The user re-enters nothing. *Test:* greeting scripts reference at least one of the same facts, use the identical name spelling, and pass the FR-14 address checks. **This is the product's core differentiator.**

**FR-40 (MUST)** Each greeting is 20–45 s. *Test:* measured duration in range; out-of-range output is regenerated once, then trimmed at a sentence boundary.

**FR-41 (MUST)** Greetings are delivered with `sendVoice` as OGG/Opus mono so they render as native waveform voice bubbles, not attachments. Other provider formats are transcoded first. *Test:* the delivered message type is `voice` and a waveform renders on mobile and desktop. *Rationale:* this is what makes the greeting feel like a person left a message. Do not compromise it for convenience.

**FR-42 (MUST)** Speech routes by language: RU/EN → ElevenLabs, UZ → Yandex SpeechKit. Routing is derived from the output-language field and invisible to the user. *Test:* a UZ order's TTS requests hit only the UZ provider; an outage on one language does not affect the others.

**FR-43 (MUST)** All three greetings are produced by default; the buyer may deselect personas before generation. *Test:* deselecting one results in two greetings and two provider calls.

**FR-44 (MUST)** No persona may be named after, marketed as, or trained on a real identifiable person, and no user-supplied reference audio is accepted. *Test:* persona catalogue signed off before launch; no upload path exists in the codebase.

**FR-45 (SHOULD)** Greeting scripts are shown as editable text before TTS is called; one free edit. *Test:* editing the script changes the rendered audio at no cost.

### 4.6 Name-pronunciation subsystem (FR-46 – FR-53, FR-95)

*The product's second differentiator. Across the entire researched market, nobody solves this.*

**FR-46 (MUST)** A dictionary maps a normalised name key → per-engine respelling, stress marking and IPA, per output language, seeded with the ~2,000 most common Uzbek and Russian given names and diminutives. *Test:* a seeded name resolves with zero LLM calls, logged with source `dictionary`.

**FR-47 (MUST)** Resolution order: exact key → normalised key (case-folded, `ё/е` unified, Uzbek apostrophe variants `oʻ/o'/o` and `gʻ/g'/g` unified, Latin and Cyrillic forms unified, hyphen/space stripped) → LLM respelling fallback. *Test:* `Gulnora`, `Gulnoraʼ`, `GULNORA`, `Gul-nora` and `Гулнора` all resolve to one entry; an unseeded name falls through.

**FR-48 (MUST)** For unresolved names, an LLM returns ≥2 ranked candidate respellings plus IPA with a confidence score, cached against the normalised key; low-confidence results queue for admin review (FR-91). *Test:* an invented name returns ≥2 candidates; a second order with the same name makes no LLM call; a low-confidence result appears in the queue.

**FR-49 (MUST)** The respelled form is injected into the engine payload; **the lyrics displayed to the user retain the original spelling exactly as entered**. *Test:* where respelling differs, payload and displayed strings differ and the displayed string is byte-identical to `name_as_sung`.

**FR-50 (MUST)** Engine-appropriate markup: SSML phoneme tags where supported, `+` stress marks before the stressed vowel for Yandex SpeechKit, grapheme respelling where nothing is supported (music models accept nothing but orthography). *Test:* per-engine payload snapshot tests for all three languages.

**FR-51 (MUST)** Before the paywall, the bot renders and sends a ~3 s TTS clip of the name alone in the output language, with Yes / "Sounds wrong" controls. "Sounds wrong" advances to the next candidate and re-previews, up to 3 candidates, then offers manual respelling. *Test:* delivered before any payment, at no cost; selecting an alternative changes the stored respelling used downstream. *Rationale:* the highest-leverage requirement in this document per unit of effort — it pre-empts the entire complaint class before money changes hands.

**FR-52 (MUST)** Every delivered song variant and voice message carries a "Name sounds wrong" control, re-rendering that asset with the next-ranked candidate — free for greetings (up to 2 per asset), drawing on the FR-36 entitlement for songs. *Test:* greeting re-render leaves entitlement unchanged and uses a different respelling; the third press explains the cap and routes to support.

**FR-53 (SHOULD)** Accepted respellings (user-confirmed, or delivered with no complaint within 7 days) are promoted to the admin review queue; approvals are written into the dictionary and rejected candidates demoted. *Test:* after approval, the next order with that name resolves from the dictionary with no LLM call.

**FR-95 (MUST)** The ~2,000-name seed dictionary (FR-46) is a delivered work product, not an assumption. Every entry carries source, licence, contributor and date; no entry has source `unknown`; no entry is taken from a source whose terms forbid extraction or redistribution (LR-65). Two-pass native review per language before launch. Coverage is measured, not claimed: ≥90% of the 80-name corpus and ≥90% of distinct names in the first 500 production orders resolve from the dictionary with zero LLM calls. *Test:* a provenance query returns zero unknown-source rows; the coverage figure is computed from production `name_pronunciations.source` at launch +30 days and reported on the FR-92 dashboard.

### 4.7 Delivery and sharing (FR-54 – FR-61, FR-96)

**FR-54 (MUST)** Delivery order: each song variant in turn (`sendAudio`, in the order the generation returned them) → each greeting (`sendVoice`) → final lyrics as text → share card (FR-58). *Test:* the message-type log matches this sequence exactly for any variant count *n ≥ 1*.

**FR-55 (MUST)** Every `sendAudio` sets `title`, `performer`, `duration` and a cover-art `thumbnail`. *Test:* the bubble shows a human-readable title and cover art, and the scrubber shows correct length before playback.

**FR-56 (MUST)** Delivery retry ladder: `RetryAfter` → wait `retry_after + 30`; network-class → retry after 60 s, up to 3 attempts; user-blocked → mark and stop; anything else → send a signed download URL as text and flag for admin. *Test:* each failure class is exercised in a harness; no class results in a silently lost paid order.

**FR-57 (MUST)** All assets are copied to our own object storage on completion and served from signed URLs; no delivery path depends on a provider CDN URL. *Test:* with provider URLs expired in a fixture, re-download (FR-78) still works. *Rationale:* provider-side files are retained ~15 days.

**FR-58 (MUST)** A single "Send to the recipient" control produces a forwardable message set the buyer forwards in Telegram. **The recipient is never required to start the bot.** *Test:* forward to an account that has never interacted with the bot; all audio and voice messages play, no "start the bot" wall appears.

**FR-59 (SHOULD)** Each gift optionally gets a public page at `/g/<short_code>` with Open Graph tags; `robots.txt` disallows `/g/` for all crawlers but allows `TelegramBot`, `Twitterbot`, `facebookexternalhit`. **Opt-in only** (see D-11) and the recipient's name is absent from the OG preview. *Test:* a pasted link renders a preview card; a generic crawler UA is refused; the exact allow-list is present.

**FR-60 (MUST)** The share page carries a "Make one like this" CTA with a referral `start` parameter; opens and conversions attribute to the originating order. *Test:* a click produces a `/start` with the parameter and the resulting order is attributed. *Note:* we adopt the mechanic, not the undisclosed-affiliate practice observed in the category's marketing.

**FR-61 (SHOULD)** The buyer can disable the public page; disabling returns 404 thereafter for all user-agents including allow-listed crawlers. *Test:* toggle off, then the URL 404s.

**FR-96 (MUST)** A server-side cover-art producer renders the cover required by FR-55 and FIL-2 from a versioned, licensed template set (background library + typography), composed deterministically from `(occasion, mood, genre, language, seed)`. No third-party image model sits in the request path at launch, and no user-supplied image is ever accepted (FR-7). The template version is recorded on the asset. *Test:* the same seed renders a byte-identical object; p95 render ≤2 s; no `sendAudio` is attempted without a cover, asserted pre-send.

### 4.8 Payment and paywall (FR-62 – FR-70)

**FR-62 (MUST)** The paywall sits after the user has seen two complete drafts and selected/edited one, and before any music or speech generation. *Test:* across a full funnel run, zero billable music and TTS calls occur before successful payment, excepting only the ~3 s name preview (FR-51) and static samples (FR-5).

**FR-63 (MUST)** Payment rails by region: Payme and Click for Uzbekistan; Telegram Stars available but never pre-selected as the default on mobile; YuKassa only if D-3 admits the RU market. *Test:* a UZ-locale user's primary button is Payme or Click; Stars requires an extra tap.

**FR-64 (MUST)** The v1 SKU is **one completed kit**: one song generation — delivering every asset that generation produces, per FR-30 — plus 3 greetings and the FR-36 re-render entitlement. The internal ledger is denominated in kit credits so packs need no rework, but exactly one SKU is sold at launch and no wallet UI exists. *Test:* the purchase flow contains no balance concept; the order transitions directly from paid to generating. *Resolution note:* the functional draft rejected credit packs outright and the commercial draft argued for them. Reconciled: credit ledger internally, single SKU externally, packs in Phase 2 once the refund policy is proven operationally.

**FR-65 (LATER)** Multi-kit packs priced per kit. Phase 2.

**FR-66 (MUST)** Promo codes: percentage, fixed-amount and free-order, with expiry, total usage cap and per-user cap, editable in admin without deploy. *Test:* expired, exhausted and already-used codes each produce a distinct tested message; a free-order code completes with a zero-amount transaction recorded.

**FR-67 (MUST)** Prices per region and currency are editable in admin without deploy, and are versioned data — a purchased kit is governed by the price-list and offer versions in force at capture, both written to the order. *Test:* change the UZ price; the next UZ user sees it with no restart, and an existing order's recorded versions are unchanged.

**FR-68 (MUST)** Every payment carries an idempotency key; duplicate webhooks never double-charge or double-fulfil; a failed payment never leaves an order generating. *Test:* replay the same webhook 5 times; exactly one order fulfilled, one transaction recorded.

**FR-69 (MUST)** Fiscal receipts are issued where the rail and jurisdiction require it, with a receipt-email field collected where required. *Test:* a completed payment stores a receipt reference against the transaction.

**FR-70 (SHOULD)** Where the rail supports it, checkout completes inside Telegram rather than redirecting to an external browser. *Test:* completing a payment never leaves the Telegram client on iOS or Android. *Caveat:* an embedded non-redirecting checkout is verified only on a competitor's *website*, which is not a Mini App. This must be validated against Telegram's current payment policy directly, not by analogy (D-2).

### 4.9 Retention loop (FR-71 – FR-76, FR-97 – FR-102)

**FR-71 (MUST)** Immediately after delivery, offer to remember this recipient's birthday — **day and month only** — in one tap. Explicitly opt-in, with the consent timestamp recorded in `reminders.consent_at`. *Test:* declining stores nothing and never re-asks for that order; accepting creates a recipient record carrying a day and a month and no year.

**FR-72 (MUST)** Reminders fire at D-7 and D-1 (configurable), in the stored language, naming the recipient, with one primary action. *Test:* a seeded recipient 7 days out receives exactly one reminder on the correct day in the correct language.

**FR-73 (MUST)** The reminder's primary action opens a pre-filled brief: same name, same resolved pronunciation, same relationship and address form, last year's facts as editable suggestions, and an age suggestion derived by adding the elapsed whole years to the age given in the brief that supplied it. The suggestion is editable and is never stored as a fact. *Test:* a repeat order reaches the draft stage in ≤3 taps and ≤30 s, with pronunciation resolved from the record with no LLM call; an order twelve months on suggests age+1; an order whose brief gave no age suggests none.

**FR-74 (MUST)** `/recipients` lists saved recipients with edit and delete, plus a global "stop all reminders". *Test:* deleting removes the record and cancels scheduled reminders; the global switch suppresses future reminders while preserving order history.

**FR-75 (MUST)** Stored recipient data is limited to name as entered, any disambiguation label, relationship, address form, day and month, and the last brief's facts; records with no activity for 24 months are purged automatically. *Test:* a seeded aged record is purged by the scheduled job and the purge is logged.

**FR-76 (MUST)** At most one reminder message per user per calendar day; coinciding recipients are batched. *Test:* three recipients on the same date produce exactly one message naming all three.

**FR-97 (MUST)** Reminder fan-out is scheduled and rate-governed, not fired at once. The scheduler spreads each day's due reminders across a configurable per-user local send window (default 09:00–21:00, target hour per FR-98) with deterministic per-user jitter, and never exceeds a configurable global reminder send rate (default 20 msg/s) drawn from a token bucket **separate from and subordinate to** transactional delivery, which always pre-empts it. Reminders deferred past the window roll to the next day's window, never dropped. *Test:* seed 50,000 reminders due on 1 January; observed peak reminder rate ≤ cap, zero Telegram 429s attributable to reminders, no paid-order delivery waits >5 s behind the fan-out, and every seeded reminder is sent exactly once within its window.

**FR-98 (MUST)** Timezone is captured, stored and used. Each user carries a stored IANA timezone, defaulted from region at language selection (UZ → `Asia/Tashkent`), confirmed in one tap at the first reminder opt-in, editable in `/recipients`. Reminders fire at a per-user local hour (default 10:00, admin-configurable per FR-89). Where the timezone is unknown the market default applies and the opt-in copy says so. Changing a timezone reschedules all pending reminders. *Test:* three users in `Asia/Tashkent`, `Europe/Moscow` and `Europe/London` with a recipient 7 days out each receive their reminder within ±15 min of 10:00 local.

**FR-99 (MUST)** Duplicate and ambiguity guard. An occasion cycle key `(recipient_id, occasion, cycle_year)` governs the loop. (a) A reminder is suppressed if a paid, delivered order already exists against that key. (b) Two saved recipients of one user whose names normalise identically require a disambiguation label at save time; the label appears in `/recipients` (FR-74) and in every reminder. (c) FR-73's prefill against an already-covered cycle shows an explicit "you already sent one this year — order another?" confirmation before a second paid kit can be created. *Test:* order → the D-7 reminder for that key produces zero sends; a second "Aziz" cannot be saved without a label; prefill on a covered cycle requires the extra confirmation, and declining creates no order.

**FR-100 (MUST)** 29 February. A 29-February recipient fires on 28 February in non-leap years by default, per-recipient switchable to 1 March at save time; the D-7 and D-1 offsets are computed from the resolved fire date, not from the stored day and month. *Test:* a 29-Feb recipient in 2027 receives D-7 on 21 February and D-1 on 27 February; with the alternate rule, 22 and 28 February.

**FR-101 (MUST)** Blocked and dead chats leave the schedule. A user-blocked verdict from the FR-56 ladder suspends, in the same transaction, all reminders and broadcasts to that user (`reminders.status = suspended_blocked`) and excludes them from FR-90 dry-run counts, delivered counters and the FR-92 funnel denominators. Any subsequent inbound update from that user reactivates the schedule. A recipient record whose owner has been suspended for 24 months is purged by FR-75 as normal. *Test:* block the bot → the next due reminder produces zero send attempts and the user is absent from the dry-run count; `/start` after unblocking restores the schedule and the next reminder sends.

**FR-102 (MUST)** The recipient birth year is not stored anywhere. No schema column, API field, export or log may contain a recipient birth year, and the reminder record holds day and month only. *Test:* a schema and export scan finds no recipient birth-year field, enforced by a CI check that fails any migration adding one. *Rationale:* day and month is not a date of birth; the year is the component that would turn the record into one. The reminder — the entire Phase 2 business case — needs day and month and nothing more, and the only thing the year would buy is an arithmetic convenience FR-73 derives from data we already hold. Day and month under the explicit opt-in of FR-71, recorded in `reminders.consent_at` and purged at 24 months of inactivity (FR-75), *is* minimisation; keeping the year is not. This also makes LR-59's rule — never ask for a child's exact date of birth — true by construction rather than by exception.

### 4.10 History, refunds, support (FR-77 – FR-83, FR-103 – FR-106)

**FR-77 (MUST)** `/orders` lists every order — date, occasion, recipient, status, assets — paginated. *Test:* a user with 25 orders can reach the oldest.

**FR-78 (MUST)** Any asset can be re-sent from history for the retention period (§6.5), reusing the cached Telegram `file_id` where available. *Test:* re-send a 90-day-old song; correct metadata, zero bytes transferred when a `file_id` is cached.

**FR-79 (MUST)** A refund policy is published in-bot and linked from checkout: automatic full refund for technical failure or non-delivery; discretionary refund on quality grounds within 24 h of delivery, decided and communicated within 24 h; free re-renders (FR-36, FR-52) offered first. *Test:* reachable in ≤2 taps from checkout in all three languages; a seeded technical-failure order is auto-refunded unprompted.

**FR-80 (MUST)** Every delivered order carries "Problem with this order", opening a ticket pre-populated with order id, provider job ids and the brief. *Test:* the ticket contains all three identifiers without the user typing them.

**FR-81 (SHOULD)** The stated response time is shown at ticket creation and ticket state is visible to the user. *Test:* an admin state change reflects to the user within 60 s.

**FR-82 (SHOULD)** Post-delivery star rating plus structured defect categories — *name pronounced wrong · wrong voice/gender · lyrics · music · spoken greeting · other* — with optional free text. *Test:* feedback stored against the order with its category and queryable per category per week.

**FR-83 (MUST)** A user can request deletion of their account data, removing recipients, briefs and personal fields and anonymising retained transaction records. *Test:* recipient records and personal fields removed within the stated window; financial records survive anonymised.

**FR-103 (MUST)** Paid but undeliverable orders. An order that is paid and generated but cannot be delivered (FR-56 user-blocked, or the ladder exhausted) enters status `undelivered`: assets are held for the full FIL-7 retention, one delivery retry fires on the next inbound update from that user, and if still undelivered **72 h** after generation completed the order is auto-refunded in full with reason code `undeliverable` and no operator action. `undelivered` orders are a named admin queue and are excluded from delivered-revenue and margin reporting until resolved. *Test:* block the bot immediately after payment → assets are held, the refund is issued at 72 h unprompted, and the order never appears in delivered revenue; unblocking at 48 h delivers the kit and cancels the pending refund with no double-refund.

**FR-104 (MUST)** What a refund after delivery takes back. A refund on a delivered order: (a) does **not** revoke or delete the audio already sent — a Telegram delivery is irreversible and pretending otherwise is dishonest; (b) takes the public share page (FR-59) down within 60 s and revokes signed URLs and re-send from history (FR-78); (c) leaves the order visible in `/orders` marked refunded, with its assets purged on the normal FIL-7 schedule and not extended; (d) increments a per-user refund counter that routes the fourth refund request in a rolling 12 months to an operator instead of the automatic path (LR-22). *Test:* refund a delivered order → `/g/<code>` returns 404 within 60 s, re-send is refused with the published policy copy, the order shows `refunded`, the counter increments and the fourth request queues for a human.

**FR-105 (MUST)** Support has a system of record and a money entry point outside Telegram. Every ticket (FR-80) is created in one ticket store with id, user, order, category, state, assignee and first-response/resolution timestamps. A support entry point reachable **without a working Telegram session** — a published email address and a web form on our own domain — accepts payment, refund, delivery and account issues, not only erasure (LR-53) and abuse (§6.9), and lands in the same queue as in-bot tickets. *Test:* a user who has blocked the bot opens a payment ticket through the web form, it appears in the same queue as an in-bot ticket, and the reply reaches them by email; a query for "tickets opened outside Telegram, last 7 days" returns them.

**FR-106 (SHOULD)** Support hours and a first-response target (proposed: 12 h, seven days a week) are published on the support page and shown at ticket creation (FR-81). Out-of-hours tickets receive an automatic acknowledgement naming the next response window. *Test:* a ticket created at 03:00 receives the acknowledgement within 5 min naming a concrete time; rolling 7-day median first response is inside the published target, reported on the OBS-7 dashboard.

### 4.11 Admin surface (FR-84 – FR-93, FR-107 – FR-111)

**FR-84 (MUST)** Order queue with filters (status, language, region, date, provider) showing brief, provider job ids, timings and asset links. *Test:* locate an order by recipient name or order id in under 10 s.

**FR-85 (MUST)** Orders generating beyond a threshold (default 10 min) are surfaced automatically; an operator can re-run generation without charging again. *Test:* a seeded stuck order appears in the alert list; a manual re-run delivers and creates no new charge.

**FR-86 (MUST)** One-click refund from the order view against the correct rail, writing an audit entry (operator, timestamp, amount, reason code) and notifying the user. *Test:* refund on each live rail reconciles and produces an audit entry and a notification.

**FR-87 (MUST)** Independent per-capability kill switches: music, RU/EN speech, UZ speech, lyric LLM, pronunciation LLM, STT. Each toggles primary→fallback or pauses intake, effective for new jobs within 60 s, no deploy. *Test:* flipping UZ speech routes UZ orders to the fallback while RU is unaffected.

**FR-88 (MUST)** When no provider is available for a capability, new orders requiring it are blocked **before payment** with a clear message and an optional notify-me. *Test:* with all music providers down, a user cannot reach checkout; existing paid orders queue and fulfil on recovery.

**FR-89 (MUST)** Prices per region/currency, promo codes, free-regeneration caps (FR-26), free re-render counts (FR-36), reminder offsets (FR-72), the reminder local send hour and window (FR-97, FR-98), the reminder send-rate cap (FR-97) and the concurrency cap (FR-35) are editable in admin without deploy. *Test:* each change takes effect for the next order without restart and is audit-logged.

**FR-90 (SHOULD)** Segmented broadcast (language, region, days since last order, has/has-not saved a birthday, last rating) with scheduling, a dry-run count shown before send, throttling within Telegram's limits, marketing opt-out honoured, and live delivered/blocked/failed counters. *Test:* the dry-run count matches a direct query; a real send respects throttling, skips opted-out users, and reports accurately.

**FR-91 (MUST)** Pronunciation review queue where low-confidence and user-corrected respellings are approved, edited or rejected; approvals write to the dictionary. *Test:* after approval, the next order with that name resolves with no LLM call.

**FR-92 (MUST)** Funnel and unit-economics dashboard, per day / language / region: brief started → drafts shown → paywall shown → paid → delivered → re-render used → rated; plus direct COGS per order by provider, the `cost_source` mix, and provider error rate and latency percentiles.

*Test (a) — launch gate, executable with no vendor dependency:* every stage count reconciles against the event log with zero variance on paid-order counts; **100% of `generations` rows carry a non-null `cost_usd` and a `cost_source`**; the per-order COGS figure is displayed with its source label, so a `derived` or `estimated` number is never presented as an invoice-backed one.

*Test (b) — invoice reconciliation, monthly, at the granularity the invoices actually have:* for each provider, the sum of `cost_usd` over the invoice period reconciles to the vendor invoice total for that provider within **5%** where `cost_source` is `vendor_reported` or `derived`, and within **15%** where it is `estimated`. Variance outside tolerance is a SEV-3 and drives a correction to the unit-price config, which is versioned. The dashboard shows the current period's variance per provider, so the trustworthiness of the per-order number is visible next to the number.

Test (a) is a **launch gate**. Test (b) is a **MUST operational duty on the first invoice after launch**, with a named owner and a date, and monthly thereafter — it cannot be a launch gate because the first invoice does not exist at launch. Where a sandbox or trial invoice is available pre-launch, one reconciliation is run against it and recorded, as a dry run of the procedure.

**FR-93 (MUST)** Append-only, exportable admin audit log of every mutating action with operator identity, timestamp, target and before/after values. *Test:* one action of each type appears with complete before/after values; no admin path writes without logging.

**FR-107 (MUST)** Global "pause new orders" switch. One global switch, independent of FR-87's per-capability kill switches, that blocks intake **before payment** in all languages with configurable copy and an optional notify-me, leaves paid in-flight orders generating and delivering, is effective within 60 s with no deploy, and is operable by any on-call role (SEC-8 `ops` and above). *Test:* flip it — a new user cannot reach checkout in any language, an in-flight paid order still delivers, an audit entry with operator and reason is written, and un-flipping restores intake within 60 s.

**FR-108 (MUST)** Provider balance and quota panel. Admin shows per provider per capability: prepaid balance or remaining quota, currency, `as_of` timestamp, and days-of-cover computed against trailing 7-day burn. A provider under its configured floor renders as degraded and is excluded from router selection (API-9). *Test:* a seeded low balance renders the warning and the days-of-cover figure matches a hand calculation from `generations.cost_usd`; a stale `as_of` older than 60 min is shown as stale, not as healthy.

**FR-109 (MUST)** Dispute and chargeback case handling. A dispute is a first-class state on the order and the payment. The admin dispute view shows the rail case id, opened and deadline timestamps, reason code, and a one-click **evidence pack** containing order id, brief hash, consent event and offer version, capture record, generation and delivery timestamps, delivered message ids, asset checksums, and any device/IP data the rail supplies. Accepting or contesting writes an audit entry (FR-93) and a ledger entry; a lost dispute revokes entitlement, marks the order `refunded_by_dispute` and writes the payment identity to the SEC-7 abuse list per SEC-14. *Test:* a seeded dispute webhook produces a case with its deadline; the generated pack contains every listed field; a lost case leaves ledger, entitlement and ban list mutually consistent, asserted in one query.

**FR-110 (MUST)** Accounting settlement export. A per-period, per-rail export (CSV and JSON) with one row per money event: transaction id, order id, capture timestamp, legal entity, rail, gross, `fee_minor`, net, currency, FX rate recorded at capture, refunds and dispute adjustments with dates and reason codes, receipt reference, SKU, and price-list/offer version. Totals reconcile to the `payments` table with zero variance. This is a settlement report for a bookkeeper and is distinct from FR-92's product dashboard and FR-93's admin audit log. *Test:* export one month; per-rail totals equal that rail's own statement within the rail's rounding; a refunded and a disputed transaction each appear with the correct sign; re-running the export produces an identical file.

**FR-111 (MUST)** Unredeemed-credit and deferred-revenue report. A month-end report of unconsumed credits: count, credit balance, money value at the price in force at capture, age buckets, and expiries falling in the period (LR-5), reconciling to `credits_ledger`. *Test:* seed grants, consumptions and expiries — closing balance equals opening + granted − consumed − expired, with no manual adjustment.

---

## 5. User flow specification

Screen by screen, for a first-time Uzbek-language buyer ordering a birthday kit for their mother. Bracketed IDs cite the governing requirement.

**S1 — Language gate.** `/start`. Four buttons: Русский · Oʻzbekcha · Ўзбекча · English. Nothing else. The choice sets the interface language, the Uzbek script and the default timezone for the market. [FR-1, FR-94, FR-98]

**S2 — Sample pack.** "Here's what you'll get." A 25 s song excerpt and a 20 s spoken greeting, both static files, both in Uzbek. Buttons: *Boshlash* (start) · *Yana namunalar* (more samples). No generation occurs. [FR-5]

**S3 — Recipient-data notice.** One short paragraph: what we collect about the person, that we never contact them, how long we keep it, how to have it deleted; and a confirmation that the user is entitled to provide it. One acknowledgement tap, timestamped. Shown once per user. [FR-6, LR-54]

**S4 — Occasion.** Birthday first and visually dominant, then anniversary, then "something else" (free text). [FR-9, FR-10]

**S5 — Name.** "Enter the name exactly as it should be sung." Helper text with one good and one bad example (`Dilnoza` ✅ / `Rahimova Dilnoza Akmalovna` ❌). [FR-12]

**S6 — Name echo.** "We'll sing: «Dilnoza». Correct?" → Yes · Edit. [FR-13]

**S7 — Name pronunciation preview.** A ~3-second voice message of the name alone. "Is this how it's said?" → Yes · Sounds wrong. "Sounds wrong" plays the next candidate; after three, an inline field accepts a manual respelling. Free, before any payment. **This is the moment the product proves its differentiator.** [FR-51]

**S8 — Relationship.** Enum keyboard: mother, father, wife, husband, daughter, son, sister, brother, friend, colleague, boss, grandparent, other. [FR-12]

**S9 — Age.** Number entry, or "don't mention age". An age is a fact about this order, never a stored date of birth. [FR-12, FR-15, FR-102]

**S10 — Form of address.** For Uzbek: *sen (erkak) · sen (ayol) · siz (erkak) · siz (ayol) · neytral*. One tap. The screen the entire market omits. [FR-14]

**S11–S13 — Facts, one at a time.** "Tell me one thing about her." → "One more." → "One more, or skip." Free text or voice message. Minimum two. [FR-12, FR-8]

**S14 — Mood.** warm · funny · celebratory · ironic · wistful. [FR-16]

**S15 — Genre.** Eight+ chips including regional options, plus "describe it yourself". [FR-28]

**S16 — Vocal.** female · male · duet · any. [FR-29]

**S17 — Voice personas.** Three named characters with free sample playback; all three selected by default, deselectable. [FR-38, FR-43]

**S18 — Summary.** Every captured field in one message, each with an edit control that returns to that field and back to the summary. [FR-17]

**S19 — Lyric drafts.** Two complete lyrics, materially different, free. Buttons per draft: *Choose* · *Edit*. Global: *Write different ones* (2 free rounds). Editing is unlimited and free. [FR-20, FR-21, FR-25, FR-26]

**S20 — Greeting scripts.** The three spoken greeting texts, one free edit each. [FR-45]

**S21 — Paywall.** Price, currency, what is included (one song — every version that generation produces — 3 voice greetings, lyric sheet, one free re-render), refund policy link in one tap, consent line. Payment buttons: Payme · Click · Telegram Stars (secondary). [FR-62, FR-63, FR-79, FR-30, LR-67]

**S22 — Checkout.** In-context where the rail permits. On success, generation fires automatically without a second confirmation tap. [FR-70, FR-32]

**S23 — Wait.** One status message, edited through real phases: *in the queue* → *writing the music* → *recording the voices* → *finishing*. No timer-driven fake progress. If the audio phase exceeds 90 s, the bot offers "we'll ping you — you can close this." [FR-34, ASY-17–ASY-24]

**S24 — Lyrics arrive first.** The moment lyrics are final — 8–20 s in, long before the audio — they are sent as their own message with the name rendered with confirmed stress. The user reads something personal about their mother for the whole audio wait. [ASY-20]

**S25 — Delivery.** Every version the generation produced, in order (`sendAudio`, cover art, title, performer, duration) → three voice messages (`sendVoice`, native waveforms) → lyric sheet as text. Where the generation produced a single version the sequence renders with no empty slot. Status message deleted first. [FR-54, FR-55, FR-41, FR-30, FR-96, FIL-10]

**S26 — Gift designation.** Where more than one version was produced: "Which one is the gift?" → Version 1 · Version 2. Both stay in history. With a single version the step does not appear. [FR-30]

**S27 — Share.** *Send to her* produces a forwardable pack the buyer forwards in Telegram — she needs no bot, no install, no account. Secondary: *Get a link* (opt-in public page). [FR-58, FR-59]

**S28 — Rate.** Stars plus structured categories including *name pronounced wrong*. Every asset also carries an inline *Name sounds wrong* control that re-renders it. [FR-82, FR-52]

**S29 — Save the date.** "Shall I remind you next year, on 14 March?" → Yes · No thanks. Explicit opt-in, one tap plus date confirmation — day and month only, never a birth year. The same screen confirms the timezone we will use ("We'll write to you at 10:00, Tashkent time" → Yes · Change), and asks for a distinguishing label if this user already has a saved recipient whose name normalises the same way. [FR-71, FR-98, FR-99, FR-102]

**S30 — Next year, D-7.** "Dilnoza's birthday is in a week. Make this year's gift?" One tap opens a prefilled brief: same name, same resolved pronunciation, same relationship and address form, last year's facts as editable suggestions, age +1 as an editable suggestion derived from the earlier brief. Three taps to drafts. Where a paid kit for this recipient and occasion has already been delivered this cycle, the prefill first asks "you already sent one this year — order another?" and creates nothing if declined. [FR-72, FR-73, FR-99]

**Failure paths.** Generation failure → entitlement restored within 60 s + a message naming the reason [FR-32]. Content rejection → a plain-language explanation, no charge, a repair path [FR-18, SEC-3]. Capability outage → intake blocked *before* payment with an optional notify-me [FR-88]. Intake paused by an operator → the same pre-payment block in every language, with in-flight paid orders still delivering [FR-107]. Delivery failure → retry ladder, degrading to a signed link and an admin flag [FR-56]; an order that cannot be delivered at all is held, retried on the user's next inbound update, and auto-refunded at 72 h [FR-103]. Abandonment → state persists; `/start` offers to continue [FR-27]. At every failure path the user can open a ticket, and the same ticket can be opened without a working Telegram session, from the support page on our own domain [FR-105].

---

## 6. Technical architecture and non-functional requirements

### 6.1 Components

Thirteen cooperating parts: nine processes and libraries we write, four managed dependencies. **Nothing in the request path does inference** — every generation is displaced onto a queue.

1. **`hbd-api`** — webhook receiver. Verifies Telegram's secret-token header, deduplicates on `update_id`, persists the raw update, hands off to the FSM for a fast reply, returns `200`. Also hosts provider callbacks, payment webhooks, `/healthz`, `/readyz`, `/metrics`.
2. **`hbd-bot`** — aiogram 3.x FSM wizard with `RedisStorage` (never `MemoryStorage`). Every step writes through to the `briefs` table, so an abandoned wizard is a recoverable asset.
3. **`hbd-payments`** — the rail layer. Payme, Click and Telegram Stars behind one abstraction, owning capture, refund, dispute intake and the append-only ledger writes. No handler and no worker talks to a rail directly, and switching the default rail is configuration.
4. **Redis + ARQ** — broker, FSM store, rate-limit token buckets, idempotency set, cache. ARQ over Celery for native asyncio and a smaller operational surface; the queue contract is the only coupling.
5. **`hbd-worker`** — stateless ARQ workers on four queues with independent concurrency: `q:lyrics`, `q:song`, `q:speech`, `q:media`. A music stall cannot starve TTS or delivery.
6. **`hbd-providers`** — the adapter layer (§6.2). No worker imports a vendor SDK.
7. **`hbd-cover`** — the cover-art producer. A deterministic renderer over a versioned, licensed template set (background library, typography, ornament), composing from `(occasion, mood, genre, language, seed)` and emitting both the ID3/`sendAudio` cover and the OG-sized variant used by the share surfaces. It calls no third-party image model in the request path and accepts no user-supplied image. It is a component, not a helper, because FR-55 and FIL-2 make a picture part of every delivery and nothing else in the system makes one.
8. **`hbd-scheduler`** — the single owner of timed work: reminder fan-out across per-user local send windows, the non-terminal generation reconciler, retention and purge jobs, legal-hold expiry, provider balance and quota refresh, synthetic probes, and the post-restore reconciliation run. No web process runs a timer.
9. **Object storage** — S3-compatible (Cloudflare R2 preferred for zero egress). Every artefact mirrored from the provider CDN within seconds.
10. **`hbd-admin`** — FastAPI + HTMX, SSO + IP allowlist. Operational tool for the four things that happen in week one — replaying dead letters, refunding, flipping a provider off, editing the pronunciation dictionary — and the system of record for tickets, disputes and settlement reporting.
11. **Support intake edge** — a published mailbox and a web form on our own domain, writing into the same `support_tickets` queue as in-bot tickets. It is deliberately independent of the bot: it must stay reachable when the bot token is rotated, when Telegram is unavailable to the user, when the user has blocked us, and when intake is paused.
12. **PostgreSQL 16** — managed, PITR, Alembic.
13. **Delivery edge** — unguessable object keys, used once per asset for the first `sendAudio`; thereafter Telegram's own `file_id`.

**Request path.** Telegram → webhook (validate, dedupe, persist, `200`) → FSM replies in-request → payment webhook marks `paid` → enqueue `generate_order` → orchestrator fans out `q:lyrics`, then on approval `q:song` + 3× `q:speech` in parallel → adapter calls provider → completion by callback (preferred) or poll (safety net) → `q:media` mirrors, normalises loudness, renders and embeds the cover, tags, sends, captures `file_id` → order `delivered` → `hbd-scheduler` places the reminder in the owner's local send window.

- **ARC-1 (MUST)** No inference, file download or third-party HTTP call inside a Telegram webhook request.
- **ARC-2 (MUST)** FSM state survives process restart and rolling deploy.
- **ARC-3 (MUST)** Workers horizontally scalable and stateless; adding a replica needs no config change.
- **ARC-4 (MUST)** Admin supports: order search by Telegram id / order id / phone; in-browser playback of every asset; DLQ inspection and replay; refund and credit issue; per-provider kill switch and the global intake pause; provider balance and quota panel; dispute console and evidence pack; settlement and deferred-revenue exports; the ticket queue, including tickets raised outside Telegram; pronunciation dictionary CRUD; moderation review; broadcast composer. *(Irreducible launch minimum if the timeline compresses: DLQ replay, refund, per-provider kill switch, global intake pause.)*
- **ARC-5 (SHOULD)** `docker compose up` brings the whole system up locally against fake providers.
- **ARC-6 (MUST)** Every recurring job is owned by `hbd-scheduler`, is idempotent under duplicate execution and under a missed window, and records its last successful run and the rows it touched. A job that has not run inside twice its interval is an alert, not a silence.
- **ARC-7 (MUST)** The support intake edge shares the ticket store and nothing else with the bot: it has its own hostname, its own deploy, and no dependency on the bot token, on Telegram availability or on the state of the intake pause.

### 6.2 Provider abstraction

This is the most load-bearing architectural decision in the build, and it is justified by evidence:

- **The same model is sold through at least five mutually incompatible reseller APIs** (kie.ai/sunoapi.org, acedata, AIMLAPI, EvoLink, apiframe) with five different request shapes. Code that talks to one is welded to it.
- **Apparent redundancy is often fake.** `api.kie.ai` and `api.sunoapi.org` return byte-identical error bodies, set the same `JSESSIONID`, and sit behind identical Cloudflare configuration — one backend, two brands. Listing both as "two providers" buys zero resilience.
- **Vendors exit.** PiAPI and GoAPI both discontinued Suno access.
- **We may be forced to switch for legal reasons at short notice** (LR-37). One config change is a legal control, not a convenience.
- **No single vendor covers our languages.** Per-language routing is permanent and structural, not a fallback.
- **TTS voices get withdrawn.** Voices are addressed by our own stable identifier, mapped in config.
- **Unit prices differ 3×** for identical output. Cost-based routing requires routing to exist.

- **API-1 (MUST)** No vendor SDK, hostname, field name or error string outside `hbd-providers`. Enforced by an import-linter rule in CI.
- **API-2 (MUST)** Adding a provider = implement one protocol + one registry entry. No changes to workers, handlers, models or admin.
- **API-3 (MUST)** Provider selection is DB-backed runtime configuration editable in admin, not a code constant.
- **API-4 (MUST)** Errors are mapped into our own closed taxonomy: `RATE_LIMITED`, `CONTENT_REJECTED`, `INVALID_INPUT`, `UPSTREAM_TIMEOUT`, `UPSTREAM_5XX`, `QUOTA_EXHAUSTED`, `ARTIST_NAME_IN_STYLE`, `UNKNOWN`. Nothing downstream pattern-matches a vendor string.
- **API-5 (MUST)** `FakeSongProvider` and `FakeSpeechProvider` return fixture audio with configurable latency and failure injection; default in dev and CI.
- **API-6 (MUST)** One contract-test suite runs identically against every adapter: submit → poll/callback → terminal → assets non-empty; rejection path; timeout path; duplicate and out-of-order callbacks.
- **API-7 (MUST)** The router selects by `(capability, language, health, cost)` in that order, with an explicit ordered fallback chain per capability, overridable per order in admin.
- **API-8 (MUST)** Every adapter populates `cost_usd` on every call, together with `cost_source ∈ {vendor_reported, derived, estimated}`. Where the vendor reports a per-call cost, use it (`vendor_reported`). Where it does not but the response exposes a priced usage unit — seconds of audio, characters, tokens, credits — the adapter computes cost from that unit times a config-held unit price (`derived`). Only where neither exists may the adapter fall back to a configured flat estimate (`estimated`), and that provider is listed as such in the provider licence matrix. *Test:* a contract test asserts every adapter returns non-null `cost_usd` and a valid `cost_source` on the success, rejection and timeout paths.
- **API-9 (MUST)** Every adapter exposes `ProviderHealth.balance_remaining`, `quota_remaining` and `as_of` where the vendor publishes them, refreshed at least every 15 min. A `QUOTA_EXHAUSTED` error, or a balance below the configured floor, marks the provider unhealthy for API-7 selection. A vendor publishing nothing reports `unknown`, and its **first** `QUOTA_EXHAUSTED` opens the circuit immediately (ASY-25) rather than waiting for five failures. *Test:* a fixture returning zero balance removes the provider from selection within one refresh interval; an `unknown` provider's first quota error opens its circuit on the first occurrence.
- **API-10 (MUST)** The persona catalogue is configuration: our stable persona id → vendor voice id → licence reference (LR-66) → sample asset → **designated substitute in the same language**. Retiring a voice is a config change that repoints the persona to its substitute for new orders only; delivered assets are never re-rendered. *Test:* retire a vendor voice in staging — new orders for that persona render on the substitute within 60 s, existing assets are unaffected, and the substitution is visible in admin and in the licence matrix.

**Interface shape.** `SongProvider` exposes `generate_song(request, *, idempotency_key, callback_url, timeout_s) -> TaskHandle`, `poll_song(handle) -> TaskResult`, `parse_callback(payload) -> TaskResult | None`, `cancel`, `health`, plus capability metadata (`supports_languages`, `max_lyrics_chars`, `variants_per_call`, `unit_cost_usd`). `SpeechProvider` exposes `generate_speech(request, *, idempotency_key, timeout_s) -> TaskResult` (synchronous by contract) plus `voices` (our id → vendor id), `supports_phoneme_override` and `health`. Domain types are vendor-neutral: `SongRequest`, `SpeechRequest`, `RemoteAsset`, `TaskHandle`, `TaskResult`, `ProviderHealth` (health state, error rate, latency, `balance_remaining`, `quota_remaining`, `as_of`), and `TaskState ∈ {QUEUED, PARTIAL, SUCCEEDED, FAILED, REJECTED}`.

Two contract details are deliberate and must not be "simplified" away:

- **`pronunciations` is a first-class request field carrying grapheme, IPA, stressed form and syllables — not a pre-formatted string.** Each adapter compiles it into what its vendor understands: SSML phoneme tags, `+` stress marks, or (for music, which accepts nothing) a capitalised stressed vowel inside the lyric text. If the caller formatted the markup, adding a provider would mean rewriting the caller.
- **`parse_callback` may return `None`.** Providers in this family fire callbacks in stages and audio URLs exist only in the final one. The single most common integration bug in this category is treating an interim callback as terminal and delivering empty URLs. Encoding "interim" in the type system prevents it once, in one place.

**Routing table (v1).**

| Capability | Primary | Fallback |
|---|---|---|
| Song, any language | ElevenLabs Music | Google Lyria |
| Speech RU / EN | ElevenLabs | Yandex SpeechKit / OpenAI TTS |
| Speech UZ | Yandex SpeechKit | ElevenLabs multilingual (degraded) |
| Lyrics | Claude | GPT-4-class |
| STT | Whisper | Yandex SpeechKit STT |

> **Unverified capability, flagged.** `variants_per_call` and the billing unit are **unknown** for ElevenLabs Music and Google Lyria. The two-variants-per-request behaviour on which FR-30a, the §2.2 differentiation row and the $0.28 COGS line were originally drafted is a verified property of a **Suno**-backed pipeline only, and Suno resellers are forbidden in any paid path by LR-37. Nothing about Suno's billing transfers to a provider we do not use. P0-V measures both properties for every configured provider before Phase 1 opens.

*Resolution note:* the technical draft listed a Suno reseller as fallback-2 behind a legal gate. Removed entirely, per LR-37. No reseller appears in any paid path.

### 6.3 Asynchronous generation

- **ASY-1 (MUST)** Validate the webhook secret token; reject with `403` and no body. The webhook path contains a random 32-char segment.
- **ASY-2 (MUST)** Idempotency on `update_id` (`SET NX EX 172800`). A redelivered "confirm purchase" callback must never double-charge.
- **ASY-3 (MUST)** Raw update JSON persisted before any handling.
- **ASY-4 (MUST)** Return `200` even when handling raised. Telegram redelivery is not our retry mechanism; our queue is.
- **ASY-5 (MUST)** Payment webhooks idempotent on the PSP transaction id, with a unique constraint as the last line of defence.
- **ASY-6 (MUST)** Deterministic job ids (`gen:{generation_id}`) so a duplicate enqueue is a queue-level no-op.
- **ASY-7 (MUST)** Debit before the provider call, refund on terminal failure. [see FR-32]
- **ASY-8 (MUST)** `idempotency_key` = `generation_id`, so a retry after an ambiguous timeout cannot bill twice.
- **ASY-9 (MUST)** Callback URLs carry an opaque signed token, never the Telegram chat id — that leaks a user identifier to a third party and their logs.
- **ASY-10 (MUST)** A reconciler runs every 30 s over non-terminal generations past `poll_after_s`. Callbacks are a latency optimisation; polling is the correctness guarantee.
- **ASY-11 (MUST)** Callback handling is idempotent; variant rows are pre-created at submit time.
- **ASY-12 (MUST)** A 10-minute wall-clock deadline per order across all attempts and providers.
- **ASY-13 (MUST)** Dead-lettering writes full attempt history, moves the order to `failed`, **auto-refunds**, notifies the user with a concrete next step, raises SEV-2.
- **ASY-14 (MUST)** Circuit breaker per provider per capability: open after 5 consecutive failures or >30% error rate over 5 min; half-open probe every 60 s; state mirrored to `providers_health` and shown in admin.
- **ASY-15 (MUST)** DLQ replay as a one-click admin action and a CLI command, capped at 3 replays per generation.
- **ASY-16 (MUST)** Outbound concurrency governed by a shared Redis token bucket at 70% of any published vendor cap.
- **ASY-25 (MUST)** `QUOTA_EXHAUSTED` and payment-required errors are never retried against the same provider, open that provider's circuit immediately, re-route at attempt 1, and raise SEV-1 if no provider remains for the capability — which also triggers FR-88's pre-payment intake block and NFR-20's degraded mode. *Test:* injected `QUOTA_EXHAUSTED` produces zero retries against that provider, exactly one route change, and with the fallback also exhausted, intake for that capability is blocked before payment within 60 s.
- **ASY-26 (MUST)** A captured payment with no matching order is re-run against the matcher every 60 s for 30 min; a matching pending order is fulfilled idempotently; if none is found, a **full automatic refund** is issued at 60 min with reason `unmatched_payment`. The OBS-6 SEV-1 page fires in parallel and the timer does not wait for acknowledgement. *Test:* inject an unmatched payment webhook at 03:00 with no operator response — refunded within 60 min, one ledger entry, one user notification; inject one that becomes matchable at minute 10 — fulfilled exactly once, no refund, no double-charge.

**Retry policy by error class** (the class, not the vendor, decides): *transient* → 5/10/20/40 s ±20% jitter, max 4 attempts; *rate-limited* → honour `Retry-After`, min 10 s, does not consume an attempt, max 8 deferrals; *provider down* → do not retry the same provider, re-route immediately and restart at attempt 1; *quota exhausted or payment required* → the provider-down path, with the circuit opened on the first occurrence (ASY-25); *content rejected* → **never retry**, route to a repair flow, consume no entitlement; *invalid input* → never retry, page on-call, it is our bug.

**The wait UX** is 40 s to 4 minutes and is where the product is delightful or abandoned. It is a designed feature.

- **ASY-17 (MUST)** One status message per generation, `message_id` stored on the row; all progress is `editMessageText` on that message.
- **ASY-18 (MUST)** Edit no more often than once per 5 s, driven by real backend phase, not a timer. Telegram throttles chatty bots, and fake progress destroys trust when it says "almost done" for 90 seconds.
- **ASY-19 (MUST)** Phase copy maps to actual states, with 3–4 rotating variants per phase so a long phase does not look frozen.
- **ASY-20 (MUST — the headline wait feature)** **Send the lyrics the moment they are final**, 8–20 s in, as their own message with the name in its confirmed stressed form. The user spends the entire audio wait reading something personal instead of watching a spinner. This costs nothing and converts the worst part of the funnel into the second-best.
- **ASY-21 (SHOULD)** Where a provider exposes a stream URL before the final file, surface it as "listen while it finishes".
- **ASY-22 (MUST)** Delivery happens as a push whether or not the user stayed; the status message reaches a final state in all outcomes including failure.
- **ASY-23 (MUST)** The status message is deleted immediately before audio is sent, so the chat's final state is the gift, not the scaffolding.
- **ASY-24 (SHOULD)** After 90 s, offer "we'll ping you when it's ready".

### 6.4 Data model

PostgreSQL, UUIDv7 ids, `timestamptz` UTC, soft delete on user-owned rows, hard purge on erasure.

- **`users`** — `tg_user_id` (unique), locale, `ui_language`, `uz_script`, `country_hint`, **`timezone`** (IANA, defaulted from the market at language selection), ban state, free-tier counters, lifetime orders/revenue, `referred_by_user_id`, consent fields, `data_region`, timestamps.
- **`orders`** — status (`draft|awaiting_payment|paid|generating|partially_delivered|delivered|undelivered|failed|refunded|refunded_by_dispute`), `product_sku`, `price_minor`, `currency`, `payment_id`, promo/discount, **`cogs_usd`**, `price_list_version`, `offer_version`, **`is_probe`**, `delivered_at`, `failed_reason`.
- **`briefs`** — occasion, `recipient_name_raw`, `recipient_name_normalized`, `name_pronunciation_id`, age, relationship, **`address_form`**, facts, mood, genre, vocal, lyric/speech language, voice ids, `input_mode`, moderation status and labels, completion/abandonment. **This is the single table subject to erasure.**
- **`generations`** — one row per provider call and the retry/idempotency/cost ledger: `kind`, `sequence`, provider, `provider_remote_id`, state, attempt, **PII-redacted** `request_payload`, `response_raw`, error code/message, `cost_usd`, **`cost_source`**, `latency_ms`, `status_message_id`, `deadline_at`.
- **`assets`** — kind, `variant_index`, storage bucket/key, mime, bytes, duration, `sha256`, `loudness_lufs`, **`tg_file_id`**, provider URL + expiry, `cover_template_version`, `template_licence_ref`, `retention_class`, `expires_at`.
- **`payments`** — psp, `psp_transaction_id` (unique per psp), amount, currency, **`fee_minor`** (the rail cost, measured per transaction), net, FX rate at capture, status, refunded amount and reason, dispute reference, raw payload.
- **`recipients`** — owner user, display label, `name_normalized`, **`disambiguation_label`**, `name_pronunciation_id`, relationship, address form, event **month and day only — no birth year, in this or any other table**, `leap_rule`, `consent_at`, last delivered order, inactivity timer.
- **`reminders`** — recipient reference, occasion, **`occasion_cycle_key`** `(recipient_id, occasion, cycle_year)`, `lead_days`, `next_fire_at`, **`send_hour_local`**, status, **`suspended_reason`**, `send_count`.
- **`name_pronunciations`** — the moat. `grapheme`, `grapheme_normalized`, language, script, `ipa`, `stressed_form`, `syllables`, gender/origin hints, `source` (`curated|user_confirmed|llm_generated|g2p`), licence and contributor provenance, `confidence`, `usage_count`, `correction_count`, verification. Unique on `(grapheme_normalized, language, variant_ordinal)` — one name legitimately has multiple stress patterns, so variants are rows and the wizard asks when count > 1. Trigram index for fuzzy lookup.
- **`providers_health`** — enabled flag, priority, circuit state, error rate, latency percentiles, quota, unit cost. Unique on `(provider, capability)`.
- **`provider_quota`** — provider, capability, prepaid balance, remaining quota, currency, `as_of`, configured floor, days-of-cover against trailing 7-day burn.
- **`disputes`** — payment id, rail case id, `opened_at`, `deadline_at`, state, reason code, evidence-pack reference, outcome, ledger references.
- **`legal_holds`** — subject type, subject id, `opened_at`, `opened_by`, reason, `expires_at`, `released_at`.
- **`support_tickets`** — id, user, order, channel (in-bot, web form, email), category, state, assignee, `first_response_at`, `resolved_at`.
- **Supporting:** `telegram_updates` (30-day), `dead_letters`, `moderation_events`, `credits_ledger` (append-only; balance is the sum, never a mutable column), `restore_reconciliations` (one row per ENV-11 run with its report), `admin_audit_log`.

- **DAT-1 (MUST)** Every money-affecting write is transactional with its ledger or payment row.
- **DAT-2 (MUST)** `generations.request_payload` is redacted — recipient name salted-hashed, free text truncated to 120 chars. Full text lives only in `briefs`.
- **DAT-3 (MUST)** Erasure purges `briefs`, `assets` (objects included), user-sourced pronunciation rows and PII columns within 30 days, leaving financial records intact as tax law requires. **This means the tax record and the personal-data record must be separable at the schema level** — if the brief is a column on the order row, the retention schedule is unimplementable.
- **DAT-4 (MUST)** Alembic migrations only; no manual DDL in any environment.
- **DAT-5 (MUST)** No recipient birth year exists in any column, API field, export or log line. *Test:* migrations apply and reverse cleanly against a seeded database; a CI check fails any migration adding a column matching a birth-year pattern to a recipient or reminder table.
- **DAT-6 (MUST)** A legal hold on a brief, order, asset or moderation record suspends the FIL-7 purge and the DAT-3 erasure **for exactly the held records and no others**. A hold has a named opener, a reason code, and an expiry ≤180 days, renewable once with a recorded justification, released automatically on expiry. Where an erasure request (LR-53, FR-83) arrives against held records, everything not held is erased on schedule, and the requester is told that a subset is retained, on what ground and for how long; that notification is itself logged. *Test:* open a hold on one brief, run the purge job — the held brief survives, its sibling is purged, and the erasure response contains the disclosure; on expiry the record purges on the next scheduled run with no operator action.

### 6.5 File handling and retention

- **FIL-1 (MUST)** Mirror every provider asset to our own bucket within 60 s of completion, before delivery. Provider retention is short and finite.
- **FIL-2 (MUST)** On mirror: `sha256`, duration, loudness normalisation to −14 LUFS, ID3v2.4 tags (title, brand, occasion, order id, "AI-generated"), embedded cover art.
- **FIL-3 (MUST)** `sendAudio` with our URL, always passing `duration`, `title`, `performer`; greetings via `sendVoice` as OGG/Opus. [FR-41, FR-55]
- **FIL-4 (MUST — the cost control)** Capture and persist `file_id` / `file_unique_id` on every successful send; all subsequent sends reuse it — zero bandwidth, zero egress, near-zero latency. `file_id` is scoped to the bot token and is invalidated on rotation; never share across environments.
- **FIL-5 (MUST)** The delivery retry ladder of FR-56.
- **FIL-6 (MUST)** Size envelope: song 3.5–5 MB, greeting 100–400 KB, cover 100–300 KB. Enforced pre-send: audio ≤45 MB, voice ≤1 MB. Inbound voice capped at 20 MB / 300 s with friendly copy, not silent failure.
- **FIL-7 (MUST) Retention schedule** — *this supersedes the conflicting figures in the source drafts:*

| Data | Retention |
|---|---|
| Delivered audio (paid) | **12 months** from delivery, then purge |
| Free-tier / sample-adjacent output | 30 days |
| Ephemeral (user voice input, intermediate renders) | 7 days |
| Abandoned draft briefs | 14 days |
| Free-text brief (recipient facts) | **30 days** from delivery |
| Recipient name + relationship + address form, **no reminder consent** | 90 days |
| Recipient record **with** reminder consent | Until deleted, or 24 months of inactivity (FR-75) |
| Order/payment ledger | As tax law requires (typically 5 years), **stripped of the brief** |
| Moderation logs, unflagged | Verdict + hash survive; brief text deleted at 30 days |
| Moderation logs, flagged or complained-of | 12 months, restricted access, access itself logged |

Users are told the audio retention period in the delivery message. Every row of this schedule yields to an open legal hold, and only for the held records (DAT-6).

- **FIL-8 (SHOULD)** Unguessable object keys, non-indexed hostname, `X-Robots-Tag: noindex`. A public share page is a separate deliberate opt-in (FR-59).
- **FIL-9 (MUST)** Deduplicate on `sha256` before storing.
- **FIL-10 (MUST)** Cover art produced by `hbd-cover` (FR-96): 1000×1000 JPEG, 100–300 KB (already inside FIL-6's envelope), embedded in ID3v2.4 per FIL-2 and passed as the `sendAudio` thumbnail per FR-55, deduplicated on `sha256` per FIL-9 so a repeated template costs one stored object. The template licence reference is recorded on the asset row (LR-64). *Test:* two orders with the same template seed share one storage object; the delivered bubble shows the cover on iOS, Android and desktop, verified per release.

### 6.6 Non-functional targets

Sized for the spike, not the mean. Realistic year-one target: **300–1,500 paid orders/day** with 10× concentration on New Year, Navruz, 8 March and the weekends before them.

**Latency** (user action → artefact in chat, excluding typing):

- **NFR-1 (MUST)** Webhook `200`: p50 ≤120 ms, p95 ≤400 ms, p99 ≤800 ms.
- **NFR-2 (MUST)** Wizard step reply: p50 ≤300 ms, p95 ≤1.0 s.
- **NFR-3 (MUST)** Lyrics: p50 ≤12 s, p95 ≤25 s, hard timeout 45 s.
- **NFR-4 (MUST)** Song (submit → file in our storage): p50 ≤100 s, p95 ≤240 s, hard timeout 420 s.
- **NFR-5 (MUST)** One greeting: p50 ≤8 s, p95 ≤20 s, hard timeout 60 s. Three run in parallel.
- **NFR-6 (MUST)** Full kit, payment → everything delivered: p50 ≤3 min, p95 ≤6 min, hard deadline 10 min.
- **NFR-7 (MUST)** Lyrics reach the user (ASY-20) at p95 ≤30 s after payment, so the perceived wait is ~30 s regardless of the audio tail.

**Throughput and availability:**

- **NFR-8 (MUST)** 60 concurrent in-flight generations, 1,500 orders/day, absorbing a 200-orders/hour burst with no user-visible failure — only a longer, honestly-reported queue.
- **NFR-9 (MUST)** 200 webhook updates/second on a single replica.
- **NFR-10 (MUST)** Per-provider outbound ≤70% of the published cap, enforced across all worker replicas.
- **NFR-11 (MUST)** Backlog degrades gracefully with a real position/ETA; no paid order is ever dropped.
- **NFR-12 (MUST)** Ingest and wizard 99.5% per calendar month; generation pipeline 99.0%, measured as the share of paid orders delivered within the NFR-6 deadline, over the calendar month, excluding `is_probe` orders.
- **NFR-13 (MUST)** Zero-downtime deploys for ingest; drain-then-restart for workers with in-flight jobs completed or re-queued, never lost.
- **NFR-23 (MUST)** Reminders (FR-97) and broadcasts (FR-90) together consume at most 50% of the Telegram global send budget (~30 msg/s), and transactional delivery is never queued behind them. *Test:* load scenario — 50,000 reminders due concurrent with a 200-orders/hour burst — p95 payment→delivery stays within 10% of the quiet-period baseline and no paid order breaches NFR-6.

**Cost:**

- **NFR-14 (MUST)** Direct COGS ceiling **$0.45** per paid kit against a **$0.28** target, measured from `generations.cost_usd`, not assumed.
- **NFR-15 (MUST)** A hard per-order cost circuit breaker at **$0.90**: the order stops, dead-letters and pages rather than retry-looping into an unbounded bill.
- **NFR-16 (MUST)** Free-tier COGS ≤ **$0.15 per free user per rolling 30 days**, and ≤ **$0.12 per paid order** blended at a 10% conversion assumption. Enforced by measurement (OBS-7) and by the per-user caps and rolling-30-day budget of SEC-6, not by assumption.
- **NFR-17 (MUST)** Rail cost recorded per transaction (`payments.fee_minor`) and reported. Checkout defaults to the local rail wherever the region permits.
- **NFR-18 (SHOULD)** Fixed infrastructure ≤ **$150/month** at launch scale, where "fixed infrastructure" means the trailing-30-day sum of non-provider cloud invoices (compute, managed Postgres, Redis, object storage, egress, error tracking, metrics). **Provider spend is not infrastructure and is not inside this ceiling.** Two provider-spend lines exist and are budgeted separately, both reported on the OBS-7 dashboard: order COGS (governed by NFR-14/15/16) and **synthetic-probe COGS ≤ $25/month** (`probe_cogs_usd`, governed by OBS-9c). Total controllable non-order spend at launch ≤ **$175/month**.

**Provider-outage behaviour — required and tested, not hoped for:**

- **NFR-19 (MUST)** On primary failure the router re-routes transparently. The user sees at most a longer wait and is never told which vendor failed.
- **NFR-20 (MUST)** With all providers for a capability unhealthy, the system enters **degraded mode**: new orders refused **before payment** with honest copy and a notify-me; already-paid orders held to the NFR-6 deadline then auto-refunded. **Under no circumstances does the system take money for a capability it cannot currently deliver.**
- **NFR-21 (MUST)** Partial degradation sells a reduced, honestly-labelled product: greetings-only if music is down; Russian speech with explicit consent if Uzbek speech is down.
- **NFR-22 (MUST)** A quarterly game-day forces each provider to fail in staging and verifies NFR-19–21 end to end.

### 6.7 Observability

- **OBS-1 (MUST)** Structured JSON logs, one event per line, every line carrying `correlation_id`, `tg_user_id`, `order_id`, `generation_id`, `provider`, `env`. The `correlation_id` is minted at the webhook and threaded through the queue into provider calls.
- **OBS-2 (MUST)** Per generation: provider, model version, attempt, timestamps, terminal state, latency split (queue / provider / mirror / deliver), `cost_usd`, `cost_source`, `error_code`, redacted request. Enough to answer "why did order X take 6 minutes and cost $0.61" without reproducing it.
- **OBS-3 (MUST)** Never logged at any level: full recipient names in free text, raw voice transcripts, payment card data, API keys, or full provider bodies containing user text. Enforced by a CI scan.
- **OBS-4 (MUST)** Prometheus metrics: `orders_total{status}`, `generations_total{kind,provider,state}`, `generation_latency_seconds{kind,provider}`, `generation_cost_usd_total{provider}`, `queue_depth{queue}`, `queue_oldest_job_age_seconds`, `webhook_latency_seconds`, `telegram_send_failures_total{reason}`, `provider_circuit_state`, `provider_days_of_cover{provider,capability}`, `payment_events_total{psp,status}`, `dispute_events_total{psp,outcome}`, `reminder_sends_total{result}`, `probe_runs_total{tier,result}`, `probe_cogs_usd_total`, `dlq_depth`, `funnel_step_total{step}`.
- **OBS-5 (MUST)** Error tracking with tagged releases and `correlation_id` on every event.
- **OBS-6 (MUST)** Alerts: *SEV-1, page* — any paid order >10 min undelivered; payment captured with no order; all providers down for a capability. *SEV-2* — DLQ +5 in 15 min; generation failure rate >10% over 15 min; any order >$0.60; daily spend >2× trailing 7-day mean; oldest queued job >5 min; webhook p95 >1 s. *SEV-3* — Telegram send failures >2%; provider p95 >2× baseline; >20 moderation blocks in an hour.
- **OBS-7 (MUST)** Hourly business dashboard: orders, revenue, gross margin per order, COGS by provider with the `cost_source` mix, funnel conversion by wizard step, **free-tier cost per paid order**, free→paid conversion, provider mix and days-of-cover, delivery latency percentiles, refund and dispute rate, `probe_cogs_usd`, median support first response, and **contact rate**.
- **OBS-8 (SHOULD)** A per-order trace view in admin showing every generation, attempt, provider, latency and cost — this is what support actually needs, and it removes engineers from the support loop.
- **OBS-9 (MUST) — synthetic probe, three tiers.** The probe is decomposed by what each tier can prove and what it costs, so that continuous assurance does not consume the margin it exists to protect.

  - **OBS-9a — stack probe, every 5 minutes, $0.** A synthetic user (the §8.6 Telethon harness) walks the full wizard on the canary account against the **production** bot, queue, database, object storage and Telegram delivery path, with `FakeSongProvider` / `FakeSpeechProvider` returning fixture audio. 288 runs/day at zero provider cost. *Proves:* ingest, FSM, payment sandbox path, queue, worker, mirror, cover render, `sendAudio`/`sendVoice`, `file_id` capture, status-message lifecycle. *Does not prove:* that any provider works. Failure → SEV-1 page (detection ≤10 min).
  - **OBS-9b — provider reachability, every 15 minutes, $0.** Per configured provider, one authenticated **non-billable** call (models/voices/quota endpoint, or the vendor's own health route). Any provider with no non-billable authenticated endpoint is recorded as such in the provider licence matrix and covered by OBS-9c only. *Proves:* credentials valid, DNS, TLS, 5xx, quota headers, region reachability. *Does not prove:* that a generation completes or that its output is good. Failure → SEV-2, and → SEV-1 if it is the last healthy provider for a capability.
  - **OBS-9c — real-generation probe, suppression-gated and budget-capped.** A real generation on each song provider (**primary and fallback**) and each speech provider, subject to:
    - **Suppression:** skipped for any `(provider, capability)` that has had a **production** generation reach terminal success within the previous 4 hours. Real traffic is free evidence; at the NFR-8 volume of 300–1,500 orders/day the primary is suppressed almost always and the cost accrues only in genuinely quiet windows and on the fallback.
    - **Hard cap:** ≤3 song probes/day and ≤6 speech probes/day, enforced by a counter in the same cost ledger as NFR-15, not by cron spacing.
    - **Cost, stated so it can be checked:** 3 × $0.20 + 6 × $0.01 = **$0.66/day = $19.80/month**, against a declared probe budget of **$25/month** (NFR-18). The fallback — the one component whose failure is invisible until it is needed — is exercised daily.
    - **Budget breach behaviour:** month-to-date `probe_cogs_usd` above $25 suppresses OBS-9c and raises SEV-3. The probe never silently overspends and never silently stops.
    - Probe orders are tagged `is_probe = true`, are excluded from funnel, revenue, COGS-per-order and conversion metrics, and are asserted excluded by a test — otherwise the probe corrupts the numbers it exists to protect.
  - **What no probe covers, said plainly.** A provider that returns HTTP 200 and musically valid audio in which the name is mispronounced is invisible to all three tiers. That failure is caught by the §8.6 nightly regression and the weekly human sample, not by a probe, and the runbook says so.

- **OBS-10 (MUST)** SEV-2 when a paid provider's days-of-cover falls below 7 or its balance below the configured floor; SEV-1 when a capability's last remaining healthy provider reports zero balance or returns `QUOTA_EXHAUSTED`. A daily digest reports balance and days-of-cover for every paid provider. *Test:* seeded balances fire each alert within 5 min in staging; the digest arrives daily and its figures match FR-108.
- **OBS-11 (MUST)** A named on-call rota covering seven days is published in the runbook with contact channels and a named primary and secondary. SEV-1 pages the primary; unacknowledged at 15 min it escalates to the secondary, at 30 min to the founder; **unacknowledged at 60 min it automatically trips FR-107 (pause new orders)** and posts the honest intake copy. Acknowledgement, escalation and auto-pause events are logged. *Test:* fire a staging SEV-1 with no acknowledgement — each escalation and the auto-pause occur on schedule and are logged; acknowledging at 10 min stops the ladder.

### 6.8 Environments, secrets, deployment

- **ENV-1 (MUST)** Three environments — dev (fake providers, no money), staging (sandbox providers and PSPs, **its own bot token**), prod. A bot token binds to one webhook URL, so separate bots are the only correct isolation.
- **ENV-2 (MUST)** Secrets in a managed store. None in committed `.env` files, CI logs, images or the admin UI. `gitleaks` blocks in CI.
- **ENV-3 (MUST)** Documented secret inventory with owners and 90-day rotation (immediate on suspicion or personnel change): bot tokens, webhook secret, provider keys, PSP credentials, storage keys, DB and Redis URLs, Sentry DSN, admin SSO secret.
- **ENV-4 (MUST)** CI-built Docker images tagged by commit SHA; rollback = redeploy the previous SHA in under 5 minutes; migrations run as a gated step and are expand/contract compatible with the previous release.
- **ENV-5 (MUST)** Typed settings module failing fast at boot on a missing or malformed value; precedence env → DB settings → defaults.
- **ENV-6 (MUST)** Nightly Postgres backup with PITR, 30-day retention, and **a restore drill executed and documented before launch**. An untested backup is not a backup.
- **ENV-7 (MUST)** Primary region chosen for lowest latency to Tashkent. **RU is geo-gated out of v1** (D-3); if it is later admitted, a second RU-resident Postgres holds RU users' personal data with `users.data_region` routing writes, and that is Phase 2R, not a footnote.
- **ENV-8 (MUST)** v1 uses the cloud Bot API, not a self-hosted server. Our songs are 3.5–5 MB against a 50 MB limit, so the upload ceiling is irrelevant; the only real friction is the 20 MB inbound `getFile` ceiling, which we solve by capping voice input at 300 s and saying so — better UX than silent truncation.
- **ENV-9 (MUST)** `TELEGRAM_API_BASE` is configuration, never hard-coded.
- **ENV-10 (SHOULD)** Re-evaluate a local Bot API server at two documented triggers: shipping video output, or sustained ingest above 100 updates/second. **Note that `file_id` values are not portable between the cloud API and a local server** — a migration invalidates the entire `assets.tg_file_id` cache and needs a lazy re-upload path.
- **ENV-11 (MUST)** A documented, tested post-restore procedure run **before traffic is readmitted** after any PITR restore: (1) reconcile ledger and payments against each rail's own transaction list across the restore gap and re-apply missing captures and refunds idempotently; (2) rebuild the Redis idempotency and `update_id` dedup sets from `telegram_updates` and `payments` for the gap window, so a replayed webhook cannot double-fulfil after the TTL was lost with the Redis instance; (3) suppress re-delivery of orders already delivered before the restore point, matching on `assets.tg_file_id` and delivered message ids; (4) recompute `reminders.next_fire_at` and suppress any reminder whose window has already passed, so a restore never re-fires yesterday's reminders; (5) publish a reconciliation report listing every record changed. *Test:* staging drill restoring from a backup taken 6 h before a scripted workload — zero double-charges, zero double-deliveries, zero duplicate reminders, and the report accounts for every difference.
- **ENV-12 (SHOULD)** ENV-6's restore drill executes ENV-11 in full, is repeated at least twice a year, and is re-run after any schema change touching `payments`, `credits_ledger`, `reminders` or `assets`. *Test:* dated drill records exist with the ENV-11 reconciliation report attached.

### 6.9 Security, moderation, abuse

The name field is the primary input and the primary attack surface: it is free text, it enters an LLM prompt, it is spoken by a synthetic voice, it is sung, and it reaches a third party who never consented.

- **SEC-1 (MUST)** Syntactic validation: length 1–64; Unicode restricted to letters, marks, spaces, apostrophes, hyphens; NFKC normalisation; reject zero-width characters, bidi overrides and mixed-script confusables (a Cyrillic `а` inside a Latin word is a spoofing signal); collapse whitespace; reject all-punctuation or all-digit strings.
- **SEC-2 (MUST)** Layered semantic moderation: (a) a maintained profanity/slur list covering **Uzbek (both scripts), Russian and English** including transliteration, leetspeak and spacing evasions — an off-the-shelf English list is worse than useless; (b) a public-figure blocklist; (c) an LLM pass with a defined label set (`sexual`, `hate`, `violence`, `self_harm`, `impersonation`, `political`, `prompt_injection`); (d) a prompt-injection classifier.
- **SEC-3 (MUST)** Three-way verdict: `clean` proceeds; `flagged` proceeds but is queued for review and excluded from any public surface; `blocked` refuses with **non-specific** copy. Never explain which rule fired — that is a free oracle for probing the filter.
- **SEC-4 (MUST)** Structural injection defence independent of the classifier: user fields enter prompts inside delimited untrusted blocks; the system prompt declares that content there is data, never instruction; model output is schema-validated (lyrics only, no tool calls, no URLs).
- **SEC-5 (MUST)** Generated lyrics are re-screened before display and before delivery. Acceptable input can produce unacceptable output.
- **SEC-6 (MUST)** Rate limits and caps per Telegram user, all with friendly copy: 20 messages/min and 300/hour; 10 wizard restarts/hour; 5 free lyric generations/hour, 15/day and **a lifetime cap of 6 free lyric generations per `tg_user_id`**; 10 voice uploads/hour; 20 paid generations/hour (fraud tripwire); 10 payment attempts/hour; 5 promo redemptions/hour then a 24 h lockout. Above these, a **per-user rolling-30-day free-tier cost budget** hard-stops the free path with an explanatory message, so the caps and NFR-16's ceiling reconcile by construction rather than by hope.
- **SEC-7 (MUST)** Abuse controls: free tier once per `tg_user_id`; secondary check on account age and on a shared payment instrument across accounts; reduced free tier for accounts under 24 h old; velocity rule flagging >5 new accounts on one payment instrument in 24 h; all blocks logged, reviewable and reversible. **Assume the free tier will be farmed.**
- **SEC-8 (MUST)** Admin: SSO with mandatory 2FA, IP allowlist, role separation (`support` = read + refund; `ops` = + kill switches, the global intake pause and DLQ replay; `admin` = + user data and config), append-only audit log. Support can play an asset; support cannot bulk-export briefs.
- **SEC-9 (MUST)** Third-party data subjects: recipient data is order-scoped, never cross-linked, never enriched, never used for marketing, never used to train models. We never contact the recipient. Reminders go only to the purchaser with explicit opt-in recorded in `reminders.consent_at`. The purchaser sees a one-line notice at the point of entry (FR-6).
- **SEC-10 (MUST)** Provider data handling is disclosed: model providers are foreign companies and brief text leaves the country. The policy names the processor categories; the wizard warns, before the free-text step, against entering identifying details beyond a first name; a regex PII detector on the facts field warns inline.
- **SEC-11 (MUST)** Every delivered asset is labelled AI-generated in the caption and the ID3 comment, and the terms state plainly that purely AI-generated output may carry no copyright protection.
- **SEC-12 (MUST)** HTTPS with HSTS; webhook secret verified on every request; provider callback tokens signed and single-purpose; buckets private with no listing; dependency and container scanning blocking on HIGH+.
- **SEC-13 (SHOULD)** A rehearsed incident runbook covering: leaked API key, provider account suspension, mass refund event, PSP outage, and a moderation escape that reached a user.
- **SEC-14 (MUST)** A dispute lost on fraud grounds, or three or more disputes from one payment identity in 12 months, writes that payment identity and its associated Telegram ids to the SEC-7 abuse list with the reason code and a reference to the evidence pack (FR-109). Entries are reviewable and reversible like every other SEC-7 block. *Test:* seed a fraud-coded lost dispute — subsequent orders from that payment identity are blocked before payment, the block appears in the review queue, and reversing it restores purchase within 60 s.

**Harassment and defamation.** The "prank/roast" occasion is the harassment vector and competitors ship it. Our position: keep a humour occasion, frame it in prompt scaffolding as affectionate teasing with explicit negative constraints (no appearance, weight, disability, ethnicity, criminality, infidelity or medical claims), route roast-occasion orders naming a person to a higher moderation tier, and design for the assumption that this will be attempted in the first week. A **takedown path** is required: a public abuse contact reachable without Telegram — the same support intake edge that carries payment and account issues (FR-105) — an operator action that kills a share link within 4 hours of a substantiated complaint, deletion of the underlying files, and a repeat-offender ban list keyed on Telegram id and payment identity. A written escalation matrix names what is auto-blocked, what goes to human review, what triggers a ban, what triggers evidence preservation, and what — CSAM, credible threats, terrorism-related content — triggers reporting to authorities and to Telegram, **with a named owner**. An unowned escalation path is the same as none. Evidence preservation opens a legal hold under DAT-6, so an erasure request cannot destroy the record of a complaint under investigation. Moderation rules are versioned and verdicts record the version, so a complaint three months later can be answered with what the filter actually did on that date.

---

## 7. Commercial, legal and compliance

*Not legal advice. Every jurisdictional statement is drafting input for counsel admitted in the relevant jurisdiction.*

### 7.1 Pricing and packaging

- **LR-1 (MUST)** The billable unit is a **kit**: one song generation — delivering every asset that generation produces, per FR-30 — plus 3 spoken greetings, verified name pronunciation and a lyric sheet. The kit is not decomposed into separately-charged parts at launch, because the whole competitive claim is that one brief produces the whole celebration.
- **LR-2 (MUST)** The ledger is denominated in kit credits; money is recorded at capture, in the currency actually charged. This is complete for the card rails. For Telegram Stars, capture and settlement are different events in different units, and both are recorded per LR-62.
- **LR-3 (MUST, prices pending D-1)** Launch ladder — **only `KIT_1` is sold in v1**; the rest are configured and dark until Phase 2:

| SKU | Contents | RUB | UZS | USD | XTR |
|---|---|---|---|---|---|
| `FREE_TRY` | Static samples + 1 lyric draft round + 2 refinements + one ~3 s name preview. **No music, ever.** | 0 | 0 | 0 | — |
| `KIT_1` | 1 kit | 490 | 39 000 | 5.90 | 300 |
| `KIT_3` *(Phase 2)* | 3 kits | 1 190 | 89 000 | 13.90 | 700 |
| `KIT_10` *(Phase 2)* | 10 kits | 2 990 | 219 000 | 34.90 | 1 750 |
| `ADD_VOICE` *(Phase 2)* | +1 greeting on an existing order | 90 | 9 000 | 0.99 | 60 |

- **LR-4 (MUST)** One free re-render per kit, granted automatically without support contact, per FR-36 and FR-52.
- **LR-5 (MUST)** Credits do not expire for 24 months and the expiry is stated at the point of sale.
- **LR-6 (MUST)** Price lists and offers are versioned data; a purchased kit is governed by the versions in force at capture, both recorded on the order and shown on the confirmation. Changing a price never alters an already-sold kit. [FR-67]
- **LR-7 (MUST)** Four independently hand-set price lists (RUB, UZS, USD, XTR). **No runtime FX conversion of displayed prices, ever.** FX is recorded at capture for accounting only.
- **LR-8 (MUST)** The UZ price is deliberately ~55% of the RU price at prevailing FX. This is purchasing-power pricing, not a bug, and it must survive the first "the numbers don't match" report.
- **LR-9 (MUST)** All amounts are integers in minor units with an explicit currency exponent. Never floats. **Specific trap: Telegram's payments API expects UZS with exponent 2**, so 39 000 UZS is transmitted as `3900000`. One misplaced exponent charges 100× or 1/100×.
- **LR-10 (MUST)** Stars prices are set per SKU independently, never derived from the ruble price — Star unit economics differ by client platform and Telegram adjusts them.
- **LR-11 (DECISION, D-6)** VAT and tax treatment per market. The strongest engineering argument is a merchant of record for all non-UZ sales so no VAT registration lands on the operator.
- **LR-12 (MUST)** **Prepaid packs, never subscription.** Reasoning, recorded so it is not re-litigated: demand is episodic and calendar-bound (3–8 birthdays a year, in bursts) so there is no monthly reason to open the bot; recurring billing is a legal surface (auto-renewal disclosure, cancellation-path duties, "I forgot to cancel" claims) not a feature; it is 5–8 extra engineer-days plus permanent dunning and card-updater support load; the rails resist it for a small merchant; every operator in the category converged on prepaid independently, and the one claimed subscription in the segment traces to a paid listicle and is contradicted by that operator's own site config; and prepaid gives negative working capital, which at 91–95% gross margin is the best cash-flow property this business has.
- **LR-13 (LATER)** The one plausible subscription is B2B — an HR or school seat covering a year of employee or pupil birthdays. Different buyer, different invoice flow, different contract. Explicitly out of launch scope; do not let it contaminate the consumer ladder.
- **LR-63 (MUST)** **Credits are a liability until consumed.** Revenue is recognised on kit delivery, not at capture; capture creates a deferred-revenue balance reported by FR-111. Expiry at 24 months (LR-5) releases the balance where local rules permit and the accountant confirms. *Test:* buy a `KIT_3` pack and consume one kit — the report recognises one and defers two, and the balance ties to `credits_ledger`. *Reasoning:* at launch, with one SKU consumed immediately, the balance is near zero and the treatment is free. With Phase 2 packs and credit-form refunds (LR-22) it is material, and retrofitting recognition corrupts every prior reported period.

### 7.2 Payment integration

- **LR-14 (MUST)** Rails and cost. Engineering days exclude merchant onboarding calendar time, which is the actual critical path.

| Rail | Market | Eng. days | Onboarding | Effective take |
|---|---|---|---|---|
| Telegram Stars (XTR) | All | 2–3 | ~0 | **~32% on mobile** |
| Payme | UZ | 5–8 | 2–4 weeks incl. certification | ~1.5% |
| Click | UZ | 3–5 | 2–3 weeks | ~1.5% |
| YuKassa *(Phase 2R only)* | RU | 4–6 | 1–3 weeks | ~3.5% |
| Paddle / Stripe *(D-7)* | Intl | 3–6 | 1–4 weeks | 5–8% |
| **Shared payment core** | — | **6–10** | — | — |

- **LR-15 (MUST)** The shared core is the real work. Making one payment succeed is a day; making money never disappear is two weeks. Do not let a plan estimate the rails and forget the core.
- **LR-16 (MUST)** Debit before generation, auto-refund on failure. [FR-32, ASY-7]
- **LR-17 (MUST)** Every money-moving operation is idempotent on a client key; every webhook tolerates duplicate delivery; callback-populated rows are pre-created so the handler is a pure upsert. [FR-68]
- **LR-18 (MUST)** Understand the Telegram digital-goods conflict. The product is a digital good consumed inside Telegram; Telegram's policy directs those to Stars, and the ~30% mobile component is Apple's and Google's in-app-purchase commission passed through, not Telegram's invention. **The competitor cohort is not a safe precedent**: the market leader takes card payments through an embedded modal on its own website, which is verifiably *not* a Mini App, so it is no evidence that in-Telegram third-party card payment is tolerated. What its bot does at checkout was never observed.
- **LR-19 (DECISION, D-2)** Two lawful options. **Option A — Stars-only inside Telegram:** unambiguously compliant, 2–3 days, no merchant account, no PCI scope, refunds are one API call, works in every country from day one; costs ~32% on mobile, turning a 95% gross margin into ~63%, and puts Telegram between us and the customer. **Option B — off-platform checkout on our own domain:** ~1.5% in UZ, but 15–30% conversion loss at the app-to-browser handoff, we take on acquiring, fiscalisation and refund mechanics, and there is residual platform risk that grows the more the bot advertises or deep-links that checkout to iOS users. Mitigations for B: keep the page a genuine web property with its own value, never surface a payment link in an in-app browser context on iOS, and keep Stars live as a fallback rail. LR-62's settlement mechanics are an input to this decision.
- **LR-20 (MUST)** **Build both Stars and at least one card rail behind one payment abstraction**, whichever option is chosen. It costs ~1 extra day and is the only thing that makes a forced rail switch survivable.
- **LR-21 (MUST)** Never display a price in a currency different from the one that will be charged, and never show a "≈" converted price.
- **LR-22 (MUST)** Refund automation: *generation failed after debit* → credit restored immediately with a plain-language reason, no human; *name mispronounced or wrong vocal gender* → free re-render in-flow, no human; *duplicate charge detected by reconciliation* → full money refund on the original rail, no human; *paid order undeliverable* → full money refund at 72 h, no human, per FR-103; *dissatisfied within 24 h, first occurrence* → credit restored, no human; *any other money-refund request* → operator queue with a 24 h SLA. Regardless of category, the **fourth** refund request from one user in a rolling 12 months routes to an operator rather than the automatic path (FR-104).
- **LR-23 (MUST)** Stars refunds use `refundStarPayment`, so the charge id must be persisted at capture or the refund becomes impossible. Card refunds use the provider API with the original transaction id. Both write an immutable ledger entry with a reason code.
- **LR-24 (MUST)** An operator console (LR-24 = FR-84–FR-86, FR-93 in the admin surface). Without it, support is done by SSH and the audit trail is shell history.
- **LR-25 (MUST)** The refund policy is deliberately generous, and its automation (LR-22) is the policy rather than a courtesy applied case by case: any failure we can detect, we remedy without the customer having to ask twice, and a money refund is never harder to obtain than a purchase was. *Rationale, on its own merits:* at $0.28 direct COGS on a $5.90 sale, refunding every dissatisfied customer in full is affordable long before it is necessary, and a published, honest refund path is the cheapest trust instrument available to a new merchant selling an unfamiliar digital good. It is also a live differentiator: no refund clause appears in any offer of the market leader that was examined, its `/refund` route returns 404, and its FAQ contradicts its own offer text.
- **LR-26 (MUST)** Every purchase produces an in-bot confirmation containing order id, SKU, quantity, amount and currency as charged, rail, **the seller's legal entity name and tax id**, the offer version accepted, and a refund-policy link — for all rails including Stars.
- **LR-27 (MUST, pending D-6)** Fiscal receipts: UZ obligations run through the acquirer/OFD, confirmed at onboarding; RU 54-FZ receipt objects only if Phase 2R proceeds; for Stars, Telegram is the processor and any additional obligation depends on entity tax residence.
- **LR-28 (MUST)** **The entity named in the offer, on the acquiring account, and on the receipt must be the same entity**, and the alignment is evidenced at launch (LR-60 #16) rather than assumed. *Rationale:* a buyer's contractual counterparty, the party that took the money, and the party named on the fiscal document must be one legal person, or the refund path, the chargeback defence and the tax position each point at a different entity. It is stated as a requirement because it is a real and observed failure mode: the market leader's consumer contract names ИП Пермяков (ИНН 344713025915) while its mandated disclosure page names ООО «Бро.Хит» (ИНН 3444282987) as seller of an identical price list.
- **LR-61 (MUST)** **Chargebacks and disputes.** We contest a dispute where the evidence pack (FR-109) shows delivery and accept where it does not. A dispute is recorded in the ledger when the rail notifies us, not when it resolves: the provisional debit and its reversal are separate entries, so a won dispute does not net to a silent zero. Dispute rate is reported monthly per rail; breaching a rail's own threshold (card networks typically ~0.75–1%; confirm the exact figure per rail at onboarding) is a SEV-2 with a written remediation note. Consequences for the buyer are FR-104's and SEC-14's, not ad hoc. *Test:* seeded won and lost disputes each produce two ledger entries with correct signs and appear in the monthly report; the dispute-rate calculation matches a hand count.
- **LR-62 (MUST)** **Stars settlement mechanics, written down before Stars go live.** Documented in writing from Telegram's current published terms — not from directional figures: the withdrawal hold period, the minimum withdrawal threshold, the withdrawal mechanism and its fee, the FX basis applied at withdrawal versus the rate recorded at capture, and what document (if any) Telegram issues that an accountant can use. The ledger records Stars revenue at capture in XTR **and** the money value only at withdrawal, holding the difference as an unwithdrawn-Stars balance surfaced in FR-110. *Test:* the Stars section of the settlement export shows XTR captured, XTR withdrawn, money received, FX applied and unwithdrawn balance; the balance ties to `getStarTransactions`. *Note:* this is a D-2 input — Stars capture and settlement are different events in different units, and a plan that treats them as one will not reconcile.
- **LR-67 (MUST)** **The published refund policy states what a refund takes back.** The policy text matches FR-104 exactly: files already delivered stay with the buyer, the public share page comes down, re-sending stops, the order stays visible marked refunded, and repeated refunds route to a human. *Test:* a per-release checklist item asserts the policy text against FR-104's tested behaviour in all three languages; the support canned response quotes the same wording.

### 7.3 Free tier and cost control

- **LR-29 (MUST)** The design constraint: the competitor-style free tier (a full free generation plus unlimited free lyric regeneration) costs **~$0.72 per paid order at 10% conversion — 2.5× the COGS of the thing being sold.** The free tier is a cost-engineering problem first and a marketing problem second.
- **LR-30 (MUST)** The free tier gives away **text and one very short spoken clip; never music**: static pre-rendered samples (FR-5), one lyric-draft round producing two drafts plus two refinements (FR-20, FR-26), and one ~3-second name preview whose sole job is to prove we say the name correctly (FR-51). No song, no full kit, no first-verse teaser.
- **LR-31 (MUST)** Free-tier generations route to cheaper model tiers than the paid path — a cheaper LLM for drafts, Yandex SpeechKit for the name preview rather than a premium voice. Premium voices are part of what is bought.
- **LR-32 (MUST)** Target: **≤$0.12 of free-tier cost per paid order** at 10% conversion, ≤$0.15 per free user per 30 days. *Arithmetic, stated so it can be checked:* ~3 cheap LLM passes ≈ $0.010 + a 3-second SpeechKit clip ≈ $0.001 ≈ $0.011 per free user ≈ $0.11 per paid order. **This is why FR-26 caps refinements at two on a cheap model** — the source drafts' 3 uncapped rounds did not close against this target.
- **LR-33 (MUST)** Anti-farming per SEC-7: one free preview per Telegram id for life (re-issuable only by an operator), rate limits, new-account heuristics, and no free tier for any account with a prior moderation block.
- **LR-34 (MUST)** Instrument free-tier unit cost as a first-class dashboard metric from day one (OBS-7). This is the number most likely to quietly eat the margin and it is invisible unless deliberately measured.
- **LR-35 (DECISION, D-8)** Whether the free tier is permanent or a capped launch-period acquisition subsidy.

### 7.4 Rights and licensing

- **LR-36 (MUST)** Maintain a version-controlled **provider licence matrix**: per provider, the exact ToS clause granting commercial use of outputs, date checked, whether an indemnity is offered, and whether our tier qualifies. No provider enters a paid code path without a row. Re-reviewed on every swap and at least quarterly. The matrix also carries the cover-art template rows (LR-64), the dictionary-source rows (LR-65) and the voice-persona rows (LR-66).
- **LR-37 (MUST) — may NOT be used in any paid flow:** Suno reseller APIs (kie.ai / api.sunoapi.org — one backend — plus acedata, AIMLAPI and equivalents), because they are not in a position to sublicense output rights, they break the chain we intend to promise the buyer, and they carry an upstream termination risk that would take the product offline without notice; **any provider accessed by cookie scraping or browser automation**; **any TTS voice cloned from a public figure**.
- **LR-38 (MUST) — may be used, subject to matrix confirmation:** ElevenLabs Music (song primary), Google Lyria via the official API (fallback), ElevenLabs TTS (RU/EN, stock voices only), Yandex SpeechKit (UZ and the free preview path), and the lyric LLM — each confirmed for output ownership and no-training-on-inputs on the specific tier.
- **LR-39 (MUST)** Provider swaps must not require re-papering customer terms: describe capabilities generically in the terms while still disclosing the *category* of transfer for data-protection purposes.
- **LR-40 (MUST)** **The bot must not claim the user owns exclusive copyright.** Purely AI-generated output, absent meaningful human authorship, is not protectable in the US and the position in RU and UZ is at best unsettled. An assertion that the buyer "является обладателем исключительного права" — which the market leader's terms make — is a claim no AI supply chain in this category can support, and we do not repeat it.
- **LR-41 (MUST)** What we may say, and the shape the terms take: (1) we assign whatever rights we hold in the delivered files; (2) we grant a perpetual, worldwide, irrevocable, royalty-free, transferable licence to use, reproduce, publish, perform and adapt, **including commercially**; (3) we disclose plainly that AI-generated material may not attract copyright in the customer's jurisdiction and they may be unable to prevent others using an identical output; (4) we warrant we obtained the output through providers whose terms permit this grant — which is true only if LR-37 holds.
- **LR-42 (MUST)** **We take no publishing licence back by default.** Any marketing use of a customer's song or greeting requires separate, affirmative, revocable opt-in captured at a distinct moment, with a working revocation path. *Rationale:* a blanket marketing licence buried in an offer is precisely the term a buyer would decline if it were put to them at the moment of purchase — so we put it to them at that moment, and take nothing without a yes. The recipient never consented to anything at all (LR-49), which makes a silent marketing grant over their name and story indefensible as well as unattractive.
- **LR-43 (MUST)** **Exactly one live offer version at one canonical URL**, carrying a version id and an effective date, with superseded versions archived at stable, clearly-labelled URLs and every acceptance recorded against the version id in force at capture. *Test:* a crawl of every legal route returns exactly one document bearing the current version id; an acceptance record exists for every purchase and names a version that resolves; a superseded URL serves the archived text under an unambiguous "superseded on `<date>`" banner and is never the target of an in-product link. *Rationale, stated on its own merits:* if two versions are ever simultaneously reachable and in-product links are not version-pinned, a user who accepted one has a colourable argument that another binds them, and the acceptance record is the only thing that can answer it. **Note on the incumbent:** the research contains an unresolved conflict between two primary probes as to whether the market leader runs one offer text at several URLs or three materially different offers simultaneously (§2.2). We rely on neither reading; the requirement does not need it.
- **LR-44 (MUST)** Required clauses, in substance: output rights and the copyright caveat (LR-41); no exclusivity ("similar inputs may produce similar results for other users"); nature of the service — the remedy stated (LR-4, LR-22), not a bare "as is"; **recipient warranty** ("you confirm you are entitled to give us this information and that this greeting is not intended to harass, humiliate, threaten or defame"); voice ("all voices are original characters or licensed stock voices; we do not and will not imitate any real, identifiable person"); enumerated prohibited use, enforced by §6.9 not merely stated; marketing use (LR-42); the actual refund policy in plain language, including what a refund takes back (LR-67); the retention carve-out for records under legal hold (LR-68); who we are, with entity, registration number, tax id, address and support contact matching LR-28; and governing law and forum.
- **LR-64 (MUST)** **Cover-art licensing.** Every cover template's background, typeface and ornament carries a recorded licence permitting commercial redistribution **inside a sold digital good**, held in the LR-36 provider licence matrix alongside the model providers. No template ships without a row. *Test:* the template inventory and the licence matrix reconcile with zero unmatched entries, checked at launch and on every template addition.
- **LR-65 (MUST)** **Dictionary licensing.** No name-dictionary entry originates from a source whose terms forbid extraction or redistribution; per-entry source and licence are recorded (FR-95); entries derived from user corrections (FR-53) are recorded as ours. *Test:* as FR-95, plus a dated counsel sign-off that the seeded sources are usable before the dictionary enters a production path.

### 7.5 Voice policy

- **LR-45 (MUST)** Original character personas only — either a licensed stock voice used within its library terms, or a voice commissioned from a named actor under a written agreement covering synthesis, unlimited use and this product. Presented as characters ("a warm grandfather", "an energetic radio host"), never as anyone.
- **LR-46 (MUST)** **Absolute prohibition on public-figure impersonation** — celebrity, politician, musician, deceased. Enforced technically, not aspirationally: a public-figure blocklist checked against persona selection and free-text style requests; prompt filtering for "in the voice of…", "как …", "sounds like …" in every supported language including transliteration; and provider-side rejections caught, surfaced in plain language and refunded per LR-22, never failing silently. This is a deliberate refusal of a proven-lucrative adjacent product (celebrity-persona greetings at 1 190–2 590 ₽), and the terms must say so plainly enough that no customer expects it.
- **LR-47 (MUST)** No user-uploaded audio anywhere in v1. [FR-7]
- **LR-48 (DECISION, D-10 — separate legal workstream)** If sender-voice-cloning ever enters scope it is a new product with a new compliance posture, not a feature increment. Minimum before a line is written: (1) treat voice as biometric personal data under the heightened regimes of RU 152-FZ Art. 11, UZ special-category rules and GDPR Art. 9, with **explicit consent from the voice owner as the only basis**; (2) in-session recorded consent using a freshly-generated phrase so it cannot be replayed, retained as the consent artefact with its own clock; (3) **only the sender's own voice** — never uploaded third-party audio, never a forwarded voice message, never the recipient — with liveness/anti-replay on enrolment; (4) purpose limitation in the consent text *and in the code*; (5) deletion on request within the statutory window and automatically after 90 days of inactivity, including from backups on a documented schedule; (6) a per-synthesis audit log; (7) a completed DPIA. Until all seven exist, this is out of scope — say so in the roadmap so it is not quietly assumed into a sprint.
- **LR-66 (MUST)** **Persona procurement and withdrawal.** Nine persona-language pairs (3 personas × 3 output languages, FR-38) are procured before M1.3 completes, each as either **(a)** a stock voice whose library terms have been read, recorded in the licence matrix and confirmed to permit this use at our tier — including redistribution of the rendered audio to a third party who is not our customer — or **(b)** a voice commissioned from a named actor under a written agreement covering synthesis, unlimited commercial use, this product and its successors, term, territory and fee. Each persona has a designated same-language substitute (API-10); a withdrawn voice is replaced in configuration within 24 h and buyers of delivered audio are unaffected. *Test:* at launch all nine pairs have a licence-matrix row, a signed agreement or terms citation, and a named substitute; a simulated withdrawal completes within 24 h in staging. *Note:* licence fees or actor fees for nine renders, plus counsel time for an actor-agreement template, are a commercial cost line, not engineer-days, and the Uzbek inventory may not contain three distinct usable personas at all — in which case commissioning carries 2–6 weeks of calendar time.

### 7.6 Data protection

- **LR-49 (MUST)** **The defining fact of this product: the person the song is about has never interacted with us and has given no consent**, and in many cases will never know. Their name, age, relationship, anecdotes, habits — sometimes health or marital situation — are processed on a third party's say-so. This must shape the architecture, not be papered over in a policy.
- **LR-50 (DECISION, D-4)** Lawful basis. Consent from the recipient is unobtainable by construction. The proposed posture: **(a)** the sender warrants they are entitled to provide the information (LR-44); **(b)** radical minimisation and short retention (FIL-7) so the exposure window is small; **(c)** an accessible deletion route for a recipient who does learn of it (LR-53). Counsel must confirm this is defensible or supply a better basis. Note the incumbent's approach — a clause obliging the user not to enter personal data, inside a product whose entire function is entering a person's name and personal details — is unenforceable in substance and should be read as an admission, not a template.
- **LR-51 (MUST)** Minimisation as technical design: recipient data is order-scoped with no profile, no cross-order linking by name, no enrichment; never used for marketing; never used to contact the recipient; never used to train models, ours or a provider's (a tier that trains on inputs is disqualified by LR-36); and only fields the generation needs — no address, no phone, **no birth year and therefore no exact date of birth**, no photo. The day-and-month reminder record is the single deliberate exception, on the terms of LR-69.
- **LR-52 (MUST)** The retention schedule of FIL-7 is the authoritative one. *Resolution note:* three periods were proposed in drafting — 180 days, 24 months and 90 days for delivered audio; reconciled at 12 months for paid audio, with the recipient's free-text brief purged at 30 days regardless, and recipient identity retained beyond 90 days only where reminder consent exists.
- **LR-53 (MUST)** Two deletion routes: **(1) sender** — a `/forget` command deleting briefs, delivered files and profile, retaining only the ledger stripped of personal content, with confirmation of what was and was not deleted and why; **(2) recipient or third party** — a published contact (email and web form) **reachable without installing Telegram**, proportionate identity verification, and a **10 working day** response SLA, with requests and outcomes logged. The same non-Telegram contact surface carries payment, refund, delivery and account issues (FR-105), so a user who has blocked the bot is never left without a route to their money.
- **LR-54 (MUST)** A plain-language notice **in the bot at first use**, not only in a policy page: what we collect about the person, that we do not contact them, how long we keep it, and how to have it deleted. Cheap, honest, and the mitigation that makes LR-50's posture defensible. [FR-6]
- **LR-55 (MUST)** **RU 152-FZ Art. 18(5)**, if RU is ever admitted: recording, systematisation, accumulation, storage, amendment and retrieval of Russian citizens' personal data must use databases physically in Russia, plus RKN processing notification and **prior notification of any cross-border transfer**. Concretely this forbids a foreign primary database and forbids treating a US AI provider as the point of first collection — sending the recipient's name and brief to a foreign model **is** a cross-border transfer. It cannot be evaded by pseudonymising the name, because the name in the song *is* the product.
- **LR-56 (DECISION, D-3 — resolved for v1)** Three RU postures were available: **(A)** full compliance (RU primary DB, RKN filings, foreign providers downstream only) at +8–15 engineer-days plus a RU legal entity and ongoing filings; **(B)** geo-gate RU out; **(C)** RU served entirely by Russian providers with no cross-border transfer, at +10–20 days and a quality risk on the music model. **This SoW resolves to Posture B for v1**, per the technical draft's recommendation, with Posture A available as gated Phase 2R. This gates the storage-layer design and is confirmable, not re-openable mid-build.
- **LR-57 (MUST, pending D-5)** Uzbekistan, per ZRU-547 as understood and requiring UZ counsel confirmation: personal data of Uzbek citizens processed using databases **physically located in Uzbekistan**; operator **registration in the State Register of Personal Data Bases** (closer to an affirmative registration than RU's notification regime, and a prerequisite); cross-border transfer permitted to adequate jurisdictions and otherwise requiring additional grounds; enforcement includes resource blocking. **If Uzbekistan is a launch market — and it is the strategic opening — in-country hosting and register entry are launch blockers with calendar time attached, not phase-2 items.**
- **LR-58 (MUST)** Data residency is a **per-user routing decision** resolved at signup and persisted, not a global deployment choice. One codebase, region-aware storage. Retrofitting this after launch is a rewrite.
- **LR-59 (MUST)** **Children are a core use case, not an edge case.** When the supplied age is below the applicable threshold, the sender must affirmatively confirm they are the parent or guardian or have that person's permission — one tap, logged with the order. No photographs of children ever. No profiling, marketing or retargeting on any order flagged as involving a minor, and the shortest retention tier. Set our own minimum user age (recommend 16+, or 18+ where payments are involved) and state it in the terms and at first use — Telegram's floor is 13 and ours should be higher because we take money. **Never ask for a child's exact date of birth**; an age band is sufficient for the lyric and materially less sensitive, and LR-69 makes this true by construction for every recipient.
- **LR-68 (MUST)** **Erasure yields to legal hold, and says so.** The deletion routes (LR-53, FR-83) state plainly that where a record is subject to an open abuse investigation (§6.9) or a legal, tax or regulatory obligation, that record is retained under DAT-6, and the requester is told the category of retained data, the ground and the duration, while everything not held is deleted on schedule. Counsel confirms the wording per jurisdiction. *Test:* the published text contains the carve-out in all three languages; a seeded erasure request against held data produces both the partial deletion and the disclosure, and both are logged.
- **LR-69 (MUST)** **No recipient birth year, anywhere.** The reminder record holds day and month only; no schema column, API field, export or log may contain a recipient birth year (FR-102). The day-and-month record is the single deliberate exception to LR-51's minimisation list, permitted only under the explicit opt-in of FR-71, recorded in `reminders.consent_at`, and purged per FR-75. *Reasoning:* day+month is not a date of birth; the year is the component that turns the record into one, and the reminder loop needs nothing more than day and month. *Test:* the published policy text and the schema agree, asserted by the same CI check that fails any migration adding a recipient birth-year column.

### 7.7 Launch documents

**LR-60 (MUST)** Launch is blocked until each of these exists, is published at a stable URL, and is linked from the bot. "Draft in a Google Doc" is not "exists."

| # | Document | Owner |
|---|---|---|
| 1 | Public offer — UZ, in **Uzbek and Russian**, single live version, versioned, predecessors archived | UZ counsel |
| 2 | Terms of use — output rights (LR-41/44), voice policy (LR-46), prohibited use, remedy for bad output | Counsel |
| 3 | Privacy policy — UZ, Uzbek and Russian, naming payment and AI processor categories | UZ counsel |
| 4 | Privacy policy — international/GDPR-shaped, if non-CIS users are accepted | Counsel |
| 5 | Consent texts — PD processing (sender), recipient-data warranty, reminder opt-in, marketing opt-in (separate) | Counsel + build |
| 6 | Refund policy — published, plain-language, matching LR-22's automation and LR-67's scope exactly | Founder + counsel |
| 7 | **`/paysupport` handler** — required of any bot accepting Telegram payments: how to get a refund, the SLA, a working contact, a policy link. ~0.5 day, non-negotiable | Build |
| 8 | `/terms`, `/privacy`, `/help` handlers plus persistent menu links | Build |
| 9 | UZ State Register of Personal Data Bases entry + operator registration | UZ counsel |
| 10 | Named data-protection responsible person, published in the policies | Founder |
| 11 | Provider licence matrix (LR-36), including cover-art template (LR-64), dictionary-source (LR-65) and voice-persona (LR-66) rows, reviewed and signed off | Build + counsel |
| 12 | Records of processing (ROPA) | Counsel |
| 13 | Abuse contact + takedown procedure, published outside Telegram | Founder + build |
| 14 | Moderation policy and escalation matrix with a named owner | Founder |
| 15 | Age policy — minimum user age, minor-recipient handling | Counsel |
| 16 | Entity/acquiring alignment evidence (LR-28) | Founder |
| 17 | Fiscalisation configuration for the live rails | Build + tax adviser |
| 18 | DPIA — conditional now; **mandatory** before any voice-cloning work | Counsel |
| 19 | Community/channel rules, if a marketing channel is operated *(does not block launch)* | Founder |
| 20 | Voice-persona licence citations or signed actor agreements for all nine persona-language pairs (LR-66) | Founder + counsel |
| 21 | Support page outside Telegram — hours, first-response target, money and account entry point (FR-105, FR-106) | Founder + build |

*RU-specific documents (RU offer, RU privacy policy, RKN processing and cross-border notifications, 54-FZ receipt configuration) are Phase 2R and are not launch blockers under Posture B.*

---

## 8. Delivery plan, milestones, acceptance criteria, estimates

**Unit.** One engineer-day = one uninterrupted 6-hour day of a mid-to-senior backend engineer already fluent in Python, aiogram 3.x and async queues. Not a calendar day.

**Confidence, applied consistently.** High = median × 1.25. Medium = median × 1.5. Low = median × 2–3. This is the rule §8 stated in v1.0 and then broke in three of five P80 columns, always downward. Every P80 below is recomputed from it.

**How the P80 is aggregated, stated so it can be checked.** Each phase is split into a Medium block and a Low block; the factor is applied to each block and the results summed. Blocks are not variance-reduced against each other. That is deliberate: these lines are not independent draws. They share one engineer, one provider set, one legal entity and one set of unknowns, so the thing that makes M1.6 late (an acquirer's certification schedule) is the same thing that makes M0.6 late. Positively correlated risks add; they do not cancel. Where the Low band spans 2–3×, the low end (×2) is taken and the reason is named per line.

**Engineer-days are not the schedule.** Read §8.0 before any table below. The front of this project is gated by an entity registration and two acquirer onboardings, and no amount of engineering removes those weeks.

**Phase ordering is not negotiable.** Phase 0 produces the criteria that decide whether Phase 1 is worth building and what it contains. No Phase 1 ticket opens before the Phase 0 memo is signed.

---

### 8.0 The critical path is legal and administrative

v1.0 presented 137 engineer-days as though that were the plan. It is not. The chain below runs in calendar weeks, is owned by the founder and counsel rather than by engineering, and contains the gate that opens Phase 1. Week 0 is the day the client signs and D-6 is answered.

| Wk | Event | Owner | Duration | Depends on | Source |
|---|---|---|---|---|---|
| 0 | **D-6 decided** — entity structure and tax residence | Founder | — | Nothing. If this slips, everything below slips one-for-one | §10, D-6 |
| 0–4 | Entity registration in Uzbekistan: charter, tax registration, bank account | Founder + counsel | 2–4 wk | D-6 | LR-28 |
| 0–4 | UZ counsel engaged; ZRU-547 position written; State Register application prepared | UZ counsel | 2–4 wk | D-6 | LR-57, D-5 |
| 0–4 | **M0.6** Payme/Click sandbox integration built (engineering, 4 d) | Engineering | — | Nothing | LR-14 |
| 4–8 | **Payme merchant application + sandbox certification** | Founder + eng | **2–4 wk** | A registered entity; M0.6 complete | LR-14 |
| 4–7 | **Click merchant application** (parallel) | Founder + eng | **2–3 wk** | A registered entity; M0.6 complete | LR-14 |
| 4–16 | **UZ State Register of Personal Data Bases entry** | UZ counsel | **4–12 wk** *(estimated; unsourced)* | A registered entity | LR-57, §9.3 #16 |
| 4–10 | In-country hosting for UZ personal data: procurement, contract, provisioning | Founder + eng | 2–6 wk | Entity; D-3 settled | LR-57, LR-58 |
| **8** | **Gate 3 can pass at the earliest** | — | — | One acquirer live in sandbox with a real test transaction | §8.3 |
| 9 / 15 | **Phase 0 memo signed** — median / P80 | Founder | — | M0.1–M0.6 complete | §8.2 |
| **9 / 15** | **Phase 1 opens** — median / P80 | — | — | max(Gate 3, memo) | — |

**The chain, drawn:**

```
D-6 ──▶ entity registration (2–4 wk) ──┬──▶ Payme onboarding + certification (2–4 wk) ──┐
                                       ├──▶ Click onboarding (2–3 wk) ─────────────────┤
                                       ├──▶ UZ State Register entry (4–12 wk) ─────────┼─▶ launch blocker
                                       └──▶ UZ hosting procurement (2–6 wk) ───────────┘
M0.6 sandbox integration (4 eng-d, wk 0–4) ─────────────────────────────────────────────┘
                                                                                        │
                                                              ┌─────────────────────────┘
                                                              ▼
                                              GATE 3 ── earliest week 8 ──▶ PHASE 1 OPENS
```

**Three consequences the v1.0 plan did not state.**

1. **Phase 0's "4–5 calendar weeks" was impossible against its own Gate 3.** Gate 3 requires a live sandbox transaction on Payme or Click. Both require a registered entity, which is D-6 and still open. The onboarding is 2–4 weeks *after* the entity exists. The floor is 8 weeks, and merchant onboarding was neither started, owned, nor listed as a task anywhere in v1.0. It is now M0.6 plus the two rows above.
2. **Phase 0's engineering and the acquirer land in the same window.** Phase 0 is 25 engineer-days (§8.2), which a solo founder-engineer clears in ~9 calendar weeks median and ~15 at P80 (§8.9). So the binding constraint at the front of the project is *both* the acquirer and Phase 0's own engineering, and neither is shortened by working on the other.
3. **The State Register entry is a launch blocker with unknown calendar time.** §9.3 #16 assumes it "completes within the pre-launch window" with no basis. It is a prerequisite registration, not a notification (LR-57). At Phase 1 durations of 29–44 weeks (§8.9) it is not the binding constraint — but that is luck, not planning, and it becomes binding the moment Phase 1 is compressed.

**Earliest realistic launch: week 38 (median), week 59 (P80)** — Phase 1 opening at week 9/15 plus 29/44 weeks of two-engineer Phase 1. Solo, it does not launch inside a year (§8.9).

---

### 8.1 Headline totals

| Phase | v1.0 median | **Rebuilt median** | **P80** | P80 factor applied |
|---|---|---|---|---|
| Phase 0 — Spike | 16 | **25** | **44** | Medium 11→16.5; Low 13→26; High 1→1.25 |
| Phase 1 — MVP (planning case, CAC-Red included) | 85 | **180** | **280** | Medium 162→243; Low 18→36 |
| Phase 2 — Retention, residual after CAC-Red pull-forward | 36 | **23** | **35** | Medium 23→34.5 |
| **v1 through retention** | **137** | **228** | **359** | |
| Phase 2R — Russian market *(optional, D-3)* | 18 | 18 | **36–54** | Low ×2–3 |
| Phase 3 — B2B + cloning *(direction, not commitment)* | 36 | 36 | **72–108** | Low ×2–3 |
| Phase 3 — B2B only, cloning cut | 26 | 26 | **52–78** | Low ×2–3 |

**The honest number is larger, and here is where the 91 days came from:**

| Correction | Δ median |
|---|---|
| Name-pronunciation subsystem priced as specified (27 d) instead of half a 6-day line | **+27** |
| Production provider layer priced (27 d) — M0.1's bench harness is not it | **+27** |
| Payment rails rebuilt against LR-14's own 16–26 band (12 + 4 in Phase 0 + 8 core = 24) | **+3** |
| Public share page as a web property (M1.13) | **+6** |
| Cover-art generation (M1.14) | **+3** |
| Phase 0: sandbox integration for Gate 3 (M0.6), billing-shape measurement (M0.5), capped α re-run (M0.2R) | **+9** |
| Storage/delivery raised 3→5; sample packs; voice registry; free-tier lifetime caps; launch-doc build items | **+8** |
| CAC-Red add-on moved into the headline (§8.4) | **+11** |
| Integration and hardening rescaled to 20% of the corrected base | **+14** |
| Phase 2 loses M2.2 and M2.3 to the CAC-Red pull-forward | **−13** |
| **Net** | **+91** |

Nothing was dropped to get here. Two things were *moved*: 4 days of Payme work from Phase 1 into Phase 0 (Gate 3 cannot pass without it), and 11 days of share/referral from Phase 2 into Phase 1 (the document's own CAC-Red branch).

---

### 8.2 Phase 0 — Spike (25 engineer-days median / 44 P80, plus 10 founder-days, 9–15 calendar weeks)

Phase 0 answers four questions the evidence base cannot: can any available model pronounce a person's name acceptably in Russian, Uzbek and English, sung and spoken; what does it cost to buy one paying customer; which payment rail is actually live; and **how do the music providers bill**, because the delivery model in FR-30/D-9 assumes an answer nobody has checked.

**The critical technical framing:** there is no phoneme-level control over a *sung* name. Speech providers expose SSML stress marks and phoneme tags; music providers expose nothing but orthography. The only lever for sung names is **respelling the name inside the lyric text**, so respelling must be tested as an explicit experimental variable, not an afterthought.

| ID | Milestone | Acceptance criteria | Est. | Conf. | P80 |
|---|---|---|---|---|---|
| **M0.1** | Provider abstraction + **bench** harness (adapters for ElevenLabs Music, Lyria, ElevenLabs TTS, SpeechKit; `bench run --set names80 --provider X --lang uz-Latn --strategy raw`; fixture replay; cost/latency logging) | (1) `bench run` over 80 names emits one JSONL row per (name, language, script, provider, strategy) with `audio_path`, `latency_ms`, `cost_usd`, `provider_request_id` all non-null. (2) Switching provider is one config value — the identical command with `--provider lyria` completes with no source edits, in a recorded session committed to the repo. (3) Each adapter maps errors onto the five classes; a fixture test replays one recorded instance of each per adapter. **(4) The harness is labelled a bench, not a production layer, in its own README, and M1.22 is referenced there.** | 5 d | Medium | 7.5 |
| **M0.2** | 80-name pronunciation test set, rubric, Round 1 (30 RU / 30 UZ each with both scripts / 20 EN; four strategies: `raw`, `stress_marked`, `respelled_phonetic`, `script_transliterated`; blind rating app; 3 paid native raters per language) | (1) CI schema test asserts 80 rows, the 30/30/20 split, both script forms on every UZ row, no duplicates. (2) Every clip rated by ≥3 native speakers who were not shown the expected name. (3) Output is an accept rate **with a two-sided 95% CI**, per language per modality, and the interval is reported everywhere the number appears. | 6 d | **Low** — rater recruitment and rubric convergence are outside our control | 12 |
| **M0.2R** | **α re-run reserve, hard-capped.** If Krippendorff's α < 0.6 for a language: **one** rubric revision and **one** re-run of **that** language, plus one further round of rater fees. | (1) The revision is diffed against the original rubric and the diff is in the memo. (2) If a **second** language also fails α after its own re-run, **Phase 0 stops** and M0.4 records "pronunciation quality is not measurable with this instrument" — a Tier-D-adjacent outcome, not a schedule extension. | 3 d | **Low** — recursive by nature, which is why it is capped | 6 |
| **M0.3** | Paid-CAC fake door (landing page + bot taking real briefs and real money, fulfilled **manually** within 24 h or refunded within 48 h; ≥2 channels × 2 language creatives; $300–600; hard cap 30 orders) | (1) ≥1,000 impressions per channel per language and ≥100 `/start` events, else the test is inconclusive, is re-flighted, **and no CAC number is reported** — an inconclusive result is planned as Red (§8.4). (2) Cost per paid pre-order computed from the ad platform's **billing export**, not the dashboard estimate. (3) At close, zero orders are `unfulfilled AND unrefunded`, verified by query. | 4 d **+ 10 founder-d** | **Low** | 8 |
| **M0.5** | **Provider billing-shape measurement.** For each music provider: is billing per generation, per generated second, or per credit; does one call return two variants; is the second variant marginal-cost-zero. Same for the TTS providers per character/second. | (1) A table of measured `cost_usd` per call against the provider's own invoice for the billing period, agreeing within 5%. (2) A written yes/no on "the second song variant is free", **because FR-30, D-9, the $0.28 COGS figure and Gate 2's contribution table all assume yes and none of them has checked.** (3) If the answer is no, the D-9 contingency in §8.4 is triggered. | 2 d | Medium | 3 |
| **M0.6** | **Payme (or Click) sandbox integration — the thing Gate 3 actually requires.** JSON-RPC merchant methods to spec (`CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`) against sandbox, enough to attempt certification. | (1) One successful sandbox transaction, recorded, with the request/response pair committed as a fixture. (2) The integration is written inside `hbd-payments` behind the LR-20 abstraction, not as a spike to be thrown away. | 4 d | Medium | 6 |
| **M0.4** | Go/no-go memo | States, for each of Gates 1–4, the measured value, the bar, and PASS/FAIL, and names exactly one Ship Tier and one CAC branch. Signed and dated before any Phase 1 ticket opens. | 1 d | High | 1.25 |
| | **Total** | | **25 d** | | **44** |

Non-engineering cost: rater fees $300–600 (plus up to $300–600 more if M0.2R fires), ad spend $300–600, provider credits ~$150.

#### Phase 0 founder time — the correction

v1.0 booked "~3 founder-days" against M0.3. M0.3 is a multi-week ad flight in which up to 30 orders are **manually fulfilled within 24 hours each** and refunded within 48. That is a daily seven-day duty for the length of the flight, not three days of work. Derived:

| Duty | Basis | Hours |
|---|---|---|
| Per-order manual fulfilment | 30 orders × 45 min (brief → lyric → generate → 3 TTS → assemble → QA → deliver) | 22.5 |
| Daily standby and 24-hour response obligation | 21 days × 7 days/week × 1.0 h/day | 21.0 |
| Refunds, ledger, ad-platform management, reconciliation | 3 weeks × 2 h | 6.0 |
| Landing copy, creative briefing, native-reviewer coordination | one-off | 8.0 |
| **Total** | | **57.5 h ≈ 10 founder-days** |

**And the shape matters more than the total.** Those 57.5 hours are spread across 21 consecutive calendar days with a hard 24-hour response clock on every one of them, including weekends. During the flight, founder engineering throughput is **halved** — 1.75 engineer-days per calendar week instead of 3.5 (§8.9). That is what turns Phase 0's engineering from 7 weeks into 9.

Founder-days: **10 median, 20 at P80** (Low, ×2 — the fulfilment time per order is a guess and the flight may need re-flighting under M0.3's AC-1).

#### Gate 1 — Name pronunciation

**A hard statistical rule:** at n=30 per language an accept rate carries roughly ±15pp. Every threshold must be cleared by the **lower bound of the 95% CI**, not the point estimate. A measured 75% with a lower bound of 60% is a FAIL.

| Language | Spoken | Sung |
|---|---|---|
| Russian | ≥ 90% | ≥ 85% |
| English | ≥ 90% | ≥ 85% |
| Uzbek | ≥ 85% | ≥ 70% |

*"Accept" = a native rater, hearing the clip cold, answers yes to "would the person named here accept this as their name?" Best-of-four-strategies counts, provided the winning strategy is deterministically derivable from the input name — a hand-tuned respelling per name is not a product.*

**The α escape clause is capped.** v1.0 wrote "α ≥ 0.6 per language **or the rubric is revised and that language re-run**" with no bound. One re-run of one language is most of M0.2's six days, and the estimate assumed a single round across three languages, four strategies, both Uzbek scripts and three raters each. The cap is now M0.2R: one revision, one re-run, one language reserve of 3 days; a second failure stops the phase.

**Outcome ladder — what ships if the models cannot sing Uzbek:**

| Tier | Trigger | What ships |
|---|---|---|
| **A** | UZ sung ≥70% and UZ spoken ≥85% | Full bilingual product. "The only bot that sings your name right, in Uzbek." |
| **B** | UZ sung <70%, UZ spoken ≥85% | **Uzbek ships spoken-only**: the three greetings are Uzbek and carry the name; the song is Russian or instrumental-with-Uzbek-intro and references the person by relationship, not by name. Removes ~3 engineer-days of Uzbek lyric tuning from M1.2. |
| **C** | UZ spoken <85% too | **Uzbek deferred.** Ship RU+EN — but keep Uzbek-name handling inside the Russian pipeline. Removes ~4 d from M1.16 (Uzbek dictionary seeding) and the Uzbek third of M1.23/M1.24. |
| **D** | Fails in all three languages, sung and spoken | The "we solve name pronunciation" thesis is dead. Fall back to **name-avoidance**: the name appears in the message text, file title, cover art and lyric card, never in generated audio. **Removes M1.18, M1.19, M1.20 and most of M1.17 — roughly 14 engineer-days — and removes the reason to build the product.** Requires an explicit founder decision to continue. |

**Tier B is the most likely outcome and the plan should be read as though B is the base case.**

#### Gate 2 — Customer acquisition cost

**Contribution per first order at the reference price of $5.90**, with the free-tier line corrected per §8.5:

| Line | Payme/Click | Telegram Stars | Note |
|---|---|---|---|
| Revenue | $5.90 | $5.90 | D-1 |
| Direct COGS | −$0.28 | −$0.28 | Target; NFR-14 ceiling is $0.45. Provisional until M0.5 |
| Payment rail | −$0.09 (1.5%) | −$1.89 (32%) | LR-14 |
| Free-tier waste (**corrected**, §8.5) | **−$0.40** | **−$0.40** | Was −$0.12, which did not survive its own requirements |
| **Contribution** | **$5.13** | **$3.33** | |

*Sensitivity, since two of these three inputs are unmeasured:* at the NFR-14 ceiling of $0.45 COGS, contribution is **$4.96**. If M0.5 finds the second song variant is separately billed, COGS rises to ~$0.33 and contribution to **$5.08** (§8.4, D-9 contingency).

**What this test can and cannot resolve.** v1.0 applied a statistical objection to Gate 1 (demanding CI lower bounds) and then omitted it from Gate 2, which is capped at 30 orders. CAC = spend ÷ orders; with spend fixed, the uncertainty is in the order count. For 30 observed events the exact Poisson 95% interval is **[20.24, 42.83]**, so the measured CAC carries an upper factor of 30 ÷ 20.24 = **×1.48**.

That means the test **cannot** separate Green from Amber at n=30 — a point estimate of $4.00 has an interval spanning both. It **can** separate Green from not-Green, provided the trigger is tightened so the *upper* bound clears the threshold. And since the document already instructs that Amber be treated as Red, the Green/Amber distinction has no planning consequence anyway.

| Branch | Trigger (local rail) | Consequence |
|---|---|---|
| **Green** | Measured CAC ≤ **$1.73** — so the ×1.48 upper bound clears $2.57 (50% of contribution) | Paid acquisition works on the first order. Phase 1 as scoped, **without** the +11 d add-on. |
| **Amber** | $2.57 – $5.13 | Works only with ≥1.6 orders per customer, which is unproven. **Treat as Red for planning.** No ad budget beyond test scale. |
| **Red** | > $5.13, **or inconclusive under M0.3 AC-1** | Paid acquisition is off the table. Pull M2.2 (share artifact) and M2.3 (referral) forward into Phase 1: **+11 engineer-days**. |

**To buy a real Green/Amber separation you must halve the interval, which takes 4× the orders (120) and 4× the ad budget.** That is a legitimate option and it costs $1,200–2,400. It is not currently funded. Absent it, the plan is Red — see §8.4.

The prior CAC figure of $3–15 is unsourced (§9.2 #12). If it is accurate, the branch is Red.

#### Gate 3 — Payment rail (binary)

At least one rail in the ~1.5% class (Payme or Click) must be **live in sandbox with a successful test transaction** before Phase 1 begins. If the only available rail is Stars at ~32%, contribution falls 35% and the price point must be re-derived first. **FAIL blocks Phase 1 regardless of Gates 1 and 2.**

**This gate now has an owner, a task and a date: M0.6 (4 engineer-days) plus the acquirer chain in §8.0. It cannot pass before week 8.** v1.0 asserted this gate and then scoped Phase 0 at 4–5 weeks with no merchant onboarding anywhere in the plan.

#### Gate 4 — Legal position (documented, not necessarily lawyered)

A written position on record for: the commercial-rights chain of the chosen music provider with the clause quoted; whether Russian users are served and how residency is satisfied; the recipient as a non-consenting data subject; and the celebrity-cloning prohibition restated as a product rule. **FAIL is not "we don't have a lawyer" — FAIL is "we have not written down a position."** Budget: 1 counsel-day (§8.10).

---

### 8.3 Phase 1 — MVP (169 engineer-days median / 263 P80, before the CAC-Red add-on)

One occasion, the Gate 1 language set, one local rail plus Stars, one price, one delivery format. Everything a competitor has that is not on this list is deliberately absent.

#### 8.3.1 Core product and platform

| ID | Milestone | Key acceptance criteria | Est. | Conf. |
|---|---|---|---|---|
| **M1.1** | Bot skeleton, wizard FSM, i18n | Table-driven test walks all valid and invalid FSM transitions; every state handles text, voice, photo, sticker and unexpected callback data, asserted by a completeness test over the transition table. A CI grep fails on any user-visible string outside the locale files. `/start` mid-wizard has a defined, tested outcome. | 5 d | Medium |
| **M1.2** | **Lyric-draft pipeline only** (FR-20–FR-27) | Two complete drafts per round with pairwise chorus-line token overlap <40% and one silent re-roll on failure. Every draft contains `name_as_sung` twice including once in the chorus and passes the FR-14 address lint, asserted pre-display on 50 samples. Structural tags in the music payload are 100% English, asserted in a contract test. LLM-judge fact-grounding ≥95% at ≥2/3 facts. Brief and drafts survive a killed session for 24 h. | 6 d | Medium |
| **M1.3** | Spoken-greeting pipeline (FR-39–FR-43, FR-45) | Three greetings from one brief with no extra input, end-to-end. Peak and integrated loudness inside the configured band, asserted by an ffmpeg check on fixtures in CI. Delivered as `voice` OGG/Opus mono with a rendering waveform on mobile and desktop. Duration 20–45 s, out-of-range regenerated once then trimmed at a sentence boundary. | 4 d | Medium |
| **M1.4** | Queue, workers, idempotency | Killing a worker with 20 jobs in flight loses zero jobs and double-charges zero users, verified by a scripted chaos test asserting ledger and queue state. Replaying one provider callback 5 times produces exactly one delivery and one ledger entry. An intermediate-then-failure status sequence reaches `failed` with the credit refunded, from fixtures. | 5 d | Medium |
| **M1.7** | Storage, mirroring, delivery + retry ladder (FR-54–FR-58) | Every delivered file is served from own storage — asserted by a check that no delivered URL host matches a provider domain, and by a fixture test where provider URLs have expired and re-download still works. **Each of the five FR-56 failure classes is exercised in a harness and no class results in a silently lost paid order.** The message-type log matches FR-54's order exactly. `file_id` is captured and reused on re-send with zero bytes transferred. | 5 d | Medium |
| **M1.8** | Moderation pipeline | Name sanitisation, multilingual blocklists (UZ both scripts, RU, EN) including transliteration/leetspeak/spacing evasions, PII and defamation-pattern detection, prompt-injection defence, three-way verdict with non-specific block copy, review queue, versioned rules recorded on every verdict. Blocked input consumes no entitlement and reaches no provider. | 7 d | Medium |
| **M1.9** | Data-protection plumbing | Region routing per LR-58, retention jobs per FIL-7, `/forget`, the recipient/third-party deletion route reachable without Telegram, and the flagged/unflagged log split. A seeded aged record is purged on schedule and the purge is logged. | 6 d | Medium |
| **M1.10** | Legal surfaces **+ the five LR-60 build items** | Offer, privacy and refund policy reachable in ≤2 taps in all three languages, naming the entity, tax id and support contact. Purchase rejected without a recorded consent event. **`/paysupport` (LR-60 #7, non-negotiable), `/terms`/`/privacy`/`/help` plus persistent menu links (#8), versioned consent capture (#5), abuse contact and takedown surface reachable outside Telegram (#13), fiscalisation configuration for the live rails (#17).** Versioned acceptance records. | 4 d | Medium |
| **M1.11** | Operator console, observability, runbook | A named dashboard shows queue depth, p95 payment→delivery, provider error rate, daily orders, contact rate and **free-tier cost per paid order** from production data. Each SEV-1/2 alert fires within 5 minutes, verified by deliberate trigger in staging. The runbook contains a tested full-provider-outage procedure including notifying in-flight orders. | 7 d | Medium |
| **M1.12** | Free-tier metering, caps, anti-farming **+ the SEC-6/NFR-16 reconciliation** | Free-tier cost per free user and per paid order visible on the dashboard from day one. One free preview per `tg_user_id` for life. **A lifetime cap of 6 free lyric generations per `tg_user_id`, and a per-user rolling-30-day cost budget that hard-stops the free path with an explanatory message** — see §8.5. Rate limits and new-account heuristics enforced and reversible. | 5 d | Medium |

#### 8.3.2 Payments — rebuilt against LR-14

v1.0 priced Payme + Click + Stars + the shared abstraction at **13 days**. LR-14's own table totals **16–26** for the same scope, and LR-15 warns in terms: *"the shared core is the real work… do not let a plan estimate the rails and forget the core."* The plan then did exactly that, landing 3–13 days under its own floor. Rebuilt:

| Component | LR-14 band | Allocated | Where |
|---|---|---|---|
| Shared payment core (ledger, idempotency, reconciliation, refund automation, entity/receipt alignment) | 6–10 | **8** | M1.5 |
| Payme | 5–8 | **8** = 4 (M0.6, sandbox) + 4 (certification, `CancelTransaction`/`CheckTransaction`/`GetStatement`, error-code semantics, production go-live, refunds) | M0.6 + M1.6 |
| Click | 3–5 | **4** | M1.6 |
| Telegram Stars | 2–3 | **3** | M1.6 |
| Rail abstraction (LR-20: "~1 extra day") | — | **1** | M1.6 |
| **Total** | **16–26** | **24** | |

24 sits above the midpoint of LR-14's band, and deliberately: splitting Payme across two phases costs the top of its range, because the sandbox work in M0.6 has to be re-opened, re-contextualised and certified months later.

| ID | Milestone | Key acceptance criteria | Est. | Conf. |
|---|---|---|---|---|
| **M1.5** | Payment core, ledger, reconciliation | The ledger is append-only — a test asserts no code path issues UPDATE or DELETE against it. A user abandoning mid-generation and restarting cannot get a second generation on one credit, asserted by a concurrency test. Every money-moving operation idempotent on a client key. All amounts integers in minor units with an explicit exponent, with a test asserting 39 000 UZS transmits as `3900000` (LR-9). The daily reconciliation report shows zero unmatched payments for 3 consecutive production days before launch. | 8 d | Medium |
| **M1.6** | Rails: Payme (remainder) + Click + Stars behind one abstraction | Each rail completes a real end-to-end transaction **and a real refund** in production. Switching the default rail is configuration. `refundStarPayment` charge ids persisted at capture. Payme's certified error-code semantics asserted against the certification fixtures. | 12 d | **Low** — certification is a third party's schedule and the reason this line was previously below its own floor |

#### 8.3.3 Name-pronunciation subsystem — the differentiator, priced

v1.0 gave FR-46–FR-53 **no line of its own**: half of a 6-day "lyrics + name-safe pipeline" line. FR-46–FR-53 specify a seeded ~2,000-name dictionary with per-engine respellings, IPA and stress per output language; a normaliser folding Uzbek apostrophe variants and both scripts; an LLM fallback returning ranked candidates with confidence and caching; a pre-payment preview loop with three candidates and manual respelling; per-asset re-render controls; an admin review queue; and a promotion loop. This is the product's second differentiator and §4.6 says nobody in the researched market solves it. Priced:

| ID | Milestone | Key acceptance criteria | Est. | Conf. |
|---|---|---|---|---|
| **M1.15** | Normaliser + dictionary schema + resolution order (FR-46, FR-47) | `Gulnora`, `Gulnoraʼ`, `GULNORA`, `Gul-nora` all resolve to one entry, as a pure unit test. NFKC, `ё/е` unification, Uzbek apostrophe folding across `ʻ` (U+02BB), `'` (U+2019), ASCII `'` and the bare `o`/`g` forms, hyphen/space stripping. **Uzbek Latin↔Cyrillic transliteration round-tripped over the full 80-name corpus in both directions.** Resolution order exact → normalised → fallback, with the resolution source logged. All 80 corpus names produce the expected canonical form. | 5 d | Medium |
| **M1.16** | **Dictionary content: ~2,000 seeded Uzbek and Russian given names and diminutives**, per-engine respellings + IPA + stress, per output language | A seeded name resolves with zero LLM calls, logged with source `dictionary`. Coverage test: ≥90% of a held-out sample of 200 names drawn from a different source resolves from the dictionary. Every entry carries a reviewer id and a review date. | 4 d **engineering** (seeding pipeline, validation, import, coverage harness) | **Low** — the content is not engineering. See the reviewer line below |
| **M1.17** | LLM respelling fallback + cache (FR-48) | An invented name returns ≥2 ranked candidates with IPA and a confidence score; a second order with the same name makes zero LLM calls; a low-confidence result appears in the FR-91 queue. Schema-validated output, no tool calls, no URLs (SEC-4). Per-call `cost_usd` recorded. | 4 d | Medium |
| **M1.18** | Per-engine markup compiler (FR-49, FR-50) | `pronunciations` is a first-class request field carrying grapheme, IPA, stressed form and syllables; **each adapter** compiles it — SSML `<phoneme>` where supported, `+` stress marks for SpeechKit, capitalised-stressed-vowel grapheme respelling for music. Payload snapshot tests for **3 languages × 4 engines**. Where respelling differs from input, payload and displayed strings differ and the displayed string is byte-identical to `name_as_sung`. | 4 d | Medium |
| **M1.19** | Pre-payment preview loop (FR-51) | A ~3 s TTS clip of the name alone in the output language is delivered **before any payment, at no cost**, with Yes / "Sounds wrong". "Sounds wrong" advances to the next candidate and re-previews, up to 3, then offers manual respelling. Selecting an alternative changes the stored respelling used downstream, asserted end-to-end. | 3 d | Medium |
| **M1.20** | Per-asset re-render controls (FR-52, FR-36) | Every delivered song variant and voice message carries "Name sounds wrong". Greeting re-render leaves entitlement unchanged and demonstrably uses a different respelling, up to 2 per asset; the third press explains the cap and routes to support. A song pronunciation re-render decrements the single free re-render and the counter is visible to the user. | 4 d | Medium |
| **M1.21** | Admin review queue + promotion loop (FR-53, FR-91) | Approve / edit / reject with write-through to the dictionary; rejected candidates demoted. After approval, the next order with that name resolves from the dictionary with no LLM call. Respellings delivered with no complaint within 7 days are queued for promotion by a scheduled job. | 3 d | Medium |
| | **Subsystem total** | | **27 d** | |

**M1.16's real cost is not the four engineer-days.** Two thousand names × three output languages, each needing a respelling, a stress mark and an IPA form, is content production. The realistic method is an open name list plus an LLM first pass plus native review of every entry that will actually be used. Native-reviewer labour: **~40 hours Uzbek, ~24 hours Russian.** This is the line most likely to be cut and, with the Uzbek reviewer already load-bearing (§9.3 #13), the one whose cut silently degrades the differentiator rather than visibly removing it.

#### 8.3.4 Production provider layer — never previously estimated

M0.1 builds a **5-day bench harness**. v1.0 then assumed it into production. It is not the same artefact: a bench harness proves a name can be sung; it does not survive a provider outage at 200 orders/hour, does not re-route by health, does not reconcile a callback that never arrived, and does not stop a retry storm from producing a catastrophic invoice. M1.4's 5 days cover queue and idempotency, not this. API-1–API-8, ASY-10, ASY-11, ASY-14 and ASY-16 have no line anywhere in v1.0.

| Component | Requirement | Est. |
|---|---|---|
| Router by `(capability, language, health, cost)` in that order, ordered fallback chain per capability, per-order admin override | API-7 | 4 d |
| Circuit breaker per provider per capability: open after 5 consecutive failures or >30% error rate over 5 min; half-open probe every 60 s; state mirrored to `providers_health` and shown in admin | ASY-14 | 3 d |
| 30-second reconciler over non-terminal generations past `poll_after_s`; pre-created variant rows; `parse_callback` returning `None` for interim callbacks | ASY-10, ASY-11 | 4 d |
| Shared Redis token buckets at 70% of published vendor caps, enforced across all worker replicas | ASY-16, NFR-10 | 2 d |
| Cross-adapter contract suite running identically against every adapter: submit → poll/callback → terminal → assets non-empty; rejection; timeout; duplicate and out-of-order callbacks | API-6 | 4 d |
| `FakeSongProvider` / `FakeSpeechProvider` with configurable latency and failure injection, default in dev and CI | API-5 | 2 d |
| Closed error taxonomy + import-linter rule in CI + DB-backed runtime provider config editable in admin | API-1, API-3, API-4 | 3 d |
| Hardening the four M0.1 bench adapters into production adapters: idempotency keys, signed callback tokens carrying no Telegram id, `cost_usd` reporting, `health`, capability metadata | API-8, ASY-8, ASY-9 | 5 d |
| **M1.22 total** | | **27 d** |

**Confidence: Medium, not Low** — and the reason is specific. The architecture is fully specified in §6.2 and §6.3; the unknown is the four vendors' actual API shapes, and M0.1 removes that unknown by building adapters against the same four providers before Phase 1 opens. **If Phase 0 does not build all four adapters, M1.22 reverts to Low (×2 = 54 d).**

#### 8.3.5 Assets and surfaces — also never estimated

| ID | Milestone | Key acceptance criteria | Est. | Conf. |
|---|---|---|---|---|
| **M1.13** | **Public share page** (FR-59, FR-60, FR-61) — a web property, not a link | `/g/<short_code>` renders a rich preview when pasted into Telegram, verified per release. `robots.txt` disallows `/g/` for all crawlers but allows `TelegramBot`, `Twitterbot`, `facebookexternalhit`, and the exact allow-list is asserted. A generic crawler UA is refused. **The recipient's name is absent from the OG preview.** Opt-in only; disabling returns 404 thereafter for all user-agents including allow-listed crawlers. "Make one like this" carries a referral `start` parameter and a click produces an attributed order. Includes its own domain, TLS, OG image rendering, and a privacy surface for a public page carrying third-party data. | 6 d | Medium |
| **M1.14** | **Cover-art generation** (FR-55, FIL-2) | Every `sendAudio` sets `title`, `performer`, `duration` and a cover-art `thumbnail`; the bubble shows a human-readable title and cover art, and the scrubber shows correct length before playback. Deterministic template rendering across **three scripts** (Latin, Cyrillic, Uzbek Latin with `ʻ`), inside Telegram's thumbnail constraints, with an OG-sized variant for M1.13. Fonts licensed for commercial embedding, evidenced. | 3 d | Medium |
| **M1.23** | **Static sample packs, 3 languages** (FR-5, FR-38) | Playing samples any number of times triggers zero provider calls and creates no order row. One ~25 s song excerpt + one ~20 s spoken greeting per language, **plus one playable zero-cost sample per persona per language (9 clips)**. Loudness-normalised, stored by us, served from own storage. Each shipped sample carries a recorded rights check that it is licensed for marketing use. | 2 d eng | Medium |
| **M1.24** | **Voice catalogue: 3 personas × 3 languages** (FR-38, FR-44, LR-45) | Voices addressed by our own stable identifier mapped to vendor ids in config, so a withdrawal is a config change. Persona catalogue signed off before launch; no persona named after, marketed as, or trained on a real identifiable person; **no user-supplied reference-audio path exists in the codebase**, asserted by a CI check. | 2 d eng | **Low** |

**M1.24 is mostly not engineering, and it has calendar time.** LR-45 permits only a licensed stock voice used within its library terms, or a voice commissioned from a named actor under a written agreement covering synthesis, unlimited use and this product. Route (a) means reading and recording the licence terms for each of nine voice slots. Route (b) means casting, contracting and recording. **The live risk: the Uzbek voice inventory on the only identified UZ provider (SpeechKit, per §6.2's routing table) may not contain three distinct personas at all**, in which case FR-38 cannot be met in Uzbek without commissioning — 2–6 weeks of calendar and a counsel-reviewed contract. Non-engineering cost: 1–2 counsel-days, 3–5 founder-days, and the calendar.

#### 8.3.6 Phase 1 roll-up

| Block | Median | Factor | P80 |
|---|---|---|---|
| Milestone lines M1.1–M1.24 | 141 | | |
| Integration and hardening — **cross-cutting work, not insurance** (20%) | 28 | | |
| **Phase 1 subtotal** | **169** | | |
| ├─ Low block (M1.6 12, M1.16 4, M1.24 2) | 18 | ×2 | 36 |
| └─ Medium block (everything else, including the integration line) | 151 | ×1.5 | 226.5 |
| **Phase 1 P80** | | | **263** |

*The 28-day integration line is real work — wiring 24 milestones, three languages, four providers, three rails and one ledger into one product — not padding. The only insurance in this plan is the P80 multiplier.*

#### Definition of Done for Phase 1

Done only when **all eight** are simultaneously true:

1. **Ten strangers, ten completions.** Ten people who are not the founder, not related to the founder, and have never seen the bot each go from `/start` to a delivered kit, having paid real money from their own account on their own phone, with no human intervention. Ten of ten succeed. *(This is the criterion most often quietly skipped. It should not be.)*
2. Wall-clock `/start` → final delivery under 12 minutes in each of those ten runs.
3. Over the last 100 production orders: p95 payment→delivery ≤8 min, p99 ≤20 min.
4. Three consecutive production days with zero unreconciled payments.
5. A worker killed mid-generation with ≥20 jobs in flight loses zero jobs and creates zero double-charges.
6. The nightly name regression suite is within 10pp of the Phase 0 baseline for every shipped language and modality.
7. A refund can be issued by one admin command in under 60 seconds and appears correctly on the reconciliation report.
8. Offer, privacy policy and refund policy published, reachable in ≤2 taps, naming the operating entity — and **the UZ State Register entry complete** (LR-57, LR-60 #9).

---

### 8.4 The CAC-Red add-on is in the headline, not beside it

v1.0 excluded the +11-day add-on from both headline totals while §8.1 instructed the reader to *"treat Amber as Red for planning"* and §9.2 #12 stated the only CAC figure available is unsourced. Under the document's own reasoning, the planning case is Red:

- Green requires a measured CAC ≤ $1.73 (§8.2, Gate 2) — a narrow target.
- Amber is instructed to be planned as Red.
- Inconclusive (M0.3 AC-1) is Red.
- The only prior, $3–15, is above the Red threshold and is explicitly not assumed.

Three of four outcomes carry the add-on. It belongs in the number.

| ID | Pulled forward from Phase 2 | Est. | Conf. |
|---|---|---|---|
| **M2.2 → M1.25** | Share artifact (vertical 9:16 video card: cover, waveform, name, audio, watermark) | 7 d | Medium |
| **M2.3 → M1.26** | Referral + promo codes | 4 d | Medium |
| | **Add-on** | **11 d** → P80 **16.5** | |

**Phase 1, planning case: 180 engineer-days median, 280 P80.** If Gate 2 returns Green, subtract 11 / 16.5 and return both to Phase 2.

**The D-9 contingency, also named rather than assumed.** $0.28 COGS assumes ~$0.05 for the song and, via FR-30 and D-9, that the second variant is marginal-cost-zero. That is a Suno-billing property, and §9.1 #4 concedes neither music provider has been evaluated. If M0.5 finds ElevenLabs Music bills per generated second or per credit and charges the second variant separately, then FR-30's rationale falls, COGS rises to ~$0.33 and Gate 2's table moves. **Contingency: D-9 flips to "one variant delivered, second held as an upsell" — 1 engineer-day against M1.7's delivery ordering, plus a recomputed contribution table. Booked as a named 1-day contingency, not a re-plan.**

---

### 8.5 Free-tier cost — re-derived against the requirements that generate it

LR-32 states its arithmetic as *"~3 cheap LLM passes ≈ $0.010 + a 3-second SpeechKit clip ≈ $0.001 ≈ $0.011 per free user ≈ $0.11 per paid order"* against a hard ceiling of **$0.12 per paid order** (NFR-16). The requirements do not permit three passes. FR-20 plus FR-26 permit **three draft sets of two complete lyrics each — six generations** — and FR-21, FR-23, FR-24, SEC-2, SEC-5, FR-48, FR-51 and FR-8 each add model calls that were never counted.

**Cost basis, stated so it can be replaced by an invoice:** a cheap-tier model at roughly **$1 per million input tokens and $5 per million output tokens**. One complete verse/chorus lyric is ~350–500 output tokens against a ~1,200–2,000-token prompt (brief + per-language style guide + name-safety instructions) ≈ **$0.0040**. Screening and judging passes are short-output ≈ **$0.0006–0.0008**.

| Item | Requirement | Qty per engaged free user | Unit | Cost |
|---|---|---|---|---|
| Lyric draft generations (1 initial round + 2 free rounds × 2 complete lyrics) | FR-20, FR-26 | 6 | $0.0040 | $0.0240 |
| Contrast re-roll allowance (chorus overlap <40%, one silent re-roll) | FR-21 | 0.75 | $0.0040 | $0.0030 |
| Fact-grounding LLM judge, per round | FR-23 | 3 | $0.0008 | $0.0024 |
| Moderation LLM pass + prompt-injection classifier (brief and each draft set) | SEC-2c/d | 4 | $0.0008 | $0.0032 |
| Output re-screen before display | SEC-5 | 3 | $0.0006 | $0.0018 |
| Pronunciation LLM fallback, ~35% cache-miss on an unseeded name | FR-48 | 0.35 | $0.0020 | $0.0007 |
| Name preview TTS (SpeechKit), avg 1.4 of up to 3 candidates | FR-51 | 1.4 | $0.0010 | $0.0014 |
| Voice-brief STT, ~20% of users × 45 s | FR-8 | 0.2 | $0.0045 | $0.0009 |
| Inline editing | FR-25 | see note | — | $0 |
| **Per engaged free user** | | | | **$0.0374** |
| **Per paid order at 10% conversion** (×10) | NFR-16 | | | **$0.374** |

**Against the $0.12 ceiling: over by 3.1×.** LR-32 was not slightly optimistic; it counted 3 model calls where the requirements specify **13**, and omitted moderation, the judge, STT and the pronunciation fallback entirely.

**FR-25 must be disambiguated, and it is a requirement change either way.** *"Free unlimited inline editing of the chosen draft before payment"* is ambiguous. If an edit is the user typing into their own copy of the text and the edit is stored verbatim, it costs nothing and the table above stands. If an edit calls a model to rewrite a line, it is **uncapped LLM cost sitting directly under a hard ceiling**. Recommended resolution: FR-25 is client-side editing, no model call. If model-assisted editing is wanted it is capped at 3 per order on the cheap tier: **+$0.012 per engaged free user → $0.49 per paid order.**

**Two resolutions, both costed. Pick one; the current text picks neither.**

| | **(A) Cap the requirements to fit $0.12** | **(B) Raise the ceiling to fit the requirements** |
|---|---|---|
| Changes | FR-26 → 0 free re-roll rounds (one draft set only); FR-20's two drafts produced in **one** call; FR-23's judge sampled at 5% not 100% on the free path; FR-51 → 1 candidate not 3 | NFR-16 → **≤$0.40 per paid order** and **≤$0.05 per free user per rolling 30 days** |
| Arithmetic | 2 lyrics in 1 call $0.0060 + moderation $0.0016 + re-screen $0.0006 + judge (5%) $0.0000 + pronunciation $0.0007 + TTS $0.0010 + STT $0.0009 = **$0.0108/free user = $0.108/paid order** ✓ | $0.374 → covered with headroom for the FR-25 variant |
| Cost | Removes the "write different ones" affordance entirely, and removes FR-21's "choice between two goods" — one of the document's stated departures from the competitor and its top-of-funnel conversion mechanic | Contribution $5.41 → **$5.13** (−$0.28, a 5% move). Gate 2's Red threshold moves to $5.13 and Green to $2.57 |

**Recommendation: (B), with one cap that must exist under either option.** $0.28 of contribution is cheaper than removing the free draft loop. But **SEC-6 and NFR-16 do not currently reconcile at all**: SEC-6 permits 15 free lyric generations per day per user with **no lifetime cap**, which is 450 generations per 30 days ≈ **$1.80 per user** — 12× NFR-16's per-user ceiling even after raising it. Reconciliation, priced into M1.12 (4 d → 5 d):

- **A lifetime cap of 6 free lyric generations per `tg_user_id`**, matching exactly what FR-20 + FR-26 grant for one order.
- SEC-6's per-hour and per-day limits retained as anti-burst controls, not as the cost control.
- A **per-user rolling-30-day cost budget** that hard-stops the free path at $0.05 with an explanatory message and an operator-reversible flag.
- Free-tier cost per free user and per paid order on the dashboard from day one (LR-34, OBS-7) — it is a measured number by launch, not an assumed one.

---

### 8.6 The competitor's free-tier waste — derived, with its range

$0.72 is one of §1.4's three headline levers and one of Gate 2's four lines. v1.0 showed it without arithmetic while showing our own number with it. Derived:

The competitor pattern gives a new free user **one full free song generation** plus **unlimited pre-purchase lyric regeneration**. The competitor's cost basis is a Suno reseller — verified from the research corpus: kie.ai / sunoapi.org at ~$0.05 per generation returning two tracks; acedata at $0.0348 per track; apiframe at $0.11 per generation; EvoLink at $0.111 per song.

| Component | Basis | Cost |
|---|---|---|
| One free song generation | kie.ai/sunoapi.org, the default across the open-source implementations in the corpus | $0.050 |
| Lyric passes before abandoning, median 3 | ~$0.007 per mid-tier pass | $0.021 |
| **Per free user** | | **$0.071** |
| **Per paid order at 10% conversion** (10 free users per paid order) | | **$0.71 ≈ $0.72** |

**Two corrections to how this number has been used.**

1. **It is derivable and internally consistent — on *their* cost basis, not ours.** The objection that "a full free song at $0.20–0.28 COGS would give $2.00–2.80" compares our **full kit** (song + 3 premium TTS greetings + LLM lyrics) to their **single reseller API call**. Those are different things. $0.20–0.28 is never a song; it is a kit.
2. **It is a range, not a point.** Three of the four reseller prices in the corpus are above $0.05:

| Competitor's song cost | + 3 lyric passes | Per free user | **Per paid order @ 10%** |
|---|---|---|---|
| $0.0348 (acedata) | $0.021 | $0.056 | **$0.56** |
| $0.050 (kie.ai — planning figure) | $0.021 | $0.071 | **$0.71** |
| $0.110 (apiframe / EvoLink) | $0.021 | $0.131 | **$1.31** |

**Restated for §1.4 and Gate 2: competitor free-tier waste is $0.56–$1.31 per paid order, planning figure $0.72.** It keeps its place as a lever. It stops being a point estimate.

*And the comparison that actually matters is not in the document at all:* if **we** ran their free tier on **our** provider mix — ElevenLabs Music (unevaluated, §9.1 #4) plus a premium name clip — the figure would be materially higher and is unknown until M0.5 measures it. Our design avoids this by never giving away music, which is the whole point of FR-5 and LR-30.

---

### 8.7 Phase 2 — Retention and second occasion set (23 d median / 35 P80, after the CAC-Red pull-forward)

**The honest problem:** a birthday is annual, so a "same recipient next year" loop has a 365-day cycle and shows no signal for a year. The loop that can be built and measured this quarter is **same buyer, different recipient, different occasion**.

| ID | Milestone | Key acceptance criteria | Est. |
|---|---|---|---|
| **M2.1** | Recipient book + reminder engine | A scheduled reminder fires within ±2 h of target for 20/20 seeded records across three time zones. Unsubscribe stops all future sends, asserted by schedule→unsubscribe→advance-clock→expect-zero. Recipient records carry a retention expiry and purge on schedule. | 6 d |
| **M2.4** | Five additional occasions (recommended: wedding/*toʻy*, new baby, anniversary, Navruz, 8 March) | Each has a per-language lyric guide and three greeting scripts signed off by a native reviewer. The name regression suite runs green per occasion (occasion changes the lyric context around the name and can break pronunciation). Adding a sixth occasion requires no code change, demonstrated in the test suite. | 6 d |
| **M2.5** | Funnel and cohort analytics | The funnel reconciles to the ledger with zero variance on paid-order counts. A weekly cohort report shows repeat-purchase rate by signup week from ≥4 weeks of production data. | 4 d |
| **M2.6** | Multi-kit packs (`KIT_3`, `KIT_10`, `ADD_VOICE`) | Pack purchase credits the ledger correctly; refund of a pack is proportionate and reconciles; expiry is displayed at sale. | 3 d |
| | Integration buffer (20%) | | 4 d |
| | **Total** — Medium ×1.5 | | **23 d → P80 35** |

*M2.2 (share artifact, 7 d) and M2.3 (referral, 4 d) have moved to Phase 1 as M1.25/M1.26 under the CAC-Red planning case (§8.4). If Gate 2 returns Green they return here and Phase 2 is 36 d / 54 P80.*

**Exit criterion (business, not engineering):** the weekly cohort report shows repeat-purchase above a threshold set at the start of the phase (suggest ≥15% of buyers placing a second order within 60 days). If not, Phase 3 is deferred and the phase re-runs against the retention hypothesis.

### 8.8 Later phases — P80s brought into compliance only

Neither phase below was rebuilt line by line. Both are almost certainly under-scoped by the same mechanisms found in Phase 1 (unpriced content production, unpriced procurement, an unpriced production provider layer for a new capability) and both must be re-derived from Phase 2 data before either is committed. What is corrected here is only that their P80s violated the confidence rule.

| Phase | Median | Conf. | Rule | v1.0 P80 | **Corrected P80** |
|---|---|---|---|---|---|
| **Phase 2R** — RU-resident Postgres with `data_region` routing, YuKassa, 54-FZ receipts, RKN notifications, RU offer and privacy policy. **Must be decided before the Phase 1 storage layer is built** — the routing seam (LR-58) is Phase 1 work; the second region is Phase 2R work. | 18 | Low | ×2–3 | 30 ✗ | **36–54** (plan 36) |
| **Phase 3** — B2B bulk orders (9 d), branded templates (6 d), voice cloning for the buyer's own voice only (10 d), B2B/cloning legal position (4 d), buffer (7 d). *Voice cloning is gated, not scheduled: it does not start until M3.4's position is written and the provider's ToS read in full.* | 36 | Low | ×2–3 | 65 ✗ | **72–108** (plan 72) |
| **Phase 3, cloning cut** — B2B only | 26 | Low | ×2–3 | — | **52–78** (plan 52) |

---

### 8.9 Calendar translation — reproducible arithmetic

v1.0 said *"0.7 engineer-days per calendar day"* and then reported 28 calendar weeks for 85 engineer-days. Neither reading of "0.7" produces 28:

- Per **calendar** day: 0.7 × 7 = 4.9 engineer-days/week → 85 ÷ 4.9 = **17 weeks**.
- Per **working** day: 0.7 × 5 = 3.5 engineer-days/week → 85 ÷ 3.5 = **24 weeks**.

**This plan uses the second reading and says so: 0.7 engineer-days per *working* day, 5 working days per calendar week, = 3.5 engineer-days per calendar week for a solo founder-engineer.** The 0.3 that disappears is support, ops, marketing, merchant-onboarding follow-up and context-switching — the work §9.3 #17 correctly says is additive to calendar and not to engineer-days.

#### Solo founder-engineer

| Phase | Median e-d | ÷ 3.5 | P80 e-d | ÷ 3.5 |
|---|---|---|---|---|
| Phase 0 | 25 *(with the ad flight at 1.75 e-d/wk for 3 weeks)* | **9 wk** | 44 | **15 wk** |
| Phase 1 (planning case) | 180 | **51 wk** | 280 | **80 wk** |

**Solo, this does not launch inside a year.** That is not a scheduling problem to be optimised; it is the finding. The contract engineer in §8.10 is not optional.

#### Two engineers — with the costs v1.0 assumed away

v1.0 claimed a contract engineer "compresses to ~14 weeks", which requires near-perfect parallelisation of two engineers on one codebase with zero onboarding and zero coordination cost. Priced properly:

| Factor | Value | Reasoning |
|---|---|---|
| Contractor throughput | 5.0 e-d/wk | 1.0 per working day — full-time, no support/marketing/legal duties |
| Founder throughput | 3.5 e-d/wk | 0.7 per working day, as above |
| Raw combined | 8.5 e-d/wk | |
| **Onboarding, one-off** | **−8 e-d** | Contractor at 40% output for 2 weeks (−6); founder loses 30% of 2 weeks to onboarding (−2) |
| **Coordination tax, ongoing** | **−15%** | Review, merge, interface negotiation, duplicated context on one codebase → 7.2 e-d/wk |
| **Serialisation haircut, ongoing** | **−10%** | The payment core, the ledger and the provider layer are each single-owner critical chains that do not parallelise → **6.5 e-d/wk** |

| Phase 1 | Engineer-days | + onboarding | ÷ 6.5 | Calendar |
|---|---|---|---|---|
| Median | 180 | 188 | 28.9 | **29 weeks** |
| P80 | 280 | 288 | 44.3 | **44 weeks** |

**Not 12 weeks, and not 14.** The 15% and 10% figures are judgement, stated so they can be argued with; the alternative — assuming perfect parallelisation — is the error being corrected.

**Three engineers is not modelled and should not be assumed.** Adding a third to a 24-milestone codebase with one payment ledger and one provider layer raises the coordination tax faster than it raises throughput.

**Launch date, combining §8.0 and this table:** Phase 1 opens week 9 (median) or 15 (P80); add 29 or 44 weeks. **Launch week 38 median, week 59 P80.**

---

### 8.10 Team, non-engineer resources, and the support-labour cap

| Role | Commitment | When | Substitutable? |
|---|---|---|---|
| Founder — product, backend, prompts, support, marketing | Full time | Day 1 | No |
| **Contract backend engineer** | **29–44 weeks**, not 12 | Phase 1 — **required, not optional** (§8.9) | Yes, in principle |
| **Uzbek native reviewer / QA** | 4–8 h/week ongoing **+ ~40 h for M1.16 dictionary seeding** | From the first Uzbek clip in Phase 0 | **No.** Cannot be automated, cannot be done by a non-native speaker, cannot be deferred |
| Russian native reviewer | 2–4 h/week **+ ~24 h for M1.16** | Phase 0 | Possibly the founder |
| Designer | 3–5 days total (cover-art templates M1.14, share card M1.25, sample-pack art M1.23) | Phase 1 | Yes |
| **Counsel** | **7–11 days** (was stated as 3–5) | Gate 4, M1.10, M1.24, UZ registration | Partially |
| Part-time support | Triggered | Post-launch | No, once triggered |

**Non-engineer effort, totalled for the first time.** None of this is in the 228 engineer-days and none of it was in the 137.

| Resource | Days / hours | Where it goes |
|---|---|---|
| Founder, outside engineering | **23–29 days** | Phase 0 fake door (10, §8.2) · launch documents owned by the founder — LR-60 #6, #10, #13, #14, #16, #19 (4–6) · voice procurement M1.24 (3–5) · sample-pack curation M1.23 (2) · merchant-onboarding paperwork and follow-up across 2–4 weeks (4–6) |
| Counsel | **7–11 days** | Gate 4 position (1) · LR-60 #1–#5 offer, ToU, two privacy policies, consent texts (2–3) · UZ counsel for ZRU-547 and State Register (1–2) · provider licence matrix #11 (0.5) · age policy, ROPA, DPIA #12/#15/#18 (1–2) · D-6 entity and tax structuring (1–2) · M1.24 voice agreements (1–2) |
| Uzbek reviewer | **~160 h ≈ 27 six-hour days** | 4–8 h/wk from Phase 0 to launch (~120 h) + M1.16 dictionary seeding (40 h) |
| Russian reviewer | **~60 h ≈ 10 days** | Ongoing review + M1.16 (24 h) |
| Designer | 3–5 days | M1.14, M1.23, M1.25 |
| **Contractor** | **29–44 weeks × an unstated weekly rate** | **The largest cost line in the project, and it has no number anywhere in this document.** It belongs in §10 as a decision alongside D-1 |

**Launch documents: 19, per LR-60.** Five of them are engineering and are now inside M1.10's 4 days (#5 consent capture, #7 `/paysupport`, #8 the command handlers, #13 the abuse/takedown surface, #17 fiscalisation config). The rest are counsel and founder work, counted above. #9 — the UZ State Register entry — is calendar time on the §8.0 chain, not days of anybody's work.

**Support-labour cap — derived, not measured.** The research establishes the *mechanism* (quality failures plus regenerate-costs-full-price) but gives no ticket rate. Assumptions: 90 minutes/day of sustainable solo support, **seven days a week** (birthdays do not respect the working week — this is the detail that breaks founders who plan for five), and 5 minutes per average ticket. **Cap ≈ 18 tickets/day, ≈126/week.** At a 25% contact rate that is ~72 orders/day; at 12%, ~150; at 6%, ~300.

Two things this hides, both more important than the headline:

1. **The cap binds on language, not founder hours.** If the founder cannot judge Uzbek audio, the Uzbek ceiling is the reviewer's availability — ~72 Uzbek tickets/week at 6 h — and that is the real ceiling on Uzbek order volume. Budget the reviewer as a *support* resource from the day Uzbek launches, **on top of** the 160 hours above.
2. **Contact rate is a design variable and buying it down is far cheaper than buying support capacity.** One free re-render costs ~$0.20–0.28 in COGS; if 20% of buyers use it that is ~$0.05 per order, and it converts the single largest ticket class — a bad pronunciation — from a conversation into a button. This is precisely where the plan departs from every competitor: their "regenerate costs full price" wall generates their complaint corpus, and copying it would import their support load with it.

**Hiring trigger, stated in advance so it is not argued about later:** hire part-time support when the 7-day rolling average exceeds **15 tickets/day**, or median first response exceeds **4 hours for 3 consecutive days**. Not before, and not on a feeling.

---

### 8.11 Testing strategy

*Unchanged from v1.0 in substance. Three suites now have an owning milestone that did not previously exist, and they are named here so they are not built twice: the cross-adapter contract suite belongs to **M1.22** (API-6), the dictionary and transliteration round-trip tests to **M1.15**, and the per-engine payload snapshots to **M1.18**.*

**Unit-testable (pure functions by design, <30 s, pre-commit gate):** name normalisation and Uzbek Latin↔Cyrillic transliteration round-tripped over the full corpus; stress-mark insertion and the respelling rule; RU→EN structural tag mapping; syllable counting per language; style-string assembly **including the comma-only split rule** (splitting on `/` corrupts tokens like `4/4`); banned-phrase filtering; ledger arithmetic (debit, refund, idempotent replay, insufficient balance); price and promo maths including the UZS minor-unit exponent; referral eligibility; FSM transition-table completeness and reachability.

**Contract tests (recorded fixtures, no live providers)** covering especially the failure modes: the intermediate-status trap; content rejection; artist-name-in-style rejection; rate limiting and backoff; timeout and partial response; duplicate and out-of-order callbacks. Fixtures are refreshed weekly against live providers, and **a fixture-drift failure is a real alert** — it is how a silent provider API change is caught. *Owner: M1.22.*

**Telegram integration harness** (dedicated test bot, its own token, database and payment sandbox; a Telethon/Pyrogram client acting as a synthetic user): full wizard happy path per language; abandonment and resume; `/start` mid-order; payment success, failure and cancellation in the rail sandbox; audio delivery and the retry ladder; progress-message editing and cleanup; the user blocking the bot mid-generation; duplicate callbacks; rate-limit handling on a burst of 30 messages. Runs on every merge to main and before every release — not on every commit; it is slow and costs credits.

**Generation-quality regression.** The 80-name corpus becomes a permanent suite; this is what stops a prompt tweak or a silent provider model update from destroying the only differentiator.

- *Nightly:* 20 stratified names, sung and spoken, transcribed by ASR, compared to the expected form by phoneme-aware edit distance; alert on a >10pp drop from baseline. **Honest limitation:** ASR round-trip is a proxy, it mishears too, and it mishears in correlated ways — its threshold must be calibrated against the Phase 0 human labels, and the ASR-vs-human agreement rate must be reported alongside every nightly result so nobody mistakes a proxy score for an accept rate.
- *Weekly:* 20 clips rated blind by native reviewers using the M0.2 rubric. Ground truth, and it re-calibrates the proxy. Budget 1–2 paid hours per language per week — **included in the reviewer hours in §8.10.**
- *Per release:* the full 80 names, ASR-scored. A release dropping any language/modality below its Gate 1 bar does not ship. **Plus a render check on M1.14's cover art in all three scripts and an OG-preview check on M1.13.**
- *On provider, model-version or prompt-template change:* full 80-name run plus a human sample before rollout. **No exceptions** — a provider model update is invisible and can move pronunciation quality with no code change.

**Load testing.** The binding constraint is not our server but provider concurrency and Telegram's limits (~30 messages/second globally, 1/second per chat). Scenarios: (1) 500 orders in a 60-minute window — no job lost, no double-charge, queue drains within SLA, p95 degrades gracefully rather than timing out; (2) **the 1 January problem** — in this region an outsized share of recorded birthdays fall on 1 January and on the first of each month, because that is what gets entered when the exact date is unknown, so model a 10× hour, not a 2× hour; (3) provider 429s injected at 50% — queue backs off, no user sees an error, delivery completes late rather than failing; (4) full provider outage for 20 minutes mid-flight — fallback engages (this is what M1.22 was for) or affected users are notified and credited; (5) worker restart under load. Run before launch and before every expected peak.

---

### 8.12 Launch checklist

Every item binary, with a named owner. Launch means all boxes, not most.

**Product** — Phase 1 DoD, all 8, verified and recorded · ten-stranger test 10/10 with dates logged · name regression green at release for every shipped language and modality · every user-facing string reviewed by a native speaker · tested error messages for payment failed, generation failed, provider down, name rejected, unsupported input · **sample packs live in all shipped languages with zero provider calls on playback** · **cover art renders correctly in Latin, Cyrillic and Uzbek Latin**.

**Money** — rail live in production with a real transaction from a real card · refund path tested in production with a real refund · reconciliation green 3 consecutive days · price displayed inclusive of all fees, in local currency, before payment · **UZS minor-unit exponent verified against a real charge (LR-9)**.

**Legal** — offer, privacy and refund policy published and reachable in ≤2 taps · entity, tax id and support contact on the offer · **offer entity = acquiring entity = receipt entity, evidenced (LR-28)** · consent captured at purchase and stored as an event · recipient-data retention policy written and the purge job tested · provider ToS conformance memo written · **voice-persona licences or actor agreements signed and filed (LR-45, M1.24)** · data-residency position documented for every jurisdiction served · **UZ State Register entry complete (LR-57, §8.0)**.

**Operations** — dashboard live (queue depth, p95 delivery, provider error rate, orders, contact rate, **free-tier cost/order against the §8.5 ceiling**) · all SEV-1/2 alerts verified by deliberate trigger · incident runbook written and one scenario rehearsed · **fallback provider tested by disabling the primary, with the circuit breaker observed opening and half-opening** · backups running and one restore verified · secrets in a store, verified by a git history scan.

**Support** — support entry point with a stated response expectation · canned responses for the top 6 issues in every shipped language · Uzbek reviewer on-call schedule agreed and paid for · free re-render button live and its cost modelled · ticket volume logging from order #1.

**Go-to-market** — creatives approved by a native speaker per language · attribution wired and verified with 20 test clicks · daily budget cap set and a CAC-breach kill rule written · load test at 10× expected peak passed within the last 7 days.

## 9. Assumptions, dependencies, risks

**[LB] = load-bearing: if wrong, the estimate or the business case moves materially.**

### 9.1 Technical

1. **[LB]** At least one music provider produces acceptable sung output in Russian and English at the Gate 1 bar. If none does, this is not a re-plan, it is a different project.
2. **[LB]** A deterministic respelling rule exists that meaningfully improves sung-name accuracy. If mitigation only works hand-tuned per name, it is not shippable and Gate 1 Tier D applies.
3. Speech providers expose stress/phoneme control adequate for Uzbek names (SpeechKit SSML stress marks are the assumed mechanism). Uzbek TTS quality is **unvalidated**; if SpeechKit is not good enough for a paid gift, NFR-21's degradation path becomes the default and the differentiator weakens.
4. **[LB]** ElevenLabs Music and Google Lyria are commercially and qualitatively acceptable for Russian and Uzbek lyrics. **They have not been evaluated**, and their asset-count and billing behaviour are equally unknown. The two-variants-at-one-price property is a **billing property of a Suno-backed reseller pipeline** — a provider LR-37 forbids us from using — and nothing about it transfers to a provider in our routing table. The Phase 0 billing-shape measurement (M0.5) establishes, for every configured provider, how many assets one accepted request returns and what the billing unit is, before Phase 1 opens. If billing turns out to be per asset or per second, direct COGS moves from **$0.28 to $0.33** and contribution from **$5.13 to $5.08** on the local rail (**$3.33 to $3.28** on Stars) — inside NFR-14's $0.45 ceiling and immaterial to Gate 2's verdict — but FR-30a, the §2.2 "doubles perceived value" row and D-9 all fall. If both providers fail on quality or on rights, the routing table has no compliant primary and the product's rights story needs rework.
5. Provider concurrency around 20 requests / 10 s suffices at Phase 1–2 volumes. It does not at Phase 3 B2B batch volumes, which is why M3.1 budgets batching and scheduling.
6. Both audio variants fit comfortably under Telegram's 50 MB limit, so no chunking logic is needed.
7. Provider API surfaces remain stable through Phase 1. Weekly fixture-drift checks are the detection mechanism; a breaking change costs 1–3 unplanned days.

### 9.2 Commercial

8. **[LB]** A payment rail in the ~1.5% class is obtainable by the operating entity. If the only rail is Stars, contribution falls 35% and the price must be re-derived.
9. **[LB]** The $0.28 direct COGS figure holds at the chosen provider mix. It is a research estimate, not an invoice, and it is provisional until M0.5 measures the billing shape.
10. Free-tier waste is two different numbers and neither is a measurement. The competitor-pattern figure of ~$0.72 per paid order is **derived on their reseller cost basis, not observed**, and spans **$0.56–$1.31** depending on which reseller price in the corpus is used; nothing establishes what they actually spend, and no requirement or estimate line in this document depends on it. Our own figure is arithmetic from our own requirements: **$0.374 per paid order at 10% conversion** (§8.5), against the $0.12 that NFR-16 originally carried and that the requirements never permitted. It is the second-largest cost line, D-8 settles which ceiling governs it, and it is a measured number by launch rather than an assumed one (LR-34, OBS-7).
11. The reference price of $5.90 is assumed for all Gate 2 arithmetic. A different price moves every CAC threshold proportionally (D-1).
12. **The $3–15 CAC figure from prior research is explicitly NOT assumed.** It is unsourced, nothing in the plan depends on it, and Gate 2 exists to replace it — bearing in mind that at its manual-fulfilment cap Gate 2 buys a two-way answer, not a three-way one, and the three-way answer is a Phase 1 exit measurement taken over ≥200 attributed paid orders.

### 9.3 Organisational and legal

13. **[LB]** A qualified Uzbek native reviewer is available 4–8 h/week, reliably, from Phase 0, **plus roughly 40 one-off hours for dictionary seeding and two-pass review**. No substitute, no automation. The reviewer is also a *support* resource once Uzbek launches, on top of those hours.
14. The founder can sustain 90 minutes/day of support, seven days a week, alongside building.
15. Counsel is available within 5 business days when needed. A longer turnaround delays Gate 4 and therefore Phase 1's start.
16. **[LB]** UZ registration in the State Register of Personal Data Bases completes within the pre-launch window. Calendar time, not engineer-days, and it is a launch blocker; its duration is estimated and unsourced.
17. No estimate line includes founder time on marketing, partnerships or fundraising — those are additive to calendar, not to engineer-days — and no line anywhere in this document carries a weekly rate for the contract engineer, who is the largest single cost in the project (D-13).
18. **[LB]** The critical path is legal and administrative, not engineering. Entity registration, two acquirer onboardings, in-country hosting procurement and the State Register entry run in calendar weeks owned by the founder and counsel; Gate 3 cannot pass before week 8 however fast the code is written. Engineer-days are one input to the schedule, not the schedule, and compressing engineering does not move the front of the project.
19. On-call is one person unless D-14 funds a second. The founder cannot be both primary and secondary, and the compensating control is OBS-11's automatic trip of FR-107 — new orders pause when a SEV-1 goes unacknowledged for 60 minutes. **The residual risk is accepted, not mitigated:** an incident that begins while the founder is asleep or unreachable is *contained* by closing intake, not fixed, and paid in-flight orders keep running against providers nobody is watching until someone acknowledges.
20. Nine persona-language pairs (3 personas × 3 output languages) can be procured before M1.3 completes, as either licensed stock voices whose library terms permit redistribution of the rendered audio inside a sold digital good, or voices commissioned from named actors under written agreement (LR-66). **Unvalidated:** the only identified Uzbek speech provider may not carry three distinct Uzbek personas at all, in which case FR-38 can only be met by commissioning — 2–6 weeks of calendar, a counsel-reviewed contract, and a cost line that is not engineer-days (D-15).

### 9.4 Principal risks and their controls

| Risk | Control |
|---|---|
| Uzbek singing does not work | Gate 1 tiers A–D; Tier B is the planning base case |
| Paid acquisition uneconomic | Gate 2 branches; the not-viable branch pulls share and referral into Phase 1 (+11 d), which is the planning case |
| Rail unavailable or Stars-only | Gate 3 blocks Phase 1; LR-20 keeps both rails behind one abstraction |
| Entity, acquirer certification or State Register calendar slips | The §8.0 chain has named owners and dates; M0.6's sandbox integration starts at week 0 so engineering is never the reason Gate 3 is late |
| Provider withdraws, changes terms, or degrades silently | API-1/API-7 abstraction, per-capability kill switches (FR-87), weekly fixture-drift alerts, mandatory full regression on any provider change |
| The delivery model rests on a billing property nobody measured | M0.5 measures asset count and billing unit per provider; FR-30 is written for *n* ≥ 1 and FR-30a/FR-30b select the product on the finding |
| A prepaid provider balance or quota runs out mid-flight | API-9 balance and quota reporting, FR-108's days-of-cover panel, OBS-10 alerting, ASY-25 treating exhaustion as provider-down rather than as a transient |
| Retry storm against a paid API produces a catastrophic invoice | Per-order cost circuit breaker at $0.90 (NFR-15) plus daily spend anomaly alert |
| Free tier farmed | SEC-7 controls plus LR-34 measurement; assume it will happen |
| A defamatory or harassing gift is generated and shared | Pre-generation moderation (SEC-2/3), roast-tier escalation, a 4-hour takedown path, a named escalation owner |
| Recipient data-protection complaint | Order-scoped minimisation, day-and-month-only recipient records, 30-day brief retention, a deletion route reachable without Telegram, an in-bot notice at the point of entry |
| Telegram enforcement against off-platform checkout | D-2; both rails built; never surface a payment link in an iOS in-app browser context |
| Chargebacks push a rail's dispute rate over its own threshold | An evidence pack per order (FR-109), a stated contest/accept rule (LR-61), monthly per-rail dispute reporting, and SEC-14 feeding fraud-coded losses to the abuse list |
| A paid order is generated and can never be delivered | FR-103: assets held for full retention, one retry on the next inbound update, automatic full refund at 72 h, a named admin queue, excluded from delivered revenue until resolved |
| Reminder clustering (1 January) swamps the send budget | FR-97's rate-governed fan-out on a token bucket subordinate to transactional delivery, NFR-23's 50% ceiling, and a dedicated load-test scenario |
| A restore reinstates money or messages that already happened | ENV-11 reconciliation run before traffic is readmitted — ledger, dedup sets, delivery suppression, reminder rescheduling — drilled at least twice a year (ENV-12) |
| A vendor withdraws a voice mid-life | API-10's designated same-language substitute; a config repoint within 24 h; delivered assets never re-rendered |
| Unredeemed credits mis-state revenue | LR-63 recognises revenue on delivery, FR-111 reports the deferred balance monthly against the ledger, FR-110 reconciles it to each rail's own statement |
| Nobody is awake when a SEV-1 fires | OBS-11's escalation ladder ending in an automatic intake pause at 60 minutes; the residual risk is accepted under §9.3 #19 unless D-14 funds a secondary |
| Support load exceeds solo capacity | Free re-render button buys down the largest ticket class at ~$0.05/order; hiring trigger stated in advance |
| MAU decays like the incumbent's (~89% in 7 months) | The retention loop is MUST-class (FR-71–FR-76), not garnish |

---

## 10. Decisions required from the client before work starts

Each blocks specific work. Each needs an owner and a date.

| # | Decision | Blocks | Why it cannot be decided in the build |
|---|---|---|---|
| **D-1** | Launch prices in all four currencies. Build assumes $5.90 / 39 000 UZS / 490 ₽ / 300 XTR. | Pricing config; **Gate 2's ad test** | Willingness-to-pay and positioning are founder calls; only the ladder structure is engineering. Every CAC threshold moves proportionally. |
| **D-2** | Telegram payments posture: Stars-only inside Telegram, or off-platform checkout on our own domain. | Payment architecture, unit economics, checkout copy | Trades ~30 margin points against opaque, unappealable platform risk. The build is rail-agnostic; the P&L is not. Two sub-decisions: are Stars SKUs priced to hold net revenue constant (≈1.45× the card price) or price-matched with the fee absorbed; and Stars settlement mechanics — hold period, minimum withdrawal, withdrawal fee, the FX basis at withdrawal versus capture, and what document an accountant can use — must be written down from Telegram's current published terms before Stars go live (LR-62). |
| **D-3** | Russian market posture. **This SoW resolves to geo-gating RU out of v1** with Posture A available as Phase 2R (18 d). Confirm or overturn. | **The storage layer — must be settled before it is built** | 152-FZ requires the primary database in Russia and cross-border transfer notified. Market strategy plus risk appetite. |
| **D-4** | Lawful basis for processing the recipient's personal data. | Privacy policy, retention schema, the entire consent flow | The recipient never consented and may never know. No RU or UZ statute cleanly authorises it. The highest-stakes legal question in the project. |
| **D-5** | Uzbek localisation, State Register entry and cross-border specifics. | UZ hosting, **launch timing** | Requires UZ counsel; registration has calendar time, is on the §8.0 critical path, and may be a launch blocker. Nothing here was verified in research — the corpus covered Russian operators only. |
| **D-6** | Entity structure and tax residence. | The international rail, VAT, fiscal receipts, most launch documents, LR-28 — **and everything on the §8.0 chain, one-for-one** | Offer entity = acquiring entity = receipt entity. Upstream of D-7 and LR-27, and week 0 of the calendar: entity registration cannot start until it is answered, and the acquirer onboardings cannot start until registration completes. |
| **D-7** | International rail: Paddle (merchant of record) vs Stripe vs Stars-only — **and availability for the chosen entity**. | Rail integration (3–6 d) | Depends on D-6 and banking. |
| **D-8** | Free-tier economics: which of §8.5's two resolutions is taken — **(A)** cap the requirements to fit $0.12 per paid order, losing the two free refinement rounds and the two-draft choice, or **(B)** raise NFR-16 to ≤$0.40 per paid order and ≤$0.05 per free user per rolling 30 days — and separately, how generous the first 90 days are against a hard capped budget. | Free-tier limits config, FR-20/FR-26 scope, NFR-16, Gate 2's contribution line | The requirements as written cost **$0.374 per paid order**, 3.1× the original $0.12 target; the document prices both resolutions and picks neither. (A) removes a stated departure from the competitor and a top-of-funnel conversion mechanic; (B) costs ~$0.28 of contribution. Acquisition strategy with a number attached, and a founder call either way. |
| **D-9** | Deliver every variant a generation produces (SoW default: yes) or hold additional variants as an upsell. **Conditional on the Phase 0 billing-shape measurement (M0.5): if the selected music provider returns one asset per request, or bills per asset, this decision does not arise.** | Delivery UX, NFR-14 modelling, the §2.2 differentiation claim | Only reachable once M0.5 has established the provider's asset count and billing unit. Presented to the client with that finding attached, not before. |
| **D-10** | Is sender-voice-cloning on the roadmap at all? | Nothing at launch; sets up a separate compliance programme if yes | Determines whether a biometric-data workstream (LR-48's seven prerequisites) is needed. Answering no now is cheaper than answering yes later. |
| **D-11** | Does v1 publish a shareable public gift page? SoW default: opt-in only, recipient's name absent from the OG preview. | FR-59, FR-61 | Strongest available viral loop; collides directly with D-4. |
| **D-12** | Uzbek native reviewer — availability, cost, and whether the founder speaks Uzbek. Scope includes the one-off dictionary seeding and review hours (~40 h Uzbek, ~24 h Russian) as well as the ongoing 4–8 h/week. | Phase 0 start; **M1.16's dictionary content**; the Uzbek support ceiling | If the founder does not speak Uzbek, the reviewer's ~6 h/week becomes the binding ceiling on Uzbek order volume, not the founder's hours. The dictionary content is native-speaker labour, not engineering, and it is the line most likely to be cut in a way that silently degrades the differentiator. |
| **D-13** | Contract backend engineer: funded or not, at what weekly rate, starting when. | Phase 1's schedule and its largest cost line | Solo, Phase 1 does not launch inside a year; the plan books 29–44 weeks of a second engineer and this document contains no rate for it anywhere. Engineering cannot decide whether it is funded, and the answer changes the launch date by months. |
| **D-14** | On-call cover: contract a paid secondary responder, or accept documented single-person on-call with FR-107's automatic intake pause as the compensating control. | The team table, OBS-11's rota, and the residual risk recorded in §9.3 #19 | One person cannot be primary and secondary on a seven-day rota. Either a retainer is paid or the risk is signed for by name; neither is an engineering choice. |
| **D-15** | Voice-persona procurement route and budget for nine persona-language pairs: licensed stock voices used within their library terms, or voices commissioned from named actors under written agreement. | M1.3 completion, FR-38, LR-66, the launch checklist | A licence fee or an actor fee plus a counsel-reviewed contract template — a commercial cost line, not engineer-days. If the Uzbek inventory does not carry three distinct personas, commissioning adds 2–6 weeks of calendar ahead of launch. |
| **D-16** | Support desk: an off-the-shelf ticketing product, or a ticket table inside `hbd-admin`. | FR-105, FR-106, LR-22's 24 h operator SLA, and the non-Telegram entry point for payment and refund issues | A third-party desk is a subscription *and* a data processor handling user and payment data, which needs a processing agreement and an entry in the ROPA; the in-house route is engineer-days. The choice is cost, legal posture and build time together. |

### Resolutions already made in this document

Where the source drafts disagreed, this SoW resolved as follows, and these are recorded so they are not silently re-opened:

1. **Free tier** — static samples + one lyric-draft round (2 drafts) + **2** free refinements on a cheaper model + one ~3 s name preview. The functional draft's 3 uncapped rounds did not close against the commercial draft's cost target. The $0.12 ceiling that resolution was measured against did not itself survive §8.5's re-derivation; the shape stands, and D-8 settles the ceiling. *(FR-20, FR-26, LR-30–LR-32)*
2. **SKU vs credits** — the ledger is credit-denominated from day one so packs need no rework; exactly **one SKU** is sold in v1 and no wallet UI exists; packs ship in Phase 2. The functional draft rejected packs; the commercial draft argued for them. *(FR-64, LR-2, LR-3)*
3. **Free re-renders** — **one per kit for any reason**, plus free pronunciation re-renders of *greetings* (cheap) which do not consume it; a *song* pronunciation re-render draws on the entitlement (expensive). Reconciled on cost, not on preference. *(FR-36, FR-52, LR-4)*
4. **Retention periods** — paid audio 12 months, free-text brief 30 days, recipient identity 90 days without reminder consent, indefinite-until-purge with it. The drafts variously said 180 days, 24 months and 90 days. *(FIL-7, LR-52)*
5. **Russian market** — geo-gated out of v1, per the technical draft's recommendation, with a costed Phase 2R. *(ENV-7, LR-56, D-3)*
6. **Suno resellers** — removed entirely from the routing table, including as a legal-gated fallback. The technical draft listed one; the commercial draft forbade it. *(FR-31, LR-37)*
7. **All variants of a paid generation are delivered** — *conditional on the Phase 0 billing-shape measurement*. The premise that a provider bills per request and renders two assets at zero marginal cost is verified for a Suno reseller and for no provider in our routing table. FR-30 is written to handle *n* ≥ 1; FR-30a/FR-30b select the product on the measured finding; D-9 is put to the client only if FR-30a applies. *(FR-30, M0.5, D-9)*
8. **Reference price** — $5.90 / 39 000 UZS, and Gate 2's contribution arithmetic recomputed against it rather than the delivery draft's placeholder $5.00. *(LR-3, §8.2 Gate 2)*
9. **Phase 1 estimate** — the delivery draft priced the build and the commercial draft priced payments, moderation and data protection separately; the two overlapped by construction, and the delivery draft's 12 days for that work did not cover the commercial draft's 34–54. §8 prices them once, inside Phase 1, alongside the previously unpriced name-pronunciation subsystem, production provider layer and public surfaces: **180 engineer-days median, 280 at P80** for the planning case.
10. **Uzbek ships in both scripts at launch** — Latin default with a Cyrillic toggle and complete parity of every string, button, error and legal surface, not a v1.1 item. Both-script moderation, transliteration and Uzbek legal texts are already MUST-class, so the residual work is translation and native QA rather than engineering. *(FR-94, amending FR-3)*
11. **No recipient birth year is stored** — the recipient record holds day and month only, under the explicit opt-in of FR-71 and purged per FR-75. FR-73's age suggestion is derived from data already held, presented as editable, and never stored as a fact. Day and month is what the reminder loop needs; the year is the component that would turn the record into a date of birth. *(FR-102, LR-69)*
