import { SlidersHorizontal } from "lucide-react";
import { useCallback, useMemo, useState, type JSX } from "react";
import { useSearchParams } from "react-router-dom";

import {
  AUDIT_ACTION_VALUES,
  AUDIT_OUTCOME_VALUES,
  AUDIT_SUBJECT_TYPE_VALUES,
  type AuditAction,
  type AuditEntryView,
  type AuditFilters,
  type AuditOutcome,
  type AuditSubjectType,
} from "@/api/audit";
import { CLIENT_ERROR_CODES } from "@/api/client";
import { MAX_SUBJECT_ID_CHARS } from "@/api/constants";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type PageRequest } from "@/api/pagination";
import { Badge } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { formatCount } from "@/features/dashboard/adapt";
import { EMPTY_VALUE, REVEAL_REASON_KEYS } from "@/features/reveal";
import type { AdminQueryError } from "@/lib/adminQuery";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { cn } from "@/lib/cn";
import { useSessionGuard } from "@/state/useSessionGuard";

/** Every sentence on this screen, bound to the operator's chosen language. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

import { ChainVerifyPanel } from "./ChainVerifyPanel";
import {
  ADMIN_ROLE_LABELS,
  AUDIT_ACTION_GROUPS,
  AUDIT_OUTCOME_LABELS,
  AUDIT_OUTCOME_MEANINGS,
  AUDIT_OUTCOME_TONES,
  NO_FIELDS_NAMED,
  NO_REASON_TEXT_LABEL,
  NO_SUBJECT,
  REASON_SWEEP_CAVEAT,
  REASON_WITHHELD_LABEL,
  RECORD_COUNT_ABSENT,
  RECORD_COUNT_ABSENT_LABEL,
  SEAL_EXPLANATION,
  formatSeq,
  isoToLocalInput,
  localInputToIso,
  localZoneLabel,
  reasonDisclosure,
  shortenId,
  shortenSeal,
  splitTimestamp,
  subjectTypeLabel,
} from "./auditFormat";
import {
  EnumToggleGroup,
  FilterPanel,
  GroupedEnumToggles,
  SingleEnumSelect,
  TextFilter,
  TimeRangeFilter,
} from "./filterControls";
import { useAuditEntries, useChainVerify } from "./useAudit";

/**
 * `/audit` — who did what to which record, when, from where, and whether it worked.
 *
 * This is the compliance record and it is the table an investigation reads under time
 * pressure, so every decision below is about not making a claim the wire cannot support.
 *
 * ## Everything narrowing the list is in the URL
 *
 * Seven filters and the cursor live in the query string, so a filtered view is a link — the
 * thing an operator pastes into an incident channel — and survives a reload. What is
 * deliberately NOT in the URL is anything personal. `actor` is staff and `subjectId` is an
 * opaque identifier, both safe; a customer's name is not, and there is no parameter here that
 * would take one — `/api/audit` has no `q` and no name search at all.
 *
 * ## The three reason states, which are the thing this screen exists to get right
 *
 * `reasonText: null` means two different things and the row says which. With
 * `hasReasonText: true` it is "a reason was recorded, you may not read it" — §12.2 gives
 * `audit.read` as **M** to ADMIN and **R** to OWNER, and no button, no step-up and no second
 * request changes that, so there is no affordance beside it. With `hasReasonText: false` it is
 * "no free text on this row", which is still not "no reason was given": every row carries a
 * `reasonCode`, and the 90-day sweep nulls the prose while the row lives 730 days. An empty
 * cell would state the one thing that is definitely false.
 *
 * ## Paging is keyset on `seq`, and Previous is the CLIENT'S memory
 *
 * The API mints an opaque `{"seq": n}` cursor and takes it back verbatim; there is no page
 * number, no offset and no previous cursor on the wire, so Previous is a stack this component
 * keeps. There is also **no `total`** — `AuditPageMeta` carries a cursor and nothing else — so
 * the range label never says "of N". When this tab did not walk to the page it is on, it falls
 * back to the sequence span the rows themselves carry, which is a fact rather than an invented
 * ordinal.
 *
 * ## Two things are surfaced that a table would rather drop
 *
 * `fieldNames` and `recordCount` are the blast radius of a read — names only, never values
 * (§12.4), and a count in RECORDS, which is what the reveal budget is denominated in. A null
 * count is "not recorded" and never `0`. And `chainHmac`, the tamper-evidence seal, is
 * shortened rather than dumped: see `SEAL_EXPLANATION` for why sixty-four hex characters in a
 * cell is a table that no longer answers the question it was opened for.
 *
 * ## What this screen deliberately does not do
 *
 * There is **no step-up prompt on this surface, ever.** Both routes resolve to `check_role`
 * with no subject to scope a step-up against, so a `STEP_UP_REQUIRED` from either is a server
 * bug and a password prompt answering it would be a loop the operator cannot win — it renders
 * as an ordinary refusal. There is **no role gate** either: the server's 403 is the answer, and
 * it renders as a denial with no retry button rather than as a screen this console decided not
 * to draw. And destructive actions get no row highlight, because `DataTable` reserves its one
 * row treatment for the active row — a severity tint sharing that channel would say "selected"
 * to half the readers and "dangerous" to the other half.
 */

