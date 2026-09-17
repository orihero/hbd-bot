# PlanIQ reskin — admin console migration plan

**Axis note.** This lane is `PQ-1 … PQ10`. It is deliberately a *fourth* name because three already
collide: `docs/product/ADMIN_PANEL_PLAN.md` §14 uses Phases 1–7 (feature delivery),
`docs/product/ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md` §6 uses Phases 1–3 (defect fixes), and WS0–WS8 exists
only in user memory and appears in no file in this repo. `PQ*` is orthogonal to all three: it changes
how the console *looks*, never what it *knows*. Where a PQ workstream touches a screen, it touches the
container and not the data.

**Not to be confused with the other axis this document introduces:** `data-palette`, the CSS attribute
that makes colour swappable at runtime (§2.0). `PQ*` names *workstreams*; `data-palette` names
*palettes*. Where "the axis" appears unqualified below, it is the palette one.

**Every ratio in this document was recomputed**, not quoted. The method: re-implement
`admin-ui/src/styles/tokenContrast.test.ts`'s arithmetic (`colorOf` → `over` → `relativeLuminance` →
`contrast` / `rgbDistance`) together with the full `SURFACES` / `FAMILIES` / `ORDER_STATES` /
`PIPELINE_STATUSES` / `tintGrounds` / `ROLES` / `GROUNDS` sets, and run it against the live
`tokens.css`. The harness reproduces the tree exactly before it is pointed at any candidate:
**0 role failures light, 0 dark, 35 light annotations + 33 dark with zero drift**, and the suite is
**101 files / 1409 tests, green in 6.5 s** (`npx vitest run` in `admin-ui/`, run this session).

**Effort scale, anchored once.** **S** ≤ 1 day · **M** ≤ 3 days · **L** ≤ 1 week · **XL** = more than
a week, and therefore *not allowed to exist* — the two XL workstreams in the first draft (PQ4, PQ8) are
split here into first-class lettered tranches, each with its own commit and its own revert tag.

---

## 1. The decision

**Status, 2026-09-07.** PQ1's gate work, the PlanIQ palette and the runtime switch were built; the
switch was then **removed at the user's direction** and the console moved to PlanIQ outright (§2.0).
`tokens.css` is two blocks keyed on `data-theme`, `gogo` is in git history, and the appearance change
that PQ2c was going to stage is simply landed. What survived the axis — complete blocks, anchored block
matching, the invariant/colour split — is described in §2.0 and is load-bearing.

**Matching PlanIQ means adopting its *grounds, geometry and rhythm*, and re-deriving its *inks*.** The
kit is 22 000 nodes of hand-built frames with no component library (`get_components` returns 200
components, all icons; `get_components(name:"button")` → 0), no radius scale, no spacing scale, no
elevation system, and — measured — no accessible foreground palette. Its brand green `#75FC96` is
**1.06:1** on this console's worst light ground and **1.30:1** on white: it misses the 3:1 graphic bar
by ~3× and the 4.5:1 text bar by ~4×. That is not a near miss to be negotiated; it is the single fact
that shapes the whole port. Inverted, the same green is **16.12:1 under black**, and PlanIQ's own CTA
labels and nav labels are `#000000` in both themes. So the honest reading of the kit is that **the
green is an action ground, not a hue family** — and that is exactly what we adopt: `--brand-solid:
#75fc96` with `--ink-on-brand: #000000`, replacing today's white-on-magenta at 4.95:1.

**But the button's label contrast and the button's *shape* are two different measurements, and only
one of them improves.** Today `--brand-solid` `#bd32af` is **4.75:1 against the page ground** and
**4.95:1 against a card**: the primary button is self-delimiting, a magenta rectangle you can see
without reading it. Under this plan `#75fc96` is **1.21:1 on `--surface` `#f6f6f6`** and **1.30:1 on
`--surface-card` `#ffffff`** — for a low-vision operator the button stops having a visible shape, and
only its label identifies it. That is the same defect this plan diagnoses in PlanIQ's own light nav
(`#FFFFFF` pills on a `#FFFFFF` bar), and it must not be reported as a pure win. The fix ships in the
same commit as the green: a **1px ring in PlanIQ's own deep green** `#218C3B` (the file-icon fold,
"Primary deep"), added as a new token `--brand-solid-edge` with its own `ROLES` entry at the 3:1
graphic bar. Measured: **3.98:1 on `--surface`, 4.30:1 on `--surface-card`, 3.78:1 on
`--surface-sunken`** in light; **4.39 / 4.00 / 4.27** in dark. Both numbers — 16.12:1 for the label,
1.21:1 for the ground plus 3.78:1 for the ring that replaces it — go into `buttonVariants.ts`'s header
table and into the deviation log.

We **reject the alternative branch**: a darker light-mode `--brand-solid` with the mint green reserved
for dark. It would give the console's most-clicked control a different hue per theme, and it would
throw away the 16.12:1 black-on-green label win precisely in the palette most operators sit in.

**We reject three more things flatly, and each rejection is measured rather than tasteful.**

*First, a green `--brand`/`--brand-fill`.* PlanIQ's own darkest green, `#218C3B`, measures **3.51:1 on
`--surface-control-hover`** — under the 4.5:1 text bar — so it cannot be a text member as it stands,
and it sits **38.8 rgbDistance from `--success`** and **41.9 from `--success-fill`**. Today's magenta
brand is **174** from `--success` (192 fill-to-fill), and the tightest *existing* family pair in the
palette is `neutral`/`slate` at 29. `--st-held` (= `--brand`) and `--st-delivered` (= `--success`) are
adjacent stacked segments in `StateDistributionBar`; two greens in that bar is one segment. So the hue
layer does not move at all, which incidentally costs zero `ROLES` edits on the nine families.

*Second, PlanIQ's density and its dark inset surfaces.* Its table cells are 12px, captions 10px and
status pills 8px on a 1440 canvas; this console renders Uzbek-Cyrillic recipient names and 32-char
correlation ids at an 11px floor. And its literal dark ramp (`#313131` input fill, `#474747` chart
track) fails **40** role-bar assertions when substituted — measured.

*Third, and most important, PlanIQ's silences.* `find_nodes(name:"empty")` returns **0 nodes** across
the entire document. There is no empty state, no loading state, no error state, no focus ring, no
invalid input, no disabled treatment (one lone pill), no permission-denied, no pagination and no
tooltip anywhere in the kit. Those are roughly 40% of what this console renders — `AsyncBoundary`
alone resolves six states, and `PurgedValue`, `NOT_INSTRUMENTED_LABEL`, `PermissionGate`-hides-never-
disables and the three-channel rule (glyph + word + hue) are all load-bearing operational vocabulary.
A faithful port would delete the most valuable half of the console, and the plan's job is to make that
impossible by re-skinning that vocabulary *deliberately and early* (PQ7) rather than letting it rot.

### 1.1 Three PlanIQ citations, corrected

The dossier is stronger than the first draft's summary of it, and the plan should not lean on claims
it does not support:

- **"PlanIQ never paints a word green except twice"** is false. It paints words green in at least five
  places: `Forgot password` (0:2948), `Sign up` (0:3037), the AI card's `Assist You Today?` tail, the
  8px/600 delta `4.3%` (0:4736), and the **44px Manrope bold OTP digits** (0:3145). Its tooling clears
  none of them; the two it flags as errors are the auth links. The 44px OTP digits are the strongest
  counter-example to "green is an action ground" and are named here so the argument is made against
  the kit's best case, not its worst.
- **`#E8E8E8` "Stock", 4188 nodes** is real, but the dossier's role for those nodes is
  hairline/track/border, never a control ground. The hex is PlanIQ's; the role is ours.
- **`#F0F0F0`** appears in the kit only as the AI-chat rail's attachment-thumbnail ground and as
  `bg/sub-250` in a variable collection the dossier calls vestigial (no node binds to it). It is not
  a documented "inset".

---

## 2. Target design language

### 2.0 One palette, and what the axis left behind

**Superseded, 2026-09-07, at the user's direction: "remove palette, move completely from gogo to
planiq."** This section previously specified a swappable `data-palette` axis carrying `gogo` and
`planiq` side by side. It was built, shipped green, and then removed — the console renders PlanIQ
outright, `gogo` lives in git history, and `tokens.css` is back to two blocks keyed on `data-theme`
alone. §2.1–2.2 below are now simply *the palette*, not one cell of four.

The axis is recorded here rather than deleted because three of its parts were kept, each having
caught a real defect, and a future reader is owed the reason they exist:

| Kept | Why it stays |
|---|---|
| **Complete blocks** — `[data-theme="dark"]` restates all 65 colour declarations rather than diffing `:root` | Composing a cell from `:root`'s INVARIANT half instead of all of `:root` turns an incomplete block into a loud failure instead of silent inheritance. It found two missing dark declarations the day it was written. |
| **Anchored `blockRange`** | `indexOf(selector + " {")` is a substring match. `[data-theme="dark"] {` is a substring of `[data-palette="planiq"][data-theme="dark"] {`, so it returned one cell's block for the other, with every assertion green. The next compound block will not announce itself either. |
| **The invariant/colour split** — 65 `var()` aliases and 30 non-colour tokens live only in `:root`, and no block outside it may declare an alias | A block that could re-point `--st-held` would change what the screen *says*, not how it looks. Asserted, not intended. |

Two things went with the axis: the registry-closure assertion (there is no registry), and the
`?palette=` review override. **What replaces closure is the assertion that the axis stays gone** —
`tokens.css` must contain no `data-palette` in its code, and no file under `src/` may write that
attribute. Both halves matter: a `[data-palette]` block would now be measured by *nothing*, and a
`setAttribute("data-palette", …)` would put an attribute on `<html>` matching no rule, so the control
would look broken to an operator and fine to the suite.

**The gate is 269 assertions over two cells**, down from 508 over four, and every number in §2.1–2.4
was recomputed on the change of scope rather than carried over — which caught one: the card-vs-page
separation floor was `1.04:1` in `gogo/light`, and with that cell gone the true tightest is **1.08:1**
(light), 1.10:1 (dark).

**The cost of the reversal, stated plainly.** The PlanIQ port is a one-way door again. There is no
way to put the two looks side by side on real data, and no cheap route to a high-contrast palette —
that was the axis's best argument and it is gone. If either is ever wanted, the three kept parts above
are most of the mechanism; what would need rebuilding is the registry, the store's `palette` state and
the `?palette=` override.

### 2.1 Colour — the `planiq` palette, light

The `planiq` block is **complete** — all 64 declarations, per §2.0.3 — but only these eight **differ
from `gogo`**. The other 56 are carried across verbatim, and "Current" below means `gogo`'s value,
which continues to exist unchanged in its own block rather than being replaced.

| Token | Current | **Target** | Measured | Source |
|---|---|---|---|---|
| `--surface` | `#fafafa` | **`#f6f6f6`** | L 0.9216 | PlanIQ page ground (variable `Background`, collection 1:4) |
| `--surface-card` | `#ffffff` | `#ffffff` | L 1.0000 | unchanged; PlanIQ card |
| `--surface-sunken` | `#f2f2f5` | **`#f0f0f0`** | L 0.8714 | PlanIQ `#F0F0F0` — vestigial `bg/sub-250`, used on one chat-rail thumb; the hex is PlanIQ's, the role is ours |
| `--surface-control` | `#f0f0f3` | **`#ececec`** | L 0.8388 | interpolated to hold the surface ordering |
| `--surface-control-hover` | `#e7e7ec` | **`#e8e8e8`** | L 0.8070 | PlanIQ hairline `Stock` `#E8E8E8`, repurposed as a control ground |
| `--edge` | `#8f8f95` | **`#8c8c92`** | 3.09:1 on `--surface` | +0.11 to hold 3:1 on the lighter page |
| `--brand-solid` | `#bd32af` | **`#75fc96`** | **16.12:1** vs `--ink-on-brand` | PlanIQ Primary/700 |
| `--ink-on-brand` | `#ffffff` | **`#000000`** | **16.12:1** vs `--brand-solid` | PlanIQ CTA label |
| **new** `--brand-solid-edge` | — | **`#218c3b`** | **3.78:1** at worst | PlanIQ "Primary deep" (file-icon fold) — the ring that gives the green button a shape |
| **new** `--ink-on-error` | — | **`var(--surface-card)`** | **5.72:1** on `--error` | closes the `EnvBadge` prod pair, which is unmeasured today |

Surface order is preserved (`control-hover` stays darkest of the five), which is why the
mass-annotation break in §6 does not fire on a *re-ranking* — although 53 annotations still need their
*numbers* rewritten (§2.3).

**The button's ground contrast, stated as a loss.** `--brand-solid` on the surfaces it actually sits
on: **1.21:1 (`--surface`)**, **1.30:1 (`--surface-card`)**, 1.14 (sunken), 1.10 (control), 1.06
(hover). Today's `#bd32af`: 4.75 / 4.95 / 4.43 / 4.36 / 4.02. This is written into the deviation log
and into `buttonVariants.ts`'s header table beside the 16.12:1 label figure.

**`--brand-solid-edge` full matrix, recorded so nobody re-derives the flattering half** (the `--edge`
precedent): light `--surface` 3.98 · `--surface-card` 4.30 · `--surface-sunken` 3.78 ·
`--surface-control` 3.64 · `--surface-control-hover` 3.51. Dark 4.39 · 4.00 · 4.27 · 3.50 · **3.04**.
Its `ROLES` grounds are the **three** a primary button and a dialog actually float over — page, card,
sunken well — not all five: declaring the hover ground would make `3.04` the tightest floor in the
whole dark palette (0.04 headroom) and freeze `--surface-control-hover` permanently for a ring nothing
paints there. It sits ~42 rgbDistance from `--success-fill`, which is fine for a 1px button ring and
means it **must never be used as a chart series or a state fill**; its `what` string says so.

**Unchanged, and deliberately so:** all nine families × 3 members, `--st-*`, `--pg-*`, `--c-1…8`,
`--seq-*`, `--div-*`, `--focus-ring: var(--brand-fill)` (magenta), `--st-held: var(--brand)`, `--ink`,
`--ink-muted`, `--ink-mark`, `--ink-rule`, `--hairline`, `--hairline-strong`, `--surface-nav` and
`--surface-topbar` (both stay `var(--surface-card)`; PQ6 detaches those two surfaces from the page
ground geometrically and repoints nothing).

### 2.2 Colour — the `planiq` palette, dark (`[data-palette="planiq"][data-theme="dark"]`)

Complete in its 64, as above; these are the ones that differ from `gogo`'s dark block.

| Token | Current | **Target** | Note |
|---|---|---|---|
| `--surface` | `#202022` | **`#111111`** | PlanIQ page (frame 0:25236). **This is now the palette's binding ceiling constraint** — see §2.4 |
| `--surface-card` | `#26262a` | **`#1b1b1b`** | PlanIQ card; ΔL vs page = 0.00535 (floor 0.003), contrast 1.10:1 — slightly *better* separation than today's 0.00510 / 1.08:1 |
| `--surface-sunken` | `#1a1a1c` | **`#141416`** | |
| `--surface-control` | `#2c2c31` | **`#26262a`** | |
| `--surface-control-hover` | `#33333a` | **`#303038`** | |

