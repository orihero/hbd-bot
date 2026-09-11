/**
 * The lifeline panel, over the five shapes a real payment actually takes.
 *
 * The component computes nothing — `status`, `at` and `noteCode` are the server's — so what is
 * asserted here is that each of the four states RENDERS as itself and that the note beside it
 * is a sentence rather than a slug. Three of the five fixtures exist because a naive renderer
 * gets them wrong:
 *
 *  - a PLAN sale, whose `credit_granted` step is `not_applicable` and must never read as
 *    missing: a plan mints songs as they are used and grants nothing at purchase;
 *  - an ERASED buyer, whose money moved and whose receipt was deliberately never written —
 *    a state, not a discrepancy, and never a fraud badge;
 *  - a settled payment with no `notifiedAt`, which is the ONE honest `missing` on a healthy
 *    payment and the only one that should ask for work.
 *
 * The last test is the one that keeps this panel honest as the server grows: every note code
 * the wire can carry must have a rendered string in `en`, because a missing translation shows
 * up here as the slug itself on the panel whose entire job is explaining things.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LIFELINE_NOTE_VALUES, type Lifeline as LifelineData } from "@/api/billing";
import { en } from "@/i18n/locales/en";

import { Lifeline } from "./Lifeline";
import { makeLifeline } from "./fixtures";

function stepOf(key: string): HTMLElement {
  return screen.getByTestId(`lifeline-step-${key}`);
}

function statusOf(key: string): string | null {
  return stepOf(key).getAttribute("data-status");
}

describe("Lifeline", () => {
  it("renders a pending payment with no rail transaction", () => {
    render(<Lifeline lifeline={makeLifeline()} />);

    expect(statusOf("opened")).toBe("done");
    expect(statusOf("rail_transaction")).toBe("pending");
    // The note is the answer to most support calls, and it is what a hand-settled payment
    // looks like too — so it must be a sentence and not the slug.
    expect(within(stepOf("rail_transaction")).getByTestId("lifeline-note-rail_transaction"))
      .toHaveTextContent(en.billing.lifeline.notes.neverOpened);
  });

  it("renders a fully settled single-song sale as six done steps", () => {
    const lifeline: LifelineData = makeLifeline([
      { key: "rail_transaction", status: "done", at: "2026-09-10T08:01:00Z", noteCode: null },
      { key: "performed", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "receipt", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "credit_granted", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      {
        key: "customer_told",
        status: "done",
        at: "2026-09-10T08:03:00Z",
        noteCode: "already_told",
      },
    ]);
    render(<Lifeline lifeline={lifeline} />);

    for (const key of [
      "opened",
      "rail_transaction",
      "performed",
      "receipt",
      "credit_granted",
      "customer_told",
    ]) {
      expect(statusOf(key)).toBe("done");
    }
    // A note on a DONE step: "was the confirmation sent, and when?" is what the operator
    // opened this dossier to ask, so the note rides on the success rather than replacing it.
    expect(screen.getByTestId("lifeline-note-customer_told")).toHaveTextContent(
      en.billing.lifeline.notes.alreadyTold,
    );
  });

  it("renders a PLAN sale's credit step as not-applicable, never as missing", () => {
    const lifeline = makeLifeline([
      { key: "rail_transaction", status: "done", at: "2026-09-10T08:01:00Z", noteCode: null },
      { key: "performed", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "receipt", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      {
        key: "credit_granted",
        status: "not_applicable",
        at: null,
        noteCode: "plan_grants_nothing",
      },
      { key: "customer_told", status: "done", at: "2026-09-10T08:03:00Z", noteCode: null },
    ]);
    render(<Lifeline lifeline={lifeline} />);

    expect(statusOf("credit_granted")).toBe("not_applicable");
    expect(statusOf("credit_granted")).not.toBe("missing");
    expect(screen.getByTestId("lifeline-note-credit_granted")).toHaveTextContent(
      en.billing.lifeline.notes.planGrantsNothing,
    );
  });

  it("renders an erased buyer as a state, not a discrepancy", () => {
    const lifeline = makeLifeline([
      { key: "rail_transaction", status: "done", at: "2026-09-10T08:01:00Z", noteCode: null },
      { key: "performed", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "receipt", status: "not_applicable", at: null, noteCode: "buyer_erased" },
      { key: "credit_granted", status: "not_applicable", at: null, noteCode: "buyer_erased" },
      { key: "customer_told", status: "not_applicable", at: null, noteCode: "buyer_erased" },
    ]);
    render(<Lifeline lifeline={lifeline} />);

    // Money moved; there is nobody left to sell to. Three not-applicables and no alarm.
    for (const key of ["receipt", "credit_granted", "customer_told"]) {
      expect(statusOf(key)).toBe("not_applicable");
      expect(statusOf(key)).not.toBe("missing");
      expect(screen.getByTestId(`lifeline-note-${key}`)).toHaveTextContent(
        en.billing.lifeline.notes.buyerErased,
      );
    }
  });

  it("renders a settled payment whose confirmation never went out as missing", () => {
    const lifeline = makeLifeline([
      { key: "rail_transaction", status: "done", at: "2026-09-10T08:01:00Z", noteCode: null },
      { key: "performed", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "receipt", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "credit_granted", status: "done", at: "2026-09-10T08:02:00Z", noteCode: null },
      { key: "customer_told", status: "missing", at: null, noteCode: null },
    ]);
    render(<Lifeline lifeline={lifeline} />);

    // The ONE honest `missing` on a healthy payment, and the one the dossier's notify action
    // is the remedy for.
    expect(statusOf("customer_told")).toBe("missing");
    expect(screen.getByTestId("lifeline-step-customer_told")).toHaveTextContent(
      en.billing.lifeline.status.missing,
    );
  });

  it("renders a sentence for every note code the server can send", () => {
    // A slug on screen is what a missing translation looks like, on the panel whose whole job
    // is explaining things. This fails the day the server adds an eighth note code.
    for (const note of LIFELINE_NOTE_VALUES) {
      const lifeline = makeLifeline([{ key: "receipt", status: "missing", noteCode: note }]);
      const view = render(<Lifeline lifeline={lifeline} />);
      const rendered = screen.getByTestId("lifeline-note-receipt").textContent ?? "";
      expect(rendered.length, note).toBeGreaterThan(note.length);
      expect(rendered, note).not.toContain(note);
      view.unmount();
    }
  });
});
