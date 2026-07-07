# PRD: Dissolve ktlyst-hub — Tier-2 fleet teardown + promote-and-archive the KTLYST product

**Date:** 2026-07-06
**Author:** Assaf Kipnis (engineering design: git-internals + systems-safety review)
**Status:** Draft
**Priority:** P1 (high — final batch of the fleet persona-reorg; highest blast radius)

> **Revision note (2026-07-06):** first draft treated `product` + `product-baseline`
> as coupled peers to move together with the sibling-worktree link preserved. Founder
> corrected the intent: **`product-baseline` is the successor** (the v5 canonical port),
> `product` is the deprecated old line. Salvage-check confirmed it — every gate/packaging
> file added on `product/main` exists on baseline at equal-or-greater size; the 3
> real-looking merges (ATT&CK technique-fit, fabricated-IOC rejector, source-fidelity
> gates) were all forward-ported into baseline and extended. product/main's 54 unique
> commits are 47 automated syncs + 3 already-ported merges + 4 fleet-cleanup chores.
> Nothing stranded. Mechanism changed from "preserve worktree link" to
> "**detach baseline to standalone, archive product.**"

---

## 1. Problem

`ktlyst-hub` is the last undissolved cluster in the fleet persona-reorg (RULE-2026-07-06-A). Its 6 instances must scatter into existing personas and the cluster retires. Tier-2 (registry + `~/.ktlyst/bridge/` + a GLOBAL cluster rule + git worktrees) — highest blast radius of the reorg. The product/baseline pair has an inverted git topology that must be fixed, not carried forward.

- **Evidence (successor trapped as a worktree of the corpse):** `product-baseline` — the live successor on branch `feat/v5-canonical-port` — is a **linked git worktree of `product`**, the deprecated line. Its `.git` is an 84-byte `gitdir:` pointer into `product/.git/worktrees/product-baseline`. So the *good* product's git metadata lives **inside the repo we want to delete.** Archive product blind and baseline's history dies with it.
- **Evidence (successor confirmed):** baseline's real work is the Jun-08 "forward-port the stranded v5 Advisory Control Dashboard as canonical" line. product/main's recent commits are `chore: sync ... from skeleton` — the fleet auto-updater, not development. Salvage-check (verified) shows baseline holds every gate file product added, equal-or-larger:

  | file | product | baseline |
  |---|---|---|
  | technique_verb_phase_advisor.py | 322 | 322 |
  | category_cross_check.py | 665 | 665 |
  | technique_behavior_fit_advisor.py | 186 | 219 |
  | fabricated_ioc_rejector.py | 238 | 265 |
  | inter_gate_validator.py | 582 | 640 |
  | hallucination_scanner.py | 738 | 867 |
  | cross_artifact_contradiction.py | 322 | 385 |
  | correlation_coverage.py | 873 | 1048 |

- **Evidence (symlink-pinned linkage):** `/Users/assafkip` is a symlink → `/Users/assafkipnis` (a two-Mac file migration). `product/.git/worktrees/product-baseline/gitdir` records the worktree under the old `assafkip` path; the linkage resolves **only** through that symlink. Detaching baseline into a fresh repo sidesteps this entirely (new repo, clean absolute paths).
- **Impact:** the current `persona-reorg.py` models product + product-baseline as two independent project entries. They are one repo, and the valuable half is the *linked* half. A blind coupled move orphans baseline on the next `git gc`/`prune`.
- **Root cause (scatter):** the 6 instances fan into **4 destination buckets** (consulting, cole-gtm, intel, a new ktlyst-saas). The `PERSONAS` schema assumes one parent + all projects under `parent/dst/projects/`. It cannot express a distribution, nor a promote-and-archive.

## 2. Scope

