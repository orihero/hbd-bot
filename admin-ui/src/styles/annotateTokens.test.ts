/**
 * `tools/annotate-tokens.mts` — the annotation generator, measured against the file it is
 * allowed to rewrite.
 *
 * A generator that writes into the one file this repo's accessibility contract rests on is
 * only trustworthy on two conditions, and every assertion below is one of them:
 *
 *  1. **It agrees with the humans BEFORE it is trusted to write.** All 72 annotations in
 *     `tokens.css` — 36 in each of the two cells — were measured by hand or written
 *     by this tool and then read by a person. `--check` recomputes every one of them and finds
 *     nothing, so the first thing the tool proves is that it reproduces the tree, not that it
 *     can produce a tree of its own. A generator that disagreed here would be asking to be
 *     believed over the file it is meant to be maintaining.
 *  2. **It touches ONLY the measured span.** `N.NN:1 [at best ]on <ground>` is machine-owned;
 *     the sentence after the em dash is a human's statement of what the token is FOR, and no
 *     arithmetic can author it. So the no-op case is asserted byte-for-byte, the prose tail is
 *     asserted to survive a rewrite verbatim, and a declaration with NO annotation is asserted
 *     to be reported and left alone rather than given a machine-written comment.
 *
 * `tokenContrast.test.ts` is the gate; this file is not a second copy of it. It never asks
 * whether a token clears its bar — it asks whether the tool's account of the stylesheet is
 * honest, and whether its edits are as narrow as it claims.
 *
 * The fixtures are always the REAL `tokens.css`, mutated. A synthetic three-token stylesheet
 * would let this file pass while the tool broke on the actual grammar — the alpha hexes, the
 * `--x-tint over --surface` grounds, the multi-line comments between declarations.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { annotate } from "../../tools/annotate-tokens.mts";
import { blockRange, readStylesheet, THEMES } from "./paletteBlocks.mts";

const TOKENS_PATH = resolve(process.cwd(), "src/styles/tokens.css");
const TOKENS_CSS = readFileSync(TOKENS_PATH, "utf8");

/** Replace the first occurrence of `find`, failing loudly rather than silently doing nothing. */
function mutate(css: string, find: string, replaceWith: string): string {
  expect(css, `the fixture expected to find: ${find}`).toContain(find);
  return css.replace(find, replaceWith);
}

/** The lines that differ between two versions of the stylesheet, as `oldLine → newLine`. */
function changedLines(before: string, after: string): readonly string[] {
  const oldLines = before.split("\n");
  const newLines = after.split("\n");
  expect(newLines).toHaveLength(oldLines.length);
  return oldLines
    .map((line, index) => [line, newLines[index] ?? ""] as const)
    .filter(([oldLine, newLine]) => oldLine !== newLine)
    .map(([oldLine, newLine]) => `${oldLine.trim()} → ${newLine.trim()}`);
}

describe("the generator agrees with the humans before it is trusted to write", () => {
  const report = annotate(TOKENS_CSS);

  it("recomputes every hand-written annotation and finds no drift", () => {
    // The acceptance test for the whole tool. 72 comments across two blocks, recomputed from
    // the hexes beside them: not one disagrees. Until this holds there is no reason to let the
    // tool near the file, and if a value legitimately moves, this is the number that moves
    // with it. It was 70 before `--brand-solid-edge` arrived, went to 144 while the console
    // shipped two palettes on a `data-palette` axis, and came back to 72 when it committed to
    // one — the tool needed no change in either direction, which is the claim below about
    // looping over the blocks it finds.
    expect(
      report.findings.map((finding) => `${finding.cell}: ${finding.message}`),
      "the tool disagrees with tokens.css. Before assuming the comments are stale, check " +
        "that the tool's arithmetic is still the gate's — they share contrastMath.mts " +
        "precisely so that this can only be one bug and not two.",
    ).toEqual([]);
    expect(report.verified).toBe(72);
  });

  it("rewriting an unmodified stylesheet is a byte-for-byte no-op", () => {
    // `--write` on a clean tree must produce a zero-byte diff. A generator that reformatted
    // as it went — normalised whitespace, re-wrapped a comment, reordered a declaration —
    // would make every future palette commit unreviewable, because the measurement change
    // would be buried in the churn.
    expect(report.changed).toBe(false);
    expect(report.text).toBe(TOKENS_CSS);
  });

  it("measures each block in its OWN cell", () => {
    // The cells come from the stylesheet through the same parser the gate uses, so the set of
    // blocks here is a fact about the file and not about this tool. Labels and selectors are
    // asserted together because measuring the right block under the wrong label is exactly as
    // wrong as the reverse.
    expect(report.cells.map((cell) => `${cell.label} ${cell.selector}`)).toEqual(
      readStylesheet(TOKENS_CSS).cells.map((cell) => `${cell.label} ${cell.selector}`),
    );
    expect(report.cells).toHaveLength(THEMES.length);
    expect(report.cells.map((cell) => cell.verified).reduce((a, b) => a + b, 0)).toBe(
      report.verified,
    );
  });
});

