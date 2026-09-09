# Admin Panel Comprehensive Audit & Redesign Plan

**Project**: `hbd-bot` (Telegram Birthday Song & Celebration Kit Bot)  
**Scope**: Full Admin Panel Audit (Backend APIs, Database Models, Schemas, Frontend React UI/UX, Design Patterns, Business Decision Metrics)  
**Date**: September 2026  
**Status**: Ready for Implementation  

---

## 1. Executive Summary: Why the Admin Panel is in Chaos

An exhaustive audit of both the backend (`src/hbd/admin/`, `src/hbd/db/`) and the frontend (`admin-ui/src/`) confirms the exact problems raised: **the data is scattered, timestamps are inconsistent and unreadable, key business telemetry is missing, and the user interface lacks coherent design patterns.**

```
CURRENT STATE (Chaos & Fragmentation)                 TARGET STATE (Modern High-Velocity Admin Console)
┌──────────────────────────────────────────────┐       ┌─────────────────────────────────────────────────────────────┐
│ • Raw ISO strings ("2026-09-03T12:00:00Z")   │       │ • Human relative time ("3m ago") + UTC/Local dual tooltips   │
│ • "Peek panel" pushing entire table down     │       │ • 2-column Shopify-style Order Details & Slide-out Drawers  │
│ • Credits & ledger completely hidden from UI │  ───► │ • Complete User 360: Balances, Ledger History, Grant Action │
│ • Hardcoded "not instrumented" costs/latency │       │ • Real Suno/AI provider cost & latency monitoring            │
│ • No revenue, conversion funnel, or GMV      │       │ • Executive KPI Tiles with trends (+/- % vs previous period)│
│ • Audio assets isolated from generation info │       │ • Unified Media Cards with waveform playback & lyric diffs  │
└──────────────────────────────────────────────┘       └─────────────────────────────────────────────────────────────┘
```

### Key Root Causes Identified
1. **Premature Isolation of Domain Features**: Advanced features like credit balances (`credit_accounts`), append-only credit ledgers (`credit_ledger`), and lyric write rate-limits (`lyric_budgets`) exist in the database with strict constraints, but **no admin endpoints or frontend views expose them**. Operators cannot answer simple questions like *"Does this customer have credits?"* or *"Was this order comped or debited?"*.
2. **Unreadable Timestamps & Naive Renderings**: Several screens display raw ISO strings without formatting (e.g., `LiveScreen` prints `24 h window <raw_from> → <raw_to>`). Tables display cramped UTC strings without visual hierarchy between date, time, and relative duration.
3. **Disruptive Interaction Models**: The orders list employs an in-table "peek panel" that shifts all table rows down and pauses live polling when clicked. The generations screen squashes a 10-column data table when a side drawer opens.
4. **Complete Business & Financial Blind Spot**: The dashboard has no revenue figures, no credit consumption metrics, and hardcodes `isCostTelemetry: false`. AI generation costs (Suno/ElevenLabs) and provider response latencies are not tracked or surfaced to operators.

---

## 2. Backend Architecture & Data Gaps Audit

### 2.1 Database Models vs. Admin Exposure

Our audit of `src/hbd/db/models/` reveals **14 mapped models**, but only a fraction of their actionable data reaches the admin panel:

| Database Model | Table | Exists in DB? | Exposed in Admin API? | Identified Gaps & Impact on Operations |
|---|---|:---:|:---:|---|
| **`CreditAccountRow`** | `credit_accounts` | **YES** | **NO (0%)** | Holds `balance`, `lifetime_granted`, and `allowance_period_index`. **Critical blind spot**: Operators cannot see user credit balances or whether an account was comped. |
| **`CreditLedgerRow`** | `credit_ledger` | **YES** | **NO (0%)** | Append-only ledger of all `GRANT`, `DEBIT`, `REFUND`, `CONSUME` movements with idempotency keys and actor attribution. **Missing**: Operators cannot see payment/credit transaction history for an order or user. |
| **`LyricBudgetRow`** | `lyric_budgets` | **YES** | **NO (0%)** | Daily anti-abuse counter (`writes`, `day_index`). **Missing**: Operators cannot see if a user is hitting anti-spam lyric write limits. |
| **`NameRecordRow`** | `name_records` | **YES** | **NO (0%)** | Phonetic pronunciation dictionary with IPA, syllables, confidence, and learning counters. **Missing**: No admin lookup or correction tool. |
| **`GenerationAttemptRow`**| `generation_attempts` | **YES** | **Partial (60%)** | `cost_usd` and `latency_ms` columns exist, but provider code does not populate them; dashboard hardcodes them to `null` ("not instrumented"). Raw upstream error payloads are discarded. |
| **`OrderRow`** | `orders` | **YES** | **Partial (75%)** | Only has boolean `is_paid`. No monetary value, currency, pricing tier, payment gateway reference, or customer refund status. |
| **`BriefRow`** | `briefs` | **YES** | **Partial (70%)** | Cleared on 30-day and 90-day clocks. Unmasking requires `POST /reveal` step-up, but UI has no preview diff between customer draft lyrics and generated lyrics. |
| **`AssetRow`** | `assets` | **YES** | **Partial (80%)** | Audio assets are served via range requests, but asset cards lack direct linkage back to the prompt/parameters that generated them. |

