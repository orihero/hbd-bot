import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CodeBlock } from "./CodeBlock";

describe("CodeBlock", () => {
  it("renders the code verbatim, including U+02BB", () => {
    const code = 'recipient_name_raw = "Gʻulom"';
    render(<CodeBlock code={code} />);
    expect(screen.getByText(code).textContent).toBe(code);
  });

  it("preserves whitespace rather than collapsing an indented block", () => {
    const { container } = render(<CodeBlock code={"a\n  b\n    c"} />);
    expect(container.querySelector("pre")).toHaveClass("whitespace-pre");
  });

  it("wraps only when asked", () => {
    const { container } = render(<CodeBlock code="x" isWrapped />);
    expect(container.querySelector("pre")).toHaveClass("whitespace-pre-wrap");
  });

  it("labels the language when the caller names one", () => {
    render(<CodeBlock code="{}" language="json" />);
    expect(screen.getByText("json")).toBeInTheDocument();
  });

  it("numbers lines in a gutter hidden from assistive tech and from a copy", () => {
    const { container } = render(<CodeBlock code={"one\ntwo\nthree"} showLineNumbers />);
    const gutter = container.querySelectorAll('[aria-hidden="true"].num');
    expect([...gutter].map((cell) => cell.textContent)).toEqual(["1", "2", "3"]);
  });

  it("offers a copy button naming what it copies", () => {
    render(<CodeBlock code="x" label="traceback" />);
    expect(screen.getByRole("button", { name: "copy traceback" })).toBeInTheDocument();
  });

  it("does not highlight — no tokeniser gets between the string and the DOM", () => {
    const { container } = render(<CodeBlock code={'{"a": 1}'} language="json" />);
    const code = container.querySelector("code");
    expect(code?.children).toHaveLength(0);
    expect(code?.textContent).toBe('{"a": 1}');
  });
});
