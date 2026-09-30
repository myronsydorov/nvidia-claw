import { type FormEvent, useState } from "react";
import { verifyToken } from "../api/http";
import { Orb, Screen } from "../components/ui";
import { setToken } from "../lib/token";

type Phase = "idle" | "checking" | "wrong" | "unreachable";

export function Connect({ onConnected }: { onConnected: () => void }) {
	const [token, setValue] = useState("");
	const [phase, setPhase] = useState<Phase>("idle");

	const submit = async (e: FormEvent) => {
		e.preventDefault();
		const t = token.trim();
		if (!t) return;
		setPhase("checking");
		try {
			if (!(await verifyToken(t))) return setPhase("wrong");
		} catch {
			return setPhase("unreachable");
		}
		setToken(t);
		onConnected();
	};

	return (
		<Screen>
			<header className="flex flex-col items-center pt-14 pb-12 text-center">
				<Orb />
				<h1 className="mt-10 font-display text-[40px] leading-none font-light tracking-tight">
					Connect
				</h1>
				<p className="mt-4 max-w-[18rem] text-[15px] leading-relaxed text-muted">
					Paste your Warden's device token. It stays on this device.
				</p>
			</header>
			<form onSubmit={submit} className="flex flex-col gap-4">
				<label htmlFor="token" className="sr-only">
					Device token
				</label>
				<input
					id="token"
					type="password"
					value={token}
					onChange={(e) => setValue(e.target.value)}
					placeholder="Device token"
					autoComplete="off"
					className="h-12 rounded-full border border-line bg-surface px-5 text-[16px] text-ink placeholder:text-faint focus:outline-none"
				/>
				<button
					type="submit"
					disabled={!token.trim() || phase === "checking"}
					className="h-12 rounded-full bg-accent px-6 text-[15px] font-medium text-on-accent transition-opacity disabled:opacity-50"
				>
					{phase === "checking" ? "Checking…" : "Connect"}
				</button>
				<p className="h-5 text-center text-sm text-muted" role="status">
					{phase === "wrong" && "That token didn't work."}
					{phase === "unreachable" && "Can't reach your Warden right now."}
				</p>
			</form>
		</Screen>
	);
}
