import { describe, expect, it } from "vitest";
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

	it("hand-over rejects when the worry fails", async () => {
		const d = sample();
		const api = createHttpApi({
			getToken: () => "tok",
			onUnauthorized: () => {},
			events: fakeEvents(),
			fetchImpl: async (_u, init) =>
				init?.method === "POST"
					? json({ ...d.worry, status: "triaging", watcher_id: null })
					: json({ ...d, worry: { ...d.worry, status: "failed" } }),
		});
		await expect(api.handOver("x")).rejects.toThrow(/failed/);
	});
});
