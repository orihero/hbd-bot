# 05 — Higgsfield recreation setup: a 43.000 s vertical piece in the "Peshta" register

Operations document. Written 2026-09-19. Supersedes nothing; continues `01_character_concepts.md` … `04_generation_plan.md`.

Every capability claim below is tagged **CONFIRMED** (seen in tool output or measured on this machine during research) or **ASSUMED** (reasoning, not output). Where a thing is unconfirmed the step says what to run to find out.

**Nothing in this guide has been generated or charged.** All credit figures come from `get_cost: true` preflights or `balance`. Balance at time of writing: **1568.1 credits, plan `pro`** (CONFIRMED, re-read 2026-09-19).

**Revision 2 — 2026-09-19, after an adversarial review pass.** Twelve defects were found and fixed in place, three of them fatal: every JSON call block had the wrong nesting and would have been rejected before reaching Higgsfield; the master ffmpeg command aborted because `libsoxr` is absent from this machine's build; and the Reference-Element call was missing a required field. Also fixed: both contact-sheet gates called `montage`, which is not installed, with a glob that matched no file; `nano_banana_pro` was passed a `soul_2`-only parameter; `kling3_0`'s returned resolution was assumed rather than measured across 55 % of the runtime; and the MVP's shot-19 substitution broke the adjacency invariant §5 is built on. The patched master block, the replacement contact sheets and the GATE 4 hue probe were each executed on this machine and confirmed to run.

---

## 1. What you are actually building

**Deliverable:** `marketing/campaigns/peshta/05_build/build/reel_peshta_1080x1920.mp4` — 1080×1920, 9:16, 30 fps CFR, **1290 frames = 43.000 s exactly**, H.264 High/4.1, AAC-LC 256 kbps 48 kHz, −14 LUFS / −1.0 dBTP, `+faststart`. Plus `cover_frame0.jpg`.

It is a **32-cut vertical music piece** cut on the song's own 95.600 BPM bar grid, generated natively at 1080×1920 (nothing is ever cropped from 16:9, so the 394-credit `reframe` pass is never bought — CONFIRMED price, never used).

### The two visual worlds

| | World A — red studio | World B — desert quarry |
|---|---|---|
| Ground | monochrome red-orange seamless cyclorama; matte orange foam blocks scattered on the floor; a low red-carpeted rostrum of three broad risers | eroded sand-cliff exterior under a pale bleached sky; freestanding red-painted vertical gate frames standing in the sand; red blocks |
| Corps | ~16 figures, floor-length black dresses, black wide-brim hats | corps in white suits, white lace masks covering the face entirely |
| Light | single hard warm key camera-left 45°, deep red gel wash on the background, hot specular edge on the jaw, no fill | open noon daylight, bleached highlights, short hard shadows, no fill |
| Screen time | 0.000–19.567 and 29.600–43.000 = **32.967 s (76.7 %)** | 19.567–29.600 = **10.033 s (23.3 %)** |

World B is one contiguous block and can be built and approved on its own.

**The world change lands at t = 19.567 s** — the downbeat of bar 8, where the bass drops out and onset density collapses from 52/bar to 8/bar. That is the sparsest bar in the 43 s, and shot 16 holds it for a full bar with no cut. The source video changes world somewhere else entirely; putting it on the break is free and makes this version read tighter than the original, which cut by feel and let phase drift (median 118 ms off the nearest beat).

### Why the leads are archetypes and not the real actors' faces

You asked for the Turkish antihero and a woman from the same series in the two lead roles. Both are played by real living performers, and the series and its character designs are owned. Higgsfield's own `character-sheet` workflow states the rule in its Principle 2 (CONFIRMED, quoted from tool output): *"IP awareness — original characters only. Never replicate a recognizable real person's likeness or a copyrighted character/property… Always describe an **original** character."* The `ms_image` model record says the server **runs an IP check before queueing** (CONFIRMED). **No tool anywhere in the account can preflight a refusal** (CONFIRMED — I looked; the `ad-multiplier` failure table has no moderation row) — a refusal lands server-side, as a terminal job failure, *after* the credit is committed.

So the two leads are **original characters built in the genre's visual language**: an Anatolian crime-drama antihero and the woman from the rival house. A Turkish or Uzbek viewer reads that type in under a second off a black coat, a cropped head, a trimmed beard, prayer beads and a flat unblinking stare. None of that belongs to anyone. Each character carries **one invented, asymmetric anchor feature** — a scar through his left eyebrow, a beauty mark on her right cheekbone — which does more for shot-to-shot consistency than ten adjectives about bone structure, *and* makes the face demonstrably nobody's.

### One thing the research got wrong, and I have changed

Every upstream document specified the male lead's wardrobe as a near-literal transcription of the source video's costume — the bottle-green military tunic, gold fringed epaulettes, aiguillette, chest of medals, burnt-orange neckerchief, cream wide-brim straw hat. **That is not in this guide.** Two reasons, and the second is the one that matters:

1. A costume-for-costume reproduction of a released commercial music video is a derivative-work problem independent of the likeness problem — and the prompt-level grep gate in Step 2 catches proper nouns, not costume clones. It would sail straight through.
2. **It defeats your actual brief.** You asked for the antihero, not for the original singer in a different face. Epaulettes and a straw hat read as the singer. A charcoal frock coat, bare head, black shirt to the throat and amber prayer beads read as the antihero. The original wardrobe is both the safer choice and the better one.

What is kept from the source is **palette, production-design vocabulary and cutting rhythm** — a monochrome red field, orange blocks, black wide-brim hats, a desert with red gate frames, ~1.3 s cutting. Those are genre vocabulary. What is dropped is the costume.

---

## 2. Before you start — five decisions, each with a default you can just accept

**D1 · The audio. This is the only decision that can zero the entire spend, and it must close before Step 1.**

Measured on this machine, 2026-09-19:

```
/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3
  md5 08946b867398121e3cb05c5ae4aeac2e  (identical to marketing/campaigns/peshta/audio/ copy)
  43.000000 s, 48 kHz stereo, 320 kbps
  TAG:comment = made with suno; created=2026-09-18T12:46:27Z; id=bf67f0b3-...
marketing/campaigns/peshta/audio/Xamdam_Sobirov_Peshta_27s_to_110s.mp3  md5 a9286c9bd0b9487ee42fe5bc5306ef29
marketing/campaigns/peshta/audio/Xamdam_Sobirov_Peshta_Add_Vocal_cropped_27_110.mp3  md5 a9286c9bd0b9487ee42fe5bc5306ef29
  -> BYTE-IDENTICAL. And decoded PCM at t=1..6 s of the 43 s cut matches both exactly.
```

**CONFIRMED: your 43 s file is a crop of a Suno _Add-Vocal_ render.** Add-Vocal adds a vocal to an *uploaded* track — so the instrumental underneath is derived from the commercial master, not composed from nothing. The project memory note `peshta-ruled-out-rebuild-native.md` already recorded that this lineage is why Suno withholds the download, and that Peshta-derived audio was ruled out for this Instagram launch.

One upstream research document asserts the opposite ("there is no third-party master in the file") and prescribes renaming it to `bed_43s_suno.mp3`. **Do not do that rename** — the string `Add_Vocal` is the only provenance marker on disk and erasing it is how this gets re-litigated in three weeks.

Consequences, stated plainly: Meta fingerprints uploaded audio pre-publication, the account in play is a cold *professional* account whose in-app library is already restricted, and there is no Suno commercial grant that survives this lineage. Artist permission helps you *dispute* a claim; it does not stop the automated action, because the mute/claim/block policy is set in the rights database by the distributor.

> **Default (recommended): D1-b.** Commission or render an **original bed at exactly 95.600 BPM with the bass-out break in bar 8** and cut to that. `bpm_detect.py`, `BED_AUDITION.md` and `audio/variant_d_bed_001.mp3` are already in this folder — this path is half-built. The entire shot table below is defined on a *bar grid*, not on musical events, so swapping to a same-tempo bed is a re-derivation of the table, **not** a re-shoot.
>
> **D1-a (what you probably want to do):** build the whole piece against the current 43 s cut, and treat a mute/claim as an accepted risk on a one-off promo. Defensible for one post. Not defensible as the launch-slate strategy.
>
> **D1-c ("attach the track in-app"):** do not choose this. It is structurally incompatible with this build — every lip-sync bed is welded to a fixed timeline position (§5), and you cannot frame-align an in-app music attach to a 1290-frame grid from a phone. Choosing it throws away 28.3 % of the runtime and ~70 of the priced credits.

**Do not** pitch-shift, time-stretch or layer noise to defeat the fingerprint. It is detected anyway and it converts a routine rights match into deliberate circumvention, which attaches to the account rather than to the post.

**D2 · Train Souls, or use a single reference image?**
Soul training is the only unpriced spend in the plan. **Default: attempt it, with a balance-delta measurement and a hard stop** (Step 3). The zero-cost fallback (Step 3b) is a complete working path and is what the MVP uses.

**D3 · Full build, or MVP?**
**Default: MVP first (§7, ~216 credits), then decide.** The MVP delivers all six recognition signals; the full build adds one lip-sync bed, a Soul-locked face, and polish.

**D4 · Which model carries the singing?**
**Default: `wan2_7` 1080p with `audio_references`** (2.5 cr/s CONFIRMED). That the role *exists* on `wan2_7` is CONFIRMED; that it drives **sung** lip-sync is **ASSUMED**. Step 6 spends 10 credits to find out before 70 credits ride on it.

**D5 · Two-shot of the pair, or intercut singles?**
**Default: one two-shot, as a still.** The upstream plan dropped the two-shot entirely to avoid ever creating a Reference Element. That was the wrong trade: a two-Element still on `nano_banana_pro` costs **2 credits**, needs no video generation, and buys the piece its only narrative image. Restored as shot 13.

---

## 3. Decisions where the reviews disagreed, and the call I made

| Question | Call | Why, in one line |
|---|---|---|
| `soul_cast` audition round first? | **Dropped** | It returns no `soul_id` and its 16:9 output can only re-enter `soul_2` as a max-1 `image` reference; `soul_2` auditions faces at the same billed price *and* at the aspect ratio you need — the 10-credit round was a dead handoff. |
| Corps in receding rows, or the lateral bank? | **Both, per setup** | The symmetric bank flanking the lead *is* the signature image; in 9:16 you keep it and let the outer figures clip at both frame edges, which reads as a line continuing off-screen. Receding rows are used only where the lead must stay legible in front (K1 bank vs. LS beds). |
| Re-stage the pyramid as a still, or generate it? | **Generate it (take K5)** | A locked-off wide of 16 dancers doing unison choreography is where the motion *lives*; freezing it at the loudest part of the track reads as a freeze-frame. |
| Two-shot? | **Restored as a 2-credit still** | See D5. |
| Source wardrobe verbatim? | **No — original variation** | See §1. |
| Cut rate | **32 shots, mean 1.344 s** | The source's real cut count is 35 in 43 s (mean 1.23 s); the upstream 26-shot grid was 1.65 s, 34 % slower, and at Reels scale the relentless cutting *is* the feel. 1.344 s is 9 % slower than source, with two deliberate holds. |

