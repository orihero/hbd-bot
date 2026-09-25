# `docs/`

Everything written down about this product except [`../README.md`](../README.md), which is
the developer entry point and stays at the repository root because that is where a reader
looks first.

**One rule governs this directory: nothing lands at the repository root, and nothing lands
loose in `docs/` either.** Every file belongs to exactly one of the folders below. If a new
document fits none of them, the honest move is a new folder with a line in this table — not
a file in `docs/` with no home.

`docs/` is the *product's* written record. Two sibling trees at the repository root hold
writing that is not about the product: [`../marketing/`](../marketing/README.md), which is how
the product is taken to market, and [`../reference/`](../reference/README.md), which is
somebody else's material we only read. Both have their own index and the same no-loose-files
rule. **`marketing/` used to be `docs/marketing/` and moved out on 2026-09-21**, because it had
grown a brand folder and two campaign working trees — scripts, ledgers and 1.2 GB of render
output — and none of that is a document.

| Folder | Holds | Lifecycle |
| --- | --- | --- |
| [`deployment/`](deployment/README.md) | How the system is provisioned, released, operated and debugged. Has its own index. | Living — must track reality |
| [`decisions/`](decisions/DECISIONS.md) | Decisions taken, each with its named fallback and the trigger that switches to it. | Append-only; supersede, never rewrite |
| [`product/`](product/) | What is being built and why: scope of work, the admin-panel plans, the payment-rail, billing-console, broadcast, support-ticket and image/video specifications, and the admin-dashboard localization plan with its test specification. | Living until shipped, then historical |
| [`research/`](research/) | Investigations that fed a decision — benchmarks, vendor teardowns, unit economics, bake-off prompts. | Frozen at their date; correct by adding, not editing |
| [`audits/`](audits/) | Point-in-time reviews of something that already exists. | Frozen at their date |
| [`mockups/`](mockups/) | Standalone HTML design mockups. Not built, not served, not tested. | Superseded by the real UI |

## What is where

### `deployment/` — the operational tree

**Thirteen** numbered documents, `00`–`12`, indexed by
[`deployment/README.md`](deployment/README.md). Start there for anything to do with the running
system: releasing a change, standing up a host, or a symptom you are looking at right now. `12`
is the newest: [`deployment/12-media-gateway.md`](deployment/12-media-gateway.md), written
2026-09-25 with IMAGE_VIDEO_SPEC M2.6 — hardening the owner's generation gateway, the G1–G8
endpoints the owner installs on it, its sweeper and the `doctor` that proves it from the host;
none of it has been run on the box yet. Before it came
[`deployment/11-ci-cd.md`](deployment/11-ci-cd.md), written 2026-09-16 with the CI workflow it
describes and re-layered on 2026-09-19 — CI runs on every push, and continuous
*deployment* stops at the door deliberately, so a release is still one command a human runs on the
host. `10` is the `hbd` → `bayram` rename cutover, which kept its own page because it was an
all-or-nothing operation with its own rollback; that window has since closed.

