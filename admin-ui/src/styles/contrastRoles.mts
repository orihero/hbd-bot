/**
 * The ROLES table: what every colour token in `tokens.css` is FOR, the WCAG bar it has to
 * clear, and the complete set of grounds it may legally sit on.
 *
 * Extracted from `tokenContrast.test.ts` so that the gate and `tools/annotate-tokens.mts`
 * read one table rather than two. The generator needs it for a reason that is not
 * convenience: an annotation names the token's WORST ground (or, for an `exempt` token, its
 * BEST), so "which ground does this comment name" is a question only `ROLES` can answer. A
 * generator carrying its own copy would write annotations against a ground set the gate does
 * not police — and the risk table already names exactly this duplication class (`FAMILIES`
 * living in both `tokenContrast.test.ts` and `tailwind.config.ts`) as a silent-drift source.
 *
 * What did NOT move, deliberately: the `describe`s, the waivers, the source scan and every
 * assertion. This file states the contract; the test is the only thing that enforces it, and
 * a tool that imports the contract still cannot loosen it.
 *
 * Bars, per WCAG 2.1: 4.5:1 for text (1.4.3); 3:1 for large text and for a graphical object
 * that carries meaning (1.4.11); no bar at all for a rule, a decoration or an inactive
 * control, which 1.4.3 and 1.4.11 both put outside the requirement.
 */

import { type Palette, ratioOn } from "./contrastMath.mts";

/** Every ground a surface-agnostic component can be dropped onto. */
export const SURFACES = [
  "--surface",
  "--surface-card",
  "--surface-sunken",
  "--surface-control",
  "--surface-control-hover",
] as const;

/** The nine semantic hue families, each with a `--x` / `--x-fill` / `--x-tint` trio. */
export const FAMILIES = [
  "brand",
  "accent",
  "success",
  "caution",
  "warning",
  "error",
  "info",
  "neutral",
  "slate",
] as const;

export const ORDER_STATES = [
  "draft",
  "brief-ready",
  "lyrics-ready",
  "authorized",
  "generating",
  "delivered",
  "failed",
  "cancelled",
  "held",
] as const;

export const PIPELINE_STATUSES = [
  "started",
  "retrying",
  "succeeded",
  "degraded",
  "failed",
  "skipped",
] as const;

/**
 * `text` → 4.5:1 (1.4.3). `large-text` → 3:1 (1.4.3, ≥24px or ≥18.66px bold). `graphic` →
 * 3:1 (1.4.11). `exempt` → no floor: 1.4.3 exempts an inactive control and 1.4.11 exempts
 * decoration, so what an exempt role asserts is a CEILING and, at a site, its EVIDENCE.
 */
export type Bar = "text" | "large-text" | "graphic" | "exempt";

export const THRESHOLD = {
  text: 4.5,
  "large-text": 3,
  graphic: 3,
  exempt: 0,
} as const satisfies Record<Bar, number>;

/* ------------------------------------------------------------------------------------- *
 * The ROLES table: every colour token, the bar it must clear, and every ground it may
 * legally sit on.
 * ------------------------------------------------------------------------------------- */

export interface Role {
  /** The floor this token must clear on every one of its grounds, in every cell. */
  readonly bar: Bar;
  /** Every ground expression this token may be painted on. */
  readonly grounds: readonly string[];
  /**
   * An upper bound, asserted per palette. Only for `exempt` tokens: a token documented as
   * "never text" that quietly became readable would invite exactly the misuse the role
   * exists to prevent.
   */
  readonly ceiling?: number;
  /** What this token is for, in one line — quoted in failure messages. */
  readonly what: string;
}

/*
 * A tint over EVERY surface it can actually be dropped onto — all five, not the two this
 * list used to carry.
 *
 * The two-ground version was a real measurement hole, and three separate reskin passes
 * walked into it independently. A `-tint` is translucent, so the ratio a chip really
 * achieves depends on what is behind it, and a tinted chip is not confined to the page and
 * the card: `DataTable` hovers a row to `--surface-control-hover`, `AttentionList` hovers
 * to `--surface-control`, and `CodeBlock`/`JsonViewer`/`CommandPalette` are `--surface-
 * sunken` wells. Every one of those grounds is darker than the card in the light palette,
 * so every one of them LOWERS the ratio of a hue painted on its own tint — and none of the
 * three was measured. The suite stayed green while `--error` on `--error-tint` on a hovered
 * table row sat at 3.90:1, below the 4.5:1 text bar, in shipped components.
 *
 * Widening this list is what lets the suite see that class of failure at all. It is
 * deliberately the FULL surface set rather than a curated one: a curated list is how the
 * hole got here, and "which surfaces may a chip land on" is not a question a token author
 * can answer for every component that will ever exist.
 */
