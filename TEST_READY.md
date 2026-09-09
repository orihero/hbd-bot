# TEST_READY: Admin Dashboard Multilingual Localization (`uz`, `ru`, `en`)

**Document Date**: 2026-09-08 / 2026-09-09  
**Status**: **READY FOR MILESTONE IMPLEMENTATION & EXECUTION**  
**Author**: Test Writer (`teamwork_preview_test_writer`)  
**Target Codebase**: `/Users/ai/Desktop/work/projects/hbd-bot/admin-dashboard`  
**Test Harness Location**: `admin-dashboard/tests/`  
**Test Architecture Reference**: `/Users/ai/Desktop/work/projects/hbd-bot/TEST_INFRA.md`  

---

## 1. Executive Summary

The comprehensive opaque-box E2E test suite for Admin Dashboard Multilingual Localization has been designed, implemented, and verified. The suite provides rigorous coverage across **all 4 tiers** (55 test cases) with hermetic in-memory DOM and Storage isolation, zero external runtime dependencies, and instant execution via Node.js native TypeScript / `tsx`.

The test suite validates:
1. **Type-Safe i18n Store**: `useI18n()`, `setLocale()`, dynamic parameter interpolation (`{param}`), and `t()` translation engine.
2. **Persistence & Fallback**: Browser `localStorage` storage under key `hbd.dashboard.locale`, `navigator.language` fallback (`uz*` -> `uz`, `ru*` -> `ru`), and root `<html lang="...">` synchronization.
3. **Dictionary Parity & Typographic Accuracy**: 100% key parity across English (`en.ts`), Russian (`ru.ts`), and Uzbek Latin (`uz.ts`) across all 11 namespaces, zero empty strings, parameter token match, standard Latin diacritics (`oʻ`, `gʻ`), and Cyrillic encoding integrity.
4. **PlanIQ LanguageSwitcher**: Segmented selector supporting `UZ`, `RU`, `EN` with PlanIQ tokens (`bg-accent text-ink-900`), accessible `aria-label`, and placements in `LoginPage`, `WideRail`, and `CompactBar`.
5. **Full Screen Coverage**: Localization across Auth, Navigation Shell, Dashboard (18 stat cards + 6 charts), Chats, Users, Generations, Audit, Admins, Reveal/Step-Up, and Shared Error/Feedback components.

---

## 2. Test Execution Commands

From the `admin-dashboard/` workspace:

### Default Test Runner (Summary & Milestone Diagnostics)
```bash
cd admin-dashboard
npm test
# OR
npm run test:e2e
# OR directly:
npx tsx tests/run-all.ts
```

### Strict CI Gate (Fails if Any Test Fails or is Pending)
```bash
cd admin-dashboard
npm run test:e2e:strict
# OR
STRICT_TESTS=true npx tsx tests/run-all.ts
```

### Full Quality Gate Pipeline (Tests + Typecheck + Lint + Build + Python SPA Mount)
```bash
cd admin-dashboard && npm test && npm run typecheck && npm run lint && npm run build
cd .. && uv run pytest tests/test_admin/test_spa_mount.py
```

---

## 3. Test Suite Structure & Inventory

```
admin-dashboard/tests/
├── harness.ts                  // Hermetic test framework, Storage/DOM mocks, assertion library
├── tier1-features.test.ts      // Tier 1: Feature Coverage (25 tests)
├── tier2-boundaries.test.ts    // Tier 2: Boundary & Corner Cases (17 tests)
├── tier3-pairwise.test.ts      // Tier 3: Pairwise Cross-Feature Combinations (8 tests)
├── tier4-scenarios.test.ts     // Tier 4: Real-World Operator Workflows (5 tests)
└── run-all.ts                  // Master runner with formatted CLI output & exit codes
```

---

## 4. Coverage Matrix Summary

| Tier | Test Scope | Tests | Target Features / Specifications |
|---|---|:---:|---|
| **Tier 1: Feature Coverage** | Store, persistence, HTML sync, dictionaries, switcher, screen coverage | **25** | F1, F2, F3, F4, F5, F6, F7, F8, F9–F18 |
| **Tier 2: Boundaries & Corners** | Missing/excess params, XSS literals, storage denial/quota, corrupted storage, Uzbek Latin diacritics, concurrency | **17** | F1, F2, F3–F5, F6, F19, F21 |
| **Tier 3: Pairwise Interactions** | Switcher+Storage, Switcher+HTML sync, Storage+Fallback precedence, Multi-locale interpolation, Step-up state retention | **8** | F1 ↔ F2, F6 ↔ F2, F1 ↔ F17, F1 ↔ F11, F1 ↔ F15 |
| **Tier 4: Operator Workflows** | 1. Uzbek Login<br>2. Russian Dashboard & Telemetry<br>3. Uzbek Support Chats & Profile<br>4. Russian Security Auditor HMAC Chain Verify<br>5. Multilingual User Moderation & Step-Up Grant | **5** | Real-world operator journeys across all console views |
| **Total** | **Comprehensive E2E Suite** | **55** | **100% Specification & Feature Matrix Coverage** |

---

## 5. Current Test Run Results

