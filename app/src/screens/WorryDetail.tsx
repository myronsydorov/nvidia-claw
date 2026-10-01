import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { WorryDetail as Detail } from "../api/schemas";
import { PermissionCard } from "../components/PermissionCard";
import { BackLink, Button, Screen, SectionLabel } from "../components/ui";
import { adapterLabel, statusLabel } from "../lib/labels";
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
			if (home) return navigate({ name: "home" });
			setDetail(next);
		} catch {
			setFailed(true);
		}
		setBusy(false);
	};

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
				<p className="mt-3 text-[15px] leading-relaxed text-muted">
					The fear: {worry.fear.charAt(0).toLowerCase() + worry.fear.slice(1)}.
				</p>
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

			{last && (
				<section className="mt-10">
					<SectionLabel>Last check</SectionLabel>
					<p className="text-[16px] leading-relaxed text-ink">{last.summary}</p>
					<p className="mt-1 text-sm text-faint">
						{ago(last.evidence.checked_at)} · {last.evidence.source}
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
						variant="quiet"
						disabled={busy}
						onClick={() => act(api.letGo, true)}
					>
						Let it go
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
