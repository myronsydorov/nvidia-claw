# ADR-0001: One OpenShell sandbox per watcher

**Status:** Accepted (timings to be filled in by spike T-04)

## Context
Watchers are code written by the agent. We want per-watcher least privilege: a parcel watcher may reach the DHL API and nothing else. OpenShell identifies a process by the **real path of its executable** (with a recorded hash and process ancestry). So all Python scripts that share one interpreter look like the same program, and one sandbox can't give two scripts different network permissions.

## Decision
Each watcher runs in **its own OpenShell sandbox** with its own generated policy. Only `warden/src/warden/sandbox/` creates, applies policy to, execs in and deletes these sandboxes.

## Consequences
- ✅ Real isolation per watcher; a clear story for the video ("every worry gets its own jail"); denials are logged per watcher.
- ⚠️ A container per watcher costs startup time and memory. **The spike measures:** create time, exec time, memory per idle sandbox.
- **Fallback if it's too slow or heavy:** a pool of pre-warmed sandboxes (policy applied when a watcher is assigned), or start the sandbox per run and delete it afterwards.

## Spike results
| metric | value |
|---|---|
| create → Ready | _tbd_ |
| policy set --wait | _tbd_ |
| exec run.py | _tbd_ |
| RAM per idle sandbox | _tbd_ |
| denied egress visible in logs | _tbd_ |
