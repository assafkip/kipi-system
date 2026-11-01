---
id: verify-mechanisms-run-not-that-they-exist
kind: methodology
title: Verify Mechanisms Run, Not That They Exist
date: 2026-10-31
---

## Problem

When you assert that a safeguard, job, hook, or integration is "in place," you will tend to prove the cheapest provable thing: that an artifact exists. Existence checks are one keystroke away (search for a string, list a file, check a config key). Execution checks require knowing which log the process writes, whether the component is loaded, whether it matched the triggering condition, and whether any guard or budget suppressed it — four or more commands that differ per subsystem and must be rediscovered each time.

The failure mode is not ignorance. Teams that already have a written rule saying "configuration is not wiring" still violate it within the hour, because a standard that names the bar but supplies no instrument decays to the nearest available measurement.

The danger is not merely under-verification. An existence check can return GREEN on a control that structurally cannot fire — e.g. a guard registered against a matcher group that never sees the operation it was built to intercept.

## How

**1. For every mechanism, write down its execution signature before you claim it works.**

A minimum signature has four parts:
- **Trigger**: the exact observable event that should invoke it.
- **Sink**: where evidence of invocation lands (log, metric, counter, side-effect record).
- **Negative trigger**: an event that should NOT invoke it.
- **Suppressors**: every condition that can silently skip it (not loaded, budget exhausted, disabled flag, upstream short-circuit, matcher mismatch).

If you cannot name the sink, you do not yet have a way to verify the mechanism, only a way to verify its configuration.

**2. Verify with a provocation, not an inspection.**

The accepted proof is: fire the real trigger, observe the real sink, then fire the negative trigger and observe the absence. Inspecting configuration proves intent; provoking behavior proves function. Make the provocation the default verification step and inspection merely a pre-check.

**3. Ship the instrument with the standard.**

Any rule of the form "X must be actually running" must be accompanied by an executable one-liner or script that produces the answer. Bind the instrument to the standard in the same place, so reaching for the rule hands you the tool. Rules without tools are aspirations; the measurement that is easiest to run is the measurement that will be run.

Practical form: a per-subsystem verification command, registered in a single index keyed by mechanism name, that returns PASS/FAIL based on sink evidence from a live provocation. One lookup, one command — competitive with the cheap wrong check.

**4. Make existence checks structurally incapable of passing for wiring.**

Where a cheap check can return GREEN on a dead control, treat that as a defect in the check. Either extend it to assert the trigger path (does the registered condition actually match the intended operation?) or rename/label it so its output cannot be mistaken for a liveness result. Reporting "configured: yes, invoked: unverified" is correct; reporting "present" as "working" is not.

**5. Gate the claim surface that has no gate.**

Audit where assertions about system state are made, and note that published artifacts, external deliverables, and committed code usually have automated checks, while direct conversational or status-update claims to a decision-maker usually have none. That ungated surface is where unverified claims escape.

Close it with a stated discipline plus, where possible, a mechanical aid:
- Any claim that a mechanism is active must carry its evidence inline: the trigger fired, the sink line observed, the timestamp.
- Absent that evidence, state the weaker true claim: "configured but not yet observed running."
- Keep a short, enumerated list of verbs that require execution evidence (running, active, enforcing, blocking, catching, firing) and treat their use without a sink citation as a defect.

**6. Separate design intent from observed behavior in your language.**

Describe what a mechanism is *designed* to do only in the future or conditional tense. Reserve present-tense, indicative claims ("this blocks X") for behavior you have provoked and observed. This single lexical rule catches most instances of intent being reported as fact.

## Review checklist

- Named the trigger, sink, negative trigger, and every suppressor?
- Provoked the real trigger and read the real sink, rather than inspecting config?
- Confirmed the registered trigger condition can actually match the intended operation?
- Does the standard you are applying come with a runnable instrument? If not, write it now.
- Does the claim you are about to make cite evidence, or is it an intent statement wearing the present tense?
- Is the surface you are making the claim on gated, or is this the ungated one?
