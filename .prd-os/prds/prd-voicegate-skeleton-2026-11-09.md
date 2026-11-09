---
id: prd-voicegate-skeleton-2026-11-09
title: Voicegate Skeleton
status: approved
created_at: 2026-11-09T18:04:43Z
updated_at: 2026-11-09T18:24:19Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-voicegate-skeleton-2026-11-09-findings.jsonl
codex_reviewed_at: 2026-11-09T18:13:58Z
reviewed_by: claude-review
---

# Voicegate Skeleton

Skeleton half of ASK-3834 (the voiceloop-in-code plan, children of ASK-3815). The consulting half is its own PRD in the consulting repo. Source plan: consulting `q-system/output/plans/voiceloop-enforced-in-code-resume-2026-11-07.md` (sections from line 130 win) and the execution plan approved 2026-11-09. Rulings: consulting `q-consult/canonical/decisions.md` RULE-2026-11-07-A to G, RULE-2026-11-09-A.

Revised 2026-11-09 after the claude-review round (21 findings). Each finding's disposition and reason is on its row in the findings file.

## Problem

Measured on kipi-system origin/main 976993a7, 2026-11-09:

- The consulting gate-draft hook fails open. It is wired PostToolUse `if test -f X; then python3 X; fi` (consulting origin `.claude/settings.json:305`), so deleting `automation/gate_draft_hook.py` passes every draft. Instance mode in `apply_claude_changes.py` adds entries only (`:183`); `replace` is limited to rule text (`:189`, refused outside `.claude/rules/*.md` at `:505-533`), so an instance cannot rewrite that command. It can add a second entry beside it.
- Whether that second entry survives `kipi update` depends on its text. Measured with `kipi-settings-merge.py merge_settings` on a fixture: `test -f "$CLAUDE_PROJECT_DIR/automation/gate_draft_hook.py" || { echo "gate_draft_hook.py missing: ..." >&2; exit 2; }` keys as `{path:automation/gate_draft_hook.py, gate_draft_hook.py}` and is kept beside the real hook, report empty. `[ -f "$CLAUDE_PROJECT_DIR/automation/gate_draft_hook.py" ] || exit 2` keys as `{path:automation/gate_draft_hook.py}`, the same key as the real hook, so the merge drops it. Nothing pins which shape survives.
- `voiceloop-band-lint.py:74` `CHANNEL_BY_PATH` maps x and threads apart and passes that channel to `voiceloop review` (`:111`). RULE-2026-11-07-A makes them one `short` lane, defined in an instance manifest (`q-consult/config/voice-check.json`, built by consulting V1). The engine accepts any channel string and applies short-form rules only to `x` and `threads` (voice-loop `x_format.SHORT_FORM_CHANNELS`), so the lane name can never reach the engine.
- In-file skip markers are the only suppression path: `voice-lint-skip` (`voice-lint.py:80`, `:875`; reused by `voice-substance-lint.py:46`, `:142`) and `voiceloop-band-lint-skip` (`voiceloop-band-lint.py:57`, `:209`). No owner, no reason, no expiry. `voice-stop-gate.py` honours none.
- `linear-worker.sh:12` says "It will not MERGE. It opens a PR and stops. Merging is the founder's." The same file defines `arm_automerge` (`:1985`) and calls it (`:2792`, `:3915`).
- `lessons-validator.py` knows no `held_by` or `prose_accepted`, so a lesson can state a must-rule with nothing holding it. It is a PostToolUse Edit/Write hook; the lessons that land are written by `lessons-distill.py`, `lessons-daily.sh` and `lesson-note.sh`, which the hook never sees.

## Goals

