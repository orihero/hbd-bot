/**
 * `GET /api/generations` and `GET /api/generations/{attemptId}` — the render ledger.
 *
 * Transcribed from `.openpencil-export/users-generations-openapi.json` (produced by
 * `hbd/admin/routers/generations.py` over `hbd/admin/schemas/orders.py` — there is exactly
 * ONE projection of a `generation_attempts` row in that codebase, so the masking it applies
 * is applied everywhere the row is read).
 *
 * ## Four things this wire says that a table must not flatten
 *
 * **`costUsd` and `latencyMs` are `null`, not `0`, and `isInstrumented` says which kind of
 * row this is.** The columns default to `0.0`/`0` and nothing writes them yet, so every row
 * in production today is uninstrumented. "$0.00 / 0 ms" on the one screen an operator uses
 * to decide what to spend is a confident lie, and once real numbers land it would be
 * indistinguishable from a genuinely free, instantaneous vendor call.
 *
 * **`isOrphaned` states one predicate and cannot say which of its two causes applies.**
 * `order_id IS NULL` is both a name preview rendered before any order existed and an attempt
 * whose order was deleted — the FK sets null rather than cascading precisely so the tuning
 * data outlives the orders it came from. Nothing in the row tells them apart, so the UI must
 * not guess.
 *
 * **`nameCandidate` is MASKED and `sttTranscriptChars` is a LENGTH.** The name is the
 * orthography a vendor was asked to sing; the transcript is a near-verbatim copy of the whole
 * song, so only its size is on this wire. Plaintext for either comes from
 * `POST /api/reveal` (`generation_attempts.name_candidate_text`,
 * `generation_attempts.stt_transcript`) and from nowhere else — and both are PAGED reveals,
 * charged per page against the daily conversation ceiling as well as the record one.
 *
 * **Purged is not missing.** `identityPurgedAt` and `textPurgedAt` are the retention clocks
 * for those two columns. A purged value renders as "purged {date}" — never blank, and never
 * behind a reveal affordance that cannot succeed.
 *
 * ## Roles
 *
 * Both routes sit on `records.read`, which §12.2 gives to all four roles as **M** (masked) —
 * OWNER included. There is no unmasked cell here for anyone, so neither handler even takes
 * the operator. Nothing on this screen is role-gated; the reveal dialog it opens is.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";
import { GENERATIONS_PREFIX } from "./constants";
import {
  appendEach,
  appendPage,
  appendParam,
  pageMetaSchema,
  queryOf,
  type PageRequest,
} from "./pagination";
import { languageSchema } from "./users";

/* `Language` is declared beside `UserView`, its first consumer, and imported here rather
   than declared twice: two spellings of one closed vocabulary drift, and the drift always
   shows up as a filter that quietly matches nothing. */
export { LANGUAGE_VALUES, languageSchema, type Language } from "./users";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* Enums — verbatim from the spec; a new member must be added here first        */
/* -------------------------------------------------------------------------- */

/**
 * `GenerationKind` — what the attempt was trying to make. `name_preview` and
 * `name_verification` are the two that legitimately have no order, which is what makes
 * `isOrphaned` a normal condition rather than a fault.
 */
export const GENERATION_KIND_VALUES = [
  "song",
  "song_inpaint",
  "greeting",
  "lyrics",
  "name_preview",
  "name_verification",
  "cover",
] as const;
export const generationKindSchema = z.enum(GENERATION_KIND_VALUES);
export type GenerationKind = z.infer<typeof generationKindSchema>;

/**
 * `NameStrategy` — which spelling of the recipient's name this attempt tried. The bake-off
 * axis: `nameCandidateRank`, `isNameVerified` and `matchConfidence` are only readable beside
 * it.
 */
export const NAME_STRATEGY_VALUES = [
  "canonical",
  "stripped",
  "ascii",
  "cyrillic",
  "hyphenated",
  "phonetic",
] as const;
export const nameStrategySchema = z.enum(NAME_STRATEGY_VALUES);
export type NameStrategy = z.infer<typeof nameStrategySchema>;

