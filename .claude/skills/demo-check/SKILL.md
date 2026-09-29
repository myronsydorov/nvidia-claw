---
name: demo-check
description: Pre-recording checklist for the challenge video. Verifies the live system and the story before recording.
disable-model-invocation: true
---
Run each check against the **live** Brev host and report ✅/❌ with evidence:

1. `/api/health` is healthy; sandbox count matches the active watchers.
2. Hand-over flow on the phone: a new worry → the "taking custody" animation → permission card → approve → status `watching` in under 60 seconds.
3. At least one watcher has produced `act_now` in real usage, and the alert card shows evidence.
4. An **unusual** worry (not parcel or weather) compiles and passes its dry run.
5. "Is Anna OK?" gets an answer from the second machine in under 10 seconds; the privacy receipt is shown; the second machine's OpenShell egress log shows only relay traffic.
6. Ledger numbers match `/api/ledger`; nothing fake is presented as real (anything simulated is labelled).
7. The app is installed to the home screen, dark and light mode both look right, and there are no console errors.
8. The README states the hosted-inference privacy limitation honestly (ADR-0003).
9. `scripts/restart.sh` has been tested since the last deploy.
10. The video script in `docs/DESIGN.md` §8 matches what the system actually does today.

End with the list of ❌ items, most important first.
