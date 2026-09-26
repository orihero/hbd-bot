# Recreating an Uzbek pop track natively in Suno

*Research, 2026-09-19. Question: the Peshta Add-Vocal remix cannot be downloaded — what are the lawful routes to an equivalent track we own outright?*

**Status, 2026-09-19 — settled, and settled against Peshta.** This is an investigation and it stays filed as one: sourced, confidence-stamped, with its dead ends and its unknowns left standing rather than tidied away. But it is not an open question. The ruling it reached is that the remix is unrecoverable because its lineage breaks at somebody else's upload of a commercial master — a rights decision, not a credit balance, and therefore nothing that a reset on 2026-10-18, a fresh Cover, or a support ticket can undo. What replaces it is a native Suno rebuild from our own Uzbek lyrics with no upload anywhere in its history, frozen as a Persona so every later bot song carries the same singer; the fallback, if that does not land, is commissioning a Tashkent composer under a work-for-hire buyout that assigns master *and* publishing to us; and the walk-away number on any attempt to license the real thing is roughly $3,000–$5,000 all-in for a twelve-month Uzbekistan-only social campaign (§Licensing verdict). Read anything below that reads like deliberation as the reasoning that produced that ruling, not as a door still ajar.

One thing this document cannot do is be the decision log. As of this date `docs/decisions/DECISIONS.md` stops at D19 and contains no Peshta entry at all, so nothing in the log yet records that the remix was abandoned or on what ground — the ruling lives only here. Until that entry exists, cite this document, and cite it by section name rather than by line.

## Verdict

Stop trying to save the Peshta remix — it is gone, and every route to recovering it either does not work or is not something you should do. Suno's download button is the point where commercial rights are granted, and it will not grant rights on a track whose lineage starts with somebody else's upload of a commercial master; that is not a quota problem and it will not reset on 2026-10-18. Uploading the MP3 yourself does not help either, because the upload form makes you attest you hold exclusive rights to it, and you do not. Licensing the real thing is theoretically possible (the ℗ line points at a Moscow publisher, A+, via the Silk distributor) but realistically dead: you would need master and publishing separately, most-favoured-nations parity doubles the quote, and the use you actually want — a paid bot minting per-customer derivative versions — is a bespoke product licence nobody grants a pre-revenue startup. What you do instead: keep your Uzbek lyrics, which are genuinely yours and the best asset in the whole package, and rebuild the feel from a text-only Suno generation with zero uploads anywhere in its history. Prompt in Turkish/Arabic musical vocabulary rather than Uzbek instrument names (the model has almost no representation of dutar, doira, ghijak), pin the language with "singing in Uzbek", target 95–102 BPM, then freeze the winning take as a Persona so every future bot song sounds like the same singer. Budget one evening: roughly 10–15 generations to land the bed, then a pronunciation pass on the Uzbek. That gets you a file that is downloadable, commercially licensed to you, outside Meta's recording fingerprints, and reusable as the product's house sound — which the remix never could have been, even if the download had worked.

## Why the download is blocked

On Suno, commercial rights attach to the act of downloading while on a paid plan, not to generating the song — their downloads FAQ says so in as many words. That makes the Download button the enforcement point: if Suno cannot warrant that you hold the rights in everything that went into a track, it withholds the download rather than silently handing you a licence it cannot back. Your track's lineage starts with another user's upload of a commercial Uzbek pop master. When anyone uploads audio to Suno they must tick an attestation that they hold exclusive rights to it; that attestation runs from the uploader to Suno, and Suno's own rules say it does not transfer to you downstream. Their Remix article is explicit that if you did not create the original you cannot monetise the remix, even when the original creator enabled remixing, and the Extend article applies the same rule to every derived operation and calls out the uploaded-audio case by name. So the rights you can hold in an output never exceed the rights you held in the input, and the chain breaks at the upload — Add Vocal, Cover, Extend or another Remix on top of it inherits the same break. Two caveats worth naming. First, Suno does not publicly document the specific mechanism that greys out the button, so the "provenance flag" story is a reconstruction from their published rights rules, not from documentation (medium confidence). Second, there is a genuinely separate constraint that could be greying out your OTHER track: since 3 September 2026 Pro carries a monthly download-credit allowance (20/month per the policy post, no rollover) — and your UI reportedly shows 25 remaining, which does not match, so either the counter you read is something else or the allowance changed. If a track you generated yourself, from your own lyrics, with no upload anywhere in its history is still not downloadable after you check that it finished rendering, that you are in the right workspace, and that you are on the web app rather than mobile, that one is worth a support@suno.com ticket. The Peshta remix is not.

## Recreation plan

1. Salvage first, delete later. Copy your Uzbek lyrics out of the Suno project into a plain text file in the repo — docs/research/ is the right home under the project's docs rule — before you touch anything else. They are your authored work, they are the strongest IP in the package, and they carry across unchanged. Also note down anything you remember liking about the remix's arrangement (where the riff dropped out, where the hook doubled) as prose notes, not audio.

2. Write your own 4–8 note riff before you open Suno. Harmonic minor, sixteenth-note staccato, stepwise motion plus one leap, resolving to the 5th or the flat 2nd, one or two bars, looping continuously. This is the single element that carries identity in this genre, and if you cannot hum yours, every generation will sound like a different song and you will burn credits re-rolling. Hum it into your phone. Do NOT try to reconstruct Peshta's actual riff — that recreates the rights problem on the composition side, which fingerprinting will not warn you about but a publisher can still pursue.

3. Set the tempo target at 95–102 BPM and test both ends. Measurement of the reference file (ffmpeg decode plus onset-envelope autocorrelation) puts its beat at ~95 BPM with a 2.53 s bar, and the file is 180.5 s at 320 kbps — but you remember it as ~102, and the wedding-floor variant of the idiom genuinely does sit at 100–104. Generate one batch at 95 and one at 102 and pick by feel. Write the number as a numeral in the Style field; 'mid-tempo' is a much weaker signal than '98 BPM'.

4. Open a blank Create page on Pro, Custom mode, no upload of any kind. Paste your lyrics with structure tags only — [Intro], [Verse], [Pre-Chorus], [Chorus], [Bridge], [Instrumental Break], [Outro] — square brackets, capitalised, each alone on its own line above its section. Nothing else goes in the lyric box: instrument and production directives there are community folklore with no documented backing, and tagging above every line measurably degrades adherence because the model loses the section shape.

5. Paste one of the three style prompts below into the Style field and fill Exclude Styles — it is the cheapest quality lever you have. Minimum exclusions for this genre: trap, 808 slides, rap, female lead vocals, EDM drop, lo-fi, acoustic singer-songwriter, sitar, tabla, Bollywood. Excluding the South Asian timbres matters specifically: models drift hard toward sitar and Bollywood whenever they see a plucked lute over a dance beat.

