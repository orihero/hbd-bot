# The Billing Rail Board — the admin panel's view of the Payme rail

**Specification. Cite it by section: `BILLING_RAIL_BOARD §4.5`, never by path** — a section
number survives this file moving and a path does not, which is the rule
[`../README.md`](../README.md) states and which a previous reorganisation of `docs/` had to
enforce across twenty-two citations in `src/`, `tests/` and `migrations/`.

Companion documents. [`PAYME_INTEGRATION.md`](PAYME_INTEGRATION.md) is the rail itself — the
two seams (§1), both state machines (§2), the one commit (§3), the five replay guarantees
(§5), the reconciliation identity (§8.5). This document does not restate any of that; it
specifies the **screen** that reads it. [`../decisions/DECISIONS.md`](../decisions/DECISIONS.md)
**D11** is why the rail exists, **D14** is why the panel may find and may nudge but may not
mint, and **D15** is why this section is built in `admin-dashboard` and not in `admin-ui`.
[`../deployment/09-payme-go-live.md`](../deployment/09-payme-go-live.md) §11 is the operator's
half: which of the CLI's commands the console now covers and which it deliberately does not. The
CLI itself has **nine** subcommands, and its refusals and exit codes are inventoried in
`../deployment/08-payme.md` §12 — worth reading before assuming a button is missing here.

> **STATUS, 2026-09-10 — this section has no data and will not have any for weeks, and that is
> the design constraint it was drawn around, not an embarrassment to be hidden.** The merchant
> id on this deployment is literally the string `placeholder`, the gateway boots with
> `is_sandbox` true, `CHECKOUT_PROVIDER` is unset so the bot builds `StubCheckoutProvider`, and
> all three rail tables are empty. §8 is what the board says in that state, and it is the part
> of this specification most likely to be read first and dismissed as filler. It is not filler:
> a screen whose every number is `0` is a screen whose every number means two things unless
> somebody decided otherwise in advance, and §8 is that decision.

> **STATUS, 2026-09-11 — "no data for weeks" lasted one afternoon. Two of the four facts above
> are now false, and the empty-state design is what has to be re-read rather than the status.**
>
> * **The merchant id is no longer `placeholder`.** `[HOST 2026-09-11]` the gateway's boot line
>   reads `merchant_id: 6aa24fd9ee30563de3a1ac22` — a real **sandbox** cashbox, installed
>   2026-09-10, public by the same argument that puts it in a log at INFO.
> * **The three rail tables are no longer empty.** `[HOST 2026-09-11]`: `payment_intents` 7,
>   `payme_transactions` 3, `payme_rpc_log` 53 — plus `topup_purchases` 6 and `credit_ledger` 18
>   downstream of them. A settlement rehearsal ran on 2026-09-10 at 13:30 +05
>   (`../deployment/09-payme-go-live.md` §4.0) and every row it wrote carries `is_sandbox = true`.
> * **Unchanged:** `is_sandbox` is still `true` and `CHECKOUT_PROVIDER` is still unset, so the bot
>   still builds `StubCheckoutProvider` and **no customer has ever been charged**.
>
> **So the screen's data is real, none of it is revenue, and the distinction between those two
> sentences is now the whole job of this specification.** Seven intents that look like payments and
> are rehearsals; three verdict states that were drawn for an empty deployment and are now being
> asked about a populated one; a `never_settled` card that has flipped. §8.1 and §8.2 carry the
> corrections, and both are kept rather than rewritten, because the reasoning in them is what the
> **next** empty screen in this product should inherit.

---

> **AMENDMENT, 2026-09-10 — the board is gone from the console; the server is unchanged.**
> `/billing` is now the **payments list** and nothing else: a filter panel (opened window,
> state, product, settled-by, attention population, sandbox), the reference lookup inline in
> its toolbar, the pause switch beside them, and the table. The five bands this document
> specifies — the status header, the settlement card, the attention chips, the funnel and the
> fault fold — were removed on the operator's instruction that the screen carried too much
> prose for a rail that has never sold. Every number they printed survives as a filter over
> the same rows or as a column on one.
>
> What that changes here: **§5** (the settlement identity), **§8.1** (what the board says on
> an empty deployment), **§8.2** (the `railVerdict` ladder) and the board half of **§2.1** describe
> a screen that no longer exists, and are kept as the record of why those numbers were computed the
> way they were.
>
> **Addendum, 2026-09-11: "no longer exists" is not the same as "is not computed", and the two
> halves differ.** `[TREE 2026-09-11]` §5's machinery is all still in the tree and still answers —
> `settlement_counts`, the row probes, and the `never_settled` verdict are in
> `src/bayram/admin/schemas/billing.py` and `src/bayram/admin/routers/billing.py`; they simply have
> no caller. §8.2's `railVerdict` ladder, by contrast, **was never implemented at all**: grep the
> tree for `railVerdict`, `armed_but_idle` or `never_armed` and there is nothing. So §5 is a live
> server contract with no client, and §8.2 is a design that did not ship. Treat them differently
> when either band is rebuilt.
> **§3's route table still holds** — all twelve routes are mounted and unchanged, and
> `/api/metrics/rail/settlement`, `/funnel`, `/attention` and `/calls-by-code` simply have no
> caller in the console today. §4 (the dossier), §6 (privacy), §7 (retention) and §9 (the refusals) are
> untouched.

---

## 1. What this section is, and what it deliberately is not

**It is about the rail and about individual payments.** Is the machine armed? Has Payme ever
called us? Did *this* customer's money turn into a song, and if not, where did the chain stop?
Those are the three questions, in that order — the board answers the first, the intents list
narrows the second, the dossier answers the third.

