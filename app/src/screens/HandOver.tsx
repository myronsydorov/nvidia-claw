import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { WorryDetail } from "../api/schemas";
import { PermissionCard } from "../components/PermissionCard";
import { BackLink, Orb, Screen } from "../components/ui";
import { navigate } from "../lib/router";

const STEPS = [
	"Understanding",
	"Writing a watcher",
	"Building its jail",
	"Asking your permission",
] as const;
const STEP_MS = 1400;
const DONE_MS = 2600;

type Phase = "steps" | "permission" | "allowed" | "denied" | "error";

function StepRow({
	label,
	state,
}: {
	label: string;
	state: "todo" | "now" | "done";
}) {
	return (
		<li className="flex items-center gap-4 py-2.5">
			<span
				className="relative flex size-5 items-center justify-center"
				aria-hidden
			>
				{state === "done" && (
					<svg
						aria-hidden="true"
						viewBox="0 0 20 20"
						className="size-5 text-accent"
						fill="none"
						stroke="currentColor"
						strokeWidth="1.8"
					>
						<path
							d="m5 10.5 3.2 3L15 6.5"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
				)}
				{state === "now" && (
					<>
						<span className="absolute size-5 animate-glow rounded-full bg-accent-soft" />
						<span className="size-2 rounded-full bg-accent" />
					</>
				)}
				{state === "todo" && <span className="size-1.5 rounded-full bg-line" />}
			</span>
			<span
				className={`text-[17px] transition-colors duration-700 ${
					state === "todo"
						? "text-faint"
						: state === "now"
							? "text-ink"
							: "text-muted"
				}`}
			>
				{label}
				{state === "now" && <span className="text-faint">…</span>}
			</span>
			<span className="sr-only">
				{state === "done" ? "done" : state === "now" ? "in progress" : ""}
			</span>
		</li>
	);
}

export function HandOver({ text }: { text: string }) {
	const [step, setStep] = useState(0);
	const [phase, setPhase] = useState<Phase>("steps");
	const [detail, setDetail] = useState<WorryDetail | null>(null);
	const [busy, setBusy] = useState(false);
	const started = useRef(false);

	// Hand over exactly once (StrictMode runs effects twice; the ref survives).
	useEffect(() => {
		if (!text) {
			navigate({ name: "home" });
			return;
		}
		if (started.current) return;
		started.current = true;
		api.handOver(text).then(setDetail, () => setPhase("error"));
	}, [text]);

	// Walk the steps; the last one waits for the watcher to be ready.
	useEffect(() => {
		if (phase !== "steps") return;
		if (step < STEPS.length - 1) {
			const t = setTimeout(() => setStep((s) => s + 1), STEP_MS);
			return () => clearTimeout(t);
		}
		if (detail) {
			const t = setTimeout(() => setPhase("permission"), STEP_MS);
			return () => clearTimeout(t);
		}
	}, [step, phase, detail]);

	useEffect(() => {
		if (phase !== "allowed" && phase !== "denied") return;
		const t = setTimeout(() => navigate({ name: "home" }), DONE_MS);
		return () => clearTimeout(t);
	}, [phase]);

	const decide = async (allow: boolean) => {
		if (!detail) return;
		setBusy(true);
		try {
			await (allow ? api.approve(detail.worry.id) : api.deny(detail.worry.id));
			setPhase(allow ? "allowed" : "denied");
		} catch {
			setPhase("error");
		}
	};

	if (phase === "allowed" || phase === "denied") {
		return (
			<Screen>
				<button
					type="button"
					onClick={() => navigate({ name: "home" })}
					className="flex flex-1 animate-rise flex-col items-center justify-center text-center"
				>
					<Orb size={140} />
					<h1 className="mt-12 font-display text-[44px] leading-none font-light tracking-tight">
						{phase === "allowed" ? "I've got this." : "Parked."}
					</h1>
					<p className="mt-5 max-w-[17rem] text-[15px] leading-relaxed text-muted">
						{phase === "allowed"
							? "I'll stay quiet unless you need to act."
							: "We'll look at it together at worry time."}
					</p>
				</button>
			</Screen>
		);
	}

	return (
		<Screen>
			<BackLink href="#/" label="Back" />
			<p className="mt-10 font-display text-[26px] leading-snug font-light text-ink">
				“{text}”
			</p>

			{phase === "error" ? (
				<p className="mt-10 text-[15px] text-muted">
					Something went wrong taking this one. Nothing was set up. Try handing
					it over again in a moment.
				</p>
			) : (
				<ol className="mt-10">
					{STEPS.map((label, i) => (
						<StepRow
							key={label}
							label={label}
							state={
								phase === "permission" || i < step
									? "done"
									: i === step
										? "now"
										: "todo"
							}
						/>
					))}
				</ol>
			)}

			{phase === "permission" && detail?.watcher && (
				<div className="mt-auto animate-rise pt-10">
					<PermissionCard
						watcher={detail.watcher}
						busy={busy}
						onDecide={decide}
					/>
				</div>
			)}
		</Screen>
	);
}
