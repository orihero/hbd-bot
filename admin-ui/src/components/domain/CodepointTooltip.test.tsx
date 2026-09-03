/**
 * The breakdown panel. Same rule as `<NameText>`: the value is spelled out, never folded.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CodepointTooltip } from "./CodepointTooltip";
import { NAME_OKTAM, WORD_SANAT } from "./fixtures";
import { NameText } from "./NameText";

describe("CodepointTooltip", () => {
  it("stays closed until asked", () => {
    render(
      <CodepointTooltip value={NAME_OKTAM}>
        <NameText value={NAME_OKTAM} />
      </CodepointTooltip>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on focus, not only on hover — an incident is a keyboard conversation", async () => {
    const user = userEvent.setup();
    render(
      <CodepointTooltip value={NAME_OKTAM}>
        <NameText value={NAME_OKTAM} />
      </CodepointTooltip>,
    );
    await user.tab();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });

  it("spells every codepoint of the value, in order", async () => {
    const user = userEvent.setup();
    render(
      <CodepointTooltip value={NAME_OKTAM}>
        <span>trigger</span>
      </CodepointTooltip>,
    );
    await user.click(screen.getByRole("button"));
    const panel = screen.getByRole("tooltip");
    expect(panel).toHaveTextContent("U+004F");
    expect(panel).toHaveTextContent("U+02BB");
    expect(panel).toHaveTextContent("U+006D");
  });

  it("tells the two modifier letters apart", async () => {
    const user = userEvent.setup();
    render(
      <CodepointTooltip value={WORD_SANAT}>
        <span>trigger</span>
      </CodepointTooltip>,
    );
    await user.click(screen.getByRole("button"));
    const panel = screen.getByRole("tooltip");
    expect(panel).toHaveTextContent("U+02BC");
    expect(panel).not.toHaveTextContent("U+02BB");
  });

  it("draws a placeholder for the invisible characters rather than an empty cell", async () => {
    const user = userEvent.setup();
    render(
      <CodepointTooltip value={"a​b"}>
        <span>trigger</span>
      </CodepointTooltip>,
    );
    await user.click(screen.getByRole("button"));
    const panel = screen.getByRole("tooltip");
    expect(panel).toHaveTextContent("U+200B");
    expect(panel).toHaveTextContent("◌");
  });
});