export const tintGrounds = (family: string): readonly string[] =>
  SURFACES.map((surface) => `--${family}-tint over ${surface}`);

/** Every tint of every family — the full ground set for the ink tokens. */
export const ALL_TINT_GROUNDS: readonly string[] = FAMILIES.flatMap((family) => tintGrounds(family));

/** A `--x` / `--x-fill` / `--x-tint` trio, wherever it appears (families, states, statuses). */
export function trio(token: string, what: string): Record<string, Role> {
  return {
    [`--${token}`]: {
      bar: "text",
      grounds: [...SURFACES, ...tintGrounds(token)],
      what: `${what} — text-safe member: a word may be painted with it`,
    },
    [`--${token}-fill`]: {
      bar: "graphic",
      grounds: SURFACES,
      what: `${what} — graphic member: dots, strokes, bars, never a character`,
    },
  };
}

/**
 * Every `--x` / `--x-fill` pair in the palette, flattened into one table: the nine hue
 * families, the nine order states, the six pipeline statuses and the two error classes.
 *
 * `Object.fromEntries` over flattened entries rather than `Object.assign({}, ...groups)`,
 * which is the same merge but types as `any` — and `any` in the middle of the ROLES table is
 * a hole in exactly the structure the whole contract is checked against.
 */
const TRIOS: Readonly<Record<string, Role>> = Object.fromEntries(
  [
    ...FAMILIES.map((family) => trio(family, `the ${family} family`)),
    ...ORDER_STATES.map((state) => trio(`st-${state}`, `order state ${state}`)),
    ...PIPELINE_STATUSES.map((status) => trio(`pg-${status}`, `pipeline status ${status}`)),
    trio("retryable", "the ↻ retryable error class"),
    trio("terminal", "the ■ terminal error class"),
  ].flatMap((group) => Object.entries(group)),
);

