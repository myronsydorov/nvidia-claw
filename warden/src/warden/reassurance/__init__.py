"""Layer 2: private reassurance between paired Wardens (CONTRACTS §2, ADR-0004).

`vocabulary` enforces the fixed answer vocabulary before anything is encrypted, `crypto`
and `keys` hold the X25519 material, `signal` computes the local "normal day" answer, and
`service` ties pairing, asking and answering to the relay mailbox.
"""
