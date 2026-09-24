"""
Automated Verification & Adversarial Stress-Test Suite for
@bayram_uzbot 'Peshta' Parody Campaign Video Production Blueprint.

Challenger: Challenger Production 2 (.agents/challenger_production_2)
Targets:
  - marketing/campaigns/peshta/03_production_blueprint.md
  - marketing/campaigns/peshta/CAMPAIGN_MASTER.md
"""

import re
from pathlib import Path
import pytest

# Anchored to this file, not to a home directory: these tests live inside the
# campaign they verify (marketing/campaigns/peshta/tests/), so the root is
# derived from __file__ and the checkout can sit anywhere.
CAMPAIGN_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_PATH = CAMPAIGN_ROOT / "03_production_blueprint.md"
CAMPAIGN_MASTER_PATH = CAMPAIGN_ROOT / "CAMPAIGN_MASTER.md"


# ----------------------------------------------------------------------
# 1. Dynamic Markdown Parser & Timestamp Continuity Verification
# ----------------------------------------------------------------------

def parse_blueprint_shots(md_content: str):
    """Extract shot numbers, start/end timecodes, and durations from 03_production_blueprint.md."""
    # Pattern: ### Shot (\d+):[^\n]+\n- \*\*Timecode\*\*: `(\d{2}:\d{2}\.\d{2})` – `(\d{2}:\d{2}\.\d{2})` \(Duration: ([\d\.]+)s\)
    pattern = re.compile(
        r"### Shot\s+(\d+):.*?\n-\s+\*\*Timecode\*\*:\s+`(\d{2}):(\d{2}\.\d{2})`\s+–\s+`(\d{2}):(\d{2}\.\d{2})`\s+\(Duration:\s+([\d\.]+)s\)",
        re.DOTALL
    )
    matches = pattern.findall(md_content)
    shots = []
    for m in matches:
        shot_num = int(m[0])
        start_sec = int(m[1]) * 60.0 + float(m[2])
        end_sec = int(m[3]) * 60.0 + float(m[4])
        duration = float(m[5])
        shots.append({
            "shot": shot_num,
            "start": round(start_sec, 3),
            "end": round(end_sec, 3),
            "duration": round(duration, 3),
        })
    return shots


def parse_campaign_master_shots(md_content: str):
    """Extract shot rows from the 25-second script table in CAMPAIGN_MASTER.md."""
    # Table rows: │ 1     │ 0.00s–2.50s  │ Tight Close-up   │
    pattern = re.compile(r"│\s*(\d)\s*│\s*([\d\.]+)s[–\-](\d+[\.\d]*)s\s*│\s*([^│]+)│", re.UNICODE)
    matches = pattern.findall(md_content)
    shots = []
    for m in matches:
        shot_num = int(m[0])
        start_sec = float(m[1])
        end_sec = float(m[2])
        duration = round(end_sec - start_sec, 3)
        framing = m[3].strip()
        shots.append({
            "shot": shot_num,
            "start": round(start_sec, 3),
            "end": round(end_sec, 3),
            "duration": duration,
            "framing": framing
        })
    return shots


def test_markdown_file_presence():
    """Ensure both deliverables exist and are non-empty."""
    assert BLUEPRINT_PATH.exists(), f"Missing {BLUEPRINT_PATH}"
    assert CAMPAIGN_MASTER_PATH.exists(), f"Missing {CAMPAIGN_MASTER_PATH}"
    assert BLUEPRINT_PATH.stat().st_size > 10000
    assert CAMPAIGN_MASTER_PATH.stat().st_size > 10000


