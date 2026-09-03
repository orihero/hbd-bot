/**
 * `/admins` — §11.2: *"Is there a stale account?"*, dominant signal *"active count +
 * last-login recency"*.
 *
 * **The role check happens before the request, not after it.** The roster is OWNER's alone —
 * `admin.read`, §6.8 line 949 — and `build_admins_router` refuses the other three roles with
 * a 403 that *writes a `permission.denied` audit row*. A SUPPORT who follows a pasted link
 * would otherwise put a refusal row in the log for doing nothing but opening a page. The nav
 * entry is already behind a `PermissionGate` for the same reason; this is the direct-URL
 * half of it.
 *
 * **Deactivated accounts are rendered, greyed, never omitted.** The schema's own comment says
 * so, and the reason is the question: an account that was deactivated last year is the
 * cleanest possible answer to "is there a stale account?", and a list that hides it makes an
 * operator go to `psql` to find out.
 *
 * **The roster is a bounded whole-table read.** `AdminRosterResponse` has no `meta` and the
 * server caps at `MAX_ADMIN_ACCOUNTS`, so there is no pager here and there should not be one.
 *
 * Polling: none. §11.5 puts this in "everything else" — a roster changes when an OWNER
 * changes it, and those writes are Phase 2.
 *
 * This screen is READ-ONLY on this build. Create, reset-password, demote and deactivate are
 * all OWNER writes behind a step-up (§12.2) and none of their endpoints exists yet, so no
 * button for any of them is drawn — a control that 404s is worse than an absent one.
 *
 * **An OWNER loads this normally: there is no step-up on the read, and no dialog for one.**
 * The route's cell is `admin.read` — §6.8 line 949's `| GET | /admins | List | W |`, owner,
 * no `+S`. §12.2 collapsed that read and the four account writes into a single `W+S` row,
 * and following it literally refused every caller for ever: the router guard
 * resolves to `check_role`, which reports a cell's step-up requirement *without consulting a
 * grant at all* (`security/permissions.py:379-393`), so even a fresh, correctly-scoped
 * `admin.manage` grant left the next `GET` a 403. The endpoint table was ruled the
 * authority; `ADMIN_MANAGE` keeps its `W+S` cell for the Phase 2 writes.
 *
 * So this screen offers **no step-up affordance**. Not because a grant would be ignored, but
 * because this read never asks for one; the writes that will are not in this build. A
 * `STEP_UP_REQUIRED` from here would mean the server moved back onto the collapsed row, and
 * it is left to `AsyncBoundary` to report like any other unexpected refusal rather than
 * explained away in this screen's prose.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import { getAdmins, unwrapAsync, type AdminAccountView } from "@/api";
import { DataTable, StatTile, Timestamp, type DataColumn } from "@/components/data";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, EmptyState, PermissionGate, Skeleton, useRole } from "@/components/util";
import { NO_POLLING, formatInteger, formatRelative, pollWhileVisible, queryKeys } from "@/lib";

import { STALE_REASON_LABEL, staleReasons, summariseRoster } from "./adminRoster";

export function AdminsScreen(): ReactElement {
  const role = useRole();

  if (role === null) {
    return (
      <div className="p-gutter">
        <Skeleton className="h-[7.5rem] w-72" />
      </div>
    );
  }

  // §11.4's hiding semantics, spelled with the component that owns them rather than with a
  // bare `hasPermission`: a role with no `admin.read` cell gets the explanation and no
  // request, so opening this URL by hand writes no `permission.denied` row.
  return (
    <PermissionGate permission="admin.read" role={role} fallback={<AdminsNotPermitted />}>
      <AdminsBody />
    </PermissionGate>
  );
}

/**
 * VIEWER, SUPPORT and ADMIN. A denial with a reason, not a generic error and not a blank —
 * and deliberately not the roster with its controls greyed out (§11.4).
 */
function AdminsNotPermitted(): ReactElement {
  return (
    <div className="flex justify-center px-gutter py-gutter" data-testid="admins-forbidden">
      {/*
       * The design's shape for an absence — a centred card, a glyph, a bold line, a muted
       * line — but built here rather than with `<EmptyState>`, because this is a whole
       * screen and needs the page's one `h1`. `EmptyState` renders a `role="status"` region
       * with a `<p>` for its title, which would leave the route with no heading at all.
       */}
      <section className="flex w-full max-w-xl flex-col items-center gap-3 rounded-card bg-surface-card px-8 py-12 text-center shadow-card">
        <span aria-hidden="true" className="text-[28px] leading-none text-ink-muted">
          🔒
        </span>
        <h1 className="type-h1 text-ink">Admins</h1>
        <p className="type-body max-w-prose text-ink-muted">
          The operator roster is an owner capability — §6.8 gives{" "}
          <code className="type-mono text-ink">admin.read</code> to OWNER and to no other role.
          Nothing was requested on your behalf, so this visit wrote no refusal row.
        </p>
      </section>
    </div>
  );
}

