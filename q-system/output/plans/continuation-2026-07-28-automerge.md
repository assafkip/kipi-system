# Continuation: the merge step is a repo setting, not an architecture problem

Written 2026-07-28 ~00:00Z. Paste this whole file into a fresh session.
Supersedes `continuation-2026-07-27c.md`. That file's §10 order is DONE through
step 4; its §7 corrections still hold and are restated in §8 below.

You are **Sana**, senior staff engineer, in `/Users/assafkipnis/projects/kipi-system`.
Tracking epic **ASK-113**. Founder authorized this end to end and does not review
code. Do not hand work back. Fix the loop; do not route around it.

---

## 1. THE FOUNDER'S HARD REQUIREMENT (read before anything)

> "I do not want to be the merge step - ever. Nothing should hinge on me."

This is a constraint, not a preference. **Never ask the founder to merge. Never
ask permission to merge.** Merging is pre-authorized. If you catch yourself
writing "want me to merge?", that is contract rejection. Merge it.

Also: **do not narrate the founder's time.** "Not tonight", "that's for
tomorrow", "when you're ready" are all forbidden. You do not schedule them.

---

## 2. THE FINDING THAT EXPLAINS 48 HOURS

We spent two days hand-building things GitHub already does. Three repo settings:

| setting | was | now | what it does |
|---|---|---|---|
| `allow_auto_merge` | **false** | **true** (I set it) | GitHub merges the PR itself when required checks pass. No human. |
| `allow_update_branch` | false | **true** (I set it) | GitHub can bring a stale PR up to date itself |
| `required_status_checks.strict` | **false** | still false | whether a PR must be current with main before merging |
| `required_pull_request_reviews` | **null** | still null | no approval bound to anything |

**`strict: false` IS the ASK-212 bug.** PR #11 approved 06:08, PR #16 landed
17:30 and broke it. We spent a whole issue teaching the loop to notice. It is a
checkbox. (Bors/homu calls this the *Not Rocket Science Rule*: never merge
anything that has not passed tests on the merged result.)

**The local verdict file IS the ASK-216 bug.** A GitHub status is bound to a sha
by construction. We store verdicts in `~/.config/kipi/pr-reviews/pr-<N>.verdict.json`
keyed by PR NUMBER, which is precisely why it cannot say which code it approved.

### Why 48 hours, structurally

1. **The loop has never completed one cycle.** Every run ends waiting on a human,
   so it has never once proven it works end to end.
2. **Every failure is silent.** Stale copy reported success; agent died holding
   work and converge said "no PR"; the CI scope scanner could not start and that
   looked identical to finding nothing. Breaks are found only when a human
   squints at a log, one at a time. Hence serial discovery: fetch, then
   mergeability, then receipt, then producer, then deadlock, then sha.
3. **Components are tested; the composition is not.** Every fix ships a
   reproducer for its own unit. Nothing exercises
   issue -> PR -> review -> merge -> receipt as one path.
4. **The precondition list is unbounded.** The merge-authority design named six
   things that must be true before a script may merge. One night added four more.
   "Safe enough" has no floor, so the integrator never ships.

### The architectural correction

Prior art (GitHub merge queue, Bors/homu, Mergify, Kodiak) all share one shape:

> **Every precondition is a required status check. The platform does the merging.**

Not a bespoke script that runs afterward and decides. `pr-receipt-gate.py` is
already a CI step, which is right. The reviewer's verdict is a local file, which
is wrong, and that single choice created the sha bug.

**Item 6c (`pr-integrate.sh`) in `merge-authority-design-2026-07-27.md` should
mostly NOT be built.** Required checks + auto-merge is the integrator.

---

## 3. THE APPROVAL IDENTITY QUESTION — ANSWERED AND PROVEN

The founder asked: can approvals actually happen, does the bot need its own login?

**No bot login is needed.** Proven live on 2026-07-27, not assumed:

