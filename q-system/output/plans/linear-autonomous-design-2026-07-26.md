# Autonomous Linear-driven development for the kipi fleet

Design, 2026-07-26. Researched against Linear's docs (via `mcp__linear__search_documentation`),
Claude Code's official headless docs (`working-with-claude-code` skill references), and
this fleet's own code. Not a generic architecture: every component below is either
something kipi already runs or a named gap.

## The constraint that decides everything

**Subscription only.** That removes two of Linear's three agent paths:

| Linear path | Verdict | Why |
|---|---|---|
| **Coding sessions** (delegate → Linear runs Claude Code, drafts a PR) | **OUT** | Draws workspace **AI credits**, billed separately. Default model Opus 4.8. |
| **Triage Intelligence** (LLM duplicate + relationship detection, auto-apply properties) | **OUT, for now** | Business/Enterprise only. Workspace is 2 users; plan tier needs confirming. |
| **Open issue in coding tool** (`W` `O` / `Cmd+Opt+.`, custom prompt template) | **IN** | Free, local, launches Claude Code on the subscription. |

So Linear is the **board and the queue**. The **thinking runs locally** on the
subscription. Anything that needs an LLM verdict happens in `claude -p`, never in
Linear's AI.

**And the scheduler is launchd, never cron (ASK-150).** Every `claude -p` step below
depends on this. cron runs from a bare environment with no keychain access, so
subscription auth fails — probed 2026-07-23, `keychain_read_rc=44` plus
`{"is_error":true,...}` (`reddit-build-radar/logs/cron-probe/result.txt`). launchd
jobs do have keychain access, which is why every working `claude -p` job in this
fleet is a LaunchAgent. Building any part of this design on cron would fail at
runtime with an error that reads like a bad prompt rather than a bad scheduler.
`fleet-health-daily.py`'s `cron-shells-claude` detector files an issue for any
crontab line that shells `claude`, so the next scheduler choice cannot re-learn
this the slow way.

## The engine already exists

`q-system/.q-system/scripts/open-loops-heartbeat.sh` is the pattern, already in
production under `com.kipi.openloops-heartbeat.plist`:

- runs `claude -p "<prompt>" </dev/null` headless, per instance, on the subscription
- `timeout 1800` per instance so a runaway agent cannot spin
- Slacks the founder via `slack-notify.sh` on failure **and only on meaningful change**
- logs every run centrally; `run-step-audit.py` audits the steps afterward

**This design does not build a new worker. It gives that worker a better queue.**
Today it reads `open-loops.json`. Tomorrow it reads Linear.

That also satisfies `feedback_fleet_homogeneity`: one canonical engine, not a second
autonomous runner alongside the first.

## Architecture

```
  INTAKE                QUEUE              WORKER               GATE
  ------                -----              ------               ----
  reddit-build-radar    Linear             linear-worker.sh     prd-os
  tool-radar-score      (ASK team,         (launchd, per-repo)  /issue-verify
  capability-map-gen    project per repo)  claude -p headless   /issue-closeout
  founder's brain            |             claim -> worktree    receipts
        |                    |             -> PR -> release          |
        +---> dedup gate ----+                    |                  |
              (kipi-key +                         +---> Slack ONLY on
               capability-overlap.py)                   decision-needed
```

### 1. Intake — how work gets onto the board

Three producers, one gate.

- **`reddit-build-radar`** (`com.cole.reddit-radar-daily`, `com.cole.tool-radar-score`)
  already finds tools daily. Today its output dies in a file.
- **`capability-map-gen.py`** already finds unwired engines across 25 repos.
- **The founder**, via `kipi linear issue "<title>"`.

All three go through the same chokepoint: **`kipi linear create`**, which refetches
the remote guard and refuses anything whose `kipi-key` already exists. That is the
single-writer discipline the fleet already uses everywhere else.

