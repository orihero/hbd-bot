# 12 — The media gateway (the owner's RTX 5090)

**Written 2026-09-25 with IMAGE_VIDEO_SPEC M2.6.** This page is the runbook IMAGE_VIDEO_SPEC §9.4
asks for: how the local generation gateway is hardened, what the owner installs on it, how its
kept files are swept, which variables the bot and worker read, and the switches an operator
flips when it misbehaves. Cite it by section (`12-media-gateway §3`), never by path.

> **STATUS — nothing on this page has been run on the box or on `abdu-test` yet.** The bayram
> side (the `doctor`, the Access-token headers, the boot refusals, the Redis switches) is in the
> tree and unit-tested against a fake gateway. **Every step marked _owner_ below is a change to
> the Windows machine or to the Cloudflare account, and only the owner can make it.** The M2.6
> acceptance is one line — **`doctor` green from the production host** — and it is not met until
> §2 is done. Like [11-ci-cd.md](11-ci-cd.md), this page does not use the `[HOST]`/`[TREE]`
> marks: its subject is code in this repository and work not yet done on the box.

Decisions behind it: `DECISIONS.md` D21 (local flux2 for paid images), D22 (Wan Standard tier,
customer pre-emption) and D24 (guard models on the 5090, fail closed).

---

## 1. What the gateway is, and who owns which half

A FastAPI front over ComfyUI and Ollama on one Windows RTX 5090, today on port `5174`, plain
HTTP, a residential dynamic IP. `POST /generate` → `GET /jobs/{id}` → `GET /result/{id}`; one job
at a time; flux2 images in 31–43 s, a 5 s Wan clip in ~17.5 min. The traps the adapter is written
against are `RESEARCH-image-video-pipeline` §1.3 and IMAGE_VIDEO_SPEC §4.2.

| Half | What | State |
| --- | --- | --- |
| bayram (this repo) | `LocalGatewayProvider`: header-only key, model allowlist (`flux2`, `wan`), closed payload, Access service-token headers | built (M2.2, M2.6) |
| bayram | boot refusals: model off the allowlist, half an Access token, an offered local SKU with no URL or key | built (M2.2, M2.6) |
| bayram | `python -m bayram.tools.media doctor [--contract]`, `make gateway-doctor` / `make gateway-contract` | built (M2.6) |
| bayram | the operator switches: pause, backend override, GPU reserved window | built (M2.2) |
| _owner_ | key rotation, Tunnel + Access, header-only auth, closed port, autostart (§2) | **not done** |
| _owner_ | G1–G8 on the gateway (§3) | **not done**; G3 exists and needs its contract confirmed |
| _owner_ | the `api_in_*` sweeper (§4) | **not done** |

**The beta gate.** Image goes to the allowlist only after M3.1 lands (no unscreened beta), and
no real customer photo crosses the gateway before §2 is green (IMAGE_VIDEO_SPEC §9.1 heading).

---

## 2. Hardening (IMAGE_VIDEO_SPEC §9.1) — _owner_

Do these in order; each ends with the `doctor` row that proves it. How to run the doctor is §2.4.

### 2.1 Rotate the gateway key

The current key is in plain text in both gateway READMEs, `FIXING-VIDEO.md` and
`scripts/client.py:9` on the owner's side (research §1.5). Treat it as public.

1. Generate a new one on any machine: `openssl rand -hex 32`.
2. Set it as the gateway's key (wherever the gateway reads `GENAI_API_KEY`), restart the gateway.
3. Remove the old literal from the READMEs, `FIXING-VIDEO.md` and `scripts/client.py`; have
   `client.py` read it from the environment. If any of those files is ever vendored into
   `reference/`, redact first.
4. On the production host set `BAYRAM_GENAI_API_KEY` in the **bot and worker** env file only
   (`/etc/bayram/bayram.env`, which bot and worker share — never `bayram-admin.env` or
   `payme.env`; the admin process refuses vendor secrets in production) and restart
   `bayram-bot` and `bayram-worker`.
5. The owner's own scripts (marketing renders, the film pipeline) get the new key too, or they
   stop working the moment step 2 lands.

