# q-system/lessons/ — cross-instance lessons corpus

Skeleton-authored, read-only-consumer lessons that fan to every kipi instance via `kipi update`.

## What a lesson is

A HOW-only, reusable pattern or methodology learned in one instance and worth sharing with all. NEVER the WHAT (no client name, matter, product, file path, or codename). `kind: pattern` or `kind: methodology` only.

## How lessons get here (the running model, 2026-06-30)

Fully autonomous. **No human queue and no recurrence requirement** — every learning is shareable, and de-identification is by SCRUBBING client data, not by waiting for a pattern to recur across unrelated instances.

The daily heartbeat (`lessons-daily.sh`, launchd-fired; run once by hand with `kipi lessons-run`):

1. **DISTILL** — `lessons-distill.py` sweeps TWO intakes across every registered instance:
   - documented failures: `q-system/output/rca/*.md` (RCAs), and
   - non-failure learnings: `q-system/output/learnings/*.md` — a lesson from a build, a near-miss, or a self-caught error that never became an RCA (drop one with `lesson-note.sh`, below).

   Each new source is turned into a HOW-only lesson via `claude -p`.
2. **GATE (fail-closed)** — `lessons_scrub.py` finds client-data signals and scrubs them; a lesson PUBLISHES only if the scrubbed text is deterministically clean AND an LLM semantic pass confirms no residual real entity. Anything the gate can't clear is HELD in `lesson-candidates/` for founder review, never published.
3. **PUBLISH** — clean lessons are written to `q-system/lessons/<id>.md` and committed to the skeleton.
4. **PROPAGATE** — `kipi-update.sh` fans the corpus read-only to every instance; `lessons-index.py` surfaces titles at SessionStart fleet-wide.
5. **LEDGER** — every source is recorded (`lesson-candidates/.processed.json`) so daily runs are idempotent.

### Adding a learning by hand

To add a lesson, pick the path that matches where you are standing:

- **From inside an instance** (a build-lesson or a self-caught error) — drop a note; the daily sweep distills, scrubs, and fans it:
  ```
  bash q-system/.q-system/scripts/lesson-note.sh "short title" "the HOW, in your words"
  ```
  Writes to this instance's `q-system/output/learnings/` (instance-protected; survives `kipi update`).
- **Directly in the skeleton** (founder, fully-formed lesson) — create `q-system/lessons/<id>.md`. Copy `single-writer-chokepoint.md` as a template.

## Read-only-consumer invariant

Instances RECEIVE lessons (read-only) via `kipi update` and DROP raw learnings into their own `output/learnings/`, but never author or edit a published lesson. `kipi update` fans `lessons/` down; the skeleton is the sole publisher.

## Frontmatter (exactly these keys)

```yaml
id: <kebab-case>
kind: pattern | methodology
title: <short, HOW-only, no client names>
date: YYYY-MM-DD
```

No other keys. No `source_instances` (naming instances is itself a disclosure). Enforced by `lessons-validator.py`: it blocks any lesson file that violates this.
