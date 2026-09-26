# Peshta Promo — Variant D 15-Second Generation Plan

**Target:** `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/04_generation_plan.md`
**Authored:** 2026-09-18 · **Balance at authoring:** 1568.1 credits, plan `pro` (verified live via `mcp__higgsfield__balance`)
**Status:** PLAN ONLY. Nothing here has been executed. No Higgsfield job was submitted; no ElevenLabs request was sent. Every credit figure came from a `get_cost:true` preflight, re-probed during this session.

**Thesis.** Three things can sink this build, and all three can be tested for **9 credits and 7.5 cents**: the character (does the Alabay come back on-model and text-free?), the song (does it come back in Uzbek, at a usable tempo?), and the audio-sync premise (does handing Higgsfield our track actually lock motion to the beat?). Everything expensive sits behind those three gates. The song is built first and *measured*, because the beat grid is the spine of every cut and no vendor field lets us ask for a tempo.

**A note on filing.** Per D6 this document lives in `marketing/campaigns/peshta/`. That clears the repo's absolute prohibition (`CLAUDE.md`: never a Markdown document at the repository root) but does **not** satisfy the second half of the same rule, which files a plan under `docs/product/`. D6 overrides. Noting the deviation once, and following D6.

---

## 1. Decisions locked

| | Decision |
|---|---|
| **D1** | The song is rendered through the product's own pipeline — `ElevenLabsMusicProvider.compose()` in `src/bayram/providers/music/elevenlabs.py`. Higgsfield has no usable music path for this. |
| **D2** | Character is Flagship 1, the **Alabay hype-squad**: Central Asian Shepherd in a Chust doppi, gold Cuban chain, 90s **rectangular** sunglasses, two **smaller** street-pup hype-men. A dog needs no lipsync. |
| **D3** | Cut is **Variant D**, the hyper-condensed 15-second soundbite (`02_parody_lyrics.md` §2.4). |
| **D4** | Rights position is **original soundalike**. New composition in the same idiom, our own lyrics, our own master. We never touch Hamdam Sobirov's recording, and we never name him or the track anywhere a vendor can see. |
| **D5** | **Zero spend this turn.** Cost preflight via `get_cost:true` submits no job and was the only pricing method used. |
| **D6** | Everything stays under `marketing/campaigns/peshta/`. |
| **D7** | `marketing/campaigns/peshta/alabay_video/` is **discarded as a deliverable** — mined for tooling and lessons only (§12). |

### 1.1 One correction to the brief, before anything else

**The environment variable is `BAYRAM_ELEVENLABS_API_KEY`, not `ELEVENLABS_API_KEY`.** I grepped `.env`: there is no unprefixed key, and the prefixed one is present (51 characters). A script that reads `ELEVENLABS_API_KEY` gets an empty string and fails at call time with an auth error instead of a clear config error. Go through `build_settings().elevenlabs_api_key` (`src/bayram/config.py:235`); the prefix is applied by the loader.

---

## 2. Beat grid

### 2.1 The tempo ruling

**95.8 BPM, 4/4.** Not 126 BPM 6/8.

The corpus' load-bearing identity is "13 syllables = 2 bars = 5.0104 s" (`02_parody_lyrics.md` §1.5). Solved three ways, re-run this session:

```
4/4:  BPM = 8 beats × 60 ÷ 5.0104 s = 95.801     ✅ matches the stated 95.8
6/8:  eighth   = 5.0104 ÷ 12 = 0.4175 s → 143.7 BPM   ✗
      dotted-Q = 5.0104 ÷  4 = 1.2526 s →  47.9 BPM   ✗
```

Neither 6/8 reading is 126. `03_production_blueprint.md` §6.1 tries to reconcile them — *"Tempo: 126.0 BPM (or 95.8 BPM half-time pop-folk grid)"* — and the reconciliation is false. **Half of 126 is 63.0.** The real ratio is 126 ÷ 95.8 = **1.3152**, which is not a metric modulation. The same section's *"Bar Period: 1.9048 seconds (4 beats at 126 BPM)"* is 4/4 arithmetic with a 6/8 label on it.

The structural proof is cleaner than the numbers. Barmoq's 4+4+5 caesura maps Turoq 1 to four eighths over beats 1–2 and Turoq 2 to four eighths over beats 3–4 — eight eighths, one complete bar. A 6/8 bar holds six. **4+4 cannot fill a 6/8 bar.** The meter is 4/4; the Khorezm Lazgi 6/8 feel survives as doira ornamentation on top, never as the meter.

| Figure | Value |
|---|---|
| Beat | 0.6263 s |
| Bar (4 beats) | 2.5052 s |
| Barmoq line (2 bars) | 5.0104 s |
| Six bars | 15.0313 s |

**Corroboration.** The measured master Verse 1 (0:11.6 → 0:31.6 = 20.04 s) is 7.999 bars at 95.8 — essentially 8 — but 10.52 bars at 126 in 4/4, which is not integral. And the existing promo audio measures **95.70 BPM** by autocorrelation against a declared 95.8.

### 2.2 Frame-rate ruling: 50 fps, 750 frames, 15.000 s

| Cut | @30 fps | @50 fps | @60 fps |
|---|---|---|---|
| 1.60 s | 48 | **80** | 96 |
| **2.54 s (the slam)** | 76.2 ✗ | **127** ✓ | 152.4 ✗ |
| 8.00 s | 240 | **400** | 480 |
| 11.50 s | 345 | **575** | 690 |
| 15.00 s | 450 | **750** | 900 |

**Master: 1080×1920 @ 50 fps, exactly 750 frames, exactly 15.000000 s.**

> **The 15.031 s trap.** Six bars is 15.0313 s, and 15.0313 × 50 = 751.57 — *not* a whole number of frames. A video master cut to 15.031 s cannot be encoded on the grid and would fail its own container gate. **Cut the AUDIO BED at 15.0313 s** (so the musical turnaround completes) **and let the mux's `-t 15.0` trim the final 31 ms of video.** The master is 750 frames.

Honest note, from the retention review: the 30 fps error on the slam is 6.7 ms, which is below the ~20 ms audio-visual binding window and therefore imperceptible. 50 fps is free, so we take it — but this is hygiene, not a retention lever. **The retention levers are in §2.5, and that table is what the cut is actually gated on.** The blueprint's mandated 60.00 fps is unbuildable natively (no catalog model declares an fps; the one real clip on disk came back at 24) *and* fractional on the slam.

*Fallback if 50 fps causes platform trouble:* 30 fps with the slam snapped to frame 76 (2.5333 s), a 6.7 ms error, and every segment length recomputed.

### 2.3 The rider on all of the above

Everything in §2.1–2.2 is derived from measurements the researchers took **of someone else's master recording**. Under D4 we are composing an original track, and `build_compose_body` sends **no tempo field of any kind** — I printed the emitted body and confirmed it carries only `composition_plan`, `model_id`, `force_instrumental`, `store_for_inpainting`, and optionally `seed` / `source_song_id`.

> **The table in §2.4 is PROVISIONAL. It is the design target handed to the composer, not the edit grid.** Step 0.5 measures the delivered file, re-solves `bar = 240 ÷ measured_BPM`, rebuilds this table from real transients, and re-picks the master fps so the real slam lands on an integer frame. **No video credit is spent before that re-derivation is on paper.**

A plan that buys 49 credits of motion against a 95.8 BPM assumption and then discovers the render came back at 88 BPM has thrown the money away.

### 2.4 Timecode table — 750 frames @ 50 fps

Every Uzbek string below uses **U+02BB MODIFIER LETTER TURNED COMMA (ʻ)**, never ASCII `'`. Strings marked **[NEW]** or **[ADAPTED]** have never been read by a native speaker and are blocked behind gate G13.

| # | Frames | t_start – t_end | Audio event | Visual | On-screen text | Source |
|---|---|---|---|---|---|---|
| 1 | 0–11 (12f) | 0.000 – 0.240 | First transient of the hook; air-whoosh + 60 Hz sub-impact thud, −3.0 dBFS | **COLD OPEN.** Bright hero still, snap-zoom 1.12 → 1.00. Shades ON, chain, doppi, confetti mid-air. Built in ffmpeg from KF-2 — **no generation** | **c1 HOOK** in at frame 0 | 03 §1.1 retention rule + §1.3 Formula 2 |
| 2 | 12–79 (68f) | 0.240 – 1.600 | Frantic hook; sub-bass sounds briefly then cuts. Comedic vinyl scratch at ~1.45 s, 180 ms, −4.5 dBFS. Vocal: *"Sovgʻa izlab boshim qotdi..."* | **SH-01.** Hard cut to a dim-but-not-dark apartment. Alabay slumped with cheap grey socks, ears down. **Sunglasses stay ON, pushed down the muzzle** so eyes read over the top | **c1** holds | 02 §2.4 r1 · 03 §5 Shot 1 |
| 3 | 80–126 (47f) | 1.600 – 2.540 | **Authored 0.94 s sub-bass vacuum** — 20–200 Hz pulled ≥ 24 dB, vocal out. *(Implemented with an `enable` upper bound of **2.53**, not 2.54 — §7.5(b) explains why.)* High-passed reverse-cymbal riser 400 Hz → 12 kHz underneath, −4.0 dBFS | **SNAP-ZOOM, not a freeze.** Last frame of SH-01 pushed 1.00 → 1.20 across 47 frames. Escalating motion into the cut — because 50–62% of the audience hears nothing at all | **c1** + **c2 `TOʻXTA…`** pulsing | 02 §2.4 r2 |
| — | **frame 127** | **2.540** | **808 SUB-BASS + KHOREZM DOIRA RIM-SHOT SLAM.** 45 Hz sine sub, < 5 ms attack, no limiter duck, −1.0 dBTP. Vocal: **"BOTDA! BAYRAM-BOTDA!"** | **HARD CUT.** Whip-flash to bright studio; confetti pop | **c3** in; **c1/c2** out | 02 §2.4 r3 · 03 §5 Shot 4 head |
| 4 | 127–217 (91f) | 2.540 – 4.360 | Heavy 4/4 folk-trap bounce, driving doira | **SH-02a.** Shoulder-bounce dance (*yelka qoqish*), hype-pups behind | **c3 `BAYRAM-BOTDA!`**; **c7 handle pill** in at frame 145 | 02 §2.4 r4 |
| 5 | 218–308 (91f) | 4.360 – 6.180 | — | **SH-02b.** Same clip, **punch-in cut**: 2-frame white flash + 1.06× scale step | **c4** in; **c3** out; **c7** holds | jump-cut cadence, 03 §1.1 |
| 6 | 309–399 (91f) | 6.180 – 8.000 | — | **SH-02c.** Second punch-in: flash + 1.12× | **c4**, **c7** | 03 §1.1 |
| 7 | 400–449 (50f) | 8.000 – 9.000 | High emotional register vocal run. Vocal: *"O mani kuydirding, o mani suydirding!"* | **SH-03.** Phone propped on a table, **screen blank matte dark grey** — the player UI is composited, never generated | **c5** in; **c8 price badge** in at frame 420; **c7** holds | 02 §2.4 r5 · 03 §5 Shot 6 |
| 8 | 450–524 (75f) | 9.000 – 10.500 | Same vocal run continues | **REAL SCREEN RECORDING** of the live bot, filmed against the **shipped** flow: name typed → `✅ Ha, shunday` (`button.name_ok`) → language picked (`wizard.output_language.prompt`) → `wizard.lyrics.writing` spinner → free lyric preview (`wizard.lyrics.preview`). **Zero credits.** This is real UI, not AI-rendered text | **c5**, **c7**, **c8** | `src/bayram/bot/locales/uz_latn.py:290, 309, 311, 312, 421` |
| 9 | 525–574 (50f) | 10.500 – 11.500 | Vocal run resolves | **SH-02d** — the **final 1.00 s** of the same 6 s hero clip (source 5.00–6.00 s): the dog reacting, delighted. **Zero extra credits — but not a disjoint window:** it **re-uses 0.46 s of SH-02c's source** (3.64–5.46 s), so master frames 525–547 replay the same 0.46 s of action already seen at frames 377–399, three seconds earlier and at a different scale (SH-02c runs at a 1.12× punch-in, SH-02d at 1.00×). Accepted deliberately: the alternative is +3.5 credits for a 7 s SH-02 — see §6.4 | **c5** out at 524; **c7**, **c8** | — |
| 10 | 575–661 (87f) | 11.500 – 13.240 | Final cadence; bed ducks 6 dB under the CTA. Vocal: *"Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!"* | **SH-04a.** Alabay points down-frame, two rhythmic emphasis pushes | **c6 CTA** in; **c7**, **c8** | 02 §2.4 r6 · 03 §5 Shot 7 |
| 11 | 662–749 (88f) | 13.240 – 15.000 | Percussive turnaround; **60 ms fade only** | **SH-04b.** Flash cut + 1.06×. **Last 8 frames colour-matched to frame 0** so the loop seam is invisible | **c6**, **c7**, **c8** | loop rule, §2.6 |

`12 + 68 + 47 + 91 + 91 + 91 + 50 + 75 + 50 + 87 + 88 = **750 frames = 15.000000 s**` (arithmetic re-run this session).

> **Row 8 is filmed against the shipped bot, not against the blueprint.** `03_production_blueprint.md:522` scripts a three-tap flow ending on a **`Qoʻshiq yaratish`** button. **That button does not exist in the product** — grep over `src/bayram/bot/locales/uz_latn.py` finds no `yaratish` anywhere, and no button key on that verb at all — the only *yarat-* forms in the file are `watermark.song` (*yaratilgan*, `:519`) and `watermark.invite` (*yarating*, `:520`), neither of which is a wizard button. The blueprint's 3-tap script is aspirational. An operator must film the real keys named in the row, or the "this is real UI" claim collapses.

### 2.5 Funnel-exposure budget — the table this cut is actually gated on

Neither draft stated, for any element, how many frames it is on screen or whether a muted viewer can read it. This table is the gate.

| Funnel element | First frame | Last frame | Frames | Seconds | Frames as the *newest* element |
|---|---|---|---|---|---|
| Problem stated (c1) | 0 | 126 | 127 | 2.54 | 0–79 → **80** |
| Brand name (c3) | 127 | 217 | 91 | 1.82 | 127–144 → **18** (then shares with c7) |
| **Handle `@bayram_uzbot` (c7 + c6)** | 145 | 749 | **605** | **12.10** | 575–749 at full size → **175** |
| Product claim (c4) | 218 | 399 | 182 | 3.64 | 218–399 → **182** |
| Free-preview claim (c5) | 400 | 524 | 125 | 2.50 | 400–419 → **20** |
| Product demonstration | 450 | 524 | 75 | 1.50 | 450–524 → **75** |
| **Price (c8)** | 420 | 749 | **330** | **6.60** | 420–574 → **155** |
| CTA verb (c6) | 575 | 749 | 175 | 3.50 | 575–749 → **175** |

**Pass rule (gate G16): the handle must hold ≥ 500 frames of continuous presence AND ≥ 125 frames as the newest, largest element. Both are met.** Under both draft plans the handle first appeared at frame 575 — 77% of the runtime gone before the product is named. That is fixed here.

**Post-5.0 s cut cadence.** `03_production_blueprint.md` §1.1's timeline diagram sets the rule: *"Jump-cuts every 1.5 s – 2.0 s"*. Cut lengths after 5.0 s in this plan: 1.82 s (SH-02c), 1.00 s, 1.50 s, 1.00 s, 1.74 s, 1.76 s. Every one is at or under the 2.0 s ceiling. Both drafts ran 3.50–5.46 s uncut and neither cited the rule.

### 2.6 Loop, cover frame, and the two dropouts

**Loop.** A 15 s asset lives or dies on replays, and a 0.35 s fade-out is the strongest possible "it's over" signal. **The fade is cut to 60 ms**, and the last 8 frames (742–749) are colour- and framing-matched to frame 0's bright hero look. Gate G17 measures the seam.

**Cover frame.** TikTok and Reels both show a still in grid and profile view, and Reels picks one if you do not. **Set the cover to frame 127** (the slam — bright studio, shades, confetti, `BAYRAM-BOTDA!` card). The natural default would be frame 0's cold open, which is acceptable, but the slam frame is the strongest grid thumbnail in the film. Never let the platform pick the despair shot.

**The two dropouts.** The researchers measured *two* 0.9 s sub-bass dropouts in the source window (0:31.7–0:32.6 and 0:33.1–0:34.0), mapping to 0.20–1.10 s and 1.60–2.50 s of our cut. Variant D labels only the second. Since we author our own bed under D4, these are design choices, not features to copy. **Default: author only the labelled vacuum at 1.60–2.54 s.** Adding the first is a free ffmpeg experiment on our own audio.

---

## 3. Step 0 — Render the song

### 3.1 Why this bypasses the orchestrator, and why a script is required

`pipeline/orchestrator.py` also runs payment authorisation, name resolution, STT name verification, greeting TTS and ffmpeg assembly, and it needs a database and an `Order` row. None of that applies to a promo. Hand-build a `CompositionPlan` and call `compose()` directly.

There is no operator CLI to do that with — `pyproject.toml` has no `[project.scripts]`, there is no `__main__.py` anywhere under `src/bayram`, and `bayram.demo` is hardcoded to fakes (`_demo_settings()` sets `use_fake_providers=True`, `elevenlabs_api_key="demo"` and `_env_file=None`, so it never reads `.env`). A throwaway script is required. It does not exist yet, and per `CLAUDE.md` it goes in `marketing/campaigns/peshta/` — **never at the repository root**.

### 3.2 Bootstrap the directories — nothing downstream works without this

`marketing/campaigns/peshta/` today contains only the five `.md` files and `alabay_video/`. ffmpeg does not create parent directories; every output command below fails on a missing path.

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && \
mkdir -p marketing/campaigns/peshta/{audio,raw,cards,build,demo}
```

(`shots/` was in an earlier draft of this list and nothing in the plan ever writes to it. Generated clips land in `raw/`, conformed segments in `build/`, keyframes and card PNGs in `cards/`.)

### 3.3 Gate 0a — prove we will hit the real vendor (free, opens no socket)

Run this **before** every render. I ran it this session:

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && .venv/bin/python -c "
import asyncio
from bayram.config import build_settings
from bayram.providers.music import build_music_provider

async def dry():
    s = build_settings()
    assert s.use_fake_providers is False, 'FAKE PROVIDERS ARE ON'
    p = build_music_provider(s)
    print('provider.name =', p.name)
    assert p.name == 'elevenlabs_music'
    print('would POST to', s.elevenlabs_base_url + '/v1/music',
          '?output_format=' + s.music_output_format)
    print('model', s.music_model_id, 'timeout', s.music_timeout_s,
          'usd/min', s.music_usd_per_minute, 'conc', s.music_max_concurrency)
    print('key len', len(s.elevenlabs_api_key))
    await p.aclose()
    print('DRY RUN OK - no request sent')

asyncio.run(dry())
"
```

Output this session, verbatim:

```
provider.name = elevenlabs_music
would POST to https://api.elevenlabs.io/v1/music ?output_format=mp3_44100_128
model music_v2 timeout 420.0 usd/min 0.15 conc 2
key len 51
DRY RUN OK - no request sent
```

