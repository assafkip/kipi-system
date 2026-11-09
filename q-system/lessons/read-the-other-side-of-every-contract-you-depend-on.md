---
id: read-the-other-side-of-every-contract-you-depend-on
kind: methodology
title: Read the Other Side of Every Contract You Depend On
date: 2026-11-09
---

When code starts depending on a contract it does not own (an external API's enumerated status values, another script's exit codes, a downstream system's dedup or identity key), engineers tend to write against their mental model of that contract instead of its actual definition. The belief is usually plausible and usually wrong at the edges, and only the other side's code reveals where: a status value that bundles several conditions (some of which your own logic already treats as non-blocking), or a 'success' exit code that covers several outcomes, most of which did nothing for your case. Repeated review rounds that each find a new flaw of this shape point to a process gap, not bad luck.

How to apply:
1. Inventory the outside contracts. For every new dependency, write down the exact values, codes, or keys you rely on and what you assume each one means.
2. Read the source of truth. Open the other side's implementation or authoritative documentation and list every path that produces each value. If one value maps to several outcomes, your code must tell them apart, or the contract must change so it can.
3. Reuse your own existing interpretation. If the codebase already classifies the same upstream data somewhere, route through that logic instead of writing a second, divergent table.
4. Test the contract, not your belief about it. Tests written from the same assumption as the code cannot fail. Build fixtures from real captured payloads or the real component's output shape, not hand-written tables.
5. Make fakes able to disagree. A stub that always returns success with empty output hides every interesting case. Give fakes a mode for each distinct outcome the real dependency can produce, including 'succeeded but did nothing for this input' and 'deduplicated against an earlier item.'
6. Assert on what the dependency actually uses. If a downstream system computes an identity or dedup key after normalizing or stripping parts of the input, assert on the computed key, or run the real normalizer in the test. Asserting that the raw message contains an identifier proves nothing if that identifier is removed before the key is formed.
7. Add a distinguishing case. For dedup and identity behavior, always test two inputs that should be treated as distinct and confirm they are.

Review heuristic: for each external value the change reads, ask 'where is this produced, and have I seen that code?' If the answer is no, the review is not finished.
