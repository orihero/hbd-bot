# Standard Operating Procedure (SOP): Weekly Virality Monitoring & Rapid Response Engine (R4)

**Document ID**: `SOP-BAYRAM-VIRAL-004`  
**Target Repository Directory**: `marketing/campaigns/viral-ideas/`  
**Brand**: Bayram Bot (`@bayram_uzbot` / `bayrambot.uz`)  
**Scope**: Recurring Weekly Operational Workflow for Tracking, Deconstructing, and Hijacking Breakout Uzbek Reels & Shorts Trends Within 48 Hours.  
**Effective Date**: September 2026  
**Status**: APPROVED OPERATIONAL STANDARD  

---

## 1. SOP Objective & Operational Cadence

### 1.1 Strategic Objective
The objective of this Standard Operating Procedure (SOP) is to establish a rigorous, repeatable weekly workflow that detects high-velocity viral content spikes across Instagram Reels and YouTube Shorts within Uzbekistan within 24–48 hours of emergence. By identifying trending audio and visual mechanics early in their lifecycle curve, Bayram Bot (`@bayram_uzbot`) deploys culturally native, copyright-compliant responsive video assets before trend saturation occurs.

### 1.2 Operational Cadence (Monday Morning to Thursday Evening)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                         WEEKLY 4-STEP VIRALITY MONITORING & PRODUCTION ENGINE                    │
├───────────────────┬───────────────────┬────────────────────────────┬─────────────────────────────┤
│ STEP 1: DISCOVERY │ STEP 2: VELOCITY  │ STEP 3: DECONSTRUCTION     │ STEP 4: 48-HOUR SPRINT      │
│ Monday 09:00-12:00│ Monday 14:00-17:00│ Tuesday 10:00-13:00        │ Tue 14:00 - Thu 21:30       │
├───────────────────┼───────────────────┼────────────────────────────┼─────────────────────────────┤
│ • Instagram Audio │ • View Delta Calc │ • Copyright Tier Check     │ • 2 Format Selections      │
│ • YouTube Shorts  │ • VPH Thresholds  │ • BPM & Meter Analysis     │ • Bilingual Scripting (UZ/RU│
│ • Telegram Scrape │ • Share/Like Gate │ • Cultural Tension Mapping │ • Fast Production & Edit    │
│ • Raw 50-Item Log │ • Qualified Top 5 │ • Pattern Interrupt Decode │ • Peak Window Launch (19:30)│
└───────────────────┴───────────────────┴────────────────────────────┴─────────────────────────────┘
```

---

## 2. Step 1: Systematic Discovery (Monday 09:00 – 12:00)

### 2.1 Scope & Purpose
To systematically aggregate an unfiltered candidate pool of at least **50 high-growth short-form videos** produced in or targeted at Uzbekistan during the preceding 7-day period.

### 2.2 Channels & Execution Protocol

#### Channel A: Instagram Reels Trending Audio Tab (Uzbekistan Region)
* **Frequency**: Monday 09:00 – 10:00 UZT.
* **Execution**:
  1. Open Instagram on dedicated monitoring device with Uzbekistan IP address and Tashkent GPS coordinates.
  2. Navigate to Reels $\rightarrow$ Camera $\rightarrow$ Audio $\rightarrow$ **Trending Sounds**.
  3. Filter for audio tracks marked with the trending upward arrow ($\nearrow$) having under $10{,}000$ total lifetime Reels created (indicating early lifecycle phase).
  4. Record track title, original artist/creator, total reel count, and audio URL.

#### Channel B: YouTube Shorts Geo-Scraper (`regionCode=UZ`)
* **Frequency**: Monday 10:00 – 11:00 UZT.
* **Execution**: Execute the automated YouTube Data API v3 discovery script to pull trending vertical videos tagged for Uzbekistan:

```python
# API Endpoint: https://www.googleapis.com/youtube/v3/videos
# Query Parameters:
params = {
    "part": "snippet,statistics,contentDetails",
    "chart": "mostPopular",
    "regionCode": "UZ",
    "videoCategoryId": "24",  # Entertainment (also run for 10 = Music)
    "maxResults": 50,
}
```

* Extract video IDs with aspect ratio 9:16 (vertical Shorts) published within the last 72 hours.
* Extract metadata: view count, like count, comment count, title, and channel country code.

#### Channel C: Telegram Virality Aggregators
* **Frequency**: Monday 11:00 – 12:00 UZT.
* **Execution**: Scan primary Tashkent entertainment and humor channels for forwarded Instagram Reels and TikTok videos that surpassed $200{,}000$ views within 24 hours of posting:
  * `@tashkent_vine`
  * `@subyektivuz`
  * `@mittivine_channel`
  * `@darakchi_uz`
  * `@toshkentliklar`
  * `@uzbekistan_trend`

### 2.3 Discovery Output: Raw Candidate Log
All 50 candidates are logged into the weekly tracking spreadsheet (`Weekly_Virality_Tracker_YYYY_WW.csv`) with the following fields:
1. `Timestamp_Discovered` (ISO 8601)
2. `Platform` (Instagram / YouTube / Telegram)
3. `Video_URL`
4. `Creator_Handle`
5. `Audio_Title`
6. `Audio_Type` (Original / Commercial Track / Folk Sample)
7. `Initial_Views_T0`
8. `Initial_Likes_T0`
9. `Initial_Comments_T0`

---

## 3. Step 2: Velocity Tracking & Filtering (Monday 14:00 – 17:00)

### 3.1 Scope & Purpose
To filter the 50 candidate videos down to a qualified slate of **Top 5 Breakout Trends** using rigorous mathematical velocity formulas, eliminating artificially boosted or non-local content.

### 3.2 Quantitative Velocity Formulas

#### 1. Views Per Hour ($VPH$)
$$VPH = \frac{\text{Views}_{T_1} - \text{Views}_{T_0}}{T_1 - T_0}$$
*where $T_0$ is discovery time (09:00–12:00) and $T_1$ is evaluation time (14:00–17:00).*

#### 2. 24-Hour Velocity Delta ($\text{Velocity}_{24h}$)
$$\text{Velocity}_{24h} = \text{Views}_{24h} - \text{Views}_{0h}$$

#### 3. Viral Acceleration ($a_{\text{viral}}$)
$$a_{\text{viral}} = \frac{\text{VPH}(t_2) - \text{VPH}(t_1)}{t_2 - t_1}$$
*Measures second-order velocity growth between evaluation intervals ($t_1, t_2$). Identifies exponential breakout velocity before a video reaches peak view saturation.*

#### 4. Virality & Shareability Coefficient ($Q_{\text{viral}}$)
$$Q_{\text{viral}} = \frac{(\text{Shares} \times 3.0) + (\text{Saves} \times 2.5) + (\text{Comments} \times 1.5) + (\text{Likes} \times 0.5)}{\text{Views}}$$
*Synthesizes high-intent engagement signals weighted according to Meta Explore delivery priority in Central Asia (DMs and saves carry 5.5x combined weight of likes).*

#### 5. Audio Momentum Growth Rate ($M_{\text{audio}}$)
$$M_{\text{audio}} = \frac{\text{ReelsCount}(T) - \text{ReelsCount}(T - 48h)}{\text{ReelsCount}(T - 48h)} \times 100\%$$
*Calculates 48-hour velocity growth for emerging audio tracks to catch early trend adoption before market saturation.*

#### 6. Share-to-Like Ratio ($SLR$)
$$SLR = \frac{\text{Shares}}{\text{Likes}}$$

#### 7. Comment-to-View Ratio ($CVR$)
$$CVR = \frac{\text{Comments}}{\text{Views}} \times 100\%$$

#### 8. Geographic Comment Concentration ($GCC$)
$$GCC = \frac{\text{Uzbek / Tashkent Vernacular Comments in Random 100-Sample}}{\text{Total Sampled Comments (100)}} \times 100\%$$

### 3.3 Quantitative Qualification Gate Thresholds

A candidate video advances to Step 3 ONLY if it satisfies the quantitative gate thresholds:

| Metric | Minimum Qualification Threshold | Strategic Rationale |
| :--- | :--- | :--- |
| **24h Velocity** | $\text{Velocity}_{24h} > 50{,}000\text{ views}$ | Isolates organic viral breakout from baseline organic creator impressions. |
| **Velocity Rate** | $VPH > 2{,}000\text{ views/hour}$ | Confirms that active algorithmic distribution is currently accelerating. |
| **Viral Acceleration** | $a_{\text{viral}} > 0\quad (\text{Breakout: } VPH \ge 10{,}000 \text{ and } a_{\text{viral}} > 0)$ | Validates non-linear exponential growth curve before peak distribution saturation. |
| **Shareability Coefficient** | $Q_{\text{viral}} \ge 0.05\quad (5.0\%)\quad (\text{Extreme: } Q_{\text{viral}} > 0.08)$ | Composite engagement coefficient confirming high DM forwarding and Telegram saves. |
| **Audio Momentum** | $M_{\text{audio}} > 100\%\text{ in 48h}\quad (\text{ReelsCount} < 10{,}000)$ | Pinpoints high-velocity emerging audio tracks within the optimal 48-hour adoption window. |
| **Share-to-Like Ratio** | $SLR > 25\%\quad (\text{Ratio} \ge 0.25)$ | The definitive indicator of private DM / Telegram group forwarding in Uzbekistan. |
| **Comment Density** | $CVR > 0.8\%\quad (\ge 8\text{ comments per } 1{,}000\text{ views})$ | Proves active cultural dialogue and user engagement rather than passive scrolling. |
| **Geographic Purity**| $GCC \ge 75\%$ | Filters out international algorithmic leakage; verifies that the audience is located in Uzbekistan. |

### 3.4 Disqualification Rules
* **Dead Trend Rule**: Total views $>5{,}000{,}000$ with $VPH < 500$ (Trend has already crested and saturated; late adoption will result in audience fatigue).
* **Bot-Farm Rule**: Likes $>50{,}000$ with $CVR < 0.1\%$ or comments consisting exclusively of single emojis or foreign accounts.
* **Non-Compliant Master Rule**: Content reliant on un-parodyable global studio masters that cannot be adapted for business profiles.

### 3.5 Velocity Qualification Decision Flowchart

```
                          RAW CANDIDATE POOL (50 VIDEOS)
                           (Instagram, YouTube, Telegram)
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │ GATE 1: Initial Velocity & Volume     │
                     │  • Velocity_24h > 50,000 views?       │
                     │  • VPH > 2,000 views/hour?            │
                     └───────────────────┬───────────────────┘
                                         │
                                ┌────────┴────────┐
                                │ NO              │ YES
                                ▼                 ▼
                          DISQUALIFIED    ┌───────────────────────────────────────┐
                          (Baseline)      │ GATE 2: Acceleration & Audio Momentum │
                                          │  • a_viral > 0 (Exponential growth)?  │
                                          │  • If Audio: M_audio > 100% in 48h?   │
                                          └───────────────────┬───────────────────┘
                                                              │
                                                     ┌────────┴────────┐
                                                     │ NO              │ YES
                                                     ▼                 ▼
                                               DISQUALIFIED    ┌───────────────────────────────────────┐
                                               (Plateaued)     │ GATE 3: Cultural & Audience Purity    │
                                                               │  • Q_viral >= 0.05 (High intent)?     │
                                                               │  • SLR > 25% & CVR > 0.8%?            │
                                                               │  • GCC >= 75% (Uzbekistan geo)?       │
                                                               └───────────────────┬───────────────────┘
                                                                                   │
                                                                          ┌────────┴────────┐
                                                                          │ NO              │ YES
                                                                          ▼                 ▼
                                                                    DISQUALIFIED    ┌───────────────────────────────────────┐
                                                                    (Non-local/Bot) │ QUALIFIED TOP 5 BREAKOUT TRENDS       │
                                                                                    │ (Proceeds to Step 3 Deconstruction)   │
                                                                                    └───────────────────────────────────────┘
```

---

## 4. Step 3: Sound & Cultural Deconstruction (Tuesday 10:00 – 13:00)

### 4.1 Scope & Purpose
To reverse-engineer the psychological and musical anatomy of the Top 5 qualified trends, identifying the exact cultural tension, musical meter, and hook pattern to adapt for Bayram Bot.

### 4.2 Deconstruction Protocol Checklist

#### Part A: Audio Source Classification & Rights Mapping
Every qualified trend must be assigned to one of Bayram Bot's four legal compliance tiers:
1. **Tier 1 (Bot Original)**: Can this concept be executed using a 100% original Bayram Bot song (`Genre.POP`, `Genre.UZBEK_POP`, `Genre.SHASHMAQOM`, etc.)?
2. **Tier 2 (Rhythm Parody Bed)**: If the trend relies on a commercial hit (e.g. Hamdam Sobirov's "Peshta"), compose an original royalty-free instrumental bed matching the identical tempo and meter with original parody lyrics.
3. **Tier 3 (Native Audio Stitch)**: Can the trend be hijacked through influencer partner accounts using the native audio sticker?
4. **Tier 4 (Spoken Dialogue + Cleared Stems)**: Does the trend rely on spoken dialogue/skits that can be paired with cleared traditional acoustic stems?

#### Part B: Musical Meter & Acoustic Analysis
* **Tempo Extraction**: Determine exact BPM using terminal command:
  ```bash
  aubio tempo -i audio_sample.wav
  ```
  or Python `librosa`:
  ```python
  import librosa
  y, sr = librosa.load("audio_sample.wav")
  tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
  print(f"Detected BPM: {tempo:.1f}")
  ```
* **Time Signature Identification**:
  * $6/8$ Metric Groove: Khorezmian *Lazgi* meter; requires *yelka qoqish* (shoulder pop) choreography.
  * $4/4$ Contemporary Pop / Hip-Hop: 90–124 BPM; syncopated vocal drops.
  * $3/4$ Traditional Waltz / Ballad: 72–84 BPM; emotional family milestone delivery.
* **Transient Beat Drop Timestamp**: Pinpoint exact millisecond timestamp (e.g., $t=0:02.40$ or $t=0:10.50$) where the visual pattern interrupt must synchronize with the audio transient.

#### Part C: Cultural Tension Mapping
Map the trend against the 6 core Uzbek viral cultural tension codes:
1. *Ota-onaga ehtirom* (Filial piety / parent tears / migrant sacrifice)
2. *Qarz va Click madaniyati* (Borrowing money / fintech dilemmas / saving face)
3. *Toʻy va sarpo majburiyatlari* (Wedding costs / toast anxieties / dowry comparisons)
4. *Musofirlik sogʻinchi* (Diaspora yearning / distant reunions)
5. *Milliy raqs va yelka qoqish* (Spontaneous festive release / Lazgi kinetic energy)
6. *Ism va talaffuz gʻururi* (Linguistic dignity / native phonetic pride)

#### Part D: Hook Pattern Interrupt Decode
Deconstruct the first 3.0 seconds of the source video:
* **Frame-0 Visual**: What is the visual shock or curiosity gap at 0.0s?
* **Audio Cue**: What is the opening sound effect or spoken line?
* **Text Hook**: What is the framing banner formula (e.g., *"X boʻlganda nima qilasiz?"*)?

---

## 5. Step 4: Rapid Content Production Sprint (Tuesday 14:00 – Thursday 21:30)

### 5.1 Scope & Purpose
To execute an agile 48-hour production turnaround, writing, filming, editing, and publishing **2 responsive video assets** tailored for Bayram Bot before trend velocity wanes.

### 5.2 48-Hour Production Sprint Timeline

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             48-HOUR AGILE PRODUCTION TIMELINE                                    │
├───────────────────┬──────────────────────────────────────────────────────────────────────────────┤
│ TIME (UZT)        │ OPERATIONAL DELIVERABLES & MILESTONES                                        │
├───────────────────┼──────────────────────────────────────────────────────────────────────────────┤
│ Tuesday 14:00     │ Creative Greenlight Meeting: Creative Director selects top 2 concepts from  │
│                   │ the R3 slate mapping to the week's qualified trends.                         │
│ Tuesday 16:00     │ Script Finalization: Verbatim bilingual hooks (Uzbek Latin & Russian) locked │
│                   │ with exact on-screen `#FFE600` banner copy and safe-zone markings.           │
│ Wednesday 09:00   │ Production Phase A (Live Action): Videographer and actors execute physical   │
│                   │ shoot (courtyard, restaurant, or street setting).                            │
│ Wednesday 11:00   │ Production Phase B (AI Video): Prompt engineer generates keyframes and video │
│                   │ choreography using Higgsfield MCP or 3D pipeline for mascot concepts.        │
│ Wednesday 14:00   │ Audio Engineering: Sound engineer generates bot audio via `@bayram_uzbot`    │
│                   │ or tracks Tier 2 parody vocals locked to extracted BPM.                      │
│ Thursday 09:00    │ Post-Production Assembly: Video editor synchronizes visual beat drop with    │
│                   │ audio transients, burns in kinetic subtitles, and checks 9:16 safe zones.    │
│ Thursday 14:00    │ Pre-Flight QA Gate: Automated validation script checks aspect ratio, text    │
│                   │ placement, price banner (`15 000 soʻm`), and Telegram handle integrity.      │
│ Thursday 18:30    │ Hero Video Launch: Publish Video 1 during peak Tashkent evening engagement   │
│                   │ window (18:30 – 21:30 UZT).                                                  │
│ Friday 19:00      │ Secondary Video Launch: Publish Video 2 during weekend kickoff window.       │
└───────────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Publishing Windows for Uzbekistan
* **Primary Peak Window (Highest Engagement)**: Thursday & Friday, 18:30 – 21:30 UZT (Commute end, family dinner, evening leisure).
* **Secondary Weekend Window**: Saturday & Sunday, 12:00 – 15:00 UZT (Choyxona gatherings, family lunches).

---

## 6. Weekly Monitoring Roles & Responsibilities Matrix

The execution of this SOP operates under a strict RACI (Responsible, Accountable, Consulted, Informed) governance framework:

| Role | Primary Responsibilities | Step 1 (Disc.) | Step 2 (Velo.) | Step 3 (Decon.) | Step 4 (Sprint) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Social Intelligence Lead** | Manages scrapers, compiles candidate log, calculates $VPH$ and $SLR$ metrics, enforces qualification thresholds. | **A / R** | **A / R** | **C** | **I** |
| **Creative Director** | Selects target trends, greenlights concepts from R3 slate, oversees brand voice and cultural dignity rules. | **C** | **C** | **A / R** | **A** |
| **Uzbek/Russian Scriptwriter**| Authors verbatim bilingual hooks, ensures correct Uzbek Latin orthography (`oʻ`, `gʻ`), writes CTA scripts. | **I** | **I** | **R** | **R** |
| **Video Producer / AI Artist**| Shoots live-action footage or animates AI keyframes via Higgsfield, ensures 9:16 safe zones. | **I** | **I** | **C** | **R** |
| **Sound Designer / Audio Eng.**| Analyzes BPM, tracks parody beds, generates bot audio via `@bayram_uzbot`, aligns beat drops. | **I** | **I** | **R** | **R** |
| **Community & Growth Manager** | Publishes posts in peak windows, pins deep-link CTA comments, monitors DM conversion in Telegram. | **I** | **I** | **I** | **R** |

*Legend: **A** = Accountable; **R** = Responsible; **C** = Consulted; **I** = Informed.*

---

## 7. Escalation Criteria & Emergency Trend Hijacking Protocol

### 7.1 Breakout Mega-Trend Trigger
If a video in the candidate pool exhibits hyper-acceleration surpassing the following **Emergency Velocity Criteria**:
* **$VPH > 10{,}000\text{ views/hour}$** within the first 6 hours of posting, OR
* **Total Views $>500{,}000$** in under 12 hours with $SLR > 35\%$, OR
* A spontaneous nationwide cultural meme or national music release (e.g. new Hamdam Sobirov or Ozodbek Nazarbekov album drop) dominating all Tashkent Telegram channels.

### 7.2 The 12-Hour Flash Production Sprint
Upon declaration of an Emergency Breakout by the Social Intelligence Lead:
1. **Immediate Standup (T+0h)**: Social Intelligence Lead alerts Creative Director and Sound Designer via priority Telegram notification.
2. **Concept Adaptation (T+1h)**: Creative Director matches the mega-trend to an existing pre-scripted concept from the R3 slate (Concepts 1–12).
3. **Rapid Audio Track (T+3h)**: Sound engineer generates or tracks the parody bed within 120 minutes.
4. **Fast-Track Production (T+8h)**: Video team utilizes single-setup live studio capture or pre-rendered Higgsfield mascot motion control templates.
5. **Emergency Publish (T+12h)**: Video is cleared through pre-flight QA and published within 12 hours of initial trend detection, capturing maximum top-of-curve algorithmic reach.

---

## 8. Decision Trees & Operational Flowcharts

### 8.1 Trend Qualification Decision Tree

```
[Candidate Video Discovered]
          │
          ▼
Is 24h Views > 50,000 AND VPH > 2,000?
    ├── NO  ──> [DISQUALIFY: Insufficient Growth Velocity]
    └── YES ──> [Check Engagement Quality]
                      │
                      ▼
               Is Share-to-Like Ratio > 25%?
                   ├── NO  ──> [DISQUALIFY: Low Private DM Sharing]
                   └── YES ──> [Check Geographic Purity]
                                     │
                                     ▼
                              Is UZ Language Comments >= 75%?
                                  ├── NO  ──> [DISQUALIFY: Foreign Algorithmic Leakage]
                                  └── YES ──> [Check Lifetime Volume]
                                                    │
                                                    ▼
                                             Is Total Views < 5,000,000?
                                                 ├── NO  ──> [DISQUALIFY: Trend Saturated]
                                                 └── YES ──> [QUALIFIED: Advance to Step 3]
```

### 8.2 Audio Compliance & Rights Decision Tree

```
[Qualified Viral Trend]
          │
          ▼
Does the trend rely on a copyrighted commercial pop studio master?
    ├── NO (Relies on dialogue, meme sound effect, or royalty-free audio)
    │     └──> [ROUTE TO TIER 4: Spoken Dialogue + Cleared Ethnic Stems]
    │          - Record clean dialogue
    │          - Layer cleared dutar/doira background
    │          - Safe for all business ad boosts
    │
    └── YES (Commercial pop track e.g. "Peshta")
          │
          ▼
    Is an original Bayram Bot genre song sufficient for the emotional payoff?
        ├── YES ──> [ROUTE TO TIER 1: 100% Bot-Generated Original Song]
        │           - Select from 10 native genres
        │           - Full commercial ownership
        │           - Registered as brand Original Audio
        │
        └── NO  ──> [ROUTE TO TIER 2: Rhythm-Synchronized Parody Bed]
                    - Re-track instrumental at exact BPM (e.g. 95.8 BPM / 126 BPM)
                    - Write original parody lyrics ("Tabriklarim mani jonim, botda...")
                    - Derivative parody safe for business profiles
```

### 8.3 Production Route Decision Tree

```
[Concept Execution Greenlight]
          │
          ▼
Is the concept character-driven / absurd mascot (e.g. Alabay Squad)?
    ├── YES ──> [ROUTE: Higgsfield AI Video / 3D Animation Pipeline]
    │           - Render 9:16 portrait keyframes
    │           - Apply Motion Control choreography
    │           - 48h turnaround
    │
    └── NO  ──> Does it require public interaction (e.g. Chorsu street test)?
                  ├── YES ──> [ROUTE: Live Street Vox-Pop Production]
                  │           - Wireless lavaliers + stabilizer gimbal
                  │           - 2-hour field shoot in Tashkent
                  │
                  └── NO  ──> [ROUTE: Staged Relatable Courtyard/Banquet Skit]
                              - Single location (hovli or dining room)
                              - 2 actors in traditional attire
                              - 3-hour shoot, fast assembly
```

---

## 9. Trend Logging & Performance Telemetry Template

Every executed trend response is archived in the quarterly virality database (`Bayram_Virality_Archive_2026.csv`) with the following standardized performance schema:

| Field Name | Data Type | Description & Format Example |
| :--- | :--- | :--- |
| `Sprint_ID` | String | Unique identifier: `SPRINT-2026-W38-01` |
| `Trend_Source_URL` | String | Source URL of original viral video |
| `Source_Velocity_24h` | Integer | Total views gained in 24h by source: `1,120,000` |
| `Source_SLR` | Float | Share-to-like ratio of source: `0.34` (34%) |
| `Bayram_Concept_ID` | String | Mapping to R3 slate: `Concept 01 (Qaynona-Kelin)` |
| `Audio_Compliance_Tier`| String | `Tier 1 (Bot Original)` / `Tier 2 (Parody Bed)` |
| `Bayram_Reel_URL` | String | Published video link on `@bayrambot` |
| `Views_24h_Actual` | Integer | First 24-hour view count achieved: `145,000` |
| `Shares_24h_Actual` | Integer | Direct shares generated: `28,400` |
| `Telegram_CTR` | Float | Click-through rate from Instagram bio to `@bayram_uzbot`: `4.8%` |
| `Songs_Generated_Count`| Integer | Total paid 15,000 UZS songs created via deep-link: `342` |
| `ROI_Multiple` | Float | Revenue generated vs production cost: `3.8x` |
