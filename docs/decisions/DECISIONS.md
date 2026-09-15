# Vendor & Stack Decisions — Bayram

**Revision 1.0 · 26 August 2026**

Companion to [`../product/SCOPE_OF_WORK.md`](../product/SCOPE_OF_WORK.md). Every entry is a pick, a named fallback, and the trigger that switches to it.


> **Binding client constraint:** Payme and Click are ruled out for launch. All payment analysis assumes the fastest path to accepting money.


---

## 0. Verification notes (checked directly, after the research)


Three claims in this document were re-checked against primary sources before it was issued, because each one carries a decision.

**The UzLiB leaderboard is real and the scores are accurate.** [github.com/tahrirchi/uzlib](https://github.com/tahrirchi/uzlib) — Gemini 3.7 Flash 0.8092 (rank 2), GPT-5.6 Luna 0.7141 (rank 6), Claude Opus 4.5 0.6002 (rank 20), human-voter baseline 0.5894. Google sweeps the top five places. The full Claude set on the board is: Claude 3.7 Sonnet 0.6513 (rank 11), Sonnet 4.6 0.6411, 3.5 Sonnet 0.6362, **Sonnet 5 0.6147**, Opus 4.5 0.6002, Sonnet 4 0.5046, Sonnet 4.5 0.4847. **Claude Opus 5 and Haiku 4.5 are absent.** So the Gemini pick for Uzbek is well founded — the margin over the best Claude entry is ~0.16, which is large — but note that the strongest current Claude model has never been measured on it. If you want that datapoint, running Opus 5 against the public UzLiB set is a couple of hours of work.

**Gemini 3.7 Flash pricing confirmed — and it doubles.** $0.75 / $3.75 per MTok is correct **only through 31 December 2026**. On 1 January 2027 it goes to $1.50 / $7.50. The LLM line in the cost model doubles in about four months. It is small in absolute terms (~$0.024 → ~$0.048 per order) so it changes nothing today, but do not build a budget past new year on the current rate.

**The free tier trains on your data.** Google's own pricing page confirms free-tier content is "used to improve our products". The paid-tier-mandatory call in D5 is correct and is a privacy requirement, not a performance one — you are sending a third party's name and private family facts.


---

## 1. The stack

| Component | Pick | Price | Fallback (and trigger) | Why |
|---|---|---|---|---|
| Song generation | **ElevenLabs Eleven Music**, direct API, 1 track/order | $0.150/min → **$0.30** per 2-min track (same rate on every tier — no on-plan discount exists) | **Google Lyria 3 Pro** — switch if the bake-off favours it on Uzbek, if music concurrency saturates, or when Lyria reaches GA at $0.08 flat | Only GA self-serve first-party API with an explicit commercial-resale licence from $6/mo, trained on licensed stems, `composition_plan` places the name in a named section, payable from UZ by card |
| Song — do NOT use | Suno (any reseller), Udio, MiniMax direct, Stable Audio, MusicGen, Mubert/Loudly/Soundraw/Beatoven/AIVA | — | — | Broken licence chain / no export / closed to new users / no lyrics input at all |
| Uzbek TTS (Latin + Cyrillic) | **Aisha AI** (Gulnoza + male, mood=Cheerful/Happy) | 1 UZS/char → **$0.19**/kit (2,250 chars), billed in som | **Navoiy TTS self-hosted** (Apache-2.0, 10 emotion styles, bundled Cyrillic→Latin normaliser) — switch on latency/uptime failure or refusal of written commercial terms. Then **Azure uz-UZ** as degraded failover | Only Uzbek voice with emotional control that bills in UZS with a self-serve key — no card, no forex, no contract. Azure's uz-UZ has no emotion styles and no phonemes (footnote 3) |
| Russian TTS | **ElevenLabs v3** — inline IPA `/ɐˈlʲɵnə/` + `[excited]` audio tags | $0.10/1k → **$0.225**/kit | **Azure ru-RU** Svetlana/Dmitry with `<phoneme alphabet="ipa">` — switch if IPA consistency <85% on the golden set, or on outage | Best payable combination of hard stress control and celebratory register. Yandex's `+` marker is better and cheaper but cannot be paid for from UZ |
| English TTS | **ElevenLabs v3** | $0.225/kit | **Gemini 2.5 Flash TTS** (~$0.041) → OpenAI `gpt-4o-mini-tts` | Same voice family as Russian; one vendor, one key |
| LLM (intake + lyrics) | **Gemini 3.7 Flash**, PAID tier, `thinking_level` low/medium | $0.75/$3.75 per MTok → **~$0.024**/order | **GPT-5.6 Luna** ($0.20/$1.20) behind the same strict-JSON contract — switch on structured-output failure under load, or if the in-house Uzbek name eval reverses the ranking | Reportedly best-measured Uzbek at a third of Pro's price; failover is cheaper than the primary. **Paid tier mandatory** — free tier may train on customer data |
| Speech-to-text (optional briefs) | **ElevenLabs Scribe v2** + keyterm prompting | $0.22/hr + $0.05/hr keyterms → **$0.003**/kit | **Azure Fast Transcription** ($0.36/hr, uz-UZ Latin explicit) → **Google Chirp 3** — switch on low confidence or wrong-script output | Only global vendor that names Uzbek *and* publishes a WER tier (Good, >10–≤20%). **The name is typed, never transcribed** |
| Cover art | **Deterministic template composition** — Pillow/resvg + Noto Sans + pre-bought backgrounds | **$0.00** marginal; $13–27 one-off for 100–200 backgrounds | **Gemini 3.1 Flash Lite Image** (~$0.034) for text-free backgrounds only, name composited on top — switch only for measured conversion lift | Only path where the name is correct 100% of the time by construction. No image model renders U+02BB. Ideogram's own docs say to composite text manually |
| Moderation | **omni-moderation (free) → Azure Content Safety + custom blocklist → LLM policy judge in the intake call** | **~$0.0004**/kit (free below 5,000 records/mo) | Promote the LLM judge to first-line for Uzbek if Azure's recall measures badly on a 400-string probe set | Azure is the only vendor that lists `uz`, `ru` and `ru-Latn`; the blocklist is deterministic regardless of model quality; only a written policy can distinguish a grandmother's age from harassment |
| Audio post | **ffmpeg two-pass `loudnorm`** (I=-14 song, I=-16 speech) + libopus for Telegram voice notes | **$0.00** | None needed | The difference between "produced" and "AI slop", for free. Telegram `sendVoice` requires OGG/Opus or it renders as a file attachment |
| Payment rail | **Telegram Stars (XTR)**, 300 XTR/kit | Nets **~$3.82** on a $5.90-equivalent sale (~64% take rate) | **Polar** (apply day 1, ~$4.94 net) for international + as the Fragment escape hatch; **Payme/Click at ~2%** from month 3 behind an IP | Not merely fastest — the only rail Telegram permits for in-bot digital goods. Reaches domestic Uzcard/Humo buyers via the Stars reseller market |
| Normalisation layer | **Our own code, written first** | $0.00 | None | Owns U+02BB canonicalisation, script detection, transliteration, name respelling, golden-set regression. No vendor offers phoneme control for singing — this layer *is* the answer to the core failure mode |


---

## 2. Language capability matrix

**The four Uzbek capabilities are different products and must never be conflated.** A vendor that recognises Uzbek does not speak it; a vendor that speaks it does not sing it; a benchmark that measures Uzbek reasoning measures nothing about Uzbek Cyrillic.

| Capability | Uzbek — Latin (oʻ/gʻ) | Uzbek — Cyrillic | Russian | English |
|---|---|---|---|---|
| **SINGING** (music model vocals) | **NO VENDOR DOCUMENTS IT.** ElevenLabs Music — roster of 59 withheld → *UNSTATED, test*. Lyria — no list at all, only "generates lyrics in the language of your prompt" → *UNSTATED*. Suno — no official list, Turkic is a known gap → *UNSTATED + rejected on licence*. Mureka — **EXPLICIT NO** (closed 10-language list). ACE-Step v1 — absent from its published 19. **VERDICT: assume UNSUPPORTED; ship as measured beta only.** | Same as Latin, plus a distinct tokenisation risk: the apostrophe digraphs are a plausible failure point that Cyrillic input sidesteps. Untested by anyone. **VERDICT: UNSUPPORTED.** | ElevenLabs Music — **not named in any published list** → *UNSTATED* (the research's "highly likely" is an inference, and it is load-bearing since Russian is the fallback SKU). Mureka — **EXPLICIT YES**. ACE-Step — **YES, explicit top-10 tier**. **VERDICT: PROBABLE but unverified on the chosen vendor.** | ElevenLabs — **YES, native-like tier, explicitly named**. Every vendor — YES. **VERDICT: SUPPORTED.** |
| **TTS** (spoken synthesis) | **Aisha AI — YES**, 4 moods, M+F, UZS billing ✅ *pick*. **Navoiy TTS — YES**, Apache-2.0, 10 emotion styles, self-hostable ✅ *fallback*. **Azure `uz-UZ` — YES** (Madina F, Sardor M) but footnote 3: no phonemes, no lexicon, **no emotion styles at all**. **Narakeet — YES**, 5 genuinely native voices (the "64" headline is false). **Yandex — YES**, 3 voices, **all female**, no markup support. ❌ ElevenLabs, Google, OpenAI, Amazon, Cartesia, Rime, Deepgram, Fish, Hume — **NONE**. | **No hosted vendor accepts Cyrillic.** Azure's locale is literally "Uzbek (Latin, Uzbekistan)"; Narakeet states "Latin script only… transcribe any Cyrillic first". **We transliterate.** Navoiy ships its own Cyrillic→Latin normaliser (strong hint that Aisha's hosted API is Latin-internal too). Meta MMS `uzb-script_cyrillic` is the only native Cyrillic model and is **CC-BY-NC — unusable commercially**. | **ElevenLabs v3 — YES**, inline IPA with ˈ/ˌ stress, ~80-90% consistent ✅ *pick*. **Azure `ru-RU` — YES**, `<phoneme alphabet="ipa">` + custom lexicon genuinely work (no footnote 3) ✅ *fallback*. **Yandex — YES**, `+` stress marker is the only *deterministic* mechanism in existence — **rejected on payment rail, not on capability**. Amazon — Standard-tier only, a decade old. | **ElevenLabs v3 — YES** ✅ *pick*. Gemini 2.5 Flash TTS, OpenAI, Azure, Cartesia, Rime — all YES. Only language where the whole market competes. |
| **STT** (recognition) | **ElevenLabs Scribe v2 — YES**, "Good" tier = **>10% to ≤20% WER** (corrected from the research's ≤25%) ✅ *pick*. **Azure `uz-UZ` — YES**, Latin explicit, Fast Transcription. **Google Chirp 1/2/3 — YES**, region-pinned. **Yandex `uz-UZ` (Latin) — YES** ⚠️ *corrects the research's "unevidenced, reject"; rejected on payment only*. **Aisha — YES**, claims dialect + code-switching. ❌ AssemblyAI lists `uz` at its own **>50% WER** ("Fair") — a checkmark, not a capability. ❌ Deepgram — none. ❌ Whisper — token exists, hallucinates fluent wrong-language text. | **Which script Scribe emits is UNDOCUMENTED — highest-value 30-minute test.** Azure and Yandex are Latin locales by name. | Excellent everywhere. Scribe **"Excellent" ≤5% WER**; Deepgram, AssemblyAI ("High" ≤10%), Google, Azure all strong. | Excellent everywhere. |
| **TEXT GENERATION** (LLM) | **Gemini 3.7 Flash** reportedly best (UzLiB rank 2) ✅ *pick* ⚠️ *scores unverified at source*. **GPT-5.6 Luna** — strongest non-Google, at ⅕ the price ✅ *fallback*. **DeepSeek-V4-Flash** — competitive, cheapest. Claude family ~20 pts behind at 6.7× the price → **overturned as Uzbek writer**. ⚠️ **Purpose-built Uzbek fine-tunes score WORSE than general models** — several near random. ⚠️ TUMLU: Uzbek *Language & Literature* is the models' worst Uzbek subject, **at or below the 25% random baseline**, while Uzbek maths scores 73-81%. Models reason *through* Uzbek but are near-chance about Uzbek *as a language* — and lyric writing is entirely the second thing. | **COMPLETELY UNMEASURED on every model.** UzLiB converts to Latin; TUMLU is Latin. No public benchmark exists. **Architecture decision: generate in Latin, transliterate deterministically** (published models score ~0.999 char-level F1 — far more reliable than any LLM's unmeasured Cyrillic). | All frontier models excellent. Trap: **ё is collapsed to е by convention in training data**, so no model preserves Алёна reliably — capture the stressed form as an explicit intake field, don't ask the model to remember. | All excellent. |
| **MODERATION** | **Azure Content Safety — `uz` LISTED** ✅ *the only vendor on earth*, but "supported, not specially trained" → pair with a **hand-built blocklist** (100% deterministic). OpenAI omni — Uzbek **not named** in its 40-language evaluation. ❌ Perspective — no Uzbek + **EOL 31 Dec 2026**. ❌ AWS Comprehend — English only. | Azure auto-detects language; the blocklist covers both scripts. | Azure **`ru` + `ru-Latn`** both listed (translit matters — Telegram users type it constantly). OpenAI omni: Russian not named but near-certainly in the 40. | All vendors YES. |
| **TYPOGRAPHY** (cover art) | **Deterministic only.** Noto Sans/Serif, Inter, Montserrat cover **U+02BB** and **U+02BC** (SIL OFL 1.1, free to embed). ❌ **NO image model is known to render U+02BB correctly** — Ideogram's own docs say to add text manually. Most display fonts lack the glyph entirely → tofu box mid-name. | Noto Sans covers full Cyrillic incl. Ў/Қ/Ғ/Ҳ. Nano Banana Pro handles generic Cyrillic well but **Uzbek-specific letters are untested**. | Noto Sans; ё is preserved because it is *typeset*, not predicted. | Any font; any model. |
| **FORCED ALIGNMENT** (v2 karaoke) | **Montreal Forced Aligner ONLY** — CC-0 Common-Voice Uzbek acoustic model. **No hosted API on earth does Uzbek alignment.** ❌ ElevenLabs Forced Alignment covers 29 languages and **excludes Uzbek**. | Same (MFA, via Latin transliteration). | ElevenLabs FA **YES**; MFA Russian models **YES** (CC BY 4.0). | Both. |

**Reading the matrix in one line:** Uzbek support degrades monotonically as you move up the stack — recognition is solved, moderation is barely covered by exactly one vendor, speech is served by four small vendors of which one has emotion, text generation is unmeasured in Cyrillic, and singing is documented by nobody. Build the product's promise at the level where the evidence actually is.


---

## 3. Cost model

## One delivered kit — full arithmetic

**Kit = 1 song (2 min, one variant) + 3 spoken greetings (~750 chars each) + cover art.**
FX: 11,850 UZS/USD.

### Direct COGS, base case (no retries)

| Line | Arithmetic | Uzbek order | RU/EN order |
|---|---|---|---|
| Song — ElevenLabs Music | 2 min × $0.150/min | $0.3000 | $0.3000 |
| Speech — Aisha (UZ) | 2,250 chars × 1 UZS = 2,250 UZS ÷ 11,850 | $0.1899 | — |
| Speech — ElevenLabs v3 (RU/EN) | 2,250 chars × $0.10/1,000 | — | $0.2250 |
| LLM — Gemini 3.7 Flash | intake $0.0082 + lyric pass $0.0127 + UZ critic $0.0030 | $0.0239 | $0.0209 |
| STT — Scribe v2 (optional 45 s brief) | 0.75 min × ($0.22+$0.05)/60 | $0.0034 | $0.0034 |
| Moderation | omni free + Azure free tier | $0.0000 | $0.0004 |
| Cover art | Pillow/Noto on own worker | $0.0000 | $0.0000 |
| Audio post — ffmpeg | own worker, ~2 s CPU | $0.0000 | $0.0000 |
| **Base COGS** | | **$0.5172** | **$0.5497** |

### Expected COGS with realistic retries

Name pronunciation is the core failure mode and there is **no phoneme control on any music model**, so re-rolls are a normal operating cost, not an exception.

```
Song:    $0.3000 base + (25% re-roll rate × $0.3000)   = $0.3750
Speech:  blended (0.6×$0.1899 + 0.4×$0.2250) = $0.2039
         + 15% re-synthesis                             = $0.2345
LLM:     $0.0239 + critic loops/repairs $0.0100         = $0.0339
STT:     $0.0034
Mod/art/audio:                                          = $0.0004
─────────────────────────────────────────────────────────────────
EXPECTED COGS PER DELIVERED KIT                         = $0.6472  → call it $0.65
```

At a $5.90 sticker, COGS is **11.0% of gross** → gross margin 89.0%. The prior 91–95% figure survives, but only just, and only because the corrected song price is $0.30 rather than the $0.18 the false on-plan arbitrage implied.

**A 2-variant product would add $0.30 + a second concurrency slot** → COGS $0.95, 16.1% of gross. Rejected: ship one track, offer a free re-roll.

### Net after the chosen rail — Telegram Stars at 300 XTR

⚠️ Every Stars rate below is **PROVISIONAL** — Telegram publishes its rate table as an image and exposes `stars_usd_withdraw_rate_x1000` only as a config key with no documented value. Read it live before pricing.

```
Buyer pays (in-app iOS/Android):   300 × $0.0199        = $5.97
Buyer pays (UZ reseller, UZS):     300 × 220 UZS        = 66,000 UZS ≈ $5.57
Buyer pays (Fragment/web):         300 × $0.0145        = $4.35

You are credited:                  300 XTR   (per Star, NOT per dollar the buyer spent)
Fragment withdrawal:               300 × $0.013         = $3.9000   [21-day hold, 1,000-XTR floor]
TON → UZS via Wallet in Telegram:  × 0.98 (≈2% spread)  = $3.8220
Less expected COGS:                − $0.6472
─────────────────────────────────────────────────────────────────
FOUNDER NETS PER KIT                                    = $3.1748
```

**≈ $3.17 in the founder's Uzbek bank account per $5.90 kit.**

- Contribution margin on recognised revenue ($3.90): **81.4%**
- Take rate vs an in-app buyer's spend ($5.97): **64.0%**
- Take rate vs a Fragment buyer's spend ($4.35): **87.9%** — you cannot see or control which

### What the constraint costs, stated plainly

| Rail | Gross to you | Less COGS | Net per kit | vs Stars |
|---|---|---|---|---|
| Payme/Click (~2% MDR) — **ruled out** | $5.78 | −$0.65 | **$5.13** | +$1.96 |
| Polar Pro ($20/mo, 3.8%+$0.40, +1.5% intl, ~1.475% payout) | $5.11 | −$0.65 | **$4.46** | +$1.29 |
| Polar Starter (free, 5%+$0.50, +1.5% intl, ~1.475% payout) | $4.94 | −$0.65 | **$4.29** | +$1.12 |
| Gumroad (10% best case) | $5.31 | −$0.65 | **$4.66** | +$1.49 |
| **Telegram Stars (chosen)** | **$3.82** | −$0.65 | **$3.17** | — |

**The fast path forgoes $1.96 per kit versus a domestic acquirer — 33.2% of gross revenue.** At 1,000 kits/month that is **$1,960/month**; at 5,000, **$9,800/month**. This is a *revenue* haircut, not a margin collapse: gross margin on recognised revenue stays at 81%. COGS remains non-binding. The rail is the binding constraint, and the client is choosing to pay it for speed.

### Two pricing traps in the client's own numbers

1. **39,000 UZS ≠ $5.90.** 39,000 ÷ 11,850 = **$3.29** — a 44% discount to the USD price. At the UZ reseller rate that is only ~177 XTR, netting $2.30 gross → **$1.65 after COGS**, barely half the $3.17 above. The honest UZS price for a 300-XTR kit is **~66,000 UZS**. Either make the purchasing-power discount deliberate or fix the number. (490 RUB ≈ $6.13 is fine.)
2. **To actually net $5.90 you would need ~454 XTR**, which puts the in-app sticker at **$9.03** — a 53% price rise to hold your net constant. Don't. Take the 300-XTR price, and recover the difference by adding Payme/Click in month three.

### One free lever worth $0.30/kit

You always receive $0.013/Star; the buyer paid between $0.0145 and $0.0199. Nudging buyers toward Fragment or local reseller top-ups during onboarding costs them less and costs you nothing — it does not change your revenue, but it materially lowers the *perceived* price and lifts conversion at the same 300 XTR.

### Break-evens worth knowing

- **Polar Pro vs Starter:** $20/mo ÷ ($4.46 − $4.29) = **~118 kits/month**.
- **ElevenLabs Scale ($299/mo) is NOT a music discount** — Music is $0.150/min on every tier. It buys **5 concurrent music slots instead of 2**, and that is the only reason to buy it. Trigger: sustained queue depth, not cost.
- **2027 LLM repricing:** Gemini Flash doubles on 2026-12-31 → LLM line goes $0.034 → $0.068, COGS $0.65 → $0.68. Immaterial.


---

## 4. The decisions


### D1 — Which model generates the sung song?

**Decision.** ElevenLabs Eleven Music, direct API (never via fal.ai), on a paid plan from the first customer. Ship ONE track per order, not two.


**Reasoning.** It is the only shortlisted vendor that is simultaneously a GA self-serve first-party API, explicitly licensed for commercial resale from a $6/mo Starter plan ('Songs are available for broad commercial use on all paid plans'), trained on licensed stems so there is no upstream infringement cloud, controllable via composition_plan so the recipient's name lands in a named section at a known offset, and fully available and payable from Uzbekistan. Suno is cheaper, faster and better and is rejected outright — its rights are assigned to the reseller's account holder, obtained by the automated access its own ToS forbids, under a competing-product bar a paid song bot arguably trips, from a vendor still in label litigation, producing files that self-identify via ID3 bytes. Note two corrections to the input research that change the reasoning: (a) there is no on-plan discount — Music is $0.150/min on Free/PAYG through Business alike, so the 'Scale plan saves 40%' analysis is wrong and no tier should be bought expecting it; (b) the documented default model is music_v1 and section-by-section regeneration is NOT evidenced on the API reference, so the single feature the research called decisive is unproven. ElevenLabs still wins, but on licence clarity, lyric placement and payability rather than on re-roll. On variants: the competitor's two-variant UX is not a product decision, it is simply what one Suno call returns. ElevenLabs returns one track per call, so matching it doubles both cost and concurrency pressure. Ship one track and offer a free re-roll on request — that reads as service rather than as a menu, halves concurrency load, and costs $0.30 only on the minority of orders that ask.


**Fallback and switch trigger.** Google Lyria 3 Pro (lyria-3-pro-preview) via the Gemini API. Switch if any of: (1) the bake-off shows Lyria sings Uzbek acceptably and ElevenLabs does not; (2) ElevenLabs' music concurrency saturates — the real caps are Free 0, Starter/Creator/Pro 2, Scale/Business 5, Enterprise higher, so Scale at $299/mo buys 5 slots and is the cheapest headroom purchase, not the 2 the research claimed; (3) Lyria reaches GA and holds $0.08 flat per song, at which point it becomes primary on a 3.75x cost advantage plus a written IP indemnity no competitor offers. Do not promote Lyria while it is preview-only: model ids can be deprecated on short notice and it has no section-level editing at all.


**Cost.** $0.30 per 2-minute track ($0.150/min × 2). Expected $0.375/kit including a 25% re-roll allowance. 6.4% of a $5.90 kit.


**Confidence.** MEDIUM-HIGH on the vendor, LOW on Uzbek and Russian singing quality. Pricing, concurrency and commercial terms are verified against ElevenLabs' own pages. What is not verified is the thing that matters most: Eleven Music's 59-language vocal roster is withheld, so Uzbek AND Russian are both unstated for singing. A three-hour, sub-$15 bake-off across ElevenLabs, Lyria, Mureka (as negative control), MiniMax-via-fal, ACE-Step-on-Replicate and Suno-via-kie.ai (unpriced benchmark), on one fixed Uzbek lyric in both scripts plus one stress-sensitive Russian name, moves this to HIGH or overturns it. Getting the 59-language list from ElevenLabs support in writing is a one-email question worth doing in parallel.


**Reversibility.** CHEAP. Put both providers behind a MusicProvider interface on day one — submit(plan) → poll(id) → asset. Swapping is a config flag. Nothing about the entity, the payment rail or the customer relationship touches this choice.


### D2 — What does the bot promise when no vendor can sing in Uzbek?

**Decision.** Reposition the differentiator from 'sings in Uzbek' to 'speaks Uzbek properly, in both scripts'. Guarantee three spoken greetings in flawless Uzbek. Make the sung language an explicit user choice at intake, with Uzbek labelled 'beta' until the bake-off says otherwise, and a free re-roll or free switch to another sung language if the name is mangled.


**Reasoning.** This is not uncertainty, it is exhaustion of the evidence. Two vendors publish closed language lists and exclude Uzbek (Mureka explicitly; ACE-Step v1's 19), four publish nothing at all, and ElevenLabs specifically withholds the one roster that could settle it. Default to unsupported. The fallback the research proposed — Uzbek spoken greetings over a Russian-sung song — rests on a second unverified assumption, because Eleven Music's Russian singing is exactly as undocumented as its Uzbek singing, and it still has to pronounce an Uzbek name inside a Russian vocal line, which is the same failure mode wearing a different hat. The defensible architecture is: the SPOKEN layer carries the language, the SUNG layer carries the mood, and the recipient's name is pronounced by a synthesiser you control rather than guessed by a music model. Spoken Uzbek is where support is real and verifiable — Azure GA in both genders, Narakeet's five native voices, Aisha's hosted API, and now Navoiy's open weights. That claim is true today and no global competitor has it. Marketing 'sings in Uzbek' before measuring is a refund magnet the first time a name is mangled, and refunds are the one thing Telegram Stars punishes.


**Fallback and switch trigger.** If the bake-off fails everywhere: ship sung English or sung Russian (whichever measures better) as the default for Uzbek orders, with the recipient's name delivered correctly in the three spoken Uzbek greetings. Strategic reserve if Uzbek singing becomes commercially critical: ACE-Step 1.5, Apache-2.0, self-hostable, ~27x real-time on one consumer GPU, and the only model in the survey that could be FINE-TUNED to sing Uzbek rather than merely tested for it.


**Cost.** Zero incremental cost. Costs one line of honest copy and one intake question.


**Confidence.** HIGH that no vendor documents Uzbek singing; MEDIUM on whether Uzbek singing actually works in practice. The bake-off resolves it. If ElevenLabs or Lyria clears the bar, drop the beta label and market the singing loudly — it would be a genuine moat.


**Reversibility.** CHEAP in both directions. Upgrading the promise after a successful bake-off is free. Downgrading it after customers have paid for 'Uzbek songs' is expensive and reputationally worse than never claiming it.


### D3 — Which TTS speaks Uzbek?

**Decision.** Aisha AI hosted REST API (Gulnoza + male voice, mood=Cheerful/Happy) as primary. Self-hosted Navoiy TTS as the designated fallback. Azure uz-UZ as the third leg / degraded-mode failover.


**Reasoning.** Azure's two Uzbek voices carry footnote 3 in Microsoft's own source table — 'Phonemes, custom lexicon, and visemes aren't supported' — and their Style/Roles column is empty. Two product-critical capabilities missing at once: no way to fix a mispronounced name, no way to sound happy. An Azure birthday greeting sounds like a bank IVR, because that is what the voice was built for. Aisha ships four moods including Cheerful and Happy, both genders, and claims correct handling of Russian and English words embedded in Uzbek text — exactly what a real Uzbek brief contains. It also bills 1 UZS per character in som with a self-serve key: no international card, no forex, no merchant contract, which is the only vendor in the entire stack that fully satisfies the fastest-path constraint. The important correction to the research: the fallback is NOT Azure. It is Navoiy TTS — an Uzbek TTS model open-sourced by Aisha AI itself under Apache-2.0, built on CosyVoice2-0.5B, with ten emotional styles and a bundled utility that converts Uzbek Cyrillic to Latin and standardises apostrophes. That single artefact falsifies three of the research's own gotchas ('the only Cyrillic-Uzbek model is non-commercial', 'the two best open-source models for our languages are both non-commercial') and collapses the proposed 2-3 month F5-TTS fine-tune moat into something buildable now. Note also the vendor's own honesty: Navoiy's model card warns it 'can mispronounce names, loanwords, and abbreviations' and that styles are 'style requests, not guarantees' — direct evidence on this product's core failure mode that no other vendor publishes.


**Fallback and switch trigger.** Self-hosted Navoiy TTS (Apache-2.0) — switch if Aisha refuses commercial terms in writing, if p99 latency proves unacceptable, or if Aisha's uptime fails during the soft launch. Azure uz-UZ MadinaNeural/SardorNeural — switch to as emergency failover only; accept flat delivery, never accept it as the steady state. Narakeet's five genuinely native voices (Shavkat, Zulfiya, Dilnoza, Odina, Gulnora) exist purely as a source of additional voice IDENTITY — note the '64 Uzbek voices' headline is false, the other 59 are foreign 'Polyglot' speakers reading Uzbek with an accent.


**Cost.** 2,250 chars/kit (3 × ~750) × 1 UZS = 2,250 UZS ≈ $0.19 at 11,850 UZS/USD. 3.2% of a $5.90 kit. Navoiy self-hosted: GPU time only, effectively $0.00 marginal. Azure ~$0.036/kit (unverified — Azure's public pricing page renders '$-' placeholders).


**Confidence.** MEDIUM. Aisha's Uzbek quality is entirely vendor marketing, unverified by ear, and its commercial terms, SLA, latency and rate limits are all unpublished. But Navoiy's existence is strong indirect evidence that this lab genuinely does Uzbek TTS, and its bundled Cyrillic→Latin normaliser strongly suggests the hosted API is Latin-internal too — which partly answers the highest-value open question. Twenty real Uzbek names and twenty Russian names inside Uzbek sentences, run through all four moods and listened to, moves this to HIGH. Getting commercial terms in writing is a hard gate, not a nice-to-have.


**Reversibility.** CHEAP as code (one TtsProvider interface, language-routed). MODERATE as product: the research's real insight is that Uzbek voice IDENTITY is scarce — roughly eight usable voices exist worldwide and about three of them are male. If the bot markets 'three greetings in different character voices', that promise breaks in Uzbek first and may force a multi-vendor Uzbek stack for variety rather than redundancy.


### D4 — Which TTS speaks Russian and English, and how is lexical stress controlled?

**Decision.** ElevenLabs v3 for both, using inline IPA in forward slashes (/ɐˈlʲɵnə/) for stress and square-bracket audio tags ([excited], [laughs]) for celebratory register. Azure ru-RU Svetlana/Dmitry with <phoneme alphabet="ipa"> as the fallback.


**Reasoning.** Yandex SpeechKit is the technically superior answer and we are not using it. Its `+` marker (Ал+ёна) is a hard, deterministic front-end instruction the synthesiser obeys, not a probabilistic hint, and it costs $0.017 per kit against ElevenLabs' $0.225 — thirteen times less. It is rejected purely on the payment rail: Yandex publishes prices only in RUB and KZT and states that payment currency depends on which legal entity you contracted with. Paying the Russian entity from Uzbekistan means Russian acquiring, largely severed from international Visa/Mastercard; the Kazakhstan route wants a KZ instrument or a corporate contract — precisely the onboarding the client ruled out. Worth recording the nuance the research got right for a subtle reason: SSML did NOT survive into Yandex API v3 ('Поддержка SSML доступна только при использовании API v1'), but stress control did — it moved into TTS-markup, where `+` works on v3, Russian only. Azure's ru-RU rows carry no footnote 3, so <phoneme alphabet="ipa"> and custom lexicons genuinely work there — that is a real deterministic fallback, and unlike Yandex it is payable by card. Do not design Russian delivery around Azure's expressive MAI-Voice-2 voices: they are public preview, region-restricted, no SLA, and the GA Russian voices have no styles at all.


**Fallback and switch trigger.** Azure ru-RU with IPA phonemes — switch if the golden-set stress test shows ElevenLabs IPA below ~85% on the name set, or on an ElevenLabs outage. For English only, Google Gemini 2.5 Flash TTS (prompt-steered style, ~$0.041/kit) is a perfectly good second fallback. Yandex re-enters consideration only if a KZ billing relationship is ever opened for other reasons — never as a reason to open one.


**Cost.** 2,250 chars × $0.10/1k = $0.225/kit. 3.8% of a $5.90 kit. ElevenLabs tiers buy no per-character discount — every plan divides to exactly $0.10/1k on v3 and $0.05/1k on Flash; a plan buys concurrency and a prepaid commitment, nothing else.


**Confidence.** MEDIUM-HIGH. ElevenLabs Russian TTS support is verified from an enumerated language list. The weak point is that inline IPA is reported at ~80-90% consistency from secondary sources, not from ElevenLabs — it is a strong hint, not a command. Build a golden-set regression test of the 200 commonest Russian and Uzbek given names with their IPA and expected stress, and re-run it on every model change. Measure the real consistency yourself rather than trusting the number.


**Reversibility.** CHEAP. Same TtsProvider interface. The only sticky asset is voice identity — customers get attached to a voice, and PlayHT's death (accounts, clones and audio deleted with no export) is the cautionary tale. Keep at least two vendors per language and never let a voice identity live only in one vendor's cloud.


### D5 — Which LLM handles intake, lyric writing and name respelling?

**Decision.** Gemini 3.7 Flash on the PAID tier — thinking_level 'low' for intake turns, 'medium' for the single lyric pass — with GPT-5.6 Luna wired behind the same strict-JSON contract from day one. PROVISIONAL: this overturns the prior Claude direction on the strength of UzLiB scores that were not verified at source.


**Reasoning.** The prior direction was Claude Haiku/Sonnet. UzLiB — a native Uzbek multiple-choice benchmark on correct forms, usage and nuance, published by Tahrirchi, a verifiably real Uzbek NLP lab — measures precisely the skill this product sells, and reportedly places Google in the top five with Claude roughly twenty points behind at 6.7x the input price. Two structural findings fall out and both are counterintuitive enough to be worth acting on: within every vendor's own line-up the CHEAP model is better at Uzbek than the expensive one (3.7 Flash beats 3.1 Pro; Luna beats GPT 5.2; V4-Flash beats V4-Pro), and the purpose-built Uzbek fine-tunes are WORSE than the general models, several of them barely above random. So do not pay up for Uzbek and do not trust 'fine-tuned on Uzbek' as a proxy for quality. Two-vendor from day one because Gemini 3.7 Flash is thirteen days old with no independent testing of structured-output strictness under load, and the failover is cheaper than the primary. Paid tier is mandatory, not a cost decision: Google's free tier may train on prompts and responses, and every order carries a real named person plus private family facts.


**Fallback and switch trigger.** GPT-5.6 Luna — switch if Gemini's structured-output strictness fails under load, if the in-house Uzbek name eval reverses the ranking, or on any Gemini availability incident. DeepSeek-V4-Flash is the cost ceiling for a free tier, but its host's Uzbekistan payability is unverified; OpenRouter with crypto settlement is the geo/payment hedge for the whole layer and is worth keeping funded regardless.


**Cost.** ~$0.024 per order across intake (5 cached turns), the lyric+spoken-script pass, and an Uzbek critic pass. 0.4% of revenue. Budget 2x from 2027-01-01 — Google marks these rates as effective through 2026-12-31, doubling to $1.50/$7.50. Watch the OpenAI long-context price step on the failover: Luna is $0.20/$1.20 short-context but $0.40/$1.80 long, and large cached system prompts can cross it.


**Confidence.** LOW-MEDIUM, and honestly so. The entire 'overturn Claude' argument rests on specific UzLiB numbers that the adversarial pass did not verify against the live leaderboard, and the benchmark reportedly converts everything to Latin script, so it says nothing about Uzbek Cyrillic generation — a blind spot given both scripts are priority-one. Re-read the leaderboard from source before acting. Independent of that, build a 200-name in-house eval covering Uzbek possessive and case suffix agreement on proper nouns (Gulnoraga / Gulnoraning / Gulnorajon), vowel harmony, and both scripts. No published benchmark tests that, and it is exactly the failure mode. One day of work, highest-value unknown in the layer.


**Reversibility.** CHEAPEST decision in the document. Two vendors, one strict-JSON schema, one config flag. If UzLiB turns out to be misread, switching back to Claude costs an afternoon.


### D6 — How are voice briefs transcribed, and how is the recipient's name captured?

**Decision.** The recipient's name is ALWAYS typed by the user and NEVER transcribed. Voice briefs are optional and cover only the free-text facts. ElevenLabs Scribe v2 transcribes them, with the typed name passed as a keyterm so the transcript is forced to agree with the spelling that will actually be sung.


**Reasoning.** This is a product decision that eliminates a whole class of vendor risk. The name is the one string that must be perfect; putting it through any ASR introduces a silent failure mode nobody can detect downstream. Typing it costs the user four seconds and removes STT from the critical path entirely. Scribe then wins the remaining job on evidence rather than on marketing: it is the only global vendor that both names Uzbek and publishes a quality tier for it — 'Good', which the corrected band puts at >10% to ≤20% WER, against AssemblyAI's own self-published >50% for Uzbek and Deepgram's total absence of Uzbek from every model it ships. It is the cheapest Uzbek-capable option, it is already in the stack (one key, one invoice), and keyterm prompting is a direct lever on the core failure mode. Whisper is rejected specifically because it hallucinates fluent wrong-language text rather than failing loudly, which would poison the lyric prompt with confident false facts about the recipient.


**Fallback and switch trigger.** Azure Fast Transcription ($0.36/hr, uz-UZ Latin explicitly documented) — switch on low Scribe confidence, or permanently if Scribe's Uzbek script handling turns out to be wrong. Google Chirp 3 (uz-UZ confirmed on chirp/chirp_2/chirp_3, region-pinned) as the third leg. Longer term, if Uzbek STT ever becomes the binding constraint, community FastConformer checkpoints trained on UzbekVoice plus Common Voice report ~6.2% WER on Uzbek read speech — far better than any commercial tier, though read speech is an optimistic upper bound on spontaneous voice notes.


**Cost.** $0.22/hr batch = $0.00275 for a 45-second brief. Keyterm prompting adds a published $0.050/hr and entity detection $0.070/hr — both were listed as unknown in the research and are in fact on ElevenLabs' pricing page. Total under $0.004/kit.


**Confidence.** HIGH on the architecture (typed name), MEDIUM on the vendor. One undocumented item gates it: which script Scribe emits for Uzbek. Azure by contrast explicitly labels its locale 'Uzbek (Latin, Uzbekistan)'. Ten real briefs settle it. Note one correction to the research: Yandex SpeechKit DOES support Uzbek STT — uz-UZ (Latin script) is in Yandex's own recognition-language table, and the 'unevidenced, reject on language' verdict was an artefact of the CAPTCHA-walled docs. Yandex stays rejected on payment and jurisdiction, not on capability.


**Reversibility.** CHEAP. Confidence-based cascade behind one interface: Scribe → Azure → Google Chirp. Because the name never passes through it, an STT swap cannot damage the product's core promise.


### D7 — How is the cover art produced?

**Decision.** Deterministic template composition on our own worker — Pillow or resvg, Noto Sans/Noto Serif (SIL OFL 1.1), a pre-bought background library, and a Unicode normaliser that maps every apostrophe variant to canonical U+02BB before the name is typeset. No image model in the request path, ever.


**Reasoning.** The strongest recommendation in the document, and it overturns the obvious choice. Ideogram was shortlisted precisely because it is the market leader in AI text-in-image — and Ideogram's OWN documentation states that AI has limitations rendering non-Latin alphabets including Cyrillic, recommends English for best text rendering, and advises generating the visual and adding the text manually in a graphics editor. The leader in AI typography is telling you to composite the text yourself. Uzbek Latin makes it strictly worse: correct oʻ and gʻ require U+02BB MODIFIER LETTER TURNED COMMA, a character no image model is known to distinguish from a straight or curly apostrophe, and which most display fonts do not even contain. A generative cover that renders 'Gulnoraga' as 'GuInoraga' fails SILENTLY — undetectable without OCR-ing your own output, by which time it is in the customer's chat. Deterministic composition inverts every property: correct by construction, 50-200 ms instead of 8-20 s, no network hop, no vendor outage, no rate limit, no cold start, no SynthID provenance question, and adding a toʻy or Navruz theme becomes adding a template rather than re-prompting a model and hoping.


**Fallback and switch trigger.** Hybrid, if per-order unique art is ever demanded: Gemini 3.1 Flash Lite Image at ~$0.034 for a bespoke TEXT-FREE background, with the name composited on top in real type. Adds 3-8 s and $0.034, keeps the name guaranteed-correct. Trigger: a measured conversion or retention lift from unique art — not an aesthetic preference. Nano Banana Pro at 2K is the right model if a live generative call is ever forced, but never with the name prompted into the image.


**Cost.** $0.00 marginal. One-time background library: generate 100-200 text-free backgrounds offline via Nano Banana Pro at $0.134 each = $13-27 total, or license Unsplash+ (~$180/yr, explicit commercial licence, no attribution). Fonts are free to embed and rasterise commercially.


**Confidence.** HIGH. This is the only decision in the document where correctness is guaranteed rather than probabilistic, and the vendor's own docs argue for it.


**Reversibility.** CHEAP and one-directional — you can always add a generative background later behind the same compositor. Going the other way (retrofitting deterministic type onto a generative pipeline after customers complain about mangled names) is the expensive direction.


### D8 — How is user-supplied content moderated across three languages?

**Decision.** Three cheap layers in this order: OpenAI omni-moderation-latest (free) on name and facts separately → Azure AI Content Safety with a hand-built Uzbek/Russian blocklist (free to 5,000 records/month, name+brief batched into ONE record) → a contextual policy verdict folded into the Gemini intake call that already runs.


**Reasoning.** Two of the obvious candidates are dead on arrival: Perspective API goes out of service after 31 December 2026 with no migration support, no Uzbek, and a 1 QPS ceiling that can no longer be raised; AWS Comprehend toxicity is English-only and cannot moderate either language this product exists for. Of the survivors, Azure Content Safety is the only vendor that explicitly lists Uzbek (`uz`), Russian (`ru`) and Russian-in-Latin-script (`ru-Latn`, which matters because Telegram users type translit constantly). Microsoft is candid that Uzbek is 'supported but not specially trained' — which is exactly why the custom BLOCKLIST feature is the reason to pick it: a hand-maintained Uzbek and Russian slur list is 100% deterministic regardless of model quality. But the layer that actually solves the problem is the LLM policy judge, because off-the-shelf classifiers are trained for comment-section toxicity while this product's risk surface is different (a real politician's name in the recipient field, a 'birthday' brief that is targeted harassment, sexual content dressed as a greeting) and its false-positive surface is unusually delicate (a legitimate brief is full of age, illness recovery, family relationships and affection that naive filters over-flag). Only a written policy in a prompt can express 'flag impersonation of real public figures; do NOT flag a grandmother's age'.


**Fallback and switch trigger.** If Azure's Uzbek recall measures badly on the probe set, promote the LLM judge to first-line for Uzbek and demote Azure to blocklist-only duty. Note two operational ceilings: OpenAI's free moderation tier caps at 250 RPM / 5,000 requests per day, and Azure's free tier HARD-STOPS at 5,000 records/month with no overage accrual — usage fails rather than billing, so build the paid upgrade path before you reach it.


**Cost.** $0.00038/kit above the Azure free tier, $0.00 below it. Effectively free. Marginal LLM cost is zero because the intake call already runs.


**Confidence.** MEDIUM-HIGH. Azure's Uzbek listing is verified against Microsoft's own support table. What is unmeasured is real recall on Uzbek — nobody publishes it. Resolve by running a labelled probe set of 200 Russian and 200 Uzbek strings (slurs, threats, impersonation attempts, benign names) through both endpoints. The OpenAI endpoint is free, so this costs only labelling time.


**Reversibility.** CHEAP. Three independent layers; any one can be swapped or dropped. The blocklist is our own data and portable.


### D9 — Which payment rail, given Payme and Click are ruled out?

**Decision.** Telegram Stars (XTR), priced at 300 XTR per kit. Not a workaround — Telegram's rules make it the only permitted rail for digital goods sold inside a bot. Polar applied for on DAY ONE as rail two. Payme/Click deliberately deferred to month three, behind an IP registration.


**Reasoning.** The constraint and the policy point the same way, which is fortunate. Telegram states plainly: 'your bot or mini app must use Telegram Stars for the sale of digital goods and services inside Telegram apps, REGARDLESS OF ANY OTHER WEB PORTALS'. The credits-bought-on-a-website pattern the Russian incumbents use is not a grey area, it is the named prohibition, and the penalty per ToS §6.2 is removal from the store versions of Telegram — your bot keeps working on desktop while vanishing for every mobile user, which is your entire Uzbek market. Stars also uniquely reaches the domestic-card buyer: Uzbek resellers sell Stars for Uzcard, Humo, Click and Payme at roughly 220 UZS/Star, so you get domestic-card acceptance through Telegram's ecosystem without ever signing an Uzcard contract. No merchant contract, no acquirer, no entity, no KYB, live in hours. Polar goes in on day one specifically because its review takes up to 14 days and this product sits in its 'AI Content Generation (text, image, video, voice)' enhanced-due-diligence bucket — apply early, disclose the AI generation openly, state that lyrics are original and no real artist's voice is cloned. Polar does not serve Uzbek domestic cards; its jobs are international buyers off a landing page, an escape hatch if a Fragment payout is ever blocked, and a real invoice trail. Explicitly rejected: Stripe direct, Paddle, Creem, CloudPayments and Stripe Managed Payments (Uzbekistan not a supported seller/payout country, or a migration path leading somewhere we cannot follow); YuKassa and Robokassa (Russian tax registration is the real gate); Crypto Bot as primary (same §6.2 breach, and asking an impulse gift buyer to acquire USDT first destroys the funnel).


**Fallback and switch trigger.** Polar (Starter free tier: 5% + $0.50, +1.5% international, plus a ~1.475% payout stack — about $4.94 net on $5.90, an 83.7% take rate) for international traffic and as the Fragment escape hatch; trigger to lean on it is any Fragment withdrawal failure or KYC rejection. Gumroad as the backup if Polar's enhanced DD rejects the product — fastest onboarding of any card rail, but run one real $5.90 sale and read the settlement line, because the fee stack is reported anywhere between 10% and 13.2%. Tribute is the only shortlisted rail that reaches Russian cards, relevant only once the RU segment is sized. And the real answer: register an IP through EPIGU (real-time registration, 1-2 working days, 4% turnover tax or 0% with IT Park residency) once monthly revenue is real, then onboard Payme/Click at ~2% and recover the third of revenue currently being given away. Deferring is right for launch and wrong by month three — at 1,000 kits/month the deferral costs far more than the entity.


**Cost.** THE MOST EXPENSIVE DECISION IN THE DOCUMENT, and the client should own it consciously. At 300 XTR the buyer pays ~$5.97 in-app or ~66,000 UZS via a reseller; you are credited 300 XTR and withdraw at roughly $0.013/Star ≈ $3.90, then lose ~2% converting TON to UZS through Wallet in Telegram ≈ $3.82. Against a Payme/Click merchant discount rate of ~2% ($5.78 net), the fast path forgoes about $1.96 per kit — roughly 33% of gross revenue. At 1,000 kits/month that is $1,960/month; at 5,000, $9,800/month. Also non-trivial: a 21-day hold on every Star and a 1,000-XTR minimum before the first withdrawal, so budget at least a month of vendor bills out of pocket.


**Confidence.** HIGH on the choice, LOW on the numbers. The policy requirement, Polar's Uzbekistan payout eligibility and Polar's fee ladder are all verified against vendor pages. Every Stars economic figure is NOT — Telegram renders its rate table as an image and exposes stars_usd_sell_rate_x1000 / stars_usd_withdraw_rate_x1000 as config keys with no published values. The $0.013/Star, the 21-day hold and the 1,000-Star floor all come from secondary sources. Read the live config before setting the 300 XTR price, and re-read it quarterly.


**Reversibility.** THE EXPENSIVE ONE. Everything else in this stack is a provider behind an interface; the payment rail is tied to an entity, a jurisdiction and a cash-out path. Adding rails later is straightforward; unwinding a bad one is not. Two specific stickinesses: Stars revenue moved into the Telegram Ads cabinet CANNOT be moved back out (never park working capital there), and the cash-out lands you in crypto regulation — Uzbek residents may transact only through NAPP-licensed domestic VASPs, and NAPP demonstrated in May 2026 that licences get revoked, so verify Wallet in Telegram is currently in the registry rather than merely that it once was.


### D10 — What is the single most load-bearing piece of code, and who owns the name-correctness problem?

**Decision.** Write the Unicode normalisation and name-handling layer FIRST, before touching any vendor SDK, and treat it as the product's core rather than as plumbing. It owns apostrophe canonicalisation, script detection, Cyrillic↔Latin transliteration, name respelling for TTS, and a golden-set regression test.


**Reasoning.** No music vendor anywhere offers phoneme, IPA, SSML or lexical-stress control — not one. The only levers on a mispronounced sung name are respelling it inside the lyric string and regenerating. On the spoken side the levers are better (ElevenLabs inline IPA for Russian, near-phonemic Latin respelling for Uzbek) but they live in our code, not the vendor's. Meanwhile Uzbek Latin oʻ and gʻ arrive from a Telegram keyboard as at least five different Unicode sequences — U+02BB (correct), U+2018, U+0027, U+0060, U+00B4 — and each tokenises differently in every model, so the same person's name is several different strings to the system unless normalised on intake. Russian ё is collapsed to е by convention in training data, so no model will preserve Алёна reliably; capture the stressed form as an explicit field at intake rather than asking a model to remember it. Every viable Uzbek TTS option is Latin-only (Azure's locale is literally 'Uzbek (Latin, Uzbekistan)'; Narakeet states it outright), so Cyrillic→Latin transliteration is a hard prerequisite — and Navoiy TTS ships exactly such a normaliser under Apache-2.0, which is worth reading before writing our own. Generate Uzbek in Latin and transliterate deterministically where Cyrillic output is needed: the published transliteration models score ~0.999 character-level F1, far more reliable than any LLM's entirely unmeasured Cyrillic generation.


**Fallback and switch trigger.** None. If it is skipped, every downstream decision in this document degrades, and the failure is silent.


**Cost.** Roughly a week of engineering. Zero marginal cost. The highest-value week in the build.


**Confidence.** HIGH. This is the one part of the system where correctness is achievable deterministically and where every vendor has already told us they cannot help.


**Reversibility.** N/A — it is our own code, and it is the layer that makes every vendor swap survivable.


### D11 — Payme Merchant API as the domestic rail (supersedes D9)

**Decision.** Payme Merchant API — the standard checkout redirect, not the Subscribe/`receipts.*` API — as the domestic rail. The inbound JSON-RPC endpoint is served by a **fourth process**, `bayram-payme.service` on `127.0.0.1:8091`, reading its own `/etc/bayram/payme.env` through its own `BAYRAM_PAYME_ENV_FILE` variable; it is not a router on the admin panel and not a socket in the bot. The bot's checkout seam switches on `BAYRAM_CHECKOUT_PROVIDER` between `stub` (today's behaviour, and still the default) and `payme`. It ships **switched off**: with `BAYRAM_CHECKOUT_PROVIDER=stub` and `BAYRAM_PAYME_ENABLED=false`, production behaviour is byte-identical to the day before this landed. The specification is `PAYME_INTEGRATION` (§1 the two seams, §3 the one commit, §8 go-live); the runbook is `docs/deployment/08-payme.md`.


**Reasoning.** The trigger D9 itself named has fired: the contract with АО «PAYME» is signed. D9's fallback paragraph said the real answer was to "register an IP through EPIGU … then onboard Payme/Click at ~2% and recover the third of revenue currently being given away", and its cost line put the Stars deferral at about **$1.96 per kit — roughly 33% of gross**, $1,960/month at 1,000 kits and $9,800/month at 5,000. So this is D9's own month-three branch arriving on schedule, not a change of mind about the analysis. Two things D9 could not know are now settled and shape the build rather than the choice. First, **Telegram ToS §6.2, which D9 cited as requiring Stars for digital goods sold inside a bot regardless of any other web portal, is not satisfied by a Payme redirect rail — the exposure is removal from the store versions of Telegram, and the business has contracted with Payme accepting that risk knowingly rather than resolving it.** Second, Payme's Merchant API is **inbound**: its six methods are calls Payme makes against a server we write, and there is no create-payment-link API for the standard checkout at all, so a checkout link is base64 of a `;`-joined string and `CheckoutProvider.charge` opens no socket. That inbound endpoint is a third blast radius and earns its own container. It cannot live on the admin panel — `FORBIDDEN_ENV_VARS` (`src/bayram/admin/app.py:116-118`) is widened with the merchant key, so the panel would refuse to boot in prod once the key was in reach; `BAYRAM_ADMIN_ENABLED=false` is the documented incident kill switch and refusing operator logins is not the same incident as refusing money; the panel's `{"error":{code,message,correlationId}}` envelope is app-wide and Payme reads any non-200 as a transport fault; and `EXEMPT_PATHS` is frozen at three paths in the tests precisely to stop an unauthenticated POST being added. It cannot live in the bot either: that process holds all four outbound credentials and its own unit file says it needs "outbound HTTPS and nothing inbound". The gateway holds exactly one credential — the cashbox key, an **inbound verification** secret whose theft mints credits rather than impersonating us or spending our vendor balance. The correctness core is one commit: the transaction flip, the intent claim, the receipt and the credit grant land inside a single database transaction under the same bot-minted idempotency key every money row here already deduplicates on, with two conditional `UPDATE`s whose rowcount *is* the lock — the `claim_plan_song`/`debit_balance` primitive this repository already uses, chosen over `SELECT … FOR UPDATE` and `begin_nested()` on this repository's own recorded SQLite evidence.


**Fallback and switch trigger.** `BAYRAM_CHECKOUT_PROVIDER=stub` plus one restart restores today's behaviour exactly — the stub rail stays wired, stays constructed and stays tested, and neither new table is read by it — and any Payme transaction already in flight still settles, because the gateway is independent of the bot's provider setting. Switch back on any of: certification lapsing or being withdrawn; a Telegram enforcement notice under §6.2; or the endpoint's error rate against Payme exceeding the agreed threshold for one week. To stop new checkouts without a restart, `python -m bayram.payme.cli pause`, which never refuses an inbound `PerformTransaction` — refusing money already in flight is how an incident becomes a dispute. The named alternative rail remains **Telegram Stars via BotFather's Paycom provider token** (D9's pick): available with no registration, and not built, because it moves the ledger of record into Telegram and gives no transaction state machine, no `GetStatement` and no cabinet-side reconciliation.


**Cost.** The point of the decision: a ~2% merchant discount rate against the ~33% of gross D9 priced. Recurring engineering cost is a fourth long-running process — one systemd unit, one dotenv file, one hostname at the TLS terminator, and at most 5 more Postgres connections (`pool_size=3, max_overflow=2`, taking the fleet's ceiling from 70 to 75 against a stock `max_connections` of 100 — 70 rather than the `3 × 30 = 90` quoted at `src/bayram/db/engine.py:64-67`, because that is the figure the admin API's smaller pool exists to avoid; the arithmetic is written out in `docs/deployment/08-payme.md` §3 so the *fifth* process has to re-argue it). One thing that is deliberately **not** built and therefore not paid for: any post-perform reversal. `CancelTransaction` on a performed transaction answers `-31007` unconditionally, which is PaycomUZ's own template's default behaviour; a refund is a cabinet action plus an operator credit correction, and the reason is that `credit_accounts.balance` is a single fungible scalar with no lot structure (`src/bayram/db/plan_sql.py:15`), so an automated reversal of purchase A can debit a credit the customer paid for in purchase B (`PAYME_INTEGRATION` §6).


**Confidence.** HIGH on the protocol, which is primary-sourced and pinned to Payme's own published golden vector and its two published sandbox scenarios; MEDIUM on certification, which no amount of reading closes. **Three protocol facts are inferred, and each is an environment variable rather than a constant, so each is closed by one observation in the sandbox without a release**: the Basic-auth login (`BAYRAM_PAYME_BASIC_LOGIN`, defaulting to the literal `Paycom` that both official templates hard-code, with the `-32504` log line printing the login actually received and never the key); the code for "this order already has another active transaction" (`BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE`, defaulting to `-31008`, where Payme's own materials contradict each other); and integer `0` rather than `null` for unset times. `PAYME_INTEGRATION` §7 names the experiment that closes each. The one genuinely open question is whether Payme will certify a merchant that never reverses (§6.3) — and if the certifier insists, the answer is a business decision, not a code one.


**Reversibility.** CHEAP IN CODE, EXPENSIVE IN CONTRACT — the same asymmetry D9 named. One environment variable and one restart takes the product back to the stub, and nothing downstream of the seam has to be unwound: both new tables are additive, no existing table gained a column, and the extracted sale-writing primitives are the ones `SqlPurchaseLedger` already used. What does not reverse cheaply is the entity, the merchant contract and the settlement account behind it, and — unlike a vendor swap — the §6.2 exposure is not undone by switching the rail off later.


### D12 — Build the broadcast composer, and reverse §11.2's closed rail rather than extend it quietly

**Decision.** Build an outbound broadcast feature in the admin panel — a segment builder over `users`, a campaign composer, and a worker-driven send pipeline — specified by `BROADCAST_SPEC` (§1 the segment DSL, §2 the schema, §3 the API, §4 the send pipeline, §6 privacy). Add **Broadcasts** to the left rail, and amend `ADMIN_PANEL_PLAN` §11.2 — the rail enumeration and the per-route table — in the same change that files the spec, because `navItems.ts` is transcribed from §11.2 and says so in its own docstring ("the rail is transcribed from the plan, not extended by inference"). The panel composes and the worker sends: the admin process never holds a bot token, so D10's boundary and `FORBIDDEN_ENV_VARS` are untouched. Consent is **out of scope for this build** (`BROADCAST_SPEC` §6.3) — no consent table, no `/stop`, no opt-out; a Telegram block is the only suppression signal, checked at expansion and again at send.


**Reasoning.** This reverses a written refusal and the reversal must be stated, not inferred. Two artefacts refuse something adjacent: `admin-ui/src/components/layout/TopBar.tsx:29-32` says "There is no notifications button. The Gogo bar has one; this console has no notification feed to put behind it, and inventing an affordance that opens an empty list is exactly the 'reskin quietly became a redesign' failure this pass is not allowed to make"; and PLANIQ's shell work treats the top bar's inventory as closed. **That refusal stands and is not reversed.** It is about an *inbound* feed with no producer — an icon whose panel would be empty. This is the opposite artefact: an *outbound* action with a specified producer, three permissions, a step-up action, two audit rows per send and a spec that predates the button. What is genuinely reversed is narrower and real: §11.2's rail enumeration was closed, and ARC-4's irreducible launch minimum excludes a broadcast composer, so a `/broadcasts` item could not have been added by inference. The alternative to building it is not "no broadcasts" — it is somebody with database access running a loop against the Bot API: unpaced against NFR-23's ~30 msg/s ceiling, unaudited, unrepeatable, with no record of who authorised a message to forty thousand customers and no way to pause it once it is wrong. The panel already owns exactly that shape of problem (step-up, reason codes, an INTENT row before the act and an OUTCOME row after), so the composer is a new subject inside an existing machine rather than a new machine. Two properties make it defensible rather than merely convenient: the audience is compiled from an **allowlist** registry — no name, phone, username or free-text predicate exists at any role, so the segment cannot become an unmask oracle by binary search (`BROADCAST_SPEC` §6.1) — and the segment engine is independently valuable on `/users` before any campaign table exists, which is the shape of the first pull request.


**Fallback and switch trigger.** The segment engine alone — `BROADCAST_SPEC` §1 wired into `/users` — ships with no campaign table, no rail entry and no outbound message; drop §2–§5 and the panel is exactly what it is today plus a filter builder, with §11.2 amended back to its closed enumeration. Switch to that fallback on any of: (1) legal answers LR-42/D-4 with "no outbound message without a working revocation path" before §6.3's opt-out exists — in which case nothing sends until the consent record and the bot-side revocation ship; (2) a staged rehearsal shows the worker cannot survive a mid-flight deploy without double-sending, since §4.4's never-double-send rule is the whole safety argument; (3) NFR-23's shared budget cannot carry both the reminder fan-out (FR-97) and broadcasts, which on today's defaults it cannot. Stopping without a release needs no flag: a campaign never leaves `draft` without a step-up, and `state=paused` halts a run within about two seconds because the chunk job re-reads state every 25 messages.


**Cost.** One migration (`0024`), three tables, and one column on `purge_runs`. Three permissions, one step-up action, seven `AuditAction` members, one `SUBJECT_TYPES` entry. Three ARQ jobs plus a five-minute cron, the first **outbound** rate limiter this codebase has ever had, and a second `ArqRedis` pool on the admin container (separate from the panel's `decode_responses=True` client, which would corrupt arq's pickled payloads if shared). Roughly fifteen new frontend files in `admin-dashboard`, which has no test runner today — adding vitest is part of the price, not an optional extra, for a feature that can message every customer. Recurring: `broadcast_recipients` at one row per (campaign, account), bounded at 400 days by a cutoff rather than a legal clock, and a second consumer competing for the worker's fifteen slots — bounded by 200-message chunks so a customer's render never waits behind a campaign.


**Confidence.** HIGH on the mechanism, which is assembled from primitives this repository already runs: the conditional-`UPDATE`-rowcount claim from `db/churn.py`, `insert_or_ignore` idempotency from the activity snapshots, the Redis fixed-window counter from the inbound rate limiter, and the step-up/audit pair from the existing destructive actions. HIGH on the privacy position, which is a refusal list a reviewer sees in the diff and a test asserts. LOW on the legal position for anything marketing-shaped: D-4's lawful basis is unresolved, LR-54's in-bot notice does not exist, and §6.3 ships with no opt-out at all — so a `marketing` campaign is a decision a human takes knowingly, not one the system has cleared. MEDIUM on operations: nobody has watched a 70-minute campaign survive a deploy on `aizu`, and SSH to that host is not available to the sessions writing this.


**Reversibility.** CHEAP IN CODE, NOT REVERSIBLE IN THE CUSTOMER'S INBOX. Every table is additive, no existing table changes shape except one counter column on `purge_runs`, and removing the routers, the rail entry and the jobs restores today's panel exactly — the segment engine can stay behind on `/users` on its own merits. What does not reverse is a message that went out: there is no unsend, and with no opt-out in this build (§6.3) the first campaign that annoys people cannot be un-annoyed by a config flag. That asymmetry is the reason the send is behind a step-up, a typed audience-size confirmation, a drift check against the number the operator actually saw, and two audit rows rather than one.



### D13 — Hold an OpenRouter management key, and reverse the balance poller's own written refusal

**Decision.** Add a **fifth** outbound vendor credential, `BAYRAM_OPENROUTER_MANAGEMENT_KEY`, held only so the hourly balance poll can call `GET /api/v1/credits` and read the account's prepaid pool. It is **optional** — unset, every process starts and the poller reports exactly what it reported before — and it is in `bayram.config.VENDOR_SECRET_FIELDS` but **not** in `REQUIRED_VENDOR_SECRET_FIELDS`, so the admin panel refuses to boot in production holding it while the bot, the worker and the gateway all start without it. Only `bayram.runtime.vendor_balance_job` reads it; no inference path touches it. The credits call is made **only when `GET /api/v1/key` reported no cap**, it is handed to the **primary** OpenRouter target alone, and every way it can fail — refused, unreachable, unreadable, renamed, zero — degrades to the `/key` reading rather than to a failed probe.

**Reasoning.** This reverses a refusal that named its own reversal condition, which is why it is filed here rather than landing as a diff. `bayram/runtime/vendor_balance_probes.py`'s module docstring called `/api/v1/credits` "the security decision of the whole workstream" and refused it: the endpoint is documented "Management key required", a management key can create and revoke API keys and read the account, and holding one buys "a credential whose compromise costs more than the spend it reports". It closed with the condition — *"if the prepaid figure is later judged worth a fifth secret, that is a separate decision with its own review; it must not arrive as an implementation detail of a dashboard tile."* The judgement has now been made, and the trigger is a real gap rather than a nicety: the admin panel's global header draws each vendor's balance as a **ring — remaining as a fraction of the pool** — and `/key` on an uncapped inference key answers `limit: null`. There is no denominator to draw against, and the alternatives were worse. A configured `BAYRAM_OPENROUTER_BUDGET_USD` would ring a real spend against a number we invented, which is the class of confident-looking fiction `vendor_usage`'s nullable columns exist to prevent. Soft-probing `/credits` with the inference key would leave the ring present or absent depending on an undocumented vendor behaviour, which is a worse property than either holding the key or not. ElevenLabs needs none of this — its subscription body carries `character_limit` and `character_count`, so its ring has always been computable — so the whole reversal buys exactly one vendor's denominator, and that is the honest size of it.

**Fallback and switch trigger.** Blank the variable and restart the worker: the poller drops back to the `/key` reading, `is_unbounded` returns to `true`, the panel draws its dashed "uncapped" ring, and no other behaviour anywhere changes. That is the fallback, and it needs no code path that does not already exist, because the un-keyed branch is the one every other deployment runs. Switch back on any of: (1) the management key appearing in a process that should not hold it — the admin panel's boot refusal is the detector, and it firing at all means the deployment layout drifted; (2) OpenRouter tightening what a management key can do such that this one starts failing the poll rather than silently degrading; (3) any key-revocation incident traced to this credential, in which case the ring is not worth re-earning. Note the asymmetry the fallback cannot undo: a leaked management key is a rotation of every OpenRouter key on the account, not a bill.

**Cost.** One optional settings field, one path constant, one payload model and one merge helper in the probe module; one field on the poller's `_Target`; a **second HTTP request per hour**, and only for an uncapped primary key. One widened regex in `tests/test_admin/test_settings_and_boot.py` — the shape test that is supposed to catch an unlisted credential matched `api_key` and not a bare `key`, so the sharpest credential in the tree would not have been swept up by the very test written to notice it. No migration, no schema change, no new API field: `vendor_balances.balance_total` and `balance_used` have been on the row and on `VendorBalanceView` since `0019`, unpopulated for OpenRouter and now filled.

**Confidence.** HIGH on the mechanism and its fences, which are asserted rather than described: the credits call is skipped for a capped key, carries the management credential and never the inference one, and eight failure shapes are driven through a `MockTransport` to prove each leaves the `/key` reading untouched. MEDIUM on the operational posture, for the reason D12 records about `aizu` — nobody has watched this key live on the production host, and the split that keeps it away from the panel is enforced at boot rather than by the deployment tooling. The residual risk is not technical: it is that a fifth secret exists at all, on a host whose other four already justify their own process boundaries.

**Reversibility.** CHEAP IN CODE, NOT REVERSIBLE IN THE CREDENTIAL. Removing the field restores the previous module exactly; a key that has been created, deployed and read cannot be un-created, only rotated. Treat the decision as reversible and the secret as not.

### D14 — The panel may find and may nudge; it may not mint

**Decision.** The admin console gets a **Billing / Rail Board** section over the Payme rail — twelve read routes, and exactly **three** writes: `pause`, `resume`, and *re-enqueue the confirmation message for one intent*. **Force-settle does not ship**, and neither do cancel, refund, expire, release, hold, claim, or a "run reconcile" button. The specification is `BILLING_RAIL_BOARD` (§1 what the section is and is not, §3 the twelve routes, §4 the dossier, §5 the settlement identity, §6 privacy, §9 the refusal index). The dossier renders the force-settle invocation as **selectable text with a copy control and no submit path**, beside the receipt's cabinet reference, so the out-of-band check the command depends on is in front of the operator at the moment they need it (`BILLING_RAIL_BOARD` §4.4).

**Reasoning.** The line is "may find, may nudge, may not mint", and it falls where it does for five reasons, of which the fifth is sufficient on its own.

*One — the panel is structurally forbidden the evidence.* `src/bayram/admin/app.py::derive_forbidden_env_vars` refuses to boot in prod if `BAYRAM_PAYME_MERCHANT_KEY` is reachable, which is the mechanism that keeps the merchant endpoint a fourth process (D11). So the panel can display every fact about a payment *except* the one that authorises the press: a charge in the Payme merchant cabinet. A button whose precondition the screen cannot show is a button pressed on faith.

*Two — the action is unmintable in reverse.* Force-settle writes a `credit_ledger` GRANT against a `credit_accounts.balance` that is a single fungible scalar with no lot structure (`src/bayram/db/plan_sql.py:15`). Nothing anywhere in this system can un-mint it. That is the same reason `CancelTransaction` on a performed transaction answers `-31007` unconditionally (`PAYME_INTEGRATION` §6.1) — and a refusal we enforce against Payme should not be one click away for ourselves.

*Three — there is already an honest front door.* "The customer paid and got nothing" has a route: `POST /api/users/{id}/credits/grant`, which records a **human decision as a human decision**, with a step-up, a reason code and an audit row. Force-settle instead rewrites the money history to assert that a sale occurred. The first is a correction; the second is a claim.

*Four — `operatorSettlements` is a named term in the reconciliation identity precisely so hand-settlements are not mistaken for defects* (`BILLING_RAIL_BOARD` §5). Making the recovery button one click makes the number that *explains* mismatches into the number that *hides* them.

*Five, and decisive on its own — force-settle is the one transition in the entire state machine that deliberately drops the mutex.* Every other move is a conditional `UPDATE` whose rowcount **is** the lock: `hold_intent` matches on `state='pending'`, `claim_intent` and `release_intent` both match on `active_transaction_id=:txn`. `claim_intent_for_operator` matches `pending OR awaiting` and **names no holder**, by explicit argued decision, because an operator reading Payme's cabinet has no transaction id of ours to match on. An action whose defining property is that it bypasses the concurrency guard should not be one click from a browser tab that polls every fifteen seconds. The terminal is the correct blast door, and typing a public ref by hand is a rate limit that costs nothing to maintain.

The three writes that *do* ship pass the same test in the other direction. **Pause and resume stop the bot quoting new checkouts**: no money moves, no personal data is disclosed, no credit is minted, no message is sent, and the next operator undoes it in one click. **Notify sends a message the customer was already owed**, writes no money row and no state a customer can spend, and its idempotency is structural rather than promised — `payme_notify_job_id(public_ref)` is deterministic so ARQ collapses a double press, and `mark_intent_notified` stamps only `WHERE notified_at IS NULL`, so the enqueue and the sweep's backstop cannot both message one person.

**Pause carries no step-up, and this is the part most likely to be "tightened" by a later reviewer.** Four reasons. (a) `bayram/payme/pause.py`'s own docstring declares the switch **"not a security control … must never be documented, tested or relied upon as one"** — putting the panel's heaviest gate on a control the owning module has disclaimed is an inconsistency that module would contradict on sight. (b) The blast radius is not in the step-up class: compare `REVEAL` (discloses a person), `USER_BLOCK` (denies service to a person), `CREDIT_GRANT` (mints money), `BROADCAST_SEND` (messages forty thousand people). Pause belongs with `ORDER_RETRY`, which carries none. (c) The moment you need it is the moment you cannot afford it — pause is an incident brake, and `pause.py` already made exactly this availability-over-strictness trade on the read path. (d) It is one hazard away from a dead route: `check_role` holds no subject and therefore no grant, so any `Permission` appearing in `STEP_UP_ACTIONS` answers `STEP_UP_REQUIRED` at the router **for ever, at OWNER, while looking exactly correct**. `Permission.RAIL_CONTROL` is therefore a plain `W` cell, with a comment in `RBAC_MATRIX` and an explicit assertion in `tests/test_admin/test_rbac_matrix.py` saying so. What pause gets instead: a mandatory `reasonCode`, a confirm dialog, OWNER and ADMIN only, one audit row per press, and a response that **re-reads** the Redis key rather than echoing the request.

`PAYMENT_NOTIFY` is a separate permission including SUPPORT, rather than a ride on `RAIL_CONTROL`, because SUPPORT is who takes the "I paid and nothing happened" call — and handing a support agent the switch that stops the business selling in order to give them the button that re-sends a receipt is a trade nobody would make if it were written down.

**Fallback and switch trigger.** If operators are force-settling weekly and the SSH round trip is measurably costing customers songs, the route to reconsider is **not** a plain `W` route added quietly. It is: a read-only pre-flight that shows the cabinet evidence, plus a `W+S` cell **split** into `PAYMENT_SETTLE_WRITE` (declared at the router) and `PAYMENT_SETTLE` (consumed in the handler via `enforce_step_up`) — never the single `W+S` member, which ships a route nobody can reach. And never before the panel can display evidence of the cabinet charge, because reason one above does not weaken with volume. **Trigger:** three force-settles in one calendar month, **or** one incident in which the terminal was unreachable while a customer was waiting. The same split is the remedy if a reviewer later decides pause deserves a step-up (`RAIL_CONTROL_WRITE` + `RAIL_CONTROL`); adding the existing member to `STEP_UP_ACTIONS` is the move that must not be made.

**Cost.** Three `db/admin` query modules (one per table, per the package's own rule), one migration adding the two settlement-clock indexes that do not exist today — `payment_intents.settled_at` and `payme_transactions.perform_time` are the filter columns of `settlement_counts` and of the operator-settlement count, and the board polls. Four routers, two `Permission` members, three `AuditAction` members, one `SUBJECT_TYPES` member (`payment`), and a **fourth method on `AdminQueue`**, whose docstring had closed its surface at three — a deliberate widening, argued in place, whose rejected alternative was enqueuing ARQ from the handler and thereby breaking the seam that lets every admin test run without a Redis. One ~50-line `rail_switch` seam, which exists only because `set_paused` raises and handlers in this package never write `try`/`except`. Roughly twenty frontend files. Recurring: nothing — no new table, no new row per anything, no new outbound call, and no second revenue figure to reconcile.

**Confidence.** HIGH on the boundary, which is a refusal list a reviewer sees in the diff and tests assert. HIGH on the read layer, which is assembled from shapes this repository already runs — correlated `EXISTS` subqueries rather than a `LEFT JOIN` that would fan the money columns out per transaction, keyset paging, window-ignoring ROW probes beside every count. MEDIUM on the operator posture, for a reason worth naming: **nobody has used this screen against real data, because no real data exists** (`BILLING_RAIL_BOARD` §8). Every judgement about what an operator needs on the dossier is inherited from `cli._render_dossier`, which is the only version of this that has ever been used in anger, and the first week of real payments should be read as a review of these choices rather than as a confirmation of them.

**Reversibility.** CHEAP. Every route is additive and every table is read-only except the Redis key, which the CLI has always written. Removing the four routers, the two permissions and the nav entry restores today's panel exactly; the query modules can stay on their own merits, and the two indexes are worth keeping regardless. What does not reverse is the widened `AdminQueue` surface — once a fourth method exists, the sentence that closed it at three no longer holds, and the next widening has one fewer argument against it. That is the honest price of the notify button.

### D15 — The console is `admin-dashboard`; `admin-ui` is not where features land

**Decision.** The Billing Rail Board — and every feature after it — is built in **`admin-dashboard/`**. `admin-ui/` is legacy and receives no new sections. This overrides the `admin-ui/src/features/billing/` path named in the task that commissioned D14.

**Reasoning.** There are two React SPAs in this repository and **both build to the same `src/bayram/admin/static/`**, so whichever was built last wins and a feature built in the wrong one is a feature the deployed console does not have. Four pieces of evidence, all checkable in this tree: `Makefile:30` sets `UI := admin-dashboard` and `LEGACY_UI := admin-ui`, and `make ui-build` — the target that produces the bundle `app.py::_mount_spa` serves — runs `cd $(UI) && npm run build`; `admin-dashboard/vite.config.ts:20` sets `outDir: "../src/bayram/admin/static"`; the bundle sitting in `src/bayram/admin/static/index.html` right now carries a favicon link that only `admin-dashboard`'s shell emits, identifying the deployed artefact; and `admin-ui/package.json` describes itself as *"[DEPRECATED in favor of admin-dashboard] The legacy Gogo admin console SPA."*

Three further findings settle it rather than merely permitting it. `admin-dashboard` already exports `money(minorUnits, currency)` over a `MINOR_EXPONENT` table with UZS rendered as whole soʻm, and that module's docstring explicitly warns against a second copy — Payme amounts are tiyin, so building in `admin-ui`, which has no currency formatter at all beyond two hard-coded-`$` USD helpers, would have created exactly the duplicate table it warns about, across a package boundary no test can compare. `admin-dashboard/src/api/audit.ts` parses `action` as `z.string()`, using its action tuple only to populate a filter picker; `admin-ui`'s `auditEntryViewSchema` uses a **closed `z.enum`**, so the first real `rail.paused` row would have turned that SPA's entire `/audit` screen into a SCHEMA_DRIFT banner. And `admin-dashboard` already has every primitive the section needs — `DataTable`, `CursorPager`, `FilterChips`, `EmptyState`, `ConfirmDialog`, `StepUpDialog`, `MaskedValue`, the `adminQuery` presets, the `rbac` mirror.

The cost of the other choice is what makes this a decision rather than a preference: building in `admin-ui` would require flipping `UI := admin-ui`, which **un-deploys** the broadcasts, i18n and finance-dashboard work that is the newest shipped code on this branch.

**Fallback and switch trigger.** `admin-ui`, conditional on flipping `UI := admin-ui` **in the same change** — the flip is the fallback, not an afterthought to it, because a section built there without it is invisible. The port then costs three specific things and they should be priced before anybody agrees to it: a new `admin-ui/src/lib/money.ts` carrying `MINOR_EXPONENT` with a comment naming its origin and a UZS test; three members added to `api/enums.ts::AUDIT_ACTION_VALUES` **in the same commit as the handlers**, or the first audited press breaks the audit screen; and `components/layout/NavRail.test.tsx`'s pinned placeholder count dropping from three to two as the "Payments — phase 3" item becomes a real route. **Trigger:** a decision to restore the six screens `admin-dashboard` does not have — orders, assets, vendors, config, retention, live — by reviving `admin-ui` rather than porting them into `admin-dashboard`.

**Cost.** None beyond the section itself. `admin-dashboard`'s gates are the per-package scripts — `npm run typecheck`, `npm run lint`, `npm run test:unit` (vitest) and `npm test` (the tsx localization key-parity suite, which asserts 100% parity across `en`/`ru`/`uz` and is what makes a key added to one locale a build failure). Until 2026-09-10 `make ui-check` could not be read as a green signal for this package: it ended in `npm run tokens:check`, a script `admin-dashboard` does not declare, so the target failed on a green tree — and because that line came last it never reached `test:unit`, leaving the component suite guarded by no target at all. `ui-check` now runs exactly the four scripts above, and `tokens:check` moved to `make legacy-ui-check`, beside the `admin-ui` stylesheet and annotator it measures. **`make ui-e2e` / `make ui-e2e-install` are still `admin-ui` recipes pointed at a package with no matching scripts, and were deliberately left that way**: re-pointing them would run the legacy console's specs — one of which asserts on `admin-ui`'s own font pipeline — against the deployed console's bundle. The CSP and the SPA nonce are therefore guarded by nothing until `e2e/csp.ts` and `e2e/smoke.spec.ts` are ported into `admin-dashboard/`, which is a change of its own.

**Confidence.** HIGH. Every claim above is a file and a line in this working tree, and the deployed-artefact claim is a byte in a built file.

**Reversibility.** CHEAP IN CODE, EXPENSIVE IN ATTENTION. One line of the `Makefile` and one rebuild swaps which SPA is served. What does not reverse cheaply is the split itself: two consoles sharing an API contract and an output directory is a standing hazard, and this decision narrows it by declaring one of them closed rather than resolving it. Deleting `admin-ui` is the resolution and is a separate change.

### D16 — ElevenLabs "songs of cover" is divided by the vendor's own credit burn, not by our character counts

**Decision.** `measure_per_song_rate` measures ElevenLabs as **`balance_used` for the current quota period ÷ delivered songs in that period that drew on the pool**, under a new basis `quota_period_credit_burn`. The previous divisor — trailing `billed_characters` per delivered song, basis `trailing_tts_characters` — is no longer produced by any poll. The member stays in `BalanceEstimateBasis` because rows written under it are still readable.

**Reasoning.** The old divisor never once produced a number on this deployment, and could not have. `billed_characters` has exactly one writer, `providers/tts/elevenlabs.py` on the `speech_synthesis` leg, and the pipeline's ElevenLabs traffic is `music_compose` and `transcription` — `select distinct operation from vendor_usage` returns `health`, `transcription`, `music_compose`, `chat_completion` and no speech. So `SUM(billed_characters)` was `NULL` on every poll, the divisor was `None`, all three estimate columns stayed null together under `ck_vendor_balances_estimate_carries_its_basis`, and the balance meter read `unmeasured · no per-song rate` permanently while the account held 98 538 credits. A basis that cannot be measured on the traffic the system actually sends is not a conservative estimate; it is an empty tile with a rationale.

The replacement needs no rate card, which is what makes it a measurement rather than a second `usd_per_minute`. `balance_used` is the subscription's own count of credits consumed since the last reset, so it already covers every leg drawing on the pool — the music render that writes only `audio_ms`, transcription, and TTS if it is ever added — and nothing here converts a duration into a credit. The denominator is deliberately narrower than "delivered songs": it counts delivered orders created in the period with at least one non-fake ElevenLabs call attributed to them, because a song ElevenLabs never rendered in a divisor against ElevenLabs' own burn would shrink the rate and inflate the cover.

Both halves take the vendor's window and not the operator's, which is why `vendor_balance_estimate_window_days` does not reach this path: `balance_used` covers the quota period, and pairing it with a denominator over a shorter window would divide a full period's burn by part of a period's songs. The period start is the reported reset walked back 30 days, since the subscription reports when the next reset lands and never when this one opened.

Against the live local row — 24 188 credits burned, 98 538 remaining, two delivered songs — this yields 12 094 credits/song and **8 songs of cover, critical**, where the meter previously showed nothing at all.

**Fallback and switch trigger.** A configured credits-per-minute rate card multiplied by `audio_ms` per delivered song, on a `trailing_audio_credits` basis. It isolates the music leg and is deterministic, at the cost of a constant somebody must look up and keep current and of blindness to transcription's draw on the same pool. **Trigger:** ElevenLabs stops reporting `character_count` on the subscription endpoint, or the burn figure is found to include enough non-song credit (console experiments, failed renders billed anyway) that the lower bound reads as alarmist rather than safe.

**Cost.** None in schema. Migration 0019 stored `estimate_basis` as `VARCHAR(32)` with `create_constraint` off precisely so a later member costs no migration, and the check constraint enumerates no values — it only binds the three estimate columns to move together. The SPA gained a third member in `BALANCE_ESTIMATE_BASIS_VALUES`, a caption, and a bound direction: the meter now prints `≥` on this basis, `≤` on `trailing_tts_characters`, and no inequality on `trailing_spend_usd`, whose error has no known sign.

**Confidence.** HIGH on the defect — the absent `speech_synthesis` traffic is a query against the live table, not an inference. MEDIUM on the divisor's accuracy, and the direction of the doubt is stated in the enum member's own docstring: burn that bought no delivered song inflates the divisor, so the figure under-promises cover. That is the safe direction for a number whose only job is to say when to top up.

**Reversibility.** CHEAP. One branch in `measure_per_song_rate`; the old basis member, its column values and the SPA's handling of them were all left in place.

### D17 — Paying starts the render, on a redirect rail only

**Decision.** When a Payme payment settles, the worker starts the song the customer was paying for, instead of announcing the payment and leaving them a button. The bot records the render's deterministic order id on the payment intent at the moment it builds the checkout link (`payment_intents.resume_order_id`, migration 0026); the settlement job re-reads the customer's parked draft, re-derives that id and compares, claims `payment_intents.resumed_at` with a conditional `UPDATE`, posts the progress frame, submits, and parks the session — in that order. `bayram/runtime/render_resume.py` is the whole of it. **This reverses, for redirect rails only, the "paying does NOT queue a render" paragraph in `bayram/bot/handlers/checkout.py`'s module docstring**, which was amended rather than deleted: its other half — the rejection of folding the purchase into `handle_confirm` — still stands and is the reason the resume lives in another module in another process.

**Reasoning.** On an inline rail "pay, then press 🎬" is two taps in one sitting, and the decision was right. On a redirect rail the customer leaves Telegram for a payment page and settlement arrives minutes or hours later at a different process, so the second tap is being asked of somebody who has put their phone away — and a customer who paid 15 000 soʻm and closed the app came back to a song that had never started. That was reported as a bug, and it is one.

The render's identity is the UUID5 `order_id_for` already takes over the draft, and choosing it rather than inventing a marker is what makes the design short. One value is simultaneously the `orders` primary key, the seed of the ARQ job id, and the proof the draft has not moved — the fingerprint covers every field including the approved lyric and `session_id`, so a customer who edits anything after paying is declined by a single equality rather than by a checklist. A racing 🎬 press computes the same value, so the primary key, the job id and `credits.charge`'s already-paid probe all collide on it: two attempts, one song.

**Claim before act is the ordering, and its cost is stated rather than hidden.** `notify_payment_settled` is at-least-once by construction, so a side effect placed in it with no latch of its own fires once per attempt — and this one bills a vendor and delivers a song. A process that dies between the claim and the enqueue therefore renders nothing, permanently, with no automated recovery. That customer is left exactly where this product left every customer yesterday, which is why it is the right direction to fail in.

**Fallback and switch trigger.** `BAYRAM_AUTO_RENDER_ON_PAYMENT=false` restores the previous behaviour exactly — announce, and let the customer press 🎬 — with a restart and no deploy and no migration. **Trigger:** any evidence of a double render, or of a song rendered from a draft the customer had edited.

**Alternatives rejected.** *Synthesising a Telegram update and letting `handle_confirm` run* — rejected decisively on aiogram's event-isolation lock being per-dispatcher and in-process, so a second dispatcher in the worker would hold a different lock over the same Redis FSM key and a real tap and a synthesised one could both proceed; the full four-point argument is in `render_resume`'s module docstring. *A ticket in FSM data instead of two columns* — cheaper (no migration, no port change, no privacy amendment) and rejected on two grounds only: a durable transactional latch, and an auditable answer to "which render did this payment expect, and did anything start it?". That is a judgement call and is recorded as one. *Minting a marker on the `/balance` surface* — rejected because there is no draft there to fingerprint, and attaching the money to whichever run happens to be parked would put the purchase's idempotency scope and its render marker on two different runs. That population is served instead by the settlement's keyboard, which is chosen from the session rather than from the marker.

**Cost.** Two nullable columns, no index, no backfill. One method on the WIDE `PaymeLedger` port only — the bot still holds `PaymentIntentOpener` and still cannot settle, cancel or claim. The gateway process is untouched and still holds no Telegram token.

**A live defect fixed alongside it, and worth naming because it was independent of all the above.** The settlement message carried `start_over_keyboard`, whose ↩️ reaches `reset_to_welcome` — "a clean slate, every time". The only prominent button under a paid receipt destroyed the draft it had been paid for. `paid_late_keyboard` replaces it wherever a usable draft is parked, and the rollback lever above would otherwise have shipped customers straight onto the old button.

**Confidence.** HIGH on the defect and on the idempotency argument — five independent mechanisms, four of them keyed on one value. MEDIUM on the FSM writes: the worker has no per-chat lock and uses compare-and-write, which is the same discipline `jobs._release_session` has used since it shipped and carries the same narrow, real race. It cannot be closed without moving the work back into the bot process.

**Reversibility.** CHEAP behaviourally (one environment variable), MEDIUM structurally (the columns and the port method would need a migration to remove).

**Known weaknesses.** (1) No per-chat lock, as above. (2) A crash between claim and enqueue renders nothing, with no automated recovery — a `payme` CLI arm or a sweep over `settled_at IS NOT NULL AND resume_order_id IS NOT NULL AND resumed_at IS NULL` would close it and is deliberately not in this cut. (3) The in-flight order cap is 1, so an auto-render takes the account's only slot for the run and a Confirm press during it is refused; acceptable only because the render is for the draft the customer was looking at. (4) `WIZARD_STATE_TTL` (14 d) has no boot check of its own — `main.refuse_an_unsafe_checkout_rail` refuses `payme_intent_ttl_s >= WIZARD_STATE_TTL`, but shortening the module constant would silently stop auto-renders with nothing going red.


### D18 — The ⚠️ button becomes a ticket queue, the support group is a first-class staff surface, and the body is kept indefinitely

**Decision.** Build a support-ticket queue behind the post-delivery "⚠️ Something is wrong" button and behind `/support`, specified by `SUPPORT_TICKETS_SPEC` (§1 the customer flow, §2 the schema, §3 the group card and the two-way reply, §4 the board, §5 the API, §7 privacy). Three parts, each of which is a decision on its own. **(a) A queue, not a forwarded message**: a row with a `public_ref` the customer can quote, an append-only timeline beside it, and migration `0027`. **(b) Four Kanban states and exactly four** — `new → in_progress → waiting → resolved`, where `waiting` means waiting on the CUSTOMER and `resolved` is terminal but reopens to `in_progress` when the customer replies; no `triaged`, no `closed` archive. **(c) The Telegram support group is a first-class staff surface with full two-way reply**: the card carries `✋ Claim`, `✅ Resolve` and `🔗 Open in panel`, and a staffer who *replies to the card* has their reply relayed to the customer in the customer's own language, with the reply counting as the claim. Operators can equally work from the panel. Add **Support** to the left rail and amend `ADMIN_PANEL_PLAN` §11.2 — the rail enumeration and the per-route table — in the same change that files the spec, because `navItems.ts` is transcribed from §11.2 and says so in its own docstring; **D12** set that precedent when Broadcasts landed and this follows it exactly. And **(d) the ticket body is kept indefinitely** rather than put on a retention clock: no `*_expires_at` column, no cutoff, no sweep, erasure through `/forget` alone, with a written exemption paragraph in `tests/test_db/test_privacy_constraints.py` naming both tables, revision `0027` and the route.

**Reasoning.** The ⚠️ button has, since it shipped, rendered a sentence and written nothing. A customer who pressed it was told where to write; whatever they wrote landed in a chat nobody owned. There was no row, so there was no reference to quote back, no queue to work, no way to answer "how many people told us the name was wrong last month?" and no way for two staff to avoid answering the same person twice. That is not a missing feature, it is a promise the product already makes and does not keep — and this product's single named risk is getting somebody's name wrong, which means the complaint channel is where the evidence for D10's whole name-correctness workstream was supposed to accumulate and never did.

**Why the group is a surface and not a notification.** The alternative shape — post a read-only card and make staff open the panel to answer — was rejected on the honest observation that they will not. The people triaging a complaint at nine in the evening are in Telegram already, on a phone, and a workflow whose first step is "log into the admin console" is a workflow that degrades into answering the customer from a personal account with no record at all. That is the status quo, and it is worse than a group reply in every respect: no ticket, no timeline, no relayed language, no `relayed_at`. Making the group a real surface is choosing the place the work actually happens and putting a record under it. The cost is stated in §9 Q2 and Q7 rather than hidden: a customer's own words are cached on every phone in that room, and every person in the room can speak to a customer in the product's voice with no review step. That is why the group leg ships **off** by default (`support_group_chat_id = 0`) and why the ticket, the board and the answer all work without it.

**Why four states.** `waiting` earns its column because a queue in which "we asked them a question three days ago" and "nobody has looked at this yet" share one state is a queue whose length means nothing — the operator cannot tell which half is their backlog. A `triaged` step was rejected because the act that would set it, a staffer reading the card, is the same act that claims the ticket, so the two would always move together and one would be noise. A `closed` archive was rejected because `resolved` is already terminal and a fifth column nobody drags to is a column that silently collects tickets; a ticket leaves the board by ageing out of the default filter. Starting narrow is cheap by construction: `enum_type` renders a `VARCHAR(32)` with `create_constraint` off, so a fifth state later is a code change and not DDL.

**Why the body is kept for ever, which is the part most likely to be challenged.** Every other table in this schema that holds something about a person is either on a clock or anonymised on request, and this one is neither. Two reasons. First, volume is not the problem: this is `topup_purchases`' footing, a few complaints a week against `broadcast_recipients`' one row per account per campaign — the table that actually needed a 400-day cutoff. Second, and decisively, **a support history that deleted itself on a schedule would delete the evidence in the one dispute it was kept for**: "you told us in March the name was wrong and said you would fix it" is answerable only if March is still there, and a cutoff makes that answer disappear at precisely the moment a customer produces a screenshot. The erasure route is therefore `/forget`, and it is DELETION rather than anonymisation — the departure from `credit_ledger`, `plan_purchases`, `bot_membership_events` and `broadcast_recipients`, all of which are anonymised because an aggregate has to survive the person. A complaint with the id nulled is not a statistic; it is somebody's sentence with the name filed off. So `support_tickets.telegram_user_id` is NOT NULL, `support_ticket_events.ticket_id` cascades, and one statement erases both.

**Fallback and switch trigger.** The ticket queue **without the group leg** — `BAYRAM_SUPPORT_GROUP_CHAT_ID=0`, which is the shipped default — is a complete, useful product: the row is written, the customer gets a reference and an answer, and the board works. Falling back is a restart, not a deploy and not a migration. Switch to it on any of: (1) Q2 or Q7 being answered badly — the group's membership cannot be governed, or not everyone in it should be speaking to customers unreviewed; (2) the group ceiling of ~20 messages/minute producing a `retry_after` on the bot token in a real incident, because that stops customer ORDERS and not merely cards (`SUPPORT_TICKETS_SPEC` §3.4 paces group posts on their own key precisely to prevent this, and evidence that it does not is the trigger); (3) any relay reaching the wrong customer, which would mean the `group_message_id` uniqueness argument is wrong. For the retention half the trigger is different in kind: **if legal names a retention period (§9 Q3), the exemption paragraph is rewritten rather than deleted** and the period arrives as a cutoff, a `PurgeReport` field and a `purge_runs` column — the suffix `*_expires_at` is what obliges all three, which is why no column carries it today.

**Alternatives rejected.** *Forwarding the customer's message into the group with no row* — the status quo with a nicer wrapper; it cannot be searched, counted, assigned or erased, and there is nothing to quote back. *An FSM state for the description* — rejected outright: `navigation`'s handlers are deliberately not state-filtered, ⚠️ is reachable from a month-old delivery message, and `set_state` would destroy a wizard draft the customer is halfway through. The flow is DB-backed and FSM-free, matching on `reply_to_message.message_id` against a stored `prompt_message_id`, which adds no FSM key and swallows no wizard input. *Adding a field to `NavCB`* — rejected because it changes the wire format of every nav button already sitting in customers' chat histories; a new `SupportCB(prefix="sup")` is 41 of the 64 available bytes. *Persisting the body through `ChatRecorder`* — rejected because `offer()` is explicitly lossy and `flush_batch` swallows every exception, and a silently dropped complaint is worse than no ⚠️ button at all. *A step-up on `support.write`* — rejected because replying to customers is a support operator's entire job and gating it would leave the role unable to do the thing it is named for; the audit row and the append-only event log carry the accountability, as `broadcast.write`'s own note argues.

**Cost.** One migration (`0027`), two tables, no column on `purge_runs` and no sweep. Four `StrEnum`s in `contracts.py`, two permissions with no step-up, four `AuditAction` members and one `SUBJECT_TYPES` entry. One new bot router pair with a chat-id filter, one shared card module, one pacer key, two ARQ jobs (`support:card_sync`, `support:relay`) on D12's existing admin→ARQ seam, and three settings. On the frontend: a ninth rail item, a `support` i18n namespace in three locales, an entry in the closed `REQUIRED_NAMESPACES` list, and a Kanban board hand-rolled on the native HTML5 drag-and-drop API — no dependency is added, and the keyboard path is part of the price rather than a follow-up, because native DnD is invisible to a keyboard and a screen reader. Recurring: a few rows a week, kept for ever, and a room of staff phones holding customer complaints.

**Confidence.** HIGH on the mechanism, which is assembled from primitives this repository already runs: the conditional-`UPDATE`-rowcount latch from `payment_intents.resumed_at` (revision `0026`), the composite keyset index from `ix_orders_state_created_at`, the denormalised actor from `admin_audit_log`, the enqueue-never-send seam from D12, and `ON DELETE SET NULL` from `generation_attempts.order_id`. HIGH on the four-state argument, which is a product decision with a stated rejection for each state not taken. MEDIUM on the retention position: the operational argument is strong and the legal one is unmade (§9 Q3). MEDIUM on operations, for D12's reason — nobody has watched the group leg under the burst a vendor outage produces, and the ~20/minute ceiling on a single group is the tightest limit this product touches.

**Reversibility.** CHEAP IN CODE, CHEAP IN THE GROUP, NOT REVERSIBLE IN WHAT WAS SAID. Both tables are additive, nothing existing changes shape, and removing the routers, the rail entry, the jobs and the bot handlers restores today's product exactly — the ⚠️ button returns to rendering a sentence. Turning the group leg off is one environment variable and a restart. What does not reverse is a relayed reply: there is no unsend, and a staffer's message has reached the customer before any operator sees it. That asymmetry is why the relay writes its event *before* the send and stamps `relayed_at` *after*, so an answer nobody received is distinguishable from one that landed.

**Known weaknesses.** (1) The group leg has no review step, by design (Q7). (2) A failed group post leaves the latch unset and is retried only by a later panel action — there is deliberately no sweep, so a ticket can sit unposted while the customer has already been confirmed; the row and the board are the safety net, not the group. (3) The per-account ceiling on ticket creation (§1.4) is in-memory unless it is made row-backed, and `InMemoryWindowCounterStore` resets on every redeploy. (4) A resolved ticket can reopen on its own when a customer replies, and there is no notification surface in the panel to announce it — the board is the only place it shows, which follows `TopBar.tsx`'s still-standing refusal of a notifications feed rather than reversing it. (5) The four `AuditAction` members exist twice, in Python and in `admin-dashboard/src/api/audit.ts`, with no cross-language parity test; they stay in step by hand.


> **Amended 2026-09-15 — the support group is chosen in the admin panel, not in the environment.** This amends D18 rather than opening D19: it does not change what the support group *is* — a first-class staff surface with two-way reply, which is D18's second part and stands untouched — it changes only **how the room is chosen**. `BAYRAM_SUPPORT_GROUP_CHAT_ID` and `BAYRAM_SUPPORT_GROUP_THREAD_ID` are **removed from `Settings` and from `.env.example`**, with nothing replacing them: the group is a row in `bot_chats` (migration `0028`) carrying `is_support_group`, selected by an ADMIN or an OWNER in the panel and verified asynchronously against Telegram. `SUPPORT_TICKETS_SPEC` **§3.8** is the specification; **§3.7**'s config table and **§5.1**/**§5.2**/**§6.1**/**§8**/**§9** carry their own dated blocks.
>
> **Reasoning.** Repointing the staff inbox was a unit-file edit, a redeploy and a bot restart — which is why, in practice, it would never have moved. The room a complaint lands in is an operational choice made by the person who runs support, on the day a group is reorganised or a topic is split, and putting it behind a deploy puts it behind the one person in the company who does deploys. The removal is total rather than a seed or a fallback for one reason worth restating: a setting that seeded the table, or that won when the table was empty, is a second authority on one fact, and it makes the first question asked in every support incident — *which room is this actually posting into?* — have two answers, one of them invisible to the screen that exists to show it. The cost of removing them is what made this cheap rather than brave: both were added and deleted **inside the same day**, are deployed nowhere, and so have no operator to warn and no value to carry forward.
>
> **The constraint that shaped the design, and that no amount of engineering moves: Telegram has no "list my groups" API.** A bot cannot enumerate its chats; the only way it learns a group exists is a `my_chat_member` update about its own membership. A group the bot was already in when this shipped produces no such event and **cannot be backfilled** — not from `support_tickets.group_chat_id` either, which would fabricate a title, a type and a membership status nobody ever observed. So discovery is two routes that are deliberately not equally trustworthy: groups the bot is added to from now on are recorded automatically (`source = membership_event`, Telegram's own word), and everything else is a chat id an operator pastes into the panel (`source = manual`, an unverified claim). Because the paste route carries the whole burden the missing API leaves behind, the **verification job** does more work here than it would have in a design with a `/register` command: `support:verify_group` calls `getChat`, posts a confirmation into the room, and records either `verified_at` or a `verification_error` that distinguishes *no such chat*, *the bot is not a member*, *the bot cannot post there* and *the chat migrated to a new id* — a generic failure string would defeat the point of the feature.
>
> **Fallback and switch trigger.** D18's named fallback is unchanged in substance and is now reached by a click rather than a redeploy: **no group selected** — an empty `bot_chats`, which is what every fresh deployment has — is the same complete product `BAYRAM_SUPPORT_GROUP_CHAT_ID=0` was, with the ticket written, the customer answered and the board filled, only the group post skipped. `POST /api/support/groups/clear` is that fallback as an operator action; D18's own triggers (Q2 or Q7 answered badly, the 20/minute group ceiling earning a `retry_after` on the bot token) still switch to it. If the picker itself proves wrong, reverting is a revert: the table is additive, nothing existing changed shape, and the two settings can be reinstated from this repository's own history — but see Reversibility, because that is not free.
>
> **Cost.** One migration (`0028`) and one table. Three enums in `contracts.py`. **One new permission, `support.group.write`, `W` at ADMIN and OWNER with no step-up** — it is deliberately not `support.write`, because working the queue and repointing where the queue lands are different acts with different blast radii, and the accountability is the audit row plus the append-only log exactly as `broadcast.write`'s note argues for its own cell. A second `my_chat_member` registration in the bot, disjoint from the churn one and filtered to groups, which must never touch `users`. Three admin routes, two `AuditAction` members and one `SUBJECT_TYPES` entry. One ARQ job on D12's existing enqueue-never-send seam. One panel screen off the Support board's toolbar — **not** a tenth rail item, so `ADMIN_PANEL_PLAN` §11.2's enumeration is not widened. D18's Cost paragraph said "three settings"; it is now **two**, and neither of them is the group.
>
> **Confidence.** HIGH on the mechanism, which is assembled from primitives already running here: the partial unique index from `admin_users`' active-OWNER invariant, the denormalised actor from `admin_audit_log`, the committed-then-enqueued ordering from the defect fixed in `admin/routers/support.py` the same morning, and the `my_chat_member` subscription that `handlers/membership.py` already causes `start_polling` to request. MEDIUM on discovery as a product experience, and honestly so: the first operator to open this screen on an existing deployment will find it **empty**, because the bot is already in the support group and Telegram will never mention it again. That is the constraint, not a bug, but it means the manual paste is the primary route on day one rather than the fallback it looks like.
>
> **Reversibility.** CHEAP IN CODE, NOT REVERSIBLE IN THE ROOMS THE BOT HAS BEEN IN. The table is additive and the settings could be reinstated, but the rows this feature accumulates are Telegram's own record of every group the bot was added to and removed from, and that history has no other source: delete the table and it cannot be rebuilt, for exactly the reason it could not be backfilled in the first place. What the amendment does **not** make reversible is anything about a customer's words — `bot_chats` deliberately stores **nothing about a person**: `my_chat_member` carries `from_user`, the human who added the bot, and it is not written anywhere, which is what keeps this table out of both of `test_privacy_constraints.py`'s sets and out of `/forget`'s path entirely.
>
> **Known weaknesses.** (1) **An existing deployment discovers nothing** — see Confidence; the bot must be removed and re-added, or the id pasted, and neither is obvious from an empty screen. (2) **A selected group the bot is thrown out of stays selected**: `bot_status` records the removal, nothing un-selects, and cards then fail to post while tickets keep landing on the board — deliberately an operator's call rather than the product's, and filed as §9 Q8. (3) **The group filter is now a per-update lookup**, so it must be cheap and structurally incapable of raising; any cache added later trades a stale room — still claiming messages an operator has stopped reading — for a saving this repository's group traffic will not notice. (4) The `migrate_to_chat_id` case is **reported** rather than followed: the verification job names the new id in words an operator can act on, and a human re-selects.


### D19 — The price and the FX rate are mirrored into the admin process by hand, and an unset pair is a card that names its absence

**Decision.** This deployment carries its song price and its soʻm-per-USD rate into the admin process as four hand-set environment variables — `BAYRAM_ADMIN_SINGLE_SONG_PRICE_MINOR` + `BAYRAM_ADMIN_KIT_CURRENCY`, and `BAYRAM_ADMIN_UZS_PER_USD` + `BAYRAM_ADMIN_UZS_PER_USD_AS_OF` — with **no feed, no scheduled refresh and no cross-process read**, and the rate obliged to carry the date a person took it. Each is a **pair**, bound both-or-neither by a model validator (`src/bayram/admin/settings.py:553`, `:578`); half a pair is a boot refusal, not a degraded card. Unset is a supported, shipped end state: "Est. revenue" renders an em dash carrying `no_price_published`, "MRR" and "ARR" render an em dash carrying `no_fx_rate`, and recorded sales keep totalling in their own currency beside them. The operator procedure is `docs/deployment/02-configuration.md` §"The four finance variables".

**Reasoning.** Two facts force the mirroring and neither is negotiable. The price lives on `Settings`, which is the bot's and the worker's; the panel **deliberately cannot read their `.env`**, because that separation is the vendor-key boundary that justifies running the panel as a third process at all (D14's blast-radius argument, `src/bayram/admin/settings.py:258-262`). Reaching across to discover the running price would hand the admin host the file holding four credentials, which is the one thing the architecture exists to prevent. And the FX rate is owned by nobody: every vendor rate card in the product is quoted in USD and every sale is recorded in UZS tiyin, so the bot and the worker have no use for a rate and it appears in no `.env` of theirs. It is not mirrored from anywhere — it is *originated* here, by a person.

**Why absence is rendered rather than defaulted.** A default of `1.0` would imply parity and make 15 000 soʻm read as $15 000 against $6.31 of cost — a six-figure margin on the one card that exists to say whether the business works. A "plausible" 12 800 would be a number nobody chose, drifting with the som and presented with the confidence of one an operator entered. The em dash with its reason is the only option that is both useful and true: it is diagnosable from the screen, it names the variable to set, and it cannot be mistaken for a measurement. This is the same rule the balance meter follows in **D16** and the same rule `ck_vendor_usage_cost_carries_its_source` enforces in the schema — a figure that could not be measured is absent, and absence names its own reason.

**Why the date is mandatory.** There is no feed, so there is no freshness anywhere in the system except the date a person typed. The panel renders it beside the rate for exactly that reason, and the server converts nothing: every payload carries the UZS amount, the USD cost and the rate side by side, so a card is reproducible from its own response and editing the rate never silently revalues a figure already reported. An undated rate would be a Net card that looks current forever — which is the failure mode this entry is really about.

**What it cost to not have this written down.** The live host has taken **25 recorded sales — 11 via Payme, 14 via the stub rail, all UZS, 24 700 000 tiyin** — and `/api/metrics/dashboard/finance` answers **200** with all of it. None of the four variables is in `/etc/bayram/bayram-admin.env`, so three cards showed dashes, and the dashes were read as an outage and investigated as one. Three of the four gates in `_to_net_run_rate` were already satisfied on that data — the cost figure is present, every revenue row is UZS — so the FX pair alone was the whole fix. A decision that had been recorded would have been a one-line answer.

**Fallback and switch trigger.** **Leave the pair blank and let the panel name the absence.** That is a complete, shipped configuration, not a half-finished one: the tab works, recorded revenue is exact, and the derived cards say why they are empty. It is one line and a restart in each direction. **Trigger: a rate nobody is refreshing is worse than none.** Concretely — the as-of date passing a quarter with no update, a figure from this panel being quoted to anyone on the strength of a rate whose date nobody checked, or the person who set it leaving without handing over the refresh. In any of those, blank both FX lines and restart. The price pair has a different trigger and the same remedy: blank it whenever the worker's `BAYRAM_SINGLE_SONG_PRICE_MINOR` moves and nobody is certain the mirror moved with it — an unpublished price beats a price this deployment does not charge.

**Alternatives rejected.** *Reading the bot's `.env` from the admin process* — rejected on the vendor-key boundary; it is the one thing the third process exists to prevent, and no Finance card is worth it. *A rate feed (CBU or a commercial API)* — rejected for now on the honest count of what it costs: a fourth outbound host on the admin box, a credential or at least an egress rule, a cache, a staleness policy for when the feed is down, and a new class of silent wrongness where a bad fetch revalues every historical card. The em dash costs none of that and is correct. It stays the right answer until somebody is quoting these figures often enough that hand-refreshing them fails, which is the reverse trigger. *Publishing the settings-model default as the price* — rejected outright: it would put a number on a card that a deployment may not be charging, which is worse than a dash because it looks like an answer. *Storing the rate in the config-override table so it can be edited in the panel* — rejected because it puts a figure that revalues every Finance card behind a session rather than behind file access and a restart, and because `BAYRAM_ADMIN_CONFIG_ENABLED` is inert today (no route reads it), so the kill switch that was supposed to guard that surface guards nothing. *Zero-filling* — never on the table; it is the house rule this repository is built on.

**Cost.** Four environment variables, already declared, already validated, in a file that already exists. One section in `02-configuration.md`. Recurring: somebody must remember to re-type a rate, and the only thing that surfaces their forgetting is a date on a card. That is the real price of this decision and it is why the fallback is stated as an end state rather than as a failure.

**Confidence.** HIGH on the mirroring, which is forced by the process boundary and not a preference. HIGH on the absence rendering, which is this codebase's settled rule with three precedents. MEDIUM on the hand-refresh holding: it depends on a human habit with no alarm behind it, which is exactly why the switch trigger is written as "nobody is refreshing it" rather than as a rate threshold.

**Reversibility.** CHEAP IN BOTH DIRECTIONS, and deliberately so. Setting a pair is one edit and a restart; unsetting it is the same. Nothing is persisted, nothing is back-priced, and no historical figure is revalued by either move — the rate travels in the response beside the numbers it converted, so a card rendered last month still explains itself with the rate it was rendered under.

**Known weaknesses.** (1) Nothing alarms on a stale date; the date is rendered and a human must look at it. (2) The price mirror can drift silently — `extra="ignore"` means writing the worker's spelling into the admin file is a no-op with no error, and nothing cross-checks the two processes. (3) Setting three of the four variables takes the panel off the air in a crash loop rather than degrading, which is the correct refusal but an unkind one to walk into; the procedure in `02-configuration.md` states it in capitals for that reason. (4) The rate applies to every historical card at once, so correcting a wrong rate changes what past periods appear to have earned — the as-of date is the only record that they were ever read differently.


---

## 5. Fastest path to a paying bot

## Ordered build sequence — first payment on **day 7**, first cash in hand on **day 28**

The two clocks that cannot be compressed run in parallel from hour one: Telegram's **21-day Stars hold** and Polar's **14-day account review**. Start both on day 1 even though you have no product. Everything else fits inside them.

---

### Day 1 (four hours, mostly waiting on other people)
1. **Enable 2FA on the Telegram account that will own the bot.** Withdrawal requires the 2FA password and setting it up later adds Telegram's own cooldown on top of the 21-day hold. Do this first.
2. **BotFather → bot token → aiogram 3 skeleton with `sendInvoice(currency="XTR", provider_token="")`.** Confirm an invoice renders and a test payment succeeds.
3. **Buy 1,000 Stars yourself and pay your own bot.** ⏱ *This starts the 21-day clock.* Cost: ~$13-20. This single act de-risks the largest unverified dependency in the plan.
4. **Submit the Polar application.** ⏱ *This starts the 14-day clock.* Describe the product as personalised greeting media, disclose AI generation up front, state that lyrics are original and no real artist's voice is cloned — you are in their "AI Content Generation (voice)" enhanced-due-diligence bucket.
5. **Card check:** run a $5 test charge on ElevenLabs, Google Cloud billing and OpenAI with the international Visa/Mastercard. If any declines, try the second issuer's card. Fund an OpenRouter balance (crypto or card) as the LLM payment hedge.
6. **Subscribe to ElevenLabs Starter ($6).** Free-tier output carries no commercial licence and upgrading does **not** retroactively license anything made on Free. Separate free and production keys at the environment level now.

### Day 2 (three hours, ~$15) — **the gate**
7. **Run the singing bake-off.** One fixed Uzbek birthday lyric containing a hard multi-syllable name, in **both** Latin (with real oʻ/gʻ) and Cyrillic; plus one Russian lyric with a stress-sensitive name (Алёна vs Алена). Across ElevenLabs Music, Lyria 3 Pro, Mureka (negative control), MiniMax-via-fal, ACE-Step-on-Replicate, and Suno-via-kie.ai as an **unpriced internal benchmark only**. While you're there, fire 10 concurrent Lyria requests and record what happens — its concurrency ceiling is entirely unpublished and the whole overflow-valve thesis rests on it.
   **This test, not this document, decides what the bot promises.** Do not write marketing copy before it.
8. **Run the Uzbek TTS listen test in parallel:** 20 real Uzbek names + 20 Russian names embedded in Uzbek sentences, through Aisha's four moods, and the same text in Latin *and* Cyrillic to answer the script question. Compare against Azure uz-UZ.
9. **Email Aisha** for commercial rights, SLA, rate limits and Cyrillic handling in writing. **Email ElevenLabs support** for the 59-language Music roster and confirmation of whether `music_v2` and section-level regeneration exist on the API.

### Days 3–5 — the layer that actually matters
10. **Normalisation and name-handling module, written before any vendor SDK.** Apostrophe canonicalisation (U+2018 / U+0027 / U+0060 / U+00B4 / U+2019 → **U+02BB**), script detection, Cyrillic↔Latin transliteration, name respelling heuristics, explicit stressed-form capture for Russian. Unit test per apostrophe variant. Read Navoiy TTS's bundled normaliser first — it is Apache-2.0 and solves part of this already.
11. **Golden-set regression test:** 200 commonest Uzbek and Russian given names, both scripts, with expected pronunciation. Wire it to run on every model or vendor change.
12. **Cover-art compositor:** Pillow/resvg + Noto Sans, verified for U+02BB/U+02BC glyph coverage. Generate 100–200 text-free backgrounds offline via Nano Banana Pro ($13–27, one time) and never call an image model again at request time.
13. **ffmpeg chain:** two-pass `loudnorm` (I=-14 song, I=-16 speech), silence trim, fade, `-c:a libopus -b:a 32k -ar 48000 -ac 1` for Telegram voice notes.

### Days 5–7 — pipeline
14. **ARQ queue + provider interfaces** (MusicProvider, TtsProvider, LlmProvider, SttProvider). The queue is load-bearing, not a nicety: 2 concurrent music slots on Starter/Creator/Pro. Honest "your song is being written" progress messaging, set to the *measured* p95, not the advertised average.
15. **Full order flow:** typed name → optional voice brief → moderation (3 layers) → Gemini intake → lyric + spoken-script + name-respelling in one strict-JSON call → 1 song + 3 greetings + cover → loudnorm → deliver.
16. **Preview-then-deliver:** charge, then send a 20-second watermarked song clip + one greeting, release the full kit on confirmation. This is the structural defence against Stars refunds, where Telegram sides with users and §6.2 threatens debiting your balance.

### 🎯 Day 7 — **FIRST REAL PAYMENT**
17. Soft launch to ~30 friendly users at **300 XTR**. Watch three numbers: name-correctness complaint rate, p95 queue wait, and refund requests.

### Day 21–22 — **the cash-out proves out**
18. The 1,000 Stars bought on day 1 clear their hold. **Withdraw via Fragment → TON → sell through Wallet in Telegram (NAPP-licensed) to a Humo/Uzcard card in UZS.** If this fails, you learn it with $13 at stake instead of a month of revenue. Read `stars_usd_withdraw_rate_x1000` live and re-check the 300 XTR price against it.

### Week 3
19. **Polar goes live** (review complete) as a web checkout for international/English buyers off a landing page. Never for in-bot digital sales — that is the named §6.2 prohibition.

### Day 28 — **first real revenue in the bank**
20. First withdrawal of actual customer Stars.

### Month 2–3
21. **Register an IP (ЯТТ) via EPIGU** — real-time registration, typically under 30 minutes, 1–2 working days to complete. 4% turnover tax, or 0% with IT Park residency (extended to 2040 for companies exporting >50% of revenue, which your market mix easily clears).
22. **Onboard Payme and Click at ~2%.** This recovers **$1.96 per kit** — at 1,000 kits/month, $1,960/month, far more than the entity costs. Keep Stars as the in-bot default because Telegram policy requires it; Payme/Click serve the out-of-bot web checkout and the eventual Uzbek-market landing page.

---

**Time to first payment: 7 days. Time to first cash: 28 days. Time to a payment rail that isn't giving away a third of revenue: ~10 weeks.**

Two things that will break this schedule if skipped: the day-1 Stars withdrawal test (it is the only way to find out whether the money can come out at all), and the day-2 bake-off (it is the only thing that tells you what the bot may honestly promise). Everything else can slip a day without consequence.


---

## 6. Blockers — verify these yourself before committing


1. **FRAGMENT WITHDRAWAL, END TO END — the single highest-risk unverified dependency in the plan.** Enable 2FA on the owning Telegram account, buy 1,000 Stars, pay your own bot, wait the 21 days, then withdraw to a TON wallet and sell that TON through Wallet in Telegram for UZS to a Humo/Uzcard card. Cost: ~$13-20. What you are testing: (a) whether Fragment's Sumsub KYC gates reward *withdrawals* (it demonstrably gates purchases since Nov 2024) and whether an Uzbek passport passes it — one uncorroborated source places Uzbekistan on a Fragment blocked list, which I could not verify against any primary document; (b) whether Fragment will send to the *custodial* Wallet's deposit address, since the NAPP-licensed product in Uzbekistan is the custodial Crypto Wallet and TON Space availability there is unclear; (c) whether Wallet's TON→UZS sale actually completes. Start this on day 1, before writing product code that assumes it works.


2. **INTERNATIONAL VISA/MASTERCARD — apply for TWO from different issuers before anything else.** Uzcard and Humo are domestic rails and cannot pay a single foreign vendor in this stack; this is confirmed by an OpenAI developer-community thread specifically requesting UzCard/Humo support. Kapitalbank, TBC UZ, Anorbank, Uzum and Ipoteka all issue UZS-denominated Visa/MC with international payments enabled. Test a real $5 charge on each of: ElevenLabs, Google Cloud billing, OpenAI and Anthropic. Stripe's fraud layer separately flags BIN-country vs billing-address mismatches, which is exactly what a UZ-issued card with a Tashkent address triggers, so a card that works at one vendor may decline at another. A failed outbound card stops the product just as dead as a failed acquirer.


3. **READ THE LIVE TELEGRAM STARS RATE TABLE BEFORE SETTING THE PRICE.** Every Stars economic figure in this document — $0.0199/Star sell, ~$0.013/Star withdraw, the 21-day hold, the 1,000-XTR floor, the 3-year expiry — comes from secondary sources. Telegram renders its rate table as an IMAGE on core.telegram.org/bots/payments-stars and exposes `stars_usd_sell_rate_x1000` and `stars_usd_withdraw_rate_x1000` as config keys with no documented numeric values. Pull the live config, confirm the numbers, and only then commit to 300 XTR. Re-read quarterly — Telegram can change these at will.


4. **POLAR: submit on day 1 and confirm the payout mechanism.** The review takes up to 14 days and your product falls in Polar's 'AI Content Generation (text, image, video, voice)' enhanced-due-diligence category. Also ask them directly, during onboarding, whether an Uzbekistan payout runs through a full Stripe Connect Express account or a recipient-service-agreement account using Stripe Global Payouts — Stripe's own docs say cross-border payouts CANNOT be made to recipient-service-agreement accounts, and Uzbekistan was only added to Global Payouts destinations in Feb 2026. This determines settlement currency, minimum payout and timing. Uzbekistan IS explicitly on Polar's supported-payout-countries page; the mechanism is what's unclear.


5. **AISHA AI: get commercial rights, SLA, rate limits and latency IN WRITING before it enters the request path.** None of it is published. Specifically ask: (1) may we resell synthesised audio to end consumers as a paid product; (2) does the API accept Cyrillic Uzbek input or must we transliterate — this is the single highest-value unknown in the TTS layer, and their own open-source Navoiy model ships a Cyrillic→Latin normaliser, which suggests the answer is 'we transliterate'; (3) p50/p99 latency and concurrency ceiling, since the existence of both a sync response and an async webhook hints sync is not guaranteed fast; (4) whether they offer support or a licence on Navoiy TTS if we self-host it. Ask all four in one email on day 1.


6. **GOOGLE CLOUD BILLING FROM UZBEKISTAN — attach a real card and make one $0.08 Lyria call.** Uzbekistan IS explicitly on Google's available-regions list for AI Studio and the Gemini API, but I could not confirm from Google's own currency and payment-methods documentation that Uzbekistan is a supported *self-serve Cloud Billing* country; where a country is unlisted, Google says charges 'might incur in USD'. USD billing on an international card is the expected path and is probably fine — but the entire music fallback and the entire LLM layer depend on it, so prove it before architecting around it.


7. **AZURE AND GOOGLE CLOUD PRICES MUST BE READ FROM YOUR OWN BILLING CONSOLE.** Azure's public Speech pricing page renders every figure as a '$-' placeholder and Google's TTS/STT pricing page could not be rendered at all. Every Azure and Google Cloud dollar figure in this document ($16/1M chars TTS, $0.36/hr Fast Transcription, $0.016/min STT, $0.38/1,000 moderation records) is from secondary sources. At 0.05-3% of revenue the risk is immaterial to the decision, but do not put these numbers in a spreadsheet you will defend later without confirming them in the console.


8. **ELEVENLABS: three things only you can ask them.** (1) Request the full 59-language Eleven Music vocal roster in writing — it is a one-email question with a large planning payoff and it may settle the Uzbek and Russian singing questions outright. (2) Confirm whether `music_v2` and section-by-section regeneration actually exist on the REST API — the documented default is `music_v1` and the section-regeneration feature the prior research called decisive is not evidenced on the API reference. (3) Request zero-retention / no-training mode: ElevenLabs' standard terms grant them a licence to use submitted content to improve their models, and your voice briefs are third-party PII — a customer recording facts about someone else who never consented.


9. **UZBEK DATA-PROTECTION: one hour with a local lawyer, on two specific questions.** (a) Post the 27 March 2026 amendments to ZRU-547, is registration with the State Register of Personal Databases still mandatory for an operator processing abroad? None of the amendment coverage answers this clearly. (b) The recipient never consented — the buyer supplies a third party's name, age, relationship and private facts, and the law requires notifying a data subject of their inclusion within 3 days, which is structurally impossible for a surprise gift. Confirm that transient processing with immediate deletion after delivery (maintaining no searchable recipient database) plus an explicit buyer warranty of authority is a sufficient posture. This is not a checkbox you can design your way around.


10. **LOCAL ACCOUNTANT: how is TON received by an individual from Fragment, then sold for UZS, treated for tax and currency control?** Whether it is declarable income, at what rate, and whether IT Park residency (0%) would cover it once an IP is registered. Settle this before revenue reaches a material level, not after. Related: verify that Wallet in Telegram is CURRENTLY in the NAPP registry — Uzbek law confines residents to licensed domestic VASPs and criminalises use of foreign exchanges, and NAPP demonstrated in May 2026 (UzNEX, Order No. 45) that licences get revoked.


11. **NEVER OPERATE ANY ACCOUNT, CI/CD PIPELINE OR SERVER FROM A RUSSIAN IP.** ElevenLabs restricts Russia outright; Russia is absent from Google's Gemini available-regions list, from OpenAI's supported countries and from Anthropic's. Uzbekistan is on all of them. Host on Hetzner Germany (Falkenstein/Nuremberg) — and note ElevenLabs' own help documentation warns that servers can be blocked when the cloud provider's IP range is flagged as associated with a restricted country, so test the vendor handshake from the actual production IP before writing product code against it.


12. **VERIFY THE UZLIB LEADERBOARD YOURSELF BEFORE ACTING ON D5.** The entire decision to overturn Claude in favour of Gemini rests on specific scores (Gemini 3.7 Flash 0.8092 rank 2, GPT-5.6 Luna 0.7141, Claude Opus 4.5 0.6002, human average 0.5894) that were not checked against the live leaderboard, and on the claim that the benchmark converts everything to Latin script. The benchmark itself is real and Tahrirchi is a credible Uzbek NLP lab. Read the leaderboard from source, then run a 200-name in-house eval on Uzbek possessive and case suffix agreement — no public benchmark tests that, and it is the actual failure mode.



---

## 7. Rejected vendors


1. **Suno, via any reseller (kie.ai, apiframe, sunoapi.org, EvoLink, musicapi.ai, APIPASS)** — the licence chain is broken at four points simultaneously: rights are assigned to the *account holder*, which through a reseller is the reseller and never you; the assignment carries 'no representation or warranty that any copyright will vest in any Output'; resellers obtain access by exactly the 'robots, scraping, or similar' methods the ToS forbids, so their accounts are terminable without notice; and the ToS bars using Output 'to create a competing music-generation product'. EvoLink states in writing that it 'does not make licensing guarantees on behalf of the model provider'. Add unresolved major-label litigation and forensic self-identification (the competitor was unmasked from ID3 'made with suno' bytes — any customer or rival can do the same to you). Additionally: **every Suno price and the pivotal 'one generation returns two tracks' billing claim comes from reseller docs, not from Suno** — treat the whole two-variant asymmetry as unestablished. USE FOR ONE THING ONLY: a $5 unpriced internal quality benchmark. File the official partner-API intake form — if a licensed API ever ships, this analysis inverts overnight.


2. **Udio** — post-UMG-settlement it is a walled garden. Outputs 'cannot be exported, downloaded, or uploaded to Spotify, Apple Music, YouTube, or any external platform', and downloads were cut off even for paying annual subscribers. A bot whose entire deliverable is a downloadable file cannot use a platform that forbids downloads by deliberate architecture.


3. **MiniMax Music, direct API** — closed to new users as of 20 August 2026 by MiniMax's own docs: 'the paid APIs will no longer be available to new users; existing paying users can continue'. Access survives only via fal.ai, an intermediary whose own access could change. A vendor closing its front door is not a foundation for a revenue path.


4. **Stable Audio 2.5, Meta MusicGen, Mubert, Loudly, Soundraw, Beatoven.ai, TopMediai, AIVA, Stable Audio Open, DiffRhythm** — none accepts a lyrics input; none sings words in any language. They cannot deliver the product's single hardest requirement at any price or licence quality. Note Beatoven charges $0.10 per *instrumental*, more than Lyria charges for a full *sung* song. Loudly is additionally disqualified by quote-driven enterprise sales — exactly the contract friction the client ruled out. One narrow later use: a licensed instrumental bed under the spoken greetings.


5. **Riffusion / ProducerAI / FUZZ-1.1** — no longer exists as a vendor. Google acquired it in Feb 2026, folded the team into DeepMind, rebranded to Flow Music in April. The redirect chain is live: riffusion.com/api → producer.ai/api → flowmusic.app/api. Old docs and the circulating Postman collection lead nowhere. Everything of value is now reachable through Lyria.


6. **ElevenLabs Music via fal.ai** — $0.60/output-minute versus $0.15/min direct. A 4x markup for zero benefit. fal.ai is the right route for MiniMax and nothing else in this stack.


7. **Any ElevenLabs free-tier key for a paying customer's asset** — the free tier carries NO commercial licence and requires attribution 'no less prominently than immediately surrounding text', and upgrading later does NOT retroactively license anything made on Free. One test render leaking into a paid delivery is an unlicensed commercial distribution. Separate free and production keys at the environment level from day one. Same rule for Narakeet (free accounts are non-commercial and lack API/SSML) and for Gemini (free tier may train on your customers' private family facts).


8. **Yandex SpeechKit — TTS and STT alike** — rejected on payment rail and jurisdiction, NOT on capability. Correcting the research: Yandex genuinely does support Uzbek STT (uz-UZ, Latin script, in its own recognition-language table) and has three Uzbek TTS voices. But prices exist only in RUB and KZT, payment currency depends on which legal entity you contracted with, the Russian route means Russian acquiring severed from international Visa/MC, and the Kazakh route wants a KZ instrument or a corporate contract — the exact onboarding the client ruled out. Two capability caveats if it is ever reconsidered: all three Uzbek voices are FEMALE, and the `+` stress markup is Russian-only ('Поддержка TTS-разметки доступна для русского языка'), so it cannot fix an Uzbek name anyway.


9. **PlayHT / PlayAI** — the vendor is dead. Meta acquired it 12 July 2025, the API went dark 26 July 2025, permanent closure took effect 31 December 2025. play.ht and play.ai fail DNS entirely and docs.play.ai serves an expired TLS certificate. All accounts, voice clones, saved audio and API keys were DELETED with no export tooling. It still appears near the top of most 2024-era TTS shortlists. The lesson generalises: keep two vendors per language and never let a voice identity live only in one vendor's cloud.


10. **Amazon Polly, Cartesia, Rime, Deepgram TTS, Fish Audio, Hume Octave, Speechify** — no Uzbek in any of them. Rime is the most painful rejection: its name-and-address pronunciation control is the closest match on the market to this product's core requirement, and it speaks neither Uzbek nor Russian. Polly's Russian is Standard-tier only and sounds a decade old. Hume is philosophically the right emotion model and is worth revisiting in six months, but Russian is preview-only and its acting-instruction control is still English-gated.


11. **Google Cloud Text-to-Speech, for Uzbek specifically** — zero Uzbek at every tier (Standard, WaveNet, Neural2, Chirp 3 HD, Gemini TTS), verified by grepping the live voice tables. Google Cloud *STT* does support uz-UZ and stays in the stack as an STT fallback; Google TTS does not.


12. **AssemblyAI for Uzbek** — it lists `uz` and then places it in its own 'Fair accuracy (>50% WER)' tier. More than half the words wrong is not a transcript, it is noise, and it would silently corrupt the name and the personal facts the whole product depends on. The clearest illustration in this entire research of why a language-list checkmark must always be checked against a published WER tier.


13. **Whisper (hosted or self-hosted) for Uzbek** — a language token exists, functional accuracy does not. Whisper hallucinates fluent, confident, wrong-language text rather than failing loudly; the documented pattern for comparable low-resource languages is WER at or above 100%. A silent hallucination poisons the lyric prompt with invented facts about a real person.


14. **Ideogram for cover art** — it was shortlisted for exactly one reason, text-in-image, and its own documentation disqualifies it: AI has limitations rendering non-Latin alphabets including Cyrillic, English is recommended for best text rendering, and for precise readable text you should generate the visual and add the text manually in a graphics editor. Where third-party reviews contradict the vendor, believe the vendor. Plus a $15/mo Plus subscription gate for API access.


15. **Any image model asked to render the recipient's name** — Nano Banana Pro included. Correct Uzbek Latin requires U+02BB MODIFIER LETTER TURNED COMMA, and no image model is known to distinguish it from a straight or curly apostrophe. The failure is silent: you cannot detect 'GuInoraga' without OCR-ing your own output, and by then it is in the customer's chat.


16. **Google Imagen 4** — shut down 17 August 2026. **OpenAI gpt-image-1 and gpt-image-1-mini** — scheduled for API removal 1 December 2026. Any plan naming either is out of date.


17. **Perspective API** — out of service after 31 December 2026, Jigsaw stopped processing new usage in February 2026, no migration support offered, no Uzbek, and a 1 QPS ceiling that can no longer be raised. Building on it now creates a migration project before the bot reaches its first thousand users.


18. **AWS Comprehend DetectToxicContent** — English only. It cannot moderate either of the two languages this product exists to serve.


19. **Meta MMS `mms-tts-uzb-script_cyrillic` and Coqui XTTS-v2** — the two open models that actually cover our languages are BOTH non-commercial. MMS is CC-BY-NC-4.0; XTTS-v2 is under the Coqui Public Model License, non-commercial without a separate agreement, and Coqui has shut down so it is unclear who could even grant one. Use **Navoiy TTS (Apache-2.0)** instead — it covers Uzbek in both scripts, has ten emotion styles, and carries none of this baggage. **FLUX.2 [dev] weights** are likewise non-commercial and explicitly prohibit revenue-generating use; the BFL *API* is fine, the dev weights are not.


20. **Purpose-built Uzbek LLM fine-tunes** (Mistral 7B Uz, Mistral Nemo Uz, Llama 3.1 8B Uz, Llama 3.2 1B Uz) — all score below the human baseline on UzLiB and the smallest is barely distinguishable from random. 'It was fine-tuned on Uzbek' is not evidence of quality. The one exception worth evaluating is NeuronAI-oʻzbek_tili (4B), which reportedly beats every Claude model at 4B parameters and could serve as a cheap self-hosted validator — never as the generator.


21. **Stripe direct, Paddle, Creem, CloudPayments, Lemon Squeezy / Stripe Managed Payments** — Uzbekistan is not a supported merchant, seller or payout country for any of them (Creem's 86-country list omits it; CloudPayments' non-resident form names only AZ/AM/BY/GE/KZ/AE; Stripe's 46 merchant countries exclude UZ; Stripe Managed Payments' ~35 exclude it, so Lemon Squeezy is a migration path leading somewhere you cannot follow). Reaching any of them requires foreign incorporation — 4-10 weeks, exactly the gate the client ruled out.


22. **YuKassa and Robokassa** — both require a Russian tax registration (ИП, ООО or самозанятый) or a Russia-bankable foreign entity. Robokassa's 1-3 day application review is fast only *after* you already hold that registration, which is the part that takes weeks.


23. **Any external web checkout for digital goods sold inside the bot** — including Payme and Click once you have them, and including Crypto Bot / @send. Telegram's wording closes the loophole explicitly: 'your bot or mini app must use Telegram Stars for the sale of digital goods and services inside Telegram apps, regardless of any other web portals'. The penalty per ToS §6.2 is 'permanent removal of your TPA from Bot Platform or from store versions of Telegram' — the bot keeps working on desktop while vanishing for every mobile user, which is your entire Uzbek market. Payme/Click belong on an out-of-bot landing page, never inside the conversation.


24. **Telegram Ads as a treasury** — Stars moved into the Ads cabinet buy inventory at a 30% discount and CANNOT be moved back out. A documented operator account describes Stars stranded there permanently alongside repeated unexplained moderation rejections and no support channel. Treat the Ads discount as a marketing decision, never as a place to park working capital.


25. **A raw prompt-to-song passthrough feature** — ElevenLabs' Music Model-Specific Terms define a prohibited 'Reseller' as anyone who makes the Music Models available WITHOUT SUBSTANTIAL ADDED FUNCTIONALITY. Bayram passes that test comfortably today (LLM intake, lyric writing, spoken greetings, cover art, Telegram delivery). Shipping a bare 'send me a prompt, get a song' mode would land squarely inside the prohibition and put the whole licence at risk.



---

## 8. Known weaknesses in these decisions


An adversarial pass attacked the document above. Its findings are recorded here rather than quietly absorbed, because several are unresolved.


**Overall verdict.** Strong document — the reversibility framing, the deterministic-typography call (D7), and the "no vendor sings Uzbek, so don't sell it" honesty (D2) are all correct and rare. Four things would change decisions.

MOST LIKELY WRONG IN SIX MONTHS: D9's price, not its rail. The doc quietly overrides the client's 39,000 UZS (~$3.29) with 66,000 UZS (~$5.57) because Stars won't survive the lower number — at 39,000 UZS the doc's own math gives $1.65/kit net. That inverts the argument: the founder didn't pick a price and then a rail; the rail picked the price, and it picked one ~69% above whatever market signal produced 39,000. If 39,000 is real, Stars is not a speed decision, it is a decision not to sell in Uzbekistan. Payme/Click at month three isn't margin recovery, it's the precondition for the domestic market existing. Resolve the price question before day 7, not month 3.

SINGLE-VENDOR BET WITH NO REAL FALLBACK: ElevenLabs, and the doc never names it. Music + Russian TTS + English TTS + STT = four of eight layers on one account, one ToS, one card, celebrated in the stack table as "one vendor, one key." A suspension, a geo/IP-range block (which the doc's own blocker #11 warns about), or a billing decline takes out song, speech, and transcription simultaneously. Every listed fallback is untested and one (Lyria) the doc explicitly forbids promoting. Aisha is the weaker *contract*, but ElevenLabs is the correlated *failure*.

PAYMENT — HIDDEN GATES, YES, THREE: (1) Stars is the fastest path to *charging*, not to *being paid*. Day 28 is the floor and it is contingent on Fragment KYC that the doc itself cannot verify passes an Uzbek passport, on Fragment sending to a custodial Wallet address, and on a TON→UZS sale through a VASP whose licence the doc warns can be revoked. Three unverified serial gates on the only cash-out path. (2) 300 XTR is not a purchasable quantity — Apple/Google sell Stars in fixed packs (…250, 350, 500…), so a 300 XTR sticker forces a 350 pack and strands 50 Stars. Price on a pack boundary or eat the friction. (3) The entire "reaches domestic Uzcard/Humo buyers" claim rests on unofficial third-party Star resellers at 220 UZS. That is a grey market Telegram can close, not an ecosystem feature, and it carries the whole Uzbek funnel.

UZBEK PLAN — HONEST ON SINGING, NOT ON SPEAKING. "Guarantee three spoken greetings in flawless Uzbek" is not supportable on any of the three legs: Aisha's quality is vendor marketing with no contract, Navoiy's own model card says it mispronounces names (quoted approvingly as vendor candour rather than counted as a fallback downgrade), and Azure uz-UZ carries footnote 3 — no phonemes, no lexicon — meaning on the failover leg you *cannot correct a mispronunciation at all*. D10's whole thesis is that name correctness is won by respelling in your own code, but respelling requires a phonetically predictable front end, and you have zero measurement of Aisha's grapheme-to-phoneme behaviour. Say "native Uzbek voices" and drop "flawless" and "guarantee" until the 20-name listen test exists.


### Decisions most likely to be wrong


1. D10, concrete bug in the single most load-bearing module: the spec says map every apostrophe variant to canonical U+02BB. That is wrong. Uzbek uses U+02BB for oʻ/gʻ and U+02BC (tutuq belgisi) elsewhere — Sanʼat, Maʼmur, Nuʼmon. Blanket collapse corrupts exactly the names it exists to protect, and the document contradicts itself: the typography row of the language matrix correctly lists both codepoints. Normalisation must be context-sensitive (after o/g → U+02BB, otherwise → U+02BC), and the golden set must contain tutuq-belgisi names or the test will never catch it.


2. D9 price, the most consequential error: 66,000 UZS is a founder-margin-derived number overriding a market-derived one (39,000). The doc flags the gap as a 'pricing trap in the client's numbers' but the trap may be in the rail. Test 39,000 UZS demand before committing to a rail that cannot survive it.


3. Stack-table framing of ElevenLabs concentration as a virtue ('one vendor, one key', 'same voice family; one vendor, one key'). Four layers on one account is the largest uncorrelated-failure assumption in the document and it is never stated as a risk anywhere, including in reversibility, which assesses each decision in isolation.


4. D3, Aisha in the synchronous request path with no published commercial terms, no SLA, no rate limits, no latency figures. The blockers list correctly says get it in writing 'before it enters the request path' — but the day 1-7 build plan puts it in the request path on day 5-7 and only emails on day 2. Either the email answer gates the launch or it doesn't; as written it doesn't.


5. D3 fallback correlation: Aisha primary and Navoiy fallback are the same lab. Apache-2.0 makes the weights unrevocable only if you have them. Mirror the weights and the normaliser to your own storage on day 1 — the doc never says to.


6. D2's chosen differentiator is the weakest moat in the stack. 'Speaks Uzbek properly' is delivered by a self-serve API and a public Apache-2.0 repo — a Tashkent competitor replicates it in a weekend. The defensible assets are the normalisation layer, the golden set, and the deterministic compositor (D7/D10), not the voice.


7. D9 defers the entity to month 3 without checking whether самозанятый (self-employed) status — registrable same-day via my.soliq.uz — unlocks any domestic PSP contract. If it does, the 33% haircut is a week-one problem, not a ten-week one. This is the single highest-value unasked question in the payment section.


8. Take-rate terminology is inverted throughout: '~64% take rate' for Stars and '83.7% take rate' for Polar are retention rates. Stars' actual take is ~36%. A founder comparing rails on these labels will read them backwards.


9. The 7-day schedule. Days 3-7 cover the normalisation module (self-costed at 'roughly a week'), a 200-name golden set, the compositor, the ffmpeg chain, the ARQ queue, four provider interfaces, the full order flow, and a preview-then-deliver payment flow. That is 2-3 weeks of real work. It matters because the 21-day hold and 14-day Polar review are sold as the binding clocks; if the build is binding, the day-1 parallelism buys nothing and day 28 is really day 40.


### Risks with no cost line


1. Refunds. Zero budgeted, in a rail the doc itself says 'sides with users' and can debit your balance. A 5% refund rate costs the full $3.90 recognised revenue plus $0.65 of already-spent COGS ≈ $0.23/kit — larger than the entire moderation, STT, art and audio lines combined, and a third of total COGS.


2. Navoiy as a *hot* fallback costs money the model shows as $0.00. A GPU that must be spun up during an Aisha outage is not a fallback; a 24/7 standby is ~$150-300/mo on Hetzner GPU. At 1,000 kits/month that is ~$0.20/kit — it doubles the Uzbek speech line. Either price the standby or admit the fallback is warm-at-best.


3. The free re-roll is unbounded but modelled as exactly one re-roll on 25% of orders. With no phoneme control on any music model and Uzbek names as the failure mode, both the rate and the count are guesses; 40% at 1.4 rolls each doubles the song line.


4. Star reseller market risk. The 220 UZS/Star rate is the entire domestic-card story and depends on unofficial resellers. If that channel is squeezed, the Uzbek buyer's only remaining price is the $5.97 in-app one, in a market the client priced at $3.29.


5. Voice-brief PII shipping to ElevenLabs on day 7 under terms that grant a model-training licence, on recordings containing a third party's private family facts. Blocker #8 flags it; the build plan launches before zero-retention is confirmed. This is a live exposure at first payment, not a later cleanup.


6. Uzbek data protection generally: blocker #9 says it is 'not a checkbox you can design your way around', and it appears nowhere in the day 1-28 sequence. The 3-day subject-notification requirement is structurally incompatible with a surprise gift and the doc knows it.


7. FX. 11,850 UZS/USD is treated as fixed across the Aisha line, the reseller rate, and both sticker prices. UZS depreciation is steady, not hypothetical; a 10% move shifts the UZS sticker and the Uzbek COGS in opposite directions.


8. Burst concurrency. 2 music slots is sized against a monthly average. Gift buying is evening-clustered and holiday-spiked (New Year, Navruz, 8 March); the queue depth that triggers the $299 Scale purchase will arrive on a specific evening, not gradually.


9. Founder time. Not one hour of engineering or founder labour is costed anywhere, including the day-2 bake-off, the labelled 400-string moderation probe set, the 200-name evals (two of them), and the lawyer and accountant hours the blockers mandate.


### Options never considered


1. Mohir.ai (Tahrirchi) — Uzbek STT and TTS from the same lab whose UzLiB benchmark the document treats as authoritative enough to overturn D5. Never evaluated, never listed, never rejected. It is the obvious second Uzbek speech vendor and would break the Aisha/Navoiy single-lab correlation.


2. A human. At $5.90 with 89% gross margin and low launch volume, a Tashkent singer recording the name-bearing line over a licensed instrumental bed is the only path that actually delivers sung Uzbek — the exact capability the doc concludes no vendor has. A $1.50-2.00 human pass on a premium Uzbek SKU is affordable and is a real moat, unlike the spoken-TTS one. Never considered.


3. A cheaper spoken-only SKU. One price, one product, one rail is the whole plan. A ~100 XTR spoken-greetings-plus-cover kit sidesteps the singing uncertainty entirely, lands on a purchasable Star pack, and fits the 39,000 UZS price point the client actually named.


4. Uzbek PSPs beyond Payme and Click — Atmos, Multicard, Octobank, Uzum merchant, Paynet. The doc treats 'Payme/Click' as synonymous with domestic acquiring; onboarding requirements and timelines differ across them and at least one may accept a lighter registration.


5. YuE (M-A-P, Apache-2.0, lyrics-to-song) as the self-hostable fine-tunable strategic reserve. The doc nominates ACE-Step 1.5 for that role and never mentions YuE, which is the closer comparison on lyrics conditioning.

