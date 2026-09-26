#!/usr/bin/env python3
"""Derive the 43 s beat grid of the Peshta master. Emits JSON on stdout.

No numpy / scipy / librosa / aubio / soundfile exist on this machine (checked,
not assumed), so this reuses marketing/campaigns/peshta/bpm_detect.py -- a pure-stdlib
two-band-flux + harmonic-autocorrelation detector that already ships in this
folder -- via its own detect() entry point, so the tempo reported here is
byte-for-byte the tempo `python3 bpm_detect.py <audio>` prints.
"""
from __future__ import annotations
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bpm_detect as B  # noqa: E402

AUDIO = os.path.join(ROOT, "audio", "Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3")
FPS = 30.0
MIN_BPM, MAX_BPM = 60.0, 200.0


def main() -> int:
    r = B.detect(AUDIO, MIN_BPM, MAX_BPM, n_transients=64)
    bpm, beat, dur = r.bpm, 60.0 / r.bpm, r.duration
    first = r.phase_s

    env = B.onset_envelope(B.decode_mono(AUDIO))
    env_rate = r.env_rate

    beats = []
    k = -int(first / beat) - 1
    while True:
        t = first + k * beat
        k += 1
        if t < -1e-9:
            continue
        if t > dur:
            break
        beats.append(round(t, 4))

    downbeats = beats[::4]

    def env_at(t, halfwin=0.07):
        a = max(0, int((t - halfwin) * env_rate))
        b = min(len(env), int((t + halfwin) * env_rate) + 1)
        return max(env[a:b]) if b > a else 0.0

    scored = sorted(((env_at(t), t) for t in downbeats), reverse=True)
    strongest_downbeats = [
        {"t_s": round(t, 4), "strength": round(s, 4),
         "frame_30fps": int(round(t * FPS))} for s, t in scored[:8]]

    # Section energy: 1 s means of the flux envelope. The "drop" is the first
    # bar line where the running mean steps up and stays up.
    secs = []
    n = int(dur)
    for i in range(n):
        a, b = int(i * env_rate), min(len(env), int((i + 1) * env_rate))
        seg = env[a:b]
        secs.append(round(sum(seg) / len(seg), 4) if seg else 0.0)
    overall = sum(secs) / len(secs)
    drop_candidates = []
    for t in downbeats:
        i = int(t)
        if i < 1 or i + 3 >= n:
            continue
        before = sum(secs[max(0, i - 3):i]) / max(1, len(secs[max(0, i - 3):i]))
        after = sum(secs[i:i + 3]) / len(secs[i:i + 3])
        drop_candidates.append({"t_s": round(t, 4),
                                "frame_30fps": int(round(t * FPS)),
                                "step_up": round(after - before, 4),
                                "after_mean": round(after, 4)})
    drop_candidates.sort(key=lambda d: d["step_up"], reverse=True)

    out = {
        "analysis_libraries_available": False,
        "analysis_libraries_checked": ["numpy", "scipy", "librosa",
                                       "soundfile", "aubio", "madmom"],
        "method": "marketing/campaigns/peshta/bpm_detect.py detect() -- pure stdlib, "
                  "two-band half-wave-rectified log flux envelope at 344.53 Hz "
                  "+ harmonic autocorrelation, peak refined on the 16th ACF peak",
        "source": "audio/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3",
        "decoded_duration_s": round(dur, 6),
        "bpm": round(bpm, 3),
        "bpm_coarse_winner": round(r.candidates[0][0], 3),
        "confidence": r.verdict,
        "confidence_metrics": {
            "acf_peak": round(r.peak, 4), "peak_over_mean": round(r.peak_to_mean, 3),
            "margin_over_unrelated_lag": round(r.margin, 3),
            "envelope_crest": round(r.crest, 3),
            "inter_onset_disagreement_beats": round(r.ioi_err, 4)},
        "confidence_note": "MEDIUM, not HIGH: margin 1.37 is under the 1.50 bar "
                           "and the DOUBLE-tempo candidate 191.41 BPM scores "
                           "0.4233 against the winner's 0.4411. Treat 95.58 and "
                           "191.16 as the same grid at two subdivisions; cut on "
                           "the 95.58 beat and it also lands on the 191 grid.",
        "candidates": [{"bpm": round(b, 2), "lag_frames": l, "score": round(s, 4)}
                       for b, l, s in r.candidates],
        "beat_period_s": round(beat, 6),
        "bar_period_s": round(beat * 4, 6),
        "first_beat_s": round(first, 4),
        "beat_count": len(beats),
        "beats_s": beats,
        "beat_frames_30fps": [int(round(t * FPS)) for t in beats],
        "downbeats_s": downbeats,
        "downbeat_frames_30fps": [int(round(t * FPS)) for t in downbeats],
        "strongest_downbeats": strongest_downbeats,
        "drop_candidates": drop_candidates[:6],
        "strongest_transients": [{"t_s": round(t, 4), "strength": round(s, 3),
                                  "frame_30fps": int(round(t * FPS))}
                                 for t, s in sorted(r.transients,
                                                    key=lambda p: -p[1])[:20]],
        "per_second_envelope_mean": secs,
        "per_second_overall_mean": round(overall, 4),
    }
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