**Rejected, measured:** PlanIQ's `#313131` input fill and `#474747` chart track as control grounds →
**40 role failures** including `--ink-muted`, `--brand-fill`, `--focus-ring`, `--error-fill`. PlanIQ's
dark mode is entirely hand-authored hex with zero variable bindings and carries a documented defect
cluster (`#666D80` title on `#1B1B1B` at ~3.4:1 across five screens; a `#75FC96B2` pill flipped to
white text at ~2.5:1; one light border token fanned across nine dark encodings). We take its
*polarity*, not its values.

**The rule we adopt the ground from and then drop.** The dossier calls PlanIQ's 1px `#FFFFFF0A` inside
stroke on every dark surface-1 frame "the single most consistent rule in the whole dark file". We
adopt `#1b1b1b` on `#111111` **without** it, and this is a checked decision, not an oversight: the
card/page separation is ΔL 0.00535 and 1.10:1, marginally better than what ships today, and this
design's premise (`tokenContrast.test.ts` header, fact 4) is that a card is `--surface-card` plus
`--shadow-card` and never a border.

### 2.3 Annotation lines: **53** for `planiq`, and why the axis makes the generator mandatory

Not ten. The harness produced the exact list. These 53 are the `planiq` cells only — `gogo`'s existing
68 annotations (35 light + 33 dark) are untouched by this plan, because `gogo`'s hexes do not move.
**The file therefore carries ~121 measured claims across four blocks, and every one is recomputed to
2 dp on every test run.**

That total is the argument. Hand-maintaining 53 was already the tail that wagged PQ2; hand-maintaining
121 across a growing registry is not a thing a person should be asked to do, and the failure mode when
they stop is a *stale comment beside a passing token* — precisely the defect (`--fg-2` annotated
"4.6:1" when it was 4.34:1) that licensed 131 sub-AA prose sites. So the generator moves from
"prerequisite of PQ2" to **a precondition of the axis itself**.

**What mechanising does and does not cost.** The number and the named ground become machine-written;
the *bar* and the *role prose* stay hand-declared in `ROLES`, and the gate still fails on a bar miss.
What is lost is the friction of a human typing a ratio and noticing it looks wrong — but that friction
never caught the two incidents this file exists because of; the recomputation did. Generating the
number strictly dominates: it cannot be stale, and it cannot name a flattering ground. Moving `--surface-control-hover` `#e7e7ec → #e8e8e8`
lifts **every** fill and chart ratio measured against it (`--c-3` 3.01→3.03, `--warning` 4.52→4.55,
`--slate-fill` 4.18→4.21 …); moving dark `--surface-control-hover` `#33333a → #303038` lifts all 17
dark fill/chart ratios (`--brand-fill` 3.06→3.19, `--c-3` 6.48→6.76); and dark `--edge` goes 3.35→3.83
because `--surface-card` moved. The annotation test recomputes to 2 dp and fails on any mismatch, so
all 53 are hard failures. **`tools/annotate-tokens.mts` is therefore a hard prerequisite of PQ2, not a
convenience** — and, per the paragraph above, of the axis itself.

Of the 53, **seven change the ground they name** as well as the number, and those are the ones worth
reading by hand:

```
LIGHT
  --ink:            #4d4d4d;  /* 6.88:1 on --brand-tint over --surface — all prose and headings */
  --ink-muted:      #636363;  /* 4.89:1 on --brand-tint over --surface — every muted label */
  --ink-mark:       #767680;  /* 3.66:1 on --brand-tint over --surface — marks and glyphs, never text */
  --brand:          #a92d9d;  /* 4.82:1 on --brand-tint over --surface — brand-coloured text and labels */
DARK
  --ink-rule:       #5e5e66;  /* 2.94:1 at best on --surface — rules and dead controls, never text */
  --hairline:       #313138;  /* 1.46:1 at best on --surface — a decorative rule, never a boundary */
  --hairline-strong:#404048;  /* 1.84:1 at best on --surface — a firmer rule, still decoration */
```

Plus, changed or new outright:

```
  --edge (light):        #8c8c92;  /* 3.09:1 on --surface — the popover boundary ring */
  --ink-on-brand:        #000000;  /* 16.12:1 on --brand-solid — the label on a primary button */
  --brand-solid:         #75fc96;  /* 16.12:1 on --ink-on-brand — primary button fill */
  --brand-solid-edge:    #218c3b;  /* 3.78:1 on --surface-sunken — the ring that gives that fill a shape */
```

`--st-held`, `--ink-on-error` and every `--st-*`/`--pg-*` are `var()` aliases and carry no annotation
of their own. `--brand-solid` and `--brand-solid-edge` are declared once in `:root` and not redefined
in the dark block, exactly as `--brand-solid` is today, so neither needs a dark annotation while both
are still measured through `DARK`.

### 2.4 Tightest headroom after the change — floors **and** ceilings

**Scope: the `planiq` cells only.** `gogo`'s own floors are unchanged and are not reproduced here. The
two axes do not interact — a palette is a complete block, so no `planiq` value can constrain a `gogo`
one, and the freezes below bind `planiq` alone. Read "light"/"dark" in the first column as
`planiq/light` and `planiq/dark`.

| Cell | Token(s) | Kind | Measured | Bar | Headroom |
|---|---|---|---|---|---|
| dark | `--ink-rule` on `--surface` | **CEILING 3.0** | **2.939** | — | **0.061** |
| light | `--c-3` | floor 3.0 | 3.027 | 3.0 | 0.027 |
| light | `--info-fill`, `--st-brief-ready-fill`, `--st-lyrics-ready-fill`, `--pg-started-fill` | floor 3.0 | 3.028 | 3.0 | 0.028 |
| light | `--c-5` / `--c-2` | floor 3.0 | 3.042 / 3.045 | 3.0 | 0.042 / 0.045 |
| light | `--warning`, `--pg-degraded` | floor 4.5 | 4.547 | 4.5 | 0.047 |
| light | `--c-1` | floor 3.0 | 3.055 | 3.0 | 0.055 |
| dark | `--warning`, `--pg-degraded` (on `--warning-tint over --surface`) | floor 4.5 | 4.570 | 4.5 | 0.070 |
| dark | `--accent`, `--st-authorized` | floor 4.5 | 4.588 | 4.5 | 0.088 |
| dark | `--brand`, `--st-held` | floor 4.5 | 4.598 | 4.5 | 0.098 |
| light | `--ink-rule` on `--surface-card` | CEILING 3.0 | 2.231 | — | 0.769 |

**The guardrail sentence, corrected.** The first draft's "`--surface-control-hover` remains the most
constrained value in the system in both palettes" is false once §2.2 lands. Replace it with the two
constraints that are actually binding:

1. **Light: `--surface-control-hover` `#e8e8e8` (L 0.80695) and `--brand-tint` (L 0.80517, opaque, so
   identical over all five surfaces) sit 0.00178 apart in relative luminance, and `--brand-tint` is
   now the darker.** Either one moving in either direction re-ranks `--ink`, `--ink-muted`,
   `--ink-mark` and `--brand` simultaneously. **Both are frozen**, not just the hover ground.
2. **Dark: `--surface` `#111111` may not darken further** — `--ink-rule` sits **0.061** under its 3:1
   ceiling against it — **and no dark tint may lighten.** (This is also the real reason
   `--surface-sunken` is `#141416` and not PlanIQ's darker wells: `#0d0d0f` measures `--ink-rule` at
   **3.022**, over the ceiling. The constraint lives on `--surface` now, and the sunken value follows
   from the ordering rather than from the ceiling.)

### 2.5 Type scale

PlanIQ's product face is Manrope (2739/2957 light-page text nodes; the Style Guide's Outfit scale is
stale and used by zero screens). **We do not take its ratios, and this plan should say so plainly
rather than dress a normalisation up as an extraction.** PlanIQ's line-height is a single rule —
Manrope auto = fontSize × 1.366, with a typed 1.5 where the designer overrode it. What follows rounds
each rung to whole pixels at roughly 1.30–1.40 and caps tracking at −0.045em where PlanIQ uses −0.06em,
because a 40px numeral at −0.06em collides on `.num`'s tabular, slashed-zero figures, and because a
1.366 hero (40 → 55px leading) does not fit the console's 68px top bar and 143px-equivalent tile
rhythm. We take PlanIQ's **weights, its sentence case, its negative tracking direction and its
size relationships**; the line-heights are ours. We keep a **12px floor** for anything an operator
reads a value from, and 11px absolute.

*(Rejected: the cheaper "set every rung to round(size × 1.366)" alternative. It is more faithful and
worse — it inflates the hero and metric leading by 11–13px each on a screen whose whole job is
information density.)*

| Class | Current | **Target** | PlanIQ role |
|---|---|---|---|
| `.type-hero` | 40 / 44 / 700 / −0.02em | **40 / 52 / 700 / −0.045em** | display 42/57.372/700/−0.06em |
| `.type-metric` | 28 / 34 / 700 / −0.01em | **28 / 38 / 700 / −0.045em** | metric 32/43.712/700/−0.06em |
| `.type-h1` | 26 / 34 / 700 / −0.01em | **24 / 33 / 600 / −0.02em** | screen title 24/32.784/600 |
| `.type-h2` | 18 / 26 / 600 | **17 / 23 / 600 / −0.02em** | card header 16/21.856/600 |
| `.type-h3` | 15 / 22 / 600 | **15 / 21 / 600 / −0.02em** | inline label 14/19.124/600 |
| `.type-body` | 14 / 22 / 400 | **14 / 21 / 400** | body 14/21/400 |
| `.type-body-sm` | 13 / 20 / 400 | **13 / 18 / 400 / −0.02em** | table cell 12/16.392 → floored at 13 |
| `.type-caption` | 11 / 16 / 600 / +0.06em / **uppercase** | **unchanged — see Open Questions** | PlanIQ has no uppercase product role at all |
| `.type-mono` | 13 / 20 | **unchanged** | PlanIQ has **zero** monospace nodes |
| — | *no button rung* | **`text-button` 14/20/500/−0.02em** | button lg 18/500/−0.02em |

`.type-hero` and `.type-metric` may be restyled, never renamed (`src/styles/index.css:91-93`; asserted
in Vitest and by `e2e/smoke.spec.ts`'s `statValue()`). The scale is duplicated in three places kept in
sync by a test — `src/styles/index.css:75-168`, `tailwind.config.ts` `fontSize`, and
`src/lib/utils.ts` `TYPE_SCALE_UTILITIES`; a rung added to one and not the others makes `twMerge`
silently delete the utility.

### 2.6 Radius

Repoint the **semantic aliases**, never renumber the rungs — the rungs project 1:1 into
`tailwind.config.ts:150-170` and every `rounded-*` call site.

| Alias | Current | **Target** | PlanIQ |
|---|---|---|---|
| `--r-card` | `--r-3xl` (28px) | **`--r-md` (16px)** | card r15 / modal r16 — unifies PlanIQ's own authoring slip |
| `--r-button` | `--r-md` (16px) | **`--r-3xs` (10.4px)** | r6 CTA; 10px is PlanIQ's own Log In button and survives a 40px target |
| `--r-control` | `--r-sm` (14px) | **`--r-4xs` (8px)** | chip r6 → floored at the scale's 8px minimum |
| `--r-pill` | `--r-full` | unchanged | nav pill r26 on a 34px box is a pill |

**The rung sweep — the half the first draft left stranded.** `--r-card` 28 → 16 inverts the nesting on
**27 hand-typed `rounded-xl` / `rounded-2xl` / `rounded-3xl` sites across 21 files**, every one of
which would end up rounder than the card containing it — the exact incoherence this section claims to
remove. Verified inventory: `RevealDialog.tsx` ×4, `LyricSheetPanel.tsx` ×2, `GrantCreditsDialog.tsx`
×2, `ChartFrame.tsx` ×2, and one each in `UserDetailScreen`, `RetentionScreen`, `AuthPanel`,
`ChainVerifyPanel`, `KeyboardShortcuts`, `ErrorState`, `ErrorBoundary`, `CommandPalette`,
`AccountMenu`, `StepUpPrompt`, `RevealBudgetMeter`, `PurgedRange`, `PipelineTimeline`, `ConfigField`,
`CodepointTooltip`, `JsonViewer`, `CodeBlock`. PQ3 repoints them in two groups:

- **Inset wells** (`JsonViewer:65`, `CodeBlock:58`, `ChartFrame`'s empty state `:150-155`,
  `RevealBudgetMeter:91`, `StepUpPrompt:107`, `GrantCreditsDialog:209,310`) → a new semantic alias
  `--r-well: var(--r-xs)` (12.56px), so a well is always inside its card's 16px.
- **Popover and dialog shells** (`CommandPalette:116` `rounded-3xl`, `KeyboardShortcuts:104`
  `rounded-3xl`, `AccountMenu:94` `rounded-2xl`, `CodepointTooltip:78` `rounded-2xl`) → `rounded-card`,
  so they track the same repoint forever.

The remaining ~10 (`PurgedRange`'s dashed range, `PipelineTimeline`, `ConfigField`, `ErrorState`,
`ErrorBoundary`, `AuthPanel`, `ChainVerifyPanel`, `RetentionScreen`, `UserDetailScreen`,
`LyricSheetPanel`) are resolved by PQ4's `Card` extraction, which is what those sites are.

We hold the **8px floor**: PlanIQ's r4 chips would trade the scale's only remaining coherence for a kit
that has no radius scale.

### 2.7 Spacing & layout

| Token | Current | **Target** | Evidence |
|---|---|---|---|
| `--card-pad` | 24px | **16px** | PlanIQ card inset, verified on 10+ containers |
| **new** `--dialog-pad` | — | **24px** | PlanIQ pads modal bands at 24, *not* 16 (Create New Task 763×914 header h64/p24, form p24, footer px24; Export Data 680×423). The card inset and the modal band are not the same token, and the first draft applied `p-card` to the one container PlanIQ deliberately pads differently |
| `--gutter` | 24px | 24px | PlanIQ page padding is also 24 |
| `--row-h` | 44px | 44px | PlanIQ's own 40px targets are flagged sub-minimum by its tooling |
| `--row-h-compact` | 34px | **34px, unchanged** | the persisted `density: "compact"` mode (`usePrefsStore.ts:39`, read by `DataTable.tsx:272` and `Skeleton.tsx:111`). A 16px card inset and a 13/18 body rung both shrink around it; the row itself does not move, and PQ3's review list includes one compact screenshot to price that |
| `--nav-w` / `--nav-w-collapsed` | 264 / 76 | unchanged | asserted by *class name* (`w-nav`), not pixels |
| `--topbar-h` | 68px | unchanged | PlanIQ bar is 54 + 24 top gutter = 78 |

PlanIQ's real base is a **2pt grid with a 10px module** (71.9% of gaps on 2pt vs 15.9% on 8pt; `10`
appears 947× vs `8` at 484×). Its 10px gutter is measured on a 1392px canvas *with no rail*. Ours has
a 264px rail and a 68px top bar; at the 1512px e2e viewport the content column is ~1200px. **Do not
transcribe PlanIQ's grids** — `3×322 + 2×10 = 986` and `4×340.5 + 3×10 = 1392` resolve at 1392 and
nowhere else.

