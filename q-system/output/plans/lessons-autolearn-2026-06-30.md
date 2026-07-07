# Plan: autonomous cross-instance auto-learn (founder redesign, 2026-06-30)

## What / why
Replace the human-in-the-loop candidate queue with a fully autonomous daily loop: every instance's
learnings get distilled into HOW-only lessons, client-data-scrubbed, published, propagated to the
whole fleet, and summarized to the founder over Slack. Founder does nothing; system does everything.

## Model change (founder-directed, inverts the prior PRD)
- OLD: share only patterns recurring in 2+ unrelated instances; founder hand-authors; de-identify by recurrence.
- NEW: EVERY learning is shareable to ALL instances. De-identify by SCRUBBING client data, not by recurrence.
  Rationale (founder): a real HOW-only learning has no client data; if any slips in, strip it. One instance's
  lesson helps all; requiring two misses most of it.

## Non-negotiable safety (built in, fail-closed)
A distilled lesson publishes ONLY if it passes a DETERMINISTIC client-data check (`lessons_scrub.py`).
Anything that can't be made clean is HELD (not published) and named in the Slack. A cross-client leak is
irreversible for a threat-intel shop, so the gate is hard code: static token denylist + instance-name
roster + path/email patterns. LLM does the abstraction; the deterministic verifier is the backstop.

## Pipeline (daily heartbeat)
1. HARVEST each instance's new learnings (RCAs first; source-hash ledger so each is processed once).
2. DISTILL each into a HOW-only lesson via `claude -p` (drop all WHAT/specifics).
3. SCRUB client data (deterministic strip) -> VERIFY clean (fail-closed). Unclean -> HOLD + report.
4. PUBLISH clean lessons to `q-system/lessons/<id>.md` (the existing lessons-validator is the write gate).
5. PROPAGATE: `kipi update` fans lessons to all instances (local; no 18-remote push).
6. NOTIFY: `slack-notify.sh` — "Published N lessons across the fleet: [titles]" (+ any HELD).

## Files
- `q-system/.q-system/scripts/lessons_scrub.py` (new — the safety gate, importable)
- `q-system/.q-system/scripts/test/test-lessons-scrub.sh` (new — fail-closed tests)
- `q-system/.q-system/scripts/lessons-distill.py` (new — harvest+distill+scrub+publish+ledger)
- `q-system/.q-system/scripts/lessons-daily.sh` (new — heartbeat: distill -> propagate -> slack)
- `~/Library/LaunchAgents/com.kipi.lessons-daily.plist` (new — daily) + committed installer
- retire `lessons-harvest.py` candidate-queue path (keep or replace; founder wants no queue)

## Acceptance (reproducer-first on the safety gate)
- [ ] `lessons_scrub.py`: text with a client token (KTLYST / instance name / /Users/ path / email) -> is_clean=False (HELD).
      Clean HOW-only text -> is_clean=True. Scrub replaces tokens. test-lessons-scrub.sh green.
- [ ] distiller publishes only clean lessons; held ones are reported, never written.
- [ ] source-hash ledger: a second run publishes nothing new (idempotent).
- [ ] daily heartbeat Slacks a summary only when something changed.

## Patterns
- Reuse lessons-validator denylist tokens; extend with registry instance names.
- `claude -p` distill with graceful fallback (skip, don't crash) — open-loops-heartbeat pattern.
- launchd daily + committed installer + watchdog coverage (this session's automation/ + launchd-health).
