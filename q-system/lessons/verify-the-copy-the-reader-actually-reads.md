---
id: verify-the-copy-the-reader-actually-reads
kind: methodology
title: Verify the copy the reader actually reads
date: 2026-08-17
---

When the same record or artifact is written to more than one destination, a verification is only meaningful if it targets the destination the person raising the question actually opens. Reading whichever copy you happen to have a client, credential, or query path for proves that copy is correct and nothing else.

This failure is worse than skipping verification, because a confident "verified" report closes the question. The reporter believes it, the asker believes it, and the divergent copy stays broken with no one looking.

How to apply:

1. Before verifying, enumerate the destinations the record can land in: the primary store, any mirror, cache, index, export, downstream sync, or human-facing view. Multi-destination writes are common and usually invisible from the write side.
2. If more than one exists, establish which one the reader is looking at before you read anything. If you do not know, ask. One question costs less than a false all-clear.
3. Read that destination. If you have no read path for it, say so plainly rather than substituting the copy you can reach. "I verified the mirror, not the view you are using" is an honest and useful report; "verified" is not.
4. Scope the claim to what you read. Name the destination in the report every time, not just when it was ambiguous.
5. If the copies are supposed to be identical, the divergence itself is a defect worth its own investigation, separate from the original issue.

The general rule most verification guidance encodes is "check the live artifact, not the source." That rule silently assumes there is exactly one live artifact. When there are several, the prior step is identifying which one is in question, and that step has to happen before the read, not after the report.
