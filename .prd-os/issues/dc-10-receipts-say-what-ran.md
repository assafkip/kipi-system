---
id: dc-10-receipts-say-what-ran
title: Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_receipts.py
  - q-system/.q-system/scripts/test/test_dc_served_round.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_receipts.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_receipts.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-1 at=2026-09-18T20:21:26Z -->

# Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

seal writes a stages list per page (floor, vision, craft, gap, impeccable, readers, checks, engines) with each producer's output sha. sealed_and_unedited() accepts a receipt with a stages record, or one whose receipts.json has a git commit dated before the coded cutover; status and the hook block message print the stages. Negative control: RCA round B (hand-typed receipt, uncommitted) reads OPEN. Population check: every sealed round committed before the cutover still reads COMPLETE. ADDED 2026-09-18 by Sana's decision on dc-02's adversarial finding-6 (a gate copy beside stand-ins seals a real round and its receipt is indistinguishable): Each stage record names the producer's repo-relative path and the sha256 of the file that ran; a stage is honored only when that sha matches the file at that path now or appears in git history for that path, so stand-ins run from a copied directory are refused, and a test proves a gate or producer upgrade leaves every previously sealed round COMPLETE. ADDED 2026-09-18 by Sana's disposition of dc-02 finding-11 (the no-override test is a review aid, evaded two rounds running): The stage record also names the gate file's own repo-relative path and the sha256 of the file that ran, honored under the same rule (matches the file at that path now, or appears in git history for that path), so a modified or copied gate is refused like a copied producer. ADDED 2026-09-18 by Sana's decision on dc-03 finding-10 (served-bytes proof covered the HTML only, so a swapped shared.css left every sha matching while an honest re-measure FAILED): `sealed_and_unedited()` also recomputes the round's asset digest recorded by seal and refuses the round when it differs, and a test proves a subresource swap after seal flips the round from COMPLETE to OPEN. ADDED 2026-09-18 by Sana's disposition of ASK-1808 adversarial finding-7: the digest `sealed_and_unedited()` recomputes excludes only the files a seal itself writes (`standard.json`, `checks/gap.json`, `receipts.json`), not the chain records, so an edit to `brief.md`, `craft-manifest.json`, `directions.md`, `critique.md`, `proof.md`, `sources.json` or `gate/reader-runs.jsonl` after the seal also flips the round from COMPLETE to OPEN; a test proves one of each. ORDER, same decision: dc-10 now runs BEFORE dc-21 (ASK-1808 -> ASK-1806 -> dc-10 -> dc-21), because it closes a live bypass and dc-21 is test debt. ADDED 2026-09-19 by Sana's design calls before build. CUTOVER: the cutover is not a stored constant: it is the commit date, in the round's own repo (`git -C <round>`), of the design-chain-gate.py bytes currently committed there (found via git history of the gate's own repo-relative path), so it advances automatically the moment a real sync commit lands the stages-aware gate in that instance. A bare receipt is honored only when the current bytes of receipts.json equal its bytes at some commit dated before that cutover; a hand-typed, uncommitted or since-edited receipt matches none and reads OPEN. A test proves a repo with no history for the gate's path fails closed (not grandfathered). DIGEST: asset_digest/round_asset_digest is the one function used by both seal's write and sealed_and_unedited's recompute, excluding only _SEAL_WRITES; a test proves editing brief.md, craft-manifest.json, directions.md, critique.md, proof.md, sources.json or gate/reader-runs.jsonl after seal flips COMPLETE to OPEN, and _CHAIN_RECORDS is removed once nothing reads it. STAGES: only stages with a wired producer in this gate get a stage record (today: standard, gap), each with the producer's repo-relative path, sha256 and exit code; a test proves a round sealed today carries no entry for impeccable/readers/checks/engines, and a later issue adding one of those producers is the only path that adds its stage. Paths are relative to `git -C <round> rev-parse --show-toplevel`, and 'appears in git history' is checked in that same repo. CACHE: the passive hook path (open_pages -> chain_problems -> sealed_and_unedited) caches the digest and cutover check per round in the session ledger, keyed by a cheap file-set fingerprint (path, size, mtime), so repeated browser-show/Stop events in one session do not re-hash the round or re-spawn git on every call; a test proves N calls in one session produce one recompute, not N. VERIFY CONTRACT 2: the required check drives design-chain-gate.py at its tracked path (no gate copy in a temp bin). ADDED 2026-09-19 by Sana's triage of dc-10 review round 1. BELIEF: a recorded `__gate__` is believed only when its path equals `repo_path(GATE_FILE, <round>)` for the gate that is running, and its sha256 matches that file now or, for a repo-relative path only, appears in that path's git history. A stage record is believed only when its path equals `repo_path(HERE/<the producer this gate runs for that stage>)`, its sha256 passes the same rule, and its exit is 0; a stage name this gate has no producer for is not believed. A copied gate or producer is therefore refused whether or not its directory still exists, and a test proves it with the copy present. REQUIRED STAGE: every page entry in a staged receipt carries a believed `standard` stage; `stages: []` reads OPEN. SHAPE: `stages` must be a list of objects, each with string `stage`, `path` and `sha256` and an integer `exit`, and `__gate__` and `__assets__` must be objects; anything else reads OPEN with "the receipt's stage record is malformed", never a traceback. CACHE: the fingerprint is (path, size, mtime_ns, ctime_ns, inode), because a same-length rewrite with mtime restored kept a stale verdict; a test proves it. Cache values in STATE_DIR are trusted: same-user tampering is out of scope for a local check. DIGEST SCOPE (reconciles the DIGEST sentence above with the code): the digest also excludes `corrections.jsonl` and the round's top-level page files, because each page carries its own sha in the receipt and a wording correction to one page must not open every other page; a test proves a correction on page A leaves page B COMPLETE. OUTPUT SHA: the Acceptance clause "with each producer's output sha" is superseded by the STAGES sentence (path, sha256, exit) and moves to ASK-1826, with grandfathered-round binding, ancestry instead of dates, corrected pages, and a recorded skip list. Same-user forgery of a whole receipt and of STATE_DIR moves to ASK-1827 (CI recompute).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover (DELIVERED: receipts record the gate and each stage; the passive gate believes a receipt only at the gate's own path, with exit 0, a standard stage per page and the round digest; a bare receipt only through git history; cached by a stat fingerprint with ctime and inode. Consulting: 32/32 COMPLETE. Moved: ASK-1826 (grandfathered/corrected binding, ancestry, output sha, skip list), ASK-1827 (same-user forgery, CI).)

