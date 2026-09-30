import { describe, expect, it } from "vitest";
import { createEventStream, type LiveEvent, parseSse } from "./events";

const frame = (type: string, data: unknown) =>
	`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;

describe("parseSse", () => {
	it("parses complete frames and keeps the partial tail", () => {
		const text =
			frame("worry.updated", { worry_id: "w_1" }) + "event: peer.ans";
		const { events, rest } = parseSse(text);
		expect(events).toEqual([
			{ type: "worry.updated", data: { worry_id: "w_1" } },
		]);
		expect(rest).toBe("event: peer.ans");
	});

	it("reassembles a frame split across chunks", () => {
		const whole = frame("approval.needed", { worry_id: "w_2" });
		const first = parseSse(whole.slice(0, 17));
		expect(first.events).toEqual([]);
		const second = parseSse(first.rest + whole.slice(17));
		expect(second.events).toEqual([
			{ type: "approval.needed", data: { worry_id: "w_2" } },
		]);
		expect(second.rest).toBe("");
	});

	it("drops comments, unknown types and non-JSON data", () => {
		const text =
			": ping\n\n" +
			frame("not.a.contract.event", {}) +
			"event: worry.updated\ndata: nope\n\n";
		expect(parseSse(text).events).toEqual([]);
	});
});

function sseResponse(chunks: string[]): Response {
	const body = new ReadableStream<Uint8Array>({
		start(c) {
			for (const chunk of chunks) c.enqueue(new TextEncoder().encode(chunk));
			c.close();
		},
	});
	return new Response(body, { status: 200 });
}

const tick = () => new Promise((r) => setTimeout(r, 5));

describe("createEventStream", () => {
	it("sends the bearer token, emits events and reconnects after the stream ends", async () => {
		const calls: RequestInit[] = [];
		const fetchImpl = async (_url: RequestInfo | URL, init?: RequestInit) => {
			calls.push(init ?? {});
			return sseResponse([frame("worry.updated", { worry_id: "w_1" })]);
		};
		const stream = createEventStream({
			url: "/api/events",
			getToken: () => "tok",
			onUnauthorized: () => {},
			fetchImpl,
			backoffMs: () => 0,
		});
		const seen: LiveEvent[] = [];
		const off = stream.subscribe((e) => seen.push(e));
		await tick();
		off();

		expect(calls.length).toBeGreaterThanOrEqual(2); // it reconnected
		expect(new Headers(calls[0]?.headers).get("authorization")).toBe(
			"Bearer tok",
		);
		expect(seen.slice(0, 3)).toEqual([
			{ type: "connected" },
			{ type: "worry.updated", data: { worry_id: "w_1" } },
			{ type: "connected" },
		]);
	});

	it("stops and reports on 401", async () => {
		let unauthorized = 0;
		let calls = 0;
		const stream = createEventStream({
			url: "/api/events",
			getToken: () => "bad",
			onUnauthorized: () => {
				unauthorized += 1;
			},
			fetchImpl: async () => {
				calls += 1;
				return new Response(null, { status: 401 });
			},
			backoffMs: () => 0,
		});
		const off = stream.subscribe(() => {});
		await tick();
		off();
		expect(calls).toBe(1);
		expect(unauthorized).toBe(1);
	});

	it("keeps backing off when the stream drops straight after connecting", async () => {
		const attempts: number[] = [];
		const stream = createEventStream({
			url: "/api/events",
			getToken: () => "tok",
			onUnauthorized: () => {},
			fetchImpl: async () => sseResponse([]),
			backoffMs: (n) => {
				attempts.push(n);
				return 0;
			},
		});
		const off = stream.subscribe(() => {});
		await tick();
		off();
		expect(attempts.slice(0, 3)).toEqual([0, 1, 2]);
	});

	it("backs off and retries after a network error", async () => {
		const attempts: number[] = [];
		let calls = 0;
		const stream = createEventStream({
			url: "/api/events",
			getToken: () => "tok",
			onUnauthorized: () => {},
			fetchImpl: async () => {
				calls += 1;
				throw new TypeError("network down");
			},
			backoffMs: (n) => {
				attempts.push(n);
				return 0;
			},
		});
		const off = stream.subscribe(() => {});
		await tick();
		off();
		expect(calls).toBeGreaterThanOrEqual(3);
		expect(attempts.slice(0, 3)).toEqual([0, 1, 2]);
	});
});
