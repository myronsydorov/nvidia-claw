# brain

The OpenClaw workspace for the Custody agent: `skills/custody/SKILL.md`, standing orders (silence by default, never approve its own permissions, no "check again" loops), and config snippets for the loopback chat endpoint. The brain reaches the Warden only through MCP tools (`docs/CONTRACTS.md` §4) — it never calls `openshell` or talks to the app directly.

Populated starting T-11.
