---
id: never-let-a-failed-read-of-an-identity-anchoring-secret-beco
kind: pattern
title: Never let a failed read of an identity-anchoring secret become a create
date: 2026-07-06
---

A value that anchors durable identity — an encryption key, a signing salt, anything downstream artifacts are bound to — must never be fetched with get-or-create semantics once the system is past first provisioning. Get-or-create is correct exactly once: when nothing exists yet. On an already-provisioned system it silently converts "I cannot read the secret right now" into "therefore none exists, so mint a new one," which is an irreversible identity reset that orphans every artifact keyed to the old value.

HOW to build it safely:

1. Split provisioning from retrieval. Have two distinct code paths: create (may only run when no durable state exists) and fetch (must succeed or hard-fail; it may never fall through to create). One function that does both is the bug.

2. Guard the create path with a positive existence check, and order the check before the mint. Ask "does durable state already exist?" first — the presence of the artifact that the secret protects is itself proof the secret must exist. If that artifact is on disk, a failed read is an error to surface, not a signal to re-mint. Do not consult the artifact only after the secret could already have been regenerated; the check has to gate the mint, not trail it.

3. On an existing install, a read failure is an environmental fault (locked store, permission loss, transient backend). Fail loudly and stop. Re-minting cannot recover it and actively destroys recoverability.

4. Test the seam, not around it. Mocking the identity boundary lets a green suite coexist with a dead system, because the exact layer that drifts is never exercised. Add a test that runs the real store against a real pre-existing artifact and asserts the anchoring value is unchanged after a second startup. Testing that you can recover after the value changes is not the same as testing that it never changes on an existing install — cover the prevention case, not just the recovery case.

5. Watch for surface-patch momentum. Repeated downstream cleanups (dedupe, retire, replace, upsert) that manage damage already done are a signal the wound is upstream. If the same failure reopens under a new surface each cycle, the fix belongs at the source that lets identity drift, not at each place the drift surfaces.
