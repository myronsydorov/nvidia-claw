import { navigate } from "../lib/router";
import { clearToken, getToken } from "../lib/token";
import {
	buildDetail,
	initialDetails,
	iso,
	pickTemplate,
} from "../mocks/fixtures";
import {
	DAD,
	initialLedger,
	initialPeople,
	initialQuestionLog,
	initialRules,
	mockAnswer,
	mockPeer,
} from "../mocks/people";
import { createEventStream, type Listener } from "./events";
import { ApiError, createHttpApi } from "./http";
import {
	type AskPeerResponse,
	askPeerResponseSchema,
	type LedgerResponse,
	type PairingStartResponse,
	type PairingStatusResponse,
	type Peer,
	type PeopleListItem,
	pairingStartResponseSchema,
	pairingStatusResponseSchema,
	peerSchema,
	peopleListItemSchema,
	type ReassuranceAnswer,
	type ReassuranceQuestion,
	type SharingRulesResponse,
	sharingRulesResponseSchema,
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
	/** Hand a worry over. Resolves once it settles, whatever the outcome: awaiting approval
	 *  (with a watcher), parked, failed (the resolution names the phase) or let go. Rejects
	 *  only if the worry couldn't be handed over at all. */
	handOver(text: string): Promise<WorryDetail>;
	/** Build a `failed` worry again; resolves once it settles, like handOver. */
	retry(id: string): Promise<WorryDetail>;
	approve(id: string): Promise<WorryDetail>;
	deny(id: string): Promise<WorryDetail>;
	letGo(id: string): Promise<WorryDetail>;
	/** Paired people and their last answer (GET /api/people). */
	listPeople(): Promise<PeopleListItem[]>;
	/** Ask a paired person's Warden a fixed-vocabulary question. Rejects with an
	 *  ApiError: 429 within the 10-minute cooldown, 503 no relay, 504 no answer in
	 *  time, 502 an answer outside the vocabulary (discarded). */
	ask(peerId: string, q: ReassuranceQuestion): Promise<AskPeerResponse>;
	/** The fingerprints matched: my sharing rule for them takes effect. */
	confirm(peerId: string): Promise<void>;
	/** Forget a paired person (e.g. the fingerprints didn't match). */
	unpair(peerId: string): Promise<void>;
	/** Show a one-time code; `displayName` is what I call them. */
	startPairing(displayName: string): Promise<PairingStartResponse>;
	/** The code-showing side waits on this until the other phone has joined. */
	pairingStatus(pairingId: string): Promise<PairingStatusResponse>;
	/** Type the other phone's code. */
	joinPairing(code: string, displayName: string): Promise<Peer>;
	/** What others may ask about me, plus the log of what they asked. */
	getSharingRules(): Promise<SharingRulesResponse>;
	/** Replaces the full rules list; the log is server-maintained. */
	putSharingRules(body: SharingRulesResponse): Promise<SharingRulesResponse>;
	getLedger(): Promise<LedgerResponse>;
	/** What an allowed person asking "Are you OK?" would hear right now. */
	mySignal(): Promise<ReassuranceAnswer>;
	/** "I'm OK": answers "Normal day" for the next 3 hours and clears "I need help". */
	checkIn(): Promise<void>;
	/** Set or clear "I need help". */
	setHelp(on: boolean): Promise<void>;
	/** Live updates (GET /api/events). Returns an unsubscribe function. */
	subscribe(listener: Listener): () => void;
}

