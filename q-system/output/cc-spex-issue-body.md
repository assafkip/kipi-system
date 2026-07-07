cc-spex already states this rule in several places, but only as prompt-level guidance:

- `verify.md` Iron Law: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE" and "Claiming work is complete without verification is dishonesty."
- `review-code.md`: "DO NOT proceed with deviations unresolved."
- `spex-deep-review` writes a findings table with a Remaining column, and its own rule is "Critical + Important = 0 => GATE PASS."

In autonomous mode (`ask: smart|never`), `verify`/`stamp` are instructed to "complete the verification and return." Nothing deterministically reads `review-findings.md` and refuses completion when Critical/Important findings remain, so the rule can be skipped exactly when it matters most.

**Proposal:** a small deterministic gate (`spex/scripts/spex-closeout-gate.sh`, bash+jq, same style as `spex-flow-state.sh`) that reads the Remaining Critical+Important counts and exits non-zero when > 0. Wired as Step 0 of `verify`. Fail-open when no `review-findings.md` exists (does not force deep review); `SPEX_CLOSEOUT_STRICT=1` makes it fail-closed.

**Scope:** ~216 lines, one 24-line addition to `verify.md`, plus the script and a shell test in the `tests/` style. `make validate` stays green; the new test is 6/6.

Does this fit the project? Any preference on placement or naming before I open the PR?
