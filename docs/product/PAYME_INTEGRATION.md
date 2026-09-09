# Payme Merchant API — the domestic rail

**Specification. Cite it by section: `PAYME_INTEGRATION §3.2`, never by path** — a section
number survives this file moving and a path does not, which is the rule
[`../README.md`](../README.md) states and which a previous reorganisation of `docs/` had to
enforce across twenty-two citations in `src/`, `tests/` and `migrations/`.

Companion documents: [`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11** is the
decision this specifies and **D9** is the decision D11 supersedes;
[`../deployment/08-payme.md`](../deployment/08-payme.md) is how the fourth process is
provisioned, operated and debugged.

> **STATUS — this is built and switched OFF.** `HBD_CHECKOUT_PROVIDER` defaults to `stub` and
> `HBD_PAYME_ENABLED` defaults to `false`, so production behaviour is byte-identical to the
> day before this landed: the stub rail is still constructed at the composition root, still
> wired into `BotDeps`, still under test, and neither new table is read by it. Nothing below
> describes money that has moved. What it describes is a state machine that is green against
> in-memory SQLite, a link builder pinned to Payme's own published golden vector, and an ASGI
> app driven end to end with a placeholder merchant key — because the key is only ever
> compared against itself, an invented one makes a functionally complete gateway.

---

## 1. The two seams, and why `charge` opens no socket

### 1.1 There are two payment seams in this repository and they answer different questions

`hbd.payments.PaymentProvider.authorize` answers *"may this order be rendered?"*. It is the
RENDER gate: called once per order, by the worker, against a credit the customer already
owns. `hbd.checkout.CheckoutProvider.charge` answers *"did money change hands for a
product?"*: called on a button tap, possibly many times per customer, and it has a receipt.
`src/hbd/checkout.py`'s module docstring has argued that separation since before a rail
existed, and it is the reason this integration touches exactly one of the two.

That distinction is also why `HBD_KIT_PRICE_AMOUNT_MINOR` **stays 0 at go-live** (§8.2). The
render gate is quoted an amount for an order that is authorised against a balance; the
checkout is quoted an amount for a credit it is selling. They are two answers to two
questions and only one of them is a price a customer pays. The single flag that moves is
`HBD_CREDITS_ENFORCED`.

### 1.2 The inbound half is not a seam at all — it is a server

Payme's Merchant API is **inbound**. The six methods (`CheckPerformTransaction`,
`CreateTransaction`, `PerformTransaction`, `CancelTransaction`, `CheckTransaction`,
`GetStatement`, plus the archived `ChangePassword`) are things Payme calls against a server
we write. None of them is a thing the bot asks a provider to do. That is the whole reason
`CheckoutProvider` does not grow a second method: there is nothing to add to it.

So the integration is two halves that share a database and share no process:

| Half | Direction | Lives in | Holds |
| --- | --- | --- | --- |
| The **opener** | outbound-shaped, contacts nothing | the bot process, behind `CheckoutProvider.charge` | the PUBLIC merchant id |
| The **gateway** | inbound from the public internet | a fourth process, `hbd-payme.service` | the SECRET merchant key |

The bot never holds the key. The gateway never holds the Telegram token. Neither can do the
other's job, and that is enforced at boot in prod by two mirrored refusals (§8.3).

### 1.3 `charge` opens no socket, and that is the most surprising true claim here

**Payme has no create-payment-link API for the standard checkout.** A checkout link is
*constructed*, not requested: base64 of a `;`-joined `key=value` string, appended to the
checkout host. `PaymeCheckoutProvider.charge` therefore writes one row (the intent), builds
one string, and returns. It owns no `httpx.AsyncClient`, unlike every other vendor adapter in
this tree — and `tests/test_payme/test_provider.py::test_the_payme_provider_holds_no_http_client`
scans the instance's attributes to keep it that way, because "contacts nothing" is precisely
the kind of true claim that rots the first time somebody reaches for httpx inside `charge`.

Three facts about Payme's parser are enforced in the builder rather than trusted:

1. **A `;` anywhere inside a value silently truncates it.** Verified against Payme's own
   unauthenticated sandbox echo. So `public_ref` uses a hex alphabet (§2.1) and a `;` in
   `HBD_PAYME_RETURN_URL` is refused at settings-build time — a truncated deep link fails in a
   way nothing observes.
2. **Percent-encoding is not decoded.** The return URL is passed raw and never quoted.
3. **`ct` (callback timeout) is not sent.** The documentation gives its default as 15 with the
   unit stated as milliseconds, which is not a plausible redirect delay. We do not send a
   parameter whose unit we cannot name.

The golden vector the builder is pinned to is Payme's own published one:
`m=587f72c72cac0d162c722ae2;ac.order_id=197;a=500` →
`https://checkout.paycom.uz/bT01ODdmNzJjNzJjYWMwZDE2MmM3MjJhZTI7YWMub3JkZXJfaWQ9MTk3O2E9NTAw`.

### 1.4 Amounts are tiyin and nothing multiplies by 100

`single_song_price_minor` is `700_000` (`src/hbd/config.py:444`) and 700 000 tiyin is 7 000
soʻm. That integer is already the number Payme is sent, is already what
`PaymentAuthorization.amount_minor` carries, and is compared as an integer against the stored
`payment_intents.amount_minor` at every Payme method. A mismatch is a **refusal** (`-31001`),
never a re-price from `Settings` at Perform time: re-pricing would let a config edit change
the amount of a payment already in flight.
`test_the_amount_is_passed_as_tiyin_unmultiplied` exists to catch the 100× bug specifically.

---

## 2. Two state machines

There are two, they are separate on purpose, and the relationship between them is what makes
merchant-side expiry safe (§2.3).

### 2.1 The intent — ours

One row in `payment_intents` per attempt to buy. It carries `public_ref`, 24 lowercase hex
from `secrets.token_hex(12)`, which is **the only identifier that crosses to Payme**. It is
opaque by construction: no Telegram id, no `;`, no `=`. The bot-minted `idempotency_key`
(`topup:{telegram_user_id}:{scope}:{seq}`) deliberately does NOT cross — it would hand a
customer's Telegram id to a third party and render it in a browser address bar — but it is
the key every money row in this repository already deduplicates on, so it is the one
identifier that crosses the *process* boundary (§3.3).

| State | Means | Set by | Legal successors |
| --- | --- | --- | --- |
| `pending` | a link was issued; no rail-side transaction exists | `open_intent` | `awaiting`, `expired`, `cancelled` |
| `awaiting` | **a live Payme transaction holds this intent** | `hold_intent`, at `CreateTransaction` | `paid`, `pending` |
| `paid` | settled; a receipt and a credit grant exist | `claim_intent`, at `PerformTransaction` | — terminal |
| `cancelled` | abandoned before payment | operator/CLI | — terminal |
| `expired` | `valid_until` passed while still `pending` | `expire_intent` | — terminal |

`awaiting → pending` is the retry path: `release_intent` on a cancel puts the intent back so a
customer whose card declined can press the button again immediately rather than waiting out
twelve hours.

The column is `valid_until` and **not** `*_expires_at`, deliberately.
`tests/test_db/test_audit_retention.py::_clocks_in_the_schema` collects every column whose
name ends in `expires_at` and demands `hbd.db.purge.rows_past_expiry_statements` read it. That
suffix would therefore claim a legal retention schedule this business clock does not have.

### 2.2 The transaction — Payme's

One row in `payme_transactions` per Payme transaction. Payme's `id` is a 24-character Mongo
ObjectId, stored as `String(24)` and **never parsed as a number**. The `transaction` field we
return is OUR uuid as a string; in `GetStatement` rows the two are swapped — `id` is Payme's,
`transaction` is ours.

| Wire state | Stored | Means | Legal transitions |
| --- | --- | --- | --- |
| `1` | `created` | Payme created it; no money moved | `1 → 2`, `1 → -1` |
| `2` | `performed` | paid, receipt and grant written | `2 → -2` (**refused**, §6) |
| `-1` | `cancelled` | cancelled from `created` | — terminal |
| `-2` | `cancelled_after_perform` | reversed after payment | never reached by us (§6) |

Anything else is `-31008`. `cancel_reason` is stored as a **bare integer**, not an enum: it is
Payme's own vocabulary echoed back numerically on the wire, and a VARCHAR mirror would be a
translation table whose only possible failure mode is emitting a value Payme does not
recognise. Reason `4` is timeout, and it is the only one we originate.

The 12-hour window is 43 200 000 ms measured from `payme_transactions.payme_time` — Payme's
own `params.time`, per the specification's wording *«с момента создания транзакции в Payme
Business»*, not from our `created_at`. It is a **setting**, not a constant, so the expiry
branch can be driven in seconds during certification.

### 2.3 Why our clock can never refuse a payment Payme still considers live

This is the property the whole design is arranged around, and it is carried by the intent's
own state rather than by care:

```
expire_intent:  UPDATE payment_intents SET state='expired'
                WHERE id = :id AND state = 'pending' AND valid_until <= :now
```

`CreateTransaction` moves the intent `pending → awaiting` before it answers. So **an intent
under a live transaction is structurally unreachable by the expiry predicate.** Not "the sweep
is careful"; not "the ordering happens to work" — the row is not in the set. The sweep
(§8.4) runs the same predicate as a backstop for rows Payme never mentions again, and nothing's
correctness depends on the sweep running at all.

`tests/test_payme/test_state_machine.py::test_an_intent_holding_a_live_transaction_is_never_expired_by_our_clock`
advances the clock past `valid_until` while the intent is `awaiting`, runs the sweep, and then
performs successfully.

### 2.4 The mutex is `CreateTransaction`, which is before the card is charged

A second Payme transaction for an intent that already has one is refused at
`CreateTransaction`, by `hold_intent` returning rowcount 0. That is deliberately the earliest
possible point: refusing at `PerformTransaction` would refuse a card that has already been
charged, which is a dispute rather than a decline.

---

## 3. The one commit

### 3.1 Exactly-once fulfilment is a commit boundary, not a promise

`PerformTransaction` writes four things — the transaction flip, the intent claim, the receipt
and the credit grant — inside **one** `async with self._sessions.begin()`, from **one** `now`,
under the **same** bot-minted `idempotency_key`. Either all four exist or none do. There is no
compensating write anywhere in this design, because a compensating write is a second commit
and a second commit is a second chance to be interrupted.

The order inside that transaction is fixed and each step is load-bearing:

1. `transaction_by_payme_id` — missing is `-31003`, and **`PerformTransaction` never creates a
   transaction.** No primary source guarantees ordering either way; both official reference
   servers answer `-31003` defensively, and so do we.
2. already `performed` → return the **stored** `perform_time` and state 2, writing nothing.
3. any other state → `-31008`.
4. expired → `mark_cancelled(reason=4)` **and** `release_intent`, **then** raise `-31008`.
   Cancel first, error second; the test asserts the row state after the refusal, not merely
   the returned code.
5. `mark_performed` (the first conditional UPDATE, §3.2).
6. re-read the intent; a `merchant_id` that is not ours → `-31055`, rolling back the flip.
7. `claim_intent` (the second conditional UPDATE, §3.2).
8. `write_single_sale` / `write_plan_sale` — the *same* primitives `SqlPurchaseLedger` uses,
   extracted so there is one copy of "what a paid sale writes" rather than two that drift.
9. commit.

### 3.2 The two conditional UPDATEs, and why the rowcount is the lock

```sql
-- 5. the transaction flip
UPDATE payme_transactions SET state='performed', perform_time=:now
 WHERE id = :id AND state = 'created';

-- 7. the intent claim
UPDATE payment_intents SET state='paid', settled_at=:now, settle_note=:note
 WHERE id = :id AND state = 'awaiting' AND active_transaction_id = :tx;
```

`rowcount == 1` **is** the lock. This is not a new idea in this repository: it is the primitive
`hbd.db.credit_sql.debit_balance` and `hbd.db.plan_sql.claim_plan_song` already use, and both
rejected alternatives were rejected on this repository's own recorded evidence — `SELECT … FOR
UPDATE` is a verified silent no-op in SQLAlchemy's SQLite dialect and the unit suite is
SQLite, and `session.begin_nested()` savepoints behave differently under aiosqlite. A lock
that is a no-op in the environment where the concurrency tests run is worse than no lock,
because it makes the tests green for the wrong reason.

Two consequences worth naming:

* **Step 5 returning `False` is not automatically an error.** Re-read by
  `payme_transaction_id`; if the fresh row is `performed`, return it. That is Payme's own retry
  losing a race with itself, and the correct answer is the replay (state 2, the stored
  `perform_time`), not `-31008`.
* **Step 7 returning `False` rolls the whole transaction back**, so a second Payme transaction
  racing for one intent performs nothing, grants nothing and is refused — and Payme cancels
  it. `test_two_concurrent_performs_on_one_intent_grant_exactly_one_credit` asserts exactly
  one Ok, one `topup_purchases` row, one `credit_ledger` GRANT and a balance of 1. It has a
  second copy marked `@pytest.mark.integration` against Postgres, because SQLite's file lock
  and Postgres READ COMMITTED reach the same answer for **different** reasons and only the
  second one is production.

### 3.3 The guards travel with the write, not with the caller

`_refuse_an_unpaid_purchase` and `_refuse_a_product_that_is_not_a_topup` are the **first
statements** of the extracted `write_single_sale`, not something its callers do first. They
run before the clock is read and before the transaction opens
(`src/hbd/db/purchases.py:186-188` is where they ran before the extraction). Lifting only "the
bodies" from `now =` onward — which is what a careless reading of the refactor produces —
would leave the gateway, *the one process in this system that writes money rows in response to
an inbound request from the public internet*, without the last-line defence whose own
docstring says it has to exist before the rail that needs it does.

`tests/test_db/test_fulfilment_guards.py` asserts those refusals through the **new** entry
point, which is the path the gateway takes.

---

## 4. Account errors: the `-31050 … -31055` allocation

Errors in the `-31050 … -31099` range are the "we cannot identify or accept this account"
family. Payme requires two things of them that no other error in the protocol requires:
`error.data` must be the account **subfield name** (our `HBD_PAYME_ACCOUNT_FIELD`, default
`order_id`), and `error.message` must be a map with exactly the three keys `ru`, `uz`, `en`.

**Those strings are rendered by Payme's UI, not ours.** They are therefore built in
`hbd/payme/protocol.py` and never come from `hbd.bot.i18n`, which speaks four languages
(`uz_latn` and `uz_cyrl` are distinct there) and would present the wrong shape as well as the
wrong key space.

| Code | Constant | When | Why not something else |
| --- | --- | --- | --- |
| `-31050` | `ACCOUNT_UNKNOWN` | no intent with that `public_ref` | Also the shape a cabinet misconfiguration produces — see below |
| `-31051` | `ACCOUNT_ALREADY_PAID` | intent state `paid` | A second charge for a delivered product |
| `-31052` | `ACCOUNT_CANCELLED` | intent state `cancelled` | |
| `-31053` | `ACCOUNT_EXPIRED` | intent state `expired`, or `pending` past `valid_until` | |
| `-31054` | *deliberately unallocated* | — | Third-party packages use it for the duplicate-transaction case; we do not guess (§7.2) |
| `-31055` | `ACCOUNT_WRONG_MERCHANT` | `intent.merchant_id` is not this gateway's | The single column that makes a sandbox/production or second-cashbox split-brain a refusal rather than a customer charged by the wrong cashbox |

Outside the range: `-31001` (wrong amount) and `-31008` (state refusal) carry **no** `data` and
a plain-string message; `-32601` carries the unknown method name in `data`.

**`-31050` is the single most likely go-live defect and it will look like our bug.** The
cabinet's «Настройка Аккаунт» field name is typed by a human into a web form and nothing in
this repository can validate it before the cabinet exists. So the `-31050` log line records
the account subfield names actually **received** alongside the one expected, which turns that
diagnosis into one line of the journal instead of a support ticket (see
[`../deployment/08-payme.md`](../deployment/08-payme.md) §5).

---

## 5. Idempotency: the five replay guarantees

Payme resends `CreateTransaction`, `PerformTransaction` and `CancelTransaction` on a lost
response, and the sandbox asserts that the second answer **equals** the first. Not "is also a
success" — equals. `tests/test_payme/test_sandbox_scenarios.py` issues every one of them twice
and compares the parsed bodies with `==`.

1. **A replayed `CreateTransaction`** on a transaction in state 1 returns the STORED
   `create_time` and `transaction` and writes nothing. The unique index on
   `payme_transaction_id` is the entire retry story.
2. **A replayed `PerformTransaction`** on state 2 returns the STORED `perform_time` and state
   2 — never `now()`, never an error, and it grants nothing a second time.
3. **A replayed `CancelTransaction`** on state −1 or −2 returns the STORED `cancel_time` and
   state as a **success**, never an error.
4. **A replayed checkout** in the bot: `open_intent` insert-or-ignores on `idempotency_key`,
   so pressing the button again re-mints the identical key, writes nothing, and returns the
   same `public_ref` and therefore the identical link.
5. **An operator force-settle followed by a late genuine Perform** grants nothing twice,
   because `force_settle` writes the sale under the intent's OWN bot-minted
   `idempotency_key` — the same string a real Perform would use — so both land on the same
   unique index (§6.2).

Guarantee 5 is why the recovery button is safe to press while unsure. It is the difference
between a recovery mechanism and a second way to pay a customer twice.

---

## 6. No post-perform reversal is built. This is a decision, not a gap.

### 6.1 Why `CancelTransaction` on a performed transaction answers `-31007`, unconditionally

`credit_accounts.balance` is documented at `src/hbd/db/plan_sql.py:15` as *"a single fungible
scalar with no lot structure"*, and `hbd.db.credit_sql.verify_balances` asserts
`balance == SUM(credit_ledger.delta)`. A refund of purchase A therefore has no way to know
whether the credit it is debiting is the one purchase A paid for or one the customer paid cash
for in purchase B. That is not a theoretical risk; it is a specific, reproducible way to take
away a paid entitlement.

Reinforcing facts: `topup_purchases` is append-only with no `refunded_at`; `CreditReason`'s two
refund members (`ORDER_FAILED`, `ORDER_NOT_DELIVERED`) are both about a *render*, not a
*charge*; and PaycomUZ's own PHP merchant template returns `false` from `Order::allowCancel()`
by default, which makes `-31007` **the reference behaviour** rather than a shortcut.

No flag, no settings field whose true branch raises, no dead code path. A reversal gets built
the first time a real refund is requested, as its own decision with its own migration.

### 6.2 What an operator does instead

A refund is a **cabinet action plus a credit correction**, in that order, and it is written
out step by step in [`../deployment/08-payme.md`](../deployment/08-payme.md) §7. In outline:
refund in the Payme cabinet; then `python -m hbd.tools.credits` to debit the credit if it has
not been spent; then record it. The `-31007` we return when Payme's system asks us to reverse
is expected and appears in the journal — `python -m hbd.payme.cli journal --ref <public_ref>`
shows it.

The inverse incident — *the customer paid and got nothing* — is the common one, and it has a
button: `python -m hbd.payme.cli settle --ref <public_ref> --note "<why>"`, which is
guarantee 5 above.

### 6.3 The open question this leaves

Payme's own sandbox scenario two cancels a performed transaction. If a certifier insists on
state −2 unconditionally, **the answer is a business decision, not a code one**: absorb the
refund at the cabinet and correct the credit by hand, or accept an entitlement reversal
against a fungible balance. Decide which before the certification slot rather than during it.

---

## 7. Three inferred protocol facts, and the experiment that closes each

Each is inferred from secondary evidence, each is therefore an **environment variable rather
than a constant**, and each is closed by a single observation during sandbox certification —
without a release. This section exists so that the person in the certification slot knows
exactly which three knobs are theirs to turn.

### 7.1 The Basic-auth login

The current documentation says to request it from a Payme technical specialist. The archived
2017 specification, PaycomUZ's own PHP template (`// Login is always "Paycom"`) and the
official Kotlin template's `security.user.name` all say the literal string `Paycom`. We
default to the evidence, expose it as `HBD_PAYME_BASIC_LOGIN`, and — the experiment — **the
`-32504` failure log line records the login actually received and never the key**, so the
first sandbox call answers the question.

Note the related hardening: the WHOLE decoded `login:key` pair is compared under
`hmac.compare_digest`. PayTechUz's widely-installed package splits on `:` and compares only
the trailing key, which accepts any username. `tests/test_payme/test_auth.py` pins that
weakening as a regression: the right key with login `admin` must FAIL.

### 7.2 The code for "this order already has another active transaction"

A real contradiction inside Payme's own materials: the sandbox scenario text demands `-31008`,
PaycomUZ's own PHP template returns `-31050`, and three third-party packages pick `-31054` or
`-31099`. We emit `-31008` through `HBD_PAYME_DUPLICATE_TRANSACTION_CODE`. The experiment is
the duplicate-transaction scenario itself: flip the variable and re-run it. Worth asking Payme
support before the slot rather than burning the slot on it.

### 7.3 Integer `0` for unset times

`perform_time` and `cancel_time` must serialise as integer `0` when unset, never `null`. The
official PHP template's `null` is the known deviation; payrest and PayTechUz both coerce to 0,
and every wire timestamp is a 13-digit integer of milliseconds since the Unix epoch, UTC. The
experiment is `CheckTransaction` against a freshly created transaction during certification:
if the sandbox accepts the reply, the inference held. `wire_time(None) == 0` and is an `int` is
asserted in `tests/test_payme/test_protocol.py`, so the shape cannot drift while the question
is open.

### 7.4 What is NOT inferred

Everything in the `# PROTOCOL CONTRACT` register is primary-sourced: HTTP 200 on every reply
including bad auth and parse failures (any other status reads to Payme as `-32300`/`-32400`
and costs us the `id` echo); a `jsonrpc` member accepted whether present or absent, because
every documented request example omits it; amounts as integer tiyin; `GetStatement` filtering
inclusively on Payme's own time and returning the plural key `{"transactions": […]}`;
`CheckPerformTransaction` returning a bare `{"allow": true}` and writing nothing at all.

---

## 8. Go-live and rollback

Full host procedure is [`../deployment/08-payme.md`](../deployment/08-payme.md); this is the
product-level sequence and the invariants that must hold at each step.

### 8.1 The order, and why it is this order

1. **Ship dark.** `HBD_CHECKOUT_PROVIDER=stub`, `HBD_PAYME_ENABLED=false`. Everything is
   built, tested and installed. Nothing behaves differently.
2. **Install the gateway credential-free**, with an invented 36-character key and
   `HBD_PAYME_IS_SANDBOX=true`, and run `python -m hbd.payme.harness` against it. That
   exercises the real database, the real ARQ enqueue, the real worker notification and a real
   Telegram message — the whole settlement path up to *"your payment went through"* — before
   Payme has heard of us. Rows created this way carry `is_sandbox=true` and are excluded from
   every revenue figure by construction.
3. **Certify in the sandbox** the day the cabinet exists. Step one inside that stage is
   declaring the account field name, because a mismatch makes every `CheckPerformTransaction`
   a `-31050` that looks like our defect (§4). Close the three inferred facts here (§7).
4. **Production, two restarts and no code change** (§8.2).

### 8.2 The two variables that must move together

`HBD_CHECKOUT_PROVIDER=payme` and `HBD_CREDITS_ENFORCED=true` move in the **same edit**.
`src/hbd/main.py` refuses to boot on a live rail with a dark credit meter — a real rail taking
real money into a meter nobody reads is a free song sold for 7 000 soʻm, and that must fail
the boot rather than log a warning. Failing in that direction is the point.

`HBD_KIT_PRICE_AMOUNT_MINOR` **stays 0** (§1.1). It is the render gate's quote, not the
checkout's.

### 8.3 The refusals that keep the two halves apart

Each is a boot-time `ConfigError` in prod, not a convention:

* the **bot** refuses if `HBD_PAYME_MERCHANT_KEY` is reachable in its environment or dotenv —
  it builds links with a public merchant id and must never hold the Merchant API key;
* the **admin panel** refuses likewise, via `FORBIDDEN_ENV_VARS`
  (`src/hbd/admin/app.py:116-118`) widened with `FOREIGN_SECRET_ENV_VARS` — which is what makes
  *"the Payme endpoint is not a router on the panel"* a mechanical fact rather than an
  intention;
* the **gateway** refuses if any of `hbd.config.REQUIRED_VENDOR_SECRET_FIELDS` is within
  reach — derived from that tuple, never restated, so a fifth vendor credential is covered
  without anybody remembering to;
* the **gateway** refuses on `payme_enabled=false` or a blank merchant key.

### 8.4 Rollback

`HBD_CHECKOUT_PROVIDER=stub` and one restart returns the product to exactly today's behaviour.
The stub is still wired, still constructed and still tested; both new tables are additive and
the stub reads neither. Open intents simply stop being created, **and any live Payme
transaction still settles correctly**, because the gateway is independent of the bot's provider
setting — which is the property that makes rollback safe to do during a payment.

To stop new checkouts without a restart at all: `python -m hbd.payme.cli pause`. It writes a
Redis key that the checkout provider reads and that **the inbound Perform never consults** —
refusing money that is already in flight is how an incident becomes a dispute. Two honest
caveats: a Redis rebuild silently un-pauses the rail, so `python -m hbd.payme.cli status`
re-checks it after any Redis restart; and a Redis read that raises is treated as *not* paused
and logged at WARNING, because a Redis blip must never silently stop sales.

### 8.5 What reconciliation actually is

There is **no outbound Merchant API method a merchant may call** — no status polling, no
fetch-my-transactions. Reconciliation is therefore two things and this is stated rather than
hidden:

* the **three-way settlement invariant**, logged hourly by the worker sweep: over the last 24
  hours, performed `payme_transactions` == `payme` receipts == credit grants under those
  idempotency keys. A mismatch is logged at ERROR with all three numbers and is **never
  self-repaired** — an operator must see it, because it is the only automated way to catch a
  defect in the shared write primitive;
* a **human diffing `python -m hbd.payme.cli statement --from … --to …` against a cabinet
  export**, weekly.
