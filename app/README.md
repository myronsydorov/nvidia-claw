# Custody app

Installable web app (React + Vite + Tailwind). It talks only to the Warden's `/api` (docs/CONTRACTS.md §3). In dev, Vite proxies `/api` to `WARDEN_URL` (default `http://127.0.0.1:8000`).

- `make dev` (repo root): Warden with mock sandboxes and the real compiler (NVIDIA Build if `NVIDIA_API_KEY` is in `.env`, otherwise replayed model answers), plus this app. Open it and paste your `WARDEN_DEVICE_TOKEN` on the Connect screen. The token stays in this browser's localStorage.
- `pnpm dev:mock`: the app on an in-memory mock API (`VITE_API_MODE=mock`), no Warden needed.
- `pnpm test`: Vitest (contract schemas, HTTP client, SSE parser/reconnect, mock API).
- `pnpm e2e`: Playwright smoke test. It starts a real Warden (`CUSTODY_SANDBOX=mock`, the real compiler on replayed model answers via `CUSTODY_LLM_REPLAY`, temp DB) and Vite, then runs hand over → approve → watching at 390×844. The first time, run `pnpm exec playwright install chromium`.

Live updates come from `GET /api/events` over `fetch` (EventSource can't send the bearer header). The stream reconnects with backoff and emits a `connected` signal so screens refetch what they missed.
