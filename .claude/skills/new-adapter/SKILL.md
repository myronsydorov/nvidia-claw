---
name: new-adapter
description: Add a new watcher adapter (data source) with endpoint declarations, a policy snapshot and fixture tests.
disable-model-invocation: true
---
Add adapter: $ARGUMENTS

1. Read `docs/CONTRACTS.md` §1 (AdapterDeclaration) and one existing adapter in `warden/src/warden/adapters/` as the pattern.
2. Declare **every** endpoint precisely (host, port, method, path prefix). No wildcards. GET only unless an ADR allows otherwise. List needed secrets by name only.
3. Implement the runtime helper in `watcher_runtime/src/watcher_runtime/adapters/<name>.py` so it only calls the declared endpoints and returns plain Python data.
4. Record fixtures (sanitized; no personal data, no secrets) under `warden/tests/fixtures/<name>/`.
5. Tests: parsing from fixtures; the **policy generator snapshot** for a watcher that uses only this adapter; a negative test showing an undeclared host is absent from the generated policy.
6. Add the adapter to the list in CONTRACTS.md §1 and to the compiler's adapter catalogue prompt.
7. Run `uv run pytest warden/tests/adapters -q` and `make lint typecheck`, and paste the output.
8. Ask the `security-reviewer` subagent to review the diff.