export const ROLES: Readonly<Record<string, Role>> = {
  "--ink": {
    bar: "text",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "all prose and headings, and the word inside every tinted chip",
  },
  "--ink-muted": {
    bar: "text",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "the one muted TEXT colour — descriptions, axis ticks, breadcrumbs",
  },
  "--ink-mark": {
    bar: "graphic",
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "marks and glyphs only — POLICED, never a character",
  },
  "--ink-rule": {
    bar: "exempt",
    ceiling: 3,
    grounds: [...SURFACES, ...ALL_TINT_GROUNDS],
    what: "rules and inactive controls only — POLICED, clears no bar anywhere",
  },
  "--ink-on-brand": {
    bar: "text",
    grounds: ["--brand-solid"],
    what: "the label on a primary button",
  },
  "--brand-solid": {
    bar: "text",
    grounds: ["--ink-on-brand"],
    what: "the primary-button fill, measured against its own label",
  },
  /*
   * The 1px ring that gives the primary button an outline of its own.
   *
   * It exists because `--brand-solid` stopped being a colour that has a shape. The magenta
   * this palette replaced was 4.75/4.95:1 against the page and the card, so the button's own
   * edge WAS the boundary; PlanIQ Primary/700 measures 1.21:1 on the page and 1.30:1 on the
   * card, which is a button with no outline at all. The ring is what replaces that boundary,
   * so it carries meaning and 1.4.11's 3:1 applies to it.
   *
   * THREE grounds, not the usual five, and the two it leaves out are named here so nobody
   * re-derives the flattering half (the `--edge` precedent). A primary button and a dialog's
   * confirm float over the page, over a card, or over a sunken well; the control grounds are
   * where an input sits, and nothing paints this ring there. Declaring all five would put
   * dark's 3.04:1 on `--surface-control-hover` at 0.04 headroom — the tightest floor in the
   * whole palette — and freeze that surface permanently for a ring that is never painted on
   * it. Measured on all five, recorded so the omission is a decision and not an oversight:
   *
   *   cell     surface  card  sunken  control  control-hover
   *   light       3.98  4.30    3.78     3.64           3.51
   *   dark        4.39  4.00    4.27     3.50           3.04
   *
   * The consequence to state out loud, because a reader of the ANNOTATION will otherwise
   * infer the wrong thing: an annotation names the worst of the grounds the ROLE declares,
   * not the worst of the five above. So `dark` is written as 4.00:1 on `--surface-card` while
   * this token measures 3.04:1 on `--surface-control-hover` — a surface it is never painted
   * on, and the reason that number is here rather than in the comment. All ten values clear
   * 3:1, so nothing is hidden by the curation; what is curated is which three
   * this palette is FROZEN against. Re-open the decision by declaring all five, which costs
   * nothing today and pins `planiq/dark`'s `--surface-control-hover` at 0.04 headroom
   * forever.
   *
   * `planiq`'s value is a green, and it sits 26.7 rgbDistance from `--c-8` — the green
   * categorical slot — and 41.9 from `--success-fill`. That is fine for a 1px ring on a green
   * button and it is exactly why the `what` string forbids it anywhere else: a 26.7-apart
   * green used as a chart series or a state fill would be a second green that means something
   * different, which is the one thing this palette's vocabulary may not do.
   */
  "--brand-solid-edge": {
    bar: "graphic",
    grounds: ["--surface", "--surface-card", "--surface-sunken"],
    what: "the 1px ring that gives --brand-solid a shape; never a chart series or a state fill",
  },
  /*
   * The label on a SOLID error ground — `EnvBadge`'s prod pill and the `danger-solid` button.
   *
   * Added by PQ2a because the pair was unmeasured: `EnvBadge` paints `text-surface-card` on
   * `--error` today, which names a SURFACE token as a foreground and therefore fell through
   * every ground set in this table. It is an alias (`var(--surface-card)`), so it is declared
   * once in `:root` and resolves per cell through the `var()` chase — it is not one of the
   * palette's own literal colours and no palette block declares it.
   *
   * The measurement is what makes the addition worth having, in `gogo` as much as in `planiq`:
   * 5.72:1 light and 5.68:1 dark in `gogo`, 5.72:1 and 6.48:1 in `planiq`. The dark figure is
   * the one PQ2 perturbs blind — moving `--surface-card` moves this pair — and until now
   * nothing would have noticed.
   */
  "--ink-on-error": {
    bar: "text",
    grounds: ["--error"],
    what: "the label on a solid error ground — the prod EnvBadge, the danger-solid button",
  },
  "--edge": {
    bar: "graphic",
    grounds: ["--surface", "--surface-card"],
    what: "the one border that carries meaning: a floating popover's boundary ring",
  },
  /*
   * The `:focus-visible` outline. `index.css` paints it as `outline: 2px solid
   * var(--focus-ring); outline-offset: 2px`, and the OFFSET is what decides this role's ground
   * set: an outline drawn 2px outside the border box sits on whatever is BEHIND the focused
   * element, not on the element's own fill. So the grounds are the five surfaces, and they are
   * the honest ones.
   *
   * PQ2a's plan proposes a sixth, `--brand-solid`, on the premise that the ring is painted on
   * the primary button. That edit is DEFERRED, and both halves of the reason are measurements
   * rather than opinions:
   *
   *   1. The premise is false on this tree. `outline-offset: 2px` means the ring's ground is
   *      the page or the card, which SURFACES already covers, and the 2px gap in the page
   *      colour is what makes the indicator visible on a magenta button at all.
   *   2. Adding it would put two hard failures into `gogo` that no value change inside a
   *      palette can repair. `--focus-ring` is `var(--brand-fill)`, an INVARIANT alias, so it
   *      is one value for every palette; measured on `--brand-solid` it is 1.000:1 in
   *      gogo/light (the ring is the fill's own hex) and 1.210:1 in gogo/dark, against a 3:1
   *      bar. `planiq` clears it comfortably — 3.80:1 light, 3.14:1 dark — but `gogo`'s
   *      `--brand-solid` may not move, and re-pointing `--focus-ring` off `--brand-fill` is a
   *      visible change to a palette this tranche promised not to touch.
   *
   * What is left is a real question about ADJACENCY — whether a 2px gap is enough separation
   * from a fill the ring nearly matches — and that is a design decision about `gogo`, not a
   * token decision. It belongs to whoever owns that change. Narrowing anything here to make it
   * go away would be the move this file's own failure message forbids.
   */
  "--focus-ring": {
    bar: "graphic",
    grounds: SURFACES,
    what: "the :focus-visible outline, offset 2px, so its ground is the surface behind",
  },
  "--hairline": {
    bar: "exempt",
    ceiling: 3,
    grounds: SURFACES,
    what: "a decorative rule between dense rows — never the boundary of a control",
  },
  "--hairline-strong": {
    bar: "exempt",
    ceiling: 3,
    grounds: SURFACES,
    what: "a firmer decorative rule — still never the only thing identifying a control",
  },
  ...TRIOS,
  ...Object.fromEntries(
    [1, 2, 3, 4, 5, 6, 7, 8].map((slot) => [
      `--c-${String(slot)}`,
      {
        bar: "graphic",
        grounds: SURFACES,
        what: `categorical chart series ${String(slot)} — graphic only, never text`,
      } satisfies Role,
    ]),
  ),
};

