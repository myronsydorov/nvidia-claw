import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type {
	AskPeerResponse,
	PeopleListItem,
	PrivacyReceipt,
	ReassuranceAnswer,
	ReassuranceQuestion,
} from "../api/schemas";
import { BackLink, Button, Screen, SectionLabel } from "../components/ui";
import {
	answerHeadline,
	askFailure,
	askLabel,
	cooldownLine,
	cooldownMinutes,
	questionShort,
	receiptLine,
} from "../lib/reassurance";
import { href } from "../lib/router";
import { ago } from "../lib/time";
import { useAsync, useLiveEvents } from "../lib/useAsync";

function LevelDot({ level }: { level: ReassuranceAnswer["level"] }) {
	const look =
		level === "help"
			? "bg-accent ring-4 ring-accent/25"
			: level === "normal"
				? "bg-accent/60"
				: level === "unusual"
					? "bg-accent/35"
					: "bg-line";
	return (
		<span aria-hidden className={`size-2.5 shrink-0 rounded-full ${look}`} />
	);
}

function Receipt({ receipt }: { receipt: PrivacyReceipt }) {
	return (
		<div className="mt-4 rounded-2xl bg-accent-soft px-4 py-3">
			<p className="text-xs font-medium tracking-[0.14em] text-accent uppercase">
				Privacy receipt
			</p>
			<p className="mt-1.5 text-[15px] leading-snug text-ink">
				{receiptLine(receipt)}
			</p>
			{receipt.fields_shared.length > 0 && (
				<p className="mt-1 text-sm text-muted">
					Fields: {receipt.fields_shared.join(", ")}
				</p>
			)}
			<p className="mt-1 font-mono text-[11px] break-all text-faint">
				{receipt.egress_log_ref}
			</p>
		</div>
	);
}

function AnswerCard({ name, res }: { name: string; res: AskPeerResponse }) {
	return (
		<section
			aria-label={`${name}'s answer`}
			className="mt-5 animate-rise border-t border-line pt-5"
		>
			<p className="flex items-center gap-3">
				<LevelDot level={res.answer.level} />
				<span className="font-display text-[26px] leading-tight font-light">
					{answerHeadline(res.answer)}, {ago(res.answer.ts)}
				</span>
			</p>
			<Receipt receipt={res.receipt} />
		</section>
	);
}

type Asked =
	| { state: "asking"; q: ReassuranceQuestion }
	| {
			state: "answered";
			q: ReassuranceQuestion;
			res: AskPeerResponse;
			at: string;
	  }
	| { state: "failed"; q: ReassuranceQuestion; status: number | null };

/** Re-render every `ms` so "Asked N min ago" counts and the cooldown ends. */
function useNow(ms: number): number {
	const [now, setNow] = useState(() => Date.now());
	useEffect(() => {
		const timer = setInterval(() => setNow(Date.now()), ms);
		return () => clearInterval(timer);
	}, [ms]);
	return now;
}

function Person({
	item,
	onChanged,
}: {
	item: PeopleListItem;
	onChanged: () => void;
}) {
	const { peer, last_answer } = item;
	const name = peer.display_name;
	const [asked, setAsked] = useState<Asked | null>(null);
	const busy = asked?.state === "asking";
	const now = useNow(15_000);
	const lastAskedAt =
		item.last_asked_at ?? (asked?.state === "answered" ? asked.at : null);
	const cooling = busy ? null : cooldownMinutes(lastAskedAt, now);

	const ask = async (q: ReassuranceQuestion) => {
		setAsked({ state: "asking", q });
		try {
			const res = await api.ask(peer.id, q);
			setAsked({ state: "answered", q, res, at: new Date().toISOString() });
		} catch (e) {
			const status = e instanceof ApiError ? e.status : null;
			// 429: asked recently (maybe from another device); the refresh shows the line.
			setAsked(status === 429 ? null : { state: "failed", q, status });
		}
		// The Warden starts the cooldown when the question leaves, answered or not.
		onChanged();
	};

	return (
		<li className="rounded-3xl border border-line bg-surface p-5">
			<h2 className="font-display text-[24px] leading-none font-light">
				{name}
			</h2>
			{asked?.state !== "answered" && (
				<p className="mt-2 text-sm text-faint">
					{busy
						? `Asking ${name}'s Warden…`
						: last_answer
							? `${answerHeadline(last_answer)}, ${ago(last_answer.ts)}`
							: `Paired ${ago(peer.paired_at)}. Not asked yet.`}
				</p>
			)}

			{asked?.state === "answered" && (
				<AnswerCard name={name} res={asked.res} />
			)}
			{asked?.state === "failed" && (
				<p
					className="mt-3 text-[15px] leading-relaxed text-muted"
					role="status"
				>
					{askFailure(asked.status, name)}
				</p>
			)}

			{cooling !== null ? (
				<p
					className="mt-5 text-[15px] leading-relaxed text-muted"
					role="status"
				>
					{cooldownLine(cooling)}
				</p>
			) : (
				<div className="mt-5 flex gap-3">
					<Button
						variant={asked?.state === "answered" ? "quiet" : "primary"}
						disabled={busy}
						onClick={() => ask("ok")}
					>
						{askLabel("ok", name)}
					</Button>
					<Button variant="quiet" disabled={busy} onClick={() => ask("home")}>
						{questionShort.home}
					</Button>
				</div>
			)}
		</li>
	);
}

function Chevron() {
	return (
		<svg
			aria-hidden
			viewBox="0 0 20 20"
			className="size-4 text-faint"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.6"
		>
			<path d="M7.5 4.5 13 10l-5.5 5.5" strokeLinecap="round" />
		</svg>
	);
}

function RowLink({ to, children }: { to: string; children: string }) {
	return (
		<a
			href={to}
			className="flex items-center justify-between rounded-2xl px-1 py-3 text-[16px] text-ink transition-colors active:bg-surface"
		>
			{children}
			<Chevron />
		</a>
	);
}

export function People() {
	const list = useAsync(() => api.listPeople(), "people");
	useLiveEvents(api.subscribe, (e) => {
		if (e.type === "connected") list.reload();
	});

	return (
		<Screen>
			<BackLink href={href({ name: "home" })} label="Home" />
			<header className="mt-8 mb-10">
				<h1 className="font-display text-[38px] leading-none font-light tracking-tight">
					People
				</h1>
				<p className="mt-4 text-[15px] leading-relaxed text-muted">
					Ask how they are. Their Warden answers with one word from a fixed
					list. Never where they are.
				</p>
			</header>

			{list.state === "ready" && list.data.length === 0 && (
				<p className="text-[15px] text-muted">
					No one is paired yet. Pair with a one-time code below.
				</p>
			)}
			{list.state === "ready" && list.data.length > 0 && (
				<ul className="animate-rise space-y-4">
					{list.data.map((item) => (
						<Person key={item.peer.id} item={item} onChanged={list.reload} />
					))}
				</ul>
			)}
			{list.state === "error" && (
				<p className="text-[15px] text-muted">
					Can't reach your Warden right now.
				</p>
			)}

			<section className="mt-12">
				<SectionLabel>Pair with someone</SectionLabel>
				<RowLink to={href({ name: "pair-show" })}>Show a code</RowLink>
				<RowLink to={href({ name: "pair-enter" })}>Enter their code</RowLink>
			</section>

			<section className="mt-10">
				<SectionLabel>About you</SectionLabel>
				<RowLink to={href({ name: "sharing" })}>
					What others can ask about me
				</RowLink>
			</section>
		</Screen>
	);
}
