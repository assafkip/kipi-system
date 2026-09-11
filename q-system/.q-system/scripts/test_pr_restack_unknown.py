#!/usr/bin/env python3
"""Self-test: pr-restack.py must not silently skip a PR it could not classify.

THE DEFECT (measured 2026-08-30). GitHub computes PR mergeability lazily. In the
minute or two after a merge to main a large fraction of the backlog reports
UNKNOWN, and the first version of the sweeper filtered for DIRTY and dropped
those without a word. A run moments after a merge examined 1 PR out of 23 and
printed "conflicted 1", which reads as "the backlog is nearly clean". It was
reported upward as exactly that. Twenty-two branches were never looked at.

The fix has two halves and this file pins both:

  1. an UNKNOWN is RE-QUERIED (asking about one PR forces GitHub to compute it),
     bounded, rather than assumed to be fine;
  2. anything still UNKNOWN at the end is NAMED in the output, and every run
     reports how many PRs it examined against how many are open -- because a
     count of findings alone cannot tell "examined everything, found little"
     from "examined almost nothing".

Hermetic: a stub `gh` on PATH decides what every query returns. No network, and
the sweeper never reaches a real branch because the stub's PRs have none.

Run: python3 test_pr_restack_unknown.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "pr-restack.py"

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append("%s\n    %s" % (name, detail))


def _stub_gh(bindir: Path, *, settles: bool) -> None:
    """A `gh` whose `pr list` says UNKNOWN for #901.

    `pr view` then answers DIRTY (settles) or UNKNOWN forever (does not), so the
    two branches of the retry are chosen by the fixture rather than by timing.
    """
    view_answer = "DIRTY" if settles else "UNKNOWN"
    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then\n'
        "  cat <<'JSON'\n"
        '[{"number":901,"headRefName":"stub/never-existed",'
        '"mergeStateStatus":"UNKNOWN","title":"stub"}]\n'
        "JSON\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "pr" ] && [ "$2" = "view" ]; then\n'
        '  printf "%s\\n" "' + view_answer + '"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    gh.chmod(0o755)


def run_tool(bindir: Path, repo: Path):
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    env["PR_RESTACK_UNKNOWN_WAIT"] = "0"      # no real sleeping in a test
    return subprocess.run([sys.executable, str(TOOL), "--dry-run"],
                          cwd=str(repo), capture_output=True, text=True,
                          env=env, timeout=120)


def _repo(root: Path) -> Path:
    repo = root / "r"
    repo.mkdir(parents=True)
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
              ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True,
                       capture_output=True)
    (repo / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True,
                   capture_output=True)
    # The sweeper cuts its worktree from origin/main, so the fixture needs that
    # ref to exist. A local alias is enough: nothing here contacts a remote.
    subprocess.run(["git", "-C", str(repo), "update-ref",
                    "refs/remotes/origin/main", "HEAD"], check=True,
                   capture_output=True)
    return repo


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- it never settles: the run must NAME it, not stay quiet ---
        bindir = root / "bin_stuck"
        bindir.mkdir()
        _stub_gh(bindir, settles=False)
        r = run_tool(bindir, _repo(root / "a"))
        out = r.stdout + r.stderr
        check("an unsettled UNKNOWN is reported, not dropped",
              "WARNING" in out and "#901" in out, out[-400:])
        check("and it says how many are open on the nothing-to-do path too",
              "1 open PR(s), none reported DIRTY" in out, out[-400:])

        # --- it settles to DIRTY on re-query: the PR must be EXAMINED ---
        bindir2 = root / "bin_settles"
        bindir2.mkdir()
        _stub_gh(bindir2, settles=True)
        r2 = run_tool(bindir2, _repo(root / "b"))
        out2 = r2.stdout + r2.stderr
        # It has no real branch, so it lands in `failed` -- which is the proof
        # it was PICKED UP rather than filtered out at the list step.
        check("an UNKNOWN that re-queries to DIRTY is examined",
              "#901" in out2 and "WARNING" not in out2, out2[-400:])
        check("the examined count reflects it",
              "examined 1 of 1 open PR" in out2, out2[-400:])

    if FAILURES:
        print("FAIL %d/%d\n" % (len(FAILURES), CHECKS))
        for f in FAILURES:
            print("  " + f + "\n")
        return 1
    print("ok  %d/%d checks passed" % (CHECKS, CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
