# HBD Bot — developer entry points.
# `make test`, `make lint` and `make typecheck` need no Docker, no keys and no network.
#
# THE GATES, AND WHICH ONE COVERS WHAT. `make check` is the Python half only — ruff, mypy
# and the coverage run. It deliberately does NOT run:
#
#   * the console's own gates (`cd admin-ui && npx tsc --noEmit && npx eslint . && npx vitest run`)
#   * `make ui-e2e`, the browser gate, which is the ONLY check that can see a
#     Content-Security-Policy regression at all — jsdom implements no CSP
#
# `ui-e2e` is out of `check` because it needs a ~150 MB Chromium (`make ui-e2e-install`), and
# a first `make check` on a new machine must not silently start that download. The
# consequence is that the CSP and the SPA nonce are guarded by a gate nobody is obliged to
# run: before a release, run `make check`, the console's three, and `make ui-e2e`. See the
# "Checks" section of README.md, which lists the same split.

PYTHON  := .venv/bin/python
PIP     := uv pip install --python $(PYTHON)
SRC     := src/hbd
TESTS   := tests
UI      := admin-ui

.DEFAULT_GOAL := help
.PHONY: help install up down dev worker admin admin-bootstrap demo test test-all cov cov-admin lint format typecheck check migrate revision clean ui-install ui ui-build ui-e2e ui-e2e-install

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

dev: ## Run the Telegram bot (long polling)
	$(PYTHON) -m hbd.main

worker: ## Run the ARQ worker
	$(PYTHON) -m arq hbd.worker.WorkerSettings

admin: ## Run the admin API (loopback only; put a TLS proxy in front of it)
	$(PYTHON) -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080

admin-bootstrap: ## First OWNER, prompting for the password:  make admin-bootstrap u=owner
	@test -n "$(u)" || (echo 'usage: make admin-bootstrap u=<username> [args="--reset-owner"]' \
		&& echo '       the password is never an argument — you are prompted, or use' \
		&& echo '       args="--password-file /path" on a file only you can read' && exit 1)
	$(PYTHON) -m hbd.admin.bootstrap --username "$(u)" $(args)

ui-install: ## Install the admin console's Node dependencies (admin-ui/ is the only Node in the tree)
	cd $(UI) && npm install

ui: ## Run the console's dev server on :5173, proxying /api to the API on :8080
	@echo "Needs 'make admin' in another shell, and HBD_ADMIN_PUBLIC_ORIGIN=http://localhost:5173"
	@echo "in .env.admin — the dev proxy forwards the browser's real Origin (changeOrigin: false),"
	@echo "so the API's origin check is live in development too. That is deliberate."
	cd $(UI) && npm run dev

ui-build: ## Build the console into src/hbd/admin/static/, which the API serves and the wheel ships
	cd $(UI) && npm run build

ui-e2e-install: ## Download the Chromium build Playwright drives (once per machine)
	cd $(UI) && npm run e2e:install

ui-e2e: ui-build ## The browser gate: the built console against the real admin API, under the production CSP
	@echo "No Postgres, Redis, network, vendor key or ffmpeg: the harness"
	@echo "(tests/e2e/serve_admin_e2e.py) runs the real admin app over in-memory SQLite and"
	@echo "a dictionary Redis, and Playwright starts and stops it. Needs 'make ui-e2e-install'"
	@echo "once. It builds the bundle first, because the gate serves the BUILT console."
	cd $(UI) && npm run e2e

demo: ## One full kit, offline: no keys, no Redis, no Postgres, no spend
	HBD_USE_FAKE_PROVIDERS=1 $(PYTHON) -m hbd.demo

test: ## Unit tests only — no network, Redis, Postgres or ffmpeg
	$(PYTHON) -m pytest -m "not integration"

test-all: ## Every test, including those marked integration
	$(PYTHON) -m pytest

cov: ## Unit tests with the 80% coverage gate
	$(PYTHON) -m pytest -m "not integration" --cov --cov-report=term-missing

cov-admin: cov ## Re-report the same run against src/hbd/admin alone, gated at 85%
	$(PYTHON) -m coverage report --include='src/hbd/admin/*' --fail-under=85

lint: ## ruff check
	$(PYTHON) -m ruff check $(SRC) $(TESTS)

format: ## ruff format + autofix
	$(PYTHON) -m ruff format $(SRC) $(TESTS)
	$(PYTHON) -m ruff check --fix $(SRC) $(TESTS)

typecheck: ## mypy --strict
	$(PYTHON) -m mypy

check: lint typecheck cov ## The Python gates. NOT the console's, and NOT ui-e2e — see the top of this file

migrate: ## Apply Alembic migrations
	$(PYTHON) -m alembic -c migrations/alembic.ini upgrade head

revision: ## Autogenerate a migration:  make revision m="add orders"
	@test -n "$(m)" || (echo 'usage: make revision m="describe the change"' && exit 1)
	$(PYTHON) -m alembic -c migrations/alembic.ini revision --autogenerate -m "$(m)"

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
