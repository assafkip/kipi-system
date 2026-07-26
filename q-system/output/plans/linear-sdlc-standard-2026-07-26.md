# The Linear SDLC standard for the kipi fleet

Written 2026-07-26 under ASK-113. Governs every repo in `instance-registry.json`
plus the `kipi-system` skeleton. This is the reference doc; the enforced slice is
named in "Enforcement" at the bottom and lives in scripts, not here.

---

## Part 0 — Where I adjusted the founder's instruction, and why

The directive said to research SDLC best practice and adjust where it conflicts,
stating the change plainly. Three conflicts. All three are adjusted.

### 0.1 Issue-first, not issue-as-receipt

**Directive:** "Every time we build anything, it creates the issue."

**Conflict:** that inverts the order. An issue created *after* a build is a
receipt. It records that something happened; it cannot specify, scope, review, or
make the work ready, because the work is already done. Every SDLC worth the name
puts the issue first: the issue is where scope is written down, argued with, and
declared ready — then the build references it.

**Adjusted to:** issue-first. Concretely:

- The unit of work opens as a Linear issue in `Todo` with a Definition of Ready
  (§4) satisfied. Then the build starts. Then the commit names it.
- `linear-issue-ref-check.py` (already shipped, commit `b23fdfd`) already enforces
  the correct direction — a commit must name an issue that already exists. Nothing
  about the gate changes.
- What was missing was not a receipt-generator. It was a **low-friction way to
  open the issue at the start of work**, so issue-first is the cheap path rather
  than the disciplined one. That is what the queue/drain mechanism (§0.2) is for.
- Retroactive filing still exists, but as a named, countable exception:
  `[no-issue: reason]` appends to `q-system/output/linear-bypass.jsonl`. Bypasses
  stay visible instead of becoming the norm.

**Net effect:** we build one mechanism (open-an-issue-fast) instead of two
(open-an-issue and also mint-a-receipt), and the mechanism pushes work in the
direction the gate already enforces.

### 0.2 Queue-and-drain, because bash cannot reach the MCP server

**Directive:** `kipi new` creates a Linear project; building in an instance
creates the issue.

**Conflict:** verified this session — there is no Linear API key anywhere in
`~/.config/kipi/` and no `LINEAR_*` environment variable. Linear is reachable only
through the MCP server, which is available to the agent, not to
`kipi-new-instance.sh`. A bash hook calling Linear directly cannot work today.

**Adjusted to:** split the mechanism at the credential boundary.

| Half | Where it runs | What it does |
|------|---------------|--------------|
| Capture | bash, no credentials | Appends one JSON line to a repo-root queue file. Deterministic, always succeeds, never blocks the founder. |
| Drain | agent, has MCP | Reads the queue, creates the Linear objects, writes back the assigned ids, marks lines drained. |

The deterministic guarantee is on the **capture** side: a build or a `kipi new`
cannot silently fail to record itself, because appending to a local file has no
network dependency. The Linear write happens where credentials exist.

**The alternative, if the founder wants it:** create a Linear personal API key,
drop it at `~/.config/kipi/linear-api-key`, and the capture side can call the
GraphQL API directly and skip the drain. That is a founder action (it is a
credential). Until then, queue-and-drain is the only shape that works. Recorded as
an open decision, not silently assumed.

### 0.3 Scoped issues in Linear, full inventory in the repo

**Directive:** a project per instance repo, "each holding that repo's capability
issues", then triage every issue in every project.

**Conflict:** 24 repos at 20-60 capabilities each is 500-1500 issues. Three
problems:

1. **They are permanent.** `mcp__linear__*delete*` and archive are both blocked by
   `~/.claude/hooks/destructive-op-deny.sh`, and an agent cannot set
   `ALLOW_DESTRUCTIVE=1` for itself. Every object created is an object the founder
   lives with forever.
2. **Linear's own guidance says don't.** The import docs
   (`https://linear.app/docs/import-issues`, "Pre-import best practices") tell you
   to ask whether data needs to be in Linear at all, and note that teams who start
   clean "start fresh with minimal clutter" rather than importing a full historical
   record.
3. **A tracker of already-done things is not a tracker.** 1400 issues in `Done`
   that nobody will ever groom turn the workspace into a database with a worse
   query language than `jq`.

**Adjusted to:** two tiers, each holding what it is good at.

| Tier | Lives in | Holds | Cost |
|------|----------|-------|------|
| Inventory | `CAPABILITY-MAP.json` committed at each repo root | **All** capabilities: name, layer, status, entry point, trigger, deps, evidence | Free, diffable, greppable, joinable across repos |
| Tracker | Linear project, one per repo | Only capabilities that are **actionable**: not-live, degraded, untested, or flagged by the overlap pass. Plus one anchor issue per repo. | Permanent, so kept deliberate |

