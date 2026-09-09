# HBD Studio — identity

Every file here is hand-built vector geometry. **No fonts are involved**, including in the
wordmark: `h`, `b`, `d` and the six letters of `STUDIO` are drawn from circles and
round-capped bars, so nothing shifts if a font is missing, unlicensed, or substituted by a
print shop. Open any file in a text editor and the construction is readable.

## The system

One flame, one bar width, one rhythm:

| | |
|---|---|
| Bar width | 9 units, fully rounded (`rx` = half the width) |
| Bar rhythm | heights 22 / 36 / 29 — a 3 : 5 : 4 step, deliberately not symmetric |
| Flame | identical on all three candles, ~0.8 × bar width, ~1.95 × as tall as wide |
| Wick gap | 1.2 units at display sizes, closed to 0 in the small cut |
| Stroke (wordmark) | 12 units, round caps — the same softness as the bars |

The flame is the only coloured element anywhere. That is the rule that holds the set
together, and it is why the mark still reads at 16 px: one spot of magenta is what the eye
finds first.

## Files

| File | Use |
|---|---|
| `mark-level-meter.svg` | **The mark.** Anything 24 px and up. |
| `mark-level-meter-small.svg` | Below 24 px — favicon, dense UI. Chunkier bars, flame welded to the wick. |
| `mark-level-meter-mono.svg` | One colour, inherits `currentColor`. For stamps, embroidery, single-colour print. |
| `mark-level-meter-reversed.svg` | All white, for magenta or photographic grounds. |
| `avatar-telegram.svg` / `.png` / `.jpg` | The Telegram bot picture. PNG is 512 × 512, which is what BotFather wants; the JPEG is the same image with the alpha flattened, because `setMyProfilePhoto` takes JPEG only — see `python -m hbd.tools.identity`. |
| `wordmark-hbd.svg` | `hbd` with its three ascenders lit. |
| `wordmark-studio.svg` | `STUDIO`, tracked to sit exactly 140 units wide. |
| `lockup-stacked.svg` | `hbd` over `STUDIO`. The default lockup. |
| `lockup-horizontal.svg` | `hbd STUDIO` on one line, baselines shared. For wide, short spaces. |
| `mark-candle-mic.svg` | Secondary mark — see below. |
| `mark-level-meter-512.png` | The mark at 512 × 512, transparent ground. |
| `mark-candle-mic-512.png` | The secondary mark at 512 × 512, transparent ground. |
| `icon-level-meter-512.png` | The mark reversed out of a magenta disc, 512 × 512. App/store icon. |
| `icon-candle-mic-512.png` | The same treatment for the secondary mark. |

## Colour

| Token | Hex | Where |
|---|---|---|
| Ink | `#1C1620` | Candles, letterforms. A near-black with a violet bias, not a pure black. |
| Flame | `#BD32AF` | Flames only. Inherited from the admin panel's `--brand-solid`. |
| Reversed | `#FFFFFF` | Everything, on a `#BD32AF` ground. |

## Rules

**Clear space** — one bar width (9 units, or one ninth of the mark's height) on every side.
The 64 × 64 artboards already carry it.

**Minimum sizes** — mark 16 px; wordmark 60 px wide; stacked lockup 64 px wide. Below
24 px switch to the small cut.

**Do not lock the symbol to the wordmark.** The wordmark already carries three candles;
putting the symbol beside it makes six, and neither one leads. Use the symbol alone (avatar,
favicon, app icon) or the wordmark alone (everywhere else).

Also: do not recolour the candles, do not add a second colour to the flame, do not outline
the mark, and do not set the flames at different sizes — one flame size across all three
candles is what makes them read as flames rather than as a mistake.

## The secondary mark

`mark-candle-mic.svg` — a studio microphone wearing the same flame. It is the more literal
mark and reads at any size; keep it for places where the product needs to explain itself
faster than the level meter can (a listing thumbnail, an app store icon, a sticker), and
keep the level meter as the primary everywhere else.

## Regenerating

The geometry is generated, not drawn by hand in an editor. Re-deriving it means re-running
the construction that produced these files — change a constant (bar width, flame ratio, the
3 : 5 : 4 rhythm) and every file stays consistent with the others. Exporting a new PNG:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --default-background-color=00000000 \
  --screenshot=brand/avatar-telegram.png --window-size=512,512 \
  file://$PWD/brand/avatar-telegram.svg
```

And the JPEG cut the Bot API needs, alpha flattened:

```sh
sips -s format jpeg -s formatOptions best \
  brand/avatar-telegram.png --out brand/avatar-telegram.jpg
```