/**
 * The ADAPTER names this deployment writes — finer than the `Vendor` an invoice is issued
 * under (two ElevenLabs adapters, one bill). `openai-compat` is hyphenated and the others are
 * not; that is the literal in `providers/llm/openai_compat.py` and it is not a typo to tidy.
 *
 * **The tuple below is the whole vocabulary**, taken from `providers/**` and from nowhere
 * else. A vendor remembered from a plan document or from another product is not in this
 * system; a filter offering one would return an empty page for ever and read as an outage.
 *
 * The `fake_*` four are `HBD_USE_FAKE_PROVIDERS` runs: recorded rather than dropped, because
 * no rows at all cannot be told from an uninstrumented deploy.
 */
export const PROVIDER_VALUES = [
  "elevenlabs_music",
  "elevenlabs_tts",
  "elevenlabs_scribe",
  "openai-compat",
  "gemini",
  "fake_music",
  "fake_tts",
  "fake_llm",
  "fake_stt",
] as const;
/**
 * For the FILTER only — a picker offering a value the server has never seen returns an empty
 * page, so the vocabulary is closed where an operator chooses from it.
 *
 * `AttemptWireView.provider` is deliberately NOT parsed with this. The column is free-form
 * `varchar(64)` (the vocabulary is a vendor's, not ours), so a new adapter shipping tomorrow
 * must render as itself rather than turn every row on the screen into a `SCHEMA_DRIFT`
 * banner. Widen the tuple when an adapter is added; the wire keeps working meanwhile.
 */
export const providerSchema = z.enum(PROVIDER_VALUES);
export type Provider = z.infer<typeof providerSchema>;

/* -------------------------------------------------------------------------- */
/* GET /api/generations                                                        */
/* -------------------------------------------------------------------------- */

/** One row of the render ledger. */
export const attemptWireViewSchema = z.object({
  id: z.string().uuid(),
  /** `null` exactly when `isOrphaned` — see the header for the two causes. */
  orderId: z.string().uuid().nullable(),
  kind: generationKindSchema,
  /** Which stage instance within the order, and which try within that stage. */
  sequence: z.number().int(),
  attempt: z.number().int(),
  /** The adapter that made the call. Free-form on the wire; see `providerSchema`. */
  provider: z.string().nullable(),
  /** The vendor's own id for the job, for chasing it in their console. */
  providerRemoteId: z.string().nullable(),
  language: languageSchema.nullable(),
  isSuccess: z.boolean(),
  isOrphaned: z.boolean(),

  nameCandidateStrategy: nameStrategySchema.nullable(),
  nameCandidateRank: z.number().int().nullable(),
  /** `null` = never verified, which is not the same as verified-and-failed (`false`). */
  isNameVerified: z.boolean().nullable(),
  matchConfidence: z.number().nullable(),

  /** MASKED, like any other name. Plaintext only via a reveal, and it is a paged one. */
  nameCandidate: z.string().nullable(),
  /** Retention clock for `nameCandidate`. Non-null = "purged {date}", not "missing". */
  identityPurgedAt: timestampSchema.nullable(),
  /** LENGTH only — the transcript is a near-verbatim copy of the whole song. */
  sttTranscriptChars: z.number().int().nullable(),
  /** Retention clock for the transcript and the candidate text. */
  textPurgedAt: timestampSchema.nullable(),

  errorCode: z.string().nullable(),
  /** Our own operator prose plus a closed-vocabulary code. Never a customer's words. */
  errorMessage: z.string().nullable(),
  /** `null` = the code is unknown to the taxonomy, NOT "not retryable". */
  isRetryable: z.boolean().nullable(),

  /** USD, decimal. `null` = never instrumented; never render it as `$0.00`. */
  costUsd: z.number().nullable(),
  costSource: z.string().nullable(),
  /** Whole milliseconds. `null` = never instrumented. */
  latencyMs: z.number().int().nullable(),
  /** Whether this row's telemetry was ever written. False today for every row. */
  isInstrumented: z.boolean(),
  createdAt: timestampSchema,
});
export type AttemptWireView = z.infer<typeof attemptWireViewSchema>;

