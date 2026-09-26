import { useState, type JSX } from "react";

import { cn } from "@/lib/cn";

/**
 * The kit's 32px circle with its 8px status dot, drawn against two facts about this API.
 *
 * **The image is a same-origin subresource.** `UserView.avatarUrl` is composed by the ROUTER
 * (`GET /api/users/{id}/avatar`) and this SPA never builds an avatar path — no id in a query
 * string, no id in a fragment. The browser sends the session cookie with the `<img>` request
 * because it is same-origin; nothing here has to arrange that, and nothing here should try.
 *
 * **`hasAvatar` is a claim, not a guarantee.** The bytes can be gone, the fetch can have been
 * stale, and the route answers 404. So the image is never trusted: a failed load falls back to
 * the monogram in the same 32px circle, which is why `initials` is required even when a `src`
 * is present. A broken-image glyph in a customer list is a bug report.
 *
 * The monogram is built by the CALLER, from masked text only. This component never derives
 * initials from a name field itself, because the only name fields it could reach are the ones
 * that are masked by default and revealed only through `POST /api/reveal` — deriving a letter
 * from a revealed name would leak it into a place with no audit row and no lifetime.
 */

export type AvatarStatus = "ok" | "warning" | "danger" | "muted";

const DOT_TONE: Record<AvatarStatus, string> = {
  ok: "bg-status-ok",
  warning: "bg-warn",
  danger: "bg-required",
  muted: "bg-ink-300",
};

interface AvatarProps {
  /** `UserView.avatarUrl`, verbatim. `null` when there is none. */
  readonly src?: string | null | undefined;
  /** One or two characters, from MASKED text. Rendered when there is no image or it 404s. */
  readonly initials: string;
  /**
   * The image's accessible name. Empty by default: in a table the row already names the
   * customer, and "avatar of 12•••34" read out before every row is noise.
   */
  readonly alt?: string;
  readonly status?: AvatarStatus | undefined;
  /** What the dot means, in words. A colour is not a status anyone is obliged to see. */
  readonly statusLabel?: string | undefined;
  /** The kit's 32. Bigger only on a detail header. */
  readonly size?: number;
  readonly className?: string | undefined;
}

export function Avatar({
  src,
  initials,
  alt = "",
  status,
  statusLabel,
  size = 32,
  className,
}: AvatarProps): JSX.Element {
  /** The src that 404'd, so a later prop change to a different URL gets a fresh attempt. */
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const hasImage = src !== null && src !== undefined && src !== "" && src !== failedSrc;
  const dotSize = Math.max(6, Math.round(size / 4));

  return (
    <span
      className={cn("relative inline-flex shrink-0", className)}
      style={{ width: size, height: size }}
    >
      {hasImage ? (
        <img
          src={src}
          alt={alt}
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          onError={() => setFailedSrc(src)}
          className="h-full w-full rounded-full bg-bg object-cover"
        />
      ) : (
        <span
          aria-hidden={alt === ""}
          role={alt === "" ? undefined : "img"}
          aria-label={alt === "" ? undefined : alt}
          className="flex h-full w-full items-center justify-center rounded-full bg-bg font-semibold uppercase leading-none text-ink-500"
          style={{ fontSize: Math.round(size * 0.375) }}
        >
          {initials}
        </span>
      )}

      {status === undefined ? null : (
        <>
          <span
            aria-hidden
            className={cn(
              "absolute bottom-0 right-0 rounded-full ring-2 ring-card",
              DOT_TONE[status],
            )}
            style={{ width: dotSize, height: dotSize }}
          />
          {statusLabel === undefined ? null : <span className="sr-only">{statusLabel}</span>}
        </>
      )}
    </span>
  );
}
