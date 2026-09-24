# Project: Admin Dashboard Multilingual Localization (`uz`, `ru`, `en`)

**Filed into `docs/product/` from the repository root on 2026-09-19.** Cite this document by
section — `PROJECT.md § Interface Contracts` — and never by path, so the citation survives the next
move. Nothing was renumbered in the move: the F1–F21 inventory below is still the only place in the
repository where those feature numbers are defined, and `TEST_INFRA.md` uses them throughout.

> **Where the brief went.** The `ORIGINAL_REQUEST §R1`–`§R3` citations in the Feature Inventory are
> section-form and still say what they always said, but they no longer point at anything a clone can
> open. `ORIGINAL_REQUEST.md` sits on disk at the repository root, is owned by the harness that
> produced it rather than by this project, and was untracked and added to `.gitignore` on
> 2026-09-19. Read those citations as provenance — which part of the original brief a feature came
> from — not as a pointer the reader can follow. Nothing in this document should be re-derived from
> that file; a requirement that still matters is written out here in full, and one that is not
> written out here is not a requirement any more.

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
| M3 | Auth, Shell, Dashboard & Chats Localization | Localize `features/auth/*`, `app/{navItems.ts, NavRail.tsx, AppShell.tsx}`, `features/dashboard/*`, `features/chats/*` | M1, M2 | **DONE**, dashboard leaf widgets excepted (2026-09-19) |
| M4 | Users, Generations, Audit, Admins, Reveal & Shared Localization | Localize `features/users/*`, `features/generations/*`, `features/audit/*`, `features/admins/*`, `features/reveal/*`, `components/*`, `app/{NotFoundPage, RouteErrorPage}` | M1, M2 | **DONE**, with three exceptions (2026-09-19) |
| M5 | Final E2E Verification & Adversarial Hardening | Pass 100% E2E test suite (Tiers 1-4), build gates, static mount tests, Python test suite, and Tier 5 adversarial hardening | E2E, M3, M4 | **PARTLY DONE** (2026-09-19) |

### Milestone status, re-verified 2026-09-19

Those three cells read `IN_PROGRESS`, `PLANNED` and `PLANNED` until this date, and had stopped being
true some time before it. What follows is what was actually checked against the tree, and — more
usefully — where the checking stopped short of the claim.

**M3 is done in the screens, and the dashboard's leaf widgets are what is left of it.**
`features/auth/*`, `features/chats/ChatsPage.tsx`, `app/{NavRail.tsx, navItems.ts}` and
`DashboardPage.tsx` with everything under its `sections/` import `@/i18n` and render their copy
through `t()`; eighty-eight files under `src/features`, `src/app` and `src/components` now import
the subsystem. `cardSpecs.ts` and `chartSpecs.tsx` carry `TranslationPath` keys rather than English
caption literals, so the eighteen stat cards and six charts F11 names are localized. The leaf
widgets under them are not: `ChurnCard.tsx` still labels its eyebrows `"Bot blocks"` and
`"Subscription churn"`, `TopGenerators.tsx` and `RecentSubscribers.tsx` pass English titles and
messages into `EmptyState`, and eight files under `charts/` hold English `aria-label` text — plus,
in `PlanLiability.tsx` and `PlanUtilisation.tsx`, row labels a reader actually sees. None of those
eleven imports `@/i18n`. `AppShell.tsx` does not import it either, but that one is correct: at
forty-five lines it renders no copy of its own.

**M4 is done in substance, and three of the files it names still carry English literals.**
`BlockUserDialog.tsx` builds its dialog title from `"Block this account"` / `"Unblock this
account"` in the component; `ChainVerifyPanel.tsx` labels its button `"Checking…"` / `"Check
again"`; and `auditFormat.ts` — which F15 names explicitly, for exactly these strings — holds the
outcome and reason prose as English constants. None of the three imports `@/i18n`. They are the
remainder of M4, not a separate milestone, and the feature rows above still describe the work.
`EmptyState.tsx` also does not import `@/i18n`, but that is correct rather than outstanding: it
takes its `title` and `message` as props, so it has no copy of its own to localize. Where an empty
state still reads in English — `TopGenerators.tsx` and `RecentSubscribers.tsx`, both named under M3
above — the untranslated string belongs to the caller, not to this component.

**M5 is not done, and the part that is missing is the part it was named for.** The gates pass:
`npx tsc --noEmit` and `npx eslint .` both exit clean, `npx tsx tests/run-all.ts` reports 55 passed,
0 failed, 0 pending, and `pytest tests/test_admin/test_spa_mount.py` is 12 passed. The Vite build
into `src/bayram/admin/static/` was not re-run for this note, so F20's build half is asserted only
as far as the typecheck and lint carry it. F21's Tier 5 adversarial hardening, though, does not
exist: `tests/run-all.ts` composes four tiers and imports no fifth, and nothing under
`admin-dashboard/tests/` or `admin-dashboard/src/` mentions a Tier 5 at all. The `challenger-m1-*`
and `challenger-m2-*` files sitting in that directory are the M1 and M2 challenger passes, not the
adversarial tier, and the runner does not call them. M5 stays open on that single item.

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
