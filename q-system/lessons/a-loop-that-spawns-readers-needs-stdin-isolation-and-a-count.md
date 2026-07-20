---
id: a-loop-that-spawns-readers-needs-stdin-isolation-and-a-count
kind: pattern
title: A loop that spawns readers needs stdin isolation and a count invariant
date: 2026-07-20
---

When a loop reads its items from a stream on file descriptor 0 (e.g. a `while read` fed by process substitution or a pipe), any command inside the body that also reads standard input will steal from that same feed. The reader drains the loop's queue, so iterations silently vanish and the loop exits early with no error. Two independent defenses are required, and neither is optional.

First, isolate every child's stdin. Redirect any command in the loop body that might read input away from the loop's feed (point it at the null device), or move the loop's own feed onto a dedicated descriptor and read from that descriptor explicitly, leaving fd 0 free for children. Do not assume a body command is stdin-safe just because it usually is; a single interactive or input-consuming subprocess is enough to truncate the whole pass.

Second, assert a completion invariant inside the loop, not only after it. "It ran without error" is not the same as "it processed everything." Count the inputs at the start and the completed units of work at the end, and fail loudly when they disagree. The dangerous case is a mid-sequence item that behaves differently from the rest (for example, one that triggers the stdin-stealing child); a test must exercise that exact condition and prove the loop still visits every item. An after-the-fact audit that notices the shortfall later catches the symptom but does not prove the loop iterates the full set.

The general rule: a stream-fed loop is a shared, drainable resource. Protect the feed from its own body, and prove the iteration count end-to-end with a test that includes an item capable of breaking it.
