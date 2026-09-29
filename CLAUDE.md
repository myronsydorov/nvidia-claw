@AGENTS.md

# Claude Code specifics
- **Workflow:** for multi-file work, go explore → plan (plan mode) → implement → verify → commit. For a change you could describe in one sentence, skip the plan.
- **Verify, then show evidence.** Run the task's check from `docs/PLAN.md` and paste the output. For app work, take a mobile-viewport screenshot and compare it with the design notes.
- **Subagents:**
  - use subagents for broad codebase or doc investigation;
  - `security-reviewer` for any change under `warden/src/warden/sandbox/`, `policies/`, `relay/` or `warden/src/warden/reassurance/`;
  - `verifier` to check the diff against the task's acceptance criteria before you call it done.
- **Skills:** `/new-adapter` adds a watcher adapter the right way. `/demo-check` runs the pre-recording checklist.
- **When compacting, preserve:** the current task ID, the list of modified files, the test commands, and open decisions.
- IMPORTANT: never run `openshell`, `nemoclaw` or `docker` commands against the production host unless the task says so. Use `CUSTODY_SANDBOX=mock` locally.