Proof: `doctor` → `[  ok] auth` and `[  ok] keyless refused`.

### 2.2 Cloudflare Tunnel + Access in front of `:5174`

The production host's own ingress is already a Cloudflare Tunnel (`00-host-inventory.md`, the
`cloudflared` rows); the gateway gets the same shape, as its own tunnel on the Windows box.

1. **Tunnel.** In Zero Trust → Networks → Tunnels, create a tunnel for the 5090; install it on
   Windows with the dashboard's `cloudflared.exe service install <token>` so it runs as a Windows
   service. Public hostname: a name on the owner's zone (for example `genai.<zone>`) →
   service `http://localhost:5174`.
2. **Access application.** Zero Trust → Access → Applications → *Self-hosted* on that hostname.
   One policy, action **Service Auth**, include **Service Token** = a token created for bayram
   (Access → Service Auth → *Create service token*; copy the Client ID and Secret once — the
   secret is shown only at creation). No *Allow* policy for humans on this hostname: a browser
   that needs `/docs` goes through a separate application or the LAN.
3. **Give bayram the token.** In the bot and worker env file:
   `BAYRAM_GENAI_BASE_URL=https://genai.<zone>`, `BAYRAM_GENAI_ACCESS_CLIENT_ID=<id>.access`,
   `BAYRAM_GENAI_ACCESS_CLIENT_SECRET=<secret>`. Both or neither — boot refuses half a token.
   The adapter sends them as `CF-Access-Client-Id` / `CF-Access-Client-Secret` on every request.
4. **Close the raw port.** Remove the router's port-forward to `5174`; bind the gateway's uvicorn
   to `127.0.0.1` (cloudflared reaches it on loopback); add a Windows Defender Firewall inbound
   *block* rule for TCP 5174 as a second fence. From any outside network,
   `curl -m 5 http://<old-public-ip>:5174/health` must now time out.
5. **Service-token expiry.** Access service tokens expire (the default is a year). Put the expiry
   date in the owner's calendar; an expired token is a `302` at the edge (see §7).

Proof: `doctor` → `[  ok] base url: https://…`, `[  ok] access token`, `[  ok] reachable`.
A `302` on `reachable` means Access did not accept the token.

### 2.3 Header-only auth on the gateway; CORS off

Today every route declares an optional `api_key` **query** parameter beside the `x-api-key` and
`authorization` headers (`/openapi.json`). A key in a URL lands in every proxy and access log on
the way. bayram never sends it that way (asserted by tests), but the gateway must stop accepting
it, so nobody else's client can leak it either.

1. Remove the `api_key` query parameter from the gateway's auth dependency, so only `X-API-Key`
   (or `Authorization: Bearer`) authenticates.
2. Remove the CORS middleware, or set `allow_origins=[]`. Nothing calls the gateway from a browser.

Proof: `make gateway-contract` → `[  ok] header-only auth`. Until then that row is `fail`, and it
is the row that keeps the contract smoke red today.

### 2.4 Reachability from the production host — the M2.6 acceptance

Run from `abdu-test`, as the user that can read the bot's env file:

```bash
sudo bash -c 'set -a; . /etc/bayram/bayram.env; set +a; \
  /opt/bayram/venv/bin/python -m bayram.tools.media doctor'
# and once, after §2.3 and after any gateway upgrade:
sudo bash -c 'set -a; . /etc/bayram/bayram.env; set +a; \
  /opt/bayram/venv/bin/python -m bayram.tools.media doctor --contract'
```

(The env-file and venv paths are the ones `bayram-release` uses; check them against
`00-host-inventory.md` before the first run.) From a checkout, `make gateway-doctor` and
`make gateway-contract` do the same with the dotenv the `ENV` knob selects.

What it asks, in order, and what it never does:

