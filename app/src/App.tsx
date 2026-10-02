import { useState } from "react";
import { mockMode } from "./api/client";
import { navigate, useRoute } from "./lib/router";
import { getToken } from "./lib/token";
import { Connect } from "./screens/Connect";
import { HandOver } from "./screens/HandOver";
import { Home } from "./screens/Home";
import { Ledger } from "./screens/Ledger";
import { PairEnter, PairShow } from "./screens/Pair";
import { People } from "./screens/People";
import { Sharing } from "./screens/Sharing";
import { Talk } from "./screens/Talk";
import { WorryDetail } from "./screens/WorryDetail";

function App() {
	const route = useRoute();
	const [connected, setConnected] = useState(() => mockMode || !!getToken());
	if (route.name === "connect" || !connected || (!mockMode && !getToken())) {
		return (
			<Connect
				onConnected={() => {
					setConnected(true);
					navigate({ name: "home" });
				}}
			/>
		);
	}
	switch (route.name) {
		case "home":
			return <Home />;
		case "hand-over":
			return <HandOver key={route.text} text={route.text} />;
		case "worry":
			return <WorryDetail id={route.id} />;
		case "people":
			return <People />;
		case "sharing":
			return <Sharing />;
		case "ledger":
			return <Ledger />;
		case "talk":
			return <Talk />;
		case "pair-show":
			return <PairShow />;
		case "pair-enter":
			return <PairEnter />;
	}
}

export default App;
