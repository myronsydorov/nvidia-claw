import { describe, expect, it } from "vitest";
import {
	healthResponseSchema,
	watcherSchema,
	watchResultSchema,
	worrySchema,
} from "./schemas";

describe("healthResponseSchema", () => {
	it("accepts a valid health response", () => {
		const result = healthResponseSchema.safeParse({
			status: "ok",
			sandboxes_live: 0,
		});
		expect(result.success).toBe(true);
	});

	it("rejects a status outside the fixed literal", () => {
		const result = healthResponseSchema.safeParse({
			status: "degraded",
			sandboxes_live: 0,
		});
		expect(result.success).toBe(false);
	});

	it("rejects a non-integer sandbox count", () => {
		const result = healthResponseSchema.safeParse({
			status: "ok",
			sandboxes_live: 1.5,
		});
		expect(result.success).toBe(false);
	});
});

const ULID = "01K6B8Z3Q4R5S6T7V8W9XA0001";
const worry = {
	id: `w_${ULID}`,
	text: "I'm worried my parcel won't arrive before Friday",
	type: "deadline",
	fear: "Parcel not delivered by Friday 18:00",
	deadline: "2026-10-02T16:00:00Z",
	status: "watching",
	watcher_id: `wt_${ULID}`,
	resolution: null,
	fear_came_true: null,
	created_at: "2026-09-29T08:00:00Z",
	updated_at: "2026-09-29T09:00:00Z",
};

describe("worrySchema", () => {
	it("accepts a contract-shaped worry", () => {
		expect(worrySchema.safeParse(worry).success).toBe(true);
	});

	it("rejects an id without the w_ prefix or a bad ULID", () => {
		expect(worrySchema.safeParse({ ...worry, id: ULID }).success).toBe(false);
		expect(
			worrySchema.safeParse({ ...worry, id: "w_01K6B8Z3Q4R5S6T7V8W9XA000I" })
				.success,
		).toBe(false);
	});

	it("rejects a status outside the enum", () => {
		expect(worrySchema.safeParse({ ...worry, status: "done" }).success).toBe(
			false,
		);
	});
});

describe("watchResultSchema", () => {
	const result = {
		status: "ok",
		summary: "In transit",
		evidence: { source: "DHL", checked_at: "2026-09-29T09:00:00Z", data: {} },
		fear_came_true: null,
		next_check_s: 3600,
	};

	it("accepts a valid result", () => {
		expect(watchResultSchema.safeParse(result).success).toBe(true);
	});

	it("rejects a summary longer than 140 characters", () => {
		expect(
			watchResultSchema.safeParse({ ...result, summary: "x".repeat(141) })
				.success,
		).toBe(false);
	});
});

describe("watcherSchema", () => {
	const watcher = {
		id: `wt_${ULID}`,
		worry_id: `w_${ULID}`,
		adapters: ["parcel_dhl"],
		code: "",
		policy_yaml: "",
		policy_summary: [
			{
				method: "GET",
				host: "api-eu.dhl.com",
				path: "/track/shipments",
				why: "x",
			},
		],
		sandbox_name: "cw-xa0001",
		interval_s: 3600,
		state: "active",
		last_result: null,
	};

	it("accepts a valid watcher", () => {
		expect(watcherSchema.safeParse(watcher).success).toBe(true);
	});

	it("rejects non-GET permissions", () => {
		const post = [{ ...watcher.policy_summary[0], method: "POST" }];
		expect(
			watcherSchema.safeParse({ ...watcher, policy_summary: post }).success,
		).toBe(false);
	});

	it("enforces the sandbox name and interval bounds", () => {
		for (const sandbox_name of ["cw-", "CW-abc", "cw-abcdefghijklmnopq"]) {
			expect(
				watcherSchema.safeParse({ ...watcher, sandbox_name }).success,
			).toBe(false);
		}
		for (const interval_s of [299, 86401]) {
			expect(watcherSchema.safeParse({ ...watcher, interval_s }).success).toBe(
				false,
			);
		}
	});
});
