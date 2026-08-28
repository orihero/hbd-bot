# HBD Bot

A Telegram bot for the Uzbekistan market. A user types a recipient's full name, answers
four short structured questions, and receives a **celebration kit**:

- one AI-generated song (~2 min) that names the recipient,
- a lyric sheet,

with the recipient's name **pronounced correctly**. That last part is the entire product.

> **Greetings are switched off.** `HBD_GREETINGS_PER_KIT` defaults to **0**, so a kit is the
> song and the sheet, and no TTS call is made at all. The spoken-greeting subsystem
> (`hbd.providers.tts`, personas, OGG/Opus voice notes) is fully built and tested and comes
> back by raising that one setting to 1–5. Note this contradicts SOW §4.5 (FR-38–FR-45),
> which makes song+speech the differentiator; it was switched off by product decision on
> 2026-08-28, not by accident.

Interface language and output language are chosen independently across Uzbek Latin
(default), Uzbek Cyrillic, Russian and English. All four ship complete.

---

## See it work in two commands, with no keys

Everything below was run on macOS 15 / Python 3.12.12 while writing this file.

```bash
make install                    # uv venv .venv + pip install -e ".[dev]"
make demo                       # one complete kit, offline
```

`make demo` runs the **real** pipeline — real orchestrator, real name subsystem, real
ffmpeg, real SQLite repository, real files — with only the five vendor adapters swapped for
fakes. No API key is read, no request leaves the machine, nothing is spent. It prints the
candidate orthographies, the acoustic verification loop re-rolling the name, and the paths
of the song, the three OGG/Opus voice notes and the lyric sheet it just produced.

It needs **ffmpeg on PATH** and nothing else (`brew install ffmpeg`).

### Drive the actual bot, still with no keys and no infrastructure

```bash
cp .env.example .env
# in .env:  HBD_USE_FAKE_PROVIDERS=true
#           HBD_TELEGRAM_BOT_TOKEN=<a real token from @BotFather>
#           HBD_DATABASE_URL=sqlite+aiosqlite:///./var/hbd.db
make dev
```

With `HBD_USE_FAKE_PROVIDERS=true` the bot keeps the wizard in memory, runs each order as
a background task in its own process, and writes to SQLite — no Redis, no Postgres, no
worker, no vendor. Message the bot, walk the wizard, and the kit arrives in the chat.
A Telegram token is the one thing a *chat* demo genuinely cannot fake; `make demo` needs
no token at all.

### Production shape

```bash
cp .env.example .env && $EDITOR .env    # real keys; HBD_USE_FAKE_PROVIDERS=false
docker compose up -d                    # postgres 16 + redis 7
make migrate                            # alembic upgrade head
make dev                                # terminal 1: the bot
make worker                             # terminal 2: the ARQ worker
```

> **If 5432 is already taken** (a system Postgres, Postgres.app, another project), the
> container will fail to bind, and `localhost` resolving to IPv6 first means a foreign
> Postgres can answer instead of ours. Pick a free port and pass it to both:
>
> ```bash
> HBD_POSTGRES_PORT=55432 docker compose up -d
> export HBD_TEST_POSTGRES_URL="postgresql+asyncpg://hbd:hbd@localhost:55432/hbd"
> export HBD_DATABASE_URL="postgresql+asyncpg://hbd:hbd@localhost:55432/hbd"
> ```
>
> The Postgres-backed tests skip rather than fail when no *project* database answers, so a
> green run with 8 skips means "Postgres not wired up", not "nothing is broken".


`make dev` is `python -m hbd.main`; `make worker` is
`python -m arq hbd.worker.WorkerSettings`.

### Checks

```bash
make test        # unit tests only: no network, Redis, Postgres or ffmpeg
make lint        # ruff
make typecheck   # mypy --strict over src and tests
make cov         # unit tests with the 80% gate
make test-all    # adds the integration tests (need ffmpeg; some need Postgres)
```

Verified on this machine: **2636 unit tests pass**, `ruff check` clean, `mypy` clean over
259 files, unit coverage **95%**. The integration suite adds 21 real-ffmpeg audio tests, 5
full-stack wizard-to-delivery tests, the offline demo, and 8 Postgres tests that need
`docker compose up -d`.

---

## Module map

Every module depends on the foundation, and on nothing else in `src/hbd/` except through
a `Protocol`. Only `hbd.runtime` knows which concrete vendor is behind which protocol.

### Foundation

| File | Owns |
|---|---|
| `src/hbd/contracts.py` | Every frozen model, the `Result` type, and all eight `Protocol` interfaces. The one file every module imports. |
| `src/hbd/config.py` | All settings: keys, model ids, timeouts, retry bounds, loudness targets, chunk durations, free-tier caps, and **the name-candidate order**. |
| `src/hbd/errors.py` | `HbdError` and its subclasses. Every error carries a customer-safe `user_message_key` *and* full operator context, and declares itself retryable or terminal. |
| `src/hbd/logging.py` | JSON logs, one correlation id per order via `contextvars`, secret redaction at the formatter. |

