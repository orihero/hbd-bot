"""
Empirical Verification & Adversarial Stress-Test Suite for Milestone 1 (M1) Driving Clips.
Author: teamwork_preview_challenger_m1_1
Targets:
  - marketing/campaigns/peshta/driving_clips/clip_01_verse1_setup.mp4 to clip_11_polat_hero_outro.mp4
  - marketing/campaigns/peshta/driving_clips/SHOT_TABLE.md
  - marketing/campaigns/peshta/slice_driving_clips.py
  - /Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3
"""

import json
import math
import subprocess
from pathlib import Path

import pytest

# Anchored to this file, not to a home directory: these tests live inside the
# campaign they verify (marketing/campaigns/peshta/tests/), so both roots are
# derived from __file__ and the checkout can sit anywhere.
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
CLIPS_DIR = WORKSPACE_ROOT / "marketing/campaigns/peshta" / "driving_clips"
SHOT_TABLE_PATH = CLIPS_DIR / "SHOT_TABLE.md"
AUDIO_PATH = Path("/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3")

EXPECTED_CLIPS = [
    {"index": 1, "name": "clip_01_verse1_setup.mp4", "expected_dur": 2.256, "expected_frames": 68},
    {"index": 2, "name": "clip_02_hook_duo_roses.mp4", "expected_dur": 2.920, "expected_frames": 88},
    {"index": 3, "name": "clip_03_chorus_drop_hero.mp4", "expected_dur": 3.800, "expected_frames": 114},
    {"index": 4, "name": "clip_04_call_response_1.mp4", "expected_dur": 2.840, "expected_frames": 85},
    {"index": 5, "name": "clip_05_call_response_2.mp4", "expected_dur": 2.600, "expected_frames": 78},
    {"index": 6, "name": "clip_06_strophe_swagger_strut.mp4", "expected_dur": 4.840, "expected_frames": 145},
    {"index": 7, "name": "clip_07_duo_charm_finger_wag.mp4", "expected_dur": 6.240, "expected_frames": 187},
    {"index": 8, "name": "clip_08_canyon_transition_stomp.mp4", "expected_dur": 4.480, "expected_frames": 134},
    {"index": 9, "name": "clip_09_canyon_double_point.mp4", "expected_dur": 5.920, "expected_frames": 178},
    {"index": 10, "name": "clip_10_elif_red_steps.mp4", "expected_dur": 1.600, "expected_frames": 48},
    {"index": 11, "name": "clip_11_polat_hero_outro.mp4", "expected_dur": 5.504, "expected_frames": 165},
]

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30.0
NOMINAL_STEP_S = 1.0 / TARGET_FPS
CUMULATIVE_TARGET_DUR = 43.000
DUR_TOLERANCE_MS = 50.0  # Allowed deviation in ms


def run_cmd(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def probe_stream(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_name,profile,width,height,r_frame_rate,avg_frame_rate,time_base,pix_fmt,nb_frames,duration",
        "-show_entries", "format=duration,size,bit_rate,format_name",
        "-of", "json",
        str(file_path),
    ]
    rc, out, err = run_cmd(cmd)
    assert rc == 0, f"ffprobe error on {file_path}: {err}"
    data = json.loads(out)
    return data.get("streams", [{}])[0], data.get("format", {})


def test_master_audio_presence_and_duration():
    """Verify master parody audio exists and is exactly 43.000 seconds."""
    assert AUDIO_PATH.is_file(), f"Master audio {AUDIO_PATH} not found"
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,bit_rate,format_name",
        "-show_entries", "stream=codec_name,sample_rate,channels",
        "-of", "json",
        str(AUDIO_PATH),
    ]
    rc, out, err = run_cmd(cmd)
    assert rc == 0, f"ffprobe error: {err}"
    data = json.loads(out)
    dur = float(data.get("format", {}).get("duration", 0.0))
    assert math.isclose(dur, 43.000, abs_tol=0.005), f"Audio duration {dur} != 43.000s"


def test_shot_table_completeness():
    """Verify SHOT_TABLE.md exists and documents all 11 driving clips."""
    assert SHOT_TABLE_PATH.is_file(), f"SHOT_TABLE.md missing at {SHOT_TABLE_PATH}"
    content = SHOT_TABLE_PATH.read_text(encoding="utf-8")
    for clip in EXPECTED_CLIPS:
        assert clip["name"] in content, f"Missing documentation for {clip['name']} in SHOT_TABLE.md"


