# Promo Peshta — Milestone 1 (M1) Macro Driving Shot Table

## Technical Calibration & Synchronization Architecture
- **Master Reference Video**: `marketing/campaigns/peshta/raw/Xamdam_Sobirov_Peshta_1080p_h264.mp4` (1920x1080, 25 fps).
- **Master Audio**: `/Users/ai/Downloads/Xamdam_Sobirov_Peshta_27s_to_1m10s.mp3` (43.000s, 48kHz stereo Suno parody remix).
- **Beat Drop Calibration**: Raw video sub-bass slam at $t = 34.184\text{ s}$; MP3 drop slam at relative $t = 6.920\text{ s}$.
- **Calibrated Video Window**: $t = 27.264\text{ s}$ (Frame 682) to $t = 70.264\text{ s}$ (Frame 1757) — total: **43.000 s**.
- **Delivered Video Format**: 1080x1920 (9:16 portrait vertical), strictly 30.0 fps Constant Frame Rate (CFR), H.264 High Profile, `yuv420p`.

## 11 Macro Driving Clips Inventory

| # | File Name | Source Range (s) | Rel Range (s) | Dur (s) | Frames (30fps) | Target Character | Crop Center X | Crop X Offset | Choreographic Action / Dance Phase |
|:---:|:---|:---:|:---:|:---:|:---:|:---|:---:|:---:|:---|
| 01 | `clip_01_verse1_setup.mp4` | 27.264s – 29.520s | 0.000s – 2.256s | 2.256s | 68 | Elif Eylül (01) -> Polat Alemdar (02) | 960 | 656 | Hook open & staging setup; smartphone surprise reaction transition into ensemble wrist flourishes atop red pyramid steps. |
| 02 | `clip_02_hook_duo_roses.mp4` | 29.520s – 32.440s | 2.256s – 5.176s | 2.920s | 88 | Duo (Polat Alemdar + Elif Eylül) | 884 | 580 | Romance on red velvet steps; Elif seated holding red roses, Polat leaning down charismatically from higher step. |
| 03 | `clip_03_chorus_drop_hero.mp4` | 32.440s – 36.240s | 5.176s – 8.976s | 3.800s | 114 | Polat Alemdar (Hero WS with Ensemble) | 960 | 656 | THE PRIMARY 0:34 BEAT DROP (source 34.184s / rel 6.920s)! Sub-bass dropout followed by massive slam; Polat drops into deep squat bounce, dancers snap into synchronized Khorezm Lazgi knee bounces. |
| 04 | `clip_04_call_response_1.mp4` | 36.240s – 39.080s | 8.976s – 11.816s | 2.840s | 85 | Elif Eylül (05) -> Polat Alemdar (06) | 940 | 636 | Call & Response Phase 1; Elif profile glance clutching pearls, cutting to Polat executing sharp alternating shoulder pops ('Yelka qoqish'). |
| 05 | `clip_05_call_response_2.mp4` | 39.080s – 41.680s | 11.816s – 14.416s | 2.600s | 78 | Elif Eylül (07) -> Polat Alemdar (08) | 850 | 546 | Call & Response Phase 2; Elif intense direct camera eye contact playing with pearls, cutting to Polat upward dual-shoulder shrug on snare hit. |
| 06 | `clip_06_strophe_swagger_strut.mp4` | 41.680s – 46.520s | 14.416s – 19.256s | 4.840s | 145 | Elif Eylül (09) -> Polat Alemdar (10, 11) | 960 | 656 | Emotional strophe & swagger strut; Elif seated prayer/wrist snap, cutting to Polat rhythmic lateral torso sway and low-angle dynamic strut down steps ('Davra glide'). |
| 07 | `clip_07_duo_charm_finger_wag.mp4` | 46.520s – 52.760s | 19.256s – 25.496s | 6.240s | 187 | Duo (Polat Alemdar + Elif Eylül) | 910 | 606 | Duo charm & playful finger wag; intercut romantic gestures, backward lean on velvet steps, ensemble unison pelvic bounce, and playful finger wag into lens. |
| 08 | `clip_08_canyon_transition_stomp.mp4` | 52.760s – 57.240s | 25.496s – 29.976s | 4.480s | 134 | Polat Alemdar (with White Corps) | 920 | 616 | Outdoor canyon shift; navy jacket archway swagger, white dancers arm thrust at start of 19s break, and center-stage Lazgi stomp on red cubes. |
| 09 | `clip_09_canyon_double_point.mp4` | 57.240s – 63.160s | 29.976s – 35.896s | 5.920s | 178 | Polat Alemdar (with White Corps) | 980 | 676 | Canyon dance break & iconic double point; wrist snap pans, low-angle elbow pump groove, explosive 'Peshta Double-Point' into camera lens, and lateral arm whip. |
| 10 | `clip_10_elif_red_steps.mp4` | 63.160s – 64.760s | 35.896s – 37.496s | 1.600s | 48 | Elif Eylül | 650 | 346 | Return to red studio; Elif seated on red steps, arms crossed tightly over chest clutching pearls with mysterious, elegant gaze. |
| 11 | `clip_11_polat_hero_outro.mp4` | 64.760s – 70.264s | 37.496s – 43.000s | 5.504s | 165 | Polat Alemdar | 1020 | 716 | Polat Alemdar atop pyramid steps; extended signature dinosaur wrist flick with smirk, ending in statuesque hero pose at attention as music transitions to Verse 2. |

**Total Sequence Duration:** 43.000 s (1290 frames at 30.0 fps CFR).

## Crop Geometry & Centering Rationale
From native 1920x1080 widescreen footage, 9:16 vertical extraction requires slicing a window of width $W = 1080 \times 9 / 16 = 607.5\text{ px}$ (rounded to 608 px for even YUV chroma alignment).
The crop formula applied per clip is:
```text
crop=w='in_h*9/16':h=in_h:x=X_OFFSET:y=0,scale=1080:1920:flags=lanczos,setsar=1,fps=30
```
Where `X_OFFSET = round(Center_X - 304)`.
- **Clips 01, 03, 06**: Centered on pyramid steps ($X = 960$, $X_{\text{offset}} = 656$).
- **Clip 02**: Centered on duo interaction ($X = 884$, $X_{\text{offset}} = 580$).
- **Clip 04 & 05**: Weighted for call-and-response close-ups with female lead and Hamdam shoulder pops ($X = 940$ / $X_{\text{offset}} = 636$ and $X = 850$ / $X_{\text{offset}} = 546$).
- **Clip 07**: Centered on duo gestures and finger wag ($X = 910$, $X_{\text{offset}} = 606$).
- **Clip 08**: Centered on canyon archway ($X = 920$, $X_{\text{offset}} = 616$).
- **Clip 09**: Centered on canyon dance break and double-point ($X = 980$, $X_{\text{offset}} = 676$).
- **Clip 10**: Centered on Elif seated on red steps ($X = 650$, $X_{\text{offset}} = 346$). Completely eliminates head cutoff (18% headroom).
- **Clip 11**: Centered on Polat studio wrist flick and hero pose ($X = 1020$, $X_{\text{offset}} = 716$).
