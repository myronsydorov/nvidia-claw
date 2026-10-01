import { expect, type Page, test } from "@playwright/test";

// initialLedger() in src/mocks/people.ts. Copied, not imported: e2e/ is
// type-checked as Node ESM and can't follow the app's extensionless imports.
const LEDGER = {
	worries_total: 23,
	active: 3,
	never_needed_you: 17,
	needed_you: 2,
	watchers_built: 21,
	sandboxes_live: 3,
	endpoints_denied: 7,
	peer_questions_answered: 12,
	locations_shared: 0,
	came_true_by_type: { checkable: 1 / 9, deadline: 1 / 8, person: 0 },
};

/** The exact 390×844 phone viewport, plus the whole scroll for review. */
async function shot(page: Page, name: string, scheme: string) {
	await page.screenshot({ path: `e2e/results/${name}-${scheme}.png` });
	await page.screenshot({
		path: `e2e/results/${name}-${scheme}-full.png`,
		fullPage: true,
	});
}

for (const scheme of ["dark", "light"] as const) {
	test.describe(`${scheme} mode`, () => {
		test.use({ colorScheme: scheme });

		test("ask: Is Anna OK? → answer card with the privacy receipt", async ({
			page,
		}) => {
			await page.goto("/");
			await page.getByRole("link", { name: "People" }).click();
			await expect(
				page.getByRole("heading", { name: "People", exact: true }),
			).toBeVisible();

			await page.getByRole("button", { name: "Is Anna OK?" }).click();
			await expect(page.getByText("Asking Anna's Warden…")).toBeVisible();

			const card = page.getByRole("region", { name: "Anna's answer" });
			await expect(card.getByText("Normal day, just now")).toBeVisible();
			await expect(card.getByText("Privacy receipt")).toBeVisible();
			await expect(
				card.getByText(
					"Shared: 1 answer, 212 bytes, encrypted. Location: never.",
				),
			).toBeVisible();
			await expect(card.getByText("Fields: level, reason, ts")).toBeVisible();
			// No "check again": the buttons give way to the cooldown line.
			await expect(
				page.getByText(
					"Asked 1 min ago. They'll tell you if anything changes.",
				),
			).toBeVisible();
			await expect(
				page.getByRole("button", { name: "Is Anna OK?" }),
			).toHaveCount(0);
			await shot(page, "people", scheme);
		});

		test("an asleep Warden: a calm 504 line, no made-up answer", async ({
			page,
		}) => {
			await page.goto("/#/people");
			await page.getByRole("button", { name: "Is Dad OK?" }).click();
			await expect(
				page.getByText(
					"Dad's Warden didn't answer in time. Their computer may be asleep or offline. That alone doesn't mean anything is wrong.",
				),
			).toBeVisible();
			// No re-ask loop after silence either: the cooldown runs from the question.
			await expect(
				page.getByText(
					"Asked 1 min ago. They'll tell you if anything changes.",
				),
			).toBeVisible();
			await expect(
				page.getByRole("region", { name: "Dad's answer" }),
			).toHaveCount(0);
			await shot(page, "people-no-answer", scheme);
		});

		test("what others can ask about me: rules and the question log", async ({
			page,
		}) => {
			await page.goto("/#/people");
			await page
				.getByRole("link", { name: "What others can ask about me" })
				.click();
			const dad = page.getByRole("switch", { name: "Let Dad ask about me" });
			await expect(dad).toBeChecked();
			const log = page.getByRole("list", { name: "Question log" });
			await expect(log.getByRole("listitem")).toHaveCount(3);
			await expect(log.getByText("Anna asked “Are you home?”")).toBeVisible();
			await shot(page, "sharing", scheme);

			// Turning Dad off goes through PUT /api/sharing-rules (the whole list).
			await dad.click();
			await expect(page.getByText("Can't ask anything")).toBeVisible();
		});

		test("ledger: every §5 field, compared with 91.4%", async ({ page }) => {
			await page.goto("/");
			await page.getByRole("link", { name: "Ledger" }).click();
			const l = LEDGER;
			const field = (f: string) => page.locator(`[data-field="${f}"]`);
			await expect(field("never_needed_you")).toHaveText(
				String(l.never_needed_you),
			);
			for (const f of [
				"worries_total",
				"active",
				"needed_you",
				"watchers_built",
				"sandboxes_live",
				"endpoints_denied",
				"peer_questions_answered",
				"locations_shared",
			] as const) {
				await expect(field(f)).toHaveText(String(l[f]));
			}
			await expect(field("median_warning_lead_h")).toHaveText("31.5 h");
			await expect(field("came_true_rate")).toHaveText("10.5%");
			await expect(
				field("came_true_by_type").getByRole("listitem"),
			).toHaveCount(Object.keys(l.came_true_by_type).length);
			await expect(page.getByText("Penn State study")).toBeVisible();
			await expect(page.getByText("91.4%", { exact: true })).toBeVisible();
			await shot(page, "ledger", scheme);
		});
	});
}