```
$ gh auth status
  Logged in to github.com account assafkip   scopes: 'gist','read:org','repo','workflow'

$ SHA=$(gh pr view 23 --json headRefOid --jq .headRefOid)     # 6f540dfd...
$ gh api -X POST repos/assafkip/kipi-system/statuses/$SHA \
    -f state=success -f context=kipi/reviewer-probe -f description="probe"
{"context":"kipi/reviewer-probe","creator":"assafkip","state":"success"}

$ gh pr view 23 --json statusCheckRollup
[{"name":"validate","state":"FAILURE"},
 {"name":"kipi/reviewer-probe","state":"SUCCESS"}]     <-- auto-merge can see it
```

### Why a commit STATUS, not a PR review

| | commit status | PR review |
|---|---|---|
| needs a second identity | **no** | **yes** (GitHub forbids approving your own PR, and these PRs are authored by `assafkip`) |
| bound to a sha | **yes, inherently** | yes |
| can be required in branch protection | **yes**, arbitrary context name | yes |
| posted by existing token | **yes**, `repo` scope is enough | n/a |

A PR *review* would deadlock us: the agent runs as `assafkip`, the PR author, and
GitHub refuses self-approval. A *status* has no such rule. That is the whole
answer, and it is why the reviewer must emit a status.

**Left behind by the probe:** a `kipi/reviewer-probe` SUCCESS status on sha
`6f540dfd` of PR #23. Statuses cannot be deleted. It is not a required context so
it is inert. Ignore it, or supersede it with `state=failure` if it bothers you.

---

## 4. THE ORDERING TRAP — DO NOT REPEAT PR #23

**Do NOT add `kipi/reviewer-approved` to `required_status_checks.contexts` until
the reviewer actually posts it.** A required context that nothing produces blocks
100% of PRs forever.

This is the SAME mistake as PR #23: a gate that landed before its producer
existed. That trap cost this project a full day. The rule is:

> **Producer first, then the gate. Always. Verify the producer emits on a real PR
> before making it required.**

---

## 5. WHAT TO BUILD (in this order)

Everything below is one Linear issue each, one change each, `owner:sana`, filed
with a `## Definition of Ready` (Files / Check / Outcome / Not doing) or the
worker will not pick it up.

**5a. Reviewer posts a commit status.** `pr-review-agent.sh` posts
`kipi/reviewer-approved` on the PR's head sha: `success` for an approving verdict,
`failure` otherwise, with `target_url` pointing at the review markdown. Keep
writing the local JSON too for now (`converge.sh` still reads it). Capture the sha
ONCE at review time from the same state the reviewer read; never look it up after,
or the record claims a commit the reviewer never saw.

**5b. Verify on a live PR**, then add `kipi/reviewer-approved` to
`required_status_checks.contexts`. See §4. This is the step that must not be
rushed.

**5c. Agent PRs opt into auto-merge.** `linear-worker.sh` (or wherever the PR is
opened) runs `gh pr merge --auto --squash <n>`. GitHub then merges when `validate`
and `kipi/reviewer-approved` are both green. **This is the step that removes the
founder from the loop.** Ship it.

**5d. Flip `strict: true`.** Requires PRs be current with main. `allow_update_branch`
is already on so GitHub can self-update them. This closes the ASK-212 class at the
platform level. Expect some churn; that is the intended cost.

**5e. Then reassess ASK-216 and item 6c.** 5a makes the verdict sha-bound for
free, so ASK-216 may be redundant. Read it before continuing it. 6c is mostly
cancelled by 5c.

**5f. The composition test.** Nothing exercises the full chain. Build one
end-to-end check (a throwaway issue that goes issue -> PR -> review -> merge ->
receipt unattended) so the loop can prove itself instead of being audited by hand.
This is the fix for diagnosis #3 in §2 and is arguably the most valuable item here.

---