### 2.8 Elevation and the scrim

| Token | Current | **Target** |
|---|---|---|
| `--shadow-2xs … --shadow-2xl` (+`-darker`) | Gogo scale | **unchanged** — PlanIQ has 7 ad-hoc shadows and no ramp to import |
| `--shadow-card` | `var(--shadow-xs)` | **unchanged** — pinned as a literal string at `tokenContrast.test.ts:901` |
| `--shadow-overlay` | `0 0 0 1px var(--edge), 0 3px 28px #0000001f` | **`0 0 0 1px var(--edge), 0 16px 32px -1px #80889733`** — PlanIQ E6, its only real elevation |
| **new** `--scrim` | — | **`#00000044` light / `#000000b3` dark** |

**The light scrim is computed, not transcribed.** PlanIQ's 20% black over `#f6f6f6` composites to
`#c4c4c4`, against which a `#ffffff` dialog measures **1.73:1** — noticeably weaker than what ships
today (`bg-ink opacity-40`, i.e. `#4d4d4d` at 40% over `#fafafa` → `#b5b5b5`, **2.06:1**). PlanIQ's
20% was authored for a kit whose modals carry *no shadow at all*; ours carry `--shadow-overlay`, which
PQ3 simultaneously changes to PlanIQ's cool-grey E6. Landing 1.73 in the same wave as `--r-card`
28→16 (less shape distinction) and a near-invisible green button ground is three simultaneous losses
of figure/ground in light mode, and nobody would have decided that on purpose. So: **`#00000044`
(26.7%)**, which composites to `#b4b4b4` and measures **2.06:1** — today's separation exactly. Dark
`#000000b3` measures **1.18:1** for a `#1b1b1b` card, up from today's 1.08:1. The combined light-mode
separation delta is recorded in the deviation log as a decision rather than an accumulation.

`--scrim` resolves to a colour, so it **must** be classified in `tokenContrast.test.ts` or the
completeness gate fails. That failure is the gate working. It is a *translucent* ground, so it also
gets an explicit `over which surfaces` note plus the two measured lines above — see PQ1's reworked
assertion, which keys on *role* rather than on the `^--surface` prefix precisely so that this token is
covered by it.

---

## 3. Shell & IA decision

**Keep the left rail. Adopt PlanIQ's chrome.** PlanIQ has no sidebar anywhere — its only left panel is
a chat conversation list — and porting its floating top bar literally is the single most tempting and
most wrong move in the kit. Three reasons, in order of weight:

**It does not fit.** PlanIQ's six nav pills occupy 507px of a 714px bar (widths 91/77/80/83/81/95 at
16px padding). Our twelve labels — `Generations`, `Moderation`, `Payments`, `Vendors` — land near
~900px of pills at the same type, plus ~150px for three inline `phase 3` chips (which PlanIQ has no
vocabulary for), plus a group separator, plus the mark and env badge. Against a right cluster already
denser than PlanIQ's (`LiveHeartbeatPill` + ⌘K + a deliberately *wide* `TimeZoneToggle` that writes its
current zone on its face + theme + `?` + `AccountMenu`), the honest total is ~1750–1800px on a viewport
`playwright.config.ts` pins at 1512×900.

**Role-gating reflows the wrong axis.** Removing Audit and Admins for a viewer shifts two rows off the
bottom of the rail; every other item keeps its position. In a horizontal bar the same removal changes
the bar's width and therefore the x-position of the entire right cluster — and because `PermissionGate`
renders nothing while `/auth/me` is in flight, that reflow happens as a visible jump on **every cold
load**. A rail absorbs a role difference; a bar advertises it.

**PlanIQ's state model is worse than ours and we would inherit it.** Its nav uses identical
`12px/500/#000000` type in both states — selection is fill colour alone — and in light mode the
inactive fill is `#FFFFFF` on a `#FFFFFF` bar, which its own `describe` flags as an error on five
items. `NavRail.tsx:107-131` already carries three channels (the `segmentVariant` pill, `font-semibold`,
`aria-current`). We copy the pill's *shape* and its solid-green *fill*; never its state model.