6. Generate 6–10 candidates per variant and select on the Uzbek diction, not on the instrumental. The backing track in this idiom is easy to get and the pronunciation is not. Change ONE descriptor per iteration and log the exact Style string next to the resulting clip ID — multi-variable changes make convergence impossible because you cannot attribute the improvement to anything.

7. Run a deliberate pronunciation pass before you fix the lyrics. Burn one throwaway generation on a nonsense line that probes q, x, oʻ, gʻ and the tutuq belgisi so you learn what the model does with each, then hand-respell the words it mangles. Keep the resulting per-word respelling table in the repo — it is reusable across every song the bot ever generates and it is worth more than any single track.

8. The moment one take has the right voice, stop re-rolling from scratch. Mint a Persona from it via the song's '...' menu, then Create, then Make a Persona, and name it descriptively ('Warm Uzbek Male Tenor, Hijaz Dance Pop'). Personas cannot be made from uploads, which is exactly why they are safe here: the lineage stays entirely yours. With a Persona attached, simplify the Style field and let the Persona carry vocal identity while Style carries genre and instrumentation.

9. Converge with the right tool rather than regenerating. Once a take is roughly 80% right: Extend continues from a timestamp and holds tempo, voice and style; Replace Section fixes one broken region and protects the rest; Cover/Remix keeps melody and structure while re-performing the production. Regenerating preserves nothing and is correct only while you are still hunting the base feel.

10. Download the keeper immediately, from the web app (WAV is web-and-paid-plan only; mobile can silently default to MP3 and you will misread a missing format as a missing download). One song is one download credit regardless of format; re-downloading the same song and pulling its stems each count once more. Archive the WAV plus the exact Style string, the Persona ID, the model version and the date alongside it.

11. Store the recipe, not the reference. Commit the Style prompt, the Exclude Styles string, the Persona name/ID, the lyric structure and the respelling table into the repo as text. A recipe is reproducible, portable across model versions and carries zero rights exposure; a reference audio file in the repo reintroduces exactly the problem you are trying to leave behind.

12. Before the new track becomes the house sound, do a five-minute composition sanity check: play your new hook against the original from memory and confirm the melody is not the same tune in a new coat. Meta's fingerprinting only polices the sound recording — a re-recorded but melodically identical track sails past it and straight into a publishing claim.

13. Post one quiet canary Reel with the new track a week before the campaign push and leave it up. Retroactive muting lands days to weeks after posting, so 'it went up and nothing happened' on day one is not evidence of anything. A clean canary at day seven is.


## Style prompt variants

### Anatolian Anchor (highest hit rate)

**Style field (paste as-is):**

```
Turkish pop with arabesk influence, emotional male vocals singing in Uzbek, melismatic ornamented delivery with audible pitch correction, staccato muted bağlama riff hook, darbuka and davul with frame drum jingles, hicaz makam over minor loop, four-on-the-floor kick, 98 BPM, glossy commercial radio production
```

**Structure:** [Intro] 8 bars, riff alone, states the hook before any voice — [Verse] single-tracked vocal, riff ducks slightly but keeps running — [Pre-Chorus] 4 bars, percussion builds, bass moves to offbeat eighths — [Chorus] doubled vocal with octave-up layer, riff and voice trade phrases — [Instrumental Break] riff plus hand percussion, no vocal — [Verse] — [Chorus] — [Bridge] bowed spike fiddle answer line or a whole-tone key lift — [Chorus] double chorus, highest energy — [Outro] bare riff, fade

**Rationale:** This is the safe bet and where you should spend your first six generations. Suno's training data for Turkish pop and arabesk is dense; its data for anything labelled Uzbek is thin, and 'Uzbek pop' on its own drifts to vaguely Slavic or vaguely generic Eastern European pop. So you buy the sonic vocabulary in Turkish and pin the language separately with 'singing in Uzbek', which is the closest thing Suno exposes to a language selector. Every Uzbek instrument name has been swapped for the cognate the model actually knows: dutar/tanbur → bağlama, doira → frame drum with jingles, ghijak → bowed spike fiddle, ufar → the 6/8 hand-percussion feel against the straight kick. 'Audible pitch correction' is deliberate and counter-intuitive: hard retune is a genre norm here, and prompting for raw or natural vocals makes the result read as folk revival instead of contemporary estrada. Exclude Styles: trap, 808 slides, rap, female lead vocals, EDM drop, lo-fi, acoustic singer-songwriter, sitar, tabla, Bollywood, orchestral ballad.

### Club-Forward (Instagram cut)

**Style field (paste as-is):**

```
Mediterranean dance pop, driving four-on-the-floor house kick with sidechain pump, bright staccato plucked lute riff doubled by a synth pluck an octave up, warm analog synth pads, male vocals singing in Uzbek, confident and forward, hijaz maqam melody, darbuka fills, 102 BPM, loud bright mid-forward mix
```

**Structure:** [Intro] 4 bars filtered riff, high-pass sweep opening up — [Verse] kick drops to half-time feel, pads sustain — [Pre-Chorus] 4 bars, riser, percussion doubles — [Chorus] full four-on-the-floor, riff and synth pluck in unison, vocal triple-tracked — [Instrumental Break] beat-only bar then riff return (the loopable 8 seconds) — [Verse] — [Chorus] — [Bridge] pads and vocal only, kick out — [Chorus] — [Outro] riff over filtered kick

**Rationale:** Different centre of gravity: here the electronic layer leads and the lute is a colour on top, rather than the acoustic riff leading with a beat underneath. Three reasons to have this one in your kit. First, it is the version that survives a phone speaker and a 15-second Reel crop — the sidechain pump and the octave-doubled pluck read instantly where a subtler arrangement does not. Second, dropping 'Turkish' and 'arabesk' and using 'Mediterranean dance pop' pulls the model away from the heavy-vibrato ballad reading that arabesk sometimes triggers, which is wrong for a birthday song. Third, the [Instrumental Break] is deliberately written as a self-contained loopable 8-second figure — that is the fragment that becomes your named Instagram 'original audio' and gets reused across every post. Sits at 102 BPM, the wedding-floor end of the range. Exclude Styles: trap, rap, female lead vocals, ballad, orchestral, lo-fi, sitar, Bollywood, dubstep, hardstyle.

### Celebration Live-Band (warmest, most on-brand)

**Style field (paste as-is):**

```
Central Asian celebration pop, live-sounding wedding band energy, joyful male vocals singing in Uzbek with melismatic phrase endings, ney intro, plucked lute and bağlama trading the hook, riq and darbuka hand percussion in 6/8 against a straight kick, bright brass stabs, harmonic minor, 95 BPM, warm punchy organic mix
```

