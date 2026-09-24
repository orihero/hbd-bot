# Polat Alemdar & Elif Eylül Character Reference Prompts & Parameter Catalog

**Project**: Recreating Hamdam Sobirov's "Peshta" (0:27–1:10) in 9:16 Instagram Reels format via Higgsfield AI  
**Characters**: Polat Alemdar (*Necati Şaşmaz*) & Elif Eylül (*Özgü Namal*) — *Kurtlar Vadisi* (2003–2005 Classic Era)  
**Target Engine**: Higgsfield AI (`web.higgsfield.ai` / Higgsfield MCP `soul_2` & `gpt_image_2_5`)  
**Output Directory**: `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/character_assets/`  
**Author**: `worker_m2`  
**Date**: September 2026  

---

## 1. Executive Summary & Character Engineering Rationale

This catalog provides production-grade image generation prompt cards, exact rendering parameters, and visual anchor specifications to recreate the 43-second sequence of Hamdam Sobirov's "Peshta" music video.

### 1.1 The Creative Premise
In this campaign, Hamdam Sobirov is swapped with **Polat Alemdar** (the stoic, deadly mafia protagonist in a bespoke tailored black suit), and the female lead dancer is swapped with **Elif Eylül** (the graceful, expressive early-2000s Turkish attorney). The core virality stems from the surreal, high-contrast juxtaposition: Polat Alemdar maintaining his lethal, unsmiling, intense mafia gaze while executing the sharp Khorezmian syncopated shoulder-pops (*yelka qoqish*), swaggering dance glides, and wrist flicks of the viral pop track.

### 1.2 Motion Transfer Failure Modes & Technical Countermeasures
Higgsfield's motion transfer engines (Higgsfield Genjutsu `hf_mult_motion_control` and Kling 3.0 `motion_control`) animate a static character reference anchor using the skeletal tracking, optical flow, and camera dynamics of driving video clips. In sub-optimal prompts, diffusion-based motion transfer suffers from four critical flaws:

1. **Limb & Torso Melting (Edge Bleed)**: In classic noir lighting, a black suit on a dark background lacks edge contrast. When the character rapidly pops his shoulders or twirls his wrists, the neural network cannot segment the arms from the torso, causing melted elbows or duplicate hands.
   - **Countermeasure**: Every Polat card enforces a dedicated **cool 5600K cyan/steel-blue rim light (*backlight*)** striking at 45 degrees. This creates a crisp 2-pixel specular edge along his shoulders and sleeves, guaranteeing clean limb separation during fast dance moves.
2. **Framing & Parallax Hallucination**: Puppeteering a full-body dance motion using a tight headshot forces the model to hallucinate missing hips, knees, and feet, causing gelatinous feet and floating hips.
   - **Countermeasure**: Three discrete framing scales (Full Body, Medium Shot, Close-Up) plus scene-matched specialty anchors (Canyon Outfit, Seated on Red Velvet Steps) are generated to match the exact framing of each driving shot.
3. **Synthetic "Plastic AI Sheen"**: Default modern diffusion checkpoints generate glossy, over-airbrushed, porcelain skin reminiscent of 2026 synthetic influencers. The canonical *Kurtlar Vadisi* (2003–2005) visual identity relied on 35mm film stock, visible skin pores, natural matte skin, and low-key chiaroscuro.
   - **Countermeasure**: Every card includes the mandatory **Anti-AI Realism Engine** keywords to enforce natural skin texture, visible pores, subtle facial asymmetry, and zero cosmetic airbrushing.

---

## 2. Core Realism Engine & Universal Negative Prompt

### 2.1 Anti-AI Realism Engine Module (Mandatory in Positive Prompts)
```text
visible fine skin texture with natural pores, fine lines, subtle facial asymmetries and natural texture irregularities, authentic matte-to-natural complexion, natural visible stubble texture, slight natural skin sheen rather than glossy or dewy retouched finish, no digital smoothing, no beauty filter, no AI-airbrushed look, skin completely free of artificial glare, shine or highlight blooms, naturally muted catchlights, no oversized specular glare in the iris
```

