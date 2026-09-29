import type { ReactNode } from "react";

export function Screen({
	children,
	flushBottom = false,
}: {
	children: ReactNode;
	/** Set when the screen pins its own footer to the bottom edge. */
	flushBottom?: boolean;
}) {
	const pb = flushBottom ? "" : "pb-[max(env(safe-area-inset-bottom),1.5rem)]";
	return (
		<main
			className={`mx-auto flex min-h-svh w-full max-w-md flex-col bg-bg px-6 pt-[max(env(safe-area-inset-top),1.5rem)] font-sans text-ink ${pb}`}
		>
			{children}
		</main>
	);
}

/** The slow "breathing" pulse shown when all is quiet. */
export function Orb({ size = 112 }: { size?: number }) {
	return (
		<div
			aria-hidden
			className="relative flex items-center justify-center"
			style={{ width: size, height: size }}
		>
			<div className="absolute inset-0 animate-breathe rounded-full bg-accent-soft" />
			<div className="absolute inset-[22%] animate-breathe rounded-full bg-accent/25 [animation-delay:-1.5s]" />
			<div className="absolute inset-[40%] rounded-full bg-accent/70" />
		</div>
	);
}

export function SectionLabel({ children }: { children: ReactNode }) {
	return (
		<h2 className="mb-3 text-xs font-medium tracking-[0.14em] text-faint uppercase">
			{children}
		</h2>
	);
}

export function BackLink({ href, label }: { href: string; label: string }) {
	return (
		<a
			href={href}
			className="-ml-1 inline-flex items-center gap-1 py-2 text-sm text-muted transition-colors hover:text-ink"
		>
			<svg
				aria-hidden
				viewBox="0 0 20 20"
				className="size-4"
				fill="none"
				stroke="currentColor"
				strokeWidth="1.6"
			>
				<path d="M12.5 4.5 7 10l5.5 5.5" strokeLinecap="round" />
			</svg>
			{label}
		</a>
	);
}

type ButtonProps = {
	children: ReactNode;
	onClick: () => void;
	variant?: "primary" | "quiet";
	disabled?: boolean;
};

export function Button({
	children,
	onClick,
	variant = "primary",
	disabled,
}: ButtonProps) {
	const look =
		variant === "primary"
			? "bg-accent text-on-accent"
			: "border border-line text-muted hover:text-ink";
	return (
		<button
			type="button"
			disabled={disabled}
			onClick={onClick}
			className={`h-12 flex-1 rounded-full px-6 text-[15px] font-medium transition-opacity disabled:opacity-50 ${look}`}
		>
			{children}
		</button>
	);
}
