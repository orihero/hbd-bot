#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
marketing/campaigns/peshta/qa_gate.py — the automated half of 04_generation_plan.md section 8.

Run with the repository venv, which is the only python on this box that has PIL:

    .venv/bin/python marketing/campaigns/peshta/qa_gate.py
    .venv/bin/python marketing/campaigns/peshta/qa_gate.py <master.mp4> --cards <dir>

EXIT 0 only when every machine-checkable gate passed. EXIT 1 on ANY failure, on a
missing input, or on an internal error. Gates that need a human eye or a native
speaker are printed as SKIPPED-HUMAN and are never counted as passes.

Design rules this file obeys, each one earned the hard way (section 8, section 7.5):

  * ONE SPEC dict. Every expected number lives in it. No literal thresholds in the
    gate bodies. section 12: the discarded harness hardcoded `assert len(packets) == 151`
    and so encoded the failure as a pass.
  * ffmpeg on this box is 9.0.1. `-vsync` was REMOVED in 9.x -- this file uses
    `-fps_mode`. Verified: `-vsync 0` dies with "Unrecognized option 'vsync'".
  * `volumedetect` and `loudnorm` print at AV_LOG_INFO. `-v error` swallows their
    numbers ENTIRELY, so the gate would match nothing and fall through green on any
    input. Commands that are parsed here therefore never carry `-v error`, and an
    empty match is a FAIL, never a pass.
  * ffprobe needs `-select_streams v:0`. Without it the audio stream's r_frame_rate
    and nb_frames are printed AFTER the video stream's, and the natural key=value
    parse keeps the audio row -- reporting FAIL on a correctly built master.
    Verified on this box against the discarded clip: the unselected command emits
    `nb_frames=151` then `nb_frames=236`.
  * EVERY frame extraction deletes the target first and asserts it was recreated
    non-empty. Seeking past EOF makes ffmpeg EXIT 0 having written nothing
    (verified: `-ss 900` on a 5.03 s file, exit 0, no file), so a leftover PNG from
    a previous run would otherwise be measured instead of the current one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

# --------------------------------------------------------------------------- #
#  THE SPEC. Everything the gate expects lives here and nowhere else.
# --------------------------------------------------------------------------- #

# Uzbek marks as explicit escapes, so nothing depends on this file's encoding
# round-tripping through an editor (section 7.4).
TC = "\u02bb"  # MODIFIER LETTER TURNED COMMA      -- the mark in o+TC and g+TC
MC = "\u02bc"  # MODIFIER LETTER APOSTROPHE
NBSP = "\u00a0"  # NO-BREAK SPACE                  -- the price grouping separator
ASCII_APOS = "\u0027"  # the one that must never appear
RSQUO = "\u2019"  # RIGHT SINGLE QUOTATION MARK    -- the other common wrong mark

