# ADR-0003: Hosted Nemotron inference (NVIDIA Build) for v1

**Status:** Accepted

## Context
There's no local NVIDIA GPU. NemoClaw supports hosted NVIDIA endpoints without a GPU. Local inference on macOS has known routing gaps (NemoClaw issue #260).

## Decision
Use NVIDIA Build hosted Nemotron models for triage, code generation and chat. Keep model routing configurable, so a stronger hosted model can take code generation if Nemotron's watcher code quality isn't good enough.

## Consequences
- ✅ No GPU needed; fastest path to working.
- ⚠️ Worry text leaves the host for NVIDIA's endpoint. **We say this honestly** in the README and video, and never claim "nothing leaves your device" for L1.
- 🔜 Roadmap: route private content to a local Nemotron Nano on a GPU machine via NemoClaw's routing.
- Note: L2 answers are still computed **on the person's own device**, and only the fixed-vocabulary answer leaves it.
