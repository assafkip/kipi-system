# PRD: Safe Rollout of Diet + Ripple Graph to All Instances

**Date:** 2026-04-12
**Author:** Assaf Kipnis
**Status:** Draft
**Priority:** P0 (blocking - instances drift further every day without these changes)

---

## 1. Problem

Two PRDs are implemented in the skeleton (kipi-system) but not deployed to any of the 10 active instances. Every session on an instance runs with the old 633-line always-on payload and no ripple verification. The longer we wait, the more canonical drift accumulates.

- **Evidence:** `kipi update` has not been run. No instance has the new scripts, slimmed CLAUDE.md, or ripple graph.
- **Impact:** Instances burn ~10K tokens/session on instructions Claude ignores. Canonical files in KTLYST_strategy drift without detection.
- **Root cause:** The changes are committed to skeleton only. `kipi update` has not been run.

## 2. Scope

### In Scope
- Commit skeleton changes
- Dry-run to preview what propagates
- Deploy to all instances (kipi update processes all at once, no single-instance flag)
- Post-deploy validation: canary checks on car-research, then KTLYST_strategy, then spot checks on 2 custom q-dir instances

### Out of Scope
- Modifying any instance-specific content (canonical files, my-project, memory)
- Changing Notion IDs, MCP configs, or API keys in any instance
- Adding a `--instance` flag to kipi update (separate enhancement)

## 3. How kipi update actually works

`kipi-update.sh` processes ALL registered instances in one pass. There is no `--instance` flag. The only option is `--dry-run`.

**For direct-clone instances** (car-research): runs `git pull --rebase origin main`.
**For subtree instances** (all others): runs `git archive` from skeleton, then `rsync` into the instance with these exclusions:
- `my-project/` (preserved)
- `canonical/` (preserved)
- `memory/` (preserved)
- `output/` (preserved)
- `.q-system/agent-pipeline/bus/` (preserved)

Then syncs `.claude/` config (agents, rules, output-styles, plugins) via direct copy. Merges `settings.json` preserving instance MCP servers, plugins, permissions, and tool configs.

**Notion safety:** `.mcp.json` is NOT touched by kipi update. `settings.json` MCP servers are preserved via the merge logic (lines 149-185 of kipi-update.sh). Notion IDs in `my-project/notion-ids.md` are in the excluded `my-project/` directory.

## 4. Instance inventory

| # | Instance | Type | Custom q-dir | Notion | Post-deploy check |
|---|----------|------|-------------|--------|-------------------|
| 1 | car-research | direct-clone | none | No | **Canary 1** (deterministic) |
| 2 | KTLYST_strategy | subtree | q-ktlyst | Yes | **Canary 2** (deterministic + behavioral) |
| 3 | ktlyst (product) | subtree | none | Yes | None |
| 4 | ktlyst-website | subtree | none | No | None |
| 5 | ktlyst_lawyer | subtree | none | No | None |
| 6 | q-education | subtree | none | No | None |
| 7 | ASK_AI_consultant | subtree | q-consult | Yes | **Spot check** (custom q-dir intact) |
| 8 | 4_points_consulting | subtree | q-investigate | Yes | **Spot check** (custom q-dir intact) |
| 9 | Pure_spectrum_Q | subtree | q-pure | Yes | None |
| 10 | q-investigate-osint-bot | standalone | N/A | No | Skipped (no skeleton) |

## 5. Rollout steps

### Step 1: Commit skeleton

Run from `/Users/assafkip/Desktop/kipi-system`:

```bash
git add CLAUDE.md q-system/CLAUDE.md .claude/rules/ q-system/.q-system/scripts/ \
  q-system/.q-system/ripple-graph.json q-system/.q-system/commands.md \
  q-system/canonical/changelog.md q-system/sources/.gitkeep \
  q-system/methodology/debrief-template.md .gitignore \
  q-system/output/prd-claude-md-diet-2026-04-12.md \
  q-system/output/prd-ripple-graph-2026-04-12.md \
  q-system/output/prd-safe-rollout-2026-04-12.md
git commit -m "feat: CLAUDE.md diet (633->171 lines) + ripple graph + safe rollout PRD"
```

**Gate:** Pre-commit hook runs `instruction-budget-audit.py`. Must exit 0.

### Step 2: Push to remote

```bash
git push origin main
```

This is required BEFORE `kipi update` because car-research (direct-clone) pulls from the remote.

### Step 3: Dry-run all instances

```bash
./kipi-update.sh --dry-run
```

**Review output for each instance:**
- [ ] No errors or warnings
- [ ] Direct-clone shows commits behind count
- [ ] Subtree instances show file count comparison
- [ ] No "FAIL" lines

**Gate:** Dry-run completes with 0 failures.

### Step 4: Deploy to all instances