**It publishes no revenue total, and this is the single most important boundary in the
document.** `src/bayram/admin/routers/dashboard.py::finance` already concatenates
`plan_revenue_totals(...) + topup_revenue_totals(...)` into the dashboard's finance card. A
second money rollup, computed from a different table by a different query on a different
screen, will eventually disagree with the first — not because either is wrong, but because
they window differently, or one excludes sandbox rows and the other does not, or one is
grouped by provider and the other saturates a count. The first operator to notice the two
screens differ files it as a bug, and the fix is always to make one of them lie. So: **nothing
in this section sums `amount_minor` across intents.** An amount appears beside the payment it
belongs to and nowhere else.

The rejected alternative was a `sandbox_contamination` figure — receipts joined back to
`payment_intents.is_sandbox` so a certification week could be subtracted from recorded revenue.
It is a real problem (§2.4) and it was cut anyway, because it is a revenue-shaped number that
can disagree with the finance card, it is zero for months, and its existence invites somebody
to "fix" the finance card to match it. The honest and cheaper answer is to surface `isSandbox`
on every row and on the header, so a certification week is *visible* where it happened rather
than *netted out* somewhere else.

Also deliberately absent, each for a reason recorded in D14 or below: a force-settle button, a
"run reconcile" button, expire/release/hold/claim/cancel/refund buttons, a green/red gateway
health dot, a name or free-text search over buyers, a sort control, a CSV export, and any
alerting. **D14** carries the arguments; the short version is that the panel may find and may
nudge, and may not mint.

---

## 2. The three switches, and which of them this process can see

The rail's behaviour is governed by three independent settings. **The admin process can read
exactly one of them.** Every design decision on the header follows from that sentence.

| Switch | Lives in | Asks | Readable by the admin API? |
| --- | --- | --- | --- |
| `CHECKOUT_PROVIDER` | `bayram.config.Settings`, loaded from the **bot's** dotenv | Does the product sell anything for real money? `stub` builds `StubCheckoutProvider`; `payme` builds the real rail | **No.** A different file from the one this process loads |
| `PAYME_ENABLED` | `bayram.payme.settings.PaymeSettings`, loaded from `/etc/bayram/payme.env` | May the gateway daemon serve Payme's inbound calls at all? | **No.** Not on `AdminSettings` in any form |
| the pause key | Redis, `bayram:payme:paused`, written through `bayram.payme.pause.set_paused` by **two** writers — the operator CLI and this panel (§2.3) | Should the bot stop *quoting* new checkouts? | **Yes** — read and written |

`PAYME_INTEGRATION` §8.6.3 states the first two are two questions with two blast radii and that
conflating them is the most likely way to turn the rail on by accident. The panel inherits that
hazard and must not become a fourth way to trip over it.

> **THE TWO NAMES IN THAT TABLE DO NOT MATCH THE RUNNING HOST, AND SINCE 2026-09-10 ONE OF THEM
> RESOLVES TO THE WRONG FILE RATHER THAN TO NOTHING.** This document is written in the
> repository's post-rename spellings, like every specification here, and `aizu` is pre-rename. So:
>
> * **the dotenv path.** The gateway reads `/etc/hbd/payme.env` `[HOST 2026-09-11]`. A
>   `/etc/bayram/payme.env` also exists on that host now — 361 B, `0640 root:hbd`, written by a
>   rename cutover that aborted before installing a single unit — **and nothing reads it.** An edit
>   there changes nothing, raises nothing and logs nothing. Check the gateway's `payme.boot.ok`
>   line for `env_file` before believing any edit took.
> * **the Redis key.** The running wheel writes `hbd:payme:paused`; `bayram:payme:paused` is what
>   the staged wheel and this repository write. `[HOST 2026-09-11]` **neither key is set** — Redis
>   holds five keys and neither spelling is among them.
>
> [`../deployment/10-rename-cutover.md`](../deployment/10-rename-cutover.md) §3 is the inventory of
> everything now duplicated under two names, and `09-payme-go-live.md` §11.5 is what the cutover
> does to whoever is looking at this screen when it happens.

### 2.1 Measured, not declared

Provider, merchant id and sandbox flag are **read off the newest `payment_intents` row**
(`latest_checkout_seen`), never off configuration.

The rejected alternative was a `checkout_provider` field on `AdminSettings`. It would read
`.env.admin` — a *different file* from the one the bot loads — and would therefore render an
answer with total confidence that is about a process nobody asked about. Worse, it fails in the
direction that matters: the day somebody flips the bot to `payme` without touching the admin
dotenv, the panel says `stub` while customers are being charged. A row that the bot actually
wrote cannot be wrong in that direction; it can only be *stale*, which is why `seenAt` is
rendered beside it.

Two consequences the screen states in copy rather than hiding:

* **There is no `gatewayEnabled` field on the wire, not even a nullable one.** A field that is
  always `null` teaches the next reader that it might one day be populated. Its absence, plus
  the header line "Gateway daemon: not readable from this process", teaches the truth. The
  substitute evidence is the line below it — *Last heard from Payme* — which is a measurement
  rather than a claim.
* **There is no green/red health dot.** Two of the three switches are unobservable and the
  admin process is structurally forbidden to make an outbound call (`app.py`'s
  `derive_forbidden_env_vars` refuses to boot in prod if `BAYRAM_PAYME_MERCHANT_KEY` is
  reachable; `dashboard.py` restates twice that no outbound call is made from this process). A
  dot would be a guess wearing the costume of a measurement.

### 2.2 `isPaused` is a boolean, and it is deliberately not a tri-state

Both design proposals wanted `boolean | null`, with `null` meaning "Redis did not answer".
Rejected. `bayram.payme.pause.is_paused` never raises and answers `False` when Redis is
unreachable, **because that is what the bot's own checkout path does** — the module argues the
trade at length: an unreachable Redis silently stopping all revenue is a far worse outage than
a paused rail briefly taking a payment an operator meant to defer.

