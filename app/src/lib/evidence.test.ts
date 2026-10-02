import { describe, expect, it } from "vitest";
import type { WatchResult, WorryDetail } from "../api/schemas";
import { initialDetails } from "../mocks/fixtures";
import { asksOutcome, evidenceRows } from "./evidence";

const result = (data: Record<string, unknown>): WatchResult => ({
	status: "act_now",
	summary: "S7 toward Potsdam Hbf is cancelled.",
	evidence: { source: "BVG", checked_at: "2026-10-02T07:00:00Z", data },
	fear_came_true: null,
	next_check_s: 300,
});

describe("evidenceRows", () => {
	it("shows up to six readable rows as plain text", () => {
		const rows = evidenceRows(
			result({
				delay_min: 14,
				cancelled: true,
				platform: null,
				disruptions: [{ line: "S7" }],
				note: "x".repeat(200),
				truncated: true,
				a: 1,
				b: 2,
			}),
		);
		expect(rows.slice(0, 4)).toEqual([
			{ key: "delay min", value: "14" },
			{ key: "cancelled", value: "yes" },
			{ key: "platform", value: "—" },
			{ key: "disruptions", value: '[{"line":"S7"}]' },
		]);
		expect(rows[4]?.value).toHaveLength(80);
		expect(rows).toHaveLength(6);
		expect(rows.map((r) => r.key)).not.toContain("truncated");
	});
});

describe("asksOutcome", () => {
	const base = (): WorryDetail => {
		const d = structuredClone(initialDetails()[0]);
		if (!d) throw new Error("fixture");
		d.worry.status = "resolved";
		d.worry.fear_came_true = null;
		d.timeline = [{ at: "2026-10-02T07:00:00Z", kind: "approved", text: "x" }];
		return d;
	};
	it("asks once for a closed worry that was watched", () => {
		expect(asksOutcome(base())).toBe(true);
	});
	it("doesn't ask when answered, still open, or never approved", () => {
		const answered = base();
		answered.worry.fear_came_true = false;
		const open = base();
		open.worry.status = "needs_you";
		const denied = base();
		denied.timeline = [
			{ at: "2026-10-02T07:00:00Z", kind: "denied", text: "x" },
		];
		expect([answered, open, denied].map(asksOutcome)).toEqual([
			false,
			false,
			false,
		]);
	});
});