### 5a + 5b: DONE 2026-07-28 00:41Z. Evidence, not assertion.

**5a merged** as PR #29 -> `94a95263` (ASK-217). `pr-review-agent.sh` posts
`kipi/reviewer-approved` on the sha captured before the reviewer ran: `success`
for APPROVE / APPROVE WITH NITS, `failure` otherwise, a loud WARN when the POST
fails, and nothing at all when the sha is empty.

**Proven on a live PR** before the gate was armed, which is the §4 rule:

```
$ gh pr view 27 --json headRefOid,statusCheckRollup
head: c063c3dd8c59c4b0c49469440e81ab4b6a93cbbf
  validate                 SUCCESS
  kipi/reviewer-approved   SUCCESS   -> .../pull/27#issuecomment-5098509039
```

**5b armed** only after seeing that:

```
$ gh api -X POST .../branches/main/protection/required_status_checks/contexts \
    -f 'contexts[]=kipi/reviewer-approved'
["validate","kipi/reviewer-approved"]
```

Pre-change protection saved to the session scratchpad
(`branch-protection-before-5b.json`) so this is reversible. `enforce_admins` is
false, so the auto-committer's direct pushes to `main` are unaffected. Used the
`.../required_status_checks/contexts` endpoint deliberately: a `PATCH` on
`/protection` REPLACES the whole payload and would have silently dropped
settings it did not restate.

**The negative case is PROVEN.** PR #30 (ASK-219) supplied all three states on a
live PR, so the gate is known to refuse and not merely known to allow:

```
00:43:27Z  PR #30 opened     validate:SUCCESS, no reviewer status   -> MERGEABLE BLOCKED
           ... held BLOCKED for 11 minutes on ABSENCE alone ...
00:54Z     reviewer ran      + kipi/reviewer-approved:FAILURE       -> MERGEABLE BLOCKED
(earlier)  PR #27 approved   both SUCCESS                            -> merged
```

Allows on green, refuses on ABSENT, refuses on FAILURE. A gate only ever seen
allowing is not a gate; these are the two refusals that make it one.

### 5c: the platform is the integrator — proven on PR #30 before any code

`gh pr merge --auto --squash 30` at 00:54:51Z. GitHub now holds the PR itself:

```
autoMergeRequest.enabledAt  2026-07-28T00:54:51Z   mergeMethod SQUASH
mergeable MERGEABLE   mergeStateStatus BLOCKED     <- held on the FAILURE status
```

The whole chain is now live and unattended: ASK-219's round-2 agent pushes ->
new sha -> `validate` runs -> the reviewer runs and posts a sha-bound status ->
if approving, **GitHub merges it with no human in the path.**

This is why item 6c (`pr-integrate.sh`) should not be built. There is no script
here. Two required checks plus one platform flag, which is the §2 shape every
prior-art integrator converged on.

**5c's remaining code is small and mechanical:** `linear-worker.sh` runs
`gh pr merge --auto --squash "$PR_NUM"` right where `PR_NUM` is resolved (~line
699), covering both the agent-opened and worker-opened paths. Ship it AFTER
ASK-219 lands — both edit that file, and §8's conflict class is not worth
re-learning.

### 5g-CORRECTION: ASK-219 does NOT block 5c. 5b already solved it structurally.

Earlier tonight I filed ASK-219 (wire the sha-drift exit to its callers) as a
blocker for 5c, reasoning that auto-merge on a stale approval merges unreviewed
code. **That reasoning was superseded by 5b and is now wrong.**

A commit status is bound to a sha *by construction*. Once
`kipi/reviewer-approved` is a REQUIRED context, a push creates a new sha that
carries no such status, so the required context reads absent and **GitHub will
not merge it** — no local logic involved. Merge-time drift is structurally
impossible, not merely detected.

ASK-219 is still worth shipping: `converge` currently reports "waiting on founder
merge only" for a PR whose approval is stale, which is a lie about loop state and
a silent-success defect. But that is **loop-control honesty, not merge safety.**
It does not gate 5c.

