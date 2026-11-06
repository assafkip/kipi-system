---
id: verify-each-item-at-the-source-not-the-list-that-names-it
kind: pattern
title: Verify Each Item at the Source, Not the List That Names It
date: 2026-11-06
---

## Principle

When you act on entries from a curated list, catalog, index, or feed, treat the list as a pointer only. Before committing to any entry, fetch and inspect that entry's own self-reported metadata and content. List descriptions are second-hand summaries: they age, they generalize across entries, and they are often written once for a group and never revisited.

## Why list-level trust fails

- **Aggregation flattens differences.** A single description is frequently applied to several near-identical entries (similar names, mirrors, replicas, variants). Entries that look interchangeable by name are not necessarily interchangeable in content.
- **Drift.** The entry can change after the list was written; the list has no obligation to notice.
- **Authorship gap.** The list author's intent is not the entry owner's intent. Only the entry itself states what it currently claims to be.

## How to apply

1. **Add a per-item verification step** between "selected from list" and "acted upon." Make it a required stage, not an optional spot-check.
2. **Read the item's own identity fields first** — its title, label, self-description, headers, manifest, or landing content. These are the cheapest signals and are controlled by the item, not the index.
3. **Compare self-report against list-report.** Log any divergence. Divergence is a signal worth escalating even when the item still passes your checks.
4. **Never generalize across siblings.** If entries share a name prefix, version suffix, or appear to be mirrors of one another, verify each one independently. Explicitly forbid "checked one, approved all" in your process.
5. **Fail closed.** If an item's own metadata cannot be retrieved, treat it as unverified rather than inheriting the list's assessment.
6. **Record what you saw.** Store the self-reported metadata at verification time so later audits can distinguish "was always like this" from "changed after approval."

## Where this generalizes

Any time a cheap identifier stands in for an expensive object: dependency names in a lockfile versus package contents, endpoint entries in a registry versus live responses, asset IDs in a manifest versus the asset, user-supplied references versus the referenced resource, hostnames in an allowlist versus what the host serves today.

## Cost framing

Per-item verification is usually one extra cheap read. The failure it prevents is acting on something whose own stated purpose would have disqualified it immediately — a failure that is visible in hindsight and therefore expensive to explain.
