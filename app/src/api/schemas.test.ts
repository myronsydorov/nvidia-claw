import { describe, expect, it } from "vitest";
import {
	askPeerRequestSchema,
	askPeerResponseSchema,
	eventSchema,
	healthResponseSchema,
	ledgerResponseSchema,
	outcomeRequestSchema,
	peerSchema,
	peopleListItemSchema,
	privacyReceiptSchema,
	pushSubscriptionSchema,
	questionLogEntrySchema,
	reassuranceAnswerSchema,
	sharingRuleSchema,
	sharingRulesResponseSchema,
	watcherSchema,
	watchResultSchema,
	worryCreateRequestSchema,
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

// --- T-07 additions below ---

describe("worryCreateRequestSchema / outcomeRequestSchema", () => {
	it("accepts a worry creation request", () => {
		expect(worryCreateRequestSchema.safeParse({ text: "x" }).success).toBe(
			true,
		);
	});

	it("rejects a non-boolean outcome", () => {
		expect(
			outcomeRequestSchema.safeParse({ fear_came_true: "yes" }).success,
		).toBe(false);
	});
});

const peer = {
	id: `p_${ULID}`,
	display_name: "Anna",
	public_key: "base64key",
	paired_at: "2026-09-29T08:00:00Z",
	fingerprint: "4821 0937",
};

describe("peerSchema / peopleListItemSchema", () => {
	it("accepts a contract-shaped peer", () => {
		expect(peerSchema.safeParse(peer).success).toBe(true);
	});

	it("requires the 8-digit fingerprint", () => {
		expect(
			peerSchema.safeParse({ ...peer, fingerprint: "48210937" }).success,
		).toBe(false);
		const { fingerprint: _, ...without } = peer;
		expect(peerSchema.safeParse(without).success).toBe(false);
	});

	it("rejects a peer id with the wrong prefix", () => {
		expect(peerSchema.safeParse({ ...peer, id: `w_${ULID}` }).success).toBe(
			false,
		);
	});

	it("accepts a people list item with a null last answer", () => {
		expect(
			peopleListItemSchema.safeParse({
				peer,
				last_answer: null,
				last_answer_at: null,
				last_asked_at: null,
			}).success,
		).toBe(true);
	});
});

describe("reassuranceAnswerSchema / askPeerResponseSchema", () => {
	const answer = {
		level: "unknown",
		reason: "not_enough_data",
		ts: "2026-09-29T08:00:00Z",
	};

	it("accepts a fixed-vocabulary answer", () => {
		expect(reassuranceAnswerSchema.safeParse(answer).success).toBe(true);
	});

	it("rejects free text outside the vocabulary", () => {
		expect(
			reassuranceAnswerSchema.safeParse({ ...answer, level: "fine!" }).success,
		).toBe(false);
	});

	it("accepts an ask-peer response with a privacy receipt", () => {
		const receipt = {
			bytes_sent: 0,
			fields_shared: ["level", "reason", "ts"],
			location_shared: false,
			egress_log_ref: "n/a",
		};
		expect(askPeerResponseSchema.safeParse({ answer, receipt }).success).toBe(
			true,
		);
		expect(privacyReceiptSchema.safeParse(receipt).success).toBe(true);
	});

	it("rejects an ask-peer request question outside ok|home", () => {
		expect(askPeerRequestSchema.safeParse({ q: "location" }).success).toBe(
			false,
		);
	});
});

describe("sharingRuleSchema / sharingRulesResponseSchema", () => {
	const rule = {
		peer_id: `p_${ULID}`,
		allowed_questions: ["ok"],
		allowed_levels: ["normal", "unusual"],
		active: true,
	};

	it("accepts a contract-shaped sharing rule", () => {
		expect(sharingRuleSchema.safeParse(rule).success).toBe(true);
	});

	it("accepts a sharing-rules response with a questions log", () => {
		const entry = {
			id: "q1",
			peer_id: `p_${ULID}`,
			question: "ok",
			asked_at: "2026-09-29T08:00:00Z",
			answer_level: "normal",
		};
		expect(questionLogEntrySchema.safeParse(entry).success).toBe(true);
		expect(
			sharingRulesResponseSchema.safeParse({
				rules: [rule],
				questions_log: [entry],
			}).success,
		).toBe(true);
	});
});

describe("pushSubscriptionSchema", () => {
	it("accepts a web-push subscription", () => {
		expect(
			pushSubscriptionSchema.safeParse({
				endpoint: "https://push.example/abc",
				keys: { p256dh: "x", auth: "y" },
			}).success,
		).toBe(true);
	});
});

describe("ledgerResponseSchema", () => {
	it("accepts the contract-shaped ledger and pins locations_shared to 0", () => {
		const ledger = {
			worries_total: 1,
			active: 1,
			never_needed_you: 0,
			needed_you: 0,
			median_warning_lead_h: 0,
			came_true_rate: 0,
			came_true_by_type: {},
			watchers_built: 0,
			sandboxes_live: 0,
			endpoints_denied: 0,
			peer_questions_answered: 0,
			locations_shared: 0,
		};
		expect(ledgerResponseSchema.safeParse(ledger).success).toBe(true);
		expect(
			ledgerResponseSchema.safeParse({ ...ledger, locations_shared: 1 })
				.success,
		).toBe(false);
	});
});

describe("eventSchema", () => {
	it("accepts a known event type", () => {
		expect(
			eventSchema.safeParse({ type: "worry.updated", data: {} }).success,
		).toBe(true);
	});

	it("rejects an unknown event type", () => {
		expect(
			eventSchema.safeParse({ type: "worry.deleted", data: {} }).success,
		).toBe(false);
	});
});
