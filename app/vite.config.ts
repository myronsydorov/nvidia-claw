import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
	plugins: [react(), tailwindcss()],
	server: {
		// Same-origin /api in dev: the app only ever talks to the Warden's /api.
		proxy: {
			"/api": process.env.WARDEN_URL ?? "http://127.0.0.1:8000",
		},
	},
	test: {
		environment: "node",
		exclude: [...configDefaults.exclude, "e2e/**"],
	},
});