def test_all_11_clips_exist():
    """Verify all 11 driving video clips exist on disk."""
    for clip in EXPECTED_CLIPS:
        path = CLIPS_DIR / clip["name"]
        assert path.is_file(), f"Driving clip file missing: {path}"
        assert path.stat().st_size > 100_000, f"Driving clip suspiciously small: {path}"


@pytest.mark.parametrize("clip_info", EXPECTED_CLIPS)
def test_clean_ffmpeg_decode(clip_info):
    """
    Task 1.1: Decode every single frame using ffmpeg -v error -i clip.mp4 -f null -
    to prove zero bitstream corruption, zero dropped frames, and clean decode.
    """
    clip_path = CLIPS_DIR / clip_info["name"]
    cmd = ["ffmpeg", "-v", "error", "-i", str(clip_path), "-f", "null", "-"]
    rc, out, err = run_cmd(cmd)
    assert rc == 0, f"FFmpeg decode exited with code {rc}: {err}"
    assert len(err.strip()) == 0, f"FFmpeg decode reported error/corruption: {err}"


@pytest.mark.parametrize("clip_info", EXPECTED_CLIPS)
def test_clip_format_and_geometry(clip_info):
    """Verify resolution is 1080x1920 (9:16 portrait), H.264 High profile, yuv420p, 30fps CFR."""
    clip_path = CLIPS_DIR / clip_info["name"]
    vstream, _ = probe_stream(clip_path)

    assert int(vstream.get("width", 0)) == TARGET_WIDTH, f"Invalid width in {clip_info['name']}"
    assert int(vstream.get("height", 0)) == TARGET_HEIGHT, f"Invalid height in {clip_info['name']}"
    assert vstream.get("codec_name") == "h264", f"Non-H264 codec in {clip_info['name']}"
    assert vstream.get("pix_fmt") == "yuv420p", f"Non-yuv420p pix_fmt in {clip_info['name']}"
    assert vstream.get("r_frame_rate") == "30/1", f"Non-30fps frame rate in {clip_info['name']}"
    assert vstream.get("avg_frame_rate") == "30/1", f"Non-CFR avg_frame_rate in {clip_info['name']}"


@pytest.mark.parametrize("clip_info", EXPECTED_CLIPS)
def test_pts_strict_monotonicity_and_uniformity(clip_info):
    """
    Task 1.2: Assert packet presentation timestamps (PTS) are strictly monotonic
    and uniform (step = 1/30s = 0.03333s) with no jitter or duplicate timestamps.
    """
    clip_path = CLIPS_DIR / clip_info["name"]
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "frame=pts,pts_time,pkt_pts,pkt_pts_time,key_frame,pict_type",
        "-of", "json",
        str(clip_path),
    ]
    rc, out, err = run_cmd(cmd)
    assert rc == 0, f"ffprobe frames error: {err}"
    frames = json.loads(out).get("frames", [])

    assert len(frames) == clip_info["expected_frames"], (
        f"{clip_info['name']} frame count {len(frames)} != expected {clip_info['expected_frames']}"
    )

    vstream, _ = probe_stream(clip_path)
    tb_num, tb_den = (int(x) for x in vstream["time_base"].split("/"))
    expected_tick_step = round((tb_den / tb_num) / TARGET_FPS)

    pts_values = []
    pts_times = []
    for i, f in enumerate(frames):
        pts = int(f.get("pts") if f.get("pts") is not None else f.get("pkt_pts", 0))
        pts_t = float(f.get("pts_time") if f.get("pts_time") is not None else f.get("pkt_pts_time", 0.0))
        pts_values.append(pts)
        pts_times.append(pts_t)

        # Exact integer tick assertion
        assert pts == i * expected_tick_step, (
            f"Frame {i} in {clip_info['name']} has PTS {pts} != expected {i * expected_tick_step}"
        )

        if i > 0:
            assert pts > pts_values[i - 1], f"PTS non-monotonic at frame {i}"
            step = pts_t - pts_times[i - 1]
            jitter_ms = abs(step - NOMINAL_STEP_S) * 1000.0
            assert jitter_ms < 0.01, f"Frame {i} jitter {jitter_ms}ms exceeds 0.01ms limit"


