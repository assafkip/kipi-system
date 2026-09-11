---
id: a-pipe-in-a-grep-pattern-is-literal-under-basic-grep
kind: pattern
title: A pipe in a grep pattern is a literal character under basic grep
date: 2026-09-02
---

kipi-push-upstream.sh joined its tripwire terms with `|` and called plain `grep`, which reads `|` as a literal pipe under basic regular expressions. The pre-push scan that keeps client names out of the skeleton matched nothing at all, and every push read as clean. Caught by Codex on prd-lessons-rail-and-up-rail issue 8; the inline list it replaced had used `\|`.

How to apply:

1. When a pattern is built by joining alternatives, run grep with `-E` and pin it with a test that plants one term and proves the scan blocks.
2. A scan that never fires is indistinguishable from a scan that has nothing to find. Give every tripwire a positive control in its test.
3. Treat "it matched nothing" on a guard as a finding, never as a clean result.
