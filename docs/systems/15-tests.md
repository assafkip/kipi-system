# 15. Tests: every proof in the tree

Every test file the code carries, grouped by directory, each with the first line of its own docstring where it has one. A script with no test here has no proof beyond its own run. The coverage gate holds this page to naming every test file; `capability_manifest.py` separately holds that every declared test exists and every existing test is declared.

## Components

```mermaid
flowchart LR
    C[capability fragments: one per declared test] --> G[capability-gate.py: declared vs actual]
    T[(test files, 269)] --> G
    G --> V[verify.sh: pre-commit --staged, identical in CI]
    T --> P[pytest, run by verify.sh and by ci-shaped-run.sh]
    M[mutation on a copy: the negative self-test discipline] -.proves each test can fail.-> T
```

The proof chain. Each test is declared in a capability fragment so the gate can tell a missing test from a never-declared one; the floor script runs them identically as a pre-commit hook and in continuous integration; and the fable-discipline rule asks that each new test be seen red under a mutation on a copy before its green is trusted, because a test that cannot fail is decoration.

## Flow: a test earns its place

```mermaid
sequenceDiagram
    participant D as Developer or agent
    participant T as new test file
    participant F as capability fragment
    participant L as fable-discipline-lint.py
    participant V as verify.sh
    D->>T: write the reproducer first, see it red
    D->>D: fix, see it green
    D->>T: mutate a copy of the code, see the test red, restore
    D->>F: one fragment file declaring the test path and runner
    D->>L: PostToolUse on the test file
    L-->>D: refuses a test that touches a live data path or drives a pager unstubbed
    D->>V: git commit runs verify.sh --staged
    V-->>D: green locally means green in CI, same script
```

Reproducer first, mutation second, declaration third, and the same floor script at commit time and in continuous integration. The discipline lint refuses the two test shapes that have hurt this repo: one that reads or writes a live data path, and one that reaches a real pager without a stub in the same command.

## Every test, by directory

### `q-system/.q-system/scripts/` (57)

