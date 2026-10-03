# The checkout.uz rail — Click and Payme through one hosted page

This page covers provisioning, switching on, operating and debugging the checkout.uz rail. The
customer presses a "Click / Payme" button, pays on checkout.uz's own page, and the **worker** then
confirms the payment by asking checkout.uz itself. The reasons for every rule below are in
`DECISIONS.md D28`; this page only covers how the rail runs on a host.

> **STATUS: WRITTEN FROM THE TREE ON 2026-10-03. NOTHING ON THIS PAGE HAS BEEN DONE ON THE HOST.**
> No key is installed, migration 0030 has not been applied there, and nobody has checked whether
> the tunnel route for `/checkoutuz/*` exists. Each step below is a step to perform, not a
> description of a running system. Statements carry `[TREE 2026-10-03]` when they were read off
> the code, and `[HOST <date>]` only once somebody has checked them on `aizu`.

> **THERE IS NO SANDBOX.** checkout.uz documents no test host and no test key. Every payment on
> this rail is real money, including the first test (§9), and **a test payment needs the owner's
> explicit yes, with the count and the cost stated**, before it is made.

---

## 1. What the rail is, in one picture

```
customer presses 💸 Click/Payme
  └─ bot: CheckoutUzCheckoutProvider.charge()                       (bot process)
       ├─ refuses if the owner switch is off, or the checkout is paused, or the price
       │   is not whole soʻm in 1 000..10 000 000
       ├─ opens (or re-uses) a payment_intents row, provider = 'checkoutuz'
       ├─ re-uses a link from this intent that is live for more than 60 s, OR
       │   POST https://checkout.uz/api/v1/create_payment   (Bearer key; amount in SOʻM)
       │   and inserts a checkoutuz_payments row (order_id = checkout.uz's _id)
       └─ shows one button per payment method (Click, Payme, Uzcard/Humo, …), then
           "All payment methods", with the hint "valid for 1 hour"   (see below)

customer pays on checkout.uz (Click or Payme)
  ├─ (maybe) checkout.uz → POST https://pay.bayrambot.uz/checkoutuz/callback/<public_ref>
  │     Cloudflare edge → tunnel → [Caddy :80 handle /checkoutuz/*] → gateway 127.0.0.1:8091
  │     gateway: one SELECT; if the order is known and pending → enqueue
  │     reconcile_checkoutuz_order; ALWAYS answers 200 {"ok":true}
  └─ worker cron run_checkoutuz_poll, every 5 min at :01, :06, … :56   ← THE SOURCE OF TRUTH
        └─ settle_checkoutuz_order(order_id):
             POST /status_payment {id} → must be status "paid", the same id, and the stored
             amount (which must equal the intent's amount_minor / 100)
             then, in ONE transaction: payment pending→paid, intent →paid, receipt + credit
             then enqueue "your payment went through", and the D17 auto-render
```

Three properties of this flow matter more than the rest:

- **The webhook is believed for nothing** `[TREE 2026-10-03]`. It is unsigned and never retried,
  and it reaches us from the open internet. The route reads one number from it (`order_id`) and
  only uses it to decide whether a worker job is worth enqueuing. A forged call can, at most,
  make the worker ask checkout.uz about an order we already hold as pending.
- **The poll settles everything without the webhook.** A lost webhook costs the customer at
  most one poll interval (`BAYRAM_CHECKOUTUZ_POLL_MINUTES`, default 5).
- **One intent can have several links.** A link lives one hour and an intent lives twelve. A
  press within the hour hands back the same link; a later press mints a new one **beside** the
  old one. Every link stays pollable until its hour plus a 15-minute grace has passed. After
  that the poll asks once more and then closes the link as `expired`. If checkout.uz cannot be
  asked (`retry_later`), the link stays pending and is asked again on later passes — each
  failed attempt is stamped, so it rotates to the back of the batch — until 24 hours after its
  end; then it is closed `expired` with an ERROR `checkoutuz.final_check_unresolved` (§7.2).

The tables `[TREE 2026-10-03]`:

