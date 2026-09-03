/**
 * `<ConfigField>` — one setting, in one of §11.2's **four visual tiers**.
 *
 * `/config` answers "what differs from the deployed config?", and the four tiers are the
 * answer to a second question the operator has before they touch anything: *can I change
 * this, and what happens if I do?*
 *
 * | tier | meaning (§8.3) |
 * |---|---|
 * | `live` | Tier 1 — on the `LIVE_EDITABLE_FIELDS` allowlist, takes hold on refresh or on the next order |
 * | `after-fix` | Tier 2 — editable only once its named fix lands. Three fields today: the greeting trio, the two LLM fields, and the price pair. Editing one now would apply to one process and not another — the bot gating at one price while the worker authorises at another |
 * | `read-only` | restart-only. Changing it means an env change and a redeploy |
 * | `secret-absent` | never returned at any role. `databaseUrl`, `redisUrl`, `adminAuditHmacKey`, `adminProbeToken`, `adminAuditDsn` are ABSENT, not masked (§12.3) — what is shown is where a DSN points, never what it authenticates with |
 *
 * The tiers are not decoration. A `secret-absent` field rendered as an empty string reads as
 * "unset", and an operator who believes the audit HMAC key is unset will go and set one,
 * breaking the chain. So that tier renders a lock and the word **not shown**, and where the
 * server does publish a presence flag (`isAuditDsnConfigured`) it renders *configured* or
 * *not configured* instead — a fact about existence that is safe to state.
 *
 * Phase 1's `/config` is READ-ONLY at every role; the write path, its dry-run and
 * `ConfigDiffDialog` are Phase 6. This component therefore renders values and never an
 * input.
 */

import type { ReactElement, ReactNode } from "react";

import { cn } from "@/lib";

import { tintVar } from "./colors";

/** §11.2's four tiers, in the order they appear there. */
export type ConfigTier = "live" | "after-fix" | "read-only" | "secret-absent";

export interface ConfigFieldProps {
  /** The `Settings` field name, in the wire's camelCase. Rendered in mono, verbatim. */
  name: string;
  /** The value, already formatted by the caller. Never a secret. */
  value?: ReactNode;
  tier: ConfigTier;
  /** When the change takes hold — §8.3's "next order" / "on refresh". */
  effect?: string | undefined;
  /** For `after-fix`: the named fix this field is waiting on. */
  note?: string | undefined;
  className?: string | undefined;
}

interface TierPresentation {
  readonly glyph: string;
  readonly label: string;
  readonly colorVar: string;
}

/** Glyph + word + colour, for the same reason a status pill carries all three (§11.3). */
const TIER_PRESENTATION: Record<ConfigTier, TierPresentation> = {
  live: { glyph: "◉", label: "live editable", colorVar: "var(--success)" },
  "after-fix": { glyph: "⚑", label: "after a named fix", colorVar: "var(--caution)" },
  "read-only": { glyph: "■", label: "restart only", colorVar: "var(--slate)" },
  // `--neutral`, not `--ink-muted`: every hue the tier chip uses has to be a SEMANTIC
  // family, because the chip derives its ground with `tintVar` and only the families ship a
  // `-tint` member. `--neutral` is a true grey (4.52:1 worst-case light, 4.60:1 dark), so
  // "not shown" still reads as the quietest tier without being an unresolvable variable.
  "secret-absent": { glyph: "🔒", label: "not shown", colorVar: "var(--neutral)" },
};

export function ConfigField({
  name,
  value,
  tier,
  effect,
  note,
  className,
}: ConfigFieldProps): ReactElement {
  const presentation = TIER_PRESENTATION[tier];

  return (
    <div
      data-testid="config-field"
      data-field={name}
      data-tier={tier}
      className={cn(
        // The tier used to be a 2px left rule. This design has no rules, so the tier chip
        // below carries the hue instead — glyph, word AND a tinted capsule, three channels
        // where there were two. The field itself is a soft card.
        "flex flex-col gap-1.5 rounded-2xl bg-surface-card px-4 py-3 shadow-2xs",
        tier === "secret-absent" && "bg-surface-control shadow-none",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="type-mono text-ink-muted">{name}</span>
        <span
          data-testid="config-tier"
          className="type-caption inline-flex items-baseline gap-1 rounded-pill px-2 py-0.5"
          style={{
            color: presentation.colorVar,
            backgroundColor: tintVar(presentation.colorVar),
          }}
        >
          <span aria-hidden="true">{presentation.glyph}</span>
          <span>{presentation.label}</span>
        </span>
      </div>

      <div className="type-body num text-ink" data-testid="config-value">
        {tier === "secret-absent" ? (
          // Never an empty string here: "unset" is a different claim from "never returned",
          // and only one of them is true.
          <span className="text-ink-muted">{value ?? SECRET_ABSENT_VALUE}</span>
        ) : (
          value
        )}
      </div>

      {effect === undefined ? null : (
        <span className="type-body-sm text-ink-muted">{`takes hold: ${effect}`}</span>
      )}
      {note === undefined ? null : <span className="type-body-sm text-ink-muted">{note}</span>}
    </div>
  );
}

/** §12.3: these are absent at every role, not masked. */
export const SECRET_ABSENT_VALUE = "not returned at any role";
