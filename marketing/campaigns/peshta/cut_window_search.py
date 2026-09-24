"""Cut-window search over a rendered song bed. Pure stdlib. Reads only; spends nothing.

Usage:
    .venv/bin/python marketing/campaigns/peshta/cut_window_search.py <raw-band-dir> [--profile] [--search]

The band .raw files are mono s16le @ 44100 produced by ffmpeg (see __main__ docstring).
Nothing here touches the mp3 itself.
"""

from __future__ import annotations

import array
import math
import sys
from pathlib import Path

SR = 44100
HOP = 0.010  # 10 ms analysis frame
FRAME = int(SR * HOP)  # 441 samples
BANDS = ("full", "sub", "lowmid", "vox", "high")


def load(path: Path) -> array.array:
    a = array.array("h")
    a.frombytes(path.read_bytes())
    if sys.byteorder == "big":
        a.byteswap()
    return a


def rms_db(samples: array.array) -> list[float]:
    out: list[float] = []
    n = len(samples)
    for start in range(0, n - FRAME + 1, FRAME):
        acc = 0
        for s in samples[start : start + FRAME]:
            acc += s * s
        r = math.sqrt(acc / FRAME) / 32768.0
        out.append(20.0 * math.log10(r) if r > 1e-9 else -180.0)
    return out


def load_bands(d: Path) -> dict[str, list[float]]:
    return {b: rms_db(load(d / f"{b}.raw")) for b in BANDS}


# ---------------------------------------------------------------- helpers


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else -180.0


def median(xs: list[float]) -> float:
    if not xs:
        return -180.0
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


def seg(env: list[float], t0: float, t1: float) -> list[float]:
    a, b = int(t0 / HOP), int(t1 / HOP)
    return env[max(0, a) : min(len(env), b)]


def onset_strength(env: list[float], lookback: int = 8, ahead: int = 3) -> list[float]:
    """dB rise of the next `ahead` frames over the previous `lookback` frames."""
    out = [0.0] * len(env)
    for i in range(lookback, len(env) - ahead):
        before = max(env[i - lookback : i])
        after = max(env[i : i + ahead + 1])
        out[i] = after - before
    return out


def peaks(strength: list[float], env: list[float], floor_db: float, min_gap: int = 12):
    """(time_s, rise_db, level_db) for local maxima of the onset function."""
    found = []
    i = 1
    while i < len(strength) - 1:
        if strength[i] >= strength[i - 1] and strength[i] > strength[i + 1] and strength[i] > 0:
            if env[i] >= floor_db:
                found.append((i * HOP, strength[i], env[i]))
                i += min_gap
                continue
        i += 1
    return found


# ---------------------------------------------------------------- profile


def profile(env: dict[str, list[float]]) -> None:
    n = len(env["full"])
    dur = n * HOP
    print(f"frames={n}  duration={dur:.2f}s  hop={HOP*1000:.0f}ms\n")
    for b in BANDS:
        e = env[b]
        print(
            f"{b:7s} min {min(e):7.1f}  p10 {pct(e,0.10):7.1f}  med {median(e):7.1f}  "
            f"p90 {pct(e,0.90):7.1f}  max {max(e):7.1f}  range(p10-p90) {pct(e,0.90)-pct(e,0.10):5.1f} dB"
        )
    print("\n0.25 s buckets — RMS dBFS per band (full / sub / lowmid / vox / high)")
    step = int(0.25 / HOP)
    for k in range(0, n, step):
        t = k * HOP
        row = [mean(env[b][k : k + step]) for b in BANDS]
        bar = "#" * max(0, int((row[0] + 60) / 1.5))
        print(
            f"{t:6.2f}  {row[0]:6.1f} {row[1]:6.1f} {row[2]:6.1f} {row[3]:6.1f} {row[4]:6.1f}  {bar}"
        )

    print("\nSUB-BAND ONSETS (impact candidates) — rise over prior 80 ms")
    st = onset_strength(env["sub"])
    for t, rise, lvl in sorted(peaks(st, env["sub"], floor_db=-40.0), key=lambda x: -x[1])[:25]:
        print(f"  t={t:6.3f}  rise={rise:5.1f} dB  sub_level={lvl:6.1f} dBFS")

    print("\nFULL-BAND ONSETS")
    st = onset_strength(env["full"])
    for t, rise, lvl in sorted(peaks(st, env["full"], floor_db=-45.0), key=lambda x: -x[1])[:25]:
        print(f"  t={t:6.3f}  rise={rise:5.1f} dB  level={lvl:6.1f} dBFS")


# ---------------------------------------------------------------- search

