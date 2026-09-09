# `docs/`

Everything written down about this product except [`../README.md`](../README.md), which is
the developer entry point and stays at the repository root because that is where a reader
looks first.

**One rule governs this directory: nothing lands at the repository root, and nothing lands
loose in `docs/` either.** Every file belongs to exactly one of the folders below. If a new
document fits none of them, the honest move is a new folder with a line in this table — not
a file in `docs/` with no home.

| Folder | Holds | Lifecycle |
| --- | --- | --- |
| [`deployment/`](deployment/README.md) | How the system is provisioned, released, operated and debugged. Has its own index. | Living — must track reality |
| [`decisions/`](decisions/DECISIONS.md) | Decisions taken, each with its named fallback and the trigger that switches to it. | Append-only; supersede, never rewrite |
| [`product/`](product/) | What is being built and why: scope of work, the admin-panel plans, and the payment-rail and broadcast specifications. | Living until shipped, then historical |
| [`research/`](research/) | Investigations that fed a decision — benchmarks, vendor teardowns, unit economics, bake-off prompts. | Frozen at their date; correct by adding, not editing |
| [`audits/`](audits/) | Point-in-time reviews of something that already exists. | Frozen at their date |
| [`mockups/`](mockups/) | Standalone HTML design mockups. Not built, not served, not tested. | Superseded by the real UI |

## What is where

### `deployment/` — the operational tree

Ten documents, indexed by [`deployment/README.md`](deployment/README.md). Start there for
anything to do with the running system: releasing a change, standing up a host, or a symptom
you are looking at right now.

> **Read its STATUS block first.** Every claim in that tree is derived from this repository
> and verified against code. Nothing in it was verified against the production host, and
> [`deployment/00-host-inventory.md`](deployment/00-host-inventory.md) is deliberately empty
> until somebody fills it in.

### `decisions/`

- [`DECISIONS.md`](decisions/DECISIONS.md) — the vendor and architecture picks, numbered
  (`D1`, `D2`, …) and cited by number from code comments throughout `src/hbd/`. Those
  citations are by number, not by path, so they survive this file moving.

### `product/`

- [`SCOPE_OF_WORK.md`](product/SCOPE_OF_WORK.md) — §4 functional requirements, §6
  architecture. Cited by section from code and from `deployment/`.
- [`ADMIN_PANEL_PLAN.md`](product/ADMIN_PANEL_PLAN.md) — the admin panel's specification.
  Cited by section (`§4.2`, `§4.5`, `§12.1`) from a dozen places in `src/hbd/admin/`.
- [`ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md`](product/ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md)
- [`ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md`](product/ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md)
- [`PAYME_INTEGRATION.md`](product/PAYME_INTEGRATION.md) — the Payme Merchant API rail: the
  two seams, both state machines, the one-commit perform, and the go-live sequence. Cited by
  section (`PAYME_INTEGRATION §3.2`) from `src/hbd/payme/`, `src/hbd/db/` and migration 0023.
  It specifies `DECISIONS.md` **D11**, and the host half of it is
  [`deployment/08-payme.md`](deployment/08-payme.md).
- [`BROADCAST_SPEC.md`](product/BROADCAST_SPEC.md) — the newsletter/broadcast feature: the segment
  DSL and its privacy allowlist (§1, §6.1), the campaign schema (§2), the API and its step-up (§3),
  the send pipeline (§4). To be cited by section (`BROADCAST_SPEC §4.4`) from
  `src/hbd/db/admin/segment.py` and `src/hbd/runtime/`. It specifies `DECISIONS.md` **D12**, and
  §6.3 records what the first build deliberately leaves out.

### `research/`

- [`BENCHMARK-song-generation.md`](research/BENCHMARK-song-generation.md) — why ElevenLabs
  won, and a "Corrections to DECISIONS.md" table that supersedes parts of `D2`.
- [`RESEARCH-brohit-teardown.md`](research/RESEARCH-brohit-teardown.md)
- [`RESEARCH-unit-economics-and-uzbek-vendors.md`](research/RESEARCH-unit-economics-and-uzbek-vendors.md)
- [`DASHBOARD_METRICS_RESEARCH.md`](research/DASHBOARD_METRICS_RESEARCH.md) — cited from
  `src/hbd/db/admin/vendor_usage.py`.
- [`bakeoff-prompts.md`](research/bakeoff-prompts.md) + `bakeoff-prompts.json` — the
  name-orthography bake-off. The verification command inside is written to run from the
  repository root.

### `audits/`

- [`ux-copy-audit.md`](audits/ux-copy-audit.md)

### `mockups/`

`admin-panel-mockup.html`, `dashboard-mockup.html`, `dashboard-mockup-full.html`. Open them
in a browser; nothing builds or serves them. The real console is `admin-ui/`.

## Citing a document from code

Prefer a **section number over a path** — `ADMIN_PANEL_PLAN §4.5`, `DECISIONS.md D10`. A
section number survives a file being moved; a path does not, and this reorganisation had to
rewrite twenty-two of them. Where a path is genuinely needed, write it from the repository
root (`docs/product/ADMIN_PANEL_PLAN.md`) so it is greppable and unambiguous.
