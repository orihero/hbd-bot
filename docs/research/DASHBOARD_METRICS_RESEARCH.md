# Admin Dashboard — Metric Research & Visualisation Catalog

> Generated from a 15-agent research pass over the Bayram codebase: 8 parallel researchers, synthesis into one catalog, then a 5-way adversarial verification pass that re-opened every referenced model file to confirm each `table.column` actually exists.

**100 metrics** proposed · **94 survived** verification · **6 killed** · **51 cards** across **7 sections** · **17 instrumentation gaps** found

---

## The thesis

This is the screen a founder-operator opens at 08:00 in Tashkent with coffee, before opening Telegram. It answers four questions in falling order of panic: (1) is the pipeline delivering songs right now, and is anything wedged; (2) are we making or losing money on each song at the price actually shipped in config.py (7 000 UZS, not the $5.90 every planning doc assumes); (3) is the one thing we sell — a song that pronounces an Uzbek name correctly — still working; and (4) is personal data leaving on its lawful clock. It is deliberately NOT the Live screen (a single-question ops page that fetches a daily series and draws no chart) and NOT a replacement for the six detail screens — every tile is a headline whose drill-through is an existing screen. Two invariants are inherited wholesale from the codebase and are non-negotiable: null is a third state and never renders as 0 or $0.00 (a rate ships with its denominator, a cost ships with costedCalls and its cost_source), and no dashboard payload may contain a reveal-gated value or a raw telegram_user_id — DASHBOARD_READ is the one permission with no masking branch, and it must stay that way.

---

## Contents