SPEC = {
    # ---- inputs -----------------------------------------------------------
    "master": "marketing/campaigns/peshta/variant_d_final.mp4",
    "cards_dir": "marketing/campaigns/peshta/cards",
    "strings_name": "strings.txt",
    # ---- G0: what the assembly chain in section 7.5 actually needs ---------
    "ffmpeg": {
        "required_filters": [
            "overlay", "concat", "loudnorm", "zoompan", "highpass", "volume",
            "scale", "crop", "fps", "setsar", "format", "afade",
            "alphaextract", "atrim", "lowpass", "volumedetect", "ebur128",
        ],
        # section 7.1: drawtext MISSING is EXPECTED on the slim Homebrew formula.
        # If any command in the plan uses one of these, the PLAN is wrong, not the box.
        "expected_missing": ["drawtext", "subtitles", "ass", "zscale"],
        "required_encoders": ["libx264", "aac", "pcm_s16le", "png"],
        # section 7.5(b) leans on these being timeline-enabled; section 7.5(d) leans on
        # zoompan NOT being, which is why fps=50 goes INSIDE the filter.
        "timeline_required": ["volume", "highpass", "overlay", "lowpass"],
        "timeline_absent": ["zoompan"],
    },
    # ---- G1: container geometry -------------------------------------------
    "video": {
        "width": 1080,
        "height": 1920,
        "r_frame_rate": "50/1",
        "nb_frames": 750,
        "fps": 50,
        "duration_s": 15.0,
        "duration_tol_s": 0.002,
    },
    # ---- G3: loudness on the FINAL MUX, never the intermediate wav ---------
    "loudness": {"target_i": -14.0, "tol_i": 0.5, "max_tp_dbtp": -1.0},
    # ---- G4: the authored sub-bass vacuum, 1.60-2.53 s ---------------------
    "vacuum": {
        "window": (1.70, 2.40),      # inside the dropout, clear of both edges
        "reference": (3.00, 4.00),   # the bounce, sub fully present
        "lowpass_hz": 200,
        "min_drop_db": 20.0,
    },
    # ---- G5a: safe zone (section 7.3; the box is ASYMMETRIC about x=540) ---
    "safe_zone": {
        "y_min": 220, "y_max": 1500,
        "x_min": 40, "x_max": 940,
        "alpha_threshold": 8,
        "skip": {"c9"},  # deliberate full-frame flash; its alpha IS the canvas
    },
    # ---- G5b: the glyph floor (section 7.3; TWO numbers, not one) ----------
    "glyph": {
        "min_em_px": 76,
        "min_cap_px": 53,
        "exempt": {"c7", "c9"},  # persistent 48 pt pill, and the flash
        "cap_probe": "A",
        "font_candidates": [
            os.path.expanduser("~/Library/Fonts/Montserrat-ExtraBold.ttf"),
            "/Library/Fonts/Arial Unicode.ttf",
        ],
    },
    # ---- the nine cards: windows in MASTER FRAMES, per section 2.4 ---------
    # `windows` are INCLUSIVE frame ranges. section 7.5(h)'s `enable` expressions
    # pull every interior upper bound back half a frame precisely so that the last
    # ENABLED frame is the `last` written here.
    "cards": {
        "c1": {"windows": [(0, 126)],    "pt": 79, "key_rgb": (0xFF, 0xE6, 0x00)},
        "c2": {"windows": [(80, 126)],   "pt": 84, "key_rgb": (0xFF, 0xE6, 0x00)},
        "c3": {"windows": [(127, 217)],  "pt": 83, "key_rgb": (0xFF, 0xE6, 0x00)},
        "c4": {"windows": [(218, 399)],  "pt": 80, "key_rgb": (0xFF, 0xD7, 0x00)},
        "c5": {"windows": [(400, 524)],  "pt": 76, "key_rgb": (0x00, 0xC8, 0x53)},
        "c6": {"windows": [(575, 749)],  "pt": 80, "key_rgb": (0xFF, 0xE6, 0x00)},
        "c7": {"windows": [(145, 749)],  "pt": 48, "key_rgb": (0x00, 0x88, 0xCC)},
        "c8": {"windows": [(420, 749)],  "pt": 76, "key_rgb": (0x00, 0xC8, 0x53)},
        "c9": {"windows": [(217, 218), (308, 309), (661, 662)],
               "pt": None, "key_rgb": (0xFF, 0xFF, 0xFF)},
    },
    # ---- G6: is the card actually on screen in its window? ----------------
    "presence": {
        "colour_tol": 32,        # yuv420p round-trip shifts saturated colour
        "min_fraction": 0.30,    # of the key-colour pixel count in the card PNG itself
        "skip": {"c9"},          # 2-frame flash: G6 samples a window midpoint
    },
    # ---- G9: the slam. 2.54 s x 50 fps = frame 127, exactly ---------------
    "slam": {
        "frame": 127,
        "min_cut_delta": 8.0,   # mean |dRGB| across the cut
        "min_cut_ratio": 2.0,   # ...and it must dominate the neighbouring step
    },
    # ---- G16: funnel exposure, recomputed from the card windows above -----
    "funnel": {
        "handle": {"cards": ["c7", "c6"], "newest": "c6",
                   "min_frames": 500, "min_newest_frames": 125},
        "price": {"cards": ["c8"], "min_frames": 250},
        "problem": {"cards": ["c1"], "max_first_frame": 80},
    },
    # ---- G17: the loop seam ----------------------------------------------
    "loop": {"frame_a": 0, "frame_b": 749, "max_mean_rgb_delta": 20.0},
    # ---- G14: character integrity on cards/strings.txt --------------------
    "strings": {
        "max_ascii_apostrophes": 0,
        "min_nbsp": 1,
        "forbidden_marks": {ASCII_APOS: "U+0027 ASCII APOSTROPHE",
                            RSQUO: "U+2019 RIGHT SINGLE QUOTATION MARK"},
    },
    # ---- gates no machine can sign off -----------------------------------
    "human_gates": {
        "G7":  "No AI-rendered text in frame -- inspect every keyframe at full size, "
               "then 8 sampled frames of the master. ZERO glyphs that did not come "
               "from a card PNG or the real screen recording at 9.00-10.50 s.",
        "G10": "Mute-readability -- play at 0% volume on a phone. Problem by 1.0 s, "
               "solution by 3.0 s, handle AND price legible before the end.",
        "G11": "Handset safe zone -- AirDrop to a 6.1\" AND a 6.7\" handset and "
               "overlay a real TikTok and a real Reels UI screenshot.",
        "G12": "Full-volume speaker -- 100% on a handset: the 808 punches without "
               "buzzing the grille; lyrics stay intelligible.",
        "G13": "Cultural / linguistic sign-off -- a native Uzbek reviewer reads the "
               "complete final string set against section 8's nine flagged items. "
               "Happens BEFORE any card is rendered.",
        "G15": "Handle routing -- tap the ?start=ig_peshta deep link from an "
               "Instagram DM, and search 'bayram bot' in Telegram; record honestly.",
    },
    # G9's numeric half is automated below; this half is not.
    "human_subchecks": {
        "G9":  "the change at frame 127 must be the WARDROBE/SET change, not any "
               "other motion -- eyeball frames 126/127/128.",
        "G17": "after the numeric seam check, watch it loop three times without "
               "touching the screen and confirm the seam is invisible.",
    },
}

