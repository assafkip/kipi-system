# RCA: six open spillover items, one drift between a truth and its copy

**Date:** 2026-06-30
**Trigger:** Founder asked to investigate all 6 open spillover items deeply and identify any related root cause.
**Surface-fix commit:** 4df4945 (settings-template-sync-check, fixes one facet)
**Structural-fix commit:** c494b85 (version-bump guard), 4df5781 (bidirectional sync-check + freshness wiring), d3b83d0 (prd-os template contract), 9068d2f (token-guard runtime guard) — 5 of 7 action items shipped; see below.

## What happened

Six findings sit open on the spillover ledger, captured across three unrelated
work streams (the say-cache fix, the spillover-gate PRD, and this session's
memory-confidence PRD). On their face they look unrelated: a Codex hang, a stale
PRD manifest, an unwired hook, a plugin-version mismatch, a marketplace clone
that was hand-edited, and a lint that misses chat prose. Investigated together,
five of the six are the same failure: a single truth has more than one stored
representation, the representations drifted, and nothing checked that they agreed.

## Surface symptom

The six open items (`.prd-os/spillover.jsonl`):

- `sp-aa7e4995` — `memory-freshness.md` claims "a SessionStart hook enforces" decay; the hook was absent from the skeleton's `.claude/settings.json`.
- `sp-435edda6` — the cached `prd-os/0.1.0` `prd-start` template teaches an `id`-keyed `## Issues` manifest; the runner's approval gate requires a `finding_id`-keyed one. A PRD authored to the template is rejected.
- `sp-9886486d` — the marketplace clone was hand-patched across sessions (stray untracked `say.*` files + a 7-line local edit to `issue_runner.py`) instead of git-pulled; the version-keyed cache never refreshed.
- `sp-cd50b062` — the spillover-gate PRD manifest references 4 issue specs that do not exist on disk; the feature shipped without going through split.
- `sp-28bf75a4` — a `UserPromptSubmit` hook fires inside Codex's own session and returns Blocked, so `codex exec` produces no final message.
- `sp-chatprose-stophook` — the deferral lint is PostToolUse, so a deferral spoken only in chat prose (never written to a file) is never seen.

## Surface root cause

Each item has its own proximate trigger: a missing line in `settings.json`; a
template file out of step with a runner; an un-bumped `plugin.json` version; a
manifest never materialized; a hook with no runtime guard; a lint bound to the
wrong event. Fixing any one in isolation (wire the hook, edit the template, bump
the version) closes that item and leaves the class intact.

## Structural root cause

The system keeps **many derived representations of one truth and has no
deterministic check that a given pair agrees.** A fact lives in a canonical place
AND in one or more copies generated, cached, cloned, or merely *claimed* from it;
when they drift, the copy that actually runs is silently not the one you edited or
asserted. Evidence of the multiplicity: `prd-os` exists in four copies right now —
`plugins/prd-os` (repo), `~/.claude/plugins/cache/kipi/prd-os/0.1.0`, `.../0.4.0`,
and the marketplace clone — and the slash command, the cached runner, and the repo
runner are not the same version.

### Root cause #1 — duplicated representations with no sync-verification
type: implicit-contract

`settings.json` vs `settings-template.json` (the dead-hook bug fixed earlier this
session, and `sp-aa7e4995`); cached plugin template vs live runner contract
(`sp-435edda6`); rule prose that *claims* an enforcement vs the wiring that does or
does not exist (`sp-aa7e4995`). In every case two stores of one fact were allowed
to diverge because no gate compared them. The just-shipped
`settings-template-sync-check.py` is the exemplar fix for exactly one of these
pairs; the class has more pairs and no general guard.

### Root cause #2 — mutating a derived/cached copy instead of the source
type: process

`sp-9886486d` (the marketplace clone was hand-edited rather than changed at the
skeleton and pulled; the version key was never bumped, so the cache could never
notice) and `sp-cd50b062` (the spillover feature shipped by editing reality
directly, leaving the PRD manifest pointing at issue files that were never
created). When work lands on a copy or outside the generating flow, the
source-of-truth and the copy drift by construction.

### Root cause #3 — enforcement scoped to one path or runtime, silently partial
type: environmental-trigger

`sp-28bf75a4` (a hook written for the Claude Code runtime fires under Codex, a
runtime it was never scoped for, and breaks it) and `sp-chatprose-stophook` (a
deterministic catch covers the tool-use path but not the chat-prose path). The
guard exists but its coverage is narrower than the surface it claims, and nothing
enumerates the paths it must cover. This is the same shape as #1 — a contract
asserted more broadly than it is enforced.

