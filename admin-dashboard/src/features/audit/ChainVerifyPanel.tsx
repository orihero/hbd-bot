import { useId, type JSX, type ReactNode } from "react";

import type { ChainVerify } from "@/api/audit";
import { Badge } from "@/components/Badge";
import { Skeleton } from "@/components/Skeleton";
import { ToolbarButton } from "@/components/Toolbar";
import { formatCount } from "@/features/dashboard/adapt";
import { cn } from "@/lib/cn";

import {
  BREAK_EXPLANATION,
  TRUNCATION_EXPLANATION,
  chainProtectionNote,
  chainVerdict,
  formatSeq,
  localZoneLabel,
  splitTimestamp,
} from "./auditFormat";

/**
 * `GET /api/audit/verify`, as an answer an operator can act on.
 *
 * The audit log is the record everything else is checked against, so the only useful question
 * about it is whether it still says what it said when it was written. This panel is that
 * question and its answer, and its whole design problem is that the answer has **three** states
 * where a badge naturally has two.
 *
 * ## `ok: true` with `isComplete: false` is not a pass
 *
 * The walk stops at `MAX_VERIFY_ROWS` (50 000) and the tail check is deliberately skipped when
 * it does, so a clean pass over the first 50 000 rows can claim neither the rest of the table
 * nor the tail. A green all-clear there is exactly the misreading `isComplete` exists to
 * prevent, so this renders as its own verdict in `warning` — a caveat, not an alarm, and never
 * the same pill as a clean walk. Note the inverse, which is why the third state is not
 * symmetric: when `ok` is `false` the walk stopped because it found the answer, so a break
 * always arrives complete.
 *
 * ## `ok: false` is an incident, and reads as one
 *
 * The chain is HMAC-keyed with a key that lives only in the admin process's environment, so an
 * adversary who can write the table cannot forge a valid link. A break is therefore a finding
 * and not a hint, the server has already logged `admin.audit.chain_broken` at ERROR with the
 * reader's username by the time this renders, and the panel says what the break does and does
 * not condemn: rows below it are still trustworthy.
 *
 * ## `chainProtection` is printed verbatim, and `hmac-only` is not a failure
 *
 * §12.4 says verbatim, so `revoke+hmac` and `hmac-only` keep their punctuation and are never
 * run through a humaniser. `hmac-only` is the honest answer wherever the database has not
 * confirmed the revoke — including a Postgres deployment where it was configured and did not
 * land — and it means tampering would be detected but not prevented. A control that is not
 * deployed is reported as not deployed, in the ink ramp, not in the alarm colour. A value this
 * build has never heard of is printed with a note saying there is no note, rather than crashing
 * or inventing prose about a mode nobody here has read the code for.
 *
 * ## `truncationPoints` are holes the system dug itself
 *
 * Each is a sequence below which the 730-day sweep deleted rows on schedule and wrote a
 * TRUNCATION anchor naming the survivor. They are why a log with retired history still
 * verifies, and listing them as errors would send somebody to investigate the retention job.
 *
 * ## The verdict carries the instant it was taken
 *
 * `useChainVerify` holds an answer for ever (`staleTime: Infinity`, no focus refetch, no
 * reconnect refetch), which is the right policy — a walk is taken deliberately — and it means
 * the verdict on screen can be hours older than the rows in the table below it. The sentence it
 * renders is absolute ("The log has not been edited since it was written"), so without a
 * "Checked at" beside it an operator paging through rows written after the walk reads a stale
 * pass as a current guarantee covering rows it never touched. There is no server-side timestamp
 * on this wire — `chainVerifySchema` has six fields and none of them is a clock — so the
 * instant is the query's own `dataUpdatedAt`, handed down as `checkedAt`. It is the moment this
 * browser received the answer, which is the honest bound: the walk itself finished slightly
 * before it, never after.
 *
 * ## The failure states, and the one control that has to obey them
 *
 * The failure and loading states arrive as props rather than being read here: the screen owns
 * `noteFor`, so one function decides how every read on this surface explains itself, and this
 * panel does not grow a second opinion about what a 403 means. `canRecheck` is the other half
 * of that arrangement. Deferring the INTERPRETATION of a refusal while leaving a live button
 * that re-fires the refused request is not deference — `audit.read` is ADMIN and OWNER only,
 * every refused `GET /api/audit/verify` writes a `permission.denied` row in its own committed
 * transaction, and a SUPPORT operator pressing "Check again" three times has written three more
 * rows against themselves. So the screen's `noteFor(...).canRetry` comes down here too and the
 * button is dead for exactly the failures `<ErrorNote>` already withholds its Retry for. It
 * stays live for the ones where a recheck genuinely helps — offline, a 5xx, an aborted walk.
 */

interface ChainVerifyPanelProps {
  /** `undefined` until the walk lands. */
  readonly verification: ChainVerify | undefined;
  /**
   * When this browser received the verdict on screen, as an epoch millisecond, or `0` before
   * one ever landed. The query's `dataUpdatedAt`; see the header for why it is not on the wire.
   */
  readonly checkedAt: number;
  /** No verdict at all yet — not a refetch of one already on screen. */
  readonly isPending: boolean;
  /** A walk is in flight; the button rests until it lands so one press is one walk. */
  readonly isFetching: boolean;
  /** The screen's composed `<ErrorNote>`, or nothing. Rendered instead of a stale verdict. */
  readonly note?: ReactNode | undefined;
  /**
   * False when asking again could only be refused again — the screen's own `canRetry`. The
   * button goes DISABLED rather than absent: it is the panel's one control, and a header that
   * loses it under a refusal reads as a panel that failed to draw.
   */
  readonly canRecheck: boolean;
  readonly onRecheck: () => void;
}