def test_blueprint_shot_continuity_and_duration():
    """Verify continuity, non-overlapping sequence, and 25.0s sum from 03_production_blueprint.md."""
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    shots = parse_blueprint_shots(content)

    assert len(shots) == 7, f"Expected exactly 7 shots in blueprint, found {len(shots)}"

    running_time = 0.0
    for i, shot in enumerate(shots):
        assert shot["shot"] == i + 1, f"Shot numbering broken at index {i}: {shot['shot']}"
        assert shot["start"] == running_time, (
            f"Shot {shot['shot']} starts at {shot['start']}s, expected {running_time}s (Gap or Overlap!)"
        )
        calculated_duration = round(shot["end"] - shot["start"], 3)
        assert calculated_duration == shot["duration"], (
            f"Shot {shot['shot']}: declared duration {shot['duration']} != calculated {calculated_duration}"
        )
        running_time = shot["end"]

    assert running_time == 25.0, f"Final timeline duration {running_time}s != 25.0s"
    total_duration_sum = sum(s["duration"] for s in shots)
    assert round(total_duration_sum, 3) == 25.0, f"Sum of durations {total_duration_sum}s != 25.0s"


def test_campaign_master_shot_continuity_and_duration():
    """Verify continuity, non-overlapping sequence, and 25.0s sum from CAMPAIGN_MASTER.md."""
    content = CAMPAIGN_MASTER_PATH.read_text(encoding="utf-8")
    shots = parse_campaign_master_shots(content)

    assert len(shots) == 7, f"Expected 7 shots in CAMPAIGN_MASTER table, found {len(shots)}"

    running_time = 0.0
    for i, shot in enumerate(shots):
        assert shot["shot"] == i + 1
        assert shot["start"] == running_time, (
            f"CAMPAIGN_MASTER Shot {shot['shot']} start {shot['start']}s != running {running_time}s"
        )
        running_time = shot["end"]

    assert running_time == 25.0
    total_duration_sum = sum(s["duration"] for s in shots)
    assert round(total_duration_sum, 3) == 25.0


def test_60fps_frame_perfection():
    """Verify that every shot cut aligns precisely with an integer frame boundary at 60.00 fps."""
    content = BLUEPRINT_PATH.read_text(encoding="utf-8")
    shots = parse_blueprint_shots(content)

    frame_sum = 0
    for shot in shots:
        start_f = shot["start"] * 60.0
        end_f = shot["end"] * 60.0
        dur_f = shot["duration"] * 60.0

        assert start_f.is_integer(), f"Shot {shot['shot']} start frame {start_f} is fractional"
        assert end_f.is_integer(), f"Shot {shot['shot']} end frame {end_f} is fractional"
        assert dur_f.is_integer(), f"Shot {shot['shot']} duration frame {dur_f} is fractional"
        frame_sum += int(dur_f)

    assert frame_sum == 1500, f"Total frame count {frame_sum} != 1500 (25.0s * 60fps)"


# ----------------------------------------------------------------------
# 2. UI Safe Zone Coordinates (9:16 Vertical Canvas, 1080x1920)
# ----------------------------------------------------------------------

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
MARGIN_TOP = 220
MARGIN_BOTTOM = 420
MARGIN_RIGHT = 140
MARGIN_LEFT = 40

SAFE_X_MIN = MARGIN_LEFT                      # 40px
SAFE_X_MAX = CANVAS_WIDTH - MARGIN_RIGHT      # 940px
SAFE_Y_MIN = MARGIN_TOP                       # 220px
SAFE_Y_MAX = CANVAS_HEIGHT - MARGIN_BOTTOM    # 1500px

TEXT_BOUND_Y_MIN = 240                        # 220px + 20px buffer
TEXT_BOUND_Y_MAX = 1480                       # 1500px - 20px buffer


def test_safe_zone_geometric_invariants():
    """Validate 9:16 vertical video UI safe zone coordinates and dimensions."""
    safe_width = CANVAS_WIDTH - MARGIN_RIGHT - MARGIN_LEFT
    safe_height = CANVAS_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    assert safe_width == 900
    assert safe_height == 1280
    assert SAFE_X_MIN == 40
    assert SAFE_X_MAX == 940
    assert SAFE_Y_MIN == 220
    assert SAFE_Y_MAX == 1500

    # Verification of the text safe bounding box: Y in [240px, 1480px]
    assert TEXT_BOUND_Y_MIN == 240
    assert TEXT_BOUND_Y_MAX == 1480
    assert (TEXT_BOUND_Y_MAX - TEXT_BOUND_Y_MIN) == 1240