**What we do adopt:** the rail and top bar become **detached rounded surfaces on the page ground**
rather than butted zones (they already have no border and no bottom rule — only the gutter is missing;
`--surface-nav` and `--surface-topbar` keep pointing at `--surface-card`); rail rows go
`rounded-button` → `rounded-pill` at `px-4`; the active row becomes **solid `#75fc96` with a black
label** (PlanIQ's signature, and a genuine contrast win over the current tint); the four top-bar
utility controls group into one `--surface-card` pill with `AccountMenu` beside it at PlanIQ's 8px
rhythm.

**Narrow viewports** are the one place PlanIQ's horizontal bar is right — a 264px rail is 41% of a
640px window — so that becomes a documented responsive fallback (PQ6, optional), never the default.

**Untouchable, each with a named silent-failure mode:** `<main id="main">` stays the only scroll
container (`e2e/smoke.spec.ts:219-231` asserts the modal scroll lock yields `padding-right: 0`
*because* `<body>` never scrolls); `PlayerBar` stays outside `<main>`/`<Outlet>` with **no `key`** on
`<AudioPlayer>`; `ErrorBoundary` stays scoped to `<main>`; nothing in `components/layout/` may read a
`@/routes` binding at module scope (`navHref()`, `isRealPath()`, `routeHref()` are lazy for this
reason, and the failure is undefined hrefs, not a crash); the landmark names `nav "Sections"`,
`nav "Breadcrumb"`, `banner`, `region "Audio player"`, `dialog "Command palette"` are selectors in five
test files.

---

## 4. Workstreams

Ordered so the console ships after every one.

---

### PQ-1 — Commit the tree (the real precondition)

**Goal.** Make the rollback story possible at all. This is a gate on **PQ0**, not on close-out.

`git status --porcelain admin-ui` today: **50 modified, 21 untracked**, and the untracked set is not
incidental — it is all of `src/features/vendors/` (6 files, ~1 566 lines) plus `Drawer.tsx`,
`CreditBalanceChip`, `CreditLedgerTable`, `GrantCreditsDialog`, `ReasonConfirmDialog`, `UserAvatar`,
`credits.ts`, `DurationBadge`, `UserPeekDrawer`, `profile.ts`, `endpoints.test.ts`, `schemas.test.ts`
and their tests. PQ0 edits `OrdersScreen.tsx` and `Drawer.tsx:123` directly; PQ4 migrates card sites
inside untracked files; PQ5 restyles `Drawer`. If the reskin starts here, five waves of restyle edits
interleave with uncommitted feature work in the same files and **every sentence in PQ9's rollback
section is already false** — `git revert` of a reskin wave would take shipped feature work with it.

**Changes.** Commit the WS1/WS2 work as its own commit (or small series), separately from anything in
this plan. Nothing else.

**Depends on.** Nothing. **Effort.** S. **Risk.** Low, and unbounded if skipped.

**DoD.** `git status --porcelain admin-ui` is clean. `npx vitest run` on the committed tree reports
**101 files / 1409 tests**. That number is the plan's baseline and every later DoD is expressed
relative to it.

---

### PQ0 — Defect sweep and seam freeze

**Goal.** Fix three real bugs found while auditing, and pin the seam that keeps every later workstream
cheap.

**Changes.**
- `src/features/orders/OrdersScreen.tsx:463-500` — `OrderPeekDrawer` is a hand-rolled `<div>` +
  `<aside>` with **no Radix root, no focus trap, no `role="dialog"`, no Escape handler and no
  opener-focus restore** — the exact "lost my place in the list" failure `Drawer.tsx:80-90` documents
  itself as preventing. Re-express it on `<Drawer>`, preserving `data-testid="order-peek"`,
  `data-order-id` and `data-testid="order-peek-backdrop"` verbatim.
- `src/features/orders/OrdersScreen.tsx:476` — `bg-black/40` is a Tailwind **default-palette leak**:
  theme-blind, does not invert in dark, invisible to every gate. `backdrop-blur-xs` **does not exist**
  in Tailwind 3.4 (the `backdropBlur` scale has no `xs`) — a silent no-op. Both deleted with the drawer.
- `src/features/orders/OrdersScreen.tsx:486` and `src/components/util/Drawer.tsx:123` —
  `sm:border-line`. `line` is not a border colour in this config; `tailwind.config.ts:19` claims removed
  names "FAIL TO BUILD" but they are silent no-ops. **Neither drawer has the left border it asks for.**
  Delete, or use `border-hairline`.
- `eslint.config.js` — new `no-restricted-syntax` banning Tailwind default-palette colour utilities in
  `className` literals (`bg-black/40`, `text-gray-400`, `bg-red-500`, …), scoped to `src/components/**`
  and `src/features/**`. This is the gap the audit named: nothing catches a theme-blind colour today.
- **NEW** `src/test/contract.test.ts` — snapshot the **globally sorted set** of `data-testid` literals
  across `src/**/*.tsx` and the shell's `(role, accessible-name)` landmark pairs. 553 testid references
  and 352 `ByRole` calls are what hold a restyle to ~107 assertions instead of suite-wide; nothing
  guards them. **The snapshot is global, not per-file, precisely because PQ4 and PQ8 move testids
  between files** — a per-file shape would fail on every extraction commit and teach reviewers to
  regenerate it. Updating it requires an explicit line in the commit message naming which testids
  changed and why; a diff that only *moves* ids leaves the snapshot byte-identical, which is the whole
  point.
- `src/app/RootLayout.test.tsx:54,61` — name the currently **unnamed** `getByRole("navigation")`. It
  passes today only because the routed stub renders no `PageHeader`; the moment the shell has two nav
  landmarks it throws `found multiple elements`, which reads as a test bug.
- `e2e/smoke.spec.ts:48,161` — replace `page.locator("article")` (StatTile) and `page.locator("section")`
  (failure-mix panel) with testid locators so a primitive changing its tag does not fail the CSP gate
  cosmetically.

**Depends on.** PQ-1. **Effort.** S. **Risk.** Low. `OrdersScreen.test.tsx` selects the peek by testid,
but the panel goes from `<aside aria-label="expanded order">` to a Radix-managed `role="dialog"` — grep
its `getByRole` calls first.

**DoD.** `npx vitest run` at **1409 + N**, where N is the number of cases `contract.test.ts` adds and
is named in the commit message. No assertion edits beyond the two named. `npx eslint src` clean.
Manually: open a peek, press Escape (closes), Tab (stays trapped), close (focus returns to the
originating row) — none of the three work today.

---

### PQ1 — Build the net: harden the contrast gate, add an appearance gate, mechanise annotations, stand up the gallery

**Goal.** Close four silent evasion routes and add the two nets this repo has never had: a
rendered-colour check and a pixel baseline. `vitest.config.ts` sets `css: false` and `getComputedStyle`
appears exactly once in the whole repo (`e2e/smoke.spec.ts:67`, for `overflow`/`padding-right`).
**A palette that is arithmetically correct in `tokens.css` but wired to the wrong element ships with
1409 green tests today.**

**Changes.**
- `src/styles/tokenContrast.test.ts:568` — widen the must-annotate filter `/^#[\da-f]{6}$/u` →
  `/^#[\da-f]{6,8}$/iu`. `ANNOTATION` already accepts `{6,8}`; an alpha role token currently escapes
  annotation entirely.
- Same file (structural block, ~:877) — new assertion: **every hex in `tokens.css` is lowercase**.
  `ANNOTATION` (`:500`) is `[\da-f]` with **no `i` flag**, so a hex pasted from a design tool as
  `#75FC96` is neither required to carry an annotation nor checked against one, while the role-bar test
  still passes. `tokens.css` is 100% lowercase today; a reskin is precisely when that changes.
- Same block — new assertion: the set of `[data-theme="…"]` selectors in `tokens.css` is exactly
  `{dark}`. `PALETTES` (`:108`) is a hardcoded 2-tuple, so a third theme block is parsed and *never
  measured*. This is also what makes "no parallel-theme flag" enforceable rather than a preference.
- Same block — new assertion, **keyed on role rather than on the `^--surface` prefix**: every `GROUNDS`
  entry whose value resolves to an **opaque** colour must also appear in `SURFACES`; every entry that
  resolves to a **translucent** colour must carry an explicit `over which surfaces` note and at least
  one measured line beside it. The prefix form the first draft proposed would not have covered
  `--scrim`, the very token PQ3 adds — the exact "a sixth surface, green forever" evasion it was
  written to close.
- Same block — **make the extreme-ground comparison tie-aware.** `:562` sorts and asserts
  `ranked[0][0] === namedGround` as a string. After PQ2 the light darkest ground is a **five-way exact
  tie** (`--brand-tint over <any surface>`, L 0.80517, because tints are opaque so the composite is
  byte-identical), and which one wins is V8 sort stability plus the order of `SURFACES[0]` and
  `FAMILIES[0]`. The plan's `on --brand-tint over --surface` happens to be right *by tie-break luck*;
  reordering either array — or a future engine — would break `--ink`, `--ink-muted`, `--ink-mark` and
  `--brand` at once with "names X but its worst ground is Y", which reads as a test bug. Fix: build the
  set of grounds within `1e-9` of the extreme and assert `expect(tied).toContain(namedGround)`, with
  the failure message listing every tied ground.
- **NEW** `src/styles/contrastMath.mts` — extract `colorOf`, `over`, `relativeLuminance`, `contrast`,
  `rgbDistance`, `ground`, `ratioOn`.
- **NEW** `src/styles/contrastRoles.mts` — extract `SURFACES`, `FAMILIES`, `ORDER_STATES`,
  `PIPELINE_STATUSES`, `tintGrounds`, `trio`, `ROLES`, `GROUNDS`, `THRESHOLD`. **Both** the test and
  the annotate tool import this one file. The first draft had the tool "reconstruct `ROLES` from the
  same arrays" while leaving `ROLES` in the test — which is a second copy of the exact data whose
  duplication (`FAMILIES` in `tokenContrast.test.ts` *and* `tailwind.config.ts`) the risk table already
  names as a silent-drift class. Two behaviour-neutral commits; the test keeps only its `describe`s,
  the bars, the waivers and the source scan.
- **NEW** `tools/annotate-tokens.mts` — imports both extracted modules, and rewrites only the
  `N.NN:1 [at best ]on --ground` span of each literal-hex role token's comment, preserving the
  ` — prose` tail verbatim. `--check` in CI, `--write` locally. It *measures*; it must never author the
  role prose after the em dash.
  **Runtime:** `package.json` declares `"engines": {"node": ">=20.19"}`. Native TypeScript
  type-stripping is flagged from Node 22.6 and default only from 23.6, so a `.mjs` entry importing a
  `.ts` module works on this machine (v26.7.0) and breaks CI on the declared floor. Add `tsx` to
  `devDependencies` and run `npx tsx tools/annotate-tokens.mts`; do **not** raise the engines floor as
  a side effect of a reskin.
- **NEW** `e2e/appearance.spec.ts` (~250 lines) — reads `getComputedStyle` on ~18 anchors in **both
  themes**: page ground, card, sunken well, control, control-hover (via `page.hover` on a table row),
  primary-button ground, its label **and its ring**, focus ring (`Tab` → `outlineColor`), `StatusPill`
  tint + word, `ErrorCodeBadge`, hairline, `LivePill` per state. Expectations come from **NEW**
  `e2e/palette.ts`, generated by the annotate tool so they cannot drift from the stylesheet.
  **It gets its own Playwright project on its own port**, not a reuse of smoke's session. The reason is
  concrete: there is exactly one authenticating spec today and its sign-in is a **one-shot state
  transition** — `smoke.spec.ts:106-127` signs in with `manifest.bootstrapPassword`, asserts the forced
  rotation, and rotates to `manifest.rotatedPassword`. `playwright.config.ts` sets `workers: 1`,
  `fullyParallel: false`, `reuseExistingServer: false` (one server, one seed, whole run) and Playwright
  orders spec files alphabetically, so `appearance` would run *before* `smoke`, consume the rotation,
  and make smoke's rotation step fail against an already-cleared `must_change_password`. The config
  already reads `BAYRAM_E2E_PORT` from the environment and passes it to the harness, so a second project
  with its own `webServer` on a second port is a small, honest change.
  *(Rejected: extracting an "idempotent" `signIn()` helper that tries the rotated password first and
  falls back to bootstrap. It edits `smoke.spec.ts`, which this plan elsewhere refuses to relax, and an
  idempotent sign-in cannot distinguish "already rotated" from "wrong password" — it would mask an auth
  regression as a fallback.)*
- **NEW** `src/features/dev/GalleryScreen.tsx` + `/__gallery` registered only under
  `import.meta.env.DEV` — every primitive at every variant/state/size, fixed props, no clock, no
  network, a theme toggle, and one `[data-gallery-section]` per idiom. **NEW** `e2e/gallery.spec.ts`
  screenshotting **per section** so a `Button` change does not invalidate the `Card` baseline. Force
  `prefers-reduced-motion` or the `◉ pulse-ring` flakes every run.
  It is built **here**, not at close-out. The first draft answered "no visual-regression net" with a
  gallery in the last workstream, which means PQ3 (27+ radius sites at once), PQ5 (all buttons), PQ6
  (the whole shell) and PQ8 (15 routes) would each have shipped with no pixel baseline at all. The
  gallery starts nearly empty and is **populated as each primitive is extracted in PQ4**; it is the
  acceptance evidence for PQ5 and PQ6.
- `package.json` — `tokens:annotate`, `tokens:check`, `e2e:appearance`, `e2e:gallery`. The last two
  must run `npm run build` first: `vite.config.ts:106` outputs into `src/bayram/admin/static`, and a stale
  bundle would assert the old palette and pass.
- `eslint.config.js:130-142` — `INK_MARK_MESSAGE` hardcodes "3.52:1 at worst" while `tokens.css:101`
  says 3.65 and the true light worst is 3.646 (global worst 3.563, dark). Already stale. Have the tool
  regenerate it, or replace the numbers with a pointer to `tokens.css`.
- **Generalise the gate to a registry cross-product, with the registry still at one palette.**
  `PALETTES` (`:108`) is a hardcoded 2-tuple; it becomes `REGISTRY × THEMES`. Teach `block()` combined
  selectors (it is `indexOf(selector + " {")`, so `[data-palette="x"][data-theme="dark"] {` already
  parses — what is missing is the assertion that the file writes each selector canonically, single, and
  comma-free). **With `REGISTRY = ["gogo"]` this must produce exactly the same 244 assertions and the
  same numbers as before the refactor** — that identity is how the refactor is proved
  behaviour-preserving, and it is why the work belongs here rather than in PQ2.
- **The three axis invariants from §2.0.5**, added now so they are exercised before a second palette
  exists: key-set parity across palette blocks, no `var()` alias outside `:root`, and registry closure
  in both directions.
- **`tokens.css` `[data-theme="dark"]` — add 2 lines.** Key-set parity **fails on the untouched tree**:
  `:root` declares 64 palette tokens, the dark block 62, missing `--brand-solid` and `--ink-on-brand`.
  Add both to the dark block with **their existing `:root` values** — `#bd32af` and `#ffffff`. Zero
  visual change, zero ratio change; the two tokens were already being measured through `DARK` by
  inheritance. This is the new assertion proving itself on real drift before it is trusted.
- `tools/annotate-tokens.mts` — written against the block registry from the start, not against a
  hardcoded pair, so PQ2 costs it no changes.
- **A documented spike, then reverted:** temporarily add `--surface` and `--surface-card` to
  `--brand-solid`'s `ROLES` grounds at the graphic 3:1 bar and run the suite against the *candidate*
  palette. It fails at 1.21 and 1.30. That failure — produced by the gate rather than asserted by this
  document — is the evidence for `--brand-solid-edge`, and the spike commit is reverted before PQ2
  lands. `--brand-solid` keeps its single closed-pair ground because it is a *ground*, not a boundary;
  the boundary is a different token with a different bar.

**Depends on.** PQ0. **Effort.** L. **Risk.** Extracting `contrastMath`/`contrastRoles` touches the
file the whole contract rests on — do each as its own commit and confirm the count is unchanged before
any value moves.

**DoD.** `npx vitest run src/styles/tokenContrast.test.ts` → **244 + M**, M named (four new structural
assertions, the three axis invariants, plus the tie-aware rework). **The 244 itself must not move** —
the registry refactor at N=1 is behaviour-preserving by definition, and any change in that number means
the parser or the merge order is wrong. Full suite at **PQ0's number + M**, recorded here as the new
baseline. `npx tsx tools/annotate-tokens.mts --check` on the untouched tree exits 0 and verifies all
**68** hand-written annotations — proving the tool agrees with the humans before it is trusted to
write. `npm run build && npm run e2e:appearance && npm run e2e:gallery` green on the **current**
palette. Then break one hex locally and confirm exactly one assertion fails readably.

---

### PQ2 — The palette

**Landed 2026-09-07.** Built first as a second palette on the `data-palette` axis (PQ2a/b/c below, kept
for the record), then collapsed: the axis was removed at the user's direction and PlanIQ became the
palette outright. Read the tranches as history — what shipped is their combined effect, in `:root` and
`[data-theme="dark"]`.

**Goal.** Land §2.1–2.3. Values plus four vocabulary edits — no component file changes.

**Changes.**
- `src/styles/tokens.css` — `:root` and `[data-theme="dark"]`, 65 declarations each, carrying §2.1 and
  §2.2. Every token not named in those sections keeps the value it had: completeness is a cascade
  requirement (§2.0), not an invitation to redesign the other 50.
- **`ROLES`/`GROUNDS` edits, enumerated. The first draft's "zero lines of `ROLES` change" was the
  claim that stopped the gate from seeing the button dissolve; the honest count is four:**
  1. **new** `--brand-solid-edge`: `{ bar: "graphic", grounds: ["--surface", "--surface-card",
     "--surface-sunken"], what: "the 1px ring that gives --brand-solid a shape; never a chart or state
     fill" }`. Measured worst 3.78 (light) / 4.00 (dark).
  2. **new** `--ink-on-error`: `{ bar: "text", grounds: ["--error"] }`, aliasing `var(--surface-card)`.
     Measured **5.72:1** light, **6.48:1** dark under the new card colour (5.68 today). This closes the
     `EnvBadge` prod pairing, which is an *unmeasured* pair today and which PQ2 perturbs blind by
     moving dark `--surface-card`. `EnvBadge.tsx`'s `text-surface-card` becomes `text-ink-on-error` in
     PQ5, and `danger-solid` uses the same pair.
  3. `--focus-ring` gains `--brand-solid` as a ground. Today the ring is `#bd32af` on a `#bd32af`
     button — **1.00:1, an invisible focus indicator on the most-clicked control, with a green suite**,
     because `--focus-ring`'s grounds are `SURFACES` only. After the swap it is **3.80:1** light and
     **3.14:1** dark — both clear 1.4.11, and now by assertion rather than by luck.
  4. PQ3 adds the `--scrim` `GROUNDS` entry (§2.8).
- `npx tsx tools/annotate-tokens.mts --write`, then hand-edit only the prose tails of `--ink-on-brand`
  (polarity flipped) and the two new tokens.
- `src/styles/tokens.css:49-50, 180-182, 587` — the header prose calls `--brand-solid` "Gogo's
  `--primary` verbatim", and its `ROLES` `what` string says the same. Both become false. Rewrite: it is
  now PlanIQ Primary/700 as an action ground, and `--brand`/`--brand-fill` remain Gogo's magenta as the
  identity/link hue. State the measurement that forced the split (PlanIQ's own darkest green is 3.51:1
  on the hover ground and 38.8 rgbDistance from `--success`; today's brand is 174 away).
- `src/styles/tokens.css:126-132` — `--edge`'s inline 10-value measurement matrix is prose and becomes
  wrong. Recompute all ten.
- `src/styles/tokens.css:536-588` — extend the deviation log with a **PlanIQ** section recording what
  was rejected and *why measured*: `#75FC96` as a foreground is 1.06–1.30:1; **`--brand-solid`'s own
  ground contrast falls from 4.75/4.95 to 1.21/1.30, and `--brand-solid-edge` at 3.78–4.30 is what
  replaces the shape**; `#474747`/`#313131` as dark control grounds fail 40 tokens; the Style-Guide
  Gray and Green ramps are used by zero PlanIQ screens; the Green captions are stale purple from the
  source template; the light scrim is computed to 2.06:1 rather than transcribed at 1.73:1; the dark
  `#FFFFFF0A` card hairline is deliberately dropped and the separation checked at ΔL 0.00535 / 1.10:1.
- `tailwind.config.ts` — two additions only: `colors.brand["solid-edge"]` and `colors.ink["on-error"]`.
  Everything else is pure `var()` projection and does not move — and this is exactly why the axis costs
  Tailwind nothing: the config projects custom properties, never hexes, so it is palette-blind.

**Depends on.** PQ1. **Effort.** M.

**Risk.** The one to watch is the temptation, if anything fails, to widen a role's grounds or drop the
tint grounds — the exact move `tokenContrast.test.ts:434` forbids ("Darken or lighten the token — do
not widen the role"). The tint-over-five-surfaces ground set exists *because* a curated list previously
hid a 3.90:1 shipped defect. Treat any proposal to narrow it as a red flag. Secondary: eight tokens sit
under 0.05 headroom, and §2.4's two frozen constraints now bind.

**DoD.** `npx vitest run src/styles/tokenContrast.test.ts` → **~488 + M**: the cell count doubles
because the registry did, and every `planiq` cell clears the same bars `gogo` does. The **four**
`ROLES`/`GROUNDS` edits above are the only vocabulary change; any further edit means the plan was wrong
about scope. `npx tsx tools/annotate-tokens.mts --write` **touches exactly 53 comment spans in the two
new blocks and zero spans in `gogo`'s** — if it rewrites a `gogo` annotation, the blocks are not
independent and the cascade is wrong. `--check` then exits 0. `npm run build && npm run e2e:appearance`
green in **four** cells. Full `npx vitest run` at PQ1's number — **zero** component failures, since no
token was renamed and the default did not move. Confirm by screenshot that the console is pixel-identical
without `?palette=`.

---

#### PQ2b — The runtime switch *(built, then removed — kept for the record)*

**Goal.** Make the second palette reachable by a person rather than a query string.

**Changes.**
- `src/lib/stores/usePrefsStore.ts` — `palette: PaletteChoice` defaulting to `"gogo"`; `setPalette`;
  `applyPalette()` per §2.0.4 (**the default removes the attribute rather than setting it**, mirroring
  "light is home"); `palette` added to `partialize`. `initPalette()` beside `initTheme()`.
- `src/main.tsx:33` — call it, before `createRoot`, for the reason the comment there already gives.
- `src/routes.tsx` or the shell — read a non-persisted `?palette=` override, validated against the
  registry and **ignored if unknown** (an unrecognised value must fall back to the default, never to an
  unstyled document).
- `src/components/layout/AccountMenu.tsx` — the control. **Not the top bar**: PQ6 is spending that
  width, and a palette is a rarely-changed preference, not a per-task one.
- `index.html:47-51` — extend the no-flash comment to both axes. It currently explains the guarantee
  for `data-theme` alone and would otherwise become half-true.
- `e2e/` — the gallery visits each palette via `?palette=`, which is why the parameter is not merely a
  developer convenience.

**Depends on.** PQ2. **Effort.** S. **Status: built, then removed with the axis.**

**Risk.** Low, and bounded by the same seam the theme already uses. The one real hazard is a persisted
palette that is no longer in the registry (a palette removed in a later release): `applyPalette` must
treat an unknown persisted value as the default and rewrite the store, or an operator is stranded on a
palette whose CSS no longer exists. Add that as a test.

**DoD.** Switching palette repaints charts, tints, shadows and scrollbars with **no remount** — assert
it by holding a Recharts tooltip open across a swap. `localStorage` round-trips. An unknown
`?palette=` and an unknown persisted value both land on `gogo`. Gallery baselines exist for all four
cells.

---

#### PQ2c — Flip the default *(superseded)*

**Goal.** Make `planiq` what a new operator sees. In the event this happened by deleting the axis, so
the appearance change is a normal commit rather than a one-line preference flip.

**Changes.** `usePrefsStore`'s `palette` default `"gogo"` → `"planiq"`, and swap which palette lives in
`:root` versus in an attribute block — because "the default is the attribute-less document" is what
preserves the no-flash guarantee, so the *default* palette must be the one in `:root`. That is a
mechanical move of two blocks, and key-set parity plus the annotation generator make it safe: the
numbers do not change, only which selector carries them.

**Depends on.** PQ2b. **Effort.** S. **Status: superseded — the default moved by removing the axis,
not by flipping a constant.**

**DoD.** Every gate green with the registry unchanged and only the two block *selectors* swapped.
Gallery baselines regenerate with `gogo` and `planiq` trading places and **no third image changing** —
if anything else moves, a value leaked between blocks.

---

### PQ3 — Geometry: radius, padding, elevation, scrim

**Goal.** Land §2.6–2.8. The largest visual delta per unit of test risk in the whole plan — nothing in
`tokenContrast.test.ts` touches radius, spacing or shadow geometry.

**Changes.**
- `src/styles/tokens.css:378-386` — repoint `--r-card`, `--r-button`, `--r-control`; add `--r-well`.
  **Do not renumber the rungs** (`tailwind.config.ts:150-170` projects them 1:1 and
  `DataTable.test.tsx:90-91` asserts `rounded-l-control` by *name*).
- **The rung sweep of §2.6** — the six inset wells to `rounded-well`, the four popover/dialog shells to
  `rounded-card`. `tailwind.config.ts` gains `borderRadius.well`.
- `src/styles/tokens.css:410-411` — `--card-pad: 16px`; **new** `--dialog-pad: 24px`; `--gutter` stays
  24; `--row-h-compact` stays 34 (§2.7). `tailwind.config.ts` gains `spacing["dialog"]`.
- `src/styles/tokens.css:358` and the dark block — `--shadow-overlay` adopts PlanIQ E6.
- `src/styles/tokens.css` — new `--scrim` in both palettes at the computed values of §2.8, **plus** its
  `GROUNDS` entry with the translucent-ground note and the two measured lines PQ1's reworked assertion
  now requires.
- `tailwind.config.ts` — no colour change; `--card-pad`/`--gutter` already project through
  `spacing.card`/`spacing.gutter`.

**Depends on.** PQ1 (appearance + gallery gates), PQ2 (so the scrim is measured against the new
grounds). **Effort.** M.

**Risk.** Real on the visual axis: `--r-card` 28 → 16 changes **40** hand-typed card sites plus the
27-site rung sweep at once. Land the alias repoint and the rung sweep as **two** commits so each
reverts independently.

**DoD.** `tokenContrast` green — the new `--scrim` forcing a classified `GROUNDS` entry with a measured
line *is* the gate working. Full `npx vitest run` at PQ2's number (radius assertions are by name).
`npm run e2e:gallery` — the section baselines move exactly where expected and nowhere else.
Browser-review at both themes: `/orders`, `/orders/:id`, `/live`, **`/config`, `/audit`, `/assets`, a
reveal dialog** (which is where most of the 27 stranded rungs live), and **one `/orders` screenshot at
`density: "compact"`**.

---

### PQ4 — Extract the primitives (zero visual change), in four tranches

**Goal.** Turn a 40-site card restyle into a 1-file restyle. Measured duplication: **40
`rounded-card bg-surface-card` sites in 29 files**, 13 files hand-styling
`rounded-control bg-surface-control`, 12 files with raw `<input>`, 42 `rounded-pill` sites in 31 files,
**6 files re-implementing `fixed inset-0` scrims**, and `EnumToggleGroup`/`TriStateSelect` existing
twice. Extract nothing and every screen migration is a simultaneous diff against 40 files.

Each primitive lands with the **byte-identical current class string** as its default and is added to
the PQ1 gallery in the same commit.

**PQ4a — `util/` (effort M).**
- **NEW** `src/components/util/Card.tsx` — `tone: 'default' | 'sunken' | 'error'`, `pad`, and a
  `className` escape hatch merged through `cn()`. **`pad` is not a three-value taxonomy**: the 40 sites
  use at least eight distinct paddings (`p-card` ×24, `p-4`, `px-4 py-2` `PlayerBar`, `px-5 py-4`
  `FilterBar`, `px-6 py-12` `EmptyState`/`AssetsScreen`, `px-8 py-12` `PermissionDenied`, `px-8 py-14`
  `NotFound`, `px-7 py-8` `AuthPanel`) plus five sites with no padding at all (`StatTile`, `DataTable`,
  `AttentionList`, `LiveFeed`, `LiveScreen:356`). Three options cannot be byte-identical to eight, so
  `pad` enumerates `'card' | 'tight' | 'roomy' | 'none'` for the four that recur and the remaining
  one-offs pass `className`; **PQ4a's commit message enumerates which of the 40 use the escape hatch**,
  and PQ5 is where those collapse deliberately and pixels are allowed to move.
  Migrate `EmptyState:41`, `ErrorState:90`, `ErrorBoundary:73`, `AsyncBoundary:130`.
- **NEW** `src/components/util/Field.tsx` + `Input`/`Select`/`Textarea` — **`size: 'sm' | 'md'`**, not
  `density`. `usePrefsStore.ts:39` already exports `density: Density` with the literals
  `'compact' | 'comfortable'`, persisted under `bayram.admin.prefs` and read by `DataTable.tsx:272` and
  `Skeleton.tsx:111` to pick `--row-h` vs `--row-h-compact`; reusing the identical name and literals
  for field padding would make every future `density` reference in the tree ambiguous. `isInvalid`
  renders an **`--error-tint` ground, never a red border**. PlanIQ draws no invalid state anywhere; the
  ground rule is ours and is right (a filter bar with six bordered controls above a 50-row table is six
  more lines competing with the data). `features/auth/FormField.tsx:1-20` explicitly declined this role
  — overrule it and rewrite the docstring. `DebouncedTextInput` (`features/users/filterControls.tsx:171`)
  folds in here rather than leaving a third debounce implementation in `features/users/`.
- **NEW** `src/components/util/DialogShell.tsx` — PlanIQ's three bands (header `border-b
  border-hairline`, body, footer `justify-end gap-3.5 border-t`), `size` mapping to PlanIQ's 540/680/763
  as `max-w-*`, and **one exported `DIALOG_SCRIM_CLASS`**. The body is **`p-dialog` (24px), not
  `p-card`** — §2.7. `CommandPalette` keeps its own geometry classes as *props*, never defaults.
- **NEW** `src/components/util/PermissionDenied.tsx` — the two sites (`AuditScreen:184`,
  `AdminsScreen:88`) are **not verbatim duplicates**: Audit says "Reading the audit log is an operator
  and owner capability"; Admins says "The operator roster is an owner capability — §6.8 gives
  `admin.read` to OWNER and to no other role" with an inline `<code className="type-mono">`. Only the
  trailing "Nothing was requested on your behalf, so this visit wrote no refusal row" is shared, and
  each also carries the route's own `<h1>`. So the signature is `<PermissionDenied title capability>`
  where `title` renders the `<h1>` and `capability` is the route-specific clause; the refusal sentence
  and the 🔒 glyph are fixed content. A naive collapse onto `EmptyState` (whose title is a `<p>`) would
  leave the route with **no `h1`**, breaking `routes.test.tsx` and the PQ9 route walk.
  **NEW** `PermissionDenied.test.tsx` asserts exactly one `<h1>` with the passed title.

**PQ4b — `data/` (effort M).**
- Migrate `DataTable:277`, `StatTile:141`, `ChartFrame:123`, `FilterBar:57` onto `Card`.
- **NEW** `src/components/util/Chip.tsx` — the tinted-capsule idiom behind `StatusPill`,
  `CreditBalanceChip`, `ErrorCodeBadge`, `CorrelationChip`, `OrderRefChip`, `TelegramUserChip`,
  `FilterChip`. Must emit `style={{ backgroundColor }}` in the same shape (tests assert exact inline
  `var()` strings). **`EnvBadge` is excluded** — its `prod` state is a deliberately inverted solid chip
  and is a safety affordance, not a style; say so in `Chip.tsx`'s docstring. `DurationBadge` uses
  classes not inline vars, so it takes the class escape hatch. `Chip` needs `tintVar` from
  `components/domain/colors.ts` but lives in `util/`; move `tintVar` to `src/lib/` rather than importing
  upward.
- **NEW** `src/components/data/EnumToggleGroup.tsx` and `src/components/data/TriStateSelect.tsx` —
  these exist **twice** today (`features/users/filterControls.tsx:43,104` and
  `features/generations/filterControls.tsx:34,86`), and `EnumToggleGroup` is the main consumer of the
  `segmentVariant` that PQ5 repoints to the solid-green selected pill. Extracting them *before* PQ5 is
  what stops that repoint from being a two-file edit forever. Each screen keeps its own option-label
  copy as props. `SingleEnumSelect` and `TextFilter` (generations-only) and `QuickFilterChip`
  (users-only) stay where they are; only the two duplicated ones move.

**PQ4c — `domain/` and `layout/` (effort M).**
- Migrate `AttentionList:87`, `LiveFeed:71`, `AssetCard:92`, `TimelineSourceLegend:87`,
  `PipelineTimeline`, `SimilarityHistogram`, `StrategyBakeoffChart`, `ConfigField`, `layout/PlayerBar:55`
  onto `Card`.
- **NEW** `src/components/layout/Section.tsx` — merges the two `Group` implementations and `Panel`
  (`LiveScreen.tsx:306,344`, `VendorsScreen.tsx:692`). **They are not verbatim.** `LiveScreen`'s takes
  `{ label, caption?: ReactNode, children: ReactNode }` and lays label and caption out as a
  `justify-between items-baseline` row; `VendorsScreen`'s takes `{ label, children: ReactElement }` with
  no caption and a bare `<p>`. **The merged signature is `LiveScreen`'s** — it is the superset, and a
  naive merge on the Vendors signature would silently drop the window captions, which is exactly where
  the `24 h window` caption was deliberately relocated to fix the audit's raw-ISO complaint. Vendors'
  `children: ReactElement` narrowing is dropped. The label stays a `<p>`, not a heading — the cards
  inside already own `<h2>`.
  **`Section` emits `data-section` on its root**, as part of its contract, so PQ9's route walk has
  something real to assert against. (`grep -rn 'data-section' src e2e` returns nothing today.)
- **NEW** `src/components/util/Fact.tsx` — merge the three copies (`OrdersScreen:567`,
  `OrderDetailScreen:1068`, `ChainVerifyPanel:138`).

**PQ4d — screens (effort L).**
- The remaining card sites: `UserDetailScreen` ×8, `OrderDetailScreen` ×6, **`NameStrategiesScreen` ×4**,
  `WizardStatePanel` ×2, `UserPeekDrawer` ×2, `AdminsScreen` ×2, and one each in `RetentionScreen`,
  `OrdersScreen`, `LiveScreen`, `GenerationsScreen`, `AttemptDetailPanel`, `AuthPanel`,
  `ChainVerifyPanel`, `AuditScreen`, `LyricSheetPanel`, `AssetsScreen`, `NotFoundScreen`.
- **NEW** `src/components/data/Toolbar.tsx` — PlanIQ A2 (`0:11342`), `context` · `filters` · `actions`
  slots in one `Card`. Build at **64px with 36px controls**, not PlanIQ's 82/48 — too tall for a 44px-row
  console. **No CTA slot**: PlanIQ's right end holds a green "Create task"; this console has almost no
  create actions and inventing one to fill a shape is how a reskin becomes a redesign.

**Depends on.** PQ3. **Effort.** M + M + M + L, four commits, four tags.

**Risk.** `codepointIntegrity.test.tsx:185-209` walks **every ancestor** of a rendered recipient name
and fails on any `uppercase|lowercase|capitalize|type-caption` class. `AttentionList` renders a
`NameText` inside a card, so `Card`, `Chip`, `Section` and any header slot they grow must never emit
`type-caption`. The failure message talks about codepoints and will read as unrelated; assert it
directly in `Card.test.tsx`. Secondary: the extraction is where testids and element tags get lost —
PQ0's global contract snapshot is the guard, and it should stay byte-identical through all four
tranches.

**DoD.** Per tranche: `npx vitest run` at **PQ3's number, with zero assertion edits** — if a test needed
changing, the extraction changed behaviour. After PQ4d:
`rg -c 'rounded-card bg-surface-card' src --glob '!*.test.*'` → **1**;
`rg 'fixed inset-0' src --glob '!*.test.*'` → **5**, all five the identical `DIALOG_SCRIM_CLASS` string.
(Not 1. There are 6 such sites today — `OrdersScreen:476`, `Drawer:99`, `KeyboardShortcuts:95`,
`CommandPalette:108`, `RevealDialog:213`, `ReasonConfirmDialog:161` — PQ0 removes one, and *adopting*
the shared class across the remaining five is PQ5, where pixels are allowed to move. Getting to 1 is
PQ5's DoD, not PQ4's.)
`npm run e2e:gallery` — every newly-added section has a baseline; no existing baseline moved.

---

### PQ5 — Restyle the primitives, and the green action pill

**Goal.** The first workstream that changes component pixels, deliberately after the extraction: one
file per idiom, and the screens already route through them.

**Changes.**
- `src/components/util/buttonVariants.ts` — geometry to PlanIQ (`py-3 px-4` at `md`, `rounded-button`
  now 10px). `primary` becomes `bg-brand-solid text-ink-on-brand` **plus a 1px
  `ring-1 ring-brand-solid-edge`** — without the ring the control has 1.21:1 of shape against the page
  and 1.30:1 against a card, and `--shadow-card` at `#0000000a` does not make up the difference. Both
  numbers go into the file's header table beside the 16.12:1 label figure: **the label ratio and the
  ground-against-ground ratio, before and after.**
- Same file — add **`variant: 'selected'`** = `bg-brand-solid text-ink-on-brand` + the same ring, and
  repoint `segmentVariant(true)` to it. That is where PlanIQ's identity actually becomes visible: the
  active nav row, every tab strip, every toggle group (now including the extracted
  `EnumToggleGroup`), in one line. `secondary` (`bg-brand-tint text-brand`) survives as the tint idiom.
- `src/components/layout/NavRail.tsx:122` — **delete the `isActive && "text-brand-fill"` icon
  override.** On the new solid pill that paints magenta `#bd32af` on mint `#75fc96` — measured
  **3.80:1**, which clears 1.4.11 but is an **unmeasured pair** (`--brand-fill`'s `ROLES` grounds are
  the five surfaces; `--brand-solid` is not among them), i.e. exactly the "green suite over an
  unmeasured pairing" class PQ1 exists to close, introduced by PQ5. It also contradicts §1's own reason
  for holding the hue layer still. The solid ground plus the black label plus `font-semibold` plus
  `aria-current` already carry three channels; the icon inherits `--ink-on-brand`.
  *(Rejected: the alternative of adding `--brand-solid` to `--brand-fill`'s `ROLES` grounds so the pair
  is measured. It passes at 3.80, but it licenses magenta-on-mint everywhere `--brand-fill` is painted
  and buys a channel we already have three of.)*
- Same file — add `variant: 'danger-solid'` = **`bg-error text-ink-on-error`** for the confirm step of
  an irreversible action; keep `danger` as the tint for in-row destructive affordances. The pair is
  **not** "already measured" as the first draft claimed — `--error` appears in `ROLES` only as a
  *foreground*, and the `EnvBadge` prod chip that uses this pairing is unmeasured today (light 5.72,
  dark 5.68). PQ2's new `--ink-on-error` role is what makes it measured; this variant simply uses it,
  and `EnvBadge.tsx:149`'s `text-surface-card` is rewritten to `text-ink-on-error` in the same commit.
  **Reject** PlanIQ's `#DF1C41` solid + `radius 100` pill: a new solid red needs a new token, a new
  `ROLES` entry and a new annotation, and a pill shape that appears only on delete makes it look like
  it came from a different product.
- Same file — add `isLoading`: a leading spinner slot reusing `animate-pulse-ring`, with `aria-busy`.
  **Name its colour**: `currentColor` on every variant, so on `primary`/`selected` it inherits
  `--ink-on-brand` (16.12:1 on the green) and needs no new measured pair. Neither PlanIQ nor this
  console has one; every mutation dialog currently just disables.
- Same file — **reject PlanIQ's secondary button** (white + `#DFE1E7` border) explicitly in the header,
  beside the existing rationale. It is precisely the grey-on-grey idiom this file documents deleting;
  PlanIQ's secondary is not a better design, it is the same design pre-fix.
- `src/components/util/Button.test.tsx` — 11 of 14 tests assert exact class vocabulary
  (`:26-28, :37-38, :45-47, :60-61, :66-69, :74-75, :84-86, :92, :102-106, :123-128, :135-140`). Update
  **one at a time**, writing each new measured ratio into the file's header table.
  `src/features/audit/AuditScreen.test.tsx:278-315` re-asserts the same vocabulary through
  `segmentVariant` — same commit.
- `src/components/util/Card.tsx`, `Field.tsx`, `DialogShell.tsx`, `Chip.tsx` — geometry to §2.6/§2.7,
  and the PQ4a `className` escape hatches collapse into the enumerated `pad` values here, where pixel
  movement is intended. Field height 52 for dialog forms only; filter bars stay ~36px (`size="sm"`) or
  every screen loses a table row.
- `src/components/domain/RevealDialog.tsx:213`, `ReasonConfirmDialog.tsx:161`,
  `KeyboardShortcuts.tsx:95`, `CommandPalette.tsx:108`, `Drawer.tsx:99` — adopt `DIALOG_SCRIM_CLASS` and
  `--scrim`. Reconcile `opacity-40` vs `opacity-30` and state the reason (they become one value; §2.8
  computed it at 2.06:1 light / 1.18:1 dark).

**Depends on.** PQ4. **Effort.** M.

**Risk.** `buttonVariants` has ~20 consumers and `segmentVariant` feeds the nav rail's active state; one
bad pair ships everywhere at once. That is the seam working, but every new variant naming a colour must
be re-measured in **both** palettes with the ratio written into the header table — that table's numbers
being computed rather than estimated is the file's entire credibility. `RevealDialog.test.tsx` has 72
testid references and `GrantCreditsDialog.test.tsx` 36; `DialogShell` must render children verbatim so
the reveal flow's focus order and `aria-describedby` wiring do not move.

**DoD.** `npx vitest run` at PQ4's number with **intentionally** updated assertions, each named in the
commit. `rg 'fixed inset-0' src --glob '!*.test.*'` → **1**. `npm run e2e` green — especially the ⌘K
geometry step (`smoke.spec.ts:186-202`, which also guards the `react-remove-scroll` CSP-nonce bug; do
not relax it) and the scroll lock (`:219-231`). `npm run e2e:appearance` now asserts the primary
button's **ring** as well as its ground and label. `npm run e2e:gallery` is the acceptance evidence.

---

### PQ6 — Shell chrome

**Goal.** Land §3's adopted half.

**Changes.**
- `src/components/layout/AppShell.tsx:55-78` — rail and main float on the page ground with a
  `--gutter`-derived inset. The `flex h-full min-h-0 flex-col` chain and `<main>`'s `overflow-y-auto`
  are untouched. `--surface-nav`/`--surface-topbar` keep pointing at `--surface-card`; what changes is
  geometry, not the token.
- `src/components/layout/NavRail.tsx:183-187` — `rounded-card`; `w-nav`/`w-nav-collapsed` kept as
  *class names*.
- `src/components/layout/NavRail.tsx:57-61` — rows `rounded-button` → `rounded-pill`, `px-3` → `px-4`.
  The `phase 3` chip (`:86-93`) is unchanged: PlanIQ has zero vocabulary for a non-interactive nav
  item, and "not yet" said in words rather than by dimming is the rule (`:79-85`).
- `src/components/layout/TopBar.tsx:159-192` — `rounded-card` on the header; group
  `LiveHeartbeatPill` + `PaletteTrigger` + `TimeZoneToggle` + `ThemeToggle` + `?` into one
  `rounded-pill bg-surface-card` container at `gap-2`, `AccountMenu` outside at 8px.
  **`TimeZoneToggle` stays wide** — the current zone is written on its face (`:120-123`) and shrinking
  it to an icon reintroduces the "click to find out which clock you are reading" support incident.
  **No notifications button** — `:29-32` already refuses it by name; PlanIQ having one is not a reason.
- `src/components/layout/CommandPalette.tsx:176-216` — PlanIQ A9's row internals: a leading `size-8
  rounded-2xs bg-surface-sunken` tile holding the existing `KIND_GLYPH`. The `unavailable` row keeps
  its sentence ("Searching by recipient name is not available on this build") — it is a claim, not a
  category. **Do not move the box**: `left-1/2 top-[12vh] w-[min(38rem,94vw)]` is measured numerically
  at the pinned 1512×900 viewport. Keep the combobox+listbox shape with `aria-activedescendant`;
  PlanIQ draws no keyboard model and must not be allowed to suggest a menu.
- `src/components/layout/PlayerBar.tsx:50-56` + `src/components/domain/AudioPlayer.tsx:309` — reconcile
  radius/shadow; the scrubber adopts PlanIQ's `213×3 radius-4` track geometry (`--surface-control`
  track, `--brand-fill` fill). Render site, `key`-lessness and null-track behaviour untouched.
- `src/components/layout/PageHeader.tsx:97` — reconcile horizontal padding so content is indented once,
  not twice. Record the derived content width (~1200px at 1512) in the docstring so downstream work
  re-derives PlanIQ's grids instead of transcribing them.
- **Stale prose, no behaviour change:** `AppShell.tsx:21` and `NavRail.tsx:27` say "eleven items"
  (twelve since Vendors); `AppShell.test.tsx:56` likewise; `NavRail.test.tsx:1,82` say 220/64px (tokens
  are 264/76); `breadcrumbs.ts:10` says twelve screens render `PageHeader` (thirteen);
  `PasswordRotationGate.tsx:14-21` shows the gate nested *inside* `AppShell` where `RootLayout.tsx`
  correctly has it outside.
- **Optional, defer unless narrow viewports are in scope:** a horizontal fallback below `md`, reusing
  the same `NAV_SECTIONS` data and the same `NavRow`, keeping `aria-label="Sections"`, rendering *one or
  the other* — never both, or every named `getByRole` in five files goes ambiguous.

**Depends on.** PQ5. **Effort.** M.

**Risk.** Any pattern that makes the shell root taller than the viewport hands `<body>` a scrollbar and
fails a browser gate whose real job is an unrelated CSP bug. And `navHref(item)` must still be called
*during render* — precomputing an href map for a horizontal variant yields `undefined` on every item: a
silently unnavigable console, caught only by `routerCycle.test.tsx`.

**DoD.** `npx vitest run src/components/layout src/app src/routes.test.tsx` green — all 9 `NavRail`
tests including the exact twelve-item order array, the `getByRole("separator")` rule, the three phase-3
assertions and the three RBAC assertions. `npm run e2e` green; `smoke.spec.ts` contains no nav
assertion, so a failure there means the change reached past the shell. `npm run e2e:gallery` +
manual review of the shell at both themes.

---

### PQ7 — Data display: wire what is already built, and re-skin absence

**Goal.** The most under-used surface in the console, and PlanIQ's dashboard read is exactly what it
needs.

**The premise, corrected.** The first draft said `StatTile`'s `delta`/`trend`/`trendLabel` are used
zero times, citing `rg 'trend=' src/features` → 0. That grep is blind to a spread.
**`src/features/users/UsersScreen.tsx:501-506` already passes both** —
`{...(series === null ? {} : { trend: series })}` plus a literal `trendLabel` — fed by
`src/features/users/newUsers.ts`, a 90-line module written for exactly this. `Sparkline` is reached
*through* `StatTile`, so "imported by no screen" is true and misleading. The accurate statement:
**`trend` is used on exactly one screen (`/users`), `delta` on none (`rg 'delta=' src/features` → 0),
and `ChartFrame`'s `actions` slot on none** (its three `actions=` hits in `src/features` are all
`PageHeader`'s). `ChartFrame` appears at **3 call sites across 2 screens** (`VendorsScreen:569,609`,
`AuditScreen:585`).

**And `newUsers.ts` is the precedent for the gap-filling decision, so it does not need re-deriving.**
Its docstring already settles the hard case: the window is closed at both ends because "an end
recomputed per request is a DIFFERENT end per request, and this series is bucketed by day"; and **a
truncated page yields no series at all**, because a sparkline built from one would show a cliff that is
an artefact of the page size. Vendors and Live adopt the same rule verbatim.

**Changes.**
- `src/features/live/liveMetrics.ts` — add `TREND_WINDOW_DAYS = 30` and `trendWindow(now)` quantised
  like `rollingWindow`; `dailyDeliveryRates(days)` mapping each `OrdersPerDayView`;
  `compareWindows(current, previous): StatDelta` where a falling failure count is
  `direction: "down", tone: "good"` (the `DeltaChip` splits direction from tone — strictly better than
  PlanIQ, which has no such split).
- `src/features/live/useLiveOps.ts` — a `trend` query on `queryKeys.metrics.ordersByDay(trendWindow)`
  at the default policy (**not** `POLL_MS.pulse` — a 30-day aggregate does not change in 5s) plus a
  previous-24h query for the delta denominator. Both against an endpoint we already ship.
- `src/features/live/LiveScreen.tsx` — hero `StatTile` gets `delta` + `trend` + `trendLabel`;
  `failed · 24 h` and `paid · 24 h` get `delta`. Add a `ChartFrame kind="stacked-bar"` "Delivery per day
  · 30 days" with `series` on `--st-delivered`/`--st-failed` **plus their mandatory dash and marker** —
  `tokens.css` records, and the harness confirms, that those two are **1.00:1 against each other in
  luminance** in light (both pushed to the same lightness to clear 4.5:1 on white, 156 apart in sRGB),
  so hue is not a channel there.
- `src/features/live/LiveScreen.tsx:555-573` — the failure mix is captioned **"all time, from the
  pulse"** on an operations screen. `getFailures(window)` and `getLatency(window)` are fully typed in
  `api/endpoints.ts:563-587`, windowed, and called by **nothing in the SPA**. Repoint at `getFailures`
  over the rolling 24h and change the caption to name the window. Drop the pulse's array — two
  all-time/windowed sources on one screen is the ambiguity this fixes.
- **NEW** `src/components/data/ProportionRow.tsx` — the mark four components hand-roll
  (`StateDistributionBar`, `LiveScreen`'s `FailureMix` which draws no bar at all,
  `StrategyBakeoffChart`, `SimilarityHistogram`). Rank badge → label → `flex-grow` fill →
  right-aligned `.num` count and rate. **`share === null` renders hatched with the literal "not
  measured"**, never a zero-width fill. Adopt in `FailureMix` and `StrategyBakeoffChart` (preserving its
  fixed `NAME_STRATEGY_VALUES` order and its "zero attempts renders no bar" rule). **Do not** fold in
  `StateDistributionBar` (a single stacked band whose segment order and 2px gaps are pinned) or
  `SimilarityHistogram` (its threshold band and four-channel marking are semantic).
- `src/components/data/ChartFrame.tsx:201` — PlanIQ chart chrome: `<CartesianGrid vertical={false}
  stroke="var(--hairline)" strokeDasharray="2 2" />`, `axisLine={false} tickLine={false}` on both axes
  (PlanIQ has no axis lines or ticks anywhere). Fill the `actions` slot with a **drill-through link plus
  a window echo** — *not* a per-chart range chip. `TimeRangePicker.tsx:6-7` states the rule: "One picker
  per screen, in the `FilterBar` row, scoping everything below it — never one per chart." Two pickers
  produce two windows and a screenshot nobody can reconstruct.
- `src/components/data/chartTokens.ts` + `ChartFrame.tsx` — an absence pattern: 45° hatch over
  `--surface-sunken` for a null datum in a bar series, with a `nullLabel` default of "not measured" in
  both the tooltip and the `<details>` table twin. **Decide the stroke token before authoring** —
  `RULE_WAIVERS` is empty on purpose and the first entry matches on an exact source line.
- **NEW** `src/components/domain/AbsentValue.tsx` — one component for the four absences already spoken
  in prose: `not-instrumented`, `nothing-in-window`, `nothing-priced`, `source-unavailable`. Required
  discriminated `kind`, no default. Adopt in `VendorsScreen` (whose docstring already forbids drawing
  `$0.00`) and `LiveScreen`'s capabilities panel.
- `src/components/util/EmptyState.tsx`, `ErrorState.tsx:90-94`, `AsyncBoundary.tsx:130,216-224`,
  `Skeleton.tsx` — re-skin onto `Card`/`Chip`, keeping the virgin-vs-filtered split, the `isDrift` fork,
  the 70%-opacity stale render and `aria-busy`. **PlanIQ contributes nothing here and must not be
  consulted.**
- `src/features/vendors`, `generations`, `audit`, `retention`, `users` — wire `delta` on the tiles whose
  direction has a fixed meaning, and `trend` on Vendors from the `vendor-usage-by-day` series **the
  screen already fetches** (zero new requests), under `newUsers.ts`'s truncated-page rule. Cost tiles
  draw no trend when `isCostPriced` is false — a flat line at zero reads as "we spent nothing".

**Depends on.** PQ5. **External blocker, acknowledged:** every cost and latency figure this workstream
would trend is gated on WS3 (provider instrumentation). `GenerationAttemptRepository.record()` has no
call site in `src/` and `generation_attempts.cost_usd`/`.latency_ms` have no writer, so their defaults
read "free" and "instant". PQ7 ships the *presentation* rule for that (`isCostPriced === false` → no
trend, `AbsentValue kind="nothing-priced"`), and the numbers arrive when WS3 does. **Effort.** L.

**Risk.** Two. (a) **Gap-filling.** The API omits a day with no orders, and that is genuinely ambiguous
— none created, or none terminated. Zero-filling a *rate* would draw a 0% success day on a quiet
Sunday, the most alarming wrong number this console could show. Recommendation: sparkline the delivered
**count** (which zero-fills honestly) while the figure above stays the rate; write which and why in the
docstring, and cite `newUsers.ts`. (b) **Delta tone is a product judgement per metric** and must be
stated at each call site, never derived: rising spend is `bad`, rising deliveries `good`, rising reveals
`bad`. `neutral` is the honest default and the component already does it.

**DoD.** New `liveMetrics` tests for the gap case, the null-rate day and the direction/tone split.
`LiveScreen.test.tsx` gains a case asserting the failure-mix caption names a window rather than "all
time". `VendorsScreen.test.tsx` keeps its no-`$0.00` assertion. `AbsentValue.test.tsx` covers all four
kinds with their exact sentences. Full suite at PQ6's number plus the named new cases.

---

### PQ8 — Screen sweep

**Goal.** Move **all 15 routes** onto the new vocabulary — the first draft opened with "15" and then
assigned 12. Ordered by test coupling ascending × operator value descending, so the cheapest screens
prove the idiom before the expensive ones adopt it.

**PQ8a — Reference: Live + auth (effort M).**
`LiveScreen.tsx` deletes its local `Group`/`Panel` for `Section`. `AuthPanel.tsx:47,57` onto `Card`;
`FormField` → `Field.Text`. **Reject PlanIQ A10's 665×976 marketing panel** — an internal console has
no product pitch, and the split would put the credential form in a 641px column with nothing to say
beside it. `e2e/smoke.spec.ts:106-122` pins `#username`/`#password`/`#currentPassword`/`#newPassword`/
`#confirmPassword`, so `Field.Text` must forward `id` verbatim.

**PQ8b — Six list screens onto `Toolbar` (effort L).**
`OrdersScreen:204-233`, `UsersScreen:526-621` (the `q` box, exact-id field, the now-shared
`EnumToggleGroup`/`TriStateSelect`, quick-filter chips — `Q_PLACEHOLDER`/`Q_HINT` copy unchanged, name
search is a deliberate server-side refusal), `AuditScreen:442-554`, `AdminsScreen`,
`RetentionScreen:203-260`, `AssetsScreen:206-297`. Both `PermissionDenied` sites collapse onto the
PQ4a component. `ChainVerifyPanel` (the body of `/audit`'s "Standing checks", one `rounded-card` plus a
`rounded-2xl`) adopts `Card` here so it does not keep 28px corners inside a 16px screen.
`DataTable` adopts PlanIQ A4's *chrome only* — header on `--surface-sunken`, no zebra, no dividers
(already true). **This changes a test with a stated rationale, and the change is part of the tranche,
not a surprise:** `DataTable.test.tsx:66-73` asserts `expect(header).toHaveClass("bg-surface-card")`
because "the head is a label row, not a filled bar — but it still has to occlude the rows sliding under
it, and the card colour is the one opacity that is invisible." The occlusion argument still holds
(`--surface-sunken` is opaque) but that sentence becomes false; update the assertion to
`bg-surface-sunken` and rewrite the comment to say the head is now a filled bar by design.
**Reject A4's type scale** (its header is 16/400 and its cells 12/600 — an inverted hierarchy) and
**its column-major DOM** (structurally incompatible with TanStack's row model, and it breaks table
semantics).

**PQ8c — Vendors, Name strategies, Not found (effort M).**
The three routes the first draft never assigned. All three are low-coupling
(`VendorsScreen.test.tsx` 419 lines, `NameStrategiesScreen.test.tsx` 261, `NotFoundScreen` none), so
they are cheap **and** they prove the `Group`→`Section` merge and the `ChartFrame` chrome change before
the two 1000-line detail screens adopt them.
- `/vendors` (`VendorsScreen.tsx`, 707 lines) — the richest chart screen in the console: two
  `ChartFrame`s, two `DataTable`s, a `FilterBar` and its own `Group`. PQ7 wires `delta` and `trend`
  into its tiles; without this tranche the migration ends half-ported, with new tiles in an old
  container. Its four `Group`s become `Section`s (on the `LiveScreen` superset signature, §PQ4c).
- `/generations/names` (`NameStrategiesScreen.tsx`, 365 lines, **4 `rounded-card` sites** — the
  third-highest count in `features/` after the two detail screens) — `Card` + `Section`;
  `StrategyBakeoffChart` picks up `ProportionRow` from PQ7.
- `*` (`NotFoundScreen.tsx`, 58 lines) — one card site, `px-8 py-14`, and it renders its own `<h1>`
  outside `PageHeader` (`:40`). It stays that way; only the card shell changes.

**PQ8d — Two detail screens (effort L).**
`OrderDetailScreen` keeps its `lg:grid-cols-12` at `:377`; six card sites → `Card`, local `Fact`
deleted. `UserDetailScreen`'s `Profile` (`:516`) and `Credits` (`:609`) adopt PlanIQ A5's
`description-left / content-right` section; `Orders` and `Wizard session` stay full-width — and
**`WizardStatePanel.tsx` (2 card sites, the body of that section) adopts `Card` in this tranche**, so
the layout decision and the panel decision are made together. **No testid may be added, removed or
renamed** — 37 and 65 references respectively.

**PQ8e — Side panels → drawers, and Config (effort M).**
`GenerationsScreen.tsx:440-441` (`xl:grid-cols-[minmax(0,1fr)_24rem]`) and `AssetsScreen.tsx:299`
squeeze a table to make room for a detail panel — the audit's still-open complaint. PlanIQ's answer is
instructive *by omission*: it has no side-panel archetype at all; detail is always a modal or popover.
Move `AttemptDetailPanel` into the existing `Drawer` (which was extracted from exactly this pattern on
Orders), keeping `?attempt=<uuid>` so pasted links resolve.
`ConfigScreen.tsx:107-129` adopts PlanIQ A5 properly — the kit's **one true 1:1 match**: one `Card`, a
left menu of group names, a right pane of description/content sections, with the legend as the first
section and `ABSENT_RUNTIME_FIELDS` as the last menu entry so "what this panel cannot show you" is
navigable. **Note the group source:** `ConfigScreen` renders `groups.map(...)` from the `GET /api/config`
response, not from a local constant, plus one locally-defined `ABSENT_RUNTIME_FIELDS` section
(`configFields.ts:220`). If the endpoint yields fewer than three groups the menu is dead weight and
Config shrinks to a re-skin — check the live response before building the menu.
**`ConfigField.tsx` is named here, with an explicit decision.** It is what Config is entirely made of,
and the first draft redesigned the pane while leaving its contents as 24px cards inside a 16px card. Its
four visual tiers (`live` / `after-fix` / `read-only` / `secret-absent`) are an **operational fact, not
decoration** — the docstring says a `secret-absent` field rendered as an empty string reads as a broken
chain. Decision: **the tiers survive as cards**, adopting `Card` with a `tone` per tier, keeping the
`rounded-2xl → rounded-card` repoint from PQ3, the inline-styled tier chip as the fourth channel, and
`secret-absent`'s drop to `bg-surface-control shadow-none`. They do **not** become rows in the A5
section; a tier that is only a chip loses the ground channel.
**Normalise PlanIQ's ×1.26087 scale first** (252.174→252, 46.174→**44** to match `--row-h`,
20.174→20, 15.130→12) and use `segmentVariant` for the active row, not PlanIQ's `#F6F8FA` + border +
weight bump.

**Depends on.** PQ8a–c need only PQ5; PQ8b–e also want PQ7's `ProportionRow`/`AbsentValue`.

**Risk.** PQ8d is the highest test coupling in the plan (638 + 1045 lines of test). PQ8e's Config menu
adds a **third** navigation landmark to the page — PQ0's `RootLayout` fix is the prerequisite.

**DoD.** Per tranche: `rg -o 'data-testid="[^"]+"' <files> | sort` byte-identical before and after, and
PQ0's global contract snapshot unchanged. All screen suites green — including `DataTable.test.tsx`,
whose one intentional edit is named in PQ8b's commit. `e2e/smoke.spec.ts` green including `tbody tr`,
`.type-hero, .type-metric` and the `?attempt` link. Manual at 1280px: `/generations` shows every column
with no 24rem panel stealing width.

---

### PQ9 — Close-out

**Goal.** Make the reskin auditable and revertable.

**Changes.**
- **NEW** `docs/product/ADMIN_PANEL_PLANIQ_MIGRATION.md` — the as-built record, with the axis relationship in
  its first paragraph and each workstream naming the PlanIQ node ids it adopted *and rejected*.
- `e2e/smoke.spec.ts` — a step walking all 12 rail routes asserting each renders **exactly one `<h1>`
  and at least one heading at level 2**. The first draft asserted `[data-section]`, an attribute that
  did not exist and that no workstream created; PQ4c now makes `Section` emit it, but six of the fifteen
  routes have no `Group`/`Section` idiom at all — Config, Admins, NameStrategies, NotFound, Login,
  ChangePassword — so a `[data-section]` walk would fail on Config and Admins **by construction**. The
  `h1` + `h2` form holds on every route today and is what "the screen still has its structure" actually
  means. (A second, narrower step may assert `[data-section]` on the routes that do use `Section`:
  Live, Vendors, and anything PQ8 converts.)
- CI order: `lint → typecheck → vitest → tokens:check → build → playwright (appearance, gallery, smoke,
  font-coverage)`. **This chain does not exist end-to-end in the repo today**; PQ1 creates the three new
  scripts and PQ9 is where the chain is written down and owned. The 4 known-red `hbd_test` integration
  failures are environmental (missing DB grants on `hbd_test`, recorded in project memory), are **not**
  in this chain, and are documented as known-red rather than silently tolerated.
- **Rollback:** one squashed commit per **tranche**, tagged `pq0`, `pq1`, `pq2`, `pq3`, `pq4a`…`pq4d`,
  `pq5`, `pq6`, `pq7`, `pq8a`…`pq8e`, `pq9`, with the palette as `pq2`. Because PQ2 is
  values-plus-four-role-edits and PQ4's
  extraction is behaviour-neutral, reverting the palette does **not** strand the primitives — which is
  the main reason to extract before restyling. Per-tranche tags rather than per-wave tags because the
  waves are not comparable increments (PQ4 and PQ8 each outweigh W1 and W2 combined).
- **No feature flag, and no parallel *theme* — but a parallel *palette*, which is a different thing.**
  The first draft forbade both, and half of that was right. The objection was never to a second look;
  it was to an **unmeasured** one: a third `[data-theme]` block is parsed and never measured because
  `PALETTES` was a hardcoded 2-tuple, and the annotation burden grew with nothing checking it. §2.0
  answers each of those rather than ignoring them — the registry-closure assertion makes an unmeasured
  block *impossible to add*, key-set parity makes a partial block impossible to write, and the
  annotation generator makes the burden free. **A palette earns its place by clearing 244 assertions in
  both themes; a feature flag earns its place by nobody looking.** That is the distinction, and it is
  why the build-time swap the first draft recommended (a Vite `resolve.alias` over `tokens.css` plus a
  CI matrix) is now *worse* than the runtime axis: it ships one palette, so the comparison the decision
  actually needs cannot be made by the people making it.
  - Still true, and unchanged: `data-theme` stays a **two**-value axis. Tailwind's `darkMode` supports
    one alternate selector, and PQ1's selector assertion keeps it at `{dark}`. The palette axis costs
    Tailwind nothing because the config projects `var()`, never hexes.

**Depends on.** PQ8. **Effort.** M.

**DoD.** Dry-run the rollback on a scratch branch: land PQ2, `git revert` it, confirm the vitest count
returns to PQ1's (PQ2 is values-only so it changes no count; the absolute
number is PQ1's baseline, not 1409, and every DoD in this plan is phrased against "the count at the head
of the previous workstream" for exactly that reason). Confirm `e2e:appearance` passes against the
original palette. **A rollback story that has never been executed is not a rollback story.**

---

### PQ10 — Manrope (optional, price separately)

**Goal.** The kit's real typeface. ~1000 lines of e2e rewrite, coupled to nothing else in the plan.

**The blocker is not the swap.** `e2e/font-coverage.spec.ts`'s negative control is that **Urbanist has
no Cyrillic** — it asserts Urbanist draws `Oʻktam` and does *not* draw `Дилноза`. Manrope covers
Cyrillic itself, so a Manrope-first `--font-heading` makes the Mulish fallback redundant and kills the
gate's ability to distinguish "our font drew this" from "the host did". **Design the replacement control
before touching a stack** (cheapest: keep Urbanist vendored *only* as the control face, at the cost of
one 34KB woff2 that ships and is never used — state that trade explicitly).

**Changes.** `tools/build-fonts.py` fetches Manrope (OFL 1.1, `wght 200–800`) and **re-measures the
cmap** for Ғ U+0492, Қ U+049A, Ҳ U+04B2, U+02BB, U+02BC — the Cyrillic claim comes from Google's
published subset list, not a binary. `src/styles/fonts.css:139-156` goes Manrope-first for sans and
heading; `--font-mono` stays (PlanIQ has zero monospace anywhere, and ids, hashes and Cyrillic names
depend on it). The §2.5 scale lands in all three synced places (`index.css`, `tailwind.config.ts`,
`lib/utils.ts` `TYPE_SCALE_UTILITIES`) in one commit. **Do not vendor Satoshi** — ITF Free Font Licence,
not OFL, not on Google Fonts, 33 decorative chat-mock nodes.

**Risk.** Dropping Urbanist without a control silently weakens the gate from "our face rendered these
glyphs" to "something did", and the failure is invisible until an Uzbek name renders as `.notdef` boxes
in production. `tokenContrast.test.ts:984` fails if `--font-*` ever re-enters `tokens.css`.

**DoD.** `npx playwright test font-coverage` green with the new control; the attached probe screenshot
shows `Oʻktam`, `Gʻulom`, `Дилноза`, `sanʼat` as glyphs. Independent cmap verification via fontTools,
not the spec.

---

## 5. Migration waves

Waves are a narrative for stakeholders; **the revert unit is the tranche tag, not the wave**, because
PQ4 and PQ8 are each larger than W1 and W2 combined.

**The revert point, now that there is no palette switch.** W2 changes the console's appearance for
everyone in one commit, and the only way back to the console as it stood is the tag at the end of W1 —
not a preference, and not a partial revert, because PQ3's geometry lands in the same wave.

| Wave | Workstreams | Effort | What the console looks like after |
|---|---|---|---|
| **W0** | PQ-1 | S | **Identical.** The tree is committed. Everything downstream is now revertable. |
| **W1** | PQ0 + PQ1 | S + L | **Visually identical.** Three real bugs fixed (the peek drawer traps focus and closes on Escape; two dead utilities gone). Four silent evasion routes closed, including the tie-break one nobody had noticed. For the first time a rendered-colour gate reads real computed colour in both themes under the real CSP, `tokens:check` recomputes every annotation, and a dev-only gallery holds per-section pixel baselines. Nothing has moved, and now nothing *can* move unnoticed. |
| **W2** | PQ2 + PQ3 | M + M | **Recognisably PlanIQ, with zero component edits.** Page ground `#f6f6f6`, dark page `#111111` on `#1b1b1b` cards. Primary buttons and active nav pills are `#75fc96` with black labels at 16.12:1 (up from 4.95:1) **and a `#218c3b` ring at 3.78–4.30:1 so the control still has a shape**. Cards sharpen 28 → 16, buttons 16 → 10, card padding 24 → 16 while modal bands stay at 24; the 27 stranded inset wells and popovers follow. Popovers get PlanIQ's cool-grey elevation and a scrim computed to today's separation rather than transcribed to 1.73:1. Semantics, states, glyphs, charts — untouched. Two `git revert`s. |
| **W3** | PQ4a–d + PQ5 | M+M+M+L + M | **One card, one field, one dialog, one chip, one toggle group.** 40 card sites → 1 file; 6 scrim recipes → 1; 42 pill sites → 1; the duplicated `EnumToggleGroup`/`TriStateSelect` → 1 each, just in time for `segmentVariant` to be repointed once. Then those restyle at once: PlanIQ's three-band modal at its own 24px inset, its field rhythm on our ground-not-border invalid state, a solid-green selected segment whose icon finally inherits its own label colour, a loading state, and a measured `danger-solid`. |
| **W4** | PQ6 + PQ7 | M + L | **The shell floats and the data speaks.** Rail and top bar become detached rounded surfaces; the four utility controls group into one pill; the palette gets PlanIQ's icon-tile rows without moving a pixel of its box. Live Ops gains its first chart, its failure mix stops being all-time, and `StatTile`'s delta chips and full-bleed sparklines — built and tested, used on exactly one screen — light up across ten. Absence gets a re-skin of its own rather than rotting. |
| **W5** | PQ8a–e + PQ9 | M+L+M+L+M + M | **All 15 routes on one vocabulary**, Vendors and Name strategies included. Six list screens share a toolbar; two detail screens adopt the description/content section; the two squeezed tables get their full width back and their detail moves into a drawer; Config becomes the kit's one true 1:1 match, `ConfigField`'s four tiers intact. The e2e walk asserts every route keeps its `h1` and its section headings, and the rollback has been executed once on a scratch branch. |
| **W6** | PQ10 *(optional)* | L | Manrope, once its replacement negative control exists. |

---

## 6. Risks & the accessibility contract

**The contract survives because the vocabulary barely moves.** `ROLES` is generated by `trio()` over
`FAMILIES` / `ORDER_STATES` / `PIPELINE_STATUSES` and `SURFACES` — five surfaces, five inks, three line
tokens, nine families × 3, `st-*`, `pg-*`, `c-1…8`. This plan preserves every one of those names. The
`ROLES`/`GROUNDS` diff is **four edits, enumerated in PQ2 and PQ3**: two new tokens
(`--brand-solid-edge`, `--ink-on-error`), one widened ground set (`--focus-ring` gains
`--brand-solid`), one new ground (`--scrim`). That still inverts the naive reading that a palette swap
rewrites 17% of the suite — but the real annotation work is **53 lines, not ten**, and
`tools/annotate-tokens.mts` derives all 53 from the same arithmetic the test uses.

**The measured result, run against the live `tokens.css`:** baseline 0 failures light / 0 dark
(reproducing the tree, 35 + 33 annotations, zero drift); candidate 0 failures light / 0 dark; 53
annotation lines need their number rewritten, of which 7 also change the ground they name.

| Risk | Why it bites | Mitigation |
|---|---|---|
| **The primary button loses its shape** | `#75fc96` is 1.21:1 on the page and 1.30:1 on a card, down from 4.75/4.95, and `--brand-solid`'s single closed-pair `ROLES` ground means the gate can never see it. This is the plan's own central move and the one thing a "244/244 green" DoD would have hidden. | `--brand-solid-edge` `#218c3b` at 3.78–4.30:1, with its own `ROLES` entry, applied by `primary` and `selected`; PQ1's reverted spike produces the failing number as evidence; both figures in the deviation log and in `buttonVariants.ts`'s header. |
| **An uppercase hex from a design tool** | `ANNOTATION` is `[\da-f]` with no `i` flag and the must-annotate filter is `{6}` only. The token is neither required to carry an annotation nor checked against one, while the role-bar test still passes. This is *the* highest-probability way a reskin breaks the contract green. | PQ1's lowercase assertion, landed **before** any hex moves. |
| **A five-way argmin tie** | After PQ2 the light darkest ground is `--brand-tint over <any surface>` at L 0.80517 — identical for all five, because tints are opaque — 0.00178 from `--surface-control-hover`. `:562` compares the argmin **as a string**, so `--ink`, `--ink-muted`, `--ink-mark` and `--brand` are correct only by V8 sort stability. | PQ1's tie-aware comparison (`toContain` over the set within 1e-9) plus §2.4's corrected guardrail freezing **both** values. |
| **A sixth surface, or a translucent ground** | A new surface satisfies completeness via `GROUNDS` alone and is then never a measurement ground, forever, green. A prefix-keyed fix would not have covered `--scrim`, which this plan adds. | PQ1's role-keyed assertion: opaque ⇒ must be in `SURFACES`; translucent ⇒ must carry an `over which surfaces` note and a measured line. |
| **An 8-digit role token** | `ANNOTATION` accepts `{6,8}`; the must-annotate filter does not. PlanIQ leans hard on alpha (`#FFFFFF0A`, `#75FC961F`). | PQ1 widens the filter to `{6,8}`. |
| **A third `[data-theme]` block** | `PALETTES` is a hardcoded 2-tuple — parsed, never measured. | PQ1's selector-set assertion; and no feature flag by design. |
| **Widening a role instead of fixing a colour** | The temptation when something fails. The tint-over-five-surfaces ground set exists *because* a curated list hid a 3.90:1 shipped defect across every family in both palettes. | Named as a red flag in PQ2; `tokenContrast.test.ts:434` already says it. |
| **Moving a frozen value** | Light: `--surface-control-hover` and `--brand-tint` are 0.0018 apart and re-rank four annotations together. Dark: `--surface` sets `--ink-rule`'s ceiling at 2.939 vs 3.0 — 0.061 of headroom — so it may not darken, and no dark tint may lighten. | §2.4's floor **and ceiling** table; both constraints in the deviation log. |
| **Copying PlanIQ's dark values** | Its `#313131`/`#474747` fail **40** assertions; its own dark mode ships `#666D80` on `#1B1B1B` (~3.4:1, five screens) and a `#75FC96B2` pill at ~2.5:1. | PQ2's deviation-log entry states the measurement so it is not re-litigated. |
| **`#75FC96` creeping into a foreground** | It is the kit's link colour, its delta value, its greeting tail and its 44px OTP digits — all ~1.2–1.4:1. | It exists only as `--brand-solid`, whose sole `ROLES` ground is `--ink-on-brand`. Any other use fails the completeness gate. |
| **An unmeasured pair on the new green** | `NavRail:122` paints the active icon `text-brand-fill` — magenta on mint, 3.80:1, and `--brand-fill`'s grounds are the five surfaces, so the gate never looks. The focus ring is worse: today `--focus-ring` on `--brand-solid` is **1.00:1** and the suite is green. | PQ5 deletes the icon override; PQ2 adds `--brand-solid` to `--focus-ring`'s grounds (3.80 light / 3.14 dark, both by assertion); `isLoading`'s spinner is `currentColor`. |
| **The `EnvBadge` prod pair** | `bg-error text-surface-card` is unmeasured today (5.72 light / 5.68 dark) and PQ2 perturbs the dark half blind by moving `--surface-card` (it happens to improve to 6.48). | PQ2's `--ink-on-error` role; PQ5 rewrites the call site. |
| **Losing a non-colour channel** | PlanIQ encodes nav selection by fill alone, status by hue alone at an 8px caption, and role in chat by side alone. | `StatTile` prints the band word, `StatusPill` glyph + word, `ErrorCodeBadge` tri-state, charts dash + marker. Note `--st-delivered` and `--st-failed` are **1.00:1 in luminance** in light (156 apart in sRGB) — hue is not a channel there at all. |
| **`--ink-mark` / `--ink-rule` waivers** | Match on the **exact trimmed source line**; a rewrite invalidates one and a dead waiver fails the suite. `RULE_WAIVERS` is empty on purpose. | PQ7 decides the absence-hatch token *before* the pattern is authored. |
| **Renaming a testid or a landmark** | Converts a 2% break into a suite-wide one, presenting as ~300 unrelated screen failures. And PQ4/PQ8 are precisely the workstreams that move testids between files. | PQ0's **global** contract snapshot, landed first; a pure move leaves it byte-identical, and any real change needs a named line in the commit message. |
| **`codepointIntegrity.test.tsx:185-209`** | Walks every ancestor of a rendered name for `uppercase`/`type-caption`. A caption treatment on `Card` or `Section` fails with a message about codepoints. | Named in PQ4's risk; asserted directly in `Card.test.tsx`. |
| **Silent no-ops** | `tailwind.config.ts:19` claims removed names "FAIL TO BUILD"; false. `bg-bg-0`, `border-line`, `backdrop-blur-xs` emit nothing. | PQ0 fixes the three live instances; the new ESLint rule catches default-palette leaks. |
| **No visual regression net** | A restyle can keep every class assertion green and still look wrong. | PQ1's computed-colour gate **and** the gallery baselines, both in CI **before** PQ3 moves a pixel; before/after PNGs per tranche. |
| **Type-scale drift** | Duplicated in `index.css`, `tailwind.config.ts` and `lib/utils.ts`; a rung in one and not the others makes `twMerge` silently delete the utility. | A test guards the existing list; PQ10 edits all three together. |
| **CI chain that has never run** | PQ1 adds three scripts to a `lint → typecheck → vitest → tokens:check → build → playwright` chain that does not exist end-to-end today. | PQ9 writes the chain down and names an owner; the 4 `hbd_test` grant failures stay outside it and are documented as known-red. |
| **WS3 never lands** | PQ7 presents cost and latency trends whose writers do not exist (`GenerationAttemptRepository.record()` has no call site). | PQ7 ships the *absence* rule, not the number: `isCostPriced === false` → no trend, `AbsentValue kind="nothing-priced"`. Listed as an external blocker on PQ7's Depends-on line. |

**The contract under N palettes — the risk the axis adds, and the one it removes.**

*Adds:* the gate's surface grows with the registry, and so does the pixel gallery. Every assertion,
every annotation and every baseline is now per-cell. At two palettes that is ~488 assertions, ~121
annotations and 2× the images; the assertions cost seconds and the annotations cost nothing once
generated, but **the images cost a person's attention on every regeneration**, and attention does not
scale linearly. This is the concrete reason the registry should stay at two until a third has a stated
purpose (a high-contrast palette would be the first good one).

*Removes:* the single largest risk in the original plan — that the palette change was irreversible and
therefore had to be argued to a conclusion before it could be seen. **A palette cannot enter the
registry without clearing all 244 assertions in both its themes**, so "swappable colours", which is
usually the hole through which unmeasured colour ships, is here the mechanism that guarantees the
opposite. There is no user-supplied hex anywhere in this design, and there must not be: the moment a
colour can be chosen at runtime that was not measured at build time, every number in this document
becomes a claim about one configuration among many. That is the line, and §2.0 sits deliberately on the
safe side of it.

**The failure mode to watch** is not arithmetic, it is *drift between blocks*: a token tuned in
`planiq` and forgotten in `gogo`, or a semantic alias quietly overridden to make one palette work.
Key-set parity and the no-alias rule (§2.0.5) exist for exactly this and are the two assertions to
strengthen first if anything goes wrong.

**The one accessibility improvement worth stating plainly, and its cost stated beside it:**
`--ink-on-brand` on `--brand-solid` goes from **4.95:1 to 16.12:1** — the console's most-clicked
element gets 3.3× more contrast for its label. In the same move that button's *ground* contrast falls
from 4.75/4.95 to 1.21/1.30, and `--brand-solid-edge` at 3.78–4.30:1 is what pays for it. Both halves
ship together or neither does.

---

## 7. Open questions

1. **ANSWERED — PlanIQ, outright.** Decided 2026-09-07; the switch that would have let this be decided
   from use was removed with it. Recorded here because the shape of the result still needs knowing:
   `--brand`/`--brand-fill`/`--brand-tint` stay **magenta** and only `--brand-solid` went green,
   because PlanIQ's own darkest green (`#218C3B`) is 3.51:1 on the hover ground — under the text bar —
   and 38.8 rgbDistance from `--success` against the magenta's 174. So the console is a green *action*
   hue with a magenta *identity/link* hue: a green primary button, a magenta link. That is what PlanIQ
   itself does, but it is two hues, and it is the first thing to look at if the result reads oddly.

2. **If not — do links stay magenta?** `--focus-ring: var(--brand-fill)`, `--st-held: var(--brand)`,
   `OrderRefChip` and every `text-brand` follow the brand. Keeping them magenta is zero-risk and
   zero-churn. The alternative (retire the `text-brand` idiom, links become `--ink` + underline,
   `--st-held` repoints to `--warning`) is more PlanIQ-faithful and removes the two-hue objection, but
   it is a components change and `--st-held` turning green-adjacent next to `--st-delivered` is a real
   operational misread.

3. **Does `.type-caption` stay uppercase?** It is 11/600/+0.06em/uppercase and is the console's only
   sanctioned `text-transform`, banned under `components/domain/**` by `eslint.config.js:231-233`.
   PlanIQ has **no uppercase product role at all** and its captions are sentence-case with *negative*
   tracking — the exact inverse. The kit cannot arbitrate this; it is a product call, and it touches
   every `StatTile` label, `Fact` and chip in PQ4–PQ5.

4. **Is narrow-viewport support in scope?** `playwright.config.ts` pins 1512×900 and nothing states a
   minimum width. The horizontal-nav fallback in PQ6 is the only piece that adds a navigation landmark;
   if operators are all on ≥1280px it should be dropped rather than sequenced.

5. **Is PQ10 (Manrope) in scope, and on what timeline?** ~1000 lines of e2e rewrite, coupled to nothing
   else, and its real cost is designing a replacement negative control now that Urbanist's
   missing-Cyrillic hole would stop being load-bearing. It can ship a month after the palette.

6. **Should the peek surfaces converge?** The first draft's framing was stale.
   `UserPeekDrawer.tsx:68,147` **already imports and renders `<Drawer>`**, and `LyricSheetPanel` is an
   inline panel embedded in `OrderDetailScreen` and `AssetsScreen`, not a peek surface at all. So the
   real question is narrower: there are **two conversions** (`OrderPeekDrawer` in PQ0,
   `AttemptDetailPanel` in PQ8e) against **one existing consumer** (`UserPeekDrawer`) — is a shared
   `PeekDrawer` taking a `Fact` list worth it across those three? Their payloads differ enough that
   forcing it may be worse than three thin call sites on the same `Drawer`.

7. **Is a `/dashboard` route coming?** `docs/research/DASHBOARD_METRICS_RESEARCH.md` proposes 51 cards across 7
   sections and `docs/mockups/dashboard-mockup-full.html` is 5 273 lines, but no route exists and the doc says
   it is explicitly *not* the Live screen. If it is landing, it is the best possible target for
   PlanIQ's dashboard archetype and PQ4/PQ7 are its prerequisites — it should lead the migration rather
   than follow it. Note also that `docs/mockups/dashboard-mockup.html` already hit this plan's central wall
   independently: it defines `--accent-deep: #218C3B` for its LIVE chip, which measures **3.86:1** on
   its own tint — under the text bar. (The same hex is fine as this plan's 1px button ring, which is a
   3:1 graphic, and is exactly why the two uses must not be conflated.) **Treat the mockup as a
   trustworthy layout and rhythm reference and an untrustworthy colour source.**

8. **Who owns the CI chain?** PQ1 introduces `tokens:check`, `e2e:appearance` and `e2e:gallery` into a
   `lint → typecheck → vitest → tokens:check → build → playwright` sequence that has never been run
   end-to-end in this repo. Confirm whether that chain is being created here or already exists
   elsewhere, and who is on the hook when the gallery baselines need regenerating.