**Structure:** [Intro] breathy ney phrase, 2 bars, then band enters on a brass stab — [Verse] hand percussion carries it, kick light, lute answers each sung line — [Pre-Chorus] percussion crescendo, clap layer enters — [Chorus] full band, brass stabs on the downbeats, vocal doubled with a third above — [Instrumental Break] call and response between lute and brass — [Verse] — [Chorus] — [Bridge] percussion breakdown, claps and voice, then a semitone key lift — [Chorus] — [Outro] band hit, ney tail

**Rationale:** The one I would actually build the Bayram product's house sound on, even though it is furthest from the reference. The other two variants are dance records; this is a celebration record, and a birthday-song bot is selling celebration, not the club. The 6/8 hand percussion against the straight kick is the characteristic lift of the whole idiom and it is much more audible here than under a house arrangement. The brass stabs stand in for karnay and surnay, the ceremonial instruments of Uzbek wedding music, using words the model knows. The semitone key lift in the bridge is a genre convention and it gives a short cut-down an obvious emotional peak to land on. Practical bonus: 'warm punchy organic mix' plus live-band framing produces takes that tolerate a customer's name being dropped into the lyric without the whole arrangement sounding synthetic around it. Exclude Styles: trap, 808, rap, EDM, house, female lead vocals, lo-fi, sitar, tabla, Bollywood, heavy autotune robotic.

## Uzbek vocal handling

- There is NO primary-source evidence that Suno handles Uzbek well. Suno markets roughly 50 languages but publishes no current definitive list, Uzbek is not confirmed on any of them, and the old suno-ai Notion 'Supported Languages' page predates the current music models. Treat Uzbek as unvalidated and budget listening time accordingly. Expect the model to read Uzbek Latin as a transliterated near-neighbour of Turkish/Russian phonology.

- Write the Style field in English, always, even with Uzbek lyrics. Suno's genre and production vocabulary is English-trained, so Uzbek or Russian words in the Style box are close to wasted tokens. The one exception is the language NAME as a hint — 'singing in Uzbek' — which is effectively the only language selector the product exposes. Put it early, inside the first 20 words.

- Your at-risk graphemes are q, x, oʻ, gʻ and the tutuq belgisi. All of them are ASCII-adjacent and will likely be read as plain English letters: q flattened to k, x read as ks rather than a velar fricative, and the modifier apostrophes on oʻ and gʻ probably ignored entirely. Burn one throwaway generation probing exactly these before you write production lyrics.

- There is no IPA and no formal phonetic notation. Respelling is empirical, per word and per voice. What actually works: hyphenate or space the syllables to force separation, CAPITALISE the stressed syllable, and respell the word the way an English or Russian speaker would transcribe it by ear. A fix that works on one Persona can fail on another, so re-test the table whenever you change voice or model version.

- Spell every recurrence of the hook character-for-character identically, apostrophes included. This is the number one cause of a chorus that sings differently on each repeat — inconsistent spelling makes the model re-derive the pronunciation from scratch each time.

- Shorten any line that comes out slurred. A lyric line too long for its musical phrase gets rushed and smeared, and the fix is fewer syllables, not a delivery tag. Swapping an awkward word for a simpler synonym is often faster than fighting the pronunciation.

- Try [Staccato] as a delivery cue on the chorus line where intelligibility matters most. It reportedly pushes the model to separate syllables rather than smear them, which helps disproportionately in a language the model handles poorly. Community-reported, not documented — low confidence, but it is free to test.

- Vocal character pins from the Style field and not at all from the lyrics box. Register words (baritone, tenor) outperform age or ethnicity words, which get ignored or produce stereotype artefacts. For this genre aim high for a male voice — verses around A3–E4, hook popping to A4 and above — with nasal, forward, chest-dominant placement and fast grace-note turns on phrase endings.

- Keep the audible pitch correction. Hard, fast retune is part of the aesthetic in contemporary Uzbek pop, not a defect. Prompting for 'raw', 'natural' or 'untuned' vocals will give you something that reads as folk revival rather than a current record.

- Double or triple-track the hook and leave the verses single-tracked with a slapback. Dotted-eighth slapback delay plus a bright medium plate is the idiomatic space — wetter than Western pop but still upfront and intelligible.

- Get a native Uzbek speaker to sign off before any generated song reaches a paying user of the bot. Nothing in the research supports assuming Suno gets Uzbek right, and a mispronounced birthday greeting is a refund, not a rounding error.

- Select candidates on diction, not on the instrumental. You will get a usable backing track in two or three generations; you may need ten to get the Uzbek clean. Judge in that order or you will keep the wrong takes.


## Licensing verdict

Not feasible — do not spend time on it, and definitely do not spend time on it before the Peshta window shuts in early October. The concrete picture: the recording's ℗ line reads "℗ 2026 gosilk.ru по лицензии А+", so the master ships through Silk (gosilk.ru), a Russian digital distributor — a pipe, not a rights owner — under licence from A+, a Moscow publisher that does run a synchronisation desk. That makes A+ the realistic first door and the artist's own management (a name, Diyorbek Yangiboev, surfaces on a paywalled aggregator; the reliable contact is the hamkorlik/reklama line in the About tab of the official YouTube channel) the second. But you would need TWO clearances — the master and the composition — and since Sobirov is credited as composer and songwriter, the publishing side most likely sits with him or his own company personally. Published benchmarks put organic social use at roughly $1,500–$20,000 per side and paid social at $3,000–$40,000 per side for independent-to-mid-tier repertoire, and most-favoured-nations parity means the two sides must match, so any quote effectively doubles. An informed guess for a 12-month, Uzbekistan-only, digital-only, non-exclusive marketing sync is maybe $2,000–$10,000 all in — and that is a guess, because no public source prices Uzbek repertoire. Worse, PESHTA was released 14 August 2026: a current priority single is the single worst moment to ask for a cheap licence. And none of that buys you what you actually need. A sync licence covers audiovisual synchronisation in a defined piece of content. A paid Telegram bot that re-voices a commercial recording per customer engages adaptation/derivative-work rights, mechanical reproduction and per-unit distribution, plus name-and-likeness exposure if customers think Sobirov is singing to them — that is a bespoke product licence with per-unit accounting, the kind of deal granted to a telecom or a major brand, not a bootstrapped bot. If someone offers you a "sync licence" for that use, it is the wrong instrument and will not protect you. Uzbekistan's collecting societies cannot help: UzAvtor and SIIPUz, regulated by the Agency on Intellectual Property under the Ministry of Justice, administer blanket public-performance and phonogram remuneration; synchronisation and derivative rights are exclusive rights, never administered collectively. If you genuinely want the Peshta flavour with full ownership, the lawful equivalent that actually fits your budget is commissioning a Tashkent composer/arranger to write an original work in the genre under a written work-for-hire buyout assigning master and publishing to your company — session rates there are low, and you end up owning something you can sell per customer forever. Set a walk-away number before you contact anybody, and if the all-in for a 12-month Uzbekistan-only social campaign exceeds roughly $3,000–$5,000, stop.

