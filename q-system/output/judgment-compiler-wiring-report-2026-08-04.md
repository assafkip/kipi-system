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
| R-3 | full prd-os suite | `422 passed, 1 skipped` (was 399 + 1 before this work; +23 new, zero regressions) |
| R-8 | mutation test | 17 single-invariant corruptions applied to a copy; **16 killed**. The one survivor is a defensive build-time assert no normal path reaches, labelled as such in the code; its enforced half is the read-side check (test_n7). |
| R-9 | concurrency | 6 concurrent `capture` processes → 6 receipts, sequences 1..6, `verify` exit 0 |
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

## Adversarial review: 17 findings, all dispositioned

A senior-staff adversarial review (`claude-adversarial`, a first-class reviewer
source in findings_writer) returned 1 blocker, 6 major, 7 minor, 3 nit. Every
one was real and reproduced. 16 fixed in code; 1 deferred with its own tracked
issue. Highlights:

- **Blocker — concurrent capture forked the ledger while every writer exited 0.**
  Unlocked read-modify-append on a ledger deliberately shared across worktrees.
  Now `fcntl.flock`-guarded. Repro before: corruption; after: 6 concurrent
  captures → chain intact.
- **Deleting the tip anchor re-opened the entire truncation hole** for one `rm`
  (cheaper than editing it, and a bad rsync does it by accident). A missing
  anchor over a non-empty ledger is now an error.
- **Evidence refs were grammar-matched, never resolved** — `commit:zzzz` and
  `finding:prd-does-not-exist/finding-999` were both recorded as the evidence
  justifying a rejection. Now every ref kind is opened.
- **Findings and judgment ledgers diverged on partial failure.** The findings
  file now rolls back when capture fails.
- **Deferred with its own issue (sp-1caf70c9):** omitting `--reason-code` skips
  the evidence gate. Closing it changes the contract of a command every fleet
  instance inherits, so it does not ride along inside this PRD. Interim: the
  bypass is counted, not assumed — `evaluate` reports `ungated_decision_rate`.

## Mistake made and corrected during this work

The dogfood run used a sandbox that had copied a `.git` directory, so
`_ledger_root` correctly resolved to the **main checkout** and wrote 17 test
receipts into the live ledger. The behavior was right; the harness was wrong.
The files were moved out (preserved in the session scratchpad, not deleted from
any history — the ledger had existed for three minutes and held zero real
workflow decisions), the repo is back to its true pre-feature state with no
`.prd-os/judgments*` files, and a test now pins the shared-root behavior.

## Defect found and fixed during this work (self-attack)

Truncating the ledger tail (`head -1 judgments.jsonl`) returned `VERIFY PASS`.
A prefix of a valid hash chain is a valid chain. Fixed with `sequence` +
tip anchor + `verify --cross-check`; the same attack now exits 2 with
`ledger is TRUNCATED: 1 receipt(s) present, tip anchor recorded 2`.
Recorded in the PRD (N-15..N-20) and the CHANGELOG.

## Honest gaps — NOT claimed as wired

0. **Capability gate: my test passes; the gate is RED on two unrelated tests.**
   Fresh full-clone run of the final branch state: `declared: 116 tests`,
   `tests: ran=114`, and `plugins/prd-os/tests/test_judgment_compiler.py` is
   among those that ran and is NOT in the failure list. The 2 REDs are 60s
   TIMEOUTS in `test-review-invoker-provenance.sh` and
   `test-updater-issue-sequence.py`. Neither is touched by this branch
   (`git diff origin/main...HEAD` shows zero hits), both fail on the main
   checkout too (exit 127, missing interpreter/dependency), and the last commit
   to either is dd8318a (ASK-221). Pre-existing, not caused here — but the gate
   is red, so `kipi check` green is still NOT claimed.

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
