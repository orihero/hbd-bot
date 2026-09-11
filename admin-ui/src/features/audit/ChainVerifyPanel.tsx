/**
 * `GET /api/audit/verify`, rendered as the two facts it actually reports.
 *
 * **1. Does the chain hold, and over how much of the table?** §11.4's schema note is blunt
 * about the trap: a clean `ok: true` with `isComplete: false` is *not* a clean answer over
 * the whole log — the walk hit its row ceiling. "Render both facts or neither." So the verb
 * changes with `isComplete`: an incomplete walk says **holds over the rows checked**, never
 * **holds**, and the row count sits beside it.
 *
 * **2. Which protections are actually deployed.** §12.4: if `BAYRAM_ADMIN_AUDIT_DSN` is empty
 * the migration skips the `REVOKE`, and `/audit/verify` reports
 * `chainProtection: "hmac-only"` — "which the panel renders verbatim. A control that is not
 * deployed is reported as not deployed." The value contains a `-` and a `+` and is not a
 * slug: it is printed exactly as it arrives, and never run through `humaniseEnum`.
 *
 * `truncationPoints` are seqs below which rows were deleted **on purpose** by the 730-day
 * retention sweep, so a gap there is not a break — the panel names them so nobody
 * investigates a hole the system dug itself.
 */

import type { ReactElement } from "react";

import type { ChainVerifyResponse } from "@/api";
import { tintVar } from "@/components/domain";
import { cn, formatInteger } from "@/lib";

export interface ChainVerifyPanelProps {
  readonly verify: ChainVerifyResponse;
  readonly className?: string;
}

/** The two deployed shapes, and what each one means for what a break would prove. */
const PROTECTION_NOTE: Record<string, string> = {
  "revoke+hmac": "the app role cannot UPDATE or DELETE this table, and every row is HMAC-chained",
  "hmac-only":
    "the database REVOKE is not deployed (BAYRAM_ADMIN_AUDIT_DSN is empty) — the HMAC chain is the only control standing",
};

export function ChainVerifyPanel({ verify, className }: ChainVerifyPanelProps): ReactElement {
  const isBroken = !verify.ok;
  // Three verdicts, three hues, and the verb below changes with them — `--caution` is the
  // partial answer ("holds over the rows checked"), not a failure, which is why it is the
  // softer attention hue and not `--warning`.
  const colorVar = isBroken
    ? "var(--error)"
    : verify.isComplete
      ? "var(--success)"
      : "var(--caution)";
  const glyph = isBroken ? "✗" : verify.isComplete ? "✓" : "◑";
  const verdict = isBroken
    ? "chain broken"
    : verify.isComplete
      ? "chain holds"
      : "chain holds over the rows checked";

  return (
    <section
      data-testid="chain-verify"
      data-ok={String(verify.ok)}
      data-complete={String(verify.isComplete)}
      data-protection={verify.chainProtection}
      aria-label="audit chain verification"
      /* A card, like everything else on this screen: paper, 28px, a whisper of shadow, and
         no border at all. The verdict's hue lives in the chip below, not in an outline. */
      className={cn(
        "flex flex-col gap-4 rounded-card bg-surface-card p-card shadow-card",
        className,
      )}
    >
      <header className="flex flex-wrap items-baseline gap-2">
        {/* The verdict is a tinted capsule: the hue in the ground and the glyph, the WORDS in
            `--ink` at 6.6:1. Glyph, word and colour — three channels, per §11.3. */}
        <span
          className="type-h2 inline-flex items-baseline gap-2 rounded-pill px-3 py-1 text-ink"
          style={{ backgroundColor: tintVar(colorVar) }}
        >
          <span aria-hidden="true" style={{ color: colorVar }}>
            {glyph}
          </span>
          {verdict}
        </span>
        <span className="type-caption text-ink-muted">audit chain</span>
      </header>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Fact label="rows checked" value={formatInteger(verify.checkedRows)} isNumeric />
        <Fact
          label="last seq"
          value={verify.lastSeq === null ? "no rows" : formatInteger(verify.lastSeq)}
          isNumeric
        />
        <Fact
          label="walk"
          value={verify.isComplete ? "whole table" : "stopped at the row ceiling"}
        />
        <Fact
          label="first break"
          value={verify.firstBreakSeq === null ? "none" : `seq ${formatInteger(verify.firstBreakSeq)}`}
          isNumeric={verify.firstBreakSeq !== null}
        />
      </dl>

      <p className="type-body-sm text-ink-muted" data-testid="chain-protection">
        {/* Verbatim, per §12.4 — `revoke+hmac` and `hmac-only` are values, not slugs. The
            value is printed exactly as it arrived and never run through `humaniseEnum`: a
            control that is not deployed is reported as not deployed. */}
        <code className="type-mono rounded-2xs bg-surface-control px-2 py-0.5 text-ink">
          {verify.chainProtection}
        </code>{" "}
        <span className="text-ink-muted">
          {PROTECTION_NOTE[verify.chainProtection] ?? "this build has no note for that value"}
        </span>
      </p>

      {verify.isComplete ? null : (
        <p className="type-body-sm rounded-2xl bg-caution-tint px-4 py-3 text-ink">
          <span aria-hidden="true" className="text-caution">
            ◑{" "}
          </span>
          The walk stopped early, so this is an answer about {formatInteger(verify.checkedRows)}{" "}
          rows and not about the log.
        </p>
      )}

      {verify.truncationPoints.length === 0 ? null : (
        <p className="type-body-sm text-ink-muted" data-testid="chain-truncation-points">
          <span className="num">
            {verify.truncationPoints.map((seq) => formatInteger(seq)).join(", ")}
          </span>{" "}
          — rows below these seqs were deleted on purpose by the retention sweep. A gap there
          is not a break.
        </p>
      )}
    </section>
  );
}

function Fact({
  label,
  value,
  isNumeric = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly isNumeric?: boolean;
}): ReactElement {
  return (
    <div className="flex flex-col">
      <dt className="type-caption text-ink-muted">{label}</dt>
      <dd className={cn("type-body text-ink", isNumeric && "num")}>{value}</dd>
    </div>
  );
}
