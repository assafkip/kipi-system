---
id: trace-every-new-output-to-its-consumer-before-calling-a-fix-
kind: methodology
title: Trace every new output to its consumer before calling a fix done
date: 2026-11-09
---

When a fix adds or changes something another component reads (a log or alert line, a message, a record, a key), reading the code that produces it and the place it is written is not enough. Find the code that consumes it and read what that code assumes. Fix rounds that only answer the finding they were handed can keep failing because no round asks who reads the new output.

Method:
1. Map producer -> write site -> consumer(s) before editing. For each consumer, write down its contract. Examples: which fields it parses, whether it derives an identity, dedup key, or fingerprint from the content, and whether it expects that value to stay stable over time. Contracts like this are often documented near the write site, so read the code around the edit and not only the changed lines.
2. Check whether the change breaks that contract. A common failure is putting variable data (names, counts, lists of affected items) into a string that a downstream system hashes or groups by. Each change in that data then looks like a new event, so you get duplicate tickets or alerts.
3. Test through the real consumer, not just the producer. Asserting that the output 'contains X' can lock the defect in place. Write a test that sends the produced output through the actual consumer and checks the consumer-level property, such as 'one ticket regardless of which items are affected', while the underlying data varies.
4. Make the guard general. A test that covers only the one output you just fixed leaves every future output of the same kind unprotected. Prefer a parameterized or contract test that runs every output from that producer through the consumer, so new entries get checked automatically.
5. Check handoff and status claims against the real state, not your mental list. Before saying 'all work is pushed' or 'this item is still waiting on rework', list the actual workspaces, branches, and worktrees on disk and compare each one to the remote. Claims built only from the branches you remember can hide finished but unpushed work. That leads to wrong hold or deferral decisions on work that is already done.

Quick checklist for any change that emits output: Who reads this? What do they derive from it? Does my change alter that derivation? Is there a test that goes through the real reader? Does that test cover the next output someone adds? Is everything I claim is done actually pushed?
