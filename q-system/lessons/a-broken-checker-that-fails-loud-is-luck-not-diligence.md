---
id: a-broken-checker-that-fails-loud-is-luck-not-diligence
kind: pattern
title: A broken checker that fails loud is luck; the same bug inverted passes green forever
date: 2026-08-06
---

A checker has two ways to be wrong about itself, and they are not equally survivable. If its own bug makes it report FAIL, someone investigates and finds it in minutes. If the same bug makes it report PASS, nothing ever investigates, because a green check is the signal to stop looking. The direction a checker breaks in is usually an accident of syntax, not a property of care taken — so a checker that has only ever been seen green has not been shown to work, it has been shown to be quiet.

The habit that catches it: read the checker's own stderr, not only its verdict. A tool that errors and exits non-zero looks identical to a tool that ran and found a violation, and the calling code almost always conflates them.

Observed 2026-08-06 while writing a guard test for `kipi-update.sh`. The check enumerated every comparison against `$DRY_RUN` and asserted each right-hand side was a value the variable can actually hold, using `grep -Eq '^(|--dry-run)$'`. BSD grep rejects an empty alternation branch with `empty (sub)expression` and exits non-zero. The case read that non-zero as "illegal value" and reported all 8 comparisons defective, including the 7 correct ones. It was found only because the words `empty (sub)expression` appeared in the output above the verdict. Written as `^(--dry-run)?$|^$` with the alternation on the other side, the same class of typo would have matched everything, reported 0 violations, and passed for as long as the file existed — while the real dead comparison it was written to catch sat two lines away.

The same run produced the inverse-direction sibling: the enumerator scanned comment lines, so the fix's own why-comment, which quotes the dead comparison it removed, was re-detected as live code. That one also failed loud. Both were luck.

A second instance the same day, in a different shape: a claim was read out of a log line rather than measured. `kipi-update.sh` prints `restored untracked: <path>` for every preserved file, including tracked ones, because the restore loop was written for untracked files and reuses its string. Reading it produced a filed defect asserting that tracked instance-only files were being silently de-tracked across four live instances. Measuring it — `git ls-files --error-unmatch`, `git status --porcelain`, `git cat-file -e HEAD:<path>` — showed the file tracked, clean, and still in HEAD, because the restore runs before staging and the content matches. The defect did not exist. A log line naming a state it never computed is the same class as a docstring claiming coverage it never computed; both are believed because reading is cheaper than measuring.

How to apply:

- Before trusting a checker's green, make it red on purpose for the reason you care about. A checker never seen red is decoration.
- When a checker goes red, read its stderr before believing the finding. `empty (sub)expression`, `command not found`, `No such file` and a real violation all surface as non-zero.
- Never let a tool's exit status stand in for its verdict when the tool can fail to run. Separate "did not run" from "ran and found nothing" explicitly.
- Ask which direction your bug would break in. If the honest answer is "I would not have noticed", add the negative self-test now.
- A state named in a log line, docstring, comment or report is a claim, not an observation. Measure it with the tool that owns that state before acting on it, and especially before filing a defect about it.
