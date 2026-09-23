#!/usr/bin/env python3
"""Run mcp-denylist-namespace-check.py against the PATCHED guard.

The checker measures whatever guard it is pointed at. The guard on disk is the
unpatched one (the founder applies the proposal, not an agent), so this builds
the candidate in a temp dir by applying the proposal's insert to a COPY, and
runs the checker on that. The live hook is READ, never written.

    python3 q-system/.q-system/scripts/mcp-candidate-measure.py [--report]
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "mcp_denylist_namespace_check", HERE / "mcp-denylist-namespace-check.py")
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

PROPOSAL = HERE.parent / "proposals" / "mcp-denylist-operation-split.json"


def candidate(into):
    """A copy of the live guard with the proposal's insert applied."""
    hook = checker.resolve_hook()
    text = hook.read_text(encoding="utf-8")
    (edit,) = json.loads(PROPOSAL.read_text(encoding="utf-8"))["edits"]
    if text.count(edit["anchor"]) != 1:
        raise SystemExit("anchor hits the guard %d times, not once"
                         % text.count(edit["anchor"]))
    out = pathlib.Path(into) / "candidate.sh"
    out.write_text(text.replace(edit["anchor"], edit["insert"] + edit["anchor"], 1),
                   encoding="utf-8")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory() as tmp:
        hook = candidate(tmp)
        syntax = subprocess.run(["bash", "-n", str(hook)],
                                capture_output=True, text=True)
        if syntax.returncode != 0:
            print("the patched guard does not parse:\n%s" % syntax.stderr,
                  file=sys.stderr)
            return 2
        print("candidate: live guard + proposal insert (bash -n clean)\n")
        return checker.main(["--hook", str(hook)] + argv)


if __name__ == "__main__":
    sys.exit(main())
