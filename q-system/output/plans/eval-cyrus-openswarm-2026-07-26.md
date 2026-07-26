# Evaluation: cyrus vs OpenSwarm, for the fleet + Linear work (ASK-113)

Read the code, not the READMEs. Both cloned at 2026-07-26 and inspected at source
level. Neither is vapor: both are real, actively released systems.

## What each one actually is

### cyrus — `cyrusagents/cyrus`, Apache 2.0, ~100k LOC TypeScript

A **hosted webhook worker** that turns Linear issues into agent runs.

| Layer | Evidence |
|---|---|
| Entry | `packages/edge-worker/src/EdgeWorker.ts` — 7,497 LOC monolith |
| Ingress | `SharedApplicationServer.ts` runs Fastify + `CloudflareTunnelClient`; needs a **public URL** for Linear/GitHub/Slack webhooks |
| Trigger | `@mention` of the bot, or assignment (`EdgeWorker.ts:1258` "Only trigger on comments that mention the bot") |
| Multi-repo | `RepositoryRouter.ts` — 3-priority routing: **routing labels → projects → teams**, with a catch-all repo |
| Isolation | `GitService.ts` + `WorktreeIncludeService` — **one git worktree per session**. There is NO mutex anywhere in the codebase |
| Runners | `claude-runner` (uses `@anthropic-ai/claude-agent-sdk`), plus `codex-runner`, `gemini-runner`, `cursor-runner` |
| Transports | linear, github, gitlab, slack |
| Auth | `session-env.ts` honors `CLAUDE_CODE_OAUTH_TOKEN` **or** `ANTHROPIC_API_KEY` — subscription auth works |
| Extras | `EgressProxy.ts` (911 LOC), sandbox requirement probing, attachment service, skills plugin resolver |

**The architectural fact that matters:** cyrus has no claim-lock because it does not
need one. Every session gets its own worktree, so two sessions cannot share a
working tree by construction. That is the structural answer to the problem our
`linear-claim.py` solves by locking — and it is the same remedy our own refusal
message already recommends ("use a separate git worktree").

### OpenSwarm — `unohee/OpenSwarm`, MIT, ~133k LOC TypeScript

A **local CLI autonomous orchestrator** that pulls Linear issues and works them.

| Layer | Evidence |
|---|---|
| Entry | `bin: openswarm` → `dist/cli.js`. No server, no ingress required |
| Loop | `src/automation/autonomousRunner.ts` — 2,625 LOC scheduler |
| Linear | `src/linear/linear.ts` — 1,642 LOC. `getNextBacklogIssue`, `getInProgressIssues`, `updateIssueState`, `logWorkStart` / `logProgress` / `logWorkComplete` / `logBlocked`, `parseBlockerIdentifiers`, `STUCK_LABEL = 'swarm:stuck'`, per-day issue rate limiting |
| Isolation | `src/support/worktreeManager.ts` — worktree per issue, guarded by a **SQLite `BEGIN IMMEDIATE` transaction** per issueId (`LIFECYCLE_LOCK_DIR`, lock db at 0o600 in the git common dir) |
| Resumability | `src/automation/runLedger.ts` (1,378 LOC), `src/registry/sqliteStore.ts` |
| Loop exits | `MAX_RETRY_COUNT = 4` with backoff; distinguishes **infra_error vs task failure** so an auth/timeout failure does not burn the task's retry budget; marks STUCK at the cap |
| Adapters | `src/adapters/claude.ts:71` → `command: 'claude'` — **shells the CLI**, so the founder's subscription is used, same as our `claude -p` pattern. Also codex, gpt, openrouter, ollama, lmstudio, llama.cpp |
| Tests | **241 test files** |
| Config | `config.yaml`: `linear.apiKey`, `linear.teamId`, per-agent `linearLabel`, `projectPath`, heartbeat interval |

**Maturity risk:** single maintainer. 49 of the last 50 commits are Heewon Oh /
unohee (same person), 1 dependabot. v0.19.10. The test discipline is real, but the
bus factor is 1.

## Fit against what we are actually doing

Our stack: 25 repos, one Linear team (ASK), a project per repo, queue-and-drain
because bash has no Linear key, `linear-claim.py`, and prd-os / kipi-dsse for
gated PRDs, findings, receipts, spillover, and the capability gate.

### 1. Neither one replaces prd-os / kipi-dsse

Different layer. cyrus and OpenSwarm are **execution orchestrators** (get issue →
run agent → push → comment). prd-os is a **governance and evidence layer** (gated
approval, findings triage with dispositions, closure receipts, spillover ledger,
bypass gates). Nothing in either repo does receipts-with-refusal. Adopting either
wholesale would mean running two systems whose state does not meet.

### 2. Both would obsolete queue-and-drain — but so would a Linear API key