# --------------------------------------------------------------------------- #
#  plumbing
# --------------------------------------------------------------------------- #

RESULTS: list[tuple[str, str, str]] = []  # (status, gate, message)
_PASS, _FAIL, _HUMAN, _INFO = "PASS", "FAIL", "SKIPPED-HUMAN", "INFO"


def record(status: str, gate: str, message: str) -> None:
    RESULTS.append((status, gate, message))
    tag = {_PASS: "[ PASS ]", _FAIL: "[ FAIL ]",
           _HUMAN: "[HUMAN ]", _INFO: "[ info ]"}[status]
    print(f"{tag} {gate:<4} {message}", flush=True)


def ok(gate: str, msg: str) -> None:
    record(_PASS, gate, msg)


def bad(gate: str, msg: str) -> None:
    record(_FAIL, gate, msg)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def extract_frame(master: str, n: int, dest: str) -> str | None:
    """Delete-then-assert. Returns None on success, or an operator-readable reason.

    Seeking past EOF makes ffmpeg EXIT 0 having written nothing, so `check=True`
    alone would let a stale PNG from a previous run be measured instead. Verified
    on this box: `-ss 900` against a 5.03 s file exits 0 and writes no file.
    """
    if os.path.exists(dest):
        os.remove(dest)
    proc = run([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y",
        "-i", master,
        "-vf", f"select='eq(n\\,{n})'",
        "-fps_mode", "passthrough",      # -vsync was REMOVED in ffmpeg 9.x
        "-frames:v", "1",
        dest,
    ])
    if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
        err = (proc.stderr or "").strip().splitlines()
        return (f"no frame {n} written (ffmpeg exit={proc.returncode}"
                f"{'; ' + err[-1] if err else ''}) -- the file has fewer than "
                f"{n + 1} frames")
    return None


def mean_rgb(path: str) -> tuple[float, float, float]:
    from PIL import Image, ImageStat
    with Image.open(path) as im:
        m = ImageStat.Stat(im.convert("RGB")).mean
    return (m[0], m[1], m[2])


def count_colour(im, rgb: tuple[int, int, int], tol: int, alpha_min: int | None = None) -> int:
    """Count pixels within `tol` of `rgb` on every channel. PIL-only, C-speed."""
    from PIL import ImageChops
    bands = im.split()
    masks = []
    for ch, want in zip(bands[:3], rgb):
        masks.append(ch.point(lambda p, w=want: 255 if abs(p - w) <= tol else 0))
    if alpha_min is not None and im.mode == "RGBA":
        masks.append(bands[3].point(lambda p, a=alpha_min: 255 if p > a else 0))
    m = masks[0]
    for other in masks[1:]:
        m = ImageChops.multiply(m, other)
    return m.convert("L").histogram()[255]


def frames_of(card: str) -> set[int]:
    s: set[int] = set()
    for a, b in SPEC["cards"][card]["windows"]:
        s.update(range(a, b + 1))
    return s


# --------------------------------------------------------------------------- #
#  G0 -- ffmpeg capability
# --------------------------------------------------------------------------- #

def gate_G0() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        bad("G0", "ffmpeg/ffprobe not on PATH")
        return
    ver = run(["ffmpeg", "-hide_banner", "-version"]).stdout.splitlines()[0]
    spec = SPEC["ffmpeg"]
    missing, present_but_should_be_absent = [], []

    for f in spec["required_filters"]:
        h = run(["ffmpeg", "-hide_banner", "-h", f"filter={f}"])
        if "Unknown filter" in (h.stdout + h.stderr):
            missing.append(f)
    for f in spec["expected_missing"]:
        h = run(["ffmpeg", "-hide_banner", "-h", f"filter={f}"])
        if "Unknown filter" not in (h.stdout + h.stderr):
            present_but_should_be_absent.append(f)

    enc_missing = []
    for e in spec["required_encoders"]:
        h = run(["ffmpeg", "-hide_banner", "-h", f"encoder={e}"])
        if "is not recognized" in (h.stdout + h.stderr) or "Codec '" in (h.stderr or ""):
            enc_missing.append(e)

    tl_bad = []
    for f in spec["timeline_required"]:
        h = run(["ffmpeg", "-hide_banner", "-h", f"filter={f}"])
        if "support for timeline" not in h.stdout:
            tl_bad.append(f"{f} has NO timeline support (section 7.5 needs enable=)")
    for f in spec["timeline_absent"]:
        h = run(["ffmpeg", "-hide_banner", "-h", f"filter={f}"])
        if "support for timeline" in h.stdout:
            tl_bad.append(f"{f} unexpectedly HAS timeline support")

    demux = run(["ffmpeg", "-hide_banner", "-demuxers"]).stdout
    if not re.search(r"^\s*D\s+concat\s", demux, re.M):
        missing.append("concat demuxer")

    if missing or enc_missing or tl_bad:
        bad("G0", f"{ver} | missing filters: {missing or 'none'} | "
                  f"missing encoders: {enc_missing or 'none'} | "
                  f"timeline: {tl_bad or 'ok'}")
    else:
        ok("G0", f"{ver} | all {len(spec['required_filters'])} filters + "
                 f"{len(spec['required_encoders'])} encoders present; "
                 f"timeline flags as section 7.5 assumes")
    if present_but_should_be_absent:
        record(_INFO, "G0", f"present but section 7.1 expected MISSING: "
                            f"{present_but_should_be_absent} -- harmless; the plan "
                            f"composites PIL PNGs and must not start using them")
    else:
        record(_INFO, "G0", f"MISSING as section 7.1 expects: {spec['expected_missing']} "
                            f"-- this build cannot burn text; PIL owns typography")