A panel that reported UNKNOWN would be reporting a distinction the runtime does not make, from
a second reader that disagrees with the one the bot consults. That is two answers to "is the
rail paused", which is the exact defect the one-mechanism rule exists to prevent. **The panel
calls the same `is_paused` and reports what the bot would see**, with the module's own two
caveats rendered permanently beside the switch:

* an eviction, a `FLUSHDB` or a Redis restart with no persistence clears the key silently;
* a Redis that cannot be reached reads as **open**, in the panel and in the bot alike.

`pause.py`'s own docstring says this switch **is not a security control and must never be
documented, tested or relied upon as one.** That sentence is why pause and resume carry no
step-up (**D14**).

**One mechanical fact about the key that the panel has to get right and could easily get wrong:
resuming is a `DELETE`, not a falsy write.** Presence is the signal. `PAUSED_VALUE` is `"1"`, and
`_OPEN_VALUES` — `""`, `"0"`, `"false"`, `"no"`, `"off"` — are all read as **open**, deliberately, so
that somebody hand-setting the key to `0` does not silently pause the rail, which is the opposite of
what they meant. Two consequences for this screen: the resume button must go through `set_paused`
and never write a value of its own, and **a header that reports "paused" is reporting the
key's presence** — which is exactly the state a Redis eviction removes with nothing to say about
it (§2.2's first caveat, and it is the same fact from the storage side).

### 2.3 The write may not guess

The asymmetry is preserved in `src/bayram/admin/rail_switch.py`, a ~50-line seam that exists
because `set_paused` *raises* `StorageError` on a failed write and handlers in this package
never write `try`/`except`. The read may guess and answers `False`; the write may not, so a
failed pause is a 503 and never a silent success. The response then **re-reads the key** rather
than echoing the request, so an operator sees the switch as stored and not as asked for.

### 2.4 Sandbox money is not separable on the receipt

`payment_intents.is_sandbox` exists precisely so rehearsal rows are excludable. But
`topup_purchases` and `plan_purchases` have **no `is_sandbox` column**, so any revenue figure
that must exclude a certification run can only do so by joining back to the intent on
`idempotency_key`. The existing finance card does not do this. Once the rail is live, a
certification week will land in recorded revenue unless somebody handles it.

This section's answer is to make it **visible, not netted**: `isSandbox` is a column on every
intent row and a word on the header. Fixing the finance card is a separate change with its own
argument; pretending this section fixed it would be worse than the current state, because it
would leave two numbers that disagree with no record of which one was meant.

---

## 3. The route table — twelve routes, four routers

The guard is per-router, so a second permission cell means a second `build_*_router()` factory
and a second `include_router` line. All paths are absolute `Final` constants derived from one
another; nothing uses `prefix=`. Every one of the twelve is a line in
`tests/test_admin/test_routes_enumeration.py::MOUNTED_ROUTES`, which is asserted equal to the
served set in **both** directions.

| Method | Path | Router / permission | Answers |
| --- | --- | --- | --- |
| GET | `/api/ops/rail` | `build_rail_router` · `DASHBOARD_READ` | The header: `checkoutSeen`, `isPaused`, `pauseKey`, `lastInboundCall`, four probes, `asOf` |
| GET | `/api/metrics/rail/settlement` | ″ | The identity, with a server-computed `verdict`. **`?from=` is required** |
| GET | `/api/metrics/rail/funnel` | ″ | Intent states, transaction states, the expired split, `rpcCalls`/`rpcFaults` |
| GET | `/api/metrics/rail/attention` | ″ | The three stuck populations. `?staleAfterHours=` 1..168. **No window** |
| GET | `/api/metrics/rail/calls-by-code` | ″ | Fault clusters by `(method, replyCode)`. `?limit=` 1..50 |
| GET | `/api/billing/calls` | ″ | The inbound RPC journal, keyset-paged |
| GET | `/api/billing/intents` | `build_billing_records_router` · `RECORDS_READ` | The payments list, keyset-paged, with `capabilities` inside the envelope |
| GET | `/api/billing/lookup` | ″ | `?ref=` **or** `?transactionId=` → `{intentId, matchedOn}`, either field nullable |
| GET | `/api/billing/intents/{intent_id}` | ″ | The dossier (§4) |
| POST | `/api/ops/rail/pause` | `build_rail_control_router` · `RAIL_CONTROL` | Writes the Redis key, re-reads it, audits |
| POST | `/api/ops/rail/resume` | ″ | ″ |
| POST | `/api/billing/intents/{intent_id}/notify` | `build_payment_notify_router` · `PAYMENT_NOTIFY` | Re-enqueues the confirmation message |

### 3.1 Why `/api/billing/calls` sits on the aggregate router

It shares a prefix with the identified routes but carries `DASHBOARD_READ`, not `RECORDS_READ`,
because `payme_rpc_log` holds no Telegram id, no request body and no header — and `peerIp` is
Payme's data-centre address rather than a customer's. That absence is the table's design and is
what keeps it off the privacy inventories. `build_audience_lists_router` already uses this
same-prefix-different-guard shape on `/api/metrics/dashboard/*`.

### 3.2 Why the URL key is `{intent_id}` and lookup is a separate route

`test_every_path_parameter_is_typed` asserts every path parameter's annotation is `UUID` or
`int`, so a `{public_ref}: str` route with a `Path(pattern=…)` cannot exist here — a malformed
id must be a 422 from FastAPI rather than a query that runs. But the operator holds a 24-hex
reference read to them over the phone, not a UUID. Hence `/api/billing/lookup?ref=`, whose
whole value is a **discriminated not-found**: a well-formed reference that matches nothing
returns `200` with `{intentId: null, matchedOn: null}`, which is a different screen with a
different remedy from a malformed reference (a 422). "No payment exists under that reference on
this deployment" is an answer; a validation error is not.

There is deliberately **no `idempotencyKey` parameter** on lookup and no `idempotencyKey` field
on any view model — see §6.

### 3.3 Two permissions, neither of them a step-up cell

`RAIL_CONTROL` (`admin`, `owner`) and `PAYMENT_NOTIFY` (`support`, `admin`, `owner`) are plain
`W` cells with matrix rows and **no entry in `STEP_UP_ACTIONS`**. This is asserted by a test
carrying the reason, because the failure mode is invisible: `check_role` holds no subject and
therefore no grant, so any permission that appears in `STEP_UP_ACTIONS` answers
`STEP_UP_REQUIRED` at the router unconditionally — for ever, at OWNER, while looking exactly
correct, because `STEP_UP_REQUIRED` is what the matrix predicts. If a future reviewer decides
pause deserves a step-up, the remedy is to **split** into `RAIL_CONTROL_WRITE` (router) plus
`RAIL_CONTROL` (handler, via `enforce_step_up`) — never to add the existing member to the
mapping.

`PAYMENT_NOTIFY` is its own permission rather than a ride on `RAIL_CONTROL` because SUPPORT is
who takes the "I paid and nothing happened" call, and handing a support agent the switch that
stops the business selling in order to give them the button that re-sends a receipt is a
trade nobody would make if it were written down.

### 3.4 Refusals, not silent coarsening

`?staleAfterHours=0` and `=169` are 422s naming the parameter. `?limit=51` on the fault
clusters is a 422, not a clamp. `/api/metrics/rail/settlement` with no `?from=` is a 422 naming
`from`, because the identity is a statement *about a window* — "all time" is a different and,
on a column that until now had no index, expensive question, and widening it silently is how a
number becomes untrustworthy. `/api/billing/lookup` with neither parameter or with both is a
422 naming both.

---

## 4. The dossier — six panels and a six-step lifeline

`GET /api/billing/intents/{intent_id}` makes six data-layer calls **inside the one request
transaction** `get_db_session` already opens. This reproduces `bayram.payme.cli._dossier`'s
single-read-transaction property, and the reason is in that module's own docstring: an operator
has to trust that the receipt and the transaction were true at the same instant, and six
separate reads during a live settlement would show a performed transaction with no receipt.

The panels, in `cli._render_dossier`'s order, because that ordering is the only existing answer
to "did this customer's money turn into a song?" and it was arrived at by somebody doing the
job:

1. **The lifeline** (§4.1) — first and dominant.
2. **The intent** — `publicRef`, state, product, amount, buyer (masked or *erased*), merchant
   and sandbox, opened / valid-until / settled / notified, and `settleSource`.
3. **Every rail transaction**, oldest-first by `paymeTime`, with `cancelReason` as the bare
   integer plus its protocol name resolved at the presentation edge only.
4. **The receipt** — which table it landed in, its amount and provider, and its `reference`,
   which is what an operator searches for in the Payme cabinet.
5. **The ledger rows** under the same key.
6. **The inbound calls** naming either identifier. Zero rows here is ambiguous and §7 says how
   the screen disambiguates it.

Then the chain-stop panel (§4.5), always rendered, never hidden.

### 4.1 The lifeline: six steps, four states

| Step | Done when |
| --- | --- |
| `opened` | the intent row exists |
| `rail_transaction` | Payme opened at least one transaction against it |
| `performed` | a transaction reached `performed`, or the intent was settled by an operator |
| `receipt` | a row exists under the key in `topup_purchases` or `plan_purchases` |
| `credit_granted` | a `credit_ledger` GRANT exists under the key |
| `customer_told` | `notified_at` is stamped |

The four states are `done`, `pending`, `not_applicable`, `missing`. **The distinction between
`not_applicable` and `missing` is the entire value of this screen over `psql`**, and it is why
the lifeline is computed **server-side**: a plan sale that granted nothing and an erased buyer
who could not be granted anything are both *correct*, and both look exactly like a hole. Two
clients computing this independently would invent a fifth state within a month.

### 4.2 `noteCode` is a slug, not a sentence

Each step may carry a `noteCode` from a **closed** vocabulary. The server never sends English
prose: the deployed console is trilingual (en/ru/uz) with key parity asserted across all three
locale files, so a sentence on the wire is a sentence that cannot be translated.

| `noteCode` | What the English locale renders |
| --- | --- |
| `never_opened` | Payme has never opened a transaction against this intent |
| `awaiting_rail` | a transaction is open and the rail has not performed it yet |
| `buyer_erased` | the buyer was erased between paying and settling; the money moved and there was nobody left to grant to |
| `plan_grants_nothing` | a plan sale grants no credit at purchase — a plan mints songs as they are used |
| `not_settled` | this payment has not settled, so nothing downstream of it has happened |
| `already_told` | the confirmation was sent; re-sending would do nothing |
| `purged` | the record this step would show has aged out of retention (§7) |

### 4.3 What the dossier does not contain

No `idempotencyKey` (§6). No plaintext `telegramUserId` (§6). No force-settle pre-flight
verdict — that idea was cut deliberately, and the argument is this: a verdict computed at
time *T* and acted on at *T*+minutes can be falsified by the five-minute sweep or by a real
inbound `PerformTransaction` in between, and a stale verdict an operator has learned to trust
is worse than no verdict at all. The dossier already shows the intent's current state, its
transactions and its receipt in full, which is the same information without the false currency.

### 4.4 The settle-by-hand card

The dossier renders

```
python -m bayram.payme.cli settle --ref <public_ref> --note '<public_ref>'
```

as **selectable text with a copy control and no submit path** — no button, no form, no
mutation. `settleCommand` is built on the server so the flag spelling lives in one place, and
the string contains nothing but the public ref. The card sits beside the receipt panel's
cabinet reference, so the out-of-band check the command depends on is directly in front of the
operator; it states in copy that the check is a charge in the Payme merchant cabinet, which
this process is structurally forbidden to see. D14 is why it is a copyable command and not a
button.

### 4.5 Where the chain stops

**This subsection is citable on its own because it is the fact most likely to be mistaken for a
missing feature.**

For a **single-song sale** the chain stops at the credit grant, and no query anywhere in this
system can continue it. `credit_accounts.balance` is a single fungible scalar with no lot
structure (`src/bayram/db/plan_sql.py:15`), and `bayram.db.credit_sql.verify_balances` asserts
only `balance == SUM(credit_ledger.delta)`. A `DEBIT` row with reason `ORDER_RENDER` therefore
cannot be attributed to the GRANT that funded it: there is no lot, no FIFO, no link. **Whether
this customer's purchased credit became this customer's song is unanswerable by construction.**
This is the same property that makes a post-perform reversal refuse with `-31007`
(`PAYME_INTEGRATION` §6.1) — a refund of purchase A could debit a credit paid for in purchase
B.

The dossier **states this as a fact in its last panel** rather than leaving a blank. A blank
reads as broken and invites somebody to "fix" it by inventing an attribution, which would be a
guess presented as a record.

For a **plan sale** the chain does continue, and the answer is on the receipt row itself:
`plan_purchases.songs_used` of `songs_included`, with `plan_ends_at`. The panel renders it.

### 4.6 Re-sending the confirmation

The one nudge the panel has. It sends a message the customer was already owed; it writes no
money row and no state a customer can spend, so it carries a mandatory `reasonCode`, a confirm
dialog, an audit row, and no step-up.

Its idempotency is **structural rather than promised**: `payme_notify_job_id(public_ref)` is
deterministic so ARQ collapses a double press (and answers `None`, which *is* the response's
`isReplay` — asking ARQ a second time to find out would race the worker), and
`mark_intent_notified` stamps `notified_at` only `WHERE notified_at IS NULL`, so the enqueue and
the sweep's own backstop cannot both message one person.

Its three refusals are the CLI's, re-checked **server-side before anything is enqueued**,
because the client's disabled button is a courtesy and the server is the authority: the intent
is not `paid`; the buyer has been erased; the confirmation was already sent. Each is a 409
carrying a `refusalCode` the SPA renders as the reason the button is disabled.

**There is no delivery-status view.** `notified_at` says we enqueued and the worker sent.
Whether the customer *saw* it is a Telegram fact this database does not hold, and inventing a
status we cannot know would be worse than the CLI's own honest sentence.

---

## 5. The settlement identity, and the number without which it lies

The card renders **the CLI's identity, not the two-way equality**
`payme_sql.settlement_counts`' docstring asserts:

```
transactionsPerformed + operatorSettlements == receiptsWritten
grantsWritten <= receiptsWritten
```

The fourth number is load-bearing. **A force-settled intent has no performed transaction** —
`claim_intent_for_operator` moves `pending` or `awaiting` straight to `paid` with
`settle_note = 'operator:<ref>'`. Render the two-way form and every use of the recovery button
reads as a defect; an alert that fires on correct operator behaviour is an alert that gets
muted, and then the real mismatch arrives to a muted alert. `operatorSettlements` is counted
separately, from `state='paid' AND settled_at IN window AND settle_note LIKE 'operator:%'`,
using the `OPERATOR_SETTLE_PREFIX` constant promoted into `bayram.payme.ports` — a third
spelling of that string is precisely how the invariant would start reporting every use of the
recovery button as a defect.

`grantsWritten <= receiptsWritten` because grants are the **single-song subset**: a plan sale
writes a receipt and no grant at all. Only `grants > receipts` is strictly impossible, and it is
the only combination the SPA renders as a fault.

The first three numbers come from `payme_sql.settlement_counts` **called unchanged**, not
re-derived. A second copy of that three-subquery statement is exactly how the panel and the
five-minute sweep come to report different numbers about the same window; `PAYME_INTEGRATION`
§8.5 is what the sweep logs, and the board must agree with it by construction.

### 5.1 An all-zero identity is `never_settled`, and explicitly not a pass

`verdict` is computed on the **server**, in the schema layer, by a pure function tested against
every zero and edge combination, in this precedence:

1. `never_settled` — `hasRecordedSettlement` is false. **A zero-equals-zero green tick on a rail
   that has never settled anything is the worst lie this card can tell**, and it is the lie a
   naive implementation ships by default. `09-payme-go-live.md` §0.1 makes the same point about
   the sweep's three zeroes: they prove the sweep is wired and prove nothing about settlement.
2. `grants_over_receipts` — the only strictly impossible combination. Wins over any arithmetic
   mismatch, and is the only fault state.
3. `receipts_short` / `receipts_over` — `performed + operator` against `receipts`.
4. `balanced`.

On `never_settled` the four slots are greyed and one sentence replaces the tick, with the
identity printed beneath as a **legend** — so its shape is learnable before it has data, which
is most of what an operator needs on the day it first has data.

**That day was 2026-09-10.** `hasRecordedSettlement` went true at 13:30 +05 and `never_settled`
stopped applying to this deployment, so precedence 1 falls through and the card answers on the
arithmetic — `1 + 0 == 1`, `balanced` — for any window containing the rehearsal
(`[HOST 2026-09-11]` the worker's own copy of the same identity reported `1, 1, 1`). **Two things
follow that are easy to miss.** The verdict is `balanced` on a rail that has never taken a som, so
`balanced` answers "do these three tables agree", not "is this real money" — the sandbox point of
§8.2. And for a window that does *not* contain the rehearsal, the counts are zero again while
`hasRecordedSettlement` — a **window-ignoring** probe (§8.1) — stays true, so the precedence above
falls past `never_settled` and the card answers **`balanced` with four zeroes**. That is the
intended behaviour rather than a hole: it is the one reading that distinguishes *"nothing in this
window"* from *"nothing, ever"*, which is the whole reason the probe ignores the range.
`PAYME_INTEGRATION` §8.5.1 works the same argument through the sweep's log line, where the same
three zeroes now have three possible causes instead of one.

On `receipts_short` the card names the legitimate causes **before** the alarming one. There are
two of them, and neither is a defect.

* **A buyer erased between paying and settling writes no receipt** (§6.2). The card links
  straight to that population rather than to a support ticket.
* **A hand-settled payment whose rail transaction then arrived is counted twice on the left.**
  `_already_settled_by_this_transaction_or_refuse` answers that late `PerformTransaction` with
  **state 2**: it marks the transaction `performed`, keeps the operator's `settle_note` and
  `settled_at`, and re-runs an insert-or-ignore sale under the same key — so one receipt is
  matched by one `transactionsPerformed` *and* one `operatorSettlements`.

### 5.2 Why the second cause is not netted out

The obvious correction is to stop counting an operator settlement that has a `performed`
transaction. It is **not made**, and the reason is that it moves the false reading rather than
removing it. Our clock and the rail's are not the same clock, so the hand settlement and the
late perform frequently fall in **different windows**; excluding the operator term would then
take it out of the window that holds the receipt and turn a balanced range into
`receipts_over`. A windowed identity cannot net two events that straddle its boundary, and the
exclusion would also hide the population this card exists to surface — a performed transaction
with no receipt is what an **erased buyer** looks like too. Naming the cause in the copy costs
nothing and hides nothing; subtracting it does both. The argument is repeated on
`payment_intents.settlement_snapshot`, which is where somebody will go to "fix" it.

**If this reading becomes common**, the change to make is not a subtraction but a fourth
displayed term — hand settlements whose transaction has since performed — so the operator sees
the double count rather than a number that quietly netted it away. That needs one more scalar
subquery and one more line on the card, and it should wait until force-settle has been used
often enough for anyone to care (D14's trigger is three in one calendar month).

---

## 6. The privacy contract

### 6.1 `idempotencyKey` never reaches the wire

The key is shaped `topup:{tg}:{scope}:{seq}` or `plan:starter:{tg}:{scope}:{seq}`
(`src/bayram/bot/handlers/checkout.py:789`). **It embeds the customer's Telegram id.** That is
precisely why it is never sent to the rail and precisely why `public_ref` — 24 hex characters
carrying nothing about anybody — exists at all.

One design proposal shipped it on the dossier, labelled as the visible join, behind a warning
tooltip. Rejected: a tooltip does not stop a value reaching a DOM node, a screenshot and a
support ticket. It is absent from every view model and from every accepted query parameter, and
a test asserts by introspection that no field name on the detail view contains `idempotency`.
It stays a server-side join key.

### 6.2 Erased buyers, and the state that looks like fraud and is not

`payment_intents.telegram_user_id` is nullable **only because `/forget` anonymises it**. Money
columns survive erasure by design; the buyer does not.

The consequence that must be got right: **a settled intent with no receipt is a legitimate
state.** `src/bayram/db/payme.py::_settle` claims the intent and writes no sale when
`telegram_user_id IS NULL` — the customer erased themselves between paying and settling, the
money moved, there is nobody to grant a credit to, and refusing would leave the rail retrying a
charge it has already taken. It logs at ERROR and surfaces as a performed transaction with no
receipt, which is exactly what trips the identity in §5.

Every screen renders this as **"buyer erased" with the money columns intact** — never as a
discrepancy to be repaired, never as fraud, never as an error, never blank. `isBuyerErased` is
an **explicit boolean on the wire** rather than something the client infers from a null,
because "masked" and "erased" are two different facts and collapsing them is the bug the
existing `PurgedValue` / `MaskedValue` components exist to prevent.

The same rule governs the counts: `paidNeverAnnounced` **excludes** erased buyers, mirroring
`payme_sql.unnotified_settled_intents`. There is nobody to tell and `notified_at` will never be
stamped, so including them would produce a backlog that never drains — and a backlog that never
drains teaches operators to ignore the number.

### 6.3 No plaintext identity, and no second reveal path

The list and the dossier publish `telegramUserIdMasked` plus `isBuyerErased`. **There is no
`telegramUserId` field on this surface at all**, and there is no route that would produce one.
A payer's identity is a `POST /api/reveal` question — one path, one audit shape, one budget. If
a payer phone or a PAN fragment ever lands in these tables it becomes a `RevealField` member
consumed by that existing mechanism, never a new route and never a role branch in a billing
handler.

**Billing is searched by `publicRef` and by Payme transaction id — the two identifiers that are
not people.** Name and free-text search over buyers is a standing, deliberate refusal in this
panel and this section does not reopen it.

### 6.4 What the read routes audit

Nothing extra. The list and the dossier publish a masked buyer only, exactly as `/api/orders`
does, so they write no `admin_audit_log` row and there is no `payment.read` action. Plaintext
still costs a `POST /api/reveal`, with its own row and its own budget. Three audit actions ship
in total, all of them writes: `rail.paused`, `rail.resumed`, `payment.notify`.

`subject_type` for a notify is the one new member of the closed `SUBJECT_TYPES` vocabulary,
`"payment"` — a payment intent is neither an order nor a person nor a config, and the audit
log's value is that "everything done to this payment" is an indexed equality filter on
`(subject_type, subject_id)` rather than a guess about which `action` values to OR together.
Pause and resume use `subject_type="config"` with `subject_id="payme_rail"`, which is honest —
the switch *is* configuration — and keeps the vocabulary change to one member with one user.

`subject_id` for a notify is `str(intent_id)`: a 36-character UUID. This is checked rather than
assumed, because `db/admin/audit.py::_CREDENTIAL_SHAPES` silently blanks any 64-hex run or any
`[A-Za-z0-9_-]{40,}` run in an operator-supplied field, and a Payme idempotency key or a sha256
digest passed as a subject would trip it — leaving the action succeeding with an audit row that
lost its subject.

---

## 7. Retention, orphans, and why "none" needs two renderings

The three tables are on three different clocks and there are **no foreign keys anywhere**:

| Table | Bound |
| --- | --- |
| `payme_transactions` | **none at all** |
| `payment_intents` | terminal *unpaid* rows deleted at `PAYMENT_INTENT_RETENTION_DAYS` = 400. A `paid` intent is never purged |
| `payme_rpc_log` | `PAYME_RPC_LOG_RETENTION_DAYS` = 90 |

So after thirteen months two things are **ordinary**: a transaction whose intent is gone, and an
old paid intent with zero inbound calls beside it.

The second reads identically to the CLI's "Payme has never called this endpoint about it" — the
sentence that means *this intent was settled by hand*. **These are opposite facts with the same
empty list**, and the screen decides between them by the row's own age against the retention
constant: older than 90 days renders as **purged**, newer renders as **never happened**. Getting
this backwards turns a routine old payment into an incident, or an incident into a shrug.

The same distinction governs every empty state on the board, which is §8.

---

## 8. The empty state is the product today

### 8.1 What the board says on 2026-09-10

> **Superseded on 2026-09-11 as a description, kept in full as a specification.** The deployment
> this subsection describes lasted until 13:30 +05 on 2026-09-10. `[HOST 2026-09-11]` the three
> tables hold 7, 3 and 53 rows, the merchant id is a real sandbox cashbox, and every probe below
> now answers **true**. **Nothing in the mechanism is wrong — it is simply no longer the state**,
> and the probes did exactly what they were for: they are the reason nobody has to ask whether
> those counts mean "nothing happened" or "nothing in this window". Read on for the design; read
> §8.2 for what the change revealed about the verdict ladder.
>
> One prediction in it was also settled, and it was wrong in an interesting way — see §8.2.

Three empty tables, `merchant_id` literally `placeholder`, `is_sandbox` true, `CHECKOUT_PROVIDER`
unset. Every count is `0` and every list is empty. **`0` must therefore never have to mean two
things**, and the mechanism is uniform: **every count on every band travels beside a
window-ignoring ROW probe** — `hasOpenedAnyIntent`, `hasRecordedTransaction`,
`hasSettledAnyIntent`, `hasRecordedInboundCall` — measured with the range deliberately ignored.
The list route ships its probes **inside the page envelope** rather than behind a second
request, following `getVendorUsage`'s precedent, so an empty table is legible on first paint.

They are **ROW probes and not `has_table` probes**, and the distinction is load-bearing: the
migration ships *with* this panel, so "the table exists" is true on day one and is not the
question anybody is asking. Related and separate: `db/admin/sql.py::PAYMENTS_TABLE = 'payments'`
names a table that does not exist and never will. **It must not be repointed at these tables**
to light up a capability — it drives `ReadCapabilities.is_payment_ledger`, `TimelineSource.PAYMENTS`
reporting "not enabled here" in `db/admin/orders.py`, and the `OrderPaymentRail` reasoning in
`db/admin/views.py`, and flipping it would silently change what an order timeline claims.

Concretely, today:

* the header reads *no checkout has ever been opened here*, *merchant never recorded*,
  *checkouts open*, *gateway daemon: not readable from this process*, *last heard from Payme:
  none, ever*;
* the settlement card renders `never_settled` — the sentence and the legend, **not** a balanced
  green state;
* the three attention chips render one shared caption, *nothing is stuck; nothing has run*, and
  **not** three green ticks;
* **no chart is drawn anywhere** — an axis with no line reads as a failed fetch, so the probe
  sentence occupies the slot instead;
* a *what would light this up* panel names the three switches of §2 and which of them this
  process can and cannot observe. It disappears the moment `hasOpenedAnyIntent` goes true.

### 8.2 The state that comes next is not "the first payment"

The gateway daemon is **already active** on `127.0.0.1:8091` behind the Cloudflare Tunnel and
publicly reachable, while `CHECKOUT_PROVIDER` is unset. So the first non-empty state this
deployment reaches is **inbound RPC rows with no intents at all** — Payme, or a scanner, or a
certification probe calling an endpoint that answers correctly about a shop that is not open.

The board has a word for it. `railVerdict` is a pure function over the four probes plus
`isPaused`, in this precedence:

| Verdict | When |
| --- | --- |
| `paused` | `isPaused` — wins over everything |
| `never_armed` | neither an intent nor an inbound call has ever been recorded |
| `armed_but_idle` | inbound calls exist, intents do not |
| `quiet` | intents exist, nothing has settled |
| `selling` | otherwise |

**`armed_but_idle` is the state this deployment will be in first and the one a naive
implementation gets wrong** — it renders as its own legible line, not as an error and not as a
mismatch. The words `healthy` and `unhealthy` appear nowhere: two of the three switches are
unobservable (§2), so a binary would be a claim we cannot support.

> **THE PREDICTION IN THIS SUBSECTION DID NOT COME TRUE, AND THE REASON IS WORTH MORE THAN THE
> LADDER.** `armed_but_idle` was never reached. On 2026-09-10 the Gate C rehearsal wrote inbound
> calls, intents, transactions, a receipt and a credit grant **inside the same ninety minutes**, so
> the deployment went from `never_armed` to a settled rail in one step and skipped the state this
> ladder was drawn around. `[HOST 2026-09-11]` all four probes answer true, which puts
> `railVerdict` at **`selling`** — on a deployment where `CHECKOUT_PROVIDER` is unset, no customer
> can be charged, and every row in those tables is a rehearsal stamped `is_sandbox = true`.
>
> **`selling` is the wrong word for that, and the fault is not in the precedence — it is that
> `is_sandbox` appears nowhere in the ladder.** The five verdicts are computed over four row probes
> plus `isPaused`, none of which can tell a rehearsal from a sale. The durable distinction on this
> screen was never *"calls but no intents"* — a state a deployment passes through in an afternoon —
> it is **sandbox versus real**, which is the one thing §1 and §2.4 already insist must be *visible*
> rather than netted out, and which this ladder does not read.
>
> **What to do about it, if the bands are ever rebuilt** (they were removed from the console on
> 2026-09-10 — see the amendment at the head of this document, which is why this is a correction to
> a specification and not a bug in a running screen): keep the precedence, and make the first
> non-`paused` question *"has anything non-sandbox ever happened here"*. A verdict of `selling`
> over exclusively `is_sandbox` rows is the same class of lie as a zero-equals-zero green tick on a
> rail that has never settled — the lie §5.1 exists to prevent — and it arrives by exactly the same
> route: a pure function over probes that do not distinguish the thing the operator cares about.
>
> **`[TREE 2026-09-11]` none of this is in the tree.** `railVerdict`, `armed_but_idle` and
> `never_armed` appear in no Python and no TypeScript file in this repository; the probes
> (`has_opened_any_intent` and its siblings) and the `never_settled` verdict of §5.1 **are** there,
> in `src/bayram/admin/routers/billing.py` and `src/bayram/admin/schemas/billing.py`. So this
> subsection specifies a verdict that was never implemented and then removed with the band it
> belonged to, and the correction above is for whoever builds it next rather than for anybody
> today.

### 8.3 Empty-virgin and empty-filtered are different screens

Every list distinguishes them. No filter active and no rows: *none has ever been opened here*.
Filters active and no rows: name the active filter count and offer Clear. The calls journal's
empty state additionally states that "Payme has never called this endpoint" is also what a
settle case looks like on a live rail — so the sentence is never read as a synonym for "the
gateway is down".

---

## 9. What this section deliberately does not do

Recorded here so nobody rediscovers one of these and files it as a gap. The arguments are in
`DECISIONS.md` **D14**; this is the index.

* **Force-settle as a button.** No route, no permission, no dialog, no queue path. §4.4 renders
  the invocation instead. Five arguments, and the fifth alone is sufficient:
  `claim_intent_for_operator` is the one transition in the entire state machine that
  deliberately **names no holder** and therefore drops the mutex every other move relies on.
* **A force-settle pre-flight verdict.** §4.3.
* **A sandbox-contamination money aggregate.** §1, §2.4.
* **A separate reconciliation screen.** Folded into the board as its second band: nothing else
  tells an operator the invariant tripped, so the invariant belongs where they look.
* **A `run reconcile` button.** `run_payme_sweep` runs it every five minutes on both the healthy
  and the mismatched path, the board recomputes the same numbers from the same query on load,
  and a read must not be a POST — `test_no_get_route_changes_domain_state` enforces that from
  the other side.
* **Expire / release / hold / claim / cancel / refund.** The state machine moves only by
  conditional `UPDATE`s whose rowcount is the lock, and the sweep owns them. `expire_intent`
  deliberately excludes `awaiting` because our clock and the rail's are not the same clock
  (`PAYME_INTEGRATION` §2.3), so a panel that let an operator expire an awaiting intent would
  produce the worst outcome this system has: a customer whose money moved against an order we
  had already refused.
* **Editable amounts, re-pricing, manual receipt entry.** `amount_minor` is stored twice on
  purpose — what we quoted and what they said — and a mismatch is a refusal, never a re-price.
  Nothing in this section writes a money column.
* **A fourth and fifth exception list** (`lapsedPending`, `staleCreatedTransactions`). Those are
  the expiry sweep's and the stale-transaction sweep's *inputs*, not an operator's work queue;
  listing a backlog the system drains on its own teaches operators to ignore the counts that
  matter.
* **A calls-by-bucket sparkline.** A chart with no data for months, needing the whole
  `build_bucket` refusal surface. `rpcCalls`/`rpcFaults` plus `lastInboundCall` already carry the
  signal. **Add it when** the rail has taken real traffic for two weeks and somebody needs to see
  *when* the faults clustered rather than that they did.
* **A payments CSV export.** `EXPORT_AGGREGATE` and `AUDIT_EXPORT` are their own permission cells
  with their own step-ups and their own arguments. A separate proposal, not a checkbox on this
  one.
* **Alerting, paging, a notification rule engine.** The board is a screen an operator opens. The
  sweep already logs the invariant twelve times an hour on both paths; routing that to a pager
  is an ops-infrastructure decision.
* **A `PaymeLedger` extension for diagnostics.** That protocol is held by an internet-facing
  process; putting the six-table join on it would leave it one authentication bug away from a
  stranger. Every new read lives in `src/bayram/db/admin/` behind a permission-guarded router.
* **A second pause mechanism.** One Redis key, one writer function, one reader function. Two
  mechanisms would give two answers.
