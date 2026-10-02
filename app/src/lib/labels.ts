import type { WorryStatus } from "../api/schemas";

export const statusLabel: Record<WorryStatus, string> = {
	triaging: "Understanding",
	compiling: "Writing a watcher",
	awaiting_approval: "Waiting for your OK",
	watching: "Watching",
	needs_you: "Needs you",
	resolved: "Resolved",
	parked: "Parked",
	failed: "Couldn't watch this",
};

const adapterNames: Record<string, string> = {
	http_json: "a public web API",
	rss: "a news feed",
	web_diff: "a web page",
	imap_search: "your inbox",
	ics_calendar: "a calendar",
	weather_openmeteo: "the Open-Meteo forecast",
	transit_bvg: "BVG departures",
	parcel_dhl: "DHL parcel tracking",
	flight_status: "flight status",
};

export function adapterLabel(name: string): string {
	return adapterNames[name] ?? name;
}

/** "The fear: …" exactly as triage wrote it: never re-cased, so names keep their capitals
 *  ("S-Bahn", "Open-Meteo", "Lena"). Only a trailing full stop is normalised. */
export function fearLine(fear: string): string {
	const text = fear.trim().replace(/[.\s]+$/, "");
	return text ? `The fear: ${text}.` : "";
}

/** Where a check's evidence came from. Watchers sometimes name their adapter ("weather_openmeteo");
 *  show its plain name then, otherwise the source as written. */
export function sourceLabel(source: string): string {
	const name = adapterNames[source];
	return name ? name.replace(/^(a|an|the|your) /, "") : source;
}
