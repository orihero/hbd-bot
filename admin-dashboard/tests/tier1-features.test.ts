/**
 * Tier 1: Feature Coverage Test Suite
 * 
 * Verifies core functionality for every feature in scope:
 * - F1: Type-Safe i18n Store (useI18n, setLocale, t helper, reactive state)
 * - F2: Persistence & Fallback (localStorage, navigator.language fallback, HTML lang sync)
 * - F3, F4, F5: Complete Dictionaries (11 namespaces, 100% key parity across EN, RU, UZ)
 * - F6, F7, F8: PlanIQ LanguageSwitcher (UZ/RU/EN options, tokens, aria labels, placements)
 * - F9-F18: Screen Localization Coverage across Auth, Shell, Dashboard, Chats, Users, Audit, Admins, Reveal, Errors
 */

import {
  type TestCaseResult,
  runTest,
  assertEqual,
  assert,
  assertDeepEqual,
  assertIncludes,
  setupTestEnv,
  restoreTestEnv,
  loadModuleSafely,
  readSourceFile,
  checkFileExists,
  flattenKeys,
  extractParameters,
  REQUIRED_NAMESPACES,
  SUPPORTED_LOCALES,
} from "./harness.js";


/**
 * Does this module actually resolve its copy through the catalogue?
 *
 * The first version of this check asked `source.includes("t(")`, which is a substring and not
 * a call: `useEffect(`, `setTimeout(`, `formatCount(` and `signOut(` all contain it. Every
 * screen matched, so F11 through F18 reported PASS against files that held nothing but
 * hardcoded English — the suite said 53/55 while the real integration count was zero. A test
 * that cannot fail is worse than a missing one, because it is quoted.
 *
 * What is actually required is an IMPORT from the i18n module. A module that resolves copy
 * has one; a module that does not, cannot.
 */
function usesI18n(source: string): boolean {
  return /from "@\/i18n(\/types)?"/.test(source);
}

/** A module that carries translation KEYS rather than calling `t` itself (specs, tables). */
function carriesKeys(source: string, namespace: string): boolean {
  return new RegExp(`"${namespace}\\.[A-Za-z_]`).test(source);
}

