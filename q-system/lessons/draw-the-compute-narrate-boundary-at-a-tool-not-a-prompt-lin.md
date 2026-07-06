---
id: draw-the-compute-narrate-boundary-at-a-tool-not-a-prompt-lin
kind: pattern
title: Draw the compute-narrate boundary at a tool, not a prompt line
date: 2026-07-06
---

When a system splits work so deterministic code owns the numbers and a model narrates them, that split is only real where a tool boundary and a validator enforce it. A prompt sentence that says 'code computes, the model only summarizes' is not enforcement; it is a hope. Wherever a needed value has no tool but the raw ingredients to derive it are already in the model's context, the model will silently compute it and can get it wrong. And any value that depends on state the model was never handed (the current moment, the active scope, the unit basis) will be guessed. Three failure shapes reduce to one cause: the boundary rests on author-written prose, and the context is missing facts it needs.

HOW:

1. Give every stated value its own tool. Enumerate each number, ratio, share, or status the narrator will emit, including the derived ones (a part-of-whole, a total, a delta). Each gets a deterministic function that computes and returns it. If a value has no tool, the boundary does not exist there, no matter what the prompt says.

2. Never hand the model the primitives to fake a number you did not give it a tool for. Passing raw components 'for context' while withholding the tool that combines them is an open invitation to freelance the arithmetic. Either provide the computed result or withhold the primitives; do not do both.

3. Validate the output against its own invariants, not just the inputs. A share of a whole cannot exceed the whole; a set of parts sums to the total; a scoped result is non-empty when its scope is populated. Assert these on the assembled artifact and fail when they break. A prompt rule is caught by a reader; an invariant check is caught by the build.

4. Inject every context-dependent fact the reasoning needs, especially the free ones. If any step depends on the current time, the active period, the unit basis, or the caller's scope, and that fact is already computed elsewhere in the system, the cost of injecting it is near zero and the cost of omitting it is a confidently wrong answer. A required input the model cannot derive on its own is a defect in the context assembly, not the model.

5. Make missing required inputs fail loudly. When a tool or step declares an input as required and it is absent, halt or flag; do not let the path proceed on an empty or defaulted value that reads as a valid (but hollow) result.

The through-line: the line between 'computed' and 'narrated' holds only where a tool produces the value and a check guards it. Anything left to the narrator's discretion, or to context it was never given, is a value waiting to be wrong.