const ASK_COOLDOWN_MS = 10 * 60_000;
const MOCK_JOIN_AFTER_MS = 2_500;

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

	let people = initialPeople();
	const pairings = new Map<
		string,
		{ name: string; startedAt: number; peer: Peer | null }
	>();
	let sharing: SharingRulesResponse = {
		rules: initialRules(),
		questions_log: initialQuestionLog(),
	};

	let checkedInAt: number | null = null;
	let help = false;

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
		async retry(id) {
			await wait(latencyMs * 4);
			return update(id, (d) => {
				const now = iso(0);
				// Like the Warden: a fresh build yields a watcher awaiting approval.
				const rebuilt = buildDetail(d.worry.text, pickTemplate(d.worry.text), {
					status: "awaiting_approval",
					createdAgoMs: 0,
					checkedAgoMs: null,
				});
				d.watcher = rebuilt.watcher
					? { ...rebuilt.watcher, worry_id: d.worry.id }
					: null;
				d.worry.watcher_id = d.watcher?.id ?? null;
				d.worry.status = "awaiting_approval";
				d.worry.resolution = null;
				d.worry.updated_at = now;
				d.timeline.push({
					at: now,
					kind: "retried",
					text: "You asked me to try again.",
				});
				return d;
			});
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
		async listPeople() {
			await wait(latencyMs);
			return peopleListItemSchema.array().parse(people);
		},
		async ask(peerId, q) {
			// A round trip through the relay to the peer's Warden and back.
			await wait(latencyMs * 3.6);
			const person = people.find((p) => p.peer.id === peerId);
			if (!person) throw new ApiError(404, "peer not found");
			// Like the Warden: one ask per person per 10 minutes...
			const last = person.last_asked_at ?? person.last_answer_at;
			if (last && Date.now() - Date.parse(last) < ASK_COOLDOWN_MS) {
				throw new ApiError(429, "asked less than the cooldown ago");
			}
			// ...counted from when the question leaves, answered or not.
			const askedAt = new Date().toISOString();
			people = people.map((p) =>
				p.peer.id === peerId ? { ...p, last_asked_at: askedAt } : p,
			);
			// Dad's computer is asleep: his Warden never answers (the 504 path).
			if (peerId === DAD) throw new ApiError(504, "no answer in time");
			const res = askPeerResponseSchema.parse(mockAnswer(q));
			people = people.map((p) =>
				p.peer.id === peerId
					? { ...p, last_answer: res.answer, last_answer_at: res.answer.ts }
					: p,
			);
			for (const l of [...listeners]) {
				l({ type: "peer.answer", data: { peer_id: peerId, q } });
			}
			return res;
		},
		async confirm(peerId) {
			await wait(latencyMs);
			if (!people.some((p) => p.peer.id === peerId)) {
				throw new ApiError(404, "peer not found");
			}
		},
		async unpair(peerId) {
			await wait(latencyMs);
			if (!people.some((p) => p.peer.id === peerId)) {
				throw new ApiError(404, "peer not found");
			}
			people = people.filter((p) => p.peer.id !== peerId);
			sharing = {
				...sharing,
				rules: sharing.rules.filter((r) => r.peer_id !== peerId),
			};
		},
		async startPairing(displayName) {
			await wait(latencyMs * 2);
			const res = pairingStartResponseSchema.parse({
				pairing_id: `pr_01K6C0PA1R${String(pairings.size).padStart(16, "0")}`,
				code: "K7M2Q9XA",
				expires_at: iso(10 * 60_000),
			});
			pairings.set(res.pairing_id, {
				name: displayName,
				startedAt: Date.now(),
				peer: null,
			});
			return res;
		},
		async pairingStatus(pairingId) {
			await wait(latencyMs);
			const p = pairings.get(pairingId);
			if (!p) return { state: "expired", peer: null };
			// The other phone "joins" a few seconds after the code is shown.
			if (!p.peer && Date.now() - p.startedAt > MOCK_JOIN_AFTER_MS) {
				p.peer = mockPeer(people.length, p.name);
				people = [
					...people,
					{
						peer: p.peer,
						last_answer: null,
						last_answer_at: null,
						last_asked_at: null,
					},
				];
			}
			return pairingStatusResponseSchema.parse({
				state: p.peer ? "paired" : "waiting",
				peer: p.peer,
			});
		},
		async joinPairing(code, displayName) {
			await wait(latencyMs * 3);
			const normal = code.toUpperCase().replace(/[\s-]/g, "");
			if (!/^[0-9A-HJKMNP-TV-Z]{8}$/.test(normal)) {
				throw new ApiError(422, "a pairing code is 8 characters");
			}
			if (normal === "K7M2Q9XA") {
				throw new ApiError(409, "that code is this Warden's own");
			}
			const peer = peerSchema.parse(mockPeer(people.length, displayName));
			people = [
				...people,
				{
					peer,
					last_answer: null,
					last_answer_at: null,
					last_asked_at: null,
				},
			];
			return peer;
		},
		async getSharingRules() {
			await wait(latencyMs);
			return sharingRulesResponseSchema.parse(sharing);
		},
		async putSharingRules(body) {
			await wait(latencyMs);
			// Like the Warden: only `rules` is replaced; the log is read-only.
			sharing = sharingRulesResponseSchema.parse({
				rules: structuredClone(body.rules),
				questions_log: sharing.questions_log,
			});
			return sharing;
		},
		async getLedger() {
			await wait(latencyMs);
			return initialLedger();
		},
		async mySignal() {
			await wait(latencyMs);
			const ts = new Date().toISOString();
			if (help) return { level: "help", reason: "asked_for_help", ts };
			if (checkedInAt && Date.now() - checkedInAt < 3 * 3_600_000)
				return { level: "normal", reason: "active_as_usual", ts };
			return { level: "unknown", reason: "not_enough_data", ts };
		},
		async checkIn() {
			await wait(latencyMs);
			checkedInAt = Date.now();
			help = false;
		},
		async setHelp(on) {
			await wait(latencyMs);
			help = on;
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
