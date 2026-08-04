# WIRING REPORT — Judgment Compiler (ASK-363)

Date: 2026-08-04. Branch: `worktree-judgment-compiler`. Every row is "ran X, got Y".

## Definition-of-done rows

| Check | Status | Evidence |
|---|---|---|
| New script has a caller | PASS | `findings_writer.cmd_set_disposition` imports and calls `judgment_compiler.capture_from_triage` (the one chokepoint every triage flows through). Proven live: sandbox triage produced 2 chained receipts. |
| New CLI registered | PASS | `kipi judgment <assemble\|capture\|verify\|evaluate\|sample-check\|policy-candidates\|selftest>` case block + 6 usage lines. Ran `kipi judgment selftest` → SELFTEST PASS; `kipi judgment verify` from a sandbox repo read THAT repo's ledger, not the skeleton's. |
| Command doc updated | PASS | `plugins/prd-os/commands/prd-triage.md` step 4 documents `--reason-code` / `--evidence` and the refusal behavior. |
| Test exists and is discoverable | PASS | `plugins/prd-os/tests/test_judgment_compiler.py`, 55 tests. Self-executing (`python3 <path>` → 55 passed) per the `test_prd_split_from_linear.py` precedent. |
| Capability manifest entry | PASS | `expected_tests` += `{"path": "plugins/prd-os/tests/test_judgment_compiler.py", "runner": "python3", "timeout_s": 240}`. |
| Plugin version bumped | PASS | prd-os 0.9.2 → 0.10.2; CHANGELOG entries for the feature and the truncation fix. lefthook `plugin-version-bump` green. |
| Ledger uses the shared worktree root | PASS | `_ledger_dir` calls `prd_runner._ledger_root` (the sp-bc42f1d3 scar helper) for both `judgments.jsonl` and the candidates ledger. |
| Exit-code contract preserved | PASS | 0 success / 2 validation error, matching findings_writer. |
| Kill switch | PASS | `KIPI_JUDGMENT_CAPTURE=0` → legacy behavior byte-identical, zero receipts written (test `test_kill_switch_restores_legacy_behavior`). |

## Regression rows

| # | What | Result |
|---|---|---|
| R-1 | v1 calibration self-test | `SELFTEST PASS: scoring changes, schema and coverage enforced, blind export clean` |
| R-2 | v1 dataset verification | `VERIFY PASS: 50 unique cases, 20/20/10 balance, all source hashes match` |
| R-3 | full prd-os suite | `406 passed, 1 skipped` (was 399 + 1 before this work; +7 new) |
| R-5 | read-only execution | `test_verify_evaluate_selftest_survive_read_only_repo` chmods the tree 0555; verify, evaluate and selftest all exit 0 |
| R-6 | `kipi check` | **PARTIAL — see below** |

## Live end-to-end proof (sandbox repo, never the live `.prd-os`)

```
add 2 findings via findings_writer            -> finding-1, finding-2
set-disposition finding-1 accepted            -> receipt jr-77e3335a… (reason_code null,
                                                 missing_context ["human.reason_code", …])
set-disposition finding-2 rejected            -> REFUSED exit 2:
  --reason-code duplicate (no evidence)          "requires an evidence ref with prefix
                                                  ['finding:','issue:','spillover:']"
                                                 findings file md5 UNCHANGED (fail-fast)
same call + --evidence finding:…/finding-1    -> accepted, receipt jr-9b7382d8…, chained
verify                                        -> VERIFY PASS: 2 receipt(s), chain intact
```

## Defect found and fixed during this work (self-attack)

Truncating the ledger tail (`head -1 judgments.jsonl`) returned `VERIFY PASS`.
A prefix of a valid hash chain is a valid chain. Fixed with `sequence` +
tip anchor + `verify --cross-check`; the same attack now exits 2 with
`ledger is TRUNCATED: 1 receipt(s) present, tip anchor recorded 2`.
Recorded in the PRD (N-15..N-20) and the CHANGELOG.

## Honest gaps — NOT claimed as wired

1. **`kipi check` is not fully green, and was not green before this change.**
   - Stage 1 `remote-coverage-check.py` exits 2 on the *main checkout* too
     (untracked sibling worktrees with no remote). Pre-existing, unrelated.
   - `capability-gate.py` refuses to run from a `.claude/worktrees` copy by
     design (exit 3). Run it from the primary checkout after merge.
   - A shallow-clone attempt to run it out-of-tree produced only
     `fatal: not a tree object` FCU errors — an artifact of `--depth 1`, not a
     real result. A full-clone run was still executing at report time.
   - **Therefore: `kipi check` green is NOT claimed. It must be run from the
     primary checkout post-merge.**
2. **The live slash-command path does not have this yet.** `/prd-triage` loads
   from `~/.claude/plugins/marketplaces/kipi/plugins/prd-os`, which is a clone
   of `github.com/assafkip/kipi-system.git` currently serving prd-os **0.6.0**
   — three minor versions behind main (0.9.2) before this change even lands.
   So the capture path is inert in real Claude sessions until the branch merges
   AND that clone pulls. Pre-existing fleet drift, captured as spillover
   **sp-fe57de2d**, not invented by this work. The `kipi judgment` CLI and
   direct `findings_writer.py` invocation are unaffected (they resolve through
   `$KIPI_HOME` / the caller's cwd).
3. **Evidence refs are grammar-checked, not resolved.** The gate proves a ref
   of the right kind was supplied; it does not open the target to confirm it
   exists. `verify --cross-check` is the only check that reads an independent
   source. Stated here rather than left for a reviewer to discover.
4. **Zero prospective calibration cases exist.** Release gates are all closed
   and `evaluate` reports `passed: false`. No calibration claim is made.

## Propagation

`plugins/` and `kipi` are skeleton-owned, so `kipi update --dry` → `kipi update`
is required to reach instances. NOT run from this worktree (it would sync a
branch state to the whole fleet). Sequence at merge: merge to main → run
`kipi check` from the primary checkout → `kipi update --dry` → `kipi update` →
refresh the marketplace clone (sp-fe57de2d).