| Row | Question | `fail` means |
| --- | --- | --- |
| `base url` | `https://`, no `?api_key=` in the URL | plain HTTP or a key in the URL; **nothing is contacted** |
| `api key`, `image model`, `video model` | key set; models are `flux2` / `wan` | unset key, or a model off the allowlist |
| `access token` | both halves of the service token | half a token (`warn` when neither: Access is not in front) |
| `reachable` | `GET /health` → 200 through the tunnel | down, blocked, or `302`/`403` at the Access edge; the rest is skipped |
| `auth` | `GET /v1/models` → 200 with the key in `X-API-Key` | the gateway refused the key |
| `models` | `flux2` and `wan` are installed | a configured model is missing (others, e.g. `zootopia`, are counted, never selectable) |
| `keyless refused` | the same call **without** the key → 401/403 | the gateway serves anyone |
| `G4 guards` | `GET /v1/moderate/health` → 200 | `warn` only, until M3 |
| `contract *` (`--contract`) | the live `/openapi.json` against what the adapter sends | a route we call is gone, or the body schema would reject a key we send |

The key is never put in a URL, not even to prove the gateway still accepts one — the contract row
reads that from the schema. Exit `0` = no `fail` (warnings allowed); `3` = a check failed; `2` =
the settings did not load. With `BAYRAM_GENAI_BASE_URL` unset and no SKU on `local` it prints one
`skip` row and exits `0`.

**It also runs in every release.** IMAGE_VIDEO_SPEC §9.1 item 4 puts it in `bayram-release`'s
verify step, and it is there as `python -m bayram.tools.media doctor --release`, with
`/etc/bayram/bayram.env` sourced in a subshell (the `alembic_run` rule). `--release` makes a red
report **fatal only while an offered media SKU routes to `local`**: the release then exits `4`
(verify failed) and says to fix the gateway or pause the SKU. With media off, the same findings
print as a warning and the release lands.

The worker also **refuses to boot** with a SKU offered on `local` whose `BAYRAM_GENAI_BASE_URL`
is not `https://` (plain HTTP is accepted on loopback only) or carries `?api_key=` — the same
rule as the `base url` and `key in url` rows above, so a key and customers' photos are never
sent unencrypted even when nobody runs the doctor.

### 2.5 Start without a login — _owner_, Q12

The gateway starts only after an interactive Windows login today. Either:

* run it as a service — `nssm install bayram-genai <python.exe> <args>`, or a Task Scheduler task
  *At startup*, *Run whether user is logged on or not* — and turn autologon off; or
* accept login-dependent start and **monitor** it: the `reachable` row going red is the signal,
  and `python -m bayram.tools.media pause image` (§6) is the response.

`cloudflared` installed by §2.2 is already a service. Risk R5 (IMAGE_VIDEO_SPEC §11) sets the
exit: three outages over an hour in 30 days moves Standard video to fal Wan 2.5.

---

## 3. What the owner adds to the gateway: G1–G8 (IMAGE_VIDEO_SPEC §6.5) — _owner_

The contracts are the spec's, repeated here so the person at the Windows box has one page. The
spec wins if they ever disagree. "Needed by" is the first milestone that cannot ship without it.

| # | Endpoint / change | Contract (summary) | Needed by | How bayram sees it |
| --- | --- | --- | --- | --- |
| **G1** | `POST /v1/moderate/text` → Qwen3Guard-Gen-4B | req `{items:[{id, content}], lang_hint}`; resp `{model, results:[{id, safety: safe\|controversial\|unsafe, categories, logprobs?}], latency_ms}`. Interim: the model as `qwen3guard-gen-4b` on `/v1/chat/completions`, parsed strictly | M3 (screening) | the M3 moderator; fail closed |
| **G2** | `POST /v1/moderate/image` → ShieldGemma 2 (4B) | req `{items:[{id, data_b64}], policies:[sexually_explicit, dangerous, violence, {custom: "sexualised depiction of a minor"}]}`; resp `{model, results:[{id, scores:{policy: p_yes}}]}`. **In memory, never written to disk** | M3 | the M3 moderator |
| **G3** | `POST /v1/audio/transcriptions` (whisper large-v3 — **exists**) | multipart OGG; resp must carry `text`, `language`, per-segment `no_speech_prob` / `avg_logprob`. Confirm the verbose shape | M4 (voice notes) | the M4 screener |
| **G4** | `GET /v1/moderate/health` | resident guard models, VRAM held, p95 latency | M3 | `doctor` row `G4 guards` (`warn` until then) |
| **G5** | `priority` + `client` on `/generate` and in `GET /queue` | `priority:"customer"` goes ahead of queued non-customer jobs; a running job is never interrupted | before paid volume | `doctor --contract` row `G5 priority`; bayram already sends `client:"bayram"` |
| **G6** | `DELETE /result/{id}` and `DELETE /inputs/{hash}` (or the §4 sweeper) | removes a job's inputs and outputs | M2 go-beta with real photos (the sweeper suffices) | `doctor --contract` row `G6 delete`; bayram's `media_cleanup` calls it once it exists |
| **G7** | no request-body logging on G1–G3 and G8; guard routes bypass the ComfyUI queue | guards answer ≤10 s p95 **while Wan renders** | M3 | measured by the owner during a Wan render (Q4) |
| **G8** | `POST /v1/moderate/describe` → PaddleOCR(-VL) text + a ≤30-word qwen3-vl caption | req `{items:[{id, data_b64}]}`; resp `{results:[{id, ocr_text, caption}]}`; in memory only | M3 | its strings go through G1 and the L0 lexicon |

