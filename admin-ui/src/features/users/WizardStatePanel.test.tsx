/**
 * §12.3's strictest row and §14's matching acceptance, as a rendering test.
 *
 * The wizard draft is hidden **at every role**, OWNER included: only key presence, char
 * counts and the step may be exposed. For an abandoned session that draft is the only copy
 * of the recipient's name, the note and the lyric that exists anywhere, so "no substring of
 * the plaintext" is the assertion — not "no field called note".
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { WizardStateView } from "@/api";
import { renderWithProviders, resetPrefs } from "@/components/util/testRender";

import { FIELD_ABSENT_LABEL, FIELD_EMPTY_LABEL, WizardStatePanel } from "./WizardStatePanel";

/** The plaintext a leak would surface. Uzbek Latin on purpose: U+02BB is the datum. */
const DRAFT_NAME = "Gʻulom";
const DRAFT_NOTE = "sizni juda yaxshi ko'raman";

function makeState(overrides: Partial<WizardStateView> = {}): WizardStateView {
  return {
    telegramUserId: 770000123,
    telegramUserIdMasked: "•••••123",
    isStatePresent: true,
    state: "Wizard:note",
    sessionId: "018f9c2e-0000-7000-8000-000000000000",
    choices: { ui_language: "uz_latn", occasion: "birthday" },
    textFields: [
      { key: "note", isPresent: true, charCount: DRAFT_NOTE.length },
      { key: "recipient", isPresent: true, charCount: DRAFT_NAME.length },
      { key: "lyrics", isPresent: false, charCount: null },
    ],
    lyricWrites: 2,
    ...overrides,
  };
}

beforeEach(() => {
  resetPrefs();
});

describe("WizardStatePanel", () => {
  it("renders counts and presence, never a substring of the draft", () => {
    renderWithProviders(<WizardStatePanel state={makeState()} />);

    expect(screen.getByTestId("wizard-state")).toHaveAttribute("data-present", "true");
    expect(screen.getByText("26 chars")).toBeInTheDocument();
    expect(screen.getByText("6 chars")).toBeInTheDocument();

    const rendered = document.body.textContent ?? "";
    expect(rendered).not.toContain(DRAFT_NAME);
    expect(rendered).not.toContain(DRAFT_NOTE);
    // Not even the first grapheme: this panel has no reveal, masked or otherwise.
    expect(rendered).not.toContain("Gʻ");
  });

  it("draws choice KEYS and not choice values", () => {
    // The values are bare `string` on the wire — Redis JSON a possibly-older build wrote —
    // so they cannot be proven to be one of our closed vocabularies, and unproven content
    // from a draft is draft content.
    renderWithProviders(<WizardStatePanel state={makeState()} />);

    expect(screen.getByText("ui language")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("uz_latn");
    expect(document.body.textContent).not.toContain("birthday");
  });

  it("marks a present choice and an absent one differently", () => {
    renderWithProviders(<WizardStatePanel state={makeState()} />);

    const all = screen.getAllByTestId("wizard-choice");
    const byKey = new Map(all.map((node) => [node.dataset["choice"], node.dataset["present"]]));
    expect(byKey.get("ui_language")).toBe("true");
    expect(byKey.get("genre")).toBe("false");
  });

  it("keeps “absent” and “present but empty” apart", () => {
    renderWithProviders(
      <WizardStatePanel
        state={makeState({
          textFields: [
            { key: "note", isPresent: true, charCount: 0 },
            { key: "recipient", isPresent: false, charCount: null },
            { key: "lyrics", isPresent: false, charCount: null },
          ],
        })}
      />,
    );

    // `null` = the key is absent; `0` = present and empty. Different facts.
    expect(screen.getByText(FIELD_EMPTY_LABEL)).toBeInTheDocument();
    expect(screen.getAllByText(FIELD_ABSENT_LABEL)).toHaveLength(2);
  });

  it("says so when there is no session, rather than rendering an empty shell", () => {
    renderWithProviders(<WizardStatePanel state={makeState({ isStatePresent: false })} />);

    expect(screen.getByTestId("wizard-state")).toHaveAttribute("data-present", "false");
    expect(screen.getByText(/no draft in redis/i)).toBeInTheDocument();
  });

  it("shows the aiogram step, which §12.3 names as exposable", () => {
    renderWithProviders(<WizardStatePanel state={makeState()} />);
    expect(screen.getByText("Wizard:note")).toBeInTheDocument();
  });
});
