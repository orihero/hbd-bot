# Benchmark — AI song generation for Uzbekistan

**Compiled 27 August 2026.** This measures what vendors *document*: whether a self-serve API exists today, what one ~2-minute sung track costs from a primary pricing page, whether exact lyrics can be supplied, whether one section can be re-rendered without re-rolling the whole track, what the written licence says about reselling the output, and whether an operator in Uzbekistan can pay for it.

**What was NOT measured: no audio was generated.** Nothing here is a listening test. Not one vendor in this survey has a demonstrated, auditable sample of sung Uzbek, and this report does not produce one. Every "Uzbek (sung)" cell below is a statement about documentation, not about sound. The final section is a runnable protocol for closing that gap in a day; until it runs, sung Uzbek is unmeasured for the entire market.

Prices carry a source link. Where a figure could not be re-derived from a vendor-hosted page it says **unverified** — that is a legitimate result, not a hole. Three adversarial audits corrected the underlying survey; where an auditor overturned a claim, the auditor's value is used.

---

## The verdict up front

**Take ElevenLabs Eleven Music as the day-1 hosted engine, and treat its licence as an open pre-launch question rather than a settled one.** It is the only vendor that is simultaneously a GA self-serve first-party API, documented for exact lyrics *and* section-level inpainting, confirmed payable from Uzbekistan by card, and — critically — one whose Uzbek roster is *withheld* rather than *published-and-exclusionary*, which is the only remaining place Uzbek could hide. **Runner-up: Mureka**, which assigns you outright ownership of the output, ships region-edit plus per-word timestamps, and is the only vendor on earth that affirms sung **Russian** in writing — held back by an Uzbek exclusion in its own FAQ, an unverifiable price, and an undocumented region allow-list that 403s. The one thing that would change the answer: if the bake-off shows ElevenLabs cannot land an Uzbek name and **ACE-Step 1.5** (MIT weights, seeded, repaint-capable, no payment rail at all) can — then the engine moves in-house, because that is also the only route where the product's promised free re-renders are literally free.

---

## Scorecard

