---
id: ask-984-guard-reader-stages
title: path-write-guard stops blocking read-only commands and .claude-plugin paths (sp-54b02aa0, sp-1d4ca360)
status: open
priority: p1
allowed_files:
  - q-system/.q-system/scripts/claude-path-write-guard.py
  - q-system/.q-system/tests/test_claude_path_write_guard.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/tests/test_claude_path_write_guard.py
required_reviews: []
deliverables_count: 2
---
<!-- generated-by: prd_split.py prd=prd-manual finding=sp-54b02aa0 at=2026-08-23T08:35:00Z -->

# Guard stops blocking read-only commands and .claude-plugin paths

## Context

Two ledger items, one defect class: the guard's fail-closed posture is right,
but three of its readers over-match and block work that writes nothing.

1. `find` had no reader form, so ANY find touching a `.claude` path blocked,
   including plain enumerations (sp-54b02aa0 case 1).
2. The layer2_blind containment test treated every stage as a writer, so a
   bare `q-system` token (find's search root) flipped layer2_blind on for the
   whole command and find's glob operand then hit the unreadable-literal
   refusal (sp-54b02aa0 case 3). Round 11's pinned shapes are all writers
   (rm, mv, `: >`, echo >, python -c os.remove) and stay blocked.
3. Raw-text rules matched substring `.claude`, refusing sed/awk pipelines that
   mention `.claude-plugin/` -- which the plugin-version-bump gate REQUIRES
   editing (sp-1d4ca360).

Ledger case 2 (bracket-test closing bracket read as a path argument) did NOT
reproduce at HEAD across plausible reconstructions; recorded honestly here. If
it resurfaces it goes back to the ledger with the verbatim command.

## Evidence

RED before any edit (guard stdin contract, rc=2 + reason):

```
BLOCKED | find .claude/skills -name SKILL.md -maxdepth 2
         'find' would write inside .claude/: .../.claude/skills
BLOCKED | find q-system plugins -name validate-separation.py -not -path '*__pycache__*'
         takes an argument this parser cannot read as a literal path
         (*__pycache__*), while the same command re-baselines Layer 2
BLOCKED | sed -i '' 's/1.7.18/1.7.19/' plugins/kipi-core/.claude-plugin/plugin.json
         'sed' runs a program text this parser cannot read, mentions .claude/
```

GREEN after: all three rc=0; controls stay rc=2 (touch .claude/_probe.txt;
find -delete under .claude; sed -i on .claude/settings.json; awk redirect into
.claude/). probe_round9/11 fully green; rounds 12-15 report ONLY their own
injected negative self-test as failed.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Reader-stage semantics for find-without-write-primaries in both layers, component-boundary matcher for raw-text `.claude`
- [x] Permanent pytest harness pinning the four shapes, four controls, and the round-9 phase-1 shape
