# lesson-candidates/ — the harvest queue (skeleton-only, NOT fanned)

Auto-generated drafts from `kipi lessons-harvest`. This is the ENGINE half of the cross-instance
lessons corpus: `lessons-harvest.py` sweeps every instance's RCAs, classifies each structural cause
into a fixed-taxonomy tag (LLM proposes, the script verifies against the allowlist), and drops a
candidate here whenever the SAME cause-type recurred across **2+ unrelated clusters**.

## Why this dir is here and not in q-system/lessons/

- It lives at the repo ROOT (outside `q-system/`), so `kipi update` NEVER fans it to instances.
  Candidates carry source-instance provenance (which RCAs, which instances) — safe to keep here
  skeleton-only, unsafe to ever ship. This is the promotion-provenance ledger the PRD deferred to v2.
- It is git-tracked (recoverable), unlike gitignored `output/`.

## What you do with a candidate

A candidate is a DRAFT, not a lesson. It never becomes a lesson automatically — the confidentiality
model requires a human-authored abstraction (never an auto-scrub of a client scar):

1. `kipi lessons-harvest` (or `--dry` to preview). Candidates land here, one file per cause-type.
2. Read the candidate + its source RCAs.
3. Hand-write a NET-NEW, HOW-only lesson at `q-system/lessons/<id>.md` (frontmatter EXACTLY
   `{id, kind: pattern|methodology, title, date}`). The lessons-validator gates the write.
4. Delete the candidate. It has done its job (it found the pattern; you abstracted it).

The rail (`q-system/lessons/`) fans the finished lesson read-only to all instances on the next update.
