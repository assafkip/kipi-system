# RCA: ASK-4386 took two review rounds because a held `.claude/` loss had no declared exit

**Date:** 2026-11-14
**Trigger:** Round 3 of ASK-4386 (`~/.claude/rules/iteration-speed.md` rule 6: at round 3 a fresh Sana agent writes the RCA, then continues from it). Two review rounds on PR #738 both returned REQUEST CHANGES; the PR was closed by pr-owner on 2026-11-13 with the issue still open.
**Author:** Sana (fresh agent)
**Scope:** `q-system/hooks/auto-commit.py`, `q-system/.q-system/scripts/linear-issue-ref-check.py`. Prior branch `sana/ask-4386-auto-commit-claude-deletions` at `5dea9a4e`; this branch `sana/ask-4386`.

## What happened

Six review findings across two rounds on one 521-line diff, and the issue is
still open after three dispatches. Both rounds fixed the exact finding the
reviewer pointed at and both re-opened the same hole somewhere else, because the
new state the fix introduced (a `.claude/` loss that is held: not committed, not
reverted) never had its exit declared for every caller.

## Surface symptom

Round 1 shipped "hold the loss, leave it uncommitted" and earned a blocking
major: the tree stays dirty, so `kipi-update.sh`'s own guard abandons that
instance on every run. Round 2 shipped "restore the held loss from HEAD in
`--system-state`" and earned a major: that restore reverts any author's
uncommitted line-dropping `.claude/` edit, its stderr notice is discarded by
`kipi-update.sh 2>/dev/null`, and its ledger is read by nothing. The Stop-hook
half still only holds, which is round 2's second major: the deleted rule file
stays missing from the worktree, the next session in it runs without that rule,
and no named consumer restores it.

## Surface root cause

type: process

Each round fixed the finding the reviewer wrote down, at the file:line the
reviewer pointed at. Round 1's finding named `--system-state`, so round 2
changed `--system-state` and nothing else. The Stop-hook half has the identical
hole and was never revisited, because no finding had named it yet.

## Structural root cause

type: implicit-contract

**The hold introduced a new state and never declared that state's exit, so the
exit got designed one caller at a time, by whichever reviewer reached it first.**

`hold_claude_losses` creates "a `.claude/` loss that is on disk or not, not
committed, and not reverted". That state has exactly three exits: commit it (the
original 2026-11-10 scar), revert it (can destroy content), or leave it
(abandons the caller). `loop-exits.md` is explicit that a durable loop declares
its exits in CODE before the prompt is written. This change declared none, and
there is no test, gate or docstring anywhere in the diff that enumerates the
callers of the held state. The contract was implicit, so two of the three
callers were simply never considered.

## Contributing factors

1. **The restore was scoped to the context it was discovered in, not to the
   hazard.** `q-system/lessons/scoping-guards-to-the-hazardous-operation.md`
   step 5: state the contract in one sentence next to the guard, or the guard is
   scoped to a symptom. Round 1's finding arrived from the updater, so the
   restore was written into the updater's mode and nowhere else. The real
   discriminator is whether the held loss holds any work at all, and that
   sentence was never written. type: implicit-contract
2. **A terminal state with no named next actor.**
   `~/.claude/rules/no-idle-escalate-to-sana.md`: "there is no someone". The
   restore wrote `restored.jsonl` and one stderr line. Nothing reads the file,
   and the stderr is discarded two call sites up. Round 2's first major is
   literally that sentence. type: process
3. **Round 1's two halves collided with each other.** The gate half refuses a
   `[no-issue:]` bypass on any branch naming an issue. `kipi-update.sh:3183`
   commits `[no-issue: fleet updater system-state commit]`, so an instance
   checkout parked on `sana/ask-NNNN` has that commit refused. That re-creates
   round 1's own blocking major (instance abandoned) through a different file,
   and it is round 2's minor. Nothing enumerated the bypass emitters before the
   refusal was added. type: missing-test

## Verification

Measured in this worktree, not recalled:

```
$ grep -n "system-state" kipi-update.sh
2940:                 | python3 "$sys_classifier" --system-state 2>/dev/null)
3133:                    python3 "$sys_classifier" --system-state 2>/dev/null
3183:        if ! retry_on_index_lock "$path" "system-state commit" git commit -q -m "chore: commit system-written state before skeleton sync [no-issue: fleet updater system-state commit]
3189:          echo "  WARNING: the system-state commit FAILED; this instance will very"
```