```bash
./kipi-update.sh
```

**Gate:** Script exits 0. Summary shows 0 failures.

### Step 5: Canary 1 validation - car-research

Run from `/Users/assafkip/Desktop/car-research`:

| # | Check | Command | Pass criteria |
|---|-------|---------|---------------|
| C1.1 | Budget audit | `python3 q-system/.q-system/scripts/instruction-budget-audit.py` | Exit 0, total < 300 |
| C1.2 | Ripple tests | `python3 q-system/.q-system/scripts/test-ripple.py` | 7/7 passed |
| C1.3 | Content lint runs | `python3 q-system/.q-system/scripts/content-lint.py` | Exit 0 or 1 (not crash) |
| C1.4 | CLAUDE.md import resolves | `head -3 CLAUDE.md` | Shows `@q-system/CLAUDE.md` |
| C1.5 | Scripts exist | `ls q-system/.q-system/scripts/ripple-verify.py q-system/.q-system/scripts/changelog-write.py` | Both exist |

**If any fail:** Do NOT proceed. Fix in skeleton, re-commit, re-push, re-run `kipi-update.sh`.

### Step 6: Canary 2 validation - KTLYST_strategy

Run from `/Users/assafkip/Desktop/ktlyst-hub/strategy`:

| # | Check | Command | Pass criteria |
|---|-------|---------|---------------|
| C2.1 | Budget audit | `python3 q-system/.q-system/scripts/instruction-budget-audit.py` | Exit 0, total < 300 |
| C2.2 | Ripple tests | `python3 q-system/.q-system/scripts/test-ripple.py` | 7/7 passed |
| C2.3 | Custom q-dir untouched | `git diff q-ktlyst/` | Empty (no changes) |
| C2.4 | Notion IDs intact | `cat q-system/my-project/notion-ids.md \| head -5` | IDs present and unchanged |
| C2.5 | .mcp.json intact | `cat .mcp.json \| python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d),'servers')"` | Server count unchanged |

**If C2.3 shows changes to q-ktlyst/:** kipi update has a scoping bug. Revert: `cd /Users/assafkip/Desktop/ktlyst-hub/strategy && git checkout HEAD~1 -- q-ktlyst/`

### Step 7: Spot check custom q-dir instances

Run from each instance directory:

**ASK_AI_consultant** (`/Users/assafkip/Desktop/ASK_AI_consultant`):
```bash
python3 q-system/.q-system/scripts/instruction-budget-audit.py
git diff q-consult/
```
Pass: exit 0, empty diff.

**4_points_consulting** (`/Users/assafkip/Desktop/4_points_consulting`):
```bash
python3 q-system/.q-system/scripts/test-ripple.py
git diff q-investigate/
```
Pass: 7/7, empty diff.

## 6. Rollback plan

| Scenario | Command | Blast radius |
|----------|---------|-------------|
| All instances need rollback | `cd /Users/assafkip/Desktop/kipi-system && git revert HEAD && git push && ./kipi-update.sh` | All instances |
| Single subtree instance broken | `cd <instance> && git checkout HEAD~1 -- q-system/` | 1 instance |
| Single direct-clone broken (car-research) | `cd /Users/assafkip/Desktop/car-research && git revert HEAD` | 1 instance |
| Custom q-dir corrupted | `cd <instance> && git checkout HEAD~1 -- <q-dir>/` | 1 instance |

## 7. Post-rollout monitoring (week after)

| Signal | What it means | Fix |
|--------|--------------|-----|
| Claude asks "what are the conventions?" unprompted | CLAUDE.md too slim | Add missing convention back to CLAUDE.md |
| Debrief skips ripple verification | Template didn't propagate or instructions ignored | Verify template, add emphasis |
| folder-structure rule never loads during code edits | `paths:` globs don't match instance file patterns | Widen globs |
| Token discipline ignored in pure conversation (no file reads) | `paths: ["**/*"]` only triggers on file read | Move 3 critical rules back into CLAUDE.md |

The last item is highest risk. `token-discipline.md` loads on first file read (`**/*`). In a pure conversation session with zero file reads, it never loads. If observed, move retry limit, agent spawn guard, and 10-call checkpoint back into CLAUDE.md.

## 8. Wiring checklist

| Check | Status | Notes |
|-------|--------|-------|
| PRD saved | Done | This file |
| Skeleton committed | Pending | Step 1 |
| Remote pushed | Pending | Step 2 |
| Dry-run clean | Pending | Step 3 |
| All instances updated | Pending | Step 4 |
| Canary 1 (car-research) passes | Pending | Step 5 |
| Canary 2 (KTLYST_strategy) passes | Pending | Step 6 |
| Spot checks pass | Pending | Step 7 |
| PRD Status updated to Done | Pending | After Step 7 |
