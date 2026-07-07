# CONTINUE HERE — ktlyst-hub dissolution (final persona-reorg batch)

## ⇢ Paste this as your first message after clearing context

> Resume the ktlyst-hub dissolution. My work is COMMITTED on branch
> `chore/retire-eyeball-fleet-map` (a parallel session switched this repo to
> `feat/fleet-ingestion-coverage-contract`, which has no `scripts/`, so the files
> look missing on disk — they're safe in git). FIRST run
> `git checkout chore/retire-eyeball-fleet-map` to restore the working tree, then
> `python3 scripts/test_persona_reorg.py && python3 scripts/test_persona_reorg_detach.py`
> to confirm green. Then read
> `q-system/output/plans/ktlyst-hub-dissolution-CONTINUE-2026-07-07.md` and
> `q-system/output/prd-ktlyst-hub-dissolution-2026-07-06.md`. We stopped AT THE
> DRY-RUN REVIEW GATE — nothing has moved. Do not apply until I approve the dry run.
> Pick up at "Next actions" below.

---

## ⚠ Incident that must be understood before resuming

- **Two sessions shared ONE checkout of `~/projects/kipi-system`.** The other
  session (workstream: `feat/fleet-ingestion-coverage-contract`, "fleet-canonical
  ingestion coverage contract") switched the shared repo's branch at 18:20 on
  2026-07-06 (commit `9f591c1`). That removed `scripts/` from the working tree
  because `scripts/` is not tracked on that branch.
- **Nothing was lost.** All my work was captured by an auto-commit ("chore: update
  project files", 18:15) on `chore/retire-eyeball-fleet-map`. Verified: restored
  all three files from that branch tip and BOTH test suites PASS.
- **Hazard for later (worth an RCA / guardrail):** parallel agent sessions must not
  share one working tree. Use `git worktree` per session, or serialize. This is how
  the working tree got yanked mid-task. Not urgent to the dissolution; capture it.

## Where we are (2026-07-06, carried to 2026-07-07)

**STATUS: at the DRY-RUN REVIEW GATE. Nothing has moved. Founder must review the
dry run before any apply.** The tool is built and green.

### What's built + committed (branch `chore/retire-eyeball-fleet-map`)
- `scripts/persona-reorg.py` — the ktlyst-hub dissolution is added:
  - `salvage_check(main_repo, keep_branch, drop_ref, include_skeleton=False)` —
    files on the old line not on the successor; skips `SKELETON_MANAGED`
    (`plugins/`, `q-system/`, `.claude/`, `CLAUDE.md`) which re-sync via kipi update.
  - `promote_worktree_to_standalone(worktree_dir, main_repo, branch, new_repo)` —
    commit pending → `git clone --single-branch` via `file://` → rename branch to
    `main`. Severs the successor from the old repo.
  - `verify_repo_independent(repo)` — `.git` is a dir, `git log` works, no foreign
    `/Users/<other>` path. The "survives source deletion" proof.
  - `KTLYST_HUB` map (6 sources → 4 buckets), `run_dissolve()`, `dissolve_preview()`,
    rollback `promotions` handling, `build_oldnew_map()` extended.
- `scripts/test_persona_reorg_detach.py` — hermetic git reproducer. Killer test
  (2.2, clone survives source deletion) + guard (2.5, salvage flags real strand,
  skips skeleton). GREEN.
- `scripts/test_persona_reorg.py` — added ktlyst-hub map tests (1.1/1.2). GREEN.
- `q-system/output/prd-ktlyst-hub-dissolution-2026-07-06.md` — the PRD (detach
  version). On disk (untracked, survived).
- `q-system/output/plans/ktlyst-hub-reorg-2026-07-06.md` — plan, updated to detach.

### The decisions already made (founder-directed / delegated)
- **product-baseline is the LIVE successor** (v5 canonical port); **product is the
  deprecated old line** kept alive only by bot syncs. Salvage-verified: 0 product
  code stranded (all `ktlyst_v2/` gate files on baseline, equal-or-larger).
- **Product bucket = B**: new `ktlyst-saas/` bucket. product-baseline → promoted to
  standalone `ktlyst-saas/projects/product`; old product → `_archive/`.
- **Mechanism = promote-and-archive** (NOT preserve the worktree link).

### The dry run output (the review artifact — re-run to see it)
`python3 scripts/persona-reorg.py --persona ktlyst-hub`
```
1 bucket created     -> ktlyst-saas/
4 plain moves        -> consulting(accountant,lawyer), cole-gtm(strategy), intel(deliverables)
1 product PROMOTED   product-baseline -> ktlyst-saas/projects/product (standalone, branch->main)
1 old product ARCHIVED -> _archive/product-ktlyst-old-2026-07-06 (reversible)
4 registry rewrites  (accountant, ktlyst_lawyer, KTLYST_strategy, ktlyst)
1 disabled plist     com.ktlyst.q-morning.plist.disabled (rewrite only, no reload)
2 bridge DEFAULTs    bridge-sync.py, write-legal-flags.py (low-risk; auto-detect covers)
salvage: 406 skeleton-sync skipped | 1 real file preserved in archive
1 global rule        ktlyst-cluster.md [HELD — retire]
```

## OPEN — founder decisions still needed

1. **The 1 non-skeleton file** `scripts/eng_persona_review_workflow.js` on old
   product — a 92-line eng-review harness that hardcodes `product-baseline` as its
   target (dead path after the move). Preserved in the archive regardless.
   **My call: leave it in the archive, don't carry to the live product.** Override
   if actually used.
2. **HELD — `~/.claude/rules/ktlyst-cluster.md`** (GLOBAL rule): retire the
   ktlyst-hub cluster topology (the cluster is dissolving). Needs founder confirm
   (Cross-Instance Preflight). Rows reference: lawyer, strategy, product.
3. **HELD — bridge defaults**: low-risk, already-stale `~/Desktop/ktlyst-hub` paths.
   Not really a judgment call; can just apply with the run.

## Next actions (in order)

1. `git checkout chore/retire-eyeball-fleet-map` (restore working tree).
2. Confirm green: both test files.
3. **Remaining test before apply:** add the rollback INTEGRATION test (3.1/3.2 in
   the PRD) to `test_persona_reorg_detach.py` — apply-then-rollback restores the
   BEFORE worktree topology, keeps the clone flagged. (Code exists; test doesn't.)
4. On founder GO for apply: `python3 scripts/persona-reorg.py --persona ktlyst-hub --apply`
   (salvage-gate → create bucket → 4 moves → promote+archive → registry/plist/bridge
   → kipi check). Reversible via `--rollback --persona ktlyst-hub`.
5. Founder-confirm the HELD `ktlyst-cluster.md` retirement → apply that edit.
6. `--remediate` sweep → `python3 scripts/reorg-stale-ref-audit.py` exit 0 →
   `kipi check` FAIL ≤ 2.
7. Add `"ktlyst-hub"` to the tool's `MIGRATED` set (prevents re-apply).
8. Update `q-system/canonical/fleet-map.md` + `decisions.md` (new RULE-2026-07-06-G
   for the dissolution), per the canonical-tracks-as-you-go rule.
9. Resolve spillover `sp-bcb38f04` (product/product-baseline fork) — the
   promote-and-archive IS the resolution once applied.

## Verification commands (re-confirm green on resume)
```bash
git checkout chore/retire-eyeball-fleet-map
python3 scripts/test_persona_reorg.py          # pure-fn: PASS
python3 scripts/test_persona_reorg_detach.py   # detach: PASS
python3 scripts/persona-reorg.py --persona ktlyst-hub   # DRY (changes nothing)
```

## Key facts (so a fresh session doesn't re-derive)
- `product` (git main, deprecated) vs `product-baseline` (branch
  `feat/v5-canonical-port`, live successor, a LINKED WORKTREE of product).
- `/Users/assafkip` → `/Users/assafkipnis` is a two-Mac migration symlink much
  fleet git plumbing rides on. A fresh clone (the detach) drops that dependency.
- Memory saved: `project_ktlyst_product_successor.md`.
