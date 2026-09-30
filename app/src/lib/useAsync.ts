import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveEvent } from "../api/events";

export type AsyncState<T> =
	| { state: "loading" }
	| { state: "ready"; data: T }
	| { state: "error"; error: Error };

/** Load on mount and whenever `key` changes; `reload()` refetches in place,
 *  keeping the current data on screen until the new data arrives. */
export function useAsync<T>(
	load: () => Promise<T>,
	key: string,
): AsyncState<T> & { reload: () => void } {
	const [s, setS] = useState<AsyncState<T>>({ state: "loading" });
	const [version, setVersion] = useState(0);
	const loaded = useRef<string | null>(null);
	// biome-ignore lint/correctness/useExhaustiveDependencies: reload only when the key or version changes
	useEffect(() => {
		let live = true;
		if (loaded.current !== key) setS({ state: "loading" });
		load().then(
			(data) => {
				if (!live) return;
				loaded.current = key;
				setS({ state: "ready", data });
			},
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
	}, [key, version]);
	const reload = useCallback(() => setVersion((v) => v + 1), []);
	return { ...s, reload };
}

/** Call `onEvent` for every live event while mounted. */
export function useLiveEvents(
	subscribe: (l: (e: LiveEvent) => void) => () => void,
	onEvent: (e: LiveEvent) => void,
): void {
	const handler = useRef(onEvent);
	handler.current = onEvent;
	useEffect(() => subscribe((e) => handler.current(e)), [subscribe]);
}
