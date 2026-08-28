# HBD Bot — developer entry points.
# `make test`, `make lint` and `make typecheck` need no Docker, no keys and no network.

PYTHON  := .venv/bin/python
PIP     := uv pip install --python $(PYTHON)
SRC     := src/hbd
TESTS   := tests

.DEFAULT_GOAL := help
.PHONY: help install up down dev worker demo test test-all cov lint format typecheck check migrate revision clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

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

demo: ## One full kit, offline: no keys, no Redis, no Postgres, no spend
	HBD_USE_FAKE_PROVIDERS=1 $(PYTHON) -m hbd.demo

test: ## Unit tests only — no network, Redis, Postgres or ffmpeg
	$(PYTHON) -m pytest -m "not integration"

test-all: ## Every test, including those marked integration
	$(PYTHON) -m pytest

cov: ## Unit tests with the 80% coverage gate
	$(PYTHON) -m pytest -m "not integration" --cov --cov-report=term-missing

lint: ## ruff check
	$(PYTHON) -m ruff check $(SRC) $(TESTS)

format: ## ruff format + autofix
	$(PYTHON) -m ruff format $(SRC) $(TESTS)
	$(PYTHON) -m ruff check --fix $(SRC) $(TESTS)

typecheck: ## mypy --strict
	$(PYTHON) -m mypy

check: lint typecheck cov ## Everything CI runs

migrate: ## Apply Alembic migrations
	$(PYTHON) -m alembic -c migrations/alembic.ini upgrade head

revision: ## Autogenerate a migration:  make revision m="add orders"
	@test -n "$(m)" || (echo 'usage: make revision m="describe the change"' && exit 1)
	$(PYTHON) -m alembic -c migrations/alembic.ini revision --autogenerate -m "$(m)"

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