WIN = 15.0313  # six bars @ 95.8 BPM, the plan's audio-bed length (2.2)

# Structure slots, offsets from window start, per 2.4.
SLOT_COLD = (0.00, 1.60)
SLOT_VAC = (1.60, 2.53)
SLAM_T = 2.540
SLOT_DANCE = (2.54, 8.00)
SLOT_CALM = (8.00, 11.50)
SLOT_CAD = (11.50, 15.0313)


def score_window(env: dict[str, list[float]], w: float, ref: dict[str, float]) -> dict:
    f, sub, hi = env["full"], env["sub"], env["high"]
    sub_on = env["_sub_onset"]
    full_on = env["_full_onset"]

    cold = seg(f, w + SLOT_COLD[0], w + SLOT_COLD[1])
    vac_sub = seg(sub, w + SLOT_VAC[0], w + SLOT_VAC[1])
    vac_full = seg(f, w + SLOT_VAC[0], w + SLOT_VAC[1])
    dance = seg(f, w + SLOT_DANCE[0], w + SLOT_DANCE[1])
    calm = seg(f, w + SLOT_CALM[0], w + SLOT_CALM[1])
    cad = seg(f, w + SLOT_CAD[0], w + SLOT_CAD[1])

    # 1. cold open headroom: how far below the track's loud passages it sits
    cold_q = ref["p90"] - median(cold)

    # 2. vacuum authorability: there must be sub energy to remove, and no transient
    #    inside the window that the duck would destroy
    vac_sub_lvl = median(vac_sub)
    vac_have = max(0.0, vac_sub_lvl - ref["sub_p10"])
    i0, i1 = int((w + SLOT_VAC[0]) / HOP), int((w + SLOT_VAC[1]) / HOP)
    vac_intrusion = max(sub_on[i0:i1] or [0.0])

    # 3. slam: strongest sub onset within +-60 ms of w+2.54
    ic = int((w + SLAM_T) / HOP)
    lo, hi_i = max(0, ic - 6), min(len(sub_on), ic + 7)
    slam_rise = max(sub_on[lo:hi_i] or [0.0])
    slam_full = max(full_on[lo:hi_i] or [0.0])
    slam_lvl = max(sub[lo:hi_i] or [-180.0])
    # 3b. FLEXIBLE slam — 2.3 says the 2.4 grid is provisional and re-derived from real
    #     transients, so also find the best impact anywhere in +1.9 .. +3.6 s.
    fa, fb = int((w + 1.90) / HOP), int((w + 3.60) / HOP)
    band = sub_on[max(0, fa) : min(len(sub_on), fb)]
    flex_rise = max(band) if band else 0.0
    flex_off = (band.index(flex_rise) + fa) * HOP - w if band else 0.0
    # step across the boundary: how much louder the dance is than the vacuum
    slam_step = median(seg(f, w + 2.54, w + 3.04)) - median(vac_full)

    # 4. dance: loud and sustained, no long holes
    dance_lvl = median(dance)
    dance_floor = pct(dance, 0.10)
    dance_sag = dance_lvl - dance_floor

    # 5. calm: measurably below the dance but not dead
    calm_lvl = median(calm)
    calm_drop = dance_lvl - calm_lvl

    # 6. cadence + loop seam: last 0.5 s vs first 0.5 s, level and spectral tilt
    head = seg(f, w, w + 0.5)
    tail = seg(f, w + WIN - 0.5, w + WIN)
    seam_lvl = abs(median(head) - median(tail))
    head_tilt = median(seg(hi, w, w + 0.5)) - median(head)
    tail_tilt = median(seg(hi, w + WIN - 0.5, w + WIN)) - median(tail)
    seam_tilt = abs(head_tilt - tail_tilt)
    cad_lvl = median(cad)
    # outro-fade contamination: fraction of the cadence slot below the track's own p10
    fade_contam = (sum(1 for x in cad if x < ref["p10"]) / len(cad)) if cad else 1.0

    # ---- points (each 0..1, then weighted)
    p_cold = min(1.0, max(0.0, cold_q / 12.0))
    p_vac = min(1.0, vac_have / 12.0) * (1.0 if vac_intrusion < 6.0 else 0.4)
    p_slam = min(1.0, max(0.0, slam_rise / 10.0)) * 0.6 + min(
        1.0, max(0.0, slam_step / 8.0)
    ) * 0.4
    p_dance = min(1.0, max(0.0, (dance_lvl - ref["med"] + 3.0) / 6.0)) * (
        1.0 if dance_sag < 8.0 else 0.5
    )
    p_calm = min(1.0, max(0.0, calm_drop / 5.0))
    p_loop = min(1.0, max(0.0, 1.0 - seam_lvl / 8.0)) * 0.6 + min(
        1.0, max(0.0, 1.0 - seam_tilt / 8.0)
    ) * 0.4

    p_slam_flex = min(1.0, max(0.0, flex_rise / 10.0)) * 0.6 + min(
        1.0, max(0.0, slam_step / 8.0)
    ) * 0.4
    p_fade = 1.0 - fade_contam

    total = (
        2.0 * p_cold
        + 1.5 * p_vac
        + 3.0 * p_slam
        + 2.0 * p_dance
        + 1.5 * p_calm
        + 1.0 * p_loop
        + 1.0 * p_fade
    )
    total_flex = total - 3.0 * p_slam + 3.0 * p_slam_flex
    return dict(
        w=w,
        total=total,
        total_flex=total_flex,
        p_slam_flex=p_slam_flex,
        p_fade=p_fade,
        flex_rise=flex_rise,
        flex_off=flex_off,
        fade_contam=fade_contam,
        p_cold=p_cold,
        p_vac=p_vac,
        p_slam=p_slam,
        p_dance=p_dance,
        p_calm=p_calm,
        p_loop=p_loop,
        cold_q=cold_q,
        vac_sub_lvl=vac_sub_lvl,
        vac_intrusion=vac_intrusion,
        slam_rise=slam_rise,
        slam_full=slam_full,
        slam_lvl=slam_lvl,
        slam_step=slam_step,
        dance_lvl=dance_lvl,
        dance_sag=dance_sag,
        calm_lvl=calm_lvl,
        calm_drop=calm_drop,
        cad_lvl=cad_lvl,
        seam_lvl=seam_lvl,
        seam_tilt=seam_tilt,
    )


