# ADR-0002: Installable web app (PWA) instead of a native app or Telegram

**Status:** Accepted

## Context
Telegram looks cheap for a product demo. A native iOS app can't be built, signed and distributed in 3 days.

## Decision
A React + Vite + TypeScript **installable web app**, served by the Warden over an HTTPS tunnel. Added to the home screen, it opens full-screen, and web push works (iOS 16.4+ once installed). Telegram remains a developer and debug channel only.

## Consequences
- ✅ Looks and feels like an app; one codebase; fast to iterate on; screenshots and video straight from a phone.
- ⚠️ iOS push only works after "Add to Home Screen", so the video shows the installed app.
- ⚠️ No background sensors on the phone, so "normal day" signals come from the person's computer and Warden in v1.