## Instagram / Meta guidance

- Do not post the Peshta-derived remix in any form — not as Reel audio, not as 'original audio', not as a muted post you swap audio into later. It carries the master's fingerprint, and Meta runs two overlapping matchers: Rights Manager (rights-holder reference files, claimant picks the action) and Audible Magic (third-party fingerprinting that can auto-block with nobody pressing anything). Fingerprints are explicitly built to survive compression, cropping, resizing and minor edits.

- A genuinely re-created track in the same style is outside the detection domain, and Meta's own rules say why: covers, recreations and karaoke versions are ineligible as reference files, because recording-level fingerprinting keys on the specific master and not on tempo, timbre, chord progression or genre. This is the structural reason the rebuild is the right move and not merely the cautious one.

- It only clears the RECORDING exposure. If your new melody reproduces the original's tune, fingerprinting will never warn you and a publisher can still come after you. Check the hook against the original from memory before it becomes the house sound.

- Your account is business-classified, which is why the in-app music library looks empty: Meta's label licences are personal and non-commercial only, so business accounts are cut down to the ~14,000-track Meta Sound Collection. Peshta will never appear there and no deal with the artist changes that — the library is Meta's, not the artist's. Seeing the song on a friend's personal account is not clearance.

- Meta Sound Collection is a fine fallback bed for posts that do not use your own track, but read its terms: the royalty-free grant covers content created, uploaded and distributed on Meta products only. Those tracks cannot travel to TikTok, YouTube or inside the Telegram bot itself. It is a Meta-only asset, never your house track.

- Upload the rebuilt track once as 'original audio' on a Reel and then NAME the audio so it enters Instagram's audio search. Every later post reuses that same named sound. You get one audio page accumulating attribution back to the account instead of dozens of orphaned one-off uploads — for a birthday-song product that compounds. Instagram will not notify you when others reuse it; check the audio page.

- Understand what 'original audio' is and is not. It is a provenance label describing how the sound entered Instagram — it asserts no ownership, proves no clearance, and does not exempt anything from Audible Magic or Rights Manager. For audio you actually own it is the correct surface and a discoverability asset; for audio you do not own it launders nothing.

- Structure every post so the music is a bed under a strong visual, not the point of the post. Meta's Music Guidelines state plainly that the more prominently music is used the higher the likelihood of restrictions, and that videos should not function primarily as a listening experience — accounts doing that risk removal and profile deletion. A static card over a full song is exactly the shape they penalise. Lead with the bot UX on screen, a reaction, a face.

- Turn on AI disclosure at posting time for any post with AI-generated audio, and check whether the account-level label applies. As of 2026 Meta requires disclosure of realistic AI-generated audio in organic content and applies 'AI info' labels automatically from technical signals; Suno now watermarks and fingerprints its own outputs, so automatic detection is likely regardless of what you declare. Undisclosed AI carries a reach penalty. Version-dependent — verify the in-app control at posting time.

- Add framing to every generated-song post. Since 30 April 2026 accounts that mainly post material they did not meaningfully transform are pulled from recommendations (Explore, Reels feed for non-followers, suggested posts), with roughly 10+ reposts in 30 days cited as the trigger. Posting raw bot outputs back to back reads as aggregation and costs you reach with no copyright claim involved. Voiceover, on-screen text, a reaction, a visible product moment — any of these count as transformation.

- Assume no strike buffer exists. Instagram publishes no numeric threshold for its repeat-infringer policy; the 'three strikes' figure is folklore. On a cold 0/0 professional account with no history to cushion anything, treat a single enforcement event as expensive.

- Silence is not safety. Reels are widely documented going from clean to 'Audio unavailable' days or weeks after posting, including when a reference file is added after you posted. Post the canary early and let it sit before you commit the campaign to that sound.

- For the marketing half specifically, a royalty-free licence ($29–$150 per track from Epidemic Sound, Artlist or Soundstripe) removes the clearance question entirely and — unlike Meta Sound Collection — can be bought with terms that travel to TikTok and YouTube. It will not sound like Peshta, but it is a zero-risk bed for posts where the music is incidental.


## Dead ends — do not spend time here

- Waiting for download credits to reset on 2026-10-18 will not unlock the remix. The block is a rights-lineage decision, not a credit-balance one, and fresh credits change nothing about it.

- Asking the original uploader to re-attest, or to enable remixing on their song, does nothing for you. Suno states outright that enabling remix does not transfer commercial rights and that the original creator retains them — the attestation runs to Suno, not to you.

- Running the flagged track through Cover, Extend, Add Vocal or another Remix to launder the lineage produces another undownloadable child. Suno's whole position is that the rights in an output cannot exceed the rights in the input, and the same rule is applied explicitly to every derived operation.

- Uploading the MP3 yourself — whether the original file, a re-recorded version, a pitch-shifted one or a partial clip — is the same dead end and a false attestation on top of it. The upload form makes you agree you hold exclusive rights to the material. The rights problem lives in the composition and the recording, not in the file format.

- Appealing to Suno support with the remix will fail and points a spotlight at your account. That channel exists for false positives on material you genuinely own; a commercial Uzbek pop master uploaded by a third party is not a false positive. Save the ticket for a self-generated track that genuinely will not download after the mundane checks.

- Third-party downloaders, API wrappers, browser tricks and stream-rippers are out of scope here, and they are also strictly worse than useless commercially: Suno's commercial grant attaches specifically to a download obtained through their approved channels, so a file obtained any other way carries no licence at all.

- Suno Studio is not a workaround. It is Premier-only, and its exemption is from the download-credit limit — a quota exemption, not a lineage clearance.

- Iterating from scratch toward the original's exact melody defeats the whole exercise. A from-scratch rebuild reproduces the genre, not the composition; chasing the actual tune recreates the rights problem on the publishing side, where fingerprinting will not warn you and a publisher still can.

- Naming Uzbek instruments in the Style field does not work. dutar, tanbur, ghijak, doira, rubab, karnay and surnay have essentially no representation in text-to-music training data — you get silence or a generic plucked string. Use the Turkish/Arabic cognates.

- Naming maqom terms does not work either. shashmaqom, usul, ufar, Buzruk, Navo, Segoh, Dugoh and Iroq are unrecognised. maqam, hijaz/hicaz and harmonic minor are the terms that land.

