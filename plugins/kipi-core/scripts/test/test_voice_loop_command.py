#!/usr/bin/env python3
"""Pins `/voice-loop` (ASK-2226): the hand-run door to the same review the hook runs.

TEST ISOLATION (fable-discipline): a stub `voiceloop` on a sealed PATH and a temp
corpus. Nothing here reads the founder's corpus or runs the real engine. The hook
the command imports its channel table from is the REAL one in this checkout, on
purpose: the property under test is that the two cannot disagree.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "plugins" / "kipi-core" / "scripts" / "voice-loop.py"


def _run(tmp_path, rel_path, *extra, rc=0, stdout="0 finding(s) against 5 exemplar(s)",
         project_dir=None):
    draft = tmp_path / rel_path
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("a draft\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = bin_dir / "argv.log"
    stub = bin_dir / "voiceloop"
    stub.write_text("#!/usr/bin/env bash\n"
                    f'echo "$*" > "{log}"\n'
                    f"cat <<'OUT'\n{stdout}\nOUT\n"
                    f"exit {rc}\n")
    stub.chmod(0o755)
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["VOICE_LOOP_CORPUS"] = str(corpus)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir is not None else REPO)
    r = subprocess.run([sys.executable, str(SCRIPT), str(draft), *extra],
                       capture_output=True, text=True, env=env, timeout=60)
    argv = log.read_text().split() if log.exists() else []
    return r, argv


def test_a_channel_path_runs_the_full_review(tmp_path):
    r, argv = _run(tmp_path, "outreach/linkedin-post-a.md")
    assert r.returncode == 0, r.stderr
    assert argv[:3] == ["review", "--channel", "linkedin"], argv


def test_it_agrees_with_the_hook_on_a_path_the_hook_maps_to_comment(tmp_path):
    """The command has no table of its own. If it did, this is the case it would drift on."""
    r, argv = _run(tmp_path, "outreach/linkedin-comment-to-dana.md")
    assert argv[:3] == ["review", "--channel", "comment"], argv


def test_no_channel_in_the_path_runs_score(tmp_path):
    r, argv = _run(tmp_path, "notes/plan.md")
    assert argv[:1] == ["score"], argv


def test_an_explicit_channel_overrides_the_path(tmp_path):
    r, argv = _run(tmp_path, "notes/plan.md", "--channel", "email")
    assert argv[:3] == ["review", "--channel", "email"], argv


def test_an_unknown_channel_is_refused_not_passed_through(tmp_path):
    """`voiceloop review` accepts any channel silently and falls back to generic rules."""
    r, argv = _run(tmp_path, "notes/plan.md", "--channel", "linkdin")
    assert r.returncode == 2
    assert argv == [], "the engine must not run on a typo'd channel"
    assert "linkdin" in r.stderr


def test_engine_output_and_exit_code_come_through_verbatim(tmp_path):
    r, _ = _run(tmp_path, "outreach/linkedin-post-a.md", rc=1,
                stdout="substance-fragment: 3 words\n1 finding(s) on channel linkedin against 9 exemplar(s)")
    assert r.returncode == 1
    assert "substance-fragment: 3 words" in r.stdout
    assert "review --channel linkedin" in r.stdout, "the header must say which engine ran"
    assert r.stdout.index("review --channel linkedin") < r.stdout.index("substance-fragment"), \
        "the header must come BEFORE the findings, not after them"


def test_a_missing_file_is_refused(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.md")],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(REPO)})
    assert r.returncode == 2
    assert "nope.md" in r.stderr


def test_an_instance_without_the_hook_says_so(tmp_path):
    """A missing table is NOT CHECKED, never a silent fall back to some default."""
    r, argv = _run(tmp_path, "outreach/linkedin-post-a.md", project_dir=tmp_path / "no-instance")
    assert r.returncode == 2
    assert argv == []
    assert "voiceloop-band-lint.py" in r.stderr
