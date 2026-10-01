import {
	type LedgerResponse,
	ledgerResponseSchema,
	type Peer,
	type PeopleListItem,
	type PrivacyReceipt,
	peerSchema,
	peopleListItemSchema,
	privacyReceiptSchema,
	type QuestionLogEntry,
	questionLogEntrySchema,
	type ReassuranceAnswer,
	type ReassuranceQuestion,
	reassuranceAnswerSchema,
	type SharingRule,
	sharingRuleSchema,
} from "../api/schemas";
import { iso } from "./fixtures";

// Mock data for T-17 (Layer 2 + Ledger). Every record is parsed through the
// contract schemas, so drift from docs/CONTRACTS.md fails loudly.

const MIN = 60_000;
const HOUR = 60 * MIN;

export const ANNA = "p_01K6C0ANNA0000000000000001";
export const DAD = "p_01K6C0DAD00000000000000002";

/** Every mock pairing shows this on "both" screens. */
export const MOCK_FINGERPRINT = "4821 0937";

// Placeholder X25519 keys (base64, 32 bytes of nothing in particular).
const fakeKey = (seed: string) => btoa(seed.padEnd(32, ".")).slice(0, 43);

export function initialPeople(now: number = Date.now()): PeopleListItem[] {
	return peopleListItemSchema.array().parse([
		{
			peer: {
				id: ANNA,
				display_name: "Anna",
				public_key: fakeKey("anna"),
				paired_at: iso(-9 * 24 * HOUR, now),
				fingerprint: "1593 2604",
			},
			last_answer: {
				level: "normal",
				reason: "active_as_usual",
				ts: iso(-3 * HOUR, now),
			},
			last_answer_at: iso(-3 * HOUR, now),
			last_asked_at: iso(-3 * HOUR, now),
		},
		{
			peer: {
				id: DAD,
				display_name: "Dad",
				public_key: fakeKey("dad"),
				paired_at: iso(-4 * 24 * HOUR, now),
				fingerprint: "7718 0452",
			},
			last_answer: null,
			last_answer_at: null,
			last_asked_at: null,
		},
	]);
}

/** A newly paired mock person. */
export function mockPeer(
	n: number,
	name: string,
	now: number = Date.now(),
): Peer {
	return peerSchema.parse({
		id: `p_01K6C0NEW${String(n).padStart(17, "0")}`,
		display_name: name,
		public_key: fakeKey(`new${n}`),
		paired_at: iso(0, now),
		fingerprint: MOCK_FINGERPRINT,
	});
}

export function initialRules(): SharingRule[] {
	return sharingRuleSchema.array().parse([
		{
			peer_id: ANNA,
			allowed_questions: ["ok", "home"],
			allowed_levels: ["normal", "unusual", "help", "unknown"],
			active: true,
		},
		{
			peer_id: DAD,
			allowed_questions: ["ok"],
			allowed_levels: ["normal", "unusual", "help", "unknown"],
			active: true,
		},
	]);
}

/** Questions others asked about me, newest first. */
export function initialQuestionLog(
	now: number = Date.now(),
): QuestionLogEntry[] {
	return questionLogEntrySchema.array().parse([
		{
			id: "q_3",
			peer_id: ANNA,
			question: "home",
			asked_at: iso(-50 * MIN, now),
			answer_level: "normal",
		},
		{
			id: "q_2",
			peer_id: DAD,
			question: "ok",
			asked_at: iso(-26 * HOUR, now),
			answer_level: "normal",
		},
		{
			id: "q_1",
			peer_id: ANNA,
			question: "ok",
			asked_at: iso(-3 * 24 * HOUR, now),
			answer_level: "unusual",
		},
	]);
}

/** What a peer's Warden sends back: fixed vocabulary only. */
export function mockAnswer(
	q: ReassuranceQuestion,
	now: number = Date.now(),
): { answer: ReassuranceAnswer; receipt: PrivacyReceipt } {
	const answer = reassuranceAnswerSchema.parse(
		q === "home"
			? { level: "normal", reason: "arrived", ts: iso(0, now) }
			: { level: "normal", reason: "active_as_usual", ts: iso(0, now) },
	);
	const receipt = privacyReceiptSchema.parse({
		bytes_sent: 212,
		fields_shared: ["level", "reason", "ts"],
		location_shared: false,
		egress_log_ref: `egress/${new Date(now).toISOString().slice(0, 10)}#${Math.floor(now / 1000) % 100000}`,
	});
	return { answer, receipt };
}

/** A few weeks of use: 19 worries with a known outcome, 2 came true. */
export function initialLedger(): LedgerResponse {
	return ledgerResponseSchema.parse({
		worries_total: 23,
		active: 3,
		never_needed_you: 17,
		needed_you: 2,
		median_warning_lead_h: 31.5,
		came_true_rate: 2 / 19,
		came_true_by_type: { checkable: 1 / 9, deadline: 1 / 8, person: 0 },
		watchers_built: 21,
		sandboxes_live: 3,
		endpoints_denied: 7,
		peer_questions_answered: 12,
		locations_shared: 0,
	});
}