### 2.2 Universal Negative Prompt Engine
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```
*(Note: For Card P04 Canyon Outfit, remove `hat` and `fedora` from the negative prompt to allow Polat's iconic fedora hat).*

---

## 3. Polat Alemdar Prompt Cards (Necati Şaşmaz — 2003–2005)

### Card P01: Full Body Standing (9:16) — `POLAT_FULL_BODY_9_16`
- **Primary Use**: Driving clips with wide staging, full-body posture, and dance footwork (`clip_01`, `clip_03`, `clip_06`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `424242` (Alternate: `190703`)
- **Camera Angle & Focal Length**: Straight eye-level full-body shot, 35mm master prime lens, uncropped head-to-toe with clean floor clearance.
- **Lighting Setup**: High-contrast low-key chiaroscuro (4:1 key-to-fill), warm 3200K key light from 45° camera left, sharp cool 5600K cyan rim backlight sculpting shoulders and pompadour.
- **Anti-AI Realism Keywords**: Visible fine skin pores, authentic matte complexion, natural stubble texture, subtle facial asymmetry, no beauty filter, zero plastic sheen.

#### Positive Prompt (Copy-Paste Ready):
```text
Full-body portrait in 9:16 vertical orientation, an adult Mediterranean man in his early 30s embodying undercover Turkish mafia operative Polat Alemdar in the classic 2003 Kurtlar Vadisi aesthetic. Standing upright in a confident commanding posture facing the camera, entire body and both shoes completely visible within frame with clean floor clearance. Sharp chiseled angular jawline, defined high cheekbones, masculine cleft chin, straight prominent Mediterranean nose, firm stoic unsmiling lips, piercing deep-set hooded dark brown eyes with an intense brooding unblinking stare, naturally muted catchlights. Thick jet-black hair neatly styled in a classic swept-back pompadour with vintage pomade finish and tapered sides, clean-shaven with faint subtle 5 o'clock shadow stubble along jawline. Visible fine skin texture with natural pores, fine lines, authentic matte-to-natural complexion, no digital smoothing, no beauty filter, no plastic skin. Lean athletic masculine build with broad shoulders and upright posture. Wearing a custom bespoke two-button tailored single-breasted suit in midnight black Italian wool with structured roped shoulders and clean waist taper, matching flat-front black wool trousers with a clean break, a crisp stark white cotton dress shirt with top button unbuttoned at open collar, polished black leather oxford dress shoes, minimalist black leather belt with silver buckle, no hat, hands resting naturally at sides with clear separation from torso. Cinematic low-key chiaroscuro lighting, hard key light casting defined shadows, cool 5600K cyan rim lighting sculpting hair and shoulders for razor-sharp edge separation, dark minimalist studio background with subtle deep crimson velvet floor. Shot on 35mm master prime lens, ultra-sharp focus on subject, 4k resolution, cinematic mafia noir realism.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card P02: Medium Shot (Waist-Up) (9:16) — `POLAT_MEDIUM_SHOT_9_16`
- **Primary Use**: Driving clips featuring Khorezm shoulder pops (*yelka qoqish*), torso bounces, wrist flicks, and swagger walks (`clip_02`, `clip_04`, `clip_05`, `clip_07`, `clip_11`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `200397` (Alternate: `774219`)
- **Camera Angle & Focal Length**: Waist-up medium framing, slight low-angle commanding perspective, 50mm anamorphic lens.
- **Lighting Setup**: Dramatic chiaroscuro with classic Rembrandt light triangle on shadow cheek, warm 3200K key light, cool 5600K electric cyan edge rim light carving shoulders, lapels, and pompadour.
- **Anti-AI Realism Keywords**: Visible facial micro-pores, natural skin irregularities, faint lines around mouth and eyes, faint 5 o'clock shadow stubble along jaw, matte natural finish, zero digital airbrushing.

#### Positive Prompt (Copy-Paste Ready):
```text
Cinematic medium shot portrait in 9:16 vertical orientation, framed from waist up, an adult Mediterranean man in his early 30s as Turkish mafia operative Polat Alemdar in the iconic 2003 Kurtlar Vadisi style. Centered in frame facing slightly three-quarters toward camera, upright commanding posture with shoulders broad and square. Strong angular facial bone structure, high sculpted cheekbones, sharp masculine jawline, straight prominent Roman nose, firm resolute lips, intense brooding dark brown eyes with heavy hooded lids and a piercing penetrating gaze, naturally muted iris catchlights, faint furrow in brow. Thick jet-black hair neatly brushed back in a slick pompadour with natural hair texture and subtle pomade sheen. Visible fine facial pores, realistic skin micro-texture, faint 5 o'clock shadow stubble along jaw, matte natural skin finish, zero beauty retouching, zero plastic shine, no digital airbrushing. Wearing a tailored midnight-black wool suit jacket with structured shoulders and crisp notch lapels, a pristine white poplin collared dress shirt open at the throat, a vintage stainless steel wristwatch with black dial on his left wrist, hands held in natural low resting gesture at waist height. Dramatic chiaroscuro lighting, warm 3200K key light creating classic Rembrandt light triangle on right cheek, paired with cool 5600K electric cyan rim light tracing shoulders and hair to isolate dark silhouette, dark moody studio backdrop. Shot on 50mm anamorphic lens, shallow depth of field, sharp focus on eyes, 35mm film grain, high-end filmic color grade.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card P03: Close-Up Portrait (9:16) — `POLAT_CLOSEUP_9_16`
- **Primary Use**: Driving clips with tight camera close-ups, vocal delivery, direct camera stare, and dramatic intensity (`clip_05`, `clip_11`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `551024` (Alternate: `338901`)
- **Camera Angle & Focal Length**: Tight chest-up close-up portrait, direct straight-on eye-level gaze, 85mm portrait prime lens, shallow depth of field.
- **Lighting Setup**: High-contrast chiaroscuro, directional key light with deep shadow falloff, cool 5600K rim light tracing jawline, temple, and collar.
- **Anti-AI Realism Keywords**: Authentic high-resolution skin texture with visible pores, natural skin irregularities, matte finish without oily sheen, no synthetic smoothing, naturally muted iris catchlights.

#### Positive Prompt (Copy-Paste Ready):
```text
Tight cinematic close-up portrait in 9:16 vertical orientation, framed chest-up, capturing the iconic intense stare of an early 2000s Turkish mafia protagonist in the definitive Kurtlar Vadisi aesthetic. Subject is a 33-year-old Mediterranean man with sharp masculine features, looking directly into the camera lens with an unwavering brooding unblinking expression. Defined mandibular angle, prominent cheekbones, straight sharp nose, determined composed lips, piercing dark hooded eyes with natural depth and zero oversized reflections. Meticulously styled jet-black swept-back hair with individual strand definition, crisp side tapers, subtle authentic stubble along the jawline. Authentic high-resolution skin texture with visible pores, natural skin irregularities, matte finish without oily sheen, no synthetic smoothing or AI artifacts. Crisp white collared dress shirt with open collar framing his neck, dark black wool suit lapels visible at the bottom edge. High-contrast filmic chiaroscuro lighting, deep rich shadow with soft fill, brilliant cool 5600K rim light carving the jawline against dark atmospheric studio background. 35mm motion picture still, Kodak Vision2 film stock look, cinematic contrast, 4k ultra-sharp detail on iris and skin.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card P04: Canyon Outfit Variant with Fedora & Pilot Jacket (9:16) — `POLAT_CANYON_OUTFIT_9_16`
- **Primary Use**: Driving clips in the outdoor canyon/quarry setting (`clip_08_canyon_transition_stomp.mp4` and `clip_09_canyon_double_point.mp4`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `810934` (Alternate: `941820`)
- **Camera Angle & Focal Length**: Low-angle medium-full shot (knees-up), 35mm-50mm cinematic anamorphic lens, dynamic outdoor perspective.
- **Lighting Setup**: High-contrast outdoor natural sun key with dramatic canyon shadow, strong 5600K crisp rim light sculpting hat brim, shoulders, and jacket silhouette for sharp edge separation against the quarry backdrop.
- **Anti-AI Realism Keywords**: Visible fine masculine skin texture with natural pores, subtle stubble along jawline, matte natural complexion, zero beauty filter, zero plastic sheen.

#### Positive Prompt (Copy-Paste Ready):
```text
Cinematic medium-full portrait in 9:16 vertical orientation, adult Mediterranean man in his early 30s as undercover operative Polat Alemdar in outdoor canyon mission attire from Kurtlar Vadisi. Standing in a dynamic swaggering stance in an arid rocky canyon setting with warm sandstone rock formations and a vivid deep red architectural doorway in the background. Chiseled rectangular jawline, high cheekbones, masculine cleft chin, intense piercing brooding dark brown eyes with focused stoic stare. Jet-black hair neatly trimmed at temples, wearing a dark vintage wool felt fedora hat angled slightly low over his brow, styled with a tailored dark navy-blue and black heavy pilot bomber jacket with silver zip hardware and structured aviator collar, crisp white shirt collar visible at neck, tailored charcoal wool trousers. Visible fine masculine skin texture with natural pores, subtle stubble along jawline, matte natural complexion, zero beauty filter, zero plastic sheen. High-contrast natural sunlight with dramatic canyon shadow and strong 5600K crisp rim light sculpting hat brim, shoulders, and jacket silhouette for sharp edge separation against the quarry backdrop. Shot on 35mm cinematic anamorphic lens, 4k film still, gritty cinematic action realism.
```

#### Negative Prompt (Copy-Paste Ready):
*(Notice: `hat` and `fedora` are removed from this negative prompt to preserve his canonical headwear).*
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card P05: Master Split-Screen Reference Sheet (16:9) — `POLAT_MASTER_SPLIT_SHEET_16_9`
- **Primary Use**: Identity conditioning, multi-view consistency check, and Higgsfield Soul training standard.
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `16:9` (1920x1080 / 2048x1152)
- **Exact Recommended Seed**: `424242` (Alternate: `101010`)
- **Camera Angle & Focal Length**: Dual-view studio layout — Left panel: full-body standing head-to-toe 50mm; Right panel: chest-up close-up portrait 85mm.
- **Lighting Setup**: Seamless pure white studio background, diffused softbox three-point lighting, neutral 5000K daylight, clean edge definition.
- **Anti-AI Realism Keywords**: Visible fine skin texture with natural pores and subtle uneven tone, matte-to-natural complexion, no digital smoothing, no beauty filter, skin free of artificial glare.

#### Positive Prompt (Copy-Paste Ready):
```text
Split-screen character sheet composition in 16:9 horizontal orientation, left side a full-body shot of the character standing upright in a neutral straight standing pose facing the camera with both feet flat on the ground and arms relaxed at sides, full head-to-toe framing with the whole body and both feet visible, right side a tight close-up chest-up portrait of the same character, identical original male character on both sides, single subject only exactly one person with only the character in frame, pure white seamless studio background, professional character sheet presentation, Mediterranean man in his early 30s with healthy olive skin tone, chiseled rectangular jawline, defined prominent cheekbones, masculine cleft chin, straight Roman nose, firm unsmiling lips, piercing deep-set hooded dark brown eyes with naturally muted catchlights and no artificial glare, thick jet-black hair styled swept-back with pomade finish and neat tapered sides, clean-shaven with faint subtle 5 o'clock shadow stubble, visible fine skin texture with natural pores and subtle uneven tone, matte-to-natural complexion, no digital smoothing, no beauty filter, no AI-airbrushed look, skin free of artificial glare or highlight blooms, lean muscular build with broad shoulders and upright posture, wearing a bespoke tailored two-button midnight black wool suit jacket, matching flat-front black wool trousers, crisp white cotton collared shirt unbuttoned at top collar button, polished black leather oxford dress shoes, minimalist black leather belt with silver buckle, no hat, no sunglasses, no weapons, natural anatomy, high-end unretouched commercial photography style, soft diffused studio lighting without harsh reflections, cinematic realism, clean white background, 4K quality, sharp focus on skin texture detail, single subject only, exactly one person, only the character in frame, left panel standing full-body head-to-toe not cropped not sitting, right panel tight close-up not full body, no text, no watermark, no logos, no frame borders.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

## 4. Elif Eylül Prompt Cards (Özgü Namal — 2003–2005)

### Card E01: Seated on Red Velvet Steps with Pearls (9:16) — `ELIF_SEATED_RED_STEPS_9_16`
- **Primary Use**: Direct replacement for driving clip `clip_10_elif_red_steps.mp4` (seated on red steps clutching pearls) as well as `clip_02_hook_duo_roses.mp4` and `clip_06_strophe_swagger_strut.mp4`.
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `110492` (Alternate: `260388`)
- **Camera Angle & Focal Length**: Low-to-medium seated angle, 35mm prime lens, framing the subject seated gracefully on tiered red steps.
- **Lighting Setup**: Soft directional warm key light (3800K softbox) from camera left, gentle ambient fill preserving shadow details, rich deep crimson red velvet background.
- **Anti-AI Realism Keywords**: Visible natural skin texture with fine pores, delicate natural peach blush, matte unretouched complexion, no digital airbrushing, no plastic smoothing, naturally soft catchlights in eyes.

#### Positive Prompt (Copy-Paste Ready):
```text
Cinematic 9:16 vertical full-body shot, an elegant 26-year-old Turkish woman embodying the iconic Elif Eylul from the 2003 Kurtlar Vadisi series, seated gracefully on wide tiered steps covered in rich crimson red velvet carpet. Seated with poise, legs angled gently together in a modest dignified posture, torso upright, hands clasped softly over her chest holding a delicate multi-strand freshwater pearl necklace. Soft heart-shaped face, delicate rounded chin, soft natural cheekbones, natural full lips with a subtle rosy-nude satin finish, deeply expressive warm hazel-brown almond eyes looking upward with a tender heartfelt gaze, natural dark arched eyebrows. Rich chocolate brunette hair falling past shoulders in loose soft cascading waves with natural bounce and fine flyaways, natural center parting. Visible natural skin texture with fine pores, delicate natural peach blush, matte unretouched complexion, no digital airbrushing, no plastic smoothing, naturally soft catchlights in eyes. Wearing an elegant minimalist ivory-white silk-crepe tea-length dress with a modest boat neckline and clean tailoring, dainty white ankle-strap low heels, no excessive jewelry. Soft directional warm key lighting from camera left illuminating her face and dress, gentle ambient fill preserving shadow details, rich deep red background with soft cinematic bokeh. Shot on 35mm film prime lens, nostalgic early 2000s Turkish television aesthetic, ultra-sharp focus, timeless emotional elegance.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card E02: Medium Shot (Waist-Up) (9:16) — `ELIF_MEDIUM_SHOT_9_16`
- **Primary Use**: Driving clips with standing gestures, graceful call-and-response reactions, and dance movements (`clip_04_call_response_1.mp4`, `clip_07_duo_charm_finger_wag.mp4`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `789123` (Alternate: `445566`)
- **Camera Angle & Focal Length**: Waist-up medium portrait, 50mm portrait prime lens, straight eye level.
- **Lighting Setup**: Soft diffused studio lighting with warm golden key light and gentle wrap-around fill, subtle cool backlight accentuating brunette hair strands, dark atmospheric studio background.
- **Anti-AI Realism Keywords**: Authentic unretouched skin texture with visible pores, matte-to-satin finish, natural subtle makeup with earthy taupe tones, zero beauty filter, zero plastic AI glare.

#### Positive Prompt (Copy-Paste Ready):
```text
Cinematic medium shot in 9:16 vertical orientation, framed from waist to head, an expressive and graceful 26-year-old Turkish woman as Elif Eylul from 2003 Kurtlar Vadisi with natural beauty of early 2000s Turkish cinema. Standing in a balanced, elegant pose facing slightly to the side with head turned toward camera. Harmonious oval-to-heart facial structure, soft jawline, gentle cheekbones, warm hazel-brown eyes radiating intelligence and emotional depth, subtle natural dimple, soft natural rose lips. Shoulder-length dark chocolate brunette hair in voluminous natural waves, effortless blowout finish with natural movement. Authentic unretouched skin texture with visible pores, matte-to-satin finish, natural subtle makeup with earthy taupe tones, zero beauty filter, zero plastic AI glare. Wearing a refined cream fine-knit merino wool turtleneck sweater beneath a tailored charcoal wool blazer with soft lapels, a dainty silver chain necklace, minimalist and professional attorney elegance. Soft diffused studio lighting with warm golden key light and gentle wrap-around fill, subtle cool backlight accentuating brunette hair strands, clean atmospheric dark studio background with subtle warm undertones. 35mm cinematic film still, sharp focus on facial expression, high-end organic realism.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card E03: Close-Up Portrait (9:16) — `ELIF_CLOSEUP_9_16`
- **Primary Use**: Tight facial reactions, nostalgic glance cuts, and eye-contact call-and-response moments (`clip_05_call_response_2.mp4`).
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `9:16` (1080x1920 / 1152x2048)
- **Exact Recommended Seed**: `982314` (Alternate: `667788`)
- **Camera Angle & Focal Length**: Intimate chest-up close-up portrait, 85mm portrait prime lens, shallow depth of field (f/1.8).
- **Lighting Setup**: Warm golden-hour key light creating subtle highlights on cheekbones and in irises, soft shadows, delicate background blur with warm ambient tones.
- **Anti-AI Realism Keywords**: Ultra-realistic skin micro-texture, visible fine pores, soft natural skin tone, authentic matte appearance, completely free of digital smoothing or artificial shine.

#### Positive Prompt (Copy-Paste Ready):
```text
Intimate cinematic close-up portrait in 9:16 vertical orientation, chest-up framing of a beautiful 26-year-old Turkish woman as Elif Eylul in the definitive 2003 Kurtlar Vadisi aesthetic. Soft natural facial features, delicate bone structure, expressive deep hazel eyes filled with poignant emotion, soft natural eyebrows, full lips with natural rosy hue and satin finish, faint natural dimple near mouth. Dark chocolate brunette hair framing the face with soft natural waves, fine wisps catching the light. Ultra-realistic skin micro-texture, visible fine pores, soft natural skin tone, authentic matte appearance, completely free of modern digital smoothing, airbrushing, or artificial shine. Wearing a high-neck cream cashmere knit top, collar of a dark tailored jacket visible at base. Soft flattering portrait lighting, warm golden-hour key light creating subtle highlights on cheekbones and in irises, soft shadows, delicate background blur with warm ambient tones. Captured on 85mm portrait prime lens, shallow depth of field, 35mm film grain, 4k ultra-detailed organic portraiture.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

### Card E04: Master Split-Screen Reference Sheet (16:9) — `ELIF_MASTER_SPLIT_SHEET_16_9`
- **Primary Use**: Identity conditioning, multi-view consistency check, and Higgsfield Soul training standard for Elif Eylül.
- **Target Model**: `soul_2` (Quality: `2k`) or `gpt_image_2_5`
- **Aspect Ratio**: `16:9` (1920x1080 / 2048x1152)
- **Exact Recommended Seed**: `554433` (Alternate: `200502`)
- **Camera Angle & Focal Length**: Dual-view studio layout — Left panel: full-body standing head-to-toe 50mm; Right panel: chest-up close-up portrait 85mm.
- **Lighting Setup**: Seamless pure white studio background, diffused softbox three-point lighting, neutral 5000K daylight, clean edge definition.
- **Anti-AI Realism Keywords**: Visible fine skin texture with natural pores and subtle uneven tone, natural visible makeup with visible foundation texture, matte-to-natural complexion, zero digital smoothing.

#### Positive Prompt (Copy-Paste Ready):
```text
Split-screen character sheet composition in 16:9 horizontal orientation, left side a full-body shot of the character standing upright in a neutral straight standing pose facing the camera with both feet flat on the ground and arms relaxed at sides, full head-to-toe framing with whole body and both feet visible, right side a tight close-up chest-up portrait of the same character, identical original female character on both sides, single subject only exactly one person with only the character in frame, pure white seamless studio background, professional character sheet presentation, Turkish woman in her mid-20s with warm fair skin tone, soft heart-shaped face with gentle jawline, delicate chin, natural cheekbones, expressive warm hazel-brown almond eyes with naturally muted catchlights and no artificial glare, natural dark arched eyebrows, soft full lips with natural rosy-nude satin finish, rich chocolate brunette hair in loose cascading waves with natural blowout finish, visible fine skin texture with natural pores and subtle uneven tone, natural visible makeup with visible foundation texture rather than flawless coverage, faint natural peach blush, matte-to-natural complexion, no digital smoothing, no beauty filter, no AI-airbrushed look, skin free of artificial glare or highlight blooms, slender graceful build with balanced proportions, wearing an elegant ivory-white tailored tea-length dress with a modest neckline, dainty white strap heels, thin silver chain necklace, no bag, natural anatomy, high-end unretouched commercial photography style, soft diffused studio lighting without harsh reflections, cinematic realism, clean white background, 4K quality, sharp focus on skin texture detail, single subject only, exactly one person, only the character in frame, left panel standing full-body head-to-toe not cropped not sitting, right panel tight close-up not full body, no text, no watermark, no logos, no frame borders.
```

#### Negative Prompt (Copy-Paste Ready):
```text
deformed, distorted anatomy, extra limbs, extra arms, extra legs, mutated hands, fused fingers, more than five fingers per hand, missing fingers, floating limbs, disconnected limbs, plastic skin, porcelain doll skin, airbrushed, beauty filter, heavy glamour makeup, modern 2026 influencer face, female babyface, rounded juvenile jawline, cartoon, 3d render, anime, cgi illustration, oversaturated, blown out highlights, motion blur, bad eyes, crossed eyes, glowing pupils, oversized anime specular catchlights, sunglasses, hat, fedora, watermark, text, signature, logos, frame borders, cropped feet, cropped head
```

---

## 5. Parameter Summary Matrix

| Card ID | Subject | Shot Scale | Aspect Ratio | Target Model | Seed | Camera / Lens | Lighting Setup | Verified PNG Asset |
|:---:|:---|:---:|:---:|:---:|:---:|:---|:---|:---|
| **P01** | Polat Alemdar | Full Body | 9:16 | `soul_2` | `424242` | Eye-level, 35mm Prime | Chiaroscuro 4:1, 5600K cyan rim light | `polat_full_body_9_16.png` |
| **P02** | Polat Alemdar | Medium (Waist-Up) | 9:16 | `soul_2` | `200397` | Low-angle, 50mm Anamorphic | Rembrandt key, 5600K electric blue rim | `polat_medium_shot_9_16.png` |
| **P03** | Polat Alemdar | Close-Up (Chest-Up) | 9:16 | `soul_2` | `551024` | Straight-on, 85mm Prime | High-contrast key, 5600K temple/jaw rim | `polat_closeup_9_16.png` |
| **P04** | Polat Alemdar | Canyon (Fedora/Jacket) | 9:16 | `soul_2` | `810934` | Dynamic low-angle, 35mm-50mm | Hard sunlight, 5600K brim/shoulder rim | `polat_canyon_outfit_9_16.png` |
| **P05** | Polat Alemdar | Master Split Sheet | 16:9 | `soul_2` | `424242` | Dual-view (50mm + 85mm) | Diffused softbox, neutral 5000K daylight | `polat_master_split_sheet_16_9.png` |
| **E01** | Elif Eylül | Seated on Red Steps | 9:16 | `soul_2` | `110492` | Seated low-angle, 35mm Prime | Warm 3800K key, soft ambient red fill | `elif_seated_red_steps_9_16.png` |
| **E02** | Elif Eylül | Medium (Waist-Up) | 9:16 | `soul_2` | `789123` | Eye-level, 50mm Prime | Golden key, wrap fill, 5400K hair rim | `elif_medium_shot_9_16.png` |
| **E03** | Elif Eylül | Close-Up (Chest-Up) | 9:16 | `soul_2` | `982314` | Eye-level, 85mm Prime (f/1.8) | Golden-hour warm key, soft eye catchlights | `elif_closeup_9_16.png` |
| **E04** | Elif Eylül | Master Split Sheet | 16:9 | `soul_2` | `554433` | Dual-view (50mm + 85mm) | Diffused softbox, neutral 5000K daylight | `elif_master_split_sheet_16_9.png` |

---

## 6. Complete 11 Driving Clips to Character Anchor Mapping Table

Below is the definitive production mapping connecting every driving video clip in `marketing/campaigns/peshta/driving_clips/` to its recommended character anchor asset:

| Clip # | Driving File Name | Range (s) | Dur (s) | Target Character | Choreographic Action / Dance Phase | Recommended Anchor Asset | Model & Transfer Strategy |
|:---:|:---|:---:|:---:|:---|:---|:---|:---|
| **01** | `clip_01_verse1_setup.mp4` | 0.000s – 2.256s | 2.256s | Elif (01) $\rightarrow$ Polat (02) | Hook open & pyramid steps setup; phone reaction into wrist flourishes atop red steps. | `POLAT_FULL_BODY_9_16`<br>`elif_seated_red_steps_9_16.png` | Kling 3.0 (`scene_control: video`) / Genjutsu |
| **02** | `clip_02_hook_duo_roses.mp4` | 2.256s – 5.176s | 2.920s | Duo (Polat + Elif) | Romance on red velvet steps; Elif seated holding roses, Polat leaning down charismatically. | `elif_seated_red_steps_9_16.png`<br>`polat_medium_shot_9_16.png` | Kling 3.0 (1080p) / Genjutsu multi-character |
| **03** | `clip_03_chorus_drop_hero.mp4` | 5.176s – 8.976s | 3.800s | Polat Alemdar (Hero WS) | **PRIMARY 0:34 BEAT DROP!** Deep squat bounce into synchronized Khorezm Lazgi knee bounces. | `polat_full_body_9_16.png` | Kling 3.0 (1080p, skeletal tracking high) |
| **04** | `clip_04_call_response_1.mp4` | 8.976s – 11.816s | 2.840s | Elif (05) $\rightarrow$ Polat (06) | Call & Response Phase 1; Elif profile glance clutching pearls $\rightarrow$ Polat sharp shoulder pops (*yelka qoqish*). | `elif_medium_shot_9_16.png`<br>`polat_medium_shot_9_16.png` | Genjutsu (`hf_mult_motion_control`) |
| **05** | `clip_05_call_response_2.mp4` | 11.816s – 14.416s | 2.600s | Elif (07) $\rightarrow$ Polat (08) | Call & Response Phase 2; Elif direct camera eye contact $\rightarrow$ Polat upward dual-shoulder shrug on snare hit. | `elif_closeup_9_16.png`<br>`polat_medium_shot_9_16.png` | Genjutsu (`hf_mult_motion_control`) |
| **06** | `clip_06_strophe_swagger_strut.mp4` | 14.416s – 19.256s | 4.840s | Elif (09) $\rightarrow$ Polat (10, 11) | Emotional strophe & swagger strut; Elif wrist snap $\rightarrow$ Polat lateral torso sway and low-angle step strut. | `elif_seated_red_steps_9_16.png`<br>`polat_full_body_9_16.png` | Kling 3.0 (1080p) |
| **07** | `clip_07_duo_charm_finger_wag.mp4` | 19.256s – 25.496s | 6.240s | Duo (Polat + Elif) | Duo charm; backward lean on velvet steps, ensemble unison pelvic bounce, playful finger wag into lens. | `polat_medium_shot_9_16.png`<br>`elif_seated_red_steps_9_16.png` | Kling 3.0 (`scene_control: video`) |
| **08** | `clip_08_canyon_transition_stomp.mp4` | 25.496s – 29.976s | 4.480s | Polat Alemdar (White Corps) | Outdoor canyon shift; navy bomber/pilot jacket & fedora archway swagger, Lazgi stomp on red cubes. | `polat_canyon_outfit_9_16.png` | Kling 3.0 (`scene_control: image`) |
| **09** | `clip_09_canyon_double_point.mp4` | 29.976s – 35.896s | 5.920s | Polat Alemdar (White Corps) | Canyon dance break & iconic double point; wrist snap pans, low-angle elbow pump, explosive double-point. | `polat_canyon_outfit_9_16.png` | Kling 3.0 (1080p) |
| **10** | `clip_10_elif_red_steps.mp4` | 35.896s – 37.496s | 1.600s | Elif Eylül | Return to red studio; Elif seated on red steps, arms crossed tightly over chest clutching pearls. | `elif_seated_red_steps_9_16.png` | Genjutsu (`hf_mult_motion_control`, 1080p) |
| **11** | `clip_11_polat_hero_outro.mp4` | 37.496s – 43.000s | 5.504s | Polat Alemdar | Polat atop pyramid steps; extended signature wrist flick with subtle smirk, ending in statuesque hero pose. | `polat_medium_shot_9_16.png`<br>`polat_full_body_9_16.png` | Kling 3.0 (1080p) / Genjutsu |

---

## 7. Verifiable Asset Checksums & Specifications

All visual anchor files have been synthesized, validated for aspect ratio, and stored locally in `/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/character_assets/`:

- `polat_full_body_9_16.png`: 1152 x 2048, 2.5 MB, PNG
- `polat_medium_shot_9_16.png`: 1152 x 2048, 3.9 MB, PNG
- `polat_closeup_9_16.png`: 1152 x 2048, 2.7 MB, PNG
- `polat_canyon_outfit_9_16.png`: 1152 x 2048, 3.0 MB, PNG
- `polat_master_split_sheet_16_9.png`: 2048 x 1152, 1.8 MB, PNG
- `elif_seated_red_steps_9_16.png`: 1152 x 2048, 2.8 MB, PNG
- `elif_medium_shot_9_16.png`: 1152 x 2048, 3.5 MB, PNG
- `elif_closeup_9_16.png`: 1152 x 2048, 2.9 MB, PNG
- `elif_master_split_sheet_16_9.png`: 2048 x 1152, 1.9 MB, PNG
