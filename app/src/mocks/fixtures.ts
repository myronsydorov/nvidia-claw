import {
	type PermissionLine,
	type TimelineEvent,
	type WorryDetail,
	worryDetailSchema,
} from "../api/schemas";

// Mock data for T-05. Every record is parsed through the contract schemas,
// so drift from docs/CONTRACTS.md fails loudly at load and in tests.

const MIN = 60_000;

export function iso(offsetMs: number, now: number = Date.now()): string {
	return new Date(now + offsetMs).toISOString();
}

let counter = 0;
/** A deterministic, valid ULID body; the prefix makes it a w_/wt_ id. */
export function mockUlid(): string {
	counter += 1;
	return `01K6B8Z3Q4R5S6T7V8W9XA${String(counter).padStart(4, "0")}`;
}

export function policyYaml(name: string, lines: PermissionLine[]): string {
	const endpoints = lines
		.map(
			(l) =>
				`      - host: ${l.host}\n        port: 443\n        protocol: rest\n        enforcement: enforce\n        rules:\n          - allow: { method: ${l.method}, path: "${l.path}" }`,
		)
		.join("\n");
	return `network_policies:\n  ${name}:\n    endpoints:\n${endpoints}\n    binaries:\n      - path: /usr/bin/python3.12\n`;
}

type Template = {
	type: WorryDetail["worry"]["type"];
	fear: string;
	/** Fixed demo-week dates, so the fear text and the deadline agree. */
	deadline: string | null;
	adapters: string[];
	lines: PermissionLine[];
	interval_s: number;
	source: string;
	summary: string;
};

export const templates = {
	parcel: {
		type: "deadline",
		fear: "Parcel not delivered by Friday 18:00",
		deadline: "2026-10-02T16:00:00Z",
		adapters: ["parcel_dhl"],
		lines: [
			{
				method: "GET",
				host: "api-eu.dhl.com",
				path: "/track/shipments",
				why: "check the parcel's status",
			},
		],
		interval_s: 3600,
		source: "DHL",
		summary: "In transit, Leipzig hub. Expected Thursday.",
	},
	train: {
		type: "checkable",
		fear: "The 07:42 RE1 to Potsdam is cancelled on Friday",
		deadline: "2026-10-02T05:42:00Z",
		adapters: ["transit_bvg"],
		lines: [
			{
				method: "GET",
				host: "v6.bvg.transport.rest",
				path: "/stops/900100001/departures",
				why: "see Friday's departures",
			},
		],
		interval_s: 1800,
		source: "BVG",
		summary: "Running on time. No disruptions reported.",
	},
	weather: {
		type: "deadline",
		fear: "A storm during Saturday's garden wedding",
		deadline: "2026-10-03T18:00:00Z",
		adapters: ["weather_openmeteo"],
		lines: [
			{
				method: "GET",
				host: "api.open-meteo.com",
				path: "/v1/forecast",
				why: "read Saturday's forecast",
			},
		],
		interval_s: 10800,
		source: "Open-Meteo",
		summary: "Dry and mild on Saturday. 10% chance of rain.",
	},
} satisfies Record<string, Template>;

export type TemplateName = keyof typeof templates;

export function buildDetail(
	text: string,
	t: Template,
	opts: {
		status: WorryDetail["worry"]["status"];
		createdAgoMs: number;
		checkedAgoMs: number | null;
		now?: number;
	},
): WorryDetail {
	const now = opts.now ?? Date.now();
	const worryId = `w_${mockUlid()}`;
	const watcherId = `wt_${mockUlid()}`;
	const created = iso(-opts.createdAgoMs, now);
	const active = opts.status === "watching";
	const lastResult =
		opts.checkedAgoMs === null
			? null
			: {
					status: "ok" as const,
					summary: t.summary,
					evidence: {
						source: t.source,
						checked_at: iso(-opts.checkedAgoMs, now),
						data: {},
					},
					fear_came_true: null,
					next_check_s: t.interval_s,
				};
	const timeline: TimelineEvent[] = [
		{ at: created, kind: "created", text: "You handed it over." },
		{
			at: iso(-opts.createdAgoMs + 4_000, now),
			kind: "triaged",
			text: "Understood what you're afraid of.",
		},
		{
			at: iso(-opts.createdAgoMs + 19_000, now),
			kind: "compiled",
			text: "Wrote a watcher and tested it in its own sandbox.",
		},
		{
			at: iso(-opts.createdAgoMs + 21_000, now),
			kind: "approval_requested",
			text: "Asked for your permission.",
		},
	];
	if (active) {
		timeline.push({
			at: iso(-opts.createdAgoMs + 60_000, now),
			kind: "approved",
			text: "You allowed it. Watching quietly.",
		});
	}
	if (active && lastResult) {
		timeline.push({
			at: lastResult.evidence.checked_at,
			kind: "checked",
			text: t.summary,
		});
	}
	return worryDetailSchema.parse({
		worry: {
			id: worryId,
			text,
			type: t.type,
			fear: t.fear,
			deadline: t.deadline,
			status: opts.status,
			watcher_id: watcherId,
			resolution: null,
			fear_came_true: null,
			created_at: created,
			updated_at: lastResult?.evidence.checked_at ?? created,
		},
		watcher: {
			id: watcherId,
			worry_id: worryId,
			adapters: t.adapters,
			code: `# run.py (generated)\nfrom custody_adapters import ${t.adapters[0]}\n`,
			policy_yaml: policyYaml(t.adapters[0] ?? "watcher", t.lines),
			policy_summary: t.lines,
			sandbox_name: `cw-${watcherId.slice(-8).toLowerCase()}`,
			interval_s: t.interval_s,
			state: active ? "active" : "awaiting_approval",
			last_result: lastResult,
		},
		timeline,
	});
}