/* -------------------------------------------------------------------------- */
/* Copy that is load-bearing                                                   */
/* -------------------------------------------------------------------------- */

/** Why the subtitle and the pager never say "of N". */
/* `audit.noTotalNote`, `audit.hints.actor` and `audit.hints.subjectId` carry these now. */

/** What `actor` really matches, which is not what a free-text box usually means. */


/** `subjectId` is pasted, not typed, and it is not a person. */


/* -------------------------------------------------------------------------- */
/* URL state                                                                   */
/* -------------------------------------------------------------------------- */

/** Ties the Filters button's `aria-controls` to the panel it discloses. */
const FILTER_PANEL_ID = "audit-filters";

const PARAM = {
  actor: "actor",
  action: "action",
  subjectType: "subjectType",
  subjectId: "subjectId",
  outcome: "outcome",
  from: "from",
  to: "to",
  cursor: "cursor",
} as const;

interface UrlState {
  readonly actor: string | null;
  readonly action: readonly AuditAction[];
  readonly subjectType: AuditSubjectType | null;
  readonly subjectId: string | null;
  readonly outcome: readonly AuditOutcome[];
  readonly from: string | null;
  readonly to: string | null;
  /** Paging, not a filter. */
  readonly cursor: string | null;
}

const EMPTY_STATE: UrlState = {
  actor: null,
  action: [],
  subjectType: null,
  subjectId: null,
  outcome: [],
  from: null,
  to: null,
  cursor: null,
};

function readString(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Enum parameters are validated against our own vocabulary and unknown members DROPPED.
 *
 * `action` and `outcome` are typed enums server-side, so an unknown value is a 422 for the
 * whole request — one hand-edited character in a pasted link would blank the table rather than
 * ignore one chip. `actor`, `subjectId` and the two instants are NOT validated here for the
 * opposite reason: the server's 422 names the parameter, and that is a better answer than this
 * screen silently widening a filter somebody wrote on purpose.
 *
 * `subjectType` is validated even though the server does not: the column can only ever hold one
 * of `SUBJECT_TYPES`, so a value outside it is not a filter the server would honour differently
 * — it is a guaranteed empty page wearing a filter's clothes.
 */
function readEnums<T extends string>(
  params: URLSearchParams,
  name: string,
  values: readonly T[],
): readonly T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of params.getAll(name)) {
    const member = values.find((value) => value === raw);
    if (member === undefined || seen.has(member)) continue;
    seen.add(member);
    out.push(member);
  }
  return out;
}

function readUrlState(params: URLSearchParams): UrlState {
  return {
    actor: readString(params, PARAM.actor),
    action: readEnums(params, PARAM.action, AUDIT_ACTION_VALUES),
    subjectType: readEnums(params, PARAM.subjectType, AUDIT_SUBJECT_TYPE_VALUES)[0] ?? null,
    subjectId: readString(params, PARAM.subjectId),
    outcome: readEnums(params, PARAM.outcome, AUDIT_OUTCOME_VALUES),
    from: readString(params, PARAM.from),
    to: readString(params, PARAM.to),
    cursor: readString(params, PARAM.cursor),
  };
}

