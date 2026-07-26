# Make the `validate` required check real (ASK-113)

Founder decision 2026-07-26: fix the 5 failing updater tests so branch protection
on `main` stops being decorative, THEN start the claim-lock PRD. Recorded because
`validate` has been bypassed on 4+ consecutive pushes.

## What/why

`validate` is a required status check on `main` that has never been green. Every
push lands via `Bypassed rule violations`. A required check that cannot pass is
prompt-only enforcement wearing a CI badge, which is the exact failure mode this
repo's rules exist to prevent.

## Root causes (from CI ground truth, run 30219138594, not from theory)

The prior session's guess (`sp-d29346e9`: "pytest skips the hidden
`q-system/.q-system/` directory") is **wrong**. The gate does not use pytest
discovery; `capability-gate.py:303` runs each declared test artifact by
convention via `subprocess.run`, and it ran all 59 (`ran=59`).

Two real causes, not five:

### Cause 1 — no git identity on the runner (explains 4 of the 5)

CI log, verbatim:

```
fatal: empty ident name (for <runner@runnervm....internal.cloudapp.net>) not allowed
  ERROR: could not commit q-system sync
```

`kipi-update.sh:705` commits via
`git -C "$target" -c core.hooksPath="$guard_dir" commit --no-gpg-sign` with **no
`-c user.name` / `-c user.email`**. It relies on ambient identity. GitHub's
`ubuntu-latest` runner user has an empty gecos field, so git cannot guess a name
and refuses.

The cascade matters: `kipi-update.sh:1289` is
`abandon_instance "  ERROR: could not commit q-system sync" && continue`, and that
`continue` is **upstream of the plugins rsync at line 1393**. One failed commit
skips the whole rest of the instance, so the downstream assertions fail as
symptoms:

| Test | Reported failure | Actually |
|------|-----------------|----------|
| `test-kipi-update-hook-contract.sh` | `could not commit q-system sync` | the cause itself |
| `test-kipi-update-dry-final-state.sh` | `empty ident name` | the cause itself |
| `test-kipi-update-build-artifacts.sh` | `stale .venv survived; --delete-excluded did not reach it` | plugins rsync never ran |
| `test-kipi-update-safety.sh` | `tracked file not synced from skeleton` | config sync never ran |

**Ruled out:** local rsync is `openrsync` (2.6.9-compatible), CI is GNU rsync 3.x.
That is a genuine platform delta and was the leading suspect for the `.venv`
failure. It is NOT the cause: the rsync at `kipi-update.sh:1393` carries correct
`--delete-excluded --exclude=".venv/"` flags and simply never executes.

### Cause 2 — the receipts ledger cannot exist in a fresh clone (the 5th)

`test-updater-issue-sequence.py:101` audits `<repo>/.prd-os/receipts.jsonl`.
`.gitignore:31` is a blanket `*.jsonl`, so that file is untracked and absent in
CI. Every issue then reports `no closure receipt`.

Its 11 hermetic self-tests all PASS in CI (they build their own fixtures). Only
the live-repo audit section fails. Locally it passes solely because the founder's
working copy holds an untracked 112-line ledger.

## Approach

Three reasonable approaches for cause 1; naming them per the `name-options` rule:

1. **Configure identity in `validate.yml`.** One step, standard CI practice, zero
   production change.
2. **Give `guarded_commit` a fallback identity.** Makes the fleet updater robust
   on any machine with no git config (launchd runs with a minimal env). Changes
   production behavior.
3. **Export `GIT_AUTHOR_*` / `GIT_COMMITTER_*` inside each test.** Hermetic tests,
   but leaves the updater itself still ambient-dependent.

**Pick: #1.** Scope discipline — the flagged problem is a red gate, and a git
identity is a legitimate precondition of any committing tool, same as on a
developer machine. #2 is a real robustness gap but is scope expansion; captured as
spillover instead of bundled.

For cause 2: un-ignore `.prd-os/receipts.jsonl` and track it. The blanket `*.jsonl`
silently excluding this repo's own evidence ledger is the defect. 112 lines / 36K.
Plus `fetch-depth: 0` on checkout, because the same test probes commit ancestry
(`a closure commit unreachable from HEAD is rejected`) and the default depth-1
shallow clone has no history to probe.

## Files to touch

- `.github/workflows/validate.yml` — git identity step; `fetch-depth: 0` on checkout
- `.gitignore` — negate `*.jsonl` for `.prd-os/receipts.jsonl`
- `.prd-os/receipts.jsonl` — force-add (currently untracked)

## Acceptance criteria

- [ ] Reproducer: the 5 tests fail in a true ubuntu environment BEFORE the fix
      (local macOS cannot reproduce — see below)
- [ ] `capability-gate.py` exits 0 in CI with `ran=59`, 0 RED
- [ ] `validate` reports success on a PR, with no bypass line
- [ ] The 4 updater tests still pass locally on macOS/openrsync (no regression)
- [ ] Spillover captured for the `guarded_commit` fallback-identity gap

## Local reproduction is not possible; this is why

Three attempts, all falsified, recorded so the next session does not retry them:

1. `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null` — all 4 still pass.
   macOS git guesses an identity from the passwd gecos field.
2. `+ user.useConfigOnly=true` via `GIT_CONFIG_COUNT` — git provably refuses to
   guess (verified with a bare commit), yet all 4 still pass.
3. Cause found for at least one: `test-kipi-update-hook-contract.sh:417` sets its
   own `GIT_CONFIG_COUNT=1`, which **overwrites** the injected override for that
   invocation.

Verification therefore runs in CI on a PR branch, not on `main`. That is also the
honest way to prove a required check works: make the check pass on a PR.

## Patterns followed

- Reproducer/ground-truth first (`verification-loops`): every cause above is a
  quoted CI log line or a cited `file:line`, never inference.
- Bounded loop: 3 attempts, then stop and change approach (done — switched from
  emulating the runner to reading the control flow).
- `no-orphan-findings`: the updater robustness gap is captured, not mentioned.
