# Ready-to-send: cc-spex closeout-gate contribution

STATUS (2026-06-16):
- ISSUE FILED: https://github.com/rhuss/cc-spex/issues/9 — waiting on maintainer.
- Repo is `rhuss/cc-spex` (renamed from `cc-sdd`; old name redirects). Target the
  PR at `rhuss/cc-spex`.
- PR is BUILT + verified, not yet pushed (waiting on maintainer reply).

Target: rhuss/cc-spex. Branch built + tested at /tmp/prd-os-targets/cc-sdd
on `chore/closeout-gate`. Changeset: 3 files, +216 lines. `make validate` green,
new test 6/6 green. Durable patch (survives /tmp wipe):
`q-system/output/cc-spex-closeout-gate.patch`.

PR commands below get finalized as single-line (the founder hit multi-line paste
breakage) when the maintainer says go. `gh` runs in the founder's terminal only
(sandbox can't read the keychain token).

---

## STEP 1 — Issue (propose, get a thumbs-up)

**Title:** Enforce "do not proceed with unresolved findings" deterministically

**Body:**

cc-spex already states the rule in several places, but only as prompt-level
guidance:

- `verify.md` Iron Law: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE"
  and "Claiming work is complete without verification is dishonesty."
- `review-code.md`: "DO NOT proceed with deviations unresolved."
- `spex-deep-review` writes a findings table with a Remaining column, and its own
  rule is "Critical + Important = 0 => GATE PASS."

In autonomous mode (`ask: smart|never`), `verify`/`stamp` are instructed to
"complete the verification and return." Nothing deterministically reads
`review-findings.md` and refuses completion when Critical/Important findings
remain. So the rule can be skipped.

Proposal: a small deterministic gate (`spex/scripts/spex-closeout-gate.sh`,
bash+jq, same style as `spex-flow-state.sh`) that reads the Remaining
Critical+Important counts and exits non-zero when > 0. Wired as Step 0 of
`verify`. Fail-open when no `review-findings.md` exists (does not force deep
review); `SPEX_CLOSEOUT_STRICT=1` makes it fail-closed.

Scope: ~216 lines, one 24-line addition to `verify.md`, plus the script and a
shell test in the `tests/` style. `make validate` stays green.

Does this fit the project? Any preference on placement or naming before I open
the PR?

---

## STEP 2 — PR (after buy-in)

**Title:** Add deterministic closeout gate: refuse completion on unresolved Critical/Important findings

**Body:**

### Problem

cc-spex states "do not proceed with unresolved findings" and "evidence before
claims" but enforces it only as prompt guidance. In autonomous mode the verify
and stamp commands are told to complete and return, with no deterministic check
of the deep-review findings table. The rule can be skipped exactly when it
matters most.

### Change

- `spex/scripts/spex-closeout-gate.sh` (new): reads `specs/<feature>/review-findings.md`,
  parses the Remaining column for Critical + Important, exits 1 when > 0. bash+jq,
  matching `spex-flow-state.sh`.
- `spex/extensions/spex-gates/commands/speckit.spex-gates.verify.md`: new Step 0
  runs the gate before any other check; non-zero means STOP, do not claim
  completion.
- `tests/test_closeout_gate.sh` (new): 6 cases, shell style matching
  `test_marketplace_install.sh`.

### Behavior

- No `review-findings.md` -> pass (does not force deep review).
- Unparseable table -> pass with a warning, never a false block, unless
  `SPEX_CLOSEOUT_STRICT=1`.
- Critical+Important Remaining > 0 -> block with the counts.

### Evidence

- `tests/test_closeout_gate.sh`: 6 passed, 0 failed.
- `make validate`: marketplace + plugin manifests pass.

### Possible follow-up

A Stop-hook variant for fully out-of-band enforcement in long autonomous
pipelines. Left out of this PR to keep the diff small; happy to add if wanted.

---

## STEP 3 — Commands (when gh is authed)

```bash
cd /tmp/prd-os-targets/cc-sdd

# 1. open the issue first
gh issue create --repo rhuss/cc-sdd \
  --title "Enforce 'do not proceed with unresolved findings' deterministically" \
  --body-file <(sed -n '/^## STEP 1/,/^---$/p' /Users/assafkipnis/projects/kipi-system/q-system/output/cc-spex-pr-drafts-2026-06-16.md)

# 2. after a thumbs-up: fork, push, PR
gh repo fork rhuss/cc-sdd --clone=false
git remote add fork "https://github.com/$(gh api user -q .login)/cc-sdd.git"
git push -u fork chore/closeout-gate
gh pr create --repo rhuss/cc-sdd --head "$(gh api user -q .login):chore/closeout-gate" \
  --title "Add deterministic closeout gate: refuse completion on unresolved Critical/Important findings" \
  --body "see PR body in cc-spex-pr-drafts-2026-06-16.md STEP 2"
```
