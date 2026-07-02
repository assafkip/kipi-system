# Token-guard: blocked attempts falsely escalate to "attempted 3 times"

**What/why:** Verified from Pure_spectrum_Q transcript (cd6f068f, 2026-07-02):
at the 50-call volume ceiling, each guard-BLOCKED Edit still increments
`repeat_map` (and `edit_targets`). The exact-retry check outranks the volume
check, so the 3rd blocked retry reports "You've attempted this exact call 3
times" for a call that executed zero times. Separately, the volume block/warn
messages never mention that `git commit` is exempt and resets the counter, so
the model retries into the deadlock instead of committing its way out.

**Approach (founder-approved option 1):** un-count a guard-blocked attempt
(decrement `repeat_map` + `edit_targets` before save on every block path in
`token-guard.py` — executable code, pinned by a new section in
`test-token-guard-hook-behavior.sh`); reword the volume block + warning to name
the commit escape hatch. No threshold changes.

**Files to touch**
- `q-system/.q-system/token-guard.py` — uncount helper + block paths + messages
- `q-system/.q-system/scripts/test/test-token-guard-hook-behavior.sh` — new
  sections: ceiling-blocked identical Edits never produce the retry message and
  leave `repeat_map`/`edit_targets` clean; executed identical calls still trip
  exact-retry.

**Acceptance criteria**
- [x] New test section shown FAILING against the unfixed script ("FAIL:
      attempt 3 escalated to false exact-retry")
- [x] 3 identical Edits at the ceiling: every block says the volume message
      (with commit hint), never "attempted this exact call"; `repeat_map` for
      that key and `edit_targets` for that file end at 0/absent
- [x] Exact-retry still fires for identical calls that pass the guard
- [x] All existing token-guard tests still pass (behavior, wiring, runtime)
- [x] `kipi update` propagates the script fleet-wide (commit 5f4d547; re-run
      post-commit — the first run synced pre-commit HEAD). Pure_spectrum_Q is
      standalone (skeleton-skipped): fixed by direct copy of token-guard.py +
      behavior test, test PASS in place.

**Patterns to follow:** black-box stdin-event tests in
`test-token-guard-hook-behavior.sh` (seed cache, run guard, assert cache +
stderr); negative self-test before fix (fable-discipline); scar-anchored
why-comment citing the 2026-07-02 qep_agent incident.
