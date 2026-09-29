import { useEffect, useState } from "react";

// A tiny hash router: #/, #/hand-over?text=…, #/worry/:id

export type Route =
	| { name: "home" }
	| { name: "hand-over"; text: string }
	| { name: "worry"; id: string };

export function parseHash(hash: string): Route {
	const [path = "", query = ""] = hash.replace(/^#/, "").split("?");
	if (path === "/hand-over") {
		return {
			name: "hand-over",
			text: new URLSearchParams(query).get("text") ?? "",
		};
	}
	const worry = /^\/worry\/([A-Za-z0-9_]+)$/.exec(path);
	if (worry?.[1]) return { name: "worry", id: worry[1] };
	return { name: "home" };
}

export function href(route: Route): string {
	switch (route.name) {
		case "home":
			return "#/";
		case "hand-over":
			return `#/hand-over?${new URLSearchParams({ text: route.text })}`;
		case "worry":
			return `#/worry/${route.id}`;
	}
}

export function navigate(route: Route): void {
	window.location.hash = href(route);
}

export function useRoute(): Route {
	const [route, setRoute] = useState(() => parseHash(window.location.hash));
	useEffect(() => {
		const onChange = () => {
			setRoute(parseHash(window.location.hash));
			window.scrollTo(0, 0);
		};
		window.addEventListener("hashchange", onChange);
		return () => window.removeEventListener("hashchange", onChange);
	}, []);
	return route;
}
