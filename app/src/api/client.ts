import { navigate } from "../lib/router";
import { clearToken, getToken } from "../lib/token";
import {
	buildDetail,
	initialDetails,
	iso,
	pickTemplate,
} from "../mocks/fixtures";
import { createEventStream, type Listener } from "./events";
import { createHttpApi } from "./http";
import {
	type WorryDetail,
	type WorrySummary,
	worryDetailSchema,
	worrySummarySchema,
} from "./schemas";

// The app's view of the Warden's /api (docs/CONTRACTS.md §3): the HTTP client
// in ./http.ts, or this in-memory mock when VITE_API_MODE=mock (`pnpm dev:mock`).
export interface Api {
	listWorries(): Promise<WorrySummary[]>;
	getWorry(id: string): Promise<WorryDetail>;
	/** Hand a worry over. Resolves once the watcher awaits approval. */
	handOver(text: string): Promise<WorryDetail>;
	approve(id: string): Promise<WorryDetail>;
	deny(id: string): Promise<WorryDetail>;
	letGo(id: string): Promise<WorryDetail>;
	/** Live updates (GET /api/events). Returns an unsubscribe function. */
	subscribe(listener: Listener): () => void;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createMockApi(latencyMs = 250): Api {
	const store = new Map<string, WorryDetail>(
		initialDetails().map((d) => [d.worry.id, d]),
	);

	function get(id: string): WorryDetail {
		const d = store.get(id);
		if (!d) throw new Error(`unknown worry ${id}`);
		return d;
	}

	const listeners = new Set<Listener>();
	function changed(id: string) {
		for (const l of [...listeners]) {
			l({ type: "worry.updated", data: { worry_id: id } });
		}
	}

	function update(
		id: string,
		change: (d: WorryDetail) => WorryDetail,
	): WorryDetail {
		const next = worryDetailSchema.parse(change(structuredClone(get(id))));
		store.set(id, next);
		changed(id);
		return next;
	}

	return {
		async listWorries() {
			await wait(latencyMs);
			// Like the Warden: every worry, resolved ones included.
			return [...store.values()].map((d) =>
				worrySummarySchema.parse({
					worry: d.worry,
					last_result: d.watcher?.last_result ?? null,
				}),
			);
		},
		async getWorry(id) {
			await wait(latencyMs);
			return get(id);
		},
		async handOver(text) {
			await wait(latencyMs * 4);
			const d = buildDetail(text, pickTemplate(text), {
				status: "awaiting_approval",
				createdAgoMs: 0,
				checkedAgoMs: null,
			});
			store.set(d.worry.id, d);
			changed(d.worry.id);
			return d;
		},
		async approve(id) {
			await wait(latencyMs);
			return update(id, (d) => {
				const now = iso(0);
				d.worry.status = "watching";
				d.worry.updated_at = now;
				if (d.watcher) d.watcher.state = "active";
				d.timeline.push({
					at: now,
					kind: "approved",
					text: "You allowed it. Watching quietly.",
				});
				return d;
			});
		},
		async deny(id) {
			await wait(latencyMs);
			return update(id, (d) => {
				const now = iso(0);
				d.worry.status = "parked";
				d.worry.updated_at = now;
				d.worry.resolution = "You said no. Saved for worry time.";
				if (d.watcher) d.watcher.state = "retired";
				d.timeline.push({ at: now, kind: "denied", text: "You said no." });
				return d;
			});
		},
		async letGo(id) {
			await wait(latencyMs);
			return update(id, (d) => {
				const now = iso(0);
				d.worry.status = "resolved";
				d.worry.updated_at = now;
				d.worry.resolution = "You let it go.";
				if (d.watcher) d.watcher.state = "retired";
				d.timeline.push({ at: now, kind: "let_go", text: "You let it go." });
				return d;
			});
		},
		subscribe(listener) {
			listeners.add(listener);
			return () => listeners.delete(listener);
		},
	};
}

export const mockMode = import.meta.env.VITE_API_MODE === "mock";

function onUnauthorized() {
	clearToken();
	navigate({ name: "connect" });
}

export const api: Api = mockMode
	? createMockApi()
	: createHttpApi({
			getToken,
			onUnauthorized,
			events: createEventStream({
				url: "/api/events",
				getToken,
				onUnauthorized,
			}),
		});
