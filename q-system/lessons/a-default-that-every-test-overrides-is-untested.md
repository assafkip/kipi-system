---
id: a-default-that-every-test-overrides-is-untested
kind: pattern
title: A default that every test overrides is untested
date: 2026-09-07
---

**The shape.** A parameter has a fallback: when the caller omits it, the code resolves it to a deployment value. A safety convention then says every test must pass that parameter explicitly, so no test can touch a live resource. The convention is correct, and it carves a blind spot shaped exactly like itself. The suite now exercises only the supplied branch. Production runs the omitted branch. The suite is green, the deployed path is broken, and neither is lying.

The same shape appears wherever a rule forces callers to be explicit: required-argument lint, a fixture that always injects config, a wrapper that every caller passes through with all fields set. Any branch reachable only by omission is invisible to a suite that never omits.

**How to spot it before it ships.** For each value with a fallback, ask which branch the tests take. If the answer is "all of them supply it, deliberately, for safety", that fallback has zero coverage no matter how many tests call the function. The metric is the count of tests that OMIT the argument, not the count that use it. Zero is the finding.

**How to cover it without giving up the safety.** Do not assert the side effect; the side effect is what forced the explicit value in the first place. Assert the ARGUMENT instead. Replace the callee with a recording stub, invoke the wrapper with the parameter omitted, and check what the wrapper handed down. That pins the resolution logic while touching nothing live, so the safety rule and the coverage stop competing.

**Two branches, two tests.** Resolution usually differs by environment: omitted under normal operation resolves to the deployment value, omitted under test conditions resolves to something inert so nothing can be written. Both need their own test. Adding only the first quietly trades away the protection that motivated the convention, and the loss is silent because the remaining test still passes.

**The general rule.** A safety convention that constrains how callers invoke code also constrains what the suite can observe. Whenever you add one, name the branch it just made unreachable from tests, and cover that branch by inspecting arguments rather than effects.
