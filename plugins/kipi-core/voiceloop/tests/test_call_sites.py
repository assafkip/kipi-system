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
# The real files name the binary a few lines up; the detector needs that word.
BIN_LINE = 'binary = shutil.which("claude") or "claude"\n'  # linear-triage.py:380
PY_LINE = BIN_LINE + 'res = subprocess.run([binary, "-p", prompt],\n                     capture_output=True)\n'  # linear-triage.py:388
SH_LINE = ('  if run_bounded "$T" bash -c "cd \'$TREE\' && KIPI_AGENT=\'$A\' claude -p '
           '\\"\\$1\\" </dev/null >>\'$LOG\' 2>&1" _ "$PROMPT"; then\n    :\n  fi\n')  # linear-worker.sh:2074
POPEN_LINE = BIN_LINE + 'proc = subprocess.Popen(\n    [command, "-p", "--model", FABLE_MODEL],\n    stdin=subprocess.PIPE)\n'  # fable-escalate.py:313
# The two PR #413 round 1 misses, as they are written in the wild:
IFEXP_LINE = ('r = subprocess.run(\n    [CLAUDE_BIN if os.access(CLAUDE_BIN, os.X_OK) else "claude",\n'
              '     "-p", "--output-format", "json", "--model", MODEL, PROMPT])\n')  # claude_auth_probe.py:96
FIRST_LINE = 'CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")\nDEFAULT_ARGS = ["-p", "--permission-mode", "acceptEdits"]\n'  # executor.py:22


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
        # a variable before "-p" in a file that never names claude (round 1 minor 2)
        "h.py": 'argv = [ssh_bin, "-p", str(port), host]\n',
        "i.py": "import os, subprocess\n" + IFEXP_LINE,
        "j.py": "import os\n" + FIRST_LINE,
        # options between claude and -p, and a printed mention (round 1 minor 4)
        "k.sh": '#!/bin/bash\nclaude --model "$M" -p "$PROMPT" </dev/null\n',
        "l.sh": '#!/bin/bash\necho "run: claude -p x"\nprintf "%s" "claude -p y"\n',
        "tests/t.py": "import subprocess\n" + PY_LINE,
        ".review-scratch/x.sh": "#!/bin/bash\n" + SH_LINE,
    })
    assert cs.call_sites(root) == {"a.py", "b.sh", "c.py", "f.py", "i.py", "j.py", "k.sh"}


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
