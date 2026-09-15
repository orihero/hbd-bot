# SUPPORT_TICKETS_SPEC — the ticket queue behind the ⚠️ button

**Migration head when this was written:** `0026`; this feature is revision **`0027`**. Cite this
document by section — `SUPPORT_TICKETS_SPEC §3.3` — never by path, so the citation survives the
file moving.

**What changes.** The post-delivery "⚠️ Something is wrong" button has, until now, rendered a
sentence and written nothing. A customer who pressed it was told where to write; whatever they
wrote landed in a chat nobody owned. There was no row, so there was no reference to quote back, no
queue to work, no way to answer "how many people told us the name was wrong last month?", and no
way for two staff to avoid answering the same person twice. This specification turns that button
into a ticket: a row, a formatted card in a Telegram support group where staff triage **and answer
the customer without leaving the group**, and a four-column Kanban board in the admin panel.

**The ticket body is kept indefinitely and erased only on request.** There is no retention clock on
either table and no `*_expires_at` column anywhere in this feature. §7.2 makes that argument in
full and names what it obliges; it is the one position in this document that a reviewer should
read before the schema.

---

## 0. Ground truth this specification is built on

Facts established by reconnaissance over this repository and re-verified before filing. Each one
closes a design option that would otherwise look reasonable.

| Fact | Consequence |
| --- | --- |
| `post_delivery_keyboard`'s only caller is `bayram/bot/delivery.py::_closing_message`, which runs **inside the ARQ worker** | The ⚠️ button is drawn by the worker, at the one moment `kit.order_id` and the button exist together. The order id must travel in the callback payload (§1.3). |
| `navigation`'s handlers are deliberately **not** state-filtered; ⚠️ is reachable from a month-old delivery message | `state.set_state(...)` would clobber a half-finished wizard. The flow is DB-backed and FSM-free (§1.2). |
| Alembic head is `0026`, ids are hand-set 4-digit serials | The new revision is `0027`; `down_revision = "0026"` (§2.4). |
| `enum_type()` renders a plain `VARCHAR(32)` with `create_constraint` off | Adding a fifth status later needs **no migration**. Said in the migration docstring, or a reviewer asks for a follow-up revision that is not needed. |
| `retry_jobs=True` and SIGTERM cancels running jobs, so every job replays on every deploy | "This card was posted" must live in the row, never in the job. Hence the `group_chat_id`/`group_message_id` latch (§3.3), the shape revision `0026` gave `payment_intents.resumed_at`. |
| Only the **bot** process receives updates; the worker's `Bot` is send-only | Both group directions — the staffer's reply and the two inline buttons — are bot-process routers (§3.5). |
| `bayram.admin.*` may not import `bayram.runtime.*`, and `tests/test_admin/test_queue.py::test_the_seam_can_reach_nothing_that_sends_a_message` reads `queue.py`'s imports | A panel-side reply is an **enqueue**, never a send. Job names are restated in `queue.py` as literals with a paired test (§5.5). |
| `AdminQueue` / `ArqAdminQueue` already exist — D12 built the admin→ARQ seam for broadcasts | This feature adds two methods to an existing port, not a new pool. |
| `db/admin/audit.py:SUBJECT_TYPES` is a **closed** frozenset; a missing member raises inside `append`, which `audit_sink` swallows and retries with `subject_id=None, ip=None` | A forgotten `"ticket"` member is a 200 with an audit row that lost its subject — silent. Add it first (§7.4). |
| `require_permission` → `check_role` holds no subject and therefore no grant | A step-up permission used as a **router** guard returns `STEP_UP_REQUIRED` unconditionally and for ever. Neither permission here carries a step-up (§5.1). |
| The SPA's client is `"GET" \| "POST"` only | Every mutation is a POST (§5.2). |
| `ORDER_STATE_COUNTS_PATH` carries the warning verbatim: a literal path registered after a `{param}` path 422s on a malformed UUID | `/board` is declared **before** `/{ticket_id}` (§5.2). |
| `translate()` falls back across four locales and the locale-contract AST scan holds all four catalogues in step | Staff copy must never enter the customer catalogues; the card is built from plain English literals in its own module (§3.1). |
| Telegram rate-limits **one group** at ~20 messages/minute, far tighter than the ~30/s across different chats `BAYRAM_BROADCAST_SEND_RATE_PER_S=12` is sized against; the shared `SendPacer` bucket meters the **token** | A burst of tickets into one group earns a `retry_after` on the bot token, which stops customer **orders**. Group posts are paced on their own key (§3.4). |
| `ChatRecorder.offer()` is explicitly lossy and `flush_batch` swallows every exception | The complaint is never persisted through chat logging. A silently dropped complaint is worse than no ⚠️ button (§1.5). |
| No drag-and-drop library is installed in either SPA; `ConfirmDialog.tsx` argues the no-dependency position by name | The board uses the native HTML5 DnD API plus a real keyboard path (§6.2). |
| `tests/test_db/test_privacy_constraints.py`'s two sets are "on a clock" and "erased on request (a full reset to first-contact state)" | Neither fits. The support tables take the third route, with a written paragraph (§7.2). |

**One conflict, resolved.** `/support` already exists as a command that prints
`settings.support_contact`, and the ⚠️ button already exists as a nav callback. Building the ticket
flow behind only one of them would leave two routes to one inbox that describe themselves
differently — which is precisely the divergence `common.support_text` was extracted to prevent. So
**both doors file the same kind of ticket**, and the door is recorded on the row rather than
branched on (§1.1).

---

## 1. THE CUSTOMER FLOW

### 1.1 The two doors, and why they converge

| Door | Where it is drawn | `source` | `order_id` |
| --- | --- | --- | --- |
| ⚠️ **Something is wrong** | `post_delivery_keyboard`, under a delivered song, drawn by the worker | `delivery_button` | the delivered order |
| `/support` | typed from anywhere, at any time | `support_command` | NULL |

Both write a `support_tickets` row, both ask the same question, both confirm with the same
`public_ref`. `SupportTicketSource` exists to answer "where do complaints come from?" and to explain
why half the rows have a NULL `order_id` — **it is never branched on afterwards.** A second inbox
keyed off that value is the divergence this design exists to prevent.

`/support` **stays in `gate.ERASURE_COMMANDS`**, so a customer whose account is blocked can still
open a ticket by typing the command — the same carve-out `/privacy` and `/forget` have, for the same
reason: a blocked customer must always be able to reach a human. **The ⚠️ button does not join that
carve-out.** It is a callback on a keyboard, it is reachable only from a message we sent, and
widening the erasure exemption to callbacks would take a curated list of three commands and make it
a shape.

**A carve-out on the command alone is not enough, and shipping it that way closed a loop.** A ticket
is OPENED by a command and DESCRIBED by an ordinary message. The description is not a command, so
`_is_erasure_request` answered `False`, the block gate refused it with `error.blocked` — whose copy
reads *"send /support and tell me about it"* — and the customer obeyed, got another prompt, and was
refused again. Each turn burned one of the three undescribed tickets §1.4 allows, so after three
turns the account held three empty tickets nobody had been told about and could not reach support at
all. So **a message that is a reply to one of the bot's own messages passes the block wall too**
(`gate._is_answer_to_the_bot`, checkable from the update alone: the middleware runs inside the FSM
isolation lock and may not read the database). It is bounded three ways and the argument is in that
function's docstring: it does not cover callbacks, so a blocked account still cannot walk the wizard
— which is reached and walked entirely by buttons; `handlers.confirm` still refuses a blocked
account at the confirm screen; and unlike the three commands it is NOT exempt from the ordinary
throttle, because `erasure_max_updates` is a three-a-minute budget that exists only because those
commands skip the ordinary meter, and putting a customer's typed sentences on it would tighten the
limit on everybody in order to loosen it for the blocked.

`NavAction.REPORT_PROBLEM` **keeps its member and stays registered to a handler.**
`test_every_nav_action_is_registered_to_a_handler` AST-walks `.register(` calls, and a drawn-but-
unregistered action is exactly how `TRY_AGAIN` once shipped. It remains the order-less door on the
degraded delivery screen — and it now opens a ticket too, with `order_id` NULL.

### 1.2 The flow is DB-backed and FSM-free, and that is the central bot decision

`navigation`'s handlers are deliberately not state-filtered. ⚠️ can be tapped from a month-old
delivery message while a **new** wizard is half-finished, so `state.set_state(SupportFlow.waiting)`
would silently destroy a draft the customer is in the middle of. There is therefore no FSM state for
this feature at all:

1. **Tap ⚠️** → INSERT a row (`status=new`, `body=NULL`, `described_at=NULL`, `order_id` from the
   callback payload) → reply with a **`ForceReply`** prompt sent as a **new** message via
   `common.say` → store that prompt's `message_id` on the row as `prompt_message_id`.
2. **The customer answers.** A private message whose `reply_to_message.message_id` equals some row's
   `prompt_message_id` **for that account** resolves to that ticket, described or not, and the
   handler branches on `described_at`:
   - **undescribed** → fill `body`, stamp `described_at`, write a `described` event, post the card
     to the group (§3), confirm with the `public_ref`;
   - **described** → it is a FOLLOW-UP: append a `reply` event with `author_kind=customer`, relay it
     into the group as a threaded reply to the card, apply `REOPEN_STATUS` (§4.2), and acknowledge
     from the reference the customer already holds. A follow-up never mints a second ticket.
3. **`/support`** does the same with `source=support_command` and no `order_id`.

> **Superseded.** Step 2 first read "fills `body`, stamps `described_at`, …" with no branch, and the
> lookup behind it (`db/support_tickets.find_by_prompt`) carried `described_at IS NULL`. That made
> the relay's own closing sentence — *"Reply here if there is more to say"* (§1.6) — an invitation
> to a dead end: a customer's follow-up matched no ticket, fell past the support router, and was
> claimed by whichever wizard step they were parked in. At `Wizard.name` it was stored as the
> RECIPIENT'S NAME and the pipeline sang it; at `Wizard.note` it became free text about a real third
> party. The as-built branch above is the correction. The protection the narrowing was credited with
> is not lost and never lived in the lookup: `describe`'s own `WHERE described_at IS NULL` is what
> stops a second message overwriting the first complaint, and that is where it belongs, because that
> is the statement which would do the overwriting.

The prompt is a **new message and never an edit over the closing message**: that message carries the
customer's order reference and their "make another" button, and editing it away to ask a question
destroys the one screen they were told to keep.

Because the match is "is a reply to *that* message", ordinary wizard input is never swallowed. There
is nothing to add to `bot/draft.py`'s nine-key list and nothing for `clear_keeping_identity` to
drop. `prompt_message_id` is **not** cleared once answered — it is also the evidence of which prompt
a late reply belongs to when a customer answers two of them out of order.

**Read `prompt_message_id` as "the message this ticket is currently listening on"**, not as "the
ForceReply we sent once. It is re-pointed, unconditionally, at two moments: when a staff or operator
reply is relayed to the customer — **both doors, the group's (§3.5) and the panel's (§3.5b)** — and
when a customer at the undescribed ceiling is handed back the ticket they already hold (§1.4). `db/support_tickets` therefore has two writers of that one
column and they differ in exactly one way — `attach_prompt` is conditional on the column being NULL,
so a replayed open cannot orphan a prompt the customer can still see; `listen_on` is unconditional,
because a newer message has taken over the conversation and the only message that can resolve is the
one on their screen. Merging them breaks one case or the other. **No new column is needed for any of
this**, which is why there is none.

**The support router's MESSAGE observer must NOT stand down for `Wizard.submitting`; its CALLBACK
observer must.** The stand-down belongs to CATCH-ALLS — `onboarding` claims every update from an
un-onboarded account and `menu` claims any text equal to a reply-keyboard label, so either could
swallow the park `handlers/submitting.py` owns and blind `order_in_flight`. The support router's one
message registration is not a catch-all: it is filtered on "a ticket of this account's is listening
on the message this is a reply to", which no wizard input can satisfy.

> **Superseded.** This section first required the stand-down on **both** observers, "the way
> `onboarding` and `menu` do", and it shipped that way. The defensive filter guarded a state its
> handler could not have harmed, and it cost a real flow: a customer who typed `/support` during a
> render got the prompt (`commands` is registered above everything, so the command always worked)
> and their answer was then swallowed by `submitting.handle_message_while_working` — a ticket
> opened, prompted, and deafened, leaving an undescribed row that counted against their own quota.
> The callback half of the rule stands unchanged: ⚠️ pressed mid-render still answers
> `wizard.queued`, because a tap that opens no ticket loses nothing the customer typed.

