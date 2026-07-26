# Last handoff — 2026-07-26 (continuation session)

Tracking epic **ASK-113**. PR #10 **merged to main** (`05af553`), 7 commits.
Everything below was verified by running it, not by reading it.

## Carried forward from the earlier 2026-07-26 session (still true)

- **Goal 1, a Linear project per instance repo: DONE.** 25 of 25 (24 instances +
  the skeleton). A fleet-wide re-plan creates zero projects.
- **Goals 2 and 3, deterministic creation on build: SHIPPED** as queue-and-drain.
  No Linear API key exists, so bash cannot reach the MCP server; capture is local
  and offline, the agent drains it.
- **Goal 5, overlap/collision analysis: SHIPPED** (`capability-overlap.py`).
- **Goal 6, SDLC standard: WRITTEN**, adjustments recorded in its Part 0.
- **Goal 4: still NOT STARTED.** Triage every issue in every project (done /
  needs work / recorded, with evidence): 61 pre-existing kipi-system issues, 45
  in cole-GTM.
- **29 of 31 planned Linear issues remain uncreated.** Resumable:
  `kipi linear status` says which repos are done without querying Linear.
- Dedup key `<repo-slug>/<capability-slug>`, written into each Linear
  description as `<!-- kipi-key: ... -->`. **Never drop that marker.**

## Founder decisions this session

- **Q2 (branch-protection bypass):** fix the 5 tests, make the gate real.
- **Sequencing:** updater tests first, then the claim-lock.
- **Merge:** merge PR #10 with the admin bypass, containment failure and all.

## What shipped

| Commit | What |
|--------|------|
| `226cf6f` | CI: git identity + `fetch-depth: 0` + track the receipts ledger |
| `c307bed` | Close discipline into the SDLC standard §3.1 / §5 |
| `a6ba923` | Instance identity out of 2 scar comments |
| `d26b425` | Slice 0: truthful reviewer provenance (`claude-*` sources) |
| `7c0fccb` | Slice B: the agent claim-lock |
| `f32bfbd` | Adversarial review fixes: 2 blockers + 8 more |

## The 5 updater CI failures — fixed

The prior session's theory (`sp-d29346e9`, "pytest skips the hidden
`q-system/.q-system/` dir") was **wrong**: `capability-gate.py:303` runs tests by
convention, not pytest discovery.

Two causes, not five. **No git identity on the runner** (4 of 5):
`kipi-update.sh:705` commits with none, the ubuntu runner's user has an empty
gecos field, and `kipi-update.sh:1289` `abandon_instance ... && continue` is
*upstream* of the plugins rsync at 1393 — so one missing identity produced four
unrelated-looking symptoms. And **`.gitignore`'s blanket `*.jsonl`** hid
`.prd-os/receipts.jsonl`, the ledger `test-updater-issue-sequence.py:101` audits.

Local macOS **cannot** reproduce this: its git guesses an identity from the
passwd gecos field. Three failed reproducer attempts are recorded in
`q-system/output/plans/ci-validate-green-2026-07-26.md` — do not retry them.

## Two lessons worth carrying forward

**1. A fixture invented by the author tests nothing.** The claim-lock's remote
half read `state`; `mcp__linear__get_issue` emits `status` + `statusType`. That
remote check is the ONLY cover for a cross-checkout collision and it granted
unconditionally — while the suite stayed green, because the fixture was
hand-rolled from the same mental model as the code. Fixtures are now the verbatim
captured payload. Prefer `statusType` over the status NAME: teams rename states.

**2. `\s` matches a newline even under `re.M`.** `^reviewed_by:\s*.*$` ate the
FOLLOWING frontmatter line when the value was empty. Driven to a real exploit:
eating `findings_path:` made the gate report "no findings" and a PRD with an
untriaged BLOCKER advanced to `approved`, exit 0. Use `[^\n]*`.

## The claim lock (how to use it)

```
kipi linear claim ASK-nnn --agent <name> --session <id>   # BEFORE branching; exit 3 = refused
kipi linear claims                                        # who holds this tree
kipi linear release ASK-nnn --agent <name> --session <id> # when the PR opens
```

- Identity is **(agent, session)**, never agent alone — two sessions both named
  "claude" were both granted, the exact `53f2eeb` scar. `KIPI_SESSION_ID` /
  `CLAUDE_SESSION_ID` are honored.
- **The resource is the working tree, not the issue.** A separate git worktree is
  the remedy for a refusal, not `--break-stale`.
- `--break-stale` is a compare-and-swap: needs `--holder <session>` naming the
  exact claim you looked at.
- Remote half: pass the verbatim `mcp__linear__get_issue` response as
  `--remote-state`. Unrecognized shapes fail closed.

## Still open — `validate` is NOT green

One pre-existing failure, ASK-58/ASK-59: semantic containment. The headline
number misleads. Of ~11,800 findings, **all but 46 are
`unclassified_populated_record`**, which `prd-prevent-fact-fanout-2026-07-25.md:83`
says must never block. The **46 real** ones:

`source_identity` 25 · `pricing` 11 · `client_identity` 4 ·
`sourced_interaction` 3 · `case_proof_gap` 3

Unchanged this session. **The bypass on `main` stands until these are resolved.**
That PRD has founder decisions already pending, so it was captured
(`sp-88d889b5`), not started.

## Open spillover

- `sp-5375bc44` — `guarded_commit` still ambient-identity-dependent for the fleet
  updater itself (launchd runs with a minimal env). Fixed at the CI layer only.
- `sp-b386aba4` — `codex_reviewed_at` key is still vendor-named; renaming needs a
  read-either/write-new compatibility window.
- `sp-88d889b5` — `validate-separation.py:609` blocks on warn-only records,
  hiding the actionable 46 behind ~11,800.
- Pre-existing: `sp-7b123c14`, `sp-cfc861f1`, `sp-333f81b4`, `sp-3cb2e575`,
  `sp-d29346e9`, `sp-2ae4df51`.

## Correction on record

`a6ba923`'s message claimed removing instance names from comments closed a leak.
**False.** `instance-registry.json`, `INSTANCES.md` and `kipi-update.sh` publish
all 24 instance names with absolute home paths in the same public repo. Net leak
reduction: zero. The PROPAGATION argument stands on its own and is why the change
was kept (`q-system/.q-system/scripts/` rsyncs to every instance).

## Verification, as run (on merged main)

```
capability-gate.py             GREEN, ran=61   (was 59)
test-linear-claim.sh           30 checks       (was 21)
test-receipts-ledger-check.sh   5 checks, 12 leak shapes blocked
pytest plugins/prd-os/tests/   318 passed, 1 skipped
validate-separation.py 1       1 FAIL (pre-existing containment), PASS 68
```

## Not done

`/prd-review` never ran as a prd-os ceremony — there is no active PRD; the work
was built directly and reviewed by three adversarial subagents instead. If the
prd-os receipt trail matters for this work, it needs a retro-PRD.
