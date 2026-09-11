---
id: a-predicate-whose-false-branch-is-unreachable-reports-suc
kind: pattern
title: A predicate whose false branch is unreachable reports success by construction
date: 2026-08-20
---

"A check must be able to fail" is usually taught as a discipline: name the input that makes it red, then watch it go red. That framing catches the checks nobody bothered to test. It does not catch the larger class, where the check *was* tested, the test *did* go red once, and the false branch is nonetheless unreachable in production for a reason that has nothing to do with the assertion.

The sharper statement: **any predicate whose false branch is unreachable reports success by construction.** Not because it is wrong, but because it is no longer a predicate. It is a constant wearing a conditional's syntax. The tell is never in the assertion — it is in the input path that feeds it.

## Five costumes in one day, one lane

All five surfaced on 2026-08-20 in the consulting CRM card lane. Same shape, five disguises, and no two would have been caught by the same review.

**The counter that counts the wrong bucket.** A poll counter reported abstains as applies. 179 polls said the lane was working while it had closed nothing from natural language. The counter incremented correctly on every branch it knew about; it simply had no branch that could report failure. Fixed in 744b0ace.

**The empty set that can never match.** A `founder_ids` argument defaulting to an empty set would have positively identified nobody, forever, and reported a clean zero routed. The membership test was correct. Its false branch was the only branch. Caught before shipping, in the same session that fixed the counter — by the person who had fixed the counter.

**The heartbeat where zero and never-ran are the same value.** `dropped_not_for_client` is durable and nothing reads it, so a 0 cannot be distinguished from a skipped run. A metric with no liveness signal answers "healthy" identically to "dead."

**The guard that saw no input.** A pre-push hook parsed git's stdin to find contaminated refs. Standalone, fed by hand, it was red on the bad sha and green on four controls. Wired, lefthook consumed stdin first to build its own templates, so the loop iterated over nothing and returned 0. A real `git push --dry-run` of the exact branch it existed to block printed a clean pass. The predicate was fine. It was never handed a subject.

**The mutant that survived on prose.** Deleting a required field from a JSON schema in a prompt left the test green, because the paragraph underneath the schema still contained the field's name. The assertion matched a substring that another part of the file also produced — so the schema could vanish entirely and the check would still pass.

## Why review does not catch it

Each of these reads correctly line by line. The counter increments, the set is tested for membership, the loop iterates, the assertion matches. Review simulates the *logic*, and the logic is sound. What review does not simulate is the **arrival of the input**: whether the set is ever non-empty, whether stdin still holds refs by the time this consumer reads it, whether the matched substring has a second producer.

This is why "I tested it and watched it go red" is necessary and not sufficient. The guard above went red under hand-feeding and was inert under lefthook. The test and the production caller disagreed about how the input arrives, and only the production caller was authoritative.

## The check that generalises

For any predicate that gates behaviour, ask the question one level up from the assertion:

- **Name the production input that reaches the false branch.** Not a test input — a real one, and the path it travels to get there. If you cannot name it, the branch is decorative.
- **Run the predicate the way its real caller runs it**, not the way it is convenient to call. The guard's test now runs the script with no stdin and cwd at a repo, because that is what lefthook does. That version of the test is the one that would have caught the inert version.
- **Distinguish zero from never.** A counter, a metric, or a returned collection needs a liveness signal separate from its value, or its healthy state and its dead state are the same bytes.
- **Assert where the value is decided, not where it is shown.** Three mutants survived on three consecutive issues in this lane, every one a test asserting a result that other code also produced. The prose-and-schema mutant is the pure form: match the token the machine consumes, not the word a human also wrote nearby.

The related lesson [[a-check-must-be-able-to-fail-for-the-reason-you-care-abou]] covers the assertion side. This one covers the input side, which is where the harder instances live.
