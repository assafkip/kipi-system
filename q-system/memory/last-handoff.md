# Last handoff: fleet-wide Linear rollout (ASK-113)

Session 2026-07-26. Autonomous, end to end. Everything below was verified by
running it, not by reading it.

## Where it stands

**Goal 1, a Linear project per instance repo: DONE.** 25 of 25 (24 instances plus
the skeleton). A fleet-wide re-plan wants to create zero projects, so the dedup
key holds at fleet scale rather than only on the repo it was proven on.

**Goals 2 and 3, deterministic issue/project creation on build: SHIPPED**, as
queue-and-drain. There is no Linear API key in `~/.config/kipi/`, so bash cannot
reach the MCP server. Capture is local and offline (cannot fail on a network
problem); the agent drains it.

**Goal 5, overlaps and collisions: SHIPPED** as `capability-overlap.py`.

**Goal 6, SDLC standard: WRITTEN**, with every adjustment recorded in Part 0.

**Goal 4, triage every issue in every project: NOT STARTED.**

## The commands

```
kipi linear issue "<title>"   open an issue BEFORE building (issue-first)
kipi linear pending           what the queue holds that Linear does not
kipi linear status            which repos are rolled out (no Linear call)
kipi linear map               regenerate all 25 capability maps (~25s)
kipi linear overlap           divergence + collision report
/linear-drain                 agent-side: create the queued Linear objects
```

## Resuming

`kipi linear status` answers "which repos are done" without querying Linear.
**29 of 31 planned issues are still uncreated.** Re-planning any repo yields
exactly the gap:

```bash
kipi linear map
python3 q-system/.q-system/scripts/linear-sync.py plan \
  --map q-system/output/capability-maps/<repo>.json \
  --remote <snapshot.json> --out /tmp/plan.json --filter actionable --rollup
```

Fetch `<snapshot.json>` from Linear first (`list_issues` for the project, keep
`id`/`identifier`/`title`/`description`). The `<!-- kipi-key: ... -->` marker in
each description is what makes a re-run safe; **never drop it.**

## Three instructions adjusted toward best practice

1. **Issue-first, not issue-as-receipt.** An issue created after the build cannot
   specify or review the work. The commit-msg gate already enforced the right
   direction; what was missing was a cheap way to open an issue first.
2. **Queue-and-drain**, because bash has no credentials. If a key is ever placed
   at `~/.config/kipi/linear-api-key`, capture can call GraphQL and the drain
   disappears. Founder action.
3. **Scoped issues, full inventory in the repo.** 500-1500 permanent objects
   became 31. Skeleton propagations are tracked once, not 24 times.

## Findings, each verified by hashing files directly

- **ASK-116** `evidence-capture-protocol.md`: 3 versions across
  `4_points_consulting`, `investigations`, `Alice`, absent from the skeleton, so
  no existing gate can see the drift.
- **ASK-117** `reddit-build-radar`: registered instance, ZERO skeleton
  propagation. Possibly the only repo running with no enforcement layer while
  counted as governed.
- `q-system/hooks/auto-commit.py`: 23 instances on one version, the skeleton on
  another. The skeleton is ahead of the fleet on a Stop hook.
- `norri ai` and `all_points_setup` have zero locally-owned capabilities.

## The thing to carry forward

**The overlap pass produced three convincing, wrong findings.** All three were
caught by verifying instead of reporting, and DIVERGENT fell 131 -> 98 -> 54.

The worst: DIVERGENT was indexed by capability NAME, so three unrelated files
called `token-guard.py` read as "3 versions of the fleet's token ceiling". Direct
hashing showed the real one is byte-identical in all 24 repos that have it.
Propagation drift is about the same PATH, not the same name.

Recon output looks authoritative because it is generated. It is not evidence
until the specific claim is checked against the files.

## Open

Spillover: `sp-7b123c14` (kipi-new REGISTRY override blocks a true end-to-end
test), `sp-cfc861f1` (kipi-investigations wires run-lint.sh 4x under one
event+matcher), `sp-333f81b4` (ORPHAN=1246 / DUPLICATE=359 too coarse to act on),
plus pre-existing `sp-3cb2e575`, `sp-d29346e9`, `sp-2ae4df51`.

Unpushed commits on `main`. Nothing has been pushed this session.

## Verification, as run

```
test-linear-sync-idempotent.sh   14 pass 0 fail
test-linear-queue.sh             13 pass 0 fail
test-linear-wiring.sh            13 pass 0 fail
test-linear-issue-ref-check.sh   exit 0
capability-gate.py               GREEN, 59 tests
```

Not re-run this session: `kipi check` / `validate-separation.py`, which was
already RED at handoff on pre-existing failures owned by ASK-58 and ASK-59.