function parkedDetail(now: number): WorryDetail {
	const created = iso(-2 * 24 * 60 * MIN, now);
	return worryDetailSchema.parse({
		worry: {
			id: `w_${mockUlid()}`,
			text: "I think I said something awkward at dinner",
			type: "social",
			fear: "Friends think less of me after Saturday's dinner",
			deadline: null,
			status: "parked",
			watcher_id: null,
			resolution: "Nothing to watch. Saved for Sunday's worry time.",
			fear_came_true: null,
			created_at: created,
			updated_at: created,
		},
		watcher: null,
		timeline: [
			{ at: created, kind: "created", text: "You handed it over." },
			{
				at: created,
				kind: "parked",
				text: "Nothing to watch. Saved for Sunday's worry time.",
			},
		],
	});
}

// The S7 incident's shape, before the fix: parked, but with a leftover dry_run_failed watcher.
// The app must show no present-tense check and no jail for it.
function legacyParkedBuildDetail(now: number): WorryDetail {
	const created = iso(-90 * MIN, now);
	const text = "What if the S7 is disrupted around 9:00 from Lichtenberg?";
	return worryDetailSchema.parse({
		worry: {
			id: `w_${mockUlid()}`,
			text,
			type: "checkable",
			fear: "S7 from Lichtenberg disrupted around 09:00",
			deadline: iso(9 * 60 * MIN, now),
			status: "parked",
			watcher_id: `wt_${mockUlid()}`,
			resolution:
				"I couldn't build a watcher that works, so I've parked this rather than pretend.",
			fear_came_true: null,
			created_at: created,
			updated_at: created,
		},
		watcher: {
			id: `wt_${mockUlid()}`,
			worry_id: `w_${mockUlid()}`,
			adapters: ["transit_bvg"],
			code: "",
			policy_yaml: "",
			policy_summary: [
				{
					method: "GET",
					host: "v6.bvg.transport.rest",
					path: "/stops/8011120/departures",
					why: "check departures for this stop",
				},
			],
			sandbox_name: "cw-bjasgm4b",
			interval_s: 300,
			state: "dry_run_failed",
			last_result: null,
		},
		timeline: [{ at: created, kind: "created", text: "You handed it over." }],
	});
}

function failedBuildDetail(now: number): WorryDetail {
	const created = iso(-30 * MIN, now);
	const resolution =
		"Testing the watcher failed: the check could not get its data. Nothing was set up; you can try again.";
	return worryDetailSchema.parse({
		worry: {
			id: `w_${mockUlid()}`,
			text: "What if the U5 is late tonight?",
			type: "checkable",
			fear: "U5 late tonight",
			deadline: null,
			status: "failed",
			watcher_id: null,
			resolution,
			fear_came_true: null,
			created_at: created,
			updated_at: created,
		},
		watcher: null,
		timeline: [
			{ at: created, kind: "created", text: "You handed it over." },
			{ at: created, kind: "failed", text: resolution.slice(0, 140) },
		],
	});
}

export function initialDetails(now: number = Date.now()): WorryDetail[] {
	return [
		buildDetail(
			"I'm worried my parcel won't arrive before Friday",
			templates.parcel,
			{
				status: "watching",
				createdAgoMs: 26 * 60 * MIN,
				checkedAgoMs: 12 * MIN,
				now,
			},
		),
		buildDetail(
			"What if my train to Potsdam gets cancelled?",
			templates.train,
			{
				status: "watching",
				createdAgoMs: 5 * 60 * MIN,
				checkedAgoMs: 3 * MIN,
				now,
			},
		),
		buildDetail(
			"What if it storms at the wedding on Saturday?",
			templates.weather,
			{
				status: "watching",
				createdAgoMs: 3 * 24 * 60 * MIN,
				checkedAgoMs: 41 * MIN,
				now,
			},
		),
		parkedDetail(now),
		legacyParkedBuildDetail(now),
		failedBuildDetail(now),
	];
}

export function pickTemplate(text: string): Template {
	const t = text.toLowerCase();
	if (/(train|bus|bvg|s-bahn|u-bahn|tram)/.test(t)) return templates.train;
	if (/(rain|storm|weather|snow|wind)/.test(t)) return templates.weather;
	return templates.parcel;
}
