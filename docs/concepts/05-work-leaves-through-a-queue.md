# Work leaves through a queue

The founder does not review code and is not the merge step. Work enters as a Linear issue,
an agent picks it up, a different model reviews the pull request, the checks decide, and
GitHub merges it. Every step leaves a record, every failure has a machine consumer, and the
only decisions that reach a person are publish, spend and delete.

```mermaid
sequenceDiagram
    participant Src as Detectors and founder
    participant L as Linear
    participant W as Worker (linear-worker.sh)
    participant PR as GitHub PR
    participant R as Reviewer (pr-review-agent.sh)
    participant CI as CI checks
    participant S as Sana's triage queue
    Src->>L: issue filed (needs-triage label if a machine filed it)
    L->>L: triage pass decides worked / parked / voided, records why
    L->>L: a Definition of Ready is drafted if missing
    W->>L: claims a ready issue (claim lock, one agent at a time)
    W->>PR: opens a branch and a PR, commit names the issue
    PR->>CI: validate, verify, reviewer floor
    PR->>R: fresh-eyes adversarial review, verdict posted as a commit status
    alt REQUEST CHANGES
        R-->>W: findings, each reproduced
        W->>PR: fixes with a test that goes red under mutation
        PR->>R: next round (capped; a repeated finding class means a structural fix)
    else APPROVE
        CI-->>PR: all required checks green
        PR->>PR: auto-merge squashes to main (the only permitted merge shape)
    end
    PR-->>L: issue closed with the command that proves it
    CI-->>S: red CI or a refused review gets a machine consumer, then a ticket if it cannot recover
```

A task's whole life. Issues arrive from detectors (a failed job, a drifted counter, a
review finding) or from the founder. A triage pass records a decision on each one so the
board does not only grow. Issues lacking a Definition of Ready get one drafted. The worker
claims a ready issue with a lock so two agents never take the same one, does the work on a
branch, and opens a pull request whose commits name the issue. Continuous integration runs
the same script the pre-commit hook ran locally, and `pr-review-agent.sh` runs a fresh-eyes
review of the diff and posts its verdict as a commit status. Findings get fixed with a
test that fails when the fix is removed; a finding class that repeats across rounds means
the fix shape was wrong and the next fix is structural. When every required check is
green, GitHub merges; the one command shape that skips the checks is refused by a gate.

## The pieces that keep it honest

- **A claim lock.** An issue another session already holds is refused.
- **A severity floor.** An absent review verdict counts as failing, never as passing.
- **Bounded rounds.** The review loop has a declared cap; past it, findings are captured
  as spillover and the merge decision goes to the triage queue.
- **Machine consumers for red.** Red CI and a refused review each have a script that
  reads the failure, retries what is retryable, and files a ticket when it cannot.
- **Cross-model escalation.** When the working model is stuck (same retry three times, an
  edit spiral, a call ceiling), a fresh session of a different model triages the transcript
  tail and hands back one diagnosis, one thing to stop, one next action, and the command
  that would refute it.
- **The alert path pages nobody.** Engineering signals become Linear tickets in an agent's
  queue. Founder pings are the exception, wired per instance, never a default.

## What this means for you

You will see pull requests appear, get reviewed and merge without you. The place to look is
the Linear board and the PR body, which carries the measured numbers and the honest
boundary of each change. Three things still come to you, and only three: something is about
to be published, something costs money, something is about to be deleted. Everything else
has a machine that owns it, and if that machine cannot cope, a ticket in the triage queue
says so.