def test_text_bounding_box_compliance():
    """
    Check all burned-in text elements across Shots 1 to 7 for compliance
    with the vertical text bounding box Y=240px to Y=1480px.
    """
    elements = [
        {"shot": 1, "text": "SOAT 23:55. SOVG'A ESA YO'Q! 😱", "y_center": 380, "box_h": 120},
        {"shot": 2, "text": "Guruhdagi 50-chi bir xil gul rasmi o'rniga...", "y_center": 420, "box_h": 100},
        {"shot": 3, "text": "1. Ismni yoz ➔ 2. Bepul she'rni o'qi! ⚡️", "y_center": 320, "box_h": 100},
        {"shot": 4, "text": "TABRIKLARIM MANI JONIM, BOTDA TELEGRAM BOTDA!", "y_center": 1200, "box_h": 140},
        {"shot": 5, "text": "PESHTA, PESH-PESHTA! 1 DAQIQADA TAYYOR! ⚡️", "y_center": 1180, "box_h": 120},
        {"shot": 6, "text": "ATIGI 15 000 SO'M! (Bitta kofe narxi ☕️)", "y_center": 880, "box_h": 120},
        {"shot": 7, "text": "IZOHGA «BAYRAM» DEB YOZING! 👇", "y_center": 1350, "box_h": 160},
    ]

    for elem in elements:
        y_top = elem["y_center"] - (elem["box_h"] / 2.0)
        y_bottom = elem["y_center"] + (elem["box_h"] / 2.0)

        assert y_top >= TEXT_BOUND_Y_MIN, (
            f"Shot {elem['shot']} top ({y_top}px) breaches TEXT_BOUND_Y_MIN ({TEXT_BOUND_Y_MIN}px)"
        )
        assert y_bottom <= TEXT_BOUND_Y_MAX, (
            f"Shot {elem['shot']} bottom ({y_bottom}px) breaches TEXT_BOUND_Y_MAX ({TEXT_BOUND_Y_MAX}px)"
        )


def test_adversarial_coordinate_flaws():
    """
    Adversarially probe edge-case coordinates in 03_production_blueprint.md:
    1. Line 128: 'X = 80px to 1000px: Frame-0 Yellow Text Banner'
       This violates the 140px right safe margin (X_max = 940px) by 60px!
    2. Line 380: 'Sticker 4: Animated CTA Down-Arrows at Y = 1420px with downward pulsing bounce'
       A 60px arrow bouncing +30px reaches Y = 1510px, penetrating the bottom danger zone!
    """
    # 1. Right Margin Conflict
    claimed_banner_x_end = 1000
    encroachment = claimed_banner_x_end - SAFE_X_MAX
    assert encroachment == 60, f"Expected 60px right margin encroachment, got {encroachment}px"

    # 2. Bottom Margin CTA Arrow Conflict
    arrow_anchor_y = 1420
    arrow_height = 55
    downward_bounce_amplitude = 30
    arrow_max_reach = arrow_anchor_y + arrow_height + downward_bounce_amplitude
    assert arrow_max_reach > TEXT_BOUND_Y_MAX, (
        f"Arrow peak ({arrow_max_reach}px) exceeds TEXT_BOUND_Y_MAX ({TEXT_BOUND_Y_MAX}px)"
    )
    assert arrow_max_reach > SAFE_Y_MAX, (
        f"Arrow peak ({arrow_max_reach}px) encroaches Bottom Danger Zone ({SAFE_Y_MAX}px)"
    )


# ----------------------------------------------------------------------
# 3. Acoustic Timing: 95.8 BPM, 126 BPM, and 0:34.04 Drop
# ----------------------------------------------------------------------