### In Scope
- New `run_dissolve()` apply path in `scripts/persona-reorg.py`: moves each ktlyst-hub instance to an **explicit per-project destination** (4 buckets), own manifest (`persona-reorg-manifest-ktlyst-hub.json`) so the Tier-2 teardown rolls back atomically.
- **`detach_worktree_to_standalone()`**: commit baseline's pending work → `git clone --single-branch` baseline into an independent repo at `ktlyst-saas/projects/product` → rename branch to `main` → **verify independence** (survives product removal) → `git worktree remove` the now-redundant baseline → archive old `product`.
- Create the anchor-less **`ktlyst-saas/`** bucket (`create=True`, existing machinery).
- Plain moves for accountant, lawyer, strategy, deliverables to their explicit buckets.
- Tier-2 side-effects: rewrite the 4 registry entries, the disabled `com.ktlyst.q-morning.plist.disabled` (rewrite only, no reload), the 2 already-stale bridge writer DEFAULT constants.
- Cluster-rule teardown: rewrite/retire `~/.claude/rules/ktlyst-cluster.md` (GLOBAL rule — HELD, founder-confirm per Cross-Instance Preflight).
- Reproducer-first tests (fable-discipline): a codified salvage-check + an independence test (clone survives source deletion).
- Gates: `reorg-stale-ref-audit.py` exit 0, `kipi check` FAIL ≤ 2, `--remediate` sweep.

### Out of Scope
- Finishing or reviewing the v5 port itself. baseline ships as-is (founder: moved completely to it).
- Deleting old `product` outright. It is **archived** (reversible), not `rm`'d.
- Bridge protocol / schema changes. Only stale path constants touched.
- Reloading the q-morning launchd job (it is `.disabled`).

### Non-Goals
- Not building a general many-to-many reorg engine. Scoped dissolution path.
- Not merging product's history into baseline. baseline's own history is the product's history; product's extra commits are proven-redundant and archived, not merged.

## 3. Changes

### Change 1: `KTLYST_HUB` dissolution map + `run_dissolve()` apply path

- **What:** dedicated dissolution structure (per-project explicit `dst`) + distribution-aware apply path, distinct from `run_apply()`.
- **Where:** `scripts/persona-reorg.py`
- **Why:** §1 root cause (scatter).
- **Exact change (structure):**

```python
KTLYST_HUB = {
    "label": "dissolve ktlyst-hub cluster (Tier-2)",
    "buckets": [{"name": "ktlyst-saas", "dst": os.path.join(PROJECTS, "ktlyst-saas")}],
    "projects": [
        {"name": "accountant", "src_sub": "ktlyst-hub/accountant",
         "dst": _pj("consulting", "accountant"), "registry": "accountant"},
        {"name": "lawyer", "src_sub": "ktlyst-hub/lawyer",
         "dst": _pj("consulting", "lawyer"), "registry": "ktlyst_lawyer", "rule": "ktlyst-cluster"},
        {"name": "strategy", "src_sub": "ktlyst-hub/strategy",
         "dst": _pj("cole-gtm", "strategy"), "registry": "KTLYST_strategy", "rule": "ktlyst-cluster"},
        {"name": "deliverables", "src_sub": "ktlyst-hub/deliverables",
         "dst": _pj("intel", "deliverables")},
        # PROMOTE: baseline (successor) becomes the standalone product; OLD product archived.
        {"name": "product", "src_sub": "ktlyst-hub/product-baseline",
         "dst": _pj("ktlyst-saas", "product"), "registry": "ktlyst",
         "rule": "ktlyst-cluster", "promote_from_worktree": {
             "branch": "feat/v5-canonical-port",
             "main_repo": "ktlyst-hub/product",
             "archive_main_to": "_archive/product-ktlyst-old-2026-07-06"}},
    ],
    "plists": ["com.ktlyst.q-morning.plist.disabled"],  # rewrite only, NO reload
}
# _pj(bucket, name) -> PROJECTS/bucket/projects/name
```

- **Apply sequence (`run_dissolve`):**
  1. Refuse if already migrated (add `"ktlyst-hub"` to `MIGRATED` on completion).
  2. **Precondition snapshot:** record `git -C product worktree list --porcelain` + baseline's `git status --porcelain` into the manifest (BEFORE state, for rollback verification).
  3. Create `ktlyst-saas/` bucket (`_mkdir`/`_create_file`/roster).
  4. Plain-move accountant, lawyer, strategy, deliverables to explicit `dst`; rewrite each registry entry right after its move.
  5. **Promote product** via `detach_worktree_to_standalone` (Change 2).
  6. Rewrite the disabled plist (no reload); update the 2 bridge DEFAULT constants.
  7. `kipi check` gate; abort (rollback-able) on regression > baseline.
  8. HELD: surface `ktlyst-cluster.md` rewrite for founder confirm — never auto-applied.
- **Scope:** skeleton tool, single run against this machine's fleet.

