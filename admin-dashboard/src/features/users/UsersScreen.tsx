/**
 * `/users` — the directory: who is in the system, and what standing are they in?
 *
 * ## The search box matches the Telegram id and NOTHING else
 *
 * `UserFilters.search` (src/bayram/db/admin/users.py) is a substring of `telegram_user_id`. That
 * is a privacy decision, not an unfinished feature: every other free-text column this list can
 * reach — `telegram_username`, `first_name`, `last_name`, `phone_e164` — is masked at all four
 * roles, so a `LIKE '%…%'` over any of them would let an operator with no reveal cell confirm a
 * customer's name three characters at a time, with no step-up, no budget and no audit row.
 * `SEARCH_LABEL`, `SEARCH_PLACEHOLDER`, `SEARCH_HINT` and the no-match copy are the only places
 * this box is described, and none of them may name a person or a person-shaped noun — only
 * the id. An operator who believes a customer is findable by who they are reads an empty
 * result as "this customer does not exist".
 *
 * ## No reveal affordance in a row
 *
 * Every personal column here renders the MASKED twin the server sent, and that is where it
 * stops. A `<MaskedValue>` per row would put fifty Reveal buttons on one screen, and a reveal
 * costs a step-up, a budget unit and an audit row naming one operator, one subject and one
 * reason — a screenful of them invites exactly the sweep the budget exists to prevent. Reveal
 * belongs on the detail screen, against one subject, with a reason typed for that subject.
 * (The masked Telegram id is not even a `RevealField`: nothing is behind it to ask for.)
 *
 * ## Three states in the credits column
 *
 * `creditBalance` is `null` when `credit_accounts` holds no row — never metered — which is a
 * different fact from a balance of `0`, i.e. metered down to nothing. Rendering the first as
 * the second says the opposite of what is true, so the column prints "never metered". The
 * `hasBalance` filter draws the same distinction: its `false` covers BOTH of the other shapes,
 * which is why its hint says so rather than reading "no credits".
 *
 * ## "Last order", never "last seen"
 *
 * `UserView` carries no `lastSeenAt`. `lastOrderAt` is `MAX(orders.created_at)` — a
 * measurement of purchases, not of presence — so the column is headed for what it is. The same
 * goes for `accountCreatedAt`: three writers create a `users` row (an order, answering the
 * language question, and `db/credits.py::touch` on any inbound update), so for a row created
 * since that shipped it means FIRST CONTACT and for older rows the first order. The header
 * title says both rather than picking the flattering one.
 *
 * ## Paging is a walk, and the walk is remembered here
 *
 * The API mints an opaque `nextCursor` and no previous cursor, and there is no offset and no
 * page number. So Previous is this screen's own bookkeeping: a trail of the stops already
 * visited, held in component state and dropped the moment a filter changes. The trail is only
 * trusted while its head matches the cursor in the URL — a pasted link or a Back lands with a
 * cursor and no trail, and then the pager honestly offers no Previous and the range label
 * stops claiming absolute positions rather than inventing them.
 *
 * Filters and the cursor live in the query string so a filtered view is linkable and survives
 * a reload. Nothing else goes there: no name, no revealed plaintext. The Telegram id appears
 * in the URL only when a row is opened, because it is the key `/api/users/{id}` itself is
 * addressed by.
 *
 * ## Two filters, one list — and the second one is a document
 *
 * The four quick controls in the panel are `/api/users` PARAMETERS. `?segment=` is a
 * DOCUMENT — the same one the campaign wizard freezes, the same one `/api/segments/preview`
 * counts — and the server ANDs it with the parameters rather than replacing them, which is
 * what keeps every bookmark an operator already holds working. Both are drawn as chips in one
 * row, and "Filters · N" counts the segment's LEAF RULES at every depth, because "Filters · 1"
 * over a nine-clause audience is the exact lie the chip row exists to prevent.
 *
 * A campaign audience is the document and nothing else, so "Message these users" hands the
 * wizard the token VERBATIM and refuses while a quick filter is on: `q` is a substring of the
 * Telegram id and no registry field can express it, so a hand-off under an active chip would
 * freeze a population that is not the one on screen.
 *
 * ## The ordering has exactly one home
 *
 * `?sort=`/`?sortDir=` — where the server reads it (`build_query`, routers/users.py), and
 * where both the column headings and the builder's own sort control write. A document that
 * arrives carrying its own `sort` has it lifted out into those two parameters on the way in,
 * and an explicit `?sort=` overrides it, exactly as the server does. Two homes for one
 * ordering is how a table ends up sorted by something no control on screen is showing.
 *
 * Only the registry's `sortable` keys get a heading control. `last_activity_at` is filterable
 * and deliberately not sortable, and no free-text column is either — a sort publishes a total
 * order over identified accounts, which is a different disclosure from a predicate. And
 * `withTotal` is dropped beside a sort on a computed column, because the server refuses that
 * pair by name: the count is what goes, since the sort is what the operator just pressed.
 */

