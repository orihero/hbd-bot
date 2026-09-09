/**
 * `<UserAvatar>` — the customer's Telegram profile photo, or a monogram of their masked name.
 *
 * It lives in `domain/` and not in `data/` because it knows what a MISSING photo means: the
 * absence of an avatar is a fact about a person's profile, not a rendering accident, and the
 * fallback it draws is that fact's rendering.
 *
 * ## Why this is one `<img>` and not `@radix-ui/react-avatar`
 *
 * The dependency is declared and was tempting, and it is the wrong tool here. Radix's
 * `AvatarImage` decides its loading status by constructing a DETACHED `new window.Image()` in a
 * layout effect and only then renders a second, real `<img>`; every `/api/**` response is
 * `Cache-Control: no-store` (`security_headers.py` REPLACES the header rather than appending, so
 * a handler cannot opt out), so the second element cannot be served from cache and each avatar
 * costs TWO network requests — a hundred for a fifty-row page. A detached image is also not in
 * the document, so the `loading="lazy"` that makes a list of faces affordable never applies. And
 * jsdom loads no images at all, so under Vitest the Radix image never reaches `loaded` and the
 * photo branch would be untestable. One `<img>` with `onError` costs one request, lazy-loads,
 * and can be asserted on.
 *
 * ## Why there is no probe, and what a broken image means
 *
 * PD-1 made `GET /api/users/{telegram_user_id}/avatar` an ordinary `records.read` route: no
 * step-up, no reveal budget, no audit row. There is therefore nothing for a probe to tell the
 * operator that the fallback does not — the one interesting refusal is 404 ("no photo
 * captured"), and the monogram IS its rendering. A 401 after an idle timeout also lands here,
 * and that is acceptable precisely because the avatar is never the only signal: every JSON query
 * on the screen shares the same `__Host-` cookie and will surface the same 401 as a real error
 * state, loudly, where an operator will act on it.
 *
 * ## The `src` is the server's own string, never one built here
 *
 * `UserView.avatarUrl` is `null` exactly when there is nothing to fetch, so the presence
 * decision and the URL are ONE value that cannot disagree. A client-built path beside a separate
 * `hasAvatar` boolean can — and the way it fails is an `<img>` pointed at a 404 on every row of
 * a fifty-row page. `hasAvatar` and `avatarFetchedAt` have a different job on the detail screen
 * ("photo: captured 2026-09-04"), which is what an operator needs when the picture itself will
 * not draw; this component takes neither.
 *
 * No query string is ever appended. A `?v=` is a different URL to the browser and buys a
 * re-download and nothing else — `api/stream.ts` already argues this for `<audio src>`.
 *
 * ## The monogram is built from the MASKED name
 *
 * There is no unmasked name on this wire at any role, OWNER included. `mask_name("Gʻulom")` is
 * `"G•••"`, which preserves the first grapheme — that is exactly what makes a masked value a
 * legitimate monogram source. The first code point is taken with `toCodepoints()`, which
 * iterates by code point and folds nothing; `.toUpperCase()[0]` is banned in this directory by
 * the ESLint fence and would in any case be data loss on a name whose first letter is `Gʻ`.
 *
 * When there is no name at all the ring is drawn EMPTY, with no glyph. A placeholder character
 * would have to be vendored into the four self-hosted faces or it draws as tofu in the
 * `make ui-e2e` font gate (`e2e/fonts.ts` and `e2e/font-coverage.spec.ts` enumerate every glyph
 * the console is allowed to rely on); an empty ring needs nothing, and the wrapper's `title`
 * says in words what the ring cannot.
 *
 * ## `alt` is the empty string
 *
 * Deliberately. This picture sits beside a `<TelegramUserChip>` and a `<NameText>` that already
 * say who it is, so an informative `alt` is read twice by a screen reader; and an empty `alt`
 * makes "the alt must never carry the raw Telegram integer" true BY CONSTRUCTION rather than by
 * review. Note that `document.body.textContent` does not include attribute values, so no
 * existing text assertion would have caught an `alt` leak — the colocated test asserts the
 * attribute itself.
 */

import { useState, type ReactElement } from "react";

import { cn } from "@/lib";

import { toCodepoints } from "./codepoints";

