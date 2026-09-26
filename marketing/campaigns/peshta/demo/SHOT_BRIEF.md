# Step 12 — the 1.50 s product demo (you record this)

**Why you and not me:** the zero-AI-text rule (§7 of the plan, `03_production_blueprint.md` §4.1). Every other
frame of this film is generated, so the one moment showing the actual product has to be genuinely real UI. A
generated phone screen is exactly the tell that makes an Uzbek viewer call the whole thing *arzon montaj*.

**Where it lands:** master frames 450–524, 9.000 s – 10.500 s, over the sustained vocal run. Save as
`marketing/campaigns/peshta/demo/bot_demo.mov` (or `.mp4`) — the assembly chain reads that path.

---

## Capture settings

| | |
|---|---|
| Device | Any phone whose screen is at least 1080 wide. iOS screen recording is fine. |
| Orientation | Portrait, held still. The frame gets scaled into a 1080×1920 master. |
| Duration | Record **6–10 seconds** of the flow. I cut the 1.50 s that works; don't try to hit the length on camera. |
| Chrome | Full screen recording including the Telegram header is fine — it reads as authentic. |
| Do not | Add zoom gestures, rotate, or tap notifications. One continuous take. |

---

## The flow to film — shipped labels only

There is **no `Qoʻshiq yaratish` button**. The research blueprint invented it; `uz_latn.py` has no such string.
Film what the bot actually does:

1. The name prompt is on screen: *"Endi ismini — oʻzingiz yozadigan koʻrinishda yozing…"*
2. **Type a name.** Use a neutral one — not a real customer, not a family member. `Saodatxon` is what the plan
   uses and it is safe.
3. Tap **`✅ Ha, shunday`** — the name-confirm button.
4. The language question appears: *"{name} uchun qoʻshiq qaysi tilda boʻlsin?"* — answer it.
5. The writing line appears: *"✍️ {name} uchun soʻzlarni yozayapman… bu bir daqiqagacha oladi."*
6. **Stop once the free lyric preview renders.** That preview is the payload of this shot — it is the proof
   that the product does something before anyone pays.

---

## What the shot has to show, in order of importance

1. **The lyric preview appearing.** If only one thing is legible at thumbnail size, it is this.
2. **A real name being typed**, so the personalisation claim is visible rather than asserted.
3. **The Telegram chrome**, which is what makes it read as real.

## What will get the take rejected

- A real person's name, or anything identifying a customer.
- A visible phone number, contact list, or other chat in the header.
- Any payment screen or price — the price ships as a burned-in card (c8), not as UI.
- A stalled or errored render. If the bot fails mid-flow, retake; a broken product on camera is worse than no
  demo at all.

---

## If you would rather not

Say so and I'll cut the shot: those 75 frames fold back into the hero dance, the film loses its only proof
that the product works, and the price card has to carry more weight. It is a real trade, not a formality.