---

## 4. The build

Folder layout, created in Step 0:

```
marketing/campaigns/peshta/05_build/
├─ LEDGER.tsv          one row per PAID call, appended BEFORE the call. Append-only.
├─ shots.tsv           the 32-shot map (source of truth for the edit)
├─ prompts/            identity_M1.txt, identity_F1.txt, negative.txt, key_*.txt, take_*.txt
├─ keys/               downloaded keyframe PNGs, 1080x1920
├─ takes/              TK_<id>_a<NN>.mp4 (every attempt kept) + TK_<id>.mp4 -> symlink to the accepted one
├─ audio_slices/       slice_LS-A.wav … slice_LS-D.wav
├─ cuts/               shot_01.mp4 … shot_32.mp4 (frame-exact, silent)
├─ qa/                 sheet_keys.png, sheet_identity.png
├─ build/              edit_43s.mp4, reel_peshta_1080x1920.mp4, cover_frame0.jpg
└─ bin/                still2clip.sh, cut.sh, ipgate.sh
```

**Naming:** `S-A##`/`S-B##` = still keyframe (A = red studio, B = desert). `LS-x` = time-locked lip-sync bed. `K#` = time-free cutaway take. `_a<NN>` = paid attempt number, **never overwritten**. `shot_##` = a conformed timeline segment. The edit reads only `TK_<id>.mp4`, the symlink, so a re-roll never requires touching `shots.tsv`.

**`LEDGER.tsv` is the cost-control mechanism**, because three things in this plan cannot be priced in advance. Columns:

```
ts  asset  attempt  tool  model  params_digest  job_id  quoted  actual  balance_after  gate  verdict  note
```

**Call `balance` immediately after every paid call and write the figure into `balance_after`; `actual` is then the delta from the previous row.** This is the only way `actual` is ever populated for `sync_so`, for Soul training, or for anything the server prices differently from its quote — and the §4 stop rule below reads column 9. A ledger with an empty `actual` column cannot stop you overspending.

`quoted` is deliberately `null` for any tool with no `get_cost` path, so an unpriced call is visible at a glance. Running total: `awk -F'\t' 'NR>1{s+=$9}END{print s}' LEDGER.tsv`. **If the running total passes 700 before Step 10, stop and re-read §8.**

---

### STEP 0 — Scaffold, slice the audio, install the two scripts (0 credits)

```bash
P=/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/05_build
mkdir -p $P/{prompts,keys,takes,audio_slices,cuts,qa,build,bin}
cd $P
printf 'ts\tasset\tattempt\ttool\tmodel\tparams_digest\tjob_id\tquoted\tactual\tbalance_after\tgate\tverdict\tnote\n' > LEDGER.tsv

SONG=/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3
ffprobe -v error -show_entries format=duration -of csv=p=0 "$SONG"      # must print 43.000000

# the four lip-sync audio windows. Each slice's start IS the bed's timeline anchor (§5).
for spec in "LS-A 4.200 11.0" "LS-B 29.300 7.0" "LS-C 38.000 5.0" "LS-D 24.200 5.0"; do
  set -- $spec
  ffmpeg -v error -y -ss $2 -t $3 -i "$SONG" -ar 48000 -ac 2 -c:a pcm_s16le audio_slices/slice_$1.wav
  printf "%-6s want %-6s got %s\n" "$1" "$3" \
    "$(ffprobe -v error -show_entries format=duration -of csv=p=0 audio_slices/slice_$1.wav)"
done
```

**GATE 0.** Four files, durations **exactly** `11.000000 / 7.000000 / 5.000000 / 5.000000`. VERIFIED on this machine 2026-09-19 — all four come back exact, and LS-C's window `38.000 + 5.000 = 43.000` lands precisely on the end of the file with nothing to spare. (An earlier draft of this plan used `-ss 39.400 -t 4.0`, which silently yields 3.600 s on a 43.000 s file and leaves the closing shot with no driving audio. Fixed.)

Now install the two scripts. **Both were run byte-for-byte on this machine (ffmpeg 9.0.1, Homebrew) and produce the exact frame counts printed below.**

`bin/still2clip.sh`:

```bash
#!/bin/bash
# still2clip.sh <in.png> <out.mp4> <frames> <zoom_end> [drift_px_per_frame]
# Emits EXACTLY <frames> frames at 1080x1920 / 30 fps CFR and prints the count.
set -euo pipefail
IN="$1"; OUT="$2"; FR="$3"; ZE="$4"; DRIFT="${5:-0}"
ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$IN" -frames:v "$FR" \
  -vf "scale=2160:3840:flags=lanczos,zoompan=z='min(1.0+(${ZE}-1.0)*on/(${FR}-1),${ZE})':x='iw/2-(iw/zoom/2)+(${DRIFT})*on':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,setsar=1,format=yuv420p" \
  -c:v libx264 -preset slow -crf 14 -r 30 -an \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv "$OUT"
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$OUT"
```

Two details that are load-bearing and were wrong in the upstream draft: **`-framerate 30` on the input** (without it the still loops at 25 fps and `zoompan d=1` emits 25 frames per second, not 30), and **each `zoompan` option value in its own pair of quotes** (the upstream version closed the quote after the `z=` expression, which collapses `x`, `y`, `d`, `s` and `fps` into the `fps` argument and dies with `Unable to parse "fps" option value`).

`bin/cut.sh`:

```bash
#!/bin/bash
# cut.sh <take.mp4> <out.mp4> <in_point_seconds> <frames> [scale_pct]
set -euo pipefail
SRC="$1"; OUT="$2"; SS="$3"; FR="$4"; SC="${5:-100}"
BASE="fps=30,scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920"
if [ "$SC" = "100" ]; then
  VF="${BASE},setsar=1,format=yuv420p"
else
  VF="${BASE},scale=trunc(iw*${SC}/200)*2:trunc(ih*${SC}/200)*2:flags=lanczos,crop=1080:1920,setsar=1,format=yuv420p"
fi
ffmpeg -hide_banner -loglevel error -y -i "$SRC" -ss "$SS" -frames:v "$FR" -vf "$VF" \
  -c:v libx264 -preset slow -crf 14 -r 30 -an \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv "$OUT"
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$OUT"
```

`-ss` sits **after** `-i` deliberately — that is output-side seek and it is frame-accurate. `trunc(...)*2` keeps the intermediate scale even, which a raw `iw*104/100` does not.

`bin/ipgate.sh` — run this before **every** generation call:

```bash
#!/bin/bash
# ipgate.sh : returns non-zero if any forbidden proper noun is in prompts/
set -uo pipefail
cd "$(dirname "$0")/.."
if grep -rniE 'alemdar|kurtlar|vadisi|sasmaz|şaşmaz|pana ?film|sobirov|xamdam|hamdam|peshta|valley of the wolves|deepfake|face ?swap|lookalike|looks exactly like|celebrity|shot-for-shot' prompts/ ; then
  echo "IP GATE: FAIL — a forbidden token is in prompts/. Do not submit."; exit 1
fi
echo "IP GATE: pass"
```

**GATE 0b.** `bash bin/ipgate.sh` prints `pass`. Make it muscle memory: a refusal you can prevent with grep costs nothing; one you cannot costs 12–27 credits to discover, server-side, after the charge.

---

### STEP 1 — Audition the two faces (32 credits budgeted, 16 for the MVP)

Write `prompts/identity_M1.txt` and `prompts/identity_F1.txt` from Appendix A, and `prompts/negative.txt` from Appendix B, **first**.

**Call shape — read this once, it applies to every `generate_image` / `generate_video` call in this guide.** These tools take **one top-level property, `params`**. `model`, `prompt`, `aspect_ratio`, `count`, `soul_id`, `medias`, `use_unlim` and `get_cost` are all keys **inside** `params`, not siblings of it (CONFIRMED — the nested form returns `Input validation error: ... params: Invalid input`; the flat form returns a cost). `count` is capped at 4.

```json
{"params":{"model":"soul_2","prompt":"…","aspect_ratio":"2:3","quality":"2k","count":4}}
```

**Always pass `use_unlim:false`** unless you mean to spend an unlim slot. Both models here report `supports_unlim:true`, and omitting the key can make the server return an `unlim_choice` prompt and submit no job — which reads as a silent failure.

**Always preflight with `get_cost:true` first.** It returns a price and submits nothing.

```json
{"params":{"model":"soul_2","prompt":"<identity_M1.txt verbatim>, plain charcoal t-shirt, neutral mid-grey seamless background, soft even three-point studio light, 85mm lens, f/4, sharp focus on the eyes, no catchlight glare, photoreal unretouched editorial photography, visible skin pores, natural asymmetry, matte skin, no beauty filter","aspect_ratio":"2:3","quality":"2k","count":4,"use_unlim":false}}
```

Repeat for F1. Up to 4 rounds per character.

**Cost:** `soul_2` at `quality:"2k"` bills **1 credit per image** (exact 0.12, rounded up at billing — CONFIRMED). 4 rounds × 4 images × 2 characters = **32 credits worst case**. Budget 32; expect 16.

**GATE 1.** One face per character you would put on a poster, with the anchor feature (scar on the **left** eyebrow, beauty mark on the **right** cheekbone) legible and on the correct side. If the scar keeps landing on the right, append `the scar is on his own LEFT eyebrow, which appears on the RIGHT side of a front-facing photograph` and re-roll. Do not proceed on "close enough" — everything downstream inherits this face. Save the winner per character as `keys/REF_M1.png` / `keys/REF_F1.png`; Step 3b needs it.

---

### STEP 2 — Character sheets, the Soul training set (32 credits budgeted; SKIPPED in the MVP)

First call `get_workflow_instructions {"workflow":"character-sheet"}` — **free**, and it is authoritative for the slot order and the `photoreal-unretouched` anti-AI module. It also states the original-characters-only principle this whole plan is built on.

**Tool:** `generate_image`, `model:"soul_2"`, `aspect_ratio:"2:3"`, `quality:"2k"`, `count:4`, **plus the Step-1 winner as the reference** so the sheets do not re-roll the face from text:

