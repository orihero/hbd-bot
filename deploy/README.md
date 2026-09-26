# `deploy/` — the artefacts

This directory holds the deployment **artefacts**. The prose that explains them lives in
[`docs/deployment/`](../docs/deployment/README.md); start there.

```
deploy/systemd/bayram-bot.service      the Telegram bot — aiogram long polling
deploy/systemd/bayram-worker.service   the ARQ worker — every render, every cron job
deploy/systemd/bayram-admin.service    the admin API — FastAPI, serving its own React bundle
deploy/systemd/bayram-payme.service    the Payme Merchant API endpoint — the settlement rail
```

The other things that get *installed* rather than run:

```
deploy/sudoers.d/bayram-release        the grant for the release script, five fixed commands
deploy/sudoers.d/bayram-deploy         the post-cutover grant, replacing /etc/sudoers.d/hbd-deploy
deploy/caddy/*.caddy                   two vhost blocks, appended to /etc/caddy/Caddyfile
deploy/fix-table-ownership.sql         psql, by hand — `-f`, as root; read its header first
```

```
deploy/payme-open-orders.py           opens N *pending* payment intents for a Payme sandbox slot
deploy/first-install-proposal.md      retired; a citation target only — see below
deploy/deploy-{d17,payme,support}.sh  retired 2026-09-19; citation targets only — see below
```

The four unit files are meant to be copied onto a machine. Read the comments in them: each
unit argues for its own hardening lines, and `bayram-admin.service` carries the
`InaccessiblePaths=` that enforces the vendor-key separation at the kernel level rather than
only in the application. Note what `cutover-to-bayram.sh` says about them: the units it wrote
on `abdu-test` say `User=hbd`, `/opt/bayram` and `/var/lib/hbd`, whereas these four say
`User=bayram` and `/srv/bayram` — **a path that has never existed on that host**. On
`abdu-test` the running units are the cutover's, not these.

The two `deploy/caddy/*.caddy` blocks are pasted into `/etc/caddy/Caddyfile` (a single file
with no `import`, so there is no sites directory to drop them into). Caddy is not the outer
edge: public traffic arrives over a **Cloudflare Tunnel** that speaks plain HTTP to
`127.0.0.1:80`, and Caddy is what sits between that and the loopback processes. See
[`08-payme.md`](../docs/deployment/08-payme.md) §4 for the whole chain.

## The scripts an operator runs

Every one of these runs **on the host, as root**. None is shipped by the wheel and none is run
by CI: `release.yml` builds and stages a bundle, and a human on `abdu-test` does the rest
(see [`11-ci-cd.md`](../docs/deployment/11-ci-cd.md)). Read each script's own header before
running it — the commands below are copied from those headers, not invented here.

| Artefact | What it is, and how it is run |
| --- | --- |
| `deploy/bayram-release` | **The release script** — the consumer half of operator-triggered CD, replacing the three retired `deploy-*.sh`. Installed **by hand** at `/opt/bayram/sbin/bayram-release` (`0755 root:root`); it is **not** shipped by the wheel bundle, so editing this file changes nothing on the host until it is copied up. `sudo /opt/bayram/sbin/bayram-release plan` is a dry run; `deploy`, `verify`, `rollback` and `backup` are the other verbs. It takes **no path argument** by design. Live on the host since 2026-09-17. |
| `deploy/install-bayram-backup.sh` | **A BASH INSTALLER. IT IS NOT A SYSTEMD UNIT** — its own header opens with that line, because the name it used to carry (`bayram-backup.timer`) invited an `scp` into `/etc/systemd/system/`, where it would be a silent no-op. Install it by running it: `scp deploy/install-bayram-backup.sh aizu:/tmp/install-bayram-backup.sh` then `ssh -t aizu 'sudo bash /tmp/install-bayram-backup.sh'`, **in the same breath** — `/tmp` is world-writable and a staged copy is a window in which something else chooses what root executes. **It has never been run on the host, so there is still no scheduled backup of anything of ours.** Re-verified read-only 2026-09-19: no `bayram-backup` unit, nothing in `systemctl list-timers`, and `/opt/bayram/sbin` holds `bayram-release` alone. The nightly `aizu-backup.timer` you will see in `list-timers` belongs to a **different tenant** and backs up somebody else's SQLite file. |
| `deploy/set-probe-tokens.sh` | Generates and installs the two `/readyz` probe tokens, rewrites each env file atomically preserving its existing owner and mode, then **restarts `bayram-admin` and `bayram-payme` and proves the tokens took** by reading the gated body back. `scp deploy/set-probe-tokens.sh aizu:/tmp/set-probe-tokens.sh` then `ssh -t aizu 'sudo bash /tmp/set-probe-tokens.sh'`. The restart is a **live-service action** — `bayram-payme` is the settlement rail; `--admin-only` leaves it alone. Also `--rotate`, `--yes`. |
| `deploy/prune-stale-sudo-grants.sh` | Removes the sudo grants nothing needs any more, and — on its own flag — the blanket passwordless-root rule that makes every other grant cosmetic. It reads the policy out of `deploy/sudoers.d/` rather than carrying a second copy of it, so **both files travel — and neither may be run out of `/tmp`.** The script refuses to read itself or the drop-in from any path that is not root-owned and unwritable by group and other, **every directory up to `/` included**; `/tmp` is `1777` and an `scp` lands the files `developer:developer`, so `sudo bash /tmp/prune-stale-sudo-grants.sh` stops with a refusal and changes nothing. Stage, then **re-stage as root**, which is steps 1–4 of this script's own header: `scp -r deploy/prune-stale-sudo-grants.sh deploy/sudoers.d aizu:/tmp/` and note `shasum -a 256` of both on your workstation; then `ssh -t aizu 'sudo install -d -m 0755 -o root -g root /opt/bayram/stage /opt/bayram/stage/sudoers.d && sudo install -m 0644 -o root -g root /tmp/prune-stale-sudo-grants.sh /opt/bayram/stage/ && sudo install -m 0644 -o root -g root /tmp/sudoers.d/bayram-deploy /opt/bayram/stage/sudoers.d/'`; **compare those two digests with the ones the script prints** — that comparison is what closes the `/tmp` window, and it is the operator's job, not the script's. Only then `ssh -t aizu 'sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh plan'` — `plan` is the default and **writes nothing**; `apply` is the only verb that writes, and `apply --drop-blanket` is the one that removes `/etc/sudoers.d/90-developer-nopasswd`. Finish with `ssh aizu 'rm -rf /tmp/prune-stale-sudo-grants.sh /tmp/sudoers.d'` so nobody finds a stale copy and trusts it. If `/opt/bayram` turns out not to be root-owned the script names it and stops; `/root/stage` is root-owned `0700` by definition and the rest of the recipe is unchanged. **Keep a second root shell open on the host for the whole operation**: a malformed sudoers file breaks `sudo` for every account and this host has no root ssh login to recover through. |
| `deploy/cutover-to-bayram.sh` | The one-shot `hbd` → `bayram` rename: `sudo bash /opt/hbd/cutover-to-bayram.sh`. **Already done** — `abdu-test` runs `bayram-{bot,worker,admin,payme}.service` and no `hbd-*` unit survives (verified read-only 2026-09-19). It is kept as the **rollback reference** (the old units were disabled, never deleted) and as the record of which paths and accounts did *not* move. A release today is an ordinary wheel upgrade through `bayram-release`, never this. |

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

