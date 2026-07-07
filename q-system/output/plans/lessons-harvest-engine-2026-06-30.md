# Plan: lessons-harvest engine (the claudesidian loop, kipi-confidential edition)

## What / why (1-2 lines)
The cross-instance lessons corpus has the sharing RAIL but no engine, so it holds 1 lesson.
claudesidian fills its brain via capture -> synthesize -> write-back. Port that loop, but the
write-back is HUMAN promotion (kipi's confidentiality model forbids auto-publishing a client scar).

## The forced design decision (not a real fork — the existing controls dictate it)
Auto-publishing distilled lessons into `q-system/lessons/` is FORBIDDEN by the PRD's primary
confidentiality controls: skeleton-sole-writer + human-authored abstraction (the validator only
checks SHAPE, not semantics; auto-scrubbing a client scar is explicitly banned). So the engine
HARVESTS + CLUSTERS + QUEUES candidates for the founder to promote by hand. It automates the
tedious 90% (find patterns recurring across UNRELATED instances, draft a candidate) and solves
the PRD's flagged v1 provenance gap (it KNOWS the source instances; provenance lives skeleton-only).

## Approach (the pick)
1. HARVEST (deterministic): sweep every registered instance's `q-system/output/rca/*.md`; extract
   (instance, file, title, Structural-root-cause text). No client content leaves this stage.
2. CLASSIFY (LLM via `claude -p`, bounded): tag each RCA's structural cause with a cause-type from
   a FIXED taxonomy; script validates the tag is in the allowlist (LLM proposes, script verifies —
   the sycophancy-harness pattern). Fallback: "unclassified" if claude absent. Test mode injects tags.
3. CLUSTER (deterministic): group by cause-type; emit a candidate only when 2+ UNRELATED instances
   share a type. "Unrelated" derived from name/path (ktlyst-* = one cluster; unsure => RELATED, the
   safe default so we never over-claim unrelated).
4. QUEUE (write): candidate -> repo-root `lesson-candidates/<cause-type>.md` (skeleton-only, git-
   tracked, NOT fanned — outside q-system/ so kipi update never carries it; provenance safe here).
   Body = the pattern + skeleton-only source pointers + a HOW-only DRAFT stub + promotion steps.
5. PROMOTE (human, unchanged): founder hand-authors the real `q-system/lessons/<id>.md`; existing
   lessons-validator gates the write. Sole-writer + human-abstraction controls stay intact.

## Files to touch
- `q-system/.q-system/scripts/lessons-harvest.py` (new — the engine)
- `q-system/.q-system/scripts/test/test-lessons-harvest.sh` (new — reproducer)
- `lesson-candidates/` (new repo-root dir, git-tracked, NOT fanned)
- `kipi` (add `kipi lessons-harvest` subcommand — the discoverable trigger)
- `q-system/lessons/README.md` (document the harvest->candidate->promote flow)

## Acceptance criteria (reproducer defines done)
- [ ] Fixture: 3 fake instances. Two UNRELATED share cause-type A; a ktlyst-pair share type B;
      one instance has a singleton type C. Harvest (test mode, injected tags) yields a candidate for
      A ONLY. B (related pair) and C (singleton) produce NO candidate. `test-lessons-harvest.sh` green.
- [ ] Candidate lands in `lesson-candidates/`, NOT in `q-system/lessons/` (validator untouched).
- [ ] `lesson-candidates/` is NOT in the kipi update fan-out (grep the rsync source/excludes; it's
      outside q-system/ so it is structurally excluded — assert no fan).
- [ ] `--dry` prints candidates, writes nothing.
- [ ] `kipi lessons-harvest` runs the engine.

## Patterns to follow (from this repo)
- LLM-proposes / script-verifies against a fixed set: `sycophancy-harness.py`.
- `claude -p` as batch LLM client with graceful no-claude fallback: `open-loops-heartbeat.sh` (lines 30-33).
- Skeleton-side script reads all instances via `instance-registry.json`: `kipi-update.sh`, `open-loops-heartbeat.sh`.
- Repo-root dir to stay outside the fan-out + git-tracked: the `automation/` relocation (this session).

## Follow-on (not this pass — noted so it's not a silent drop)
- Schedule it (weekly launchd) once candidates prove useful. - Harvest memories/debriefs too, not just RCAs.
- A `kipi lessons-promote <candidate>` helper that drafts the HOW-only body interactively.