VRAM: both guards resident (~8 GB each in bf16) compete with Wan. If G7's latency misses during a
render, pin the guards to reserved VRAM or run Wan with offloading (Q4).

**Also on the gateway, not numbered in §6.5:** declare `length` (and `client`, `priority`) in the
`GenReq` schema. Today the schema declares `frames`, which the gateway ignores, and not `length`,
which it honours; our body gets through only because the schema says `additionalProperties:
true`. `doctor --contract` reports that as `warn: contract body`; if `additionalProperties` is ever
turned off without declaring them, the row goes `fail` before a customer's render does.

---

## 4. The `api_in_*` sweeper (IMAGE_VIDEO_SPEC §9.2) — _owner_

The gateway keeps every input as `api_in_<hash>.png` and every output, with no delete endpoint
(research §1.3). A customer's photo would outlive every retention clock bayram keeps (owner
decision O16: uploads deleted immediately after delivery). Until G6 exists, **the sweeper is the
only control, and its interval is the exposure window.**

* **What:** every `api_in_*` file in ComfyUI's input directory, and every output file the gateway
  wrote for a job, older than **60 minutes** (`gateway_retention_minutes`, spec §9.2).
* **When:** a Task Scheduler task every 15 minutes, *Run whether user is logged on or not*, so a
  file lives at most ~75 minutes.
* **Not:** the owner's own marketing or film inputs — scope the delete to the `api_in_` prefix and
  to the gateway's output subfolder, not the whole ComfyUI tree.

A starting point, **untested** — fill in the two directories from the box's ComfyUI install:

```powershell
# sweep-api-inputs.ps1 — delete gateway inputs/outputs older than 60 minutes (IMAGE_VIDEO_SPEC §9.2)
$cutoff = (Get-Date).AddMinutes(-60)
$inputs  = 'C:\<ComfyUI>\input'             # where api_in_<hash>.png lands
$outputs = 'C:\<ComfyUI>\output\<gateway>'  # the gateway's own output subfolder only
Get-ChildItem -Path $inputs -Filter 'api_in_*' -File |
  Where-Object LastWriteTime -lt $cutoff | Remove-Item -Force
Get-ChildItem -Path $outputs -File -Recurse |
  Where-Object LastWriteTime -lt $cutoff | Remove-Item -Force
```

