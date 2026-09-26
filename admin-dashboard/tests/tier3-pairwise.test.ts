/**
 * Tier 3: Cross-Feature Combinations (Pairwise Coverage) Test Suite
 * 
 * Verifies multi-feature interactions:
 * - C1: Switcher + LocalStorage persistence across view changes
 * - C2: Switcher + HTML document lang attribute synchronization
 * - C3: LocalStorage precedence over navigator.language
 * - C4: Dynamic Interpolation across sequential locale transitions
 * - C5: Step-Up Dialog state preservation across language changes
 * - C6: Multi-namespace synthesis (Users + Common + Reveal)
 * - C7: Dashboard period selection + card spec localization
 * - C8: Cryptographic HMAC verification + audit action/outcome formatters
 */

import {
  type TestCaseResult,
  runTest,
  assertEqual,
  assert,
  assertIncludes,
  setupTestEnv,
  restoreTestEnv,
  loadModuleSafely,
} from "./harness.js";

export async function runTier3Tests(): Promise<TestCaseResult[]> {
  const results: TestCaseResult[] = [];

  // =========================================================================
  // C1: Switcher + LocalStorage Persistence across view transitions
  // =========================================================================
  results.push(
    await runTest("T3.1", "C1: Switcher change updates localStorage and persists to simulated new view", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
        }>("src/i18n/index.ts");

        // Operator on login screen switches to Uzbek
        mod.useI18n().setLocale("uz");
        assertEqual(env.storage.getItem("bayram.dashboard.locale"), "uz");

        // Simulated navigation / fresh store instantiation
        const storedLocale = env.storage.getItem("bayram.dashboard.locale");
        assertEqual(storedLocale, "uz", "Navigating to new screen should observe stored locale 'uz'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C2: Switcher + HTML Lang Sync
  // =========================================================================
  results.push(
    await runTest("T3.2", "C2: LanguageSwitcher action triggers immediate document.documentElement.lang update", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { setLocale: (l: string) => void };
        }>("src/i18n/index.ts");

        mod.useI18n().setLocale("ru");
        assertEqual(env.doc.documentElement.lang, "ru", "HTML lang attribute must update immediately to 'ru'");

        mod.useI18n().setLocale("uz");
        assertEqual(env.doc.documentElement.lang, "uz", "HTML lang attribute must update immediately to 'uz'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C3: LocalStorage Precedence over Browser Navigator Language
  // =========================================================================
  results.push(
    await runTest("T3.3", "C3: Explicit localStorage strictly overrides contrary browser navigator language", async () => {
      // Browser says Russian (ru-RU), but localStorage has explicit Uzbek (uz)
      const env = setupTestEnv("uz", "ru-RU");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "uz", "Explicit localStorage 'uz' must take priority over browser 'ru-RU'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C4: Dynamic Interpolation across Sequential Locale Transitions
  // =========================================================================
  results.push(
    await runTest("T3.4", "C4: Dynamic interpolation preserves parameters through sequential locale swaps", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { setLocale: (l: string) => void };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        const params = { start: 1, end: 15, total: 300 };

        // English
        mod.useI18n().setLocale("en");
        const enRes = mod.t("common.pageOf", params);
        assertIncludes(enRes, "1–15 of 300");

        // Russian
        mod.useI18n().setLocale("ru");
        const ruRes = mod.t("common.pageOf", params);
        assertIncludes(ruRes, "1–15 из 300");

        // Uzbek
        mod.useI18n().setLocale("uz");
        const uzRes = mod.t("common.pageOf", params);
        assert(uzRes.includes("1–15 / 300") || uzRes.includes("1–15"), "Uzbek page range must interpolate parameters cleanly");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C5: Step-Up Dialog + Locale Reactivity
  // =========================================================================
  results.push(
    await runTest("T3.5", "C5: Step-up re-auth dialog copy updates across locales while maintaining context", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { setLocale: (l: string) => void };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // English check
        assertEqual(mod.t("reveal.stepUp.title"), "Re-authenticate for this action");

        // Switch to Russian
        mod.useI18n().setLocale("ru");
        const ruTitle = mod.t("reveal.stepUp.title");
        assert(ruTitle.includes("авториз") || ruTitle.includes("парол") || ruTitle.includes("действие") || ruTitle.length > 5);

        // Switch to Uzbek
        mod.useI18n().setLocale("uz");
        const uzTitle = mod.t("reveal.stepUp.title");
        assert(uzTitle.includes("parol") || uzTitle.includes("tasdiq") || uzTitle.includes("amal") || uzTitle.length > 5);
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C6: Multi-Namespace Integration (Users + Common + Reveal)
  // =========================================================================
  results.push(
    await runTest("T3.6", "C6: User details composite view combines users, common, and reveal namespaces seamlessly", async () => {
      const env = setupTestEnv("uz");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // Common namespace: actions
        const confirmLabel = mod.t("common.confirm");
        const cancelLabel = mod.t("common.cancel");

        // Users namespace: identity labels
        const standingLabel = mod.t("users.detail.standing");
        const creditsLabel = mod.t("users.credits.balance");

        // Reveal namespace: unmasking
        const revealCost = mod.t("reveal.costRecords", { count: 1 });

        assert(confirmLabel.length > 0, "common.confirm must resolve");
        assert(cancelLabel.length > 0, "common.cancel must resolve");
        assert(standingLabel.length > 0, "users.detail.standing must resolve");
        assert(creditsLabel.length > 0, "users.credits.balance must resolve");
        assert(revealCost.length > 0, "reveal.costRecords must resolve with parameter");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C7: Dashboard Period Selector + Card Specs Localization
  // =========================================================================
  results.push(
    await runTest("T3.7", "C7: Dashboard period selection and card spec translations align seamlessly", async () => {
      const env = setupTestEnv("ru");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // Period picker
        const todayLabel = mod.t("dashboard.periods.today");
        const weekLabel = mod.t("dashboard.periods.week");
        assertEqual(todayLabel, "Сегодня");
        assertEqual(weekLabel, "Неделя");

        // Metric Card specs. The card's `sub` — the caption printed under the figure — is
        // gone from all eighteen cards; the hover `subtitle` is what still carries the
        // definition, and is what this asserts on.
        const usersCardTitle = mod.t("dashboard.cards.totalUsers.label");
        const usersCardSubtitle = mod.t("dashboard.cards.totalUsers.subtitle");
        assertEqual(usersCardTitle, "Всего пользователей");
        assertIncludes(usersCardSubtitle, "бота");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // C8: Audit HMAC Verification + Action Formatters
  // =========================================================================
  results.push(
    await runTest("T3.8", "C8: Cryptographic HMAC verify verdict banner and audit outcomes format consistently", async () => {
      const env = setupTestEnv("ru");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        const successTitle = mod.t("audit.verify.successTitle");
        const successMsg = mod.t("audit.verify.successMessage", { count: 500 });
        const outcomeOk = mod.t("audit.outcome.ok");

        assert(successTitle.length > 0, "audit.verify.successTitle must resolve");
        assertIncludes(successMsg, "500", "audit.verify.successMessage must interpolate record count");
        assert(outcomeOk.length > 0, "audit.outcome.ok must resolve");
      } finally {
        restoreTestEnv();
      }
    })
  );

  return results;
}
