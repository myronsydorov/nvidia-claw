import { describe, expect, it, vi } from "vitest";
import { initialDetails } from "../mocks/fixtures";
import type { Listener } from "./events";
import { ApiError, createHttpApi } from "./http";
import type { WorryDetail } from "./schemas";

const json = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});

function fakeEvents() {
	const listeners = new Set<Listener>();
	return {
		subscribe(l: Listener) {
			listeners.add(l);
			return () => listeners.delete(l);
		},
		emit(worry_id: string) {
			for (const l of [...listeners])
				l({ type: "worry.updated", data: { worry_id } });
		},
		get size() {
			return listeners.size;
		},
	};
}

const sample = (): WorryDetail => {
	const d = initialDetails().find((x) => x.watcher);
	if (!d) throw new Error("fixture with a watcher");
	return d;
};

describe("http api", () => {
	it("sends the bearer token and zod-validates the response", async () => {
		const seen: Headers[] = [];
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: fakeEvents(),
			fetchImpl: async (_u, init) => {
				seen.push(new Headers(init?.headers));
				return json([{ worry: sample().worry, last_result: null }]);
			},
		});
		const list = await api.listWorries();
		expect(list).toHaveLength(1);
		expect(seen[0]?.get("authorization")).toBe("Bearer tok");
	});

	it("rejects a response that breaks the contract", async () => {
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: fakeEvents(),
			fetchImpl: async () => json([{ worry: { id: "nope" } }]),
		});
		await expect(api.listWorries()).rejects.toThrow();
	});

	it("reports a 401 and throws ApiError", async () => {
		let unauthorized = 0;
		const api = createHttpApi({
			getToken: () => "bad",
			onUnauthorized: () => {
				unauthorized += 1;
			},
			events: fakeEvents(),
			fetchImpl: async () => json({ detail: "invalid device token" }, 401),
		});
		await expect(api.getWorry("w_x")).rejects.toBeInstanceOf(ApiError);
		expect(unauthorized).toBe(1);
	});

	it("hand-over resolves once events show the watcher awaiting approval", async () => {
		const events = fakeEvents();
		const d = sample();
		let status: WorryDetail["worry"]["status"] = "triaging";
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events,
			fetchImpl: async (url, init) => {
				if (init?.method === "POST")
					return json({ ...d.worry, status: "triaging", watcher_id: null });
				expect(String(url)).toBe(`/api/worries/${d.worry.id}`);
				return json({
					...d,
					worry: { ...d.worry, status },
					watcher:
						status === "awaiting_approval"
							? { ...d.watcher, state: "awaiting_approval" }
							: null,
				});
			},
		});
		const pending = api.handOver(d.worry.text);
		await new Promise((r) => setTimeout(r, 5));
		expect(events.size).toBe(1);
		events.emit("w_someone_else");
		status = "awaiting_approval";
		events.emit(d.worry.id);
		const out = await pending;
		expect(out.worry.status).toBe("awaiting_approval");
		expect(events.size).toBe(0); // unsubscribed
	});

	it.each(["failed", "parked"] as const)(
		"hand-over resolves with the real state when it ends %s (S7 incident)",
		async (end) => {
			const d = sample();
			const resolution =
				"Testing the watcher failed: the check could not get its data.";
			const api = createHttpApi({
				getToken: () => "tok",
				onUnauthorized: () => {},
				events: fakeEvents(),
				fetchImpl: async (_u, init) =>
					init?.method === "POST"
						? json({ ...d.worry, status: "triaging", watcher_id: null })
						: json({
								...d,
								worry: { ...d.worry, status: end, resolution },
								watcher: null,
							}),
			});
			const out = await api.handOver("x");
			expect(out.worry.status).toBe(end);
			expect(out.worry.resolution).toBe(resolution);
		},
	);

	it("hand-over keeps waiting past a minute and survives a failed read", async () => {
		vi.useFakeTimers();
		try {
			const d = sample();
			let reads = 0;
			const api = createHttpApi({
				getToken: () => "tok",
				onUnauthorized: () => {},
				events: fakeEvents(),
				pollMs: 15_000,
				fetchImpl: async (_u, init) => {
					if (init?.method === "POST")
						return json({ ...d.worry, status: "triaging", watcher_id: null });
					reads += 1;
					if (reads === 2) throw new TypeError("network blip");
					const status = reads < 10 ? "compiling" : "awaiting_approval";
					return json({
						...d,
						worry: { ...d.worry, status },
						watcher: { ...d.watcher, state: "awaiting_approval" },
					});
				},
			});
			const box: { out: WorryDetail | null } = { out: null };
			void api.handOver("x").then((out) => {
				box.out = out;
			});
			await vi.advanceTimersByTimeAsync(120_000); // two minutes: no "gave up" any more
			expect(box.out).toBeNull();
			await vi.advanceTimersByTimeAsync(30_000);
			expect(box.out?.worry.status).toBe("awaiting_approval");
		} finally {
			vi.useRealTimers();
		}
	});

	it("only a failed POST rejects: nothing was handed over", async () => {
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: fakeEvents(),
			fetchImpl: async () => json({ detail: "down" }, 503),
		});
		await expect(api.handOver("x")).rejects.toBeInstanceOf(ApiError);
	});
});

describe("me: signal, check-in, help", () => {
	it("calls the CONTRACTS §3 routes and rejects an answer outside the vocabulary", async () => {
		const calls: string[] = [];
		let reply: unknown = {
			level: "normal",
			reason: "active_as_usual",
			ts: "2026-10-02T07:00:00Z",
		};
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: fakeEvents(),
			fetchImpl: async (u, init) => {
				calls.push(`${init?.method} ${String(u)}`);
				return String(u).endsWith("/signal")
					? json(reply)
					: new Response(null, { status: 204 });
			},
		});
		expect((await api.mySignal()).reason).toBe("active_as_usual");
		await api.checkIn();
		await api.setHelp(true);
		await api.setHelp(false);
		expect(calls).toEqual([
			"GET /api/me/signal",
			"POST /api/me/check-in",
			"POST /api/me/help",
			"DELETE /api/me/help",
		]);
		reply = {
			level: "normal",
			reason: "at the gym",
			ts: "2026-10-02T07:00:00Z",
		};
		await expect(api.mySignal()).rejects.toThrow();
	});
});
