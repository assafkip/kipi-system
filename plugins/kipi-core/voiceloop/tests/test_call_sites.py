"""The call-site detector, proved on a throwaway repo with real lines (ASK-2008)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Same import shape as the sibling engine tests: the package's parent on the
# path, so the suite runs from any cwd with no deployment tree on disk.
PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)
from voiceloop import call_sites as cs  # noqa: E402

# Real lines, copied from the scripts they came from, not typed for the test.
PY_LINE = 'res = subprocess.run([binary, "-p", prompt],\n                     capture_output=True)\n'  # linear-triage.py:388
SH_LINE = ('  if run_bounded "$T" bash -c "cd \'$TREE\' && KIPI_AGENT=\'$A\' claude -p '
           '\\"\\$1\\" </dev/null >>\'$LOG\' 2>&1" _ "$PROMPT"; then\n    :\n  fi\n')  # linear-worker.sh:2074
POPEN_LINE = 'proc = subprocess.Popen(\n    [command, "-p", "--model", FABLE_MODEL],\n    stdin=subprocess.PIPE)\n'  # fable-escalate.py:313


def repo(tmp_path: Path, files: dict) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_real_call_shapes_are_seen_and_mentions_are_not(tmp_path):
    root = repo(tmp_path, {
        "a.py": "import subprocess\n" + PY_LINE,
        "b.sh": "#!/bin/bash\n" + SH_LINE,
        "c.py": "import subprocess\n" + POPEN_LINE,
        # unparseable under this Python, still a caller: the text fallback sees it
        "f.py": 'print "x"\nargv = [CLAUDE, "-p", prompt]\n',
        "d.sh": "#!/bin/bash\n# claude -p in a comment only\necho hi\n",
        "e.py": 'MSG = "we run claude -p here"\n',
        # pytest's own -p flag, the false positive a bare grep buys
        "g.py": 'argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]\n',
        "tests/t.py": "import subprocess\n" + PY_LINE,
        ".review-scratch/x.sh": "#!/bin/bash\n" + SH_LINE,
    })
    assert cs.call_sites(root) == {"a.py", "b.sh", "c.py", "f.py"}


def test_an_untracked_file_is_not_a_site_yet(tmp_path):
    root = repo(tmp_path, {"a.py": "import subprocess\n" + PY_LINE})
    (root / "later.py").write_text("import subprocess\n" + PY_LINE)
    assert cs.call_sites(root) == {"a.py"}


def test_check_reports_new_and_stale_but_not_absent(tmp_path):
    root = repo(tmp_path, {
        "a.py": "import subprocess\n" + PY_LINE,
        "b.sh": "#!/bin/bash\n" + SH_LINE,
        "wrapped.py": "x = 1\n",           # listed, present, no longer calls: stale
        "wrapper.py": "import subprocess\n" + PY_LINE,
    })
    new, stale = cs.check(root, {"a.py": "r", "wrapped.py": "r", "absent.py": "r"},
                          wrappers=["wrapper.py"])
    assert new == {"b.sh"}
    assert stale == {"wrapped.py"}  # absent.py is neither
