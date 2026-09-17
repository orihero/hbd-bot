/**
 * The three flags, drawn as discs.
 *
 * ## A flag is not a language, and this one is a deliberate exception
 *
 * The usual objection holds: languages are not countries, English is not America, and Russian
 * is read in more places than Russia. What makes it survivable here is that the flag is never
 * the ACCESSIBLE name — every button carries the language's own endonym (`Oʻzbekcha`,
 * `Русский`, `English`) as its label and its tooltip, and the drawing is `aria-hidden`. A
 * screen reader announces a language; an eye picks the disc out of a header at a glance. If
 * the console ever offers a language whose flag would be a genuine ambiguity, the honest fix
 * is to drop back to the two-letter code, not to pick a country for it.
 *
 * ## Why hand-drawn and not an icon set
 *
 * Three flags is less code than a dependency, and the CSP on this console forbids fetching
 * anything at runtime anyway. Each is drawn into a 24×24 box and clipped to a circle of r=12,
 * which is what a `2:1` flag looks like centre-cropped to a disc — the shape every rounded
 * flag control uses.
 *
 * The detail is tuned for ~20px, not for a poster. Uzbekistan's twelve stars are omitted: at
 * this size they are three grey pixels beside the crescent and read as dirt on the glass. The
 * crescent stays, because it is the mark that separates this flag from every other tricolour.
 * The American canton keeps nine dots where fifty stars belong, for the same reason and with
 * the same test: does the flag stay recognisable when the detail goes.
 */

import type { JSX } from "react";

import type { SupportedLocale } from "@/i18n/types";

export interface LanguageFlagProps {
  readonly locale: SupportedLocale;
  /** Edge length in CSS pixels. The disc fills it. */
  readonly size?: number;
  readonly className?: string;
}

/** Uzbekistan: three bands parted by two red fimbriations, crescent in the hoist. */
function UzbekFlag(): JSX.Element {
  return (
    <>
      <rect width="24" height="24" fill="#0099B5" />
      <rect y="7.2" width="24" height="1.2" fill="#CE1126" />
      <rect y="8.4" width="24" height="7.2" fill="#FFFFFF" />
      <rect y="15.6" width="24" height="1.2" fill="#CE1126" />
      <rect y="16.8" width="24" height="7.2" fill="#1EB53A" />
      {/* The crescent, as a white disc with a blue one bitten out of it. Two circles rather
          than a mask: a mask inside a clipped <svg> is one more id to keep unique per mount. */}
      <circle cx="6.1" cy="3.6" r="2.3" fill="#FFFFFF" />
      <circle cx="7.3" cy="3.2" r="2.3" fill="#0099B5" />
    </>
  );
}

/** Russia: white, blue, red, in equal bands. */
function RussianFlag(): JSX.Element {
  return (
    <>
      <rect width="24" height="8" fill="#FFFFFF" />
      <rect y="8" width="24" height="8" fill="#0039A6" />
      <rect y="16" width="24" height="8" fill="#D52B1E" />
    </>
  );
}

/**
 * The Stars and Stripes, for English.
 *
 * Thirteen stripes at 24/13 apiece, and a canton over the top seven. The fifty stars are twelve
 * dots in a 4×3 lattice: at 20px a real star field is a grey smear, and a lattice of dots is
 * what the eye completes into one anyway. Nobody counts them; they are there so the canton is
 * not a plain blue square.
 */
function AmericanFlag(): JSX.Element {
  const stripe = 24 / 13;
  const stars: JSX.Element[] = [];
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      stars.push(
        <circle
          key={`${String(row)}-${String(col)}`}
          cx={1.5 + col * 2.2}
          cy={2.2 + row * 3.4}
          r="0.62"
          fill="#FFFFFF"
        />,
      );
    }
  }

  return (
    <>
      <rect width="24" height="24" fill="#FFFFFF" />
      {[0, 2, 4, 6, 8, 10, 12].map((index) => (
        <rect
          key={index}
          y={index * stripe}
          width="24"
          height={stripe}
          fill="#B31942"
        />
      ))}
      <rect width="10.2" height={stripe * 7} fill="#0A3161" />
      {stars}
    </>
  );
}

const FLAGS: Readonly<Record<SupportedLocale, () => JSX.Element>> = {
  uz: UzbekFlag,
  ru: RussianFlag,
  en: AmericanFlag,
};

export function LanguageFlag({
  locale,
  size = 20,
  className,
}: LanguageFlagProps): JSX.Element {
  const Flag = FLAGS[locale];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      /* Decoration: the button around this carries the language's name. */
      aria-hidden
      focusable="false"
    >
      {/* The disc is a clip rather than a border-radius so the SVG's own edges are cut too —
          a rounded box around a square drawing leaves the corner colours showing at 1px. */}
      <clipPath id={`flag-${locale}`}>
        <circle cx="12" cy="12" r="12" />
      </clipPath>
      <g clipPath={`url(#flag-${locale})`}>
        <Flag />
      </g>
      {/* A hairline inside the edge, so a white band never dissolves into a light page. */}
      <circle
        cx="12"
        cy="12"
        r="11.5"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.18"
        strokeWidth="1"
      />
    </svg>
  );
}
