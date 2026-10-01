import { describe, expect, it } from "vitest";
import type { ReassuranceReason } from "../api/schemas";
import { reassuranceReasonSchema } from "../api/schemas";
import { initialLedger } from "../mocks/people";
import {
	answerHeadline,
	askLabel,
	defaultRule,
	didntComeTrue,
	hours,
	pct,
	receiptLine,
	withRule,
} from "./reassurance";

const ts = "2026-10-01T10:00:00Z";

describe("answer wording", () => {
	it("has words for every reason in the fixed vocabulary", () => {
		for (const reason of reassuranceReasonSchema.options) {
			const h = answerHeadline({ level: "normal", reason, ts });
			expect(h).toBeTruthy();
			expect(h).not.toBe(reason);
		}
	});

	it("reads like the design: Normal day", () => {
		const reason: ReassuranceReason = "active_as_usual";
		expect(answerHeadline({ level: "normal", reason, ts })).toBe("Normal day");
		expect(askLabel("ok", "Anna")).toBe("Is Anna OK?");
	});
});

describe("privacy receipt", () => {
	it("states bytes, encryption and location", () => {
		expect(
			receiptLine({
				bytes_sent: 212,
				fields_shared: ["level", "reason", "ts"],
				location_shared: false,
				egress_log_ref: "x",
			}),
		).toBe("Shared: 1 answer, 212 bytes, encrypted. Location: never.");
	});

	it("claims nothing when nothing was sent (today's Warden placeholder)", () => {
		const line = receiptLine({
			bytes_sent: 0,
			fields_shared: [],
			location_shared: false,
			egress_log_ref: "n/a (no relay yet)",
		});
		expect(line).toBe("Nothing left their device. Location: never.");
		expect(line).not.toContain("encrypted");
	});

	it("never hides a shared location", () => {
		expect(
			receiptLine({
				bytes_sent: 1,
				fields_shared: [],
				location_shared: true,
				egress_log_ref: "x",
			}),
		).toContain("Location: shared.");
	});
});

describe("ledger numbers", () => {
	it("compares didn't-come-true with Penn State's 91.4%", () => {
		const l = initialLedger();
		expect(didntComeTrue(l)).toBeCloseTo(17 / 19);
		expect(pct(0.914)).toBe("91.4%");
		expect(pct(17 / 19)).toBe("89.5%");
		expect(pct(1)).toBe("100%");
		expect(pct(0)).toBe("0%");
	});

	it("makes no claim before any outcome is known", () => {
		const l = {
			...initialLedger(),
			needed_you: 0,
			never_needed_you: 0,
			came_true_rate: 0,
		};
		expect(didntComeTrue(l)).toBeNull();
	});

	it("formats warning lead times", () => {
		expect(hours(0.5)).toBe("30 min");
		expect(hours(31.5)).toBe("31.5 h");
		expect(hours(72)).toBe("3 days");
	});
});

describe("sharing rules", () => {
	it("replaces one person's rule and keeps the others", () => {
		const a = defaultRule("p_01K6C0ANNA0000000000000001");
		const b = defaultRule("p_01K6C0DAD00000000000000002");
		const next = withRule([a, b], { ...a, active: false });
		expect(next).toHaveLength(2);
		expect(next.find((r) => r.peer_id === a.peer_id)?.active).toBe(false);
		expect(next.find((r) => r.peer_id === b.peer_id)).toEqual(b);
	});
});
