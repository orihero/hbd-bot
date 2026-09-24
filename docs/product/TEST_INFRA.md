# Test Infrastructure: Admin Dashboard Multilingual Localization (`uz`, `ru`, `en`)

**Document Version**: 1.0.0  
**Target Codebase**: `admin-dashboard/`  
**Test Suite Directory**: `admin-dashboard/tests/`  
**Author**: Test Writer (`teamwork_preview_test_writer`)  
**Specification Sources**: `PROJECT.md` (`docs/product/PROJECT.md`) — the only one a clean clone can open.

> **Filed into `docs/product/` on 2026-09-19, and three of the four sources this header used to
> name did not survive the move.** It cited `admin_panel_translation_plan.md`,
> `spec_inventory.md` and `screen_string_inventory.md` alongside `PROJECT.md`. The first exists
> nowhere in this repository — it was a path on the author's own machine, never a file here. The
> other two exist only under `.agents/`, which `.gitignore:26` excludes, so nobody who clones
> this repository can read either one. They are dropped rather than repaired, because a
> specification that cites what no reader can open is not traceable; it only looks traceable.
> `ORIGINAL_REQUEST.md` is gone from the list for a different reason: it is ignored harness
> scratch — excluded at the root by `.gitignore:100` and under `.agents/` by `.gitignore:26` —
> and so it is a record of what was asked, not an authority a test result may be checked
> against. The two paths above were absolute `/Users/ai/…` paths and are now written from the
> repository root, as CLAUDE.md asks.

---

## 1. Test Philosophy & Architecture

### 1.1 Opaque-Box, Requirement-Driven Testing
The testing suite for the Admin Dashboard Multilingual Localization is built on **opaque-box principles**:
- **Zero Coupling to Internal Implementation Details**: Tests evaluate observable behavior, exported interface contracts (`PROJECT.md § Interface Contracts`), dictionary data parity, dynamic parameter interpolation fidelity, accessibility synchronization, and user-facing workflows.
- **Authoritative Specification Traceability**: Expected values and keys are derived from `PROJECT.md § Interface Contracts`, which is the one cited source a reader of this repository can resolve. *Corrected 2026-09-19: this sentence used to name `ORIGINAL_REQUEST.md`, `admin_panel_translation_plan.md`, `spec_inventory.md` and `screen_string_inventory.md` — see the note under the header for why all four are gone. What those documents contributed to the literal strings asserted in Tiers 1 through 4 is not recoverable from anything in the tree, so for those strings the honest statement is narrower than the heading above promises: they are checked against the catalogs in `admin-dashboard/src/i18n/locales/`, and their origin outside this repository can no longer be traced.*
- **Hermetic & Deterministic**: The test harness runs cleanly in Node.js without requiring external browser binaries, live backend servers, or PostgreSQL instances. It provides isolated, in-memory simulations of the DOM (`document.documentElement.lang`) and web storage (`localStorage`).
- **Progressive Testability & Failure Granularity**: Every test asserts clean, actionable error diagnostics. Tests gracefully report when milestones are not yet implemented while exercising the full contract once implementations land.

### 1.2 Subsystem Interface Contract Under Test
As specified in `PROJECT.md`, the i18n subsystem must conform to the following contract:

```typescript
export type Locale = 'en' | 'ru' | 'uz';

export interface I18nStore {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

export const useI18n: () => I18nStore;
export const getLocale: () => Locale;
export const t: (key: string, params?: Record<string, string | number>) => string;
```

Key behavioral invariants:
1. **Locale Persistence**: Stored under `localStorage` key `bayram.dashboard.locale`. Falls back to browser language (`uz*` -> `uz`, `ru*` -> `ru`) or canonical default `'en'`.
2. **HTML Root Sync**: Updates `document.documentElement.lang = locale` upon initialization and subsequent updates.
3. **Interpolation**: Replaces `{paramName}` tokens with parameter values. Unsupplied parameters or edge-case characters must not crash the application.
4. **Key Parity**: 100% parity across all 3 catalogs (`en.ts`, `ru.ts`, `uz.ts`) with zero missing or empty keys across all 11 namespaces: `common`, `nav`, `auth`, `dashboard`, `chats`, `users`, `generations`, `audit`, `admins`, `reveal`, `errors`.
5. **Language Switcher**: PlanIQ styled segmented selector supporting `UZ`, `RU`, `EN` with active token highlighting, accessible ARIA attributes, and reactive updates without full page reloads.

---

## 2. 4-Tier Test Matrix

