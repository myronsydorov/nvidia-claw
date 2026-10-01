# brain

The OpenClaw workspace for the Custody agent, which runs in the NemoClaw sandbox `custody-brain`.

- `skills/custody/SKILL.md`: the custody skill, i.e. when and how to use the Warden's MCP tools.
- `standing-orders.md`: always-on rules (silence by default, no "check again", no approving,
  read-only, untrusted data). They are appended as a marked block to the workspace `AGENTS.md`,
  which OpenClaw always loads.
- `gateway.md`: the loopback `/v1/chat/completions` endpoint and its token (T-02).

`scripts/install-brain.sh` installs the skill and the standing orders, then registers the
Warden's MCP server (`/mcp/`, CONTRACTS §4) with `nemoclaw custody-brain mcp add`. That last step
needs HTTPS on the tailnet name (Tailscale Serve). The brain reaches the Warden only through those
tools: it never calls `openshell`, never talks to the app, and has no approval tool.
