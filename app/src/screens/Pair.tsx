import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { PairingStartResponse, Peer } from "../api/schemas";
import { BackLink, Button, Screen } from "../components/ui";
import { formatCode, joinFailure } from "../lib/reassurance";
import { href, navigate } from "../lib/router";

// Pairing with a one-time code (CONTRACTS §2). One phone shows a code, the other
// types it. Then both screens show the same 8-digit fingerprint, and the two
// people compare them: if someone else saw the code and joined first, the
// numbers differ and either side can undo the pairing.

const statusOf = (e: unknown) => (e instanceof ApiError ? e.status : null);

const inputClass =
	"h-12 rounded-full border border-line bg-surface px-5 text-[16px] text-ink placeholder:text-faint focus:outline-none";
const submitClass =
	"h-12 rounded-full bg-accent px-6 text-[15px] font-medium text-on-accent transition-opacity disabled:opacity-50";

function Header({ title, lead }: { title: string; lead: string }) {
	return (
		<>
			<BackLink href={href({ name: "people" })} label="People" />
			<header className="mt-8 mb-10">
				<h1 className="font-display text-[38px] leading-none font-light tracking-tight">
					{title}
				</h1>
				<p className="mt-4 text-[15px] leading-relaxed text-muted">{lead}</p>
			</header>
		</>
	);
}

function NameField({
	value,
	onChange,
}: {
	value: string;
	onChange: (v: string) => void;
}) {
	return (
		<>
			<label htmlFor="pair-name" className="text-sm text-muted">
				What do you call them?
			</label>
			<input
				id="pair-name"
				value={value}
				onChange={(e) => onChange(e.target.value)}
				placeholder="Anna"
				maxLength={64}
				autoComplete="off"
				className={inputClass}
			/>
		</>
	);
}

/** Shown on both phones once paired. The numbers must match. */
function FingerprintCheck({ peer }: { peer: Peer }) {
	const [phase, setPhase] = useState<
		"checking" | "confirming" | "removing" | "removed" | "failed"
	>("checking");
	const name = peer.display_name;

	const busy = phase === "confirming" || phase === "removing";

	const matches = async () => {
		setPhase("confirming");
		try {
			await api.confirm(peer.id);
			navigate({ name: "people" });
		} catch {
			setPhase("failed");
		}
	};

	const mismatch = async () => {
		setPhase("removing");
		try {
			await api.unpair(peer.id);
			setPhase("removed");
		} catch {
			setPhase("failed");
		}
	};

	if (phase === "removed") {
		return (
			<section className="animate-rise" aria-label="Pairing undone">
				<p className="text-[17px] leading-relaxed text-ink">
					Unpaired. Nothing about you was shared.
				</p>
				<p className="mt-2 text-[15px] leading-relaxed text-muted">
					Until you confirm a match, any question about you only gets "Not
					enough to say". Someone else may have seen the code: start again
					somewhere no one else can see the screen.
				</p>
				<div className="mt-8 flex">
					<Button onClick={() => navigate({ name: "people" })}>
						Back to People
					</Button>
				</div>
			</section>
		);
	}

	return (
		<section className="animate-rise" aria-label="Check the pairing">
			<p className="text-[17px] text-ink">Paired with {name}.</p>
			<p className="mt-2 text-[15px] leading-relaxed text-muted">
				Check that {name}'s screen shows the same number:
			</p>
			<p
				data-testid="fingerprint"
				className="mt-6 mb-8 text-center font-mono text-[40px] tracking-[0.12em] text-ink"
			>
				{peer.fingerprint}
			</p>
			<div className="flex gap-3">
				<Button disabled={busy} onClick={matches}>
					It matches
				</Button>
				<Button variant="quiet" disabled={busy} onClick={mismatch}>
					It doesn't match
				</Button>
			</div>
			{phase === "failed" && (
				<p className="mt-4 text-sm text-muted" role="status">
					That didn't go through. Try again.
				</p>
			)}
		</section>
	);
}

type ShowPhase =
	| { state: "naming" }
	| { state: "starting" }
	| { state: "showing"; pairing: PairingStartResponse }
	| { state: "paired"; peer: Peer }
	| { state: "expired" }
	| { state: "failed"; status: number | null };

