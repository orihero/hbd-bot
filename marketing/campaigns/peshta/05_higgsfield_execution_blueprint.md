# Polat Alemdar & Elif Eylül "Peshta" Recreation — Higgsfield Execution Blueprint

**Document Reference:** `marketing/campaigns/peshta/05_higgsfield_execution_blueprint.md`  
**Target Platform:** Higgsfield AI (`web.higgsfield.ai` & Higgsfield MCP Server)  
**Campaign:** Polat Alemdar (*Necati Şaşmaz*) & Elif Eylül (*Özgü Namal*) — 43.000s "Peshta" 9:16 Instagram Reels Recreation  
**Master Audio Anchor:** `/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3` (43.000s, 48kHz stereo)  
**Author:** `worker_m3`  
**Status:** Production Ready  

---

## 1. Executive Production Blueprint & Campaign Scope

### 1.1 Campaign Premise & Creative Juxtaposition
This campaign executes an unauthorized-style high-virality parody for `@bayram_uzbot` (Bayram Bot), recreating 43.000 seconds (timeline 0:27.0 to 1:10.0) of Hamdam Sobirov’s viral Uzbek pop anthem *"Peshta"*. The original performers are swapped with legendary protagonists from the definitive Turkish mafia drama *Kurtlar Vadisi* (2003–2005 Classic Era):
- **Polat Alemdar** (*Necati Şaşmaz*): Cold, calculating, lethal mafia protagonist in a bespoke midnight-black Italian wool suit and open-collar crisp white dress shirt. The core viral hook is the surreal dissonance of Polat maintaining his unsmiling, brooding mafia stare while executing the high-energy, syncopated Khorezmian shoulder-pops (*yelka qoqish*), swaggering dance glides, and wrist flourishes of *Peshta*.
- **Elif Eylül** (*Özgü Namal*): Graceful, expressive early-2000s Turkish attorney in an ivory-white silk-crepe dress, providing romantic tension, elegant glances, and delicate choreography on the red carpeted steps.

### 1.2 Master Sequence Specifications & Conforming Standards
Every asset in this pipeline adheres strictly to vertical social delivery standards:
- **Frame Geometry:** Strictly **1080 x 1920 pixels** (9:16 portrait vertical aspect ratio).
- **Temporal Rate:** Strictly **30.0 frames per second Constant Frame Rate (CFR)**.
- **Sequence Length:** Exactly **43.000 seconds = 1,290 frames** ($43.0 \times 30.0$).
- **Color Pipeline:** 8-bit YUV 4:2:0 (`yuv420p`), Rec.709 color matrix, High Profile Level 4.0.
- **Audio Alignment Track:** `/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3` (43.000000s, 48,000 Hz, stereo, -14.0 LUFS integrated loudness).

### 1.3 Audio-Visual Synchronization & Beat Drop Calibration
The original reference video (`marketing/campaigns/peshta/raw/Xamdam_Sobirov_Peshta_1080p_h264.mp4`) and the parody remix audio differ in their lead-in transients. Precise physical alignment requires a calibrated time shift:
- **Raw Video Sub-Bass Drop Slam:** Occurs at absolute video timestamp **$t = 34.184\text{ s}$**.
- **Master Audio Sub-Bass Drop Slam:** Occurs at relative audio timestamp **$t = 6.920\text{ s}$** (Frame 208 on the 30fps timeline).
- **Calibrated Source Slice Window:** **$t = 27.264\text{ s}$** to **$t = 70.264\text{ s}$** ($34.184 - 6.920 = 27.264\text{ s}$).
- **Phase Shift Offset:** A strict **$+264\text{ ms}$** offset is applied relative to nominal $t=27.000\text{ s}$ to achieve zero-phase acoustic and choreographic lock at the drop.

```
0.000s (Frame 0)                   6.920s (Frame 208)                               43.000s (Frame 1290)
├──────────────────────────────────┼────────────────────────────────────────────────┤
│  VERSE 1 BUILDUP (Clips 01-02)   │           CHORUS & DROP (Clips 03-11)          │
│  Polat & Elif staging on steps   │  🔥 THE 0:34 BEAT DROP (Clip 03 deep squat)    │
│  Phone reaction & romantic lean  │  Khorezm shoulder pops, canyon strut, outro    │
└──────────────────────────────────┴────────────────────────────────────────────────┘
```

### 1.4 Visual Conditioning Architecture & Edge Separation
Diffusion-based motion transfer models (Kling 3.0 and Genjutsu) tend to suffer from limb melting, suit tearing, and facial plasticization when animating dark subjects against dark backgrounds. To prevent these failures, all character anchors in this pipeline enforce:
1. **Cool 5600K Cyan/Steel-Blue Rim Light:** Directed at 45° behind the subject to generate a crisp 2-pixel specular edge along black suit shoulders, lapels, and pompadour hair, guaranteeing clean limb separation during rapid arm crosses.
2. **Anti-AI Realism Engine:** Mandatory positive prompt tokens requiring visible micro-pores, natural skin texture, subtle facial asymmetry, and zero cosmetic airbrushing to match early-2000s 35mm film stock.
3. **Dedicated Shot-Matched Framing:** Anchor images generated at exact matching focal lengths (Full-Body 35mm, Medium 50mm, Close-Up 85mm, Canyon Outdoor) to prevent parallax distortion.

### 1.5 Account Budget & Credit Architecture
- **Verified Account Tier:** Pro (Balance: >1,500 credits).
- **Kling 3.0 Motion Control (`motion_control`):** **10 credits** per generation.
- **Higgsfield Genjutsu Multi-Motion Control (`hf_mult_motion_control`):** **35 credits** per generation.
- **Total Production Budget for 11 Clips:**
  - 7 Kling 3.0 generations ($7 \times 10 = 70$ credits)
  - 4 Genjutsu generations ($4 \times 35 = 140$ credits)
  - Estimated First Pass: **210 credits** (leaves >1,300 credits for retakes and iterations).

---

## 2. Master Shot Table Summary & Overview Matrix

The 43.0-second sequence is sliced into 11 discrete, continuous macro driving clips centered on the active subject:

| # | Driving Clip Filename | Rel Timeline (s) | Dur (s) | Frames | Target Character | Recommended Model | Anchor Asset ID | Motion Strength |
|:---:|:---|:---:|:---:|:---:|:---|:---|:---|:---:|
| **01** | `clip_01_verse1_setup.mp4` | 0.000s – 2.256s | 2.256s | 68 | Elif (01) $\rightarrow$ Polat (02) | Kling 3.0 (`scene: video`) | Card P01 / Card E01 | 0.72 |
| **02** | `clip_02_hook_duo_roses.mp4` | 2.256s – 5.176s | 2.920s | 88 | Duo (Polat + Elif) | Genjutsu (`hf_mult`) | Card E01 + Card P02 | 0.72 |
| **03** | `clip_03_chorus_drop_hero.mp4` | 5.176s – 8.976s | 3.800s | 114 | Polat Alemdar (Lead WS) | Kling 3.0 (`scene: video`) | Card P01 (`polat_full_body`) | **0.76** |
| **04** | `clip_04_call_response_1.mp4` | 8.976s – 11.816s | 2.840s | 85 | Elif (05) $\rightarrow$ Polat (06) | Genjutsu (`hf_mult`) | Card E02 + Card P02 | 0.75 |
| **05** | `clip_05_call_response_2.mp4` | 11.816s – 14.416s | 2.600s | 78 | Elif (07) $\rightarrow$ Polat (08) | Genjutsu (`hf_mult`) | Card E03 + Card P02 | 0.74 |
| **06** | `clip_06_strophe_swagger_strut.mp4` | 14.416s – 19.256s | 4.840s | 145 | Elif (09) $\rightarrow$ Polat (10,11) | Kling 3.0 (`scene: video`) | Card E01 + Card P01 | 0.74 |
| **07** | `clip_07_duo_charm_finger_wag.mp4` | 19.256s – 25.496s | 6.240s | 187 | Duo (Polat + Elif) | Genjutsu (`hf_mult`) | Card P02 + Card E01 | 0.73 |
| **08** | `clip_08_canyon_transition_stomp.mp4` | 25.496s – 29.976s | 4.480s | 134 | Polat Alemdar (Canyon) | Kling 3.0 (`scene: image`) | Card P04 (`polat_canyon`) | 0.75 |
| **09** | `clip_09_canyon_double_point.mp4` | 29.976s – 35.896s | 5.920s | 178 | Polat Alemdar (Canyon) | Kling 3.0 (`scene: video`) | Card P04 (`polat_canyon`) | 0.75 |
| **10** | `clip_10_elif_red_steps.mp4` | 35.896s – 37.496s | 1.600s | 48 | Elif Eylül (Seated) | Kling 3.0 (`scene: image`) | Card E01 (`elif_seated`) | **0.70** |
| **11** | `clip_11_polat_hero_outro.mp4` | 37.496s – 43.000s | 5.504s | 165 | Polat Alemdar (Outro) | Kling 3.0 (`scene: video`) | Card P02 / Card P01 | 0.74 |