- `test-break-glass-audit.sh`: Regression test: the break-glass hatch may never open without a trace.
- `test-ripple.py`: Ripple system regression tests. Run automatically via `kipi check`.
- `test_autocapture_e2e.py`: End-to-end acceptance for memory auto-capture (issue autocapture-e2e-acceptance,
- `test_autocapture_wiring.py`: Reproducer-first tests for the design-partner-only wiring of memory auto-capture
- `test_blocked_claim_evidence_lint.py`: Reproducer + negative self-test for blocked-claim-evidence-lint.py (ASK-317).
- `test_capability_gate.py`: Paired test for capability-gate.py (prd-silent-absence-capability-gate).
- `test_client_output_evidence_gate.py`: Self-test for client-output-evidence-gate.py.
- `test_correction_outcome.py`: Reproducer-first tests for correction_outcome.py (issue autocapture-corrected-path,
- `test_dispatch_alias_reachability.py`: Reachability is a fact about a CHECKOUT, not a string match on two names (ASK-840).
- `test_dispatch_reachability.py`: SKIPPED is routine, UNREACHABLE is a fact nobody can act on from here (ASK-729).
- `test_enforced_claim_lint.py`: Tests for enforced-claim-lint.py (ASK-965).
- `test_evidence_ledger.py`: Self-test for evidence_ledger.py.
- `test_handoff_provenance_lint.py`: Self-test for handoff-provenance-lint.py.
- `test_instruction_budget_audit.py`: Tests for instruction-budget-audit.py count_lines (ASK-965).
- `test_instrument_lint.py`: Reproducer for instrument-lint.py (case-004 instrument discipline).
- `test_kb_graph_guard.py`: Tests for kb-graph-guard.py. Runnable directly or via pytest.
- `test_knowledge_supply.py`: Tests for knowledge_supply.py and knowledge-inject.py. Runnable via pytest.
- `test_launchd_health_check.py`: Regression tests for launchd-health-check.py (the silent-job-death watchdog).
- `test_launchd_intent_verify.py`: Regression tests for launchd-intent-verify.py (sp-2c7e5819).
- `test_lessons_index.py`: Tests for q-system/hooks/lessons-index.py (ASK-965, finding-12).
- `test_lessons_inject.py`: Self-test for lessons-inject.py.
- `test_linear_sync_comments.py`: Contract test for `linear-sync.py comments` -- the READ half of the Sana/codex
- `test_memory_autocapture.py`: Reproducer-first tests for memory_autocapture.py (issue autocapture-capture-core,
- `test_memory_confidence_surface.py`: Test for memory-confidence-surface.py (PRD prd-memory-confidence-provenance).
- `test_memory_confidence_validator.py`: Test for memory-confidence-validator.py (PRD prd-memory-confidence-provenance).
- `test_memory_confidence_wiring.py`: Wiring test for the memory-confidence feature (mcp-03).
- `test_memory_lint.py`: Self-test for memory-lint.py.
- `test_memory_outcomes.py`: Tests for memory_outcomes.py — the outcome event log + single-writer.
- `test_memory_reflect.py`: Tests for memory_reflect.py — the earned-trust scoring engine.
- `test_memory_scores_surface.py`: Tests for memory-scores-surface.py — the earned-trust recall surface.
- `test_merge_bypass_gate.py`: Self-test for merge-bypass-gate.py.
- `test_merge_bypass_gate_admin_forms.py`: Reproducer: `gh pr merge --admin=true` must be refused, not only bare `--admin`.
- `test_merge_bypass_gate_emits_deny.py`: A classified bypass must actually EMIT a deny. End-to-end, via stdin (ASK-1136).
- `test_merge_bypass_gate_global_flags.py`: Reproducer: a gh GLOBAL FLAG must not be able to smuggle a merge past the gate.
- `test_merge_bypass_gate_hidden_tool.py`: Reproducer: the PUSH side must refuse a hidden `git`, exactly as the merge side does.
- `test_merge_bypass_gate_wrappers.py`: Reproducer: a wrapper or a compact separator must not hide a merge or a push.
- `test_miyo_kb_hooks.py`: Tests for the Miyo KB hooks: miyo-session-pull.py and miyo-research-gate.py.
- `test_plan_lint.py`: Reproducer for plan-lint.py (ASK-136).
- `test_plugin_version_bump_check.py`: Test for plugin-version-bump-check.py (reproducer-first).
- `test_pr_restack_unknown.py`: Self-test: pr-restack.py must not silently skip a PR it could not classify.
- `test_pr_verify.py`: Self-test for pr_verify.py, the only writer of .prd-os/pr-receipts/.
- `test_prompt_only_enforcement_guard.py`: Self-test for prompt-only-enforcement-guard.py.
- `test_provenance_vocabulary.py`: Self-test for provenance_vocabulary.py, the ONE source both provenance
- `test_read_first_gate.py`: Self-test for read-first-gate.py.
- `test_review_tier.py`: Paired test for review-tier.py (deterministic review-tier classifier).
- `test_session_recall.py`: Reproducer-first tests for session_recall.py (issue autocapture-recall-artifact,
- `test_settings_template_sync_check.py`: Test for settings-template-sync-check.py (reproducer-first).
- `test_skill_hook_audit_local.py`: settings.local.json is not authoritative wiring (ASK-965, finding-13).
- `test_spillover_promote_selection.py`: The conveyor test: does what spillover-promote.py FILES get PICKED UP? (ASK-451)
- `test_spillover_ratchet.py`: Tests for spillover-ratchet.py (ASK-343).
- `test_system_manifest.py`: Self-test for system_manifest.py.
- `test_token_guard_commit_forms.py`: Paired test for token-guard.py's volume-ceiling commit exemption
- `test_token_guard_observation.py`: Paired test for token-guard.py's observation exemption (sp-ff7611cd) and
- `test_voice_lint_caps.py`: test_voice_lint_caps: the capitalization rule in voice-lint.py.
- `test_voice_stop_gate_drain_only.py`: The last post of a session surfaces its score (ASK-902, sp-08c34cf1).
- `test_voiceloop_migrate.py`: Tests for kipi-update-voiceloop-migrate.py and its call site (sp-8d55455a).
- `test_wiring_check.py`: Pins what `wiring-check.py` detects, and pins that detecting is ALL it does (ASK-132).

### `q-system/.q-system/scripts/test/` (129)

- `ask293-append-negation-repro.sh`: ASK-293 reproducer: append-negation against apply_claude_changes.py.
- `ask293-decision-evidence.sh`: ASK-293 decision evidence: BUILD the two candidate guards, then defeat them.
- `test-accept-rate-receipts.py`: Pairs with accept-rate.py load_receipts.
- `test-apply-claude-changes.sh`: Tests for apply-claude-changes: the safe path for landing .claude/ edits.
- `test-ask358-round3-mutation.sh`: THE NEGATIVE SELF-TESTS FOR PR #211 ROUND 3 (ASK-358). Two majors, two
- `test-ask842-dispatch-decision.sh`: Pairs with: instance-registry.json (the two rows ASK-842 decided) and
- `test-attempts-ledger.py`: Reproducer + acceptance criterion for the attempts-ledger lock (ASK-286).
- `test-audhd-output-eval.py`: Tests for audhd-output-eval.py (H2 output-quality harness).
- `test-auto-update-nudge.sh`: H5: auto-update.sh must be de-fanged (no subtree pull), nudge-only, and wired. Pairs with issue auto-update-nudge.
- `test-canonical-digest-real-values.py`: Prove canonical_digest actually READ a live canonical tree, by named value.
- `test-capability-gate-inert-spillover.py`: Reproducer + acceptance for the capability gate's declared_inert liveness check (ASK-345).
- `test-capability-gate-reap.sh`: Reproducer + acceptance criteria for the capability gate's test runner (ASK-190).
- `test-capability-map-wiring.py`: Wiring detection in capability-map-gen.py: what counts as "this engine is alive".
- `test-ci-redrive.sh`: Pairs with ci-redrive.py (ASK-295): red CI on an agent-opened PR is a dead end
- `test-claim-page-once-routing.sh`: Reproducer + acceptance criterion for how linear-worker.sh routes the ledger's
- `test-claude-write-path.sh`: test-claude-write-path.sh -- ASK-282, the .claude/ write path.
- `test-client-name-guard.py`: Paired test for client-name-guard.py (ASK-747).
- `test-consumer-parity-check.py`: consumer-parity-check: does it re-find the known defect, and can it be seen to fail?
- `test-containment-gitlink.py`: Pairs with containment-targets.py: a gitlink must not take the gate down.
- `test-control-file-propagate.sh`: Negative-first self-test for control-file-propagate.py (ASK-755).
- `test-converge-capout.sh`: Reproducer + acceptance criteria for ASK-871: a converge cap-out is invisible
- `test-converge-crossrepo-receipt.sh`: Pairs with receipt_tree() in converge.sh (ASK-821).
- `test-converge.sh`: Reproducer + acceptance criteria for the convergence driver (ASK-113).
- `test-dispatch-client-refusal-after-hold.sh`: THE GUARD THAT REPLACES THE HOLD (ASK-738 + ASK-741).
- `test-dispatch-liveness.sh`: Pairs with kipi-dispatch.sh: a dispatch that DIED must not report success.
- `test-dispatch-per-repo-concurrency.sh`: Pairs with the PER-REPO CONCURRENCY block in kipi-dispatch.sh (sp-e45251f7).
- `test-dispatch-pinned.sh`: Tests for kipi-dispatch-pinned.sh.
- `test-dispatch-stale-checkout.sh`: Reproducer for sp-c775b116: the dispatcher ran the founder's working tree with
- `test-dor-refuses-unroutable.py`: The DoR drafter refuses the two issue shapes a DoR cannot help (ASK-839).
- `test-enforced-claim-mutation-matrix.sh`: enforced-claim-mutation-matrix: one fabricated input per BLOCKING CONDITION,
- `test-findings-block-reader.sh`: Reproducer for sp-c0a9dac3: ONE reader of the machine-readable findings block.
- `test-firecrawl-scrape.sh`: H7: firecrawl scrape-to-file, OFFLINE (mock response). Pairs with issue firecrawl-scrape.
- `test-fleet-health-daily.py`: Pairs with fleet-health-daily.py.
- `test-gate-13b-scope.py`: Pins Gate 1.3b's gating scope (ASK-191).
- `test-gh-repo-scope-converge.sh`: Reproducer + acceptance for call site 2 of ASK-738: converge.sh resolves the
- `test-gh-repo-scope-reviewer.sh`: Reproducer + acceptance for call site 3 of ASK-738, the one that can approve
- `test-gh-repo-scope-worker.sh`: Reproducer + acceptance for call site 1 of ASK-738: linear-worker.sh's
- `test-install-plist.sh`: Pins install-plist.sh (ASK-191): every committed com.kipi.*.plist template
- `test-instance-automation-guard.sh`: Tests for instance-automation-guard.py (blocks scripts into an instance's q-system/ subtree).
- `test-instance-ownership-contract.py`: Executable contract tests for registry-derived updater ownership.
- `test-kipi-rollback-matrix.sh`: Rollback across updater failure phases. Pairs with issue fcu-rollback-matrix.
- `test-kipi-rollback.sh`: H3: kipi rollback -- safe revert of the last skeleton sync. Pairs with issue kipi-rollback-verb.
- `test-kipi-update-build-artifacts.sh`: A build artifact must not ride the plugin sync into 23 instances.
- `test-kipi-update-dry-final-state.sh`
- `test-kipi-update-hook-contract.sh`: A valid skeleton ships the propagation leak gate: kipi-update.sh is
- `test-kipi-update-leak-preflight.sh`: The chokepoint: a leaked fact must stop `kipi update` BEFORE any instance is
- `test-kipi-update-owned-deletion-guard.sh`: The q-system sync must REFUSE when --delete would remove instance-owned data.
- `test-kipi-update-plugin-excludes.sh`: A plugin-root .env is copied into all 23 instances and committed there.
- `test-kipi-update-preservation-failure.sh`: A valid skeleton ships the propagation leak gate: kipi-update.sh is
- `test-kipi-update-safety.sh`: H2+H4: kipi update must not destroy untracked (incl. gitignored) instance files,
- `test-kipi-update-source-provenance.sh`: The bytes fanned out to 23 instances must be the bytes that were reviewed.
- `test-kipi-update-system-state-commit.sh`: The carve-out that exists to PREVENT the dirty-tree refusal is what causes it.
- `test-kipi-update-unmanaged-instance.sh`: A registered instance that receives NOTHING must say so out loud.
- `test-lessons-daily-exit.sh`: Pins the exit contract of lessons-daily.sh (ASK-182).
- `test-lessons-distill.sh`: Tests for lessons-distill.py: gate publishes clean, scrubs client data, holds semantic flags,
- `test-lessons-doc-wiring.sh`: Keeps H0 docs/wiring in sync. Pairs with issue lessons-doc-wiring-sync.
- `test-lessons-propagation.sh`: Test: q-system/lessons/ propagates via kipi update (not excluded from the rsync sync).
- `test-lessons-push-guard.sh`: Test suite for the lessons + registry guards in kipi-push-upstream.sh.
- `test-lessons-scrub.sh`: Fail-closed tests for lessons_scrub.py (the client-data gate before autonomous publish).
- `test-lessons-validator.sh`: Negative-test suite for lessons-validator.py. Pairs with issue lessons-validator.
- `test-linear-claim.sh`: Reproducer + acceptance criterion for the agent claim-lock (ASK-113).
- `test-linear-create.py`: Reproducer + acceptance criterion for `linear-sync.py create` (ASK-113).
- `test-linear-dor-drafter-redrive.sh`: The redrive path: a `needs-scope` refusal comes BACK to the DoR drafter and is
- `test-linear-dor-failure-reporting.py`: Test paired with the linear-dor-drafter.py script: its failures reach Linear.
- `test-linear-issue-ref-check.sh`: Reproducer + regression suite for linear-issue-ref-check.py
- `test-linear-queue.sh`: Reproducer + regression suite for linear-queue.py (the capture half of the
- `test-linear-sync-idempotent.sh`: Reproducer + regression suite for linear-sync.py.
- `test-linear-triage.sh`: Pairs with linear-triage.py. Asserts the DETERMINISTIC slice only: the parts
- `test-linear-wiring.sh`: Wiring suite for the Linear capture path (ASK-113).
- `test-linear-worker-fetch.sh`: Reproducer + acceptance criterion for "the worker never fetches, and when the
- `test-linear-worker-parallel.sh`: Reproducer + acceptance criterion for the claim-lock serializing the whole
- `test-notify-exit-contract.sh`: ASK-636: the fleet alert path must report whether the alert was FILED.
- `test-notify-fixture-guard.sh`: Regression suite for slack-notify.sh's fixture-run guard.
- `test-notify-supplies-repo-path.sh`: ASK-839 review finding (PR #191, codex major): the alert writer's project
- `test-open-loops-heartbeat-exit.sh`: Pins the exit contract of open-loops-heartbeat.sh (ASK-184).
- `test-open-loops.sh`: AUDHD anti-drop: open-loops.py surfaces every parked item. Pairs with open-loops.json registry.
- `test-plist-drift.py`: Pairs with fleet-health-daily.py's `plist-drift` detector (ASK-860).
- `test-plugin-hook-ownership.sh`: Required check for issue lint-hook-ownership-dedupe (spillover sp-700047ff).
- `test-pr-review-root-guard.sh`: Pairs with the review-root guard in q-system/.q-system/scripts/pr-review-agent.sh.
- `test-prompt-only-enforcement-guard-stderr.sh`: Scar (2026-07-02, sp-cd530cc7): on block, the guard exited 2 but printed its
- `test-propagation-entrypoints.py`: Every path that copies generic content into an instance runs the same gate.
- `test-propagation-leak-baseline.py`: A baseline is only evidence if someone had to say why, one line at a time.
- `test-propagation-leak-gate.py`: Fingerprints for the propagation leak gate.
- `test-propagation-leak-sources.py`: What the gate must scan is what propagation actually copies.
- `test-quick-plan-rule-wired.sh`: ASK-136: .claude/rules/quick-plan.md carried an (ENFORCED) heading and named no
- `test-receipts-ledger-check.sh`: Pairs with receipts-ledger-check.py (the content gate on the one .jsonl that
- `test-repo-preflight.sh`: Reproducer for finding-8 (BLOCKER) and finding-9 of
- `test-review-artifact-repo-keyed.sh`: Reproducer + acceptance for ASK-738 criterion 3: review artifacts are keyed by
- `test-review-comment-body.sh`: Reproducer for sp-b418be32: a codex review is too large for a GitHub comment,
- `test-review-degraded-provenance.sh`: Reproducer for sp-8379cd52: the verdict record could not distinguish a review
- `test-review-dry-run-labelled.sh`: ASK-758: a dry run must SAY it is a dry run, at the moment a reader forms a
- `test-review-early-bail-ref.sh`: PR #265 codex major: an EARLY bail out of review_worktree left the stale
- `test-review-fallback-exact-sha.sh`: PR #265 codex major: the fallback tree search accepted a DESCENDANT worktree.
- `test-review-gate-no-fake-green.sh`: The review gate must not go green on a review that never ran (ASK-312).
- `test-review-invoker-provenance.sh`: Reproducer for sp-53aad86f: the verdict record could not distinguish a
- `test-review-plan-echo-gate.sh`: Reproducer for sp-df1a458f: a review that NEVER RAN must never fill the gate.
- `test-review-redrive-absent.py`: review-redrive must see a reviewer slot that was NEVER POSTED (sp-d87c5416).
- `test-review-redrive.sh`: Pairs with review-redrive.py (ASK-352): a PR whose REVIEWER refused has no
- `test-review-root-and-lock.sh`: PR #265 codex majors.
- `test-review-tree-guard.sh`: Reproducer for the tree-vs-PR-head guard in pr-review-agent.sh (ASK-221,
- `test-review-worktree-ref.sh`: review_worktree must refresh refs/remotes/pr/<N>, not only HEAD (sp-690ba60b).
- `test-reviewer-floor-workflow.sh`: reviewer-floor.yml must never RUN pr-controlled code while holding statuses:write.
- `test-reviewer-floor.sh`: The reviewer floor posts RED on absence and NEVER touches a real verdict (ASK-361).
- `test-runtime-plugin-freshness-wired.sh`: Pairs with detect_stale_runtime_plugins in
- `test-runtime-plugin-freshness.sh`: Pairs with q-system/.q-system/scripts/runtime-plugin-freshness.py.
- `test-script-stable-under-self-edit.sh`: Reproducer + acceptance for ASK-351: a long-running bash driver corrupts itself
- `test-settings-merge.sh`: Required check for kipi-settings-merge.py (extracted from kipi-update.sh).
- `test-severity-floor.sh`: Reproducer + acceptance criteria for the review severity floor (ASK-113).
- `test-skill-trigger-eval.sh`: H1: skill-trigger eval harness, OFFLINE (mocks claude -p). Pairs with issue skill-trigger-eval.
- `test-social-reaction-gate-rule-wired.sh`: ASK-138: .claude/rules/social-reaction-gate.md carried an (ENFORCED) heading and named
- `test-styles-csv-width.sh`: Gate for issue styles-csv-row77-width (spillover sp-42f164c5):
- `test-terminal-states.sh`: NEVER LET THIS TEST REACH THE FOUNDER PHONE (ASK-729).
- `test-token-discipline-rule-wired.sh`: ASK-139: .claude/rules/token-discipline.md carried three ENFORCED-shaped claims and
- `test-token-guard-hook-behavior.sh`: Required checks for the token-guard hook fixes (hooks review 2026-07-02).
- `test-token-guard-template-wiring.sh`: Required check for issue token-guard-template-blocking (spillover sp-dd731488).
- `test-update-preservation-manifest.py`: Black-box tests for the registry-derived preservation manifest.
- `test-updater-issue-sequence.py`: Order gate for the shared fail-closed updater work.
- `test-updater-receipt-contract.py`: Dependency-free producer and consumer tests for updater receipts.
- `test-verdict-statement-shape.sh`: Pairs with extract_verdict() in pr-verdict-lib.sh (ASK-356).
- `test-verdict-usability.sh`: Pairs with pr-review-agent.sh's verdict-record writer (sp-2a832233, ASK-352).
- `test-voice-enforcement-rule-wired.sh`: ASK-140: .claude/rules/voice-enforcement.md says ENFORCED, so it has to name the
- `test-voice-lint-topups.sh`: H8+H10: voice-lint emphasis-opener detector + voice-substance >=2-anchor fix. Pairs with issue voice-lint-topups.
- `test-voice-lint-warn-detectors.sh`: H8b+H9: emphasis-opener + rhetorical-QA WARN detectors. Pairs with issue voice-lint-warn-detectors.
- `test-worker-project-scope.sh`: Reproducer + regression suite for the worker's READY filter (ASK-275).
- `test-worker-refusal.sh`: The refusal path: Sana judges an issue unexecutable, and that judgment sticks
- `test-zero-safe-count-idiom.sh`: `grep -c ... \|\| echo 0` is not a zero-safe count. Pins the corrected idiom
- `test_linear_alert_triage.py`: Pins the ONE property linear-alert-triage.py exists to create: after a
- `test_voiceloop_band_lint.py`: Pins the DETECTED claim in `.claude/rules/voice-loop-anywhere.md`.
- `verify-alert-wiring.sh`: ASK-636 wiring receipt. Checks the alert path end to end across every LIVE

### `q-system/.q-system/scripts/test/fixtures/` (1)

- `capability-map-gen.d20f412.py`: Generate a CAPABILITY-MAP.json for a kipi instance repo by structural recon.

### `q-system/.q-system/scripts/tests/` (1)

- `test-stat-verify.py`: End-to-end tests for stat-verify.py. Covers hook-mode payloads, JSON content

### `q-system/.q-system/` (2)

- `test_token_guard_runtime.py`: Test the token-guard runtime guard (scar sp-28bf75a4).
- `test_verify_adversarial.sh`: Adversarial test for verify.sh: does it actually BLOCK, or only pass tests?

### `q-system/.q-system/tests/fixtures/` (1)

- `destructive-op-deny.reference.sh`: destructive-op-deny.sh - PreToolUse hook that denies destructive

### `q-system/.q-system/tests/separation/` (15)

- `test_baseline_receipt.py`
- `test_containment_claims.py`
- `test_containment_export.py`
- `test_containment_rollback.py`
- `test_containment_scoped_checks.py`
- `test_containment_sequence.py`
- `test_containment_targets.py`
- `test_fact_grammar.py`
- `test_instance_fact_inventory.py`
- `test_inventory_redaction.py`
- `test_public_history_contract.py`
- `test_semantic_client_leakage.py`
- `test_template_restoration.py`
- `test_update_propagation.py`: Updater final states must not give an injected instance fact a free ride.
- `test_updater_dependency_receipt.py`

### `q-system/.q-system/tests/` (46)

- `test_alert_to_linear.py`: Pins alert-to-linear.py: the flood collapses, and a test can never file live.
- `test_alert_to_linear_race.py`: Two concurrent alert writers must open ONE permanent Linear ticket, not two.
- `test_auto_commit.py`: The auto-commit Stop hook (ASK-498).
- `test_browser_session.py`: The six hard constraints of the persistent-browsing capability, as checks.
- `test_browser_session_states.py`: Six probe states, per-surface alerting, and the two decisions that are code.
- `test_capability_gate_inert_closure.py`: The inert-engine check's wired-closure must cross the plugin boundary.
- `test_capmap_scratch_and_mention.py`: A committed scratch tree is not a capability, and a mention is not a test.
- `test_claude_path_write_guard.py`: claude-path-write-guard must block writes and nothing else.
- `test_consulting_board.py`: The consulting morning board: mirror, never a second derivation (2026-09-03).
- `test_decision_corpus_cost.py`: RED FIRST. Issue mbl-two-measurements (plan 2h, Codex finding-16). The cost
- `test_draft_vs_sent.py`: RED FIRST. Issue mbl-draft-sent-pairing (prd-morning-brief-learns, Codex
- `test_fable_cap_page_deleted.py`: Reproducer + regression pin for ASK-504: the escalation-cap page.
- `test_fable_escalation.py`: Tests for the Fable escalation branch on token-guard's stuck blocks (ASK-311).
- `test_gitignore_block.py`: The skeleton's never-commit stanza must reach every instance (sp-097d2e23).
- `test_grounding_manifest_health.py`: ASK-533: the grounding guard's coverage check must not fail open silently.
- `test_hook_envelope_audit.py`: Pins hook_envelope_audit.py AND the fleet-shared hooks it audits.
- `test_instance_automation_guard.py`: instance-automation-guard's instance-owned carve-out, held to the truth.
- `test_lessons_daily_label.py`: RED FIRST. Issue lr-lessons-label-collision (prd-lessons-rail-and-up-rail).
- `test_lessons_daily_streak.py`: RED FIRST. Issue lr-propagation-streak-escalation (prd-lessons-rail-and-up-rail,
- `test_lessons_drift_report.py`: RED FIRST. Issue lr-drift-reporter (prd-lessons-rail-and-up-rail, plan 4c) and
- `test_lessons_notion_sync.py`: RED FIRST. lessons_notion_sync.py mirrors the corpus into the founder's
- `test_lessons_recall_corpus.py`: RED FIRST. Issue lr-recall-names-its-corpus (prd-lessons-rail-and-up-rail,
- `test_linear_filer_label_lint.py`: Tests for linear-filer-label-lint.py (ASK-882).
- `test_linear_triage_health.py`: Pins linear-triage-health.py and the needs-triage marking in alert-to-linear.py.
- `test_loops_path.py`: loops_path: missing must never render as empty.
- `test_md_prune_budgets.py`: What md-prune is allowed to archive.
- `test_merge_bypass_gate_fail_open.py`: merge-bypass-gate must DENY when it cannot classify (ASK-1179).
- `test_morning_brief.py`: Engine test for the morning brief (ASK-1178).
- `test_notion_board.py`: RED FIRST. Issue mbl-board-section-bounded (prd-morning-brief-learns,
- `test_off_switches.py`: RED FIRST. Issue mbl-off-switches (prd-morning-brief-learns, Codex
- `test_permission_ask_counter.py`: RED FIRST. Issue mbl-two-measurements (plan 2i). The counter is advisory and
- `test_promotion_receipt.py`: RED FIRST. The promotion path (prd-lessons-rail-and-up-rail, Phase 4), one
- `test_reddit_read.py`: The Reddit read lane: an HTTP client with an honest User-Agent.
- `test_roadmap_scope.py`: RED FIRST. Issue mbl-roadmap-scope-classifier (prd-morning-brief-learns,
- `test_roadmap_scope_suite.py`: RED FIRST. Issue mbl-roadmap-scope-paraphrase-suite (Codex finding-12 on
- `test_route_overrides_to_learn.py`: RED FIRST. Issue mbl-weekly-improve-runner (prd-morning-brief-learns, Codex
- `test_skill_changelog.py`: RED FIRST. Issue mbl-changelog-convention (prd-morning-brief-learns,
- `test_token_guard.py`: Black-box tests for the token-guard circuit breaker (sp0-guard-actor-scope).
- `test_token_guard_cache_race.py`: The guard cache must survive parallel hook fires (sp-016776e6).
- `test_trigger_inventory.py`: RED FIRST. Issue lr-trigger-inventory (prd-lessons-rail-and-up-rail, plan 4d,
- `test_unknown_terms.py`: RED FIRST. Issue mbl-unknown-term-detector (prd-morning-brief-learns,
- `test_voice_stop_gate_channel_registry.py`: The skeleton Stop-gate routes a channel through an OPTIONAL instance registry.
- `test_voice_stop_gate_not_checked.py`: A missing lint must report NOT CHECKED, never a pass.
- `test_web_read_tools.py`: The agent-facing surface for the two read lanes.
- `test_weekly_improve.py`: RED FIRST. Issue mbl-friction-artifact (prd-morning-brief-learns, Codex
- `test_wip_check.py`: An untracked file the skeleton itself wrote is exhaust, not work (sp-940bcf47).

### `q-system/hooks/test/` (1)

- `test-lessons-index.sh`: Test suite for lessons-index.py (SessionStart consumer). Pairs with issue lessons-consumer-hook.

### `scripts/` (2)

- `test_persona_reorg.py`: Unit tests for persona-reorg.py's hardened rewriter + single-source map.
- `test_persona_reorg_detach.py`: Integration tests for persona-reorg.py's detach/promote-to-standalone path.

### `test-kipi-update-armed-marker-unblocks.sh/` (1)

- `test-kipi-update-armed-marker-unblocks.sh`: Pairs with kipi-update.sh SYSTEM_NEVER_COMMIT / the one-time untrack migration

### `test-kipi-update-bash32-empty-array.sh/` (1)

- `test-kipi-update-bash32-empty-array.sh`: Regression test for ASK-607: kipi-update.sh must survive an EMPTY bash array

### `test-kipi-update-cache-exclusion.sh/` (1)

- `test-kipi-update-cache-exclusion.sh`: sp-f6733ee3: the dry-run model must not strip a TRACKED file, and must still

### `test-kipi-update-config-commit-unwind.sh/` (1)

- `test-kipi-update-config-commit-unwind.sh`: The ASK-797 unwind on the CONFIG-SYNC commit half must leave a clean index.

### `test-kipi-update-dataloss-guards.sh/` (1)

- `test-kipi-update-dataloss-guards.sh`: The two ASK-606 data-loss notes I refused to close on a code read.

### `test-kipi-update-dirty-guard-scope.sh/` (1)

- `test-kipi-update-dirty-guard-scope.sh`: ASK-609: the dirty-tree guard must block on dirt the sync CAN write and must

### `test-kipi-update-dry-tagging.sh/` (1)

- `test-kipi-update-dry-tagging.sh`: sp-a4a933ad: a dry run's output must be impossible to mistake for a real one.

### `test-kipi-update-never-commit-coverage.sh/` (1)

- `test-kipi-update-never-commit-coverage.sh`: Pairs with kipi-update.sh SYSTEM_NEVER_COMMIT (ASK-797).

### `test-kipi-update-preserve-integration.sh/` (1)

- `test-kipi-update-preserve-integration.sh`: End-to-end proof that kipi-update.sh preserves instance-only files.

### `test-kipi-update-preserve-scan.sh/` (1)

- `test-kipi-update-preserve-scan.sh`: Regression test for kipi-update-preserve-scan.py (the warn+preserve guard).

### `test-kipi-update-restore-recovers.sh/` (1)

- `test-kipi-update-restore-recovers.sh`: sp-20c967ed, the half my dry-run fixture could not reach.

### `test-slack-notify-label.sh/` (1)

- `test-slack-notify-label.sh`: ASK-604: the Slack label prefix and the message body must name the SAME project.

### `test_destructive_op_deny_anchor.py/` (1)

- `test_destructive_op_deny_anchor.py`: sp-9166e58a: `kipi update` is the one FLEET_DENY pattern that is not anchored.

### `test_fleet_unblock.py/` (1)

- `test_fleet_unblock.py`: fleet-unblock.py acts only on what it can attribute, and refuses the rest.

## Scars

- Two green-but-wrong tests shipped in one day, both caught by mutation rather than review (memory: fixtures come from producers). Result: the mutation step above.
- A mutation harness once reported perfect survival because it ran no tests. Result: a test is trusted only after it has been seen red.
- 2026-08-01: a test reached the real alert script and paged the founder twice while reporting green. Result: the pager-stub rule in `fable-discipline-lint.py`.

## Retired

- Test files under `agent-pipeline/` and the bus verifiers' tests exercise the retired morning pipeline (page 14); they still run and still pass, which is why they are listed rather than deleted.