**This strengthens goal 5, it does not weaken it.** The overlap-and-collision
analysis across 25 repos is a join over 25 JSON files. That is a script. Doing the
same analysis by querying 1400 Linear issues is slower, costs MCP calls, and
cannot be re-run in CI.

**What the founder still gets:** every repo has a Linear project. Every repo's full
capability list is written down and verified. Every capability that needs a human
decision is an issue with a status and evidence. The thing that shrinks is the pile
of `Done` issues describing things that were already working before this session
started.

**Estimate after adjustment:** roughly 8-20 issues per repo, ~200-400 total, versus
500-1500. The two projects that already exist (`kipi-system` 61 issues, `cole-GTM`
45 issues) are **left exactly as they are** — they are already filed and permanent,
and re-litigating them costs more than it returns.

### 0.4 A survey finding is one issue, not N

Added during execution, after the planner produced its first real numbers.

The first fleet-wide plan came to **347 issues**, and 25 of `4_points_consulting`'s
26 were the same sentence: "this engine has no test and no caller." That is not 25
decisions. It is one decision for the repo, made once with the whole list in view.

**Adjusted to:** `UNWIRED` findings collapse into a single audit issue per repo
carrying the full table, so nothing is lost (every script is still named with its
line count and why it was flagged). `NEEDS_WORK` and `BROKEN` stay individual,
because each of those is a distinct defect with its own fix.

Fleet-wide: **347 issues became 31.** An issue is now a unit of work rather than a
row in a survey, which is the actual SDLC principle underneath.

### 0.5 Maps live centrally, not at each repo root

Part 2 originally said each repo carries its own `CAPABILITY-MAP.json` at its root.
In practice they are generated into
`q-system/output/capability-maps/` in the skeleton instead, for three reasons: the
overlap join needs them in one place, writing them into 24 repos means 24 commits
in 24 repos for a regenerable artifact, and at 4.9MB they would churn every run.
They are gitignored and regenerate in about 25 seconds.

**The tradeoff, stated:** an instance cannot self-check its own map without the
skeleton present. If that becomes a real need, the generator already takes
`--out`, so writing a copy into a repo root is a one-line change.

### 0.6 One correction to the handoff state

The continuation prompt said "Projects `CAP-01` … `CAP-45` already exist". They are
not projects. `list_projects` returns exactly two: `kipi-system` and `cole-GTM`.
`CAP-01`…`CAP-45` are the title prefixes of the 45 capability issues *inside* the
`cole-GTM` project. That is already the correct shape, which means goal 1 is 2/25
done rather than 0/25 with 45 strays to work around. Standing instruction to leave
them alone is unchanged.

---

## Part 1 — Object model

Linear's hierarchy, and what each level means for this fleet. (Grounded in
`https://linear.app/docs/import-issues` and `https://linear.app/docs/linear-agent`:
one workspace per company; an issue belongs to exactly one team; a project may span
teams; initiatives are hand-picked groups of projects.)

| Linear object | Fleet meaning | Cardinality |
|---------------|---------------|-------------|
| Workspace | KTLYST Labs, all of it | 1 |
| Team | `ASK_Consulting` (`ASK`) | 1 today. Do not add teams to model repos — issue ids would fragment across key prefixes and cross-repo queries get harder. |
| **Initiative** | A persona: `consulting`, `cole-gtm`, `personal`, `micro-saas`, `intel`, `ktlyst-saas`, `skeleton` | 7, matching the directory personas |
| **Project** | **One git repo.** This is the load-bearing mapping. | 25 (24 instances + skeleton) |
| Issue | One unit of work inside one repo | ~8-20 per project |
| Milestone | A phase within a repo's work, when a repo has one | optional |
| Cycle | Not used. The fleet has one operator and no sprint cadence; cycles would add ceremony with no scheduling decision behind it. | 0 |

**Why project = repo and not project = capability-layer:** a repo is the unit that
has its own git history, its own `kipi update` propagation boundary, and its own
`CAPABILITY-MAP.json`. A layer (`L1 propagation`) spans repos and is better
expressed as a label. Repos are also the unit the founder actually navigates.

**Labels** carry the cross-cutting dimensions, because they can span projects where
a project cannot:

- `kind:capability` (the only `kind:` label created so far)
- `unwired` (engine with no test and no caller)
- `fleet-shared` — this capability exists in more than one repo (set by the overlap
  pass, §7)