| Row | Where | What it says |
| --- | --- | --- |
| the intent | `payment_intents`, `provider = 'checkoutuz'`, `merchant_id = 'checkoutuz'` on a stub deployment | Was this purchase settled? Expiry is the Payme sweep's `payme_intent_ttl_s` (12 h), as for every redirect rail. |
| each link | `checkoutuz_payments` (migration 0030): `order_id` (checkout.uz `_id`, PK), `intent_id`, `payment_uuid`, `pay_url`, `pay_via`, `amount_som`, `state`, `link_valid_until`, `last_polled_at`, `paid_at` | Has THIS link been checked for the last time? `state` is `pending` / `paid` / `expired` / `orphan_paid`. Only `pending` moves, plus `expired -> paid` when checkout.uz confirms a late payment (§7.2). |
| a settled intent | `payment_intents.settle_note = 'checkoutuz:<order_id>'` | Which link paid it. |

**What the customer sees after pressing the price button** `[TREE 2026-10-03]` (`DECISIONS.md`
D28 rule 18). The paywall message turns into the link screen. Its buttons are:

1. one URL button for each payment method in checkout.uz's `_pay_via`, two per row, in the order
   checkout.uz sent them. Each opens that method's own page. The labels are brand names and are
   not translated: Click, Payme, Uzcard / Humo, Plum, Paylov, Xazna, OSON. A method the bot does
   not know is shown under its key, capitalised;
2. 🌐 "All payment methods", which opens the general `pay_url` page;
3. 🏠 back to the menu.

The method list is whatever the merchant has enabled in the checkout.uz dashboard. It is
captured when the link is minted and stored in `checkoutuz_payments.pay_via`, so a re-press
within the hour shows the same buttons. If `create_payment` returns no `_pay_via`, there is one
WARNING `checkoutuz.client.pay_via_missing` and the screen falls back to a single 🔗 button for
the general page. If some entries are malformed, they are dropped with one WARNING
`checkoutuz.client.pay_via_dropped`. A method switched on or off in the dashboard shows up on the
next newly minted link.

The expiry column is called `link_valid_until`, not `link_expires_at`. Any `*expires_at` column is
treated as a retention clock by `tests/test_db/test_audit_retention.py`, and this column is not
one.

---

## 2. Configuration and where the key goes

All of these are `Settings` fields, read from **the bot's dotenv only**: `/etc/bayram/bot.env`,
which both `bayram-bot` and `bayram-worker` read through `BAYRAM_ENV_FILE`. There is no
`.env.checkoutuz`. The variable reference is `02-configuration.md`, section "The checkout.uz
rail".

| Variable | Default | Notes |
| --- | --- | --- |
| `BAYRAM_CHECKOUTUZ_ENABLED` | `false` | **Controls sales only.** On with a blank key, the bot and the worker refuse to boot, and the error names `BAYRAM_CHECKOUTUZ_API_KEY`. |
| `BAYRAM_CHECKOUTUZ_API_KEY` | `""` | The merchant's Bearer key, from the checkout.uz dashboard. **This one setting drives settlement:** the poll cron is registered whenever it is non-blank, whatever the flag says. |
| `BAYRAM_CHECKOUTUZ_BASE_URL` | `https://checkout.uz/api/v1` | Override only if checkout.uz moves it. |
| `BAYRAM_CHECKOUTUZ_WEBHOOK_BASE_URL` | `https://pay.bayrambot.uz/checkoutuz/callback` | Sent as each payment's `webhook_url`. The bot appends `/<public_ref>` itself. |
| `BAYRAM_CHECKOUTUZ_RETURN_URL` | `https://t.me/BayramBot` | Where checkout.uz sends the customer after payment. |
| `BAYRAM_CHECKOUTUZ_POLL_MINUTES` | `5` (1..60) | The poll fires on minutes counted from :01, skipping any minute another cron already uses (`bayram.runtime.jobs.checkoutuz_poll_minutes`). |
| `BAYRAM_CHECKOUTUZ_POLL_BATCH` | `50` (1..500) | The maximum number of `status_payment` calls in one pass. The oldest-polled links go first, so a backlog is cleared over several passes. |

