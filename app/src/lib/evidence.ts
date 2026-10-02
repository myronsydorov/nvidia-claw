import type { WatchResult, WorryDetail } from "../api/schemas";

// The evidence behind an alert (WatchResult.evidence.data). It is watched content: untrusted,
// shown to the person as plain text only (React escapes it), never fed anywhere else.

const MAX_ROWS = 6;
const MAX_CHARS = 80;

function show(value: unknown): string {
	if (value === null || value === undefined) return "—";
	if (typeof value === "boolean") return value ? "yes" : "no";
	const text = typeof value === "string" ? value : JSON.stringify(value);
	return text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS - 1)}…` : text;
}

/** Up to six "key: value" rows, keys made readable ("delay_min" → "delay min"). */
export function evidenceRows(
	result: WatchResult,
): { key: string; value: string }[] {
	return Object.entries(result.evidence.data)
		.filter(([key]) => key !== "truncated")
		.slice(0, MAX_ROWS)
		.map(([key, value]) => ({
			key: key.replaceAll("_", " "),
			value: show(value),
		}));
}

/** Ask "did it happen?" only for a closed worry that was really watched (its watcher was
 *  approved) and isn't answered yet. */
export function asksOutcome({ worry, timeline }: WorryDetail): boolean {
	return (
		worry.status === "resolved" &&
		worry.fear_came_true === null &&
		timeline.some((e) => e.kind === "approved")
	);
}
