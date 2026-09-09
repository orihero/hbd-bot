/**
 * The reason block, which every operator action shares and none of them may skip.
 *
 * Three of these assertions are about a body that must not be sent (no reason code, a
 * malformed ticket reference, an empty string where the field should be absent) and one is
 * about state that must not be lost: a step-up takes the fields off screen, and the operator's
 * typed reason has to be there when they come back.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ACTION_REASON_REQUIRED_HINT,
  ReasonConfirmDialog,
  type ReasonValue,
} from "./ReasonConfirmDialog";

function renderDialog(
  props: Partial<Parameters<typeof ReasonConfirmDialog>[0]> = {},
): { readonly onConfirm: ReturnType<typeof vi.fn> } {
  const onConfirm = vi.fn();
  render(
    <ReasonConfirmDialog
      isOpen
      onOpenChange={vi.fn()}
      title="Block this account"
      confirmLabel="Block"
      onConfirm={onConfirm as (reason: ReasonValue) => void}
      {...props}
    />,
  );
  return { onConfirm };
}

/**
 * The toggle in the harnesses below, addressed by TEXT rather than by role.
 *
 * A modal dialog `aria-hidden`s the rest of the page, so anything outside the portal is off
 * the accessibility tree and `getByRole` cannot see it — which is the behaviour under test
 * everywhere else in this file.
 */
function toggle(): HTMLElement {
  return screen.getByText("toggle");
}

function chooseReason(code = "abuse_report"): void {
  fireEvent.change(screen.getByTestId("action-reason-code"), { target: { value: code } });
}

describe("ReasonConfirmDialog", () => {
  it("withholds the confirm until a reason is chosen, and says why", () => {
    renderDialog();

    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    expect(screen.getByTestId("action-reason-required")).toHaveTextContent(
      ACTION_REASON_REQUIRED_HINT,
    );

    chooseReason();

    expect(screen.getByTestId("action-confirm")).toBeEnabled();
    expect(screen.queryByTestId("action-reason-required")).not.toBeInTheDocument();
  });

  it("omits an empty ref and an empty note rather than sending them as empty strings", () => {
    const { onConfirm } = renderDialog();
    chooseReason("support_investigation");

    fireEvent.click(screen.getByTestId("action-confirm"));

    // `""` is not a ticket reference: the server's pattern refuses it, and an absent key is
    // the honest way to say "the operator gave none".
    expect(onConfirm).toHaveBeenCalledWith({ reasonCode: "support_investigation" });
  });

  it("passes the ref and the note through when they were written", () => {
    const { onConfirm } = renderDialog();
    chooseReason("incident");
    fireEvent.change(screen.getByTestId("action-reason-ref"), { target: { value: "SUP-1423" } });
    fireEvent.change(screen.getByTestId("action-reason-text"), {
      target: { value: "customer called twice" },
    });

    fireEvent.click(screen.getByTestId("action-confirm"));

    expect(onConfirm).toHaveBeenCalledWith({
      reasonCode: "incident",
      reasonRef: "SUP-1423",
      reasonText: "customer called twice",
    });
  });

  it("refuses a ref the server's pattern would refuse, before the round trip", () => {
    renderDialog();
    chooseReason();
    fireEvent.change(screen.getByTestId("action-reason-ref"), {
      target: { value: "not a ticket!" },
    });

    expect(screen.getByTestId("action-confirm")).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Letters, digits, #, _ and - only");
  });

  it("warns about a 40-character slug, which the audit boundary reads as a credential", () => {
    renderDialog();
    chooseReason();
    fireEvent.change(screen.getByTestId("action-reason-ref"), {
      target: { value: "a".repeat(44) },
    });

    // Two guards disagreeing by design: the field's own pattern allows it, the audit
    // boundary does not. The operator is told rather than 422'd.
    expect(screen.getByTestId("action-ref-credential-warning")).toBeInTheDocument();
  });

  it("keeps the typed reason while the fields are hidden for a step-up", () => {
    function Harness(): ReactElement {
      const [isHidden, setHidden] = useState(false);
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setHidden((current) => !current);
            }}
          >
            toggle
          </button>
          <ReasonConfirmDialog
            isOpen
            onOpenChange={vi.fn()}
            title="Grant credits"
            confirmLabel="Grant"
            onConfirm={vi.fn()}
            isFieldsHidden={isHidden}
          />
        </>
      );
    }
    render(<Harness />);
    chooseReason("customer_request");

    fireEvent.click(toggle());
    expect(screen.queryByTestId("action-reason-code")).not.toBeInTheDocument();
    fireEvent.click(toggle());

    // The password box is a detour, not a reset: retyping the reason after re-authenticating
    // is how an action ends up attributed to whatever was quickest to select.
    expect(screen.getByTestId("action-reason-code")).toHaveValue("customer_request");
  });

  it("starts clean when it is reopened", () => {
    function Harness(): ReactElement {
      const [isOpen, setOpen] = useState(true);
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setOpen((current) => !current);
            }}
          >
            toggle
          </button>
          <ReasonConfirmDialog
            isOpen={isOpen}
            onOpenChange={setOpen}
            title="Grant credits"
            confirmLabel="Grant"
            onConfirm={vi.fn()}
          />
        </>
      );
    }
    render(<Harness />);
    chooseReason("abuse_report");

    fireEvent.click(toggle());
    fireEvent.click(toggle());

    // Carrying "abuse report" into the next customer's goodwill comp is a wrong audit row
    // that nobody will ever notice.
    expect(screen.getByTestId("action-reason-code")).toHaveValue("");
  });

  it("hands the whole footer to the caller's banner once the fields are hidden", () => {
    renderDialog({ isFieldsHidden: true, banner: <p>step-up goes here</p> });

    expect(screen.getByText("step-up goes here")).toBeInTheDocument();
    expect(screen.queryByTestId("action-confirm")).not.toBeInTheDocument();
  });

  it("closes on Escape, the X and Cancel when nothing is at stake", () => {
    for (const dismiss of [
      () => {
        fireEvent.keyDown(screen.getByTestId("reason-confirm-dialog"), { key: "Escape" });
      },
      () => {
        fireEvent.click(screen.getByRole("button", { name: "Close" }));
      },
      () => {
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      },
    ]) {
      const onOpenChange = vi.fn();
      renderDialog({ onOpenChange });
      dismiss();
      expect(onOpenChange).toHaveBeenCalledWith(false);
      cleanup();
    }
  });

  it("refuses every one of those while isDismissLocked — a write in flight is not dismissable", () => {
    const onOpenChange = vi.fn();
    renderDialog({ onOpenChange, isDismissLocked: true });

    fireEvent.keyDown(screen.getByTestId("reason-confirm-dialog"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Not "closed and reopened": never asked to close at all. The caller is the only thing
    // that may end this dialog while its answer is unread — see rule 4.
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByTestId("reason-confirm-dialog")).toBeInTheDocument();
  });
});
