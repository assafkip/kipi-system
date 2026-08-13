#!/usr/bin/env python3
"""The retired-string sweep, and the tree it is supposed to keep clean (ASK-701).

why this exists (spillover sp-36788323): a retired positioning line survived
verbatim at `plugins/kipi-core/skills/founder-voice/references/voice-dna.md:55`.
Every retired-set sweep in the fleet only ever read pipeline prompt constants,
and that file is not on the pipeline path, so no sweep would ever have found it
-- while the voice DNA it sits in rides into drafts the publishing engine then
rejects for carrying the retired line.

The deterministic blocker is `scripts/retired-strings-sweep.py`, a script this
test suite runs; nothing here relies on guidance being read and obeyed.

Nothing here restates the retired strings. Every expectation is derived from the
data file that owns them (`retired-strings.json`) and from the word-count
threshold owned by `voicekit.echo` -- restating either would let the test agree
with a stale copy of itself.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
# Set in the mutant child only, so the entrypoint test does not spawn itself.
MUTANT_ENV = "KIPI_RETIRED_SWEEP_MUTANT"
SWEEP = REPO / "q-system" / ".q-system" / "scripts" / "retired-strings-sweep.py"
RETIRED_SET = REPO / "q-system" / ".q-system" / "scripts" / "retired-strings.json"


def run_sweep(*args):
    return subprocess.run(
        [sys.executable, str(SWEEP), *args],
        capture_output=True, text=True, cwd=str(REPO),
    )


def retired_entries():
    return json.loads(RETIRED_SET.read_text(encoding="utf-8"))["retired"]


def blocking_entries():
    """Entries the sweep must treat as blocking, derived the way the sweep
    derives them: word count against voicekit.echo.NGRAM. If the threshold moves,
    this moves with it."""
    sys.path.insert(0, str(REPO / "plugins" / "kipi-core"))
    from voicekit import echo  # noqa: PLC0415  (path must be set first)

    return [e for e in retired_entries() if len(echo._words(e["text"])) >= echo.NGRAM]


# --- the defect this issue exists for ------------------------------------

def test_founder_voice_references_carry_no_blocking_retired_string():
    """Acceptance 1: the named string appears nowhere under founder-voice/.

    Read from the data file, never typed here -- a literal in this test would
    keep passing after someone edited the retired set.
    """
    skill = REPO / "plugins" / "kipi-core" / "skills" / "founder-voice"
    bodies = {p: p.read_text(encoding="utf-8") for p in skill.rglob("*.md")}
    assert bodies, f"no skill references found under {skill}"

    hits = [
        f"{p.relative_to(REPO)} carries retired {entry['id']!r}"
        for entry in blocking_entries()
        for p, body in bodies.items()
        if entry["text"] in body
    ]
    assert hits == [], "retired copy still steering an auto-invoked skill: " + "; ".join(hits)


# --- the sweep itself -----------------------------------------------------

def test_sweep_covers_the_skill_references_glob():
    """Acceptance 2a: `plugins/*/skills/*/references/` is in the covered paths."""
    result = run_sweep("--show-paths")
    assert result.returncode == 0, result.stderr
    assert "plugins/*/skills/*/references/" in result.stdout, result.stdout


def test_sweep_is_green_on_the_real_tree():
    """Acceptance 2b: the sweep exits 0 on the cleaned tree."""
    result = run_sweep()
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_sweep_fails_when_a_retired_string_is_planted(tmp_path):
    """Acceptance 3, the negative self-test: a check that cannot go red for the
    reason we care about is decoration. Plant a blocking entry into a COPY of the
    tree (never the live one -- fable-discipline) and require a non-zero exit."""
    entry = blocking_entries()[0]
    tree = tmp_path / "tree"
    target = tree / "plugins" / "kipi-core" / "skills" / "founder-voice" / "references"
    target.mkdir(parents=True)
    (target / "voice-dna.md").write_text(
        f"# planted\n\n- \"{entry['text']}\"\n", encoding="utf-8"
    )
    shutil.copy(RETIRED_SET, tree / "retired-strings.json")

    result = run_sweep("--root", str(tree), "--retired-set", str(tree / "retired-strings.json"))
    assert result.returncode != 0, (
        "the sweep passed a tree containing a planted blocking retired string; "
        f"stdout={result.stdout}"
    )
    assert entry["id"] in result.stdout + result.stderr


def test_sweep_catches_a_retired_string_wrapped_across_lines(tmp_path):
    """The corpus this sweep guards is hard-wrapped prose, so a retired sentence
    normally STRADDLES a line break. A matcher that only ever looks at one physical
    line would miss the exact shape the corpus stores, and the gate would report
    green on the file it was built for. Split a blocking entry over two lines and
    require the sweep to still block."""
    entry = blocking_entries()[0]
    words = entry["text"].split()
    assert len(words) > 1, f"{entry['id']} is one word, cannot straddle a wrap"
    half = len(words) // 2
    wrapped = " ".join(words[:half]) + "\n" + " ".join(words[half:])

    tree = tmp_path / "tree"
    target = tree / "plugins" / "kipi-core" / "skills" / "founder-voice" / "references"
    target.mkdir(parents=True)
    (target / "voice-dna.md").write_text(
        f"# wrapped like the real corpus\n\n{wrapped}\n", encoding="utf-8"
    )
    shutil.copy(RETIRED_SET, tree / "retired-strings.json")

    result = run_sweep("--root", str(tree), "--retired-set", str(tree / "retired-strings.json"))
    assert result.returncode != 0, (
        "a retired string wrapped across two lines walked past the sweep; every "
        f"reference file in the corpus is wrapped this way. stdout={result.stdout}"
    )
    assert entry["id"] in result.stdout + result.stderr


def test_running_this_file_as_a_script_actually_runs_its_tests(tmp_path):
    """The capability gate runs a `runner: python3` entry as `python3 <file>`
    (capability-gate.py:423). A pytest-only module run that way DEFINES its tests,
    calls none of them, and exits 0 -- registered, green, and enforcing nothing.

    Proven against a copy, not against this file's own exit code: write a mutant
    sibling carrying a test that cannot pass, run it the way the gate would, and
    require a non-zero exit. The mutant lives in this directory so `parents[3]`
    resolves to the same repo; it is `_`-prefixed so a normal pytest run skips it.
    """
    if os.environ.get(MUTANT_ENV):
        pytest.skip("running inside the mutant child; the guard stops the recursion")

    mutant = Path(__file__).resolve().parent / "_retired_sweep_entrypoint_mutant.py"
    mutant.write_text(
        Path(__file__).read_text(encoding="utf-8")
        + "\n\ndef test_planted_failure():\n"
        + "    assert False, 'planted so the run has something to report'\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, str(mutant)],
            capture_output=True, text=True, cwd=str(REPO),
            env={**os.environ, MUTANT_ENV: "1"},
        )
    finally:
        mutant.unlink(missing_ok=True)

    assert result.returncode != 0, (
        "`python3 <this file>` exited 0 on a copy containing a failing test, so the "
        "capability manifest entry runs nothing and the sweep is unenforced; "
        f"stdout={result.stdout[-400:]}"
    )


def test_warn_tier_does_not_block(tmp_path):
    """A 2-word retired phrase is warn tier: reported, never a red build. Without
    this the sweep would fire on every ordinary use of a short phrase and get
    switched off, which is how a gate stops protecting anything."""
    warn = [e for e in retired_entries() if e not in blocking_entries()]
    if not warn:
        pytest.skip("no warn-tier entries in the retired set")

    tree = tmp_path / "tree"
    target = tree / "plugins" / "kipi-core" / "skills" / "founder-voice" / "references"
    target.mkdir(parents=True)
    (target / "voice-dna.md").write_text(f"{warn[0]['text']} shows up here.\n", encoding="utf-8")
    shutil.copy(RETIRED_SET, tree / "retired-strings.json")

    result = run_sweep("--root", str(tree), "--retired-set", str(tree / "retired-strings.json"))
    assert result.returncode == 0, result.stdout
    assert warn[0]["id"] in result.stdout, result.stdout


if __name__ == "__main__":
    # REQUIRED, not decoration. capability-gate.py:423 runs a `runner: python3`
    # entry as `python3 <file>`, so a pytest-only module would define its tests,
    # call none of them, and exit 0 -- registered, green, enforcing nothing.
    # test_running_this_file_as_a_script_actually_runs_its_tests is what holds
    # this line: delete the block and that test goes red against a mutant copy.
    sys.exit(pytest.main([__file__, "-q"]))
