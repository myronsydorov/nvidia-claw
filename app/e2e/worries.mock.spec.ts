import { expect, test } from "@playwright/test";

// S7 incident (2026-10-02): a worry with no running watcher shows no present-tense check and
// no jail, and a build failure says which phase failed and offers a retry.
test("a parked build shows no check and no jail", async ({ page }) => {
	await page.goto("/");
	await page.getByText("What if the S7 is disrupted around 9:00").click();
	await expect(page.getByText("I couldn't build a watcher")).toBeVisible();
	await expect(page.getByText("What it checks")).toHaveCount(0);
	await expect(page.getByText("Its jail")).toHaveCount(0);
	await expect(page.getByText("cw-bjasgm4b")).toHaveCount(0);
});

test("a failed build names the phase and can be retried", async ({ page }) => {
	await page.goto("/");
	await page.getByText("What if the U5 is late tonight?").click();
	await expect(
		page
			.getByText(
				"Testing the watcher failed: the check could not get its data.",
			)
			.first(),
	).toBeVisible();
	await expect(page.getByText("Its jail")).toHaveCount(0);
	await page.getByRole("button", { name: "Try again" }).click();
	await expect(page.getByText("Waiting for your OK")).toBeVisible();
	await expect(page.getByText("What it would check")).toBeVisible();
	await page.screenshot({ path: "e2e/results/retry-light.png" });
});
