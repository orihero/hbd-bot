#!/bin/bash
# cut.sh <take.mp4> <out.mp4> <in_point_seconds> <frames> [scale_pct]
set -euo pipefail
SRC="$1"; OUT="$2"; SS="$3"; FR="$4"; SC="${5:-100}"
BASE="fps=30,scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920"
if [ "$SC" = "100" ]; then
  VF="${BASE},setsar=1,format=yuv420p"
else
  VF="${BASE},scale=trunc(iw*${SC}/200)*2:trunc(ih*${SC}/200)*2:flags=lanczos,crop=1080:1920,setsar=1,format=yuv420p"
fi
ffmpeg -hide_banner -loglevel error -y -i "$SRC" -ss "$SS" -frames:v "$FR" -vf "$VF" \
  -c:v libx264 -preset slow -crf 14 -r 30 -an \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv "$OUT"
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$OUT"
