# Bayram Bot (`@bayram_uzbot`) — Product & Functionality Overview

**Bayram** (internal project: `hbd-bot`) is an AI-powered celebration kit engine in Telegram. It transforms a simple 1-minute brief about a friend, colleague, or family member into a **complete personalized celebration package**: a full studio-quality song, character spoken voice greetings, and an illustrated lyric sheet — all centered on the recipient's real name and personal stories.

---

## 1. Core Value Proposition & Market Differentiators

Unlike generic AI music tools or static greeting bots, Bayram was engineered specifically for Uzbekistan and the CIS market with five key pillars:

1. **Complete Celebration Kit (Song + Voice Greeting)**:
   Competitors produce either an impersonal song or a generic celebrity voice clone. Bayram bridges both: users receive an original song in their chosen genre *plus* customized spoken congratulatory voice messages from a single brief.
2. **First Native Uzbek AI Song Bot**:
   Full first-class support for **Uzbek Latin (`uz_latn`)**, **Uzbek Cyrillic (`uz_cyrl`)**, **Russian (`ru`)**, and **English (`en`)**, with interface and song language selectable independently.
3. **Proprietary Name Pronunciation Subsystem**:
   The #1 complaint in AI music is mispronounced regional names. Bayram employs an internal name candidate normalization engine (handling apostrophes like `o'`, `g'`, soft signs, and phonetic respelling) so names sound completely authentic.
4. **Free Lyrics Preview Before Paywall**:
   Users complete the wizard and review/edit their rhymed lyrics for free. Payment is only required when authorizing final audio generation.
5. **Frictionless Local Payments**:
   Native integration with local payment rails: **Payme**, **Click**, **Rhmt** (Uzcard / Humo), and **Telegram Stars**.

---

## 2. Supported Categories (Occasions)

The bot offers dedicated categories tailored to different life moments:

| # | Occasion (Uzbek / Russian) | Description |
|---|---|---|
| 1 | **Tugʻilgan kun / День рождения** | Flagship daily driver. Personal birthdays with inside jokes, hobbies, and wishes. |
| 2 | **Yubiley / Юбилей** | Milestone celebrations (30, 40, 50, 60 years) with a grand, respectful tone. |
| 3 | **Sevgi izhori / Признание** | Romantic confessions, relationship anniversaries, and romantic apologies. |
| 4 | **Dalda / Поддержка** | Encouragement during difficult times, exam stress, illness, or career changes. |
| 5 | **Hazil / Розыгрыш** | Lighthearted, good-natured roasts and banters among close friends. |
| 6 | **Toʻy / Свадьба** | Wedding congratulations for newlyweds (*Kelin-Kuyov*), engagements (*Fotiha*). |
| 7 | **Bolalar uchun / Для детей** | Cheerful, magical songs for kids' birthdays and baby showers. |
| 8 | **Bayram / Праздник** | Calendar holidays (New Year, March 8, Navro'z, etc.). |
| 9 | **O'qituvchilar kuni / День учителя** | Dedicated holiday category for honoring teachers and mentors. |
| 10 | **Sababsiz / Без повода** | "Just because" — unexpected smiles on a random Tuesday. |
| 11 | **Boshqa sabab / Свой повод** | Open-ended custom occasion. |

---

## 3. Musical Variety & Styles

Users can tailor the song's musical identity:

* **Genres**:
  * `Uzbek Pop` (modern mainstream Uzbek radio pop)
  * `Retro Estrada` (classic, nostalgic 80s/90s Uzbek/Soviet pop warmth)
  * `Modern Pop` (contemporary international dance/radio pop)
  * `Hip-Hop / Rap` (energetic urban beats and dynamic flow)
  * `Acoustic Ballad` (guitar/piano heartfelt emotional acoustic)
  * `Shashmaqom / Folk` (traditional national instruments and melodies)
  * `Dance / Electronic` (high-energy club and festival rhythms)
  * `Rock` & `Jazz Lounge`
* **Vocal Options**:
  * Male solo
  * Female solo
  * Duet

---

## 4. End-to-End User Experience (The Wizard)

```
[1. Start & Name] ──► [2. Occasion] ──► [3. Details / Audio Note] ──► [4. Genre & Voice]
                                                                                │
[7. Celebration Kit Delivered] ◄── [6. Payme / Click / Stars] ◄── [5. Free Lyrics Preview]
```

1. **Step 1: Recipient Name & Language**: User selects language and enters the recipient's display name.
2. **Step 2: Occasion Selection**: User picks the event (e.g. *Tug'ilgan kun*).
3. **Step 3: Personalization Input**:
   * Users can type quirks, hobbies, shared memories, or professions.
   * **Voice Note Input**: Users can simply speak a 30-second voice message into Telegram; the bot transcribes it into structured brief notes automatically.
   * Alternatively, users can choose *"I will write the words myself"*.
4. **Step 4: Style Selection**: Pick genre and vocal gender.
5. **Step 5: Free Lyric Generation**: The AI generates rhymed verses in seconds. The user can tweak, rewrite, or accept the draft.
6. **Step 6: Instant Checkout**: One-click local payment via Payme, Click, or Telegram Stars.
7. **Step 7: Delivery**: The bot delivers:
   * **The Master MP3 Song** (custom studio track with proper vocal pronunciation).
   * **Character Congratulatory Voice Notes**.
   * **Illustrated Lyric Sheet**.

---

## 5. Technical Architecture

* **Telegram Bot Core**: Python 3.12/3.14 async runtime, `aiogram 3`, Starlette ASGI, PostgreSQL, Redis.
* **AI Pipelines**:
  * **LLM Engine**: Dynamic prompt orchestration for lyric crafting and brief interpretation.
  * **STT Pipeline**: Whisper-based voice message transcription for zero-typing inputs.
  * **Music Generation**: High-fidelity AI music synthesis.
  * **Speech Generation**: Gemini TTS with acoustic mastering chains.
* **Admin Dashboard**: Standalone multilingual web dashboard (`admin-dashboard`) in Uzbek, Russian, and English for managing orders, monitoring generation queues, and tracking revenue analytics.
