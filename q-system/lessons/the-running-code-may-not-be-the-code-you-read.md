---
id: the-running-code-may-not-be-the-code-you-read
kind: methodology
title: The running code may not be the code you read
date: 2026-08-11
---

A test asserted `40 <= 25` and named a module constant as the source of the 40. The file said 25. `git show HEAD` said 25. The module's own `__file__` pointed at that file, and reading line 99 of that exact path printed the 25. The value was 40 anyway, and nothing anywhere assigned it. A cached bytecode file compiled from an older source was being imported instead, and it passed its own validity check because the edit changed `40` to `25` without changing the byte count and the two files shared a modification time to the second.

How to apply:

1. When source and behaviour disagree and you have already checked the obvious writers, suspect the artifact between them before you suspect your reading. Compiled caches, build outputs, installed copies, vendored duplicates and plugin clones all sit in that gap, and each one can be stale while every check you would naturally run says the source is fine.

2. Prove which bytes execute, not which bytes exist. Printing a module's path proves where it came from. It does not prove the interpreter used it rather than a cache derived from an older version of it. The cheap decisive test is to delete or bypass the intermediate artifact and see whether the answer changes.

3. Distrust staleness checks built on metadata rather than content. Timestamp-and-size validation is a heuristic, and same-length edits to a constant defeat it exactly when you are tuning a threshold, which is the most common reason to make a same-length edit.

4. Treat a suite that ran against a stale artifact as unrun, including the green parts. A stale cache produces a false pass as readily as a false failure, and the passes are the ones nobody investigates. Re-run after clearing it and say plainly that the earlier result did not count.

5. Make the check executable once you have paid for the lesson. Recompile the current source and compare it against whatever the cache holds; any disagreement means an import could serve the stale copy. Give that check a negative self-test that reconstructs the same-size, same-timestamp condition, or it will silently be testing nothing.

The reason this one is expensive is that every instinct for verifying it, reading the file, diffing it, printing its path, agrees with you and is wrong together.
