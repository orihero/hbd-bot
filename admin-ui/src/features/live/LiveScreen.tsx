/**
 * `/` — **Is the system fine right now?**
 *
 * §11.2's dominant signal, and every decision on this screen serves it: the **24 h delivery
 * success rate, colour-driven** (green ≥95%, amber 85–95%, red <85%), with **in flight**
 * beside it carrying a pulsing ring. The rate sits in the `PageHeader`'s `signal` slot
 * rather than in the body, so it cannot drift below a panel as this screen grows.
 *
 * The colour rule is `rateBand` and the hero size is `StatTile size="hero"` — neither is
 * re-implemented here. `StatTile` also prints the band's WORD (`good` / `at risk` / `bad`)
 * beside the figure, because a 40px number that means "the system is broken" purely by
 * being reddish fails on a projector, in greyscale, and for a red-green reader.
 *
 * Where the hero's numbers come from, and why they are not the pulse's, is argued in
 * `liveMetrics.ts`. The short version: the shipped `/ops/pulse` takes no window, and an
 * all-time rate cannot answer "right now".
 *
 * Everything polls at 5 s, visibility-gated (§11.5). Nothing on this screen blanks on a
 * failed tick: each panel is its own `AsyncBoundary`, so a stalled pulse leaves the orders
 * table alone and shows its own last-known numbers at 70% behind a `stale 42s` chip.
 *
 * ## The reskin
 *
 * This is the screen the new layout language maps onto most directly, so it is the one that
 * states the idiom for the rest of the console:
 *
 *  - **Groups, not boxes.** Content is gathered under a plain sentence-case section label
 *    (`Stats`, `Activity`, `Diagnostics`) set ON THE PAGE GROUND above the cards, never
 *    inside them and never as uppercase micro-caps. The label is a `<p>`, not a heading:
 *    `AttentionList`, `LiveFeed` and `Panel` each own an `<h2>` inside their own card, and a
 *    second heading level above them would leave a screen reader with two competing outlines
 *    for one group of four cards. `<h1>` stays singular, in `PageHeader`.
 *  - **Cards separate themselves.** `--surface-card` at a 28px radius under `--shadow-card`,
 *    with no border anywhere — the old `border border-line` is gone from this file.
 *  - **The window caption moved up, not away.** `24 h window <from> → <to>` used to be the
 *    last line on the page, below everything it qualified. It is now the caption beside the
 *    `Stats` label, which is what it qualifies; the text is unchanged.
 *
 * The hero keeps its own card in the header's signal slot rather than joining the tile row.
 * It answers a different question from the four tiles — "is this fine" against "what is
 * happening" — and §11.2 wants it reached first.
 */

import { useEffect, useMemo, type ReactElement, type ReactNode } from "react";

import {
  NOT_INSTRUMENTED_LABEL,
  SOURCE_UNAVAILABLE_LABEL,
  type CapabilitiesView,
  type FailureView,
} from "@/api";
import { StatTile, Timestamp } from "@/components/data";
import { AttentionList, ErrorCodeBadge, LiveFeed } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Skeleton, SkeletonText } from "@/components/util";
import {
  formatDurationS,
  formatInteger,
  formatRate,
  rateBand,
  statusGlyph,
  useFeedStore,
} from "@/lib";

import { feedEventsFromOrders, summariseDays } from "./liveMetrics";
import { useLiveOps } from "./useLiveOps";

/**
 * What this deployment can and cannot answer, in the operator's words.
 *
 * Every one of these is `false` in production today. The point of putting them on the
 * dashboard is that a zero and an absence look identical everywhere else: an operator who
 * does not know payments are uncaptured reads "0 payments" as a business fact.
 */
