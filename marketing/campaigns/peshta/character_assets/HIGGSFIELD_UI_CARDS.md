# Higgsfield Web UI Operator Parameter Cards & Step-by-Step Execution Guide

**Target Environment**: `web.higgsfield.ai`  
**Campaign**: Polat Alemdar & Elif Eylül "Peshta" 9:16 Instagram Reels Recreation  
**Target Output**: Vertical 9:16 (1080x1920) Character Reference Anchors & Motion Control Transfers  
**Author**: `worker_m2`  
**Working Directory**: `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/character_assets/`  

---

## 1. Web UI Operator Quick-Start Overview

This manual provides human operators with exact, step-by-step click paths, model configurations, and copy-paste parameter cards for generating character anchor assets and puppeteering them via Motion Control on `web.higgsfield.ai`.

### 1.1 Web UI Interface Layout Map
When logged into [web.higgsfield.ai](https://web.higgsfield.ai):
- **Left Navigation Rail**:
  - 🎨 **Image** $\rightarrow$ Text-to-Image Generation interface.
  - 🎬 **Video** $\rightarrow$ Video Generation / Motion Control interface.
  - 👥 **Soul / Characters** $\rightarrow$ Reusable Soul persona library.
- **Top Control Ribbon**: Model selector dropdown, Quality toggle (`Standard` / `2K` / `4K`).
- **Prompt Canvas**: Center textarea for Positive Prompt.
- **Left/Bottom Inspector**: Aspect ratio selector (`9:16`, `16:9`, `1:1`, etc.), Count selector (`1` to `4`).
- **Advanced Settings Collapsible Drawer**: Negative Prompt textarea, Seed input field, Sampling Steps, CFG Scale.

---

## 2. Step-by-Step Operator Guide on web.higgsfield.ai

### Phase 1: Generating Character Anchor Stills (Image Generation)

#### Step 1: Access Image Generation Canvas
1. Open your browser and navigate to `https://web.higgsfield.ai/generate/image`.
2. Ensure you are signed into the organization account with sufficient Pro credits (each generation requires 0.12–1.0 credit).

#### Step 2: Select Model & Quality Tier
1. In the **Model Dropdown** at the top of the canvas, select **Higgsfield Soul 2.0** (`soul_2`).
   - *Alternative*: If typography or specific structural micro-details require enhanced rendering, select **GPT Image 2.5** (`gpt_image_2_5`).
2. Set the **Quality Toggle** to **2K** (High Resolution, renders at 1152x2048 for 9:16 or 2048x1152 for 16:9).

#### Step 3: Configure Aspect Ratio & Output Count
1. In the left/lower parameter panel, click the **Aspect Ratio** dropdown:
   - For Cards 1–4 (both characters): Select **`9:16 (Portrait / Reels / TikTok)`**.
   - For Card 5 / Card 4 (Master Split Sheets): Select **`16:9 (Landscape / Widescreen)`**.
2. Set **Generation Count** to `1` (or `2` if exploring subtle expression variations).

#### Step 4: Input Positive & Negative Prompts
1. Copy the exact **Positive Prompt** from the operator card below and paste it into the main prompt textarea.
2. Click **Advanced Settings** (gear icon or accordion below the canvas) to reveal advanced inputs.
3. Toggle **Negative Prompt** to ON.
4. Copy the exact **Negative Prompt** from the card and paste it into the Negative Prompt field.

#### Step 5: Input Fixed Seed for Reproducibility
1. In the Advanced Settings panel, locate the **Seed** field.
2. Uncheck *Randomize Seed* (dice icon).
3. Type or paste the recommended **Seed integer** specified in the card (e.g. `424242`).

#### Step 6: Generate and Save Anchor Asset
1. Click the large violet **Generate** button.
2. Processing time is typically 10–25 seconds.
3. Once rendered, click on the thumbnail to open the full-resolution preview.
4. Verify visual criteria:
   - Sharp cheekbones, intense unblinking gaze, clean white open collar, black suit.
   - Cool 5600K cyan rim lighting sculpting shoulders and pompadour.
   - Visible skin pores, matte complexion, zero beauty filter or plastic sheen.
5. Click **Download (PNG)** and save the file into `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/character_assets/` matching the canonical filename.

---

### Phase 2: Animating Anchors via Motion Control (Video Generation)

Once anchor images are rendered and stored, use them to transfer motion from the driving clips in `marketing/campaigns/peshta/driving_clips/`.

#### Step 1: Open Motion Control Canvas
1. On the left navigation rail of `web.higgsfield.ai`, click **Video** $\rightarrow$ **Motion Control** (or select **Kling 3.0 / Genjutsu Motion Control**).

#### Step 2: Upload Character Anchor Still
1. In the **Character / Subject Input** box (left dropzone), click *Upload Image* or drag-and-drop the generated anchor PNG (e.g. `polat_full_body_9_16.png`).
2. Verify that the subject is fully detected by the pose segmentation bounding box.

#### Step 3: Upload Driving Video Clip
1. In the **Motion Reference / Driving Video** box (right dropzone), upload the corresponding sliced driving MP4 clip from `marketing/campaigns/peshta/driving_clips/` (e.g. `clip_03_chorus_drop_hero.mp4`).
2. Verify that the video duration and frame rate (30fps) are recognized.

#### Step 4: Configure Motion & Scene Control Parameters
1. **Scene Control Mode**:
   - For studio pyramid shots (Clips 1, 2, 3, 6, 7, 10, 11): Select **`scene_control: video`** to inherit the dynamic lighting and studio stage from the driving footage.
   - For canyon outdoor shots (Clips 8, 9): Select **`scene_control: image`** to preserve the custom canyon sandstone environment of `polat_canyon_outfit_9_16.png`.
2. **Motion Strength**: Set slider to `0.85` – `0.95` (high fidelity tracking for snappy shoulder pops and wrist flourishes).
3. **Resolution**: Select **`1080p`**.

#### Step 5: Render and Export Transfer
1. Click **Generate Video**. Total synthesis time is typically 90–180 seconds.
2. Review playback for limb stability and facial likeness retention.
3. Download rendered MP4 directly to `marketing/campaigns/peshta/rendered_clips/`.

---

## 3. Formatted Operator Quick-Reference Cards

---

### [CARD P01] Polat Alemdar — Full Body Standing (9:16)
- **File Asset**: `polat_full_body_9_16.png`
- **Target Clips**: `clip_01`, `clip_03`, `clip_06`, `clip_11`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `424242`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Full-body portrait in 9:16 vertical orientation, an adult Mediterranean man in his early 30s embodying undercover Turkish mafia operative Polat Alemdar in the classic 2003 Kurtlar Vadisi aesthetic. Standing upright in a confident commanding posture facing the camera, entire body and both shoes completely visible within frame with clean floor clearance. Sharp chiseled angular jawline, defined high cheekbones, masculine cleft chin, straight prominent Mediterranean nose, firm stoic unsmiling lips, piercing deep-set hooded dark brown eyes with an intense brooding unblinking stare, naturally muted catchlights. Thick jet-black hair neatly styled in a classic swept-back pompadour with vintage pomade finish and tapered sides, clean-shaven with faint subtle 5 o'clock shadow stubble along jawline. Visible fine skin texture with natural pores, fine lines, authentic matte-to-natural complexion, no digital smoothing, no beauty filter, no plastic skin. Lean athletic masculine build with broad shoulders and upright posture. Wearing a custom bespoke two-button tailored single-breasted suit in midnight black Italian wool with structured roped shoulders and clean waist taper, matching flat-front black wool trousers with a clean break, a crisp stark white cotton dress shirt with top button unbuttoned at open collar, polished black leather oxford dress shoes, minimalist black leather belt with silver buckle, no hat, hands resting naturally at sides with clear separation from torso. Cinematic low-key chiaroscuro lighting, hard key light casting defined shadows, cool 5600K cyan rim lighting sculpting hair and shoulders for razor-sharp edge separation, dark minimalist studio background with subtle deep crimson velvet floor. Shot on 35mm master prime lens, ultra-sharp focus on subject, 4k resolution, cinematic mafia noir realism.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD P02] Polat Alemdar — Medium Shot Waist-Up (9:16)
- **File Asset**: `polat_medium_shot_9_16.png`
- **Target Clips**: `clip_02`, `clip_04`, `clip_05`, `clip_07`, `clip_11`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `200397`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Cinematic medium shot portrait in 9:16 vertical orientation, framed from waist up, an adult Mediterranean man in his early 30s as Turkish mafia operative Polat Alemdar in the iconic 2003 Kurtlar Vadisi style. Centered in frame facing slightly three-quarters toward camera, upright commanding posture with shoulders broad and square. Strong angular facial bone structure, high sculpted cheekbones, sharp masculine jawline, straight prominent Roman nose, firm resolute lips, intense brooding dark brown eyes with heavy hooded lids and a piercing penetrating gaze, naturally muted iris catchlights, faint furrow in brow. Thick jet-black hair neatly brushed back in a slick pompadour with natural hair texture and subtle pomade sheen. Visible fine facial pores, realistic skin micro-texture, faint 5 o'clock shadow stubble along jaw, matte natural skin finish, zero beauty retouching, zero plastic shine, no digital airbrushing. Wearing a tailored midnight-black wool suit jacket with structured shoulders and crisp notch lapels, a pristine white poplin collared dress shirt open at the throat, a vintage stainless steel wristwatch with black dial on his left wrist, hands held in natural low resting gesture at waist height. Dramatic chiaroscuro lighting, warm 3200K key light creating classic Rembrandt light triangle on right cheek, paired with cool 5600K electric cyan rim light tracing shoulders and hair to isolate dark silhouette, dark moody studio backdrop. Shot on 50mm anamorphic lens, shallow depth of field, sharp focus on eyes, 35mm film grain, high-end filmic color grade.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD P03] Polat Alemdar — Close-Up Portrait (9:16)
- **File Asset**: `polat_closeup_9_16.png`
- **Target Clips**: `clip_05`, `clip_11`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `551024`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Tight cinematic close-up portrait in 9:16 vertical orientation, framed chest-up, capturing the iconic intense stare of an early 2000s Turkish mafia protagonist in the definitive Kurtlar Vadisi aesthetic. Subject is a 33-year-old Mediterranean man with sharp masculine features, looking directly into the camera lens with an unwavering brooding unblinking expression. Defined mandibular angle, prominent cheekbones, straight sharp nose, determined composed lips, piercing dark hooded eyes with natural depth and zero oversized reflections. Meticulously styled jet-black swept-back hair with individual strand definition, crisp side tapers, subtle authentic stubble along the jawline. Authentic high-resolution skin texture with visible pores, natural skin irregularities, matte finish without oily sheen, no synthetic smoothing or AI artifacts. Crisp white collared dress shirt with open collar framing his neck, dark black wool suit lapels visible at the bottom edge. High-contrast filmic chiaroscuro lighting, deep rich shadow with soft fill, brilliant cool 5600K rim light carving the jawline against dark atmospheric studio background. 35mm motion picture still, Kodak Vision2 film stock look, cinematic contrast, 4k ultra-sharp detail on iris and skin.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD P04] Polat Alemdar — Canyon Outfit Variant (Fedora & Pilot Jacket) (9:16)
- **File Asset**: `polat_canyon_outfit_9_16.png`
- **Target Clips**: `clip_08_canyon_transition_stomp.mp4`, `clip_09_canyon_double_point.mp4`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `810934`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Cinematic medium-full portrait in 9:16 vertical orientation, adult Mediterranean man in his early 30s as undercover operative Polat Alemdar in outdoor canyon mission attire from Kurtlar Vadisi. Standing in a dynamic swaggering stance in an arid rocky canyon setting with warm sandstone rock formations and a vivid deep red architectural doorway in the background. Chiseled rectangular jawline, high cheekbones, masculine cleft chin, intense piercing brooding dark brown eyes with focused stoic stare. Jet-black hair neatly trimmed at temples, wearing a dark vintage wool felt fedora hat angled slightly low over his brow, styled with a tailored dark navy-blue and black heavy pilot bomber jacket with silver zip hardware and structured aviator collar, crisp white shirt collar visible at neck, tailored charcoal wool trousers. Visible fine masculine skin texture with natural pores, subtle stubble along jawline, matte natural complexion, zero beauty filter, zero plastic sheen. High-contrast natural sunlight with dramatic canyon shadow and strong 5600K crisp rim light sculpting hat brim, shoulders, and jacket silhouette for sharp edge separation against the quarry backdrop. Shot on 35mm cinematic anamorphic lens, 4k film still, gritty cinematic action realism.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD P05] Polat Alemdar — Master Split-Screen Reference Sheet (16:9)
- **File Asset**: `polat_master_split_sheet_16_9.png`
- **Target Use**: Soul Training, Consistency Reference, Model Fine-Tuning
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `16:9 (1920x1080)`
- **Quality**: `2K`
- **Seed**: `424242`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Split-screen character sheet composition in 16:9 horizontal orientation, left side a full-body shot of the character standing upright in a neutral straight standing pose facing the camera with both feet flat on the ground and arms relaxed at sides, full head-to-toe framing with the whole body and both feet visible, right side a tight close-up chest-up portrait of the same character, identical original male character on both sides, single subject only exactly one person with only the character in frame, pure white seamless studio background, professional character sheet presentation, Mediterranean man in his early 30s with healthy olive skin tone, chiseled rectangular jawline, defined prominent cheekbones, masculine cleft chin, straight Roman nose, firm unsmiling lips, piercing deep-set hooded dark brown eyes with naturally muted catchlights and no artificial glare, thick jet-black hair styled swept-back with pomade finish and neat tapered sides, clean-shaven with faint subtle 5 o'clock shadow stubble, visible fine skin texture with natural pores and subtle uneven tone, matte-to-natural complexion, no digital smoothing, no beauty filter, no AI-airbrushed look, skin free of artificial glare or highlight blooms, lean muscular build with broad shoulders and upright posture, wearing a bespoke tailored two-button midnight black wool suit jacket, matching flat-front black wool trousers, crisp white cotton collared shirt unbuttoned at top collar button, polished black leather oxford dress shoes, minimalist black leather belt with silver buckle, no hat, no sunglasses, no weapons, natural anatomy, high-end unretouched commercial photography style, soft diffused studio lighting without harsh reflections, cinematic realism, clean white background, 4K quality, sharp focus on skin texture detail, single subject only, exactly one person, only the character in frame, left panel standing full-body head-to-toe not cropped not sitting, right panel tight close-up not full body, no text, no watermark, no logos, no frame borders.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD E01] Elif Eylül — Seated on Red Velvet Steps with Pearls (9:16)
- **File Asset**: `elif_seated_red_steps_9_16.png`
- **Target Clips**: `clip_10_elif_red_steps.mp4`, `clip_02_hook_duo_roses.mp4`, `clip_06`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `110492`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Cinematic 9:16 vertical full-body shot, an elegant 26-year-old Turkish woman embodying the iconic Elif Eylul from the 2003 Kurtlar Vadisi series, seated gracefully on wide tiered steps covered in rich crimson red velvet carpet. Seated with poise, legs angled gently together in a modest dignified posture, torso upright, hands clasped softly over her chest holding a delicate multi-strand freshwater pearl necklace. Soft heart-shaped face, delicate rounded chin, soft natural cheekbones, natural full lips with a subtle rosy-nude satin finish, deeply expressive warm hazel-brown almond eyes looking upward with a tender heartfelt gaze, natural dark arched eyebrows. Rich chocolate brunette hair falling past shoulders in loose soft cascading waves with natural bounce and fine flyaways, natural center parting. Visible natural skin texture with fine pores, delicate natural peach blush, matte unretouched complexion, no digital airbrushing, no plastic smoothing, naturally soft catchlights in eyes. Wearing an elegant minimalist ivory-white silk-crepe tea-length dress with a modest boat neckline and clean tailoring, dainty white ankle-strap low heels, no excessive jewelry. Soft directional warm key lighting from camera left illuminating her face and dress, gentle ambient fill preserving shadow details, rich deep red background with soft cinematic bokeh. Shot on 35mm film prime lens, nostalgic early 2000s Turkish television aesthetic, ultra-sharp focus, timeless emotional elegance.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD E02] Elif Eylül — Medium Shot Waist-Up (9:16)
- **File Asset**: `elif_medium_shot_9_16.png`
- **Target Clips**: `clip_04_call_response_1.mp4`, `clip_07_duo_charm_finger_wag.mp4`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `789123`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Cinematic medium shot in 9:16 vertical orientation, framed from waist to head, an expressive and graceful 26-year-old Turkish woman as Elif Eylul from 2003 Kurtlar Vadisi with natural beauty of early 2000s Turkish cinema. Standing in a balanced, elegant pose facing slightly to the side with head turned toward camera. Harmonious oval-to-heart facial structure, soft jawline, gentle cheekbones, warm hazel-brown eyes radiating intelligence and emotional depth, subtle natural dimple, soft natural rose lips. Shoulder-length dark chocolate brunette hair in voluminous natural waves, effortless blowout finish with natural movement. Authentic unretouched skin texture with visible pores, matte-to-satin finish, natural subtle makeup with earthy taupe tones, zero beauty filter, zero plastic AI glare. Wearing a refined cream fine-knit merino wool turtleneck sweater beneath a tailored charcoal wool blazer with soft lapels, a dainty silver chain necklace, minimalist and professional attorney elegance. Soft diffused studio lighting with warm golden key light and gentle wrap-around fill, subtle cool backlight accentuating brunette hair strands, clean atmospheric dark studio background with subtle warm undertones. 35mm cinematic film still, sharp focus on facial expression, high-end organic realism.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD E03] Elif Eylül — Close-Up Portrait (9:16)
- **File Asset**: `elif_closeup_9_16.png`
- **Target Clips**: `clip_05_call_response_2.mp4`
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `9:16 (1080x1920)`
- **Quality**: `2K`
- **Seed**: `982314`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Intimate cinematic close-up portrait in 9:16 vertical orientation, chest-up framing of a beautiful 26-year-old Turkish woman as Elif Eylul in the definitive 2003 Kurtlar Vadisi aesthetic. Soft natural facial features, delicate bone structure, expressive deep hazel eyes filled with poignant emotion, soft natural eyebrows, full lips with natural rosy hue and satin finish, faint natural dimple near mouth. Dark chocolate brunette hair framing the face with soft natural waves, fine wisps catching the light. Ultra-realistic skin micro-texture, visible fine pores, soft natural skin tone, authentic matte appearance, completely free of modern digital smoothing, airbrushing, or artificial shine. Wearing a high-neck cream cashmere knit top, collar of a dark tailored jacket visible at base. Soft flattering portrait lighting, warm golden-hour key light creating subtle highlights on cheekbones and in irises, soft shadows, delicate background blur with warm ambient tones. Captured on 85mm portrait prime lens, shallow depth of field, 35mm film grain, 4k ultra-detailed organic portraiture.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### [CARD E04] Elif Eylül — Master Split-Screen Reference Sheet (16:9)
- **File Asset**: `elif_master_split_sheet_16_9.png`
- **Target Use**: Soul Training, Consistency Reference, Model Fine-Tuning
- **Model**: `Soul 2.0` (`soul_2`)
- **Aspect Ratio**: `16:9 (1920x1080)`
- **Quality**: `2K`
- **Seed**: `554433`

