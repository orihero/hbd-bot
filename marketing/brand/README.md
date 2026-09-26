# Bayram — brand assets

Three files, and one of them is a product surface.

| File | What it is |
|---|---|
| `Logo-Bot.png` | **The logo.** 1254 × 1254. The blue robot with the gift, the phone and `@bayram_uzbot` set in its own typography. |
| `Logo-Bot.jpg` | The same image, alpha flattened. Exists only because the Bot API's `setMyProfilePhoto` takes JPEG and nothing else. |
| `bot-decoration.json` | The copy pack — bot name, About, description, tagline, ad lines, in three locales, with the reasoning for every line kept beside it. |

## `Logo-Bot.png` is not a listing asset

It is duplicated at `src/bayram/audio/assets/cover.png`, where `bayram.audio.cover` resizes
it to 320 × 320 and encodes it as the cover art of **every** song — the whole picture, not a
mark composited onto one. So it is what a recipient sees in their music player and what a
stranger sees in a forwarded chat. Treat an edit to it as a product change, not a design one.

It is a copy rather than a reference because the application is installed as a wheel and
`marketing/brand/` is not packaged. The full-size source is copied rather than a pre-scaled cut, so
`tests/test_audio/test_cover.py` can assert byte-identity instead of comparing a resampling
result that shifts between Pillow versions.

**After editing `Logo-Bot.png`, re-copy it:**

```sh
cp marketing/brand/Logo-Bot.png src/bayram/audio/assets/cover.png
```

Forgetting is a failing test, not a silent divergence — the test names that command in its
failure message.

**And re-cut the JPEG,** or the Telegram profile photo drifts from the cover art:

```sh
sips -s format jpeg -s formatOptions best marketing/brand/Logo-Bot.png --out marketing/brand/Logo-Bot.jpg
python -m bayram.tools.identity change --photo marketing/brand/Logo-Bot.jpg
```

## Because the logo carries the handle in its own pixels

`@bayram_uzbot` is drawn into the artwork. That is why `bayram.audio.cover` draws no text of
its own — two typefaces on one square — and it is also the one thing that makes the file
expensive to change: a rename, a second handle, or a move to `bayrambot.uz` as the primary
address means redrawing the logo, re-copying it, re-cutting the JPEG, and re-setting the bot
photo. Four steps, all of them listed above.

## What used to be here

An unused vector identity — a level-meter mark of three candles, a candle-mic secondary
mark, a `BAYRAM`/`STUDIO` wordmark and two lockups, a magenta Telegram avatar, and six
rejected logo proposals under `proposals/` with the script that generated them. None of it
was referenced by any code path, none of it had ever shipped, and the wordmark and both
lockups still drew the letters `h`, `b`, `d` from before the rename. Removed 2026-09-18;
it is in the git history if a future identity pass wants to start from it rather than from
a blank page.