import { Megaphone } from "lucide-react";
import { useCallback, useMemo, useState, type JSX, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CLIENT_ERROR_CODES } from "@/api/client";
import { MAX_SEARCH_CHARS } from "@/api/constants";
import { DEFAULT_PAGE_LIMIT, nextCursorOf, type PageRequest } from "@/api/pagination";
import {
  segmentFieldIndex,
  type SegmentFieldView,
  type SegmentFieldsView,
  type SegmentPreviewView,
} from "@/api/segments";
import { LANGUAGE_VALUES, type Language, type UserView, type UsersFilters } from "@/api/users";
import { broadcastNewPath, userDetailPath } from "@/app/paths";
import { Avatar } from "@/components/Avatar";
import { Badge } from "@/components/Badge";
import { CursorPager } from "@/components/CursorPager";
import {
  CELL_SECONDARY_CLASS,
  DataTable,
  type Column,
  type ColumnSort,
} from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { FilterChips, type FilterChip } from "@/components/FilterChips";
import {
  SegmentBuilder,
  buildSegmentChips,
  segmentFilterCount,
  useSegmentFields,
  useSegmentPreview,
  withSort,
} from "@/components/SegmentBuilder";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import {
  DateRangeFields,
  EnumToggleGroup,
  SearchField,
  TriStateSelect,
} from "@/features/users/filterControls";
import { useUsers } from "@/features/users/useUsers";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import type { AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import {
  EMPTY_SEGMENT,
  decodeSegment,
  isSegmentEmpty,
  segmentToken,
  type Segment,
  type SortDirection,
} from "@/lib/segmentCodec";
import { useCanWriteBroadcasts } from "@/lib/rbac";
import { useSessionGuard } from "@/state/useSessionGuard";

/* -------------------------------------------------------------------------- */
/* Copy that is load-bearing                                                   */
/* -------------------------------------------------------------------------- */

/*
 * The copy the privacy rule pins to the search box — its accessible name, its placeholder and
 * the reason underneath — is `users.searchLabel`, `users.searchPlaceholder` and
 * `users.searchHint`, with the empty page's `users.noMatchHint` beside them. They were
 * constants here so the four sat together with the control they describe; the catalogue keeps
 * that property and adds two more languages to it. Before rewording any of them, read the
 * note on `SearchFieldSlot`: none of the four may become a promise to find a person.
 *
 * `LANGUAGE_LABEL` is `@/lib/languageLabel` now, shared with the three other screens that had
 * each grown their own copy of the same four members.
 */

/* -------------------------------------------------------------------------- */
/* URL state                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The direction a fresh sort opens in, and the one the server assumes.
 *
 * Descending, because every sortable key here is a count or an instant and the interesting end
 * of both is the big one — the customer who ordered most, the account that moved last.
 */
const DEFAULT_SORT_DIRECTION: SortDirection = "desc";

interface UsersUrlState {
  readonly q: string | null;
  readonly isBlocked: boolean | null;
  readonly hasBalance: boolean | null;
  readonly uiLanguage: readonly Language[];
  readonly from: string | null;
  readonly to: string | null;
  /**
   * The advanced segment, DECODED — the same document the wizard freezes, held here as an
   * object and written back to `?segment=` as `encodeSegment`'s bytes.
   *
   * It never carries a `sort`: the ordering lives in `sort`/`sortDir` below, where the server
   * reads it and where a column header can write it. Two homes for one ordering is how a
   * table ends up sorted by something no control on screen is showing.
   */
  readonly segment: Segment;
  /** A registry `sortable` key, or `null` for the default `(created_at, id)` walk. */
  readonly sort: string | null;
  readonly sortDir: SortDirection;
  readonly cursor: string | null;
}

function readText(params: URLSearchParams, name: string): string | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/** `true`/`false`/absent — three answers, and anything else is not one of them. */
function readTriState(params: URLSearchParams, name: string): boolean | null {
  const raw = readText(params, name);
  if (raw === "true") return true;
  if (raw === "false") return false;
  return null;
}

function asLanguage(raw: string): Language | null {
  return LANGUAGE_VALUES.find((value) => value === raw) ?? null;
}

function readLanguages(params: URLSearchParams): readonly Language[] {
  const seen: Language[] = [];
  for (const raw of params.getAll("uiLanguage")) {
    const language = asLanguage(raw.trim());
    // An unknown member would be a 422 naming the parameter, which empties the table and
    // blames a filter the operator cannot see. Dropping it narrows nothing they asked for.
    if (language !== null && !seen.includes(language)) seen.push(language);
  }
  return seen;
}

function readSortDirection(params: URLSearchParams): SortDirection | null {
  const raw = readText(params, "sortDir");
  return raw === "asc" || raw === "desc" ? raw : null;
}

function parseUrlState(params: URLSearchParams): UsersUrlState {
  /*
   * A segment that will not decode is NOT a filter. `decodeSegment` never throws — an
   * over-long, truncated, hand-edited or version-mismatched token is `null` — and `null` here
   * has to render the unfiltered list rather than a blank screen, because the alternative is a
   * pasted link that silently shows nobody and looks exactly like an outage.
   */
  const decoded = decodeSegment(params.get("segment")) ?? EMPTY_SEGMENT;
  /*
   * `?sort=` OVERRIDES the document's own ordering — the same precedence `build_query`
   * applies server-side (routers/users.py), so the rows the URL walks and the rows this screen
   * thinks it asked for are ordered by one key. A document that arrived carrying a sort and no
   * `?sort=` beside it keeps its ordering, lifted out into the two parameters that own it.
   */
  const explicitKey = readText(params, "sort");
  const documentSort = decoded.sort ?? null;
  const key = explicitKey ?? documentSort?.key ?? null;
  const direction =
    explicitKey !== null
      ? (readSortDirection(params) ?? DEFAULT_SORT_DIRECTION)
      : (documentSort?.dir ?? DEFAULT_SORT_DIRECTION);

  return {
    q: readText(params, "q"),
    isBlocked: readTriState(params, "isBlocked"),
    hasBalance: readTriState(params, "hasBalance"),
    uiLanguage: readLanguages(params),
    // Kept verbatim: an instant this screen did not mint is still the operator's question, and
    // a non-RFC-3339 value is a 422 that names `from`, which is more use than a silent repair.
    from: readText(params, "from"),
    to: readText(params, "to"),
    segment: withSort(decoded, null),
    sort: key,
    sortDir: direction,
    cursor: readText(params, "cursor"),
  };
}

function writeUrlState(state: UsersUrlState): URLSearchParams {
  const params = new URLSearchParams();
  // Absent, `true` and `false` are three different questions; only the last two are written.
  if (state.q !== null) params.set("q", state.q);
  if (state.isBlocked !== null) params.set("isBlocked", String(state.isBlocked));
  if (state.hasBalance !== null) params.set("hasBalance", String(state.hasBalance));
  for (const language of state.uiLanguage) params.append("uiLanguage", language);
  if (state.from !== null) params.set("from", state.from);
  if (state.to !== null) params.set("to", state.to);
  // `segmentToken` is `null` for a document that narrows nothing, so an empty builder leaves no
  // parameter behind — the plain list is one URL and one cache key, not four spellings of one.
  const segment = segmentToken(state.segment);
  if (segment !== null) params.set("segment", segment);
  // The direction rides on the key and is never written alone: on its own it would name a
  // direction for an ordering nobody chose.
  if (state.sort !== null) {
    params.set("sort", state.sort);
    params.set("sortDir", state.sortDir);
  }
  if (state.cursor !== null) params.set("cursor", state.cursor);
  return params;
}

/**
 * How many filters are narrowing the list.
 *
 * The cursor is a position, not a filter, and the SORT is an ordering — neither counts. The
 * segment counts as its LEAF RULES at every depth, never as the one `?segment=` key: "Filters ·
 * 1" over a nine-clause audience is the exact lie the chip row exists to prevent.
 */
function activeFilterCount(state: UsersUrlState): number {
  return (
    (state.q === null ? 0 : 1) +
    (state.isBlocked === null ? 0 : 1) +
    (state.hasBalance === null ? 0 : 1) +
    (state.uiLanguage.length === 0 ? 0 : 1) +
    (state.from === null ? 0 : 1) +
    (state.to === null ? 0 : 1) +
    segmentFilterCount(state.segment)
  );
}

/**
 * Whether any of the six quick filters is on.
 *
 * It decides one thing: whether "Message these users" may hand this view to the wizard. The
 * quick filters are `/api/users` parameters and the campaign audience is a segment DOCUMENT —
 * `q` is a substring of the Telegram id, which no registry field can express at all — so a
 * hand-off under an active chip would freeze an audience that is not the one on screen.
 */
function hasQuickFilters(state: UsersUrlState): boolean {
  return (
    state.q !== null ||
    state.isBlocked !== null ||
    state.hasBalance !== null ||
    state.uiLanguage.length > 0 ||
    state.from !== null ||
    state.to !== null
  );
}

/* -------------------------------------------------------------------------- */
/* Panel geometry                                                              */
/* -------------------------------------------------------------------------- */

/*
 * The advanced section's own heading and its one sentence. Sized to the kit's control label
 * and hint rather than to a page heading: this is a section INSIDE the filter panel, and a
 * 22px title in there would read as a second screen.
 */
const SECTION_HEADING_CLASS =
  "m-0 text-[14px] font-semibold leading-5 tracking-[-0.084px] text-ink-800";
const SECTION_HINT_CLASS = "m-0 max-w-[68ch] text-[12px] font-normal leading-[1.4] text-ink-400";

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

/** Every sentence on this screen, bound to the operator's chosen language. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

const NUMBER_FORMAT = new Intl.NumberFormat();
const RELATIVE_FORMAT = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

function formatCount(value: number): string {
  return NUMBER_FORMAT.format(value);
}

/**
 * A bounded count, said honestly.
 *
 * `isTotalExact` is `false` when the count stopped at `TOTAL_COUNT_CAP`, and `null` when the
 * server did not say — which is not a promise of exactness either. Both read as "at least".
 */
function formatTotal(total: number, isTotalExact: boolean | null, t: Translate): string {
  return isTotalExact === true
    ? formatCount(total)
    : t("users.atLeast", { count: formatCount(total) });
}

const MINUTE_S = 60;
const HOUR_S = 60 * MINUTE_S;
const DAY_S = 24 * HOUR_S;
const MONTH_S = 30 * DAY_S;
const YEAR_S = 365 * DAY_S;

/** "3 days ago". The exact instant rides along in a `title`; this is for scanning. */
function formatRelative(iso: string, t: Translate): string | null {
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  const elapsedS = Math.round((at - Date.now()) / 1000);
  const magnitude = Math.abs(elapsedS);
  if (magnitude < MINUTE_S) return t("common.justNow");
  if (magnitude < HOUR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MINUTE_S), "minute");
  if (magnitude < DAY_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / HOUR_S), "hour");
  if (magnitude < MONTH_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / DAY_S), "day");
  if (magnitude < YEAR_S) return RELATIVE_FORMAT.format(Math.round(elapsedS / MONTH_S), "month");
  return RELATIVE_FORMAT.format(Math.round(elapsedS / YEAR_S), "year");
}

