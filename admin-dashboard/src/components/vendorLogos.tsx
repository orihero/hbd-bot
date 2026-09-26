/**
 * The vendor marks the balance pills are drawn with, inline and monochrome.
 *
 * ## Why they are inline paths and not files
 *
 * `index.css` says it self-hosts its fonts so "the panel renders identically on a machine
 * with no egress", and a logo fetched from a CDN would quietly undo that: the one deployment
 * where an operator most needs to read a vendor balance — a locked-down host mid-incident —
 * is the one where the request fails and the pill loses its identity. These are three path
 * strings, they add nothing to the network, and they cannot 404.
 *
 * ## Why they are monochrome
 *
 * Each mark is `fill="currentColor"`, so it takes the ink of the pill it sits in and works on
 * both palettes with no second asset. That is a deliberate trade against brand fidelity:
 * ElevenLabs' and OpenRouter's own marks are already monochrome, and a full-colour logo on a
 * 16px pill in dark mode is a smudge with a licence attached.
 *
 * The paths are Simple Icons' (CC0-1.0, https://simpleicons.org), taken at 24×24.
 *
 * ## The unknown vendor is not an error
 *
 * `Vendor` is a closed enum on the wire and only two of its members are polled today, but the
 * poller's `_targets()` grows by configuration rather than by a release — a third vendor that
 * starts reporting a balance must render as itself immediately, not as a broken image. So an
 * unrecognised vendor gets a MONOGRAM: the first letter of its own name, in the same circle,
 * at the same size. Nothing about the pill's geometry depends on which arm was taken.
 */

import type { JSX } from "react";

import type { Vendor } from "@/api/dashboard";

/** The 24×24 path for each mark we hold, keyed by the wire's own vendor spelling. */
const VENDOR_PATH: Partial<Record<Vendor, string>> = {
  elevenlabs: "M4.6035 0v24h4.9317V0zm9.8613 0v24h4.9317V0z",
  openrouter:
    "M16.778 1.844v1.919q-.569-.026-1.138-.032-.708-.008-1.415.037c-1.93.126-4.023.728-6.149 " +
    "2.237-2.911 2.066-2.731 1.95-4.14 2.75-.396.223-1.342.574-2.185.798-.841.225-1.753.333-1.751" +
    ".333v4.229s.768.108 1.61.333c.842.224 1.789.575 2.185.799 1.41.798 1.228.683 4.14 2.75 2.126 " +
    "1.509 4.22 2.11 6.148 2.236.88.058 1.716.041 2.555.005v1.918l7.222-4.168-7.222-4.17v2.176c-.86" +
    ".038-1.611.065-2.278.021-1.364-.09-2.417-.357-3.979-1.465-2.244-1.593-2.866-2.027-3.68-2.508." +
    "889-.518 1.449-.906 3.822-2.59 1.56-1.109 2.614-1.377 3.978-1.466.667-.044 1.418-.017 2.278.02" +
    "v2.176L24 6.014Z",
};

export interface VendorLogoProps {
  readonly vendor: Vendor;
  /** Edge length in px. The mark is square and centred; the caller owns the circle around it. */
  readonly size?: number;
}

/**
 * One vendor's mark, or its initial when we hold no mark for it.
 *
 * `aria-hidden` throughout: every pill this appears in writes the vendor's name into its own
 * accessible label and its `title`, so announcing the logo as well would read the vendor
 * twice — and a logo that is the ONLY statement of which account a number belongs to would be
 * a pill nobody using a screen reader could interpret. The mark is decoration over a label
 * that already says it.
 */
export function VendorLogo({ vendor, size = 14 }: VendorLogoProps): JSX.Element {
  const path = VENDOR_PATH[vendor];

  if (path === undefined) {
    return (
      <span
        aria-hidden="true"
        className="inline-flex select-none items-center justify-center font-semibold leading-none"
        style={{ width: size, height: size, fontSize: size * 0.82 }}
      >
        {vendor.slice(0, 1).toUpperCase()}
      </span>
    );
  }

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}
