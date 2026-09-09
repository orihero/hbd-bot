/**
 * One card per supplier, carrying the five figures the owner asked for: what is left, what
 * we consumed, what a song consumes, what a song costs, and how much consumption the balance
 * still buys — with the traffic light on the first and the last.
 *
 * ## The unit problem, which is the whole reason this file is shaped the way it is
 *
 * The two suppliers do not answer in the same unit and cannot be made to. OpenRouter reports a
 * DOLLAR balance; ElevenLabs reports a CHARACTER balance. `BalanceUnit`'s own docstring is the
 * argument — "4 312 remaining is a fortune in dollars and an afternoon in ElevenLabs
 * characters" — so there is no cross-vendor axis on this component and no total anywhere. Each
 * card is read on its own, in its own unit, and the only number that means the same thing on
 * both cards is SONGS OF COVER, which is what the light is computed from.
 *
 * ## "Remaining token count" is not a stored quantity, and this file says so rather than
 * inventing one
 *
 * Nothing anywhere records a remaining token balance, because no vendor publishes one:
 *
 *  * **ElevenLabs** bills characters and its balance IS a character count, so its remaining
 *    consumption figure is MEASURED — it is the same number the balance card prints, and the
 *    card says so instead of implying a second reading.
 *  * **OpenRouter** bills dollars. A remaining token figure can only be DERIVED, by dividing
 *    the dollar balance by the dollars-per-token this window actually measured. That division
 *    is only defined when both operands exist, and there are two ordinary states where it is
 *    not, which are drawn as themselves rather than as zero:
 *      - `costUsd === 0` — the vendor REPORTED these calls as free, which is the normal
 *        reading on a `:free` model and is the shipped default. A free model has no price to
 *        divide a balance by; the runway is not zero, it is undefined.
 *      - `costUsd === null` — nobody could price the calls at all, because no rate is
 *        configured. That is "unmeasured", and is emphatically not "$0.00".
 *
 * Every derived figure is labelled `derived` where it is printed. A number that looks measured
 * and is really an inference is worse than no number, which is the same rule
 * `plan_liability` follows when it refuses to value an unconsumed song.
 *
 * ## One light per card, deliberately, and never two
 *
 * The owner asked for the same highlight on the balance and on the remaining-consumption
 * figure. Both therefore read ONE `songsOfCover` per card rather than each thresholding its
 * own arithmetic — two estimates over two divisors would eventually disagree, and a card
 * showing a green balance beside a red runway is a card nobody can act on. The adapter picks
 * that one number and both figures quote it.
 *
 * Where a supplier has TWO accounts (the second OpenRouter key is a separate billing
 * relationship wearing one adapter name), the light reads the WORST of them: the deployment
 * stops when the account carrying the traffic stops, and a healthy spare does not refill an
 * empty primary. Each account's own balance is printed under the card so the pair is legible.
 */

import type { CSSProperties, JSX } from "react";

import { Skeleton } from "@/components/Skeleton";
import type { VendorCard, VendorFigure } from "@/features/dashboard/adapt";
import { type ThresholdState } from "@/features/dashboard/svg";
import { cn } from "@/lib/cn";

/**
 * The threshold inks, as CSS variables rather than Tailwind classes.
 *
 * `--th-*` is declared in `tokens.css` and moves with the theme; it is deliberately not in
 * `tailwind.config.ts`, so an inline `style` is how HTML reaches it. This mirrors `StatCard`'s
 * own `HATCH` constant, which is inline for the same reason: no utility fits.
 */
const THRESHOLD_INK: Record<ThresholdState, CSSProperties> = {
  ok: { color: "var(--th-ok)" },
  warn: { color: "var(--th-warn)" },
  bad: { color: "var(--th-bad)" },
  unknown: { color: "var(--th-unknown)" },
};

/** The dash a figure with no measurement prints. */
const NO_VALUE = "—";

