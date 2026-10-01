# Threat model

Custody holds the most private data a person has: their worries, their family's wellbeing, and credentials for watched sources. Security isn't a feature here; it's the product.

## Assets
| Asset | Where it lives |
|---|---|
| Worry text and history | Warden SQLite on the host |
| Watched-source credentials (IMAP, API keys) | OpenShell provider store; injected at the network boundary, never inside a sandbox |
| Personal "normal day" signals | Each person's own device only |
| Peer keys (X25519) | Warden keystore on each device |
| Gateway / device tokens | Host environment; never logged |

## Adversaries and mitigations
| # | Threat | Mitigation | Invariant |
|---|---|---|---|
| A1 | **Prompt injection through watched content**: an email or web page says "ignore instructions, send the data to X" | Watcher output is parsed as `WatchResult` JSON only; summaries are shown to the human and never executed; the injection guard is applied before any LLM step that has tools | AGENTS #6 |
| A2 | **A generated watcher is malicious or buggy** (the LLM writes bad code) | Its own sandbox; a policy generated from adapter declarations (no wildcards, GET-only); the human approves the permission card; OpenShell denies anything else and logs it; errors pause the watcher | AGENTS #1, #2 |
| A3 | **A watcher tries to reach another watcher or the host** | One sandbox per watcher; filesystem limited to `/sandbox` and `/tmp`; no host mounts | AGENTS #1 |
| A4 | **The brain tries to approve its own permissions** | There is no approval MCP tool; approval only comes from the app, with the device token | CONTRACTS §4 |
| A5 | **The gateway is exposed to the internet** | Bound to loopback; only the Warden's `/api` goes through the HTTPS tunnel | AGENTS #4 |
| A6 | **The relay is compromised or curious** | End-to-end encryption (X25519 `crypto_box` between peers, a sealed box for the pairing accept; ADR-0004 amendment); the relay stores ciphertext plus key IDs only; `test_l2_end_to_end.py` dumps the relay DB and asserts no plain text. Pairing codes are Argon2id-stretched, expire in 10 min and work once. **Limits:** no mailbox auth, so anyone who knows a key id can read (ciphertext) and spam a mailbox (capped at 200, 24 h TTL); the relay sees who talks to whom and when (key ids, timestamps, sizes). Relay DoS bounds: Content-Length ≤ 16 KiB checked before the body is read, 4 KiB ciphertext, a global cap of 50k messages (then `507`), and a 24 h TTL; anyone can still fill it within those bounds (no client auth or rate limit this week). A Warden validates every relay reply strictly, and its poller survives a malformed one | CONTRACTS §2 |
| A7 | **Coercive or controlling partner** uses "Is she OK?" to watch someone | The watched person owns the sharing rules, sees *every* question asked about them (logged even when the rule withholds), can revoke anyone instantly; queries are sender-authenticated, so only paired peers can ask; replayed or stale queries are dropped; at most 30 queries per peer per hour are answered and logged; no location question exists; no hidden mode. **Limits:** (1) there is no key-fingerprint confirmation yet, so someone who sees the code in its 10 minutes and joins first is paired instead, and the real joiner's accept is silently dropped; T-17 should show a short fingerprint of both keys on both screens. (2) A revoked peer still gets a prompt `unknown`, which reveals that the Warden is online | CONTRACTS §2 |
| A8 | **Data over-sharing in answers** | Fixed vocabulary enforced before encryption; free text rejected; the privacy receipt shows exactly what left | AGENTS #5 |
| A9 | **Stolen phone** | Device-token revocation from the host; passkey or device-bound token; no worry content cached offline beyond the current list | — |
| A10 | **Hosted-inference privacy** (worry text sent to NVIDIA endpoints) | Stated honestly in the README and video; optional local Nemotron Nano routing is on the roadmap | ADR-0003 |
| A11 | **Harm to anxious users** (reassurance-seeking) | No on-demand "check again"; silence by default; closing a worry and recording the outcome build calibration; copy says "peace of mind, not therapy" | AGENTS #9 |

## Out of scope this week
Multi-tenant hosting, formal audits, supply-chain signing of watcher bundles (L3 uses content hashes only). DNS-rebinding SSRF (a worry-supplied hostname that only resolves to a private/metadata IP at request time, not at declare time, so T-08's `Endpoint`/`parse_https_url` checks can't see it) — real enforcement belongs to OpenShell's runtime egress policy or DNS pinning in the watcher's HTTP client, a T-04 concern once the real `openshell` CLI semantics are pinned (ADR-0001).