- 'Uzbek pop' alone as a genre tag is too thin and drifts to vaguely Slavic or vaguely Turkish generic pop. It needs 'Central Asian' or 'Turkish pop / arabesk' beside it plus explicit instruments.

- Prompting for a plucked lute over a dance beat without exclusions reliably misfires into sitar, tabla and Bollywood. Put those in Exclude Styles rather than hoping the model resolves the ambiguity.

- Piling 40 comma-separated tags or five synonyms for 'soft' into the Style field degrades output — the descriptors conflict and the result averages out to genre-median, which sounds identical to the too-few-descriptors failure. 5–10 high-information descriptors is the working range.

- Exceeding the Style character cap fails silently. Overflow is truncated, the generation proceeds, and you conclude a tag 'does not work' when it was never read. Cap is reportedly ~1,000 characters on v4.5+ (up from 200); aim for 150–300 anyway.

- Do not expect BPM or key to behave as hard parameters. A numeral BPM is a strong hint with a few BPM of drift and occasional half/double-time reinterpretation; key is barely steerable at all. Correct downstream if the bot pipeline needs exact values.

- Do not put instrument, production or mix directives in the lyrics box. No Suno documentation supports them; the lyrics box carries structure tags and, less reliably, short vocal-delivery cues. Timbre belongs in the Style field.

- Do not buy or trust the '1000+ Suno metatags' lists. They are community inventory with no documented backing; the reliable set is under a dozen structure tags.

- Do not treat a Persona as a guaranteed same-singer lock. It biases strongly and still drifts, so a catalogue still needs per-song listening checks.

- Do not expect IPA or any formal phonetic notation to work, and do not assume one respelling fix generalises across voices or model versions.

- UzAvtor and SIIPUz cannot sell you the licence you need. Collective management organisations administer public performance, broadcast and phonogram remuneration; synchronisation and derivative-product rights are exclusive rights, cleared only with the rightsholder directly.

- Silk / gosilk.ru is a distributor, not a rights owner — emailing them gets you forwarded at best. And BookingAgentInfo-style aggregators are paywalled and routinely stale for Central Asian artists; the artist's own Instagram and YouTube About tab are better.

- Owning the MP3 in ~/Downloads conveys zero rights of any kind. Possession of a file has no bearing on what you may do with the work.

- There is no way to get Peshta into Instagram's in-app music picker on a professional account. That catalogue is licensed for personal/creator use only and no deal with the artist changes what appears in Meta's library.

- Posting the remix from a personal account and resharing to the business account does not work. The fingerprint check is on the audio, not the account type — and the personal-account music licence is non-commercial by its own terms, so the moment it is tied to your product it is outside that licence anyway.

- Do not design around a detection threshold. Meta publishes no 'N seconds of match' number and neither does Audible Magic; every specific figure you will find is practitioner guesswork.

- Do not count on a three-strike buffer or read early silence as safety. No threshold is published, and detection is retroactive by design.

- Do not expect Suno's commercial grant to give the bot exclusive rights over its own output. Suno says plainly that commercial use rights do not guarantee copyright protection and that eligibility is decided by your local copyright office — plan the product's terms around a licence to sell, not around owning the master.


## Open questions

- Your UI reportedly shows 25 downloads remaining, but the 3 September 2026 policy post puts Pro at 20 per month with no rollover. Either the counter you read is a different number, or the allowance changed after that post. Check the account settings page directly before you plan around any figure.

- Why is the SECOND track ('Bayram-botda') greyed out? Unresolved. Plausible causes in order of likelihood: it shares lineage with the flagged upload (a Cover/Extend/Remix of the Peshta-derived track inherits the block and the greying is expected); download credits exhausted; the render did not finish; wrong Library/Workspace view; or you are on mobile where WAV is unavailable and only the format is missing. Work through those in that order before concluding anything.

- Suno v6 shipped on 9 September 2026 — ten days ago as of today — and I could not verify the v6 claims (v6, v6-wild, v6-mini; 'first models built on licensed music') against an official Suno page. If a v6 generation specifically will not download, an early-release limitation is plausible and entirely unverified. Check suno.com/release-notes before relying on any v6-specific behaviour. LOW CONFIDENCE.

- Whether Suno handles Uzbek at all is genuinely unknown. No published current language list confirms it, no guide found offers any Turkic or Central Asian specifics, and the old Notion 'Supported Languages' page predates the current music models. This is the single biggest unvalidated assumption in the whole plan and the first thing to test.

- The Persona UI: secondary sources report the Create page now surfaces Personas under a 'Voices' button with Style Personas inside it, rather than only via the song's '...' menu. LOW CONFIDENCE on the exact feature name and its availability on Pro as of today — check the app.

- Exact Style-field character limits and the tag-list-versus-prose behaviour are version-dependent. Two official Suno help articles cited by search (5782849 on detailed style instructions, 5782977 on prompts in lyrics) now 404, which itself says the docs were reorganised. Re-verify against the model version actually selected in your account.

- Tempo: measurement of the reference puts the beat at ~95 BPM (bar 2.53 s, file 180.5 s at 320 kbps, confirmed), but you describe the feel as ~102. Both are inside the idiom's range and they produce noticeably different records. Generate at both and decide by ear.

- Suno does not publicly document the mechanism that disables the Download button. The provenance/lineage explanation above is reconstructed from their published rights rules, not from documentation. MEDIUM CONFIDENCE on the mechanism; HIGH CONFIDENCE on the rights rules themselves and therefore on the outcome.

- Whether A+ controls the composition as well as the master is unknown — the ℗ line only evidences the recording side. If you ever do enquire, the first question to ask is which sides they control.

- Whether the melody you ended up with in the remix reproduces the original composition is something only you can judge, and it matters: if you were attached to that specific tune, that attachment is itself the risk you need to let go of.

- Whether Meta's AI-audio disclosure control behaves as described at posting time — the 2026 AI labelling rules are moving fast and the in-app control is the only authority. Check it when you post, not now.


---

## Full research report

Everything above this line is the summary. Everything below it is the long-form source for that summary — the same argument again, at length, carrying the citations, the URLs and the measurements that the sections above compress into assertions. It is kept rather than deleted because a research document that drops its sources stops being one: the half above is what will be quoted, and the half below is what will be checked when somebody doubts the quote. Nothing below overrides anything above. Where the two halves differ in wording, the summary is the revised text and this is what it was revised from.

The sections below are therefore nested one level under this heading, and that nesting is load-bearing. The two halves name their sections almost identically — "Instagram / Meta guidance" up here against "Instagram" down there, "Open questions" against "Open questions and low-confidence items" — so before the nesting, a short citation like §Instagram or §Open questions pointed at two different places with nothing to tell them apart. Now the `##` heading is always the canonical summary section and the `###` heading beneath this one is always its long-form source: §Open questions is the summary list, and the sourcing behind it is §Open questions and low-confidence items. Cite the summary unless you specifically mean the sourcing.

