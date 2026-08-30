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


# --- test_wiring_check.py: the SAME shape, one variation, and NOT excluded ---
#
# It is a standalone script whose `main()` builds one temp directory and passes
# it to each check by hand, so its `test_*` functions take a plain `tmp`
# parameter. pytest reads that parameter as a FIXTURE REQUEST, finds no fixture
# called `tmp`, and errors 8 times -- at root scope, where the run that matters
# happens (ASK-1129).
#
# The sweep recorded above looked for a module-level `sys.exit` and correctly
# reported this file was not one: it guards its exit under `__main__`, so it
# imports cleanly. The shape it shares is "test_ prefix by convention, not a
# pytest suite"; the shape it does NOT share is the crash. One AST predicate,
# two different symptoms.
#
# A fixture, NOT another collect_ignore entry. Excluding it would keep the run
# green by removing 8 real contract checks from it, and those checks are the
# only thing pinning the nesting detector. Three lines make them run under
# pytest AND leave `python3 test_wiring_check.py` working exactly as before,
# which is what the file's own callers still do.
import pytest  # noqa: E402


@pytest.fixture
def tmp(tmp_path):
    """`tmp_path` under the name this directory's scripts already ask for."""
    return tmp_path
