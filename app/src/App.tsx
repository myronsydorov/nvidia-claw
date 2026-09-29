import { useRoute } from "./lib/router";
import { HandOver } from "./screens/HandOver";
import { Home } from "./screens/Home";
import { WorryDetail } from "./screens/WorryDetail";

function App() {
	const route = useRoute();
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
