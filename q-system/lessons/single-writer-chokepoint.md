---
id: single-writer-chokepoint
kind: pattern
title: Route every mutation of a shared resource through one writer
date: 2026-06-19
---

When more than one code path can mutate the same shared resource (a file, a folder, a config), route every mutation through a single helper and add a test that greps the tree to prove no caller bypasses it. Two writers on one resource is the failure mode: each is correct alone, together they clobber or race. Migrate existing call-sites one small, independently revertible edit at a time, not one bulk rewrite. The grep-the-tree test is what keeps the chokepoint a chokepoint as the code grows.
