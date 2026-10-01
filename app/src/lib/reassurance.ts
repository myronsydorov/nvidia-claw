import type {
	LedgerResponse,
	PrivacyReceipt,
	ReassuranceAnswer,
	ReassuranceLevel,
	ReassuranceQuestion,
	ReassuranceReason,
	SharingRule,
} from "../api/schemas";

// Words for the fixed reassurance vocabulary (CONTRACTS §2). Nothing here may
// add information the answer doesn't carry.

const reasonHeadline: Record<ReassuranceReason, string> = {
	active_as_usual: "Normal day",
	quieter_than_usual: "Quieter than usual",
	do_not_disturb: "Do not disturb is on",
	asked_for_help: "Asked for help",
	not_enough_data: "Not enough to say",
	arrived: "Home",
	not_arrived: "Not home yet",
};

export function answerHeadline(a: ReassuranceAnswer): string {
	return reasonHeadline[a.reason];
}

export const levelLabel: Record<ReassuranceLevel, string> = {
	normal: "Normal",
	unusual: "Unusual",
	help: "Asked for help",
	unknown: "Unknown",
};

export function askLabel(q: ReassuranceQuestion, name: string): string {
	return q === "ok" ? `Is ${name} OK?` : `Is ${name} home?`;
}

/** How a question reads in the log of what others asked about me. */
export const questionLabel: Record<ReassuranceQuestion, string> = {
	ok: "Are you OK?",
	home: "Are you home?",
};

export const questionShort: Record<ReassuranceQuestion, string> = {
	ok: "Are you OK?",
	home: "Home yet?",
};

/** "Shared: 1 answer, 212 bytes, encrypted. Location: never." */
export function receiptLine(r: PrivacyReceipt): string {
	const location = r.location_shared ? "Location: shared." : "Location: never.";
	if (r.bytes_sent === 0) return `Nothing left their device. ${location}`;
	return `Shared: 1 answer, ${r.bytes_sent} bytes, encrypted. ${location}`;
}

/** Penn State (LaFreniere & Newman, 2019): 91.4% of worries didn't come true. */
export const PENN_STATE_DIDNT_COME_TRUE = 0.914;

export function pct(fraction: number): string {
	const p = fraction * 100;
	return `${p >= 99.5 || p < 10 ? p.toFixed(0) : p.toFixed(1).replace(/\.0$/, "")}%`;
}

export function hours(h: number): string {
	if (h < 1) return `${Math.round(h * 60)} min`;
	if (h < 48) return `${Number(h.toFixed(1))} h`;
	return `${Number((h / 24).toFixed(1))} days`;
}

/** Fraction of worries with a known outcome whose fear did NOT come true;
 *  null when no outcome is known yet (came_true_rate would mean nothing). */
export function didntComeTrue(l: LedgerResponse): number | null {
	if (l.needed_you + l.never_needed_you === 0) return null;
	return 1 - l.came_true_rate;
}

const typeNames: Record<string, string> = {
	checkable: "Things to check",
	deadline: "Deadlines",
	person: "People",
	social: "Social",
	uncontrollable: "Out of your hands",
	unclassified: "Unsorted",
};

export function typeLabel(t: string): string {
	return typeNames[t] ?? t;
}

/** What a newly allowed person may ask until you change it. */
export function defaultRule(peerId: string): SharingRule {
	return {
		peer_id: peerId,
		allowed_questions: ["ok"],
		allowed_levels: ["normal", "unusual", "help", "unknown"],
		active: true,
	};
}

/** The full rules list with one person's rule replaced (PUT replaces all). */
export function withRule(
	rules: SharingRule[],
	next: SharingRule,
): SharingRule[] {
	const others = rules.filter((r) => r.peer_id !== next.peer_id);
	return [...others, next];
}

// --- Asking: the cooldown and honest failure lines ---------------------------

/** One ask per person per 10 minutes: no "check again" loop (AGENTS #9). */
export const ASK_COOLDOWN_MS = 10 * 60_000;

/** Whole minutes since the last ask while still inside the cooldown (at least
 *  1, so it never reads "0 min"), or null once asking is open again. */
export function cooldownMinutes(
	lastAskedAt: string | null,
	now: number = Date.now(),
): number | null {
	if (!lastAskedAt) return null;
	const ms = now - Date.parse(lastAskedAt);
	if (ms >= ASK_COOLDOWN_MS) return null;
	return Math.max(1, Math.floor(ms / 60_000));
}

export function cooldownLine(minutes: number): string {
	return `Asked ${minutes} min ago. They'll tell you if anything changes.`;
}

/** What to say when an ask fails, by the Warden's status code. Calm, and only
 *  what we know: a silent Warden says nothing about the person. */
export function askFailure(status: number | null, name: string): string {
	switch (status) {
		case 503:
			return "Your Warden couldn't reach the relay, so your question may not have gone through.";
		case 504:
			return `${name}'s Warden didn't answer in time. Their computer may be asleep or offline. That alone doesn't mean anything is wrong.`;
		case 502:
			return `${name}'s Warden sent something outside the fixed answers, so it was discarded.`;
		case 404:
			return `${name} isn't paired any more.`;
		default:
			return "That didn't go through.";
	}
}

// --- Pairing -------------------------------------------------------------------

/** "K7M2Q9XA" → "K7M2 Q9XA", easier to read aloud and type. */
export function formatCode(code: string): string {
	return `${code.slice(0, 4)} ${code.slice(4)}`;
}

export function joinFailure(status: number | null): string {
	switch (status) {
		case 422:
			return "A code is 8 letters and digits, like K7M2 Q9XA.";
		case 404:
			return "That code doesn't match a live pairing. Codes last 10 minutes and work once.";
		case 409:
			return "That's this phone's own code, or you're already paired with them. To pair again, remove them from People first.";
		case 503:
			return "Your Warden can't reach the relay right now. Nothing was paired.";
		default:
			return "That didn't go through. Nothing was paired.";
	}
}
