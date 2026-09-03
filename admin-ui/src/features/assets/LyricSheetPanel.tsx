/**
 * `GET /api/assets/{id}/text` — the lyric sheet, revealed on a click and hidden on another.
 *
 * §12.3 puts a lyric sheet in the same class as a greeting's audio: it names the recipient,
 * so reading it **is** a reveal. The route says so mechanically — a step-up scoped to this
 * asset id, one unit of the reveal budget, and an audit row, all decided before a character
 * comes back — and this panel is the operator's side of that transaction.
 *
 * ## Why this is a mutation and never a query
 *
 * `/stream` audits the first request per `(actor, asset)` per ten-minute window, because an
 * `<audio>` element issues many. `/text` has **no such window**: one request returns the
 * whole sheet, so a second read is a second disclosure, separately charged and separately
 * audited. A cached query is a thing an invalidation can refetch, and an invalidation
 * nobody asked for would spend an operator's budget and write a row they did not cause. So
 * it is click-driven, uncached, and **Hide** really removes the text from the DOM rather
 * than collapsing it — the plaintext is not left in the tree for a screenshot to find.
 *
 * ## The audio half is deliberately NOT here
 *
 * `AssetCard` owns the play button, and it should: the card is rendered on `/assets`, on
 * order detail and on user detail, and playback has to be offered identically on all three.
 * A second play control on this screen would mean two buttons for one reveal and two
 * authorisations for one stream. This panel renders for lyric rows only.
 *
 * ## The step-up prompt is here rather than in a dialog
 *
 * `/text` is an `A+S` cell: `REVEAL_MEDIA_READ` gates the router by ROLE, and the handler
 * separately demands a step-up scoped to `str(asset_id)`. A `PermissionGate` therefore
 * hides the control from a VIEWER but proves nothing about the grant, and the only honest
 * way to discover whether one exists is to ask and be refused. So the refusal IS the
 * prompt: `STEP_UP_REQUIRED` renders a password field, and confirming it re-runs the reveal
 * that was refused. Nothing is asked for pre-emptively, and no state here claims to know
 * what the server will decide.
 */

import { useMutation } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import {
  failureOf,
  getAssetText,
  postStepUp,
  unwrapAsync,
  type AssetTextView,
  type AssetWireView,
} from "@/api";
import { Button, ErrorState, PermissionGate } from "@/components/util";
import { cn } from "@/lib";

import { assetMediaKind } from "./mediaKinds";

export const LYRICS_ARE_A_REVEAL_HINT =
  "Every read of the sheet is charged and audited — there is no ten-minute window here the way there is on playback.";

/** §12.2's row for "stream audio or read lyric text": `—` for VIEWER, `A+S` above it. */
const REVEAL_PERMISSION = "reveal.media" as const;

/** What a role with no media-reveal cell sees instead of the control. */
export const NO_REVEAL_CELL_LABEL =
  "Your role holds no media-reveal cell, so this sheet is metadata only.";

export interface LyricSheetPanelProps {
  readonly asset: AssetWireView;
  readonly className?: string | undefined;
}

/**
 * Renders nothing at all for an asset the text route will not serve.
 *
 * `assetMediaKind` matches the whole mime, exactly as the server does. A row `/text` would
 * answer 415 to gets no button rather than one that fails: §11.4's rule about role-based
 * HIDING — "a disabled button nobody can explain is worse than an absent one" — applies to
 * formats as well as to roles.
 */
export function LyricSheetPanel({ asset, className }: LyricSheetPanelProps): ReactElement | null {
  if (assetMediaKind(asset.mime) !== "lyrics") return null;

  return (
    <section
      data-testid="lyric-sheet-panel"
      aria-label="lyric sheet"
      className={cn("flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card", className)}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="type-h2 text-ink">lyric sheet</h3>
        <span className="type-mono text-ink-muted">{asset.mime}</span>
      </header>

      <PermissionGate
        permission={REVEAL_PERMISSION}
        fallback={
          <p className="type-body-sm text-ink-muted" data-testid="lyric-sheet-no-cell">
            {NO_REVEAL_CELL_LABEL}
          </p>
        }
      >
        <LyricSheetControl asset={asset} />
      </PermissionGate>
    </section>
  );
}

