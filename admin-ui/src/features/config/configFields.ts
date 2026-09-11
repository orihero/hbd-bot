/**
 * `GET /api/config`, arranged into the groups an operator reads it in.
 *
 * Two things about this endpoint decide the whole screen.
 *
 * **1. It is the admin PROCESS's own settings, not the bot's.** Every field is an
 * `BAYRAM_ADMIN_*` variable, read once inside the lifespan into a frozen `AdminSettings`. There
 * is no override table behind the route, nothing to commit and nothing to roll back — so
 * every field here is **restart only**, and marking any of them `live` would be a claim the
 * server cannot honour. The bot's tiered fields (§8.3) live behind the Phase 7 editor and
 * are named in `ABSENT_RUNTIME_FIELDS` so an operator who followed the similarity-threshold
 * link from `/generations/names` finds out where the value actually is.
 *
 * **2. Secrets are ABSENT, not masked** (§12.3). `databaseUrl`, `redisUrl`,
 * `adminAuditHmacKey`, `adminProbeToken` and `adminAuditDsn` are not on the response in any
 * form at any role. A blank line would read as "unset", and an operator who believes the
 * audit HMAC key is unset will go and set one — breaking the chain. Where the server
 * publishes a presence flag instead (`isAuditDsnConfigured`, `isProbeTokenConfigured`) the
 * field renders *configured* / *not configured*, which is a fact about existence and safe to
 * state; where it publishes where a DSN points, the host and port are separate `read-only`
 * fields.
 */

import type { ConfigTier } from "@/components/domain";
import type { ConfigView } from "@/api";
import { formatDurationS, formatInteger } from "@/lib";

export interface ConfigFieldModel {
  /** The wire's camelCase field name, rendered verbatim. */
  readonly name: string;
  readonly value?: string | undefined;
  readonly tier: ConfigTier;
  readonly note?: string | undefined;
}

export interface ConfigGroupModel {
  readonly id: string;
  readonly title: string;
  readonly blurb?: string;
  readonly fields: readonly ConfigFieldModel[];
}

const yesNo = (value: boolean): string => (value ? "yes" : "no");

/** `43,200 s · 12h` — the raw number an env var is set to, and what it means. */
const seconds = (value: number): string =>
  `${formatInteger(value)} s · ${formatDurationS(value)}`;

/** A port is an address, not a quantity: never grouped, so `5432` cannot read as `5,432`. */
const hostPort = (host: string | null, port: number | null): string => {
  if (host === null) return "not configured";
  return port === null ? host : `${host}:${String(port)}`;
};

