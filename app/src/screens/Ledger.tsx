import type { ReactNode } from "react";
import { api } from "../api/client";
import type { LedgerResponse } from "../api/schemas";
import { BackLink, Screen, SectionLabel } from "../components/ui";
import {
	didntComeTrue,
	hours,
	PENN_STATE_DIDNT_COME_TRUE,
	pct,
	typeLabel,
} from "../lib/reassurance";
import { href } from "../lib/router";
import { day } from "../lib/time";
import { useAsync, useLiveEvents } from "../lib/useAsync";

// The stats wall (DESIGN §6). Every value comes straight from GET /api/ledger
// (CONTRACTS §5); `data-field` names the field it shows.

function Tile({
	label,
	field,
	value,
	note,
	wide,
	emphasis,
}: {
	label: string;
	field: keyof LedgerResponse;
	value: ReactNode;
	note?: string;
	wide?: boolean;
	emphasis?: boolean;
}) {
	return (
		<div
			className={`rounded-2xl border p-4 ${wide ? "col-span-2" : ""} ${
				emphasis ? "border-accent/40 bg-accent-soft" : "border-line bg-surface"
			}`}
		>
			<p className="text-sm text-muted">{label}</p>
			<p
				data-field={field}
				className={`mt-1 text-[28px] leading-tight font-semibold ${
					emphasis ? "text-accent" : "text-ink"
				}`}
			>
				{value}
			</p>
			{note && <p className="mt-1 text-[13px] text-faint">{note}</p>}
		</div>
	);
}

/** A ratio on a same-hue track: accent for you, grey for the study. */
function Meter({
	label,
	fraction,
	field,
	mine,
}: {
	label: string;
	fraction: number;
	field?: string;
	mine?: boolean;
}) {
	const w = Math.max(0, Math.min(1, fraction)) * 100;
	return (
		<div>
			<div className="flex items-baseline justify-between gap-4">
				<span className="text-[15px] text-ink">{label}</span>
				<span data-field={field} className="text-[15px] font-semibold text-ink">
					{pct(fraction)}
				</span>
			</div>
			<meter
				className="sr-only"
				aria-label={label}
				min={0}
				max={100}
				value={Number(w.toFixed(1))}
			/>
			<div
				aria-hidden
				className={`mt-2 h-2 overflow-hidden rounded-full ${
					mine ? "bg-accent-soft" : "bg-line/60"
				}`}
			>
				<div
					className={`h-full rounded-full ${mine ? "bg-accent" : "bg-faint"}`}
					style={{ width: `${w}%` }}
				/>
			</div>
		</div>
	);
}

