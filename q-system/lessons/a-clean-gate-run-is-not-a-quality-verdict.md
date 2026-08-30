---
id: a-clean-gate-run-is-not-a-quality-verdict
kind: methodology
title: A clean gate run is not a quality verdict
date: 2026-08-24
---

Automated checks answer the questions someone was able to encode. The question that matters at review time is usually the one nobody could encode: is this output actually good for its purpose. When every check returns clean and you report "clean" as the verdict, you have silently substituted the checkable question for the real one.

HOW TO APPLY

1. Before running checks, write down the goal in one sentence, in the terms a consumer of the output would use. Keep it separate from the check list. When you report results, report against that sentence first and the check list second.

2. Enumerate what the checks structurally cannot see. Most automated validators inspect properties of a text or artifact, never its fitness. Say this out loud in the report: "the checks confirm X, Y, Z; they cannot tell whether this is worth shipping." A report that omits this line invites the reader to treat green as approval.

3. Treat a non-blocking warning as a finding, not as noise. A warning that is downgraded to advisory in a summary is a detector that fired correctly and was overruled without argument. Read the warning's actual text before deciding it does not matter. If its text describes the defect you would care about, the fact that it was configured non-blocking is a configuration decision, not evidence that the defect is absent.

4. Watch for warnings that repeat across most items in a batch. A signal firing on nearly every item is either a miscalibrated detector or a systemic defect in the batch. Both need a decision. Neither is served by the phrase "warnings only."

5. When a prior review already recorded that these checks cannot judge fitness, that record is binding on the next review. Re-deriving "the checks passed so it is fine" after the limitation has been written down is the same failure committed one layer up.

6. When the output is in a domain owned by a specific reviewer or role, a passing automated run does not substitute for that reviewer. Checks gate mechanics; the owner gates judgment. If the owner was not consulted, say so in the report rather than letting the clean run imply they were.

STOP RULE

Do not write "verified" or "clean" as a standalone conclusion. Write what was checked, what came back, what the checks are blind to, and whether the goal sentence is satisfied. If you cannot answer the last part from evidence, the honest report is "checks pass, fitness unassessed."