Both `--system-state` call sites redirect stderr to `/dev/null`, so the
round-2 restore notice cannot reach an operator. `kipi-update.sh` is OUTSIDE
this issue's allowed-files list, so the notice has to leave `auto-commit.py` by
another road.

```
$ grep -rn "no-issue:" . --exclude-dir=.git | grep -v linear-issue-ref-check
kipi-update.sh:2798 ... [no-issue: fleet updater instance-local untrack]
kipi-update.sh:2860 ... [no-issue: fleet updater never-commit untrack]
kipi-update.sh:3183 ... [no-issue: fleet updater system-state commit]
kipi-update.sh:3388 ... [no-issue: fleet updater skeleton sync]
kipi-update.sh:3650 ... [no-issue: fleet updater skeleton sync]
fleet-unblock.py:413 ... [no-issue: fleet updater exhaust, no issue in this instance]
kipi-update-voiceloop-migrate.py:831 ... [no-issue: fleet migration, sp-8d55455a tracks it]
q-system/.q-system/scripts/lessons-daily.sh:281 ... [no-issue: automated daily lesson persist]
q-system/hooks/auto-commit.py:635 ... [no-issue: auto-commit safety net, unattended Stop hook]
```

Nine bypass emitters. Exactly one of them (`auto-commit.py:635`) runs inside an
agent's issue worktree and can ask the gate for a branch issue. The other eight
run in a main checkout and have no issue to name. Round 1's refusal was written
against all nine. Observed count, so this is a measurement and not an opinion.

Rounds 1 and 2 share a finding CLASS, "the held loss has no correct exit". Per
`feedback_same_finding_twice_go_structural`, the fix SHAPE was wrong, not the
fix detail.

## Fixes shipped

Declare the exit once, scoped to the hazard rather than to the caller. The
discriminator is whether the working copy holds anything:

- [x] A held path **absent from disk** holds no work, so restoring it from HEAD
      can lose nothing. BOTH modes restore it. That is round 2's second major
      (the Stop hook) and it names its consumer: the Stop hook itself.
- [x] A held path **present with lines dropped** has someone's content on disk.
      The Stop hook leaves it dirty and prints, because a live session is there
      to read the line. The `--system-state` sweep restores it, keeps a copy,
      and files ONE ticket for Sana, because the alternative is abandoning that
      instance on every sync.
- [x] One sentence next to the guard: *an unattended committer never commits a
      `.claude/` loss and never leaves one that holds no work; HEAD is the
      truth, the working copy is kept, and a restore that could cost content is
      filed for Sana.*
- [x] Named consumer for the restore event: `slack-notify.sh`, which files a
      Linear ticket for Sana. One alert per restore EVENT with a stable shape,
      never one per path: the 2026-08-10 flood that moved that sink off Slack
      was 51 auto-commit messages naming a file set that changed every turn.
- [x] The gate refusal narrows to the one committer that can name its branch
      issue, so none of the other eight bypass emitters is ever refused.
- [x] A reproducer per open finding, observed RED on `36915e5a` first.

## Action items

- [x] Restore in BOTH modes, discriminated by "absent from disk" rather than by
      caller. Owner: Sana, this branch.
- [x] Name the restore event's consumer (`slack-notify.sh`, one ticket per
      event). Owner: Sana, this branch.
- [x] Narrow the gate refusal to `auto-commit.py`'s own bypass reason. Owner:
      Sana, this branch.
- [x] A reproducer per open finding, observed RED on `36915e5a`. Owner: Sana,
      this branch.
- [ ] Promote lesson 1 below into `q-system/lessons/` so the next change that
      introduces a parked state inherits the exit audit. Owner: Sana, at
      `/issue-closeout` of ASK-4386.

## Lessons

1. **A change that introduces a held, parked or withheld state names that
   state's exit for EVERY caller, in the same commit.** Not one reviewer at a
   time. The audit is `loop-exits.md`: enumerate the callers, then write the
   exit each one takes. If the exits differ by caller, the discriminator goes in
   a docstring table, so the next reader cannot miss a caller.
2. **Before adding a refusal to a shared gate, count its current emitters.** One
   grep answered round 2's minor and would have prevented it. A refusal written
   against nine emitters when the hazard is one of them is a fail-closed check
   at a shared chokepoint, which is the exact failure signature
   `scoping-guards-to-the-hazardous-operation.md` already names.
3. **A notice whose only road is stderr is not a notice.** Check the call site
   before counting a print as an exit; two of two here redirect to `/dev/null`.
