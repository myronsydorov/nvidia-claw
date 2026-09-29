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
	ics_calendar: "your calendar",
	weather_openmeteo: "the Open-Meteo forecast",
	transit_bvg: "BVG departures",
	parcel_dhl: "DHL parcel tracking",
	flight_status: "flight status",
};

export function adapterLabel(name: string): string {
	return adapterNames[name] ?? name;
}