### 1.3 The callback data

A **new** `SupportCB(CallbackData, prefix="sup")` with `action: SupportAction` and `order: str` — the
order UUID hex, or `"-"` for none. `sup:open:<32 hex>` is 41 of Telegram's 64 bytes.

**Do not add a field to `NavCB`.** That would change the wire format of every existing nav button,
including buttons already sitting in customers' chat histories.

`SupportAction`: `OPEN` (the customer's tap), `CLAIM` and `RESOLVE` (staff, in the group).

### 1.4 Rate limiting — one tap is a write amplifier

One tap writes a row **and** sends a message to a group. That is the unmetered amplification
`InboundPolicy.erasure_max_updates` was added for, and it must be metered per account:

The ceiling is `bayram.support.SupportQuota`, resolved through `resolve_support_quota(settings)` so
the two numbers are named once:

- **At most 3 undescribed tickets held at once** (`body IS NULL`). A customer who taps ⚠️ four times
  without typing gets the prompt for the ticket they already have, not a fourth row. **This ceiling
  is NOT a refusal**: `latest_undescribed_ticket` reads back their newest undescribed, not-resolved
  row, a fresh `ForceReply` goes out carrying `support.ticket.still_open` and its reference, and
  `listen_on` re-points the ticket at that new prompt — the older one is scrolled away and only the
  message on screen can resolve. If no row comes back for a count that said there was one, the open
  path falls through and mints the ticket anyway: one row over the line is the cheap error and a
  customer left holding a refusal we cannot justify is the expensive one.
- **At most 5 tickets opened per day.** **This ceiling IS the refusal** (`support.ticket.too_many`).
  A sixth ticket in a UTC day is a script rather than a person with six problems, and unlike the
  ceiling above there is nothing useful to hand back — the five they opened today may all be
  described and working.

> **Superseded.** The first build read `TicketQuotaVerdict.is_allowed` alone and answered BOTH
> ceilings with `support.ticket.too_many`, which contradicted this section's own rule and mattered
> most to the customer least able to work around it. `/support` is in `gate.ERASURE_COMMANDS`, so a
> BLOCKED account could open tickets; its descriptions were refused by the block gate (§1.1); and
> after three taps it was over the undescribed ceiling and locked out of support permanently. The
> verdict now carries `is_holding_too_many` and `is_over_daily` as separate questions, because the
> two ceilings mean different things and deserve opposite answers.

`InMemoryWindowCounterStore` is per-process and resets on redeploy, so if the ceiling is load-bearing
rather than advisory it belongs in a durable row-backed counter in the style of
`bayram.lyric_budget.LyricBudgetStore` / `db.lyric_budget.SqlLyricBudget`. A refusal is answered in
the customer's language and names the reference of the ticket they already hold — never a bare
"try again later", which reads as the product being broken on the one screen where the customer is
already telling us it is.

### 1.5 Ports, and what must not be imported

`BotDeps` has **no** session factory, **no** repository and **no** ARQ pool. Adding a write means
four things and only four: a port `Protocol`, an `Sql*` implementation under `src/bayram/db/`, a
container field, and one wiring line in `main.py`.

**Do not import `bayram.db` into a shared bot module.** `handlers/common.py` guards its single such
import behind `if TYPE_CHECKING:` with a paragraph explaining that SQLAlchemy must not enter through
the module every handler imports.

**The body is never persisted through `ChatRecorder`.** `offer()` returns `False` when its bounded
queue is full and `flush_batch` swallows every exception — both correct for a chat log and both
fatal for a complaint. Chat logging still captures the message incidentally; that is fine, and it is
not the ticket's record.

### 1.6 Copy

Customer-facing strings — the prompt, the confirmation carrying the reference, the rate-limit
refusal, the relay prefix — are ordinary catalogue keys in all four locales, and every one of them
enrols itself in `test_every_key_the_code_renders_is_defined_in_every_catalogue` (§8). **Staff copy
is not.** The card is English literals in its own module; §3.1 argues why.

**Eight keys, not six.** `support.ticket.` `prompt` · `still_open` · `filed` · `already_filed` ·
`too_many` · `unavailable` · `reply` · `follow_up`. The two added after the first build are
`still_open` (the re-prompt at the undescribed ceiling, §1.4) and `follow_up` (the acknowledgement a
customer's second message gets, §1.2 step 2) — both of them the copy a customer sees on a path that
previously had no copy because it had no code. `too_many` was reworded at the same time: it is now
the DAILY refusal only, and saying "that is as many open tickets as I can hold" on a screen that is
really about a per-day ceiling would send a customer to close tickets they cannot close.

---

## 2. DATA MODEL

Two tables, one migration. Revision `0027` carries the whole feature; there is no second revision
and no column on `purge_runs`, because nothing sweeps these tables (§7.2).

### 2.1 `support_tickets` — the complaint, and where it is now

`src/bayram/db/models/support_ticket.py`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `sa.Uuid` PK default `uuid4` | |
| `public_ref` | `String(12)` NOT NULL **UNIQUE** | The reference a customer reads down a phone line. **The leading 8 characters of the ticket id itself, lowercase** — `bayram.support.public_ref_for`, which is `delivery.order_reference`'s rule one domain along: a reference support reproduces *by reading* the id in a log or an error context, never by computing it, and never by case-folding it before pasting it into a `WHERE` clause. Unique because a reference resolving to two tickets is worse than no reference: support answers about the wrong complaint while believing they looked it up. Eight hex characters can collide in principle, so the row is minted **against the unique index** rather than trusting the arithmetic (`mint_ticket_identity`). `unique=True, index=True` builds one unique index, the `payment_intents.public_ref` shape. The column is 12 so a longer shape — a group prefix, a check character — can be minted later without a migration. |
| `telegram_user_id` | `BigInteger` **NOT NULL**, indexed | Not nullable-for-erasure — the departure from every other table holding this id, argued in §7.2. Indexed for the erasure `DELETE` first and the per-account history second. |
| `language` | `enum_type(Language)` NOT NULL | The locale the ticket was opened in. Stored rather than re-read from `users`: the relay must answer in the language they complained in, on the one message where being understood is the entire point. |
| `source` | `enum_type(SupportTicketSource)` NOT NULL | §1.1. |
| `order_id` | `sa.Uuid` NULL, FK `orders.id` **ON DELETE SET NULL**, indexed | Matching `generation_attempts.order_id` exactly. A cascade would make retention on `orders` into an undeclared retention policy on complaints. |
| `status` | `enum_type(SupportTicketStatus)` NOT NULL, default `NEW` | Defaulted in the mapper — a ticket has exactly one birth state, written by the customer's tap. Every later move is an explicit conditional `UPDATE` naming both ends (§4.2). |
| `body` | `String(4096)` NULL | The customer's own words, unedited. NULL until they answer. 4096 is Telegram's own single-message ceiling, so the column cannot truncate a complaint that was actually made. |
| `prompt_message_id` | `BigInteger` NULL | **The message this ticket is currently listening on** (§1.2) — the ForceReply prompt at first, then the relay of each answer we send, then a re-prompt if one goes out. Two writers: `attach_prompt` (conditional on NULL) and `listen_on` (unconditional). Reading it as "the ForceReply we sent once" is what made a customer's follow-up unroutable. |
| `described_at` | `UtcDateTime` NULL | Set when `body` arrives. **NULL means the customer tapped and never typed.** Those rows are real data and are excluded from the board (§4.3), never deleted. |
| `assigned_admin_username` | `String(ACTOR_USERNAME_LENGTH)` NULL | Denormalised with no FK, as `admin_audit_log` denormalises its actor: a rename must not rewrite history. |
| `assigned_at` | `UtcDateTime` NULL | Separate from `status`, because a ticket can be claimed without being moved and moved without being claimed. |
| `group_chat_id` | `BigInteger` NULL | NULL when the group is unconfigured, or when Telegram refused and the post is still owed. |
| `group_message_id` | `BigInteger` NULL | The card's message id, and the ticket's half of the two-way reply. The pair with `group_chat_id` is the **once-only latch** (§3.3), and it is the **pair** that carries the uniqueness — see the index list below. No uniqueness and no index on this column alone. |
| `group_posted_at` | `UtcDateTime` NULL | Settled **after** the Telegram call returns. A row with a message id and no clock is a send that crashed mid-flight and is worth looking at. |
| `resolved_at` | `UtcDateTime` NULL | **Not cleared on a reopen.** It records that this ticket was once considered finished, which is the most useful thing to know about a ticket that came back; clearing it would make repeat complaints invisible (`orders.delivered_at`'s rule). |
| `created_at` / `updated_at` | `TimestampMixin` | Used here, unlike on this package's append-only tables: this row is a state machine, so `updated_at` is true and load-bearing — it is what a "nothing has happened here for four days" filter reads. |

**Index, hand-named** — the migration must spell it identically, because
`test_the_migrated_indexes_match_the_model_metadata` compares index **names**:

```
ix_support_tickets_status_created_at_id              (status, created_at, id)
ix_support_tickets_group_chat_id_group_message_id    (group_chat_id, group_message_id) UNIQUE
```

`id` is the third column and not an afterthought: without it Postgres adds an
`Incremental Sort … Presorted Key: created_at` on every keyset page, and the sort buffer grows with
the tie group — which a burst of tickets from one outage is made of. `ix_orders_state_created_at` is
the exemplar. A single-column index on `status` would be
redundant with this one's leading column (the "three unused read indexes shipped" mistake revision
`0012` had to reconcile), and `described_at` gets none at all, because the board only ever filters on
it alongside a status equality this index has already narrowed to a few hundred rows.

The second composite is the **card latch**, and it is UNIQUE over `(group_chat_id,
group_message_id)`. It is NULL-tolerant by construction — both engines treat NULLs as distinct in a
unique index, and a composite is unique only when every column is non-NULL — which is what makes the
latch safe to leave unset after a failed send, and it is the exact shape the group-reply lookup
(`find_by_group_message`) filters on.

> **Superseded.** This section first specified the uniqueness as `UNIQUE (group_message_id)` on the
> column alone, with `unique=True, index=True` on the mapper. That was wrong, and wrong in a way that
> loses a ticket rather than rejecting a duplicate. **A Telegram `message_id` is a per-chat
> counter**, so a global unique index asserts something Telegram never promised. Move the support
> group — a new group, or Telegram auto-upgrading a basic group to a supergroup, which *changes the
> chat id* — and an operator repoints `BAYRAM_SUPPORT_GROUP_CHAT_ID`. Old rows still hold message ids
> 2, 5, 9… from the old chat. The next card posts successfully, Telegram returns `message_id=5` in
> the new chat, and `claim_group_post`'s `UPDATE` trips the index: the commit raises
> `IntegrityError`, `run_guarded` turns it into an `Err`, and the latch fails for a card that *was*
> posted — leaving the ticket permanently un-latched and an orphan card in the group that nothing can
> edit or relay from. The as-built index is the correction. It was made **in revision `0027` itself**
> rather than in a follow-up, because `0027` had never been applied anywhere when the defect was
> found; there is no `0028`.

`telegram_user_id`, `order_id` and `public_ref` carry their own indexes as noted above.
`group_message_id` carries **none of its own** — the composite above is its only index, and re-adding
a single-column unique one restores the defect.

**No ORM relationship** to the event table and none to `orders`. An implicit lazy load inside async
SQLAlchemy surfaces as a confusing greenlet error at a random await point; the read layer runs
separate statements, the shape `get_broadcast` already uses. If one is ever added it takes
`lazy="raise"`, as everywhere else in this schema.

### 2.2 `support_ticket_events` — how it got here

`src/bayram/db/models/support_ticket_event.py`. Append-only, and therefore **no `TimestampMixin`** —
`created_at` only, the way every other append-only table in this package does it. Nothing here is
ever updated, and a column that claims otherwise is a column somebody will eventually write to.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `sa.Uuid` PK | |
| `ticket_id` | `sa.Uuid` NOT NULL, FK `support_tickets.id` **ON DELETE CASCADE** | An event is a *part* of a ticket and meaningless without it. The cascade is also what makes `/forget` one statement instead of two that can disagree (§7.2). |
| `kind` | `enum_type(SupportTicketEventKind)` NOT NULL | |
| `author_kind` | `enum_type(SupportAuthorKind)` NOT NULL | |
| `author_admin_username` | `String(ACTOR_USERNAME_LENGTH)` NULL | Set for `operator`. |
| `author_telegram_user_id` | `BigInteger` NULL | Set for `customer` and `staff_group`. |
| `author_display_name` | `String(64)` NULL | The group staffer's `@handle` or first name, so the timeline reads as a conversation rather than a list of numeric ids. 64 is the wider of Telegram's two real bounds (32 for a handle, 64 for a first name). |
| `from_status` / `to_status` | `enum_type(SupportTicketStatus)` NULL | Set **only** on `status_change`, and both ends always — a transition with one end recorded is a transition nobody can audit. |
| `body` | `String(4096)` NULL | The note, or the reply text. |
| `relayed_at` | `UtcDateTime` NULL | Stamped when a reply **actually reached** the customer. A `reply` row with no `relayed_at` is an answer nobody received, and it is the only way to tell that apart from one that landed. |
| `created_at` | `UtcDateTime` NOT NULL | |

**Index, hand-named:**

```
ix_support_ticket_events_ticket_id_created_at_id   (ticket_id, created_at, id)
```

The only read anybody performs is one ticket's timeline, oldest first. `id` is the third column for
the reason above, sharpened: two events written in one transaction share an instant exactly. There
is **no** separate index on `ticket_id` — this composite leads with it and already serves every
lookup by ticket, including the cascading delete's (`broadcast_bodies` declines the same redundant
index for the same reason) — and none on `created_at` alone, because nothing reads this table across
tickets and no sweep runs over it at all.

### 2.3 The enums — `src/bayram/contracts.py`

Lifecycle enums live in `contracts.py`, beside `BroadcastState`/`BroadcastKind`, because the
enum-length sweep (`tests/test_db/test_enum_lengths.py`) walks only `bayram.contracts` and
`bayram.db.*`. Every member is ≤ 32 characters (`ENUM_LENGTH`).

```python
class SupportTicketStatus(StrEnum):
    NEW = "new"; IN_PROGRESS = "in_progress"; WAITING = "waiting"; RESOLVED = "resolved"

class SupportTicketSource(StrEnum):
    DELIVERY_BUTTON = "delivery_button"; SUPPORT_COMMAND = "support_command"

class SupportTicketEventKind(StrEnum):
    OPENED = "opened"; DESCRIBED = "described"; STATUS_CHANGE = "status_change"
    NOTE = "note"; REPLY = "reply"; ASSIGNED = "assigned"; GROUP_POSTED = "group_posted"

class SupportAuthorKind(StrEnum):
    CUSTOMER = "customer"; OPERATOR = "operator"; STAFF_GROUP = "staff_group"; SYSTEM = "system"
```

`OPENED` and `DESCRIBED` are two kinds and not one: a customer who taps ⚠️ and never types has an
opened ticket with no description, and collapsing them would make that row indistinguishable from
one that never existed. `SupportAuthorKind` separates `operator` (signed in to the panel, has a
username and an audit row) from `staff_group` (a person in the Telegram group, identified only by
their Telegram id and display name) because the accountability available for the two is genuinely
different, and a timeline that pretended otherwise would attribute an unaudited action to the audit
log.

### 2.4 Migration authoring checklist (rev `0027`)

- Filename `20260915_1000_0027_add_support_tickets.py`; `revision: str = "0027"`,
  `down_revision: str | None = "0026"`, in `script.py.mako`'s `str | Sequence[str] | None` spelling.
  Set both by hand — `make revision` mints a random hash.
- **A migration may never contain a line starting with `import bayram` or `from bayram`**
  (`test_no_migration_imports_application_code`). Enum members are literal strings in
  `sa.Enum(..., native_enum=False, length=32)`; clocks are `sa.DateTime(timezone=True)`; column
  lengths are literal ints even though the model has a `Final` constant — revision `0024`
  re-declares `_CAPTION_LENGTH` locally for exactly this reason.
- Say in the docstring that **adding a status later needs no migration**, because `enum_type`
  renders a `VARCHAR(32)` with `create_constraint` off. Left unsaid, a reviewer asks for a follow-up
  revision that does not exist.
- Everything through `op.batch_alter_table`; the two composite index names spelled identically to
  `__table_args__`.
- A real `downgrade()`: drop indexes in `reversed()` order, then the tables child-first.
- **Register both models in `src/bayram/db/models/__init__.py` — import *and* `__all__` — in the
  same commit.** `_EXPECTED_TABLES` is derived from `Base.metadata.tables`, so an unimported model
  drops out of **both** sides of the comparison and the whole suite goes green having never touched
  the table. §8 names the hand-written test that closes this hole.

---

## 3. THE GROUP CARD AND THE TWO-WAY REPLY

### 3.1 Where the card is built, and why not in the catalogues

`src/bayram/bot/support_card.py`, imported by both the bot handlers and the runtime jobs —
`bot/delivery.py` sets the precedent for a `bot/` module that also runs in the worker. It exports the
card renderer and the inline-keyboard builder and **nothing else**.

**Staff copy does not go in the customer i18n catalogues.** `translate()` falls back across four
locales and the locale-contract AST scan holds all four in step, so a staff-only string there would
demand four translations of an internal triage message — and would put "Claim" into the same
catalogue a customer's confirmation is read from. The card is plain English literals.

### 3.2 The card

Every outgoing message is `parse_mode=HTML` by default (`bot/app.py::build_bot`). Use only tags in
`tests/test_bot/test_locale_contract.py::SUPPORTED_TAGS` — `<blockquote>` is in that set and is
used here — close every opening tag, and run **every customer-supplied fragment** through
`bayram.bot.i18n.escape_html`. An unescaped `<` is a 400 at send time and the ticket never reaches
the group at all, which is the worst failure this feature has.

```
🎫 <b>Ticket 9f4c1a7e</b> · 🆕 New
━━━━━━━━━━━━━━━━━━━━━
👤 Customer  <code>#48219</code> · 🇺🇿 uz
🎵 Order     <code>3b71d0c5</code>
🕒 Opened    15 Sep, 14:02 UTC

💬 <blockquote>Ismni notoʻgʻri aytdi — Dilnoza emas, Dilnora</blockquote>

↩️ <i>Reply to this message to answer the customer.</i>
[ ✋ Claim ] [ ✅ Resolve ]
[ 🔗 Open in panel ]
```

The status line and the claim row are **re-rendered on every change**, so the card in the group is
always the current truth rather than a snapshot of the moment it was posted. The `🔗 Open in panel`
URL comes from `support_panel_base_url`; when that is unset the button is **omitted entirely** —
not rendered pointing at a relative path, not pointed at `localhost`. Telegram validates a URL
button at send time, so a half-configured link does not produce a dead button, it produces a 400
that loses the whole card.

### 3.3 The once-only latch

The obvious implementation posts the card inside the job that creates the ticket and remembers
nothing. ARQ runs `retry_jobs=True` and SIGTERM cancels running jobs, so **every job is replayed on
every deploy**: a card whose only record of having been posted is the job that posted it is a card
posted again on every deploy, into a group where staff are already replying to the first copy.

So: **claim before act, settle after.**

```
UPDATE support_tickets
   SET group_chat_id = :chat, group_message_id = :placeholder   -- rowcount IS the lock
 WHERE id = :id AND group_message_id IS NULL
-- COMMIT, then the Telegram call, then:
UPDATE support_tickets SET group_message_id = :real, group_posted_at = :now WHERE id = :id
```

This is the shape revision `0026` gave `payment_intents.resumed_at`, for the identical reason. The
record of "this was posted" lives in the row, never in the job.

**A failed group post must never lose the ticket.** Catch `TelegramAPIError`, log it, leave the latch
unset so a later panel action or sweep can retry, and **still confirm to the customer**. The ticket
row is written and the customer has a reference; the group leg is an internal delivery problem and
they must not be told their complaint failed because our group was misconfigured.

### 3.4 Pacing one group, on its own key

Telegram rate-limits a **single group** at roughly 20 messages per minute — far tighter than the
~30/s across different chats that `BAYRAM_BROADCAST_SEND_RATE_PER_S=12` is sized against. The shared
`SendPacer` bucket (`bayram:send:budget`) meters the **token**, not the chat, so a burst of tickets
into one group earns a `retry_after` on the bot token — which stops customer **orders**, not just
cards.

Group posts therefore take their own pacer key, and the docstring says why. This is the one place in
this feature where getting the rate limiter wrong breaks something outside the feature.

### 3.5 The reply path — group to customer

Only the bot process receives updates, so this is a bot-process router, registered with a **chat-id
filter** so it can never fire in a private chat, and a **no-op when no support group is selected**
(§3.8).

A message in the support group whose `reply_to_message.message_id` matches a
`support_tickets.group_message_id`:

1. writes a `reply` event, `author_kind = staff_group`, with the staffer's Telegram id and display
   name;
2. sends the text to the customer's private chat, in **their** `language` from the row, prefixed so
   they know it is support answering and not a new sales message. **The 4096-character bound is
   computed against the FINISHED message, never against the raw body** — see the supersession below;
3. stamps `relayed_at` on the event — **after** the send, so an un-relayed reply is visible as
   exactly that;
4. **re-points `prompt_message_id` at the relay's own `message_id`** (`listen_on`), which is what
   makes the relay's closing "reply here" resolve back to this ticket instead of into the wizard;
5. acknowledges in the group thread, so the staffer knows it went;
6. **if the ticket is `new`, moves it to `in_progress`.** The reply *is* the claim. A staffer who
   answers has demonstrably picked the ticket up, and requiring them to also press ✋ is how a board
   fills with `new` tickets that have already been answered.

A reply with no text at all — a sticker, a photo, a voice note — resolves the ticket and is answered
in the group with "I can only relay text". There is nothing to relay and nothing worth putting on
the timeline, and "not one of our cards" is the one answer that is both untrue and unactionable.

**A failed relay is reported as what it was.** A `Forbidden: bot was blocked by the user` is a fact
about the customer (`delivery.is_blocked_by_customer`, the one place that classification lives) and
the group is told so. Every other refusal is a fact about us, and the group is told *that* instead,
with the advice that follows from it: try again, shorter.

> **Superseded.** Steps 2 and 4 are corrections, and the two failures they fix compounded. The relay
> bounded the staffer's body at 4096 — `support_tickets.body`'s own column width, and the right
> bound for the column — and then wrapped it in a header, a `<blockquote>` and a closing line, every
> character of which counts towards the same 4096. `translate` HTML-escapes its parameters, so one
> `&` becomes five characters and one `<` becomes four, and a body measured before escaping can be
> a fifth of its rendered size. A long answer was therefore refused by Telegram with a 400: the
> customer got nothing, `relayed_at` stayed NULL — and the group was told "they may have blocked the
> bot", because every refusal was reported as a block. A staffer was sent to investigate a customer
> who had blocked nobody while the real cause went unlooked-at. The bound is now computed by
> rendering and trimming the raw body until the RESULT fits (`handlers.support.relay_text_for`), and
> the two failures are reported separately.

The customer's own further messages do not need a new ForceReply: a reply to the relayed message
matches the same `prompt_message_id` mechanism extended to the relay's message id, which is why
§2.1 keeps `prompt_message_id` populated rather than clearing it — and why step 4 exists at all.
What that customer message then does is §1.2 step 2's follow-up branch.

### 3.5a The group's chat id claims everything, and the customer routers claim nothing outside a DM

Two filters, one hole, and neither half closes it alone.

**`InSupportGroup` is a promise about the whole room.** Both of the group router's observers end in
a catch-all, so every message and every button from the **selected** chat id is claimed there.
`handle_unresolved_group_message` answers "I could not match that to a ticket" when the staffer was
plainly talking to us — a reply to one of the bot's own messages that resolved to no ticket — and
deliberately says nothing to staff talking to each other, because a bot that answered every "anyone
around?" would be muted, and muting it costs this feature its only notification channel.
`handle_unresolved_group_callback` always speaks, because a button press is unambiguously aimed at
us and an unanswered callback query leaves a spinner for Telegram's own timeout.

**Every customer-facing router carries a private-chat filter**, stamped once in
`handlers.build_router` by `only_in_private` rather than repeated inside eleven `build_router`s.
`membership` (whose subject is chats of any kind), `commands`, `start` (a staffer's `/privacy` in
the room must reach its handler) and `support_group` sit outside it.

> **Superseded.** §3.5 first said only that the group router carries a chat-id filter "so it can
> never fire in a private chat", and left what it could not resolve to fall through. What it fell
> through to was the CUSTOMER routers, starting with `onboarding`'s catch-all — which claims every
> update from an account with no `user_profiles` row, and that is every staffer, because a triager
> has never ordered a song from this bot. So a reply to an erased ticket's card, to a duplicate card
> whose delete Telegram refused, to the bot's own relay-failure warning (the most natural thing in
> the room to answer) or to a card answered with a sticker was met with "Which language should I
> speak?" and a phone-number keyboard, **posted into the support group**, while the staffer believed
> they had answered a customer and the customer heard nothing. The private-chat filter is the other
> half: the group catch-alls know only about the configured room, and a bot added to any other group
> had the same hole with no filter in front of it.

