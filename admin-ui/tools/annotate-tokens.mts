/**
 * The annotation generator: it MEASURES `tokens.css` and writes the measurement back into the
 * comment beside each colour, and it never writes anything else.
 *
 *     npx tsx tools/annotate-tokens.mts --check    recompute every annotation, report drift
 *     npx tsx tools/annotate-tokens.mts --write    rewrite the measured spans in place
 *
 * ## Why this exists at all
 *
 * `tokens.css` states, beside every literal colour, the ratio that colour achieves and the
 * ground it was measured on:
 *
 *     --ink-muted: #636363; /· 4.87:1 on --surface-control-hover — every muted label ·/
 *
 * Those claims are load-bearing. `src/styles/tokenContrast.test.ts` recomputes all 144 of them
 * on every run and fails on any disagreement, because this codebase has shipped a wrong one
 * twice — `--fg-2` annotated "4.6:1 — floor for real text" while measuring 4.34:1, which is
 * what licensed 131 sub-AA prose sites. The failure mode is never a comment that looks wrong;
 * it is a STALE comment beside a token that still passes its bar.
 *
 * Hand-maintaining them by hand was already the tail wagging the colour work — 70 before the
 * two-palette axis, and 72 across the two blocks the console kept (36 per block; the
 * plan's §2.3 estimate of ~121 predates both `--brand-solid-edge` and the two declarations
 * key-set parity added to the dark block: 35 light + 33 dark became 36 in every cell).
 * Every one of them moves when any surface moves: nudging light `--surface-control-hover` from `#e7e7ec` to `#e8e8e8` shifts EVERY fill
 * and chart ratio measured against it. That is not work a person should be asked to redo by
 * hand, and the moment they stop is the moment the comments start lying. So the generator is
 * a precondition of moving the palette at all, not a convenience beside it.
 *
 * ## What it writes, and what it will not touch
 *
 * It rewrites exactly the span `N.NN:1 [at best ]on <ground>` and nothing else. The role prose
 * after the em dash is a human's sentence about what the token is FOR, and no measurement can
 * author it — so a declaration with no annotation is REPORTED and left alone rather than given
 * a machine-written comment with an empty tail. It measures; it does not describe.
 *
 * Nor does it decide the two things that make a measurement mean something. The BAR each token
 * has to clear and the GROUNDS it may legally sit on are hand-declared in
 * `src/styles/contrastRoles.mts`, and the gate still fails independently when a value misses
 * its bar. Generating the number strictly dominates typing it: the friction of a human noticing
 * a ratio "looks wrong" never caught either of the two incidents this file exists because of —
 * the recomputation did — and a generated number cannot be stale and cannot name a flattering
 * ground.
 *
 * ## It loops over the blocks it finds, rather than over a light/dark pair
 *
 * Every block is measured in its OWN cell and its annotations rewritten from its OWN hexes,
 * through the same `paletteBlocks.mts` the gate parses with. The console briefly shipped two
 * palettes on a `data-palette` axis and this file needed no change to cover the extra two
 * cells; it needed none to go back, either. That sharing is the point rather than the tidiness:
 * a generator with its own parser could measure a ratio in one cell and write the comment into
 * another — `[data-theme="dark"] {` is a substring of `[data-palette="planiq"][data-theme="dark"] {`,
 * and an unanchored `indexOf` hands back the same block for both — and the result would be a
 * stylesheet full of confidently generated, precisely wrong numbers.
 *
 * ## Exit codes
 *
 *   0  every annotation agrees with its cell (or `--write` made them agree)
 *   1  drift `--check` found, or a finding `--write` cannot fix on its own
 *   2  the invocation was wrong
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ratioOn } from "../src/styles/contrastMath.mts";
import {
  extremeGround,
  type Role,
  ROLES,
  tiedExtremeGrounds,
} from "../src/styles/contrastRoles.mts";
import {
  ANNOTATION,
  blockRange,
  type Cell,
  readStylesheet,
} from "../src/styles/paletteBlocks.mts";

/**
 * `on` or `at best on`, decided by the ROLE and never by what the file already says.
 *
 * An `exempt` token — `--ink-rule`, `--hairline`, `--hairline-strong` — clears no bar
 * anywhere, so the only claim worth writing about it is its CEILING: the best it ever gets.
 * Everything else has a floor to clear, so the claim is its worst case. Deriving the form
 * rather than preserving it means the grammar cannot drift away from the bar: a token that
 * stopped being exempt would have its comment re-pointed at the worst ground in the same pass
 * that re-measures it.
 */
