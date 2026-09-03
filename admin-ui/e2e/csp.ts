/**
 * The assertion this whole gate exists for: **nothing was refused.**
 *
 * A Content-Security-Policy failure is silent by design — the browser drops the offending
 * stylesheet, script or style element and carries on rendering a page that looks nearly
 * right. The scroll-lock bug this gate was written after was exactly that shape: the
 * `<style>` element `react-remove-scroll` injects for every Radix modal was refused, the
 * dialog still opened, and the only trace anywhere was one console line. jsdom has no CSP
 * at all, so the whole green Vitest suite said nothing.
 *
 * So the browser is asked twice, by two mechanisms that fail differently:
 *
 * 1. `securitypolicyviolation` events, collected from an init script that runs before any
 *    page script in every document — including one the HTML parser fires while the shell is
 *    still parsing. This is the machine-readable half: directive, blocked URI, source file
 *    and line.
 * 2. Console messages matching `Refused to …`. A backstop for the case where the event
 *    never reaches a listener (a violation inside a worker, or one raised before the
 *    document exists), and the thing a human would have seen by hand.
 *
 * Both are collected across the WHOLE flow and asserted once at the end. The events are
 * pushed out to Node through an exposed binding rather than into a `window` array on
 * purpose: a `window` array is per-DOCUMENT, so every violation raised before the last
 * navigation would be thrown away by the reload that follows it, and the gate would quietly
 * only ever check its final screen. A violation that fires on the first screen is still a
 * failure of the run.
 */

import type { ConsoleMessage, Page } from "@playwright/test";

export interface CspViolation {
  /** `style-src-elem`, `script-src`, … — the directive as the browser reported it. */
  readonly directive: string;
  readonly blockedUri: string;
  /** The document or script that tried it, and where. */
  readonly sourceFile: string;
  readonly lineNumber: number;
  /** The first characters of the refused content, when the browser offers them. */
  readonly sample: string;
  readonly documentUri: string;
}

declare global {
  interface Window {
    /** Installed by `page.exposeFunction`; hands one violation back to the test process. */
    __reportCspViolation?: (violation: CspViolation) => Promise<void>;
  }
}

/** Console text that means the browser refused something. */
const REFUSAL_PATTERN = /refused to|content security policy/i;

export interface CspWatch {
  /** Every violation event the page reported, in order, across every navigation. */
  violations(): Promise<CspViolation[]>;
  /** Console lines that read as a refusal. Cleared by nothing; the whole run's worth. */
  refusals(): readonly string[];
  /** One line per violation, for a failure message that names the file and directive. */
  describe(found: readonly CspViolation[]): string;
}

/**
 * Start collecting. Must be called before the first navigation, which is why it takes the
 * page rather than being a fixture on the response.
 */
export async function watchCspViolations(page: Page): Promise<CspWatch> {
  const refusals: string[] = [];
  const collected: CspViolation[] = [];

  page.on("console", (message: ConsoleMessage) => {
    const text = message.text();
    if (REFUSAL_PATTERN.test(text)) refusals.push(text);
  });

  await page.exposeFunction("__reportCspViolation", (violation: CspViolation) => {
    collected.push(violation);
  });

  await page.addInitScript(() => {
    // Capture on `document`: an event fired at an element bubbles through here, and one
    // fired at the document itself runs its listeners at target regardless of the phase.
    document.addEventListener(
      "securitypolicyviolation",
      (event: SecurityPolicyViolationEvent) => {
        void window.__reportCspViolation?.({
          directive: event.effectiveDirective,
          blockedUri: event.blockedURI,
          sourceFile: event.sourceFile,
          lineNumber: event.lineNumber,
          sample: event.sample,
          documentUri: event.documentURI,
        });
      },
      true,
    );
  });

  return {
    async violations(): Promise<CspViolation[]> {
      // One turn of the page's event loop, so a violation raised by the step that just
      // finished has reached the binding before the assertion reads the list.
      await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 50)));
      return collected;
    },
    refusals(): readonly string[] {
      return refusals;
    },
    describe(found: readonly CspViolation[]): string {
      return found
        .map(
          (violation) =>
            `${violation.directive} refused ${violation.blockedUri} ` +
            `(${violation.sourceFile}:${String(violation.lineNumber)}) ` +
            `while loading ${violation.documentUri}` +
            (violation.sample === "" ? "" : ` — sample: ${violation.sample}`),
        )
        .join("\n");
    },
  };
}

/** The nonce the middleware minted for this response, read off the header it wrote. */
export function nonceOf(header: string): string {
  const match = /'nonce-([A-Za-z0-9+/_=-]+)'/.exec(header);
  if (match?.[1] === undefined) {
    throw new Error(`no style nonce in the Content-Security-Policy header: ${header}`);
  }
  return match[1];
}

/**
 * The policy the middleware would have written for this nonce.
 *
 * `template` is `CSP_TEMPLATE` carried over in the manifest, so this is a comparison
 * against the Python constant rather than against a transcription of it.
 */
export function expectedCsp(template: string, nonce: string): string {
  return template.replace("{nonce}", nonce);
}
