import { expect, test } from "@playwright/test";
import { E2E_TOKEN, WARDEN_PORT } from "./env.ts";

test("hand over → approve → watching, against a real Warden", async ({
	page,
	request,
}) => {
	await page.goto("/");

	// First run: connect with the device token.
	await page.getByLabel("Device token").fill(E2E_TOKEN);
	await page.getByRole("button", { name: "Connect" }).click();
	await expect(page.getByRole("heading", { name: "All quiet." })).toBeVisible();
	await expect(page.getByText("Nothing in custody.")).toBeVisible();

	// Hand it over.
	const text = "Will my DHL parcel arrive by Friday?";
	await page.getByLabel("What's on your mind?").fill(text);
	await page.getByRole("button", { name: "Hand it over" }).click();

	// The Warden's (mock) compiler reaches awaiting_approval → permission card.
	await expect(page.getByText("Your watcher asks to reach:")).toBeVisible({
		timeout: 15_000,
	});
	await expect(page.getByText("api-eu.dhl.com/track/shipments")).toBeVisible();
	await page.screenshot({ path: "e2e/results/permission-card.png" });
	await page.getByRole("button", { name: "Allow" }).click();
	await expect(page.getByText("I've got this.")).toBeVisible();

	// Home lists it, live from the Warden; open it and see it watching.
	await expect(
		page.getByText("1 worry in custody. Nothing needs you."),
	).toBeVisible({
		timeout: 10_000,
	});
	await page.getByRole("link", { name: new RegExp(text) }).click();
	await expect(page.getByText("Watching", { exact: true })).toBeVisible();
	await page.screenshot({
		path: "e2e/results/detail-watching.png",
		fullPage: true,
	});

	// And the Warden agrees.
	const id = page.url().split("/worry/")[1];
	const res = await request.get(
		`http://127.0.0.1:${WARDEN_PORT}/api/worries/${id}`,
		{
			headers: { Authorization: `Bearer ${E2E_TOKEN}` },
		},
	);
	const detail = await res.json();
	expect(detail.worry.status).toBe("watching");
	expect(detail.watcher.state).toBe("active");
});
