---
id: prd-cross-instance-learning-2026-06-19
title: Cross Instance Learning
status: archived
created_at: 2026-06-19T22:46:17Z
updated_at: 2026-06-20T00:49:40Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-cross-instance-learning-2026-06-19-findings.jsonl
codex_reviewed_at: 2026-06-19T23:42:56Z
---

# Cross Instance Learning

<!-- PROVENANCE: drafted from Addendum A of q-system/output/plans/claudesidian-canonical-brief-2026-06-19.md.
Two review rounds (standard Codex + agent-team adversarial + agent-team re-review). v1 was
rejected (consumer wouldn't propagate, rsync --delete would kill the index, kipi push would
leak upward, source_instances frontmatter was itself a leak). The v2 redesign (skeleton-sole-
writer, read-only consumers) was re-reviewed and its push-side-exclude was found UNGROUNDED
(git subtree push has no subpath exclude). This v3 replaces it with an implementable pre-push
GUARD and tightens the validator to an allowlist. Finding-to-fix map in the Changelog. -->

## Problem

kipi learns inside each instance and never across the ~18. A lesson learned in one instance (an RCA root-cause type, a reusable pattern, a process fix) never reaches the others. Siloed per instance: per-project auto-memory (`~/.claude/projects/<instance>/memory/MEMORY.md`), debrief output (`/q-debrief`), RCAs (`q-system/output/rca/`), scars and corrections.

The rails that cross instances do not carry learning: `kipi update` carries structure top-down; `kipi push` carries generic code bottom-up; the KTLYST bridge carries current STATE across 5 same-company instances. The per-instance producers (rca, learn-from-correction) exist; they have no consumer.

Measurable today: 0 lessons flow between instances; `q-system/memory/weekly/` and `monthly/` rollup dirs are still `.gitkeep` stubs.

The constraint Noah's single-vault claudesidian never faces: ~4 instances are client-confidential (consulting, lawyer). Any cross-instance sharing that leaks client A's data into client B is a non-starter, AND the leak can hide in metadata or a title, not just the lesson body.

## Goals

- A skeleton-authored `q-system/lessons/` corpus that fans READ-ONLY to every instance via the existing `kipi update` rail (no 19th repo).
- A consumer that propagates: a SessionStart hook registered in `settings-template.json` (so the `kipi-update.sh` hook-union carries it to every instance), injecting lesson TITLES via `hookSpecificOutput.additionalContext` (no persisted index file).
- Confidentiality safe by ARCHITECTURE + DISCIPLINE, with deterministic structural backstops. Explicitly NOT "safe by construction via the validator" (the validator cannot read content semantics).
- Give the per-instance producers (rca, learn-from-correction) their first cross-instance consumer.

## Non-goals

- v1: auto-promotion. Lessons are hand-authored by the founder, in the skeleton only.
- v1: a semantic content scanner + a client/target/codename roster (v2).
- v1: lesson decay/aging (v2).
- v1: a skeleton-only promotion-provenance ledger (v2; see accepted residual risk).
- v1: an Obsidian meta-vault rendering layer (v3).
- Sharing `kind=scar` or `kind=rca` content verbatim. Forbidden by design.
- Per-instance authored lessons. Instances are READ-ONLY consumers; only the skeleton writes lessons.

## Confidentiality model (the make-or-break, layered)

Primary controls (architecture + discipline), priority order:

1. **Skeleton is the SOLE writer.** Lessons are authored only in the kipi-system skeleton, by the founder, after observing a pattern recur across 2+ unrelated instances ("unrelated" = no shared client/confidentiality boundary, not in the same KTLYST cluster). No instance authors a lesson.
2. **Instances are READ-ONLY consumers.** `lessons/` flows skeleton -> instances (down) only. Never up.
3. **Human-authored abstraction.** The lesson body is a net-new HOW-only restatement (pattern/methodology), never an auto-scrub of a client-specific scar.
4. **No identifying metadata in the fanned file.** Frontmatter is EXACTLY `{id, kind, title, date}`. No `source_instances` (naming two client instances is itself a disclosure), no client/codename/matter field, no counts that narrow identity.

Deterministic structural backstops (enforce SHAPE, cannot read semantics):

