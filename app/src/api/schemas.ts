import { z } from "zod";

// Mirrors warden/src/warden/models.py (docs/CONTRACTS.md). Change the contract first.

const ULID = "[0-9A-HJKMNP-TV-Z]{26}";
const worryId = z.string().regex(new RegExp(`^w_${ULID}$`));
const watcherId = z.string().regex(new RegExp(`^wt_${ULID}$`));
const datetime = z.iso.datetime({ offset: true });

export const healthResponseSchema = z.object({
	status: z.literal("ok"),
	sandboxes_live: z.number().int(),
});

// "unclassified" is T-07's addition: the pre-triage placeholder POST /api/worries sets.
export const worryTypeSchema = z.enum([
	"unclassified",
	"checkable",
	"deadline",
	"person",
	"social",
	"uncontrollable",
]);

export const worryStatusSchema = z.enum([
	"triaging",
	"compiling",
	"awaiting_approval",
	"watching",
	"needs_you",
	"resolved",
	"parked",
	"failed",
]);

export const worrySchema = z.object({
	id: worryId,
	text: z.string(),
	type: worryTypeSchema,
	fear: z.string(),
	deadline: datetime.nullable(),
	status: worryStatusSchema,
	watcher_id: watcherId.nullable(),
	resolution: z.string().nullable(),
	fear_came_true: z.boolean().nullable(),
	created_at: datetime,
	updated_at: datetime,
});

export const permissionLineSchema = z.object({
	method: z.literal("GET"),
	host: z.string(),
	path: z.string(),
	why: z.string(),
});

export const watchResultSchema = z.object({
	status: z.enum(["ok", "act_now", "resolved", "error"]),
	summary: z.string().max(140),
	evidence: z.object({
		source: z.string(),
		checked_at: datetime,
		data: z.record(z.string(), z.unknown()),
	}),
	fear_came_true: z.boolean().nullable(),
	next_check_s: z.number().int(),
});

export const watcherSchema = z.object({
	id: watcherId,
	worry_id: worryId,
	adapters: z.array(z.string()),
	code: z.string(),
	policy_yaml: z.string(),
	policy_summary: z.array(permissionLineSchema),
	sandbox_name: z.string().regex(/^cw-[a-z0-9-]{1,16}$/),
	interval_s: z.number().int().min(300).max(86400),
	state: z.enum([
		"draft",
		"dry_run_failed",
		"awaiting_approval",
		"active",
		"paused",
		"retired",
	]),
	last_result: watchResultSchema.nullable(),
});

export const timelineEventSchema = z.object({
	at: datetime,
	kind: z.enum([
		"created",
		"triaged",
		"compiled",
		"approval_requested",
		"approved",
		"denied",
		"checked",
		"act_now",
		"resolved",
		"let_go",
		"retried",
		"parked",
		"failed",
		"test",
	]),
	text: z.string().max(140),
});

export const worrySummarySchema = z.object({
	worry: worrySchema,
	last_result: watchResultSchema.nullable(),
});