```text
[POSITIVE PROMPT - CLICK TO COPY]
Split-screen character sheet composition in 16:9 horizontal orientation, left side a full-body shot of the character standing upright in a neutral straight standing pose facing the camera with both feet flat on the ground and arms relaxed at sides, full head-to-toe framing with whole body and both feet visible, right side a tight close-up chest-up portrait of the same character, identical original female character on both sides, single subject only exactly one person with only the character in frame, pure white seamless studio background, professional character sheet presentation, Turkish woman in her mid-20s with warm fair skin tone, soft heart-shaped face with gentle jawline, delicate chin, natural cheekbones, expressive warm hazel-brown almond eyes with naturally muted catchlights and no artificial glare, natural dark arched eyebrows, soft full lips with natural rosy-nude satin finish, rich chocolate brunette hair in loose cascading waves with natural blowout finish, visible fine skin texture with natural pores and subtle uneven tone, natural visible makeup with visible foundation texture rather than flawless coverage, faint natural peach blush, matte-to-natural complexion, no digital smoothing, no beauty filter, no AI-airbrushed look, skin free of artificial glare or highlight blooms, slender graceful build with balanced proportions, wearing an elegant ivory-white tailored tea-length dress with a modest neckline, dainty white strap heels, thin silver chain necklace, no bag, natural anatomy, high-end unretouched commercial photography style, soft diffused studio lighting without harsh reflections, cinematic realism, clean white background, 4K quality, sharp focus on skin texture detail, single subject only, exactly one person, only the character in frame, left panel standing full-body head-to-toe not cropped not sitting, right panel tight close-up not full body, no text, no watermark, no logos, no frame borders.
```

