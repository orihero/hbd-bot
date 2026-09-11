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
| [`product/`](product/) | What is being built and why: scope of work, the admin-panel plans, and the payment-rail, billing-console and broadcast specifications. | Living until shipped, then historical |
| [`research/`](research/) | Investigations that fed a decision — benchmarks, vendor teardowns, unit economics, bake-off prompts. | Frozen at their date; correct by adding, not editing |
| [`audits/`](audits/) | Point-in-time reviews of something that already exists. | Frozen at their date |
| [`mockups/`](mockups/) | Standalone HTML design mockups. Not built, not served, not tested. | Superseded by the real UI |

## What is where

### `deployment/` — the operational tree

**Eleven** numbered documents, `00`–`10`, indexed by
[`deployment/README.md`](deployment/README.md). Start there for anything to do with the running
system: releasing a change, standing up a host, or a symptom you are looking at right now. `10`
is the newest: the `hbd` → `bayram` rename cutover, as its own page because it is an
all-or-nothing operation with its own rollback.

> **Read its STATUS block first, because that tree is in two halves.** Three documents —
> [`deployment/00-host-inventory.md`](deployment/00-host-inventory.md),
> [`deployment/08-payme.md`](deployment/08-payme.md) and
> [`deployment/09-payme-go-live.md`](deployment/09-payme-go-live.md) — and now
> [`deployment/10-rename-cutover.md`](deployment/10-rename-cutover.md) are written against the
> production host and date every claim they make; 00 was re-checked row by row on 2026-09-11.
> **`01`–`07` were derived from this repository alone until 2026-09-11, when every one of them was
> reconciled against the machine** — they now carry between 29 and 68 dated `[HOST]` marks each.
> A sentence in them without such a mark is still a claim about the repository, not about `aizu`:
> the absence of the mark is the signal.
> **Where the inventory disagrees with one of them, the inventory wins.** Three further warnings
> live in that STATUS block and are easy to trip over. (1) **There is a blocking defect on the
> host right now**: the migration role has no rights on schema `public`, so `alembic upgrade head`
> cannot run and revision `0025` is stuck on disk — 00 row 50. (2) The host still runs the
> pre-rename `hbd` names, so host paths quoted in those four documents must not be swept by a
> rename pass — **and the host is pre-rename because the cutover of 2026-09-10 FAILED, not
> because nobody ran it; it left `/etc/bayram` and `/opt/bayram` behind as debris** (00 row 49).
> (3) `deploy/` is a proposal whose `/srv/bayram` shape does not exist on the host.

### `decisions/`

- [`DECISIONS.md`](decisions/DECISIONS.md) — the vendor and architecture picks, numbered
  (`D1`, `D2`, …, currently through `D15`) and cited by number from code comments throughout
  `src/bayram/`. Those citations are by number, not by path, so they survive this file moving.
  The two newest are about the admin console rather than a vendor: **D14** draws the line
  between what the panel may do to a payment and what stays in the terminal, and **D15** records
  which of the two SPAs in this repository is the deployed one.

### `product/`

- [`SCOPE_OF_WORK.md`](product/SCOPE_OF_WORK.md) — §4 functional requirements, §6
  architecture. Cited by section from code and from `deployment/`.
- [`ADMIN_PANEL_PLAN.md`](product/ADMIN_PANEL_PLAN.md) — the admin panel's specification.
  Cited by section (`§4.2`, `§4.5`, `§12.1`) from a dozen places in `src/bayram/admin/`.
- [`ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md`](product/ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md)
- [`ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md`](product/ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md)
- [`PAYME_INTEGRATION.md`](product/PAYME_INTEGRATION.md) — the Payme Merchant API rail: the
  two seams, both state machines, the one-commit perform, and the decisions taken while going
  live (§8.6). Cited by section (`PAYME_INTEGRATION §3.2`) from `src/bayram/payme/`,
  `src/bayram/db/` and migration 0023. It specifies `DECISIONS.md` **D11**. **Its STATUS block
  holds three facts that are all true at once and are routinely collapsed into one: the gateway is
  deployed and running; the rail is OFF (the bot builds `StubCheckoutProvider`, so no customer can
  pay); and as of 2026-09-10 the full path `CreateTransaction → PerformTransaction → receipt and
  credit in one commit → ARQ job → Telegram message` HAS been executed on the production host
  against a real sandbox cashbox — 4/4 scenarios at 13:30 +05, with the settlement invariant
  corroborating at `1, 1, 1`. "Settlement has been proven" and "money can move" remain different
  sentences (§8.6.3).** The host half of it is
  [`deployment/08-payme.md`](deployment/08-payme.md), and the *sequence* — which gates are
  open, who closes each, and the command that proves it — is
  [`deployment/09-payme-go-live.md`](deployment/09-payme-go-live.md), deliberately in one place
  rather than narrated twice. Gate C (settlement) and four of Gate B's six facts closed on
  2026-09-10; **Gate A, the rename, is the one that has been attempted and failed** — see
  [`deployment/10-rename-cutover.md`](deployment/10-rename-cutover.md) and
  `deployment/00-host-inventory.md` rows 49–50.
