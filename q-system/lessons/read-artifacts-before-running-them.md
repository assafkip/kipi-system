---
id: read-artifacts-before-running-them
kind: methodology
title: Read Artifacts Before Running Them
date: 2026-11-04
---

When you need to answer a high-level question about an untrusted or unknown binary, archive, or bundle, start with inert inspection rather than execution. Extracting the static, readable content of an artifact is zero-risk and often settles the question you actually care about.

How to apply it:

1. State the one question you need answered first, and phrase it as a yes/no about intent or capability (for example: does this touch payment flows, does it reach the network, does it target a specific class of data). Narrow questions are the ones static inspection answers well.

2. Derive a concrete indicator list from that question before you look. Decide in advance which literal strings, identifiers, embedded resources, symbol names, dependency references, declared permissions, or configuration keys would count as evidence. Writing the list first prevents you from rationalizing whatever you happen to find.

3. Pull the artifact's static surface without executing it: embedded text and literals, imported and exported symbols, metadata and manifests, bundled resources, and declared dependencies. Keep the artifact in its own isolated directory, and run your tooling from a separate location with paths passed as arguments so nothing in the artifact's directory gets loaded as code.

4. Match findings against your indicator list and record the answer plus the raw evidence. Presence of a strong indicator is usually decisive for intent questions.

5. Be explicit about the limit. Static content reveals intent and capability surface; it does not prove that any code path is reachable, correct, or functional. Dead code, unused resources, and leftover strings all survive into shipped artifacts. Never upgrade "this contains X" into "this does X."

6. Only escalate to execution once static inspection has either answered the question or shown you exactly which behavior needs dynamic confirmation. Use an isolated, instrumented environment, and let the static findings define what you watch for. This keeps costly or risky steps targeted instead of exploratory.

Why it works: inspection and execution answer different classes of questions, and inspection is strictly cheaper and safer. Ordering them correctly means many investigations end at step 4, and the ones that continue start with a hypothesis instead of a blank slate.

Generalizes beyond security work: the same ordering applies to auditing an unfamiliar third-party dependency, triaging a build output that behaves unexpectedly, verifying what a released package actually ships, or checking whether a vendor binary contains functionality it was not supposed to include.