### Modules

| Module | Responsibility |
|---|---|
| `hbd.names` | **The differentiator.** Canonicalise the typed name, emit ranked candidate orthographies, hold the display/submitted split. Pure functions; no network. |
| `hbd.i18n` | JSON locale catalogues, CLDR plurals, the U+02BB orthography guard. |
| `hbd.providers.llm` | Gemini 3.7 Flash (paid tier, strict JSON) with an OpenAI-compatible fallback behind the identical contract. Plus `FakeLlmProvider`. |
| `hbd.providers.music` | ElevenLabs Eleven Music. Builds the `CompositionPlan`, submits it, and re-renders the name chunk alone via inpainting. Plus `FakeMusicProvider`. |
| `hbd.providers.tts` | ElevenLabs v3 for all four languages, behind one `LanguageRoutingTts`. Also hosts `ElevenLabsScribe` (STT), used **only** to verify the rendered name. |
| `hbd.audio` | ffmpeg: two-pass loudnorm, silence trim, fades, libopus 32k/48k/mono voice notes. |
| `hbd.db` | Postgres via SQLAlchemy 2.x async + Alembic. `SqlKitRepository`, retention policy, the purge job. |
| `hbd.storage` | `LocalFileStorage` — the object-storage leg, filesystem-backed. Confined keys, atomic writes, never raises. |
| `hbd.pipeline` | The orchestrator: one `Brief` in, one `Kit` out, including the acoustic verification loop and its bounded re-rolls. |
| `hbd.bot` | aiogram 3.x wizard, four locales, progress, delivery. |
| `hbd.payments` | `NoopPaymentProvider`. The only payment code in this build. |
| `hbd.runtime` | **The composition root.** Builds real or fake vendors from config, owns the container, the queue seam and the job that generates *and delivers*. |

### Entry points

| Command | Module | What it is |
|---|---|---|
| `make dev` | `hbd.main` | The bot process. Long polling. |
| `make worker` | `hbd.worker` | The ARQ worker. Owns a send-only `Bot`. |
| `make demo` | `hbd.demo` | One kit, offline, printed to the terminal. |

The one flag that changes everything is `HBD_USE_FAKE_PROVIDERS`. It is **all-or-nothing**
by design — a half-fake run spends money on a result nobody can trust — and it is refused
outright when `HBD_ENVIRONMENT=prod`.

`NoopPaymentProvider`, which always authorises, is the only payment code in this build.
There is no checkout, no ledger and no refund path; the `PaymentProvider` protocol exists
so the real rail drops in without a refactor.

---

## The name subsystem

No music model on earth supports IPA, SSML `<phoneme>`, lexicons or stress marks.
Pronunciation control is not a vendor feature, so we assemble one:

1. **Canonicalise.** Uzbek Latin `oʻ`/`gʻ` correctly use **U+02BB MODIFIER LETTER TURNED
   COMMA**. Real input arrives as U+2018, U+0027, U+0060, U+00B4 or U+2019. All of them
   fold to the canonical form.
2. **Emit ranked candidates.** Canonical, U+02BB-stripped, ASCII apostrophe, Cyrillic
   transliteration, syllable-hyphenated, phonetic respelling. **The ranking is
   configuration** — `HBD_NAME_CANDIDATE_ORDER`, default
   `stripped,canonical,hyphenated,ascii,phonetic`. A bake-off result is applied by
   reordering that variable, never by editing code.
3. **Isolate the name.** It gets its own ~8 s chunk (`Chunk.is_name_chunk`), so a
   re-render costs one chunk, not one track.
4. **Close the loop acoustically.** The rendered name chunk goes through STT and is
   compared to the intended name after normalisation. A mismatch silently re-rolls that
   chunk with the *next* candidate before the customer hears anything. Retries are bounded
   by `HBD_NAME_VERIFICATION_MAX_ATTEMPTS`; when they run out we deliver anyway.
5. **Never conflate display with submitted.** `RecipientName.display` is perfect U+02BB
   and is the only form a human ever sees. `NameCandidate.text` is what we post to a
   vendor and is internal. Two values, two fields, no exceptions.

Two notes that cost real money to learn: Uzbek stress falls on the **final** syllable, and
Russian needs `ё` preserved (Алёна /ɐˈlʲɵnə/, not Алена). Capitalising for stress does
**not** work in music models — ALL CAPS means louder, not stressed. Do not implement it.

---

## Conventions every module follows

- **Immutability.** Frozen models, tuples, `.model_copy()` / `with_*()` helpers. Nothing
  mutates an input.
- **`Result` at every boundary.** Protocol methods return `Ok`/`Err` and never raise.
  Exceptions are caught inside the adapter that owns the boundary.
