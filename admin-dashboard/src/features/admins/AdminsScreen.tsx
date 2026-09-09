/**
 * `/admins` — who can sign in to this panel, and who currently cannot.
 *
 * ## Both halves of that question are on the screen
 *
 * A deactivated account is not a row to hide: it is the second half of the answer. It still
 * owns audit rows, it can still be reactivated, and one deactivated last year is the cleanest
 * possible answer to "is anything stale here?". So the table lists every account the server
 * sent, groups the ones that can sign in above the ones that cannot, and marks the difference
 * in **words** — a `Deactivated` pill and a "cannot sign in" line — because a greyed username
 * on its own says "cannot sign in" only to somebody who can see grey. The muted ink is the
 * second channel, never the only one.
 *
 * ## There is no pager, and adding one would be wrong
 *
 * `AdminRosterResponse` carries `items` and nothing else — no cursor, no total — and the
 * server takes the read under `MAX_ADMIN_ACCOUNTS`. That ceiling is the shape of the
 * question rather than a deferred pagination default: a deployment with more than 500
 * operator accounts has a problem this panel cannot fix, and a cursor in front of the roster
 * would hide that problem instead of surfacing it. When the response comes back at exactly
 * the ceiling the screen says the list **may** be truncated — never "showing 500 of N",
 * because N is not on the wire and the response carries no flag saying it was cut.
 *
 * ## No filters either
 *
 * The route takes no query parameters, so any narrowing would be client-side, and a search
 * box in front of a list of five to fifty rows hides the one account somebody opened the page
 * to look for. A "hide deactivated" toggle would be worse still: it answers "who has access?"
 * with a number smaller than the number of credentials that exist.
 *
 * ## Read-only, and every write affordance is ABSENT rather than disabled
 *
 * See `NO_WRITES_NOTE` below and the comment above the column list. There is no create, no
 * role edit, no reset-password, no deactivate toggle, no revoke-sessions and no row menu,
 * because none of those endpoints exists on this build and each would 404. The `isActive`
 * flag is display-only for the same reason: a control that looks like a switch and cannot
 * move is a lie about what this screen can do.
 *
 * ## The 403 is a first-class state, not "something went wrong"
 *
 * The roster is OWNER's alone (`admin.read`, §6.8 line 949) and the other three roles get a
 * plain `FORBIDDEN`. Two consequences are rendered here. The refusal says whose role refused
 * it and offers **no Retry**: the guard writes a `permission.denied` audit row in its own
 * committed transaction before raising, so every press would mint another row against an
 * operator who did nothing but open a page. And a `STEP_UP_REQUIRED` from this route is
 * reported as an unexpected refusal rather than answered with a password prompt — §12.2 once
 * collapsed this read into the account writes' `W+S` row, and following that literally
 * refused every caller for ever because the router guard resolves to `check_role`, which
 * holds no subject and so cannot see a grant. A prompt here is a loop nobody can win.
 *
 * The refusal is the server's, deliberately: `lib/rbac.ts` holds three cells and none of them
 * is `admin.read`, and inventing a fourth to gate this route client-side is a change to a
 * shared module for one screen's benefit. The cost of letting the server answer is exactly
 * one audit row per wrong-role visit — bounded, because nothing here retries or polls.
 *
 * ## Usernames are printed in the clear, and that is not an oversight
 *
 * §12.3's masking governs *customer* personal data. An operator is staff and their username
 * is the thing this endpoint exists to enumerate, so there is no `MaskedValue`, no reveal
 * button and no step-up anywhere on this screen. `admin_users` carries no retention clock
 * either, so no value here has a purged state.
 */

import { Ban, Check, KeyRound, UserCog } from "lucide-react";
import { useMemo, type JSX } from "react";

import { CLIENT_ERROR_CODES } from "@/api/client";
import { MAX_ADMIN_ACCOUNTS } from "@/api/constants";
import { Badge, type BadgeTone } from "@/components/Badge";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote, type NoteTone } from "@/components/ErrorNote";
import { Toolbar } from "@/components/Toolbar";
import { formatCount } from "@/features/dashboard/adapt";
import { EMPTY_VALUE } from "@/features/reveal";
import type { AdminQueryError } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";
import { useRole, type AdminRole } from "@/lib/rbac";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { useSessionGuard } from "@/state/useSessionGuard";

/** Every sentence on this screen, bound to the operator's chosen language. */
type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