/** An absent filter writes NO parameter — `?actor=` is a filter, not the absence of one. */
function writeUrlState(state: UrlState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.actor !== null) params.set(PARAM.actor, state.actor);
  for (const action of state.action) params.append(PARAM.action, action);
  if (state.subjectType !== null) params.set(PARAM.subjectType, state.subjectType);
  if (state.subjectId !== null) params.set(PARAM.subjectId, state.subjectId);
  for (const outcome of state.outcome) params.append(PARAM.outcome, outcome);
  if (state.from !== null) params.set(PARAM.from, state.from);
  if (state.to !== null) params.set(PARAM.to, state.to);
  if (state.cursor !== null) params.set(PARAM.cursor, state.cursor);
  return params;
}

/** Paging is not a filter, and counting it would misreport an empty page. */
function activeFilterCount(state: UrlState): number {
  return (
    (state.actor === null ? 0 : 1) +
    (state.action.length === 0 ? 0 : 1) +
    (state.subjectType === null ? 0 : 1) +
    (state.subjectId === null ? 0 : 1) +
    (state.outcome.length === 0 ? 0 : 1) +
    (state.from === null ? 0 : 1) +
    (state.to === null ? 0 : 1)
  );
}

/* -------------------------------------------------------------------------- */
/* Keyset paging                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One tab's memory of a keyset walk.
 *
 * The cursor is `base64url({"seq": n})` and means "rows strictly below this seq". It mints no
 * previous cursor and accepts no page index, so both "go back" and "which page is this" have to
 * be remembered on the client or not offered at all — and a "Page 3 of 12" invented from a row
 * count would be a control whose first use is a jump to a page that cannot be addressed.
 */
interface Walk {
  /** The cursor of the page this walk describes. `null` is page one. */
  readonly cursor: string | null;
  /** The cursors of the pages before it, oldest first. Its length is the page ordinal. */
  readonly stack: readonly (string | null)[];
  /** False once a page was reached by a route this walk did not take — a pasted link. */
  readonly isOrdinalKnown: boolean;
}

const FIRST_PAGE_WALK: Walk = { cursor: null, stack: [], isOrdinalKnown: true };

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly hint: string;
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on. The CODE decides, not the status: a 403
 * is three different facts (`FORBIDDEN`, `CSRF_REJECTED`, `ORIGIN_REJECTED`) with three
 * different remedies, and only one of them is about this operator's role.
 *
 * `null` for `REQUEST_ABORTED`, which must render as nothing at all — it is a request this
 * screen cancelled on purpose.
 *
 * `STEP_UP_REQUIRED` has its own branch here and it is not a prompt. Neither of these routes
 * asks for a step-up — the guard resolves to `check_role` and there is no subject to scope one
 * against — so if one ever arrives it is a server-side fault, and a password box offering to
 * answer it would be a loop with no winning move.
 */
