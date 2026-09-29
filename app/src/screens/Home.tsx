import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import type { WorrySummary } from "../api/schemas";
import { Orb, Screen, SectionLabel } from "../components/ui";
import { statusLabel } from "../lib/labels";
import { href, navigate } from "../lib/router";
import { ago } from "../lib/time";
import { useAsync } from "../lib/useAsync";

function subline(items: WorrySummary[]): string {
	const held = items.filter((i) => i.worry.status !== "parked").length;
	if (held === 0) return "Nothing in custody.";
	const noun = held === 1 ? "worry" : "worries";
	const waiting = items.filter((i) => i.worry.status === "needs_you").length;
	if (waiting > 0) return `${held} ${noun} in custody. ${waiting} needs you.`;
	return `${held} ${noun} in custody. Nothing needs you.`;
}

function WorryRow({ item }: { item: WorrySummary }) {
	const { worry, last_result } = item;
	const needsYou = worry.status === "needs_you";
	const meta =
		worry.status !== "watching"
			? statusLabel[worry.status]
			: last_result
				? `Checked ${ago(last_result.evidence.checked_at)}`
				: "Watching. First check soon.";
	return (
		<li>
			<a
				href={href({ name: "worry", id: worry.id })}
				className="flex items-center gap-4 rounded-2xl px-1 py-4 transition-colors active:bg-surface"
			>
				<span
					aria-hidden
					className={`size-2 shrink-0 rounded-full ${
						needsYou
							? "bg-accent"
							: worry.status === "watching"
								? "bg-accent/45"
								: "bg-line"
					}`}
				/>
				<span className="min-w-0 flex-1">
					<span className="block truncate text-[16px] text-ink">
						{worry.text}
					</span>
					<span className="mt-0.5 block text-sm text-faint">{meta}</span>
				</span>
			</a>
		</li>
	);
}

function WorryGroup({
	label,
	items,
}: {
	label: string;
	items: WorrySummary[];
}) {
	if (items.length === 0) return null;
	return (
		<section className="mb-8 animate-rise">
			<SectionLabel>{label}</SectionLabel>
			<ul className="divide-y divide-line">
				{items.map((item) => (
					<WorryRow key={item.worry.id} item={item} />
				))}
			</ul>
		</section>
	);
}

function MindInput() {
	const [text, setText] = useState("");
	const submit = (e: FormEvent) => {
		e.preventDefault();
		const t = text.trim();
		if (t) navigate({ name: "hand-over", text: t });
	};
	return (
		<div className="sticky bottom-0 -mx-6 mt-auto bg-linear-to-t from-bg from-70% to-transparent px-6 pt-8 pb-[max(env(safe-area-inset-bottom),1.5rem)]">
			<form
				onSubmit={submit}
				className="flex items-center gap-2 rounded-full border border-line bg-surface py-2 pr-2 pl-5 shadow-[0_8px_30px_rgb(0_0_0/0.18)]"
			>
				<label htmlFor="mind" className="sr-only">
					What's on your mind?
				</label>
				<input
					id="mind"
					value={text}
					onChange={(e) => setText(e.target.value)}
					placeholder="What's on your mind?"
					autoComplete="off"
					className="h-10 min-w-0 flex-1 bg-transparent text-[16px] text-ink placeholder:text-faint focus:outline-none"
				/>
				<button
					type="submit"
					aria-label="Hand it over"
					disabled={!text.trim()}
					className="flex size-10 items-center justify-center rounded-full bg-accent text-on-accent transition-opacity disabled:opacity-30"
				>
					<svg
						aria-hidden
						viewBox="0 0 20 20"
						className="size-4"
						fill="none"
						stroke="currentColor"
						strokeWidth="1.8"
					>
						<path d="M10 15.5v-11M5 9l5-4.5L15 9" strokeLinecap="round" />
					</svg>
				</button>
			</form>
		</div>
	);
}

export function Home() {
	const list = useAsync(() => api.listWorries(), "home");
	const items = list.state === "ready" ? list.data : [];
	const needsYou = items.some((i) => i.worry.status === "needs_you");
	const parked = items.filter((i) => i.worry.status === "parked");
	const held = items.filter((i) => i.worry.status !== "parked");

	return (
		<Screen flushBottom>
			<header className="flex flex-col items-center pt-14 pb-12 text-center">
				<Orb />
				<h1 className="mt-10 font-display text-[44px] leading-none font-light tracking-tight">
					{needsYou ? "Something needs you." : "All quiet."}
				</h1>
				<p className="mt-4 h-5 text-[15px] text-muted">
					{list.state === "ready" && subline(items)}
					{list.state === "error" && "Can't reach your Warden right now."}
				</p>
			</header>

			<WorryGroup label="In custody" items={held} />
			<WorryGroup label="For worry time" items={parked} />

			<MindInput />
		</Screen>
	);
}
