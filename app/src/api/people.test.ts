import { describe, expect, it } from "vitest";
import {
	ANNA,
	initialLedger,
	initialPeople,
	initialQuestionLog,
	initialRules,
} from "../mocks/people";
import { createMockApi } from "./client";
import type { Listener } from "./events";
import { createHttpApi } from "./http";
import {
	type Event,
	ledgerResponseSchema,
	peopleListItemSchema,
	sharingRulesResponseSchema,
} from "./schemas";

const json = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});

const noEvents = { subscribe: () => () => {} };

describe("people fixtures", () => {
	it("follow the contract", () => {
		expect(peopleListItemSchema.array().parse(initialPeople())).toHaveLength(2);
		const s = { rules: initialRules(), questions_log: initialQuestionLog() };
		expect(sharingRulesResponseSchema.safeParse(s).success).toBe(true);
		expect(ledgerResponseSchema.safeParse(initialLedger()).success).toBe(true);
	});

	it("keep the question log newest first", () => {
		const at = initialQuestionLog().map((e) => Date.parse(e.asked_at));
		expect([...at].sort((a, b) => b - a)).toEqual(at);
	});
});

describe("mock api: people, sharing, ledger", () => {
	it("asks, answers in the fixed vocabulary, and hands back a receipt", async () => {
		const api = createMockApi(0);
		const seen: Event["type"][] = [];
		const listener: Listener = (e) => {
			if (e.type !== "connected") seen.push(e.type);
		};
		api.subscribe(listener);

		const res = await api.ask(ANNA, "ok");
		expect(res.answer.level).toBe("normal");
		expect(res.answer.reason).toBe("active_as_usual");
		expect(res.receipt.bytes_sent).toBe(212);
		expect(res.receipt.location_shared).toBe(false);
		expect(seen).toContain("peer.answer");

		const anna = (await api.listPeople()).find((p) => p.peer.id === ANNA);
		expect(anna?.last_answer).toEqual(res.answer);
	});

	it("refuses an unknown peer", async () => {
		const api = createMockApi(0);
		await expect(
			api.ask("p_01K6C0NKNWN0000000000000099", "ok"),
		).rejects.toThrow();
	});

	it("PUT replaces the rules but never the server's log", async () => {
		const api = createMockApi(0);
		const before = await api.getSharingRules();
		const after = await api.putSharingRules({
			rules: before.rules.map((r) => ({ ...r, active: false })),
			questions_log: [],
		});
		expect(after.rules.every((r) => !r.active)).toBe(true);
		expect(after.questions_log).toEqual(before.questions_log);
		expect(await api.getSharingRules()).toEqual(after);
	});

	it("serves a contract-shaped ledger", async () => {
		const l = await createMockApi(0).getLedger();
		expect(l.locations_shared).toBe(0);
	});
});

describe("http api: people, sharing, ledger (CONTRACTS §3)", () => {
	function recording(body: unknown) {
		const calls: { url: string; method: string; body: unknown }[] = [];
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: noEvents,
			fetchImpl: async (u, init) => {
				calls.push({
					url: String(u),
					method: init?.method ?? "GET",
					body: init?.body ? JSON.parse(String(init.body)) : undefined,
				});
				return json(body);
			},
		});
		return { api, calls };
	}

	it("GET /api/people", async () => {
		const { api, calls } = recording(initialPeople());
		expect(await api.listPeople()).toHaveLength(2);
		expect(calls[0]).toMatchObject({ url: "/api/people", method: "GET" });
	});

	it("POST /api/people/{peer_id}/ask with { q }", async () => {
		const { api, calls } = recording({
			answer: {
				level: "unknown",
				reason: "not_enough_data",
				ts: "2026-10-01T10:00:00Z",
			},
			receipt: {
				bytes_sent: 0,
				fields_shared: [],
				location_shared: false,
				egress_log_ref: "n/a (no relay yet)",
			},
		});
		const res = await api.ask(ANNA, "home");
		expect(res.receipt.bytes_sent).toBe(0);
		expect(calls[0]).toEqual({
			url: `/api/people/${ANNA}/ask`,
			method: "POST",
			body: { q: "home" },
		});
	});

	it("rejects an answer outside the fixed vocabulary", async () => {
		const { api } = recording({
			answer: {
				level: "normal",
				reason: "at_the_gym",
				ts: "2026-10-01T10:00:00Z",
			},
			receipt: {
				bytes_sent: 1,
				fields_shared: [],
				location_shared: false,
				egress_log_ref: "x",
			},
		});
		await expect(api.ask(ANNA, "ok")).rejects.toThrow();
	});

	it("GET and PUT /api/sharing-rules", async () => {
		const body = { rules: initialRules(), questions_log: initialQuestionLog() };
		const { api, calls } = recording(body);
		await api.getSharingRules();
		await api.putSharingRules(body);
		expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
			"GET /api/sharing-rules",
			"PUT /api/sharing-rules",
		]);
		expect(calls[1]?.body).toEqual(body);
	});

	it("GET /api/ledger, and only locations_shared: 0", async () => {
		const { api, calls } = recording(initialLedger());
		expect(await api.getLedger()).toEqual(initialLedger());
		expect(calls[0]?.url).toBe("/api/ledger");
		const bad = recording({ ...initialLedger(), locations_shared: 1 });
		await expect(bad.api.getLedger()).rejects.toThrow();
	});
});