> **Read its STATUS block first, because that tree is in two halves.** Three documents —
> [`deployment/00-host-inventory.md`](deployment/00-host-inventory.md),
> [`deployment/08-payme.md`](deployment/08-payme.md) and
> [`deployment/09-payme-go-live.md`](deployment/09-payme-go-live.md) — and now
> [`deployment/10-rename-cutover.md`](deployment/10-rename-cutover.md) are written against the
> production host and date every claim they make; 00 was re-checked row by row on 2026-09-11.
> **[`deployment/11-ci-cd.md`](deployment/11-ci-cd.md) belongs with them and reads slightly
> differently**: its host claims are dated and read-only-verified in prose (“verified read-only
> 2026-09-19”) rather than carried on a `[HOST]` mark, so grep for the date rather than for the
> bracket when you want to know what it actually looked at.
> **`01`–`07` were derived from this repository alone until 2026-09-11, when every one of them was
> reconciled against the machine** — they now carry between 29 and 68 dated `[HOST]` marks each.
> A sentence in them without such a mark is still a claim about the repository, not about `aizu`:
> the absence of the mark is the signal.
> **Where the inventory disagrees with one of them, the inventory wins.** Two warnings that stood
> here through the first half of September are now void, and both were struck on **2026-09-19**.
> **The blocking defect is closed**: role `hbd` had neither `USAGE` nor `CREATE` on schema
> `public`, so no migration could run — 00 row 50 now reads **RESOLVED 2026-09-14**, the same
> query from a live session returning `t|t|0025`, both privileges present and the head moved from
> `0024` to `0025`. **And the host is no longer pre-rename**: the `hbd` → `bayram` cutover was
> verified and its rollback window closed on **2026-09-14**, since when the four `bayram-*` units
> have been live and active
> ([`deployment/10-rename-cutover.md`](deployment/10-rename-cutover.md) §4.7,
> [`deployment/02-configuration.md`](deployment/02-configuration.md)). A release is now an ordinary
> wheel upgrade through `bayram-release`, not a cutover.
> **The instruction that used to sit beside that claim — that host paths in those pages must not
> be swept by a rename pass — is struck with it**, and struck here in writing rather than quietly,
> because the instruction is what kept the claim alive through every later pass over this file. What
> survives of it is narrower and still true: where one of those pages quotes a command or a path it
> read on the host *before* 2026-09-14, the `hbd` spelling is faithful to what the machine said that
> day and is history, not an error to correct. Rows 46 and 49 in 00 still *open* in the pre-cutover
> present tense — the divergence, and the cutover that failed — and both now carry a layer at the
> end that reverses the opening: 46 `SUPERSEDED 2026-09-14`, 49 `SUPERSEDED 2026-09-19`. Read a row
> of that table to its end before acting on its first sentence.
> **One of the three does survive, halved.** `deploy/` is no longer only a proposal: it holds
> artefacts that have been executed — `deploy/bayram-release`, which the host carries at
> `/opt/bayram/sbin/bayram-release` and which ran the first real deploy on 2026-09-17, and
> `deploy/install-bayram-backup.sh`, which exists and has still never been run there. What is still
> a proposal is [`deploy/first-install-proposal.md`](../deploy/first-install-proposal.md) and the
> `/srv/bayram` layout it and the `deploy/systemd/*.service` files beside it describe: the live host runs
> from `/opt/bayram` and `/etc/bayram`, and `/srv/bayram` does not exist on it.

### `decisions/`