import {
  DORMANT_DAYS,
  STALE_REASON_KEY,
  readRoster,
  type RosterEntry,
  type StaleReason,
} from "./adminRoster";
import { useAdmins } from "./useAdmins";

/* -------------------------------------------------------------------------- */
/* Copy that is load-bearing                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Why there is no Add, no Reset password and no Deactivate toggle.
 *
 * Rendered rather than left in a code comment: an operator who cannot find the button
 * otherwise concludes the console is broken and files a ticket, and the honest answer — the
 * endpoints do not exist yet — is short enough to print.
 *
 * It names what `hbd.admin.bootstrap` ACTUALLY does, which is two things: insert the first
 * OWNER into an empty table, and recover ownership when no active OWNER is left. Its parser
 * takes `--username`, `--password-file` and `--reset-owner` and nothing else, and
 * `db/admin/accounts.py` exports no role setter and no deactivator, so "all done through the
 * CLI" sent an operator to run a command that refuses them — on the one screen whose whole
 * ethic is not claiming a capability the system does not have. The honest shape of the answer
 * is that three of the four writes exist NOWHERE on this build, and saying so is what stops
 * somebody hunting for the flag that would do it. Deactivating an account is currently a
 * hand-written UPDATE against `admin_users`, which is not a procedure this screen is entitled
 * to print as if it were one.
 */
/*
 * The copy that used to be spelled here is in the catalogue, under `admins`:
 * `noWritesNote` (which three writes exist nowhere on this build, and why a button for them
 * would only 404), `status.cannotSignIn` (said on the row itself, because "greyed" is not a
 * channel everybody has), `subtitles.truncated` (the truncation POSSIBILITY — the response
 * carries no total and no flag, so a roster of exactly the ceiling is the one case where this
 * screen cannot promise it is showing everything), `emptyTitle`/`emptyMessage`, and
 * `table.attention` with `attentionTitle`.
 */

/**
 * The four roles, in this console's words. Keyed on `AdminRole`, so a fifth member added to
 * the wire vocabulary is a compile error here rather than a blank pill in production.
 *
 * The third role is spelled `admin` on the wire; §12.2's table heads that column OPERATOR.
 * Same role, and the wire spelling wins — a console using two words for one role is a
 * support call.
 */
const ROLE_LABEL_KEY: Readonly<Record<AdminRole, TranslationPath>> = {
  owner: "admins.roles.owner",
  admin: "admins.roles.admin",
  support: "admins.roles.support",
  viewer: "admins.roles.viewer",
};

/**
 * What each role may do, as the tooltip on its pill.
 *
 * Only the facts this screen can vouch for: the matrix lives on the server and these are the
 * cells that decide whether an operator can even open this page.
 */
const ROLE_HINT_KEY: Readonly<Record<AdminRole, TranslationPath>> = {
  owner: "admins.roleHints.owner",
  admin: "admins.roleHints.admin",
  support: "admins.roleHints.support",
  viewer: "admins.roleHints.viewer",
};

/**
 * One ground per role, and only OWNER gets the accent.
 *
 * The pill's word is the information; the ground exists so the one role that can do anything
 * privileged is findable in a fifty-row table without reading every cell. The other three
 * share `neutral` rather than being ranked by colour: they differ in what they may do, not in
 * how alarming they are, and a ramp of tones would invent a severity the matrix does not have.
 */
const ROLE_TONE: Readonly<Record<AdminRole, BadgeTone>> = {
  owner: "accent",
  admin: "neutral",
  support: "neutral",
  viewer: "neutral",
};

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * An identifier printed for recognition rather than for reading.
 *
 * The string mirrors `features/users/detailKit.ts` field for field and is restated here for
 * the reason that module's neighbours state: these are one feature's classes, not a shared
 * primitive, and a single class string is not worth a module under `components/`.
 */
const MONO_CLASS = "font-mono text-[12px] leading-[16px] tracking-[-0.2px] break-all";

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });
const ABSOLUTE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const RELATIVE_FORMAT = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const MINUTE_S = 60;
const HOUR_S = 60 * MINUTE_S;
const DAY_S = 24 * HOUR_S;
const MONTH_S = 30 * DAY_S;
const YEAR_S = 365 * DAY_S;

/**
 * "3 months ago" — for scanning. The exact instant rides along in a `title`.
 *
 * `null` when the string will not parse, so the caller can print what arrived instead of
 * "Invalid Date": a contract change is something an operator should be able to see and paste
 * into a ticket, not something this screen hides behind a plausible-looking blank.
 */