The real remaining sequencing constraint is mundane: ASK-219 and 5c both edit
`linear-worker.sh`, so run them serially to avoid the conflict class §8 warns
about. Order between them does not matter; overlap does.

### 5g. WHY 5b MUST PRECEDE 5c — the order is load-bearing, not stylistic

Today `required_status_checks.contexts` is exactly `["validate"]`. Enable
auto-merge (5c) before `kipi/reviewer-approved` is required (5b) and GitHub
merges every worker PR **the instant CI goes green** — which happens minutes
after the push, long before the reviewer has read a line. That is not a slower
loop; it is an unreviewed-merge machine wired straight into `main`, and `main`
fans out fleet-wide through `kipi update`.

The failure is silent in the worst way: it looks exactly like success. PRs merge,
the board moves, and nobody notices no review gated anything.

So: **5a (producer) -> 5b (make required, verified on a live PR) -> 5c
(auto-merge).** Never 5c early "to see if it works".

### 5h. 5d (`strict: true`) IS NOT A FREE CHECKBOX — verify before flipping

`allow_update_branch: true` gives GitHub the *ability* to update a stale branch.
It does **not** make GitHub do it automatically. Plain auto-merge + `strict: true`
is believed to leave a behind-main PR sitting at BEHIND forever, never merging and
never saying why — the same silent-stall class this project keeps finding.
{{UNVALIDATED}}: confirm on a real behind-main PR before flipping, or 5d
re-introduces the founder as the merge step through the back door.

The mechanism that genuinely does this is GitHub's **merge queue** (it tests the
merged result — the Not Rocket Science Rule — and updates branches itself). If the
behind-PR stall is confirmed, merge queue is the answer to 5d, not `strict` alone.

## 6. STATE AS OF 2026-07-28 00:00Z

**main:** `f1d70e7`, green. Three PRs merged in this session.