- [`BILLING_RAIL_BOARD.md`](product/BILLING_RAIL_BOARD.md) — the admin console's Billing / Rail
  Board over the Payme rail: the three switches and which of them the admin process can actually
  read (§2), the twelve routes (§3), the payment dossier and its six-step lifeline (§4), where
  the chain stops and why a purchased credit cannot be traced to a song (§4.5), the settlement
  identity and why an all-zero result is not a pass (§5), the privacy contract (§6), retention
  and orphans (§7), and the empty state the section shipped into (§8). **§8.1 is dated 2026-09-10
  and describes a host that has since moved on**: it says `merchant_id` is literally `placeholder`
  and every count is `0`, and as of that afternoon the gateway carries a real sandbox cashbox and
  the database holds one performed transaction, one receipt and one grant. The *design* it
  explains — every count travelling beside a window-ignoring ROW probe, so `0` never has to mean
  two things — is exactly what makes that transition legible, and §8.2 predicted the shape of it.
  Read §8 as the reasoning, and `deployment/00-host-inventory.md` for what the board is actually
  looking at. To be cited
  by section (`BILLING_RAIL_BOARD §4.5`) from `src/bayram/db/admin/payment_intents.py`,
  `src/bayram/admin/routers/billing.py` and `admin-dashboard/src/features/billing/`. It specifies
  `DECISIONS.md` **D14** (the panel may find and may nudge; it may not mint) and **D15** (the
  console is `admin-dashboard`). Its operator half is
  [`deployment/09-payme-go-live.md`](deployment/09-payme-go-live.md) §11.
- [`BROADCAST_SPEC.md`](product/BROADCAST_SPEC.md) — the newsletter/broadcast feature: the segment
  DSL and its privacy allowlist (§1, §6.1), the campaign schema (§2), the API and its step-up (§3),
  the send pipeline (§4). To be cited by section (`BROADCAST_SPEC §4.4`) from
  `src/bayram/db/admin/segment.py` and `src/bayram/runtime/`. It specifies `DECISIONS.md` **D12**, and
  §6.3 records what the first build deliberately leaves out.

### `research/`

- [`BENCHMARK-song-generation.md`](research/BENCHMARK-song-generation.md) — why ElevenLabs
  won, and a "Corrections to DECISIONS.md" table that supersedes parts of `D2`.
- [`RESEARCH-brohit-teardown.md`](research/RESEARCH-brohit-teardown.md)
- [`RESEARCH-unit-economics-and-uzbek-vendors.md`](research/RESEARCH-unit-economics-and-uzbek-vendors.md)
- [`DASHBOARD_METRICS_RESEARCH.md`](research/DASHBOARD_METRICS_RESEARCH.md) — cited from
  `src/bayram/db/admin/vendor_usage.py`.
- [`bakeoff-prompts.md`](research/bakeoff-prompts.md) + `bakeoff-prompts.json` — the
  name-orthography bake-off. The verification command inside is written to run from the
  repository root.

### `audits/`

- [`ux-copy-audit.md`](audits/ux-copy-audit.md)

### `mockups/`

`admin-panel-mockup.html`, `dashboard-mockup.html`, `dashboard-mockup-full.html`. Open them
in a browser; nothing builds or serves them. The real console is `admin-dashboard/`, which is
what `make ui-build` builds and what the FastAPI app serves; `admin-ui/` is the deprecated
predecessor and receives no new features (`DECISIONS.md` **D15**).

## Citing a document from code

Prefer a **section number over a path** — `ADMIN_PANEL_PLAN §4.5`, `DECISIONS.md D10`. A
section number survives a file being moved; a path does not, and this reorganisation had to
rewrite twenty-two of them. Where a path is genuinely needed, write it from the repository
root (`docs/product/ADMIN_PANEL_PLAN.md`) so it is greppable and unambiguous.
