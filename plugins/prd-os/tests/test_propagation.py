"""Regression test for the prd-os artifact propagation contract.

`kipi-update.sh` rsyncs `q-system/` from the skeleton repo into every
registered instance. The rsync excludes a fixed set of directories so each
instance can maintain instance-local state under those paths without being
overwritten by `kipi update`. The prd-os plugin depends on this exclusion:
`q-system/memory/working/prd-personas-baseline.md` is appended to by
`plugins/prd-os/scripts/phase0_measure.py` per-instance and would silently
break if the exclusion were ever removed.

This test reads the real `kipi-update.sh` from the repo root, locates the
rsync invocation that propagates `q-system/`, captures the contiguous flag
block, and asserts the three protected paths are excluded inside that
specific rsync block. A substring match on the script body alone would not
catch a refactor that left the flags present but disconnected from the
relevant propagation call; this test reads the rsync call as a structured
unit instead.

Exception to the standard fake_repo pattern: this test reads a real file
from the repo root (`kipi-update.sh`) rather than building an ephemeral
fixture under tmp_path. The read is read-only against a stable artifact;
no state mutation, no side effects.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "kipi-update.sh"

# kipi-update.sh lives at the skeleton repo root, not inside the portable
# plugin. In a standalone extraction of plugins/prd-os it is absent, so this
# whole module (which validates that skeleton propagation contract) skips
# rather than failing. In the kipi-system skeleton the script is present and
# the tests run.
pytestmark = pytest.mark.skipif(
    not UPDATE_SCRIPT.is_file(),
    reason="kipi-update.sh is a kipi-system skeleton artifact, absent in a portable extraction",
)

PROTECTED_EXCLUSIONS = ("memory/", "output/", "my-project/")


def _read_update_script() -> str:
    assert UPDATE_SCRIPT.is_file(), f"kipi-update.sh not found at {UPDATE_SCRIPT}"
    return UPDATE_SCRIPT.read_text()


def _extract_rsync_block(text: str) -> tuple[str, str]:
    """Return (block_text, source_arg) for the rsync that propagates q-system/.

    Finds the rsync line whose SOURCE argument (the first positional arg
    after `rsync` and any flags) ends in `q-system/` — anchoring to the
    source position prevents false positives from rsync calls where
    `q-system/` only appears in the destination path or in a flag value
    (addresses codex finding on issue prdos-propagation-regression-test).

    Walks forward across line-continuation backslashes to capture the full
    multi-line command. Returns the captured block plus the parsed source
    argument so callers can assert on it explicitly.
    """
    lines = text.splitlines()
    source_arg_re = re.compile(
        r"""rsync\b           # rsync command
            (?:\s+-[A-Za-z-]+)*   # short or long flags
            \s+
            (?P<source>"[^"]*q-system/"|'[^']*q-system/'|\S*q-system/)
        """,
        re.VERBOSE,
    )
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        match = source_arg_re.search(raw)
        if not match:
            continue
        source = match.group("source").strip("'\"")
        if not source.endswith("q-system/"):
            continue
        block_lines = [raw]
        j = i
        while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            block_lines.append(lines[j])
        return "\n".join(block_lines), source

    raise AssertionError(
        "no rsync call with q-system/ as the SOURCE argument found in "
        "kipi-update.sh"
    )


def test_kipi_update_script_exists():
    """Sanity: the script we're auditing is reachable from the test."""
    assert UPDATE_SCRIPT.is_file(), (
        f"kipi-update.sh missing at {UPDATE_SCRIPT}; "
        "the propagation regression test cannot run without it."
    )


def test_rsync_call_propagates_q_system():
    """The rsync invocation we audit must have q-system/ as its SOURCE
    argument, not just somewhere on the line. Anchoring to the source
    position prevents future refactors from silently moving the
    exclusions to a different rsync call.
    """
    text = _read_update_script()
    _, source = _extract_rsync_block(text)
    assert source.endswith("q-system/"), (
        f"rsync source argument must end with q-system/, got {source!r}"
    )


@pytest.mark.parametrize("path", PROTECTED_EXCLUSIONS)
def test_rsync_block_excludes_protected_path(path: str):
    """The rsync that propagates q-system/ must exclude each protected
    directory. This is the binding contract that lets prd-os append to
    files under memory/working/ without being clobbered by kipi update.

    The match is intentionally strict on shell-quoting form. Equivalent
    rsync forms like --exclude=memory/ or --exclude='memory/' are not
    treated as substitutes (per a deferred codex finding): the strictness
    forces any cosmetic change to the exclusion DSL to come through
    pytest, where the author can confirm the new form preserves the
    contract.
    """
    text = _read_update_script()
    block, _ = _extract_rsync_block(text)
    needle = f'--exclude="{path}"'
    assert needle in block, (
        f"protected exclusion {needle!r} not found in the rsync block "
        f"that propagates q-system/. Block:\n{block}"
    )
