#!/usr/bin/env python3
"""Pure-stdlib tempo detector for marketing/campaigns/peshta Step 0.5 (04_generation_plan.md 3.8).

WHY THIS EXISTS
---------------
There is no BPM tooling on this machine: aubio, librosa, numpy, scipy,
soundfile, sox and bpm-tools are all absent from both interpreters and the
PATH (numpy and aubio re-verified absent from .venv this session). Step 0.5 has
to re-derive the whole edit grid from the *delivered* song, because
`build_compose_body` sends no tempo field and ElevenLabs picks the tempo
itself. This script fills the gap with nothing but the standard library plus
one ffmpeg subprocess call to decode the input to mono 16-bit PCM.

WHAT IT REPORTS
---------------
1. The detected BPM, refined against a high-order autocorrelation peak.
2. A confidence indication -- four numbers and a HIGH / MEDIUM / LOW verdict:
   peak (normalised ACF height), peak/mean (contrast against the search range),
   margin (the winner over the best lag that is NOT a metrical relative of it),
   and the inter-onset disagreement between the tempo and the real transients.
3. The top-5 candidate lags, so a half-tempo or double-tempo read is visible
   rather than silent (3.8 requires this explicitly).
4. The timestamps of the strongest transients and the best-fitting beat phase,
   because 3.8 step 2 re-cuts the grid from real transients, not from a BPM.
5. The grid arithmetic of 3.8 steps 1 and 4: bar = 240 / BPM, six bars, and the
   frame counts at 30 / 50 / 60 fps, with the fps verdict computed over the
   EDIT CUT POINTS (not over the musical periods -- see grid_report).

ALGORITHM
---------
ffmpeg -> mono 22050 Hz PCM s16 -> per-hop (64 samples, so a 344.53 Hz
envelope) mean square in two bands: the full band, and a pre-emphasised band
which is just the first difference of the signal, lifting clicks and hats off
the bass -> half-wave-rectified log flux summed over both bands -> 3-tap
smoothing -> mean removed -> unbiased normalised autocorrelation across the lag
range implied by --min-bpm/--max-bpm -> harmonic score ac(L) + 0.5*ac(2L) +
0.25*ac(4L), so the fundamental does not lose to its own half-tempo -> the
winning integer lag is then refined against the m-th ACF peak with parabolic
interpolation (see refine_lag: this is what buys the last two decimal places).

MEASURED ACCURACY (`--selftest`, ffmpeg-synthesised ground truth, 24 s each)
---------------------------------------------------------------------------
    click  88.0 BPM   ->  88.00   error -0.000   HIGH
    click  95.8 BPM   ->  95.80   error -0.004   HIGH
    click 126.0 BPM   -> 126.00   error -0.000   HIGH
Before the refine_lag change the same three read 87.97 / 95.70 / 126.05: the
envelope grid quantises lag to ~0.44 BPM near 96 BPM, and interpolating the
autocorrelation LINEARLY can never place a maximum between two samples, so a
fine BPM sweep just snapped back to the integer lag. Cross-check of the whole
grid path: `--bpm 95.8 --cuts 2.54,8.0,11.5` reproduces the 2.2 table exactly
(2.54 s -> 76.20 / 127 / 152.40 frames, so 50 fps; six bars = 15.0313 s).

FAILURE MODES (all measured this session, not guessed)
------------------------------------------------------
* NOT PERCUSSIVE. A sustained pad has almost no flux; the autocorrelation is
  smooth rather than spiky, so EVERY lag scores about the same. Measured on a
  three-sine pad with a 0.2 Hz tremolo: it returned 92.32 BPM -- a number with
  no musical meaning whatsoever -- but with margin 1.00 (want >= 1.50) and
  envelope crest 3.4 against 19-21 for a click track, so the verdict is LOW.
  Note that peak height does NOT catch this case: the pad's ACF peak is 0.941,
  as high as a click track's. The margin is what catches it.
  *Treat LOW as "no tempo found", never as a tempo.*
* STRONG OFF-BEAT. If the off-beat hit is a DIFFERENT sound from the down-beat,
  the two-band envelope separates them and the quarter survives: a 95.8 BPM
  track with a bright off-beat hat 12 dB above the kick still read 95.80, HIGH.
  If the off-beat is the SAME sound and louder, the onset train is genuinely
  periodic at the eighth and the detector reports DOUBLE: measured 191.61 BPM,
  HIGH, on a 95.8 BPM track whose "and" is 12 dB up. That is a real ambiguity,
  not a bug -- and the top-5 table showed 95.70 sitting right underneath it
  (1.5680 against the winner's 1.6174). ALWAYS read the top-5 table before
  trusting the headline number.
* SWING. A 2:1 swung off-beat does not land at lag/2, so the half-tempo
  harmonic is weakened and the quarter is found correctly: measured 95.80 BPM,
  HIGH, on a swung 95.8 click. Swing shows up instead as a 3:2 relative in the
  candidate table (143.55 BPM appeared there at 0.4475).
* DENSE SUBDIVISION IN REAL MUSIC. On the existing promo audio
  (`alabay_video/audio_aligned.aac`, 5.08 s) it reports 191.37 BPM with 95.70
  listed as HALF of winner -- consistent with 2.1's "measures 95.70 BPM"
  claim, one octave down. The inter-onset disagreement printed 0.491 beat,
  i.e. the real onsets are twice as dense as the reported beat, which is what
  dropped the verdict to MEDIUM. That disagreement number IS the octave alarm.
* TRIPLE / SHUFFLE FEEL. Measured on the delivered bed
  (`audio/variant_d_bed_001.mp3`, 30.04 s, mean -14.8 dB so definitely not a
  dead render): 100.00 BPM, MEDIUM, with 149.80 and 74.90 BPM sitting right
  behind it at almost the same score. Those three are 6 : 4 : 3 multiples of
  one 0.2003 s atom, and the transient list lands repeatedly on +0.33 and
  +0.67 of a beat -- a triplet grid, not a straight one. Re-run on 10 s
  windows and the SAME three lags (207 / 138 / 276 envelope frames) come back
  in all three windows, which is why the number is trustworthy even at MEDIUM:
  noise does not repeat a lag across independent windows. What the detector
  cannot tell you is which of the three the ARRANGER calls the beat. Decide
  that by ear, then pass it to --bpm.
* RUBATO / TEMPO DRIFT. This is a whole-file autocorrelation: one number for
  the file, and a moving tempo is smeared. Run it on 10 s windows if in doubt.
* SHORT FILES. Under ~8 s there are few periods to average and the refinement
  order m drops (the promo clip refined at x5, a 24 s click at x12-x16), so the
  last decimal place is not trustworthy. Under 2 s it exits 3 and says so.
* Digital silence or a dead render exits 3 with a STOP message, matching 3.8's
  treatment of a -91 dB volumedetect reading.

USAGE
-----
    .venv/bin/python marketing/campaigns/peshta/bpm_detect.py marketing/campaigns/peshta/audio/song.mp3
    .venv/bin/python marketing/campaigns/peshta/bpm_detect.py song.mp3 --expect 95.8 \
        --cuts 2.54,8.0,11.5
    .venv/bin/python marketing/campaigns/peshta/bpm_detect.py --bpm 95.8 --cuts 2.54,8.0
    .venv/bin/python marketing/campaigns/peshta/bpm_detect.py --selftest

Exit status: 0 on a successful measurement (LOW confidence still exits 0 -- the
verdict is printed and the operator decides), 1 if --selftest fails, 2 if the
file cannot be decoded, 3 if the audio is silent or too short to measure.
"""

