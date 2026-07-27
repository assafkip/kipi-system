---
id: the-last-path-insert-wins-order-your-module-search-path-deli
kind: pattern
title: The last path insert wins: order your module search path deliberately
date: 2026-07-27
---

When a program mutates its module/library search path at startup, treat that path as an ordered contract, not a bag of directories. Front-insertion primitives push earlier entries down, so the entry added LAST has the highest priority. A path bolted on later for an unrelated dependency will silently outrank the directory everyone assumed was first, and a generic bare name (a common word like `attribution`, `utils`, `config`, `client`) then resolves into the wrong tree.

## How to write it

- Set the search path in ONE place, as an explicit ordered list, instead of scattering successive front-inserts. If the list is built in one statement, its order is reviewable.
- If you must use front-insertion, insert the directory that must win LAST, and put a comment next to it saying which name depends on that priority.
- Use append (lowest priority) for auxiliary paths added to satisfy one helper import. Only the entrypoint's own directory earns the front slot.
- Prefer unambiguous imports for local modules (package-qualified or explicitly relative) so a sibling tree cannot capture a bare generic name regardless of path order.
- Never let two directories on the path expose the same top-level name. If they do, rename one; ordering is too fragile to rely on.

## How to test it

- Assert WHERE a module resolved, not just that the import succeeded. Check the loaded module's file/origin against the expected directory.
- Run that assertion in a FRESH process. In-process module caching means the first import wins for the rest of the run, so a suite that already loaded the module passes while the real entrypoint fails.
- Make the test the entrypoint's own smoke check: launch the program the way production launches it (same working directory, same environment) and fail on non-zero exit. Import-time failures often surface as an empty run rather than a loud crash, so the harness must check the exit status, not just the absence of output.
- Treat 'added one path for one new dependency' as a change to every import in the process. Re-run the resolution test on any path edit; the blast radius is global, not local.

## The trigger to watch for

Any diff that adds a search-path entry so that one newly-needed helper can be imported. That is the exact moment the implicit 'my own directory comes first' assumption breaks, and nothing in the language will warn you.
