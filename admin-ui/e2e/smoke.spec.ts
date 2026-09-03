/**
 * §14 Slice 1d's browser gate: one operator's first session, under the production CSP.
 *
 * The flow is the acceptance bullet's own sentence — *"`make admin && make ui` → login with
 * the bootstrapped account, land on Live Ops with real counts"* — run against the real
 * admin API over a real socket, with the real `SecurityHeadersMiddleware` enforcing the real
 * §12.1 T7 policy in a real Chromium. The bootstrapped account arrives with
 * `must_change_password` set, because `accounts.insert_first_owner` sets it, so the forced
 * rotation is part of the flow rather than something the seed arranges away.
 *
 * It is ONE test with named steps rather than several, and deliberately: it is one session.
 * A second `test` would need its own login, its own cookie jar and its own violation
 * collector, and the interesting failures — a refused stylesheet, a scroll lock that does
 * nothing — are properties of the whole session rather than of a screen.
 *
 * The three assertions this file exists for, and which no jsdom test can make:
 *
 *  1. **Zero CSP violations across the whole flow.** The one that would have caught the
 *     `react-remove-scroll` nonce bug.
 *  2. **The ⌘K dialog is correctly positioned.** Centred horizontally and at its declared
 *     `top-[12vh]` — derived from the palette's own classes, not from pinned pixels.
 *  3. **The scroll lock actually applies.** `overflow: hidden` on `<body>`, the scrollbar's
 *     width compensated in `padding-right`, and the injected `<style>` carrying this
 *     response's nonce. If this fails it is a regression in the nonce path, not an
 *     assertion to relax.
 *
 * Everything the flow needs — origin, credentials, seeded ids, expected counts, and the
 * middleware's own CSP template — comes from `.manifest.json`. Nothing is spelled twice.
 */

import { expect, test, type Page } from "@playwright/test";

import { expectedCsp, nonceOf, watchCspViolations, type CspViolation } from "./csp";
import { readManifest } from "./manifest";

const manifest = readManifest();

/** `Gʻulom` as code points, so a fold or a re-encode shows up as a diff and not a guess. */
function codepointsOf(value: string): string[] {
  return Array.from(value, (character) => {
    const code = character.codePointAt(0) ?? 0;
    return `U+${code.toString(16).toUpperCase().padStart(4, "0")}`;
  });
}

/** One `<StatTile>`, found by the label in its own `<h3>`. */
function statTile(page: Page, label: string) {
  return page.locator("article").filter({ has: page.getByRole("heading", { name: label }) });
}

/** The figure a tile shows — `.type-hero` for the 44px signal, `.type-metric` for the rest. */
async function statValue(page: Page, label: string): Promise<string> {
  return (await statTile(page, label).locator(".type-hero, .type-metric").innerText()).trim();
}

interface ScrollState {
  readonly overflow: string;
  readonly paddingRight: string;
  /** `innerWidth - clientWidth` — the classic scrollbar's width, or 0 when there is none. */
  readonly scrollbarGap: number;
  readonly isLocked: boolean;
  readonly canScroll: boolean;
}

async function scrollState(page: Page): Promise<ScrollState> {
  return await page.evaluate(() => {
    const body = window.getComputedStyle(document.body);
    return {
      overflow: body.overflow,
      paddingRight: body.paddingRight,
      scrollbarGap: window.innerWidth - document.documentElement.clientWidth,
      isLocked: document.body.hasAttribute("data-scroll-locked"),
      canScroll: document.documentElement.scrollHeight > document.documentElement.clientHeight,
    };
  });
}