/**
 * What KIND of ground an entry is — the classification PQ1 asks for, keyed on the token's
 * role rather than on its name.
 *
 * The prefix form this replaces (`^--surface`) was proposed and rejected in the plan for a
 * concrete reason: it would not have covered `--scrim`, the token PQ3 adds, and `--scrim` is
 * exactly the shape of the evasion — a token that resolves to a colour, satisfies the
 * completeness gate by appearing in `GROUNDS` with a sentence beside it, and is then never a
 * measurement ground for anything, forever, green. "A sixth surface" is the same failure
 * wearing a different name: `--surface-nav` and `--skeleton-base` are grounds today ONLY
 * because they are byte-identical to a surface that is measured, and nothing but this
 * classification would notice one of them drifting a shade away and becoming a ground in its
 * own right that no ink is measured on.
 *
 * So each entry states which of six things it is, and each kind is then held to the property
 * that makes it safe to carry no bar of its own. The assertions are in
 * `tokenContrast.test.ts` — this file states the contract, the test is what enforces it.
 */
export type GroundKind =
  /** One of the five grounds a surface-agnostic component can be dropped onto. */
  | "surface"
  /** Names a surface for one component's sake; must BE one, colour for colour, in every cell. */
  | "surface-alias"
  /** A chip/pill ground; measured under the inks composited over all five surfaces. */
  | "chip-tint"
  /** A ramp stop that aliases a token with a ROLE, and is measured through it. */
  | "ramp-alias"
  /** A ramp stop with a colour of its own: a FILL, never behind a character. */
  | "ramp-stop"
  /** Carries nothing the words do not. The only kind 1.4.11 puts outside the requirement. */
  | "decoration";

export interface Ground {
  readonly kind: GroundKind;
  /**
   * The surfaces a TRANSLUCENT ground is composited over.
   *
   * Required of every ground that resolves to a colour with alpha < 1 in any cell, and
   * forbidden to every ground that does not. A translucent ground's real colour is not its
   * own hex — it is whatever is behind it — so a translucent entry with no stated backing is
   * an unmeasurable claim, and an opaque entry carrying the note is a note that reads as
   * evidence and is not.
   */
  readonly over?: readonly string[];
  /** Why this token carries no bar of its own, in one line. */
  readonly why: string;
}

/**
 * Colour tokens that are GROUNDS or ramp stops rather than foregrounds, each with its kind
 * and the reason it carries no bar of its own. Everything in `tokens.css` that resolves to a
 * colour must be in here or in `ROLES`; the completeness test is what makes that true.
 */
