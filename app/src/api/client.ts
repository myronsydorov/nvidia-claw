import {
	buildDetail,
	initialDetails,
	iso,
	pickTemplate,
} from "../mocks/fixtures";
import {
	type WorryDetail,
	type WorrySummary,
	worryDetailSchema,
	worrySummarySchema,
} from "./schemas";

// The app's view of the Warden's /api (docs/CONTRACTS.md §3).
// T-05 ships only the in-memory mock; T-12 adds the HTTP implementation.
export interface Api {
	listWorries(): Promise<WorrySummary[]>;
	getWorry(id: string): Promise<WorryDetail>;
	/** Hand a worry over. Resolves once the watcher awaits approval. */
	handOver(text: string): Promise<WorryDetail>;
	approve(id: string): Promise<WorryDetail>;
	deny(id: string): Promise<WorryDetail>;
	letGo(id: string): Promise<WorryDetail>;
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

	function update(
		id: string,
		change: (d: WorryDetail) => WorryDetail,
	): WorryDetail {
		const next = worryDetailSchema.parse(change(structuredClone(get(id))));
		store.set(id, next);
		return next;
	}

	return {
		async listWorries() {
			await wait(latencyMs);
			return [...store.values()]
				.filter((d) => d.worry.status !== "resolved")
				.map((d) =>
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
	};
}

export const api: Api = createMockApi();
