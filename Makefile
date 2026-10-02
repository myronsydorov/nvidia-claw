SHELL := /bin/bash

.PHONY: setup dev relay lint typecheck test e2e eval-compiler spike watcher-image

setup:
	uv sync --all-packages
	pnpm -C app install

# Without NVIDIA_API_KEY in .env, the compiler replays recorded model answers (mock sandboxes only).
WARDEN_PORT ?= 8000
APP_PORT ?= 5173

dev:
	@scripts/dev-env.sh
	@trap 'kill 0' EXIT; \
	set -a; . ./.env; set +a; \
	if [ -z "$$NVIDIA_API_KEY" ]; then \
		echo "NVIDIA_API_KEY not set: replaying recorded model answers"; \
		export CUSTODY_LLM_REPLAY=warden/tests/fixtures/llm/replay.json; \
	fi; \
	CUSTODY_SANDBOX=mock uv run --package warden uvicorn warden.app:app --reload \
		--host 127.0.0.1 --port $(WARDEN_PORT) & \
	WARDEN_URL=http://127.0.0.1:$(WARDEN_PORT) pnpm -C app dev --host 127.0.0.1 \
		--port $(APP_PORT) --strictPort & \
	wait

# The L2 relay mailbox (ciphertext only). Point each Warden's RELAY_URL at it.
relay:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	uv run --package relay uvicorn relay.app:app --host 127.0.0.1 --port 8100

lint:
	uv run ruff check .
	pnpm -C app lint

typecheck:
	uv run mypy warden relay
	pnpm -C app typecheck

test:
	uv run pytest -q
	pnpm -C app test

e2e:
	pnpm -C app e2e

# Opt-in, live: 10 labelled worries against NVIDIA Build (needs NVIDIA_API_KEY in .env).
# ARGS=--record saves the model answers as test fixtures; ARGS="--only parcel" runs one case.
eval-compiler:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	CUSTODY_SANDBOX=mock uv run --package warden python warden/evals/run_compiler_eval.py $(ARGS)

# Live, needs an OpenShell host: build the watcher image, then create -> policy -> exec -> deny -> delete.
spike:
	scripts/build-watcher-image.sh
	uv run --package warden python scripts/spike_sandbox.py

watcher-image:
	scripts/build-watcher-image.sh