## Amendments

### 2026-09-19T02:38:52Z
Reason: Two tests outside dc-10's allowed_files assert the pre-dc-10 digest rule and must flip with it: test_dc_served_round.py::AssetDigest::test_the_chains_own_records_do_not_move_the_digest and test_design_chain_gate.py::TestPasses::test_full_chain_passes_send_and_stop. Both encode the behavior dc-10 deliberately reverses (critique.md/impeccable.txt/reader-runs.jsonl now move the digest; a screenshot must land before seal, not after). Adding them to allowed_files so the issue's own scope covers the tests it breaks, per its stated acceptance criteria. (Sana, 2026-09-19)

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/test/test_dc_receipts.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_receipts.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/test/test_dc_receipts.py', 'q-system/.q-system/scripts/test/test_dc_served_round.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_receipts.py']
- disallowed_files: []

### 2026-09-19T03:20:24Z
Reason: Sana's triage 2026-09-19 of dc-10 review round 1 (92e9f77c): ship F1 (bind to the running gate's own path, exit 0), F2 (a standard stage per page), F3 (ctime/inode in the cache fingerprint), F12 (receipt shape), tests for F16/F17, and the DIGEST SCOPE sentence; move grandfathered/corrected/old-format binding and output shas to ASK-1826, same-user forgery to ASK-1827.

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/test/test_dc_receipts.py', 'q-system/.q-system/scripts/test/test_dc_served_round.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_receipts.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/test/test_dc_receipts.py', 'q-system/.q-system/scripts/test/test_dc_served_round.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_receipts.py']
- disallowed_files: []
