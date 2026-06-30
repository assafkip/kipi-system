#!/usr/bin/env python3
"""Test for memory-confidence-validator.py (PRD prd-memory-confidence-provenance).

Test isolation: every memory file is written under a TemporaryDirectory whose path
contains the in-scope substrings (.claude/projects/<slug>/memory/). Never touches
the real auto-memory dir. Includes a NEGATIVE self-test (fable-discipline): a known
violation MUST exit 2, so a green run is not a rubber stamp.

Run: python3 q-system/.q-system/scripts/test_memory_confidence_validator.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATOR = os.path.join(HERE, "memory-confidence-validator.py")


def run_case(frontmatter_body, *, in_scope=True):
    """Write a memory file, invoke the validator over it, return exit code."""
    with tempfile.TemporaryDirectory() as tmp:
        if in_scope:
            mem_dir = os.path.join(tmp, ".claude", "projects", "slug", "memory")
        else:
            mem_dir = os.path.join(tmp, "q-system", "canonical")
        os.makedirs(mem_dir, exist_ok=True)
        fpath = os.path.join(mem_dir, "some-memory.md")
        with open(fpath, "w") as fh:
            fh.write(frontmatter_body)
        payload = json.dumps({"tool_input": {"file_path": fpath}})
        proc = subprocess.run(
            [sys.executable, VALIDATOR],
            input=payload,
            capture_output=True,
            text=True,
        )
        return proc.returncode


def fm(**fields):
    lines = ["---", "name: some-memory", "description: x"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", "body"]
    return "\n".join(lines)


CASES = [
    # (label, content, in_scope, expected_exit)
    ("confidence 1.5 -> block", fm(confidence="1.5"), True, 2),
    ("provenance madeup -> block", fm(provenance="madeup"), True, 2),
    ("confidence non-numeric -> block", fm(confidence="abc"), True, 2),
    ("valid 0.4 + inferred -> pass", fm(confidence="0.4", provenance="inferred"), True, 0),
    ("confidence 0 -> pass", fm(confidence="0"), True, 0),
    ("confidence 1.0 -> pass", fm(confidence="1.0"), True, 0),
    ("neither field -> pass", fm(), True, 0),
    ("no frontmatter -> pass", "just body text\n", True, 0),
    ("invalid value but off-scope -> pass", fm(confidence="1.5"), False, 0),
]


def main():
    failures = []
    for label, content, scope, expected in CASES:
        got = run_case(content, in_scope=scope)
        ok = got == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {label} (exit {got}, want {expected})")
        if not ok:
            failures.append(label)

    # Negative self-test: prove the validator has teeth. The same payload that
    # passes when valid MUST fail when the confidence is corrupted past the bound.
    valid = run_case(fm(confidence="0.9"), in_scope=True)
    corrupt = run_case(fm(confidence="9.9"), in_scope=True)
    teeth_ok = valid == 0 and corrupt == 2
    print(f"[{'PASS' if teeth_ok else 'FAIL'}] negative self-test: valid passes ({valid}), corrupt blocks ({corrupt})")
    if not teeth_ok:
        failures.append("negative self-test")

    if failures:
        print(f"\nFAILED: {len(failures)} case(s): {failures}")
        sys.exit(1)
    print(f"\nOK: all {len(CASES) + 1} checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
