# BayramBot "Wellerman" Video Production Blueprint & UGC Strategy

**Document Reference**: `marketing/campaigns/wellerman/02_production_blueprint.md`  
**Campaign**: BayramBot ("Wellerman" Sea Shanty Parody Viral Campaign)  
**Target Ratios**: 9:16 Vertical Video (Instagram Reels, TikTok, YouTube Shorts)  
**Target Duration**: 28–34 seconds  
**Audio Alignment**: 96–100 BPM; 4/4 Syncopated Stomp-Clap Grid  
**Status**: Production-Ready  

---

## 1. Frame-0 Hook & Retention Engineering

In the Uzbek short-form ecosystem, users swipe away within **1.1 to 1.4 seconds** if there is no immediate pattern interrupt. The "Wellerman" shanty structure solves this through physical acoustics and visual progression:

### 1.1 Visual Pattern Interrupt (0:00 - 0:02)
* **Visual Anchor**: Close-up on hands slamming a wooden table or beating chest in precise cadence.
* **On-Screen High-Contrast Banner**: Canary Yellow (`#FFE600`) text on Rich Black (`#121212`) box positioned between $y=300\text{px}$ and $y=420\text{px}$.
  - *Uzbek Latin*: **"SOVG'AGA 15 MING SO'M QOLGANDA... 😭"**
  - *Russian Alternative*: **"КОГДА НА ПОДАРОК ОСТАЛОСЬ 15 000 СУМ... 💀"**

---

## 2. Split-Screen "Choir Duet Chain" Staging

The defining virality mechanism of Nathan Evans' original video was the **Duet Chain**. The video visually and acoustically expands as follows:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   SPLIT-SCREEN TEMPORAL PROGRESSION                     │
├────────────────────┬────────────────────┬──────────────────────────────┤
│ TIMECODE           │ VISUAL LAYOUT      │ AUDIO STEM CONTRIBUTION      │
├────────────────────┼────────────────────┼──────────────────────────────┤
│ 0:00 - 0:07.5      │ Full Screen 1x     │ Lead Vocal + Table Stomp     │
│ 0:07.5 - 0:15.0    │ 2-Way Split (1x2)  │ + Deep Baritone Bass Drone   │
│ 0:15.0 - 0:22.5    │ 4-Way Split (2x2)  │ + Tenor Harmony + Doira Clap │
│ 0:22.5 - 0:30.0    │ Full Screen / Bot  │ Full Polyphonic Shanty Choir │
└────────────────────┴────────────────────┴──────────────────────────────┘
```

### Detailed Shot Progression:
1. **Shot 1 (0:00 - 0:07.5) [Solo Lead]**:
   - Single creator sits at desk/table, knocks on the table rhythmically, singing Verse 1.
   - At the end of line 4: Creator looks deadpan into camera and shouts **"(HUH!)"** while punching down.
2. **Shot 2 (0:07.5 - 0:15.0) [The Bass Joins]**:
   - Screen splits into left and right.
   - Right side: Second creator in traditional do'ppi or casual hoodie appears, singing deep bass drone: *"Bum... bum... bum-bum-bum..."*.
3. **Shot 3 (0:15.0 - 0:22.5) [The Harmony & Doira]**:
   - Screen splits into 4 quadrants.
   - Top right: Third singer adds high tenor harmonies.
   - Bottom right: Fourth person beats a live traditional Uzbek **doira** on the backbeats.
   - Collective shout at the end of Verse 2: **"(HUH!)"** in unison!
4. **Shot 4 (0:22.5 - 0:30.0) [The Drop & Bot Payoff]**:
   - Audio drop into Chorus: *"Tezroq BayramBot kelsin..."*.
   - Quick jump-cut or overlay of the Telegram bot `@bayram_uzbot` generating the song with the recipient's name in green text.
   - Characters celebrate and dance in their split quadrants.
5. **Shot 5 (0:30.0 - 0:34.0) [CTA & Outro]**:
   - Big text banner: **"@bayram_uzbot — 15 000 so'mga shaxsiy hit!"**.

---

## 3. Audio Engineering & Mobile Mixing Standard

To ensure the reel punches through small smartphone speakers (iPhone, Redmi, Samsung) without distortion:

1. **Target Integrated Loudness**: **-14.0 LUFS** ($\pm 0.5 \text{ LUFS}$), True Peak: **-1.0 dBTP**.
2. **The Stomp-Clap Transient Stack**:
   - **Kick/Table Stomp**: High-pass filter at 35 Hz to remove unnecessary sub-rumble; boost at 80 Hz and 2.5 kHz for sharp wooden slap attack.
   - **Clap/Snare**: Stereo spread at 1.5 kHz – 4 kHz with 0.15s plate reverb.
3. **Vocal Processing**:
   - Lead Baritone: Centered, heavy 4:1 compression, subtle tape saturation.
   - Bass Drone: Panned center, compressed with fast attack.
   - Choir Harmonies: Panned 45% Left and 45% Right for immersive stereo width.
4. **The Iconic Shout "(HUH!)"**:
   - High transient boost, short gated reverb (300ms decay), volume peak at +2dB above average vocal level.

---

## 4. Viral Caption, Sound & Distribution Strategy

### 4.1 Native Sound Strategy
* **Sound Title on Instagram/TikTok**: `BayramBot - Wellerman (Uzbek Shanty Parody)`
* **Duet/Remix Permission**: Set to **"Allow Duets / Allow Stitches"**.
* **Pinned Comment**:
  > *"Siz ham do'stingiz ismini yozing, xor bo'lib kuylab beramiz! 😂👇 @bayram_uzbot orqali 90 soniyada o'zingiz ham tayyorlashingiz mumkin!"*

### 4.2 Posting Copy Kit

```text
Do'stingizga, qaynonangizga yoki hamkasbingizga nima sovg'a qilishni bilmayapsizmi? 😂
15 000 so'mga ismini aytib kuylaydigan shaxsiy hit qo'shiq yarating! 🎶

Telegramda: @bayram_uzbot 🤖

#bayrambot #wellerman #seashanty #uzbekistan #tashkent #samarkand #tiktokuz #uzbekreels #prikoluz #kulgu #tugilgankun #sovga
```