function claimsBest(role: Role): boolean {
  return role.bar === "exempt";
}

export type FindingKind = "ratio" | "ground" | "form" | "unroled" | "unannotated";

export interface Finding {
  /** `gogo/dark` — which cell the annotation was measured in. */
  readonly cell: string;
  readonly token: string;
  readonly kind: FindingKind;
  /** True when `--write` repairs it; false when only a human can. */
  readonly fixable: boolean;
  /** One line, naming the drift and its repair. */
  readonly message: string;
}

export interface CellReport {
  readonly label: string;
  readonly selector: string;
  /** Annotations recomputed in this block. */
  readonly verified: number;
}

export interface Report {
  /** The stylesheet with every measured span rewritten. Byte-identical when nothing drifted. */
  readonly text: string;
  readonly changed: boolean;
  /** Total annotations recomputed, across every block. */
  readonly verified: number;
  readonly cells: readonly CellReport[];
  readonly findings: readonly Finding[];
}

/**
 * Recompute every annotation in one block and return that block's text with the measured
 * spans rewritten.
 *
 * `String.replace` over `ANNOTATION` is what keeps the prose safe: the regex match ENDS at the
 * em dash, so everything the callback returns replaces only the declaration-plus-measurement
 * head, and the sentence after the dash is never inside the span being rebuilt. A line with no
 * annotation matches nothing and is copied through untouched.
 */
function rewriteBlock(cell: Cell, body: string, findings: Finding[]): { body: string; count: number } {
  let count = 0;
  const rewritten = body.replace(
    ANNOTATION,
    (match, token: string, _hex: string, claimed: string, best: string | undefined, named: string) => {
      const role = ROLES[token];
      if (role === undefined) {
        // Annotated but unroled: there is no ground set to find an extreme in, so there is
        // nothing to measure and nothing this tool may invent. The gate fails on it too
        // ("%s is annotated but has no role"), and the repair is a ROLES entry, which is a
        // decision about what the token is FOR.
        findings.push({
          cell: cell.label,
          token,
          kind: "unroled",
          fixable: false,
          message:
            `${token} carries an annotation but no entry in ROLES, so no ground set exists ` +
            `to measure it against. Add it to src/styles/contrastRoles.mts with the bar it ` +
            `has to clear.`,
        });
        return match;
      }

      count += 1;
      const wantsBest = claimsBest(role);
      // A named ground that is already tied for the extreme is KEPT. Rewriting it to whichever
      // tied ground a stable sort happens to put first would churn a true comment into a
      // different true comment every time `SURFACES` or `FAMILIES` is reordered — and after
      // PQ2 the light palette's darkest ground is a five-way exact tie, because the tints are
      // opaque and composite identically over all five surfaces.
      const tied = tiedExtremeGrounds(cell.tokens, token, role, wantsBest);
      const ground = tied.includes(named)
        ? named
        : extremeGround(cell.tokens, token, role, wantsBest);
      const ratio = ratioOn(cell.tokens, token, ground).toFixed(2);

      const tail = `${claimed}:1 ${best ?? ""}on ${named} —`;
      const newTail = `${ratio}:1 ${wantsBest ? "at best " : ""}on ${ground} —`;
      if (!match.endsWith(tail)) {
        // Unreachable while `tail` is rebuilt from this match's own capture groups. Stated
        // anyway: silently returning `match` here would make the tool report "no drift" on a
        // file it had failed to parse.
        throw new Error(`could not locate the measured span in: ${match}`);
      }

      // The two drift kinds are reported as ONE finding each, never both, because a comment
      // that names the wrong ground has no meaningful "claimed ratio" to disagree with: its
      // number may be perfectly true of the flattering surface it picked. Reporting "claims
      // 3.22:1 but measures 3.08:1" against a token that really is 3.22:1 on the ground it
      // named would be the tool telling a small lie of its own.
      if (ground !== named) {
        findings.push({
          cell: cell.label,
          token,
          kind: "ground",
          fixable: true,
          message:
            `${token} names ${named} at ${ratioOn(cell.tokens, token, named).toFixed(2)}:1, ` +
            `which is not its ${wantsBest ? "best" : "worst"} ground. That is ${ground}, at ` +
            `${ratio}:1.`,
        });
      } else if (ratio !== claimed) {
        findings.push({
          cell: cell.label,
          token,
          kind: "ratio",
          fixable: true,
          message: `${token} claims ${claimed}:1 on ${named} but measures ${ratio}:1.`,
        });
      }
      if ((best !== undefined) !== wantsBest) {
        findings.push({
          cell: cell.label,
          token,
          kind: "form",
          fixable: true,
          message:
            `${token} is written as "${best === undefined ? "on" : "at best on"}" but its ` +
            `role's bar is "${role.bar}", which claims a ` +
            `${wantsBest ? "ceiling (at best on)" : "floor (on)"}.`,
        });
      }

      return match.slice(0, match.length - tail.length) + newTail;
    },
  );
  return { body: rewritten, count };
}

