import { useState } from "react";
import { mockMode } from "./api/client";
import { navigate, useRoute } from "./lib/router";
import { getToken } from "./lib/token";
import { Connect } from "./screens/Connect";
import { HandOver } from "./screens/HandOver";
import { Home } from "./screens/Home";
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
	}
}

export default App;
