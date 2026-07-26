# Continuation prompt: fleet-wide Linear rollout (ASK-113)

Written 2026-07-26 for a fresh session. Paste the whole thing.

---

You are continuing autonomous work in `/Users/assafkipnis/projects/kipi-system`
(the kipi skeleton repo). Tracking epic: **ASK-113**.

## Precondition — check this first, and STOP if it fails

Confirm the Linear MCP tools exist (`mcp__linear__list_teams` etc.; they may be
deferred, load via ToolSearch). If Linear is not reachable, STOP and say so. Do
not plan against a server that never authenticated, and do not build a local
substitute for it.

## The goal (founder directive 2026-07-26, autonomous end to end)

1. A Linear **project per instance repo**, each holding that repo's capability
   issues.
2. A **deterministic mechanism** so that building anything in an instance creates
   the appropriate issue in that instance's project.
3. **`kipi new` creates a Linear project** for every new instance.
4. Then, as a senior staff engineer, go through **every issue in every project**
   and mark it accurately: done / needs work / recorded, with evidence.
5. Then find **overlaps and collisions** across projects.
6. Research SDLC best practices — **light, not a token sink**. Where findings
   conflict with the instructions above, **adjust toward best practice and state
   plainly what you changed and why.**

The standing rule from here on: everything goes through Linear, and projects are
run to SDLC best practice.

## State as of 2026-07-26 (verified, do not re-derive)

**Linear**
- Workspace has exactly one team: `ASK_Consulting`, key `ASK`, id
  `a75b9b87-bfdf-4fb7-bff3-a5a1a2a6946f`.
- Project **`kipi-system`** exists: id `00bec4fd-cdd1-4d5a-992a-4ae3319c2d0a`,
  url `https://linear.app/ask-consulting/project/kipi-system-c0944236257f`.
  Holds **61 issues, ASK-51 … ASK-113**, one per capability of the skeleton repo.
- Projects **`CAP-01` … `CAP-45`** already exist and map **cole-gtm**, not
  kipi-system. Created by a parallel session 2026-07-26 ~18:00 UTC. Founder
  decision: **leave them alone, build alongside.** Do not "clean them up."
- Source of truth for the kipi-system issues:
  `q-system/output/plans/kipi-capability-map-2026-07-26.json` — 59 capabilities,
  each with a `linear` field carrying its ASK id. Use this as the shape template
  for other repos.

**The linear-first gate (already shipped, commit `b23fdfd`, ASK-112)**
- `q-system/.q-system/scripts/linear-issue-ref-check.py` runs as a lefthook
  `commit-msg` command. It exits 1 when a commit message names no issue id.
- Format: an uppercase id anywhere in the message (`ASK-51`), or
  `[no-issue: reason]` which is allowed and appended to
  `q-system/output/linear-bypass.jsonl`.
- Test: `q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh`, 17
  cases, registered in `capability-manifest.json`.
- Rule doc: `.claude/rules/linear-first.md`, **paths-scoped** (see the ratchet
  constraint below).
- `q-system/hooks/auto-commit.py` declares `[no-issue: auto-commit safety net]`
  because it fires unattended and cannot know the session's issue.
- **Every commit you make this session needs an issue ref.** Use ASK-113 or a
  more specific issue you create.

**Repo**
- 24 instances in `instance-registry.json`, all paths verified present.
- `kipi check` (`python3 validate-separation.py 5`) is **RED**: 170 PASS, 3 FAIL,
  1 WARN. Fails are Gate 1.2 KTLYST refs (1 file), Gate 1.3b semantic containment
  (11684 findings), Phase 1 skeleton sweep (1 file). **Pre-existing. Not yours to
  fix as a side effect** — ASK-58 and ASK-59 own them.
- `capability-gate.py` is GREEN, 56 tests.
- 5 commits unpushed at handoff; ask before pushing if the founder has not said.

## Hard constraints — read before writing anything

**1. Linear objects are effectively permanent.** `mcp__linear__*delete*` is blocked
by `~/.claude/hooks/destructive-op-deny.sh` and an agent cannot set
`ALLOW_DESTRUCTIVE=1` for itself. Archive is equally out of reach. **Therefore:
build and prove the dedup/idempotency key BEFORE any bulk creation.** A duplicate
you create is a duplicate the founder lives with. This is the single most
important ordering decision in this work.

Design the key so a re-run is a no-op: a stable identifier per unit of work
(suggested: `<instance>/<capability-slug>`), recorded in a local ledger and
checked against existing issues before every create. Prove it with a test that
runs the creator twice and asserts the second run creates nothing.