**The tool-finder flow, concretely** (the founder's own example):

1. `reddit-build-radar` finds a candidate tool.
2. A scoring pass writes a `kipi-key` of `tool-radar/<tool-slug>` — so the same tool
   found twice, on any day, from any subreddit, is ONE issue forever.
3. `kipi linear create` files it into the **`tool-radar` project** as an
   *evaluation* issue carrying the rubric (what it does, what it would replace,
   what it costs, what it duplicates in the fleet).
4. The worker picks it up like any other issue and does the evaluation — the same
   read-the-code evaluation done for cyrus/OpenSwarm on 2026-07-26.
5. **If the verdict is adopt**, the closing step runs `kipi new <path> <name>`,
   which already creates a repo with the full founder OS, and `kipi linear create`
   opens that repo's Linear project. Repo and project are created by the same
   command that recorded the decision.

Nothing here needs the founder present. The only Slack ping is at step 5, because
creating a repo is the one irreversible act in the chain.

### 2. Queue — Linear is the state machine

Already specified in `q-system/output/plans/linear-sdlc-standard-2026-07-26.md`
(§3 States, §4 Definition of Ready, §5 Definition of Done). The worker only ever
picks up issues that satisfy **Definition of Ready**, which is the mechanism that
stops it flailing on vague work:

> Outcome · Files · Reproducer-or-check (observed red for a defect) · Blast radius · Not-doing

An issue without a DoR is not workable. That is a feature: it is the difference
between "agents get things done in the background" and "agents produce plausible
garbage in the background".

**Where the LLM judgment happens:** a nightly `claude -p` pass that reads Backlog
issues lacking a DoR and *drafts* one, leaving the issue in Backlog with a comment.
The founder promotes to Todo, or a rule does. Drafting is cheap; promoting is the
decision.

### 3. Worker — `linear-worker.sh`, modeled on the heartbeat

Per repo, on a **launchd** schedule — step 3 shells `claude -p`, so cron is ruled
out by ASK-150 (no keychain, auth fails):

```
1. kipi linear claim <ASK-n> --agent linear-worker --session <launchd-run-id>
     exit 3 = another session holds this tree -> skip, no error
2. git worktree add (the claim's refusal message already recommends this)
3. claude -p "<prompt>" --allowedTools ... --permission-mode acceptEdits </dev/null
     under `timeout 1800`, exactly as the heartbeat does today
4. push branch, open PR, comment the PR link on the issue
5. kipi linear release <ASK-n>   (at PR-open, so a reviewer can take it)
```

Why the claim lock matters here specifically: multiple repos can be worked in
parallel, and `linear-claim.py` makes the working tree the resource, refusing a
second session in the same checkout with exit 3. Parallel workers are safe by
construction rather than by scheduling luck.

**The prompt loads the existing discipline** rather than restating it: the issue
body, `/issue-start` (which loads `fable-discipline`), and the repo's CLAUDE.md.
No new instruction budget is spent — the budget is already FAILING at 513/300, so
a new always-on rule would require trimming an existing one, which is a founder
decision.

### 4. Gate — prd-os stays exactly where it is

The worker cannot close an issue. It can only open a PR. Closing runs through
`/issue-verify` and `/issue-closeout`, which already refuse without receipts, and
`prd_runner.py gates run` stays red while any spillover item is open.

This is the part neither cyrus nor OpenSwarm has, and the reason neither should own
the loop. **The autonomy is in the execution; the refusal stays in the gates.**

### 5. Duplication — use the fleet's own engine, not Linear's paid one

The founder's ask: *"identify duplication between projects and issues so we don't
relearn things."* Three layers already exist:

| Layer | Mechanism | Status |
|---|---|---|
| Same capability, same repo | `kipi-key` dedup, remote-marker guard | **built, proven on 31 live objects** |
| Same capability, different repos | `capability-overlap.py` — cross-repo divergence + collision | **built** |
| Same *problem*, different words | semantic similarity | **gap** |

The third is what Linear's Triage Intelligence sells. Two ways to get it on a
subscription:

- **Local:** a `claude -p` pass over open issue titles+bodies, emitting suspected
  duplicate pairs as a Linear comment with `relatedTo` set. Costs subscription
  tokens, runs nightly, no plan upgrade.
- **Linear:** enable Triage Intelligence (needs Business/Enterprise and turning
  `triageEnabled` on for team ASK, currently **false**).

Recommend the local pass first: it reuses the engine already in place, and its
output is auditable in the repo rather than inside Linear's black box.

### 6. AUDHD layer — the founder remembers nothing

Enforced by existing code, not by intention:

- **`slack-notify.sh` is the only ping channel.** `founder-notifications.md` already
  bans osascript (silently dropped from a background process). Ping ONLY on:
  decision-needed, an irreversible act (new repo), or a run that failed. Never on
  routine progress.
- **The fleet-loop board** (`reference_fleet_loop_board`) is the glanceable
  "what shipped / what's open" view. It is the AUDHD stand-in for reading a backlog.
- **Every issue carries Energy mode + Time Est** (`audhd-executive-function`), so
  when the founder *does* look, the board is pickable rather than a wall.
- **`launchd-health-check.py`** already watches for silently dead jobs. Autonomy
  that dies quietly is worse than no autonomy.

### 7. Where Notion stays, and where Linear takes over

They are not the same system and must not be merged:

| Domain | Owner | Why |
|---|---|---|
| Software work: issues, PRs, repos, capabilities | **Linear** | it is the dev board |
| Relationships, pipeline, deals, client deliverables | **Notion** (via cole-gtm / ASK consulting) | Cole is the fleet's single GTM brain (`project_gtm_consolidation_ask_to_cole`); deal state lives in `cole-gtm/.../deals/` |
| Decisions, canonical positioning | **the repo** (`canonical/decisions.md`) | already origin-tagged and lint-gated |

Rule: **an item exists in exactly one system.** A GTM task that requires code
becomes a Linear issue that *links back* to the Notion page. No mirroring — a
mirror is the duplication the founder is trying to eliminate.

## Loop exits (audited against `.claude/rules/loop-exits.md`)

The fleet's own 8-exit checklist, applied to `linear-worker`:

| Exit | Covered by |
|---|---|
| 1 goal met | `/issue-verify` required_checks + `prd_runner.py gates run` |
| 2 turn cap | `token-guard.py` `VOLUME_CEILING=50`, fires in autonomous runs |
| 3 budget | token-guard call/agent/MCP proxies |
| 4 wall clock | `timeout 1800` per issue, as the heartbeat does |
| 5 no progress | token-guard's 6 detectors (retry hash, edit spiral, stall) |
| 6 human interrupt | `destructive-op-deny.sh`; the worker cannot merge |
| 7 error threshold | `self-healing-retry.md` 3-attempt cap; environmental stops at 1 |
| 8 external event | the Linear issue's own status |

**Gap to close before shipping:** exit 7 needs a per-issue failure counter so a
poisoned issue is not retried nightly forever. OpenSwarm's `autonomousRunner.ts`
solves this well — `MAX_RETRY_COUNT = 4` with backoff, and crucially it separates
**infra_error from task failure** so an auth expiry does not burn the issue's
budget, then marks the issue STUCK at the cap. Copy that taxonomy; a `swarm:stuck`
equivalent label makes a dead-end visible on the board.

## Build order

1. **Turn on "Open in coding tool"** (Settings → Code & reviews → Claude Code) and
   write the prompt template. Zero code, immediate value on 142 issues. *~20 min.*
2. **`linear-worker.sh`** — clone `open-loops-heartbeat.sh`, swap the queue for
   `kipi linear` + the claim lock, keep the timeout/Slack/step-audit skeleton. One
   repo first, `--only` style. *~half a day.*
3. **Per-issue failure counter + stuck label** (exit 7). Do NOT ship step 2 without
   it. *~2 h.*
4. **Nightly DoR drafter** — `claude -p` writes a Definition of Ready onto
   Backlog issues that lack one. *~2 h.*
5. **Semantic duplicate pass** — nightly, emits `relatedTo` + a comment. *~3 h.*
6. **Radar → Linear intake** — `tool-radar/<slug>` keys, evaluation rubric issue,
   and `kipi new` on an adopt verdict. *~half a day.*

## Honest risks

- **`validate` is red on `main`.** An autonomous worker opening PRs into a repo
  whose required check cannot pass means every PR merges by bypass or not at all.
  **Fix the 46 containment findings before step 2**, or the loop produces work that
  cannot land.
- **Subscription rate limits** are the real ceiling on how much this can do per
  night. Unknown until measured. Start with one repo and read the logs.
- **A worker that opens PRs nobody reviews is a queue, not progress.**
  `loop-exits.md` names this: cost per *accepted* change is the metric, and the
  fleet has no accepted-change signal because the heartbeat self-merges. Decide the
  review posture before scaling past one repo.
- **`triageEnabled=false` on team ASK.** Several Linear automations (triage rules,
  Triage Intelligence) do nothing until that is on, and the paid ones need a plan
  check.