function Wall({ l }: { l: LedgerResponse }) {
	const known = l.needed_you + l.never_needed_you;
	const mine = didntComeTrue(l);
	const byType = Object.entries(l.came_true_by_type);

	return (
		<div className="animate-rise">
			<section aria-label="Never needed you">
				<p
					data-field="never_needed_you"
					className="text-[72px] leading-none font-light tracking-tight text-ink"
				>
					{l.never_needed_you}
				</p>
				<p className="mt-2 text-[17px] text-ink">worries never needed you.</p>
				<p className="mt-1 text-[15px] leading-relaxed text-muted">
					<span data-field="needed_you">{l.needed_you}</span> needed you
					{l.needed_you > 0 && l.median_warning_lead_h > 0 ? (
						<>
							, warned a median{" "}
							<span data-field="median_warning_lead_h">
								{hours(l.median_warning_lead_h)}
							</span>{" "}
							ahead.
						</>
					) : (
						<>
							.{" "}
							<span data-field="median_warning_lead_h" className="sr-only">
								no warnings yet
							</span>
						</>
					)}
				</p>
			</section>

			<section aria-label="Silence" className="mt-8">
				<p className="text-[17px] text-ink" data-testid="silence-line">
					<span data-field="checks_run" className="font-semibold">
						{l.checks_run}
					</span>{" "}
					{l.checks_run === 1 ? "check" : "checks"},{" "}
					<span data-field="alerts_sent" className="font-semibold">
						{l.alerts_sent}
					</span>{" "}
					{l.alerts_sent === 1 ? "interruption" : "interruptions"}
				</p>
				<p className="mt-1 text-sm text-faint">
					{l.checks_since
						? `Counted since ${day(l.checks_since)}.`
						: "No checks counted yet."}
				</p>
			</section>

			<section className="mt-12">
				<SectionLabel>Did it come true?</SectionLabel>
				{mine === null ? (
					<p className="text-[15px] leading-relaxed text-muted">
						No outcomes yet. When a worry ends, I'll ask whether it happened.
						<span data-field="came_true_rate" className="sr-only">
							no outcomes yet
						</span>
					</p>
				) : (
					<>
						<div className="space-y-5">
							<Meter label="Yours, didn't happen" fraction={mine} mine />
							<Meter
								label="Research, not your data: Penn State study"
								fraction={PENN_STATE_DIDNT_COME_TRUE}
							/>
						</div>
						<p className="mt-4 text-sm leading-relaxed text-faint">
							Came true:{" "}
							<span data-field="came_true_rate" className="text-muted">
								{pct(l.came_true_rate)}
							</span>{" "}
							of your {known} worries with a known outcome. For comparison,
							research (Penn State, LaFreniere &amp; Newman, 2019, people with
							generalized anxiety): 91.4% of their worries didn't come true.
						</p>
					</>
				)}
				{byType.length > 0 && (
					<ul
						data-field="came_true_by_type"
						className="mt-6 divide-y divide-line border-y border-line"
					>
						{byType.map(([type, rate]) => (
							<li
								key={type}
								className="flex items-baseline justify-between py-3 text-[15px]"
							>
								<span className="text-ink">{typeLabel(type)}</span>
								<span className="text-muted">came true {pct(rate)}</span>
							</li>
						))}
					</ul>
				)}
			</section>

			<section className="mt-12">
				<SectionLabel>Custody</SectionLabel>
				<div className="grid grid-cols-2 gap-3">
					<Tile
						label="Handed over"
						field="worries_total"
						value={l.worries_total}
					/>
					<Tile label="Still watched" field="active" value={l.active} />
					<Tile
						label="Watchers built"
						field="watchers_built"
						value={l.watchers_built}
					/>
					<Tile
						label="Sandboxes live"
						field="sandboxes_live"
						value={l.sandboxes_live}
					/>
					<Tile
						wide
						label="Endpoints denied"
						field="endpoints_denied"
						value="—"
						note="Not counted here yet. Each sandbox blocks and logs anything outside its rules; the log is real, this tile isn't wired to it."
					/>
				</div>
			</section>

			<section className="mt-12">
				<SectionLabel>Between people</SectionLabel>
				<div className="grid grid-cols-2 gap-3">
					<Tile
						label="Questions about you"
						field="peer_questions_answered"
						value={l.peer_questions_answered}
					/>
					<Tile
						emphasis
						label="Locations shared"
						field="locations_shared"
						value={l.locations_shared}
						note="Never."
					/>
				</div>
			</section>
		</div>
	);
}

export function Ledger() {
	const d = useAsync(() => api.getLedger(), "ledger");
	useLiveEvents(api.subscribe, (e) => {
		if (e.type === "connected") d.reload();
	});
	return (
		<Screen>
			<BackLink href={href({ name: "home" })} label="Home" />
			<header className="mt-8 mb-10">
				<h1 className="font-display text-[38px] leading-none font-light tracking-tight">
					Ledger
				</h1>
				<p className="mt-4 text-[15px] leading-relaxed text-muted">
					What custody has done for you, counted.
				</p>
			</header>
			{d.state === "ready" && <Wall l={d.data} />}
			{d.state === "error" && (
				<p className="text-[15px] text-muted">
					Can't reach your Warden right now.
				</p>
			)}
		</Screen>
	);
}