Queue-and-drain exists for exactly one reason: **no Linear API key, so bash cannot
reach the MCP server.** Both tools require a Linear API key (`LINEAR_API_KEY` /
`initLinear(credential, team, isOAuth)`).

That is the finding worth acting on independently of adoption: the constraint that
shaped our whole design is a config decision, not a law. Creating one Linear API
key would let `linear-sync.py` create issues directly and delete the entire
capture-then-drain round trip. The 29 uncreated issues become one script run.

### 3. The claim-lock comparison is unflattering to ours, in a useful way

| | ours (`linear-claim.py`) | OpenSwarm | cyrus |
|---|---|---|---|
| Mechanism | O_EXCL guard file + JSON lock | SQLite `BEGIN IMMEDIATE` per issueId | none — worktree per session |
| Resource | the working tree | the issue | n/a |
| Crash in critical section | leaked guard; we had to add pid-liveness + reclaim after review found it bricked the tree | SQLite rolls back the transaction natively | n/a |
| Stale claim | `--break-stale --holder <session>` CAS | transaction ends with the process | n/a |

SQLite `BEGIN IMMEDIATE` gets crash recovery for free — it is a database
transaction, so a killed process releases the lock with no guard file to leak, no
pid liveness probe, and no `--break-stale` escape hatch to get wrong. Our
adversarial review found three separate defects in the hand-rolled version
(leaked guard bricking the tree, `--break-stale` stealing live claims, cwd
fallback granting every session). All three are structurally absent in the SQLite
approach.

### 4. What each is good at that we do not have

**cyrus:** label/project/team → repo routing across a fleet (`RepositoryRouter`).
That is the exact shape of our 25-repo, one-team, project-per-repo layout, and we
have nothing like it. Also: @mention as a trigger, and a genuine multi-runner
abstraction (claude/codex/gemini/cursor) that would have made the "Codex is out of
credits" problem a config change instead of slice 0.

**OpenSwarm:** the autonomous scheduler's failure taxonomy —
**infra_error vs task failure**, so an auth expiry or timeout does not consume the
task's retry budget. Ours says the same thing in `self-healing-retry.md` rule 5
(environmental-trigger stops on attempt 1) as prose; theirs is a branch in
`autonomousRunner.ts:536` that a test can fail on.

Same contrast on close discipline. `linear.ts` `STUCK_LABEL = 'swarm:stuck'` plus
`logBlocked()` write a dead-end marker onto the Linear issue from
`autonomousRunner.ts:746` when the retry cap is hit — a code path, so an abandoned
task is visible on the board without anyone remembering to mark it. Our §3.1
close-discipline rule is the same intent with no such code path behind it: I wrote
it today and said in the same commit that nothing checks it. That gap is real and
is the honest argument for reading their implementation before writing ours.

## Recommendation

**Do not adopt either wholesale.** Both assume they own the execution loop; ours
is owned by prd-os and the gates, which is the part that is actually differentiated
and which neither replaces.

Three things worth doing, in order of value per hour:

1. **Create a Linear API key.** Removes the constraint behind queue-and-drain,
   unblocks the 29 uncreated issues and Goal 4's 106-issue triage as script runs
   rather than agent sessions. Independent of either tool. ~15 min.
2. **Replace our lock's guard file with SQLite `BEGIN IMMEDIATE`.** Deletes the
   guard-leak, pid-liveness, and `--break-stale` complexity that review forced us
   to add. Keep our (agent, session) identity model and the remote-state check.
   ~2 h including tests.
3. **Steal cyrus's routing shape** (labels → projects → teams → catch-all) if and
   when issues need to route to repos automatically. Not needed today; we already
   know which repo an issue belongs to via the dedup key.

**Pilot-worthy, not adopt-worthy:** OpenSwarm on ONE low-stakes repo, to see
whether its scheduler + Linear logging beats our morning pipeline for unattended
work. Its `claude` adapter shells the CLI, so a pilot costs subscription tokens,
not API spend. Bus factor 1 is the reason it stays a pilot.

**cyrus is the wrong shape for us today** for one concrete reason: it needs public
webhook ingress (Cloudflare tunnel or equivalent) and a long-running server. Our
fleet is local-first on launchd with no ingress. That is a real infrastructure
commitment, not a config flag — and the thing it buys (webhook-latency triggering
off @mentions) is not a problem we currently have.

## What I did NOT verify

- Neither was run. This is a source read, not a bake-off. No claim here about
  whether either actually works end to end.
- I did not audit either for supply-chain risk (dependency count is large in both:
  OpenSwarm pulls LanceDB, apache-arrow, transformers, discord.js, better-sqlite3).
  Running either against real repos with real credentials deserves that audit
  first.
- Shallow clones (depth 50), so "contributor" counts reflect recent history only.