```text
[NEGATIVE PROMPT - CLICK TO COPY]
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

## 4. Operator Troubleshooting & Quality Assurance Checklist

| Issue Observed | Root Cause | Operator Remediation Action |
|:---|:---|:---|
| **Limb tearing / melting during shoulder pops** | Lack of edge contrast between dark suit and dark background. | Verify that the prompt contains the `5600K cyan rim lighting` clause. Increase rim light intensity or switch from `scene_control: video` to `scene_control: image`. |
| **Face identity drift during head turns** | Diffusion checkpoint substituting a generic influencer face. | Re-run with fixed Seed (`424242` or `200397`). Ensure `soul_2` model is active. Do not use generic artistic style modifiers like "digital illustration". |
| **Excessive plastic/glossy skin sheen** | AI default beauty filter overfitting. | Ensure the full **Anti-AI Realism Engine** block is present at the front of the prompt. Verify negative prompt includes `plastic skin, porcelain doll skin, airbrushed`. |
| **Feet or hands cropped in wide shots** | Model hallucinating framing boundaries. | Verify aspect ratio is set strictly to `9:16`. Confirm positive prompt contains `entire body and both shoes completely visible within frame with clean floor clearance`. |
| **Fedora missing in Canyon scenes** | Universal negative prompt filtering out hats. | When running Card P04, explicitly ensure `hat` and `fedora` are removed from the Negative Prompt field. |
