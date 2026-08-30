---
description: A generation loop repairs what has one correct answer before it gates (repair-first)
paths:
  - "**/voice-lint.py"
  - "**/make_social.py"
  - "**/voice_send_gate.py"
  - "**/voice_channel_registry.py"
  - "gtm/scripts/podcast/**/*"
  - "gtm/config/voice-channels.json"
---

# Repair-First: a generation loop fixes what it can before it gates (ENFORCED)

Founder, 2026-08-03: *"we need to fix that earlier in the loop so things get
capitalized and not blocked ... and not continuously blocked because the
capitalization doesn't work."*

Restated 2026-08-10: *"the rule was that you dont reject - you fix until it can
come out."*

## The rule

When a generation loop gates output on a deterministic rule, and that rule has
exactly ONE correct answer a machine can produce, the loop REPAIRS the output and
carries on. It does not reject, and it does not spend a regeneration.

Rejecting is reserved for what a machine cannot decide: word choice, substance,
banned language, voice. Those are the writer's job.

## The split, and why conflating the two halves is the whole defect

One lint rule routinely covers two different defects that need OPPOSITE treatments.
Decide which half you are looking at before you touch anything:

| Shape | Treatment | Why |
|---|---|---|
| One correct answer exists (a lowercase English sentence start, a bare `i`) | **REPAIR in place** | The machine can produce it. A regeneration spent here may come back wrong in a new way. |
| The output is already correct and the rule is wrong for this lane (`pi-from-scratch`, `phone-harness`, a URL) | **RELAX at the lane**, never repair | "Fixing" it CORRUPTS the value. Capitalizing a tool name breaks the tool name. |
| A human judgement (banned words, substance, voice) | **BLOCK** | Not a machine's call. |

Relaxation is lane-scoped, in the channel registry, never in the fleet linter. A
fleet-wide exemption to unblock one lane is the wrong blast radius: it silently
weakens the rule for every instance to fix one job.

## Enforcement (the executables)

- **The repairer:** `q-system/.q-system/scripts/voice-lint.py --fix <file>`.
  `repair_capitalization()` is pure and takes `check_capitalization`'s own
  violations as its input, so the repairer can never disagree with the checker
  about what a sentence start is. `CODE_ISH_TOKEN_RE` is the leave-it-alone test
  and exempts nothing from the CHECK.
- **Its tests:** `q-system/.q-system/scripts/test_voice_lint_caps.py`, classes
  `RepairFirstFixesProseAndLeavesIdentifiersAlone` and
  `TheFixModeExitCodeIsUsable`. Both halves are asserted, including a case proving
  repair CLEARS the block it was repairing.
- **The lane relaxation:** `gtm/scripts/voice_send_gate.py` `DIGEST_DOWNGRADE` +
  `JUDGE_SKIP_TYPES`, resolved through `gtm/config/voice-channels.json`.

## The caller's obligation

**Check the repair step's exit code.** A repair step that fails must be loud.

`--fix` exits 0 whether or not anything needed repairing, because "nothing to fix"
is success; a caller treating it as failure would hold every clean draft, which is
the opposite of this rule. It exits 1 only on a real fault.

## Scar

2026-08-03 the directive was recorded as a CODE COMMENT at
`gtm/scripts/podcast/make_social.py:217`. It was in no rule file, no decision log,
and no test. The comment described a `--fix` mode nobody had built, and the caller
discarded the exit code, so the call hit the usage branch and exited 1 on every run
for a week while claiming casing was being repaired.

The loop quietly reverted to reject-and-regenerate. On 2026-08-10 the daily social
job died three times and shipped nothing, and the printed reason
(`[capitalization] sentence starts lowercase: 'pi-from-scratch'`) was a diagnostic
from a raw re-lint that the decision path never consulted. A week of silence, a
misleading error, and a founder directive that had never executed once.

A rule that names no executable is prompt-only. That is why this file names three.
