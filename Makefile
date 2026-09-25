# Bayram — Tabriklar, Qoʻshiqlar. Developer entry points.
# `make test`, `make lint` and `make typecheck` need no Docker, no keys and no network.
#
# THE GATES, AND WHICH ONE COVERS WHAT. `make check` is the Python half only — ruff, mypy
# and the coverage run. It deliberately does NOT run `make ui-check`, the console's own gates
# (tsc, eslint, vitest, the strict localization suite, the production build and the built-shell
# CSP check). Before a release, run both.
#
# THERE IS NO BROWSER GATE. The Playwright suite lived in `admin-ui/`, the legacy console
# removed on 2026-09-16, and it asserted on that console's own bundle and font pipeline — so
# it could not have been pointed at $(UI) without a rewrite, and `make ui-e2e` had already
# been unrunnable for some time (it called `npm run e2e` in $(UI), which declares no such
# script). What went with it is worth naming, because nothing replaced it: jsdom implements no
# CSP, so no remaining check can see a Content-Security-Policy regression in a real browser.
# The POLICY is still covered in Python by `tests/test_admin/test_security_headers.py` and
# `test_spa_nonce.py`; what is not covered is whether the built bundle actually complies with
# it. Restoring that means new specs against $(UI), not resurrecting the old ones.
#
# `ui-check` targets $(UI), the console that is actually deployed. Until 2026-09-10 it ran the
# legacy console's script list against admin-dashboard and therefore FAILED ON A GREEN TREE, at
# `tokens:check`, a script admin-dashboard does not define — and because that line came last the
# target also never reached admin-dashboard's `test:unit`, so its component suite was guarded by
# no target at all. Each package's gate runs that package's own scripts; there is now one package.

PYTHON  := .venv/bin/python
PIP     := uv pip install --python $(PYTHON)
SRC     := src/bayram
# Referenced by `lint` and `format`, and it must stay defined: an undefined TESTS expands to
# nothing, so `make lint` silently narrows to src/bayram and the gate stops covering the suite
# while still reporting success. mypy reads its own `files = ["src","tests"]` out of
# pyproject.toml and is unaffected, which is exactly what makes the gap quiet.
TESTS   := tests
UI      := admin-dashboard

# ENV — WHICH SET OF DOTENV FILES the long-running processes read. Not the same thing as
# BAYRAM_ENVIRONMENT, which is what the code branches on (fake providers refused, DEBUG refused,
# a public origin required). This picks the FILE; that file says which environment it is.
#
#   make dev                 .env          + .env.admin      + .env.payme   (the default)
#   make admin ENV=prod      .env.prod     + .env.admin.prod + .env.payme.prod
#
# THREE variables and not one derived path, and that is deliberate rather than repetitive:
# each process reads a different file BECAUSE each holds a different set of credentials — the
# bot holds four outbound vendor keys, the panel holds none, and the gateway holds one inbound
# verification secret. One knob deriving all three would be one edit away from pointing them at
# the same file, which is the mistake the separate processes exist to make impossible.
#
# `dev` maps to the bare names deliberately: a checkout that has only ever had `.env` keeps
# working with no rename and no flag, and `git status` on this branch stays quiet.
#
# On the VPS none of this is used. systemd sets BAYRAM_ENV_FILE=/etc/bayram/bot.env directly, so
# the secrets live outside the checkout and a stray `.env` left in /srv/bayram cannot be read
# by accident. See deploy/README.md.
ENV ?= dev
ifeq ($(ENV),dev)
ENV_FILES :=
else
ENV_FILES := BAYRAM_ENV_FILE=.env.$(ENV) BAYRAM_ADMIN_ENV_FILE=.env.admin.$(ENV) BAYRAM_PAYME_ENV_FILE=.env.payme.$(ENV)
endif

.DEFAULT_GOAL := help
.PHONY: help install up down dev worker admin admin-bootstrap payme demo gateway-doctor gateway-contract test test-all cov cov-admin lint format typecheck check migrate revision clean ui-install ui ui-build ui-check

# `0-9` stays in the target-name class even though no current target has a digit: it cost
# nothing and the omission has already bitten once, when `ui-e2e` and `ui-e2e-install` were
# invisible here — the two targets nobody was obliged to run were also the two `make help`
# never mentioned.
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install the package with dev extras
	uv venv --python 3.12 .venv
	$(PIP) -e ".[dev]"

up: ## Start Postgres 16 + Redis 7
	docker compose up -d

down: ## Stop them, keeping data
	docker compose down

dev: ## Run the Telegram bot (long polling).  ENV=prod reads .env.prod
	$(ENV_FILES) $(PYTHON) -m bayram.main

worker: ## Run the ARQ worker.  ENV=prod reads .env.prod
	$(ENV_FILES) $(PYTHON) -m arq bayram.worker.WorkerSettings

admin: ## Run the admin API (loopback only; put a TLS proxy in front of it)
	$(ENV_FILES) $(PYTHON) -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080

admin-bootstrap: ## First OWNER, prompting for the password:  make admin-bootstrap u=owner
	@test -n "$(u)" || (echo 'usage: make admin-bootstrap u=<username> [args="--reset-owner"]' \
		&& echo '       the password is never an argument — you are prompted, or use' \
		&& echo '       args="--password-file /path" on a file only you can read' && exit 1)
	$(ENV_FILES) $(PYTHON) -m bayram.admin.bootstrap --username "$(u)" $(args)