- K8: the band lint reads the instance `voice-check.json` when present. The lane only chooses the channel the engine receives, which stays `x` or `threads`. Absent manifest: today's table result. Malformed manifest: one reported line, then the table.
- K1a: pin the instance existence-guard contract. A PostToolUse entry `test -f "$CLAUDE_PROJECT_DIR/<p>" || { echo "<basename> missing: the gate cannot run" >&2; exit 2; }` added beside the gate's own hook is accepted by instance-mode apply and kept by `kipi-settings-merge.py` across two updates. No new apply op.
- K7: one reader module for a per-instance suppression file with bounded rows. The three voice lints call it. In an instance that has the file, in-file voice markers stop skipping.
- K5: `lessons-validator.py` requires a linked `held_by` or a dated `prose_accepted` on new and changed lessons, and every lesson writer produces one.
- K2: `linear-worker.sh:12` names the merge mechanism the file runs, pinned by a test.

## Non-goals

- Anything in the consulting repo (its PRD covers V0 to V10 and K1b). K1b writes the guard proposal and owns the red test that deleting `automation/gate_draft_hook.py` refuses the next draft.
- The fail-closed census for an instance hook. `test_hook_fail_closed_population.py` reads only the skeleton's two settings files by design; the instance gate's proof is consulting K1b's delete-the-file test.
- The skeleton template's voice-lint wrappers (`settings-template.json:144`, `:305`, `:310`, `:457`) and the crash-exits-1 class in those lints. Deferred on finding-4 to its own ticket: a different fix (template plus crash handling) with fleet blast radius.
- K10 worker ledger fields. Deferred on finding-16: RULE-2026-11-07-F reads pickup-to-merge from GitHub on day one, so the fields would be write-only. They land with the consulting V10 reader that names them.
- K6 proof writers (evidence ledger, morning step log, design-chain receipts). Deferred on finding-18 to one ticket listing the three; the plan orders K6 after V9.
- The lessons-injector replay (4 incident prompts, 5 target lessons, 0 of 5 today). Deferred on finding-14: no injector change has a design yet, and a test pinning 0 of 5 would pin the defect.
- The shell-header claim lint (folded into ASK-3818, not built here).
- K4's shared receipt module: both `runtime_receipt.py` copies are already blob b8c2d99e, pinned by the byte-identity assertion at `plugins/prd-os/tests/test_runtime_receipt_gate.py:71`. K4 closes citing that test.
- chief's email gate and investigations' `client_report.py`: filed in their own repos.
- Files owned by open PRs #701, #699, #698, #697, #670, #668 until each merges or closes. (#695 merged 2026-11-09.)

## Proposed approach

One issue per spec, one PR each, in this order. Before each spec starts, `gh pr view <n> --json files` for every open PR; a spec whose allowed_files overlap an open PR waits for it.

1. `vg-k8-band-lint-manifest`. Waits on nothing (no open PR holds its files).
2. `vg-k1a-guard-contract`. Waits on nothing.
3. `vg-k7-suppression-file`. After spec 1 (both edit `voiceloop-band-lint.py`). Before consulting V6.
4. `vg-k5-lesson-holder`. After #699 merges or closes (it adds lesson files the new writer contract must count).
5. `vg-k2-worker-header`. After #701 and #668 merge or close (both edit `linear-worker.sh`).

Every spec: red test first, then the change, `issue-verify`, one `issue-review` round, closeout, PR, merge by `gh pr merge --auto --squash <url>`.

Reaching consulting (Skeptic A1): a skeleton change protects consulting only once the fleet sync puts it on consulting origin/main (RULE-2026-11-09-A). The check cannot be a required_check here, because it can only pass after this repo merges and the sync lands. It is the entry precondition of the consulting spec that depends on each one: K1b on spec 2, V1 on spec 1, V6 on spec 3. That spec compares the merged file's blob on consulting origin/main with kipi-system origin/main before it starts.

### Shared discovery rule (K8 and K7)

Instance root: `$CLAUDE_PROJECT_DIR` when set, else the git toplevel of the draft. Instance content dir: resolved by the existing `instance_q_dir` resolver in `q-system/.q-system/scripts/evidence_ledger.py` (registry first, then the single root-level `q-*` dir other than `q-system`; ambiguity reported). Files: `<root>/<q_dir>/config/voice-check.json` and `<root>/<q_dir>/config/voice-suppressions.json`. No env var: hooks and launchd jobs see different environments.

### K8 manifest contract (what the skeleton reads)

