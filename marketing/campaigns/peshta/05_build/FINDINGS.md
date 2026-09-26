# Build findings — 2026-09-19, live execution against `05_HIGGSFIELD_RECREATION_SETUP.md`

Six facts the plan got wrong or left ASSUMED. All verified by running them.

## 1. CONFIRMED — retrieval (was ASSUMED, Step 6)

`count:N` returns N separate job ids. `jobs_wait` takes `jobs:[{index,job_id}]` — objects, not
id strings, `index` required, **max 12 per call**, `timeout_seconds` max 15. The file URL is
`jobs[].result_url`, already present in the wait response. See `RETRIEVAL.md`.

## 2. FATAL to the plan — the `soul_2` reference-image path (Step 3b) does NOT work

Step 3b was the zero-cost identity fallback and the MVP's entire identity mechanism. It fails:
`soul_2` with `medias:[{role:"image"}]` copies the reference's **whole frame** — grey seamless
background, charcoal t-shirt, portrait crop — and ignores the prompt's set, wardrobe and corps.
Both S-A11 attempts came back as grey studio headshots. The face drifted anyway.
**Step 3b cannot place a character in a scene. Do not budget on it.**

## 3. The replacement: Reference Elements — which also deletes Soul training from the plan

`show_reference_elements action=create` → embed `<<<element_id>>>` in `params.prompt`.
Elements *do* place the character in a new set correctly (verified: red cyclorama, hatted corps,
frock coat all present). They work on **image** models `nano_banana_pro` / `nano_banana_2` /
`gpt_image_2` / `seedream_v4_5` / `seedream_v5_lite` / `cinematic_studio_2_5` **and on video**
models `kling3_0` / `cinematic_studio_video` / `cinematic_studio_3_0` / `seedance_2_0` — but NOT
on `soul_2` / `soul_cinematic`. Souls are the mirror image: `soul_2` / `soul_cinematic` only.

**Consequence: Steps 2 and 3 (character sheets + Soul training — 32 cr + 120 unpriced reserved)
are deleted.** Elements are instant, free to create, allow multiple characters in one frame, and
lock identity in the video models directly.

Elements created:
- `kemal-m1` — `82d3cf81-ea53-437e-9ddf-3e95b1685fa9`
- `nergis-f1` — `d14538dc-e4da-4a96-9493-7ffe2ad98a7a`

Caveat measured: identity fidelity is roughly **50 % per attempt**. Of two S-A11 Element renders,
one held the face and one drifted to a different man. Budget **2 attempts per keyframe** and gate
on the anchor feature, exactly as GATE 4 says.

## 4. CONFIRMED — `wan2_7` `audio_references` drives a real singing mouth (GATE 6, the load-bearing gate)

The pilot articulates through closed / open-with-teeth / wide across 4 s, identity is stable
within the take, and the red set with the hatted corps is correct behind him.

**The returned file carries the driving audio at zero lag: envelope correlation +0.999 at
lag 0 ms over the full 4.00 s.** A bed is therefore self-timing — the take's frame grid maps
straight onto song time, and sync can be verified without muxing anything.

The `.mp3` slice was accepted; the `.wav` was never needed.

## 5. `wan2_7` does NOT return 1080×1920

Returned **1076×1928**, 30 fps, 120 frames, **4.04 s** for a 4 s request. The plan's claim that
everything is generated natively at 1080×1920 and that "there is no `scale`/`crop` fallback
anywhere in this chain" is wrong twice. `bin/cut.sh`'s
`scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920` is **load-bearing** and
must stay. Also budget for duration overshoot: ask for 4 s, get 4.04 s.

## 6. New trap — a submission can be silently swallowed by a preset recommendation

`generate_video` returned `{"notice":{"type":"preset_recommendation",…}}`, submitted **no job**
and charged nothing. Retry with `declined_preset_id:"<suggested preset id>"` inside `params`.
This is the same failure class as the `unlim_choice` trap: a successful-looking response with no
job behind it. **Always confirm a `results[].id` came back before you start polling.**

---

## Wallet note — the credit pool is shared and is being drained from outside this build

| Time (UTC) | Balance | My cumulative spend |
|---|---|---|
| 11:37 | 1568.10 | 0 |
| 11:46 | 1020.58 | ~1.5 |
| 12:02 | 962.58 | 18.0 |

At **11:42:42** ten `Higgsfield Multiplier Motion Control` jobs were submitted within one second
(44 + 44 + 55 + 66 + 66 + 66 + 44 + 44 + 44 + 44 ≈ 517 cr), only partly refunded. That is the
parallel agent running the transform/Genjutsu route, not this build. Budget accordingly: this
build's remaining need is ~530 cr against a pool that is not exclusively ours.