describe("it finds drift, and repairs exactly the span that drifted", () => {
  it("a stale ratio is named and rewritten back to the measured value", () => {
    // The defect this whole apparatus exists for, in its purest form: a number nobody
    // remeasured after the hex beside it moved. `--fg-2` said 4.6:1 and was 4.34:1.
    const drifted = mutate(
      TOKENS_CSS,
      "--ink-muted: #636363; /* 4.89:1",
      "--ink-muted: #636363; /* 4.99:1",
    );
    const report = annotate(drifted);

    expect(report.findings).toHaveLength(1);
    expect(report.findings[0]?.kind).toBe("ratio");
    expect(report.findings[0]?.token).toBe("--ink-muted");
    expect(report.findings[0]?.cell).toBe("light");
    expect(report.findings[0]?.fixable).toBe(true);
    expect(report.text).toBe(TOKENS_CSS);
  });

  it("a flattering ground is named and re-pointed at the extreme one", () => {
    // `--edge` really is 3.34:1 on a card and really is 3.09:1 on the page ground, so this
    // drift is a comment that states a TRUE number about the wrong surface — the failure the
    // "worst ground" rule exists to close, and the one a human proof-reading a diff is least
    // likely to catch.
    const drifted = mutate(
      TOKENS_CSS,
      "--edge: #8c8c92; /* 3.09:1 on --surface —",
      "--edge: #8c8c92; /* 3.34:1 on --surface-card —",
    );
    const report = annotate(drifted);

    expect(report.findings).toHaveLength(1);
    expect(report.findings[0]?.kind).toBe("ground");
    // Both numbers appear in the message: the one the comment picked and the one it owes.
    expect(report.findings[0]?.message).toContain("--surface-card at 3.34:1");
    expect(report.findings[0]?.message).toContain("--surface, at 3.09:1");
    expect(report.text).toBe(TOKENS_CSS);
  });

  it("the claim FORM follows the token's bar, not what the file happens to say", () => {
    // `at best on` is a ceiling and belongs to a token that clears no bar; `on` is a floor.
    // Which one a comment uses is decided by `ROLES`, so a text token that acquired an "at
    // best" is drift even when its number and its ground are both right — the comment would
    // be claiming the opposite of what the gate measures.
    const drifted = mutate(
      TOKENS_CSS,
      "--ink: #4d4d4d; /* 6.88:1 on",
      "--ink: #4d4d4d; /* 6.88:1 at best on",
    );
    const report = annotate(drifted);

    expect(report.findings).toHaveLength(1);
    expect(report.findings[0]?.kind).toBe("form");
    expect(report.text).toBe(TOKENS_CSS);
  });

  it("one drifted ratio rewrites one line and no others", () => {
    // The narrowness claim, measured rather than asserted. A tool with the run of the file is
    // one bad regex away from rewriting a hex, a prose comment or a declaration it was never
    // pointed at, and the palette commits it will appear in are exactly the commits where
    // nobody can tell an intended change from an accidental one.
    const drifted = mutate(
      TOKENS_CSS,
      "--slate-fill: #5b6e8f; /* 4.21:1",
      "--slate-fill: #5b6e8f; /* 9.99:1",
    );
    expect(changedLines(drifted, annotate(drifted).text)).toEqual([
      "--slate-fill: #5b6e8f; /* 9.99:1 on --surface-control-hover — cancelled marks and bars */ → " +
        "--slate-fill: #5b6e8f; /* 4.21:1 on --surface-control-hover — cancelled marks and bars */",
    ]);
  });

  it("the role prose after the em dash survives a rewrite verbatim", () => {
    // The tool measures; it does not describe. "every muted label" is a human's sentence
    // about what the token is for, and the regex the rewrite is built on deliberately ENDS at
    // the dash so that the sentence is never inside the span being rebuilt.
    const drifted = mutate(
      TOKENS_CSS,
      "--ink-muted: #636363; /* 4.89:1 on --brand-tint over --surface — every muted label */",
      "--ink-muted: #636363; /* 1.11:1 at best on --surface — every muted label */",
    );
    expect(annotate(drifted).text).toContain(
      "--ink-muted: #636363; /* 4.89:1 on --brand-tint over --surface — every muted label */",
    );
  });

  it("repairing is idempotent — a second pass finds nothing left to do", () => {
    // Convergence, which is what makes `--check` in CI meaningful: if `--write` could produce
    // a file that `--check` still rejects, the gate would be unpassable and the tool would be
    // the thing that made it so. The tie-preserving choice of ground is what this is really
    // testing — a tool that always rewrote to whichever tied ground a stable sort put first
    // could oscillate between two equally true comments.
    const drifted = mutate(
      TOKENS_CSS,
      "/* 4.89:1 on --brand-tint over --surface",
      "/* 4.11:1 on --surface-card",
    );
    const once = annotate(drifted);
    expect(once.changed).toBe(true);
    const twice = annotate(once.text);
    expect(twice.findings).toEqual([]);
    expect(twice.text).toBe(once.text);
  });
});