const CAPABILITY_ROWS: readonly {
  readonly key: keyof CapabilitiesView;
  readonly label: string;
  readonly offLabel: string;
}[] = [
  { key: "isCostTelemetry", label: "cost telemetry", offLabel: NOT_INSTRUMENTED_LABEL },
  { key: "isLatencyTelemetry", label: "latency telemetry", offLabel: NOT_INSTRUMENTED_LABEL },
  {
    key: "isAssetStorageKeyRecorded",
    label: "asset storage keys",
    offLabel: "not recorded — bytes outlive the row",
  },
  { key: "isChatCapture", label: "chat capture", offLabel: SOURCE_UNAVAILABLE_LABEL },
  { key: "isPaymentLedger", label: "payment ledger", offLabel: SOURCE_UNAVAILABLE_LABEL },
  { key: "isStateTransitionLog", label: "state transition log", offLabel: SOURCE_UNAVAILABLE_LABEL },
  /*
   * The two `vendor_usage` probes, and they are a PAIR because they are two different
   * absences with two different remedies. "not instrumented" means no worker writes a row —
   * deploy one. "no rate configured" means the rows are there and the money is not — set
   * `HBD_LLM_USD_PER_MILLION_*` or `HBD_ELEVENLABS_USD_PER_CHARACTER`. Collapsing them into
   * one row would send an operator looking for a missing writer that is already running.
   */
  { key: "isVendorUsage", label: "vendor usage", offLabel: NOT_INSTRUMENTED_LABEL },
  { key: "isVendorCost", label: "vendor cost rates", offLabel: "no rate configured" },
];

/** The hero card's width, fixed so the header does not reflow as the figure changes. */
const HERO_WIDTH = "w-[19rem]";

export function LiveScreen(): ReactElement {
  const { pulse, delivery, orders, window: liveWindow } = useLiveOps();

  const summary = useMemo(() => summariseDays(delivery.data ?? []), [delivery.data]);
  const liveOrders = useMemo(() => orders.data?.items ?? [], [orders.data]);
  const events = useMemo(() => feedEventsFromOrders(liveOrders), [liveOrders]);

  // The feed is a store, not a query: paused, arrivals buffer and the visible list does not
  // move under the operator's cursor. Ingest is idempotent — events carry a stable id.
  const ingest = useFeedStore((state) => state.ingest);
  useEffect(() => {
    ingest(events);
  }, [ingest, events]);

  const rate = summary.successRate;

  const signal = (
    <AsyncBoundary
      status={delivery.status}
      hasData={delivery.data !== undefined}
      dataUpdatedAt={delivery.dataUpdatedAt}
      error={delivery.error}
      onRetry={() => {
        void delivery.refetch();
      }}
      noun="the 24 h delivery rate"
      skeleton={<Skeleton width="19rem" height="10.5rem" />}
      className={HERO_WIDTH}
    >
      <StatTile
        size="hero"
        label="24 h delivery success"
        value={formatRate(rate)}
        band={rateBand(rate)}
        hint={
          <>
            <span className="num">{formatInteger(summary.delivered)}</span>
            {" delivered of "}
            <span className="num">{formatInteger(summary.terminal)}</span>
            {" terminal (delivered + failed) · rolling 24 h"}
          </>
        }
        className={HERO_WIDTH}
      />
    </AsyncBoundary>
  );

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Live Ops"
        description="Is the system fine right now?"
        signal={signal}
      />

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        <Group
          label="Stats"
          caption={
            <>
              {"24 h window "}
              <Timestamp at={liveWindow.from} />
              {" → "}
              <Timestamp at={liveWindow.to} />
            </>
          }
        >
          <AsyncBoundary
            status={pulse.status}
            hasData={pulse.data !== undefined}
            dataUpdatedAt={pulse.dataUpdatedAt}
            error={pulse.error}
            onRetry={() => {
              void pulse.refetch();
            }}
            noun="the pulse"
            skeleton={
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[0, 1, 2, 3].map((slot) => (
                  <Skeleton key={slot} height="8rem" />
                ))}
              </div>
            }
          >
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatTile
                label="in flight"
                value={formatInteger(pulse.data?.delivery.inFlight ?? 0)}
                glyph={statusGlyph("generating")}
                isPulsing={(pulse.data?.delivery.inFlight ?? 0) > 0}
                hint="orders that have not reached a terminal state"
              />
              <StatTile
                label="failed · 24 h"
                value={formatInteger(summary.failed)}
                hint={
                  <>
                    {"of "}
                    <span className="num">{formatInteger(summary.orders)}</span>
                    {" created in the window"}
                  </>
                }
              />
              <StatTile
                label="delivery latency p50"
                value={formatDurationS(pulse.data?.latency.p50Seconds ?? null)}
                hint={
                  <>
                    {"p95 "}
                    <span className="num">
                      {formatDurationS(pulse.data?.latency.p95Seconds ?? null)}
                    </span>
                    {" · "}
                    <span className="num">
                      {formatInteger(pulse.data?.latency.sampleCount ?? 0)}
                    </span>
                    {" samples"}
                  </>
                }
              />
              <StatTile
                label="paid · 24 h"
                value={formatInteger(summary.paid)}
                hint="authorisations, not revenue"
              />
            </div>
          </AsyncBoundary>
        </Group>

        <Group label="Activity">
          <div className="grid gap-4 xl:grid-cols-2">
            <AsyncBoundary
              status={orders.status}
              hasData={orders.data !== undefined}
              dataUpdatedAt={orders.dataUpdatedAt}
              error={orders.error}
              onRetry={() => {
                void orders.refetch();
              }}
              noun="orders needing attention"
              skeleton={<Skeleton height="18rem" />}
            >
              <AttentionList orders={liveOrders} />
            </AsyncBoundary>

            <LiveFeed />
          </div>
        </Group>

        <Group label="Diagnostics">
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="failure mix" caption="all time, from the pulse">
              <AsyncBoundary
                status={pulse.status}
                hasData={pulse.data !== undefined}
                isEmpty={(pulse.data?.failures.length ?? 0) === 0}
                dataUpdatedAt={pulse.dataUpdatedAt}
                error={pulse.error}
                onRetry={() => {
                  void pulse.refetch();
                }}
                noun="failures"
                emptyTitle="no failures recorded"
                emptyBody="Nothing in the record has a failure code against it."
                skeleton={<SkeletonText lines={4} />}
              >
                <FailureMix failures={pulse.data?.failures ?? []} />
              </AsyncBoundary>
            </Panel>

            <Panel
              title="what this deployment can answer"
              caption="an absence here is a missing writer, never a zero"
            >
              <AsyncBoundary
                status={pulse.status}
                hasData={pulse.data !== undefined}
                dataUpdatedAt={pulse.dataUpdatedAt}
                error={pulse.error}
                onRetry={() => {
                  void pulse.refetch();
                }}
                noun="capabilities"
                skeleton={<SkeletonText lines={6} />}
              >
                <Capabilities capabilities={pulse.data?.capabilities ?? null} />
              </AsyncBoundary>
            </Panel>
          </div>
        </Group>
      </div>
    </div>
  );
}

