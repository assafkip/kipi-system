#!/usr/bin/env python3
"""Pairs with containment-targets.py: a gitlink must not take the gate down.

Scar (2026-07-27). The auto-committer swept the review agent's scratch
worktrees into main. Eleven gitlinks (mode 160000) landed as tracked entries.
`_indexed_bytes` runs `git cat-file blob <object_id>` on every tracked entry,
but a gitlink's object id is a COMMIT in another repository and is never a blob
here, so the call failed, `ContainmentScopeBlocked` was raised, and Gate 1.3b
reported "scope unavailable" on main and on every open PR at once.

Nothing was wrong with the containment rule. The scanner could not start, and a
scanner that cannot start reads exactly like a scanner that found nothing.

This pins the scope decision: a submodule's content lives in a different
repository, so this repo cannot scan it and never could. Skipping it is correct
scope. The test asserts the ABSENCE of an exception, because the observed
failure mode was a crash, not a wrong answer.

Hermetic: builds its own repo in a temp dir, stages a gitlink with
`git update-index --cacheinfo`, and never touches the real index.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "containment-targets.py"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(': ' + detail) if detail else ''}")


def load_module():
    spec = importlib.util.spec_from_file_location("containment_targets", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def build_repo(repo: Path) -> None:
    """A repo with one real file and one gitlink, mirroring the observed shape."""
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    (repo / "real.md").write_text("# ordinary tracked text\n")
    git(repo, "add", "real.md")
    git(repo, "commit", "-q", "-m", "seed")
    # A gitlink pointing at a commit sha that does not exist as a blob here.
    # This is exactly what a committed scratch worktree looks like in the index.
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},scratch/worktree")


def main() -> int:
    module = load_module()

    # getattr, not attribute access: against pre-fix code the constant is absent,
    # and an AttributeError here would abort the run before the case that matters.
    # A reproducer that cannot run against the broken version proves nothing.
    check("GITLINK_MODE is git's submodule mode",
          getattr(module, "GITLINK_MODE", None) == "160000",
          f"got {getattr(module, 'GITLINK_MODE', None)!r}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        build_repo(repo)

        # THE CORE CASE, and it must go through enumerate_containment_targets,
        # not _tracked_entries. Enumeration is where the observed crash lived:
        # _tracked_entries only LISTS the gitlink without incident, and the
        # failure fires later when _indexed_bytes runs `git cat-file blob` on
        # it. A first draft of this test asserted against _tracked_entries and
        # passed against the broken code -- a reproducer that goes green on the
        # defect is worse than no reproducer, because it certifies the bug.
        raised = None
        try:
            module.enumerate_containment_targets(repo)
        except Exception as exc:  # noqa: BLE001 - the crash IS the defect
            raised = exc
        check("enumerating a repo with a gitlink does not crash", raised is None,
              f"raised {type(raised).__name__}: {raised}")

        entries = None
        try:
            entries = module._tracked_entries(repo)
        except Exception:  # noqa: BLE001
            entries = None

        if entries is not None:
            paths = [e["path"] for e in entries]
            check("the gitlink is excluded from scope",
                  "scratch/worktree" not in paths, f"paths={paths}")
            # Must not over-skip: real content still has to be scanned, or the
            # fix would silently empty the gate instead of crashing it.
            check("ordinary tracked text is still in scope", "real.md" in paths,
                  f"paths={paths}")
            check("no entry carries the gitlink mode",
                  all(e["mode"] != "160000" for e in entries))

    print()
    print(f"passed {PASS}, failed {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
