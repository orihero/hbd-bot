#!/bin/bash
# still2clip.sh <in.png> <out.mp4> <frames> <zoom_end> [drift_px_per_frame]
set -euo pipefail
IN="$1"; OUT="$2"; FR="$3"; ZE="$4"; DRIFT="${5:-0}"
ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$IN" -frames:v "$FR" \
  -vf "scale=2160:3840:flags=lanczos,zoompan=z='min(1.0+(${ZE}-1.0)*on/(${FR}-1),${ZE})':x='iw/2-(iw/zoom/2)+(${DRIFT})*on':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,setsar=1,format=yuv420p" \
  -c:v libx264 -preset slow -crf 14 -r 30 -an \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv "$OUT"
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$OUT"