/**
 * Reveal, read, hide.
 *
 * The sheet is rendered in a `<pre lang="uz-Latn" dir="ltr">` and nothing is done to the
 * string on the way — no trim, no slice, no case folding. It is not routed through
 * `<NameText>` because that component is an inline single-VALUE renderer with a codepoint
 * toggle, and a lyric sheet is a multi-line document; what matters is the guarantee, and
 * this carries the same one. `whitespace-pre-wrap` keeps the line breaks the renderer put
 * there, because a lyric whose lines have been reflowed is not the lyric that was sung.
 */
function LyricSheetControl({ asset }: { readonly asset: AssetWireView }): ReactElement {
  const [sheet, setSheet] = useState<AssetTextView | null>(null);

  const reveal = useMutation({
    mutationFn: () => unwrapAsync(getAssetText(asset.id)),
    onSuccess: (data) => {
      setSheet(data);
    },
  });

  const failure = failureOf(reveal.error);
  const needsStepUp = failure?.code === "STEP_UP_REQUIRED";

  if (sheet !== null) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="type-caption text-ink-muted">revealed — this read is in the audit log</span>
          {/* Dismissive, so `quiet` — no ground of its own. */}
          <Button
            variant="quiet"
            size="sm"
            shape="pill"
            data-testid="lyric-sheet-hide"
            onClick={() => {
              setSheet(null);
              reveal.reset();
            }}
          >
            Hide
          </Button>
        </div>
        <pre
          data-testid="lyric-sheet-text"
          lang="uz-Latn"
          dir="ltr"
          className="type-mono max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-2xl bg-surface-sunken p-4 text-ink"
        >
          {sheet.text}
        </pre>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {/* Revealing costs budget and writes an audit row, so it is the panel's one primary
          action and wears the primary button. */}
      <Button
        variant="primary"
        shape="pill"
        className="self-start"
        data-testid="lyric-sheet-reveal"
        disabled={reveal.isPending}
        onClick={() => {
          reveal.mutate();
        }}
      >
        {reveal.isPending ? "Revealing…" : "Reveal the lyric sheet"}
      </Button>
      <p className="type-body-sm text-ink-muted">{LYRICS_ARE_A_REVEAL_HINT}</p>

      {needsStepUp ? (
        <StepUpPrompt
          assetId={asset.id}
          onGranted={() => {
            reveal.mutate();
          }}
        />
      ) : reveal.isError ? (
        <ErrorState
          error={reveal.error}
          what="the lyric sheet"
          onRetry={() => {
            reveal.mutate();
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * Confirm the password for ONE asset.
 *
 * `scope` is the ACTION alone (`"reveal"`) and `subjectId` is the asset id; the server
 * composes the `action:subject` pair and stores it on the session. Sending a composed pair
 * here is a 422, and sending a different subject grants a scope that will not admit this
 * asset — which would look like a step-up that silently did nothing.
 *
 * The field is never pre-filled, the value never leaves this component, and it is cleared
 * on success: the grant lives on the session server-side and there is nothing worth keeping
 * on this side of it.
 */
function StepUpPrompt({
  assetId,
  onGranted,
}: {
  readonly assetId: string;
  readonly onGranted: () => void;
}): ReactElement {
  const [password, setPassword] = useState("");
  const grant = useMutation({
    mutationFn: (secret: string) =>
      unwrapAsync(postStepUp({ password: secret, scope: "reveal", subjectId: assetId })),
    onSuccess: () => {
      setPassword("");
      onGranted();
    },
  });

  return (
    <form
      data-testid="lyric-sheet-step-up"
      className="flex flex-col gap-2 rounded-2xl bg-surface-control p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (password === "") return;
        grant.mutate(password);
      }}
    >
      <label htmlFor="lyric-sheet-step-up-password" className="type-body-sm font-semibold text-ink">
        Confirm your password to reveal this sheet
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id="lyric-sheet-step-up-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
          className="type-body-sm min-w-0 flex-1 rounded-control bg-surface-card px-3 py-2 text-ink"
        />
        <Button
          type="submit"
          variant="primary"
          shape="pill"
          className="px-4"
          disabled={grant.isPending || password === ""}
        >
          {grant.isPending ? "Confirming…" : "Confirm"}
        </Button>
      </div>
      {grant.isError ? <ErrorState error={grant.error} what="the confirmation" /> : null}
    </form>
  );
}
