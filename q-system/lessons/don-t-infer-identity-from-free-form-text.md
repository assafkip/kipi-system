---
id: don-t-infer-identity-from-free-form-text
kind: pattern
title: Don't Infer Identity From Free-Form Text
date: 2026-11-07
---

## When to use

Apply when code must decide "is this the thing I own?" and the only available input is a free-form string a human or tool wrote: a command line, a config blob, a comment marker, a URL, a log line. Symptom that you are already in trouble: each review round finds a new way to spell the same thing that defeats your matcher, and your fixes are a growing list of pattern cases.

## How

1. Name the decision the matcher is actually making. Write it as a sentence with a subject and a verdict, e.g. "this entry is managed by us and may be rewritten." If the sentence contains "probably" or "looks like," you have an inference, not an identity check.

2. Count the spellings. Take the input language and list the independent mechanisms that can express one logical value: quoting, whitespace, variable expansion, indirection through a working-directory change, nesting or subshells, aliases, relative vs. absolute forms, encoding. If that list is open-ended, pattern matching cannot be completed. Stop adding cases.

3. Invert the direction of the contract. Instead of widening what you recognize, narrow what you accept. Options, in order of preference:
   - Carry identity out of band: an explicit field, key, or label that the producer sets, so no parsing is needed.
   - Require a canonical form: define one legal spelling, reject or refuse to claim anything else, and document the rule where authors will see it.
   - Canonicalize before comparing: resolve the input through the same machinery that will eventually execute or consume it, then compare resolved values rather than source text.

4. Make non-matches safe, not silent. Unrecognized input should fall into the conservative branch (leave it alone, hand it back, surface a warning) rather than the destructive branch. Then an unexpected spelling becomes a visible no-op instead of data loss.

5. Write down the closed set. Record the exact accepted forms as a short list in code or docs. A bounded, stated set is reviewable; a regex that grew by accretion is not.

## Pinning the premise

Separately, treat every claim in a docstring, commit message, or design note as an untested assertion until a test names it:

1. Read the prose that describes what the change preserves or guarantees. Extract each claim as a sentence.
2. For each claim, ask which test fails if the claim is violated. If the answer is "none," the claim is decoration.
3. Add the missing test named after the claim, so the failure message states the broken promise. Prefer one test per claim over one broad test touching several.
4. Watch for the specific gap where a change has thorough tests for the mechanism it adds and zero tests for the invariant it promises not to break. Coverage of the new path hides the absence of coverage for the preserved path.

## Signals you have finished

- The accepted input forms are enumerable and written down.
- A novel spelling produces a safe no-op, not a wrong verdict.
- Every guarantee stated in prose has a test that fails when it is violated.
- Review rounds stop producing new counterexamples, because counterexamples are now out of scope by construction rather than by patch.
