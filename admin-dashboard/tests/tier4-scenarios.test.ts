/**
 * Tier 4: Real-World Application Scenarios Test Suite
 * 
 * Verifies end-to-end operator workflows:
 * - Scenario 1: Uzbek Operator First-Time Sign-In on Login Screen
 * - Scenario 2: Russian Operator Navigating Dashboard & Analyzing Telemetry
 * - Scenario 3: Uzbek Customer Care Specialist Investigating Chats & User Profile
 * - Scenario 4: Security Auditor Performing HMAC Hash-Chain Verification in Russian
 * - Scenario 5: Multilingual Operator Moderating User & Granting Audited Credits
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

export async function runTier4Tests(): Promise<TestCaseResult[]> {
  const results: TestCaseResult[] = [];

  // =========================================================================
  // Scenario 1: Uzbek Operator First-Time Sign-In on Login Screen
  // =========================================================================
  results.push(
    await runTest("T4.1", "Scenario 1: Uzbek Operator First-Time Sign-In workflow", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // 1. Initial render is in English
        assertEqual(mod.t("auth.login.title"), "Login to your account");
        assertEqual(env.doc.documentElement.lang, "en");

        // 2. Operator clicks 'UZ' on the Language Switcher
        mod.useI18n().setLocale("uz");

        // 3. Reactively updates all login prompts, labels, and console hero copy
        assertEqual(mod.t("auth.login.title"), "Hisobingizga kiring");
        assertEqual(mod.t("auth.login.subtitle"), "Egasi tomonidan berilgan hisob qaydnomasi bilan kiring.");
        assertEqual(mod.t("auth.login.username"), "Foydalanuvchi nomi");
        assertEqual(mod.t("auth.login.password"), "Parol");
        assertEqual(mod.t("auth.login.rememberMe"), "Foydalanuvchi nomini eslab qolish");
        assertEqual(mod.t("auth.login.forgotPassword"), "Parolni unutdingizmi?");
        assertEqual(mod.t("auth.login.resetHint"), "Parolni tiklash uchun egasiga murojaat qiling.");
        assertEqual(mod.t("auth.login.signIn"), "Kirish");
        assertEqual(mod.t("auth.console.heroTitle"), "hbd tugʻilgan kun qoʻshiqlari boti operator konsoli");

        // 4. Invariants verified
        assertEqual(env.doc.documentElement.lang, "uz");
        assertEqual(env.storage.getItem("hbd.dashboard.locale"), "uz");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // Scenario 2: Russian Operator Navigating Dashboard & Analyzing Telemetry
  // =========================================================================
  results.push(
    await runTest("T4.2", "Scenario 2: Russian Operator Dashboard & Telemetry workflow", async () => {
      const env = setupTestEnv("ru");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // 1. Navigation items in Russian
        assertEqual(mod.t("nav.items.dashboard"), "Дашборд");
        assertEqual(mod.t("nav.items.chats"), "Чаты");
        assertEqual(mod.t("nav.items.users"), "Пользователи");
        assertEqual(mod.t("nav.items.generations"), "Генерации");
        assertEqual(mod.t("nav.items.audit"), "Аудит");
        assertEqual(mod.t("nav.items.admins"), "Администраторы");

        // 2. Dashboard main headers and period pickers
        assertEqual(mod.t("dashboard.title"), "Дашборд HBD");
        assertEqual(mod.t("dashboard.periods.today"), "Сегодня");
        assertEqual(mod.t("dashboard.periods.week"), "Неделя");
        assertEqual(mod.t("dashboard.periods.month"), "Месяц");
        assertEqual(mod.t("dashboard.periods.year"), "Год");

        // 3. Section group headers
        assertEqual(mod.t("dashboard.groups.audience"), "Аудитория");
        assertEqual(mod.t("dashboard.groups.finances"), "Финансы");
        assertEqual(mod.t("dashboard.groups.performance"), "Производительность");
        assertEqual(mod.t("dashboard.groups.charts"), "Графики");

        // 4. Metric cards
        assertEqual(mod.t("dashboard.cards.totalUsers.label"), "Всего пользователей");
        assertEqual(mod.t("dashboard.cards.totalRevenue.label"), "Оценочная выручка");
        assertEqual(mod.t("dashboard.cards.costPerSong.label"), "Себестоимость песни");

        // 5. Chart titles
        assertEqual(mod.t("dashboard.charts.revcost.title"), "Выручка и расходы");
        assertEqual(mod.t("dashboard.charts.costsplit.title"), "Структура расходов");
        assertEqual(mod.t("dashboard.charts.funnel.title"), "Воронка заказов");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // Scenario 3: Uzbek Customer Support Specialist Investigating Chats
  // =========================================================================
  results.push(
    await runTest("T4.3", "Scenario 3: Uzbek Customer Support Chats & Profile workflow", async () => {
      const env = setupTestEnv("uz");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // 1. Chats search toolbar
        assertEqual(mod.t("chats.title"), "Chatlar");
        assertEqual(
          mod.t("chats.searchPlaceholder"),
          "Foydalanuvchi nomi, ism, telefon yoki ID boʻyicha qidirish..."
        );

        // 2. Thread preview badges & sender tags
        assertEqual(mod.t("chats.audioMessage"), "🎵 Audio xabar");
        assertEqual(mod.t("chats.customer"), "Mijoz");
        assertEqual(mod.t("chats.hbdBot"), "HBD Bot");
        const callbackBadge = mod.t("chats.callback", { data: "select_style" });
        assertEqual(callbackBadge, "🔘 Callback: select_style");

        // 3. Customer detail navigation
        assertEqual(mod.t("chats.viewProfile"), "Foydalanuvchi profili");
        assertEqual(mod.t("users.detail.customer"), "Mijoz");
        assertEqual(mod.t("users.credits.balance"), "balans");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // Scenario 4: Security Auditor Performing HMAC Chain Verification in Russian
  // =========================================================================
  results.push(
    await runTest("T4.4", "Scenario 4: Russian Security Auditor HMAC Chain Verification workflow", async () => {
      const env = setupTestEnv("ru");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // 1. Audit screen headers
        assertEqual(mod.t("audit.title"), "Аудит");
        assertEqual(mod.t("audit.table.seq"), "Порядковый номер");
        assertEqual(mod.t("audit.table.actor"), "Инициатор");
        assertEqual(mod.t("audit.table.action"), "Действие");
        assertEqual(mod.t("audit.table.outcome"), "Результат");
        assertEqual(mod.t("audit.table.subject"), "Объект");

        // 2. Chain verification modal
        assertEqual(mod.t("audit.verify.title"), "Проверка целостности журнала аудита");
        assertIncludes(
          mod.t("audit.verify.description"),
          "хэш-цепочку HMAC"
        );

        // 3. Verification verdict reporting
        assertEqual(
          mod.t("audit.verify.successTitle"),
          "Целостность журнала аудита подтверждена"
        );
        const successDetail = mod.t("audit.verify.successMessage", { count: 1250 });
        assertIncludes(successDetail, "1250");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // Scenario 5: Multilingual Operator Moderating User & Granting Audited Credits
  // =========================================================================
  results.push(
    await runTest("T4.5", "Scenario 5: Multilingual User Moderation & Grant Credits workflow", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");

        // 1. Initial view in English
        assertEqual(mod.t("users.title"), "Users");
        assertEqual(mod.t("users.table.user"), "User");
        assertEqual(mod.t("users.standing.blocked"), "Blocked");
        assertEqual(mod.t("users.grantDialog.title"), "Grant credits");

        // 2. Operator opens grant dialog and switches to Uzbek
        mod.useI18n().setLocale("uz");
        assertEqual(mod.t("users.grantDialog.title"), "Kredit berish");
        const uzGrantConfirm = mod.t("users.grantDialog.confirm", {
          count: 5,
          unit: "kredit",
          subject: "#12345",
        });
        assertIncludes(uzGrantConfirm, "#12345");
        assertIncludes(uzGrantConfirm, "5");

        // 3. Operator switches to Russian
        mod.useI18n().setLocale("ru");
        assertEqual(mod.t("users.grantDialog.title"), "Начислить кредиты");
        const ruGrantConfirm = mod.t("users.grantDialog.confirm", {
          count: 5,
          unit: "кредитов",
          subject: "#12345",
        });
        assertIncludes(ruGrantConfirm, "#12345");
        assertIncludes(ruGrantConfirm, "5");

        // 4. Step-up password prompt
        const stepUpTitle = mod.t("reveal.stepUp.title");
        assert(stepUpTitle.length > 0);
      } finally {
        restoreTestEnv();
      }
    })
  );

  return results;
}
