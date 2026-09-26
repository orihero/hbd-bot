#!/usr/bin/env python3
"""A/B comparison harness: Higgsfield cloud render (A) vs local-model render (B).

The point of this script is that a human can look at its output for thirty
seconds and say which pipeline won.  It produces three things:

  ab/side_by_side.mp4   both reels playing in lockstep, labelled, with a
                        running timecode and the master music once
  ab/contact_sheet_A.png,
  ab/contact_sheet_B.png
                        one frame per macro shot, so identity drift across the
                        eleven shots is visible at a glance
  ab/metrics.json       per-shot objective numbers for both files, plus the
                        A-minus-B delta

Read docs/research/RESEARCH-ab-higgsfield-vs-local-reel-metrics.md for what the
numbers mean.

Shot windows come from 06_local/shot_bible_v2.json; if that is missing the eleven
windows are parsed out of FINAL_RECREATION_REPORT.md section 3 instead and the
fallback is recorded in metrics.json.

Self-test (run this before trusting any real comparison) -- feed the harness the
same file twice; every difference metric must land at or near zero:

    python3 compare_ab.py --b <same path as --a> --label-b "A (SELF-TEST)"

Environment notes
-----------------
* ffmpeg here has NO libfreetype and NO libass, so `drawtext` and `subtitles`
  do not exist.  All burned-in text is rendered to PNG by _abtext.py (stdlib
  only) and composited with `overlay`.
* numpy / opencv / Pillow are absent from every interpreter on this machine and
  the brief forbids installing them, so the Laplacian-variance sharpness metric
  is NOT computed.  metrics.json says so explicitly instead of faking it.  A
  weaker but real substitute -- mean Laplacian edge energy via ffmpeg's
  `convolution` filter -- is reported under its own, differently-named key so
  the two can never be confused.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _abtext  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROMO = os.path.dirname(HERE)
REPO = os.path.dirname(PROMO)

DEFAULT_A = os.path.join(PROMO, "final_polat_peshta_reel.mp4")
DEFAULT_B = os.path.join(HERE, "build", "local_reel.mp4")
DEFAULT_AUDIO = os.path.join(PROMO, "audio", "Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3")
DEFAULT_BIBLE = os.path.join(HERE, "shot_bible_v2.json")
FALLBACK_REPORT = os.path.join(PROMO, "FINAL_RECREATION_REPORT.md")
DEFAULT_OUTDIR = os.path.join(HERE, "ab")

READING_DOC = "docs/research/RESEARCH-ab-higgsfield-vs-local-reel-metrics.md"

ACCENT_A = (255, 230, 0, 255)   # gold  -- Higgsfield / reference
ACCENT_B = (0, 229, 255, 255)   # cyan  -- local build


# ---------------------------------------------------------------------------
# shell helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], quiet: bool = True) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write("FAILED: %s\n%s\n" % (" ".join(cmd[:14]), proc.stderr[-4000:]))
        raise SystemExit(1)
    if not quiet and proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.stdout


def filter_escape(path: str) -> str:
    """Escape a path for use inside a filter option value (one level)."""
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def probe(path: str) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", path,
    ])
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        raise SystemExit("no video stream in %s" % path)
    num, den = (video.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    return {
        "path": path,
        "exists": True,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": round(fps, 6),
        "nb_frames": int(video["nb_frames"]) if video.get("nb_frames") else None,
        "duration_s": round(float(data["format"]["duration"]), 3),
        "video_codec": video.get("codec_name"),
        "has_audio": audio is not None,
        "size_bytes": int(data["format"]["size"]),
    }


# ---------------------------------------------------------------------------
# shot windows
# ---------------------------------------------------------------------------

def load_shots(bible_path: str, report_path: str) -> tuple[list[dict], dict]:
    """Return (shots, provenance).  Each shot: id, start_s, end_s, label."""
    if os.path.isfile(bible_path):
        bible = json.load(open(bible_path))
        shots = [
            {
                "id": str(s["id"]),
                "start_s": float(s["start_s"]),
                "end_s": float(s["end_s"]),
                "label": s.get("driving_clip", ""),
            }
            for s in bible["shots"]
        ]
        return shots, {
            "source": "shot_bible_v2.json",
            "path": os.path.relpath(bible_path, REPO),
            "fallback_used": False,
            "schema_version": bible.get("schema_version"),
        }

    # Fallback: the manifest table in FINAL_RECREATION_REPORT section 3, whose
    # rows read  | **01** | `clip_...mp4` | ... | 0.000s - 2.256s | 2.256s | ...
    if not os.path.isfile(report_path):
        raise SystemExit("no shot_bible.json and no %s to fall back to" % report_path)
    row = re.compile(
        r"^\|\s*\*\*(\d+)\*\*\s*\|\s*`([^`]+)`\s*\|.*?\|\s*"
        r"([0-9.]+)s\s*[-–—]\s*([0-9.]+)s\s*\|",
    )
    shots = []
    for line in open(report_path, encoding="utf-8"):
        m = row.match(line.strip())
        if m:
            shots.append({
                "id": m.group(1),
                "start_s": float(m.group(3)),
                "end_s": float(m.group(4)),
                "label": m.group(2),
            })
    if not shots:
        raise SystemExit("could not parse any shot rows out of %s section 3" % report_path)
    return shots, {
        "source": "FINAL_RECREATION_REPORT.md section 3 (FALLBACK)",
        "path": os.path.relpath(report_path, REPO),
        "fallback_used": True,
        "note": "shot_bible.json was absent; windows parsed from the render "
                "manifest table in section 3. Regenerate the bible and re-run "
                "for authoritative windows.",
    }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def _parse_metadata(path: str) -> list[tuple[float, dict]]:
    """Parse ffmpeg `metadata=mode=print` output into [(pts_time, {key: val})]."""
    frames: list[tuple[float, dict]] = []
    cur: dict | None = None
    t = 0.0
    if not os.path.isfile(path):
        return frames
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("frame:"):
            if cur is not None:
                frames.append((t, cur))
            cur = {}
            m = re.search(r"pts_time:(\S+)", line)
            t = float(m.group(1)) if m else 0.0
        elif cur is not None and "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip()] = v.strip()
    if cur is not None:
        frames.append((t, cur))
    return frames


def collect_raw(path: str, workdir: str, tag: str, scdet_threshold: float) -> dict:
    """One decode of `path` fanned out into four analysis branches.

    Four separate passes would take four decodes; `split` lets a single decode
    feed signalstats, a frame-difference stat, scene detection and an edge-energy
    stat at once, each writing its own metadata file.
    """
    st = os.path.join(workdir, "%s_stats.txt" % tag)
    df = os.path.join(workdir, "%s_diff.txt" % tag)
    sc = os.path.join(workdir, "%s_scd.txt" % tag)
    lp = os.path.join(workdir, "%s_lap.txt" % tag)

    yavg = "lavfi.signalstats.YAVG"
    # 4-neighbour Laplacian on the luma plane; chroma passed through untouched.
    lap_kernel = "0 1 0 1 -4 1 0 1 0"
    passthru = "0 0 0 0 1 0 0 0 0"

    graph = (
        "[0:v]split=4[s1][s2][s3][s4];"
        "[s1]signalstats,metadata=mode=print:file='{st}'[out];"
        "[s2]tblend=all_mode=difference,signalstats,"
        "metadata=mode=print:key={y}:file='{df}',nullsink;"
        "[s3]scdet=t={thr},metadata=mode=print:file='{sc}',nullsink;"
        "[s4]convolution=0m='{lap}':1m='{pt}':2m='{pt}',signalstats,"
        "metadata=mode=print:key={y}:file='{lp}',nullsink"
    ).format(
        st=filter_escape(st), df=filter_escape(df), sc=filter_escape(sc),
        lp=filter_escape(lp), y=yavg, thr=scdet_threshold,
        lap=lap_kernel, pt=passthru,
    )

    run(["ffmpeg", "-v", "error", "-i", path, "-an",
         "-filter_complex", graph, "-map", "[out]", "-f", "null", "-"])

    return {
        "stats": _parse_metadata(st),
        "diff": _parse_metadata(df),
        "scd": _parse_metadata(sc),
        "lap": _parse_metadata(lp),
    }


def _stat(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "stddev": None, "min": None, "max": None, "n": 0}
    return {
        "mean": round(statistics.fmean(values), 4),
        "stddev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "n": len(values),
    }


def _window(frames: list[tuple[float, dict]], start: float, end: float,
            key: str) -> list[float]:
    out = []
    for t, md in frames:
        if start <= t < end and key in md:
            try:
                out.append(float(md[key]))
            except ValueError:
                pass
    return out


def shot_metrics(raw: dict, shots: list[dict], scdet_threshold: float) -> list[dict]:
    yavg = "lavfi.signalstats.YAVG"
    satavg = "lavfi.signalstats.SATAVG"
    rows = []
    for s in shots:
        a, b = s["start_s"], s["end_s"]
        luma = _window(raw["stats"], a, b, yavg)
        sat = _window(raw["stats"], a, b, satavg)
        diff = _window(raw["diff"], a, b, yavg)
        edge = _window(raw["lap"], a, b, yavg)
        cuts = [
            t for t, md in raw["scd"]
            if a <= t < b and "lavfi.scd.time" in md
        ]
        rows.append({
            "id": s["id"],
            "start_s": round(a, 3),
            "end_s": round(b, 3),
            "dur_s": round(b - a, 3),
            "label": s["label"],
            "frames_observed": len(luma),
            # motion energy / temporal flicker
            "frame_diff": _stat(diff),
            # a local i2v model that "resets" mid-shot lights this up
            "scene_changes": {
                "count": len(cuts),
                "threshold": scdet_threshold,
                "times_s": [round(t, 3) for t in cuts],
            },
            # grade drift between the two pipelines
            "luma": _stat(luma),
            "saturation": _stat(sat),
            # honest naming: this is mean edge ENERGY, not Laplacian VARIANCE
            "edge_energy_ffmpeg_laplacian": _stat(edge),
            "laplacian_variance": None,
        })
    return rows


def delta_rows(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    out = []
    for ra, rb in zip(rows_a, rows_b):
        def d(path_a, path_b=None):
            va = ra
            vb = rb
            for k in path_a:
                va = (va or {}).get(k)
                vb = (vb or {}).get(k)
            if va is None or vb is None:
                return None
            return round(va - vb, 4)

        out.append({
            "id": ra["id"],
            "frames_observed_delta": ra["frames_observed"] - rb["frames_observed"],
            "frame_diff_mean_delta": d(["frame_diff", "mean"]),
            "frame_diff_stddev_delta": d(["frame_diff", "stddev"]),
            "scene_changes_delta": ra["scene_changes"]["count"] - rb["scene_changes"]["count"],
            "luma_mean_delta": d(["luma", "mean"]),
            "saturation_mean_delta": d(["saturation", "mean"]),
            "edge_energy_mean_delta": d(["edge_energy_ffmpeg_laplacian", "mean"]),
        })
    return out


# ---------------------------------------------------------------------------
# contact sheet
# ---------------------------------------------------------------------------

def contact_sheet(video: str, shots: list[dict], out_png: str, workdir: str,
                  tag: str, title: str, accent, cell_w: int = 360,
                  cell_h: int = 640, cols: int = 4) -> dict:
    """One frame per macro shot, taken at the midpoint of its window."""
    info = probe(video)
    rows = math.ceil(len(shots) / cols)
    cells_dir = os.path.join(workdir, "cells_%s" % tag)
    os.makedirs(cells_dir, exist_ok=True)

    clamped = []
    for i, s in enumerate(shots, start=1):
        mid = (s["start_s"] + s["end_s"]) / 2.0
        # A short B build must not silently sample black past its own end.
        if mid >= info["duration_s"]:
            mid = max(0.0, info["duration_s"] - 0.05)
            clamped.append(s["id"])
        cap = _abtext.badge(
            os.path.join(cells_dir, "cap_%02d.png" % i),
            "S%s  %06.3fS" % (s["id"], mid),
            scale=3, fg=(255, 255, 255, 255), bg=(0, 0, 0, 200), pad=7,
        )
        run([
            "ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % mid, "-i", video,
            "-i", cap,
            "-filter_complex",
            "[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[c];"
            "[c][1:v]overlay=8:8" % (cell_w, cell_h, cell_w, cell_h),
            "-frames:v", "1", os.path.join(cells_dir, "cell_%02d.png" % i),
        ])

    title_png = _abtext.badge(
        os.path.join(workdir, "title_%s.png" % tag), title,
        scale=4, fg=(0, 0, 0, 255), bg=accent, pad=12,
    )
    run([
        "ffmpeg", "-v", "error", "-y",
        "-framerate", "1", "-i", os.path.join(cells_dir, "cell_%02d.png"),
        "-i", title_png,
        "-filter_complex",
        "[0:v]tile=%dx%d:margin=10:padding=8:color=0x101010,"
        "pad=iw:ih+72:0:72:color=0x101010[t];[t][1:v]overlay=14:16"
        % (cols, rows),
        "-frames:v", "1", out_png,
    ])
    return {"path": out_png, "grid": "%dx%d" % (cols, rows),
            "cells": len(shots), "clamped_shots": clamped}


# ---------------------------------------------------------------------------
# side-by-side
# ---------------------------------------------------------------------------

def side_by_side(a: str, b: str, audio: str, out_mp4: str, workdir: str,
                 label_a: str, label_b: str, layout: str,
                 shots: list[dict], duration: float, crf: int) -> dict:
    """Both reels in lockstep, labelled, with a running timecode.

    LAYOUT CHOICE -- hstack (2160x1920) is the default, not a vstack into
    1080x1920.  Two reasons, both about being able to actually judge the thing:

      1. Resolution.  hstack keeps each half at its native 1080x1920, so every
         pixel of the original survives into the comparison file.  Stacking two
         9:16 frames into a 1080x1920 canvas forces each half down to roughly
         540x960 -- a 4x reduction in pixel count -- which destroys exactly the
         detail the A/B exists to judge: face identity, hair and fabric
         micro-detail, i2v softness, h264 blocking.  A comparison that blurs
         away the artefact is worthless.
      2. Eye movement.  Side by side puts the two faces at the SAME vertical
         position, so the comparison is a short horizontal saccade at matching
         scale.  Vertically stacked, the eye has to travel the full height of
         the frame and re-anchor, and a viewer cannot hold the two in foveal
         view at once.

    `--layout vstack` is kept for phone viewing, where a 2160-wide file is
    awkward; it letterboxes rather than distorts, and is explicitly the
    lower-fidelity option.
    """
    if layout == "hstack":
        half_w, half_h = 1080, 1920
        out_w, out_h = 2160, 1920
        pos_a, pos_b = (0, 0), (1080, 0)
        label_w = 1080
    else:
        half_w, half_h = 1080, 960
        out_w, out_h = 1080, 1920
        pos_a, pos_b = (0, 0), (0, 960)
        label_w = 1080

    lab_a = _abtext.label_strip(
        os.path.join(workdir, "lab_a.png"), label_w, label_a,
        scale=6, accent=ACCENT_A,
    )
    lab_b = _abtext.label_strip(
        os.path.join(workdir, "lab_b.png"), label_w, label_b,
        scale=6, accent=ACCENT_B,
    )

    # Running timecode: one PNG per second, fed in as a 1 fps stream and held
    # by overlay. drawtext would do this per-frame, but this build has no
    # drawtext -- and at 1 Hz the readout is more legible anyway.  Each tick
    # also names the macro shot that is live, which is what you actually need
    # when you spot a defect and want to go fix that shot.
    tc_dir = os.path.join(workdir, "tc")
    os.makedirs(tc_dir, exist_ok=True)
    # +2 spare ticks: a 1 fps stream of exactly ceil(duration) frames signals EOF
    # at t = duration-1, and an overlay that ends on it would truncate the output
    # by the last second. Overrunning the video costs nothing.
    seconds = max(1, int(math.ceil(duration)) + 2)
    for sec in range(seconds):
        live = next((s["id"] for s in shots if s["start_s"] <= sec < s["end_s"]), "--")
        _abtext.badge(
            os.path.join(tc_dir, "tc_%04d.png" % (sec + 1)),
            "%02d:%02d  |  SHOT %s" % (sec // 60, sec % 60, live),
            scale=5, bg=(0, 0, 0, 200), pad=12,
        )
    tc_w = _abtext.text_width("00:00  |  SHOT 00", 5) + 24
    tc_h = _abtext.text_height(5) + 24

    fit = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
           "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
           % (half_w, half_h, half_w, half_h))
    stack = "hstack=inputs=2:shortest=1" if layout == "hstack" else "vstack=inputs=2:shortest=1"

    graph = (
        "[0:v]{fit}[va];"
        "[1:v]{fit}[vb];"
        "[va][vb]{stack}[st];"
        "[st][3:v]overlay={ax}:{ay}[s1];"
        "[s1][4:v]overlay={bx}:{by}[s2];"
        # no shortest= here: output length is set by hstack/vstack shortest=1
        # (i.e. the shorter of the two reels) and by -shortest against the audio.
        "[s2][5:v]overlay=(W-w)/2:H-h-48[v]"
    ).format(fit=fit, stack=stack,
             ax=pos_a[0], ay=pos_a[1], bx=pos_b[0], by=pos_b[1])

    run([
        "ffmpeg", "-v", "error", "-y",
        "-i", a,
        "-i", b,
        "-i", audio,          # audio taken ONCE from the master, never doubled
        "-i", lab_a,
        "-i", lab_b,
        "-framerate", "1", "-i", os.path.join(tc_dir, "tc_%04d.png"),
        "-filter_complex", graph,
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest", out_mp4,
    ])
    return {
        "path": out_mp4,
        "layout": layout,
        "resolution": "%dx%d" % (out_w, out_h),
        "audio_source": audio,
        "audio_doubled": False,
        "timecode_hz": 1,
        "timecode_badge_px": [tc_w, tc_h],
    }


# ---------------------------------------------------------------------------
# sharpness capability probe
# ---------------------------------------------------------------------------

def sharpness_capability() -> dict:
    have = {}
    for mod in ("numpy", "cv2", "PIL"):
        try:
            __import__(mod)
            have[mod] = True
        except ImportError:
            have[mod] = False
    ok = have["numpy"] and (have["cv2"] or have["PIL"])
    return {
        "laplacian_variance_computed": ok,
        "modules_present": have,
        "reason": None if ok else (
            "Laplacian VARIANCE is not reported: it needs numpy plus opencv or "
            "Pillow to read decoded frames into an array, and none of those are "
            "installed on this machine. The brief forbids pip-installing them, "
            "so the metric is omitted rather than faked. "
            "'edge_energy_ffmpeg_laplacian' is reported instead: it is the mean "
            "of a 4-neighbour Laplacian edge map computed by ffmpeg's "
            "convolution filter. It moves in the same direction as sharpness "
            "(soft frame -> lower) but it is a MEAN, not a variance, so it is "
            "more sensitive to global contrast and less sensitive to a small "
            "region going soft. Compare it A-vs-B on the same content only; "
            "never quote it as a Laplacian variance."
        ),
    }


# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="A/B the Higgsfield cloud reel against the local-model rebuild.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Self-test: pass the same file as --a and --b; every difference "
               "metric must come out at or near zero.",
    )
    p.add_argument("--a", default=DEFAULT_A, help="reference render (default: Higgsfield reel)")
    p.add_argument("--b", default=DEFAULT_B, help="local render")
    p.add_argument("--label-a", default="A  HIGGSFIELD CLOUD")
    p.add_argument("--label-b", default="B  LOCAL MODELS")
    p.add_argument("--audio", default=DEFAULT_AUDIO, help="master mp3 muxed once")
    p.add_argument("--shot-bible", default=DEFAULT_BIBLE)
    p.add_argument("--report", default=FALLBACK_REPORT, help="fallback shot windows")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument("--layout", choices=["hstack", "vstack"], default="hstack")
    p.add_argument("--scdet-threshold", type=float, default=10.0)
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--skip", default="", help="comma list of: sbs,sheets,metrics")
    p.add_argument("--keep-temp", action="store_true")
    args = p.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit("%s not on PATH" % tool)
    for path, what in ((args.a, "--a"), (args.b, "--b"), (args.audio, "--audio")):
        if not os.path.isfile(path):
            raise SystemExit("%s not found: %s" % (what, path))

    os.makedirs(args.outdir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="abcmp_")
    self_test = os.path.realpath(args.a) == os.path.realpath(args.b)

    shots, prov = load_shots(args.shot_bible, args.report)
    info_a, info_b = probe(args.a), probe(args.b)
    duration = min(info_a["duration_s"], info_b["duration_s"])

    print("A: %s (%dx%d, %s frames, %.3fs)" % (
        args.a, info_a["width"], info_a["height"], info_a["nb_frames"], info_a["duration_s"]))
    print("B: %s (%dx%d, %s frames, %.3fs)" % (
        args.b, info_b["width"], info_b["height"], info_b["nb_frames"], info_b["duration_s"]))
    print("shots: %d from %s" % (len(shots), prov["source"]))
    if self_test:
        print("SELF-TEST MODE: A and B are the same file; deltas must be ~0.")

    result = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "harness": "marketing/campaigns/peshta/06_local/compare_ab.py",
        "reading": READING_DOC,
        "self_test": self_test,
        "inputs": {"A": info_a, "B": info_b,
                   "audio_master": args.audio,
                   "labels": {"A": args.label_a, "B": args.label_b}},
        "shot_windows": prov,
        "bucketing_note": (
            "frames_observed counts frames whose pts falls in [start_s, end_s), "
            "which can differ by one from the shot bible's nominal round(dur*fps) "
            "at a window boundary. Both sides are bucketed by the identical rule, "
            "so this never biases an A-vs-B delta."
        ),
        "sharpness": sharpness_capability(),
        "outputs": {},
    }

    if "metrics" not in skip:
        print("[1/3] metrics ...")
        raw_a = collect_raw(args.a, workdir, "A", args.scdet_threshold)
        raw_b = collect_raw(args.b, workdir, "B", args.scdet_threshold)
        rows_a = shot_metrics(raw_a, shots, args.scdet_threshold)
        rows_b = shot_metrics(raw_b, shots, args.scdet_threshold)
        result["per_shot"] = {"A": rows_a, "B": rows_b,
                              "delta_A_minus_B": delta_rows(rows_a, rows_b)}
        result["whole_reel"] = {
            side: {
                "frame_diff_mean": round(statistics.fmean(
                    [r["frame_diff"]["mean"] for r in rows if r["frame_diff"]["mean"] is not None]), 4),
                "scene_changes_total": sum(r["scene_changes"]["count"] for r in rows),
                "luma_mean": round(statistics.fmean(
                    [r["luma"]["mean"] for r in rows if r["luma"]["mean"] is not None]), 4),
                "saturation_mean": round(statistics.fmean(
                    [r["saturation"]["mean"] for r in rows if r["saturation"]["mean"] is not None]), 4),
                "edge_energy_mean": round(statistics.fmean(
                    [r["edge_energy_ffmpeg_laplacian"]["mean"] for r in rows
                     if r["edge_energy_ffmpeg_laplacian"]["mean"] is not None]), 4),
            }
            for side, rows in (("A", rows_a), ("B", rows_b))
        }
        if self_test:
            deltas = result["per_shot"]["delta_A_minus_B"]
            worst = max(
                abs(v) for row in deltas for k, v in row.items()
                if k != "id" and isinstance(v, (int, float))
            )
            result["self_test_result"] = {
                "max_abs_delta": worst,
                "passed": worst < 1e-6,
                "expectation": "every per-shot delta must be exactly 0.0 when A and B "
                               "are the same file; a non-zero value means the harness "
                               "itself is non-deterministic.",
            }
            print("    self-test max |delta| = %g -> %s" % (
                worst, "PASS" if worst < 1e-6 else "FAIL"))

    if "sheets" not in skip:
        print("[2/3] contact sheets ...")
        result["outputs"]["contact_sheet_A"] = contact_sheet(
            args.a, shots, os.path.join(args.outdir, "contact_sheet_A.png"),
            workdir, "A", args.label_a, ACCENT_A)
        result["outputs"]["contact_sheet_B"] = contact_sheet(
            args.b, shots, os.path.join(args.outdir, "contact_sheet_B.png"),
            workdir, "B", args.label_b, ACCENT_B)

    if "sbs" not in skip:
        print("[3/3] side-by-side ...")
        result["outputs"]["side_by_side"] = side_by_side(
            args.a, args.b, args.audio,
            os.path.join(args.outdir, "side_by_side.mp4"),
            workdir, args.label_a, args.label_b, args.layout, shots,
            duration, args.crf)

    metrics_path = os.path.join(args.outdir, "metrics.json")
    with open(metrics_path, "w") as fh:
        json.dump(result, fh, indent=2)
    print("wrote %s" % metrics_path)

    if args.keep_temp:
        print("temp kept: %s" % workdir)
    else:
        shutil.rmtree(workdir, ignore_errors=True)

    if self_test and "metrics" not in skip:
        return 0 if result["self_test_result"]["passed"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