*(Those are the script's five lines exactly, re-run this session. It does not print `use_fake_providers` — the setting is asserted, not echoed. If you want it on the transcript, add `print('use_fake_providers =', s.use_fake_providers)` to the script.)*

**Where the anti-stub guarantee actually lives.** `build_music_provider` (`src/bayram/providers/music/factory.py`) is the **live** factory: it constructs `ElevenLabsMusicProvider` unconditionally, never inspects `use_fake_providers`, and **cannot return the fake**. The fake only ever appears via `runtime.providers.build_provider_set`, which is the one all-or-nothing switch between real and fake across all five adapters (`runtime/providers.py:95`; its own `_live_set` comment reads *"ONE sink object reaches all five adapters"*). The guarantee is therefore the `settings.use_fake_providers is False` assertion **plus** the fact that this script never touches `build_provider_set`. The `provider.name` check is cheap belt-and-braces, not the guarantee. *(The memory note about a default stub refers to `checkout_provider` — payments. Music has no stub default.)*

Second, independent tell — kept even though the fake is unreachable from `build_music_provider`, because it also catches a silent or truncated **real** render: `FakeMusicProvider` writes a repeated 104-byte silent MPEG-1 Layer III frame (header `FF FB 10 C0`), 32 kbps mono. `ffmpeg -af volumedetect` reporting `max_volume: -91 dB` means silence arrived, whatever wrote it. **That reading is only visible if you do not pass `-v error`** — see §3.8.

**Run everything with `cwd` = the repo root.** `build_settings()` resolves `.env` relative to the process working directory; from anywhere else it finds no credentials and raises a `ConfigError` naming `BAYRAM_ELEVENLABS_API_KEY`.

### 3.4 Duration strategy — render 30 s, cut 15

Duration is controlled **only** by the sum of `Chunk.duration_ms`. `build_compose_body` deliberately never sends `music_length_ms` (the vendor 422s when a `composition_plan` is present). Bounds read directly from `src/bayram/contracts.py:122-126` this session:

```python
MIN_CHUNK_DURATION_MS: Final[int] = 3_000
MAX_CHUNK_DURATION_MS: Final[int] = 120_000
MIN_SONG_DURATION_MS:  Final[int] = 3_000
MAX_SONG_DURATION_MS:  Final[int] = 600_000
MAX_CHUNKS_PER_PLAN:   Final[int] = 30
```

A 15 s plan is legal. **Render 30 s anyway**, for three reasons:

1. The 0.94 s vacuum and the instantaneous slam are **below the 3000 ms chunk floor and cannot be expressed in a composition plan at all.** They must be authored in ffmpeg post from a rendered bed.
2. A longer bed gives a choice of where the usable hook starts, instead of betting the take on the first 15 seconds landing.
3. It doubles the cost from $0.0375 to $0.075 — noise.

> ⚠ **UNVERIFIED, and it shapes the chunk sizes.** `MIN_CHUNK_DURATION_MS = 3000` is asserted in a `contracts.py` comment as *"validation bounds published by the vendor"*, and nothing in the repo verifies that against the live API. ElevenLabs' public music documentation has historically stated a **10 s** minimum. A rejected chunk earns a 400/422, which `failures.py` maps to a **non-retryable** error — the ladder stops immediately, no audio, and the message complains about an invalid payload rather than about duration. **Every chunk below is ≥ 6000 ms as insurance.** If a 422 arrives, `error.context['response_detail']` carries the first 1000 chars of the vendor body and will name the offending field; the first remedy is to raise every chunk to ≥ 10 000 ms.

### 3.5 The sung lyrics — verbatim, U+02BB throughout

These are the chunk `text` values. **Every SUNG line here is corpus-verbatim** (`02_parody_lyrics.md` §2.4 rows 1, 3, 4, 5, 6 and `01_character_concepts.md` §6.3), with the corpus' ASCII apostrophes corrected to U+02BB and two singability changes noted below. **No lyric in this section is invented.** Chunk 1 is not a lyric — its `[instrumental]` direction is **authored for this plan** and appears in none of `01`, `02` or `03`.

| Chunk | ms | Text |
|---|---|---|
| 1 | 6000 | `[instrumental] lone doira, thin tense synth, no bass yet` |
| 2 | 9000 | `Sovgʻa izlab boshim qotdi...`<br>`BOTDA! BAYRAM-BOTDA!` |
| 3 | 9000 | `Isming aytib kuylar bugun, botda Bayram-botda!`<br>`O mani kuydirding, o mani suydirding!` |
| 4 | 6000 | `Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!` |

Total **30 000 ms**, four chunks, each ≥ 6000 ms.

**Four notes on the sung copy.**

- **The numeral is spelled out.** The Variant D table writes *"15 mingga qoʻshiq tayyor: kiring @bayram_uzbot!"*. A numeral is not singable and a sung `@handle` is unintelligible. Rendered as **"Oʻn besh mingga"**, and the handle moves to the card where it is read, not heard.
- **The CTA verb phrase is corpus-verbatim, and it is the grammatical one.** Uzbek *kirmoq* governs the dative, so *"kiring Bayram bot"* (no case marking) is broken Uzbek. `01_character_concepts.md:520` already contains the correct form as a scripted parody vocal tag: **"Bayram-botga kiring!"**. Use that. It is sourced, not invented.
- **The 13-syllable 4+4+5 Barmoq rule does NOT bind Variant D.** Re-running the corpus' own vowel-invariant counter: all 16 verse lines in Variants A/B/C1/C2 score exactly 13; **Variant D's lines score 8/6/14/12/14** — the repo's own harness states the same figures, `tests/test_peshta_lyrics.py:287` `expected_counts = [8, 0, 6, 14, 12, 14]` (silence row included), and that test passes. Re-running `count_uzbek_vowels` over this section's own rewritten CTA line `Oʻn besh mingga qoʻshiq tayyor, Bayram-botga kiring!` also returns **14**. The doc's own certification block says *"Lines Evaluated: 16 Verse Lines across 4 Variants"* — Variant D is excluded by design. **Do not "fix" these lines to 13 syllables.**
- **`peshta` does not appear in Variant D, and it must stay out.** It is the original hit's title and hook word. Under D4 it is the single word most likely to attract an association claim. Keep it in the campaign documents and out of anything that ships.

### 3.6 The style prompt — original soundalike, never a copy instruction

```python
POS = (
    # from styles.py Genre.UZBEK_POP
    "uzbek pop", "central asian pop", "doira percussion", "festive",
    # idiom
    "folk trap", "808 sub bass", "trap hi-hats",
    "male lead vocal", "shouted hype ad-libs", "anthemic",
    # language must come from HERE plus the chunk text — nothing else carries it
    "uzbek language vocal", "sung in uzbek",
)
NEG = (
    "explicit lyrics", "lo-fi", "muffled vocals", "spoken word",
    "english lyrics", "russian lyrics", "cover version", "karaoke backing",
)
```

**Hand-authored, not reused.** `negative_styles_for()` returns `UNIVERSAL_NEGATIVE_STYLES` = `("explicit lyrics", "aggressive", "melancholic", "distorted vocals")`, and its own comment says it was written for the birthday product — *"a celebration kit is never explicit"*. *Aggressive* and *melancholic* actively fight a folk-trap hype track. Take `explicit lyrics`; leave the other three.

**Never put "Hamdam Sobirov", "Peshta", "in the style of", "sounds like" or "cover of" in any POSITIVE style field or in chunk text.** *(`cover version` and `karaoke backing` sit in `NEG` deliberately — as **exclusions** they push the render away from the original, not toward it. `NEG` is a style field and it does go on the wire: `build_compose_body` emits `negative_styles` per chunk, `payload.py:53`. Do not strike them.)*

**The idempotency key is vendor-visible too, and it is the one place the original's title was still reaching a vendor.** `ElevenLabsMusicProvider` sends it as the `idempotency-key` **HTTP header** — `IDEMPOTENCY_HEADER: Final[str] = "idempotency-key"` (`providers/music/elevenlabs.py:96`), applied in `_headers()` at `:354` and attached to every `POST /v1/music` at `:366-370`. It is **not** a local label. §3.7's key is therefore `bayram-variant-d-bed-001`, never `peshta-...`: D4 says *"we never name him or the track anywhere a vendor can see"*, and a header is somewhere a vendor can see.

**What `failures.py` actually does — it is not a safety net.** If the vendor rejects the payload, `failures.py` will *label* that rejection `ARTIST_NAME_IN_STYLE` and mark it non-retryable: `_payload_rejection()` (`failures.py:136-143`) scans the **vendor's own 400/422 response body** for `_ARTIST_MARKERS = ("artist", "copyright", "trademark")` (`:59`) and is reached only from `map_status_error()` on a status the vendor has already returned. **It never inspects our request and prevents nothing.** ⚠ **Whether ElevenLabs rejects artist names at all is UNVERIFIED** — nothing in this repo establishes it, and no live call was made to find out. **D4 is enforced by us; the mapping only names the failure after the fact.** Do not read it as a guardrail that catches a slip. **Describe the idiom. Never the artist, never the track.**

`plan.language` is carried in the domain model for our records but is **never sent on the wire** — confirmed by printing the emitted body. Uzbek comes from the chunk text plus the two language style tags, and nothing else. Budget 2–3 takes.

### 3.7 The render script

Save as `marketing/campaigns/peshta/render_variant_d_bed.py`. **Not at the repository root.**

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from bayram.config import build_settings
from bayram.contracts import Chunk, CompositionPlan, ContextAdherence, Err, Genre, Language
from bayram.providers.music import build_music_provider, guard_plan
from bayram.providers.music.styles import positive_styles_for

OUT = Path("/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/audio/variant_d_bed_001.mp3")

# Bump this (-001 -> -002) for every DELIBERATE new take. Keep it FIXED when
# retrying a transport failure, or you pay twice for the same song.
IDEMPOTENCY_KEY = "bayram-variant-d-bed-001"   # NOT "peshta-..." — this string goes on the wire, see §3.6

POS = (
    *positive_styles_for(Genre.UZBEK_POP),
    "folk trap", "808 sub bass", "trap hi-hats",
    "male lead vocal", "shouted hype ad-libs", "anthemic",
    "uzbek language vocal", "sung in uzbek",
)
NEG = (
    "explicit lyrics", "lo-fi", "muffled vocals", "spoken word",
    "english lyrics", "russian lyrics", "cover version", "karaoke backing",
)

# U+02BB written as an escape so nothing depends on this file's encoding
# round-tripping through an editor.
TC = "\u02bb"   # ʻ  MODIFIER LETTER TURNED COMMA

PLAN = CompositionPlan(
    chunks=(
        Chunk(text="[instrumental] lone doira, thin tense synth, no bass yet",
              duration_ms=6000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.MEDIUM),
        Chunk(text=f"Sovg{TC}a izlab boshim qotdi...\nBOTDA! BAYRAM-BOTDA!",
              duration_ms=9000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
        Chunk(text="Isming aytib kuylar bugun, botda Bayram-botda!\n"
                   "O mani kuydirding, o mani suydirding!",
              duration_ms=9000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
        Chunk(text=f"O{TC}n besh mingga qo{TC}shiq tayyor, Bayram-botga kiring!",
              duration_ms=6000, positive_styles=POS, negative_styles=NEG,
              context_adherence=ContextAdherence.HIGH),
    ),
    language=Language.UZ_LATN,          # our records only; NOT sent to the vendor
    seed=20260918,                      # same seed + same plan = reproducible take
    is_instrumental=False,
    should_store_for_inpainting=True,   # keeps a song-id so ONE chunk can be re-rolled
)


async def main() -> int:
    settings = build_settings()

    if settings.use_fake_providers:                      # gate 1
        print("REFUSING: fake providers on; this writes silent MP3 frames.")
        return 2

    guarded = guard_plan(PLAN)                           # gate 2 — a bad plan costs nothing
    if isinstance(guarded, Err):
        print("plan rejected locally:", guarded.error.operator_message)
        return 2

    provider = build_music_provider(settings)
    if provider.name != "elevenlabs_music":              # gate 3
        print(f"REFUSING: provider is {provider.name!r}")
        await provider.aclose()
        return 2

    est = PLAN.total_duration_ms / 60000 * settings.music_usd_per_minute
    print(f"rendering {PLAN.total_duration_ms}ms via {provider.name} "
          f"({settings.music_model_id}, {settings.music_output_format}) est ${est:.4f}")

    try:
        result = await provider.compose(
            PLAN, idempotency_key=IDEMPOTENCY_KEY, timeout_s=settings.music_timeout_s
        )
        if isinstance(result, Err):
            e = result.error
            print(f"FAILED code={e.error_code.value} retryable={e.is_retryable}")
            print(f"       {e.operator_message}")
            print(f"       context={e.context}")
            return 1
        audio = result.value
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(audio.data)
        print(f"wrote {OUT}  {len(audio.data):,} bytes  mime={audio.mime}")
        print(f"  requested_duration_s={audio.duration_s}  (REQUESTED, not measured)")
        print(f"  remote_id={audio.remote_id!r}  (None => this take cannot be inpainted)")
        print(f"  cost_usd={audio.cost_usd} ({audio.cost_source.value})")
        return 0
    finally:
        await provider.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && .venv/bin/python marketing/campaigns/peshta/render_variant_d_bed.py
```

> ⚠ **AMENDED 2026-09-18, Phase A. The code block above is a transcription; `marketing/campaigns/peshta/render_variant_d_bed.py` on disk is the authority.** The shipped script differs from the block in three ways, and the command above is now a **DRY RUN** that sends nothing.
>
> 1. **Spending is opt-in.** No arguments = build the body, print it, send nothing. A real render needs the flag with the idempotency key as its value: `--spend-real-money=bayram-variant-d-bed-001`. **This is the Phase B command.**
> 2. **Why the flag takes a value.** The first version used a plain boolean `--spend-real-money`, and **that was not accident-proof: `argparse` abbreviates long options by default, so `--spend` matched it and bought a song during a test written to prove it would not.** ~$0.075 was spent unauthorised and `marketing/campaigns/peshta/audio/variant_d_bed_001.mp3` (480,698 bytes, 30.04 s, `max_volume -0.2 dB`, `remote_id=LIZxbNHtSqirtfbLeSrA`) exists as a result. The script now runs `argparse` with `allow_abbrev=False` **and** requires the key typed out. Both locks were re-tested; `--spend`, `--spend-real`, a bare `--spend-real-money` and a wrong key all refuse and send nothing.
> 3. **The D4 rights position is enforced in code, not by review.** `rights_violations()` refuses before anything is sent if "hamdam sobirov" or "peshta" appears in the idempotency key or in any chunk's text, positive **or negative** styles, or if "in the style of" / "sounds like" / "cover of" appears in text or positive styles. Negative styles are exempt from that second list only — §3.6's reasoning — so the shipped `cover version` and `karaoke backing` pass.
>
> **Before Phase B, decide what the accidental take is worth.** It is a real, non-silent 30 s render of this exact plan, so §3.9's listen-and-approve gate can run on it now for free. If it is approved, Phase B is already paid for. If it is not, **bump the key to `-002`** — re-running `-001` risks the vendor replaying the cached take instead of rendering a new one, and whether ElevenLabs honours `idempotency-key` that way is UNVERIFIED here.

**Operator notes.**

- `compose()` **never raises.** Every outcome is `Ok[RenderedAudio]` or `Err` — an httpx exception that escaped would bypass the retry ladder's `is_retryable` decision. Read the `Err`; do not wrap this in a try/except for control flow.
- Retryable: 429 (`ProviderRateLimitedError`, surfaces `Retry-After`), 5xx and transport resets (`ProviderUnavailableError`), timeouts, and a 200 whose body is not audio. **Terminal:** 401/403 (config), 402 (quota), 400/422 (rejected content or invalid input).
- This calls `compose()` **once**, with no retry ladder. For the pipeline's 4-attempt backoff, wrap it — and note that `call_with_retry` returns a **2-tuple**, `tuple[Result[T], RetryReport]` (`src/bayram/pipeline/retry.py:99-107`), not a bare `Result`. Unpack it, or `isinstance(result, Err)` is a tuple test that is always false and every failure reads as a success:
  ```python
  result, report = await bayram.pipeline.retry.call_with_retry(
      lambda: provider.compose(PLAN, idempotency_key=IDEMPOTENCY_KEY,
                               timeout_s=settings.music_timeout_s),
      label="music.compose",
      policy=RetryPolicy.from_settings(settings),
      sleeper=asyncio.sleep,
  )
  ```
- `RenderedAudio.duration_s` is the duration we **asked for**, not a measured one. Only ffprobe tells you what arrived.
- `cost_usd` is always `CostSource.ESTIMATED` and can never be anything else — `POST /v1/music` returns audio and no price. The rate is ours: `music_usd_per_minute = 0.15` (shipped default; `.env` holds no `BAYRAM_MUSIC_*` keys). Setting it to 0.0 does not make a render free; it makes `cost_usd` 0.0 and leaves the usage row NULL, meaning "not priced".
- `music_max_concurrency = 2` is a hard vendor ceiling on this tier, enforced by an `asyncio.Semaphore` inside the adapter. Do not run two renders in parallel.
- Every call writes a greppable `music.usage` log line and a `VendorUsage` row even on failure. With no database the default `LOGGING_USAGE_SINK` puts them on stdout, so a throwaway script is still measured.
- The provider writes nothing to disk; the bytes are in memory and this script saves them itself.

### 3.8 Step 0.5 — measure what actually arrived

**This is the step the whole plan turns on. Do not skip it, and do not buy video before it is done.**

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && \
ffprobe -v error \
  -show_entries format=duration,bit_rate,size \
  -show_entries stream=codec_name,channels,sample_rate \
  -of default=noprint_wrappers=1 marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 && \
ffmpeg -hide_banner -nostdin -i marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 \
  -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
```

> **No `-v error` on the `volumedetect` command, ever.** `volumedetect` prints its summary at `AV_LOG_INFO`, so `-v error` suppresses the only output the check exists to read. I ran both forms this session: with `-v error` the grep matches **zero lines and exits 1**; without it, `mean_volume` and `max_volume` both print. A gate written the first way can never print a number — it just falls through, which is the never-goes-red gate §12 condemns. Same correction applies to G4.

Pass: duration ≈ 30 s, `max_volume` well above −91 dB. **A −91 dB reading means silence arrived** (`FakeMusicProvider`'s signature, though §3.3 explains the fake cannot reach this path — a truncated or dead real render reads the same way). **An empty grep is a FAIL, not a pass:** in `qa_gate.py` pipe through `grep -q` and fail on its non-zero exit rather than on the absence of a number.

Then measure the tempo. **There is no BPM tooling on this machine** — aubio, librosa, numpy, scipy, soundfile, sox and bpm-tools are all absent from both interpreters and the PATH. A pure-stdlib RMS-onset-envelope + autocorrelation detector fills the gap; it read **95.70 BPM** off the existing promo audio against a declared 95.8, in 0.04 s.

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && \
.venv/bin/python marketing/campaigns/peshta/bpm_detect.py marketing/campaigns/peshta/audio/variant_d_bed_001.mp3
```

It prints the top-5 candidate lags so a half-tempo or double-tempo read is visible rather than silent.

**Then do the re-derivation, on paper, for free:**

1. `bar = 240 ÷ measured_BPM`; `six_bars = 6 × bar`.
2. Open the file and mark the real transients — where the hook enters, the biggest downbeat, the vocal run, the cadence turnaround.
3. Rewrite the §2.4 table against those marks. The shape survives (cold open → despair → vacuum → slam → dance → demo → CTA); the numbers move.
4. Pick the master fps so the real slam is an integer frame, and **re-derive every segment length so they sum to a whole number of frames.** 50 fps suits a 2.54 s slam; 2.60 s suits 30/50/60 equally.
5. Recompute the per-shot durations in §6 and re-preflight their cost with `get_cost:true` before approving the spend.

If the measured tempo is within a few BPM of 95.8, the table stands and this is ten minutes of confirmation. If it is not, this step just saved the video budget.

### 3.9 Listen-and-approve gate

There is **no acoustic check on this path.** The repo's STT verification loop exists only to verify a recipient's *name* inside the full orchestrator, and this script bypasses it. Nothing programmatically confirms the vocals say the Uzbek lines or that the CTA is intelligible — and a mumbled CTA kills the conversion the whole video exists for.

A human listens and approves, explicitly, before Step 1. Checklist: Uzbek, not English or Russian-accented; `oʻ` and `gʻ` not mangled; "BAYRAM-BOTDA" lands as a hard staccato shout; "Oʻn besh mingga" is intelligible; "Bayram-botga kiring" is intelligible; no profanity or nonsense syllables.

If one chunk is wrong and the rest is good, `provider.inpaint()` re-rolls that single chunk far cheaper than a full recompose — **but only if `store_for_inpainting=True` was sent AND the vendor returned the song-id header**, which the code treats as optional. Check the printed `remote_id`; `None` means this take cannot be inpainted and a bad chunk costs a whole new render.

---

## 4. Step 1 — Keyframes

**Stills are 2 credits; video is 7–54.** Every identity, wardrobe, anatomy and framing decision gets settled at 2 credits a look, and only frames that pass are animated.

### 4.1 Model

**`nano_banana_pro`, `aspect_ratio: "9:16"`, `resolution: "2k"` — 2 credits per image.** Preflighted live this session: `{"cost":{"credits":2,"credits_exact":2}}`. Chosen because it is the cheapest 2k 9:16 image in the catalog *that also accepts an `image_references` role*, which is what makes hero-keyframe reuse possible at all.

Rejected alternatives, all preflighted at 9:16:

| Model | Config | Credits | Why not |
|---|---|---|---|
| `soul_cast` | — | 1 | **Unusable.** Declares `aspect_ratios: ["16:9"]` only and exposes no `medias` input; the cost probe silently forced 16:9. |
| `soul_2` | 1.5k/2k | 1 (0.12 exact) | Human-portrait model, capped at one reference image. |
| `gpt_image_2_5` | 1k / medium | 1 | Kept as a safe-build alternate face. |
| `gpt_image_2_5` | 2k / high | 3 | Sharper; safe-build alternate. |
| `gpt_image_2_5` | 4k / max | 16 | Pointless against a 1080×1920 target. |
| `cinematic_studio_2_5` | 2k | 2 | Viable tie, no advantage here. |
| `seedream_v4_5` | basic | 1 | Cheapest, lower fidelity on fur and embroidery. |
| `gpt_image_2` | 2k / high | 6.5 | 3× the price for no gain at this output size. |

**`gpt_image_2_5`'s text-rendering strength is irrelevant here and must not be leaned on.** `03 §4.1` forbids AI-rendered text and phone UI outright.

### 4.2 Absolute prompt rules

- **Prompt text is English.** No Uzbek inside any image prompt.
- **No text in the image, ever.** `03_production_blueprint.md` §4.1: *"Under no circumstances will text or phone screen UI be rendered with AI."* Every caption, badge and handle is composited in post. The discarded build violated this and it is its single most visible failure (§12).
- Every previously-established detail carries forward **verbatim** in every subsequent prompt. That is the cheap half of character consistency, and it is free.

### 4.3 The MASTER SUBJECT BLOCK (repeated verbatim in every image and video prompt)

> `A massive, majestic Central Asian Shepherd dog (Alabay), snow-white and fawn fur, wide chest, docked ears, powerful noble posture, projecting immense unbothered swagger. It wears an authentic traditional black-and-white embroidered Uzbek Chust doppi skullcap tilted on its head, an oversized chunky polished 24k gold Cuban link chain resting on its thick neck fur, retro black 1990s RECTANGULAR sunglasses, and an open sleeveless black velvet mini-chopon with gold trim over its shoulders. Two SMALLER Tashkent street pups stand behind as hype-men, wearing plain backward baseball caps and gold rings on their collars. High-end Central Asian streetwear aesthetic, photorealistic white and fawn fur texture, ultra-sharp focus, cinematic depth of field, 8k, shot on 35mm lens, vertical composition.`

"RECTANGULAR", "SMALLER" and "plain" are load-bearing: the discarded build delivered aviators, two full-size adults, and branded hoodies.

*(Midjourney v6.1 and Kling v1.5, which `01 §6.1` specifies, do not exist in this account's catalog — there is no Midjourney at all, and the Kling line is `kling3_0` / `kling2_6` / `kling3_0_turbo`. The prompt TEXT carries forward; the model ids do not.)*

### 4.4 The keyframe set

| ID | Covers | Prompt delta appended to the MASTER SUBJECT BLOCK | `image_references` | Credits |
|---|---|---|---|---|
| **KF-2 (HERO)** | frames 0–11 cold open, 127–399, 525–574 | *"Explosive high-energy medium shot, mid shoulder-bounce dance, chin up, confident smirk, sunglasses ON catching a hard specular flash. Bright modern studio set, warm wedding-banquet key light with amber and magenta rim accents, gold confetti bursting mid-air, the two smaller hype-pups bouncing behind and slightly out of focus. Clean uncluttered background with NO signage of any kind. Vertical 9:16, subject centred between x=120 and x=940 of a 1080-wide frame, clean space above and below."* | — | **2** |
| **KF-1** | frames 12–126 | *"Tight vertical close-up, head and shoulders. The dog slumped and crestfallen, holding up a pair of cheap thin grey synthetic socks in one paw, total comic despair, ears drooping. **Retro rectangular sunglasses ON but pushed DOWN the muzzle so the eyes are fully visible over the top.** Late-night apartment interior, warm practical lamp behind, cool blue fill — dim but not dark, the doppi and gold chain must stay clearly legible. Same dog, same doppi, same gold chain. Generous clean negative space in the top 250 and bottom 420 pixels."* | **KF-2** | **2** |
| **KF-3** | frames 400–449 | *"Over-the-shoulder medium. A modern smartphone propped upright on a warm-lit table, screen facing camera and COMPLETELY BLANK matte dark grey — no interface, no text, no icons, no graphics of any kind. Warm domestic interior bokeh, festive string lights out of focus. The Alabay is soft-focus in the background, smiling. Shallow depth of field, phone occupying the central third."* | **KF-2** | **2** |
| **KF-4** | frames 575–749 | *"Medium-wide, same bright studio set as the hero shot. The dog faces camera with a broad confident open-mouthed grin, one front paw raised and pointing decisively down and forward toward the bottom of the frame. Sunglasses ON. Gold confetti settling. The lower third of the frame kept visually clean, empty and uncluttered for a graphic overlay."* | **KF-2** | **2** |
| **KF-1b** | SH-01's `end_image`; source of the frame 80–126 snap-zoom | *Second despair look, the peak of the beat: same framing and lighting as KF-1, head dropped further, ears flatter, the socks lowered. This is the frame the vacuum pushes into, so it must be worth holding for 47 frames.* | **KF-2** | **2** |
| **Reroll budget** | — | Up to 6 further rolls, spent as G7 demands. **This is deliberately larger than either draft's 1–2 spares.** The discarded build produced "TASHKENT" and "ALABAY HYPE SQUAD" *despite* a negative prompt that already banned `text`, and `01 §4.3` prescribes "top 3 cleanest of 15 rolls". At 2 credits a still, roll stills — never clips. | — | *up to 12* |

**Committed keyframe floor: 10 credits (KF-2, KF-1, KF-1b, KF-3, KF-4). Realistic ceiling with rerolls: 22.** KF-1b is committed, not optional: §5 Rank 4 and the §6.4 clip table both make it SH-01's required `end_image`, so a lean build that reaches Phase E without it cannot submit SH-01 as specified.

**There is no keyframe for the vacuum beat.** Frames 80–126 are a snap-zoom on SH-01's last frame, built in ffmpeg. That is one full beat of the film for **zero credits**, and it is more faithful than any generated motion.

### 4.5 Negative prompt (every keyframe, verbatim)

```
text, lettering, words, letters, writing, signage, logo, brand marks, watermark,
signature, caption, subtitle, user interface, phone screen graphics, app icons,
hoodie graphics, jacket logos, neon signs, storefront text,
cartoon, 3d render, plastic toy, illustration, anime,
deformed paws, six toes, six paws, extra limbs, extra legs, bad canine anatomy,
human hands, human fingers, anthropomorphic hands, blurry face, melted face,
aviator sunglasses, bandana, du-rag, adult-sized sidekick dogs,
oversaturated neon, low quality, jpeg artifacts, cropped subject
```

The last four wardrobe entries and the four signage entries are lessons from the discarded build, which produced exactly those defects. **A negative prompt is a preference, not a guarantee** — the original bible's list already banned `text` and `watermark` and the output had signage anyway. Every keyframe gets eyeballed at full size before it is used, and that check is gate G7.

### 4.6 The exact call

```
mcp__higgsfield__generate_image params={
  "model": "nano_banana_pro",
  "prompt": "<MASTER SUBJECT BLOCK> <per-shot delta>",
  "aspect_ratio": "9:16",
  "resolution": "2k",
  "get_cost": true          ← REMOVE THIS LINE TO ACTUALLY GENERATE
}
```

For KF-1 / KF-1b / KF-3 / KF-4, add: `"medias": [{"role": "image_references", "value": "<KF-2 job_id>"}]`.

---

## 5. Step 2 — Character consistency

Ranked cheapest-and-most-certain first. Identity drift is the single biggest quality risk for a mascot, and the discarded build failed on it *within one 5-second clip* — the lead's headwear morphed from a bandana into a doppi between 2.0 s and 3.0 s.

### Rank 1 — Verbatim prompt carry-forward. **0 credits. Never optional.**

Every prompt reuses the MASTER SUBJECT BLOCK character-for-character. Do not paraphrase between shots. (This is the `character-sheet` workflow's Principle 4, the only technique in the 16 bundled workflows that transfers here — none of the workflows themselves apply: `character-sheet` targets 16:9 and says "Do not generate without an explicit ask", `ad-multiplier` needs an existing video, and every `ugc-*` / `faceless-video` flow requires a human presenter.)

### Rank 2 — Hero-keyframe reuse via `image_references`. **0 extra credits.**

KF-1 / KF-1b / KF-3 / KF-4 are generated *from* the approved KF-2 rather than from text. Same 2-credit price, dramatically better identity coherence. This is the structural reason the hero keyframe is generated and inspected first.

### Rank 3 — `start_image` chaining into video. **0 extra credits.**

Every clip starts from its approved still. `wan3_0`'s roles are verified live as `start_image, end_image, image_references, video_references, audio_references`, so the still is a hard anchor, not a suggestion. Identity is decided *before* the expensive step.

### Rank 4 — `end_image` chaining for the freeze. **0 extra credits.**

For SH-01, pass **KF-1 as `start_image` and KF-1b (the despair peak) as `end_image`** so the clip resolves onto exactly the frame the snap-zoom starts from. This makes the vacuum-and-slam sequence frame-deterministic instead of hoping the model lands somewhere usable.

### Rank 5 — Reference Elements. **Price undocumented. Safe build only, and NOT on `wan3_0`.**

```
mcp__higgsfield__show_reference_elements action="create" name="alabay-hype"
  category="character"
  medias=[{"id":"<media_id>","url":"https://upload.higgsfield.ai/...","type":"media_input"}]
```

Instant, synchronous, built from a single image, multiple `<<<element_id>>>` placeholders per prompt. Requires `media_upload` → PUT bytes → `media_confirm` first. I checked the workspace this session: `show_reference_elements action="list"` returns `{"items":[],"next_cursor":null}` — nothing exists yet.

**The decisive constraint.** The published Elements-supported video list names `cinematic_studio_video_2/3.0`, **`seedance_2_0`** and **`kling3_0`**. It does **not** name `wan3_0` and does **not** name `seedance_2_5`. So **Elements and the lean build's `wan3_0` are mutually exclusive.** Buying the lock means moving shot generation to `seedance_2_0` at 9 cr/s — a 2.6× price step, which is exactly what the safe build does (and why it picks `2_0` over `2_5`: same price, keeps the lock).

> ⚠ **UNVERIFIED:** Elements creation has no documented credit price and could not be probed without an `action="create"` call. Budgeted as *unpriced*, not as zero. Read the response before proceeding.

### Rank 6 — Soul training. **DO NOT DO THIS.**

The tool's own guard rules it out rather than this being our judgement: `show_characters` states *"Trained Soul is usable ONLY with `soul_2` and `soul_cinematic`"* and *"→ Force Elements: >1 character in shot, **non-person subject**, single image…"*. An Alabay is a non-person subject and the shot has three of them. Cost is also unknown (no price field anywhere in the schema, and `action='train'` is forbidden this turn).

### Fallback ladder

1. Ranks 1–4 (all free). If drift is acceptable across the four shots — ship.
2. Drift visible **between** shots → reroll the failing keyframe only (2 credits). Never reroll the clip first.
3. Drift visible **inside** a clip → **shorten the clip.** Drift is time-dependent; at `wan3_0`'s 2 s floor with integer durations, three 2 s clips cost the same 21 credits as one 6 s clip and hold identity better.
4. Persistent failure on one shot → switch **that shot only** to `seedance_2_0` with `<<<element_id>>>` at 9 cr/s. Never escalate globally on one bad shot.
5. Persistent canine-anatomy failure on the dance → `hf_mult_motion_control` (Genjutsu), transferring motion from a real driving dance clip onto the Alabay stills. **Price unknown** — `get_cost` returns HTTP 422 unless a real `video_references` item is attached. Upload a driving clip and preflight before treating this as a budget line.

---

## 6. Step 3 — Shot generation

### 6.1 Model ruling

Hard requirements: accepts an `audio_references` role, has a switch to turn generated audio **off**, offers 1080p, offers 9:16. Exactly four catalog models satisfy all four.

| Model | cr/s @1080p 9:16 | Duration range | Elements? | Verdict |
|---|---|---|---|---|
| **`wan3_0`** | **3.5** | **2–30 s, any integer** | No | **LEAN BUILD WORKHORSE** |
| `wan3_0_prime` | 6 | 2–30 s | No | Quality step-up if `wan3_0` underperforms |
| `seedance_2_0` | 9 | 4–15 s | **Yes** | **SAFE BUILD WORKHORSE** |
| `seedance_2_5` | 9 | 4–30 s | **No** | Same price as `2_0`, loses Elements. Avoid. |

**Chosen: `wan3_0`.** I pulled its definition live this session:

```
parameters:   duration (2-30, or -1 smart billed as 10s), resolution (480p|720p|1080p),
              generate_audio (bool, default TRUE), enable_thinking (bool)
medias:       ONE slot, type "image", roles [start_image, end_image, image_references,
              video_references, audio_references]
aspect_ratios: [auto, 16:9, 9:16, 1:1, 4:3, 3:4]
unlim:        {"available": false}
```

Three reasons: (1) it takes our track as an audio reference and lets us switch its own audio off, so we get a clean silent plate conditioned on the real beat; (2) **integer durations from 2 s** — the one that matters, because the Variant D beats are 1.36 / 0.94 / 5.46 / 1.00 / 3.50 s and `seedance`'s 4 s floor forces waste on every short beat; (3) 3.5 cr/s, 2.57× cheaper than either seedance.

Rejected, with reasons: `kling3_0` is far cheaper (1.75 cr/s pro with `sound:"off"`) and its tags advertise "audio sync, motion transfer", but its declared roles are **only** `start_image` / `end_image` — no audio input, so the motion-transfer tag is unreachable here. **Kept as the R1 fallback:** the moment audio-reference sync is proven not to work, Kling's lack of an audio role stops mattering. **Its declared duration range is 3–15 s (verified live this session), so its floor is 3 s, not 2** — SH-01 (needs 1.36 s) and SH-03 (needs 1.00 s) must each be generated at 3 s, making the fallback 3 + 6 + 3 + 4 = **16 s ≈ 28 credits instead of 49** (preflighted: 3 s → 5.25, 6 s → 10.5, 4 s → 7, at pro `sound:"off"`). `minimax_h3` is 2 cr/s and takes `audio_references` but exposes **no** `generate_audio` toggle, so a clean silent plate cannot be guaranteed (and it is 2K-only). `flux_3_video` and both `gemini_omni` variants take no audio reference at all. `grok_video_v15`'s `aspect_ratios` list is empty, so 9:16 is unproven. A single 15 s `seedance_2_5` take (135 credits) is cheaper than four seedance clips (162) but surrenders per-beat cut control, and Variant D is *built* on a hard cut at 2.54 s — rejected on craft, not price.

**`reframe` is never called:** 138 credits for 15 s at 1080p, for output every recommended model already produces natively vertical. **`bytedance_video_upscale` with `fps:60` is never called** either: it doubles that pass's cost (0.1 → 0.2 confirmed) and 50 fps comes free from ffmpeg.

### 6.2 Gate A2a — the FREE check that comes before the 7-credit probe

> **The `audio_references` role has never been exercised on this account, and there is a concrete mechanism for why it might not work: the media slot is declared `type: "image"`.** One slot, typed image, carrying audio and video roles. An audio `media_id` may be rejected outright — and it would fail at *submission*, not at the sync check.

Before spending anything, upload the 15 s cut (`media_upload` → PUT bytes → `media_confirm`, all free) and run a `get_cost` with it attached:

```
mcp__higgsfield__generate_video params={
  "model": "wan3_0", "prompt": "<SH-02 prompt>", "aspect_ratio": "9:16",
  "resolution": "720p", "duration": 4, "generate_audio": false,
  "medias": [
    {"role": "start_image",      "value": "<KF-2 job_id>"},
    {"role": "audio_references", "value": "<15s cut media_id>"}
  ],
  "get_cost": true
}
```

`get_cost` **does** validate `medias` — I confirmed this indirectly: `hf_mult_motion_control` returns HTTP 422 `[{"type":"too_short","loc":["video_references"]}]` on a cost probe with no media attached. So a type rejection here surfaces for free.

**Also unstated anywhere in the dossier and worth settling in the same free step: the accepted audio container, duration cap and size limit for an `audio_references` item.** Try the 48 kHz stereo WAV first; if `media_confirm` rejects it, fall back to the 192 kbps MP3.

**Pass → proceed to A2. 422 or a media-type rejection → the audio-first premise is dead at zero cost.** Drop `audio_references` entirely, beat-match by hand in ffmpeg (free — the cut points are already known to the frame), and **switch the workhorse to `kling3_0` pro `sound:"off"` at 1.75 cr/s**, cutting the shot budget from 49 to ~28 credits (16 s, because Kling's duration floor is 3 s — §6.1).

### 6.3 Gate A2 — the 7-credit probe

```
mcp__higgsfield__generate_video params={
  "model": "wan3_0",
  "prompt": "<the SH-02 prompt below, verbatim>",
  "aspect_ratio": "9:16",
  "resolution": "720p",
  "duration": 4,
  "generate_audio": false,
  "enable_thinking": true,
  "medias": [
    {"role": "start_image",      "value": "<KF-2 job_id>"},
    {"role": "audio_references", "value": "<15s cut media_id>"}
  ]
}
```

**7 credits** — preflighted live this session (`wan3_0`, 720p, 9:16, 4 s, audio off → `{"credits":7}`). `enable_thinking` is a documented `wan3_0` parameter ("slower, better prompt adherence") and did not change the preflight price.

Verify frame-accurately, not by feel:

```bash
ffprobe -v error -show_entries stream=width,height,r_frame_rate,duration,nb_frames \
  -of default=noprint_wrappers=1 marketing/campaigns/peshta/raw/probe.mp4
rm -f /tmp/f_*.png
ffmpeg -v error -i marketing/campaigns/peshta/raw/probe.mp4 -vf "select='between(t,2.3,2.8)'" -fps_mode passthrough /tmp/f_%03d.png
ls /tmp/f_*.png | wc -l    # must be > 0, or the seek went past EOF
```

> **`-fps_mode passthrough`, never `-vsync 0`.** `-vsync` was **removed** in ffmpeg 9.0.1 — the build on this machine. Verified this session: the `-vsync 0` form aborts with `Unrecognized option 'vsync'. Error splitting the argument list: Option not found`, **exit code 8, zero PNGs written**, before a single frame is decoded; the `-fps_mode passthrough` form exits 0 and writes 25 PNGs from the same clip. That matters *here* more than anywhere else in the plan: this is the kill switch that decides whether the remaining 42 credits are spent. A dead command makes `ls | wc -l` print `0`, the comment above hands the operator the wrong diagnosis ("the seek went past EOF"), and a perfectly good 7-credit probe reads as a broken render — whose documented response is to abandon the audio-first premise or reroll. **If the count is 0, check the ffmpeg exit status before believing the clip is at fault.**

**Three questions, answered here and nowhere later:** (a) does motion show any relationship to the track's transients — a visible accent within ±2 frames of the slam? (b) does identity hold across 4 seconds of motion? (c) **what fps did it actually come back at?** No catalog model declares one, and the only real Higgsfield clip on disk came back at 24 fps.

**Fail on (a) → drop `audio_references`, switch to `kling3_0`, re-cost, and beat-match by hand.** That decision belongs *here*, before 42 more credits.

### 6.4 The clip table (lean build)

Every clip: `aspect_ratio: "9:16"`, `resolution: "1080p"`, `generate_audio: false`, `enable_thinking: true`, `medias` carries `start_image` plus `audio_references` = the 15 s cut.

| ID | Frames it covers | Gen dur | Trim to | `start_image` | `end_image` | Audio ref | Credits |
|---|---|---|---|---|---|---|---|
| **cold open** | 0–11 (0.24 s) | — **ffmpeg snap-zoom on KF-2** — | 0.240 s | — | — | — | **0** |
| **SH-01** | 12–79 (1.36 s) | 2 s | 1.360 s | KF-1 | KF-1b | ✓ | **7** |
| **vacuum** | 80–126 (0.94 s) | — **ffmpeg snap-zoom on SH-01's last frame** — | 0.940 s | — | — | — | **0** |
| **SH-02** | 127–399 + 525–574 (6.46 s delivered) | 6 s | 5.46 s (in 3 punch-in segments) + 1.00 s reaction window | **KF-2** | — | ✓ | **21** |
| **SH-03** | 400–449 (1.00 s) | 2 s | 1.000 s | KF-3 | — | ✓ | **7** |
| **demo** | 450–524 (1.50 s) | — **real screen recording of the live bot** — | 1.500 s | — | — | — | **0** |
| **SH-04** | 575–749 (3.50 s) | 4 s | 3.500 s (in 2 punch-in segments) | KF-4 | — | ✓ | **14** |
| | **14 s generated → 15.000 s delivered** | | | | | | **49** |

Preflighted live this session at 1080p 9:16 audio-off: 2 s → 7, 4 s → 14, 6 s → 21. Flat 3.5 cr/s. Generation waste: **0 s** — the 6 s SH-02 clip supplies 6.46 s of screen time, because the reaction beat at 10.50–11.50 s is cut from its final second.

> **That is an overlap, not free footage, and the plan says so rather than pretending otherwise.** §7.5(c) cuts `s06` from SH-02 at 3.64–5.46 s and `s09` at 5.00–6.00 s, so **0.46 s of source is used twice** — master frames 525–547 replay the action of frames 377–399 at a different scale, 3 s apart. It is a distinctive shoulder-bounce, so a viewer may notice it on a second watch. **Ruling: accept the reuse and document it** (§2.4 row 9), because the fix costs credits. *The clean alternative, if the repeat reads badly at G10: generate SH-02 at **7 s** for **24.5 credits** (+3.5) — `wan3_0` accepts any integer 2–30 — re-preflight it with `get_cost:true`, and cut `s09` at `-ss 5.80 -t 1.000`, which is disjoint from every other window. That changes the Phase E ledger, so it needs a fresh green light.*

### 6.5 Shot prompts, in full

Each prepends the §4.3 MASTER SUBJECT BLOCK verbatim and uses the §4.5 negative prompt. Motion intensity guidance from `01 §4.3`: **lock to 3.5–4.5**; above ~6 paws turn into human hands and doppi patterns dissolve. Prefer named camera moves over character acrobatics. **Never attempt tight mouth lipsync on an AI mascot** — energy comes from beat-synced head nods, camera push-ins and body posture.

**SH-01 (2 s, 1080p, start_image KF-1, end_image KF-1b) — "The Dilemma"**

> `[MASTER SUBJECT BLOCK]. The dog sits slumped in a late-night apartment holding up a pair of cheap thin grey socks, shoulders sagging, ears drooping under the Chust doppi, shaking its head slowly in weary comic defeat. Retro rectangular sunglasses stay ON, pushed down the muzzle, eyes fully visible over the top. Slow confident camera push in toward the face. Warm practical lamp behind, cool blue phone-screen fill — dim but not dark; the doppi embroidery and gold chain stay clearly legible. Minimal body movement, natural fur movement, high motion stability, cinematic depth of field, photorealistic, professional music-video grading. No text anywhere in frame. Camera: slow push in. Motion intensity: 3.5.`

**SH-02 (6 s, 1080p, start_image KF-2) — "The Drop", the shot that carries the film**

> `[MASTER SUBJECT BLOCK]. The dog bursts into a heavy, rhythmic shoulder-bounce dance with supreme unbothered boss swagger — deep head nods on the beat, shoulder dips, chin lifted, a confident smirk. Retro rectangular sunglasses ON, catching hard specular flashes from warm banquet lights. The two smaller hype-pups bounce in rhythm behind, slightly out of focus. Gold confetti bursts and falls through the frame. Bright modern studio set, warm amber key with magenta rim accents, clean uncluttered background with NO signage of any kind. Camera snaps in with a fast dynamic push, then holds a locked medium. Natural fur movement, ears perked under the doppi, no mouth articulation beyond the smirk, high motion stability, cinematic depth of field, photorealistic, professional music-video grading. No text anywhere in frame. Camera: fast push in, then hold. Motion intensity: 4.5.`

**SH-03 (2 s, 1080p, start_image KF-3) — "The Payoff"**

> `A modern smartphone propped upright on a warm-lit table, screen facing camera and COMPLETELY BLANK matte dark grey — no interface, no text, no icons, no writing, no graphics of any kind. The phone catches a soft moving highlight. Warm domestic interior bokeh behind with festive string lights out of focus, gentle background movement. [MASTER SUBJECT BLOCK] visible only as a soft out-of-focus shape behind, shoulders shaking with delighted laughter. Very slow camera drift down onto the phone. Shallow depth of field, photorealistic, high motion stability. No text anywhere in frame. Camera: slow drift down. Motion intensity: 3.5.`

**SH-04 (4 s, 1080p, start_image KF-4) — "The CTA"**

> `[MASTER SUBJECT BLOCK]. The dog looks straight down the lens with a broad confident open-mouthed grin and raises one front paw, pointing decisively down and forward toward the bottom of the frame, holding the point with two firm rhythmic emphasis pushes on the beat. Retro rectangular sunglasses ON. Same bright studio set with warm amber key and subtle neon blue fill, gold confetti settling. The lower third of the frame stays visually clean and simple. Camera holds a locked medium with a very slight push. No mouth articulation beyond the open grin, natural fur movement, high motion stability, photorealistic, professional music-video grading. No text anywhere in frame. Camera: locked off, slight push. Motion intensity: 4.0.`

### 6.6 Getting the generated clips onto disk — the step both drafts skipped

**`generate_video` returns a JOB, not a file.** Every ffmpeg command in §7 reads a local `.mp4` that does not exist until this runs. Neither draft had this step, and without it Phase D cannot start.

```
1. mcp__higgsfield__generate_video  params={... , no get_cost}   → returns job id(s)
2. mcp__higgsfield__jobs_wait       with those job ids           → blocks until complete
3. mcp__higgsfield__show_generation_by_ids  with those job ids   → returns the asset URL(s)
4. curl -fsSL -o marketing/campaigns/peshta/raw/SH-02.mp4 '<asset url>'
5. ffprobe the file BEFORE anything else (§6.7)
6. THE SAME SEQUENCE RETRIEVES THE KEYFRAMES. `generate_image` also returns a job, and
   nothing else in this plan downloads a still. Run `jobs_wait` → `show_generation_by_ids`
   → `curl` for each approved keyframe, to:
     marketing/campaigns/peshta/cards/KF2.png   marketing/campaigns/peshta/cards/KF1.png   marketing/campaigns/peshta/cards/KF1b.png
     marketing/campaigns/peshta/cards/KF3.png   marketing/campaigns/peshta/cards/KF4.png
   §7.5(d) reads `cards/KF2.png` off disk; without this step the cold open has no input.
```

> ⚠ **UNVERIFIED.** I confirmed `jobs_wait`, `job_status`, `job_display` and `show_generation_by_ids` exist in the catalog, but I did not run them and do not know the exact response shape or the asset-URL field name. **Read the first real result and adapt steps 3–4.** This is the one place in the plan where the operator is flying on a tool contract I could not exercise read-only.

**Also unestablished, and it makes Phase D unschedulable until the first job lands:**
- How long a `wan3_0` 1080p 6 s job takes. Time SH-02 and write the number here.
- Whether the four shots can be submitted in parallel. `generate_video_batch` exists for 2–12 independent requests; whether it is cheaper or faster is unknown.
- **Whether credits are consumed by a failed or unusable job.** The reroll budget in §4.4 is a *quality* budget. If a job can fail and still bill, add a separate failure reserve before approving Phase C.

### 6.7 Verify every clip the moment it lands

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,duration,nb_frames \
  -of default=noprint_wrappers=1 marketing/campaigns/peshta/raw/SH-02.mp4
```

**`-select_streams v:0` is required here too** — without it the probe prints the video stream's values followed by the audio stream's, and a downstream `key=value` parse keeps the audio row (see G1, §8).

**No model in the catalog declares its output fps.** Run this on the *first* clip to pin `wan3_0`'s real rate before assuming anything about the conform.

**SH-02 carries an explicit duration floor, and it is the one clip that does.** §7.5(c) cuts `s09` at `-ss 5.00 -t 1.000`, which consumes SH-02's **final second with zero tail margin**. No model in the catalog declares its output duration any more than its fps, so **`duration` must measure ≥ 6.00 s or `s09` must be re-cut from the *measured* end, not from the hardcoded 5.00 offset.** A 5.98 s delivery yields a 49-frame `s09` and a 749-frame master — caught only at G1, after all 49 shot credits are spent.

---

## 7. Step 4 — Assembly

### 7.1 The blocker you must handle before writing a single overlay

**This ffmpeg cannot burn text.** Re-verified filter by filter this session:

```bash
for f in drawtext subtitles ass zscale loudnorm minterpolate overlay concat zoompan highpass volume; do
  printf "%-14s " "$f"
  ffmpeg -hide_banner -h filter=$f 2>&1 | grep -q "Unknown filter" && echo MISSING || echo present
done
# drawtext MISSING · subtitles MISSING · ass MISSING · zscale MISSING
# loudnorm present · minterpolate present · overlay present · concat present
# zoompan present · highpass present · volume present
```

`ffmpeg 9.0.1` at `/opt/homebrew/bin` is the slim Homebrew formula — no freetype, libass, fontconfig, harfbuzz or zimg. **Any instruction anywhere in the corpus that says "burn the text in with drawtext" is unexecutable here, and it fails outright rather than degrading.**

I also re-confirmed timeline support, which matters below: **`volume` and `highpass` are timeline-enabled; `zoompan` is NOT.**

**Solution, proven not theoretical: PIL owns typography, ffmpeg only composites finished RGBA PNGs.** PIL 11.3.0 / freetype 2.13.3 exists in `.venv` (the system python has nothing). This is strictly better than `drawtext`, because it lets the card renderer **assert the safe zone and the minimum glyph height at render time**.

*(If you insist on drawtext: `brew install ffmpeg-full` is keg-only with 47 dependencies and will not shadow the `ffmpeg` on PATH that the product's own `ensure_ffmpeg_available` startup check probes. It is unnecessary.)*

### 7.2 Fonts, the Uzbek marks, and the emoji blocker

**Fonts.** Neither Montserrat ExtraBold nor Bebas Neue is installed. `~/Library/Fonts` is empty; `/Library/Fonts` holds exactly one file, `Arial Unicode.ttf`; fontconfig is not installed at all, so there is no `fc-list`.

Arial Unicode **does** carry the Uzbek marks — measured this session:

| Codepoint | bbox | mask | Verdict |
|---|---|---|---|
| `A` (control) | (−1, 23, 43, 69) | 44×46 | real glyph |
| **U+02BB** `ʻ` | (0, 23, 14, 69) | **14×46** | **real, distinct glyph** |
| **U+02BC** `ʼ` | (0, 23, 14, 69) | **14×46** | **real, distinct glyph** |
| **U+00A0** (NBSP) | (0, 69, 18, 69) | 18×0 | **real no-break space, 18 px advance** |
| **U+1F525** 🔥 | (0, 21, 64, 69) | **64×48** | **TOFU** |
| **U+1F449** 👉 | (0, 21, 64, 69) | **64×48** | **TOFU — identical mask to 🔥** |

Install the brand faces (untested — no network writes were attempted):

```bash
mkdir -p ~/Library/Fonts && \
curl -fsSL -o /tmp/montserrat.zip 'https://fonts.google.com/download?family=Montserrat' && \
unzip -j -o /tmp/montserrat.zip 'static/Montserrat-ExtraBold.ttf' -d ~/Library/Fonts && \
cd /Users/ai/Desktop/work/projects/hbd-bot && .venv/bin/python -c "
from PIL import ImageFont
f = ImageFont.truetype('$HOME/Library/Fonts/Montserrat-ExtraBold.ttf', 64)
for c in ['\u02bb','\u02bc','\u00a0']: print(hex(ord(c)), f.getbbox(c), f.getmask(c).size)"
```

**Verify U+02BB, U+02BC and U+00A0 coverage on whatever you install — and then re-measure every card line's width against the §7.3 pill bound.** Bebas Neue is uppercase-Latin and may lack the marks; if so, use Montserrat for any string containing `oʻ`, `gʻ` or `ʼ`, and fall back to Arial Unicode rather than shipping tofu.

> **Coverage is not the whole check.** Every width in §7.3 and §7.4 ruling 5 was measured on **Arial Unicode**, and **Montserrat ExtraBold is materially wider**. c1 line 2 (759 px) and c3 (730 px) already sit within ~40 px and ~70 px of the 800 px bound on the narrower face, so **they are likely to overflow on the face this section tells you to install** — and the §7.3 render-time assert will refuse to write them. Re-run the measurement loop over the full §7.4 string set on the installed face **before** Phase A step 10, and re-derive the line breaks (and, for c1/c3 only, the type sizes) from that measurement rather than from the Arial Unicode figures printed here.

**EMOJI — a hard blocker.** Both drafts put 🔥 on the hero card and 👉 on the CTA card. **With the only installed font those render as empty rectangles**, and the safe-zone asserts would pass happily. Apple Color Emoji is installed but PIL loads it only at specific sizes — measured this session: **64 OK, 96 OK, 137 `OSError: invalid pixel size`, 160 OK.**

**Ruling: draw the flame and the chevron as PIL vector shapes.** They are two simple marks and it removes a whole class of font dependency. If colour emoji are genuinely wanted:

```python
emoji = ImageFont.truetype('/System/Library/Fonts/Apple Color Emoji.ttc', 160)  # 160 ONLY
tile = Image.new('RGBA', (220, 220), (0, 0, 0, 0))
ImageDraw.Draw(tile).text((10, 10), '\U0001F525', font=emoji, embedded_color=True)
tile = tile.resize((96, 96), Image.LANCZOS)   # scale AFTER drawing, never draw at 96
card.alpha_composite(tile, (x, y))
```

### 7.3 Safe-zone geometry — the asymmetry trap

`03 §1.4` is authoritative (the looser bounds in `01 §7.4` are superseded — they are 70 px slacker top and bottom and abandon the right-flank margin entirely):

```
TOP DANGER        Y    0 –  220    zero text, zero marks, zero faces
UPPER ACTION      Y  220 –  480    Frame-0 banner, floating bot badge
CORE SAFE BOX     X   40 –  940    Y 220 – 1500
FOCAL STAGING     X  120 –  940    Y 480 – 1350, eye-line Y 680
RIGHT DANGER      X  940 – 1080    (140 px clear margin)
BOTTOM DANGER     Y 1500 – 1920
```

**The trap: the safe box is asymmetric about the canvas centre (540).** A centre-aligned pill is bounded by the *nearer* edge:

```
max half-width = min(540 − 40, 940 − 540) = 400
max centred pill width = 800 px, NOT the 900 px the safe-box width implies
```

**800 px bounds the *pill*, not the text.** The text budget is `800 − 2 × pill padding`, and on this face that leaves almost nothing: measured at the specified sizes, c1 line 2 (`SOVGʻA ESA YOʻQ!`, 84 pt) is **759 px** and c3 (`BAYRAM-BOTDA!`, 88 pt) is **730 px** — 41 px and 70 px of total horizontal slack, i.e. **under 21 px and 35 px of padding per side**. Budget the padding first and measure the line against what is left; do not measure the line against 800 and then add a pill around it.

Fitting a centred pill to 900 px overflows the right danger zone. This is a real defect that fires in practice (a pill landed at x=1006 during investigation), and it is the same class as `verify_production_specs.py`'s own FINDING 1 (X=1000 penetrating the right zone by 60 px). **The card renderer hard-asserts both bounds at render time**, so a bad card fails before a single pixel is encoded.

**Three corpus contradictions, settled here:**

- **Type size.** `01 §6.3` says 110–120 pt where `03 §5` says 72–84 pt for the same overlays, and the corpus never defines a pt-to-px mapping. **Ruling: 1 pt = 1 px on the 1080×1920 canvas** (the CapCut/After Effects convention the blueprint implicitly assumes), and `03 §5`'s per-shot sizes govern.
- **The green.** `01 §6.3` uses `#00E676`; `03 §5` Shot 6 and `03 §4.1` Sticker 2 both use `#00C853`. **Ruling: `#00C853`**, two votes to one, and it is the one attached to an actual sticker spec.
- **Minimum glyph height.** Neither draft added the assert that would have caught the discarded build's ~40 px glyphs against a mandated 78–88 pt. **`make_cards.py` measures the rendered mask height and refuses to write a card that falls below the floor.** Gate G5b re-checks it.

  > **The floor is two numbers, not one, because cap-height is not type size.** An earlier version of this ruling asserted "cap-height ≥ 78 px", which is **unreachable under this section's own 1 pt = 1 px ruling** and would have refused to write every card in §7.4. Measured on the only installed face (Arial Unicode, `.venv` PIL 11.3.0, `font.getbbox('A')[3]-[1]`), cap-height ÷ font-size is **0.708–0.716**: 76 pt → **54 px**, 80 pt → **57 px**, 84 pt → **60 px**, 88 pt → **63 px**. A 78 px cap-height needs a ~109 pt face. The old assert conflated "78–88 pt type size" with "78 px cap-height".
  >
  > **Ruling: `make_cards.py` asserts rendered em size ≥ 76 px AND measured cap-height ≥ 53 px** (0.70 × the smallest specified size, so it holds on a face with a shorter cap than Arial Unicode's). Re-measure the ratio on whatever face you install — Montserrat ExtraBold's cap ratio is not Arial Unicode's, and the em-size half of the assert is the one that carries the spec.
  >
  > **The assert applies to the six narrative cards c1–c6 and c8. `c7` (the persistent 48 pt handle pill) and `c9` (the full-frame flash) are exempt by name**, carried as an explicit exemption list in `make_cards.py`'s `SPEC` dict. c7 is deliberately small — it is a persistent corner pill, not a read-in-1.2-seconds card, and at 48 pt it renders a 34 px cap. It is also the single most load-bearing element in the §2.5 funnel table (605 frames), so an assert that refuses to write it takes the handle out of the film.

### 7.4 The nine cards

Rendered by `marketing/campaigns/peshta/make_cards.py`, which asserts the safe zone *and* the glyph height as it goes, with `c7` and `c9` in an explicit exemption list (§7.3). **It also writes `marketing/campaigns/peshta/cards/strings.txt` — one line per card id plus its exact rendered text, UTF-8 — which is the artefact gate G14 audits.** Nothing else in the plan produces that file, and G14 dies on `FileNotFoundError` without it.

**Every Uzbek string is constructed from explicit escapes** so nothing depends on this file's encoding round-tripping. Write them as escapes, not as literals — an invisible literal U+00A0 in source is indistinguishable from a plain space on inspection, which is exactly the failure ruling 4 below exists to prevent:

```python
TC   = "\u02bb"   # ʻ  MODIFIER LETTER TURNED COMMA
NBSP = "\u00a0"   #    NO-BREAK SPACE — the price MUST use this, see below
```

| Card | Window (frames / s) | Text | Spec | Status |
|---|---|---|---|---|
| **c1** | 0–126 · 0.000–2.540 | `SOAT 23:55.`<br>`SOVGʻA ESA YOʻQ!` | 84 pt, `#FFE600` on `#121212` @90%, pill centre **Y 380**, TWO short lines | **corpus-verbatim** (03 §5 Shot 1, line 492) |
| **c2** | 80–126 · 1.600–2.540 | `TOʻXTA…` | 84 pt, `#FFE600`, 3-frame alpha pulse, Y 560 | corpus (02 §2.4 r2), apostrophe corrected |
| **c3** | 127–217 · 2.540–4.360 | `BAYRAM-BOTDA!` + **PIL vector flame** | 88 pt, `#121212` on a `#FFE600` card, Y 420 | corpus (02 §2.4 r3); emoji → vector |
| **c4** | 218–399 · 4.360–8.000 | `UNING ISMIGA`<br>`ATALGAN QOʻSHIQ!` | 80 pt, karaoke gold `#FFD700` with black stroke, Y 1200, **TWO lines — the break is specified, not left to the renderer** | **[ADAPTED]** — see below |
| **c5** | 400–524 · 8.000–10.500 | `SOʻZLARINI OʻQISH`<br>`BEPUL!` | 76 pt white on a `#00C853` badge, Y 880, **TWO lines — the break is specified** | **[ADAPTED]** from 03:419 |
| **c6** | 575–749 · 11.500–15.000 | `HOZIROQ KIRING:`<br>**PIL vector chevron** + `@bayram_uzbot` | 80 pt `#FFE600` / white, block centred **Y 1050** | corpus (02 §2.4 r6); emoji → vector; **moved up** |
| **c7** | 145–749 · 2.900–15.000 | `@bayram_uzbot` pill, cyan `#0088CC`, white paper-plane vector | 48 pt, right-aligned to X 940, Y 250–330. **Exempt from the G5b glyph floor by name** (~34 px cap at 48 pt) — it is a persistent pill, not a narrative card | corpus (03 §4.1 Sticker 1), re-timed |
| **c8** | 420–749 · 8.400–15.000 | `ATIGI 15` + **U+00A0** + `000 SOʻM`<br>`Bitta kofe narxi` | 76 pt white on `#00C853` badge, Y 1300 | corpus (03 §4.1 Sticker 2) |
| **c9** | 4.335–4.375, 6.155–6.195 and **13.215–13.255** | full-frame white, 2 frames each | the three punch-in flashes. **Exempt from G5a and G5b by name** — its alpha is the whole 1080×1920 canvas on purpose | — |

**Five copy rulings, all of which need sign-off (gate G13) and four of which correct a real defect:**

1. **The hook is swapped to the master script's own Shot 1 card.** Variant D's row-1 text — `SOVGʻAGA NIMADIR TOPISH KERAKMI?` — is 31 characters and 4 words, which wraps to 2–3 lines at 84 pt inside the 800 px bound. A muted viewer cannot parse a novel image *and* 31 characters of Uzbek in 1.2 s. `03_production_blueprint.md:492` already contains a shorter, front-loaded, U+02BB-correct alternative for exactly this beat: **`SOAT 23:55. SOVGʻA ESA YOʻQ!`**. It is sourced, not invented. It also now **persists 0.000–2.540 s**, matching `03 §1.2`'s own Frame-0 persistence spec of "fixed 0.00 s to 2.45 s" — both drafts pulled it at 1.600 s, 0.85 s early.
2. **`ISMINGIZ BILAN MAXSUS QOʻSHIQ!` names the wrong person and is replaced.** *Ismingiz* is second-person-polite possessive — *YOUR* name — but the entire campaign premise is gifting a song to someone else, the blueprint's own proposed trend greeting asks *"Kimning ismiga qoʻshiq yozamiz?"* (`03:440` — a proposal, not shipped product copy; the shipped key is `wizard.name.prompt`, `uz_latn.py:290`), and the shot this card sits over is the **recipient's** phone. The replacement is adapted from `03:418`'s own *"uning ismiga atalgan shaxsiy qoʻshiq"*: **`UNING ISMIGA ATALGAN QOʻSHIQ!`**. There is a second, compounding defect the reviewer must settle: the sung line is *"Isming aytib"* (informal singular) while the card was *"Ismingiz"* (polite) — the same clause in two registers, seconds apart.
3. **The speed claim is removed entirely, not renumbered.** Variant D promises `10 SONIYADA`; both drafts "corrected" it to `1 DAQIQADA`. **Both numbers are overclaims.** The bot's own Uzbek at `src/bayram/bot/locales/uz_latn.py:311` reads *"✍️ {name} uchun soʻzlarni yozayapman… bu bir daqiqagacha oladi"* — one minute is what the **lyric write alone** takes, and that step happens *before* the payment gate (`src/bayram/bot/handlers/lyrics.py`: *"It is also the first vendor spend in the product, and it happens BEFORE the payment gate"*). `config.py:425` sets `music_timeout_s = 420.0` — a seven-minute ceiling on the compose call alone. **The product deliberately promises no song turnaround anywhere**: the only render-wait copy in `uz_latn.py` is *"Tayyor boʻlishi bilan shu yerga…"* — "as soon as it's ready, here" — with no number. Burning a hard time promise into a viral video that the product itself refuses to make is a refund generator. **It is replaced by the one claim that is both true and verifiable in code: the free lyric preview.** `03:419` already has the Uzbek — *"soʻzlarini oʻqish esa MUTLAQO BEPUL!"* — and a risk-free trial is a stronger conversion lever than a speed claim. The speed claim moves to the pinned comment, where it costs nothing and cannot be litigated.
4. **The price uses U+00A0, not a plain space.** `src/bayram/bot/pricing.py:35-41` spells out why, and I read it this session: *"A price is the one string on the checkout screen that must not be split across a line: '49' at the end of one line and '000 soʻm' at the start of the next reads as a different, much cheaper product… a plain space was rejected because it is exactly the character that wraps."* Both drafts used a plain space in a renderer that auto-shrinks and wraps to fit the safe zone. A wrap between `15` and `000` turns a 15 000 soʻm promo into a 15 soʻm promo. Construct it as `"ATIGI 15" + NBSP + "000 SO" + TC + "M"`.
5. **`c4` and `c5` are two-line cards, and the break is written into the spec — because as single lines they are unrenderable under this plan's own asserts.** Measured on the only installed face (Arial Unicode, `.venv` PIL 11.3.0, `font.getbbox`): `UNING ISMIGA ATALGAN QOʻSHIQ!` at 80 pt is **1335 px** and `SOʻZLARINI OʻQISH BEPUL!` at 76 pt is **993 px** — both over §7.3's 800 px centred-pill bound, **before any pill padding**. Auto-shrinking to fit needs **48 pt** and **61 pt** respectively, and both sit under G5b's ≥ 76 px rendered-em floor. **The two asserts are mutually unsatisfiable for these two strings**, so `make_cards.py` as specified would refuse to write them and Phase A step 10 would dead-end. Ruling 1 rejected a 31-character string for exactly this reason and then ruling 2 introduced c4 at 29 characters without re-applying the test. **Measured fits at the specified sizes:** c4 → `UNING ISMIGA` (560 px) / `ATALGAN QOʻSHIQ!` (755 px) at 80 pt; c5 → `SOʻZLARINI OʻQISH` (701 px) / `BEPUL!` (271 px) at 76 pt. **The renderer must not be trusted to pick the break** — a greedy wrap on c5 yields `SOʻZLARINI` / `OʻQISH BEPUL!`, which splits the claim across the wrong clause.

**Also: `c6` was moved up.** Both drafts centred the CTA block at Y 1350. At 1 pt = 1 px, a three-line 80 pt block plus pill padding is 320–360 px tall, so centring at 1350 spans roughly Y 1170–1530 — **breaching the bottom danger zone by up to 30 px, i.e. failing the plan's own G5 gate.** Y 1350–1500 is also exactly where Reels' caption block intrudes on tall handsets. Centred at **Y 1050** a two-line block spans 940–1160, with clear margin both ways, and the price badge sits below it at Y 1300.

### 7.4a Phase A correction — measured on the installed face, 2026-09-18

Everything in 7.3/7.4 above was measured on **Arial Unicode**. Phase A installed
**Montserrat ExtraBold** and re-measured. Four facts the sections above get wrong, all
verified by running `marketing/campaigns/peshta/make_cards.py`:

1. **The 7.2 install command does not work.** `https://fonts.google.com/download?family=Montserrat`
   now returns an **HTML page**, not a zip (193 KB of `text/html`), so the `unzip` step fails.
   `google/fonts` no longer ships static instances either — `ofl/montserrat/` holds only
   `Montserrat[wght].ttf` and its italic. The static face was installed from the project
   upstream, `JulietaUla/Montserrat/fonts/ttf/Montserrat-ExtraBold.ttf`, to
   `~/Library/Fonts/Montserrat-ExtraBold.ttf`. (The variable font also works — PIL reports the
   `wght` axis and `set_variation_by_name("ExtraBold")` matches the static face to within 1 px —
   but the static file needs no variation call from every consumer.)
2. **Coverage confirmed, emoji blocker confirmed again.** On Montserrat ExtraBold at 64 px:
   U+02BB mask 18x47, U+02BC mask 19x48 (distinct real glyphs, not .notdef), U+00A0 a real
   19 px zero-ink advance. U+1F525 and U+1F449 are **absent** — `make_cards.py`'s coverage
   probe refuses them by name, so 7.2's vector-mark ruling stands on this face too.
3. **Cap ratio is 0.690–0.708, below Arial Unicode's 0.708–0.716.** At the 76 pt floor the cap
   measures **exactly 53 px**. 7.3's `cap >= 53` floor therefore holds, with zero slack — do not
   raise it.
4. **Montserrat ExtraBold is wider than 7.3/7.4 ruling 5 assumed, and it breaks two rulings.**
   Measured widths (Arial Unicode figure in brackets): c1 L2 **817** [759], c3 **816** [730],
   c4 L2 `ATALGAN QOʻSHIQ!` **834** [755], c5 L1 **770** [701]. Consequences:
   - **c1 84 pt -> 79 pt**, **c3 88 pt -> 83 pt** — the re-derivation 7.2 explicitly authorises.
     Both still clear the 76 px em floor (caps 56 and 58 px).
   - **c4's two-line break is unrenderable on this face.** `ATALGAN QOʻSHIQ!` is 834 px at
     80 pt and 792 px at the 76 pt floor; with its 6 px black stroke both breach the 800 px
     centred bound, so the two asserts are mutually unsatisfiable again — the exact failure
     ruling 5 exists to prevent, one face later. **c4 is now THREE lines at the specified 80 pt:**
     `UNING ISMIGA` (611 px) / `ATALGAN` (417 px) / `QOʻSHIQ!` (394 px). The copy is unchanged;
     only the break moved. **G13 question 2 must now review a three-line break.**
   - **c5 cannot shrink** (already at the floor), so its badge is a full 800 px band with the
     text inset 15 px. c1 and c3's bands are likewise full-width at 14–15 px inset.
     `make_cards.py` prints every such clamp rather than applying it silently.

### 7.5 The ffmpeg chain, end to end

Every command below runs on this machine as written. Paths assume `cd /Users/ai/Desktop/work/projects/hbd-bot`.

**(a) Cut the audio window from the 30 s bed**

```bash
ffmpeg -hide_banner -nostdin -y -v error \
  -ss <CUE> -i marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 \
  -t 15.0313 \
  -af "afade=t=in:st=0:d=0.05,afade=t=out:st=14.971:d=0.060" \
  -ar 48000 -ac 2 -c:a pcm_s16le \
  marketing/campaigns/peshta/audio/bed_15s.wav
```

> **`-ss` goes BEFORE `-i`, and this was a real bug, proved this session.** With `-ss` after the input,
> ffmpeg seeks on the *output* and the filter graph still sees the source's timestamps — so `afade=t=out:st=14.971`
> fires relative to the 30 s bed, not to the 15 s cut. Reproduced at `CUE=9.130`: the command exits 0, writes a
> file of exactly the right duration, and that file is **silent from ~5.9 s to the end** (`max_volume −91.0 dB`
> at 6.2 s, 8.0 s and 12.0 s). With `-ss` before `-i` the same probe points read −1.6, −1.6 and −0.6 dB. The bug
> is invisible at `CUE=0`, which is why the colour-bars rehearsal did not catch it — the rehearsal cut from the
> top of the bed. Input seeking is also accurate here: ffmpeg decodes to the exact sample, it does not snap to a
> keyframe on audio.
>
> The `cut ()` helper in (c) still takes `-ss` after `-i`, and that is fine **only** because it applies no
> time-based filter. If a fade, `enable=` clause or any other timeline expression is ever added there, move its
> `-ss` too.

`<CUE>` comes from Step 0.5, not from guesswork. **The fade-out is 60 ms, not 350 ms** — a long fade is the strongest possible "it's over" signal and it kills the loop (§2.6). Stay uncompressed between passes so the chain never stacks lossy generations; that is the rule `src/bayram/audio/constants.py` already encodes as `INTERMEDIATE_CODEC`.

**(b) Author the 0.94 s sub-bass vacuum** — the step the whole hook depends on, and the one the composition plan cannot express

```bash
ffmpeg -hide_banner -nostdin -y -v error -i marketing/campaigns/peshta/audio/bed_15s.wav \
  -af "highpass=f=200:enable='between(t,1.60,2.53)',volume=0.06:enable='between(t,1.60,2.53)'" \
  -ar 48000 -ac 2 -c:a pcm_s16le marketing/campaigns/peshta/audio/bed_vacuum.wav
```

> **The upper bound is `2.53`, not `2.54`, for the same reason §7.5(h)'s card windows are** — and here it is the slam that pays. `between()` is inclusive, and on an audio filter the `enable` decision is taken **per sample block**, so the window bleeds past its upper bound by the remainder of the block. Measured this session: `volume=0.001:enable='between(t,1.0,2.0)'` on a 48 kHz sine leaves the signal at **−78.3 dB through 2.005 s** and restores it only at 2.005–2.010 s — about **5 ms past the stated end**. §2.4 puts the 808 slam at **2.540 with a `< 5 ms` attack**, so the `2.54` form high-passes and ducks by 24 dB **exactly the transient the whole hook is built on**. Ending the vacuum at 2.53 loses 10 ms off a 0.94 s dropout, which is inaudible, and buys clean separation. *(The 5 ms figure is this build's block size, not a documented contract — treat it as a floor, not a constant.)*

I re-verified this session that both filters are timeline-enabled on this build (`-h filter=volume` and `-h filter=highpass` both report timeline support). The highpass plus a −24 dB duck is the musical version: the sub disappears but the room does not, so the vacuum reads as tension rather than as a dropped file. A hard `volume=0` gate is the alternative if the softer version does not bite. Both are post-production on **our own** audio — no vendor call, no spend.

**(c) Conform every shot to the grid**

```bash
cut () {  # cut <src> <in> <dur> <zoomheight> <out>
  ffmpeg -hide_banner -nostdin -y -v error -i "$1" -ss "$2" -t "$3" -an \
    -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=-2:$4,crop=1080:1920,fps=50,setsar=1,format=yuv420p" \
    -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
    -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 "$5"
}
# segment            src                       in     dur    zoom-h   out
cut marketing/campaigns/peshta/raw/SH-01.mp4  0.00  1.360  1920  marketing/campaigns/peshta/build/s02.mp4   #  68f
cut marketing/campaigns/peshta/raw/SH-02.mp4  0.00  1.820  1920  marketing/campaigns/peshta/build/s04.mp4   #  91f
cut marketing/campaigns/peshta/raw/SH-02.mp4  1.82  1.820  2036  marketing/campaigns/peshta/build/s05.mp4   #  91f  1.06x punch-in
cut marketing/campaigns/peshta/raw/SH-02.mp4  3.64  1.820  2152  marketing/campaigns/peshta/build/s06.mp4   #  91f  1.12x punch-in
cut marketing/campaigns/peshta/raw/SH-03.mp4  0.00  1.000  1920  marketing/campaigns/peshta/build/s07.mp4   #  50f
cut marketing/campaigns/peshta/demo/demo.mp4  0.00  1.500  1920  marketing/campaigns/peshta/build/s08.mp4   #  75f  REAL screen recording
cut marketing/campaigns/peshta/raw/SH-02.mp4  5.00  1.000  1920  marketing/campaigns/peshta/build/s09.mp4   #  50f  reaction window
cut marketing/campaigns/peshta/raw/SH-04.mp4  0.00  1.740  1920  marketing/campaigns/peshta/build/s10.mp4   #  87f
cut marketing/campaigns/peshta/raw/SH-04.mp4  1.74  1.760  2036  marketing/campaigns/peshta/build/s11.mp4   #  88f  1.06x punch-in
```

`force_original_aspect_ratio=increase` + `crop` survives a source that is not exactly 9:16. **`setsar=1` is required** or `concat` rejects the segment. The second `scale`/`crop` pair is the punch-in step: 1920 → 2036 is 1.06×, 1920 → 2152 is 1.12×. **Combined with the 2-frame white flash (card c9) at each junction, this is what turns one continuous 6 s generation into three cuts** — satisfying `03 §1.1`'s "jump-cuts every 1.5 s – 2.0 s" rule for free.

*If the punch-ins read as fake, the upgrade is three separate 2 s `wan3_0` generations (2+2+2 = 6 s = the same 21 credits) with genuinely different framings — at the cost of three separate identity risks and three separate jobs.*

**If clips arrive at 24 fps** (the one real Higgsfield clip on disk did), swap `fps=50` for `minterpolate=fps=50:mi_mode=mci:mc_mode=aobmc:vsbmc=1`. Measured at ~3.7× realtime and effectively single-threaded, so budget roughly 60 s for the whole film. Only worth it if judder is visible; plain frame duplication took 0.36 s for 5 s.

**(d) The cold open — snap-zoom on the hero still, zero credits**

```bash
ffmpeg -hide_banner -nostdin -y -v error -loop 1 -i marketing/campaigns/peshta/cards/KF2.png \
  -t 0.240 -vf "scale=1210:2152,zoompan=z='max(1.12-0.0109*on,1.00)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=12:fps=50:s=1080x1920,setsar=1,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 marketing/campaigns/peshta/build/s01.mp4
```

> **`zoompan`'s own `fps` option defaults to 25 and `zoompan` is NOT timeline-enabled** — I re-confirmed both this session. Putting `fps=50` *inside* the filter (rather than chaining `fps=50` after it) is what makes the 12 emitted frames real zoom steps instead of duplicated 25 fps frames travelling half the intended distance. Both drafts got this wrong in the freeze beat; it is fixed here and in (e).
>
> **`x` and `y` are mandatory, and their default is the bug.** `ffmpeg -h filter=zoompan` on this build reports `x` and `y` defaulting to `"0"` — meaning the zoom is anchored to the **top-left corner**, not the centre. Omitted, the 1.12 → 1.00 cold open and the 1.00 → 1.20 vacuum push crop into the corner of the frame instead of pushing in on the dog's face. It **fails silently**: the commands run, exit 0 and emit exactly the right frame counts, so nothing downstream catches it and no gate in §8 is looking at framing. Hence `x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'` in both commands. Eyeball the first frame and the last frame of `s01.mp4` and `s03.mp4` against each other before concat — if the subject slides up and left, the anchor is missing.

**(e) The vacuum snap-zoom — NOT a static freeze**

```bash
# 1. Extract SH-01's LAST frame. -sseof is the only seek that works here.
rm -f marketing/campaigns/peshta/build/freeze.png
ffmpeg -hide_banner -nostdin -y -v error -sseof -0.04 \
  -i marketing/campaigns/peshta/build/s02.mp4 -frames:v 1 marketing/campaigns/peshta/build/freeze.png
test -s marketing/campaigns/peshta/build/freeze.png || { echo "FATAL: no freeze frame written"; exit 1; }

# 2. Push it 1.00 -> 1.20 across 47 frames.
ffmpeg -hide_banner -nostdin -y -v error -loop 1 -i marketing/campaigns/peshta/build/freeze.png \
  -t 0.940 -vf "scale=1296:2304,zoompan=z='min(1.00+0.00426*on,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=47:fps=50:s=1080x1920,setsar=1,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 marketing/campaigns/peshta/build/s03.mp4
```

> **The `-ss` freeze command is broken and I proved it this session.** Against a 1.600 s / 80-frame / 50 fps clip, `ffmpeg -ss 1.5999 -i c01.mp4 -frames:v 1 freeze.png` **exits 0 and writes no file**. So does the output-seek variant. Only `-sseof -0.04` worked (10 385-byte PNG). Because ffmpeg exits 0, the next command either dies on a missing input or — far worse — silently reuses a **stale** `freeze.png` from a previous run. That is the exact stale-frame failure documented in §8, and it would silently drop 47 frames from the master, caught only at G1, after all 49 credits of shot generation are spent. **Hence the `rm -f` before and the `test -s` after. Apply that pattern to every frame extraction in this plan.**

> **And the freeze is not static.** `03 §1.1` sizes the muted audience at 50–62% of impressions. For all of them the "SILENCE VACUUM" does not exist — they would get 47 frames of a motionless picture of a sad dog, landing exactly in the second swipe-decision window. The 1.00 → 1.20 push is what they see instead. The audio vacuum is untouched for the sound-on viewer.

**(f) Concat**

```bash
printf "file '%s'\n" \
  "$PWD/promo_peshta/build/s01.mp4" "$PWD/promo_peshta/build/s02.mp4" \
  "$PWD/promo_peshta/build/s03.mp4" "$PWD/promo_peshta/build/s04.mp4" \
  "$PWD/promo_peshta/build/s05.mp4" "$PWD/promo_peshta/build/s06.mp4" \
  "$PWD/promo_peshta/build/s07.mp4" "$PWD/promo_peshta/build/s08.mp4" \
  "$PWD/promo_peshta/build/s09.mp4" "$PWD/promo_peshta/build/s10.mp4" \
  "$PWD/promo_peshta/build/s11.mp4" > /tmp/concat.txt

ffmpeg -hide_banner -nostdin -y -v error -f concat -safe 0 -i /tmp/concat.txt \
  -c copy marketing/campaigns/peshta/build/silent_cut.mp4

ffprobe -v error -show_entries stream=nb_frames -show_entries format=duration \
  -of default=noprint_wrappers=1 marketing/campaigns/peshta/build/silent_cut.mp4
```

**Expect exactly `nb_frames=750` and `duration=15.000000`.** `-c copy` works only because every segment was encoded with identical codec, fps and SAR in (c)–(e).

**(g) Loudnorm — two passes, mirroring the repo's own chain**

Targets from `src/bayram/config.py:478-480` and `audio/constants.py:52`: `I=-14.0`, `TP=-1.0`, `LRA=11.0`.

```bash
# pass 1 — measure only, write nothing
ffmpeg -hide_banner -nostdin -i marketing/campaigns/peshta/audio/bed_vacuum.wav \
  -af "loudnorm=I=-14.000:TP=-1.500:LRA=11.000:print_format=json" \
  -vn -f null - 2>&1 | sed -n '/^{/,/^}/p'

# pass 2 — apply the measured correction LINEARLY. NO -v error: see below.
ffmpeg -hide_banner -nostdin -y -i marketing/campaigns/peshta/audio/bed_vacuum.wav \
  -af "loudnorm=I=-14.000:TP=-1.500:LRA=11.000:measured_I=<input_i>:measured_TP=<input_tp>:measured_LRA=<input_lra>:measured_thresh=<input_thresh>:offset=<target_offset>:linear=true:print_format=summary" \
  -vn -map_metadata -1 -ar 48000 -ac 2 -c:a pcm_s16le marketing/campaigns/peshta/audio/bed_norm.wav
```

`linear=true` with the `measured_*` values from pass 1 is what makes this a single precise gain change; without them it silently degrades to single-pass dynamic squashing, which will flatten the 808.

> **Pass 2 must NOT carry `-v error`, and it has a pass condition.** `loudnorm` prints its `print_format=summary` block at `AV_LOG_INFO`, so `-v error` swallows it entirely — verified this session: the command with `-v error` prints **nothing at all**, the same command without it prints the summary. That suppressed block is the **only** way to detect the exact failure the paragraph above warns about. **Pass condition: the summary must read `Normalization Type:   Linear`.** `Dynamic` means the `measured_*` values did not take and the 808 has been squashed — re-run pass 1 and re-transcribe them. This is the identical defect already diagnosed and fixed for `volumedetect` in §3.8 and G4 (*"Same correction applies to G4"*); pass 2 was the one remaining info-level command in the chain that had not been swept.

> **Target `TP = −1.5`, not `−1.0`, in BOTH passes.** AAC encoding *raises* true peak: a normalised wav measuring −2.0 dBTP came out at −1.4 dBTP after the final mux, a 0.6 dB rise. Normalising to −1.0 and then encoding lands around −0.4 dBTP — **over the ceiling, and the plan's own G3 gate would fail on a correctly built master.** Buy the headroom here. The gate stays at ≤ −1.0 dBTP on the final mux.

**(h) Final composite, mux and export**

```bash
ffmpeg -hide_banner -nostdin -y -v error \
  -i marketing/campaigns/peshta/build/silent_cut.mp4 \
  -loop 1 -i marketing/campaigns/peshta/cards/c1.png -loop 1 -i marketing/campaigns/peshta/cards/c2.png -loop 1 -i marketing/campaigns/peshta/cards/c3.png \
  -loop 1 -i marketing/campaigns/peshta/cards/c4.png -loop 1 -i marketing/campaigns/peshta/cards/c5.png -loop 1 -i marketing/campaigns/peshta/cards/c6.png \
  -loop 1 -i marketing/campaigns/peshta/cards/c7.png -loop 1 -i marketing/campaigns/peshta/cards/c8.png -loop 1 -i marketing/campaigns/peshta/cards/c9.png \
  -i marketing/campaigns/peshta/audio/bed_norm.wav \
  -filter_complex "\
[0:v][1:v]overlay=0:0:enable='between(t,0.000,2.530)'[v1];\
[v1][2:v]overlay=0:0:enable='between(t,1.600,2.530)'[v2];\
[v2][3:v]overlay=0:0:enable='between(t,2.540,4.350)'[v3];\
[v3][4:v]overlay=0:0:enable='between(t,4.360,7.990)'[v4];\
[v4][5:v]overlay=0:0:enable='between(t,8.000,10.490)'[v5];\
[v5][6:v]overlay=0:0:enable='between(t,11.500,15.000)'[v6];\
[v6][7:v]overlay=0:0:enable='between(t,2.900,15.000)'[v7];\
[v7][8:v]overlay=0:0:enable='between(t,8.400,15.000)'[v8];\
[v8][9:v]overlay=0:0:enable='between(t,4.335,4.375)+between(t,6.155,6.195)+between(t,13.215,13.255)',format=yuv420p[vout]" \
  -map "[vout]" -map 10:a \
  -c:v libx264 -preset slow -crf 20 -maxrate 12M -bufsize 24M \
  -profile:v high -level 4.2 -pix_fmt yuv420p \
  -r 50 -g 100 -keyint_min 50 -sc_threshold 0 \
  -c:a aac -b:a 192k -ar 48000 -ac 2 \
  -movflags +faststart -map_metadata -1 -t 15.0 \
  marketing/campaigns/peshta/variant_d_final.mp4
```

**Six traps in that command, each of which bites:**

- **Every interior upper bound is pulled back half a frame (0.01 s at 50 fps), and that is not a rounding wobble.** `between(t,a,b)` in ffmpeg is **inclusive at both ends**, so a window written `between(t,0.000,2.540)` composites c1 on frame 127 (t = 2.540) as well — **one frame past its stated end**. Verified directly this session on a purpose-built 50 fps clip: with `enable='between(t,0.5,1.0)'` the overlay is still present at frame 50 (t = 1.000) and gone only at frame 51. The consequence here is arithmetic, not opinion — frame 127 is t = 2.540 **exactly**, so it falls inside `between(t,0.000,2.540)`; likewise frame 218 inside c3's old window, frame 400 inside c4's, and frame 525 inside c5's. A rehearsal build of the master confirmed it: c1, c2 and the incoming c3 were all present on frame 127. **Frame 127 is the frame §2.6 publishes as the cover**, so the un-amended chain ships a TikTok/Reels grid thumbnail with the despair card `SOAT 23:55. SOVGʻA ESA YOʻQ!` and `TOʻXTA…` stacked on top of `BAYRAM-BOTDA!` — the one frame the plan spends a whole section choosing. The amended bounds make the last enabled frame exactly the one §2.4 names: c1/c2 end at frame 126, c3 at 217, c4 at 399, c5 at 524. **The §7.4 and §2.4 window columns are unchanged and still correct** — they are written as half-open boundaries (c1 `0–126 · 0.000–2.540`, and frame 126 is t = 2.520), which is precisely why the `enable` expression cannot use the boundary value verbatim. `c6`, `c7` and `c8` keep `15.000` because `-t 15.0` truncates there anyway, and the three `c9` flash windows are left alone: `4.335–4.375`, `6.155–6.195` and `13.215–13.255` each cover exactly 2 frames, straddling the junctions at 217/218, 308/309 and 661/662.
- **The bed is input 10, not 9.** Nine card PNGs occupy inputs 1–9. `-map 9:a` produces `Stream map '9:a' matches no streams`. This off-by-one was hit for real during investigation with six cards; it moved when the card count moved.
- **`format=yuv420p` goes after the LAST overlay**, or the RGBA chain poisons the output pixel format.
- **The white-flash overlay uses `between(...)+between(...)+between(...)`** — an ffmpeg expression that evaluates > 0 when any window is true. That is one overlay stage doing all three flashes. **There are three, not two.** §2.4 row 11 puts "SH-04b. Flash cut + 1.06×" at frame 662 (13.240 s) and §7.5(c) cuts `s11` with a 1.06× punch-in there, so the third junction needs its own flash — frames 661–662, window `13.215–13.255`. Without it that junction gets a scale step with no flash and reads as a glitch rather than a cut.
- **`-loop 1` on every card input, and uniform colour tags in (c)/(d)/(e) — the §7.6 rehearsal caught this one silently eating all nine cards.** A single-frame PNG input is exhausted after one frame. That is harmless *only* while the filtergraph is never reinitialised. But `concat -c copy` happily splices segments whose **colour metadata differs** — an ffmpeg-generated segment built from a PNG reports `color_range=unknown, color_space=unknown`, while a segment conformed from a source that carries tagging reports `tv/bt470bg`. At that boundary the decoder signals a format change, ffmpeg **rebuilds the filtergraph**, and every exhausted PNG input has nothing left to feed — so **every overlay silently becomes a no-op for the rest of the film.** Measured in the rehearsal: with a `tv/bt470bg` segment at frame 127, card c8 was present on frames 0–125 (≈141 900 key-colour px) and **completely absent from frame 126 to 749** (0 px). `ffmpeg exits 0`, `nb_frames=750`, `duration=15.000000` — G1, G2, G3, G8 and G17 all stay green. **Only G6 catches it**, and only on the cards whose key colour the footage does not accidentally contain. Two independent fixes, both applied above because either alone leaves a hole: `-loop 1` before each card `-i` makes the overlay inputs inexhaustible (verified: restores c8 to ≈141 800 px at frame 584 across the reinit), and the `-color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709` tagging in (c), (d) and (e) makes every segment identical so no reinit happens at all. *(Tagging the main stream with `setparams` **inside** (h) does **not** work — the reinit happens at the decoder-to-filtergraph link, before any filter runs. Tested: 640 px, still broken.)* **`-loop 1` makes those nine inputs infinite, so the output-side `-t 15.0` is now load-bearing — remove it and the encode never terminates.**
- **`-crf 20` with a maxrate cap, not CRF 18.** CRF 18 produced a 15 MB file for 15 seconds of upscaled material. CRF 20 capped at 12 Mbps is well inside TikTok/Reels limits and loses nothing visible.

### 7.6 Rehearse the whole chain on colour bars, before any credit is spent

Both drafts skipped this, and it costs nothing. It is the step that would have caught the dead freeze command and the 751.57-frame arithmetic on paper.

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && mkdir -p marketing/campaigns/peshta/{audio,raw,cards,build,demo}   # audio/ and build/ included: the rehearsal writes to both

# GUARD. The rehearsal WRITES OVER audio/variant_d_bed_001.mp3. That file is the
# $0.075 Phase B purchase. Refuse to run in place if it is already real.
if [ -s marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 ] && \
   ! ffprobe -v error -show_entries format=duration -of csv=p=0 \
       marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 | grep -q '^31'; then
  echo "REFUSING: a real (non-rehearsal) bed is on disk. Move it aside or rehearse on a scratch copy."; exit 1
fi

# SH-01 / SH-03 share one look; SH-02 MUST look different — see the ruling below.
for n in SH-01:2 SH-03:2; do
  s=${n%%:*}; d=${n##*:}
  ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "testsrc2=s=1080x1920:r=50:d=$d" \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p -t "$d" "marketing/campaigns/peshta/raw/$s.mp4"
done
ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "testsrc2=s=1080x1920:r=50:d=2" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -t 2 marketing/campaigns/peshta/demo/demo.mp4
ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "sine=f=220:d=31" \
  -ar 48000 -ac 2 -c:a libmp3lame marketing/campaigns/peshta/audio/variant_d_bed_001.mp3
# §7.5(d) reads a hero STILL off disk, which does not exist until Phase D. Stand one in,
# or the rehearsal cannot execute step (d) at all — the one step it most needs to prove.
ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "testsrc2=s=1080x1920" \
  -frames:v 1 marketing/campaigns/peshta/cards/KF2.png
# SH-02 is a DIFFERENT pattern so master frame 126 -> 127 is a real cut (G9).
# It also carries the tv/bt470bg colour tagging testsrc2 lacks, which is exactly the
# mixed-tagging case §7.5(h)'s sixth trap is about — keep it, it is the useful half.
ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "smptebars=s=1080x1920:r=50:d=6" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -t 6 marketing/campaigns/peshta/raw/SH-02.mp4
# SH-04's LAST 0.6 s is the hero still, so master frame 749 matches frame 0 (G17).
# §2.4 row 11 requires exactly this of the real SH-04; a decoy that omits it cannot pass.
ffmpeg -hide_banner -nostdin -y -v error -f lavfi -i "testsrc2=s=1080x1920:r=50:d=4" \
  -loop 1 -i marketing/campaigns/peshta/cards/KF2.png \
  -filter_complex "[0:v][1:v]overlay=0:0:enable='gte(t,3.4)',format=yuv420p[o]" -map "[o]" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -t 4 marketing/campaigns/peshta/raw/SH-04.mp4
# then run §7.5 (a) through (h) verbatim (CUE = 0.00), then §8's qa_gate.py
```

**Pass condition: `qa_gate.py` exits 0 on the placeholder master (750 frames, 15.000000 s, all nine cards present).** If it does not, the chain is wrong and no credit should be spent fixing it.

> **Two of the decoys must model structure, not just fill a path — and the first draft of this section did not, which made its own pass condition unreachable.** Run with four identical `testsrc2` clips, `qa_gate.py` **cannot** exit 0, for two reasons that are nothing to do with the chain:
> - **G9** wants a hard cut at frame 127. With SH-01 and SH-02 cut from the same generator the measured step was `mean |dRGB| = 7.74` against a floor of `8.0` — a *near miss*, which is worse than a clear failure because it invites someone to shave the threshold. Giving SH-02 a different pattern puts the step at `21.49` and G9 goes green honestly.
> - **G17** compares frame 0 with frame 749. §2.4 row 11 already requires the real SH-04's last 8 frames to be colour-matched to frame 0; a decoy that ignores that requirement fails, as it should. Building the hero still into SH-04's tail models the requirement and G17 reports a worst-channel delta of `13.1` against a ceiling of `20.0`.
>
> The distinction that matters: these two edits make the stand-ins *model properties §2.4 demands of the real footage*. They are not threshold-tuning, and nothing in the gate was relaxed to get to exit 0.

> **G17's budget is mostly spent before the footage is even considered.** Frame 0 carries **c1**; frame 749 carries **c6 + c7 + c8**. Composited over *identical* mid-grey, those two card sets alone differ by a worst-channel mean-RGB of **14.3** — **71% of G17's 20.0 ceiling**, leaving only ≈5.7 for the footage match the gate is actually trying to measure. G17 is therefore a *weak* test of the loop seam and a *strong* test of nothing. It is left at 20.0 because it survived two rounds of fact-checking and because the human half of G17 (watch it loop three times) is the real check — but do not read a green G17 as proof the footage is matched, and do not tighten the ceiling below ~15 without first re-deriving it from the card delta.

> **A green G6 in the rehearsal is partly meaningless, and here is exactly which part.** `testsrc2`'s yellow bar is RGB `(253,254,0)`, which is inside G6's ±32 tolerance of `#FFE600` — the key colour of **c1, c2, c3 and c6**. On a colour-bar background G6 counts the *background* and passes those four cards whether or not they were composited at all: at master frame 63 it reported **332 740 px** for c1, whose own key-colour area is only **34 302 px** — a 10× inflation, essentially all backdrop. `#FFD700` (c4), `#00C853` (c5/c8) and `#0088CC` (c7) are matched by no `testsrc2` bar, so **only c4, c5, c7 and c8 are real signal in the rehearsal.** That is not hypothetical: it is how the missing-overlay bug in §7.5(h)'s sixth trap stayed hidden through a full green G6 on the first rehearsal pass.

**Then tear the decoys down — this step is mandatory, not tidiness.** Run it as the last action of Phase A step 11, **before** the first paid step (Phase B step 13):

```bash
cd /Users/ai/Desktop/work/projects/hbd-bot && \
rm -rf marketing/campaigns/peshta/raw/* marketing/campaigns/peshta/build/* marketing/campaigns/peshta/demo/* \
       marketing/campaigns/peshta/cards/KF*.png marketing/campaigns/peshta/audio/variant_d_bed_001.mp3 \
       marketing/campaigns/peshta/audio/bed_15s.wav marketing/campaigns/peshta/audio/bed_vacuum.wav \
       marketing/campaigns/peshta/audio/bed_norm.wav marketing/campaigns/peshta/variant_d_final.mp4 && \
mkdir -p marketing/campaigns/peshta/{audio,raw,cards,build,demo} && \
ls marketing/campaigns/peshta/raw marketing/campaigns/peshta/build marketing/campaigns/peshta/demo   # all three must be empty
```

> ⚠ **The rehearsal manufactures decoys that pass every automated gate, and it writes them to the exact paths production later reads and writes** — `raw/SH-0{1..4}.mp4`, `demo/demo.mp4`, `audio/variant_d_bed_001.mp3`, `cards/KF2.png`, plus everything §7.5 derives from them (`build/*.mp4`, the three intermediate wavs, and `variant_d_final.mp4` itself). Nothing in Phase D, E or F removes them. If a §6.6 `curl` returns non-zero, or the §7.5(h) mux fails, **the next step silently consumes the placeholder** — and because the rehearsal master is *by construction* 750 frames / 15.000000 s with all nine cards, `qa_gate.py` greens **G1, G2, G3, G5, G6, G8, G14, G16 and G17 on colour bars**. That is exactly the never-goes-red gate §12 condemns, built by the plan's own hand. R15's `rm -f` / `test -s` doctrine was applied only to `freeze.png`; it applies here with more force.
>
> **Why the teardown belongs at the END of Phase A and not at the head of Phase D:** by Phase D the *real* `audio/variant_d_bed_001.mp3` exists and has been paid for (step 13, $0.075), and the derived wavs from step 18 exist too. A blanket `rm` there destroys purchased work. At the end of step 11 nothing real has been made yet, so the teardown cannot delete anything but decoys. **If the rehearsal is ever re-run after Phase B, re-run it against a scratch copy of the tree, never in place.**
>
> **That contingency already happened.** `audio/variant_d_bed_001.mp3` was purchased out of order (see §3.7's amendment), so when the §7.6 rehearsal was actually executed on 2026-09-18 the paid file was already sitting on the path the rehearsal overwrites and the teardown deletes. It was moved to `audio/variant_d_bed_001.PAID_DO_NOT_DELETE.mp3` for the duration and restored afterwards, md5 `f44e2134a9acd1de0a9d72e5f9c461af` verified identical before and after. The `GUARD` block at the head of the setup above now refuses to run in place in that situation instead of relying on whoever is at the keyboard remembering this paragraph.

---

## 8. Step 5 — QA gates

Every gate is a command with a binary pass condition. Wire them into `marketing/campaigns/peshta/qa_gate.py` with all spec values in a single `SPEC` dict at the top, and **make it exit non-zero on failure** — §12 explains why that instruction is not rhetorical.

| # | Gate | Command | Pass condition |
|---|---|---|---|
| **G0** | ffmpeg capability | the `-h filter=` loop in §7.1 | `overlay`, `concat`, `loudnorm`, `zoompan`, `highpass`, `volume` present. **`drawtext` MISSING is EXPECTED** — if any command in this plan uses it, the plan is wrong, not the machine |
| **G1** | Container geometry | `ffprobe -v error -select_streams v:0 -show_entries format=duration -show_entries stream=width,height,r_frame_rate,nb_frames -of default=noprint_wrappers=1 marketing/campaigns/peshta/variant_d_final.mp4` | `width=1080`, `height=1920`, `r_frame_rate=50/1`, **`nb_frames=750`**, `duration=15.000000` — and **nothing else**. **`-select_streams v:0` is load-bearing, not tidiness.** Without it `-show_entries stream=…` prints the video stream's values *and then the audio stream's*, and the audio values come **last**: verified on a built master, the unselected command emits `r_frame_rate=50/1`, `nb_frames=750`, then `r_frame_rate=0/0`, `nb_frames=647`. The natural `key=value` parse of `-of default=noprint_wrappers=1` into the `SPEC` dict therefore keeps the *audio* row and reports FAIL on a correctly built file. A gate that reds on a good master gets disabled, which is exactly how §12's never-goes-red gates were born |
| **G2** | Decode integrity | `ffmpeg -v warning -err_detect explode -i marketing/campaigns/peshta/variant_d_final.mp4 -f null - && echo CLEAN` | stderr **completely empty**. Any output at all is a fail |
| **G3** | Loudness, on the **final mux** | `ffmpeg -hide_banner -nostdin -i marketing/campaigns/peshta/variant_d_final.mp4 -filter_complex ebur128=peak=true -f null - 2>&1 \| sed -n '/Summary:/,$p'` | `I` within −14.0 ±0.5 LUFS; **true peak ≤ −1.0 dBTP**. Never measure the intermediate wav — AAC raises TP by ~0.6 dB, which is why §7.5(g) targets −1.5 |
| **G4** | Vacuum present | `ffmpeg -hide_banner -nostdin -i marketing/campaigns/peshta/variant_d_final.mp4 -af "atrim=1.7:2.4,lowpass=f=200,volumedetect" -f null - 2>&1 \| grep max_volume` | `max_volume` at least 20 dB below the same measurement over 3.0–4.0 s. Proves the sub actually dropped. **No `-v error`** — `volumedetect` logs at `AV_LOG_INFO` and `-v error` swallows the number entirely, so the gate matches nothing and falls through on any input (§3.8). In `qa_gate.py` use `grep -q` and **fail on an empty match**, never pass on it |
| **G5a** | Safe zone, per card | alphaextract + raw row/column scan (below) | every card **except `c9`**: `220 ≤ Y ≤ 1500` **and** `40 ≤ X ≤ 940`. The centred-pill bound is **800 px**, not 900. **`c9` is the deliberate full-frame flash** — its alpha covers all 1080×1920, so the scan returns Y 0–1919 / X 0–1079 and all four asserts fail *by construction* on a correct card. Carry `SKIP_SAFE_ZONE = {"c9"}` in `qa_gate.py`'s `SPEC` |
| **G5b** | **Legibility** | measure each card's rendered em size and glyph mask height in PIL | **rendered em size ≥ 76 px AND measured cap-height ≥ 53 px** (`font.getbbox('A')[3]-[1]`), on the six narrative cards **c1–c6 and c8**. **`c7` (48 pt handle pill) and `c9` (the flash) are exempt by name.** Not "cap-height ≥ 78 px": cap ÷ size is 0.708–0.716 on Arial Unicode, so 78 px cap needs a ~109 pt face and the assert would refuse every card in §7.4 — see the §7.3 ruling. The discarded build shipped ~40 px against a mandated 78–88 pt and neither draft added this check |
| **G6** | Cards present at the right times | sample a frame at the midpoint of each of the nine windows, count brand-colour pixels | each window shows its card. **Delete the target PNG before every extraction and assert it was recreated non-empty** — see the stale-frame note below. **The naive midpoint is wrong for two of the nine windows, and it reds a CORRECT master.** §7.5(h)'s `c9` flash windows enable frames **308–309** (`6.155–6.195`) and **661–662** (`13.215–13.255`); `c4`'s window is 218–399, whose midpoint is **308**, and `c6`'s is 575–749, whose midpoint is **662**. Both midpoints therefore sample a **full-frame white flash**, in which the card's brand colour is absent and the count is zero — the exact "gate that goes red on a good file gets disabled" failure this table warns about under G1. Verified by construction in `qa_gate.py` (`pick_sample_frame`), which walks the midpoint off any `c9` frame: c4 → 307, c6 → 663. `c9` itself is skipped by name — a 2-frame flash has no meaningful midpoint sample |
| **G7** | No AI-rendered text in frame | inspect every keyframe at full size, then sample 8 frames of the master | **zero** letters, glyphs, signage, logos or UI anywhere that did not come from a card PNG or from the real screen recording at 9.00–10.50 s |
| **G8** | Faststart | `python3 -c "h=open('marketing/campaigns/peshta/variant_d_final.mp4','rb').read(4096); mo=h.find(b'moov'); md=h.find(b'mdat'); print('moov@',mo,'mdat@',md,'OK' if mo>0 and (md==-1 or mo<md) else 'FAIL')"` | `OK` — moov before mdat |
| **G9** | Slam sync | extract frames 126, 127, 128 and inspect | the wardrobe/set change is visible at frame 127, not 126 or 128. `2.54 × 50 = 127` exactly |
| **G10** | **Mute-readability** | play at 0% volume on a phone | problem understood by **1.0 s**; solution (a Telegram bot) by **3.0 s**; `@bayram_uzbot` **and** the price legible before the end. The whole story followable from text alone |
| **G11** | Handset safe zone | AirDrop to a **6.1″ and a 6.7″** handset, **and overlay a real TikTok and Reels UI screenshot** | no text box clipped or obscured by platform chrome on either. Abstract pixel bounds are not enough — the caption block is what the CTA card was courting at Y 1350 |
| **G12** | Full-volume speaker | play at 100% on a handset | the 808 punches without buzzing the grille; lyrics stay intelligible |
| **G13** | **Cultural / linguistic sign-off** | a native Uzbek reviewer reads every sung and on-screen string **as a final set**, with the NEW/CHANGED ones flagged by name | see the mandatory question list below. **Human gate — nothing automates this, and it happens BEFORE any card is rendered** |
| **G14** | Character integrity | `python3 -c "s=open('marketing/campaigns/peshta/cards/strings.txt',encoding='utf-8').read(); print('ASCII apostrophes:', s.count(chr(39)), '\| U+00A0 count:', s.count(chr(0xa0)))"` — **the file is written by `make_cards.py`** (§7.4, §11 step 4), one line per card id plus its exact rendered text. If that artefact is ever dropped, point the gate at `make_cards.py`'s own `CARDS` dict instead; never let the gate be quietly deleted because its input is missing | ASCII apostrophes = **0** (every mark is U+02BB or U+02BC) **and** U+00A0 ≥ 1 (the price grouping separator). A `FileNotFoundError` here is a **fail**, not a skip |
| **G15** | **Handle routing** | (a) tap `https://t.me/bayram_uzbot?start=ig_bayram` from an Instagram DM; (b) type `bayram bot` into Telegram search and record what comes up | (a) Telegram opens with the welcome message. (b) record the result honestly — the audio hook is "Bayram-botda", which is *not* the handle |
| **G16** | **Funnel exposure** | recompute the §2.5 table against the built master | handle ≥ 500 frames present AND ≥ 125 frames as the newest element; price ≥ 250 frames; problem stated within the first 80 frames |
| **G17** | **Loop seam** | extract frames 0 and 749; compare mean colour | mean RGB within ±20 per channel. Then watch it three times through without touching the screen and confirm the seam is not visible |

**G5a, the safe-zone measurement** (PIL is not in the system python; this ffmpeg + raw-scan path works). Run it over `c1`–`c8`; **skip `c9`**, whose alpha is the whole canvas by design:

```bash
ffmpeg -nostdin -hide_banner -v error -i marketing/campaigns/peshta/cards/c1.png \
  -vf alphaextract -pix_fmt gray -f rawvideo /tmp/a.raw -y && \
python3 -c "
W,H=1080,1920; d=open('/tmp/a.raw','rb').read()
ys=[y for y in range(H) if max(d[y*W:(y+1)*W])>8]
xs=[x for x in range(W) if max(d[y*W+x] for y in range(H))>8]
print('Y',min(ys),max(ys),'X',min(xs),max(xs))
assert 220<=min(ys) and max(ys)<=1500, 'Y OUT OF SAFE ZONE'
assert 40<=min(xs) and max(xs)<=940, 'X OUT OF SAFE ZONE'
print('SAFE ZONE OK')"
```

**The stale-frame trap in G6, G7, G9 and G17 — this bit for real.** Seeking past EOF makes ffmpeg **exit 0** having written nothing, so a leftover PNG from a previous run gets measured instead of the current one. A first version of exactly this gate reported `PASS c4 @ t=6.0s: 134047 brand-yellow px` against a **5.03 s** video that has no frame at 6.0 s. **Every frame extraction must delete the target first and assert it was recreated non-empty:**

```python
if os.path.exists(fn):
    os.remove(fn)
subprocess.run([...extract...], check=True)
assert os.path.exists(fn) and os.path.getsize(fn) > 0, f"no frame at t={t}s (seek past EOF?)"
```

Without that, a gate will happily declare a one-third-length cut publishable.

### G13 — the mandatory native-reviewer question list

The corpus contains **no evidence that any Uzbek review ever happened**. These are the strings that are new, changed, or contested. The reviewer sees the **final set**, with these flagged:

1. **`SOAT 23:55. SOVGʻA ESA YOʻQ!`** — [SWAPPED IN] from `03:492`, replacing Variant D's longer row-1 text. Does it read as contemporary vernacular?
2. **`UNING ISMIGA ATALGAN QOʻSHIQ!`** — [ADAPTED] from `03:418`. Does it correctly name the *recipient*, not the viewer? Is *uning* right, or should it be *doʻstingiz ismiga*?
3. **`SOʻZLARINI OʻQISH BEPUL!`** — [ADAPTED] from `03:419`. Does it read as "reading the lyrics is free" rather than something else?
4. **Register.** The sung line is *"Isming aytib"* (informal singular); the cards use polite forms. Settle it in one direction, for the sung lines and the cards together.
5. **`O mani kuydirding, o mani suydirding!`** — the designated lip-sync line (`02:625`: *"the emotional peak that viewers love to lip-sync"*). Two questions: is *mani* (Tashkent colloquial) right versus standard *meni*? And is bare *o* correct, or should it be *Oʻ* (U+02BB) or a different interjection? **The apostrophe gate cannot catch this — the line contains no apostrophe to check.**
6. **`Bayram-botga kiring!`** — sourced verbatim from `01:520`. Confirm the dative is right and that *Bayram-bot* reads as a name rather than a typo.
7. **`Oʻn besh mingga`** — is the spelled-out numeral singable and natural?
8. **The audio-title spelling.** The corpus writes it both *"Bayram Uzbekiston"* (`02:638`) and *"Bayram Oʻzbekiston"* (`CAMPAIGN_MASTER §5.2`). Pick one. (And see R10 — neither should carry the word *Peshta*.)
9. **The speed claim is gone.** Confirm that no on-screen string implies a turnaround time.

**Prove the gate can fail.** Run `qa_gate.py` against `marketing/campaigns/peshta/alabay_video/alabay_promo_final.mp4` (5.03 s, 30 fps, 151 packets). **It must exit non-zero.** A gate that has never gone red is not a gate.

---

## 9. Cost ledger

Balance confirmed live this session: **1568.1 credits, plan `pro`**. No free-trial unlimited allowance is available — several models advertise `supports_unlim` but every response carries `"unlim":{"available":false}` — so every figure below is a real charge.

### Kill-switch — 9 credits, 0.57% of balance

| Step | Item | Credits |
|---|---|---|
| A1 | Hero keyframe **KF-2** only, `nano_banana_pro` 2k 9:16 | **2** |
| A2a | **Free** `media_confirm` + `get_cost` with the audio media attached | **0** |
| A2 | Audio-sync probe, `wan3_0` **720p** 9:16 4 s, audio off | **7** |
| | **Total exposure before the first irreversible commitment** | **9** |

Everything expensive sits behind these two inspections. If the character is wrong, or the audio premise does not hold, we know for 9 credits and 7.5 cents.

### Lean build — 66 credits committed floor, 78 with the full reroll budget

| Step | Item | Unit | Qty | Credits |
|---|---|---|---|---|
| A1 | Hero keyframe KF-2 | 2 | 1 | 2 |
| A2 | Audio-sync probe, `wan3_0` 720p 4 s | 7 | 1 | 7 |
| 1 | KF-1, KF-1b, KF-3, KF-4 (each from KF-2 via `image_references`) | 2 | 4 | 8 |
| 1 | *Keyframe reroll budget, spent as G7 demands* | 2 | *0–6* | *0–12* |
| 3 | SH-01, `wan3_0` 1080p 2 s | 7 | 1 | 7 |
| 3 | SH-02, `wan3_0` 1080p 6 s | 21 | 1 | 21 |
| 3 | SH-03, `wan3_0` 1080p 2 s | 7 | 1 | 7 |
| 3 | SH-04, `wan3_0` 1080p 4 s | 14 | 1 | 14 |
| — | Cold open, vacuum, punch-ins, demo insert, reaction beat | — | — | **0** (local ffmpeg / screen recording) |
| 4 | Cards, loudnorm, conform, concat, composite, export | — | — | **0** |
| — | *Optional* `video_upscale` 15 s | 2 | 1 | *2* |
| | **TOTAL** | | | **66 floor · 78 with rerolls · 80 with upscale** |

That is **4.2% / 5.0% / 5.1%** of the balance, leaving at least 1488 credits.

Deliberately **not** bought: `reframe` (138 credits for 15 s, and every model here already outputs 9:16 natively); `bytedance_video_upscale` at `fps:60` (doubles that pass's cost — 0.1 → 0.2 confirmed — and 50 fps comes free from ffmpeg).

### Safe build — 465 credits, 29.7% of balance, leaving 1103

| Step | Item | Unit | Qty | Credits |
|---|---|---|---|---|
| 1 | Hero keyframe + 2 variants, `nano_banana_pro` 2k | 2 | 3 | 6 |
| A2 | Audio-sync probe, `wan3_0` 720p 4 s | 7 | 1 | 7 |
| 1 | KF-1/KF-3/KF-4 at 2 variants each | 2 | 6 | 12 |
| 1 | Alternate faces, `gpt_image_2_5` 2k/high | 3 | 2 | 6 |
| 2 | Reference Element creation | *unknown* | 1 | *unpriced* |
| 3 | Primary pass, `seedance_2_0` 1080p with `<<<element_id>>>`, 4+6+4+4 = 18 s | 9/s | 18 s | 162 |
| 3 | Full second pass, all four shots | 9/s | 18 s | 162 |
| 3 | Two extra rolls of the 6 s hero | 54 | 2 | 108 |
| 4 | `video_upscale` 15 s | 2 | 1 | 2 |
| | **TOTAL** | | | **465** |

`seedance_2_0` at 1080p 9:16 std, audio off, 6 s → **54 credits** (preflighted live this session). Its 4 s duration floor is why the safe build generates 18 s rather than 14 s. **Elements creation cost is genuinely unknown, not zero** — read the response before proceeding.

### ElevenLabs music — USD, not credits

At the configured `music_usd_per_minute = 0.15` (shipped default; `.env` holds no `BAYRAM_MUSIC_*` keys):

| Render | Estimate |
|---|---|
| 15 s | $0.0375 |
| **30 s bed (one take)** | **$0.075** |
| Lean budget, 3 takes | **$0.225** |
| Safe budget, 6 takes | **$0.45** |

`cost_usd` is always `CostSource.ESTIMATED` and can never be anything else — `POST /v1/music` returns audio and no price, and the duration used is the duration we *asked* for.

---

## 10. Risk register

| # | Risk | Trigger (how you know) | Fallback |
|---|---|---|---|
| **R1** | **The audio-first premise does not hold.** `audio_references` is a declared field nobody here has exercised, and **the media slot is declared `type: "image"`** — verified live. An audio media_id may be rejected at submission | **Gate A2a** (free) 422s on media type, or **Gate A2** shows no motion accent within ±2 frames of the slam | Drop `audio_references`, generate on prompt alone, beat-match by hand in ffmpeg (free — every cut point is already known to the frame). **Then switch the workhorse to `kling3_0` pro `sound:"off"` at 1.75 cr/s**: **16 s ≈ 28 credits instead of 49** (`kling3_0`'s duration floor is 3 s, not 2 — verified live — so SH-01 and SH-03 each generate 3 s: 3+6+3+4). Kling's missing audio role stops mattering the moment the audio role stops working |
| **R2** | **The track comes back at the wrong tempo.** No tempo field exists in the request body; ElevenLabs picks | Step 0.5 `bpm_detect.py` reads materially off 95.8 | Rebuild the §2.4 grid from measured transients — free. Re-pick fps, **and re-derive every segment so they sum to a whole number of frames.** Only then buy video. Re-render at $0.075 if the feel is wrong |
| **R3** | **Vocals come back in English or Russian, or the orthography is mangled.** `plan.language` is never sent; language is inferred from chunk text alone | §3.9 listen gate | Two language style tags are already in `POS`; keep `context_adherence=HIGH` on every vocal chunk; bump `IDEMPOTENCY_KEY` and re-render. Budget 2–3 takes at $0.075. If one chunk is wrong and `remote_id` came back, a single-chunk `inpaint()` is far cheaper than a full recompose |
| **R4** | **The vendor rejects the payload as invalid.** The 3000 ms chunk floor is a repo comment, not a verified vendor fact, and 400/422 is **non-retryable** | Terminal `ProviderError(INVALID_INPUT)` or `ProviderRejectedContentError` on the first call | Every chunk is already ≥ 6000 ms. Read `error.context['response_detail']` — the first 1000 chars of the vendor body name the offending field. First remedy: raise every chunk to ≥ 10 000 ms |
| **R5** | **Artist-name rejection.** `ARTIST_NAME_IN_STYLE` is terminal and burns the attempt | Any style or text field mentions Hamdam Sobirov, "Peshta", "in the style of", "cover of" | Never happens if §3.6 is followed. The style list describes the **idiom** only. The parody reference lives in the campaign documents and nowhere a vendor can read it |
| **R6** | **AI-generated Uzbek text appears in frame.** The discarded build produced "TASHKENT", "ALABAY / HYPE SQUAD" and a magenta "A" monogram **despite** a negative prompt that already banned `text` and `signature` | **Inspect every keyframe at 2 credits, BEFORE animating.** Zoom on clothing, signage and background architecture | Reroll that keyframe (2 credits) with the strengthened negative in §4.5. **Never animate a still that has text in it** — the text will warp and worsen. If it recurs, reframe tighter on the dog to exclude backgrounds and clothing surfaces. This is why the reroll budget is 6 stills, not 1 |
| **R7** | **Canine anatomy failure** — six toes, human hands, dissolving doppi patterns. Worst on the dancing hero shot | Keyframe inspection at 2 credits, then the probe clip | Motion intensity is locked to 3.5–4.5 (above ~6 turns paws into hands). Prefer named camera moves over acrobatics. Never attempt tight mouth lipsync. **Roll stills, not clips** — `01 §4.3`'s "top 3 of 15" ratio is affordable at 2 credits a still and not at 21. If it persists in motion, **shorten the clip** (three 2 s clips = the same 21 credits), then `hf_mult_motion_control` — **price unknown; preflight it with a driving clip attached before budgeting** |
| **R8** | **Shot-to-shot identity drift.** The lean build has no Elements lock — `wan3_0` is absent from the supported list. The discarded build drifted *inside* one 5 s clip (bandana → doppi between 2.0 s and 3.0 s) | Place frames from all four shots side by side. Check doppi pattern, chain thickness, **rectangular** not aviator sunglasses, **velvet chopon** not satin bomber, **smaller pups** not adult dogs | §5 ladder: ranks 1–4 free, then reroll the keyframe (2 cr), then shorten the clip, then escalate **that shot only** to `seedance_2_0` + `<<<element_id>>>` at 9 cr/s. Never escalate globally on one bad shot |
| **R9** | **Audio/motion desync at the slam** | Gate G9 | The cut is authored in ffmpeg at frame 127, so this is a conform problem, not a generation problem. Re-cut. If the video's own motion accent is off, that is R1 |
| **R10** | **Platform rights flag on the audio** | Upload rejected, muted, or the sound page restricted | **Do not publish as "Peshta (Parodiya)"** — under D4 that title invites the exact association we paid to avoid, and the corpus recommends it. Publish as **original audio** under a title carrying the handle, e.g. `@bayram_uzbot — Bayram-botda`. Keep *peshta* out of the lyrics (Variant D happens not to contain it; keep it that way). Restate the Tier-2 clearance by **provenance** — composed in-house, rendered through the product's own ElevenLabs Music provider, genre `UZBEK_POP` — **never by BPM**, or someone later commissions a 126 BPM stem that will not sit on this grid. Note the Instagram account is a cold 0/0 **professional** account with a restricted audio library, so the custom-audio path is the one that works there |
| **R11** | **Overclaiming on screen.** The product deliberately makes no turnaround promise | The card ships with any time claim | Removed entirely in §7.4 ruling 3. The speed claim lives in the pinned comment. **Do not put a number back on the card without a measured end-to-end run**, and if you do, make it a ceiling (*bir necha daqiqada*), not a promise |
| **R12** | **Text unreadable in a muted feed.** The discarded build's glyphs are ~40 px against a mandated 78–88 pt | Gates G5b and G10 | 1 pt = 1 px is ruled in §7.3 and `03 §5`'s sizes govern. `make_cards.py` refuses to write a narrative card (c1–c6, c8) below **76 px rendered em size or 53 px measured cap-height** — *not* 78 px cap-height, which is unreachable at these type sizes and would refuse every card in §7.4 (cap ÷ size is 0.708–0.716 on the installed face). `c7` and `c9` are exempt by name. **Measure; do not eyeball** |
| **R13** | **Safe-zone overflow.** The box is asymmetric about centre; 900 px overflows, and Y 1350 courts the Reels caption block | Gates G5a and G11 | `make_cards.py` hard-asserts at render time. Max centred pill is **800 px**. The CTA block sits at Y 1050, not Y 1350 |
| **R14** | **Emoji render as tofu boxes.** Arial Unicode has no glyph for 🔥 or 👉 — both return an identical 64×48 full-em mask, verified this session | Cards show empty rectangles, and the safe-zone assert passes anyway | Draw the flame and chevron as **PIL vector shapes** (the ruling). If colour emoji are wanted, Apple Color Emoji loads in PIL only at 20/32/48/64/96/160 — 137 raises `OSError: invalid pixel size` — so draw at 160 and LANCZOS-resize down |
| **R15** | **The freeze frame silently vanishes.** `ffmpeg -ss` past the end of a clip exits 0 writing nothing, and the next step reuses a stale PNG | Gate G1 reports 703 frames instead of 750 — **after all 49 credits are spent** | Use `-sseof -0.04` (verified working this session), with `rm -f` before and `test -s` after. §7.5(e). Same rule for every frame extraction in §8 |
| **R16** | **The demo insert cannot be made.** It depends on a working bot and a real 1080×1920 screen capture | No `marketing/campaigns/peshta/demo/demo.mp4` at Phase D | Redistribute frames 450–524 to SH-03 (extend the phone insert to 2.50 s) and accept that the cut has **no product demonstration at all**. This is a real loss, not a shrug — it is the only honest product proof in the film. Use a neutral recipient name (*Saodatxon*, the corpus' own demo name), never a real person's |
| **R17** | **The 15 s cut cannot convert on its own.** `03` Shot 3 was the only product demo in the corpus, and even restored it is 1.50 s | Bot CTR from this asset is low | Structural. Treat this as the top-of-funnel and audio-page asset and ship the **25 s demo cut** as the conversion piece — exactly the dual-flagship cadence in `01 §5.3` (Alabay days 1–3, demo days 4–7). The caption and pinned comment carry the how-it-works that 15 seconds has no room for, and they ship **with** the video, not after it |
| **R18** | **The sound is reused with a dead tail.** Every creator who picks it up inherits a track that stops at 15.0 s | Remixes stop dead | We already render a 30 s bed and use half of it. Seed a **loop-clean 30 s version** of the bed to the sound page — nearly free, and it is what makes the sound a distribution asset rather than a one-off |

---

## 11. Execution order

Steps marked **💰 SPEND** require the user's explicit green light. Everything else is free. **The user has authorised ZERO spend so far.**

### Phase A — free preparation

1. ☐ **FREE** — `mkdir -p marketing/campaigns/peshta/{audio,raw,cards,build,demo}` (§3.2). Nothing downstream works without this.
2. ☐ **FREE** — Write `marketing/campaigns/peshta/render_variant_d_bed.py` (§3.7). **Not at the repo root.**
3. ☐ **FREE** — Write `marketing/campaigns/peshta/bpm_detect.py` (pure-stdlib autocorrelation BPM detector).
4. ☐ **FREE** — Write `marketing/campaigns/peshta/make_cards.py` (PIL renderer; render-time safe-zone assert **and** the glyph-height assert — **≥ 76 px rendered em size and ≥ 53 px measured cap-height**, on c1–c6 and c8 only, with `c7` and `c9` in a named exemption list; `TC = "\u02bb"` and `NBSP = "\u00a0"` written as escapes, never literals; PIL vector flame and chevron). **It also writes `marketing/campaigns/peshta/cards/strings.txt`** — one line per card id plus its exact rendered text, UTF-8 — which is the artefact G14 audits.
5. ☐ **FREE** — Write `marketing/campaigns/peshta/qa_gate.py` (§8, one `SPEC` dict, **exits non-zero on failure**, delete-then-assert on every frame extraction).
6. ☐ **FREE** — **Prove the gate can fail:** run it against `marketing/campaigns/peshta/alabay_video/alabay_promo_final.mp4`. It must exit **1**.
7. ☐ **FREE** — Run G0 (ffmpeg filter check). Install Montserrat ExtraBold and verify U+02BB / U+02BC / U+00A0 coverage on the installed face (§7.2).
8. ☐ **FREE** — Run Gate 0a, the provider dry run (§3.3). Must print `provider.name = elevenlabs_music`.
9. ☐ **FREE** — **Gate G13: native Uzbek reviewer signs off the complete final string set**, with the nine flagged items in §8. **This happens NOW, before any card is rendered and before the song is bought.**
10. ☐ **FREE** — Render all nine cards; G5a and G5b fire at render time. Look at them.
11. ☐ **FREE** — **Rehearse the entire assembly chain on colour bars (§7.6).** `qa_gate.py` must exit 0 on the placeholder master. This is the step that catches a broken command on paper instead of after 49 credits. **Then run §7.6's teardown block and confirm `raw/`, `build/` and `demo/` are empty.** The rehearsal's artefacts are decoys that green nine of the automated gates on colour bars; leaving one behind means a failed download or a failed mux is never noticed. **This sub-step is mandatory and it happens before step 13.**
12. ☐ **FREE** — Record the 1.50 s product demo on a real device (§2.4 row 8): name typed → `✅ Ha, shunday` → language picked → lyric-writing spinner → free lyric preview. **Film the shipped flow, not the blueprint's — there is no `Qoʻshiq yaratish` button.** Neutral recipient name.

### Phase B — the song (💰 $0.075 USD, no credits)

13. 💰 ☐ **SPEND ~$0.075** — Run `render_variant_d_bed.py`. 30 s bed, idempotency key `-001`. *(ElevenLabs, USD, not credits.)*
14. ☐ **FREE** — ffprobe + volumedetect (§3.8). **Run `volumedetect` without `-v error`** or it prints nothing at all. `max_volume ≈ −91 dB` means silence arrived — stop and fix. **No number printed is also a stop**, not a pass.
15. ☐ **FREE** — Measure the tempo with `bpm_detect.py`.
16. ☐ **FREE** — **Re-derive the §2.4 grid from measured transients. Re-pick the master fps. Re-derive every segment so they sum to a whole number of frames. Recompute the shot durations.** This is the gate on all video spend.
17. ☐ **FREE** — Human listen-and-approve (§3.9). Not approved → back to 13, bump `IDEMPOTENCY_KEY`. Up to 3 takes budgeted.
18. ☐ **FREE** — Cut the 15.0313 s window and author the vacuum (§7.5 a–b).
19. ☐ **FREE** — `media_upload` → PUT → `media_confirm` the 15 s cut to Higgsfield.

### Phase C — the kill switches (💰 9 credits total)

20. 💰 ☐ **SPEND 2 credits** — Generate **KF-2, the hero keyframe** (§4.4).
21. ☐ **FREE** — **KILL SWITCH 1.** Inspect KF-2 at full size: canine anatomy, paw count, doppi pattern, **rectangular** sunglasses, **velvet chopon**, two **smaller** pups, and **zero text anywhere in frame**. Reroll (2 credits) or abort.
22. ☐ **FREE** — **Gate A2a** (§6.2): `get_cost` with the audio media attached in the `audio_references` role. A 422 on media type kills the audio-first premise at zero cost.
23. 💰 ☐ **SPEND 7 credits** — **Gate A2**, the audio-sync probe (§6.3).
24. ☐ **FREE** — **KILL SWITCH 2.** Three questions: (a) does motion relate to the track's transients? (b) does identity hold across 4 s of motion? (c) what fps did it come back at? **If (a) fails, switch the workhorse to `kling3_0`, re-cost, and re-plan — here, before 40 more credits.**

> **Total spend to this point: 9 credits (0.57% of balance) and 7.5 cents.** Everything expensive is still unbought, and all three things most likely to sink the build have been tested.

### Phase D — keyframes (💰 8 credits committed, up to 12 more in rerolls)

25. ☐ **FREE** — Re-preflight every shot cost with `get_cost:true` against the **re-derived** durations.
26. 💰 ☐ **SPEND 8 credits** — Generate KF-1, **KF-1b**, KF-3, KF-4, each with `image_references: <KF-2 job_id>` (§4.4). **KF-1b is committed, not optional** — SH-01 cannot be submitted without it (§5 Rank 4, §6.4).
27. ☐ **FREE** — **Gate G7 on every keyframe**, then retrieve all five to `marketing/campaigns/peshta/cards/` (§6.6 step 6) — §7.5(d) reads `cards/KF2.png` off disk. KF-3 in particular: **the phone screen must be blank matte dark grey with no interface.** Reroll rather than accept.
28. 💰 ☐ **SPEND 0–12 credits** — Reroll any keyframe that fails. Budget six rolls; use what you need.

### Phase E — shots (💰 49 credits)

29. 💰 ☐ **SPEND 21 credits** — Generate **SH-02 first.** It is 43% of the runtime, it carries the film, and it holds the anatomy risk. If it fails, the build changes shape and you have spent the least.
30. ☐ **FREE** — Retrieve it (§6.6: `jobs_wait` → `show_generation_by_ids` → `curl`), `ffprobe` it, inspect against R7 and R8. Reroll (21 credits) or proceed.
31. ☐ **FREE** — **Time that job and write the number into this plan.** Phase E is unschedulable until you do.
32. 💰 ☐ **SPEND 28 credits** — Generate SH-01 (7), SH-03 (7), SH-04 (14).
33. ☐ **FREE** — Retrieve all three, `ffprobe` every clip for its real fps, inspect all four side by side for drift.

### Phase F — assembly (free, all of it)

34. ☐ **FREE** — Conform every shot to the grid with the punch-in scale steps (§7.5 c).
35. ☐ **FREE** — Build the cold open and the vacuum snap-zoom (§7.5 d–e). **`-sseof`, `rm -f` before, `test -s` after.**
36. ☐ **FREE** — Concat → **expect exactly 750 frames / 15.000000 s** (§7.5 f).
37. ☐ **FREE** — Loudnorm two-pass at `TP=-1.5` (§7.5 g).
38. ☐ **FREE** — Final composite, mux and export (§7.5 h). **The bed is input 10.**

### Phase G — QA (free)

39. ☐ **FREE** — Run `qa_gate.py`: G1–G9, G14, G16, G17. **Any failure blocks.**
40. ☐ **FREE** — G10 mute-readability, G11 handset + real UI screenshot overlay, G12 full-volume speaker, G15 deep link **and Telegram search**, G17 loop watch.
41. ☐ **FREE** — G13 final read: the native reviewer sees the **burned-in cards**, not just the strings.
42. ☐ **FREE** — Set the cover frame to frame 127 explicitly at upload (§2.6).

### Phase H — publish (ships WITH the video, not after it)

43. ☐ **FREE** — Upload as **original audio** under a title that does not carry the original's name (R10).
44. ☐ **FREE** — Caption carrying the tappable handle and the speed claim that was pulled off the card.
45. ☐ **FREE** — Pinned comment with the how-it-works the 15 s cut had no room for.
46. ☐ **FREE** — Seed the loop-clean 30 s bed to the sound page (R18).

**Spend summary — four money moments:** step 13 (~$0.075 USD), step 20 (2 credits), step 23 (7 credits), steps 26/28/29/32 (57–69 credits). **Steps 16, 22 and 24 are the three decision points where the plan is allowed to change its mind before the expensive step.**

---

## 12. Discarded

Nothing in `marketing/campaigns/peshta/alabay_video/` is reused as a deliverable (D7). Here is what is wrong with each piece, and what survives.

| Artefact | Verdict | Why |
|---|---|---|
| `alabay_promo_final.mp4` | **Discarded** | **5.033 s against a 15.0 s brief** — 33.5% of the required runtime. It cannot carry the drop-then-payoff arc at all: at 5.03 s the CTA card is already on screen half a second after where the slam would land. |
| | | 30 fps, 151 packets, and a **1.5× upscale of a 720×1280 source**, so it carries no native 1080p detail. |
| | | **One continuous push-in with no cuts.** Frames sampled at 0.5 / 2.0 / 3.0 / 4.5 s show the same trio composition throughout. No hard cut, no wardrobe snap, no confetti, no phone prop, no *yelka qoqish* shoulder bounce, no paw-point. Variant D needs a hard cut at 2.54 s plus distinct staging at 2.54, 8.00 and 11.50 s — **four visual beats, of which this delivers zero.** |
| | | **Violates the zero-AI-text rule**, the one the corpus states in bold. A neon sign reading "TASHKENT", a hoodie reading "ALABAY / HYPE SQUAD" with a mangled glyph, a tracksuit reading "ALABAY" under a crown, and a magenta "A" monogram. `01:353-356`'s negative prompt **already listed** `text` and `signature` — so the guardrail was either not applied or not honoured. This is R6, and it is why keyframe inspection at 2 credits is a hard gate here. |
| | | **Off-bible wardrobe.** A bandana/du-rag at 0.5 s and 2.0 s that **morphs into a doppi by 3.0 s** — identity drift inside a single generation. **Aviator** sunglasses where the bible says rectangular. A magenta satin bomber where the bible says black velvet mini-chopon. Two **full-size adult** Alabays in branded hoodies where the bible says two *smaller* pups in plain backward caps. Grade is rain-slick neon cyberpunk; the spec is warm studio portrait with amber `#FFB703` and magenta `#E63946` accents. |
| `alabay_dance_raw.mp4` | **Discarded as footage** | 720×1280 @ 24 fps — half the target pixel count and the wrong frame rate. New shots are generated natively at 1080×1920. **Retained only as the single piece of empirical evidence anywhere of what Higgsfield actually outputs** (24 fps, which no catalog entry declares). It is why R11-class fps checking exists and why G1 probes rather than assumes. |
| `alabay_trio_keyframe.png` | **Discarded** | It is the keyframe that produced the wardrobe and AI-text failures above. Anything generated from it inherits them. |
| `overlay_hook.png`, `overlay_cta.png` | **Discarded** | Copy is wrong and unsourced: the hook reads `SOVG'AGA BOSHI QOTGANLAR UCHUN...`, a string appearing in **none** of the four research documents, and the CTA reads `KIRGIN BAYRAM-BOTGA!`, which is not the scripted CTA anywhere. ASCII U+0027 throughout, violating `03 §6.2`. Geometry *passes* the safe zone (hook Y 280–349 X 159–924; CTA Y 1120–1396 X 160–926) but is off-spec: the hook pill centres at Y≈314 against a mandated 380–480 band, and its 70 px pill height implies **~40 px glyphs against a mandated 78–88 pt** — roughly half, and exactly what the muted-feed protocol is *not* sized for. No down-chevrons, no handle pill, no price badge, no audio-player sticker. |
| `audio_aligned.aac` | **Discarded** | 4.742 s against a 5.033 s video — ~0.29 s of silence at the tail. No sub-bass vacuums, no 808 slam, no doira rim-shot. |
| `challenger_frames/` | **Discarded** | Evidence, not assets. |
| `tests/verify_production_specs.py` | **Discarded as a gate** | **Contains zero assertions.** It prints `'PASS' if cond else 'FAIL'` and **always exits 0**. Wired into CI it returns green unconditionally. Treat it strictly as a written report. Its FINDING 1 (X=1000 penetrates the right danger zone by 60 px) and FINDING 2 (CTA arrows breach the bottom bound) are genuine — FINDING 1's defect class was independently reproduced while deriving the 800 px centred-pill bound in §7.3. |
| `tests/test_promo_peshta_production.py`, `tests/test_peshta_lyrics.py` | **Leave alone** | 25 tests, all passing — but they assert against the **markdown** for the 25 s / 7-shot / 60 fps master (`len(shots)==7`, `running_time==25.0`, `frame_sum==1500`). Every constant is wrong for Variant D, and they will keep passing no matter what the new 15 s file contains. Keep them as the 25 s master's spec tests; add a **parallel** Variant D gate rather than rewriting them. |

### Mined and kept

| Kept | Why |
|---|---|
| **The structure of `challenger_stress_test.py`** | The only artefact in the repo that asserts against a *rendered file*. Its five suites — bitstream decode with `-err_detect explode`, media-parameter assertion, EBU R128 loudness audit, frame visual sampling, faststart moov-before-mdat validation — are a ready-made skeleton for G1–G8. |
| **…with three hardcodes lifted into `SPEC`** | `assert len(packets) == 151`, `assert 5.0 <= dur_val <= 10.0`, and the fixed probe timestamps `[0.5, 2.0, 3.0, 4.5]` with fixed pixel coordinates. **Reusing it unchanged would green-light a clip a third of the required length.** |
| **…and its WCAG block rewritten or deleted** | That block computes contrast from **hardcoded RGB literals**, never from the sampled frame — it would pass on a completely black video. Make it read `img.getpixel`, or delete it. (`PIL` is absent from the *system* python; use `.venv/bin/python` or the ffmpeg `alphaextract` path.) |
| **The mastering chain** | The one spec the discarded file actually met: measured EBU R128 **−14.4 LUFS integrated, −2.2 dBTP true peak**, inside the −14.0 ±0.5 / −1.0 dBTP gate. §7.5(g) reproduces it properly as a two-pass linear loudnorm — with the correction that measurement happens on the **final muxed mp4** and the target is `TP=-1.5`. |
| **Safe-zone discipline on the overlays** | Both PNGs clear Y 220, Y 1500 and X 940. The *position* and *size* within the zone are wrong, but nothing breaches the danger zones. |

### The warning this project has already been given once

`challenger_stress_test.py` contains:

```python
assert 5.0 <= dur_val <= 10.0
assert len(packets) == 151
```

Those assertions encode the *failure* as a pass. Against a 15-second brief, a harness that green-lights a 5.03-second file is worse than no harness. `verify_production_specs.py` is the same shape one step further gone — zero assertions, always exits 0.

**This is the `.includes("t(")` i18n test again, in a different medium.** A gate that has never gone red is not a gate. Phase A step 6 exists for exactly that reason: before trusting `qa_gate.py`, point it at the 5.03-second file and confirm it exits non-zero.