### Change 2: `detach_worktree_to_standalone()` — promote successor, sever the corpse

- **What:** turn the linked worktree into a real independent repo, then archive the old main.
- **Where:** `scripts/persona-reorg.py` (new fn).
- **Why:** §1 — the good product's git lives inside the repo we archive; a clone gives it independent history + `.git`, and drops the `assafkip` symlink dependency for free.
- **Exact change:**

```python
def detach_worktree_to_standalone(main_repo, branch, worktree_dir, new_repo, archive_to):
    """Promote a linked worktree to a standalone repo, then archive the old main.
    git-correct: a clone copies the object store, giving `branch` full independent
    history and its own .git — severed from `main_repo`. Pending work in the worktree
    is committed first (a clone never carries uncommitted changes)."""
    # 1. preserve in-flight work on the worktree (2 tracked files today)
    if sh(["git", "-C", worktree_dir, "status", "--porcelain"])[1].strip():
        sh(["git", "-C", worktree_dir, "add", "-A"])
        sh(["git", "-C", worktree_dir, "commit", "-m",
            "chore: preserve in-flight work before standalone detach (persona-reorg)"])
    # 2. clone the branch into its own repo
    code, out = sh(["git", "clone", "--single-branch", "--branch", branch,
                    "file://" + main_repo, new_repo])
    if code != 0:
        raise RuntimeError(f"detach clone failed: {out}")
    # 3. it's THE product now — make the branch `main`
    sh(["git", "-C", new_repo, "branch", "-m", branch, "main"])
    # 4. VERIFY INDEPENDENCE — the clone must survive the source being gone.
    _mkdir(os.path.dirname(archive_to)) if not os.path.isdir(os.path.dirname(archive_to)) else None
    sh(["git", "-C", main_repo, "worktree", "remove", "--force", worktree_dir])  # drop redundant wt
    _move(main_repo, archive_to)                                                # archive old product
    code, _ = sh(["git", "-C", new_repo, "log", "-1", "--oneline"])             # still works?
    ok = (code == 0) and os.path.isdir(os.path.join(new_repo, ".git")) \
        and "/Users/assafkip/" not in sh(["git", "-C", new_repo, "worktree", "list"])[1]
    print(c(f"    detach: standalone {'independent OK' if ok else 'FAILED'} "
            f"(survives source removal)", "32" if ok else "1;31"))
    _manifest.setdefault("promotions", []).append(
        {"new_repo": new_repo, "archived": archive_to, "orig_main": main_repo,
         "orig_worktree": worktree_dir, "branch": branch})
    return ok
```

- **Scope:** skeleton tool.

### Change 3: rollback for a promotion

- **What:** `run_rollback` reverses a promotion: move archived product back from `_archive`, `git worktree add` baseline back at its original path on its branch, remove the standalone clone (only if it has no commits past the clone point — else KEEP + flag; never destroy unmerged work).
- **Where:** `scripts/persona-reorg.py` (`run_rollback`, new `promotions` handling).
- **Why:** the Tier-2 teardown must be reversible to the BEFORE-snapshot topology.
- **Scope:** skeleton tool.

### Change 4: bridge DEFAULT constants + cluster-rule teardown (HELD)

- **What:** (a) update 2 stale bridge DEFAULT path constants; (b) rewrite/retire `~/.claude/rules/ktlyst-cluster.md`.
- **Where:** `~/.ktlyst/bridge/bridge-sync.py:20`, `~/.ktlyst/bridge/write-legal-flags.py:21`; `~/.claude/rules/ktlyst-cluster.md` (lines 9,10,12,13,18,20).
- **Why:** bridge DEFAULTs already wrong (`~/Desktop/ktlyst-hub/...`, auto-detect covers) — fix for correctness, low risk. Cluster rule hardcodes ktlyst-hub paths and is GLOBAL → HELD, founder-confirm.
- **Scope:** bridge = local; cluster rule = global (HELD).