1. [Is it on fire](#1-is-it-on-fire) — 16 metrics
2. [Unit economics and revenue](#2-unit-economics-and-revenue) — 18 metrics
3. [The credit economy](#3-the-credit-economy) — 10 metrics
4. [Vendors and the AI supply chain](#4-vendors-and-the-ai-supply-chain) — 11 metrics
5. [Does it sing the name](#5-does-it-sing-the-name) — 10 metrics
6. [Funnel, demand and customers](#6-funnel-demand-and-customers) — 17 metrics
7. [Privacy, retention and panel governance](#7-privacy-retention-and-panel-governance) — 18 metrics
8. [Killed in verification](#killed-in-verification)
9. [Instrumentation gaps](#instrumentation-gaps)
10. [Backend work, in unblocking order](#backend-work-in-unblocking-order)
11. [Open questions](#open-questions)

**Legend** — Availability: 🟢 served by an endpoint today · 🟡 one aggregation from an existing query · 🟠 needs a new endpoint · 🔴 the data is not captured at all. Tier: **T1** = looked at every morning, T2 = supporting, T3 = behind a tab.

---

## 1. Is it on fire

*The first thirty seconds. Live delivery health, what is wedged, and an honest statement of which numbers on this page are absences rather than zeros. Everything here must be able to change colour within minutes of an incident starting — which is why the all-time pulse rate is demoted in favour of a windowed one.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Delivery latency p50 / p95** | How long does a customer wait between confirming and receiving the song? | `distribution` | stat — *Delivery latency* | `CONFIRMED, including the unused-endpoint claim. `LATENCY_PATH = /api/metrics/latency`…` | 🟢 served today | **T1** |
| **Delivery success rate (24h, with prior-window delta)** | Of the orders that finished in the last 24 hours, what share shipped a song — and is that worse than… | `single-number` | F11 Tick Gauge — *Delivered, last 24h* | `GET /api/metrics/orders-by-day?from=&to= summed client-side is real — summariseDays…` | 🟡 one query away | **T1** |
| **Deployment capability ledger** | Which numbers on this screen are absences rather than zeros? | `breakdown` | list — *Instrumentation* | `CONFIRMED end to end, all eight flags. src/bayram/db/admin/metrics.py:214-225 returns…` | 🟢 served today | **T1** |
| **Order state distribution (whole book)** | Where is every order sitting right now, across the whole filtered set? | `breakdown` | F1 Rung Bars — *Where the whole book sits* | `CONFIRMED as written. Route is `ORDER_STATE_COUNTS_PATH = f"{ORDERS_PATH}/state-counts"`…` | 🟢 served today | **T1** |
| **Orders in flight** | How many orders have not yet reached a terminal state right now? | `single-number` | stat — *In flight* | `CONFIRMED as written. `PulseView.delivery` is a `DeliveryView` carrying `in_flight`…` | 🟢 served today | **T1** |
| **Orders per day (volume and outcome)** | How much work arrived each day, how did it end, and is today normal? | `timeseries` | F11 Tick Gauge — *Delivered, last 24h* | `Confirmed exactly as stated. orders_per_day (src/bayram/db/admin/metrics.py) selects…` | 🟢 served today | **T1** |
| **Stalled orders by age** | Is anything actually wedged, as opposed to merely running? | `distribution` | stat — *Oldest wedged order* | `CONFIRMED with one correction. orders.updated_at exists via TimestampMixin…` | 🟠 new endpoint | **T1** |
| **Abandoned-draft backlog** | How many wizard sessions were opened and never confirmed? | `single-number` | F1 Rung Bars — *Where the whole book sits* | `ALREADY SHIPPED — do not build it. bayram.db.purge.rows_past_expiry_statements…` | 🟢 served today | T2 |
| **Concurrency headroom** | Are we saturating the render pipeline? | `single-number` | F5 Tick Rows — *Live pipeline board* | `HALF WRONG — the numerator is fine, the ceilings are not available. `COUNT(orders WHERE…` | 🟠 new endpoint | T2 |
| **Delivered-but-not-received gap** | Did the audio actually reach Telegram, or did we only render it? | `single-number` | list — *Ops footnotes* | `COLUMNS ARE REAL but the JOIN PREDICATE IS WRONG. assets.tg_file_id (String(128),…` | 🟠 new endpoint | T2 |
| **Failures per day (error timeseries)** | When did this class of failure start, and is it new? | `timeseries` | G10 Diverging Bar — *Failure codes vs baseline* | `Correct as stated. failure_breakdown at src/bayram/db/admin/metrics.py:155-182 already does…` | 🟡 one query away | T2 |
| **Live pipeline board by non-terminal state** | Where in the funnel is every in-flight order sitting this second? | `breakdown` | stat — *In flight* | `SELECT state, count(*), min(created_at) FROM orders WHERE state IN…` | 🟠 new endpoint | T2 |
| **Order failure reasons** | When an order dies, what killed it? | `ranked-list` | G10 Diverging Bar — *Failure codes vs baseline* | `CONFIRMED. orders.failed_reason exists — src/bayram/db/models/order.py, `failed_reason:…` | 🟡 one query away | T2 |
| **Cancellation rate** | How often do orders end in cancellation rather than failure? | `single-number` | F2 Hairline Line — *Orders per day* | `UPGRADE THIS — the proposal under-sells it. `orders.state` carries `CANCELLED`…` | 🟢 served today | T3 |
| **Service readiness** | Are the database and Redis reachable, and which config version is live? | `single-number` | list — *Instrumentation* | `Confirmed: GET /readyz returns {status, database, redis, configVersion} to a caller…` | 🟢 served today | T3 |

**Why these are tier 1**

- **Delivery success rate (24h, with prior-window delta)** — The one number that says whether the product works, at the only grain that can move during an incident. On 10k delivered orders an all-time rate barely twitches for a totally failed morning — the current hero is exactly that, computed server-side over the whole record. The delta arm is what separates a bad day from a bad week; without it a 12-point drop reads identically to normal. Rate is null (never 0.0) when nothing terminated, and terminalCount/sampleCount must travel with it.
- **Orders in flight** — Separates 'quiet' from 'stuck'. A 100% rate with 40 in flight and a 100% rate with 0 in flight are different mornings, and inFlight is the only field that distinguishes work running from work failing. Reuse queryKeys.ops.pulse() so the top-bar LIVE pill and this tile share one request per tick.
- **Stalled orders by age** — inFlight is a volume, not an alarm. A generating order that has sat an hour is the one that needs a human, and a newest-first list buries it. OBS-6 pages SEV-2 at oldest queued job >5 minutes and SEV-1 on any paid order >10 minutes undelivered (NFR-6's hard deadline); this is the tile those alerts are drawn on. updated_at is the only 'last touched' signal in the schema, so this is the cheapest stall detector available.
- **Order state distribution (whole book)** — The densest shape in the console — one 8px band answers draft/authorized/generating/delivered/failed/cancelled at a glance — and the dashboard has no view of the book at all today, only of its 24h edge. Zero-filling is deliberate so a stacked bar does not re-lay-out under the cursor. Note it replaced a client-side computation over one 50-row page that reported the newest page's shape as the deployment's; do not reintroduce that.
- **Orders per day (volume and outcome)** — The biggest single miss on the current screen: the series is already paid for and no chart is drawn, even though Recharts is wired behind ChartFrame. It is the only line that distinguishes 'we had a bad hour' from 'we have been degrading for a week', and it is the denominator every other rate on the page is a proportion of — without it a falling failure count reads as an improvement when it is a traffic drop. The chart layer must fill absent days itself or the line will connect across gaps and imply continuity. Bucketing is UTC while the market is UTC+5, so the local 19:00-23:00 ordering peak straddles two UTC days — label the axis UTC.
- **Delivery latency p50 / p95** — The customer-felt quality of service and the metric NFR-6 is written in (p50 <=3 min, p95 <=6 min, hard deadline 10 min; NFR-12 measures 99.0% pipeline availability against that deadline). Percentiles are nearest-rank so both numbers were really observed. It MUST render with sampleCount — 'p95 = 4s' from three orders is not a measurement. Wiring the windowed endpoint instead of the pulse is the cheapest correctness win available: an all-time p95 cannot detect a slow morning.
- **Deployment capability ledger** — MEASURED, never declared, and load-bearing: isCostTelemetry is false (generation_attempts.cost_usd defaults 0.0, nothing writes it) and isStateTransitionLog is hardcoded false. Every 'not instrumented' state on the dashboard must branch on this rather than on an empty array. Best form on a redesign is NOT half a diagnostics row but a thin footer strip PLUS per-tile states, so a tile with no writer renders 'not instrumented' itself instead of a zero the ledger later has to retract. Performance caveat: the cost and latency probes scan unindexed columns and, because both are false in production, the pathological full-scan is the normal case.

---

## 2. Unit economics and revenue

*The reason this product either works or does not. Cost per delivered kit against the price actually in config, with the trustworthiness of every dollar figure stated on the tile. Revenue is built as a shape now even though the rail is a stub, because retrofitting it after Payme lands corrupts every prior period.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Bookings by day (plan purchases)** | How much money came in? | `timeseries` | F1 Rung Bars — *Bookings, last 8 weeks (stub rail)* | `CONFIRMED column for column on src/bayram/db/models/plan_purchase.py: `telegram_user_id`…` | 🟠 new endpoint | **T1** |
| **Cost per delivered song** | What does one delivered kit actually cost us in vendor fees? | `distribution` | F11 Tick Gauge — *Cost per delivered song* | `Every column checked and CONFIRMED on src/bayram/db/models/vendor_usage.py: `cost_usd`…` | 🟠 new endpoint | **T1** |
| **Fake / demo call contamination guard** | Is any of this spend from a fake-provider run? | `single-number` | stat — *Vendor spend, 30d* | `Columns verified: vendor_usage.is_fake Boolean NOT NULL default False, and Vendor.FAKE…` | 🟠 new endpoint | **T1** |
| **Priced coverage of the spend figure** | How complete is the dollar number I am reading? | `single-number` | stat — *Vendor spend, 30d* | `CONFIRMED. VendorUsageTotals.costed_calls: int at src/bayram/db/admin/views.py:982 (the…` | 🟢 served today | **T1** |
| **Unattributed pre-order vendor spend** | How much are we spending on people who never place an order? | `timeseries` | G18 Draw-in + Counter — *Free-tier spend (nobody to bill)* | `CONFIRMED with one counting bug to fix. `vendor_usage.order_id` is `Uuid, nullable=True,…` | 🟠 new endpoint | **T1** |
| **Vendor spend in window** | What did the AI vendors cost us over this window? | `single-number` | stat — *Vendor spend, 30d* | `CONFIRMED almost field for field. `GET /api/metrics/vendor-usage?from=&to=&vendor=` is…` | 🟢 served today | **T1** |
| **Active plan holders** | How many customers currently hold an unexpired plan with songs left? | `single-number` | stat — *Plan liability* | `COUNT(DISTINCT telegram_user_id) FROM plan_purchases WHERE plan_ends_at > now() AND…` | 🟠 new endpoint | T2 |
| **Cost provenance mix (vendor-reported / derived / estimated)** | How much of our reported spend is measured fact versus our own guess? | `breakdown` | F11 Tick Gauge — *Cost per delivered song* | `Column verified: vendor_usage.cost_source is enum_type(CostSource) nullable, tied to…` | 🟡 one query away | T2 |
| **Daily spend vs trailing 7-day mean, with per-order outliers** | Did spend jump today, and which orders caused it? | `timeseries` | F3 Hairline Area — *Spend per day vs trailing mean* | `SPLIT VERDICT. Daily-spend arm is real: VENDOR_USAGE_BY_DAY_PATH =…` | 🟡 one query away | T2 |
| **Deferred revenue: unconsumed plan songs** | How much of the money we have taken is still owed as songs? | `single-number` | stat — *Plan liability* | `FIRST HALF CONFIRMED, SECOND HALF NOT COMPUTABLE, AND THE INDEX IS THE WRONG ONE.…` | 🟠 new endpoint | T2 |
| **Effective revenue per song by product** | What does a song actually sell for once plan buyers use their allowance? | `distribution` | stat — *Price shipped vs cost* | `Every column verified on src/bayram/db/models/plan_purchase.py: amount_minor (Integer,…` | 🟠 new endpoint | T2 |
| **Free-tier cost per paid order and per free user** | Is pre-paywall spend eating the margin? | `timeseries` | G18 Draw-in + Counter — *Free-tier spend (nobody to bill)* | `COMPUTABLE, but the source needs two fixes and the GRAIN is partly impossible.…` | 🟠 new endpoint | T2 |
| **Invoice reconciliation variance** | Does our reported spend tie to the vendor's invoice? | `single-number` | F14 Rung Histogram — *Plan utilisation and breakage* | `COMPUTABLE, and cheaper than described on one side, more expensive on the other.…` | 🟠 new endpoint | T2 |
| **Plan utilisation and breakage** | Do customers use what they paid for? | `distribution` | F14 Rung Histogram — *Plan utilisation and breakage* | `CONFIRMED, every column. src/bayram/db/models/plan_purchase.py: songs_included (Integer,…` | 🟠 new endpoint | T2 |
| **Plans expiring within 7 days** | How many plans run out this week? | `single-number` | stat — *Plan liability* | `Columns confirmed: `plan_ends_at` (UtcDateTime, not null, index=True) and the…` | 🟠 new endpoint | T3 |
| **Token, character and audio-minute consumption** | What physical volume are we buying from each leg? | `timeseries` | table — *Vendor × operation × model* | `All five columns verified on vendor_usage (src/bayram/db/models/vendor_usage.py):…` | 🟡 one query away | T3 |

**Why these are tier 1**

- **Vendor spend in window** — The only real money on the whole console and the dashboard shows none of it. Three booleans must travel with the figure or it lies: isInstrumented (no writer at all), hasRowsInWindow (widen the range), isCostPriced (calls recorded, no rate configured). cost_usd is nullable with no default and NULL means NOT PRICED, never $0.00 — the CHECK cost_carries_its_source guarantees any priced row names its provenance. Exclude is_fake rows from the headline.
- **Priced coverage of the spend figure** — Bounds the credibility of every spend number on the screen. Today only music ships a rate (0.15/min, an admitted placeholder); elevenlabs_usd_per_character and all four LLM per-million rates ship 0.0, which records the quantity and leaves cost NULL. So a typical window's costUsd is a true sum over a MINORITY of the calls beside it, and a naked '$41.20' is a partial total read as a complete one.
- **Cost per delivered song** — THE unit-economics number for a business selling song kits, and the one the project's own research doc is about. NFR-14 makes it a MUST with a $0.45 ceiling against a $0.28 target, 'measured from cost, not assumed'; NFR-15 sets a $0.90 per-order circuit breaker; OBS-6 pages SEV-2 above $0.60. Today it can only be eyeballed by dividing two unrelated endpoints, and that division is a lie while costedCalls << calls. Must carry both its priced coverage and its attribution coverage — unattributed and unpriced spend both sit outside the numerator.
- **Unattributed pre-order vendor spend** — The one class of spend with nobody to charge it to, and structurally invisible to any cost-per-song figure. free_allowance_credits ships 0 by product decision — the free half of this product is the LYRIC, not a free song — so this IS the free tier's entire cost line. LR-34 makes it a MUST as a first-class dashboard metric from day one: 'the number most likely to quietly eat the margin, invisible unless deliberately measured'.
- **Fake / demo call contamination guard** — The Vendor enum docstring says FAKE exists so a BAYRAM_USE_FAKE_PROVIDERS run is RECORDED and visibly excluded rather than invisible — 'a demo that wrote no rows at all would be indistinguishable from a deployment nobody instrumented'. Any non-zero value in production is a red banner, not a chart. It is also the ONLY contamination guard that exists: SOW OBS-9c requires probe orders tagged is_probe and excluded from funnel/revenue/COGS, and orders has no is_probe column in this build.
- **Bookings by day (plan purchases)** — A dashboard for a product that sells things and cannot show revenue is not a business dashboard, and this is the only table in the schema holding a money amount at all. It will read near-zero and every row will carry provider='stub' today (StubCheckoutProvider always reports paid and contacts no rail), so the tile must be labelled from plan_purchases.provider — 'recorded purchases (stub rail)', never settled GMV. Build the shape before the rail lands, not after: LR-63 warns that retrofitting revenue recognition corrupts every prior reported period.

---

## 3. The credit economy

*With Payme stubbed and credits_enforced shipping False, the credit ledger IS the economy: a delivered song is a debited credit. This section is the entitlement P&L and the go/no-go evidence for switching enforcement on. Nothing in it is exposed by any endpoint today.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Unenforced (dark) renders** | How many renders would enforcement have refused? | `timeseries` | G18 Draw-in + Counter — *Dark renders, 30d* | `CONFIRMED, including the quote. `CreditReason.UNENFORCED_RENDER = "unenforced_render"`…` | 🟠 new endpoint | **T1** |
| **Credit balance drift** | Does any stored balance disagree with its own ledger? | `single-number` | stat — *Open (unsettled) debits* | `CONFIRMED — the function is real and genuinely unreachable from the panel.…` | 🟠 new endpoint | T2 |
| **Credits granted by reason** | Where do credits come from — allowances, purchases, comps, or the dark switch? | `breakdown` | F9 Rung Waterfall — *Minted vs burned* | `COLUMNS FINE, ENUM LIST WRONG. credit_ledger.kind (CreditEntryKind), reason…` | 🟠 new endpoint | T2 |
| **Credits minted vs burned** | Is the meter net-minting or net-burning? | `timeseries` | F9 Rung Waterfall — *Minted vs burned* | `COLUMNS CONFIRMED, ONE FACTUAL CLAIM WRONG, ONE ARITHMETIC GAP. Confirmed:…` | 🟠 new endpoint | T2 |
| **Open (unsettled) debits** | How many credits are locked against renders that never settled? | `single-number` | stat — *Open (unsettled) debits* | `The predicate exists twice and both are scoped. credit_sql.count_in_flight…` | 🟠 new endpoint | T2 |
| **Outstanding credit liability** | How many unspent credits are sitting on customer balances? | `single-number` | stat — *Plan liability* | `CONFIRMED. src/bayram/db/models/credit_account.py: balance (Integer, NOT NULL, default 0,…` | 🟠 new endpoint | T2 |
| **Refund rate** | How often does a render die badly enough to hand the credit back? | `timeseries` | F9 Rung Waterfall — *Minted vs burned* | `Numerator: COUNT(*) WHERE kind='refund'. Today its only reason is ORDER_FAILED.…` | 🟠 new endpoint | T2 |
| **Settlement outcome mix** | How do charges close — delivered, undeliverable, or swept? | `breakdown` | F7 Stacked Rungs — *How charges close* | `MATERIAL BUG IN THE PROPOSED QUERY. All three reasons exist (enums.py:147-152) and…` | 🟠 new endpoint | T2 |
| **Erased ledger rows** | How many accounts have exercised /forget? | `single-number` | stat — *Outstanding credit liability* | `COUNT(*) FROM credit_ledger WHERE telegram_user_id IS NULL, and COUNT(*) FROM…` | 🟠 new endpoint | T3 |
| **Lyric-budget pressure** | How many accounts are hitting the daily lyric-write ceiling? | `single-number` | F7 Stacked Rungs — *How charges close* | `CONFIRMED with one arithmetic correction. src/bayram/db/models/lyric_budget.py:…` | 🟠 new endpoint | T3 |

**Why these are tier 1**

- **Unenforced (dark) renders** — credits_enforced ships False on purpose, and the config comment states this counter's purpose outright: 'Counting these rows is how an operator sees what enforcement would have refused before switching it on.' It is the single go/no-go input for flipping the paywall on, designed into the schema for a dashboard that never read it. Present it as decision support, not as errors or lost revenue.

---

## 4. Vendors and the AI supply chain

*Where the money goes and where the failures start. Because no render-attempt writer exists, vendor_usage is also the ONLY honest render-failure signal in the build — which is why vendor error rate sits this high rather than in a diagnostics footer.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Vendor error rate and error mix** | Which vendor is failing us right now, and how? | `matrix` | F11 Tick Gauge — *Vendor error rate, 15m* | `CONFIRMED. `VENDOR_ERRORS_PATH = /api/metrics/vendor-errors` (routers/vendors.py:96,…` | ready — for the shipped population; needs-backend for an is_fake-excluded, health-excluded rate | **T1** |
| **Music spend share and cost per rendered minute** | Is the music vendor still the overwhelming majority of our cost, and are we paying the rate we think? | `timeseries` | stat — *Music minutes requested, MTD* | `SPLIT, and the gauge half is close to a tautology. The spend half is already on the…` | 🟡 one query away | T2 |
| **Vendor capacity headroom vs contractual caps** | How close are we to the ceiling that stops the product dead? | `single-number` | stat — *Music minutes requested, MTD* | `NUMERATOR IS BETTER THAN CLAIMED; CEILING CLAIM CONFIRMED MISSING.…` | 🟠 new endpoint | T2 |
| **Vendor fallback share** | Is the primary provider degraded enough that we are silently running on the backup? | `timeseries` | stat — *Silent fallback share* | `COLUMN IS REAL AND WRITTEN, but the availability is wrong. vendor_usage.is_fallback is…` | 🟠 new endpoint | T2 |
| **Vendor latency (avg / max)** | Which vendor leg is making customers wait? | `matrix` | F12 Dumbbell Queue — *Latency: mean to p95, per leg* | `Confirmed ready as stated for avg/max. vendor_usage.latency_ms is sa.Integer NULLABLE…` | 🟢 served today | T2 |
| **Vendor latency p95 per operation** | What does the slow tail of each vendor call look like? | `distribution` | F12 Dumbbell Queue — *Latency: mean to p95, per leg* | `CONFIRMED. `vendor_usage.latency_ms` is `Integer, nullable, no default` — the…` | 🟠 new endpoint | T2 |
| **Vendor spend and calls per day** | Is our vendor bill trending up, and which vendor is driving it? | `timeseries` | F3 Hairline Area — *Spend per day vs trailing mean* | `CONFIRMED exactly. `VENDOR_USAGE_BY_DAY_PATH = /api/metrics/vendor-usage-by-day`…` | 🟢 served today | T2 |
| **Vendor x operation x model rollup** | Which vendor leg is burning the money, and at what unit? | `matrix` | table — *Vendor × operation × model* | `CONFIRMED, every field. Route: src/bayram/admin/routers/vendors.py:94 VENDOR_USAGE_PATH =…` | 🟢 served today | T2 |
| **Health-probe volume and outcome** | Are the quota probes seeing a healthy vendor? | `timeseries` | stat — *Silent fallback share* | `UPGRADE — this is already on the wire, not merely derivable. `VendorOperation.HEALTH =…` | ready (as a windowed gauge); needs-backend only for a per-day health series | T3 |
| **LLM parse-retry rate** | Is the lyric model returning valid JSON, or are we paying twice per order? | `timeseries` | — | `Sharper and simpler than proposed: the parse failure is RECORDED ON THE ROW.…` | 🟡 one query away | T3 |
| **Vendor HTTP status mix** | Are failures rate limits, auth problems, or transport drops? | `breakdown` | L4 Arc Matrix — *Errors by vendor and code* | `CONFIRMED. src/bayram/db/models/vendor_usage.py: `http_status: Mapped[int \| None] =…` | 🟡 one query away | T3 |

**Why these are tier 1**

- **Vendor error rate and error mix** — Promoted to tier 1 by a schema fact the researchers split on: because GenerationAttemptRepository.record() has no call site, generation_attempts holds only name-verification verdicts — so vendor_usage is the ONLY honest render-failure signal in this build. A vendor outage is also the most likely cause of a falling delivery rate, and DECISIONS §8 notes ElevenLabs carries music plus RU/EN TTS plus STT, 'four of eight layers on one account, one ToS, one card', so a single suspension is a correlated outage. OBS-6 pages SEV-2 above a 10% failure rate over 15 minutes. A denominator spanning all vendors would report one broken ElevenLabs call as near-zero share simply because OpenRouter was busy.

---

## 5. Does it sing the name

*The product's single differentiator and its own health metric. A delivery rate of 100% made of songs that mispronounce the recipient is a refund queue. Every metric here is an aggregate over verdicts and scores; the candidate text and transcripts behind them are reveal-gated and appear nowhere.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Name verification pass rate** | Do the vendors actually sing the recipient's name? | `single-number` | F11 Tick Gauge — *Name pass rate, 7d* | `Column verified: generation_attempts.is_name_verified is Mapped[bool \| None],…` | 🟢 served today | **T1** |
| **Bring-your-own-lyrics share** | How many orders take the path where our pronunciation guarantee does not apply? | `single-number` | stat — *Bring-your-own-lyrics share* | `THE PROPOSED PREDICATE IS WRONG. Use the ABSENT RECIPIENT, not the present lyric:…` | 🟠 new endpoint | T2 |
| **Match confidence distribution and threshold band** | Are verifications passing comfortably or scraping the threshold? | `distribution` | stat — *Scraping the threshold* | `CONFIRMED, and the payload is richer than described. Route:…` | 🟢 served today | T2 |
| **Name strategy bake-off** | Which candidate orthography should BAYRAM_NAME_CANDIDATE_ORDER put first? | `ranked-list` | F5 Tick Rows — *Strategy bake-off* | `CONFIRMED, with the index claim overstated. `NAME_STRATEGIES_PATH =…` | 🟢 served today | T2 |
| **Audio quality outliers** | Are we shipping songs that are too short, too quiet or malformed? | `distribution` | — | `Columns confirmed on src/bayram/db/models/asset.py: `duration_s` (Float, **nullable=False,…` | 🟠 new endpoint | T3 |
| **Candidate rank effectiveness** | Is the first-ranked orthography usually the one that works? | `matrix` | F5 Tick Rows — *Strategy bake-off* | `Columns verified in the 'tuning signal: never purged, never personal data' block of…` | 🟡 one query away | T3 |
| **Expiring user-confirmed name records** | How much of the dictionary is about to lawfully evaporate? | `single-number` | F5 Tick Rows — *Backlog by clock* | `CONFIRMED, and it is already SHIPPED for the past-due case. name_records.expires_at is…` | 🟡 one query away | T3 |
| **Genre x verification pass rate** | Which musical styles break name pronunciation? | `matrix` | F10 Dot Heat — *Genre × language pass rate* | `CONFIRMED, with a simpler join than proposed. `briefs.genre` is `enum_type(Genre),…` | 🟠 new endpoint | T3 |
| **Name correction volume** | How often does a human tell us we got a name wrong? | `single-number` | F5 Tick Rows — *Strategy bake-off* | `COLUMNS CONFIRMED; A DECAY THE PROPOSER MISSED. `name_records.correction_count`…` | 🟠 new endpoint | T3 |

**Why these are tier 1**

- **Name verification pass rate** — This is the actual product — README says the pronunciation is 'the entire product' — and delivery can be 100% while the songs are wrong. Gate 1 sets the bars per language, cleared by the LOWER bound of the 95% CI: sung >=85% RU/EN and >=70% Uzbek; failing Uzbek sung triggers Tier B (Uzbek ships spoken-only), which SOW calls the most likely outcome. RESEARCH notes the true first-pass rate is unmeasured for every vendor on earth, so this chart is the only evidence that will ever exist. Exclude bring-your-own-lyrics orders from the denominator — they carry recipient=None and never enter the ladder.

---

## 6. Funnel, demand and customers

*Who arrives, who converts, who comes back, and when the calendar spikes. Honest about the limit: with no order_events table the pipeline funnel counts survivors, not passages, and that must be said on the tile rather than papered over.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Daily active accounts (DAU / MAU)** | How many real people touched the bot today? | `single-number` | stat — *Active accounts* | `users.last_seen_at is real: Mapped[datetime], UtcDateTime, nullable=False,…` | 🟠 new endpoint | **T1** |
| **Activation rate** | What share of accounts that said hello ever confirmed an order? | `cohort` | L13 Hourglass Stream — *Where people fall out* | `Columns exist: users.id and users.created_at (TimestampMixin, index=True,…` | 🟠 new endpoint | T2 |
| **Occasion / genre / language mix** | What are customers actually ordering, and in which language? | `breakdown` | F10 Dot Heat — *Genre × language pass rate* | `Columns CONFIRMED on src/bayram/db/models/brief.py — `occasion`, `genre`, `vocal_gender`,…` | 🟠 new endpoint | T2 |
| **Occasion-date seasonality calendar** | When is the next demand spike, so we can pre-scale? | `matrix` | L17 Calendar Heat — *The occasion calendar* | `CONFIRMED, and durable — better than the proposer knew. `briefs.event_day` and…` | 🟠 new endpoint | T2 |
| **Onboarding lifecycle funnel** | Where do people fall out between opening the bot and getting a song? | `funnel` | L13 Hourglass Stream — *Where people fall out* | `CONFIRMED, all five columns, exactly as claimed. users.created_at via TimestampMixin…` | 🟠 new endpoint | T2 |
| **Order-state survivor funnel** | Which pipeline stage loses the most orders, as best the schema can say? | `funnel` | L13 Hourglass Stream — *Where people fall out* | `STAGES 1,2,4,5 CONFIRMED; STAGE 3 DECAYS TO ZERO; THE ABANDONMENT PREDICATE IS WRONG.…` | 🟠 new endpoint | T2 |
| **Paid conversion rate** | What share of orders created actually reached the authorised moment? | `timeseries` | F11 Tick Gauge — *Authorised conversion* | `CONFIRMED end to end. `orders_per_day` (db/admin/metrics.py:76-102) selects `count()` as…` | 🟢 served today | T2 |
| **Repeat purchase rate** | Do buyers come back for a second song? | `cohort` | F11 Tick Gauge — *Authorised conversion* | `Verified: orders.telegram_user_id is BigInteger NOT NULL and denormalised onto the order…` | 🟠 new endpoint | T2 |
| **Signups per day** | How many new accounts touched the bot each day? | `timeseries` | F2 Hairline Line — *Signups per day* | `SEMANTICS CONFIRMED; THE INDEX CLAIM IS FALSE — THIS IS THE HALLUCINATION. 'users has NO…` | 🟠 new endpoint | T2 |
| **Blocked accounts** | How many accounts are barred, and did that change? | `single-number` | stat — *Active accounts* | `users.is_blocked is Boolean NOT NULL default False and GET…` | 🟡 one query away | T3 |
| **Lyrics-preview volume vs orders** | Do people who try the free lyric writer come back and buy? | `relationship` | L17 Calendar Heat — *The occasion calendar* | `UsageTask.LYRICS_PREVIEW confirmed at src/bayram/contracts.py:333, and its docstring…` | 🟡 one query away | T3 |
| **Nameless-song adoption** | Is the new 'song that names nobody' path being used? | `timeseries` | stat — *Bring-your-own-lyrics share* | `CONFIRMED, and the proposal is more right than it claims. `recipient_name_raw`,…` | 🟠 new endpoint | T3 |
| **Time to first order** | How long from first contact to first confirmed order? | `distribution` | L13 Hourglass Stream — *Where people fall out* | `MIN(orders.created_at) per user_id minus users.created_at is expressible from the…` | 🟠 new endpoint | T3 |
| **Total users under filter** | How big is the population I am looking at? | `single-number` | stat — *Active accounts* | `CONFIRMED down to the constant. `TOTAL_COUNT_CAP: Final[int] = 10_000` at…` | 🟢 served today | T3 |
| **UI vs output language cross-tab** | Do people order songs in the language they read the bot in? | `matrix` | F5 Tick Rows — *What people order* | `Columns verified and better-placed than the proposal claims: briefs.ui_language and…` | 🟠 new endpoint | T3 |
| **Vocal gender mix** | What voice do customers ask for? | `breakdown` | F5 Tick Rows — *What people order* | `CONFIRMED. briefs.vocal_gender is `Mapped[VoiceGender] =…` | 🟡 one query away | T3 |

**Why these are tier 1**

- **Daily active accounts (DAU / MAU)** — The core engagement metric of any bot product, and it corrects a stale claim in the redesign plan (§3.4) that last_seen_at only moves on order creation. Two hard caveats: the column is overwritten in place, so this is a GAUGE that can never be back-filled into a historical series, and there is no index on last_seen_at. The count is defensible as an aggregate; exposing the column per row is not — it is deliberately withheld from every /users view so an operator cannot watch one customer minute by minute.

---

## 7. Privacy, retention and panel governance

*Privacy is a shipped product constraint here, not a compliance afterthought — reveal is step-up gated, budgeted and HMAC-chained. This section is how an operator sees that the machinery is working, and it belongs on the dashboard rather than three clicks away because a scheduler that quietly stopped is invisible everywhere else.*

| Metric | The question it answers | Shape | Visualisation | Source | Avail. | Tier |
|---|---|---|---|---|---|---|
| **Retention backlog by clock** | How many rows are past their retention clock right now? | `breakdown` | stat — *Rows past their clock* | `CONFIRMED, all twelve keys, verbatim. src/bayram/admin/schemas/retention.py:59-78…` | 🟢 served today | **T1** |
| **Assets past expiry** | What audio is past its deletion date, and what is about to be swept? | `single-number` | stat — *Rows past their clock* | `Confirmed to the predicate. GET /api/retention returns rowsPastExpiry as SweepCounts,…` | 🟢 served today | T2 |
| **Login and step-up failures** | Is the panel under credential pressure? | `timeseries` | F1 Rung Bars — *Reveals and denials by operator* | `Actions CONFIRMED verbatim in src/bayram/db/enums.py: `LOGIN_FAILURE = "login.failure"`…` | 🟠 new endpoint | T2 |
| **Object-store deletion leak** | Did every purged record's bytes actually get deleted? | `single-number` | stat — *Last sweep* | `CONFIRMED end to end. `purge_runs.storage_keys_returned`, `storage_keys_deleted` and…` | 🟢 served today | T2 |
| **Permission denials** | Is anyone repeatedly hitting walls they should not be at? | `ranked-list` | F1 Rung Bars — *Reveals and denials by operator* | `Split the two predicates. For the RBAC question use action = 'permission.denied'…` | 🟡 one query away | T2 |
| **Retention sweep health** | Did the purge run, did it finish, and is it falling behind? | `timeseries` | stat — *Last sweep* | `Every field verified against src/bayram/admin/schemas/retention.py: RetentionResponse…` | 🟢 served today | T2 |
| **Reveal volume by operator** | How much customer data did operators unmask, and is anyone over budget? | `ranked-list` | F1 Rung Bars — *Reveals and denials by operator* | `CONFIRMED with a material RBAC correction. AuditAction.REVEAL_PERSONAL =…` | 🟡 one query away | T2 |
| **Storage-key coverage** | Can the purge job actually delete the bytes it is deleting the records for? | `single-number` | stat — *Last sweep* | `COLUMN CONFIRMED, AVAILABILITY WRONG. `assets.storage_key` is `String(PATH_LENGTH),…` | 🟠 new endpoint | T2 |
| **Admin actions per day by action** | How much is the panel being used, and for what? | `timeseries` | table — *Sweep history, last 24 runs* | `COLUMNS CONFIRMED, AVAILABILITY TOO OPTIMISTIC. `admin_audit_log` has `at` (UtcDateTime,…` | 🟠 new endpoint | T3 |
| **Admin roster health** | Is the console's own access hygiene sound? | `breakdown` | table — *Sweep history, last 24 runs* | `CONFIRMED field for field. `GET /api/admins` is src/bayram/admin/routers/admins.py under…` | 🟢 served today | T3 |
| **Admin session posture** | Who is logged in, who is elevated, and are sessions being cleaned up? | `single-number` | F1 Rung Bars — *Reveals and denials by operator* | `Every column verified on src/bayram/db/models/admin_session.py: revoked_at (nullable),…` | 🟠 new endpoint | T3 |
| **Asset deduplication rate** | Are we storing the same bytes twice? | `single-number` | table — *Sweep history, last 24 runs* | `Column CONFIRMED: `assets.sha256` is `String(SHA256_LENGTH), nullable=False,…` | derivable — expressible in one statement over an existing indexed column, but with no route today it still needs a db/admin function plus a schema and route; treat it as small needs-backend work rather than free | T3 |
| **Asset storage footprint** | How many bytes are we holding, and of what? | `breakdown` | table — *Sweep history, last 24 runs* | `CONFIRMED. src/bayram/db/models/asset.py: kind (AssetKind enum, :50), size_bytes…` | 🟠 new endpoint | T3 |
| **Audit chain integrity** | Can the tamper-evident audit log still be trusted? | `single-number` | stat — *Audit chain* | `CONFIRMED, all seven fields. src/bayram/admin/schemas/audit.py:118-133 ChainVerifyResponse:…` | 🟢 served today | T3 |
| **Audit reason-code mix** | Why do operators say they are touching customer data? | `breakdown` | table — *Sweep history, last 24 runs* | `Correct as stated. admin_audit_log.reason_code is enum_type(AuditReasonCode) NOT NULL…` | 🟡 one query away | T3 |
| **Destructive admin actions (24h)** | Did anyone do something irreversible today? | `single-number` | stat — *Audit chain* | `Confirmed as already built. AuditScreen.tsx:210-218 builds destructiveQuery = {from:…` | 🟢 served today | T3 |
| **Purge trigger mix** | Are sweeps routine, manual, or driven by erasure requests? | `breakdown` | stat — *Last sweep* | `CONFIRMED exactly as written. `PurgeRunRow.trigger` is `enum_type(PurgeTrigger),…` | derivable — the runs are already on the wire at GET /api/retention (each PurgeRunView carries its trigger), so a windowed count over the last N runs needs no backend at all; a count over a longer window than MAX_RUN_HISTORY does | T3 |

**Why these are tier 1**

- **Retention backlog by clock** — The most compliance-critical panel available: each non-zero row is personal data sitting past its lawful clock — data we told someone we would have deleted. It is deliberately NOT derived from the last run's counts, because isBatchFull answers 'run again', never 'how far behind'. Privacy is a real shipped constraint here, so this belongs on the fire strip rather than three clicks away, and it is already computed and reachable only on the Retention screen. Performance caveat: one unbounded COUNT per clock across five tables on every request.

---

## Killed in verification

These were proposed by a researcher and then removed when a verifier actually opened the model file. They are recorded so nobody re-proposes them.

### `name-verification-failure-codes` — Name-verification failure breakdown by error code

Second, independent caveat the proposal misses: `_replace_verdicts` DELETEs this order's NAME_VERIFICATION rows before re-inserting (repository.py:422-426), so this table is a snapshot of each order's LATEST verdict set, not an append-only history. `created_at` is the last-save instant, which quietly distorts any windowed count over it.

### `contribution-margin-per-song` — Contribution margin per delivered song

Keep the metric's intent — the pricing contradiction it exposes is real and the shipped catalogue values check out — but the tile cannot be built until the prices are mirrored into AdminSettings. Do not let anyone 'fix' it by hardcoding 700_000 in the SPA; that reintroduces exactly the stale-$5.90 problem the metric was written to kill.

### `music-billing-granularity` — Music billing-granularity probe

No PII either way. Keep the metric on the roadmap but relabel its availability honestly: as written it would render an empty chart that reads as 'no music was rendered' rather than 'this deployment cannot answer the question'. That is precisely the failure the capability ledger exists to prevent, and this tile needs its own 'not instrumented' state.

### `dictionary-coverage` — Pronunciation dictionary coverage and zero-LLM hit rate

The PII warning is right and UNDERSTATED. name_records.grapheme and display_form ARE recipient names when source=user_confirmed (NameSource.is_personal_data returns True for exactly that member), and unlike briefs.recipient_name_display they are NOT RevealField members on either side — revealFields.ts covers six briefs fields, two attempts fields and four user_profiles fields, and name_records appears nowhere. So there is no audited path to them and no masking serializer: a tile rendering one would be an unaudited disclosure with no budget and no audit row. Counts, confidence buckets and rates by source/language ONLY. Never a 'top names' list.

### `order-transition-funnel` — True order-transition funnel

States and timestamps only, if built that way — and it should be, since orders deliberately carries no recipient data (DAT-3, order.py module docstring). Do NOT put an actor free-text field on the new table; follow admin_audit_log and use a closed enum plus an actor id. Tier 2 as 'prerequisite to build, not a tile to ship' is the right call.

### `tg-file-id-reuse` — Telegram file-id reuse coverage

THE SECOND BREAK IN THE GROUP, and more dangerous than a wrong column name because it fails silently in the believable direction: a 0% coverage tile reads as 'we are burning egress on every re-send' when it actually means 'the column was never populated'. Same class of defect as generation_attempts.cost_usd DEFAULT 0.0 — the one the whole vendor_usage table was built to avoid repeating. It should not ship as a percentage before the writer exists.

---

## Instrumentation gaps

Questions the business needs answered that **the current schema cannot answer at all**. Each is a decision to make, not a bug to fix.

1. NO ORDER STATE-TRANSITION LOG. capabilities.isStateTransitionLog is hardcoded false and bayram.db.admin.orders.build_timeline infers every transition from mutable columns. orders carries only created_at, updated_at (overwritten on every touch) and delivered_at, so time-in-state, per-stage dwell, and 'which state did this order die in' are not computable — an order that passed through AUTHORIZED and then failed retains no record of the passage. Fix: an order_events table (order_id, from_state, to_state, at, actor) plus a pipeline writer. This is the prerequisite for every real funnel on the screen.

2. NO RENDER-ATTEMPT WRITER. GenerationAttemptRepository.record() has no call site anywhere in src/ — the only writer is repository._replace_verdicts via attempts.verdict_row_values, which writes NAME_VERIFICATION rows only. Consequences the dashboard must respect: attempts-per-delivered-order, retry depth, attempt success by kind and by provider are all unbuildable; a delivered order can report attempt_count = 0 while three songs were rendered; and /api/metrics/failures is a name-check failure list, not a render failure list. Fix: call the writer from the render path, or formally retire the table's render columns in favour of vendor_usage.

3. generation_attempts.cost_usd (default 0.0) and .latency_ms (default 0) have no writer at all, and their defaults read as 'free' and 'instant'. capabilities.isCostTelemetry / isLatencyTelemetry probe for a non-zero value and are false in production, which also means those two probes full-scan an unindexed column on every uncached call. Either wire the worker or retire the columns; vendor_usage already supersedes both.

4. plan_purchases HAS NO ADMIN SURFACE. The table holds telegram_user_id, plan, songs_included, songs_used, amount_minor, currency, provider, reference, idempotency_key and plan_ends_at with two indexes, and grep finds zero references to PlanPurchaseRow under src/bayram/admin/ or src/bayram/db/admin/. Needs db/admin/plans.py, schemas/plans.py and routes before any revenue, plan-liability, utilisation or deferred-revenue tile can exist.

5. NO CREDIT AGGREGATE ENDPOINT. credit_ledger and credit_accounts are readable only per user at GET /api/users/{telegramUserId}/credits. Every metric in the credit-economy section — mint vs burn, grants by reason, liability, refund rate, settlement mix, open debits, unenforced renders — needs a new windowed GROUP BY over an append-only table that already carries the indexes for it.

6. SINGLE-SONG TOP-UP REVENUE IS NOT RECORDED. bayram.db.purchases._fulfil_single writes only a credit_ledger GRANT (reason=TOPUP_PURCHASE, delta=+1) with no amount, currency, provider or reference. Top-up bookings can only be estimated as COUNT(reason='topup_purchase') x Settings.single_song_price_minor — a config value at read time, not the price actually charged. Fix: a purchases table, or the amount columns on the ledger row.

7. NO FX RATE ANYWHERE. Revenue is UZS minor units; vendor cost is USD. Every margin number needs an out-of-band, dated UZS/USD rate that the dashboard must display rather than silently apply. Related and worth surfacing on the same tile: the shipped catalogue (7 000 UZS a song, 49 000 UZS for a 12-song plan) is roughly a tenth of the $5.90 every margin figure in the planning docs assumes.

8. NO ACCOUNTS-PER-DAY METRIC, AND NO INDEX TO BUILD IT ON. users has only the unique telegram_user_id index — nothing on created_at or last_seen_at — so both the signup series and DAU are full scans today. The existing UsersScreen sparkline is derived from one page of rows and prints its own surrender above 200 new accounts in the window.

9. NO is_probe COLUMN ON ORDERS. SOW OBS-9c requires synthetic probe orders to be tagged and excluded from funnel, revenue, COGS and conversion, asserted by a test. vendor_usage.is_fake is the only contamination guard that exists, and it covers vendor calls, not orders.

10. NO CHAT / EVENT CAPTURE. capabilities.isChatCapture is false and no chat_messages table exists, so per-wizard-screen drop-off is unmeasurable no matter what else is built. There is also no GET /api/ops/feed — the current 'live feed' is the polled orders list relabelled, and no event bus exists behind it.

11. NO PAYMENTS TABLE AND NO RAIL ATTRIBUTION. capabilities.isPaymentLedger is false; StubCheckoutProvider always reports paid. Beyond the missing revenue rows, payment RAIL attribution is unrecoverable by construction for two of three cases — credit_accounts.balance is fungible with no lot structure, so a DEBIT cannot say whether it spent an allowance credit or an admin comp. A 'revenue by source' breakdown would be invented, not derived.

12. NO VENDOR LATENCY PERCENTILES. VendorUsageRollup exposes avg and max only. p95 over vendor_usage.latency_ms is one new query using the technique _percentile already uses for delivery latency, and it is the number that actually predicts customer-visible slowness.

13. NO WINDOWED DELIVERY-RATE ENDPOINT. The 24h hero is browser arithmetic over orders-by-day because /api/ops/pulse refuses a window by design. A windowed delivery-outcome route would also relieve the pulse, whose latency percentiles sort a computed duration expression no index can serve, twice per tick, over the whole delivered set.

14. NO EXPLICIT FEATURE FLAGS on briefs for the two newest features. Bring-your-own-lyrics and nameless-song adoption are inferable only from NULL patterns (approved_lyrics IS NOT NULL; recipient_name_raw IS NULL AND identity_purged_at IS NULL), and both inferences decay once the 30-day text and 90-day identity sweeps fire. Two boolean columns would make both exact and permanent.

15. NO HISTORY ON lyric_budgets. One row per account with day_index and writes overwritten in place — deliberately, so nothing accumulates and nothing needs purging. Abuse pressure can therefore only ever be a point-in-time gauge; a trend needs a new table or a nightly snapshot.

16. NO VENDOR TIER CAP OR QUOTA IN CONFIG. music_max_concurrency exists but the contractual monthly generation-minute ceiling does not, so the capacity-headroom tile FR-108 requires needs an operator-entered value. Related: no support/ticket store exists at all, so OBS-7's first-response and contact-rate tiles and FR-105/FR-106 are not buildable and must not be stubbed with zeros.

17. NO GEOGRAPHY, NO EXPERIMENT ID, AND NO MODERATION TABLE. There is no region/city/carrier column anywhere (deriving one from user_profiles.phone_e164 would be high-risk PII against a deliberately unindexed, unfilterable column); no variant or A/B id, so every strategy, genre and provider comparison is observational; and no record of what was moderated or its verdict — only admin_audit_log rows and vendor_usage WHERE task='moderation'.

---

## Backend work, in unblocking order

Ordered by how many tier-1 cards each item unblocks.

- 1. PERMISSION BRIDGE + FOLD BUNDLE (unblocks cards 6, 7, 8, 54, 55 and the entire section-1 fold for a dashboard-only operator). Today /api/orders/state-counts is RECORDS_READ and /api/retention is RETENTION_READ, while every other dashboard route is DASHBOARD_READ — an operator holding only DASHBOARD_READ gets a 403 on the fold's headline tiles. Add GET /api/metrics/fold under DASHBOARD_READ returning {stateCounts, rowsPastExpiry, capabilities, pulse}, reusing count_orders_by_state and rows_past_expiry_statements verbatim. Keep the existing routes for the detail screens. This is the single highest-leverage change on the list and it is plumbing, not new SQL.

- 2. FIX _narrow IN src/bayram/db/admin/vendor_usage.py: add optional is_fake and operation filters (unblocks cards 12, 13, 14, 30, 31, 33, 34, 35, 36). This is not a new tile — it is a CORRECTNESS FIX to every vendor figure the panel already shows. Today fake-provider rows and health probes are folded into costUsd, calls, successRate, avgLatencyMs and the error breakdown, so a BAYRAM_USE_FAKE_PROVIDERS demo run inflates real spend and a quota probe moves a rate that pages SEV-2. Add `is_fake: bool | None` and `exclude_operations: tuple[VendorOperation, ...]` to the shared helper and expose both as query params. The fake-call guard tile is the receipt for this fix.

- 3. NEW AGGREGATE: stalled orders + live pipeline board (cards 3, 10). One route, one query: SELECT state, count(*), min(created_at), max(now()-updated_at), plus CASE-bucketed age counts, WHERE state IN (draft, brief_ready, lyrics_ready, authorized, generating) GROUP BY state. Index-served by ix_orders_state_created_at. Label updated_at 'last touched', not 'time in state'. Also fixes the pulse's silent inclusion of DRAFT in inFlight by giving the SPA a per-state number to subtract.

- 4. COST PER DELIVERED SONG (card 13, the tier-1 economics figure). New db/admin function joining vendor_usage.order_id to the delivered cohort defined as state='delivered' AND created_at IN window (NOT delivered_at, which has no index and would not reconcile with any other tile). Return sum(cost_usd), count(*) FILTER (cost_usd IS NOT NULL), count(DISTINCT order_id), the delivered count, and the dominant cost_source. Ship the MEAN first; defer the p50/p95 per-order distribution, which needs a COUNT round-trip plus one OFFSET query per percentile over an unindexed GROUP BY order_id.

- 5. MIRROR SETTINGS ONTO AdminSettings + config_view ALLOWLIST (unblocks cards 14, 10, 32 and every threshold rule on the page). Needed: the shipped kit price (7 000 UZS) and an operator-entered FX note, music_usd_per_minute, music_max_concurrency, worker_concurrency. Follow the established pattern of admin_name_match_min_similarity and admin_free_allowance_credits — the latter's docstring records that defaulting instead of mirroring already cost the panel a real bug. Three files per value: AdminSettings field, config_view entry, and the SPA reading it. Do NOT let the SPA hardcode any of them.

- 6. CREDIT LEDGER AGGREGATE MODULE — new src/bayram/db/admin/credit_metrics.py (unblocks the ENTIRE credits section, cards 22–28; nothing in the admin API aggregates this table today, only per-account reads). One grouped query over the window returning GROUP BY (UtcDay(created_at), kind, reason) serves mint-vs-burn, grants-by-reason, refund rate, settlement mix and the unenforced-render series in a single round trip — combine them rather than issuing five. Plus: SUM(balance)/COUNT(*)/SUM(lifetime_granted) over credit_accounts; the global form of credit_sql.count_in_flight (same NOT EXISTS on (order_id, generation), minus the per-user predicate); and NULL-telegram_user_id counts on credit_ledger and plan_purchases. Filter on reason IN (...), never on kind, and group by the (kind, reason) PAIR.

- 7. UNATTRIBUTED PRE-ORDER SPEND (card 16). Daily series: WHERE order_id IS NULL AND task IS NOT NULL, GROUP BY UtcDay(created_at), task, with sum(cost_usd) and count(*). The task IS NOT NULL clause is not optional — health probes also carry a null order_id and would be counted as free-tier spend. Pair with the paid-order denominator from orders.is_paid.

- 8. PLAN_PURCHASES READ MODULE + ROUTE (cards 17, 20, 21; the table is 0% exposed — no db/admin module, no schema, no router). One module serving: bookings GROUP BY (UtcDay(created_at), plan, currency, provider); utilisation cohort GROUP BY month with AVG(songs_used/songs_included); breakage SUM(songs_included−songs_used) WHERE plan_ends_at <= now; deferred liability SUM(songs_included−songs_used) WHERE plan_ends_at > now; COUNT(DISTINCT telegram_user_id) for active holders; and the 7-day expiry window. Use UtcDay, never sa.func.date. Reuse db/plan_sql's live_plan predicate. The only index that serves a global plan_ends_at predicate is the standalone ix_plan_purchases_plan_ends_at — ix_plan_purchases_user_ends leads with telegram_user_id and cannot.

- 9. TWO CHEAP COLUMNS ADDED TO EXISTING GROUP BYs (cards 19, 31). Add is_fallback to vendor_usage_rollup's and vendor_usage_per_day's GROUP BY and wire models — the column is first-class, populated end to end by three adapters, and grep shows zero reads anywhere in the admin layer. Separately, add a cost_source GROUP BY (four-way, NULL kept as a bucket); it cannot be reconstructed from the wire because the rollup collapses provenance to a MIN/MAX is_cost_mixed pair. This is the highest value-per-line change in the whole list.

- 10. VENDOR p95 PER LEG (card 35). Reuse metrics._percentile + nearest_rank_offset for a SMALL FIXED SET of (vendor, operation) pairs — music_compose, speech_synthesis, chat_completion — not the 4×6 cross-product, which would be up to 24 groups × 3 round trips. Refresh on the 24h cadence. Do not reach for percentile_cont: it is Postgres-only and the unit suite runs SQLite, and a query only production can execute is a query nobody tests.

- 11. NAME ANALYTICS EXTENSIONS (cards 38, 44). (a) Group the verification rate by generation_attempts.language so Gate 1's per-language bars (≥85% RU/EN, ≥70% Uzbek) become evaluable — neither shipped endpoint groups by it today. (b) New genre × output_language cross-tab joining generation_attempts.order_id to briefs.order_id, with SERVER-SIDE suppression of cells below 5. Neither may widen its projection to name_candidate_text or stt_transcript.

- 12. USERS AND FUNNEL AGGREGATES (cards 46, 47, 50). (a) accounts-per-day: GROUP BY UtcDay(created_at) — cheap, ix_users_created_at has existed since migration 0001, contrary to the audit note. (b) DAU/MAU: ONE query with count_where over three cutoffs on last_seen_at, polled at 60s+ — the column is unindexed, so three separate queries are three full users scans. (c) Onboarding cohort: MATERIALISED nightly, not live — user_profiles has no index on any of its three lifecycle timestamps and the per-user MIN(orders.created_at) is the costly leg. Same treatment for repeat-purchase cohorts.

- 13. INDEX AND MIGRATION BATCH, raised once rather than as scattered caveats: ix_assets_created_at (or a composite (kind, created_at)) — blocks BOTH the asset growth series and the dedup count; a partial index on credit_ledger(created_at) WHERE reason='unenforced_render', with exact precedent in ix_generation_attempts_failures_created_at; a partial index users(id) WHERE is_blocked, so the blocked count stops full-scanning in the normal case; and consider a composite credit_ledger(kind, created_at) if the open-debits tile is polled — ix_credit_ledger_user_created leads on telegram_user_id and cannot serve a global window.

- 14. AUDIT AGGREGATES (cards 59, 60). Three grouped readers over admin_audit_log, none of which exist: reveal volume GROUP BY (actor_username, reason_code) with sum(record_count) and a null-count footnote, filtered action='reveal.personal' (index-served by ix_admin_audit_log_action_at); permission denials GROUP BY actor_username filtered action='permission.denied' ONLY; and admin actions GROUP BY (UtcDay(at), action, outcome) — never by subject_id, and never projecting reason_text. Gate reveal volume on Permission.REVEAL_VOLUME_READ, which exists and guards no route today. Also add a cheap head-anchor-only chain status endpoint so the audit tile can show a passive light without running the 50 000-row HMAC walk.

- 15. OPERATOR-INPUT STORE — new table + step-up-gated write route + permission + audit action, for the vendor invoice total (card 21) and the vendor tier cap (card 32). Neither has anywhere to live: there is no invoices table, no such column on any model, and AdminSettings is frozen at boot with no override layer. This is a migration plus a governed write, not a query — scope it as such and ship the tiles in their 'not recorded' state until it lands.

- 16. SCHEMA ASKS, worth raising together because each one turns an inference into a fact: briefs.lyrics_source (enum) or is_nameless (bool) — makes BYO share and nameless adoption exact and purge-proof instead of a NULL-pattern inference one refactor away from inverting; orders.authorized_at — the only way to measure confirm→deliver latency against NFR-6 rather than wizard-inclusive latency; orders.failed_at — there is no failure timestamp at all, so no true finished-in-window success rate is computable; an order_events transition table (closed enum action + actor id, NO free-text actor field, following admin_audit_log) — this is the prerequisite that turns the survivor funnel into a real funnel and flips is_state_transition_log off its hardcoded False; and a daily snapshot table for lyric_budgets and last_seen_at, both of which are overwritten in place and can never be back-filled into a trend.

---

## Open questions

Decisions that need a human. Each one changes what the dashboard says.

- THE SIX-CHART CAP vs A REAL DASHBOARD. lieflat §1.2 caps a page at six charts and I resolved it by making the seven sections real tabs, each its own page with its own template allocation. That is compliant, but it means an operator cannot see money and pipeline health on one screen. Is the tabbed resolution acceptable, or should the fold instead be a hand-picked cross-section (three fire tiles + cost-per-song + vendor error rate + retention backlog) with the sections behind it? I recommend the tabs, because the fold as specified already answers all four panic questions in its first two rows.

- WHICH SUCCESS RATE IS THE HERO. Card 1 measures 'orders OPENED in the last 24h, bucketed by their current state', because the window is on orders.created_at and there is no failed_at column. A true finished-in-window rate is not computable today. Do we ship the honest-but-odd label, or land orders.failed_at first and ship the tile people actually expect? Everything else on the page reconciles to the created_at cohort, so changing it later means changing every denominator.

- THE PRICE. config.py ships 7 000 UZS; every planning document assumes $5.90. Card 14 shows the reconciliation rather than a margin, because the price is not on AdminSettings and the FX rate exists nowhere at all. Is 7 000 UZS the price actually charged today, and who owns the FX figure — an operator input, a pinned monthly rate, or a live feed we do not have?

- GREEN AS BRAND vs GREEN AS HEALTH. I have reserved #75FC96 strictly for 'the subject of this tile' and encoded health by position against a drawn threshold plus a text verdict. This is the correct reading of the kit (its Primary IS its Success ramp), but it means a healthy dashboard is not a green dashboard. Confirm that is the intended feel before it is built.

- REVEAL VOLUME'S AUDIENCE. Card 59 is gated on Permission.REVEAL_VOLUME_READ (admin + owner) and HIDDEN for viewer and support, so a support operator cannot infer an admin's activity from a greyed card. That also means the person most likely to be revealing data cannot see their own budget consumption. Should support see their OWN row only, or nothing?

- POLLING BUDGET. The pulse is unwindowed and grows with lifetime order count forever; /readyz touches Redis on every call; retention runs twelve unbounded COUNTs; state-counts keeps a briefs outer join even with no search term. My proposed cadences are: pulse 5s (one shared request), fire aggregates 30s, retention and vendors 60s, everything cohort-shaped nightly, and balance drift + audit chain on-demand only. Is a 5s tick still wanted once the dashboard is not the Live screen?

- IS THE LIVE SCREEN RETIRED. This dashboard subsumes what the Live screen fetches and then draws the chart Live never drew. Does Live survive as a dedicated incident view, or does it fold in? If it survives, the two must not both poll the unwindowed pulse.

- TIER-3 METRICS DELIBERATELY OFF-SCREEN, listed so the omission is a decision rather than an oversight: match-confidence bucket drill-through, candidate-rank as its own tile (it is a margin table on card 43), audio-quality outliers as a chart (F15 Tick Box was budgeted and cut — it needs the ix_assets_created_at migration first), LLM parse-retry rate as its own tile (it is a caption on the vendors tab), vendor HTTP status as its own tile (it is a ring encoding on card 34), erased-ledger-rows as its own tile (a caption on card 23), and admin roster / session posture / asset footprint / dedup (all footer rows on card 60). Say if any of these should be promoted.

- THE KILLED SIX. name-verification-failure-codes, contribution-margin-per-song, music-billing-granularity, dictionary-coverage, order-transition-funnel and tg-file-id-reuse are absent by construction, and three of them fail in the same believable direction: they would render an empty or zero chart that reads as 'nothing is wrong' when it means 'this deployment cannot answer'. If any is wanted anyway, it needs its own explicit 'not instrumented' state rather than a percentage — a 0% tg-file-id-reuse tile reads as 'we burn egress on every re-send' when it actually means the column has no writer.

- OFFLINE / ARTIFACT DELIVERY. Every chart I selected except G18 and G10 is pure SVG and runs with no network. If this is ever published as an Artifact rather than served by the SPA, the two Glance charts pull ECharts from cdn.jsdelivr.net/npm/ (allowed) but nothing else on the page may fetch anything. Confirm the delivery target before the two ECharts cards are built, or swap them for pure-SVG substitutes and lose the counter animation.

---

## Design decisions carried into the mockup

### Colour

LOCK ONE CUSTOM SYSTEM: "PlanIQ Ink" — mono-plus-accent logic, PlanIQ values. No preset, no mixing, for the whole deliverable including every tab.

WHY A CUSTOM PALETTE IS THE LEGAL CHOICE. lieflat §6.5 permits a custom palette only when the user supplies actual hex values, brand colours or "match this reference". The PlanIQ mockup is exactly that: a measured brand spec with five bound variables (collection 1:4) that the shipped screens actually paint. Picking porcelain, palm or wire instead would produce charts that look pasted into the mockup — the stated failure mode.

WHY MONO-PLUS-ACCENT LOGIC (wire's logic, none of wire's values). PlanIQ has exactly one chroma. Its whole visual argument is greyscale structure with a single green protagonist — 85 uses of #000000 and 43 of #75FC96 against zero other hues on the dashboard frame. That is the mono+accent contract verbatim: lightness carries the data, one accent marks one protagonist. Borrowing wire's #F5572F or palm's amber would be preset-mixing, which is an automatic redo.

ROLES (define the logic before the values; every colour is pulled from a role, never scattered as hex):
  BG    #F6F6F6      TXT #0D0D12      MUT #666D80      FAINT #8D8D8D
  GRID  rgba(0,0,0,.06) 1px dashed 2 2
  CARD  #FFFFFF
  DATA ladder, derived by mixing TXT toward BG (never a new hue):
        D0 #0D0D12 · D1 #3A3B3F · D2 #5B5A64 · D3 #8D8D8D · D4 #B4B4B7 · D5 #D3D3D4 · D6 #E8E8E8
        Most important series is the blackest. Assignment follows importance down the ladder, never data order.
  HERO  #75FC96 — exactly one element per chart (the current period, the top rank, the tile's own subject). "A second green means there is no protagonist."
  HERO-TEXT #218C3B — because #75FC96 fails contrast as text or as a hairline; the accent is for fills and 2px+ marks only.
  CAT2  #8CB4B9 — used ONLY where two simultaneous series are unavoidable (delivered vs failed, minted vs burned). Above two series, fall back to the ladder.
  ALARM #E93544 (the kit's own red/600 primitive, part of the brand file, not a preset import) — reserved for a crossed threshold and nothing else, and always paired with a text label, because colour may never be the only cue.

THE TRAP THIS AVOIDS, EXPLICITLY. In this kit Primary IS Success — #75FC96 sits inside the Primary ramp and there is a second, darker green Success ramp. On a pipeline-health dashboard, using green for both "brand" and "healthy" makes status unreadable. So: green never encodes health. Health is encoded by position against a drawn threshold line plus a text verdict. Green only ever means "this is the mark the tile is about".

MECHANICS (non-optional the moment a chart leaves pure greyscale): INK_BOOST strokeScale 1.8 — 0.5px hairlines vanish once they stop being black — and opacityFloor 0.85, with the single documented exemption for F10 Dot Heat (card 44). Every chart carries ≥3 tonal steps or colour positions; a chart that would use only one or two colours falls back to greyscale. One HERO per chart. No dark cards anywhere: lieflat budgets one dark card per four and PlanIQ has exactly one inverted surface in its whole system — a dark card in a 6-card ops tab reads as an error state, not as emphasis.

SEMANTIC ENCODING SENTENCE, to be printed in the deliverable and in every `.src` line: "Lightness is volume; the green mark is the subject of the tile; red appears only where a stated threshold is crossed."

NULL IS A THIRD STATE AND HAS ITS OWN VISUAL. A null rate, a null cost, a null latency renders as D5 #D3D3D4 diagonal hatching plus the literal string "not measured" — never as a zero-height bar, never as $0.00, never as an empty array. This is a colour rule, not a copy rule, because the whole codebase (vendor_usage's COALESCE ban, _as_int, _as_rounded_int, LatencySummary) is built to preserve that distinction and a chart is the last place it can be destroyed.

### Layout

```
PAGE: 1440×1024 minimum, #F6F6F6, 24px side margins, 1392px content band, 10px gutter.

CHROME (y=24, h=54, all r=70, fill #FFFFFF) — copied from PlanIQ 0:7754 exactly:
- Nav pill x=24 w=714: logo lockup x=36 y=31 159×40; nav row y=34 h=34 with the active section pill 91×34 fill #75FC96 r=26 (12/500 #000, 16px inset). Items: Fire · Money · Credits · Vendors · The Name · Funnel · Privacy. Sections ARE the tabs — this is how the lieflat 6-chart-per-page cap is satisfied honestly rather than quietly broken.
- Search pill x=895 w=197 → repurposed as the global order/correlation-ID jump box. Placeholder "correlation id or order id" 12/500 rgba(0,0,0,.40). NEVER a name search (deliberate product refusal).
- Settings circle x=1100 54×54.
- Profile pill x=1162 w=254, right edge 1416. PII CHANGE FROM MOCKUP: render admin username 16/600 + role 12/400 (#666D80). Do NOT render the email address the mockup shows in plaintext.
- Gap 738→895 is the flex space: justify-content:space-between, nav group left, search/settings/profile group right.

GREETING BAND y=114 h=93:
- Left x=24 w=490: eyebrow 22/400 #5B5A64 "Tashkent 08:04 · data in UTC" over hero 42/700 #000 "Good morning, {admin.username}". Vertical stack, gap 10.25.
- Right x=1020 w=396, bottom-aligned to y=207: TimeRangePicker as a 108×32 r30 filter chip ("Last 24 hours"), an 88×32 chip showing the quantised window end (WINDOW_QUANTUM_MS), and a LIVE pill (h32 r30, #75FC96 12% ground, 8px #0AB552 dot, "LIVE · 5s"). One shared queryKeys.ops.pulse() request per tick feeds this pill AND card 2 — never two unwindowed callers.

SECTION TOOLBAR y=249 1392×54 r15 #FFFFFF: left = the section title 16/600 and its one-line purpose 12/400 #666D80; right = per-section filter chips (vendor, language, plan). Content starts y=323.

TEMPLATE A — sections 1–3 (rail layout, PlanIQ 0:7754 geometry shifted +74px):
  main zone 986 (x=24→1010) + 10 + rail 396 (x=1020→1416)
  Row A  y=323 h=143 : 322 | 322 | 322   (x = 24 / 356 / 688)
  Row B  y=476 h=301 : left 476 (x=24) | right column 500 (x=510) subdivided 500×164 at y=476 and, at y=650 h=127, either 500×127 or 245+10+245 (x=510 / 765)
  Row C  y=787 h=269 : 663 (x=24) | 313 (x=697)
  Rail   x=1020: 396×355 at y=323 (ends 678) | 10 | 396×368 at y=688 (ends 1056)
  Rail bottom and Row C bottom both land at 1056; page height 1098 with 42px slack.

TEMPLATE B — sections 4–7 (no rail; wide charts need the full band):
  Row 1 y=323 h=143 : 3 × 457.33 (x = 24 / 491.33 / 958.67)
  Row 2 y=476 h=301 : 691 | 691 (x = 24 / 725)
  Row 3 y=787 h=269 : 1392 full width (x=24) — this is the `.card.wide` slot; every 840-viewBox lieflat band chart lives here and nowhere else.
  Page height 1098.

CAPABILITY FOOTER (both templates, y=1066, 1392×32, no card chrome): a single hairline strip of 8 pills from GET /api/ops/capabilities — cost telemetry, latency telemetry, storage keys, chat capture, payment ledger, state transition log, vendor usage, vendor cost. False pills render #8D8D8D with a strikethrough label, never red (an absence is not an error). Cached per deploy. Per-tile "not instrumented" states branch on THIS payload, never on an empty array.

FOLD: the browser fold at 1024 sits inside Row B. Rows A and B therefore carry every tier-1 alarm; Row C and the rail bottom are context. The one tier-1 tile deliberately below the fold is order-state-distribution (card 8) — it is a book-shape reading, not an alarm, and its 24h edge is already on card 1.

RESPONSIVE
- ≥1440: as specified.
- 1200–1439: band = 100vw − 48; Template A rail drops to 320 and the main zone flexes; Template B row-2 halves flex 1:1. Row 3 stays full width.
- 1024–1199: rail moves BELOW the main zone as a full-width row (two 691 cards). Template B row 1 becomes 2×2.
- <1024: single column, 100% width cards, min 320. Every chart re-authors its viewBox to the new aspect and drops mark count (≤5 bars, ≤6 rows, ≤30 points) — it does not scale down, because a 400×320 viewBox squeezed into 340px puts every label under the 6.5px floor.
- Wide content (the two table cards) scrolls inside its own overflow-x:auto container; the body never scrolls horizontally.

DRILL-THROUGH: every card header's 38×38 circle button is a route, not a menu — Fire cards → /orders with the filter pre-applied, Money/Vendors → /vendors, Credits → /users/{id}/credits (never a list), Name → /generations, Privacy → /retention or /audit. The dashboard is all headlines; the six detail screens stay the article.
```

### Tokens

```
PLANIQ, DISTILLED FOR AN IMPLEMENTER. Source of truth is the shipped mockup frame 0:7754 ("Dashboard", Light Version), NOT the Style Guide page — the Style Guide documents a different system (Outfit/Inter/Urbanist, #E4E7EC hairlines, 10-step ramps) that the product frames never use. Build on variable collection 1:4 + Manrope.

COLOR TOKENS (hex, all read from node fills)
--bg:            #F6F6F6   page ground, chip bg, icon-circle bg, chart track, inactive row
--card:          #FFFFFF   every card surface, nav pill, search pill
--stroke:        #E8E8E8   hairline / bar track
--divider:       #ECECEC
--ink-900:       #0D0D12   card titles (16/600)
--ink-800:       #000000   KPI values, hero, table cells
--ink-700:       #161618   list-row titles
--ink-500:       #5B5A64   eyebrow
--ink-400:       #666D80   KPI labels, captions
--ink-300:       #8D8D8D   table column headers, row subtitles
--ink-a50:       rgba(0,0,0,.50)  legend labels
--ink-a40:       rgba(0,0,0,.40)  placeholders, @handles
--gridline:      rgba(0,0,0,.06)  1px dashed 2 2
--accent:        #75FC96   THE only chroma. Active nav pill, CTA, one hero mark per chart
--accent-70:     rgba(117,252,150,.70)
--accent-12:     rgba(117,252,150,.12)  delta-chip ground
--accent-deep:   #218C3B   positive-delta TEXT (accent is unreadable as text)
--accent-2:      #8CB4B9   the one desaturated blue-grey, second series only
--alarm:         #E93544   from the kit's own red/600 primitive; threshold breach only
--online:        #0AB552

TYPE — Manrope, one family, default line-height 136.6% of size
hero        42/700  lh 57.372  ls -2.52  #000000
kpi-value   42/700  lh 57.372  ls -2.52  #000000
stat-md     32/700  lh 43.712  ls -1.92  #000000
eyebrow     22/400  lh 33      ls -0.44  #5B5A64
card-title  16/600  lh 21.856  ls -0.32  #0D0D12   (EVERY card header)
kpi-label   16/400  lh 24      ls -0.48  #666D80
col-header  16/400  lh 21.856  ls -0.64  #8D8D8D
axis-x      14/500  lh 19.124  ls -0.28  rgba(0,0,0,.60)
title-sm    14/500  lh 19.124  ls -0.28  #0D0D12   (sub-card titles)
nav/chip    12/500  lh 16.392  ls -0.24..-0.36
body-sm     12/400  lh 16.392  #000 / #666D80
meta        10/400-600 lh 13.66
micro        8/500-600 lh 10.928  (delta chips, status labels)
SVG FLOOR: 6.5px in a half-width card, 5.5px full-width (lieflat §2). At 322×143 that means labels move to hover or the subtitle — never shrink.

RADII
card 15 | pill 70 (top-bar) | nav-active 26 | filter-chip 30 | delta-chip 40 | list-row 12 | inner-tile 8 | icon-tile 16 | rank-badge 11 | chip-small 6/4 | micro-bar 2 | tick 1 | deck-card 29.21

SHADOWS — none on any card. Separation is white-on-#F6F6F6, full stop.
Only exceptions: active list row 0 1px 5px rgba(0,0,0,.20) + 1px inside stroke rgba(0,0,0,.20); inactive row 1px inside stroke rgba(0,0,0,.02); toolbar chip 0 0 4px rgba(0,0,0,.06).
Cards have NO border. (Style-guide #E4E7EC hairline belongs to the poster artboards, not the product.)

SPACING / GRID
Frame 1440×1024. Side margins 24/24 → content band 1392. Gutter 10px, horizontal AND vertical, everywhere. Card padding 16 all sides. Card header = a (w−32)-wide space-between row at (16,16): title left, and right either a 38×38 circle button (fill #F6F6F6, 20px glyph inset 9,9) or a filter chip (h32, r30, #F6F6F6, 12/500 label + 24×24 white circle chevron, gap 8, inset 16).
Common inner metrics: 38×38 header action; 32×32 icon tile; 42×42 chrome avatar / 32×32 table avatar; 8px legend dot; legend gap 12, dot-to-label 6.
Vertical rhythm: chrome→greeting 36, greeting→content 42, card→card 10, bottom slack 42.
There is NO uniform N-column module (322/476/500/663/313/396 do not reconcile to 12 cols). Use explicit grid-template-columns per row.
```