/**
 * A plain section label with the cards it gathers.
 *
 * Deliberately NOT a heading and NOT a landmark: the cards inside already carry `<h2>`s and
 * their own accessible names, and this is a visual grouping in the new layout language, not
 * a new level of information architecture. See this module's docstring.
 */
function Group({
  label,
  caption,
  children,
}: {
  readonly label: string;
  readonly caption?: ReactNode;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="type-h3 text-ink">{label}</p>
        {caption === undefined ? null : (
          <p className="type-body-sm text-ink-muted">{caption}</p>
        )}
      </div>
      {children}
    </div>
  );
}

/**
 * A titled card, for the two diagnostics panels.
 *
 * The `<h2>` lives INSIDE the card so this panel matches `AttentionList` and `LiveFeed`,
 * which own theirs and cannot be told otherwise. The browser gate finds the failure mix by
 * `section` + `heading level 2`, which this shape keeps.
 *
 * The cost of that choice: `AsyncBoundary`'s empty and error branches are themselves cards
 * (`EmptyState` and `ErrorState` both carry `--surface-card` + `--shadow-card`), so a panel
 * with nothing in it renders a card inside a card. Both surfaces are the same colour and the
 * shadow is 4% black, so it reads as a faint halo rather than a second box — but it is a
 * real seam, and closing it needs a "you are already inside a card" mode on `AsyncBoundary`
 * that this task does not own. Overriding it from here with `shadow-none` is NOT the fix: it
 * would also erase `ErrorState`'s `--ring-error` on a schema-drift failure, which is a
 * signal, not decoration. Reported rather than papered over.
 */
