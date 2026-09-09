/**
 * The client half of `render_body_html` — the one function that decides how long a message is.
 *
 * `hbd/admin/schemas/broadcasts.py` measures a body TWICE against the same ceiling: the raw text
 * the operator typed, and the string that will actually reach Telegram once literal runs are
 * escaped and allowlisted tags are re-emitted. Neither bound implies the other — `&` is one
 * character typed and five on the wire, `&nbsp;` is six typed and one rendered — so a counter
 * over `text.length` alone is a counter that lets a 4 096-character body of ampersands through
 * and then loses the whole campaign to a 422 nobody could have predicted from the editor.
 *
 * So this module is a transcription, not an approximation. It follows Python's `HTMLParser` with
 * `convert_charrefs=True` and the module's own eleven refusals, in the same order, and it counts
 * in CODE POINTS because `len()` does — an emoji is one character to the server and two to
 * `String.prototype.length`.
 *
 * **The scan produces a tree as well as a string.** The rendered string is what gets measured;
 * the tree is what the preview draws, as React elements — `<b>`, `<i>`, an `<a href>` whose URL
 * passed {@link isTelegramButtonUrl}. Nothing here ever reaches `dangerouslySetInnerHTML`: the
 * body is operator-authored text that has been stored and read back, and a panel that parsed it
 * with the browser would be injecting a stored string into the console's own document. Parsing
 * it ourselves and mapping the result onto elements is what makes the preview a rendering of the
 * message rather than a rendering of whatever the string turns out to be.
 *
 * **The server is still the authority.** Two edges are deliberately simpler here: an attribute
 * value containing `>` ends the tag early (the server's URL rule forbids `>` anyway, so both
 * layers refuse — they just name different rules), and character references are decoded by the
 * browser's own RCDATA parser, which is the same table Python's is generated from but not the
 * same code. Every refusal below is a refusal the server also makes; none of them is invented
 * here, and where the two could disagree this one refuses first and cheaply.
 */

import { TELEGRAM_BODY_TAGS, isTelegramButtonUrl, type TelegramBodyTag } from "@/api/broadcasts";

/* -------------------------------------------------------------------------- */
/* What a body can be refused for                                              */
/* -------------------------------------------------------------------------- */

/**
 * The closed set of refusals, one per rule the server states in words.
 *
 * `tooLong`, `buttonPair`, `badUrl`, `badStorageKey` and `empty` are the model validators;
 * everything else comes out of the markup scan. Each maps to one sentence in the catalogue, so an
 * operator reads the rule rather than the parser.
 */
export const BODY_ISSUE_CODES = [
  "empty",
  "blankText",
  "incompleteTag",
  "unknownTag",
  "badAttribute",
  "selfClosing",
  "unbalanced",
  "nestedLink",
  "notMarkup",
  "badHref",
  "tooLong",
  "badUrl",
  "buttonPair",
  "badStorageKey",
] as const;
export type BodyIssueCode = (typeof BODY_ISSUE_CODES)[number];

/* -------------------------------------------------------------------------- */
/* The tree the preview draws                                                  */
/* -------------------------------------------------------------------------- */

export interface BodyTextNode {
  readonly kind: "text";
  /** Decoded, NOT escaped: this is the text a recipient reads. */
  readonly text: string;
}

export interface BodyTagNode {
  readonly kind: "tag";
  readonly tag: TelegramBodyTag;
  /** Only ever set on `a`, and only ever a URL {@link isTelegramButtonUrl} accepted. */
  readonly href: string | null;
  readonly children: readonly BodyNode[];
}

export type BodyNode = BodyTextNode | BodyTagNode;

export interface BodyScanOk {
  readonly ok: true;
  /** Byte for byte what the sender will hand Telegram. What the length rule measures. */
  readonly rendered: string;
  /** In CODE POINTS, because `len()` counts code points and the ceiling is Python's. */
  readonly renderedLength: number;
  /** Every literal run concatenated — the words, with no markup. Blank means blank. */
  readonly literal: string;
  readonly nodes: readonly BodyNode[];
}

export interface BodyScanFailed {
  readonly ok: false;
  readonly code: BodyIssueCode;
}

export type BodyScan = BodyScanOk | BodyScanFailed;

/* -------------------------------------------------------------------------- */
/* Escaping — `hbd.bot.i18n.escape_html`, and `html.escape(quote=True)` for a href */
/* -------------------------------------------------------------------------- */

