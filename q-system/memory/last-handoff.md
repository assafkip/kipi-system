# Session handoff — 2026-06-16

## Headline

OSS-contribution workstream kicked off. Locked the north star: contribute the
novel components Assaf built as **PRs into existing projects**, NOT new standalone
repos. First candidate in flight: prd-os closeout-receipts. Next step is choosing
which existing TDD/spec plugin gets the PR.

## RESUME HERE (next unchecked action)

ISSUE FILED: https://github.com/rhuss/cc-spex/issues/9 (the closeout-gate
proposal). Repo note: `rhuss/cc-sdd` was renamed to `rhuss/cc-spex`; old name
redirects. Target the PR at `rhuss/cc-spex`.

WAITING ON: maintainer (rhuss) to reply on issue #9. Nothing to do until then.

When the maintainer says yes (or "just send it"): push the PR. The branch
`chore/closeout-gate` is built + verified (new test 6/6, `make validate` green):
- `spex/scripts/spex-closeout-gate.sh` (new), `verify.md` Step 0 (edit),
  `tests/test_closeout_gate.sh` (new).
- Durable patch (survives /tmp wipe): `q-system/output/cc-spex-closeout-gate.patch`
- PR/push commands + issue/PR text: `q-system/output/cc-spex-pr-drafts-2026-06-16.md`
- PR design + gap analysis: `q-system/output/plans/prd-os-cc-spex-pr-2026-06-16.md`

GOTCHA: `gh` works in the founder's terminal but NOT in the sandboxed tool shell
(token in macOS keychain, sandbox can't read it). So the founder runs the
push/PR commands; the agent prepares them.

## TOOL #2 — capability approval token -> dwarvesf/claude-guardrails

BUILT + verified (committed test 12/12), NOT yet filed. Adds a forgery-resistant,
one-time, command-scoped approval path for destructive commands (the missing
"approve safely" tier in their guardrails). 5 files, +351 lines, openssl default
(SE/Touch-ID optional, so the parked SE helper does not block it).
- Branch `chore/capability-approval` in /tmp/captoken-targets/claude-guardrails
- Durable patch: `q-system/output/captoken-claude-guardrails.patch`
- Issue + PR text + commands: `q-system/output/captoken-pr-drafts-2026-06-16.md`
- Issue body file: `q-system/output/captoken-issue-body.md`
- NEXT: founder runs the single-line `gh issue create` from STEP 1 of the drafts,
  pastes the issue URL back. Then PR after maintainer buy-in.

## What got done this session

- Reviewed the kipi-system build for contributable components. Top candidates:
  prd-os closeout-receipts, capability-token local biometric approval, the AUDHD
  skill, the skill-hook-pairing pattern.
- Verified the live ecosystem (anthropics/skills, awesome-claude-code lists,
  community marketplaces, tdd-guard / cc-sdd / night-market, OpenLeash / ZeroID).
- Wrote the **mission record**: `q-system/output/plans/oss-contribution-mission-2026-06-16.md`
  (north star, candidate pipeline, contribution-unit principle).
- Wrote the **prd-os extraction plan**: `q-system/output/plans/prd-os-opensource-extraction-2026-06-16.md`.
  Decision 1 realigned from "standalone repo" (off-mission) to "PR into existing
  project" (on-mission). The Approach + Files sections still need a rework once
  the target repo is chosen.
- Saved memory `project-oss-contribution-mission` (+ MEMORY.md line).

## IMPORTANT loose end from this session — parked DSSE issue

`capability-signer-se` was PARKED to lift its scope lock so the plan could be
written. Its state file is intact at:
`.claude/state/active-issue.json.parked`

The issue has its `verified` receipt set and one review round done; only
`reviewed` + `findings_triaged` remain. To RESUME it, un-park:
```
mv /Users/assafkipnis/projects/kipi-system/.claude/state/active-issue.json.parked /Users/assafkipnis/projects/kipi-system/.claude/state/active-issue.json
```
Then `/issue-review` and `/issue-closeout`. Until un-parked, the DSSE stop/scope
gates are dormant.

## Carried-over open loops (still live, not this session's work)

1. **Post the `/goal` amplify reply** (from 2026-06-15) if not already posted.
   Concedes /goal is real, then plants the deterministic-receipt distinction.
   Draft is in the 2026-06-15 conversation.

### kipi-investigations (belongs to ~/projects/kipi-investigations, verify before acting)

2. Wait for Ally's report bundle, then run the full pipeline (`./invctl ingest
   --inbox --investigation handala-2026 && ./invctl consolidate && ./invctl
   analyze && ./invctl profile && ./invctl synthesize && ./invctl export-vault
   && ./invctl export-intel`)
3. Re-consolidate to merge alias splits (`@unydigma` vs `Unydigma`)
4. Add `watchlist` feature to the webapp
5. Add multi-case support (webapp shows one global graph; should respect
   `q-investigate/investigations/<case>/` boundaries)
6. Show prototype to Ally + record her reaction
7. Loop in Ethan (FBI contractor, IOC3 originator) once Ally validates
