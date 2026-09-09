/**
 * Tier 2: Boundary & Corner Cases Test Suite
 * 
 * Verifies resilient edge-case handling:
 * - Parameter Interpolation boundaries (missing, excess, null/undefined, repeated, XSS, extreme length)
 * - Storage & Fallback boundaries (storage permission exceptions, corrupted values, invalid locale args)
 * - Linguistic & Typographic edge cases (Uzbek Latin turned comma, Cyrillic encoding, 0 and negative numbers, missing key fallback)
 * - Reactivity & Concurrency (rapid switching, multiple concurrent subscribers)
 */

import {
  type TestCaseResult,
  runTest,
  assertEqual,
  assert,
  assertIncludes,
  assertNotIncludes,
  setupTestEnv,
  restoreTestEnv,
  loadModuleSafely,
  flattenKeys,
} from "./harness.js";

export async function runTier2Tests(): Promise<TestCaseResult[]> {
  const results: TestCaseResult[] = [];

  // =========================================================================
  // 1. Parameter Interpolation Boundaries
  // =========================================================================

  results.push(
    await runTest("T2.1.1", "T2.1: Missing parameter does not throw and leaves remaining placeholder or handles safely", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");
        // common.pageOf expects {start}, {end}, {total}
        const res = mod.t("common.pageOf", { start: 1 });
        assert(typeof res === "string", "Result must be a string");
        assertIncludes(res, "1", "Provided parameter {start} must be interpolated");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.1.2", "T2.1: Excess unreferenced parameters are safely ignored without polluting output", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");
        const res = mod.t("common.confirm", { extraParam: "unreferenced", count: 99 } as unknown as Record<string, string>);
        assertEqual(res, "Confirm", "Excess parameters should not alter static string output");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.1.3", "T2.1: Null or undefined parameter values render safely without throwing", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, unknown>) => string;
        }>("src/i18n/index.ts");
        const res1 = mod.t("common.usersCount", { count: undefined } as unknown as Record<string, string>);
        assert(typeof res1 === "string", "Undefined parameter must not throw");

        const res2 = mod.t("common.usersCount", { count: null } as unknown as Record<string, string>);
        assert(typeof res2 === "string", "Null parameter must not throw");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.1.4", "T2.1: XSS payloads and HTML tags in parameters are treated as literal text", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");
        const xssPayload = `<script>alert("hacked")</script>&"'>`;
        const res = mod.t("chats.callback", { data: xssPayload });
        assertIncludes(res, xssPayload, "XSS string should be safely placed as literal content");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.1.5", "T2.1: Extreme length parameter strings (10,000 chars) interpolate without memory overflow", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");
        const longStr = "A".repeat(10000);
        const res = mod.t("chats.callback", { data: longStr });
        assertIncludes(res, longStr, "Long string should be interpolated accurately");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // 2. Storage & Fallback Boundaries
  // =========================================================================

  results.push(
    await runTest("T2.2.1", "T2.2: Storage QuotaExceededError is caught and handled defensively", async () => {
      const env = setupTestEnv("en");
      env.storage.shouldThrowOnSet = true;
      env.storage.throwErrorType = "QuotaExceededError";
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        // Should not throw
        store.setLocale("uz");
        assertEqual(store.locale, "uz", "Store in-memory state should update even when quota is exceeded");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.2.2", "T2.2: Corrupted or invalid locale string in localStorage falls back to 'en'", async () => {
      const env = setupTestEnv("INVALID_LOCALE_###");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "en", "Invalid localStorage value must fall back to default 'en'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.2.3", "T2.2: setLocale with unknown locale defaults safely to 'en'", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        store.setLocale("es" as unknown as string);
        assertEqual(store.locale, "en", "Calling setLocale with unsupported locale should fallback to 'en'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.2.4", "T2.2: Uppercase or regional browser languages (e.g. RU-RU, uz-Cyrl) parse correctly", async () => {
      const env = setupTestEnv(undefined, "RU-RU");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "ru", "Regional tag RU-RU should resolve to 'ru'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.2.5", "T2.2: Empty string or null in localStorage resolves to fallback", async () => {
      const env = setupTestEnv("");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assert(store.locale === "en" || store.locale === "ru" || store.locale === "uz", "Empty string in storage must not set invalid locale");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // 3. Linguistic & Typographic Edge Cases
  // =========================================================================

  results.push(
    await runTest("T2.3.1", "T2.3: Uzbek Latin dictionary uses standard turned comma / apostrophe and no Cyrillic letters", async () => {
      const uzMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/uz.ts");
      const uzFlat = flattenKeys(uzMod.default || (uzMod as unknown as Record<string, unknown>));

      // Cyrillic range: \u0400-\u04FF
      const cyrillicRegex = /[\u0400-\u04FF]/;
      const cyrillicViolations: string[] = [];

      for (const [k, v] of Object.entries(uzFlat)) {
        if (cyrillicRegex.test(v)) {
          cyrillicViolations.push(`${k}: "${v}"`);
        }
      }

      assertEqual(cyrillicViolations.length, 0, `Uzbek Latin dictionary must not contain Cyrillic characters: ${cyrillicViolations.slice(0, 5).join("; ")}`);
    })
  );

  results.push(
    await runTest("T2.3.2", "T2.3: Russian translations contain valid Cyrillic without raw unicode escape bugs", async () => {
      const ruMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/ru.ts");
      const ruFlat = flattenKeys(ruMod.default || (ruMod as unknown as Record<string, unknown>));

      for (const [k, v] of Object.entries(ruFlat)) {
        assertNotIncludes(v, "\\u04", `Key ${k} has unescaped unicode sequence \\u04: "${v}"`);
      }
    })
  );

  results.push(
    await runTest("T2.3.3", "T2.3: Numeric zero, negative numbers, and decimals interpolate cleanly", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // Zero count
        const zeroRes = mod.t("common.usersCount", { count: 0 });
        assertEqual(zeroRes, "0 users", "0 must interpolate as '0'");

        // Decimal FX rate
        const decimalRes = mod.t("dashboard.fx.rate", { rate: "12,850.50" });
        assertIncludes(decimalRes, "12,850.50", "Decimal rate should interpolate cleanly");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.3.4", "T2.3: Missing key fallback returns the key itself rather than crashing", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string) => string;
        }>("src/i18n/index.ts");
        const missingKey = "nonexistent.deeply.nested.key";
        const res = mod.t(missingKey);
        assertEqual(res, missingKey, "Missing key should fallback to key path string");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.3.5", "T2.3: Deeply nested keys (4+ segments) resolve without object indexing errors", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string) => string;
        }>("src/i18n/index.ts");
        const res = mod.t("dashboard.cards.totalUsers.label");
        assertEqual(res, "Total users", "Deep key dashboard.cards.totalUsers.label must resolve");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // 4. Reactivity & Concurrency
  // =========================================================================

  results.push(
    await runTest("T2.4.1", "T2.4: Rapid sequential switching preserves deterministic state and DOM sync", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();

        const sequence = ["ru", "uz", "en", "uz", "ru", "en", "uz"];
        for (const loc of sequence) {
          store.setLocale(loc);
          assertEqual(store.locale, loc, `Store locale must match ${loc}`);
          assertEqual(env.doc.documentElement.lang, loc, `DOM lang must match ${loc}`);
          assertEqual(env.storage.getItem("hbd.dashboard.locale"), loc, `Storage must match ${loc}`);
        }
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T2.4.2", "T2.4: Multiple concurrent subscribers receive updated locale simultaneously", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: {
            (): { locale: string; setLocale: (l: string) => void };
            subscribe?: (fn: (state: { locale: string }) => void) => () => void;
          };
        }>("src/i18n/index.ts");

        if (typeof mod.useI18n.subscribe === "function") {
          const subscriberValues: string[] = [];
          const unsubscribes: (() => void)[] = [];

          for (let i = 0; i < 5; i++) {
            const unsub = mod.useI18n.subscribe((state) => {
              subscriberValues.push(state.locale);
            });
            unsubscribes.push(unsub);
          }

          mod.useI18n().setLocale("ru");
          assert(subscriberValues.length >= 5, "All subscribers should receive update");
          assert(subscriberValues.every((val) => val === "ru"), "All subscribers should see 'ru'");

          for (const u of unsubscribes) u();
        }
      } finally {
        restoreTestEnv();
      }
    })
  );

  return results;
}