### 2.2 Backend API Query & Filter Rigidity
- **Strict Interval Validation Bug**: All date filters use `_window(since, until)` in `src/hbd/admin/routers/orders.py:102` which enforces:
  ```python
  if start is None or end is None:
      raise _invalid("from and to are one window — give both bounds or neither")
  ```
  Passing `?from=2026-09-01T00:00:00Z` without `to=` returns HTTP 422 `INVALID_INPUT`. Users and UI pickers frequently want "since date X until now", which fails unless the client manually constructs a second timestamp.
- **Zero Dynamic Sorting**: Despite being planned in architecture docs, **no admin endpoint implements `?sort=`**. Every list is locked to hardcoded SQL `ORDER BY created_at DESC, id DESC`. Operators cannot sort by latency, cost, delivery time, or retry count.
- **No Search Query (`q`) on Users or Orders**: `GET /api/users` only filters by exact `telegramUserId`. There is no partial text search for Telegram usernames, recipient names, or correlation IDs.

---

## 3. Frontend UI/UX Audit (Screen-by-Screen Breakdown)

### 3.1 Global Shell & Layout (`AppShell`, `TopBar`, `NavRail`)
- **TopBar Issues**:
  - The UTC/Local toggle is a small button that toggles global mode, but timestamp cells throughout the app don't display their relative time clearly.
  - Search trigger (⌘K) is a small icon button; it lacks an intuitive global search input with instant results dropdown.
- **NavRail Issues**:
  - Displays dead-end items marked "phase 3" (`Chat`, `Payments`, `Moderation`). They occupy vertical rail space while useful features like **Credits & Financials** and **Provider Health** are nowhere in the navigation.