function formatAbsolute(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString();
}

/**
 * The monogram, built from MASKED text only.
 *
 * A letter derived from a revealed name would put plaintext in a place with no audit row and
 * no lifetime. `?` when there is no profile at all — a customer who has spoken to the bot and
 * never shared one is the normal case, not a missing avatar.
 */
function initialsOf(user: UserView): string {
  const first = user.firstNameMasked?.trim().charAt(0) ?? "";
  const last = user.lastNameMasked?.trim().charAt(0) ?? "";
  const initials = `${first}${last}`.trim();
  return initials === "" ? "?" : initials;
}

/* -------------------------------------------------------------------------- */
/* The walk                                                                    */
/* -------------------------------------------------------------------------- */

/** One stop on the keyset walk: the cursor that fetched it, and how many rows preceded it. */
interface PageStop {
  readonly cursor: string | null;
  /** `null` once the walk was joined mid-way — a pasted link knows no offset, and neither do we. */
  readonly offset: number | null;
}

interface Walk extends PageStop {
  /** The stops already visited, newest last. Empty on page one. */
  readonly trail: readonly PageStop[];
}

const FIRST_STOP: Walk = { cursor: null, offset: 0, trail: [] };

/* -------------------------------------------------------------------------- */
/* Failure copy                                                                */
/* -------------------------------------------------------------------------- */

interface NoteCopy {
  readonly tone: NoteTone;
  readonly title: string;
  readonly message: string;
  readonly canRetry: boolean;
}

/**
 * A failed read, as something an operator can act on.
 *
 * Branching is on the CODE, not the status: `FORBIDDEN` is a statement about the role,
 * `ORIGIN_REJECTED` is a deployment fault nobody in the room caused, `SCHEMA_DRIFT` means this
 * bundle and the server disagree about the contract, and a 422 means the filters were refused.
 * None of the four is fixed by asking again, so none of them offers a Retry: a button that
 * always fails is worse than no button, and on a 403 each press writes a `permission.denied`
 * audit row against somebody who did nothing wrong.
 */
