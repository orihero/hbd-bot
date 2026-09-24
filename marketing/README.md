# `marketing/`

How the product is taken to market, and the material the market sees. This is a sibling of
[`../docs/`](../docs/README.md) rather than a folder inside it, because only one of the three
subfolders below holds documents; the other two hold a shipped asset and two working trees of
scripts, ledgers and render output.

**The same rule applies here as in `docs/`: nothing lands loose.** Every file belongs to one of
the three folders below. Something that fits none of them needs a new folder and a new row in
this table.

| Folder | Holds | Lifecycle |
| --- | --- | --- |
| [`strategy/`](strategy/README.md) | The written record of how we go to market: trend research, the creative that came out of it, account design, and what it did. Has its own index. | Frozen at their date, and they rot fastest of anything in the repository |
| [`brand/`](brand/README.md) | The identity itself — the logo and the bot's profile copy. **Not just marketing: the product reads it.** | Living; a change here forces the four steps in its README |
| [`campaigns/`](#campaigns) | One folder per campaign: briefs, generation scripts, build ledgers, QA gates and the tests that verify the deliverables. | Frozen when the campaign ships |

## `brand/` is a product dependency, not decoration

`marketing/brand/Logo-Bot.png` is the source of truth for the cover art burned into every song
the bot delivers. The wheel cannot read this folder — `brand/` is not packaged — so the bytes
are **copied** to `src/bayram/audio/assets/cover.png`, and `tests/test_audio/test_cover.py`
fails if the two ever differ. That test is the only thing standing between a redrawn logo and a
month of songs shipping last month's cover.

So a logo change is not a file replacement. It is the four-step sequence written down in
[`brand/README.md`](brand/README.md): redraw, re-copy into the package, re-cut the flattened
JPEG, and push the new picture to Telegram with the identity tool. Skip step two and the test
catches it. Skip step four and the bot's avatar drifts from its own songs, which nothing
catches.

## `campaigns/`

Each campaign is a self-contained working tree. It is normal for one to hold Python, shell,
JSON and TSV alongside its Markdown — that is the point of keeping them out of `docs/`.

| Campaign | What it is |
| --- | --- |
| [`campaigns/peshta/`](campaigns/peshta/CAMPAIGN_MASTER.md) | The 43-second vertical reel: character concepts, parody lyrics, the production blueprint, the Higgsfield build (`05_build/`) and the local open-weight rebuild (`06_local/`). `CAMPAIGN_MASTER.md` is the entry point. **The Peshta ride itself is off** — the audio is unrecoverable on a rights-lineage block, not a quota — so read `FINAL_RECREATION_REPORT.md` and `strategy/`'s expiry notes before acting on anything here. |
| [`campaigns/viral-ideas/`](campaigns/viral-ideas/README.md) | Platform intelligence, Uzbek viral case studies, the concept slate and the weekly monitoring standard operating procedure. |
| [`campaigns/wellerman/`](campaigns/wellerman/CAMPAIGN_MASTER.md) | The Nathan Evans "Wellerman" Sea Shanty parody campaign: 10 situational/cultural lyrics variations, split-screen choir duet choreography, mobile acoustic mix standard, and viral UGC distribution plan. `CAMPAIGN_MASTER.md` is the entry point. |

### Media in a campaign is not committed

`.gitignore` drops video, image, `.m4a`, `.aac` and `.raw` under `marketing/campaigns/**`. The
peshta tree alone is about 1.2 GB of h264 and PNG frames, which is past what a Git host will
carry and is reproducible anyway: `05_build/LEDGER.tsv` and `05_build/MEDIA_IDS.tsv` record
what was generated and with which identifiers.

The globs are scoped to `campaigns/`, deliberately. A blanket `marketing/**` rule would ignore
`brand/Logo-Bot.png`, which is tracked and has to stay tracked for the cover-art test to mean
anything. A new campaign folder inherits the rules with no edit to `.gitignore`.

### A campaign's tests live with the campaign

[`campaigns/peshta/tests/`](campaigns/peshta/tests/) holds six files that assert against the
campaign's own deliverables — the lyric sheet, the blueprint, the sliced driving clips and the
assembled reel. They sit here rather than in `tests/` because `pytest` is configured with
`testpaths = ["tests"]`, and a campaign gate that needs ffmpeg and a 1080p master has no
business failing `make test` for somebody working on the bot.

Run them explicitly:

```bash
.venv/bin/python -m pytest marketing/campaigns/peshta/tests -v
```

Every path inside them is derived from `__file__`, so the checkout can sit anywhere. **One
external dependency is left and it is deliberate:** the two assembly tests read the
rightsholder's master from `~/Downloads`, which is not ours to carry into the repository. They
skip or fail loudly on a machine that does not have it.

## Where the rest of it is

- **Decisions** about marketing that bind the product — pricing shown in copy, what the bot may
  claim — belong in [`../docs/decisions/DECISIONS.md`](../docs/decisions/DECISIONS.md), not
  here. A claim in a playbook is a draft; a claim in `DECISIONS.md` is a commitment.
- **Research that fed a product decision** stays in
  [`../docs/research/`](../docs/research/), even when it is about a reel. Two documents there
  cite `campaigns/peshta/06_local/` by path: the A/B metrics reading and the render budget.
- **The bot's user-facing copy** is not marketing material. It is localized product strings
  under `src/bayram/i18n/`.
