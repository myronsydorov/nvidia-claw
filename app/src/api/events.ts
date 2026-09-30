import { type Event, eventSchema } from "./schemas";

// Live updates from GET /api/events (docs/CONTRACTS.md §3). EventSource can't
// send the bearer device token, so this reads the stream over fetch.

/** A contract event, or our own signal that the stream (re)connected, so any
 *  screen can refetch what it might have missed while disconnected. */
export type LiveEvent = Event | { type: "connected" };
export type Listener = (event: LiveEvent) => void;

/** Split complete `\n\n`-terminated SSE frames off the buffer. */
export function parseSse(buffer: string): { events: Event[]; rest: string } {
	const text = buffer.replace(/\r\n/g, "\n");
	const frames = text.split("\n\n");
	const rest = frames.pop() ?? "";
	const events: Event[] = [];
	for (const frame of frames) {
		let type = "message";
		const data: string[] = [];
		for (const line of frame.split("\n")) {
			if (line.startsWith(":")) continue;
			const colon = line.indexOf(":");
			const field = colon < 0 ? line : line.slice(0, colon);
			const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
			if (field === "event") type = value;
			else if (field === "data") data.push(value);
		}
		if (data.length === 0) continue;
		try {
			const parsed = eventSchema.safeParse({
				type,
				data: JSON.parse(data.join("\n")),
			});
			if (parsed.success) events.push(parsed.data);
		} catch {
			// Not JSON: not a contract event. Drop it.
		}
	}
	return { events, rest };
}

export type EventStreamOptions = {
	url: string;
	getToken: () => string | null;
	onUnauthorized: () => void;
	fetchImpl?: typeof fetch;
	/** Backoff before reconnect attempt n (0-based). */
	backoffMs?: (attempt: number) => number;
};

export const defaultBackoff = (attempt: number) =>
	Math.min(30_000, 1000 * 2 ** attempt) * (0.5 + Math.random() / 2);

export type EventStream = {
	subscribe(listener: Listener): () => void;
};

/** One shared connection, opened with the first listener and closed with the last. */
export function createEventStream(opts: EventStreamOptions): EventStream {
	const listeners = new Set<Listener>();
	const doFetch = opts.fetchImpl ?? ((...a) => fetch(...a));
	const backoff = opts.backoffMs ?? defaultBackoff;
	let controller: AbortController | null = null;

	const emit = (e: LiveEvent) => {
		for (const l of [...listeners]) l(e);
	};

	async function run(ctl: AbortController) {
		let attempt = 0;
		while (!ctl.signal.aborted) {
			const token = opts.getToken();
			if (!token) break;
			try {
				const res = await doFetch(opts.url, {
					headers: {
						Accept: "text/event-stream",
						Authorization: `Bearer ${token}`,
					},
					signal: ctl.signal,
				});
				if (res.status === 401) {
					opts.onUnauthorized();
					break;
				}
				if (!res.ok || !res.body) throw new Error(`events: ${res.status}`);
				attempt = 0;
				emit({ type: "connected" });
				const reader = res.body
					.pipeThrough(new TextDecoderStream())
					.getReader();
				let buffer = "";
				for (;;) {
					const { value, done } = await reader.read();
					if (done) break;
					const parsed = parseSse(buffer + value);
					buffer = parsed.rest;
					for (const e of parsed.events) emit(e);
				}
			} catch {
				if (ctl.signal.aborted) break;
			}
			if (ctl.signal.aborted) break;
			await new Promise((r) => setTimeout(r, backoff(attempt)));
			attempt += 1;
		}
		if (controller === ctl) controller = null;
	}

	return {
		subscribe(listener) {
			listeners.add(listener);
			if (!controller) {
				controller = new AbortController();
				void run(controller);
			}
			return () => {
				listeners.delete(listener);
				if (listeners.size === 0 && controller) {
					controller.abort();
					controller = null;
				}
			};
		},
	};
}