### The short version

You cannot download that track, you cannot fix it, and you cannot license your way out of it. What you can do — in about one evening of work — is rebuild the same feel from scratch in Suno with no uploaded audio anywhere in its lineage, keep your Uzbek lyrics exactly as written, and end up with a WAV that is yours, downloadable, commercially licensed to you, and outside Meta's recording fingerprints. That last property matters more than the download: the rebuilt track can become the Bayram product's permanent house sound, which the remix never could have been even if the button had worked.

The rest of this document explains why each of the other doors is shut, and then gives you the exact recipe.

### Why Suno will not let you download it

Suno's downloads FAQ states the rule plainly: *"For any song that you download from the platform as a paying subscriber, you have the commercial rights to the music."* ([help.suno.com/en/articles/13614785](https://help.suno.com/en/articles/13614785), and the Rights & Ownership article at [9601665](https://help.suno.com/en/articles/9601665)). The download **is** the licence grant. That makes the button the enforcement point — if Suno cannot warrant the lineage, it withholds the download rather than silently handing you a licence it cannot back.

Your track's lineage begins with another user's upload of a commercial master. Suno's upload flow requires an attestation that the uploader holds exclusive rights ([2477633](https://help.suno.com/en/articles/2477633); the ToS requires "all rights, licenses, consents, permissions, power and/or authority necessary"). That attestation runs from the uploader **to Suno**. It does not transfer to you:

- *Can I monetize a Remix?* — if you did not create the original, you cannot monetise the remix, **even when the original creator enabled remixing**; enabling remix does not transfer commercial rights ([9604993](https://help.suno.com/en/articles/9604993)).
- *Who owns an extension?* — "If you did not create the original work you are extending from, we advise against assuming ownership, attempting to monetize, etc.", and it calls out the upload case specifically ([2871105](https://help.suno.com/en/articles/2871105)).

So the rights in an output can never exceed the rights in the input, and the chain breaks at the upload. Add Vocal, Cover, Extend and further Remix all inherit the break by design.

Two honest caveats. **(1)** Suno does not publicly document the mechanism that greys the button — I checked the downloads FAQ, the limits FAQ, the ToS-update post and all 17 articles in the [Rights & Ownership category](https://help.suno.com/en/categories/550145-rights-ownership) and none of them says which songs are download-ineligible or why. The "provenance flag" story is reconstruction from the published rights rules, *medium confidence* on mechanism, *high confidence* on outcome. **(2)** There is a genuinely separate constraint: since 3 September 2026 Pro carries a monthly download-credit allowance ([suno.com/blog/suno-updates-tos](https://suno.com/blog/suno-updates-tos), [13876929](https://help.suno.com/en/articles/13876929)) — reported as 20/month for Pro, no rollover. Your UI reportedly shows 25 remaining, which does not match; verify on the settings page before planning around either number.

#### The second greyed-out track

Before assuming "Bayram-botda" is flagged too, rule out the mundane causes in this order: (1) it is itself a Cover/Extend/Remix of the Peshta-derived track, in which case the greying is expected and correct; (2) download credits exhausted; (3) the render never finished; (4) wrong Library or Workspace view; (5) you are on mobile, where WAV is unavailable and only that *format* is missing rather than the download. If a track you generated yourself from your own lyrics with **no upload in its history** still will not download after all five checks, that is exactly the case `support@suno.com` exists for — send the song link, account email and the UI state.

### Routes considered

| Route | Verdict |
| --- | --- |
| Download the existing remix | **Blocked, unrecoverable.** Rights-lineage decision, not a quota one. |
| Wait for credits to reset 2026-10-18 | **No effect.** Wrong mechanism entirely. |
| Ask the uploader to re-attest / enable remix | **No effect.** Enabling remix does not transfer commercial rights. |
| Cover / Extend / Add Vocal the flagged track | **Inherits the block.** Output rights ≤ input rights, by stated policy. |
| Appeal to Suno support | **Wrong tool.** Support handles false positives on work you own. |
| Upload the MP3 yourself | **Do not.** The attestation would be false; same block anyway. |
| Re-record / pitch-shift / partial upload | **Do not.** The rights sit in the composition and recording, not the file. |
| Third-party downloaders, rippers, API wrappers | **Out of scope, and worthless.** The Pro grant attaches to an approved-channel download; such a file carries no licence at all. |
| Suno Studio | **Not a workaround.** Premier-only, and its exemption is from the quota, not from lineage. |
| License Peshta (sync) | **Not feasible.** See below. |
| UzAvtor / SIIPUz blanket licence | **Cannot grant it.** CMOs do public performance and phonogram remuneration, never sync. |
| Meta Sound Collection for Instagram | **Works — for marketing only.** Meta surfaces only; cannot travel to the bot. |
| Royalty-free library ($29–$150/track) | **Works for marketing.** Can be licensed to travel to TikTok/YouTube. |
| Commission a Tashkent composer, work-for-hire buyout | **Strong.** You own master and publishing outright. Costs money and time. |
| **Rebuild text-only in Suno, keep your lyrics** | **RECOMMENDED.** Yours, downloadable, fingerprint-clean, reusable. |

### Licensing Peshta: the real numbers

The recording is credited *℗ 2026 gosilk.ru по лицензии А+* ([Apple Music, PESHTA single, released 14 Aug 2026](https://music.apple.com/tm/album/peshta-single/6800696958)). [gosilk.ru](https://gosilk.ru/) is Silk, a digital distributor delivering to 150+ platforms — a pipe, not a rights owner. **A+** is a Moscow music publisher that explicitly does synchronisation licensing ([i-m-i.ru profile](https://i-m-i.ru/profiles/a-publisher)). That is the realistic first door; the artist's own management is the second, and the reliable contact is the hamkorlik/reklama line on the official YouTube About tab rather than a paywalled aggregator.

You would need **two** clearances — master and composition — and since Sobirov is credited as composer and songwriter, publishing most likely sits with him or his own company. Published benchmarks ([syncvaluations.com](https://syncvaluations.com/sync-license-cost)) put organic social at roughly $1,500–$20,000 *per side* and paid social at $3,000–$40,000 *per side* for independent-to-mid-tier repertoire, and most-favoured-nations parity means the two sides must match — so a quote doubles. An informed guess for 12 months, Uzbekistan only, digital only, non-exclusive: $2,000–$10,000 all in. *That is a guess; no public source prices Uzbek repertoire.* And PESHTA released on 14 August 2026 — a current priority single is the worst possible moment to ask for a discount.

None of which buys what you actually need. A sync licence covers audiovisual synchronisation in a defined piece of content. A paid bot that re-voices a commercial recording per customer engages adaptation/derivative work, mechanical reproduction, per-unit distribution, **and** name-and-likeness exposure if customers perceive the artist as singing to them. That is a bespoke product licence with per-unit accounting — a telecom's deal, not a bootstrapped bot's. If anyone offers you a "sync licence" for that use, it is the wrong instrument.

Uzbekistan's institutions cannot bridge the gap. [UzAvtor](https://uzavtor.uz/ru/contacts) and [SIIPUz](https://siip.uz/about), supervised by the Agency on Intellectual Property under the Ministry of Justice, are collective management organisations: blanket licences for public performance, broadcast and phonogram remuneration. Synchronisation and derivative rights are exclusive rights and are never administered collectively.

**If you want the Peshta flavour with real ownership**, the affordable lawful route is commissioning a Tashkent composer/arranger to write an original work in the genre under a written work-for-hire buyout assigning master *and* publishing to your company. Session rates there are low and you end up owning something sellable per customer forever.

### What the track actually is, musically

Measured from your local file (ffmpeg decode to mono 8 kHz, onset-envelope autocorrelation over 100 ms–1.5 s lags): duration **180.49 s**, **320 kbps**, 48 kHz stereo. Periodicity hierarchy — strongest peak at 1.265 s (a 2-beat cycle), second at 0.63 s = **95.2 BPM** (the beat), third at 0.315 s (the eighth grid). So beat tempo ≈ 95 BPM, bar ≈ 2.53 s. *This is tempo and duration metadata only.* You remember it as ~102, which is the wedding-floor end of the same idiom — generate at both and pick by ear.

Structurally this is a Turkish/arabesk-adjacent production:

- **Electronic layer owns rhythm and low end.** Programmed four-on-the-floor kick, sub, clap on 2 and 4. Bass either locked to the kick or bouncing on offbeat eighths. Sidechain present but modest. Mix loud, bright, mid-forward, less sub than Western pop.
- **Acoustic layer owns melody and high percussion.** A short muted plucked-lute riff in the 400 Hz–2 kHz band is the song's identity — 4–8 notes, mostly sixteenths, stepwise plus one leap, resolving to the 5th or ♭2, running continuously and only ducking under the vocal, answering it in the gaps. Above that, a hand-percussion sweetener grouping in threes against the straight kick. **That collision of straight 4/4 against a 6/8-feeling hand layer is the characteristic lift, and it is what separates this from generic Euro house.**
- **Modal colour** is harmonic minor / Phrygian dominant (hijaz). The augmented second is the single most identifying interval. Harmony is a static two- or four-chord minor loop; the melody carries all the motion.
- **Vocal**: male, sitting high (verses ~A3–E4, hook popping to A4+), nasal and forward, chest-dominant, landing on the note then decorating out with fast grace-note turns and descending melisma. Pitch correction is fast and **audible** — that is a genre norm, not a defect. Verses single-tracked with slapback; hooks doubled or tripled with an octave or a light third above.
- **Form**: riff intro (4–8 bars, states the hook before any voice) → verse → short pre → chorus → riff break → verse → chorus → bridge (instrumental solo or a key lift) → double chorus → outro on the bare riff. ~3:00–3:40.

Sources for the idiom: [melodigging: Turkish pop](https://www.melodigging.com/genre/turkish-pop), [arabesk](https://www.melodigging.com/genre/arabesk), [Uzbek instruments](https://www.advantour.com/uzbekistan/culture/music.htm), [Shashmaqam overview](https://voicesoncentralasia.org/shashmaqam-music-and-poetry-of-central-asia/).

#### The prompting insight that matters most

**Suno has almost no vocabulary for Uzbek-specific terms and a dense one for their Turkish/Arabic cognates.** `dutar`, `tanbur`, `ghijak`, `doira`, `rubab`, `karnay`, `surnay`, `shashmaqom`, `usul`, `ufar` and the maqom names produce silence or a generic plucked string. Translate before you prompt:

| Uzbek | Prompt instead |
| --- | --- |
| dutar | bağlama, or "double-course plucked lute" |
| tanbur | "long-necked saz" |
| ghijak | kamancheh, or "bowed spike fiddle" |
| doira | "frame drum with jingles", riq, daf |
| rubab | "plucked lute", rebab |
| karnay / surnay | "bright brass stabs" |
| nay | ney *(this one works as-is)* |
| maqom | maqam |
| ufar | "6/8 dance groove" |

And write **every** style/production tag in English, pinning the language separately and explicitly: `male vocals singing in Uzbek`. That phrase is the closest thing Suno exposes to a language selector.

### The three style prompts

Full text, rationale and meta-tag structure for each are in §Style prompt variants above — the paste-as-is Style field, the bar-by-bar structure and the per-variant Exclude Styles list. In brief:

1. **Anatolian Anchor** — spend your first six generations here. Buys the sonic vocabulary in Turkish (where training data is dense) while pinning Uzbek as the sung language. 98 BPM.
2. **Club-Forward** — electronic layer leads, lute is colour on top. Survives a phone speaker and a 15-second Reel crop; its instrumental break is written as a self-contained loopable figure to become your named Instagram audio. 102 BPM.
3. **Celebration Live-Band** — furthest from the reference and the one I would actually build the product on. A birthday bot sells celebration, not the club; the 6/8-against-4/4 lift is far more audible here, and organic takes tolerate a customer's name dropped into the lyric without the arrangement sounding synthetic around it. 95 BPM.

Fill **Exclude Styles** on all three — it is the cheapest quality lever available. Minimum: `trap, 808 slides, rap, female lead vocals, EDM drop, lo-fi, acoustic singer-songwriter, sitar, tabla, Bollywood`. Excluding the South Asian timbres is not optional: models drift there whenever they see a plucked lute over a dance beat.

Style-field mechanics *(low confidence, version-dependent)*: aim for 5–10 high-information descriptors, vocal type and lead instrument inside the first 20 words, 150–300 characters in practice. The cap is reportedly ~1,000 chars on v4.5+ (was 200) and **overflow is silently truncated** — the generation still runs, so you misdiagnose a working tag as broken. Two official help URLs on style instructions (5782849, 5782977) now 404, which tells you the docs have been reorganised; verify against the model version selected in your account.

### Lyrics box: structure only

Reliable tags: `[Intro]`, `[Verse]`, `[Pre-Chorus]`, `[Chorus]`, `[Bridge]`, `[Instrumental Break]`, `[Guitar Solo]`, `[Outro]`, `[End]` ([jackrighteous meta-tag guide](https://jackrighteous.com/en-us/blogs/guides-using-suno-ai-music-creation/suno-ai-song-structure-meta-tags)). Square brackets only, capitalised, each alone on its own line directly above its section. Mixing bracket styles degrades adherence; tagging above every line destroys the section shape entirely.

Instrument and production directives in the lyric box are **folklore** — no Suno documentation enumerates them. Timbre belongs in the Style field. Ignore the "1000+ metatags" lists; the reliable set is under a dozen.

BPM as a numeral is a strong hint with a few BPM of drift and occasional half/double-time reinterpretation. Key is barely steerable at all — plan downstream correction if the bot pipeline ever needs an exact key.

### Uzbek pronunciation

**There is no primary-source evidence that Suno handles Uzbek.** It markets ~50 languages without publishing a current list, Uzbek is not confirmed on any of them, and the old [suno-ai Notion "Supported Languages"](https://suno-ai.notion.site/Supported-Languages-16550b00a3f04ee6bab541d135eaf713) page predates the current music models. Assume it is treated as transliterated near-Turkish/Russian phonology. This is the biggest unvalidated assumption in the plan.

Concrete technique (§Uzbek vocal handling above has the full list): probe `q`, `x`, `oʻ`, `gʻ` and the tutuq belgisi in one throwaway generation first; there is no IPA support, so respelling is empirical and per-voice — hyphenate syllables, CAPITALISE the stress, transcribe by ear; spell every hook recurrence character-for-character identically or the model re-derives pronunciation each time; shorten any slurred line rather than fighting it. `[Staccato]` on the chorus is worth testing for enunciation *(community-reported, low confidence)*.

Keep the per-word respelling table in `docs/research/` — it is reusable across every song the bot ever generates and is worth more than any single track. **Get a native speaker to sign off before a generated song reaches a paying user.**

### Personas: the house voice

Once one take has the right voice, stop re-rolling. Mint a Persona from it — song's `...` menu → Create → Make a Persona ([suno.com/blog/personas](https://suno.com/blog/personas)). Personas *cannot* be made from uploads, which is exactly what makes them safe: the lineage stays entirely yours. Name it descriptively ("Warm Uzbek Male Tenor, Hijaz Dance Pop"), and once attached, **simplify** the Style field — let the Persona carry vocal identity and Style carry genre and instrumentation. It is a strong bias, not a guaranteed lock; drift still happens, so a catalogue still needs per-song listening checks. *(Secondary sources report the Create UI now surfaces this under a "Voices" button — low confidence on the current name.)*

Then converge with the right tool rather than regenerating: **Extend** holds tempo/voice/style and gives you more song; **Replace Section** fixes one region and protects the rest; **Cover/Remix** keeps melody and structure while changing production. Regeneration preserves nothing and is only correct while still hunting the base feel. Change **one** descriptor per iteration and log the Style string against the clip ID.

### Instagram

Meta runs two overlapping audio matchers: **Rights Manager** (rights-holder reference files; the claimant chooses block / claim ad revenue / monitor / report) and **Audible Magic** (third-party fingerprinting that prevents a matching upload from being viewed, with nobody pressing anything) — [Meta Transparency Center](https://transparency.meta.com/reports/intellectual-property/protecting-intellectual-property-rights/). Fingerprints are built to survive compression, cropping, resizing and minor edits ([Rights Manager reference files](https://www.facebook.com/business/help/389834765475043)).

The structural reason the rebuild works: Meta's own eligibility rules **exclude covers, recreations and karaoke versions as reference files**, because recording-level fingerprinting keys on the specific master and not on tempo, timbre, chord progression or genre. A re-created track in the same style is not in the detection domain at all. **But that clears the recording exposure only** — if your new melody reproduces the original tune, fingerprinting will never warn you and a publisher can still act.

Your account is business-classified, which is why the music library looks empty: Meta's label licences are personal and non-commercial, so business accounts are cut to the ~14,000-track [Meta Sound Collection](https://www.facebook.com/business/help/402084904469945). Peshta will never appear there, and no deal with the artist changes what is in Meta's library. The Sound Collection licence is royalty-free and commercially cleared **on Meta products only** ([terms](https://www.facebook.com/sound/collection/terms)) — those tracks cannot travel to TikTok, YouTube or inside the Telegram bot.

Operationally: upload the rebuilt track once as **original audio**, then **name** it so it enters Instagram's audio search, and reuse that same named sound in every later post — one audio page accumulating attribution instead of orphaned uploads. Understand that "original audio" is a provenance label describing how the sound entered Instagram; it asserts no ownership and exempts nothing from matching, but for audio you own it is the right surface.

Three reach risks with no copyright claim attached. **(1)** [Meta's Music Guidelines](https://www.facebook.com/legal/music_guidelines) escalate restrictions as music becomes more prominent and warn against videos that function primarily as a listening experience — a static card over a full song is the shape they penalise. Lead with the bot UX, a face, a reaction. **(2)** Since 30 April 2026, accounts posting material they did not meaningfully transform are pulled from recommendations (~10+ in 30 days cited as trigger) — raw back-to-back bot outputs read as aggregation; voiceover, on-screen text or a visible product moment counts as transformation. **(3)** Meta requires disclosure of realistic AI-generated audio in organic content and applies "AI info" labels from technical signals; Suno now watermarks and fingerprints its outputs, so detection is likely regardless, and undisclosed AI carries a reach penalty *(2026, moving fast — check the in-app control at posting time)*.

Finally: assume **no** strike buffer — Instagram publishes no numeric threshold and "three strikes" is folklore; on a cold 0/0 account treat one event as expensive. And **silence is not safety**: Reels are documented going clean → "Audio unavailable" days or weeks later, including when a reference file is added after you posted. Put up a canary Reel with the new track a week before the campaign push and let it sit.

### One thing to keep in mind about ownership

Suno states directly that granting commercial use rights "does not guarantee copyright protection," and that eligibility is decided by your country's copyright office, not by Suno ([9601665](https://help.suno.com/en/articles/9601665), [2746945](https://help.suno.com/en/articles/2746945)). So plan the Bayram bot's terms around **a licence to sell**, not around owning the master — you may not be able to stop someone else reusing an output. Your **Uzbek lyrics are separately your own authored work** and are the strongest IP in the whole package. Protect them, reuse them, and put them in the repo as text.

### Open questions and low-confidence items

Collected in §Open questions above. The ones that could change your plan: the 25-vs-20 download-credit discrepancy; whether the second track's greying has a mundane cause; **v6 shipped ten days ago and I could not verify any v6 claim against an official page** — check [suno.com/release-notes](https://suno.com/release-notes) before relying on v6-specific behaviour; and whether Suno handles Uzbek at all, which is the first thing to test and the assumption everything else rests on.