> **Superseded 2026-09-15 — `InSupportGroup` is a query, not a constant.** This section was written
> when the room was `support_group_chat_id`, a frozen `int` read once at construction, so "the
> configured chat id" was a value the filter could close over. §3.8 makes the selection a row, and
> the filter now **asks per update** which chat is selected. Two consequences are worth stating
> rather than discovering. First, the filter runs on every message in every group the bot sits in,
> so it must be the cheap half of the pair — a `chat.type` test before any lookup — and it must be
> structurally incapable of raising: an exception in a filter is an exception outside every handler,
> and this observer has no error net (`handlers/membership.py` makes that argument at length about
> its own observer). Second, **do not cache the answer without arguing the invalidation.** A stale
> cache keeps claiming messages in the room an operator has just stopped using, and the next thing
> it claims is a customer's complaint posted to staff who no longer read it — which is worse than
> the lookup this repository's group traffic will never notice. If a cache is ever added, its TTL
> belongs in seconds and its invalidation belongs beside the select endpoint that repoints the
> group. The private-chat filter above is unchanged and still the other half.

> **Superseded 2026-09-15 — a chat that HOLDS CARDS is a support chat for the update that touches
> one, and `commands`/`start` are under the umbrella.** Three defects, all created by §3.8 making
> the room movable, all in this section's two paragraphs.
>
> **1. `InSupportGroup` dropped every button on an older card.** It resolved a `CallbackQuery`'s
> chat with `isinstance(message, Message)`. aiogram delivers an `InaccessibleMessage` — a SIBLING
> of `Message`, not a subclass — whenever Telegram judges the message carrying the button too old
> or deleted, which is what a week-old card in a busy staff room becomes. It carries `chat` and
> `message_id`; only the body is gone. So a real press by a real staffer on a real card in the
> SELECTED room was declined by this filter, could not be picked up by anything below it (the
> customer routers are under the private-chat filter and the chat is a supergroup), and was
> UNHANDLED: `callback.answer()` was never called and the button span until Telegram said "query
> is too old" — while `handle_unresolved_group_callback`, written so that can never happen, sat
> inside the router the filter had just closed. Resolution is by whatever carries `chat`;
> `_rerender_card` keeps its own `isinstance(..., Message)` guard, because editing an inaccessible
> message is genuinely impossible and must still degrade to "the move happened, the card did not
> redraw".
>
> **2. Moving or clearing the inbox turned the old room into a black hole.** Cards already posted
> stay where they are and `support:card_sync` goes on repainting them, so the room looks like a
> working queue. A triager replying to one of those cards matched no router at all: nothing was
> written, the customer heard nothing, and the staffer was answered nothing — not even the
> `_NO_TICKET_MATCH` sentence this module was given for that exact shape. **A staff reply in a
> room that holds cards must never vanish silently**, so `InSupportGroup` now claims an update in
> an unselected chat **if and only if** that update touches a card whose `group_chat_id` is that
> chat — the `ticket_for_group_message(chat, message)` lookup `ReplyToCard` already makes, which
> is precisely the question "does this chat hold this card". It answers a dict, `inbox_is_here`,
> which every handler in the router takes.
>
> **The line between the two rooms is whether the act reaches the CUSTOMER.** A relay does, so it
> is REFUSED outside the selected inbox and answered with "I did NOT send that to the customer —
> this chat is no longer the support inbox; the ticket is still open", with nothing written to the
> timeline and no status move: a paragraph the customer never received must not appear as an
> answer, and a reply that was not delivered must not claim a `new` ticket. Claim and Resolve do
> not reach the customer — they are internal triage the same operator could do from the panel — so
> they keep working on an old card and the staffer gets the news in an alert instead. Refusing
> them would leave a live-looking card whose buttons do nothing, which is the defect one layer up.
>
> **Deliberately NOT done:** claiming every group chat (that is what comparing chat ids exists to
> prevent), and remembering the previous selection (nothing keeps that history, and it answers
> wrongly the second time the inbox moves). The selected room pays nothing for this — the filter
> returns before the lookup whenever the chat is the current inbox.
>
> **3. `commands` and `start` left outside the umbrella became a privacy leak the moment this
> feature shipped.** The picker asks operators to add the bot to groups so they appear in it. A
> colleague typing `/start` in such a room took `handle_start`'s un-onboarded branch and the bot
> posted `onboarding_contact_screen` **into the group** — a `ReplyKeyboardMarkup` whose button
> carries `request_contact=True`, shown to every member. **Anyone who tapped it published their
> own phone number to the whole room**, and the answer then reached nothing, because `onboarding`
> IS under the umbrella. `/balance` and `/support` had the same shape with smaller blast radii.
> Both routers are now wrapped by `only_in_private`. The stated reason they were left out — "a
> staffer's `/privacy` in the room must reach its handler" — was written when the bot was in no
> groups, and it argued against itself: the answer to `/privacy` is a statement about the person
> who typed it, and posting it into a room of colleagues is a disclosure, not a service. The
> data-subject surface is **redirected, never denied**: `handle_unresolved_group_message` answers
> a command typed in the support group with "I answer commands in a private chat only", the same
> command in a DM behaves exactly as before, and `gate.ERASURE_COMMANDS` is untouched.
> `membership` (which records the groups) and `support_group` (whose subject is a group) stay
> outside the umbrella; the sentence naming `commands` and `start` above is superseded by this.