function formatRelative(iso: string, t: Translate): string | null {
  const at = Date.parse(iso);
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

/** The relative form with the raw string as a fallback, plus the absolute one for a `title`. */
interface Instant {
  readonly relative: string;
  readonly absolute: string;
}

function readInstant(iso: string, t: Translate): Instant {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return { relative: iso, absolute: iso };
  return { relative: formatRelative(iso, t) ?? iso, absolute: ABSOLUTE_FORMAT.format(at) };
}

/** The house two-line cell: the day above, the time under it in the secondary ink. */
function splitInstant(iso: string): { readonly date: string; readonly time: string } {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return { date: iso, time: "" };
  return { date: DATE_FORMAT.format(at), time: TIME_FORMAT.format(at) };
}

/** The reasons, in one line, worst first — or the dash that means "nothing to act on". */
function reasonsLine(reasons: readonly StaleReason[], t: Translate): string {
  if (reasons.length === 0) return EMPTY_VALUE;
  return reasons
    .map((reason) => t(STALE_REASON_KEY[reason], { days: DORMANT_DAYS }))
    .join(" · ");
}

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
 * Branching is on the CODE first and the status second, and the role is passed in so the
 * refusal can name it: "your role does not allow this" is a sentence somebody can check
 * against who they signed in as, where a generic failure banner would send them looking for
 * an outage that is not there.
 *
 * That ordering is load-bearing rather than tidy, and the `|| error.status === 403` fallback
 * below is exactly why. `STEP_UP_REQUIRED` is itself a **403** on this API, so a status test
 * placed above it swallows it and tells an OWNER — the one role that holds `admin.read` — that
 * their role has no `admin.read` cell, which is a refusal wearing the wrong explanation and
 * sends the operator to check the one thing that is not wrong. So every code that can arrive
 * carrying a 403 is answered first and the bare status is the LAST word on a 403, kept only to
 * catch a code this build has not heard of. `features/audit/AuditScreen.tsx` and
 * `features/users/detailKit.tsx` branch the same way round.
 *
 * Four of these withhold Retry, and on this route that matters more than usual: a refused
 * request has already written a `permission.denied` audit row, so a Retry button is a machine
 * for filling the audit log with rows about somebody who did nothing wrong.
 *
 * `null` for an aborted request — a navigation cancelled the read, which is not a failure and
 * must render as nothing at all.
 */
function noteFor(
  error: AdminQueryError,
  role: AdminRole | null,
  isStale: boolean,
  t: Translate,
): NoteCopy | null {
  const subject = t("admins.subject");

  if (error.code === CLIENT_ERROR_CODES.aborted) return null;

  if (error.code === "UNAUTHENTICATED" || error.code === "CSRF_REJECTED") {
    return {
      tone: "denied",
      title: t("errors.query.sessionEndedTitle"),
      message: t("admins.notes.sessionEndedMessage", { message: error.message }),
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

  if (error.code === "STEP_UP_REQUIRED") {
    // Above the 403 below, and not a prompt. This read is a bare `W` cell with no step-up
    // (§6.8 line 949), and the guard that answers it holds no subject, so no password round
    // trip could satisfy it — it would refuse the retry identically, for ever. The only way
    // this arrives is §12.2's collapsed `W+S` row coming back server-side, which is a fault
    // to report and NOT the reader's role being wrong. A refusal to display, reported.
    return {
      tone: "denied",
      title: t("admins.notes.stepUpTitle"),
      message: t("admins.notes.stepUpMessage", { message: error.message }),
      canRetry: false,
    };
  }

  // The last word on a 403, deliberately: every other code that carries one is already
  // answered above, so anything still here is a role refusal or a code this build predates.
  if (error.code === "FORBIDDEN" || error.status === 403) {
    const who =
      role === null
        ? t("admins.notes.forbiddenRoleUnknown")
        : t("admins.notes.forbiddenRoleNamed", { role: t(ROLE_LABEL_KEY[role]) });
    return {
      tone: "denied",
      title: t("admins.forbiddenTitle"),
      message: t("admins.notes.forbiddenMessage", { message: error.message, who }),
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
      message: t("admins.notes.staleMessage", { message: error.message }),
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

export function AdminsScreen(): JSX.Element {
  const { t } = useI18n();
  const admins = useAdmins();
  const role = useRole();

  useSessionGuard([admins.error]);

  /**
   * The whole derivation, pinned to the answer rather than to the render.
   *
   * `Date.now()` is read inside the memo and deliberately not in a dependency: dormancy is a
   * judgement about a list, and a row that silently crosses the 60-day line while somebody is
   * reading the table would change what the screen says without anything having happened.
   */
  const roster = useMemo(() => readRoster(admins.data?.items ?? []), [admins.data]);

  const failure = admins.error;
  const note =
    failure === null ? null : noteFor(failure, role, admins.data !== undefined, t);

  const subtitle = useMemo(() => {
    if (admins.data === undefined) {
      return failure === null ? t("admins.subtitles.reading") : t("admins.subtitles.failed");
    }
    const counted = t("admins.subtitle", {
      active: formatCount(roster.activeCount),
      deactivated: formatCount(roster.deactivatedCount),
    });
    return roster.isPossiblyTruncated
      ? t("admins.subtitles.truncated", { counted, cap: formatCount(MAX_ADMIN_ACCOUNTS) })
      : counted;
  }, [admins.data, failure, roster, t]);

  /*
   * Seven read-only columns and no eighth.
   *
   * There is no action column, no kebab menu, no inline role editor and no deactivate switch,
   * because `POST /admins`, `PATCH /admins/{id}`, `POST /admins/{id}/reset-password` and
   * `DELETE /admins/{id}/sessions` do not exist on this build and would 404 — and a control
   * that 404s is worse than an absent one. If you are here to "fix" the omission, add the
   * endpoint first: each of those is an OWNER cell demanding a step-up and an audit row.
   *
   * There is also no row click and no `/admins/:id` detail route: the row already holds every
   * field the contract exposes, so a detail panel would be the same eight values again.
   */
  const columns = useMemo<readonly Column<RosterEntry>[]>(
    () => [
      {
        key: "username",
        header: t("admins.table.username"),
        width: "16rem",
        render: ({ account }) => (
          <div className="flex flex-col">
            <span
              /* Muted ink is the SECOND channel for a deactivated account; the line under it
                 and the pill two columns over are the ones that do not need eyes. */
              className={cn(MONO_CLASS, account.isActive ? "text-ink-800" : "text-ink-400")}
            >
              {account.username}
            </span>
            {account.isActive ? null : (
              <span className={CELL_SECONDARY_CLASS}>{t("admins.status.cannotSignIn")}</span>
            )}
          </div>
        ),
      },
      {
        key: "role",
        header: t("admins.table.role"),
        width: "8rem",
        render: ({ account }) => (
          <Badge tone={ROLE_TONE[account.role]} title={t(ROLE_HINT_KEY[account.role])}>
            {t(ROLE_LABEL_KEY[account.role])}
          </Badge>
        ),
      },
      {
        key: "state",
        header: t("admins.table.signIn"),
        width: "10rem",
        render: ({ account }) =>
          account.isActive ? (
            <Badge tone="neutral" icon={<Check className="h-3 w-3" strokeWidth={2} />}>
              {t("admins.status.active")}
            </Badge>
          ) : (
            /* `muted`, not `danger`: a deactivated account is the control working, not an
               alarm. The word carries the fact and the icon repeats it. */
            <Badge
              tone="muted"
              icon={<Ban className="h-3 w-3" strokeWidth={2} />}
              title={t("admins.tooltips.deactivated")}
            >
              {t("admins.status.deactivated")}
            </Badge>
          ),
      },
      {
        key: "credential",
        header: t("admins.table.credential"),
        width: "12rem",
        render: ({ account }) => {
          if (account.mustChangePassword) {
            return (
              <Badge
                tone="warning"
                icon={<KeyRound className="h-3 w-3" strokeWidth={2} />}
                title="The password somebody else chose is still the password on this account."
              >
                Temporary
              </Badge>
            );
          }
          const rotated = readInstant(account.passwordChangedAt, t);
          return (
            <div className="flex flex-col">
              <span title={rotated.absolute}>Rotated</span>
              <span className={CELL_SECONDARY_CLASS} title={rotated.absolute}>
                {rotated.relative}
              </span>
            </div>
          );
        },
      },
      {
        key: "lastLogin",
        header: t("admins.table.lastSignIn"),
        width: "11rem",
        render: ({ account }) => {
          if (account.lastLoginAt === null) {
            /* Never signed into is a different fact from signed in long ago, and the two must
               not collapse into one dash: this one is the account whose temporary password is
               still live and the one worth chasing after a handover. */
            return (
              <div className="flex flex-col">
                <span>Never</span>
                <span className={CELL_SECONDARY_CLASS}>no sign-in recorded</span>
              </div>
            );
          }
          const seen = readInstant(account.lastLoginAt, t);
          return <span title={seen.absolute}>{seen.relative}</span>;
        },
      },
      {
        key: "created",
        header: t("admins.table.created"),
        width: "10rem",
        render: ({ account }) => {
          const at = splitInstant(account.createdAt);
          return (
            <div className="flex flex-col">
              <span>{at.date}</span>
              <span className={CELL_SECONDARY_CLASS}>{at.time}</span>
            </div>
          );
        },
      },
      {
        key: "attention",
        header: t("admins.table.attention"),
        render: ({ reasons }) => (
          <span className={reasons.length === 0 ? CELL_SECONDARY_CLASS : undefined}>
            {reasonsLine(reasons, t)}
          </span>
        ),
      },
    ],
    [t],
  );

  return (
    <main className="py-6">
      {/* The 1392px content box the shell's screens are composed against. The page ground and
          the min-height belong to `AppShell`; a second one here would paint over the rail's. */}
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Toolbar title="Admins" subtitle={subtitle} />

        {note === null || failure === null ? null : (
          <ErrorNote
            tone={note.tone}
            title={note.title}
            message={note.message}
            hint={`${failure.endpoint} · ${failure.correlationId ?? "no correlation id"}`}
            onRetry={() => {
              void admins.refetch();
            }}
            isRetrying={admins.isFetching}
            retryable={note.canRetry}
          />
        )}

        {roster.stale.length === 0 ? null : <AttentionList entries={roster.stale} />}

        {/* A failed FIRST read has nothing to draw: the note above is the whole answer. A
            failed refresh keeps the table — those rows are still true, they are just not
            moving, and the `stale` note above says so. */}
        {admins.data === undefined && failure !== null ? null : (
          <section aria-label="Operator accounts" className="flex min-w-0 flex-col gap-3">
            <DataTable
              columns={columns}
              rows={roster.rows}
              getRowKey={({ account }) => account.id}
              isLoading={admins.isPending}
              /* The roster is small and unpaged, so the skeleton reserves a plausible team
                 rather than a page limit there is no page to have. */
              skeletonRows={8}
              caption={t("admins.tableCaption")}
              emptyMessage={
                <EmptyState
                  icon={<UserCog className="h-6 w-6" strokeWidth={1.75} />}
                  title={t("admins.emptyTitle")}
                  message={t("admins.emptyMessage")}
                />
              }
            />
            <p className="m-0 text-[11px] font-normal leading-[1.35] text-ink-400">
              {t("admins.noWritesNote")}
            </p>
          </section>
        )}
      </div>
    </main>
  );
}

/* -------------------------------------------------------------------------- */
/* Parts                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The accounts that are worth doing something about, above the table rather than inside it.
 *
 * The table answers "who can sign in"; this answers "and which of them should not still be
 * able to", which is the follow-up question every roster review actually asks. Every reason is
 * spelled out in words — the caution ground is a second channel, not the message — and only
 * ACTIVE accounts appear, because a deactivated one cannot sign in and so is not work.
 */
function AttentionList({ entries }: { readonly entries: readonly RosterEntry[] }): JSX.Element {
  const { t } = useI18n();

  return (
    <section
      aria-label={t("admins.attentionTitle")}
      className="flex flex-col gap-3 rounded-card border border-stroke bg-card px-4 py-4"
    >
      <h2 className="m-0 text-[16px] font-normal leading-[21.856px] tracking-[-0.64px] text-ink-300">
        {t("admins.attentionTitle")}
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {entries.map(({ account, reasons }) => (
          <li key={account.id} className="flex flex-wrap items-center gap-2">
            <span className={cn(MONO_CLASS, "text-ink-800")}>{account.username}</span>
            <span className={CELL_SECONDARY_CLASS}>{t(ROLE_LABEL_KEY[account.role])}</span>
            {reasons.map((reason) => (
              <Badge key={reason} tone="warning">
                {t(STALE_REASON_KEY[reason], { days: DORMANT_DAYS })}
              </Badge>
            ))}
          </li>
        ))}
      </ul>
    </section>
  );
}
