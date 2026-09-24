#!/usr/bin/env python3
"""
Burn Captions & Static CTA Overlay onto Final Polat Peshta Reel

Visual Configuration:
- Captions: Style A (Kinetic Gold #FFE600 with black outline & drop shadow, centered at Y=1310px).
- Bottom CTA: c6.png encapsulated in frosted dark glassmorphism pill badge with gold border, centered at Y=1600px.
- Timing: Beat-drop synchronized (Verse 1–4 across intro 0.0s–6.92s, Chorus 5–8 across 6.92s–43.0s).
"""

import os
import sys
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
OVERLAYS_DIR = BASE_DIR / "overlays"
OUTPUT_DIR = BASE_DIR / "rendered_clips"
INPUT_VIDEO = BASE_DIR / "final_polat_peshta_reel.mp4"
OUTPUT_VIDEO = BASE_DIR / "final_polat_peshta_reel_captioned.mp4"
CARD_PATH = BASE_DIR / "cards" / "c6.png"
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
if not FONT_PATH.exists():
    FONT_PATH = Path("/System/Library/Fonts/Helvetica.ttc")

LYRIC_LINES = [
    ("cap_01.png", "Gul keltirsam ikki kunda\nsoʻlib qoladi", 0.000, 5.400),
    ("cap_02.png", "Mersedesga choʻntak\nkuyib kuyib yonadi", 5.400, 10.500),
    ("cap_03.png", "Bayrambotga ismini yoz\nbir zum boʻladi", 10.500, 15.380),
    ("cap_04.png", "Qoʻshiq aytsa quvonchidan\nkoʻzi toʻladi", 15.380, 20.340),
    ("cap_05.png", "Bayram xonim mani, jonim botda\nBAYRAM-BOTDA!", 20.340, 25.780),
    ("cap_06.png", "Sovgʻa izlab sarson boʻlma,\nbotda Bayram-botda!", 25.780, 30.600),
    ("cap_07.png", "O mani kuydirding,\no mani suydirding,", 30.600, 35.440),
    ("cap_08.png", "Ismi bilan qoʻshiq tayyor,\ntingla peshta peshta!", 35.440, 43.000),
]



def render_overlay_assets():
    """Generates transparent RGBA overlay PNGs for the bottom CTA card and captions."""
    OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Render bottom CTA pill card
    print("[1/4] Generating bottom CTA pill card overlay...")
    if not CARD_PATH.exists():
        raise FileNotFoundError(f"Card asset not found: {CARD_PATH}")

    card = Image.open(CARD_PATH).convert("RGBA")
    bbox = card.getbbox()
    text_crop = card.crop(bbox)  # 766x175

    cta_img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    pad_x, pad_y = 32, 18
    crop_x = (1080 - text_crop.width) // 2  # 157
    crop_y = 1600

    rect = [
        crop_x - pad_x,
        crop_y - pad_y,
        crop_x + text_crop.width + pad_x,
        crop_y + text_crop.height + pad_y,
    ]
    ov_draw = ImageDraw.Draw(cta_img)
    ov_draw.rounded_rectangle(
        rect, radius=24, fill=(0, 0, 0, 190), outline=(255, 230, 0, 230), width=3
    )
    cta_img.paste(text_crop, (crop_x, crop_y), text_crop)
    cta_out = OVERLAYS_DIR / "overlay_cta_card.png"
    cta_img.save(cta_out)
    print(f"      Saved: {cta_out}")

    # 2. Render 8 Caption Overlays (Style A: Kinetic Gold)
    print("[2/4] Generating 8 lyric caption overlays...")
    font_caption = ImageFont.truetype(str(FONT_PATH), 46)

    for filename, text, start_t, end_t in LYRIC_LINES:
        cap_img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(cap_img)
        tbbox = draw.multiline_textbbox((0, 0), text, font=font_caption, align="center")
        text_w = tbbox[2] - tbbox[0]
        x = (1080 - text_w) // 2
        y = 1310

        # Draw drop shadow
        draw.text(
            (x + 3, y + 3),
            text,
            font=font_caption,
            fill=(0, 0, 0, 200),
            stroke_width=7,
            stroke_fill=(0, 0, 0, 200),
            align="center",
        )
        # Draw main text: Gold fill + crisp black outline
        draw.text(
            (x, y),
            text,
            font=font_caption,
            fill=(255, 230, 0, 255),
            stroke_width=5,
            stroke_fill=(0, 0, 0, 255),
            align="center",
        )

        cap_out = OVERLAYS_DIR / filename
        cap_img.save(cap_out)
        print(f"      Saved {filename} [{start_t:5.2f}s -> {end_t:5.2f}s] (w={int(text_w)}px)")


def composite_video():
    """Executes FFmpeg filtergraph to composite the overlays onto the master video."""
    print("[3/4] Compositing captions and CTA card with FFmpeg...")
    if not INPUT_VIDEO.exists():
        raise FileNotFoundError(f"Input video not found: {INPUT_VIDEO}")

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "warning",
        "-stats",
        "-i", str(INPUT_VIDEO),
        "-loop", "1", "-i", str(OVERLAYS_DIR / "overlay_cta_card.png"),
    ]

    # Add 8 caption inputs
    for filename, _, _, _ in LYRIC_LINES:
        cmd.extend(["-loop", "1", "-i", str(OVERLAYS_DIR / filename)])

    # Build filtergraph
    # Stream 0: Video base
    # Stream 1: CTA card (active for full 43.0s)
    # Streams 2..9: Captions 1..8
    filter_chains = ["[0:v][1:v]overlay=0:0:shortest=1[v0]"]
    for idx, (_, _, start_t, end_t) in enumerate(LYRIC_LINES):
        in_stream = f"[v{idx}]"
        next_stream = "[v_out]" if idx == len(LYRIC_LINES) - 1 else f"[v{idx + 1}]"
        filter_chains.append(
            f"{in_stream}[{idx + 2}:v]overlay=0:0:enable='between(t,{start_t:.3f},{end_t:.3f})'{next_stream}"
        )

    filter_complex = "; ".join(filter_chains)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "17",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-t", "43.000",
        str(OUTPUT_VIDEO),
    ])

    print("Running FFmpeg composite command...")
    res = subprocess.run(cmd, text=True)
    if res.returncode != 0:
        raise RuntimeError("FFmpeg compositing failed")
    print(f"Composited video generated successfully: {OUTPUT_VIDEO}")


def extract_sample_frames():
    """Extract sample frames to verify every caption line visually."""
    print("[4/4] Extracting sample verification frames for all 8 lyric lines...")
    sample_timestamps = [
        ("t01_line1_2.5s.png", 2.5),
        ("t02_line2_8.0s.png", 8.0),
        ("t03_line3_13.0s.png", 13.0),
        ("t04_line4_18.0s.png", 18.0),
        ("t05_line5_23.0s.png", 23.0),
        ("t06_line6_28.0s.png", 28.0),
        ("t07_line7_33.0s.png", 33.0),
        ("t08_line8_39.0s.png", 39.0),
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for fname, ts in sample_timestamps:
        out_frame = OUTPUT_DIR / f"verify_caption_{fname}"
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{ts:.2f}",
            "-i", str(OUTPUT_VIDEO),
            "-vframes", "1",
            str(out_frame),
        ]
        subprocess.run(cmd, check=True)
        print(f"      Extracted: {out_frame}")


if __name__ == "__main__":
    render_overlay_assets()
    composite_video()
    extract_sample_frames()
    print("\nOverlay and Captioning Process Complete!")