```
+-----------------------------------------------------------------------------------+
|                           ADMIN DASHBOARD E2E TEST SUITE                         |
+-----------------------------------------------------------------------------------+
| Tier 1: Feature Coverage (>=5 tests per feature)                                  |
|   - F1: Type-Safe i18n Store                                                     |
|   - F2: Persistence, Fallback & HTML Sync                                        |
|   - F3-F5: Complete Dictionaries (EN, RU, UZ 100% Key Parity)                    |
|   - F6-F8: PlanIQ LanguageSwitcher & Component Integration                       |
|   - F9-F18: Screen Coverage (Auth, Nav, Dashboard, Chats, Users, Audit, Admins)   |
+-----------------------------------------------------------------------------------+
| Tier 2: Boundary & Corner Cases (>=5 tests per feature)                           |
|   - Missing/excess/corrupted interpolation parameters                             |
|   - Malformed/invalid locale codes, private browsing storage exceptions           |
|   - Special chars, XSS payloads in interpolation, Uzbek Latin diacritics          |
|   - Rapid switching race conditions and subscription reactivity                   |
+-----------------------------------------------------------------------------------+
| Tier 3: Cross-Feature Combinations (Pairwise Interactions)                        |
|   - Switcher + LocalStorage Persistence across view transitions                   |
|   - LocalStorage + HTML Lang Sync + Multi-Tab / Re-render Consistency            |
|   - Parameter Interpolation across Dynamic Locale Swapping                        |
|   - Modal / Drawer State Retention through Language Transitions                  |
|   - Complex Screen Workflows (Period Pickers, Filter Tables, Audit Verification)   |
+-----------------------------------------------------------------------------------+
| Tier 4: Real-World Application Scenarios (Operator Journeys)                      |
|   - S1: Uzbek Operator First-Time Sign-In on Login Screen                         |
|   - S2: Russian Operator Navigating Dashboard & Analyzing Telemetry               |
|   - S3: Uzbek Customer Support Specialist Investigating Chats & User Profile     |
|   - S4: Security Auditor Performing HMAC Hash-Chain Verification in Russian       |
|   - S5: Multilingual Operator Moderating User & Granting Credits with Step-Up    |
+-----------------------------------------------------------------------------------+
```

---

## 3. Tier 1: Feature Coverage Specification (>=5 tests per feature)

### 3.1 Feature F1: Type-Safe i18n Store & Engine
- `T1.1.1`: Store exposes `locale`, `setLocale`, and `t` matching interface contract.
- `T1.1.2`: `setLocale('ru')` switches active locale to Russian and notifies subscribers immediately.
- `T1.1.3`: `setLocale('uz')` switches active locale to Uzbek and notifies subscribers immediately.
- `T1.1.4`: `t(key)` resolves simple top-level string without parameters.
- `T1.1.5`: `t(key, { count: 5 })` replaces single curly brace parameter `{count}`.
- `T1.1.6`: `t(key, { start: 1, end: 20, total: 100 })` interpolates multiple distinct parameters.

### 3.2 Feature F2: Locale Persistence, Fallback & HTML Sync
- `T1.2.1`: Store persists selected locale to `localStorage` under `bayram.dashboard.locale`.
- `T1.2.2`: Store reads initially saved locale from `localStorage` on bootstrap.
- `T1.2.3`: Missing `localStorage` falls back to browser navigator language (`uz` -> `uz`, `ru` -> `ru`).
- `T1.2.4`: Unsupported browser navigator language (e.g. `fr`, `de`, `ja`) falls back to default `'en'`.
- `T1.2.5`: Calling `setLocale` immediately updates `document.documentElement.lang` to match the active locale.

### 3.3 Features F3, F4, F5: Dictionaries Completeness & Parity
- `T1.3.1`: English dictionary (`locales/en.ts`) contains all 11 required namespaces (`common`, `nav`, `auth`, `dashboard`, `chats`, `users`, `generations`, `audit`, `admins`, `reveal`, `errors`).
- `T1.3.2`: Russian dictionary (`locales/ru.ts`) achieves 100% key parity with English dictionary with zero missing keys.
- `T1.3.3`: Uzbek Latin dictionary (`locales/uz.ts`) achieves 100% key parity with English dictionary with zero missing keys.
- `T1.3.4`: No empty strings, undefined values, or raw untranslated placeholders exist in any dictionary entry.
- `T1.3.5`: Parameter token consistency: whenever an English key contains `{param}`, the corresponding Russian and Uzbek translations contain the identical `{param}` token.

