# User chat behaviour — every user, paid or not (2026-10-08)

**Source:** a read-only export of production `chat_messages`, `users`/`user_profiles` (flags
only), `orders`+`briefs`, `payment_intents`, `channel_attributions`, `support_tickets` and
`credit_ledger`, pulled 2026-10-08 ~20:50 Tashkent time. The window runs 2026-09-10 → 2026-10-08.
Message text is kept for only 14 days (`text_expires_at`), so anything older is the flow
(steps, buttons, message kinds) without the text. The raw export stayed outside the repository.
This document holds counts and paraphrases only: no names, ids or numbers.

**Scale:** 355 users, 9 715 messages, 70 orders (67 delivered, 3 moderation failures), 102
payment intents. **266 of the 355 users arrived today** from two paid channel placements
(`c_andijon_bugun` 224 first touches, `c_fargona24` 39). Four tester accounts (anyone holding
an `admin_grant`) are excluded from the funnel below, which leaves 353 users.

## 1. The funnel

| Stage | Users | % of starters |
| --- | ---: | ---: |
| Pressed /start | 353 | 100 % |
| Chose a language | 334 | 95 % |
| **Shared phone** | **178** | **50 %** |
| Picked an occasion | 165 | 47 % |
| Approved lyrics (saw price) | 118 | 33 % |
| Tapped "pay" | 73 | 21 % |
| Opened a payment intent | 67 | 19 % |
| **Paid** | **26** | **7 %** |

### By acquisition channel

| Channel | Users | Phone | Lyrics OK | Pay tap | Paid | Start→paid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| organic / no param | 112 | 63 | 49 | 40 | 22 | **20 %** |
| `andijon_bugun` (today) | 205 | 100 | 61 | 29 | 4 | **2 %** |
| `fargona24` (today) | 36 | 15 | 8 | 4 | 0 | **0 %** |

Channel traffic is cold. It drops off at the same points as organic traffic, only harder, and
it collapses at the final payment step: 29 intents, 4 paid. Today's evening cohort was still
open when the export ran, so a few of those may yet convert. The gap is still roughly tenfold.

## 2. Findings, ranked by users lost

### F1 — The phone wall loses half of everyone (≈156 users)

After choosing a language, 170 users never got past the phone request: 108 left without
replying and 62 replied with something other than the contact button.

- **44 users typed their phone number as text**, which the bot rejects with "press the button
  below". Only 25 of them ever shared it the proper way, so 19 who were willing to give a
  number were turned away.
- Many typed the **recipient's name** or the request itself at this step ("a birthday song",
  "a congratulations song for my parents"). They thought the bot was asking who the song
  is for.
- Others wrote "I don't understand", sent 🤬, or pressed /start again (43 times).

**Actions:**
1. Accept a typed `+998…`/9–12-digit number as the phone.
2. Move the phone request **after** lyrics approval, or make it optional. Its stated purpose
   (a fallback delivery channel) is not needed before the user has seen any value.
3. If the request stays up front, treat non-number text at this step as an early brief: keep
   it and continue, instead of repeating the same prompt.

### F2 — Price shock at the lyrics → payment step (45 users)

45 users approved lyrics, saw "15 000 soʻm", and never tapped pay: 34 had lyrics as their
last step, plus the cancels at `Wizard:confirm`. What they wrote there: "oh, it's paid",
"don't need it", "let me hear the song first", "scam".

**Actions:**
1. **Say it is paid before the wizard**, on the first screen. Users are surprised at the end,
   after investing 5–10 taps.
2. **A 10–15 s preview** (watermarked or low-bitrate) before payment. "Let me hear it first"
   is the single most explicit objection. `src/bayram/watermark.py` already exists.
3. Show one example song from the menu, so new users know what they are buying.

### F3 — The payment step itself fails for channel traffic (≈40 users)

73 tapped pay and 26 paid. Today on Rahmat it went 7 paid against **32 still `pending`**. Users
who tapped pay and stalled wrote:

- "I don't have a card. Can I pay at Paynet?" (asked twice)
- "I can't transfer the money"
- "I'll pay later, once money lands on my card"
- many pressed **🎫 Limitim** right after the link. They were apparently checking whether the
  payment had gone through.

**Actions:**
1. **Payment-later recovery:** an intent that is still pending after ~2 h, and again the
   next day, gets one reminder carrying the same lyrics and the link. "I'll pay later" users
   are told nothing today.
2. Add a cash/terminal route (Paynet). Otherwise answer the "no card" question on the pay
   screen itself.
3. After the link, show "waiting for payment… (check)" instead of leaving users to guess
   with Limitim.
4. Check: only 1 Rahmat intent has ever expired, so `pending` may not have an expiry sweep
   for that rail.

### F4 — Support tickets are not being answered (10 of 11 still `new`)

Every ticket except one is `status=new`, including four from 2026-09-27 and five from today.
Most are **quality complaints from paying users**: "my 2-year-old sings better", "re-record it
or refund me", "stress the name more", "the name was pronounced wrong". One said "do I have to
pay again to get the same thing?".

**Actions:**
1. Triage today's five tickets. The 09-27 customer was promised nothing and has waited 11 days.
2. Add a **free re-roll for paid songs** (one retake), aimed at name pronunciation in
   particular. Post-delivery messages also ask to "change the lyrics".
3. Add an alert when a ticket sits in `new` for more than N hours.

### F5 — Users write rich context into the name field

At the name step users write phrases rather than names: "my wife, my love", "my older brother
whom I respect", "I call her mum", nicknames, or name + age + style together. The median user
sends 1 name message but the tail goes up to 20 (retypes after a failed name confirm).

**Action:** split the input into a *name* and a "*how do you call them / anything else*" note.
Alternatively, pass the extra words through as the note instead of asking again. This is
also what the "stress the name more" ticket was really asking for.

### F6 — Lyrics regeneration is a buying signal, not a problem

49 users regenerated lyrics (mean 2.4, max 11). They paid at **27 %**, against **17 %** for
users who approved the first draft. "Back" is pressed most from `lyrics` (26) and `confirm` (24).

**Action:** keep regeneration free and visible, and don't cap it below ~5.

## 2a. What people order (70 briefs)

Occasion: birthday 20, love 17, no occasion 9, kids 8, prank 7, support 4, custom 4.
Genre: pop 20, hip-hop 11, acoustic ballad 11, retro estrada 9, Uzbek pop 9. Output language:
uz-Latn 32, ru 21, uz-Cyrl 17. UI language of all users: uz-Latn 233, uz-Cyrl 92, ru 28.
Retention is thin: 24 of 33 buyers ordered once, and only 18 users ever came back on a second
day.

## 3. Priority list

| # | Change | Expected effect | Size |
| --- | --- | --- | --- |
| 1 | Answer the open tickets; free retake for complaints | protects paying users and word of mouth | ops + S |
| 2 | Accept typed phone numbers | +~19 users today alone | S |
| 3 | Pending-payment reminder (2 h / 24 h) | recover some of the 32 pending | M |
| 4 | Say "paid, 15 000 soʻm" on the first screen | stops spending effort on users who won't pay | S |
| 5 | Move phone request after lyrics, or make it optional | the largest drop (−50 %) | M |
| 6 | Paid-song preview snippet before payment | answers the main objection | M–L |
| 7 | Non-card payment answer (Paynet) | channel traffic | M |
| 8 | Split name / nickname-and-context fields | quality complaints about names | S–M |

**Re-run before spending more on channel placements.** Today's two placements bought 241
users and 4 payments. Items 2–4 are cheap and should land before the next placement.
