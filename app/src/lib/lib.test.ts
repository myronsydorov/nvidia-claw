import { describe, expect, it } from "vitest";
import { href, parseHash } from "./router";
import { ago, day, every } from "./time";

describe("router", () => {
	it("round-trips every route", () => {
		for (const r of [
			{ name: "home" },
			{ name: "hand-over", text: "Will it rain? & more" },
			{ name: "worry", id: "w_01K6B8Z3Q4R5S6T7V8W9XA0001" },
			{ name: "people" },
			{ name: "sharing" },
			{ name: "ledger" },
		] as const) {
			expect(parseHash(href(r))).toEqual(r);
		}
	});

	it("falls back to home", () => {
		expect(parseHash("#/nope")).toEqual({ name: "home" });
	});
});

describe("time", () => {
	const now = Date.parse("2026-09-29T12:00:00Z");
	it("formats relative times", () => {
		expect(ago("2026-09-29T11:59:30Z", now)).toBe("just now");
		expect(ago("2026-09-29T11:48:00Z", now)).toBe("12 min ago");
		expect(ago("2026-09-29T09:00:00Z", now)).toBe("3 h ago");
		expect(ago("2026-09-28T12:00:00Z", now)).toBe("yesterday");
	});
	it("formats intervals", () => {
		expect(every(3600)).toBe("every hour");
		expect(every(10800)).toBe("every 3 hours");
		expect(every(1800)).toBe("every 30 minutes");
		expect(every(86400)).toBe("once a day");
	});
});

describe("day", () => {
	it("shows Berlin wall-clock time for a UTC instant (S7 incident)", () => {
		// 07:00 UTC on Fri 2 Oct 2026 is 09:00 in Berlin (CEST), whatever the device zone.
		expect(day("2026-10-02T07:00:00Z")).toBe("Fri 09:00");
	});
});
