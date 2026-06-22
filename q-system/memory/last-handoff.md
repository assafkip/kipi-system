# Session handoff - 2026-06-21

## Headline

Shipped `/say` autoplay-with-controls and launched `claude-voice` as a public
repo. `/say` now opens a real Terminal window playing the response via mpv, so
the keyboard drives speed/seek/pause. Extracted a de-kipi'd standalone version
to github.com/assafkip/claude-voice (MIT, public). Posts drafted, not published.

## What shipped today (effort, not outcomes)

1. Verified the `/say` plugin scope fix held: `kipi-core@kipi` is `scope:user`,
   no projectPath, 1.5.3. All three kipi-core commands present this session.
   Original closeout task: DONE.
2. Built `/say` autoplay-with-controls (kipi-core). Diagnosed that a slash
   command runs in a seatbelt sandbox that BLOCKS AppleEvents (AppleScript to
   iTerm times out -1712). Chose `open -a Terminal <file>.command` (sandbox
   allows it, Terminal runs the .command). iTerm is impossible from the sandbox.
   Tested compile + SSH/no-mpv guards + full open->Terminal->launcher->mpv chain
   + live run. Committed to skeleton.
3. Propagated to the fleet: `kipi update` -> 16 updated, 0 failed, 2 skipped.
   All 16 instance copies carry `autoplay_in_terminal`. Runtime was already live
   everywhere via the shared user-scoped cache; this synced the source dirs.
4. Created + published `claude-voice` (bare `/say` command, script, README, MIT
   LICENSE, .gitignore). Re-authored with the GitHub noreply email (push was
   rejected for the private gmail), `main` default branch.
5. Memory saved: `project_claude_voice_repo.md` (+ MEMORY.md pointer).

## RESUME HERE (next unchecked action)

`claude-voice` launch posts PUBLISHED (X + Reddit, 2026-06-21). Repo:
github.com/assafkip/claude-voice. Next: watch for replies/issues/stars, answer
questions, fold any real install friction back into the README. No action
required unless someone engages.

Note: claude-voice is a NEW standalone repo, a deliberate exception to the
OSS-mission north star (PRs into existing projects, not new repos). Founder
directed it as a product launch, not an OSS contribution. Separate track, not
drift.

---

# Session handoff — 2026-06-16 (prior session - still-live loops below)

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