# --------------------------------------------------------------------------- #
#  G1 -- container geometry
# --------------------------------------------------------------------------- #

def gate_G1(master: str) -> dict | None:
    if not os.path.exists(master):
        bad("G1", f"master does not exist: {master}")
        return None
    if os.path.getsize(master) == 0:
        bad("G1", f"master is a zero-byte file: {master}")
        return None

    proc = run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",          # LOAD-BEARING, see the module docstring
        "-show_entries", "format=duration",
        "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
        "-of", "default=noprint_wrappers=1",
        master,
    ])
    if proc.returncode != 0 or not proc.stdout.strip():
        err = (proc.stderr or "").strip().splitlines()
        bad("G1", f"ffprobe could not read it as a video (exit={proc.returncode}): "
                  f"{err[-1] if err else 'no output'}")
        return None

    got: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            got[k.strip()] = v.strip()

    if "width" not in got:
        bad("G1", f"no video stream found in {master} (ffprobe returned: "
                  f"{list(got) or 'nothing'})")
        return None

    v = SPEC["video"]
    problems = []
    for key, want in (("width", v["width"]), ("height", v["height"]),
                      ("r_frame_rate", v["r_frame_rate"]), ("nb_frames", v["nb_frames"])):
        have = got.get(key, "<absent>")
        if str(have) != str(want):
            problems.append(f"{key}={have}, expected {want}")
    try:
        dur = float(got.get("duration", "nan"))
    except ValueError:
        dur = float("nan")
    if not abs(dur - v["duration_s"]) <= v["duration_tol_s"]:
        problems.append(f"duration={got.get('duration', '<absent>')}, expected "
                        f"{v['duration_s']:.6f} +/- {v['duration_tol_s']}")

    if problems:
        bad("G1", "; ".join(problems))
    else:
        ok("G1", f"{got['width']}x{got['height']} @ {got['r_frame_rate']}, "
                 f"nb_frames={got['nb_frames']}, duration={got['duration']}")
    return got


# --------------------------------------------------------------------------- #
#  G2 / G3 / G8 -- decode, loudness, faststart
# --------------------------------------------------------------------------- #

def gate_G2(master: str) -> None:
    proc = run(["ffmpeg", "-v", "warning", "-err_detect", "explode",
                "-i", master, "-f", "null", "-"])
    noise = (proc.stderr or "").strip()
    if proc.returncode != 0 or noise:
        first = noise.splitlines()[0] if noise else f"exit={proc.returncode}"
        bad("G2", f"decode was not clean: {first}")
    else:
        ok("G2", "full decode with -err_detect explode produced no stderr at all")


def gate_G3(master: str) -> None:
    # NO -v error: ebur128's Summary block prints at AV_LOG_INFO.
    proc = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", master,
                "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    out = proc.stdout + proc.stderr
    tail = out.split("Summary:", 1)[-1] if "Summary:" in out else ""
    mi = re.search(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", tail, re.M)
    mp = re.search(r"^\s*Peak:\s*(-?[\d.]+)\s*dBFS", tail, re.M)
    if not mi or not mp:
        bad("G3", "no ebur128 Summary parsed -- no audio stream, or the summary was "
                  "suppressed (never pass -v error to a command you parse)")
        return
    i_val, tp_val = float(mi.group(1)), float(mp.group(1))
    ld = SPEC["loudness"]
    problems = []
    if abs(i_val - ld["target_i"]) > ld["tol_i"]:
        problems.append(f"I={i_val} LUFS, want {ld['target_i']} +/- {ld['tol_i']}")
    if tp_val > ld["max_tp_dbtp"]:
        problems.append(f"true peak={tp_val} dBTP, ceiling {ld['max_tp_dbtp']}")
    if problems:
        bad("G3", "; ".join(problems))
    else:
        ok("G3", f"I={i_val} LUFS, true peak={tp_val} dBTP (on the final mux)")


def gate_G8(master: str) -> None:
    try:
        with open(master, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        bad("G8", f"cannot read: {exc}")
        return
    mo, md = head.find(b"moov"), head.find(b"mdat")
    if mo > 0 and (md == -1 or mo < md):
        ok("G8", f"faststart: moov@{mo} before mdat@{md}")
    else:
        bad("G8", f"not faststart: moov@{mo}, mdat@{md} -- +faststart missing from the mux")


# --------------------------------------------------------------------------- #
#  G4 -- the sub-bass vacuum
# --------------------------------------------------------------------------- #

def _max_volume(master: str, a: float, b: float) -> tuple[float | None, str]:
    hz = SPEC["vacuum"]["lowpass_hz"]
    # NO -v error: volumedetect logs max_volume at AV_LOG_INFO.
    proc = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", master,
                "-af", f"atrim={a}:{b},lowpass=f={hz},volumedetect",
                "-f", "null", "-"])
    out = proc.stdout + proc.stderr
    m = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", out)
    if not m:
        err = [l for l in out.splitlines() if l.strip()]
        return None, (err[-1] if err else "no output")
    return float(m.group(1)), ""


