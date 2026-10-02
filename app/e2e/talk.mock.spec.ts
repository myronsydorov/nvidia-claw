import { expect, test } from "@playwright/test";

// Talk to Custody (CONTRACTS §3 /api/talk), the daily close on Home (§6) and the silence line
// on the Ledger (§5), on the in-memory mock API.
test("talk: a question gets the brain's answer as plain text; a link is sent to Hand over", async ({
	page,
}) => {
	await page.goto("/");
	await expect(page.getByTestId("daily-close")).toContainText("38 checks ran");
	await page.getByRole("link", { name: "Talk" }).click();
	await expect(
		page.getByRole("heading", { name: "Talk to Custody" }),
	).toBeVisible();
	await page
		.getByRole("button", {
			name: "What are you watching, and why is it quiet?",
		})
		.click();
	await expect(page.locator('[data-who="custody"]')).toContainText(
		"I'm watching 3 worries",
	);
	await page
		.getByLabel("Say something to Custody")
		.fill("watch example.com/page");
	await page.getByRole("button", { name: "Send" }).click();
	await expect(page.locator('[data-who="note"]')).toContainText(
		"go through Hand over",
	);
	await page.screenshot({ path: "e2e/results/talk.png" });
});

test("ledger: checks and interruptions in one line", async ({ page }) => {
	await page.goto("/#/ledger");
	await expect(page.getByTestId("silence-line")).toHaveText(
		"214 checks, 2 interruptions",
	);
	await page.screenshot({
		path: "e2e/results/ledger-silence.png",
		fullPage: true,
	});
});
