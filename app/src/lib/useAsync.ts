import { useEffect, useState } from "react";

export type AsyncState<T> =
	| { state: "loading" }
	| { state: "ready"; data: T }
	| { state: "error"; error: Error };

export function useAsync<T>(
	load: () => Promise<T>,
	key: string,
): AsyncState<T> {
	const [s, setS] = useState<AsyncState<T>>({ state: "loading" });
	// biome-ignore lint/correctness/useExhaustiveDependencies: reload only when the key changes
	useEffect(() => {
		let live = true;
		setS({ state: "loading" });
		load().then(
			(data) => live && setS({ state: "ready", data }),
			(e: unknown) =>
				live &&
				setS({
					state: "error",
					error: e instanceof Error ? e : new Error(String(e)),
				}),
		);
		return () => {
			live = false;
		};
	}, [key]);
	return s;
}
