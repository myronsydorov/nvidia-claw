import { describe, expect, it } from "vitest";
import {
	ANNA,
	DAD,
	initialLedger,
	initialPeople,
	initialQuestionLog,
	initialRules,
	mockDailyClose,
} from "../mocks/people";
import { createMockApi } from "./client";
import type { Listener } from "./events";
import { ApiError, createHttpApi } from "./http";
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

	it("refuses to ask again within 10 minutes (429), like the Warden", async () => {
		const api = createMockApi(0);
		await api.ask(ANNA, "ok");
		await expect(api.ask(ANNA, "home")).rejects.toMatchObject({ status: 429 });
	});

	it("an asleep Warden is a 504, never a made-up answer", async () => {
		const api = createMockApi(0);
		await expect(api.ask(DAD, "ok")).rejects.toMatchObject({ status: 504 });
		const dad = (await api.listPeople()).find((p) => p.peer.id === DAD);
		expect(dad?.last_answer).toBeNull();
		// The cooldown still started: the question left, even though no answer came.
		expect(dad?.last_asked_at).not.toBeNull();
		await expect(api.ask(DAD, "ok")).rejects.toMatchObject({ status: 429 });
	});

	it("pairs by showing a code: waiting, then paired with a fingerprint", async () => {
		const api = createMockApi(0);
		const started = await api.startPairing("Mia");
		expect(started.code).toMatch(/^[0-9A-HJKMNP-TV-Z]{8}$/);
		expect((await api.pairingStatus(started.pairing_id)).state).toBe("waiting");
		await new Promise((r) => setTimeout(r, 2600));
		const done = await api.pairingStatus(started.pairing_id);
		expect(done.state).toBe("paired");
		expect(done.peer?.fingerprint).toMatch(/^\d{4} \d{4}$/);
		expect((await api.listPeople()).map((p) => p.peer.display_name)).toContain(
			"Mia",
		);
	});

	it("pairs by entering a code, refuses a malformed or own code, and unpairs", async () => {
		const api = createMockApi(0);
		await expect(api.joinPairing("nope", "Mia")).rejects.toMatchObject({
			status: 422,
		});
		await expect(api.joinPairing("k7m2-q9xa", "Mia")).rejects.toMatchObject({
			status: 409,
		});
		const peer = await api.joinPairing("ab12 cd34", "Mia");
		expect(peer.display_name).toBe("Mia");
		await api.unpair(peer.id);
		expect((await api.listPeople()).some((p) => p.peer.id === peer.id)).toBe(
			false,
		);
		await expect(api.unpair(peer.id)).rejects.toBeInstanceOf(ApiError);
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

	it("pairing routes: POST /api/pairing, GET /api/pairing/{id}, POST join, DELETE peer", async () => {
		const peer = initialPeople()[0]?.peer;
		const start = recording({
			pairing_id: "pr_01K6C0PA1R0000000000000000",
			code: "K7M2Q9XA",
			expires_at: "2026-10-01T10:10:00Z",
		});
		await start.api.startPairing("Anna");
		expect(start.calls[0]).toEqual({
			url: "/api/pairing",
			method: "POST",
			body: { display_name: "Anna" },
		});
		const status = recording({ state: "paired", peer });
		expect((await status.api.pairingStatus("pr_x")).peer).toEqual(peer);
		expect(status.calls[0]?.url).toBe("/api/pairing/pr_x");
		const join = recording(peer);
		await join.api.joinPairing("K7M2Q9XA", "Anna");
		expect(join.calls[0]).toEqual({
			url: "/api/pairing/join",
			method: "POST",
			body: { code: "K7M2Q9XA", display_name: "Anna" },
		});
		const calls: string[] = [];
		const del = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: noEvents,
			fetchImpl: async (u, init) => {
				calls.push(`${init?.method} ${String(u)}`);
				return new Response(null, { status: 204 });
			},
		});
		await del.confirm(ANNA);
		await del.unpair(ANNA);
		expect(calls).toEqual([
			`POST /api/people/${ANNA}/confirm`,
			`DELETE /api/people/${ANNA}`,
		]);
	});

	it("a peer without a fingerprint is a contract error", async () => {
		const peer = { ...initialPeople()[0]?.peer, fingerprint: undefined };
		const { api } = recording(peer);
		await expect(api.joinPairing("K7M2Q9XA", "Anna")).rejects.toThrow();
	});

	it.each([503, 504, 502, 429])(
		"surfaces ask status %i as an ApiError",
		async (status) => {
			const api = createHttpApi({
				getToken: () => "tok",
				onUnauthorized: () => {},
				events: noEvents,
				fetchImpl: async () => json({ detail: "x" }, status),
			});
			await expect(api.ask(ANNA, "ok")).rejects.toMatchObject({ status });
		},
	);

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

	it("POST /api/talk sends only the text and parses the reply", async () => {
		const reply = { reply: "<b>2</b> worries", at: "2026-10-02T11:00:00Z" };
		const { api, calls } = recording(reply);
		expect(await api.talk("What are you watching?")).toEqual(reply);
		expect(`${calls[0]?.method} ${calls[0]?.url}`).toBe("POST /api/talk");
		expect(calls[0]?.body).toEqual({ text: "What are you watching?" });
	});

	it.each([422, 429, 503])(
		"surfaces talk status %i as an ApiError",
		async (status) => {
			const api = createHttpApi({
				getToken: () => "tok",
				onUnauthorized: () => {},
				events: noEvents,
				fetchImpl: async () => json({ detail: "x" }, status),
			});
			await expect(api.talk("hi")).rejects.toMatchObject({ status });
		},
	);

	it("GET /api/daily-close: a note or null", async () => {
		const note = mockDailyClose();
		expect(await recording(note).api.getDailyClose()).toEqual(note);
		expect(await recording(null).api.getDailyClose()).toBeNull();
		const long = recording({ ...note, text: "x".repeat(401) });
		await expect(long.api.getDailyClose()).rejects.toThrow();
	});
});
