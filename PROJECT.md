# Project: Admin Dashboard Multilingual Localization (`uz`, `ru`, `en`)

## Architecture
- **Framework & Libraries**: React 18, Vite 6, TypeScript 5 (strict mode), Zustand 5, TailwindCSS 3.4.
- **i18n Subsystem**: Bespoke strongly-typed Zustand store located in `admin-dashboard/src/i18n/` with zero external runtime dependencies.
  - `src/i18n/types.ts`: Strict `TranslationSchema` interface defining namespaces and keys with compile-time exhaustion checks. Supported locales: `'en' | 'ru' | 'uz'`.
  - `src/i18n/index.ts`: Zustand store providing `useI18n()` hook, `t(key, params)` helper with dynamic interpolation (e.g. `{count}`, `{name}`), reactive locale switching, `localStorage` persistence under key `bayram.dashboard.locale` (with try/catch error boundaries), and automatic synchronization of `<html lang="...">`.
  - `src/i18n/locales/en.ts`: English canonical source-of-truth dictionary (526 keys).
  - `src/i18n/locales/ru.ts`: Russian complete dictionary matching `TranslationSchema` (526 keys).
  - `src/i18n/locales/uz.ts`: Uzbek Latin (`Oʻzbekcha`) complete dictionary matching `TranslationSchema` (526 keys, 0 Cyrillic).
- **UI Components**:
  - `src/components/LanguageSwitcher.tsx`: Reusable segmented selector styled with PlanIQ design tokens (`tokens.css`, `Segmented.tsx`), supporting compact, wide, and login placements.
- **Integration Points**:
  - `LoginPage.tsx`: Top-right corner.
  - `NavRail.tsx`: Bottom of `WideRail` (collapsing vertically to 44px centered stack) and right chrome of `CompactBar`.
  - All screens across Auth, Shell, Dashboard, Chats, Users, Generations, Audit, Admins, Reveal, and Error/Feedback screens consume `useI18n()` and `t()`.
- **Backend Serving & Verification**:
  - Vite compiles SPA assets into `src/bayram/admin/static/`.
  - Starlette ASGI app mounts static assets with CSP nonce injection; verified with `pytest tests/test_admin/test_spa_mount.py` and full Python test suite.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Type-Safe i18n Store | Zustand 5 store with `useI18n()`, `setLocale()`, dynamic `{param}` interpolation, and `t()` helper | M1 | ORIGINAL_REQUEST §R1 |
| F2 | Locale Persistence & Fallback | `localStorage` persistence at `bayram.dashboard.locale`, fallback to browser lang or `en`, HTML `<html lang="...">` sync | M1 | ORIGINAL_REQUEST §R1 |
| F3 | English Canonical Dictionary | Complete English `en.ts` strictly typed against `TranslationSchema` across 11 namespaces | M1 | ORIGINAL_REQUEST §R1 |
| F4 | Russian Localization Dictionary | Complete Russian `ru.ts` with natural technical terminology | M1 | ORIGINAL_REQUEST §R1 |
| F5 | Uzbek Latin Localization Dictionary | Complete Uzbek `uz.ts` (Latin script `Oʻzbekcha`, standard orthography) | M1 | ORIGINAL_REQUEST §R1 |
| F6 | PlanIQ LanguageSwitcher Component | Reusable `LanguageSwitcher` using PlanIQ tokens (`Segmented.tsx`) for `UZ`, `RU`, `EN` | M2 | ORIGINAL_REQUEST §R2 |
| F7 | LanguageSwitcher in LoginPage | Top-right placement in `LoginPage` auth view | M2 | ORIGINAL_REQUEST §R2 |
| F8 | LanguageSwitcher in NavRail | Placement in bottom chrome of `WideRail` and top of `CompactBar` | M2 | ORIGINAL_REQUEST §R2 |
| F9 | Auth Domain Localization | Localize `LoginPage`, `ConsolePanel`, `ChangePasswordPage` | M3 | ORIGINAL_REQUEST §R3 |
| F10 | Shell Domain Localization | Localize `NavRail`, `navItems.ts`, `AppShell`, `PendingShell` | M3 | ORIGINAL_REQUEST §R3 |
| F11 | Dashboard & Analytics Localization | Localize `DashboardPage`, all 18 stat cards in `cardSpecs.ts`, 6 charts in `chartSpecs.tsx`, period selectors, dynamic FX tags | M3 | ORIGINAL_REQUEST §R3 |
| F12 | Chats Domain Localization | Localize `ChatsPage` (search, thread transcript, sender tags, media badges, empty states) | M3 | ORIGINAL_REQUEST §R3 |
| F13 | Users Domain Localization | Localize `UsersScreen`, `UserDetailScreen`, `BlockUserDialog`, `GrantCreditsDialog`, child panels (`CreditsPanel`, `OrdersPanel`, `IdentityPanel`, `WizardStatePanel`) | M4 | ORIGINAL_REQUEST §R3 |
| F14 | Generations Domain Localization | Localize `GenerationsScreen`, `AttemptDetailPanel`, `AttemptDeepLink`, `attemptFormat.ts` | M4 | ORIGINAL_REQUEST §R3 |
| F15 | Audit Domain Localization | Localize `AuditScreen`, `ChainVerifyPanel`, `auditFormat.ts` (HMAC verification verdicts, action types, outcome tags) | M4 | ORIGINAL_REQUEST §R3 |
| F16 | Admins Domain Localization | Localize `AdminsScreen`, `adminRoster.ts` (roles, staleness hints, warnings) | M4 | ORIGINAL_REQUEST §R3 |
| F17 | Reveal & Step-Up Localization | Localize `RevealDialog`, `StepUpDialog`, `MaskedValue`, `revealFields.ts`, `useReveal.ts` | M4 | ORIGINAL_REQUEST §R3 |
| F18 | Shared Feedback & Errors Localization | Localize `NotFoundPage`, `RouteErrorPage`, `ConfirmDialog`, `EmptyState`, `CursorPager`, `ErrorNote` | M4 | ORIGINAL_REQUEST §R3 |
| F19 | E2E Testing Suite (Tiers 1-4) | Comprehensive opaque-box test runner validating dictionaries, switching, persistence, parameter interpolation, and UI rendering | E2E | Project Pattern |
| F20 | Build, Static Mount & Regression Gate | Zero TypeScript errors, zero ESLint errors, successful Vite build to `static/`, passing Python tests (`pytest tests/test_admin/test_spa_mount.py` & `pytest -m "not integration"`) | M5 | ORIGINAL_REQUEST Acceptance |
| F21 | Adversarial Coverage Hardening (Tier 5) | Challenger-driven edge case validation, missing key detection, malformed interpolation protection | M5 | Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Design & implement opaque-box test suite (Tiers 1-4) covering all features; publish `TEST_READY.md` | none | **DONE** |
| M1 | Type-Safe Reactive i18n Subsystem | Implement `src/i18n/{types.ts, index.ts, locales/en.ts, locales/ru.ts, locales/uz.ts}`, Zustand store, persistence, interpolation, HTML sync | none | **DONE** |
| M2 | LanguageSwitcher Component & Shell Integration | Implement `LanguageSwitcher.tsx`, integrate into `LoginPage`, `WideRail`, `CompactBar` | M1 | **DONE** |
| M3 | Auth, Shell, Dashboard & Chats Localization | Localize `features/auth/*`, `app/{navItems.ts, NavRail.tsx, AppShell.tsx}`, `features/dashboard/*`, `features/chats/*` | M1, M2 | **IN_PROGRESS** |
| M4 | Users, Generations, Audit, Admins, Reveal & Shared Localization | Localize `features/users/*`, `features/generations/*`, `features/audit/*`, `features/admins/*`, `features/reveal/*`, `components/*`, `app/{NotFoundPage, RouteErrorPage}` | M1, M2 | PLANNED |
| M5 | Final E2E Verification & Adversarial Hardening | Pass 100% E2E test suite (Tiers 1-4), build gates, static mount tests, Python test suite, and Tier 5 adversarial hardening | E2E, M3, M4 | PLANNED |