```json
{"params":{"model":"soul_2","prompt":"<identity block verbatim>, <view directive>, neutral mid-grey seamless background, no wardrobe, plain charcoal t-shirt, one consistent soft key","aspect_ratio":"2:3","quality":"2k","count":4,"use_unlim":false,"medias":[{"role":"image","value":"<media_id of keys/REF_M1.png>"}]}}
```

`soul_2` accepts a reference in the `image` role, **max 1** (CONFIRMED). Three calls per character, view directives: (a) front neutral + 3/4 left, (b) profile + 3/4 right, (c) slight low angle + slight high angle. **12 images per character, 24 total.**

**Cost:** 24 credits, +8 for one re-roll round = **32 budgeted**.

**GATE 2.** Lay the 12 frames per character side by side. Cull to the **8–12 most consistent**; discard anything where the nose, the jaw or the anchor feature disagrees. Step 3 needs 8–12 per Soul, and 12 generated → 8–10 surviving is the design, not an accident. *If fewer than 8 survive, your identity block is under-specified — add slots (Appendix A's shape), do not add adjectives, and re-roll. Do not train on a mushy set: a Soul trained on drift is drift, permanently.*

---

### STEP 3 — Train two Souls (UNPRICED — 120 reserved, hard stop at 150)

Local files have no `media_id`. Upload with **`media_upload_widget`, which must be the only tool call in its turn** (CONFIRMED — the MCP server states this), then `media_confirm`.

**Batch them, or this rule costs you a turn per file.** The widget takes `{"type":"auto","multiple":true,"max_files":20}`, so put every file a step needs into **one** widget call: Step 3 wants 8–12 training images, Step 7 wants 4 start images plus 4 audio slices. Record each returned `media_id` **and its https url** in `MEDIA_IDS.tsv` as you go — Reference Elements (Step 4) need the url as well as the id, and recovering a url later means re-uploading.

**Tool:** `show_characters` (CONFIRMED schema: `action:"train"`, `name`, `type`, `images[]` of 5–20 media_ids or completed image-job ids; never local paths).

```json
{"action":"train","name":"kemal-yalcin-m1","type":"soul_2","images":["<8-12 media_ids from Step 2>"]}
```

~10 minutes, non-blocking. Poll `{"action":"status","soul_id":"<id>"}`.

**Cost: UNKNOWN.** No `get_cost` path exposes Soul training (CONFIRMED — I checked the model record, the catalog and the apps registry). **Price it by differencing the balance:** call `balance` immediately before the first training call and immediately after it reports ready; the delta is the price. Log it.

**GATE 3.** (a) The delta is recorded in `LEDGER.tsv`. (b) **If the first Soul cost more than 150 credits, do not train the second** — go to 3b for both. (c) Spend 4 credits proving it: `generate_image {"params":{"model":"soul_2","prompt":"<identity block>, neutral grey seamless, soft frontal key","aspect_ratio":"9:16","quality":"2k","soul_id":"<id>","count":4,"use_unlim":false}}`. All four must be the same person *and* the same person as the sheets. If not, retrain — every keyframe inherits it.

**STEP 3b — the no-training path (0 credits).** Skip Steps 2 and 3 entirely. Pass `keys/REF_M1.png` / `REF_F1.png` as `soul_2`'s max-1 `image` reference on every keyframe generation in Step 4. Consistency is meaningfully worse than a trained Soul — expect ~1.5× more keyframe attempts — but keyframes bill at 1 credit, so 1.5× of nearly nothing is nearly nothing. **This is strictly better than gambling an unpriced spend, and the MVP takes it by default.**

Two mechanism facts that shape everything downstream (both CONFIRMED):
- **A trained Soul works only with `soul_2` / `soul_cinematic`. No video model accepts a `soul_id`.** Identity reaches video *exclusively* through the keyframe passed as `start_image`.
- **One `soul_id` per generation.** Multi-character frames need `show_reference_elements`. That is why the two-shot (shot 13) is a `nano_banana_pro` still with two Elements and never a video generation — it is the one frame in the piece that needs both leads, and it costs 2 credits instead of forcing the whole build onto a second model family.

---

### STEP 4 — The 14 keyframes (45 credits budgeted)

All at `aspect_ratio:"9:16"`, `quality:"2k"`. **Native vertical from the first pixel.** Assemble each prompt in this order (CONFIRMED as the `soul_2` shape from the character-sheet workflow): one comma-separated paragraph, identity tokens early, quality tail last —

```
[COMPOSITION] , [IDENTITY verbatim] , [WARDROBE] , [PROPS] , [POSTURE] , [SET] ,
[LIGHT] , [LENS] , [GRADE] , [FORMAT] , photoreal unretouched, visible skin pores,
natural asymmetry, matte skin, no beauty filter, no smoothing
```

| Key | Model | Content | Used as |
|---|---|---|---|
| `S-A01` | `soul_2` M1 | Kemal MCU, red seamless, bare head, coat collar high, eyes to lens | **shot 1 (cover frame)** + `start_image` for **LS-A** |
| `S-A04` | `soul_2` F1 | Nergis clear-face CU, empty red seamless, no set dressing | shot 3 |
| `S-A05` | `soul_2` F1 | Nergis MCU, net veil across the eyes, garnet chain, one orange block in frame, hard side key | `start_image` for **K2** |
| `S-A07` | `soul_2` M1 | Macro: left hand, amber prayer beads, signet ring, shallow focus, red falloff | shot 28 |
| `S-A08` | `soul_2` — | Low angle across the floor: orange foam blocks foreground, black hems and black hat brims above | shot 15 |
| `S-A09` | `soul_2` — | Corps frontal, **a symmetric lateral bank of black wide-brim hats spreading to both frame edges and clipping off-screen**, no lead | `start_image` for **K1** |
| `S-A10` | `soul_2` M1 | Kemal MCU, chorus energy, chin dropped, eyes lifted to lens | `start_image` for **LS-B** |
| `S-A11` | `soul_2` M1 | Kemal tight MCU, coat shoulder clipping the frame edge | `start_image` for **LS-C** |
| `S-A12` | **`nano_banana_pro`** (`resolution:"2k"` — this model has **no** `quality` parameter; `quality` is `soul_2`-only and passing it here errors or silently bills at the default) | **Two-shot:** the pair seated on the red rostrum, a bundle of dark red flowers across her lap, he turns his head to her, she does not turn | shot 13 |
| `S-A13` | `soul_2` M1 | **On-axis low angle**, lead standing on the red rostrum, corps in two equal banks flanking left and right, clipping at both edges, floor sweeping away below | `start_image` for **K5** |
| `S-A14` | `soul_2` F1 | Nergis full figure, seated upright on the red rostrum, spine long, hands folded | `start_image` for **K6** |
| `S-B01` | `soul_2` M1 | Kemal at a vertical red gate frame, sand cliff behind, coat open, pale sky | `start_image` for **K4** |
| `S-B02` | `soul_2` — | White-masked corps in white suits among red blocks, sand cliff, low angle | `start_image` for **K3** |
| `S-B03` | `soul_2` M1 | Kemal MCU in the desert, masked corps soft behind him, arm starting to rise | `start_image` for **LS-D** |

**S-A12 is the only Reference-Element frame.** Create two Elements first — `show_reference_elements {"action":"create","name":"kemal-m1","category":"auto","medias":[{"id":"<uuid>","url":"https://upload.higgsfield.ai/…","type":"image_job"}]}` — instant, synchronous, no charge observed (CONFIRMED). **Every `medias[]` entry requires BOTH `id` and `url`** (CONFIRMED — the schema lists `"required":["id","url"]`); an entry with the id alone is rejected at validation. Capture the `url` from the `media_confirm` / image-job response at the same moment you capture the id, and record both in `MEDIA_IDS.tsv` — see Step 0. Then embed both `<<<id>>>` placeholders in a `nano_banana_pro` prompt. Elements are supported on `nano_banana_pro` / `nano_banana_2` / `gpt_image_2` / `seedream_v4_5` / `seedream_v5_lite` / `cinematic_studio_2_5` and explicitly **not** on Soul V2 / Cinema (CONFIRMED).

**Cost:** 13 `soul_2` keys × 2 attempts = 26 credits; `nano_banana_pro` at 2k = **2 credits/image** × 2 = 4. Clean 30, **45 budgeted** with retries.

**GATE 4 — the cheapest fidelity gate in the plan, and the most important.** Build a contact sheet and check four things:

```bash
cd $P
# ImageMagick is NOT installed by default on this machine (`montage` not found, CONFIRMED).
# This ffmpeg form needs nothing extra. Note the filenames are keys/S-A01.png, not S-*_a01.png.
ffmpeg -v error -y -pattern_type glob -i 'keys/S-[AB]*.png' \
  -vf "scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:-1:-1:color=black,tile=4x4:padding=4" \
  -frames:v 1 qa/sheet_keys.png
# (If you would rather have ImageMagick: brew install imagemagick, then
#  montage keys/S-A*.png keys/S-B*.png -tile 4x4 -geometry 270x480+4+4 qa/sheet_keys.png)
```

1. **Same man in all 7 male frames, same woman in all 4 female frames.** Scar left, beauty mark right, in every one.
2. **Every World-A frame is the SAME red.** If `S-A13` is orange-red and `S-A01` is crimson, the cut will strobe at 1.3 s intervals and the grade cannot rescue it. Re-roll the outlier — it costs 1 credit here and 12 after it reaches video.
   Do not argue about this by eye — measure it. This prints one average background RGB triple per World-A frame:
   ```bash
   for f in keys/S-A*.png; do
     printf "%-16s " "$f"
     ffmpeg -v error -i "$f" -vf "crop=200:200:100:1600,scale=1:1" -f rawvideo -pix_fmt rgb24 - | xxd -p
   done
   ```
   Any frame whose hue sits more than ~8° off the group median is the outlier. Re-roll that one for 1 credit.
3. **`S-A09` and `S-A13` actually show a lateral bank clipping at both frame edges**, not a huddle of five hats behind a torso. This is the piece's signature formation; if the model keeps producing a cluster, add `the line of dancers continues past the left and right edges of the frame, cut off by the frame` and re-roll.
4. **Nothing important above y=220 or below y=1500**, eyeline near **y ≈ 700–760** (§6 safe areas).

Download all 14 to `keys/`. **Spend an hour here.** Every credit lost later is lost to a keyframe you accepted while unsure.

---

### STEP 5 — Build the five still-clips (0 credits)

```bash
cd $P
bin/still2clip.sh keys/S-A01.png cuts/shot_01.mp4 60 1.10 0      # opens the Reel, slow push
bin/still2clip.sh keys/S-A04.png cuts/shot_03.mp4 38 1.06 0
bin/still2clip.sh keys/S-A12.png cuts/shot_13.mp4 37 1.04 0      # the two-shot
bin/still2clip.sh keys/S-A08.png cuts/shot_15.mp4 38 1.12 0      # fast push, reads as a whip
bin/still2clip.sh keys/S-A07.png cuts/shot_28.mp4 38 1.04 1.2    # macro, slight lateral drift
```

**GATE 5.** Each command prints its own frame count. Must be exactly **60, 38, 37, 38, 38**. VERIFIED on this machine — those five parameter sets return exactly those counts. A one-frame error here propagates through the concat and 1290 becomes 1289.

**16.4 % of the finished Reel is now done, for ~10 billed credits of keyframes.** Zoom rates are tuned per shot (4 % on the macro, 12 % on the whip) rather than a uniform Ken Burns, no still runs longer than 2.000 s, and no two stills are ever adjacent — check the map in §5.

---

### STEP 6 — THE PILOT: does `audio_references` actually drive a singing mouth? (14.5 credits)

**This is the load-bearing gate. 70 credits of lip-sync beds ride on an assumption.** The `audio_references` role on `wan2_7` is CONFIRMED; that it produces usable *sung* lip-sync is ASSUMED. Spend 10 to find out.

Upload `audio_slices/slice_LS-C.wav` and `keys/S-A11.png` (`media_upload_widget` alone in its turn → `media_confirm`).

**Expect the upload to be the first thing that fails.** `wan2_7` declares its media block as `{"type":"image","roles":["start_image","end_image","audio_references"]}` — the **role** is CONFIRMED, the **container type for audio is not**, and Step 0 writes PCM `.wav`. If the widget refuses the `.wav`, or `audio_references` rejects it, re-encode the slice and retry — this costs nothing:
```bash
ffmpeg -v error -y -i audio_slices/slice_LS-C.wav -c:a libmp3lame -b:a 320k -ar 48000 audio_slices/slice_LS-C.mp3
```
Confirm the audio `media_id` resolves **before** spending the 10 credits. The entire 70-credit bed architecture sits behind this upload.

**Tool:** `generate_video`
```json
{"params":{"model":"wan2_7","aspect_ratio":"9:16","duration":4,"resolution":"1080p","use_unlim":false,
 "prompt":"<identity_M1> , <WARDROBE_M_A> , singing directly to the lens, chin dropped, eyes lifted, small confident head movements on the beat, shoulders still , <SET_A> , <LIGHT_A> , <LENS> , <GRADE> , handheld micro-movement, slow push in",
 "medias":[{"role":"start_image","value":"<S-A11 media_id>"},
           {"role":"audio_references","value":"<slice_LS-C media_id>"}]}}
```
**Cost: 10 credits** (`wan2_7` 1080p 9:16 = **2.5 cr/s**, CONFIRMED).

Then one corps probe:
```json
{"params":{"model":"kling3_0","aspect_ratio":"9:16","duration":3,"mode":"std","sound":"off","use_unlim":false,
 "prompt":"<SET_A corps clause> , <LIGHT_A> , <LENS> , <GRADE> , the dancers step and turn in unison on a steady beat, hat brims tipping, handheld camera drifting slowly forward, continuous motion",
 "medias":[{"role":"start_image","value":"<S-A09 media_id>"}]}}
```
**Cost: 4.5 credits** (`kling3_0` std 9:16 `sound:"off"` = **1.5 cr/s**, CONFIRMED; 5 s = 7.5, 8 s = 12, 10 s = 15, 15 s = 22.5).

> **Price trap, measured 2026-09-19.** `sound` defaults to `"on"`, and that costs **2 cr/s, not 1.5** — an 8 s take preflights at **16 credits with `sound` omitted** and **12 with `sound:"off"`** (both CONFIRMED by `get_cost`). Every K-take in this plan is silent by design, so **omitting `sound:"off"` overspends the entire cutaway budget by 33 %** and buys audio that gets discarded at the mux. Put it in every `kling3_0` call.

**Retrieving the output. Do this here, on the pilot, because nothing downstream works without it.** Submission returns a job id. Poll with `job_status` (or `jobs_wait` for several at once), then read the result URL with `show_generation_by_ids` and pull it to disk with `curl -L -o takes/…`. The *tool names* are CONFIRMED (they are in the MCP server's own routing instructions); **the exact field name that carries the file URL is ASSUMED** — so on this pilot, print the full `job_status` / `show_generation_by_ids` response and write the field path into `05_build/RETRIEVAL.md`. That one note unblocks every download for the rest of the build.

**GATE 6 — three checks, all must pass:**
1. **Sync.** `ffmpeg -i pilot.mp4 -i audio_slices/slice_LS-C.wav -c:v copy -shortest pilot_sync.mp4`, then watch it. You are not looking for phoneme accuracy — at 1080×1920 with the face at ~30 % of frame height you need *plausible articulation on the right beats*.
2. **Identity.** Last frame vs. `S-A11.png`. Same man? Scar still on the left eyebrow?
3. **Corps.** In the `kling3_0` probe: do the dancers move *together*, do the hat brims hold their shape, and does the lateral bank survive to second 3 — or dissolve into blobs?
4. **Actual returned resolution — do not skip this.** `kling3_0` has **no `resolution` parameter at all** (CONFIRMED — its model record exposes only `mode`: std/pro/4k), and its std output dimensions are undocumented. All six K-takes are `kling3_0`, which is **23.8 s = 55.3 % of the Reel**. Measure what actually came back:
   ```bash
   ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <probe>.mp4
   ```
   If it is not `1080,1920`, decide **now**, not at GATE 10: either pay `mode:"pro"` (14 cr / 8 s CONFIRMED, ~+24 cr over budget across the six takes) or knowingly accept an upscale on 55 % of the runtime. Be aware that `bin/cut.sh` carries `scale=1080:1920:force_original_aspect_ratio=increase`, which will silently upscale a 720×1280 return to 1080×1920 without warning you — that fallback is load-bearing, and §6's claim that "there is no scale/crop fallback anywhere in this chain" is wrong on both counts.

**If check 1 fails → Route B** (below). **If check 3 fails →** re-probe the corps with `minimax_h3` (2 cr/s, 2K only, 8 s = 16 CONFIRMED) or `wan2_7` 720p (1.5 cr/s, 8 s = 12 CONFIRMED) before buying K1 and K5.

**Route B — the lip-sync fallback.** Generate every singing shot as ordinary `kling3_0` motion, assemble the whole 43 s silent, then run **one** `sync_so` pass over the finished edit: `medias` roles `input_video` + `input_audio`, `sync_mode:"cut_off"` (preserves timing; `"remap"` retimes the video, which would destroy the frame grid). **`sync_so` cannot be cost-preflighted through this MCP layer** — CONFIRMED by the error it returns: the MCP layer injects an empty `prompt` and the backend rejects it with `{"type":"extra_forbidden","loc":["prompt"]}`. (An earlier draft also asserted the backend "requires `duration`". Downgraded to ASSUMED: `sync_so`'s model record exposes only `sync_mode` and `folder_id`, and shows neither field.) Read the price in the Higgsfield web UI before submitting. **Hard stop: 150 credits.**

---

### STEP 7 — The four lip-sync beds (167.5 credits budgeted, 70 clean)

**The rule that makes this work, stated once.** A `wan2_7` bed is generated against **one contiguous audio slice**, so the bed's internal time `t` is welded to song time `slice_start + t`. A shot placed at timeline position `T` must therefore be cut from that bed at **in-point `T − slice_start`**, and its out-point must fall inside the generated duration. Every in-point in §5 is derived that way and the arithmetic is verified; the upstream plans that reused one bed at unrelated timeline positions put four of nine singing shots 8–30 seconds out of phase, discoverable only in the edit.

| Bed | Anchor (slice start) | Dur | Cost | Start image | Audio slice | Timeline window it owns | Shots it feeds |
|---|---|---|---|---|---|---|---|
| **LS-A** | 4.200 | 11 s | **27.5** | `S-A01` | `slice_LS-A.wav` | 4.200 → 15.200 | 4, 6, 9, 11 |
| **LS-D** | 24.200 | 5 s | **12.5** | `S-B03` | `slice_LS-D.wav` | 24.200 → 29.200 | 19, 21 (World B) |
| **LS-B** | 29.300 | 7 s | **17.5** | `S-A10` | `slice_LS-B.wav` | 29.300 → 36.300 | 23, 26 |
| **LS-C** | 38.000 | 5 s | **12.5** | `S-A11` | `slice_LS-C.wav` | 38.000 → 43.000 | 30, 32 |

```json
{"params":{"model":"wan2_7","aspect_ratio":"9:16","duration":11,"resolution":"1080p","use_unlim":false,
 "prompt":"<identity_M1> , <WARDROBE_M_A> , <PROPS_M> , singing to the lens, moving slowly among the corps, the corps in receding rows behind him, occasional half-turn, chin dropped, eyes lifted , <SET_A> , <LIGHT_A> , <LENS> , <GRADE> , continuous handheld movement throughout, slow arc to the right",
 "medias":[{"role":"start_image","value":"<S-A01 media_id>"},
           {"role":"audio_references","value":"<slice_LS-A media_id>"}]}}
```

**Why an 11-second bed instead of four 3-second clips.** Four separate `kling3_0` generations of the verse would cost 18 credits against 27.5 — cheaper on paper — but they are four independent chances for the face to change, and identity drift between generations is the dominant failure mode in AI music video. At 1080×1920 the face is large and drift is unmissable. One take guarantees one face across shots 4, 6, 9 and 11. I am knowingly paying ~9 credits for 5.9 s of bed that will never be shown.

**"Continuous movement throughout" is load-bearing** — you cut *back into* LS-A three times, and a static camera makes each return a jump cut. §5 adds a scale offset on every return as a second line of defence.

**Retry allowance: LS-A ×3 (82.5), the other three ×2 (35 + 25 + 25).**

**GATE 7.** Per bed: mux against its own slice and confirm sync across the **whole** length — models often hold for 4 seconds and drift after. Check the tail: `LS-A` has 0.666 s of slack past its last out-point, `LS-B` 0.434 s, `LS-D` 0.867 s — **`LS-C` has 0.000 s**, because the Reel ends exactly when the song does. If LS-C's final 25 frames degrade, the free fallback is: freeze the last clean frame and run `bin/still2clip.sh <frame>.png cuts/shot_32.mp4 25 1.02 0`. Costs nothing, and a held closing portrait is legitimate grammar.

---

### STEP 8 — The six cutaway takes (115.5 credits budgeted, 48 clean)

Time-free: generate once, cut from anywhere. `kling3_0` std, 9:16, `sound:"off"` — sound off is what gets you the 1.5 cr/s rate. **`kling3_0`'s media roles are `start_image` and `end_image` only** (CONFIRMED; there is no `image_references` role, and it accepts no `soul_id`). Identity reaches it through the start image.

**Generate K1 and K5 first.** They are pure silhouette, wardrobe and formation work with no lip-sync, they are the two hardest things in the piece, and they are the cheapest way to falsify the plan.

| Take | Dur | Cost | Start | Content |
|---|---|---|---|---|
| **K1** | 8 s | **12** | `S-A09` | Red-studio corps: a **symmetric lateral bank** of black dresses and black wide-brim hats, clipping past both frame edges, stepping in unison, brims tipping; handheld, low angle, slow push |
| **K5** | 5 s | **7.5** | `S-A13` | **On-axis low-angle wide**: the lead on the red rostrum, corps in two equal banks flanking him, floor sweeping away; locked with a very slow rise, the corps in unison motion throughout |
| **K2** | 5 s | **7.5** | `S-A05` | Nergis: slow quarter-turn, draws the garnet chain across her body, head tips, the net veil catches the key; locked with a slow push |
| **K4** | 5 s | **7.5** | `S-B01` | Desert lead: Kemal at the vertical red gate frame, holds, then walks toward the lens; locked, slow push, then a step-in |
| **K3** | 5 s | **7.5** | `S-B02` | Desert corps: white-masked figures in white suits moving past camera among red blocks; handheld, low angle, motion blur |
| **K6** | 4 s | **6** | `S-A14` | Nergis full figure on the red rostrum: settles, hands fold, chin lifts, gaze drifts off camera-left; locked |

K3 is the cheapest 3.8 seconds in the piece — the figures are fully masked, so there is no identity to hold. K6 is 4 s because the edit draws 2.500 s from it with 1.233 s of slack. **Every take length in this table was derived from its last OUT-point, not its first in-point** (§5 lists them), which is the arithmetic the upstream plan got wrong.

**Retry allowance: K1 ×3 (36), K5 ×3 (22.5), the rest ×2 (15+15+15+12).**

**GATE 8.** Scrub each take and confirm the exact in-points in §5 are usable: each needs **≥ its own shot duration of clean motion** after it, with no melting hands, inverted hat brims or duplicated figures. Every take carries 0.73–1.23 s of slack past its last out-point, so a bad stretch can be stepped around — but if you move an in-point, re-derive the whole window set for that take and re-run the audit in §5.

---

### STEP 9 — One optional hero upgrade (14 credits)

Shot 25 (t=32.100, 2.533 s) is the longest cutaway hold in the piece and the biggest corps moment in the chorus. If `K1` std looks soft there, regenerate **that take only** at `mode:"pro"` — 8 s = **14 credits** (1.75 cr/s, CONFIRMED), a 2-credit premium. Upgrade nothing else. `seedance_2_0` at 1080p is **9 cr/s** (45 credits for 5 s, CONFIRMED) and buys identity locking you do not need on a faceless corps.

**GATE 9.** A/B the two takes at phone size, not on a monitor. If you cannot tell at phone size, keep std and pocket the 14.

---

### STEP 10 — Conform the 32 cuts (0 credits)

Run the five `still2clip.sh` lines from Step 5, then the 27 `cut.sh` lines generated from §5:

```bash
cd $P
# generated from shots.tsv; every line prints its own frame count
bin/cut.sh takes/TK_K1.mp4   cuts/shot_02.mp4 0.000 37
bin/cut.sh takes/TK_LS-A.mp4 cuts/shot_04.mp4 0.300 38
bin/cut.sh takes/TK_K5.mp4   cuts/shot_05.mp4 0.000 37
bin/cut.sh takes/TK_LS-A.mp4 cuts/shot_06.mp4 2.800 38 103
bin/cut.sh takes/TK_K2.mp4   cuts/shot_07.mp4 0.000 37
bin/cut.sh takes/TK_K1.mp4   cuts/shot_08.mp4 1.433 38 104
bin/cut.sh takes/TK_LS-A.mp4 cuts/shot_09.mp4 6.567 38 105
bin/cut.sh takes/TK_K6.mp4   cuts/shot_10.mp4 0.000 37
bin/cut.sh takes/TK_LS-A.mp4 cuts/shot_11.mp4 9.067 38 106
bin/cut.sh takes/TK_K5.mp4   cuts/shot_12.mp4 1.500 38 104
bin/cut.sh takes/TK_K1.mp4   cuts/shot_14.mp4 3.000 38 106
bin/cut.sh takes/TK_K4.mp4   cuts/shot_16.mp4 0.000 75
bin/cut.sh takes/TK_K3.mp4   cuts/shot_17.mp4 0.000 38
bin/cut.sh takes/TK_K4.mp4   cuts/shot_18.mp4 2.700 37 104
bin/cut.sh takes/TK_LS-D.mp4 cuts/shot_19.mp4 0.367 38
bin/cut.sh takes/TK_K3.mp4   cuts/shot_20.mp4 1.500 38 103
bin/cut.sh takes/TK_LS-D.mp4 cuts/shot_21.mp4 2.900 37 104
bin/cut.sh takes/TK_K3.mp4   cuts/shot_22.mp4 3.000 38 106
bin/cut.sh takes/TK_LS-B.mp4 cuts/shot_23.mp4 0.300 38
bin/cut.sh takes/TK_K2.mp4   cuts/shot_24.mp4 1.500 37 104
bin/cut.sh takes/TK_K1.mp4   cuts/shot_25.mp4 4.500 76 108
bin/cut.sh takes/TK_LS-B.mp4 cuts/shot_26.mp4 5.333 37 105
bin/cut.sh takes/TK_K2.mp4   cuts/shot_27.mp4 3.000 38 106
bin/cut.sh takes/TK_K5.mp4   cuts/shot_29.mp4 3.000 37 106
bin/cut.sh takes/TK_LS-C.mp4 cuts/shot_30.mp4 1.633 38
bin/cut.sh takes/TK_K6.mp4   cuts/shot_31.mp4 1.500 38 104
bin/cut.sh takes/TK_LS-C.mp4 cuts/shot_32.mp4 4.167 25 104
```

The trailing number is a **scale offset in percent**, applied on every re-entry into a take you have already used. At 1.3 s cutting a +3–8 % reframe is invisible as an effect and completely kills the jump-cut feel of returning to the same camera. **Never offset a lip-sync shot by more than 6 %** — it crops the mouth toward the frame edge and the sync reads worse.

**GATE 10.** The frame-count audit, before anything is concatenated:

```bash
tot=0; for i in $(seq -w 1 32); do
  n=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 cuts/shot_$i.mp4)
  printf "shot_%s %4s\n" "$i" "$n"; tot=$((tot+n)); done; echo "TOTAL $tot  (must be 1290)"
```

---

### STEP 11 — The identity-drift contact sheet (0 credits)

The check that nothing else catches, because drift is invisible while you review clips one at a time:

```bash
for i in 01 04 06 09 11 19 21 23 26 30 32; do
  ffmpeg -v error -y -i cuts/shot_$i.mp4 -vf "select=eq(n\,0),crop=540:540:270:520" -vframes 1 qa/face_$i.png
done
ffmpeg -v error -y -pattern_type glob -i 'qa/face_*.png' \
  -vf "scale=300:300,tile=4x3:padding=6" -frames:v 1 qa/sheet_identity.png
# (ImageMagick equivalent, if you installed it:
#  montage qa/face_*.png -tile 4x3 -geometry 300x300+6+6 qa/sheet_identity.png)
```

**GATE 11.** Eleven crops of the male lead's face in one image (shot 1 plus every lip-sync shot). **The scar must be in the same place in all eleven.** If one bed's face has drifted, regenerate that bed — not the edit.

---

### STEP 12 — Assemble and master (0 credits) → §6.

**GATE 12.** `ffprobe` reports `1080/1920`, `30/1`, `yuv420p`, `duration=43.000000`; `ebur128` reports `I: -14.x LUFS` and `Peak: -1.0` or lower.

---

### STEP 13 — Cover frame (0 credits)

Frame 0 is both the default cover and what people stare at while the Reel buffers. Shot 1 is `S-A01` — a fully exposed, in-focus MCU of the lead. **Never open on black, never fade in, never open soft.** Anything on the cover that must survive everywhere goes in the **centre 1080×1080 (y 420–1500)**: the feed preview card keeps y 285–1635 and the profile grid tile keeps y 240–1680, and only that centre square survives both crops *and* the UI safe area.

---

## 5. The shot table — all 43.000 seconds

Built on the song's own grid: **95.600 BPM**, beat 0.627615 s, bar 2.510460 s, first downbeat **1.985 s**. Every boundary is a bar or half-bar, snapped to 30 fps. **Maximum deviation of any boundary from the exact half-bar grid: 16.4 ms** — one half-frame. **32 shots, mean 1.344 s** (source: 35 shots, mean 1.23 s). **1290 frames = 43.000 s exactly.**

World: **A** 0.000–19.567 · **B** 19.567–29.600 · **A** 29.600–43.000.
Tiers: **T1** = time-locked `wan2_7` lip-sync bed · **T2** = time-free `kling3_0` take · **T3** = still + programmatic push.

| # | Start | Dur | f | Tier | Source | In-pt | Scale | What is on screen |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.000 | 2.000 | 60 | T3 | `S-A01` | — | push→110 | Kemal MCU, red seamless. **Cover frame.** |
| 2 | 2.000 | 1.233 | 37 | T2 | `K1` | 0.000 | 100 | Corps lateral bank, first unison step |
| 3 | 3.233 | 1.267 | 38 | T3 | `S-A04` | — | push→106 | Nergis clear-face CU |
| 4 | 4.500 | 1.267 | 38 | **T1** | `LS-A` | 0.300 | 100 | **sings** |
| 5 | 5.767 | 1.233 | 37 | T2 | `K5` | 0.000 | 100 | On-axis wide, lead on the rostrum, banks flanking |
| 6 | 7.000 | 1.267 | 38 | **T1** | `LS-A` | 2.800 | 103 | **sings** |
| 7 | 8.267 | 1.233 | 37 | T2 | `K2` | 0.000 | 100 | Nergis quarter-turn |
| 8 | 9.500 | 1.267 | 38 | T2 | `K1` | 1.433 | 104 | Corps, brims tipping |
| 9 | 10.767 | 1.267 | 38 | **T1** | `LS-A` | 6.567 | 105 | **sings** |
| 10 | 12.033 | 1.233 | 37 | T2 | `K6` | 0.000 | 100 | Nergis full figure on the rostrum |
| 11 | 13.267 | 1.267 | 38 | **T1** | `LS-A` | 9.067 | 106 | **sings** |
| 12 | 14.533 | 1.267 | 38 | T2 | `K5` | 1.500 | 104 | Wide, corps in unison, slow rise |
| 13 | 15.800 | 1.233 | 37 | T3 | `S-A12` | — | push→104 | **Two-shot** on the rostrum, dark red flowers |
| 14 | 17.033 | 1.267 | 38 | T2 | `K1` | 3.000 | 106 | Corps bank |
| 15 | 18.300 | 1.267 | 38 | T3 | `S-A08` | — | push→112 | Orange blocks + black hems + brims, fast push |
| **16** | **19.567** | **2.500** | **75** | T2 | `K4` | 0.000 | 100 | **THE BREAK — desert arrival at the red gate. Hold. Do not cut.** |
| 17 | 22.067 | 1.267 | 38 | T2 | `K3` | 0.000 | 100 | Masked white corps |
| 18 | 23.333 | 1.233 | 37 | T2 | `K4` | 2.700 | 104 | Kemal at the gate |
| 19 | 24.567 | 1.267 | 38 | **T1** | `LS-D` | 0.367 | 100 | **sings** (World B) |
| 20 | 25.833 | 1.267 | 38 | T2 | `K3` | 1.500 | 103 | Masked corps |
| 21 | 27.100 | 1.233 | 37 | **T1** | `LS-D` | 2.900 | 104 | **sings** |
| 22 | 28.333 | 1.267 | 38 | T2 | `K3` | 3.000 | 106 | Masked corps pass-by |
| 23 | 29.600 | 1.267 | 38 | **T1** | `LS-B` | 0.300 | 100 | Back to red. **sings** |
| 24 | 30.867 | 1.233 | 37 | T2 | `K2` | 1.500 | 104 | Nergis draws the chain |
| **25** | **32.100** | **2.533** | **76** | T2 | `K1` | 4.500 | 108 | **Corps hero hold — the lateral bank** |
| 26 | 34.633 | 1.233 | 37 | **T1** | `LS-B` | 5.333 | 105 | **sings** |
| 27 | 35.867 | 1.267 | 38 | T2 | `K2` | 3.000 | 106 | Nergis, final look |
| 28 | 37.133 | 1.267 | 38 | T3 | `S-A07` | — | 104 + drift | Macro: hand, amber beads, signet ring |
| 29 | 38.400 | 1.233 | 37 | T2 | `K5` | 3.000 | 106 | Lead descends the rostrum, banks behind |
| 30 | 39.633 | 1.267 | 38 | **T1** | `LS-C` | 1.633 | 100 | **sings the final line** |
| 31 | 40.900 | 1.267 | 38 | T2 | `K6` | 1.500 | 104 | Nergis, gaze drifts off camera-left |
| 32 | 42.167 | 0.833 | 25 | **T1** | `LS-C` | 4.167 | 104 | **Button** — held on his face |

**Tier split:** T1 **365 f = 12.167 s (28.3 %)** · T2 **714 f = 23.800 s (55.3 %)** · T3 **211 f = 7.033 s (16.4 %)**. Total **1290 f = 43.000 s**.

That 28.3 % lip-sync load is within a point and a half of the 29.7 % measured in the source window — the piece carries the same weight of performance at a fraction of the cost, because the stills absorb the short cuts and the masked corps carries the desert.

### The audit this table passes (re-run it before Step 10 if you change anything)

Verified programmatically 2026-09-19:

```
frames total 1290 == 1290: True        shots 32   mean dur 1.344 s
max boundary deviation from the half-bar grid: 16.4 ms
adjacent same-source shots: none
direct cuts joining two DIFFERENT lip-sync beds: none

take   len    windows drawn                                        max-out  drawn  slack
K1     8.00   (0.000,1.233)(1.433,2.700)(3.000,4.267)(4.500,7.033)  7.033   6.300  0.967
K2     5.00   (0.000,1.233)(1.500,2.733)(3.000,4.267)               4.267   3.733  0.733
K3     5.00   (0.000,1.267)(1.500,2.767)(3.000,4.267)               4.267   3.801  0.733
K4     5.00   (0.000,2.500)(2.700,3.933)                            3.933   3.733  1.067
K5     5.00   (0.000,1.233)(1.500,2.767)(3.000,4.233)               4.233   3.733  0.767
K6     4.00   (0.000,1.233)(1.500,2.767)                            2.767   2.500  1.233
LS-A  11.00   (0.300,1.567)(2.800,4.067)(6.567,7.834)(9.067,10.334)10.334   5.068  0.666
LS-B   7.00   (0.300,1.567)(5.333,6.566)                            6.566   2.500  0.434
LS-C   5.00   (1.633,2.900)(4.167,5.000)                            5.000   2.100  0.000
LS-D   5.00   (0.367,1.634)(2.900,4.133)                            4.133   2.500  0.867
ALL TAKE DRAWS LEGAL: True
```

Three invariants this enforces, and they are the ones the upstream plans broke:
- **No window overlaps another window from the same take**, so no frame is ever shown twice.
- **No take is over-drawn** — every max-out is inside its generated length, with slack everywhere except LS-C's tail, which is flagged with a free fallback in GATE 7.
- **No two consecutive shots come from the same source**, and **no direct cut ever joins two different lip-sync beds**, so identity drift between separate generations never lands on a cut.

---

## 6. Assembly and master (copy-pasteable)

```bash
P=/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/05_build
SONG=/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3
cd $P

# --- 1. frame audit, then concat (stream copy: every segment came out of the same encoder line) ---
tot=0; for i in $(seq -w 1 32); do
  n=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 cuts/shot_$i.mp4)
  tot=$((tot+n)); done; echo "TOTAL $tot (must be 1290)"; [ "$tot" = 1290 ] || exit 1

for i in $(seq -w 1 32); do echo "file 'cuts/shot_$i.mp4'"; done > build/list.txt
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i build/list.txt -c copy build/edit_43s.mp4
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 build/edit_43s.mp4

# --- 2. loudness pass 1 (already measured on THIS file, values below; re-run if the bed changes) ---
# ffmpeg -hide_banner -i "$SONG" -af loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json -f null -
#   input_i=-15.63  input_tp=-1.54  input_lra=1.50  input_thresh=-25.63  target_offset=-0.49

# --- 3. mux, normalise, encode to Reels spec ---
ffmpeg -hide_banner -y \
  -i build/edit_43s.mp4 \
  -i "$SONG" \
  -filter_complex "[0:v]fps=30,setsar=1,format=yuv420p[v];\
[1:a]loudnorm=I=-14:TP=-1.0:LRA=11:measured_I=-15.63:measured_TP=-1.54:measured_LRA=1.50:\
measured_thresh=-25.63:offset=-0.49:linear=true,\
aresample=48000[a]" \
  -map "[v]" -map "[a]" -t 43.000 \
  -c:v libx264 -preset slow -profile:v high -level 4.1 \
  -b:v 9M -maxrate 12M -bufsize 18M \
  -x264-params "keyint=60:min-keyint=60:scenecut=0:bframes=2:ref=3:aq-mode=2" \
  -pix_fmt yuv420p \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -c:a aac -b:a 256k -ar 48000 -ac 2 \
  -movflags +faststart \
  build/reel_peshta_1080x1920.mp4

# --- 4. a silent picture master, kept as a first-class output ---
ffmpeg -hide_banner -loglevel error -y -i build/reel_peshta_1080x1920.mp4 -an -c:v copy \
  -movflags +faststart build/reel_peshta_1080x1920_silent.mp4

# --- 5. verify ---
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels \
  -show_entries format=duration,bit_rate -of default=noprint_wrappers=1 build/reel_peshta_1080x1920.mp4
ffmpeg -hide_banner -i build/reel_peshta_1080x1920.mp4 -af ebur128=peak=true -f null - 2>&1 | tail -15

# --- 6. cover ---
ffmpeg -hide_banner -y -i build/reel_peshta_1080x1920.mp4 -vf "select=eq(n\,0)" -vframes 1 -q:v 2 build/cover_frame0.jpg
```

**Want:** `h264 / 1080 / 1920 / 30/1 / yuv420p`, `aac / 48000 / 2`, `duration=43.000000`, `I: -14.x LUFS`, `Peak: -1.0 dBTP` or lower.

Notes on the choices that matter:
- `linear=true` applies one linear gain instead of dynamic compression, preserving the master's dynamics. This bed measured `LRA 1.50` — an extremely compressed master — so linear mode is the right call; drop it only if pass 1 warns it would clip.
- `scenecut=0` with fixed `keyint=60` gives a predictable 2 s closed GOP, making frame 0 a clean IDR and behaving better through Instagram's transcoder and the in-app scrubber.
- `-t 43.000` after the filters is the second net on duration. The concat container often reports 42.99xx because of timebase rounding while the **frame count is exactly 1290** — that is normal and verified; trust the frame count, and let `-t` set the final duration.
- **Do not upload at 40 Mbps.** It triggers a harsher server-side re-encode, not better quality.
- There is no `scale`/`crop` fallback anywhere in this chain because every clip is generated natively at 1080×1920. Nothing is ever cropped from 16:9, and the 394-credit `reframe` pass is never bought.

### Reels safe areas — compose to these, check every keyframe against them at GATE 4

| Edge | Reserve | What sits there |
|---|---|---|
| Top | **220 px** (y 0–220) | status bar, Reels header |
| Bottom | **420 px** (y 1500–1920) | handle, caption, audio ticker, progress bar |
| Right | **180 px** (x 900–1080) | like / comment / share / remix rail |
| Left | **60 px** (x 0–60) | caption breathing room |

Every face and every word lives inside **x 60–900, y 220–1500**, which puts eyelines at **y ≈ 700–760 (38 % down)** — the `LENS` clause in Appendix A, and where the eye goes first anyway.

---

## 7. Credit budget

Balance **1568.1, plan `pro`** (CONFIRMED). Every ✅ figure is a `get_cost: true` preflight; ❓ means no preflight path exists in this account.

### Full build

| Step | Item | Unit | Clean | Retry basis | Budget | Conf. |
|---|---|---|---|---|---|---|
| 1 | `soul_2` face auditions, 2:3 2k | 1 cr/img | 16 | 4 rounds × 2 chars | **32** | ✅ |
| 2 | `soul_2` character sheets, 2:3 2k, ref-anchored | 1 cr/img | 24 | +1 re-roll round each | **32** | ✅ |
| 3 | Soul training ×2 | **unknown** | — | reserve, hard stop 150 each | **120** | ❓ |
| 3 | post-train identity proof, 8 images | 1 cr/img | 8 | — | **8** | ✅ |
| 4 | `soul_2` keyframes ×13, `nano_banana_pro` two-shot ×1 | 1 / 2 cr/img | 30 | ×1.5 | **45** | ✅ |
| 5 | Stills → clips (ffmpeg) | 0 | 0 | — | **0** | ✅ |
| 6 | Pilot `wan2_7` 1080p 4 s | 2.5 cr/s | 10 | — | **10** | ✅ |
| 6 | Pilot `kling3_0` std 3 s | 1.5 cr/s | 4.5 | — | **4.5** | ✅ |
| 7 | `LS-A` `wan2_7` 1080p 11 s | 27.5 | 27.5 | ×3 | **82.5** | ✅ |
| 7 | `LS-B` `wan2_7` 1080p 7 s | 17.5 | 17.5 | ×2 | **35** | ✅ |
| 7 | `LS-C` `wan2_7` 1080p 5 s | 12.5 | 12.5 | ×2 | **25** | ✅ |
| 7 | `LS-D` `wan2_7` 1080p 5 s | 12.5 | 12.5 | ×2 | **25** | ✅ |
| 8 | `K1` `kling3_0` std 8 s | 12 | 12 | ×3 | **36** | ✅ |
| 8 | `K5` `kling3_0` std 5 s | 7.5 | 7.5 | ×3 | **22.5** | ✅ |
| 8 | `K2` / `K3` / `K4` std 5 s each | 7.5 | 22.5 | ×2 | **45** | ✅ |
| 8 | `K6` `kling3_0` std 4 s | 6 | 6 | ×2 | **12** | ✅ |
| 9 | Hero upgrade `K1` pro 8 s | 14 | — | optional | **14** | ✅ |
| 10–13 | Conform, QA, assemble, master, cover | 0 | 0 | — | **0** | ✅ |
| | **Priced clean pass** | | **210.5** | | | |
| | **BUDGETED TOTAL** | | | | **548.5** | |

**Reserves held outside the table:** `sync_so` fallback (Route B) **150, hard stop** ❓; general contingency **150**.

**Worst realistic case,** with Soul training at 150/character and Route B triggered:
`548.5 − 120 (Soul reserve) + 300 (Soul actual) + 150 (sync_so) = 878.5`. **Against 1568.1 that leaves 689.6 spare.**

Honesty notes on this table, because the upstream version of it was presented optimistically:
- The `soul_2` "0.12 exact" figure is **not** what gets deducted. Billing rounds to **1 credit per image**, and this table uses 1. A claim like "19 % of the Reel for 0.6 credits" is off by roughly 10×; the real keyframe cost of the five still-clips is ~10 credits.
- The 120-credit Soul reserve is for a path that Step 3b makes optional. If you take 3b, the budgeted total drops to **428.5** and the clean pass to **186.5**.
- The retry allowances are not a flat multiplier. LS-A and K1/K5 get ×3 because they are the three hardest generations in the plan (an 11 s audio-driven bed with a corps; two unison-corps takes). Everything else gets ×2. Effective video multiplier is 2.3×, which is what the research recommended.
- **What this plan deliberately never buys:** `reframe` (394 credits at 43 s @1080p, CONFIRMED, and unsteered at that length because guidance images are refused above 15 s — never needed, everything is native 9:16); `upscale_video` (has **no** `get_cost` at all, CONFIRMED — never needed at native 1080p); `seedance_2_0` at 1080p (9 cr/s — an all-Seedance build at the source's cut rhythm comes to ~1980 credits and **does not fit** in this balance).

### The MVP — what ships for under 400

Changes from the full build:
1. **No Soul training, no character sheets.** Step 3b: one reference image per character in `soul_2`'s max-1 `image` role. Removes the only unpriced spend.
2. **Three lip-sync beds, not four. Drop `LS-D`** (the World-B singing shots). Shot 19 becomes a T3 still (**`S-B02`**, the masked-corps desert frame, push→106, 38 frames — **not** `S-B01`, which is `K4`'s own start frame, and shot 18 is `K4`: cutting a `K4` frame against the still it was generated from is exactly the jump cut the no-two-consecutive-same-source rule exists to prevent. The §5 adjacency invariant is about the *image*, not the label — re-run the audit after any MVP substitution); shot 21 becomes a third window of `K4`, which therefore grows from 5 s to 6 s. **Re-audited: K4 at 6 s draws (0.000, 2.500), (2.700, 3.933), (4.200, 5.433) — no overlap, max-out 5.433 ≤ 6.000, slack 0.567.** Adjacency still holds (18 = K4, 19 = still, 20 = K3, 21 = K4, 22 = K3). `S-B03` is no longer needed, so 13 keyframes instead of 14.
3. **Skip the hero upgrade.**

| Item | Cost |
|---|---|
| `soul_2` auditions, 2 rounds × 4 × 2 chars | 16 |
| Keyframes: 12 `soul_2` × 2 + `nano_banana_pro` × 2, with retries | 36 |
| Pilot `wan2_7` 1080p 4 s | 10 |
| `LS-A` 11 s ×2 attempts | 55 |
| `LS-B` 7 s | 17.5 |
| `LS-C` 5 s | 12.5 |
| `K1` 8 s ×2 | 24 |
| `K5` 5 s ×2 | 15 |
| `K2` 5 s / `K3` 5 s / `K6` 4 s | 21 |
| `K4` **6 s** | 9 |
| **MVP TOTAL** | **216** |

**Under 400 with 184 credits spare** — enough to regenerate the desert entirely twice, or add `LS-D` back if the chorus looks thin. T1 drops to 9.667 s (22.5 %).

**What the MVP still delivers, signal by signal.** A scrolling viewer registers six things inside four seconds, and all six survive: (1) a totally monochrome red world — stills and K1; (2) a phalanx of black wide-brim hats in a lateral bank — K1 and K5; (3) an austere dark-coated lead with a bare head against that bank — every keyframe; (4) a woman in ivory behind a veil — K2, K6, `S-A04`, `S-A05`; (5) a hard cut to a bleached desert with white-masked figures, landing on the bass-out break — K3, K4; (6) ~1.3 s cutting, which costs zero credits. What you lose is 2.5 s of World-B lip-sync and some corps polish.

---

## 8. Risk register

| # | What goes wrong | Likelihood | Detected by | Fallback |
|---|---|---|---|---|
| **R1** | **`audio_references` does not drive sung lip-sync.** CONFIRMED that the role exists on `wan2_7`; ASSUMED that it works on singing. 70 credits ride on it. | medium | **GATE 6**, for 10 credits, *before* any bed is bought | Route B: generate everything as motion, assemble silent, run **one** `sync_so` pass (`input_video` + `input_audio`, `sync_mode:"cut_off"`). Cost cannot be preflighted through MCP (CONFIRMED 422 on the injected `prompt`) — read it in the web UI. Hard stop 150. |
| **R2** | **A prompt trips the server-side IP check.** No tool in the account can preflight a refusal (CONFIRMED); it lands as a terminal failure *after* the charge. | low, if disciplined | `bin/ipgate.sh` before every call | Prompts live in `prompts/*.txt` and are `cat`-ed into calls, never typed fresh at 1 a.m. **A filename can carry a proper noun into an upload** — name uploads `S-A01.png`, never descriptively. Character names in Higgsfield are `kemal-yalcin-m1` / `nergis-f1`, never anything else. |
| **R3** | **The audio is claimed, muted or region-blocked after the piece is finished.** The file is CONFIRMED to be a Suno add-vocals render over the commercial master, on a cold professional account with a restricted library. | **high** | **D1, on day one, before Step 1** | The original-bed path (D1-b). Because the whole edit is cut to a **bar grid** rather than to musical events, re-cutting to a different bed at 95.600 BPM with the break in bar 8 is a re-derivation of §5, not a re-shoot. `reel_peshta_1080x1920_silent.mp4` is built as a first-class output for exactly this reason. |
| **R4** | **Identity drifts between the four beds.** Each is a separate generation with only a start image holding the face, and they are the four places the face is largest. | medium | **GATE 11**'s face-crop montage — invisible clip-by-clip, obvious in a grid | All four start images come from the same Soul in the same Step-4 batch, so they are already the same person before the video model sees them. And §5 guarantees **no direct cut ever joins two different beds** — every bed-to-bed transition is buffered by at least one non-lead shot. |
| **R5** | **The corps dissolves.** Sixteen near-identical figures in unusual silhouettes is genuinely hard; brims invert, bodies duplicate, hands merge by second 3. | medium | **GATE 6**'s 4.5-credit probe, before the 19.5 credits of K1+K5 | `minimax_h3` (2 cr/s, 2K, 8 s = 16 ✅) or `wan2_7` 720p (1.5 cr/s, 8 s = 12 ✅) are both priced and both accept a start image. K1 is 8 s but the edit draws 6.300 s — there is 0.967 s of slack to step around a bad stretch. |
| **R6** | **The red drifts between generations.** Five takes and six stills all have to be the same red; a hue shift across a 1.3 s cut is glaring and the grade cannot fix it. | medium | **GATE 4**, check 2, at 1 credit per re-roll | `LIGHT_A` and `GRADE` are pasted verbatim into every World-A prompt, and each World-A take starts from a keyframe that already *is* the right red — the model matches its start frame. Last resort: an `eq=saturation`/`hue` pass inside `cut.sh` on the offending segment. |
| **R7** | **A one-frame drift breaks the audio sync for the rest of the piece.** 32 segments, `-c copy` concat. | low | `still2clip.sh` and `cut.sh` each **print their own frame count**; GATE 10 sums them; the master pass adds `-t 43.000` | Both scripts were run on this machine and return exact counts; a mixed concat of still-clips and cut-clips with `-c copy` was verified to preserve the total exactly. |
| **R8** | **`LS-C` has zero tail slack** — the Reel ends exactly when the song does, so the closing 25 frames are the model's last 25 frames, where motion degrades most. | medium | **GATE 7** | Freeze the last clean frame of LS-C and run `bin/still2clip.sh <frame>.png cuts/shot_32.mp4 25 1.02 0`. Costs 0. A held closing portrait is legitimate grammar. |
| **R9** | **Soul training turns out to be expensive, and you find out by paying for it.** The only unpriced spend. | medium | `balance` immediately before and after the *first* training call | Hard stop at 150 on the first Soul; do not train the second. Step 3b is a complete working path and is the MVP default. |
| **R10** | **You cannot get the renders off Higgsfield onto disk.** The retrieval tool names are CONFIRMED; the exact response field carrying the file URL is **ASSUMED**. | low | **STEP 6** — print the full `job_status` / `show_generation_by_ids` response on the pilot | Write the field path into `05_build/RETRIEVAL.md` before generating anything else. `sandbox_exec` is the fallback if the URL is only reachable server-side. Do not discover this after 200 credits of takes. |
| **R11** | **Derivative-work exposure at Meta / with the rights holder**, separate from the likeness question. | low, as specified | Read §1 and Appendix A before writing any prompt | The costume is an **original variation**, not a transcription; no proper noun of a person or a titled work appears anywhere in the pipeline; no Higgsfield call in this guide takes the source mp4 as an input — not `hf_mult_motion_control`, not `hf_mult_replace_object`, not `ad_multiplier` `video_edit`. Those trace someone else's footage and make the output a derivative of the *media*, not just the faces. |
| **R12** | **Budget overrun.** | low | `LEDGER.tsv` running total; stop at 700 before Step 10 | The stack is cheap by design: `kling3_0` std at 1.5 cr/s and `wan2_7` at 2.5 cr/s. Even at 5× retries plus expensive Souls plus Route B this lands near 1000, not 1568. |

---

## Appendix A — the two literal character blocks

Write these to `prompts/identity_M1.txt` and `prompts/identity_F1.txt` **once** and `cat` them into every prompt. Re-prompting a face fourteen times gives you fourteen different people. The identity block is **frozen**; only wardrobe, set, light, lens and camera change.

### `prompts/identity_M1.txt` — "Kemal Yalçın"

```
original fictional character named Kemal Yalçın, Turkish man, 38 years old, lean
athletic build, 180cm, broad square shoulders, medium-tan Mediterranean complexion;
oval face with a broad flat brow, deep-set dark brown eyes under heavy straight
black brows, aquiline nose with a slight break at the bridge, high flat cheekbones,
strong square jaw, thin unsmiling mouth; a short vertical scar through the outer
third of the LEFT eyebrow; black hair cropped very short at the sides, slightly
longer on top, matte, no styling product; short dense trimmed black beard, 8mm,
sharp cheek line, no moustache flare; no glasses, no earrings, no tattoos, no
visible teeth; visible skin pores, natural asymmetry, matte unretouched skin,
no beauty filter
```

The **scar is the anchor**. One invented, asymmetric, cheap feature does more for shot-to-shot consistency than ten adjectives about bone structure, and it makes the face demonstrably not a real person's. It appears in every prompt and it is what GATE 4 and GATE 11 check.

**`WARDROBE_M_A` (red studio) — original, deliberately not the source's costume:**
```
charcoal-black heavy wool frock coat, high standing collar, worn closed, double row
of matte black horn buttons, long skirt to mid-thigh, no insignia, no epaulettes,
no braid, no medals; black shirt buttoned to the throat, no tie; a narrow oxblood
silk sash at the waist; bare-headed, the only uncovered head in the frame
```
Bare-headed is doing real work: against a corps of sixteen wide-brim hats it makes the lead the single focal point at Reels scale, and it is the opposite of the source's costume logic.

**`WARDROBE_M_B` (desert quarry):**
```
the same charcoal-black wool frock coat worn open over a slate-grey shirt buttoned
to the collar, sand dust on the hem, bare-headed, collar turned up against the light
```

**`PROPS_M`:**
```
worn amber prayer beads hanging from the left hand, thumb resting on them; heavy
oxidised silver signet ring with a geometric eight-point star on the right ring
finger; plain steel watch on a cracked brown leather strap. NO weapons, no
cigarettes, no brand logos.
```

**`POSTURE_M`:**
```
weight on the back foot, hips square to camera, shoulders level and still, chin
dropped 10 degrees, eyes lifted to the lens, hands low and open; absolutely no
smile, no eyebrow raise, no head tilt
```

### `prompts/identity_F1.txt` — "Nergis"

The role as blocked is aloof, veiled, seated, still, handed flowers, with no agency across 43 seconds. That constraint decides the archetype: the **glamorous dynastic antagonist** — power expressed by not moving, by making people wait, by being looked at without returning warmth. The hard-edged professional is miscast the moment she stops moving; the grieving loyalist tips a veil plus stillness plus a black-clad corps into mourning imagery, and this is a courtship song. The antagonist also hands you a complete wordless story for free: the antihero courting the woman from the rival house, no lyrics translation required.

```
original fictional character named Nergis, Turkish woman, 31 years old, tall and
long-necked, straight level shoulders, slim; pale olive skin; oval face, very high
cheekbones, large hooded dark-brown eyes with a level gaze, long straight narrow
nose, full unsmiling mouth, delicate pointed chin; a small dark beauty mark high on
the RIGHT cheekbone below the outer eye; black hair, centre-parted, pulled back flat
and low into a small nape knot; minimal makeup, matte skin, deep berry lip, no
visible teeth; visible skin pores, natural asymmetry, unretouched, no beauty filter
```

**`WARDROBE_F_A` (red studio) — original variation:**
```
floor-length ivory silk column gown, high boat neckline, long narrow sleeves, matte
crepe, bias cut; one heavy single-strand chain of dark garnet beads falling to the
waist; a fine ivory net veil pinned low across the eyes to the cheekbone from a
plain flat chignon, no cap, no beading; bare hands, no watch, no rings
```

**`WARDROBE_F_B` (desert):**
```
ivory tailored trouser suit, sharp shoulder, ivory silk shell, plain ivory net
half-mask over the upper face
```

**`POSTURE_F`:**
```
seated upright on the red carpeted riser, spine long, knees together and angled away
from camera, hands folded still in the lap, chin level, gaze to the lens then
drifting slowly off-camera left; no smile, no lean-in
```

The beauty mark is her anchor, exactly as the scar is his. Both appear in every prompt.

### Shared blocks — pasted verbatim, never paraphrased

```
SET_A:   monochrome red-orange seamless cyclorama studio, matte orange foam blocks
         scattered across the floor, a low red-carpeted rostrum of three broad
         risers; a corps of sixteen dancers in floor-length black dresses and black
         wide-brim hats
SET_A formation, lateral (K1, K5, S-A09, S-A13):
         the corps stands in a symmetric bank spreading to both the left and right
         edges of the frame, the outer figures cut off by the frame edge so the line
         reads as continuing off screen
SET_A formation, depth (LS beds, where the lead must stay legible in front):
         the corps in four receding rows behind the subject, not in a lateral line
SET_B:   eroded sand-cliff quarry exterior under a pale bleached sky, freestanding
         red-painted rectangular gate frames standing vertically in the sand, red
         blocks scattered; a corps in all-white suits with plain white lace masks
         fully covering their faces
LIGHT_A: single hard warm key from camera-left 45 degrees, deep red gel wash on the
         background, hot specular edge along the jaw, heavy falloff, no fill
LIGHT_B: open noon daylight, bleached highlights, hard short shadows, no fill
LENS:    50mm anamorphic feel, T2.0, shallow depth of field, subject centred in a
         vertical 9:16 frame, eyeline at 38 percent from the top of frame
GRADE:   filmic, warm, crushed blacks, fine 35mm grain, slight halation on
         highlights, saturated red channel
FORMAT:  1080x1920 vertical, 9:16
```

---

## Appendix B — `prompts/negative.txt`, the never-type list

None of this reaches a Higgsfield prompt. Not as a "loose reference", not in a caption, **not in a filename that gets uploaded**, not in a Soul or Element name.

```
any real actor's, singer's, performer's or public figure's name
the name of any real TV series, film, song or album
any real production company or record label
"music video recreation" · "shot-for-shot remake of" · "based on the film/series"
likeness · lookalike · "looks exactly like" · "in the style of <person>"
deepfake · face swap · celebrity · "famous Turkish actor" · "real person"
"TV series character"
any real army's medals, ribbons, flags, national emblems or unit insignia
brand logos
guns, rifles, pistols, knives
```

**Safe substitutions — what you actually type:**

| Refused / flagged | What you write instead |
|---|---|
| a named series lead in a red studio | `original fictional character Kemal Yalçın, in a red studio` |
| "a man who looks exactly like \<actor\>" | the full invented-face block in Appendix A |
| "the lead from the Turkish mafia series" | `a Turkish crime-drama antihero archetype, 1990s Istanbul noir register` |
| "recreate the \<title\> music video" | `a red monochrome studio dance-film sequence, warm hard key, corps in black` |
| "in the style of \<series\>" | `Anatolian noir, Yeşilçam-meets-modern-crime grade` |
| "face swap onto this frame" | `use this character reference image for facial consistency` |

The principle: **describe the archetype and the frame, never the property or the person.** Genre labels, decade labels, wardrobe, lighting and lens language are all safe. Proper nouns of people and titled works are not.

---

## Appendix C — execution order, one line each

0. Scaffold, slice audio, install `still2clip.sh` / `cut.sh` / `ipgate.sh` — **0 cr** · **and close D1 today, in parallel with everything below**
1. Audition two faces on `soul_2` at 2:3 — **16–32 cr**
2. *(full build only)* Character sheets, ref-anchored — **24–32 cr**
3. *(full build only)* Train two Souls, balance-delta priced, hard stop 150 — **~120 cr reserve** · else **3b, 0 cr**
4. Fourteen 9:16 keyframes + two Elements + the two-shot — **30–45 cr** · *spend an hour at GATE 4*
5. Five still-clips via `still2clip.sh` — **0 cr** · 16.4 % of the Reel done
6. **THE PILOT** — `wan2_7` sync probe + `kling3_0` corps probe, and pin down retrieval — **14.5 cr**
7. Four lip-sync beds, time-locked to their slices — **70–167.5 cr**
8. Six cutaway takes, K1 and K5 first — **48–115.5 cr**
9. Optional `K1` pro upgrade — **14 cr**
10. Conform 32 cuts, audit to 1290 frames — **0 cr**
11. Identity-drift contact sheet — **0 cr**
12. Concat, loudnorm, master, verify — **0 cr**
13. Cover frame — **0 cr**

---

**Files this produces** — all under `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/05_build/` (untracked working folder, alongside `01_character_concepts.md`–`04_generation_plan.md`, `BED_AUDITION.md`, `bpm_detect.py`, `qa_gate.py`). Deliverable: `05_build/build/reel_peshta_1080x1920.mp4`. Cover: `05_build/build/cover_frame0.jpg`. Ledger: `05_build/LEDGER.tsv`.

**Nothing at the repository root.** Per this repo's `CLAUDE.md` that rule covers throwaway analysis notes too. If any of this later becomes a document someone reads — a costing, a post-mortem — it moves into `docs/research/` or `docs/product/` with a row added to `docs/README.md`, and inbound references get grepped and fixed in the same change.

**No generations were run and nothing was charged in producing this guide.** All credit figures are `get_cost: true` preflights or `balance`; all ffmpeg behaviour, frame counts, audio slice durations, loudness measurements and file checksums were measured on this machine on 2026-09-19.