| Vendor | API | $/2-min track | Uzbek (sung) | Exact lyrics | Section re-gen | Resale licence | Payable from UZ | Verdict |
|---|---|---|---|---|---|---|---|---|
| ElevenLabs Eleven Music | GA | [$0.30](https://elevenlabs.io/pricing/api) | unlisted | yes | yes (v2) | conditional | yes | **PICK** |
| Mureka (V9.5) | GA | unverified | no | yes | yes | conditional | untested (403 risk) | RU/EN SKU |
| ACE-Step 1.5 (self-host) | weights | ~$0.001 | unlisted | yes | yes (repaint) | [MIT](https://huggingface.co/ACE-Step/Ace-Step1.5) | n/a — no rail | reserve |
| Google Lyria 3 Pro | preview | [$0.08](https://ai.google.dev/gemini-api/docs/pricing) | no | yes | **no** | conditional | untested | EN only |
| HeartMuLa-oss-3B (self-host) | weights | ~$0.011–0.08 | claimed | yes | no | [Apache-2.0](https://github.com/HeartMuLa/heartlib) | n/a | bench only |
| MiniMax music-1.5 via Replicate | GA | unverified (~$0.03) | no | yes | no | conditional | untested | no |
| DiffRhythm2 (self-host) | weights | ~$0.002 | no | yes (LRC) | no | [Apache-2.0](https://huggingface.co/ASLP-lab/DiffRhythm2) | n/a | no |

Cell notes: "unlisted" = Uzbek neither named nor excluded on any vendor page. "no" = the vendor publishes a roster that omits Uzbek. **No vendor scores "demonstrated" or "claimed-in-docs"** — see *The Uzbek problem*. "conditional" resale licence means the grant exists but carries a duty (co-branding, quota, eligibility) or a carve-out that bites this specific business.

---

## Detail table

| Vendor | Max duration | Concurrency | Latency | Output format | Watermark | Price change scheduled |
|---|---|---|---|---|---|---|
| ElevenLabs Eleven Music | **conflicting**: 600 s ([API ref](https://elevenlabs.io/docs/api-reference/music/compose), [API page](https://elevenlabs.io/eleven-music-api)) vs 300 s ([pricing](https://elevenlabs.io/pricing/api), [capabilities](https://elevenlabs.io/docs/overview/capabilities/music)); chunks 3–120 s, ≤30/plan | Free 0 / Starter 2 / Creator 2 / Pro 2 / Scale 5 / Business 5 ([models](https://elevenlabs.io/docs/overview/models)) | **unverified** — no figure, no SLA anywhere; `/v1/music/stream` + SSE mitigate | mp3 44.1k/128 (v1 default), mp3 48k/192 (v2), pcm, opus; stems endpoint paid-only; word timestamps | **unverified** — none documented for Music (documented only for Dubbing) | none announced; a past cut (up to 50% API) landed with [music_v2, 26 May 2026](https://elevenlabs.io/blog/introducing-music-v2) |
| Mureka | 330 s (BGM 270 s); lyrics ≤5,000 chars | bought with top-up tier; `concurrent_request_limit` on `/v1/account/billing` (docs example 5) | **unverified** — no SLA, no p50/p95; async poll + optional stream | MP3 + FLAC + WAV, URLs valid 30 days; per-section/line/**word** timestamps included | none documented (absence of a statement, not a denial) | **claimed** 28 Aug 2026: $0.045 → $0.15/song — **UNVERIFIED**, see corrections. [§7.2 allows changes on 14 days' notice](https://platform.mureka.ai/service_terms.pdf) |
| ACE-Step 1.5 | 600 s ([paper](https://arxiv.org/abs/2602.00744)); hosted WaveSpeed caps 240 s | self-provisioned; ≤6 GB VRAM runs 2B-turbo, XL 4B needs ≥12–20 GB | <2 s/full song on A100, <10 s on RTX 3090 (vendor paper; excludes cold start) | **unverified** — no sample rate or container stated in repo, HF card or guide | none (self-hosted, you own the pipeline) | none — MIT weights cannot be repriced; [GPU host rates](https://www.runpod.io/pricing) can |
| Google Lyria 3 Pro | 184 s hard ceiling; no numeric duration param | 10 RPM per base model on Vertex; **unpublished** on the [Gemini API rate-limit tables](https://ai.google.dev/gemini-api/docs/rate-limits) | **unverified** — no p50/p95/SLA; Google's own hint is that Clip is "the faster" model | MP3 44.1 kHz / 192 kbps stereo; WAV per Gemini docs (Vertex card says MP3 only — surfaces disagree); 1 clip/prompt, no stems | **mandatory** SynthID audio watermark + C2PA Content Credentials, no opt-out | none on the Lyria rows; the "through 31 Dec 2026" doubling applies to Gemini **text** rows only ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) |
| HeartMuLa-oss-3B | **unverified** | self-provisioned; repo recommends multi-GPU | RTF ≈ 1.0 → ~120 s GPU per 2-min track | **unverified** | none | none |
| MiniMax music-1.5 via Replicate | 240 s ([model page](https://replicate.com/minimax/music-1.5)) | **unverified** — Replicate rate-limit docs did not render | ~28 s (one embedded example prediction; not a p95) | mp3/wav/pcm, 44.1 kHz, up to 256 kbps; no stems | undisclosed by Replicate; [MiniMax terms](https://www.minimax.io/audio/doc/terms-of-service-music.html) reserve non-removable identifiers | none announced; upstream [closed to new users 20 Aug 2026](https://platform.minimax.io/docs/guides/pricing-paygo) |
| DiffRhythm2 | 285 s | self-provisioned; 8 GB VRAM min | "blazingly fast", **no figure published** | **unverified** | none | none |

**Market-wide gap:** no vendor publishes a **retry-billing policy**. Every price above is a first-attempt price. For a product whose headline promise is free re-renders, attempts-per-delivered-kit is the largest missing COGS input in this table — larger than any individual price dispute.

---

## What the scores actually mean

### 1. ElevenLabs Eleven Music — the pick

**Wins on:** the richest lyric-control surface in the market, and it is better than the project's own decision record believes. `composition_plan` gives an ordered list of up to 30 chunks, each with literal lyric lines, a `duration_ms` between 3,000 and 120,000, per-chunk positive/negative styles and `context_adherence` — so the recipient's name can be pinned to a named section at a known millisecond offset. Section-level regeneration is **fully documented**, with a dedicated [inpainting guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/music/inpainting): `compose_detailed(store_for_inpainting=True)` returns a `song_id`, and a subsequent `music_v2` plan mixes untouched audio-reference chunks with generation chunks that re-render only the bad line, with `conditioning_ref`/`condition_strength` to keep the seam musical. Price is hard: [$0.150/min on every tier](https://elevenlabs.io/pricing/api), re-derivable two ways (stated rate, and "minutes included" = plan fee ÷ $0.150 for all six tiers), so $0.30 per 2-minute track with no volume discount ever. Uzbekistan is not on the [restricted list](https://help.elevenlabs.io/hc/en-us/articles/22497891312401) and billing is card-only, which is exactly the rail a UZ operator has.

**Killer flaw:** the licence is built for individuals, not for a company reselling songs, and three separate clauses bite. (a) [Music API Terms §4.A](https://elevenlabs.io/music-api-terms) obliges a "Pure-play Music AI Creation Company" — defined as an entity whose primary commercial product is AI-generated sound recordings — to *prominently co-brand* with "powered by ElevenLabs" across the product **and all promotional content**; unlike the "Reseller" definition, this one has **no substantial-added-functionality carve-out**, so lyric authoring and spoken greetings do not exit it. (b) [ElevenLabs never assigns or grants ownership of Output anywhere](https://elevenlabs.io/terms-of-use) — across all four instruments the only operative language is a revocable, plan-conditioned permission to "use such Output outside of the Services", while [Music Terms §3](https://elevenlabs.io/music-terms) expressly disclaims warranties of **title and non-infringement** and states output "may be similar or identical to Output returned to other users". (c) The [Music Commercial Rights table](https://elevenlabs.io/eleven-music-model-specific-terms) is contractually *incorporated* (§1(b): non-adherence "will be deemed a breach"), and it caps Starter at 17 minutes generated / 30 minutes downloaded per month — about 15 saleable kits — while marking Free/Starter/Creator/Pro "For Individual Use Only" and Reseller Rights "Prohibited" on every self-serve tier through Business.

**Switch away when:** the bake-off shows it cannot land an Uzbek name at ≥80% and something else can; **or** ElevenLabs confirms in writing that a UZ company selling kits is a pure-play requiring co-branding *and* the founder judges a permanent third-party brand on a $5.90 gift unacceptable; **or** the 17-min Starter cap is confirmed to bind API usage and the entity-eligible floor really is Scale at $299/mo, which converts a $6 line item into a $299 one before the first sale.

### 2. Mureka — the runner-up, and the Russian answer

**Wins on:** the strongest ownership text of any hosted vendor — [API Service Agreement §3.2](https://platform.mureka.ai/service_terms.pdf): "you (a) retain all ownership rights in Input and (b) own all Output. We hereby assign to you all our right, title, and interest, if any, in and to Output," plus §3.3 no-training-on-customer-content and §2 containing **no resale bar and no competing-product bar**. It ships `POST /v1/song/region-edit` (song_id + edit_start/edit_end in ms + replacement lyrics, region ≥3 s) as a first-class GA endpoint, and returns per-**word** start/end timestamps on every generation — meaning you can locate where the name landed automatically and re-render only that region. And its [FAQ](https://platform.mureka.ai/docs/en/faq.html) names Russian on the sung roster: it is the **only vendor in this entire survey that affirms sung Russian in writing**, where ElevenLabs' Russian is pure inference.

**Killer flaw:** the same FAQ is a closed 10-language list — Chinese, English, Japanese, Korean, Portuguese, Spanish, German, French, Italian, Russian — with **no Turkic language of any kind**. That is the single hardest primary-source Uzbek negative in the market. Two secondary flaws compound it: the price is **unverifiable** (the $0.045→$0.15 figures come from a minified JS bundle, not a readable page; four candidate prices circulate with no primary confirmation), and the [error-codes page](https://platform.mureka.ai/docs/en/error-codes.html) documents a `403 — you are accessing the API from an unsupported region` while publishing **no supported-region list**, so Uzbekistan's access is unknown. Credits are non-refundable and expire 12 months from last top-up. Also, the §10.1 indemnity the survey praised is largely hollow here: it carves out "(d) Claims related to Customer Applications" and "(e) trademark or related rights violations based on your use of Output in trade or commerce" — and the agreement defines a Customer Application as exactly what this bot is.

**Switch away when:** a smallest-possible top-up from a UZ egress IP returns 403; **or** the Russian bake-off arm shows ElevenLabs matches it, at which point the second vendor stops earning its integration cost.

### 3. ACE-Step 1.5 — the strategic reserve, and the cost ceiling

**Wins on:** it is the only route in the entire survey with **no payment rail to fail** — free ungated weights, <4 GB VRAM, <10 s per full song on an RTX 3090, meaning a single consumer GPU box physically in Tashkent runs the whole engine with no card, no forex, no geo-block, and no ToS counterparty between you and your customer. **[MIT on both code and weights](https://huggingface.co/ACE-Step/Ace-Step1.5)** — cleaner than Apache-2.0 for resale, and the only shortlisted route with **no in-product attribution duty** (ElevenLabs' co-branding, Stability's "Powered by Stability AI", and MiniMax-Music3's UI-branding clause all put a third-party brand on a consumer gift). It has repaint mode (regenerate a start/end region only) **and explicit seed control**, so a name re-render is a controlled retry rather than a fresh lottery ticket — the only place in the market where both exist together. On self-hosted GPU a re-render costs ~$0.001, which is the only configuration where "free re-renders when a name is mispronounced" is literally free rather than a margin hole.

**Killer flaw:** Uzbek is not in its published list, nobody has ever demonstrated it singing Uzbek, and there is no phonetic control to force the issue — so as the primary it is a bet on an untested capability. Turkish *is* named in its [musicians' guide](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/ace_step_musicians_guide.md), which is tempting, but the adjacency argument is weak: Turkish Latin has no oʻ/gʻ digraph and no U+02BB, so Turkish orthographic competence transfers nothing to the exact character-level failure this product faces. Second flaw: it converts a variable per-track cost into a fixed floor — a dedicated always-on RunPod Community RTX 4090 is [$0.34/hr ≈ $245/month](https://www.runpod.io/pricing) regardless of volume, which only beats a $0.05/track hosted API above roughly 4,900 tracks/month, plus real ops (CUDA pinning, cold starts, queueing, on-call at 3am on someone's birthday). Third: MIT licenses the *weights*, not the *corpus* — the "licensed, royalty-free, and synthetic sources" claim on the model card is unaudited and uninsured.

**Switch to it when:** the bake-off shows a ʻ-free or Cyrillic respelling lands the Uzbek name reliably here and nowhere hosted; **or** volume crosses ~5,000 tracks/month; **or** ElevenLabs' co-branding/eligibility answer comes back unacceptable.

---

## Disqualified, and why

| Vendor | Reason | DECISIONS.md rejection still correct? |
|---|---|---|
| Suno (first-party) | No public API. [1 July 2026 the CPO announced only that Suno is *exploring* one](https://www.digitalmusicnews.com/2026/07/03/suno-is-opening-an-api-partner-program/), curated partners, no docs, no timeline. ToS bars Output used "to create a competing product or service" — twice. | **Yes**, and harder than before |
| Suno via kie.ai / sunoapi.org / MusicAPI.ai / apiframe | No licence at either end. kie.ai/terms, /terms-of-service, /legal/terms, sunoapi.org/terms and docs.sunoapi.org/terms all **404 on live check today** — there is no written instrument to inherit. Upstream, [Suno's help centre now gates commercial rights on a metered official download](https://help.suno.com/en/articles/13614785): Pro 20/mo, Premier 60/mo, retroactive from 3 Sept 2026, i.e. $0.40/track. A wrapper claiming $0.03 sits 13x below that floor. Add [in-waveform watermarking + fingerprinting announced 6 Aug 2026](https://techcrunch.com/2026/08/06/amid-legal-battles-suno-says-it-will-start-watermarking-songs/) — unstrippable, unlike the ID3 bytes that unmasked the competitor. | **Yes.** Use only as an unpriced internal benchmark; never ship a file |
| Udio | [Vendor's own help centre: "we don't currently offer a public API"](https://help.udio.com/en/articles/10756277-udio-public-api), and post-UMG-settlement [downloading of audio, video and stems is disabled platform-wide](https://help.udio.com/en/articles/12683565-changes-associated-with-the-universal-music-group-umg-partnership). You cannot get the file out. | **Yes.** (One auditor read the stack-table cell as claiming Udio is "closed to new users" — that is a compound-cell misreading; rejected item #2 says walled garden / no export, which is exactly right) |
| MiniMax Music, direct | [Closed to new paid users since 20 Aug 2026](https://platform.minimax.io/docs/guides/pricing-paygo); free music SKUs discontinued. Confirmed verbatim; $0.15/generation confirmed but academic. | **Yes**, verbatim |
| MiniMax via fal.ai | [fal's ToS](https://fal.ai/legal/terms-of-service) grants ownership of **Input only**, disclaims any IP entitlement in Output, forecloses implied grants ("no other rights are granted … by implication, estoppel, waiver, or otherwise"), and §6(e) bars "service bureau" use "for the benefit of any third party". | **Needs correction** — rejected item #6 says "fal.ai is the right route for MiniMax". It is the *worse* aggregator; Replicate at least grants outputs |
| Stable Audio 2.5 / 3.0 / Open | No vocals, no lyrics parameter. The strings "vocal" and "lyric" appear zero times in Stability's developer docs. Cannot say a name. | **Yes**, but see corrections — 3.0 exists now and the Community Licence is not free of duties |
| Meta MusicGen / AudioCraft | Two hard stops: [weights are CC-BY-NC-4.0](https://github.com/facebookresearch/audiocraft) (no commercial use) and it generates instrumental only. | **Yes**, nothing to reconsider |
| SongGeneration 2 / LeVo 2 (Tencent) | [Licence forbids "any commercial or production purposes under any circumstances"](https://raw.githubusercontent.com/AMAImedia/SongGeneration2-LeVo2/main/LICENSE) — despite the best published lyric accuracy in the survey (PER 8.55%). Hosted resellers of it are broken chains by construction. | **Not listed — add it.** Same failure mode as Suno wrappers, different logo |
| YuE | 10–24 min of GPU per 2-min track, ≥80 GB VRAM for a full song, unmaintained since Jun 2025. Named languages are EN/ZH/Cantonese/JA/KO — but the repo says "**including but not limited to**", so this is an open list, not an exclusion. Rejected on latency and hardware, not language. | Not listed; DECISIONS.md's open item nominating YuE over ACE-Step should be closed against YuE |
| Google Lyria 2 / Lyria RealTime | Lyria 2: "Vocal generation: Not supported", 32.8 s cap. RealTime: experimental, "with no vocals", unpriced. Neither can sing a name. Lyria 2's narrow legitimate use is an **unwatermarked 48 kHz WAV** instrumental bed. | Consistent with item #4's "licensed instrumental bed" note |
| MusicFX / MusicFX DJ / Flow Music | MusicFX retired 31 July 2026; successor [Flow Music](https://www.flowmusic.app/) has no public API. Driving it would be an unlicensed wrapper. | n/a — everything of value now reaches you via Lyria, as item #5 says |
| Riffusion / ProducerAI / FUZZ | Vendor absorbed into Google; redirect chain verified live 27 Aug 2026 (riffusion.com → flowmusic.app; www.riffusion.com/docs → support.google.com/flow). It never had a GA self-serve API to inherit. | **Yes**, and the redirect chain in item #5 is confirmed |
| Qwen-Music | Paper only ([arXiv 2607.11699](https://arxiv.org/abs/2607.11699)); no verifiable public weights, no licence, all evaluation on 600 Chinese/English prompts. "Hundreds of languages" describes a *corpus*, not an output roster. | Not listed; watchlist item, never a plan |

---

## The Uzbek problem

**Zero vendors in this survey have demonstrated sung Uzbek. Not one.** After adversarial re-checking from vendor pages, model cards, API docs, repos, papers, help centres and Uzbek-language third-party sources, the highest defensible grade any vendor earns is **unlisted** — Uzbek neither named nor excluded. That grade is held by ElevenLabs Music, Suno, ACE-Step (1.5 and v1), YuE and HeartMuLa. Exactly three vendors affirmatively exclude Uzbek by publishing a roster that omits it: [Mureka](https://platform.mureka.ai/docs/en/faq.html) (closed 10, no Turkic language), [Google Lyria 3](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-lyria-3-pro) (8 — English, German, Spanish, French, Hindi, Japanese, Korean, Portuguese, with "more languages coming soon"), and [MiniMax music-1.5](https://replicate.com/minimax/music-1.5) ("Supports English and Chinese lyrics").

Two things that look like evidence and are not. First, the widely repeated claim that Suno sings Uzbek traces to a **single third-party Uzbek blog** with no Suno affiliation, no audio samples, and a verdict that is itself negative — *"Talaffuz baʼzan gʻalati"*, "pronunciation is sometimes strange" ([salom-ai.uz](https://salom-ai.uz/blog/ai-musiqa-yaratish/)). Suno publishes no language roster anywhere; the circulating "50 languages" figure appears on no Suno-owned page. Second, the AI-labelled Uzbek track *"Vaqtinchalik shamol"* (DLEJ) is real, is in Uzbek, and circulated widely — but **no source attributes it to any named model**. It is evidence that *some* model sings Uzbek, and evidence about *no vendor*. It cannot raise anyone's grade, though identifying the model behind it is worth an hour.

Note the market-wide pattern: every published sung-language roster stops at roughly the same 10–12 high-resource languages. Russian is in nearly all of them. Uzbek is in none. That convergence is itself a signal — it tracks training-data mass, and Uzbek does not have it. It also means ElevenLabs' Uzbek prior is materially worse than its Russian prior even though both are formally "unstated" for music: Uzbek is absent even from the [TTS roster](https://elevenlabs.io/docs/help-center/other/what-languages-do-you-support) where Russian is present.

### The orthography failure is upstream of every vendor

Correct Uzbek Latin oʻ/gʻ use **U+02BB MODIFIER LETTER TURNED COMMA**. Because that character is missing from most keyboards, real Uzbek text — including on government sites — routinely substitutes U+2018 or a plain ASCII apostrophe. So the bot's input distribution is already mixed-encoding before a vendor is involved.

And this is a **known, characterised failure mode**, not an unknown. Published Uzbek NLP work documents that the modifier letters in oʻ/gʻ and the glottal-stop sign are treated as **delimiters** that split words incorrectly — including in TahrirchiBERT, a model built *specifically for Uzbek*. Tokenizing "Oʻqituvchi gapirdi" yields "O", "qituvchi", "gapirdi": three tokens where there should be two. If a purpose-built Uzbek encoder mis-splits there, a music model's English-dominant BPE tokenizer almost certainly fragments "Gʻulomjon" at the ʻ and sings the fragments. **That is a text-layer bug, not an acoustic one — which is the good news, because it is the one part of the chain you own.**

### Name-pronunciation control surfaces, across the whole market

| Surface | Who has it | What it buys |
|---|---|---|
| IPA / SSML `<phoneme>` / lexicon / stress marks | **Nobody.** Zero music vendors, commercial or open | — |
| Section-level regeneration | ElevenLabs (composition-plan inpainting), Mureka (`/v1/song/region-edit`), ACE-Step (repaint), Suno (UI-only, no clean API) | Re-render just the name line instead of the whole track |
| Seed / determinism | ElevenLabs (best-effort, plan-only, "exact reproducibility is not guaranteed"); ACE-Step (true, self-hosted); PiAPI's Udio-backed `music-u` | Controlled retry vs fresh lottery ticket |
| Orthographic respelling | Universal, undocumented, unreliable | The only *pre-generation* lever that exists anywhere |
| Delivery-mode tags (`[Spoken Word]`, `[Staccato]`) | Suno-family; partial elsewhere via style strings | Blunt but underrated — a half-spoken name line beats a sustained melisma on an unfamiliar name |
| Structural relief (name gets its own short bar) | Anyone with per-section duration control | A correct respelling still fails in an overcrowded line |

**A trap worth naming:** the Russian-TTS convention of capitalising the stressed vowel («звонИт») does **not** transfer. In music models, ALL CAPS means *louder / more intense*, not *stressed syllable*. A shouted name is not a correctly-stressed name. Do not inherit that workaround from the competitor teardown without testing it.

### What the bot may honestly promise

Treat the name as a **text-normalisation problem you own, not a vendor feature you buy**. Emit N candidate orthographies per name (canonical U+02BB, ʻ-free Latin, Cyrillic, hyphenated syllables, phonetic respelling), put the name in its own 5–10 s chunk so a re-render costs one chunk rather than one track, then **close the loop acoustically**: run the rendered name-chunk through Uzbek STT, compare to the intended name, and silently re-roll that chunk with the next candidate orthography before the customer hears anything. No vendor sells a pronunciation guarantee — but you can assemble one from parts that do exist, and that assembled guarantee is the only defensible basis for advertising it.

Decouple **display** orthography from **submitted** orthography. The ʻ only needs to be correct in the message copy and cover art, which you typeset yourself. The lyric string is an internal value nobody sees. On the tokenizer evidence, the ʻ-free respelling may well *beat* the canonical form — an uncomfortable result for a product that markets orthographic correctness, and a non-issue once the two layers are separated.

---

## Corrections to DECISIONS.md

| DECISIONS.md said | This benchmark finds | Source |
|---|---|---|
| D1: "section-by-section regeneration is NOT evidenced on the API reference, so the single feature the research called decisive is unproven" | **Refuted.** Fully documented with a dedicated guide and worked examples: `store_for_inpainting` → `song_id` → a `music_v2` plan mixing audio-reference chunks with generation chunks. `music_v1` has the equivalent `source_from {song_id, range, negative_ranges}`. Re-weight ElevenLabs **up**. Caveat: tier access is self-contradictory — the Commercial Rights table says inpainting is available on every plan including Free, while the API landing page and ElevenLabs' own skills repo say enterprise-only. Highest-value 30-minute test in the project. | [inpainting guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/music/inpainting), [compose](https://elevenlabs.io/docs/api-reference/music/compose) |
| D1 / rejected #7: "upgrading later does NOT retroactively license anything made on Free" | **Refuted.** §2(b): "If you upgrade to a higher-priced plan … all Output in your account at the time of upgrade will be subject to the upgraded plan." §2(c) protects the reverse. **But keep the operational rule** — Free's Monthly Download Limit is "Not permitted", so Free output could never lawfully leave the platform anyway. Right instruction, wrong stated reason. | [Music Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) |
| D1: "explicitly licensed for commercial resale from a $6/mo Starter plan" — licence chain clean | **Corrected to conditional.** Three separate problems: Music API Terms §4.A obliges a "Pure-play Music AI Creation Company" to display "powered by ElevenLabs" across the product and all promotional content, with **no added-functionality carve-out**; ElevenLabs **never grants or assigns ownership of Output** in any of its four instruments; Music Terms §3 disclaims warranties of **title and non-infringement** and Music API Terms §6 makes indemnity run one way, against you. | [Music API Terms](https://elevenlabs.io/music-api-terms), [Music Terms](https://elevenlabs.io/music-terms), [ToS](https://elevenlabs.io/terms-of-use) |
| *(Not in DECISIONS.md at all)* | **New, and it changes the cost model.** §1(b) contractually incorporates the Music Commercial Rights table and makes non-adherence "a breach". Monthly Generation Limit: Free 11 / Starter 17 / Creator 62 / Pro 304 / Scale 1,100 / Business 4,800 min. Monthly Download Limit: Free none / Starter 30 / Creator 250 / Pro 500 / Scale 1,500 / Business 4,000 min. **Starter supports ~15 saleable kits/month.** Paying more USD does not buy quota. | [Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) |
| *(Not in DECISIONS.md at all)* | **New.** Plan Eligibility: Free/Starter/Creator/Pro are "For Individual Use Only"; Scale = entities with <10 employees; Business = <50. §3: enrolling in an ineligible plan "may result in suspension or termination … and/or **loss or forfeiture of Outputs**, fees, and/or credits." The build plan's "Subscribe to ElevenLabs Starter ($6)" is an individual-use plan bought by a company to resell output; the entity-eligible floor is Scale at $299/mo. Reseller Rights are "Prohibited" on **every** self-serve tier including Business. | [Model-Specific Terms](https://elevenlabs.io/eleven-music-model-specific-terms) |
| D1: "no on-plan discount — Music is $0.150/min on every tier" | **Confirmed**, and now proven rather than asserted: the rate reads $0.150 on all six tiers, and "minutes included" is exactly plan fee ÷ $0.150 (Starter $6→40, Creator $22→147, Pro $99→660, Scale $299→1,993, Business $990→6,600). | [pricing/api](https://elevenlabs.io/pricing/api) |
| D1: music concurrency Free 0 / Starter–Pro 2 / Scale–Business 5 | **Confirmed** from two independent first-party surfaces. | [models](https://elevenlabs.io/docs/overview/models) |
| Line 53: "Lyria — no list at all, only 'generates lyrics in the language of your prompt' → UNSTATED" | **Corrected.** A roster now exists and is exclusionary: eight languages, excluding **both Uzbek and Russian**. Re-grade Lyria from UNSTATED to explicitly-unsupported-as-of-today. One nuance the survey overstated: the roster sits on Google Cloud's prompting-guide blog, not the DeepMind model card, and carries "(more languages coming soon)" — so it is point-in-time, worth a calendar re-check, not permanent. | [Lyria 3 prompting guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-lyria-3-pro) |
| Line 170: "switch … when Lyria reaches GA at $0.08 flat" | **Refuted as a future event.** $0.08/song is **live today** on the paid tier, in preview, on both surfaces. There is nothing to wait for on price. Rewrite the trigger as a pure GA/licence trigger. | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Line 170: "a written IP indemnity no competitor offers" | **Refuted.** Lyria is absent from the Generative AI Indemnified Services list (last modified 20 July 2026), which covers only GA Codey, Gemini, Imagen, PaLM and Veo. Pre-GA Terms §5(b): preview offerings "are not covered by any SLA or Google indemnity". **Strike this justification.** | [indemnified services](https://cloud.google.com/terms/generative-ai-indemnified-services) |
| Line 170: "[Lyria] has no section-level editing at all" | **Confirmed, emphatically.** Google's own docs: "Music generation is a single-turn process. Iterative editing or refining a generated clip through multiple prompts is not supported." Plus "Determinism: Results may vary between calls, even with the same prompt" and "Negative prompting: Not supported". Every retry is a full-price re-roll of a *different* song. | [music generation docs](https://ai.google.dev/gemini-api/docs/music-generation) |
| Day-2 step 7: "fire 10 concurrent Lyria requests … its concurrency ceiling is entirely unpublished" | **Half refuted.** Vertex publishes 10 RPM per base model on the model card (identical for lyria-3-pro-preview, lyria-3-clip-preview and lyria-002). The Gemini API tables still omit Lyria entirely. 10 RPM is thin for an "overflow valve" — comparable to ElevenLabs Scale's 5 slots, not obviously better. | [Lyria 3 model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-3) |
| *(Not in DECISIONS.md)* | **New, and project-wide.** Google Cloud Service Specific Terms §20(d) bars using a Generative AI Service in a service "likely to be accessed by individuals under the age of 18"; §20(f) permits immediate suspension on **suspected** violation; §20(g) elevates it to a formal Use Restriction. §17(a) bars using Output "to develop a similar or competing product or service", and the carve-out excludes Google Pre-Trained Models — which Lyria is. This applies to **every** Google GenAI service, so it also touches the Gemini 3.7 Flash lyric layer chosen in D5. Risk-register item, not a music-vendor item. | [Service Specific Terms](https://cloud.google.com/terms/service-terms) |
| Line 53 / D2: "ACE-Step v1 — absent from its published 19", and "two vendors publish closed language lists and exclude Uzbek" | **Corrected.** The 19 were **never published** — the repo names only the top-10 performers. Uzbek is unlisted within an unenumerated set, not excluded. At the time DECISIONS.md was written only **one** vendor (Mureka) published a genuinely closed list excluding Uzbek. Today it is three (Mureka, Lyria, MiniMax). The D2 verdict survives; one of its two stated pillars did not exist. | [ACE-Step v1 repo](https://github.com/ace-step/ACE-Step) |
| Line 190: "ACE-Step 1.5, Apache-2.0, ~27x real-time on one consumer GPU" | **Corrected on both counts.** It is **MIT**, on the repo LICENSE and the HF metadata alike — better than Apache-2.0 for resale (no NOTICE ceremony, no revenue cap, no acceptable-use rider). And it is much faster than recorded: under 2 s per **full song** on an A100, under 10 s on an RTX 3090, at <4 GB VRAM. | [HF card](https://huggingface.co/ACE-Step/Ace-Step1.5), [paper](https://arxiv.org/abs/2602.00744) |
| Rejected #4: DiffRhythm listed among vendors where "none accepts a lyrics input; none sings words in any language" | **Wrong for DiffRhythm.** It generates full-length vocal tracks from supplied lyrics, and v1 conditions on an **LRC file with per-line timestamps** — the most precise lyric-*placement* primitive found in any model. Still rejected, on a different basis: demonstrated intelligibility is English and Chinese only, and DiffRhythm2 publishes no language list at all. Fix the rationale so the rejection survives review. The same line is **correct** for Stable Audio, Stable Audio Open, MusicGen, Mubert, Loudly, Soundraw, Beatoven and AIVA. | [DiffRhythm2](https://huggingface.co/ASLP-lab/DiffRhythm2) |
| Rejected #4 / #6: Stable Audio as a clean licensed instrumental bed | **Corrected.** Stable Audio 3.0 shipped 20 May 2026 with open weights and licensed training data — but commercial use of the weights requires **registering with Stability AI**, shipping a NOTICE file, and **prominently displaying "Powered by Stability AI"**, under a **revocable** licence that terminates above $1M aggregate annual revenue. Not a free, silent bed. Hosted API price of $0.26/generation is **unverified** (the pricing table does not render); only the 20-credit Stable Audio 2.5 figure is on a Stability-hosted page, and the $0.01/credit conversion is not. | [Community Licence](https://stability.ai/community-license-agreement), [API pricing update](https://stability.ai/api-pricing-update-25) |
| Rejected #6: "fal.ai is the right route for MiniMax and nothing else in this stack" | **Corrected.** fal grants ownership of **Input only**, disclaims IP entitlement in Output, and forecloses implied grants entirely; §6(e) bars service-bureau use "for the benefit of any third party"; and one clause requires prior written authorisation to "develop any scripts or software applications that interact with … the Services". Replicate is the less-bad aggregator — it *does* grant outputs — but "all right, title and interest, **if any**" is hollow when the upstream (MiniMax) is silent on output ownership and has closed its door. | [fal ToS](https://fal.ai/legal/terms-of-service), [Replicate terms](https://replicate.com/terms) |
| Rejected #1: "every Suno price and the pivotal 'one generation returns two tracks' billing claim comes from reseller docs — treat as unestablished" | **Partly corrected.** Two-tracks-per-request is now triple-confirmed (two independent resellers' docs plus the competitor's CDN pattern) — treat as established. Suno's own pricing is readable at source: Pro $8/mo, Premier $24/mo (annual **$76.80** and **$230.40**, a 20% discount — not the $64/$192 that circulates). And the decisive new number: from **3 Sept 2026** commercial rights attach to a metered download — Pro 20/mo, Premier 60/mo, retroactive — so the cheapest legitimately downloadable Suno song is **$0.40 on both tiers**, 13x above what wrappers charge. | [suno.com/pricing](https://suno.com/pricing), [help centre](https://help.suno.com/en/articles/13614785) |
| Rejected #2 (Udio), #3 (MiniMax direct), #5 (Riffusion) | **All three hold up exactly as written.** Udio's no-API/no-download posture confirmed from its own help centre; MiniMax's closure notice confirmed verbatim; the Riffusion redirect chain re-verified live on 27 Aug 2026. One addition to #5: Riffusion never had a GA self-serve API to lose — access was waitlist-only throughout. | as cited above |
| D2: Mureka framed as "negative control" only | **Understated.** Mureka is the only vendor affirming sung **Russian** in writing, ships region-edit as a GA endpoint, returns per-word timestamps (which DECISIONS.md assumes "no hosted API on earth does"), and assigns Output ownership outright. Promote it from negative control to a real candidate for the **Russian and English SKUs** — while keeping it as the Uzbek negative control, where it is the correct choice. | [Mureka FAQ](https://platform.mureka.ai/docs/en/faq.html), [service terms](https://platform.mureka.ai/service_terms.pdf) |
| Cost model: 25% re-roll allowance at the full $0.30 track price | **Unresolved, in both directions.** Chunk-level inpainting means a re-render *could* be one 8–15 s chunk rather than 120 s — but **nothing in ElevenLabs' docs states the inpainting billing unit**, so a re-render may cost ~$0.04 or another $0.30. This single unknown decides whether "free re-renders" is a cheap moat or a margin hole. Measure it against the usage dashboard in the same test that settles inpainting tier access. | [pricing/api](https://elevenlabs.io/pricing/api) |
| Section 0 verification notes; D3/D4/D5 TTS, STT, LLM and moderation picks | **Out of scope here — this benchmark covers the sung layer only and found nothing that contradicts them.** D2's core architecture — spoken layer carries the language and the name, sung layer carries the mood — survives this pass fully intact, and for a sharper reason than the document gives: the spoken layer is the **only** place in the entire stack where real phonetic control exists. | — |

---

## Run this yourself — the bake-off protocol

A day-2 gate. Everything below is copy-pasteable.

### The fixed test lyrics

Use the *same* lyric in all three languages so musical quality is comparable across arms. The name is deliberately hard: **Gʻulomjon** is three syllables and contains a gʻ digraph; the stress arm uses **Oʻgʻiloy**, which contains *two* U+02BB in one word.

**(A) Uzbek Latin — canonical, with real U+02BB (ʻ)**

```
[Verse 1]
Bugun bayram, chiroqlar yonadi,
Gʻulomjon, bu qoʻshiq sen uchun.
[Chorus]
Tugʻilgan kuning muborak, Gʻulomjon,
Yuraging shod, umring uzoq boʻlsin.
```

Verify before submitting: `printf '%s' "Gʻulomjon" | hexdump -C` must show `CA BB` (U+02BB) — not `E2 80 98` (U+2018) and not `27` (ASCII).

**(B) Uzbek Cyrillic**

```
[Verse 1]
Бугун байрам, чироқлар ёнади,
Ғуломжон, бу қўшиқ сен учун.
[Chorus]
Туғилган кунинг муборак, Ғуломжон,
Юрагинг шод, умринг узоқ бўлсин.
```

**(C) Russian — stress-sensitive name**

```
[Куплет 1]
Сегодня свечи на торте горят,
Алёна, весь этот вечер — твой.
[Припев]
С днём рожденья, Алёна, милая Алёна,
Пусть сбудется всё, о чём ты мечтала.
```

The test is whether the model sings **/ɐˈlʲɵnə/** (a-LYO-na) or collapses ё→е and sings **a-LYE-na**. Run it twice: once as written (`Алёна`), once with the bare-е spelling (`Алена`) that training data overwhelmingly contains.

### The orthography arms (this is the actual experiment)

Do **not** test "Uzbek" as one arm. Hold the lyric constant and vary only the name string:

| Arm | Name as submitted | Tests |
|---|---|---|
| A1 | `Gʻulomjon` (U+02BB) | canonical — the tokenizer-split hypothesis |
| A2 | `G'ulomjon` (U+2018) | what real Uzbek web text contains |
| A3 | `G'ulomjon` (U+0027) | what a phone keyboard produces |
| A4 | `Gulomjon` | ʻ-free respelling — predicted to **win** |
| A5 | `Gu-lom-jon` / `Ghulomjon` | hyphenation + phonetic respelling |
| A6 | `Ғуломжон` | Cyrillic — tests language misidentification as Russian |
| A7 | `Oʻgʻiloy` vs `Ogiloy` | double-digraph stressor |
| R1/R2/R3 | `Алёна` / `Алена` / `Alyona` | ё preservation and stress |

Also run one arm with the name line tagged `[Spoken Word]` and one with the name given its own 6–8 s chunk on its own bar — structural relief is cheap and underrated.

### Vendors to run

| Vendor | Route | Role |
|---|---|---|
| ElevenLabs Eleven Music | direct API, `model_id="music_v2"`, composition plan | primary candidate |
| Mureka V9.5 | `/v1/song/generate`, `n=1` | Russian/English candidate **and** Uzbek negative control |
| ACE-Step 1.5 | WaveSpeedAI, or a 1-hour RunPod Community 4090 pod | strategic reserve. **Do not test Replicate's `lucataco/ace-step` — that is v1** |
| Lyria 3 Clip → Pro | Gemini API or Vertex | roster check; Clip first at $0.04 |
| MiniMax music-1.5 | Replicate | cheap negative control (owner says EN/ZH only) |
| Suno | via kie.ai | **unpriced internal benchmark only — no output ever ships** |

While there: fire 10 concurrent Lyria requests on Vertex and confirm the documented 10 RPM; and run one ElevenLabs inpainting call on a self-serve key to settle both the tier-access contradiction *and* the billing unit (compare the usage-dashboard delta for a 15 s chunk re-render against $0.04 vs $0.30).

### Scoring rubric

Blind. Play the isolated name line, not the whole track. Two native Uzbek listeners and one native Russian listener, scoring independently.

| Dimension | Scale | Method |
|---|---|---|
| **Name intelligibility** | 0–3 | 3 = listener writes the name back correctly, unprompted, first play. 2 = correct on one repeat. 1 = recognisable but wrong. 0 = unrecognisable |
| **Machine gate** | pass/fail | Run the name chunk through ElevenLabs Scribe v2 (uz) or Azure `uz-UZ`; exact match after normalisation |
| **Stress correctness** | 0–2 | Uzbek: stress on the final syllable (Gʻulom**JON**). Russian: Алёна = /ɐˈlʲɵnə/, not /ɐˈlʲenə/ |
| **Musical quality** | 0–3 | Two listeners: "would you pay $5.90 for this as a birthday gift?" |
| **Latency** | seconds | Wall-clock submit → downloadable file. Record p50 and worst of 5 — no vendor publishes this |
| **Cost** | USD | Metered against the dashboard delta, not the price list. Record first-attempt **and** re-render separately |

### Pass threshold

A vendor passes the **Uzbek sung SKU** if, on its best orthography arm: ≥8 of 10 renders score ≥2 on intelligibility from **both** native listeners, **and** the STT gate exact-matches ≥7 of 10, **and** median musical quality ≥2. Anything less → sung Uzbek stays labelled beta, and the shipped default for Uzbek orders is sung Russian or English with the name carried by the three spoken Uzbek greetings.

A vendor passes the **Russian SKU** if ≥9 of 10 renders preserve ё-stress on Алёна. Russian has training-data mass; a lower bar there is not warranted.

**Sanity check on the whole experiment:** if listeners cannot distinguish Mureka's Uzbek output (a vendor that publishes an exclusion) from ElevenLabs', the test lacks discriminating power and the result means nothing. Re-run with a harder name before believing any positive.

### Estimated cost

| Line | Arithmetic | Cost |
|---|---|---|
| ElevenLabs — 10 arms × 2 renders × 2 min | 40 min × $0.150 | $6.00 |
| ElevenLabs — inpainting tests | ~10 × 15 s chunks, billing unit unknown | $0.40–$3.00 |
| Mureka — 10 arms × 2 renders, `n=1` | at the $0.15 rate | $3.00 |
| Lyria — 20 Clip probes + 4 Pro confirmations | 20 × $0.04 + 4 × $0.08 | $1.12 |
| ACE-Step 1.5 — one RunPod Community 4090 hour | $0.34/hr | $0.34 |
| MiniMax 1.5 via Replicate — 20 renders | ~$0.03 each (unverified) | ~$0.60 |
| Suno via kie.ai — benchmark only | $5 minimum top-up | $5.00 |
| **Metered API spend** | | **≈ $17** |

**Cash actually out is higher, because of floors and minimums.** Google requires a **$10 minimum prepay** before the first Lyria call (no free tier on either Lyria row). Mureka credits are non-refundable and expire 12 months from last top-up — use the smallest possible top-up and **test reachability from a UZ egress IP before funding a real balance**, because Mureka documents a `403 — unsupported region` with no published region list. kie.ai's $5 minimum is non-refundable. **Realistic total: $40–50 cash, plus 6–8 hours of founder time and ~2 hours of paid native-listener time**, which the current plan does not cost.

**One gotcha that will bite on the ElevenLabs arm:** 10 arms × 2 renders × 2 min = **40 minutes of generation**, which exceeds Starter's incorporated 17 min/month limit. Run the bake-off on **Creator ($22, 62 min generated / 250 min downloaded)**. Note that Creator is also "For Individual Use Only" — fine for a personal test key, not a basis for a production account.

---

## Open questions

These cannot be closed by more searching. Each needs a render, a charge, or an email.

**Settled only by running the bake-off**
1. Does any vendor sing an intelligible Uzbek name — and which orthography arm wins? The prediction from the tokenizer literature is that the ʻ-free respelling (A4) beats the canonical U+02BB form (A1). If so, decouple display orthography from submitted orthography and the product's marketing tension disappears.
2. Does Cyrillic Uzbek get read as Russian and given Russian phonology (Ў→У, Ғ→Г)? No vendor documents script or language detection for sung text.
3. Latency for a ~2-minute track at ElevenLabs, Mureka and Lyria. **Every one of these vendors publishes nothing** — no p50, no p95, no SLA. Do not size the order queue on a guessed number.
4. Does ElevenLabs inpainting work on a self-serve key, and what is the billing unit? ElevenLabs' own sources contradict each other on tier access; the billing unit is undocumented anywhere. This single answer decides whether the free-re-render differentiator is a moat or a margin hole.
5. Does a UZ-issued international Visa/Mastercard actually clear at ElevenLabs, Google Cloud, Mureka, Replicate and RunPod? No vendor is geo-blocked and none publishes a supported-countries list; acceptance is a processor-level fraud decision and a UZ BIN with a Tashkent billing address is exactly the mismatch pattern that gets declined. Run a real small charge from the production IP, not a laptop. Google's country/currency selection is **irreversible**, and Google warns that cards requiring in-session OTP "can't be used for … recurring automatic transactions" — a live auto-pay failure mode for UZ cards.
6. Does Mureka's API answer at all from a UZ egress IP, or return the documented 403?

**Settled only by writing to a vendor**
7. **ElevenLabs, in writing, before launch:** (a) is a registered Uzbek company selling AI-generated song kits a "Pure-play Music AI Creation Company" under Music API Terms §4.C.ii, and is "powered by ElevenLabs" co-branding therefore mandatory? (b) do the Music Commercial Rights table's Monthly Generation and Download limits bind USD-billed API usage, or only the app? (c) which plan is a UZ company actually eligible for? (d) the 59-language vocal roster. All four are one email. (a) and (c) are launch gates; discovering them after customers have paid is materially worse.
8. **Mureka:** the full per-model price table, the recharge-tier→concurrency mapping, whether region-edit is billed as a full song, and the supported-region list. All are behind a login or unpublished.
9. **Suno:** file the [partner-API intake form](https://www.musicbusinessworldwide.com/suno-explores-developer-api-seeking-apps-that-unlock-experiences-generative-music-makes-possible-for-the-first-time/) — it is free, and a licensed first-party API would invert this analysis overnight. Ask explicitly whether a paid song bot trips the competing-product bar rather than assuming a partner agreement supersedes it.

**Watch and re-check on a date**
10. **28 Aug 2026 (tomorrow):** whether Mureka's V9.5 rate actually moves from $0.045 to $0.15. This deadline is **unverified from any primary source** — do not let an unconfirmed urgency claim force a non-refundable top-up.
11. **3 Sept 2026:** Suno's download caps take effect, retroactively. Watch whether any wrapper publishes a price change; a $0.03 price surviving unchanged under a $0.40 licensed floor is evidence of an un-metered pipeline, not of efficiency.
12. **September 2026:** Suno's new Terms of Service. The current ToS is what disqualifies the reseller route; the September text is the single most plausible source of a legitimate reversal.
13. **Ongoing:** Lyria's eight-language roster carries "(more languages coming soon)". It is the one exclusion in this report that could lapse.

**Unresolvable from public sources, stated plainly**
14. Whether ElevenLabs watermarks Music output. No statement exists either way — treat "no watermark" as unverified, not confirmed.
15. Retry billing at every vendor. Nobody publishes it. For a business whose promise is free re-renders, the attempts-per-kit multiplier is the largest unquantified input in the entire cost model.
16. Which model produced *"Vaqtinchalik shamol"*, the only widely distributed AI-generated Uzbek track anyone can point to. Identifying it — by contacting the uploader or running the audio through a detector — would be the single most valuable hour of research left in this space, because it is the only existence proof that any model sings Uzbek at all.
---

## Addendum — music quality vs Suno (added 27 Aug 2026)

The main report deliberately did not score audio quality. This addendum fills that gap using the only
independent head-to-head data that exists: the [Artificial Analysis Music Arena](https://artificialanalysis.ai/music/arena),
a blind pairwise vote (two tracks, same prompt, model identities hidden) scored as Elo.

### Blind-vote Elo, vocals

| Rank | Model | Elo | Votes | Suno V5.5 beats it |
|---|---|---|---|---|
| 1 | **Suno V5.5** | 1171 | 10,470 | — |
| 2 | Mureka V9 | 1161 | 3,112 | 51% (statistical tie) |
| 3 | Mureka V8 | 1141 | 11,544 | 54% |
| 4 | Suno V5 | 1098 | 11,458 | 60% |
| 5 | MiniMax Music 2.5+ | 1094 | 11,331 | 60% |
| 6 | MiniMax Music 2.6 | 1092 | 11,144 | 61% |
| 7 | Suno V4.5 | 1089 | 9,426 | 61% |
| 8 | Lyria 3 Pro | 1082 | 11,146 | 63% |
| 9 | **Eleven Music v2** | **1070** | 5,684 | **64%** |
| 11 | Eleven Music (v1) | 1024 | 9,745 | 70% |
| 14 | Udio v1.5 Allegro | 969 | 8,889 | 76% |

Source: [vocals leaderboard](https://artificialanalysis.ai/music/leaderboard/vocals). Win probabilities are
the standard Elo expectation `1/(1+10^(-Δ/400))`. Instrumental board is similar and slightly worse for the
pick: [Suno V5.5 1186, Mureka V9 1177, Lyria 3 Pro 1118, Eleven Music v2 1058](https://artificialanalysis.ai/music/leaderboard/instrumental)
— a 68% Suno win rate.

**The uncomfortable result: Eleven Music v2 is beaten by every Suno generation on the board, including
V4.5, which is two generations old.** The pick in this report is not the quality leader and is not close
to it. It was selected on licence, API surface, lyric control and payability — every axis except this one.

### Lyric alignment — the metric that actually matters here

Arena Elo measures "which track do you like more", which is not this product's question. The closer proxy
is lyric alignment: does the model sing the words you supplied, intelligibly. From the
[ACE-Step 1.5 paper's](https://arxiv.org/html/2602.00744v1) comparison table:

| Model | Style align | **Lyric align** | AudioBox CU | SongEval PQ |
|---|---|---|---|---|
| **Suno-v5** | 46.8 | **34.2** | 7.87 | 8.29 |
| Suno-v4.5 | 40.5 | 32.7 | 7.85 | 8.25 |
| MiniMax-2.0 | 43.1 | 29.5 | 7.95 | 8.38 |
| ACE-Step 1.5 | 39.1 | 26.3 | **8.09** | 8.35 |
| Udio-v1.5 | 34.9 | 24.8 | 7.65 | 8.03 |

Suno leads lyric alignment by a wide margin — the largest gap in the table, and the one dimension where
open weights have not closed. ACE-Step 1.5 wins on raw audio quality (highest CU) and its subjective A/B
"ranks between Suno-v4.5 and Suno-v5", but it is the *words* it loses on. For a product whose entire value
is a name landing correctly inside a sung line, this is the wrong metric to be behind on.

Eleven Music is absent from this table (the paper predates or omits it), so its lyric-alignment standing
against Suno is **unmeasured**.

### Three caveats that bound all of the above

1. **No Uzbek. No Russian.** The ACE-Step test set is explicitly "bilingual (Chinese/English)". The Arena
   publishes no language breakdown and its prompt pool is English-dominant. Every number here is a
   general-purpose English music score. The market-wide finding of the main report stands unchanged:
   sung Uzbek is unmeasured for every vendor including Suno.
2. **Mureka V9's near-tie rests on 3,112 votes** — the smallest sample on the board, roughly a third of
   its neighbours. No confidence intervals are published. Treat rank 2 as provisional.
3. **Arena voters are rating music, not gifts.** A 64% blind preference is "noticeably better", not
   "categorically different", and it is being cast by people comparing tracks side by side — which is not
   what a birthday-gift recipient does.

### Why this does not change the pick

Suno remains unbuyable at any quality level, and the gap between it and the field narrowed in the wrong
direction for anyone hoping to use it:

- **No public API.** As of 1 July 2026 Suno was only "exploring" a partner programme — no docs, no timeline.
- **Its ToS bars using Output "to create a competing product or service"** — stated twice. An AI song bot is
  the definition of the excluded case.
- **Commercial rights are now metered to downloads** from 3 Sept 2026 — Pro 20/mo, Premier 60/mo — putting
  the cheapest legitimate Suno track at **$0.40**, above ElevenLabs' $0.30 and 13× above what the wrappers
  charge. The wrapper price advantage was always the licence violation being priced in.
- **In-waveform watermarking + fingerprinting** announced 6 Aug 2026 — unstrippable, unlike ID3 metadata.
- **Suno has said its current models "will be deprecated"** when the WMG-licensed models ship. Building on
  V5.5 means building on something its own vendor has scheduled for removal.

### What it does change

**Use Suno as the quality ceiling in the day-2 bake-off, and score against it.** The protocol already lists
it as an unpriced internal benchmark — this addendum gives that arm a purpose beyond curiosity: it
calibrates whether the licensable options are *acceptable* or merely *available*. If ElevenLabs lands the
Uzbek name at 64%-worse general quality, that is a fine trade for a $5.90 gift. If it also loses the name,
the trade is not available at all.

**Promote Mureka further.** It is statistically tied with Suno on both boards (51% / 51%), it is the only
vendor affirming sung Russian in writing, it assigns Output ownership outright, and it ships region-edit.
On this evidence Mureka outranks the current pick on quality by 91 Elo. Its blockers are commercial and
operational — an unverified price, a 403-on-unsupported-region risk, and an Uzbek exclusion in its own FAQ —
not musical. **Test reachability from a UZ egress IP before the bake-off, not during it.**
