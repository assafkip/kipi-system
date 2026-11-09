---
id: review-third-party-code-through-your-own-fork
kind: pattern
title: Review third-party code through your own fork
date: 2026-11-09
---

When you need to review, explore, or experiment with a codebase you do not own, first fork it into an account or namespace you control, then clone and work only from that fork. This removes any chance of an accidental push, branch creation, tag, or other write landing on the original repository, even if your credentials technically allow it.

How to apply it:
1. Fork the repository into your own account before cloning anything.
2. Clone the fork, not the original. Confirm the default remote points at your fork before doing any work.
3. If you want to pull in upstream updates, add the original as a separate read-only remote and only fetch from it. Never push to it. Where your tooling allows, set its push URL to an invalid value so a push fails loudly.
4. Do all experiments, review branches, notes, and scratch commits in the fork.
5. Share findings through comments, a written report, or a proposed change opened from the fork. Do not write directly to the original.

Limits to keep in mind:
- This guards only against accidental writes. It does not control or preserve access. If the owner revokes your access to a private repository, forks of it are typically removed or become inaccessible as well.
- If you need a lasting copy, agree on that with the owner explicitly, and respect their confidentiality expectations.
- A fork of a private repository still holds sensitive code. Keep it private and delete it when the review is finished.