function Panel({
  title,
  caption,
  children,
}: {
  readonly title: string;
  readonly caption?: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    // Paper, 28px, a whisper of shadow, and no border and no header rule: the gap does the
    // separating that a `border-b` used to.
    <section className="flex flex-col rounded-card bg-surface-card shadow-card">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-card pb-3 pt-card">
        <h2 className="type-h2 text-ink">{title}</h2>
        {caption === undefined ? null : <p className="type-body-sm text-ink-muted">{caption}</p>}
      </header>
      <div className="px-card pb-card">{children}</div>
    </section>
  );
}

/**
 * The failure breakdown, largest first (the API returns it in that order).
 *
 * Every row is an `ErrorCodeBadge`, so retryability arrives as `↻` / `■` / `?` rather than
 * as a colour — and `null` retryability reads "unknown", never "terminal". `errorCode: null`
 * is its own group and still gets a badge, never a blank.
 *
 * Rows are separated by SPACE — no rule, and deliberately no hover ground either. Two
 * reasons, and the second is the load-bearing one:
 *
 *  1. Nothing here is clickable, and a ground that appears under the cursor is an offer.
 *  2. A hover ground would put an `ErrorCodeBadge` on `--surface-control`, and the token
 *     layer measures every `-tint` over `--surface-card` and `--surface` ONLY. Measured on
 *     the control grounds, `--error` on `--error-tint` is 4.20:1 and `--caution` on
 *     `--caution-tint` is 4.42:1 — both below the 4.5:1 text bar, and neither is something
 *     `tokenContrast.test.ts` currently looks at. Leaving the badge on the card keeps it at
 *     4.72:1 / 4.97:1. See this task's report: the same gap is live under `DataTable`'s row
 *     hover, which this file cannot reach.
 */
function FailureMix({ failures }: { readonly failures: readonly FailureView[] }): ReactElement {
  return (
    <ul className="flex flex-col gap-3">
      {failures.map((failure) => (
        <li
          key={failure.errorCode ?? "__unrecorded__"}
          className="flex flex-wrap items-center justify-between gap-2"
        >
          <ErrorCodeBadge code={failure.errorCode} isRetryable={failure.isRetryable} size="sm" />
          <span className="type-body-sm flex items-baseline gap-3">
            <span className="num font-semibold text-ink">{formatInteger(failure.count)}</span>
            <span className="num text-ink-muted">{formatRate(failure.share, 0)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The capability ledger.
 *
 * The glyph is `--success` when a source is instrumented and `--neutral` when it is not.
 * Both clear the 4.5:1 text bar on every ground in both palettes, so neither is a policed
 * token and this file needs no `eslint-disable` and no `MARK_WAIVERS` entry — the old
 * `var(--fg-2)` mark, and the dead directive that excused it, are gone.
 *
 * `--neutral` rather than `--warning` is the point of the row: an uninstrumented source is
 * not a fault, it is an absence, and the WORDS ("not instrumented", "not enabled in this
 * deployment") are what say so. Colour is not carrying that meaning alone.
 */
function Capabilities({
  capabilities,
}: {
  readonly capabilities: CapabilitiesView | null;
}): ReactElement {
  return (
    <ul className="flex flex-col gap-2.5">
      {CAPABILITY_ROWS.map((row) => {
        const isOn = capabilities?.[row.key] ?? false;
        return (
          <li
            key={row.key}
            data-testid="capability-row"
            data-capability={row.key}
            data-enabled={isOn ? "true" : "false"}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
          >
            <span aria-hidden="true" className={isOn ? "text-success" : "text-neutral"}>
              {isOn ? "✓" : "⊘"}
            </span>
            <span className="type-body-sm text-ink">{row.label}</span>
            {isOn ? null : <span className="type-body-sm text-ink-muted">{row.offLabel}</span>}
          </li>
        );
      })}
    </ul>
  );
}

export const Component = LiveScreen;
