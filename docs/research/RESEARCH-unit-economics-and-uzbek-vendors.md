# Cost, Margin and Uzbek-Capability Report — Birthday Song Kit (UZ)

**Compiled 2026-09-05.** All prices carry a source URL. Where adversarial verification [E] corrected an input, the corrected value is used and the correction is flagged inline. Derived figures are labelled DERIVED; nothing unverified is presented as verified.

---

## 0. Standing assumptions (state these whenever quoting a number)

| # | Assumption | Value | Status |
|---|---|---|---|
| A1 | Tokenisation of Uzbek Latin / Cyrillic | **1 token ≈ 3 bytes** (worse than English's ~4; U+02BB fragmentation makes it worse still) | Assumption, per task brief. Real range plausibly 1.8–3.0 B/token → ±40% on the LLM line |
| A2 | Music billing granularity for a 90 s track | **Billed as 1 whole minute → $0.30**, not $0.225 | **[E] CORRECTION.** Two live ElevenLabs pages contradict each other: `/pricing/api` says "Music and Sound Effects are billed **per generation**"; `/pricing` says "Eleven Music **900 credits per minute**". Rounding rule stated nowhere. $0.225 must not be quoted as a price |
| A3 | Every API re-roll is fully billable | Yes | Free regenerations are website-only and explicitly "not available via the API" ([A], `/docs/help-center/account/general/do-i-use-quota-on-every-generation.md`). Whether a *failed* (5xx) generation bills is **undocumented** |
| A4 | Respell prompt size | ~1,500 B (not supplied in context) | Assumption |
| A5 | Output token counts | intake 250, lyric 700, respell 60, +150 if greeting text | Assumption; kit output is capped at `max_output_tokens 2048` so 700 is safely inside |
| A6 | LLM model | `google/gemini-3.7-flash` at $0.75/$3.75 per 1M — **the recommended replacement, not the currently-configured free model** | Verified, `openrouter.ai/api/v1/models/google/gemini-3.7-flash/endpoints` |
| A7 | Gross margin excludes the customer-side payment acquiring fee | — | No verified UZ acquirer rate exists in the research inputs |

---

## 1. Cost of one song — the number

### 1a. Token derivation (A1: bytes ÷ 3)

| LLM job | Input bytes | → input tokens | Output tokens (A5) |
|---|---|---|---|
| Intake normalisation | 2,085 + 197 = 2,282 | 761 | 250 |
| Lyric write (system + user + uz-Latn pack) | 5,039 + 416 + 1,130 = 6,585 | 2,195 | 700 |
| Name respelling (A4) | ~1,500 | 500 | 60 |
| Parse-retry nudge | 273 | 91 | (700 on retry) |

### 1b. DEFAULT SKU — 90 s song, song-only, no greeting, 1.0 generation attempts

| Line item | Unit rate | Source | Qty | USD |
|---|---|---|---|---|
| LLM intake normalisation | $0.75 /M in, $3.75 /M out | [openrouter.ai/api/v1/models/google/gemini-3.7-flash/endpoints](https://openrouter.ai/api/v1/models/google/gemini-3.7-flash/endpoints) | 761 in / 250 out | 0.00151 |
| LLM lyric write | same | same | 2,195 in / 700 out | 0.00427 |
| LLM name respelling | same | same | 500 in / 60 out | 0.00060 |
| LLM parse-retry allowance (20% × nudge+regen) | same | same | 0.2 × (2,286 in / 700 out) | 0.00087 |
| **Music render, 90 s** | **$0.15 / min, billed to the whole minute (A2)** | [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api) | 1 × 1 min | **0.30000** |
| STT name verification, 8,000 ms chunk | $0.22 / hr | [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api) | 8 s | 0.00049 |
| Retry tail (music re-rolls) | — | — | 0 extra | 0.00000 |
| **TOTAL COGS** | | | | **$0.3077** |

> If sub-minute proration turns out to be real, this line falls to $0.225 and the total to **$0.2327**. That single unknown is a 24% swing on COGS. Do not budget on it until measured.

### 1c. FULL KIT — 90 s song + 45 s spoken greeting (~650 chars), 1.0 attempts

| Line item | Unit rate | Source | Qty | USD |
|---|---|---|---|---|
| All of 1b | — | — | — | 0.30774 |
| LLM greeting-text output (incremental) | $3.75 /M out | [openrouter](https://openrouter.ai/api/v1/models/google/gemini-3.7-flash/endpoints) | +150 out | 0.00056 |
| **TTS greeting, `eleven_v3`** | $0.10 / 1,000 chars | [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api) | 650 chars | **0.06500** |
| **TOTAL COGS** | | | | **$0.3733** |

**Greeting swap available:** `eleven_v3_conversational` is $0.05/1,000 chars → **$0.0325**, halving the greeting line ([elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api)). Full-kit total becomes $0.3408.

**Greeting caveat that dwarfs the price:** ElevenLabs has **no Uzbek TTS voice at all** (grep of the full rendered models doc: zero hits for "Uzbek"/"uzb", while Kazakh, Turkish and Azerbaijani each appear 8×). This $0.065 line buys you a **RU/EN-only** greeting. See §6b.

---

## 2. The retry tail

Each additional generation attempt re-runs: name respell → music render → STT verify.

**Marginal cost of one extra attempt = $0.00060 + $0.30000 + $0.00049 = $0.30109.**

| Avg generation attempts / delivered kit | Song-only COGS | Full-kit COGS | Song-only, if A2 is wrong ($0.225/track) |
|---|---|---|---|
| 1.0 | $0.3077 | $0.3733 | $0.2327 |
| **1.5** | **$0.4583** | **$0.5238** | $0.3458 |
| 2.5 | $0.7594 | $0.8249 | $0.5719 |
| 3.0 (hard cap in code) | $0.9099 | $0.9755 | $0.6849 |

### Plan on 1.5. Here is why.

- The verification gate is `min_similarity 0.85` on an 8 s chunk of a **name sung over a backing track**. Every published Uzbek STT number in the research is for **read speech in quiet conditions** — nobody, in any language, publishes a WER for a sung name over music ([D]). You have no basis for assuming a first-pass rate near 100%.
- The failure mode is structural, not random: the U+02BB modifier letter in `oʻ`/`gʻ` fragments names like *Gʻulomjon* in the music model's tokenizer. Structural failures cluster — a name that fails once tends to fail again, which pushes the *conditional* attempt count up on the subset of orders that fail at all.
- 1.0 is only reachable if verification essentially never trips, which would make the 3-attempt loop dead code. 2.5 implies most orders fail twice, which would be a broken product you'd notice.
- 1.5 costs $0.46 song-only — **7.8% of the $5.90 price**. Even the 3.0 hard ceiling is $0.91, **15.4%**. The retry tail cannot break this business (see §4). Budget 1.5, instrument the actual distribution, and stop worrying.

### Are re-rolls billed? Per [A]: **assume yes.**

| Question | Answer | Evidence |
|---|---|---|
| Is an API re-roll billed? | **Yes — treat as fully billable** | "Free regenerations for Text to Speech and Speech to Speech are only available via the website. They are not available in via the API." Music is not named in that article at all ([elevenlabs.io/docs/help-center/account/general/do-i-use-quota-on-every-generation.md](https://elevenlabs.io/docs/help-center/account/general/do-i-use-quota-on-every-generation.md)) |
| Is a **failed** (5xx) generation billed? | **UNDOCUMENTED.** No vendor page addresses it | [A] searched `/docs/eleven-api/resources/errors.md`, billing docs, both pricing FAQs and `/docs/llms-full.txt` — nothing |
| Does **inpainting** bill only the regenerated chunk? | **UNDOCUMENTED**, and the highest-value unknown after A2 | `/docs/eleven-api/guides/how-to/music/inpainting.md` documents generation-chunks vs audio-reference-chunks with **zero** billing language. If chunk-only billing holds, re-rolling just the mis-sung name could cut the retry tail ~5× |
| Undocumented cost multiplier the earlier work missed | **Number of variants** | "The cost of Eleven Music depends on the length of your track **and how many variants you're generating**" ([elevenlabs.io/docs/help-center/product/core-capabilities/music/how-much-does-eleven-music-cost.md](https://elevenlabs.io/docs/help-center/product/core-capabilities/music/how-much-does-eleven-music-cost.md)). The compose endpoint has no variants parameter, so the API path is 1 track/request — but anyone reasoning from UI credit deltas will be off by the variant count |

---

## 3. Sensitivity — what actually moves COGS

Ranked by absolute USD swing per delivered kit, song-only baseline $0.4583 at 1.5 attempts.

| Rank | Input | Swing range | Δ USD/kit | Δ % of COGS | Notes |
|---|---|---|---|---|---|
| **1** | **Music vendor** | ElevenLabs $0.30 → WaveSpeed ACE-Step 1.5 $0.027 (90 s @ $0.0003/s) | **−$0.41** | **−89%** | [wavespeed.ai/models/wavespeed-ai/ace-step-1.5](https://wavespeed.ai/models/wavespeed-ai/ace-step-1.5). **BLOCKED on Uzbek evidence — see §6a.** [E] downgraded ACE-Step's Uzbek grade to *unlisted*, identical to ElevenLabs |
| **2** | **Avg attempts / kit** | 1.0 → 3.0 | **+$0.60** | **+196%** | Fully under your control via name-respelling quality and STT threshold tuning |
| **3** | **Music billing granularity (A2)** | $0.225 vs $0.30 per 90 s attempt | **±$0.11** at 1.5 attempts | ±25% | **Unresolvable from any vendor page.** One 20-minute experiment settles it — see §7 |
| **4** | **Greeting on/off** | $0 → $0.065 (`eleven_v3`) or $0.0325 (`v3_conversational`) | +$0.033–0.065 | +7–14% | Currently off (`greeting_duration_s = 0`) |
| **5** | Song length | 90 s → 120 s | **$0.00** under A2, +$0.075 if prorated | 0% or +16% | **If minute-rounding is real, a 120 s song costs exactly the same as a 90 s one.** Free product upgrade contingent on resolving A2 |
| 6 | LLM model | free tier $0 → gemini-3.7-flash $0.0064 → flex-tier $0.0032 | ±$0.006 | ±1.4% | Whole LLM stack is **1.4% of COGS**. Optimising it is noise; buy the good model |
| 7 | STT engine | Scribe $0.00049 → Google chirp $0.00213 | +$0.0017 | +0.4% | Noise. Choose on accuracy alone |

**The headline:** the only two levers worth engineering effort are the **music vendor** (blocked on an unrun Uzbek test) and the **attempt rate** (blocked on unmeasured production data). Everything else is rounding error against a $5.90 price.

---

## 4. Margin at $5.90

| Attempts/kit | Song-only COGS | Gross profit | **Gross margin** | Full-kit COGS | Gross profit | **Gross margin** |
|---|---|---|---|---|---|---|
| 1.0 | $0.3077 | $5.5923 | **94.8%** | $0.3733 | $5.5267 | **93.7%** |
| **1.5 (plan on this)** | **$0.4583** | **$5.4417** | **92.2%** | **$0.5238** | **$5.3762** | **91.1%** |
| 2.5 | $0.7594 | $5.1406 | **87.1%** | $0.8249 | $5.0751 | **86.0%** |
| 3.0 (code cap) | $0.9099 | $4.9901 | **84.6%** | $0.9755 | $4.9245 | **83.5%** |

### Break-even attempts per kit

COGS(n) = fixed + n × per-attempt, where per-attempt = $0.30109.

- **Song-only:** fixed $0.00665 → break-even at **n = 19.6 attempts**
- **Full kit:** fixed $0.07221 → break-even at **n = 19.4 attempts**

**Your code caps n at 3.** The retry loop is mathematically incapable of making a kit unprofitable — it would need to run **6.5× past its own hard cap**. Worst possible COGS is $0.98 (83.5% margin). Stop treating the retry tail as a financial risk; it is a *quality* and *latency* risk, and a **generation-cap** risk (§5).

*Excludes payment acquiring fees (no verified UZ rate available) and OpenRouter's 5.5% + $0.80-minimum credit top-up fee ([openrouter.ai/docs/faq](https://openrouter.ai/docs/faq)) — the latter adds ~6% to a $0.006 line item, i.e. $0.0004/kit.*

---

## 5. Monthly floor and the self-hosting crossover

### Fixed fees before the first sale

| Item | Cost | Why it's mandatory | Source |
|---|---|---|---|
| **ElevenLabs Starter** | **$6 / mo** | Music API needs it: Free has `API Access: No` and **music concurrency 0** | [elevenlabs.io/pricing](https://elevenlabs.io/pricing) |
| OpenRouter | **$0 / mo** | No subscription, no inference markup; 5.5% + $0.80 min on card top-ups (buy in blocks so the $0.80 floor amortises) | [openrouter.ai/docs/faq](https://openrouter.ai/docs/faq) |
| ElevenLabs TTS/STT | **$0** | Work on Free/PAYG | [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api) |
| **Total floor** | **$6 / mo** | | |

### The $6 floor is a trap — the contractual caps bind, not the credits

All limits from [elevenlabs.io/eleven-music-model-specific-terms](https://elevenlabs.io/eleven-music-model-specific-terms) (Music Commercial Rights table).

| Tier | $/mo | Gen cap (min/mo) | 90 s **generations** | **Delivered kits @ 1.5 attempts** | Download cap (min/mo) | Revenue ceiling @ $5.90 | Entity may enrol? |
|---|---|---|---|---|---|---|---|
| Free | $0 | 11 | — | **0** (API access No, concurrency 0, download Not permitted) | — | $0 | Individual only |
| **Starter** | **$6** | **17** | 11 | **7** | 30 | **~$41** | Individual only |
| Creator | $22 | 62 | 41 | **27** | 250 | ~$160 | Individual only |
| Pro | $99 | 304 | 202 | **135** | 500 | ~$795 | Individual only |
| **Scale** | **$299** | 1,100 | 733 | **488** | 1,500 | ~$2,880 | **First tier an entity may enrol on (<10 employees)** |
| Business | $990 | 4,800 | 3,200 | **2,133** | 4,000 | ~$12,590 | <50 employees |
| Enterprise | Contact sales | Custom | — | — | Custom | — | Yes |

Three consequences you cannot engineer around:

1. **The generation cap binds before the download cap at every tier up to Business**, because re-rolls consume generation minutes but only the delivered track consumes a download minute. At 1.5 attempts the gen cap is what you hit.
2. **Starter tops out at ~7 delivered kits a month (~$41 revenue).** You will hit this in week one of any real launch. Budget for Creator/Pro immediately.
3. **Eligibility is a hard wall.** Free/Starter/Creator/Pro are all *"For Individual Use Only."* A company cannot legitimately sit on Pro; enrolling on an ineligible plan "may result in suspension or termination of your account and/or loss or forfeiture of Outputs, fees, and/or credits." **The honest floor for an incorporated operator is $299/mo (Scale).**

Add the licence overlay: **Reseller Rights are "Prohibited" on all six self-serve tiers** — Free through Business — and Custom only on the two Enterprise Music tiers. §5(f) targets an entity that "resells, repackages, redistributes, or otherwise makes available ElevenLabs' Music Models through its own platform or application without adding substantial functionality beyond basic user interface changes." This bot adds intake normalisation, lyric authoring, name respelling, sung-name verification and a payment rail — a real argument for "substantial functionality" — but it is a legal call, not a documented fact, and the clause is aimed at this exact product shape. **Escalate before scaling.**

### When does self-hosting beat hosted?

**It probably never does, and the crossover is against the wrong baseline.** The relevant comparison is not ElevenLabs-vs-your-GPU; it is **hosted open weights** vs your GPU:

- WaveSpeed hosted ACE-Step 1.5: **$0.027 per 90 s track** at $0.0003/s, no GPU to operate ([wavespeed.ai/models/wavespeed-ai/ace-step-1.5](https://wavespeed.ai/models/wavespeed-ai/ace-step-1.5))
- Replicate hosted ACE-Step 1.5: **$0.062 per run** at $0.000975/compute-second on L40S ([replicate.com/fishaudio/ace-step-1.5](https://replicate.com/fishaudio/ace-step-1.5)) — note this is **compute-second billing, so a 90 s track is not proportionally cheaper**

A dedicated GPU bills 24/7 whether you sell or not. To beat $0.027/track at a GPU rate of $X/hour you need sustained throughput of **X ÷ 0.027 = ~37X tracks/hour**. At an *illustrative and unverified* $0.50/hr that is ~19 tracks/hour ≈ **13,500 tracks/month sustained** — an order of magnitude past even the Business-tier ceiling.

**I cannot give you a hard crossover number and will not invent one:** Vast.ai's pricing page serves a JS dashboard with no numeric rates in the HTML, MiniMax-Music3 publishes no RTF or per-song runtime, and no vendor publishes an ACE-Step cold-start figure ([C], unverified list). Both terms of the equation are missing. **Conclusion: use hosted open weights, not your own GPU, at any volume this product will plausibly reach.**

---

## 6. Can anything beat ElevenLabs on Uzbek?

### 6a. Music — **No. Nothing beats it. Nothing even matches it on evidence, because there is no evidence anywhere.**

Grades: **demonstrated** = auditable audio attributable to a named model · **claimed-in-docs** = vendor page names Uzbek · **unlisted** = no roster, no claim, no denial · **excluded-by-roster** = vendor publishes a closed list that omits Uzbek.

| Vendor / model | Uzbek grade | What the vendor actually says | 90 s price | Shippable? | Source |
|---|---|---|---|---|---|
| **ElevenLabs Eleven Music v2** (incumbent) | **unlisted** | "Multilingual, including English, Spanish, German, Japanese **and more**" — open-ended, no roster, Uzbek never named | **$0.30** (A2) | Yes, but Reseller Rights prohibited on every self-serve tier | [docs/capabilities/music](https://elevenlabs.io/docs/capabilities/music) · [pricing/api](https://elevenlabs.io/pricing/api) |
| **WaveSpeed ACE-Step 1.5** | **unlisted** ← **[E] DOWNGRADED from "claimed-in-docs"** | "Supports 50+ languages" with **no roster on the page and no language input field**. Every enumerated upstream roster omits Uzbek: musicians' guide names 19 languages, transcriber card names 26 codes — **Turkish is the sole Turkic entry in both** | **$0.027** | Cheapest by 11×, **Uzbek unproven — do not let an Uzbek SKU depend on it untested** | [wavespeed.ai/models/wavespeed-ai/ace-step-1.5](https://wavespeed.ai/models/wavespeed-ai/ace-step-1.5) |
| **Replicate ACE-Step 1.5** | **unlisted** | Same model family. **But**: the embedded prediction log shows a literal `# Languages\nunknown\n# Lyric\n...` conditioning block — the only pre-generation pronunciation lever anyone in this market exposes | $0.062/run | **Cleanest licence in the survey**: ToS §5.1 assigns "all right, title and interest… in and to Output, including… commercial purposes such as sale"; MIT upstream, no third-party rider | [replicate.com/fishaudio/ace-step-1.5](https://replicate.com/fishaudio/ace-step-1.5) |
| **Google Lyria 3.5** | **unlisted** | Reverted to "generates lyrics in the language of your prompt" with **no roster** — so the old Lyria 3 Pro exclusion is now historical | $0.08/song | Single-turn only (no iterative refinement), mandatory non-removable SynthID watermark, absent from the indemnified-services list | [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| MiniMax Music 3.0 (WaveSpeed) | unlisted | No roster; all 26 demo tracks are English Western genres | $0.15 flat/run | Community licence §3.1 forces a "MiniMax-Music3" badge on your UI — a third-party brand on a $5.90 gift | [wavespeed.ai/models/minimax/music-3.0](https://wavespeed.ai/models/minimax/music-3.0) |
| **Suno** | **demonstrated** | 166 Uzbek AI tracks on aimusic.so + 10 on musichero.ai, both attributing Suno; one file downloaded and ffprobe-verified as real audio (187.88 s, 192 kbps) | n/a | **NO. No public API** (developers.suno.com and docs.suno.com do not resolve; api.suno.com 404s), ToS bars competing-product use, commercial rights gated on metered downloads since 3 Sep 2026 | [suno.com/blog](https://suno.com/blog) |
| Mureka 9.5 | **excluded-by-roster** | Closed list of 10: zh, en, ja, ko, pt, es, de, it, fr, ru. **No Turkic language** | unverifiable | RU/EN SKU only. Upside: strongest ownership text in the market (§3.2 outright assignment) and the UZ region gate does **not** fire pre-auth (401, not 403, from Tashkent) | [platform.mureka.ai/docs/en/changelog.html](https://platform.mureka.ai/docs/en/changelog.html) |
| HeartMuLa-oss-3B | **excluded-by-roster** | Model card YAML: `language: [zh, en, ja, ko, es]` — **[C] corrects an earlier grade of "claimed"** | unverifiable | No | [huggingface.co/HeartMuLa/HeartMuLa-oss-3B](https://huggingface.co/HeartMuLa/HeartMuLa-oss-3B/raw/main/README.md) |
| Sonauto / Treblo | unknown | **Cloudflare 403 "you have been blocked"** naming the Tashkent IP | — | **Geo-blocked from Uzbekistan.** The only hard block across 15 vendors tested | [sonauto.ai](https://sonauto.ai) |
| fal.ai MiniMax Music 3 | unlisted | — | unverifiable (client-side only) | **No** — ToS disclaims any IP entitlement in Output and §6(e) bars service-bureau use for third parties. That is exactly this product | [fal.ai/models/minimax/music-3](https://fal.ai/models/minimax/music-3) |
| PiAPI ACE-Step | unknown | — | **contradicts itself 10×** ($0.00005/s vs $0.0005/s on two PiAPI-hosted pages) | ACE-Step v1, a generation behind | [piapi.ai/pricing](https://piapi.ai/pricing) |

**Blunt verdict on music:** **Zero music vendors name Uzbek for sung output.** Not one. ElevenLabs and ACE-Step are on *identical* evidence — both "and more"/"50+" with no roster — and [E] refuted the claim that ACE-Step's marketing counts as documented support. **No published Uzbek WER or MOS exists for any singing model from anyone.** The only auditable Uzbek AI songs come from Suno, which is unshippable, and even there the sole Uzbek-language review is negative on precisely the axis that matters ("*talaffuz baʼzan gʻalati*" — pronunciation is sometimes strange).

**So: nothing beats ElevenLabs on Uzbek, but only because nothing has been tested.** The 11× price gap to ACE-Step ($0.30 → $0.027) is real, re-derivable and large enough to matter at scale. It is unlocked by **one afternoon of testing** (§7, action 2), not by more reading.

### 6b. TTS / STT — **Yes on both, and decisively. This is where ElevenLabs is actually beatable.**

**Speech-to-Text (the name-verification loop):**

| Engine | Published Uzbek accuracy | Price | Verdict |
|---|---|---|---|
| **GigaAM-Multilingual** (ai-sage, open weights, **MIT**) | **WER 7.3 FLEURS / 9.2 Common Voice / 12.7 internal** — a real per-language number | $0 (self-host) | **BEATS ElevenLabs on published accuracy, by 2–4× over the next-best model.** 158,539 HF downloads, ONNX/CTC conversions exist, small enough to self-host cheaply. Caveat: measured on **read speech**, not a name sung over a backing track | [arxiv.org/html/2607.10371](https://arxiv.org/html/2607.10371) · [huggingface.co/ai-sage/GigaAM-Multilingual](https://huggingface.co/api/models/ai-sage/GigaAM-Multilingual) |
| **ElevenLabs Scribe v2** (incumbent) | **"Good (>10% to ≤20% WER)"** — the only *hosted-vendor* Uzbek accuracy figure in existence | **$0.22/hr** = $0.00049 per 8 s chunk | **Keep it.** Best-documented hosted Uzbek STT, cheapest, already integrated. Add **keyterm prompting (+$0.05/hr = +$0.0001/call)** to prime the recogniser with the expected name | [elevenlabs.io/docs/capabilities/speech-to-text](https://elevenlabs.io/docs/capabilities/speech-to-text) |
| Google chirp_2 / chirp_3 | None published | $0.016/min = $0.96/hr (**tier confirmed for `chirp` only; chirp_2/3 appear nowhere on the pricing page**) | Worth a bake-off for **one reason**: model adaptation lets you bias the recogniser toward the recipient's name. 4× Scribe's price with no published WER | [docs.cloud.google.com/speech-to-text/pricing](https://docs.cloud.google.com/speech-to-text/pricing) |
| AssemblyAI | **"Fair accuracy (>50% WER)"** | $0.15/hr | **Disqualified.** A >50% WER recogniser cannot gate a 0.85-similarity check — it would fail correct songs and burn all 3 attempts | [assemblyai.com/docs/…/supported-languages](https://www.assemblyai.com/docs/speech-to-text/pre-recorded-audio/supported-languages) |
| Whisper large-v3 | **WER 105.4 / 109.9 / 120.6** | — | **Above 100% WER. Not weak — unusable.** Reject any "just use Whisper" suggestion outright | [arxiv.org/html/2607.10371](https://arxiv.org/html/2607.10371) |
| Deepgram, Speechmatics | No Uzbek in any model | — | Out on the language gate | [developers.deepgram.com](https://developers.deepgram.com/docs/models-languages-overview) · [docs.speechmatics.com](https://docs.speechmatics.com/introduction/supported-languages) |

**Text-to-Speech (the greeting) — ElevenLabs scores zero, so everything beats it:**

| Vendor | Uzbek grade | Voices | Price | Deterministic pronunciation control? |
|---|---|---|---|---|
| **ElevenLabs `eleven_v3`** | **NONE — Uzbek absent entirely** | 0 Uzbek | $0.10/1k | n/a. **The RU/EN-only greeting is a vendor limitation, not a design choice** ([elevenlabs.io/docs/models](https://elevenlabs.io/docs/models)) |
| **Microsoft Azure** | claimed-in-docs | **`uz-UZ-MadinaNeural` (F) + `uz-UZ-SardorNeural` (M)** — the only vendor offering both genders | **$0.015 / 1k chars** (~7× cheaper than ElevenLabs) | **NO — footnote 3: "Phonemes, custom lexicon, and visemes aren't supported."** For a product about saying a name correctly, that removes your only deterministic fix | [MicrosoftDocs/azure-ai-docs tts.md](https://raw.githubusercontent.com/MicrosoftDocs/azure-ai-docs/main/articles/ai-services/speech-service/includes/language-support/tts.md) · [prices.azure.com](https://prices.azure.com/api/retail/prices) |
| **Aisha AI** (Tashkent) | **demonstrated** (playable samples) | 1 voice, "Gulnoza", female only; 1,000-char cap with API key | **1 UZS/char ≈ $0.085/1k** at CBU 11,795 UZS/USD | **Billed in UZS — no FX rail, no geo-block, no card-decline risk.** Resale terms **unverified and silent on both their pricing page and API reference** — ask in writing | [aisha.group/en/pricing](https://aisha.group/en/pricing) |
| **Navoiy TTS** (aisha-org, **apache-2.0**) | **demonstrated** (9 emotion-labelled Uzbek demo WAVs) | Voice cloning in scope (CosyVoice2-0.5B base, 600 h Uzbek) | $0 | Ships **`uztts/normalize.py`** — the only Uzbek-specific text normaliser found in any vendor or repo. **Read it before writing your own U+02BB logic.** Vendor's own warning: "can mispronounce names, loanwords, abbreviations" | [huggingface.co/aisha-org/navoiy-tts](https://huggingface.co/api/models/aisha-org/navoiy-tts) |
| Yandex SpeechKit | claimed-in-docs | 3 voices — **all female** | **$0.011/1k** (cheapest anywhere) | Payment rail + political optics risk for a Tashkent consumer brand; SSML phoneme support for Uzbek unconfirmed | [aistudio.yandex.ru/docs/en/speechkit/tts/voices.html](https://aistudio.yandex.ru/docs/en/speechkit/tts/voices.html) |
| Narakeet | demonstrated | **64 Uzbek voices**, M+F | $0.20/min output = **18× Azure** | Backing engine undisclosed — plausibly resold Azure. **Use to audition, never to ship** | [narakeet.com/languages/uzbek-text-to-speech/](https://www.narakeet.com/languages/uzbek-text-to-speech/) |
| CAMB.AI MARS8 | claimed-in-docs | first-party Uzbek page, **but every sample on it is English** | unverified | "150+ languages" with no Uzbek demo is the pattern that produces Turkish-accented gibberish on `oʻ`/`gʻ`. One afternoon moves it to demonstrated or excluded | [camb.ai/text-to-speech/uzbek](https://www.camb.ai/text-to-speech/uzbek) |
| Google TTS, Amazon Polly, OpenAI TTS | **none** | 0 Uzbek voices (verified by grepping the full voice lists) | — | Out |
| facebook/mms-tts-uzb | claimed | Cyrillic script only, no Latin variant exists | $0 | **cc-by-nc-4.0 — non-commercial. Hard blocker for a paid kit.** Ignore this branch | [huggingface.co/facebook/mms-tts-uzb-script_cyrillic](https://huggingface.co/api/models/facebook/mms-tts-uzb-script_cyrillic) |

**Blunt verdict on voice:** **Keep Scribe v2 for verification** (cheapest, best-documented hosted Uzbek WER, already integrated) and evaluate GigaAM as a self-hosted upgrade if measured accuracy on *sung* names is inadequate. **Do not use ElevenLabs for an Uzbek greeting — it cannot produce one.** If the greeting SKU returns in Uzbek, the shortlist is Azure (both genders, $0.015/1k, but no pronunciation override) and Aisha (UZS billing, one female voice, unverified resale terms).

---

## 7. What to do next — ranked

| # | Action | Cost | Time | Resolves |
|---|---|---|---|---|
| **1** | **THE CHEAPEST EXPERIMENT THAT SETTLES THE BIGGEST UNKNOWN.** On a live Starter account: record the credit/USD balance, run **one 90,000 ms compose call**, read the delta on **Developers → Usage analytics** (which breaks down by product and API key). Then force a 5xx failure, then run a deliberate re-roll, then run an inpaint of one chunk, reading the delta each time. | **~$1** | **~20 min** | **Four undocumented facts at once:** (a) A2 sub-minute rounding — a ±25% COGS swing; (b) whether failed generations bill; (c) whether API re-rolls bill; (d) **whether inpainting bills per-chunk — which could cut the retry tail ~5×.** No public page will ever tell you any of this |
| **2** | **The Uzbek bake-off.** Same Uzbek lyrics containing `Gʻulomjon` and `Oʻktam` (U+02BB intact) through: Eleven Music v2 · WaveSpeed ACE-Step 1.5 (**$1 free credit, no card**) · Replicate ACE-Step with **`Uzbek` in the `# Languages` conditioning slot** · Lyria 3.5. Score the sung output against the input text with GigaAM-Multilingual + one native speaker. | **<$5** | 1 afternoon | The **only** thing that can promote any music vendor above *unlisted*. Unlocks an **11× COGS reduction** ($0.30 → $0.027) if ACE-Step passes. Nobody has ever tried putting "Uzbek" in that conditioning slot |
| **3** | **Fix the LLM config — it is currently broken on both axes.** `google/gemma-4-31b-it:free` lists `response_format` but **NOT `structured_outputs`**, so your REQUIRED strict-JSON schema is unenforced (this is almost certainly why `llm_parse_max_attempts` exists). It also scores **0.5535 on UzLiB — below the 0.5894 human baseline**. The configured fallback `glm-5.2:free` (0.5384) is worse on Uzbek but *does* support structured outputs — the fallback is stricter than the primary, backwards. Swap to primary `google/gemini-3.7-flash` (UzLiB **0.8092**, 2nd of 67), fallback `openai/gpt-5.6-luna` (**0.7141**, best non-Google, different vendor family so a genuine failure domain). | +$0.006/order (**1.4% of COGS**) | 1 hour | Product quality on the one thing customers pay for |
| **4** | **Pin the provider on every structured call.** `structured_outputs` is an **endpoint** property, not a model property. Set `provider.only` or `provider.require_parameters: true`. **[E] found the report's own recommendation has this bug: `gpt-5.6-luna`'s Amazon Bedrock endpoint is $0.22/$1.32 with `structured_outputs: false`.** Also verified: glm-5.3-flash has it on DeepInfra but not GMICloud/Novita; deepseek-v4-flash-0731 has it on Baidu/OpenInference but not Relace; claude-opus-5 has it on Azure but not the Google endpoints. | $0 | 30 min | Silent schema failures your parse-retry counter absorbs invisibly |
| **5** | **[E] BONUS — halve the LLM bill for free.** The three Gemini 3.7 Flash price tiers are **service tiers, not context-length tiers** (raw endpoint tags: `google-vertex/global/flex` $0.375/$1.875, `.../global` $0.75/$3.75, `.../global/priority` $1.35/$6.75 — all six endpoints report identical 1,048,576 context). Pin **flex** and the LLM line drops from $0.0064 to $0.0032/order regardless of prompt length. | −$0.003/order | 10 min | Corrects the earlier "batch/short-context vs long-context" guess |
| **6** | **Resolve the licence before you scale, not after.** Reseller Rights are **Prohibited on all six self-serve tiers**; Free/Starter/Creator/Pro are **"For Individual Use Only"** and enrolling ineligibly risks "suspension or termination… and/or loss or forfeiture of Outputs, fees, and/or credits." Either (a) contact ElevenLabs sales for **Enterprise Music** (the only route to lawful resale, pricing not public), or (b) move music to **Replicate ACE-Step**, whose ToS §5.1 explicitly assigns output rights for "commercial purposes such as sale" over MIT-licensed weights — **conditional on action 2 passing**. | Legal time | — | The single largest existential risk in this report — larger than every COGS line combined |
| **7** | **Pick the tier now, knowing Starter is a toy.** 17 min/mo generation cap = **~7 delivered kits at 1.5 attempts ≈ $41 revenue ceiling**. Move to Creator ($22, ~27 kits) or Pro ($99, ~135 kits) before launch; Scale ($299) the moment an entity — not an individual — is the account holder. | $6→$299/mo | — | Hitting a contractual cap mid-launch with paid orders queued |
| **8** | **Normalise `U+02BB` / `U+2018` / ASCII apostrophe on the way IN** to every LLM and TTS call. Models treat all three as different tokens, hurting prompt-cache hits and few-shot consistency. **Read `uztts/normalize.py` from Navoiy TTS first** — it is the only purpose-built Uzbek normaliser found in any repo. | $0 | 2 hours | The root cause of the whole verification loop |
| **9** | **Turn on Scribe keyterm prompting** (+$0.05/hr = **+$0.0001 per 8 s call**) to prime the recogniser with the expected name before verifying. | +$0.0001/kit | 1 hour | Plausible direct lever on the `Gʻulomjon` failure — economically free |
| **10** | **Filter the lyric-writing prompts.** Now that customers write their own lyrics (commit `95fb8ff`), Music Terms §2(b) bans submitting **any artist's real or stage name, songwriter name, song title, album title, publisher or label name, or "a substantial or distinct portion of any song's lyrics."** Enforce in the intake-normalisation job. | $0 | 3 hours | "Material failure to adhere is deemed a breach of your agreement" |
| **11** | **Test a real Uzbek card at every vendor before depending on it.** **Every "payable from UZ" claim in this research is HTTP reachability only** — no account was created and no card charged anywhere. ElevenLabs explicitly warns: "While you can try using a prepaid card, it is not something we directly support. We have encountered issues with the issuing banks and Stripe blocking such payments." A declined renewal drops you to Free, where **music concurrency is 0 and the API stops entirely.** Sonauto/Treblo already 403s a Tashkent IP, so the geo-block risk is proven, not hypothetical. | ~$30 | 1 day | Silent production outage |
| **12** | Keep `model_id=music_v2` pinned. **"For API generations, Music v1 will remain the default model for transition period."** Omitting it silently gets you v1. | $0 | — | Already correct in the codebase — do not "clean up" this line |
| **13** | If the greeting SKU returns: **do not use ElevenLabs for Uzbek** (no voice exists). Synthesise the same Uzbek sentence containing `Gʻulomjon`/`Oʻktam` on Azure Madina, Azure Sardor, Yandex yulduz, Aisha Gulnoza and self-hosted Navoiy; have a native speaker rank them. **That one afternoon is worth more than every roster in §6b.** | <$5 | 1 afternoon | No published MOS or listening test for Uzbek TTS exists from **any** vendor. Anyone who tells you which sounds best is giving you an opinion |
| — | *Time-boxed, low confidence:* a banner on `/pricing/api` today reads **"Get 50% off TTS API pricing — for life. Subscribe before September 11."** Terms are not on the page and the flow needs auth. **Do not model TTS at $0.05/1k on the banner alone**, but if the greeting SKU is coming back, it is worth 15 minutes to chase. Appears not to touch music pricing. | — | 15 min | — |

---

## 8. Unverified / open questions

### Tier 1 — material to COGS, closable in under an hour

| Open question | Impact | Why it's open | How to close |
|---|---|---|---|
| **Music billing granularity (A2)** — is 90 s billed as 1.5 min or 2 min? | **±25% of COGS** | **Two live vendor pages contradict each other on the same day:** `/pricing/api` groups Music with Sound Effects as "billed **per generation**"; `/pricing` says Music is "900 credits **per minute**" and only Sound Effects is per-generation. No rounding rule stated anywhere. The eleven_music tooltip is minute-denominated while the sound_effects tooltip gives explicit per-second granularity — weak evidence *against* sub-minute music billing | Action 1: one 90,000 ms call, read the Usage-analytics delta |
| **Is a failed (5xx) generation billed?** | Unknown tail | Genuinely undocumented. [A] searched the errors doc, billing docs, PAYG docs, usage-analytics docs, both pricing FAQs and the full `/docs/llms-full.txt` | Action 1 |
| **Is an API re-roll billed?** | Up to **+196% COGS** | Strongly implied but never stated **for music**. The only vendor statement names TTS, STS and Studio only, and carves out API entirely. Music is not mentioned in that article at all | Action 1 |
| **Does inpainting bill per-chunk or per-track?** | Could cut the retry tail **~5×** | The inpainting guide documents generation-chunks vs audio-reference-chunks in full with **zero billing language**. The chunk architecture makes chunk-only billing the natural implementation — but no page confirms it. **The single highest-value thing to measure** | Action 1 |
| **The "variants" cost multiplier** | Unquantified | Vendor help centre: cost "depends on the length of your track **and how many variants you're generating**." The compose endpoint exposes no variants parameter, so the API path is presumed 1:1 — but UI-derived credit deltas will be off by the variant count | Action 1; read the compose response payload |

### Tier 2 — material to the product's core promise, closable in one afternoon

| Open question | Why it's open | How to close |
|---|---|---|
| **Does ANY music model sing Uzbek acceptably?** | **No vendor names Uzbek. No published Uzbek WER or MOS exists for any singing model, from anyone.** ACE-Step's "50+ languages" is never enumerated on any vendor surface; GitHub code search needs auth so its accepted language tokens could not be confirmed. ACE-Step's own demo page flags "Multilingual Lyrics Compliance" as a **future goal** | Action 2 |
| **Does ACE-Step's `# Languages` slot accept "Uzbek"?** | Only visible via Replicate's embedded example prediction log; whether it is an in-vocabulary conditioning value or free text is unknown | Action 2 |
| **Suno's actual Uzbek pronunciation quality** | Audio exists and was structurally verified (ffprobe), but **nobody listened**. Graded "demonstrated" strictly in the sense that auditable audio exists — **not** that it sings Uzbek well. The only Uzbek-language review is negative on pronunciation | Listen. It is unshippable regardless (no API), so its only role is as a quality ceiling for action 2 |
| **STT accuracy on a name SUNG OVER MUSIC** | **Every Uzbek WER in this report is read speech in quiet conditions.** No benchmark in any language covers a sung name over a backing track. The 0.85 similarity threshold rests on nothing measured | Sample 30 real orders, hand-label, measure the true first-pass rate — which also fixes the 1.0/1.5/2.5 assumption in §2 |
| **Uzbek Cyrillic path is entirely untested** | UzLiB normalises to Latin script. Your 918-byte `uz-Cyrl` lang pack is unmeasured against every number in §6 | Hand-grade ~20 Cyrillic lyric generations before launch |
| **Uzbek TTS naturalness** | **No published MOS, naturalness score or A/B listening test for Uzbek TTS from ANY vendor** — not Azure, Yandex, Aisha or CAMB.AI. The closest academic work is corpus-building, not vendor comparison | Action 13 |
| **How any vendor handles U+02BB** | Undocumented everywhere. Two hard findings bear on it: Azure explicitly does **not** support phonemes/custom lexicon/visemes on Uzbek voices, so no deterministic override exists there; and Navoiy's `uztts/normalize.py` is the only Uzbek normaliser in any repo | Action 8 |

### Tier 3 — commercial and legal, need a human, not a fetch

| Open question | Why it matters |
|---|---|
| **Does this bot constitute "reselling" under §5(f)?** | A legal determination, not a published fact. The clause is verified verbatim; its application is not something any vendor page resolves. **"Material failure to adhere is deemed a breach of your agreement."** |
| **Enterprise Music / Enterprise Music Lite pricing** | "Contact Us for Details," Custom generation limits, Custom reseller rights. **This is the only route to lawful resale AND to lifted generation caps, so the monthly floor for a fully compliant version of this business is unknown.** Must come from ElevenLabs sales |
| **Aisha AI's resale / output-ownership terms** | The vendor most worth switching to for an Uzbek greeting, and the one whose terms could **least** be verified — both their pricing page and machine-readable API reference are silent. **Ask in writing before shipping** |
| **Resale terms for Azure, Yandex, Google, Narakeet, CAMB.AI, AssemblyAI** | Not fetched, not asserted. Only three are settled: ElevenLabs (paid users may use output commercially; "you retain all rights in and to your Output"), Navoiy TTS (apache-2.0), GigaAM (MIT) — and one is a hard blocker: facebook/mms-tts-uzb (cc-by-nc-4.0) |
| **Card acceptance from Uzbekistan — every vendor** | **All "payable" claims across [A][C][D] are HTTP reachability only**, tested from a verified Tashkent IP (82.215.114.97, AS12365 Sarkor Telecom). No account created, no card charged anywhere. Reachability ≠ payment acceptance. Azure "Uzbekistan" appears in the free-account country list; Yandex has no UZ entity and requires non-Russian-bank cards; Mureka's region gate does not fire **pre-auth** (401 not 403) but a key-bearing request was never made |
| **OpenRouter country restrictions for Uzbekistan** | Their FAQ defers to ToS/support. Given the geo-blocking already hit elsewhere, confirm with OpenRouter support before migrating the paid path |
| **The "50% off TTS for life" promo** | Live banner, 11 September deadline, terms not on the page, flow requires auth |

### Tier 4 — could not be resolved from any public page

- **GPU rates for self-hosting** — Vast.ai's pricing page serves a JS dashboard with no numeric rates in the served HTML; no static table exists.
- **MiniMax-Music3 / HeartMuLa / ACE-Step per-track runtime** — no published RTF, per-song latency or reference GPU timing. Without a runtime figure, self-hosted cost per track **cannot be derived at all**. The 30–60 s cold-start used elsewhere to bracket it is an engineering estimate, not a fetched number, **and it is the dominant term** (moves per-track cost from ~$0.002 to ~$0.013).
- **fal.ai price for MiniMax Music 3** — injected client-side; four candidate JSON endpoints all 404.
- **PiAPI ACE-Step price** — two PiAPI-hosted surfaces disagree by **10×** ($0.00005/s vs $0.0005/s). No tiebreaker.
- **Mureka price per track** — unverifiable from any readable vendor page; circulating figures are JS-bundle artefacts.
- **Google chirp_2 / chirp_3 pricing tier** — the Standard-model footnote enumerates `chirp` only; `chirp_2` and `chirp_3` appear **nowhere** on the pricing page, yet they are the models that support `uz-UZ` with model adaptation.
- **Yandex async STT price** — rendered as "$0.0012418035 per second" (= $4.47/hr, implausibly 14× its own streaming rate); the page is behind SmartCaptcha and could not be re-checked. Treat the synthesis price as solid, async STT as garbled.
- **Narakeet per-tier rates** — the price table renders as "…" unauthenticated; the only dollar figure in the HTML is an FAQ line ($0.20/min on the $6 package). Larger packages are probably cheaper.
- **Cartesia / Rime / Fish Audio / PlayHT language rosters** — Cartesia redirects to auth login; the other three serve JS shells. Graded **unknown**, not excluded, because no fetched page says Uzbek is absent.
- **Mohir AI** — `mohir.ai` has **no DNS record** (`getaddrinfo ENOTFOUND`). Successor `uzbekvoice.ai` and `Muxlisa.uz` both serve JS shells whose entire extractable text is their own brand name. Anyone quoting Mohir AI prices today is quoting from memory. Reachable by email, possibly.
- **Structured-output *reliability*** (as opposed to declared support) — `supported_parameters` is a capability declaration, not a measured schema-adherence rate. No source measures strict-JSON conformance under `response_format` for any of these models, on Uzbek content or otherwise.
- **Per-order token counts** — DERIVED from your supplied byte sizes at A1's assumed 3 bytes/token, with an assumed 1,500-byte respell prompt and assumed output lengths. **Meter one real order before budgeting.**
- **Reconciliation of ElevenLabs' two meters** — the API page's "minutes included" (Starter 40) and the credit path (30,000 ÷ 900 = 33.3 min) disagree, and the plan cards encode a third, non-constant set (implied 2,000–3,947 credits/min). Model the API path in **USD only**, as `/pricing/api` instructs: "API usage is billed in US dollars, not credits."

---

## The one-paragraph version

At $5.90, **COGS is $0.46 and gross margin is 92%** at a realistic 1.5 generation attempts; the retry loop would need to run 6.5× past its own hard cap to threaten profitability, so **stop treating re-rolls as a financial risk**. The entire LLM stack is 1.4% of COGS — buy the good model (`gemini-3.7-flash`, UzLiB 0.8092) and stop economising on the one thing the customer is paying for, because both currently-configured free models score **below the human baseline on Uzbek** and the primary cannot even enforce your required JSON schema. The real risks are not per-unit costs: they are (1) **ElevenLabs' contractual generation cap**, which limits Starter to ~7 delivered kits/month and ~$41 of revenue; (2) **Reseller Rights being "Prohibited" on every self-serve tier**, with Free through Pro additionally "For Individual Use Only"; and (3) the fact that **no music vendor on Earth publishes any evidence of singing Uzbek** — ElevenLabs and the 11×-cheaper ACE-Step sit on identical, empty evidence, which two cheap experiments (a $1 billing probe and a $5 Uzbek bake-off) would resolve in a single afternoon.