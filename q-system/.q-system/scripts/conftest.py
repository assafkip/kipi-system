"""Keep a standalone verifier out of pytest's collection (ASK-634).

`test_launchd_intent_verify.py` is a SCRIPT, not a pytest suite. It runs its
checks at module level and ends with `sys.exit(0)` / `sys.exit(1)` so a caller
can read its status. It only carries a `test_` prefix by naming convention.

pytest imports every file matching `test_*.py` during collection, so importing
this one raised `SystemExit` and killed the entire run with:

    INTERNALERROR> File ".../test_launchd_intent_verify.py", line 718, in <module>
    INTERNALERROR>     sys.exit(0)
    INTERNALERROR> SystemExit: 0

That crash is what actually blocked ASK-634. Un-hiding `q-system/.q-system/`
from `norecursedirs` was necessary and not sufficient: recursion started
working and collection then aborted before reaching the 168 separation tests,
so the count moved 822 -> 833 while the suite that mattered stayed invisible.

This is an EXCLUSION FROM COLLECTION, not a hidden test. The file is not a
pytest suite and has no pytest test functions; it is still run directly by its
callers and its checks are unchanged. Hiding a real suite is the defect ASK-634
exists to fix, and this is the opposite: removing a non-suite that was stopping
the real ones from being seen.

Swept for the same shape rather than assuming this was the only one: an AST scan
of every `test_*.py` under `q-system/` for a module-level `sys.exit` found
exactly this file. If another appears, prefer guarding its exit under
`if __name__ == "__main__":` so it stays importable, and add it here only when
its checks genuinely must run at import time.
"""

collect_ignore = ["test_launchd_intent_verify.py"]
