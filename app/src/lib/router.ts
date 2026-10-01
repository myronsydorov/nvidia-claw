import { useEffect, useState } from "react";

// A tiny hash router: #/, #/hand-over?text=…, #/worry/:id, #/people,
// #/sharing, #/ledger, #/pair/show, #/pair/enter, #/connect

export type Route =
	| { name: "home" }
	| { name: "hand-over"; text: string }
	| { name: "worry"; id: string }
	| { name: "people" }
	| { name: "sharing" }
	| { name: "ledger" }
	| { name: "pair-show" }
	| { name: "pair-enter" }
	| { name: "connect" };

export function parseHash(hash: string): Route {
	const [path = "", query = ""] = hash.replace(/^#/, "").split("?");
	if (path === "/hand-over") {
		return {
			name: "hand-over",
			text: new URLSearchParams(query).get("text") ?? "",
		};
	}
	if (path === "/connect") return { name: "connect" };
	if (path === "/people") return { name: "people" };
	if (path === "/sharing") return { name: "sharing" };
	if (path === "/ledger") return { name: "ledger" };
	if (path === "/pair/show") return { name: "pair-show" };
	if (path === "/pair/enter") return { name: "pair-enter" };
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
		case "people":
			return "#/people";
		case "sharing":
			return "#/sharing";
		case "ledger":
			return "#/ledger";
		case "pair-show":
			return "#/pair/show";
		case "pair-enter":
			return "#/pair/enter";
		case "connect":
			return "#/connect";
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
