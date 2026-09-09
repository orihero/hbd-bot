# Project rules

## Where files go — the repository root is not a scratch pad

**Never create a Markdown or HTML document at the repository root.** The root holds
`README.md` and nothing else of that kind. Every other document belongs in `docs/`, in the
folder that matches what it *is* — see [`docs/README.md`](docs/README.md) for the table.

| If the document is… | It goes in |
| --- | --- |
| how the system is provisioned, released, operated or debugged | `docs/deployment/` |
| a decision, with its fallback and the trigger that switches to it | `docs/decisions/` |
| what is being built and why — scope, specs, plans | `docs/product/` |
| an investigation that fed a decision — benchmark, teardown, costing | `docs/research/` |
| a point-in-time review of something that already exists | `docs/audits/` |
| a standalone HTML design mockup | `docs/mockups/` |

`docs/` itself is an index, not a folder to drop files into. A document that fits none of
the folders above needs a **new folder and a new row in `docs/README.md`** — not a loose
file in `docs/`, and never a file at the root.

This applies to throwaway output too. Analysis notes, migration plans, audit results and
"here is what I found" write-ups are documents: they go in `docs/`, or — if they are
genuinely temporary and nobody will read them tomorrow — in the scratchpad directory
outside the repository, never at the root.

### Citing a document from code

Cite by **section number, not by path**: `ADMIN_PANEL_PLAN §4.5`, `DECISIONS.md D10`. A
section number survives the file moving; a path does not. Reorganising `docs/` on
2026-09-07 required rewriting twenty-two path citations across `src/`, `tests/`,
`migrations/` and `.env.example`.

When a path is genuinely needed, write it from the repository root —
`docs/product/ADMIN_PANEL_PLAN.md` — so it is greppable and unambiguous.

### Before moving or renaming a document

Grep for inbound references first, and fix them in the same change:

```bash
grep -rn --exclude-dir={node_modules,.git,.venv,__pycache__,.mypy_cache,dist,static} \
  -oE "docs/[A-Za-z0-9_/-]+\.(md|html)" . | sort -u
```

A moved document that leaves dead links behind is worse than one that was never filed.
