# Auto-capture referee: senior-staff finish decisions (2026-07-04)

Delegated call: "make these decisions as senior staff security engineer, finish
end to end." Recorded here as the durable checkpoint.

## The reframe that drove every decision

A wiring audit found the feature is **correctly wired but dormant by design**.
`memory_outcomes` (parent PRD, finding-1) scores ONLY `q-system/memory`. That dir
holds 4 session-state files (`last-handoff`, `marketing-state`, `morning-state`,
`article-flow`) and **zero slug-memories**. The founder's real memories
(`feedback_*`, `project_*`) live in the auto-memory store
(`~/.claude/projects/<project>/memory/`), which is the explicitly-named **v2,
out of scope**. So `outcomes.jsonl` and the score sidecar never populate: the
referee has nothing in scope to score.

Implication: widening the recall set (the earlier "#3") does not help, because the
scored store is empty of memories regardless of how broadly we surface.

## Decisions

### #1 session_id disconnect — FIXED, shipped
`resolve_session_id()` read `CLAUDE_SESSION_ID`; the real hook var is
`CLAUDE_CODE_SESSION_ID`. Producer/consumer never agreed -> capture recorded
nothing. Fixed (PR #8), regression-tested, propagated, verified on 4_points
(`MATCH: True`). RCA: `output/rca/rca-autocapture-session-id-disconnect-2026-07-04.md`.

### #3 recall breadth / proxy semantics / v2 scope — DECIDED: no bolt-on
The real unlock is scoring the auto-memory store (v2). An automated proxy that
promotes/demotes the founder's PERSISTENT cross-session memories (which shape
every future session, in every instance) is a high-blast-radius write path. A
security engineer does not bolt that onto a "finish it" mandate — see the
PocketOS 2026-05-17 scar in the global rules (agent expanded scope to a
production store under pressure, caused damage). v2 gets its own PRD with a
threat model. NOT done now.

Also deferred to that PRD / design-partner tuning (unchanged): the proxy
coarseness — "surfaced-but-unread = dead_end" would demote healthy `preferred`
memories from mere disuse (a data-integrity risk to tune against real signal, not
guess blind), and shell-read files uncounted (sp-cac8540c).

### #2 corrected-path trigger — BLOCKED (environmental), founder-gated
The learn-from-correction SKILL section loads from the one per-machine
marketplace clone, 33 commits behind main. Refreshing it fails: Claude Code's
`known_marketplaces.json` stores every `installLocation` under `/Users/assafkip/`
(a symlink to `/Users/assafkipnis/`), and the marketplace validator does a string
prefix check that rejects the symlink form. The sanctioned fix
(`claude plugin marketplace remove kipi && re-add`) risks cascade-uninstalling the
entire kipi plugin system, so it is founder-gated. The deterministic scripts work;
only the skill TRIGGER is dormant, and the feature is dormant anyway (see reframe).

### #4 stale recall buckets — DEFERRED (unreachable)
The producer writes nothing while the scored store is empty, so the leak cannot
trigger. Cheap to bound when v2 lands.

## What "finished" means here (honest)

Everything safely finishable is finished: the one real bug (#1) is fixed and live.
The two paths to actual value (#2 marketplace config, #3 v2 scope) are each
deliberate, high-blast-radius decisions correctly declined for autonomous
execution and surfaced with exact remediation. The feature is production-correct
and dormant-by-design pending a v2 scope decision.

## The real next step (founder greenlight)

Write `prd-memory-autocapture-v2` (score the auto-memory store), with: a threat
model for automated writes to persistent memory, an opt-in/allowlist per memory
class, the dead_end-vs-disuse semantics fix, and a live first-session smoke. This
is the deliberate PRD the value depends on — not a same-session bolt-on.
