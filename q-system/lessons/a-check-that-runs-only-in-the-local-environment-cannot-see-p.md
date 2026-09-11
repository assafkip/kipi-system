---
id: a-check-that-runs-only-in-the-local-environment-cannot-see-p
kind: methodology
title: A check that runs only in the local environment cannot see production-only defects
date: 2026-08-17
---

When code branches on a value the environment supplies rather than one the code sets (a request path, a rewritten or normalized URL, a header, an env var, a resolved hostname, a filename after the server touches it), your local harness almost always supplies a different value than the deployed platform does. A check that runs only locally then confirms the wrong branch and stays green forever.

How to apply:

1. Before writing the check, list every input the code reads but does not set itself. For each one, write down the value the local harness supplies and the value the deployed platform supplies. Any row where those differ is a place a local check proves nothing.
2. For each differing row, drive the check with both values (table-driven or parameterized), so the branch that only exists in production is exercised somewhere.
3. Add at least one check that queries the deployed target directly and asserts the observed value rather than the assumed one. If nothing in the repo can ask a question about the deployed environment, that absence is itself the coverage gap to close first.
4. When a manual visual or browser check passes while the defect persists, identify which layer that check was pointed at before re-running it. Repeating a check against the same layer produces the same false green.

Stop condition: the check is adequate when you can name the input value that makes it fail for the reason you care about, and that value is the one production actually supplies.
