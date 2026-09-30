import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { APP_PORT, E2E_TOKEN, WARDEN_PORT } from "./e2e/env.ts";

// T-12 smoke test: the real app against a real local Warden with mock
// sandboxes and the mock compiler stage. A fresh SQLite file per run.

const dbPath = join(mkdtempSync(join(tmpdir(), "custody-e2e-")), "warden.db");

export default defineConfig({
	testDir: "e2e",
	timeout: 30_000,
	retries: 0,
	reporter: "list",
	use: {
		...devices["iPhone 14"],
		browserName: "chromium",
		viewport: { width: 390, height: 844 },
		baseURL: `http://127.0.0.1:${APP_PORT}`,
		trace: "retain-on-failure",
	},
	webServer: [
		{
			command: `uv run --package warden uvicorn warden.app:app --host 127.0.0.1 --port ${WARDEN_PORT}`,
			cwd: "..",
			url: `http://127.0.0.1:${WARDEN_PORT}/api/health`, // 401 counts as up
			env: {
				CUSTODY_SANDBOX: "mock",
				CUSTODY_COMPILER: "mock",
				CUSTODY_MOCK_COMPILE_S: "0.3",
				WARDEN_DEVICE_TOKEN: E2E_TOKEN,
				WARDEN_DB_PATH: dbPath,
			},
			reuseExistingServer: false,
			timeout: 60_000,
		},
		{
			command: `pnpm exec vite --host 127.0.0.1 --port ${APP_PORT} --strictPort`,
			url: `http://127.0.0.1:${APP_PORT}`,
			env: { WARDEN_URL: `http://127.0.0.1:${WARDEN_PORT}` },
			reuseExistingServer: false,
			timeout: 60_000,
		},
	],
});
