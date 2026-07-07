# Plan: Extract prd-os as a public, contributable Claude Code plugin

Date: 2026-06-16
Status: DRAFT — awaiting founder pick on publish target (Decision 1)

## What / why

prd-os is the "receipts not prompts" gated PRD workflow. Its differentiator vs.
every existing spec-driven / TDD plugin (tdd-guard, cc-sdd, night-market): those
gate *entry* (no write without a failing test). prd-os gates *closeout* with
receipts. A Stop hook refuses to archive while a finding is open. No public
plugin does closeout-receipts. That gap is the contribution.

Goal: ship prd-os as a public, installable plugin other repos can adopt, with
your authorship intact.

## Current state (grounded in the actual code, 2026-06-16)

Good news. It is already built for this:
- v0.2.0, fully wired: 7 `/prd-*` commands, 2 hooks (scope_hook, stop_gate),
  8 runner scripts, findings schema, templates, SKILL.md, full pytest suite
  (14 test files).
- `config.py` already resolves a per-repo `.prd-os/config.json` with path
  overrides + schema versioning + documented defaults. Portable by design.
- README already documents the portable-core / repo-local split and a
  marketplace install path.

Three things stand between it and a public release:

1. **Codex dependency (the real blocker).** The review gate runs
   `/codex:review` + `/codex:adversarial-review`. That is the codex plugin /
   Codex CLI. A public user without Codex cannot run the gate, which is the
   heart of the product. Fix: make the reviewer pluggable (Codex OR Claude's
   own `/code-review` OR a generic "external reviewer" command in config). The
   findings schema already normalizes review output, so the seam exists.

2. **Stale README.** Header says "Portable plugin…" but the Status section says
   "Scaffold only. Version 0.1.0. Nothing wired yet" and "Install (planned, not
   yet implemented)." Both false now. First thing a visitor reads, currently
   wrong.

3. **No `/prd-os-init` + no LICENSE.** README promises an init command for
   per-repo bootstrap (writes `.prd-os/config.json`, gitignores state, registers
   hooks). Not in `commands/`. No LICENSE file means legally not contributable.

## Decision 1 (FOUNDER PICK NEEDED): publish target

| Option | What it means | Trade |
|---|---|---|
| **A. Standalone public repo** (my call) | New repo `assafkip/prd-os`, then list it in awesome-claude-code + submit to a community marketplace | Most control, full credit, differentiator stays intact. You maintain it. Plugin is already standalone-shaped, so least adaptation. |
| B. PR into an existing project | Add closeout-receipts to `rhuss/cc-sdd` or `athola/claude-night-market` | Faster reach (their audience). But you rewrite your state machine to fit theirs; your spine gets absorbed; you lose authorship framing. |
| C. List entry only | Add a line to `hesreallyhim/awesome-claude-code` pointing at a public repo | Trivial, but needs the standalone repo to exist first, so it is downstream of A, not an alternative. |

**SUPERSEDED by the OSS-contribution mission (2026-06-16).** North star is
PR-into-existing-project, so the on-mission pick is **B**: PR the
closeout-receipts pattern into an existing spec-dev / TDD plugin
(`nizos/tdd-guard`, `rhuss/cc-sdd`, or `athola/claude-night-market`). A
(standalone repo) is OFF-mission. C is downstream of a public artifact. See
`oss-contribution-mission-2026-06-16.md`. Next step: read the candidate targets,
pick where the pattern grafts with the smallest, most reviewable diff. The
"Approach" + "Files to touch" sections below were written for option A and need
a rework once the target repo is chosen.

## Decision 2 (sub-pick, my default inside A): scope of the first release

- **Default: ship prd-os alone** (idea → PRD → review → triage → approve →
  decompose). Issue *execution* (the `issue-*` commands) lives in the separate
  kipi-dsse plugin. Shipping prd-os alone is a clean, complete story; dsse can
  follow as a companion plugin once prd-os lands.
- Alt: bundle prd-os + kipi-dsse as the full lifecycle. Bigger surface, longer
  to decouple, more personal-system coupling to scrub. Park for v2.

## Approach (if A + ship-alone)

1. Make the reviewer pluggable. Add `review.command` to config schema; default
   keeps Codex, but a Claude-native `/code-review` path works with zero Codex.
2. Rewrite README to match reality (status, install, the closeout-receipts
   pitch up top).
3. Add `/prd-os-init` command (the README already specs its behavior).
4. Add LICENSE (Apache-2.0, matching anthropics/skills).
5. Scrub kipi-system coupling: no hardcoded kipi paths, no `q-system/` refs in
   plugin code; verify it runs in a bare repo.
6. New public repo, copy plugin, green test suite, marketplace + awesome-list
   submission.

## Files to touch (plugin-local; nothing in kipi personal dirs)

- `plugins/prd-os/scripts/config.py` — add `review` config block
- the review-invoking command/script (likely `scripts/prd_runner.py` +
  `commands/prd-review.md`) — read `review.command`, stop hardcoding codex
- `plugins/prd-os/README.md` — full rewrite
- `plugins/prd-os/commands/prd-os-init.md` — new
- `plugins/prd-os/LICENSE` — new (Apache-2.0)
- `plugins/prd-os/tests/` — add a "runs in a bare repo with no Codex" test

## Acceptance criteria (done = these are green, not "looks right")

- [ ] `cd /tmp/bare-repo && /prd-os-init` writes a valid `.prd-os/config.json`,
      gitignores state, registers hooks. Verified by running it in an empty git
      repo, not by reading the code.
- [ ] Full review→approve→decompose cycle completes with `review.command` set to
      a Claude-native reviewer, zero Codex installed (the portability proof)
- [ ] `pytest plugins/prd-os/tests/` green after every change
- [ ] `grep -rn "kipi\|q-system\|/Users/assaf" plugins/prd-os --include=*.py
      --include=*.md --include=*.json` returns nothing in shipped files
- [ ] README Status + Install sections match the actual v0.2.x reality
- [ ] LICENSE present

## Patterns to follow (from this repo's own code)

- Config resolution: mirror `config.py`'s strict/non-strict + schema-version
  pattern when adding the `review` block. Do not invent a second config style.
- Hook contract: exit 2 = block, exit 0 = pass (matches scope_hook/stop_gate and
  the skill-hook-pairing rule).
- Test isolation: the fable-discipline-lint rule + existing `conftest.py`. New
  tests use temp repos, never touch a live `.prd-os/`.
- README spine: keep the existing "portable core vs repo-local split" table; it
  is the clearest part. Fix only the false Status/Install claims.

## Out of scope

- kipi-dsse decoupling (Decision 2 alt, park for v2)
- Any change to kipi-system personal dirs (canonical/, my-project/, memory/)
- Marketing copy / launch post (separate task after the repo is live)

## State note (2026-06-16)

The DSSE issue `capability-signer-se` was parked (active-issue.json moved to
`.parked`) to lift its scope lock so this plan could be written. It is intact on
disk. Resume it with:
`mv /Users/assafkipnis/projects/kipi-system/.claude/state/active-issue.json.parked /Users/assafkipnis/projects/kipi-system/.claude/state/active-issue.json`