export const GROUNDS: Readonly<Record<string, Ground>> = {
  "--surface": {
    kind: "surface",
    why: "the page ground; measured as the BACKGROUND of every text token",
  },
  "--surface-card": { kind: "surface", why: "every card, panel, rail and dialog" },
  "--surface-sunken": {
    kind: "surface",
    why: "an inset well: code blocks, JSON viewers, the palette list",
  },
  "--surface-control": {
    kind: "surface",
    why: "the ground a control carries instead of a border",
  },
  "--surface-control-hover": { kind: "surface", why: "hover for a control and for a table row" },
  "--surface-nav": { kind: "surface-alias", why: "alias of --surface-card, so the rail names itself" },
  "--surface-topbar": {
    kind: "surface-alias",
    why: "alias of --surface-card, so the top bar names itself",
  },
  ...Object.fromEntries(
    [
      ...FAMILIES,
      ...ORDER_STATES.map((state) => `st-${state}`),
      ...PIPELINE_STATUSES.map((status) => `pg-${status}`),
      "retryable",
      "terminal",
    ].map((token) => [
      `--${token}-tint`,
      {
        kind: "chip-tint",
        why: "a chip/pill ground; measured under --ink, --ink-muted and its own family's text member",
      } satisfies Ground,
    ]),
  ),
  "--seq-from": {
    kind: "ramp-stop",
    why: "sequential ramp stop — a FILL, always beside a legend or a value label",
  },
  "--seq-to": {
    kind: "ramp-stop",
    why: "sequential ramp stop — a FILL, always beside a legend or a value label",
  },
  "--div-low": { kind: "ramp-alias", why: "diverging ramp stop; aliases --error-fill" },
  "--div-mid": { kind: "ramp-alias", why: "diverging ramp stop; aliases --neutral-fill" },
  "--div-high": { kind: "ramp-alias", why: "diverging ramp stop; aliases --success-fill" },
  "--skeleton-base": { kind: "surface-alias", why: "the shimmer's base stop; aliases --surface-control" },
  "--skeleton-sheen": {
    kind: "decoration",
    over: ["--surface-control"],
    why: "the shimmer's moving highlight, riding over --skeleton-base — decoration, carries nothing",
  },
};

/* ------------------------------------------------------------------------------------- *
 * Which ground an annotation is allowed to name.
 * ------------------------------------------------------------------------------------- */

/**
 * Every ground of a role, measured in one cell, ordered from worst to best.
 *
 * The sort is stable (ES2019 requires it), so grounds that tie keep the order `role.grounds`
 * lists them in. That matters more than it looks: after PQ2 the light palette's darkest
 * ground is a five-way exact tie — the tints are opaque, so `--brand-tint over <any surface>`
 * composites to a byte-identical colour — and which of the five "wins" is nothing but this
 * stability plus the order of `SURFACES` and `FAMILIES`.
 */
export function rankedGrounds(
  palette: Palette,
  token: string,
  role: Role,
): readonly (readonly [string, number])[] {
  return role.grounds
    .map((expression) => [expression, ratioOn(palette, token, expression)] as const)
    .sort((a, b) => a[1] - b[1]);
}

/**
 * The one ground an annotation may name: the token's WORST, or — for a token whose whole
 * claim is a ceiling — its BEST.
 *
 * This is the rule `tokens.css`'s grammar encodes as `on` versus `at best on`, and it exists
 * so that a comment cannot pick a flattering surface. `--fg-2`'s "4.6:1 — floor for real
 * text" was true of no surface at all; the failure this closes is the subtler version, the
 * one that is true of exactly one.
 */
export function extremeGround(palette: Palette, token: string, role: Role, best: boolean): string {
  const ranked = rankedGrounds(palette, token, role);
  const extreme = best ? ranked[ranked.length - 1] : ranked[0];
  if (extreme === undefined) throw new Error(`${token}'s role names no grounds at all`);
  return extreme[0];
}

/**
 * Two grounds are the SAME ground for annotation purposes when their ratios differ by less
 * than this. Nothing about a hex is approximate — the tie this exists for is exact, an opaque
 * tint composited over five different surfaces to five identical colours — but the ratios are
 * floats arrived at through `**2.4`, and asserting exact equality on those is a promise about
 * an FPU rather than about a palette.
 */
export const RATIO_EPSILON = 1e-9;

/**
 * Every ground within `RATIO_EPSILON` of the extreme — the set an annotation may legitimately
 * name, rather than the single member a stable sort happens to put first.
 *
 * A generator that always rewrote to `extremeGround()` would churn a perfectly true comment
 * into a different perfectly true comment whenever `SURFACES` or `FAMILIES` was reordered,
 * and a gate that only accepts `extremeGround()` reports that churn as "names X but its worst
 * ground is Y" — which reads as a test bug and gets the assertion relaxed. The tie set is the
 * honest form of the question.
 */
export function tiedExtremeGrounds(
  palette: Palette,
  token: string,
  role: Role,
  best: boolean,
): readonly string[] {
  const ranked = rankedGrounds(palette, token, role);
  const extreme = best ? ranked[ranked.length - 1] : ranked[0];
  if (extreme === undefined) throw new Error(`${token}'s role names no grounds at all`);
  return ranked
    .filter(([, ratio]) => Math.abs(ratio - extreme[1]) < RATIO_EPSILON)
    .map(([expression]) => expression);
}