`surfaces.<surface>.lane` and `lanes.<lane>.engine_channel`. `engine_channel` must be a channel the band lint's table already emits. Consulting V1 writes the rest of the file; the skeleton reads only these two keys.

### K7 row contract

Each row: `path` (exact repo-relative path; no glob characters, no `..`, not absolute), `reason` (non-empty), `owner` (from a closed set in the reader module), `created` and `expires` (UTC dates, `YYYY-MM-DD`). A row skips while today in UTC is before `expires`; on the `expires` date it no longer skips. `expires` is at most 30 days after `created`. An unreadable file or an invalid row suppresses nothing and is reported by name; the reader never raises, so a lint never exits 1 on a bad row. Every skip prints the row's owner, reason and expiry.

## Alternatives considered

- **A harden op in the apply engine that rewrites a hook command to fail closed (the original K1a).** Rejected (finding-1, finding-5). It needs a ratchet exemption, which is a sanctioned way to make a hook string vanish, and a parser for the abuse cases finding-1 lists (path swap, event or matcher change, timeout drop, a trailing `exit 0` or `|| true`). The additive guard needs no new op, the ratchet sees only growth, and its exit code is an explicit `exit 2`, not the interpreter's missing-file code.
- **Make consulting's lints read its manifest by editing the skeleton copy inside consulting.** Rejected: `kipi update` overwrites instance edits under `q-system/` (RULE-2026-06-30-A).
- **Delete the two `runtime_receipt.py` copies for one shared module.** Rejected: plugins run alone from the marketplace copy and a cross-plugin import falls back silently (`work_item_age.py` documents it).
- **Pass `short` to the engine.** Rejected (finding-6): the engine defaults unknown channels to x rules and applies short-form length rules only to `x` and `threads`.

## Scenarios

- **An instance guards its voice hook.** Consulting K1b applies a proposal that inserts the guard entry beside the gate-draft hook. With `automation/gate_draft_hook.py` deleted, the next draft write gets exit 2 and the message on stderr. The write itself already happened (PostToolUse), so the edit that restores the file is never blocked. Undo for a misfire: restore the file.
- **A band lint run on an x draft.** With a manifest mapping surface x to lane `short` with `engine_channel: threads`, the engine runs `review --channel threads`. Without a manifest, `review --channel x`, unchanged.
- **A suppression expires.** On its `expires` date the row stops skipping and the lint reports the path.

## Resolved decisions

- **K1 shape: additive guard, not a harden op.** Reason: above. The guard applies to PostToolUse only. The lesson `a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too.md` stays right for hooks that run before the action; spec 2 adds that limit to the lesson.
- **K7 markers.** In an instance that has the suppression file, in-file voice markers stop skipping and the lint says so. Instances without the file keep markers. That is the switch consulting V6 flips by creating the file, and it keeps the bypass surface from growing where the file is adopted.
- **K4.** No PR. Built and pinned (see Non-goals).
- **K2 lint half.** ASK-3818 owns it. One claim lint, not two.
- **Blind judge skipped in triage.** LEAN MODE allows no new model review pass. The judgment receipt gate does not require a judge prediction; each receipt records it as absent.

## Risks and rollback

- K7 and K8 change lints that ship to every instance. Both keep today's behaviour when the instance file is absent; the tests pin that.
- K5 changes the lesson writers the nightly and weekly jobs run. Rollback: revert the PR; a writer that fails the validator refuses that lesson and reports it, it does not stop the job.
- K2 edits `linear-worker.sh`, the fleet's worker, comment only. It waits for #701 and #668.

## Open questions

- None blocking.

## Persona Review

The `/prd-personas` command refused on its Phase 0 gate (`prd-personas-baseline.md` has no `phase_0_kill_criterion: failed` line), so this is the template scaffold. Answered by Sana: the founder ruled on 2026-11-07 and 2026-11-09 that engineering follow-ups go to Sana, not to him.

### Skeptic