- [`DECISIONS.md`](decisions/DECISIONS.md) — the vendor and architecture picks, numbered
  (`D1`, `D2`, …, currently through `D26`) and cited by number from code comments throughout
  `src/bayram/`. Those citations are by number, not by path, so they survive this file moving.
  The later ones are mostly about the product rather than a vendor: **D14** draws the line
  between what the panel may do to a payment and what stays in the terminal, **D15** records
  which of the two SPAs in this repository is the deployed one, **D16** settles how ElevenLabs
  music is metered, **D17** makes a settled payment start the render on a redirect rail,
  **D18** builds the support-ticket queue behind the ⚠️ button — four Kanban states, the
  Telegram support group as a staff surface with two-way reply, and a ticket body kept
  indefinitely rather than on a retention clock, **amended on 2026-09-15** so that the group
  is chosen in the admin panel instead of by an environment variable (the amendment sits under
  D18 rather than opening a new decision, because it changes only how the room is picked) — and
  **D19** records that the song price and
  the soʻm-per-USD rate are mirrored into the admin process **by hand**, with an unset pair
  rendering an em dash that names its own absence rather than a zero. D19's operator half is
  [`deployment/02-configuration.md`](deployment/02-configuration.md) §"The four finance
  variables", which is where to go when the Finances tab looks empty.
  **D20–D26**, all taken on 2026-09-24, are the image and video products and are specified by
  [`product/IMAGE_VIDEO_SPEC.md`](product/IMAGE_VIDEO_SPEC.md): **D20** adds the products and
  photo/voice-note intake, amending SCOPE §2.2, §3.2, FR-7, FR-96, LR-47, LR-51, LR-59 and D7's "no
  image model in the request path"; **D21** sells images rendered on local FLUX.2 [dev] as an owner
  **risk acceptance** against rejected #19; **D22** splits video into a local Standard tier (live)
  and a Higgsfield Fast tier (off) and puts paying customers ahead of marketing on the GPU; **D23**
  voices video with Gemini 3.8 TTS from an owner-supplied key pool (ToS risk accepted, rejected #11
  amended, D5 narrowed) and transcribes own voice notes with Whisper for moderation only (rejected
  #13 amended, D6 pointer); **D24** screens media with guard models on the owner's GPU, before payment
  and before delivery, failing closed; **D25** gives media its own SKU, receipt and refund credit,
  free for an admin allowlist on the stub rail until Payme production; **D26** puts a versioned
  Terms + Privacy acceptance in front of the whole bot. Each earlier `DECISIONS.md` entry they
  change (D5, D6, D7, D8, rejected #11, #13, #19) carries a dated amendment block where it is read;
  the SCOPE_OF_WORK items D20 and D26 amend receive theirs in the first media change
  (`IMAGE_VIDEO_SPEC` §10 M0.5), before any media code.

### `product/`

- [`SCOPE_OF_WORK.md`](product/SCOPE_OF_WORK.md) — §4 functional requirements, §6
  architecture. Cited by section from code and from `deployment/`.
- [`ADMIN_PANEL_PLAN.md`](product/ADMIN_PANEL_PLAN.md) — the admin panel's specification.
  Cited by section (`§4.2`, `§4.5`, `§12.1`) from a dozen places in `src/bayram/admin/`.
- [`ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md`](product/ADMIN_PANEL_PLANIQ_REDESIGN_PLAN.md) — the
  PlanIQ reskin: the same console on its own `PQ0`–`PQ10` workstream axis, orthogonal to the two
  documents above because it changes how the panel *looks* rather than what it does. **Read its
  STATUS block, dated 2026-09-19, before acting on anything in it**: the Playwright browser gate it
  names a dozen times no longer exists — it went with `admin-ui/` — and is deliberately not
  being restored, because its `webServer.command` was a Python module rather than `vite preview` and
  reviving it means two toolchains in one runner. What stands in its place is
  `tests/test_admin/test_csp_shape.py` in the Python job and
  `admin-dashboard/tests/built-shell-csp.ts` in the console job.
- [`PROJECT.md`](product/PROJECT.md) — the admin-dashboard localization project (`uz`, `ru`,
  `en`): the bespoke typed i18n store under `admin-dashboard/src/i18n/`, the three dictionaries it
  claims are key-for-key identical, the `LanguageSwitcher` and every screen that consumes `t()`,
  written up as a feature inventory by milestone. **Filed here on 2026-09-19 from the repository
  root, where it should never have been.** Two cautions for a reader: its feature table cites
  `ORIGINAL_REQUEST` by section, and `ORIGINAL_REQUEST.md` is no longer repository content — it
  was untracked and gitignored in the same pass — so the specification underneath it is not
  something a fresh clone can open; and it describes the console as built rather than as planned, so
  it reads as a record, not as a commitment.
- [`TEST_INFRA.md`](product/TEST_INFRA.md) — the test architecture for that localization work:
  the opaque-box position it takes (§1.1), the interface contract under test (§1.2), and the
  four-tier matrix specified tier by tier (§§2–6) before §7 describes the harness
  and the CI gate it asks for. Also filed from the root on 2026-09-19. It is the document
  [`deployment/11-ci-cd.md`](deployment/11-ci-cd.md) §1 names, with `TEST_READY.md`, as having
  prescribed a CI gate against a repository that had never run a check automatically in its life.
- [`TEST_READY.md`](product/TEST_READY.md) — the readiness report for that same suite, dated
  2026-09-08/09: 55 cases across the four tiers, what each tier validates, and the commands that run
  them from `admin-dashboard/`. The four tier files it names are on disk. **Read it as a claim its
  author made on that date, not as a current pass**; its own note of 2026-09-19, which is the
  current pass, records 55 run and 55 passed against §5's frozen `2 passed / 53 pending`. Read the
  comment above `usesI18n()` in `admin-dashboard/tests/tier1-features.test.ts` beside it, which
  records that the screen-coverage
  check originally asked `source.includes("t(")`, a substring that `useEffect(` and
  `setTimeout(` both satisfy, so F11–F18 reported PASS against files holding nothing but
  hardcoded English and the suite announced 53/55 while the real integration count was zero. It now
  requires an actual import from the i18n module. A readiness report is exactly the kind of document
  that cannot notice such a thing about itself.
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
  2026-09-10; **Gate A, the rename, closed on 2026-09-14** — it failed twice on 2026-09-10, and
  [`deployment/10-rename-cutover.md`](deployment/10-rename-cutover.md) carries both halves: the
  transcript of the failures and, at §4.7, the rollback window closing with the four `bayram-*`
  units live. `deployment/00-host-inventory.md` rows 49–50 are the evidence for the failures and
  for the `GRANT` that unblocked them, each under a layer added after the fact — row 50 reads
  **RESOLVED 2026-09-14**, row 49 **SUPERSEDED 2026-09-19**. *(Corrected here 2026-09-19.)*
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
- [`SUPPORT_TICKETS_SPEC.md`](product/SUPPORT_TICKETS_SPEC.md) — the ticket queue behind the ⚠️
  button and `/support`: the FSM-free customer flow and why it must stay that way (§1.2), the two
  tables of revision `0027` (§2), the Telegram group card, its once-only latch and the two-way
  reply (§3), the four Kanban states and their legal transitions (§4), the API and its
  deliberately step-up-free `support.write` (§5), and the privacy position (§7). **§3.8 is the
  2026-09-15 amendment**: the support group is no longer `BAYRAM_SUPPORT_GROUP_CHAT_ID` but a
  `bot_chats` row (revision `0028`) chosen in the panel on `support.group.write`, because
  Telegram has no "list my groups" API and the design is what that constraint leaves — §3.7,
  §5.1, §5.2, §6.1, §8 and §9 carry their own dated blocks. To be cited by
  section (`SUPPORT_TICKETS_SPEC §3.3`) from `migrations/versions/…_0027_…`,
  `src/bayram/db/models/support_ticket*.py`, `src/bayram/bot/` and
  `admin-dashboard/src/features/support/`. It specifies `DECISIONS.md` **D18**. **§7.2 is the
  section to read first**: the ticket body is kept **indefinitely** — no `*_expires_at`, no
  cutoff, no sweep — and `/forget` DELETEs a customer's tickets rather than anonymising them,
  which is the opposite of what every other table holding a Telegram id in this schema does. §7.3
  records what the first build deliberately leaves out, and §9 Q2/Q3/Q7 are the open questions
  that need a human: who is in the support group, whether indefinite retention has a lawful
  basis, and who may answer a customer unreviewed.
- [`IMAGE_VIDEO_SPEC.md`](product/IMAGE_VIDEO_SPEC.md) — the image and video products behind ✨
  Create, written 2026-09-24 as a **plan; nothing in it is built**. §0 is the ground truth and the
  owner's binding answers of that day; §2 the Terms gate and the image and video flows
  as state diagrams with their copy keys; §3 the `0029`/`0030` schema, retention and the stage-job
  chain; §4 the `MediaGenProvider` protocol, the local gateway's traps and the backend flags; §5
  Gemini TTS, the key pool and own voice notes; §6 moderation — including, at §6.1, the answer to
  the owner's local-LLM idea — and the song moderator's fail-open fix; §7 payments; §10 the M0–M6
  milestones; §11 the risk register, where three owner risk acceptances are recorded; §12 the open
  questions. Appendix A is a **DRAFT** Terms of Use and Privacy Notice outline, not legal advice and
  not in force. To be cited by section (`IMAGE_VIDEO_SPEC §4.2`). It specifies `DECISIONS.md`
  **D20–D26**.

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
- [`RESEARCH-ab-higgsfield-vs-local-reel-metrics.md`](research/RESEARCH-ab-higgsfield-vs-local-reel-metrics.md)
  — how to read the A/B metrics when the Peshta reel is rebuilt on local open-weight models.
  §2 is the per-metric worse/better/different table; §3 says which judgement the numbers
  cannot make. The harness is `marketing/campaigns/peshta/06_local/compare_ab.py`.
- [`RESEARCH-local-rebuild-render-budget.md`](research/RESEARCH-local-rebuild-render-budget.md)
  — the honest GPU budget for rebuilding the 43-second vertical reel locally: 38 generation
  units, 6–23 h wall clock, and the two-hour four-sub-shot experiment to run before
  committing to the night. Supersedes the "14 units, about 5 hours" figure — which never lived
  in `docs/` at all, so do not hunt for it here: it is in
  `marketing/campaigns/peshta/06_local/superseded/unit_plan.json`, and the superseding numbers are in
  `marketing/campaigns/peshta/06_local/render_budget.json`, the machine-readable companion to this page.
- [`RESEARCH-uzbek-pop-native-generation.md`](research/RESEARCH-uzbek-pop-native-generation.md)
  — dated 2026-09-19: why the Peshta Add-Vocal remix can never be downloaded lawfully — a
  rights-lineage break at somebody else's upload, not a quota that resets — and what to do
  instead, which is to keep our own Uzbek lyrics and rebuild the track natively in Suno with no
  upload anywhere in its history: the prompt vocabulary to use and the timbres to exclude, a
  95–102 BPM target tested at both ends, a deliberate pronunciation pass, and a Persona minted
  from the winning take so every later song carries the same voice. **It was filed correctly and
  linked from nowhere** until this row and the two in `marketing/` picked it up on 2026-09-19 — a
  document with no inbound reference is invisible, which is the failure this index is here to
  prevent.
- [`RESEARCH-image-video-pipeline.md`](research/RESEARCH-image-video-pipeline.md) — dated
  2026-09-24, frozen: what the owner's local GPU gateway actually does (video is slow, not broken —
  the older gateway README is stale), its API traps and security gaps, Gemini 3.8 TTS (Uzbek listed,
  unproven; limits per project, not per key), the Higgsfield REST API as distinct from the MCP, fal,
  the guard models considered for moderation, and unit economics for images and 5 s clips. Fed
  `DECISIONS.md` D20–D26; §7 points to what was chosen, which in three places is not what it
  recommended.

### `audits/`

- [`ux-copy-audit.md`](audits/ux-copy-audit.md)
- [`ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md`](audits/ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md) — the
  September 2026 audit of the admin panel, backend and frontend read together, and the redesign it
  argues for: credit accounts and the append-only ledger present in the database and absent from
  every screen, raw ISO timestamps, the peek panel that shoves the table down, hardcoded
  `isCostTelemetry: false`, and no revenue, funnel or GMV anywhere — each with the target state
  beside it. **Moved here from `product/` on 2026-09-19**, because it is a point-in-time review
  rather than a plan for what to build, and it had sat in the index for weeks with no description at
  all, which is why nobody could tell what it was. **It audits `admin-ui/`, the console removed on
  2026-09-16**, so read its findings as the reasoning that fed
  [`product/ADMIN_PANEL_PLAN.md`](product/ADMIN_PANEL_PLAN.md) rather than as a description of the
  console that ships today.

### `mockups/`

`admin-panel-mockup.html`, `dashboard-mockup.html`, `dashboard-mockup-full.html`. Open them
in a browser; nothing builds or serves them. The real console is `admin-dashboard/`, which is
what `make ui-build` builds and what the FastAPI app serves. It is now the only console in the
tree: `admin-ui/`, the deprecated predecessor, was removed on 2026-09-16 (`DECISIONS.md`
**D15**, and the amendment beneath it).

### `marketing/` — moved out on 2026-09-21

It is [`../marketing/`](../marketing/README.md) now, a sibling of `docs/` rather than a folder
inside it, and the seven numbered Instagram documents are under
[`../marketing/strategy/`](../marketing/strategy/README.md) with their index and their
supersession notes intact. Nothing was rewritten in the move except paths.

The reason is that the folder stopped being documents. It acquired `brand/` — the logo that
`tests/test_audio/test_cover.py` checks the packaged cover art against, so a *product* test now
reads it — and two campaign working trees carrying Python, shell, TSV ledgers and 1.2 GB of
render output. A `docs/` subfolder whose largest artefact is an h264 file is misfiled, and the
rule at the top of this page only works if it is not bent.

**Two of the research documents here still cite the Peshta campaign by path** and were
rewritten in the same change: the A/B harness is
`marketing/campaigns/peshta/06_local/compare_ab.py` and the render budget is
`marketing/campaigns/peshta/06_local/render_budget.json`.

## Citing a document from code

Prefer a **section number over a path** — `ADMIN_PANEL_PLAN §4.5`, `DECISIONS.md D10`. A
section number survives a file being moved; a path does not, and this reorganisation had to
rewrite twenty-two of them. Where a path is genuinely needed, write it from the repository
root (`docs/product/ADMIN_PANEL_PLAN.md`) so it is greppable and unambiguous.
