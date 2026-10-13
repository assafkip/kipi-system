---
id: verify-quality-gates-against-real-output-per-item-and-confir
kind: methodology
title: Verify quality gates against real output, per item, and confirm live before calling done
date: 2026-10-12
---

When you add a filter or quality gate to a system that produces composite output (a digest, report, or message containing many items), apply these practices:

1. Define the contract per item, not per document. If the requirement is that each entry is actionable, valid, or appropriate, evaluate each entry on its own. A whole-document pattern match passes as soon as one entry satisfies it, so the other entries leak through. State the per-item rule explicitly and test it.

2. Treat a single observation as an observation, not a fix. If a bad item disappears on one run, check whether something removed it or whether it merely ranked lower that day. Record a fix as verified only when a rule or test would make it disappear on every run, including quiet days with little competition.

3. Test with real captured output, not just fixtures written to match the rule. Fixtures authored alongside the rule only prove the author's assumptions. Add a regression suite that replays genuine production outputs (a full day's worth, across every job type) through the gate and asserts on the result.

4. Test the exemptions as well as the rule. Each carve-out added to stop false rejections (quoted text, threads, informational jobs) opens a possible leak. For every exemption, write a test that tries to slip bad content through that path, alongside the test that proves legitimate content still passes.

5. Balance both failure directions. Review time spent only on over-blocking will let under-blocking go unnoticed. Track and test both false rejections and leaks.

6. Define done by the outcome that reaches the user, not by merge and green tests. If the acceptance criterion concerns what appears in the destination (a channel, inbox, or dashboard), do not declare success until you have read the first full real cycle of output after deployment. Add a post-deploy check that reads the live destination where practical.

7. Classify source items by content, not only by structure. If inclusion is decided by position or state (whose turn it is, who wrote last), non-requests such as receipts, thank-yous, notices, and closed matters will be included. Add an explicit step that decides whether each item is a real request before it enters the output.