function noteFor(error: AdminQueryError, subject: string, t: Translate): NoteCopy | null {
  const hint = `${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`;

  if (error.code === CLIENT_ERROR_CODES.aborted) return null;

  if (error.code === "UNAUTHENTICATED" || error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("audit.notes.sessionEndedMessage"),
      hint,
      canRetry: false,
    };
  }

  if (error.code === "ORIGIN_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.originTitle"),
      message: t("errors.query.originMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.code === "STEP_UP_REQUIRED") {
    return {
      tone: "error",
      title: t("errors.query.stepUpTitle", { subject }),
      message: t("audit.notes.stepUpMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 403) {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("audit.notes.forbiddenMessage"),
      hint,
      canRetry: false,
    };
  }

  if (error.code === CLIENT_ERROR_CODES.schemaDrift) {
    const paths = (error.issues ?? []).map((issue) => issue.path).join(", ");
    return {
      tone: "error",
      title: t("errors.query.driftTitle", { subject }),
      message:
        paths === ""
          ? error.message
          : t("errors.query.driftMessage", { message: error.message, paths }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("errors.query.refusedFiltersTitle", { subject }),
      message: t("audit.notes.refusedFiltersMessage", { message: error.message }),
      hint,
      canRetry: false,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("errors.query.offlineTitle", { subject }),
      message: error.message,
      hint,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: t("errors.query.failedTitle", { subject }),
    message: error.message,
    hint,
    canRetry: true,
  };
}

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

/** Identifiers and machine values, read character by character and pasted into tickets. */
const MONO_CLASS = "font-mono text-[12px] leading-4";

export function AuditScreen(): JSX.Element {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readUrlState(searchParams), [searchParams]);
  const filterCount = activeFilterCount(state);

  /**
   * The walk this tab has actually made. The API mints no previous cursor, so Previous is this
   * component's memory and nothing else.
   *
   * `cursor` records which page the walk describes, so a cursor that arrives from anywhere else
   * — a pasted link, the Back button, a hand-edited URL — is detected rather than assumed to be
   * the next step of this walk.
   */
  const [walk, setWalk] = useState<Walk>(() => ({
    cursor: state.cursor,
    stack: [],
    // A load with no cursor is page one. A load WITH one is a page whose ordinal is carried
    // only by the opaque cursor, which this tab will not guess at.
    isOrdinalKnown: state.cursor === null,
  }));
  const [isPanelOpen, setIsPanelOpen] = useState(() => filterCount > 0);

  const apply = useCallback(
    (next: UrlState, options: { readonly push: boolean }) => {
      setSearchParams(writeUrlState(next), { replace: !options.push });
    },
    [setSearchParams],
  );

  /**
   * Any filter edit: back to page one, and the walked cursors go with the old question.
   *
   * `Omit<…, "cursor">` on the patch makes "a filter change that keeps the cursor" a compile
   * error rather than a page of the previous question's rows under the new chips.
   */
  const patchFilters = useCallback(
    (partial: Partial<Omit<UrlState, "cursor">>) => {
      setWalk(FIRST_PAGE_WALK);
      apply({ ...state, ...partial, cursor: null }, { push: false });
    },
    [apply, state],
  );

  const clearFilters = useCallback(() => {
    setWalk(FIRST_PAGE_WALK);
    apply(EMPTY_STATE, { push: false });
  }, [apply]);

  const filters = useMemo<AuditFilters>(
    () => ({
      actor: state.actor,
      action: state.action,
      subjectType: state.subjectType,
      subjectId: state.subjectId,
      outcome: state.outcome,
      from: state.from,
      to: state.to,
    }),
    [state],
  );

  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: state.cursor }),
    [state.cursor],
  );

  const entries = useAuditEntries(filters, page);
  const verification = useChainVerify();

  useSessionGuard([entries.error, verification.error]);

  /* Memoised on the response rather than read inline: the range label needs the FIRST and LAST
     rows, not just a count, and a fresh `[]` each render would re-run it on every render. */
  const items = useMemo<readonly AuditEntryView[]>(
    () => entries.data?.items ?? [],
    [entries.data],
  );
  const nextCursor = entries.data === undefined ? null : nextCursorOf(entries.data);

  /** Whether `walk` still describes the page on screen. See the `Walk` note above. */
  const isWalkCurrent = walk.cursor === state.cursor;
  const hasPrev = isWalkCurrent && walk.stack.length > 0;
  /** How many pages precede this one, or `null` when this tab did not walk here. */
  const pageOrdinal = isWalkCurrent && walk.isOrdinalKnown ? walk.stack.length : null;

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    setWalk((previous) =>
      previous.cursor === state.cursor
        ? {
            cursor: nextCursor,
            stack: [...previous.stack, state.cursor],
            isOrdinalKnown: previous.isOrdinalKnown,
          }
        : /* The page we are leaving was not reached through this walk, so its ordinal is
             unknown and so is every ordinal after it. Previous still works — we know the
             cursor we came from — but the range label stops counting. */
          { cursor: nextCursor, stack: [state.cursor], isOrdinalKnown: false },
    );
    apply({ ...state, cursor: nextCursor }, { push: false });
  }, [apply, nextCursor, state]);

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    const previous = walk.stack[walk.stack.length - 1] ?? null;
    setWalk({
      cursor: previous,
      stack: walk.stack.slice(0, -1),
      isOrdinalKnown: walk.isOrdinalKnown,
    });
    apply({ ...state, cursor: previous }, { push: false });
  }, [apply, hasPrev, state, walk]);

  const zoneLabel = useMemo(() => localZoneLabel(), []);

  /* ---------------------------------------------------------------------- */
  /* Chips                                                                   */
  /* ---------------------------------------------------------------------- */

  const chips = useMemo<readonly FilterChip[]>(() => {
    const out: FilterChip[] = [];

    if (state.actor !== null) {
      out.push({
        id: PARAM.actor,
        field: t("audit.chips.actor"),
        /* The value verbatim: it is an id or a username somebody pasted, and humanising an
           identifier is how a chip stops describing the filter it removes. */
        value: state.actor,
        onRemove: () => {
          patchFilters({ actor: null });
        },
      });
    }
    if (state.action.length > 0) {
      out.push({
        id: PARAM.action,
        field: t("audit.chips.action"),
        value: state.action.join(" or "),
        onRemove: () => {
          patchFilters({ action: [] });
        },
      });
    }
    if (state.outcome.length > 0) {
      out.push({
        id: PARAM.outcome,
        field: t("audit.chips.outcome"),
        value: state.outcome.map((outcome) => AUDIT_OUTCOME_LABELS[outcome]).join(" or "),
        onRemove: () => {
          patchFilters({ outcome: [] });
        },
      });
    }
    if (state.subjectType !== null) {
      out.push({
        id: PARAM.subjectType,
        field: t("audit.chips.subjectType"),
        value: subjectTypeLabel(state.subjectType),
        onRemove: () => {
          patchFilters({ subjectType: null });
        },
      });
    }
    if (state.subjectId !== null) {
      out.push({
        id: PARAM.subjectId,
        field: t("audit.chips.subjectId"),
        value: state.subjectId,
        onRemove: () => {
          patchFilters({ subjectId: null });
        },
      });
    }
    if (state.from !== null) {
      out.push({
        id: PARAM.from,
        field: t("audit.chips.recordedFrom"),
        value: `${splitTimestamp(state.from).full} ${zoneLabel}`,
        onRemove: () => {
          patchFilters({ from: null });
        },
      });
    }
    if (state.to !== null) {
      out.push({
        id: PARAM.to,
        /* "through", not "before": this window includes its upper bound. */
        field: t("audit.chips.recordedThrough"),
        value: `${splitTimestamp(state.to).full} ${zoneLabel}`,
        onRemove: () => {
          patchFilters({ to: null });
        },
      });
    }
    return out;
  }, [patchFilters, state, t, zoneLabel]);

  /* ---------------------------------------------------------------------- */
  /* Columns                                                                 */
  /* ---------------------------------------------------------------------- */

  const columns = useMemo<readonly Column<AuditEntryView>[]>(
    () => [
      {
        key: "at",
        header: t("audit.table.recorded", { zone: zoneLabel }),
        width: "9.5rem",
        render: (row) => {
          const at = splitTimestamp(row.at);
          return (
            <div className="flex flex-col">
              <span>{at.date}</span>
              <span className={CELL_SECONDARY_CLASS}>{at.time}</span>
            </div>
          );
        },
      },
      {
        key: "seq",
        header: t("audit.table.seq"),
        width: "8.5rem",
        render: (row) => {
          const seal = shortenSeal(row.chainHmac);
          return (
            <div className="flex flex-col">
              <span>{formatSeq(row.seq)}</span>
              {/* The seal rides here rather than in a column of its own: it is a value to
                  compare against an anchor line, and it belongs beside the sequence that
                  anchor names. The full 64 hex characters are in the title. */}
              <span
                className={cn(CELL_SECONDARY_CLASS, "font-mono")}
                title={`${seal.full} — ${SEAL_EXPLANATION}`}
              >
                {seal.short}
              </span>
            </div>
          );
        },
      },
      {
        key: "actor",
        header: t("audit.table.actor"),
        width: "11rem",
        render: (row) => (
          <div className="flex flex-col">
            {/* Staff, not a customer: the username is safe in the clear, and it is a SNAPSHOT
                — a rename since then did not rewrite this row. */}
            <span className="break-words">{row.actorUsername}</span>
            <span className={CELL_SECONDARY_CLASS}>
              {/* The role AT THE TIME, and the address it came from — one line, because a
                  third stacked line turns every row into three. */}
              {ADMIN_ROLE_LABELS[row.actorRole]}
              {row.ip === null ? "" : ` · ${row.ip}`}
            </span>
          </div>
        ),
      },
      {
        key: "action",
        header: t("audit.table.action"),
        width: "11rem",
        render: (row) => (
          /* Verbatim. The values are dotted and abbreviated and they are not slugs — an
             unknown one renders as itself rather than as a blank cell. */
          <span className={cn(MONO_CLASS, "break-all")}>{row.action}</span>
        ),
      },
      {
        key: "outcome",
        header: t("audit.table.outcome"),
        width: "10rem",
        render: (row) => (
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={AUDIT_OUTCOME_TONES[row.outcome]} title={AUDIT_OUTCOME_MEANINGS[row.outcome]}>
              {AUDIT_OUTCOME_LABELS[row.outcome]}
            </Badge>
            {row.errorCode === null ? null : (
              <span className={cn(CELL_SECONDARY_CLASS, "font-mono break-all")}>
                {row.errorCode}
              </span>
            )}
          </div>
        ),
      },
      {
        key: "subject",
        header: t("audit.table.subject"),
        width: "11rem",
        render: (row) => {
          const subject = row.subjectId === null ? null : shortenId(row.subjectId);
          return (
            <div className="flex flex-col">
              <span>{subjectTypeLabel(row.subjectType)}</span>
              {subject === null ? (
                <span className={CELL_SECONDARY_CLASS}>{NO_SUBJECT}</span>
              ) : (
                /* An opaque identifier, and rendered as one. It is a UUID, a Telegram id or a
                   config version — never a person's name, which this column cannot hold. */
                <span
                  className={cn(CELL_SECONDARY_CLASS, "font-mono")}
                  title={subject.isShortened ? subject.full : undefined}
                >
                  {subject.short}
                </span>
              )}
              {row.configVersion === null ? null : (
                <span className={CELL_SECONDARY_CLASS}>
                  {`settings v${String(row.configVersion)}`}
                </span>
              )}
            </div>
          );
        },
      },
      {
        key: "exposure",
        header: t("audit.table.exposure"),
        width: "12rem",
        render: (row) => (
          <div className="flex flex-col">
            {row.recordCount === null ? (
              /* Not "0". The reveal budget counts RECORDS, and a null read as zero would
                 understate exposure on the one screen that measures it. */
              <span className={CELL_SECONDARY_CLASS} title={RECORD_COUNT_ABSENT}>
                {RECORD_COUNT_ABSENT_LABEL}
              </span>
            ) : (
              <span>
                {t("audit.recordCount", { count: formatCount(row.recordCount) })}
              </span>
            )}
            {row.fieldNames === null || row.fieldNames.length === 0 ? (
              <span className={CELL_SECONDARY_CLASS}>{NO_FIELDS_NAMED}</span>
            ) : (
              /* NAMES, never values (§12.4). Nothing personal has ever been in this array. */
              <span className={cn(CELL_SECONDARY_CLASS, "font-mono break-words")}>
                {row.fieldNames.join(", ")}
              </span>
            )}
          </div>
        ),
      },
      {
        key: "reason",
        header: t("audit.table.reason"),
        width: "17rem",
        render: (row) => <ReasonCell entry={row} />,
      },
      {
        key: "correlation",
        header: t("audit.table.correlation"),
        width: "9rem",
        render: (row) => {
          if (row.correlationId === null) return <span className={CELL_SECONDARY_CLASS}>{EMPTY_VALUE}</span>;
          const id = shortenId(row.correlationId);
          return (
            /* What joins this row to the bot's and the worker's log lines — the value somebody
               greps for, so it is shown as an id and not as a word. */
            <span className={MONO_CLASS} title={id.isShortened ? id.full : undefined}>
              {id.short}
            </span>
          );
        },
      },
    ],
    [t, zoneLabel],
  );

  /* ---------------------------------------------------------------------- */
  /* Counts and the range label                                             */
  /* ---------------------------------------------------------------------- */

  const subtitle = useMemo(() => {
    if (entries.data === undefined) {
      return entries.error === null ? t("audit.subtitles.reading") : t("audit.subtitles.failed");
    }
    const note = t("audit.noTotalNote");
    return filterCount === 0
      ? t("audit.subtitleAll", { note })
      : t("audit.subtitleFiltered", { note });
  }, [entries.data, entries.error, filterCount, t]);

  const rangeLabel = useMemo(() => {
    if (entries.isPlaceholderData) {
      /* The rows on screen belong to the PREVIOUS request and the walk has already moved on,
         so any range composed now would number one page's rows with another's positions. */
      return t("audit.range.loadingNext");
    }
    if (entries.data === undefined) {
      return entries.error === null ? t("audit.range.loading") : t("audit.range.noneLoaded");
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return t("audit.range.noneOnPage");
    if (pageOrdinal === null) {
      /* This tab did not walk here, so it does not know this page's ordinal — but the rows
         carry their own sequence numbers, and a real span beats an invented position. */
      return t("audit.range.spanned", {
        count: formatCount(items.length),
        first: formatSeq(first.seq),
        last: formatSeq(last.seq),
      });
    }
    const start = pageOrdinal * DEFAULT_PAGE_LIMIT + 1;
    /* No "of N": `AuditPageMeta` carries a cursor and no count, and a total invented from a
       page length would be the one number on this screen nobody could check. */
    return t("audit.range.numbered", {
      start: formatCount(start),
      end: formatCount(start + items.length - 1),
    });
  }, [entries.data, entries.error, entries.isPlaceholderData, items, pageOrdinal, t]);

  const listNote =
    entries.error === null ? null : noteFor(entries.error, t("audit.subjects.log"), t);
  const verifyNote =
    verification.error === null
      ? null
      : noteFor(verification.error, t("audit.subjects.verdict"), t);

  return (
    <main className="py-6">
      {/* The 1392px content box the shell's screens are composed against. The page ground and
          the min-height belong to `AppShell`; a second one here would paint over the rail's. */}
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("audit.title")}
          subtitle={subtitle}
          actions={
            <ToolbarButton
              icon={<SlidersHorizontal className="h-5 w-5" strokeWidth={1.75} />}
              ariaExpanded={isPanelOpen}
              ariaControls={FILTER_PANEL_ID}
              onClick={() => {
                setIsPanelOpen((open) => !open);
              }}
            >
              {filterCount === 0
                ? t("common.filters")
                : t("common.filtersCount", { count: filterCount })}
            </ToolbarButton>
          }
        />

        {/* Above the table on purpose: whether the log still says what it said is the question
            that decides how much anything below is worth. */}
        <ChainVerifyPanel
          verification={verification.data}
          /* When this browser received the verdict. The wire carries no timestamp, so the
             query's own is the only instant there is — and the panel needs one, because the
             verdict never expires on its own and its sentence is written in the present. */
          checkedAt={verification.dataUpdatedAt}
          isPending={verification.isPending}
          isFetching={verification.isFetching}
          /* The same answer `<ErrorNote>` gets, so one decision drives both controls: a
             refusal that withholds Retry must also stop the recheck, or the button beside the
             note re-fires the refused request and writes a second `permission.denied` row. */
          canRecheck={verifyNote === null || verifyNote.canRetry}
          note={
            verifyNote === null ? undefined : (
              <ErrorNote
                tone={verifyNote.tone}
                title={verifyNote.title}
                message={verifyNote.message}
                hint={verifyNote.hint}
                retryable={verifyNote.canRetry}
                isRetrying={verification.isFetching}
                onRetry={() => {
                  void verification.refetch();
                }}
              />
            )
          }
          onRecheck={() => {
            void verification.refetch();
          }}
        />

        {isPanelOpen ? (
          <FilterPanel id={FILTER_PANEL_ID}>
            <TimeRangeFilter
              from={state.from}
              to={state.to}
              fromInput={isoToLocalInput(state.from)}
              toInput={isoToLocalInput(state.to)}
              toIso={localInputToIso}
              zoneLabel={zoneLabel}
              onChange={(next) => {
                patchFilters(next);
              }}
            />
            <TextFilter
              label={t("audit.chips.actor")}
              value={state.actor}
              placeholder={t("audit.actorPlaceholder")}
              hint={t("audit.hints.actor")}
              onChange={(actor) => {
                patchFilters({ actor });
              }}
            />
            <SingleEnumSelect<AuditSubjectType>
              label={t("audit.chips.subjectType")}
              values={AUDIT_SUBJECT_TYPE_VALUES}
              value={state.subjectType}
              format={(subjectType) => subjectTypeLabel(subjectType)}
              hint={t("audit.hints.subjectType")}
              onChange={(subjectType) => {
                patchFilters({ subjectType });
              }}
            />
            <TextFilter
              label={t("audit.chips.subjectId")}
              value={state.subjectId}
              maxLength={MAX_SUBJECT_ID_CHARS}
              placeholder="0f5c…"
              hint={t("audit.hints.subjectId")}
              onChange={(subjectId) => {
                patchFilters({ subjectId });
              }}
            />
            <EnumToggleGroup<AuditOutcome>
              label={t("audit.chips.outcome")}
              values={AUDIT_OUTCOME_VALUES}
              selected={state.outcome}
              format={(outcome) => AUDIT_OUTCOME_LABELS[outcome]}
              describe={(outcome) => AUDIT_OUTCOME_MEANINGS[outcome]}
              onChange={(outcome) => {
                patchFilters({ outcome });
              }}
            />
            <GroupedEnumToggles<AuditAction>
              label={t("audit.chips.action")}
              groups={AUDIT_ACTION_GROUPS}
              selected={state.action}
              format={(action) => action}
              hint={t("audit.hints.action")}
              /* Forty-one toggles want the whole panel width rather than one grid cell. */
              className="sm:col-span-2 xl:col-span-3"
              onChange={(action) => {
                patchFilters({ action });
              }}
            />
          </FilterPanel>
        ) : null}

        <FilterChips chips={chips} onClearAll={filterCount === 0 ? undefined : clearFilters} />

        {listNote === null ? null : (
          <ErrorNote
            tone={listNote.tone}
            title={listNote.title}
            message={listNote.message}
            hint={listNote.hint}
            retryable={listNote.canRetry}
            isRetrying={entries.isFetching}
            onRetry={() => {
              void entries.refetch();
            }}
          />
        )}

        <section aria-label="Audit entries" className="flex min-w-0 flex-col gap-3">
          <div
            aria-busy={entries.isPlaceholderData}
            /* A page still loading under NEW filters is the PREVIOUS answer; dimming it says
               so rather than presenting it under the new chips. */
            className={cn("transition-opacity", entries.isPlaceholderData && "opacity-60")}
          >
            <DataTable
              caption={t("audit.tableCaption")}
              columns={columns}
              rows={items}
              getRowKey={(row) => row.id}
              isLoading={entries.isPending}
              skeletonRows={DEFAULT_PAGE_LIMIT}
              emptyMessage={
                entries.error !== null ? (
                  <EmptyState
                    title={t("audit.empty.failedTitle")}
                    message={t("audit.empty.failedMessage")}
                  />
                ) : filterCount > 0 ? (
                  <EmptyState
                    title={t("audit.empty.noMatchTitle")}
                    message={t("audit.empty.noMatchMessage")}
                    action={
                      <ToolbarButton onClick={clearFilters}>
                        {t("common.clearAllFilters")}
                      </ToolbarButton>
                    }
                  />
                ) : (
                  <EmptyState
                    title={t("audit.empty.logEmptyTitle")}
                    message={t("audit.empty.logEmptyMessage")}
                  />
                )
              }
            />
          </div>

          <CursorPager
            rangeLabel={rangeLabel}
            hasPrev={hasPrev}
            hasNext={nextCursor !== null}
            isFetching={entries.isFetching}
            onPrev={goPrev}
            onNext={goNext}
          />
        </section>
      </div>
    </main>
  );
}