export const attemptsPageSchema = z.object({
  items: z.array(attemptWireViewSchema),
  meta: pageMetaSchema,
});
export type AttemptsPage = z.infer<typeof attemptsPageSchema>;

/* -------------------------------------------------------------------------- */
/* Filters                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * §6.7's filter set. Every field is optional; an omitted one is not sent, and each boolean is
 * a TRI-STATE — absent, `true` and `false` are three different questions.
 */
export interface GenerationsFilters {
  /** The bounded count as well. A second query; nothing needs it to render the first page. */
  readonly withTotal?: boolean;
  /** REPEATED on the wire: OR within the field, AND across fields. Empty = do not filter. */
  readonly kind?: readonly GenerationKind[];
  /**
   * Exact adapter name, one at a time — this one does NOT repeat. A free string because the
   * vocabulary is a vendor's; `PROVIDER_VALUES` is what a picker offers, not what the
   * parameter accepts. Cap the INPUT at `MAX_PROVIDER_CHARS`: an over-long value is a 422
   * naming the parameter, and truncating it here would hide that behind a page nobody asked
   * for.
   */
  readonly provider?: string | null;
  readonly isSuccess?: boolean | null;
  /**
   * Exact pipeline error code, one at a time. Free-form: the vocabulary is the pipeline's.
   * Cap the input at `MAX_ERROR_CODE_CHARS`, for `provider`'s reason.
   */
  readonly errorCode?: string | null;
  /** One strategy. An unknown value is a 422, not a filter that quietly matches nothing. */
  readonly strategy?: NameStrategy | null;
  /** `true` = attempts with no order at all. It cannot say WHICH kind of orphan. */
  readonly isOrphaned?: boolean | null;
  /** `created_at`, half-open `[from, to)`, RFC 3339. Either end may stand alone. */
  readonly from?: string | null;
  readonly to?: string | null;
}

function generationsQuery(filters: GenerationsFilters, page: PageRequest): string {
  const params = new URLSearchParams();
  if (filters.withTotal === true) params.append("withTotal", "true");
  appendEach(params, "kind", filters.kind);
  appendParam(params, "provider", filters.provider);
  appendParam(params, "isSuccess", filters.isSuccess);
  appendParam(params, "errorCode", filters.errorCode);
  appendParam(params, "strategy", filters.strategy);
  appendParam(params, "isOrphaned", filters.isOrphaned);
  appendParam(params, "from", filters.from);
  appendParam(params, "to", filters.to);
  appendPage(params, page);
  return queryOf(params);
}

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const GENERATIONS_ENDPOINT = {
  list: "GET /api/generations",
  detail: "GET /api/generations/{attemptId}",
} as const;

/** One keyset page of the render ledger, newest first. */
export function listGenerations(
  filters: GenerationsFilters,
  page: PageRequest,
  signal?: AbortSignal,
): Promise<ApiResult<AttemptsPage>> {
  return request({
    endpoint: GENERATIONS_ENDPOINT.list,
    path: `${GENERATIONS_PREFIX}${generationsQuery(filters, page)}`,
    schema: attemptsPageSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}

/**
 * One attempt by id. An id that matches nothing is a 404, never an empty body — so a detail
 * panel opened on a stale link says "no such attempt" rather than drawing an empty shell.
 */
export function getGeneration(
  attemptId: string,
  signal?: AbortSignal,
): Promise<ApiResult<AttemptWireView>> {
  return request({
    endpoint: GENERATIONS_ENDPOINT.detail,
    path: `${GENERATIONS_PREFIX}/${encodeURIComponent(attemptId)}`,
    schema: attemptWireViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
