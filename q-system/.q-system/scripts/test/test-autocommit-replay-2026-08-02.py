#!/usr/bin/env python3
"""ASK-314's Check, executable: replay the two 2026-08-02 sweeps.

`test-autocommit-wip-ref.py` proves the PROPERTY (the hook never writes to a
named branch) on a synthetic one-file case. This file proves the two INCIDENTS,
because a property test passes on a shape the author chose and the incidents had
shapes nobody chose.

The path lists below are not invented. They are the real `git show --name-only`
output of the two damaging commits, so this fixture comes from the producer:

  7383d6c "chore: update system infrastructure"
      Swept finished ASK-122 work onto sana/ask-294, an unrelated issue's
      branch. Recovery cost a worktree extraction, a reland (d20f412) and a
      revert (e770838).

  4559194 "chore: update system infrastructure"
      Swept an in-flight ASK-312 fix together with an unrelated launchd config
      change (com.kipi.dispatch.plist) into one generic commit, discarding the
      message its author was about to write. Caught pre-push, soft-reset, split.

Both replays assert the same two things: the checked-out branch gains nothing,
AND the work is still recoverable. The second assertion is why this is not a
test a do-nothing hook could pass.

Hermetic: builds its own repo, never touches the real one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = Path(
    os.environ.get("KIPI_AUTOCOMMIT_HOOK")
    or HERE.parent.parent.parent / "hooks" / "auto-commit.py"
)

# Provenance: `git show --name-only --format= <sha>` in assafkip/kipi-system.
SWEEPS = [
    (
        "7383d6c onto sana/ask-294 (ASK-122 work, unrelated branch)",
        "sana/ask-294",
        "sess-replay-7383d6c",
        [
            "q-system/.q-system/capability-manifest.json",
            "q-system/.q-system/scripts/capability-map-gen.py",
            "q-system/.q-system/scripts/test/test-capability-map-wiring.py",
        ],
    ),
    (
        "4559194 onto sana/ask-312 (ASK-312 fix + unrelated plist, one commit)",
        "sana/ask-312",
        "sess-replay-4559194",
        [
            "q-system/.q-system/scripts/com.kipi.dispatch.plist",
            "q-system/.q-system/scripts/pr-review-agent.sh",
            "q-system/.q-system/scripts/pr-verdict-lib.sh",
            "q-system/.q-system/scripts/test/fixtures/pr-verdict/declined-to-start-long.md",
            "q-system/.q-system/scripts/test/fixtures/pr-verdict/declined-to-start-short.md",
            "q-system/.q-system/scripts/test/fixtures/pr-verdict/real-review-request-changes.md",
            "q-system/.q-system/scripts/test/test-findings-block-reader.sh",
            "q-system/.q-system/scripts/test/test-review-gate-no-fake-green.sh",
        ],
    ),
]

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


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def replay(tmp: Path, label: str, branch: str, session: str, paths: list[str]) -> None:
    print(f"\nreplay {label}")
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", branch)
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("baseline\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "baseline")

    before_head = git(repo, "rev-parse", "HEAD")
    before_count = git(repo, "rev-list", "--count", "HEAD")

    # The sweep's exact file set, dirty in the working tree, as it was that day.
    for rel in paths:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"content of {rel}\n")

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env.pop("KIPI_AUTOCOMMIT", None)
    subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=repo,
        input=json.dumps({"session_id": session, "cwd": str(repo)}),
        capture_output=True,
        text=True,
        env=env,
    )

    after_head = git(repo, "rev-parse", "HEAD")
    check(
        f"{branch} gains no commit",
        after_head == before_head
        and git(repo, "rev-list", "--count", "HEAD") == before_count,
        f"{before_head[:8]} -> {after_head[:8]}",
    )
    log = git(repo, "log", "--format=%s")
    check(
        "no 'update system infrastructure' commit on the branch",
        "update system infrastructure" not in log,
        log,
    )
    # Durability half: refusing to commit is only correct if nothing was lost.
    ref = f"refs/kipi/wip/{session}"
    missing = []
    for rel in paths:
        r = subprocess.run(
            ["git", "cat-file", "-p", f"{ref}:{rel}"],
            cwd=repo, capture_output=True, text=True,
        )
        if r.returncode != 0 or r.stdout != f"content of {rel}\n":
            missing.append(rel)
    check(
        f"all {len(paths)} swept paths recoverable from {ref}",
        not missing,
        ", ".join(missing),
    )


def main() -> int:
    if not HOOK.exists():
        print(f"FAIL: hook not found at {HOOK}")
        return 1
    print(f"testing {HOOK}")
    for label, branch, session, paths in SWEEPS:
        with tempfile.TemporaryDirectory() as td:
            try:
                replay(Path(td), label, branch, session, paths)
            except Exception as e:  # noqa: BLE001
                check(label, False, f"raised {type(e).__name__}: {e}")
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