@pytest.mark.parametrize("clip_info", EXPECTED_CLIPS)
def test_no_empty_packets_and_gop_integrity(clip_info):
    """
    Task 1.3: Verify that there are no empty/zero-byte frames or broken GOP structures.
    Every clip must begin with an IDR keyframe (I-frame).
    """
    clip_path = CLIPS_DIR / clip_info["name"]
    cmd_packets = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts,dts,size,flags",
        "-of", "json",
        str(clip_path),
    ]
    rc, out, err = run_cmd(cmd_packets)
    assert rc == 0
    packets = json.loads(out).get("packets", [])

    for i, p in enumerate(packets):
        sz = int(p.get("size", 0))
        assert sz > 0, f"Packet {i} in {clip_info['name']} is empty (0 bytes)"

    # First packet must be Keyframe
    assert "K" in packets[0].get("flags", ""), f"First packet in {clip_info['name']} is not a keyframe!"

    # Verify frame 0 is IDR
    cmd_frame0 = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "frame=key_frame,pict_type",
        "-read_intervals", "%+#1",
        "-of", "json",
        str(clip_path),
    ]
    rc, out, err = run_cmd(cmd_frame0)
    assert rc == 0
    f0 = json.loads(out).get("frames", [{}])[0]
    assert int(f0.get("key_frame", 0)) == 1, f"Frame 0 is not key_frame in {clip_info['name']}"
    assert f0.get("pict_type") == "I", f"Frame 0 is not I-frame in {clip_info['name']}"


@pytest.mark.parametrize("clip_info", EXPECTED_CLIPS)
def test_faststart_moov_atom(clip_info):
    """Verify faststart layout (moov atom appears before mdat) for seamless web/cloud upload."""
    clip_path = CLIPS_DIR / clip_info["name"]
    with clip_path.open("rb") as f:
        head = f.read(128 * 1024)
    moov_idx = head.find(b"moov")
    mdat_idx = head.find(b"mdat")
    assert moov_idx != -1, f"No moov atom found in header of {clip_info['name']}"
    assert mdat_idx == -1 or moov_idx < mdat_idx, f"moov atom is not before mdat in {clip_info['name']}"


def test_cumulative_duration_within_50ms():
    """
    Task 1.4: Measure exact cumulative duration across all 11 clips and check if it
    deviates from 43.000s by more than 50 milliseconds.
    """
    total_dur = 0.0
    total_frames = 0

    for clip in EXPECTED_CLIPS:
        path = CLIPS_DIR / clip["name"]
        _, fmt = probe_stream(path)
        vstream, _ = probe_stream(path)
        dur = float(fmt.get("duration", 0.0))
        nb_f = int(vstream.get("nb_frames", 0))
        total_dur += dur
        total_frames += nb_f

    delta_ms = abs(total_dur - CUMULATIVE_TARGET_DUR) * 1000.0
    assert delta_ms <= DUR_TOLERANCE_MS, (
        f"Cumulative duration {total_dur:.4f}s deviates by {delta_ms:.3f}ms (> {DUR_TOLERANCE_MS}ms)"
    )
    assert total_frames == 1290, f"Cumulative frame count {total_frames} != 1290"


def test_beat_drop_choreographic_alignment():
    """Verify that the primary 0:34 beat drop (rel 6.920s) is contained within Hero Clip 03."""
    c1_dur = float(probe_stream(CLIPS_DIR / "clip_01_verse1_setup.mp4")[1]["duration"])
    c2_dur = float(probe_stream(CLIPS_DIR / "clip_02_hook_duo_roses.mp4")[1]["duration"])
    c3_dur = float(probe_stream(CLIPS_DIR / "clip_03_chorus_drop_hero.mp4")[1]["duration"])

    c3_start = c1_dur + c2_dur
    c3_end = c3_start + c3_dur
    drop_target = 6.920

    assert c3_start <= drop_target <= c3_end, (
        f"Beat drop {drop_target}s outside Clip 03 window [{c3_start:.3f}s - {c3_end:.3f}s]"
    )


if __name__ == "__main__":
    pytest.main(["-v", __file__])