**2. Scale is real.** 24 instances at 20-60 capabilities each is roughly 500-1500
issues. `token-guard.py` enforces `MCP_RATE_LIMIT=30/60s` and blocks at 50 tool
calls without a commit (`VOLUME_CEILING=50`, resets on a real commit). This work
**spans multiple sessions.** Build for resumption from the start: a per-instance
ledger, a commit after each instance completes, and a way to answer "which
instances are done" without re-querying everything.

Do not blindly create 1500 issues. Scope per instance to its real capabilities,
and `log` what you deliberately left out rather than silently truncating.

**3. A shell script cannot call the Linear MCP server.** MCP tools are available
to the agent, not to `kipi-new-instance.sh`. So goals 2 and 3 cannot be a direct
API call from a bash hook unless you wire a real Linear API key (there is none in
`~/.config/kipi/` today — check before assuming). The likely correct shape is a
**queue file** that scripts append to and an agent-side drain step consumes, so
the deterministic part is the capture and the API call happens where credentials
exist. Decide this deliberately and record the decision.

**4. Prompt-only enforcement is blocked.** `prompt-only-enforcement-guard.py`
(PostToolUse) exits 2 on any rule or doc claiming enforcement without naming a
hook, script, test, or validator. Name the executable inline. It blocked this
work's own first draft; expect it.

**5. The instruction-budget ratchet blocks new always-on rules.** The blocker is
`instruction-budget-audit.py --ratchet`, a lefthook pre-commit command: always-on
total is 513 against a 300-line target and that script exits 1 on any regression.
A new always-on rule requires trimming an existing one, which is a founder call.
Paths-scope new rules the way `folder-structure.md` (274 lines) and
`loop-exits.md` (127) do. Enforcement lives in the hook, so it holds whether or
not the doc is loaded.

**6. Propagation rules.**
- Root `CLAUDE.md` does **not** reach instances. `.claude/rules/*.md`,
  `.claude/agents/*.md`, `q-system/CLAUDE.md`, `plugins/*/` do, via `kipi update`.
- A new fleet hook must be added to BOTH `.claude/settings.json` and
  `settings-template.json`, or `settings-template-sync-check.py` blocks it.
- `kipi update` runs `rsync --delete`: a script written into an instance's
  `q-system/` subtree gets clobbered. Instance-local automation goes at repo root.
  `instance-automation-guard.py` enforces this.
- Plugins run from the marketplace clone `~/.claude/plugins/marketplaces/`, not a
  project's `plugins/` dir. Editing the latter is dead text.

**7. Verification is not optional.** Reproducer first: write the failing test,
show it red, then make it green, and report the command and the result. "Should
work" does not close anything. Codex is out of credits until 2026-08-24 and Gemini
needs auth, so the review substitute is a Claude subagent required to ship a
runnable repro per finding.

**8. Capture, never mention.** Anything real you find and are not fixing goes to
the spillover ledger:
`python3 plugins/prd-os/scripts/prd_runner.py spillover add --source ASK-113 --desc "..."`.
A sentence in chat is a silent drop.

## Suggested order (deviate if you have a better reason, and say so)

0. Preconditions. Read `q-system/memory/last-handoff.md` and the capability map.
1. **SDLC research, light.** Then write the standard to
   `q-system/output/plans/` — project/issue taxonomy, states, definition of ready,
   definition of done, estimation, how epics relate to issues, what a good issue
   contains. Reconcile against the founder's instructions and **state every place
   you adjusted their instruction toward best practice.**
2. **Idempotency foundation + its test.** Prove double-run is a no-op. Nothing
   bulk happens before this is green.
3. **One instance end to end** as the pattern (suggest `4_points_consulting` —
   the production investigation OS, 22 commands, real complexity). Get the shape
   right on one before multiplying by 24.
4. **The remaining instances**, resumable, committing per instance.
5. **Auto-issue-on-build mechanism** + test.
6. **`kipi new` → project** + test.
7. **Sr staff eng triage pass**, every issue every project, evidence-backed.
8. **Overlap and collision analysis** across projects; report duplicated
   capabilities, conflicting ownership, and where two instances solved the same
   problem differently. This is where the real value is — the fleet-homogeneity
   principle says a shared capability belongs in ONE canonical source, and this
   pass is how you find the violations.
9. Fold the standard into an enforced rule + gate. Update `last-handoff.md` once,
   at the end.

## Autonomy

The founder authorized this end to end. Do not ask permission to continue between
phases, do not use handoff-doc updates as a stopping ritual, and do not convert a
status answer into a permission request. Pick the next most leveraged thing and
start it.

Still requires an explicit founder OK: force-push, branch deletion, destructive
resets, anything the destructive-op hook blocks (including Linear deletes), and
trimming an existing always-on rule to make room for a new one.

Report honestly. If a phase is blocked, finish everything that is not blocked,
then say exactly what you left and why.