**Two other variables must be right before the flag goes on** `[TREE 2026-10-03]`:

- **`BAYRAM_CREDITS_ENFORCED=true`.** `bayram.main` refuses to boot when any rail can take money
  (`checkout_provider != stub` **or** `checkoutuz_enabled`) while the credit meter is dark. Set
  both in the same edit.
- **`BAYRAM_PAYME_IS_SANDBOX` does not matter to this rail.** The sandbox refusal still checks
  only `checkout_provider`, so a stub + checkout.uz production deployment boots with Payme
  unconfigured.

**The key must not reach any other process.** It is in `VENDOR_SECRET_FIELDS`, so in production
the admin API (`FORBIDDEN_ENV_VARS`) and the Payme gateway both refuse to boot if they can reach
it. Neither of them needs it: the gateway's webhook route only reads our own database and the
queue. Do **not** copy it into `/etc/bayram/payme.env` or `/etc/bayram/bayram-admin.env`.

> **One gap in the kernel-level separation, flagged rather than fixed.** The committed
> `deploy/systemd/bayram-payme.service` declares
> `InaccessiblePaths=/etc/bayram/bayram.env /etc/bayram/bayram-admin.env`, but the bot and worker
> units read `/etc/bayram/bot.env`, which that list does not name `[TREE 2026-10-03]`. The
> gateway is still protected at the application level, because it only reads
> `BAYRAM_PAYME_ENV_FILE` and refuses a reachable key. But the kernel-level block that
> `08-payme.md` §2 relies on does not cover the file holding this key. Before installing the key,
> check what the unit on the host actually says (`systemctl cat bayram-payme | grep Inaccessible`).

**How to install the key.** Edit the file in place as root, keeping its mode and owner, and
never paste the key into a shell command line:

```bash
sudoedit /etc/bayram/bot.env      # add BAYRAM_CHECKOUTUZ_API_KEY=… (and, at go-live, §9)
sudo systemctl restart bayram-worker bayram-bot
journalctl -u bayram-worker -f | grep checkoutuz.poll_finished   # one line per pass from the next poll minute
```

The worker registers the `run_checkoutuz_poll` cron only when the key is set. Once it is set, a
`checkoutuz.poll_finished` line appears at every scheduled minute, even when no link is open
(`"polled": 0`). No line at all means the worker has no key.

---

## 3. The public path: the tunnel must deliver `/checkoutuz/*` to the gateway

**All public traffic reaches this host through the Cloudflare Tunnel `aizu-vds`.** Origin ports
80 and 443 are filtered (`08-payme.md` §4). The tunnel's ingress is configured in the Cloudflare
Zero Trust dashboard (**Networks → Tunnels → `aizu-vds` → Published application routes**), not in
any file on the machine. So the one hard requirement is:

> **The tunnel ingress for `pay.bayrambot.uz` must deliver `POST /checkoutuz/*` to the gateway at
> `127.0.0.1:8091`.**

There are two ways to satisfy it, and which one applies depends on what the published route for
`pay.bayrambot.uz` points at today. Read the route in the dashboard before choosing.

`[HOST 2026-10-03]` Read in the dashboard: the route is `pay.bayrambot.uz`, path `*`, service
`http://127.0.0.1:80`. **A applies, and the tunnel needs no change.** The host Caddyfile then
still had only `handle /payme`, so a POST to `/checkoutuz/callback` got Caddy's 404 (and so does
`/rhmt/callback`).

**A. The route still ends at Caddy (`pay.bayrambot.uz → http://127.0.0.1:80`, as recorded in
`08-payme.md` §4.1 on 2026-09-10).** Caddy then has to forward the path. The committed site block
`deploy/caddy/pay.bayrambot.uz.caddy` now contains:

```caddy
handle /checkoutuz/* {
	reverse_proxy 127.0.0.1:8091
}
```

It sits before the catch-all `handle { respond 404 }`. The host's `/etc/caddy/Caddyfile` is a
single file with no `import`, so this block has to be **added to the host's copy by hand**, inside
the existing `http://pay.bayrambot.uz { … }` block. Then reload:

```bash
sudoedit /etc/caddy/Caddyfile
sudo -u caddy caddy validate --config /etc/caddy/Caddyfile   # NOT plain `sudo caddy validate`: §4.4 of 08
sudo systemctl reload caddy
```

**B. Add a path rule to the tunnel itself.** Add a published application route for
`pay.bayrambot.uz` with path `^/checkoutuz/` and service `http://127.0.0.1:8091`, placed **above**
the hostname-only route. Cloudflare matches routes top to bottom, and a catch-all placed first
takes everything. This skips Caddy for this one path, and it is the only option if the
hostname's route has been re-pointed straight at the gateway.

Either way, **keep the `http://` scheme on the Caddy site address.** A bare
`pay.bayrambot.uz { … }` turns on Caddy's automatic HTTPS, which answers every tunnelled request
with a `308` back to itself. That is the trap described in `08-payme.md` §4.3, and it would break
`/payme` and `/checkoutuz` together. checkout.uz does not retry, so a webhook that hits a 308 is
simply lost (the poll still settles the payment).

**Verify from outside, without `-L`.** It is the absence of `-L` that makes this check
informative:

```bash
curl -sS -w '\n%{http_code} -> %{redirect_url}\n' \
     -X POST https://pay.bayrambot.uz/checkoutuz/callback \
     -H 'Content-Type: application/json' -d '{}'
```