### 3.4 Feature F6, F7, F8: PlanIQ LanguageSwitcher & Placements
- `T1.4.1`: Switcher component renders 3 segments: `UZ`, `RU`, `EN` with accessible labels.
- `T1.4.2`: Active locale segment receives active PlanIQ token classes (`bg-accent text-ink-900`).
- `T1.4.3`: Inactive locale segments receive inactive styling (`text-ink-400 hover:text-ink-900`).
- `T1.4.4`: Clicking a switcher option triggers `setLocale()` without page refresh.
- `T1.4.5`: Switcher supports layout variants (`login`, `wide`, `compact`) for placement in `LoginPage` and `NavRail`.

### 3.5 Features F9-F18: Screen Localization Coverage
- `T1.5.1` (Auth): Login titles, input labels, error notices, forgot password hint, and ConsolePanel hero text have localized keys across all 3 languages.
- `T1.5.2` (Nav Shell): Nav item titles (`dashboard`, `chats`, `users`, etc.), section groups, collapse toggles, and sign-out copy have localized keys.
- `T1.5.3` (Dashboard): Metric card titles (all 18 cards), subtitles, period filters (`Today`, `Week`, `Month`, `Year`), and chart titles have localized keys.
- `T1.5.4` (Chats): Search placeholders, transcript tags, audio/voice badges, and sender names have localized keys.
- `T1.5.5` (Users & Audit): User status badges, search hints, audit column headers, outcome labels, and HMAC verify panels have localized keys.

---

## 4. Tier 2: Boundary & Corner Cases Specification (>=5 tests per feature)

### 4.1 Parameter Interpolation Boundaries
- `T2.1.1` (Missing Parameter): `t("common.pageOf", { start: 1 })` without `{end}` or `{total}` does not crash, leaving placeholder intact or safely rendered.
- `T2.1.2` (Excess Parameter): Passing `{ unused: "value" }` to a key with no parameters does not pollute the output.
- `T2.1.3` (Null/Undefined Values): Passing `{ count: null }` or `{ name: undefined }` formats safely without throwing uncaught exceptions.
- `T2.1.4` (Repeated Placeholders): Keys with repeated tokens like `{count} ... {count}` have all occurrences replaced.
- `T2.1.5` (Special Characters & XSS Payloads): Parameter containing `<script>alert(1)</script>`, quotes, and ampersands is preserved literally without unescaped execution.
- `T2.1.6` (Large String Parameter): Handling 10,000-character parameter values without memory leaks or buffer truncation.

### 4.2 Storage & Fallback Boundaries
- `T2.2.1` (Storage Denial): `localStorage.setItem` throws `SecurityError` (e.g. Private Browsing mode); store catches error, keeps in-memory state, and continues functioning.
- `T2.2.2` (Storage Quota): `localStorage.setItem` throws `QuotaExceededError`; store safely swallows error.
- `T2.2.3` (Corrupted Value in Storage): `localStorage` contains invalid string like `"GERMAN"`, `"{}"`, or `""`; store safely falls back to `'en'`.
- `T2.2.4` (Invalid Locale Argument): Calling `setLocale("invalid" as any)` does not corrupt store state and retains or reverts to valid locale.
- `T2.2.5` (Navigator Languages Edge Cases): `navigator.languages` is empty array, `undefined`, or returns uppercase tags like `UZ-UZ` / `RU-MO`; store normalizes and detects correctly.

### 4.3 Linguistic & Typographic Edge Cases
- `T2.3.1` (Uzbek Latin Turned Comma): Uzbek strings use standard Latin turned comma `ʻ` (U+02BB or `ʻ` in `Oʻzbekcha`, `soʻm`, `gʻ`) consistently rather than conflicting backticks or Cyrillic characters.
- `T2.3.2` (Russian Cyrillic Non-Breaking Spaces): Russian metric strings and currency abbreviations preserve valid Cyrillic encoding without double-escaped unicode sequences (e.g. `\u0441\u0443\u043c`).
- `T2.3.3` (Numeric Interpolation): Number `0`, negative numbers, and floating point numbers format cleanly in interpolated strings.
- `T2.3.4` (Missing Key Fallback): Querying a nonexistent key path returns the key itself as a fallback rather than throwing a runtime TypeError.
- `T2.3.5` (Deeply Nested Keys): Keys with 4+ segments (e.g. `dashboard.cards.totalUsers.label`) resolve cleanly without object traversal faults.

### 4.4 Reactivity & Concurrency Edge Cases
- `T2.4.1` (Rapid Sequential Switching): Rapidly switching `en` -> `ru` -> `uz` -> `en` in a synchronous loop ends in consistent, deterministic state with matching DOM `lang`.
- `T2.4.2` (Multiple Observers): 20 concurrent store subscribers all receive the latest locale simultaneously without stale reads.