function noteFor(error: AdminQueryError, isStale: boolean, t: Translate): NoteCopy {
  const subject = t("users.subject");

  if (error.code === "FORBIDDEN") {
    return {
      tone: "denied",
      title: t("errors.query.forbiddenTitle", { subject }),
      message: t("users.notes.forbiddenMessage"),
      canRetry: false,
    };
  }

  if (error.code === "ORIGIN_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.originTitle"),
      message: t("errors.query.originMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("users.notes.sessionEndedMessage", { message: error.message }),
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
      canRetry: false,
    };
  }

  if (error.status === 422) {
    return {
      tone: "error",
      title: t("errors.query.refusedFiltersTitle", { subject }),
      message: t("users.notes.refusedFiltersMessage", { message: error.message }),
      canRetry: false,
    };
  }

  if (error.status === 429) {
    const wait =
      error.retryAfterS === null
        ? ""
        : t("errors.query.rateLimitedWait", { seconds: error.retryAfterS });
    return {
      tone: "error",
      title: t("errors.query.rateLimitedTitle", { subject }),
      message: `${error.message}${wait}`,
      canRetry: false,
    };
  }

  if (isStale) {
    return {
      tone: "stale",
      title: t("errors.query.staleTitle", { subject }),
      message: t("errors.query.staleMessage", { message: error.message }),
      canRetry: true,
    };
  }

  if (error.status === 0) {
    return {
      tone: "offline",
      title: t("errors.query.offlineTitle", { subject }),
      message: error.message,
      canRetry: true,
    };
  }

  return {
    tone: "error",
    title: t("errors.query.failedTitle", { subject }),
    message: error.message,
    canRetry: true,
  };
}

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