## 4. Change Interaction Matrix

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| C2 archive old product | C2 clone independence | Clone must be proven independent BEFORE product is archived-then-verified | Sequence: clone → worktree-remove → archive → `git log` on clone proves survival |
| C1 registry `ktlyst` rewrite | C2 promotion | `ktlyst` must point at the new standalone, not the archived old | Rewrite `ktlyst` → new standalone path after detach completes |
| C2 branch rename → main | any tooling expecting `feat/v5-canonical-port` | Branch name changes | Grep fleet for the old branch name in configs; none expected (in-repo branch) |
| C1 `create=True` ktlyst-saas | existing buckets | Same machinery | Reuse `_mkdir`/`_create_file`/`_write_roster` |
| C4 symlink-free clone | C4 cluster/bridge text rewrites | Disjoint (git plumbing vs doc text) | No overlap |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `scripts/persona-reorg.py` | Edit | ~130 | ~5 |
| `scripts/test_persona_reorg.py` | Edit | ~80 | 0 |
| `~/.ktlyst/bridge/bridge-sync.py` | Edit | +1 | -1 |
| `~/.ktlyst/bridge/write-legal-flags.py` | Edit | +1 | -1 |
| `~/.claude/rules/ktlyst-cluster.md` | Edit (HELD) | TBD | TBD |
| `instance-registry.json` | Edit (by tool) | 4 paths | 4 paths |
| `com.ktlyst.q-morning.plist.disabled` | Edit (by tool) | 4 paths | 4 paths |

## 6. Test Cases

### [Change 2] Detach-to-standalone (reproducer-first)

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 2.1 | DET | Clone is independent | temp repo + linked worktree on a branch; detach | new repo has own `.git` dir + full branch history | `git -C new log` count == branch history count |
| 2.2 | DET | **Killer test — survives source deletion** | after detach, `rm -rf` the temp main | new repo still fully functional | `git -C new log`/`status` exit 0 after source gone |
| 2.3 | DET | Pending work preserved | dirty worktree (1 tracked change) before detach | change present in clone | file content matches in new repo HEAD |
| 2.4 | DET | Symlink dependency gone | back-pointer written via symlinked alt-user path | new repo has no symlinked path | no `/Users/<alt>/` in `git -C new worktree list` |
| 2.5 | DET | **Negative — salvage-check catches a real strand** | temp main has a file NOT on the branch | salvage-check flags it | fn returns the stranded path (would BLOCK archive) |

### [Change 1] Distribution map

| # | Type | Scenario | Expected | Pass Criteria |
|---|------|----------|----------|---------------|
| 1.1 | DET | 6 sources → 4 buckets, exact `dst` each | matches taxonomy table | assert every `dst` |
| 1.2 | DET | `build_oldnew_map` includes ktlyst-hub moves (incl. baseline→product) | all pairs present | audit + remediate see one source |
| 1.3 | INT | Dry run prints plan, changes nothing | disk unchanged | `git status` on ktlyst-hub unchanged post-dry |

### [Change 3] Rollback

| # | Type | Scenario | Expected | Pass Criteria |
|---|------|----------|----------|---------------|
| 3.1 | DET | Rollback restores BEFORE topology | product back from archive, baseline worktree re-added | porcelain == manifest BEFORE-snapshot |
| 3.2 | DET | Rollback KEEPS a clone with new commits | clone advanced post-detach | clone kept + flagged, not destroyed |

## 7. Regression Tests

| # | What to Verify | How | Pass |
|---|----------------|-----|------|
| R-1 | Existing persona tests pass | `python3 scripts/test_persona_reorg.py` | all green |
| R-2 | Normal-persona apply refuses migrated persona | `--apply --persona dev-tools` | exit 3 |
| R-3 | `_repair_git_worktrees` (nested path) unchanged | kipi-investigations-style case | still re-links |
| R-4 | `kipi check` ≤ baseline | `kipi check` | FAIL ≤ 2 |
| R-5 | Stale-ref audit clean | `reorg-stale-ref-audit.py` | exit 0 |

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| C1 moves | `--rollback --persona ktlyst-hub` (manifest: moves back, `.bak` restore, empty ktlyst-saas removed) | Low |
| C2 promotion | move product back from `_archive`, `git worktree add` baseline at original path/branch, remove clone if unadvanced | Medium — if clone advanced, KEEP + flag (never destroy work); snapshot proves target |
| C4 cluster rule | restore from `.persona-reorg.bak` | Low (HELD until confirmed) |
| Registry / plist | `.bak` restore via manifest | Low |

