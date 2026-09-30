---
id: validate-then-copy-is-a-race-the-copy-must-be-the-check
kind: pattern
title: Validate-then-copy is a race; the copy itself must be the check
date: 2026-09-02
---

The first promoter validated a path (no symlinks, inside the tree) and then called `cp`. Between the checks and the copy a component could be swapped for a symlink and followed. The fix makes the copy walk both chains with `openat` and `O_NOFOLLOW` relative to directory descriptors, so a swapped component fails the open instead of being followed. A fifo swapped in still hung the open until `O_NONBLOCK` was added. Codex adversarial and the Claude standard pass on issue 7 of prd-lessons-rail-and-up-rail.

How to apply:

1. Pre-checks in bash give readable refusals; the operation that touches the disk must re-establish every property itself, on descriptors it holds.
2. Open the final component with O_NOFOLLOW and O_NONBLOCK, then fstat and refuse anything that is not a regular file.
3. The destination chain needs the same walk as the source chain; symlinks under the target tree are the same attack in the other direction.
