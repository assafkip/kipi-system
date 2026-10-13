---
id: diagnosing-why-only-one-node-fails-a-fleet-wide-template-syn
kind: methodology
title: Diagnosing Why Only One Node Fails a Fleet-Wide Template Sync
date: 2026-10-12
---

When a shared template is pushed to many downstream copies and only one keeps failing, treat it as a set of independent causes and check three things.

1. Compare pre-commit gates across all targets. Measure what each target actually runs at commit time instead of assuming uniformity. If one target runs tests or checks that exercise its own code against the incoming template files, any template change that those checks depend on needs a matching local change. A sync that commits only template files cannot supply that change, so that target fails while targets without such gates never do. Fixes: make the dependency explicit, let the sync carry or trigger the paired change, or run those checks outside the sync commit path.

2. Check the state of the sync target itself. If the sync writes into a long-lived working checkout, find out which branch it is on and how far it lags the main line (commits behind, files differing). Gates run the checkout's local copies of tests and code, so a fix already merged upstream still fails until the checkout is brought forward. Fixes: have the sync fast-forward or rebase the target, or use a fresh clean worktree, before applying changes, and fail early with a clear message when drift exceeds a threshold. Existing drift metrics are not enough unless something acts on them.

3. Detect local edits to template-managed files. If a downstream copy edits files owned by the template in place, the next sync will correctly refuse them as the target being ahead. Fixes: route such edits upstream first, or mark ownership clearly with guards, such as a pre-commit check that rejects local changes to managed paths, and provide a documented path for promoting local improvements to the template.

General method: enumerate what differs for the failing node (gates, branch state, local modifications), measure each with a dated, concrete number, classify each cause (implicit contract vs. process), and fix each independently, since resolving one will not clear the failure while the others remain.
