# Superseded — audit trail only. DO NOT USE AS GENERATION INPUT.

Every file in this folder describes a **different film** from the one in
`final_polat_peshta_reel.mp4`. They were written from the Higgsfield *prompts*
and never checked against the render. A generative render does not obey its
prompt, so prompt text is **intent**, never description.

Measured against master frames, these files are wrong about: the backdrop (they
say near-black; it is a saturated red cyclorama), the set count (they say one
studio; there are three, including a desert quarry exterior that is 24% of the
film), headwear (they say "NO HAT"; there are four distinct hats), shot 10's
framing (they say wide full-body; it is a face close-up), shot 11's contents
(they say one man; it is five setups including a fully veiled woman), and the
cast itself — neither identity sheet matches any face in the film.

They also carry 121 occurrences of real actor and TV-character names in the very
fields that become prompts.

**Authority now:**

| For | Use |
| --- | --- |
| timeline, sub-shots, action | `../shot_bible_v2.json` |
| the 38 sub-shot boundaries | `../subshots.json` |
| sets, palette, lighting | `../sets_observed.json` |
| cast, wardrobe, headwear | `../cast_observed.json` |
| identity drift threshold | `../identity/README.json` |
| node schemas and traps | `../node_schemas.json` |

Kept, not deleted: they are the evidence of how the error happened.