/* -------------------------------------------------------------------------- */
/* Parts                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The reason a row carries, in the three states the contract can express.
 *
 * The code is always there and is always the reason; the ticket reference and the free text are
 * both optional, and the free text has two distinct absences. Nothing here draws an affordance
 * beside the withheld state: unmasking is a property of the ROLE, so a button there could only
 * ever fail, and a button that always fails is worse than no button.
 */
function ReasonCell({ entry }: { readonly entry: AuditEntryView }): JSX.Element {
  const { t } = useI18n();
  const disclosure = reasonDisclosure(entry);

  return (
    <div className="flex flex-col gap-[2px]">
      <span>{t(REVEAL_REASON_KEYS[entry.reasonCode])}</span>
      {entry.reasonRef === null ? null : (
        <span className={cn(CELL_SECONDARY_CLASS, "font-mono break-all")}>{entry.reasonRef}</span>
      )}
      {disclosure.kind === "text" ? (
        /* The operator's own prose. It is the one field somebody could have typed a customer's
           name into, so it is rendered as written — never trimmed into a preview that changes
           what it says, and never in a tooltip an investigation cannot read. */
        <span className={cn(CELL_SECONDARY_CLASS, "whitespace-pre-wrap break-words")}>
          {disclosure.text}
        </span>
      ) : disclosure.kind === "withheld" ? (
        <span className={CELL_SECONDARY_CLASS}>{REASON_WITHHELD_LABEL}</span>
      ) : (
        <span className={CELL_SECONDARY_CLASS} title={REASON_SWEEP_CAVEAT}>
          {NO_REASON_TEXT_LABEL}
        </span>
      )}
    </div>
  );
}