/**
 * Every role token in one block that states a literal colour and carries no annotation.
 *
 * `{6,8}`, which the gate now matches: `ANNOTATION` itself accepts an 8-digit hex, so a
 * translucent role token is a colour the grammar can annotate. This tool asked for the wider
 * set first and `tokenContrast.test.ts` was widened to `{6,8}` to agree with it — on the
 * present tree both sets are the same 144 lines, `--skeleton-sheen` being the only 8-digit
 * value and a GROUND rather than a role, which is what made the widening safe on both sides.
 *
 * Reported, never written. The comment after the em dash says what the token is FOR, and a
 * generator that invented that sentence would be authoring the design rationale it is supposed
 * to be measuring against.
 */
function findUnannotated(cell: Cell, body: string, findings: Finding[]): void {
  const annotated = new Set(
    [...body.matchAll(ANNOTATION)].map(([, token]) => token).filter((t) => t !== undefined),
  );
  for (const match of body.matchAll(/(--[\w-]+):\s*#[\da-f]{6,8};/gu)) {
    const [, token] = match;
    if (token === undefined) continue;
    const role = ROLES[token];
    // Not a role token, or already annotated: a GROUND (`--brand-tint`) carries no claim of
    // its own, because it is measured under every ink that can be painted on it.
    if (role === undefined || annotated.has(token)) continue;
    const wantsBest = claimsBest(role);
    const ground = extremeGround(cell.tokens, token, role, wantsBest);
    const ratio = ratioOn(cell.tokens, token, ground).toFixed(2);
    findings.push({
      cell: cell.label,
      token,
      kind: "unannotated",
      fixable: false,
      message:
        `${token} states a literal colour with no annotation. Add ` +
        `\`/* ${ratio}:1 ${wantsBest ? "at best " : ""}on ${ground} — <what it is for> */\`; ` +
        `the prose after the dash is yours to write, not this tool's.`,
    });
  }
}

/**
 * Recompute every annotation in every cell.
 *
 * Pure: it takes the stylesheet text and returns the rewritten text plus what it found. The
 * blocks are spliced back from the last to the first so that every range stays valid against
 * the ORIGINAL text while the rewrite changes lengths.
 *
 * The cells come from the stylesheet itself, so a test can hand this a file with more blocks
 * than the console ships and watch the count grow. That is the only way to show that
 * "loops over the blocks it finds" is a fact about the code rather than a claim in a
 * comment.
 */
export function annotate(css: string): Report {
  const { cells } = readStylesheet(css);
  const findings: Finding[] = [];
  const reports: CellReport[] = [];

  const edits = cells.map((cell) => {
    const [start, end] = blockRange(css, cell.selector);
    const body = css.slice(start, end);
    const { body: rewritten, count } = rewriteBlock(cell, body, findings);
    findUnannotated(cell, body, findings);
    reports.push({ label: cell.label, selector: cell.selector, verified: count });
    return { start, end, body: rewritten };
  });

  let text = css;
  for (const edit of [...edits].sort((a, b) => b.start - a.start)) {
    text = text.slice(0, edit.start) + edit.body + text.slice(edit.end);
  }

  return {
    text,
    changed: text !== css,
    verified: reports.reduce((total, report) => total + report.verified, 0),
    cells: reports,
    findings,
  };
}

/* ------------------------------------------------------------------------------------- *
 * The command line.
 * ------------------------------------------------------------------------------------- */

const USAGE =
  "usage: npx tsx tools/annotate-tokens.mts --check | --write\n" +
  "  --check  recompute every annotation in tokens.css; exit 1 on any drift\n" +
  "  --write  rewrite the measured span of every annotation in place\n";

/** One line per block: which cell it is, which selector carries it, how much was recomputed. */
function describeReport(report: Report, path: string): string {
  const labelWidth = Math.max(...report.cells.map((cell) => cell.label.length));
  const selectorWidth = Math.max(...report.cells.map((cell) => cell.selector.length));
  return [
    `annotate-tokens: ${path}`,
    ...report.cells.map(
      (cell) =>
        `  ${cell.label.padEnd(labelWidth)}  ${cell.selector.padEnd(selectorWidth)}  ` +
        `${String(cell.verified).padStart(3)} annotations`,
    ),
  ].join("\n");
}

export function main(argv: readonly string[], cssPath: string): number {
  const mode = argv[0];
  if (argv.length !== 1 || (mode !== "--check" && mode !== "--write")) {
    process.stderr.write(USAGE);
    return 2;
  }

  const css = readFileSync(cssPath, "utf8");
  const report = annotate(css);
  process.stdout.write(`${describeReport(report, cssPath)}\n`);

  const blocks = `${String(report.cells.length)} block${report.cells.length === 1 ? "" : "s"}`;
  const unfixable = report.findings.filter((finding) => !finding.fixable);
  const fixable = report.findings.length - unfixable.length;

  if (mode === "--check") {
    if (report.findings.length === 0) {
      process.stdout.write(
        `verified ${String(report.verified)} annotations across ${blocks}; every ratio and ` +
          `every named ground agrees with the cell it is written in.\n`,
      );
      return 0;
    }
    for (const finding of report.findings) {
      process.stderr.write(`  ${finding.cell}: ${finding.message}\n`);
    }
    process.stderr.write(
      `${String(report.findings.length)} finding${report.findings.length === 1 ? "" : "s"} ` +
        `against ${String(report.verified)} annotations. ` +
        (fixable === 0
          ? `None of them is this tool's to fix — each needs a decision about what a token is for.\n`
          : `Run --write to repair the ${String(fixable)} this tool may fix.\n`),
    );
    return 1;
  }

  if (report.changed) writeFileSync(cssPath, report.text, "utf8");
  process.stdout.write(
    report.changed
      ? `rewrote ${String(fixable)} measured span${fixable === 1 ? "" : "s"} across ${blocks}; ` +
          `${String(report.verified)} annotations now state what they measure.\n`
      : `verified ${String(report.verified)} annotations across ${blocks}; nothing to rewrite.\n`,
  );
  for (const finding of unfixable) {
    process.stderr.write(`  ${finding.cell}: ${finding.message}\n`);
  }
  return unfixable.length === 0 ? 0 : 1;
}

/**
 * Run only when this file IS the program.
 *
 * The `file:` guard is what lets the unit test import `annotate()` without the CLI firing:
 * under Vitest's jsdom environment `import.meta.url` is an `http://` URL, and `fileURLToPath`
 * throws on those rather than returning something plausible.
 */
if (import.meta.url.startsWith("file:")) {
  const here = fileURLToPath(import.meta.url);
  const entry = process.argv[1];
  if (entry !== undefined && resolve(entry) === here) {
    process.exitCode = main(process.argv.slice(2), resolve(dirname(here), "../src/styles/tokens.css"));
  }
}