### 3.5b The panel door does the same three things, and shipped doing none of them

An operator answering from the board is the **second** door onto the identical act: one message,
to one customer, rendered from `support.ticket.reply`. It cannot be sent by the process that
composed it (§5.5), so it travels as `relay_support_reply` — but once that job holds the ticket it
owes the customer exactly what §3.5 steps 2 to 4 owe them, and the list is closed:

1. **render through `handlers.support.relay_text_for`**, so the bound is computed against the
   FINISHED message in this door as in the other one;
2. **stamp `relayed_at`** on the event row, after the send;
3. **re-point `prompt_message_id` at the relay's own `message_id`** (`listen_on`), so the reply
   the message invites resolves back to this ticket.

The stamp goes before the re-point. The stamp is the replay guard — every job is replayed on
deploy (§3.3), and a deploy landing between the send and these writes would relay the same
paragraph twice — while the re-point's own window is bounded by a person reading and typing.
Neither failure is retried (the customer has been told; every retry path ends in another send)
and **neither is allowed to skip the other**: they protect against different failures and a
missed stamp must not also cost the customer their way back.

> **Superseded.** This specification described all three at §1.2, §2.1 and §3.5 without ever
> saying which door it meant, and the panel door was built with none of them. `support_jobs.py`
> contained no reference to `listen_on` at all and its `_send` helper discarded Telegram's
> response — `await bot.send_message(...)` with nothing on the left of it — so the relay's
> `message_id` was not merely unused, it was unobtainable. An operator's answer therefore left
> the ticket listening on a ForceReply from weeks ago, and the customer's reply to it resolved
> to nothing, fell past the support router and was claimed by whichever wizard step they were
> parked in: **the same critical defect §1.2's supersession records, through a different door,
> still live after that one was closed.** The same function also still bounded the RAW body at a
> local `MAX_RELAY_BODY_CHARS` of 3000 before the header, the blockquote, the footer and the HTML
> escaping — §3.5's other supersession, also fixed on one door only. Both are now closed by
> **sharing the bot's implementation rather than by a second copy of it**: `relay_text_for` takes
> a two-member structural protocol (`bayram.support.RelayAddressee`: `public_ref` and `language`)
> so that the worker's `SupportTicketListItem` and the bot's `TicketSnapshot` both satisfy it
> under `mypy --strict`, and the worker's own template key and length constant are **deleted**
> rather than left as misleading exports. A feature whose supersession notes are this long earns
> the rule: **a fix to one door is not finished until the other door is checked.**

### 3.6 The two inline buttons

- **✋ Claim** → `in_progress`, record `assigned_admin_username`/`assigned_at` from the staffer,
  write `assigned` + `status_change` events, re-render the card.
- **✅ Resolve** → `resolved`, stamp `resolved_at`, write `status_change`, re-render the card.

Both go through the same transition guard as the panel (§4.2). There is no "reopen" button on the
card: a reopen happens when the customer replies, and a button that reopened a resolved ticket from
the group is a button somebody presses by accident on a card three weeks old.

### 3.7 Config

`src/bayram/config.py`, in the `# -- support ---` block. **Two settings, and neither of them is the
group** — the group is §3.8.

| Setting | Default | Notes |
| --- | --- | --- |
| `support_contact: str` | `""` | §1.1. Where `/support` sends a customer. Empty is honest: a destination nobody reads is worse than none, because the customer believes they have reported the problem. |
| `support_panel_base_url: str` | `""` | §3.2. A display string pasted into the card's URL button, never called. Empty omits the button rather than linking nowhere. |

**Neither is a credential.** Neither may be added to `VENDOR_SECRET_FIELDS` or
`FOREIGN_SECRET_ENV_VARS`: those drive `admin/app.py::derive_forbidden_env_vars()`, which makes a
production admin host **refuse to boot** when the named variable is reachable. An address is not a
secret — knowing it grants nothing without the bot token, which the admin process does not hold
(ADMIN_PANEL_PLAN D10 / §4.2).

`Settings` is `frozen=True` and must never be constructed directly — `load_settings()` /
`get_settings()`.

Both variables go in `.env.example`, which is the **bot/worker** file; the admin API reads
`.env.admin` and needs neither. No test asserts `.env.example` parity — it is on the author.

> **Superseded 2026-09-15 — the group stopped being a setting.** This section shipped with two more
> rows, `support_group_chat_id: int = 0` and `support_group_thread_id: int = 0`, and the paragraph
> arguing why a negative id must not be bounded below. Both fields are **removed from `Settings`**,
> both variables are **removed from `.env.example`**, and nothing replaces them: §3.8 makes the room
> a row in `bot_chats`, chosen in the panel. The argument the removed rows made is not lost — it
> moved to the columns, which is where it is now enforced: a chat id is still negative and still
> unbounded below, and "no group" is still a complete product rather than a broken one.
>
> **Why removed outright and not kept as a seed or a fallback**, which is the part most likely to be
> re-litigated by somebody being helpful. A setting that seeded the table, or that won when the
> table was empty, is a second authority on one fact, and it makes the first question asked in every
> support incident — *which room is this actually posting into?* — have two answers, one of them
> invisible to the very screen that exists to show it. The cost of removal is what made the call
> easy rather than brave: both fields were added and deleted inside 2026-09-15 and were **deployed
> nowhere**, so there is no operator to warn, no value to carry forward and no migration to write.
> `Settings` is `extra="ignore"`, so a stale `BAYRAM_SUPPORT_GROUP_CHAT_ID` left in a dotenv is
> ignored rather than fatal — with `extra="forbid"` this removal would have been a boot refusal on
> every host whose `.env` had not been hand-edited first, which is worth knowing before anybody
> tightens that setting. `tests/test_config.py` asserts the absence of both fields, and asserts the
> stale variable is harmless, so a re-addition fails rather than quietly ships.

### 3.8 The support group is chosen in the panel, not in the environment

**Decision.** The Telegram group that receives ticket cards is a row in `bot_chats` with
`is_support_group = true`, selected by an operator in the admin panel. `DECISIONS.md` **D18**'s
2026-09-15 amendment records it; migration `0028` creates the table; the model's docstring
(`src/bayram/db/models/bot_chat.py`) is the long-form argument for every column and is not repeated
here.

