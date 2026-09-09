/**
 * `GET /api/segments/fields`, verbatim.
 *
 * Generated from `to_segment_fields_view(capabilities=frozenset())` — the real registry, all
 * forty fields, with their real `doc` prose and their real operator sets, on a deployment
 * WITHOUT the optional `chat_messages` table (so the three capability-gated fields arrive
 * `isAvailable: false`, which is the case the builder has to draw rather than hide).
 *
 * It is a fixture and not a hand-written subset because the four audiences this feature was
 * asked for by name are only meaningful against the operators the server actually offers: if
 * `plan_status` stops taking `in`, or `last_activity_at` stops taking `not_within_last_days`,
 * or `delivered_order_count` stops being `sortable`, the tests that compose those audiences
 * must fail — and against a trimmed fixture they would not.
 *
 * Regenerate with:
 *   python -c "import json;from hbd.admin.schemas.segment import to_segment_fields_view as v;\
 *     print(json.dumps(v(capabilities=frozenset()).model_dump(by_alias=True,mode='json')))"
 */

import type { SegmentFieldsView } from "@/api/segments";

export const SEGMENT_FIELDS_FIXTURE: SegmentFieldsView =
{
  "version": 1,
  "defaultSort": {
    "key": "joined_at",
    "dir": "desc"
  },
  "limits": {
    "maxRules": 25,
    "maxDepth": 3,
    "maxValueMembers": 50,
    "maxAggregateRules": 6
  },
  "fields": [
    {
      "key": "bot_block_event_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "How many times this account has blocked the bot. Our own delivery history. Not sortable: a ranked list of the people most annoyed with us is a leaderboard nobody needs, and the count answers every question a campaign has as a filter."
    },
    {
      "key": "bot_blocked",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "**The CUSTOMER's block** — they blocked the bot. Safe for the same reason as ``is_blocked`` and load-bearing for a different one: it is the cheapest way to keep a campaign from spending its whole rate budget on accounts Telegram will refuse. A presence test over a stamp we recorded, never the stamp itself."
    },
    {
      "key": "bot_blocked_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "When they blocked us. An instant we observed about our own delivery, at day-scale resolution in practice, and the only way to ask 'who left us in the week after the price change'. NULL means not currently blocked, which is why a backward-looking operator includes NULLs: 'has not blocked us since March' must contain everyone who never blocked us at all."
    },
    {
      "key": "credit_balance",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "The STORED balance, never ``read_balance``'s projection. Our own ledger number about our own product, already on every row of the list. It is the stored column for the reason ``UserFilters.has_balance`` gives: the projection is three statements per account and a function of ``now``, so a page filtered or sorted on it would drift under its own cursor mid-pagination. ``COALESCE(…, 0)`` so the sort is total: 'never metered' orders as zero, and the UI says so."
    },
    {
      "key": "delivered_order_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Songs actually delivered. This is 'generated the most' — as a THRESHOLD, because a sort alone narrows nothing and a campaign aimed at 'the top of a list' has no members until somebody says how far down the list goes."
    },
    {
      "key": "failed_order_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Orders that failed on our side. Our own defect record, and the only honest way to address an apology to the people it is owed to."
    },
    {
      "key": "first_metered_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When the credit account was opened — the first charge or grant. An instant in our ledger, not in the customer's life, and the cohort key for 'people whose first month is about to end'."
    },
    {
      "key": "first_order_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When they first ordered. Derived from ``MIN(orders.created_at)`` rather than read from a column, so it stays true no matter what a later writer does — the same derivation the list publishes as ``firstOrderAt``."
    },
    {
      "key": "has_abandoned_checkout",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Started a payment and never completed one. A fact about our own checkout funnel — no amount, no rail, no card, no reference. The second half subtracts anyone who ever paid, so this never reaches a customer who abandoned one attempt and completed the next."
    },
    {
      "key": "has_avatar",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Whether we have stored an avatar. A presence tick over a stamp WE wrote — never a claim about bytes, which ``db/admin/assets`` refuses to make without reading them, and never anything about what the picture shows."
    },
    {
      "key": "has_credit_account",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Whether this account has ever been metered. The row is opened by the first charge or grant, so its absence means never metered — a fact about our ledger, and the distinction ``UserListItem.credit_balance`` publishes as NULL rather than 0 for exactly this reason."
    },
    {
      "key": "has_paid_ever",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Has money ever moved, on either rail. The single most useful cut a campaign makes — 'customers' against 'people who have only ever looked' — and it is one bit derived from two of our own ledgers, disclosing neither amount nor date."
    },
    {
      "key": "has_phone",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Whether a phone number is on file — and the exact boundary ``SEGMENT_REFUSALS`` draws. 'We hold one' is a fact about our records that the panel already shows as a masked cell; 'it starts with +99890' is a fact about the customer and is refused at every role, because an exact or prefix predicate on a column masked everywhere is an unmask oracle with no step-up, no budget unit and no audit row. ``POST /reveal`` stays the only unmask path, which is only true while nothing else in the API answers questions about the value."
    },
    {
      "key": "has_profile",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Whether we hold a profile row at all. A fact about OUR RECORDS, not about the customer, and one the list already publishes as ``isProfilePresent``. It is also the honest way to ask 'who never finished onboarding' without touching a single identity column."
    },
    {
      "key": "has_returned_after_block",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Blocked us at some point and unblocked us at some point. Two bits from our own membership log, and the audience most worth being careful with: they left once already."
    },
    {
      "key": "has_username",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Whether Telegram gave us a handle. Presence only, on the identical argument as ``has_phone``: a substring predicate over a handle recovers it three characters at a time, which is the refusal ``UserFilters.search`` already makes in prose."
    },
    {
      "key": "inbound_message_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": "chat_messages",
      "isAvailable": false,
      "doc": "How many messages this account has sent us. A COUNT of rows, never their contents: ``chat_messages.body`` is in ``SEGMENT_REFUSALS`` on exactly the same footing as the profile names, and no operator, at any role, may point a predicate at what a customer typed."
    },
    {
      "key": "is_blocked",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "**The OPERATOR's bar**, written by the panel itself. It is our own decision about our own account, so filtering on it discloses nothing about the customer that the operator did not write. Never OR-ed with ``bot_blocked``: they are opposite facts with opposite subjects, they get different labels in the builder, and collapsing them is how 'barred by us' silently becomes 'left us'."
    },
    {
      "key": "is_reachable",
      "kind": "bool",
      "ops": [
        "is_false",
        "is_true"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "Derived: neither barred by us nor blocked by them. Two columns the operator may already filter on, ANDed — so it discloses nothing either one does not, and it exists because every campaign wants it and a wizard that made each operator spell it out would eventually meet one who spelled it wrong."
    },
    {
      "key": "joined_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "FIRST CONTACT — the language question, a touch, or an order, whichever came first (``users`` has three writers; see ``db/admin/users``'s module docstring). It is already published on every row of the list as ``accountCreatedAt``, and it is the default sort because it is the column the keyset has always used. 'Joined in June' is this field with a half-open ``between``."
    },
    {
      "key": "language_chosen_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When the first question the bot asks was answered — the earliest signal this system has that an account is a person, and a cohort boundary for every campaign that wants 'people who arrived after the redesign'."
    },
    {
      "key": "last_activity_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "``users.last_seen_at``, and it is FILTERABLE BUT NEVER SORTABLE — the one asymmetry in this registry, and it is deliberate. ``credits.touch`` moves this column on every inbound update, which is why ``db/admin/users`` and ``db/admin/overview`` withhold it from every per-row projection: a published column would let an operator watch a customer's activity minute by minute from a screen whose stated purpose is records. A PREDICATE discloses only the bucket the operator already chose ('quiet for 90 days'), which is the one question a re-engagement campaign is made of. A SORT discloses a total order over identified accounts — the same surveillance the withheld projection exists to prevent, rebuilt one page at a time. So the predicate is allowed and the sort is refused, and ``sortable=False`` here is that refusal in code."
    },
    {
      "key": "last_delivered_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When we last delivered to them. Separate from ``last_order_at`` because an order placed and an order fulfilled are different facts, and a 'here is something new' campaign is owed to people we actually delivered to."
    },
    {
      "key": "last_inbound_message_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": "chat_messages",
      "isAvailable": false,
      "doc": "When they last wrote to us. A stamp on our own inbox, at the granularity a re-engagement window needs, and the closest this registry comes to ``last_seen_at`` — which is why it is filterable and not sortable either."
    },
    {
      "key": "last_order_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When they last ordered — the purchase-shaped activity signal this package publishes INSTEAD of ``last_seen_at``, and the reason that refusal costs the panel nothing. Bounded, purchase-shaped, and one number rather than a live feed. NULL means never ordered, which a backward-looking operator includes."
    },
    {
      "key": "last_topup_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When they last topped up — our own receipt's stamp, not a claim about the customer's wallet. It is the money-shaped counterpart to ``last_order_at`` and carries the same NULL reading: never topped up is stale, so a backward-looking operator reaches them and a forward-looking one does not."
    },
    {
      "key": "lifetime_credits_granted",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Everything we have ever granted this account. A monotonic number from our own ledger — the closest thing to 'how much has this customer been given', which is the question behind every thank-you campaign."
    },
    {
      "key": "onboarded_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When onboarding completed. An instant in OUR funnel, the thing a 'welcome, one week in' campaign is keyed on, and it says nothing about the customer beyond when they finished answering us."
    },
    {
      "key": "order_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "How many orders this account has placed, in any state. A count of OUR OWN records that the list already publishes per row, and the coarsest possible shape of 'how engaged is this customer' — a number, never a title, never a recipient, never a lyric."
    },
    {
      "key": "order_state",
      "kind": "enum",
      "ops": [
        "in",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "'Has an order in one of these states' — a presence question over a closed enum of our own pipeline's stages. It names no order and reveals nothing about any one of them, which is what keeps it a segment predicate rather than a peek at the orders screen. ``in``/``not_in`` only: an account has many orders, so 'is equal to' has no single answer to be equal to."
    },
    {
      "key": "paid_order_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Orders that reached a paid state, using the same ``_PAID_STATES`` tuple the list rollup counts with, so the chip and the column can never disagree about what 'paid' means."
    },
    {
      "key": "phone_shared_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "WHEN a number was shared — deliberately not WHAT was shared. The stamp is a step in our own funnel; the value behind it stays masked and unfilterable."
    },
    {
      "key": "plan_ends_at",
      "kind": "instant",
      "ops": [
        "between",
        "gt",
        "gte",
        "is_not_null",
        "is_null",
        "lt",
        "lte",
        "not_within_last_days",
        "within_last_days",
        "within_next_days"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "When the longest-running plan stops minting. The one field with a genuine forward-looking use — ``within_next_days`` is 'whose plan ends this week', the audience for the only renewal-shaped message this product can honestly send."
    },
    {
      "key": "plan_purchase_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "How many plans they have bought. A count of receipts we issued; it separates a first-time buyer from someone who has come back three times, which is the whole of what a loyalty message needs to know."
    },
    {
      "key": "plan_status",
      "kind": "enum",
      "ops": [
        "in",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Where the account stands on plans, in four mutually-exclusive, exhaustive cases derived from ``PlanState``'s own two predicates. Our commercial relationship with them, which is the thing a campaign is allowed to be about. **``lapsed`` is the only truthful spelling of 'did not renew'** — there is no renewal in this product, no auto-renew and no recurring billing, so the operator-facing label must read 'plan expired and not repurchased'. Getting that wrong ships 'your subscription lapsed' to people who never had one."
    },
    {
      "key": "telegram_user_id",
      "kind": "int",
      "ops": [
        "eq",
        "in"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "Safe because this screen already returns the value unmasked in every row — every ``/users/**`` route keys on it, so the panel could not draw a link or a reveal without it. A predicate over a value the same response prints in full discloses nothing the caller did not already hold. ``eq`` and ``in`` only: a range over account ids is not a question anybody asks and is a full scan wearing a filter's clothes."
    },
    {
      "key": "topup_count",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "How many top-ups they have bought. A count of receipts WE issued, on our own one-off rail. It separates somebody who bought a single song once from somebody who keeps coming back for them, which is the only thing a repeat-purchase message needs to know — and it names no product, no amount and no date."
    },
    {
      "key": "topup_spend_minor",
      "kind": "int",
      "ops": [
        "between",
        "eq",
        "gt",
        "gte",
        "in",
        "lt",
        "lte",
        "neq",
        "not_in"
      ],
      "sortable": true,
      "isAggregate": true,
      "capability": null,
      "isAvailable": true,
      "doc": "Total top-up spend in minor units. Money WE charged, from our own ledger, in the currency the receipt was written in. ``SUM`` is NULL over an empty set on both dialects, so the ``COALESCE`` is what makes 'never topped up' sort as zero instead of vanishing to whichever end the dialect puts NULLs."
    },
    {
      "key": "ui_language",
      "kind": "enum",
      "ops": [
        "eq",
        "in",
        "neq",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": false,
      "capability": null,
      "isAvailable": true,
      "doc": "The language the bot speaks to this account in — our own setting, chosen by the customer from four options, and the one field a broadcast genuinely cannot work without: a campaign body is written per language and sending the Russian one to an Uzbek speaker is the failure this field exists to prevent."
    },
    {
      "key": "wizard_step",
      "kind": "token",
      "ops": [
        "in",
        "not_in"
      ],
      "sortable": false,
      "isAggregate": true,
      "capability": "chat_messages",
      "isAvailable": false,
      "doc": "Which step of OUR wizard they have reached. The values are short tokens this system writes from its own closed vocabulary — never text a customer typed — and each is length-capped at the column's own width, so the ``in`` list cannot become a probe of anything else. It is how 'people who got as far as choosing an occasion and stopped' is expressible at all."
    }
  ]
};