def search(env: dict[str, list[float]], step: float = 0.05) -> None:
    env["_sub_onset"] = onset_strength(env["sub"])
    env["_full_onset"] = onset_strength(env["full"])
    f = env["full"]
    ref = dict(
        med=median(f),
        p90=pct(f, 0.90),
        p10=pct(f, 0.10),
        sub_p10=pct(env["sub"], 0.10),
        sub_med=median(env["sub"]),
    )
    print("reference levels:", {k: round(v, 2) for k, v in ref.items()})
    dur = len(f) * HOP
    last = dur - WIN
    print(f"sliding {WIN:.4f}s window from 0.000 to {last:.3f} in {step*1000:.0f} ms steps")
    results = []
    w = 0.0
    while w <= last + 1e-9:
        results.append(score_window(env, w, ref))
        w += step
    for key, label in (("total", "STRICT slam at +2.540"), ("total_flex", "FLEXIBLE slam in +1.9..+3.6")):
        results.sort(key=lambda r: -r[key])
        sk = "p_slam" if key == "total" else "p_slam_flex"
        print(f"\n=== ranked by {label} === (max 12.0)\n")
        for r in results[:12]:
            extra = "" if key == "total" else f" @+{r['flex_off']:.2f}s"
            print(
                f"start {r['w']:6.3f}  TOTAL {r[key]:5.2f} | cold {r['p_cold']:.2f} "
                f"vac {r['p_vac']:.2f} slam {r[sk]:.2f}{extra} dance {r['p_dance']:.2f} "
                f"calm {r['p_calm']:.2f} loop {r['p_loop']:.2f} fade {r['p_fade']:.2f}"
            )
    results.sort(key=lambda r: -r["total_flex"])
    print("\ndetail of top 3 (flexible):")
    for r in results[:3]:
        print(f"\n  window start {r['w']:.3f}s  ->  {r['w']+WIN:.3f}s   total {r['total']:.2f}")
        for k in (
            "cold_q",
            "vac_sub_lvl",
            "vac_intrusion",
            "slam_rise",
            "slam_full",
            "slam_lvl",
            "slam_step",
            "dance_lvl",
            "dance_sag",
            "calm_lvl",
            "calm_drop",
            "cad_lvl",
            "seam_lvl",
            "seam_tilt",
            "flex_rise",
            "flex_off",
            "fade_contam",
        ):
            print(f"      {k:14s} {r[k]:7.2f}")
    # spread across the file, so a flat render is visible
    print("\nscore spread (all windows): "
          f"min {min(x['total'] for x in results):.2f}  "
          f"med {median([x['total'] for x in results]):.2f}  "
          f"max {max(x['total'] for x in results):.2f}")


if __name__ == "__main__":
    d = Path(sys.argv[1])
    env = load_bands(d)
    if "--profile" in sys.argv:
        profile(env)
    if "--search" in sys.argv:
        search(env)
