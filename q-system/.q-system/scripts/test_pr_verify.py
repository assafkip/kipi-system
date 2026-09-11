#!/usr/bin/env python3
"""Self-test for pr_verify.py, the only writer of .prd-os/pr-receipts/.

Hermetic: every case builds a throwaway git repo, a stub `verify.sh` whose
output the case controls, and a stub `gh` on PATH that answers headRefOid from
an environment variable. Nothing reaches the network and no real suite runs.

The cases that matter are the ones that must NOT produce a green receipt, so
each is paired with a green control. A test suite for a receipt writer that only
ever asserts "green when green" cannot tell the writer from a rubber stamp.

Run: python3 test_pr_verify.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "pr_verify.py"

FAILURES: list[str] = []
CHECKS = 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo(root: Path, verify_body: str, verify_rc: int = 0) -> Path:
    repo = root / ("r%d" % len(list(root.iterdir())))
    (repo / "q-system" / ".q-system").mkdir(parents=True)
    (repo / "q-system" / ".q-system" / "verify.sh").write_text(
        "#!/usr/bin/env bash\ncat <<'OUT'\n%s\nOUT\nexit %d\n"
        % (verify_body, verify_rc))
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    return repo


def _stub_gh(bindir: Path) -> None:
    """A `gh` that prints whatever PRVERIFY_FAKE_HEAD says."""
    gh = bindir / "gh"
    gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$PRVERIFY_FAKE_HEAD"\n')
    gh.chmod(0o755)


def run_tool(repo: Path, bindir: Path, fake_head: str):
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    env["PRVERIFY_FAKE_HEAD"] = fake_head
    return subprocess.run([sys.executable, str(TOOL), "9", "--root", str(repo)],
                          capture_output=True, text=True, env=env)


def check(name: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append("%s\n    want: %r\n    got : %r" % (name, want, got))


def receipt_of(repo: Path):
    p = repo / ".prd-os" / "pr-receipts" / "pr-9.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text())


GREEN_OUT = "  python syntax   ok\n  pytest:q-system   ok\nverify.sh ok"


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repos"
        root.mkdir()
        bindir = Path(td) / "bin"
        bindir.mkdir()
        _stub_gh(bindir)

        # --- the green control. Without it every refusal below could be a
        # writer that never writes anything.
        repo = _repo(root, GREEN_OUT)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        r = run_tool(repo, bindir, head)
        check("green run exits 0", r.returncode, 0)
        rec = receipt_of(repo)
        check("green run writes a receipt", rec is not None, True)
        if rec:
            check("receipt says green", rec.get("result"), "green")
            check("receipt names the sha that was run", rec.get("sha"), head)

        # --- RULE 2: the checkout must BE the PR head. Running one tree and
        # stamping another is the failure a receipt exists to prevent.
        repo = _repo(root, GREEN_OUT)
        r = run_tool(repo, bindir, "0" * 40)
        check("head mismatch refuses", r.returncode != 0, True)
        check("head mismatch writes NO receipt", receipt_of(repo), None)
        check("head mismatch says why", "head is" in (r.stdout + r.stderr), True)

        # --- RULE 3: a zero-test run is a FAILURE. This is the case the gate's
        # own message names, and it is why "verify.sh exited 0" is not enough.
        repo = _repo(root, "  pytest:q-system   ok\nno tests ran in 0.01s")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        r = run_tool(repo, bindir, head)
        check("zero-test run exits non-zero", r.returncode != 0, True)
        rec = receipt_of(repo)
        check("zero-test run still WRITES a receipt", rec is not None, True)
        if rec:
            check("zero-test receipt says red", rec.get("result"), "red")

        # --- a floor that ran no pytest suite at all certifies nothing.
        repo = _repo(root, "  python syntax   ok\nverify.sh ok")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        r = run_tool(repo, bindir, head)
        check("no pytest suite exits non-zero", r.returncode != 0, True)
        rec = receipt_of(repo)
        check("no pytest suite is red", (rec or {}).get("result"), "red")

        # --- and the ordinary red: verify.sh itself failed.
        repo = _repo(root, "  pytest:q-system   FAILED", verify_rc=1)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        r = run_tool(repo, bindir, head)
        check("failing floor exits non-zero", r.returncode != 0, True)
        check("failing floor is red", (receipt_of(repo) or {}).get("result"), "red")

    if FAILURES:
        print("FAIL %d/%d\n" % (len(FAILURES), CHECKS))
        for f in FAILURES:
            print("  " + f + "\n")
        return 1
    print("ok  %d/%d checks passed" % (CHECKS, CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
