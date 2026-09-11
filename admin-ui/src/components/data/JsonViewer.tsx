/**
 * `JsonViewer` — collapsible, copy-path, and **client-side redaction as belt-and-braces**
 * (§11.4).
 *
 * The redaction here is the second belt, not the first. §12.3 is explicit that masking is
 * server-side, in `bayram/admin/serializers/redaction.py`, applied at the response boundary:
 * "not a CSS blur, not a client toggle — an unmasked value must never be in a JSON payload
 * the operator did not explicitly request". That control is the one that matters, and this
 * one cannot substitute for it: the value is already in the browser's memory by the time
 * this component sees it, so a reader with devtools open is not stopped by anything here.
 *
 * What it does buy is real anyway: `*_api_key`, `*token`, `*secret` and `*_url` are the
 * fields §12.3 marks **"never returned at any role, revealed or not"**, so one of them
 * appearing in a payload is a server bug — and the failure mode of that bug is a credential
 * on a shared screen, in a screenshot pasted into Slack, or in a support recording. Masking
 * them on the way to the DOM turns that from an exposure into an anomaly the operator can
 * see and report. Hence `data-redacted`, so a test can assert the key never rendered.
 *
 * The redaction rule itself lives in `redaction.ts`; this file applies it.
 *
 * ## The syntax theme
 *
 * Keys `--info`, strings `--success`, numbers `--caution`, booleans `--accent`, everything
 * structural `--ink-muted`, on the `--surface-sunken` well. Every one of those is a TEXT-bar
 * token measured on all five surfaces in both palettes.
 *
 * That is the fix for a real bug rather than a restyle. The old theme was built from the
 * `-hi` variants (`text-cyan-hi`, `text-green-hi`, `text-amber-hi`, `text-violet-hi`) on
 * `--bg-inset` — and all five of those were defined ONLY in the dark `:root` block. The light
 * theme never redefined any of them, so a light-theme payload rendered a dark syntax theme on
 * a dark well embedded in a white page, and no test could see it because jsdom does not
 * compute colour.
 */

import { useCallback, useMemo, useState, type ReactElement } from "react";

import { MASK } from "@/api";
import { cn, formatInteger } from "@/lib";

import { isRedactedKey } from "./redaction";
import { useCopy } from "./useCopy";

export interface JsonViewerProps {
  /** Anything `JSON.parse` could have produced. */
  readonly value: unknown;
  /** The root's name in a copied path. `$` by default. */
  readonly rootLabel?: string;
  /** How deep the tree starts expanded. `1` shows the root's own keys. */
  readonly defaultExpandedDepth?: number;
  readonly className?: string;
  /** Names the tree for assistive tech. */
  readonly label?: string;
}

export function JsonViewer({
  value,
  rootLabel = "$",
  defaultExpandedDepth = 1,
  className,
  label = "JSON",
}: JsonViewerProps): ReactElement {
  return (
    <div
      className={cn(
        "type-mono overflow-auto rounded-2xl bg-surface-sunken p-4 text-ink",
        className,
      )}
      role="tree"
      aria-label={label}
    >
      <JsonNode
        name={null}
        value={value}
        path={rootLabel}
        depth={0}
        defaultExpandedDepth={defaultExpandedDepth}
        isRedacted={false}
      />
    </div>
  );
}

interface JsonNodeProps {
  readonly name: string | null;
  readonly value: unknown;
  readonly path: string;
  readonly depth: number;
  readonly defaultExpandedDepth: number;
  readonly isRedacted: boolean;
}