describe("it reports what it may not write, rather than inventing it", () => {
  it("a literal colour with no annotation is named, with the line a human should write", () => {
    // The gate fails on an unannotated colour token and this tool cannot fix it, because the
    // repair contains a sentence only a person can write. So it hands over the half it does
    // know — the ratio and the ground — and marks the finding unfixable rather than emitting
    // a comment with an empty tail that would then read as reviewed.
    const stripped = mutate(
      TOKENS_CSS,
      "--edge: #8c8c92; /* 3.09:1 on --surface — the popover boundary ring */",
      "--edge: #8c8c92;",
    );
    const report = annotate(stripped);

    const unannotated = report.findings.filter((finding) => finding.kind === "unannotated");
    expect(unannotated.map((finding) => finding.token)).toEqual(["--edge"]);
    expect(unannotated[0]?.fixable).toBe(false);
    expect(unannotated[0]?.message).toContain("3.09:1 on --surface");
    // …and it wrote nothing: the stripped declaration is still bare.
    expect(report.changed).toBe(false);
    expect(report.text).toContain("--edge: #8c8c92;\n");
  });
});

describe("each block is measured against its OWN hexes, and repaired in place", () => {
  /**
   * Cell isolation is the property the whole block table depends on, and it survived the
   * removal of the `data-palette` axis because it was never really about palettes: it is the
   * claim that a ratio written inside one block was measured against that block's own grounds.
   * With two cells the claim is checked by moving the dark block's WORST ground — every dark
   * ratio measured against it moves, and `:root`, which shares none of its hexes, must not.
   *
   * `blockRange` is anchored rather than an `indexOf`, and that anchoring is why a compound
   * selector cannot capture this block. The axis that made the collision live is gone; the
   * assertion stays, because the next compound block will not announce itself either.
   */
  it("a hex moved in ONE block drifts that block's annotations and no other's", () => {
    const [start] = blockRange(TOKENS_CSS, '[data-theme="dark"]');
    const drifted =
      TOKENS_CSS.slice(0, start) +
      mutate(
        TOKENS_CSS.slice(start),
        "--surface-control-hover: #303038;",
        "--surface-control-hover: #33333a;",
      );

    const report = annotate(drifted);
    expect(report.findings.length).toBeGreaterThan(10);
    expect([...new Set(report.findings.map((finding) => finding.cell))]).toEqual(["dark"]);

    // The repair stays inside that block too: every changed line is below its opening brace.
    const [repairedStart] = blockRange(report.text, '[data-theme="dark"]');
    expect(report.text.slice(0, repairedStart)).toBe(drifted.slice(0, start));
    expect(annotate(report.text).findings).toEqual([]);
  });
});
