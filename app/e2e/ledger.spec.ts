import { expect, test } from "@playwright/test";
import { E2E_TOKEN, WARDEN_PORT } from "./env.ts";

// T-17: the Ledger shows exactly what the real Warden's GET /api/ledger says.

test("ledger numbers match /api/ledger; people starts empty", async ({
	page,
	request,
}) => {
	await page.emulateMedia({ reducedMotion: "reduce" }); // settled screenshot
	await page.goto("/");
	await page.getByLabel("Device token").fill(E2E_TOKEN);
	await page.getByRole("button", { name: "Connect" }).click();

	await page.getByRole("link", { name: "Ledger" }).click();
	const res = await request.get(`http://127.0.0.1:${WARDEN_PORT}/api/ledger`, {
		headers: { Authorization: `Bearer ${E2E_TOKEN}` },
	});
	const l = await res.json();
	const field = (f: string) => page.locator(`[data-field="${f}"]`);
	for (const f of [
		"worries_total",
		"active",
		"never_needed_you",
		"needed_you",
		"watchers_built",
		"sandboxes_live",
		"peer_questions_answered",
		"locations_shared",
	]) {
		await expect(field(f)).toHaveText(String(l[f]));
	}
	// Not measured yet (CONTRACTS §5): shown as "—", never as a real-looking 0.
	await expect(field("endpoints_denied")).toHaveText("—");
	if (l.needed_you + l.never_needed_you === 0) {
		// No outcome known yet: no came-true claim, no 91.4% comparison.
		await expect(
			page.getByText("No outcomes yet.", { exact: false }),
		).toBeVisible();
		await expect(page.getByText("Penn State study")).toHaveCount(0);
	}
	await page.screenshot({ path: "e2e/results/ledger-real-warden.png" });

	await page.getByRole("link", { name: "Home" }).click();
	await page.getByRole("link", { name: "People" }).click();
	await expect(page.getByText("No one is paired yet.")).toBeVisible();
});