test("the operator's first session, under the production CSP", async ({ page }, testInfo) => {
  const watch = await watchCspViolations(page);
  const { expected, names, seeded } = manifest;

  await test.step("the shell is served with the production CSP and a per-response nonce", async () => {
    const response = await page.goto("/login");
    expect(response, "no response for /login").not.toBeNull();
    const header = response?.headers()["content-security-policy"];
    expect(header, "the shell arrived without a Content-Security-Policy").toBeDefined();

    const nonce = nonceOf(header ?? "");
    // Compared against `security_headers.CSP_TEMPLATE` itself, carried over in the
    // manifest: a widened directive in Python fails here rather than being transcribed.
    expect(header).toBe(expectedCsp(manifest.cspTemplate, nonce));
    expect(header).not.toContain("unsafe-inline");
    expect(header).not.toContain("unsafe-eval");

    // The shell hands that same nonce to the bundle through a meta element, which is what
    // `src/lib/csp.ts` reads at boot and gives to `get-nonce`.
    const published = await page
      .locator('meta[name="csp-nonce"]')
      .getAttribute("content", { timeout: 5_000 });
    expect(published, "the shell published a different nonce from the header's").toBe(nonce);

    await expect(page.getByTestId("login-form")).toBeVisible();
  });

  await test.step("sign in with the bootstrapped OWNER", async () => {
    await page.locator("#username").fill(manifest.username);
    await page.locator("#password").fill(manifest.bootstrapPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    // `insert_first_owner` sets `must_change_password`, so a first sign-in lands on the
    // rotation form rather than in the console. §14 Slice 1a: every other route is a 403
    // while the flag is set, logout included.
    await expect(page.getByTestId("password-rotation-form")).toBeVisible();
    await expect(page.getByTestId("password-rotation-form")).toHaveAttribute(
      "data-forced",
      "true",
    );
  });

  await test.step("rotate the forced password and land on Live Ops", async () => {
    await page.locator("#currentPassword").fill(manifest.bootstrapPassword);
    await page.locator("#newPassword").fill(manifest.rotatedPassword);
    await page.locator("#confirmPassword").fill(manifest.rotatedPassword);
    await page.getByRole("button", { name: "Change password" }).click();

    await expect(page.getByRole("heading", { name: "Live Ops", level: 1 })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
  });

  await test.step("Live Ops renders the seeded counts", async () => {
    // The hero: `delivered / (delivered + failed)` over a rolling 24 h — 1 of 2 — which
    // `formatRate` prints at one decimal place. Parsed rather than string-matched so the
    // assertion is about the NUMBER the console computed from the seeded rows.
    const hero = statTile(page, "24 h delivery success");
    await expect(hero.locator(".type-hero")).toHaveText(/%/);
    const rate = Number.parseFloat((await hero.locator(".type-hero").innerText()).replace("%", ""));
    expect(rate, "the 24 h delivery rate is not the seeded 1-of-2").toBeCloseTo(
      expected.successRatePercent,
      1,
    );
    await expect(hero).toContainText(
      `${String(expected.delivered24h)} delivered of ${String(expected.terminal24h)} terminal`,
    );

    expect(await statValue(page, "in flight")).toBe(String(expected.inFlight));
    expect(await statValue(page, "failed · 24 h")).toBe(String(expected.failed24h));
    expect(await statValue(page, "paid · 24 h")).toBe(String(expected.paid24h));
    await expect(statTile(page, "failed · 24 h")).toContainText(
      `of ${String(expected.orders24h)} created in the window`,
    );

    // The attention list is the same three non-terminal-or-failed orders, seen through a
    // different endpoint. A count that disagrees with the tiles means one of the two reads
    // is wrong, which is precisely what a dashboard must not do quietly.
    await expect(page.getByTestId("attention-row")).toHaveCount(expected.attentionRows);

    // The failure mix, which the pulse groups from `generation_attempts.error_code` — a
    // different table from the `orders.failed_reason` the attention row shows. Scoped to
    // its own panel, because both surfaces draw an `<ErrorCodeBadge>` and the whole point
    // is that the two reads agree. The code is rendered VERBATIM: it is the string an
    // operator greps the logs for, so a humanised label here would be a wrong answer.
    const failureMix = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "failure mix", level: 2 }) });
    await expect(failureMix.getByTestId("error-code")).toHaveCount(expected.failureRows);
    await expect(failureMix.getByTestId("error-code")).toHaveText(expected.failureCode);
    await expect(
      page.getByTestId("attention-row").filter({ hasText: expected.failureCode }),
    ).toHaveCount(1);
  });

  await test.step("⌘K opens a centred dialog whose scroll lock actually applies", async () => {
    const before = await scrollState(page);
    expect(before.overflow, "the page was already scroll-locked before ⌘K").not.toBe("hidden");

    await page.keyboard.press("ControlOrMeta+KeyK");
    const dialog = page.getByRole("dialog", { name: "Command palette" });
    await expect(dialog).toBeVisible();

    const box = await dialog.boundingBox();
    expect(box, "the open dialog has no layout box at all").not.toBeNull();
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    const width = viewport?.width ?? 0;
    const height = viewport?.height ?? 0;

    if (box !== null) {
      testInfo.annotations.push({
        type: "dialog-box",
        description: `x=${String(box.x)} y=${String(box.y)} w=${String(box.width)} h=${String(box.height)} in ${String(width)}×${String(height)}`,
      });
      // Centred, from `left-1/2 -translate-x-1/2`. Asserted as a property rather than as
      // the baseline's `x=452 w=608`, so a different root font size or scrollbar is not a
      // failure but an off-centre dialog is.
      const centre = box.x + box.width / 2;
      expect(Math.abs(centre - width / 2), "the dialog is not horizontally centred").toBeLessThanOrEqual(2);
      // `top-[12vh]`, the palette's own class.
      expect(Math.abs(box.y - height * 0.12), "the dialog is not at its declared 12vh").toBeLessThanOrEqual(2);
      // `w-[min(38rem,94vw)]` — never full-bleed, never collapsed.
      expect(box.width).toBeGreaterThan(320);
      expect(box.width).toBeLessThanOrEqual(width * 0.94 + 1);
    }

    // The scroll lock. `react-remove-scroll` injects a <style> element for this, and
    // `style-src 'self' 'nonce-…'` refuses it unless `get-nonce` was primed from the
    // shell's meta element — which is exactly the bug this gate was written after.
    const locked = await scrollState(page);
    testInfo.annotations.push({
      type: "scroll-lock",
      description:
        `before: overflow=${before.overflow} padding-right=${before.paddingRight} ` +
        `scrollbar-gap=${String(before.scrollbarGap)} scrollable=${String(before.canScroll)} · ` +
        `open: overflow=${locked.overflow} padding-right=${locked.paddingRight} ` +
        `data-scroll-locked=${String(locked.isLocked)}`,
    });
    expect(locked.overflow, "the modal scroll lock did not apply — the injected <style> was refused or never mounted").toBe("hidden");
    expect(locked.isLocked, "<body> is missing data-scroll-locked").toBe(true);
    // Compensation, not a fixed 15px — and in THIS console the honest expectation is zero.
    // `AppShell` scrolls `<main class="overflow-y-auto">`, so `<html>`/`<body>` never carry
    // a scrollbar, `innerWidth - clientWidth` is 0, and `react-remove-scroll` therefore
    // emits `padding-right: 0px !important`. The invariant that means something is that the
    // padding equals the gap the lock removed: a non-zero padding here would be the console
    // jumping sideways on every dialog, and a non-zero gap with a zero padding would be the
    // classic reflow this rule exists to prevent. Asserting a positive number instead would
    // be asserting the app has a layout it deliberately does not have.
    expect(
      Number.parseFloat(locked.paddingRight),
      `padding-right must offset the scrollbar the lock removed (gap was ${String(before.scrollbarGap)}px)`,
    ).toBeCloseTo(before.scrollbarGap, 1);

    // And the element itself: the injected sheet must carry this document's nonce. The
    // content attribute reads empty because of CSP nonce hiding, so the IDL property is
    // the only honest place to look.
    const injected = await page.evaluate(() => {
      const sheets = Array.from(document.querySelectorAll("style"));
      const lock = sheets.find((element) =>
        (element.textContent ?? "").includes("with-scroll-bars-hidden"),
      );
      return lock === undefined
        ? null
        : { nonce: lock.nonce, rules: lock.sheet?.cssRules.length ?? 0 };
    });
    expect(injected, "no scroll-lock stylesheet reached the document").not.toBeNull();
    expect(injected?.nonce, "the scroll-lock <style> carries no nonce").not.toBe("");
    expect(injected?.rules, "the scroll-lock stylesheet parsed no rules").toBeGreaterThan(0);
    testInfo.annotations.push({
      type: "scroll-lock-sheet",
      description: `nonce=${injected?.nonce ?? "-"} rules=${String(injected?.rules ?? 0)}`,
    });
  });

  await test.step("a U+02BB name survives a real render and a real keystroke path", async () => {
    const input = page.getByRole("combobox", { name: "Search" });
    await input.pressSequentially(names.gulom);
    // Typed character by character, read back out of the DOM: no fold, no NFKD, no
    // re-encode. `Gʻulom` normalised under NFKD becomes `G'ulom`, which is a different name.
    expect(await input.inputValue()).toBe(names.gulom);
    expect(codepointsOf(await input.inputValue())).toEqual(codepointsOf(names.gulom));
    expect(codepointsOf(names.gulom)).toContain("U+02BB");
    // The palette says plainly that name search is not on this build, rather than showing
    // an empty list an operator would read as "no such customer".
    await expect(
      page.getByText("Searching by recipient name is not available on this build"),
    ).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeHidden();
    const released = await scrollState(page);
    expect(released.overflow, "the scroll lock was never released").not.toBe("hidden");
  });

  await test.step("/orders deep-links, masks the names, and renders the purged row", async () => {
    // A cold load of a non-root path: the SPA fallback, a fresh nonce and the whole policy
    // again. A deep link pasted into a chat has to work, and it has to work under the CSP.
    const response = await page.goto("/orders");
    const header = response?.headers()["content-security-policy"];
    expect(header).toBe(expectedCsp(manifest.cspTemplate, nonceOf(header ?? "")));

    await expect(page.getByRole("heading", { name: "Orders", level: 1 })).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(expected.ordersTotal);

    // §12.3 at the response boundary, seen from the browser: `Gʻulom` reaches the DOM as
    // `G•••` — the U+02BB is a grapheme cluster of its own and the cut is before it, so
    // nothing is split and no replacement character appears anywhere on the page.
    const masked = page.getByTestId("name-text").filter({ hasText: names.maskedGulom });
    await expect(masked.first()).toBeVisible();
    await expect(masked.first()).toHaveAttribute("lang", "uz-Latn");
    await expect(masked.first()).toHaveAttribute("dir", "ltr");
    await expect(page.getByTestId("name-text").filter({ hasText: names.maskedOktam }).first()).toBeVisible();
    expect(await page.locator("body").innerText()).not.toContain("�");
    // The plaintext must not be on the page at all — this is the browser's copy of the
    // substring assertion `tests/test_admin/test_orders_router.py` makes on the bytes.
    expect(await page.content()).not.toContain(names.gulom);

    // §14, verbatim: `🔒 purged <date>`, never an error and never a blank.
    const purged = page.getByTestId("purged-value");
    await expect(purged).toHaveCount(1);
    await expect(purged).toContainText(`🔒 purged ${seeded.purgedDate}`);
    await expect(purged).toHaveAttribute("data-purged-at", /\d{4}-\d{2}-\d{2}/);
  });

  await test.step("nothing was refused by the Content-Security-Policy", async () => {
    const found: CspViolation[] = await watch.violations();
    expect(
      found,
      found.length === 0 ? "" : `CSP violations during the flow:\n${watch.describe(found)}`,
    ).toHaveLength(0);
    expect(
      watch.refusals(),
      `console refusals during the flow:\n${watch.refusals().join("\n")}`,
    ).toHaveLength(0);
  });
});