def gate_G4(master: str) -> None:
    vac = SPEC["vacuum"]
    a0, a1 = vac["window"]
    r0, r1 = vac["reference"]
    v, verr = _max_volume(master, a0, a1)
    r, rerr = _max_volume(master, r0, r1)
    # An empty match is a FAIL, never a fall-through pass (section 8, G4).
    if v is None or r is None:
        bad("G4", f"volumedetect printed no max_volume "
                  f"({a0}-{a1}s: {verr or 'ok'}; {r0}-{r1}s: {rerr or 'ok'}) -- "
                  f"no audio stream, or the window lies past the end of the file")
        return
    drop = r - v
    if drop < vac["min_drop_db"]:
        bad("G4", f"no vacuum: {a0}-{a1}s max_volume={v} dB vs reference "
                  f"{r0}-{r1}s={r} dB -- only {drop:.1f} dB down, need "
                  f">= {vac['min_drop_db']} dB. The sub never dropped.")
    else:
        ok("G4", f"vacuum present: {v} dB vs {r} dB = {drop:.1f} dB below reference")


# --------------------------------------------------------------------------- #
#  G5a / G5b -- the card PNGs
# --------------------------------------------------------------------------- #

def gate_G5a(cards_dir: str) -> None:
    from PIL import Image
    sz = SPEC["safe_zone"]
    v = SPEC["video"]
    failures, checked, skipped = [], [], []
    for cid in sorted(SPEC["cards"]):
        path = os.path.join(cards_dir, f"{cid}.png")
        if not os.path.exists(path):
            failures.append(f"{cid}: MISSING {path}")
            continue
        with Image.open(path) as im:
            if im.size != (v["width"], v["height"]):
                failures.append(f"{cid}: canvas {im.size[0]}x{im.size[1]}, "
                                f"expected {v['width']}x{v['height']}")
                continue
            if cid in sz["skip"]:
                skipped.append(cid)
                continue
            if im.mode != "RGBA":
                failures.append(f"{cid}: mode={im.mode}, needs RGBA (no alpha to scan)")
                continue
            alpha = im.getchannel("A")
        box = alpha.point(lambda p, t=sz["alpha_threshold"]: 255 if p > t else 0).getbbox()
        if box is None:
            failures.append(f"{cid}: alpha is empty -- the card is blank")
            continue
        x0, y0, x1, y1 = box
        x1, y1 = x1 - 1, y1 - 1  # getbbox right/lower are exclusive
        bad_axes = []
        if y0 < sz["y_min"]:
            bad_axes.append(f"top Y={y0} above {sz['y_min']} (TOP DANGER)")
        if y1 > sz["y_max"]:
            bad_axes.append(f"bottom Y={y1} below {sz['y_max']} (BOTTOM DANGER)")
        if x0 < sz["x_min"]:
            bad_axes.append(f"left X={x0} left of {sz['x_min']}")
        if x1 > sz["x_max"]:
            bad_axes.append(f"right X={x1} right of {sz['x_max']} (RIGHT DANGER)")
        if bad_axes:
            failures.append(f"{cid}: " + ", ".join(bad_axes))
        else:
            checked.append(f"{cid} Y{y0}-{y1} X{x0}-{x1}")
    if failures:
        bad("G5a", "safe zone: " + " | ".join(failures))
    else:
        ok("G5a", f"safe zone clear on {len(checked)} cards ({', '.join(checked)})")
    if skipped:
        record(_INFO, "G5a", f"skipped by name (full-frame by design): {sorted(skipped)}")


