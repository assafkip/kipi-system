---
id: a-file-that-fans-out-must-pass-the-gates-of-every-destination
kind: pattern
title: A file that fans out must pass the gates of every destination
date: 2026-09-02
---

Two defects in one PRD, same class. The receipts file was named `.jsonl`, which the skeleton and every instance gitignore, so the fanned-out copy would have stayed untracked in each instance and the push guard would have refused every push after the first receipt. And a receipt row carried the instance's absolute path, which contains `/Users/` and the owner's name, two tripwire terms the push scan refuses. Both were invisible in the skeleton and would have broken the fleet on the first fan-out. prd-lessons-rail-and-up-rail issues 9 and 11.

How to apply:

1. Before adding a file under a fanned-out tree, run the destination's own checks on it: `git check-ignore`, the tripwire scan, the guards that read it there.
2. Never write a machine-local value (home path, username, hostname) into a file that leaves the machine. Record a registry name instead.
3. Pin the rule with a test that scrubs the artifact against the same term list the gate uses.