**This section is about the unit files and that layout — not about the scripts above.** Those
were written against a host somebody had read-only access to, and each states which of its
claims are host facts and when they were last checked. `abdu-test` does run systemd, and the
four `bayram-*` services are `active` there (verified read-only 2026-09-19).

Before copying them anywhere, fill in
[`docs/deployment/00-host-inventory.md`](../docs/deployment/00-host-inventory.md) and compare.
Where a filled-in row there disagrees with a line here, **the row is right** — correct the
unit file rather than reconciling the two. That document also lists the places where this
proposal is already known to be wrong.

## Where the explanations went

The table covers 01 through 11. [`00-host-inventory.md`](../docs/deployment/00-host-inventory.md)
is the one named above instead, because it is the only document in that tree that describes
*this* machine rather than a shape. **Rows 08 through 11 were added on 2026-09-19**: until then
this table stopped at 07, and the four pages that carry the Payme rail, the go-live gates, the
rename and CI were reachable from here only where the prose above happens to name one — 08
twice and 11 once, 09 and 10 nowhere at all — so a releaser arriving here was routed past the
release procedure (08 §11) the rest of the tree sends them to.

| You want | Read |
| --- | --- |
| what the three processes are and why they are three | [01-architecture.md](../docs/deployment/01-architecture.md) |
| which dotenv file each process reads, and every variable production requires | [02-configuration.md](../docs/deployment/02-configuration.md) |
| the full first-install sequence — packages, roles, schema, console build, first OWNER, supervision, TLS | [03-provisioning.md](../docs/deployment/03-provisioning.md) |
| the routine deploy, restart order, verification, rollback | [04-release.md](../docs/deployment/04-release.md) |
| operator accounts, cron jobs, logs, backup/restore | [05-operations.md](../docs/deployment/05-operations.md) |
| a symptom you are looking at right now | [06-troubleshooting.md](../docs/deployment/06-troubleshooting.md) |
| which security controls depend on the deployment, and how to prove each is on | [07-security.md](../docs/deployment/07-security.md) |
| the fourth process end to end — the gateway's unit, its public path, its certification, refund, rotation and reconciliation runbooks, and the wheel release the whole tree cites (§11; §11.4 for the order, which is not the obvious one) | [08-payme.md](../docs/deployment/08-payme.md) |
| what is still in the way of taking real money, gate by gate, and who each gate is waiting on | [09-payme-go-live.md](../docs/deployment/09-payme-go-live.md) |
| what the `hbd` → `bayram` cutover moved on 2026-09-14, what it deliberately left where it was, and what moves silently whenever anything is renamed | [10-rename-cutover.md](../docs/deployment/10-rename-cutover.md) |
| what CI checks on every push, and why deploying is still one command a human types on the host rather than something a merge does | [11-ci-cd.md](../docs/deployment/11-ci-cd.md) |

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
