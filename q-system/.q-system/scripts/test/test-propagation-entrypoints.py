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

# Copy primitives, matched as COMMANDS rather than as words, so prose in a
# comment or a docstring does not register as a copy.
COPY_PRIMITIVE = re.compile(
    r"""(?:^|[;&|]\s*|\$\(\s*|`\s*|=\s*)      # start of a statement
        (?:cp|rsync|install)\b                 # shell copy commands
      | shutil\.(?:copytree|copy2?|copyfile)\b # python copy calls
      | git\s+(?:archive|subtree\s+add)\b      # git-based copies
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
EXEMPT = {
    "kipi-push-upstream.sh": "copies INTO the skeleton from an instance, the "
    "opposite direction; nothing fans out",
    "kipi-rollback.sh": "restores an instance from its own backup, no skeleton "
    "content crosses",
    "kipi-update-preserve-scan.py": "inventories instance-only files for the "
    "updater; it is called BY a gated entry point and copies nothing outward",
    "kipi-settings-merge.py": "merges settings-template.json into one instance "
    "file; it is called BY kipi-update.sh after that gate has run",
    "test-kipi-update-preserve-integration.sh": "a test harness that builds "
    "throwaway fixtures in a temp dir; it propagates to no real instance",
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


def repo_root_scripts() -> list:
    return sorted(
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_file() and path.suffix in {".sh", ".py"}
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
    copy_line = first_match(name, COPY_PRIMITIVE)
    if copy_line is None:
        return
    assert gate_line < copy_line, (
        f"{name} copies at line {copy_line} but gates at line {gate_line}: "
        "a leak is already out by then"
    )


@pytest.mark.parametrize(
    "name", sorted(n for n in DECLARED_ENTRYPOINTS if n.endswith(".py"))
)
def test_every_python_entrypoint_aborts_before_copying(name, tmp_path):
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