- `canonical-source` — this repo is the ONE source for a `fleet-shared` capability
- `needs-evidence` — status is claimed but no command proves it

---

## Part 2 — Issue taxonomy and the dedup key

### 2.1 The dedup key is the whole ballgame

Linear objects are permanent here (§0.3). So every create is guarded by a stable
key, checked before the write, on every run.

```
key = <repo-slug>/<capability-slug>
```

- `repo-slug`: the `name` field from `instance-registry.json`, lowercased,
  non-alphanumerics collapsed to `-`. Example: `4_points_consulting` →
  `4-points-consulting`.
- `capability-slug`: the capability's `name`, same transform. Example:
  `kipi CLI` → `kipi-cli`.
- Full example: `4-points-consulting/case-intake`.

The key is written into the issue description as a fenced marker line so it
survives title edits and is greppable from a Linear query:

```
<!-- kipi-key: 4-points-consulting/case-intake -->
```

**Two independent guards, because one is not enough:**

1. **Ledger guard (fast path).** `q-system/output/linear-ledger.jsonl`, append-only,
   one line per created object: `{key, kind, linear_id, identifier, created_at}`.
   Checked first; if the key is present, skip without an MCP call.
2. **Remote guard (truth path).** Before any create, the existing issues of the
   target project are fetched once and their `kipi-key` markers parsed. A key found
   remotely is recorded into the ledger and skipped. This is what makes the system
   correct after a ledger loss, a fresh clone, or a parallel session.

The remote guard is why a lost ledger is recoverable and a duplicate is not created.

### 2.2 Title format

```
<CAP-ID> <Capability name>: <one-line what it does>
```

`CAP-ID` is per-repo sequential (`CAP-01`…), matching the convention `cole-GTM`
already established. Sequence is assigned from the `CAPABILITY-MAP.json` order and
frozen once written, so it is stable across re-runs.

---

## Part 3 — States

The `ASK_Consulting` team has 7 statuses. Mapped, with the rule for entering each:

| Status | Type | Means | Entry rule |
|--------|------|-------|------------|
| `Backlog` | backlog | Recorded, not ready. No one has written the DoR. | Default for anything filed by the drain without a spec |
| `Todo` | unstarted | **Ready.** Definition of Ready (§4) is satisfied. | A human or agent wrote the DoR fields |
| `In Progress` | started | Someone is building it now | A commit naming this id exists, or work is claimed |
| `In Review` | started | Built, awaiting the review substitute | Reviewer subagent invoked, findings not yet triaged |
| `Done` | completed | Definition of Done (§5) is satisfied **with a command and its output** | The evidence line is in the issue |
| `Canceled` | canceled | Won't do. Rationale required in a comment. | Terminal, with a reason |
| `Duplicate` | duplicate | Same key as another issue | Set `duplicateOf`; this is the *only* recovery for an accidental duplicate, since delete is blocked |

**`Duplicate` is the safety net.** Because `mcp__linear__*delete*` is hook-blocked,
a duplicate that does get created is marked `Duplicate` with `duplicateOf` pointing
at the survivor. It does not vanish, but it stops polluting counts and queries. This
is the recovery path, not a substitute for the dedup key.

### 3.1 Close discipline — a state means what it says

Close an issue only when the slice is actually complete. Do NOT close at session end
"for hygiene" while anything is still in progress.

Never end a session with an issue left `In Progress` under your name and no live
branch. Two ways out, both acceptable, one required:

- **Release it** — move it back to `Todo` and drop the claim, so the next session or
  reviewer can take it.
- **Record the blocker on the issue** — a comment naming what stopped the work and
  the exact next action, so `In Progress` stays truthful.

Why this is a rule and not a preference: the board is the fleet's only shared view of
what is being worked on. A `Done` that means "the session ended" and an `In Progress`
that means "abandoned three days ago" both destroy the one thing the board is for. A
stale claim is worse than no claim, because the claim-lock will refuse the issue to
the next agent on the strength of it.

Nothing enforces this today — no hook, script, or validator checks for an abandoned
`In Progress`. It is discipline, stated here so it is at least written down; the
claim-lock's stale-claim handling is where it would become deterministic.

---

## Part 4 — Definition of Ready

An issue may leave `Backlog` for `Todo` only when all five are true. Fewer than five
and it is not ready; say which one is missing.

1. **Outcome** — one sentence on what is true when this is done, in the founder's
   terms, not implementation terms.
2. **Files** — explicit paths that will be touched. Not "the updater"; the path.
3. **Reproducer or check** — for a defect, the command that currently fails. For a
   capability, the command that will prove it works. Named, runnable, and if it is
   a defect, **already observed red**.
