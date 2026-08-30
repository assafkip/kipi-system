---
id: read-the-rows-a-fix-turns-blank-the-real-defect-is-under-them
kind: pattern
title: Read the rows a fix turns blank; the real defect is usually under them
date: 2026-08-11
---

A correct fix that stops producing a wrong value does not automatically start producing the right one. It produces nothing, and nothing looks like success: the bad values are gone, the tests are green, the count of defects drops. The rows that went empty are the most informative output of the change and the easiest to skip past, because an empty cell reads as "correctly declined" rather than "still broken, one layer down".

Observed 2026-08-11. Thirty records carried a field label where a person's name belonged, because the name rule was "the first leftover line with no digits" and a masked `Order Number: #1576361` leaves the bare string `Order Number:`. Teaching the rule to refuse labels was right and it fixed four records. Twenty-six went blank. Reading those twenty-six showed the actual cause: the customer's name was written on the same line as the deal separator, `3#Barb Donaldson`, so the digit disqualified the only line that held a person. The label had merely been winning a race nothing else could enter. Fixing that recovered twenty-eight of thirty, and the two that stayed blank turned out to be messages with genuinely no name in them.

The same session produced the inverse error twice, which is what makes the pair worth recording. A blank-cell audit reported zero defects while a cell that was FILLED AND WRONG sat in the same column: the source said `1gb+ tv` and the field said `1G`. An audit scoped to emptiness cannot see a value that is present and incomplete, and "not all the info is there" from a user covers both.

How to apply:

1. After a fix that can decline, count what it declined and read those records individually. If the count is larger than the count it corrected, the fix is a symptom patch and the cause is one layer down.
2. Never report the drop in bad values without reporting where they went. "Thirty wrong became four right and twenty-six empty" is the honest sentence; "thirty defects fixed" is not.
3. Audit for wrong separately from audit for missing. They need different queries and one will not surface the other. A user complaint about incomplete data means both.
4. Prefer a fix that makes the right value reachable over one that only stops the wrong value being chosen. The first is a cause, the second is a race.
5. When a rule picks "the first thing that qualifies", enumerate what was disqualified before trusting what won. The winner is often only the last one standing.
