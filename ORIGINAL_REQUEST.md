# Original User Request

## 2026-09-08T19:54:45Z

Implement complete multilingual localization for the admin panel (`admin-dashboard`) in 3 languages: Uzbek (`uz`), Russian (`ru`), and English (`en`), with a language switcher accessible both on the sign-in screen and across the navigation rail, strictly following the implementation plan in `admin_panel_translation_plan.md`.

Working directory: /Users/ai/Desktop/work/projects/hbd-bot
Integrity mode: development

## Reference Material
- Implementation Plan: /Users/ai/.gemini/antigravity-cli/brain/af52e80e-e1bb-4664-abe4-e60d4cb5b360/admin_panel_translation_plan.md

## Requirements

### R1. Type-Safe Reactive i18n Subsystem
Implement a strongly-typed i18n store in `admin-dashboard/src/i18n/` integrated with the existing Zustand store and `localStorage` persistence (`bayram.dashboard.locale`), with fallback to English. The subsystem must support type-checked translation keys, parameter interpolation (e.g. `{count}`), and update the root document language attribute (`<html lang="...">`).
Dictionaries must provide complete translations for:
- English (`en` - source of truth)
- Russian (`ru`)
- Uzbek (`uz` - Latin script)

### R2. PlanIQ-Styled Language Switcher Component
Create a reusable `LanguageSwitcher` component matching the PlanIQ design tokens (`tokens.css`, `Segmented.tsx`) that allows instant switching between UZ, RU, and EN.
Integrate the switcher into:
- `LoginPage`: In the top-right corner of the authentication view so operators can switch languages prior to logging in.
- `NavRail`: In the bottom section of `WideRail` (beside or above the identity/logout controls) and in `CompactBar` (the mobile/tablet top rail).

### R3. Full Screen and Shell Localization
Replace all hardcoded English strings with localized translation keys across all admin panel views:
- Authentication (`LoginPage`, `ConsolePanel`, `ChangePasswordPage`)
- Navigation Shell (`NavRail`, `navItems.ts`, `AppShell`)
- Dashboard overview (`DashboardPage`, `cardSpecs.ts`, `chartSpecs.tsx`)
- Chats history and drawer (`ChatsPage`)
- Users directory and detail drawer (`UsersScreen`, `UserDetailScreen`)
- Generations log and drawer (`GenerationsScreen`, `AttemptDeepLink`)
- Audit trail and chain verification (`AuditScreen`, `ChainVerifyPanel`)
- Admins roster and role notices (`AdminsScreen`)
- Shared error and feedback components (`NotFoundPage`, `RouteErrorPage`, `ConfirmDialog`, `EmptyState`)

## Acceptance Criteria

### Compilation and Linting
- [ ] `cd admin-dashboard && npm run typecheck` passes with zero TypeScript errors.
- [ ] `cd admin-dashboard && npm run lint` passes with zero ESLint violations.
- [ ] `cd admin-dashboard && npm run build` successfully compiles and outputs production assets into `src/bayram/admin/static/`.

### Functional Verification
- [ ] Switching languages updates the UI immediately across navigation, table columns, action buttons, and screen content without requiring a page reload.
- [ ] The chosen language persists across browser reloads via `localStorage`.
- [ ] The sign-in screen displays the language switcher and reactively updates all login prompts, labels, errors, and side-panel descriptions.
- [ ] All 3 languages (Uzbek, Russian, English) have 100% dictionary coverage with no missing keys or untranslated placeholder text.

### System Integrity
- [ ] Existing Python test suites (`make test` or `pytest -m "not integration"`) continue to pass without regressions.
