# Project rules

## Where files go — the repository root is not a scratch pad

**Never create a Markdown or HTML document at the repository root.** The root holds
`README.md` and nothing else of that kind. Every other document belongs in one of three
indexed trees, in the folder that matches what it *is*.

| If the document is… | It goes in |
| --- | --- |
| how the system is provisioned, released, operated or debugged | `docs/deployment/` |
| a decision, with its fallback and the trigger that switches to it | `docs/decisions/` |
| what is being built and why — scope, specs, plans | `docs/product/` |
| an investigation that fed a decision — benchmark, teardown, costing | `docs/research/` |
| a point-in-time review of something that already exists | `docs/audits/` |
| a standalone HTML design mockup | `docs/mockups/` |
| how the product is taken to market — trend research, creative, what it did | `marketing/strategy/` |
| a campaign's brief, script, ledger or gate | `marketing/campaigns/<campaign>/` |
| the identity itself — logo, profile copy | `marketing/brand/` |
| somebody else's spec or export that we only read | `reference/<vendor>/` |

Each tree has an index and the same no-loose-files rule:
[`docs/README.md`](docs/README.md), [`marketing/README.md`](marketing/README.md),
[`reference/README.md`](reference/README.md). A document that fits no row above needs a
**new folder and a new row in the owning index** — not a loose file in `docs/`, and never a
file at the root.

**Which tree.** `docs/` is the product's written record. `marketing/` is how the product is
sold, and it is a sibling rather than a `docs/` subfolder because only its `strategy/` half
holds documents — the other two hold a shipped asset and campaign working trees of scripts,
ledgers and render output. `reference/` is material we did not write and only read.

This applies to throwaway output too. Analysis notes, migration plans, audit results and
"here is what I found" write-ups are documents: they go in the tree that fits, or — if they
are genuinely temporary and nobody will read them tomorrow — outside the repository
entirely, never at the root. `scratch/` was a 32 MB root folder of exactly this and was
deleted on 2026-09-21.

### Media and build output are never committed

`.gitignore` drops video, image, `.m4a`, `.aac` and `.raw` under `marketing/campaigns/**`,
which is about 1.2 GB in the peshta tree alone. The globs are scoped to `campaigns/` on
purpose: a blanket `marketing/**` rule would ignore `marketing/brand/Logo-Bot.png`, which is
tracked and has to stay tracked, because `tests/test_audio/test_cover.py` fails when it
drifts from the copy packaged at `src/bayram/audio/assets/cover.png`. A new campaign folder
inherits the rules with no edit.

### Tests belong to the thing they test

`pytest` runs `testpaths = ["tests"]`, and that suite is the product's. A campaign's own
gates live beside the campaign — `marketing/campaigns/peshta/tests/` — so that a check
needing ffmpeg and a 1080p master never fails `make test` for somebody working on the bot.
Run them by naming the path.

Anchor every path in such a test to `__file__`, never to a home directory. Six of these
tests were pinned to `/Users/…/hbd-bot` and had to be rewritten when the folder moved on
2026-09-21.

### Citing a document from code

Cite by **section number, not by path**: `ADMIN_PANEL_PLAN §4.5`, `DECISIONS.md D10`. A
section number survives the file moving; a path does not. Reorganising `docs/` on
2026-09-07 required rewriting twenty-two path citations across `src/`, `tests/`,
`migrations/` and `.env.example`; the 2026-09-21 reorganisation rewrote 457 lines across 77
files, most of them paths in prose.

When a path is genuinely needed, write it from the repository root —
`docs/product/ADMIN_PANEL_PLAN.md` — so it is greppable and unambiguous.

### Before moving or renaming a document

Grep for inbound references first, and fix them in the same change:

```bash
grep -rn --exclude-dir={node_modules,.git,.venv,__pycache__,.mypy_cache,dist,static} \
  -oE "(docs|marketing|reference)/[A-Za-z0-9_/-]+\.(md|html)" . | sort -u
```

A moved document that leaves dead links behind is worse than one that was never filed.

**Prose is not the only caller.** A bulk path rewrite will also hit Python import
statements, which look like paths and are not: `from promo_peshta.x import y` became
`from marketing/campaigns/peshta.x import y` on 2026-09-21 and did not parse. After any such
rewrite, compile what you touched.
