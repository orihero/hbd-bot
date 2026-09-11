# `deploy/` — the artefacts

This directory holds the deployment **artefacts**. The prose that explains them lives in
[`docs/deployment/`](../docs/deployment/README.md); start there.

```
deploy/systemd/bayram-bot.service      the Telegram bot — aiogram long polling
deploy/systemd/bayram-worker.service   the ARQ worker — every render, every cron job
deploy/systemd/bayram-admin.service    the admin API — FastAPI, serving its own React bundle
```

```
deploy/payme-open-orders.py         opens N *pending* payment intents for a Payme sandbox slot
deploy/first-install-proposal.md    superseded; kept only as a citation target — see below
```

The three unit files are meant to be copied onto a machine. Read the comments in them: each
unit argues for its own hardening lines, and `bayram-admin.service` carries the
`InaccessiblePaths=` that enforces the vendor-key separation at the kernel level rather than
only in the application.

`payme-open-orders.py` is copied too, and is the one artefact here that is **run** rather than
installed. Payme's engineer asks for pending orders — the `order_id` and the amount in tiyin —
at every sandbox certification slot, and nothing in the wheel can produce one: the harness
drives every intent it opens to a terminal state, and the bot's checkout is behind the stub.
It writes through `PaymeLedger.open_intent` and nothing else, stamps `is_sandbox=true` on every
row, and imports under **either** package name so it spans the `hbd` → `bayram` cutover. The
orders it opens expire in twelve hours. Read
[`08-payme.md`](../docs/deployment/08-payme.md) §6.C.1 before running it.

## They are a proposal, not a record

The unit files, and the `/srv/bayram` + `/etc/bayram` layout they assume, were authored in this
repository by an assistant with **no access to the production host**. They describe a
coherent shape somebody could deploy. They are not evidence that anything is deployed that
way, and nobody in that workflow could confirm the host runs systemd at all.

Before copying them anywhere, fill in
[`docs/deployment/00-host-inventory.md`](../docs/deployment/00-host-inventory.md) and compare.
Where a filled-in row there disagrees with a line here, **the row is right** — correct the
unit file rather than reconciling the two. That document also lists the places where this
proposal is already known to be wrong.

## Where the explanations went

| You want | Read |
| --- | --- |
| what the three processes are and why they are three | [01-architecture.md](../docs/deployment/01-architecture.md) |
| which dotenv file each process reads, and every variable production requires | [02-configuration.md](../docs/deployment/02-configuration.md) |
| the full first-install sequence — packages, roles, schema, console build, first OWNER, supervision, TLS | [03-provisioning.md](../docs/deployment/03-provisioning.md) |
| the routine deploy, restart order, verification, rollback | [04-release.md](../docs/deployment/04-release.md) |
| operator accounts, cron jobs, logs, backup/restore | [05-operations.md](../docs/deployment/05-operations.md) |
| a symptom you are looking at right now | [06-troubleshooting.md](../docs/deployment/06-troubleshooting.md) |
| which security controls depend on the deployment, and how to prove each is on | [07-security.md](../docs/deployment/07-security.md) |

## Why `first-install-proposal.md` is still here

This file used to carry its own install narrative. It has been retired rather than maintained
in parallel: 03 and 04 supersede it, they cite a file and a line for every claim, and they are
explicit about which statements are host facts nobody has checked.

The old text is preserved verbatim, at its original line numbers, as
`first-install-proposal.md`, because `docs/deployment/00`–`07` reference it **35 times, 26 of
those by line number** — several of them specifically to show where it is wrong (its `grep host_verified` matches
nothing; its `.venv/bin/uv` cannot exist from its own instructions; its migration step exports
too little for migration 0007's `REVOKE` to land). Deleting it would have turned every one of
those citations into a dead reference. It is a citation target and a historical record. Do not
follow it.
