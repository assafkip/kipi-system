---
id: a-retired-component-is-a-decision-not-a-spare-part
kind: methodology
title: A retired component is a decision, not a spare part
date: 2026-10-05
---

When a plan reaches for a component that exists in the tree but not in the live path, the first recon question is why it left the live path. A deliberately retired component carries a decision inside it. Reading it as an intact asset silently reverses that decision, and the reversal never appears in the diff as a reversal: it appears as reuse.

Three independent mechanisms produced one visible symptom here. Each is worth checking separately because fixing any one of them alone leaves the failure reachable.

**1. Recon inventoried capability, not intent.**
The recon pass listed the retired path as working code. It never asked what superseded it or when. An authorization to change WHEN something runs is not an authorization to change WHAT produces it, but a plan written from a capability inventory treats those as the same decision, because both look like wiring.

How to apply: for every component a plan proposes to re-enable, the plan states the date it was retired and the decision that retired it, or states that no such record was found. "It is still here and it still runs" is not a finding about intent. If a prior decision record or stored note says do not re-add this layer, quote it in the plan and argue against it explicitly, or drop the approach.

**2. A single-producer contract was tested only as a side effect of a different switch.**
The test that enforced "only one thing may produce this output" asserted that the alternate entry points raise on call. That assertion was true only because a separate capability was disabled at the time. When that capability was re-authorized, the test was inverted wholesale as part of the re-authorization, and the single-producer guarantee went with it, because no test named it independently.

How to apply: a structural invariant gets a test whose assertion survives every legitimate flip of neighbouring switches. Write it as a positive claim about the live path ("every scheduled unit of work records the producer X"), not as a negative claim about the dead paths ("Y and Z raise"). The negative form is parasitic on the dead paths staying dead, so it has to be deleted the moment they live, and deleting it looks like routine test maintenance rather than removing a guard. Mutation check: flip the unrelated switch and confirm the invariant test still goes red when the invariant is violated.

**3. A producer's admission contract was implicit, so the feeding path bypassed it.**
The producer accepted only inputs of a certain provenance, by design, after a documented evaluation showed every out-of-provenance input failed its quality checks. That restriction lived in a verdict document and in one exception type raised deep inside the producer. A new upstream queue, built from exactly the excluded provenance, was wired directly in as material. A downstream guard caught the result and refused it, which reads as a quality failure rather than what it was: an input the producer should never have been offered.

How to apply: when a component refuses a class of input on purpose, that refusal belongs at the admission boundary, typed and tested, not only in a prose verdict and a deep exception. Then any new feeder fails fast at wire-up time instead of producing refused work at runtime. When you build a new input queue, state its provenance class in one line and match it against each consumer's admission contract before connecting it.

**The shared shape.** All three are the same error at different layers: a constraint that was real, recorded somewhere, and not expressed where the next change would hit it. A decision stored only in prose, a guarantee stored only as a side effect, and a restriction stored only as a verdict are all invisible to the person wiring the next thing. Each one needs a representation on the path a change actually travels.
