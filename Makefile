# Bayram — Tabriklar, Qoʻshiqlar. Developer entry points.
# `make test`, `make lint` and `make typecheck` need no Docker, no keys and no network.
#
# THE GATES, AND WHICH ONE COVERS WHAT. `make check` is the Python half only — ruff, mypy
# and the coverage run. It deliberately does NOT run:
#
#   * `make ui-check`, the console's own gates (tsc, eslint, vitest and the localization suite)
#   * `make ui-e2e`, the browser gate, which is the ONLY check that can see a
#     Content-Security-Policy regression at all — jsdom implements no CSP
#
# EACH UI PACKAGE'S GATE RUNS THAT PACKAGE'S OWN SCRIPTS, and the two packages do not have the
# same ones. `ui-check` targets $(UI) — the console that is actually deployed — and
# `legacy-ui-check` targets $(LEGACY_UI), which is where `tokens:check` and the Playwright
# specs live. Until 2026-09-10 `ui-check` ran admin-ui's script list against admin-dashboard
# and therefore FAILED ON A GREEN TREE, at `tokens:check`, a script admin-dashboard does not
# define — and because that line came last the target also never reached admin-dashboard's
# `test:unit`, so its component suite was guarded by no target at all.
#
# `ui-e2e` is out of `check` because it needs a ~150 MB Chromium (`make ui-e2e-install`), and
# a first `make check` on a new machine must not silently start that download. The
# consequence is that the CSP and the SPA nonce are guarded by a gate nobody is obliged to
# run: before a release, run `make check`, `make ui-check` and `make ui-e2e`. See the
# "Checks" section of README.md, which lists the same split.

PYTHON  := .venv/bin/python
PIP     := uv pip install --python $(PYTHON)
SRC     := src/bayram
# Referenced by `lint` and `format`, and it must stay defined: an undefined TESTS expands to
# nothing, so `make lint` silently narrows to src/bayram and the gate stops covering the suite
# while still reporting success. mypy reads its own `files = ["src","tests"]` out of
# pyproject.toml and is unaffected, which is exactly what makes the gap quiet.
TESTS   := tests
UI      := admin-dashboard
LEGACY_UI := admin-ui

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
.PHONY: help install up down dev worker admin admin-bootstrap payme demo test test-all cov cov-admin lint format typecheck check migrate revision clean ui-install ui ui-build ui-check legacy-ui legacy-ui-build legacy-ui-check ui-e2e ui-e2e-install

# `0-9` is in the target-name class because `ui-e2e` and `ui-e2e-install` have a digit in
# their names and were invisible here: the two targets nobody was obliged to run were also
# the two `make help` did not mention.
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

legacy-ui: ## [DEPRECATED] Run the legacy Gogo console on :5173
	cd $(LEGACY_UI) && npm run dev

legacy-ui-build: ## [DEPRECATED] Build the legacy Gogo console
	cd $(LEGACY_UI) && npm run build

# FOUR SCRIPTS, AND NEITHER RUNNER SUBSUMES THE OTHER. admin-dashboard splits its suites:
# `test:unit` is vitest over `src/**/*.test.tsx` (the components), and `test` is the bespoke
# tsx harness in `tests/run-all.ts` that asserts 100% key parity and interpolation-token
# consistency across en/ru/uz. Running only one leaves the other guarded by nobody — which is
# exactly what this target used to do.
#
# `tokens:check` is NOT here and its absence is the fix rather than an omission: the annotator
# it runs (`tools/annotate-tokens.mts`) and the stylesheet it measures both live in
# $(LEGACY_UI), and admin-dashboard declares no such script. It is on `legacy-ui-check`, with
# its own argument, below.
ui-check: ## The deployed console's gates: typecheck, lint, vitest and the localization suite
	cd $(UI) && npm run typecheck && npm run lint && npm run test:unit && npm test

# The contrast contract is checked TWICE on purpose, in the package that has it. `vitest`
# recomputes every annotation in admin-ui's tokens.css and fails on drift; `tokens:check`
# additionally verifies the annotation FORM against each token's bar and runs the wider
# `{6,8}` must-annotate scan. Neither subsumes the other, and `tokens:check` is reachable only
# by typing it or by running this target.
#
# The zero-tests hazard, written down because it is deliberate and therefore easy to
# misread: a malformed selector in tokens.css takes `tokenContrast.test.ts` to ZERO tests by
# design — `blockRange()` throws at module load rather than measuring a plausible-but-wrong
# block — and `vitest run` reports a file that contributed no tests as a pass. `tokens:check`
# parses the same stylesheet through the same module and exits 1, which is what makes that
# loud failure actually loud from this target.
legacy-ui-check: ## [DEPRECATED] The legacy console's gates, including the tokens.css annotations
	cd $(LEGACY_UI) && npm run typecheck && npm run lint && npm test && npm run tokens:check

# KNOWN BROKEN FOR $(UI), AND NOT FIXED HERE BECAUSE THE FIX IS NOT A MAKEFILE EDIT. Both of
# these run `npm run e2e*` in $(UI), and admin-dashboard declares neither script: the
# Playwright config, the `e2e/` specs and the CSP assertions all live in $(LEGACY_UI), and
# some of those specs (`font-coverage.spec.ts`) assert on admin-ui's own font pipeline. So
# re-pointing them at $(LEGACY_UI) would run the legacy console's specs against the deployed
# console's bundle, which is a different claim and an unverified one. Until somebody ports
# `e2e/csp.ts` and `e2e/smoke.spec.ts` into $(UI), the CSP and the SPA nonce are guarded by
# nothing, and the note at the top of this file overstates the cover `ui-e2e` provides.
ui-e2e-install: ## Download the Chromium build Playwright drives (once per machine)
	cd $(UI) && npm run e2e:install

ui-e2e: ui-build ## The browser gate: the built console against the real admin API, under the production CSP
	@echo "No Postgres, Redis, network, vendor key or ffmpeg: the harness"
	@echo "(tests/e2e/serve_admin_e2e.py) runs the real admin app over in-memory SQLite and"
	@echo "a dictionary Redis, and Playwright starts and stops it. Needs 'make ui-e2e-install'"
	@echo "once. It builds the bundle first, because the gate serves the BUILT console."
	cd $(UI) && npm run e2e

demo: ## One full kit, offline: no keys, no Redis, no Postgres, no spend
	BAYRAM_USE_FAKE_PROVIDERS=1 $(PYTHON) -m bayram.demo

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

check: lint typecheck cov ## The Python gates. NOT ui-check, and NOT ui-e2e — see the top of this file

migrate: ## Apply Alembic migrations.  ENV=prod reads .env.prod
	$(ENV_FILES) $(PYTHON) -m alembic -c migrations/alembic.ini upgrade head

revision: ## Autogenerate a migration:  make revision m="add orders"
	@test -n "$(m)" || (echo 'usage: make revision m="describe the change"' && exit 1)
	$(ENV_FILES) $(PYTHON) -m alembic -c migrations/alembic.ini revision --autogenerate -m "$(m)"

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