from __future__ import annotations

import argparse
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

SR = 22050          # decode rate; plenty for an onset envelope
HOP = 64            # -> 344.53 Hz envelope rate
EPS = 1e-12
FPS_CANDIDATES = (30, 50, 60)
FRAME_TOL_MS = 0.5  # a cut point closer than this to an integer frame counts


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------
def decode_mono(path: str, sr: int = SR) -> array.array:
    """Decode any ffmpeg-readable file to a mono 16-bit sample array."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not on PATH; this script decodes through it")
    tmpdir = tempfile.mkdtemp(prefix="bpm_detect_")
    wav_path = os.path.join(tmpdir, "mono.wav")
    try:
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", path,
             "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le",
             "-f", "wav", wav_path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(wav_path):
            sys.stderr.write(proc.stderr)
            raise SystemExit(2)
        with wave.open(wav_path, "rb") as w:
            if w.getsampwidth() != 2:
                raise SystemExit(2)
            raw = w.readframes(w.getnframes())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


# --------------------------------------------------------------------------
# onset envelope
# --------------------------------------------------------------------------
def onset_envelope(x: array.array, hop: int = HOP) -> list[float]:
    """Half-wave-rectified log flux of two band energies, one value per hop."""
    n = len(x)
    nframes = n // hop
    if nframes < 4:
        return []
    e_lo: list[float] = []
    e_hi: list[float] = []
    prev_sample = 0
    for f in range(nframes):
        base = f * hop
        chunk = x[base:base + hop]
        s_lo = 0.0
        s_hi = 0.0
        p = prev_sample
        for v in chunk:
            s_lo += float(v) * v
            d = v - p
            s_hi += float(d) * d
            p = v
        prev_sample = p
        e_lo.append(s_lo / hop)
        e_hi.append(s_hi / hop)

    env = [0.0]
    for i in range(1, nframes):
        d_lo = math.log(e_lo[i] + EPS) - math.log(e_lo[i - 1] + EPS)
        d_hi = math.log(e_hi[i] + EPS) - math.log(e_hi[i - 1] + EPS)
        env.append(max(0.0, d_lo) + max(0.0, d_hi))
    # light 3-tap smoothing: transients survive, sample-level jitter does not
    smooth = list(env)
    for i in range(1, len(env) - 1):
        smooth[i] = 0.25 * env[i - 1] + 0.5 * env[i] + 0.25 * env[i + 1]
    return smooth


# --------------------------------------------------------------------------
# autocorrelation
# --------------------------------------------------------------------------
class AcCtx:
    """Mean-removed envelope plus its energy, so single lags can be costed later."""

    def __init__(self, env: list[float]):
        self.n = len(env)
        mean = sum(env) / self.n
        self.e = [v - mean for v in env]
        self.energy = sum(v * v for v in self.e) / self.n

    def lag(self, lag: int) -> float:
        """Unbiased normalised autocorrelation at one integer lag."""
        m = self.n - lag
        if m <= 0 or self.energy <= EPS:
            return 0.0
        e = self.e
        s = 0.0
        for i in range(m):
            s += e[i] * e[i + lag]
        return (s / m) / self.energy


def autocorr(ctx: AcCtx, min_lag: int, max_lag: int) -> list[float]:
    """Autocorrelation over a lag range, index == lag."""
    ac = [0.0] * (max_lag + 1)
    for lag in range(min_lag, max_lag + 1):
        if lag >= ctx.n:
            break
        ac[lag] = ctx.lag(lag)
    return ac


def parabolic_vertex(y_m1: float, y_0: float, y_p1: float) -> float:
    """Sub-sample offset of the vertex of the parabola through three points."""
    denom = y_m1 - 2.0 * y_0 + y_p1
    if abs(denom) < EPS:
        return 0.0
    off = 0.5 * (y_m1 - y_p1) / denom
    return max(-0.5, min(0.5, off))


def refine_lag(ctx: AcCtx, coarse_lag: int) -> tuple[float, int]:
    """Refine an integer lag using a HIGH-ORDER autocorrelation peak.

    Linear interpolation of the ACF can never produce a maximum between two
    samples, so a fine sweep over interpolated lags always snaps back to the
    integer grid -- at 344.5 Hz that is a ~0.44 BPM quantisation, which is far
    too coarse when the whole point is to decide between 95.8 and 88. The fix
    is to locate the m-th ACF peak (m periods out, as far as the file allows),
    parabolically interpolate THAT peak, and divide by m: the resolution
    improves by a factor of m, because a tempo error accumulates across m
    periods. Only a handful of extra lags are costed, so it stays cheap.
    """
    if coarse_lag < 2:
        return float(coarse_lag), 1
    m = int(ctx.n / (3.0 * coarse_lag))
    m = max(1, min(16, m))
    target = m * coarse_lag
    half = max(4, m)
    best_i, best_v = target, -2.0
    for lag in range(max(2, target - half), min(ctx.n - 2, target + half) + 1):
        v = ctx.lag(lag)
        if v > best_v:
            best_v, best_i = v, lag
    off = parabolic_vertex(ctx.lag(best_i - 1), best_v, ctx.lag(best_i + 1))
    return (best_i + off) / m, m


def ac_at(ac: list[float], lag: float) -> float:
    """Linearly interpolated autocorrelation at a fractional lag."""
    if lag < 1 or lag + 1 >= len(ac):
        return 0.0
    i = int(lag)
    frac = lag - i
    return ac[i] * (1.0 - frac) + ac[i + 1] * frac


def harmonic_score(ac: list[float], lag: float) -> float:
    """Favour the fundamental over its own half-tempo."""
    return ac_at(ac, lag) + 0.5 * ac_at(ac, 2.0 * lag) + 0.25 * ac_at(ac, 4.0 * lag)


# --------------------------------------------------------------------------
# transients
# --------------------------------------------------------------------------
def pick_transients(env: list[float], env_rate: float, count: int,
                    min_gap_s: float = 0.08) -> list[tuple[float, float]]:
    """Strongest local maxima of the envelope as (time_s, strength)."""
    peaks = []
    for i in range(1, len(env) - 1):
        if env[i] >= env[i - 1] and env[i] > env[i + 1] and env[i] > 0.0:
            peaks.append((env[i], i))
    peaks.sort(reverse=True)
    min_gap = max(1, int(round(min_gap_s * env_rate)))
    chosen: list[tuple[int, float]] = []
    for strength, i in peaks:
        if all(abs(i - j) >= min_gap for j, _ in chosen):
            chosen.append((i, strength))
        if len(chosen) >= count:
            break
    chosen.sort()
    return [(i / env_rate, s) for i, s in chosen]


def best_phase(env: list[float], lag: float) -> tuple[float, float]:
    """Beat phase (in envelope frames) that maximises the comb sum at `lag`."""
    n = len(env)
    best_off, best_val = 0.0, -1.0
    limit = int(math.ceil(lag))
    for off in range(limit):
        total = 0.0
        pos = float(off)
        while pos < n - 1:
            i = int(pos)
            frac = pos - i
            total += env[i] * (1.0 - frac) + env[i + 1] * frac
            pos += lag
        if total > best_val:
            best_val, best_off = total, float(off)
    return best_off, best_val


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------
class Result:
    pass


def detect(path: str, min_bpm: float, max_bpm: float,
           n_transients: int = 16) -> Result:
    x = decode_mono(path)
    duration = len(x) / SR
    env_rate = SR / HOP
    env = onset_envelope(x)
    if not env or duration < 2.0:
        sys.stderr.write("bpm_detect: %s is shorter than 2 s or undecodable\n" % path)
        raise SystemExit(3)
    if max(env) <= 1e-6:
        # Flat envelope: digital silence, or a dead/truncated render. 3.8
        # treats a -91 dB volumedetect reading as a STOP, and so does this.
        sys.stderr.write("bpm_detect: %s has a flat onset envelope -- silence "
                         "or a dead render. No tempo. STOP (3.8).\n" % path)
        raise SystemExit(3)

    min_lag = max(2, int(math.floor(60.0 * env_rate / max_bpm)))
    max_lag = int(math.ceil(60.0 * env_rate / min_bpm))
    max_lag = min(max_lag, len(env) - 2)
    if max_lag <= min_lag:
        sys.stderr.write("bpm_detect: %s is too short for the %.0f-%.0f BPM "
                         "search range\n" % (path, min_bpm, max_bpm))
        raise SystemExit(3)

    # autocorrelate out to 4x the slowest lag so the harmonic terms are real
    ctx = AcCtx(env)
    ac = autocorr(ctx, min_lag, min(4 * max_lag + 2, len(env) - 2))

    scores = [(harmonic_score(ac, float(lag)), lag)
              for lag in range(min_lag, max_lag + 1)]
    # local maxima of the harmonic score are the candidates
    cands = []
    for k in range(1, len(scores) - 1):
        if scores[k][0] >= scores[k - 1][0] and scores[k][0] > scores[k + 1][0]:
            cands.append(scores[k])
    if not cands:
        cands = [max(scores)]
    cands.sort(reverse=True)
    top = cands[:5]

    best_lag = top[0][1]
    fine_score = top[0][0]
    lag_final, order = refine_lag(ctx, best_lag)
    fine_bpm = 60.0 * env_rate / lag_final
    if not (min_bpm * 0.9 <= fine_bpm <= max_bpm * 1.1):  # refinement ran away
        lag_final, order = float(best_lag), 1
        fine_bpm = 60.0 * env_rate / lag_final
    peak = ac_at(ac, float(best_lag))
    # Contrast: the winning ACF peak against the mean ABSOLUTE autocorrelation
    # across the search range. A flat (tempo-less) autocorrelation gives ~1;
    # a real beat gives 3 and up. The mean of the *signed* harmonic score is
    # useless here -- it sits near zero and flips sign, which made this ratio
    # read -937 on a perfectly detected 88 BPM click track.
    in_range = [abs(ac[lag]) for lag in range(min_lag, max_lag + 1)]
    mean_abs = sum(in_range) / len(in_range)
    peak_to_mean = peak / mean_abs if mean_abs > EPS else 0.0

    # Margin: the winner against the best candidate that is NOT a simple
    # metrical relative of it. On a pad with no transients every candidate
    # scores about the same and this collapses to ~1.0; on a real beat the
    # winner is several times clear of the nearest unrelated lag. This is the
    # metric that catches non-percussive material -- peak height alone does
    # not, because the autocorrelation of a smooth tremolo is ALSO near 1.0.
    # 3/4 and 4/3 are in this list because of a real measurement: the delivered
    # bed throws up 74.90 / 99.86 / 149.80 BPM in EVERY 10 s window, a 3:4:6
    # family over one 0.2003 s atom -- a triple/shuffle feel. Without 3:4 the
    # song's own dotted relative counted as an unrelated rival and dragged the
    # verdict to LOW on a file that plainly has a stable tempo. The tolerance
    # is 2%, not 4%: at 4% the non-percussive pad's 0.772 rival was swallowed
    # by the 0.75 slot and the pad stopped being rejected.
    RELATED = (1.0, 0.5, 2.0, 1.5, 2.0 / 3.0, 3.0, 1.0 / 3.0, 4.0, 0.25,
               0.75, 4.0 / 3.0)
    coarse_bpm_win = 60.0 * env_rate / best_lag
    rival = 0.0
    for sc, lag in cands:
        ratio = (60.0 * env_rate / lag) / coarse_bpm_win
        if any(abs(ratio - m) < 0.02 * m for m in RELATED):
            continue
        rival = max(rival, sc)
    margin = fine_score / rival if rival > EPS else 99.0

    # Crest: how spiky the onset envelope is. Percussive material concentrates
    # its flux in a few frames; a pad spreads it evenly.
    env_mean = sum(env) / len(env)
    crest = (max(env) / env_mean) if env_mean > EPS else 0.0

    phase_frames, _ = best_phase(env, lag_final)
    transients = pick_transients(env, env_rate, max(8, n_transients))

    # cross-check: median inter-onset interval of the strongest transients,
    # folded onto the detected beat period
    iois = [b[0] - a[0] for a, b in zip(transients, transients[1:])]
    beat_period = 60.0 / fine_bpm
    folded = []
    for ioi in iois:
        ratio = ioi / beat_period
        nearest = round(ratio)
        if nearest >= 1:
            folded.append(abs(ratio - nearest))
    ioi_err = median(folded) if folded else 1.0

    if (peak >= 0.20 and peak_to_mean >= 3.0 and margin >= 1.50
            and ioi_err <= 0.08):
        verdict = "HIGH"
    elif peak >= 0.10 and peak_to_mean >= 2.0 and margin >= 1.15:
        verdict = "MEDIUM"
    else:
        verdict = "LOW"

    r = Result()
    r.path = path
    r.duration = duration
    r.env_rate = env_rate
    r.bpm = fine_bpm
    r.lag = lag_final
    r.peak = peak
    r.peak_to_mean = peak_to_mean
    r.margin = margin
    r.crest = crest
    r.verdict = verdict
    r.order = order
    r.ioi_err = ioi_err
    r.candidates = [(60.0 * env_rate / lag, lag, sc) for sc, lag in top]
    r.transients = transients
    r.phase_s = phase_frames / env_rate
    r.n_frames = len(env)
    return r


# --------------------------------------------------------------------------
# grid arithmetic -- 3.8 step 1 and step 4
# --------------------------------------------------------------------------
def _frame_row(name: str, t: float) -> tuple[str, dict]:
    row = "  %-26s" % name
    errs = {}
    for f in FPS_CANDIDATES:
        frames = t * f
        nearest = round(frames)
        signed_ms = (frames - nearest) / f * 1000.0
        errs[f] = abs(signed_ms)
        if abs(signed_ms) <= FRAME_TOL_MS:
            row += "  %10d OK " % nearest
        else:
            row += "  %8.2f %+5.1fms" % (frames, signed_ms)
    return row, errs


def grid_report(bpm: float, extra_cuts: list[float],
                transients: list[float] | None = None) -> str:
    """The arithmetic 3.8 steps 1 and 4 ask for.

    Two tables, deliberately kept apart. The MUSICAL PERIODS (beat, bar, line,
    six bars) are fractional at essentially every fps for essentially every
    tempo -- that is normal and 2.2 already handles it by cutting the audio bed
    at six bars and letting `-t 15.0` trim the video. Averaging those errors
    into the fps decision drowns it: on 95.80 BPM it recommends 60 fps, when
    the actual decision (does the 2.54 s slam land on a whole frame?) says 50.
    So the fps VERDICT is computed over the EDIT CUT POINTS only.
    """
    beat = 60.0 / bpm
    bar = 240.0 / bpm
    line = 2.0 * bar
    six = 6.0 * bar

    out = []
    out.append("")
    out.append("GRID -- derived from %.2f BPM, 4/4 (04_generation_plan.md 2.1)" % bpm)
    out.append("  beat            60 / BPM   = %9.6f s" % beat)
    out.append("  bar (4 beats)  240 / BPM   = %9.6f s" % bar)
    out.append("  barmoq line (2 bars)       = %9.6f s" % line)
    out.append("  six bars (6 x bar)         = %9.6f s" % six)
    out.append("")

    header = "  %-26s" % "" + "".join("  %14s" % ("@%d fps" % f)
                                      for f in FPS_CANDIDATES)
    rule = "  " + "-" * (26 + 16 * len(FPS_CANDIDATES))

    out.append("MUSICAL PERIODS -- informational. Fractional at every fps is NORMAL;")
    out.append("2.2 cuts the audio bed at six bars and lets -t 15.0 trim the video.")
    out.append(header)
    out.append(rule)
    for name, t in (("beat", beat), ("bar", bar),
                    ("barmoq line (2 bars)", line), ("six bars", six)):
        row, _ = _frame_row(name, t)
        out.append(row)
    out.append("")

    if extra_cuts:
        cuts = [("cut @ %.3f s" % t, t) for t in extra_cuts]
        source = "--cuts"
    elif transients:
        cuts = [("transient @ %.3f s" % t, t) for t in transients]
        source = "the strongest detected transients"
    else:
        cuts = []
        source = None
    cuts.append(("master 15.000 s", 15.0))

    out.append("EDIT CUT POINTS -- THIS is the fps decision (3.8 step 4).")
    if source is None:
        out.append("  No cut points given. Pass --cuts t1,t2,... with the times you")
        out.append("  re-derived from the transients; the fps verdict needs them.")
    else:
        out.append("  Cut points taken from %s." % source)
    out.append(header)
    out.append(rule)
    worst = {f: 0.0 for f in FPS_CANDIDATES}
    for name, t in cuts:
        row, errs = _frame_row(name, t)
        out.append(row)
        for f in FPS_CANDIDATES:
            worst[f] = max(worst[f], errs[f])
    out.append("")

    if source is None:
        out.append("  NO VERDICT: 15.000 s alone is an integer frame count at every")
        out.append("  fps, so it decides nothing. Supply --cuts.")
        out.append("")
        out.append("  Six bars = %.4f s = %.2f frames @ 50 fps. The video master stays "
                   "750 frames / 15.000 s:" % (six, six * 50))
        out.append("  cut the AUDIO BED at %.4f s, let -t 15.0 trim the video (2.2)."
                   % six)
        return "\n".join(out)

    best_fps = min(FPS_CANDIDATES, key=lambda f: (worst[f], -f))
    for f in FPS_CANDIDATES:
        mark = "  <== best" if f == best_fps else ""
        out.append("  worst-case error @%d fps: %6.2f ms%s" % (f, worst[f], mark))
    clean = [f for f in FPS_CANDIDATES if worst[f] <= FRAME_TOL_MS]
    if clean:
        out.append("  VERDICT: %s fps land every cut point on an integer frame. "
                   "2.2 takes the highest (%d)."
                   % (" / ".join(str(f) for f in clean), max(clean)))
    else:
        out.append("  VERDICT: NO fps lands every cut point on an integer frame.")
        out.append("  Take %d fps, snap each cut to its nearest frame, and "
                   "re-derive every" % best_fps)
        out.append("  segment length so they sum to a whole number of frames "
                   "(3.8 step 4).")
    out.append("")
    out.append("  Six bars = %.4f s = %.2f frames @ 50 fps. The video master stays "
               "750 frames / 15.000 s:" % (six, six * 50))
    out.append("  cut the AUDIO BED at %.4f s, let -t 15.0 trim the video (2.2)."
               % six)
    return "\n".join(out)


# --------------------------------------------------------------------------
# self-test -- synthesises its own ground truth, so no fixture lives in the repo
# --------------------------------------------------------------------------
def _synth(path: str, expr: str, dur: float = 24.0) -> None:
    ffmpeg = shutil.which("ffmpeg")
    subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "lavfi",
         "-i", "aevalsrc='%s':s=44100:d=%g" % (expr, dur),
         "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", path],
        check=True, capture_output=True)


def _click_expr(bpm: float, swing: bool = False, offbeat: bool = False) -> str:
    """A kick+click impulse train at `bpm`, built from ffmpeg's own eval.

    exp(-k*mod(t,P)) is a decaying envelope that restarts every P seconds, so
    multiplying it by a sine gives a percussive hit exactly every P seconds --
    ground truth to the sample.
    """
    p = 60.0 / bpm
    base = ("0.8*sin(2*PI*1400*t)*exp(-45*mod(t,%.9f)) + "
            "0.7*sin(2*PI*55*t)*exp(-18*mod(t,%.9f))" % (p, p))
    if swing:                       # off-beat at 2/3 of the beat, 2:1 swing
        o = p * 2.0 / 3.0
        base += (" + 0.45*sin(2*PI*2600*t)*"
                 "exp(-60*mod(max(0,t-%.9f),%.9f))" % (o, p))
    if offbeat:                     # identical hit on the "and", 12 dB LOUDER
        o = p / 2.0
        base = ("0.22*sin(2*PI*1400*t)*exp(-45*mod(t,%.9f)) + "
                "0.22*sin(2*PI*55*t)*exp(-18*mod(t,%.9f)) + "
                "0.88*sin(2*PI*1400*t)*exp(-45*mod(max(0,t-%.9f),%.9f)) + "
                "0.88*sin(2*PI*55*t)*exp(-18*mod(max(0,t-%.9f),%.9f))"
                % (p, p, o, p, o, p))
    return base


PAD_EXPR = ("(0.30*sin(2*PI*220*t)+0.22*sin(2*PI*277.18*t)+"
            "0.20*sin(2*PI*329.63*t))*(0.75+0.25*sin(2*PI*0.2*t))")


def selftest() -> int:
    """Regenerate ground truth with ffmpeg, detect it, and check the answers."""
    tmp = tempfile.mkdtemp(prefix="bpm_selftest_")
    failures = 0
    print("%-26s %10s %10s %9s %-8s %s"
          % ("case", "actual", "measured", "error", "conf", "check"))
    print("-" * 82)
    try:
        cases = []
        for bpm in (88.0, 95.8, 126.0):
            cases.append(("click %g BPM" % bpm, bpm, _click_expr(bpm), bpm, "any"))
        cases.append(("swung 95.8 (2:1)", 95.8, _click_expr(95.8, swing=True),
                      95.8, "any"))
        cases.append(("loud off-beat 95.8", 95.8, _click_expr(95.8, offbeat=True),
                      191.6, "any"))
        cases.append(("non-percussive pad", None, PAD_EXPR, None, "LOW"))
        for name, actual, expr, expect, want_conf in cases:
            path = os.path.join(tmp, name.replace(" ", "_") + ".wav")
            _synth(path, expr)
            r = detect(path, 60.0, 200.0)
            if expect is None:
                ok = (r.verdict == want_conf)
                print("%-26s %10s %10.2f %9s %-8s %s"
                      % (name, "n/a", r.bpm, "n/a", r.verdict,
                         "PASS (rejected)" if ok else "FAIL (not rejected)"))
            else:
                err = r.bpm - expect
                ok = abs(err) <= 0.5 and (want_conf == "any" or r.verdict == want_conf)
                print("%-26s %10.2f %10.2f %+9.3f %-8s %s"
                      % (name, actual, r.bpm, err, r.verdict,
                         "PASS" if ok else "FAIL (expected %.2f)" % expect))
            if not ok:
                failures += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 82)
    print("%d case(s) failed" % failures if failures else "all cases passed")
    return 1 if failures else 0


# --------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Pure-stdlib autocorrelation tempo detector (Step 0.5).")
    ap.add_argument("audio", nargs="?", help="any ffmpeg-readable audio/video file")
    ap.add_argument("--selftest", action="store_true",
                    help="synthesise click tracks of known tempo with ffmpeg, "
                         "detect them, and check the answers. Writes nothing "
                         "into the repo. Non-zero exit on failure.")
    ap.add_argument("--min-bpm", type=float, default=60.0)
    ap.add_argument("--max-bpm", type=float, default=200.0)
    ap.add_argument("--bpm", type=float, default=None,
                    help="skip detection, print the grid for this BPM")
    ap.add_argument("--cuts", default="",
                    help="comma-separated extra cut times in seconds")
    ap.add_argument("--transients", type=int, default=16,
                    help="how many strongest transients to list")
    ap.add_argument("--expect", type=float, default=None,
                    help="the BPM the plan assumed; prints the deviation and "
                         "checks the half/double relatives too (3.8)")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    extra = [float(v) for v in args.cuts.split(",") if v.strip()]

    if args.bpm is not None:
        print(grid_report(args.bpm, extra))
        return 0

    if not args.audio:
        ap.error("an audio file is required unless --bpm is given")

    r = detect(args.audio, args.min_bpm, args.max_bpm, args.transients)

    print("FILE      %s" % r.path)
    print("  duration        %.3f s   envelope %.2f Hz, %d frames"
          % (r.duration, r.env_rate, r.n_frames))
    print("")
    print("TEMPO     %.2f BPM        (beat %.6f s, lag %.3f envelope frames, "
          "refined on ACF peak x%d)" % (r.bpm, 60.0 / r.bpm, r.lag, r.order))
    print("CONFIDENCE %s" % r.verdict)
    print("  peak %.3f (want >=0.20)   peak/mean %.2f (want >=3.0)   "
          "margin over unrelated lag %.2f (want >=1.50)"
          % (r.peak, r.peak_to_mean, r.margin))
    print("  envelope crest %.1f   inter-onset disagreement %.3f beat (want <=0.08)"
          % (r.crest, r.ioi_err))
    if r.verdict == "LOW":
        print("  !! LOW means NO TEMPO FOUND. Do not re-derive a grid from this "
              "number -- see the failure modes in this script's docstring.")
    print("")
    print("TOP-5 CANDIDATE LAGS  (a half- or double-tempo read is visible here)")
    print("  %-8s %-10s %-10s %s" % ("BPM", "lag(frames)", "score", "relation to winner"))
    for idx, (bpm, lag, sc) in enumerate(r.candidates):
        ratio = bpm / r.bpm
        if idx == 0:
            rel = "<== WINNER"
        else:
            rel = ""
            for mult, label in ((0.5, "HALF of winner -- check this one"),
                                (2.0, "DOUBLE of winner -- check this one"),
                                (1.5, "3:2 of winner"), (0.6667, "2:3 of winner"),
                                (4.0, "4x winner"), (0.25, "quarter of winner"),
                                (3.0, "3x winner"), (0.3333, "third of winner"),
                                (0.75, "3:4 of winner (triple feel)"),
                                (1.3333, "4:3 of winner (triple feel)"),
                                (1.0, "within 2% of winner (same peak)")):
                if abs(ratio - mult) < 0.02 * mult:
                    rel = label
                    break
        print("  %-8.2f %-10.1f %-10.4f %s" % (bpm, lag, sc, rel))
    print("")
    print("STRONGEST TRANSIENTS  (re-cut the grid from these, not from the BPM alone)")
    print("  best beat phase: first beat at %.3f s, beats every %.6f s"
          % (r.phase_s, 60.0 / r.bpm))
    for t, s in r.transients[:args.transients]:
        beat_pos = (t - r.phase_s) / (60.0 / r.bpm)
        off = abs(beat_pos - round(beat_pos))
        flag = "on-beat" if off < 0.12 else ("off-beat %.2f" % (beat_pos - int(beat_pos)))
        print("  %8.3f s   strength %6.3f   beat %+8.2f   %s"
              % (t, s, beat_pos, flag))
    if args.expect is not None:
        print("")
        print("AGAINST THE PLAN'S ASSUMED %.2f BPM" % args.expect)
        for mult, name in ((1.0, "as measured"), (0.5, "half of measured"),
                           (2.0, "double of measured")):
            cand = r.bpm * mult
            dev = cand - args.expect
            pct = 100.0 * dev / args.expect
            verdict = "MATCHES" if abs(pct) <= 2.0 else "differs"
            print("  %-18s %8.2f BPM   %+7.2f BPM (%+6.2f%%)   %s"
                  % (name, cand, dev, pct, verdict))
        print("  If none of the three MATCHES, the grid in 2.4 is dead: "
              "re-derive it from the transients above before any video spend.")
    print(grid_report(r.bpm, extra, [t for t, _ in r.transients[:6]]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