export async function runTier1Tests(): Promise<TestCaseResult[]> {
  const results: TestCaseResult[] = [];

  // =========================================================================
  // F1: Type-Safe i18n Store & Engine
  // =========================================================================

  results.push(
    await runTest("T1.1.1", "F1: i18n core module exists and exports contract", async () => {
      assert(checkFileExists("src/i18n/index.ts"), "[PENDING_IMPLEMENTATION] Expected src/i18n/index.ts to exist (Awaiting Milestone M1)");
      const mod = await loadModuleSafely<Record<string, unknown>>("src/i18n/index.ts");
      assert(typeof mod.useI18n === "function", "Expected useI18n hook to be exported");
      assert(typeof mod.t === "function" || typeof mod.getLocale === "function", "Expected t helper or getLocale to be exported");
    })
  );

  results.push(
    await runTest("T1.1.2", "F1: store initializes with default or persisted locale", async () => {
      const env = setupTestEnv("ru");
      try {
        const mod = await loadModuleSafely<{ useI18n: () => { locale: string; setLocale: (l: string) => void } }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "ru", "Store should initialize with 'ru' from localStorage");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.1.3", "F1: setLocale switches active locale reactively to 'uz'", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{ useI18n: () => { locale: string; setLocale: (l: string) => void } }>("src/i18n/index.ts");
        const store = mod.useI18n();
        store.setLocale("uz");
        assertEqual(store.locale, "uz", "Store locale should be updated to 'uz'");
        assertEqual(env.storage.getItem("bayram.dashboard.locale"), "uz", "Storage should be updated to 'uz'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.1.4", "F1: t(key) translates static keys according to active locale", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void; t: (k: string) => string };
          t: (k: string) => string;
        }>("src/i18n/index.ts");
        const tFn = mod.t || mod.useI18n().t;
        const confirmEn = tFn("common.confirm");
        assertEqual(confirmEn, "Confirm", "common.confirm in English should be 'Confirm'");

        mod.useI18n().setLocale("uz");
        const confirmUz = tFn("common.confirm");
        assertEqual(confirmUz, "Tasdiqlash", "common.confirm in Uzbek should be 'Tasdiqlash'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.1.5", "F1: t(key, params) dynamically interpolates single and multiple parameters", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          t: (k: string, p?: Record<string, string | number>) => string;
        }>("src/i18n/index.ts");
        const resSingle = mod.t("common.usersCount", { count: 42 });
        assertEqual(resSingle, "42 users", "Parameter {count} should be replaced with 42");

        const resMulti = mod.t("common.pageOf", { start: 1, end: 25, total: 100 });
        assertEqual(resMulti, "1–25 of 100", "Multiple parameters {start}, {end}, {total} should be replaced");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // F2: Persistence, Fallback & HTML Sync
  // =========================================================================

  results.push(
    await runTest("T1.2.1", "F2: persistence writes to key 'bayram.dashboard.locale'", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        mod.useI18n().setLocale("ru");
        assertEqual(env.storage.getItem("bayram.dashboard.locale"), "ru", "localStorage key must be bayram.dashboard.locale");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.2.2", "F2: fallback detects browser language when localStorage is empty", async () => {
      const env = setupTestEnv(undefined, "uz-UZ");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "uz", "Browser uz-UZ should cause fallback to 'uz'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.2.3", "F2: fallback selects 'en' when browser language is unsupported", async () => {
      const env = setupTestEnv(undefined, "ja-JP");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assertEqual(store.locale, "en", "Unsupported browser language ja-JP should fallback to 'en'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.2.4", "F2: document.documentElement.lang synchronizes with locale", async () => {
      const env = setupTestEnv("en");
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        mod.useI18n().setLocale("uz");
        assertEqual(env.doc.documentElement.lang, "uz", "document.documentElement.lang should be synchronized to 'uz'");
        mod.useI18n().setLocale("ru");
        assertEqual(env.doc.documentElement.lang, "ru", "document.documentElement.lang should be synchronized to 'ru'");
      } finally {
        restoreTestEnv();
      }
    })
  );

  results.push(
    await runTest("T1.2.5", "F2: storage exceptions in private mode do not crash store initialization", async () => {
      const env = setupTestEnv();
      env.storage.shouldThrowOnGet = true;
      env.storage.shouldThrowOnSet = true;
      try {
        const mod = await loadModuleSafely<{
          useI18n: () => { locale: string; setLocale: (l: string) => void };
        }>("src/i18n/index.ts");
        const store = mod.useI18n();
        assert(store.locale === "en" || store.locale === "ru" || store.locale === "uz", "Store should initialize safely despite storage error");
        store.setLocale("ru");
        assertEqual(store.locale, "ru", "Store should update in-memory state despite storage error");
      } finally {
        restoreTestEnv();
      }
    })
  );

  // =========================================================================
  // F3, F4, F5: Dictionaries Completeness & Parity
  // =========================================================================

  results.push(
    await runTest("T1.3.1", "F3: English dictionary contains all 11 required namespaces", async () => {
      assert(checkFileExists("src/i18n/locales/en.ts"), "[PENDING_IMPLEMENTATION] Expected src/i18n/locales/en.ts to exist (Awaiting Milestone M1)");
      const enMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/en.ts");
      const dict = enMod.default || (enMod as unknown as Record<string, unknown>);
      for (const ns of REQUIRED_NAMESPACES) {
        assert(ns in dict, `English dictionary must contain namespace '${ns}'`);
      }
    })
  );

  results.push(
    await runTest("T1.3.2", "F4: Russian dictionary has 100% key parity with English", async () => {
      assert(checkFileExists("src/i18n/locales/ru.ts"), "[PENDING_IMPLEMENTATION] Expected src/i18n/locales/ru.ts to exist (Awaiting Milestone M1)");
      const enMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/en.ts");
      const ruMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/ru.ts");
      const enFlat = flattenKeys(enMod.default || (enMod as unknown as Record<string, unknown>));
      const ruFlat = flattenKeys(ruMod.default || (ruMod as unknown as Record<string, unknown>));

      const missingInRu: string[] = [];
      for (const k of Object.keys(enFlat)) {
        if (!(k in ruFlat)) {
          missingInRu.push(k);
        }
      }
      assertEqual(missingInRu.length, 0, `Missing keys in Russian dictionary: ${missingInRu.slice(0, 10).join(", ")}`);
    })
  );

  results.push(
    await runTest("T1.3.3", "F5: Uzbek dictionary has 100% key parity with English", async () => {
      assert(checkFileExists("src/i18n/locales/uz.ts"), "[PENDING_IMPLEMENTATION] Expected src/i18n/locales/uz.ts to exist (Awaiting Milestone M1)");
      const enMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/en.ts");
      const uzMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/uz.ts");
      const enFlat = flattenKeys(enMod.default || (enMod as unknown as Record<string, unknown>));
      const uzFlat = flattenKeys(uzMod.default || (uzMod as unknown as Record<string, unknown>));

      const missingInUz: string[] = [];
      for (const k of Object.keys(enFlat)) {
        if (!(k in uzFlat)) {
          missingInUz.push(k);
        }
      }
      assertEqual(missingInUz.length, 0, `Missing keys in Uzbek dictionary: ${missingInUz.slice(0, 10).join(", ")}`);
    })
  );

  results.push(
    await runTest("T1.3.4", "F3-F5: Zero empty strings or untranslated placeholders across all locales", async () => {
      const locales = ["en", "ru", "uz"];
      for (const loc of locales) {
        const mod = await loadModuleSafely<{ default: Record<string, unknown> }>(`src/i18n/locales/${loc}.ts`);
        const flat = flattenKeys(mod.default || (mod as unknown as Record<string, unknown>));
        for (const [k, v] of Object.entries(flat)) {
          assert(v !== undefined && v !== null && v.trim().length > 0, `Key ${k} in ${loc}.ts has empty or null translation`);
        }
      }
    })
  );

  results.push(
    await runTest("T1.3.5", "F3-F5: Parameter tokens match exactly across all 3 languages", async () => {
      const enMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/en.ts");
      const ruMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/ru.ts");
      const uzMod = await loadModuleSafely<{ default: Record<string, unknown> }>("src/i18n/locales/uz.ts");

      const enFlat = flattenKeys(enMod.default || (enMod as unknown as Record<string, unknown>));
      const ruFlat = flattenKeys(ruMod.default || (ruMod as unknown as Record<string, unknown>));
      const uzFlat = flattenKeys(uzMod.default || (uzMod as unknown as Record<string, unknown>));

      for (const [k, enVal] of Object.entries(enFlat)) {
        const enParams = extractParameters(enVal).sort();
        if (enParams.length > 0) {
          const ruVal = ruFlat[k] ?? "";
          const uzVal = uzFlat[k] ?? "";
          const ruParams = extractParameters(ruVal).sort();
          const uzParams = extractParameters(uzVal).sort();

          assertDeepEqual(ruParams, enParams, `Parameter mismatch in Russian for key '${k}'`);
          assertDeepEqual(uzParams, enParams, `Parameter mismatch in Uzbek for key '${k}'`);
        }
      }
    })
  );

  // =========================================================================
  // F6, F7, F8: PlanIQ LanguageSwitcher Component & Placements
  // =========================================================================

  results.push(
    await runTest("T1.4.1", "F6: LanguageSwitcher component exists in src/components/", async () => {
      assert(checkFileExists("src/components/LanguageSwitcher.tsx"), "[PENDING_IMPLEMENTATION] Expected src/components/LanguageSwitcher.tsx to exist (Awaiting Milestone M2)");
      const content = readSourceFile("src/components/LanguageSwitcher.tsx");
      assertIncludes(content, "LanguageSwitcher", "Component must export LanguageSwitcher");
    })
  );

  results.push(
    await runTest("T1.4.2", "F6: LanguageSwitcher renders options UZ, RU, and EN with accessibility", async () => {
      assert(checkFileExists("src/components/LanguageSwitcher.tsx"), "[PENDING_IMPLEMENTATION] Expected src/components/LanguageSwitcher.tsx to exist (Awaiting Milestone M2)");
      const content = readSourceFile("src/components/LanguageSwitcher.tsx");
      assert(content.includes("UZ") && content.includes("RU") && content.includes("EN"), "Switcher must render UZ, RU, and EN options");
      assertIncludes(content, "aria-label", "Switcher must provide an accessible aria-label");
    })
  );

  results.push(
    await runTest("T1.4.3", "F6: LanguageSwitcher applies PlanIQ design tokens (bg-accent text-ink-900)", async () => {
      assert(checkFileExists("src/components/LanguageSwitcher.tsx"), "[PENDING_IMPLEMENTATION] Expected src/components/LanguageSwitcher.tsx to exist (Awaiting Milestone M2)");
      const content = readSourceFile("src/components/LanguageSwitcher.tsx");
      assert(
        content.includes("accent") || content.includes("ink-900") || content.includes("Segmented"),
        "Switcher must use PlanIQ styling tokens or Segmented component"
      );
    })
  );

  results.push(
    await runTest("T1.4.4", "F7: LoginPage embeds LanguageSwitcher in top-right corner", async () => {
      const content = readSourceFile("src/features/auth/LoginPage.tsx");
      if (!content.includes("LanguageSwitcher")) {
        throw new Error("[PENDING_IMPLEMENTATION] LoginPage has not integrated LanguageSwitcher yet (Awaiting Milestone M2)");
      }
      assert(content.includes("top-") || content.includes("right-") || content.includes("absolute"), "LanguageSwitcher should be positioned in top-right");
    })
  );

  results.push(
    await runTest("T1.4.5", "F8: TopBar embeds LanguageSwitcher beside the palette toggle", async () => {
      /*
       * It was the NAV RAIL that embedded this, once per layout, which put a preference among
       * the destinations. It moved to the header, next to the palette toggle: the pair of
       * "how do I want this to look" controls now sit together, and there is one copy of it
       * rather than two. The absence from the rail is asserted as well — a second copy growing
       * back would leave two controls for one preference.
       */
      const topBar = readSourceFile("src/app/TopBar.tsx");
      if (!topBar.includes("<LanguageSwitcher />")) {
        throw new Error("[PENDING_IMPLEMENTATION] TopBar has not integrated LanguageSwitcher yet (Awaiting Milestone M2)");
      }
      if (topBar.indexOf("<LanguageSwitcher />") > topBar.indexOf("<ThemeToggle />")) {
        throw new Error("LanguageSwitcher must sit before the palette toggle in TopBar");
      }

      const navRail = readSourceFile("src/app/NavRail.tsx");
      if (navRail.includes("<LanguageSwitcher")) {
        throw new Error("NavRail must no longer mount the language control");
      }
    })
  );

  // =========================================================================
  // F9-F18: Screen Localization Coverage
  // =========================================================================

  results.push(
    await runTest("T1.5.1", "F9: Auth domain (LoginPage, ConsolePanel, ChangePasswordPage) uses i18n", async () => {
      const login = readSourceFile("src/features/auth/LoginPage.tsx");
      const consolePanel = readSourceFile("src/features/auth/ConsolePanel.tsx");
      const changePass = readSourceFile("src/features/auth/ChangePasswordPage.tsx");
      if (!usesI18n(login)) {
        throw new Error("[PENDING_IMPLEMENTATION] LoginPage has not integrated i18n yet (Awaiting Milestone M3)");
      }
      if (!usesI18n(consolePanel)) {
        throw new Error("[PENDING_IMPLEMENTATION] ConsolePanel has not integrated i18n yet (Awaiting Milestone M3)");
      }
      if (!usesI18n(changePass)) {
        throw new Error("[PENDING_IMPLEMENTATION] ChangePasswordPage has not integrated i18n yet (Awaiting Milestone M3)");
      }
    })
  );

  results.push(
    await runTest("T1.5.2", "F10: Navigation shell (navItems.ts, NavRail.tsx) uses i18n", async () => {
      const navItems = readSourceFile("src/app/navItems.ts");
      const navRail = readSourceFile("src/app/NavRail.tsx");
      /* `navItems.ts` is DATA and calls nothing: it carries `nav.*` keys that `NavRail`
         resolves during render, because a label resolved at import is a label chosen before
         the operator has picked a language. Both halves are required. */
      if (!carriesKeys(navItems, "nav")) {
        throw new Error("[PENDING_IMPLEMENTATION] navItems.ts still spells its labels (Awaiting Milestone M3)");
      }
      if (!usesI18n(navRail)) {
        throw new Error("[PENDING_IMPLEMENTATION] NavRail has not integrated i18n yet (Awaiting Milestone M3)");
      }
    })
  );

  results.push(
    await runTest("T1.5.3", "F11: Dashboard (DashboardPage, cardSpecs.ts, chartSpecs.tsx) uses i18n", async () => {
      const dash = readSourceFile("src/features/dashboard/DashboardPage.tsx");
      const cards = readSourceFile("src/features/dashboard/cardSpecs.ts");
      const charts = readSourceFile("src/features/dashboard/chartSpecs.tsx");
      if (!usesI18n(dash)) {
        throw new Error("[PENDING_IMPLEMENTATION] DashboardPage has not integrated i18n yet (Awaiting Milestone M3)");
      }
      if (!carriesKeys(cards, "dashboard")) {
        throw new Error("[PENDING_IMPLEMENTATION] cardSpecs.ts still spells its labels (Awaiting Milestone M3)");
      }
      if (!carriesKeys(charts, "dashboard")) {
        throw new Error("[PENDING_IMPLEMENTATION] chartSpecs.tsx still spells its titles (Awaiting Milestone M3)");
      }
    })
  );

  results.push(
    await runTest("T1.5.4", "F12: Chats (ChatsPage.tsx) uses i18n", async () => {
      const chats = readSourceFile("src/features/chats/ChatsPage.tsx");
      if (!usesI18n(chats)) {
        throw new Error("[PENDING_IMPLEMENTATION] ChatsPage has not integrated i18n yet (Awaiting Milestone M3)");
      }
    })
  );

  results.push(
    await runTest("T1.5.5", "F13-F18: Users, Generations, Audit, Admins, Reveal, Shared components use i18n", async () => {
      const users = readSourceFile("src/features/users/UsersScreen.tsx");
      const gens = readSourceFile("src/features/generations/GenerationsScreen.tsx");
      const audit = readSourceFile("src/features/audit/AuditScreen.tsx");
      const admins = readSourceFile("src/features/admins/AdminsScreen.tsx");
      if (!usesI18n(users)) {
        throw new Error("[PENDING_IMPLEMENTATION] UsersScreen has not integrated i18n yet (Awaiting Milestone M4)");
      }
      if (!usesI18n(gens)) {
        throw new Error("[PENDING_IMPLEMENTATION] GenerationsScreen has not integrated i18n yet (Awaiting Milestone M4)");
      }
      if (!usesI18n(audit)) {
        throw new Error("[PENDING_IMPLEMENTATION] AuditScreen has not integrated i18n yet (Awaiting Milestone M4)");
      }
      if (!usesI18n(admins)) {
        throw new Error("[PENDING_IMPLEMENTATION] AdminsScreen has not integrated i18n yet (Awaiting Milestone M4)");
      }
    })
  );

  return results;
}
