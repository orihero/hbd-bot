/**
 * The body rules, measured against the server's own.
 *
 * Every expectation here is transcribed from `bayram/admin/schemas/broadcasts.py` — the escaping
 * (`html.escape(quote=False)`), the two length ceilings applied to the raw AND the rendered
 * string, the tag allowlist, and the four refusals a stripper would have swallowed. If one of
 * these ever disagrees with the server, this file is where the disagreement shows up rather than
 * in a 422 that arrives after an audience has been counted.
 */

import { describe, expect, it } from "vitest";

import { MAX_BROADCAST_BODY_CHARS, MAX_BROADCAST_CAPTION_CHARS } from "@/api/constants";

import { codePointLength, isMediaStorageKey, scanBody } from "./bodyMarkup";
import { EMPTY_BODY, bodyIssues, type BodyDraft } from "./wizardState";

function bodyOf(overrides: Partial<BodyDraft>): BodyDraft {
  return { ...EMPTY_BODY, ...overrides };
}

function codesOf(body: BodyDraft): readonly string[] {
  return bodyIssues(body).map((issue) => issue.code);
}

describe("scanBody — the string that will actually be sent", () => {
  it("escapes the three markup characters and nothing else", () => {
    const scan = scanBody("Tom & Jerry");
    expect(scan.ok).toBe(true);
    if (!scan.ok) return;
    // `&` is ONE character typed and FIVE on the wire. This is the whole reason the counter
    // cannot be `value.length`.
    expect(scan.rendered).toBe("Tom &amp; Jerry");
    expect(scan.renderedLength).toBe(15);
  });

  it("is idempotent on its own output: `&` and `&amp;` render identically", () => {
    const typed = scanBody("a & b");
    const pasted = scanBody("a &amp; b");
    expect(typed.ok && pasted.ok).toBe(true);
    if (!typed.ok || !pasted.ok) return;
    expect(pasted.rendered).toBe(typed.rendered);
  });

  it("renders a character reference SHORTER when the reference is longer than the character", () => {
    const scan = scanBody("a&nbsp;b");
    expect(scan.ok).toBe(true);
    if (!scan.ok) return;
    // Six characters typed, one on the wire: neither bound implies the other.
    expect(scan.renderedLength).toBe(3);
  });

  it("treats a `<` that cannot begin a tag as text", () => {
    const scan = scanBody("5 < 6");
    expect(scan.ok).toBe(true);
    if (!scan.ok) return;
    expect(scan.rendered).toBe("5 &lt; 6");
  });

  it("keeps allowlisted tags and re-emits them canonically", () => {
    const scan = scanBody("<B>bold</B> and <i>italic</i>");
    expect(scan.ok).toBe(true);
    if (!scan.ok) return;
    expect(scan.rendered).toBe("<b>bold</b> and <i>italic</i>");
    expect(scan.literal).toBe("bold and italic");
  });

  it("keeps a link whose href is absolute http(s), and escapes the attribute", () => {
    const scan = scanBody('<a href="https://example.com/a?b=1">here</a>');
    expect(scan.ok).toBe(true);
    if (!scan.ok) return;
    expect(scan.rendered).toBe('<a href="https://example.com/a?b=1">here</a>');
  });

  it("refuses every rule the server refuses, by name", () => {
    const cases: readonly (readonly [string, string])[] = [
      ["<script>x</script>", "unknownTag"],
      ['<b class="x">y</b>', "badAttribute"],
      ["<b/>", "selfClosing"],
      ["<b><i>x</b></i>", "unbalanced"],
      ["x</b>", "unbalanced"],
      ["<b>x", "unbalanced"],
      ["a <b", "incompleteTag"],
      ["<!-- hidden -->x", "notMarkup"],
      ['<a href="https://a.example/"><a href="https://b.example/">x</a></a>', "nestedLink"],
      ['<a href="/relative">x</a>', "badHref"],
      ['<a href="javascript:alert(1)">x</a>', "badHref"],
      ['<a href="https://user:pw@example.com/">x</a>', "badHref"],
    ];
    for (const [text, code] of cases) {
      const scan = scanBody(text);
      expect(scan.ok, text).toBe(false);
      if (scan.ok) continue;
      expect(scan.code, text).toBe(code);
    }
  });

  it("counts code points, because the server counts with `len()`", () => {
    expect(codePointLength("🎂")).toBe(1);
    expect("🎂".length).toBe(2);
  });
});

describe("bodyIssues — the same ceilings, chosen the same way", () => {
  it("accepts a body exactly at the limit and refuses the character after it", () => {
    expect(codesOf(bodyOf({ text: "a".repeat(MAX_BROADCAST_BODY_CHARS) }))).toEqual([]);
    expect(codesOf(bodyOf({ text: "a".repeat(MAX_BROADCAST_BODY_CHARS + 1) }))).toContain(
      "tooLong",
    );
  });

  it("measures the RENDERED string too: a body of ampersands is five times its own length", () => {
    // 1 000 ampersands is 1 000 characters typed and 5 000 on the wire. The raw bound passes;
    // the rendered one does not, and the server applies both.
    const issues = bodyIssues(bodyOf({ text: "&".repeat(1_000) }));
    const tooLong = issues.find((issue) => issue.code === "tooLong");
    expect(tooLong).toBeDefined();
    expect(tooLong?.limit).toBe(MAX_BROADCAST_BODY_CHARS);
    expect(tooLong?.actual).toBe(5_000);
  });

  it("drops the ceiling to a caption's the moment an image is attached", () => {
    const text = "a".repeat(MAX_BROADCAST_CAPTION_CHARS + 1);
    expect(codesOf(bodyOf({ text }))).toEqual([]);
    const withImage = bodyOf({ text, mediaStorageKey: "broadcasts/2026/promo.jpg" });
    const tooLong = bodyIssues(withImage).find((issue) => issue.code === "tooLong");
    expect(tooLong?.limit).toBe(MAX_BROADCAST_CAPTION_CHARS);
  });

  it("refuses a body that is only markup", () => {
    expect(codesOf(bodyOf({ text: "<b> </b>" }))).toContain("blankText");
  });

  it("refuses half a button, in either direction, and accepts neither half", () => {
    expect(codesOf(bodyOf({ text: "hi", buttonLabel: "Open" }))).toContain("buttonPair");
    expect(
      codesOf(bodyOf({ text: "hi", buttonUrl: "https://example.com/" })),
    ).toContain("buttonPair");
    expect(codesOf(bodyOf({ text: "hi" }))).toEqual([]);
    expect(
      codesOf(bodyOf({ text: "hi", buttonLabel: "Open", buttonUrl: "https://example.com/" })),
    ).toEqual([]);
  });

  it("refuses a button URL that is not an absolute public http(s) address", () => {
    for (const url of ["/orders", "tg://resolve?domain=x", "https://intranet/", "http://a.b c/"]) {
      expect(codesOf(bodyOf({ text: "hi", buttonLabel: "Open", buttonUrl: url })), url).toContain(
        "badUrl",
      );
    }
  });

  it("refuses a media key that is a path rather than a key this deployment wrote", () => {
    expect(isMediaStorageKey("broadcasts/2026/promo.jpg")).toBe(true);
    expect(isMediaStorageKey("../secrets/key.pem")).toBe(false);
    expect(isMediaStorageKey("/leading/slash")).toBe(false);
    expect(codesOf(bodyOf({ text: "hi", mediaStorageKey: "../etc/passwd" }))).toContain(
      "badStorageKey",
    );
  });
});
