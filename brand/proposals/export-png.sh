#!/bin/sh
# 512 x 512 PNGs for every proposal.
#   mark-*-512.png    transparent ground, ink + flame       (docs, dark or light)
#   avatar-*-512.png  white out of a #BD32AF disc           (BotFather / app icon)
# The wordmark is centred in the same square so the set is one size throughout.
set -eu
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DIR=$(cd "$(dirname "$0")" && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

shoot() {  # shoot <src.svg> <out.png>
  "$CHROME" --headless=new --disable-gpu --default-background-color=00000000 \
    --force-device-scale-factor=1 --hide-scrollbars \
    --screenshot="$2" --window-size=512,512 "file://$1" 2>/dev/null
}

for f in "$DIR"/mark-*.svg; do
  b=$(basename "$f" .svg)
  sed 's/width="64" height="64"/width="512" height="512"/' "$f" > "$TMP/$b.svg"
  shoot "$TMP/$b.svg" "$DIR/$b-512.png"
  echo "$b-512.png"
done

for f in "$DIR"/avatar-*.svg; do
  b=$(basename "$f" .svg)
  shoot "$f" "$DIR/$b-512.png"
  echo "$b-512.png"
done

# wordmark: 448 units wide inside the 512 square, optically centred
{ printf '%s' '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" fill="none"><g transform="translate(32 184.4) scale(1.5238)">'
  sed -e '1s/^.*<svg[^>]*>//' -e 's|</svg>||' "$DIR/04-wordmark-bayram.svg" | tr -d '\n'
  printf '%s' '</g></svg>'; } > "$TMP/wm.svg"
shoot "$TMP/wm.svg" "$DIR/04-wordmark-bayram-512.png"
echo "04-wordmark-bayram-512.png"
