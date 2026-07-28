#!/usr/bin/env python3
"""Test for memory-confidence-surface.py (PRD prd-memory-confidence-provenance).

Test isolation: sets HOME and CLAUDE_PROJECT_DIR to point get_memory_dir() at a
TemporaryDirectory, seeds memory files there, never touches the real auto-memory
dir. Negative self-test (fable-discipline): a high-confidence / explicit memory
must NOT be flagged, proving the filter is not "flag everything".

Run: python3 q-system/.q-system/scripts/test_memory_confidence_surface.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SURFACER = os.path.join(HERE, "memory-confidence-surface.py")


def write_memory(mem_dir, stem, **fields):
    lines = ["---", f"name: {stem}", "description: x"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", "body"]
    (mem_dir / f"{stem}.md").write_text("\n".join(lines))


def run_surfacer(project_dir, home):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = project_dir
    proc = subprocess.run(
        [sys.executable, SURFACER],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        project_dir = "/Users/x/projects/demo"
        slug = project_dir.replace("/", "-")
        mem_dir = home / ".claude" / "projects" / slug / "memory"
        mem_dir.mkdir(parents=True)

        write_memory(mem_dir, "low-conf-fact", confidence="0.3")
        write_memory(mem_dir, "inferred-guess", provenance="inferred")
        write_memory(mem_dir, "observed-thing", provenance="observed")
        write_memory(mem_dir, "solid-fact", confidence="0.95", provenance="explicit_statement")
        write_memory(mem_dir, "no-fields", )  # legacy, no signal

        code, out = run_surfacer(project_dir, home)

        checks = [
            ("exit 0", code == 0),
            ("flags low-conf-fact", "low-conf-fact" in out),
            ("flags inferred-guess", "inferred-guess" in out),
            ("flags observed-thing", "observed-thing" in out),
            # negative self-test: high-trust + legacy must NOT be flagged
            ("does NOT flag solid-fact", "solid-fact" not in out),
            ("does NOT flag no-fields", "no-fields" not in out),
        ]
        for label, ok in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}")
            if not ok:
                failures.append(label)

        # empty dir -> exit 0, no output
        with tempfile.TemporaryDirectory() as tmp2:
            home2 = Path(tmp2)
            (home2 / ".claude" / "projects" / slug / "memory").mkdir(parents=True)
            code2, out2 = run_surfacer(project_dir, home2)
            ok = code2 == 0 and out2.strip() == ""
            print(f"[{'PASS' if ok else 'FAIL'}] empty memory dir -> exit 0, silent")
            if not ok:
                failures.append("empty dir")

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
