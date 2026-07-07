# NORTH STAR: Contribute what Assaf built as PRs to existing OSS projects

Date: 2026-06-16
Type: Mission record. This guides every task in the contribution workstream.
Read this first before planning any individual contribution.

## The one sentence

Take the genuinely novel components Assaf built (in kipi-system and the fleet)
and land each one as a valuable PR into an EXISTING open-source project. Not as
new standalone repos.

## What this means concretely

- **INPUT:** his built work. prd-os (gated PRD + closeout-receipts),
  capability-token security (local Secure-Enclave / Touch-ID approval), the
  AUDHD executive-function skill, the skill-hook-pairing pattern,
  fable-discipline, the enforcement-hook architecture.
- **OUTPUT:** PRs into existing, active repos that already have a maintainer and
  an audience.
- **The contribution UNIT is an extracted feature or pattern, reshaped to the
  target project's conventions.** Not a wholesale republish of his system. The
  question is never "where do I publish my thing," it is "which existing project
  would value this capability, and what is the smallest PR that lands it there."

## The rule every task in this workstream follows

If a proposed path produces a NEW standalone repo, it is OFF-mission, unless that
repo is a strict prerequisite for a PR somewhere else. Default move: name the
existing target project, then the minimal PR.

## Candidate pipeline (from 2026-06-16 research)

| What Assaf built | Existing target repo(s) | The PR |
|---|---|---|
| prd-os closeout-receipts | `nizos/tdd-guard`, `rhuss/cc-sdd`, `athola/claude-night-market` | Add "gate closeout while a finding is open." Existing plugins gate ENTRY (no write without a failing test); none gate CLOSEOUT with receipts. That is the novel feature. |
| capability-token (local biometric approval) | `OpenLeash`, or a Claude Code security plugin | Add a local Secure-Enclave / Touch-ID approval path for destructive agent ops. Existing frameworks are server-side enterprise identity; the local hardware-rooted tier is missing. |
| AUDHD executive-function skill | `anthropics/skills` (Apache-2.0, takes community skills) | Add an accessibility / neurodivergent skill. None exist in the official repo. |
| skill-hook pairing pattern | `hesreallyhim/awesome-claude-code` | Contribute the "skills generate, hooks validate" pattern as a documented entry. |

## How this re-frames prd-os (correction logged)

An earlier draft recommended publishing prd-os as a standalone repo, optimizing
for reuse across repos. Under this north star that is OFF-mission. The on-mission
path is: extract the **closeout-receipts pattern** and PR it into an existing
spec-driven / TDD plugin (tdd-guard / cc-sdd / night-market). Reshape it to their
state machine and conventions. The contribution is the capability, not the repo.

## Open question carried forward (for prd-os specifically)

Which existing target gets the closeout-receipts PR. Needs a read of each
project's architecture to pick the one where the pattern grafts cleanest with the
smallest, most reviewable diff. That is the next planning step.

## Linked docs

- prd-os extraction plan: `q-system/output/plans/prd-os-opensource-extraction-2026-06-16.md`
  (its Decision 1 needs realignment from "standalone repo" to "PR into existing
  project" per this mission)
