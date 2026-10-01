export function ago(isoTime: string, now: number = Date.now()): string {
	const s = Math.max(0, Math.round((now - Date.parse(isoTime)) / 1000));
	if (s < 60) return "just now";
	const m = Math.round(s / 60);
	if (m < 60) return `${m} min ago`;
	const h = Math.round(m / 60);
	if (h < 24) return `${h} h ago`;
	const d = Math.round(h / 24);
	return d === 1 ? "yesterday" : `${d} days ago`;
}

export function every(intervalS: number): string {
	if (intervalS % 86400 === 0) {
		const d = intervalS / 86400;
		return d === 1 ? "once a day" : `every ${d} days`;
	}
	if (intervalS % 3600 === 0) {
		const h = intervalS / 3600;
		return h === 1 ? "every hour" : `every ${h} hours`;
	}
	return `every ${Math.round(intervalS / 60)} minutes`;
}

// Custody's people are in Berlin: times show as Europe/Berlin wall-clock time whatever zone
// the device is in (the Warden stores UTC).
export const LOCAL_TIME_ZONE = "Europe/Berlin";

export function day(isoTime: string): string {
	return new Date(isoTime).toLocaleString("en-GB", {
		weekday: "short",
		hour: "2-digit",
		minute: "2-digit",
		timeZone: LOCAL_TIME_ZONE,
	});
}
