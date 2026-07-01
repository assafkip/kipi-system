# q-system/lessons/ — cross-instance lessons corpus

Skeleton-authored, read-only-consumer lessons that fan to every kipi instance via `kipi update`. Part of PRD `prd-cross-instance-learning-2026-06-19`.

## What a lesson is

A HOW-only, reusable pattern or methodology learned in one instance and worth sharing with all. NOT a scar, NOT an RCA, NOT client work.

## Promotion rule (who writes, when)

- **Skeleton is the sole writer.** Lessons are authored ONLY here in kipi-system, by the founder. No instance authors or edits a lesson.
- **Eligibility:** `kind: pattern` or `kind: methodology` ONLY. `kind: scar` and `kind: rca` are forbidden (the specific that makes a scar sting IS the client-confidential WHAT).
- **2+ unrelated instances:** promote a lesson only when the same pattern recurred in 2 or more UNRELATED instances. "Unrelated" = no shared client/confidentiality boundary, and not in the same instance cluster. A pattern common to two unrelated engagements is de-identified by construction.
- **Hand-authored abstraction:** write a net-new HOW-only restatement. Never paste or auto-scrub a client-specific scar.

## Read-only-consumer invariant

Instances RECEIVE lessons (read-only) via `kipi update`. They never author, edit, or push lessons. `kipi update` fans this folder down. Enforced by sibling issues in this PRD: `kipi push` will hard-fail if `lessons/` was modified in an instance, once wired (issue `lessons-push-guard`).

## Adding a lesson

To add a lesson, create `q-system/lessons/<id>.md` with frontmatter `id` / `kind` / `title` / `date` and a HOW-only body. Copy `single-writer-chokepoint.md` as a template. Only the founder authors lessons, here in the skeleton; instances receive them read-only.

## Finding what to write (the harvest engine)

`kipi lessons-harvest` finds candidates FOR you so the corpus fills itself. It sweeps every instance's RCAs, classifies each structural cause into a fixed-taxonomy tag (`lessons-harvest.py`), and queues a candidate in repo-root `lesson-candidates/` whenever the same cause-type recurred across **2+ unrelated clusters** (the cross-cluster recurrence IS the de-identification). Candidates are DRAFTS with skeleton-only provenance; they never auto-publish. You read the candidate, hand-author the HOW-only lesson here, then delete the candidate. This is the capture -> synthesize -> promote loop (claudesidian's model, adapted to kipi's confidentiality: the write-back stays human). Run `kipi lessons-harvest --dry` to preview.

## Frontmatter (exactly these keys)

```yaml
id: <kebab-case>
kind: pattern | methodology
title: <short, HOW-only, no client names>
date: YYYY-MM-DD
```

No other keys. No `source_instances` (naming instances is itself a disclosure). Enforced by sibling issue `lessons-validator`: a PostToolUse validator blocks any file that violates this once wired.
