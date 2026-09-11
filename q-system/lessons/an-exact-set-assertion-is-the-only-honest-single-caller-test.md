---
id: an-exact-set-assertion-is-the-only-honest-single-caller-test
kind: pattern
title: An exact-set assertion is the only honest single-caller test
date: 2026-09-02
---

The first "exactly one caller" test allowed the reporter itself, its config, its manifest fragment and every file under the receipts directory, so a second caller could pass. It also excluded all of `.claude` while the contract excluded only its worktrees. The test now scans tracked files with `git grep` and asserts the set is exactly the plist template and the test. Codex on issue 14 of prd-lessons-rail-and-up-rail.

How to apply:

1. When the contract says "exactly", assert equality with the expected set; an allowlist that keeps growing is a decoration.
2. Define "the tree" as tracked files; untracked runtime state and dead worktree copies fall out by construction instead of by exclusion lists.
3. A bypass selector must select the tests it names; run it once and check the collected count.
