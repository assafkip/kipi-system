---
id: writing-safe-automated-rename-migrations
kind: methodology
title: Writing Safe Automated Rename Migrations
date: 2026-11-01
---

## When this applies

Any time you ship an automated rewrite that renames an identifier, package, or configuration key across a codebase you do not fully control — especially when that rewrite runs as a hook inside a larger deploy or sync pipeline that also replaces files.

## 1. Classify prose vs. code with a real parser, never a regex

A rename tool must rewrite the old token in code while leaving it intact in the text that documents the rename. Regex cannot make that distinction reliably:

- A "skip anything that looks like a comment" rule misfires on comment-like sequences inside strings.
- A "skip strings" rule is worse: the old token legitimately appears in string literals that are import paths, module references, registry keys, or config lookups — exactly the occurrences that *must* migrate.
- Documentation of a rename is self-referential: it has to name the old token to be useful, so a blind rewrite destroys the only record of what happened.

**How:** use the language's own tokenizer/parser and act on token or node kinds, not character patterns. Rewrite identifiers and string literals that resolve to code references; skip comment tokens and documentation strings (e.g. a leading string statement in a module, class, or function). If the language has no usable tokenizer available in your tool's runtime, reduce scope to an explicit allowlist of files and line forms rather than guessing.

**Test with:** a fixture containing the old token in every syntactic position at once — identifier, import path, string key, inline comment, block comment, and documentation string — and assert the exact post-rewrite text.

## 2. Write down who owns each path, then derive that set from code

When a migration step and a file-delivery step run in the same pipeline, they can both claim the same paths. The delivery step wins, so the migration silently redoes work that the next step discards — and reports success every time.

**How:**

- State the ownership contract explicitly, in a comment or doc next to both steps: *a path delivered by the sync belongs to the sync; the migration may only touch paths the sync leaves alone.*
- Make the migration skip the delivered set.
- Derive that set programmatically from the delivery step's own configuration — its source arrays, destination roots, exclude lists, and any per-deployment path prefix — rather than re-deriving it from a proxy.

**Watch for the proxy trap:** "the file exists in the template" is *not* the same set as "the file gets delivered." They diverge at carve-outs for deployment-owned subtrees, at the template root itself, at files that are merged rather than overwritten, and at copy-exclusion lists. Any one of those divergences puts a path in the wrong bucket. If the delivery logic changes, the migration's skip set must change with it, which is only automatic if it reads the same source of truth.

## 3. Build fixtures that match what you actually ship

An idempotency test that passes on a stripped-down fixture proves nothing. If the fixture omits the token in the position where it really occurs — an empty subtree, a minimal init file with no documentation — then "an already-migrated deployment is untouched" passes vacuously while the real artifact still carries the old token.

**How:**

- Generate fixtures from the real template/skeleton the pipeline ships, or snapshot it into the test tree, so fixture drift is impossible.
- Add an explicit idempotency assertion: run the migration twice over a shipped-shape tree and require the second run to produce zero changes.
- Add a negative-space test: assert the documentation of the rename still contains the old token after migration.

## 4. Detect no-op churn at the fleet level

A migration that is undone on every cycle is invisible from inside the migration: it does work, exits zero, and looks healthy. The signal lives one level up.

**How:** alarm on repeat-rewrite churn — a step that produces a change every cycle on a target that was already migrated, or a commit whose diff the next cycle reverts. A convergent migration should go quiet after its first successful run; any step that never quiets down is either non-idempotent or fighting a later step for the same files.

## Checklist

- [ ] Rewrite driven by a tokenizer/parser, not pattern matching
- [ ] Code-bearing string literals migrate; comments and doc strings do not
- [ ] Ownership contract for every path written, stated in both steps
- [ ] Skip set derived from the delivery step's own config, not a proxy
- [ ] Carve-outs, merged files, and exclude lists accounted for in that derivation
- [ ] Fixtures generated from the shipped template
- [ ] Second run produces zero changes
- [ ] Fleet-level alert on per-cycle churn that the next cycle reverts