function AdminsBody(): ReactElement {
  const roster = useQuery({
    queryKey: queryKeys.admins.list(),
    queryFn: ({ signal }) => unwrapAsync(getAdmins({ signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const items = useMemo(() => roster.data?.items ?? [], [roster.data]);
  const summary = useMemo(() => summariseRoster(items), [items]);

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Admins"
        description="Is there a stale account?"
        signal={
          <div className="flex flex-wrap items-stretch gap-3" data-testid="admins-signal">
            <StatTile
              size="hero"
              label="active accounts"
              value={roster.data === undefined ? "—" : formatInteger(summary.activeCount)}
              hint={
                roster.data === undefined
                  ? "not read yet"
                  : `${formatInteger(summary.deactivatedCount)} deactivated, listed below and not omitted`
              }
            />
            <StatTile
              label="most recent sign-in"
              value={
                roster.data === undefined
                  ? "—"
                  : summary.lastLoginAt === null
                    ? "never"
                    : formatRelative(summary.lastLoginAt)
              }
              hint={
                summary.lastLoginAt === null
                  ? "no active account has ever signed in"
                  : "across every active account"
              }
            />
            <StatTile
              label="needs a look"
              value={roster.data === undefined ? "—" : formatInteger(summary.stale.length)}
              hint="never signed in, still on a temporary password, or long quiet"
            />
          </div>
        }
      />

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        <AsyncBoundary
          status={roster.status}
          hasData={roster.data !== undefined}
          error={roster.error}
          onRetry={() => void roster.refetch()}
          {...(roster.isError ? { dataUpdatedAt: roster.dataUpdatedAt } : {})}
          noun="the operator roster"
          skeleton={<Skeleton className="h-64 w-full" />}
        >
          {summary.stale.length === 0 ? null : (
            <section aria-label="accounts needing attention" className="flex flex-col gap-3">
              <h2 className="type-h3 text-ink">Worth a look</h2>
              {/*
               * The design's feed-item shape: a ring at the left, a title line, a muted line,
               * separated by whitespace rather than by rules. The ring is `--caution-fill` and
               * it is not the only channel — every reason is spelled out in words beside it.
               */}
              <ul className="flex flex-col gap-2" data-testid="admins-stale">
                {summary.stale.map(({ account, reasons }) => (
                  <li
                    key={account.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card bg-surface-card px-5 py-4 shadow-card"
                  >
                    <span
                      aria-hidden="true"
                      className="size-2.5 shrink-0 rounded-full bg-caution-fill"
                    />
                    <span className="type-mono text-ink">{account.username}</span>
                    <span className="type-caption text-ink-muted">{account.role}</span>
                    <span className="flex flex-wrap items-center gap-2">
                      {reasons.map((reason) => (
                        <span
                          key={reason}
                          className="type-body-sm rounded-pill bg-caution-tint px-3 py-0.5 text-ink"
                        >
                          {STALE_REASON_LABEL[reason]}
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-label="operator roster" className="mt-8 flex flex-col gap-3">
            <h2 className="type-h3 text-ink">Every account</h2>
            <DataTable
              data={items}
              columns={ROSTER_COLUMNS}
              getRowId={(row) => row.id}
              label="Operator accounts"
              isRefetching={roster.isRefetching}
              emptyState={
                <EmptyState
                  title="No operator accounts"
                  body="The roster came back empty, which on a bootstrapped deployment should be impossible — the account you are signed in as would be in it."
                />
              }
            />
          </section>
        </AsyncBoundary>
      </div>
    </div>
  );
}

/**
 * `username` is rendered as plain text, deliberately NOT through `<NameText>`: §12.3's
 * lang/dir wrapper is for CUSTOMER content. An operator username is staff data chosen from
 * an ASCII-ish vocabulary by the OWNER who created it, and wrapping it would say something
 * false about where it came from.
 */
const ROSTER_COLUMNS: readonly DataColumn<AdminAccountView>[] = [
  {
    id: "username",
    header: "Username",
    isNumeric: false,
    cell: (row) => (
      <span className={row.isActive ? "type-mono text-ink" : "type-mono text-ink-muted"}>
        {row.username}
      </span>
    ),
  },
  {
    id: "role",
    header: "Role",
    isNumeric: false,
    // The WIRE spelling (`admin`), not §12.2's column heading (`OPERATOR`). The roster shows
    // what the row holds; a console using two words for one role is a support call.
    cell: (row) => <span className="type-body-sm text-ink-muted">{row.role}</span>,
  },
  {
    id: "status",
    header: "Status",
    isNumeric: false,
    cell: (row) =>
      row.isActive ? (
        <span className="type-body-sm text-ink-muted">
          <span aria-hidden="true" className="text-success">
            ✓{" "}
          </span>
          active
        </span>
      ) : (
        <span className="type-body-sm text-ink-muted" data-deactivated="true">
          <span aria-hidden="true" className="text-neutral">
            ⊘{" "}
          </span>
          deactivated
        </span>
      ),
  },
  {
    id: "password",
    header: "Credential",
    isNumeric: false,
    cell: (row) =>
      row.mustChangePassword ? (
        <span className="type-body-sm text-caution">temporary — not yet rotated</span>
      ) : (
        <span className="type-body-sm text-ink-muted">
          rotated <Timestamp at={row.passwordChangedAt} relative />
        </span>
      ),
  },
  {
    id: "lastLogin",
    header: "Last sign-in",
    isNumeric: false,
    cell: (row) =>
      row.lastLoginAt === null ? (
        <span className="type-body-sm text-ink-muted">never</span>
      ) : (
        <Timestamp at={row.lastLoginAt} relative />
      ),
  },
  {
    id: "created",
    header: "Created",
    isNumeric: false,
    cell: (row) => <Timestamp at={row.createdAt} />,
  },
  {
    id: "attention",
    header: "Why it is listed",
    isNumeric: false,
    cell: (row) => {
      const reasons = staleReasons(row);
      if (reasons.length === 0) return <span className="type-body-sm text-ink-muted">—</span>;
      return (
        <span className="type-body-sm text-ink-muted">
          {reasons.map((reason) => STALE_REASON_LABEL[reason]).join(" · ")}
        </span>
      );
    },
  },
];

export const Component = AdminsScreen;
