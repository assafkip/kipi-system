---
id: a-registry-driven-guard-cannot-see-an-unregistered-actor
kind: pattern
title: A registry-driven guard cannot see an unregistered actor
date: 2026-09-07
---

When a system protects a resource by declaring an invariant ("nothing may write to X") and enforcing it with a checker, the checker usually validates the entries in a registry: a list of known writers, jobs, or components. That design has a hole. The registry is populated by hand at the time each component is added. A new component that writes to the protected resource without registering itself is invisible to the checker, so the checker returns OK precisely when the invariant is being violated. The guard reports green while the damage accumulates.

HOW to close it:

1. Derive the actor list from the system, not from the declaration. Enumerate who actually touches the resource by scanning source for the write primitive, by instrumenting the access layer, or by reading the resource's own audit trail. Diff that derived set against the registry and fail on any member that is only in one of them. A registry entry with no code is dead; code with no registry entry is the hole.

2. Put the check at the choke point, not at the edges. If every write must pass through one function, client, or credential, the invariant can be asserted there at call time and no registration step is needed. A guard that runs beside the write path is advisory; a guard that runs inside it is enforcement.

3. Prove the guard can go red. Before trusting it, add a writer that violates the invariant and confirm the checker fails. A guard that has only ever been observed passing is untested. This is the same failure as a test that has never been seen to fail.

4. Treat a manual or one-off mutation of the protected resource as unguarded by definition. Nothing that runs later can retroactively validate it, so record its scope and its reversal path at the time it happens, and count it as an open risk until the resource is re-derived or verified from source.

5. Separate the risk you were asked about from the risk that exists. When someone asks whether a specific component (a model, an external service, a new dependency) can corrupt the data, answer it with evidence, then state where the integrity risk actually lives. Answering only the question asked leaves the real hole undocumented.

The general shape: any enforcement built on self-declaration inherits the completeness of the declaration. Where you cannot make declaration mandatory, make the check derive its own inventory.
