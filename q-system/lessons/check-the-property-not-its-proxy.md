---
id: check-the-property-not-its-proxy
kind: pattern
title: Check the property, not its proxy
date: 2026-10-05
---

A gate can stay green while the thing it guards is unplugged. This happens when a name, docstring or heading states a property and the code that runs checks something cheaper nearby.

Why it happens: the author checks what is observable from where they stand. A test written beside a helper calls the helper. A gate registered beside a data builder builds its own inputs inline. Observing the real property needs an end-to-end run. The proxy costs one line, so the proxy wins.

A second cause: in a suite that blocks live model calls, every model answer is hand-typed. That block is correct because tests must be cheap and deterministic. But it means no test ever sees output a real model produced, and nothing replaces that coverage unless you build it.

How to apply:

1. For each gate, write the property in one sentence, then name the artifact the check actually reads. If that artifact is not the thing the sentence describes (a file standing in for the prompt built from it, a hand-written sample standing in for real data), you have a proxy.
2. Build the red input first: the case where the real property is violated but the proxy still holds. Run the gate against it. If it passes, the gate is decoration.
3. Bind the check to the real path. Make the test read the same inputs the production path reads, or assert on the final rendered output the consumer receives.
4. Replace hand-typed external outputs with captured ones. Record real responses once, in a fixture that must carry a provenance block (source, capture date, version). Make the loader refuse any fixture without that block. Refresh captures on a schedule so the fixtures cannot drift from reality.
5. Give every multi-item run a floor. If some items fail, define the minimum success count or ratio below which the whole run fails, so partial failure cannot read as a pass on whatever remained.
6. Check which parts of the system have a real-output fixture and which have none. The uncovered list is your blind-spot map.