```powershell
schtasks /Create /TN "bayram-genai-sweep" /SC MINUTE /MO 15 /RU SYSTEM `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\ops\sweep-api-inputs.ps1"
```

Check it once by hand: send one image job through the gateway, confirm its `api_in_*` file exists,
wait 75 minutes, confirm it is gone. **When G6 lands**, bayram's `media_cleanup` (worker job,
`bayram.runtime.media_jobs`) gains the delete call, and the sweeper stays as the backstop for jobs
whose cleanup never ran.

The CSAM-class exception (O16, spec §6.7) lives on **bayram's** side: the held bytes are bayram's
own stored copy of the input or output, encrypted under `legal_hold`, and bayram's G6 call will
skip held rows. The gateway's copy is not the evidence, so the time-based sweeper needs no
exception of its own.

---

## 5. Environment variables (bot + worker only)

All in `/etc/bayram/bayram.env` on the host, `.env` in a checkout; `.env.example` carries every
one with an empty or default value. **None of the secrets goes near the admin or Payme file** —
the admin process refuses every `VENDOR_SECRET_FIELDS` member in production (D13/D14).

| Variable | Default | Secret | Notes |
| --- | --- | --- | --- |
| `BAYRAM_GENAI_BASE_URL` | empty | no | `https://` tunnel hostname (§2.2). Empty = gateway unused; boot refuses an offered `local` SKU without it |
| `BAYRAM_GENAI_API_KEY` | empty | **yes** | sent as `X-API-Key` only, never in a URL (§2.1) |
| `BAYRAM_GENAI_ACCESS_CLIENT_ID` | empty | no | Cloudflare Access service-token id, `<id>.access` (§2.2) |
| `BAYRAM_GENAI_ACCESS_CLIENT_SECRET` | empty | **yes** | its secret. Both or neither — boot refuses one alone |
| `BAYRAM_GENAI_IMAGE_MODEL` | `flux2` | no | must be on `LOCAL_MODEL_ALLOWLIST`, or boot refuses even with media off |
| `BAYRAM_GENAI_VIDEO_MODEL` | `wan` | no | same |
| `BAYRAM_IS_IMAGE_OFFERED`, `…_VIDEO_STANDARD_OFFERED`, `…_VIDEO_FAST_OFFERED` | `false` | no | the catalogue switches (spec §4.5) |
| `BAYRAM_IMAGE_BACKEND`, `BAYRAM_VIDEO_STANDARD_BACKEND` | `local` | no | `local\|higgsfield\|fal\|fake`; the Redis override wins for new submits (§6) |
| `BAYRAM_MEDIA_BETA_ENABLED`, `BAYRAM_MEDIA_BETA_ALLOWLIST` | `false`, empty | no | required on any rail that is not live-paid (O9) |
| `BAYRAM_MEDIA_IMAGE_RENDER_TIMEOUT_S`, `…_VIDEO_RENDER_TIMEOUT_S` | `300`, `2400` | no | counted only while the gateway says `running` |

The full media block (prices, deadlines, steps, the margin rule) is in `.env.example` under
"Media: images and videos"; spec §9.5 lists what later milestones add (the moderator URL, the
Gemini key pool, Higgsfield, fal). `gateway_retention_minutes` (60) is a setting on the **box's**
sweeper (§4), not a bayram variable.

---

## 6. Operating it: pause, reroute, reserve the GPU

The switches live in Redis; the writer is `python -m bayram.tools.media` (spec §4.5). Run with
the bot's env file as in §2.4. **Redis here is a cache**: a restart without persistence clears
every switch, so re-run `status` after any Redis restart.

| Situation | Command | Effect |
| --- | --- | --- |
| See everything | `… media status` | each SKU's env / override / effective backend, pause, the GPU window |
| Gateway down, or `doctor` red | `… media pause image` (and `video_standard`) | the SKU leaves the picker; open quotes answer `media.busy`; **paid jobs continue** and retry until their deadline |
| It is back | `… media resume image` | the key is deleted |
| Route new submits elsewhere | `… media backend image higgsfield` / `… env` | `env` clears the override. `higgsfield` is built (M6.1, §6.4 below); `fal` has no adapter yet and an override to it fails the submit cleanly |
| The owner needs the GPU (film, a reel rebuild) | `… media reserve --minutes 180` | every SKU on `local` refuses at Done/quote (O11); paid jobs already queued continue. Max 24 h |
| Window over | `… media release` | |
| A customer is refunded in cash from the Payme cabinet (spec §7.5) | `… media credit <tg> <sku> --revoke --actor <you> [--job <id>]` | takes back the one credit the failed job granted, so the customer is not refunded twice; `--grant` hands one out where the automatic paths missed. Writes `media_credit_ledger` `admin_correction` + the balance in one transaction; never below zero. Needs the database, not Redis |