| merged | what |
|---|---|
| `8c9709e` (#24) | worker fetches origin before cutting a worktree (ASK-211) |
| `f1d70e7` (#25) | rework gate reads mergeability, caps rebase rounds (ASK-212) |
| `1ed3335` (#26) | `prd_split.py --from-linear` (ASK-214) |
| `033edfb` | triage skips issues with an open PR (sp-d901c01e) |
| `a327c31` | `linear-triage.py` declared inert (unbroke main) |
| `8a4fb3a` | containment scanner survives gitlinks (unbroke main) |

**Open PRs:**

| PR | branch | state |
|---|---|---|
| #27 | `sana/ask-215` | MERGEABLE. token-guard deadlock. converge round 2/3 running |
| #28 | `sana/ask-216` | MERGEABLE. verdict head sha. converge round 1/3 running |
| #23 | `sana/ask-210` | **CONFLICTING**. The receipt gate. See below |
| #5, #4 | pre-existing, not mine | untouched |

**Two converge runs were live when this was written.** Check them first:
`tail ~/.config/kipi/converge-ASK-215.log` and `-ASK-216.log`.

### Session log, 2026-07-28 00:04Z onward (Sana)

- **PR #28 (ASK-216) MERGED** `1b7e75c`. `validate` green, verdict APPROVE WITH
  NITS, CLEAN. ASK-216 auto-closed Done on merge, so the closeout half of the
  loop demonstrably works. The verdict record now carries `head_sha`, which makes
  5a cheap: the sha to post a status on is already captured before the reviewer
  runs (`pr-review-agent.sh:83`).
- **ASK-217 filed and dispatched** — 5a, the reviewer emits `kipi/reviewer-approved`
  as a commit status. `converge --issue ASK-217 --max-rounds 3`, round 1 at 00:06Z.
- **PR #23 DECIDED: does not merge in its current shape.** Recorded on the PR
  (`#issuecomment-5098257806`). Its `validate.yml` step is blocking, inside the
  ONE required context, and refuses any `sana/ask-*` branch lacking a receipt at
  the head sha. **No producer writes those receipts in the autonomous path** —
  `linear-worker.sh:637` only tells the agent not to close out, nothing invokes
  `/issue-closeout`, and the newest ledger entry (2026-07-26) belongs to an
  unrelated PRD. Merging it fails `validate` on 100% of worker PRs forever. This
  is §4's trap one layer down, and the PR failing its own gate is the gate
  correctly reporting it.
- **ASK-218 filed** — the producer: converge writes a receipt at the terminal
  approving verdict, only when the verdict's sha matches the head. Set as
  `blockedBy` on ASK-210. PR #23 merges as-is once it emits on a live PR.
  So the ASK-210 DoR question in the paragraph below is **moot** — the blocker was
  never the missing DoR, it was the missing producer.

### PR #23 specifically

It is now CONFLICTING and it fails its own receipt gate (`sp-ac51aa81` — its
docstring claims it avoids failing its own PR; it does not). To merge it, ASK-210
needs a `## Definition of Ready` so `--from-linear` can generate a spec and
`close` can write a receipt. `--from-linear ASK-210` **correctly refused** for the
missing DoR; that refusal is the feature working, do not force past it.

Founder was offered "let `kipi dor` draft it retroactively" vs "wait for the gate's
bootstrap fix" and did not answer, because the question was overtaken by §2. **Your
call now.** Also strip `q-system/output/ask210-read.py` from that PR: it is a
26-line one-off scratch script with no caller (`sp-8e11f94e`), which the
adversarial reviewer approved without flagging.

---

## 7. THE SILENT-SUCCESS PATTERN (the real enemy)

Every defect this project has found is the same class: **something fails while
reporting success.** Keep this as the primary lens.

- worker cut from stale code, reported success
- agent died holding finished work, converge exit-7 with worker rc=0
- containment scanner could not start, which read as "found nothing"
- a fetch guard that exited 0 on failure (caught in review, PR #22 round 3)
- a test that PASSED against the broken code (caught 2026-07-27, see §8)

**Corollary for your own work:** every reproducer must be shown RED against the
unfixed code before it is shown green. A test that cannot fail on the defect
certifies the bug.

---

## 8. CORRECTIONS — DO NOT RE-DERIVE

- **"~44 of 55 ready issues are scanner junk" was wrong.** `fleet-health` filed 3.
  The 32 job-migrations are the founder's own paused `com.cole.*` jobs; the 14
  audits are a deliberate fan-out. Closing them would delete the backlog.
- **The real disqualifier is structural.** Of 56 issues the worker called READY, 13
  carry no `**Files:**` line and 1 names only machine-local paths. Those produce no
  diff, so no PR, so `converge` exits 7 and burns an attempt.
- **The board is one day old.** 190 open issues created within 24h, 96% with zero
  comments. It is a dump, not an aged backlog.
- **The reviewer approves PRs whose required check is RED.** It reads diffs, not CI.
  `converge` exit-1 says "waiting on founder merge" for landable and unlandable PRs
  alike. **Converged != landable.** Always check CI yourself.
- **`plugins/kipi-dsse/scripts/linear_branch.py` does not exist on main.** PR #23
  creates it. `linear-triage.py` therefore carries a private branch->issue regex
  (`sp-6d394dbb`); collapse them once #23 lands.
- **The capability manifest is a magnet file** (`sp-f3a2ad81`). Every test-adding
  issue edits it. Prefer extending an existing test file in place. Do NOT re-sort
  `expected_tests` — one sort caused three separate merge conflicts in one session.
  Resolve conflicts there as a **union by path**, never by picking a side.

---

## 9. SCOPE DISCIPLINE — PROVEN FOUR TIMES

| issue | scope | rounds |
|---|---|---|
| ASK-209 | one change | **1** |
| ASK-211 | one change | **1** |
| ASK-212 | one change | 2 |
| ASK-204 | medium | 3 |
| ASK-208 | four changes | **capped out, closed unmerged** |

One issue = one change. This is not negotiable and it is the single strongest
predictor of convergence in the data.

---

## 10. STANDING CONSTRAINTS

- Subscription only. `claude -p` under launchd, never cron.
- **Launch converge DETACHED** or the harness kills it:
  `nohup ./kipi converge --issue ASK-n --max-rounds 3 > ~/.config/kipi/converge-<issue>.log 2>&1 & disown`
- **No `--admin`, ever.** Branch protection stays. `validate` stays required.
- **`git rebase` is DENIED** by `.claude/settings.json`. `git merge` is allowed and
  is this repo's sanctioned path. Do not try to route around the deny.
- **`rm -rf` and friends are hook-blocked** (`destructive-op-deny.sh`). Asking about
  those is the contract, not a violation of it. Never set `ALLOW_DESTRUCTIVE=1`.
- Linear objects are permanent. Delete and archive are hook-blocked.
- The worker's four refusals are load-bearing: never merges, never closes, never
  touches `owner:assaf`, never touches an issue without a DoR. **Auto-merge does
  not violate this** — GitHub merges, not the worker.
- Every commit message needs `(ASK-n)` or `[no-issue: reason]` (lefthook
  `commit-msg`).
- A changed plugin must bump its `.claude-plugin/plugin.json` version (lefthook
  `plugin-version-bump`).
- **`token-guard.py` blocks at 50 tool calls.** `git commit` is exempt and resets
  it. If a pre-commit gate refuses that commit you are deadlocked — that is
  ASK-215/PR #27, currently being fixed. Commit early and keep diffs small.
- A prompt instruction is not enforcement. `prompt-only-enforcement-guard.py`
  blocks the claim at write time.
- Instruction budget FAILING 513/300. Add no always-on rules; write plan docs.
- **No orphan findings.** Anything real and out of scope gets
  `prd_runner.py spillover add`, never a mention in chat. 144 open items.

---

## 11. UNRESOLVED / KNOWN DEBT

- `sp-1aae7516` — the auto-committer sweeps agent scratch into main. 196 files
  across `.pr22rev/`, `.pr23rev/`, `.pr24rev/`, `.pr25rev/`, `.review-scratch/`,
  including **11 gitlinks** (mode 160000). Those gitlinks took the containment gate
  down fleet-wide (fixed defensively in `8a4fb3a`; the scratch itself is untouched).
- `sp-3a0cac1c` — a crashed reviewer reaches nobody. Problem 3, not filed yet.
- `sp-f3a2ad81` — magnet file, blocks naive file-disjoint parallel dispatch.
  Problem 4, not started.
- `sp-0126e55b` — `com.kipi.linear-dor` is LOADED and drafts 8 DoRs/night onto
  untriaged issues. **Triage must gate the drafter, not follow it.**
- `sp-ac51aa81`, `sp-3c2a4527`, `sp-96d10f08`, `sp-8e11f94e`, `sp-6d394dbb`,
  `sp-97303649` (being fixed by ASK-215).
- `gates run` is RED and pre-existing (ASK-148).

## 12. TRIAGE — WAITING ON A FOUNDER READ, NOT A DECISION

A full dry pass over 115 issues ran. **Nothing was written to Linear.** Table at
`q-system/output/plans/triage-dry-table-2026-07-27.md`, already sent to the founder.

| count | bucket |
|---|---|
| 57 | batch |
| 38 | **not-planned** (the only destructive one: comment + close as not planned) |
| 9 | needs-scope |
| 7 | do-now |
| 4 | founder-decision |

ASK-210 was auto-skipped as in-flight, which proved the `sp-d901c01e` fix in
production. Do not run `--apply` until the founder has read the 38.