export function UsersScreen(): JSX.Element {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [walk, setWalk] = useState<Walk>(FIRST_STOP);
  const canWriteBroadcasts = useCanWriteBroadcasts();

  const url = useMemo(() => parseUrlState(searchParams), [searchParams]);
  const filterCount = activeFilterCount(url);
  /*
   * A quick filter and a campaign audience are not the same kind of thing. The six chip
   * parameters are `/api/users` filters; a campaign freezes a segment DOCUMENT, and `q` — a
   * substring of the Telegram id — has no registry field at all. So while any of them is on,
   * the hand-off is refused rather than silently freezing a different population than the one
   * on screen. Expressing the same narrowing as segment rules re-enables it.
   */
  const quickFiltersActive = hasQuickFilters(url);

  /**
   * A filter change starts the walk again from the top.
   *
   * A cursor is a position in ONE ordering of ONE filtered set; carrying it into a different
   * set asks for a page of rows that were never counted, and the server would either 422 or —
   * worse — answer a page nobody can locate.
   */
  const patch = useCallback(
    (change: Partial<Omit<UsersUrlState, "cursor">>) => {
      setWalk(FIRST_STOP);
      setSearchParams(writeUrlState({ ...url, ...change, cursor: null }), { replace: true });
    },
    [setSearchParams, url],
  );

  const goToStop = useCallback(
    (stop: Walk) => {
      setWalk(stop);
      setSearchParams(writeUrlState({ ...url, cursor: stop.cursor }), { replace: true });
    },
    [setSearchParams, url],
  );

  const clearAll = useCallback(() => {
    setWalk(FIRST_STOP);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  /*
   * The field registry — the ONLY source of what may be filtered on and what may be sorted by.
   *
   * Gated separately from the audience count on purpose: `/segments/fields` is `broadcast.read`
   * and `/segments/preview` is `records.read`, so a role that can page this list can still see
   * how many accounts a segment selects even where the builder itself is refused. A failed read
   * therefore degrades to "no builder, plain headings", never to a broken table.
   */
  const registry = useSegmentFields();
  /* An abort is a superseded request, not a refusal, and renders as nothing — the same rule
     the list read follows. Everything else is explained where the builder would have been. */
  const registryFailure =
    registry.error !== null && registry.error.code !== CLIENT_ERROR_CODES.aborted
      ? registry.error
      : null;
  const fieldIndex = useMemo(
    () =>
      registry.data === undefined
        ? new Map<string, SegmentFieldView>()
        : segmentFieldIndex(registry.data),
    [registry.data],
  );

  /**
   * The segment as the BUILDER sees it: the document with the screen's ordering put back on.
   *
   * The two are stored apart (the URL owns `sort`/`sortDir`, which is where the server reads
   * them and what a column header writes) and joined only here, so the builder's sort control
   * and the table's headings are two views of one value rather than two values.
   */
  const builderValue = useMemo<Segment>(
    () =>
      url.sort === null ? url.segment : withSort(url.segment, { key: url.sort, dir: url.sortDir }),
    [url.segment, url.sort, url.sortDir],
  );

  const onSegmentChange = useCallback(
    (next: Segment) => {
      const sort = next.sort ?? null;
      patch({
        segment: withSort(next, null),
        sort: sort === null ? null : sort.key,
        sortDir: sort?.dir ?? DEFAULT_SORT_DIRECTION,
      });
    },
    [patch],
  );

  /*
   * `withTotal` and a sort on a computed column cannot be asked for together: the count would
   * have to materialise every correlated aggregate over the whole filtered set before it could
   * order anything, and the server refuses the pair by name (422, `withTotal`). So the count is
   * dropped rather than the sort — the sort is what the operator just pressed — and the
   * subtitle says which of the two went. A sort whose field the registry has not answered for
   * is treated as aggregate: all but one sortable key is, and a wrong guess here is a 422 that
   * empties the table.
   */
  const isTotalAvailable = url.sort === null || fieldIndex.get(url.sort)?.isAggregate === false;

  const filters = useMemo<UsersFilters>(
    () => ({
      // Asked for deliberately: the toolbar states a count, and a count nobody asked for is a
      // count that must not be invented. It is bounded (`TOTAL_COUNT_CAP`) and says so.
      withTotal: isTotalAvailable,
      q: url.q,
      isBlocked: url.isBlocked,
      hasBalance: url.hasBalance,
      uiLanguage: url.uiLanguage,
      from: url.from,
      to: url.to,
      // The TOKEN, byte-identical to the one in the address bar and to the one the audience
      // count is keyed on — one audience, one cache entry, one question.
      segment: segmentToken(url.segment),
      sort: url.sort,
      sortDir: url.sortDir,
    }),
    [isTotalAvailable, url],
  );

  const page = useMemo<PageRequest>(
    () => ({ limit: DEFAULT_PAGE_LIMIT, cursor: url.cursor }),
    [url.cursor],
  );

  const users = useUsers(filters, page);
  /*
   * A cancelled request — a filter change superseding this page, an unmount — is not a failure
   * and must render as nothing at all. Everything else is this screen's to explain.
   */
  const failure =
    users.error !== null && users.error.code !== CLIENT_ERROR_CODES.aborted ? users.error : null;
  useSessionGuard([failure]);

  const items = users.data?.items ?? [];
  const meta = users.data?.meta ?? null;

  /* The trail describes ONE cursor. A pasted link or a Back button lands on a cursor this
     walk knows nothing about, and then there is no Previous to offer and no offset to claim. */
  const isWalkCurrent = walk.cursor === url.cursor;
  const offset = isWalkCurrent ? walk.offset : null;
  const trail = isWalkCurrent ? walk.trail : [];
  const previousStop = trail.length === 0 ? undefined : trail[trail.length - 1];
  const nextCursor = users.data === undefined ? null : nextCursorOf(users.data);

  /*
   * How many accounts the SEGMENT selects — the exact count, not the list's bounded total.
   *
   * Only asked for when there is something to count for: an operator with the panel shut and no
   * segment is reading the directory, and a request per visit for a number nobody is looking at
   * is a request nobody asked for. It counts the segment ALONE — `/segments/preview` takes
   * `?segment=` and nothing else — which is why the panel says so beside the number, and why
   * "Message these users" refuses while a quick filter is on.
   */
  const isSegmentPresent = !isSegmentEmpty(url.segment);
  const preview = useSegmentPreview(url.segment, {
    enabled: isSegmentPresent || isPanelOpen,
  });
  const previewFailure =
    preview.error !== null && preview.error.code !== CLIENT_ERROR_CODES.aborted
      ? preview.error
      : null;

  const chips = useMemo<readonly FilterChip[]>(() => {
    const list: FilterChip[] = [];
    if (url.q !== null) {
      // The VALUE verbatim: it is what was typed, and a chip is read back by somebody who did
      // not type it. The FIELD says what it searched, so an empty page is legible.
      list.push({
        id: "q",
        field: t("users.chips.query"),
        value: url.q,
        onRemove: () => {
          patch({ q: null });
        },
      });
    }
    if (url.isBlocked !== null) {
      list.push({
        id: "isBlocked",
        field: t("users.chips.blocked"),
        value: url.isBlocked ? t("common.yes") : t("common.no"),
        onRemove: () => {
          patch({ isBlocked: null });
        },
      });
    }
    if (url.hasBalance !== null) {
      list.push({
        id: "hasBalance",
        field: t("users.chips.creditBalance"),
        value: url.hasBalance
          ? t("users.chips.aboveZero")
          : t("users.chips.zeroOrNever"),
        onRemove: () => {
          patch({ hasBalance: null });
        },
      });
    }
    if (url.uiLanguage.length > 0) {
      list.push({
        id: "uiLanguage",
        field: t("users.chips.language"),
        value: url.uiLanguage
          .map((language) => t(LANGUAGE_LABEL_KEY[language]))
          .join(t("users.chips.languageJoin")),
        onRemove: () => {
          patch({ uiLanguage: [] });
        },
      });
    }
    if (url.from !== null) {
      list.push({
        id: "from",
        field: t("users.chips.createdFrom"),
        value: formatAbsolute(url.from),
        onRemove: () => {
          patch({ from: null });
        },
      });
    }
    if (url.to !== null) {
      list.push({
        id: "to",
        field: t("users.chips.createdBefore"),
        value: formatAbsolute(url.to),
        onRemove: () => {
          patch({ to: null });
        },
      });
    }
    /*
     * One row, both sources. A segment chip carries its own group's connective when it is
     * nested ("Any · Songs delivered: at least 3"), because a chip lifted out of an `any` group
     * and shown beside the `all` ones reads as one more thing EVERY account must match — which
     * inverts the audience. Removing one prunes a nested group its removal emptied.
     */
    list.push(
      ...buildSegmentChips({
        segment: url.segment,
        fields: fieldIndex,
        t,
        locale,
        onChange: onSegmentChange,
      }),
    );
    return list;
  }, [fieldIndex, locale, onSegmentChange, patch, t, url]);

  /**
   * A column heading, wired to the server's ordering — or nothing, for a column it refuses.
   *
   * The allowlist is the registry's own `sortable` flag and nothing else. `telegram_user_id`,
   * `ui_language` and `is_blocked` are all filterable and none is sortable, so those three
   * headings stay words; `last_activity_at` is not even a column here. Offering a control the
   * server will 422 teaches an operator that the panel is unreliable about a refusal that is
   * deliberate — a sort publishes a total order over identified accounts, and that is the
   * whole reason the flag exists.
   *
   * Three states, not two: unsorted → descending → ascending → unsorted. The third press is
   * how an operator gets back to the default `(created_at, id)` walk — the cheap cursor, and
   * the one every bookmarked "next page" link they already hold was minted against.
   */
  const sortFor = useCallback(
    (fieldKey: string, column: string): ColumnSort | undefined => {
      const field = fieldIndex.get(fieldKey);
      if (field === undefined || !field.sortable) return undefined;
      const isActive = url.sort === fieldKey;
      const next: SortDirection | null = !isActive
        ? "desc"
        : url.sortDir === "desc"
          ? "asc"
          : null;
      return {
        direction: isActive ? url.sortDir : null,
        label:
          next === null
            ? t("users.sort.clear", { column })
            : t(next === "desc" ? "users.sort.descending" : "users.sort.ascending", { column }),
        onSort: () => {
          patch({
            sort: next === null ? null : fieldKey,
            sortDir: next ?? DEFAULT_SORT_DIRECTION,
          });
        },
      };
    },
    [fieldIndex, patch, t, url.sort, url.sortDir],
  );

  const columns = useMemo<readonly Column<UserView>[]>(
    () => [
      {
        key: "identity",
        header: t("users.table.user"),
        width: "20rem",
        render: (row) => (
          <span className="flex min-w-0 items-center gap-3">
            <Avatar
              src={row.avatarUrl}
              initials={initialsOf(row)}
              /* A dot only where there is something to say. A green "healthy" pill on every
                 row would be decoration; the sr-only word is what carries the meaning. */
              {...(row.isBlocked
                ? { status: "danger" as const, statusLabel: t("users.standing.blocked") }
                : {})}
            />
            <span className="flex min-w-0 flex-col">
              {/* The masked twin, as sent. No reveal affordance in a row — see the header. */}
              <span className="truncate">{row.telegramUserIdMasked}</span>
              <span className={cn(CELL_SECONDARY_CLASS, "truncate")}>
                {row.telegramUsernameMasked ?? t("users.table.noUsername")}
              </span>
            </span>
          </span>
        ),
      },
      {
        key: "uiLanguage",
        header: t("users.table.language"),
        width: "9rem",
        render: (row) => (
          <span className="text-ink-500">{t(LANGUAGE_LABEL_KEY[row.uiLanguage])}</span>
        ),
      },
      {
        key: "orderCount",
        header: t("users.table.orders"),
        width: "6rem",
        align: "right",
        sort: sortFor("order_count", t("users.table.orders")),
        render: (row) => formatCount(row.orderCount),
      },
      {
        key: "paidOrderCount",
        header: t("users.table.paid"),
        width: "6rem",
        align: "right",
        sort: sortFor("paid_order_count", t("users.table.paid")),
        render: (row) => (
          <span className={row.paidOrderCount === 0 ? "text-ink-300" : undefined}>
            {formatCount(row.paidOrderCount)}
          </span>
        ),
      },
      {
        key: "creditBalance",
        header: t("users.table.credits"),
        width: "9rem",
        align: "right",
        sort: sortFor("credit_balance", t("users.table.credits")),
        render: (row) =>
          row.creditBalance === null ? (
            <span
              className={cn(CELL_SECONDARY_CLASS, "whitespace-nowrap")}
              title={t("common.noCreditRow")}
            >
              never metered
            </span>
          ) : (
            formatCount(row.creditBalance)
          ),
      },
      {
        key: "isBlocked",
        header: t("users.table.standing"),
        width: "8rem",
        render: (row) =>
          row.isBlocked ? (
            <Badge tone="danger">{t("users.standing.blocked")}</Badge>
          ) : (
            <Badge tone="muted">{t("users.standing.notBlocked")}</Badge>
          ),
      },
      {
        key: "lastOrderAt",
        // Not "last activity": `UserView` carries no `lastSeenAt`, so this is MAX(orders.created_at)
        // — a measurement of purchases, and a column headed for presence would be a claim.
        header: t("users.table.lastOrder"),
        width: "10rem",
        sort: sortFor("last_order_at", t("users.table.lastOrder")),
        render: (row) => {
          if (row.lastOrderAt === null) {
            return <span className={CELL_SECONDARY_CLASS}>no orders</span>;
          }
          const relative = formatRelative(row.lastOrderAt, t);
          return (
            <span className="whitespace-nowrap" title={formatAbsolute(row.lastOrderAt)}>
              {relative ?? row.lastOrderAt}
            </span>
          );
        },
      },
      {
        key: "accountCreatedAt",
        header: t("users.table.firstContact"),
        width: "10rem",
        /* `joined_at` IS `users.created_at` under the registry's own name, so this column's
           descending sort is the default walk and keeps the cheap cursor. */
        sort: sortFor("joined_at", t("users.table.firstContact")),
        render: (row) => {
          const relative = formatRelative(row.accountCreatedAt, t);
          return (
            <span
              className={cn(CELL_SECONDARY_CLASS, "whitespace-nowrap")}
              title={`${formatAbsolute(row.accountCreatedAt)} — when the users row was created: first contact for anyone onboarded since that shipped, the first order for accounts that predate it.`}
            >
              {relative ?? row.accountCreatedAt}
            </span>
          );
        },
      },
    ],
    [sortFor, t],
  );

  /* ---------------------------------------------------------------------- */
  /* What the toolbar and the pager are allowed to claim                     */
  /* ---------------------------------------------------------------------- */

  const total = meta?.total ?? null;
  const isTotalExact = meta?.isTotalExact ?? null;

  let subtitle: string;
  if (users.data === undefined) {
    subtitle =
      failure === null ? t("users.subtitles.reading") : t("users.subtitles.failed");
  } else if (total === null) {
    /* Either `withTotal` was asked for and the server still declined to count, or it was never
       asked for because the chosen sort is a computed column and the pair is a 422. Both say
       what is on screen; only the second can also say why the count went. */
    subtitle = isTotalAvailable
      ? t("users.subtitles.onThisPage", { count: formatCount(items.length) })
      : t("users.subtitles.onThisPageSorted", { count: formatCount(items.length) });
  } else {
    const shown = formatTotal(total, isTotalExact, t);
    subtitle =
      filterCount === 0
        ? t("users.subtitles.accounts", { total: shown })
        : t("users.subtitles.accountsFiltered", { total: shown });
  }

  let rangeLabel: string;
  if (users.isPlaceholderData) {
    // The rows on screen belong to the PREVIOUS request and the walk has already moved on, so
    // any range composed now would number one page's rows with another page's positions.
    rangeLabel = t("users.range.loadingNext");
  } else if (users.data === undefined) {
    rangeLabel = failure === null ? t("users.range.loading") : t("users.range.noneLoaded");
  } else if (items.length === 0) {
    rangeLabel = filterCount === 0 ? t("users.range.none") : t("users.range.noneMatching");
  } else {
    const totalClause =
      total === null
        ? ""
        : t("users.range.ofTotal", { total: formatTotal(total, isTotalExact, t) });
    rangeLabel =
      offset === null
        ? // Joined mid-walk: the row numbers are unknowable, and guessing them would put a
          // wrong "51–100" in front of somebody about to quote it.
          t("users.range.onThisPage", {
            count: formatCount(items.length),
            total: totalClause,
          })
        : t("users.range.numbered", {
            start: formatCount(offset + 1),
            end: formatCount(offset + items.length),
            total: totalClause,
          });
  }

  /* A query holding anything but digits cannot match a Telegram id, ever. Saying so is the
     difference between "narrow this" and an operator concluding the customer does not exist. */
  const unmatchableQuery = url.q !== null && /\D/u.test(url.q) ? url.q : null;
  const emptyMessage = (
    <EmptyState
      title={filterCount === 0 ? t("users.empty.noUsers") : t("users.empty.noMatching")}
      message={
        filterCount === 0
          ? t("users.empty.noUsersHint")
          : unmatchableQuery !== null
            ? t("users.empty.unmatchable", {
                query: unmatchableQuery,
                hint: t("users.noMatchHint"),
              })
            : t("users.noMatchHint")
      }
      {...(filterCount === 0
        ? {}
        : {
            action: (
              <ToolbarButton onClick={clearAll} variant="secondary">
                {t("common.clearAllFilters")}
              </ToolbarButton>
            ),
          })}
    />
  );

  const note = failure === null ? null : noteFor(failure, users.data !== undefined, t);

  return (
    <main className="py-6">
      {/* The shell owns the page ground and the rail; this is only the content band. */}
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar
          title={t("users.title")}
          subtitle={subtitle}
          filters={
            <SearchFieldSlot
              value={url.q}
              onChange={(next) => {
                patch({ q: next });
              }}
            />
          }
          actions={
            <>
              <ToolbarButton
                /* Always the outlined button: the accent one is the kit's PRIMARY action, and a
                   disclosure is not one. That the list is narrowed is said by the chips below,
                   which carry the accent ground, and by the count in this label. */
                variant="secondary"
                ariaExpanded={isPanelOpen}
                ariaControls="users-filter-panel"
                onClick={() => {
                  setIsPanelOpen((open) => !open);
                }}
              >
                {filterCount === 0
                  ? t("common.filters")
                  : t("common.filtersCount", { count: filterCount })}
              </ToolbarButton>
              {canWriteBroadcasts ? (
                <ToolbarButton
                  /* The kit's PRIMARY action, and here it earns it: this is the only control on
                     the screen that starts something rather than narrowing it. */
                  variant="primary"
                  icon={<Megaphone className="h-5 w-5" aria-hidden />}
                  disabled={quickFiltersActive}
                  ariaLabel={
                    quickFiltersActive
                      ? t("users.broadcast.blockedByQuickFilters")
                      : isSegmentPresent
                        ? t("users.broadcast.ariaSegment")
                        : t("users.broadcast.ariaEveryone")
                  }
                  onClick={() => {
                    /* The token VERBATIM — the same bytes the address bar carries and the same
                       bytes `POST /api/broadcasts` freezes. Re-encoding it here would be a
                       second answer to "which audience did the operator approve". */
                    navigate(broadcastNewPath(segmentToken(url.segment)));
                  }}
                >
                  {t("users.broadcast.action")}
                </ToolbarButton>
              ) : null}
            </>
          }
        />

        <div
          id="users-filter-panel"
          role="group"
          aria-label={t("users.filtersAria")}
          hidden={!isPanelOpen}
          className="rounded-card border border-stroke bg-card px-4 py-4"
        >
          <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
            <TriStateSelect
              label={t("users.filter.blocked")}
              value={url.isBlocked}
              onChange={(next) => {
                patch({ isBlocked: next });
              }}
              trueLabel={t("users.standing.blocked")}
              falseLabel={t("users.standing.notBlocked")}
              hint={t("users.hints.blocked")}
            />
            <TriStateSelect
              label={t("users.filter.creditBalance")}
              value={url.hasBalance}
              onChange={(next) => {
                patch({ hasBalance: next });
              }}
              trueLabel={t("users.filter.aboveZero")}
              falseLabel={t("users.filter.zeroOrNever")}
              hint="“Above zero” is a strictly positive stored balance. The other position covers both remaining shapes — metered down to zero, and never metered at all."
            />
            <EnumToggleGroup<Language>
              label={t("users.filter.botLanguage")}
              values={LANGUAGE_VALUES}
              selected={url.uiLanguage}
              onChange={(next) => {
                patch({ uiLanguage: next });
              }}
              format={(language) => t(LANGUAGE_LABEL_KEY[language])}
              hint={t("users.hints.language")}
            />
            <DateRangeFields
              label={t("users.filter.accountCreated")}
              from={url.from}
              to={url.to}
              onChange={(next) => {
                patch({ from: next.from, to: next.to });
              }}
              hint={t("users.hints.accountCreated")}
            />
          </div>

          {/* The second section, under a rule: the four controls above are the FAST path and
              this is the complete one. Both narrow the same list and both write to the same
              URL, and everything they select is ANDed. */}
          <div className="mt-5 flex flex-col gap-2 border-t border-stroke pt-5">
            <div className="flex flex-col gap-1">
              <h2 className={SECTION_HEADING_CLASS}>{t("users.segment.heading")}</h2>
              <p className={SECTION_HINT_CLASS}>{t("users.segment.description")}</p>
            </div>
            <SegmentPanel
              view={registry.data ?? null}
              isPending={registry.isPending}
              error={registryFailure}
              value={builderValue}
              onChange={onSegmentChange}
              preview={
                <AudiencePreview
                  audience={preview.data ?? null}
                  isPending={preview.isFetching}
                  error={previewFailure}
                  hasQuickFilters={quickFiltersActive}
                />
              }
            />
          </div>
        </div>

        <FilterChips chips={chips} onClearAll={chips.length === 0 ? undefined : clearAll} />

        {note === null || failure === null ? null : (
          <ErrorNote
            tone={note.tone}
            title={note.title}
            message={note.message}
            hint={`${failure.endpoint} · ${failure.correlationId ?? t("errors.query.noCorrelationId")}`}
            onRetry={() => {
              void users.refetch();
            }}
            isRetrying={users.isFetching}
            retryable={note.canRetry}
          />
        )}

        {/* A failed FIRST read has nothing to draw: the note above is the whole answer. A
            failed refresh keeps the table, dimmed by nothing — those rows are still true. */}
        {users.data === undefined && failure !== null ? null : (
          <div
            /* `keepPreviousData` swaps rows rather than blanking the table, so the rows under
               new chips are the PREVIOUS answer until this one lands. Dimmed, and marked busy,
               because presenting them at full contrast is the one failure nothing on screen
               would look wrong for. */
            aria-busy={users.isPlaceholderData}
            className={cn("transition-opacity", users.isPlaceholderData && "opacity-50")}
          >
            <DataTable
              columns={columns}
              rows={items}
              getRowKey={(row) => row.id}
              isLoading={users.isPending}
              /* The skeleton reserves the PAGE, not a token eight rows: eight then fifty
                 moves the pager underneath by about a page-length as the data lands. */
              skeletonRows={DEFAULT_PAGE_LIMIT}
              caption={t("users.tableCaption")}
              emptyMessage={emptyMessage}
              onRowClick={(row) => {
                navigate(userDetailPath(row.telegramUserId));
              }}
            />
          </div>
        )}

        <CursorPager
          hasPrev={previousStop !== undefined}
          hasNext={nextCursor !== null}
          isFetching={users.isFetching}
          rangeLabel={rangeLabel}
          onPrev={
            previousStop === undefined
              ? undefined
              : () => {
                  goToStop({
                    cursor: previousStop.cursor,
                    offset: previousStop.offset,
                    trail: trail.slice(0, -1),
                  });
                }
          }
          onNext={
            nextCursor === null
              ? undefined
              : () => {
                  goToStop({
                    cursor: nextCursor,
                    offset: offset === null ? null : offset + items.length,
                    trail: [...trail, { cursor: url.cursor, offset }],
                  });
                }
          }
        />
      </div>
    </main>
  );
}

/**
 * The search box, with the copy the privacy rule pins to it.
 *
 * Split out so the three strings sit together with the control they describe rather than being
 * threaded through the toolbar's JSX, where a well-meaning edit could reword one of them into
 * a promise to find a person.
 */
function SearchFieldSlot({
  value,
  onChange,
}: {
  readonly value: string | null;
  readonly onChange: (next: string | null) => void;
}): JSX.Element {
  const { t } = useI18n();

  return (
    <SearchField
      value={value}
      onChange={onChange}
      label={t("users.searchLabel")}
      placeholder={t("users.searchPlaceholder")}
      hint={t("users.searchHint")}
      maxLength={MAX_SEARCH_CHARS}
      className="w-full max-w-[22rem]"
    />
  );
}

/**
 * The advanced segment section: the builder, or the reason it is not there.
 *
 * `GET /api/segments/fields` is `broadcast.read`, which is a different cell from the one that
 * lists these accounts — so a role that can read the directory may still be refused the
 * registry, and that has to read as a stated refusal rather than as a builder with no fields.
 * A builder drawn against an empty field list looks exactly like a server with no data.
 *
 * The audience count is passed IN. The builder never fetches: the count belongs to the screen
 * that reasons about it, and a self-fetching builder on a page that shows the number twice
 * would ask the same question twice.
 */
function SegmentPanel({
  view,
  isPending,
  error,
  value,
  onChange,
  preview,
}: {
  readonly view: SegmentFieldsView | null;
  readonly isPending: boolean;
  readonly error: AdminQueryError | null;
  readonly value: Segment;
  readonly onChange: (next: Segment) => void;
  readonly preview: ReactNode;
}): JSX.Element {
  const { t } = useI18n();

  if (view === null) {
    if (isPending) return <p className={SECTION_HINT_CLASS}>{t("segments.loading")}</p>;
    const message =
      error !== null && error.code === "FORBIDDEN"
        ? t("segments.forbidden")
        : t("segments.loadFailed");
    return <p className={SECTION_HINT_CLASS}>{message}</p>;
  }

  return (
    <SegmentBuilder
      value={value}
      onChange={onChange}
      fields={view.fields}
      limits={view.limits}
      version={view.version}
      /* The Users screen is where an ordering is a legitimate question — "who generated the
         most" is a threshold AND a sort. A campaign has no such question: its order is the
         sender's, so the wizard passes `showSort={false}`. */
      showSort
      label={t("users.segment.builderLabel")}
      preview={preview}
    />
  );
}

/**
 * How many accounts this segment selects — and what the number is not.
 *
 * Three honesty rules, all of them the server's own arithmetic:
 *
 * `matched`, `skippedBlocked` and `skippedBotBlocked` OVERLAP — the first is everyone the
 * document selects, the second is the accounts we barred, the third the accounts that blocked
 * the bot, and one person can be in both bars. Only `reachable` is the complement, so the two
 * skips are rendered as reasons and never added up.
 *
 * It counts the SEGMENT alone. `GET /api/segments/preview` takes `?segment=` and nothing else,
 * so while a quick filter is on, this number is larger than the list underneath it — and the
 * sentence says so rather than letting an operator read it as the table's total.
 *
 * It is exact. The toolbar's total saturates at `TOTAL_COUNT_CAP` and says "10,000+"; this one
 * does not, because "at least ten thousand" is a refusal to answer rather than an approximation
 * and nobody can approve a campaign against a ceiling.
 */
function AudiencePreview({
  audience,
  isPending,
  error,
  hasQuickFilters,
}: {
  readonly audience: SegmentPreviewView | null;
  readonly isPending: boolean;
  readonly error: AdminQueryError | null;
  readonly hasQuickFilters: boolean;
}): JSX.Element {
  const { t } = useI18n();

  if (error !== null) {
    return (
      <p className={SECTION_HINT_CLASS}>
        {error.code === "FORBIDDEN"
          ? t("users.audience.forbidden")
          : t("users.audience.failed", { message: error.message })}
      </p>
    );
  }

  if (audience === null) {
    return <p className={SECTION_HINT_CLASS}>{t("users.audience.counting")}</p>;
  }

  return (
    <div className="flex flex-col gap-1" aria-live="polite" aria-busy={isPending}>
      <p className="m-0 text-[14px] font-semibold leading-5 tracking-[-0.084px] text-ink-800">
        {t("users.audience.matched", { count: formatCount(audience.matched) })}
      </p>
      <p className={SECTION_HINT_CLASS}>
        {t("users.audience.reachable", {
          reachable: formatCount(audience.reachable),
          blocked: formatCount(audience.skippedBlocked),
          botBlocked: formatCount(audience.skippedBotBlocked),
        })}
      </p>
      {hasQuickFilters ? (
        <p className={SECTION_HINT_CLASS}>{t("users.audience.quickFiltersExcluded")}</p>
      ) : null}
    </div>
  );
}