**The constraint that shapes all of it: Telegram has no "list my groups" API.** A bot cannot
enumerate the chats it belongs to. The only way it ever learns a group exists is a `my_chat_member`
update, delivered when its **own** membership changes — so a group the bot was already in on the day
this shipped produces no event, appears in no list, and **cannot be backfilled from anything**.
Nothing in this design is a workaround for that; the design is what the constraint leaves.

**Discovery is two routes, and they carry different amounts of truth.**

1. **Auto-record.** A second `my_chat_member` registration, disjoint from the churn one, filtered to
   `group` and `supergroup`, upserts `bot_chats` with `source = membership_event`. This is
   Telegram's own word that the bot is in that room, with the title, the type and the bot's status.
   It must be structurally incapable of raising, for the reason `handlers/membership.py` documents
   about its own observer: that observer has neither `InboundGateMiddleware` nor `ErrorGuardMiddleware`,
   so an escaping exception is logged and lost. It must never write a `users` row — the `PRIVATE`
   filter on the churn handler is "the correctness condition" precisely because a group arrives with
   a **negative** chat id, and the upsert underneath would mint a phantom account keyed on it.
2. **A manual chat id**, pasted into the panel, recorded as `source = manual`. There is no
   `/register` command in the group: a command is one more thing to document, to localise and to
   guard, and it answers only the case the paste already answers. A pasted id is an **unverified
   claim** — a typo, a room the bot was removed from, a channel — and the panel shows `manual`
   against it for exactly that reason.

**Selecting is an intent, so verification is what makes it safe.** `POST …/groups/select` writes the
selection and enqueues `support:verify_group`, which calls `getChat`, posts a short confirmation
into the room, and records either `verified_at` or a `verification_error` an operator can act on.
The error must distinguish at least: **the chat does not exist**, **the bot is not a member**, **the
bot cannot post there** (an administrator whose `can_post_messages` was taken away transitions
nothing and sends no membership update, so this state is invisible until something is sent), and
**the chat migrated to a new id**. A generic "verification failed" defeats the feature: the whole
point of the paste route is that the panel tells the truth about a claim it cannot check by looking.

