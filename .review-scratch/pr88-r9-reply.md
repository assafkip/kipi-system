## Round 9 finding: real, and outside this PR's diff

The reviewer's own note says it: *"This logic has been unchanged since commit `d528638`."* That is correct, and it is the whole disposition.

**This PR touches 5 files. `ci-redrive.py` is not one of them.**

```
$ git diff --name-only origin/main...HEAD
q-system/.q-system/capability-manifest.json
q-system/.q-system/instruction-budget-baseline.json
q-system/.q-system/scripts/apply_claude_changes.py
q-system/.q-system/scripts/instruction-budget-audit.py
q-system/.q-system/scripts/test/test-instruction-budget-ratchet.sh

$ git diff --name-only origin/main...HEAD | grep -c ci-redrive
0

$ git log --oneline -1 -- q-system/.q-system/scripts/ci-redrive.py
d528638 Red CI on an agent PR is re-dispatched to its agent, not emailed to the founder (ASK-295) (#73)
```

`d528638` is ASK-295, PR #73, already merged to main. Pulling a fix for it into an instruction-accounting PR would put another issue's control code in this diff and break the allowed_files scoping that `/issue-review` runs on.

**So it is captured, not fixed here:** `sp-99eaa9d3` (open, severity major, source ASK-285). The standing spillover gate stays red until it is resolved, so it cannot be forgotten. It is distinct from the two neighbouring items already on the ledger: `sp-5d92a01d` is about the message CONTENT naming no next action, and `sp-b0807ab4` is about `ledger_recorded()` being a write named like a read. This one is the claim/delivery ordering.

Recorded fix shape, so whoever picks it up does not re-derive it: make delivery success part of the atomic claim, so a nonzero notifier exit stays retryable without producing page spam.

## The ASK-285 work itself, re-run at this head

```
$ bash q-system/.q-system/scripts/test/test-instruction-budget-ratchet.sh
PASS=143 FAIL=0

$ bash q-system/.q-system/scripts/test/test-apply-claude-changes.sh
passed: 122   failed: 0

$ bash q-system/.q-system/scripts/test/test-claude-write-path.sh
passed=78 failed=0

$ python3 q-system/.q-system/scripts/instruction-budget-audit.py --ratchet --no-write
RATCHET PASS: total 512, cap 512, headroom 0. Target 300.
```

Real-repo cap is still 512 with headroom 0: nothing lands today that would not have landed before this PR.

Not merging. Closeout goes through `/issue-verify` and `/issue-closeout`.
