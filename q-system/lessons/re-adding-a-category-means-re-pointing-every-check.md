---
id: re-adding-a-category-means-re-pointing-every-check
kind: pattern
title: Re-adding a Category Means Re-pointing Every Check
date: 2026-11-07
---

## When it applies

You maintain a system where some enumerated dimension (a category, channel, tenant, locale, content type, device class) selects which validation rules, reference data, or thresholds apply. At some point that dimension is removed, renamed, merged into another, or re-added as its own value. Enumerations tend to be duplicated across code, config, prompts, fixtures, and docs, so a change in one place leaves the others stale.

## How to do it

**1. Enumerate every consumer of the dimension before changing it.** Grep for the literal value and for the name of the dimension itself, then list every place it appears: CLI argument choices and other input validators; lookup tables and path/name-to-category mappings; rule or rubric datasets keyed by the value; reference corpora, golden samples, or few-shot examples; feature flags and routing tables; dashboards and alert filters. Treat that list as the change's checklist, not a byproduct.

**2. Audit the rules and the enforcement of the rules as two separate items.** A common failure is auditing the *authoring* side thoroughly (the spec, the style guide, the acceptance criteria) while leaving the *checking* side pointed at the old value. The rules were reviewed; the thing that enforces them was not. Put both on the checklist explicitly, with separate sign-offs.

**3. Make empty reference data a hard error, not a pass.** A validator that loads zero rules, zero examples, or zero baselines for a given key will return "no problems found," which is indistinguishable from success at the call site and in logs. Change each such validator to fail loudly when its keyed dataset is empty or the key is unknown: raise, exit non-zero, or return an explicit `not_applicable`/`unconfigured` status that callers must handle. Never let the absence of criteria read as satisfaction of criteria.

**4. Add a conformance test over the enumeration itself.** Write a single test that iterates every value of the dimension and asserts that each required artifact exists and is non-empty: rule set present, at least N reference items, accepted by every input validator, present in every mapping table. This test fails the moment a new value is added without its dependencies, which is exactly when you want to know. It also catches the reverse error: data left behind for a value that no longer exists.

**5. Validate the mapping, not just the dataset.** Separately assert that a value is routed where you expect. If an implicit convention maps a name or path prefix onto a category, test that convention directly, including the case where the prefix is absent or ambiguous. Silent misrouting to a configured-but-wrong category produces output that looks checked.

## Collapse the check surface into one entry point

A second, compounding failure mode: the full validation is real but exists only as several independent commands in several places. Anyone running it manually will run a subset and believe they ran all of it.

- **Provide one command that runs the complete suite** and prints a pass, fail or skip line per check plus a single overall verdict. Make this the only documented way to validate. Individual checks may stay available for debugging, but they should not be the documented path.
- **Require every check to report an explicit outcome.** Any check that is skipped, unconfigured, or inapplicable must say so by name in the output and must force the overall verdict to "incomplete" rather than "pass." The aggregate verdict should be unanimous-pass only.
- **Thread the full context through the entry point.** If a check needs a source document, a baseline, or a category to do real work, the entry point should require those arguments rather than let them default to something that makes the check vacuous. Missing context is an error, not a reduced-strength run.

## When a manual path is temporarily sanctioned

If automation is not ready and a stage must be done by hand for a while, write down the scope of "by hand" precisely: which steps a human performs, and which steps remain machine-enforced regardless. The ambiguous case is where a human is authorized to produce the artifact and quietly assumes that authorization extends to verifying it. State that production may be manual while verification stays automated and mandatory, and give that verification a single command (see above) so following the instruction is cheaper than skipping it.

## Verification before you call the change done

- Pass the changed value into every input validator and confirm it is accepted.
- Confirm each keyed dataset returns a non-zero count for it.
- Deliberately feed in known-bad input and confirm the suite fails. A check that cannot be made to fail is not providing evidence.
- Confirm the aggregate command reports every check by name, with no silent omissions.

## Signals you have this bug today

- A validator whose rule set or example set is keyed by some dimension, with no assertion that the set is non-empty.
- Any enumeration written out in more than one place without a test tying the copies together.
- A documented process that is a list of commands rather than one command.