### 6.1 The GPU reserved window procedure

1. `reserve --minutes N` **first**, so no new customer order is taken.
2. Wait for bayram's queue to drain: `GET /queue` on the gateway shows no job with
   `client:"bayram"`.
3. Start the owner's own work. `release` when done (or let the window lapse).

### 6.2 The marketing-yield rule, until G5

Customer jobs pre-empt marketing by **queue order, never by killing a render** — `/interrupt` is
global and bayram never calls it (spec §3.4, §4.2). Until G5 gives `/generate` a `priority`, the
owner's marketing and film scripts must yield by hand: **before each submit, read `GET /queue`;
if any running or pending job carries `client:"bayram"`, wait and re-check** (a 30–60 s poll is
enough for images; a video holds the GPU ~17.5 min). bayram stamps `client:"bayram"` on every
job for exactly this. A script that cannot do that runs inside a reserved window (§6.1) instead.

### 6.3 Gemini TTS key pool rotation — M4, not built yet

The voice pool (spec §5.2, O8) lands with M4. When it does, rotation is: add the new key to the
comma-separated `BAYRAM_GEMINI_TTS_API_KEYS`, restart bot and worker, watch its `key_ref` go
healthy on the admin card, then remove the old key and restart again. A key is identified only by
`key_ref = sha256(key)[:8]`; never paste a key into a ticket or a log. This section is rewritten
when M4 ships.

---

### 6.4 Higgsfield — the paid backend (spec §4.3, M6.1)

The adapter is built and **off**: nothing reaches it until a SKU's backend (env or override) is
`higgsfield`. Unlike the gateway it bills per call, so before any SKU is pointed at it:

1. A **separate** Higgsfield REST account from the consumer MCP wallet; set
   `BAYRAM_HIGGSFIELD_API_KEY_ID` and `BAYRAM_HIGGSFIELD_API_SECRET` (the secret never on the
   admin host).
2. **Confirm the endpoint paths and body keys** in `HIGGSFIELD_MODELS` against the vendor's
   docs, then run one free `POST /estimate/<path>` per configured model. The paths were written
   from the documentation, not a live account: a wrong one fails the estimate, and a failed
   estimate refuses the submit — a busy quote, never money spent.