| Answer | Meaning |
| --- | --- |
| `{"ok":true}` then `200 ->` | Correct. The gateway answered. An empty body names no order, so nothing is enqueued. |
| `404 ->` (Caddy's empty 404) | The request reached Caddy and the handle is missing: do option A. |
| `404` from Cloudflare, or a `1033`/`530` page | The tunnel has no route for this path or host: do option B, or check the hostname route. |
| `308 -> https://pay.bayrambot.uz/…` | The §4.3 trap: a scheme-less site address. |
| `502` | The route is right but the gateway is down. The gateway only boots when Payme is enabled with a key (`_refuse_disabled_gateway`, `_refuse_a_blank_key`). See `DECISIONS.md D28`, known weakness 3. |

`/rhmt/*` is not touched by this change, and is still answered 404 by the committed Caddy block.
Whether Rahmat's callbacks reach the host is a separate open question.

**The webhook needs the Payme gateway process.** The route is mounted on `bayram.payme.app`, and
the gateway's lifespan always installs the checkout.uz webhook gate. A deployment that sells on
checkout.uz alone, with no Payme gateway running, has no webhook at all and settles through the
poll only. That is supported, not a fault.

---

## 4. The dashboard-global webhook (optional)

checkout.uz can also send every successful payment to one URL configured in its merchant
dashboard, in addition to the per-payment `webhook_url` this rail already sends.

- **It is not needed.** Every link we create already carries
  `https://pay.bayrambot.uz/checkoutuz/callback/<public_ref>`.
- **If you set one anyway, use the bare form, `https://pay.bayrambot.uz/checkoutuz/callback`.** A
  dashboard URL cannot carry a per-order path, and the bare route exists for exactly this case.
- **Duplicates are harmless.** The gate enqueues under a deterministic job id
  (`checkoutuz_reconcile:<order_id>`), so two webhooks for one payment queue one job, and the
  settlement's conditional `UPDATE`s make any further run a `replay`. A second webhook that
  arrives while the first job is still queued logs `checkoutuz.webhook_deduplicated`. The job
  keeps no result (`keep_result=0`), so a finished reconcile — an early or forged webhook that
  found the order `not_paid` — never blocks the real one that follows.
- **When the path's `public_ref` does not match the order's intent**, the call is logged as
  `checkoutuz.webhook_ref_mismatch`, treated as forged, and nothing is enqueued.

---

## 5. The IP whitelist on the key (optional, owner's call)

checkout.uz lets the merchant restrict the API key to a list of caller IPs. Whitelisting
narrows what a leaked key can do, but before turning it on:

- **The address to whitelist is the host's OUTBOUND address**, not anything Cloudflare shows.
  Inbound traffic comes through the tunnel, while outbound calls to `checkout.uz` leave through
  the host's own NAT. `00-host-inventory.md` records one CGNAT address on `ens18` and
  `192.166.228.52` as a provider NAT. Read the real outbound address from the host itself
  (`curl -s https://ifconfig.me`) and do not assume it.
- **A whitelisted key works only from that host.** A test from a developer machine (§9) will be
  refused. checkout.uz's error is then a 4xx from `create_payment`, which the bot logs as
  `checkoutuz.create_failed` and shows the customer as a checkout error.
- **If the provider renumbers the NAT, the rail stops selling and stops settling at the same
  moment.** Every `status_payment` call fails, which appears as `checkoutuz.status_unavailable`
  and `retry_later` in every `checkoutuz.poll_finished` line. Payments are not lost: they
  settle once the whitelist is corrected, provided that happens within 24 hours of each link's
  end — the final check keeps re-asking an order it cannot get an answer about until then, and
  only then closes it with `checkoutuz.final_check_unresolved`. After that, recover them by
  hand (§7.2).

---

## 6. The owner's per-rail switch

The admin panel's **Payments** screen has a **Payment rails** panel with one row each for
Rahmat, Payme and checkout.uz:

- **Every role can see each row.** It shows On or Off, and a "Not live in env" badge when the
  bot's last boot did not wire that rail.
- **Only the OWNER can flip a switch** (`CONFIG_MANAGE`, `POST /api/config/checkout-rails`). It
  requires a reason, writes one `CONFIG_COMMIT` audit row with
  `subject_id = checkout_rail:<rail>:on` or `…:off` (the direction is in the row, because the
  Redis value is overwritten by the next flip) plus the client IP, and needs no restart.

| What the switch does | What it does not do |
| --- | --- |
| Hides that rail's button on the paywall and in `/balance` from the next screen drawn. | Touch settlement. A link already handed out still settles and is credited. |
| Refuses a stale press. Rahmat and Payme show the "payments are paused" copy, because the switch is composed into their `paused`. checkout.uz shows its own `checkout.rail_disabled` copy. | Override the env. A rail the env does not wire stays off whatever the switch says. |
| When every rail is off, the paywall keeps its price text, adds `checkout.unavailable`, and draws no price button. | Override the global pause. The pause still wins over a switch that is on. |

Storage `[TREE 2026-10-03]`:

- **Each switch** is the Redis key `bayram:config:checkout_rail:<rail>`, written as an explicit
  `"1"` or `"0"`, never deleted.
- **Missing keys and errors fail open.** A missing key, an unrecognised value or a Redis error
  all read as **on**, the same way the Payme pause fails open.
- **The "Not live in env" badge** comes from `bayram:checkout:wired_rails`, which the bot
  publishes at every boot (comma-joined, no TTL). An empty value means a stub deployment. A
  missing key means the bot has not booted since this change: the panel then shows no badge and
  says the wiring is unknown.

**Read it from a shell**, against the queue's Redis (the instance `BAYRAM_REDIS_URL` names):

```bash
redis-cli MGET bayram:config:checkout_rail:rhmt bayram:config:checkout_rail:payme \
               bayram:config:checkout_rail:checkoutuz bayram:checkout:wired_rails
```

**There is no CLI writer.** Use the panel, so the change carries a reason and an audit row.
Setting the key by hand with `redis-cli SET … 0` works, but it leaves no audit trail. If you do
it in an emergency, write `"0"` or `"1"` and never `DEL`.

---

## 7. Confirming a payment by hand

### 7.1 Ask checkout.uz what it thinks

Use this when a customer says they paid and the bot disagrees. Find the order first (the
database name is `hbd` on this host, unchanged by the rename):

```bash
sudo -u postgres psql -d hbd -c "
  select p.order_id, p.state, p.amount_som, p.link_valid_until, p.last_polled_at, p.paid_at,
         i.public_ref, i.state as intent_state, i.amount_minor, i.settle_note
    from checkoutuz_payments p join payment_intents i on i.id = p.intent_id
   where i.public_ref = '<public_ref>'          -- or: p.order_id = <id>
   order by p.created_at"
```

Then ask checkout.uz. The key is read into a variable, so it never appears on a command line or
in shell history:

```bash
KEY=$(sudo sed -n 's/^BAYRAM_CHECKOUTUZ_API_KEY=//p' /etc/bayram/bot.env)
curl -sS -X POST https://checkout.uz/api/v1/status_payment \
     -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
     -d '{"id": <order_id>}'
unset KEY
```

A paid answer looks like
`{"status":"success","data":{"id":152,"amount":50000,"status":"paid",…}}`. Here `amount` is in
**soʻm**, and it must equal `amount_som`, which must equal `amount_minor / 100`.

| Our row | checkout.uz says | What to do |
| --- | --- | --- |
| `pending` | `paid` | Nothing. The next poll settles it (within `POLL_MINUTES`). If it does not, read the worker's `checkoutuz.poll_finished` and `checkoutuz.status_unavailable` lines. |
| `pending` | `pending` | The customer has not paid on this link. Check the other links on the same intent. |
| `paid` | `paid` | Settled. Check that `settle_note = 'checkoutuz:<order_id>'` and that the notification went out (it is the same job as for Payme). |
| `orphan_paid` | `paid` | A double payment or an amount mismatch: §8. |
| `expired` | `paid` | **Paid after the final check**: §7.2. |

### 7.2 A link paid after it was closed as `expired`

The poll asks about a link one last time 15 minutes after its hour, then closes it. If someone
pays on a page left open longer than that, checkout.uz takes the money and our row says
`expired`. **If the webhook arrives, nothing is needed**: the gate still queues a reconcile for an
`expired` link (WARNING `checkoutuz.webhook_after_expiry`), the settlement asks checkout.uz and,
on `paid`, moves the link `expired -> paid` and grants as usual, logging ERROR
`checkoutuz.paid_after_expiry` so the case is seen. If the webhook was lost (it is never
retried), no poll looks at the row again and no log line records it; the customer's message is
usually the first signal, and the procedure below applies.

The one exception is a link the final check could never get an answer about: it is closed
`expired` 24 hours after its end with an ERROR `checkoutuz.final_check_unresolved` carrying the
`order_id`. Every such line needs §7.1 for that order, and this section if it shows `paid`.

The settlement can handle this payment. To let it run without a webhook, put the one row back
to `pending`. The next poll's final-check arm then asks checkout.uz once more and settles it. That
settlement still runs all of D28's checks, and the intent is claimable even if it has expired:

```bash
sudo -u postgres psql -d hbd -c "
  update checkoutuz_payments set state = 'pending'
   where order_id = <order_id> and state = 'expired'"
```

**This procedure has not been rehearsed** `[TREE 2026-10-03]`. Run it only after §7.1 has shown
`paid` at checkout.uz for that exact `order_id`, and record the case.

If the intent was meanwhile paid through another link, the settlement records the row as
`orphan_paid` and grants nothing, which is correct: refund it as in §8.

---

## 8. `orphan_paid` and amount mismatches: the manual refund runbook

In both cases checkout.uz holds real money and **nothing was granted**. The settlement closed the
link as `orphan_paid` instead of crediting the customer twice or crediting the wrong amount.
So, unlike `08-payme.md` §7, there is **no credit to take back**. The only action is the refund.

| Log event (worker, ERROR) | What happened |
| --- | --- |
| `checkoutuz.double_payment` | The customer paid two links of one purchase. The first settled the intent and this one is the second. |
| `checkoutuz.amount_mismatch` | checkout.uz confirmed `paid` for an amount other than the one we stored. Nothing was granted. |

**Find them:**

```bash
journalctl -u bayram-worker --since '-7 days' | grep -E 'checkoutuz\.(double_payment|amount_mismatch)'
sudo -u postgres psql -d hbd -c "select order_id, amount_som, paid_at, intent_id
                                   from checkoutuz_payments where state = 'orphan_paid'
                                   order by paid_at"
```

**Refund each one:**

1. **Confirm at checkout.uz** with §7.1 that the order really is `paid`, and note the amount.
2. **Refund in the checkout.uz merchant dashboard.** This repository has no refund call, and
   checkout.uz's API documents none.
3. **Record the refund** where accounting lives. `checkoutuz_payments` keeps `orphan_paid`
   forever — the FK to `payment_intents` is `ON DELETE RESTRICT` and the 400-day intent purge
   skips any intent with a `paid` or `orphan_paid` link; there is no `refunded` state, by design, in the same way `08-payme.md` §7 step 5
   keeps refunds out of `topup_purchases`.
4. **Tell the customer.** The intent's `public_ref` leads to the buyer the same way it does for
   a Payme case.

The refund process and SLA are not yet decided by the owner. Until they are, the default is to
refund every `orphan_paid` row within one business day of it appearing.

**Other `checkoutuz.*` events worth an alert rule** `[TREE 2026-10-03]`:

| Event | Level | Meaning |
| --- | --- | --- |
| `checkoutuz.payment_unrecorded` | ERROR (bot) | checkout.uz created a payment that we could not store. The link was **not** shown to the customer. The log line carries the `order_id`. Normally no one can pay it, but if §7.1 ever shows it `paid`, refund it. |
| `checkoutuz.amount_echo_mismatch` | ERROR (bot) | `create_payment` echoed a different amount from the one we asked for. The page was withheld. Investigate before selling further. |
| `checkoutuz.foreign_intent` | ERROR (worker) | An order's intent belongs to another rail. This should be impossible. |
| `checkoutuz.expire_failed` | ERROR (worker) | The final check could not close a lapsed link. It is retried on the next pass. |
| `checkoutuz.status_unavailable` | WARNING, or ERROR when the error is not retryable | checkout.uz did not answer `status_payment`. Persistent occurrences mean the key, the whitelist (§5) or the vendor itself. At ERROR (4xx, malformed reply, an answer about another order) asking again will not help: check the order with §7.1. |
| `checkoutuz.final_check_unresolved` | ERROR (worker) | A lapsed link checkout.uz never answered for, 24 hours after its end, was closed `expired` **unverified**. Check the `order_id` with §7.1; if `paid`, §7.2. |
| `checkoutuz.paid_after_expiry` | ERROR (worker) | A link already closed `expired` was confirmed paid by checkout.uz and has been settled and granted (§7.2). No action unless the intent was already paid, which shows separately as `checkoutuz.double_payment`. |
| `checkoutuz.webhook_after_expiry` | WARNING (gateway) | A webhook named a link already closed `expired`; a reconcile was queued. Forged ones cost one `status_payment` call and grant nothing. |
| `checkoutuz.paid_after_forget` | WARNING | Paid for a buyer whose data has since been erased. The intent settled and nothing could be granted. |
| `checkoutuz.webhook_ref_mismatch`, `…_foreign_intent` | WARNING (gateway) | Forged or confused webhooks. Expect a few. |
| `checkoutuz.poll_finished` | INFO | One line per pass: `polled`, `settled`, `not_paid`, `retry_later`, `orphaned`, `mismatched`, `final_checked`, `expired`, `unresolved`, `faults`, `duration_ms`. Non-zero `unresolved` means §7.2. Non-zero `orphaned` or `mismatched` means §8; a run of non-zero `retry_later` means §5 or §7.1. |

---

## 9. Switching the rail on

The order matters, because the edge and the key have to be in place before a button exists.

1. **Release a build that contains migration 0030.** This is an ordinary `bayram-release
   deploy` (`11-ci-cd.md`), because the migration is additive. Check it:
   `sudo -u postgres psql -d hbd -Atc "select version_num from alembic_version"` must print
   `0030`.
2. **Route the edge** (§3) and verify it with the `curl` in §3. This is safe to do days ahead,
   because the route only enqueues for orders on file.
3. **Install the key with the flag still `false`** (§2) and restart the worker and the bot. The
   poll now runs and finds nothing. On the panel, checkout.uz shows "Not live in env".
4. **Decide the whitelist** (§5), and apply it before step 6 if it is wanted.
5. **Set `BAYRAM_CHECKOUTUZ_ENABLED=true`** and, if it is not already set,
   `BAYRAM_CREDITS_ENFORCED=true` in `/etc/bayram/bot.env`. Restart `bayram-worker` and
   `bayram-bot`. The bot's boot publishes `…,checkoutuz` to `bayram:checkout:wired_rails`. The
   panel badge clears. The paywall shows "💸 Click/Payme …" after any Rahmat and Payme buttons.
6. **The first live payment, at the 1 000 soʻm floor, with the owner's explicit yes.** The
   planned cost is one payment of 1 000 soʻm, refunded afterwards. The production price
   (15 000 soʻm) cannot be lowered for one test without lowering it for every customer, so the
   floor test runs:
   - **on a separate test deployment.** This is a dev bot with its own
     token and database, `BAYRAM_SINGLE_SONG_PRICE_MINOR=100000`, the real key, and a worker
     running. A test machine has no public webhook, so this rehearses the poll path only. A
     whitelisted key (§5) refuses such a machine.
   - **or, if the owner prefers to test the full production path including the webhook, as one
     real purchase at the production price**, refunded afterwards. That is a different cost and
     needs its own yes.

   Either way, before the money moves, ask for and record the owner's yes with the count (1) and
   the cost (the amount, refunded afterwards). Then:
   - press the button;
   - pay on checkout.uz;
   - watch `journalctl -u bayram-payme -u bayram-worker -f | grep checkoutuz` for
     `webhook_enqueued`, then `settled`;
   - confirm the receipt in the panel and the "payment went through" message in the chat;
   - refund (§8 step 2).
7. **Write `[HOST <date>]` marks into this page** for each step that has actually been done.

---

## 10. Switching it off

| How hard | Do | Effect |
| --- | --- | --- |
| Soft, no restart | The owner turns **checkout.uz** off in the panel (§6). | The button disappears and a stale press is refused. Links already issued still settle. |
| Hard | `BAYRAM_CHECKOUTUZ_ENABLED=false`, then restart the bot and the worker. | The rail is no longer wired. The poll **keeps running** as long as the key is set. |
| Gone | Remove the key, then restart. | The poll is no longer registered. **Do this only one hour plus 15 minutes after the last link was issued**, or a link still in flight can be paid and never settled. Find the last one with `select max(created_at) from checkoutuz_payments`. |

No drain procedure is needed beyond that wait. That is why settlement depends on the key and not
on the flag (`DECISIONS.md D28`, rule 12).

---

## 11. Symptoms

| Symptom | Most likely cause | Check |
| --- | --- | --- |
| The bot will not boot: "CHECKOUTUZ_ENABLED is on but CHECKOUTUZ_API_KEY is empty" | The flag was set without the key. | §2. |
| The bot will not boot: "… but BAYRAM_CREDITS_ENFORCED is false" | The flag was turned on with the meter dark. | Set `BAYRAM_CREDITS_ENFORCED=true` in the same edit. |
| The admin or the gateway will not boot in prod, naming `BAYRAM_CHECKOUTUZ_API_KEY` | The key was copied into their env. | Remove it. It belongs in `bot.env` only. |
| No checkout.uz button | The flag is off, the owner switch is off, the checkout is paused, or the bot has not restarted. | The panel's Payment rails row; `redis-cli GET bayram:checkout:wired_rails`. |
| The customer sees "This payment method is not available right now" | The owner switch is off and the button was stale. | §6. |
| A price button gives a checkout error and the log says `checkoutuz.unpayable_amount` | The price is not whole soʻm or is outside 1 000..10 000 000. | The price settings, in tiyin. |
| Payments settle about 5 minutes late, never sooner | The webhook is not arriving: the edge route is missing, there is a 308, or no gateway is running. | §3 `curl`. |
| Payments never settle, and `poll_finished` shows non-zero `retry_later` | The key is wrong or revoked, the whitelist is wrong, or checkout.uz is down. | §7.1 by hand; §5. |
| No `checkoutuz.poll_finished` lines at all | The key is blank in the **worker's** env, or the worker did not restart. | §2. |
| `receipts_over` alarm after a checkout.uz sale | A build that predates the D28 `settlement_counts` filter. | Release. |