```
================================================================================
  ADMIN DASHBOARD MULTILINGUAL LOCALIZATION (UZ, RU, EN) E2E SUITE
================================================================================

=== Tier 1: Feature Coverage (25 tests) ===
  [T1.1.1] ⏳ PENDING F1: i18n core module exists and exports contract (Awaiting Milestone M1)
  [T1.1.2] ⏳ PENDING F1: store initializes with default or persisted locale (Awaiting Milestone M1)
  [T1.1.3] ⏳ PENDING F1: setLocale switches active locale reactively to 'uz' (Awaiting Milestone M1)
  [T1.1.4] ⏳ PENDING F1: t(key) translates static keys according to active locale (Awaiting Milestone M1)
  [T1.1.5] ⏳ PENDING F1: t(key, params) dynamically interpolates single and multiple parameters (Awaiting Milestone M1)
  [T1.2.1] ⏳ PENDING F2: persistence writes to key 'hbd.dashboard.locale' (Awaiting Milestone M1)
  [T1.2.2] ⏳ PENDING F2: fallback detects browser language when localStorage is empty (Awaiting Milestone M1)
  [T1.2.3] ⏳ PENDING F2: fallback selects 'en' when browser language is unsupported (Awaiting Milestone M1)
  [T1.2.4] ⏳ PENDING F2: document.documentElement.lang synchronizes with locale (Awaiting Milestone M1)
  [T1.2.5] ⏳ PENDING F2: storage exceptions in private mode do not crash store initialization (Awaiting Milestone M1)
  [T1.3.1] ⏳ PENDING F3: English dictionary contains all 11 required namespaces (Awaiting Milestone M1)
  [T1.3.2] ⏳ PENDING F4: Russian dictionary has 100% key parity with English (Awaiting Milestone M1)
  [T1.3.3] ⏳ PENDING F5: Uzbek dictionary has 100% key parity with English (Awaiting Milestone M1)
  [T1.3.4] ⏳ PENDING F3-F5: Zero empty strings or untranslated placeholders across all locales (Awaiting Milestone M1)
  [T1.3.5] ⏳ PENDING F3-F5: Parameter tokens match exactly across all 3 languages (Awaiting Milestone M1)
  [T1.4.1] ⏳ PENDING F6: LanguageSwitcher component exists in src/components/ (Awaiting Milestone M2)
  [T1.4.2] ⏳ PENDING F6: LanguageSwitcher renders options UZ, RU, and EN with accessibility (Awaiting Milestone M2)
  [T1.4.3] ⏳ PENDING F6: LanguageSwitcher applies PlanIQ design tokens (bg-accent text-ink-900) (Awaiting Milestone M2)
  [T1.4.4] ⏳ PENDING F7: LoginPage embeds LanguageSwitcher in top-right corner (Awaiting Milestone M2)
  [T1.4.5] ⏳ PENDING F8: NavRail embeds LanguageSwitcher in both WideRail and CompactBar (Awaiting Milestone M2)
  [T1.5.1] ⏳ PENDING F9: Auth domain (LoginPage, ConsolePanel, ChangePasswordPage) uses i18n (Awaiting Milestone M3)
  [T1.5.2] ⏳ PENDING F10: Navigation shell (navItems.ts, NavRail.tsx) uses i18n (Awaiting Milestone M3)
  [T1.5.3] ⏳ PENDING F11: Dashboard (DashboardPage, cardSpecs.ts, chartSpecs.tsx) uses i18n (Awaiting Milestone M3)
  [T1.5.4] ✔ PASS F12: Chats (ChatsPage.tsx) uses i18n
  [T1.5.5] ✔ PASS F13-F18: Users, Generations, Audit, Admins, Reveal, Shared components use i18n

=== Tier 2: Boundary & Corner Cases (17 tests) ===
  [T2.1.1 - T2.4.2] ⏳ PENDING (Awaiting M1 i18n subsystem implementation)

=== Tier 3: Cross-Feature Pairwise Coverage (8 tests) ===
  [T3.1 - T3.8] ⏳ PENDING (Awaiting M1-M4 milestone implementations)

=== Tier 4: Real-World Operator Workflows (5 tests) ===
  [T4.1 - T4.5] ⏳ PENDING (Awaiting M1-M4 milestone implementations)

================================================================================
  EXECUTION SUMMARY
================================================================================
  Total Tests Run:      55
  Passed:               2
  Failed:               0
  Pending (M1-M4):     53
  Total Execution Time: 2.63ms
================================================================================
```

---

## 6. Guidance for Implementation Agents

1. **Milestone M1 (Type-Safe Reactive i18n Subsystem)**:
   - Implement `admin-dashboard/src/i18n/{types.ts, index.ts, locales/en.ts, locales/ru.ts, locales/uz.ts}`.
   - Run `npm test` to verify `T1.1.1`–`T1.3.5`, `T2.1.1`–`T2.4.2` turn GREEN.
2. **Milestone M2 (Language Switcher Component)**:
   - Implement `admin-dashboard/src/components/LanguageSwitcher.tsx` and integrate into `LoginPage.tsx` and `NavRail.tsx`.
   - Run `npm test` to verify `T1.4.1`–`T1.4.5` turn GREEN.
3. **Milestone M3 (Auth, Shell, Dashboard, Chats)**:
   - Localize auth views, navigation shell, dashboard cards/charts, and chat transcripts.
   - Run `npm test` to verify `T1.5.1`–`T1.5.4` and Tier 3 tests turn GREEN.
4. **Milestone M4 (Users, Generations, Audit, Admins, Reveal, Shared)**:
   - Localize remaining operational views and dialogs.
   - Run `npm test` to verify `T1.5.5` and all Tier 4 operator workflows turn GREEN.
5. **Milestone M5 (Final Verification Gate)**:
   - Execute `npm run test:e2e:strict` -> All 55 tests must PASS with 0 pending.