export function PairShow() {
	const [name, setName] = useState("");
	const [phase, setPhase] = useState<ShowPhase>({ state: "naming" });

	const start = async (e: FormEvent) => {
		e.preventDefault();
		setPhase({ state: "starting" });
		try {
			setPhase({
				state: "showing",
				pairing: await api.startPairing(name.trim()),
			});
		} catch (err) {
			setPhase({ state: "failed", status: statusOf(err) });
		}
	};

	// Wait for the other phone. No event exists for this, so poll gently.
	const pairingId = phase.state === "showing" ? phase.pairing.pairing_id : null;
	useEffect(() => {
		if (!pairingId) return;
		let stopped = false;
		const tick = async () => {
			try {
				const s = await api.pairingStatus(pairingId);
				if (stopped) return;
				if (s.state === "paired" && s.peer) {
					setPhase({ state: "paired", peer: s.peer });
				} else if (s.state === "expired") {
					setPhase({ state: "expired" });
				}
			} catch {
				// A blip; the next tick tries again.
			}
		};
		const timer = setInterval(tick, 1500);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	}, [pairingId]);

	return (
		<Screen>
			<Header
				title="Show a code"
				lead="They type it on their phone. It lasts 10 minutes and works once. Only public keys are exchanged."
			/>
			{(phase.state === "naming" || phase.state === "starting") && (
				<form onSubmit={start} className="flex flex-col gap-4">
					<NameField value={name} onChange={setName} />
					<button
						type="submit"
						disabled={!name.trim() || phase.state === "starting"}
						className={submitClass}
					>
						{phase.state === "starting" ? "Making a code…" : "Show a code"}
					</button>
				</form>
			)}
			{phase.state === "showing" && (
				<section className="animate-rise" aria-label="Pairing code">
					<p className="text-[15px] text-muted">
						Type this on {name.trim()}'s phone:
					</p>
					<p
						data-testid="pairing-code"
						className="my-8 text-center font-mono text-[44px] tracking-[0.12em] text-ink"
					>
						{formatCode(phase.pairing.code)}
					</p>
					<p className="text-sm text-faint" role="status">
						Waiting for {name.trim()}…
					</p>
				</section>
			)}
			{phase.state === "paired" && <FingerprintCheck peer={phase.peer} />}
			{phase.state === "expired" && (
				<p className="text-[15px] leading-relaxed text-muted" role="status">
					The code expired. Nothing was paired.
				</p>
			)}
			{phase.state === "failed" && (
				<p className="text-[15px] leading-relaxed text-muted" role="status">
					{phase.status === 503
						? "Your Warden can't reach the relay right now. Nothing was paired."
						: "That didn't go through. Nothing was paired."}
				</p>
			)}
		</Screen>
	);
}

type EnterPhase =
	| { state: "typing"; error: string | null }
	| { state: "joining" }
	| { state: "paired"; peer: Peer };

export function PairEnter() {
	const [name, setName] = useState("");
	const [code, setCode] = useState("");
	const [phase, setPhase] = useState<EnterPhase>({
		state: "typing",
		error: null,
	});

	const join = async (e: FormEvent) => {
		e.preventDefault();
		setPhase({ state: "joining" });
		try {
			setPhase({
				state: "paired",
				peer: await api.joinPairing(code.trim(), name.trim()),
			});
		} catch (err) {
			setPhase({ state: "typing", error: joinFailure(statusOf(err)) });
		}
	};

	return (
		<Screen>
			<Header
				title="Enter their code"
				lead="The code on their phone. Only public keys are exchanged."
			/>
			{phase.state === "paired" ? (
				<FingerprintCheck peer={phase.peer} />
			) : (
				<form onSubmit={join} className="flex flex-col gap-4">
					<NameField value={name} onChange={setName} />
					<label htmlFor="pair-code" className="text-sm text-muted">
						Their code
					</label>
					<input
						id="pair-code"
						value={code}
						onChange={(e) => setCode(e.target.value)}
						placeholder="K7M2 Q9XA"
						maxLength={12}
						autoCapitalize="characters"
						autoComplete="off"
						spellCheck={false}
						className={`${inputClass} font-mono tracking-[0.12em]`}
					/>
					<button
						type="submit"
						disabled={
							!name.trim() ||
							code.trim().length < 8 ||
							phase.state === "joining"
						}
						className={submitClass}
					>
						{phase.state === "joining" ? "Pairing…" : "Pair"}
					</button>
					<p className="min-h-5 text-sm text-muted" role="status">
						{phase.state === "typing" && phase.error}
					</p>
				</form>
			)}
		</Screen>
	);
}
