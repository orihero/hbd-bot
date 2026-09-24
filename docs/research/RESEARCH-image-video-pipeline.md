# RESEARCH — the image and video pipeline: gateway, Gemini 3.8 TTS, Higgsfield, fal, moderation, unit economics

**Dated 2026-09-24. Frozen at that date** — correct it by adding a dated note at the end, never by
editing a finding in place (`docs/README.md`, `research/` lifecycle).

**Method.** Nine read-only investigations over this repository, the owner's gateway README and
OpenAPI export, the gateway's own logs, the live gateway's unauthenticated `/health` and
authenticated `/v1/models` and `/queue` (read only), and vendor documentation. **No generation
job was submitted and no credit was spent.** The gateway credential appears here only by its
variable name, `GENAI_API_KEY`; the Gemini keys only as `GEMINI_TTS_API_KEYS`. The gateway's
public address is deliberately not written into this repository (§1.5).

**What this fed.** `IMAGE_VIDEO_SPEC` (all sections) and `DECISIONS.md` **D20–D26**. The owner
answered the open questions the same day; where his answer differs from a recommendation below,
the recommendation is left as written — it is what the research said — and the decision record
says what was chosen and which risk was accepted (§7).

---

## 1. The local gateway ("Unified Gen-AI Gateway v2.0", RTX 5090, Windows)

### 1.1 What works — and a stale README

| Capability | Status, 2026-09-24 | Evidence |
| --- | --- | --- |
| `flux2` (FLUX.2-dev) t2i and img2img | Works. 31–43 s per 1280×720 image at 25 steps. img2img is a single-input denoise restyle: 0.5–0.7 keeps the subject, above 0.8 loses it. | README "Measured throughput" (09-23), `generation_log.jsonl` |
| `wan` (Wan 2.2) t2v and i2v | **Works**, ~1 050 s (17.5 min) per 81-frame, 16 fps, 5.06 s, 1280×720 silent h264 clip. 13 clips on 09-22/23, 0 failures. | `assets/run_full.log`, `generation_log.jsonl` |
| HunyuanVideo 1.5 | Never exercised; no i2v mode. Treat as unknown. | — |
| Ollama LLMs/VLMs at `/v1/chat/completions` | Works: `qwen3.8:27b-q4_K_M`, `qwen3:8b`, `qwen3-vl:30b-a3b-instruct`, `qwen3-vl:8b`, `gemma3:27b`, `minicpm-v4.5`, `PaddleOCR-VL`. **No safety-tuned model installed.** `kimi-k2.7-code:cloud` leaves the box. | live `/v1/models` |
| whisper large-v3 STT (uz/ru/en) | Present. | README §6 |
| "Local" TTS | **Edge-TTS** — Microsoft's consumer Read-Aloud endpoint. Not local, no commercial licence, needs outbound internet. | README §6 |
| Undocumented since the README | Models `storybook`, `storybook_wan`, **`zootopia` (a LoRA of named Disney characters)**; endpoint `POST /v1/images/generations`. | live `/v1/models`, `/openapi.json` |

