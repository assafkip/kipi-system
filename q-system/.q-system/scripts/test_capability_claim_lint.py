#!/usr/bin/env python3
"""Reproducer + negative self-test for capability-claim-lint.py (ASK-562).

RED: the ticket's own shapes ("I'll tell you either way", "will alert you") with
no executable nearby must be flagged, through the real hook path (exit 2).
GREEN: the same claim with a script path adjacent passes, and so does an honest
negation ("nothing alerts on this").
POPULATION: the skeleton's own rules and READMEs must be clean. A lint red on its
own population gets switched off, so this is the gate on the gate.

Run: python3 test_capability_claim_lint.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "capability-claim-lint.py"
REPO = HERE.parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("capability_claim_lint", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def hook(path: Path) -> int:
    """Run the lint as PostToolUse does, on a file written to a throwaway tree."""
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})
    return subprocess.run([sys.executable, str(LINT)], input=payload, text=True,
                          capture_output=True, check=False).returncode


def write_rule(body: str) -> Path:
    d = Path(tempfile.mkdtemp()) / ".claude" / "rules"
    d.mkdir(parents=True)
    p = d / "probe.md"
    p.write_text(body, encoding="utf-8")
    return p


def main() -> int:
    if not LINT.exists():
        print(f"FAIL: {LINT.name} does not exist yet (the RED state)")
        return 1
    mod = _load()
    cases: list[tuple[str, bool]] = []

    # RED: the ticket's own promises, no emitter.
    for text in ("If the job breaks, it will alert you.",
                 "I'll tell you either way once the run finishes.",
                 "The queue is watched overnight."):
        cases.append((f"flagged: {text!r}", len(mod.hits(text + "\n")) == 1))
    cases.append(("hook path exits 2 on 'will alert you' with no path",
                  hook(write_rule("# R\n\nIf the job breaks, it will alert you.\n")) == 2))

    # GREEN: same claim with the emitter adjacent, and honest negation.
    ok = ("# R\n\nIf the job breaks, it will alert you.\n"
          "The emitter is `q-system/.q-system/scripts/slack-notify.sh`.\n")
    cases.append(("hook path exits 0 once a script path is adjacent",
                  hook(write_rule(ok)) == 0))
    cases.append(("an emitter beyond the window does not vouch",
                  len(mod.hits("It will alert you.\n\na\nb\nc\nrun.sh\n")) == 1))
    cases.append(("honest negation passes",
                  mod.hits("Nothing will alert you on this.\n") == []))
    cases.append(("a claim inside a code fence is output, not a claim",
                  mod.hits("```\nit will alert you\n```\n") == []))
    cases.append(("out-of-scope path exits 0 (code is never linted)",
                  hook(Path(tempfile.mkdtemp()) / "x.py") == 0))

    # POPULATION: the skeleton's own rules and READMEs.
    files = mod.scan(REPO)
    bad = [f"{f.relative_to(REPO)}:{n}" for f in files for n, _ in mod.lint_file(f)]
    cases.append((f"skeleton population is clean ({len(files)} files, "
                  f"{len(bad)} hits {bad[:3]})", len(files) >= 20 and not bad))

    failures = 0
    for name, passed in cases:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        failures += not passed
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