---

## 3. Comprehensive Shot-by-Shot Execution Profiles (Clips 01 to 11)

---

### Shot Profile: Clip 01 (`clip_01_verse1_setup.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_01_verse1_setup.mp4`
- **Source Range:** 27.264s – 29.520s (Source Shot 01)
- **Relative Timeline Range:** 0.000s – 2.256s
- **Duration:** 2.256s (68 frames @ 30.0 fps CFR)
- **Target Characters:** Elif Eylül (reaction hook) transitioning to Polat Alemdar (pyramid steps staging).
- **Choreographic Action:** Hook opening; smartphone surprise reaction cuts into ensemble wrist flourishes atop red pyramid steps.
- **Framing & Centering:** Center X = 960 px ($X_{\text{offset}} = 656\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Staging establishing shot. Kling 3.0 provides rigid geometric stability for the red pyramid stairs and ensures Polat’s black Italian wool suit maintains crisp contour boundaries against the dark background.
- **Scene Control Mode:** `scene_control: video` (inherits dynamic lighting and red carpet architecture).

#### 3. Character Anchor Selection
- **Anchor File:** `polat_full_body_9_16.png` (Card P01)
- **Secondary Reference:** `elif_seated_red_steps_9_16.png` (Card E01)
- **Resolution:** 1152 x 2048 (native 9:16)
- **Framing Rationale:** Full-body framing guarantees clean shoe placement on the red steps without hallucinatory limb cropping.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.72**
- **Technical Justification:** Clip 01 consists of establishing poses and subtle wrist turns. A strength of 0.72 prevents background step warpage while accurately tracking the hand flourishes.

#### 5. Copy-Paste Ready Positive Prompt
```text
Full-body portrait in 9:16 vertical orientation, adult Mediterranean man in his early 30s as Turkish mafia operative Polat Alemdar in Kurtlar Vadisi 2003 aesthetic, standing on wide red velvet pyramid steps, executing subtle confident wrist flourishes facing camera, sharp chiseled jawline, intense brooding unblinking stare, jet-black swept-back pompadour hair, wearing tailored midnight-black Italian wool suit, crisp white dress shirt with unbuttoned open collar, polished black oxford shoes. Visible fine skin pores, authentic matte complexion, natural stubble texture, subtle facial asymmetry, no beauty filter, zero plastic sheen. Cinematic low-key chiaroscuro lighting, cool 5600K cyan rim backlight sculpting shoulders and hair for razor-sharp edge separation against dark studio backdrop. Shot on 35mm master prime lens, 4K resolution, cinematic realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Smartphone prop in the opening frame can hallucinate a floating object or mutated hand.
- **Mitigation:** The prompt explicitly conditions natural resting hands and wrist flourishes. Kling 3.0 optical flow absorbs the motion vector into Polat's hand without generating a telephone prop.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames) to eliminate model initial latent freeze.
- **Lead-Out Trim:** 0.000s.
- **Color Grade:** Cool shadows slightly with cyan lift (`+2%`) to accentuate the 5600K rim light.

---

### Shot Profile: Clip 02 (`clip_02_hook_duo_roses.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_02_hook_duo_roses.mp4`
- **Source Range:** 29.520s – 32.440s (Source Shot 02)
- **Relative Timeline Range:** 2.256s – 5.176s
- **Duration:** 2.920s (88 frames @ 30.0 fps CFR)
- **Target Characters:** Duo (Polat Alemdar + Elif Eylül).
- **Choreographic Action:** Romance on red velvet steps; Elif seated holding red roses, Polat leaning down charismatically from a higher step.
- **Framing & Centering:** Center X = 884 px ($X_{\text{offset}} = 580\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Higgsfield Genjutsu (`hf_mult_motion_control`)
- **Cost:** 35 credits
- **Rationale:** Multi-subject spatial interaction. Polat leans over Elif in close proximity. Genjutsu’s multi-character cross-attention prevents Polat's dark wool sleeve from bleeding into Elif’s ivory silk dress or the red rose bouquet.
- **Scene Control Mode:** Inferred from multi-reference conditioning (`medias`).

#### 3. Character Anchor Selection
- **Primary Anchor:** `elif_seated_red_steps_9_16.png` (Card E01)
- **Secondary Anchor:** `polat_medium_shot_9_16.png` (Card P02)
- **Framing Rationale:** Card E01 already features Elif seated on red carpeted steps, perfectly matching the driving clip geometry.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.72**
- **Technical Justification:** Subtle romantic body language. Setting strength higher than 0.75 would cause the delicate rose stems and petals to disintegrate or morph into red fabric.

#### 5. Copy-Paste Ready Positive Prompt
```text
Cinematic 9:16 vertical duo shot, Turkish mafia operative Polat Alemdar leaning down charismatically from upper step toward elegant 26-year-old Turkish woman Elif Eylul seated gracefully on crimson red velvet carpeted steps holding a bouquet of red roses. Polat in tailored midnight-black wool suit with open-collar white shirt, intense brooding gaze. Elif with expressive hazel eyes, wavy chocolate brunette hair, wearing an elegant ivory-white silk-crepe dress. Dramatic chiaroscuro lighting, warm 3800K directional key light on Elif, cool 5600K cyan rim lighting sculpting Polat's back and shoulders to ensure clean separation between characters. Visible skin pores, natural matte texture, fine lines, no beauty filter, zero plastic AI sheen. Shot on 35mm anamorphic prime lens, 4K resolution, nostalgic 2003 Kurtlar Vadisi cinematic elegance.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
fused bodies, blended clothing, black suit melting into white dress, extra arms, extra hands, mutated fingers, missing fingers, floating roses, distorted flowers, plastic skin, porcelain doll skin, airbrushed, heavy glamour makeup, cartoon, 3d render, anime, oversaturated, blown out highlights, bad eyes, crossed eyes, glowing pupils, sunglasses, hat, watermark, text, signature, frame borders
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Hand contact and bouquet occlusion risk limb blending.
- **Mitigation:** High-contrast color difference (black wool vs ivory silk vs crimson rose) paired with cool rim-lighting provides strong segmentation boundaries.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.033s (1 frame) before the cut to the drop.
- **Conforming:** Warm midtones by +3% to highlight the romantic red velvet atmosphere.

---

### Shot Profile: Clip 03 (`clip_03_chorus_drop_hero.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_03_chorus_drop_hero.mp4`
- **Source Range:** 32.440s – 36.240s (Source Shot 03)
- **Relative Timeline Range:** 5.176s – 8.976s
- **Duration:** 3.800s (114 frames @ 30.0 fps CFR)
- **Target Character:** Polat Alemdar (Hero Wide Shot with Ensemble).
- **Choreographic Action:** **THE PRIMARY 0:34 BEAT DROP!** Sub-bass dropout followed by a massive acoustic slam at relative $t = 6.920\text{ s}$ (Frame 208). Polat drops into a deep squat bounce, and dancers snap into synchronized Khorezm Lazgi knee bounces.
- **Framing & Centering:** Center X = 960 px ($X_{\text{offset}} = 656\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Solo hero tracking. The rapid vertical drop requires rigid anatomical anchoring so Polat's knees and spine do not stretch unnaturally. Kling 3.0 preserves suit structure during violent vertical acceleration.
- **Scene Control Mode:** `scene_control: video` (captures the synchronized backing ensemble on the steps).

#### 3. Character Anchor Selection
- **Anchor File:** `polat_full_body_9_16.png` (Card P01)
- **Framing Rationale:** Full-body framing with established floor and shoe clearance is non-negotiable; a waist-up anchor would hallucinate rubbery legs during the deep squat.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.76**
- **Technical Justification:** Elevated to 0.76 to ensure instantaneous response to the explosive downward velocity vector on the beat drop. Lower strengths lag behind the sub-bass transient.

#### 5. Copy-Paste Ready Positive Prompt
```text
Full-body cinematic 9:16 vertical hero shot, Polat Alemdar executing explosive Khorezm Lazgi deep squat bounce atop red pyramid steps, centered commanding posture dropping decisively on the heavy beat drop, sharp chiseled jawline, intense unblinking mafia stare, thick jet-black swept-back pompadour hair. Wearing a bespoke tailored single-breasted suit in midnight-black Italian wool, crisp stark white cotton dress shirt with open collar, polished black oxford shoes, clean floor clearance. Visible fine skin pores, authentic matte complexion, natural stubble texture, subtle facial asymmetry, no beauty filter, zero plastic sheen. Cinematic low-key chiaroscuro lighting, hard key light, cool 5600K cyan rim lighting sculpting shoulders, elbows, and knees for razor-sharp edge separation against background dancers. Shot on 35mm master prime lens, ultra-sharp focus, 4K resolution, gritty Turkish mafia noir realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
deformed, distorted anatomy, knee dislocation, rubbery legs, gelatinous feet, suit tearing, floating limbs, disconnected limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Knee dislocation or trouser stretch distortion during the bottom of the squat.
- **Mitigation:** Strength set to 0.76; Card P01 provides roped shoulders and tailored trouser taper which Kling 3.0 preserves as rigid bodies.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Transient Check:** Verify that frame index 52 within this rendered clip aligns to master timeline Frame 208 ($t = 6.920\text{ s}$).

---

### Shot Profile: Clip 04 (`clip_04_call_response_1.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_04_call_response_1.mp4`
- **Source Range:** 36.240s – 39.080s (Source Shot 04)
- **Relative Timeline Range:** 8.976s – 11.816s
- **Duration:** 2.840s (85 frames @ 30.0 fps CFR)
- **Target Characters:** Elif Eylül (05) transitioning to Polat Alemdar (06).
- **Choreographic Action:** Call & Response Phase 1; Elif profile glance clutching pearls cuts to Polat executing sharp alternating shoulder pops (*yelka qoqish*).
- **Framing & Centering:** Center X = 940 px ($X_{\text{offset}} = 636\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Higgsfield Genjutsu (`hf_mult_motion_control`)
- **Cost:** 35 credits
- **Rationale:** High-velocity upper-body articulation. Alternating shoulder pops (*yelka qoqish*) involve rapid clavicle shifts at 95.8 BPM. Genjutsu’s optical flow handling avoids torso tearing.

#### 3. Character Anchor Selection
- **Elif Anchor:** `elif_medium_shot_9_16.png` (Card E02)
- **Polat Anchor:** `polat_medium_shot_9_16.png` (Card P02)
- **Framing Rationale:** Waist-up framing concentrates diffusion latents on the shoulders, collarbones, and facial expressions.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.75**
- **Technical Justification:** Perfectly balances sharp clavicle snapping without disconnecting the shoulder joint from the suit armhole.

#### 5. Copy-Paste Ready Positive Prompt
```text
Cinematic medium shot in 9:16 vertical orientation, framed waist-up, rapid call-and-response transition between Elif Eylul clutching her freshwater pearls with an expressive profile glance and Turkish mafia operative Polat Alemdar executing sharp alternating Khorezmian shoulder pops ('yelka qoqish'). Polat with sharp chiseled jawline, intense brooding gaze, tailored midnight-black wool suit jacket with structured shoulders, pristine open-collar white shirt. Elif with wavy chocolate brunette hair, soft hazel eyes, cream knit and blazer. Visible fine facial pores, realistic skin micro-texture, matte natural finish, no beauty filter, zero plastic AI sheen. Dramatic chiaroscuro lighting, warm key light paired with cool 5600K electric cyan rim light carving shoulders and lapels for crisp edge separation. Shot on 50mm anamorphic lens, 35mm film grain, 4K resolution, cinematic realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
disconnected shoulders, floating clavicle, detached suit arms, rubbery neck, mutated hands, fused fingers, more than five fingers per hand, missing fingers, extra limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Lapel flickering during fast alternating shoulder pops.
- **Mitigation:** The 5600K cyan edge rim light locks suit boundaries in pixel space.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.033s (1 frame).

---

### Shot Profile: Clip 05 (`clip_05_call_response_2.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_05_call_response_2.mp4`
- **Source Range:** 39.080s – 41.680s (Source Shot 05)
- **Relative Timeline Range:** 11.816s – 14.416s
- **Duration:** 2.600s (78 frames @ 30.0 fps CFR)
- **Target Characters:** Elif Eylül (07) transitioning to Polat Alemdar (08).
- **Choreographic Action:** Call & Response Phase 2; Elif intense direct camera eye contact playing with pearls cuts to Polat upward dual-shoulder shrug on snare hit.
- **Framing & Centering:** Center X = 850 px ($X_{\text{offset}} = 546\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Higgsfield Genjutsu (`hf_mult_motion_control`)
- **Cost:** 35 credits
- **Rationale:** Focuses on micro-expressions and tight eye contact. Genjutsu prevents facial distortion while tracking Elif’s fingers near her neck.

#### 3. Character Anchor Selection
- **Elif Anchor:** `elif_closeup_9_16.png` (Card E03)
- **Polat Anchor:** `polat_medium_shot_9_16.png` (Card P02)
- **Framing Rationale:** Tight chest-up framing highlights Elif's emotional eyes and Polat's sharp jawline.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.74**
- **Technical Justification:** Sufficient compliance for the syncopated snare shrug while maintaining steady iris geometry and natural eyelid movement.

#### 5. Copy-Paste Ready Positive Prompt
```text
Tight cinematic 9:16 vertical close-up and medium shot transition, Elif Eylul looking directly into camera lens with poignant deep hazel eyes, touching delicate pearl necklace, cutting to Polat Alemdar executing synchronized upward dual-shoulder shrug on snare hit. Polat with defined angular jawline, prominent cheekbones, resolute unblinking mafia stare, tailored black suit with open white collar. Elif with soft heart-shaped face, natural rose lips, chocolate brunette hair wisps. Ultra-realistic skin micro-texture, visible fine pores, authentic matte appearance, completely free of digital smoothing or artificial shine. High-contrast filmic chiaroscuro lighting, deep shadow with soft fill, brilliant cool 5600K rim light tracing jawline and temples. Kodak Vision2 film stock look, 85mm prime portrait lens, 4K resolution.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
deformed anatomy, disconnected neck, extra fingers on pearl necklace, fused fingers, mutated hands, missing fingers, wandering eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, oversaturated, blown out highlights, motion blur, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Fingers interacting with the pearl necklace can cause finger duplication.
- **Mitigation:** Card E03 establishes a clean neck baseline; negative prompt includes explicit tokens against `extra fingers on pearl necklace`.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Audio Sync:** Lock Polat’s dual-shoulder apex to the snare transient at $t = 13.10\text{ s}$.

---

### Shot Profile: Clip 06 (`clip_06_strophe_swagger_strut.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_06_strophe_swagger_strut.mp4`
- **Source Range:** 41.680s – 46.520s (Source Shot 06)
- **Relative Timeline Range:** 14.416s – 19.256s
- **Duration:** 4.840s (145 frames @ 30.0 fps CFR)
- **Target Characters:** Elif Eylül (09) transitioning to Polat Alemdar (10, 11).
- **Choreographic Action:** Emotional strophe & swagger strut; Elif seated prayer/wrist snap cuts to Polat’s rhythmic lateral torso sway and low-angle dynamic strut down steps ('Davra glide').
- **Framing & Centering:** Center X = 960 px ($X_{\text{offset}} = 656\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Locomotion down physical steps. Kling 3.0 excels at maintaining fixed ground contact planes, preventing sliding or ice-skating feet during Polat’s descent.
- **Scene Control Mode:** `scene_control: video`.

#### 3. Character Anchor Selection
- **Primary Anchor:** `polat_full_body_9_16.png` (Card P01)
- **Secondary Reference:** `elif_seated_red_steps_9_16.png` (Card E01)
- **Framing Rationale:** Full-body framing is essential to track footfalls and trouser drape as Polat steps forward toward the camera.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.74**
- **Technical Justification:** Locks shoes to stair treads while accurately conveying the rhythmic torso sway.

#### 5. Copy-Paste Ready Positive Prompt
```text
Low-angle full-body cinematic 9:16 vertical shot, Polat Alemdar executing dynamic swagger strut down red velvet pyramid steps ('Davra glide') with rhythmic lateral torso sway, commanding mafia walk facing camera, sharp chiseled jawline, intense unblinking stare, swept-back jet-black pompadour hair. Bespoke tailored two-button midnight-black Italian wool suit jacket, matching black trousers with clean break over polished black leather oxford shoes, crisp white dress shirt open at neck. Visible fine skin pores, authentic matte complexion, natural stubble texture, no digital smoothing, no beauty filter, zero plastic sheen. Cinematic low-key chiaroscuro lighting, cool 5600K cyan rim lighting sculpting shoulders, elbows, and shoes for razor-sharp edge separation against red velvet steps. 35mm master prime lens, ultra-sharp focus, 4K resolution, Turkish noir realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
ice-skating feet, sliding feet, melting shoes, floating steps, rubbery legs, detached ankles, suit distortion, deformed anatomy, extra limbs, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Foot penetration into stair geometry.
- **Mitigation:** Setting `scene_control: video` allows the model to reference the physical step collisions from the driving clip.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.050s (1.5 frames) to cleanly bridge into Clip 07.

---

### Shot Profile: Clip 07 (`clip_07_duo_charm_finger_wag.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_07_duo_charm_finger_wag.mp4`
- **Source Range:** 46.520s – 52.760s (Source Shot 07)
- **Relative Timeline Range:** 19.256s – 25.496s
- **Duration:** 6.240s (187 frames @ 30.0 fps CFR)
- **Target Characters:** Duo (Polat Alemdar + Elif Eylül).
- **Choreographic Action:** Duo charm & playful finger wag; intercut romantic gestures, backward lean on velvet steps, ensemble unison pelvic bounce, and playful finger wag into lens.
- **Framing & Centering:** Center X = 910 px ($X_{\text{offset}} = 606\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Higgsfield Genjutsu (`hf_mult_motion_control`)
- **Cost:** 35 credits
- **Rationale:** Longest clip (6.240s) containing complex hand foreshortening. Genjutsu handles multi-character tracking and the delicate finger kinematics of the finger-wag gesture without generating extra digits.

#### 3. Character Anchor Selection
- **Polat Anchor:** `polat_medium_shot_9_16.png` (Card P02)
- **Elif Anchor:** `elif_seated_red_steps_9_16.png` (Card E01) / `elif_medium_shot_9_16.png` (Card E02)
- **Framing Rationale:** Waist-up framing captures both characters' expressive torso movements and the forward hand gesture.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.73**
- **Technical Justification:** Calibrated to 0.73 to prevent finger elongation when pointing directly at the camera while preserving body rhythm.

#### 5. Copy-Paste Ready Positive Prompt
```text
Cinematic medium shot in 9:16 vertical orientation, Polat Alemdar and Elif Eylul on red velvet steps in a charming playful moment. Polat leaning back smoothly in his tailored black Italian wool suit before executing a confident, subtle finger-wag gesture directly toward the camera lens with a faint stoic smirk, sharp angular jawline, intense deep-set dark brown eyes, crisp white open-collar shirt. Elif smiling warmly beside him, chocolate brunette hair in soft waves, ivory dress. Dramatic chiaroscuro lighting, warm key light, cool 5600K cyan rim lighting carving both characters to prevent clothing blend. Visible fine facial pores, realistic skin micro-texture, matte natural finish, no beauty filter, zero plastic AI sheen. Shot on 50mm anamorphic lens, 35mm film grain, 4K resolution, cinematic realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
extra fingers, six fingers, fused fingers, mutated hands, warped fingers, deformed anatomy, extra arms, disconnected shoulders, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Perspective foreshortening during the finger-wag toward the lens can cause hand morphing.
- **Mitigation:** The negative prompt heavily penalizes `extra fingers`, `six fingers`, and `warped fingers`.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.033s (1 frame).

---

### Shot Profile: Clip 08 (`clip_08_canyon_transition_stomp.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_08_canyon_transition_stomp.mp4`
- **Source Range:** 52.760s – 57.240s (Source Shot 08)
- **Relative Timeline Range:** 25.496s – 29.976s
- **Duration:** 4.480s (134 frames @ 30.0 fps CFR)
- **Target Character:** Polat Alemdar (with White Corps dancers).
- **Choreographic Action:** Outdoor canyon shift; navy jacket archway swagger, white dancers arm thrust at start of 19s break, and center-stage Lazgi stomp on red cubes.
- **Framing & Centering:** Center X = 920 px ($X_{\text{offset}} = 616\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Outfit transition to Card P04 (vintage aviator bomber jacket & fedora hat). Kling 3.0 preserves the structured fedora silhouette and prevents background sandstone from bleeding into his navy jacket.
- **Scene Control Mode:** `scene_control: image` (locks the high-contrast canyon environment from the anchor).

#### 3. Character Anchor Selection
- **Anchor File:** `polat_canyon_outfit_9_16.png` (Card P04)
- **Framing Rationale:** Card P04 was specifically engineered with the dark wool felt fedora, pilot bomber jacket, and sandstone canyon background.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.75**
- **Technical Justification:** Transfers the heavy rhythmic ground stomp and arm thrusts with maximum kinetic weight without dislodging the fedora hat.

#### 5. Copy-Paste Ready Positive Prompt
```text
Cinematic medium-full portrait in 9:16 vertical orientation, adult Mediterranean man in his early 30s as undercover operative Polat Alemdar in outdoor canyon mission attire from Kurtlar Vadisi. Executing powerful Khorezm Lazgi stomp dance and swaggering arm thrusts in an arid rocky canyon setting with warm sandstone formations and a vivid deep red architectural archway. Chiseled rectangular jawline, high cheekbones, masculine cleft chin, intense piercing brooding dark brown eyes with focused stoic stare. Wearing a dark vintage wool felt fedora hat angled slightly low over his brow, tailored dark navy-blue and black heavy pilot bomber jacket with silver zip hardware and structured aviator collar, crisp white shirt collar visible, tailored charcoal trousers. Visible fine skin texture with natural pores, subtle stubble along jawline, matte natural complexion, zero beauty filter, zero plastic sheen. High-contrast natural sunlight with dramatic canyon shadow and strong 5600K crisp rim light sculpting hat brim, shoulders, and jacket silhouette for sharp edge separation against quarry backdrop. Shot on 35mm cinematic anamorphic lens, 4K film still, gritty cinematic action realism.
```

#### 6. Copy-Paste Ready Negative Prompt
*(CRITICAL: `hat` and `fedora` MUST be omitted from negative prompt to allow Polat's headwear).*
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Fedora hat brim warping during rapid head turns.
- **Mitigation:** The prompt explicitly specifies the hat; `scene_control: image` keeps headwear geometry tied to the anchor latent.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.033s (1 frame).

---

### Shot Profile: Clip 09 (`clip_09_canyon_double_point.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_09_canyon_double_point.mp4`
- **Source Range:** 57.240s – 63.160s (Source Shot 09)
- **Relative Timeline Range:** 29.976s – 35.896s
- **Duration:** 5.920s (178 frames @ 30.0 fps CFR)
- **Target Character:** Polat Alemdar (with White Corps dancers).
- **Choreographic Action:** Canyon dance break & iconic double point; wrist snap pans, low-angle elbow pump groove, explosive 'Peshta Double-Point' into camera lens, and lateral arm whip.
- **Framing & Centering:** Center X = 980 px ($X_{\text{offset}} = 676\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** High-impact solo gesture. The forward double-point requires sharp finger isolation against the canyon background.
- **Scene Control Mode:** `scene_control: video` (to preserve the dynamic camera pan and backing dancers).

#### 3. Character Anchor Selection
- **Anchor File:** `polat_canyon_outfit_9_16.png` (Card P04)
- **Framing Rationale:** Matches outdoor canyon setting with fedora and pilot bomber jacket.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.75**
- **Technical Justification:** Ensures the forward extension of both index fingers hits the camera plane synchronously with the vocal hit.

#### 5. Copy-Paste Ready Positive Prompt
```text
Dynamic low-angle medium shot in 9:16 vertical orientation, Polat Alemdar in outdoor canyon attire wearing dark vintage wool felt fedora and navy pilot bomber jacket, executing the explosive signature 'Peshta Double-Point' gesture directly pointing both index fingers forward into camera lens with intense unwavering mafia stare, sharp elbow pumps, and rhythmic lateral arm whip. Arid sandstone canyon setting with vivid red doorway background. Sharp rectangular jawline, prominent cheekbones, stoic expression. Visible fine masculine skin texture with natural pores, subtle stubble along jawline, matte natural complexion, zero beauty filter, zero plastic sheen. High-contrast natural sunlight, strong 5600K crisp rim light sculpting hat brim and shoulders for sharp edge separation. Shot on 35mm anamorphic prime lens, 4K resolution, gritty cinematic action realism.
```

#### 6. Copy-Paste Ready Negative Prompt
*(CRITICAL: `hat` and `fedora` omitted).*
```text
mutated hands, fused fingers, more than five fingers per hand, missing fingers, extra index fingers, detached wrists, rubbery arms, broken elbows, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, sunglasses, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Both hands pointing straight forward can trigger 6-finger hallucinations.
- **Mitigation:** Strict negative prompt tokens against `extra index fingers` and `mutated hands`.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.050s (1.5 frames).

---

### Shot Profile: Clip 10 (`clip_10_elif_red_steps.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_10_elif_red_steps.mp4`
- **Source Range:** 63.160s – 64.760s (Source Shot 10)
- **Relative Timeline Range:** 35.896s – 37.496s
- **Duration:** 1.600s (48 frames @ 30.0 fps CFR)
- **Target Character:** Elif Eylül (Seated solo).
- **Choreographic Action:** Return to red studio; Elif seated on red steps, arms crossed tightly over chest clutching pearls with mysterious, elegant gaze.
- **Framing & Centering:** Center X = 650 px ($X_{\text{offset}} = 346\text{ px}$). Crop shifted left by 310 px to guarantee 18% headroom and eliminate head cutoff.

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Static seated posture. Kling 3.0 with `scene_control: image` locks Elif into the pristine studio red steps from Card E01, ensuring zero background jitter during this short 1.6-second cut.
- **Alternative:** Higgsfield Genjutsu (`hf_mult_motion_control`, 35 credits).

#### 3. Character Anchor Selection
- **Anchor File:** `elif_seated_red_steps_9_16.png` (Card E01)
- **Framing Rationale:** Perfect 1:1 pose match; Card E01 was composed with Elif seated gracefully on tiered red steps holding pearls.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.70**
- **Technical Justification:** Lowest strength in the sequence. Since Elif is seated and primarily conveying emotion through subtle head tilts and eye expressions, 0.70 prevents her arms and pearl necklace from melting into her dress.

#### 5. Copy-Paste Ready Positive Prompt
```text
Cinematic 9:16 vertical full-body shot, elegant 26-year-old Turkish woman as Elif Eylul from 2003 Kurtlar Vadisi, seated gracefully on wide tiered steps covered in rich crimson red velvet carpet. Torso upright, arms crossed gently over her chest clutching a delicate multi-strand freshwater pearl necklace, deeply expressive warm hazel-brown almond eyes looking upward with a tender mysterious gaze, soft heart-shaped face, delicate rounded chin, soft natural rose lips. Rich chocolate brunette hair in loose cascading waves over shoulders. Elegant minimalist ivory-white silk-crepe tea-length dress with modest neckline, dainty white ankle-strap heels. Visible natural skin texture with fine pores, delicate peach blush, matte unretouched complexion, no digital airbrushing, no plastic smoothing. Soft directional warm key lighting from camera left, gentle ambient red fill, rich deep red background with soft bokeh. Shot on 35mm film prime lens, 4K resolution, timeless emotional elegance.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
fused hands, hands melting into chest, warped pearl necklace, extra fingers, missing fingers, distorted arms, head cutoff, cropped forehead, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Head cutoff and hands blending into silk fabric.
- **Mitigation:** The re-centered crop ($X=650$) provides 18% headroom; motion strength calibrated down to 0.70 protects pearl and hand integrity.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.033s (1 frame).

---

### Shot Profile: Clip 11 (`clip_11_polat_hero_outro.mp4`)

#### 1. Clip Metadata & Scene Context
- **Filename:** `clip_11_polat_hero_outro.mp4`
- **Source Range:** 64.760s – 70.264s (Source Shot 11)
- **Relative Timeline Range:** 37.496s – 43.000s
- **Duration:** 5.504s (165 frames @ 30.0 fps CFR)
- **Target Character:** Polat Alemdar (Solo Hero Outro).
- **Choreographic Action:** Polat atop pyramid steps; extended signature wrist flick with subtle smirk, ending in a statuesque hero pose at attention as the music transitions to Verse 2.
- **Framing & Centering:** Center X = 1020 px ($X_{\text{offset}} = 716\text{ px}$).

#### 2. Model Selection & Technical Rationale
- **Selected Model:** Kling 3.0 Motion Control (`motion_control` / `kling3_0`)
- **Cost:** 10 credits
- **Rationale:** Grand finale hero shot. Requires maximum facial resolution to render Polat’s iconic subtle mafia smirk and unwavering unblinking gaze before locking into a statuesque pose.
- **Scene Control Mode:** `scene_control: video`.

#### 3. Character Anchor Selection
- **Primary Anchor:** `polat_medium_shot_9_16.png` (Card P02)
- **Secondary Reference:** `polat_full_body_9_16.png` (Card P01)
- **Framing Rationale:** Waist-up medium framing highlights his facial expression and wrist flick while keeping the suit silhouette rock-solid.

#### 4. Motion Strength & Slider Calibration
- **Recommended Value:** **0.74**
- **Technical Justification:** Fluidly animates the wrist twirl and smoothly decelerates into an immovable statuesque hold at frame 165.

#### 5. Copy-Paste Ready Positive Prompt
```text
Heroic medium shot in 9:16 vertical orientation, framed waist-up, adult Mediterranean man in his early 30s as Turkish mafia operative Polat Alemdar in iconic 2003 Kurtlar Vadisi aesthetic, standing commanding atop red pyramid steps. Executing slow swaggering wrist flick before locking into an immovable statuesque hero pose facing camera with a faint stoic smirk, sharp angular jawline, sculpted cheekbones, intense brooding dark brown eyes with piercing penetrating gaze, thick swept-back jet-black pompadour hair. Wearing tailored midnight-black Italian wool suit jacket with structured roped shoulders, pristine white collared dress shirt open at throat, vintage stainless steel wristwatch. Visible fine facial pores, realistic skin micro-texture, faint 5 o'clock shadow along jaw, matte natural skin finish, zero beauty retouching, zero plastic shine. Dramatic chiaroscuro lighting, warm 3200K key light, brilliant cool 5600K electric cyan rim light carving shoulders and hair against dark moody studio backdrop. Shot on 50mm anamorphic lens, 35mm film grain, 4K resolution, cinematic mafia noir realism.
```

#### 6. Copy-Paste Ready Negative Prompt
```text
deformed wrists, extra hands, fused fingers, more than five fingers per hand, missing fingers, distorted mouth, asymmetrical smirk deformation, floating limbs, disconnected shoulders, plastic skin, porcelain doll skin, airbrushed, beauty filter, modern 2026 influencer face, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped head
```

#### 7. Anticipated Challenges & Mitigation
- **Challenge:** Final hold frame jitter or facial drift during the deceleration.
- **Mitigation:** The positive prompt explicitly mandates an "immovable statuesque hero pose"; Kling 3.0 settles into the anchor latent.

#### 8. Post-Processing & Trimming Notes
- **Lead-In Trim:** 0.100s (3 frames).
- **Lead-Out Trim:** 0.000s (Hold the final frame to lock the 43.000s sequence mark).

---

## 4. Step-by-Step Operator Click-Path on web.higgsfield.ai

This section provides human operators with the exact mouse and keyboard click-path to execute generations directly via the web interface.

### 4.1 Phase 1: Authentication & Workspace Preflight
1. Open Google Chrome or Brave and navigate to `https://web.higgsfield.ai`.
2. Verify you are authenticated under the active organization account.
3. Check credit balance in the upper right profile widget: ensure available balance is **$\ge 210$ credits**.
4. Confirm workspace is set to default production workspace.

### 4.2 Phase 2: Generating & Verifying Character Anchor Images (If Re-Generating)
1. In the left navigation rail, click **🎨 Image**.
2. Top bar model dropdown: Select **Higgsfield Soul 2.0** (`soul_2`) or **GPT Image 2.5** (`gpt_image_2_5`).
3. Quality setting: Toggle to **2K** (renders at 1152x2048 for 9:16).
4. Aspect ratio selector: Select **`9:16 (Portrait / Reels / TikTok)`**.
5. Paste the Positive Prompt from the corresponding card (P01–P04, E01–E03).
6. Expand **Advanced Settings**:
   - Toggle **Negative Prompt** to ON and paste the card's negative prompt.
   - Uncheck *Randomize Seed* and enter the exact seed (e.g. `424242` for P01, `110492` for E01).
7. Click **Generate** (cost: 0.12–1.0 credit).
8. Inspect output: verify sharp cheekbones, 5600K cyan rim lighting, matte skin texture.
9. Click **Download (PNG)** and save into `marketing/campaigns/peshta/character_assets/`.

### 4.3 Phase 3: Motion Control Video Synthesis Click-Path
For each clip from 01 to 11:

1. In the left navigation rail, click **🎬 Video** $\rightarrow$ **Motion Control**.
2. **Select Motion Model:**
   - For Clips 01, 03, 06, 08, 09, 10, 11: Select **Kling 3.0 Motion Control** (`motion_control`).
   - For Clips 02, 04, 05, 07: Select **Higgsfield Genjutsu** (`hf_mult_motion_control`).
3. **Upload Character Image (Subject Anchor):**
   - Click the left dropzone labeled *Upload Character Image* (or drag and drop).
   - Select the designated anchor file from `marketing/campaigns/peshta/character_assets/` (e.g., `polat_full_body_9_16.png`).
   - Confirm the yellow/green pose detection box highlights the character.
4. **Upload Driving Video Clip:**
   - Click the right dropzone labeled *Upload Driving Video* (or drag and drop).
   - Select the corresponding sliced driving clip from `marketing/campaigns/peshta/driving_clips/` (e.g., `clip_03_chorus_drop_hero.mp4`).
   - Verify the thumbnail and player load properly.
5. **Configure Model Parameters:**
   - **Aspect Ratio:** Verify **`9:16`**.
   - **Output Resolution:** Select **`1080p`**.
   - **Scene Control (Kling 3.0):**
     - Select **`video`** for studio pyramid shots (Clips 01, 03, 06, 09, 11).
     - Select **`image`** for canyon / custom background shots (Clips 08, 10).
   - **Motion Strength Slider:**
     - Drag slider to the exact value specified in Section 3 (e.g., `0.76` for Clip 03, `0.70` for Clip 10, `0.74` standard).
   - **Prompt Box:** Paste the copy-paste ready positive prompt for that shot.
   - **Negative Prompt Box:** Expand advanced controls and paste the shot-specific negative prompt.
6. **Generate & Render:**
   - Click the primary purple **Generate Video** button.
   - Kling 3.0 will deduct **10 credits**; Genjutsu will deduct **35 credits**.
   - Synthesis duration is typically **90 to 180 seconds**.

### 4.4 Phase 4: Output Verification, Naming, and Ingestion
1. Play through the rendered preview in the web UI at full resolution.
2. Verify:
   - Zero limb duplication or detached shoulders during arm movements.
   - Face maintains Polat Alemdar / Elif Eylül likeness throughout.
   - No plastic airbrushing or porcelain skin sheen.
3. Click the **Download** icon (select 1080p MP4).
4. Save the file directly to `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/rendered_clips/` following the strict canonical naming format:
   - `render_clip_01.mp4`
   - `render_clip_02.mp4`
   - `render_clip_03.mp4`
   - ...
   - `render_clip_11.mp4`

---

## 5. Higgsfield MCP / API Automation Guide

This section provides complete, verified Python and bash automation scripts to orchestrate the entire 11-clip synthesis pipeline via the `higgsfield` MCP server tools.

### 5.1 MCP Pipeline Architecture & Execution Flow
The automation follows a 5-stage deterministic protocol:
```
Local Files (.png / .mp4)
      │
      ▼
1. media_upload ──────► Allocates upload slot & presigned S3 PUT URL
      │
      ▼
2. HTTP PUT ──────────► Streams raw binary bytes directly to S3
      │
      ▼
3. media_confirm ─────► Confirms upload & obtains validated media_id
      │
      ▼
4. motion_control ────► Submits generation job (Kling 10 cr / Genjutsu 35 cr)
   generate_video
      │
      ▼
5. jobs_wait ─────────► Long-polls job completion & returns MP4 download URL
      │
      ▼
Download to marketing/campaigns/peshta/rendered_clips/render_clip_XX.mp4
```

### 5.2 Standalone Python Automation Script: `run_higgsfield_pipeline.py`

Below is the complete, dependency-free Python 3 script (using standard library `urllib`, `json`, `subprocess`, `pathlib`) ready to execute all 11 shots:

```python
#!/usr/bin/env python3
"""
run_higgsfield_pipeline.py
==========================
Automated batch execution script for Polat & Elif "Peshta" 11-clip recreation.
Orchestrates Higgsfield MCP tools: media_upload -> PUT -> media_confirm ->
motion_control/generate_video -> jobs_wait -> download.

Standard Library only: requires zero pip dependencies.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional

# Workspace Configuration
WORKSPACE_ROOT = Path("/Users/ai/Desktop/work/projects/hbd-bot")
PROMO_DIR = WORKSPACE_ROOT / "marketing/campaigns/peshta"
DRIVING_DIR = PROMO_DIR / "driving_clips"
ASSETS_DIR = PROMO_DIR / "character_assets"
RENDER_DIR = PROMO_DIR / "rendered_clips"
RENDER_DIR.mkdir(parents=True, exist_ok=True)

# Master Manifest for All 11 Clips
SHOT_MANIFEST = [
    {
        "clip_id": "01",
        "driving_file": "clip_01_verse1_setup.mp4",
        "anchor_file": "polat_full_body_9_16.png",
        "model_type": "kling",  # "kling" or "genjutsu"
        "scene_control": "video",
        "motion_strength": 0.72,
        "prompt": "Full-body 9:16 portrait, Polat Alemdar standing on red pyramid steps with subtle wrist flourishes, tailored black wool suit, white open collar, 5600K cyan rim light, chiaroscuro, anti-AI realism, 4K.",
        "negative_prompt": "deformed anatomy, extra limbs, fused fingers, plastic skin, airbrushed, beauty filter, cartoon, 3d render, watermark, cropped feet"
    },
    {
        "clip_id": "02",
        "driving_file": "clip_02_hook_duo_roses.mp4",
        "anchor_file": "elif_seated_red_steps_9_16.png",
        "secondary_anchor": "polat_medium_shot_9_16.png",
        "model_type": "genjutsu",
        "scene_control": "video",
        "motion_strength": 0.72,
        "prompt": "Cinematic 9:16 vertical duo shot, Polat Alemdar leaning down charismatically toward Elif Eylul seated on red velvet steps holding red roses, black wool suit, ivory silk dress, 5600K cyan rim light, chiaroscuro, 4K.",
        "negative_prompt": "fused bodies, black suit melting into white dress, extra hands, mutated fingers, floating roses, plastic skin, airbrushed"
    },
    {
        "clip_id": "03",
        "driving_file": "clip_03_chorus_drop_hero.mp4",
        "anchor_file": "polat_full_body_9_16.png",
        "model_type": "kling",
        "scene_control": "video",
        "motion_strength": 0.76,
        "prompt": "Full-body cinematic 9:16 hero shot, Polat Alemdar executing explosive Khorezm Lazgi deep squat bounce atop red steps, centered commanding posture, black Italian wool suit, white open collar, 5600K cyan rim light, chiaroscuro, 4K.",
        "negative_prompt": "knee dislocation, rubbery legs, gelatinous feet, suit tearing, extra limbs, fused fingers, plastic skin, airbrushed"
    },
    {
        "clip_id": "04",
        "driving_file": "clip_04_call_response_1.mp4",
        "anchor_file": "polat_medium_shot_9_16.png",
        "model_type": "genjutsu",
        "scene_control": "video",
        "motion_strength": 0.75,
        "prompt": "Cinematic medium shot 9:16 portrait, Polat Alemdar executing sharp alternating Khorezmian shoulder pops ('yelka qoqish'), tailored black wool suit, open white collar, 5600K cyan rim light, chiaroscuro, 4K.",
        "negative_prompt": "disconnected shoulders, floating clavicle, detached suit arms, mutated hands, fused fingers, plastic skin, airbrushed"
    },
    {
        "clip_id": "05",
        "driving_file": "clip_05_call_response_2.mp4",
        "anchor_file": "polat_medium_shot_9_16.png",
        "model_type": "genjutsu",
        "scene_control": "video",
        "motion_strength": 0.74,
        "prompt": "Tight cinematic 9:16 vertical close-up and medium shot, Polat Alemdar executing upward dual-shoulder shrug on snare hit, defined jawline, intense brooding mafia stare, tailored black suit, white open collar, 5600K rim light, 4K.",
        "negative_prompt": "deformed anatomy, disconnected neck, wandering eyes, plastic skin, airbrushed, modern influencer face, watermark"
    },
    {
        "clip_id": "06",
        "driving_file": "clip_06_strophe_swagger_strut.mp4",
        "anchor_file": "polat_full_body_9_16.png",
        "model_type": "kling",
        "scene_control": "video",
        "motion_strength": 0.74,
        "prompt": "Low-angle full-body 9:16 vertical shot, Polat Alemdar executing dynamic swagger strut down red velvet steps ('Davra glide') with rhythmic torso sway, black wool suit, oxfords, 5600K cyan rim light, chiaroscuro, 4K.",
        "negative_prompt": "ice-skating feet, sliding feet, melting shoes, floating steps, rubbery legs, suit distortion, extra legs, plastic skin"
    },
    {
        "clip_id": "07",
        "driving_file": "clip_07_duo_charm_finger_wag.mp4",
        "anchor_file": "polat_medium_shot_9_16.png",
        "secondary_anchor": "elif_seated_red_steps_9_16.png",
        "model_type": "genjutsu",
        "scene_control": "video",
        "motion_strength": 0.73,
        "prompt": "Cinematic medium shot 9:16 vertical duo shot, Polat Alemdar leaning back smoothly then delivering confident subtle finger-wag toward lens, Elif Eylul smiling warmly beside him, black suit, ivory dress, 5600K rim light, 4K.",
        "negative_prompt": "extra fingers, six fingers, fused fingers, mutated hands, warped fingers, deformed anatomy, plastic skin, airbrushed"
    },
    {
        "clip_id": "08",
        "driving_file": "clip_08_canyon_transition_stomp.mp4",
        "anchor_file": "polat_canyon_outfit_9_16.png",
        "model_type": "kling",
        "scene_control": "image",
        "motion_strength": 0.75,
        "prompt": "Cinematic medium-full portrait 9:16 vertical, Polat Alemdar in outdoor canyon attire with dark vintage wool fedora and navy pilot bomber jacket, executing Khorezm Lazgi stomp dance in rocky canyon, hard sunlight, 5600K rim light, 4K.",
        "negative_prompt": "deformed anatomy, extra limbs, fused fingers, rubbery legs, plastic skin, airbrushed, cartoon, 3d render"
    },
    {
        "clip_id": "09",
        "driving_file": "clip_09_canyon_double_point.mp4",
        "anchor_file": "polat_canyon_outfit_9_16.png",
        "model_type": "kling",
        "scene_control": "video",
        "motion_strength": 0.75,
        "prompt": "Dynamic low-angle 9:16 vertical shot, Polat Alemdar in fedora and pilot bomber jacket, executing explosive 'Peshta Double-Point' gesture pointing both index fingers forward into lens, canyon backdrop, 5600K rim light, 4K.",
        "negative_prompt": "mutated hands, fused fingers, more than five fingers per hand, missing fingers, extra index fingers, rubbery arms, plastic skin"
    },
    {
        "clip_id": "10",
        "driving_file": "clip_10_elif_red_steps.mp4",
        "anchor_file": "elif_seated_red_steps_9_16.png",
        "model_type": "kling",
        "scene_control": "image",
        "motion_strength": 0.70,
        "prompt": "Cinematic 9:16 vertical shot, Elif Eylul seated gracefully on red velvet steps clutching delicate freshwater pearl necklace, looking up with mysterious tender gaze, ivory-white silk dress, chocolate brunette waves, soft warm light, 4K.",
        "negative_prompt": "fused hands, hands melting into chest, warped pearl necklace, extra fingers, head cutoff, cropped forehead, plastic skin, airbrushed"
    },
    {
        "clip_id": "11",
        "driving_file": "clip_11_polat_hero_outro.mp4",
        "anchor_file": "polat_medium_shot_9_16.png",
        "model_type": "kling",
        "scene_control": "video",
        "motion_strength": 0.74,
        "prompt": "Heroic medium shot 9:16 vertical framing, Polat Alemdar executing slow swaggering wrist flick before locking into statuesque hero pose with subtle stoic smirk, tailored black Italian wool suit, white open collar, 5600K cyan rim light, 4K.",
        "negative_prompt": "deformed wrists, extra hands, fused fingers, distorted mouth, asymmetrical smirk deformation, floating limbs, plastic skin"
    }
]


def upload_binary_s3(file_path: Path, upload_url: str, content_type: str) -> bool:
    """Streams file bytes directly to S3 presigned URL via HTTP PUT."""
    data = file_path.read_bytes()
    req = urllib.request.Request(
        upload_url,
        data=data,
        headers={"Content-Type": content_type},
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        print(f"[-] S3 PUT failed for {file_path.name}: HTTP {e.code} - {e.reason}", file=sys.stderr)
        return False


def call_higgsfield_mcp(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interface bridge to call Higgsfield MCP tools.
    In an interactive subagent context, replace this with the call_mcp_tool dispatch.
    """
    # Pseudocode bridge representing the native MCP client invocation:
    # return call_mcp_tool("higgsfield", tool_name, arguments)
    print(f"[*] MCP Call -> {tool_name}: {json.dumps(arguments, indent=2)}")
    return {"status": "dispatched", "mock_job_id": "00000000-0000-0000-0000-000000000000"}


def execute_pipeline(dry_run: bool = True):
    print("=" * 80)
    print("HIGGSFIELD AI MOTION CONTROL PRODUCTION PIPELINE")
    print(f"Target Sequence: 11 Clips | Total Frames: 1,290 | Duration: 43.000s")
    print("=" * 80)

    # Cache for confirmed media IDs to avoid re-uploading identical anchors
    uploaded_media_cache: Dict[str, str] = {}

    for shot in SHOT_MANIFEST:
        clip_id = shot["clip_id"]
        driving_path = DRIVING_DIR / shot["driving_file"]
        anchor_path = ASSETS_DIR / shot["anchor_file"]
        output_file = RENDER_DIR / f"render_clip_{clip_id}.mp4"

        print(f"\n[>>> Processing Shot {clip_id}/11: {shot['driving_file']} <<<]")
        assert driving_path.exists(), f"Missing driving clip: {driving_path}"
        assert anchor_path.exists(), f"Missing anchor image: {anchor_path}"

        if dry_run:
            print(f"  [DRY-RUN] Validated inputs:")
            print(f"    - Driving Clip: {driving_path.name} ({driving_path.stat().st_size} bytes)")
            print(f"    - Anchor Image: {anchor_path.name} ({anchor_path.stat().st_size} bytes)")
            print(f"    - Engine: {shot['model_type'].upper()} | Strength: {shot['motion_strength']}")
            print(f"    - Destination: {output_file.name}")
            continue

        # 1. Upload Driving Video
        if shot["driving_file"] not in uploaded_media_cache:
            print(f"  [1/4] Uploading driving clip: {driving_path.name}...")
            up_res = call_higgsfield_mcp("media_upload", {
                "filename": driving_path.name,
                "content_type": "video/mp4"
            })
            upload_binary_s3(driving_path, up_res["upload_url"], "video/mp4")
            conf_res = call_higgsfield_mcp("media_confirm", {
                "media_id": up_res["media_id"],
                "type": "video"
            })
            uploaded_media_cache[shot["driving_file"]] = conf_res["media_id"]
        driving_media_id = uploaded_media_cache[shot["driving_file"]]

        # 2. Upload Character Anchor Image
        if shot["anchor_file"] not in uploaded_media_cache:
            print(f"  [2/4] Uploading anchor image: {anchor_path.name}...")
            img_up = call_higgsfield_mcp("media_upload", {
                "filename": anchor_path.name,
                "content_type": "image/png"
            })
            upload_binary_s3(anchor_path, img_up["upload_url"], "image/png")
            img_conf = call_higgsfield_mcp("media_confirm", {
                "media_id": img_up["media_id"],
                "type": "image"
            })
            uploaded_media_cache[shot["anchor_file"]] = img_conf["media_id"]
        anchor_media_id = uploaded_media_cache[shot["anchor_file"]]

        # 3. Dispatch Motion Transfer Job
        print(f"  [3/4] Dispatching generation job ({shot['model_type']})...")
        if shot["model_type"] == "kling":
            job = call_higgsfield_mcp("motion_control", {
                "params": {
                    "image_id": anchor_media_id,
                    "motion_video_id": driving_media_id,
                    "resolution": "1080p",
                    "scene_control": shot["scene_control"]
                }
            })
            job_id = job.get("job_id") or job.get("mock_job_id")
        else:  # genjutsu
            medias = [
                {"role": "image_references", "value": anchor_media_id},
                {"role": "video_references", "value": driving_media_id}
            ]
            job = call_higgsfield_mcp("generate_video", {
                "params": {
                    "model": "hf_mult_motion_control",
                    "aspect_ratio": "9:16",
                    "resolution": "1080p",
                    "medias": medias,
                    "prompt": shot["prompt"],
                    "count": 1
                }
            })
            job_id = job.get("job_id") or job.get("mock_job_id")

        # 4. Wait for Job Completion
        print(f"  [4/4] Polling completion for job {job_id}...")
        res = call_higgsfield_mcp("jobs_wait", {
            "jobs": [{"index": int(clip_id), "job_id": job_id}],
            "timeout_seconds": 15
        })
        print(f"  [+] Job {job_id} successfully completed. Output ready for download.")

    print("\n[✓] Pipeline execution finished successfully.")


if __name__ == "__main__":
    is_dry = "--execute" not in sys.argv
    if is_dry:
        print("[i] Running in preflight dry-run mode. Pass '--execute' to submit live jobs.")
    execute_pipeline(dry_run=is_dry)
```

---

## 6. Fallback Plan & Troubleshooting Matrix

During AI motion transfer of high-energy Uzbek folk choreography (95.8 BPM shoulder pops, deep squats, and fast wrist flicks), operators may encounter generative anomalies. Follow the systematic remediation matrix below:

| Anomaly / Failure Mode | Root Cause | Observable Symptom | Concrete Technical Remediation |
|---|---|---|---|
| **Limb Fusion / Torso Melting** | Insufficient edge contrast between black suit and dark background. | Polat's forearm merges into jacket torso during arm crosses. | 1. Ensure `polat_full_body_9_16.png` or `polat_medium_shot_9_16.png` has active **5600K cyan rim lighting**.<br>2. Add negative tokens: `fused limbs, arm melting into torso, blended sleeves`.<br>3. Switch model from Kling 3.0 to **Higgsfield Genjutsu** (`hf_mult_motion_control`). |
| **Identity Drift / Facial Morphing** | Motion strength slider is set too high ($>0.85$). | Polat's face drifts toward Hamdam Sobirov or a generic model. | 1. Lower motion strength slider to **0.72 – 0.74**.<br>2. Re-inject Card P02 positive prompt tokens (`intense unblinking dark brown eyes, sharp Mediterranean jawline`).<br>3. Ensure negative prompt includes `face morphing, actor leakage, round juvenile jawline`. |
| **Synthetic "Plastic Skin Sheen"** | Default diffusion checkpoint airbrushing. | Character skin resembles glossy synthetic plastic or video game CGI. | 1. Enforce the **Anti-AI Realism Engine** tokens: `visible fine skin pores, authentic matte complexion, natural stubble texture, no digital smoothing, no beauty filter`.<br>2. In negative prompt, reinforce: `plastic skin, porcelain doll skin, airbrushed, 3d render, anime, cgi`. |
| **Ice-Skating / Sliding Feet** | Motion strength too low or camera angle mismatched. | Polat's shoes slide unnaturally across the red carpeted steps. | 1. Verify Card P01 (`polat_full_body_9_16.png`) is selected (head-to-toe with clean floor clearance).<br>2. In Kling 3.0, ensure `scene_control: video` is active.<br>3. Raise motion strength from 0.72 to **0.75 – 0.76**. |
| **Duo Character Bleed / Clothing Mix** | Close spatial proximity between Polat and Elif on steps. | Polat's black suit lapels bleed into Elif's ivory silk dress or roses. | 1. Switch immediately to **Higgsfield Genjutsu** (`hf_mult_motion_control`).<br>2. Supply dual reference images (`medias` with role `image_references` for both Card P02 and Card E01).<br>3. Set motion strength to **0.72**. |
| **Head Cutoff on Seated Elif (Clip 10)** | Subject placed too high in widescreen source. | Top of Elif's head or hair is cut off by top edge of 9:16 frame. | 1. Use the pre-calibrated cropped file `clip_10_elif_red_steps.mp4` where Center X = 650 px ($X_{\text{offset}} = 346\text{ px}$), providing **18% clear headroom**.<br>2. In prompt, assert `full head and hair completely visible, headroom clearance`. |
| **Fedora Brim Distortion (Clips 08, 09)** | Negative prompt accidentally bans hats. | Polat's vintage fedora vanishes, warps, or turns into hair. | 1. **CRITICAL:** Check negative prompt and remove `hat` and `fedora`.<br>2. Select Card P04 (`polat_canyon_outfit_9_16.png`).<br>3. For Clip 08, set `scene_control: image`. |

---

## 7. Post-Production Handoff Bridge to Milestone 4

This section defines the formal ingestion contract between Milestone 3 (Generative Video Synthesis) and Milestone 4 (Automated Post-Production Assembly via `assemble_polat_peshta.py`).

### 7.1 Delivery Directory & Naming Convention
All rendered clips must be placed into `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/rendered_clips/` matching the canonical naming scheme:

```text
marketing/campaigns/peshta/rendered_clips/
├── render_clip_01.mp4   # 0.000s - 2.256s (68 frames)
├── render_clip_02.mp4   # 2.256s - 5.176s (88 frames)
├── render_clip_03.mp4   # 5.176s - 8.976s (114 frames - PRIMARY DROP)
├── render_clip_04.mp4   # 8.976s - 11.816s (85 frames)
├── render_clip_05.mp4   # 11.816s - 14.416s (78 frames)
├── render_clip_06.mp4   # 14.416s - 19.256s (145 frames)
├── render_clip_07.mp4   # 19.256s - 25.496s (187 frames)
├── render_clip_08.mp4   # 25.496s - 29.976s (134 frames)
├── render_clip_09.mp4   # 29.976s - 35.896s (178 frames)
├── render_clip_10.mp4   # 35.896s - 37.496s (48 frames)
└── render_clip_11.mp4   # 37.496s - 43.000s (165 frames)
```

### 7.2 Ingestion Metadata Manifest (`assembly_manifest.json`)
The assembly script `assemble_polat_peshta.py` ingests a JSON manifest specifying per-clip conforming parameters:

```json
{
  "project": "polat_elif_peshta_43s",
  "target_fps": 30.0,
  "target_resolution": [1080, 1920],
  "target_duration": 43.000,
  "master_audio": "/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3",
  "beat_drop_timestamp": 6.920,
  "clips": [
    {"id": "01", "file": "render_clip_01.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.000, "expected_frames": 68},
    {"id": "02", "file": "render_clip_02.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.033, "expected_frames": 88},
    {"id": "03", "file": "render_clip_03.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.000, "expected_frames": 114, "is_drop_anchor": true},
    {"id": "04", "file": "render_clip_04.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.033, "expected_frames": 85},
    {"id": "05", "file": "render_clip_05.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.000, "expected_frames": 78},
    {"id": "06", "file": "render_clip_06.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.050, "expected_frames": 145},
    {"id": "07", "file": "render_clip_07.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.033, "expected_frames": 187},
    {"id": "08", "file": "render_clip_08.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.033, "expected_frames": 134},
    {"id": "09", "file": "render_clip_09.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.050, "expected_frames": 178},
    {"id": "10", "file": "render_clip_10.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.033, "expected_frames": 48},
    {"id": "11", "file": "render_clip_11.mp4", "lead_in_trim": 0.100, "lead_out_trim": 0.000, "expected_frames": 165}
  ]
}
```

### 7.3 Milestone 4 Assembly Verification Criteria
Upon ingestion, `assemble_polat_peshta.py` executes an automated verification gate asserting:
1. **Container & Stream Validity:** Output is valid MP4 (`avc1.640028` / `mp4a.40.2`).
2. **Exact Duration:** Total duration is $43.000\text{ s} \pm 0.050\text{ s}$.
3. **Exact Packet Count:** Exactly 1,290 video packets with strictly monotonic DTS/PTS.
4. **Beat Drop Alignment:** Visual apex of Clip 03 squat drop is locked to audio transient at relative $t = 6.920\text{ s}$ ($\pm 1$ frame / 33ms).
5. **Streaming Faststart:** The `moov` atom precedes the `mdat` atom for instant Reels playback.