The older README copy (the one in the owner's Telegram downloads) says every `wan` and
`hunyuan` request returns 502. That was true on 09-22 and was fixed the same day
(`FIXING-VIDEO.md`); the newer README and the logs supersede it. Several first-pass conclusions
that "video is blocked" were built on the stale copy and are wrong: **video is slow, not broken.**

### 1.2 Throughput

Measured 09-23, GPU dedicated: ~80–90 images/h **or** ~3.4 videos/h (~80/day). An older
estimate (107 s/still, ~19 min per 121-frame Hunyuan clip,
`RESEARCH-local-rebuild-render-budget.md`) is superseded for these models. The GPU is shared with
the owner's film pipeline, the storybook/zootopia work and marketing renders — a reel rebuild is
6–23 GPU-hours — so customer capacity is lower and bursty. Ten queued videos is a ~3 h wait for
the tenth customer, against SCOPE ASY-12's 10-minute order deadline and NFR-8's 200 orders/h
sizing. Idle VRAM varied from ~3.2 GB free (09-23 log) to 13.2 of 34.2 GB free (live `/health`,
09-24) with resident Ollama models; admission control must read `vram_free_gb` live.

### 1.3 API traps

| Trap | Consequence for a client |
| --- | --- |
| Async only: `POST /generate` → poll `GET /jobs/{id}` → `GET /result/{id}?index=`. No webhook, no progress %, **no idempotency key**. | A retried POST is a second GPU job. Persist the attempt before POSTing. |
| Unknown id → HTTP 200 `{status:"unknown"}` | Needs a wall-clock deadline and must be treated as terminal. |
| Validation failure → HTTP 502 with no `job_id`; `detail` truncated ~500 chars | Classify by status + absence of `job_id`, not by message. |
| `/interrupt` is **global** — it kills whatever is running; no per-job cancel | Never map a customer cancel to it. |
| `image` is **one** string (base64, data URL or http URL) | One reference per job. |
| `width`/`height` default to 1024 and ignore the input image | Always send both. |
| README documents `frames`; the working client sends **`length`** (`scripts/generate_sequential.py:236`, `scripts/client.py:112`); live echoes show `length:81` honoured, `frames:null` | Send `length`. |
| `additionalProperties: true` | A misspelt key is silently ignored, and so is — or is not — a user-chosen `model`. Pin an allowlist; forward no extra keys. |
| A job exceeded a 900 s client timeout; polls hit "Network is unreachable" | Count only rendering time toward the render timeout; retry transient poll errors. |
| Every input is kept as `api_in_<hash>.png` and every output kept; no delete endpoint | User photos outlive any retention clock we set. |

### 1.4 Licences

- **FLUX.2 [dev] weights prohibit revenue-generating use** (already recorded, `DECISIONS.md` §7
  rejected #19). `flux2` is the only local image model. The BFL *API* and a BFL commercial
  self-hosting licence are the two licensed routes.
- Wan 2.2 and HunyuanVideo each need an LR-36 licence-matrix row (SCOPE LR-36); not checked here.
- Edge-TTS has no commercial licence.

### 1.5 Operations and security

Plain HTTP on a residential dynamic IP (it has changed once), CORS `*`, one static shared key
accepted as a header, as Bearer **or as `?api_key=`**, and written in plain text in both READMEs,
`FIXING-VIDEO.md` and `scripts/client.py:9`. A Windows desktop that autostarts only after a user
logs in. Reachability from the production host has never been tested. SCOPE SEC-12 requires
HTTPS. **Before any customer photo crosses it:** rotate the key, front it with Cloudflare Tunnel +
Access (as the production host's ingress already is), accept header auth only, and sweep the box's
inputs and outputs. If the gateway README is ever vendored into `reference/`, redact the key first.

---

## 2. Gemini 3.8 TTS

- **Models:** `gemini-3.8-flash-tts` (130 languages) and `gemini-3.8-flash-lite-tts` (101), GA
  2026-09-23. "3.8" is a real id.
- **Uzbek:** "Northern Uzbek" and Russian are in both models' language tables. **Listed, not
  proven**: the model is one day old, Cyrillic-script Uzbek input is unconfirmed, quality unknown.
  `DECISIONS.md` rejected #11 ("zero Uzbek at every tier … Gemini TTS") predates 3.8 and is stale
  for this model only.
- **API:** the only documented path for 3.8 is `POST /v1beta/interactions`, header
  `x-goog-api-key`, `generation_config.speech_config`; style goes in `speech_metadata.style`
  (anything written into the text as a stage direction is spoken aloud); ≤2 speakers. Unary
  responses are WAV (24 kHz mono 16-bit) with a header; streaming is headerless L16.
- **Limits:** 8 192 input / 16 384 output tokens per call; 25 audio tokens/s (~655 s per call).
  30 prebuilt voices plus voice design. SynthID watermark on every clip.
- **Price per 1M tokens (paid tier):** Flash $0.50 in / $9.00 audio out until 2026-12-31, then
  $1 / $18; Flash-Lite $0.50 / $6.00, then $1 / $12. A 10 s clip ≈ $0.002.
- **Rate limits are per project, not per API key.** Several keys in one project add no
  throughput. Keys spread across projects or accounts to exceed limits fall under the Google APIs
  ToS §d ("will not attempt to circumvent"), with project suspension as the remedy.
- **Free tier** uses prompts for training and human review — contrary to D5's paid-tier rule.
- **Terms:** the Gemini API Additional Terms require users to be 18+ and exclude services "likely
  to be accessed by individuals under 18"; Google Service Specific Terms §20(d)/(f) allow
  suspension on suspicion (`BENCHMARK-song-generation.md`). Uzbekistan is an available region.
- **Recommendation at the time:** one billed project, ≤2 keys for rotation only, quota increase
  on request. *(Owner chose a multi-key pool — D23.)*
- **Fallback order recommended:** Gemini 3.8 Flash (uz), Flash-Lite (ru/en, after a listening
  test) → ElevenLabs (already integrated; Uzbek passed only an informal test,
  `providers/tts/router.py:52-54`) → Edge-TTS last or never (unlicensed).
- **The prompt is not a script.** A visual prompt ("a cat surfing at sunset") is not narration;
  at ~2.5 words/s a 5 s clip holds ~12 words.

---

## 3. Higgsfield REST API

- A **separate account** from the consumer MCP wallet the Peshta campaign used
  (`marketing/campaigns/peshta/05_HIGGSFIELD_RECREATION_SETUP.md:7`). Auth
  `Authorization: Key <id>:<secret>`; no `params` wrapper, no `use_unlim`; `POST /estimate/<path>`
  replaces `get_cost` and is free.
- Submit `POST /<model-path>[?hf_webhook=]`, status `/requests/{id}/status`, outputs
  `images[].url` / `video.url`. Inputs are public URLs only, via `/files/generate-upload-url`
  (1 h expiry). Outputs kept ~7 days.
- **No idempotency key; docs say never auto-repeat a POST after an ambiguous timeout; no
  list-requests endpoint** to recover a lost id. Concurrency limit returns **400** with no
  Retry-After. Insufficient credits: docs say 403, SDK README 402 — map both to quota exhausted.
  Webhooks are **unsigned** (use only as a trigger to re-read status). Server-side moderation:
  terminal `nsfw`, not charged.
- Nano Banana, Seedream, Veo and Reference Elements are MCP-only, not in the API catalogue.
- Audio defaults to override when we mux our own voice: Kling `sound` on by default, Seedance
  `generate_audio` true by default (a 33% overspend was observed on the MCP).
- Measured geometry drift (MCP): 716×1284 and 4.04 s for a 4 s request — normalise with ffprobe.

| Model (API) | Max refs |
| --- | --- |
| Grok Image 2 | ≤10 |
| Qwen Image edit | ≤3 |
| Seedance 2.0 R2V | ≤9 (+≤3 audio refs) |
| Wan 2.7 R2V | ≤5 |
| Kling 3.0 I2V | 1 + last frame |

**Terms:** outputs commercially usable and sublicensable; but a "pass-through/service bureau with
no independent value added" clause sits close to a bare prompt-to-image product; inputs may be
used for training without an Enterprise agreement; users 18+.

## 4. fal

`queue.fal.run` queue API with a `cancel_url`; broad catalogue (Nano Banana, Seedream, Veo, Wan
2.5). Static price table. Terms not reviewed in this pass. The natural "other" backend for models
Higgsfield's API lacks.

---

## 5. Moderation options

**Finding.** Screening locally is right; asking a general chat LLM "is this OK, yes/no" is its
weakest form — it follows instructions embedded in what it judges, its verdicts are uncalibrated
with no score to threshold, a q4 model answers differently across runs, it over-refuses on words
(order `1251314e` was lost over a beer mention, `pipeline/prompts.py:211-231`), and it is slow.
For image and video the main risk is in the **uploaded photos** and the **generated output**, and
the local backend refuses nothing.

| Candidate | Modality | Notes |
| --- | --- | --- |
| **Qwen3Guard-Gen-4B** | text | 119 languages; categories incl. Sexual, Violent, Jailbreak, Copyright; outputs `safe/controversial/unsafe` + categories. Uzbek and its China-centric "political" class must be tested. |
| **ShieldGemma 2 (4B)** | image | Policy-conditioned yes/no probabilities (sexually explicit, dangerous, violence). |
| Shieldstral 3B | image/text | Alternative policy-aware guard. |
| gpt-oss-safeguard-20b | text | Bring-your-own written policy; for "controversial" escalation. |
| Llama Guard 4 12B | text+image | Heavier; English-centred. |
| NudeNet / Falconsai NSFW | image | Tripwire only: Falconsai missed >59% of unsafe images in a 2026 eval. |
| whisper large-v3 | audio→text | For screening voice notes. Rejected #13 notes it hallucinates on Uzbek — acceptable for a moderation signal only with a no-speech/empty-transcript guard. |

**Existing song moderator, live weaknesses:** runs after payment and fails open on transport
errors (`pipeline/moderation.py:1-31`); `ModerationPayload.is_allowed` defaults to `True`
(`:69`) with `extra='ignore'`, so `{"allowed": false}` parses as *allowed*; user text is pasted
unescaped inside quotes (`pipeline/prompts.py:246-258`).

**Text inside images.** ShieldGemma 2 scores only sexual, dangerous and violence, so a slogan, a
slur, an insult to an official or a captioned flag in an uploaded photo would pass it, and img2img
or i2v keeps it in the output. PaddleOCR(-VL) and qwen3-vl are already on the box: OCR text plus a
short caption, screened by the text guard, covers this (adopted as G8 in `IMAGE_VIDEO_SPEC` §6.5).

**No guard detects minors.** Qwen3Guard's categories have no minor class and ShieldGemma 2's stock
policies are sexual/dangerous/violence; a youth signal has to be built (term lexicon, a ShieldGemma
custom policy, a VLM caption), and nudity on any image is safest treated as zero-tolerance.

**CSAM.** PhotoDNA/NCMEC hash lists are out of reach for this operator. Hard rule: any minor
signal with any sexual/nudity signal is a block with no retry, a strike, and evidence under a
defined legal hold; SCOPE §6.9 needs a named escalation owner.

**Legal context (not legal advice).** Law on Informatization prohibitions; the 2026 expansion of
extremism law; state review of religious materials; criminal exposure for insulting officials
(deepfakes of officials are the worst output this bot could produce); Personal Data law amendment
No. 1125 (biometric localisation) may reach faces sent abroad; AI Order 3787 argues for a human
in the loop on bans. Counsel should review.

### Face-conditioned fallback (not built; `DECISIONS.md` D20 trigger)

The owner chose Terms only, with no face logic (D20). If D20's trigger fires — the first confirmed
real-person or minor abuse case the D24 layers let through — this is the policy to build within
one release, carried over from the research brief:

- **Detector:** MediaPipe face detection (Apache-2.0) on every upload and output. **Not
  InsightFace** — its weights are non-commercial.
- **Stricter rules when a face is present:** no nudity or sexualisation, no violence against the
  person, no political or religious framing; screened at a lower threshold than faceless images.
- **Consent tap:** a logged "this is me / I have this person's consent" button before a
  face-bearing request can be quoted.
- **Likely minor → innocuous edits only** (restyle, background, costume), otherwise refuse.
- **Restyle, not identity transfer:** with a face present, img2img at denoise 0.5–0.7 only; no
  "put this person in a scene" at launch.

---

## 6. Unit economics

FX illustrative: 12 800 UZS/USD (`.env.admin.example:243-250`) or CBU 11 795. 5 000 UZS ≈
$0.39–0.42 before the ~2% Payme fee (unverified).

**Image, per request** — one 5 000 UZS request delivers **two** images; 1.5 attempts assumed per
image. Revenue per request net of the ~2% Payme fee: 4 900 UZS ≈ **$0.383** at 12 800 UZS/USD
(≈ $0.415 at CBU 11 795; the table uses the lower, conservative figure).

| Backend | Per delivered image | **Per request (×2)** | Share of net revenue | Viable at 5 000 UZS? |
| --- | --- | --- | --- | --- |
| Local flux2 | ~$0 cash; GPU time and power uncosted | ~$0 | — | yes (licence, §1.4) |
| Higgsfield Soul 2 (third-party figure) | ~$0.014 | ~$0.028 | ~7% | yes |
| Higgsfield (docs' illustrative figure) | ~$0.14 | ~$0.28 | **~73%** | **no** |
| fal Seedream v4 | ~$0.045 | ~$0.09 | ~23% | yes |
| fal Nano Banana Pro edit | ~$0.225 | ~$0.45 | **~117% (a loss)** | **no** |
| Runware FLUX dev | ~$0.006 | ~$0.012 | ~3% | yes |

Any backend above ~50% of net revenue is **not viable at this price**; `DECISIONS.md` D21's
fallback may only switch to a backend under that line, or re-price first. *Correction, same day:*
the first version of this table divided one image's cost by the whole request price and so
understated every share by half. Higgsfield figures disagree 10–30× between sources: one free
`/estimate` per chosen endpoint before committing a price.

**Video, per 5 s clip**

| Backend | Cost | Implied retail floor |
| --- | --- | --- |
| Kling 3.0 std (Higgsfield) | ~$0.56 ≈ 7 200 UZS (≈10 800 at 1.5 attempts) | ≥15–20k UZS |
| Seedance 2.0 1080p | ~$2.55 ≈ 32 600 UZS | ≥45–50k UZS |
| Seedance 2.5 480p | ~$0.43 ≈ 5 400 UZS | |
| fal Wan 2.5 | ~$0.25 ≈ 3 200 UZS | |
| Local Wan | ~$0 cash; 17.5 GPU-min | capacity-bound (~80/day ceiling) |
| Gemini TTS narration | ~$0.002 | negligible |

Identity from a person's photo holds ~50% per attempt (`marketing/campaigns/peshta/05_build/FINDINGS.md:36-38`);
budget 1.5–2 attempts. Higgsfield credits expire after 1 year. Paying USD vendors from a UZ card
carries decline/FX risk (`RESEARCH-unit-economics-and-uzbek-vendors.md:292`). Gemini prices
double on 2027-01-01.

---

## 7. What was decided afterwards (pointer only)

Owner answers of 2026-09-24, recorded in `DECISIONS.md` D20–D26 and implemented by
`IMAGE_VIDEO_SPEC`: local flux2 for paid images **with the licence risk accepted** (D21); video
Standard on local Wan now, Fast on Higgsfield later (D22); Gemini 3.8 TTS with a **multi-key pool,
ToS risk accepted** (D23); guard models installed on the 5090, fail-closed (D24); free beta for
admins on the stub rail first (D25); a Terms + Privacy gate for all users and no face-specific
logic (D20, D26).

## 8. Sources

Repository: `src/bayram/pipeline/moderation.py`, `pipeline/prompts.py:210-258`,
`providers/tts/{router,registry,metering,transport}.py`, `contracts.py:1045,1078,1165-1260`,
`config.py:125,133,217,281,306,503,857`, `errors.py:232-310`, `payme/errors.py:140-152`,
`entitlements.py:150-165`; `docs/research/BENCHMARK-song-generation.md:148`,
`RESEARCH-unit-economics-and-uzbek-vendors.md:17,18,40,292`,
`RESEARCH-local-rebuild-render-budget.md:13-27`,
`RESEARCH-ab-higgsfield-vs-local-reel-metrics.md`; `marketing/campaigns/peshta/05_HIGGSFIELD_RECREATION_SETUP.md`,
`05_build/FINDINGS.md`, `05_build/BUILD_COMPLETE.md:36-57`.

Owner material outside the repository (read only): the gateway README (two copies),
`ai-video-production/{README.md, FIXING-VIDEO.md, openapi.json, assets/run_full.log,
assets/run_fix.log, assets/generation_log.jsonl, scripts/generate_sequential.py, scripts/client.py,
docs/PRODUCTION_PIPELINE.md}`; live gateway `/`, `/health`, `/docs`, `/v1/models`, `/queue`
(2026-09-24).

Web: ai.google.dev/gemini-api/docs/speech-generation (updated 2026-09-23);
…/models/gemini-3.8-flash-tts; …/models/gemini-3.8-flash-lite-tts; …/pricing; …/rate-limits;
…/available-regions; …/safety-settings; ai.google.dev/gemini-api/terms; developers.google.com/terms;
blog.google (Gemini 3.8 TTS release; 3.1 Flash TTS). docs.higgsfield.ai (llms.txt; concepts:
requests, polling, webhooks, file-uploads, errors, rate-limits, billing-and-retention; help/faq;
models: kling-3 standard I2V, seedance-2 R2V, wan-2-7 R2V, grok-image-2, qwen-image-3 edit,
soul-2, z-image-turbo); higgsfield.ai/terms-of-use-agreement; github.com/higgsfield-ai/higgsfield-client;
mindstudio.ai and byteiota.com Higgsfield pricing write-ups; pricepertoken.com/image;
runware.ai/pricing; costgoat.com/pricing/kling. qwenlm.github.io/blog/qwen3guard and
github.com/QwenLM/Qwen3Guard; huggingface.co/google/shieldgemma-2-4b-it and arXiv 2504.01081;
huggingface.co/meta-llama/Llama-Guard-4-12B; openai.com/index/introducing-gpt-oss-safeguard;
arXiv 2603.16181 (Falconsai recall); safer.io and Prostasia CSAM-filtering comparisons;
legal500.com (Uzbekistan AI and personal-data updates); freedomhouse.org (Uzbekistan 2024);
thediplomat.com (2026-05 extremism law); state.gov (2023 religious-freedom report, Uzbekistan).