### 3.2 Live Ops Dashboard (`/`)
- **Raw Timestamp String Display**: Line 156 of [LiveScreen.tsx](file:///Users/ai/Desktop/work/projects/hbd-bot/admin-ui/src/features/live/LiveScreen.tsx#L155-L159) literally prints raw ISO strings directly into the DOM:
  ```tsx
  caption={<>{"24 h window "}<span className="num">{liveWindow.from}</span>{" → "}<span className="num">{liveWindow.to}</span></>}
  ```
  Result: Operators see `24 h window 2026-09-03T07:46:12Z → 2026-09-04T07:46:12Z` instead of `Last 24 hours (Sep 3, 12:46 → Sep 4, 12:46)`.
- **Single Metric Dominance**: The screen dedicates massive hero real estate to a single number (24h delivery success rate), while completely lacking:
  - Active in-flight pipeline count breakdown (Generating, Lyrics Ready, Authorized).
  - Credit consumption velocity (credits spent today vs yesterday).
  - Suno AI provider uptime / error rate badge.
- **Activity Feed**: The `LiveFeed` renders events, but items lack interactive quick-actions (e.g. clicking an event cannot open a drawer to inspect the order).

### 3.3 Orders Hub (`/orders`) & Order Detail (`/orders/:orderId`)
- **In-Table "Peek Panel" Chaos**: In [OrdersScreen.tsx](file:///Users/ai/Desktop/work/projects/hbd-bot/admin-ui/src/features/orders/OrdersScreen.tsx#L110-L130), clicking an order row opens an expanded card directly above the table. This pushes row 1 down by 300px, jarring the operator's eye position and pausing the auto-refresh poll.
- **Misleading State Distribution Bar**: The stacked distribution bar at the top only calculates percentages for the **current 50-row keyset page**, not the overall filtered dataset. This gives operators a false impression of system state.
- **Disjointed Order Detail View**:
  - Order details are split across 3 disjointed tabs: "Pipeline", "Attempts", and "Assets".
  - To hear the delivered song, an operator has to click away from the pipeline into the Assets tab.
  - If generation failed, the error message is truncated to 48 characters with no raw provider response or retry button.
  - Customer information is minimal: no credit balance, no total spend, no link to chat history.

### 3.4 Users List (`/users`) & User 360 Detail (`/users/:telegramUserId`)
- **Misleading "Last Seen" Column**: [users.py](file:///Users/ai/Desktop/work/projects/hbd-bot/src/hbd/db/admin/users.py#L3-L15) explains that `users.last_seen_at` only updates when an order is created. An operator sees "Last Seen: March 12" and thinks the user left, when in fact they may be actively chatting or browsing today.
- **Missing Financials & Credits**: The table shows `orderCount` and `paidOrderCount`, but **zero information on credit balances**. Operators cannot see if a user has 0 credits or 50 unused credits.
- **No Operational Actions**: Operators cannot:
  - Grant goodwill/compensation credits to a user.
  - Block or unblock a spamming user.
  - Reset daily lyric write limits.

### 3.5 AI Generations & Name Strategies (`/generations`, `/generations/names`)
- **Viewport Squeeze Anti-Pattern**: Clicking an attempt opens `AttemptDetailPanel` as a right-side column, squeezing a 10-column data table into 50% width and causing horizontal overflow chaos.
- **Audio Verification Disconnect**: Acoustic verification verdicts (`✓ passed`, `✗ failed`, confidence score `0.78`) are listed without an inline audio player. Operators cannot listen to the audio segment to judge *why* the acoustic model failed!
- **Hidden STT Transcript**: The speech-to-text transcript is hidden behind privacy step-up even when looking at anonymous acoustic benchmarks.

---

## 4. Benchmark UI/UX Patterns Identified via Mobbin

Using the Mobbin MCP, we researched best-in-class operational consoles, B2B SaaS dashboards, and AI media generators. We extracted four dominant design patterns to apply to `hbd-bot`:

### 4.1 Pattern 1: E-Commerce & Order Management (Shopify & Deel)
*Mobbin References*: [Shopify Order Detail](https://mobbin.com/screens/7b82066b-54c4-48c7-891e-10c513136d9b) · [Deel Transaction View](https://mobbin.com/screens/64373e1d-d81e-4016-9f63-0593fea580ca)

```
┌────────────────────────────────────────────────────────────────────────┬─────────────────────────────┐
│ ORDER HEADER: #ord-9481b2  [ ✓ DELIVERED ]  [ Paid: Yes ]               │ CUSTOMER 360 CARD           │
│ Created: Sep 4, 2026, 12:30 PM (15m ago) · Correlation: req-9f201       │ Telegram ID: 849201948      │
├────────────────────────────────────────────────────────────────────────┤ Balance: 2 Credits [Comp]   │
│ FULFILLMENT & GENERATION STEPPER                                       │ Lifetime Orders: 4 (3 Paid) │
│ (1) Brief Ready ──► (2) Lyric Approved ──► (3) Suno Render ──► (4) Sent │ Language: Uzbek (Latin)     │
│ [ 1.4s ]             [ 2.1s ]               [ 14.8s ]          [ 0.8s ]│ [ Message ] [ Grant Credit ]│
├────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ DELIVERABLES & MEDIA PREVIEW                                           │ RETENTION & PRIVACY CLOCKS  │
│ 🎵 Birthday Song (Variant 0) [ 2:14 ] [ ▶ Play ] [ ⬇ Download MP3 ]    │ • Identity: 86 days left    │
│ 📄 Approved Lyric Sheet [ Uzbek Latin ] [ View Full Lyrics ]           │ • Audio: 361 days left      │
└────────────────────────────────────────────────────────────────────────┴─────────────────────────────┘
```
- **2-Column Layout**: Left side (70% width) for Order Stepper, Deliverables, and Generation Attempts; Right side (30% width) for Customer 360 Card and Retention Clocks.
- **Integrated Media Player**: Audio deliverables embedded directly in the order summary rather than tucked away in a sub-tab.

### 4.2 Pattern 2: Bot User & Audience CRM (ManyChat)
*Mobbin Reference*: [ManyChat Contacts & Audience Management](https://mobbin.com/screens/b0a4a109-1555-40d7-9c45-1007b4107d67)
- **Tag & Status Filter Bar**: Quick filter chips at the top: `[ All Users ]`, `[ Has Balance > 0 ]`, `[ In Wizard ]`, `[ Blocked ]`.
- **Slide-out Customer Drawer**: Clicking a user opens a non-disruptive overlay drawer from the right. The background table remains visible and retains its filter and pagination state.
- **Credit Movement Ledger**: A sub-table inside the user drawer displaying append-only ledger entries (`+1 Allowance Period 4`, `-1 Order #ord-9481`, `+1 Admin Comp: Operator Sarah`).

### 4.3 Pattern 3: AI Media Generation Console (Suno & ElevenLabs)
*Mobbin References*: [Suno Web App](https://mobbin.com/screens/71e4433c-4d11-4c05-84e2-718cc0c85522) · [ElevenLabs History & Telemetry](https://mobbin.com/screens/b5dd4bb7-f5a0-4c00-b01d-1cc71eaa3366)
- **Inline Waveform & Audio Player**: Direct audio playback within generation attempt tables.
- **Prompt & Lyric Comparison**: Side-by-side view of customer-approved lyrics vs. acoustic STT transcription with highlighted discrepancies.
- **Acoustic Match Gauge**: Clear visual progress badge for name verification confidence (e.g. `98% match` in green, `64% match` in red).
- **One-Click Remediation**: A prominent `[ Re-render with Suno ]` button when an attempt encounters a transient upstream failure.

### 4.4 Pattern 4: Operational Metrics & Health Pulse (Mixpanel & Whop)
*Mobbin References*: [Whop Analytics](https://mobbin.com/screens/b090486e-df14-4907-9b42-2a0294d13d19) · [Mixpanel Dashboard](https://mobbin.com/screens/29090883-8625-4a44-b13c-694a33b18c27)
- **Standardized KPI Card Geometry**:
  ```
  ┌──────────────────────────────┐
  │ Active Pipeline In-Flight    │
  │ 14 orders                    │
  │ ▲ +18% vs last 24h           │
  └──────────────────────────────┘
  ```
- **Unified Time Range Picker**: Global presets (`Today`, `Last 24 Hours`, `Last 7 Days`, `Last 30 Days`, `Custom Range`) that synchronize all metrics and table views without triggering 422 errors.

---

## 5. Required New Fields & Data Schema Enhancements

To empower operators to make **real business and operational decisions**, we will add the following fields and endpoints:

### 5.1 Backend Schema & View Additions

#### 1. Expose Entitlements & Credit Ledger (`UserDetailView` & `UserView`)
Add credit fields to `src/hbd/admin/schemas/users.py`:
- `creditBalance: int` (from `credit_accounts.balance`)
- `lifetimeCreditsGranted: int` (from `credit_accounts.lifetime_granted`)
- `allowancePeriod: int | None` (from `credit_accounts.allowance_period_index`)
- `recentLedgerEntries: list[CreditLedgerEntryView]` (from `credit_ledger`)

#### 2. Order Payments & Financial View (`OrderDetailView` & `OrderView`)
Add payment tracking fields to `src/hbd/admin/schemas/orders.py`:
- `creditCost: int` (credits charged for this order, derived from `credit_ledger` where `order_id = orders.id`)
- `paymentRail: str` (e.g., `"telegram_stars"`, `"credit_allowance"`, `"admin_grant"`)
- `ledgerStatus: str` (`"settled"`, `"refunded"`, `"pending"`)
- `retryCount: int` (total attempts executed for this order)

#### 3. Instrument AI Vendor Cost & Latency (`GenerationAttemptView`)
Update provider adapters and `src/hbd/admin/schemas/dashboard.py`:
- Populate `cost_usd: float` (e.g. `$0.012` per Suno generation attempt)
- Populate `latency_ms: int` (actual provider roundtrip time in ms)
- Add provider endpoint `GET /api/metrics/providers`: returns average latency, failure rate, and total cost grouped by provider (`suno`, `elevenlabs`, `openai`).

#### 4. Flexible Query Parameters
- Update `_window()` validator to allow open-ended `from` filters (defaulting `to = utc_now()`).
- Add `q: str | None` parameter to `GET /api/users` and `GET /api/orders` for fuzzy substring search over Telegram IDs, correlation IDs, and recipient names.

---

## 6. Implementation Action Plan

### Phase 1: Timestamp & Information Display Standardization
1. **Human-Readable Timestamp Component Overhaul**:
   - Refactor `<Timestamp>` in `admin-ui/src/components/data/Timestamp.tsx` to default to **Human-Readable Primary + Tooltip Secondary**:
     - Visible text: `"3m ago"` or `"Today, 14:32"` (for events > 2h old).
     - Hover tooltip: Full absolute UTC timestamp (`2026-09-04 12:45:10 UTC`) alongside local system time (`2026-09-04 17:45:10 +05:00`).
   - Fix all raw date strings (such as `LiveScreen.tsx:156`) to use formatted dates.
2. **Standardized Duration & Latency Badges**:
   - Format milliseconds into clean human seconds: `< 1s` (green), `1s - 5s` (neutral), `5s - 15s` (amber), `> 15s` (red).
3. **Consistent Empty States & Fallbacks**:
   - Replace inconsistent blanks and raw `null`s with a unified `<EmptyValue />` component with tooltip explanation (e.g., *"Not recorded in this deployment"* vs *"Purged after 30 days"*).

### Phase 2: Screen Redesigns & UI/UX Pattern Compliance
1. **Live Ops Dashboard**:
   - Replace the lonely hero card with a **4-Tile Executive KPI Grid**:
     1. Delivery Success Rate (24h) with trend delta.
     2. In-Flight Active Pipeline count (live pulsing indicator).
     3. Total Song Generations Today & Total Credits Consumed.
     4. AI Provider Health (Suno API Latency p95 & error rate).
   - Add a direct interactive filter to the Live Activity Feed.
2. **Orders Hub & Shopify-Style Detail View**:
   - **Kill the in-table accordion Peek Panel**: Replace it with either a clean slide-out right drawer or instant navigation to Order Detail.
   - **Fix State Distribution Bar**: Query the database for true filtered state totals rather than summarizing the current 50-row page.
   - **Redesign Order Detail to 2-Column Layout**:
     - *Column 1 (Main)*: Order Status Header + Fulfillment Pipeline Stepper + Deliverables Card (with embedded audio player & lyric sheet) + Attempts History Table.
     - *Column 2 (Sidebar)*: Customer 360 Card (Telegram ID, Credits Balance, Order Count, Quick Grant Action) + Retention Clocks + Correlation Diagnostics.
3. **Users CRM & ManyChat-Style User Drawer**:
   - Add **Search Input** to Users Screen (`q` search by Telegram ID).
   - Add **Credit Balance Column** with clear badge chips (`2 credits`, `0 credits`).
   - Implement **Slide-out User Profile Drawer**:
     - User metadata & Telegram profile info.
     - Current credit balance + **"Grant Credits"** button with modal confirmation and audit reason.
     - Complete credit ledger history table (`GRANT`, `DEBIT`, `REFUND`).
     - Order history list.
4. **Generations Explorer & Audio Inspection**:
   - Replace layout-breaking side panel with an inline expandable row or slide-out inspection drawer.
   - Embed audio player directly in the attempt inspection view.
   - Provide side-by-side comparison: Customer Approved Lyrics vs. STT Acoustic Transcript with similarity diffing.
   - Add **"Retry Attempt"** operator action button.

### Phase 3: Business Analytics & Decision Support
1. **Credits & Monetization Dashboard**:
   - New dashboard tab / metrics view showing:
     - Total credits in circulation.
     - Free allowances minted vs. paid orders.
     - Credit burn rate by day.
2. **Funnel Drop-Off Analytics**:
   - Visualize wizard completion rates (Start -> Genre -> Lyrics -> Generation -> Complete).

---

## 7. Verification & Testing Strategy

1. **Visual & UX Regression Testing**:
   - Verify that all timestamp cells across all screens render clean relative time with dual UTC/Local hover tooltips.
   - Verify that no raw ISO strings appear anywhere in page ground captions or table cells.
   - Test table responsiveness on standard 1080p, 1440p, and laptop screens with both collapsed and expanded navigation rails.
2. **Backend Contract Testing**:
   - Ensure new credit endpoints (`GET /api/users/{id}/credits`, `POST /api/users/{id}/grant`) pass permission gates and write HMAC-chained audit rows to `admin_audit_log`.
   - Verify `_window` allows single-sided `from=` queries without HTTP 422 errors.
3. **Accessibility & Contrast**:
   - Verify that all status pills, glyphs, and metric badges maintain at least 4.5:1 contrast in both light and dark themes.

---

> [!TIP]
> **Recommended Immediate First Step**: Implement the **Timestamp & Duration Standardization** and fix the **Orders Screen Peek Panel**, then introduce the **User Credit Balance & Ledger** integration.
