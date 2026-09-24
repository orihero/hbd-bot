#!/usr/bin/env python3
"""
slice_driving_clips.py — Milestone 1 (M1) Reference Clip Decomposition & 9:16 Cropping.

Decomposes the source video (marketing/campaigns/peshta/raw/Xamdam_Sobirov_Peshta_1080p_h264.mp4)
into 11 continuous Driving Clips for Higgsfield Motion Control synthesis,
calibrated to t = 27.264s (Frame 682) through 70.264s (Frame 1757) to achieve
frame-perfect audio-visual synchronization with the 43.000s master parody audio track
(Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3) at the 0:34 beat drop (rel t = 6.920s).

Outputs:
  - 11 cropped, CFR 30.0 fps, 1080x1920 (9:16) H.264 MP4 clips in marketing/campaigns/peshta/driving_clips/
  - marketing/campaigns/peshta/driving_clips/SHOT_TABLE.md documenting all timing, cropping, and character data.
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

# Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
RAW_VIDEO = WORKSPACE_ROOT / "marketing/campaigns/peshta" / "raw" / "Xamdam_Sobirov_Peshta_1080p_h264.mp4"
OUTPUT_DIR = WORKSPACE_ROOT / "marketing/campaigns/peshta" / "driving_clips"
SHOT_TABLE_PATH = OUTPUT_DIR / "SHOT_TABLE.md"

# Target Specifications
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30
TOTAL_DURATION = 43.000
CALIBRATED_START_S = 27.264
CALIBRATED_END_S = 70.264

# Macro Driving Clip Definitions (11 continuous clips covering exactly 43.000s)
CLIPS_CONFIG: list[dict[str, Any]] = [
    {
        "index": 1,
        "name": "clip_01_verse1_setup.mp4",
        "start_s": 27.264,
        "end_s": 29.520,
        "duration_s": 2.256,
        "rel_start_s": 0.000,
        "rel_end_s": 2.256,
        "target_character": "Elif Eylül (01) -> Polat Alemdar (02)",
        "center_x": 960,
        "crop_x_offset": 656,
        "spanned_shots": [1, 2],
        "subshots": [
            {
                "shot_id": 1,
                "duration_s": 0.376,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 2,
                "duration_s": 1.880,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Hook open & staging setup; smartphone surprise reaction transition "
            "into ensemble wrist flourishes atop red pyramid steps."
        ),
    },
    {
        "index": 2,
        "name": "clip_02_hook_duo_roses.mp4",
        "start_s": 29.520,
        "end_s": 32.440,
        "duration_s": 2.920,
        "rel_start_s": 2.256,
        "rel_end_s": 5.176,
        "target_character": "Duo (Polat Alemdar + Elif Eylül)",
        "center_x": 884,
        "crop_x_offset": 580,
        "spanned_shots": [3],
        "subshots": [
            {
                "shot_id": 3,
                "duration_s": 2.920,
                "center_x": 884,
                "crop_x_offset": 580,
                "character": "Duo",
            },
        ],
        "choreography": (
            "Romance on red velvet steps; Elif seated holding red roses, "
            "Polat leaning down charismatically from higher step."
        ),
    },
    {
        "index": 3,
        "name": "clip_03_chorus_drop_hero.mp4",
        "start_s": 32.440,
        "end_s": 36.240,
        "duration_s": 3.800,
        "rel_start_s": 5.176,
        "rel_end_s": 8.976,
        "target_character": "Polat Alemdar (Hero WS with Ensemble)",
        "center_x": 960,
        "crop_x_offset": 656,
        "spanned_shots": [4],
        "subshots": [
            {
                "shot_id": 4,
                "duration_s": 3.800,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "THE PRIMARY 0:34 BEAT DROP (source 34.184s / rel 6.920s)! Sub-bass dropout "
            "followed by massive slam; Polat drops into deep squat bounce, "
            "dancers snap into synchronized Khorezm Lazgi knee bounces."
        ),
    },
    {
        "index": 4,
        "name": "clip_04_call_response_1.mp4",
        "start_s": 36.240,
        "end_s": 39.080,
        "duration_s": 2.840,
        "rel_start_s": 8.976,
        "rel_end_s": 11.816,
        "target_character": "Elif Eylül (05) -> Polat Alemdar (06)",
        "center_x": 940,
        "crop_x_offset": 636,
        "spanned_shots": [5, 6],
        "subshots": [
            {
                "shot_id": 5,
                "duration_s": 1.360,
                "center_x": 820,
                "crop_x_offset": 516,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 6,
                "duration_s": 1.480,
                "center_x": 1060,
                "crop_x_offset": 756,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Call & Response Phase 1; Elif profile glance clutching pearls, cutting to "
            "Polat executing sharp alternating shoulder pops ('Yelka qoqish')."
        ),
    },
    {
        "index": 5,
        "name": "clip_05_call_response_2.mp4",
        "start_s": 39.080,
        "end_s": 41.680,
        "duration_s": 2.600,
        "rel_start_s": 11.816,
        "rel_end_s": 14.416,
        "target_character": "Elif Eylül (07) -> Polat Alemdar (08)",
        "center_x": 850,
        "crop_x_offset": 546,
        "spanned_shots": [7, 8],
        "subshots": [
            {
                "shot_id": 7,
                "duration_s": 1.320,
                "center_x": 740,
                "crop_x_offset": 436,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 8,
                "duration_s": 1.280,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Call & Response Phase 2; Elif intense direct camera eye contact playing with pearls, "
            "cutting to Polat upward dual-shoulder shrug on snare hit."
        ),
    },
    {
        "index": 6,
        "name": "clip_06_strophe_swagger_strut.mp4",
        "start_s": 41.680,
        "end_s": 46.520,
        "duration_s": 4.840,
        "rel_start_s": 14.416,
        "rel_end_s": 19.256,
        "target_character": "Elif Eylül (09) -> Polat Alemdar (10, 11)",
        "center_x": 960,
        "crop_x_offset": 656,
        "spanned_shots": [9, 10, 11],
        "subshots": [
            {
                "shot_id": 9,
                "duration_s": 1.280,
                "center_x": 800,
                "crop_x_offset": 496,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 10,
                "duration_s": 1.280,
                "center_x": 980,
                "crop_x_offset": 676,
                "character": "Polat Alemdar",
            },
            {
                "shot_id": 11,
                "duration_s": 2.280,
                "center_x": 1000,
                "crop_x_offset": 696,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Emotional strophe & swagger strut; Elif seated prayer/wrist snap, cutting to "
            "Polat rhythmic lateral torso sway and low-angle dynamic strut down steps "
            "('Davra glide')."
        ),
    },
    {
        "index": 7,
        "name": "clip_07_duo_charm_finger_wag.mp4",
        "start_s": 46.520,
        "end_s": 52.760,
        "duration_s": 6.240,
        "rel_start_s": 19.256,
        "rel_end_s": 25.496,
        "target_character": "Duo (Polat Alemdar + Elif Eylül)",
        "center_x": 910,
        "crop_x_offset": 606,
        "spanned_shots": [12, 13, 14, 15, 16],
        "subshots": [
            {
                "shot_id": 12,
                "duration_s": 1.440,
                "center_x": 870,
                "crop_x_offset": 566,
                "character": "Duo",
            },
            {
                "shot_id": 13,
                "duration_s": 1.280,
                "center_x": 990,
                "crop_x_offset": 686,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 14,
                "duration_s": 1.200,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Polat + Ensemble",
            },
            {
                "shot_id": 15,
                "duration_s": 1.240,
                "center_x": 890,
                "crop_x_offset": 586,
                "character": "Elif Eylül",
            },
            {
                "shot_id": 16,
                "duration_s": 1.080,
                "center_x": 860,
                "crop_x_offset": 556,
                "character": "Duo",
            },
        ],
        "choreography": (
            "Duo charm & playful finger wag; intercut romantic gestures, backward lean on "
            "velvet steps, ensemble unison pelvic bounce, and playful finger wag into lens."
        ),
    },
    {
        "index": 8,
        "name": "clip_08_canyon_transition_stomp.mp4",
        "start_s": 52.760,
        "end_s": 57.240,
        "duration_s": 4.480,
        "rel_start_s": 25.496,
        "rel_end_s": 29.976,
        "target_character": "Polat Alemdar (with White Corps)",
        "center_x": 920,
        "crop_x_offset": 616,
        "spanned_shots": [17, 18, 19],
        "subshots": [
            {
                "shot_id": 17,
                "duration_s": 1.600,
                "center_x": 920,
                "crop_x_offset": 616,
                "character": "Polat Alemdar",
            },
            {
                "shot_id": 18,
                "duration_s": 1.240,
                "center_x": 880,
                "crop_x_offset": 576,
                "character": "White Corps",
            },
            {
                "shot_id": 19,
                "duration_s": 1.640,
                "center_x": 930,
                "crop_x_offset": 626,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Outdoor canyon shift; navy jacket archway swagger, white dancers arm thrust "
            "at start of 19s break, and center-stage Lazgi stomp on red cubes."
        ),
    },
    {
        "index": 9,
        "name": "clip_09_canyon_double_point.mp4",
        "start_s": 57.240,
        "end_s": 63.160,
        "duration_s": 5.920,
        "rel_start_s": 29.976,
        "rel_end_s": 35.896,
        "target_character": "Polat Alemdar (with White Corps)",
        "center_x": 980,
        "crop_x_offset": 676,
        "spanned_shots": [20, 21, 22, 23, 24],
        "subshots": [
            {
                "shot_id": 20,
                "duration_s": 0.840,
                "center_x": 1050,
                "crop_x_offset": 746,
                "character": "White Corps",
            },
            {
                "shot_id": 21,
                "duration_s": 1.280,
                "center_x": 930,
                "crop_x_offset": 626,
                "character": "Polat Alemdar",
            },
            {
                "shot_id": 22,
                "duration_s": 1.120,
                "center_x": 1120,
                "crop_x_offset": 816,
                "character": "White Corps",
            },
            {
                "shot_id": 23,
                "duration_s": 1.720,
                "center_x": 940,
                "crop_x_offset": 636,
                "character": "Polat Alemdar",
            },
            {
                "shot_id": 24,
                "duration_s": 0.960,
                "center_x": 1000,
                "crop_x_offset": 696,
                "character": "White Corps",
            },
        ],
        "choreography": (
            "Canyon dance break & iconic double point; wrist snap pans, low-angle elbow pump "
            "groove, explosive 'Peshta Double-Point' into camera lens, and lateral arm whip."
        ),
    },
    {
        "index": 10,
        "name": "clip_10_elif_red_steps.mp4",
        "start_s": 63.160,
        "end_s": 64.760,
        "duration_s": 1.600,
        "rel_start_s": 35.896,
        "rel_end_s": 37.496,
        "target_character": "Elif Eylül",
        "center_x": 650,
        "crop_x_offset": 346,
        "spanned_shots": [25],
        "subshots": [
            {
                "shot_id": 25,
                "duration_s": 1.600,
                "center_x": 650,
                "crop_x_offset": 346,
                "character": "Elif Eylül",
            },
        ],
        "choreography": (
            "Return to red studio; Elif seated on red steps, arms crossed tightly "
            "over chest clutching pearls with mysterious, elegant gaze."
        ),
    },
    {
        "index": 11,
        "name": "clip_11_polat_hero_outro.mp4",
        "start_s": 64.760,
        "end_s": 70.264,
        "duration_s": 5.504,
        "rel_start_s": 37.496,
        "rel_end_s": 43.000,
        "target_character": "Polat Alemdar",
        "center_x": 1020,
        "crop_x_offset": 716,
        "spanned_shots": [26, 27],
        "subshots": [
            {
                "shot_id": 26,
                "duration_s": 3.440,
                "center_x": 1120,
                "crop_x_offset": 816,
                "character": "Polat Alemdar",
            },
            {
                "shot_id": 27,
                "duration_s": 2.064,
                "center_x": 960,
                "crop_x_offset": 656,
                "character": "Polat Alemdar",
            },
        ],
        "choreography": (
            "Polat Alemdar atop pyramid steps; extended signature dinosaur wrist flick with smirk, "
            "ending in statuesque hero pose at attention as music transitions to Verse 2."
        ),
    },
]

# Backward compatibility alias
MACRO_DRIVING_CLIPS = CLIPS_CONFIG


def check_prerequisites():
    """Verify input file and ffmpeg availability."""
    if not RAW_VIDEO.is_file():
        raise FileNotFoundError(f"Source video not found: {RAW_VIDEO}")

    for tool in ["ffmpeg", "ffprobe"]:
        try:
            subprocess.run(
                [tool, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            raise RuntimeError(f"Required tool '{tool}' is not available in PATH.") from None


def build_crop_expression(clip_def: dict[str, Any], dynamic: bool = False) -> str:
    """
    Constructs the FFmpeg crop x-coordinate expression.

    If dynamic=True and 'subshots' contains multiple distinct crop_x_offsets,
    compiles a time-evaluated expression:
        if(lt(t, T1), X1, if(lt(t, T2), X2, X3))
    Otherwise, returns the static integer crop_x_offset.
    """
    fallback_offset = clip_def.get("crop_x_offset", 656)
    subshots = clip_def.get("subshots", [])

    if not dynamic or not subshots:
        return str(fallback_offset)

    offsets = [s.get("crop_x_offset", fallback_offset) for s in subshots]
    if len(set(offsets)) <= 1:
        return str(fallback_offset)

    cuts: list[tuple[float, int]] = []
    current_t = 0.0
    for s in subshots[:-1]:
        current_t += s["duration_s"]
        cuts.append((round(current_t, 3), s.get("crop_x_offset", fallback_offset)))

    expr = str(offsets[-1])
    for cut_t, cut_offset in reversed(cuts):
        expr = f"if(lt(t,{cut_t:.3f}),{cut_offset},{expr})"

    return f"'{expr}'"


def cleanup_obsolete_clips():
    """Removes any MP4 files in driving_clips/ not present in CLIPS_CONFIG."""
    valid_names = {clip["name"] for clip in CLIPS_CONFIG}
    for file_path in OUTPUT_DIR.glob("*.mp4"):
        if file_path.name not in valid_names:
            print(f"  [PURGED] Removing obsolete clip: {file_path.name}")
            file_path.unlink()


def slice_clip(
    clip_def: dict[str, Any], overwrite: bool = False, dynamic_crop: bool = False
) -> Path:
    """Slice and reframe a single driving clip with FFmpeg."""
    out_path = OUTPUT_DIR / clip_def["name"]
    if out_path.is_file() and not overwrite:
        print(f"  [SKIPPED] {clip_def['name']} already exists.")
        return out_path

    start_s = clip_def["start_s"]
    duration_s = clip_def["duration_s"]
    x_expr = build_crop_expression(clip_def, dynamic=dynamic_crop)

    # Filter chain:
    # 1. crop: takes 9:16 vertical slice (width = in_h * 9 / 16) with dynamic or static x
    # 2. scale: Lanczos upscaling to standard 1080x1920 portrait resolution
    # 3. setsar: forces 1:1 square pixel aspect ratio
    # 4. fps: conforms 25fps input to constant 30.0 fps
    vf = (
        f"crop=w='in_h*9/16':h=in_h:x={x_expr}:y=0,"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:flags=lanczos,"
        f"setsar=1,fps={TARGET_FPS}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(RAW_VIDEO),
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        vf,
        "-r",
        str(TARGET_FPS),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(out_path),
    ]

    print(
        f"  [RENDERING] {clip_def['name']} "
        f"(ss={start_s:.3f}s, dur={duration_s:.3f}s, x={x_expr})..."
    )
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed rendering {clip_def['name']}:\n{res.stderr}")

    return out_path


def probe_clip(file_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Query technical parameters of rendered clip using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,codec_name,pix_fmt,duration,nb_frames",
        "-show_entries",
        "format=duration,size,bit_rate",
        "-of",
        "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)

    v_stream = next((s for s in data.get("streams", []) if s.get("codec_name") == "h264"), None)
    if not v_stream and data.get("streams"):
        v_stream = data["streams"][0]

    fmt = data.get("format", {})
    return v_stream or {}, fmt


def generate_shot_table_md():
    """Generates the comprehensive SHOT_TABLE.md markdown file."""
    num_clips = len(CLIPS_CONFIG)
    lines = [
        "# Promo Peshta — Milestone 1 (M1) Macro Driving Shot Table",
        "",
        "## Technical Calibration & Synchronization Architecture",
        "- **Master Reference Video**: `marketing/campaigns/peshta/raw/Xamdam_Sobirov_Peshta_1080p_h264.mp4` "
        "(1920x1080, 25 fps).",
        "- **Master Audio**: `/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3` "
        "(43.000s, 48kHz stereo Suno parody remix).",
        "- **Beat Drop Calibration**: Raw video sub-bass slam at $t = 34.184\\text{ s}$; "
        "MP3 drop slam at relative $t = 6.920\\text{ s}$.",
        f"- **Calibrated Video Window**: $t = {CALIBRATED_START_S:.3f}\\text{{ s}}$ "
        f"(Frame 682) to $t = {CALIBRATED_END_S:.3f}\\text{{ s}}$ (Frame 1757) — "
        f"total: **{TOTAL_DURATION:.3f} s**.",
        "- **Delivered Video Format**: 1080x1920 (9:16 portrait vertical), strictly 30.0 fps "
        "Constant Frame Rate (CFR), H.264 High Profile, `yuv420p`.",
        "",
        f"## {num_clips} Macro Driving Clips Inventory",
        "",
        (
            "| # | File Name | Source Range (s) | Rel Range (s) | Dur (s) | Frames (30fps) | "
            "Target Character | Crop Center X | Crop X Offset | "
            "Choreographic Action / Dance Phase |"
        ),
        ("|:---:|:---|:---:|:---:|:---:|:---:|:---|:---:|:---:|:---|"),
    ]

    total_frames = 0
    total_dur = 0.0

    for clip in CLIPS_CONFIG:
        file_path = OUTPUT_DIR / clip["name"]
        nb_frames = "?"
        if file_path.is_file():
            v_stream, _ = probe_clip(file_path)
            if v_stream and "nb_frames" in v_stream:
                nb_frames = int(v_stream["nb_frames"])
                total_frames += nb_frames
            elif v_stream and "duration" in v_stream:
                nb_frames = round(float(v_stream["duration"]) * TARGET_FPS)
                total_frames += nb_frames
        total_dur += clip["duration_s"]

        lines.append(
            f"| {clip['index']:02d} | `{clip['name']}` | "
            f"{clip['start_s']:.3f}s – {clip['end_s']:.3f}s | "
            f"{clip['rel_start_s']:.3f}s – {clip['rel_end_s']:.3f}s | "
            f"{clip['duration_s']:.3f}s | {nb_frames} | "
            f"{clip['target_character']} | {clip['center_x']} | "
            f"{clip['crop_x_offset']} | {clip['choreography']} |"
        )

    lines.extend(
        [
            "",
            f"**Total Sequence Duration:** {total_dur:.3f} s "
            f"({total_frames} frames at 30.0 fps CFR).",
            "",
            "## Crop Geometry & Centering Rationale",
            (
                "From native 1920x1080 widescreen footage, 9:16 vertical extraction "
                "requires slicing a window of width $W = 1080 \\times 9 / 16 = 607.5\\text{ px}$ "
                "(rounded to 608 px for even YUV chroma alignment)."
            ),
            "The crop formula applied per clip is:",
            "```text",
            "crop=w='in_h*9/16':h=in_h:x=X_OFFSET:y=0,scale=1080:1920:flags=lanczos,setsar=1,fps=30",
            "```",
            "Where `X_OFFSET = round(Center_X - 304)`.",
            "- **Clips 01, 03, 06**: Centered on pyramid steps "
            "($X = 960$, $X_{\\text{offset}} = 656$).",
            "- **Clip 02**: Centered on duo interaction ($X = 884$, $X_{\\text{offset}} = 580$).",
            "- **Clip 04 & 05**: Weighted for call-and-response close-ups with female lead and "
            "Hamdam shoulder pops ($X = 940$ / $X_{\\text{offset}} = 636$ and "
            "$X = 850$ / $X_{\\text{offset}} = 546$).",
            "- **Clip 07**: Centered on duo gestures and finger wag ($X = 910$, "
            "$X_{\\text{offset}} = 606$).",
            "- **Clip 08**: Centered on canyon archway ($X = 920$, $X_{\\text{offset}} = 616$).",
            "- **Clip 09**: Centered on canyon dance break and double-point ($X = 980$, "
            "$X_{\\text{offset}} = 676$).",
            "- **Clip 10**: Centered on Elif seated on red steps ($X = 650$, "
            "$X_{\\text{offset}} = 346$). Completely eliminates head cutoff (18% headroom).",
            "- **Clip 11**: Centered on Polat studio wrist flick and hero pose ($X = 1020$, "
            "$X_{\\text{offset}} = 716$).",
            "",
        ]
    )

    SHOT_TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[SHOT TABLE] Written to {SHOT_TABLE_PATH}")


def verify_all_clips():
    """Performs rigorous ffprobe verification across all configured clips."""
    num_clips = len(CLIPS_CONFIG)
    print("\n" + "=" * 90)
    print(f"VERIFYING GENERATED DRIVING CLIPS ({num_clips} Clips — Milestone 1 Acceptance Gate)")
    print("=" * 90)

    header = (
        f"{'#':<3} {'Clip Name':<35} {'Res':<10} {'FPS':<6} "
        f"{'Codec':<6} {'PixFmt':<8} {'Duration':<10} {'Frames':<8} {'Status':<6}"
    )
    print(header)
    print("-" * 90)

    total_duration = 0.0
    total_frames = 0
    all_passed = True

    for clip in CLIPS_CONFIG:
        file_path = OUTPUT_DIR / clip["name"]
        if not file_path.is_file():
            print(f"{clip['index']:<3} {clip['name']:<35} MISSING FILE")
            all_passed = False
            continue

        v_stream, fmt = probe_clip(file_path)
        width = int(v_stream.get("width", 0))
        height = int(v_stream.get("height", 0))
        r_fps = v_stream.get("r_frame_rate", "")
        codec = v_stream.get("codec_name", "")
        pix_fmt = v_stream.get("pix_fmt", "")
        dur = float(fmt.get("duration", 0.0))
        if "nb_frames" in v_stream:
            nb_frames = int(v_stream["nb_frames"])
        else:
            nb_frames = round(dur * TARGET_FPS)

        total_duration += dur
        total_frames += nb_frames

        # Assertions
        passed = (
            width == TARGET_WIDTH
            and height == TARGET_HEIGHT
            and r_fps == "30/1"
            and codec == "h264"
            and pix_fmt == "yuv420p"
            and abs(dur - clip["duration_s"]) <= 0.05
        )

        # Faststart verification
        try:
            with file_path.open("rb") as f:
                head = f.read(128 * 1024)
                moov_pos = head.find(b"moov")
                mdat_pos = head.find(b"mdat")
                if moov_pos == -1 or (mdat_pos != -1 and moov_pos >= mdat_pos):
                    passed = False
        except OSError:
            passed = False

        if not passed:
            all_passed = False

        status_str = "PASS" if passed else "FAIL"
        print(
            f"{clip['index']:<3} {clip['name']:<35} {width}x{height:<5} {r_fps:<6} "
            f"{codec:<6} {pix_fmt:<8} {dur:<10.3f} {nb_frames:<8} {status_str:<6}"
        )

    print("-" * 90)
    dur_delta = abs(total_duration - TOTAL_DURATION)
    print(
        f"Total Duration: {total_duration:.3f} s (Expected: {TOTAL_DURATION:.3f} s, "
        f"Delta: {dur_delta:.4f} s)"
    )
    print(f"Total Frames:   {total_frames} frames (Expected at 30fps: 1290 frames)")

    duration_check = abs(total_duration - TOTAL_DURATION) <= 0.05
    frame_check = total_frames == 1290

    print(f"Duration Match (±0.05s):  {'PASS' if duration_check else 'FAIL'}")
    print(f"Total Frame Count Match:  {'PASS' if frame_check else 'FAIL'}")
    print("=" * 90 + "\n")

    if not (all_passed and duration_check and frame_check):
        raise RuntimeError(
            "Verification gate failed! One or more clips do not meet Milestone 1 criteria."
        )

    print(f"All {num_clips} driving clips PASSED Milestone 1 technical verification.")


def main():
    parser = argparse.ArgumentParser(
        description="Decompose and crop driving clips for Promo Peshta M1."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing rendered driving clips.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only run verification on existing driving clips.",
    )
    parser.add_argument(
        "--dynamic-crop",
        action="store_true",
        help="Apply dynamic per-subshot crop expressions for multi-subshot clips.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean up obsolete driving clips not present in CLIPS_CONFIG.",
    )
    args = parser.parse_args()

    check_prerequisites()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.verify_only:
        print(f"\n[M1] Starting decomposition of {len(CLIPS_CONFIG)} Driving Clips...")
        cleanup_obsolete_clips()
        for clip in CLIPS_CONFIG:
            slice_clip(clip, overwrite=args.overwrite, dynamic_crop=args.dynamic_crop)
    elif args.clean:
        cleanup_obsolete_clips()

    generate_shot_table_md()
    verify_all_clips()


if __name__ == "__main__":
    main()