## Verification

Multiplicity, confirmed:
```
$ ls -d plugins/prd-os ~/.claude/plugins/cache/kipi/prd-os/*/ \
       ~/.claude/plugins/marketplaces/kipi/plugins/prd-os
plugins/prd-os                                  (repo, spine-native)
~/.claude/plugins/cache/kipi/prd-os/0.1.0/      (cached, taught id-keyed template)
~/.claude/plugins/cache/kipi/prd-os/0.4.0/
~/.claude/plugins/marketplaces/kipi/plugins/prd-os/   (slash-command load path)
```

Drift-undetected, confirmed: the dead-hook instance of root cause #1 shipped 8
enforcement hooks to the fleet with their switches stranded —
`grep memory-freshness-check .claude/settings.json` returned nothing while
`settings-template.json` wired it, and the instance audit found 17-18/18 instances
missing each of 8 hooks. After the fix, the same audit returned 0/18 missing, and
`settings-template-sync-check.py --check` against the repo exits 0 (in sync); an
injected stranded hook makes `kipi update` abort (exit 1, "ABORT"). That proves the
*pattern* of fix works; it does not yet cover the other pairs.

## Contributing factors

- A rule file can assert "a hook enforces X" with no test binding the claim to the wiring (the `prompt-only-enforcement-guard` blocks the *claim shape* but not a claim whose hook later falls out of the config).
- Plugin code is version-keyed and cached, but nothing forces a version bump when the command/skill directory changes, so a stale cache is indistinguishable from a current one.
- The gated flow (prd-os split -> issue specs) can be skipped by editing reality directly; the archive gate catches the manifest drift afterward but cannot prevent the work from landing un-split.
- Hooks have no required self-scope to their runtime; a hook is free to fire anywhere the config is loaded, including foreign runtimes.

## Fixes shipped

- Surface fix: `settings-template-sync-check.py`, wired as a PostToolUse hook and a `kipi update` preflight that aborts on divergence — commit 4df4945. Closes the `settings.json` vs `settings-template.json` pair only.
- Structural fix: pending. The class is "derived copies with no sync gate"; the generalizing fix is the action items below, not the single pair already closed.

## Action items

- [x] Sync-check for the settings pair, both directions: in-settings-not-template (ships dead) AND in-template-not-settings (dead in skeleton); freshness + prompt-only-guard wired into the skeleton (closes `sp-aa7e4995`) — commit 4df5781 — type: gate. (The broader prose "rule claims hook X" parser is not built; the deterministic settings pair is.)
- [x] Plugin version-bump guard: a pre-commit + CI check that a changed plugin forces a `plugin.json` version bump, so the version-keyed cache cannot go stale silently (closes `sp-9886486d`) — commit c494b85 — type: gate
- [x] Contract test: the `prd-os` template documents every manifest key the runner's approval gate enforces, run in CI, so template/runner drift fails loudly (closes `sp-435edda6`) — commit d3b83d0 — type: test
- [x] Runtime self-scope: token-guard fast-exits when CLAUDECODE is unset (foreign runtime e.g. Codex) (closes `sp-28bf75a4`) — commit 9068d2f — type: code. Follow-up `sp-a2aaaf41`: extend the guard to the other ~11 hooks (lower urgency — they self-scope by file type).
- [x] Spillover-gate PRD: phantom manifest emptied with a documented legacy note, PRD archived; feature confirmed live via 3 passing tests (closes `sp-cd50b062`, voided with evidence) — type: process
- [x] Stop-hook / chat-prose deferral capture (`sp-chatprose-stophook`) — already resolved on the ledger — type: gate
- [ ] Consolidate prd-os to a single loaded copy (or a check that repo/cache/marketplace agree on version) — owner: founder — type: process
- [ ] `sp-32d1bc1e`: core.hooksPath unset, so the tracked .githooks pre-commit (with the new guards) is not the active hook — guards run in CI but not locally. Security-adjacent (gitleaks chain); needs founder sign-off — owner: founder — type: process

## Lessons

- These six were captured as unrelated nits; together they are one class. The spillover ledger surfaced the pattern only because every item was written down, not mentioned — the no-orphan rule paid off here.
- The fix for a "copy drifted from its source" bug is never to re-sync the copy by hand. It is a deterministic check that fails when they disagree, or the elimination of the second copy. `settings-template-sync-check` is the template; the rest of the pairs need the same treatment.
- "The text is in the file" is not "the running system does it." Five of these six are that scar in a new costume: a claim, a template, a cache, a manifest, or a hook asserted something the actually-loaded copy did not do.
