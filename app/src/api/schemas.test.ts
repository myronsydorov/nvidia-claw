import { describe, expect, it } from "vitest";
import { healthResponseSchema } from "./schemas";

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
