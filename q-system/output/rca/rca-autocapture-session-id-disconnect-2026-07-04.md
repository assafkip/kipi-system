# RCA: Auto-capture recorded nothing (session_id producer/consumer disconnect)

- **Date:** 2026-07-04
- **Severity:** high (the feature was live-but-inert on the design partner)
- **Detected by:** post-merge wiring audit (founder asked to confirm nothing was disconnected)
- **Status:** fixed (PR #8, merged, propagated to fleet, verified on 4_points)

## What happened

The memory auto-capture "referee" shipped through the full gated flow (PR #7),
merged to main, and propagated to 4_points_consulting with `is_enabled() = True`.
Every gate was green. But it recorded zero outcomes: the SessionStart producer
and the Stop-hook consumer keyed the shared `.session-recall.json` artifact by
DIFFERENT session identifiers, so the consumer's `read_and_clear` always returned
an empty set.

## Surface root cause

`session_recall.resolve_session_id()` read the environment variable
`CLAUDE_SESSION_ID`. Claude Code does not set that name; it exports the session
UUID as `CLAUDE_CODE_SESSION_ID`. So the producer fell through to its
`no-session-<pid>` fallback and keyed recall under that, while the Stop-hook
consumer read `session_id` from its stdin payload (the real UUID). Two keys,
never equal, so nothing was ever consumed.

Cause type: `latent-defect` (a wrong constant, not an environment change).

## Structural root cause

The producer and consumer derive the SAME logical value (the session id) from
TWO different sources (env var vs stdin payload) with no shared contract and no
test that pins them to the same value. A cross-process handshake was encoded as
two independent guesses. The env var name was never verified against the running
harness; it was assumed.

## Why every gate passed anyway

Cause type: `test-blind-spot`. All unit and e2e tests passed an EXPLICIT
`session_id` (to be deterministic), so not one test exercised the env-resolution
path. The e2e test drove `capture()` and even `main()` with injected ids, so it
proved the data loop but never the id-derivation that wires producer to consumer
in a real session. Green tests + green gates gave false confidence.

## Evidence (ran X, got Y)

- `env | grep CLAUDE_` -> `CLAUDE_CODE_SESSION_ID` is set; `CLAUDE_SESSION_ID` is unset.
- Before fix: `resolve_session_id()` returned `no-session-98061`; consumer id was
  `e1081454-...`; `MATCH: False`.
- After fix (`CLAUDE_CODE_SESSION_ID` read first): `MATCH: True`, proven on both
  the skeleton and inside the 4_points install.
- Regression test `test_resolve_reads_claude_code_session_id` fails on the old
  code, passes on the new.

## Fix

1. `resolve_session_id()` reads `CLAUDE_CODE_SESSION_ID` first (old names kept as
   defensive aliases). PR #8.
2. Regression test asserts the env-resolution path directly.
3. `correction_outcome.py` CLI: `session_id` optional, defaults to the same
   resolver, so the corrected path uses the same id source.

## Action items

- [x] Fix the env var name and prove producer==consumer. (owner: agent, PR #8)
- [x] Add the regression test that exercises env resolution. (owner: agent)
- [x] Re-propagate to the fleet and verify on 4_points. (owner: agent)
- [ ] Add a first-real-session smoke on the design partner: after one real
      session, assert `outcomes.jsonl` gained at least one line. A cross-process
      wiring bug like this only shows in a live session, not in unit tests.
      (owner: founder, at design-partner watch)
- [ ] When a producer/consumer pair shares a value derived from the harness,
      derive it in ONE place both import, or assert equality in a test. (owner:
      agent, carry into future hook-pair designs)

## Blameless note

The gated flow worked as designed for what it can see (logic, scope, receipts).
It cannot see a wrong environment constant, because that only manifests in a live
session against the real harness. The lesson is not "review harder"; it is "a
cross-process handshake needs a live smoke or a single shared derivation," which
is now action item 4/5.
