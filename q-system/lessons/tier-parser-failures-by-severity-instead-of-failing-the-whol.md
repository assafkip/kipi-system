---
id: tier-parser-failures-by-severity-instead-of-failing-the-whol
kind: pattern
title: Tier parser failures by severity instead of failing the whole run
date: 2026-10-19
---

When a pipeline consumes output from a nondeterministic producer (such as an LLM), do not make every parse-layer check a whole-run refusal. Treat 'this output is unsafe' and 'this output is shaped unusually' as different classes, and give them different consequences.

1. Audit each validation rule and ask what concrete harm it prevents. If a rule guards nothing that can reach a protected sink (for example, a formatting restriction on text that is already discarded before use), downgrade it or remove it. A rule whose own comment says the condition cannot occur in practice deserves the same scrutiny.
2. Sort rules into tiers. Safety and integrity rules (anything that could leak, corrupt, or publish something wrong) stay hard-fail. Shape and cosmetic rules should normalize, salvage the valid portion, skip only the affected item, or log a warning, so one odd item does not discard the rest of the batch.
3. Prefer item-level rejection over run-level rejection. Isolate the failure to the smallest unit that is actually bad.
4. Validate limits and caps against real data. A threshold chosen by assertion is a guess; check it against observed production-like inputs before enforcing it as a hard stop.
5. Test parsers with the shapes the producer actually emits, not only idealized fixtures. Collect real or recorded outputs, including messy ones (extra prose, code fences, trailing text, unusually large or small counts), and keep them as regression cases.
6. When a failure recurs in the same form, treat it as a design defect in the contract (all-or-nothing on a variable producer) rather than patching only the latest symptom.

Result: strict where it protects something, tolerant where it only reflects variability, and tests that exercise real producer behavior.