- **LLM JSON.** Request the provider's structured mode, *then still* defend the parse:
  strip fences → parse → repair → validate against a pydantic model → return `Result`. Log
  the raw payload, finish reason and parse error on failure.
- **Small files.** 200–400 lines typical, 800 hard max. Functions under 50 lines.
- **Tests alongside code**, AAA structure, 80% coverage of your own module, and no unit
  test may need network, Redis, Postgres or ffmpeg. `tests/conftest.py` has the shared
  factories.

## Known gaps

Honest list, so nobody rediscovers these under pressure.

- **Object storage is filesystem-only.** `LocalFileStorage` archives to `./var/archive`
  and its `signed_url` returns a `file://` URL, because this backend has no credential to
  sign with. The S3/R2 settings that used to sit in `.env.example` were read by nothing and
  have been removed; the backend that replaces `LocalFileStorage` behind the same protocol
  brings its own configuration back with it.
- **Two i18n systems exist.** `hbd.bot.i18n` (Python catalogues, four locales, complete,
  used by every screen) and `hbd.i18n` (JSON catalogues, CLDR plurals, strict mode, also
  complete). Their key sets have diverged. The bot's is the shipped copy deck; converging
  them is a single-seam change in `hbd/bot/i18n.py::translate` plus a copy migration, and
  it was too large to do safely as part of integration.
- **Two content writers exist.** `hbd.pipeline.content.LlmContentWriter` (what the
  orchestrator actually uses) and `hbd.providers.llm.writer.write_kit` (a one-shot
  lyrics + scripts + respellings call). Both are tested; only the first is wired.
- **`hbd.pipeline.worker.generate_kit` is superseded.** It runs the pipeline but does not
  deliver. The shipped job is `hbd.runtime.jobs.generate_and_deliver`. Wiring a worker to
  the old one would generate kits that never reach a customer.
- **Rate limiting and the free-tier caps are not enforced**, and their settings are gone.
  `HBD_MAX_ORDERS_PER_USER_PER_DAY` and the four `HBD_FREE_*` knobs were read by nothing, so
  they were removed rather than left looking load-bearing. Enforcement needs
  `KitRepository.list_orders_for_user` in `BotDeps`, and adds its own config back.
  The one exception is `hbd.bot.handlers.lyrics.MAX_LYRIC_WRITES`: the lyric preview bills an
  LLM *before* the payment gate, so a per-session cap on how many lyrics one wizard may ask
  for lives in the draft. It is a spend cap, not a rate limiter, and it does not survive a
  `/start`.
- **Retention is a policy object, not configuration.** `RetentionPolicy` in
  `db/retention.py` owns the six periods as dataclass defaults, and `purge_expired` uses
  them. The `HBD_RETENTION_*` settings duplicated those numbers and were wired to nothing —
  the config block even claimed "the purge job reads these" — so they were removed. Making
  them operator-tunable means building the settings-to-policy bridge that never existed.
- **In fake mode the audio is digital silence**, so the silence-trim pass removes
  everything and loudness normalisation degrades to shipping the raw render — the
  documented degradation path, visible as a warning in `make demo`. The real loudnorm
  passes are covered by the 21 ffmpeg integration tests.
- **Inpainting does not fire on this account, and fails SILENTLY.** Settled against the
  live API on 2026-08-28. The stored-song id guess was right: `SONG_ID_HEADERS` captures it
  (`store_for_inpainting: true` returned `song-id`, and the re-roll path has a real handle).
  The *shape* of the inpaint request was wrong. Eleven Music does not take a top-level
  `source_song_id` + `chunk_index`; unchanged sections are expressed as **audio-reference
  chunks** inside the plan — `{"song_id": ..., "range": {"start_ms": ..., "end_ms": ...}}` —
  mixed with the one generation chunk being re-rendered. `conditioning_ref` is that same
  object, not a string, and `condition_strength` is `low|medium|high|xhigh`, not a float.
  **Both the old shape and the documented shape return 200 and regenerate the whole track**,
  because `POST /v1/music` ignores fields it does not honour and inpainting is reportedly
  enterprise-gated. So a name re-roll currently costs a full render *and* returns a
  different song, rather than one patched chunk. The request shape itself is now correct:
  `payload.build_inpaint_body` emits audio-reference chunks and `Chunk.conditioning_ref` /
  `Chunk.condition_strength` carry the documented types, so the day inpainting is enabled
  on the account it should start working without a code change.

---

## Out of scope for this build

Payment (Stars, Click, Payme, checkout, invoices, ledgers, refunds), the admin panel,
referral and share pages, retention reminders, voice cloning, B2B.

## Reference documents

`SCOPE_OF_WORK.md` (§4 functional requirements, §6 architecture), `DECISIONS.md` (vendor
picks and their triggers), `BENCHMARK-song-generation.md` (why ElevenLabs won).