export const worryDetailSchema = z.object({
	worry: worrySchema,
	watcher: watcherSchema.nullable(),
	timeline: z.array(timelineEventSchema),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;
export type WorryStatus = z.infer<typeof worryStatusSchema>;
export type Worry = z.infer<typeof worrySchema>;
export type PermissionLine = z.infer<typeof permissionLineSchema>;
export type WatchResult = z.infer<typeof watchResultSchema>;
export type Watcher = z.infer<typeof watcherSchema>;
export type TimelineEvent = z.infer<typeof timelineEventSchema>;
export type WorrySummary = z.infer<typeof worrySummarySchema>;
export type WorryDetail = z.infer<typeof worryDetailSchema>;

// --- T-07 additions below: request bodies, reassurance/people, sharing rules, ledger, events ---

const peerId = z.string().regex(new RegExp(`^p_${ULID}$`));

export const worryCreateRequestSchema = z.object({
	text: z.string(),
});

export const outcomeRequestSchema = z.object({
	fear_came_true: z.boolean(),
});

export const reassuranceQuestionSchema = z.enum(["ok", "home"]);

export const reassuranceLevelSchema = z.enum([
	"normal",
	"unusual",
	"help",
	"unknown",
]);

export const reassuranceReasonSchema = z.enum([
	"active_as_usual",
	"quieter_than_usual",
	"do_not_disturb",
	"asked_for_help",
	"not_enough_data",
	"arrived",
	"not_arrived",
]);

export const peerSchema = z.object({
	id: peerId,
	display_name: z.string(),
	public_key: z.string(),
	paired_at: datetime,
	/** Same 8 digits on both devices; the humans compare them after pairing. */
	fingerprint: z.string().regex(/^[0-9]{4} [0-9]{4}$/),
});

// Pairing (CONTRACTS §2/§3, T-14).
const pairingCode = z.string().regex(/^[0-9A-HJKMNP-TV-Z]{8}$/);

export const pairingStartRequestSchema = z.object({
	display_name: z.string().min(1).max(64),
});

export const pairingStartResponseSchema = z.object({
	pairing_id: z.string().regex(new RegExp(`^pr_${ULID}$`)),
	code: pairingCode,
	expires_at: datetime,
});

export const pairingStatusResponseSchema = z.object({
	state: z.enum(["waiting", "paired", "expired"]),
	peer: peerSchema.nullable(),
});

export const pairingJoinRequestSchema = z.object({
	code: z.string().min(8).max(16),
	display_name: z.string().min(1).max(64),
});

export const reassuranceAnswerSchema = z.object({
	level: reassuranceLevelSchema,
	reason: reassuranceReasonSchema,
	ts: datetime,
});

export const privacyReceiptSchema = z.object({
	bytes_sent: z.number().int(),
	fields_shared: z.array(z.string()),
	location_shared: z.boolean(),
	egress_log_ref: z.string(),
});

export const peopleListItemSchema = z.object({
	peer: peerSchema,
	last_answer: reassuranceAnswerSchema.nullable(),
	last_answer_at: datetime.nullable(),
	/** When I last asked, answered or not: the 10-minute cooldown runs from here. */
	last_asked_at: datetime.nullable(),
});

export const askPeerRequestSchema = z.object({
	q: reassuranceQuestionSchema,
});

export const askPeerResponseSchema = z.object({
	answer: reassuranceAnswerSchema,
	receipt: privacyReceiptSchema,
});

export const sharingRuleSchema = z.object({
	peer_id: peerId,
	allowed_questions: z.array(reassuranceQuestionSchema),
	allowed_levels: z.array(reassuranceLevelSchema),
	active: z.boolean(),
});

export const questionLogEntrySchema = z.object({
	id: z.string(),
	peer_id: peerId,
	question: reassuranceQuestionSchema,
	asked_at: datetime,
	answer_level: reassuranceLevelSchema,
});

export const sharingRulesResponseSchema = z.object({
	rules: z.array(sharingRuleSchema),
	questions_log: z.array(questionLogEntrySchema),
});

export const pushSubscriptionSchema = z.object({
	endpoint: z.string(),
	keys: z.object({
		p256dh: z.string(),
		auth: z.string(),
	}),
});

export const ledgerResponseSchema = z.object({
	worries_total: z.number().int(),
	active: z.number().int(),
	never_needed_you: z.number().int(),
	needed_you: z.number().int(),
	median_warning_lead_h: z.number(),
	came_true_rate: z.number(),
	came_true_by_type: z.record(z.string(), z.number()),
	watchers_built: z.number().int(),
	sandboxes_live: z.number().int(),
	endpoints_denied: z.number().int(),
	peer_questions_answered: z.number().int(),
	locations_shared: z.literal(0),
});

export const eventTypeSchema = z.enum([
	"worry.updated",
	"watcher.result",
	"approval.needed",
	"alert.act_now",
	"peer.answer",
]);

export const eventSchema = z.object({
	type: eventTypeSchema,
	data: z.record(z.string(), z.unknown()),
});

export type ReassuranceQuestion = z.infer<typeof reassuranceQuestionSchema>;
export type ReassuranceLevel = z.infer<typeof reassuranceLevelSchema>;
export type ReassuranceReason = z.infer<typeof reassuranceReasonSchema>;
export type Peer = z.infer<typeof peerSchema>;
export type PairingStartResponse = z.infer<typeof pairingStartResponseSchema>;
export type PairingStatusResponse = z.infer<typeof pairingStatusResponseSchema>;
export type ReassuranceAnswer = z.infer<typeof reassuranceAnswerSchema>;
export type PrivacyReceipt = z.infer<typeof privacyReceiptSchema>;
export type PeopleListItem = z.infer<typeof peopleListItemSchema>;
export type AskPeerResponse = z.infer<typeof askPeerResponseSchema>;
export type SharingRule = z.infer<typeof sharingRuleSchema>;
export type QuestionLogEntry = z.infer<typeof questionLogEntrySchema>;
export type SharingRulesResponse = z.infer<typeof sharingRulesResponseSchema>;
export type PushSubscription = z.infer<typeof pushSubscriptionSchema>;
export type LedgerResponse = z.infer<typeof ledgerResponseSchema>;
export type Event = z.infer<typeof eventSchema>;
