---
id: automate-a-bot-protected-surface-through-the-real-session-no
kind: pattern
title: Automate a bot-protected surface through the real session, not a fresh profile
date: 2026-07-20
---

When you automate a consumer-web surface sitting behind bot/WAF protection, a standalone headless or scripted browser profile reads as a bot and gets blocked — and the interactive login page is blocked on that same profile too, so re-authenticating it is a dead end, not a fix. The signal the defense keys on is the pairing of a real, already-authenticated session with a real browser fingerprint; a freshly minted automation profile has neither. So the durable design is to drive the user's real, logged-in browser (via an extension or an attach-to-running-session mechanism) rather than spinning up an isolated automation profile you then try to log in.

Two checks catch this before you build the wrong thing:

1. Read the operating canon first. If the project's own rules already prescribe a mechanism for that surface (e.g. "drive the real browser"), then reaching for a standalone-profile build is silent drift from the rules, not a fresh design decision. Confirm what the canon mandates before choosing an approach.

2. When two sibling channels diverge — one built on approach X works, a parallel one built on approach Y is blocked — suspect the approach, not the credentials. The blocked channel almost certainly drifted onto the flagged path; the failure is architectural, not an expired login.

Once a profile is flagged, re-logging-in that same profile will keep failing because the fingerprint is what's flagged, not the session. The fix is to move onto the real, trusted session — never to keep re-authenticating the profile the defense already rejected.