def gate_G5b(cards_dir: str) -> None:
    from PIL import ImageFont
    g = SPEC["glyph"]
    font_path = next((p for p in g["font_candidates"] if os.path.exists(p)), None)
    if font_path is None:
        bad("G5b", f"none of the candidate faces exist: {g['font_candidates']}")
        return
    failures, rows = [], []
    for cid in sorted(SPEC["cards"]):
        if cid in g["exempt"]:
            continue
        pt = SPEC["cards"][cid]["pt"]
        if pt is None:
            failures.append(f"{cid}: no type size in SPEC")
            continue
        if not os.path.exists(os.path.join(cards_dir, f"{cid}.png")):
            failures.append(f"{cid}: card PNG missing, cannot vouch for its type")
            continue
        font = ImageFont.truetype(font_path, pt)
        bb = font.getbbox(g["cap_probe"])
        cap = bb[3] - bb[1]
        problems = []
        if pt < g["min_em_px"]:
            problems.append(f"em {pt} px < {g['min_em_px']}")
        if cap < g["min_cap_px"]:
            problems.append(f"cap {cap} px < {g['min_cap_px']}")
        if problems:
            failures.append(f"{cid}: " + ", ".join(problems))
        else:
            rows.append(f"{cid} {pt}pt/cap{cap}")
    if failures:
        bad("G5b", f"glyph floor on {os.path.basename(font_path)}: " + " | ".join(failures))
    else:
        ok("G5b", f"glyph floor met on {os.path.basename(font_path)}: {', '.join(rows)} "
                  f"(floor em>={g['min_em_px']}, cap>={g['min_cap_px']}; "
                  f"exempt by name: {sorted(g['exempt'])})")
    record(_INFO, "G5b", f"measured against {font_path} at the SPEC type sizes. This "
                         f"proves the SPEC is satisfiable on the installed face; it "
                         f"cannot prove make_cards.py used that face. make_cards.py's "
                         f"own render-time assert is the primary check (section 7.3).")


# --------------------------------------------------------------------------- #
#  G6 -- each card on screen inside its own window
# --------------------------------------------------------------------------- #

def flash_frames() -> set[int]:
    """Frames covered by the c9 white flashes -- useless as presence samples."""
    return frames_of("c9")


def pick_sample_frame(a: int, b: int) -> int | None:
    """The window midpoint, walked off any c9 flash frame.

    Real collisions, not hypothetical: c4's window is 218-399 whose midpoint is 308,
    and c6's is 575-749 whose midpoint is 662. The c9 flashes cover 308-309 and
    661-662, so the naive midpoint samples a FULL-FRAME WHITE frame and G6 would
    red a correctly built master -- the "gate that goes red on a good file gets
    disabled" failure section 8 spends a paragraph on.
    """
    flashes = flash_frames()
    mid = (a + b) // 2
    for off in range(0, (b - a) + 1):
        for cand in (mid + off, mid - off):
            if a <= cand <= b and cand not in flashes:
                return cand
    return None


def gate_G6(master: str, cards_dir: str, tmp: str) -> None:
    from PIL import Image
    pres = SPEC["presence"]
    tol, frac = pres["colour_tol"], pres["min_fraction"]
    alpha_min = SPEC["safe_zone"]["alpha_threshold"]
    failures, rows, skipped = [], [], []
    for cid in sorted(SPEC["cards"]):
        if cid in pres["skip"]:
            skipped.append(cid)
            continue
        card_path = os.path.join(cards_dir, f"{cid}.png")
        if not os.path.exists(card_path):
            failures.append(f"{cid}: card PNG missing")
            continue
        rgb = SPEC["cards"][cid]["key_rgb"]
        with Image.open(card_path) as cim:
            ref = count_colour(cim.convert("RGBA"), rgb, tol, alpha_min=alpha_min)
        if ref == 0:
            failures.append(f"{cid}: key colour #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X} "
                            f"does not appear in the card at all -- SPEC colour is wrong")
            continue
        a, b = SPEC["cards"][cid]["windows"][0]
        mid = pick_sample_frame(a, b)
        if mid is None:
            failures.append(f"{cid}: window {a}-{b} is entirely covered by the c9 "
                            f"white flashes -- nothing to sample")
            continue
        dest = os.path.join(tmp, f"g6_{cid}.png")
        why = extract_frame(master, mid, dest)
        if why:
            failures.append(f"{cid}: {why}")
            continue
        with Image.open(dest) as fim:
            got = count_colour(fim.convert("RGB"), rgb, tol)
        need = int(ref * frac)
        if got < need:
            failures.append(f"{cid}: frame {mid} has {got} key-colour px, "
                            f"need >= {need} ({frac:.0%} of the card's {ref})")
        else:
            rows.append(f"{cid}@{mid}:{got}px")
    if failures:
        bad("G6", "card presence: " + " | ".join(failures))
    else:
        ok("G6", "every card present at its window midpoint -- " + ", ".join(rows))
    if skipped:
        record(_INFO, "G6", f"skipped: {sorted(skipped)} (2-frame flash; a window "
                            f"midpoint is not a meaningful sample)")


# --------------------------------------------------------------------------- #
#  G9 -- the slam lands on frame 127, not 126 or 128
# --------------------------------------------------------------------------- #