> **Amended 2026-09-15 — selecting RETIRES the previous verdict, and the two neighbouring writes
> deliberately do not.** This section said what a selection enqueues and never said what it does to
> the verdict already on the row, and the first build therefore left `verified_at` and
> `verification_error` exactly as an earlier check had written them. Since the panel's badge derives
> from nothing else — error set is *failed*, else a clock is *verified*, else *checking…* — only a
> chat that had **never** been verified ever reached the "checking…" state this whole feature is
> built around.
>
> **What that shipped.** A group verified in August, replaced since, and quietly emptied of the bot
> comes back accent-green on both the row and the "Ticket cards go to" header the instant an
> operator re-selects it — and the panel does not poll, so the 403 the job writes a second later
> changes nothing on screen. The mirror case is worse to use: a chat whose last verdict was "the bot
> cannot post here" keeps that red sentence through a re-select, so the operator who has just fixed
> the permission in Telegram and pressed **Check again** is shown the identical sentence and cannot
> tell whether the re-check ran.
>
> **The rule, stated as an invariant rather than as a step.** The pair is the verdict on the
> selection *as it now stands*, never a record of what was once learned about a room. **Both null
> means a verdict is on its way; either one set is a verdict about the current selection.**
> `select_support_group` nulls both in the same statement that claims the row, which covers all
> three presses that reach it: a first selection, a re-select to move the topic, and **Check
> again**, which is this same endpoint pressed on the already-selected row and is the only route to
> a fresh verdict there is.
>
> **`POST …/groups/clear` leaves the pair standing**, and that is the boundary, not an oversight.
> Clearing enqueues nothing — §3.8 already says so — so nulling there would park the row at
> "checking…" for ever with nothing coming, which is the same lie in the other direction. An
> unselected chat claims nothing about where tickets go, so its last verdict is history and reads
> beside `selected_at` and `selected_by_username`, which stay for the same reason.
>
> **The `my_chat_member` upsert still may not touch either column**, including when the sighting
> says the bot was *kicked*. The model's column list is the one way to break this table from
> outside it; the bot process has never tried to post, so it holds no verdict to write; and nulling
> from there enqueues nothing either, so a bot re-added after a deploy would leave a verified inbox
> reading "checking…" with no job behind it. `bot_status` is what carries that news, toned as a
> failure for `left` and `kicked`. **Q8 (§9) is unchanged and still open** — this amendment rules on
> the verdict, not on whether a removal should unselect.
>
> **The 503 case is now honest and has a way out.** The enqueue follows the commit, so a refused
> enqueue leaves the inbox moved and its row correctly reading "checking…" with nothing coming. The
> copy already says exactly that (`support.groups.notes.workerMessage`, "Selected, and nothing can
> check it … this chat stays unchecked until one does", and `verification.checkingHint`, "If this
> never changes, no worker is running"), and **Check again** on the selected row is the press that
> asks for a verdict once a worker is back.

**The basic-group → supergroup migration is a real event, not a theoretical one.** Telegram issues a
new chat id and sends `migrate_to_chat_id`; a selected row then points at a dead id, and the next
card is lost with nothing red anywhere. The verification job reports it **in those words** — the
group moved, here is its new id — rather than as a bare failure, which is the difference between an
operator re-selecting in ten seconds and an operator opening a support incident. §2.1's supersession
already turned on this event when the id moved by redeploy; it moves by a click now, so the
composite `(group_chat_id, group_message_id)` uniqueness it argued for is **more** load-bearing, not
less.

**The enqueue happens AFTER the transaction commits.** This exact race was a critical defect in the
ticket feature the same morning: the panel enqueued while the row was uncommitted, the worker saw
nothing and treated it as terminal. `src/bayram/admin/routers/support.py` shows the
committed-then-enqueued pattern; copy it rather than reinventing it.

**At most one selected row, enforced twice**: a partial unique index on `is_support_group`, and a
select that clears the previous selection and sets the new one in **one** transaction. The index is
the invariant; the transaction is what keeps the common path from depending on a failure.

**The permission is `support.group.write`** — `W` at ADMIN and OWNER, **no step-up**; see §5.1's
amendment. Reading which group is selected is `support.read`, which every role holds, because
"where do my tickets go?" is a question an operator must be able to answer without being able to
change the answer.

**Clearing is supported and is not a failure state.** `POST …/groups/clear` unselects, and the
product keeps working exactly as §3.7's removed `0` promised: the ticket row is written, the
customer is answered and the board fills — only the group post is skipped. That is still D18's named
fallback, and it is now reached by a click rather than by a redeploy.

---

## 4. THE BOARD — four states and their legal transitions

### 4.1 Four columns, and why not five

```
new  →  in_progress  →  waiting  →  resolved
```

`waiting` means **waiting on the customer**, never on us. That is the whole reason it is a column
rather than a flag: a queue in which "we asked them a question three days ago" and "nobody has looked
at this yet" share one state is a queue whose length means nothing, because the operator cannot tell
which half is their backlog.

**There is no `triaged`.** The act that would set it — a staffer reading the card in the group — is
the same act that claims the ticket, so the two states would always move together and one of them
would be noise.

**There is no `closed` archive.** `resolved` is already terminal, and a board with a fifth column
nobody drags to is a column that silently collects tickets. A ticket leaves the board by ageing out
of the default filter, not by changing state.

Starting narrow costs a code change and not DDL: `enum_type` renders a `VARCHAR(32)` with
`create_constraint` off, so a fifth status later needs no migration.

### 4.2 The legal transitions

`bayram.support.LEGAL_STATUS_MOVES` is the whole grammar, in one table, read by the three callers
that must agree — the panel's status endpoint, the group card's buttons, and the automatic move a
staff reply performs. Three copies of a lifecycle are three chances for the board and the card to
disagree about whether a ticket is finished.

| From | To | Who | Side effects |
| --- | --- | --- | --- |
| — | `new` | the customer's tap | `opened` event |
| `new` | `in_progress` | ✋ Claim, a group reply, a panel move or reply | `assigned` (if claimed) + `status_change` |
| `new` | `waiting` | panel or group — answered with a question before anyone claimed it | `status_change` |
| `new` | `resolved` | ✅ Resolve, panel | `status_change`, `resolved_at` |
| `in_progress` | `waiting` | panel or group | `status_change` |
| `in_progress` | `resolved` | ✅ Resolve, panel | `status_change`, `resolved_at` |
| `waiting` | `in_progress` | **the customer replies**, or an operator moves it back | `status_change` |
| `waiting` | `resolved` | panel | `status_change`, `resolved_at` |
| `resolved` | `in_progress` | **reopen** — the customer replies, or an operator moves it back | `status_change`; `resolved_at` is **kept** |

Every transition not in this table is a **409 `INVALID_STATE`** naming both ends. Three refusals are
worth stating because each looks arbitrary until it is argued:

- **A status may not move to itself.** `X → X` is absent from every row on purpose. It is a no-op
  that would still write a `status_change` event with `from` and `to` equal — a timeline row that
  says nothing — and bump `updated_at`, making an untouched ticket look worked. Two staffers pressing
  ✋ Claim on one card is the common case, not the exotic one; the second press is a refused move, not
  a second event.
- **Nothing returns to `new`.** `new` means "nobody has looked at this yet", which is a claim about
  the past that no later move can make true again. A reopened ticket therefore lands in
  `in_progress` (`REOPEN_STATUS`, named once so the panel's reopen and the customer's reply cannot
  drift) and not back at the top of the unlooked-at column, where it would lose the single most
  useful fact about a repeat complaint: that it was answered once already.
- **`resolved → waiting` is not legal.** `waiting` means we have asked the customer something, and a
  resolved ticket has not.

**The two "the customer replies" rows are implemented by `bayram.support.reopen_target`**, which is
the only caller of `REOPEN_STATUS` on the bot side and answers `None` — meaning *move nothing* — for
every status outside `REOPENING_STATUSES = {waiting, resolved}`. `new` is deliberately absent even
though `new → in_progress` is a perfectly legal move: `in_progress` means somebody on our side has
picked the ticket up, and a customer adding a second sentence to a ticket nobody has read has not
made that true. Moving it would empty the unlooked-at column by pretending the backlog had been
worked, which is the fiction §4.1 says a four-column board exists to prevent. `in_progress` is
absent for the duller reason that it is already the destination.

> **Superseded.** Both rows were specified and neither was built. `REOPEN_STATUS` was referenced by
> nothing outside its own `__all__`, because the customer's reply — the event that triggers both
> transitions — could not be routed to a ticket at all (§1.2). `waiting` therefore had no exit the
> customer could take, which makes the column's own definition ("waiting on the customer, never on
> us") unfinishable by the customer. The move is attributed to `EventAuthor.customer`, not to
> `system`: it happened because a person wrote something.

`new → resolved` **is** legal and is not a shortcut to be closed off: spam and duplicates are common
enough that routing them through `in_progress` would add a click and a meaningless event.

**Every move is a conditional `UPDATE` naming the status it expects and the status it writes**, and
the rowcount is the answer. Two operators dragging one card in two browsers produce one move and one
409, not a last-write-wins silent overwrite. The panel and the group card share the one guard
function, because a transition legal from a Telegram button and illegal from the board is a bug
waiting for the first staffer who has both open.

**The status column is not the record of how a ticket got here.** Every move writes a
`status_change` event carrying `from_status` and `to_status`. The column is where it is now, the
events are how it got there — `credit_accounts.balance` beside `credit_ledger`, one domain along.

### 4.3 What the board excludes

Tickets with `described_at IS NULL` — the customer tapped ⚠️ and never typed — are **not on the
board**. There is nothing for an operator to act on and a column full of empty tickets is a column
nobody reads. The rows are kept: they are the measure of how many people tried to complain and gave
up, which is a real product signal and is answerable only because the row exists. They are reachable
through the list endpoint with an explicit filter, never by default.

### 4.4 Counts

A column's count is **exact, and comes from the board endpoint's own `GROUP BY`** —
`SupportBoardView.columns` is a `{status, count}` pair per column and nothing else. The board
is not paged and must never be: `ticket_board` returns the whole distribution by construction,
so there is no cursor to carry and no page whose length could be mistaken for a total.

> **Superseded.** This section first specified the count as `meta.total` with `withTotal: true`,
> capped at 10,000 with `isTotalExact` saying so — the convention every *paged* list in this API
> follows, and the one §6.3 still applies to the ticket list. It was wrong for the board. A cap
> exists so a `COUNT(*)` over a large filtered set cannot become the slowest query on a screen;
> four `GROUP BY` buckets over an indexed column have no such cost, and a capped column count
> would have rendered "10000+" for a queue whose real depth is the single number the board
> exists to show. The as-built response is the correction, and the frontend renders it with
> `formatCount`, not `formatTotal`.

---

## 5. BACKEND API

### 5.1 Permissions and the step-up that deliberately is not there

`src/bayram/admin/security/permissions.py`:

```python
SUPPORT_READ  = "support.read"
SUPPORT_WRITE = "support.write"
```
```python
Permission.SUPPORT_READ:  _row(viewer=_M, support=_M, admin=_M, owner=_M),
Permission.SUPPORT_WRITE: _row(support=_W, admin=_W, owner=_W),
```

`SUPPORT_READ` is `M` at every role on `broadcast.read`'s reasoning: the queue is what the panel
exists to show.

**`SUPPORT_WRITE` carries no step-up, and that is a decision rather than an omission.** Replying to a
customer is a write, and it is counted in the same permission as moving a card because a support
operator's entire job is answering customers — withholding it would leave the role unable to do the
thing it is named for, and would push the work back into the group where there is no audit row at
all. The accountability is carried by the audit row and the append-only event log, exactly as
`broadcast.write`'s note argues for its own cell.

**Never make a step-up permission the router-level guard.** `require_permission` → `check_role` holds
no subject and therefore no grant, so it returns `STEP_UP_REQUIRED` unconditionally and for ever —
to a correctly re-authenticated OWNER included — while looking right. This has been hit five times
and each has a written note in `permissions.py`. Neither permission here carries a step-up, so both
are safe as router guards; if one ever gains a step-up, the guard moves into the handler.

> **Amended 2026-09-15 — a third permission, `support.group.write`.** §3.8 moves the support group
> out of the environment and into a row an operator can repoint, so a capability that used to belong
> to whoever could deploy now belongs to whoever holds a permission, and it needs its own cell:
>
> ```python
> SUPPORT_GROUP_WRITE = "support.group.write"
> ```
> ```python
> Permission.SUPPORT_GROUP_WRITE: _row(admin=_W, owner=_W),
> ```
>
> **It is deliberately NOT `support.write`.** A support operator works the queue: they read, claim,
> answer and resolve. Repointing where every future ticket lands is a different act with a different
> blast radius — the wrong room means a customer's complaint is posted to people who should not see
> it, and nothing about it is visible from the board. SUPPORT is `—` here for that reason and the
> role loses nothing it is named for.
>
> **No step-up**, on `broadcast.write`'s precedent and with the same argument transcribed: the audit
> row plus the append-only event log carry the accountability, and a step-up on the router-level
> guard is the five-times-repeated bug the paragraph above names. Reading which group is selected
> stays `support.read` — every role can answer "where do my tickets go?" without being able to
> change the answer.
>
> Adding it is the usual pair of test files: `tests/test_admin/test_permissions.py` (7 tests) and
> `tests/test_admin/test_rbac_matrix.py`, plus the SPA's own copy in `admin-dashboard/src/lib/rbac.ts`.

### 5.2 Routes

```
GET  /api/support/tickets/board                  # DECLARED FIRST
GET  /api/support/tickets
GET  /api/support/tickets/{ticket_id}
POST /api/support/tickets/{ticket_id}/status
POST /api/support/tickets/{ticket_id}/notes
POST /api/support/tickets/{ticket_id}/reply
POST /api/support/tickets/{ticket_id}/assign
```

| Method · Path | Permission | Body | Response |
| --- | --- | --- | --- |
| `GET …/tickets/board` | `SUPPORT_READ` | — | `SupportBoardView` — `columns`, four `{status, count}` pairs in board order. Exact counts, never paged, no `meta` (§4.4) |
| `GET …/tickets?status=&source=&from=&to=&limit=&cursor=&withTotal=` | `SUPPORT_READ` | — | `TicketsPage` |
| `GET …/tickets/{id}` | `SUPPORT_READ` | — | `TicketDetailView` — the ticket, its body in full (§7.1), and its timeline |
| `POST …/{id}/status` | `SUPPORT_WRITE` | `TicketStatusRequest(ReasonedRequest)` — `to` + `expected` | `TicketDetailView`; 409 `INVALID_STATE` |
| `POST …/{id}/notes` | `SUPPORT_WRITE` | `TicketNoteRequest` | `TicketDetailView` |
| `POST …/{id}/reply` | `SUPPORT_WRITE` | `TicketReplyRequest` | `TicketDetailView`; enqueues `support:relay` |
| `POST …/{id}/assign` | `SUPPORT_WRITE` | `TicketAssignRequest` | `TicketDetailView` |

**`/board` must be declared before `/{ticket_id}`.** Starlette matches in order, and a literal path
registered second gives the caller a 422 about a malformed UUID instead of their board.
`ORDER_STATE_COUNTS_PATH` carries this warning verbatim.

Every mutation is a POST: the SPA's client is `"GET" | "POST"` only, with no PUT, PATCH or DELETE.

**The board GET must not record "this was viewed."** `tests/test_admin/test_routes_enumeration.py`
snapshots every domain table around every GET and asserts nothing changed, and a "last seen by"
stamp on a board poll would fail it — correctly, because a screen that polls would write a row every
few seconds.

Copy `routers/broadcasts.py` for style. **Do not copy `routers/chats.py`** — the survey names it the
worst style precedent in the package.

> **Amended 2026-09-15 — three routes for the support group (§3.8).**
>
> ```
> GET  /api/support/groups          SUPPORT_READ         the known chats, which one is selected, each one's verification state
> POST /api/support/groups/select   SUPPORT_GROUP_WRITE  {chatId, threadId?}
> POST /api/support/groups/clear    SUPPORT_GROUP_WRITE  unselect; tickets keep working, only the group post stops
> ```
>
> **One select endpoint, and deliberately no separate "add a manual chat".** An id that is not in
> the table is recorded as `source = manual` by the same call that selects it, because a row nobody
> selected is a row nobody looks at, and a two-step "add, then select" flow invents a state — added
> but unselected, unverified, unowned — that has no meaning in this feature. The verification job is
> what tells the truth about a pasted id; the endpoint only records the claim. Say that in the router
> docstring rather than leaving it to be re-derived.
>
> `GET /groups` is a read and **must not stamp anything** — same rule as `/board` above, and the same
> test enforces it. The three registration edits are the usual ones (§5.6), and both POSTs also need
> a line in `MUTATIONS` in `tests/test_admin/test_routes_enumeration.py`.
>
> Bodies are validated in **pydantic**, not left to the database: `tests/test_admin` runs on
> in-memory SQLite, which enforces neither check constraints nor enum lengths, so an over-long or
> malformed value must be a 422 naming the field rather than an `IntegrityError` out of a
> half-written transaction (`_checked_bodies` is the precedent; `ApiModel` is `extra="forbid"`).
>
> Audit: new `AuditAction` members for select and clear, short and dotted inside a 32-char column,
> plus the subject type in `db/admin/audit.py:SUBJECT_TYPES` — a **closed** frozenset whose omission
> raises inside `append`, which `audit_sink` swallows and retries with `subject_id=None`, producing a
> 200 whose audit row has lost the thing it was about. `field_names` must match
> `^[a-z][a-z0-9_.]{0,63}$` and be the literal `table.column`. The TypeScript copy of `AuditAction`
> in `admin-dashboard/src/api/audit.ts` and the **total** `AUDIT_ACTION_FAMILY` record over it move
> in the same change — there is no cross-language parity test, only `npm run typecheck`.

### 5.3 Schemas

`src/bayram/admin/schemas/tickets.py`, every model subclassing `ApiModel` (camelCase aliases,
frozen, `extra="forbid"`), every projection a free `to_*_view()` function.

It uses `PageMeta`, so it **must not** be re-exported from `schemas/__init__.py` — that file
re-exports only modules importing no web framework, and
`test_the_worker_decodes_a_stored_segment_without_importing_a_web_framework` runs in a subprocess and
fails if you do.

`tests/test_admin` runs on **in-memory SQLite, which enforces neither check constraints nor enum
lengths**. Restate both as pydantic validators, so an over-long reply body is a 422 naming the field
rather than an `IntegrityError` from inside a half-written transaction. `_checked_bodies` is the
precedent.

`TicketStatusRequest` carries `expected: SupportTicketStatus` — the status the operator's board was
showing. The handler's conditional `UPDATE` uses it, so a stale board produces a 409 naming both
ends instead of silently overwriting somebody else's move (§4.2).

### 5.4 The read layer, and the one privacy exception

`src/bayram/db/admin/tickets.py` — `list_tickets` / `count_tickets` / `get_ticket` /
`list_ticket_events` / `board_columns`. Session first and positional, everything else keyword-only,
never commits, never catches. `src/bayram/db/support_tickets.py` is the bot/worker write side.

`db/admin/views.py`'s standing rule is `*_chars` counts and `has_*` flags, with plaintext routed
through the audited, step-up-gated `POST /reveal`. **The ticket body is an argued exception and
crosses to the panel in full**: it is the entire content of the work item, an operator who cannot
read the complaint cannot act on it, and the customer wrote it *to* support. That argument belongs
in the view's docstring, the way `BroadcastBodyView` argues its own case — not left silent, or the
next reader takes it for an oversight and "fixes" it into a character count.

Raw Telegram ids stay masked on this wire as everywhere else.

### 5.5 The admin→ARQ seam

**The admin process cannot talk to Telegram and must not import code that could.**
`bayram.admin.*` importing `bayram.runtime.*` drags in `aiogram.Bot`, and
`test_the_seam_can_reach_nothing_that_sends_a_message` reads `admin/queue.py`'s import statements.

So a panel-side status change, note or reply **enqueues**:

| Job | Name | Role |
| --- | --- | --- |
| card sync | `support:card_sync` | Re-render the group card after a panel change |
| relay | `support:relay` | Deliver an operator's reply to the customer — render, stamp, re-point (§3.5b) |

Both job-name strings are **restated as literals in `queue.py`**, never imported from
`bayram.runtime.*`, with a paired test asserting the two spellings match. That test is the only thing
standing between a renamed job and a reply that is enqueued for ever and never runs.

- **ARQ discards a `Retry` raised on the final attempt** — no log line, nobody told. Each job reads
  its own `MAX_TRIES` and stops raising `Retry` at the last attempt (`payme_jobs._retry_or_give_up`),
  and that constant must equal the `max_tries` in its `func(...)` registration.
- `keep_result` is 3600 s and ARQ refuses a job id whose result is still in Redis. A deterministic
  job id is right for "post this card once" and **wrong** for anything that re-enqueues itself.
- `ctx['redis']` is optional — hand-built test contexts lack it — so tolerate its absence the way
  `broadcast_job._enqueue` does.
- `UtcDateTime` **raises** on a naive datetime at bind time, deep inside the driver. Pass `now`/`at`
  explicitly from call sites rather than calling `utc_now()` internally, so tests control the clock.
- **COMMIT, then enqueue.** The write and the audit row must be **committed** before the enqueue,
  not merely written: `get_db_session` commits on a clean exit of the *request*, and a worker that
  picks the job up inside that window opens its own session and cannot see the row it was named.
  Each handler reads, projects its response, calls `_committed(db)` and enqueues last. Nothing may
  touch the session after that call — SQLAlchemy refuses a statement on a transaction closed inside
  its own context manager.
- **"The row I was named is not there" is RETRYABLE in the worker**, not terminal. `relay_support_reply`
  puts an absent event row through `_retry_or_give_up` like any other recoverable failure and calls it
  gone only on the final attempt, with a distinct log line. An absent *ticket* stays terminal: that row
  predates the request that enqueues, so it is never "not yet". The two halves are independent
  defences and both are required — a commit ordering does not help a job replayed after a deploy, and
  a retry ladder is not a correctness argument.

> **Superseded.** This section first read "**Persist, then enqueue** — the write and the audit row
> commit with the request transaction; the enqueue is the last statement in the handler", and the
> routers were built that way: the enqueue ran *inside* the request transaction and was `unwrap`ed so
> that an unreachable worker rolled the whole action back, keeping the board and the group card from
> ever disagreeing. That ordering is a race. ARQ polls every `poll_delay` (0.5 s) while the handler
> still has a re-read and a serialisation to do, so a few percent of the time the worker read an
> uncommitted `reply` row — found nothing, logged, and **completed successfully with the customer
> never answered** — or re-rendered the group card from the pre-move ticket and swallowed Telegram's
> "message is not modified", freezing the card one status behind a board that was already correct.
> Both were silent. The correction is the ordering above, and its price is stated rather than hidden:
> a refused enqueue can no longer undo the write, so it is a **503 over a committed action**. What it
> leaves is visible — a card one status behind, repainted by the next action on that ticket, or a
> `REPLY` row with `relayedAt` null, which §7.1's timeline already renders as
> composed-and-not-delivered — and the operator who saw the 503 knows which. Restoring the rollback
> means restoring the race; they cannot both be had.

### 5.6 Registration — three edits per router, always

1. `src/bayram/admin/routers/__init__.py` — import + `__all__`.
2. `src/bayram/admin/app.py` — the alphabetical import block, then `include_router(...)`, **no
   `prefix=`**.
3. `tests/test_admin/test_routes_enumeration.py` — every row into the hand-written `MOUNTED_ROUTES`
   frozenset as `(method, PATH_CONSTANT, Permission.X)`, and every non-GET **also** into `MUTATIONS`.

A second permission is a second router factory, always: `build_support_read_router()` and
`build_support_write_router()`.

---

## 6. FRONTEND — `admin-dashboard/`

`admin-dashboard/` is the deployed console (`DECISIONS.md` **D15**); `admin-ui/` receives no new
features. `admin-dashboard/dist/` is checked-in stale build output and the real target is
`../src/bayram/admin/static` — hand-edit neither.

### 6.1 New files and the two existing ones that change

```
src/app/paths.ts          support: "/support", supportTicket: "/support/:ticketId" (PATTERN)
                          + supportTicketPath(ticketId) using encodeURIComponent
src/app/navItems.ts       a ninth PRIMARY_NAV item after `broadcasts`, icon LifeBuoy, ungated
src/api/support.ts        endpoint map, zod schemas, key factory, typed errors
src/features/support/useSupportTickets.ts
src/features/support/SupportBoardScreen.tsx
src/features/support/TicketDetailScreen.tsx
src/i18n/{en,ru,uz}/support.ts
```

Follow `api/broadcasts.ts` and `useBroadcasts.ts` — key factories, option bundles, typed errors.
`features/chats/useChats.ts` is the older, thinner convention and is **not** the model.

**`navItems.ts` asserts a section count in prose twice** — "Eight sections are listed" and "eight
items under two extra headings". Both go stale at nine and **both must be corrected in the same
change**, because that file's own argument is that stale counts are how this documentation rots.
The rail item may not ship ahead of `ADMIN_PANEL_PLAN` §11.2's row: `navItems.ts` is transcribed from
that enumeration and refuses to be extended by inference (`DECISIONS.md` **D12** set this precedent
and **D18** repeats it).

> **Amended 2026-09-15 — a Support group surface (§3.8).** One more screen and one more API module
> — reached from the Support board's toolbar, **not** a tenth rail item: it is where the tickets go,
> not a tenth thing an operator does, and §11.2's enumeration is not widened by a screen that hangs
> off a section already in it.
>
> Read is `support.read`, so **everyone can see which group is selected and whether it last
> verified**. The controls are gated on `support.group.write`, and a role without it is told which
> permission it lacks **in this feature's own words** — `support.actions.readOnly` is the precedent
> filed the same morning, not the generic `errors.detail.roleCannotTitle`, because a message that
> names the permission is the difference between an operator asking for the right grant and an
> operator asking why the panel is broken.
>
> The list shows, per chat: title, type, **source** (Telegram's own word vs. an operator's paste —
> they are not equally trustworthy and the screen must not flatten them), the bot's status there, and
> the verification state. Plus a manual chat-id field and a Select action.
>
> **The screen must be honest that verification is asynchronous.** The POST returns as soon as the
> row is written; the row then moves to *checking…* and only later to verified or to a **named**
> failure. A screen that renders success on the 200 is claiming the bot can post somewhere nobody
> has asked Telegram about yet — which is exactly the claim §3.8 built a job to avoid making.
>
> Conventions as above: `api/broadcasts.ts` and `useBroadcasts.ts`, `void queryClient.invalidateQueries(…)`
> for `no-floating-promises`, `MemoryRouter` in tests, and the `support` namespace extended across
> `en`, `ru` and `uz` — **Uzbek is Latin-only**, with the modifier letters `ʻ` and `ʼ` and never an
> apostrophe (§6.4).

### 6.2 The board — hand-rolled, and keyboard-first

**No drag-and-drop library is installed** — not `@dnd-kit`, not `react-beautiful-dnd`, nothing, in
either SPA. This codebase hand-rolls rather than take a dependency for one behaviour;
`ConfirmDialog.tsx` says so explicitly about Radix. Use the native HTML5 API (`draggable`,
`onDragStart`, `onDragOver`, `onDrop`).

**And give it a real keyboard path.** A card must be movable with the keyboard alone, with an
`aria-live` announcement on drop. The columns are labelled lists. This is not a nicety bolted on
after the mouse path: native HTML5 drag-and-drop is invisible to a keyboard and to a screen reader,
so a board with only the drag path is a board one class of operator cannot use at all.

Every move posts to `/status` with `expected` (§5.3) and rolls back the optimistic move on a 409,
surfacing the conflict rather than swallowing it. A card offers only the columns
`legal_moves_from(status)` allows (§4.2) — rendering four drop targets and discovering which three
are refusals is how a board teaches an operator to ignore its own errors.

### 6.3 Pagination and counts

Keyset only, no offsets. `limit` outside `[1, 200]` is a **422, never clamped**. That governs the
ticket LIST — the board is not paged and its column counts are exact, from its own response rather
than from a `meta` block (§4.4). The two screens therefore render their numbers differently on
purpose: `formatCount` on the board, `formatTotal` on the list, where a capped total really can be
inexact and has to say so.

### 6.4 i18n

Add a `support` namespace to `en`, `ru` and `uz`.

- **Uzbek here is Latin-only.** Use the modifier letters `ʻ` and `ʼ` — never apostrophes, never
  Cyrillic.
- `TranslationPath` has a hard recursion depth of **5**; do not nest deeper.
- `t` is a **new closure per locale**, so `t` goes in the dependency array of every `useMemo` that
  builds column headings or status chips. Omit it and they freeze in the first-rendered language.
- `admin-dashboard/tests/harness.ts` holds a **closed `REQUIRED_NAMESPACES` list of 11** namespaces
  over `SUPPORTED_LOCALES = ["en","ru","uz"]`. **Add `support` to it**, or the new namespace is never
  parity-checked and three catalogues drift silently.

### 6.5 The TypeScript copy of `AuditAction`

It lives in `src/api/audit.ts`, and `AUDIT_ACTION_FAMILY` in `src/features/audit/auditFormat.ts` is
a **total** `Record` over it — a new action without a family entry fails `npm run typecheck`. Python
and TypeScript hold two independent copies with **no cross-language parity test**, so the four new
actions (§7.4) must land in both in the same commit, by hand.

### 6.6 Local rules that bite

- tsconfig is aggressively strict: `exactOptionalPropertyTypes` (hence
  `...(x === undefined ? {} : { x })`), `noUncheckedIndexedAccess` (`array[i]` is `T | undefined`),
  `noUnusedLocals` / `noUnusedParameters`.
- ESLint is `strictTypeChecked` with `no-floating-promises` (hence
  `void queryClient.invalidateQueries(...)`), `consistent-type-imports` with inline `type`
  specifiers, and `no-restricted-globals` banning `fetch` outside `src/api/**`.
- In tests use `MemoryRouter`, **never** `createMemoryRouter`/`RouterProvider`: a data router builds
  a `Request` per navigation and jsdom's `AbortSignal` is not the instance undici's `Request`
  accepts, so `setSearchParams` silently never moves the URL. `BroadcastsScreen.test.tsx` writes this
  out.
- `npm test` is **not** vitest — it is the bespoke tsx localization harness (`tests/run-all.ts`).
  Component tests are `npm run test:unit`. `make ui-check` runs typecheck, lint, test:unit and test.

---

## 7. PRIVACY & POLICY

### 7.1 What crosses to the panel

1. **The body crosses in full, and it is the only free-text column in this schema that does.** The
   argument is in §5.4 and belongs in the view's docstring: it is the whole content of the work item
   and the customer wrote it to support. Everything else on the wire obeys the standing rules.
2. **Raw Telegram ids are masked**, on every ticket route, as everywhere else in the panel. No
   `/support/**` route keys on a raw id, so none needs one.
3. **The group card shows a masked customer id and never a name or a phone number.** The support
   group is a room of staff, not a room of operators with roles; putting an unmasked identifier on a
   card is putting it in everyone's Telegram cache, on their phones, for ever.
4. **No name, phone or free-text predicate exists on the ticket list at any role.** The list filters
   on `status`, `source` and a date window. `public_ref` is an exact-match lookup, not a substring
   search, so it is not an oracle: a reference is either known or it is not. `FIELDS`-style
   allowlisting is not needed here only because there is no filter DSL on this surface — if one is
   ever added it inherits `BROADCAST_SPEC` §6.1 wholesale.

### 7.2 Retention, `/forget`, and why the body is kept for ever

**`support_tickets` and `support_ticket_events` are in NEITHER of
`tests/test_db/test_privacy_constraints.py`'s two sets, with a written paragraph naming both tables,
revision `0027` and the erasure route.** This is the only exemption in that file that concedes the
table holds personal data outright: the body is free text a customer wrote about their own order —
"he said the name wrong, it is Dilnora not Dilnoza" — and the event bodies hold both the notes we
wrote about it and the replies they read. None of that can borrow `broadcasts`' argument that the
text is *from* us and never *about* a person. It **is** the person, in their own words, which is the
whole point of keeping it.

**The erasure route is `/forget`, and it is deletion rather than anonymisation.** That is the
departure from `bot_membership_events`, `credit_ledger`, `plan_purchases` and `broadcast_recipients`,
and it is deliberate: those rows are anonymised because an aggregate has to survive the person — a
churn count, a balance, a delivery record — whereas a complaint with the id nulled is not a
statistic, it is somebody's sentence with the name filed off. So:

- `support_tickets.telegram_user_id` is **NOT NULL**, unlike every other table holding that id;
- `handle_forget` **DELETEs** this customer's tickets;
- `support_ticket_events.ticket_id` carries **`ON DELETE CASCADE`** precisely so the timeline goes
  with them in the same statement rather than a second one that can disagree.

**They are not in `tables_erased_on_request` even so.** That set is read as the list of tables
`/forget` truncates for a full reset to first-contact state (PD-3) — `user_profiles`' treatment,
where the absence of a row restores an account to having never been seen. A ticket is deleted for
the person who wrote it, which is the same act at a different scope: the ticket's own erasure
restores nothing, it removes the record of a conversation.

**They are not in `tables_with_personal_data` either, because that set demands a `*_expires_at`
column, and no column on either table uses that suffix, on purpose.** In this codebase that suffix is
a published legal clock: it obliges a sweep **by name** in `tests/test_db/test_audit_retention.py`, a
`RetentionPolicy` field, a `PurgeReport` entry and a `purge_runs` column.

**THE TICKET BODY IS KEPT INDEFINITELY.** Two reasons, and both are the argument rather than an
excuse for not writing a sweep:

- **Volume is not the problem here.** This is `topup_purchases`' footing. A few complaints a week is
  not growth, and this product files complaints at nothing like the rate it sends messages —
  `broadcast_recipients`, one row per account per campaign, is the table that needed a cutoff.
- **A support history that deleted itself on a schedule would delete the evidence in the one dispute
  it was kept for.** "You told us in March that the name was wrong and we said we would fix it" is
  answerable only if March is still there. A 400-day cutoff would quietly make that answer
  unavailable at exactly the moment a customer produces a screenshot.

Neither table is on a cutoff for the same reason. There is no sweep over them at all, which is why
`test_audit_retention.py` passes over them by construction, exactly as it does over `user_profiles`.

`test_privacy_constraints.py` also scans live metadata **and the raw text of every migration on
disk** for `sa.Column('<name>'` matching `birth_year`/`dob`/`birth_date`/`age`/… — there is no such
column here and there must never be one.

### 7.3 Out of scope for the initial build

Recorded so each is a decision somebody made rather than a gap somebody missed.

- **No attachments.** A customer cannot send a photo or a voice note into a ticket. Accepting one
  would mean a `Storage` object with its own retention, its own erasure arm and its own expiring
  URL on the card, and the complaint that actually needs a screenshot can be answered by a staffer
  asking for one in the relay.
- **No SLA clocks, no escalation, no auto-close.** There is no "first response due" timer, nothing
  ages a ticket out of `waiting` on its own, and nothing resolves a stale ticket automatically. A
  board that closes tickets by itself is a board whose backlog number is fiction.
- **No customer-visible ticket history.** There is no `/tickets` command listing what you have
  reported. `/privacy` remains the only surface that tells a customer what we hold.
- **No ticket search over bodies.** Free-text search over what customers wrote is a different
  privacy question (an unmask oracle by substring) and it is not answered here.
- **No canned replies, macros or templates**, and no ticket merge or split.
- **No per-ticket priority.** The board's ordering is `created_at`, and a priority field that only
  one operator sets is a field the next operator learns to ignore.
- **`waiting` is not automated.** Nothing moves a ticket to `waiting` because we sent a message; an
  operator says so, because only they know whether the message asked a question.

### 7.4 Audit

- Add **`"ticket"` to `db/admin/audit.py:SUBJECT_TYPES`.** It is a **closed** frozenset and a missing
  member raises `AuditValueRejectedError` inside `append`, which `audit_sink` **swallows** and
  retries with `subject_id=None, ip=None` — a 200 with an audit row that has lost its subject. That
  failure is silent, which is why this is the first edit.
- New `AuditAction` members, short and dotted (the column is 32 chars):
  `ticket.status`, `ticket.note`, `ticket.reply`, `ticket.assign`. Four actions and not one
  `ticket.update`, because the audit log is queried by equality on `action` — the same reason block
  and unblock are two actions rather than one boolean.
- `subject_type = "ticket"`, `subject_id = str(ticket_id)` (matches `^[A-Za-z0-9:._-]{1,64}$`).
- `field_names` values must match `^[a-z][a-z0-9_.]{0,63}$` and be the literal `table.column` —
  `support_tickets.status`, `support_tickets.assigned_admin_username`.
- Use **`audit_sink.record()` for a success** (it rides the request transaction) and
  **`record_refusal()` before a `raise`** (it commits its own), never `record` for a refusal: the
  request transaction is about to roll back and would take the evidence with it.
- **A staffer's action in the group writes an event row, not an audit row.** They are not an
  authenticated admin subject and `admin_audit_log` must not carry an actor it cannot name. The
  append-only timeline is the accountability for the group half, and §2.3's `SupportAuthorKind` split
  exists so a reader can tell the two apart.

---

## 8. TESTS THAT BREAK AUTOMATICALLY

Not a wish list — these fail on the first commit that lands the schema.

**New tables** — `tests/test_db/test_migrations.py`: `test_upgrade_creates_every_expected_table`,
`test_the_migrated_schema_matches_the_model_metadata`,
`test_the_migrated_indexes_match_the_model_metadata` (compares index **names**),
`test_upgrade_then_downgrade_leaves_no_tables_behind`,
`test_upgrade_is_idempotent_when_already_at_head`, `test_exactly_one_migration_head_exists`,
`test_every_migration_defines_a_real_downgrade`, `test_no_migration_imports_application_code`.

**THE SILENT ONE.** `_EXPECTED_TABLES` is derived from `Base.metadata.tables`, so a model file that
exists but is never imported in `src/bayram/db/models/__init__.py` drops out of **both** sides of the
comparison: the migration creates the table, `create_all` does not, and the whole suite goes green
having never touched it. The codebase's answer is a hand-named test per table group — add
`test_the_support_ticket_tables_are_registered_as_well_as_migrated` to
`tests/test_db/test_migrations.py`, beside the four that already exist.

**Enum lengths** — `tests/test_db/test_enum_lengths.py` walks every `StrEnum` under `bayram.db` and
in `bayram.contracts`; every member ≤ 32 chars.

**Privacy** — `tests/test_db/test_privacy_constraints.py`, §7.2.

**New permission** — `tests/test_admin/test_permissions.py` (7 tests) and
`tests/test_admin/test_rbac_matrix.py`.

**New routes** — 10+ tests in `tests/test_admin/test_routes_enumeration.py`, which also snapshots
every domain table around every GET (§5.2).

**New bot locale keys** — `tests/test_i18n/test_catalog_files.py` (10 tests: key-set equality,
placeholder-set equality per key, plural parity, the uz-Latn turned-comma rules, the Russian yo
vowel, Cyrillic catalogues written in Cyrillic) **and**
`tests/test_bot/test_locale_contract.py::test_every_key_the_code_renders_is_defined_in_every_catalogue`,
which AST-scans all of `src/bayram/**` except `admin/` for `translate("literal")` calls **and for any
module constant whose name ends in `KEY` holding a dotted string**. Naming a constant
`_TICKET_PROMPT_KEY = "support.ticket.prompt"` enrols it automatically — which is a feature, and also
the trap: a constant named that way holding anything that is not a real key fails the scan.

**Button labels are stricter than they look** — `test_every_button_label_leads_with_an_emoji` (every
button, every locale), `test_no_two_buttons_on_one_screen_lead_with_the_same_emoji`, and
`test_no_text_default_emoji_is_left_without_its_selector`: `⚠`, `✉`, `⚙`, `↩`, `🗒`, `🗓` and friends
are in `TEXT_DEFAULT_EMOJI` and **must** be followed by U+FE0F. `MAX_ROW_LABEL_CHARS = 30`, measured
per locale, is a ratchet **already at its stop** — any new nav button gets a row of its own.
`tests/test_bot/test_keyboards.py::test_every_keyboard_builder_is_covered` compares the hand-written
`every_keyboard` register against `keyboards.__all__`.

**If a sweep is ever added** (none is, §7.2) —
`test_no_two_crons_in_this_worker_contend_for_the_same_minute` collects every cron's `minute` into a
set. Taken: 17, 43, 7, 0/5/10/…, 4/9/14/…. Return a hashable **tuple**, never a `set` or
`frozenset` — arq's `_get_next_dt` raises on a `frozenset`.

> **Amended 2026-09-15 — what §3.8 breaks.** Everything above applies again to `bot_chats` and to
> revision `0028`, with three additions specific to this change.
>
> **The silent one has a second instance.** `_EXPECTED_TABLES` derives from `Base.metadata.tables`,
> so a model never imported in `src/bayram/db/models/__init__.py` drops out of **both** sides and the
> suite goes green having never touched the table. `bot_chats` therefore needs its own hand-named
> `test_the_bot_chats_table_is_registered_as_well_as_migrated`, beside the ticket tables'.
>
> **The partial unique index must render on both dialects.** The unit suite is SQLite and the
> migration test is Postgres, and `test_the_migrated_indexes_match_the_model_metadata` compares index
> **names** byte-for-byte — so `sqlite_where` and `postgresql_where` both have to be given, and the
> index has to be asserted *partial* rather than merely present: a total unique index on
> `is_support_group` would permit exactly one `false` row and make the second discovered group a
> crash.
>
> **REMOVING a `Settings` field is itself a test event** — `tests/test_config.py` and
> `tests/test_admin/test_settings_and_boot.py`. The removal is asserted, not merely performed: a
> test that names both retired fields and requires their absence is what stops a future "seed it
> from the environment" from landing quietly (§3.7's supersession).
>
> The new permission and the three new routes are the ordinary entries above; the ARQ job name is
> **restated as a literal** in `admin/queue.py` with a paired test asserting the two spellings match,
> because the admin process cannot import the worker's registration (ADMIN_PANEL_PLAN D10 / §4.2, and
> `tests/test_admin/test_queue.py::test_the_seam_can_reach_nothing_that_sends_a_message` reads that
> module's imports to keep it that way).

---

## 9. RISKS & OPEN QUESTIONS

| # | Question | Why it needs a human |
| --- | --- | --- |
| **Q1** | **Does a `/support` rail entry reverse a written refusal?** Same shape as `BROADCAST_SPEC` Q1: `navItems.ts` is "transcribed from §11.2, not extended by inference". | **Answered.** `DECISIONS.md` **D18** records the decision and `ADMIN_PANEL_PLAN` §11.2 gained the rail entry and its two route rows in the same change that filed this spec. The nav item may not ship ahead of either. |
| **Q2** | **Who is in the support group, and what have they agreed to?** The card puts a customer's complaint, in their own words, into a Telegram group on staff phones, where it is cached by Telegram and by every device in the room. | This is a real data-protection question and it is not answered by masking the id. Somebody must decide who may be in that group, whether membership is reviewed, and what happens to the history when a staffer leaves. The group leg ships **off** by default (`support_group_chat_id = 0`), which is the safe default and not an answer. |
| **Q3** | **Indefinite retention of the body (§7.2) has no legal sign-off.** The argument here is operational — the evidence must outlive the dispute — and that is not the same as a lawful basis for keeping a customer's words for ever. | Product and legal must confirm, or name a retention period; if they name one it is a cutoff, a `PurgeReport` field and a `purge_runs` column, and the exemption paragraph in `test_privacy_constraints.py` is rewritten rather than deleted. LR-42/D-4 is the same open thread `BROADCAST_SPEC` §6.3 Q10 sits on. |
| **Q4** | **Is the 20/minute group ceiling right, and what happens in a real incident?** A vendor outage produces a burst of complaints far above anything this product's normal traffic generates, and §3.4's pacer will queue them. | Decide whether a queued card is acceptable (the ticket row exists either way, so the queue is a notification delay and not data loss) or whether a digest card is needed above some rate. Nobody has watched this under load. |
| **Q5** | **`resolved` is reopenable by a customer reply, which means a resolved ticket can move on its own.** An operator who resolved fifty tickets on Friday may find six of them back on Monday with no notification. | Confirm that a reopen needs no alert beyond the board itself, or specify one. This spec assumes the board is enough because there is no notification surface in the panel at all — and `TopBar.tsx`'s refusal of a notifications feed still stands. |
| **Q6** | **The ⚠️ button now writes a row and sends to a group, metered per account (§1.4) by an in-memory counter unless it is made durable.** `InMemoryWindowCounterStore` resets on redeploy. | Decide whether the ceiling is advisory (in-memory is fine) or load-bearing (it needs a row-backed counter in `LyricBudgetStore`'s style). The answer depends on Q2: an unmetered ⚠️ is a way to flood a room of staff phones. |
| **Q7** | **A group reply relays to the customer verbatim.** There is no review step, no approval, and no way to unsend. | Confirm that every person in the support group may speak to a customer directly in the product's voice. That is a staffing decision, not a code one, and it is the reason `support_group_chat_id` defaults to `0`. |

> **Amended 2026-09-15 — Q2 and Q7 in the language of §3.8.** Both rows end on "the group leg ships
> **off** by default (`support_group_chat_id = 0`)", and that sentence is now spelled differently
> without being answered differently: **off is an empty `bot_chats` table**, which is what every
> fresh deployment has, and it is still a safe default rather than an answer to either question.
>
> **Q2 gains force and does not lose it.** Repointing the room used to require a deploy, which is a
> slow, reviewed, logged act by somebody with shell access; it is now a click. That is the whole
> point of the change and it is also the risk in it: the set of people who can put a customer's
> complaint in front of a new set of staff phones is now "ADMIN and OWNER" rather than "whoever can
> deploy". The controls are `support.group.write` and the audit row (§5.1's amendment) — a
> **permission plus a record**, which is this repository's answer everywhere else and is not a
> substitute for the governance Q2 asks for. Whoever answers Q2 is now also answering: **who may
> repoint the inbox, and is the audit row read by anyone?**
>
> **Q7 is unchanged in substance.** A group reply still relays verbatim with no review step and no
> unsend, whichever room is selected. The one new line under it: an operator who selects a group is
> granting everyone already in that room the ability to speak to customers in the product's voice —
> so the verification post (§3.8) is also the notice that this has happened, and it is deliberately
> visible to the room rather than silent.
>
> **Q8, new and open: what happens to a selected group the bot is thrown out of?** A `my_chat_member`
> update says so, and the row's `bot_status` records it — but nothing in this cut un-selects it, and
> the argument for that is that an operator deciding is better than the product silently deciding
> for them. The failure mode is a card that cannot be posted with the ticket landing on the board
> anyway, which is the same shape as having no group at all. Whether removal should also clear the
> selection, and whether anyone is told, is a product call nobody has made.