Q1: What is the strongest argument against doing this?
A1: These are fleet-wide tools changed to serve one instance. And a skeleton change does not reliably reach instance origins: consulting's origin/main missed the whole prd-os overhaul until ASK-4199 (RULE-2026-11-09-A). Answered in Proposed approach: each dependent consulting spec checks the blob on consulting origin/main before it starts.

Q2: What is the smallest experiment that would disprove the thesis?
A2: For K1: delete `automation/gate_draft_hook.py` in a temp copy of consulting and write a dated draft that names a price. If that draft is refused today, the guard is not needed (consulting K1b's red test). For K8: run the band lint on one x draft with and without a manifest. If the engine argv is the same, K8 adds nothing (spec 1's red test).

Q3: What is the cheapest non-build alternative?
A3: Hand-edit consulting's `settings.json`. Measured 2026-11-09: the integrity tripwire reverts unsanctioned `.claude/` edits in the running checkout, and RULE-2026-11-06-A rules out review discipline as the holder.

## Issues

```json
[
  {
    "id": "vg-k8-band-lint-manifest",
    "finding_id": "finding-6",
    "title": "Band lint reads the instance voice-check.json; the engine still gets x or threads",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/voiceloop-band-lint.py",
      "q-system/.q-system/scripts/test/test_voiceloop_band_lint.py",
      "q-system/.q-system/scripts/test/fixtures/voice-check/*"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/scripts/test/test_voiceloop_band_lint.py"
    ],
    "bypass_exempt": "The band lint is DETECTED and exits 0 on every path by contract, so there is no gate to bypass. The red test pins the channel the engine receives.",
    "acceptance": "Discovery and manifest contract as in the PRD sections 'Shared discovery rule' and 'K8 manifest contract'. The instance_q_dir is resolved by importing the resolver in evidence_ledger.py, not by a second copy.",
    "deliverables": [
      "Red first: with a fixture manifest mapping surface x to lane short with engine_channel threads, an x draft runs review with channel threads (today it runs channel x)",
      "The engine never receives a lane name: a test asserts the argv channel is one the table emits, and with the voiceloop package installed an over-length x draft still reports its length row",
      "No manifest: the table result is unchanged (pinned)",
      "Malformed or unreadable manifest, or an engine_channel outside the table: one reported line naming the file and reason, then the table (tested)",
      "Manifest found by the shared discovery rule: CLAUDE_PROJECT_DIR else git toplevel, instance_q_dir from the evidence_ledger resolver"
    ]
  },
  {
    "id": "vg-k1a-guard-contract",
    "finding_id": "finding-5",
    "title": "Pin the instance existence-guard contract through apply and the settings merge",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-settings-merge.sh",
      "q-system/.q-system/scripts/test/test-apply-claude-changes.sh",
      "kipi-settings-merge.py",
      "q-system/lessons/a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too.md"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-settings-merge.sh",
      "bash q-system/.q-system/scripts/test/test-apply-claude-changes.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-settings-merge.sh",
    "acceptance": "The guard shape is: test -f \"$CLAUDE_PROJECT_DIR/<p>\" || { echo \"<basename> missing: the gate cannot run\" >&2; exit 2; } in the same PostToolUse event and matcher as the gate's own hook. No new apply op and no ratchet exemption. kipi-settings-merge.py may gain a why-comment at hook_key naming this contract; its behaviour does not change unless the tests show the guard is dropped.",
    "deliverables": [
      "Merge test: the guard beside an if-test-f hook for the same instance script survives merge_settings twice with no DROPPED line",
      "Negative self-test: the bare [ -f X ] || exit 2 form keys like the real hook and is dropped with a DROPPED line, proving the test sees a drop",
      "Apply test: an instance-mode proposal inserting the guard into a temp instance settings.json applies, ratchet growth only",
      "Shell test: on a temp tree the guard exits 2 with its message on stderr when the script is missing and exits 0 when present",
      "The lesson on fail-closed hooks gains its limit: the no-op existence guard is for hooks that run before the action; a PostToolUse gate uses the separate exit-2 guard"
    ]
  },
  {
    "id": "vg-k7-suppression-file",
    "finding_id": "finding-8",
    "title": "One bounded per-instance voice suppression file, read by every voice marker reader",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/voice_suppressions.py",
      "q-system/.q-system/scripts/voice-lint.py",
      "q-system/.q-system/scripts/voice-substance-lint.py",
      "q-system/.q-system/scripts/voiceloop-band-lint.py",
      "q-system/.q-system/scripts/test/test_voice_suppressions.py",
      "q-system/.q-system/scripts/test/test_voiceloop_band_lint.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test_voice_suppressions.py.json"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/scripts/test/test_voice_suppressions.py",
      "python3 -m pytest -q q-system/.q-system/scripts/test/test_voiceloop_band_lint.py"
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test_voice_suppressions.py",
    "acceptance": "Row contract and discovery as in the PRD sections 'K7 row contract' and 'Shared discovery rule'. voice_suppressions.py is the single reader; the lints never parse the file themselves. Also run every existing test that imports or shells voice-lint.py or voice-substance-lint.py, found by grep at build time.",
    "deliverables": [
      "Red first: a file-listed path is skipped by voice-lint.py; an expired row does not skip",
      "A bad file or row suppresses nothing, is reported by name and never exits 1: malformed JSON, missing owner, missing reason, bad date, expires equal to today, expires more than 30 days after created, a glob path, an absolute path",
      "voice-lint.py, voice-substance-lint.py and voiceloop-band-lint.py call the reader; every skip prints owner, reason and expiry",
      "In an instance that has the file, in-file voice markers no longer skip and the lint says so; without the file, markers behave as today",
      "Census test: every script under q-system/.q-system/scripts that defines a voice skip marker imports the reader"
    ]
  },
  {
    "id": "vg-k5-lesson-holder",
    "finding_id": "finding-12",
    "title": "Lessons carry a linked held_by or a dated prose_accepted, from every writer",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/lessons-validator.py",
      "q-system/.q-system/scripts/lessons-distill.py",
      "q-system/.q-system/scripts/lessons-daily.sh",
      "q-system/.q-system/scripts/lesson-note.sh",
      "q-system/lessons/README.md",
      "q-system/.q-system/scripts/test/test_lessons_validator_holder.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test_lessons_validator_holder.py.json"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/scripts/test/test_lessons_validator_holder.py"
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/scripts/test/test_lessons_validator_holder.py",
    "acceptance": "held_by: a repo-relative path that exists, is a hook, script or test file, and contains the lesson id (the same linkage rule_gate.py enforces for RULE-2026-11-08-CODE). prose_accepted: a reason and a YYYY-MM-DD date. Required on new and changed lessons; lessons already on origin/main without either are counted as debt and printed, not refused.",
    "deliverables": [
      "Red first: a new lesson with neither field is refused",
      "held_by naming a missing file is refused; held_by naming a file that lacks the lesson id is refused; held_by as an absolute path is refused",
      "The token denylist runs over every new field value, not only the title",
      "lessons-distill.py, lessons-daily.sh and lesson-note.sh each emit a valid field (an auto-distilled lesson gets prose_accepted with its reason and date) or run the validator; a test drives each writer on a fixture",
      "Existing lessons without either field are counted as debt by a printed number"
    ]
  },
  {
    "id": "vg-k2-worker-header",
    "finding_id": "finding-20",
    "title": "linear-worker.sh header names the merge it runs",
    "priority": "p2",
    "allowed_files": [
      "q-system/.q-system/scripts/linear-worker.sh",
      "q-system/.q-system/scripts/test/test-linear-worker-header.sh",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test-linear-worker-header.sh.json"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-linear-worker-header.sh"
    ],
    "bypass_exempt": "Comment edit in the worker header; no gate or data path to bypass. The test pins the comment against the code.",
    "acceptance": "Header comment only; no behaviour change in linear-worker.sh.",
    "deliverables": [
      "Red first: a test that the header merge sentence names a function defined in the file and does not say merging is the founder's (red on today's line 12)",
      "Line 12 names arm_automerge, the reviewer verdict it waits for, and that merging is Sana's"
    ]
  }
]
```
