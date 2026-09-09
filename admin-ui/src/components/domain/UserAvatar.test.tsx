/**
 * `<UserAvatar>`, held against the two things it is allowed to cost.
 *
 * **A request.** Every `/api/**` response is `Cache-Control: no-store`, so a fifty-row page of
 * faces is fifty requests and there is no cache to soften a second one. The assertions here are
 * therefore about the DOM the browser will act on: a `null` URL renders no `<img>` at all, and
 * the `<img>` that does render carries `loading="lazy"` and `decoding="async"`. Those three
 * attributes are the whole of the page's cost model — a component that quietly dropped one would
 * still look right in every screenshot.
 *
 * **A leak.** The monogram is drawn from a MASKED name, and `mask_name("Gʻulom")` is `"G•••"`,
 * so the first code point is a legitimate initial and nothing else about the name survives. The
 * fold assertions below are on the code point rather than on string equality, because `G` and a
 * case-folded or normalised `G` look identical in a test failure and identical on a 14px screen.
 * The last test is about an attribute, not about text: `document.body.textContent` walks text
 * nodes and does NOT include attribute values, so an `alt` carrying the raw Telegram integer
 * would sail past every text assertion in this file and in the screens' files too.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { pathUserAvatar } from "@/api";

import {
  NO_PHOTO_NO_NAME_TITLE,
  NO_PHOTO_TITLE,
  USER_AVATAR_IMAGE_TESTID,
  USER_AVATAR_MONOGRAM_TESTID,
  UserAvatar,
} from "./UserAvatar";

/** The integer that must never reach the screen. It is in the URL, and a URL is an attribute. */
const TELEGRAM_USER_ID = 770000123;
const AVATAR_URL = pathUserAvatar(TELEGRAM_USER_ID);

describe("when there is nothing to fetch", () => {
  it("renders the monogram and NO <img> at all, so a null URL costs no request", () => {
    render(<UserAvatar avatarUrl={null} firstNameMasked="G•••" lastNameMasked={null} />);

    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID).textContent).toBe("G");
    // Not "an <img> that fails quietly": an element with a null-ish src is still an element the
    // browser may resolve against the document base URL, which is a request for the SPA's own
    // index.html on every row of the table.
    expect(screen.queryByTestId(USER_AVATAR_IMAGE_TESTID)).toBeNull();
  });

  it("says so on hover, because an empty ring is not self-explanatory", () => {
    render(<UserAvatar avatarUrl={null} firstNameMasked="G•••" lastNameMasked={null} />);
    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID)).toHaveAttribute(
      "title",
      NO_PHOTO_TITLE,
    );
  });
});

describe("when there is a photo", () => {
  it("points one <img> at the server's own string, verbatim", () => {
    render(<UserAvatar avatarUrl={AVATAR_URL} firstNameMasked="G•••" lastNameMasked={null} />);

    const image = screen.getByTestId(USER_AVATAR_IMAGE_TESTID);
    // Verbatim, with no `?v=` cache-buster: a fresh query string is a fresh URL to the browser
    // and buys a re-download, and the presence decision and the URL must not be able to disagree.
    expect(image).toHaveAttribute("src", AVATAR_URL);
    expect(screen.queryByTestId(USER_AVATAR_MONOGRAM_TESTID)).toBeNull();
  });

  it("carries the three attributes that bound a fifty-row page", () => {
    render(<UserAvatar avatarUrl={AVATAR_URL} firstNameMasked="G•••" lastNameMasked={null} />);

    const image = screen.getByTestId(USER_AVATAR_IMAGE_TESTID);
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(image).toHaveAttribute("alt", "");
  });

  it("falls back to the monogram when the fetch fails, leaving no broken image behind", () => {
    render(<UserAvatar avatarUrl={AVATAR_URL} firstNameMasked="G•••" lastNameMasked={null} />);

    fireEvent.error(screen.getByTestId(USER_AVATAR_IMAGE_TESTID));

    // Every refusal lands here — 404 (no photo), 401 (idle timeout), 415 — and they all paint
    // the same ring, which is honest: the avatar is never the only signal of a failed session.
    expect(screen.queryByTestId(USER_AVATAR_IMAGE_TESTID)).toBeNull();
    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID).textContent).toBe("G");
  });
});

describe("the monogram", () => {
  it("is the first CODE POINT of the masked name, folded by nothing", () => {
    const { unmount } = render(
      <UserAvatar avatarUrl={null} firstNameMasked="Gʻ•••" lastNameMasked={null} />,
    );
    // `mask_name` preserves the first grapheme, which is why a masked value is a legitimate
    // monogram source at all. `G` here is U+0047 and not a folded or normalised look-alike.
    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID).textContent?.codePointAt(0)).toBe(0x47);
    unmount();

    render(<UserAvatar avatarUrl={null} firstNameMasked="Д•••" lastNameMasked={null} />);
    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID).textContent?.codePointAt(0)).toBe(0x414);
  });

  it("falls through to the last name, which Telegram lets a customer have on its own", () => {
    render(<UserAvatar avatarUrl={null} firstNameMasked={null} lastNameMasked="D•••" />);
    expect(screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID).textContent).toBe("D");
  });

  it("is an EMPTY ring when no name was shared — a glyph the font gate never approved is tofu", () => {
    render(<UserAvatar avatarUrl={null} firstNameMasked={null} lastNameMasked={null} />);

    const ring = screen.getByTestId(USER_AVATAR_MONOGRAM_TESTID);
    // The element is still there, so a row of nameless accounts does not collapse to a
    // different height than a row of named ones.
    expect(ring).toBeInTheDocument();
    expect(ring.textContent).toBe("");
    expect(ring).toHaveAttribute("title", NO_PHOTO_NO_NAME_TITLE);
  });
});

describe("the raw Telegram integer", () => {
  it("never reaches the text or the alt, and the alt is asserted SEPARATELY", () => {
    const { container } = render(
      <UserAvatar avatarUrl={AVATAR_URL} firstNameMasked="G•••" lastNameMasked={null} />,
    );

    expect(document.body.textContent ?? "").not.toContain(String(TELEGRAM_USER_ID));
    // `textContent` walks text nodes only. An `alt` carrying the id would be invisible to the
    // assertion above, which is why `alt=""` is checked as the attribute it is.
    expect(container.querySelector("img")?.getAttribute("alt")).toBe("");
  });
});