/** `html.escape(value, quote=False)`: the three characters that can start markup, and no more. */
export function escapeBodyText(value: string): string {
  return value.replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;");
}

/** `html.escape(value, quote=True)` — what the re-emitted `<a href="…">` is built with. */
export function escapeBodyAttribute(value: string): string {
  return escapeBodyText(value).replace(/"/gu, "&quot;").replace(/'/gu, "&#x27;");
}

/** `len()` — code points, so one emoji costs the operator one character and not two. */
export function codePointLength(value: string): number {
  /*
   * Walked by code point, not by UTF-16 unit and not by grapheme. `len()` is what the server
   * measures with, so an emoji outside the BMP costs the operator ONE character here exactly as
   * it costs one there — while `"…".length` would charge two and an `Intl.Segmenter` pass would
   * charge one for a flag that Python counts as two.
   */
  let count = 0;
  let index = 0;
  while (index < value.length) {
    const code = value.codePointAt(index);
    index += code !== undefined && code > 0xffff ? 2 : 1;
    count += 1;
  }
  return count;
}

/* -------------------------------------------------------------------------- */
/* Character references                                                        */
/* -------------------------------------------------------------------------- */

/**
 * `convert_charrefs=True`, borrowed from the browser's own RCDATA parser.
 *
 * A detached `<textarea>` parses its `innerHTML` as text — no element is ever created, no script
 * can run — and hands back the decoded string, which is exactly what `HTMLParser` gives its
 * `handle_data`. It is applied only to runs this module has ALREADY established contain no tag,
 * so nothing that could open an element reaches it. Without a DOM (a node script, a test double)
 * the raw run is returned: a count that is right for every body without an entity in it is a
 * better failure than a crash.
 */
function decodeCharacterReferences(raw: string): string {
  if (!raw.includes("&")) return raw;
  if (typeof document === "undefined") return raw;
  const decoder = document.createElement("textarea");
  decoder.innerHTML = raw;
  return decoder.value;
}

/* -------------------------------------------------------------------------- */
/* The scan                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * What may follow a `<` for `HTMLParser` to read it as the start of anything but text. A `<`
 * followed by a space or a digit is a character somebody typed, which is why `5 < 6` needs no
 * escaping by the operator.
 */
const TAG_OPEN_CHARS = /[A-Za-z!?/]/u;

const ATTRIBUTE = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/gu;

const TAG_SET: ReadonlySet<string> = new Set(TELEGRAM_BODY_TAGS);

function isTelegramTag(name: string): name is TelegramBodyTag {
  return TAG_SET.has(name);
}

/**
 * Whether the text ends inside a tag that never closed.
 *
 * Checked BEFORE the scan, exactly as the server checks it, because `HTMLParser` does not report
 * it: it DISCARDS the unterminated tag and every character after it, so `"a <b"` reaches the
 * handlers as `"a "` alone and a message would silently lose its tail. An unterminated tag can
 * only be the last one, so the final `<` is the only position worth testing.
 */
export function hasUnterminatedTag(text: string): boolean {
  const opened = text.lastIndexOf("<");
  if (opened < 0 || text.slice(opened).includes(">")) return false;
  return TAG_OPEN_CHARS.test(text.charAt(opened + 1));
}

interface OpenTag {
  readonly tag: TelegramBodyTag;
  readonly href: string | null;
  readonly children: BodyNode[];
}

function attributesOf(rest: string): readonly (readonly [string, string | null])[] {
  const attributes: (readonly [string, string | null])[] = [];
  ATTRIBUTE.lastIndex = 0;
  let match = ATTRIBUTE.exec(rest);
  while (match !== null) {
    const raw = match[2] ?? match[3] ?? match[4];
    attributes.push([
      (match[1] ?? "").toLowerCase(),
      raw === undefined ? null : decodeCharacterReferences(raw),
    ]);
    match = ATTRIBUTE.exec(rest);
  }
  return attributes;
}

/**
 * One pass over a body: the wire string, the words inside it, and the tree the preview draws —
 * or the first rule it broke.
 */
export function scanBody(text: string): BodyScan {
  if (hasUnterminatedTag(text)) return { ok: false, code: "incompleteTag" };

  const parts: string[] = [];
  const literal: string[] = [];
  const root: BodyNode[] = [];
  const open: OpenTag[] = [];

  const siblings = (): BodyNode[] => open[open.length - 1]?.children ?? root;

  function emitText(raw: string): void {
    if (raw === "") return;
    const decoded = decodeCharacterReferences(raw);
    literal.push(decoded);
    parts.push(escapeBodyText(decoded));
    siblings().push({ kind: "text", text: decoded });
  }

  let index = 0;
  while (index < text.length) {
    const opened = text.indexOf("<", index);
    if (opened < 0) {
      emitText(text.slice(index));
      break;
    }
    if (!TAG_OPEN_CHARS.test(text.charAt(opened + 1))) {
      // A `<` that cannot begin a tag is data, and the run it ends is data up to and including it.
      emitText(text.slice(index, opened + 1));
      index = opened + 1;
      continue;
    }
    emitText(text.slice(index, opened));

    const marker = text.charAt(opened + 1);
    // A comment, a doctype or a processing instruction is not markup Telegram parses, and
    // dropping it — `HTMLParser`'s default — would be the silent strip this rule exists to avoid.
    if (marker === "!" || marker === "?") return { ok: false, code: "notMarkup" };

    const closed = text.indexOf(">", opened);
    if (closed < 0) return { ok: false, code: "incompleteTag" };
    const inner = text.slice(opened + 1, closed);
    index = closed + 1;

    if (marker === "/") {
      const name = inner.slice(1).trim().toLowerCase();
      const top = open[open.length - 1];
      // Both directions of unbalanced: a stray close, and a close that crosses another tag's
      // span. `<b><i>x</b></i>` is refused because the operator meant the nesting they typed.
      if (top === undefined || top.tag !== name) return { ok: false, code: "unbalanced" };
      open.pop();
      parts.push(`</${top.tag}>`);
      siblings().push({ kind: "tag", tag: top.tag, href: top.href, children: top.children });
      continue;
    }

    const named = /^([A-Za-z][^\s/>]*)/u.exec(inner);
    const raw = named?.[1];
    if (raw === undefined) return { ok: false, code: "unknownTag" };
    const name = raw.toLowerCase();
    const rest = inner.slice(raw.length);
    // None of Telegram's tags is void, so `<b/>` is a typo or markup from somewhere else.
    if (rest.trimEnd().endsWith("/")) return { ok: false, code: "selfClosing" };
    if (!isTelegramTag(name)) return { ok: false, code: "unknownTag" };

    const attributes = attributesOf(rest);
    if (name === "a") {
      if (open.some((entry) => entry.tag === "a")) return { ok: false, code: "nestedLink" };
      const first = attributes[0];
      if (attributes.length !== 1 || first === undefined || first[0] !== "href") {
        return { ok: false, code: "badAttribute" };
      }
      const href = first[1];
      if (href === null || !isTelegramButtonUrl(href)) return { ok: false, code: "badHref" };
      parts.push(`<a href="${escapeBodyAttribute(href)}">`);
      open.push({ tag: "a", href, children: [] });
      continue;
    }

    if (attributes.length > 0) return { ok: false, code: "badAttribute" };
    parts.push(`<${name}>`);
    open.push({ tag: name, href: null, children: [] });
  }

  if (open.length > 0) return { ok: false, code: "unbalanced" };

  const rendered = parts.join("");
  return {
    ok: true,
    rendered,
    renderedLength: codePointLength(rendered),
    literal: literal.join(""),
    nodes: root,
  };
}

/* -------------------------------------------------------------------------- */
/* The media key                                                               */
/* -------------------------------------------------------------------------- */

const KEY_ALLOWED = /^[A-Za-z0-9._-]+$/u;
const PARENT_SEGMENT = "..";

/**
 * Whether a value is shaped like a key this deployment's own uploader wrote — `_is_storage_key`.
 *
 * An object-store key NAMES a file we already hold; it is not a path this panel composes. `..`
 * is refused outright rather than normalised, because the only reader is a storage client and
 * the only thing traversal buys is a file the operator was not shown.
 */
export function isMediaStorageKey(raw: string): boolean {
  if (raw === "" || raw.startsWith("/") || raw.endsWith("/")) return false;
  return raw
    .split("/")
    .every((segment) => segment !== "" && segment !== PARENT_SEGMENT && KEY_ALLOWED.test(segment));
}
