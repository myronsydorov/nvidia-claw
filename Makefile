SHELL := /bin/bash

.PHONY: setup dev lint typecheck test e2e spike

setup:
	uv sync --all-packages
	pnpm -C app install

dev:
	@trap 'kill 0' EXIT; \
	CUSTODY_SANDBOX=mock CUSTODY_COMPILER=mock uv run --package warden uvicorn warden.app:app --reload --port 8000 & \
	pnpm -C app dev & \
	wait

lint:
	uv run ruff check .
	pnpm -C app lint

typecheck:
	uv run mypy warden
	pnpm -C app typecheck

test:
	uv run pytest -q
	pnpm -C app test

e2e:
	pnpm -C app e2e

spike:
	@echo "T-04 spike stub: openshell sandbox create -> policy set --wait -> exec run.py -> delete."
	@echo "Not implemented yet — needs a NemoClaw host. See docs/adr/0001-sandbox-per-watcher.md."
