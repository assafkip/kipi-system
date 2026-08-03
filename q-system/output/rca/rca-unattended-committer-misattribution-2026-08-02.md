# RCA: a Stop-hook committed in-flight work to the wrong branch under a generic message, twice

**Date:** 2026-08-02
**Trigger:** Sana went to land the ASK-122 fix and found it already committed on `sana/ask-294` as `chore: update system infrastructure [no-issue]`. The same hook swept the ASK-312 work a few hours later.
**Surface-fix commit:** a031ca7 (re-applies the value the second sweep helped lose)
**Structural-fix commit:** pending — see Action items

## What happened

Three incidents, one mechanism.

**1. ASK-122 work landed on ASK-294's branch.** The coordinator edited
`capability-map-gen.py`, its test, and the capability manifest, then reported them
as uncommitted — `git status` was clean. It was clean because an unattended
auto-commit had already swept all three into `7383d6c "chore: update system
infrastructure"` on `sana/ask-294`, a branch belonging to an unrelated issue.
Sana had to extract them in a worktree, reland them on a correct branch, and
revert them off `ask-294`.

**2. ASK-312 work swept mid-task.** Hours later, `4559194 "chore: update system
infrastructure"` captured the review-gate fix, its fixtures, and an unrelated
dispatch config change into one generic commit. Caught before push; undone with a
soft reset and split into two properly-messaged commits.

**3. A config edit lost entirely.** The dispatch spend dial had been raised 3 → 10
in the repo template. The change existed only in the working tree, and a branch
switch to a new branch off `origin/main` left the template reading `4` while the
live launchd plist read `10`. A spend control silently disagreed with itself, and
any reinstall would have reverted the founder's directive.

## Surface symptom

Work attributed to the wrong issue, under a message that describes nothing, with
`[no-issue]` recorded in the bypass ledger — and a `git status` that reads clean
while a report says "uncommitted", so the two disagree and neither is wrong.

## Surface root cause

An auto-commit hook fires on Stop, stages whatever is dirty in the working tree,
and commits it to whatever branch happens to be checked out, under a fixed
subject line.

## Structural root cause

type: process

**A writer with no scope, running at a moment it cannot interpret.** The hook's
design intent is durability: unattended runs should not lose work. To achieve that
it commits *everything dirty*, and "everything dirty" in a repo where several
issues are in flight is not a unit of work — it is a snapshot of a moment.

Two properties make it misattribute rather than merely over-capture:

- **It cannot know which issue the dirt belongs to**, so it uses the branch, which
  is only correct when the branch and the work agree. In a session that switches
  branches, or one where a coordinator edits files for issue B while sitting on
  issue A's branch, the branch is exactly the wrong signal.
- **It declares its own bypass.** `[no-issue: reason]` is honest — the hook truly
  cannot know the issue — but it means the `linear-issue-ref` gate, whose whole
  job is to stop unattributed commits, *structurally cannot* catch this writer.
  The one gate positioned to notice is disarmed by design.

The `linear-first.md` rule already names `auto-commit.py` as declaring the hatch
"by design". That was recorded as an accepted trade and never revisited against
the case where the hatch fires during attended, multi-issue work.

## Verification

Both sweeps were observed directly, not reconstructed:

```
git log --oneline -3
  4559194 chore: update system infrastructure      <- swept ASK-312 work
  4b4dd3e fix(capability-map): ... (ASK-122) (#74)

git show 4559194 --stat
  8 files changed, 6749 insertions(+), 8 deletions(-)
  ... pr-verdict-lib.sh, pr-review-agent.sh, fixtures/, com.kipi.dispatch.plist
```

Incident 3, the divergence that resulted:

```
launchctl print gui/501/com.kipi.dispatch | grep DAILY_MAX
  KIPI_DISPATCH_DAILY_MAX => 10      <- live
grep -A1 KIPI_DISPATCH_DAILY_MAX q-system/.q-system/scripts/com.kipi.dispatch.plist
  <string>4</string>                 <- template
```

Recovery for incident 2, which is the shape that should have been unnecessary:

```
git reset --soft HEAD~1
git restore --staged .../com.kipi.dispatch.plist
-> two commits, each with a real subject and a real issue ref, both gates green
```

## Contributing factors

- **The founder's parallel-session scar is adjacent and already recorded**: two
  sessions sharing one checkout yank each other's tree on a branch switch. The
  same root — working-tree state treated as session-private when it is not.
- **`git add <paths>` silently drops files**, which is how incident 2 was noticed
  at all: six paths were staged, two appeared, because four were already committed.
- **The generic subject line defeats review.** `chore: update system
  infrastructure` appears repeatedly in recent history, so the sweep is
  indistinguishable from routine noise in a log skim.
- **The hook is fleet-wide**, so any fix touches every session — which is why it
  was not changed mid-session and is filed instead.

## Fixes shipped

- Incident 1: extracted in a worktree, relanded as `d20f412` with a real issue
  ref, reverted off `sana/ask-294` as `e770838`; 0 capability files left in that
  branch's diff.
- Incident 2: soft reset, split into `5495a9b` (ASK-312) and `a031ca7` (dispatch
  template), both passing `linear-issue-ref` without bypass.
- Incident 3: template re-raised to 10 in `a031ca7` with the live-vs-template
  divergence named in the message.
- Captured as `sp-9d61ced1` with three fix directions, none picked, because the
  hook touches every session and the choice is a design call.

## Action items

- [ ] Change the unattended committer from "commit to the current branch" to
      "commit to a per-session WIP ref" (e.g. `refs/kipi/wip/<session-id>`).
      Durability is preserved — nothing is ever lost — and no named branch gains
      a commit nobody intended. Owner: Sana. This is the recommended direction of
      the three in `sp-9d61ced1`.
- [ ] Until that lands, scope the sweep: refuse to stage a path that is not under
      the file set of the branch's own issue, and emit the skipped paths so the
      operator sees what was left dirty. Owner: Sana.
- [ ] Make the `[no-issue]` hatch loud rather than silent: a weekly count from
      `q-system/output/linear-bypass.jsonl` routed through `slack-notify.sh`, so
      a gate that structurally cannot catch this writer at least reports how often
      it fired. Owner: Sana.
- [ ] Add a live-vs-template drift check for launchd plists to
      `fleet-health-daily.py`: compare each installed plist's env values against
      its repo template and report divergence. Incident 3 was invisible until a
      branch switch exposed it. Owner: Sana.

## Lessons

- An unattended writer needs a scope, not just a trigger. "Whatever is dirty" is a
  snapshot of a moment, and a moment is not a unit of work.
- A gate that a writer is permitted to bypass does not cover that writer. If the
  bypass is genuinely necessary, the bypass itself needs counting.
- A config value that lives in two places diverges silently, and a spend control
  is the worst place for that to happen: the number you read stops being the
  number that runs.