function JsonNode({
  name,
  value,
  path,
  depth,
  defaultExpandedDepth,
  isRedacted,
}: JsonNodeProps): ReactElement {
  const [isOpen, setIsOpen] = useState(depth < defaultExpandedDepth);
  const { copy, isCopied } = useCopy();

  const onCopyPath = useCallback(() => {
    copy(path);
  }, [copy, path]);

  const entries = useMemo(() => childEntries(value, path), [value, path]);
  const isBranch = entries !== null && !isRedacted;

  const key =
    name === null ? null : (
      <span className="text-info">
        {'"'}
        {name}
        {'"'}
        <span className="text-ink-muted">: </span>
      </span>
    );

  return (
    <div
      role="treeitem"
      aria-expanded={isBranch ? isOpen : undefined}
      data-path={path}
      data-redacted={isRedacted ? "true" : undefined}
      className={depth === 0 ? undefined : "border-l border-hairline pl-3"}
    >
      <div className="group flex items-baseline gap-1">
        {isBranch ? (
          <button
            type="button"
            onClick={() => {
              setIsOpen((open) => !open);
            }}
            aria-label={`${isOpen ? "collapse" : "expand"} ${path}`}
            className="w-3 shrink-0 text-ink-muted transition-colors duration-fast ease-standard hover:text-ink"
          >
            <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
          </button>
        ) : (
          <span className="w-3 shrink-0" aria-hidden="true" />
        )}

        {key}

        {isRedacted ? (
          <RedactedValue />
        ) : isBranch ? (
          <span className="text-ink-muted">
            {Array.isArray(value) ? "[" : "{"}
            {isOpen ? "" : ` ${describeSize(entries)} `}
            {isOpen ? "" : Array.isArray(value) ? "]" : "}"}
          </span>
        ) : (
          <LeafValue value={value} />
        )}

        <button
          type="button"
          onClick={onCopyPath}
          aria-label={`copy path ${path}`}
          title={path}
          className="ml-1 shrink-0 text-ink-muted opacity-0 transition-opacity duration-fast ease-standard focus-visible:opacity-100 group-hover:opacity-100"
        >
          <span aria-hidden="true">{isCopied ? "✓" : "⧉"}</span>
        </button>
      </div>

      {isBranch && isOpen && (
        <div role="group">
          {entries.map((entry) => (
            <JsonNode
              key={entry.path}
              name={entry.name}
              value={entry.value}
              path={entry.path}
              depth={depth + 1}
              defaultExpandedDepth={defaultExpandedDepth}
              isRedacted={entry.isRedacted}
            />
          ))}
          <div className="pl-3 text-ink-muted">{Array.isArray(value) ? "]" : "}"}</div>
        </div>
      )}
    </div>
  );
}

function RedactedValue(): ReactElement {
  return (
    <span
      /* An OPAQUE ground, not `--error-tint`. The tree sits on `--surface-sunken`, and a 14%
         tint is only ever measured composited over the card and over the page — over the
         sunken well it lands low enough to put `--error` under 4.5:1 in the light palette. */
      className="inline-flex items-center gap-1 rounded-pill bg-surface-card px-2 text-error shadow-2xs"
      title="Redacted in the browser. This field is never returned at any role (§12.3) — seeing one here is a server bug worth reporting."
    >
      <span aria-hidden="true">⊘</span>
      <span>{MASK}</span>
      <span className="type-caption">redacted</span>
    </span>
  );
}

function LeafValue({ value }: { readonly value: unknown }): ReactElement {
  if (value === null) return <span className="text-ink-muted">null</span>;
  if (value === undefined) return <span className="text-ink-muted">undefined</span>;
  if (typeof value === "boolean") {
    return <span className="text-accent">{value ? "true" : "false"}</span>;
  }
  if (typeof value === "number") {
    return <span className="num text-caution">{String(value)}</span>;
  }
  if (typeof value === "string") {
    // Rendered verbatim between quotes. No normalise, no case folding, no truncation: a
    // string in here may be a recipient name, and `oʻ` must survive the round trip.
    return (
      <span className="text-success">
        {'"'}
        {value}
        {'"'}
      </span>
    );
  }
  /* Nothing `JSON.parse` produces reaches here — a function or a symbol would, and
     `String(anObject)` renders "[object Object]", which reads as a value rather than as
     "this viewer was handed something that is not JSON". */
  return <span className="text-ink-muted">{typeof value}</span>;
}

interface JsonEntry {
  readonly name: string;
  readonly value: unknown;
  readonly path: string;
  readonly isRedacted: boolean;
}

/**
 * `null` for a leaf; the children for an object or an array.
 *
 * Paths are absolute (`$.stages[2].errorCode`), because the whole point of copy-path is
 * pasting it into a jq filter or a bug report where the root is not in view.
 */
function childEntries(value: unknown, parentPath: string): readonly JsonEntry[] | null {
  if (Array.isArray(value)) {
    return (value as readonly unknown[]).map((item, index) => ({
      name: String(index),
      value: item,
      path: `${parentPath}[${String(index)}]`,
      // An array index is not a key name, so it cannot trip the pattern. A redacted key
      // holding an array is masked whole, one level up.
      isRedacted: false,
    }));
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries<unknown>(value as Record<string, unknown>).map(([name, item]) => ({
      name,
      value: item,
      path: `${parentPath}.${name}`,
      isRedacted: isRedactedKey(name),
    }));
  }
  return null;
}

function describeSize(entries: readonly JsonEntry[]): string {
  const count = entries.length;
  return `${formatInteger(count)} ${count === 1 ? "entry" : "entries"}`;
}
