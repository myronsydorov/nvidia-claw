import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { BackLink, Screen } from "../components/ui";
import { href } from "../lib/router";

// Talk to Custody: app → Warden → loopback chat endpoint → brain → MCP tools (CONTRACTS §3
// `/api/talk`). The brain's words are rendered as escaped text only, never as HTML.

type Turn = { who: "me" | "custody" | "note"; text: string };

const LINK = /https?:|www\.|\b[a-z0-9-]+\.[a-z]{2,}\b/i;

const SUGGESTIONS = [
	"What are you watching, and why is it quiet?",
	"How many worries never needed me?",
];

function failure(err: unknown): string {
	if (err instanceof ApiError) {
		if (err.status === 422)
			return "Worries with a link go through Hand over on Home, so you see exactly what will be read.";
		if (err.status === 429) return "One moment. Let's take this slowly.";
		if (err.status === 503)
			return "I couldn't reach Custody's brain just now. Nothing was claimed.";
	}
	return "Something went wrong. Nothing was claimed.";
}

export function Talk() {
	const [turns, setTurns] = useState<Turn[]>([]);
	const [text, setText] = useState("");
	const [busy, setBusy] = useState(false);

	const send = async (t: string) => {
		const said = t.trim();
		if (!said || busy) return;
		if (LINK.test(said)) {
			setTurns((ts) => [
				...ts,
				{ who: "me", text: said },
				{ who: "note", text: failure(new ApiError(422, "link")) },
			]);
			setText("");
			return;
		}
		setTurns((ts) => [...ts, { who: "me", text: said }]);
		setText("");
		setBusy(true);
		try {
			const r = await api.talk(said);
			setTurns((ts) => [...ts, { who: "custody", text: r.reply }]);
		} catch (err) {
			setTurns((ts) => [...ts, { who: "note", text: failure(err) }]);
		} finally {
			setBusy(false);
		}
	};

	const submit = (e: FormEvent) => {
		e.preventDefault();
		void send(text);
	};

	return (
		<Screen flushBottom>
			<BackLink href={href({ name: "home" })} label="Home" />
			<header className="mt-8 mb-8">
				<h1 className="font-display text-[38px] leading-none font-light tracking-tight">
					Talk to Custody
				</h1>
				<p className="mt-4 text-[15px] leading-relaxed text-muted">
					Tell it a worry in your own words, or ask what it's watching. It won't
					check again on demand; the watchers speak up when you need to act.
				</p>
			</header>

			{turns.length === 0 && (
				<ul className="space-y-2">
					{SUGGESTIONS.map((s) => (
						<li key={s}>
							<button
								type="button"
								onClick={() => void send(s)}
								className="w-full rounded-2xl border border-line bg-surface px-4 py-3 text-left text-[15px] text-ink transition-opacity active:opacity-70"
							>
								{s}
							</button>
						</li>
					))}
				</ul>
			)}

			<ol className="space-y-4" aria-live="polite" data-testid="talk-turns">
				{turns.map((t, i) => (
					<li
						// biome-ignore lint/suspicious/noArrayIndexKey: an append-only log
						key={i}
						className={
							t.who === "me"
								? "ml-10 rounded-2xl rounded-br-md bg-accent-soft px-4 py-3 text-[16px] text-ink"
								: t.who === "custody"
									? "mr-6 px-1 text-[16px] leading-relaxed whitespace-pre-line text-ink"
									: "mr-6 px-1 text-[15px] text-muted"
						}
						data-who={t.who}
					>
						{t.text}
					</li>
				))}
				{busy && (
					<li className="mr-6 px-1 text-[15px] text-faint">
						Custody is thinking…
					</li>
				)}
			</ol>

			<div className="sticky bottom-0 -mx-6 mt-auto bg-linear-to-t from-bg from-70% to-transparent px-6 pt-8 pb-[max(env(safe-area-inset-bottom),1.5rem)]">
				<form
					onSubmit={submit}
					className="flex items-center gap-2 rounded-full border border-line bg-surface py-2 pr-2 pl-5"
				>
					<label htmlFor="talk" className="sr-only">
						Say something to Custody
					</label>
					<input
						id="talk"
						value={text}
						maxLength={1000}
						onChange={(e) => setText(e.target.value)}
						placeholder="Say it in your own words"
						autoComplete="off"
						className="h-10 min-w-0 flex-1 bg-transparent text-[16px] text-ink placeholder:text-faint focus:outline-none"
					/>
					<button
						type="submit"
						disabled={!text.trim() || busy}
						className="h-10 rounded-full bg-accent px-4 text-sm font-medium text-on-accent transition-opacity disabled:opacity-30"
					>
						Send
					</button>
				</form>
			</div>
		</Screen>
	);
}