4. **Blast radius** — does this propagate via `kipi update`? Is it skeleton-only or
   fleet-wide? Does it touch `.claude/rules/` (instruction budget) or
   `settings.json` (template sync)?
5. **Not-doing** — the adjacent thing this issue explicitly does not cover, so scope
   creep has somewhere to be refused to. Anything real that turns up goes to the
   spillover ledger, never a sentence in chat.

## Part 5 — Definition of Done

An issue may enter `Done` only with all four. This is the same bar the repo already
enforces in prose ("I ran X and got Y"); here it is the issue's exit condition.

1. **The command and its output.** Pasted into the issue. `python3 foo.py` → `17
   passed`. Not "tests pass". Not "should work".
2. **The reproducer is green** and was previously observed red (for defects).
3. **Wired end to end** — the `/wiring-check` bullets that apply: a new script is
   referenced from `settings.json` *and* `settings-template.json`, a new rule is
   auto-loaded, a new bus file has a producer and a consumer, and the load-path is
   proven (the running system loads the copy that was edited, not a marketplace
   clone of it).
4. **The commit names this issue id**, which `linear-issue-ref-check.py` already
   enforces at `commit-msg`.

**Anything found and not fixed is captured, not mentioned:**
`python3 plugins/prd-os/scripts/prd_runner.py spillover add --source <id> --desc "..."`.

**`Done` is earned by the four above, never by the clock.** Closing at session end
"for hygiene" while the slice is unfinished is a false receipt: it is the same defect
as stamping a review provenance that did not happen, just on the board instead of in
the ledger. If the four are not met when the session ends, the issue does not close —
it is released or the blocker is recorded on it (§3.1).

## Part 6 — Estimation

Estimates are **on**, in the small-but-real sense, and used for one purpose:
spotting an issue that is secretly a project.

| Points | Means |
|--------|-------|
| 1 | One file, one function, has a test already |
| 2 | A few files in one repo, needs a new test |
| 3 | Crosses a boundary: skeleton→fleet, or adds a hook, or changes a schema |
| 5 | **Too big. Split it.** A 5 is a signal, not a size. |

No velocity tracking, no burndown. A single operator with a variable-energy
schedule gets nothing true from a velocity number, and a false one invites the
urgency language the founder's rules ban outright.

## Part 7 — Overlap and collision analysis

The point of a per-repo `CAPABILITY-MAP.json` with a stable key. Run as a join over
all 25 maps, producing four findings classes:

| Class | Definition | Action |
|-------|------------|--------|
| **Duplicate** | Same `capability-slug` in ≥2 repos, same entry-point filename | Label `fleet-shared`; pick ONE `canonical-source`; file a consolidation issue on the others |
| **Divergent** | Same `capability-slug`, **different** implementations | The expensive class. File an issue naming both and which behaviour differs. This is where the fleet-homogeneity principle is actually being violated. |
| **Orphan** | A capability in exactly one repo that the skeleton ought to own | Candidate for promotion into `kipi-system` |
| **Collision** | Two repos both claim to own the same external resource (a launchd label, a Slack channel, a config path, a cron slot) | Highest severity. Two writers to one resource is a silent corruption path. |

Divergent and Collision are the two that justify this whole exercise. Duplicate is
cheap to find and cheap to fix. Collision is the one that has already bitten this
fleet (see the launchd income-scanner scar).

---

## Enforcement

This document does not enforce anything. Prose cannot. The enforced slice:

| Rule | Enforced by | Kind |
|------|-------------|------|
| A commit must name an existing issue id | `q-system/.q-system/scripts/linear-issue-ref-check.py`, lefthook `commit-msg`, exit 1 | shipped, `b23fdfd` |
| Bypasses stay countable | same script, appends to `q-system/output/linear-bypass.jsonl` | shipped |
| That gate has tests | `q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh`, 17 cases, in `capability-manifest.json` | shipped |
| A double-run creates nothing | `q-system/.q-system/scripts/test/test-linear-sync-idempotent.sh` | ASK-113, this session |
| Capture cannot silently fail | `q-system/.q-system/scripts/linear-queue.py`, appends to a repo-root queue with no network dependency | ASK-113, this session |
| Every capability map is schema-valid | `q-system/.q-system/scripts/capability-map-check.py` | ASK-113, this session |

Unenforceable by script, therefore judgment, therefore stated here and nowhere
claimed as a gate: whether a Definition of Ready is *good*, whether an estimate is
honest, and whether a `Divergent` finding is worth consolidating.
