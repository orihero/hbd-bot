# Payme Merchant API — the domestic rail

**Specification. Cite it by section: `PAYME_INTEGRATION §3.2`, never by path** — a section
number survives this file moving and a path does not, which is the rule
[`../README.md`](../README.md) states and which a previous reorganisation of `docs/` had to
enforce across twenty-two citations in `src/`, `tests/` and `migrations/`.

Companion documents: [`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11** is the
decision this specifies and **D9** is the decision D11 supersedes;
[`../deployment/08-payme.md`](../deployment/08-payme.md) is how the fourth process is
provisioned, operated and debugged, and
[`../deployment/09-payme-go-live.md`](../deployment/09-payme-go-live.md) is what was actually
run on the host, in what order, on 2026-09-09/10. And
[`BILLING_RAIL_BOARD.md`](BILLING_RAIL_BOARD.md) **§1** is the admin panel's view of everything
below — what an operator can see and press without a terminal, and, more usefully, what they
deliberately cannot (**D14**).

> **STATUS, 2026-09-10 — the gateway is DEPLOYED AND RUNNING, the rail is OFF, and no money has
> ever moved through it.** Those are three separate facts and §8.6.3 is why all three can be
> true at once. Verified on `aizu` on 2026-09-10, in the host's own pre-rename names:
> `hbd-payme.service` is `active` and `enabled`,
> running `-m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091` as `User=hbd`, reachable
> from the public internet as `https://pay.bayrambot.uz/payme`; the worker's `run_payme_sweep`
> fires every five minutes — twelve times in the last hour, re-checked 2026-09-11 — and its
> invariant arm reported three zeroes all that morning.
>
> **Two corrections to this block, 2026-09-11, and the second one is a fact about the first.** The
> revision: this block said the database was at `0024` on **2026-09-09** and that it had **not**
> been re-verified since, because `psql` needs a password the deploying account does not have. **It
> has now been re-verified — still `0024` — and the route needs no password at all**:
> `sudo -n -u postgres /usr/bin/pg_dump hbd | grep -A3 "COPY public.alembic_version"`, which the
> NOPASSWD drop-in has granted all along. The newer fact is that `0024` is **no longer head**: 25
> revision files are on disk, the newest being `20260910_1000_0025_index_settlement_clocks.py`, and
> it is unapplied. `../deployment/08-payme.md` §11.3 carries both numbers and why the gap matters
> to the rollback argument; `00-host-inventory.md` rows 15 and 47 are the rows to keep in step.
>
> And the invariant no longer reports three zeroes: at 10:55 +05 on 2026-09-11 it reported
> `transactions_performed: 1, receipts_written: 1, grants_written: 1` — the rehearsal below, still
> inside the rolling 24-hour window. **It will report three zeroes again at about 13:35 +05 that
> same day**, when the rehearsal falls out of the window, and §8.5.1 is where that third kind of
> zero is written up. And the checkout-provider
> variable is unset in the deployed environment — read there under its **pre-rename** name,
> `HBD_CHECKOUT_PROVIDER` (`BAYRAM_CHECKOUT_PROVIDER` in this repository), which is the trap the
> warning at the head of §8 exists for — so the composition root takes its first branch and
> builds `StubCheckoutProvider` (`src/bayram/runtime/container.py:358-361`). The bot issues no
> Payme link at all.
>
> **Nothing below describes money that has moved** — no customer has been charged and the bot
> still sells nothing. But the path `CreateTransaction → PerformTransaction → receipt and credit
> in one commit → ARQ job → Telegram message` **has now been executed on that host**: the
> harness passed 4/4 scenarios on 2026-09-10 at 13:30 +05 under run id `e767f6ce`, a Telegram
> message was delivered, and the worker's settlement invariant corroborated it five minutes
> later with `1, 1, 1`. `../deployment/09-payme-go-live.md` §4.0 is the transcript. Until that
> afternoon every check against the deployed gateway had been read-only, which is what §8.1 was
> written to say.
>
> The deployment disproved nothing in §1–§7. Those describe a state machine green against
> in-memory SQLite, a link builder pinned to Payme's own published golden vector (§1.3), and an
> ASGI app driven end to end **in the test suite** with a placeholder merchant key — because the
> key is only ever compared against itself, an invented one makes a functionally complete
> gateway. "End to end" there means the test suite, never this host.
>
> **What is taking customer taps today is the stub, and the stub is not a closed shop.** It
> quotes a price, replies "Paid" and grants the credit without taking any money. That is a
> decision with a date on it, not an oversight — §8.6.2.

---

## 1. The two seams, and why `charge` opens no socket

### 1.1 There are two payment seams in this repository and they answer different questions

`bayram.payments.PaymentProvider.authorize` answers *"may this order be rendered?"*. It is the
RENDER gate: called once per order, by the worker, against a credit the customer already
owns. `bayram.checkout.CheckoutProvider.charge` answers *"did money change hands for a
product?"*: called on a button tap, possibly many times per customer, and it has a receipt.
`src/bayram/checkout.py`'s module docstring has argued that separation since before a rail
existed, and it is the reason this integration touches exactly one of the two.

That distinction is also why `BAYRAM_KIT_PRICE_AMOUNT_MINOR` **stays 0 at go-live** (§8.2). The
render gate is quoted an amount for an order that is authorised against a balance; the
checkout is quoted an amount for a credit it is selling. They are two answers to two
questions and only one of them is a price a customer pays. The single flag that moves is
`BAYRAM_CREDITS_ENFORCED`.

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
| The **gateway** | inbound from the public internet | a fourth process, `bayram-payme.service` | the SECRET merchant key |

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
   `BAYRAM_PAYME_RETURN_URL` is refused at settings-build time — a truncated deep link fails in a
   way nothing observes.
2. **Percent-encoding is not decoded.** The return URL is passed raw and never quoted.
3. **`ct` (callback timeout) is not sent.** The documentation gives its default as 15 with the
   unit stated as milliseconds, which is not a plausible redirect delay. We do not send a
   parameter whose unit we cannot name.

The golden vector is Payme's own published one —
`m=587f72c72cac0d162c722ae2;ac.order_id=197;a=500` →
`https://checkout.paycom.uz/bT01ODdmNzJjNzJjYWMwZDE2MmM3MjJhZTI7YWMub3JkZXJfaWQ9MTk3O2E9NTAw`
— and it is pinned to **`encode_payload`, not to `build_checkout_link`**. That distinction is
load-bearing rather than pedantic, and this document said the looser thing until it was checked
against the code: Payme's single worked example carries neither `l` nor `cr`, and we always send
both, so pinning the whole builder would mean pinning a payload of our own invention against a
number we computed ourselves — proof that the encoder agrees with itself. Pinned at the encoder
it proves the encoder agrees with **Payme** (`src/bayram/payme/link.py`,
`tests/test_payme/test_link.py`).

The parameter order the builder emits — `m`, `ac.<field>`, `a`, `l`, `cr`, then `c` — is fixed
separately and for a different reason: a stable order makes the encoded blob a deterministic
function of its inputs, so a replayed `open_intent` (same idempotency key, same `public_ref`)
returns the byte-identical URL the customer may already have open in a browser tab. Two
consequences of the standard base64 alphabet are worth knowing before anyone writes code that
takes a link apart again: padding is kept, and `/` and `+` appear inside the blob, so the blob
is *everything after the host* and not reliably the last path segment.

`c` — the return URL — is **omitted entirely when it is blank**, never sent as `c=`. An empty
value is a value: Payme's parser would carry it and redirect a paying customer to nothing.
The return URL is **reported blank** in the deployed configuration as of 2026-09-10 — reported,
not read back, because the secrets files on that host are not readable by the account that
performs deploys — so no link this rail issues would carry a `c` at all. That is a working
configuration and not an unfinished one: settlement never depends on the customer coming back,
and a payment with no landing page is a completed payment. It is nonetheless a conversion choice
somebody should make deliberately rather than inherit, and unlike everything on §8.1's
outstanding list it is blocked on nobody.

### 1.4 Amounts are tiyin and nothing multiplies by 100

`single_song_price_minor` is `700_000` (`src/bayram/config.py:444`) and 700 000 tiyin is 7 000
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
name ends in `expires_at` and demands `bayram.db.purge.rows_past_expiry_statements` read it. That
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

**The converse is the case nobody had written down, and it is an operational one: the guarantee
covers `awaiting` and covers nothing else.** An intent still `pending` — a link handed to a
customer who has not yet reached Payme's form — is squarely in the expiry predicate's set, and
**two processes keep working on it while the gateway is down**:

* the **bot** keeps quoting. `PaymeCheckoutProvider.charge` opens no socket and owns no HTTP client
  (§1.3), so there is nothing in it that could observe a dead gateway. It keeps writing intents and
  handing out links at exactly the rate it did before;
* the **worker** keeps expiring. Arm one of the sweep is `expire_lapsed`, it runs every five
  minutes in its own process, and it consults nothing about the gateway's health.

So a gateway outage does **not** stop the shop and does **not** stop the clock: every `pending`
link whose twelve hours run out during it becomes a `-31053` — *«`ACCOUNT_EXPIRED`»* — which reads,
to the customer holding it, as a broken merchant. The property this subsection is about is what
keeps the *dangerous* half safe (money in flight settles), and it is precisely why the other half
needs saying out loud. **The control is to stop quoting before you stop answering**: pause, let the
`awaiting` intents settle, then take the gateway down. `../deployment/08-payme.md` §8 has the
operator form and `09-payme-go-live.md` §9.1 has the rollback form of the same fact.

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
`bayram.db.credit_sql.debit_balance` and `bayram.db.plan_sql.claim_plan_song` already use, and both
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
(`src/bayram/db/purchases.py:186-188` is where they ran before the extraction). Lifting only "the
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
`error.data` must be the account **subfield name** (our `BAYRAM_PAYME_ACCOUNT_FIELD`, default
`order_id`), and `error.message` must be a map with exactly the three keys `ru`, `uz`, `en`.

**Those strings are rendered by Payme's UI, not ours.** They are therefore built in
`bayram/payme/protocol.py` and never come from `bayram.bot.i18n`, which speaks four languages
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

## 5. Idempotency: the six replay guarantees

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

6. **A replayed settlement NOTIFICATION queues at most one render.** `notify_payment_settled`
   is at-least-once by construction — five ARQ attempts, the sweep's third arm as a backstop,
   the gateway's post-commit enqueue and an operator force-settle all reach it — so the render
   it now starts (§9) is latched by a conditional `UPDATE` of its own:
   `payment_intents.resumed_at`, claimed under `WHERE state = 'paid' AND resumed_at IS NULL`
   **before any side effect**. And even a render that somehow queued twice would be ONE order,
   because the id it queues is a UUID5 over the customer's draft — so the `orders` primary
   key, `job_id_for` and `credits.charge`'s already-paid probe all collide on that one value.

Guarantee 5 is why the recovery button is safe to press while unsure. It is the difference
between a recovery mechanism and a second way to pay a customer twice.

Guarantee 6 is the same property for the *render* rather than for the *charge*, and it is the
one guarantee here whose failure costs a vendor bill rather than only a duplicate row.

---

## 6. No post-perform reversal is built. This is a decision, not a gap.

### 6.1 Why `CancelTransaction` on a performed transaction answers `-31007`, unconditionally

`credit_accounts.balance` is documented at `src/bayram/db/plan_sql.py:15` as *"a single fungible
scalar with no lot structure"*, and `bayram.db.credit_sql.verify_balances` asserts
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
refund in the Payme cabinet; then `python -m bayram.tools.credits` to debit the credit if it has
not been spent; then record it. The `-31007` we return when Payme's system asks us to reverse
is expected and appears in the journal — `python -m bayram.payme.cli journal --ref <public_ref>`
shows it.

The inverse incident — *the customer paid and got nothing* — is the common one, and it has a
remedy: `python -m bayram.payme.cli settle --ref <public_ref> --note "<why>"`, which is
guarantee 5 above. **It is a terminal command and is deliberately not a button in the admin
console**, which renders the invocation as copyable text beside the cabinet reference to check
and offers no submit path at all — `BILLING_RAIL_BOARD` §4.4, decided in **D14**. The short
reason is that the panel is structurally forbidden the merchant key and therefore cannot show
the cabinet charge that authorises the press; the sufficient reason is that
`claim_intent_for_operator` is the one transition in this state machine that names no holder and
so drops the mutex every other move relies on (§2.4). Two things the console *does* give this
incident: the six-table dossier that says where the chain stopped, and — for the far commoner
case where the money and the credit are both fine and only the message never arrived — a
re-enqueue button for the confirmation, which SUPPORT can press.

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
default to the evidence, expose it as `BAYRAM_PAYME_BASIC_LOGIN`, and — the experiment — **the
`-32504` failure log line records the login actually received and never the key**, so the
first sandbox call answers the question.

Note the related hardening: the WHOLE decoded `login:key` pair is compared under
`hmac.compare_digest`. PayTechUz's widely-installed package splits on `:` and compares only
the trailing key, which accepts any username. `tests/test_payme/test_auth.py` pins that
weakening as a regression: the right key with login `admin` must FAIL.

### 7.2 The code for "this order already has another active transaction"

A real contradiction inside Payme's own materials: the sandbox scenario text demands `-31008`,
PaycomUZ's own PHP template returns `-31050`, and three third-party packages pick `-31054` or
`-31099`. We emit `-31008` through `BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE`. The experiment is
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

**The host procedure is [`../deployment/09-payme-go-live.md`](../deployment/09-payme-go-live.md)
— what to run, in what order, on which box, and what each step is expected to print.**
[`../deployment/08-payme.md`](../deployment/08-payme.md) remains the gateway's own provisioning
and debugging page. This section deliberately no longer restates either. It was written as a
plan before there was a host; the deployment of 2026-09-09/10 overtook most of it, and two
documents narrating one sequence is precisely how the two come to disagree about it. What is
kept here is what belongs to a specification rather than to a runbook: where the sequence
stands, the invariants that must hold at each step, what rollback does and does not undo, and
the decisions taken while going live (§8.6).

> **NAME TRAP, 2026-09-10 — the release running on `aizu` predates the `HBD_` → `BAYRAM_`
> rename, and every variable in this section is spelled `HBD_*` there.** The running unit
> carries `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` (read from `systemctl show
> hbd-payme` on 2026-09-10) and the installed artefact is
> `/opt/hbd/release/hbd_bot-0.1.0-20260909-py3-none-any.whl`. This matters more than a
> cosmetic mismatch because **pydantic-settings ignores a variable it does not recognise
> without saying so**: setting `BAYRAM_CHECKOUT_PROVIDER=payme` on that host today changes
> nothing, raises nothing, logs nothing, and leaves the stub selling songs for free. Until the
> release carrying the rename is installed, translate every `BAYRAM_` below to `HBD_` and every
> `python -m bayram.…` to `python -m hbd.…`. Delete this box in the same change that ships the
> rename to the host, and not before.
>
> **The old-spelling strings in this box and in the STATUS block are verbatim host output read
> on 2026-09-10, and they are the one thing in this tree a repository-wide rename must not
> touch.** An earlier draft of this box was swept by one and came out reading «`BAYRAM_` →
> `BAYRAM_`», pointing at a `/opt/bayram` **whose venv now exists and which no unit executes** —
> a confident-looking instruction that fails at the first command. If the paths, unit names and
> prefixes in this box match this repository's current names rather than the host's older ones,
> the box has been corrupted by exactly that pass: `09-payme-go-live.md` is the authority, and the
> fix is to restore it from the host rather than to edit it here.
>
> **That example needed replacing on 2026-09-11, and the replacement is worse news than the
> original.** It used to read *"pointing at an `/opt/bayram` that exists on no machine"*, which was
> true until 2026-09-10 14:06. `[HOST 2026-09-11]` `/opt/bayram/venv` exists, with the `bayram`
> package installed in it, and `/etc/bayram/payme.env` exists too — both left behind by a rename
> cutover that aborted before writing a single unit file. **So a swept instruction no longer fails
> at the first command: it succeeds, against a tree nothing runs.** `ls` confirms the path,
> `/opt/bayram/venv/bin/python -c "import bayram"` works, and the gateway serving real traffic is
> still `/opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app`. **The cheap check that
> distinguishes them is the unit, never the filesystem** —
> `systemctl cat hbd-payme | grep -E "ExecStart|ENV_FILE"` — and
> [`../deployment/10-rename-cutover.md`](../deployment/10-rename-cutover.md) §2 and §3 are the
> record of the attempt and the inventory of everything now duplicated under two names.

### 8.1 Where the sequence stands — verified on the host, 2026-09-10

The four steps below are the original order and it is still the right order. What has changed
is that three of them now have an answer.

| Step | Where it stands |
| --- | --- |
| 1. **Ship dark.** Everything built, tested and installed; nothing behaves differently. | **Done, 2026-09-09.** The wheel is installed into the deployment venv with a `-ROLLBACK-` copy kept beside it in the release directory; ten migrations `0015`–`0024` applied. ~~Database at head~~ — **the database is at `0024` and the head on disk is now `0025`**, re-verified 2026-09-11; `0025` is additive (an index), so the rollback argument extends. Note what a wheel does **not** carry: migrations. The `.py` revision files are copied to the host separately, and missing that step makes `alembic upgrade head` stop at whatever is on disk and **report success**. |
| 2. **Install the gateway credential-free**, with an invented 36-character key, and rehearse the whole settlement path with the harness. | ~~Half done, and this is the open one. The harness has never been run.~~ **DONE, 2026-09-10 at 13:30:14 +05**: 4/4 scenarios under run id `e767f6ce`, a Telegram message delivered to a real phone, and the worker's invariant corroborating at 13:35:00 with `1, 1, 1`. It ran against the **real sandbox cashbox** rather than the invented key, because the credentials had landed minutes earlier. `../deployment/09-payme-go-live.md` §4.0 is the transcript. **It becomes owed again at the Gate A rename**, which is why the row is struck through rather than deleted. |
| 3. **Certify in the sandbox** the day the cabinet exists — declaring the account field name first, because a mismatch makes every `CheckPerformTransaction` a `-31050` that looks like our defect (§4), and closing the three inferred facts (§7). | **Four of six facts closed 2026-09-10**: the sandbox merchant id and TEST_KEY are installed and the boot line confirms the gateway read them (`merchant_id: 6aa24fd9ee30563de3a1ac22`, `[HOST 2026-09-11]`), the endpoint `https://pay.bayrambot.uz/payme` is registered, and the `order_id` requisite is declared with the validator of `08-payme.md` §5.1. **Two remain and neither blocks the slot**: the production key, which is a Gate F edit, and the Basic-auth login, which only a call from their side can prove (§7.1). The *slot itself* is still blocked on Payme. |
| 4. **Production, no code change** — the two variables of §8.2 and a restart of the bot and worker units. | **Not started, and gated on the owner rather than on step 3** (§8.6.2). |

**What step 2 did prove, and the exact shape of what it did not.** Through the Cloudflare
tunnel, on 2026-09-10: `POST https://pay.bayrambot.uz/payme` with no credentials answers **HTTP
200** with `{"error":{"code":-32504}}`, and the same call under `Paycom:<key>` answers HTTP 200
with `{"error":{"code":-31003},"id":77}`. Read what that actually establishes — it is more than
"the endpoint is up" and much less than "the rail works":

* the **HTTP 200 on a rejected request** is the single protocol invariant most likely to be
  broken by something in front of the app (§7.4). It holds end to end, through a proxy we do
  not control;
* `-31003` means the request was authenticated, parsed, dispatched to `CheckTransaction`, and
  reached the ledger, which correctly found no such transaction. Everything up to the database
  is wired;
* the literal login `Paycom` (§7.1) authenticates **against our own gateway**, which proves our
  comparison works and proves exactly nothing about what Payme will send;
* `GET https://pay.bayrambot.uz/` answers 404 from **Caddy**, not from the app — the site block
  routes only `/payme` and answers everything else with a bare 404, so `/healthz` and `/readyz`
  stay on the loopback where the monitor reaches them.

**Every one of those calls was read-only, and until 2026-09-10 settlement had never been
executed on this host** — no `CreateTransaction`, no `PerformTransaction`, no receipt, no credit
grant, no ARQ job, no Telegram message. **Step 2 has since been run and passed** (4/4, run id
`e767f6ce`, `../deployment/09-payme-go-live.md` §4.0), so what follows describes a rehearsal that
happened rather than one that is owed — and it describes it in the present tense on purpose,
because the Gate A rename cutover makes it owed again. The harness opens **real intents stamped
`is_sandbox=true`**
(`src/bayram/payme/harness.py:1023`) and drives the real database, the real enqueue, the real
worker notification and a real Telegram message, so it is the only rehearsal that exercises the
one commit (§3) before a customer's card does. Rows it writes are excluded from every revenue
figure by that flag rather than by being cleaned up afterwards.

Two host facts make running it slightly awkward and both belong in the runbook rather than
here: the gateway's env file is mode `0640`, owned by `root` and readable only by the service
group, so the harness runs **as the service user** with the gateway's env-file variable passed
explicitly rather than from a deploy shell; and the endpoint it drives is the loopback one
(`http://127.0.0.1:8091/payme`) rather than the public hostname. The exact command is in
`09-payme-go-live.md`.

**`PAYME_IS_SANDBOX` on the deployed gateway: `true`, and it needed no privilege to establish.**
An earlier draft of this section recorded it as unknowable because the env file is unreadable to
the deploying account. That was the wrong place to look: the gateway prints its whole effective
configuration — never a secret value — at INFO on every boot, and the line observed on `aizu` at
09:27:28 on 2026-09-10 reads `"is_sandbox": true` alongside `"environment": "dev"`,
`"merchant_id": "placeholder"`, `"account_field": "order_id"`, `"basic_login": "Paycom"`,
`"duplicate_transaction_code": -31008` and `"merchant_key_length": 36`
(`08-payme.md` §2.1 quotes the line in full). The reason it was worth asking survives the
answer, so keep it in view: the two settings objects default **oppositely** —
`Settings.payme_is_sandbox` defaults `true` (`src/bayram/config.py:834`),
`PaymeSettings.payme_is_sandbox` defaults `false` (`src/bayram/payme/settings.py:242`) — so a
gateway running non-sandbox while the bot builds sandbox links is a split that nothing would
report. The boot line is how you check it, on both processes, after every edit.

What step 2 genuinely cannot answer is whether Cloudflare's own protections will ever answer a
Payme call with a challenge page. That is a live risk with no mitigation in place yet: the
tunnel is the only public path to this host, so Cloudflare's proxy cannot be bypassed, and a
bot-challenge or error page returned to Payme reads to them as `-32400` and retries. Turning
bot-fight mode off for `pay.bayrambot.uz` and adding a WAF skip rule is outstanding work,
tracked in `09-payme-go-live.md`.

### 8.2 The two variables that must move together

`BAYRAM_CHECKOUT_PROVIDER=payme` and `BAYRAM_CREDITS_ENFORCED=true` move in the **same edit**.
`src/bayram/main.py` refuses to boot on a live rail with a dark credit meter — a real rail taking
real money into a meter nobody reads is a free song sold for 7 000 soʻm, and that must fail
the boot rather than log a warning. Failing in that direction is the point.

`BAYRAM_KIT_PRICE_AMOUNT_MINOR` **stays 0** (§1.1). It is the render gate's quote, not the
checkout's.

**One edit, two restarts, and it is worth knowing which is which.** The two variables are read
by different processes: the rail is built in one place, from the bot's composition root
(`src/bayram/runtime/container.py:486`), so the provider switch reaches only the **bot** unit;
the credit meter is read by the bot *and* by the worker, where a short balance becomes an
`UNENFORCED_RENDER` grant and the song is rendered anyway (`src/bayram/runtime/jobs.py:274`).
On `aizu` both units load the same secrets file, so it is genuinely one edit — but restarting only the bot would leave the worker still covering
shortfalls, which is the failure this pairing exists to prevent, silently reintroduced by half
a deploy.

Neither variable has moved. On 2026-09-10 at 09:27:36 the bot logged, at boot,
`the checkout is wired but the credit meter is dark` with `credits_enforced: false` — the
warning at `src/bayram/main.py:380-395`, which survives *precisely* for the stub case and would
be a `ConfigError` if the rail were live. Seeing that line in the bot unit's journal is the
cheapest confirmation that the product is in the state §8.6.2 describes.

### 8.3 The refusals that keep the two halves apart

Each is a boot-time `ConfigError` in prod, not a convention:

* the **bot** refuses if `BAYRAM_PAYME_MERCHANT_KEY` is reachable in its environment or dotenv —
  it builds links with a public merchant id and must never hold the Merchant API key;
* the **admin panel** refuses likewise, via `FORBIDDEN_ENV_VARS`
  (`src/bayram/admin/app.py:116-118`) widened with `FOREIGN_SECRET_ENV_VARS` — which is what makes
  *"the Payme endpoint is not a router on the panel"* a mechanical fact rather than an
  intention;
* the **gateway** refuses if any of `bayram.config.REQUIRED_VENDOR_SECRET_FIELDS` is within
  reach — derived from that tuple, never restated, so a fifth vendor credential is covered
  without anybody remembering to;
* the **gateway** refuses on `payme_enabled=false` or a blank merchant key.

### 8.4 Rollback

`BAYRAM_CHECKOUT_PROVIDER=stub` — or the variable deleted, which is the same thing, since `stub`
is the default — plus a restart of the **bot** unit returns the checkout seam to the stub. The
stub is still wired, still constructed and still tested; both new tables are additive and the stub reads
neither. Open intents simply stop being created.

**Any live Payme transaction still settles correctly**, and that is no longer an argument from
design. On `aizu`, verified 2026-09-10, the two halves read two different files under two
different unit files: the bot loads the shared secrets file with `EnvironmentFile=`, while the
gateway is told its own, separate file by an env-file **variable** and runs as its own service
user on `127.0.0.1:8091`. Nothing the bot's rollback touches is legible to the gateway. That is the property that makes rollback
safe to perform *during* a payment, which is when it will be wanted.

**The correction the deployment forced.** This section used to say rollback "returns the product
to exactly today's behaviour", written when the stub was a placeholder nobody could reach.
It is not a neutral position now: **rolling back to the stub does not close the shop, it reopens
the free one** (§8.6.2). The stub quotes a price, replies "Paid" and grants the credit without
taking money, so a rollback motivated by *"stop charging customers"* succeeds and a rollback
motivated by *"stop selling"* does not. There is no flag that removes the purchase buttons; if
the shop must genuinely close, that is a code change, and it should not be discovered at the
moment somebody needs it. Order of operations when rolling back a live rail: pause first (below),
let the in-flight transactions settle, then flip the provider — flipping first merely stops new
intents, which the pause does anyway and faster.

To stop new checkouts without a restart at all: `python -m bayram.payme.cli pause`. It writes one
Redis key that the checkout provider reads and that **the inbound Perform never consults** —
refusing money that is already in flight is how an incident becomes a dispute, since the card is
charged, Payme is holding funds it believes are ours, and `CancelTransaction` on a performed
transaction is `-31007` by design (§6). Four honest caveats now, not two — the count has gone up
once per month of this rail's life, which is itself worth noticing:

* a Redis rebuild, a `FLUSHDB` or eviction under `maxmemory` pressure silently un-pauses the
  rail — the key carries no TTL but Redis is a cache in this deployment — so
  re-check it after any Redis restart, with `python -m bayram.payme.cli status` **or** on the
  admin console's rail header, which reads the same key through the same `is_paused` function
  (`BILLING_RAIL_BOARD` §2.2). The console is a second *writer* of this switch as well as a
  second reader — one key, one mechanism, and it must never become two;
* a Redis read that raises is treated as *not* paused and logged at WARNING, because a Redis blip
  must never silently stop every sale in the product. It follows that **this switch is not a
  security control** and must never be relied on as one;
* **today it stops nothing, and the reason is narrower than it was.** The pause reader that
  *changes behaviour* is wired into `PaymeCheckoutProvider` alone (`src/bayram/payme/pause.py`),
  and the stub is what is built, so on the current deployment `pause` stops no sale. It becomes
  operative at the same moment the rail does. **What is no longer true is "a key no running
  process reads"**: the admin console reads the same key through the same `is_paused`, in a third
  process, and renders it in the payments screen's header — so a pause set today is invisible in
  its effects and perfectly visible on a screen. Hold both halves, because an operator who sees
  "paused" in the console and infers "nothing can be sold" is reading a true statement about the
  switch and a false one about the shop: today the stub sells regardless.
* **resuming is a `DELETE`, not a falsy write.** Presence is the signal, and `0`, `""`, `false`,
  `no` and `off` are all read as *open* — deliberately, so that a hand-typed
  `redis-cli SET <key> 0` does nothing rather than quietly pausing the rail, which is the opposite
  of what the person typing it intended. It follows that nothing you write into the value will
  resume a paused rail: `resume` is what does, and nothing else.

### 8.5 What reconciliation actually is

There is **no outbound Merchant API method a merchant may call** — no status polling, no
fetch-my-transactions. Reconciliation is therefore two things and this is stated rather than
hidden:

* the **three-way settlement invariant**, checked on **every run of the worker sweep** — arm
  four of `run_payme_sweep`, so every `BAYRAM_PAYME_SWEEP_MINUTES` minutes, five by default and
  five as deployed — over a rolling **24-hour** window: performed `payme_transactions` ==
  `payme` receipts == credit grants under those idempotency keys. The window is a day rather
  than the five minutes between runs because a defect that appeared at 03:00 must still be
  visible at 09:00 when somebody is awake to read it. A mismatch is logged at ERROR with all
  three numbers and is **never self-repaired** — an operator must see it, because it is the only
  automated way to catch a defect in the shared write primitive;
* a **human diffing `python -m bayram.payme.cli statement --from … --to …` against a cabinet
  export**, weekly.

The admin console now renders the same invariant on the rail board's settlement card, from
`settlement_counts` **called unchanged** rather than re-derived — a second copy of that
three-subquery statement is exactly how the panel and the sweep would come to report different
numbers about one window. Two differences from the log line, both deliberate and both specified
in `BILLING_RAIL_BOARD` §5: the card renders the CLI's identity
`transactions_performed + operator_settlements == receipts_written` rather than the two-way
equality, because a force-settled intent has no performed transaction and rendering the two-way
form makes every use of the recovery button read as a defect; and an all-zero result renders as
**`never_settled`**, explicitly not as a pass, for the same reason §8.1 gives about three zeroes
on this host. There is still **no "run reconcile" button** — the sweep already runs it twelve
times an hour, and a read must not be a POST.

This document said "logged hourly" until 2026-09-10 and that was wrong; a first correction on
the same day replaced it with a second wrong claim — that arm four "logs only on a mismatch" —
and the host settled both. **Arm four writes nothing anywhere, ever, but it does log on the
healthy path**, at INFO, as a line of its own with all three counts
(`_report_counts`, `src/bayram/runtime/payme_jobs.py:808`). What misled the earlier reading is
that the counts are **not** on the sweep's summary line: that line carries `intents_expired`,
`transactions_timed_out`, `notifications_re_enqueued`, `faults` and `duration_ms` and nothing
else. Two lines, one sweep. Observed on `aizu` at 10:10:00 on 2026-09-10, in this order:

```
"the payme settlement invariant holds"  {window_from, window_to,
   transactions_performed: 0, receipts_written: 0, grants_written: 0}
"payme sweep finished"                  {intents_expired: 0, transactions_timed_out: 0,
   notifications_re_enqueued: 0, faults: 0, duration_ms: 38}
```

So the "all clear" **is** emitted twelve times an hour, and grepping the sweep summary for
invariant counts will always come up empty while the subsystem is perfectly healthy. Grep for
the invariant's own message instead — which is what makes Gate C's closing check in
`09-payme-go-live.md` §4 work: after a rehearsal those three numbers must be equal and
**non-zero**. A mismatch is logged at ERROR with the same three numbers and is never
self-repaired. A fuller on-demand audit is `python -m bayram.payme.cli invariant`.

#### 8.5.1 Three zeroes have three causes, and the third one was not foreseen here

This section used to finish *"today's three zeroes are the proof that nothing has ever settled"*.
**That is only one of the three things three zeroes can mean, and the window is what distinguishes
them.** The arm reconciles a rolling **24 hours**, so:

1. **nothing has ever settled** — what `09-payme-go-live.md` §0.1 is about, and what the console's
   `never_settled` verdict is for. Needs a row probe to establish, not a count;
2. **the sweep ran before the settlement it should have seen** — the 13:30:00 sweep of 2026-09-10
   fired fourteen seconds before the harness started and reported zeroes that were correct and
   completely misleading. Wait for the next one;
3. **the settlement aged out of the window.** `[HOST 2026-09-11]` the arm reported
   `1, 1, 1` at 10:45, 10:50 and 10:55 +05 over a window opening the previous day — and the
   rehearsal it is counting happened at 13:30 +05 on 2026-09-10, **so at about 13:35 +05 on
   2026-09-11 those counts return to `0, 0, 0` and stay there.** Nothing will have broken. The
   subsystem will look exactly as it did on the morning the zeroes meant cause 1.

**That is the shape worth carrying away: a count over a window cannot tell you whether the
population is empty or merely outside the window, and only a window-ignoring row probe can.** It is
the same argument `BILLING_RAIL_BOARD` §8.1 makes for travelling every count beside a ROW probe, and
it applies to the log line exactly as it applies to the screen. When you need "has this deployment
**ever** settled anything", ask the tables, not the last sweep.

### 8.6 The decisions taken while going live, 2026-09-09/10

Three decisions were taken on the host and each is recorded here because each is the kind that
gets rediscovered as a bug six months later by somebody who was not in the room. They are
numbered so code and runbooks can cite them.

**8.6.1 — The gateway runs as a fourth process. Confirmed, not revisited.** `D11` argued this
before there was a host and the host changed none of the argument: one systemd unit, one dotenv,
one hostname, `pool_size=3, max_overflow=2`. What the deployment adds is that the boundary is
now a *file-system* fact rather than a design intent — the gateway's env file is mode `0640`,
owned by `root` and readable only by the service group, so the account that performs deploys
cannot read the cashbox key at all, and the gateway's own `InaccessiblePaths=` hides the bot's
and the panel's env files from it in the other direction.
The price was paid honestly and is worth naming so nobody re-litigates it cheaply: a fourth unit
to restart on every release, a fourth process to watch, and the one Caddy site block that has to
be written `http://pay.bayrambot.uz` rather than `pay.bayrambot.uz`, because the tunnel speaks
plain HTTP to the origin and a scheme-less block makes Caddy enable automatic HTTPS and answer
every tunnelled request with a `308` to itself — which Payme reads as `-32400` and retries
forever. That trap cost real time on 2026-09-09 and is written up in `09-payme-go-live.md`.

**8.6.2 — The paywall stays in its stub state until the owner says otherwise. Decided
2026-09-10 by the owner, asked directly.** State it plainly, because a euphemism here would be
the dishonest kind: **customers today see a purchase flow that takes no money.** They are quoted
7 000 soʻm, they tap, `StubCheckoutProvider` reports the purchase paid, the credit is granted and
the bot replies "Paid". `BAYRAM_CREDITS_ENFORCED` is false besides, so even a short balance is
covered by an `UNENFORCED_RENDER` grant and the song is rendered regardless. Nothing is charged
and nothing is owed. This is **not an oversight and not a bug to be filed**: the rail is built,
the gateway is deployed, and the only thing standing between this state and real money is the
pair of variables in §8.2. The owner was asked on 2026-09-10 and decided to leave it as it is,
and will say when to start accepting real payments. Two consequences to hold onto: the switch-on
is a configuration edit and two restarts, not a release (§8.2); and any revenue reasoning done
against `topup_purchases` rows written in this period is reasoning about gifts, not sales.

**8.6.3 — `BAYRAM_PAYME_ENABLED` and `BAYRAM_CHECKOUT_PROVIDER` are two switches answering two
different questions, and conflating them is the most likely way to turn the rail on by
accident.** The distinction is the whole reason the STATUS block at the top of this document can
say "deployed and running" and "off" in the same sentence:

| Variable | Read by | Asks | On the host, 2026-09-10 |
| --- | --- | --- | --- |
| `BAYRAM_PAYME_ENABLED` | the **gateway** unit | *May this daemon serve Payme's inbound calls at all?* The lifespan refuses to start on `false`. | `true` — the daemon is up and answering |
| `BAYRAM_CHECKOUT_PROVIDER` | the **bot** unit | *Does the product sell anything for real money?* `stub` (the default) builds `StubCheckoutProvider`; `payme` builds the real rail and requires `BAYRAM_CREDITS_ENFORCED=true` in the same edit. | unset, therefore `stub` — nothing is sold for money |

Read the table in the direction that matters: **`BAYRAM_PAYME_ENABLED=true` does not mean the
rail sells anything, and `BAYRAM_CHECKOUT_PROVIDER=stub` does not mean the endpoint is shut.**
A gateway that is up while the rail is off is the correct and intended posture for certification
— Payme can call us, we answer the protocol correctly, and no customer can be charged, which is
exactly what a sandbox slot needs. The mirrored error is the dangerous one: enabling the
**gateway** in the belief that it opens the shop leaves an unauthenticated public endpoint
running for no reason, and switching the **bot** to `payme` in the belief that the gateway's
own switch still guards anything charges customers with no second gate behind it. There is no combination that is
merely untidy — each is a specific failure, and they are different failures.

---

## 9. The settlement starts the render (D17)

A settled payment does not merely announce itself. It starts the song the customer was paying
for — which is the difference between a redirect rail and an inline one, stated as product:
an inline rail settles while the customer is still looking at the screen, so "pay, then press
🎬" is two taps in one sitting, while a redirect rail settles minutes or hours later with the
customer's phone in their pocket.

### 9.1 The marker, and why it is the order id

`bayram/bot/handlers/checkout.py` computes `order_id_for(user, draft)` when it builds the
checkout link and passes it through `PurchaseRequest.resume_order_id` → `open_intent` →
`payment_intents.resume_order_id` (migration 0026). It is `None` whenever the purchase buys no
render: bought from `/balance`, or made against a draft that is incomplete or carries no
approved lyric — the same two refusals `handle_confirm` makes, in the same order, so a payment
can never record a render the 🎬 button would itself have refused.

That id is the draft's own UUID5 fingerprint, so one value is three things at once: the
`orders` primary key, the seed of `pipeline.worker.job_id_for`, and the proof at settlement
that the draft has not moved. A customer who edits anything after paying is declined by a
single equality.

**A replayed `open_intent` returns the WINNER's marker.** Two presses in one wizard run mint
the same `idempotency_key` (the counter does not move on this branch — guarantee 4), so the
second insert is ignored and the intent keeps the render the link the customer is holding was
opened for.

### 9.2 The settlement, in order

`bayram/runtime/render_resume.py`, called from `notify_payment_settled` **after** the payment
sentence has been sent and stamped:

1. **Plan** — a pure read. Storage handle, the customer's FSM session, `Wizard.confirm` and no
   render already in flight, the draft loads and is complete with an approved lyric, the flag
   is on, a marker exists, the re-derived id matches, no `orders` row holds it yet. It writes
   nothing, so the announcement's sentence and keyboard can be chosen from its answer.
2. **Queue handle** — checked first among the acting steps because it is the only one with no
   side effect, so a half-wired worker burns neither the claim nor a progress frame.
3. **Claim** — `claim_resume`, the conditional `UPDATE` of guarantee 6, before anything else.
4. **Progress frame** — posted before the submit, so the render job's events land in a message
   that already exists.
5. **Submit** — through `ArqOrderSubmitter`, which owns persist-then-enqueue.
6. **Park** — one `update_data`, after the submit, so `jobs._release_session` finds the order
   id it expects and can un-park the session when the song lands.

### 9.3 What it deliberately does not do

* **It does not synthesise a Telegram update.** aiogram's event-isolation lock is
  per-dispatcher and in-process, so a second dispatcher in the worker would hold a different
  lock over the same Redis FSM key — a real tap and a synthesised one could both proceed, and
  that is a second charge. The full argument is in `render_resume`'s module docstring.
* **It does not render for a blocked customer.** `_send` returns `False` on a `Forbidden` and
  the resume is below that return: `entitlements` settles `NOT_DELIVERED` exactly as it
  settles `DELIVERED`, so rendering for an unreachable chat spends a paid credit on a kit that
  provably cannot arrive.
* **It does not recover from a crash between the claim and the enqueue.** That customer is
  left where every customer was before this existed — told they have a song, one tap away.

### 9.4 The rollback

`BAYRAM_AUTO_RENDER_ON_PAYMENT=false`, one restart, no deploy and no migration. It restores
the previous behaviour exactly. The migration's downgrade is for removing the *schema* once
that lever is already off — dropping the columns with the feature still on would take the
at-most-once latch away with them.
