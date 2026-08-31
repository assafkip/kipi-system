"""Every path that copies generic content into an instance runs the same gate.

`kipi update` is not a chokepoint. It is the BUSIEST of four:

- `kipi-new-instance.sh` seeds a fresh instance with settings-template.json,
  `.claude/{agents,output-styles,rules}/*.md`, `.mcp.json` and every plugin;
- `kipi-migrate.py` adds `q-system` to an existing repo;
- `build-template-repo.sh` copies the working tree into a distributable
  template that other people fork;
- `kipi-update.sh`, which is already gated.

A leak that cannot ride an update can still ride a `kipi new`, and a fresh
instance is the one nobody thinks to re-check.

Two properties, and the second is the one that survives contact with time:

1. Every DECLARED entry point calls the gate BEFORE its first copy. Position,
   not presence: an adversarial review of the updater moved its whole preflight
   inside the instance loop and every presence-based assertion still passed.
2. Nothing can quietly become a fifth entry point. Any repo-root script that
   contains a copy primitive must be declared here or carry a written
   exemption, so adding one forces a decision instead of a silent gap.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]

# The call every entry point must make before it copies anything.
GATE_CALL = re.compile(r"propagation-leak-gate\.py")

# Copy primitives. The first version anchored on the START of a line, which
# made every copy inside an `if`, a `for` or a function body invisible -- that
# is where most real copies live. It also missed `git archive` (the actual
# seeding copy), tar pipes, and the argv forms Python uses to shell out. A
# fixture with three undeclared copiers passed cleanly against it.
COPY_PRIMITIVE = re.compile(
    r"""(?:^|[;&|(]\s*|\$\(\s*|`\s*|=\s*)          # start of a statement
        \s*(?:cp|rsync|install|ditto|tar)\b        # shell copy commands
      | shutil\.(?:copytree|copy2?|copyfile)\b     # python copy calls
      | distutils\.[\w.]*copy_tree\b
      | os\.(?:link|replace)\b
      | git\s+(?:-C\s+\S+\s+)?(?:archive|subtree\s+add)\b   # git-based copies
      | ["'](?:cp|rsync|ditto|tar)["']             # argv forms: subprocess(["cp", ...])
    """,
    re.VERBOSE,
)

# For SHELL sources the match must begin at the start of the stripped line, or
# `echo "  ... (git archive)..."` reads as a copy. That mismatch let a mutation
# move the real seeding copy above the gate while the suite stayed green,
# because the first regex-visible "copy" was a log message.
# Bare `git` is NOT a copy: it matched `git init` at kipi-new-instance.sh:73,
# so the oracle was comparing the gate against a repo initialisation twenty
# lines above the real seed. Only the git subcommands that actually copy count.
SHELL_LEADING_COPY = re.compile(
    r"""^(?:cp|rsync|install|ditto|tar)\b
      | ^git\s+(?:-C\s+\S+\s+)?(?:archive|subtree\s+add)\b
    """,
    re.VERBOSE,
)

# path -> why it copies generic content into somewhere that fans out.
DECLARED_ENTRYPOINTS = {
    "kipi-update.sh": "syncs q-system, .claude config and plugins into 23 instances",
    "kipi-new-instance.sh": "seeds a fresh instance with the same generic content",
    "kipi-migrate.py": "adds q-system to an existing repo",
    "build-template-repo.sh": "copies the working tree into a forkable template",
}

# Repo-root scripts that contain a copy primitive but do NOT propagate generic
# content outward. Each needs a written reason; "it looked fine" is not one.
# Only scripts that ACTUALLY trip the copy check belong here. The first version
# listed five, three of which never tripped it at all: the list read as a
# reviewed inventory of five while only two were load-bearing, and a decorative
# entry is a claim nobody checked. The assertion at the bottom now keeps this
# honest in both directions as the regex is tightened.
EXEMPT = {
    "kipi-update-preserve-scan.py": "read-only: it inventories instance-only "
    "files for the updater and has no write path at all (the match is prose in "
    "its module docstring)",
    "test-kipi-update-preserve-integration.sh": "a test harness whose skeleton "
    "and destination are both synthetic fixtures under mktemp -d",
    "test-kipi-update-preserve-scan.sh": "a test harness for the same scanner; "
    "its copies are inside a throwaway temp fixture, not a real instance",
    # --- ASK-1145 -------------------------------------------------------
    # These eleven were always undeclared. Nobody added them since: this test
    # was declared `runner: python3` on a pytest module, so the capability gate
    # imported it and ran none of its cases. It has been red for as long as it
    # has existed. Each reason below names the line first_match() actually
    # returns, not an impression formed by reading the file.
    "kipi": "false positive: the match is the `install-jobs)` case label in the "
    "CLI dispatcher, which copies nothing and shells out to the real updater",
    "kipi-update-deletion-guard.py": "read-only guard; the match is prose in its "
    "module docstring describing what the updater does, same class as "
    "kipi-update-preserve-scan.py",
    "kipi-update-gitignore-block.py": "the match is os.replace(tmp, path), an "
    "atomic in-place rewrite of one file in the repo it runs in, never an "
    "outward copy into an instance",
    # --- PR #292 --------------------------------------------------------
    "kipi-update-voiceloop-migrate.py": "the match first_match() returns is the "
    "shutil.copy2(path, keep) at line 397, which writes a .pre-voiceloop.bak "
    "beside an UNTRACKED file in the instance being migrated, right before that "
    "file is rewritten in place. It is a same-directory backup so the rewrite is "
    "reversible for content version control never held, not an outward copy: "
    "this script only ever reads and writes inside the ONE instance it is "
    "pointed at, and has no skeleton source and no second destination. Same "
    "class as kipi-update-gitignore-block.py above, whose os.replace this file "
    "also carries",
    "test-kipi-update-bash32-empty-array.sh": "test harness; its cp -R source "
    "and destination are both synthetic fixtures under mktemp -d",
    "test-kipi-update-cache-exclusion.sh": "test harness; its cp -R source and "
    "destination are both synthetic fixtures under mktemp -d",
    "test-kipi-update-config-commit-unwind.sh": "test harness; it copies the "
    "updater into a throwaway skeleton fixture, never into an instance",
    "test-kipi-update-dataloss-guards.sh": "test harness; its cp -R source and "
    "destination are both synthetic fixtures under mktemp -d",
    "test-kipi-update-dirty-guard-scope.sh": "test harness; its cp -R source "
    "and destination are both synthetic fixtures under mktemp -d",
    "test-kipi-update-restore-recovers.sh": "test harness; the copy reads a "
    "scratch file out of its own temp fixture to assert restore worked",
    "test_destructive_op_deny_anchor.py": "test harness; shutil.copy puts the "
    "hook into a tmp dir so the copy can be patched and driven, which is "
    "exactly how it stays read-only on the real one",
    "test_fleet_unblock.py": "test harness; it copies one auditor into a "
    "synthetic skeleton fixture built under tmp_path",
}


def source_lines(name: str) -> list:
    return (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()


def is_comment(line: str, name: str) -> bool:
    stripped = line.strip()
    if name.endswith(".py"):
        return stripped.startswith("#")
    return stripped.startswith("#")


def first_match(name: str, pattern: re.Pattern) -> int | None:
    """1-based line number of the first real (non-comment) match."""
    for number, line in enumerate(source_lines(name), start=1):
        if is_comment(line, name):
            continue
        if pattern.search(line):
            return number
    return None


def first_shell_copy(name: str) -> int | None:
    """The first line whose STRIPPED text starts with a copy command.

    Anywhere-in-the-line matching made `echo "... (git archive)..."` read as a
    copy, so the oracle compared the gate against a log message.
    """
    for number, line in enumerate(source_lines(name), start=1):
        if is_comment(line, name):
            continue
        if SHELL_LEADING_COPY.match(line.strip()):
            return number
    return None


def is_script(path: Path) -> bool:
    """Any executable or shebang file, not just .sh/.py.

    The extensionless `kipi` dispatcher sat outside the old enumeration
    entirely, and so would any new extensionless copier.
    """
    if path.suffix in {".sh", ".py"}:
        return True
    if not path.stat().st_mode & 0o111:
        return False
    try:
        return path.read_bytes()[:2] == b"#!"
    except OSError:
        return False


def repo_root_scripts() -> list:
    return sorted(
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_file() and is_script(path)
    )


@pytest.mark.parametrize("name", sorted(DECLARED_ENTRYPOINTS))
def test_every_entrypoint_is_gated_before_it_copies(name):
    """The gate call must come BEFORE the first copy, not merely exist.

    Presence is not a property. The updater's own review moved its preflight
    into the instance loop -- after the chdir, after a .git lock deletion --
    and every presence-based check still passed.

    Source position is a valid oracle only where source order IS execution
    order, i.e. top-level shell. In Python a copy at line 260 lives in a
    function that runs after a gate call written at line 594, so the same
    comparison would be meaningless. Python entry points are held to the
    stronger behavioural test below instead.
    """
    gate_line = first_match(name, GATE_CALL)
    assert gate_line is not None, (
        f"{name} copies generic content into an instance and never calls the "
        f"propagation leak gate ({DECLARED_ENTRYPOINTS[name]})"
    )
    if name.endswith(".py"):
        return
    copy_line = first_shell_copy(name)
    if copy_line is None:
        return
    assert gate_line < copy_line, (
        f"{name} copies at line {copy_line} but gates at line {gate_line}: "
        "a leak is already out by then"
    )


@pytest.mark.parametrize("seeded", [False, True], ids=["fresh", "already-seeded"])
@pytest.mark.parametrize(
    "name", sorted(n for n in DECLARED_ENTRYPOINTS if n.endswith(".py"))
)
def test_every_python_entrypoint_aborts_before_copying(name, seeded, tmp_path):
    """Run it for real with a sabotaged gate and prove nothing was copied.

    A zero-byte gate is the sabotage because it is the one that passes in
    silence: a valid program that exits 0. If the entry point believes an exit
    code it never heard a verdict for, this run copies into the destination and
    the assertion below catches it.
    """
    skeleton = tmp_path / "skel"
    shutil.copytree(REPO_ROOT, skeleton, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".venv", "node_modules"))
    (skeleton / "q-system" / ".q-system" / "scripts"
     / "propagation-leak-gate.py").write_text("", encoding="utf-8")

    destination = tmp_path / "instance"
    destination.mkdir()
    if seeded:
        # A `if not isdir(q-system): <gate>` guard keeps a fresh-destination
        # test green while every REAL migration -- of an instance that already
        # has q-system/, which is all of them -- runs its copies ungated.
        (destination / "q-system").mkdir()
    before = sorted(path.name for path in destination.iterdir())

    result = subprocess.run(
        [sys.executable, str(skeleton / name), str(destination)],
        capture_output=True, text=True, timeout=300,
    )

    assert result.returncode != 0, (
        f"{name} ran to completion with a gutted gate:\n{result.stdout}"
    )
    assert "ABORT" in (result.stdout + result.stderr), (
        f"{name} stopped without saying why:\n{result.stdout}{result.stderr}"
    )
    assert sorted(path.name for path in destination.iterdir()) == before, (
        f"{name} copied into the destination before aborting"
    )


def test_every_entrypoint_fails_closed_on_a_missing_gate():
    """A deleted gate must abort, never be skipped.

    The `[ -f ... ]` shape reads as caution and behaves as a bypass: it turns a
    deleted gate into a green run, which is exactly the fan-out being guarded
    against.
    """
    for name in sorted(DECLARED_ENTRYPOINTS):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        skipped = re.search(
            r"if\s+\[\s+-f\s+\"?\$\{?[A-Z_]*LEAK[A-Z_]*\}?\"?\s+\]", text
        )
        assert skipped is None, (
            f"{name} wraps the leak gate in a [ -f ] existence guard, so "
            "deleting the gate makes the run pass"
        )


def test_no_undeclared_propagation_entrypoint_exists():
    """A fifth copier cannot appear without someone deciding it is safe.

    A hardcoded inventory rots silently. This fails the moment a repo-root
    script grows a copy primitive without being declared or exempted.
    """
    undeclared = [
        name
        for name in repo_root_scripts()
        if name not in DECLARED_ENTRYPOINTS
        and name not in EXEMPT
        and first_match(name, COPY_PRIMITIVE) is not None
    ]

    assert not undeclared, (
        "repo-root script(s) copy content but are neither declared as a "
        f"propagation entry point nor exempted with a reason: {undeclared}"
    )


def test_every_exemption_carries_a_reason():
    """An exemption without a written reason is a hole with a nicer name."""
    for name, reason in EXEMPT.items():
        assert (REPO_ROOT / name).is_file(), (
            f"{name} is exempted but no longer exists; drop the stale exemption"
        )
        assert len(reason.split()) >= 5, f"{name} has no real exemption reason"
        assert first_match(name, COPY_PRIMITIVE) is not None, (
            f"{name} is exempted but no longer trips the copy check; the list "
            "reads as a reviewed inventory, so a decorative entry is a lie"
        )