## 9. Change Review Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Additive (no breaking removals) | ☐ | new apply path; `run_apply` untouched |
| No conflict with enforced rules | ☐ | fable-discipline reproducer-first; no-orphan-findings honored |
| No hardcoded secrets | ☐ | paths only |
| Propagation verified | ☐ | skeleton-local tool; run once |
| Exit codes preserved | ☐ | abort=2, refuse-migrated=3 |
| AUDHD-friendly | ☐ | no pressure language |
| Test coverage per change | ☐ | C1/C2/C3 covered; C4 HELD manual |
| **Destructive-op check** | ☐ | old product is `_move`d to `_archive`, never `rm -rf`; worktree-remove only after clone verified independent |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| ktlyst-hub instances resolved | 0/6 | 6/6 | `ls ~/projects/ktlyst-hub` empty/gone |
| Product git independence | baseline pinned inside product | standalone | `git -C ktlyst-saas/projects/product log` works with product archived |
| Symlink-dependent git paths | ≥1 | 0 | no `/Users/assafkip/` in new repo pointers |
| Stranded work lost | 0 (verified) | 0 | salvage-check green before archive |
| kipi check FAIL | ≤2 | ≤2 | `kipi check` |
| Registry entries repointed | 0/4 | 4/4 | `kipi list` resolves |

## 11. Implementation Order

1. **Tests first.** 2.5 (salvage-check catches a strand) + 2.2 (clone survives source deletion) are the two that matter; write them red.
2. **C2** `detach_worktree_to_standalone` + salvage-check helper → make 2.1–2.5 green.
3. **C1** `KTLYST_HUB` map + `run_dissolve()` + dry wiring → 1.1–1.3 green.
4. **C3** rollback promotion handling → 3.1–3.2 green.
5. **Dry run** `--persona ktlyst-hub` → **founder reviews** (gate — nothing moves before this).
6. **Apply** → 4 plain moves + promote product + registry/plist/bridge.
7. **C4 HELD:** founder confirms `ktlyst-cluster.md` rewrite/retire → apply.
8. `--remediate` → `reorg-stale-ref-audit.py` exit 0 → `kipi check` ≤ 2.
9. Track fleet-map.md + decisions.md (RULE-2026-07-06-G) per move.

## 12. Open Questions

| Question | Owner | Resolution |
|----------|-------|------------|
| Product bucket A vs B | Founder | **RESOLVED → B (`ktlyst-saas/`)** [founder-delegated] |
| Which is the successor | Founder | **RESOLVED → baseline; product deprecated** [founder-directed, salvage-verified] |
| Stranded work in old product | — | **RESOLVED → none** (8/8 gate files present on baseline, equal-or-larger) |
| Retire cluster rule vs rewrite | Founder | recommend RETIRE ktlyst-hub topology; thin persona-authority note survives. HELD |
| Keep old product past archive | Founder | archived to `_archive/` (reversible); delete later if desired |

## 13. Wiring Checklist (MANDATORY)

| Check | Status | Notes |
|-------|--------|-------|
| PRD saved to `q-system/output/prd-ktlyst-hub-dissolution-2026-07-06.md` | ☑ | this file |
| Code/config changes implemented + tested | ☐ | pending build |
| New files listed in folder-structure rule | ☐ | none new |
| New conventions in root CLAUDE.md | ☐ | N/A |
| Memory entry for decisions/patterns | ☐ | save: baseline=successor, promote-and-archive pattern, salvage-check method |
| `kipi update --dry` propagation | ☐ | persona-reorg.py is skeleton-local, not fanned |
| `kipi update` run | ☐ | N/A |
| PRD Status → Done | ☐ | after apply + gates |

---

## Skeptic (one round before build)

**Q1 — strongest argument against?** Just `git clone` baseline by hand and `mv` old product to `_archive` — no tool change. **Rebuttal:** it's the *final* batch; the dissolution also moves 4 other instances + registry + bridge + cluster rule, and must roll back as one unit. A hand-run clone/archive is outside the manifest and un-gated. The tool owns it so the whole Tier-2 teardown is reversible and kipi-check-gated.

**Q2 — smallest experiment to disprove?** Test 2.2: clone the branch, delete the source, confirm the clone still works. If it doesn't survive, the detach thesis is wrong and I stop.

**Q3 — cheapest non-build alternative?** Keep baseline as a worktree and just move both (original draft). Rejected: leaves the live product's git life inside an archived repo — the exact fragility this fixes.