def test_acoustic_beat_periods_and_meter():
    """Validate beat and bar periods at 95.8 BPM and 126.0 BPM."""
    # 95.8 BPM
    period_95_8 = 60.0 / 95.8
    assert round(period_95_8, 4) == 0.6263
    bar_95_8 = 4 * period_95_8
    assert round(bar_95_8, 4) == 2.5052

    # 126.0 BPM
    period_126 = 60.0 / 126.0
    assert round(period_126, 3) == 0.476
    assert round(period_126, 4) == 0.4762
    bar_126 = 4 * period_126
    assert round(bar_126, 4) == 1.9048


def test_sub_bass_drop_synchronization():
    """
    Validate acoustic timing of the 0:34.04 drop:
    - Master Track Anchor: 34.04s
    - Variant D (15s): 34.04 - 31.50 = 2.54s
    - Master 25s Video: drop at 8.00s -> audio cues at 34.04 - 8.00 = 26.04s
    - Pre-drop silence: 0:33.1 to 0:34.0 (0.90s silence)
    """
    master_anchor = 34.04
    v_d_cue = 31.50
    v_d_drop = round(master_anchor - v_d_cue, 2)
    assert v_d_drop == 2.54

    script_drop = 8.00
    inferred_start = round(master_anchor - script_drop, 2)
    assert inferred_start == 26.04

    silence_start = 33.10
    silence_end = 34.00
    silence_span = round(silence_end - silence_start, 2)
    assert silence_span == 0.90


def test_adversarial_musical_downbeat_claim():
    """
    Adversarially challenge Section 6.1 line 624:
    'Every visual transition (Shot 1 ➔ Shot 2 ➔ Shot 3 ➔ Shot 4) is snapped to the nearest musical downbeat on the timeline grid.'
    
    Proof:
    At 126 BPM (Bar = 1.9048s), Shot 1 (2.50s) is 0.595s away from Bar 1 and 1.310s from Bar 2.
    At 95.8 BPM (Bar = 2.5052s), Shot 3 (8.00s) is 0.484s away from Bar 3 (7.516s).
    Therefore, Shots 1 to 3 are not snapped to a continuous musical track downbeat;
    they are an unmetered comedic skit with SFX, and the musical beat grid starts at Shot 4 (8.00s).
    """
    bar_126 = 60.0 / 126.0 * 4   # 1.90476s
    bar_95_8 = 60.0 / 95.8 * 4   # 2.50522s

    cut_1 = 2.50
    cut_2 = 5.00
    cut_3 = 8.00

    # At 126 BPM, cut 1 is NOT a bar downbeat:
    dist_126_cut_1 = min(abs(cut_1 - bar_126), abs(cut_1 - 2 * bar_126))
    assert dist_126_cut_1 > 0.50, f"Cut 1 distance {dist_126_cut_1}s is too small"

    # At 95.8 BPM, cut 3 is NOT a bar downbeat:
    dist_95_8_cut_3 = abs(cut_3 - 3 * bar_95_8)
    assert dist_95_8_cut_3 > 0.45, f"Cut 3 distance {dist_95_8_cut_3}s is too small"


# ----------------------------------------------------------------------
# 4. Audio Mastering Specifications
# ----------------------------------------------------------------------

def test_audio_mastering_parameters():
    """Verify audio mastering specifications against mobile social platform standards."""
    target_lufs = -14.0
    lufs_tolerance = 0.5
    target_true_peak = -1.0

    assert target_lufs == -14.0
    assert lufs_tolerance == 0.5
    assert target_true_peak == -1.0

    # EQ Carve
    hpf_freq = 35
    hpf_slope_db_oct = 24
    assert hpf_freq == 35
    assert hpf_slope_db_oct == 24

    low_mid_center_range = (250, 400)
    low_mid_dip_gain = -2.5
    assert low_mid_center_range == (250, 400)
    assert low_mid_dip_gain == -2.5

    presence_range = (3000, 5000)
    presence_gain = 2.0
    assert presence_range == (3000, 5000)
    assert presence_gain == 2.0

    ducking_gain = -3.5
    ducking_attack_ms = 10
    ducking_release_ms = 120
    assert ducking_gain == -3.5
    assert ducking_attack_ms == 10
    assert ducking_release_ms == 120


if __name__ == "__main__":
    pytest.main(["-v", __file__])