3. Record the measured per-output USD in `BAYRAM_HIGGSFIELD_IMAGE_USD_PER_OUTPUT` /
   `…_VIDEO_USD_PER_OUTPUT` (boot's margin check does no IO and refuses without them), and
   `BAYRAM_HIGGSFIELD_USD_PER_CREDIT` if the estimate answers in credits.
4. Keep `BAYRAM_IMAGE_MAX_COST_USD` / `BAYRAM_VIDEO_FAST_MAX_COST_USD` at or above one
   attempt's estimate per output: the stage chain refuses to post an attempt whose estimate
   would take the request past its ceiling (every variant, every retry), and the adapter
   refuses any single submit above the ceiling's per-output share.
5. Counsel's view on sending customers' photos abroad (spec R6, M6.3) before any SKU with
   photos is routed here.

What an operator sees afterwards: an ambiguous submit (timeout, 5xx, no request id) is never
re-posted — the job is `held` with `ambiguous_submit`, reconciled by hand in the Higgsfield
dashboard, and failed with a credit by `media_sweep` after two hours. A `nsfw` verdict from the
vendor fails the job `provider_rejected` with one credit. 402/403 is the balance: top up, then
`resume`.

### 6.5 The Fast tier, several photos natively, and the fallback (spec §3.3, §4, M6.2)

**Turning Fast on.** The code is built and the tier screen appears by itself once a second
tier is sellable: `BAYRAM_IS_VIDEO_FAST_OFFERED=true` **and** `BAYRAM_VIDEO_FAST_PRICE_MINOR`
set (35 000–45 000 soʻm recommended, spec §7.1). With the price empty Fast is not sellable
whatever the flag says, and boot refuses an offered SKU with no price. With Fast on, a GPU
reserved window (§6.1) closes Standard only — Fast is still sold, since it renders on
Higgsfield.

**Precondition, owner only — M6.3, spec R6 / Q6.** Before `BAYRAM_IS_VIDEO_FAST_OFFERED=true`
(and before any other SKU or fallback is pointed at `higgsfield`), record counsel's view on
sending customers' photos abroad under the Personal Data law (amendment 1125), with its date,
in the PR or change note that flips the flag. Nothing in code checks this. If counsel advises
against: keep Fast off, or keep every SKU that takes photos on `local` (R6's "Fast tier
text-only" needs a code change — ask for it; it is not built).

**Several photos, natively.** With `BAYRAM_HIGGSFIELD_VIDEO_MODEL=kling3_0_std` (the default)
several photos are still combined into one collage frame. `seedance_2_0_r2v` takes up to nine
references, so a Fast request's photos (at most four) go as they are and no collage is made.
Its path (`bytedance/seedance/v2.0/reference-to-video`) and list key (`image_urls`) are from
the documentation: verify them with one `/estimate` as in §6.4 step 2 before switching.

**Fallback.** `BAYRAM_<SKU>_FALLBACK_BACKEND` (empty by default) names where a job moves when
its backend refuses a submit **before** anything was created there — unavailable, out of
quota, rate-limited, a gateway 502 with no job id — and only while nothing of that job has
been posted. An ambiguous submit never falls back (§6.4 still holds it). A fallback for an
offered SKU passes the same boot checks as a backend, including the margin at that SKU's
price: a Standard job moved to Higgsfield is paid at 25 000 soʻm. The row's `backend` shows
where the job actually rendered, and the log line `a media job fell back to another backend`
records each move.

## 7. Troubleshooting by doctor row

| Row → status | Likely cause | Fix |
| --- | --- | --- |
| `base url` → fail | URL is `http://…` or carries `?api_key=` | the tunnel hostname, `https://`, no query (§2.2) |
| `access token` → fail | only one of the two variables set | set both, or neither (§2.2 step 3) |
| `access token` → warn | no Access application yet | §2.2; acceptable only before real photos |
| `reachable` → fail, `ConnectError`/`ConnectTimeout` | gateway or `cloudflared` down; the box asleep or logged out | §2.5; `pause` the local SKUs meanwhile (§6) |
| `reachable` → fail, `redirected (302)` | Access did not accept the service token (wrong, revoked or expired) | new token in Zero Trust → Service Auth; update both variables (§2.2) |
| `reachable` → fail, `refused (403)` | Access policy does not include this token, or the gateway refused the key on `/health` | check the policy's *Include*; then the key |
| `auth` → fail | key mismatch after a rotation | §2.1 step 4 on the host, restart bot + worker |
| `keyless refused` → fail | the gateway authenticates nothing on `/v1/models` | fix the gateway's auth dependency (§2.3) |
| `models` → fail | `flux2` or `wan` not loaded on the box | install/load it; the product cannot render that SKU until then |
| `header-only auth` → fail (`--contract`) | the gateway still declares `?api_key=` | §2.3 |
| `contract body` → fail (`--contract`) | the gateway's body schema no longer takes a key we send | declare `length`/`client` (§3, the note under the table) |
| `contract routes` → fail (`--contract`) | a gateway upgrade renamed or dropped a route | pin the gateway version; update `LocalGatewayProvider` in a reviewed change |

---

## 8. Go-live: media for everyone (IMAGE_VIDEO_SPEC M5.3) — _owner_

The code half of M5.3 is in the tree: the bot **and** the worker refuse to boot when an offered SKU
has no price, and when media is offered on a live-paid rail with the Terms + Privacy gate off
(`bayram.media.boot`, spec §7.4). The flip itself is the owner's. Do it in this order; every
line is a precondition of the next.

1. **Payme is in production** — `09-payme-go-live` gates all closed. Live-paid is three variables
   together: `BAYRAM_CHECKOUT_PROVIDER=payme`, `BAYRAM_CREDITS_ENFORCED=true`,
   `BAYRAM_PAYME_IS_SANDBOX=false` (O9). On the sandbox media stays allowlist-only, whatever else
   is set.
2. **The Terms and Privacy text is approved** (M1.3) and `BAYRAM_TERMS_VERSION` /
   `BAYRAM_PRIVACY_VERSION` name the approved pair. Boot refuses media on a live-paid rail without
   them: the acceptance is the whole of the real-person mitigation (O4, spec §11 R3).
3. **The migrations through the current head are applied** on the host as the owner role (they
   are not in the wheel; spec §10).
4. **The gateway is hardened and `doctor` is green from the host** (§2.4), and G1, G2, G4, G7, G8
   answer (§3): the guards fail closed, so an unreachable guard is a product that answers `busy`.
   `BAYRAM_MEDIA_MODERATOR=gateway`, `BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT` set (boot refuses either
   wrong). The §4 sweeper runs.
5. **Voice is decided** (M4.4): the listening test is signed off, and `BAYRAM_NARRATION_ROUTES`
   sends a language to ElevenLabs if its Gemini voice failed it.
6. **Prices.** `BAYRAM_IMAGE_PRICE_MINOR=500000` (5 000 soʻm, one request, two images — O5) and
   `BAYRAM_VIDEO_STANDARD_PRICE_MINOR=2500000` (25 000 soʻm, owner 2026-09-24) are the shipped
   defaults; set them explicitly in `/etc/bayram/bayram.env` so the file, not the wheel, is the
   record. `BAYRAM_VIDEO_FAST_PRICE_MINOR` stays empty until M6.
7. **The flags**, in the bot + worker env file:

   ```
   BAYRAM_IS_IMAGE_OFFERED=true
   BAYRAM_IS_VIDEO_STANDARD_OFFERED=true
   BAYRAM_IS_VIDEO_FAST_OFFERED=false
   BAYRAM_MEDIA_BETA_ENABLED=false
   ```

   `BAYRAM_MEDIA_BETA_ENABLED=true` on a live-paid rail only warns — beta ends at live-paid —
   but leave it false so the warning does not become noise. The allowlist may stay.
8. **Restart bot and worker together** (`bayram-release` or the two units). If either refuses to
   boot, the `ConfigError` names the variable; fix it and restart — do not switch the flag off to
   get past it without reading why.
9. **Smoke test, as a non-allowlisted account:** ✨ Create shows Image and Video; an image quote
   shows 💳 and the price above, never 🎁; pay once with a real card, and the two images arrive.
   Then one Standard video. Check the admin panel's billing view shows both intents, labelled by
   SKU, and the dashboard's media finance series counts them.

**Rolling back** is the pause switch, not the flag: `… media pause image` (§6) takes the SKU out
of the picker at once without a restart, and paid jobs still finish. Turn the flag off at the
next restart if the pause is going to last.

---

## 9. Open items

| Item | Owner | Blocks |
| --- | --- | --- |
| §2.1–§2.3 hardening (key, Tunnel + Access, header-only, closed port) | owner | M2.6 acceptance: `doctor` green from `abdu-test`; any real photo |
| §2.5 autostart without login (Q12) | owner | nothing hard; R5's outage count |
| §4 sweeper installed and checked once | owner | the beta with real photos |
| G1, G2, G4, G7, G8 | owner | M3 (screening), hence the image beta (§1) |
| G3 contract confirmed | owner | M4 voice notes |
| G5 `priority` | owner | paid volume; until then §6.2 |
| G6 delete routes, then bayram's `media_cleanup` calls them | owner, then code | nothing while the sweeper runs |
| `doctor` in `bayram-release verify` | code, reviewed | IMAGE_VIDEO_SPEC §9.1 item 4 in full |
| §8 go-live flip (Payme production, approved Terms pair, flags, smoke test) | owner | M5.3; media for everyone |
| §6.4 Higgsfield account, verified paths, measured `/estimate` figures, counsel (R6) | owner | any SKU on `higgsfield` (M6.2) |
| §6.5 counsel's view on photos abroad recorded (M6.3), Fast price set | owner | `BAYRAM_IS_VIDEO_FAST_OFFERED=true` |
| A public route for Higgsfield's webhook (a doorbell only: re-poll by id) | code, reviewed | nothing — the poll chain reads status every 15 s |