# The fourth process. It reads .env.payme — NOT .env and NOT .env.admin — and it is off unless
# that file sets BAYRAM_PAYME_ENABLED=true, so this target is a boot refusal naming the variable
# on a checkout that has not configured it. Loopback only: Payme reaches it through a TLS
# terminator that enforces the caller allowlist, never directly. See docs/deployment/08-payme.md.
payme: ## Run the Payme Merchant API endpoint (loopback only; TLS terminator in front of it)
	$(ENV_FILES) $(PYTHON) -m uvicorn bayram.payme.app:app --host 127.0.0.1 --port 8091

ui-install: ## Install the modern admin dashboard's Node dependencies (admin-dashboard/)
	cd $(UI) && npm install

ui: ## Run the modern admin dashboard dev server on :5174, proxying /api to the API on :8080
	@echo "Needs 'make admin' in another shell, and BAYRAM_ADMIN_PUBLIC_ORIGIN=http://localhost:5174"
	@echo "in .env.admin — the dev proxy forwards the browser's real Origin (changeOrigin: false),"
	@echo "so the API's origin check is live in development too. That is deliberate."
	cd $(UI) && npm run dev

ui-build: ## Build the modern admin dashboard into src/bayram/admin/static/
	cd $(UI) && npm run build

# SIX SCRIPTS, IN THE ORDER THE `node` JOB RUNS THEM, AND NO TWO OF THEM SUBSUME EACH OTHER.
# This list is a copy of `.github/workflows/ci.yml`'s `node` job; when that job gains a step,
# this line gains it too. It ran only the first four until 2026-09-19, which made the repo's
# own local gate STRICTLY WEAKER than CI: a developer ran `make ui-check`, got green, pushed,
# and CI went red on a step the local gate could not reach.
#
# What each one covers that no other does:
#   typecheck          tsc --noEmit over both tsconfigs — types only, emits nothing.
#   lint               eslint.
#   test:unit          vitest over `src/**/*.test.tsx` — the components.
#   test:e2e:strict    the bespoke tsx harness in `tests/run-all.ts`: 100% key parity and
#                      interpolation-token consistency across en/ru/uz. THE STRICT VARIANT,
#                      matching CI. Plain `npm test` is the same harness without `--strict`
#                      and exits 0 with PENDING_IMPLEMENTATION assertions outstanding — so
#                      running it here was a second way to be greener locally than in CI.
#   build              vite build. Nothing above it can fail on a bad import, a plugin that
#                      throws or an asset Rollup cannot resolve; CI never built the SPA at all
#                      until this step existed, and such breaks were found on the host.
#   check:built-shell  reads what vite just EMITTED (`src/bayram/admin/static/index.html`,
#                      .gitignore'd) for code the panel's CSP would refuse. It needs `build`
#                      to have run first and fails rather than skips when it has not. The
#                      Python suite audits the SOURCE shell and structurally cannot see this
#                      one, so an injected inline `<script>` or a dropped
#                      `__BAYRAM_CSP_NONCE__` placeholder is visible here and nowhere else.
#
# The last two are last for CI's reason: they are the newest gates and the likeliest to fail on
# something unrelated to the change under review, so a build break cannot hide a vitest result.
# Unlike CI's separate steps this is an `&&` chain, so the first failure stops the rest.
#
# `tokens:check` is NOT here, and that is now simply because no such script exists: the
# annotator (`tools/annotate-tokens.mts`) and the tokens.css it measured belonged to the legacy
# console, removed on 2026-09-16. admin-dashboard has never declared one. If the contrast
# contract is wanted back it has to be rebuilt against this package's stylesheet.
ui-check: ## The deployed console's CI gates: typecheck, lint, vitest, locales, build, built-shell CSP
	cd $(UI) && npm run typecheck && npm run lint && npm run test:unit \
		&& npm run test:e2e:strict && npm run build && npm run check:built-shell

demo: ## One full kit, offline: no keys, no Redis, no Postgres, no spend
	BAYRAM_USE_FAKE_PROVIDERS=1 $(PYTHON) -m bayram.demo

gateway-doctor: ## Check the local media gateway from here (IMAGE_VIDEO_SPEC §9.1). Network; ENV=prod reads .env.prod
	$(ENV_FILES) $(PYTHON) -m bayram.tools.media doctor

gateway-contract: ## gateway-doctor plus a diff of the live /openapi.json against what we send. Network; never in pytest
	$(ENV_FILES) $(PYTHON) -m bayram.tools.media doctor --contract

test: ## Unit tests only — no network, Redis, Postgres or ffmpeg
	$(PYTHON) -m pytest -m "not integration"

test-all: ## Every test, including those marked integration
	$(PYTHON) -m pytest

cov: ## Unit tests with the 80% coverage gate
	$(PYTHON) -m pytest -m "not integration" --cov --cov-report=term-missing

cov-admin: cov ## Re-report the same run against src/bayram/admin alone, gated at 85%
	$(PYTHON) -m coverage report --include='src/bayram/admin/*' --fail-under=85

lint: ## ruff check
	$(PYTHON) -m ruff check $(SRC) $(TESTS)

format: ## ruff format + autofix
	$(PYTHON) -m ruff format $(SRC) $(TESTS)
	$(PYTHON) -m ruff check --fix $(SRC) $(TESTS)

typecheck: ## mypy --strict
	$(PYTHON) -m mypy

check: lint typecheck cov ## The Python gates. NOT ui-check — see the top of this file

migrate: ## Apply Alembic migrations.  ENV=prod reads .env.prod
	$(ENV_FILES) $(PYTHON) -m alembic -c migrations/alembic.ini upgrade head

revision: ## Autogenerate a migration:  make revision m="add orders"
	@test -n "$(m)" || (echo 'usage: make revision m="describe the change"' && exit 1)
	$(ENV_FILES) $(PYTHON) -m alembic -c migrations/alembic.ini revision --autogenerate -m "$(m)"

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
