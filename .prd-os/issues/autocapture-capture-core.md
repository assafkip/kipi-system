---
id: autocapture-capture-core
title: memory_autocapture.py Stop-hook: deterministic useful/dead_end via record_outcome, transcript-or-mtime read
status: closed
priority: p0
parent_prd: prd-memory-autocapture-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory_autocapture.py
  - q-system/.q-system/scripts/test_memory_autocapture.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-autocapture-2026-07-04 finding=finding-4 at=2026-07-04T21:08:45Z -->

# memory_autocapture.py Stop-hook: deterministic useful/dead_end via record_outcome, transcript-or-mtime read

## Context

Parent PRD: `.prd-os/prds/prd-memory-autocapture-2026-07-04.md`

## Acceptance

Reads .session-recall.json + the session tool-transcript; emits useful (source_file read this session) and dead_end (surfaced, source never touched) ONLY through memory_outcomes.record_outcome, never writing outcomes.jsonl directly. Transcript path is confirmed at build; if unavailable the useful proxy falls back to source_file mtime-changed-within-session-window (this fallback and its threshold are owned here, covering rejected finding-7). Idempotent: re-running on the same session writes ZERO new lines (content-hash event_id dedup). Silent-safe: no sidecar and no transcript means exit 0, zero writes. Self-gates OFF unless the current instance is allowlisted (default off), so it is inert on the skeleton and every non-partner instance.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] memory_autocapture.py Stop-hook: deterministic useful/dead_end via record_outcome, transcript-or-mtime read

## Amendments

### 2026-07-04T21:27:29Z
Reason: Fix date-in-event_id idempotency bug found by adversarial review of the sibling corrected-path issue: a session replayed across UTC midnight would double-write because event_id hashed the day. Make the dedup key session-based (date-free), matching correction_outcome.py.

Before:
- allowed_files: ['q-system/.q-system/scripts/memory_autocapture.py', 'q-system/.q-system/scripts/test_memory_autocapture.py']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/scripts/memory_autocapture.py', 'q-system/.q-system/scripts/test_memory_autocapture.py']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q']
- disallowed_files: []

### 2026-07-04T21:33:47Z
Reason: Security/gate fix from instance-guard adversarial review: _current_instance trusted the KIPI_INSTANCE env var before the repo path, letting a non-allowlisted instance spoof identity to 4_points_consulting and enable capture. Derive identity ONLY from the durable repo directory name; keep the instance_id param for tests.

Before:
- allowed_files: ['q-system/.q-system/scripts/memory_autocapture.py', 'q-system/.q-system/scripts/test_memory_autocapture.py']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/scripts/memory_autocapture.py', 'q-system/.q-system/scripts/test_memory_autocapture.py']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_memory_autocapture.py -q']
- disallowed_files: []
