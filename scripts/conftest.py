"""Keep two standalone verifiers out of pytest's collection (ASK-634).

`test_persona_reorg.py` and `test_persona_reorg_detach.py` are SCRIPTS, not
pytest suites. They run their checks at module level and end with `sys.exit()`
so a caller can read a status. They carry a `test_` prefix by naming convention
only.

pytest imports every `test_*.py` during collection, so importing either raised
`SystemExit` and killed the whole run with an INTERNALERROR before it reached
the rest of the tree.

EXCLUSION FROM COLLECTION, not a hidden test: neither file defines a pytest test
function, both are still run directly by their callers, and their checks are
unchanged. Hiding a real suite is the defect ASK-634 exists to fix; this removes
two non-suites that were stopping the real ones from being collected.

Found by widening a sweep that was wrong the first time. The initial AST scan
covered only `q-system/` and reported "exactly one" module-level exit. Scoping a
sweep is itself a claim, and that one was false -- a repo-wide scan found four:

    scripts/test_persona_reorg.py:124
    scripts/test_persona_reorg_detach.py:228
    security-remediation/ask204-review/test_launchd_health_check.py:663
    q-system/.q-system/scripts/test_launchd_intent_verify.py:718

The third is already outside collection via `norecursedirs`. The fourth has its
own conftest beside it.

If another appears, prefer guarding its exit under `if __name__ == "__main__":`
so the file stays importable, and add it here only when its checks genuinely
must run at import time.
"""

collect_ignore = [
    "test_persona_reorg.py",
    "test_persona_reorg_detach.py",
]
