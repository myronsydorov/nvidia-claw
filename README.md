# Custody

**An AI that worries for you, and for the people you love, and speaks up only when someone actually needs you.**

Built for the NVIDIA Claw Agent Challenge (Berlin) on NemoClaw (OpenClaw + OpenShell) with Nemotron.

- **Hand over a worry.** Custody writes a watcher for it, locks the watcher in its **own OpenShell sandbox** with only the permissions you approve, and stays silent until you need to act.
- **Ask about someone you love.** Their agent answers "normal day" from their own device. **No location, no data, just one tiny encrypted answer.**
- **Learn.** 91.4% of worries never come true (LaFreniere & Newman). Custody shows you *your* number.

> Work in progress. Docs: [`docs/DESIGN.md`](docs/DESIGN.md) · [`docs/PLAN.md`](docs/PLAN.md) · [`docs/CONTRACTS.md`](docs/CONTRACTS.md) · [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) · [`docs/adr/`](docs/adr/)

## Honest limits (v1)
Worry text is processed by NVIDIA's hosted Nemotron endpoints (see ADR-0003). Reassurance answers are always computed on the answering person's own device.

## Quickstart
_Filled in by task T-21._
