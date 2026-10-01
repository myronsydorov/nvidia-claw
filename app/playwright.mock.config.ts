import { defineConfig, devices } from "@playwright/test";
import { MOCK_APP_PORT } from "./e2e/env.ts";

// T-17 smoke tests on the in-memory mock API (VITE_API_MODE=mock): no Warden.
// Layer 2 needs a second paired Warden (T-14/T-16), so mock mode is how the
// People, sharing and Ledger screens are exercised end to end today.

export default defineConfig({
	testDir: "e2e",
	testMatch: "*.mock.spec.ts",
	timeout: 30_000,
	retries: 0,
	reporter: "list",
	use: {
		...devices["iPhone 14"],
		browserName: "chromium",
		viewport: { width: 390, height: 844 },
		baseURL: `http://127.0.0.1:${MOCK_APP_PORT}`,
		trace: "retain-on-failure",
		// Screenshots show the settled screen, not the 700 ms rise mid-fade.
		contextOptions: { reducedMotion: "reduce" },
	},
	webServer: {
		command: `pnpm exec vite --host 127.0.0.1 --port ${MOCK_APP_PORT} --strictPort`,
		url: `http://127.0.0.1:${MOCK_APP_PORT}`,
		env: { VITE_API_MODE: "mock" },
		reuseExistingServer: false,
		timeout: 60_000,
	},
});
