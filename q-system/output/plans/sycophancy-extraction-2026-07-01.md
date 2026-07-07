# Sycophancy audit: extract the generic core from /q-morning

**What/why:** Pi computation (`calculate_pi_independent`, sycophancy-harness.py:106) only ever runs behind the morning bus artifact (run_harness SKIPs without `bus/<date>/sycophancy-audit.json`). The rule mixes generic behavior with Phase-6/synthesizer wiring, which also ships to HuntKit with six dangling references. ktlyst strategy sits at pi≈0.88 with nothing able to notice. Item #1 of morning-extraction-audit-2026-07-01.md, founder-approved.

**Approach (pick):** (a) Two-layer rule split + standalone harness mode + monthly SessionStart check. (Alternatives: (b) new sibling script instead of a harness mode — duplicates the parser, rejected; (c) single rule with a marked generic section for HuntKit to extract — brittle sed-extraction, rejected.)

**Files to touch:**
- `.claude/rules/sycophancy-core.md` (new: portable behavioral rules + origin tagging, zero Phase-6/harness/synthesizer/bus references)
- `.claude/rules/sycophancy.md` (slims to: core pointer + kipi enforcement wiring; Phase-6/synthesizer sentences move to morning-pipeline.md)
- `.claude/rules/morning-pipeline.md` (absorbs the two morning-coupled sycophancy rules)
- `q-system/.q-system/sycophancy-harness.py` (`--standalone [--json]` mode: pi over canonical/decisions.md, no bus dependency; alert exit 1 when pi >= 0.7 with total >= 5)
- `q-system/.q-system/scripts/sycophancy-monthly-check.py` (new SessionStart hook: month-stamp file, first session each month runs the standalone check and surfaces the verdict)
- `.claude/settings.json` + `settings-template.json` (wire monthly check; fix token-guard `|| true` in template → resolves sp-dd731488 through the spillover flow)
- Phase 2 (after fleet propagation): `~/projects/4_points_consulting/scripts/sync-huntkit.py` RULE_FILES ships sycophancy-core.md; rerun sync

**Acceptance criteria:**
- [x] `--standalone` reproducer: 7 fixture paths ran (alert pi=0.750 exit 1, pass 0.333 exit 0, tiny total<5 exit 0, no-tags, missing file, JSON mode)
- [x] Negative self-test: no-tags fixture → INSUFFICIENT-DATA, no crash, no false alert
- [x] Date-mode untouched: `2026-07-01` run → SKIP exit 0
- [x] Monthly check: 4 paths proven on isolated tree copy (no stamp fires + ALERT surfaced; same-month silent; stale stamp refires; healthy = no alert)
- [x] Template fix: exit-2 propagation proven (new if-then form → 2; old `|| true` form → 0; missing → 0) + regression test test-token-guard-template-wiring.sh with negative self-test. sp-dd731488 ledger closure PENDING: issue_runner rejects hand-authored specs (prd_split marker required) → needs a prd-os pass, queued
- [x] `sycophancy-core.md` grep: CLEAN
- [x] Enforcement-guard hook passed on all rule writes (blocked once on plan wording, fixed)
- [ ] HuntKit: sync-huntkit.py RULE_FILES → sycophancy-core.md + rerun (needs live kipi update to 4_points first, queued)

**Patterns to follow:** existing harness exit-code contract (0/1/2); SessionStart hook idiom from settings.json; scar-anchored comments (ktlyst pi=0.88 unobserved; huntkit dangling refs 2026-07-01).
