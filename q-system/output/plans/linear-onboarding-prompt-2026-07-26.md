# Continuation prompt — put kipi-system into Linear

Paste everything below the line into a fresh session, AFTER completing the
Linear OAuth in `/mcp`.

---

You are a senior staff engineer continuing work on the Kipi fleet.

Work only in: /Users/assafkipnis/projects/kipi-system
Read AGENTS.md and CLAUDE.md first and follow all repository instructions.
Do not use destructive git operations. Do not edit outside the repository.

## PRECONDITION — check this first, and stop if it fails

Linear is configured as a remote HTTP MCP (`mcpServers.linear` ->
`https://mcp.linear.app/mcp`) and the plugin is cached, but as of 2026-07-26 it
had never authenticated (`pluginUsage.linear@claude-plugins-official.usageCount`
was 0 and no Linear tools were exposed).

Confirm you actually have Linear tools before planning anything. If
`ToolSearch` for Linear returns nothing, STOP and say so — the fix is the
founder completing OAuth in `/mcp`, and nobody else can do it.

## GOAL

Get kipi-system represented in Linear alongside the other projects, and get the
real open work onto the board. Do NOT guess which shape the founder wants.

**First action: look, then ask one question.** List the existing Linear teams
and projects and show them. Then ask which of these it is:

1. a NEW Linear project for kipi-system, or
2. issues filed into an EXISTING project (say which)

The founder's standing preference is to be shown what exists and choose, not to
be handed a picker built from a guess.

## STATE — do not re-derive, do not re-verify

The 2026-07-26 session finished a large piece of work. All of this is already
true; spend no tokens confirming it.

- `kipi-update.sh` consolidation shipped through 5 gated prd-os issues and is
  deployed. **Fleet is 23/23 updated, 0 failed.** HEAD `357fc32`, 0 unpushed,
  marketplace clone in sync.
- All 8 updater shell suites green. `pytest` (the usual invocation) is
  368 passed / 0 failed / 1 skipped.
- 17 ledger items were opened that session; 15 resolved, plus 3 pre-existing
  ones closed (`sp-5f2d2a63`, `sp-e244e821`, `sp-4d73b735`).
- Full session record: `q-system/memory/last-handoff.md`. Read it before
  writing any issue text — the wording there is accurate and already reviewed.

## THE PAYLOAD — what belongs on the board

Three tiers. Confirm the shape with the founder before creating anything, then
create only what they picked.

### Tier 1 — open, small, fix already identified (2 items)

- **`sp-d29346e9` — pytest blind spot.** `q-system/.q-system/` is a HIDDEN
  directory and pytest does not recurse into dot-directories, so every
  directory-based invocation collects ZERO of the 34 test files under it.
  `pytest q-system/.q-system` also collects nothing; only explicit paths work.
  The quoted "368 passed / 0 failed" baseline therefore excludes 167 separation
  tests. Fix is one line of pytest config (`testpaths` / `norecursedirs`) plus
  a decision about the 4 failures it exposes.
  Repro: `python3 -m pytest -q q-system/.q-system/tests/separation/`

- **`sp-2ae4df51` — version check misses untracked files.**
  `q-system/.q-system/scripts/plugin-version-bump-check.py` only sees TRACKED
  changes, so a brand-new UNTRACKED file under `plugins/<name>/` without a
  version bump passes both call sites (lefthook `--staged`, and
  `validate-separation.py` Gate 1.7 `--against origin/main`). Fix belongs in
  that one script — add `git ls-files --others --exclude-standard` to
  `changed_files` — NOT in a second checker.

### Tier 2 — 4 real test failures, pre-existing, currently invisible

Verified NOT caused by the 2026-07-26 work: the same 4 fail at `7df21c7`, the
pre-work baseline, and the failure sets were diffed directly with zero new.

```
q-system/.q-system/tests/separation/test_containment_claims.py::test_no_unproven_propagation_claim
q-system/.q-system/tests/separation/test_containment_claims.py::test_current_updater_excludes_canonical_in_real_and_dry_paths
q-system/.q-system/tests/separation/test_containment_scoped_checks.py::test_every_completed_containment_check_is_independently_green
q-system/.q-system/tests/separation/test_containment_sequence.py::test_repository_sequence_allows_only_the_next_safe_step
```

Note these are ORDER-SENSITIVE — they read `.prd-os/` state, and the count
moved between runs during the session. Confirm the current set before filing.

### Tier 3 — 73 older items keeping `gates run` RED

`python3 plugins/prd-os/scripts/prd_runner.py gates run` lists them. These
predate the consolidation work and were explicitly out of its scope. Do NOT
bulk-import 73 issues without the founder saying so — ask whether they want
them on the board at all, a triaged subset, or left in the ledger.

## SCOPE FENCE

**Do NOT:**
- Run `kipi update` in any form. The fleet is current; this task never touches
  an instance.
- Fix any of the items you are filing. This task puts work on a board; it does
  not do the work. If you find yourself editing `kipi-update.sh`, you have left
  the task.
- Bulk-create 73 issues on your own judgement.
- Resolve any spillover item as a side effect of filing it. A Linear issue is
  not a fix; the ledger entry stays open until the code changes.

**When you find something real that is out of scope** — and you will — capture
it, do not fix it:

```bash
python3 plugins/prd-os/scripts/prd_runner.py spillover add \
  --source linear-onboarding --desc "<what it is, concretely>"
```

## DISCIPLINE

- Every issue body carries a RUNNABLE reproducer command, not a description of
  one. An issue nobody can reproduce is a note.
- Link each issue back to its ledger id (`sp-…`) so the two systems can be
  reconciled later. Two trackers with no join key is the same duplication
  defect this fleet keeps paying for.
- Do not invent priorities or estimates the founder did not give you.

## DONE — checkable, not a judgement call

- [ ] Linear tools confirmed present (or STOPPED with the OAuth blocker named)
- [ ] Existing Linear teams/projects listed and shown to the founder
- [ ] Founder picked shape #1 or #2 before anything was created
- [ ] Only the picked scope created; Tier 3 not bulk-imported without consent
- [ ] Every created issue carries a runnable repro and its `sp-…` id
- [ ] No spillover item resolved by this task
- [ ] `git status` clean; no instance touched

## STOP CONDITIONS

Stop and surface — naming exactly what is blocked and what unblocks it — on:
missing Linear auth, a destructive operation, or any ask that would mean
editing code rather than filing work.
