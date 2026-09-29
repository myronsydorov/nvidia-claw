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

export const worryTypeSchema = z.enum([
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
		"parked",
		"failed",
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
