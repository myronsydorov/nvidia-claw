import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
	Peer,
	ReassuranceQuestion,
	SharingRule,
	SharingRulesResponse,
} from "../api/schemas";
import { BackLink, Screen, SectionLabel, Toggle } from "../components/ui";
import {
	defaultRule,
	levelLabel,
	questionLabel,
	withRule,
} from "../lib/reassurance";
import { href } from "../lib/router";
import { ago } from "../lib/time";
import { useAsync, useLiveEvents } from "../lib/useAsync";

const QUESTIONS: ReassuranceQuestion[] = ["ok", "home"];

function RuleCard({
	peer,
	rule,
	busy,
	onChange,
}: {
	peer: Peer;
	rule: SharingRule | undefined;
	busy: boolean;
	onChange: (next: SharingRule) => void;
}) {
	const name = peer.display_name;
	const on = !!rule?.active;
	return (
		<li className="rounded-3xl border border-line bg-surface p-5">
			<div className="flex items-center justify-between gap-4">
				<div>
					<h3 className="font-display text-[22px] leading-none font-light">
						{name}
					</h3>
					<p className="mt-2 text-sm text-faint">
						{on ? "Can ask about you" : "Can't ask anything"}
					</p>
				</div>
				<Toggle
					label={`Let ${name} ask about me`}
					checked={on}
					disabled={busy}
					onChange={(active) =>
						onChange(
							rule ? { ...rule, active } : { ...defaultRule(peer.id), active },
						)
					}
				/>
			</div>
			{on && rule && (
				<>
					<ul className="mt-5 divide-y divide-line border-t border-line">
						{QUESTIONS.map((q) => {
							const allowed = rule.allowed_questions.includes(q);
							return (
								<li key={q} className="flex items-center justify-between py-3">
									<span className="text-[15px] text-ink">
										“{questionLabel[q]}”
									</span>
									<Toggle
										label={`${name} may ask “${questionLabel[q]}”`}
										checked={allowed}
										disabled={busy}
										onChange={(yes) =>
											onChange({
												...rule,
												allowed_questions: yes
													? QUESTIONS.filter(
															(x) =>
																x === q || rule.allowed_questions.includes(x),
														)
													: rule.allowed_questions.filter((x) => x !== q),
											})
										}
									/>
								</li>
							);
						})}
					</ul>
					<p className="mt-3 text-sm leading-relaxed text-faint">
						Answers they can get:{" "}
						{rule.allowed_levels.map((l) => levelLabel[l]).join(", ")}. Never
						where you are.
					</p>
				</>
			)}
		</li>
	);
}

function Body({
	peers,
	initial,
}: {
	peers: Peer[];
	initial: SharingRulesResponse;
}) {
	const [sharing, setSharing] = useState(initial);
	useEffect(() => setSharing(initial), [initial]);
	const [busy, setBusy] = useState(false);
	const [failed, setFailed] = useState(false);
	const names = new Map(peers.map((p) => [p.id, p.display_name]));

	const change = async (next: SharingRule) => {
		const before = sharing;
		const optimistic = { ...sharing, rules: withRule(sharing.rules, next) };
		setSharing(optimistic);
		setBusy(true);
		setFailed(false);
		try {
			setSharing(await api.putSharingRules(optimistic));
		} catch {
			setSharing(before);
			setFailed(true);
		}
		setBusy(false);
	};

	return (
		<>
			<section>
				<SectionLabel>Who may ask</SectionLabel>
				{peers.length === 0 ? (
					<p className="text-[15px] text-muted">No one is paired yet.</p>
				) : (
					<ul className="animate-rise space-y-4">
						{peers.map((p) => (
							<RuleCard
								key={p.id}
								peer={p}
								rule={sharing.rules.find((r) => r.peer_id === p.id)}
								busy={busy}
								onChange={change}
							/>
						))}
					</ul>
				)}
				{failed && (
					<p className="mt-4 text-[15px] text-muted">
						That didn't go through. Nothing changed.
					</p>
				)}
			</section>

			<section className="mt-12">
				<SectionLabel>Who asked</SectionLabel>
				{sharing.questions_log.length === 0 ? (
					<p className="text-[15px] text-muted">No one has asked yet.</p>
				) : (
					<ol aria-label="Question log" className="divide-y divide-line">
						{sharing.questions_log.map((e) => (
							<li key={e.id} className="py-4">
								<p className="text-[16px] leading-snug text-ink">
									{names.get(e.peer_id) ?? "Someone"} asked “
									{questionLabel[e.question]}”
								</p>
								<p className="mt-0.5 text-sm text-faint">
									Answered {levelLabel[e.answer_level]} · {ago(e.asked_at)}
								</p>
							</li>
						))}
					</ol>
				)}
			</section>
		</>
	);
}

export function Sharing() {
	const d = useAsync(
		() => Promise.all([api.listPeople(), api.getSharingRules()]),
		"sharing",
	);
	useLiveEvents(api.subscribe, (e) => {
		if (e.type === "connected") d.reload();
	});
	return (
		<Screen>
			<BackLink href={href({ name: "people" })} label="People" />
			<header className="mt-8 mb-10">
				<h1 className="font-display text-[34px] leading-tight font-light tracking-tight">
					What others can ask about me
				</h1>
				<p className="mt-4 text-[15px] leading-relaxed text-muted">
					They get one word from a fixed list, never your messages, your day or
					where you are. Every question is written down here.
				</p>
			</header>
			{d.state === "ready" && (
				<Body peers={d.data[0].map((i) => i.peer)} initial={d.data[1]} />
			)}
			{d.state === "error" && (
				<p className="text-[15px] text-muted">
					Can't reach your Warden right now.
				</p>
			)}
		</Screen>
	);
}