---

## 5. Tier 3: Cross-Feature Combinations (Pairwise Coverage)

| Interaction | Primary Feature | Secondary Feature | Verification Assertion |
|---|---|---|---|
| **C1** | `LanguageSwitcher` | `localStorage` | Switching locale on Login updates storage; loading Dashboard reads same locale from storage. |
| **C2** | `LanguageSwitcher` | `document.documentElement.lang` | Clicking switcher in NavRail immediately synchronizes HTML `lang` attribute. |
| **C3** | `localStorage` | `navigator.language` Fallback | Presence of valid key in `localStorage` strictly overrides browser navigator language. |
| **C4** | Dynamic Interpolation | Multi-locale Switching | Changing locale preserves dynamic variables while updating translated template strings. |
| **C5** | Step-Up Dialog | Locale Reactivity | Open StepUp password modal immediately updates copy when locale changes without clearing operator input. |
| **C6** | User Details Drawer | Namespace Integration | User detail view seamlessly integrates `users.*`, `common.*`, and `reveal.*` keys simultaneously. |
| **C7** | Dashboard Period Selector | Card Specs Localization | Toggling period (`Today` -> `Week`) preserves localized card titles, subtitles, and currency tags. |
| **C8** | Audit HMAC Verification | Action & Outcome Formatters | Cryptographic hash-chain verdict banner, action categories, and outcome tags render uniformly in selected language. |

---

## 6. Tier 4: Real-World Application Scenarios (Realistic Operator Workflows)

### Scenario 1: Uzbek Operator First-Time Sign-In on Login Screen
- **Workflow**:
  1. Operator visits `/login`. Initial interface is rendered.
  2. Operator notices English text and clicks `UZ` on the top-right `LanguageSwitcher`.
  3. UI reactively updates:
     - Heading: "Hisobingizga kiring"
     - Subtitle: "Egasi tomonidan berilgan hisob qaydnomasi bilan kiring."
     - Username label: "Foydalanuvchi nomi", placeholder: "Foydalanuvchi nomi"
     - Password label: "Parol"
     - Remember me: "Foydalanuvchi nomini eslab qolish"
     - Forgot password hint: "Parolni tiklash uchun egasiga murojaat qiling."
     - Submit button: "Kirish"
     - Console hero panel: "Bayram tugʻilgan kun qoʻshiqlari boti operator konsoli"
  4. Operator types username and password; form values remain intact during locale toggle.
  5. HTML document `lang` attribute is verified to be `"uz"`.
  6. `localStorage` key `bayram.dashboard.locale` is verified to be `"uz"`.

### Scenario 2: Russian Operator Navigating Dashboard & Analyzing Telemetry
- **Workflow**:
  1. Operator is signed into console with locale set to Russian (`ru`).
  2. Left navigation rail displays Russian labels: "Дашборд", "Чаты", "Пользователи", "Генерации", "Аудит", "Администраторы".
  3. Dashboard screen displays Russian titles:
     - Header: "Дашборд Bayram"
     - Period buttons: "Сегодня", "Неделя", "Месяц", "Год"
     - Section group headers: "Аудитория", "Финансы", "Производительность", "Графики"
  4. Metric cards render Russian titles and subtitles:
     - "Всего пользователей" / "когда-либо запускали бота"
     - "Оценочная выручка" / "доставлено × публичная цена"
     - "Себестоимость песни" / "все провайдеры, за песню"
  5. Chart specs render Russian titles: "Выручка и расходы", "Структура расходов", "Воронка заказов".
  6. Switching period updates metric ranges while preserving Russian typography.

### Scenario 3: Uzbek Customer Support Specialist Investigating Chats & User Profile
- **Workflow**:
  1. Support specialist switches to Uzbek (`uz`).
  2. Opens `/chats`.
  3. Verifies toolbar title "Chatlar" and search placeholder "Foydalanuvchi nomi, ism, telefon yoki ID boʻyicha qidirish...".
  4. Transcript displays localized badges: "🎵 Audio xabar", "🔘 Callback: ...", "Mijoz", "Bayram".
  5. Specialist clicks "Foydalanuvchi profili" to deep link to customer detail drawer.
  6. Customer profile displays localized tabs and fields: "Profil", "Holati", "Faol", "Ilk murojaat", "Kreditlar", "Balans".

