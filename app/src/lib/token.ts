// The bearer device token for the Warden's /api (CONTRACTS §3). Typed in once
// on the Connect screen and kept on this device only, never in the bundle.

const KEY = "custody.deviceToken";

export function getToken(): string | null {
	try {
		return localStorage.getItem(KEY);
	} catch {
		return null;
	}
}

export function setToken(token: string): void {
	try {
		localStorage.setItem(KEY, token);
	} catch {
		// Private mode etc.: the app will ask again next time.
	}
}

export function clearToken(): void {
	try {
		localStorage.removeItem(KEY);
	} catch {
		// nothing to clear
	}
}
