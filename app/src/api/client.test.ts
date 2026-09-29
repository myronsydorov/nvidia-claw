import { describe, expect, it } from "vitest";
import { initialDetails } from "../mocks/fixtures";
import { createMockApi } from "./client";
import { worryDetailSchema, worrySummarySchema } from "./schemas";

describe("mock fixtures", () => {
	it("every fixture follows the contract", () => {
		for (const d of initialDetails()) {
			expect(worryDetailSchema.safeParse(d).success).toBe(true);
		}
	});
});

describe("mock api", () => {
	it("hands over, approves and lets go, staying contract-shaped", async () => {
		const api = createMockApi(0);
		const before = await api.listWorries();
		for (const s of before) expect(worrySummarySchema.parse(s)).toBeTruthy();

		const handed = await api.handOver("Will my DHL parcel arrive?");
		expect(handed.worry.status).toBe("awaiting_approval");
		expect(handed.watcher?.policy_summary[0]?.host).toBe("api-eu.dhl.com");

		const approved = await api.approve(handed.worry.id);
		expect(approved.worry.status).toBe("watching");
		expect(approved.watcher?.state).toBe("active");
		expect((await api.listWorries()).length).toBe(before.length + 1);

		const gone = await api.letGo(handed.worry.id);
		expect(gone.worry.status).toBe("resolved");
		expect((await api.listWorries()).length).toBe(before.length);
	});

	it("deny parks the worry", async () => {
		const api = createMockApi(0);
		const handed = await api.handOver("What if it storms on Saturday?");
		const denied = await api.deny(handed.worry.id);
		expect(denied.worry.status).toBe("parked");
	});
});