def gate_G9(master: str, tmp: str) -> None:
    s = SPEC["slam"]
    n = s["frame"]
    frames = {}
    for k in (n - 1, n, n + 1):
        dest = os.path.join(tmp, f"g9_{k}.png")
        why = extract_frame(master, k, dest)
        if why:
            bad("G9", f"cannot evaluate the slam at frame {n}: {why}")
            record(_HUMAN, "G9", SPEC["human_subchecks"]["G9"])
            return
        frames[k] = mean_rgb(dest)

    def d(p, q):
        return sum(abs(x - y) for x, y in zip(frames[p], frames[q])) / 3.0

    cut = d(n - 1, n)      # 126 -> 127, the hard cut
    after = d(n, n + 1)    # 127 -> 128, ordinary motion
    if cut < s["min_cut_delta"]:
        bad("G9", f"no cut at frame {n}: mean |dRGB| {n-1}->{n} is {cut:.2f}, "
                  f"need >= {s['min_cut_delta']}. 2.54 s x 50 fps = frame {n} exactly; "
                  f"the wardrobe/set change is not there.")
    elif after > 0 and cut < after * s["min_cut_ratio"]:
        bad("G9", f"cut is not on frame {n}: {n-1}->{n} delta {cut:.2f} does not "
                  f"dominate {n}->{n+1} delta {after:.2f} "
                  f"(need {s['min_cut_ratio']}x). The slam is off by a frame.")
    else:
        ok("G9", f"hard cut at frame {n}: {n-1}->{n} delta {cut:.2f} vs "
                 f"{n}->{n+1} delta {after:.2f}")
    record(_HUMAN, "G9", SPEC["human_subchecks"]["G9"])


# --------------------------------------------------------------------------- #
#  G14 -- character integrity, from cards/strings.txt
# --------------------------------------------------------------------------- #

def gate_G14(cards_dir: str) -> None:
    path = os.path.join(cards_dir, SPEC["strings_name"])
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        # section 8: a FileNotFoundError here is a FAIL, not a skip.
        bad("G14", f"{path} does not exist. make_cards.py must write it (section 7.4). "
                   f"This gate is never skipped because its input is missing.")
        return
    except UnicodeDecodeError as exc:
        bad("G14", f"{path} is not valid UTF-8: {exc}")
        return
    if not text.strip():
        bad("G14", f"{path} is empty -- nothing to audit")
        return

    st = SPEC["strings"]
    problems = []
    n_apos = text.count(ASCII_APOS)
    if n_apos > st["max_ascii_apostrophes"]:
        problems.append(f"{n_apos} ASCII apostrophe(s) U+0027 -- every mark must be "
                        f"U+02BB or U+02BC")
    n_rsquo = text.count(RSQUO)
    if n_rsquo:
        problems.append(f"{n_rsquo} U+2019 RIGHT SINGLE QUOTATION MARK -- also not a "
                        f"permitted Uzbek mark")
    n_nbsp = text.count(NBSP)
    if n_nbsp < st["min_nbsp"]:
        problems.append(f"{n_nbsp} U+00A0 -- the price needs a NO-BREAK SPACE "
                        f"(pricing.py:35-41: a plain space is the character that wraps, "
                        f"and '15' / '000 so'+U+02BB+'m' across a break reads as 15 so'm)")
    if problems:
        bad("G14", "; ".join(problems))
    else:
        ok("G14", f"{len(text.splitlines())} lines: 0 ASCII apostrophes, 0 U+2019, "
                  f"{n_nbsp} U+00A0, {text.count(TC)} U+02BB, {text.count(MC)} U+02BC")


# --------------------------------------------------------------------------- #
#  G16 -- funnel exposure, recomputed from the card windows
# --------------------------------------------------------------------------- #

def gate_G16(probe: dict | None) -> None:
    v = SPEC["video"]
    last_allowed = v["nb_frames"] - 1
    try:
        actual_frames = int(probe.get("nb_frames")) if probe else None
    except (TypeError, ValueError):
        actual_frames = None

    problems, rows = [], []

    # A window that lies past the end of the file has ZERO exposure, whatever the
    # table says. This is the check that reds on a one-third-length cut.
    for cid, c in SPEC["cards"].items():
        for a, b in c["windows"]:
            if b > last_allowed:
                problems.append(f"{cid} window ends at frame {b}, past the spec's "
                                f"last frame {last_allowed}")
            if actual_frames is not None and b > actual_frames - 1:
                problems.append(f"{cid} window {a}-{b} lies outside the built master, "
                                f"which has only {actual_frames} frames -- that "
                                f"element is never on screen")

    f = SPEC["funnel"]
    h = f["handle"]
    handle = set()
    for cid in h["cards"]:
        handle |= frames_of(cid)
    newest = len(frames_of(h["newest"]))
    if len(handle) < h["min_frames"]:
        problems.append(f"handle present {len(handle)} frames, need >= {h['min_frames']}")
    if newest < h["min_newest_frames"]:
        problems.append(f"handle newest-element {newest} frames, "
                        f"need >= {h['min_newest_frames']}")
    rows.append(f"handle {len(handle)}f ({newest}f newest)")

    p = f["price"]
    price = set()
    for cid in p["cards"]:
        price |= frames_of(cid)
    if len(price) < p["min_frames"]:
        problems.append(f"price present {len(price)} frames, need >= {p['min_frames']}")
    rows.append(f"price {len(price)}f")

    pr = f["problem"]
    first = min(min(a for a, _ in SPEC["cards"][c]["windows"]) for c in pr["cards"])
    if first > pr["max_first_frame"]:
        problems.append(f"problem first stated at frame {first}, "
                        f"need <= {pr['max_first_frame']}")
    rows.append(f"problem from frame {first}")

    if problems:
        bad("G16", "funnel exposure: " + "; ".join(sorted(set(problems))))
    else:
        ok("G16", "funnel exposure: " + ", ".join(rows))


