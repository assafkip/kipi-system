# Terminal-state redrive: every dead end gets a machine consumer

Written 2026-08-01. For prd-os execution (`/prd-start` against this file).
Founder directive: "this all should be done without me — it keeps pushing back
to me instead of following the rules."

## RECORDED FIRST: is this a solved problem?

**Yes — twice over. Adopt, do not invent.**

**In industry, the pattern is standard and has names:**

- **Dead-letter queue + redrive policy** (SQS `maxReceiveCount`→DLQ→redrive,
  RabbitMQ DLX, Kafka DLT): a message that fails processing lands in a *named
  queue with a consumer and an alarm*, never in a label nobody reads. Our
  `blocked:capability` with no consumer is a DLQ with no redrive and no monitor
  — the known anti-pattern.
- **Supervisor escalation (Erlang/OTP)**: a failed worker escalates *up a tree
  of supervisors* with bounded restart intensity. A human is not a tier until
  the root gives up.
- **Reconcile-requeue (Kubernetes controllers)**: "park forever" does not exist;
  every abnormal state is requeued with backoff. CrashLoopBackOff is a *state
  with a retry policy*, not a terminal label.
- **Incident escalation policies (PagerDuty)**: ordered tiers with timeouts;
  humans are tiers, plural, at the END.

**In this repo, it is partially solved, which proves the shape works here:**

| Terminal state (linear-worker.sh @ a5ac9c1) | Consumer today | Status |
|---|---|---|
| `needs-scope` (:1297) | `linear-dor-drafter.py`, nightly `com.kipi.linear-dor` | **SOLVED — the reference implementation** |
| no DoR on issue (ready() :311) | same drafter sweeps all DoR-less issues (drafter :342) | **SOLVED** (but see verification item V1) |
| automerge unarmed (:592) | re-armed on every subsequent run; pages once | **SOLVED** (self-heals) |
| `blocked:capability` (:1295) | none — comment names the founder | **ASK-281 filed** (Codex redrive; picker confirmed it ready 2026-08-01) |
| out-of-repo skip — 18 issues / 14 repos (ready() :309) | none | **UNSOLVED** (`sp-2b59e681`) |
| stuck after MAX_ATTEMPTS (:1253) | Slack page only | **UNSOLVED** |
| drift cap — unreviewed head (:853) | Slack page only | **UNSOLVED** |
| conflict cap — unmergeable (:875) | Slack page only | **UNSOLVED** |
| `owner:assaf` (:291) | the founder | **CORRECT** — the one legitimate human queue |

**Not previously fixed:** no plan in `output/plans/`, no rule, no script
enforces "every terminal state has a machine consumer." Greps for
dead-letter/redrive/escalation across scripts, rules, and prd-os: zero hits.
`loop-exits.md` answers "can the loop stop?" — it never asks "who acts next?"
The closest prior art in-repo is the capability manifest (declared-vs-actual +
test runner), which is the enforcement pattern to reuse.

## What / why

Nine terminal states; until this week eight routed to the founder or to nobody.
The founder is not an actor in this system. Build the missing consumers and one
deterministic validator so a founder-only dead end can never ship again.

## Approach (decision made, not asked)

DLQ-with-redrive semantics on the existing machinery: Linear labels stay the
queues, launchd jobs stay the consumers, one registry + one test become the
enforcement. No new orchestrator, no Temporal, no rewrite — the
`needs-scope → drafter` pair already proves the shape at fleet scale.

**Topology decision `[SYSTEM-INFERRED]`:** ONE registry-driven dispatcher that
iterates `instance-registry.json`, not 14 per-repo launchd jobs. Rationale:
per-repo jobs die silently (income-scanner scar, 6 days dark, 2026-07);
`ee55a80` already made the worker derive repo identity from the registry;
`launchd-health` watches one job well. Risk accepted: client repos behind one
process — mitigated by the per-repo project-scope filter that already exists
and per-repo worktrees.

## The build (prd-split into these issues)

1. **Registry + validator (the enforcement — build FIRST).**
   `q-system/.q-system/terminal-states.json`: one row per terminal state —
   `state`, `where` (script:line), `consumer` (job/script), `escalation`
   (ordered tiers), `founder_position` (must be `last` or `absent`).
   `test-terminal-states.sh`: RED if any row's only actor is the founder, RED
   if a named consumer script/job does not exist (the capability gate's
   inert-engine check is the pattern). Register in `capability-manifest.json`.
   Wire into `kipi check`.
2. **Out-of-repo consumer.** Dispatcher iterates registry repos that opt in
   (`work: true` flag in `instance-registry.json`); one issue per cycle
   fleet-wide, same daily cap. The 18 skipped issues become pickable.
3. **Stuck/drift/conflict escalation tier.** Before any "needs a human" page:
   ONE attempt by the alternate runner (Codex for a stuck issue mirrors
   ASK-281; alternate-engine review for drift; Codex rebase for conflict).
   Cap: one attempt per issue per state, ever — recorded in the attempts
   ledger. Page only after it, and the page says what the machine tried.
4. **ASK-281** (blocked:capability → Codex) — already filed, referenced here so
   prd-split does not duplicate it.

**V1 (verification item, step 1 scope):** ASK-274 sat 2 days with no DoR while
the nightly drafter was loaded. Determine why (project unset? bounded batch?
team filter?) and pin the answer with a drafter test case.

## Files to touch

- `q-system/.q-system/terminal-states.json` (new)
- `q-system/.q-system/scripts/test/test-terminal-states.sh` (new)
- `q-system/.q-system/capability-manifest.json` (+1 line)
- `q-system/.q-system/scripts/linear-worker.sh` (escalation tier at :853, :875, :1253)
- `kipi-dispatch.sh` + `instance-registry.json` (repo iteration, opt-in flag)
- `.claude/rules/loop-exits.md` (add the next-actor column, pointing at the registry)
- `linear-dor-drafter.py` (V1 test only)

## Acceptance criteria

- [ ] `test-terminal-states.sh` observed RED against a fixture row whose only
      actor is "founder", then GREEN against the real registry
- [ ] Every row in the registry names an existing, executable consumer (inert-engine
      check passes)
- [ ] A dry dispatcher run lists ready issues from ≥2 registered repos
- [ ] A stuck/drift/conflict page fires only AFTER the machine tier's attempt,
      and its text names what was tried
- [ ] V1 answered with a pinned drafter test
- [ ] `kipi check` fails if a new terminal state is added without a registry row
      (grep-based: "needs a human"/new label in worker ⇒ row required)
- [ ] All 17 `test-worker-refusal.sh` cases still green; `verify-codex-review-live.sh`
      still WIRED

## Not doing

- No new orchestrator/queue infra. Labels + launchd + registry only.
- Not granting any agent a permission it lacks (ASK-281's ban stands).
- Not touching `attempts-ledger.py` locking (`sp-626e9452`, founder-deferred).
- Not building per-repo launchd jobs.
- `owner:assaf` stays a founder queue — it is the designed one.

## Patterns to follow

`capability-manifest.json` + 3-convention test runner (declared-vs-actual);
`linear-dor-drafter.py` (the working redrive consumer, bounded + nightly);
`prd_runner.py gates run` (validators only grow); `self-healing-retry.md` rule 5
(environmental failures do not retry — the escalation tier must honor it).
