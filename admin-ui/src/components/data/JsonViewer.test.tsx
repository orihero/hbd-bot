import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MASK } from "@/api";

import { JsonViewer } from "./JsonViewer";
import { isRedactedKey } from "./redaction";

describe("isRedactedKey", () => {
  it("matches the four §11.4 patterns in snake_case", () => {
    expect(isRedactedKey("openai_api_key")).toBe(true);
    expect(isRedactedKey("telegram_bot_token")).toBe(true);
    expect(isRedactedKey("admin_audit_hmac_secret")).toBe(true);
    expect(isRedactedKey("database_url")).toBe(true);
  });

  it("matches the same fields in the camelCase the wire actually uses", () => {
    expect(isRedactedKey("openaiApiKey")).toBe(true);
    expect(isRedactedKey("telegramBotToken")).toBe(true);
    expect(isRedactedKey("redisUrl")).toBe(true);
  });

  it("matches a bare url — a presigned link IS the credential", () => {
    expect(isRedactedKey("url")).toBe(true);
    expect(isRedactedKey("assetUrl")).toBe(true);
  });

  it("leaves ordinary keys alone", () => {
    expect(isRedactedKey("orderId")).toBe(false);
    expect(isRedactedKey("state")).toBe(false);
    expect(isRedactedKey("recipientNameDisplay")).toBe(false);
    // Not a suffix match: "tokenCount" is a count, not a token.
    expect(isRedactedKey("tokenCount")).toBe(false);
  });
});

describe("JsonViewer", () => {
  it("never lets a matching value reach the DOM", () => {
    render(<JsonViewer value={{ openaiApiKey: "sk-live-do-not-render", state: "delivered" }} />);
    expect(screen.queryByText(/sk-live-do-not-render/)).toBeNull();
    expect(screen.getByText(MASK)).toBeInTheDocument();
    expect(screen.getByText("redacted")).toBeInTheDocument();
  });

  it("masks a redacted key holding an object, not just a string", () => {
    render(<JsonViewer value={{ providerSecret: { key: "leak", nested: { key: "leak2" } } }} />);
    expect(screen.queryByText(/leak/)).toBeNull();
  });

  it("renders the rest of the payload normally", () => {
    render(<JsonViewer value={{ redisUrl: "redis://x", orderId: "abc-123" }} />);
    expect(screen.getByText(/abc-123/)).toBeInTheDocument();
  });

  it("renders a string value verbatim — U+02BB survives the tree", () => {
    render(<JsonViewer value={{ recipientName: "Gʻulom" }} />);
    expect(screen.getByText('"Gʻulom"').textContent).toBe('"Gʻulom"');
  });

  it("collapses and expands a branch", () => {
    render(<JsonViewer value={{ brief: { language: "uz" } }} defaultExpandedDepth={2} />);
    expect(screen.getByText(/"uz"/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /collapse \$\.brief/ }));
    expect(screen.queryByText(/"uz"/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /expand \$\.brief/ }));
    expect(screen.getByText(/"uz"/)).toBeInTheDocument();
  });

  it("offers an absolute copy-path for a nested value", () => {
    render(<JsonViewer value={{ stages: [{ errorCode: "TIMEOUT" }] }} defaultExpandedDepth={4} />);
    // Absolute, because the paste target is a jq filter or a bug report.
    expect(screen.getByRole("button", { name: "copy path $.stages[0].errorCode" })).toBeVisible();
  });

  it("distinguishes null from a missing value", () => {
    render(<JsonViewer value={{ deliveredAt: null }} />);
    expect(screen.getByText("null")).toBeInTheDocument();
  });

  it("summarises a collapsed branch by size", () => {
    render(<JsonViewer value={{ items: [1, 2, 3] }} defaultExpandedDepth={1} />);
    expect(screen.getByText(/3 entries/)).toBeInTheDocument();
  });
});
