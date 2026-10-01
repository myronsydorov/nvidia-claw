import { z } from "zod";
import type { Api } from "./client";
import type { EventStream } from "./events";
import {
	askPeerResponseSchema,
	healthResponseSchema,
	ledgerResponseSchema,
	pairingStartResponseSchema,
	pairingStatusResponseSchema,
	peerSchema,
	peopleListItemSchema,
	sharingRulesResponseSchema,
	type WorryDetail,
	worryDetailSchema,
	worrySchema,
	worrySummarySchema,
} from "./schemas";

// The real client for the Warden's /api (docs/CONTRACTS.md §3). Every response
// is parsed with the contract's zod schema, so drift fails loudly here.

export class ApiError extends Error {
	readonly status: number;
	constructor(status: number, message: string) {
		super(message);
		this.name = "ApiError";
		this.status = status;
	}
}

const noContent = z.undefined();

export type HttpApiOptions = {
	baseUrl?: string;
	getToken: () => string | null;
	onUnauthorized: () => void;
	events: EventStream;
	fetchImpl?: typeof fetch;
	/** How long a hand-over may take to reach the permission card. */
	/** How often a settling hand-over is re-read besides live events (default 15 s). */
	pollMs?: number;
};

export function createHttpApi(opts: HttpApiOptions): Api {
	const base = opts.baseUrl ?? "";
	const doFetch = opts.fetchImpl ?? ((...a) => fetch(...a));

	async function request<S extends z.ZodType>(
		method: "GET" | "POST" | "PUT" | "DELETE",
		path: string,
		schema: S,
		body?: unknown,
	): Promise<z.infer<S>> {
		const token = opts.getToken();
		if (!token) {
			opts.onUnauthorized();
			throw new ApiError(401, "no device token");
		}
		const headers: Record<string, string> = {
			Authorization: `Bearer ${token}`,
		};
		if (body !== undefined) headers["Content-Type"] = "application/json";
		const res = await doFetch(`${base}${path}`, {
			method,
			headers,
			body: body === undefined ? undefined : JSON.stringify(body),
		});
		if (res.status === 401) {
			opts.onUnauthorized();
			throw new ApiError(401, "invalid device token");
		}
		if (!res.ok) throw new ApiError(res.status, `${method} ${path}`);
		if (res.status === 204) return schema.parse(undefined);
		return schema.parse(await res.json());
	}

	const getWorry = (id: string) =>
		request("GET", `/api/worries/${encodeURIComponent(id)}`, worryDetailSchema);
	const post = (id: string, action: string) =>
		request(
			"POST",
			`/api/worries/${encodeURIComponent(id)}/${action}`,
			worryDetailSchema,
		);

	/**
	 * Follow a worry until its hand-over settles: a permission card, parked, failed, or let go.
	 * Event-driven with a slow poll as a safety net. There is deliberately no timeout: building
	 * a watcher can take minutes, and giving up early once told the person "nothing was set up"
	 * while the Warden was still working (S7 incident). Transient read errors are retried.
	 */
	function untilSettled(id: string): Promise<WorryDetail> {
		return new Promise((resolve) => {
			let done = false;
			const finish = (d: WorryDetail) => {
				if (done) return;
				done = true;
				unsubscribe();
				clearInterval(poll);
				resolve(d);
			};
			const check = async () => {
				try {
					const d = await getWorry(id);
					const s = d.worry.status;
					if (s !== "triaging" && s !== "compiling") finish(d);
				} catch {
					// keep following; the next event or poll tries again
				}
			};
			const unsubscribe = opts.events.subscribe((e) => {
				if (e.type === "connected" || e.data.worry_id === id) void check();
			});
			const poll = setInterval(() => void check(), opts.pollMs ?? 15_000);
			void check();
		});
	}

	return {
		listWorries: () =>
			request("GET", "/api/worries", worrySummarySchema.array()),
		getWorry,
		async handOver(text) {
			const worry = await request("POST", "/api/worries", worrySchema, {
				text,
			});
			return untilSettled(worry.id);
		},
		async retry(id) {
			await post(id, "retry");
			return untilSettled(id);
		},
		approve: (id) => post(id, "approve"),
		deny: (id) => post(id, "deny"),
		letGo: (id) => post(id, "let-go"),
		listPeople: () =>
			request("GET", "/api/people", peopleListItemSchema.array()),
		ask: (peerId, q) =>
			request(
				"POST",
				`/api/people/${encodeURIComponent(peerId)}/ask`,
				askPeerResponseSchema,
				{ q },
			),
		async confirm(peerId) {
			await request(
				"POST",
				`/api/people/${encodeURIComponent(peerId)}/confirm`,
				noContent,
			);
		},
		async unpair(peerId) {
			await request(
				"DELETE",
				`/api/people/${encodeURIComponent(peerId)}`,
				noContent,
			);
		},
		startPairing: (displayName) =>
			request("POST", "/api/pairing", pairingStartResponseSchema, {
				display_name: displayName,
			}),
		pairingStatus: (pairingId) =>
			request(
				"GET",
				`/api/pairing/${encodeURIComponent(pairingId)}`,
				pairingStatusResponseSchema,
			),
		joinPairing: (code, displayName) =>
			request("POST", "/api/pairing/join", peerSchema, {
				code,
				display_name: displayName,
			}),
		getSharingRules: () =>
			request("GET", "/api/sharing-rules", sharingRulesResponseSchema),
		putSharingRules: (body) =>
			request("PUT", "/api/sharing-rules", sharingRulesResponseSchema, body),
		getLedger: () => request("GET", "/api/ledger", ledgerResponseSchema),
		subscribe: (listener) => opts.events.subscribe(listener),
	};
}

/** True if the Warden accepts this device token (GET /api/health). */
export async function verifyToken(
	token: string,
	fetchImpl: typeof fetch = (...a) => fetch(...a),
): Promise<boolean> {
	const res = await fetchImpl("/api/health", {
		headers: { Authorization: `Bearer ${token}` },
	});
	if (res.status === 401) return false;
	if (!res.ok) throw new ApiError(res.status, "GET /api/health");
	healthResponseSchema.parse(await res.json());
	return true;
}