export function configGroups(view: ConfigView): readonly ConfigGroupModel[] {
  return [
    {
      id: "runtime",
      title: "Runtime",
      fields: [
        { name: "environment", value: view.environment, tier: "read-only" },
        { name: "logLevel", value: view.logLevel, tier: "read-only" },
        { name: "isDebug", value: yesNo(view.isDebug), tier: "read-only" },
        { name: "isProduction", value: yesNo(view.isProduction), tier: "read-only" },
      ],
    },
    {
      id: "panel",
      title: "The panel",
      blurb:
        "adminConfigEnabled is the escape hatch for the Phase 7 editor: read from the environment, never from the config holder it would otherwise gate.",
      fields: [
        { name: "adminEnabled", value: yesNo(view.adminEnabled), tier: "read-only" },
        { name: "adminConfigEnabled", value: yesNo(view.adminConfigEnabled), tier: "read-only" },
        { name: "adminHost", value: view.adminHost, tier: "read-only" },
        { name: "adminPort", value: String(view.adminPort), tier: "read-only" },
        { name: "adminPublicOrigin", value: view.adminPublicOrigin, tier: "read-only" },
        {
          name: "isCookieSecure",
          value: yesNo(view.isCookieSecure),
          tier: "read-only",
          note: view.isCookieSecure
            ? undefined
            : "the __Host- cookie prefix requires Secure; this is a development-only setting",
        },
      ],
    },
    {
      id: "sessions",
      title: "Sessions and step-up",
      blurb:
        "The step-up grace is zero for user.purge and config.write whatever this says — those two actions re-authenticate every time.",
      fields: [
        { name: "adminSessionTtlS", value: seconds(view.adminSessionTtlS), tier: "read-only" },
        {
          name: "adminSessionIdleTtlS",
          value: seconds(view.adminSessionIdleTtlS),
          tier: "read-only",
        },
        {
          name: "adminStepUpGraceSeconds",
          value: seconds(view.adminStepUpGraceSeconds),
          tier: "read-only",
        },
      ],
    },
    {
      id: "argon2",
      title: "argon2id",
      blurb:
        "Hashed in a worker thread: 64 MiB and ~50 ms on the event loop would block every other request.",
      fields: [
        {
          name: "adminArgon2TimeCost",
          value: formatInteger(view.adminArgon2TimeCost),
          tier: "read-only",
        },
        {
          name: "adminArgon2MemoryKib",
          value: `${formatInteger(view.adminArgon2MemoryKib)} KiB`,
          tier: "read-only",
        },
        {
          name: "adminArgon2Parallelism",
          value: formatInteger(view.adminArgon2Parallelism),
          tier: "read-only",
        },
      ],
    },
    {
      id: "client-ip",
      title: "Client IP derivation",
      blurb:
        "The login limiter is keyed on (username, client IP). A wrong hop count makes every request look like it came from the proxy.",
      fields: [
        {
          name: "adminTrustedProxyHops",
          value: formatInteger(view.adminTrustedProxyHops),
          tier: "read-only",
        },
        {
          name: "adminTrustedProxyCidrs",
          value:
            view.adminTrustedProxyCidrs.length === 0
              ? "none"
              : view.adminTrustedProxyCidrs.join(", "),
          tier: "read-only",
        },
      ],
    },
    {
      id: "reveal-budget",
      title: "Reveal budget",
      blurb:
        "Counted in RECORDS, not requests: one conversation reveal can unmask 50 bodies, and the budget is a detection control as much as a limit.",
      fields: [
        {
          name: "adminRevealRecordsPerHour",
          value: `${formatInteger(view.adminRevealRecordsPerHour)} records/hour`,
          tier: "read-only",
        },
        {
          name: "adminRevealConversationsPerDay",
          value: `${formatInteger(view.adminRevealConversationsPerDay)} conversations/day`,
          tier: "read-only",
        },
      ],
    },
    {
      id: "dependencies",
      title: "Where the DSNs point",
      blurb: "Where they point, never what they authenticate with.",
      fields: [
        {
          name: "databaseHost",
          value: hostPort(view.databaseHost, view.databasePort),
          tier: "read-only",
        },
        { name: "redisHost", value: hostPort(view.redisHost, view.redisPort), tier: "read-only" },
        { name: "databaseUrl", tier: "secret-absent" },
        { name: "redisUrl", tier: "secret-absent" },
      ],
    },
    {
      id: "secrets",
      title: "Secrets",
      blurb:
        "Absent at every role, revealed or not — not masked. An empty value here would read as 'unset', and acting on that misreading breaks the audit chain.",
      fields: [
        { name: "adminAuditHmacKey", tier: "secret-absent" },
        {
          name: "adminAuditDsn",
          value: view.isAuditDsnConfigured ? "configured" : "not configured",
          tier: "secret-absent",
          note: view.isAuditDsnConfigured
            ? "the audit REVOKE migration ran — see the chain protection on /audit"
            : "empty, so the migration skipped the REVOKE and /audit/verify reports hmac-only",
        },
        {
          name: "adminProbeToken",
          value: view.isProbeTokenConfigured ? "configured" : "not configured",
          tier: "secret-absent",
          note: view.isProbeTokenConfigured
            ? undefined
            : "/readyz answers the constant public shape for every unauthorised caller",
        },
      ],
    },
  ];
}

/**
 * The bot's tiered fields, which this endpoint does not return.
 *
 * `/generations/names` links here to answer "what should `BAYRAM_NAME_CANDIDATE_ORDER` be?",
 * and an operator who arrives to find no such field has been sent to a dead end. These rows
 * carry §8.3's real tiers and say plainly where the value lives — they are documentation of
 * an absence, which is why every one of them has an explicit value rather than a blank.
 */
export const ABSENT_RUNTIME_FIELDS: readonly ConfigFieldModel[] = [
  {
    name: "name_candidate_order",
    value: "not on this endpoint",
    tier: "live",
    note: "§8.3 Tier 1 — the bake-off flagship, applied by reordering the variable and never by editing code. Today that still needs a redeploy; the editor is Phase 7.",
  },
  {
    name: "name_match_min_similarity",
    value: "not on this endpoint",
    tier: "live",
    note: "§8.3 Tier 1 — the verification threshold /generations/names marks on its histogram.",
  },
  {
    name: "greetings_per_kit",
    value: "not on this endpoint",
    tier: "after-fix",
    note: "§8.3 Tier 2 — read in both the generation and the delivery phase of the same order; live editing would score the last two progress frames against a different denominator.",
  },
  {
    name: "llm_temperature",
    value: "not on this endpoint",
    tier: "after-fix",
    note: "§8.3 Tier 2 — the bot captures Settings by value at boot, so a commit would move the worker and not the wizard's lyric writer.",
  },
  {
    name: "kit_price_amount_minor",
    value: "not on this endpoint",
    tier: "after-fix",
    note: "§8.3 Tier 2, the sharpest hazard — frozen into BotDeps at boot and read live in the orchestrator: one order, two amounts.",
  },
];
