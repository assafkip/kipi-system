---
id: derive-a-value-from-its-owner-never-restate-it-in-a-test
kind: pattern
title: Derive a value from the code that owns it, never restate it in a test
date: 2026-08-10
---

When a test needs a value the shipping code already owns -- a list of required files, a set of schema fields, a set of excluded paths -- copying that value into the test creates a second source of truth. The copy agrees on the day it is written, which is exactly what makes it look safe, and it keeps agreeing until the moment the real value changes. Then the test goes on asserting the old contract and passes, while the thing it guards has moved.

This is not the same defect as a stale assertion someone forgot to update. A stale assertion usually goes RED and gets noticed. A restated value goes GREEN and retires the question, because the test is still internally consistent -- it just no longer describes the system.

Three instances in one session, all in one test suite, and only the third was found by looking rather than by being bitten:

**A hand-maintained fixture list.** The fixture enumerated the files a script invokes from its own directory. A new fail-closed dependency was added to the script and never added to the list, so the fixture built an incomplete tree, the script aborted before doing any work, and two tests failed on a missing fixture rather than on anything they assert. A comment sitting directly beside the list already documented that exact failure mode from a previous occurrence. A comment describing a trap next to the trap is not a guard, because a comment cannot fail.

**A set of excludes that moved.** The tests parsed literal `--exclude=` flags at the call site. The shipping code consolidated its excludes into one helper feeding four consumers, precisely because the duplicated list had drifted. The test's parser then read a correctly-hardened command as having ZERO excludes and reported it unprotected.

**A field set that matched exactly.** A test declared two sets of field names directly below a constant pointing at the JSON schema that owns them. Both sets matched the schema perfectly. That match is the whole hazard: nothing looks wrong, no test fails, and the copy silently becomes the old contract the next time a field is added or removed.

The fix in every case is the same shape: read the value from whatever owns it, at run time, and assert that the derivation returned something. An empty parse turns every downstream check into a no-op that reads as green, so the derivation needs its own floor.

Where the value genuinely cannot be derived -- the owner is a compiled binary, a remote service, a human decision -- the second-best answer is a divergence check: a test that fails when the two lists stop matching. That is strictly worse than deriving, because it must itself be maintained, but it fails loudly instead of passing quietly.

How to apply:

1. When writing a test that needs a list, a set, or a constant, ask who owns it. If the answer is "the code under test" or "a schema in this repo", derive it rather than typing it.
2. Treat exact agreement between a test constant and a shipping constant as a finding, not as reassurance. It means the two are coupled with nothing enforcing the coupling.
3. Give every derivation a floor: assert the parse returned a non-empty result. A regex that stops matching after a refactor otherwise silently disables the checks built on it.
4. Verify the derivation is BOUND, not merely equal. Mutate the source of truth -- add a field to the schema, remove an entry from the list -- and confirm the test changes its result. If it does not, the derivation is not reading what you think.
5. Confirm the derived value equals the previous literal before committing, so the change lands as a refactor rather than as a quiet relaxation of what was being checked.
6. When you find one instance, sweep for the others in the same suite rather than waiting to meet the second and third. The sweep is cheap and the pattern clusters, because the same author solved the same problem the same way more than once.