### Scenario 4: Security Auditor Performing HMAC Hash-Chain Verification in Russian
- **Workflow**:
  1. Security auditor opens console in Russian (`ru`).
  2. Navigates to `/audit`.
  3. Verifies table column headers: "Записано (UTC+5)", "Порядковый номер", "Инициатор", "Действие", "Результат", "Объект".
  4. Clicks "Проверить целостность журнала" (ChainVerifyPanel).
  5. Verifies modal description: "Проверяет криптографическую цепочку HMAC...".
  6. Simulates successful verification verdict: renders "Целостность журнала аудита подтверждена" with parameter interpolation "Цепочка подписей HMAC непрерывна на протяжении {count} проверенных записей.".

### Scenario 5: Multilingual Operator Moderating User & Granting Credits with Step-Up
- **Workflow**:
  1. Operator opens Users screen in English (`en`), seeing "Users", "Customer", "Credits", "Standing".
  2. Selects user and clicks "Grant credits".
  3. Modal opens: "Grant Free Credits".
  4. While modal is open, operator clicks `UZ` switcher.
  5. Dialog title updates reactively to "Kredit berish", confirm button updates to "{subject}ga {count} ta kredit berish" without dropping operator's entered credit amount.
  6. Operator switches to `RU`: dialog updates to "Начислить кредиты".
  7. Step-up password prompt displays localized explanation and reassurance: "Никаких изменений еще не произошло...".

---

## 7. Test Harness & Execution Engine

### 7.1 Harness Directory Structure
```
admin-dashboard/tests/
├── harness.ts                             // Hermetic test framework, in-memory DOM/Storage mocks, assert utilities
├── tier1-features.test.ts                 // Tier 1: Feature Coverage (F1 to F18, >=5 tests per feature)
├── tier2-boundaries.test.ts               // Tier 2: Boundary & Corner Cases (>=5 tests per feature)
├── tier3-pairwise.test.ts                 // Tier 3: Pairwise Cross-Feature Interactions
├── tier4-scenarios.test.ts                // Tier 4: Real-World Operator Workflows (Scenarios 1-5)
├── run-all.ts                             // Master runner executing all four tiers with exit codes & summary table
├── built-shell-csp.ts                     // The BUILT shell read against the CSP it will be served under
├── challenger-m1-empirical.ts             // M1 adversarial: Uzbek Latin purity, Turkic numerals, interpolation & store stress
├── challenger-m1-iter2-stress.ts          // M1 iteration 2: remediated caption keys, 1,000,000-op throughput, pollution fuzzing
├── challenger-m1-key-parity.ts            // M1 adversarial: 526-key parity and dynamic-token consistency across en/ru/uz
├── challenger-m2-empirical.ts             // M2 adversarial: rapid switching, prop forwarding, variant fallbacks, ARIA
├── challenger-m2-switcher-stress.ts       // M2 adversarial: 1,500+ switches, subscriber-leak integrity, storage-denial resilience
└── challenger-m2-2-keyboard-responsive.ts // M2-2 adversarial: keyboard navigation, WAI-ARIA, PlanIQ tokens, 320-1440px viewports
```

**Corrected 2026-09-19.** This tree listed six files; the directory holds thirteen, and the seven
it left out are not a rival suite. `built-shell-csp.ts` has a script of its own —
`npm run check:built-shell` — and can only run after `npm run build`, because the document that
actually ships is `src/bayram/admin/static/index.html`, a Vite artefact that `.gitignore`
excludes and that the Python CSP test structurally cannot reach; it covers the source shell
instead. The six `challenger-*.ts` harnesses are the adversarial runs from milestones M1 and M2:
each is executed directly with `tsx`, each ends on its own verdict and its own exit code, and not
one of them is imported by `run-all.ts` or named in `package.json` or in `.github/workflows/`.
Whether that separation is intent or drift is recorded nowhere — no script, comment or workflow
mentions them at all — so only the consequence is safe to state: the pass counts §7.3 describes
are the four tiers only. CI does reach `built-shell-csp.ts` — `.github/workflows/ci.yml` runs
`check:built-shell` after the build, and `make ui-check` runs the same gate locally — but it
reaches none of the six challengers, which are run by hand or not at all.

### 7.2 Execution Command
The test suite can be run at any time from `admin-dashboard/`:
```bash
npm test
# OR
npm run test:e2e
# OR directly via tsx:
npx tsx tests/run-all.ts
```

### 7.3 Integration with CI / Build Gates
- The test suite is wired directly into `package.json` scripts.
- Any failed test returns exit code `1` with verbatim assertion errors and stack traces.
- All passing tests output a clean summary matrix detailing coverage across all 4 tiers.