/** The monogram ring — present even when it holds no glyph, so a row does not change height. */
export const USER_AVATAR_MONOGRAM_TESTID = "user-avatar-monogram";

/** The photo. Absent from the DOM entirely when there is nothing to fetch. */
export const USER_AVATAR_IMAGE_TESTID = "user-avatar-image";

/** Hover copy when a name is known and the photo is not. */
export const NO_PHOTO_TITLE = "no photo";

/** Hover copy for the empty ring: two absences, and an operator should see both. */
export const NO_PHOTO_NO_NAME_TITLE = "no photo and no name shared";

export interface UserAvatarProps {
  /** `UserView.avatarUrl`, verbatim. `null` means there is nothing to fetch. */
  readonly avatarUrl: string | null;
  /** `UserView.firstNameMasked` — `"G•••"`. The monogram's first choice. */
  readonly firstNameMasked: string | null;
  /** `UserView.lastNameMasked`. Used only when there is no first name; Telegram allows either. */
  readonly lastNameMasked: string | null;
  /** `sm` is the 28px list cell; `lg` is the 64px detail header. */
  readonly size?: "sm" | "lg" | undefined;
  readonly className?: string | undefined;
}

/** The ring's box, by slot. Both are fixed so a column does not reflow as photos arrive. */
const RING_SIZES: Readonly<Record<"sm" | "lg", string>> = {
  sm: "h-7 w-7",
  lg: "h-16 w-16",
};

/**
 * The monogram's type size, set as an arbitrary utility rather than through `.type-caption`.
 *
 * `.type-caption` applies `text-transform: uppercase` (`src/styles/index.css`), which would
 * rewrite `Gʻ` on screen with no trace in the DOM — the precise failure the fence over this
 * directory exists to prevent. A pixel size transforms nothing.
 */
const MONOGRAM_SIZES: Readonly<Record<"sm" | "lg", string>> = {
  sm: "text-[12px]",
  lg: "text-[22px]",
};

export function UserAvatar({
  avatarUrl,
  firstNameMasked,
  lastNameMasked,
  size = "sm",
  className,
}: UserAvatarProps): ReactElement {
  /*
   * The failure is remembered as the URL THAT FAILED, not as a bare boolean.
   *
   * A boolean cannot be un-set when the row's avatar changes: once the monogram is showing, the
   * `<img>` is not in the tree at all, so a `key` on it can reset nothing — a keyed child cannot
   * reset its parent's state, and there is no child left to key. Holding the URL makes the retry
   * fall out of the comparison: a new `avatarUrl` is not the failed one, so the photo branch is
   * live again with no effect, no cleanup and no stale-closure window. The `key` below still
   * earns its place for the other half of the same change — it forces a fresh element rather
   * than a mutated `src`, so a half-decoded previous face is never painted under the new one.
   */
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const hasFailed = avatarUrl !== null && failedUrl === avatarUrl;

  // The masked name is the ONLY name that exists here. `?? ""` rather than a guard chain: an
  // empty string yields no code points, which is the same "no glyph" answer as a null name.
  const monogram = toCodepoints(firstNameMasked ?? lastNameMasked ?? "")[0]?.char ?? null;

  const ring = cn(
    "inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-control text-ink-muted",
    RING_SIZES[size],
    className,
  );

  if (avatarUrl === null || hasFailed) {
    return (
      <span
        className={ring}
        title={monogram === null ? NO_PHOTO_NO_NAME_TITLE : NO_PHOTO_TITLE}
        data-testid={USER_AVATAR_MONOGRAM_TESTID}
      >
        {/* The glyph is decoration beside a chip that already names the person, so it is not
            announced twice; the ring's `title` carries the fact for everyone else. */}
        <span aria-hidden="true" className={cn("leading-none", MONOGRAM_SIZES[size])}>
          {monogram}
        </span>
      </span>
    );
  }

  return (
    <span className={ring}>
      <img
        key={avatarUrl}
        data-testid={USER_AVATAR_IMAGE_TESTID}
        src={avatarUrl}
        alt=""
        loading="lazy"
        decoding="async"
        draggable={false}
        className="h-full w-full rounded-full object-cover"
        onError={() => {
          setFailedUrl(avatarUrl);
        }}
      />
    </span>
  );
}