5. **Validator = ALLOWLIST.** Self-scoped to `q-system/lessons/`, registered as a PostToolUse(Edit|Write) hook in the SKELETON's `.claude/settings.json` (it guards founder writes, where lessons are authored; instances are read-only so it is moot there). Exit 2 (BLOCK) when: `kind not in {pattern, methodology}`; any required field missing; ANY frontmatter key outside `{id, kind, title, date}` is present (allowlist, not denylist); or the `title` string matches the client-token denylist (reuse `kipi-push-upstream.sh` line-26 tokens: `KTLYST|ktlyst|CISO|re-breach|Assaf|/Users/`) as a structural check on the one content field that fans eagerly. Stated limit: it cannot verify a body is truly HOW-only; that rests on controls 1-3.
6. **Pre-push GUARD (replaces the impossible subtree exclude).** `git subtree push` has NO subpath exclude (verified, git 2.54.0), so `kipi-push-upstream.sh` instead HARD-FAILS before the push if the instance's `q-system/lessons/` differs from the skeleton's (any local add/edit/delete under `lessons/`), with a message "lessons are skeleton-authored only." Plus a registry-type guard: a client/confidential instance must not be `type=direct-clone` (a deterministic check; direct-clones bypass the subtree push and can write the skeleton remote directly).

## Proposed approach

```
AUTHOR (skeleton only)                     CONSUMER (every instance, read-only)
  founder writes q-system/lessons/<id>.md    SessionStart hook (settings-template.json)
  HOW-only, kind=pattern|methodology         reads q-system/lessons/*.md frontmatter titles
  validator (PostToolUse, skeleton) guards   emits hookSpecificOutput.additionalContext
        |                                     (<=N titles; no persisted file; never blocks)
  kipi update (rsync, lessons/ NOT excluded) --- fans READ-ONLY --->  subtree instances
  kipi push: pre-push GUARD hard-fails if lessons/ locally changed  <--- nothing flows up
```

- `q-system/lessons/`, one markdown file per lesson, frontmatter EXACTLY `{id, kind, title, date}`, HOW-only body. NOT in `kipi-update.sh`'s rsync `--delete` exclude list, so accepted lessons fan to subtree instances on the daily rail.
- **Consumer = a SessionStart hook in `settings-template.json`** (NOT skeleton `.claude/settings.json`, which does not propagate; the `kipi-update.sh` hook-union carries template hooks to every instance). The ~30-line script:
  - resolves the project root by reusing `q-system/hooks/session-start.py`'s `get_qroot` (lines 29-34) so it handles BOTH the flat and the nested `q-system/q-system/` subtree layout (do NOT hardcode a single-level path);
  - reads only the frontmatter `title` of each `q-system/lessons/*.md`, capped at **N=20** most recent;
  - emits `{"hookSpecificOutput": {"additionalContext": <titles>}}` (the shape used by `q-system/.q-system/scripts/voice-dna-loader.py:152` and `token-guard.py:336`; NOTE session-start.py itself uses a bare `print` and is cited ONLY for its never-blocks/exit-0 contract and `CLAUDE_PROJECT_DIR` handling);
  - is fail-closed and never-blocks: missing/unreadable `lessons/` -> inject nothing, exit 0; never blocks session start.
  - NO persisted `INDEX.md` (avoids the `rsync --delete` destruction of a gitignored file).
- **Single-writer:** `q-system/lessons/` is written ONLY in the skeleton; `kipi update` fans it down (the rsync is the only per-instance writer); the pre-push guard prevents an upward writer.
- **Direct-clone class:** deterministic registry-type guard (client/confidential instances must be subtree-type); car-research (the only current direct-clone) is the founder's own non-client instance.

## Acceptance criteria (become issue required_checks)

- **Propagation:** `kipi update --dry` (or `rsync -ain --delete`) shows `q-system/lessons/` as an ADD into a subtree instance and confirms it is NOT caught by an exclude.
- **Consumer propagates + injects:** the SessionStart hook is present in `settings-template.json`; on a test instance it emits `<=20` lesson titles via `hookSpecificOutput.additionalContext`, 0 bodies; with `lessons/` absent it emits nothing and exits 0; it resolves the path via `get_qroot` (passes on the nested layout); no persisted file appears in the synced tree.
- **Validator allowlist (with negative tests):** `kind=scar` -> exit 2; a frontmatter key outside `{id,kind,title,date}` -> exit 2; a `title` containing a client-token -> exit 2; a missing required field -> exit 2; a valid `kind=pattern` lesson -> exit 0.
- **Pre-push guard (negative test):** a planted edit to `q-system/lessons/` inside a subtree instance makes `kipi push` REFUSE (non-zero exit, skeleton-authored message); an unchanged `lessons/` pushes normally.
- **Direct-clone guard:** a check fails if any client/confidential registry entry is `type=direct-clone`.
- **Docs discoverable:** the promotion rule + "unrelated" definition + read-only-consumer invariant live in `q-system/lessons/README.md`.

## Risks and rollback

