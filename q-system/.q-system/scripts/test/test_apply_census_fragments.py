"""census() must count the capability manifest FRAGMENTS, not a deleted monolith.

SCAR (PR #274, Codex major, 2026-08-29). The ASK-1118 branch pointed this read
back at q-system/.q-system/capability-manifest.json, the single file that #263
had already replaced with the capability/ fragment directory. Nothing raised:
os.path.isfile said no, the set stayed empty, and the ratchet reported
manifest_tests 186 -> 0 as a perfectly legitimate constant. A ratchet dimension
pinned at zero does not refuse removals of declared tests, it stops being able
to see them, and it reads exactly like a category nobody uses.

So this asserts a NON-ZERO count tied to what is actually on disk. An assertion
that census() merely "returns a set" passes against the defect; an assertion
that it equals len(fragments) is red the moment the read moves off the
fragments again.

Ref hatch: APPLY_CLAUDE_CHANGES_REF loads the engine from a git ref instead of
the worktree, so this case can be watched failing against the pre-fix commit
rather than trusted on the strength of passing after it.

    APPLY_CLAUDE_CHANGES_REF=<pre-fix-sha> python3 -m pytest <this file>
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
REL = "q-system/.q-system/scripts/apply_claude_changes.py"
FRAGMENTS = REPO / "q-system" / ".q-system" / "capability" / "expected_tests"


def _engine():
    """Load the engine from the worktree, or from APPLY_CLAUDE_CHANGES_REF."""
    ref = os.environ.get("APPLY_CLAUDE_CHANGES_REF")
    path = REPO / REL
    tmp = None
    if ref:
        body = subprocess.run(["git", "-C", str(REPO), "show", "%s:%s" % (ref, REL)],
                              check=True, capture_output=True, text=True).stdout
        # Beside the real script: _capability_manifest() resolves the assembler
        # against __file__'s directory, so a copy parked in /tmp would find no
        # module and degrade to the empty set -- which is the very failure this
        # test exists to catch, arriving for the wrong reason.
        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                          dir=str(REPO / "q-system" / ".q-system" / "scripts"))
        tmp.write(body)
        tmp.close()
        path = Path(tmp.name)
    spec = importlib.util.spec_from_file_location("acc_under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, (tmp.name if tmp else None)


def test_census_counts_manifest_fragments():
    mod, tmpname = _engine()
    try:
        on_disk = {json.loads(f.read_text())["path"]
                   for f in FRAGMENTS.glob("*.json")}
        assert on_disk, "fixture is empty; this test cannot fail as written"
        got = mod.census(str(REPO))["manifest_tests"]
        assert got == on_disk, (
            "census read %d declared tests, %d fragments are on disk. A zero or "
            "short count means the read moved off %s."
            % (len(got), len(on_disk), FRAGMENTS))
    finally:
        if tmpname:
            os.unlink(tmpname)


# The capability manifest declares this file with runner `python3`, and a pytest
# MODULE run that way defines a function and exits 0 without calling it -- so the
# declared regression test was inert and returned success even against the
# revision it exists to catch (Codex major, PR #274). Measured: `python3 <this
# file>` exited 0 having run nothing. The sibling declared tests all carry an
# entrypoint for the same reason; a declared test with no way to fail is worse
# than no declaration, because the manifest then counts it.
if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