# --------------------------------------------------------------------------- #
#  G17 -- the loop seam
# --------------------------------------------------------------------------- #

def gate_G17(master: str, tmp: str) -> None:
    lp = SPEC["loop"]
    means = {}
    for k in (lp["frame_a"], lp["frame_b"]):
        dest = os.path.join(tmp, f"g17_{k}.png")
        why = extract_frame(master, k, dest)
        if why:
            bad("G17", f"cannot measure the loop seam: {why}")
            record(_HUMAN, "G17", SPEC["human_subchecks"]["G17"])
            return
        means[k] = mean_rgb(dest)
    a, b = means[lp["frame_a"]], means[lp["frame_b"]]
    deltas = [abs(x - y) for x, y in zip(a, b)]
    worst = max(deltas)
    if worst > lp["max_mean_rgb_delta"]:
        bad("G17", f"loop seam visible: frame {lp['frame_a']} mean RGB "
                   f"({a[0]:.1f},{a[1]:.1f},{a[2]:.1f}) vs frame {lp['frame_b']} "
                   f"({b[0]:.1f},{b[1]:.1f},{b[2]:.1f}); worst channel differs by "
                   f"{worst:.1f}, ceiling {lp['max_mean_rgb_delta']}")
    else:
        ok("G17", f"loop seam: worst channel delta {worst:.1f} "
                  f"<= {lp['max_mean_rgb_delta']}")
    record(_HUMAN, "G17", SPEC["human_subchecks"]["G17"])


# --------------------------------------------------------------------------- #
#  main
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    master = SPEC["master"]
    cards_dir = SPEC["cards_dir"]
    args = list(argv)
    if "--cards" in args:
        i = args.index("--cards")
        cards_dir = args[i + 1]
        del args[i:i + 2]
    positional = [a for a in args if not a.startswith("-")]
    if positional:
        master = positional[0]

    print("=" * 78)
    print("marketing/campaigns/peshta QA gate -- section 8 of 04_generation_plan.md")
    print(f"  master    : {master}")
    print(f"  cards     : {cards_dir}")
    print("=" * 78)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[ FAIL ] --   PIL is not importable. Run this with "
              ".venv/bin/python -- the system python has no PIL.")
        return 1

    tmp = tempfile.mkdtemp(prefix="qa_gate_")
    try:
        gate_G0()
        probe = gate_G1(master)
        if probe is not None:
            gate_G2(master)
            gate_G3(master)
            gate_G4(master)
            gate_G8(master)
            gate_G6(master, cards_dir, tmp)
            gate_G9(master, tmp)
            gate_G17(master, tmp)
        else:
            for g in ("G2", "G3", "G4", "G6", "G8", "G9", "G17"):
                bad(g, "not evaluated -- G1 could not read the master as a video")
        gate_G5a(cards_dir)
        gate_G5b(cards_dir)
        gate_G14(cards_dir)
        gate_G16(probe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 78)
    for gid, text in SPEC["human_gates"].items():
        record(_HUMAN, gid, text)

    print("=" * 78)
    fails = [(g, m) for s, g, m in RESULTS if s == _FAIL]
    passes = [g for s, g, _ in RESULTS if s == _PASS]
    humans = sorted({g for s, g, _ in RESULTS if s == _HUMAN})
    print(f"PASSED        : {len(passes)}  {sorted(set(passes))}")
    print(f"SKIPPED-HUMAN : {len(humans)}  {humans}  <- NOT passes. Nobody has signed "
          f"these off.")
    print(f"FAILED        : {len(fails)}")
    for g, m in fails:
        print(f"    {g}: {m}")
    print("=" * 78)
    if fails:
        print("RESULT: FAIL -- this file is not publishable. Exit 1.")
        return 1
    print("RESULT: every machine-checkable gate passed. The SKIPPED-HUMAN gates above "
          "still block publication. Exit 0.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # a crashing gate is a failing gate, never a pass
        import traceback
        traceback.print_exc()
        print(f"RESULT: FAIL -- qa_gate.py itself raised {type(exc).__name__}: {exc}. "
              f"Exit 1.")
        sys.exit(1)