const PANEL_CLASS = "flex flex-col gap-3 rounded-card border border-stroke bg-card p-4";

const TITLE_CLASS =
  "m-0 text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-800";

const BODY_CLASS = "m-0 text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-500";

const TERM_CLASS = "text-[12px] font-normal leading-[16.392px] tracking-[-0.36px] text-ink-300";

const VALUE_CLASS =
  "text-[14px] font-medium leading-5 tracking-[-0.084px] text-ink-900";

/** Identifiers and machine values, read character by character and pasted into tickets. */
const MONO_CLASS = "font-mono text-[12px] leading-4 text-ink-800";

export function ChainVerifyPanel({
  verification,
  checkedAt,
  isPending,
  isFetching,
  note,
  canRecheck,
  onRecheck,
}: ChainVerifyPanelProps): JSX.Element {
  const titleId = useId();

  return (
    <section aria-labelledby={titleId} aria-busy={isFetching} className={PANEL_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={titleId} className={TITLE_CLASS}>
          Chain integrity
        </h2>
        {/* Not a refresh of a list — a fifty-thousand-row HMAC walk, taken deliberately. It
            rests while one is running so a second press cannot start a second walk, and it
            rests under a refusal so a press cannot mint another audit row (see the header).
            No tooltip explains the second case: the note rendered immediately below IS the
            explanation, and a `title` repeating it would say the same thing twice, worse. */}
        <ToolbarButton onClick={onRecheck} disabled={isFetching || !canRecheck}>
          {isFetching ? "Checking…" : "Check again"}
        </ToolbarButton>
      </div>

      {isPending ? (
        <Skeleton className="h-32 w-full rounded-card" />
      ) : note !== undefined && note !== null ? (
        note
      ) : verification === undefined ? null : (
        <ChainVerdictBody verification={verification} checkedAt={checkedAt} />
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Parts                                                                       */
/* -------------------------------------------------------------------------- */

/** Said in place of an instant on the one path where there is none. See `checkedAt`. */
const NO_CHECKED_AT = "not recorded";

/**
 * The instant the verdict on screen describes, in the reader's zone and named as such.
 *
 * The zone label rides along for the same reason the table's Recorded column carries one: a
 * wall-clock time with no zone is a time somebody will compare against a log line in UTC and
 * get an hour wrong. `0` is react-query's "never resolved", which cannot be reached from here
 * — this body renders only with a verdict in hand — and is handled anyway rather than printed
 * as 1970.
 */
function formatCheckedAt(checkedAt: number): string {
  if (checkedAt === 0) return NO_CHECKED_AT;
  return `${splitTimestamp(new Date(checkedAt).toISOString()).full} ${localZoneLabel()}`;
}

function ChainVerdictBody({
  verification,
  checkedAt,
}: {
  readonly verification: ChainVerify;
  readonly checkedAt: number;
}): JSX.Element {
  const verdict = chainVerdict(verification.ok, verification.isComplete);
  const truncationPoints = verification.truncationPoints;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={verdict.tone}>{verdict.label}</Badge>
        {/* The sentence, not the colour, is the verdict — it has to read on its own. */}
        <p className={cn(BODY_CLASS, "min-w-[16rem] flex-1")}>{verdict.sentence}</p>
      </div>

      <dl className="grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-3 xl:grid-cols-6">
        {/* First, and not an afterthought at the end of the row: every other fact here is a
            property OF this walk, and this is the walk's own timestamp — the thing that says
            which rows the sentence above is about. */}
        <Fact term="Checked at" value={formatCheckedAt(checkedAt)} />
        <Fact term="Rows checked" value={formatCount(verification.checkedRows)} />
        <Fact
          term="Last sequence"
          /* `last_seq or None` normalises a 0 to null too, so "no rows" covers both the empty
             table and the walk that reached nothing. It is not sequence zero. */
          value={verification.lastSeq === null ? "no rows walked" : formatSeq(verification.lastSeq)}
        />
        <Fact
          term="Walk"
          value={
            verification.isComplete ? "the whole table" : "stopped at the 50,000-row ceiling"
          }
        />
        <Fact
          term="First break"
          value={
            verification.firstBreakSeq === null
              ? "none"
              : formatSeq(verification.firstBreakSeq)
          }
        />
        <Fact
          term="Protection"
          /* Verbatim, punctuation and all (§12.4). `revoke+hmac` is not a slug to tidy. */
          value={<code className={MONO_CLASS}>{verification.chainProtection}</code>}
        />
      </dl>

      {verification.ok ? null : <p className={BODY_CLASS}>{BREAK_EXPLANATION}</p>}

      <p className={BODY_CLASS}>{chainProtectionNote(verification.chainProtection)}</p>

      {truncationPoints.length === 0 ? null : (
        <div className="flex flex-col gap-2">
          <span className={TERM_CLASS}>Retired history</span>
          <div className="flex flex-wrap items-center gap-2">
            {truncationPoints.map((seq) => (
              /* `muted`, never `warning`: these are scheduled deletions, and a tone that
                 looked like a finding would send somebody to investigate the sweep. */
              <Badge key={seq} tone="muted">
                {`below ${formatSeq(seq)}`}
              </Badge>
            ))}
          </div>
          <p className={BODY_CLASS}>{TRUNCATION_EXPLANATION}</p>
        </div>
      )}
    </div>
  );
}

function Fact({
  term,
  value,
}: {
  readonly term: string;
  readonly value: ReactNode;
}): JSX.Element {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className={TERM_CLASS}>{term}</dt>
      <dd className={cn("m-0 break-words", VALUE_CLASS)}>{value}</dd>
    </div>
  );
}
