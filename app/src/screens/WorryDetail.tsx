import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { WorryDetail as Detail } from "../api/schemas";
import { PermissionCard } from "../components/PermissionCard";
import { BackLink, Button, Screen, SectionLabel } from "../components/ui";
import { asksOutcome, evidenceRows } from "../lib/evidence";
import {
	adapterLabel,
	fearLine,
	sourceLabel,
	statusLabel,
} from "../lib/labels";
import { navigate } from "../lib/router";
import { ago, day, every } from "../lib/time";
import { useAsync, useLiveEvents } from "../lib/useAsync";

function Body({ initial }: { initial: Detail }) {
	const [detail, setDetail] = useState(initial);
	useEffect(() => setDetail(initial), [initial]);
	const [busy, setBusy] = useState(false);
	const { worry, watcher, timeline } = detail;
	const last = watcher?.last_result ?? null;
	const open = worry.status !== "resolved";
	// Present tense only while a watcher really runs in its sandbox (S7 incident: a parked
	// worry showed "What it checks" and a jail for a sandbox that never existed).
	const running = watcher?.state === "active" || watcher?.state === "paused";
	const proposed =
		worry.status === "awaiting_approval" &&
		watcher?.state === "awaiting_approval";

	const [failed, setFailed] = useState(false);

	const act = async (op: (id: string) => Promise<Detail>, home: boolean) => {
		setBusy(true);
		setFailed(false);
		try {
			const next = await op(worry.id);
			// Closing a worry that was watched asks once whether the fear came true.
			if (home && !asksOutcome(next)) return navigate({ name: "home" });
			setDetail(next);
		} catch {
			setFailed(true);
		}
		setBusy(false);
	};
	const answer = async (cameTrue: boolean) => {
		setBusy(true);
		setFailed(false);
		try {
			await api.recordOutcome(worry.id, cameTrue);
			return navigate({ name: "home" });
		} catch {
			setFailed(true);
		}
		setBusy(false);
	};
	const alert = worry.status === "needs_you" && last?.status === "act_now";

	return (
		<>
			<header className="mt-8">
				<p className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-[13px] text-accent">
					{worry.status === "watching" && (
						<span
							aria-hidden
							className="size-1.5 animate-glow rounded-full bg-accent"
						/>
					)}
					{statusLabel[worry.status]}
				</p>
				<h1 className="mt-5 font-display text-[30px] leading-tight font-light">
					{worry.text}
				</h1>
				{worry.fear && (
					<p className="mt-3 text-[15px] leading-relaxed text-muted">
						{fearLine(worry.fear)}
					</p>
				)}
				{worry.resolution && (
					<p className="mt-2 text-[15px] text-muted">{worry.resolution}</p>
				)}
			</header>

			{worry.status === "awaiting_approval" && watcher && (
				<section className="mt-10">
					<PermissionCard
						watcher={watcher}
						busy={busy}
						onDecide={(allow) => act(allow ? api.approve : api.deny, false)}
					/>
				</section>
			)}

			{asksOutcome(detail) && (
				<section
					className="mt-10 rounded-3xl border border-line bg-surface p-5"
					aria-label="Did it happen?"
				>
					<h2 className="font-display text-[22px] leading-tight font-light">
						Did what you feared happen?
					</h2>
					<p className="mt-2 text-[15px] text-muted">
						One tap. It's how your ledger learns how often worries come true.
					</p>
					<div className="mt-5 flex gap-3">
						<Button disabled={busy} onClick={() => answer(true)}>
							Yes, it did
						</Button>
						<Button
							variant="quiet"
							disabled={busy}
							onClick={() => answer(false)}
						>
							No, it didn't
						</Button>
					</div>
				</section>
			)}

			{worry.status === "resolved" && worry.fear_came_true !== null && (
				<p className="mt-8 text-[15px] text-muted">
					{worry.fear_came_true
						? "You said it did happen."
						: "You said it didn't happen."}
				</p>
			)}

			{alert && last && (
				<section
					className="mt-10 rounded-3xl border border-accent/60 bg-accent-soft p-5"
					aria-label="Act now"
				>
					<p className="text-[13px] font-medium tracking-wide text-accent uppercase">
						Act now
					</p>
					<p className="mt-2 text-[18px] leading-snug text-ink">
						{last.summary}
					</p>
					<p className="mt-1 text-sm text-faint">
						Seen {ago(last.evidence.checked_at)} ·{" "}
						{sourceLabel(last.evidence.source)}
					</p>
					{evidenceRows(last).length > 0 && (
						<dl className="mt-4 divide-y divide-line border-t border-line">
							{evidenceRows(last).map((r) => (
								<div key={r.key} className="flex gap-4 py-2 text-sm">
									<dt className="w-28 shrink-0 text-faint">{r.key}</dt>
									<dd className="min-w-0 break-words text-ink">{r.value}</dd>
								</div>
							))}
						</dl>
					)}
				</section>
			)}

			{last && !alert && (
				<section className="mt-10">
					<SectionLabel>Last check</SectionLabel>
					<p className="text-[16px] leading-relaxed text-ink">{last.summary}</p>
					<p className="mt-1 text-sm text-faint">
						{ago(last.evidence.checked_at)} ·{" "}
						{sourceLabel(last.evidence.source)}
					</p>
				</section>
			)}

			{watcher && (running || proposed) && (
				<section className="mt-10">
					<SectionLabel>
						{running ? "What it checks" : "What it would check"}
					</SectionLabel>
					<p className="text-[16px] leading-relaxed text-ink">
						{watcher.adapters.map(adapterLabel).join(", ")},{" "}
						{every(watcher.interval_s)}
						{worry.deadline && `, until ${day(worry.deadline)}`}.
					</p>
				</section>
			)}

			{watcher && running && (
				<section className="mt-10">
					<SectionLabel>Its jail</SectionLabel>
					<PermissionCard watcher={watcher} />
				</section>
			)}

			<section className="mt-10">
				<SectionLabel>Timeline</SectionLabel>
				<ol className="border-l border-line pl-5">
					{[...timeline].reverse().map((e) => (
						<li key={`${e.at}-${e.kind}`} className="relative pb-5 last:pb-0">
							<span
								aria-hidden
								className="absolute top-2 -left-[23.5px] size-1.5 rounded-full bg-faint"
							/>
							<p className="text-[15px] leading-snug text-ink">{e.text}</p>
							<p className="mt-0.5 text-[13px] text-faint">{ago(e.at)}</p>
						</li>
					))}
				</ol>
			</section>

			{failed && (
				<p className="mt-10 text-[15px] text-muted">
					That didn't go through. Nothing changed.
				</p>
			)}

			{open && (
				<div className="mt-12 flex gap-3">
					{worry.status === "failed" && (
						<Button disabled={busy} onClick={() => act(api.retry, false)}>
							{busy ? "Trying again…" : "Try again"}
						</Button>
					)}
					<Button
						variant={worry.status === "needs_you" ? "primary" : "quiet"}
						disabled={busy}
						onClick={() => act(api.letGo, true)}
					>
						{worry.status === "needs_you" ? "Done, close it" : "Let it go"}
					</Button>
				</div>
			)}
		</>
	);
}

export function WorryDetail({ id }: { id: string }) {
	const d = useAsync(() => api.getWorry(id), id);
	useLiveEvents(api.subscribe, (e) => {
		if (e.type === "connected" || e.data.worry_id === id) d.reload();
	});
	return (
		<Screen>
			<BackLink href="#/" label="Back" />
			{d.state === "ready" && <Body key={id} initial={d.data} />}
			{d.state === "error" && (
				<p className="mt-10 text-[15px] text-muted">
					This worry isn't here any more.
				</p>
			)}
		</Screen>
	);
}
