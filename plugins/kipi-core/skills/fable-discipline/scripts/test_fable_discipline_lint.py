#!/usr/bin/env python3
"""
Self-contained test for fable-discipline-lint.py. Exit 0 = all pass, 1 = a case failed.

Dogfoods the fable-discipline skill: every fixture is written under a TemporaryDirectory
(isolation), never a real path. Run:
    python3 plugins/kipi-core/skills/fable-discipline/scripts/test_fable_discipline_lint.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

LINT = str(Path(__file__).resolve().parent / "fable-discipline-lint.py")

# (filename, content, expected_exit)
CASES = [
    ("test_live.py",
     'import sqlite3\ndef test_x():\n    sqlite3.connect("investigations/data/investigations.db")\n',
     2),
    ("test_var_indirection.py",
     'import sqlite3\ndef test_x():\n    db_path = "investigations/data/prod.db"\n    sqlite3.connect(db_path)\n',
     2),
    ("test_isolated.py",
     'import sqlite3\ndef test_x(tmp_path):\n    sqlite3.connect(":memory:")\n    sqlite3.connect(str(tmp_path / "t.db"))\n',
     0),
    ("test_skip.py",
     '# fable-discipline-lint-skip\nimport sqlite3\ndef test_x():\n    sqlite3.connect("data/live.db")\n',
     0),
    ("test_assertion_ctx.py",
     'def test_audit(out):\n    # audit test names the live path on purpose\n    assert "data/prod.db" in out\n',
     0),
    ("test_augmented.py",
     'def test_x():\n    db_path = "/var/lib/app"\n    db_path += "/var/lib/app/prod.db"\n',
     2),
    ("test_walrus.py",
     'import sqlite3\ndef test_x():\n    if (p := "/var/lib/app/prod.db"):\n        sqlite3.connect(p)\n',
     2),
    ("test_dict_target.py",
     'def test_x(cfg):\n    cfg["db"] = "/var/lib/app/prod.db"\n',
     2),
    ("test_fstring.py",
     'import sqlite3\nfrom pathlib import Path\ndef test_x():\n    sqlite3.connect(f"{Path(\'/var/lib/app/prod.db\')}")\n',
     2),
    ("test_golden_fixture.py",
     'def test_x():\n    open("/repo/tests/golden/prod.db")\n',
     0),
    ("app.py",
     'import sqlite3\nsqlite3.connect("investigations/data/investigations.db")\n',
     0),
]


def run(path):
    return subprocess.run([sys.executable, LINT, str(path)],
                          capture_output=True, text=True).returncode


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        for name, content, want in CASES:
            f = base / name
            f.write_text(content)
            got = run(f)
            ok = got == want
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: exit {got} (want {want})")
            if not ok:
                failures += 1
    if failures:
        print(f"fable-discipline-lint self-test: {failures} FAILED")
        sys.exit(1)
    print(f"fable-discipline-lint self-test: all {len(CASES)} cases passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
