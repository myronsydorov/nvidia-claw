import type { Watcher } from "../api/schemas";
import { every } from "../lib/time";
import { Button } from "./ui";

type Props = {
	watcher: Watcher;
	/** Omit for the read-only "its jail" view. */
	onDecide?: (allow: boolean) => void;
	busy?: boolean;
};

export function PermissionCard({ watcher, onDecide, busy }: Props) {
	return (
		<section className="rounded-3xl border border-line bg-surface p-5">
			{onDecide && (
				<p className="mb-4 text-[15px] text-muted">
					Your watcher asks to reach:
				</p>
			)}
			<ul className="space-y-3">
				{watcher.policy_summary.map((line) => (
					<li key={`${line.method} ${line.host}${line.path}`}>
						<p className="font-mono text-[13px] leading-snug break-all text-ink">
							<span className="mr-2 text-accent">{line.method}</span>
							{line.host}
							{line.path}
						</p>
						<p className="mt-1 text-sm text-faint">to {line.why}</p>
					</li>
				))}
			</ul>
			<p className="mt-4 text-[15px] font-medium text-ink">Nothing else.</p>
			<p className="mt-1 text-sm text-faint">
				Reads only, {every(watcher.interval_s)}, alone in its own sandbox{" "}
				<span className="font-mono text-[12px]">{watcher.sandbox_name}</span>.
			</p>
			{onDecide && (
				<div className="mt-6 flex gap-3">
					<Button disabled={busy} onClick={() => onDecide(true)}>
						Allow
					</Button>
					<Button
						variant="quiet"
						disabled={busy}
						onClick={() => onDecide(false)}
					>
						Deny
					</Button>
				</div>
			)}
		</section>
	);
}