- Risk: client-specific content reaches `lessons/`. PRIMARY control is PREVENTIVE; reactive rollback cannot retract already-fanned copies, session context, or logs. Prevention: skeleton-sole-writer + human abstraction + allowlist frontmatter + title token-check + `kind` restriction + pre-push guard. Rollback is BACKSTOP only: `git revert` + next `kipi update` fans the deletion.
- Accepted residual risk (v1): removing `source_instances` leaves v1 with NO provenance record, so the "2 unrelated instances" rule is author self-attestation until the v2 skeleton-only ledger. Accepted because the alternative (keeping the field) is itself a disclosure.
- Accepted residual risk (v1): the validator checks the `title` only against a token denylist, not semantics; a title with a novel client codename outside the token list fans before v2's roster exists.
- Risk: consumer hook fails to propagate -> mitigated by `settings-template.json` registration + the consumer acceptance check.
- Blast radius: one committed folder + one `settings-template.json` SessionStart entry + one hook script + one validator PostToolUse entry in the skeleton's `.claude/settings.json` + one `kipi-push-upstream.sh` guard + one registry-type check. Back out = remove them; instances drop `lessons/` on the next update.

## Open questions

Resolved 2026-06-19 (owner-delegated, autonomous run). See Confidentiality model + Acceptance criteria. Remaining (non-blocking, v2): semantic content scanner + client/target/codename roster; lesson decay; skeleton-only promotion ledger; Obsidian meta-vault rendering.

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. `prd_split.py` reads this block verbatim and writes
one issue spec per entry.

Required keys per entry:
  - id (kebab-case, unique across the repo)
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The runner's
    stop-gate checks that three receipts are marked (verified, reviewed,
    findings_triaged). Those receipts are meaningless unless the spec
    documents what must be verified, so an empty list is rejected.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

IDs must match the repo's issue naming convention and must not collide with
existing issue specs.
-->

```json
[
  {
    "id": "lessons-scaffold",
    "title": "Scaffold q-system/lessons/ corpus + README (promotion rule, unrelated definition, read-only-consumer invariant) + one seed kind=pattern lesson; verify lessons/ propagates via kipi update and is not excluded",
    "finding_id": "finding-4",
    "allowed_files": ["q-system/lessons/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-lessons-propagation.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-lessons-propagation.sh"
  },
  {
    "id": "lessons-validator",
    "title": "Allowlist validator for q-system/lessons/, wired PostToolUse in the skeleton .claude/settings.json: exit 2 on kind not in {pattern,methodology}, missing required field, any frontmatter key outside {id,kind,title,date}, or title matching the client-token denylist; pair per skill-hook-pairing",
    "finding_id": "finding-8",
    "allowed_files": ["q-system/.q-system/scripts/lessons-validator.py", "q-system/.q-system/scripts/test/test-lessons-validator.sh", ".claude/settings.json", ".claude/rules/skill-hook-pairing.md"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-lessons-validator.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-lessons-validator.sh"
  },
  {
    "id": "lessons-consumer-hook",
    "title": "SessionStart consumer hook registered in settings-template.json: emit <=20 lesson titles via hookSpecificOutput.additionalContext, resolve project root via session-start.py get_qroot (flat + nested layout), fail-closed never-blocks, no persisted index file",
    "finding_id": "finding-5",
    "allowed_files": ["q-system/hooks/lessons-index.py", "settings-template.json", "q-system/hooks/test/test-lessons-index.sh"],
    "required_checks": ["bash q-system/hooks/test/test-lessons-index.sh"],
    "bypass_check": "bash q-system/hooks/test/test-lessons-index.sh"
  },
  {
    "id": "lessons-push-guard",
    "title": "Pre-push guard in kipi-push-upstream.sh: hard-fail before the subtree push if q-system/lessons/ was locally modified; plus a deterministic registry-type guard that fails if a client/confidential instance is type=direct-clone",
    "finding_id": "finding-7",
    "allowed_files": ["kipi-push-upstream.sh", "q-system/.q-system/scripts/test/test-lessons-push-guard.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"
  }
]
```

## Changelog

- 2026-06-19 round 1 (10 findings) -> v2 redesign: skeleton-sole-writer + read-only consumers; consumer hook moved to settings-template.json; no persisted index (titles injected); source_instances removed; rollback demoted to backstop; acceptance criteria added.
- 2026-06-19 round 2 re-review -> v3:
  - BLOCKER (push exclude ungrounded): `git subtree push` has no subpath exclude; replaced with a pre-push GUARD that hard-fails if `lessons/` was locally edited, plus a registry-type guard for direct-clones.
  - additionalContext citation corrected (voice-dna-loader.py:152 / token-guard.py:336, not session-start.py).
  - validator flipped denylist -> ALLOWLIST (only {id,kind,title,date} keys) + a title token-check; clarified it is a PostToolUse hook in the skeleton's .claude/settings.json.
  - `recurs_unrelated` dropped (meaningless self-attestation); v1 provenance gap flagged as accepted residual risk.
  - QROOT: reuse session-start.py get_qroot (handles nested layout) instead of hardcoding single-level.
  - additionalContext title injection capped at N=20.
  - title content-validation residual risk stated.
