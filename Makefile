.DEFAULT_GOAL := help
SHELL := /bin/bash

SPLIT ?= dev
STAGE ?= retrieval
CONFIG ?= configs/bm25.yaml

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies and pre-commit hooks
	uv sync --all-groups
	uv run pre-commit install

fmt: ## Format code
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint
	uv run ruff format --check .
	uv run ruff check .

typecheck: ## mypy --strict on src/
	uv run mypy

test: ## Unit tests (no network, no Qdrant)
	uv run pytest

test-integration: ## Integration tests (needs `docker compose up -d qdrant`)
	uv run pytest -m integration

test-data: ## Tests on the real ingested corpus (needs `make ingest`)
	uv run pytest -m data

check: lint typecheck test ## lint + typecheck + test (mandatory before each commit)

ingest: ## Fetch, parse and chunk the corpus into data/processed/
	uv run python -m reglens.ingestion.cli ingest

index: ## Embed and index the chunks into Qdrant
	uv run python -m reglens.ingestion.cli index

qdrant: ## Start local Qdrant
	docker compose up -d qdrant

eval: ## Run eval (SPLIT=dev STAGE=retrieval CONFIG=configs/bm25.yaml)
	uv run python -m evals.run_eval --split $(SPLIT) --stage $(STAGE) --config $(CONFIG)

beir: ## BEIR SciFact BM25 sanity check
	uv run python -m evals.beir_sanity

eval-smoke eval-final calibrate compare serve demo docker-build docker-run load-test: ## Later milestones
	@echo "'$@' is not implemented yet (see docs/PROJECT_BRIEF.md, section 4)." && exit 1

.PHONY: help setup fmt lint typecheck test test-integration test-data check ingest index qdrant eval beir \
	eval-smoke eval-final calibrate compare serve demo docker-build docker-run load-test
