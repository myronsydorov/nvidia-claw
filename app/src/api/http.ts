import type { z } from "zod";
import type { Api } from "./client";
import type { EventStream } from "./events";
import {
	askPeerResponseSchema,
	healthResponseSchema,
	ledgerResponseSchema,
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

export type HttpApiOptions = {
	baseUrl?: string;
	getToken: () => string | null;
	onUnauthorized: () => void;
	events: EventStream;
	fetchImpl?: typeof fetch;
	/** How long a hand-over may take to reach the permission card. */
	handOverTimeoutMs?: number;
};

export function createHttpApi(opts: HttpApiOptions): Api {
	const base = opts.baseUrl ?? "";
	const doFetch = opts.fetchImpl ?? ((...a) => fetch(...a));

	async function request<S extends z.ZodType>(
		method: "GET" | "POST" | "PUT",
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

	/** Wait, event-driven, until the Warden has a watcher awaiting approval. */
	function untilAwaitingApproval(id: string): Promise<WorryDetail> {
		return new Promise((resolve, reject) => {
			let done = false;
			const finish = (settle: () => void) => {
				if (done) return;
				done = true;
				unsubscribe();
				clearTimeout(timer);
				settle();
			};
			const check = async () => {
				try {
					const d = await getWorry(id);
					const s = d.worry.status;
					if (s === "awaiting_approval" && d.watcher) {
						finish(() => resolve(d));
					} else if (s === "failed" || s === "parked" || s === "resolved") {
						finish(() => reject(new Error(`hand-over ended as ${s}`)));
					}
				} catch (e) {
					finish(() => reject(e));
				}
			};
			const unsubscribe = opts.events.subscribe((e) => {
				if (e.type === "connected" || e.data.worry_id === id) void check();
			});
			const timer = setTimeout(
				() => finish(() => reject(new Error("hand-over timed out"))),
				opts.handOverTimeoutMs ?? 60_000,
			);
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
			return untilAwaitingApproval(worry.id);
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
