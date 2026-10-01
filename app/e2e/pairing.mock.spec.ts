import { expect, type Page, test } from "@playwright/test";

// MOCK_FINGERPRINT in src/mocks/people.ts (copied: e2e/ can't import app code).
const FINGERPRINT = "4821 0937";

async function shot(page: Page, name: string, scheme: string) {
	await page.screenshot({ path: `e2e/results/${name}-${scheme}.png` });
}

for (const scheme of ["dark", "light"] as const) {
	test.describe(`${scheme} mode`, () => {
		test.use({ colorScheme: scheme });

		test("show a code → the other phone joins → compare fingerprints", async ({
			page,
		}) => {
			await page.goto("/#/people");
			await page.getByRole("link", { name: "Show a code" }).click();
			await page.getByLabel("What do you call them?").fill("Mia");
			await page.getByRole("button", { name: "Show a code" }).click();

			await expect(page.getByTestId("pairing-code")).toHaveText("K7M2 Q9XA");
			await expect(page.getByText("Waiting for Mia…")).toBeVisible();
			await shot(page, "pair-code", scheme);

			// The mock's other phone joins after ~2.5 s.
			await expect(page.getByText("Paired with Mia.")).toBeVisible({
				timeout: 10_000,
			});
			await expect(
				page.getByText("Check that Mia's screen shows the same number:"),
			).toBeVisible();
			await expect(page.getByTestId("fingerprint")).toHaveText(FINGERPRINT);
			await shot(page, "pair-fingerprint", scheme);

			await page.getByRole("button", { name: "It matches" }).click();
			await expect(
				page.getByRole("heading", { name: "Mia", exact: true }),
			).toBeVisible();
		});

		test("enter a code → fingerprint; a mismatch undoes the pairing", async ({
			page,
		}) => {
			await page.goto("/#/pair/enter");
			await page.getByLabel("What do you call them?").fill("Mia");
			await page.getByLabel("Their code").fill("k7m2 q9xa");
			await page.getByRole("button", { name: "Pair" }).click();
			await expect(page.getByText(/this phone's own code/)).toBeVisible();

			await page.getByLabel("Their code").fill("AB12 CD34");
			await page.getByRole("button", { name: "Pair" }).click();
			await expect(page.getByTestId("fingerprint")).toHaveText(FINGERPRINT);
			await shot(page, "pair-enter", scheme);

			await page.getByRole("button", { name: "It doesn't match" }).click();
			await expect(
				page.getByText("Unpaired. Nothing about you was shared."),
			).toBeVisible();
			await page.getByRole("button", { name: "Back to People" }).click();
			await expect(
				page.getByRole("heading", { name: "Mia", exact: true }),
			).toHaveCount(0);
		});
	});
}