export interface VendorCardsProps {
  /**
   * One entry per supplier that appears anywhere in the vendor response — in balances, in the
   * cost breakdown or in the unit breakdown. A supplier with usage and no balance row still
   * gets a card, because "we spent money here and nobody is watching the account" is the state
   * most worth seeing; it is the balance FIGURE that goes unmeasured, not the whole card.
   */
  readonly cards: readonly VendorCard[];
  /**
   * `VendorResponse.deliveredOrders` — the bare int, and the denominator every per-song figure
   * on every card was divided by. Printed ONCE, above the cards, and nowhere else: it is one
   * number about the window, and a copy under each per-song figure both invited the reader to
   * think the cards were divided by something of their own and spent a line of type per figure
   * to say nothing new.
   *
   * NOT `PerformanceResponse.deliveredOrders`, which is a `TrendView` of the same name over a
   * different window.
   */
  readonly deliveredOrders: number;
  /**
   * `capabilities.isVendorBalance`. `false` means this deployment polls no vendor at all,
   * which is a different sentence from "the poller has not run yet" and gets different words.
   */
  readonly isVendorBalance: boolean;
}

/** The five figures per supplier, with the owner's light on the first and the last. */
export function VendorCards({
  cards,
  deliveredOrders,
  isVendorBalance,
}: VendorCardsProps): JSX.Element {
  if (cards.length === 0) {
    return (
      <p className="rounded-card bg-card p-4 text-[11px] leading-[1.45] text-ink-300">
        {isVendorBalance
          ? "No supplier answered — no balance, no spend, no usage."
          : "No vendor is polled here, and none was called in this window."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-[1.2] text-ink-300">
        {deliveredOrders === 0
          ? "Nothing delivered — per-song figures undefined."
          : `Per song ÷ ${String(deliveredOrders)} delivered song${deliveredOrders === 1 ? "" : "s"}.`}
      </p>
      {cards.map((card) => (
        <VendorCardBlock key={card.vendor} card={card} />
      ))}
    </div>
  );
}

function VendorCardBlock({ card }: { readonly card: VendorCard }): JSX.Element {
  return (
    <article className="rounded-card bg-card p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h4 className="text-[11px] font-semibold tracking-[.4px] text-ink-800">{card.label}</h4>
        <p className="text-[11px] font-semibold tracking-[-.1px]" style={THRESHOLD_INK[card.state]}>
          {card.verdict}
        </p>
      </header>

      {card.accounts.length > 0 && (
        <p className="mt-[3px] text-[11px] leading-[1.35] text-ink-300">
          {card.accounts.join(" · ")}
        </p>
      )}

      <dl className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-x-4 gap-y-3">
        {card.figures.map((figure) => (
          <Figure key={figure.key} figure={figure} />
        ))}
      </dl>
    </article>
  );
}

function Figure({ figure }: { readonly figure: VendorFigure }): JSX.Element {
  const ink = figure.state === undefined ? undefined : THRESHOLD_INK[figure.state];

  return (
    <div>
      <dt className="text-[11px] font-semibold tracking-[-.1px] text-ink-400">{figure.label}</dt>
      {figure.value === null ? (
        <>
          <dd
            className="mt-1 text-[22px] font-bold leading-none tracking-[-1.2px] text-ink-300"
            aria-label={`${figure.label}: not measured`}
          >
            {NO_VALUE}
          </dd>
        </>
      ) : (
        <>
          <dd
            className={cn(
              "mt-1 flex items-baseline gap-[5px] whitespace-nowrap text-[22px] font-bold leading-none tracking-[-1.2px]",
              ink === undefined && "text-ink-800",
            )}
            style={ink}
          >
            <span>{figure.value}</span>
            {figure.unit !== "" && (
              <u className="text-[11px] font-medium tracking-[-.2px] text-ink-400 no-underline">
                {figure.unit}
              </u>
            )}
          </dd>
          {/* A figure with nothing left to say prints no line, rather than an empty one. */}
          {figure.note !== "" && (
            <dd className="mt-[3px] text-[11px] leading-[1.35] text-ink-300">{figure.note}</dd>
          )}
        </>
      )}
    </div>
  );
}

/** The band's own skeleton, sized to two cards so the section does not jump when they land. */
export function VendorCardsSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-[13px] w-[280px]" />
      <Skeleton className="h-[164px] w-full rounded-card" />
      <Skeleton className="h-[164px] w-full rounded-card" />
    </div>
  );
}
