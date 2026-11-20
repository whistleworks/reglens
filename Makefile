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

index: ## Embed and index chunks (STRATEGY=paragraph|article|fixed ENRICH=none|hierarchy RECREATE=1)
	uv run python -m reglens.ingestion.cli index --strategy $(or $(STRATEGY),paragraph) \
		--enrich $(or $(ENRICH),none) $(if $(RECREATE),--recreate,)

qdrant: ## Start local Qdrant
	docker compose up -d qdrant

eval: ## Run eval (SPLIT=dev STAGE=retrieval CONFIG=configs/bm25.yaml)
	uv run python -m evals.run_eval --split $(SPLIT) --stage $(STAGE) --config $(CONFIG)

review-sheet: ## Markdown review sheet for a dataset (DATASET=evals/datasets/reglens_v1.jsonl)
	PYTHONPATH=. uv run python scripts/review_sheet.py $(or $(DATASET),evals/datasets/reglens_v1.jsonl)

beir: ## BEIR SciFact BM25 sanity check (MEMORY=1 for in-process Qdrant)
	uv run python -m evals.beir_sanity $(if $(MEMORY),--memory,)

compare: ## Paired comparison of two runs (A=<json> B=<json>)
	uv run python -m evals.compare $(A) $(B)

report: ## Ablation table from runs (RUNS="a.json b.json" OUT=docs/ablation.md)
	uv run python -m evals.report $(RUNS) $(if $(OUT),--out $(OUT),)

serve: ## Run the API + UI on http://localhost:8000 (QDRANT_URL and LLM keys from .env)
	uv run uvicorn reglens.api.main:create_app --factory --host 0.0.0.0 --port $(or $(PORT),8000)

calibrate: ## Judge calibration (LABELS=evals/human_labels/calibration.jsonl RUN=<judged e2e json>)
	uv run python -m evals.calibrate_judge $(or $(LABELS),evals/human_labels/calibration.jsonl) $(RUN)

eval-smoke eval-final demo docker-build docker-run load-test: ## Later milestones
	@echo "'$@' is not implemented yet (see docs/PROJECT_BRIEF.md, section 4)." && exit 1

.PHONY: help setup fmt lint typecheck test test-integration test-data check ingest index qdrant eval \
	beir review-sheet compare report eval-smoke eval-final calibrate serve demo docker-build \
	docker-run load-test