## Interface Contracts
### i18n Subsystem API Contract (`src/i18n/index.ts` ↔ Consuming Components)
```typescript
export type SupportedLocale = 'en' | 'ru' | 'uz';

export interface I18nStore {
  locale: SupportedLocale;
  setLocale: (locale: SupportedLocale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

export const useI18n: () => I18nStore;
export const getLocale: () => SupportedLocale;
export const t: (key: string, params?: Record<string, string | number>) => string;
```
- Interpolation syntax: `{paramName}` replaced by value; missing param leaves placeholder or converts safely without throw.
- Storage key: `bayram.dashboard.locale` in `window.localStorage`.
- Default fallback: `'en'`.
- Synchronizes `document.documentElement.lang = locale` upon every change.

### LanguageSwitcher API Contract (`src/components/LanguageSwitcher.tsx` ↔ Shell / Auth)
```typescript
export interface LanguageSwitcherProps {
  variant?: 'wide' | 'compact' | 'login';
  className?: string;
  collapsed?: boolean;
}
export const LanguageSwitcher: React.FC<LanguageSwitcherProps>;
```
- Uses PlanIQ tokens (`bg-card`, `border-stroke`, `bg-accent`, `text-ink-900`, `rounded-seg`).
- Instant reactive change via `useI18n().setLocale(...)`.

## Code Layout
- `admin-dashboard/src/i18n/types.ts`: Schema interfaces.
- `admin-dashboard/src/i18n/index.ts`: Store, hook, and translation engine.
- `admin-dashboard/src/i18n/locales/en.ts`: English dictionary.
- `admin-dashboard/src/i18n/locales/ru.ts`: Russian dictionary.
- `admin-dashboard/src/i18n/locales/uz.ts`: Uzbek Latin dictionary.
- `admin-dashboard/src/components/LanguageSwitcher.tsx`: PlanIQ switcher component.
- `admin-dashboard/src/app/`: `NavRail.tsx`, `navItems.ts`, `AppShell.tsx`, `NotFoundPage.tsx`, `RouteErrorPage.tsx`.
- `admin-dashboard/src/features/auth/`: `LoginPage.tsx`, `ConsolePanel.tsx`, `ChangePasswordPage.tsx`.
- `admin-dashboard/src/features/dashboard/`: `DashboardPage.tsx`, `cardSpecs.ts`, `chartSpecs.tsx`, `adapt.ts`.
- `admin-dashboard/src/features/chats/`: `ChatsPage.tsx`.
- `admin-dashboard/src/features/users/`: `UsersScreen.tsx`, `UserDetailScreen.tsx`, dialogs, panels.
- `admin-dashboard/src/features/generations/`: `GenerationsScreen.tsx`, `AttemptDetailPanel.tsx`, `AttemptDeepLink.tsx`.
- `admin-dashboard/src/features/audit/`: `AuditScreen.tsx`, `ChainVerifyPanel.tsx`, `auditFormat.ts`.
- `admin-dashboard/src/features/admins/`: `AdminsScreen.tsx`, `adminRoster.ts`.
- `admin-dashboard/src/features/reveal/`: `RevealDialog.tsx`, `StepUpDialog.tsx`, `MaskedValue.tsx`.
- `admin-dashboard/src/components/`: Shared dialogs, tables, pagers, feedback widgets.
- `tests/test_admin/`: Python ASGI static mount and SPA serving tests.
