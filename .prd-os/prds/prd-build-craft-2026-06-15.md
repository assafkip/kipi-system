---
id: prd-build-craft-2026-06-15
title: Build Craft
status: idea
created_at: 2026-06-15T01:26:37Z
updated_at: 2026-06-15T01:26:37Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-build-craft-2026-06-15-findings.jsonl
---

# Build Craft

> Retroactive formalization. The bundle is already built and verified in the
> working tree. This PRD exists to put the already-built diff through the gated
> Codex review and receipts it skipped on the fast path. Review should audit the
> real diff, not a forward plan.

## Problem

Opus codes well by default (docstrings, type hints, defensive try/except), but a
forensic read of 697 code edits by the Fable 5 model surfaced four habits Opus
does not do by default, which an independent Codex review graded as genuinely
good: bash-first recon before edit, verify-against-a-copy with a negative
self-test, single-writer chokepoints guarded by a grep-the-tree test, and "why"
comments anchored to a named scar. The same review showed those habits applied
unevenly: 22 accepted Codex findings across 4 Fable PRDs, clustered in planning
completeness, including a test that risked mutating the live founder DB and a PRD
that omitted networkx from the dependency manifest. The graded-good code survived
in git (db.py single-writer upsert + the TTFN scar comment, last refined
2026-06-12), confirming the habits are worth keeping. There was no durable
mechanism to carry these habits into Opus sessions, and no enforcement of the one
deterministic slice (test isolation).

## Goals

- A kipi-core skill `build-craft` that teaches the graded-good habits as an
  additive layer on top of Opus defaults (the Fable delta, not a replacement).
- A paired deterministic hook that enforces test isolation: a test must not name
  a live data path; it uses a temp copy, a tempfile, or :memory:.
- An auto-invoke rule so the skill fires on coding tasks larger than one line.
- The hook catches the real variable-indirection violation shape and produces
  zero false positives across the existing kipi-investigations 217-test suite.
- The pairing is recorded in the skill-hook-pairing registry (the repo's own
  contract that a deterministic skill ships with its hook).

## Non-goals

- Enforcing the no-em-dash-in-narration rule via a hook. Narration is not a tool
  call, so a PostToolUse hook cannot see it. Documented limitation; lives in the
  skill plus the output style.
- Catching a no-argument default `db.connect()`. There is no literal to detect,
  and a generic no-arg detector false-positives on non-DB `.connect()` calls
  (websockets, mocks) across instances. Documented limitation; left to the skill
  (use the monkeypatch-the-default convention).
- Changing Opus's existing good defaults (docs, type hints, try/except).

## Proposed approach

Skill teaches (judgment), hook enforces (the deterministic slice), rule triggers.
This matches the repo's skill-hook-pairing contract exactly.

```
plugins/kipi-core/skills/build-craft/SKILL.md          # the four habits + 5 consistency rules + 3 anti-patterns
plugins/kipi-core/skills/build-craft/references/checklist.md
plugins/kipi-core/skills/build-craft/scripts/build-craft-lint.py        # PostToolUse enforcer
plugins/kipi-core/skills/build-craft/scripts/test_build_craft_lint.py   # self-test (6 cases)
plugins/kipi-core/hooks/hooks.json                     # wire the hook (PostToolUse Edit|Write|MultiEdit)
plugins/kipi-core/.claude-plugin/plugin.json           # bump version, add to description
.claude/rules/build-craft-auto-invoke.md               # trigger
.claude/rules/skill-hook-pairing.md                    # registry entry
```

The hook flags a slashed DB-path literal (.db/.sqlite/.sqlite3/.duckdb with a
path separator) that is not isolated, only in a connect/open/copy call or a
variable assignment. The slash requirement lets `tmp_path / "t.db"` through; the
call/assignment context plus an assert-skip prevents flagging an audit test that
merely names the live path in an assertion.

## Risks and rollback

- Blast radius: every instance. The skill+hook ship via the kipi-core plugin and
  the rule propagates via `.claude/rules`. A too-aggressive hook would block
  legitimate test edits fleet-wide.
- Mitigation: the hook is tightly scoped (Python test files only; slashed-DB
  literal in call/assignment context only; `# build-craft-lint-skip` escape),
  verified zero false positives across 217 real kipi-investigations tests.
- Rollback: remove the one hook line from hooks.json (skill+rule degrade to
  advisory), or delete the skill directory. Both reversible, no data migration.

## Open questions

- Close the no-arg default-connect blind spot later with a file-level heuristic?
  (deferred; FP risk needs cross-instance testing)
- Add a Stop-hook attempt for narration em-dashes? (deferred)

## Issues

```json
[
  {
    "id": "build-craft-bundle",
    "title": "build-craft skill + test-isolation hook + auto-invoke rule",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/skills/build-craft/**",
      "plugins/kipi-core/hooks/hooks.json",
      "plugins/kipi-core/.claude-plugin/plugin.json",
      ".claude/rules/build-craft-auto-invoke.md",
      ".claude/rules/skill-hook-pairing.md"
    ],
    "required_checks": [
      "python3 plugins/kipi-core/skills/build-craft/scripts/test_build_craft_lint.py",
      "python3 -c \"import json; json.load(open('plugins/kipi-core/hooks/hooks.json'))\""
    ],
    "acceptance": "Self-test passes all 6 cases (live literal and variable-indirection blocked exit 2; isolated, skip-marker, assertion-context, non-test all exit 0). hooks.json is valid JSON and wires build-craft-lint. Pairing recorded in skill-hook-pairing.md. Verified zero false positives across the kipi-investigations 217-test suite."
  }
]
```
